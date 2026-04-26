# =============================================================================
# data/options_fetcher.py — Fetch options chains + calculate IV Rank
#
# WHAT CHANGED IN THIS VERSION
# ─────────────────────────────
# Added real_iv: the implied volatility back-solved from the ATM options chain
# using Black-Scholes inversion (Newton-Raphson + bisection fallback).
#
# WHY REAL IV IS BETTER THAN THE PROXY
# ──────────────────────────────────────
# The old proxy used 30-day rolling realised volatility on close prices.
# That measures what volatility *was* over the past month.
# Real IV is *forward-looking* — it's the market's consensus forecast of
# future volatility embedded in the option price right now.  The gap between
# the two (IV - realised vol = the "volatility risk premium") is itself a
# useful signal.
#
# HOW THE IV INVERSION WORKS
# ──────────────────────────
# Given: market_price (bid/ask midpoint of ATM contract)
# Find:  sigma such that Black-Scholes(sigma) == market_price
#
# Step 1 — Newton-Raphson:
#   sigma_next = sigma - (BS(sigma) - market_price) / vega(sigma)
#   where vega = dBS/dsigma = S * sqrt(T) * N'(d1)
#   Fast (~5 iterations), but can diverge on deep ITM/OTM or near-zero vega.
#
# Step 2 — Bisection fallback (if Newton diverges):
#   Binary search on [0.001, 10.0] — guaranteed to converge in 50 iterations.
#
# IV RANK WITH REAL IV
# ─────────────────────
# IV Rank = (real_iv - proxy_52w_low) / (proxy_52w_high - proxy_52w_low)
# We use the proxy's 52-week range as the denominator because free data sources
# don't provide historical IV.  This is the industry-standard workaround when
# a historical IV feed is unavailable.  The key insight: realised vol and IV
# are highly correlated over long windows, so the proxy range is a good
# approximation of where IV "normally" sits.
#
# OUTPUT SCHEMA
# ─────────────
# ticker, fetch_date, expiration, contractSymbol, strike, option_type,
# lastPrice, bid, ask, impliedVolatility, volume, openInterest, inTheMoney,
# real_iv, current_iv_proxy, iv_52w_high, iv_52w_low, iv_rank, iv_rank_pct,
# iv_rank_label
# =============================================================================

import os
import sys
import math
import datetime
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

warnings.filterwarnings("ignore", category=FutureWarning)


# ===========================================================================
# Black-Scholes pricer and IV back-solver
# ===========================================================================

def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf — no scipy needed."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_price(S: float, K: float, r: float,
              sigma: float, T: float, opt_type: str) -> float:
    """
    Black-Scholes European option price (per share).
    Returns intrinsic value when T <= 0 or sigma <= 0.
    """
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0) if opt_type == "call" else max(K - S, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    if opt_type == "call":
        return max(S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2), 0.0)
    else:
        return max(K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1), 0.0)


def _bs_vega(S: float, K: float, r: float,
             sigma: float, T: float) -> float:
    """
    d(BS price)/d(sigma) — same formula for calls and puts.
    Used as the Newton-Raphson step denominator.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    return S * sqrt_T * _norm_pdf(d1)


def _bisection_iv(target_price: float, S: float, K: float,
                  r: float, T: float, opt_type: str,
                  lo: float = 0.001, hi: float = 10.0,
                  iterations: int = 60) -> float | None:
    """
    Find implied vol via binary search.  Guaranteed to converge but slower
    than Newton-Raphson.  Used as a fallback.
    """
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        price = _bs_price(S, K, r, mid, T, opt_type)
        if abs(price - target_price) < 1e-6:
            return mid
        if price < target_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0   # best estimate after max iterations


def implied_vol(
    market_price: float,
    S: float,
    K: float,
    r: float,
    T: float,
    opt_type: str,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> float | None:
    """
    Back-solve Black-Scholes for the implied volatility (sigma) given a
    market option price.

    Algorithm:
      1. Start with the Brenner-Subrahmanyam ATM approximation as sigma_0
      2. Apply Newton-Raphson: sigma -= (BS(sigma) - price) / vega(sigma)
      3. If Newton diverges (vega too small, or sigma leaves [0.001, 10.0]),
         fall back to bisection search

    Parameters
    ----------
    market_price : observed option price (bid/ask midpoint)
    S            : current stock price
    K            : strike price
    r            : risk-free rate (annual, continuous)
    T            : time to expiry in years
    opt_type     : 'call' or 'put'

    Returns
    -------
    float  – annualised implied volatility as a decimal (e.g. 0.28 = 28%)
    None   – if the price is below intrinsic value (no IV solution exists)
    """
    if T <= 0 or S <= 0 or K <= 0:
        return None

    # Intrinsic value — if market price is below this, IV has no solution
    intrinsic = max(S - K, 0.0) if opt_type == "call" else max(K - S, 0.0)
    if market_price <= intrinsic + 1e-8:
        return None

    # Brenner-Subrahmanyam initial estimate (good for near-ATM options)
    # sigma_0 ≈ sqrt(2π/T) × (C/S)
    sigma = min(max(math.sqrt(2.0 * math.pi / T) * (market_price / S), 0.001), 5.0)

    # Newton-Raphson
    for _ in range(max_iter):
        price = _bs_price(S, K, r, sigma, T, opt_type)
        vega  = _bs_vega(S, K, r, sigma, T)
        diff  = price - market_price

        if abs(diff) < tol:
            return round(sigma, 6)

        if vega < 1e-10:
            # Vega too small — Newton will overshoot; use bisection instead
            break

        sigma -= diff / vega
        # Keep sigma in a physically sensible range
        sigma = min(max(sigma, 0.001), 10.0)

    # Bisection fallback
    return _bisection_iv(market_price, S, K, r, T, opt_type)


# ===========================================================================
# Historical volatility (proxy) helpers — unchanged from v1
# ===========================================================================

def _compute_rolling_vol(ticker: str, window: int = 30) -> pd.Series:
    """
    Download 1y of daily closes for `ticker` and return a Series of
    annualised rolling `window`-day realised volatility.
    """
    stock = yf.Ticker(ticker)
    hist  = stock.history(period="1y", auto_adjust=True)
    if hist.empty:
        raise ValueError(f"No price history returned for {ticker}.")
    log_returns  = np.log(hist["Close"] / hist["Close"].shift(1)).dropna()
    rolling_vol  = log_returns.rolling(window=window).std() * np.sqrt(252)
    return rolling_vol.dropna()


def calculate_iv_rank(
    ticker: str,
    window: int = 30,
    real_iv: float = None,
) -> dict:
    """
    Compute IV Rank and related statistics for `ticker`.

    Parameters
    ----------
    ticker  : stock symbol
    window  : rolling vol window (days)
    real_iv : if provided, use this as the current IV in the rank formula
              instead of the proxy.  The 52-week range still comes from the
              proxy because we have no historical real IV series.

    Returns
    -------
    dict with keys:
        current_iv_proxy  – most recent proxy (rolling realised vol)
        real_iv           – real IV from options chain (None if not provided)
        iv_52w_high/low   – from proxy series
        iv_rank           – (current - low) / (high - low) using real_iv if set
        iv_rank_pct       – as percentage
        iv_rank_label     – human-readable zone
    """
    rolling_vol = _compute_rolling_vol(ticker, window=window)

    proxy_current = float(rolling_vol.iloc[-1])
    iv_52w_high   = float(rolling_vol.max())
    iv_52w_low    = float(rolling_vol.min())

    # Use real_iv as the numerator if available; fall back to proxy
    current_for_rank = real_iv if real_iv is not None else proxy_current

    iv_range = iv_52w_high - iv_52w_low
    if iv_range < 1e-8:
        iv_rank = 0.5
    else:
        iv_rank = (current_for_rank - iv_52w_low) / iv_range

    iv_rank = float(np.clip(iv_rank, 0.0, 1.0))

    if iv_rank >= config.SIGNAL_PARAMS["high_iv_rank_threshold"]:
        label = "HIGH (options expensive - consider selling premium)"
    elif iv_rank <= config.SIGNAL_PARAMS["low_iv_rank_threshold"]:
        label = "LOW (options cheap - consider buying premium)"
    else:
        label = "NEUTRAL"

    return {
        "current_iv_proxy": round(proxy_current, 4),
        "real_iv":          round(real_iv, 4) if real_iv is not None else None,
        "iv_52w_high":      round(iv_52w_high, 4),
        "iv_52w_low":       round(iv_52w_low, 4),
        "iv_rank":          round(iv_rank, 4),
        "iv_rank_pct":      round(iv_rank * 100, 1),
        "iv_rank_label":    label,
    }


# ===========================================================================
# Options chain + ATM real IV extraction
# ===========================================================================

RISK_FREE_RATE = 0.045  # used for BS inversion; update if rates change


def _get_near_term_expiration(ticker_obj: yf.Ticker) -> str | None:
    """Return nearest expiration >= 7 DTE (avoids pin-risk distortion)."""
    expirations = ticker_obj.options
    if not expirations:
        return None
    today = datetime.date.today()
    for exp_str in expirations:
        if (datetime.date.fromisoformat(exp_str) - today).days >= 7:
            return exp_str
    return expirations[1] if len(expirations) > 1 else expirations[0]


def _compute_atm_real_iv(
    chain_df: pd.DataFrame,
    current_price: float,
    expiration: str,
) -> float | None:
    """
    Back-solve for the ATM implied volatility from the live options chain.

    Strategy:
      1. Find the single call and put with the strike closest to `current_price`
      2. Require both bid and ask > 0 (filters stale/illiquid contracts)
      3. Use (bid + ask) / 2 as the market price for BS inversion
      4. Average the IV from the call and the put to cancel skew bias

    Returns None if no valid ATM contracts are found.
    """
    today   = datetime.date.today()
    exp_dt  = datetime.date.fromisoformat(expiration)
    T       = max((exp_dt - today).days, 1) / 365.0

    ivs = []
    for opt_type in ("call", "put"):
        subset = chain_df[chain_df["option_type"] == opt_type].copy()
        # Only liquid, two-sided markets
        subset = subset[(subset["bid"] > 0) & (subset["ask"] > 0)]
        if subset.empty:
            continue

        # ATM strike = the one with smallest absolute distance to current price
        subset = subset.copy()
        subset["dist"] = (subset["strike"] - current_price).abs()
        atm_row = subset.loc[subset["dist"].idxmin()]

        mid_price = (float(atm_row["bid"]) + float(atm_row["ask"])) / 2.0
        K         = float(atm_row["strike"])

        iv = implied_vol(mid_price, current_price, K,
                         RISK_FREE_RATE, T, opt_type)
        if iv is not None and 0.01 <= iv <= 5.0:
            ivs.append(iv)

    if not ivs:
        return None

    return round(sum(ivs) / len(ivs), 4)   # average call IV and put IV


def fetch_options_chain(ticker: str, save: bool = True) -> pd.DataFrame:
    """
    Fetch the options chain for `ticker`, compute both proxy IV and real IV,
    and enrich every row with IV Rank data.

    Returns
    -------
    pd.DataFrame  – combined calls + puts, one row per contract.
    """
    print(f"[options_fetcher] Fetching options chain for {ticker}...")

    stock      = yf.Ticker(ticker)
    expiration = _get_near_term_expiration(stock)

    if expiration is None:
        print(f"[options_fetcher] No options data available for {ticker}.")
        return pd.DataFrame()

    print(f"[options_fetcher] Using expiration: {expiration}")

    chain  = stock.option_chain(expiration)
    calls  = chain.calls.copy(); calls["option_type"] = "call"
    puts   = chain.puts.copy();  puts["option_type"]  = "put"
    df     = pd.concat([calls, puts], ignore_index=True)

    keep_cols = [c for c in [
        "contractSymbol", "strike", "option_type",
        "lastPrice", "bid", "ask",
        "impliedVolatility", "volume", "openInterest", "inTheMoney",
    ] if c in df.columns]
    df = df[keep_cols].copy()

    df.insert(0, "ticker",     ticker)
    df.insert(1, "fetch_date", datetime.date.today().isoformat())
    df.insert(2, "expiration", expiration)

    # ------------------------------------------------------------------
    # Get current price for ATM selection (use fast_info to avoid extra download)
    # ------------------------------------------------------------------
    try:
        current_price = float(stock.fast_info["lastPrice"])
    except Exception:
        # Fallback: median of ATM strikes
        current_price = float(df["strike"].median())

    # ------------------------------------------------------------------
    # Real IV from options chain (back-solved via Black-Scholes inversion)
    # ------------------------------------------------------------------
    real_iv = None
    print(f"[options_fetcher] Back-solving ATM real IV for {ticker}...")
    try:
        real_iv = _compute_atm_real_iv(df, current_price, expiration)
        if real_iv is not None:
            print(f"[options_fetcher] ATM real IV: {real_iv:.2%}")
        else:
            print(f"[options_fetcher] ATM real IV: could not solve (using proxy only)")
    except Exception as e:
        print(f"[options_fetcher] WARNING: real IV calculation failed: {e}")

    # ------------------------------------------------------------------
    # IV Rank — uses real_iv as numerator if available, proxy 52w range as bounds
    # ------------------------------------------------------------------
    print(f"[options_fetcher] Calculating IV Rank for {ticker}...")
    try:
        iv_stats = calculate_iv_rank(ticker, real_iv=real_iv)
        for key, value in iv_stats.items():
            df[key] = value
    except Exception as e:
        print(f"[options_fetcher] WARNING: IV Rank calculation failed: {e}")
        for col in ["real_iv", "current_iv_proxy", "iv_52w_high", "iv_52w_low",
                    "iv_rank", "iv_rank_pct", "iv_rank_label"]:
            df[col] = None

    print(f"[options_fetcher] Chain: {len(df)} contracts "
          f"({len(calls)} calls, {len(puts)} puts).")

    if save:
        _save(df, ticker)

    return df


def _save(df: pd.DataFrame, ticker: str) -> str:
    raw_dir  = os.path.join(os.path.dirname(__file__), "raw")
    os.makedirs(raw_dir, exist_ok=True)
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    filepath = os.path.join(raw_dir, f"options_{ticker}_{date_str}.csv")
    df.to_csv(filepath, index=False)
    print(f"[options_fetcher] Saved -> {filepath}")
    return filepath


def fetch_all_tickers(tickers: list = None, **kwargs) -> dict[str, pd.DataFrame]:
    if tickers is None:
        tickers = config.TICKERS
    return {t: fetch_options_chain(t, **kwargs) for t in tickers}


# ---------------------------------------------------------------------------
# Smoke test — prints proxy vs real IV comparison for AAPL
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    df = fetch_options_chain("AAPL")

    if not df.empty:
        row = df.iloc[0]

        print("\n" + "=" * 52)
        print("  IV COMPARISON: PROXY vs REAL (AAPL)")
        print("=" * 52)

        proxy = row.get("current_iv_proxy")
        real  = row.get("real_iv")
        rank  = row.get("iv_rank")
        rank_pct = row.get("iv_rank_pct")

        print(f"  Proxy IV (30d realised vol)  : "
              f"{float(proxy):.2%}" if proxy is not None else "  Proxy IV: N/A")
        print(f"  Real IV  (ATM back-solved)   : "
              f"{float(real):.2%}"  if real  is not None else "  Real IV:  N/A")

        if proxy is not None and real is not None:
            vrp = float(real) - float(proxy)
            print(f"  Vol risk premium (real-proxy): {vrp:+.2%}  "
                  f"({'premium elevated' if vrp > 0 else 'premium depressed'})")

        print(f"\n  IV Rank (using real IV if available):")
        print(f"    {float(rank_pct):.1f}%  [{row.get('iv_rank_label')}]")
        print(f"    52w range: {float(row['iv_52w_low']):.2%} to {float(row['iv_52w_high']):.2%}")

        print("\n--- ATM contracts (nearest 6 strikes) ---")
        display = ["strike", "option_type", "bid", "ask",
                   "impliedVolatility", "volume"]
        display = [c for c in display if c in df.columns]
        # Sort by distance from the mid-strike
        mid_strike = df["strike"].median()
        df_sorted  = df.assign(_dist=(df["strike"] - mid_strike).abs()).sort_values("_dist")
        print(df_sorted[display].head(6).to_string(index=False))

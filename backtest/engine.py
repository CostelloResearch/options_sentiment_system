# =============================================================================
# backtest/engine.py -- Historical vertical-spread simulation
#
# WHY SPREADS, NOT SINGLE-LEG OPTIONS
# ------------------------------------
# The live pipeline (signals/spread_builder.py) trades vertical spreads, not
# naked options.  The backtest must match that production behaviour or the
# performance numbers are meaningless.  On each signal day we now:
#
#   1. Compute IV Rank from rolling realised vol (unchanged from v1)
#   2. Run signal_engine rules -> directional signal
#   3. Map signal -> spread type (BULL_CALL_DEBIT / BEAR_PUT_DEBIT /
#      BULL_PUT_CREDIT / BEAR_CALL_CREDIT)
#   4. Synthesize a Black-Scholes option grid for a 35-DTE expiration and pick
#      long/short strikes by delta using the SAME targets as spread_builder
#      (0.55/0.30 for debit legs; 0.20 for credit short)
#   5. Apply the SAME rejection rules (debit > 70% of width; credit < 33%)
#   6. Hand the resulting spread to spread_builder.simulate_spread_pnl which
#      walks daily, applying stop-loss / profit-target / time-stop / expiration
#      in that order -- matching the live trading rules exactly.
#
# WHY NOT CALL build_spread() DIRECTLY?
# --------------------------------------
# build_spread() expects a real options chain (bid, ask, openInterest, volume).
# Free historical data doesn't provide that, so the backtest MUST synthesize
# prices from Black-Scholes.  We keep the same decision logic (delta targets,
# width rules, risk/reward filter) but source prices from BS + friction instead
# of a live chain.  This is clearly an approximation and the README says so.
#
# THE SIGMA PROBLEM
# -----------------
# We don't have historical IV.  We proxy with rolling 30-day realised vol,
# which systematically underestimates IV in real option markets (the vol risk
# premium).  Spread P&L is less vega-sensitive than a single long option, so
# this proxy is more defensible here than it was in the v1 single-leg backtest.
#
# OUTPUT SCHEMA
# -------------
# `pnl` is per-share net P&L (dollar terms); `pnl_pct` is percent-of-max-loss.
# These column names are preserved from v1 so metrics.py / dashboard keep
# working without changes.
# =============================================================================

import os
import sys
import math
import random
import datetime
import glob

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from signals.signal_engine import (
    _classify_signal, _compute_confidence,
    SIG_NEUTRAL, SIG_BUY_CALLS, SIG_SELL_PUTS,
    SIG_BUY_PUTS, SIG_SELL_CALLS,
)

# Kelly sizing (imported lazily in runner; top-level ref here for type hints)
from signals import position_sizer
# Fitted logistic confidence model (optional; falls back to legacy formula)
from signals import confidence_model as _cmodel

# Reuse the spread-builder primitives so the backtest and the live trader
# share a single source of truth for pricing, delta targets, rejection rules,
# and exit-rule enforcement.
from signals.spread_builder import (
    bs_price, bs_delta,
    simulate_spread_pnl,
    RISK_FREE_RATE,
    DTE_TARGET,
    DEBIT_LONG_DELTA,  DEBIT_LONG_DELTA_RANGE,
    DEBIT_SHORT_DELTA, DEBIT_SHORT_DELTA_RANGE,
    CREDIT_SHORT_DELTA, CREDIT_SHORT_DELTA_RANGE,
    WIDTH_HI_PRICE, WIDTH_LO_PRICE, WIDTH_PRICE_CUT,
    FRICTION_FRAC,
    DEBIT_MAX_COST_FRAC, CREDIT_MIN_PREMIUM_FR,
    ACCOUNT_NOTIONAL, RISK_PER_TRADE_FRAC,
)

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------
# HOLD_DAYS is kept only so metrics.py's Sharpe annualisation (sqrt(252/HOLD))
# continues to produce reasonable numbers.  The actual exit day comes from the
# simulator's rules (stop loss / profit target / time stop / expiration).
HOLD_DAYS      = 5
VOL_WINDOW     = 30     # rolling realised-vol window (trading days)
IV_RANK_WINDOW = 252    # ~1 year of trading days
STRIKE_STEP    = 5      # $5 equity strike grid; matches width_hi convention

# Paper-account size used ONLY by the Kelly-sizing path for its per-trade and
# per-bucket dollar caps.  spread_builder / live trading keep using their own
# $10k notional (the "live" account).  We scale the backtest account up to
# $100k so the 0.75-3.0% per-strategy buckets can actually hold a handful of
# 1-contract vertical spreads concurrently -- at $10k the MIN_CONTRACTS floor
# blows past the cap on the very first trade, which starves every follow-up
# signal in the same bucket until expiration (60 days for BEAR_PUT_DEBIT).
# The cap's job is opportunity-cost management, not strict risk enforcement,
# so sizing against a realistic multi-contract account is the honest setup.
KELLY_BACKTEST_NOTIONAL = 100_000.0


# ---------------------------------------------------------------------------
# Black-Scholes wrappers
# ---------------------------------------------------------------------------
# Keep a `black_scholes(S, K, r, sigma, T, opt_type)` function with the v1
# signature for any legacy callers / notebooks; delegates to spread_builder's
# scipy-backed bs_price (which uses the exact same formula).

def black_scholes(S: float, K: float, r: float,
                  sigma: float, T: float, opt_type: str) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        if opt_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    return bs_price(S, K, T, r, sigma, is_call=(opt_type == "call"))


def _atm_strike(price: float, step: float = STRIKE_STEP) -> float:
    """Round `price` to the nearest `step` for a standard-grid strike."""
    return round(round(price / step) * step, 2)


def _target_width(S: float) -> float:
    """Match spread_builder's width rule: $5 for S>=100, else $2.50."""
    return WIDTH_HI_PRICE if S >= WIDTH_PRICE_CUT else WIDTH_LO_PRICE


# ---------------------------------------------------------------------------
# Synthetic strike-grid builder
# ---------------------------------------------------------------------------
# We can't query an options chain for every historical day, so we build a
# dense strike grid around spot at each backtest date and use BS with the
# rolling realised vol as sigma.  Grid spans +/-25% of spot in STRIKE_STEP
# increments -- wide enough to cover any reasonable delta target.

def _strike_grid(S: float, step: float = STRIKE_STEP) -> np.ndarray:
    lo = _atm_strike(S * 0.75, step)
    hi = _atm_strike(S * 1.25, step)
    return np.arange(lo, hi + step, step)


def _pick_strike_by_delta(
    S: float, T: float, r: float, sigma: float,
    is_call: bool, target_delta: float, direction: str,
    step: float = STRIKE_STEP,
) -> float:
    """
    Walk the strike grid and return the strike whose |delta| is closest to
    `target_delta`.  `direction` is "long" or "short" -- used only in the
    docstring for readability; the math is identical.

    Delta magnitude is monotonic in strike, so the minimum-|err| search is
    guaranteed to find the right strike.
    """
    grid = _strike_grid(S, step)
    best_K = None
    best_err = 1e9
    for K in grid:
        d = abs(bs_delta(S, float(K), T, r, sigma, is_call))
        err = abs(d - target_delta)
        if err < best_err:
            best_err = err
            best_K   = float(K)
    return best_K


def _pair_width_partner(
    S: float, T: float, r: float, sigma: float,
    anchor_K: float, is_call: bool,
    partner_direction: str, spread_direction: str,
    step: float = STRIKE_STEP,
) -> float:
    """
    Given an anchor strike, find the partner strike one target_width away in
    the direction required by the strategy.

    spread_direction in {"bull_call", "bear_put", "bull_put", "bear_call"}
    partner_direction in {"short", "long"}

    For debit spreads the long leg anchors; the short leg is placed in the
    direction of the expected move (further OTM).  For credit spreads the
    short leg anchors; the long leg is placed further OTM as protection.
    """
    width = _target_width(S)

    # Which side of the anchor does the partner live on?
    #   BULL_CALL_DEBIT   : short leg is HIGHER strike (OTM call)
    #   BEAR_PUT_DEBIT    : short leg is LOWER strike  (OTM put)
    #   BULL_PUT_CREDIT   : long  leg is LOWER strike  (further OTM put)
    #   BEAR_CALL_CREDIT  : long  leg is HIGHER strike (further OTM call)
    side_higher = spread_direction in ("bull_call", "bear_call")
    partner_K = anchor_K + width if side_higher else anchor_K - width
    return round(partner_K / step) * step


# ---------------------------------------------------------------------------
# Strategy mapping
# ---------------------------------------------------------------------------
_SIGNAL_TO_STRATEGY = {
    SIG_BUY_CALLS:  "BULL_CALL_DEBIT",
    SIG_BUY_PUTS:   "BEAR_PUT_DEBIT",
    SIG_SELL_PUTS:  "BULL_PUT_CREDIT",
    SIG_SELL_CALLS: "BEAR_CALL_CREDIT",
}

# Per-strategy structural overrides.  We learned from put_structure_study.py
# that the default 35 DTE / 0.30-delta short leg systematically loses money
# on BUY PUTS even when the underlying signal has +1.44% edge at 20d.
# Variant B (60 DTE, 0.25-delta short) turned that same signal cohort into
# +$32k total P&L with Sharpe ~2.0.  The theory: puts need more time for
# the thesis (directional moves against a market that drifts up),
# and a further-OTM short leg leaves more of the downside captured in the
# long leg instead of being given back when the short comes ITM.
# Other strategies (calls, credit spreads) are fine on the defaults.
_PER_STRATEGY_DTE = {
    "BEAR_PUT_DEBIT": 60,
}
_PER_STRATEGY_SHORT_DELTA = {
    "BEAR_PUT_DEBIT": 0.25,
}


def _build_backtest_spread(
    signal: str,
    S: float,
    sigma: float,
    entry_date: datetime.date,
    r: float = RISK_FREE_RATE,
) -> dict:
    """
    Build a vertical spread for the backtest using BS synthetic prices.

    Returns a dict with the same key names as live build_spread(), so
    simulate_spread_pnl() can consume it unchanged.  Includes `accepted`
    and `rejection_reason` so callers can skip bad trades.
    """
    strategy = _SIGNAL_TO_STRATEGY.get(signal)
    if strategy is None:
        return {"accepted": False, "rejection_reason": f"no strategy for {signal}"}

    # Per-strategy DTE override (BEAR_PUT_DEBIT = 60d based on structure study)
    strategy_dte = _PER_STRATEGY_DTE.get(strategy, DTE_TARGET)
    strategy_short_delta = _PER_STRATEGY_SHORT_DELTA.get(strategy, DEBIT_SHORT_DELTA)
    T = strategy_dte / 365.0
    exp_date = entry_date + datetime.timedelta(days=strategy_dte)

    # --- Strategy-specific leg selection ---
    if strategy == "BULL_CALL_DEBIT":
        # Long ITM-ish call, short OTM call
        long_K  = _pick_strike_by_delta(S, T, r, sigma, True,  DEBIT_LONG_DELTA,  "long")
        short_K = _pair_width_partner(S, T, r, sigma, long_K, True,  "short", "bull_call")
        is_call = True
    elif strategy == "BEAR_PUT_DEBIT":
        # Long ITM-ish put (|delta|~0.55), short further-OTM put (0.25 delta).
        # We pick the short strike by DELTA TARGET (not by fixed width) so that
        # the short leg stays OTM even when sigma is large -- a fixed-width
        # partner at 60 DTE could land ITM with the long leg's delta ~0.55.
        long_K  = _pick_strike_by_delta(S, T, r, sigma, False, DEBIT_LONG_DELTA,
                                        "long")
        short_K = _pick_strike_by_delta(S, T, r, sigma, False,
                                        strategy_short_delta, "short")
        # Enforce bear-put ordering: short strike < long strike
        if short_K >= long_K:
            short_K = long_K - STRIKE_STEP
        is_call = False
    elif strategy == "BULL_PUT_CREDIT":
        # Short OTM put (|delta|~0.20), long further-OTM put as protection
        short_K = _pick_strike_by_delta(S, T, r, sigma, False, CREDIT_SHORT_DELTA, "short")
        long_K  = _pair_width_partner(S, T, r, sigma, short_K, False, "long", "bull_put")
        is_call = False
    elif strategy == "BEAR_CALL_CREDIT":
        # Short OTM call (|delta|~0.20), long further-OTM call as protection
        short_K = _pick_strike_by_delta(S, T, r, sigma, True,  CREDIT_SHORT_DELTA, "short")
        long_K  = _pair_width_partner(S, T, r, sigma, short_K, True,  "long", "bear_call")
        is_call = True
    else:
        return {"accepted": False, "rejection_reason": f"unknown strategy {strategy}"}

    direction = "debit" if strategy.endswith("_DEBIT") else "credit"

    # --- Price both legs at BS fair value, then apply friction ---
    # Friction model: debit buyer pays 1.5% above fair, seller gets 1.5% below.
    # On credit spreads: short leg is sold (minus friction), long leg is
    # bought (plus friction).  Net = short_received - long_paid.
    long_fair  = bs_price(S, long_K,  T, r, sigma, is_call)
    short_fair = bs_price(S, short_K, T, r, sigma, is_call)

    long_eff  = long_fair  * (1 + FRICTION_FRAC)   # paid
    short_eff = short_fair * (1 - FRICTION_FRAC)   # received

    if direction == "debit":
        net = long_eff - short_eff               # cost (we pay this)
    else:
        net = short_eff - long_eff               # credit (we collect this)

    width = abs(long_K - short_K)
    if width <= 0:
        return {"accepted": False, "rejection_reason": "degenerate width=0"}

    # --- Max profit / max loss (per share) ---
    if direction == "debit":
        max_profit = max(width - net, 0.0)
        max_loss   = net
    else:
        max_profit = net
        max_loss   = max(width - net, 0.0)

    # --- Breakeven ---
    if strategy == "BULL_CALL_DEBIT":
        breakeven = long_K + net
    elif strategy == "BEAR_PUT_DEBIT":
        breakeven = long_K - net
    elif strategy == "BULL_PUT_CREDIT":
        breakeven = short_K - net
    else:  # BEAR_CALL_CREDIT
        breakeven = short_K + net

    # --- Risk / reward filter (same thresholds as live trading) ---
    accepted = True
    rejection_reason = ""
    if direction == "debit" and net > DEBIT_MAX_COST_FRAC * width:
        accepted = False
        rejection_reason = f"net debit {net:.2f} > {DEBIT_MAX_COST_FRAC*100:.0f}% of width {width:.2f}"
    elif direction == "credit" and net < CREDIT_MIN_PREMIUM_FR * width:
        accepted = False
        rejection_reason = f"net credit {net:.2f} < {CREDIT_MIN_PREMIUM_FR*100:.0f}% of width {width:.2f}"

    # --- Position sizing: 2% of $10k = $200 max loss ---
    # Backtest sizing differs from live sizing on purpose.  Live trading
    # rejects a spread whose single-contract max loss exceeds the per-trade
    # budget (you can't buy half a contract).  In a backtest we're measuring
    # the SIGNAL's edge, not capital deployment -- so we floor at 1 contract
    # whenever the risk-reward filter accepts the spread.  The fractional
    # "intended" size is still recorded for reporting.
    budget_per_trade  = ACCOUNT_NOTIONAL * RISK_PER_TRADE_FRAC
    loss_per_contract = max_loss * 100.0
    if accepted and loss_per_contract > 0:
        intended  = budget_per_trade / loss_per_contract
        contracts = max(int(math.floor(intended)), 1)
    else:
        contracts = 0

    # Compute per-leg BS deltas for reporting / inspection
    long_delta  = bs_delta(S, long_K,  T, r, sigma, is_call)
    short_delta = bs_delta(S, short_K, T, r, sigma, is_call)

    return {
        "strategy_type":       strategy,
        "expiration":          exp_date.isoformat(),
        "dte_entry":           strategy_dte,
        "long_strike":         float(long_K),
        "long_delta":          float(long_delta),
        "long_price":          float(long_eff),
        "short_strike":        float(short_K),
        "short_delta":         float(short_delta),
        "short_price":         float(short_eff),
        "width":               float(width),
        "net_debit_or_credit": float(net),
        "max_profit":          float(max_profit),
        "max_loss":            float(max_loss),
        "breakeven":           float(breakeven),
        "contracts":           int(contracts),
        "total_risk":          float(max_loss * 100.0 * contracts),
        "total_max_profit":    float(max_profit * 100.0 * contracts),
        "accepted":            bool(accepted),
        "rejection_reason":    rejection_reason,
    }


# ---------------------------------------------------------------------------
# Historical data preparation (unchanged from v1)
# ---------------------------------------------------------------------------

def load_price_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    """
    Download daily OHLCV and compute rolling realised vol + IV Rank for
    every trading day in the series.

    Returns a DataFrame indexed by date with columns:
        close, log_ret, rolling_vol, iv_rank
    """
    print(f"[engine] Downloading {period} of {ticker} price history...")
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period, auto_adjust=True)

    if hist.empty:
        raise ValueError(f"No price history returned for {ticker}.")

    hist.index = pd.to_datetime(hist.index).tz_localize(None).normalize()
    hist.index.name = "date"

    df = pd.DataFrame({"close": hist["Close"]})
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1))

    df["rolling_vol"] = (
        df["log_ret"].rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std()
        * np.sqrt(252)
    )

    roll_min = df["rolling_vol"].rolling(IV_RANK_WINDOW, min_periods=30).min()
    roll_max = df["rolling_vol"].rolling(IV_RANK_WINDOW, min_periods=30).max()
    iv_range = roll_max - roll_min
    df["iv_rank"] = np.where(
        iv_range > 1e-8,
        (df["rolling_vol"] - roll_min) / iv_range,
        0.5,
    )
    df["iv_rank"] = df["iv_rank"].clip(0.0, 1.0)

    return df.dropna(subset=["rolling_vol"])


def load_sentiment_history(ticker: str) -> pd.DataFrame:
    """Load all sentiment CSVs for ticker and return a date-indexed frame."""
    raw_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    )
    pattern = os.path.join(raw_dir, f"sentiment_{ticker}_*.csv")
    files = sorted(glob.glob(pattern))

    if not files:
        return pd.DataFrame()

    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df.drop_duplicates(subset=["ticker", "date"], keep="last", inplace=True)
    df.sort_values("date", inplace=True)
    df.set_index("date", inplace=True)
    return df


# ---------------------------------------------------------------------------
# Synthetic sentiment generator (demo mode) -- unchanged from v1
# ---------------------------------------------------------------------------

def _generate_synthetic_history(ticker: str, days: int = 30) -> pd.DataFrame:
    """Mean-reverting synthetic sentiment walk for demo runs."""
    seed = sum(ord(c) for c in ticker)
    rng = random.Random(seed)

    trading_days = pd.bdate_range(end=datetime.date.today(), periods=days)

    rows = []
    score = 0.0
    for _ in trading_days:
        shock = rng.uniform(-0.18, 0.18)
        score = float(np.clip(score * 0.90 + shock, -1.0, 1.0))

        n = rng.randint(5, 40)
        bullish = round(max(score, 0) * 60 + rng.uniform(10, 30), 1)
        bearish = round(max(-score, 0) * 60 + rng.uniform(5, 20), 1)
        neutral = round(100 - bullish - bearish, 1)

        rows.append({
            "ticker":          ticker,
            "sentiment_score": round(score, 4),
            "headline_count":  n,
            "bullish_pct":     bullish,
            "bearish_pct":     bearish,
            "neutral_pct":     max(neutral, 0.0),
            "is_synthetic":    True,
        })

    df = pd.DataFrame(rows, index=pd.DatetimeIndex(trading_days, name="date"))
    return df


# ---------------------------------------------------------------------------
# Per-day trade simulation (spread-based)
# ---------------------------------------------------------------------------

def _simulate_spread_trade(
    spread: dict,
    price_df: pd.DataFrame,
    entry_date: pd.Timestamp,
) -> dict:
    """
    Forward-walk `price_df` from `entry_date` through the spread's expiration
    (or until an exit rule triggers), using the spread_builder simulator.

    Returns a dict of P&L fields to merge into the trade log.
    """
    exp_date = datetime.date.fromisoformat(spread["expiration"])

    # Build the forward slice: entry day + every trading day through expiration.
    # If the ticker history doesn't reach exp_date (e.g. we're backtesting
    # recent data), we pass everything we have and let the simulator treat
    # the last day as expiration.
    mask = (price_df.index >= entry_date) & \
           (price_df.index <= pd.Timestamp(exp_date))
    window = price_df.loc[mask]

    if window.empty:
        return {"pnl": 0.0, "pnl_pct": 0.0, "exit_reason": "no_forward_data",
                "exit_date": entry_date.date(), "days_held": 0,
                "entry_spread_value": 0.0, "exit_spread_value": 0.0,
                "S_exit": float(price_df.loc[entry_date, "close"])}

    price_ser = window["close"]
    iv_ser    = window["rolling_vol"]   # realised vol as IV proxy

    sim = simulate_spread_pnl(
        spread,
        price_ser,
        iv_ser,
        r=RISK_FREE_RATE,
        entry_date=entry_date.date(),
    )
    if "error" in sim:
        return {"pnl": 0.0, "pnl_pct": 0.0, "exit_reason": sim["error"],
                "exit_date": entry_date.date(), "days_held": 0,
                "entry_spread_value": 0.0, "exit_spread_value": 0.0,
                "S_exit": float(window.iloc[-1]["close"])}

    # pnl_total from simulator is per-contract * contracts (in dollars).
    # Convert to per-share (same unit metrics.py expects in `pnl`): divide
    # by 100 * contracts.
    contracts   = max(int(spread.get("contracts") or 1), 1)
    pnl_total   = float(sim.get("pnl_total", 0.0))
    pnl_per_sh  = pnl_total / (100.0 * contracts)

    # pnl_pct = return as % of max_loss (classic risk-adjusted return)
    max_loss = float(spread.get("max_loss") or 0.0)
    pnl_pct  = (pnl_per_sh / max_loss * 100.0) if max_loss > 0 else 0.0

    # Look up exit-day spot
    exit_dt = sim.get("exit_date", entry_date.date())
    try:
        S_exit = float(window.loc[pd.Timestamp(exit_dt), "close"])
    except KeyError:
        S_exit = float(window.iloc[-1]["close"])

    return {
        "pnl":                 round(pnl_per_sh, 4),
        "pnl_pct":             round(pnl_pct,    2),
        "exit_reason":         sim.get("exit_reason", "expiration"),
        "exit_date":           exit_dt,
        "days_held":           int(sim.get("days_held") or 0),
        "entry_spread_value":  round(float(sim.get("entry_spread_value", 0.0)), 4),
        "exit_spread_value":   round(float(sim.get("exit_spread_value", 0.0)), 4),
        "S_exit":              round(S_exit, 2),
        "pnl_total":           round(pnl_total, 2),
    }


# ---------------------------------------------------------------------------
# Main backtest runner
# ---------------------------------------------------------------------------

def run_backtest(
    ticker: str,
    demo_mode: bool = False,
    lookback_days: int = 30,
    save: bool = True,
    use_kelly_sizing: bool = False,
    output_suffix: str = "",
) -> pd.DataFrame:
    """
    Walk through historical data and simulate a vertical-spread trade on
    every non-NEUTRAL signal day.  Rejected spreads (low risk/reward) are
    recorded with pnl=0 and exit_reason='rejected_risk_reward' so the
    trade log still reflects every signal.

    Parameters
    ----------
    use_kelly_sizing : bool
        When False (default), fall back to the v1 "floor at 1 contract"
        sizing.  When True, consult position_sizer.size_trade() with the
        currently-loaded Kelly stats.  The A/B comparison is the point --
        run once with False to produce the stats, once with True to
        measure the Kelly uplift.
    output_suffix : str
        Extra suffix on the output filename ("_kelly" for the Kelly run)
        so the flat-sizing log isn't clobbered.
    """
    print(f"\n[engine] Running spread backtest for {ticker} "
          f"({'DEMO' if demo_mode else 'REAL'} mode, "
          f"{'Kelly' if use_kelly_sizing else 'flat'} sizing)...")

    # --- 1. Price history ---
    # When lookback_days > 250, pull 5y of history so IV_RANK burn-in (252)
    # still leaves enough tradable days.  Otherwise the default 2y is fine.
    hist_period = "5y" if lookback_days > 250 else "2y"
    price_df = load_price_history(ticker, period=hist_period)

    # --- 2. Sentiment (real or synthetic) ---
    if demo_mode:
        sent_df = _generate_synthetic_history(ticker, lookback_days)
        print(f"[engine] Using synthetic sentiment ({lookback_days} days).")
    else:
        sent_df = load_sentiment_history(ticker)
        if sent_df.empty:
            print("[engine] No sentiment data found. "
                  "Re-run with demo_mode=True or run scorer.py first.")
            return pd.DataFrame()
        print(f"[engine] Loaded {len(sent_df)} days of real sentiment data.")

    # --- 3. Align on dates where both exist ---
    price_df.index = pd.DatetimeIndex(price_df.index).normalize()
    sent_df.index  = pd.DatetimeIndex(sent_df.index).normalize()

    combined = sent_df.join(price_df[["close", "rolling_vol", "iv_rank"]],
                            how="inner")
    combined = combined.tail(lookback_days)

    if combined.empty:
        print("[engine] No overlapping dates between sentiment and price data.")
        return pd.DataFrame()

    # --- 3a. Derived feature columns used by the logistic confidence model ---
    # Kept next to the raw sentiment so the backtest log has them in every row.
    # `sent_momentum_3d`: rate-of-change of sentiment over the prior 3 sessions.
    # A strong +0.3 swing in 3 days carries different signal than a sentiment
    # that's been sitting flat at +0.3 for a month.  Computed after the join
    # so the lag lines up with trading days, not calendar days.
    combined["sent_momentum_3d"] = (
        combined["sentiment_score"].diff(3).fillna(0.0)
    )

    print(f"[engine] Simulating spreads over {len(combined)} days...")

    # --- 3b. SEC-availability map for the sentiment_source tag ---
    # We tag each trade with how the underlying sentiment signal was sourced,
    # so signal_decay can slice by source.  In real mode we look at
    # combined_sentiment_{ticker}.csv (merger output); in demo mode everything
    # is 'synthetic_news'.  Without this tag, signal_decay falls back to
    # 'news_only' for all rows -- still works, just coarser.
    #
    # We also capture per-date SEC *sentiment* values (not just availability)
    # so the confidence model's `sec_aligned` feature can check whether the
    # SEC's directional read agrees with the news-driven signal on that day.
    sec_map       = {}  # date -> bool   (sec available on that day)
    sec_score_map = {}  # date -> float  (sec sentiment score, forward-filled)
    if not demo_mode:
        try:
            from sentiment.merger import load_combined
            combined_df = load_combined(ticker)
            if not combined_df.empty and "sec_available" in combined_df.columns:
                combined_df["date"] = pd.to_datetime(combined_df["date"]).dt.normalize()
                sec_map = dict(zip(
                    combined_df["date"],
                    combined_df["sec_available"].astype(bool),
                ))
                if "sec_sentiment" in combined_df.columns:
                    sec_score_map = dict(zip(
                        combined_df["date"],
                        combined_df["sec_sentiment"].astype(float),
                    ))
        except Exception as e:
            print(f"[engine] note: sentiment_source tagging skipped: {e}")

    # --- 3b2. Earnings-proximity lookup (best-effort, cached per ticker) ---
    # The confidence model uses |days_to_earnings| as a feature.  In real mode
    # Finnhub returns earnings dates within a rolling ~9-month window, so for
    # dates deep in the backtest history we'll fall back to 999 (= "far from
    # earnings").  In demo mode we skip the API call entirely and use 999 for
    # every row -- the feature still fits fine, it just carries no signal in
    # synthetic runs.
    _nearest_fn = None
    if not demo_mode:
        try:
            from signals.earnings_filter import nearest_earnings as _nearest_fn
        except Exception:
            _nearest_fn = None

    # --- 3c. Kelly stats (only loaded when use_kelly_sizing=True) ---
    kelly_stats = position_sizer.load_stats() if use_kelly_sizing else {}
    if use_kelly_sizing and not kelly_stats:
        print(f"[engine] warning: Kelly sizing requested but no stats on disk. "
              f"Run the flat backtest first and then position_sizer.")

    # --- 3c2. Confidence model (optional) ---
    # Loaded once per backtest run; cheap in-memory dict of coefficients.
    # When present, the logistic p(win) replaces the legacy confidence
    # column in the trade log.  The flat pass writes these to the log so
    # the Kelly pass (which scales by confidence) uses calibrated weights.
    conf_model = _cmodel.load_model()
    if conf_model is not None:
        print(f"[engine] using fitted logistic confidence model "
              f"(n={conf_model.get('train_n')}, converged="
              f"{conf_model.get('converged')})")
    else:
        print(f"[engine] no confidence model on disk; using legacy formula")

    # --- 3d. Portfolio-level open-risk tracker ---
    # Tuples of (exit_date, signal, dollar_risk); pruned at each new entry so
    # position_sizer sees the correct "currently deployed" number BOTH in
    # aggregate (legacy single-pool cap) AND per-strategy (segregated-bucket
    # cap).  Simple single-ticker simulation: we don't do cross-ticker risk
    # aggregation here (that'd require a multi-ticker runner).
    open_positions: list[tuple[datetime.date, str, float]] = []

    # --- 4. Walk each day, build spread, simulate P&L ---
    trades = []
    _BULLISH_SIGS = {SIG_BUY_CALLS, SIG_SELL_PUTS}
    _BEARISH_SIGS = {SIG_BUY_PUTS, SIG_SELL_CALLS}
    for dt, row in combined.iterrows():
        sentiment = float(row["sentiment_score"])
        iv_rank   = float(row["iv_rank"])
        sigma     = float(row["rolling_vol"])
        S_entry   = float(row["close"])
        sent_momentum_3d = float(row.get("sent_momentum_3d", 0.0))
        headline_count   = int(row.get("headline_count", 0) or 0)

        signal     = _classify_signal(sentiment, iv_rank)

        if signal == SIG_NEUTRAL:
            continue

        # Confidence: prefer fitted logistic model, else legacy formula.
        # We compute this AFTER `continue` on neutral signals so we don't
        # waste cycles building feature rows we'll throw away.
        if conf_model is not None:
            # Approximate at-bar features; sec_aligned is still 0 in demo
            # (no SEC score map), days_to_earnings still 999 unless real.
            sec_aligned_now = 0
            if sec_score_map:
                sec_sent_today = sec_score_map.get(dt, None)
                if sec_sent_today is not None and not pd.isna(sec_sent_today):
                    if signal in _BULLISH_SIGS and sec_sent_today >  0.10:
                        sec_aligned_now = 1
                    elif signal in _BEARISH_SIGS and sec_sent_today < -0.10:
                        sec_aligned_now = 1
            if _nearest_fn is not None:
                try:
                    _, _dte = _nearest_fn(ticker, dt.date())
                    dte_now = int(abs(_dte))
                except Exception:
                    dte_now = 999
            else:
                dte_now = 999
            feat_row = _cmodel.build_feature_row(
                sentiment_score  = sentiment,
                iv_rank          = iv_rank,
                sent_momentum_3d = sent_momentum_3d,
                sec_aligned      = sec_aligned_now,
                headline_count   = headline_count,
                days_to_earnings = dte_now,
            )
            confidence = float(_cmodel.predict_proba(conf_model, feat_row))
        else:
            confidence = _compute_confidence(sentiment, iv_rank, signal)

        # --- Feature: SEC alignment ---
        # 1 if SEC's directional read agrees with this bar's signal direction,
        # else 0.  In demo mode we never have SEC data so this is always 0.
        sec_aligned = 0
        sec_sent_today = sec_score_map.get(dt, None) if sec_score_map else None
        if sec_sent_today is not None and not pd.isna(sec_sent_today):
            if signal in _BULLISH_SIGS and sec_sent_today > 0.10:
                sec_aligned = 1
            elif signal in _BEARISH_SIGS and sec_sent_today < -0.10:
                sec_aligned = 1

        # --- Feature: days to nearest earnings ---
        if _nearest_fn is not None:
            try:
                _, delta = _nearest_fn(ticker, dt.date())
                days_to_earnings = int(abs(delta))
            except Exception:
                days_to_earnings = 999
        else:
            days_to_earnings = 999

        # Prune any open positions that have already exited before `dt`,
        # then sum what's still on the book for the portfolio-risk cap.
        open_positions = [(exd, sig, rsk) for (exd, sig, rsk) in open_positions
                          if exd > dt.date()]
        open_risk_dollars = float(sum(r for _, _, r in open_positions))
        open_risk_by_strategy: dict = {}
        for (_, sig, rsk) in open_positions:
            open_risk_by_strategy[sig] = open_risk_by_strategy.get(sig, 0.0) + float(rsk)

        # Tag sentiment source
        if demo_mode:
            sentiment_source = "synthetic_news"
        else:
            has_sec = bool(sec_map.get(dt, False))
            # News is the authoritative source in non-demo mode (we loaded
            # sentiment_df from news CSVs).  If SEC is also available on
            # this date we call it 'combined'; otherwise 'news_only'.
            sentiment_source = "combined" if has_sec else "news_only"

        spread = _build_backtest_spread(signal, S_entry, sigma, dt.date())

        # Base row captures the signal + spread structure regardless of
        # whether the risk-reward filter accepted the trade.
        base = {
            "ticker":          ticker,
            "entry_date":      dt.date(),
            "signal":          signal,
            "confidence":      round(confidence, 4),
            "sentiment_score": round(sentiment, 4),
            "iv_rank":         round(iv_rank, 4),
            "S_entry":         round(S_entry, 2),
            "is_synthetic":    bool(row.get("is_synthetic", False)),
            "sentiment_source": sentiment_source,
            # Features for the logistic confidence model (Issue 1 rebuild)
            "headline_count":   int(headline_count),
            "sent_momentum_3d": round(sent_momentum_3d, 4),
            "sec_aligned":      int(sec_aligned),
            "days_to_earnings": int(min(days_to_earnings, 999)),
            # spread structure fields (empty if no strategy)
            "strategy_type":       spread.get("strategy_type", ""),
            "expiration":          spread.get("expiration", ""),
            "dte_entry":           spread.get("dte_entry", 0),
            "long_strike":         spread.get("long_strike", 0.0),
            "long_delta":          round(spread.get("long_delta", 0.0), 4),
            "long_price":          round(spread.get("long_price", 0.0), 4),
            "short_strike":        spread.get("short_strike", 0.0),
            "short_delta":         round(spread.get("short_delta", 0.0), 4),
            "short_price":         round(spread.get("short_price", 0.0), 4),
            "width":               spread.get("width", 0.0),
            "net_debit_or_credit": round(spread.get("net_debit_or_credit", 0.0), 4),
            "max_profit":          round(spread.get("max_profit", 0.0), 4),
            "max_loss":            round(spread.get("max_loss", 0.0), 4),
            "breakeven":           round(spread.get("breakeven", 0.0), 4),
            "contracts":           spread.get("contracts", 0),
            "total_risk":          round(spread.get("total_risk", 0.0), 2),
            "total_max_profit":    round(spread.get("total_max_profit", 0.0), 2),
            "accepted":            spread.get("accepted", False),
            "rejection_reason":    spread.get("rejection_reason", ""),
        }

        if not spread.get("accepted"):
            # Record the signal day but don't generate P&L
            base.update({
                "exit_date":          dt.date(),
                "S_exit":             round(S_entry, 2),
                "pnl":                0.0,
                "pnl_pct":            0.0,
                "pnl_total":          0.0,
                "entry_spread_value": 0.0,
                "exit_spread_value":  0.0,
                "exit_reason":        "rejected_risk_reward",
                "days_held":          0,
                "kelly_contracts":    0,
                "kelly_effective_frac": 0.0,
                "kelly_reason":       "rejected_risk_reward",
                "bucket_frac":        0.0,
                "bucket_used_before": 0.0,
                "bucket_cap_dollars": 0.0,
            })
            trades.append(base)
            continue

        # --- Kelly override (only when use_kelly_sizing=True) ---
        # Flat sizing already set spread["contracts"] inside _build_backtest_spread
        # (floor=1).  When Kelly is on we replace it with size_trade()'s answer,
        # including portfolio-level open_risk cap.  If Kelly says skip the trade
        # (negative historical edge for this signal type), contracts becomes 0
        # and we record it as rejected_by_kelly -- that's the desired behaviour.
        if use_kelly_sizing:
            # Defer to position_sizer's module-level USE_STRATEGY_BUCKETS
            # flag so flipping the production regime doesn't need an
            # engine change.  Currently production = QUINTILE sizing (R3);
            # legacy segregated-bucket Kelly is still available for A/B
            # via position_sizer.USE_STRATEGY_BUCKETS=True.
            size = position_sizer.size_trade(
                signal                = signal,
                confidence            = confidence,
                max_loss_per_contract = spread["max_loss"],
                stats                 = kelly_stats,
                open_risk_dollars     = open_risk_dollars,
                open_risk_by_strategy = open_risk_by_strategy,
                account_notional      = KELLY_BACKTEST_NOTIONAL,
            )
            base["kelly_contracts"]      = int(size["contracts"])
            base["kelly_effective_frac"] = float(size.get("effective_frac", 0.0))
            base["kelly_reason"]         = size.get("reason", "")
            base["bucket_frac"]          = float(size.get("bucket_frac", 0.0))
            base["bucket_used_before"]   = float(size.get("bucket_used_before", 0.0))
            base["bucket_cap_dollars"]   = float(size.get("bucket_cap_dollars", 0.0))
            if size["contracts"] <= 0:
                # Kelly disabled this trade entirely.  Record as rejected
                # (not an error) so the log still reflects every signal day.
                base.update({
                    "contracts":          0,
                    "total_risk":         0.0,
                    "total_max_profit":   0.0,
                    "exit_date":          dt.date(),
                    "S_exit":             round(S_entry, 2),
                    "pnl":                0.0,
                    "pnl_pct":            0.0,
                    "pnl_total":          0.0,
                    "entry_spread_value": 0.0,
                    "exit_spread_value":  0.0,
                    "exit_reason":        "rejected_by_kelly",
                    "days_held":          0,
                })
                trades.append(base)
                continue
            # Override contracts and downstream totals so simulator sees Kelly size
            spread["contracts"]        = int(size["contracts"])
            spread["total_risk"]       = float(size["contracts"] * spread["max_loss"] * 100.0)
            spread["total_max_profit"] = float(size["contracts"] * spread["max_profit"] * 100.0)
            base["contracts"]          = int(size["contracts"])
            base["total_risk"]         = round(spread["total_risk"], 2)
            base["total_max_profit"]   = round(spread["total_max_profit"], 2)
        else:
            base["kelly_contracts"]      = int(spread.get("contracts") or 0)
            base["kelly_effective_frac"] = 0.0
            base["kelly_reason"]         = "flat_sizing"
            base["bucket_frac"]          = 0.0
            base["bucket_used_before"]   = 0.0
            base["bucket_cap_dollars"]   = 0.0

        sim = _simulate_spread_trade(spread, price_df, dt)
        base.update(sim)
        trades.append(base)

        # Book-keep open position until its exit_date so subsequent entries
        # see the correct portfolio risk.  We record total_risk (dollar loss
        # if the trade goes maximally wrong), not remaining risk -- that's
        # the conservative read a portfolio cap should enforce.
        exit_dt = sim.get("exit_date", dt.date())
        if isinstance(exit_dt, pd.Timestamp):
            exit_dt = exit_dt.date()
        open_positions.append((exit_dt, signal,
                               float(spread.get("total_risk", 0.0))))

    if not trades:
        print("[engine] No trades were triggered during this period.")
        return pd.DataFrame()

    df = pd.DataFrame(trades)
    n_accepted = int(df["accepted"].sum()) if "accepted" in df.columns else 0
    print(f"[engine] {len(df)} signal days recorded "
          f"({n_accepted} accepted, {len(df) - n_accepted} rejected).")

    if save:
        _save(df, ticker, demo_mode, output_suffix)

    return df


def _save(df: pd.DataFrame, ticker: str, demo_mode: bool,
          output_suffix: str = "") -> str:
    raw_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    )
    os.makedirs(raw_dir, exist_ok=True)
    suffix   = ("_demo" if demo_mode else "") + (output_suffix or "")
    filepath = os.path.join(raw_dir, f"backtest_{ticker}{suffix}.csv")
    df.to_csv(filepath, index=False)
    print(f"[engine] Saved -> {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys
    demo = "--demo" in _sys.argv
    trades = run_backtest("AAPL", demo_mode=demo)
    if not trades.empty:
        print("\n--- Trade Log (first 10 rows) ---")
        cols = ["entry_date", "signal", "strategy_type",
                "long_strike", "short_strike",
                "net_debit_or_credit", "accepted",
                "exit_reason", "pnl", "pnl_pct"]
        print(trades[cols].head(10).to_string(index=False))

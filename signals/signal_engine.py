# =============================================================================
# signals/signal_engine.py — Combine sentiment + IV Rank into trade signals
#
# SIGNAL LOGIC (all thresholds configurable in config.py):
#
#   Condition A: sentiment > +0.25   → bullish
#   Condition B: sentiment < -0.25   → bearish
#   Condition C: iv_rank < 0.30      → options cheap  (favor buying premium)
#   Condition D: iv_rank > 0.70      → options expensive (favor selling premium)
#
#   A + C  →  BUY CALLS    (bullish view + cheap options = best of both worlds)
#   A + D  →  SELL PUTS    (bullish view + expensive options = collect premium,
#                            aligned with direction)
#   B + C  →  BUY PUTS     (bearish view + cheap options)
#   B + D  →  SELL CALLS   (bearish view + expensive options)
#   else   →  NEUTRAL
#
# CONFIDENCE SCORE (0.0 – 1.0):
#   Measures how far each input is past its threshold, averaged.
#   A signal right at the edge (sentiment = 0.26, iv_rank = 0.29) scores
#   near 0.0; a signal deep in the zone (sentiment = 0.80, iv_rank = 0.05)
#   scores near 1.0.  NEUTRAL always scores 0.0.
#
#   sentiment_conf = |sentiment - threshold| / (1.0 - threshold)
#   iv_rank_conf   = |iv_rank - threshold|   / threshold_range
#   confidence     = (sentiment_conf + iv_rank_conf) / 2
#
# STALENESS CHECK:
#   If the most recent sentiment date is > 3 calendar days old we warn the
#   user. Signals built on old news are unreliable.
# =============================================================================

import os
import sys
import glob
import datetime
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

# Kelly sizing lives in its own module so the sizing math is testable in
# isolation.  Imported lazily-ish (top-of-module) because it's cheap --
# no yfinance or torch dependency.
from signals import position_sizer
# Logistic confidence model -- falls back to legacy if not fitted yet.
from signals import confidence_model


# ---------------------------------------------------------------------------
# Signal labels (keep as constants so callers can do equality checks without
# depending on magic strings scattered through the codebase)
# ---------------------------------------------------------------------------
SIG_BUY_CALLS  = "BUY CALLS"
SIG_SELL_PUTS  = "SELL PUTS"
SIG_BUY_PUTS   = "BUY PUTS"
SIG_SELL_CALLS = "SELL CALLS"
SIG_NEUTRAL    = "NEUTRAL"
# Earnings-specific signal: sell ATM straddle/strangle into vol crush
SIG_IV_CRUSH   = "IV CRUSH"

# How many calendar days old the sentiment data can be before we warn
MAX_SENTIMENT_AGE_DAYS = 3


# ---------------------------------------------------------------------------
# File discovery helpers
# ---------------------------------------------------------------------------

def _latest_csv(directory: str, pattern: str) -> str | None:
    """
    Return the path of the alphabetically-last file matching `pattern`
    inside `directory`.  Because our files are named with ISO dates
    (YYYY-MM-DD), alphabetical order equals chronological order.
    """
    matches = sorted(glob.glob(os.path.join(directory, pattern)))
    return matches[-1] if matches else None


def _raw_dir() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_sentiment(ticker: str) -> dict:
    """
    Load the most recent daily sentiment CSV for `ticker` and return the
    latest row's data as a dict.

    Returns keys: sentiment_score, date, headline_count,
                  bullish_pct, bearish_pct, neutral_pct, staleness_days
    """
    csv_path = _latest_csv(_raw_dir(), f"sentiment_{ticker}_*.csv")
    if not csv_path:
        raise FileNotFoundError(
            f"No sentiment CSV found for {ticker}. "
            "Run sentiment/scorer.py first."
        )

    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df.sort_values("date", inplace=True)

    # Most recent row
    latest = df.iloc[-1]

    staleness = (datetime.date.today() - latest["date"]).days
    if staleness > MAX_SENTIMENT_AGE_DAYS:
        print(
            f"[signal_engine] WARNING: sentiment data for {ticker} is "
            f"{staleness} days old (last: {latest['date']}). "
            "Consider re-running news_fetcher + scorer."
        )

    return {
        "sentiment_score":  float(latest["sentiment_score"]),
        "date":             latest["date"],
        "headline_count":   int(latest.get("headline_count", 0)),
        "bullish_pct":      float(latest.get("bullish_pct", 0.0)),
        "bearish_pct":      float(latest.get("bearish_pct", 0.0)),
        "neutral_pct":      float(latest.get("neutral_pct", 0.0)),
        "staleness_days":   staleness,
    }


def load_iv_rank(ticker: str) -> dict:
    """
    Load the most recent options CSV for `ticker` and extract IV Rank stats.
    Prefers real_iv over the proxy when both are present.

    Returns keys: iv_rank, iv_rank_pct, iv_rank_label, current_iv_proxy,
                  real_iv, iv_52w_high, iv_52w_low, fetch_date, expiration
    """
    csv_path = _latest_csv(_raw_dir(), f"options_{ticker}_*.csv")
    if not csv_path:
        raise FileNotFoundError(
            f"No options CSV found for {ticker}. "
            "Run data/options_fetcher.py first."
        )

    df  = pd.read_csv(csv_path, nrows=1)
    row = df.iloc[0]

    # real_iv may be absent in older CSVs — use pd.isna guard
    raw_real_iv = row.get("real_iv", None)
    real_iv = None if (raw_real_iv is None or pd.isna(raw_real_iv)) \
              else float(raw_real_iv)

    return {
        "iv_rank":          float(row["iv_rank"]),
        "iv_rank_pct":      float(row["iv_rank_pct"]),
        "iv_rank_label":    str(row.get("iv_rank_label", "")),
        "current_iv_proxy": float(row.get("current_iv_proxy", 0.0)),
        "real_iv":          real_iv,
        "iv_52w_high":      float(row.get("iv_52w_high", 0.0)),
        "iv_52w_low":       float(row.get("iv_52w_low", 0.0)),
        "fetch_date":       str(row.get("fetch_date", "")),
        "expiration":       str(row.get("expiration", "")),
    }


# ---------------------------------------------------------------------------
# Signal logic
# ---------------------------------------------------------------------------

def _classify_signal(sentiment: float, iv_rank: float) -> str:
    """
    Apply the 4-quadrant rule table and return a signal label.
    Does NOT consider earnings; call _classify_with_earnings() for that.
    """
    bull      = config.SIGNAL_PARAMS["bullish_sentiment_threshold"]
    bear      = config.SIGNAL_PARAMS["bearish_sentiment_threshold"]
    iv_lo     = config.SIGNAL_PARAMS["low_iv_rank_threshold"]
    iv_hi     = config.SIGNAL_PARAMS["high_iv_rank_threshold"]

    bullish   = sentiment > bull
    bearish   = sentiment < bear
    cheap     = iv_rank < iv_lo
    expensive = iv_rank > iv_hi

    if   bullish and cheap:     return SIG_BUY_CALLS
    elif bullish and expensive: return SIG_SELL_PUTS
    elif bearish and cheap:     return SIG_BUY_PUTS
    elif bearish and expensive: return SIG_SELL_CALLS
    else:                       return SIG_NEUTRAL


def _classify_with_earnings(
    sentiment: float,
    iv_rank: float,
    ticker: str,
    check_date: datetime.date = None,
) -> tuple[str, dict]:
    """
    Full signal classification including earnings-window logic.

    Returns
    -------
    (signal_label, earnings_info_dict)

    Earnings overrides (in priority order):
      1. IV_CRUSH  — 1-2 days before earnings AND iv_rank > 0.80
      2. SUPPRESS  — anywhere else in the earnings window
      3. Normal 4-quadrant logic — outside the window
    """
    from signals.earnings_filter import is_earnings_window

    if check_date is None:
        check_date = datetime.date.today()

    earnings = is_earnings_window(ticker, check_date, iv_rank)

    if earnings["in_window"]:
        override = earnings["signal_override"]
        if override == "IV_CRUSH":
            return SIG_IV_CRUSH, earnings
        else:
            # SUPPRESS: earnings risk is too high for directional/vol trades
            return SIG_NEUTRAL, earnings

    # Normal path — no earnings proximity
    return _classify_signal(sentiment, iv_rank), earnings


# ---------------------------------------------------------------------------
# Confidence tier thresholds (news + SEC agreement)
#
# Confidence is reported on a 0-1 scale.  We split the range into three
# named tiers so downstream code (and humans) can reason about trade
# sizing / filtering without chasing decimals:
#
#   HIGH   0.80 - 1.00   news + SEC agree directionally (both bullish OR
#                        both bearish, or the currently-directional side
#                        has SEC pointing the same way)
#   MEDIUM 0.50 - 0.80   news signal is strong but SEC data is missing
#                        (stale / unavailable) -- directional read without
#                        corroboration from the regime indicator
#   LOW    0.00 - 0.50   signals DISAGREE (news bullish, SEC bearish or
#                        vice versa) OR SEC data is stale AND news is weak
# ---------------------------------------------------------------------------
CONFIDENCE_HIGH_FLOOR   = 0.80
CONFIDENCE_MEDIUM_FLOOR = 0.50
# Staleness threshold for the SEC filing.  Longer than this -> treat as
# "SEC unavailable" for confidence purposes.  Matches merger.SEC_STALE_DAYS
# but duplicated here so signal_engine doesn't need to import merger.
SEC_STALE_DAYS = 180


def _sentiment_direction(score: float) -> str:
    """Map a score to 'bullish' / 'bearish' / 'neutral' using signal thresholds."""
    bull = config.SIGNAL_PARAMS["bullish_sentiment_threshold"]
    bear = config.SIGNAL_PARAMS["bearish_sentiment_threshold"]
    if score is None:
        return "none"
    if score >  bull:  return "bullish"
    if score <  bear:  return "bearish"
    return "neutral"


def _sources_agree(news_sent: float, sec_sent: float) -> bool:
    """
    Two sentiment sources AGREE if they point the same way directionally.
    Neutral-on-either-side does NOT count as agreement -- we want the SEC
    to actively corroborate, not just 'not disagree'.
    """
    return (_sentiment_direction(news_sent) != "none"
            and _sentiment_direction(news_sent) == _sentiment_direction(sec_sent))


def _sources_disagree(news_sent: float, sec_sent: float) -> bool:
    """Explicit disagreement: one bullish, the other bearish."""
    n = _sentiment_direction(news_sent)
    s = _sentiment_direction(sec_sent)
    return (n == "bullish" and s == "bearish") or \
           (n == "bearish" and s == "bullish")


def _tiered_confidence(
    news_sent: float,
    sec_sent: Optional[float],
    sec_age_days: Optional[int],
    iv_rank: float,
    signal: str,
) -> tuple[float, str]:
    """
    Combine the legacy strength-based confidence with SEC-agreement logic
    to produce a final confidence in [0, 1] and a tier label.

    Algorithm
    ---------
    1. Compute base_confidence from news_sent + iv_rank (existing formula)
    2. Decide the tier based on SEC agreement / staleness:
         HIGH   : sources agree AND SEC fresh
         LOW    : sources disagree OR (SEC stale AND news weak)
         MEDIUM : everything else (news alone, SEC missing or stale but
                  news strong)
    3. Scale base_confidence into the tier's sub-range so a strong news
       signal in the MEDIUM tier still ranks higher than a weak one.
    """
    if signal == SIG_NEUTRAL:
        return 0.0, "NONE"

    base = _compute_confidence_legacy(news_sent, iv_rank, signal)
    base = float(np.clip(base, 0.0, 1.0))

    # SEC availability
    sec_available = (sec_sent is not None
                     and sec_age_days is not None
                     and sec_age_days <= SEC_STALE_DAYS)
    sec_stale     = (sec_sent is not None
                     and sec_age_days is not None
                     and sec_age_days > SEC_STALE_DAYS)

    # Classify tier
    if sec_available and _sources_agree(news_sent, sec_sent):
        tier      = "HIGH"
        lo, hi    = CONFIDENCE_HIGH_FLOOR, 1.0
    elif sec_available and _sources_disagree(news_sent, sec_sent):
        tier      = "LOW"
        lo, hi    = 0.0, CONFIDENCE_MEDIUM_FLOOR
    else:
        # SEC missing / stale / neutral - depend on news strength.
        # A strong news signal here still earns MEDIUM; a weak one slides to LOW.
        if base >= 0.5:
            tier = "MEDIUM"
            lo, hi = CONFIDENCE_MEDIUM_FLOOR, CONFIDENCE_HIGH_FLOOR
        else:
            tier = "LOW"
            lo, hi = 0.0, CONFIDENCE_MEDIUM_FLOOR
        # Extra penalty if SEC was present but stale -- we *tried* to use it
        # and couldn't.  Cap this case at LOW regardless of news strength.
        if sec_stale and base < 0.75:
            tier = "LOW"
            lo, hi = 0.0, CONFIDENCE_MEDIUM_FLOOR

    scaled = lo + base * (hi - lo)
    return round(float(np.clip(scaled, 0.0, 1.0)), 4), tier


def _compute_confidence_legacy(sentiment: float, iv_rank: float, signal: str) -> float:
    """
    Return a 0–1 confidence score reflecting how deeply into the signal
    zone each input sits.

    For NEUTRAL signals this is always 0.0 — no actionable edge.

    For directional signals:
      sentiment_conf = how far the score is past its ±0.25 threshold,
                       normalised over the remaining range to ±1.0
      iv_rank_conf   = how far iv_rank is past its 0.30/0.70 threshold,
                       normalised over the 0.30-wide band beyond each edge

    Final confidence = simple average of the two components, clipped [0, 1].
    """
    if signal == SIG_NEUTRAL:
        return 0.0

    bull = config.SIGNAL_PARAMS["bullish_sentiment_threshold"]   # 0.25
    bear = config.SIGNAL_PARAMS["bearish_sentiment_threshold"]   # -0.25
    iv_lo = config.SIGNAL_PARAMS["low_iv_rank_threshold"]        # 0.30
    iv_hi = config.SIGNAL_PARAMS["high_iv_rank_threshold"]       # 0.70

    # --- Sentiment component ---
    # Normalising range: from threshold to the maximum possible value (1.0 or -1.0)
    if signal in (SIG_BUY_CALLS, SIG_SELL_PUTS):
        # bullish: sentiment in (bull, 1.0]
        sent_conf = (sentiment - bull) / (1.0 - bull)
    else:
        # bearish: sentiment in [-1.0, bear)
        sent_conf = (bear - sentiment) / (1.0 + abs(bear))

    # --- IV Rank component ---
    # The "reward zone" beyond each threshold is 0.30 wide (0→0.30, or 0.70→1.0)
    if signal in (SIG_BUY_CALLS, SIG_BUY_PUTS):
        # cheap options: iv_rank in [0, iv_lo)
        iv_conf = (iv_lo - iv_rank) / iv_lo
    else:
        # expensive options: iv_rank in (iv_hi, 1.0]
        iv_conf = (iv_rank - iv_hi) / (1.0 - iv_hi)

    confidence = (sent_conf + iv_conf) / 2.0
    return round(float(np.clip(confidence, 0.0, 1.0)), 4)


# Backward-compat alias.  Legacy callers (backtest/engine.py, older scripts)
# import `_compute_confidence` expecting the strength-only formula; the new
# tiered function is used internally by generate_signal when SEC data exists.
_compute_confidence = _compute_confidence_legacy


# ---------------------------------------------------------------------------
# Optional SEC sentiment loader (no hard dependency: missing data -> None)
# ---------------------------------------------------------------------------

def _try_load_sec_sentiment(ticker: str) -> Optional[dict]:
    """
    Return the most recent SEC filing sentiment for `ticker` as a dict, or
    None if the SEC backfill hasn't been run yet.  We only need the latest
    filing's score + age -- the merger produces a full daily series but
    that's overkill for point-in-time signal generation.
    """
    path = os.path.join(
        _raw_dir(), f"sec_sentiment_{ticker.upper()}.csv"
    )
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if df.empty:
            return None
        df["filing_date"] = pd.to_datetime(df["filing_date"]).dt.date
        df = df.sort_values("filing_date")
        latest = df.iloc[-1]
        age = (datetime.date.today() - latest["filing_date"]).days
        return {
            "sec_sentiment":    float(latest["sentiment_score"]),
            "sec_filing_date":  latest["filing_date"],
            "sec_filing_type":  str(latest["filing_type"]),
            "sec_age_days":     int(age),
        }
    except Exception as e:
        print(f"[signal_engine] WARN: failed to load SEC sentiment for "
              f"{ticker}: {e}")
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_signal(ticker: str, save: bool = True) -> pd.DataFrame:
    """
    Produce a signal row for `ticker` using its latest sentiment + options data,
    including earnings-window awareness.

    Returns
    -------
    pd.DataFrame with one row and columns:
        ticker, signal_date, sentiment_date, sentiment_score,
        headline_count, bullish_pct, bearish_pct, neutral_pct,
        iv_rank, iv_rank_pct, real_iv, current_iv_proxy,
        iv_52w_low, iv_52w_high, expiration,
        signal, confidence,
        earnings_warning, earnings_date, days_to_earnings
    """
    print(f"[signal_engine] Generating signal for {ticker}...")

    sent = load_sentiment(ticker)
    iv   = load_iv_rank(ticker)
    sec  = _try_load_sec_sentiment(ticker)    # None if backfill not run

    signal, earnings = _classify_with_earnings(
        sent["sentiment_score"], iv["iv_rank"], ticker
    )

    # --- Confidence scoring ---
    # Prefer the fitted logistic model (scripts/fit_confidence_model.py) if
    # it exists on disk; otherwise fall back to the legacy tiered formula.
    # The model outputs a calibrated p(win); we use that directly as the
    # confidence score in [0, 1].  Decay-study validation showed the model
    # Q5-Q1 spread beats the legacy Q5-Q1 spread 2:1 in sample, so we swap
    # whenever a fitted model is available.
    cmodel = confidence_model.load_model() if signal != SIG_NEUTRAL else None
    if cmodel is not None and signal != SIG_NEUTRAL:
        # Build feature row at signal time.  Some features (momentum, SEC
        # alignment, days-to-earnings) aren't in the latest-row sentiment
        # dict, so we best-effort reconstruct them.  Missing -> defensible
        # defaults that don't blow up the prediction.
        sec_aligned_now = 0
        if sec is not None:
            sec_score = float(sec.get("sec_sentiment", 0.0))
            if signal in (SIG_BUY_CALLS, SIG_SELL_PUTS) and sec_score >  0.10:
                sec_aligned_now = 1
            elif signal in (SIG_BUY_PUTS, SIG_SELL_CALLS) and sec_score < -0.10:
                sec_aligned_now = 1

        # Sentiment momentum: we don't have 3-day history on the latest-row
        # dict; use 0 (no momentum info) so the feature just contributes
        # the bias at the mean.  A richer signal loop could pull the last
        # 4 rows off the sentiment CSV and compute this properly.
        sent_momentum_3d = 0.0

        # Days to earnings -- if earnings filter already ran we can reuse it
        days_to_earnings = int(earnings.get("days_to_earnings") or 999)
        if days_to_earnings < 0:
            days_to_earnings = abs(days_to_earnings)

        feat = confidence_model.build_feature_row(
            sentiment_score  = sent["sentiment_score"],
            iv_rank          = iv["iv_rank"],
            sent_momentum_3d = sent_momentum_3d,
            sec_aligned      = sec_aligned_now,
            headline_count   = sent["headline_count"],
            days_to_earnings = days_to_earnings,
        )
        confidence = round(confidence_model.predict_proba(cmodel, feat), 4)
        # Keep a readable tier label derived from the calibrated p(win).
        if confidence >= 0.60:
            confidence_tier = "HIGH"
        elif confidence >= 0.50:
            confidence_tier = "MEDIUM"
        else:
            confidence_tier = "LOW"
    else:
        # Legacy fallback: three-tier news + SEC agreement formula.
        confidence, confidence_tier = _tiered_confidence(
            news_sent    = sent["sentiment_score"],
            sec_sent     = sec["sec_sentiment"]    if sec else None,
            sec_age_days = sec["sec_age_days"]     if sec else None,
            iv_rank      = iv["iv_rank"],
            signal       = signal,
        )

    # Surface the active IV value (real preferred, proxy fallback)
    active_iv  = iv["real_iv"] if iv["real_iv"] is not None else iv["current_iv_proxy"]
    iv_source  = "real" if iv["real_iv"] is not None else "proxy"

    # --- Kelly sizing metadata ---
    # Attach the fractional-Kelly weight for this signal TYPE (ignoring the
    # specific spread's max_loss, which signal_engine doesn't know).  The
    # downstream spread_builder / backtest engine calls position_sizer.
    # size_trade() with the real max_loss to convert this into a contract
    # count.  We still stamp `size_multiplier` = kelly_f_frac * confidence
    # here so any caller that just wants "how big should this be?" gets
    # a 0-1 scalar they can scale against their own risk budget.
    kelly_stats = position_sizer.load_stats()
    kelly_f_frac, kelly_tradable = position_sizer.kelly_fraction_for(
        signal, kelly_stats
    )
    size_multiplier = round(kelly_f_frac * confidence, 4)

    if earnings["in_window"]:
        print(f"[signal_engine] EARNINGS WINDOW: {earnings['warning_text']}")

    row = {
        "ticker":             ticker,
        "signal_date":        datetime.date.today().isoformat(),
        "sentiment_date":     sent["date"].isoformat(),
        "sentiment_score":    sent["sentiment_score"],
        "headline_count":     sent["headline_count"],
        "bullish_pct":        sent["bullish_pct"],
        "bearish_pct":        sent["bearish_pct"],
        "neutral_pct":        sent["neutral_pct"],
        "iv_rank":            iv["iv_rank"],
        "iv_rank_pct":        iv["iv_rank_pct"],
        "real_iv":            iv["real_iv"],
        "current_iv_proxy":   iv["current_iv_proxy"],
        "active_iv":          round(active_iv, 4),
        "iv_source":          iv_source,
        "iv_52w_low":         iv["iv_52w_low"],
        "iv_52w_high":        iv["iv_52w_high"],
        "expiration":         iv["expiration"],
        "signal":             signal,
        "confidence":         confidence,
        "confidence_tier":    confidence_tier,
        # Kelly sizing metadata (resolves to 0 when no historical edge OR
        # insufficient sample size -- see position_sizer.MIN_TRADES_FOR_KELLY)
        "kelly_f_frac":       kelly_f_frac,
        "kelly_tradable":     kelly_tradable,
        "size_multiplier":    size_multiplier,
        # SEC fields (None when backfill hasn't been run)
        "sec_sentiment":      sec["sec_sentiment"]    if sec else None,
        "sec_filing_date":    sec["sec_filing_date"].isoformat() if sec else None,
        "sec_filing_type":    sec["sec_filing_type"]  if sec else None,
        "sec_age_days":       sec["sec_age_days"]     if sec else None,
        # Earnings fields
        "earnings_warning":   bool(earnings["in_window"]),
        "earnings_date":      earnings["earnings_date"],
        "days_to_earnings":   earnings["days_to_earnings"],
    }

    df = pd.DataFrame([row])

    if save:
        _save(df, ticker)

    return df


def generate_all_signals(tickers: list = None, **kwargs) -> pd.DataFrame:
    """
    Generate signals for every ticker and return a combined DataFrame.
    Tickers that fail (missing data, API error) are skipped with a warning.
    """
    if tickers is None:
        tickers = config.TICKERS

    frames = []
    for ticker in tickers:
        try:
            frames.append(generate_signal(ticker, **kwargs))
        except FileNotFoundError as e:
            print(f"[signal_engine] SKIP {ticker}: {e}")
        except Exception as e:
            print(f"[signal_engine] ERROR {ticker}: {e}")

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _save(df: pd.DataFrame, ticker: str) -> str:
    raw_dir = _raw_dir()
    os.makedirs(raw_dir, exist_ok=True)
    filepath = os.path.join(raw_dir, f"signals_{ticker}.csv")

    # Append to existing file so we build a signal history over time.
    # If the file doesn't exist yet, write=create; otherwise append without header.
    write_header = not os.path.exists(filepath)
    df.to_csv(filepath, mode="a", header=write_header, index=False)
    print(f"[signal_engine] Saved -> {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# Pretty-print summary
# ---------------------------------------------------------------------------

# Visual separator width
_W = 52

def _signal_decoration(signal: str) -> str:
    """Return a short descriptor that makes the signal easy to scan."""
    return {
        SIG_BUY_CALLS:  "++ BUY CALLS  (bullish + cheap vol)",
        SIG_SELL_PUTS:  "+  SELL PUTS  (bullish + expensive vol)",
        SIG_BUY_PUTS:   "-- BUY PUTS   (bearish + cheap vol)",
        SIG_SELL_CALLS: "-  SELL CALLS (bearish + expensive vol)",
        SIG_NEUTRAL:    "   NEUTRAL    (no edge)",
        SIG_IV_CRUSH:   "** IV CRUSH   (sell premium before earnings)",
    }.get(signal, signal)


def _sentiment_zone(score: float) -> str:
    bull = config.SIGNAL_PARAMS["bullish_sentiment_threshold"]
    bear = config.SIGNAL_PARAMS["bearish_sentiment_threshold"]
    if   score > bull:  return "BULLISH"
    elif score < bear:  return "BEARISH"
    else:               return "NEUTRAL"


def _iv_zone(iv_rank: float) -> str:
    if   iv_rank < config.SIGNAL_PARAMS["low_iv_rank_threshold"]:  return "LOW (cheap)"
    elif iv_rank > config.SIGNAL_PARAMS["high_iv_rank_threshold"]: return "HIGH (expensive)"
    else:                                                            return "NEUTRAL"


def print_signal_summary(df: pd.DataFrame) -> None:
    """Print a formatted single-ticker signal card to stdout."""
    if df.empty:
        print("[signal_engine] No signal to display.")
        return

    r = df.iloc[0]  # one row per ticker

    bar = "=" * _W
    print(f"\n{bar}")
    print(f"  SIGNAL SUMMARY: {r['ticker']}  ({r['signal_date']})")
    print(bar)

    print(f"  {'INPUT DATA':}")
    print(f"    Sentiment date   : {r['sentiment_date']}  "
          f"({int(r['headline_count'])} articles)")
    print(f"    Bullish / Bearish / Neutral : "
          f"{r['bullish_pct']:.1f}% / {r['bearish_pct']:.1f}% / {r['neutral_pct']:.1f}%")
    print(f"    Options expiry   : {r['expiration']}")
    print()

    print(f"  {'INDICATORS':}")
    print(f"    Sentiment score  : {r['sentiment_score']:+.4f}  "
          f"[{_sentiment_zone(r['sentiment_score'])}]")
    print(f"    IV Rank          : {r['iv_rank_pct']:.1f}%  "
          f"[{_iv_zone(r['iv_rank'])}]")

    # Show real IV vs proxy if both are available
    real_iv  = r.get("real_iv")
    proxy_iv = r.get("current_iv_proxy")
    if real_iv is not None and not pd.isna(real_iv):
        vrp = float(real_iv) - float(proxy_iv)
        print(f"    Real IV (ATM)    : {float(real_iv):.2%}  "
              f"[back-solved from chain]")
        print(f"    Proxy IV (30d rv): {float(proxy_iv):.2%}  "
              f"[vol risk premium: {vrp:+.2%}]")
    else:
        print(f"    Current IV proxy : {float(proxy_iv):.2%}  "
              f"(52w range: {r['iv_52w_low']:.2%} to {r['iv_52w_high']:.2%})")
    print(f"    IV used for rank : {'real' if (real_iv and not pd.isna(real_iv)) else 'proxy'}")

    # Earnings block
    if r.get("earnings_warning"):
        print()
        print(f"  EARNINGS WINDOW")
        print(f"    Earnings date    : {r.get('earnings_date', 'unknown')}")
        dte = r.get("days_to_earnings", 999)
        direction = f"in {dte}d" if dte > 0 else f"{abs(dte)}d ago" if dte < 0 else "TODAY"
        print(f"    Days to earnings : {direction}")
    print()

    # SEC block (only printed if data is present)
    sec_score = r.get("sec_sentiment")
    if sec_score is not None and not pd.isna(sec_score):
        print(f"  SEC CORROBORATION")
        print(f"    Latest filing    : {r.get('sec_filing_type','?')} "
              f"on {r.get('sec_filing_date','?')} "
              f"({int(r.get('sec_age_days', 0) or 0)}d ago)")
        print(f"    SEC sentiment    : {float(sec_score):+.4f}  "
              f"[{_sentiment_zone(float(sec_score))}]")
        print()

    print(f"  {'SIGNAL':}")
    print(f"    {_signal_decoration(r['signal'])}")
    tier = r.get("confidence_tier", "")
    tier_str = f"  [{tier}]" if tier and tier != "NONE" else ""
    print(f"    Confidence       : {r['confidence']:.2f} / 1.00{tier_str}")

    filled  = round(r['confidence'] * 20)
    bar_str = "#" * filled + "-" * (20 - filled)
    print(f"    [{bar_str}]")

    # Kelly sizing block -- only printed when Kelly data exists
    kf = r.get("kelly_f_frac")
    if kf is not None and not pd.isna(kf) and float(kf) > 0:
        print()
        print(f"  POSITION SIZING")
        print(f"    Kelly 0.25x      : {float(kf):.3f}  "
              f"(signal-type historical edge)")
        print(f"    Size multiplier  : {float(r.get('size_multiplier', 0)):.3f}  "
              f"(kelly x confidence)")
    elif kf is not None and float(kf) == 0:
        print()
        print(f"  POSITION SIZING")
        print(f"    Kelly 0.25x      : 0.000  "
              f"(no historical edge for this signal type, or n<"
              f"{position_sizer.MIN_TRADES_FOR_KELLY})")

    print(bar)


# ---------------------------------------------------------------------------
# Thresholds reference — useful when tuning config.py
# ---------------------------------------------------------------------------

def explain_thresholds() -> None:
    """Print the active threshold values and what each combination means."""
    p = config.SIGNAL_PARAMS
    print("\nActive signal thresholds:")
    print(f"  Bullish sentiment  > {p['bullish_sentiment_threshold']}")
    print(f"  Bearish sentiment  < {p['bearish_sentiment_threshold']}")
    print(f"  High IV Rank       > {p['high_iv_rank_threshold']}")
    print(f"  Low IV Rank        < {p['low_iv_rank_threshold']}")
    print()
    print("  Signal matrix:")
    print("              | IV LOW (<{lo}) | IV NEUTRAL | IV HIGH (>{hi})".format(
        lo=p["low_iv_rank_threshold"], hi=p["high_iv_rank_threshold"]))
    print("  ------------|----------------|------------|------------------")
    print("  BULLISH (>+{b}) | BUY CALLS      | NEUTRAL    | SELL PUTS".format(
        b=p["bullish_sentiment_threshold"]))
    print("  NEUTRAL     | NEUTRAL        | NEUTRAL    | NEUTRAL")
    print("  BEARISH (<{b}) | BUY PUTS       | NEUTRAL    | SELL CALLS".format(
        b=p["bearish_sentiment_threshold"]))


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    signal_df = generate_signal("AAPL")
    print_signal_summary(signal_df)
    explain_thresholds()

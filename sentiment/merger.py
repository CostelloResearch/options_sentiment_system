# =============================================================================
# sentiment/merger.py -- Unify daily news sentiment with quarterly SEC sentiment
#
# THE CADENCE PROBLEM
# -------------------
# News sentiment updates daily (many articles per day).  SEC filings update
# quarterly (10-Q four times a year, 10-K annually, 8-K irregularly).  To
# feed both into signal_engine without clobbering one with the other, we
# build a DAILY series where each row carries:
#
#   date, ticker,
#   news_sentiment, news_headline_count,
#   sec_sentiment, sec_filing_date, sec_filing_type, sec_age_days,
#   combined_sentiment
#
# The SEC columns are forward-filled: on day D, sec_sentiment is the score
# from the MOST RECENT 10-K/10-Q/8-K filed on or before D.  This treats the
# SEC signal as a regime indicator: management's latest reading on the
# business, carried forward until the next filing supersedes it.
#
# COMBINED SCORE
# --------------
# The unified score blends both signals.  Weights:
#   w_news = 0.70   (daily news reacts to new information fast)
#   w_sec  = 0.30   (SEC is slower but more "grounded" -- 50-page narrative
#                    vs single-headline reactions)
#
# If SEC data is older than SEC_STALE_DAYS (default 180), we drop its weight
# and use news alone.  Stale SEC data is worse than no SEC data -- the regime
# may have shifted dramatically.
#
# OUTPUT
# ------
# data/raw/combined_sentiment_{TICKER}.csv -- one row per trading day with
# both signals visible.  signal_engine.py reads this file to compute
# agreement-based confidence tiers.
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

RAW_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "raw")
)

# =============================================================================
# Weighting scheme (Path A, 2026-04-25)
# =============================================================================
# Three-stream blend, replacing the old two-stream news/sec split:
#
#   WEIGHT_NEWS           = 0.50   daily news headlines (Finnhub)
#   WEIGHT_SEC_EARNINGS   = 0.35   8-K Item 2.02 + Exhibit 99.1 prepared remarks
#   WEIGHT_SEC_OTHER      = 0.15   10-K MD&A, 10-Q MD&A, non-earnings 8-K covers
#
# WHY EARNINGS GETS HIGHER WEIGHT THAN OTHER SEC:
#   Item 2.02 / Exhibit 99.1 press releases contain the prepared-remarks
#   portion of the earnings call -- forward guidance, CFO commentary on the
#   just-closed quarter, and the company's official narrative on margin and
#   demand trends.  This is the most time-relevant SEC content available
#   (90-day relevance, vs annual or risk-factor language in 10-K MD&A
#   that's often boilerplate carried forward from prior filings).
#
#   Q&A transcripts (analyst questions + spontaneous management answers)
#   would carry even higher information value, but those are NOT filed
#   with the SEC.  Q&A integration is deferred to a paid-feed session
#   (Decision 8 candidate per PROJECT_STATE.md §10.1.4).
#
# DROP-MISSING-WEIGHT POLICY (no renormalization):
#   When a sentiment stream is unavailable, its weight is dropped rather
#   than renormalized.  This means days with fewer streams have
#   proportionally lower total weighted score magnitude, which is
#   intentional: a day with only news sentiment carries less conviction
#   than a day with all three streams aligned.  Consistent with the
#   pre-Path-A two-stream behaviour.
#
# FORWARD-FILL DECAY:
#   Earnings sentiment forward-fills for 90 days (one quarter of relevance,
#   then stale -- the next earnings call is the next read).
#   Other-SEC forward-fills for 180 days (matches old SEC_STALE_DAYS).
# =============================================================================

# Tunable weights / staleness
WEIGHT_NEWS         = 0.50
WEIGHT_SEC_EARNINGS = 0.35
WEIGHT_SEC_OTHER    = 0.15

EARNINGS_STALE_DAYS = 90    # earnings prepared-remarks decay after one quarter
SEC_STALE_DAYS      = 180   # other-SEC decay after two quarters
NEWS_MIN_ARTICLES   = 1     # days with < this many articles are treated as missing

# Backwards-compat alias: callers reading WEIGHT_SEC may exist; map to the
# combined SEC weight (sum of earnings + other) for any legacy probe.
WEIGHT_SEC = WEIGHT_SEC_EARNINGS + WEIGHT_SEC_OTHER


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_news_sentiment(ticker: str) -> pd.DataFrame:
    """
    Concatenate every per-day news-sentiment CSV for `ticker` into a single
    DataFrame indexed by date.  Columns: sentiment_score, headline_count,
    bullish_pct, bearish_pct, neutral_pct.
    """
    ticker = ticker.upper()
    # scorer.py writes sentiment_{TICKER}_{DATE}.csv.  aggregator.py writes
    # a merged daily summary -- but we skip that here and do our own
    # aggregation so the merger can reason about headline_count etc.
    pattern = os.path.join(RAW_DIR, f"sentiment_{ticker}_*.csv")
    files = [f for f in sorted(glob.glob(pattern))
             if not os.path.basename(f).startswith("sentiment_summary_")]
    if not files:
        return pd.DataFrame()

    frames = [pd.read_csv(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    if "date" not in df.columns:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    # Weighted daily aggregation across all rows for the same day.
    agg_rows = []
    for (ticker_val, date_val), grp in df.groupby(["ticker", "date"]):
        total_n = float(grp.get("headline_count", pd.Series([1]*len(grp))).sum())
        if total_n <= 0:
            total_n = float(len(grp))
        weighted = float((grp["sentiment_score"] *
                          grp.get("headline_count", 1)).sum() / total_n)
        agg_rows.append({
            "date":             date_val,
            "ticker":           ticker_val,
            "news_sentiment":   round(weighted, 4),
            "news_headline_count": int(total_n),
            "bullish_pct":      float(grp.get("bullish_pct", pd.Series([0])).mean()),
            "bearish_pct":      float(grp.get("bearish_pct", pd.Series([0])).mean()),
            "neutral_pct":      float(grp.get("neutral_pct", pd.Series([0])).mean()),
        })
    return pd.DataFrame(agg_rows).sort_values("date").reset_index(drop=True)


def load_sec_sentiment(ticker: str) -> pd.DataFrame:
    """
    Load sec_sentiment_{TICKER}.csv.  Each row is one filing with a single
    aggregate score; merger.forward-fills these onto the daily grid.

    Backwards compat: rows produced before the 2026-04-25 Path A upgrade
    don't have a `subcategory` column.  We backfill it from `filing_type`:
    10-K -> 10-K_mdna, 10-Q -> 10-Q_mdna, 8-K -> 8-K_other (conservative
    -- without the cover-page Item 2.02 check we can't distinguish
    earnings 8-Ks from non-earnings, and treating them all as "other"
    preserves the pre-Path-A behaviour where every 8-K was scored
    uniformly into the single sec_sentiment stream).
    """
    path = os.path.join(RAW_DIR, f"sec_sentiment_{ticker.upper()}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["filing_date"] = pd.to_datetime(df["filing_date"]).dt.normalize()
    if "subcategory" not in df.columns:
        df["subcategory"] = df["filing_type"].map({
            "10-K": "10-K_mdna",
            "10-Q": "10-Q_mdna",
            "8-K":  "8-K_other",
        }).fillna(df["filing_type"])
    df = df.sort_values("filing_date").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Combine daily news + quarterly SEC into a daily series
# ---------------------------------------------------------------------------

def build_combined(
    ticker: str,
    start_date: Optional[datetime.date] = None,
    end_date:   Optional[datetime.date] = None,
    save: bool = True,
) -> pd.DataFrame:
    """
    Build the unified daily sentiment frame for `ticker`.  If no bounds are
    given the frame spans from the earliest available data to today.

    Returns an empty DataFrame if neither data source exists.
    """
    news = load_news_sentiment(ticker)
    sec  = load_sec_sentiment(ticker)

    # ETFs / non-issuer tickers: the build proceeds normally on the news
    # stream; we just announce the SEC absence so log readers don't hunt
    # for missing files.  build_combined still produces a valid daily
    # frame with sec_* columns set to NaN and combined_sentiment falling
    # back to news_sentiment via the only_n branch below.
    if ticker.upper() in getattr(config, "ETF_TICKERS", set()) and sec.empty:
        print(f"[merger] {ticker}: ETF / non-issuer -- "
              f"no SEC data, news-only sentiment.")

    if news.empty and sec.empty:
        print(f"[merger] No sentiment data of any kind for {ticker}.")
        return pd.DataFrame()

    # --- 1. Determine the date grid ---
    earliest_candidates = []
    latest_candidates   = []
    if not news.empty:
        earliest_candidates.append(news["date"].min().date())
        latest_candidates.append(news["date"].max().date())
    if not sec.empty:
        earliest_candidates.append(sec["filing_date"].min().date())
        latest_candidates.append(sec["filing_date"].max().date())

    grid_start = start_date or min(earliest_candidates)
    grid_end   = end_date   or max(latest_candidates + [datetime.date.today()])

    # Business days only (matches price/options data frequency)
    grid = pd.bdate_range(grid_start, grid_end, name="date")
    base = pd.DataFrame({"date": grid, "ticker": ticker.upper()})

    # --- 2. Join news (daily) ---
    if not news.empty:
        base = base.merge(news.drop(columns=["ticker"]), on="date", how="left")
    else:
        for c in ["news_sentiment", "news_headline_count",
                  "bullish_pct", "bearish_pct", "neutral_pct"]:
            base[c] = np.nan

    # --- 3. Forward-fill SEC onto the grid (split by subcategory) ---
    # We forward-fill earnings ("8-K_earnings_prepared") and other (10-K,
    # 10-Q, non-earnings 8-K, 8-K_earnings_cover) as TWO independent
    # streams, each with its own staleness.  This lets the daily blend
    # weight earnings prepared-remarks (high time-relevance, 90d decay)
    # higher than the slower-cadence MD&A / risk-factor language (180d
    # decay) without the two cancelling each other out via averaging.
    EARNINGS_SUBS = {"8-K_earnings_prepared", "8-K_earnings_cover"}
    if not sec.empty:
        sec_e = sec[sec["subcategory"].isin(EARNINGS_SUBS)].copy()
        sec_o = sec[~sec["subcategory"].isin(EARNINGS_SUBS)].copy()

        # Earnings stream
        if not sec_e.empty:
            le = sec_e.rename(columns={
                "filing_date":     "date",
                "sentiment_score": "sec_earnings_sentiment",
            })[["date", "sec_earnings_sentiment"]]
            le["sec_earnings_filing_date"] = le["date"]
            base = base.merge(le, on="date", how="left")
            for c in ["sec_earnings_sentiment", "sec_earnings_filing_date"]:
                base[c] = base[c].ffill()
        else:
            base["sec_earnings_sentiment"]    = np.nan
            base["sec_earnings_filing_date"]  = pd.NaT

        # Other-SEC stream (10-K, 10-Q, non-earnings 8-K)
        if not sec_o.empty:
            lo = sec_o.rename(columns={
                "filing_date":     "date",
                "sentiment_score": "sec_other_sentiment",
                "filing_type":     "sec_other_filing_type",
            })[["date", "sec_other_sentiment", "sec_other_filing_type"]]
            lo["sec_other_filing_date"] = lo["date"]
            base = base.merge(lo, on="date", how="left")
            for c in ["sec_other_sentiment", "sec_other_filing_type",
                      "sec_other_filing_date"]:
                base[c] = base[c].ffill()
        else:
            base["sec_other_sentiment"]    = np.nan
            base["sec_other_filing_type"]  = np.nan
            base["sec_other_filing_date"]  = pd.NaT
    else:
        for c in ["sec_earnings_sentiment", "sec_earnings_filing_date",
                  "sec_other_sentiment",    "sec_other_filing_type",
                  "sec_other_filing_date"]:
            base[c] = np.nan

    # --- 4. Per-stream staleness ---
    base["sec_earnings_age_days"] = (
        (pd.to_datetime(base["date"]) -
         pd.to_datetime(base["sec_earnings_filing_date"]))
        .dt.days
    )
    base["sec_other_age_days"] = (
        (pd.to_datetime(base["date"]) -
         pd.to_datetime(base["sec_other_filing_date"]))
        .dt.days
    )
    earnings_stale = base["sec_earnings_age_days"].fillna(9999) > EARNINGS_STALE_DAYS
    other_stale    = base["sec_other_age_days"].fillna(9999)    > SEC_STALE_DAYS

    # --- 5. Backwards-compat single sec_sentiment column for engine.py ---
    # The backtest engine reads `combined_sentiment_{TICKER}.csv` and looks
    # for `sec_sentiment` (singular) to build sec_score_map for the
    # `sec_aligned` feature.  We expose a single column = earnings if
    # available and not stale, else other if available and not stale,
    # else NaN.  Engine code untouched.
    base["sec_sentiment"] = np.where(
        base["sec_earnings_sentiment"].notna() & ~earnings_stale,
        base["sec_earnings_sentiment"],
        np.where(
            base["sec_other_sentiment"].notna() & ~other_stale,
            base["sec_other_sentiment"],
            np.nan,
        ),
    )
    base["sec_filing_type"] = np.where(
        base["sec_earnings_sentiment"].notna() & ~earnings_stale,
        "8-K_earnings",
        base.get("sec_other_filing_type", np.nan),
    )
    base["sec_filing_date"] = np.where(
        base["sec_earnings_sentiment"].notna() & ~earnings_stale,
        base["sec_earnings_filing_date"],
        base["sec_other_filing_date"],
    )
    base["sec_age_days"] = np.where(
        base["sec_earnings_sentiment"].notna() & ~earnings_stale,
        base["sec_earnings_age_days"],
        base["sec_other_age_days"],
    )

    # --- 6. Combined sentiment (3-stream, drop-missing-weight) ---
    news_valid     = base["news_sentiment"].notna() & \
                     (base["news_headline_count"].fillna(0) >= NEWS_MIN_ARTICLES)
    earnings_valid = base["sec_earnings_sentiment"].notna() & ~earnings_stale
    other_valid    = base["sec_other_sentiment"].notna()    & ~other_stale

    n  = base["news_sentiment"].fillna(0.0)
    se = base["sec_earnings_sentiment"].fillna(0.0)
    so = base["sec_other_sentiment"].fillna(0.0)

    # Drop missing weight: when a stream is unavailable on a date, its
    # term contributes 0 (because the score is masked to 0 above) AND
    # its weight is implicitly excluded.  This means a date with only
    # news has combined = 0.50 * news, NOT renormalized to 1.00 * news.
    # See module-level comment block for the rationale.
    base["combined_sentiment"] = np.where(
        news_valid | earnings_valid | other_valid,
        (WEIGHT_NEWS         * n.where(news_valid,     0.0))
      + (WEIGHT_SEC_EARNINGS * se.where(earnings_valid, 0.0))
      + (WEIGHT_SEC_OTHER    * so.where(other_valid,    0.0)),
        np.nan,
    )

    # Backwards-compat sec_available + sec_stale flags (single SEC view)
    base["news_available"]     = news_valid
    base["sec_earnings_available"] = earnings_valid
    base["sec_other_available"]    = other_valid
    base["sec_available"]      = earnings_valid | other_valid
    base["sec_stale"]          = (
        (base["sec_earnings_sentiment"].notna() & earnings_stale) |
        (base["sec_other_sentiment"].notna()    & other_stale)
    )

    # Round for readability
    for c in ["news_sentiment", "sec_sentiment",
              "sec_earnings_sentiment", "sec_other_sentiment",
              "combined_sentiment"]:
        if c in base.columns:
            base[c] = base[c].astype(float).round(4)

    base = base.sort_values("date").reset_index(drop=True)

    if save:
        out = os.path.join(RAW_DIR, f"combined_sentiment_{ticker.upper()}.csv")
        base.to_csv(out, index=False)
        n_news = int(news_valid.sum())
        n_earn = int(earnings_valid.sum())
        n_oth  = int(other_valid.sum())
        n_comb = int(base["combined_sentiment"].notna().sum())
        print(f"[merger] Saved -> {out}  ({len(base)} rows; "
              f"news={n_news}, earnings={n_earn}, other={n_oth}, "
              f"combined={n_comb})")

    return base


def load_combined(ticker: str) -> pd.DataFrame:
    """Load a previously saved combined-sentiment CSV (if one exists)."""
    path = os.path.join(RAW_DIR, f"combined_sentiment_{ticker.upper()}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df


# ---------------------------------------------------------------------------
# Latest-row convenience (used by signal_engine)
# ---------------------------------------------------------------------------

def latest_combined_row(ticker: str) -> Optional[dict]:
    """
    Return the most recent row of combined sentiment as a dict, or None if
    no data is available.  signal_engine calls this to get today's
    news + SEC pair.
    """
    df = load_combined(ticker)
    if df.empty:
        return None
    # Prefer the latest row where combined_sentiment is populated
    valid = df[df["combined_sentiment"].notna()]
    if valid.empty:
        return None
    r = valid.iloc[-1]
    return {
        "date":                 r["date"].date(),
        "news_sentiment":       None if pd.isna(r.get("news_sentiment")) else float(r["news_sentiment"]),
        "sec_sentiment":        None if pd.isna(r.get("sec_sentiment")) else float(r["sec_sentiment"]),
        "combined_sentiment":   None if pd.isna(r.get("combined_sentiment")) else float(r["combined_sentiment"]),
        "news_headline_count":  int(r.get("news_headline_count") or 0),
        "sec_filing_type":      None if pd.isna(r.get("sec_filing_type")) else str(r["sec_filing_type"]),
        "sec_filing_date":      None if pd.isna(r.get("sec_filing_date")) else
                                  pd.to_datetime(r["sec_filing_date"]).date(),
        "sec_age_days":         None if pd.isna(r.get("sec_age_days")) else int(r["sec_age_days"]),
        "sec_stale":            bool(r.get("sec_stale") or False),
        "news_available":       bool(r.get("news_available") or False),
        "sec_available":        bool(r.get("sec_available") or False),
    }


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", default="AAPL")
    args = p.parse_args()

    df = build_combined(args.ticker)
    if not df.empty:
        cols = ["date", "news_sentiment", "news_headline_count",
                "sec_sentiment", "sec_filing_type", "sec_age_days",
                "combined_sentiment"]
        print(df[cols].tail(10).to_string(index=False))

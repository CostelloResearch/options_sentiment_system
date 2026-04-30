# =============================================================================
# sentiment/aggregator.py — Multi-day sentiment aggregation & momentum
#
# The scorer.py output is one row per day.  This module loads *all* available
# daily sentiment CSVs for a ticker and:
#
#   1. Builds a continuous time series (back-fills missing days with NaN so
#      the rolling window behaves correctly)
#   2. Computes a 5-day rolling average to smooth out single-day noise
#   3. Detects momentum: if the *raw* daily score has been moving in the same
#      direction for 3+ consecutive days, we label it RISING / FALLING
#   4. Returns a clean summary DataFrame ready for the signal engine
#
# WHY A ROLLING AVERAGE?
#   A single day's news can be dominated by one big story that doesn't
#   represent the broader sentiment trend.  A 5-day EMA is common in
#   practitioner sentiment models; here we use a simple mean for
#   transparency, but the window length is configurable.
#
# OUTPUT SCHEMA:
#   ticker, date, raw_score, rolling_score, headline_count,
#   momentum_label, momentum_days
# =============================================================================

import os
import sys
import glob
import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def load_sentiment_csvs(ticker: str, raw_dir: str = None) -> pd.DataFrame:
    """
    Glob all sentiment_{ticker}_*.csv files and stack them into one DataFrame.

    Parameters
    ----------
    ticker : str
        Stock symbol.
    raw_dir : str, optional
        Directory to search. Defaults to data/raw/ relative to this file.

    Returns
    -------
    pd.DataFrame sorted by date (oldest first), or empty DataFrame if
    no files are found.
    """
    if raw_dir is None:
        raw_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "data", "raw")
        )

    pattern = os.path.join(raw_dir, f"sentiment_{ticker}_*.csv")
    files = sorted(glob.glob(pattern))

    # sentiment_summary_{ticker}.csv is OUR own output -- exclude it to avoid
    # a feedback loop where we re-aggregate the aggregated file.
    files = [f for f in files
             if not os.path.basename(f).startswith(f"sentiment_summary_")]

    if not files:
        print(f"[aggregator] No sentiment CSVs found for {ticker} in {raw_dir}.")
        return pd.DataFrame()

    print(f"[aggregator] Found {len(files)} sentiment CSV(s) for {ticker}.")

    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f))
        except Exception as e:
            print(f"[aggregator] WARNING: Could not read {f}: {e}")

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date

    # Each daily file covers a multi-day lookback window, so stacking all files
    # produces multiple rows for the same date.  Keep the row with the highest
    # headline_count — the most comprehensive single scrape for that day.
    if df.duplicated(subset=["ticker", "date"]).any():
        df = (
            df.sort_values("headline_count", ascending=False)
              .drop_duplicates(subset=["ticker", "date"], keep="first")
        )

    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------------
# Gap filling
# ---------------------------------------------------------------------------

def _fill_date_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reindex to a continuous daily date range so rolling windows work correctly.

    Without this, a weekend gap between Friday and Monday would look like
    consecutive days, making the rolling average silently wrong.

    Fills missing days with NaN scores and 0 headline counts.
    """
    if df.empty:
        return df

    ticker = df["ticker"].iloc[0]
    full_range = pd.date_range(df["date"].min(), df["date"].max(), freq="D")

    # Build a scaffold with every calendar day
    scaffold = pd.DataFrame({"date": [d.date() for d in full_range]})
    scaffold["ticker"] = ticker

    merged = scaffold.merge(df, on=["ticker", "date"], how="left")
    merged["headline_count"] = merged["headline_count"].fillna(0).astype(int)
    # sentiment_score stays NaN for days with no data — this is correct:
    # rolling(min_periods=1) will skip NaN slots automatically

    return merged


# ---------------------------------------------------------------------------
# Rolling average
# ---------------------------------------------------------------------------

def compute_rolling_sentiment(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """
    Add a `rolling_score` column: the simple moving average of `raw_score`
    over `window` calendar days (NaN days are skipped via min_periods=1).

    Parameters
    ----------
    df : pd.DataFrame
        Must have a `sentiment_score` column.
    window : int
        Look-back window in days (default 5).

    Returns
    -------
    pd.DataFrame with `raw_score` and `rolling_score` columns added.
    """
    df = df.copy()
    # Rename for clarity in the output
    df.rename(columns={"sentiment_score": "raw_score"}, inplace=True)

    # min_periods=1 means we output a value even with fewer than `window` days
    # of data (at the start of the series), rather than producing NaN.
    df["rolling_score"] = (
        df["raw_score"]
        .rolling(window=window, min_periods=1)
        .mean()
        .round(4)
    )
    return df


# ---------------------------------------------------------------------------
# Momentum detection
# ---------------------------------------------------------------------------

def detect_momentum(df: pd.DataFrame, min_streak: int = 3) -> pd.DataFrame:
    """
    Label each row with a momentum direction if the *raw* daily score has
    been moving in the same direction for `min_streak` or more days.

    Algorithm:
      - Compute day-over-day change in raw_score
      - Find the longest *current* streak of positive / negative changes
      - Label the streak rows accordingly

    Labels: 'RISING', 'FALLING', or '' (no clear momentum)

    Parameters
    ----------
    df : pd.DataFrame
        Must have a `raw_score` column, sorted by date ascending.
    min_streak : int
        How many consecutive same-direction days to qualify as momentum.

    Returns
    -------
    df with `momentum_label` and `momentum_days` columns added.
    """
    df = df.copy()
    df["momentum_label"] = ""
    df["momentum_days"] = 0

    if len(df) < 2:
        return df

    # Day-over-day change; NaN rows get direction 0 (no signal)
    direction = np.sign(df["raw_score"].diff().fillna(0)).astype(int)

    # Walk through and count consecutive runs
    streak = 1
    streak_dir = int(direction.iloc[1]) if len(direction) > 1 else 0

    for i in range(1, len(df)):
        cur_dir = int(direction.iloc[i])

        if cur_dir != 0 and cur_dir == streak_dir:
            streak += 1
        else:
            streak = 1
            streak_dir = cur_dir

        if streak >= min_streak and streak_dir != 0:
            df.loc[df.index[i], "momentum_label"] = (
                "RISING" if streak_dir > 0 else "FALLING"
            )
            df.loc[df.index[i], "momentum_days"] = streak

    return df


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_sentiment_summary(
    ticker: str,
    raw_dir: str = None,
    rolling_window: int = 5,
    momentum_streak: int = 3,
    save: bool = True,
) -> pd.DataFrame:
    """
    Full aggregation pipeline for one ticker.

    Steps:
      1. Load all sentiment CSVs for the ticker
      2. Fill date gaps
      3. Compute rolling average
      4. Detect momentum streaks
      5. Optionally save to data/raw/sentiment_summary_{ticker}.csv

    Returns
    -------
    pd.DataFrame with columns:
        ticker, date, raw_score, rolling_score, headline_count,
        momentum_label, momentum_days
    """
    df = load_sentiment_csvs(ticker, raw_dir)
    if df.empty:
        return df

    df = _fill_date_gaps(df)
    df = compute_rolling_sentiment(df, window=rolling_window)
    df = detect_momentum(df, min_streak=momentum_streak)

    # Final column ordering for readability
    final_cols = [
        "ticker", "date", "raw_score", "rolling_score",
        "headline_count", "momentum_label", "momentum_days",
        # Carry through the % breakdowns if present
        *[c for c in ["bullish_pct", "bearish_pct", "neutral_pct"] if c in df.columns],
    ]
    df = df[[c for c in final_cols if c in df.columns]]

    if save:
        _save(df, ticker)

    return df


def build_all_summaries(tickers: list = None, **kwargs) -> dict[str, pd.DataFrame]:
    """Run build_sentiment_summary for every ticker in the list."""
    if tickers is None:
        tickers = config.TICKERS
    return {t: build_sentiment_summary(t, **kwargs) for t in tickers}


def _save(df: pd.DataFrame, ticker: str) -> str:
    raw_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    )
    os.makedirs(raw_dir, exist_ok=True)

    filename = f"sentiment_summary_{ticker}.csv"
    filepath = os.path.join(raw_dir, filename)
    df.to_csv(filepath, index=False)
    print(f"[aggregator] Saved -> {filepath}")
    return filepath


# ---------------------------------------------------------------------------
# Smoke test — uses synthetic data if no real sentiment CSVs exist yet
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import random

    TICKER = "AAPL"

    # Try to load real data first
    summary = build_sentiment_summary(TICKER, save=False)

    if summary.empty:
        # Generate 20 days of plausible fake scores so you can test the logic
        # without needing real FinBERT output yet.
        print("\n[aggregator] No real data found — using synthetic scores for demo.\n")
        random.seed(42)
        today = datetime.date.today()
        fake_rows = []
        score = 0.0
        for i in range(20):
            # Random-walk the score in [-1, +1]
            score = float(np.clip(score + random.uniform(-0.2, 0.2), -1.0, 1.0))
            fake_rows.append({
                "ticker": TICKER,
                "date": today - datetime.timedelta(days=19 - i),
                "sentiment_score": round(score, 4),
                "headline_count": random.randint(3, 30),
                "bullish_pct": 0.0,
                "bearish_pct": 0.0,
                "neutral_pct": 0.0,
            })
        raw_df = pd.DataFrame(fake_rows)

        # Run the pipeline on the synthetic data directly (skip CSV loading)
        raw_df = _fill_date_gaps(raw_df)
        raw_df = compute_rolling_sentiment(raw_df)
        summary = detect_momentum(raw_df)
        summary.rename(columns={"sentiment_score": "raw_score"}, errors="ignore",
                       inplace=True)

    print("=== Sentiment Summary ===")
    print(summary[["date", "raw_score", "rolling_score",
                    "momentum_label", "momentum_days"]].to_string(index=False))

    # Print current momentum status
    last = summary.iloc[-1]
    label = last["momentum_label"] or "NEUTRAL"
    print(f"\nLatest date    : {last['date']}")
    print(f"Raw score      : {last['raw_score']}")
    print(f"5-day rolling  : {last['rolling_score']}")
    print(f"Momentum       : {label} ({int(last['momentum_days'])} days)")

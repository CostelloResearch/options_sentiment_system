# =============================================================================
# scripts/sec_report.py -- Print a human-readable SEC sentiment report
#
# Loads data/raw/sec_sentiment_{TICKER}.csv (produced by sec_scorer.py) and
# prints:
#   * Counts by filing type
#   * Full per-filing table (date, type, score, chunks, top/bottom snippets)
#   * Rolling sentiment at known market-regime events (useful for sanity
#     checks -- the model should read tension during crashes/selloffs)
# =============================================================================

import os
import sys
import argparse
import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

RAW_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "raw")
)

# Known events to overlay against SEC sentiment.  Each entry = (label, date
# range) -- we show the filings that fell inside or were nearest to each
# window.
EVENT_WINDOWS = [
    ("COVID crash",          datetime.date(2020, 2, 15), datetime.date(2020, 5, 15)),
    ("2022 tech selloff",    datetime.date(2022, 1, 1),  datetime.date(2022, 12, 31)),
    ("2023 rate-hike peak",  datetime.date(2023, 1, 1),  datetime.date(2023, 12, 31)),
    ("2024-2025 recovery",   datetime.date(2024, 1, 1),  datetime.date(2025, 12, 31)),
]


def _load(ticker: str) -> pd.DataFrame:
    path = os.path.join(RAW_DIR, f"sec_sentiment_{ticker.upper()}.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"No sec_sentiment file at {path}. "
                                "Run sentiment/sec_scorer.py first.")
    df = pd.read_csv(path)
    df["filing_date"] = pd.to_datetime(df["filing_date"]).dt.date
    return df.sort_values("filing_date").reset_index(drop=True)


def _tier_label(score: float) -> str:
    if   score >  0.10: return "bullish"
    elif score < -0.10: return "bearish"
    else:               return "neutral"


def _print_header(title: str, width: int = 78) -> None:
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def _print_counts(df: pd.DataFrame) -> None:
    _print_header("FILING COUNTS")
    for form, grp in df.groupby("filing_type"):
        print(f"  {form:<6}: {len(grp)} filings  "
              f"({grp['filing_date'].min()} -> {grp['filing_date'].max()})")
    print(f"  TOTAL : {len(df)}")


def _print_per_filing(df: pd.DataFrame) -> None:
    _print_header("SENTIMENT SCORE PER FILING")
    print(f"  {'date':<12} {'type':<6} {'score':>8} {'chunks':>6} "
          f"{'bull%':>6} {'bear%':>6} {'zone'}")
    print(f"  {'-'*11:<12} {'-'*5:<6} {'-'*7:>8} {'-'*5:>6} "
          f"{'-'*5:>6} {'-'*5:>6} {'----'}")
    for _, r in df.iterrows():
        score = float(r["sentiment_score"])
        print(f"  {str(r['filing_date']):<12} {r['filing_type']:<6} "
              f"{score:>+8.4f} {int(r['chunk_count']):>6d} "
              f"{float(r['bullish_pct']):>6.1f} "
              f"{float(r['bearish_pct']):>6.1f}  "
              f"{_tier_label(score)}")


def _print_event_windows(df: pd.DataFrame) -> None:
    _print_header("SENTIMENT AROUND KNOWN EVENTS")
    data_earliest = df["filing_date"].min()
    data_latest   = df["filing_date"].max()
    print(f"  Data window: {data_earliest} to {data_latest}\n")

    for label, start, end in EVENT_WINDOWS:
        in_range = df[(df["filing_date"] >= start) & (df["filing_date"] <= end)]
        print(f"  * {label}  [{start} to {end}]")
        if in_range.empty:
            coverage = "none"
            if start > data_latest:
                coverage = "after data window"
            elif end < data_earliest:
                coverage = "before data window"
            print(f"      no filings in window ({coverage})")
        else:
            avg = in_range["sentiment_score"].mean()
            print(f"      {len(in_range)} filings  "
                  f"avg score {avg:+.4f}  ({_tier_label(avg)})")
            for _, r in in_range.iterrows():
                print(f"        - {r['filing_date']}  {r['filing_type']:<4}  "
                      f"{float(r['sentiment_score']):+.4f}")
        print()


def _print_extreme_chunks(df: pd.DataFrame, top_n: int = 3) -> None:
    _print_header("MOST BEARISH / BULLISH CHUNKS (top 3 each)")
    bears = df.nsmallest(top_n, "sentiment_score")
    bulls = df.nlargest(top_n, "sentiment_score")

    print("\n  BEARISH:")
    for _, r in bears.iterrows():
        print(f"  [{r['filing_date']} {r['filing_type']}  "
              f"score={float(r['sentiment_score']):+.4f}]")
        snippet = str(r.get("most_bearish_chunk", ""))[:300]
        print(f"    {snippet}...\n")

    print("  BULLISH:")
    for _, r in bulls.iterrows():
        print(f"  [{r['filing_date']} {r['filing_type']}  "
              f"score={float(r['sentiment_score']):+.4f}]")
        snippet = str(r.get("most_bullish_chunk", ""))[:300]
        print(f"    {snippet}...\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="AAPL")
    args = ap.parse_args()

    df = _load(args.ticker)
    print(f"\nSEC SENTIMENT REPORT -- {args.ticker.upper()}")
    print(f"Loaded {len(df)} filings from "
          f"data/raw/sec_sentiment_{args.ticker.upper()}.csv")

    _print_counts(df)
    _print_per_filing(df)
    _print_event_windows(df)
    _print_extreme_chunks(df)


if __name__ == "__main__":
    main()

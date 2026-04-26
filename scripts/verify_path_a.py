# =============================================================================
# scripts/verify_path_a.py -- PART 7 verification for the Path A upgrade
#
# Three checks:
#   1. AAPL old-vs-new sentiment correlation on post-2022 10-Qs
#      (validates that the MD&A regex fix changed scoring behaviour)
#   2. Per-ticker spot check: does earnings_sentiment carry meaningful
#      variance and differ from news_sentiment on the same dates?
#   3. R3 smoke test: r3_baseline drift verdict should still be MATCH
#      (demo mode bypasses combined_sentiment, so the new merger
#      weighting MUST be a no-op for the demo backtest)
# =============================================================================

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

RAW_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__),
                                        "..", "data", "raw"))


def check_aapl_correlation():
    """Compare pre-fix vs post-fix AAPL SEC sentiment scores on post-2022 10-Qs."""
    print("=" * 72)
    print("CHECK 1: AAPL pre-fix vs post-fix correlation (post-2022 10-Qs)")
    print("=" * 72)
    old_path = os.path.join(RAW_DIR, "sec_sentiment_AAPL_pre-fix.csv")
    new_path = os.path.join(RAW_DIR, "sec_sentiment_AAPL.csv")
    if not os.path.exists(old_path) or not os.path.exists(new_path):
        print(f"  missing CSV: old={os.path.exists(old_path)} "
              f"new={os.path.exists(new_path)}")
        return None

    old = pd.read_csv(old_path, parse_dates=["filing_date"])
    new = pd.read_csv(new_path, parse_dates=["filing_date"])

    # Restrict to 10-Q filings filed 2022 or later.  The text content for
    # these changed (fixed regex picks the actual MD&A slice instead of
    # tail-of-doc), so divergent scores would be evidence the prior 5-ticker
    # AAPL SEC sentiment was based on partly-broken text.
    def filter_post2022_10q(df):
        return df[
            (df["filing_type"] == "10-Q") &
            (df["filing_date"].dt.year >= 2022)
        ].sort_values("filing_date")

    o = filter_post2022_10q(old)
    n = filter_post2022_10q(new)
    print(f"  old corpus: {len(o)} filings, new corpus: {len(n)} filings")

    merged = o[["filing_date", "sentiment_score"]].rename(
        columns={"sentiment_score": "score_old"}
    ).merge(
        n[["filing_date", "sentiment_score"]].rename(
            columns={"sentiment_score": "score_new"}
        ),
        on="filing_date", how="inner",
    )
    print(f"  matched on filing_date: {len(merged)} pairs")

    if len(merged) < 3:
        print(f"  too few pairs for correlation; raw scores:")
        print(merged.to_string(index=False))
        return None

    print()
    print(merged.to_string(index=False))
    corr = merged[["score_old", "score_new"]].corr().iloc[0, 1]
    print(f"\n  Pearson correlation (old, new): {corr:+.4f}")
    diff = (merged["score_new"] - merged["score_old"]).abs().mean()
    print(f"  Mean absolute score diff:       {diff:.4f}")
    if abs(corr) < 0.7:
        print(f"\n  >>> FLAG: |correlation| < 0.70 -- prior AAPL SEC "
              f"sentiment used in 5-ticker backtesting was partially "
              f"based on broken text extraction.")
    else:
        print(f"\n  Correlation >= 0.70 -- the regex fix changed individual "
              f"scores but didn't reorder the corpus materially.")
    return {"corr": corr, "n": len(merged), "diff": diff}


def check_earnings_vs_news():
    """For each single-name ticker, does earnings sentiment carry signal?"""
    print()
    print("=" * 72)
    print("CHECK 2: earnings_sentiment vs news_sentiment per ticker")
    print("=" * 72)
    rows = []
    for ticker in config.TICKERS:
        path = os.path.join(RAW_DIR, f"combined_sentiment_{ticker}.csv")
        if not os.path.exists(path):
            print(f"  {ticker}: no combined_sentiment CSV (run merger first)")
            continue
        df = pd.read_csv(path, parse_dates=["date"])
        n_dates  = len(df)
        n_news   = int(df["news_sentiment"].notna().sum()) \
                   if "news_sentiment" in df.columns else 0
        n_earn   = int(df.get("sec_earnings_sentiment",
                              pd.Series(dtype=float)).notna().sum())
        n_other  = int(df.get("sec_other_sentiment",
                              pd.Series(dtype=float)).notna().sum())

        # Compare earnings vs news on dates where both are present
        if n_news and n_earn and "sec_earnings_sentiment" in df.columns:
            both = df.dropna(subset=["news_sentiment", "sec_earnings_sentiment"])
            if len(both) >= 3:
                corr = both[["news_sentiment", "sec_earnings_sentiment"]] \
                       .corr().iloc[0, 1]
                diverge_share = float(
                    ((both["news_sentiment"] - both["sec_earnings_sentiment"]).abs()
                     > 0.20).mean()
                )
            else:
                corr, diverge_share = float("nan"), float("nan")
        else:
            corr, diverge_share = float("nan"), float("nan")

        # Variance of earnings stream (std)
        earn_std = float(df.get("sec_earnings_sentiment",
                                pd.Series(dtype=float)).std())
        news_std = float(df.get("news_sentiment",
                                pd.Series(dtype=float)).std())

        rows.append({
            "ticker":    ticker,
            "n_dates":   n_dates,
            "n_news":    n_news,
            "n_earn":    n_earn,
            "n_other":   n_other,
            "earn_std":  round(earn_std, 4) if not np.isnan(earn_std) else None,
            "news_std":  round(news_std, 4) if not np.isnan(news_std) else None,
            "corr_news_vs_earn": round(corr, 4) if not np.isnan(corr) else None,
            "diverge>=0.2":      round(diverge_share, 3)
                                  if not np.isnan(diverge_share) else None,
        })
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    print()
    print("  earn_std = std of sec_earnings_sentiment column "
          "(meaningful variance > 0)")
    print("  corr_news_vs_earn = Pearson on dates where both are present "
          "(low corr = independent signal)")
    print("  diverge>=0.2 = share of overlap dates where |news - earnings| "
          ">= 0.20 (low corr OR high divergence suggests earnings adds info)")
    return df


def check_r3_smoke_test():
    """R3 smoke test: drift verdict should still be MATCH after Path A.
    Demo-mode backtest doesn't read combined_sentiment, so the new merger
    weighting must NOT change R3 numbers."""
    print()
    print("=" * 72)
    print("CHECK 3: R3 drift smoke test (demo mode bypasses combined_sentiment)")
    print("=" * 72)
    print("  Run separately:")
    print("    .venv/Scripts/python.exe scripts/r3_baseline.py --skip-run")
    print("  Expected: both R3 and flat verdicts MATCH (byte-identical).")
    print("  Any drift = code regression, not a Path A side-effect.")


if __name__ == "__main__":
    check_aapl_correlation()
    check_earnings_vs_news()
    check_r3_smoke_test()

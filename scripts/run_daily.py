# =============================================================================
# scripts/run_daily.py -- Automated daily pipeline runner
#
# USAGE
# -----
#   python scripts/run_daily.py              # normal run (skips weekends/holidays)
#   python scripts/run_daily.py --force      # run even on weekends/holidays
#   python scripts/run_daily.py --dry-run    # show what would run, don't execute
#   python scripts/run_daily.py --tickers AAPL NVDA   # override ticker list
#
# OUTPUT
# ------
#   logs/pipeline_YYYY-MM-DD.log   -- full timestamped output from every step
#   logs/daily_summary.txt         -- human-readable one-page summary (overwritten daily)
#
# DESIGN NOTES
# ------------
# • All print() output from imported modules is captured to the log file AND
#   written to the console simultaneously (a "tee" pattern).  You'll see live
#   progress AND have a permanent record.
#
# • Each ticker runs inside its own try/except.  A failure in NVDA's options
#   fetch will not prevent AAPL's sentiment score from running.
#
# • US market holidays are computed from rules (no external library needed).
#   The holiday set is regenerated each run so the script works correctly
#   across year boundaries without any maintenance.
# =============================================================================

import os
import sys
import math
import argparse
import datetime
import traceback
import time

import pandas as pd

# ---------------------------------------------------------------------------
# Path setup -- allow running from any working directory
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

import config


# ===========================================================================
# Tee writer -- duplicates every print() to both console and log file
# ===========================================================================

class _Tee:
    """
    Wraps a file and a stream so writes go to both simultaneously.
    Assigned to sys.stdout/sys.stderr so all module print() calls
    are automatically captured without changing any other code.
    """
    def __init__(self, file_handle, original_stream):
        self._file   = file_handle
        self._stream = original_stream

    def write(self, text):
        self._file.write(text)
        self._stream.write(text)

    def flush(self):
        self._file.flush()
        self._stream.flush()

    def fileno(self):
        # Some libraries call fileno() on stdout -- delegate to original
        return self._stream.fileno()


# ===========================================================================
# US market holiday calculator (no external library)
# ===========================================================================

def _easter(year: int) -> datetime.date:
    """
    Compute Easter Sunday via the Anonymous Gregorian Algorithm.
    Used to derive Good Friday (Easter - 2 days).
    """
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f    = (b + 8) // 25
    g    = (b - f + 1) // 3
    h    = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l    = (32 + 2 * e + 2 * i - h - k) % 7
    m    = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day   = (h + l - 7 * m + 114) % 31 + 1
    return datetime.date(year, month, day)


def _observed(d: datetime.date) -> datetime.date:
    """
    Shift a fixed-date holiday to its observed weekday.
    Saturday -> Friday before; Sunday -> Monday after.
    """
    if d.weekday() == 5:   # Saturday
        return d - datetime.timedelta(days=1)
    if d.weekday() == 6:   # Sunday
        return d + datetime.timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime.date:
    """
    Return the n-th occurrence of `weekday` (0=Mon…6=Sun) in the given month.
    n=1 → first, n=2 → second, n=-1 → last.
    """
    if n > 0:
        first  = datetime.date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + datetime.timedelta(days=offset + (n - 1) * 7)
    else:
        # Last occurrence: find last day of month then step back
        if month == 12:
            last = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        else:
            last = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        offset = (last.weekday() - weekday) % 7
        return last - datetime.timedelta(days=offset)


def us_market_holidays(year: int) -> frozenset[datetime.date]:
    """
    Return the set of NYSE market holidays for `year`.
    Covers all 9 standard NYSE holidays (New Year's, MLK, Presidents,
    Good Friday, Memorial, Juneteenth, Independence, Labor, Thanksgiving,
    Christmas) with Saturday/Sunday observance shifts.
    """
    return frozenset({
        _observed(datetime.date(year, 1, 1)),           # New Year's Day
        _nth_weekday(year, 1, 0, 3),                    # MLK Day (3rd Mon Jan)
        _nth_weekday(year, 2, 0, 3),                    # Presidents' Day (3rd Mon Feb)
        _easter(year) - datetime.timedelta(days=2),     # Good Friday
        _nth_weekday(year, 5, 0, -1),                   # Memorial Day (last Mon May)
        _observed(datetime.date(year, 6, 19)),          # Juneteenth
        _observed(datetime.date(year, 7, 4)),           # Independence Day
        _nth_weekday(year, 9, 0, 1),                    # Labor Day (1st Mon Sep)
        _nth_weekday(year, 11, 3, 4),                   # Thanksgiving (4th Thu Nov)
        _observed(datetime.date(year, 12, 25)),         # Christmas
    })


def is_trading_day(date: datetime.date = None) -> tuple[bool, str]:
    """
    Return (True, reason) if `date` is a NYSE trading day, else (False, reason).
    """
    if date is None:
        date = datetime.date.today()

    if date.weekday() >= 5:
        day_name = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][date.weekday()]
        return False, f"{day_name} -- market closed on weekends"

    holidays = us_market_holidays(date.year)
    if date in holidays:
        return False, f"US market holiday"

    return True, "trading day"


# ===========================================================================
# Per-ticker pipeline runner
# ===========================================================================

# Results accumulator -- filled by run_ticker(), read by write_summary()
_ticker_results: list[dict] = []


def run_ticker(ticker: str, logger_prefix: str = "") -> dict:
    """
    Run the full 4-step pipeline for one ticker.  Returns a result dict:
      ticker, ok, signal, iv_rank, sentiment_score,
      news_count, errors (list of error strings)

    Errors at any individual step are caught and recorded; subsequent steps
    still run where possible.
    """
    result = {
        "ticker":             ticker,
        "ok":                 True,
        "signal":             "N/A",
        "iv_rank_pct":        None,
        "sentiment_score":    None,
        "news_count":         0,
        "reddit_post_count":  0,
        "errors":             [],
    }

    tag = f"[{ticker}]"

    # ------------------------------------------------------------------
    # Step 1 -- Fetch news (Finnhub, ~30 day history)
    # ------------------------------------------------------------------
    try:
        from data.news_fetcher import fetch_news
        news_df = fetch_news(ticker, save=True)
        result["news_count"] = len(news_df)
        print(f"{tag} Step 1/5 news fetched: {len(news_df)} articles")
    except Exception as e:
        msg = f"news fetch failed: {e}"
        result["errors"].append(msg)
        result["ok"] = False
        print(f"{tag} WARN Step 1/5 {msg}")

    # ------------------------------------------------------------------
    # Step 2 -- Fetch Reddit (best-effort, up to 90 days)
    # Failure here is non-fatal -- we can still run on news-only.
    # ------------------------------------------------------------------
    try:
        from data.reddit_fetcher import fetch_reddit_posts
        reddit_df = fetch_reddit_posts(ticker, save=True)
        result["reddit_post_count"] = len(reddit_df)
        if not reddit_df.empty:
            span = (reddit_df["date"].max() - reddit_df["date"].min()).days
            print(f"{tag} Step 2/5 reddit fetched: {len(reddit_df)} posts "
                  f"({span}d span)")
        else:
            print(f"{tag} Step 2/5 reddit fetched: 0 posts")
    except Exception as e:
        # Don't mark the whole ticker as failed -- news-only is still useful
        msg = f"reddit fetch failed: {e}"
        result["errors"].append(msg)
        print(f"{tag} WARN Step 2/5 {msg}")

    # ------------------------------------------------------------------
    # Step 3 -- Fetch options chain + IV
    # ------------------------------------------------------------------
    try:
        from data.options_fetcher import fetch_options_chain
        opts_df = fetch_options_chain(ticker, save=True)
        iv_pct  = opts_df["iv_rank_pct"].iloc[0] if not opts_df.empty else None
        result["iv_rank_pct"] = iv_pct
        print(f"{tag} Step 3/5 options fetched: {len(opts_df)} contracts, "
              f"IV Rank={iv_pct:.1f}%" if iv_pct is not None else
              f"{tag} Step 3/5 options fetched (IV Rank unavailable)")
    except Exception as e:
        msg = f"options fetch failed: {e}"
        result["errors"].append(msg)
        result["ok"] = False
        print(f"{tag} WARN Step 3/5 {msg}")

    # ------------------------------------------------------------------
    # Step 4 -- Score sentiment (news AND reddit, then merge)
    # ------------------------------------------------------------------
    try:
        from sentiment.scorer import (
            score_from_csv,
            _find_latest_news_csv,
            _find_latest_reddit_csv,
        )
        from sentiment.aggregator import build_sentiment_summary

        scored_any = False

        news_csv = _find_latest_news_csv(ticker)
        if news_csv:
            score_from_csv(news_csv, save=True, source_tag="")
            scored_any = True
        else:
            result["errors"].append("no news CSV found for sentiment scoring")

        reddit_csv = _find_latest_reddit_csv(ticker)
        if reddit_csv:
            score_from_csv(reddit_csv, save=True, source_tag="reddit")
            scored_any = True

        if scored_any:
            # Aggregator merges news + reddit rows per date via weighted avg
            summary = build_sentiment_summary(ticker, save=True)
            if not summary.empty:
                latest = summary.iloc[-1]
                # raw_score is what aggregator.py renames sentiment_score to
                score_col = "raw_score" if "raw_score" in summary.columns else "sentiment_score"
                val = latest.get(score_col)
                if pd.notna(val):
                    result["sentiment_score"] = float(val)
            latest_str = (f"{result['sentiment_score']:+.4f}"
                          if result['sentiment_score'] is not None else "N/A")
            print(f"{tag} Step 4/5 sentiment scored: "
                  f"{len(summary)} days, latest={latest_str}")
        else:
            print(f"{tag} WARN Step 4/5 no text CSVs available -- skipped")
    except Exception as e:
        msg = f"sentiment scoring failed: {e}"
        result["errors"].append(msg)
        result["ok"] = False
        print(f"{tag} WARN Step 4/5 {msg}")

    # ------------------------------------------------------------------
    # Step 5 -- Generate signal
    # ------------------------------------------------------------------
    try:
        from signals.signal_engine import generate_signal
        sig_df = generate_signal(ticker, save=True)
        if not sig_df.empty:
            result["signal"] = sig_df["signal"].iloc[0]
            earnings_warning = bool(sig_df.get("earnings_warning", [False]).iloc[0])
            result["earnings_warning"] = earnings_warning
            if earnings_warning:
                result["earnings_date"] = str(sig_df["earnings_date"].iloc[0])
        print(f"{tag} Step 5/5 signal: {result['signal']}")
    except Exception as e:
        msg = f"signal generation failed: {e}"
        result["errors"].append(msg)
        result["ok"] = False
        print(f"{tag} WARN Step 5/5 {msg}")

    return result


# ===========================================================================
# Summary writer
# ===========================================================================

def write_summary(
    results: list[dict],
    run_date: datetime.date,
    elapsed_seconds: float,
    log_path: str,
) -> str:
    """
    Write logs/daily_summary.txt and return its path.
    This file is overwritten on every run so it always shows the current state.
    """
    summary_path = os.path.join(LOGS_DIR, "daily_summary.txt")

    ok_count     = sum(1 for r in results if r["ok"])
    err_count    = len(results) - ok_count
    total_news   = sum(r["news_count"]         for r in results)
    total_reddit = sum(r.get("reddit_post_count", 0) for r in results)

    mins, secs = divmod(int(elapsed_seconds), 60)
    duration   = f"{mins}m {secs:02d}s"

    lines = [
        "=" * 56,
        f"  DAILY PIPELINE SUMMARY  --  {run_date}",
        "=" * 56,
        f"  Run completed : {datetime.datetime.now().strftime('%H:%M:%S')}",
        f"  Duration      : {duration}",
        f"  Log file      : {os.path.basename(log_path)}",
        "",
        f"  TICKERS PROCESSED: {ok_count}/{len(results)}",
        "",
    ]

    for r in results:
        status = "OK  " if r["ok"] else "FAIL"
        iv_str   = f"IV={r['iv_rank_pct']:.0f}%"    if r["iv_rank_pct"]     is not None else "IV=?"
        sent_str = f"Sent={r['sentiment_score']:+.3f}" if r["sentiment_score"] is not None else "Sent=?"
        src_str  = f"n={r['news_count']}/r={r.get('reddit_post_count', 0)}"
        earn_str = ""
        if r.get("earnings_warning"):
            earn_str = f"  [EARNINGS {r.get('earnings_date','')}]"
        lines.append(f"  [{status}] {r['ticker']:<6s}  Signal={r['signal']:<12s}  "
                     f"{iv_str}  {sent_str}  {src_str}{earn_str}")
        for err in r["errors"]:
            lines.append(f"           ERROR: {err}")

    lines += [
        "",
        f"  Total news articles fetched : {total_news}",
        f"  Total reddit posts fetched  : {total_reddit}",
        f"  Errors                      : {err_count}",
        "",
    ]

    if err_count:
        lines += ["  ERRORS (see log for full traceback):"]
        for r in results:
            for err in r["errors"]:
                lines.append(f"    {r['ticker']}: {err}")
        lines.append("")

    lines.append("=" * 56)

    text = "\n".join(lines) + "\n"

    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(text)

    return summary_path


# ===========================================================================
# Main entry point
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Daily options sentiment pipeline runner"
    )
    parser.add_argument("--force",   action="store_true",
                        help="Run even on weekends/market holidays")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would run without executing")
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Override ticker list from config.py")
    args = parser.parse_args()

    run_date = datetime.date.today()
    tickers  = args.tickers or config.TICKERS

    # ------------------------------------------------------------------
    # Trading day guard
    # ------------------------------------------------------------------
    is_market, reason = is_trading_day(run_date)
    if not is_market and not args.force:
        print(f"[run_daily] Skipping {run_date}: {reason}. "
              f"Use --force to override.")
        return

    if args.dry_run:
        print(f"[run_daily] DRY RUN for {run_date}")
        print(f"  Would process: {tickers}")
        print(f"  Log -> logs/pipeline_{run_date}.log")
        return

    # ------------------------------------------------------------------
    # Set up log file + tee stdout/stderr into it
    # ------------------------------------------------------------------
    log_filename = f"pipeline_{run_date}.log"
    log_path     = os.path.join(LOGS_DIR, log_filename)

    log_file        = open(log_path, "w", encoding="utf-8")
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout      = _Tee(log_file, original_stdout)
    sys.stderr      = _Tee(log_file, original_stderr)

    start_time = time.monotonic()

    try:
        print("=" * 56)
        print(f"  OPTIONS SENTIMENT PIPELINE  --  {run_date}")
        print(f"  Started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Tickers: {', '.join(tickers)}")
        print("=" * 56)
        print()

        results = []
        for ticker in tickers:
            print(f"\n{'-' * 40}")
            print(f"  Processing {ticker} ...")
            print(f"{'-' * 40}")
            try:
                result = run_ticker(ticker)
            except Exception:
                # Catch any unexpected error that escaped run_ticker's own handlers
                tb = traceback.format_exc()
                print(f"[{ticker}] UNEXPECTED ERROR:\n{tb}")
                result = {
                    "ticker":            ticker,
                    "ok":                False,
                    "signal":            "ERROR",
                    "iv_rank_pct":       None,
                    "sentiment_score":   None,
                    "news_count":        0,
                    "reddit_post_count": 0,
                    "errors":            [f"Unexpected: {tb.splitlines()[-1]}"],
                }
            results.append(result)

        elapsed = time.monotonic() - start_time
        summary_path = write_summary(results, run_date, elapsed, log_path)

        print()
        print("=" * 56)
        ok = sum(1 for r in results if r["ok"])
        print(f"  DONE: {ok}/{len(results)} tickers succeeded  |  "
              f"{elapsed/60:.1f} min")
        print(f"  Summary -> {summary_path}")
        print(f"  Log     -> {log_path}")
        print("=" * 56)

    finally:
        # Always restore stdout/stderr and close the log file
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()


if __name__ == "__main__":
    main()

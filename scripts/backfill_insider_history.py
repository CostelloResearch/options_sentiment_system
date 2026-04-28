# =============================================================================
# scripts/backfill_insider_history.py -- One-shot backfill of insider
# transaction history for the six individual-stock tickers in the universe.
#
# WHY ONE-SHOT
# ------------
# Finnhub's insider-transactions endpoint returns the entire transaction
# stream for a ticker in one call when you give it a wide date range (no
# pagination is required for 5y of data on the universe's mega-caps; the
# largest single-ticker pull seen in development is ~1,700 rows).  That
# means a single sequential pass over the 6 tickers, with a small sleep
# between calls, is sufficient and well under the 60 calls/min free-tier
# rate ceiling.
#
# IDEMPOTENCY
# -----------
# Each per-ticker CSV is *replaced* on every run (full overwrite).  This
# is simpler than diffing against an existing on-disk frame and the API
# is the source of truth -- if the SEC posts a corrected Form 4, the
# next backfill picks it up automatically.  Re-running the script is
# therefore safe at any time.  No append, no dedup, no merge logic.
#
# OUTPUT
# ------
# - data/raw/insider_{TICKER}.csv per ticker (schema: see
#   data/insider_fetcher.py docstring)
# - Console summary: per-ticker counts and final totals
#
# USAGE
# -----
#   .venv/Scripts/python.exe scripts/backfill_insider_history.py
#   .venv/Scripts/python.exe scripts/backfill_insider_history.py --tickers AAPL JPM
#   .venv/Scripts/python.exe scripts/backfill_insider_history.py --years 3
#   .venv/Scripts/python.exe scripts/backfill_insider_history.py --dry-run
# =============================================================================

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time

import pandas as pd

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402
from data.insider_fetcher import fetch_insider_transactions  # noqa: E402

# Tickers eligible for insider data: the six individual-stock names.
# ETFs (IWM, GLD, TLT, SPY) are skipped because ETFs do not have insiders;
# the Finnhub endpoint returns an empty list for them.
_DEFAULT_TICKERS = [t for t in config.TICKERS if t not in config.ETF_TICKERS]


def _format_summary(per_ticker: list[dict], elapsed_s: float, lookback_years: int) -> str:
    """Build the multi-line summary string written to stdout at end of run."""
    lines = [
        "=" * 64,
        f"  INSIDER BACKFILL SUMMARY -- "
        f"{datetime.date.today().strftime('%Y-%m-%d')}",
        "=" * 64,
        f"  Lookback : {lookback_years} years",
        f"  Tickers  : {len(per_ticker)}",
        f"  Duration : {elapsed_s:.1f}s",
        "",
    ]
    total_rows = sum(p["n_rows"] for p in per_ticker)
    total_opp  = sum(p["n_opportunistic"] for p in per_ticker)
    total_buys = sum(p["n_buys"] for p in per_ticker)
    total_sells = sum(p["n_sells"] for p in per_ticker)

    header = (f"  {'TICKER':<6} {'ROWS':>6} {'BUYS':>6} {'SELLS':>6} "
              f"{'OPP':>5} {'OPP%':>6}  {'DATE RANGE':<24} STATUS")
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for p in per_ticker:
        opp_pct = (100.0 * p["n_opportunistic"] / p["n_rows"]) if p["n_rows"] else 0.0
        date_range = (f"{p['date_min']} -> {p['date_max']}"
                      if p["n_rows"] else "(no data)")
        status = "OK" if p["ok"] else "FAIL"
        lines.append(
            f"  {p['ticker']:<6} {p['n_rows']:>6,} {p['n_buys']:>6,} "
            f"{p['n_sells']:>6,} {p['n_opportunistic']:>5,} {opp_pct:>5.1f}%  "
            f"{date_range:<24} {status}"
        )
    lines += [
        "  " + "-" * (len(header) - 2),
        f"  {'TOTAL':<6} {total_rows:>6,} {total_buys:>6,} {total_sells:>6,} "
        f"{total_opp:>5,}",
        "",
    ]

    # Failures, if any
    failed = [p for p in per_ticker if not p["ok"]]
    if failed:
        lines.append(f"  FAILURES ({len(failed)}):")
        for p in failed:
            lines.append(f"    {p['ticker']}: {p.get('error','unknown')}")
        lines.append("")

    lines.append("=" * 64)
    return "\n".join(lines)


def _summarise(ticker: str, df: pd.DataFrame, ok: bool, error: str | None = None) -> dict:
    if not ok or df.empty:
        return {
            "ticker":          ticker,
            "ok":              ok,
            "n_rows":          0,
            "n_buys":          0,
            "n_sells":         0,
            "n_opportunistic": 0,
            "date_min":        "",
            "date_max":        "",
            "error":           error or "",
        }
    return {
        "ticker":          ticker,
        "ok":              True,
        "n_rows":          int(len(df)),
        "n_buys":          int((df["transaction_type"] == "BUY").sum()),
        "n_sells":         int((df["transaction_type"] == "SELL").sum()),
        "n_opportunistic": int(df["is_opportunistic"].sum()),
        "date_min":        str(df["transaction_date"].min()),
        "date_max":        str(df["transaction_date"].max()),
        "error":           "",
    }


def main():
    ap = argparse.ArgumentParser(
        description=("Backfill Finnhub insider-transaction history for the "
                     "individual-stock tickers in the universe.  ETFs are "
                     "skipped automatically.")
    )
    ap.add_argument("--tickers", nargs="+", default=None,
                    help=("Override ticker list.  Default: TICKERS minus "
                          "ETFs from config.py."))
    ap.add_argument("--years", type=int, default=5,
                    help="Lookback in years (default 5).")
    ap.add_argument("--sleep", type=float, default=1.5,
                    help=("Seconds to sleep between API calls (default 1.5; "
                          "Finnhub free tier is 60/min)."))
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan and exit without calling the API.")
    args = ap.parse_args()

    tickers = args.tickers or _DEFAULT_TICKERS
    # If user passed an explicit list that includes ETFs, warn but honour it
    # (the API will just return empty for ETFs).
    etfs_in_list = [t for t in tickers if t in config.ETF_TICKERS]
    if etfs_in_list:
        print(f"[backfill] WARN explicit list includes ETFs (no insiders): "
              f"{etfs_in_list}.  They will return empty frames.")

    today = datetime.date.today()
    start = today - datetime.timedelta(days=int(365.25 * args.years))

    print("=" * 64)
    print(f"  INSIDER BACKFILL  --  {today.strftime('%Y-%m-%d')}")
    print(f"  Tickers : {', '.join(tickers)}")
    print(f"  Window  : {start} -> {today}  ({args.years} years)")
    print(f"  Sleep   : {args.sleep}s between calls")
    print("=" * 64)
    print()

    if args.dry_run:
        print("[backfill] DRY RUN -- no API calls made, no files written.")
        return

    per_ticker: list[dict] = []
    t_start = time.monotonic()

    for i, t in enumerate(tickers):
        print(f"\n----- {t} ({i+1}/{len(tickers)}) -----")
        try:
            df = fetch_insider_transactions(t, start, today, save=True)
            per_ticker.append(_summarise(t, df, ok=True))
        except Exception as e:
            # The fetcher swallows expected HTTP failures and returns an
            # empty frame; this catches genuinely unexpected errors
            # (e.g. ImportError, missing API key).
            print(f"[backfill] ERROR {t}: {e}")
            per_ticker.append(_summarise(t, pd.DataFrame(), ok=False,
                                         error=str(e)))

        if i < len(tickers) - 1:
            time.sleep(args.sleep)

    elapsed = time.monotonic() - t_start
    print()
    print(_format_summary(per_ticker, elapsed, args.years))


if __name__ == "__main__":
    main()

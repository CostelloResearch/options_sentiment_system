# =============================================================================
# scripts/check_pipeline.py -- Pipeline health check
#
# Run anytime to get a quick snapshot of the system's current state.
# No arguments required; reads from data/raw/ and logs/.
#
# SHOWS
# -----
#   • Last automated run time + outcome
#   • Which tickers have data on disk
#   • How many days of sentiment history each ticker has
#   • Latest signal for every ticker
#   • Data freshness warnings (files older than 2 trading days)
# =============================================================================

import os
import sys
import glob
import datetime

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import config
import pandas as pd

RAW_DIR  = os.path.join(PROJECT_ROOT, "data", "raw")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
_W       = 60   # print width


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _latest_file(pattern: str) -> str | None:
    matches = sorted(glob.glob(os.path.join(RAW_DIR, pattern)))
    return matches[-1] if matches else None


def _file_age_days(path: str) -> float:
    """How many calendar days ago was `path` last modified?"""
    mtime = os.path.getmtime(path)
    mod   = datetime.datetime.fromtimestamp(mtime)
    return (datetime.datetime.now() - mod).total_seconds() / 86400


def _is_stale(path: str, max_days: float = 2.0) -> bool:
    return _file_age_days(path) > max_days


def _fmt_age(path: str) -> str:
    days = _file_age_days(path)
    if days < 1/24:
        return f"{int(days*1440)}m ago"
    if days < 1:
        return f"{days*24:.1f}h ago"
    return f"{days:.1f}d ago"


# ---------------------------------------------------------------------------
# Section 1 -- Last run info
# ---------------------------------------------------------------------------

def section_last_run():
    print(f"\n{'-'*_W}")
    print("  LAST AUTOMATED RUN")
    print(f"{'-'*_W}")

    summary_path = os.path.join(LOGS_DIR, "daily_summary.txt")
    log_files    = sorted(glob.glob(os.path.join(LOGS_DIR, "pipeline_*.log")))

    if not log_files:
        print("  No pipeline logs found in logs/")
        print("  -> Run scripts/run_daily.py to generate one.")
        return

    last_log = log_files[-1]
    log_date = os.path.basename(last_log).replace("pipeline_", "").replace(".log", "")
    age      = _fmt_age(last_log)
    stale    = " [STALE - consider re-running]" if _is_stale(last_log, 3) else ""

    print(f"  Most recent log  : {os.path.basename(last_log)}")
    print(f"  Log modified     : {age}{stale}")
    print(f"  Total log files  : {len(log_files)}")
    print(f"  Oldest           : {os.path.basename(log_files[0])}")

    if os.path.exists(summary_path):
        print(f"\n  -- Last summary (logs/daily_summary.txt) --")
        with open(summary_path, encoding="utf-8") as f:
            for line in f:
                print(f"  {line}", end="")
    else:
        print("\n  No daily_summary.txt found yet.")


# ---------------------------------------------------------------------------
# Section 2 -- Data inventory per ticker
# ---------------------------------------------------------------------------

def section_data_inventory():
    print(f"\n{'-'*_W}")
    print("  DATA INVENTORY")
    print(f"{'-'*_W}")
    print(f"  {'Ticker':<6}  {'News':>5}  {'Options':>7}  "
          f"{'Sent.days':>9}  {'Signals':>7}  {'Freshness'}")
    print(f"  {'------':<6}  {'-----':>5}  {'-------':>7}  "
          f"{'---------':>9}  {'-------':>7}  {'---------'}")

    today = datetime.date.today()
    warnings = []

    for ticker in config.TICKERS:
        # News files
        news_files = sorted(glob.glob(os.path.join(RAW_DIR, f"news_{ticker}_*.csv")))
        n_news     = len(news_files)

        # Options files
        opts_files = sorted(glob.glob(os.path.join(RAW_DIR, f"options_{ticker}_*.csv")))
        n_opts     = len(opts_files)

        # Sentiment days: rows across all per-day sentiment CSVs, excluding
        # our own aggregator output to avoid double-counting.
        sent_files = sorted(glob.glob(os.path.join(RAW_DIR, f"sentiment_{ticker}_*.csv")))
        sent_files = [f for f in sent_files
                      if not os.path.basename(f).startswith("sentiment_summary_")]
        sent_days  = 0
        for sf in sent_files:
            try:
                sent_days += len(pd.read_csv(sf))
            except Exception:
                pass

        # Signal rows
        sig_file  = os.path.join(RAW_DIR, f"signals_{ticker}.csv")
        n_signals = 0
        if os.path.exists(sig_file):
            try:
                n_signals = len(pd.read_csv(sig_file))
            except Exception:
                pass

        # Freshness: age of the most recent options file (options are fetched daily)
        freshness = ""
        if opts_files:
            age     = _file_age_days(opts_files[-1])
            stale   = age > 2
            freshness = f"{age:.1f}d ago {'[!]' if stale else ''}"
            if stale:
                warnings.append(f"{ticker}: options data is {age:.1f} days old")

        print(f"  {ticker:<6}  {n_news:>5}  {n_opts:>7}  "
              f"{sent_days:>9}  {n_signals:>7}  {freshness}")

    if warnings:
        print()
        for w in warnings:
            print(f"  WARNING: {w}")


# ---------------------------------------------------------------------------
# Section 3 -- Latest signals
# ---------------------------------------------------------------------------

def section_latest_signals():
    print(f"\n{'-'*_W}")
    print("  LATEST SIGNALS")
    print(f"{'-'*_W}")

    any_signal = False
    for ticker in config.TICKERS:
        sig_file = os.path.join(RAW_DIR, f"signals_{ticker}.csv")
        if not os.path.exists(sig_file):
            print(f"  {ticker:<6}  no signal file yet")
            continue

        try:
            # on_bad_lines='skip' handles CSVs that grew new columns mid-history
            # (e.g. earnings fields added after the first few runs)
            df = pd.read_csv(sig_file, on_bad_lines="skip")
            if df.empty:
                print(f"  {ticker:<6}  signal file is empty")
                continue

            last  = df.iloc[-1]
            sig   = str(last.get("signal", "?"))
            sdate = str(last.get("signal_date", "?"))
            ivpct = last.get("iv_rank_pct", None)
            sent  = last.get("sentiment_score", None)
            conf  = last.get("confidence", None)
            earn  = bool(last.get("earnings_warning", False))
            earn_str = f"  [EARNINGS {last.get('earnings_date','')}]" if earn else ""

            iv_str   = f"IV={float(ivpct):.0f}%"  if ivpct is not None else "IV=?"
            sent_str = f"Sent={float(sent):+.3f}"  if sent  is not None else "Sent=?"
            conf_str = f"Conf={float(conf):.2f}"   if conf  is not None else ""

            # Confidence bar (10 chars)
            conf_val = float(conf) if conf is not None else 0
            filled   = round(conf_val * 10)
            bar      = "#" * filled + "-" * (10 - filled)

            print(f"  {ticker:<6}  {sig:<12s}  [{bar}]  "
                  f"{iv_str}  {sent_str}  {conf_str}  ({sdate}){earn_str}")
            any_signal = True

        except Exception as e:
            print(f"  {ticker:<6}  ERROR reading signal file: {e}")

    if not any_signal:
        print()
        print("  No signals found. Run: python signals/signal_engine.py")


# ---------------------------------------------------------------------------
# Section 4 -- Upcoming earnings
# ---------------------------------------------------------------------------

def section_upcoming_earnings():
    print(f"\n{'-'*_W}")
    print("  UPCOMING EARNINGS (next 30 days)")
    print(f"{'-'*_W}")

    try:
        from signals.earnings_filter import fetch_earnings_dates
        today   = datetime.date.today()
        horizon = today + datetime.timedelta(days=30)
        found   = False
        for ticker in config.TICKERS:
            dates = fetch_earnings_dates(ticker)
            upcoming = [d for d in dates if today <= d <= horizon]
            if upcoming:
                for d in upcoming:
                    dte = (d - today).days
                    label = "TODAY" if dte == 0 else f"in {dte}d"
                    print(f"  {ticker:<6}  {d}  ({label})")
                found = True
        if not found:
            print("  No earnings found in the next 30 days for tracked tickers.")
    except Exception as e:
        print(f"  Could not fetch earnings calendar: {e}")


# ---------------------------------------------------------------------------
# Section 5 -- Environment quick check
# ---------------------------------------------------------------------------

def section_environment():
    print(f"\n{'-'*_W}")
    print("  ENVIRONMENT")
    print(f"{'-'*_W}")

    print(f"  Python          : {sys.version.split()[0]}")
    print(f"  Project root    : {PROJECT_ROOT}")
    print(f"  Tickers tracked : {', '.join(config.TICKERS)}")

    # Check that key packages are importable
    checks = [
        ("yfinance",      "yfinance"),
        ("finnhub",       "finnhub"),
        ("transformers",  "transformers"),
        ("plotly",        "plotly"),
        ("pandas",        "pandas"),
    ]
    pkg_lines = []
    for label, mod in checks:
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "?")
            pkg_lines.append(f"    {label:<14s}: {ver}")
        except ImportError:
            pkg_lines.append(f"    {label:<14s}: NOT INSTALLED")

    print("  Packages:")
    for line in pkg_lines:
        print(line)

    # API key check (don't print the actual key)
    key = config.FINNHUB_API_KEY
    if key == "YOUR_FINNHUB_API_KEY_HERE":
        print("  Finnhub API key : NOT SET (edit config.py)")
    else:
        print(f"  Finnhub API key : set ({key[:4]}...{key[-4:]})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * _W)
    print(f"  PIPELINE HEALTH CHECK  --  {datetime.date.today()}")
    print("=" * _W)

    section_last_run()
    section_data_inventory()
    section_latest_signals()
    section_upcoming_earnings()
    section_environment()

    print(f"\n{'-'*_W}")
    print("  QUICK COMMANDS")
    print(f"{'-'*_W}")
    print("  Run pipeline now      :  python scripts/run_daily.py --force")
    print("  Fetch data only       :  python main.py --fetch")
    print("  Score sentiment       :  python main.py --sentiment")
    print("  Generate signals      :  python main.py --signals")
    print("  Run backtest (demo)   :  python main.py --backtest --demo")
    print("  Open dashboard        :  python main.py --dashboard --demo")
    print("  Setup scheduler       :  powershell scripts/setup_scheduler.ps1")
    print("=" * _W)
    print()


if __name__ == "__main__":
    main()

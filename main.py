# =============================================================================
# main.py — Orchestrates the full pipeline
#
# Run stages individually with flags, or run everything end-to-end.
# Usage:
#   python main.py --fetch          # data collection only
#   python main.py --sentiment      # score fetched news
#   python main.py --signals        # generate signals
#   python main.py --backtest       # run backtest
#   python main.py --dashboard      # launch Plotly dashboard
#   python main.py                  # run everything
# =============================================================================

import argparse
import config


def run_data_fetch(tickers):
    from data.news_fetcher import fetch_all_tickers as fetch_news
    from data.options_fetcher import fetch_all_tickers as fetch_options

    print("=== Stage 1: Data Fetch ===")
    fetch_news(tickers)
    fetch_options(tickers)


def run_sentiment(tickers):
    from sentiment.scorer import score_from_csv, _find_latest_news_csv
    from sentiment.aggregator import build_sentiment_summary

    print("\n=== Stage 2: Sentiment Scoring ===")
    for ticker in tickers:
        csv_path = _find_latest_news_csv(ticker)
        if not csv_path:
            print(f"[main] No news CSV found for {ticker} — skipping.")
            continue
        score_from_csv(csv_path, save=True)
        build_sentiment_summary(ticker, save=True)


def run_signals(tickers):
    from signals.signal_engine import generate_signal, print_signal_summary

    print("\n=== Stage 3: Signal Generation ===")
    for ticker in tickers:
        try:
            df = generate_signal(ticker, save=True)
            print_signal_summary(df)
        except FileNotFoundError as e:
            print(f"[main] SKIP {ticker}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Options Sentiment Signal System")
    parser.add_argument("--fetch",     action="store_true", help="Run data fetchers")
    parser.add_argument("--sentiment", action="store_true", help="Run sentiment scorer")
    parser.add_argument("--signals",   action="store_true", help="Generate signals")
    parser.add_argument("--backtest",  action="store_true", help="Run backtest engine")
    parser.add_argument("--dashboard", action="store_true",
                        help="Build per-ticker report.html for each ticker AND "
                             "the cross-universe overview.html")
    parser.add_argument("--dashboard-overview-only", action="store_true",
                        help="Build only the cross-universe overview.html "
                             "(skip the per-ticker report.html files)")
    parser.add_argument("--demo",      action="store_true",
                        help="Use synthetic sentiment data (for backtest/dashboard demo)")
    parser.add_argument(
        "--tickers", nargs="+", default=config.TICKERS,
        help="Override tickers (e.g. --tickers AAPL TSLA)"
    )
    args = parser.parse_args()

    # `--dashboard-overview-only` is a dashboard-mode flag, so treat it
    # the same as --dashboard for the run_all-disable check.
    dashboard_any = args.dashboard or args.dashboard_overview_only

    # If no stage flags provided, run everything
    run_all = not any([args.fetch, args.sentiment, args.signals,
                       args.backtest, dashboard_any])

    if args.fetch or run_all:
        run_data_fetch(args.tickers)

    # Subsequent stages (sentiment, signals, backtest, dashboard) will be
    # wired up in later project stages.
    if args.sentiment or run_all:
        run_sentiment(args.tickers)

    if args.signals or run_all:
        run_signals(args.tickers)

    if args.backtest or run_all:
        from backtest.engine import run_backtest
        from backtest.metrics import print_summary
        print("\n=== Stage 4: Backtest ===")
        for ticker in args.tickers:
            trades = run_backtest(ticker, demo_mode=args.demo, save=True)
            print_summary(ticker, trades)

    if dashboard_any or run_all:
        import os as _os
        from dashboard.app import build_dashboard, build_overview_dashboard
        print("\n=== Stage 5: Dashboard ===")
        # Per-ticker reports: one report_{TICKER}.html per ticker so
        # the iteration doesn't clobber a single shared file.  Skipped
        # entirely under --dashboard-overview-only.
        if not args.dashboard_overview_only:
            dash_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                     "dashboard")
            for ticker in args.tickers:
                out = _os.path.join(dash_dir, f"report_{ticker.upper()}.html")
                build_dashboard(ticker, demo_mode=args.demo,
                                open_browser=False, output_path=out)
        # Cross-universe overview always runs in any dashboard mode.
        build_overview_dashboard(args.tickers, demo_mode=args.demo,
                                 open_browser=True)


if __name__ == "__main__":
    main()

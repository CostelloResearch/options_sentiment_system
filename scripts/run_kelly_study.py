# =============================================================================
# scripts/run_kelly_study.py -- End-to-end Kelly-sizing + signal-decay study
#
# Produces (in order):
#   1. Flat-sizing backtest across configured tickers  -> backtest_{T}_demo.csv
#   2. Kelly stats from that corpus                    -> kelly_stats.csv
#   3. Kelly-sizing backtest across the same tickers   -> backtest_{T}_demo_kelly.csv
#   4. Signal-decay analysis on the flat corpus        -> outputs/signal_decay_analysis.md
#   5. Side-by-side metrics (flat vs Kelly)            -> stdout + outputs/kelly_study_summary.md
#
# Uses demo-mode synthetic sentiment with a 500-day window so we have enough
# accepted trades for Kelly stats to be meaningful (n >= 10 per signal type).
# Real-mode would swap demo_mode=False once a year of real news history is
# on disk.
# =============================================================================

import os
import sys
import argparse

import numpy as np
import pandas as pd


def _df_to_md(df: pd.DataFrame) -> str:
    """
    Hand-rolled markdown table writer so we don't need the `tabulate`
    package just to print a 10-row comparison.  Numeric cells are
    formatted to 4 decimals; everything else is stringified.
    """
    if df.empty:
        return "_(empty)_\n"
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep    = "|" + "|".join("---" for _ in cols) + "|"
    lines  = [header, sep]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (int, np.integer)):
                cells.append(f"{int(v)}")
            elif isinstance(v, (float, np.floating)):
                cells.append("-" if pd.isna(v) else f"{float(v):.4f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from backtest.engine   import run_backtest
from backtest.metrics  import (
    total_return, win_rate, sharpe_ratio, max_drawdown, profit_factor,
)
from signals           import position_sizer, signal_decay


OUT_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "outputs"
))
RAW_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "data", "raw"
))


def _load_backtest(ticker: str, demo: bool, suffix: str = "") -> pd.DataFrame:
    """Load a backtest CSV by ticker + variant suffix."""
    pfx = "_demo" if demo else ""
    path = os.path.join(RAW_DIR, f"backtest_{ticker}{pfx}{suffix}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=["entry_date", "exit_date"])


def _metrics_row(label: str, ticker: str, df: pd.DataFrame) -> dict:
    """Compute headline metrics for one run + ticker."""
    if df.empty:
        return {"label": label, "ticker": ticker, "n": 0}
    # Dollar P&L: use pnl_total if present (dollar terms, already sized),
    # else fall back to per-share pnl * 100 (one contract).
    if "pnl_total" in df.columns and df["pnl_total"].notna().any():
        dollar_pnl = df["pnl_total"].fillna(0.0)
    else:
        dollar_pnl = df["pnl"].fillna(0.0) * 100.0

    cumulative = dollar_pnl.cumsum()
    running_max = cumulative.cummax()
    dd = (cumulative - running_max).min()

    # Per-trade dollar return for Sharpe
    accepted = df[df.get("accepted", False).astype(bool)] if "accepted" in df.columns else df
    n = len(accepted)
    return {
        "label":         label,
        "ticker":        ticker,
        "n_signals":     int(len(df)),
        "n_trades":      int(n),
        "total_pnl":     round(float(dollar_pnl.sum()), 2),
        "avg_trade_pnl": round(float(dollar_pnl.mean()), 2),
        "win_rate":      round(float((dollar_pnl > 0).mean()), 4),
        "sharpe":        round(float(
                             (dollar_pnl.mean() / dollar_pnl.std(ddof=1))
                             * np.sqrt(252.0 / 5.0)
                         ), 4) if dollar_pnl.std(ddof=1) > 0 else 0.0,
        "max_dd":        round(float(dd), 2),
        "profit_factor": round(float(
                             dollar_pnl[dollar_pnl > 0].sum()
                             / abs(dollar_pnl[dollar_pnl < 0].sum())
                         ), 4) if abs(dollar_pnl[dollar_pnl < 0].sum()) > 0 else float("inf"),
    }


def _merge_logs(tickers, demo: bool, suffix: str = "") -> pd.DataFrame:
    """Concatenate per-ticker backtest logs into one DataFrame."""
    frames = []
    for t in tickers:
        df = _load_backtest(t, demo=demo, suffix=suffix)
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def run(
    tickers:        list,
    demo:           bool  = True,
    lookback_days:  int   = 500,
    skip_flat:      bool  = False,
    skip_kelly:     bool  = False,
    skip_decay:     bool  = False,
) -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- 1. Flat-sizing backtest (skip if user says) ----
    if not skip_flat:
        print("=" * 72)
        print("STEP 1: Flat-sizing backtest")
        print("=" * 72)
        for t in tickers:
            run_backtest(
                t, demo_mode=demo, lookback_days=lookback_days,
                use_kelly_sizing=False, output_suffix="",
            )

    # ---- 2. Build Kelly stats from the flat corpus ----
    print("\n" + "=" * 72)
    print("STEP 2: Compute Kelly stats from flat-sizing corpus")
    print("=" * 72)
    flat_all = _merge_logs(tickers, demo=demo, suffix="")
    if flat_all.empty:
        print("[study] No flat-sizing logs available; aborting.")
        return {}
    stats = position_sizer.compute_kelly_stats(flat_all)
    position_sizer.save_stats(stats)
    position_sizer.print_stats(stats)

    # ---- 3. Kelly-sizing backtest (skip if user says) ----
    if not skip_kelly:
        print("\n" + "=" * 72)
        print("STEP 3: Kelly-sizing backtest")
        print("=" * 72)
        for t in tickers:
            run_backtest(
                t, demo_mode=demo, lookback_days=lookback_days,
                use_kelly_sizing=True, output_suffix="_kelly",
            )

    # ---- 4. Signal-decay analysis on flat corpus ----
    decay_result = None
    if not skip_decay:
        print("\n" + "=" * 72)
        print("STEP 4: Signal-decay analysis on flat corpus")
        print("=" * 72)
        decay_result = signal_decay.run_decay_analysis(flat_all, tickers=tickers)
        print(f"[study] decay report -> {decay_result['report_path']}")
        if decay_result["disabled"]:
            print("[study] segments flagged DISABLE:")
            for d in decay_result["disabled"]:
                print(f"   - {d['segment']}  ({d['reason']})")

    # ---- 5. Flat vs Kelly comparison ----
    print("\n" + "=" * 72)
    print("STEP 5: Flat vs Kelly comparison")
    print("=" * 72)
    kelly_all = _merge_logs(tickers, demo=demo, suffix="_kelly")

    rows = []
    for t in tickers:
        rows.append(_metrics_row("flat",  t, _load_backtest(t, demo, "")))
        rows.append(_metrics_row("kelly", t, _load_backtest(t, demo, "_kelly")))
    # Portfolio-wide (all tickers) aggregated row
    rows.append(_metrics_row("flat",  "ALL", flat_all))
    rows.append(_metrics_row("kelly", "ALL", kelly_all))
    summary_df = pd.DataFrame(rows)

    print(summary_df.to_string(index=False))

    # Write markdown summary
    md_path = os.path.join(OUT_DIR, "kelly_study_summary.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Kelly Sizing vs Flat Sizing -- Comparison\n\n")
        f.write("_Demo-mode backtest with synthetic sentiment. "
                "Run with `--real` once real sentiment history exists._\n\n")

        f.write("## Per-ticker headline metrics\n\n")
        f.write(_df_to_md(summary_df))
        f.write("\n\n")

        f.write("## Kelly stats (per signal type)\n\n")
        if stats:
            stats_df = pd.DataFrame([
                {"signal": k, **v} for k, v in stats.items()
            ])
            f.write(_df_to_md(stats_df))
            f.write("\n\n")

        if decay_result and decay_result["disabled"]:
            f.write("## Signals flagged DISABLE by decay analysis\n\n")
            for d in decay_result["disabled"]:
                f.write(f"- **{d['segment']}** -- {d['reason']}\n")
            f.write("\n")
        elif decay_result:
            f.write("## Signal decay\n\nNo segments flagged DISABLE.\n\n")

    print(f"\n[study] comparison md -> {md_path}")

    return {
        "stats":        stats,
        "flat":         flat_all,
        "kelly":        kelly_all,
        "summary":      summary_df,
        "decay":        decay_result,
        "summary_path": md_path,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=config.TICKERS)
    ap.add_argument("--lookback-days", type=int, default=500)
    ap.add_argument("--real", action="store_true",
                    help="Use real sentiment history instead of synthetic demo")
    ap.add_argument("--skip-flat",  action="store_true")
    ap.add_argument("--skip-kelly", action="store_true")
    ap.add_argument("--skip-decay", action="store_true")
    args = ap.parse_args()

    run(
        tickers       = args.tickers,
        demo          = not args.real,
        lookback_days = args.lookback_days,
        skip_flat     = args.skip_flat,
        skip_kelly    = args.skip_kelly,
        skip_decay    = args.skip_decay,
    )

# =============================================================================
# scripts/fit_confidence_model.py -- Fit + validate the logistic confidence
#
# Pipeline:
#   1. Re-run the FLAT-sizing backtest on every configured ticker so the
#      trade log has the enriched feature columns (headline_count,
#      sent_momentum_3d, sec_aligned, days_to_earnings).
#   2. Concatenate all per-ticker logs and fit the logistic model.
#   3. Print coefficient summary + in-sample Q1..Q5 quintile performance.
#   4. Compare against the LEGACY tiered confidence on the same trades --
#      this answers "does the new model actually rank better than v1?"
#   5. If Q5 does NOT outperform Q1 on mean return, emit a clear WARNING --
#      the features don't carry signal, we should not swap in the model.
#
# Writes nothing permanent except data/raw/confidence_model.json (the
# fitted parameters) and outputs/confidence_model_report.md.
# =============================================================================

import os
import sys
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from backtest.engine         import run_backtest, load_price_history
from signals                 import confidence_model
from signals.signal_engine   import _compute_confidence_legacy


OUT_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "outputs"
))
RAW_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "data", "raw"
))


def _load_flat_logs(tickers, demo: bool) -> pd.DataFrame:
    pfx = "_demo" if demo else ""
    frames = []
    for t in tickers:
        p = os.path.join(RAW_DIR, f"backtest_{t}{pfx}.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _df_to_md(df: pd.DataFrame) -> str:
    """Same hand-rolled markdown table writer as run_kelly_study.py."""
    if df.empty:
        return "_(empty)_\n"
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep    = "|" + "|".join("---" for _ in cols) + "|"
    lines = [header, sep]
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


def _legacy_confidence_quintiles(trades: pd.DataFrame) -> pd.DataFrame:
    """
    Re-score every accepted trade with the legacy (strength-only) confidence
    formula and bucket into quintiles the same way as the logistic model.
    Used as the baseline in the model-vs-legacy comparison table.
    """
    df = trades.copy()
    if "accepted" in df.columns:
        df = df[df["accepted"].astype(bool)]
    if df.empty:
        return pd.DataFrame()

    conf = []
    for _, r in df.iterrows():
        try:
            conf.append(_compute_confidence_legacy(
                float(r["sentiment_score"]),
                float(r["iv_rank"]),
                str(r["signal"]),
            ))
        except Exception:
            conf.append(0.0)
    df["legacy_conf"] = conf

    try:
        df["quintile"] = pd.qcut(
            df["legacy_conf"], 5,
            labels=["Q1 (lowest)", "Q2", "Q3", "Q4", "Q5 (highest)"],
            duplicates="drop",
        )
    except Exception:
        df["quintile"] = "UNSPLIT"

    summary = df.groupby("quintile", observed=True).agg(
        n        = ("legacy_conf", "size"),
        mean_p   = ("legacy_conf", "mean"),
        mean_ret = ("pnl_pct", "mean"),
        win_rate = ("pnl_pct", lambda s: float((s > 0).mean())),
    ).reset_index()
    return summary


def run(tickers, demo: bool, lookback_days: int, skip_backtest: bool) -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)

    if not skip_backtest:
        print("=" * 72)
        print("STEP 1: Flat-sizing backtest (refresh log with enriched features)")
        print("=" * 72)
        for t in tickers:
            run_backtest(
                t, demo_mode=demo, lookback_days=lookback_days,
                use_kelly_sizing=False, output_suffix="",
            )

    print("\n" + "=" * 72)
    print("STEP 2: Load enriched trade log")
    print("=" * 72)
    trades = _load_flat_logs(tickers, demo=demo)
    if trades.empty:
        print("[fit] No logs on disk; aborting.")
        return {}
    required = {"sentiment_score", "iv_rank", "sent_momentum_3d",
                "sec_aligned", "headline_count", "days_to_earnings", "pnl_pct"}
    missing = required - set(trades.columns)
    if missing:
        print(f"[fit] ERROR: log is missing required feature columns: {missing}")
        print(f"      Re-run with --skip-backtest=False to rebuild with the new engine.")
        return {}
    accepted = trades[trades["accepted"].astype(bool)]
    print(f"[fit] {len(trades)} signal rows, {len(accepted)} accepted trades "
          f"across {trades['ticker'].nunique()} tickers.")

    print("\n" + "=" * 72)
    print("STEP 3: Fit logistic confidence model")
    print("=" * 72)
    model = confidence_model.fit_from_trade_log(trades, save=True)
    print(confidence_model.summarise(model))

    print("\n" + "=" * 72)
    print("STEP 4: Validate Q1..Q5 quintile ordering (in-sample)")
    print("=" * 72)
    model_q = confidence_model.validate_quintiles(trades, model, horizon_col="pnl_pct")
    legacy_q = _legacy_confidence_quintiles(trades)

    print("\nLOGISTIC MODEL confidence (new):")
    print(model_q.to_string(index=False))
    print("\nLEGACY TIERED confidence (v1):")
    print(legacy_q.to_string(index=False))

    # Headline validation
    q1_new = float(model_q[model_q["quintile"] == "Q1 (lowest)"]["mean_ret"].iloc[0]) \
             if not model_q.empty else float("nan")
    q5_new = float(model_q[model_q["quintile"] == "Q5 (highest)"]["mean_ret"].iloc[0]) \
             if not model_q.empty else float("nan")
    q1_old = float(legacy_q[legacy_q["quintile"] == "Q1 (lowest)"]["mean_ret"].iloc[0]) \
             if not legacy_q.empty else float("nan")
    q5_old = float(legacy_q[legacy_q["quintile"] == "Q5 (highest)"]["mean_ret"].iloc[0]) \
             if not legacy_q.empty else float("nan")

    print("\n" + "-" * 72)
    print(f"  Q5 - Q1 spread, LEGACY : {q5_old - q1_old:+.4f} "
          f"(Q1={q1_old:+.4f}, Q5={q5_old:+.4f})")
    print(f"  Q5 - Q1 spread, MODEL  : {q5_new - q1_new:+.4f} "
          f"(Q1={q1_new:+.4f}, Q5={q5_new:+.4f})")
    if q5_new > q1_new:
        verdict = "PASS: Q5 outperforms Q1 under the logistic confidence."
    else:
        verdict = ("FAIL: Q5 does NOT outperform Q1 under the logistic confidence. "
                   "The features (sentiment, IV, momentum, SEC, headline, earnings) "
                   "do not carry reliable signal at this sample size. "
                   "Recommend keeping the legacy formula and gathering more data "
                   "before swapping the model in.")
    print(verdict)

    # --- Write report ---
    md_path = os.path.join(OUT_DIR, "confidence_model_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Confidence Model Rebuild -- Logistic Regression\n\n")
        f.write("_Target: probability a trade closes with pnl_pct > 0.  "
                "Features documented in signals/confidence_model.py._\n\n")

        f.write("## Fit summary\n\n```\n")
        f.write(confidence_model.summarise(model))
        f.write("\n```\n\n")

        f.write("## In-sample quintile performance\n\n")
        f.write("### LOGISTIC MODEL (new)\n\n")
        f.write(_df_to_md(model_q))
        f.write("\n### LEGACY TIERED (v1)\n\n")
        f.write(_df_to_md(legacy_q))

        f.write(f"\n**Q5 - Q1 spread, LEGACY:** {q5_old - q1_old:+.4f}  "
                f"(Q1={q1_old:+.4f}, Q5={q5_old:+.4f})\n\n")
        f.write(f"**Q5 - Q1 spread, MODEL:**  {q5_new - q1_new:+.4f}  "
                f"(Q1={q1_new:+.4f}, Q5={q5_new:+.4f})\n\n")
        f.write("## Verdict\n\n")
        f.write(f"{verdict}\n")
    print(f"\n[fit] report -> {md_path}")

    return {
        "model":    model,
        "model_q":  model_q,
        "legacy_q": legacy_q,
        "trades":   trades,
        "q_spread_model":  q5_new - q1_new,
        "q_spread_legacy": q5_old - q1_old,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=config.TICKERS)
    ap.add_argument("--lookback-days", type=int, default=500)
    ap.add_argument("--real", action="store_true",
                    help="Use real sentiment history instead of synthetic demo")
    ap.add_argument("--skip-backtest", action="store_true",
                    help="Re-use existing backtest_*_demo.csv logs without regenerating")
    args = ap.parse_args()

    run(
        tickers       = args.tickers,
        demo          = not args.real,
        lookback_days = args.lookback_days,
        skip_backtest = args.skip_backtest,
    )

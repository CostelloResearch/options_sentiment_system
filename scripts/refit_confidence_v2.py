# =============================================================================
# scripts/refit_confidence_v2.py -- Versioned logistic refit on the new corpus
#
# PURPOSE
# -------
# Step 9 of the 2026-04-25 universe rebuild.  The production logistic
# (data/raw/confidence_model.json) was trained on the 5-ticker mega-cap-tech
# corpus.  The 10-ticker universe spans 6 sectors and 3 asset classes;
# coefficients will shift when (sentiment, iv_rank, momentum, ...) features
# are evaluated against trades that aren't all AAPL/NVDA/MSFT/SPY/QQQ.
#
# We DELIBERATELY save under a new versioned filename
# (data/raw/confidence_model_v2_10t.json) so the old production model stays
# bit-for-bit reproducible while we A/B the new fit.  The system loader
# (signals.confidence_model.load_model) only ever reads the canonical
# `confidence_model.json` -- swapping a v2 model into production is a
# deliberate later step (rename / symlink / overwrite).
#
# OUTPUT
# ------
#   data/raw/confidence_model_v2_10t.json   -- fitted parameters
#   outputs/confidence_model_v2_report.md   -- coefficient + Q5-Q1 report
# =============================================================================

from __future__ import annotations

import os
import sys
import json
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from signals import confidence_model


OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "outputs"))
RAW_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))


def _load_flat_logs(tickers, demo: bool = True) -> pd.DataFrame:
    pfx = "_demo" if demo else ""
    frames = []
    for t in tickers:
        p = os.path.join(RAW_DIR, f"backtest_{t}{pfx}.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _df_to_md(df, fmt=".4f"):
    if df.empty:
        return "_(empty)_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (int, np.integer)):
                cells.append(f"{int(v)}")
            elif isinstance(v, (float, np.floating)):
                cells.append("-" if pd.isna(v) else f"{float(v):{fmt}}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(tickers, demo: bool = True, version_tag: str = "v2_10t"):
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)

    print(f"[refit] loading flat corpus for {tickers}")
    trades = _load_flat_logs(tickers, demo=demo)
    if trades.empty:
        print("[refit] no flat logs on disk; run segregated_kelly_report first.")
        return

    accepted = trades[trades["accepted"].astype(bool)] if "accepted" in trades.columns else trades
    print(f"[refit] {len(trades)} signal rows, {len(accepted)} accepted "
          f"across {trades['ticker'].nunique()} tickers.")

    # Fit but DO NOT overwrite the production model file
    model = confidence_model.fit_from_trade_log(trades, save=False)
    versioned_path = os.path.join(RAW_DIR, f"confidence_model_{version_tag}.json")
    confidence_model.save_model(model, path=versioned_path)
    print(f"[refit] -> {versioned_path}")
    print(confidence_model.summarise(model))

    # Quintile validation (in-sample)
    q_new = confidence_model.validate_quintiles(trades, model, horizon_col="pnl_pct")
    print("\n[refit] in-sample quintile P&L (new v2 fit):")
    print(q_new.to_string(index=False))

    # Compare against the old production model if present
    old_model = confidence_model.load_model()  # canonical path
    q_old = pd.DataFrame()
    if old_model is not None:
        q_old = confidence_model.validate_quintiles(trades, old_model,
                                                    horizon_col="pnl_pct")
        print("\n[refit] in-sample quintile P&L (OLD 5-ticker model on new corpus):")
        print(q_old.to_string(index=False))

    # Coefficient comparison table
    coef_rows = []
    for i, name in enumerate(model["feature_names"]):
        row = {
            "feature":     name,
            "mean_new":    round(float(model["mean"][i]), 4),
            "std_new":     round(float(model["std"][i]),  4),
            "beta_new":    round(float(model["beta"][i]), 4),
        }
        if old_model is not None and i < len(old_model.get("beta", [])):
            row["beta_old_5t"] = round(float(old_model["beta"][i]), 4)
        coef_rows.append(row)
    coef_df = pd.DataFrame(coef_rows)

    # Markdown
    md_path = os.path.join(OUT_DIR, f"confidence_model_{version_tag}_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Logistic Confidence Refit -- {version_tag}\n\n")
        f.write(f"_Refit on the 2026-04-25 universe rebuild "
                f"({len(tickers)} tickers, {len(accepted)} accepted trades)._\n\n")
        f.write(f"_Versioned filename `confidence_model_{version_tag}.json` -- "
                f"production loader still reads `confidence_model.json` (the "
                f"5-ticker fit).  Promote by overwrite/rename when ready._\n\n")

        f.write("## 1. Fit summary\n\n```\n")
        f.write(confidence_model.summarise(model))
        f.write(f"\nintercept = {model['intercept']:+.4f}\n```\n\n")

        f.write("## 2. Coefficients (new vs old 5-ticker)\n\n")
        f.write(_df_to_md(coef_df))
        f.write("\n")

        f.write("## 3. In-sample quintile P&L (new v2 model)\n\n")
        f.write(_df_to_md(q_new))
        f.write("\n")

        if not q_old.empty:
            f.write("## 4. In-sample quintile P&L (OLD 5-ticker model on new corpus)\n\n")
            f.write(_df_to_md(q_old))
            f.write("\n")

        # Q5 - Q1 spread, both
        try:
            q1n = float(q_new[q_new["quintile"] == "Q1 (lowest)"]["mean_ret"].iloc[0])
            q5n = float(q_new[q_new["quintile"] == "Q5 (highest)"]["mean_ret"].iloc[0])
            f.write(f"\n**Q5-Q1 spread (NEW v2 model):** {q5n - q1n:+.4f} "
                    f"(Q1={q1n:+.4f}, Q5={q5n:+.4f})\n\n")
        except Exception:
            pass

        f.write("## 5. Notes\n\n")
        f.write(
            "- Coefficient sign flips between the 5-ticker fit and this "
            "10-ticker fit are diagnostic: a feature that mattered in tech "
            "may not survive on a sector-diverse corpus.  Interpret in the "
            "context of the per-sector decay results "
            "(`outputs/sector_decay_analysis.md`).\n"
            "- Quintile edges in the production sizer "
            "(`data/raw/quintile_edges.json`) are NOT updated by this "
            "script -- they're still calibrated against the old model.  "
            "Promotion of the v2 model into production should refit the "
            "edges via `position_sizer.compute_and_save_quintile_edges` on "
            "the new corpus.\n"
            "- The new corpus is a fresh strategy: do NOT compare the "
            "Q5-Q1 spread reported here against the +15.76pp documented in "
            "PROJECT_STATE for the 5-ticker fit.  Different universe, "
            "different trade distribution.\n"
        )

    print(f"\n[refit] -> {md_path}")
    return {"model_path": versioned_path, "md_path": md_path,
            "coef_df": coef_df, "q_new": q_new, "q_old": q_old}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=config.TICKERS)
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--version-tag", default="v2_10t")
    args = ap.parse_args()
    main(args.tickers, demo=not args.real, version_tag=args.version_tag)

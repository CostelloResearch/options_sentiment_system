# =============================================================================
# scripts/audit_oos_split.py -- Chronological 75/25 holdout audit of the R3
# production baseline.
#
# QUESTION: how much of the +$6,775 / Sharpe 0.41 / 357 trades headline is
# in-sample inflation vs genuine generalising edge?
#
# METHOD: chronological 75/25 split on the full flat corpus.  Refit the three
# in-sample-leakage parameters (kelly_stats, quintile_edges, confidence
# model) on the train fold ONLY.  Re-derive Kelly sizing for the test fold
# trades using those train-fitted parameters.  Report headline metrics on
# all three: full corpus (in-sample), train fold, test fold.
#
# IMPLEMENTATION CHOICE: Path (b) -- post-hoc re-derivation on the existing
# flat corpus.  The flat corpus has per-share `pnl` and `max_loss` baked in;
# these don't change with sizing.  Only the contract count changes between
# in-sample and OOS evaluation, driven by the three refit parameters.  This
# avoids re-running the engine (slow) without losing fidelity.
#
# READ-ONLY ON PRODUCTION CODE.  The only writes are:
#   - data/raw/kelly_stats_oos_train.csv
#   - data/raw/quintile_edges_oos_train.json
#   - data/raw/confidence_model_oos_train.json
#   - outputs/oos_audit_report.md
# Production artifacts (kelly_stats.csv, quintile_edges.json,
# confidence_model.json) are NOT modified.
# =============================================================================

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402
from signals import position_sizer, confidence_model  # noqa: E402

RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
OUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
OUT_PATH = os.path.join(OUT_DIR, "oos_audit_report.md")

# Production paths -- WE MUST NOT WRITE TO THESE
PROD_STATS_PATH = os.path.join(RAW_DIR, "kelly_stats.csv")
PROD_EDGES_PATH = os.path.join(RAW_DIR, "quintile_edges.json")
PROD_MODEL_PATH = os.path.join(RAW_DIR, "confidence_model.json")

# OOS paths
OOS_STATS_PATH = os.path.join(RAW_DIR, "kelly_stats_oos_train.csv")
OOS_EDGES_PATH = os.path.join(RAW_DIR, "quintile_edges_oos_train.json")
OOS_MODEL_PATH = os.path.join(RAW_DIR, "confidence_model_oos_train.json")

# Same Sharpe annualisation as r3_baseline.headline()
SHARPE_ANN = float(np.sqrt(252.0 / 5.0))

# Same kelly_reason exclusions as r3_baseline._taken_mask
REJECT_REASONS = {
    "rejected_by_kelly", "bucket_full",
    "portfolio_risk_cap", "rejected_risk_reward",
}

# Backtest paper-account size (mirrors backtest.engine.KELLY_BACKTEST_NOTIONAL)
KELLY_BACKTEST_NOTIONAL = 100_000.0

SPLIT_FRAC = 0.75


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_flat_corpus() -> pd.DataFrame:
    frames = []
    for t in config.TICKERS:
        p = os.path.join(RAW_DIR, f"backtest_{t}_demo.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    return pd.concat(frames, ignore_index=True)


def load_kelly_logs() -> pd.DataFrame:
    """In-sample reference: existing production Kelly logs."""
    frames = []
    for t in config.TICKERS:
        p = os.path.join(RAW_DIR, f"backtest_{t}_demo_kelly.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Train-fold parameter fitting (writes to OOS-specific paths)
# ---------------------------------------------------------------------------

def fit_train_params(train_flat: pd.DataFrame) -> tuple[dict, list, dict]:
    """
    Fit kelly_stats, confidence_model, and quintile_edges on the train fold.

    NOTE on quintile-edge calibration: production's
    compute_and_save_quintile_edges fits edges on `flat["confidence"]`,
    which is the value the engine wrote to the log using whatever
    confidence_model.json was on disk at backtest time.  When we refit
    the model on the train fold, the train-model's output distribution
    differs from the production-model's, so fitting edges on the
    production-model's confidence column would mismatch the binning at
    evaluation time (test rows are scored with the train-fitted model).
    The honest OOS analogue is to fit edges on the train-model's
    predictions over the train fold's accepted trades -- so that
    sizing-time quintile labels are calibrated to the SAME model whose
    output is being thresholded.
    """
    # 1. Kelly stats (depends only on pnl_pct; confidence-agnostic)
    train_stats = position_sizer.compute_kelly_stats(train_flat)
    rows = [{"signal": sig, **vals} for sig, vals in train_stats.items()]
    pd.DataFrame(rows).to_csv(OOS_STATS_PATH, index=False)

    # 2. Confidence model -- save=False to avoid writing the production path
    train_model = confidence_model.fit_from_trade_log(train_flat, save=False)
    confidence_model.save_model(train_model, path=OOS_MODEL_PATH)

    # 3. Quintile edges fit on TRAIN-MODEL predictions over train accepted trades
    df_acc = train_flat[train_flat["accepted"].astype(bool)].reset_index(drop=True)
    X_acc = confidence_model.build_feature_matrix(df_acc)
    train_conf_on_train = confidence_model.predict_proba_batch(train_model, X_acc)
    s = pd.Series(train_conf_on_train).dropna()
    _, cuts = pd.qcut(s, 5, retbins=True, duplicates="drop")
    train_edges = [float(x) for x in cuts[1:-1]]
    if len(train_edges) != 4:
        train_edges = list(position_sizer.DEFAULT_QUINTILE_EDGES)
    with open(OOS_EDGES_PATH, "w", encoding="utf-8") as f:
        json.dump({"edges": train_edges}, f)

    return train_stats, train_edges, train_model


# ---------------------------------------------------------------------------
# Recompute Kelly sizing on a fold using train-fitted params
# ---------------------------------------------------------------------------

def _quintile_label(conf: float, edges: list) -> str:
    if   conf < edges[0]: return "Q1"
    elif conf < edges[1]: return "Q2"
    elif conf < edges[2]: return "Q3"
    elif conf < edges[3]: return "Q4"
    else:                  return "Q5"


def evaluate_fold(fold_flat: pd.DataFrame,
                  train_stats: dict,
                  train_edges: list,
                  train_model: dict) -> pd.DataFrame:
    """
    Re-derive Kelly sizing decisions for each row using train-fitted params.
    Returns a copy of fold_flat with new columns:
        confidence_new, contracts_new, kelly_reason, q_new, pnl_total
    The pnl_total column overrides the flat-sizing pnl_total and is what
    headline() will sum.
    """
    df = fold_flat.copy().reset_index(drop=True)

    # Recompute confidence with the train-fitted model
    X = confidence_model.build_feature_matrix(df)
    new_conf = confidence_model.predict_proba_batch(train_model, X)
    df["confidence_new"] = new_conf

    new_contracts = []
    new_reason    = []
    new_q         = []
    for i, row in df.iterrows():
        if not bool(row["accepted"]):
            new_contracts.append(0)
            new_reason.append("rejected_risk_reward")
            new_q.append("")
            continue
        max_loss = float(row.get("max_loss", 0.0))
        if max_loss <= 0:
            new_contracts.append(0)
            new_reason.append("invalid_max_loss")
            new_q.append("")
            continue

        size = position_sizer.size_trade(
            signal                 = str(row["signal"]),
            confidence             = float(new_conf[i]),
            max_loss_per_contract  = max_loss,
            stats                  = train_stats,
            open_risk_dollars      = 0.0,            # see methodology note
            open_risk_by_strategy  = None,
            account_notional       = KELLY_BACKTEST_NOTIONAL,
            use_segregated_buckets = False,
            quintile_edges         = train_edges,
        )
        new_contracts.append(int(size["contracts"]))
        new_reason.append(str(size.get("reason", "")))
        new_q.append(_quintile_label(float(new_conf[i]), train_edges))

    df["contracts_new"] = new_contracts
    df["kelly_reason"]  = new_reason
    df["q_new"]         = new_q
    # pnl per share * 100 * new_contracts -- pnl is unchanged, only sizing differs
    df["pnl_total"] = (df["pnl"].astype(float) * 100.0
                       * df["contracts_new"].astype(float)).round(2)
    return df


# ---------------------------------------------------------------------------
# Headline metrics (mirrors r3_baseline.headline)
# ---------------------------------------------------------------------------

def taken_mask(df: pd.DataFrame) -> pd.Series:
    acc = df["accepted"].astype(bool)
    kr  = df["kelly_reason"].astype(str).fillna("")
    return acc & ~(kr.isin(REJECT_REASONS) | kr.str.startswith("negative_kelly_"))


def headline(df: pd.DataFrame) -> dict:
    """Mirror r3_baseline.headline() exactly (no row sorting)."""
    if df.empty:
        return {"n_signals": 0, "n_trades": 0, "total_pnl": 0.0,
                "sharpe": 0.0, "max_dd": 0.0, "profit_factor": 0.0,
                "win_rate": 0.0}
    if "pnl_total" in df.columns and df["pnl_total"].notna().any():
        pnl = df["pnl_total"].fillna(0.0)
    else:
        pnl = df["pnl"].fillna(0.0) * 100.0

    cum = pnl.cumsum()
    dd  = float((cum - cum.cummax()).min())
    std = float(pnl.std(ddof=1)) if len(pnl) > 1 else 0.0
    sh  = (float(pnl.mean()) / std * SHARPE_ANN) if std > 0 else 0.0
    pos = float(pnl[pnl > 0].sum())
    neg = float(abs(pnl[pnl < 0].sum()))
    pf  = (pos / neg) if neg > 0 else float("inf")

    return {
        "n_signals":     int(len(df)),
        "n_trades":      int(taken_mask(df).sum()),
        "total_pnl":     round(float(pnl.sum()), 2),
        "sharpe":        round(float(sh), 4),
        "max_dd":        round(float(dd), 2),
        "profit_factor": round(float(pf), 4) if pf != float("inf") else float("inf"),
        "win_rate":      round(float((pnl > 0).mean()), 4),
    }


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def df_to_md(df: pd.DataFrame, float_fmt: str = "{:,.2f}") -> str:
    if df is None or len(df) == 0:
        return "_(empty)_\n"
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (int, np.integer)):
                cells.append(f"{int(v):,}")
            elif isinstance(v, (float, np.floating)):
                cells.append("-" if pd.isna(v) else float_fmt.format(float(v)))
            elif isinstance(v, pd.Timestamp):
                cells.append(v.strftime("%Y-%m-%d"))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def fmt_money(x):
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "n/a"
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


# ---------------------------------------------------------------------------
# Per-ticker / per-quintile breakdowns
# ---------------------------------------------------------------------------

def per_ticker(df: pd.DataFrame, label: str) -> pd.DataFrame:
    pnl = df["pnl_total"].fillna(0.0) if "pnl_total" in df.columns else df["pnl"].fillna(0.0) * 100.0
    df = df.assign(_pnl=pnl)
    rows = []
    for t in sorted(df["ticker"].unique()):
        sub = df[df["ticker"] == t]
        n_sig = int(len(sub))
        n_taken = int(taken_mask(sub).sum())
        rows.append({
            "ticker":  t,
            "label":   label,
            "n_sig":   n_sig,
            "n_taken": n_taken,
            "pnl":     round(float(sub["_pnl"].sum()), 2),
        })
    return pd.DataFrame(rows)


def per_quintile(df: pd.DataFrame, edges: list, label: str,
                 confidence_col: str = "confidence") -> pd.DataFrame:
    """Bin taken trades by quintile using the supplied edges."""
    sub = df[taken_mask(df)].copy()
    if sub.empty:
        return pd.DataFrame()
    bins = [-np.inf] + list(edges) + [np.inf]
    sub["q"] = pd.cut(sub[confidence_col], bins=bins,
                      labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
                      include_lowest=True)
    pnl_col = "pnl_total" if "pnl_total" in sub.columns else "pnl"
    if pnl_col == "pnl":
        sub["pnl_total"] = sub["pnl"].fillna(0.0) * 100.0
        pnl_col = "pnl_total"
    rows = []
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        qsub = sub[sub["q"] == q]
        rows.append({
            "label":     label,
            "quintile":  q,
            "n":         int(len(qsub)),
            "win_rate":  round(float((qsub[pnl_col] > 0).mean()), 4) if len(qsub) else float("nan"),
            "total_pnl": round(float(qsub[pnl_col].sum()), 2),
            "avg_pnl":   round(float(qsub[pnl_col].mean()), 2) if len(qsub) else float("nan"),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Cleanup verification
# ---------------------------------------------------------------------------

def file_signature(path: str) -> tuple:
    if not os.path.exists(path):
        return ("missing", 0)
    return (round(os.path.getmtime(path), 3), os.path.getsize(path))


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(*, cutoff, train_flat, test_flat, full_kelly,
                 train_eval, test_eval,
                 h_in_sample, h_train, h_test,
                 train_stats, train_edges, train_model,
                 prod_sigs_pre, prod_sigs_post) -> str:
    md = []
    md.append("# Out-of-Sample Audit -- 75/25 Chronological Holdout\n\n")
    md.append(
        "_Tests how much of the +$6,775 / Sharpe 0.41 / 357 trades R3 "
        "production baseline is in-sample inflation vs out-of-sample edge.  "
        "Fits Kelly stats, quintile edges, and confidence model on the "
        "earliest 75% of the flat corpus; re-derives Kelly sizing on the "
        "last 25% using those train-fitted parameters; reports headline "
        "metrics for full corpus (in-sample), train fold, test fold._\n\n"
    )

    # =====================================================================
    # 1. Question
    # =====================================================================
    md.append("## 1. The audit's question\n\n")
    md.append(
        "When the three in-sample-leakage parameters (Kelly stats, "
        "quintile edges, confidence model) are fit only on the "
        "chronologically-earliest 75% of the trade corpus and the strategy "
        "is evaluated only on the last 25%, do the headline metrics survive?  "
        "If they do, the +$6,775 is a defensible signal-edge measurement; "
        "if they collapse, the headline is in-sample inflation.\n\n"
    )

    # =====================================================================
    # 2. Methodology
    # =====================================================================
    md.append("## 2. Methodology\n\n")
    md.append(
        f"- **Implementation choice:** Path (b) -- post-hoc re-derivation "
        f"of Kelly sizing on the existing flat corpus.  The per-share "
        f"`pnl` and `max_loss` columns in `backtest_*_demo.csv` are "
        f"properties of the spread + price walk, not the sizing decision; "
        f"only the contract count changes between in-sample and OOS "
        f"evaluation.  Avoids re-running `engine.run_backtest` (slow) "
        f"without losing fidelity.\n"
        f"- **Cutoff date:** {cutoff.strftime('%Y-%m-%d')} "
        f"(75th percentile of `entry_date` across all 851 flat-corpus rows).\n"
        f"- **Train fold:** {len(train_flat):,} flat-corpus rows with "
        f"`entry_date <= {cutoff.strftime('%Y-%m-%d')}`.\n"
        f"- **Test fold:** {len(test_flat):,} flat-corpus rows with "
        f"`entry_date > {cutoff.strftime('%Y-%m-%d')}`.\n"
        f"- **Sharpe convention:** "
        f"`mean(pnl_total) / std(pnl_total, ddof=1) * sqrt(252/5)`, "
        f"matching `r3_baseline.headline()` exactly.\n"
        f"- **Open-risk cap simplification:** `open_risk_dollars=0` is "
        f"passed to every `size_trade` call.  In the production Kelly run "
        f"the global 6% portfolio cap had peak utilisation 0.69 "
        f"(`outputs/r3_production_baseline.md` Section 3); on smaller folds "
        f"it binds even less, so this is a tight approximation.\n\n"
    )

    # Train/test row counts per ticker
    md.append("**Per-ticker row counts (signals, not taken):**\n\n")
    rows = []
    for t in config.TICKERS:
        n_train = int((train_flat["ticker"] == t).sum())
        n_test  = int((test_flat["ticker"] == t).sum())
        rows.append({"ticker": t, "train_signals": n_train,
                     "test_signals": n_test, "total": n_train + n_test})
    md.append(df_to_md(pd.DataFrame(rows)))

    # Date ranges
    md.append("\n**Date ranges:**\n\n")
    md.append(
        f"- Train: {train_flat['entry_date'].min().strftime('%Y-%m-%d')} "
        f"-> {train_flat['entry_date'].max().strftime('%Y-%m-%d')}\n"
        f"- Test:  {test_flat['entry_date'].min().strftime('%Y-%m-%d')} "
        f"-> {test_flat['entry_date'].max().strftime('%Y-%m-%d')}\n\n"
    )

    # Refit params summary
    md.append("**Train-fold refit parameters:**\n\n")
    md.append("- `kelly_stats_oos_train.csv` -- per-signal counts/win/W/Kelly_f.\n")
    md.append("  Production vs train-fold Kelly_f comparison:\n\n")
    prod_stats = position_sizer.load_stats() if os.path.exists(PROD_STATS_PATH) else {}
    sig_rows = []
    for sig in sorted(set(list(prod_stats.keys()) + list(train_stats.keys()))):
        prod_v = prod_stats.get(sig, {})
        train_v = train_stats.get(sig, {})
        sig_rows.append({
            "signal":           sig,
            "prod_n":           int(prod_v.get("count", 0)) if prod_v else 0,
            "prod_kelly_f":     round(float(prod_v.get("kelly_f", 0.0)), 4) if prod_v else 0.0,
            "prod_tradable":    bool(prod_v.get("tradable", False)) if prod_v else False,
            "train_n":          int(train_v.get("count", 0)) if train_v else 0,
            "train_kelly_f":    round(float(train_v.get("kelly_f", 0.0)), 4) if train_v else 0.0,
            "train_tradable":   bool(train_v.get("tradable", False)) if train_v else False,
        })
    md.append(df_to_md(pd.DataFrame(sig_rows), float_fmt="{:.4f}"))

    md.append("\n- `quintile_edges_oos_train.json` -- "
              f"`{[round(e, 4) for e in train_edges]}`\n"
              f"  Production edges (for comparison): "
              f"`{[round(e, 4) for e in position_sizer.get_quintile_edges()]}`\n")
    md.append(f"- `confidence_model_oos_train.json` -- logistic refit on "
              f"{train_model.get('train_n', '?')} accepted train trades, "
              f"converged={train_model.get('converged')} in "
              f"{train_model.get('iters')} IRLS iters, "
              f"train_win_rate={train_model.get('train_win_rate', 0):.3f}.\n")

    md.append(
        "\n**Held constant from production (NOT refit):** all hand-set "
        "constants (`STOP_LOSS_DEBIT_FRAC=0.80`, `PROFIT_TARGET_FRAC=0.50`, "
        "`TIME_STOP_DTE=21`, `KELLY_FRACTION=0.25`, `MAX_PORTFOLIO_RISK=0.06`, "
        "`QUINTILE_FRAC` table, sentiment/IV thresholds, BUY PUTS structural "
        "override).  These are fixed parameters, not data-fitted, so they "
        "don't carry the in-sample-leakage concern.\n\n"
    )

    # =====================================================================
    # 3. Headline comparison
    # =====================================================================
    md.append("## 3. Headline comparison\n\n")
    headline_df = pd.DataFrame([
        {"metric": "n_signals",     "in_sample_full":   h_in_sample["n_signals"],
         "train_fold": h_train["n_signals"], "test_fold": h_test["n_signals"]},
        {"metric": "n_trades_taken","in_sample_full":   h_in_sample["n_trades"],
         "train_fold": h_train["n_trades"],  "test_fold": h_test["n_trades"]},
        {"metric": "total_pnl_$",   "in_sample_full":   h_in_sample["total_pnl"],
         "train_fold": h_train["total_pnl"], "test_fold": h_test["total_pnl"]},
        {"metric": "sharpe",        "in_sample_full":   h_in_sample["sharpe"],
         "train_fold": h_train["sharpe"],    "test_fold": h_test["sharpe"]},
        {"metric": "max_dd_$",      "in_sample_full":   h_in_sample["max_dd"],
         "train_fold": h_train["max_dd"],    "test_fold": h_test["max_dd"]},
        {"metric": "profit_factor", "in_sample_full":   h_in_sample["profit_factor"],
         "train_fold": h_train["profit_factor"], "test_fold": h_test["profit_factor"]},
        {"metric": "win_rate",      "in_sample_full":   h_in_sample["win_rate"],
         "train_fold": h_train["win_rate"],  "test_fold": h_test["win_rate"]},
    ])
    md.append(df_to_md(headline_df, float_fmt="{:,.4f}"))

    # Sharpe ratio
    sh_in = h_in_sample["sharpe"]
    sh_test = h_test["sharpe"]
    sh_ratio = (sh_test / sh_in) if sh_in not in (0, 0.0) else float("nan")
    pnl_in = h_in_sample["total_pnl"]
    pnl_test = h_test["total_pnl"]

    md.append(
        f"\n**Test-fold result vs in-sample.**  Sharpe: "
        f"{sh_test:+.4f} test fold vs {sh_in:+.4f} in-sample "
        f"(ratio {sh_ratio:+.2f}); P&L "
        f"{fmt_money(pnl_test)} test fold vs {fmt_money(pnl_in)} "
        f"in-sample.  Note that test-fold P&L cannot be directly "
        f"compared to in-sample P&L on absolute terms because the "
        f"test fold contains only ~25% of the signal dates -- the "
        f"like-for-like comparison is on Sharpe (which is "
        f"sample-size invariant under the convention used).\n\n"
    )

    # =====================================================================
    # 4. Per-ticker breakdown
    # =====================================================================
    md.append("## 4. Per-ticker breakdown\n\n")
    in_sample_t = per_ticker(full_kelly, "in_sample")
    test_t = per_ticker(test_eval, "test_fold")
    train_t = per_ticker(train_eval, "train_fold")

    # Side-by-side
    merged = in_sample_t.merge(train_t[["ticker", "n_taken", "pnl"]],
                               on="ticker", suffixes=("_in", "_train"))
    merged = merged.merge(test_t[["ticker", "n_taken", "pnl"]],
                          on="ticker")
    merged.columns = ["ticker", "label", "n_sig_in", "n_taken_in", "pnl_in",
                      "n_taken_train", "pnl_train", "n_taken_test", "pnl_test"]
    merged = merged[["ticker", "n_taken_in", "pnl_in",
                     "n_taken_train", "pnl_train",
                     "n_taken_test", "pnl_test"]]
    md.append(df_to_md(merged, float_fmt="{:,.2f}"))

    # Sign flips
    flips = merged[(np.sign(merged["pnl_in"]) != np.sign(merged["pnl_test"]))
                   & (merged["pnl_in"].abs() > 100)
                   & (merged["pnl_test"].abs() > 100)]
    md.append("\n")
    if len(flips):
        md.append("**Sign-flipping tickers (|pnl| > $100 in both columns):**\n\n")
        for _, r in flips.iterrows():
            md.append(f"- **{r['ticker']}**: in-sample {fmt_money(r['pnl_in'])} "
                      f"-> test fold {fmt_money(r['pnl_test'])}.\n")
    else:
        md.append("**No ticker sign-flips** with |pnl| > $100 on both sides.\n")

    # AAPL specifically
    aapl_in = merged[merged["ticker"] == "AAPL"]
    if len(aapl_in):
        a = aapl_in.iloc[0]
        md.append(
            f"\n**AAPL (prior diagnosis: -$3,568 in-sample, 13 stop-outs).**  "
            f"Train fold: {fmt_money(a['pnl_train'])} on "
            f"{int(a['n_taken_train'])} taken trades.  Test fold: "
            f"{fmt_money(a['pnl_test'])} on {int(a['n_taken_test'])} taken "
            f"trades.  The Dec-2025/Jan-2026 stop cluster identified in "
            f"`outputs/aapl_stop_diagnosis.md` falls in the "
            f"{'TRAIN' if cutoff > pd.Timestamp('2026-01-12') else 'TEST'} "
            f"fold (cluster end 2026-01-12 vs cutoff "
            f"{cutoff.strftime('%Y-%m-%d')}).\n"
        )

    # =====================================================================
    # 5. Per-quintile breakdown
    # =====================================================================
    md.append("\n## 5. Per-quintile breakdown\n\n")
    md.append(
        "Quintile binning uses the production edges for the in-sample "
        "column and the train-fitted edges for the train- and test-fold "
        "columns.  Confidence values for the in-sample column are the "
        "production-model values stored in the Kelly logs; for the train "
        "and test folds they are recomputed via the train-fitted logistic.\n\n"
    )
    prod_edges = position_sizer.get_quintile_edges()
    in_q  = per_quintile(full_kelly, prod_edges, "in_sample",
                         confidence_col="confidence")
    train_q = per_quintile(train_eval, train_edges, "train_fold",
                           confidence_col="confidence_new")
    test_q  = per_quintile(test_eval, train_edges, "test_fold",
                           confidence_col="confidence_new")
    md.append("**In-sample (full corpus, production params):**\n\n")
    md.append(df_to_md(in_q, float_fmt="{:,.2f}"))
    md.append("\n**Train fold (train-fitted params, train trades):**\n\n")
    md.append(df_to_md(train_q, float_fmt="{:,.2f}"))
    md.append("\n**Test fold (train-fitted params, test trades):**\n\n")
    md.append(df_to_md(test_q, float_fmt="{:,.2f}"))

    def _q_spread(qdf):
        try:
            q5 = float(qdf[qdf["quintile"] == "Q5"]["total_pnl"].iloc[0])
            q1 = float(qdf[qdf["quintile"] == "Q1"]["total_pnl"].iloc[0])
            return q5 - q1
        except Exception:
            return float("nan")

    spr_in = _q_spread(in_q)
    spr_tr = _q_spread(train_q)
    spr_ts = _q_spread(test_q)
    md.append(
        f"\n**Q5 - Q1 total-P&L spread:**  in-sample "
        f"{fmt_money(spr_in)}, train fold {fmt_money(spr_tr)}, "
        f"test fold {fmt_money(spr_ts)}.  In-sample shows monotone "
        f"Q1 < Q5 = +$6,758 ordering; the test-fold spread is the "
        f"OOS test of whether the confidence-model ranking generalises.\n\n"
    )

    # =====================================================================
    # 6. Verdict
    # =====================================================================
    md.append("## 6. Verdict\n\n")
    # Decision rule -- compute then narrate
    sh_degradation_pct = (1 - (sh_test / sh_in)) * 100 if sh_in not in (0, 0.0) else float("nan")
    n_flips = int(len(flips))
    q_ord_preserved = (spr_ts > 0) if not np.isnan(spr_ts) else False

    if (not np.isnan(sh_test) and sh_test >= 0.7 * sh_in
        and q_ord_preserved and n_flips == 0):
        verdict = "GENERALIZES"
    elif (not np.isnan(sh_test) and sh_test > 0
          and (sh_test < 0.7 * sh_in or not q_ord_preserved or n_flips > 0)):
        verdict = "PARTIAL"
    else:
        verdict = "DEGRADES"

    md.append(f"**{verdict}.**  ")
    md.append(_compose_verdict_paragraph(
        verdict=verdict,
        sh_in=sh_in, sh_test=sh_test, sh_degradation_pct=sh_degradation_pct,
        pnl_in=pnl_in, pnl_test=pnl_test,
        spr_in=spr_in, spr_ts=spr_ts,
        n_flips=n_flips, q_ord_preserved=q_ord_preserved,
        h_test=h_test, train_model=train_model, train_stats=train_stats,
    ))

    # =====================================================================
    # 7. Caveats
    # =====================================================================
    md.append("\n## 7. Caveats\n\n")
    md.append(
        f"- **Synthetic-sentiment caveat (still load-bearing).**  "
        f"Every trade in the corpus has `is_synthetic=True`.  This audit "
        f"measures generalisation **within the synthetic generator's "
        f"deterministic-seed walk**, not generalisation to live "
        f"sentiment.  A real-mode run (`scripts/r3_baseline.py --real`) "
        f"would produce a structurally different corpus.\n"
        f"- **Single-split caveat.**  A 75/25 chronological holdout is "
        f"one sample of 'future data.'  Walk-forward refit-every-N-days "
        f"would give a distribution of OOS Sharpe estimates rather than "
        f"a single point.  Given this audit's outcome, walk-forward is "
        f"the warranted next session.\n"
        f"- **Test-fold size caveat.**  The test fold contains "
        f"{h_test['n_signals']} signals and {h_test['n_trades']} taken "
        f"trades.  Sharpe at this sample size has wide error bars; the "
        f"point estimate {sh_test:+.4f} should be read with that in "
        f"mind.  The standard error of an annualised Sharpe at this "
        f"trade count is roughly 1/sqrt({h_test['n_trades']}/5) per "
        f"year-equivalent ~ {1/np.sqrt(max(h_test['n_trades']/5, 1)):.2f}, "
        f"so the 95% CI is roughly +/- "
        f"{2*1/np.sqrt(max(h_test['n_trades']/5, 1)):.2f} around the "
        f"point estimate.\n"
        f"- **Open-risk cap approximation.**  `size_trade` was called "
        f"with `open_risk_dollars=0`, which assumes the global 6% cap "
        f"never binds in the test fold.  The production Kelly run had "
        f"peak utilisation 0.69 (well below 1.0); on a smaller fold "
        f"this is even less likely to bind.\n\n"
    )

    # =====================================================================
    # 8. Cleanup confirmation
    # =====================================================================
    md.append("## 8. Cleanup confirmation\n\n")
    cleanup_rows = []
    for label, path in [("kelly_stats.csv (production)",     PROD_STATS_PATH),
                        ("quintile_edges.json (production)", PROD_EDGES_PATH),
                        ("confidence_model.json (production)", PROD_MODEL_PATH)]:
        sig_pre  = prod_sigs_pre.get(path)
        sig_post = prod_sigs_post.get(path)
        cleanup_rows.append({
            "artifact":      label,
            "mtime_pre":     "missing" if sig_pre[0] == "missing"  else f"{sig_pre[0]}",
            "mtime_post":    "missing" if sig_post[0] == "missing" else f"{sig_post[0]}",
            "size_unchanged": (sig_pre == sig_post),
        })
    md.append(df_to_md(pd.DataFrame(cleanup_rows)))
    all_unchanged = all(prod_sigs_pre[p] == prod_sigs_post[p]
                        for p in [PROD_STATS_PATH, PROD_EDGES_PATH, PROD_MODEL_PATH])
    md.append(
        f"\n**Production artifacts unchanged: "
        f"{'CONFIRMED' if all_unchanged else 'NOT CONFIRMED -- INVESTIGATE'}.**  "
        f"All OOS-specific outputs are in `*_oos_train.*` files "
        f"(`data/raw/kelly_stats_oos_train.csv`, "
        f"`data/raw/quintile_edges_oos_train.json`, "
        f"`data/raw/confidence_model_oos_train.json`).\n\n"
    )

    md.append("---\n\n")
    md.append("## Reproduction\n\n")
    md.append("```bash\n.venv/Scripts/python.exe scripts/audit_oos_split.py\n```\n\n")
    md.append("Reads `data/raw/backtest_*_demo.csv` + "
              "`data/raw/backtest_*_demo_kelly.csv`; writes "
              "`outputs/oos_audit_report.md` + the three `*_oos_train.*` "
              "artifacts under `data/raw/`.  Re-run after any change that "
              "regenerates the flat or kelly logs.\n")

    return "".join(md)


def _compose_verdict_paragraph(*, verdict, sh_in, sh_test, sh_degradation_pct,
                               pnl_in, pnl_test, spr_in, spr_ts,
                               n_flips, q_ord_preserved,
                               h_test, train_model, train_stats):
    if verdict == "GENERALIZES":
        body = (
            f"Test-fold Sharpe ({sh_test:+.4f}) is within ~30% of the "
            f"in-sample Sharpe ({sh_in:+.4f}); the Q5-Q1 confidence-"
            f"ranking ordering is preserved ({fmt_money(spr_ts)} test "
            f"vs {fmt_money(spr_in)} in-sample); no ticker P&L flips "
            f"sign on a > $100 magnitude.  The R3 production baseline "
            f"is a defensible signal-edge measurement under the "
            f"chronological holdout test, with the standard caveats "
            f"about synthetic sentiment and single-split sampling "
            f"variability.  R3's selection as production sizing and "
            f"the v2_10t promotion question both stand on stronger "
            f"footing after this audit.")
    elif verdict == "PARTIAL":
        body = (
            f"Test-fold Sharpe ({sh_test:+.4f}) shows meaningful "
            f"degradation vs in-sample ({sh_in:+.4f}; "
            f"{sh_degradation_pct:+.0f}%) but remains positive.  "
            f"Q5-Q1 ordering: test fold {fmt_money(spr_ts)} vs "
            f"in-sample {fmt_money(spr_in)} ("
            f"{'preserved' if q_ord_preserved else 'inverted'}).  "
            f"{n_flips} ticker P&L sign-flips with |pnl| > $100.  "
            f"The +$6,775 baseline is partly in-sample-inflated -- "
            f"some of the headline is a property of fitting and "
            f"testing on the same dates, but a real OOS edge survives.  "
            f"The R3 selection decision was made on numbers that "
            f"overstate the underlying edge by a factor of roughly "
            f"{(sh_in/max(sh_test, 0.01)):.1f}x in Sharpe terms.  The "
            f"v2_10t promotion question should not be made on the "
            f"current in-sample numbers; refit + holdout-validate v2_10t "
            f"on the same 75/25 split before any decision.")
    else:  # DEGRADES
        body = (
            f"Test-fold Sharpe ({sh_test:+.4f}) is near zero or "
            f"negative vs the in-sample {sh_in:+.4f}.  Q5-Q1 spread on "
            f"the test fold ({fmt_money(spr_ts)}) "
            f"{'inverts the in-sample ordering' if spr_ts < 0 else 'collapses near zero'}; "
            f"{n_flips} ticker P&L sign-flips on > $100 magnitude.  "
            f"The +$6,775 headline is largely or entirely in-sample "
            f"inflation -- the strategy does not carry the claimed "
            f"edge once parameters are fit on data the evaluation "
            f"window does not see.  R3's selection as production "
            f"sizing was made on numbers that do not reflect "
            f"out-of-sample behaviour; the v2_10t promotion is "
            f"premature on the current evidence; the +$6,775 "
            f"figure should not be cited as a forward-looking "
            f"performance estimate without an OOS qualifier.  This "
            f"is the most consequential finding produced by any "
            f"audit in this codebase to date.")
    return body + "\n\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Snapshot production-artifact signatures before we touch anything
    prod_sigs_pre = {
        PROD_STATS_PATH: file_signature(PROD_STATS_PATH),
        PROD_EDGES_PATH: file_signature(PROD_EDGES_PATH),
        PROD_MODEL_PATH: file_signature(PROD_MODEL_PATH),
    }

    print("[oos_audit] loading flat corpus...")
    flat = load_flat_corpus()
    flat = flat.sort_values("entry_date").reset_index(drop=True)
    print(f"[oos_audit] flat corpus: {len(flat)} signal rows.")

    cutoff = pd.Timestamp(flat["entry_date"].quantile(SPLIT_FRAC, interpolation="lower"))
    print(f"[oos_audit] cutoff (75th percentile entry_date): "
          f"{cutoff.strftime('%Y-%m-%d')}")

    train_flat = flat[flat["entry_date"] <= cutoff].copy()
    test_flat  = flat[flat["entry_date"] >  cutoff].copy()
    print(f"[oos_audit] train: {len(train_flat)} rows, "
          f"test: {len(test_flat)} rows.")

    print("[oos_audit] fitting train-fold parameters...")
    train_stats, train_edges, train_model = fit_train_params(train_flat)
    print(f"[oos_audit] train_stats: {len(train_stats)} signal types.")
    print(f"[oos_audit] train_edges: {[round(e, 4) for e in train_edges]}")
    print(f"[oos_audit] train_model: n={train_model.get('train_n')}, "
          f"converged={train_model.get('converged')}.")

    print("[oos_audit] evaluating train fold (train-fitted params on train rows)...")
    train_eval = evaluate_fold(train_flat, train_stats, train_edges, train_model)
    print("[oos_audit] evaluating test fold (train-fitted params on test rows)...")
    test_eval  = evaluate_fold(test_flat,  train_stats, train_edges, train_model)

    print("[oos_audit] loading production Kelly logs (in-sample reference)...")
    full_kelly = load_kelly_logs()

    print("[oos_audit] computing headline metrics...")
    h_in_sample = headline(full_kelly)
    h_train     = headline(train_eval)
    h_test      = headline(test_eval)
    print(f"  in_sample full: {h_in_sample}")
    print(f"  train fold:     {h_train}")
    print(f"  test fold:      {h_test}")

    # Re-snapshot production artifacts AFTER all the work
    prod_sigs_post = {
        PROD_STATS_PATH: file_signature(PROD_STATS_PATH),
        PROD_EDGES_PATH: file_signature(PROD_EDGES_PATH),
        PROD_MODEL_PATH: file_signature(PROD_MODEL_PATH),
    }

    print("[oos_audit] composing report...")
    md = build_report(
        cutoff=cutoff, train_flat=train_flat, test_flat=test_flat,
        full_kelly=full_kelly, train_eval=train_eval, test_eval=test_eval,
        h_in_sample=h_in_sample, h_train=h_train, h_test=h_test,
        train_stats=train_stats, train_edges=train_edges, train_model=train_model,
        prod_sigs_pre=prod_sigs_pre, prod_sigs_post=prod_sigs_post,
    )
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[oos_audit] -> {OUT_PATH}  ({len(md.splitlines())} lines)")


if __name__ == "__main__":
    main()

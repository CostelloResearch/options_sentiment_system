# =============================================================================
# scripts/r3_baseline.py -- R3 production baseline confirmation
#
# PURPOSE
# -------
# Re-run the Kelly backtest under R3 production defaults (QUINTILE sizing,
# no strategy buckets, global 6% cap) and confirm the numbers match the
# three-regime study (R3: +$12,604 / Sharpe 0.4578).  This is the post-
# adoption validation step: if the numbers drift, the productionisation
# broke something.
#
# What R3 production means in code:
#   position_sizer.USE_STRATEGY_BUCKETS = False
#   position_sizer.QUINTILE_FRAC         = {Q1:0.1%, Q2:0.2%, Q3:0.3%,
#                                           Q4:0.5%, Q5:0.8%}
#   Global portfolio cap stays at 6% (MAX_PORTFOLIO_RISK).
#   Quintile edges read from data/raw/quintile_edges.json.
#
# USAGE
# -----
#   python scripts/r3_baseline.py                 # full rerun
#   python scripts/r3_baseline.py --skip-run      # re-report off existing logs
# =============================================================================

from __future__ import annotations

import os
import sys
import time
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from backtest import engine
from signals import position_sizer


OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "outputs"))
RAW_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))

# =============================================================================
# Pinned production baseline -- synthetic-sentiment 10-ticker baseline
# as of 2026-04-25.  Drift against these numbers means either the flat
# corpus has shifted (synthetic date window is anchored to today()), the
# confidence model has been refit, or position_sizer has changed.
#
# These numbers are expected to change once real-mode runs on accumulated
# live news.  Update the pins (and the "as of" date below) the first time
# the real-data run produces a stable baseline.
#
# Old 5-ticker pins archived in comments below the active set so we have
# provenance.
# =============================================================================

# --- R3 production (quintile sizing, global 6% cap, refit v1 logistic) ---
R3_STUDY_TOTAL_PNL     = 6775.0
R3_STUDY_SHARPE        = 0.41
R3_STUDY_MAX_DD        = 6244.0   # absolute magnitude (the run reports negative)
R3_STUDY_PROFIT_FACTOR = 1.27
R3_STUDY_N_TRADES      = 357      # actually-traded (BUY CALLS only; BUY PUTS
                                  # negative-Kelly-filtered to zero-contract)

# --- Flat baseline (1 contract floor, no Kelly) ---
FLAT_TOTAL_PNL     = 17913.0
FLAT_SHARPE        = 0.42
FLAT_MAX_DD        = 21692.0      # absolute magnitude
FLAT_PROFIT_FACTOR = 1.23
FLAT_N_TRADES      = 613

# Drift tolerances.  Pins are rounded; allow ~$1 / 1bp / 1bp / single trade.
_TOL_PNL    = 1.0
_TOL_SHARPE = 0.01
_TOL_DD     = 1.0
_TOL_PF     = 0.01
_TOL_TRADES = 1

# --- Archived 5-ticker baselines (deprecated 2026-04-25 universe rebuild) ---
# Kept as comments for provenance.  Two prior pins existed:
#
# Session-1 R3 study (original):
#     R3_STUDY_TOTAL_PNL = 12604
#     R3_STUDY_SHARPE    = 0.4578
#     R3_STUDY_N_TRADES  = 358
#
# Refit-logistic update (2026-04-24, still 5-ticker universe):
#     R3_STUDY_TOTAL_PNL = 14872.48
#     R3_STUDY_SHARPE    = 0.5415
#     R3_STUDY_N_TRADES  = 358
#
# 5-ticker flat baseline:
#     FLAT_TOTAL_PNL     = 33192
#     FLAT_SHARPE        = 1.06
#     FLAT_PROFIT_FACTOR = 1.65
#     FLAT_N_TRADES      = 417


# ---------------------------------------------------------------------------
# yfinance retry wrapper (rate-limit friendly)
# ---------------------------------------------------------------------------

_ORIG_LOAD_PRICE = engine.load_price_history

def _load_price_retry(ticker, period="2y"):
    last_err = None
    for attempt in range(4):
        try:
            return _ORIG_LOAD_PRICE(ticker, period=period)
        except ValueError as e:
            last_err = e
            print(f"[r3_baseline] yfinance retry {attempt+1}/4 for {ticker}: {e}")
            time.sleep(2 + attempt * 3)
    raise last_err


# ---------------------------------------------------------------------------
# Log loaders + metrics (mirrors regime_comparison.py)
# ---------------------------------------------------------------------------

def _load_logs(tickers, suffix, demo=True):
    """Load per-ticker backtest logs.  Real-mode files live at
    `backtest_{T}{suffix}.csv` (no `_demo` infix); synthetic-mode files
    live at `backtest_{T}_demo{suffix}.csv`.  The engine writes the
    correct flavour based on `demo_mode`; this loader must mirror that
    branching, otherwise the headline aggregation reports stale demo
    numbers under `--real`."""
    infix = "_demo" if demo else ""
    frames = []
    for t in tickers:
        p = os.path.join(RAW_DIR, f"backtest_{t}{infix}{suffix}.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _pnl_series(df):
    if "pnl_total" in df.columns and df["pnl_total"].notna().any():
        return df["pnl_total"].fillna(0.0)
    return df["pnl"].fillna(0.0) * 100.0


def _taken_mask(df):
    acc = df.get("accepted", False).astype(bool)
    kr  = df.get("kelly_reason", pd.Series([""] * len(df))).astype(str).fillna("")
    # `negative_kelly_<signal>` rows are recorded with accepted=True but
    # contracts=0 / pnl=0 -- they are NOT actually-traded.  Without this
    # exclusion the n_trades count balloons by every BUY PUTS signal in
    # the 10-ticker era (where BUY PUTS Kelly_f went negative).  Match
    # segregated_kelly_report._per_strategy_trade_counts behaviour.
    not_taken = kr.isin(["rejected_by_kelly", "bucket_full",
                         "portfolio_risk_cap", "rejected_risk_reward"]) \
                | kr.str.startswith("negative_kelly_")
    return acc & (~not_taken)


def headline(df, label):
    if df.empty:
        return {"regime": label}
    pnl = _pnl_series(df)
    cum = pnl.cumsum()
    dd  = float((cum - cum.cummax()).min())
    std = float(pnl.std(ddof=1)) if len(pnl) > 1 else 0.0
    sh  = (float(pnl.mean()) / std * np.sqrt(252.0 / 5.0)) if std > 0 else 0.0
    pos = float(pnl[pnl > 0].sum())
    neg = float(abs(pnl[pnl < 0].sum()))
    pf  = (pos / neg) if neg > 0 else float("inf")
    return {
        "regime":        label,
        "n_signals":     int(len(df)),
        "n_trades":      int(_taken_mask(df).sum()),
        "total_pnl":     round(float(pnl.sum()), 2),
        "sharpe":        round(float(sh), 4),
        "max_dd":        round(float(dd), 2),
        "profit_factor": round(float(pf), 4) if pf != float("inf") else float("inf"),
        "win_rate":      round(float((pnl > 0).mean()), 4),
    }


def buy_puts_util(df):
    if df.empty or "bucket_cap_dollars" not in df.columns:
        return {}
    bp = df[(df["signal"] == "BUY PUTS") & (df["bucket_cap_dollars"] > 0)].copy()
    if bp.empty:
        return {"n_evaluations": 0}
    bp["utilization"] = bp["bucket_used_before"] / bp["bucket_cap_dollars"]
    kr = bp.get("kelly_reason", pd.Series([""] * len(bp))).astype(str).fillna("")
    blocked = kr.isin(["bucket_full", "portfolio_risk_cap"])
    return {
        "cap_$":            round(float(bp["bucket_cap_dollars"].iloc[0]), 2),
        "n_evaluations":    int(len(bp)),
        "mean_utilization": round(float(bp["utilization"].mean()), 4),
        "peak_utilization": round(float(bp["utilization"].max()),  4),
        "n_blocked":        int(blocked.sum()),
        "pct_blocked":      round(float(blocked.mean()), 4),
    }


def quintile_table(df, edges):
    if df.empty or "confidence" not in df.columns:
        return pd.DataFrame()
    taken = df[_taken_mask(df)].copy()
    if taken.empty:
        return pd.DataFrame()
    bins   = [-np.inf] + list(edges) + [np.inf]
    labels = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    taken["q"] = pd.cut(taken["confidence"], bins=bins, labels=labels,
                        include_lowest=True)
    pnl_col = "pnl_total" if "pnl_total" in taken.columns else "pnl"
    if pnl_col == "pnl":
        taken["pnl_total"] = taken["pnl"].fillna(0.0) * 100.0
        pnl_col = "pnl_total"
    rows = []
    for q, grp in taken.groupby("q", observed=True):
        rows.append({
            "quintile":  str(q),
            "n":         int(len(grp)),
            "mean_conf": round(float(grp["confidence"].mean()), 4),
            "win_rate":  round(float((grp[pnl_col] > 0).mean()), 4),
            "avg_pnl":   round(float(grp[pnl_col].mean()), 2),
            "total_pnl": round(float(grp[pnl_col].sum()), 2),
        })
    return pd.DataFrame(rows).sort_values("quintile")


def trades_per_strategy(df):
    if df.empty:
        return pd.Series(dtype=int)
    return df.loc[_taken_mask(df), "signal"].value_counts()


def _df_to_md(df):
    if df.empty:
        return "_(empty)_\n"
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
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
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def main(tickers, lookback_days=500, demo=True, skip_run=False):
    os.makedirs(OUT_DIR, exist_ok=True)

    # Sanity-check production defaults before we run
    if position_sizer.USE_STRATEGY_BUCKETS:
        raise RuntimeError(
            "USE_STRATEGY_BUCKETS is True -- production is supposed to be R3 "
            "(quintile, no buckets).  Fix position_sizer.py before running."
        )
    print(f"[r3_baseline] USE_STRATEGY_BUCKETS = "
          f"{position_sizer.USE_STRATEGY_BUCKETS}")
    print(f"[r3_baseline] QUINTILE_FRAC = {position_sizer.QUINTILE_FRAC}")

    # Plug in retry wrapper for yfinance (rate-limit safety)
    engine.load_price_history = _load_price_retry

    # --- 1. Flat corpus (required) ---
    flat = _load_logs(tickers, suffix="", demo=demo)
    if flat.empty:
        mode_hint = "demo" if demo else "real"
        print(f"[r3_baseline] No {mode_hint}-mode flat corpus on disk; run "
              "segregated_kelly_report.py first (or scripts/r3_baseline.py "
              "without --skip-run to regenerate).")
        return
    print(f"[r3_baseline] Flat corpus ({'demo' if demo else 'real'}): "
          f"{len(flat)} rows across {len(tickers)} tickers.")

    # --- 2. Rebuild Kelly stats + quintile edges from flat corpus ---
    stats = position_sizer.compute_kelly_stats(flat)
    position_sizer.save_stats(stats)
    position_sizer.print_stats(stats)
    edges = position_sizer.compute_and_save_quintile_edges(flat)
    print(f"[r3_baseline] Quintile edges: {[round(e, 4) for e in edges]}")

    # --- 3. Run Kelly backtest per ticker (production regime = R3) ---
    if not skip_run:
        print("\n" + "=" * 72)
        print("R3 Kelly backtest (quintile sizing, global 6% cap)")
        print("=" * 72)
        for t in tickers:
            engine.run_backtest(t, demo_mode=demo, lookback_days=lookback_days,
                                use_kelly_sizing=True, output_suffix="_kelly")

    kelly = _load_logs(tickers, suffix="_kelly", demo=demo)
    if kelly.empty:
        mode_hint = "demo" if demo else "real"
        print(f"[r3_baseline] No {mode_hint}-mode Kelly logs produced; aborting.")
        return

    # --- 4. Metrics ---
    heads = pd.DataFrame([
        headline(flat,  "flat (baseline)"),
        headline(kelly, "R3 production (quintile, no buckets)"),
    ])
    print("\n[headline]")
    print(heads.to_string(index=False))

    util = buy_puts_util(kelly)
    print("\n[BUY PUTS cap utilization]")
    print(util)

    q = quintile_table(kelly, edges)
    print("\n[Confidence quintile P&L -- R3 production]")
    print(q.to_string(index=False))

    counts_flat = trades_per_strategy(flat).rename("flat")
    counts_r3   = trades_per_strategy(kelly).rename("R3")
    counts_df   = pd.concat([counts_flat, counts_r3], axis=1).fillna(0).astype(int)
    print("\n[Trade counts per strategy]")
    print(counts_df)

    # --- 5. Drift check against pinned baselines ---
    r3   = heads[heads["regime"].str.startswith("R3")].iloc[0]
    flat = heads[heads["regime"].str.startswith("flat")].iloc[0]

    # R3 drifts (sign convention: max_dd compared as absolute magnitude)
    r3_drifts = {
        "total_pnl":     (r3["total_pnl"],         R3_STUDY_TOTAL_PNL,     _TOL_PNL),
        "sharpe":        (r3["sharpe"],            R3_STUDY_SHARPE,        _TOL_SHARPE),
        "max_dd":        (abs(r3["max_dd"]),       R3_STUDY_MAX_DD,        _TOL_DD),
        "profit_factor": (r3["profit_factor"],     R3_STUDY_PROFIT_FACTOR, _TOL_PF),
        "n_trades":      (r3["n_trades"],          R3_STUDY_N_TRADES,      _TOL_TRADES),
    }
    flat_drifts = {
        "total_pnl":     (flat["total_pnl"],       FLAT_TOTAL_PNL,     _TOL_PNL),
        "sharpe":        (flat["sharpe"],          FLAT_SHARPE,        _TOL_SHARPE),
        "max_dd":        (abs(flat["max_dd"]),     FLAT_MAX_DD,        _TOL_DD),
        "profit_factor": (flat["profit_factor"],   FLAT_PROFIT_FACTOR, _TOL_PF),
        "n_trades":      (flat["n_trades"],        FLAT_N_TRADES,      _TOL_TRADES),
    }

    def _check(drifts):
        ok = True
        for k, (prod, pin, tol) in drifts.items():
            if abs(float(prod) - float(pin)) >= tol:
                ok = False
                break
        return ok

    r3_match   = _check(r3_drifts)
    flat_match = _check(flat_drifts)
    match      = r3_match and flat_match

    print("\n" + "=" * 72)
    print("STUDY DRIFT CHECK -- R3 production")
    print("=" * 72)
    for k, (prod, pin, tol) in r3_drifts.items():
        d = float(prod) - float(pin)
        flag = "  ok" if abs(d) < tol else "DRIFT"
        print(f"  {k:<14s}: production {float(prod):+,.4f}  "
              f"pin {float(pin):+,.4f}  drift {d:+,.4f}  [{flag}]")
    print(f"  verdict       : {'MATCH' if r3_match else 'DRIFT'}")

    print("\n" + "=" * 72)
    print("STUDY DRIFT CHECK -- flat baseline")
    print("=" * 72)
    for k, (prod, pin, tol) in flat_drifts.items():
        d = float(prod) - float(pin)
        flag = "  ok" if abs(d) < tol else "DRIFT"
        print(f"  {k:<14s}: production {float(prod):+,.4f}  "
              f"pin {float(pin):+,.4f}  drift {d:+,.4f}  [{flag}]")
    print(f"  verdict       : {'MATCH' if flat_match else 'DRIFT'}")

    # Backwards-compatible scalar drifts so the existing markdown writer
    # (which references pnl_drift / sharpe_drift / trades_drift) keeps
    # working without restructuring its table generation.
    pnl_drift    = r3_drifts["total_pnl"][0]    - r3_drifts["total_pnl"][1]
    sharpe_drift = r3_drifts["sharpe"][0]       - r3_drifts["sharpe"][1]
    trades_drift = int(r3_drifts["n_trades"][0] - r3_drifts["n_trades"][1])

    # --- 6. Markdown baseline ---
    md = os.path.join(OUT_DIR, "r3_production_baseline.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# R3 Production Baseline\n\n")
        f.write("_Post-adoption confirmation: the QUINTILE sizing regime "
                "selected in `outputs/regime_comparison.md` is now the "
                "production default in `position_sizer.py` "
                "(`USE_STRATEGY_BUCKETS = False`).  This document locks "
                "in the numbers produced by the productionised code so "
                "any future drift is detectable._\n\n")

        f.write("## 1. Production configuration\n\n")
        f.write(f"- `USE_STRATEGY_BUCKETS` = `{position_sizer.USE_STRATEGY_BUCKETS}`\n")
        f.write(f"- `QUINTILE_FRAC` = `{position_sizer.QUINTILE_FRAC}`\n")
        f.write(f"- Global cap: `MAX_PORTFOLIO_RISK` = "
                f"{position_sizer.MAX_PORTFOLIO_RISK*100:.1f}%\n")
        f.write(f"- Per-trade cap: `MAX_RISK_PER_TRADE` = "
                f"{position_sizer.MAX_RISK_PER_TRADE*100:.1f}%\n")
        f.write(f"- Quintile edges (from flat corpus): "
                f"`{[round(e, 4) for e in edges]}`\n")
        f.write(f"- Paper-account notional (Kelly path): "
                f"${engine.KELLY_BACKTEST_NOTIONAL:,.0f}\n\n")

        f.write("## 2. Headline metrics\n\n")
        f.write(_df_to_md(heads))
        f.write("\n")

        f.write("## 3. BUY PUTS cap utilization + block rate\n\n")
        f.write("_Under R3 the `cap` is the global 6% portfolio cap "
                "(no per-strategy buckets)._\n\n")
        if util:
            util_df = pd.DataFrame([{"metric": k, "value": v}
                                    for k, v in util.items()])
            f.write(_df_to_md(util_df))
        else:
            f.write("_(no BUY PUTS signals in log)_\n")
        f.write("\n")

        f.write("## 4. Confidence quintile P&L\n\n")
        f.write(_df_to_md(q))
        f.write("\n")

        f.write("## 5. Trade counts per strategy\n\n")
        f.write(_df_to_md(counts_df.reset_index().rename(columns={"index": "signal"})))
        f.write("\n")

        f.write("## 6. Drift check vs regime_comparison study\n\n")
        drift_df = pd.DataFrame([
            {"metric": "total_pnl", "production": r3["total_pnl"],
             "study": R3_STUDY_TOTAL_PNL, "drift": pnl_drift},
            {"metric": "sharpe",    "production": r3["sharpe"],
             "study": R3_STUDY_SHARPE,    "drift": sharpe_drift},
            {"metric": "n_trades",  "production": r3["n_trades"],
             "study": R3_STUDY_N_TRADES,  "drift": trades_drift},
        ])
        f.write(_df_to_md(drift_df))
        f.write(f"\n**Verdict:** `{'MATCH' if match else 'DRIFT'}`\n")
        if not match:
            f.write("\nIf verdict is DRIFT, investigate what changed in "
                    "`position_sizer.size_trade`, `backtest/engine.py`, "
                    "or the logistic confidence model.  The R3 study "
                    "numbers are pinned in this script "
                    "(R3_STUDY_TOTAL_PNL / R3_STUDY_SHARPE / "
                    "R3_STUDY_N_TRADES) so any legitimate change in "
                    "production should update those constants alongside.\n")

    print(f"\n[r3_baseline] -> {md}")
    return {"headlines": heads, "util": util, "q": q, "counts": counts_df,
            "match": match, "md_path": md}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=config.TICKERS)
    ap.add_argument("--lookback-days", type=int, default=500)
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--skip-run", action="store_true",
                    help="Reuse existing _kelly logs, rebuild the report only.")
    args = ap.parse_args()

    main(
        tickers       = args.tickers,
        lookback_days = args.lookback_days,
        demo          = not args.real,
        skip_run      = args.skip_run,
    )

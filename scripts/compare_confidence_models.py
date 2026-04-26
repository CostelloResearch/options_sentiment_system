# =============================================================================
# scripts/compare_confidence_models.py -- Logistic vs Magnitude head-to-head
#
# PURPOSE
# -------
# The logistic confidence model (p(win)) and the magnitude model
# (expected pnl_pct) predict different quantities.  R3 proportional sizing
# is sensitive to the quantity that matches the loss function -- proportional
# bet size needs ranking by expected PnL magnitude, not win probability.
# This driver runs both models through the production R3 pipeline and
# declares a winner based on:
#
#   (a) Two holdout validations of the magnitude model:
#         time-based  (first 75% train / last 25% test)
#         ticker-based (leave-one-ticker-out, cycle through 5 tickers)
#       "Wins" means Q5 has the highest mean pnl_pct on the held-out fold.
#   (b) R3 backtest total P&L / Sharpe / profit factor.
#
# Promotion policy:
#   wins on BOTH holdouts  AND  beats logistic on R3 backtest  ->  promote
#   wins only some of the above -> keep logistic, flag findings
#   magnitude fails cleanly     -> fit interaction-term variant and retest
#
# PROMOTION MECHANICS
# -------------------
# "Promote" = rewire `backtest/engine.py` and `signals/signal_engine.py` to
# import from `confidence_model_magnitude` instead of `confidence_model`,
# OR save the magnitude coefficients into `confidence_model.json` (the name
# engine.py reads by default) with a compatible schema.  We take the second
# approach because it's reversible (keep a backup) and doesn't rename files.
# See the `promote_magnitude` function.
#
# USAGE
# -----
#   python scripts/compare_confidence_models.py
#   python scripts/compare_confidence_models.py --skip-backtest   # rpt-only
#   python scripts/compare_confidence_models.py --no-promote       # dry run
# =============================================================================

from __future__ import annotations

import os
import sys
import time
import shutil
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from backtest import engine
from signals import position_sizer
from signals import confidence_model          as cmodel_logistic
from signals import confidence_model_magnitude as cmodel_magnitude


OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "outputs"))
RAW_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))


# ---------------------------------------------------------------------------
# yfinance cache + retry (keep the 10-run loop tractable)
# ---------------------------------------------------------------------------

_PRICE_CACHE: dict = {}
_ORIG_LOAD_PRICE = engine.load_price_history

def _cached_load_price(ticker, period="2y"):
    key = (ticker, period)
    if key in _PRICE_CACHE:
        return _PRICE_CACHE[key].copy()
    last_err = None
    for attempt in range(4):
        try:
            df = _ORIG_LOAD_PRICE(ticker, period=period)
            _PRICE_CACHE[key] = df
            return df.copy()
        except ValueError as e:
            last_err = e
            print(f"[compare] yfinance retry {attempt+1}/4 for {ticker}: {e}")
            time.sleep(2 + attempt * 3)
    raise last_err


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_logs(tickers, suffix):
    frames = []
    for t in tickers:
        p = os.path.join(RAW_DIR, f"backtest_{t}_demo{suffix}.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


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
# Metric helpers (copy of r3_baseline's to stay stand-alone)
# ---------------------------------------------------------------------------

def _pnl_series(df):
    if "pnl_total" in df.columns and df["pnl_total"].notna().any():
        return df["pnl_total"].fillna(0.0)
    return df["pnl"].fillna(0.0) * 100.0


def _taken_mask(df):
    acc = df.get("accepted", False).astype(bool)
    kr  = df.get("kelly_reason", pd.Series([""] * len(df))).astype(str).fillna("")
    return acc & (~kr.isin(["rejected_by_kelly", "bucket_full",
                            "portfolio_risk_cap", "rejected_risk_reward"]))


def headline(df, label):
    if df.empty:
        return {"model": label}
    pnl = _pnl_series(df)
    cum = pnl.cumsum()
    dd  = float((cum - cum.cummax()).min())
    std = float(pnl.std(ddof=1)) if len(pnl) > 1 else 0.0
    sh  = (float(pnl.mean()) / std * np.sqrt(252.0 / 5.0)) if std > 0 else 0.0
    pos = float(pnl[pnl > 0].sum())
    neg = float(abs(pnl[pnl < 0].sum()))
    pf  = (pos / neg) if neg > 0 else float("inf")
    return {
        "model":         label,
        "n_signals":     int(len(df)),
        "n_trades":      int(_taken_mask(df).sum()),
        "total_pnl":     round(float(pnl.sum()), 2),
        "sharpe":        round(float(sh), 4),
        "max_dd":        round(float(dd), 2),
        "profit_factor": round(float(pf), 4) if pf != float("inf") else float("inf"),
        "win_rate":      round(float((pnl > 0).mean()), 4),
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


# ---------------------------------------------------------------------------
# Holdout validation (magnitude model only)
# ---------------------------------------------------------------------------

def _mag_fit(train_df, include_interactions=False):
    """Fit magnitude model without saving to disk."""
    return cmodel_magnitude.fit_from_trade_log(
        train_df, save=False, include_interactions=include_interactions,
    )


def _fold_metrics(train_df, test_df, include_interactions=False):
    """
    Fit on train, evaluate on test.  Returns RMSE, quintile table on test,
    and a flag for whether Q5 is the highest-mean-pnl quintile.
    """
    if "accepted" in train_df.columns:
        train_df = train_df[train_df["accepted"].astype(bool)]
    if "accepted" in test_df.columns:
        test_df = test_df[test_df["accepted"].astype(bool)]
    if train_df.empty or test_df.empty:
        return None

    model = _mag_fit(train_df, include_interactions=include_interactions)
    X_test = cmodel_magnitude.build_feature_matrix(
        test_df, include_interactions=include_interactions
    )
    raw_test  = cmodel_magnitude.predict_raw_batch(model, X_test)
    norm_test = cmodel_magnitude.predict_proba_batch(model, X_test)
    y_test = test_df["pnl_pct"].astype(float).values

    rmse = float(np.sqrt(np.mean((y_test - raw_test) ** 2)))

    # Quintile split on normalised test predictions.  Use TRAIN-DERIVED
    # norm_anchor_x so the quintile boundaries are leak-free -- but we still
    # qcut the test normalised scores so folds with few Q5 points don't
    # explode.  In practice qcut on ~100 holdout points is stable.
    test_eval = test_df.copy()
    test_eval["norm_conf"] = norm_test
    try:
        test_eval["q"] = pd.qcut(
            test_eval["norm_conf"], 5,
            labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
            duplicates="drop",
        )
    except Exception:
        return None

    agg = test_eval.groupby("q", observed=True).agg(
        n        = ("norm_conf", "size"),
        mean_p   = ("norm_conf", "mean"),
        mean_ret = ("pnl_pct", "mean"),
        win_rate = ("pnl_pct", lambda s: float((s > 0).mean())),
    ).reset_index().rename(columns={"q": "quintile"})

    # Q5 highest?  Compare mean_ret across the 5 bins (ties broken by label).
    if agg.empty:
        return {"rmse": rmse, "agg": agg, "q5_highest": False}
    best_q = str(agg.sort_values("mean_ret", ascending=False).iloc[0]["quintile"])
    q5_highest = (best_q == "Q5")
    # Q1 vs Q5 P&L gap (per-trade pct)
    try:
        q1_ret = float(agg[agg["quintile"].astype(str) == "Q1"]["mean_ret"].iloc[0])
    except IndexError:
        q1_ret = float("nan")
    try:
        q5_ret = float(agg[agg["quintile"].astype(str) == "Q5"]["mean_ret"].iloc[0])
    except IndexError:
        q5_ret = float("nan")
    return {
        "rmse":          rmse,
        "q5_highest":    q5_highest,
        "best_quintile": best_q,
        "q1_mean_ret":   q1_ret,
        "q5_mean_ret":   q5_ret,
        "q5_minus_q1":   q5_ret - q1_ret,
        "agg":           agg,
        "n_train":       int(len(train_df)),
        "n_test":        int(len(test_df)),
    }


def holdout_time(flat, split_frac=0.75, include_interactions=False):
    """Chronological split: first 75% train, last 25% test."""
    df = flat.sort_values("entry_date").reset_index(drop=True)
    if "accepted" in df.columns:
        df = df[df["accepted"].astype(bool)].reset_index(drop=True)
    n = len(df)
    if n < 40:
        return None
    cut = int(round(split_frac * n))
    train, test = df.iloc[:cut], df.iloc[cut:]
    r = _fold_metrics(train, test, include_interactions=include_interactions)
    if r is not None:
        r["label"] = f"time_{int(split_frac*100)}_{100-int(split_frac*100)}"
    return r


def holdout_ticker(flat, include_interactions=False):
    """
    Leave-one-ticker-out across the 5 tickers.  Per fold we predict on the
    held-out ticker and aggregate predictions across folds for a single
    "out-of-sample" table.
    """
    df = flat.copy()
    if "accepted" in df.columns:
        df = df[df["accepted"].astype(bool)].reset_index(drop=True)
    tickers = sorted(df["ticker"].unique())
    if len(tickers) < 2:
        return None

    oos_rows = []
    fold_rmse = []
    for held_out in tickers:
        train = df[df["ticker"] != held_out]
        test  = df[df["ticker"] == held_out]
        if len(train) < 10 or len(test) < 5:
            continue
        model = _mag_fit(train, include_interactions=include_interactions)
        X = cmodel_magnitude.build_feature_matrix(
            test, include_interactions=include_interactions
        )
        raw  = cmodel_magnitude.predict_raw_batch(model, X)
        norm = cmodel_magnitude.predict_proba_batch(model, X)
        y    = test["pnl_pct"].astype(float).values
        fold_rmse.append(float(np.sqrt(np.mean((y - raw) ** 2))))
        t_rows = test.copy()
        t_rows["raw_pred"]  = raw
        t_rows["norm_conf"] = norm
        t_rows["held_out_ticker"] = held_out
        oos_rows.append(t_rows)

    if not oos_rows:
        return None
    oos = pd.concat(oos_rows, ignore_index=True)

    try:
        oos["q"] = pd.qcut(oos["norm_conf"], 5,
                           labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
                           duplicates="drop")
    except Exception:
        return None

    agg = oos.groupby("q", observed=True).agg(
        n        = ("norm_conf", "size"),
        mean_p   = ("norm_conf", "mean"),
        mean_ret = ("pnl_pct", "mean"),
        win_rate = ("pnl_pct", lambda s: float((s > 0).mean())),
    ).reset_index().rename(columns={"q": "quintile"})
    best_q = str(agg.sort_values("mean_ret", ascending=False).iloc[0]["quintile"])
    q5_highest = (best_q == "Q5")
    try:
        q1_ret = float(agg[agg["quintile"].astype(str) == "Q1"]["mean_ret"].iloc[0])
        q5_ret = float(agg[agg["quintile"].astype(str) == "Q5"]["mean_ret"].iloc[0])
    except Exception:
        q1_ret = float("nan"); q5_ret = float("nan")
    return {
        "label":         "ticker_LOO",
        "rmse":          float(np.mean(fold_rmse)) if fold_rmse else float("nan"),
        "rmse_per_fold": {t: r for t, r in zip(tickers, fold_rmse)},
        "q5_highest":    q5_highest,
        "best_quintile": best_q,
        "q1_mean_ret":   q1_ret,
        "q5_mean_ret":   q5_ret,
        "q5_minus_q1":   q5_ret - q1_ret,
        "agg":           agg,
        "n_oos":         int(len(oos)),
    }


# ---------------------------------------------------------------------------
# R3 backtest A/B: run each model through the engine's full Kelly path
# ---------------------------------------------------------------------------

def _refresh_edges_for_model(flat_df, cmod_mod, cmod):
    """
    Compute and save quintile edges by re-scoring the ACCEPTED rows of the
    flat corpus with the given model.  This ensures the R3 sizer's edges
    match the distribution of confidence scores the Kelly pass will see.
    """
    df = flat_df[flat_df["accepted"].astype(bool)].copy()
    X  = cmod_mod.build_feature_matrix(df, **(
        {"include_interactions": cmod.get("use_interactions", False)}
        if cmod_mod is cmodel_magnitude else {}
    ))
    preds = cmod_mod.predict_proba_batch(cmod, X)
    _, cuts = pd.qcut(preds, 5, retbins=True, duplicates="drop")
    edges = [float(x) for x in cuts[1:-1]]
    position_sizer.save_quintile_edges(edges)
    return edges


def run_r3_with(cmod_mod, cmod, tickers, suffix, demo=True, lookback_days=500):
    """Run R3 Kelly backtest under the given confidence model."""
    _orig_cmodel    = engine._cmodel
    _orig_load_model = None  # only used when logistic model already on disk

    # Swap the engine's cmodel reference + persist the model to disk so
    # engine.load_model() re-reads the right file.  We then restore both.
    engine._cmodel = cmod_mod

    # If we're running the magnitude model, engine.run_backtest calls
    # cmod_mod.load_model() -- it looks for magnitude_model.json.  We need
    # to ensure that file reflects `cmod`.  For the logistic path the
    # engine reads confidence_model.json.  We save cmod to the right file
    # before each run.
    if cmod_mod is cmodel_magnitude:
        cmodel_magnitude.save_model(cmod)
    else:
        cmodel_logistic.save_model(cmod)

    try:
        for t in tickers:
            engine.run_backtest(t, demo_mode=demo, lookback_days=lookback_days,
                                use_kelly_sizing=True, output_suffix=suffix)
    finally:
        engine._cmodel = _orig_cmodel


# ---------------------------------------------------------------------------
# Disagreement analysis
# ---------------------------------------------------------------------------

def disagreement_table(flat, logistic_model, magnitude_model, top_k=10):
    """
    Score every accepted trade with both models, rank by each, and surface
    the largest rank disagreements -- the signals most affected by a model
    swap.
    """
    df = flat[flat["accepted"].astype(bool)].copy().reset_index(drop=True)
    X_log = cmodel_logistic.build_feature_matrix(df)
    X_mag = cmodel_magnitude.build_feature_matrix(
        df,
        include_interactions=magnitude_model.get("use_interactions", False),
    )
    p_log = cmodel_logistic.predict_proba_batch(logistic_model, X_log)
    p_mag = cmodel_magnitude.predict_proba_batch(magnitude_model, X_mag)
    df["conf_logistic"]  = p_log
    df["conf_magnitude"] = p_mag
    df["rank_logistic"]  = df["conf_logistic"].rank(pct=True)
    df["rank_magnitude"] = df["conf_magnitude"].rank(pct=True)
    df["rank_diff"]      = df["rank_magnitude"] - df["rank_logistic"]
    df["abs_rank_diff"]  = df["rank_diff"].abs()

    top = df.sort_values("abs_rank_diff", ascending=False).head(top_k)
    cols = ["ticker", "entry_date", "signal", "sentiment_score", "iv_rank",
            "pnl_pct", "conf_logistic", "conf_magnitude", "rank_diff"]
    cols = [c for c in cols if c in top.columns]
    return top[cols].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------

def promote_magnitude(magnitude_model: dict) -> dict:
    """
    Make the magnitude model the production confidence provider.

    Mechanic: we don't rename files.  Instead, we overwrite
    `data/raw/confidence_model.json` with a pointer payload that tells
    engine._cmodel.load_model to defer to the magnitude path -- but
    engine.py imports confidence_model (logistic) directly, so the
    cleanest swap is changing the import.

    We do it by:
      1. Backing up the old confidence_model.json + the import line.
      2. Editing engine.py and signal_engine.py to import
         `confidence_model_magnitude as _cmodel` instead.

    Reversible via `demote_magnitude()` (uses the saved backup).

    Returns a dict describing the promotion (paths changed, backup loc).
    """
    promoted = {"changed": [], "backups": {}}
    backup_dir = os.path.join(RAW_DIR, "model_backup")
    os.makedirs(backup_dir, exist_ok=True)

    logistic_json = cmodel_logistic.model_path()
    if os.path.exists(logistic_json):
        bak = os.path.join(backup_dir, "confidence_model.logistic.json")
        shutil.copy2(logistic_json, bak)
        promoted["backups"]["logistic_json"] = bak

    # Source-file edits: both engine.py and signal_engine.py import the
    # logistic module as _cmodel / confidence_model.  We rewrite just those
    # import lines -- minimal, targeted, reversible.
    edits = [
        (os.path.normpath(os.path.join(os.path.dirname(__file__), "..",
                                       "backtest", "engine.py")),
         "from signals import confidence_model as _cmodel",
         "from signals import confidence_model_magnitude as _cmodel  "
         "# promoted 2026-04-24"),
        (os.path.normpath(os.path.join(os.path.dirname(__file__), "..",
                                       "signals", "signal_engine.py")),
         "from signals import confidence_model",
         "from signals import confidence_model_magnitude as confidence_model  "
         "# promoted 2026-04-24"),
    ]
    for path, old, new in edits:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        if old in src and new not in src:
            # Back up first
            bak_name = os.path.basename(path) + ".pre_promotion.bak"
            bak = os.path.join(backup_dir, bak_name)
            with open(bak, "w", encoding="utf-8") as f:
                f.write(src)
            promoted["backups"][os.path.basename(path)] = bak
            src2 = src.replace(old, new)
            with open(path, "w", encoding="utf-8") as f:
                f.write(src2)
            promoted["changed"].append(path)
    return promoted


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

def main(tickers, lookback_days=500, demo=True,
         skip_backtest=False, allow_promote=True):
    os.makedirs(OUT_DIR, exist_ok=True)
    engine.load_price_history = _cached_load_price  # yfinance cache

    # --- 1. Load flat corpus ---
    flat = _load_logs(tickers, suffix="")
    if flat.empty:
        print("[compare] No flat corpus on disk; run r3_baseline.py first.")
        return None
    print(f"[compare] Flat corpus: {len(flat)} rows, "
          f"{int(flat['accepted'].sum())} accepted.")

    # --- 2. Fit both models on full corpus ---
    print("\n" + "=" * 72); print("Fit LOGISTIC on full corpus"); print("=" * 72)
    logistic_model = cmodel_logistic.fit_from_trade_log(flat, save=True)
    print(cmodel_logistic.summarise(logistic_model))

    print("\n" + "=" * 72); print("Fit MAGNITUDE on full corpus (6 features)"); print("=" * 72)
    magnitude_model = cmodel_magnitude.fit_from_trade_log(
        flat, save=True, include_interactions=False)
    print(cmodel_magnitude.summarise(magnitude_model))

    # --- 3. Holdout validation of magnitude model ---
    print("\n" + "=" * 72)
    print("Holdout validation: MAGNITUDE (6 features)")
    print("=" * 72)
    holdouts = {"6-feature": {}}
    ht = holdout_time(flat, split_frac=0.75); holdouts["6-feature"]["time"] = ht
    hk = holdout_ticker(flat);               holdouts["6-feature"]["ticker"] = hk
    for key, h in [("time", ht), ("ticker", hk)]:
        if h is None:
            print(f"  {key}: SKIPPED (insufficient data)")
            continue
        print(f"\n-- {h['label']} --")
        print(f"  n_train/test: {h.get('n_train', '-')}/{h.get('n_test', h.get('n_oos', '-'))}")
        print(f"  RMSE: {h['rmse']:.3f}")
        print(f"  Q1 mean_ret: {h['q1_mean_ret']:+.3f}  "
              f"Q5 mean_ret: {h['q5_mean_ret']:+.3f}  "
              f"Q5-Q1: {h['q5_minus_q1']:+.3f}")
        print(f"  best quintile: {h['best_quintile']}  "
              f"Q5 highest? {h['q5_highest']}")
        print(h["agg"].to_string(index=False))

    q5_wins_6ft = (
        holdouts["6-feature"]["time"] is not None
        and holdouts["6-feature"]["ticker"] is not None
        and holdouts["6-feature"]["time"]["q5_highest"]
        and holdouts["6-feature"]["ticker"]["q5_highest"]
    )

    # --- 3b. If 6-feature magnitude lost Q5, fit interaction variant ---
    magnitude_model_interactions = None
    if not q5_wins_6ft:
        print("\n" + "=" * 72)
        print("6-feature magnitude did not clear both holdouts; "
              "fitting interaction variant")
        print("=" * 72)
        magnitude_model_interactions = cmodel_magnitude.fit_from_trade_log(
            flat, save=False, include_interactions=True)
        print(cmodel_magnitude.summarise(magnitude_model_interactions))
        holdouts["8-feature"] = {}
        ht2 = holdout_time(flat, split_frac=0.75, include_interactions=True)
        hk2 = holdout_ticker(flat, include_interactions=True)
        holdouts["8-feature"]["time"]   = ht2
        holdouts["8-feature"]["ticker"] = hk2
        for key, h in [("time", ht2), ("ticker", hk2)]:
            if h is None:
                print(f"  {key}: SKIPPED"); continue
            print(f"\n-- {h['label']} (with interactions) --")
            print(f"  RMSE: {h['rmse']:.3f}  Q1: {h['q1_mean_ret']:+.3f}  "
                  f"Q5: {h['q5_mean_ret']:+.3f}  Q5-Q1: {h['q5_minus_q1']:+.3f}  "
                  f"best={h['best_quintile']}  Q5 highest? {h['q5_highest']}")
            print(h["agg"].to_string(index=False))

    # Pick the "magnitude candidate" to carry into the R3 A/B:
    q5_wins_8ft = (
        magnitude_model_interactions is not None
        and holdouts.get("8-feature", {}).get("time") is not None
        and holdouts.get("8-feature", {}).get("ticker") is not None
        and holdouts["8-feature"]["time"]["q5_highest"]
        and holdouts["8-feature"]["ticker"]["q5_highest"]
    )
    if q5_wins_6ft:
        magnitude_candidate_model = magnitude_model
        magnitude_candidate_label = "magnitude (6 features)"
        magnitude_candidate_interactions = False
    elif q5_wins_8ft:
        magnitude_candidate_model = magnitude_model_interactions
        magnitude_candidate_label = "magnitude (8 features w/ interactions)"
        magnitude_candidate_interactions = True
    else:
        # Still run the 6-feature magnitude through the R3 A/B for record;
        # promotion is blocked by the holdout failure.
        magnitude_candidate_model = magnitude_model
        magnitude_candidate_label = "magnitude (6 features) [FAILED holdouts]"
        magnitude_candidate_interactions = False

    # Ensure the disk file reflects the candidate model so engine loads match
    if magnitude_candidate_interactions:
        cmodel_magnitude.save_model(magnitude_candidate_model)

    # --- 4. R3 backtest A/B ---
    if not skip_backtest:
        print("\n" + "=" * 72)
        print("R3 backtest A/B: LOGISTIC vs " + magnitude_candidate_label)
        print("=" * 72)

        # LOGISTIC run
        print("\n[R3 run] logistic confidence")
        _refresh_edges_for_model(flat, cmodel_logistic, logistic_model)
        run_r3_with(cmodel_logistic, logistic_model, tickers,
                    suffix="_kelly_logistic", demo=demo,
                    lookback_days=lookback_days)

        # MAGNITUDE run
        print("\n[R3 run] magnitude confidence")
        _refresh_edges_for_model(flat, cmodel_magnitude, magnitude_candidate_model)
        run_r3_with(cmodel_magnitude, magnitude_candidate_model, tickers,
                    suffix="_kelly_magnitude", demo=demo,
                    lookback_days=lookback_days)

    kelly_log = _load_logs(tickers, "_kelly_logistic")
    kelly_mag = _load_logs(tickers, "_kelly_magnitude")

    # Flat headline for reference
    heads = pd.DataFrame([
        headline(flat,       "flat (1-contract baseline)"),
        headline(kelly_log,  "R3 x logistic"),
        headline(kelly_mag,  f"R3 x {magnitude_candidate_label}"),
    ])
    print("\n[headline A/B]")
    print(heads.to_string(index=False))

    # Rebuild each regime's edges (needed for quintile tables) from its
    # own Kelly log's confidence distribution.
    def _edges_from(df):
        if df.empty or "confidence" not in df.columns:
            return [0.2, 0.4, 0.6, 0.8]
        vals = df[df.get("accepted", False).astype(bool)]["confidence"].dropna()
        if vals.empty or vals.nunique() < 5:
            return [0.2, 0.4, 0.6, 0.8]
        _, cuts = pd.qcut(vals, 5, retbins=True, duplicates="drop")
        return [float(x) for x in cuts[1:-1]]
    edges_log = _edges_from(kelly_log)
    edges_mag = _edges_from(kelly_mag)
    q_log = quintile_table(kelly_log, edges_log)
    q_mag = quintile_table(kelly_mag, edges_mag)
    print("\n[Quintile P&L under LOGISTIC]");  print(q_log.to_string(index=False))
    print("\n[Quintile P&L under MAGNITUDE]"); print(q_mag.to_string(index=False))

    # --- 5. Disagreement ---
    disagree = disagreement_table(flat, logistic_model, magnitude_candidate_model)
    print("\n[Top-10 rank disagreements]")
    print(disagree.to_string(index=False))

    # --- 6. Decision ---
    log_h = heads.iloc[1]; mag_h = heads.iloc[2]
    r3_magnitude_wins = (mag_h["total_pnl"] > log_h["total_pnl"]
                         and mag_h["sharpe"] > log_h["sharpe"])
    # Q5 under R3 backtest (does magnitude fix the inversion?)
    def _q5_total(q_df):
        row = q_df[q_df["quintile"] == "Q5"]
        return float(row["total_pnl"].iloc[0]) if not row.empty else float("nan")
    q5_log = _q5_total(q_log); q5_mag = _q5_total(q_mag)
    q5_fixed_in_backtest = q5_mag > 0  # Q5 no longer net-negative

    promote_now = (q5_wins_6ft or q5_wins_8ft) and r3_magnitude_wins and allow_promote

    print("\n" + "=" * 72); print("VERDICT"); print("=" * 72)
    print(f"  6-feature magnitude clears both holdouts:  {q5_wins_6ft}")
    if magnitude_model_interactions is not None:
        print(f"  8-feature magnitude clears both holdouts:  {q5_wins_8ft}")
    print(f"  Magnitude beats logistic on R3 backtest:   {r3_magnitude_wins}")
    print(f"    logistic  total_pnl={log_h['total_pnl']:+,.2f}  "
          f"sharpe={log_h['sharpe']:+.4f}")
    print(f"    magnitude total_pnl={mag_h['total_pnl']:+,.2f}  "
          f"sharpe={mag_h['sharpe']:+.4f}")
    print(f"  Q5 flips positive under magnitude:         {q5_fixed_in_backtest}")
    print(f"    Q5 logistic = {q5_log:+,.2f}   Q5 magnitude = {q5_mag:+,.2f}")
    print(f"  Promote magnitude now?                     {promote_now}")

    promotion = None
    if promote_now:
        promotion = promote_magnitude(magnitude_candidate_model)
        print(f"\n[PROMOTED] magnitude is now the production confidence model.")
        print(f"           Backups at: {RAW_DIR}/model_backup/")
        print(f"           Edited files: {promotion['changed']}")

    # --- 7. Write report ---
    md_path = os.path.join(OUT_DIR, "confidence_model_comparison.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Confidence Model Comparison: Logistic vs Magnitude\n\n")
        f.write("## 1. Training summaries\n\n")
        f.write("### Logistic (p(win))\n```\n")
        f.write(cmodel_logistic.summarise(logistic_model)); f.write("\n```\n\n")
        f.write("### Magnitude (6 features)\n```\n")
        f.write(cmodel_magnitude.summarise(magnitude_model)); f.write("\n```\n\n")
        if magnitude_model_interactions is not None:
            f.write("### Magnitude (8 features with interactions)\n```\n")
            f.write(cmodel_magnitude.summarise(magnitude_model_interactions))
            f.write("\n```\n\n")

        f.write("## 2. Holdout validation (magnitude)\n\n")
        for cfg, hs in holdouts.items():
            f.write(f"### {cfg}\n\n")
            for key, h in hs.items():
                if h is None:
                    f.write(f"- **{key}**: skipped\n"); continue
                f.write(f"#### {h['label']}\n\n")
                f.write(f"- RMSE: **{h['rmse']:.3f}**\n")
                f.write(f"- Q1 mean_ret: {h['q1_mean_ret']:+.3f}  "
                        f"-- Q5 mean_ret: {h['q5_mean_ret']:+.3f}  "
                        f"-- Q5-Q1: **{h['q5_minus_q1']:+.3f}**\n")
                f.write(f"- Best quintile: **{h['best_quintile']}**  "
                        f"(Q5 highest? **{h['q5_highest']}**)\n\n")
                f.write(_df_to_md(h["agg"])); f.write("\n")
            f.write("\n")

        f.write("## 3. R3 backtest A/B\n\n")
        f.write(_df_to_md(heads)); f.write("\n")
        f.write("### Quintile P&L under LOGISTIC R3\n\n")
        f.write(_df_to_md(q_log)); f.write("\n")
        f.write(f"### Quintile P&L under MAGNITUDE R3 ({magnitude_candidate_label})\n\n")
        f.write(_df_to_md(q_mag)); f.write("\n")

        f.write("## 4. Ranking disagreements (top 10)\n\n")
        f.write("_Signals where the two models disagree most about ranking "
                "(percent-rank of confidence across the accepted-trade "
                "population).  Large disagreements are candidate false-"
                "positive filters._\n\n")
        f.write(_df_to_md(disagree)); f.write("\n")

        f.write("## 5. Verdict\n\n")
        f.write(f"- 6-feature magnitude clears both holdouts: "
                f"**{q5_wins_6ft}**\n")
        if magnitude_model_interactions is not None:
            f.write(f"- 8-feature magnitude clears both holdouts: "
                    f"**{q5_wins_8ft}**\n")
        f.write(f"- R3 backtest: magnitude beats logistic: "
                f"**{r3_magnitude_wins}** "
                f"(total_pnl {mag_h['total_pnl']:+,.2f} vs "
                f"{log_h['total_pnl']:+,.2f})\n")
        f.write(f"- Q5 flips positive under magnitude: "
                f"**{q5_fixed_in_backtest}** "
                f"(Q5 pnl magnitude={q5_mag:+,.2f} vs logistic={q5_log:+,.2f})\n")
        f.write(f"\n**Decision: "
                f"{'PROMOTE magnitude' if promote_now else 'KEEP logistic'}**\n")
        if promotion:
            f.write(f"\n_Promoted {len(promotion['changed'])} source file(s); "
                    f"backups at `data/raw/model_backup/`._\n")

    print(f"\n[compare] -> {md_path}")

    return {
        "headlines":         heads,
        "holdouts":          holdouts,
        "q5_wins_6ft":       q5_wins_6ft,
        "q5_wins_8ft":       q5_wins_8ft,
        "r3_magnitude_wins": r3_magnitude_wins,
        "q5_fixed":          q5_fixed_in_backtest,
        "promoted":          promote_now,
        "promotion":         promotion,
        "md_path":           md_path,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=config.TICKERS)
    ap.add_argument("--lookback-days", type=int, default=500)
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--skip-backtest", action="store_true",
                    help="Reuse _kelly_logistic / _kelly_magnitude logs.")
    ap.add_argument("--no-promote", action="store_true",
                    help="Don't write promotion edits even if criteria clear.")
    args = ap.parse_args()

    main(
        tickers       = args.tickers,
        lookback_days = args.lookback_days,
        demo          = not args.real,
        skip_backtest = args.skip_backtest,
        allow_promote = not args.no_promote,
    )

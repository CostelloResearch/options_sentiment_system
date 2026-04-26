# =============================================================================
# signals/confidence_model_magnitude.py -- Magnitude (expected-PnL) confidence
#
# WHY THIS MODULE EXISTS
# ----------------------
# The logistic confidence model (confidence_model.py) predicts `p(win)`.  It
# ranks cleanly on Q5>Q1 at 1-contract sizing but INVERTS Q5 under R3
# proportional sizing: Q5 earns more wins on average, but the wins are small
# and the losses are large enough to swamp them when Kelly/quintile sizing
# amplifies the bet.  See PROJECT_STATE.md sec 8.2.
#
# This module fits an ALTERNATIVE model that targets `pnl_pct` directly
# (continuous, can be negative).  If Q5 predictions skew toward "large
# expected-PnL trades" instead of "frequent small winners", proportional
# sizing should reward the Q5 bets instead of punishing them.
#
# WHY WEIGHTED RIDGE (NOT OLS / NOT TWO-STAGE)?
# ---------------------------------------------
# - L2 regularisation (same lambda as the logistic, same interview-defence
#   argument: ~400 accepted trades, 6 features, tight regularisation keeps
#   coefficients interpretable).
# - Sample weights w_i = min(|pnl_pct_i|, 100) / 10.  Without weights, an
#   OLS fit is dominated by the modal +/-100%-of-max-loss outcomes (all
#   near-max winners and near-max losers get equal weight).  Weighting by
#   |pnl_pct| tells the model "big movers matter more than marginal ones"
#   WITHOUT letting a single 1000%-of-max-loss trade dominate the fit (the
#   cap at 100% bounds the weight at 10x, keeping a worst-case trade from
#   rewriting the beta vector single-handedly).
# - Closed-form solution: beta = (X^T W X + lambda I)^-1 X^T W y.  No
#   sklearn, matches the house style; ~15 lines of numpy.
#
# OUTPUT NORMALISATION
# --------------------
# The raw prediction is an expected-pnl_pct (can be negative, usually in
# [-50, +50] range).  The R3 sizer consumes a [0, 1] confidence score and
# buckets it into quintiles.  We normalise raw predictions via an empirical
# quintile-rank transform fit on in-sample predictions:
#
#     anchor_xs = [p0, p20, p40, p60, p80, p100]  (6 percentiles of raw preds)
#     anchor_ys = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
#     normalised = np.interp(raw, anchor_xs, anchor_ys).clip(0, 1)
#
# Saved anchors make the transform reproducible and avoid look-ahead bias
# when evaluating on hold-out data -- anchors come from the TRAIN fold,
# applied to the TEST fold.
#
# INTERFACE
# ---------
# Exposes the same function names as confidence_model.py so it can be
# swapped in at runtime (e.g., `engine._cmodel = confidence_model_magnitude`):
#
#   load_model / save_model     <- data/raw/magnitude_model.json
#   build_feature_row / matrix  <- same 6 features as logistic (by default)
#   predict_proba / _batch      <- normalised [0, 1] score (drop-in)
#   predict_raw  / _batch       <- raw pnl_pct estimate (for RMSE eval)
#   fit_from_trade_log
#   summarise / validate_quintiles
#
# OPTIONAL INTERACTION TERMS
# --------------------------
# `fit_from_trade_log(..., include_interactions=True)` adds two extra
# features:
#     sentiment_score * iv_rank        (cross-regime non-linearity)
#     sentiment_score * abs_sentiment  (signed-curvature in sentiment)
# Used as a fallback if the 6-feature magnitude model still fails to rank
# Q5 above the other quintiles.  The saved model carries `use_interactions`
# so inference picks the matching feature builder automatically.
# =============================================================================

from __future__ import annotations

import os
import json
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Feature configuration
# ---------------------------------------------------------------------------

BASE_FEATURE_NAMES = [
    "abs_sentiment",
    "iv_rank",
    "sent_momentum_3d",
    "sec_aligned",
    "log_headline_count",
    "log_days_to_earnings",
]

INTERACTION_FEATURE_NAMES = [
    "sent_x_ivrank",           # sentiment_score (signed) * iv_rank
    "sent_x_abs_sent",         # sentiment_score (signed) * |sentiment|
]

# Regularisation.  Same L2 as the logistic model -- keep the two models'
# shrinkage comparable in the head-to-head A/B.
L2_LAMBDA = 0.5

# Sample-weight cap (as fraction of max-loss).  Without a cap, a single
# +900% outlier trade would carry 90x the weight of a +10% trade and
# rewrite the coefficients.  100 caps the weight at 10x.
WEIGHT_CAP_PCT = 100.0
WEIGHT_SCALE   = 10.0   # divisor so max weight is 10x min weight


# ---------------------------------------------------------------------------
# Feature engineering (mirrors confidence_model.py so the two models are
# feature-comparable at the 6-feature level)
# ---------------------------------------------------------------------------

def _log1p_clip(v: float, hi: float) -> float:
    v = max(float(v), 0.0)
    return float(np.log1p(min(v, hi)))


def build_feature_row(
    sentiment_score:  float,
    iv_rank:          float,
    sent_momentum_3d: float,
    sec_aligned:      int,
    headline_count:   int,
    days_to_earnings: int,
    include_interactions: bool = False,
) -> np.ndarray:
    """
    Convert raw signal-time inputs into the fixed feature vector.

    Feature order is FIXED and must match the training-time column order:
    base features first, then (optionally) interactions.
    """
    base = [
        abs(float(sentiment_score)),
        float(iv_rank),
        float(sent_momentum_3d),
        float(1 if sec_aligned else 0),
        _log1p_clip(headline_count, 200),
        _log1p_clip(days_to_earnings, 60),
    ]
    if not include_interactions:
        return np.asarray(base, dtype=float)
    s = float(sentiment_score)
    extra = [
        s * float(iv_rank),
        s * abs(s),
    ]
    return np.asarray(base + extra, dtype=float)


def build_feature_matrix(df: pd.DataFrame,
                         include_interactions: bool = False) -> np.ndarray:
    """
    (n, k) feature matrix from a backtest-log DataFrame.  Missing columns
    fill with the same defaults as the logistic model.
    """
    k = len(BASE_FEATURE_NAMES) + (len(INTERACTION_FEATURE_NAMES)
                                   if include_interactions else 0)
    X = np.zeros((len(df), k), dtype=float)
    for i, (_, r) in enumerate(df.iterrows()):
        X[i, :] = build_feature_row(
            sentiment_score  = r.get("sentiment_score", 0.0),
            iv_rank          = r.get("iv_rank", 0.5),
            sent_momentum_3d = r.get("sent_momentum_3d", 0.0),
            sec_aligned      = r.get("sec_aligned", 0),
            headline_count   = r.get("headline_count", 0),
            days_to_earnings = r.get("days_to_earnings", 999),
            include_interactions = include_interactions,
        )
    return X


def _feature_names(include_interactions: bool) -> list:
    return (list(BASE_FEATURE_NAMES) + list(INTERACTION_FEATURE_NAMES)
            if include_interactions else list(BASE_FEATURE_NAMES))


# ---------------------------------------------------------------------------
# Standardisation (same z-score as the logistic)
# ---------------------------------------------------------------------------

def _standardise(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu  = X.mean(axis=0)
    std = X.std(axis=0, ddof=0)
    std = np.where(std > 1e-9, std, 1.0)
    Xs = (X - mu) / std
    return Xs, mu, std


# ---------------------------------------------------------------------------
# Weighted ridge regression (closed form)
# ---------------------------------------------------------------------------

def fit_weighted_ridge(
    X:  np.ndarray,
    y:  np.ndarray,
    w:  np.ndarray,
    l2: float = L2_LAMBDA,
) -> dict:
    """
    Closed-form weighted ridge:
        beta = (X_des^T W X_des + Lambda)^-1 X_des^T W y
    where the design matrix prepends a bias column (not regularised).

    Returns a dict with (intercept, beta, mean, std, feature_names, l2).
    """
    if X.shape[0] != y.shape[0] or X.shape[0] != w.shape[0]:
        raise ValueError("X, y, w row counts must match.")
    if X.shape[0] == 0:
        raise ValueError("Cannot fit on empty data.")

    Xs, mu, sd = _standardise(X)
    n, k = Xs.shape
    X_des = np.hstack([np.ones((n, 1)), Xs])          # (n, k+1)

    # Scale so weights sum to n -- keeps lambda interpretable across folds
    # of different sizes.  Without this, a 5-fold train set (80% data) vs
    # a time-75% train set would apply different effective shrinkage.
    w = np.asarray(w, dtype=float)
    w = w * (n / max(w.sum(), 1e-9))

    WX = X_des * w[:, None]                           # (n, k+1)
    A  = X_des.T @ WX                                 # (k+1, k+1)
    reg = np.eye(k + 1) * l2
    reg[0, 0] = 0.0                                    # don't regularise bias
    A += reg
    b = X_des.T @ (w * y)

    try:
        beta = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        beta = np.linalg.lstsq(A, b, rcond=None)[0]

    return {
        "intercept": float(beta[0]),
        "beta":      beta[1:].tolist(),
        "mean":      mu.tolist(),
        "std":       sd.tolist(),
        "l2":        float(l2),
    }


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def predict_raw(model: dict, feature_row: np.ndarray) -> float:
    """Raw expected pnl_pct estimate (unbounded, can be negative)."""
    mu   = np.asarray(model["mean"], dtype=float)
    sd   = np.asarray(model["std"],  dtype=float)
    beta = np.asarray(model["beta"], dtype=float)
    b0   = float(model["intercept"])
    xs = (feature_row - mu) / np.where(sd > 1e-9, sd, 1.0)
    return float(b0 + xs @ beta)


def predict_raw_batch(model: dict, X: np.ndarray) -> np.ndarray:
    mu   = np.asarray(model["mean"], dtype=float)
    sd   = np.asarray(model["std"],  dtype=float)
    beta = np.asarray(model["beta"], dtype=float)
    b0   = float(model["intercept"])
    sd_safe = np.where(sd > 1e-9, sd, 1.0)
    Xs = (X - mu) / sd_safe
    return b0 + Xs @ beta


def _normalise_to_unit(raw: float, anchor_x: list, anchor_y: list) -> float:
    """Empirical-CDF interpolation of a raw prediction into [0, 1]."""
    return float(np.clip(np.interp(raw, anchor_x, anchor_y), 0.0, 1.0))


def predict_proba(model: dict, feature_row: np.ndarray) -> float:
    """
    Drop-in replacement for logistic's predict_proba: raw pnl_pct prediction
    mapped through the saved quintile-rank transform to [0, 1].
    """
    raw = predict_raw(model, feature_row)
    return _normalise_to_unit(raw,
                              model["norm_anchor_x"],
                              model["norm_anchor_y"])


def predict_proba_batch(model: dict, X: np.ndarray) -> np.ndarray:
    raw = predict_raw_batch(model, X)
    ax  = np.asarray(model["norm_anchor_x"], dtype=float)
    ay  = np.asarray(model["norm_anchor_y"], dtype=float)
    return np.clip(np.interp(raw, ax, ay), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def model_path() -> str:
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "raw", "magnitude_model.json"
    ))


def save_model(model: dict, path: Optional[str] = None) -> str:
    path = path or model_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    return path


def load_model(path: Optional[str] = None) -> Optional[dict]:
    path = path or model_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = json.load(f)
        # Schema sanity: feature_names must match the active config.
        expected = _feature_names(m.get("use_interactions", False))
        if list(m.get("feature_names", [])) != expected:
            print(f"[magnitude_model] saved feature set {m.get('feature_names')} "
                  f"doesn't match expected {expected}; ignoring stale model.")
            return None
        return m
    except Exception as e:
        print(f"[magnitude_model] failed to load: {e}")
        return None


# ---------------------------------------------------------------------------
# End-to-end fit from a trade log (with optional weight-scheme override)
# ---------------------------------------------------------------------------

def _compute_weights(y: np.ndarray) -> np.ndarray:
    """
    Per-spec: w_i = min(|pnl_pct_i|, WEIGHT_CAP_PCT) / WEIGHT_SCALE.
    Floored at 0.01 so a trade that closes exactly at breakeven still has
    non-zero weight (otherwise the weighted normal equations drop it).
    """
    w = np.minimum(np.abs(y), WEIGHT_CAP_PCT) / WEIGHT_SCALE
    return np.maximum(w, 0.01)


def _compute_norm_anchors(raw_preds: np.ndarray) -> tuple[list, list]:
    """
    Six-point empirical-CDF anchors (percentiles 0, 20, 40, 60, 80, 100).
    Returns (xs, ys) suitable for np.interp.  When the raw-pred distribution
    is degenerate (all equal), we nudge xs so np.interp still works.
    """
    xs = [float(x) for x in np.percentile(raw_preds, [0, 20, 40, 60, 80, 100])]
    ys = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    # Ensure strictly increasing xs for np.interp (ties break ordering)
    for i in range(1, len(xs)):
        if xs[i] <= xs[i-1]:
            xs[i] = xs[i-1] + 1e-9
    return xs, ys


def fit_from_trade_log(
    trades: pd.DataFrame,
    l2:     float = L2_LAMBDA,
    save:   bool  = True,
    include_interactions: bool = False,
    save_path: Optional[str] = None,
) -> dict:
    """
    Fit the magnitude model on an accepted-trade log.

    - Restricts to accepted trades only (rejected signals have no pnl_pct).
    - Target y = pnl_pct (continuous, can be negative).
    - Weights = min(|pnl_pct|, 100) / 10.
    - Normalisation anchors fit on in-sample raw predictions so predict_proba
      returns a [0, 1] score aligned with training-distribution quintiles.

    Returns the fitted model dict; also saves to disk if `save=True`.
    """
    df = trades.copy()
    if "accepted" in df.columns:
        df = df[df["accepted"].astype(bool)]
    if df.empty:
        raise ValueError("No accepted trades in log; nothing to fit.")
    if "pnl_pct" not in df.columns:
        raise ValueError("Trade log missing pnl_pct.")

    y = df["pnl_pct"].astype(float).values
    w = _compute_weights(y)
    X = build_feature_matrix(df, include_interactions=include_interactions)

    model = fit_weighted_ridge(X, y, w, l2=l2)
    model["feature_names"]    = _feature_names(include_interactions)
    model["use_interactions"] = bool(include_interactions)

    # Normalisation anchors from in-sample raw predictions
    raw = predict_raw_batch(model, X)
    xs, ys = _compute_norm_anchors(raw)
    model["norm_anchor_x"] = xs
    model["norm_anchor_y"] = ys

    # Training diagnostics
    resid = y - raw
    model["train_n"]        = int(len(y))
    model["train_rmse"]     = float(np.sqrt(np.mean(resid ** 2)))
    model["train_mean_abs"] = float(np.mean(np.abs(resid)))
    model["train_r2"]       = float(1.0 - (resid ** 2).sum() /
                                    max(((y - y.mean()) ** 2).sum(), 1e-9))
    model["train_weight_sum"] = float(w.sum())

    if save:
        save_model(model, path=save_path)
    return model


# ---------------------------------------------------------------------------
# Summaries + holdout validation helpers
# ---------------------------------------------------------------------------

def summarise(model: dict) -> str:
    lines = []
    interactions = model.get("use_interactions", False)
    lines.append(f"n={model.get('train_n')}  RMSE={model.get('train_rmse', 0):.3f}  "
                 f"R2={model.get('train_r2', 0):+.4f}  "
                 f"l2={model.get('l2')}  interactions={interactions}")
    lines.append(f"intercept = {model['intercept']:+.4f}  "
                 f"(baseline expected pnl_pct at mean-feature point)")
    lines.append("coefficients (standardised space, expected pnl_pct per 1-sd feature move):")
    for name, b in zip(model["feature_names"], model["beta"]):
        lines.append(f"  {name:<22s}  {b:+.4f}")
    xs = model.get("norm_anchor_x", [])
    if xs:
        lines.append(f"norm anchors (raw pnl_pct at 0/20/40/60/80/100 pct): "
                     f"{[round(x, 2) for x in xs]}")
    return "\n".join(lines)


def validate_quintiles(
    trades: pd.DataFrame,
    model:  dict,
    horizon_col: str = "pnl_pct",
    use_train_anchors: bool = True,
) -> pd.DataFrame:
    """
    Score every accepted trade, bucket into Q1-Q5 by NORMALISED prediction,
    and compute per-quintile mean pnl_pct + win rate.  Uses TRAIN-FOLD's
    saved normalisation anchors (no leakage).
    """
    df = trades.copy()
    if "accepted" in df.columns:
        df = df[df["accepted"].astype(bool)]
    if df.empty:
        return pd.DataFrame()
    X = build_feature_matrix(
        df,
        include_interactions=model.get("use_interactions", False),
    )
    # Use normalised [0, 1] so the quintile partition matches production.
    p = predict_proba_batch(model, X)
    df = df.assign(model_confidence=p)
    try:
        df["quintile"] = pd.qcut(
            df["model_confidence"], 5,
            labels=["Q1 (lowest)", "Q2", "Q3", "Q4", "Q5 (highest)"],
            duplicates="drop",
        )
    except Exception:
        df["quintile"] = "UNSPLIT"
    summary = df.groupby("quintile", observed=True).agg(
        n        = ("model_confidence", "size"),
        mean_p   = ("model_confidence", "mean"),
        mean_ret = (horizon_col, "mean"),
        win_rate = (horizon_col, lambda s: float((s > 0).mean())),
    ).reset_index()
    return summary

# =============================================================================
# signals/confidence_model.py -- Logistic-regression confidence score
#
# WHY THIS MODULE EXISTS
# ----------------------
# The original tiered confidence formula (news strength + IV-rank depth,
# optionally bumped by SEC agreement) failed validation in the decay study:
#
#     confidence quintile    mean 20d return
#       Q1 (weakest)              +1.35%
#       Q2                        +1.13%
#       Q3                        +0.46%
#       Q4                        +1.21%
#       Q5 (strongest)            -0.78%  <-- INVERSION
#
# If the "highest confidence" bucket UNDERPERFORMS the "lowest confidence"
# bucket, the score is worse than random -- it actively mis-ranks trades.
# The root cause is almost certainly volatility-driven inflation: a huge
# sentiment swing into an extreme IV-rank bar produces a high confidence
# score precisely on days where the market is already in a high-noise
# regime, which is the worst time to trade a mean-reverting / overreaction
# signal.
#
# So we replace the hand-rolled formula with a fitted logistic-regression
# estimate of "probability this trade wins" (pnl_pct > 0), using features
# that are available at signal-generation time.
#
# WHY LOGISTIC REGRESSION (NOT XGBOOST / RANDOM FOREST)?
# -------------------------------------------------------
# 1. Interview-defensibility -- I need to be able to write the math on a
#    whiteboard: sigmoid(beta_0 + beta . x) with a coefficient vector per
#    feature.  Gradient tree ensembles can't do that.
# 2. Small n (~400 accepted trades in demo, ~1-2k when real data lands).
#    With ~6 features a linear model is already at the upper end of what
#    the data supports; a tree ensemble would be well into overfit land.
# 3. Coefficients give us feature-importance for free.  If a feature's
#    coefficient rounds to zero, that's the model's way of saying "this
#    didn't carry signal" -- exactly what the spec asked for.
# 4. No sklearn dependency.  scipy is already pulled in for bs_price, but
#    I'd rather not require scikit-learn just for one model.  Implementing
#    it ourselves is 30 lines and demonstrates understanding.
#
# HAND-ROLLED IMPLEMENTATION
# --------------------------
# Logistic regression maximises the log-likelihood
#     L(beta) = sum_i [ y_i log(p_i) + (1-y_i) log(1-p_i) ]
# where p_i = sigmoid(x_i . beta).  No closed form -- we use gradient
# ascent (== gradient descent on -L):
#     grad   = X.T @ (p - y)                               + 2*lambda*beta
#     hess   = X.T @ diag(p*(1-p)) @ X                     + 2*lambda*I
#     beta  -= solve(hess, grad)    <- Newton-Raphson / IRLS step
# IRLS converges in ~5-10 iterations for well-conditioned problems.  If
# the Hessian is singular we fall back to a small-lr gradient step.
#
# FEATURES (documented with the "why" for each)
# ---------------------------------------------
#   abs_sentiment       |sentiment_score|        signal strength magnitude
#   iv_rank             iv_rank                  cheap/expensive regime
#   sent_momentum_3d    3-day delta in score     new news vs stale news
#   sec_aligned         {0,1} SEC agrees         cross-source corroboration
#   headline_count      log1p(n)                 conviction / liquidity
#   days_to_earnings    log1p(min(n, 60))        earnings-proximity penalty
#
# TARGET
# ------
#   y = 1 if pnl_pct > 0 else 0, computed over ACCEPTED trades only.
#   We're modelling "given the risk/reward filter let this trade through,
#   what's p(win)?"  Rejected trades have no outcome.
#
# INTEGRATION WITH signal_engine
# ------------------------------
# Fitted model is saved as data/raw/confidence_model.json (simple dict
# with beta vector + feature means/stds for standardisation).  At signal
# time, generate_signal() loads this JSON, standardises the current bar's
# features, and computes sigmoid(x.beta) as the confidence score.  If the
# file is missing we fall back to _compute_confidence_legacy (same v1
# behaviour) so the system still works cold.
# =============================================================================

from __future__ import annotations

import os
import json
import math
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Feature order is FIXED -- the fitted beta vector is interpreted in this
# order, so changing it without retraining breaks the model.
FEATURE_NAMES = [
    "abs_sentiment",
    "iv_rank",
    "sent_momentum_3d",
    "sec_aligned",
    "log_headline_count",
    "log_days_to_earnings",
]

# Regularisation: small ridge penalty to keep coefficients bounded when a
# feature is nearly constant (prevents the Hessian from going singular).
L2_LAMBDA        = 0.5

# IRLS hyperparameters
MAX_IRLS_ITERS   = 50
CONVERGENCE_TOL  = 1e-6

# When we don't have a fitted model yet (cold start), fall back to the
# legacy formula rather than returning 0.  0 would disable every trade.
FALLBACK_CONFIDENCE_ON_MISSING = True

# ---------------------------------------------------------------------------
# Option A (2026-05-01): disable the learned logistic model entirely.
# Walk-forward audit (2026-04-28) showed Q5 P&L inverts +$3,674 in-sample to
# -$5,685 OOS -- the model's "highest confidence" trades are systematically
# the worst losers on data the parameters haven't seen.  With sizing now
# uniform (position_sizer.USE_QUINTILE_SIZING=False) the predicted p(win)
# no longer routes capital, so loading the JSON would only stamp a misleading
# probability on every trade row.  We gate load_model() to return None so
# both the live signal path and the backtest engine fall through to the
# legacy tiered-confidence formula -- keeping the JSON on disk untouched
# for later A/B comparison if/when the model is rebuilt with a defensible
# OOS validation step.
USE_LEARNED_MODEL = False


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _log1p_clip(v: float, hi: float) -> float:
    """log1p(min(v, hi)) -- tames the long tail on count/day features."""
    v = max(float(v), 0.0)
    return float(np.log1p(min(v, hi)))


def build_feature_row(
    sentiment_score:  float,
    iv_rank:          float,
    sent_momentum_3d: float,
    sec_aligned:      int,
    headline_count:   int,
    days_to_earnings: int,
) -> np.ndarray:
    """
    Convert raw signal-time inputs into the fixed feature vector the model
    expects.  Always returns an array of shape (len(FEATURE_NAMES),).
    """
    return np.array([
        abs(float(sentiment_score)),
        float(iv_rank),
        float(sent_momentum_3d),
        float(1 if sec_aligned else 0),
        _log1p_clip(headline_count, 200),
        _log1p_clip(days_to_earnings, 60),
    ], dtype=float)


def build_feature_matrix(df: pd.DataFrame) -> np.ndarray:
    """
    Build an (n, k) feature matrix from a backtest-log DataFrame.
    Missing columns are filled with defensible defaults so old logs still
    work (sec_aligned=0, momentum=0, earnings=999 => far from earnings).
    """
    X = np.zeros((len(df), len(FEATURE_NAMES)), dtype=float)
    for i, (_, r) in enumerate(df.iterrows()):
        X[i, :] = build_feature_row(
            sentiment_score  = r.get("sentiment_score", 0.0),
            iv_rank          = r.get("iv_rank", 0.5),
            sent_momentum_3d = r.get("sent_momentum_3d", 0.0),
            sec_aligned      = r.get("sec_aligned", 0),
            headline_count   = r.get("headline_count", 0),
            days_to_earnings = r.get("days_to_earnings", 999),
        )
    return X


# ---------------------------------------------------------------------------
# Logistic regression core (IRLS with ridge regularisation)
# ---------------------------------------------------------------------------

def _sigmoid(z: np.ndarray) -> np.ndarray:
    # Clip to avoid overflow at large |z|.  exp(-35) ~= 6e-16 which is fine.
    z = np.clip(z, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-z))


def _standardise(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Z-score each column; return (X_std, mean, std).  Constant columns get
    std=1 so the division is safe -- their standardised value is just
    (v - mean), which is 0 after centering.
    """
    mu  = X.mean(axis=0)
    std = X.std(axis=0, ddof=0)
    std = np.where(std > 1e-9, std, 1.0)
    Xs = (X - mu) / std
    return Xs, mu, std


def fit_logistic(
    X:      np.ndarray,
    y:      np.ndarray,
    l2:     float = L2_LAMBDA,
    verbose: bool = False,
) -> dict:
    """
    Fit a logistic regression via IRLS (Newton-Raphson) with ridge.

    Returns a dict:
        intercept : scalar
        beta      : (k,) coefficient vector in the standardised feature space
        mean      : (k,) pre-standardisation means
        std       : (k,) pre-standardisation stds
        iters     : number of IRLS steps taken
        converged : bool
        feature_names : list[str]  (order must match beta)
    """
    if len(X) == 0:
        raise ValueError("Cannot fit on empty data.")
    if X.shape[0] != y.shape[0]:
        raise ValueError("X and y have mismatched row counts.")

    # --- Standardise features; augment with an explicit bias column ---
    Xs, mu, sd = _standardise(X)
    n, k = Xs.shape
    # Bias column at index 0 of the design matrix; the bias coefficient is
    # NOT regularised.
    X_des = np.hstack([np.ones((n, 1)), Xs])            # (n, k+1)
    beta  = np.zeros(k + 1, dtype=float)

    # Ridge penalty diag -- zero for the bias term.
    reg = np.eye(k + 1) * l2
    reg[0, 0] = 0.0

    prev_loss = None
    iters = 0
    converged = False
    for iters in range(1, MAX_IRLS_ITERS + 1):
        eta = X_des @ beta
        p   = _sigmoid(eta)
        # Gradient of -(log-likelihood) + ridge
        grad = X_des.T @ (p - y) + reg @ beta
        # Hessian of -(log-likelihood) + ridge
        W = p * (1.0 - p)
        # Floor W away from 0 for numerical stability when p saturates
        W = np.maximum(W, 1e-6)
        H = X_des.T @ (W[:, None] * X_des) + reg

        try:
            step = np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            # Fall back to a small gradient step if Hessian is singular
            step = 0.01 * grad
        beta = beta - step

        # Convergence: change in log-loss below tol
        eta2 = X_des @ beta
        p2   = _sigmoid(eta2)
        eps  = 1e-12
        loss = -np.mean(y * np.log(p2 + eps) + (1 - y) * np.log(1 - p2 + eps))
        if verbose:
            print(f"  iter {iters:02d}  loss={loss:.6f}  |step|={np.linalg.norm(step):.3e}")
        if prev_loss is not None and abs(prev_loss - loss) < CONVERGENCE_TOL:
            converged = True
            break
        prev_loss = loss

    return {
        "intercept":     float(beta[0]),
        "beta":          beta[1:].tolist(),
        "mean":          mu.tolist(),
        "std":           sd.tolist(),
        "iters":         int(iters),
        "converged":     bool(converged),
        "feature_names": list(FEATURE_NAMES),
        "l2":            float(l2),
    }


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def predict_proba(
    model:        dict,
    feature_row:  np.ndarray,
) -> float:
    """
    Given a fitted model dict and a single raw feature vector (shape k),
    return the predicted win probability (scalar in [0, 1]).
    """
    mu   = np.asarray(model["mean"], dtype=float)
    sd   = np.asarray(model["std"],  dtype=float)
    beta = np.asarray(model["beta"], dtype=float)
    b0   = float(model["intercept"])

    xs = (feature_row - mu) / np.where(sd > 1e-9, sd, 1.0)
    z  = b0 + float(xs @ beta)
    return float(_sigmoid(np.array([z]))[0])


def predict_proba_batch(model: dict, X: np.ndarray) -> np.ndarray:
    """Vectorised predict_proba over a feature matrix."""
    mu   = np.asarray(model["mean"], dtype=float)
    sd   = np.asarray(model["std"],  dtype=float)
    beta = np.asarray(model["beta"], dtype=float)
    b0   = float(model["intercept"])

    sd_safe = np.where(sd > 1e-9, sd, 1.0)
    Xs = (X - mu) / sd_safe
    z  = b0 + Xs @ beta
    return _sigmoid(z)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def model_path() -> str:
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "raw", "confidence_model.json"
    ))


def save_model(model: dict, path: Optional[str] = None) -> str:
    path = path or model_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2)
    return path


def load_model(path: Optional[str] = None) -> Optional[dict]:
    """Return the fitted model dict, or None if not on disk."""
    # Option A gate (2026-05-01): when USE_LEARNED_MODEL is False, every
    # caller falls through to the legacy confidence formula.  See module
    # docstring on USE_LEARNED_MODEL for the walk-forward rationale.
    if not USE_LEARNED_MODEL:
        return None
    path = path or model_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = json.load(f)
        # Basic schema check -- if someone swapped features we refuse silently.
        if list(m.get("feature_names", [])) != FEATURE_NAMES:
            print(f"[confidence_model] saved feature set doesn't match "
                  f"FEATURE_NAMES; ignoring stale model.")
            return None
        return m
    except Exception as e:
        print(f"[confidence_model] failed to load model: {e}")
        return None


# ---------------------------------------------------------------------------
# End-to-end fit from a backtest log
# ---------------------------------------------------------------------------

def fit_from_trade_log(
    trades: pd.DataFrame,
    l2:     float = L2_LAMBDA,
    save:   bool  = True,
) -> dict:
    """
    Fit the model on a backtest log.

    - Restricts to accepted trades only (rejected trades have no outcome).
    - Target: pnl_pct > 0.
    - Drops rows missing any feature column (filled with defaults via
      build_feature_matrix, so "missing" is rare in practice).

    Returns the fitted model dict; also saves to disk if `save=True`.
    """
    df = trades.copy()
    if "accepted" in df.columns:
        df = df[df["accepted"].astype(bool)]
    if df.empty:
        raise ValueError("No accepted trades in log; nothing to fit.")
    if "pnl_pct" not in df.columns:
        raise ValueError("Trade log missing pnl_pct.")

    y = (df["pnl_pct"].astype(float) > 0).astype(int).values
    X = build_feature_matrix(df)

    model = fit_logistic(X, y, l2=l2, verbose=False)
    # Diagnostic: training-set win-rate and model's in-sample accuracy
    p = predict_proba_batch(model, X)
    model["train_win_rate"]      = float(y.mean())
    model["train_n"]             = int(len(y))
    model["train_brier"]         = float(np.mean((p - y) ** 2))
    model["train_log_loss"]      = float(-np.mean(
        y * np.log(p.clip(1e-9, 1.0)) + (1 - y) * np.log((1 - p).clip(1e-9, 1.0))
    ))

    if save:
        save_model(model)
    return model


# ---------------------------------------------------------------------------
# Pretty-print + Q1/Q5 validation
# ---------------------------------------------------------------------------

def summarise(model: dict) -> str:
    """Multi-line summary: coefficients, training stats, convergence."""
    lines = []
    lines.append(f"n={model.get('train_n')}  "
                 f"train_win_rate={model.get('train_win_rate', 0):.3f}  "
                 f"converged={model.get('converged')} in "
                 f"{model.get('iters')} iters  l2={model.get('l2')}")
    lines.append(f"intercept = {model['intercept']:+.4f}  "
                 f"(bias at mean-feature point)")
    lines.append("coefficients (standardised space):")
    for name, b in zip(model["feature_names"], model["beta"]):
        lines.append(f"  {name:<22s}  {b:+.4f}")
    lines.append(f"train log-loss = {model.get('train_log_loss', 0):.4f}  "
                 f"brier = {model.get('train_brier', 0):.4f}")
    return "\n".join(lines)


def validate_quintiles(
    trades: pd.DataFrame,
    model:  dict,
    horizon_col: str = "pnl_pct",
) -> pd.DataFrame:
    """
    Score every accepted trade, bucket into Q1-Q5 by predicted probability,
    and compute per-quintile mean return + win rate.

    The spec's "Q5 should now clearly outperform Q1" validation reads the
    last row vs the first of the returned DataFrame.
    """
    df = trades.copy()
    if "accepted" in df.columns:
        df = df[df["accepted"].astype(bool)]
    if df.empty:
        return pd.DataFrame()

    X = build_feature_matrix(df)
    p = predict_proba_batch(model, X)
    df = df.assign(model_confidence=p)

    # pd.qcut can collapse if too many ties; duplicates='drop' means we may
    # end up with fewer than 5 bins if the distribution is degenerate.
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

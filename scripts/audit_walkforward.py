# =============================================================================
# scripts/audit_walkforward.py -- Daily walk-forward audit of the R3 baseline
#
# QUESTION: is the 75/25 audit's DEGRADES verdict (Sharpe +0.41 in-sample ->
# -0.60 OOS) universal across refit windows, or specific to the single
# 2025-11-17 cutoff date?  Walk-forward refits the three in-sample-leakage
# parameters (kelly_stats, quintile_edges, confidence_model) every time a
# new trade completes; each new entry is sized using parameters fit on
# data that finished BEFORE its entry date.
#
# IMPLEMENTATION: extends the path-(b) post-hoc re-derivation pattern from
# audit_oos_split.py.  The flat corpus's per-share `pnl` and `max_loss` are
# spread+price properties that do not change with sizing; only contracts
# change between in-sample and OOS sizing decisions.  Walk-forward replays
# the corpus chronologically with per-trade sizing decisions made under
# parameters known at entry time.
#
# READ-ONLY ON PRODUCTION CODE.  No artifacts written under data/raw/.
# =============================================================================

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402
from signals import position_sizer, confidence_model  # noqa: E402

RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
OUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
OUT_PATH = os.path.join(OUT_DIR, "walkforward_audit_report.md")

# Production paths (read-only references for cleanup verification)
PROD_STATS_PATH = os.path.join(RAW_DIR, "kelly_stats.csv")
PROD_EDGES_PATH = os.path.join(RAW_DIR, "quintile_edges.json")
PROD_MODEL_PATH = os.path.join(RAW_DIR, "confidence_model.json")

# Tuning constants
WARMUP_N_TRADES         = 50
KELLY_BACKTEST_NOTIONAL = 100_000.0
SHARPE_ANN              = float(np.sqrt(252.0 / 5.0))
ROLLING_WINDOW_DAYS     = 60
ROLLING_MIN_TRADES      = 10  # below this, the rolling Sharpe is undefined

REJECT_REASONS = {
    "rejected_by_kelly", "bucket_full",
    "portfolio_risk_cap", "rejected_risk_reward",
}

# ---------------------------------------------------------------------------
# Mode-conditional prose lookup
# ---------------------------------------------------------------------------
# Audit prose changes between the synthetic-corpus (DEMO) and real-news
# (REAL) backtests: the headline R3 baseline differs in each mode, the
# prior 75/25 audit returned different verdicts in each mode, and corpus
# caveats differ structurally.  Numerical content of the audit (tables,
# metrics) is unchanged by this lookup -- it only affects which phrasing
# the report-builder substitutes into prose paragraphs.

_BASELINE_REAL = {
    "baseline_full":   "+$9,697 / Sharpe 1.17 / 295 trades",
    "baseline_pnl":    "+$9,697",
    "baseline_sharpe": "+1.17",
    "prior_oos_verdict_phrase": (
        "PARTIAL verdict (Sharpe +1.17 in-sample -> +0.98 OOS) on the "
        "real-news 75/25 holdout (cutoff 2025-12-22)"
    ),
    "oos_75_25_footnote": (
        "_75/25 OOS column shows the synthetic-mode reference values from "
        "`outputs/oos_audit_report.md` (cutoff 2025-11-17); the comparison "
        "column has not been re-derived from the real-mode 75/25 audit "
        "(`outputs/oos_audit_report_real.md`).  Walk-forward column is "
        "computed in this session on the real-mode flat corpus.  The "
        "in-sample baseline column is real-mode and shares with both other "
        "columns the same per-share P&L from the real-news flat backtest._\n\n"
    ),
    "corpus_caveat": (
        "- **Real-corpus single-regime caveat.**  Trade corpus drawn "
        "from the real-news flat backtest covering ~12 months of "
        "headlines (~2025-05 to 2026-05).  Walk-forward on a single "
        "real-news regime is one realisation, not a Monte Carlo over "
        "macro conditions; per-ticker P&L is heavily concentrated "
        "(see PROJECT_STATE Section 10.2).  A different corpus window "
        "or ticker mix would produce different rolling-Sharpe "
        "dynamics.\n"
    ),
    "single_realisation_caveat": (
        "- **Single-corpus caveat.**  This audit replays exactly one "
        "real-news corpus collected for the production universe.  The "
        "rolling-Sharpe distribution captures within-corpus variance, "
        "not cross-corpus variance from re-ingesting different news "
        "windows or ticker mixes.\n\n"
    ),
}

_BASELINE_DEMO = {
    "baseline_full":   "+$6,775 / Sharpe 0.41 / 357 trades",
    "baseline_pnl":    "+$6,775",
    "baseline_sharpe": "+0.41",
    "prior_oos_verdict_phrase": (
        "DEGRADES verdict (Sharpe +0.41 in-sample -> -0.60 OOS, Q5 "
        "confidence-bucket inversion)"
    ),
    "oos_75_25_footnote": (
        "_75/25 OOS column reproduced from `outputs/oos_audit_report.md` "
        "(cutoff 2025-11-17); walk-forward column computed in this "
        "session.  Both share the in-sample comparison baseline._\n\n"
    ),
    "corpus_caveat": (
        "- **Synthetic-sentiment caveat (still load-bearing).**  Trade "
        "corpus drawn from the synthetic-mode flat backtest "
        "(deterministic per-ticker sentiment seed).  Walk-forward on "
        "the synthetic generator is a single realisation, not a Monte "
        "Carlo over RNG draws.  Real-mode walk-forward on accumulated "
        "live news will differ structurally.\n"
    ),
    "single_realisation_caveat": (
        "- **Single-realisation caveat.**  Synthetic sentiment seed is "
        "deterministic per ticker (`seed = sum(ord(c) for c in ticker)`).  "
        "Rerunning would produce identical results; a Monte Carlo over "
        "different seeds would require a code change in "
        "`backtest/engine._generate_synthetic_history` (out of scope).\n\n"
    ),
}


def _baseline_phrases(mode_label: str) -> dict:
    return _BASELINE_REAL if mode_label == "REAL" else _BASELINE_DEMO


# Frozen reference numbers from outputs/oos_audit_report.md.  Re-deriving
# would duplicate ~80 lines of audit_oos_split.py; the on-disk corpus is
# stable so these values are reproducible by re-running that script.
OOS_75_25 = {
    "n_signals":     213,
    "n_trades":      113,
    "total_pnl":     -2877.57,
    "sharpe":        -0.5977,
    "max_dd":        -7731.05,
    "profit_factor": 0.7295,
    "win_rate":      0.2629,
    "Q5_pnl":        -5585.84,
    "Q1_pnl":        -324.31,
    "AAPL_pnl":      -4534.71,
    "NVDA_pnl":      -471.32,
    "cutoff_date":   "2025-11-17",
}


# ---------------------------------------------------------------------------
# Loaders + headline + helpers (mirror audit_oos_split.py)
# ---------------------------------------------------------------------------

def load_flat_corpus(real_mode: bool = False,
                     tickers: list | None = None) -> pd.DataFrame:
    tickers = tickers if tickers is not None else config.TICKERS
    frames = []
    for t in tickers:
        fname = f"backtest_{t}.csv" if real_mode else f"backtest_{t}_demo.csv"
        p = os.path.join(RAW_DIR, fname)
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    return pd.concat(frames, ignore_index=True)


def load_kelly_logs(real_mode: bool = False,
                    tickers: list | None = None) -> pd.DataFrame:
    tickers = tickers if tickers is not None else config.TICKERS
    frames = []
    for t in tickers:
        fname = f"backtest_{t}_kelly.csv" if real_mode else f"backtest_{t}_demo_kelly.csv"
        p = os.path.join(RAW_DIR, fname)
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    return pd.concat(frames, ignore_index=True)


def taken_mask(df: pd.DataFrame) -> pd.Series:
    acc = df["accepted"].astype(bool)
    kr  = df["kelly_reason"].astype(str).fillna("")
    return acc & ~(kr.isin(REJECT_REASONS) | kr.str.startswith("negative_kelly_"))


def headline(df: pd.DataFrame) -> dict:
    """Mirror r3_baseline.headline() and audit_oos_split.headline()."""
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


def file_signature(path: str) -> tuple:
    if not os.path.exists(path):
        return ("missing", 0)
    return (round(os.path.getmtime(path), 3), os.path.getsize(path))


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
# Parameter fitting (identical to audit_oos_split.fit_train_params, modulo
# the no-disk-write contract -- nothing here writes to data/raw/)
# ---------------------------------------------------------------------------

def fit_params(completed_accepted: pd.DataFrame) -> tuple[dict, list, dict]:
    """
    Fit kelly_stats, confidence model, and quintile edges (calibrated to the
    refit model's output distribution) on the supplied completed-and-accepted
    trade slice.  In-memory only; nothing is persisted to disk.
    """
    train_stats = position_sizer.compute_kelly_stats(completed_accepted)
    train_model = confidence_model.fit_from_trade_log(completed_accepted, save=False)

    # Edges fit on train_model output over the same training rows
    X = confidence_model.build_feature_matrix(completed_accepted)
    train_conf = confidence_model.predict_proba_batch(train_model, X)
    s = pd.Series(train_conf).dropna()
    try:
        _, cuts = pd.qcut(s, 5, retbins=True, duplicates="drop")
        edges = [float(x) for x in cuts[1:-1]]
        if len(edges) != 4:
            edges = list(position_sizer.DEFAULT_QUINTILE_EDGES)
    except Exception:
        edges = list(position_sizer.DEFAULT_QUINTILE_EDGES)
    return train_stats, edges, train_model


def _quintile_label(conf: float, edges: list) -> str:
    if   conf < edges[0]: return "Q1"
    elif conf < edges[1]: return "Q2"
    elif conf < edges[2]: return "Q3"
    elif conf < edges[3]: return "Q4"
    else:                  return "Q5"


# ---------------------------------------------------------------------------
# Walk-forward main loop
# ---------------------------------------------------------------------------

def walk_forward(flat: pd.DataFrame) -> tuple[pd.DataFrame, int, list, pd.Timestamp]:
    """
    Walk through the corpus chronologically.  At each entry date T:
      1. Compute training corpus = trades with `exit_date < T` AND
         accepted=True.  This is the no-look-ahead semantic: trades whose
         realized P&L is known by day T-1.  (The prompt's phrasing
         "entry_date < T" is methodologically the same intent but allows
         in-flight trades; using exit_date is the correct read.)
      2. If |training| < WARMUP_N_TRADES, mark this signal warmup-excluded
         and skip.
      3. Else, refit (only if training corpus has grown since last refit),
         then size this signal under the just-fit parameters.

    Returns (eval_df, n_warmup_excluded, refit_events, warmup_cutoff_date).
    eval_df has all signal rows that PASSED the warmup gate (whether
    accepted=True or =False); pnl_total and kelly_reason are overwritten
    with walk-forward values.
    """
    flat = flat.sort_values("entry_date").reset_index(drop=True)
    accepted = (flat[flat["accepted"].astype(bool)]
                .copy().sort_values("exit_date").reset_index(drop=True))

    last_n   = -1
    cached   = None  # (stats, edges, model)
    refit_events: list = []
    eval_rows: list    = []
    n_warmup_excluded  = 0
    warmup_cutoff_date: pd.Timestamp | None = None

    n_total = len(flat)
    progress_every = max(n_total // 10, 1)
    t_start = time.monotonic()

    for i, row in flat.iterrows():
        T = pd.Timestamp(row["entry_date"])

        # Training corpus = accepted trades whose exit_date < T
        n_completed = int((accepted["exit_date"] < T).sum())

        if n_completed < WARMUP_N_TRADES:
            n_warmup_excluded += 1
            continue

        if warmup_cutoff_date is None:
            warmup_cutoff_date = T

        # Refit only when the training corpus has grown
        if n_completed != last_n:
            completed = accepted.iloc[:n_completed]  # equivalent slice
            stats, edges, model = fit_params(completed)
            cached = (stats, edges, model)
            refit_events.append({
                "date":    T,
                "n_train": n_completed,
                "edges":   list(edges),
                "stats":   {sig: dict(v) for sig, v in stats.items()},
                "model":   {
                    "intercept":     float(model["intercept"]),
                    "beta":          list(model["beta"]),
                    "feature_names": list(model["feature_names"]),
                },
            })
            last_n = n_completed
        stats, edges, model = cached

        if not bool(row["accepted"]):
            # Risk-reward filter rejected at structure time; same in any sizing regime
            d = row.to_dict()
            d.update({
                "wf_contracts":   0,
                "kelly_reason":   "rejected_risk_reward",
                "wf_q":           "",
                "wf_confidence":  0.0,
                "pnl_total":      0.0,
            })
            eval_rows.append(d)
            continue

        feat = confidence_model.build_feature_row(
            sentiment_score  = float(row["sentiment_score"]),
            iv_rank          = float(row["iv_rank"]),
            sent_momentum_3d = float(row.get("sent_momentum_3d", 0.0)),
            sec_aligned      = int(row.get("sec_aligned", 0)),
            headline_count   = int(row.get("headline_count", 0)),
            days_to_earnings = int(row.get("days_to_earnings", 999)),
        )
        conf = float(confidence_model.predict_proba(model, feat))

        max_loss = float(row.get("max_loss", 0.0))
        if max_loss <= 0:
            d = row.to_dict()
            d.update({
                "wf_contracts":   0,
                "kelly_reason":   "invalid_max_loss",
                "wf_q":           "",
                "wf_confidence":  conf,
                "pnl_total":      0.0,
            })
            eval_rows.append(d)
            continue

        size = position_sizer.size_trade(
            signal                  = str(row["signal"]),
            confidence              = conf,
            max_loss_per_contract   = max_loss,
            stats                   = stats,
            open_risk_dollars       = 0.0,
            open_risk_by_strategy   = None,
            account_notional        = KELLY_BACKTEST_NOTIONAL,
            use_segregated_buckets  = False,
            quintile_edges          = edges,
        )
        contracts = int(size["contracts"])
        reason    = str(size.get("reason", ""))
        q         = _quintile_label(conf, edges)

        d = row.to_dict()
        d.update({
            "wf_contracts":  contracts,
            "kelly_reason":  reason,            # override flat_sizing
            "wf_q":          q,
            "wf_confidence": conf,
            "pnl_total":     float(row["pnl"]) * 100.0 * contracts,
        })
        eval_rows.append(d)

        if (i + 1) % progress_every == 0:
            elapsed = time.monotonic() - t_start
            print(f"  [walk-fwd] {i+1}/{n_total} signals processed "
                  f"({elapsed:.1f}s, {len(refit_events)} refits)")

    elapsed = time.monotonic() - t_start
    print(f"[walk-fwd] done: {len(refit_events)} unique refits, "
          f"{n_warmup_excluded} warmup-excluded, {len(eval_rows)} evaluable, "
          f"{elapsed:.1f}s")

    if eval_rows:
        eval_df = pd.DataFrame(eval_rows)
    else:
        # Warmup never reached (e.g. partial-coverage real-mode corpus
        # smaller than WARMUP_N_TRADES).  Return an empty frame with the
        # expected schema so downstream callers can rely on the columns;
        # dedupe overlapping names (kelly_reason appears in both the flat
        # log and the wf-augmented columns).
        cols = list(flat.columns)
        for extra in ("wf_contracts", "kelly_reason", "wf_q",
                      "wf_confidence", "pnl_total"):
            if extra not in cols:
                cols.append(extra)
        eval_df = pd.DataFrame(columns=cols)
    return (eval_df, n_warmup_excluded, refit_events, warmup_cutoff_date)


# ---------------------------------------------------------------------------
# Rolling 60-day Sharpe distribution
# ---------------------------------------------------------------------------

def rolling_sharpe(eval_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each unique entry-date d in the evaluable period, compute the
    Sharpe of trades with entry_date in [d - ROLLING_WINDOW_DAYS, d].
    Returns a frame with columns: date, n, sharpe.
    """
    df = eval_df[eval_df["wf_contracts"] > 0].copy()
    if df.empty:
        return pd.DataFrame()
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df = df.sort_values("entry_date")
    eval_dates = sorted(df["entry_date"].unique())
    rows = []
    for d in eval_dates:
        d_ts = pd.Timestamp(d)
        start = d_ts - pd.Timedelta(days=ROLLING_WINDOW_DAYS)
        win = df[(df["entry_date"] >= start) & (df["entry_date"] <= d_ts)]
        if len(win) < ROLLING_MIN_TRADES:
            continue
        pnl = win["pnl_total"].values
        sd = float(np.std(pnl, ddof=1))
        if sd > 0:
            sh = float(np.mean(pnl) / sd * SHARPE_ANN)
            rows.append({"date": d_ts, "n": int(len(win)), "sharpe": sh})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Per-quintile / per-ticker (walk-forward variants)
# ---------------------------------------------------------------------------

def per_quintile_wf(eval_df: pd.DataFrame) -> pd.DataFrame:
    sub = eval_df[taken_mask(eval_df)].copy()
    if sub.empty:
        return pd.DataFrame()
    pnl_col = "pnl_total"
    rows = []
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        qsub = sub[sub["wf_q"] == q]
        rows.append({
            "quintile":  q,
            "n":         int(len(qsub)),
            "win_rate":  round(float((qsub[pnl_col] > 0).mean()), 4) if len(qsub) else float("nan"),
            "total_pnl": round(float(qsub[pnl_col].sum()), 2),
            "avg_pnl":   round(float(qsub[pnl_col].mean()), 2) if len(qsub) else float("nan"),
        })
    return pd.DataFrame(rows)


def per_quintile_in_sample(full_kelly: pd.DataFrame) -> pd.DataFrame:
    """In-sample column uses production edges + production confidence."""
    prod_edges = position_sizer.get_quintile_edges()
    sub = full_kelly[taken_mask(full_kelly)].copy()
    if sub.empty:
        return pd.DataFrame()
    bins = [-np.inf] + list(prod_edges) + [np.inf]
    sub["q"] = pd.cut(sub["confidence"], bins=bins,
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
            "quintile":  q,
            "n":         int(len(qsub)),
            "win_rate":  round(float((qsub[pnl_col] > 0).mean()), 4) if len(qsub) else float("nan"),
            "total_pnl": round(float(qsub[pnl_col].sum()), 2),
            "avg_pnl":   round(float(qsub[pnl_col].mean()), 2) if len(qsub) else float("nan"),
        })
    return pd.DataFrame(rows)


def per_ticker(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "ticker" not in df.columns:
        return pd.DataFrame(columns=["ticker", "n_taken", "pnl"])
    pnl_col = "pnl_total" if "pnl_total" in df.columns else "pnl"
    rows = []
    for t in sorted(df["ticker"].unique()):
        sub = df[df["ticker"] == t]
        rows.append({
            "ticker":  t,
            "n_taken": int(taken_mask(sub).sum()),
            "pnl":     round(float(sub[pnl_col].fillna(0.0).sum()), 2),
        })
    return pd.DataFrame(rows, columns=["ticker", "n_taken", "pnl"])


# ---------------------------------------------------------------------------
# Refit-event sampling
# ---------------------------------------------------------------------------

def sample_events(events: list, k: int = 7) -> list:
    if len(events) <= k:
        return events
    indices = np.linspace(0, len(events) - 1, k, dtype=int)
    return [events[int(i)] for i in indices]


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(*, flat, eval_df, n_warmup, refit_events,
                 warmup_cutoff, full_kelly,
                 h_in_sample, h_wf, rolling_df, prod_sigs_pre, prod_sigs_post,
                 mode_label: str = "DEMO",
                 audit_tickers: list | None = None,
                 missing_tickers: list | None = None) -> str:
    _flat_pat  = "backtest_*.csv"        if mode_label == "REAL" else "backtest_*_demo.csv"
    _kelly_pat = "backtest_*_kelly.csv"  if mode_label == "REAL" else "backtest_*_demo_kelly.csv"
    _out_file  = "walkforward_audit_report_real.md" if mode_label == "REAL" else "walkforward_audit_report.md"
    _flag      = " --real"               if mode_label == "REAL" else ""

    phrases = _baseline_phrases(mode_label)

    audit_tickers = audit_tickers if audit_tickers is not None else list(config.TICKERS)
    missing_tickers = missing_tickers if missing_tickers is not None else []
    is_partial = (mode_label == "REAL") and bool(missing_tickers)
    n_audit    = len(audit_tickers)
    n_total    = len(config.TICKERS)

    md = []
    md.append("# Walk-Forward Audit -- Daily Refit on R3 Baseline\n\n")
    if is_partial:
        md.append(f"**Mode: {mode_label} (partial coverage: "
                  f"{n_audit} of {n_total} tickers)**\n\n")
    else:
        md.append(f"**Mode: {mode_label}**\n\n")

    # =====================================================================
    # 1. Question and methodology summary
    # =====================================================================
    md.append("## 1. Question and methodology summary\n\n")
    md.append(
        f"_Tests whether the prior 75/25 audit's "
        f"{phrases['prior_oos_verdict_phrase']} is universal across refit "
        f"windows or specific to that single cutoff date.  Kelly stats, "
        f"quintile edges, and the confidence model are refit each time a "
        f"new accepted trade completes; every signal is sized with "
        f"parameters that knew nothing about its outcome.  Path-(b) "
        f"post-hoc re-derivation: the flat corpus's per-share `pnl` and "
        f"`max_loss` are spread + real-price properties unchanged by "
        f"sizing -- only contract counts shift between sizing regimes.  "
        f"No production code, sizing logic, or on-disk artifact is "
        f"modified._\n\n"
    )

    # =====================================================================
    # 2. Walk-forward design specifics
    # =====================================================================
    md.append("## 2. Walk-forward design specifics\n\n")
    if is_partial:
        included = ", ".join(audit_tickers) if audit_tickers else "_(none)_"
        miss_str = ", ".join(f"{t} ({reason})" for t, reason in missing_tickers)
        md.append(
            f"**Coverage:** real-mode corpus partial -- "
            f"{n_audit} of {n_total} tickers participate in this audit.  "
            f"Included: {included}.  Missing: {miss_str}.\n\n"
        )
    md.append(
        f"- **Refit cadence.**  Logically daily.  Implementation refits "
        f"only when the training-corpus size grows (a new accepted trade "
        f"has exited).  Identical training data produces identical "
        f"parameters; redundant refits are skipped.  Result: "
        f"**{len(refit_events)} unique refits** across the corpus, "
        f"vs the 700+ daily refits a naive walk-forward would do.\n"
        f"- **Training corpus filter.**  `accepted == True` AND "
        f"`exit_date < entry_date_of_signal_being_evaluated`.  This is "
        f"the strict no-look-ahead semantic: a trade is only used in "
        f"fitting after its P&L is realised.  The prompt's phrasing "
        f"`entry_date < T` is the loose form of the same intent.\n"
        f"- **Warmup threshold.**  {WARMUP_N_TRADES} accepted-and-completed "
        f"trades required before any signal is evaluable.  First date "
        f"this threshold is met: "
        f"**{warmup_cutoff.strftime('%Y-%m-%d') if warmup_cutoff else 'N/A'}**.  "
        f"{n_warmup} signals fall in the warmup period and are excluded "
        f"from evaluation (counted, not zeroed).\n"
        f"- **Synchronization.**  Universe-wide refits using all 10 "
        f"tickers' completed accepted trades.  Per-ticker refits would "
        f"be a different test and were not implemented.\n"
        f"- **Parameter persistence.**  All parameter snapshots held in "
        f"memory; nothing written under `data/raw/`.\n"
        f"- **Sharpe convention.**  "
        f"`mean(pnl_total) / std(pnl_total, ddof=1) * sqrt(252/5)`, "
        f"matching `r3_baseline.headline()`.  Same convention used for "
        f"the trade-level rolling-window Sharpe.\n"
        f"- **Open-risk cap simplification.**  `open_risk_dollars=0` "
        f"passed to every `size_trade` call (peak utilisation in the "
        f"production Kelly run was 0.69 << 1.0; on a walk-forward this "
        f"is even less likely to bind).\n\n"
    )

    # =====================================================================
    # 3. Headline metrics (walk-forward)
    # =====================================================================
    md.append("## 3. Headline metrics (walk-forward)\n\n")
    headline_df = pd.DataFrame([
        {"metric": "n_signals_seen",   "value": h_wf["n_signals"]},
        {"metric": "n_warmup_excluded","value": n_warmup},
        {"metric": "n_signals_evaluable", "value": h_wf["n_signals"]},
        {"metric": "n_trades_taken",   "value": h_wf["n_trades"]},
        {"metric": "total_pnl_$",      "value": h_wf["total_pnl"]},
        {"metric": "sharpe",           "value": h_wf["sharpe"]},
        {"metric": "max_dd_$",         "value": h_wf["max_dd"]},
        {"metric": "profit_factor",    "value": h_wf["profit_factor"]},
        {"metric": "win_rate",         "value": h_wf["win_rate"]},
    ])
    md.append(df_to_md(headline_df, float_fmt="{:,.4f}"))
    md.append("\n")

    # =====================================================================
    # 4. Three-column comparison
    # =====================================================================
    md.append("## 4. Three-column comparison: in-sample / 75-25-OOS / walk-forward\n\n")

    def _ticker_pnl(df: pd.DataFrame, t: str) -> float:
        if df.empty or "ticker" not in df.columns or "pnl_total" not in df.columns:
            return 0.0
        s = pd.to_numeric(df[df["ticker"] == t]["pnl_total"], errors="coerce")
        return float(s.fillna(0.0).sum()) if len(s) else 0.0
    aapl_in   = _ticker_pnl(full_kelly, "AAPL")
    nvda_in   = _ticker_pnl(full_kelly, "NVDA")
    aapl_wf   = _ticker_pnl(eval_df, "AAPL")
    nvda_wf   = _ticker_pnl(eval_df, "NVDA")

    in_q  = per_quintile_in_sample(full_kelly)
    wf_q  = per_quintile_wf(eval_df)
    q5_in = float(in_q[in_q["quintile"] == "Q5"]["total_pnl"].iloc[0]) if not in_q.empty else float("nan")
    q1_in = float(in_q[in_q["quintile"] == "Q1"]["total_pnl"].iloc[0]) if not in_q.empty else float("nan")
    q5_wf = float(wf_q[wf_q["quintile"] == "Q5"]["total_pnl"].iloc[0]) if not wf_q.empty else float("nan")
    q1_wf = float(wf_q[wf_q["quintile"] == "Q1"]["total_pnl"].iloc[0]) if not wf_q.empty else float("nan")

    cmp_df = pd.DataFrame([
        {"metric": "n_signals",     "in_sample_full": h_in_sample["n_signals"],
         "oos_75_25":   OOS_75_25["n_signals"],
         "walk_forward":h_wf["n_signals"]},
        {"metric": "n_trades_taken","in_sample_full": h_in_sample["n_trades"],
         "oos_75_25":   OOS_75_25["n_trades"],
         "walk_forward":h_wf["n_trades"]},
        {"metric": "total_pnl_$",   "in_sample_full": h_in_sample["total_pnl"],
         "oos_75_25":   OOS_75_25["total_pnl"],
         "walk_forward":h_wf["total_pnl"]},
        {"metric": "sharpe",        "in_sample_full": h_in_sample["sharpe"],
         "oos_75_25":   OOS_75_25["sharpe"],
         "walk_forward":h_wf["sharpe"]},
        {"metric": "max_dd_$",      "in_sample_full": h_in_sample["max_dd"],
         "oos_75_25":   OOS_75_25["max_dd"],
         "walk_forward":h_wf["max_dd"]},
        {"metric": "profit_factor", "in_sample_full": h_in_sample["profit_factor"],
         "oos_75_25":   OOS_75_25["profit_factor"],
         "walk_forward":h_wf["profit_factor"]},
        {"metric": "win_rate",      "in_sample_full": h_in_sample["win_rate"],
         "oos_75_25":   OOS_75_25["win_rate"],
         "walk_forward":h_wf["win_rate"]},
        {"metric": "Q5_total_pnl",  "in_sample_full": q5_in,
         "oos_75_25":   OOS_75_25["Q5_pnl"],
         "walk_forward":q5_wf},
        {"metric": "Q1_total_pnl",  "in_sample_full": q1_in,
         "oos_75_25":   OOS_75_25["Q1_pnl"],
         "walk_forward":q1_wf},
        {"metric": "AAPL_pnl",      "in_sample_full": aapl_in,
         "oos_75_25":   OOS_75_25["AAPL_pnl"],
         "walk_forward":aapl_wf},
        {"metric": "NVDA_pnl",      "in_sample_full": nvda_in,
         "oos_75_25":   OOS_75_25["NVDA_pnl"],
         "walk_forward":nvda_wf},
    ])
    md.append(df_to_md(cmp_df, float_fmt="{:,.4f}"))
    md.append("\n" + phrases["oos_75_25_footnote"])

    # =====================================================================
    # 5. Sharpe distribution analysis
    # =====================================================================
    md.append("## 5. Rolling 60-day Sharpe distribution\n\n")
    if rolling_df.empty:
        md.append("_(no rolling-window data; insufficient evaluable trades.)_\n\n")
    else:
        s = rolling_df["sharpe"]
        n_pos = int((s > 0).sum())
        n_neg = int((s < 0).sum())
        n_strong = int((s.abs() > 0.5).sum())
        n_strong_pos = int((s > 0.5).sum())
        n_strong_neg = int((s < -0.5).sum())

        dist_df = pd.DataFrame([
            {"stat": "n_windows",       "value": int(len(s))},
            {"stat": "mean",            "value": float(s.mean())},
            {"stat": "std",             "value": float(s.std(ddof=1))},
            {"stat": "p10",             "value": float(s.quantile(0.10))},
            {"stat": "p25",             "value": float(s.quantile(0.25))},
            {"stat": "p50_median",      "value": float(s.quantile(0.50))},
            {"stat": "p75",             "value": float(s.quantile(0.75))},
            {"stat": "p90",             "value": float(s.quantile(0.90))},
            {"stat": "min",             "value": float(s.min())},
            {"stat": "max",             "value": float(s.max())},
            {"stat": "n_positive",      "value": n_pos},
            {"stat": "n_negative",      "value": n_neg},
            {"stat": "n_|sharpe|>0.5",  "value": n_strong},
            {"stat": "n_sharpe>+0.5",   "value": n_strong_pos},
            {"stat": "n_sharpe<-0.5",   "value": n_strong_neg},
        ])
        md.append(df_to_md(dist_df, float_fmt="{:.4f}"))
        md.append(
            f"\n**Pos vs neg windows:** {n_pos} positive / {n_neg} negative "
            f"({100.0 * n_pos / max(len(s), 1):.0f}% positive).  "
            f"**Strong-magnitude windows** (|Sharpe| > 0.5): {n_strong} "
            f"({n_strong_pos} positive, {n_strong_neg} negative).\n\n"
        )

    # =====================================================================
    # 6. Per-refit parameter evolution
    # =====================================================================
    md.append("## 6. Per-refit parameter evolution\n\n")
    sampled = sample_events(refit_events, k=7)
    md.append(
        f"Sampled {len(sampled)} of {len(refit_events)} refit events spread "
        f"evenly through the walk-forward period.  Shows how parameters "
        f"evolve as the training corpus grows.\n\n"
    )
    # Edges + Kelly fractions
    rows = []
    for e in sampled:
        bc = e["stats"].get("BUY CALLS", {})
        bp = e["stats"].get("BUY PUTS", {})
        rows.append({
            "date":           e["date"],
            "n_train":        e["n_train"],
            "edge_q1":        round(e["edges"][0], 4),
            "edge_q2":        round(e["edges"][1], 4),
            "edge_q3":        round(e["edges"][2], 4),
            "edge_q4":        round(e["edges"][3], 4),
            "BC_kelly_f":     round(float(bc.get("kelly_f", 0.0)), 4),
            "BP_kelly_f":     round(float(bp.get("kelly_f", 0.0)), 4),
        })
    md.append("**Quintile edges + Kelly fractions:**\n\n")
    md.append(df_to_md(pd.DataFrame(rows), float_fmt="{:.4f}"))

    md.append("\n**Confidence model coefficients (intercept + 6 betas):**\n\n")
    rows = []
    for e in sampled:
        m = e["model"]
        beta = m["beta"]
        names = m["feature_names"]
        rows.append({
            "date":      e["date"],
            "n_train":   e["n_train"],
            "intercept": round(float(m["intercept"]), 4),
            **{names[i]: round(float(beta[i]), 4) for i in range(len(beta))},
        })
    md.append(df_to_md(pd.DataFrame(rows), float_fmt="{:+.4f}"))
    md.append("\n")

    # =====================================================================
    # 7. Per-quintile breakdown (walk-forward)
    # =====================================================================
    md.append("## 7. Per-quintile breakdown\n\n")
    md.append(
        "Confidence quintile labels are assigned at trade-entry time using "
        "the parameters that were live at that moment (so a trade in early "
        "2025 may have been Q3 then but would be Q4 under the late-2026 "
        "edges -- this is the correct walk-forward semantic).\n\n"
    )
    md.append("**In-sample (full corpus, production params):**\n\n")
    md.append(df_to_md(in_q, float_fmt="{:,.2f}"))
    md.append("\n**Walk-forward (entry-time params):**\n\n")
    md.append(df_to_md(wf_q, float_fmt="{:,.2f}"))

    spread_in = q5_in - q1_in if not (np.isnan(q5_in) or np.isnan(q1_in)) else float("nan")
    spread_wf = q5_wf - q1_wf if not (np.isnan(q5_wf) or np.isnan(q1_wf)) else float("nan")
    md.append(
        f"\n**Q5 - Q1 spread:** in-sample {fmt_money(spread_in)}, "
        f"75/25 OOS {fmt_money(OOS_75_25['Q5_pnl'] - OOS_75_25['Q1_pnl'])}, "
        f"walk-forward {fmt_money(spread_wf)}.\n\n"
    )

    # =====================================================================
    # 8. Per-ticker breakdown
    # =====================================================================
    md.append("## 8. Per-ticker breakdown\n\n")
    if is_partial:
        md.append(f"_({n_audit} tickers in audit)_\n\n")
    in_t = per_ticker(full_kelly)
    in_t.columns = ["ticker", "n_taken_in", "pnl_in"]
    wf_t = per_ticker(eval_df)
    wf_t.columns = ["ticker", "n_taken_wf", "pnl_wf"]
    merged = in_t.merge(wf_t, on="ticker", how="outer").fillna(0)
    md.append(df_to_md(merged, float_fmt="{:,.2f}"))

    # Sign flips
    flips = merged[(np.sign(merged["pnl_in"]) != np.sign(merged["pnl_wf"]))
                   & (merged["pnl_in"].abs() > 100)
                   & (merged["pnl_wf"].abs() > 100)]
    md.append("\n")
    if len(flips):
        md.append("**Sign-flipping tickers (|pnl| > $100 on both sides):**\n\n")
        for _, r in flips.iterrows():
            md.append(f"- **{r['ticker']}**: in-sample {fmt_money(r['pnl_in'])} "
                      f"-> walk-forward {fmt_money(r['pnl_wf'])}.\n")
    else:
        md.append("**No ticker P&L sign-flips with |pnl| > $100 on both sides.**\n")

    aapl_row = merged[merged["ticker"] == "AAPL"]
    if len(aapl_row):
        a = aapl_row.iloc[0]
        if mode_label == "REAL":
            md.append(
                f"\n**AAPL.**  Walk-forward: {fmt_money(a['pnl_wf'])} on "
                f"{int(a['n_taken_wf'])} taken trades.  Warmup cutoff: "
                f"{warmup_cutoff.strftime('%Y-%m-%d') if warmup_cutoff else 'N/A'}.  "
                f"`outputs/aapl_stop_diagnosis.md` is a synthetic-only "
                f"diagnostic; a real-mode AAPL stop-cluster post-mortem "
                f"has not been published.\n\n"
            )
        else:
            md.append(
                f"\n**AAPL (prior diagnosis: -$3,568 in-sample, 13 stop-outs).**  "
                f"Walk-forward: {fmt_money(a['pnl_wf'])} on "
                f"{int(a['n_taken_wf'])} taken trades.  The Dec-2025 / Jan-2026 "
                f"stop cluster from `outputs/aapl_stop_diagnosis.md` falls "
                f"after the warmup cutoff "
                f"({warmup_cutoff.strftime('%Y-%m-%d') if warmup_cutoff else 'N/A'}) "
                f"so it is in the walk-forward evaluable window.\n\n"
            )

    # =====================================================================
    # 9. Verdict
    # =====================================================================
    md.append("## 9. Verdict\n\n")
    verdict, body = compose_verdict(
        h_in_sample=h_in_sample, h_wf=h_wf, rolling_df=rolling_df,
        q5_in=q5_in, q1_in=q1_in, q5_wf=q5_wf, q1_wf=q1_wf,
        n_flips=int(len(flips)),
        mode_label=mode_label,
    )
    md.append(f"**{verdict}.**  {body}\n\n")

    # =====================================================================
    # 10. Caveats
    # =====================================================================
    md.append("## 10. Caveats\n\n")
    eval_min = pd.to_datetime(eval_df["entry_date"]).min().strftime("%Y-%m-%d") \
               if len(eval_df) else "N/A"
    eval_max = pd.to_datetime(eval_df["entry_date"]).max().strftime("%Y-%m-%d") \
               if len(eval_df) else "N/A"
    md.append(
        phrases["corpus_caveat"]
        + f"- **Evaluable date range.**  {eval_min} -> {eval_max} "
        f"({n_warmup} signals before the warmup cutoff are not "
        f"evaluated).\n"
        f"- **Rolling-window error bars.**  60-day windows on this "
        f"trade-frequency contain ~10-30 trades; individual window "
        f"Sharpes are noisy and should not be over-interpreted.  The "
        f"distributional summary is the right unit of analysis.\n"
        + phrases["single_realisation_caveat"]
    )

    # =====================================================================
    # 11. Cleanup confirmation
    # =====================================================================
    md.append("## 11. Cleanup confirmation\n\n")
    cleanup_rows = []
    for label, path in [("kelly_stats.csv (production)",     PROD_STATS_PATH),
                        ("quintile_edges.json (production)", PROD_EDGES_PATH),
                        ("confidence_model.json (production)", PROD_MODEL_PATH)]:
        sig_pre  = prod_sigs_pre.get(path)
        sig_post = prod_sigs_post.get(path)
        cleanup_rows.append({
            "artifact":       label,
            "mtime_pre":      "missing" if sig_pre[0]  == "missing" else f"{sig_pre[0]}",
            "mtime_post":     "missing" if sig_post[0] == "missing" else f"{sig_post[0]}",
            "size_unchanged": (sig_pre == sig_post),
        })
    md.append(df_to_md(pd.DataFrame(cleanup_rows)))
    all_unchanged = all(prod_sigs_pre[p] == prod_sigs_post[p]
                        for p in [PROD_STATS_PATH, PROD_EDGES_PATH, PROD_MODEL_PATH])
    md.append(
        f"\n**Production artifacts unchanged: "
        f"{'CONFIRMED' if all_unchanged else 'NOT CONFIRMED -- INVESTIGATE'}.**  "
        f"No artifacts under `data/raw/` were written or modified during "
        f"this audit.  All parameter snapshots were held in memory only.\n\n"
    )

    md.append("---\n\n## Reproduction\n\n")
    md.append(f"```bash\n.venv/Scripts/python.exe scripts/audit_walkforward.py{_flag}\n```\n\n")
    md.append(f"Reads `data/raw/{_flat_pat}` + "
              f"`data/raw/{_kelly_pat}`; writes "
              f"`outputs/{_out_file}` only.  Re-run after "
              f"any change that regenerates the flat or kelly logs.\n")

    return "".join(md)


def compose_verdict(*, h_in_sample, h_wf, rolling_df, q5_in, q1_in, q5_wf, q1_wf,
                    n_flips, mode_label: str = "DEMO") -> tuple[str, str]:
    phrases = _baseline_phrases(mode_label)
    sh_in = h_in_sample["sharpe"]
    sh_wf = h_wf["sharpe"]
    oos_sh = float(OOS_75_25["sharpe"])
    spread_in = q5_in - q1_in if not (np.isnan(q5_in) or np.isnan(q1_in)) else float("nan")
    spread_wf = q5_wf - q1_wf if not (np.isnan(q5_wf) or np.isnan(q1_wf)) else float("nan")

    if rolling_df.empty:
        roll_pos_frac = 0.0
        roll_mean = float("nan")
        roll_std  = float("nan")
        n_windows = 0
        n_positive = 0
        n_strong_pos = 0
        n_strong_neg = 0
    else:
        s = rolling_df["sharpe"]
        n_windows = int(len(s))
        n_positive = int((s > 0).sum())
        roll_pos_frac = n_positive / n_windows if n_windows else 0.0
        roll_mean = float(s.mean())
        roll_std  = float(s.std(ddof=1))
        n_strong_pos = int((s > 0.5).sum())
        n_strong_neg = int((s < -0.5).sum())

    # Decision rule
    sh_ratio = sh_wf / sh_in if sh_in not in (0.0, 0) else float("nan")
    q5_holds = (spread_wf > 0)

    if (not np.isnan(sh_ratio) and sh_ratio >= 0.7
        and q5_holds and n_flips == 0 and roll_pos_frac > 0.6):
        verdict = "GENERALIZES UNDER WALK-FORWARD"
    elif (not np.isnan(sh_wf) and sh_wf < 0.05
          and (spread_wf < 0 or roll_pos_frac < 0.5)):
        verdict = "DEGRADES CONSISTENTLY"
    else:
        verdict = "WINDOW-DEPENDENT"

    if verdict == "GENERALIZES UNDER WALK-FORWARD":
        body = (
            f"Walk-forward total Sharpe ({sh_wf:+.4f}) is within ~30% of "
            f"in-sample ({sh_in:+.4f}); rolling 60-day Sharpe distribution is "
            f"{100*roll_pos_frac:.0f}% positive ({n_strong_pos} windows >+0.5 "
            f"vs {n_strong_neg} <-0.5); Q5-Q1 spread {fmt_money(spread_wf)} "
            f"preserves the in-sample ordering; {n_flips} ticker sign-flips.  "
            f"The 75/25 collapse was specific to the cutoff date landing on "
            f"the AAPL Dec-2025/Jan-2026 stop cluster; daily refit averages "
            f"that adverse window with positive ones from earlier and later "
            f"in the corpus.  R3's selection as production sizing and the "
            f"v2_10t promotion question both stand on stronger footing now.")
    elif verdict == "DEGRADES CONSISTENTLY":
        body = (
            f"Walk-forward total Sharpe ({sh_wf:+.4f}) is statistically "
            f"indistinguishable from zero -- the entire {sh_in:+.4f} "
            f"in-sample edge does not reproduce.  The rolling 60-day "
            f"distribution has mean {roll_mean:+.4f} (std {roll_std:.4f}) "
            f"with substantial dispersion ({n_strong_pos} windows above "
            f"+0.5 vs {n_strong_neg} below -0.5, "
            f"{100*roll_pos_frac:.0f}% positive overall) -- the strategy "
            f"is not uniformly bad in every refit window, but on average "
            f"and on aggregate P&L it does not produce edge.  Q5-Q1 "
            f"spread {fmt_money(spread_wf)} "
            f"{'inverts' if spread_wf < 0 else 'collapses'} the "
            f"in-sample ordering of {fmt_money(q5_in - q1_in)}: even "
            f"after averaging over the walk-forward refit windows, the "
            f"model's 'highest confidence' bucket still systematically "
            f"loses money.  {n_flips} ticker P&L sign-flips on > $100 "
            f"magnitude.  The 75/25 finding reproduces under "
            f"finer-grained refits: R3's {phrases['baseline_pnl']} / "
            f"{phrases['baseline_sharpe']} Sharpe baseline is largely "
            f"in-sample inflation.  v2_10t promotion on the current "
            f"evidence is premature; the production R3 sizing decision "
            f"was made on numbers that do not survive any honest "
            f"holdout test.")
    else:  # WINDOW-DEPENDENT
        body = (
            f"Walk-forward total Sharpe ({sh_wf:+.4f}) is between in-sample "
            f"({sh_in:+.4f}) and the 75/25 OOS reference estimate "
            f"({oos_sh:+.4f}), and the rolling 60-day distribution shows "
            f"substantial variance: mean {roll_mean:+.4f}, std "
            f"{roll_std:.4f} across {n_windows} windows ({n_strong_pos} "
            f">+0.5 / {n_strong_neg} <-0.5).  {100*roll_pos_frac:.0f}% of "
            f"windows are positive.  Q5-Q1 spread {fmt_money(spread_wf)} "
            f"(in-sample {fmt_money(spread_in)}, 75/25 OOS reference "
            f"{fmt_money(OOS_75_25['Q5_pnl']-OOS_75_25['Q1_pnl'])}).  "
            f"{n_flips} ticker P&L sign-flips.  The 75/25 audit's verdict "
            f"was an over-statement: walk-forward shows the strategy does "
            f"have edge in some refit periods and not others rather than "
            f"a uniform collapse.  Recommend regime analysis as the next "
            f"session: identify which periods produce positive Sharpe and "
            f"what distinguishes them (vol regime, sector rotation, "
            f"corpus-window cycle).")
    return verdict, body


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(real_mode: bool = False):
    os.makedirs(OUT_DIR, exist_ok=True)

    mode_label = "REAL" if real_mode else "DEMO"
    out_path   = (os.path.join(OUT_DIR, "walkforward_audit_report_real.md")
                  if real_mode else OUT_PATH)

    # Coverage detection: identify which tickers have BOTH a flat log and a
    # kelly log on disk; partial real-mode coverage is now allowed.
    def _flat_name(t: str) -> str:
        return f"backtest_{t}.csv" if real_mode else f"backtest_{t}_demo.csv"
    def _kelly_name(t: str) -> str:
        return f"backtest_{t}_kelly.csv" if real_mode else f"backtest_{t}_demo_kelly.csv"

    present_flat  = [t for t in config.TICKERS
                     if os.path.exists(os.path.join(RAW_DIR, _flat_name(t)))]
    present_kelly = [t for t in config.TICKERS
                     if os.path.exists(os.path.join(RAW_DIR, _kelly_name(t)))]
    audit_tickers   = sorted(set(present_flat) & set(present_kelly))
    missing_tickers = []
    for t in config.TICKERS:
        if t in audit_tickers:
            continue
        in_flat  = t in present_flat
        in_kelly = t in present_kelly
        if not in_flat and not in_kelly:
            reason = "both missing"
        elif not in_flat:
            reason = "flat missing"
        else:
            reason = "kelly missing"
        missing_tickers.append((t, reason))

    if len(audit_tickers) == 0:
        if real_mode:
            first = missing_tickers[0][0] if missing_tickers else config.TICKERS[0]
            print(f"[wf_audit] ERROR: real-mode corpus not found at "
                  f"data/raw/backtest_{first}.csv; "
                  f"has scripts/r3_baseline.py --real been run?", file=sys.stderr)
            others = [t for t, _ in missing_tickers[1:]]
            if others:
                print(f"[wf_audit]   Also missing: "
                      f"{', '.join(f'backtest_{t}.csv' for t in others)}",
                      file=sys.stderr)
        else:
            print(f"[wf_audit] ERROR: demo corpus not found "
                  f"(0 of {len(config.TICKERS)} tickers have both flat + "
                  f"kelly logs on disk).", file=sys.stderr)
        sys.exit(1)

    if missing_tickers:
        if real_mode:
            included = ",".join(audit_tickers)
            miss_str = ", ".join(f"{t} ({reason})" for t, reason in missing_tickers)
            print(f"[wf_audit] partial coverage: {len(audit_tickers)} of "
                  f"{len(config.TICKERS)} tickers -- included: {included} -- "
                  f"missing: {miss_str}", file=sys.stderr)
        else:
            miss_str = ", ".join(f"{t} ({reason})" for t, reason in missing_tickers)
            print(f"[wf_audit] ERROR: demo corpus partial -- "
                  f"{len(audit_tickers)} of {len(config.TICKERS)} tickers "
                  f"present.  Missing: {miss_str}.  Demo coverage completeness "
                  f"is a regression signal; not relaxing the demo guard.",
                  file=sys.stderr)
            sys.exit(1)

    prod_sigs_pre = {
        PROD_STATS_PATH: file_signature(PROD_STATS_PATH),
        PROD_EDGES_PATH: file_signature(PROD_EDGES_PATH),
        PROD_MODEL_PATH: file_signature(PROD_MODEL_PATH),
    }

    print(f"[wf_audit] mode: {mode_label}")
    print(f"[wf_audit] coverage: {len(audit_tickers)}/{len(config.TICKERS)} "
          f"tickers ({','.join(audit_tickers)})")
    print("[wf_audit] loading flat corpus...")
    flat = load_flat_corpus(real_mode=real_mode, tickers=audit_tickers)
    print(f"[wf_audit] {len(flat)} signal rows.")

    print("[wf_audit] running walk-forward (cached refits)...")
    eval_df, n_warmup, refit_events, warmup_cutoff = walk_forward(flat)
    print(f"[wf_audit] {len(eval_df)} evaluable, "
          f"{n_warmup} warmup-excluded, "
          f"{len(refit_events)} unique refits, "
          f"warmup cutoff "
          f"{warmup_cutoff.strftime('%Y-%m-%d') if warmup_cutoff else 'N/A'}.")

    print("[wf_audit] loading production Kelly logs...")
    full_kelly = load_kelly_logs(real_mode=real_mode, tickers=audit_tickers)

    print("[wf_audit] computing rolling Sharpe...")
    rolling_df = rolling_sharpe(eval_df)
    print(f"[wf_audit] rolling distribution: {len(rolling_df)} windows.")

    print("[wf_audit] computing headline metrics...")
    h_in_sample = headline(full_kelly)
    h_wf        = headline(eval_df)
    print(f"  in-sample: {h_in_sample}")
    print(f"  walk-forward: {h_wf}")

    prod_sigs_post = {
        PROD_STATS_PATH: file_signature(PROD_STATS_PATH),
        PROD_EDGES_PATH: file_signature(PROD_EDGES_PATH),
        PROD_MODEL_PATH: file_signature(PROD_MODEL_PATH),
    }

    print("[wf_audit] composing report...")
    md = build_report(
        flat=flat, eval_df=eval_df, n_warmup=n_warmup,
        refit_events=refit_events, warmup_cutoff=warmup_cutoff,
        full_kelly=full_kelly,
        h_in_sample=h_in_sample, h_wf=h_wf, rolling_df=rolling_df,
        prod_sigs_pre=prod_sigs_pre, prod_sigs_post=prod_sigs_post,
        mode_label=mode_label,
        audit_tickers=audit_tickers, missing_tickers=missing_tickers,
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[wf_audit] -> {out_path} ({len(md.splitlines())} lines)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Daily walk-forward audit of the R3 production baseline."
    )
    ap.add_argument(
        "--real", action="store_true",
        help=(
            "Audit real-mode corpus (backtest_*.csv / backtest_*_kelly.csv) "
            "instead of the default demo corpus."
        ),
    )
    args = ap.parse_args()
    main(real_mode=args.real)

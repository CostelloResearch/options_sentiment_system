# =============================================================================
# signals/signal_decay.py -- Forward-return decay curves per signal segment
#
# PURPOSE
# -------
# A signal either has edge or it doesn't.  This module answers two questions
# for every historical signal:
#
#   1. How does the edge decay with holding period?  (1, 3, 5, 10, 20 days)
#   2. Which subsets of signals have NO edge at any horizon?
#
# Subsets segmented on:
#   * signal type           (BUY CALLS / BUY PUTS / SELL PUTS / SELL CALLS)
#   * confidence quintile   (Q1 lowest to Q5 highest)
#   * sentiment source      (news_only / sec_only / combined)
#
# THE RETURN METRIC
# -----------------
# We use the DIRECTIONAL underlying return, not the option P&L, because:
#   * Option P&L depends on entry strike/IV/width/friction -- confounds the
#     question "did the signal predict the stock?"
#   * Underlying return isolates the signal-vs-price relationship
#   * If a signal has no edge at the underlying level, the spread can't
#     magically create edge -- it can only leverage or hedge what's already
#     there.
#
# For bullish signals (BUY CALLS, SELL PUTS):
#     dir_ret(h) = (S_{t+h} - S_t) / S_t
# For bearish signals (BUY PUTS, SELL CALLS):
#     dir_ret(h) = -(S_{t+h} - S_t) / S_t   (we want price to fall)
#
# Positive `dir_ret` always means "the trade would have benefited from the
# move".  Zero = flat; negative = adverse move.
#
# RISK-ADJUSTED RETURN
# --------------------
# For each (segment, horizon) we compute:
#     mean_ret       -- arithmetic mean of dir_ret
#     std_ret        -- std of dir_ret
#     risk_adj       -- mean_ret / std_ret (per-trade Sharpe ratio)
#     annualised     -- risk_adj * sqrt(252 / horizon)
# The "optimal horizon" for a segment is the one maximising `risk_adj`.
# We deliberately ignore total return in favour of risk-adjusted because
# a long-horizon segment can look great on mean-return alone but have
# massive variance -- Kelly sizing (and real risk management) care about
# the distribution, not the mean.
#
# EDGE DISABLEMENT RULE
# ---------------------
# A segment is flagged "DISABLE" if:
#     mean_ret <= 0 at EVERY horizon  OR
#     max risk_adj across horizons < 0.05  (below 5% per-trade Sharpe is
#                                           in the noise for n<~200)
# Both checks must be interpretable -- we print the sample size next to
# every row so reviewers can gut-check whether "no edge" is a real finding
# or a small-sample artifact.
#
# OUTPUT
# ------
# Writes outputs/signal_decay_analysis.md with tables per segmentation.
# =============================================================================

from __future__ import annotations

import os
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Signal direction classification -- bearish signals get their return sign
# flipped so that POSITIVE dir_ret always means "trade went the right way".
_BULLISH = {"BUY CALLS", "SELL PUTS"}
_BEARISH = {"BUY PUTS", "SELL CALLS"}

# Default holding-period horizons (trading days).  Longer horizons are
# progressively less relevant because our spreads expire in 35 DTE and
# our time_stop fires at 21 DTE.
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)

# Confidence quintile labels (low -> high)
QUINTILE_LABELS = ["Q1 (lowest)", "Q2", "Q3", "Q4", "Q5 (highest)"]

# Disablement thresholds -- see module docstring
MIN_RISK_ADJ_FOR_EDGE = 0.05


# ---------------------------------------------------------------------------
# Price history helpers
# ---------------------------------------------------------------------------

def _raw_dir() -> str:
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "raw"
    ))


def _load_price_history(ticker: str, period: str = "5y") -> pd.DataFrame:
    """
    Thin wrapper over backtest.engine.load_price_history.  Kept as a local
    function so tests can monkey-patch and this module stays importable
    without yfinance side effects.
    """
    from backtest.engine import load_price_history
    df = load_price_history(ticker, period=period)
    df.index = pd.DatetimeIndex(df.index).normalize()
    return df


# ---------------------------------------------------------------------------
# Forward-return computation
# ---------------------------------------------------------------------------

def _directional_sign(signal: str) -> int:
    """+1 for bullish signals, -1 for bearish, 0 for anything else."""
    if signal in _BULLISH:
        return +1
    if signal in _BEARISH:
        return -1
    return 0


def compute_forward_returns(
    trades:    pd.DataFrame,
    price_by_ticker: dict,
    horizons:  Iterable[int] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    """
    Enrich a trade log with forward-return columns per horizon.

    For each trade row, look up the ticker's price history, find the entry
    date, and read the close `h` trading days later.  Rows whose ticker
    isn't in `price_by_ticker` get NaN.  Rows whose horizon extends past
    the history also get NaN.

    Adds columns `dir_ret_{h}d` (directional, signed so + = good).
    """
    df = trades.copy()
    df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.normalize()

    horizons = list(horizons)
    for h in horizons:
        df[f"dir_ret_{h}d"] = np.nan

    # Process ticker-by-ticker so each ticker's history is accessed once
    for ticker, grp in df.groupby("ticker"):
        hist = price_by_ticker.get(ticker)
        if hist is None or hist.empty:
            continue

        closes = hist["close"].copy()
        # Use trading-day index of the history so `h` steps forward means
        # `h` trading days, not calendar.
        idx = closes.index
        pos_lookup = {ts: i for i, ts in enumerate(idx)}

        for ridx, row in grp.iterrows():
            entry = row["entry_date"]
            sign  = _directional_sign(row["signal"])
            if entry not in pos_lookup or sign == 0:
                continue

            i = pos_lookup[entry]
            S0 = float(closes.iloc[i])
            if S0 <= 0:
                continue

            for h in horizons:
                j = i + h
                if j >= len(closes):
                    continue
                S1 = float(closes.iloc[j])
                raw_ret = (S1 - S0) / S0
                df.at[ridx, f"dir_ret_{h}d"] = sign * raw_ret

    return df


# ---------------------------------------------------------------------------
# Segmentation helpers
# ---------------------------------------------------------------------------

def _add_confidence_quintile(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign each accepted trade to a confidence quintile.  Uses qcut with
    duplicates='drop' so identical confidence values don't crash the bin
    edges (common when confidence clusters).
    """
    if "confidence" not in df.columns or df.empty:
        df["confidence_quintile"] = np.nan
        return df
    try:
        df["confidence_quintile"] = pd.qcut(
            df["confidence"], q=5,
            labels=QUINTILE_LABELS, duplicates="drop",
        )
    except ValueError:
        # Fewer unique values than bins -> put everything in one bucket
        df["confidence_quintile"] = "Q1 (lowest)"
    return df


def _ensure_sentiment_source(df: pd.DataFrame) -> pd.DataFrame:
    """
    Backfill a `sentiment_source` column if the log was produced before
    we started tagging.  Defaults to 'news_only' -- the v1 pipeline only
    had news, so this is the conservative guess.
    """
    if "sentiment_source" not in df.columns:
        df["sentiment_source"] = "news_only"
    df["sentiment_source"] = df["sentiment_source"].fillna("news_only")
    return df


# ---------------------------------------------------------------------------
# Decay table core
# ---------------------------------------------------------------------------

def _segment_stats(
    sub:       pd.DataFrame,
    horizons:  Iterable[int],
) -> pd.DataFrame:
    """
    Given a subset of enriched trades, return one row per horizon with
    n, mean, std, and risk-adjusted stats.
    """
    rows = []
    for h in horizons:
        col = f"dir_ret_{h}d"
        if col not in sub.columns:
            continue
        series = sub[col].dropna()
        n = int(len(series))
        if n == 0:
            rows.append({
                "horizon_days": h, "n": 0, "mean_ret": np.nan,
                "std_ret": np.nan, "risk_adj": np.nan, "annualised": np.nan,
            })
            continue
        m = float(series.mean())
        s = float(series.std(ddof=1)) if n >= 2 else 0.0
        risk_adj = (m / s) if s > 0 else 0.0
        ann = risk_adj * np.sqrt(252.0 / h) if h > 0 else 0.0
        rows.append({
            "horizon_days": h,
            "n":            n,
            "mean_ret":     round(m, 5),
            "std_ret":      round(s, 5),
            "risk_adj":     round(risk_adj, 4),
            "annualised":   round(ann, 4),
        })
    return pd.DataFrame(rows)


def decay_by_segment(
    enriched:      pd.DataFrame,
    segment_col:   str,
    horizons:      Iterable[int] = DEFAULT_HORIZONS,
) -> dict:
    """
    Return {segment_value: stats_df} for the given grouping column.
    """
    horizons = list(horizons)
    if segment_col not in enriched.columns:
        return {}
    out = {}
    for val, grp in enriched.groupby(segment_col, observed=False):
        out[str(val)] = _segment_stats(grp, horizons)
    return out


# ---------------------------------------------------------------------------
# Edge flagging
# ---------------------------------------------------------------------------

def classify_edge(stats_df: pd.DataFrame,
                  min_risk_adj: float = MIN_RISK_ADJ_FOR_EDGE) -> dict:
    """
    Decide whether a segment has edge.

    Returns
    -------
    dict with:
        best_horizon    horizon_days maximising risk_adj (or None if no data)
        max_risk_adj    the risk_adj at best_horizon
        max_mean_ret    the largest mean_ret across horizons
        has_edge        True if max_risk_adj >= min_risk_adj AND at least
                        one horizon has mean_ret > 0
        recommendation  'TRADE' or 'DISABLE'
    """
    if stats_df is None or stats_df.empty:
        return {"best_horizon": None, "max_risk_adj": np.nan,
                "max_mean_ret": np.nan, "has_edge": False,
                "recommendation": "DISABLE (no data)"}

    valid = stats_df.dropna(subset=["risk_adj"])
    if valid.empty:
        return {"best_horizon": None, "max_risk_adj": np.nan,
                "max_mean_ret": np.nan, "has_edge": False,
                "recommendation": "DISABLE (no data)"}

    best = valid.loc[valid["risk_adj"].idxmax()]
    max_risk_adj = float(best["risk_adj"])
    max_mean     = float(valid["mean_ret"].max())
    has_edge = (max_risk_adj >= min_risk_adj) and (max_mean > 0)

    return {
        "best_horizon":   int(best["horizon_days"]),
        "max_risk_adj":   round(max_risk_adj, 4),
        "max_mean_ret":   round(max_mean, 5),
        "has_edge":       has_edge,
        "recommendation": "TRADE" if has_edge else "DISABLE",
    }


# ---------------------------------------------------------------------------
# Markdown writer
# ---------------------------------------------------------------------------

def _fmt_pct(x: float) -> str:
    return "-" if pd.isna(x) else f"{x*100:+.2f}%"


def _fmt_f(x: float) -> str:
    return "-" if pd.isna(x) else f"{x:+.3f}"


def _stats_to_md_table(stats_df: pd.DataFrame) -> str:
    if stats_df is None or stats_df.empty:
        return "_(no data)_\n"
    lines = [
        "| horizon | n | mean ret | std | risk-adj | annualised |",
        "|--------:|--:|---------:|----:|---------:|-----------:|",
    ]
    for _, r in stats_df.iterrows():
        lines.append(
            f"| {int(r['horizon_days']):>2}d | {int(r['n']):>4d} "
            f"| {_fmt_pct(r['mean_ret'])} | {_fmt_pct(r['std_ret'])} "
            f"| {_fmt_f(r['risk_adj'])} | {_fmt_f(r['annualised'])} |"
        )
    return "\n".join(lines) + "\n"


def write_report(
    by_signal:      dict,
    by_quintile:    dict,
    by_source:      dict,
    disabled:       list,
    total_trades:   int,
    horizons:       Iterable[int],
    out_path:       Optional[str] = None,
) -> str:
    out_path = out_path or os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "outputs", "signal_decay_analysis.md"
    ))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    lines = []
    lines.append("# Signal Decay Analysis\n")
    lines.append(f"- Horizons tested: {', '.join(str(h)+'d' for h in horizons)}")
    lines.append(f"- Total trades in corpus: **{total_trades}**")
    lines.append(f"- Edge threshold: risk-adjusted return >= "
                 f"{MIN_RISK_ADJ_FOR_EDGE} AND mean > 0 at some horizon\n")

    if disabled:
        lines.append("## Signals flagged for DISABLE\n")
        for d in disabled:
            lines.append(f"- **{d['segment']}** -- "
                         f"{d['reason']} "
                         f"(best risk_adj = {_fmt_f(d['max_risk_adj'])}, "
                         f"best mean = {_fmt_pct(d['max_mean_ret'])})")
        lines.append("")
    else:
        lines.append("## Signals flagged for DISABLE\n")
        lines.append("_None -- every segment with data shows some edge_\n")

    # ---- Signal-type section ----
    lines.append("## Decay by signal type\n")
    if not by_signal:
        lines.append("_(no data)_\n")
    for sig, stats in by_signal.items():
        verdict = classify_edge(stats)
        lines.append(f"### {sig}  -> **{verdict['recommendation']}**")
        if verdict["best_horizon"] is not None:
            lines.append(f"Optimal horizon: **{verdict['best_horizon']}d**  "
                         f"(risk_adj = {_fmt_f(verdict['max_risk_adj'])}, "
                         f"mean = {_fmt_pct(verdict['max_mean_ret'])})\n")
        lines.append(_stats_to_md_table(stats))

    # ---- Confidence-quintile section ----
    lines.append("## Decay by confidence quintile\n")
    if not by_quintile:
        lines.append("_(no data)_\n")
    for q, stats in by_quintile.items():
        verdict = classify_edge(stats)
        lines.append(f"### {q}  -> **{verdict['recommendation']}**")
        if verdict["best_horizon"] is not None:
            lines.append(f"Optimal horizon: **{verdict['best_horizon']}d**  "
                         f"(risk_adj = {_fmt_f(verdict['max_risk_adj'])}, "
                         f"mean = {_fmt_pct(verdict['max_mean_ret'])})\n")
        lines.append(_stats_to_md_table(stats))

    # ---- Sentiment-source section ----
    lines.append("## Decay by sentiment source\n")
    if not by_source:
        lines.append("_(no data)_\n")
    for src, stats in by_source.items():
        verdict = classify_edge(stats)
        lines.append(f"### {src}  -> **{verdict['recommendation']}**")
        if verdict["best_horizon"] is not None:
            lines.append(f"Optimal horizon: **{verdict['best_horizon']}d**  "
                         f"(risk_adj = {_fmt_f(verdict['max_risk_adj'])}, "
                         f"mean = {_fmt_pct(verdict['max_mean_ret'])})\n")
        lines.append(_stats_to_md_table(stats))

    # ---- Interpretation notes ----
    lines.append("## Notes on interpretation\n")
    lines.append(
        "- `mean ret` is the average **directional** underlying return "
        "(positive = trade went the right way regardless of bull/bear).\n"
        "- `risk-adj` = mean / std per trade.  Multiply by sqrt(252/horizon) "
        "for an annualised Sharpe-like number.\n"
        "- Small-sample warning: segments with n < 30 have risk_adj errors "
        "comparable to the point estimate itself; treat as directional at best.\n"
        "- Disablement rule is intentionally lenient (0.05 risk-adj floor) "
        "to avoid killing a signal on a 50-trade sample -- real go/no-go "
        "should use out-of-sample data.\n"
    )

    text = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return out_path


# ---------------------------------------------------------------------------
# End-to-end runner
# ---------------------------------------------------------------------------

def run_decay_analysis(
    trades:        pd.DataFrame,
    tickers:       Optional[Iterable[str]] = None,
    horizons:      Iterable[int] = DEFAULT_HORIZONS,
    out_path:      Optional[str] = None,
    price_cache:   Optional[dict] = None,
) -> dict:
    """
    Full pipeline: filter to accepted trades, compute forward returns,
    segment three ways, flag disablement, write the markdown report.

    Returns a summary dict with all the segment verdicts so the caller
    can print them inline.
    """
    horizons = list(horizons)

    # Only accepted trades -- rejected signals have no realised return to
    # measure in the OPTIONS book, but we're measuring UNDERLYING return
    # so rejected signals actually ARE valid observations.  We include
    # them to keep sample size up.  The edge is about the signal, not
    # whether spread_builder liked the chain.
    df = trades.copy()
    df = df.dropna(subset=["signal", "entry_date"])
    df = df[df["signal"].isin(list(_BULLISH | _BEARISH))]

    if tickers is None:
        tickers = sorted(df["ticker"].unique())

    # Load prices per ticker (cache so re-runs skip yfinance)
    price_by_ticker = dict(price_cache or {})
    for t in tickers:
        if t not in price_by_ticker:
            try:
                price_by_ticker[t] = _load_price_history(t)
            except Exception as e:
                print(f"[signal_decay] price load failed for {t}: {e}")

    enriched = compute_forward_returns(df, price_by_ticker, horizons=horizons)
    enriched = _add_confidence_quintile(enriched)
    enriched = _ensure_sentiment_source(enriched)

    by_signal   = decay_by_segment(enriched, "signal", horizons)
    by_quintile = decay_by_segment(enriched, "confidence_quintile", horizons)
    by_source   = decay_by_segment(enriched, "sentiment_source", horizons)

    # Collect any segments flagged DISABLE
    disabled = []
    for label_fmt, dct in [("signal={}", by_signal),
                           ("confidence={}", by_quintile),
                           ("source={}", by_source)]:
        for seg, stats in dct.items():
            verdict = classify_edge(stats)
            if not verdict["has_edge"]:
                disabled.append({
                    "segment":      label_fmt.format(seg),
                    "max_risk_adj": verdict["max_risk_adj"],
                    "max_mean_ret": verdict["max_mean_ret"],
                    "reason":       (
                        "no horizon produced mean > 0"
                        if (pd.isna(verdict["max_mean_ret"])
                            or verdict["max_mean_ret"] <= 0)
                        else f"best risk-adj {verdict['max_risk_adj']:.3f} "
                             f"< {MIN_RISK_ADJ_FOR_EDGE}"
                    ),
                })

    path = write_report(
        by_signal, by_quintile, by_source, disabled,
        total_trades=len(enriched), horizons=horizons, out_path=out_path,
    )

    return {
        "enriched":     enriched,
        "by_signal":    by_signal,
        "by_quintile":  by_quintile,
        "by_source":    by_source,
        "disabled":     disabled,
        "report_path":  path,
        "price_cache":  price_by_ticker,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_all_logs(pattern: str = "backtest_*.csv") -> pd.DataFrame:
    import glob
    files = glob.glob(os.path.join(_raw_dir(), pattern))
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f, parse_dates=["entry_date", "exit_date"]))
        except Exception:
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


if __name__ == "__main__":
    trades = _load_all_logs()
    if trades.empty:
        print("No backtest logs found.  Run the backtest first.")
        sys.exit(1)
    result = run_decay_analysis(trades)
    print(f"[signal_decay] Wrote report -> {result['report_path']}")
    if result["disabled"]:
        print("\nSegments flagged for DISABLE:")
        for d in result["disabled"]:
            print(f"  - {d['segment']}: {d['reason']}")
    else:
        print("\nNo segments flagged for DISABLE.")

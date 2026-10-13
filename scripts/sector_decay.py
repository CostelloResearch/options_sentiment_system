# =============================================================================
# scripts/sector_decay.py -- Sector-segmented signal decay
#
# PURPOSE
# -------
# Step 8 of the 2026-04-25 universe rebuild: the critical empirical test of
# whether the BUY CALLS / BUY PUTS / SELL PUTS edge documented on the old
# 5-ticker tech-heavy universe is consistent across sectors -- or whether
# it was always a tech-only artifact.  If a signal type produces edge in
# Technology only and is flat-or-negative in Energy / Financials / Bonds,
# the original conclusion in PROJECT_STATE was overfit to the universe.
#
# WHAT IT DOES
# ------------
# 1. Loads every flat backtest log (`backtest_{TICKER}_demo.csv`) for the
#    tickers in config.TICKERS only -- no _kelly / _r1 / _r2 / _r3
#    duplicates that would multi-count the same signals.
# 2. Adds a `sector` column from config.SECTOR_MAP and an `asset_class`
#    column from config.ASSET_CLASS.
# 3. Calls signal_decay.compute_forward_returns to attach forward-return
#    columns at each horizon.
# 4. Reports `decay_by_segment` results across:
#       - signal type (existing)
#       - sector  (NEW)
#       - asset_class (NEW)
#       - sector x signal cross-tab (NEW) -- the headline output
# 5. Writes outputs/sector_decay_analysis.md.
#
# OUTPUT
# ------
# outputs/sector_decay_analysis.md -- the per-sector edge table the user
# asked for.  The "is the edge tech-only?" verdict comes from comparing the
# Technology row to every other sector at the same signal type.
# =============================================================================

from __future__ import annotations

import os
import sys
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from signals import signal_decay


OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "outputs"))
RAW_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))


def _load_flat_logs_for(tickers, real_mode: bool = False):
    """Concatenate flat-sizing backtest logs for `tickers` only.  Skips Kelly/R*
    suffixed variants so we don't multi-count the same signals."""
    frames = []
    for t in tickers:
        fname = f"backtest_{t}.csv" if real_mode else f"backtest_{t}_demo.csv"
        p = os.path.join(RAW_DIR, fname)
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
        else:
            print(f"[sector_decay] WARNING: missing flat log {fname}", file=sys.stderr)
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


def _segment_summary(seg_dict):
    """Reduce a {label: stats_df} dict from decay_by_segment into a single
    table: label, best_horizon, max_risk_adj, max_mean_ret, n_at_best,
    has_edge.  This is the headline read."""
    rows = []
    for label, stats in seg_dict.items():
        v = signal_decay.classify_edge(stats)
        n_at_best = 0
        if v["best_horizon"] is not None and not stats.empty:
            mask = stats["horizon_days"] == v["best_horizon"]
            if mask.any():
                n_at_best = int(stats.loc[mask, "n"].iloc[0])
        rows.append({
            "segment":         label,
            "best_horizon_d":  v["best_horizon"],
            "n_at_best":       n_at_best,
            "max_risk_adj":    v["max_risk_adj"],
            "max_mean_ret":    v["max_mean_ret"],
            "verdict":         v["recommendation"],
        })
    return pd.DataFrame(rows)


def _sector_signal_crosstab(enriched, horizons=(5, 10, 20)):
    """For each (sector, signal) cell, compute mean directional return and n
    at the canonical horizons.  A row of all-positive numbers means the
    sector carries the signal; a mostly-negative row exposes a tech-only
    artifact."""
    if "sector" not in enriched.columns:
        return pd.DataFrame()

    rows = []
    for (sec, sig), grp in enriched.groupby(["sector", "signal"], observed=True):
        row = {"sector": sec, "signal": sig, "n_signals": int(len(grp))}
        for h in horizons:
            col = f"dir_ret_{h}d"
            s = grp[col].dropna() if col in grp.columns else pd.Series([], dtype=float)
            row[f"mean_ret_{h}d"] = round(float(s.mean()), 5) if len(s) else np.nan
            row[f"n_{h}d"]        = int(len(s))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["signal", "sector"]).reset_index(drop=True)


def main(tickers, horizons=(1, 3, 5, 10, 20), real_mode: bool = False):
    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"[sector_decay] tickers: {tickers}")

    trades = _load_flat_logs_for(tickers, real_mode=real_mode)
    if trades.empty:
        print("[sector_decay] No flat logs on disk; run "
              "segregated_kelly_report.py first.")
        return

    # Restrict to bullish / bearish signals (signal_decay drops NEUTRAL etc)
    trades = trades.dropna(subset=["signal", "entry_date"])
    trades = trades[trades["signal"].isin(["BUY CALLS", "BUY PUTS",
                                           "SELL CALLS", "SELL PUTS"])]
    print(f"[sector_decay] {len(trades)} signal rows across "
          f"{trades['ticker'].nunique()} tickers.")

    # Add sector / asset_class
    trades["sector"]      = trades["ticker"].map(config.SECTOR_MAP)
    trades["asset_class"] = trades["ticker"].map(config.ASSET_CLASS)
    n_unmapped = int(trades["sector"].isna().sum())
    if n_unmapped:
        print(f"[sector_decay] WARNING: {n_unmapped} rows lack a sector "
              f"mapping (tickers: "
              f"{sorted(trades.loc[trades['sector'].isna(), 'ticker'].unique())})")

    # Pull price history per ticker (uses backtest.engine via signal_decay)
    price_cache = {}
    for t in tickers:
        try:
            price_cache[t] = signal_decay._load_price_history(t)
        except Exception as e:
            print(f"[sector_decay] price load failed for {t}: {e}")

    enriched = signal_decay.compute_forward_returns(
        trades, price_cache, horizons=horizons,
    )
    enriched = signal_decay._add_confidence_quintile(enriched)

    # Segmentations
    by_signal = signal_decay.decay_by_segment(enriched, "signal", horizons)
    by_sector = signal_decay.decay_by_segment(enriched, "sector", horizons)
    by_asset  = signal_decay.decay_by_segment(enriched, "asset_class", horizons)
    by_sec_q  = signal_decay.decay_by_segment(enriched, "confidence_quintile",
                                              horizons)

    # Sector x signal cross-tab -- the headline empirical test
    cross = _sector_signal_crosstab(enriched, horizons=(5, 10, 20))

    # Pretty headline summaries
    sig_sum = _segment_summary(by_signal)
    sec_sum = _segment_summary(by_sector)
    asset_sum = _segment_summary(by_asset)

    print("\n[sector_decay] BY SIGNAL")
    print(sig_sum.to_string(index=False))
    print("\n[sector_decay] BY SECTOR")
    print(sec_sum.to_string(index=False))
    print("\n[sector_decay] BY ASSET CLASS")
    print(asset_sum.to_string(index=False))
    print("\n[sector_decay] SECTOR x SIGNAL CROSSTAB (mean dir_ret)")
    print(cross.to_string(index=False))

    # ---- Markdown ----
    md_name = "sector_decay_analysis_real.md" if real_mode else "sector_decay_analysis.md"
    md_path = os.path.join(OUT_DIR, md_name)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Signal Decay -- Per-Sector Segmentation\n\n")
        f.write(f"_2026-04-25 universe rebuild: 10 tickers across "
                f"{trades['sector'].nunique()} sectors and "
                f"{trades['asset_class'].nunique()} asset classes._\n\n")
        f.write("**Critical test:** is the historical BUY CALLS / BUY PUTS / "
                "SELL PUTS edge documented on the 5-ticker tech-heavy universe "
                "consistent across sectors, or was it concentrated in tech?\n\n")

        f.write("## 1. Headline by signal (universe-wide)\n\n")
        f.write(_df_to_md(sig_sum))
        f.write("\n")

        f.write("## 2. Headline by sector\n\n")
        f.write(_df_to_md(sec_sum))
        f.write("\n")

        f.write("## 3. Headline by asset class\n\n")
        f.write(_df_to_md(asset_sum))
        f.write("\n")

        f.write("## 4. Sector x Signal cross-tab (headline)\n\n")
        f.write("`mean_ret_{h}d` = mean directional underlying return at "
                "horizon h, signed so + = trade went the right way. A row "
                "with positive numbers across horizons is a sector that "
                "carries that signal type. A mostly-negative row exposes a "
                "tech-only artifact.\n\n")
        f.write(_df_to_md(cross))
        f.write("\n")

        # Per-sector decay tables (full horizon detail)
        f.write("## 5. Per-sector decay curves\n\n")
        for sector, stats_df in by_sector.items():
            v = signal_decay.classify_edge(stats_df)
            f.write(f"### {sector}  -> **{v['recommendation']}**\n\n")
            if v["best_horizon"] is not None:
                f.write(f"Optimal horizon: **{v['best_horizon']}d**  "
                        f"(risk_adj = {v['max_risk_adj']:+.3f}, "
                        f"mean = {v['max_mean_ret']*100:+.2f}%)\n\n")
            f.write(signal_decay._stats_to_md_table(stats_df))
            f.write("\n")

        f.write("## 6. Notes\n\n")
        f.write(
            "- Sample sizes per sector are smaller than the universe-wide "
            "decay table by ~10x.  Treat sector verdicts as directional, not "
            "definitive; the small-sample warning from "
            "`outputs/signal_decay_analysis.md` applies a fortiori per "
            "sector.\n"
            "- The cross-tab uses underlying directional returns, not option "
            "P&L, so structure choices (60 DTE BUY PUTS, 0.25-delta short, "
            "etc.) don't confound the comparison across sectors.\n"
            "- An honest read: if BUY PUTS shows positive mean_ret in "
            "Technology and ~zero everywhere else, that is the answer.  Do "
            "not paper over it by widening confidence intervals.\n"
        )

    print(f"\n[sector_decay] -> {md_path}")
    return {"by_signal": by_signal, "by_sector": by_sector,
            "by_asset": by_asset, "cross": cross, "md_path": md_path}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=config.TICKERS)
    ap.add_argument("--real", action="store_true")
    args = ap.parse_args()
    main(args.tickers, real_mode=args.real)

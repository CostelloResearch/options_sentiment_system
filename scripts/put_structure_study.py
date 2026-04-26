# =============================================================================
# scripts/put_structure_study.py -- BUY PUTS structure comparison
#
# PREMISE
# -------
# The decay analysis showed BUY PUTS has genuine UNDERLYING edge:
#     horizon  mean_ret  risk_adj
#        20d   +1.44%    +0.218
# but the FLAT backtest closed that signal at -0.16% per trade -- the edge
# was getting burned by spread execution (theta, short-leg strike choice,
# width too tight, etc).  So the SIGNAL is good; the STRUCTURE is wrong.
#
# This script tests four alternative BEAR-PUT constructions against the
# same set of historical BUY PUTS signal days (pulled from the flat log
# so we don't have to re-run the whole ticker loop):
#
#   A  20 DTE debit  |  long ~0.55 delta, short 0.35 delta  -- less theta drag
#   B  60 DTE debit  |  long ~0.55 delta, short 0.25 delta  -- more time, less theta%
#   C  45 DTE debit  |  wider $10 width, short 0.30 delta   -- better risk/reward
#   D  45 DTE single long put at 0.50 delta                 -- no short leg cap
#
# Structures A, B, C are still vertical BEAR_PUT_DEBIT spreads built with
# the existing spread_builder/engine primitives -- we just override DTE
# and delta targets.  Structure D replaces the spread with a naked long
# put: richer payoff, smaller max loss per contract (just the debit),
# but uncapped upside (the underlying can only fall to 0).
#
# METRICS
# -------
# Per variant we report:
#   n_trades       accepted after the variant's risk-reward filter
#   total_pnl      sum of pnl_total across variants (dollars)
#   avg_pnl        mean dollar P&L per trade
#   win_rate       fraction with pnl > 0
#   sharpe         mean(pnl) / std(pnl) * sqrt(252/HOLD_DAYS)
#   max_dd         peak-to-trough of cumulative P&L
#   mean_ret_pct   mean pnl_pct (% of max_loss) -- normalised return
#
# We DON'T adjust position sizing between variants (all use the baseline
# 1-contract sizing) because mixing Kelly with structure comparison would
# confound the result.  The structure study is about per-contract edge.
#
# OUTPUT
# ------
#   stdout               : punch-list table
#   outputs/put_structure_study.md : markdown report with the full table +
#                                     recommendation
# =============================================================================

import os
import sys
import math
import datetime
import argparse

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from scipy.stats import norm

# Reuse BS pricing/delta from spread_builder so the study uses the exact
# same pricing model the live spreads use.
from signals.spread_builder import (
    bs_price, bs_delta,
    simulate_spread_pnl,
    RISK_FREE_RATE,
    FRICTION_FRAC,
    DEBIT_MAX_COST_FRAC,
    STOP_LOSS_DEBIT_FRAC,
    PROFIT_TARGET_FRAC,
    TIME_STOP_DTE,
)
from backtest.engine import (
    _atm_strike, _strike_grid, _pick_strike_by_delta,
    load_price_history, STRIKE_STEP,
)


OUT_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "outputs"
))
RAW_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "data", "raw"
))


# ---------------------------------------------------------------------------
# Variant specifications
# ---------------------------------------------------------------------------
# Each dict is the knob set for one BEAR_PUT_DEBIT or single-leg-put trade.
# structure: 'spread' => build 2-leg bear put debit; 'single_leg' => long put.
VARIANTS = {
    "A": {
        "structure":       "spread",
        "dte":             20,
        "long_delta":      0.55,
        "short_delta":     0.35,
        "width_override":  None,      # use engine's default width rule
        "label":           "20 DTE spread, short 0.35delta",
    },
    "B": {
        "structure":       "spread",
        "dte":             60,
        "long_delta":      0.55,
        "short_delta":     0.25,
        "width_override":  None,
        "label":           "60 DTE spread, short 0.25delta",
    },
    "C": {
        "structure":       "spread",
        "dte":             45,
        "long_delta":      0.55,
        "short_delta":     0.30,
        "width_override":  10.00,     # $10 wide
        "label":           "45 DTE spread, $10 width",
    },
    "D": {
        "structure":       "single_leg",
        "dte":             45,
        "long_delta":      0.50,
        "label":           "45 DTE single long put 0.50delta",
    },
    # Baseline = what the current engine builds for BUY PUTS.
    "Baseline": {
        "structure":       "spread",
        "dte":             35,
        "long_delta":      0.55,
        "short_delta":     0.30,
        "width_override":  None,
        "label":           "Current (35 DTE, short 0.30delta)",
    },
}


# ---------------------------------------------------------------------------
# Structure builders
# ---------------------------------------------------------------------------

def _build_spread_variant(
    S: float, sigma: float, entry_date: datetime.date,
    variant: dict,
) -> dict:
    """
    Build a BEAR_PUT_DEBIT spread using the variant's DTE/delta/width.
    Returns the same dict shape as engine._build_backtest_spread so we can
    reuse simulate_spread_pnl unchanged.
    """
    DTE = int(variant["dte"])
    T   = DTE / 365.0
    r   = RISK_FREE_RATE
    exp_date = entry_date + datetime.timedelta(days=DTE)

    long_delta_tgt  = float(variant["long_delta"])
    short_delta_tgt = float(variant["short_delta"])
    width_override  = variant.get("width_override")

    # BEAR_PUT_DEBIT: long higher-strike put (|delta| ~0.55), short lower-strike
    long_K = _pick_strike_by_delta(S, T, r, sigma, False, long_delta_tgt, "long")

    if width_override is not None:
        # Force the width exactly; ignore delta target for short leg.
        short_K = round((long_K - width_override) / STRIKE_STEP) * STRIKE_STEP
    else:
        # Pick short strike by delta target, then snap to grid.
        short_K = _pick_strike_by_delta(S, T, r, sigma, False, short_delta_tgt, "short")
        # Safety: ensure short_K < long_K (bear put order)
        if short_K >= long_K:
            short_K = long_K - STRIKE_STEP

    width = abs(long_K - short_K)
    if width <= 0:
        return {"accepted": False, "rejection_reason": "degenerate width=0"}

    long_fair  = bs_price(S, long_K,  T, r, sigma, is_call=False)
    short_fair = bs_price(S, short_K, T, r, sigma, is_call=False)
    long_eff   = long_fair  * (1 + FRICTION_FRAC)
    short_eff  = short_fair * (1 - FRICTION_FRAC)

    net = long_eff - short_eff     # debit (we pay)
    max_profit = max(width - net, 0.0)
    max_loss   = net
    breakeven  = long_K - net

    accepted = True
    rejection = ""
    if net > DEBIT_MAX_COST_FRAC * width:
        accepted = False
        rejection = f"net debit {net:.2f} > {DEBIT_MAX_COST_FRAC*100:.0f}% of width {width:.2f}"

    return {
        "strategy_type":       "BEAR_PUT_DEBIT",
        "expiration":          exp_date.isoformat(),
        "dte_entry":           DTE,
        "long_strike":         float(long_K),
        "long_delta":          float(bs_delta(S, long_K,  T, r, sigma, False)),
        "long_price":          float(long_eff),
        "short_strike":        float(short_K),
        "short_delta":         float(bs_delta(S, short_K, T, r, sigma, False)),
        "short_price":         float(short_eff),
        "width":               float(width),
        "net_debit_or_credit": float(net),
        "max_profit":          float(max_profit),
        "max_loss":            float(max_loss),
        "breakeven":           float(breakeven),
        "contracts":           1 if accepted else 0,
        "total_risk":          float(max_loss * 100.0) if accepted else 0.0,
        "total_max_profit":    float(max_profit * 100.0) if accepted else 0.0,
        "accepted":            bool(accepted),
        "rejection_reason":    rejection,
    }


def _build_single_leg_put(
    S: float, sigma: float, entry_date: datetime.date,
    variant: dict,
) -> dict:
    """
    Build a single LONG PUT.  No short leg, so "max_loss" is the entire
    debit (100% loss if it expires OTM).  Max profit bounded by K.
    """
    DTE = int(variant["dte"])
    T   = DTE / 365.0
    r   = RISK_FREE_RATE
    exp_date = entry_date + datetime.timedelta(days=DTE)

    target_delta = float(variant["long_delta"])
    K = _pick_strike_by_delta(S, T, r, sigma, False, target_delta, "long")

    fair = bs_price(S, K, T, r, sigma, is_call=False)
    debit = fair * (1 + FRICTION_FRAC)       # we pay this

    # There's no "risk/reward filter" for a single leg in the same sense --
    # instead, reject if the debit is unreasonably large relative to the
    # spot (same sanity as the spread filter: > 15% of spot is expensive).
    accepted = True
    rejection = ""
    if debit > 0.15 * S:
        accepted = False
        rejection = f"debit {debit:.2f} > 15% of spot {S:.2f}"

    return {
        "strategy_type":       "LONG_PUT",
        "expiration":          exp_date.isoformat(),
        "dte_entry":           DTE,
        "long_strike":         float(K),
        "long_delta":          float(bs_delta(S, K, T, r, sigma, False)),
        "long_price":          float(debit),
        # No short leg -- zero out so the simulator's 2-leg math gives
        # "spread value = long_value - 0 = long_value".  Strike at a sentinel
        # that will never go ITM (very low) so its BS price stays near zero.
        "short_strike":        max(0.01, float(K) - 500.0),
        "short_delta":         0.0,
        "short_price":         0.0,
        "width":               float(K),    # max profit bound = strike
        "net_debit_or_credit": float(debit),
        "max_profit":          float(max(K - debit, 0.0)),
        "max_loss":            float(debit),
        "breakeven":           float(K - debit),
        "contracts":           1 if accepted else 0,
        "total_risk":          float(debit * 100.0) if accepted else 0.0,
        "total_max_profit":    float(max(K - debit, 0.0) * 100.0) if accepted else 0.0,
        "accepted":            bool(accepted),
        "rejection_reason":    rejection,
    }


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _simulate_variant(
    structure: dict,
    price_df:  pd.DataFrame,
    entry_dt:  pd.Timestamp,
) -> dict:
    """
    Walk the trade forward using spread_builder's simulate_spread_pnl.
    Works for both spread and single-leg because we shape the single-leg
    trade as a (long_K, short_K~0) "spread" -- the short leg's BS price
    stays ~0 throughout so it contributes nothing to the daily value.
    """
    if not structure.get("accepted"):
        return {"pnl": 0.0, "pnl_pct": 0.0, "pnl_total": 0.0,
                "exit_reason": "rejected", "days_held": 0}

    exp_date = datetime.date.fromisoformat(structure["expiration"])
    mask = (price_df.index >= entry_dt) & \
           (price_df.index <= pd.Timestamp(exp_date))
    window = price_df.loc[mask]
    if window.empty:
        return {"pnl": 0.0, "pnl_pct": 0.0, "pnl_total": 0.0,
                "exit_reason": "no_forward_data", "days_held": 0}

    price_ser = window["close"]
    iv_ser    = window["rolling_vol"]
    sim = simulate_spread_pnl(
        structure, price_ser, iv_ser,
        r=RISK_FREE_RATE, entry_date=entry_dt.date(),
    )
    if "error" in sim:
        return {"pnl": 0.0, "pnl_pct": 0.0, "pnl_total": 0.0,
                "exit_reason": sim["error"], "days_held": 0}

    pnl_total = float(sim.get("pnl_total", 0.0))
    max_loss  = float(structure["max_loss"])
    pnl_per_sh = pnl_total / 100.0
    pnl_pct   = (pnl_per_sh / max_loss * 100.0) if max_loss > 0 else 0.0

    return {
        "pnl":         round(pnl_per_sh, 4),
        "pnl_pct":     round(pnl_pct, 2),
        "pnl_total":   round(pnl_total, 2),
        "exit_reason": sim.get("exit_reason", "expiration"),
        "days_held":   int(sim.get("days_held") or 0),
    }


# ---------------------------------------------------------------------------
# Study orchestration
# ---------------------------------------------------------------------------

def _load_flat_logs(tickers, demo: bool) -> pd.DataFrame:
    pfx = "_demo" if demo else ""
    frames = []
    for t in tickers:
        p = os.path.join(RAW_DIR, f"backtest_{t}{pfx}.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _price_cache(tickers) -> dict:
    """Cache price history per ticker so we don't re-download 4 times."""
    cache = {}
    for t in tickers:
        cache[t] = load_price_history(t, period="5y")
        cache[t].index = pd.DatetimeIndex(cache[t].index).normalize()
    return cache


def run(tickers, demo: bool) -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)

    print("=" * 72)
    print("PUT STRUCTURE STUDY")
    print("=" * 72)
    flat = _load_flat_logs(tickers, demo)
    if flat.empty:
        print("[study] No flat-sizing logs on disk; run the flat backtest first.")
        return {}
    buy_puts = flat[flat["signal"] == "BUY PUTS"].copy()
    # We need the raw spot + sigma for each entry date; the flat log
    # already has S_entry.  For sigma we pull from the price cache via
    # rolling_vol because the log doesn't have it.
    if buy_puts.empty:
        print("[study] No BUY PUTS signals in flat log.")
        return {}
    print(f"[study] Re-simulating {len(buy_puts)} BUY PUTS signals per variant...")

    price_cache = _price_cache(sorted(buy_puts["ticker"].unique()))

    results = {}
    for vkey, vspec in VARIANTS.items():
        sims = []
        for _, row in buy_puts.iterrows():
            t = str(row["ticker"])
            entry_dt = pd.Timestamp(row["entry_date"]).normalize()
            pdf = price_cache.get(t)
            if pdf is None or entry_dt not in pdf.index:
                continue
            S = float(pdf.loc[entry_dt, "close"])
            sigma = float(pdf.loc[entry_dt, "rolling_vol"])
            if sigma <= 0 or np.isnan(sigma):
                continue

            if vspec["structure"] == "spread":
                struct = _build_spread_variant(S, sigma, entry_dt.date(), vspec)
            else:
                struct = _build_single_leg_put(S, sigma, entry_dt.date(), vspec)

            sim = _simulate_variant(struct, pdf, entry_dt)
            sims.append({
                "ticker":     t,
                "entry_date": entry_dt.date(),
                "accepted":   bool(struct.get("accepted", False)),
                "max_loss":   float(struct.get("max_loss", 0.0)),
                **sim,
            })
        df = pd.DataFrame(sims)
        results[vkey] = df

    # --- Aggregate ---
    summary_rows = []
    for vkey, df in results.items():
        spec = VARIANTS[vkey]
        if df.empty:
            summary_rows.append({"variant": vkey, "label": spec["label"],
                                 "n_accepted": 0})
            continue
        acc = df[df["accepted"]]
        n = len(acc)
        if n == 0:
            summary_rows.append({"variant": vkey, "label": spec["label"],
                                 "n_accepted": 0})
            continue
        pnl    = acc["pnl_total"].astype(float)
        pnlpct = acc["pnl_pct"].astype(float)
        cum    = pnl.cumsum()
        dd     = float((cum - cum.cummax()).min())
        shp    = (float(pnl.mean() / pnl.std(ddof=1)) * np.sqrt(252.0 / 5.0)
                  if pnl.std(ddof=1) > 0 else 0.0)
        summary_rows.append({
            "variant":      vkey,
            "label":        spec["label"],
            "n_accepted":   int(n),
            "n_rejected":   int(len(df) - n),
            "total_pnl":    round(float(pnl.sum()), 2),
            "avg_pnl":      round(float(pnl.mean()), 2),
            "win_rate":     round(float((pnl > 0).mean()), 4),
            "mean_ret_pct": round(float(pnlpct.mean()), 2),
            "sharpe":       round(float(shp), 4),
            "max_dd":       round(float(dd), 2),
        })

    summary = pd.DataFrame(summary_rows)
    print("\n" + summary.to_string(index=False))

    # --- Pick winner by total_pnl among non-empty ---
    winner = None
    if not summary.empty and "total_pnl" in summary.columns:
        non_empty = summary[summary["n_accepted"] > 0].copy()
        if not non_empty.empty:
            winner = non_empty.sort_values("total_pnl", ascending=False).iloc[0]
            print(f"\n[study] Winner by total P&L: {winner['variant']}  "
                  f"({winner['label']})  total_pnl={winner['total_pnl']:+.2f}")

    # --- Markdown report ---
    md = os.path.join(OUT_DIR, "put_structure_study.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("# BUY PUTS Structure Study\n\n")
        f.write("_Premise: the decay analysis found BUY PUTS has underlying "
                "edge (+1.44% at 20d) but the default 35-DTE / 0.30delta bear-put "
                "spread loses money on execution.  This study compares "
                "alternative structures on the SAME set of BUY PUTS signal "
                "dates from the flat backtest._\n\n")

        f.write("## Results\n\n")
        # Hand-rolled markdown table (avoid tabulate dep)
        cols = list(summary.columns)
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("|" + "|".join("---" for _ in cols) + "|\n")
        for _, r in summary.iterrows():
            cells = []
            for c in cols:
                v = r.get(c, "")
                if isinstance(v, (int, np.integer)):
                    cells.append(f"{int(v)}")
                elif isinstance(v, (float, np.floating)):
                    cells.append("-" if pd.isna(v) else f"{float(v):.4f}")
                else:
                    cells.append(str(v))
            f.write("| " + " | ".join(cells) + " |\n")

        if winner is not None:
            f.write(f"\n## Recommendation\n\n")
            f.write(f"**Variant {winner['variant']}** -- "
                    f"_{winner['label']}_ -- delivered the highest total P&L "
                    f"({winner['total_pnl']:+.2f}) with Sharpe "
                    f"{winner['sharpe']:+.4f}.\n\n")
            f.write(f"Comparison to Baseline (35 DTE / 0.30delta short):\n")
            bl = summary[summary["variant"] == "Baseline"]
            if not bl.empty:
                bl = bl.iloc[0]
                f.write(f"  - Baseline total_pnl = {bl.get('total_pnl', 0):+.2f}, "
                        f"win_rate = {bl.get('win_rate', 0):.4f}\n")
                f.write(f"  - Winner   total_pnl = {winner['total_pnl']:+.2f}, "
                        f"win_rate = {winner['win_rate']:.4f}\n")
    print(f"\n[study] report -> {md}")

    return {"summary": summary, "per_variant": results, "winner_variant":
            (winner["variant"] if winner is not None else None)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=config.TICKERS)
    ap.add_argument("--real", action="store_true")
    args = ap.parse_args()

    run(tickers=args.tickers, demo=not args.real)

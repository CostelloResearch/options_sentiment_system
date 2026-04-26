# =============================================================================
# scripts/regime_comparison.py -- Three-regime bucket-allocation comparison
#
# PURPOSE
# -------
# Compare three candidate fixes for the BUY PUTS bucket saturation bug
# identified in segregated_kelly_report.md (58% of BUY PUTS signals blocked,
# Q5 inverts, -$3,215 P&L vs flat +$33,192).
#
#   REGIME 1  Raise BUY PUTS bucket to 4.5% (from 3.0%) at the cost of the
#             credit-spread reserves.  Hypothesis: more capacity fixes the
#             adverse-selection problem.
#
#   REGIME 2  Keep current buckets but shorten BUY PUTS to 45 DTE / $10 width
#             (Variant C from put_structure_study).  Hypothesis: faster
#             turnover eliminates saturation without touching allocations.
#
#   REGIME 3  Disable strategy buckets entirely; size per-trade by confidence
#             quintile (Q1 0.1% -> Q5 0.8%).  Hypothesis: letting signal
#             density determine exposure sidesteps the bucket problem.
#
# METHODOLOGY
# -----------
# All three regimes reuse the existing flat corpus on disk (500-day demo run,
# 5 tickers).  Kelly stats are rebuilt once from that corpus and reused.
# Confidence quintile edges (for regime 3) are computed once from the same
# flat corpus so they're fixed across runs.
#
# Each regime is run by temporarily monkey-patching the relevant module
# attribute(s):
#   R1: position_sizer.STRATEGY_BUCKETS
#   R2: engine._build_backtest_spread (BUY PUTS override only)
#   R3: position_sizer.size_trade (quintile-based, no buckets)
# Originals are restored between runs so the regimes are independent.
#
# Prices are cached in-process so the 15-ticker-run loop doesn't hammer
# yfinance 15 times.
#
# USAGE
# -----
#   python scripts/regime_comparison.py
#   python scripts/regime_comparison.py --skip-run   # reuse _r1/_r2/_r3 logs
# =============================================================================

from __future__ import annotations

import os
import sys
import math
import argparse
import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from backtest import engine
from signals import position_sizer
from signals.spread_builder import (
    bs_price, bs_delta,
    RISK_FREE_RATE,
    FRICTION_FRAC, DEBIT_MAX_COST_FRAC,
    ACCOUNT_NOTIONAL, RISK_PER_TRADE_FRAC,
)


OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "outputs"))
RAW_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))


# ---------------------------------------------------------------------------
# Regime configs
# ---------------------------------------------------------------------------

REGIME1_BUCKETS = {
    "BUY PUTS":   0.0450,
    "BUY CALLS":  0.0100,
    "SELL PUTS":  0.0025,
    "SELL CALLS": 0.0025,
}

# Variant C from put_structure_study: 45 DTE / $10 width / long 0.55d, short 0.30d
REGIME2_DTE         = 45
REGIME2_WIDTH       = 10.0
REGIME2_LONG_DELTA  = 0.55

# Quintile -> per-trade risk fraction
REGIME3_QUINTILE_FRAC = {
    "Q1": 0.001,
    "Q2": 0.002,
    "Q3": 0.003,
    "Q4": 0.005,
    "Q5": 0.008,
}


# ---------------------------------------------------------------------------
# Log I/O
# ---------------------------------------------------------------------------

def _load_suffix(tickers, suffix: str) -> pd.DataFrame:
    frames = []
    for t in tickers:
        p = os.path.join(RAW_DIR, f"backtest_{t}_demo{suffix}.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _pnl_series(df: pd.DataFrame) -> pd.Series:
    if "pnl_total" in df.columns and df["pnl_total"].notna().any():
        return df["pnl_total"].fillna(0.0)
    return df["pnl"].fillna(0.0) * 100.0


def _taken_mask(df: pd.DataFrame) -> pd.Series:
    """Accepted-and-not-rejected-for-sizing mask (a 'real' trade)."""
    acc = df.get("accepted", False).astype(bool)
    kr  = df.get("kelly_reason", pd.Series([""] * len(df))).astype(str).fillna("")
    return acc & (~kr.isin(["rejected_by_kelly",
                            "bucket_full",
                            "portfolio_risk_cap",
                            "rejected_risk_reward"]))


def headline(df: pd.DataFrame, label: str) -> dict:
    if df.empty:
        return {"regime": label, "n_signals": 0, "n_trades": 0,
                "total_pnl": 0.0, "sharpe": 0.0, "max_dd": 0.0,
                "profit_factor": 0.0, "win_rate": 0.0}
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


def buy_puts_util(df: pd.DataFrame) -> dict:
    """BUY PUTS bucket utilization + block rate (portfolio cap for R3)."""
    if df.empty or "bucket_cap_dollars" not in df.columns:
        return {}
    bp = df[(df["signal"] == "BUY PUTS") & (df["bucket_cap_dollars"] > 0)].copy()
    if bp.empty:
        return {"n_evaluations": 0}
    bp["utilization"] = bp["bucket_used_before"] / bp["bucket_cap_dollars"]
    kr = bp.get("kelly_reason", pd.Series([""] * len(bp))).astype(str).fillna("")
    blocked = kr.isin(["bucket_full", "portfolio_risk_cap"])
    return {
        "bucket_cap_$":     round(float(bp["bucket_cap_dollars"].iloc[0]), 2),
        "n_evaluations":    int(len(bp)),
        "mean_utilization": round(float(bp["utilization"].mean()), 4),
        "peak_utilization": round(float(bp["utilization"].max()),  4),
        "n_blocked":        int(blocked.sum()),
        "pct_blocked":      round(float(blocked.mean()), 4),
    }


def quintile_table(df: pd.DataFrame, q_edges=None) -> pd.DataFrame:
    """
    Q1..Q5 P&L after sizing.  If q_edges is provided we use fixed bins (so
    the table is comparable across regimes); otherwise pd.qcut on this df.
    """
    if df.empty or "confidence" not in df.columns:
        return pd.DataFrame()
    taken = df[_taken_mask(df)].copy()
    if taken.empty:
        return pd.DataFrame()
    if q_edges is not None:
        # fixed bins: outer +-inf so every conf value lands in some bucket
        bins   = [-np.inf] + list(q_edges) + [np.inf]
        labels = ["Q1", "Q2", "Q3", "Q4", "Q5"]
        taken["q"] = pd.cut(taken["confidence"], bins=bins, labels=labels,
                            include_lowest=True)
    else:
        try:
            taken["q"] = pd.qcut(taken["confidence"], 5,
                                 labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
                                 duplicates="drop")
        except ValueError:
            return pd.DataFrame()
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


def trades_per_strategy(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    taken = _taken_mask(df)
    return (df.loc[taken, "signal"]
              .value_counts()
              .rename_axis("signal")
              .reset_index(name="n_trades"))


# ---------------------------------------------------------------------------
# REGIME 2: Variant-C BUY PUTS override
# ---------------------------------------------------------------------------

def _build_spread_regime2(signal, S, sigma, entry_date, r=RISK_FREE_RATE):
    """
    Same as engine._build_backtest_spread but BUY PUTS uses Variant C:
    45 DTE, long 0.55d, short strike exactly $10 below long.
    Delegates to original for every other signal.
    """
    strategy = engine._SIGNAL_TO_STRATEGY.get(signal)
    if strategy != "BEAR_PUT_DEBIT":
        return _ORIG_BUILD(signal, S, sigma, entry_date, r)

    DTE = REGIME2_DTE
    T   = DTE / 365.0
    exp_date = entry_date + datetime.timedelta(days=DTE)

    long_K  = engine._pick_strike_by_delta(S, T, r, sigma, False,
                                            REGIME2_LONG_DELTA, "long")
    short_K = round((long_K - REGIME2_WIDTH) / engine.STRIKE_STEP) * engine.STRIKE_STEP
    if short_K >= long_K:
        short_K = long_K - engine.STRIKE_STEP

    long_fair  = bs_price(S, long_K,  T, r, sigma, is_call=False)
    short_fair = bs_price(S, short_K, T, r, sigma, is_call=False)
    long_eff   = long_fair  * (1 + FRICTION_FRAC)
    short_eff  = short_fair * (1 - FRICTION_FRAC)

    net    = long_eff - short_eff
    width  = abs(long_K - short_K)
    if width <= 0:
        return {"accepted": False, "rejection_reason": "degenerate width=0"}

    max_profit = max(width - net, 0.0)
    max_loss   = net
    breakeven  = long_K - net

    accepted  = True
    rejection = ""
    if net > DEBIT_MAX_COST_FRAC * width:
        accepted = False
        rejection = (f"net debit {net:.2f} > "
                     f"{DEBIT_MAX_COST_FRAC*100:.0f}% of width {width:.2f}")

    budget = ACCOUNT_NOTIONAL * RISK_PER_TRADE_FRAC
    loss_per_contract = max_loss * 100.0
    if accepted and loss_per_contract > 0:
        intended  = budget / loss_per_contract
        contracts = max(int(math.floor(intended)), 1)
    else:
        contracts = 0

    long_delta  = bs_delta(S, long_K,  T, r, sigma, False)
    short_delta = bs_delta(S, short_K, T, r, sigma, False)

    return {
        "strategy_type":       strategy,
        "expiration":          exp_date.isoformat(),
        "dte_entry":           DTE,
        "long_strike":         float(long_K),
        "long_delta":          float(long_delta),
        "long_price":          float(long_eff),
        "short_strike":        float(short_K),
        "short_delta":         float(short_delta),
        "short_price":         float(short_eff),
        "width":               float(width),
        "net_debit_or_credit": float(net),
        "max_profit":          float(max_profit),
        "max_loss":            float(max_loss),
        "breakeven":           float(breakeven),
        "contracts":           int(contracts),
        "total_risk":          float(max_loss * 100.0 * contracts),
        "total_max_profit":    float(max_profit * 100.0 * contracts),
        "accepted":            bool(accepted),
        "rejection_reason":    rejection,
    }


# ---------------------------------------------------------------------------
# REGIME 3: quintile-scaled per-trade cap, no strategy buckets
# ---------------------------------------------------------------------------

def make_regime3_size_trade(q_edges):
    """
    Build a size_trade drop-in that sizes by confidence quintile and uses
    only the global 6% portfolio cap (no strategy buckets).

    q_edges is the list of 4 cut points [t1, t2, t3, t4] derived from the
    flat-corpus confidence distribution.  We keep the negative-Kelly filter
    so SELL CALLS stays disabled (apples-to-apples with regimes 1 and 2).
    """
    bins   = [-np.inf] + list(q_edges) + [np.inf]
    labels = ["Q1", "Q2", "Q3", "Q4", "Q5"]

    def _size_trade(signal, confidence, max_loss_per_contract,
                    stats=None, open_risk_dollars=0.0,
                    open_risk_by_strategy=None,
                    account_notional=position_sizer.ACCOUNT_NOTIONAL,
                    use_segregated_buckets=True):
        if max_loss_per_contract is None or max_loss_per_contract <= 0:
            return {"contracts": 0, "tradable": False, "kelly_f": 0.0,
                    "effective_frac": 0.0, "dollar_risk": 0.0,
                    "bucket_frac": 0.0, "bucket_used_before": 0.0,
                    "bucket_cap_dollars": 0.0, "reason": "invalid_max_loss"}

        confidence = float(np.clip(confidence, 0.0, 1.0))
        stats = stats or {}
        s = stats.get(signal, {})

        # Keep negative-Kelly filter.  If a signal has a fitted negative
        # edge we don't trade it -- confidence alone isn't enough.
        if s and int(s.get("count", 0)) >= position_sizer.MIN_TRADES_FOR_KELLY:
            raw_f = float(s.get("kelly_f", 0.0))
            if raw_f <= 0:
                return {"contracts": 0, "tradable": False, "kelly_f": raw_f,
                        "effective_frac": 0.0, "dollar_risk": 0.0,
                        "bucket_frac": 0.0, "bucket_used_before": 0.0,
                        "bucket_cap_dollars": 0.0,
                        "reason": f"negative_kelly_{signal}"}
            kelly_f = raw_f
        else:
            kelly_f = 0.0

        # Quintile -> per-trade fraction
        q_idx = int(pd.cut([confidence], bins=bins, labels=False,
                           include_lowest=True)[0])
        q_label = labels[q_idx]
        per_trade_frac = REGIME3_QUINTILE_FRAC[q_label]

        # Global portfolio cap only (no strategy buckets in this regime)
        global_cap_dol   = position_sizer.MAX_PORTFOLIO_RISK * account_notional
        remaining_budget = max(global_cap_dol - open_risk_dollars, 0.0)

        # Reuse the bucket-* output fields to carry the global-cap context
        # so downstream analysis code doesn't need a special case for R3.
        bucket_used_before = float(open_risk_dollars)
        bucket_cap_dol     = global_cap_dol

        if remaining_budget <= 0:
            return {"contracts": 0, "tradable": False, "kelly_f": kelly_f,
                    "effective_frac": 0.0, "dollar_risk": 0.0,
                    "bucket_frac": 0.0,
                    "bucket_used_before": round(bucket_used_before, 2),
                    "bucket_cap_dollars": round(bucket_cap_dol, 2),
                    "reason": "portfolio_risk_cap"}

        dollar_budget = min(per_trade_frac * account_notional, remaining_budget)
        loss_per_contract_dollars = max_loss_per_contract * 100.0
        raw_contracts = dollar_budget / loss_per_contract_dollars
        contracts = max(int(math.floor(raw_contracts)),
                        position_sizer.MIN_CONTRACTS)
        dollar_risk = contracts * loss_per_contract_dollars
        effective_fr = (dollar_risk / account_notional) if account_notional > 0 else 0.0

        over_policy = (dollar_risk + open_risk_dollars) > global_cap_dol
        return {
            "contracts":      contracts,
            "tradable":       True,
            "kelly_f":        round(kelly_f, 4),
            "kelly_source":   f"quintile_{q_label}",
            "effective_frac": round(effective_fr, 4),
            "dollar_risk":    round(dollar_risk, 2),
            "bucket_frac":    0.0,
            "bucket_used_before": round(bucket_used_before, 2),
            "bucket_cap_dollars": round(bucket_cap_dol, 2),
            "reason":         "floor_over_cap" if over_policy else "ok",
        }

    return _size_trade


# ---------------------------------------------------------------------------
# yfinance cache so 15 backtest passes don't redownload 5y prices each time
# ---------------------------------------------------------------------------

_PRICE_CACHE: dict = {}
_ORIG_LOAD_PRICE = engine.load_price_history

def _cached_load_price(ticker, period="2y"):
    import time
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
            print(f"[regime] yfinance retry {attempt+1}/4 for {ticker}: {e}")
            time.sleep(2 + attempt * 3)
    raise last_err


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

_ORIG_BUILD   = engine._build_backtest_spread
_ORIG_SIZE    = position_sizer.size_trade
_ORIG_BUCKETS = dict(position_sizer.STRATEGY_BUCKETS)


def run_regime(tickers, suffix, lookback_days=500, demo=True):
    for t in tickers:
        engine.run_backtest(t, demo_mode=demo, lookback_days=lookback_days,
                            use_kelly_sizing=True, output_suffix=suffix)


def _df_to_md(df: pd.DataFrame) -> str:
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
                cells.append("-" if pd.isna(v) else f"{float(v):.4f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(tickers, lookback_days=500, demo=True, skip_run=False):
    os.makedirs(OUT_DIR, exist_ok=True)

    # Plug in the price-history cache so downloads happen exactly once
    engine.load_price_history = _cached_load_price

    # --- 1. Flat corpus (required) ---
    flat = _load_suffix(tickers, suffix="")
    if flat.empty:
        print("[regime] No flat corpus on disk; "
              "run segregated_kelly_report.py first.")
        return
    print(f"[regime] Flat corpus: {len(flat)} rows across {len(tickers)} tickers.")

    # --- 2. Rebuild Kelly stats from flat corpus ---
    stats = position_sizer.compute_kelly_stats(flat)
    position_sizer.save_stats(stats)
    position_sizer.print_stats(stats)

    # --- 3. Quintile edges from flat corpus's accepted-trade confidences ---
    acc = flat[flat["accepted"].astype(bool)]["confidence"].astype(float).dropna()
    _, edges = pd.qcut(acc, 5, retbins=True, duplicates="drop")
    q_edges = [float(x) for x in edges[1:-1]]
    if len(q_edges) != 4:
        raise RuntimeError(f"Expected 4 quintile edges, got {q_edges}")
    print(f"[regime] Confidence quintile edges: "
          f"{[round(x, 4) for x in q_edges]}")

    # --- 4. Run each regime ---
    if not skip_run:
        # REGIME 1
        print("\n" + "=" * 72)
        print("REGIME 1: BUY PUTS 4.5% / BUY CALLS 1.0% / SELL P 0.25% / SELL C 0.25%")
        print("=" * 72)
        position_sizer.STRATEGY_BUCKETS.clear()
        position_sizer.STRATEGY_BUCKETS.update(REGIME1_BUCKETS)
        try:
            run_regime(tickers, "_r1", lookback_days, demo)
        finally:
            position_sizer.STRATEGY_BUCKETS.clear()
            position_sizer.STRATEGY_BUCKETS.update(_ORIG_BUCKETS)

        # REGIME 2
        print("\n" + "=" * 72)
        print("REGIME 2: Variant C -- 45 DTE / $10 width BUY PUTS, buckets unchanged")
        print("=" * 72)
        engine._build_backtest_spread = _build_spread_regime2
        try:
            run_regime(tickers, "_r2", lookback_days, demo)
        finally:
            engine._build_backtest_spread = _ORIG_BUILD

        # REGIME 3
        print("\n" + "=" * 72)
        print("REGIME 3: Quintile per-trade cap (0.1-0.8%), no strategy buckets")
        print("=" * 72)
        position_sizer.size_trade = make_regime3_size_trade(q_edges)
        try:
            run_regime(tickers, "_r3", lookback_days, demo)
        finally:
            position_sizer.size_trade = _ORIG_SIZE

    # --- 5. Load each regime's logs ---
    r1 = _load_suffix(tickers, "_r1")
    r2 = _load_suffix(tickers, "_r2")
    r3 = _load_suffix(tickers, "_r3")
    kelly_current = _load_suffix(tickers, "_kelly")  # baseline from last run

    # --- 6. Assemble report ---
    print("\n" + "=" * 72)
    print("REPORT")
    print("=" * 72)

    headlines = pd.DataFrame([
        headline(flat,          "flat (baseline)"),
        headline(kelly_current, "segregated Kelly (current)"),
        headline(r1,            "REGIME 1: buckets 4.5/1.0/0.25/0.25"),
        headline(r2,            "REGIME 2: Variant C BUY PUTS (45 DTE $10w)"),
        headline(r3,            "REGIME 3: no buckets, quintile per-trade"),
    ])
    print("\n[headline]")
    print(headlines.to_string(index=False))

    util_rows = []
    for label, df in [("current", kelly_current), ("R1", r1),
                      ("R2", r2), ("R3", r3)]:
        u = buy_puts_util(df)
        if u:
            u["regime"] = label
            util_rows.append(u)
    util_df = pd.DataFrame(util_rows)
    if not util_df.empty:
        util_df = util_df[["regime", "bucket_cap_$", "n_evaluations",
                           "mean_utilization", "peak_utilization",
                           "n_blocked", "pct_blocked"]]
    print("\n[BUY PUTS bucket utilization + block rate]")
    print(util_df.to_string(index=False))

    print("\n[Quintile P&L -- fixed bins from flat corpus]")
    for label, df in [("current", kelly_current), ("R1", r1),
                      ("R2", r2), ("R3", r3)]:
        q = quintile_table(df, q_edges=q_edges)
        if not q.empty:
            print(f"\n-- {label} --")
            print(q.to_string(index=False))

    print("\n[Trade counts per strategy]")
    count_frames = {}
    for label, df in [("flat", flat), ("current", kelly_current),
                      ("R1", r1), ("R2", r2), ("R3", r3)]:
        c = trades_per_strategy(df)
        if not c.empty:
            count_frames[label] = c.set_index("signal")["n_trades"]
    counts_df = pd.DataFrame(count_frames).fillna(0).astype(int)
    print(counts_df.to_string())

    # --- 7. Pick winner (total_pnl among R1/R2/R3) ---
    cand = headlines[headlines["regime"].str.startswith("REGIME")].copy()
    winner = cand.sort_values("total_pnl", ascending=False).iloc[0]
    print(f"\n[winner by total P&L] {winner['regime']}  "
          f"total_pnl={winner['total_pnl']:+.2f}  sharpe={winner['sharpe']:+.4f}")

    # --- 8. Markdown report ---
    md_path = os.path.join(OUT_DIR, "regime_comparison.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Three-Regime Allocation Comparison\n\n")
        f.write("_Demo-mode, 500-day window, 5 tickers.  Flat corpus reused "
                "across all regimes; Kelly stats and confidence quintile edges "
                "rebuilt once from that corpus._\n\n")
        f.write("## 1. Headline metrics\n\n")
        f.write(_df_to_md(headlines))
        f.write("\n")

        f.write("## 2. BUY PUTS bucket utilization + block rate\n\n")
        f.write("_For R3, `bucket_cap_$` = the global 6% portfolio cap "
                "($6,000 on the $100k paper account); `pct_blocked` counts "
                "portfolio-cap rejections._\n\n")
        f.write(_df_to_md(util_df))
        f.write("\n")

        f.write("## 3. Confidence quintile P&L after sizing\n\n")
        f.write(f"_Fixed quintile edges (derived once from flat corpus): "
                f"{[round(x, 4) for x in q_edges]}_\n\n")
        for label, df in [("current segregated Kelly", kelly_current),
                          ("REGIME 1",                r1),
                          ("REGIME 2",                r2),
                          ("REGIME 3",                r3)]:
            q = quintile_table(df, q_edges=q_edges)
            f.write(f"### {label}\n\n")
            f.write(_df_to_md(q))
            f.write("\n")

        f.write("## 4. Trade counts per strategy\n\n")
        f.write(_df_to_md(counts_df.reset_index()))
        f.write("\n")

        f.write("## 5. Regime definitions\n\n")
        f.write("- **REGIME 1** -- STRATEGY_BUCKETS = "
                f"{REGIME1_BUCKETS} (sum = 6.0%)\n")
        f.write(f"- **REGIME 2** -- BUY PUTS overridden to {REGIME2_DTE} DTE / "
                f"${REGIME2_WIDTH:.0f} width / long {REGIME2_LONG_DELTA} delta; "
                "buckets unchanged (3.0 / 1.5 / 0.75 / 0.75)\n")
        f.write(f"- **REGIME 3** -- STRATEGY_BUCKETS disabled; per-trade cap "
                f"by confidence quintile: {REGIME3_QUINTILE_FRAC}\n")

    print(f"\n[report] -> {md_path}")
    return {
        "headlines": headlines,
        "util":      util_df,
        "counts":    counts_df,
        "md_path":   md_path,
        "winner":    winner["regime"],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=config.TICKERS)
    ap.add_argument("--lookback-days", type=int, default=500)
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--skip-run", action="store_true",
                    help="Reuse existing _r1/_r2/_r3 logs, only rebuild report.")
    args = ap.parse_args()

    main(
        tickers       = args.tickers,
        lookback_days = args.lookback_days,
        demo          = not args.real,
        skip_run      = args.skip_run,
    )

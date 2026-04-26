# =============================================================================
# signals/position_sizer.py -- Fractional-Kelly position sizing per signal type
#
# WHY KELLY?
# ----------
# The Kelly criterion is the growth-optimal fraction of bankroll to risk on a
# bet with known edge.  For a binary-outcome bet with:
#     p = win probability
#     q = 1 - p
#     W = avg_win / avg_loss  (payoff ratio, both positive)
# the fraction that maximises expected log-wealth is
#     f*  =  (W * p  -  q) / W
#
# Why that formula?  Expected log-wealth after one bet of size f is
#     E[log(1 + f * r)] = p * log(1 + f*W*L) + q * log(1 - f*L)
# where L = avg_loss per unit risk.  Setting d/df = 0 and solving yields f*.
# This is growth-optimal: over many independent bets it maximises the
# long-run compound return, BUT its short-run drawdowns can be brutal
# because it assumes the empirical p and W are the true values.
#
# WHY FRACTIONAL KELLY (0.25x)?
# -----------------------------
# Full Kelly is only optimal if your edge estimate is exactly right.  When
# p and W are estimated from a finite sample, every parameter error shows
# up magnified in f*.  Halving Kelly keeps ~75% of the geometric growth
# rate while cutting variance of the log-wealth path by ~75%.  A quarter-
# Kelly cuts variance further (~94%) and is the industry default for
# discretionary/systematic traders who can't fully trust their edge
# estimates.  We use 0.25x on purpose: noisy backtests, small samples,
# structural regime shifts all argue for humility here.
#
# WHY SCALE BY CONFIDENCE?
# ------------------------
# The signal-engine confidence (0-1) already captures how deep into the
# edge zone the signal sits.  We multiply Kelly by confidence so that:
#   * A strong signal (conf 1.0) gets the full fractional-Kelly size
#   * A borderline signal (conf 0.1) gets only a token size
# This keeps us sized down when the edge is thin -- a second line of
# defence on top of the 0.25x fractional-Kelly shrinkage.
#
# PORTFOLIO GUARDRAILS
# --------------------
# No matter what Kelly says, we enforce hard caps:
#   * MAX_RISK_PER_TRADE  = 2% of account   (single bad trade cap)
#   * MAX_PORTFOLIO_RISK  = 6% of account   (concurrent-position cap)
#   * MIN_CONTRACTS       = 1               (can't buy half a contract)
# These reflect the 2-6-10 rule: 2% per trade, 6% total open risk, 10%
# max daily loss.  The floor at 1 is there because the kelly math can
# return f* = 0.003, which would round to zero contracts and effectively
# skip the trade -- not what we want when the signal engine has already
# said "yes, trade this".
#
# DEGENERATE CASES
# ----------------
#   * No historical trades for this signal type  -> fall back to default
#     (RISK_PER_TRADE_FRAC).  Better than guessing Kelly from 3 trades.
#   * Negative Kelly (W*p < q)                   -> size = 0, trade is
#     disabled.  Signal has negative historical edge; don't trade it.
#   * avg_loss = 0                               -> undefined W.  Treat as
#     no data; fall back to default sizing.
#
# INTERFACE
# ---------
#   compute_kelly_stats(trades)       -> dict keyed by signal type
#   kelly_fraction(p, W)              -> raw Kelly fraction f*
#   size_trade(signal, confidence,
#              max_loss_per_contract, stats,
#              open_risk_dollars)     -> dict with contracts + diagnostics
#
# The backtest engine and the live signal emitter both call size_trade()
# so the sizing logic is defined in exactly one place.
# =============================================================================

from __future__ import annotations

import os
import glob
import json
import math
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants -- math decisions documented inline for interview defence
# ---------------------------------------------------------------------------

# Fraction of full Kelly.  0.25 = quarter-Kelly, the standard conservative
# choice.  See module docstring for the variance-vs-growth tradeoff.
KELLY_FRACTION = 0.25

# Hard caps (fraction of account notional)
MAX_RISK_PER_TRADE = 0.02     # 2% cap per position
MAX_PORTFOLIO_RISK = 0.06     # 6% cap across all open positions
MIN_CONTRACTS      = 1        # floor -- never size to zero if trade is taken

# ---------------------------------------------------------------------------
# Sizing regime: QUINTILE per-trade cap (production default, "R3")
# ---------------------------------------------------------------------------
# WHY NOT STRATEGY BUCKETS?
# -------------------------
# We originally segregated the 6% portfolio cap into per-strategy buckets
# (BUY PUTS 3.0% / BUY CALLS 1.5% / SELL PUTS 0.75% / SELL CALLS 0.75%) to
# stop a run of long-dated BUY PUTS positions from starving fresh BUY CALLS
# entries.  That did fix the cross-strategy starvation problem BUT the
# BUY PUTS bucket itself saturated (58% of signals blocked), and when we
# raised it to 4.5% (regime_comparison.R1) the block rate only fell to 49%
# and starving BUY CALLS hurt portfolio P&L.  Full three-regime study in
# outputs/regime_comparison.md.
#
# WHY QUINTILE PER-TRADE?
# -----------------------
# Dropping buckets entirely and sizing per-trade by confidence quintile
# (R3) delivered +$12,604 / Sharpe 0.46 vs current -$3,215 / -0.12 while
# cutting the BUY PUTS block rate from 58% to 29%.  Letting signal
# density determine total exposure -- subject only to the global 6%
# portfolio cap -- was the clean fix.  See PROJECT_STATE §9-10.
#
# SIZING FORMULA
# --------------
# Rather than Kelly_f * confidence (which amplifies the high-confidence
# trades and wrecks Q5 via selection bias), we pick a flat per-trade
# fraction from the confidence quintile.  The edges are refit to the
# current flat corpus so "Q5" always means "top 20% by predicted p(win)".
#
#   Q1 (lowest conf) :  0.10%   -- token size, low-edge signals
#   Q2              :  0.20%
#   Q3              :  0.30%
#   Q4              :  0.50%
#   Q5 (highest)    :  0.80%   -- 8x floor, still below MAX_RISK_PER_TRADE
# Implied "average" size ~0.38%, ~5x less aggressive than fractional Kelly
# on BUY PUTS (0.25 * 0.2345 = 5.86%).  The whole point is to stop
# amplifying high-confidence trades that turn out to be wrong.
QUINTILE_FRAC = {
    "Q1": 0.0010,
    "Q2": 0.0020,
    "Q3": 0.0030,
    "Q4": 0.0050,
    "Q5": 0.0080,
}

# Production default: quintile sizing, global 6% cap, no strategy buckets.
# Flip to True to run legacy segregated-bucket behaviour for A/B comparison.
USE_STRATEGY_BUCKETS = False

# Legacy STRATEGY_BUCKETS values.  Kept for reference + A/B tests (set
# USE_STRATEGY_BUCKETS=True to use them).  Values are the last-validated
# allocation before we switched to quintile sizing.
STRATEGY_BUCKETS = {
    "BUY PUTS":   0.0300,
    "BUY CALLS":  0.0150,
    "SELL PUTS":  0.0075,
    "SELL CALLS": 0.0075,
}

# Confidence-quintile cut points (4 edges -> 5 bins).  Derived from the
# current flat corpus (500-day demo run, 5 tickers, 417 accepted trades).
# Refresh by running segregated_kelly_report / r3_baseline, which calls
# compute_and_save_quintile_edges() when rebuilding Kelly stats.  The
# on-disk file (quintile_edges.json) takes precedence over these defaults.
DEFAULT_QUINTILE_EDGES = [0.4745, 0.5114, 0.5492, 0.5973]
_QUINTILE_EDGES_CACHE: Optional[list] = None

# Fallback sizing fraction when we have no stats for a signal type yet
DEFAULT_RISK_FRAC  = 0.02

# Account notional -- keep in sync with spread_builder.ACCOUNT_NOTIONAL
ACCOUNT_NOTIONAL   = 10_000.0

# Minimum accepted trade count before Kelly stats are "trusted".  Below this
# threshold we fall back to DEFAULT_RISK_FRAC rather than size on noise.
# Chosen at 10 because with <10 trades the Kelly std error dominates the
# point estimate -- garbage in, garbage out.
MIN_TRADES_FOR_KELLY = 10

# ---------------------------------------------------------------------------
# TODO (2026-04-25, real-data session): re-enable SELL PUTS in production.
# ---------------------------------------------------------------------------
# Per-sector decay on the 10-ticker universe gives SELL PUTS a TRADE
# verdict at 10d (risk_adj +0.29, mean +1.97% directional) over 108
# signal observations -- but the synthetic-vol backtest filters every
# one of them out at the credit floor (spread_builder.CREDIT_MIN_PREMIUM_FR
# = 0.33), so kelly_stats.csv has 0 accepted SELL PUTS rows and Kelly
# can't see the signal.  Root cause: rolling_vol-as-IV-proxy lacks the
# vol risk premium, so synthetic short-put credits price ~17-20% of
# width (vs the 33% floor).
#
# When real Finnhub IV data lands, SELL PUTS credits should clear the
# floor naturally and accepted-trade count should be non-zero.  At
# that point:
#   1. Re-run scripts/segregated_kelly_report.py --real on the 10-ticker
#      universe.
#   2. Confirm kelly_stats.csv now has a SELL PUTS row with kelly_f > 0
#      (decay says yes; the math says yes once premium clears the floor).
#   3. R3 sizing path will pick it up automatically -- size_trade()
#      already routes SELL PUTS through QUINTILE_FRAC when the negative-
#      Kelly filter doesn't trip.  No code change needed here, just
#      stats-driven enablement.
# Tracking: PROJECT_STATE.md §10.2.B.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stats extraction
# ---------------------------------------------------------------------------

def _pnl_pct_to_ratio(pct: float) -> float:
    """
    `pnl_pct` in the trade log is "% of max_loss" (so -100 = full loss,
    +50 = half a max-loss return).  Convert to a unit-risk return by
    dividing by 100 -- Kelly math expects fractions of the risked amount.
    """
    return float(pct) / 100.0


def compute_kelly_stats(trades: pd.DataFrame) -> dict:
    """
    Compute per-signal-type statistics from a historical trade log.

    Input schema: must have columns `signal`, `pnl_pct`, `accepted`.
    Only `accepted == True` trades are used -- rejected signals didn't
    actually produce a P&L observation and would distort win-rate.

    Returns
    -------
    dict keyed by signal label (e.g. "BUY CALLS") with fields:
        count       number of accepted trades
        win_rate    fraction with pnl_pct > 0
        avg_win     mean pnl_pct on winners, as a decimal (0.35 = +35%)
        avg_loss    mean |pnl_pct| on losers, as a decimal (0.75 = -75%)
        std_ret     stdev of pnl_pct across all accepted trades
        W           payoff ratio = avg_win / avg_loss
        kelly_f     raw Kelly fraction (may be negative)
        kelly_f_frac  fractional Kelly = KELLY_FRACTION * max(kelly_f, 0)
        tradable    bool -- True iff kelly_f > 0 AND count >= MIN_TRADES_FOR_KELLY
    """
    if trades is None or trades.empty:
        return {}

    df = trades.copy()
    if "accepted" in df.columns:
        df = df[df["accepted"].astype(bool)]

    if df.empty or "pnl_pct" not in df.columns:
        return {}

    out: dict = {}
    for sig, grp in df.groupby("signal"):
        rets = grp["pnl_pct"].astype(float).map(_pnl_pct_to_ratio)
        wins   = rets[rets > 0]
        losses = rets[rets < 0]
        n      = int(len(rets))

        p        = float(len(wins)) / n if n else 0.0
        avg_win  = float(wins.mean())        if len(wins)   else 0.0
        avg_loss = float(abs(losses.mean())) if len(losses) else 0.0
        std_ret  = float(rets.std(ddof=1))   if n >= 2      else 0.0

        if avg_loss > 0 and avg_win > 0:
            W = avg_win / avg_loss
            f_full = (W * p - (1.0 - p)) / W
        else:
            W = 0.0
            f_full = 0.0

        f_frac = KELLY_FRACTION * max(f_full, 0.0)
        tradable = (f_full > 0.0) and (n >= MIN_TRADES_FOR_KELLY)

        out[str(sig)] = {
            "count":        n,
            "win_rate":     round(p, 4),
            "avg_win":      round(avg_win, 4),
            "avg_loss":     round(avg_loss, 4),
            "std_ret":      round(std_ret, 4),
            "W":            round(W, 4),
            "kelly_f":      round(f_full, 4),
            "kelly_f_frac": round(f_frac, 4),
            "tradable":     bool(tradable),
        }

    return out


# ---------------------------------------------------------------------------
# Stats I/O
# ---------------------------------------------------------------------------

def _stats_path() -> str:
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "raw", "kelly_stats.csv"
    ))


def _quintile_edges_path() -> str:
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "raw", "quintile_edges.json"
    ))


def save_quintile_edges(edges: list, path: Optional[str] = None) -> str:
    """Persist 4 quintile cut points to disk as JSON."""
    path = path or _quintile_edges_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"edges": list(edges)}, f)
    global _QUINTILE_EDGES_CACHE
    _QUINTILE_EDGES_CACHE = list(edges)
    return path


def load_quintile_edges(path: Optional[str] = None) -> Optional[list]:
    """Load quintile edges from disk; returns None if the file is missing."""
    path = path or _quintile_edges_path()
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    edges = data.get("edges")
    if not edges or len(edges) != 4:
        return None
    return [float(x) for x in edges]


def get_quintile_edges() -> list:
    """
    Return the live quintile edges.  Cached on first call; prefers the
    on-disk file over DEFAULT_QUINTILE_EDGES so a rebuilt flat corpus
    propagates to size_trade without a code change.
    """
    global _QUINTILE_EDGES_CACHE
    if _QUINTILE_EDGES_CACHE is None:
        loaded = load_quintile_edges()
        _QUINTILE_EDGES_CACHE = loaded if loaded else list(DEFAULT_QUINTILE_EDGES)
    return _QUINTILE_EDGES_CACHE


def compute_and_save_quintile_edges(trades: pd.DataFrame,
                                    path: Optional[str] = None) -> list:
    """
    Fit the 4 confidence quintile edges on a flat-corpus trade log and
    persist them.  Called by the flagship report scripts right after
    compute_kelly_stats so production sizing tracks the current corpus.
    """
    if trades is None or trades.empty:
        return list(DEFAULT_QUINTILE_EDGES)
    df = trades
    if "accepted" in df.columns:
        df = df[df["accepted"].astype(bool)]
    if "confidence" not in df.columns or df.empty:
        return list(DEFAULT_QUINTILE_EDGES)
    s = df["confidence"].astype(float).dropna()
    _, cuts = pd.qcut(s, 5, retbins=True, duplicates="drop")
    edges = [float(x) for x in cuts[1:-1]]
    if len(edges) != 4:
        return list(DEFAULT_QUINTILE_EDGES)
    save_quintile_edges(edges, path=path)
    return edges


def _quintile_label(confidence: float, edges: Optional[list] = None) -> str:
    """Map a confidence score to its quintile label Q1..Q5."""
    edges = edges or get_quintile_edges()
    if   confidence < edges[0]: return "Q1"
    elif confidence < edges[1]: return "Q2"
    elif confidence < edges[2]: return "Q3"
    elif confidence < edges[3]: return "Q4"
    else:                        return "Q5"


def save_stats(stats: dict, path: Optional[str] = None) -> str:
    """Persist the per-signal stats dict to disk as a CSV."""
    path = path or _stats_path()
    rows = [{"signal": sig, **vals} for sig, vals in stats.items()]
    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    return path


def load_stats(path: Optional[str] = None) -> dict:
    """
    Load persisted Kelly stats, or {} if the file doesn't exist.  The
    signal_engine prefers this cached version so we don't re-scan every
    trade log on each call.
    """
    path = path or _stats_path()
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path)
    return {r["signal"]: {k: r[k] for k in df.columns if k != "signal"}
            for _, r in df.iterrows()}


def build_and_save_stats_from_logs(
    raw_dir: Optional[str] = None,
    pattern: str = "backtest_*.csv",
) -> dict:
    """
    Scan every backtest log under `raw_dir`, concatenate them, compute
    per-signal Kelly stats, and save the result.

    Used by a one-off "refresh stats" script before going live; not called
    from inside the signal loop.
    """
    raw_dir = raw_dir or os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "raw"
    ))
    files = glob.glob(os.path.join(raw_dir, pattern))
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f, parse_dates=["entry_date", "exit_date"]))
        except Exception:
            continue
    if not frames:
        print("[position_sizer] No backtest logs found; stats unchanged.")
        return {}
    all_trades = pd.concat(frames, ignore_index=True)
    stats = compute_kelly_stats(all_trades)
    save_stats(stats)
    print(f"[position_sizer] Saved Kelly stats for {len(stats)} signal types "
          f"to data/raw/kelly_stats.csv")
    return stats


# ---------------------------------------------------------------------------
# Sizing core
# ---------------------------------------------------------------------------

def kelly_fraction(p: float, W: float) -> float:
    """
    Raw Kelly formula.  Returns f* -- may be negative (no edge).
    Callers should clip at 0 before scaling.
    """
    if W <= 0:
        return 0.0
    return (W * p - (1.0 - p)) / W


def size_trade(
    signal:                str,
    confidence:            float,
    max_loss_per_contract: float,
    stats:                 Optional[dict] = None,
    open_risk_dollars:     float = 0.0,
    open_risk_by_strategy: Optional[dict] = None,
    account_notional:      float = ACCOUNT_NOTIONAL,
    use_segregated_buckets: Optional[bool] = None,
    quintile_edges:        Optional[list] = None,
) -> dict:
    """
    Translate an edge estimate + a confidence score into an integer
    contract count, subject to portfolio guardrails.

    Two sizing regimes:
      * QUINTILE (production, USE_STRATEGY_BUCKETS=False)  --  per-trade
        fraction comes from the signal's confidence quintile via
        QUINTILE_FRAC.  Only the global 6% portfolio cap applies.
      * SEGREGATED BUCKETS (legacy, USE_STRATEGY_BUCKETS=True)  --  Kelly
        math scaled by confidence, capped per-strategy by STRATEGY_BUCKETS.
        Retained for A/B comparison against historical runs.

    Parameters
    ----------
    signal                  : signal label (e.g. "BUY CALLS")
    confidence              : [0, 1] scalar from signal_engine
    max_loss_per_contract   : per-SHARE max loss; per-contract = this * 100
    stats                   : dict from compute_kelly_stats() -- only used
                              for the negative-Kelly filter (both regimes
                              refuse to trade a signal with fitted
                              negative edge)
    open_risk_dollars       : total already-deployed dollar risk (drives
                              the global 6% cap in the QUINTILE path)
    open_risk_by_strategy   : dict signal -> deployed $ (only used when
                              use_segregated_buckets=True)
    account_notional        : paper-account size (default $10k)
    use_segregated_buckets  : override the module-level USE_STRATEGY_BUCKETS
                              default.  None -> fall back to the module flag.
    quintile_edges          : override the on-disk quintile edges.  None ->
                              fall back to get_quintile_edges().

    Returns
    -------
    dict with:
        contracts            int   >= MIN_CONTRACTS or 0 if disabled
        tradable             bool  positive historical edge?
        kelly_f              raw Kelly fraction (may be negative)
        effective_frac       fraction of account actually risked
        dollar_risk          contracts * 100 * max_loss_per_contract
        bucket_frac          bucket cap that applied (0 in QUINTILE path)
        bucket_used_before   $ already in use against the cap
        bucket_cap_dollars   $ cap (per-strategy or global)
        reason               human-readable string ("ok", "quintile_Q3",
                             "bucket_full", "portfolio_risk_cap",
                             "negative_kelly_<sig>", "invalid_max_loss",
                             "floor_over_bucket", "floor_over_cap")
    """
    if max_loss_per_contract is None or max_loss_per_contract <= 0:
        return {"contracts": 0, "tradable": False, "kelly_f": 0.0,
                "effective_frac": 0.0, "dollar_risk": 0.0,
                "bucket_frac": 0.0, "bucket_used_before": 0.0,
                "bucket_cap_dollars": 0.0,
                "reason": "invalid_max_loss"}

    confidence = float(np.clip(confidence, 0.0, 1.0))
    stats = stats or {}
    s = stats.get(signal, {})

    # Resolve regime flag: explicit arg > module default
    if use_segregated_buckets is None:
        use_segregated_buckets = USE_STRATEGY_BUCKETS

    # --- Negative-edge filter (both regimes) ---
    # If we have enough trades to trust Kelly stats and the signal's fitted
    # edge is negative, we don't trade it.  This is what keeps SELL CALLS
    # disabled after decay study flagged it.
    if s and int(s.get("count", 0)) >= MIN_TRADES_FOR_KELLY:
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

    # --- Per-trade fraction: branch on regime ---
    if use_segregated_buckets:
        # Legacy: fractional Kelly scaled by confidence (floor 0.25).
        if kelly_f > 0:
            frac_kelly = KELLY_FRACTION * kelly_f
            source     = "kelly"
        else:
            frac_kelly = DEFAULT_RISK_FRAC
            source     = "fallback"
        conf_scaled    = frac_kelly * max(confidence, 0.25)
        per_trade_frac = min(conf_scaled, MAX_RISK_PER_TRADE)
    else:
        # Production: confidence quintile -> flat per-trade fraction.
        q = _quintile_label(confidence, quintile_edges)
        per_trade_frac = min(QUINTILE_FRAC[q], MAX_RISK_PER_TRADE)
        source = f"quintile_{q}"

    # --- Cap selection: per-strategy bucket OR global portfolio cap ---
    if use_segregated_buckets and signal in STRATEGY_BUCKETS:
        bucket_frac    = float(STRATEGY_BUCKETS[signal])
        bucket_cap_dol = bucket_frac * account_notional
        open_in_bucket = 0.0
        if open_risk_by_strategy:
            open_in_bucket = float(open_risk_by_strategy.get(signal, 0.0))
        remaining_budget   = max(bucket_cap_dol - open_in_bucket, 0.0)
        bucket_used_before = open_in_bucket
        cap_full_reason    = "bucket_full"
    else:
        bucket_frac        = 0.0
        bucket_cap_dol     = MAX_PORTFOLIO_RISK * account_notional
        remaining_budget   = max(bucket_cap_dol - open_risk_dollars, 0.0)
        bucket_used_before = float(open_risk_dollars)
        cap_full_reason    = "portfolio_risk_cap"

    dollar_budget = min(per_trade_frac * account_notional, remaining_budget)

    # --- Convert dollar budget to contracts ---
    loss_per_contract_dollars = max_loss_per_contract * 100.0

    if dollar_budget <= 0:
        return {"contracts": 0, "tradable": False, "kelly_f": kelly_f,
                "effective_frac": 0.0, "dollar_risk": 0.0,
                "bucket_frac": bucket_frac,
                "bucket_used_before": round(bucket_used_before, 2),
                "bucket_cap_dollars": round(bucket_cap_dol, 2),
                "reason": cap_full_reason}

    raw_contracts = dollar_budget / loss_per_contract_dollars
    contracts = max(int(math.floor(raw_contracts)), MIN_CONTRACTS)
    dollar_risk  = contracts * loss_per_contract_dollars
    effective_fr = dollar_risk / account_notional if account_notional > 0 else 0.0

    # Honesty tag: the MIN_CONTRACTS floor can push a trade above the cap
    # it was sized against.  We take it (can't buy half a contract) but
    # flag it so the log shows "floor_over_bucket" / "floor_over_cap".
    if bucket_frac > 0:
        over_policy = (dollar_risk + bucket_used_before) > bucket_cap_dol
        over_reason = "floor_over_bucket"
    else:
        over_policy = (dollar_risk + open_risk_dollars) > bucket_cap_dol
        over_reason = "floor_over_cap"

    return {
        "contracts":      contracts,
        "tradable":       True,
        "kelly_f":        round(kelly_f, 4),
        "kelly_source":   source,
        "effective_frac": round(effective_fr, 4),
        "dollar_risk":    round(dollar_risk, 2),
        "bucket_frac":    round(bucket_frac, 4),
        "bucket_used_before": round(bucket_used_before, 2),
        "bucket_cap_dollars": round(bucket_cap_dol, 2),
        "reason":         over_reason if over_policy else "ok",
    }


def kelly_fraction_for(signal: str,
                       stats: Optional[dict] = None) -> tuple[float, bool]:
    """
    Convenience for signal_engine: return (fractional_kelly, tradable) for
    a given signal type, WITHOUT needing max_loss.  signal_engine uses
    this to stamp every generated signal with a Kelly fraction.

    fractional_kelly = KELLY_FRACTION * max(kelly_f, 0).  Zero when the
    signal has negative historical edge OR insufficient data.
    """
    stats = stats or {}
    s = stats.get(signal, {})
    if not s or int(s.get("count", 0)) < MIN_TRADES_FOR_KELLY:
        return 0.0, False
    raw_f = float(s.get("kelly_f", 0.0))
    if raw_f <= 0:
        return 0.0, False
    return round(KELLY_FRACTION * raw_f, 4), True


# ---------------------------------------------------------------------------
# Pretty printer (for the refresh-stats CLI)
# ---------------------------------------------------------------------------

def print_stats(stats: dict) -> None:
    if not stats:
        print("(no stats -- run the backtest first)")
        return
    print(f"\n{'signal':<15} {'n':>4} {'WR':>6} "
          f"{'avg_W':>7} {'avg_L':>7} {'W':>6} "
          f"{'f*':>8} {'0.25f*':>8} tradable")
    print("-" * 72)
    for sig, v in stats.items():
        print(f"{sig:<15} {v['count']:>4d} {v['win_rate']:>6.2%} "
              f"{v['avg_win']:>7.3f} {v['avg_loss']:>7.3f} "
              f"{v['W']:>6.2f} {v['kelly_f']:>+8.4f} "
              f"{v['kelly_f_frac']:>+8.4f} {str(v['tradable']):>8}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    stats = build_and_save_stats_from_logs()
    print_stats(stats)

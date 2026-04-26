# =============================================================================
# signals/spread_builder.py -- Build vertical spreads from a directional signal
#
# WHY VERTICAL SPREADS (vs single-leg options)?
# ----------------------------------------------
# A vertical spread trades two options of the same type (both calls or both
# puts) and same expiration, differing only in strike.  Compared to a single
# long option it:
#   * caps max loss at a known dollar amount (risk is defined at entry)
#   * reduces vega exposure (the short leg partly offsets the long leg's IV)
#   * pays for itself: the short leg's premium discounts the long leg's cost
# Compared to a naked short option it:
#   * caps max loss (the long leg is a hedge against catastrophic moves)
#   * requires much less buying power in a margin account
#
# STRATEGY MAP (driven by the signal + IV Rank):
# -----------------------------------------------
#   BUY CALLS   (bullish + low IV)  -> BULL CALL DEBIT   (buy lower, sell higher)
#   BUY PUTS    (bearish + low IV)  -> BEAR PUT  DEBIT   (buy higher, sell lower)
#   SELL PUTS   (bullish + high IV) -> BULL PUT  CREDIT  (sell higher put, buy lower put)
#   SELL CALLS  (bearish + high IV) -> BEAR CALL CREDIT  (sell lower call, buy higher call)
#
# The debit strategies pay premium up-front and profit from favorable price
# movement.  Credit strategies collect premium and profit from time decay if
# price stays on the "right" side of the short strike -- they are the
# vol-seller counterpart to the buy-premium debit spreads.
#
# KEY DESIGN DECISIONS (so I can explain every knob in an interview):
# -------------------------------------------------------------------
#   * Expiration window 30-45 DTE, target 35.  Shorter expirations have too
#     much gamma (daily P&L is whippy); longer expirations are slow to gain
#     from a directional move because theta contribution is small.
#   * Debit long-leg target delta 0.55.  Slightly ITM -> higher delta, better
#     directional participation, lower time-decay drag than an ATM option.
#   * Debit short-leg target delta 0.30.  This is ~1/3 of a standard
#     deviation OTM, a common "25-delta" -ish short strike that pays a
#     meaningful credit without capping gains too tightly.
#   * Credit short-leg target delta 0.20.  Approx 80% probability of expiring
#     OTM -- the classic credit-spread setup.  Higher win rate at the cost
#     of lower reward per dollar risked.
#   * Width $5 for S>=$100, $2.50 otherwise -- matches standard equity
#     option chain spacing so an exact-width spread is usually available.
#   * Debit rejection: net_debit > 70% of width.  When you're paying 70%+
#     of the maximum payout, risk/reward drops below 1:0.43 -- not worth it.
#   * Credit rejection: net_credit < 33% of width.  Below that, you'd need
#     a ~66% win rate just to break even (ignoring costs).
#   * Position size: 2% of a $10k paper account = $200 max loss per trade.
#     Classic Kelly-lite risk cap; lets you survive a long losing streak.
#
# RELATIONSHIP TO signal_engine.py:
# ----------------------------------
# signal_engine produces the DIRECTIONAL signal (BUY CALLS etc).  This module
# turns that abstract signal into a concrete two-legged trade ticket.  The
# two are intentionally separate: we can tune strike-selection rules without
# touching the sentiment/IV logic.
# =============================================================================

import os
import sys
import math
import datetime
from typing import Optional

import numpy as np
import pandas as pd

# Spec explicitly says to use scipy.stats.norm.cdf for the CDF.  scipy is now
# a hard dependency (added to requirements.txt).
from scipy.stats import norm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from signals.signal_engine import (
    SIG_BUY_CALLS, SIG_SELL_PUTS, SIG_BUY_PUTS, SIG_SELL_CALLS,
    SIG_NEUTRAL, SIG_IV_CRUSH,
)


# ===========================================================================
# Tunable constants -- every number I might be asked to defend
# ===========================================================================

RISK_FREE_RATE   = 0.045     # 4.5% -- matches backtest/engine.py

# --- Expiration window ---
DTE_TARGET       = 35        # days
DTE_MIN          = 30
DTE_MAX          = 45

# --- Delta targets per strategy leg ---
# Debit-spread legs (we want the long leg ITM-ish, the short leg OTM-ish)
DEBIT_LONG_DELTA       = 0.55   # magnitude
DEBIT_LONG_DELTA_RANGE = (0.50, 0.60)
DEBIT_SHORT_DELTA      = 0.30   # magnitude
DEBIT_SHORT_DELTA_RANGE = (0.25, 0.35)

# Credit-spread short leg (long leg is defined by width below)
CREDIT_SHORT_DELTA       = 0.20   # magnitude -- roughly 1 SD OTM
CREDIT_SHORT_DELTA_RANGE = (0.15, 0.25)

# --- Spread width ---
WIDTH_HI_PRICE   = 5.00     # when underlying >= $100
WIDTH_LO_PRICE   = 2.50     # when underlying <  $100
WIDTH_PRICE_CUT  = 100.0
WIDTH_TOLERANCE  = 2.50     # acceptable width error vs target

# --- Friction / slippage (on TOP of the quoted bid-ask spread) ---
# Modeled as 1.5% worse than the displayed NBBO.  Applied to each leg.
FRICTION_FRAC    = 0.015

# --- Rejection thresholds ---
DEBIT_MAX_COST_FRAC   = 0.70   # net_debit > 70% of width -> reject
CREDIT_MIN_PREMIUM_FR = 0.33   # net_credit < 33% of width -> reject
MAX_BID_ASK_FRAC      = 0.10   # bid-ask spread > 10% of mid -> illiquid
MIN_OPEN_INTEREST     = 50     # <50 OI -> illiquid

# --- Position sizing ---
ACCOUNT_NOTIONAL      = 10_000.0   # paper account
RISK_PER_TRADE_FRAC   = 0.02       # 2% of account = $200 max loss per trade

# --- Backtest exit rules (Step 6) ---
STOP_LOSS_DEBIT_FRAC      = 0.80   # debit: close if pnl <= -80% of entry debit
STOP_LOSS_CREDIT_MULT     = 2.00   # credit: close if spread value >= 2x entry credit
PROFIT_TARGET_FRAC        = 0.50   # close at 50% of max profit
TIME_STOP_DTE             = 21     # close when DTE falls to this


# ===========================================================================
# Black-Scholes math (delta + pricing)
# ===========================================================================

def _d1(S: float, K: float, T: float, r: float, iv: float) -> float:
    """
    Black-Scholes d1.  Extracted because we re-use it for both delta and price.
    T is in years; iv is annualised decimal (0.25 = 25%).
    """
    return (math.log(S / K) + (r + 0.5 * iv * iv) * T) / (iv * math.sqrt(T))


def bs_delta(S: float, K: float, T: float, r: float, iv: float,
             is_call: bool) -> float:
    """
    Black-Scholes delta.  Returns:
      * [0, 1] for calls  (N(d1))
      * [-1, 0] for puts  (N(d1) - 1)
    Returns intrinsic-value-implied delta (0 or 1) if T<=0 or iv<=0.
    """
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        # Degenerate: at/after expiry delta is 0 or +/-1 based on moneyness
        if is_call:
            return 1.0 if S > K else 0.0
        else:
            return -1.0 if S < K else 0.0

    d1 = _d1(S, K, T, r, iv)
    # scipy.stats.norm.cdf per spec
    return float(norm.cdf(d1)) if is_call else float(norm.cdf(d1) - 1.0)


def bs_price(S: float, K: float, T: float, r: float, iv: float,
             is_call: bool) -> float:
    """
    Black-Scholes European option price (per share).  Used by both live
    spread construction and the P&L simulator.
    """
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        # At expiry: intrinsic value
        return max(S - K, 0.0) if is_call else max(K - S, 0.0)

    d1 = _d1(S, K, T, r, iv)
    d2 = d1 - iv * math.sqrt(T)
    disc = math.exp(-r * T)

    if is_call:
        return max(float(S * norm.cdf(d1) - K * disc * norm.cdf(d2)), 0.0)
    else:
        return max(float(K * disc * norm.cdf(-d2) - S * norm.cdf(-d1)), 0.0)


# ===========================================================================
# Step 1 -- Expiration selection
# ===========================================================================

def select_expiration(
    chain_df: pd.DataFrame,
    today: datetime.date = None,
    dte_target: Optional[int] = None,
    dte_min:    Optional[int] = None,
    dte_max:    Optional[int] = None,
) -> Optional[tuple]:
    """
    Pick the best expiration from the chain.

    Rule:
      1. Gather unique expirations and their DTEs.
      2. Prefer any expiration with DTE in [dte_min, dte_max]; among those,
         pick the one closest to dte_target.
      3. If none are in range, pick the nearest expiration with DTE >= dte_min.
      4. If no expiration has DTE >= dte_min, return None (no viable trade).

    Parameters
    ----------
    dte_target / dte_min / dte_max : optional overrides for the module-level
        DTE_TARGET / DTE_MIN / DTE_MAX.  Used by the BEAR_PUT_DEBIT path which
        targets 60 DTE rather than 35 (see put_structure_study.py).

    Returns
    -------
    (expiration_str, dte_int, T_years)  or  None
    """
    if chain_df.empty or "expiration" not in chain_df.columns:
        return None

    if today is None:
        today = datetime.date.today()

    tgt = DTE_TARGET if dte_target is None else int(dte_target)
    mn  = DTE_MIN    if dte_min    is None else int(dte_min)
    mx  = DTE_MAX    if dte_max    is None else int(dte_max)

    exp_dtes = []
    for exp_str in chain_df["expiration"].dropna().unique():
        try:
            exp_dt = datetime.date.fromisoformat(str(exp_str))
        except ValueError:
            continue
        dte = (exp_dt - today).days
        if dte <= 0:
            continue
        exp_dtes.append((exp_str, dte))

    if not exp_dtes:
        return None

    # First pass: expirations inside the target window
    in_window = [x for x in exp_dtes if mn <= x[1] <= mx]
    if in_window:
        # Pick the one closest to the signal-specific target
        best = min(in_window, key=lambda x: abs(x[1] - tgt))
    else:
        # Fallback: nearest expiration with DTE >= mn
        eligible = [x for x in exp_dtes if x[1] >= mn]
        if not eligible:
            return None
        best = min(eligible, key=lambda x: x[1])

    exp_str, dte = best
    T = dte / 365.0
    return exp_str, dte, T


# ===========================================================================
# Step 2 -- Add delta column to a chain DataFrame
# ===========================================================================

def enrich_with_delta(
    chain_df: pd.DataFrame,
    S: float,
    T: float,
    r: float = RISK_FREE_RATE,
) -> pd.DataFrame:
    """
    Compute and attach a `delta` column to every row in `chain_df`.

    Uses each contract's quoted `impliedVolatility` for the per-strike delta.
    Falling back to 0.0 when IV is missing/zero means that strike will never
    be chosen (our pickers only look at reasonable delta magnitudes).
    """
    df = chain_df.copy()

    deltas = []
    for _, row in df.iterrows():
        try:
            K  = float(row["strike"])
            iv = float(row.get("impliedVolatility", 0.0) or 0.0)
            opt_type = str(row.get("option_type", "")).lower()
            is_call  = opt_type.startswith("c")
            if iv <= 0 or T <= 0 or K <= 0:
                deltas.append(0.0)
                continue
            deltas.append(bs_delta(S, K, T, r, iv, is_call))
        except (ValueError, TypeError, KeyError):
            deltas.append(0.0)

    df["delta"] = deltas
    return df


# ===========================================================================
# Leg / width utilities
# ===========================================================================

def target_width(spot: float) -> float:
    """$5 on higher-priced names, $2.50 on lower.  Matches standard chain spacing."""
    return WIDTH_HI_PRICE if spot >= WIDTH_PRICE_CUT else WIDTH_LO_PRICE


def _pick_by_delta(
    candidates: pd.DataFrame,
    target: float,
    delta_range: tuple,
) -> Optional[pd.Series]:
    """
    Pick the row whose |delta| is closest to `target`, preferring rows inside
    `delta_range` (min_abs, max_abs).  Falls back to the overall closest if
    nothing lands inside the range.

    `candidates` is already filtered to the right option_type.
    Returns a pd.Series (one row) or None.
    """
    if candidates.empty:
        return None

    df = candidates.copy()
    df["abs_delta"] = df["delta"].abs()

    lo, hi = delta_range
    in_range = df[(df["abs_delta"] >= lo) & (df["abs_delta"] <= hi)]

    pool = in_range if not in_range.empty else df
    pool = pool.copy()
    pool["dist"] = (pool["abs_delta"] - target).abs()
    return pool.loc[pool["dist"].idxmin()]


def _pick_width_partner(
    candidates: pd.DataFrame,
    short_strike: float,
    spot: float,
    direction: str,
) -> Optional[pd.Series]:
    """
    For CREDIT spreads, pick the long-leg strike at the target width from
    the short leg.  "Never narrower than target" -- we widen before we narrow
    because narrower than target means an uncappable risk vs. premium trade-off.

    direction:
      "below"  -- long strike must be BELOW short (bull put credit)
      "above"  -- long strike must be ABOVE short (bear call credit)
    """
    if candidates.empty:
        return None

    tgt_w = target_width(spot)
    df = candidates.copy()

    if direction == "below":
        df = df[df["strike"] < short_strike].copy()
        df["width"] = short_strike - df["strike"]
    elif direction == "above":
        df = df[df["strike"] > short_strike].copy()
        df["width"] = df["strike"] - short_strike
    else:
        return None

    if df.empty:
        return None

    # Prefer strikes at >= target width ("never narrower").  Among those,
    # pick the one closest to the target to avoid buying an excessively
    # wide hedge that doesn't reduce risk commensurately.
    wide_enough = df[df["width"] >= tgt_w - 1e-6]
    if not wide_enough.empty:
        wide_enough = wide_enough.copy()
        wide_enough["err"] = (wide_enough["width"] - tgt_w).abs()
        return wide_enough.loc[wide_enough["err"].idxmin()]

    # Otherwise fall back to the widest available (closest to target from below)
    df["err"] = (tgt_w - df["width"]).abs()
    return df.loc[df["err"].idxmin()]


def _check_width(long_strike: float, short_strike: float, spot: float) -> tuple:
    """
    Return (width, within_tolerance_bool).  Width is always positive.
    """
    width = abs(short_strike - long_strike)
    tgt   = target_width(spot)
    ok    = abs(width - tgt) <= WIDTH_TOLERANCE
    return width, ok


# ===========================================================================
# Liquidity and pricing helpers
# ===========================================================================

def _leg_mid(bid: float, ask: float) -> float:
    """Mid-price; defensive against zero / crossed quotes."""
    if bid <= 0 and ask <= 0:
        return 0.0
    if bid <= 0:
        return ask
    if ask <= 0:
        return bid
    return (bid + ask) / 2.0


def _leg_liquidity_ok(leg: pd.Series) -> tuple:
    """
    Check if a single leg passes liquidity filters.  Returns (ok, reason).
    """
    bid = float(leg.get("bid", 0.0) or 0.0)
    ask = float(leg.get("ask", 0.0) or 0.0)
    oi  = int(leg.get("openInterest", 0) or 0)

    mid = _leg_mid(bid, ask)
    if mid <= 0:
        return False, f"leg has no valid bid/ask (bid={bid}, ask={ask})"

    spread_frac = (ask - bid) / mid if mid > 0 else 1.0
    if spread_frac > MAX_BID_ASK_FRAC:
        return False, (f"leg bid-ask spread {spread_frac:.1%} "
                       f"> {MAX_BID_ASK_FRAC:.0%} of mid")

    if oi < MIN_OPEN_INTEREST:
        return False, f"leg openInterest {oi} < {MIN_OPEN_INTEREST}"

    return True, ""


def _apply_friction(long_ask: float, short_bid: float) -> tuple:
    """
    Apply 1.5% friction to each leg:
      - The leg you buy becomes more expensive: ask * (1 + FRICTION_FRAC)
      - The leg you sell pays less:            bid * (1 - FRICTION_FRAC)
    Returns (effective_long_price, effective_short_price).
    """
    eff_long  = long_ask  * (1.0 + FRICTION_FRAC)
    eff_short = short_bid * (1.0 - FRICTION_FRAC)
    return eff_long, eff_short


# ===========================================================================
# Position sizing (Step 4)
# ===========================================================================

def size_position(max_loss_per_contract: float) -> tuple:
    """
    Risk budget: RISK_PER_TRADE_FRAC of ACCOUNT_NOTIONAL.
    Contracts = floor(budget / (max_loss * 100)).  Min 1 contract.

    Returns (contracts:int, accepted:bool, reason:str_or_empty).
    If max_loss_per_contract * 100 exceeds the per-trade budget, we
    reject rather than take on a single-contract position larger than
    our risk limit.
    """
    budget = ACCOUNT_NOTIONAL * RISK_PER_TRADE_FRAC
    max_loss_dollars = max_loss_per_contract * 100.0   # 1 contract = 100 shares

    if max_loss_dollars <= 0:
        # Structurally not possible for vertical spreads (max loss is always > 0),
        # but guard anyway.
        return 0, False, "non-positive max loss"

    if max_loss_dollars > budget:
        return 0, False, (f"1-contract risk ${max_loss_dollars:.0f} "
                          f"exceeds ${budget:.0f} budget")

    contracts = max(1, int(budget // max_loss_dollars))
    return contracts, True, ""


# ===========================================================================
# Strategy-specific builders (Step 3)
# ===========================================================================
#
# Each builder returns a partial dict with just the trade mechanics.  The
# top-level build_spread() wraps rejection checks, sizing, and metadata
# around the result.
#
# Rejection reasons are accumulated in a list so we can tell the user
# *everything* that's wrong, not just the first problem.

def _build_bull_call_debit(chain: pd.DataFrame, S: float) -> dict:
    """Long call at ~0.55 delta, short call at ~0.30 delta (both same expiry)."""
    calls = chain[chain["option_type"] == "call"].copy()

    long_leg  = _pick_by_delta(calls, DEBIT_LONG_DELTA,  DEBIT_LONG_DELTA_RANGE)
    if long_leg is None:
        return {"error": "no eligible call for long leg"}

    # Short candidates must have strike STRICTLY above the long strike
    short_pool = calls[calls["strike"] > float(long_leg["strike"])]
    short_leg  = _pick_by_delta(short_pool, DEBIT_SHORT_DELTA,
                                DEBIT_SHORT_DELTA_RANGE)
    if short_leg is None:
        return {"error": "no eligible call for short leg above long strike"}

    long_ask  = float(long_leg["ask"]  or 0.0)
    short_bid = float(short_leg["bid"] or 0.0)
    eff_long, eff_short = _apply_friction(long_ask, short_bid)
    net_debit = eff_long - eff_short

    width, _ = _check_width(float(long_leg["strike"]),
                            float(short_leg["strike"]), S)
    max_profit = max(width - net_debit, 0.0)
    max_loss   = net_debit
    breakeven  = float(long_leg["strike"]) + net_debit

    return {
        "strategy_type": "BULL_CALL_DEBIT",
        "direction":     "debit",
        "long_leg":      long_leg,
        "short_leg":     short_leg,
        "long_price":    eff_long,
        "short_price":   eff_short,
        "net":           net_debit,        # positive = paid
        "width":         width,
        "max_profit":    max_profit,
        "max_loss":      max_loss,
        "breakeven":     breakeven,
    }


def _build_bear_put_debit(chain: pd.DataFrame, S: float) -> dict:
    """
    Long put at ~-0.55 delta (|delta|~0.55), short put further OTM.

    STRUCTURE DECISION (put_structure_study.py)
    -------------------------------------------
    We use a 0.25 short-delta (not the default 0.30) because the structure
    study showed that a wider short strike captures more of the underlying
    downside move -- the decay analysis found BUY PUTS has +1.44% 20d edge
    on the underlying, and a tighter short leg gave most of that back.

    We also pair this with a LONGER expiration (60 DTE vs the default 35);
    that override happens in select_expiration() via the per-signal DTE map.
    """
    puts = chain[chain["option_type"] == "put"].copy()

    long_leg  = _pick_by_delta(puts, DEBIT_LONG_DELTA, DEBIT_LONG_DELTA_RANGE)
    if long_leg is None:
        return {"error": "no eligible put for long leg"}

    # Short candidates must have strike STRICTLY below the long strike.
    # Use the tuned 0.25-delta target so the short leg stays further OTM --
    # the structure study justifies this against the default 0.30.
    PUT_SHORT_DELTA       = 0.25
    PUT_SHORT_DELTA_RANGE = (0.20, 0.30)
    short_pool = puts[puts["strike"] < float(long_leg["strike"])]
    short_leg  = _pick_by_delta(short_pool, PUT_SHORT_DELTA,
                                PUT_SHORT_DELTA_RANGE)
    if short_leg is None:
        return {"error": "no eligible put for short leg below long strike"}

    long_ask  = float(long_leg["ask"]  or 0.0)
    short_bid = float(short_leg["bid"] or 0.0)
    eff_long, eff_short = _apply_friction(long_ask, short_bid)
    net_debit = eff_long - eff_short

    width, _ = _check_width(float(long_leg["strike"]),
                            float(short_leg["strike"]), S)
    max_profit = max(width - net_debit, 0.0)
    max_loss   = net_debit
    breakeven  = float(long_leg["strike"]) - net_debit

    return {
        "strategy_type": "BEAR_PUT_DEBIT",
        "direction":     "debit",
        "long_leg":      long_leg,
        "short_leg":     short_leg,
        "long_price":    eff_long,
        "short_price":   eff_short,
        "net":           net_debit,
        "width":         width,
        "max_profit":    max_profit,
        "max_loss":      max_loss,
        "breakeven":     breakeven,
    }


def _build_bull_put_credit(chain: pd.DataFrame, S: float) -> dict:
    """Short put at ~-0.20 delta; long put $5 (or $2.50) BELOW the short strike."""
    puts = chain[chain["option_type"] == "put"].copy()

    # Short leg: |delta| ~ 0.20, strike below spot
    below_spot = puts[puts["strike"] < S]
    short_leg  = _pick_by_delta(below_spot, CREDIT_SHORT_DELTA,
                                CREDIT_SHORT_DELTA_RANGE)
    if short_leg is None:
        return {"error": "no eligible put for short leg below spot"}

    long_leg = _pick_width_partner(puts, float(short_leg["strike"]),
                                   S, direction="below")
    if long_leg is None:
        return {"error": "no eligible put for long-leg hedge below short strike"}

    long_ask  = float(long_leg["ask"]  or 0.0)
    short_bid = float(short_leg["bid"] or 0.0)
    eff_long, eff_short = _apply_friction(long_ask, short_bid)
    # Credit: money collected net of the leg we buy as a hedge
    net_credit = eff_short - eff_long

    width, _  = _check_width(float(long_leg["strike"]),
                             float(short_leg["strike"]), S)
    max_profit = net_credit
    max_loss   = max(width - net_credit, 0.0)
    breakeven  = float(short_leg["strike"]) - net_credit

    return {
        "strategy_type": "BULL_PUT_CREDIT",
        "direction":     "credit",
        "long_leg":      long_leg,
        "short_leg":     short_leg,
        "long_price":    eff_long,
        "short_price":   eff_short,
        "net":           net_credit,       # positive = received
        "width":         width,
        "max_profit":    max_profit,
        "max_loss":      max_loss,
        "breakeven":     breakeven,
    }


def _build_bear_call_credit(chain: pd.DataFrame, S: float) -> dict:
    """Short call at ~0.20 delta; long call $5 (or $2.50) ABOVE the short strike."""
    calls = chain[chain["option_type"] == "call"].copy()

    # Short leg: |delta| ~ 0.20, strike above spot
    above_spot = calls[calls["strike"] > S]
    short_leg  = _pick_by_delta(above_spot, CREDIT_SHORT_DELTA,
                                CREDIT_SHORT_DELTA_RANGE)
    if short_leg is None:
        return {"error": "no eligible call for short leg above spot"}

    long_leg = _pick_width_partner(calls, float(short_leg["strike"]),
                                   S, direction="above")
    if long_leg is None:
        return {"error": "no eligible call for long-leg hedge above short strike"}

    long_ask  = float(long_leg["ask"]  or 0.0)
    short_bid = float(short_leg["bid"] or 0.0)
    eff_long, eff_short = _apply_friction(long_ask, short_bid)
    net_credit = eff_short - eff_long

    width, _ = _check_width(float(long_leg["strike"]),
                            float(short_leg["strike"]), S)
    max_profit = net_credit
    max_loss   = max(width - net_credit, 0.0)
    breakeven  = float(short_leg["strike"]) + net_credit

    return {
        "strategy_type": "BEAR_CALL_CREDIT",
        "direction":     "credit",
        "long_leg":      long_leg,
        "short_leg":     short_leg,
        "long_price":    eff_long,
        "short_price":   eff_short,
        "net":           net_credit,
        "width":         width,
        "max_profit":    max_profit,
        "max_loss":      max_loss,
        "breakeven":     breakeven,
    }


# Map directional signals -> spread builders
_SIGNAL_TO_BUILDER = {
    SIG_BUY_CALLS:  _build_bull_call_debit,
    SIG_BUY_PUTS:   _build_bear_put_debit,
    SIG_SELL_PUTS:  _build_bull_put_credit,
    SIG_SELL_CALLS: _build_bear_call_credit,
}


# ===========================================================================
# Top-level build entry point + output assembly (Step 5)
# ===========================================================================

OUTPUT_COLS = [
    "ticker", "date", "strategy_type", "expiration", "DTE",
    "long_strike", "long_delta", "long_price",
    "short_strike", "short_delta", "short_price",
    "width", "net_debit_or_credit", "max_profit", "max_loss", "breakeven",
    "contracts", "total_risk", "total_max_profit",
    "accepted", "rejection_reason",
]


def build_spread(
    ticker: str,
    signal: str,
    spot_price: float,
    options_chain: pd.DataFrame,
    today: datetime.date = None,
    r: float = RISK_FREE_RATE,
) -> dict:
    """
    Main entry point -- turn (signal, options chain, spot) into a trade ticket.

    Parameters
    ----------
    ticker : str
    signal : one of SIG_BUY_CALLS / SIG_BUY_PUTS / SIG_SELL_PUTS /
             SIG_SELL_CALLS.  Anything else returns a rejected row.
    spot_price : current underlying price (float).
    options_chain : DataFrame with columns {strike, option_type, bid, ask,
             impliedVolatility, openInterest, expiration}.  One row per contract.
    today : date of 'entry'.  Defaults to datetime.date.today().  Passing an
             explicit date is what lets the backtester reuse this for historical
             simulation.
    r : risk-free rate, annual continuous (0.045 default).

    Returns
    -------
    dict keyed by OUTPUT_COLS.  `accepted` is bool; `rejection_reason` is
    None or a human-readable string.
    """
    if today is None:
        today = datetime.date.today()

    # Start with a rejected template; fill in as we make progress so callers
    # always get a consistent schema (great for CSVs).
    out = {c: None for c in OUTPUT_COLS}
    out.update({
        "ticker":    ticker,
        "date":      today.isoformat(),
        "accepted":  False,
        "rejection_reason": "not evaluated",
        "contracts": 0,
        "total_risk": 0.0,
        "total_max_profit": 0.0,
    })

    # --- Signal validation ---
    if signal not in _SIGNAL_TO_BUILDER:
        out["rejection_reason"] = f"no spread defined for signal '{signal}'"
        return out

    # --- Step 1: pick expiration ---
    # Per-signal DTE overrides.  BUY PUTS needs more time for the thesis
    # to develop (see put_structure_study.py: 60 DTE beat 35 DTE by
    # ~$24k on a 168-trade sample, Sharpe 1.98 vs 0.89).
    _SIGNAL_DTE_TGT = {SIG_BUY_PUTS: 60}
    _SIGNAL_DTE_WIN = {SIG_BUY_PUTS: (50, 70)}
    dte_tgt   = _SIGNAL_DTE_TGT.get(signal, DTE_TARGET)
    dte_lo, dte_hi = _SIGNAL_DTE_WIN.get(signal, (DTE_MIN, DTE_MAX))
    exp_pick = select_expiration(
        options_chain, today=today,
        dte_target=dte_tgt, dte_min=dte_lo, dte_max=dte_hi,
    )
    if exp_pick is None:
        out["rejection_reason"] = (
            f"no expiration in range [{dte_lo},{dte_hi}] DTE available")
        return out
    expiration_str, dte, T = exp_pick

    # Narrow to that single expiration for the rest of the logic
    chain = options_chain[options_chain["expiration"] == expiration_str].copy()
    if chain.empty:
        out["rejection_reason"] = f"chain for expiration {expiration_str} is empty"
        return out

    # --- Step 2: enrich with per-strike delta ---
    # Use each contract's quoted IV (not a single ATM IV).  That way an OTM
    # strike picks up the vol-skew naturally -- our delta estimates reflect
    # the market's actual pricing rather than a flat-surface approximation.
    chain = enrich_with_delta(chain, S=spot_price, T=T, r=r)

    # --- Step 3: strategy-specific strike selection ---
    builder = _SIGNAL_TO_BUILDER[signal]
    legs = builder(chain, S=spot_price)
    if legs.get("error"):
        out["rejection_reason"] = legs["error"]
        out["expiration"] = expiration_str
        out["DTE"] = dte
        return out

    long_leg   = legs["long_leg"]
    short_leg  = legs["short_leg"]
    direction  = legs["direction"]            # "debit" or "credit"
    net        = legs["net"]                  # positive debit or credit
    width      = legs["width"]
    max_profit = legs["max_profit"]
    max_loss   = legs["max_loss"]
    breakeven  = legs["breakeven"]

    # Fill the concrete leg fields early so a downstream reject still keeps
    # the diagnostic information visible.
    out.update({
        "strategy_type":       legs["strategy_type"],
        "expiration":          expiration_str,
        "DTE":                 dte,
        "long_strike":         float(long_leg["strike"]),
        "long_delta":          round(float(long_leg["delta"]),  4),
        "long_price":          round(float(legs["long_price"]), 4),
        "short_strike":        float(short_leg["strike"]),
        "short_delta":         round(float(short_leg["delta"]), 4),
        "short_price":         round(float(legs["short_price"]), 4),
        "width":               round(float(width), 4),
        "net_debit_or_credit": round(float(net), 4),
        "max_profit":          round(float(max_profit), 4),
        "max_loss":            round(float(max_loss), 4),
        "breakeven":           round(float(breakeven), 4),
    })

    # --- Rejection checks ---
    rejections: list[str] = []

    # Liquidity on each leg
    for leg_name, leg in (("long", long_leg), ("short", short_leg)):
        ok, why = _leg_liquidity_ok(leg)
        if not ok:
            rejections.append(f"{leg_name} leg illiquid: {why}")

    # Risk/reward
    if direction == "debit":
        if width > 0 and net / width > DEBIT_MAX_COST_FRAC:
            rejections.append(
                f"net debit {net:.2f} > {DEBIT_MAX_COST_FRAC:.0%} of "
                f"width {width:.2f}")
    else:  # credit
        if width > 0 and net / width < CREDIT_MIN_PREMIUM_FR:
            rejections.append(
                f"net credit {net:.2f} < {CREDIT_MIN_PREMIUM_FR:.0%} of "
                f"width {width:.2f}")

    # Structural sanity -- should not fire given the selection rules, but
    # guards against chain data anomalies.
    if max_loss <= 0:
        rejections.append(f"non-positive max loss {max_loss:.2f}")

    # --- Step 4: position sizing ---
    if not rejections:
        contracts, sized_ok, size_reason = size_position(max_loss)
        if not sized_ok:
            rejections.append(f"sizing rejected: {size_reason}")
        else:
            out["contracts"]        = contracts
            out["total_risk"]       = round(contracts * max_loss * 100.0, 2)
            out["total_max_profit"] = round(contracts * max_profit * 100.0, 2)

    if rejections:
        out["accepted"]         = False
        out["rejection_reason"] = "; ".join(rejections)
    else:
        out["accepted"]         = True
        out["rejection_reason"] = None

    return out


# ===========================================================================
# Save to CSV
# ===========================================================================

def save_spread(spread: dict, ticker: str) -> str:
    """Write a single spread dict to data/raw/spreads_{ticker}_{date}.csv."""
    raw_dir = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "raw"))
    os.makedirs(raw_dir, exist_ok=True)

    date_str = datetime.date.today().strftime("%Y-%m-%d")
    filepath = os.path.join(raw_dir, f"spreads_{ticker}_{date_str}.csv")

    df = pd.DataFrame([{c: spread.get(c) for c in OUTPUT_COLS}])
    df.to_csv(filepath, index=False)
    print(f"[spread_builder] Saved -> {filepath}")
    return filepath


# ===========================================================================
# Step 6 -- Backtest / daily P&L simulation
# ===========================================================================

def _spread_value(
    spread: dict,
    S: float,
    T: float,
    r: float,
    iv_long: float,
    iv_short: float,
) -> float:
    """
    Mark-to-market the spread (per share) at (S, T, iv).

    spread_value = long_leg_BS_price - short_leg_BS_price

    For DEBIT spreads (we own the spread), a higher spread_value means
    profit.  For CREDIT spreads (we shorted the spread), a higher
    spread_value means loss -- we'd have to pay more to close it.

    iv_long and iv_short can differ to let callers model skew shift.
    Pass the same value for both if you don't want to simulate skew.
    """
    is_call_long  = spread["strategy_type"] in ("BULL_CALL_DEBIT", "BEAR_CALL_CREDIT")
    is_call_short = is_call_long    # vertical -> same option type on both legs

    long_val  = bs_price(S, spread["long_strike"],  T, r, iv_long,  is_call_long)
    short_val = bs_price(S, spread["short_strike"], T, r, iv_short, is_call_short)
    return long_val - short_val


def simulate_spread_pnl(
    spread: dict,
    price_series: pd.Series,
    iv_series: Optional[pd.Series] = None,
    r: float = RISK_FREE_RATE,
    entry_date: datetime.date = None,
) -> dict:
    """
    Walk day-by-day from entry through expiration and apply the exit rules.

    Parameters
    ----------
    spread : the dict returned by build_spread() (must be `accepted=True`
             with populated long_strike/short_strike/etc).
    price_series : pd.Series of underlying closes indexed by date.  Must
             contain entry_date and subsequent dates up to/through expiration.
    iv_series : pd.Series of daily IVs (decimals), same index as price_series.
             If None, we hold IV constant at the contract's entry IV (crude
             but fine for a first approximation).
    r : risk-free rate.
    entry_date : date of entry.  If None, uses the first index of price_series.

    Returns
    -------
    dict with:
        exit_date, exit_reason, days_held,
        entry_spread_value, exit_spread_value,
        pnl_per_contract, pnl_total, pnl_pct (of max_loss),
        daily (pd.DataFrame with date, S, T, spread_value, pnl)
    """
    if price_series.empty:
        return {"error": "empty price_series"}

    if entry_date is None:
        entry_date = pd.to_datetime(price_series.index[0]).date()

    exp_date = datetime.date.fromisoformat(spread["expiration"])
    direction = ("debit" if spread["strategy_type"].endswith("_DEBIT")
                 else "credit")
    entry_net = float(spread["net_debit_or_credit"])
    max_profit = float(spread["max_profit"])
    max_loss   = float(spread["max_loss"])
    contracts  = int(spread.get("contracts") or 1)

    # Stable IV series: if caller didn't pass one, hold at entry IV.
    # If they passed one but it's short, forward-fill.
    if iv_series is None:
        # Flat at the short leg's IV (a reasonable "average" of the two legs)
        # -- the explicit spec just asks for "current IV", so we need something;
        # flat is the simplest honest choice.
        iv_default = 0.30
        iv_series = pd.Series(iv_default, index=price_series.index)
    else:
        iv_series = iv_series.reindex(price_series.index).ffill().bfill()

    # Walk forward
    daily_rows = []
    exit_reason = "expiration"
    exit_date   = exp_date
    exit_value  = 0.0

    dates = list(price_series.index)

    for dt in dates:
        d = pd.to_datetime(dt).date()
        if d < entry_date:
            continue
        if d > exp_date:
            break

        S  = float(price_series.loc[dt])
        iv = float(iv_series.loc[dt])
        T  = max((exp_date - d).days, 0) / 365.0
        dte_today = (exp_date - d).days

        current_val = _spread_value(spread, S, T, r, iv, iv)

        if direction == "debit":
            # You OWN the spread: you paid `entry_net`.
            # Closing value today = current_val.  P&L = current_val - entry_net.
            pnl_per_share = current_val - entry_net
        else:
            # You are SHORT the spread: you received `entry_net`.
            # P&L = entry_net - current_val (close by buying back).
            pnl_per_share = entry_net - current_val

        pnl_per_contract = pnl_per_share * 100.0
        pnl_total        = pnl_per_contract * contracts

        daily_rows.append({
            "date":          d,
            "dte":           dte_today,
            "S":             S,
            "iv":            iv,
            "spread_value":  current_val,
            "pnl_per_share": pnl_per_share,
            "pnl_total":     pnl_total,
        })

        # --- Exit rules, checked in the order specified ---

        # 1) Stop loss
        if direction == "debit":
            # close if pnl <= -80% of entry_net * 100 * contracts
            # i.e. per-share pnl <= -0.80 * entry_net
            if pnl_per_share <= -STOP_LOSS_DEBIT_FRAC * entry_net:
                exit_reason = "stop_loss"
                exit_date   = d
                exit_value  = current_val
                break
        else:
            # credit: close if current value >= 2x entry credit (loss doubled)
            if current_val >= STOP_LOSS_CREDIT_MULT * entry_net:
                exit_reason = "stop_loss"
                exit_date   = d
                exit_value  = current_val
                break

        # 2) Profit target: >= 50% of max_profit
        # max_profit is per-share; compare to pnl_per_share
        if pnl_per_share >= PROFIT_TARGET_FRAC * max_profit:
            exit_reason = "profit_target"
            exit_date   = d
            exit_value  = current_val
            break

        # 3) Time stop
        if dte_today <= TIME_STOP_DTE and d != entry_date:
            # (skip on entry day itself to avoid closing instantly if entry
            # falls exactly at the time-stop DTE)
            exit_reason = "time_stop"
            exit_date   = d
            exit_value  = current_val
            break

        # 4) Expiration handled by the loop terminator

    if not daily_rows:
        return {"error": "no in-range days to simulate"}

    daily_df = pd.DataFrame(daily_rows)

    # If we fell out of the loop without breaking, the last daily row is
    # expiration day -- use its spread_value.
    last = daily_df.iloc[-1]
    if exit_reason == "expiration":
        exit_date  = last["date"]
        exit_value = last["spread_value"]

    entry_value = daily_df.iloc[0]["spread_value"]
    if direction == "debit":
        final_pnl_ps = exit_value - entry_net
    else:
        final_pnl_ps = entry_net - exit_value

    final_pnl_total = final_pnl_ps * 100.0 * contracts
    # Percent of max loss (negative = percent of max loss used; positive = P&L / max loss)
    pct_of_max = (final_pnl_ps / max_loss * 100.0) if max_loss > 0 else 0.0

    return {
        "exit_date":          exit_date,
        "exit_reason":        exit_reason,
        "days_held":          (exit_date - entry_date).days,
        "entry_spread_value": round(entry_value, 4),
        "exit_spread_value":  round(exit_value, 4),
        "pnl_per_share":      round(final_pnl_ps, 4),
        "pnl_per_contract":   round(final_pnl_ps * 100.0, 2),
        "pnl_total":          round(final_pnl_total, 2),
        "pnl_pct_of_max":     round(pct_of_max, 2),
        "daily":              daily_df,
    }


# ===========================================================================
# Smoke test -- run on AAPL with today's real data (satisfies spec Step 7)
# ===========================================================================

def _smoke_test_aapl() -> None:
    """
    End-to-end test:
      1. Load AAPL's current signal
      2. Load AAPL's options chain
      3. Build the spread
      4. Print all trade details + both BS prices vs quoted market mid
      5. Simulate entry + one day of mark-to-market
    """
    from signals.signal_engine import generate_signal
    from data.options_fetcher import fetch_options_chain
    import yfinance as yf

    bar = "=" * 72

    print(bar)
    print("  SPREAD BUILDER SMOKE TEST -- AAPL")
    print(bar)

    # 1) Signal
    sig_df = generate_signal("AAPL", save=False)
    row = sig_df.iloc[0]
    signal = str(row["signal"])
    print(f"\n[1] Current AAPL signal : {signal}")
    print(f"    sentiment            : {row['sentiment_score']:+.4f}")
    print(f"    IV Rank              : {row['iv_rank_pct']:.1f}%  "
          f"(real_iv={row.get('real_iv')})")
    print(f"    confidence           : {row['confidence']:.2f}")

    if signal in (SIG_NEUTRAL, SIG_IV_CRUSH):
        print(f"\n[!] Signal is {signal} -- no spread will be built for this "
              f"signal class.  Forcing a BUY CALLS build for demonstration.")
        signal_for_build = SIG_BUY_CALLS
    else:
        signal_for_build = signal

    # 2) Options chain + spot (re-fetch for today's strikes)
    print(f"\n[2] Fetching AAPL options chain + spot price...")
    chain = fetch_options_chain("AAPL", save=False)
    if chain.empty:
        print("[!] No options chain -- aborting smoke test.")
        return

    # options_fetcher picks ONE near-term expiration.  For the spread builder
    # we want the full option surface so we can pick 30-45 DTE.  Re-fetch all
    # expirations from yfinance directly.
    print("    Expanding to all expirations for DTE window selection...")
    yf_t = yf.Ticker("AAPL")
    spot = float(yf_t.fast_info["lastPrice"])
    all_frames = []
    for exp_str in yf_t.options:
        try:
            oc = yf_t.option_chain(exp_str)
            c  = oc.calls.copy(); c["option_type"] = "call"; c["expiration"] = exp_str
            p  = oc.puts.copy();  p["option_type"] = "put";  p["expiration"] = exp_str
            all_frames.append(c); all_frames.append(p)
        except Exception as e:
            print(f"    WARN chain fetch failed for {exp_str}: {e}")
    full_chain = pd.concat(all_frames, ignore_index=True)

    print(f"    Spot price           : ${spot:.2f}")
    print(f"    Full chain contracts : {len(full_chain)} across "
          f"{full_chain['expiration'].nunique()} expirations")

    # 3) Build spread
    spread = build_spread(
        ticker       = "AAPL",
        signal       = signal_for_build,
        spot_price   = spot,
        options_chain= full_chain,
        r            = RISK_FREE_RATE,
    )

    print(f"\n[3] SPREAD DETAILS")
    for k in OUTPUT_COLS:
        v = spread.get(k)
        if isinstance(v, float):
            v = f"{v:.4f}"
        print(f"    {k:<22s}: {v}")

    # 4) BS price vs quoted market mid (verification)
    if spread.get("strategy_type"):
        print(f"\n[4] BS-VERIFICATION (leg prices, per share)")
        narrow = full_chain[full_chain["expiration"] == spread["expiration"]]
        T_years = spread["DTE"] / 365.0

        for leg_name, strike_key in [("long", "long_strike"),
                                     ("short", "short_strike")]:
            K = spread[strike_key]
            is_call = spread["strategy_type"] in ("BULL_CALL_DEBIT",
                                                   "BEAR_CALL_CREDIT")
            opt_type = "call" if is_call else "put"
            leg_row = narrow[(narrow["strike"] == K) &
                             (narrow["option_type"] == opt_type)]
            if leg_row.empty:
                continue
            r0 = leg_row.iloc[0]
            mid = _leg_mid(float(r0["bid"] or 0), float(r0["ask"] or 0))
            iv  = float(r0["impliedVolatility"] or 0)
            bs  = bs_price(spot, K, T_years, RISK_FREE_RATE, iv, is_call)

            print(f"    {leg_name:<6s} K={K:<7.2f} type={opt_type:<4s}  "
                  f"market_mid=${mid:<6.2f}  BS@iv={iv:.2%} "
                  f"-> ${bs:<6.2f}  diff=${bs-mid:+.2f}")

    print(f"\n[5] ACCEPT/REJECT")
    print(f"    accepted         : {spread.get('accepted')}")
    print(f"    rejection_reason : {spread.get('rejection_reason')}")

    # 5) Simulated entry + next-day mark-to-market.
    # Always run the simulator for verification, even if the spread was
    # rejected -- we temporarily force 1 contract so we can observe the
    # engine's output. This is demo-only; the persisted spread still has
    # contracts=0 if rejected.
    print(f"\n[6] SIMULATED ENTRY + DAY-1 MARK-TO-MARKET")
    demo_spread = dict(spread)
    if not demo_spread.get("accepted"):
        print(f"    (trade rejected in production; forcing 1 contract for demo)")
        demo_spread["contracts"]         = 1
        demo_spread["total_risk"]        = demo_spread["max_loss"] * 100
        demo_spread["total_max_profit"]  = demo_spread["max_profit"] * 100
    if True:
        spread = demo_spread
        print(f"    Contracts        : {spread['contracts']}")
        print(f"    Total risk       : ${spread['total_risk']:.2f}")
        print(f"    Total max profit : ${spread['total_max_profit']:.2f}")

        # Build a 2-day price/IV series: entry day at spot, day-1 at spot * 1.005
        # (a mild +0.5% move, just to demonstrate the simulator).
        today_d = datetime.date.today()
        day1_d  = today_d + datetime.timedelta(days=1)
        idx     = pd.DatetimeIndex([today_d, day1_d])
        price_ser = pd.Series([spot, spot * 1.005], index=idx)

        # Use the chain's ATM IV as a reasonable flat IV for simulation
        narrow = full_chain[full_chain["expiration"] == spread["expiration"]]
        atm_row = narrow.iloc[(narrow["strike"] - spot).abs().argsort()[:2]]
        flat_iv = float(atm_row["impliedVolatility"].mean() or 0.25)
        iv_ser  = pd.Series([flat_iv, flat_iv], index=idx)

        sim = simulate_spread_pnl(spread, price_ser, iv_ser,
                                  entry_date=today_d)
        if "error" in sim:
            print(f"    simulate error: {sim['error']}")
        else:
            daily = sim["daily"]
            print(f"    Entry spread val : ${sim['entry_spread_value']:.4f}/share")
            if len(daily) >= 2:
                d1 = daily.iloc[1]
                print(f"    Day 1 spot       : ${d1['S']:.2f} "
                      f"(entry was ${daily.iloc[0]['S']:.2f})")
                print(f"    Day 1 spread val : ${d1['spread_value']:.4f}/share")
                print(f"    Day 1 P&L total  : ${d1['pnl_total']:+.2f} "
                      f"({d1['pnl_per_share']:+.4f}/share)")
            print(f"    Final exit       : {sim['exit_reason']} "
                  f"on {sim['exit_date']} "
                  f"(P&L ${sim['pnl_total']:+.2f})")

    print(f"\n{bar}")


if __name__ == "__main__":
    _smoke_test_aapl()

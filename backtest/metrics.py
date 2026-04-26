# =============================================================================
# backtest/metrics.py — Performance statistics from the trade log
#
# METRICS CALCULATED
# ──────────────────
# total_return    Sum of all P&L (dollar terms, per-share)
# win_rate        Fraction of trades that were profitable
# sharpe_ratio    Annualised Sharpe using per-trade P&L.
#                 Since we hold for HOLD_DAYS trading days, the annualisation
#                 factor is sqrt(252 / HOLD_DAYS).
# max_drawdown    Largest peak-to-trough decline in the *cumulative* P&L curve.
#                 This is the most intuitive measure of worst-case pain.
# avg_pnl         Mean P&L per trade
# profit_factor   Sum of winning P&L / |sum of losing P&L| — a complementary
#                 metric to win rate.  Values > 1.5 are generally considered
#                 acceptable; > 2.0 is strong.
# =============================================================================

import os
import sys
import glob

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.engine import HOLD_DAYS


def _raw_dir() -> str:
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    )


def load_trade_log(ticker: str, demo_mode: bool = False) -> pd.DataFrame:
    """
    Load the trade log CSV produced by engine.py.

    Parameters
    ----------
    ticker    : stock symbol
    demo_mode : if True, look for backtest_{ticker}_demo.csv

    Returns
    -------
    pd.DataFrame or empty DataFrame if file not found.
    """
    suffix = "_demo" if demo_mode else ""
    path = os.path.join(_raw_dir(), f"backtest_{ticker}{suffix}.csv")

    if not os.path.exists(path):
        # Try the other variant before giving up
        alt_suffix = "" if demo_mode else "_demo"
        alt_path   = os.path.join(_raw_dir(), f"backtest_{ticker}{alt_suffix}.csv")
        if os.path.exists(alt_path):
            print(f"[metrics] Note: using {'demo' if alt_suffix == '_demo' else 'real'} "
                  f"data file ({os.path.basename(alt_path)}).")
            path = alt_path
        else:
            print(f"[metrics] No trade log found for {ticker}. "
                  "Run backtest/engine.py first.")
            return pd.DataFrame()

    df = pd.read_csv(path, parse_dates=["entry_date", "exit_date"])
    return df


# ---------------------------------------------------------------------------
# Individual metric functions
# ---------------------------------------------------------------------------

def total_return(trades: pd.DataFrame) -> float:
    """Sum of all per-share P&L across all trades."""
    return round(float(trades["pnl"].sum()), 4)


def win_rate(trades: pd.DataFrame) -> float:
    """Fraction of trades with positive P&L. Range: 0–1."""
    if trades.empty:
        return 0.0
    return round(float((trades["pnl"] > 0).mean()), 4)


def sharpe_ratio(trades: pd.DataFrame, risk_free_daily: float = 0.0) -> float:
    """
    Annualised Sharpe ratio of per-trade P&L.

    We annualise by assuming each trade represents one HOLD_DAYS period and
    there are 252/HOLD_DAYS such periods per year.
    """
    if len(trades) < 2:
        return 0.0
    pnl = trades["pnl"]
    mean = pnl.mean() - risk_free_daily
    std  = pnl.std(ddof=1)
    if std == 0:
        return 0.0
    # Annualisation factor: scale by number of trading periods per year
    ann_factor = np.sqrt(252 / HOLD_DAYS)
    return round(float((mean / std) * ann_factor), 4)


def max_drawdown(trades: pd.DataFrame) -> float:
    """
    Maximum peak-to-trough decline in the cumulative P&L curve.
    Returned as a *negative* dollar amount (e.g. -3.25 means we lost $3.25/share
    from the equity peak before recovering).
    """
    if trades.empty:
        return 0.0
    cumulative = trades["pnl"].cumsum()
    running_max = cumulative.cummax()
    drawdown    = cumulative - running_max
    return round(float(drawdown.min()), 4)


def profit_factor(trades: pd.DataFrame) -> float:
    """
    Gross profit / gross loss.  > 1.0 means the strategy makes more than
    it loses in absolute dollar terms.
    """
    wins   = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    losses = trades.loc[trades["pnl"] < 0, "pnl"].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return round(float(wins / abs(losses)), 4)


def signal_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    """
    Per-signal-type performance table: count, win rate, total P&L, avg P&L.
    Useful for diagnosing which signal types are working.
    """
    if trades.empty:
        return pd.DataFrame()

    rows = []
    for sig, group in trades.groupby("signal"):
        rows.append({
            "signal":    sig,
            "count":     len(group),
            "win_rate":  round(float((group["pnl"] > 0).mean()), 4),
            "total_pnl": round(float(group["pnl"].sum()), 4),
            "avg_pnl":   round(float(group["pnl"].mean()), 4),
        })
    return pd.DataFrame(rows).sort_values("total_pnl", ascending=False)


def cumulative_pnl_series(trades: pd.DataFrame) -> pd.Series:
    """Return the running cumulative P&L indexed by exit_date."""
    if trades.empty:
        return pd.Series(dtype=float)
    s = trades.set_index("exit_date")["pnl"].sort_index().cumsum()
    return s


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

_W = 52

def print_summary(ticker: str, trades: pd.DataFrame) -> None:
    """Print a formatted performance summary card."""
    bar = "=" * _W

    is_demo = trades["is_synthetic"].any() if "is_synthetic" in trades.columns else False

    print(f"\n{bar}")
    label = "DEMO DATA" if is_demo else "REAL DATA"
    print(f"  BACKTEST RESULTS: {ticker}  [{label}]")
    print(bar)

    if trades.empty:
        print("  No trades — all signals were NEUTRAL.")
        print(bar)
        return

    n      = len(trades)
    start  = trades["entry_date"].min().date() if hasattr(trades["entry_date"].min(), "date") else trades["entry_date"].min()
    end    = trades["exit_date"].max().date()  if hasattr(trades["exit_date"].max(), "date")  else trades["exit_date"].max()

    print(f"  Period           : {start} to {end}")
    print(f"  Total trades     : {n}")
    print(f"  Hold period      : {HOLD_DAYS} trading days per trade")
    print()
    print(f"  RETURNS")
    print(f"    Total P&L      : ${total_return(trades):+.2f} per share")
    print(f"    Avg P&L/trade  : ${trades['pnl'].mean():+.2f} per share")
    print(f"    Avg return/trade: {trades['pnl_pct'].mean():+.1f}%")
    print()
    print(f"  RISK")
    print(f"    Win rate       : {win_rate(trades):.1%}")
    print(f"    Sharpe ratio   : {sharpe_ratio(trades):.2f}")
    print(f"    Max drawdown   : ${max_drawdown(trades):.2f} per share")
    print(f"    Profit factor  : {profit_factor(trades):.2f}")
    print()

    breakdown = signal_breakdown(trades)
    if not breakdown.empty:
        print(f"  BY SIGNAL TYPE")
        for _, r in breakdown.iterrows():
            print(f"    {r['signal']:<15s}: {int(r['count']):2d} trades  "
                  f"WR={r['win_rate']:.0%}  "
                  f"P&L=${r['total_pnl']:+.2f}")

    # Visual cumulative P&L sparkline (40 chars wide)
    cum = trades["pnl"].cumsum().values
    if len(cum) >= 2:
        lo, hi = cum.min(), cum.max()
        rng = hi - lo
        if rng > 0:
            scaled = [(v - lo) / rng * 6 for v in cum]
            chars  = " ._-~=^"
            line   = "".join(chars[min(int(s), 6)] for s in scaled)
            print()
            print(f"  Cumulative P&L sparkline:")
            print(f"    [{line}]")
            print(f"     ${lo:+.2f}              ${hi:+.2f}")

    print(bar)


# ---------------------------------------------------------------------------
# Convenience wrapper: load + print in one call
# ---------------------------------------------------------------------------

def run_metrics(ticker: str, demo_mode: bool = False) -> pd.DataFrame:
    trades = load_trade_log(ticker, demo_mode)
    if not trades.empty:
        print_summary(ticker, trades)
    return trades


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    demo = "--demo" in sys.argv
    run_metrics("AAPL", demo_mode=demo)

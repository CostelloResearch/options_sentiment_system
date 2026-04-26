# =============================================================================
# signals/earnings_filter.py — Earnings calendar awareness
#
# WHY THIS MATTERS FOR OPTIONS
# ─────────────────────────────
# Implied volatility reliably spikes in the 1–3 days before an earnings
# announcement (because traders buy options to speculate on the move), then
# "crushes" sharply after the announcement (the uncertainty resolves).
#
# This creates two problems for our normal signal logic:
#   1. A high IV Rank near earnings is *expected*, not a true edge — options
#      are expensive because risk is real, not mispriced.
#   2. If we buy options just before earnings, we're fighting against both
#      the direction risk AND the inevitable post-earnings vol crush.
#
# This module:
#   a) Identifies the earnings window for each ticker
#   b) Suppresses normal BUY/SELL signals during that window
#   c) Generates a special IV_CRUSH signal for the narrow pre-earnings
#      window where selling premium is historically effective
#
# WINDOW DEFINITIONS
# ──────────────────
#   PRE_EARNINGS_DAYS  = 3  → flag signals from T-3 to earnings day
#   POST_EARNINGS_DAYS = 1  → flag signals for 1 day post-earnings
#   IV_CRUSH_ENTRY_DAYS = 2 → IV_CRUSH only triggered in the final 2 days
#                             before earnings (sweetspot: IV is highest,
#                             and the crush is most predictable)
#
# CACHING
# ────────
# Finnhub API calls are cached in memory for the lifetime of the Python
# process.  This avoids hammering the API when the backtest loop calls
# is_earnings_window() for every day in the simulation.
# =============================================================================

import os
import sys
import datetime

import finnhub

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

# ---------------------------------------------------------------------------
# Constants  (tune here rather than in config.py — these are filter internals)
# ---------------------------------------------------------------------------
PRE_EARNINGS_DAYS   = 3   # days before earnings to enter the earnings window
POST_EARNINGS_DAYS  = 1   # days after earnings to stay in the earnings window
IV_CRUSH_ENTRY_DAYS = 2   # final N days before earnings → IV_CRUSH signal eligible
IV_CRUSH_IV_THRESHOLD = 0.80  # IV rank must exceed this to trigger IV_CRUSH

# ---------------------------------------------------------------------------
# Module-level cache: maps ticker -> list of datetime.date
# Populated on first call for each ticker; persists for the Python session.
# ---------------------------------------------------------------------------
_earnings_cache: dict[str, list[datetime.date]] = {}


def _build_client() -> finnhub.Client:
    if config.FINNHUB_API_KEY == "YOUR_FINNHUB_API_KEY_HERE":
        raise ValueError("Finnhub API key not set in config.py.")
    return finnhub.Client(api_key=config.FINNHUB_API_KEY)


def fetch_earnings_dates(
    ticker: str,
    lookback_months: int = 3,
    forward_months: int = 6,
    force_refresh: bool = False,
) -> list[datetime.date]:
    """
    Pull earnings dates from Finnhub for `ticker` and return them as a list
    of datetime.date objects sorted oldest → newest.

    Results are cached in `_earnings_cache` so subsequent calls are free.

    Parameters
    ----------
    ticker          : stock symbol
    lookback_months : how far back to search (catches recent post-earnings windows)
    forward_months  : how far forward to search (catches upcoming earnings)
    force_refresh   : bypass cache and re-fetch from API

    Returns
    -------
    list of datetime.date — may be empty if no earnings are found
    """
    if not force_refresh and ticker in _earnings_cache:
        return _earnings_cache[ticker]

    today = datetime.date.today()
    from_date = today - datetime.timedelta(days=lookback_months * 30)
    to_date   = today + datetime.timedelta(days=forward_months * 30)

    try:
        client = _build_client()
        response = client.earnings_calendar(
            _from=from_date.strftime("%Y-%m-%d"),
            to=to_date.strftime("%Y-%m-%d"),
            symbol=ticker,
        )

        # Finnhub returns: {'earningsCalendar': [{'date': 'YYYY-MM-DD', ...}, ...]}
        raw_items = response.get("earningsCalendar", []) if isinstance(response, dict) \
                    else getattr(response, "earnings_calendar", [])

        dates = []
        for item in raw_items:
            raw_date = item.get("date") if isinstance(item, dict) \
                       else getattr(item, "date", None)
            if raw_date:
                try:
                    dates.append(datetime.date.fromisoformat(str(raw_date)))
                except ValueError:
                    pass

        dates.sort()
        _earnings_cache[ticker] = dates

        if dates:
            print(f"[earnings_filter] {ticker}: found {len(dates)} earnings date(s): "
                  f"{[str(d) for d in dates]}")
        else:
            print(f"[earnings_filter] {ticker}: no earnings dates found in window.")

        return dates

    except Exception as e:
        print(f"[earnings_filter] WARNING: could not fetch earnings for {ticker}: {e}")
        _earnings_cache[ticker] = []
        return []


def nearest_earnings(
    ticker: str,
    check_date: datetime.date = None,
) -> tuple[datetime.date | None, int]:
    """
    Find the earnings date closest to `check_date` (either before or after).

    Returns
    -------
    (nearest_date, days_delta)
      days_delta is NEGATIVE if the earnings date is in the past,
                    POSITIVE if in the future.
      Returns (None, 999) if no earnings dates are found.
    """
    if check_date is None:
        check_date = datetime.date.today()

    dates = fetch_earnings_dates(ticker)
    if not dates:
        return None, 999

    # Find the date with the smallest absolute distance
    nearest = min(dates, key=lambda d: abs((d - check_date).days))
    delta   = (nearest - check_date).days   # negative = earnings was in the past
    return nearest, delta


def is_earnings_window(
    ticker: str,
    check_date: datetime.date = None,
    iv_rank: float = 0.0,
) -> dict:
    """
    Determine whether `check_date` falls inside an earnings sensitivity window
    and what action (if any) to take.

    Parameters
    ----------
    ticker     : stock symbol
    check_date : date to check (defaults to today)
    iv_rank    : current IV rank (0–1), used to evaluate IV_CRUSH eligibility

    Returns
    -------
    dict with keys:
        in_window        bool    – True if we should modify normal signal logic
        signal_override  str     – 'IV_CRUSH', 'SUPPRESS', or '' (no override)
        days_to_earnings int     – trading days until/since earnings
                                   (negative = earnings already passed)
        earnings_date    str     – ISO date of the nearest earnings event
        warning_text     str     – human-readable description
    """
    if check_date is None:
        check_date = datetime.date.today()

    earnings_date, delta = nearest_earnings(ticker, check_date)

    result = {
        "in_window":        False,
        "signal_override":  "",
        "days_to_earnings": delta,
        "earnings_date":    earnings_date.isoformat() if earnings_date else "",
        "warning_text":     "",
    }

    if earnings_date is None:
        return result

    # delta > 0: earnings is in the future  (pre-earnings)
    # delta < 0: earnings already happened  (post-earnings)
    # delta = 0: earnings is today

    pre_window  = 0 <= delta <= PRE_EARNINGS_DAYS
    post_window = -POST_EARNINGS_DAYS <= delta < 0

    if not (pre_window or post_window):
        return result  # outside all windows

    result["in_window"] = True

    if post_window:
        result["signal_override"] = "SUPPRESS"
        result["warning_text"] = (
            f"Post-earnings: {abs(delta)}d after {earnings_date}. "
            "IV crush likely underway — avoid new positions."
        )

    elif delta == 0:
        result["signal_override"] = "SUPPRESS"
        result["warning_text"] = f"Earnings TODAY ({earnings_date}). Signal suppressed."

    elif 1 <= delta <= IV_CRUSH_ENTRY_DAYS and iv_rank >= IV_CRUSH_IV_THRESHOLD:
        # Sweet spot: close to earnings AND IV is very elevated
        result["signal_override"] = "IV_CRUSH"
        result["warning_text"] = (
            f"IV CRUSH setup: {delta}d before earnings ({earnings_date}), "
            f"IV Rank={iv_rank:.1%} (>{IV_CRUSH_IV_THRESHOLD:.0%}). "
            "Consider selling ATM straddle/strangle."
        )

    else:
        # Pre-earnings but not in the IV crush sweet spot
        result["signal_override"] = "SUPPRESS"
        result["warning_text"] = (
            f"Pre-earnings: {delta}d before {earnings_date}. "
            "Vol spike risk — normal signals suppressed."
        )

    return result


def get_all_earnings_dates(
    tickers: list = None,
) -> dict[str, list[datetime.date]]:
    """Fetch and cache earnings dates for a list of tickers."""
    if tickers is None:
        tickers = config.TICKERS
    return {t: fetch_earnings_dates(t) for t in tickers}


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result = is_earnings_window("AAPL")
    print(f"\nAAPL earnings window check:")
    for k, v in result.items():
        print(f"  {k:20s}: {v}")

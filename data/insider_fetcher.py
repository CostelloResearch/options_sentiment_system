# =============================================================================
# data/insider_fetcher.py -- Fetch and classify insider stock transactions
# from Finnhub's /stock/insider-transactions endpoint.
#
# WHY THIS EXISTS
# ---------------
# Cohen-Malloy-Pomorski (2012, "Decoding Inside Information") and related
# literature establish that *opportunistic* insider purchases predict
# positive returns over 3-12 month horizons.  Insider sales are weaker as
# a signal because routine motivations (diversification, taxes, 10b5-1
# plans) dominate.  This module pulls the raw transaction stream and tags
# each row with an `is_opportunistic` flag so downstream signal logic can
# isolate the informative subset.
#
# SCOPE NOTE
# ----------
# Today this is pure data infrastructure -- the output CSVs are NOT yet
# consumed by signals/, sentiment/, or backtest/.  Integration is deferred
# until real-data sentiment validation establishes whether the existing
# sentiment core has any generalising edge (see PROJECT_STATE.md
# §1, 2026-04-27 honest-status update).
#
# CLASSIFICATION RULES (heuristic; see "LIMITATIONS" below)
# ---------------------------------------------------------
# `is_opportunistic = True` iff ALL of:
#   - transaction_code == "P"      (SEC Form 4 open-market purchase)
#   - change > 0                    (net acquisition of shares)
#   - is_derivative == False        (cash transaction, not option exercise)
#   - price_per_share > 0           (real cash price, not zero/award)
# Otherwise False.
#
# All sells (S) are routine regardless of size or insider, per the
# user-spec asymmetry rule.  Awards (A), option exercises (M/X/C), tax-
# withholding dispositions (F), gifts (G), inheritances (W), and every
# derivative transaction route to `is_opportunistic = False` with a
# specific `classification_reason`.
#
# LIMITATIONS (load-bearing for downstream interpretation)
# --------------------------------------------------------
# 1. Finnhub's free-tier insider-transactions response does NOT expose a
#    10b5-1 / scheduled-trade flag.  A P-coded purchase under a 10b5-1
#    plan would be misclassified as opportunistic.  In practice, 10b5-1
#    plans are predominantly used for *sales* (see Jagolinzer 2009), so
#    the false-positive rate on the buy side is expected to be low, but
#    it is non-zero.
# 2. Finnhub does NOT expose insider role/title in this endpoint.  The
#    `insider_role` schema column is present for forward compatibility
#    but populated as empty string today.  Distinguishing officers/
#    directors from 10% beneficial owners (the literature's usual cut)
#    requires SEC Form 4 XML parsing, deferred to a later session.
# 3. The classifier is *transaction-code-based*, not pattern-based.
#    Cohen-Malloy-Pomorski's stricter definition (a trade is opportunistic
#    iff the same insider did NOT trade similarly in the prior 12 months)
#    requires per-insider history scanning and is not implemented here.
#    The current rule is the looser "open-market purchase" interpretation
#    used in much of the practitioner literature.
#
# OUTPUT SCHEMA (one row per transaction)
# ---------------------------------------
#   transaction_date       ISO date
#   filing_date            ISO date (typically 2 days after transaction)
#   ticker                 string
#   insider_name           string (last-first per SEC convention)
#   insider_role           string (empty for now -- see Limitation 2)
#   transaction_type       "BUY" if change>0, "SELL" if change<0, "" otherwise
#   transaction_code       single-letter SEC Form 4 code (P, S, A, M, ...)
#   share_count            absolute share count of this transaction
#   price_per_share        USD per share (0.0 for non-cash transactions)
#   total_value            share_count * price_per_share, rounded to cents
#   shares_held_after      cumulative position after this transaction
#   is_opportunistic       bool, per CLASSIFICATION RULES above
#   classification_reason  short string explaining the flag
#   source                 "finnhub"
#   pulled_at              ISO-8601 UTC timestamp of fetch
# =============================================================================

from __future__ import annotations

import datetime
import os
import sys
import time

import pandas as pd
import requests

# Allow running this file directly: add project root to sys.path so the
# top-level `config` module imports cleanly.
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

import config  # noqa: E402

# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
FINNHUB_INSIDER_URL = "https://finnhub.io/api/v1/stock/insider-transactions"

# ---------------------------------------------------------------------------
# SEC Form 4 transaction-code reason map.
# Codes drawn from the SEC's "Codes for Reporting Transactions" table on
# Form 4.  See https://www.sec.gov/about/forms/form4.pdf appendix.
# Only "P" qualifies as opportunistic under the CLASSIFICATION RULES.
# ---------------------------------------------------------------------------
_CODE_REASON: dict[str, str] = {
    "P": "open_market_purchase",        # signal of interest
    "S": "open_market_sale",
    "A": "rsu_or_grant_award",
    "D": "disposition_to_issuer",
    "F": "tax_withholding",
    "G": "gift",
    "I": "discretionary_plan_transaction",
    "J": "other_acquisition_or_disposition",
    "K": "equity_swap",
    "L": "small_acquisition_under_16a6",
    "M": "option_or_derivative_exercise",
    "C": "derivative_conversion",
    "X": "in_the_money_derivative_exercise",
    "O": "out_of_the_money_derivative_exercise",
    "E": "short_derivative_expiration",
    "H": "long_derivative_expiration",
    "U": "tender_offer_disposition",
    "W": "inheritance_or_will",
    "Z": "voting_trust_movement",
}


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _check_api_key() -> None:
    if not config.FINNHUB_API_KEY or config.FINNHUB_API_KEY == "YOUR_FINNHUB_API_KEY_HERE":
        raise ValueError(
            "Finnhub API key not set.  Edit config.py or set the "
            "FINNHUB_API_KEY environment variable."
        )


def _to_iso_str(d) -> str:
    if isinstance(d, (datetime.date, datetime.datetime)):
        return d.strftime("%Y-%m-%d")
    return str(d)


def _normalize(item: dict, ticker: str, pulled_at: str) -> dict:
    """Map one Finnhub insider record to the project schema."""
    change = int(item.get("change") or 0)
    share_count = abs(change)
    price = float(item.get("transactionPrice") or 0.0)
    if change > 0:
        ttype = "BUY"
    elif change < 0:
        ttype = "SELL"
    else:
        ttype = ""

    return {
        "transaction_date":   item.get("transactionDate", "") or "",
        "filing_date":        item.get("filingDate", "") or "",
        "ticker":             ticker,
        "insider_name":       item.get("name", "") or "",
        # Not exposed by Finnhub free-tier endpoint -- see Limitation 2 above.
        "insider_role":       "",
        "transaction_type":   ttype,
        "transaction_code":   item.get("transactionCode", "") or "",
        "share_count":        share_count,
        "price_per_share":    price,
        "total_value":        round(share_count * price, 2),
        "shares_held_after":  int(item.get("share") or 0),
        # `is_opportunistic` and `classification_reason` filled in by _classify.
        "is_opportunistic":   False,
        "classification_reason": "",
        "source":             "finnhub",
        "pulled_at":          pulled_at,
        # Carried for diagnostics; not part of the user-spec schema but
        # cheap to keep and useful when debugging classification.
        "_is_derivative":     bool(item.get("isDerivative", False)),
    }


def _classify(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the is_opportunistic + classification_reason rules in-place."""
    if df.empty:
        return df
    code = df["transaction_code"].astype(str)

    is_open_market_buy = (
        (code == "P")
        & (df["transaction_type"] == "BUY")
        & (~df["_is_derivative"].astype(bool))
        & (df["price_per_share"] > 0)
    )
    df["is_opportunistic"] = is_open_market_buy

    # Reason: prefer the SEC code mapping; fall back to "other_routine".
    reason = code.map(_CODE_REASON).fillna("other_routine")
    # Override: derivative transactions get a more specific reason than
    # the bare code map (e.g. an A-coded derivative grant).
    deriv_mask = df["_is_derivative"].astype(bool) & ~is_open_market_buy
    reason = reason.where(~deriv_mask, "derivative_transaction")
    df["classification_reason"] = reason

    return df


def _save(df: pd.DataFrame, ticker: str) -> str:
    raw_dir = os.path.join(os.path.dirname(__file__), "raw")
    os.makedirs(raw_dir, exist_ok=True)
    fp = os.path.join(raw_dir, f"insider_{ticker}.csv")
    # Drop the diagnostic underscore-prefixed column before writing.
    out_cols = [c for c in df.columns if not c.startswith("_")]
    df[out_cols].to_csv(fp, index=False)
    print(f"[insider_fetcher] saved -> {fp}")
    return fp


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_insider_transactions(
    ticker: str,
    start_date,
    end_date,
    *,
    save: bool = False,
    timeout: int = 30,
) -> pd.DataFrame:
    """
    Pull insider transactions for `ticker` between `start_date` and
    `end_date` (inclusive), classify each row, and optionally persist
    to data/raw/insider_{ticker}.csv (replacing any existing file).

    Failure modes follow the news_fetcher.py / run_daily.py convention:
    on rate-limit or HTTP error, log a warning and return an empty
    DataFrame.  Caller is responsible for retrying or moving on.

    Parameters
    ----------
    ticker : str
        Stock symbol, e.g. "AAPL".  ETFs do not have insiders -- the
        endpoint returns an empty list, which this function logs and
        returns as an empty frame.
    start_date, end_date : str | datetime.date
        Inclusive bounds.  String form must be "YYYY-MM-DD".
    save : bool
        If True, write data/raw/insider_{ticker}.csv (full replace).
    timeout : int
        HTTP request timeout in seconds.

    Returns
    -------
    pd.DataFrame
        Schema documented at the top of this module.  Empty on failure
        or no data; columns are NOT guaranteed when empty.
    """
    _check_api_key()

    from_str = _to_iso_str(start_date)
    to_str   = _to_iso_str(end_date)
    print(f"[insider_fetcher] {ticker}: fetching {from_str} -> {to_str}")

    params = {
        "symbol": ticker,
        "token":  config.FINNHUB_API_KEY,
        "from":   from_str,
        "to":     to_str,
    }

    try:
        r = requests.get(FINNHUB_INSIDER_URL, params=params, timeout=timeout)
    except requests.RequestException as e:
        print(f"[insider_fetcher] WARN {ticker}: request failed: {e}")
        return pd.DataFrame()

    if r.status_code == 429:
        print(f"[insider_fetcher] WARN {ticker}: rate-limited (HTTP 429); "
              f"returning empty frame.  Caller should back off.")
        return pd.DataFrame()
    if r.status_code != 200:
        print(f"[insider_fetcher] WARN {ticker}: HTTP {r.status_code}: "
              f"{r.text[:200]}")
        return pd.DataFrame()

    try:
        payload = r.json()
    except ValueError as e:
        print(f"[insider_fetcher] WARN {ticker}: malformed JSON: {e}")
        return pd.DataFrame()

    items = payload.get("data") or []
    if not items:
        print(f"[insider_fetcher] {ticker}: no records in {from_str}..{to_str}.")
        return pd.DataFrame()

    pulled_at = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    rows = [_normalize(it, ticker, pulled_at) for it in items]
    df = pd.DataFrame(rows)
    df = _classify(df)
    df = df.sort_values(["transaction_date", "filing_date"], ascending=False)
    df = df.reset_index(drop=True)

    n_opp = int(df["is_opportunistic"].sum())
    print(f"[insider_fetcher] {ticker}: {len(df)} txns, "
          f"{n_opp} opportunistic ({100*n_opp/max(len(df),1):.1f}%).")

    if save:
        _save(df, ticker)

    return df


def fetch_all_insider_history(
    tickers: list[str] | None = None,
    lookback_years: int = 5,
    *,
    save: bool = True,
    sleep_between: float = 1.5,
) -> dict[str, pd.DataFrame]:
    """
    Pull `lookback_years` years of insider transactions for each ticker
    in the list, sleeping `sleep_between` seconds between calls to stay
    under the Finnhub free-tier rate ceiling (60 calls/min).

    ETFs are excluded silently if `tickers` defaults from config.TICKERS:
    config.ETF_TICKERS is filtered out because ETFs do not have insiders
    and would just waste API quota.

    Returns
    -------
    dict[ticker -> DataFrame]
    """
    if tickers is None:
        tickers = [t for t in config.TICKERS if t not in config.ETF_TICKERS]

    today = datetime.date.today()
    # 365.25 to absorb leap-year drift over multi-year lookbacks.
    start = today - datetime.timedelta(days=int(365.25 * lookback_years))

    results: dict[str, pd.DataFrame] = {}
    for i, t in enumerate(tickers):
        df = fetch_insider_transactions(t, start, today, save=save)
        results[t] = df
        if i < len(tickers) - 1:
            time.sleep(sleep_between)
    return results


# ---------------------------------------------------------------------------
# Smoke test: `python data/insider_fetcher.py` -> AAPL last 12 months,
# print summary, do not save.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    today = datetime.date.today()
    one_year_ago = today - datetime.timedelta(days=365)
    df = fetch_insider_transactions("AAPL", one_year_ago, today, save=False)
    if df.empty:
        print("[smoke] empty frame")
    else:
        print()
        print(f"Columns: {list(df.columns)}")
        print(f"Shape  : {df.shape}")
        print(f"Date range: {df['transaction_date'].min()} -> "
              f"{df['transaction_date'].max()}")
        print(f"Transaction code distribution: "
              f"{df['transaction_code'].value_counts().to_dict()}")
        print(f"is_opportunistic: "
              f"{df['is_opportunistic'].value_counts().to_dict()}")

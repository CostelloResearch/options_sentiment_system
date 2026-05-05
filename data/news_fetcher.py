# =============================================================================
# data/news_fetcher.py — Fetch news headlines from Finnhub
#
# Finnhub's /company-news endpoint returns news articles for a given ticker
# within a date range. We store one CSV per ticker per run date so reruns
# don't overwrite prior snapshots (useful for auditing sentiment drift).
#
# OUTPUT SCHEMA (columns in the saved CSV):
#   ticker, date, datetime, headline, summary, source, url, sentiment_category
# =============================================================================

import os
import time
import datetime
import pandas as pd
import finnhub

# We import config from the project root. If running this file directly
# (e.g. `python data/news_fetcher.py`), add the project root to sys.path.
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config


# ---------------------------------------------------------------------------
# Backfill support: typed exception + chunked-window fetch
#
# The chunked historical backfill (see scripts/backfill_news_history.py) walks
# `to=` backwards in ~14-day windows.  An empty response means we hit the
# Finnhub free-tier ~12-month depth ceiling -- a normal stop signal -- whereas
# any exception during the call is a transient failure that should be retried.
# The orchestrator distinguishes the two: empty DataFrame = ceiling; raised
# BackfillFetchError = retry.  This decoupling keeps the production fetch_news
# behaviour untouched.
# ---------------------------------------------------------------------------

class BackfillFetchError(Exception):
    """Raised by fetch_news_chunk on a failed Finnhub call so the backfill
    orchestrator's retry loop can distinguish API failure from depth ceiling."""
    pass


# Chunk-CSV schema -- kept identical to fetch_news output so a downstream
# scoring step can read either flavour with the same column expectations.
_CHUNK_COLUMNS = ["ticker", "date", "datetime", "headline", "summary", "source", "url"]


def _build_client() -> finnhub.Client:
    """Create and return an authenticated Finnhub client."""
    if config.FINNHUB_API_KEY == "YOUR_FINNHUB_API_KEY_HERE":
        raise ValueError(
            "Finnhub API key not set. Edit config.py or set the "
            "FINNHUB_API_KEY environment variable."
        )
    return finnhub.Client(api_key=config.FINNHUB_API_KEY)


def fetch_news(
    ticker: str,
    lookback_days: int = None,
    save: bool = True,
) -> pd.DataFrame:
    """
    Pull the last `lookback_days` of news for `ticker` from Finnhub.

    Parameters
    ----------
    ticker : str
        Stock symbol, e.g. "AAPL".
    lookback_days : int, optional
        Number of calendar days to look back. Defaults to config value.
    save : bool
        If True, write the result to data/raw/news_{ticker}_{date}.csv.

    Returns
    -------
    pd.DataFrame
        One row per article with columns defined in the module docstring.
    """
    if lookback_days is None:
        lookback_days = config.DATA_PARAMS["news_lookback_days"]

    client = _build_client()

    # Finnhub expects dates as "YYYY-MM-DD" strings
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=lookback_days)
    from_str = start_date.strftime("%Y-%m-%d")
    to_str = end_date.strftime("%Y-%m-%d")

    print(f"[news_fetcher] Fetching news for {ticker} from {from_str} to {to_str}...")

    try:
        raw_articles = client.company_news(ticker, _from=from_str, to=to_str)
    except Exception as e:
        print(f"[news_fetcher] ERROR fetching {ticker}: {e}")
        return pd.DataFrame()

    if not raw_articles:
        print(f"[news_fetcher] No articles found for {ticker}.")
        return pd.DataFrame()

    # Normalize the raw list of dicts into a clean DataFrame
    rows = []
    for article in raw_articles:
        # Convert Unix timestamp to human-readable datetime
        ts = article.get("datetime", 0)
        dt = datetime.datetime.fromtimestamp(ts) if ts else None

        rows.append({
            "ticker": ticker,
            # Date only — used as the grouping key for daily sentiment scoring
            "date": dt.date() if dt else None,
            "datetime": dt,
            "headline": article.get("headline", ""),
            "summary": article.get("summary", ""),
            "source": article.get("source", ""),
            "url": article.get("url", ""),
        })

    df = pd.DataFrame(rows)

    # Drop duplicates (same headline can appear in multiple categories)
    df.drop_duplicates(subset=["headline"], inplace=True)

    # Sort newest-first so the CSV is easy to eyeball
    df.sort_values("datetime", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)

    print(f"[news_fetcher] Retrieved {len(df)} unique articles for {ticker}.")

    if save:
        _save(df, ticker)

    return df


def _save(df: pd.DataFrame, ticker: str) -> str:
    """Write the DataFrame to data/raw/ and return the file path."""
    # Build the output directory relative to *this file's* location
    raw_dir = os.path.join(os.path.dirname(__file__), "raw")
    os.makedirs(raw_dir, exist_ok=True)

    date_str = datetime.date.today().strftime("%Y-%m-%d")
    filename = f"news_{ticker}_{date_str}.csv"
    filepath = os.path.join(raw_dir, filename)

    df.to_csv(filepath, index=False)
    print(f"[news_fetcher] Saved -> {filepath}")
    return filepath


def fetch_all_tickers(tickers: list = None, **kwargs) -> dict[str, pd.DataFrame]:
    """
    Convenience wrapper: fetch news for every ticker in the list.

    Parameters
    ----------
    tickers : list, optional
        List of ticker strings. Defaults to config.TICKERS.

    Returns
    -------
    dict mapping ticker -> DataFrame
    """
    if tickers is None:
        tickers = config.TICKERS

    results = {}
    for ticker in tickers:
        results[ticker] = fetch_news(ticker, **kwargs)
        # Finnhub free tier allows ~30 requests/minute; a small sleep keeps us safe
        time.sleep(1.5)

    return results


# ---------------------------------------------------------------------------
# Backfill: chunked historical fetch (sibling of fetch_news)
# ---------------------------------------------------------------------------

def fetch_news_chunk(
    ticker: str,
    to_date: datetime.date,
    days: int = 14,
    save_dir: str | None = None,
) -> pd.DataFrame:
    """
    Fetch a single Finnhub company_news chunk for a backwards-walking
    historical backfill.  Window is [to_date - days, to_date].

    The Finnhub free-tier endpoint returns the upper ~7-9 days of the
    requested range (per the v1/v2/v3 spike chain in
    outputs/finnhub_historical_spike*.md); days=14 oversizes deliberately so
    successive chunks overlap, which the orchestrator handles via dedup.

    Parameters
    ----------
    ticker : str
        Stock symbol, e.g. "AAPL".
    to_date : datetime.date
        Upper bound of the requested window (inclusive on Finnhub's side).
    days : int
        Window width in calendar days.  Default 14 matches the spike geometry.
    save_dir : str | None
        If provided, writes `news_{ticker}_chunk_{to_date}.csv` into this
        directory via atomic write (tmp + os.replace).  Skip-if-exists is
        the orchestrator's job, not this function's.

    Returns
    -------
    pd.DataFrame
        Articles in the window, schema identical to fetch_news.  Empty
        DataFrame means the API responded successfully with zero articles
        -- the orchestrator interprets this as the depth ceiling.

    Raises
    ------
    BackfillFetchError
        Wraps any exception from the Finnhub client or response
        normalisation.  Lets the caller's retry loop distinguish "API
        failed" (retry) from "API returned []" (depth ceiling).
    """
    from_date = to_date - datetime.timedelta(days=days)
    from_str  = from_date.strftime("%Y-%m-%d")
    to_str    = to_date.strftime("%Y-%m-%d")

    try:
        client = _build_client()
        raw_articles = client.company_news(ticker, _from=from_str, to=to_str)
    except Exception as e:
        raise BackfillFetchError(
            f"Finnhub call failed for {ticker} _from={from_str} to={to_str}: {e}"
        ) from e

    if not raw_articles:
        # Honest empty -- depth ceiling signal.  Caller decides whether to
        # treat as ceiling (>=2 chunks already done) or as auth failure.
        return pd.DataFrame(columns=_CHUNK_COLUMNS)

    try:
        rows = []
        for article in raw_articles:
            ts = article.get("datetime", 0)
            dt = datetime.datetime.fromtimestamp(ts) if ts else None
            rows.append({
                "ticker":   ticker,
                "date":     dt.date() if dt else None,
                "datetime": dt,
                "headline": article.get("headline", ""),
                "summary":  article.get("summary", ""),
                "source":   article.get("source", ""),
                "url":      article.get("url", ""),
            })
        df = pd.DataFrame(rows, columns=_CHUNK_COLUMNS)
        # Dedup within-chunk by headline (same article served under multiple
        # Finnhub categories).  Cross-chunk dedup is the scoring step's job.
        df.drop_duplicates(subset=["headline"], inplace=True)
        # Ascending by datetime so chunk CSVs read chronologically; this
        # differs from fetch_news (which sorts descending for eyeballing) --
        # the backfill convention favours chronological order for stitching.
        df.sort_values("datetime", ascending=True, inplace=True)
        df.reset_index(drop=True, inplace=True)
    except Exception as e:
        raise BackfillFetchError(
            f"Response normalisation failed for {ticker} to={to_str}: {e}"
        ) from e

    if save_dir is not None and not df.empty:
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, f"news_{ticker}_chunk_{to_str}.csv")
        # Atomic write so a SIGKILL mid-write can't corrupt the chunk file
        tmp = path + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)

    return df


# ---------------------------------------------------------------------------
# Quick smoke-test: run this file directly to fetch AAPL news
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    df = fetch_news("AAPL")
    if not df.empty:
        print("\n--- Sample output (first 5 rows) ---")
        print(df[["date", "source", "headline"]].head())
        print(f"\nColumns : {list(df.columns)}")
        print(f"Shape   : {df.shape}")
        print(f"Date range: {df['date'].min()} -> {df['date'].max()}")

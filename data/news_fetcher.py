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

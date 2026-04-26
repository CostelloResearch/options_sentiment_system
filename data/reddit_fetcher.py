# =============================================================================
# data/reddit_fetcher.py -- Pull ticker mentions from Reddit via PRAW
#
# Reddit is our second text-sentiment source.  Unlike Finnhub news (which is
# capped at ~30 days on the free tier), Reddit search can surface posts going
# back several months — this lets us extend the sentiment history backward.
#
# BEST-EFFORT HISTORY
# -------------------
# The public Reddit API does NOT expose a reliable time-range search.  We use
# PRAW's subreddit.search() with time_filter="year" (the widest window Reddit
# accepts) and then filter client-side to `lookback_days`.  In practice you'll
# get whatever Reddit's ranking surfaces:
#   • wallstreetbets, stocks, investing -> typically 30-90 days of coverage
#   • options, StockMarket              -> fewer posts but often older threads
# Accept partial results — even 30-60 days of Reddit on top of Finnhub news
# meaningfully widens the sentiment history.
#
# QUERY STRATEGY
# --------------
# For each ticker we search each subreddit twice:
#   1. plain ticker symbol ("AAPL")
#   2. cashtag form       ("$AAPL")
# Results are deduplicated by post ID.  Including both forms catches posts
# that only use one convention (WSB leans cashtag, r/investing leans plain).
#
# OUTPUT SCHEMA (matches news_fetcher.py so the scorer can reuse score_articles)
# -----------------------------------------------------------------------------
#   ticker, date, datetime, headline (title), summary (selftext), source
#   (subreddit), url, score (upvotes), num_comments
# =============================================================================

import os
import sys
import time
import datetime
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config


# ---------------------------------------------------------------------------
# PRAW client
# ---------------------------------------------------------------------------

_reddit_cache = None

def _build_client():
    """
    Return a cached read-only PRAW client.
    Reads credentials from config.py (which reads env vars first).
    """
    global _reddit_cache
    if _reddit_cache is not None:
        return _reddit_cache

    # Import lazily so the module still imports if PRAW is missing,
    # letting the pipeline continue with news-only sentiment.
    try:
        import praw
    except ImportError as e:
        raise ImportError(
            "PRAW is not installed.  Run `pip install praw` (already "
            "listed in requirements.txt)."
        ) from e

    cid     = config.REDDIT_CLIENT_ID
    csecret = config.REDDIT_CLIENT_SECRET
    ua      = config.REDDIT_USER_AGENT

    if (cid.startswith("YOUR_") or csecret.startswith("YOUR_")
            or "YourRedditUsername" in ua):
        raise ValueError(
            "Reddit API credentials not set.  Create an app at "
            "https://www.reddit.com/prefs/apps (type: 'script') and fill "
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET / REDDIT_USER_AGENT "
            "in config.py (or the matching env vars)."
        )

    _reddit_cache = praw.Reddit(
        client_id     = cid,
        client_secret = csecret,
        user_agent    = ua,
        # read-only: we only search + read submissions
        check_for_async = False,
    )
    return _reddit_cache


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------

def _query_variants(ticker: str) -> list[str]:
    """Queries to run per subreddit.  Both forms catch the typical conventions."""
    return [ticker, f"${ticker}"]


def _search_subreddit(reddit, subreddit_name: str, query: str, limit: int):
    """
    Run one search and yield normalised dicts.  Swallows per-submission errors
    so a single broken post doesn't kill the whole batch.
    """
    try:
        sub = reddit.subreddit(subreddit_name)
        results = sub.search(query, sort="new", time_filter="year", limit=limit)
        for post in results:
            try:
                yield {
                    "id":            post.id,
                    "subreddit":     subreddit_name,
                    "title":         post.title or "",
                    "selftext":      (post.selftext or "")[:2000],  # cap long posts
                    "url":           f"https://reddit.com{post.permalink}",
                    "created_utc":   float(post.created_utc),
                    "score":         int(getattr(post, "score", 0) or 0),
                    "num_comments":  int(getattr(post, "num_comments", 0) or 0),
                }
            except Exception as e:
                print(f"[reddit_fetcher] WARN skipping post in r/{subreddit_name}: {e}")
    except Exception as e:
        # Common cause: subreddit is private/banned/quarantined
        print(f"[reddit_fetcher] WARN search failed r/{subreddit_name} q='{query}': {e}")


def _mentions_ticker(row: dict, ticker: str) -> bool:
    """
    Light relevance filter.  Reddit search sometimes returns marginal matches;
    we insist the ticker appears as a whole token in title OR body.
    """
    hay = f" {row['title']} {row['selftext']} ".upper()
    needles = (f" {ticker} ", f"${ticker} ", f"${ticker}.", f" {ticker}.",
               f" {ticker},", f" {ticker}!", f" {ticker}?")
    return any(n in hay for n in needles)


def fetch_reddit_posts(
    ticker: str,
    lookback_days: int = None,
    subreddits: list = None,
    post_limit: int = None,
    save: bool = True,
) -> pd.DataFrame:
    """
    Pull Reddit posts mentioning `ticker` from the configured subreddits.

    Parameters
    ----------
    ticker : str
        Stock symbol, e.g. "AAPL".
    lookback_days : int, optional
        Keep only posts created within this many days.  Defaults to
        config.DATA_PARAMS["reddit_lookback_days"].
    subreddits : list, optional
        Subreddit names (without "r/").  Defaults to config setting.
    post_limit : int, optional
        Max posts fetched per (subreddit, query) pair.  Default from config.
    save : bool
        If True, write the result to data/raw/reddit_{ticker}_{date}.csv.

    Returns
    -------
    pd.DataFrame with columns matching news_fetcher.py plus `score` and
    `num_comments`.  Empty DataFrame if no posts are found.
    """
    params   = config.DATA_PARAMS
    lookback = lookback_days if lookback_days is not None else params["reddit_lookback_days"]
    subs     = subreddits    if subreddits    is not None else params["reddit_subreddits"]
    limit    = post_limit    if post_limit    is not None else params["reddit_post_limit"]

    cutoff_ts = (datetime.datetime.now() - datetime.timedelta(days=lookback)).timestamp()

    reddit = _build_client()
    print(f"[reddit_fetcher] Searching {len(subs)} subreddits for {ticker} "
          f"(lookback={lookback}d, limit/query={limit})...")

    seen_ids: set[str] = set()
    rows: list[dict]   = []

    for sub_name in subs:
        for q in _query_variants(ticker):
            n_before = len(rows)
            for raw in _search_subreddit(reddit, sub_name, q, limit):
                if raw["id"] in seen_ids:
                    continue
                if raw["created_utc"] < cutoff_ts:
                    continue
                if not _mentions_ticker(raw, ticker):
                    continue
                seen_ids.add(raw["id"])
                dt = datetime.datetime.fromtimestamp(raw["created_utc"])
                rows.append({
                    "ticker":       ticker,
                    "date":         dt.date(),
                    "datetime":     dt,
                    "headline":     raw["title"],
                    "summary":      raw["selftext"],
                    "source":       f"r/{sub_name}",
                    "url":          raw["url"],
                    "score":        raw["score"],
                    "num_comments": raw["num_comments"],
                })
            print(f"[reddit_fetcher]   r/{sub_name:<15s} q='{q}' -> "
                  f"+{len(rows) - n_before} new")
            # Reddit OAuth allows 60 req/min; a small sleep keeps us under that
            # even if PRAW paginates internally.
            time.sleep(0.5)

    if not rows:
        print(f"[reddit_fetcher] No qualifying posts found for {ticker}.")
        return pd.DataFrame()

    df = pd.DataFrame(rows).sort_values("datetime", ascending=False)
    df.reset_index(drop=True, inplace=True)

    oldest = df["date"].min()
    newest = df["date"].max()
    span   = (newest - oldest).days if newest and oldest else 0
    print(f"[reddit_fetcher] Retrieved {len(df)} unique posts for {ticker}  "
          f"({oldest} -> {newest}, {span}d span).")

    if save:
        _save(df, ticker)

    return df


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def _save(df: pd.DataFrame, ticker: str) -> str:
    raw_dir = os.path.join(os.path.dirname(__file__), "raw")
    os.makedirs(raw_dir, exist_ok=True)

    date_str = datetime.date.today().strftime("%Y-%m-%d")
    filename = f"reddit_{ticker}_{date_str}.csv"
    filepath = os.path.join(raw_dir, filename)

    df.to_csv(filepath, index=False)
    print(f"[reddit_fetcher] Saved -> {filepath}")
    return filepath


def fetch_all_tickers(tickers: list = None, **kwargs) -> dict[str, pd.DataFrame]:
    """Convenience wrapper: fetch reddit posts for every ticker in the list."""
    if tickers is None:
        tickers = config.TICKERS
    results = {}
    for ticker in tickers:
        try:
            results[ticker] = fetch_reddit_posts(ticker, **kwargs)
        except Exception as e:
            print(f"[reddit_fetcher] ERROR for {ticker}: {e}")
            results[ticker] = pd.DataFrame()
        # Extra spacing between tickers to stay polite to the API
        time.sleep(1.0)
    return results


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    df = fetch_reddit_posts("AAPL")
    if not df.empty:
        print("\n--- Sample output (first 5 rows) ---")
        print(df[["date", "source", "score", "num_comments", "headline"]].head())
        print(f"\nColumns   : {list(df.columns)}")
        print(f"Shape     : {df.shape}")
        print(f"Date range: {df['date'].min()} -> {df['date'].max()}")
        print(f"By sub    : {df['source'].value_counts().to_dict()}")

# =============================================================================
# config.py — Central configuration for the options sentiment system
#
# HOW TO USE:
#   1. Replace placeholder API keys with your real keys
#   2. Adjust TICKERS to add/remove symbols you want to track
#   3. Tune signal thresholds in SIGNAL_PARAMS as you backtest
# =============================================================================

import os

# ---------------------------------------------------------------------------
# API Keys
# Set these as environment variables (preferred) or replace the fallback strings.
# Never commit real keys to version control.
# ---------------------------------------------------------------------------
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "d7ldt79r01qm7o0bg2v0d7ldt79r01qm7o0bg2vg")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "YOUR_REDDIT_CLIENT_ID_HERE")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "YOUR_REDDIT_CLIENT_SECRET_HERE")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "OptionsSentimentBot/0.1 by YourRedditUsername")

# SEC EDGAR requires a descriptive User-Agent containing a contact email.
# Format: "CompanyOrProject Name contact@example.com"
# Requests without a proper UA may be throttled or blocked entirely.
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "OptionsSentimentBot/0.1 costello.t@northeastern.edu",
)

# ---------------------------------------------------------------------------
# Universe of tickers to analyze
# ---------------------------------------------------------------------------
# 10-ticker rebuild (2026-04-25): expanded from a 5-ticker mega-cap-tech
# concentration (effective sample ~1.5 independent bets) to 10 names
# spanning 6 GICS sectors and 3 asset classes.  Dropped MSFT and QQQ
# (correlated with AAPL and SPY respectively).  Treat the new universe
# as a fresh strategy: do NOT compare KPIs to the 5-ticker baseline.
TICKERS = [
    "AAPL",   # mega-cap tech
    "NVDA",   # semis / AI
    "JPM",    # financials
    "XOM",    # energy
    "UNH",    # healthcare
    "WMT",    # consumer staples
    "IWM",    # small-cap equity (Russell 2000 ETF)
    "GLD",    # gold / commodity ETF
    "TLT",    # long bonds / fixed income ETF
    "SPY",    # broad market ETF
]

# Sector taxonomy.  Drives the per-sector decay segmentation in
# scripts/sector_decay.py and the diversification commentary in
# PROJECT_STATE.md.  ETFs are bucketed by their primary exposure rather
# than the GICS sector of the issuer.
SECTOR_MAP = {
    "AAPL": "Technology",
    "NVDA": "Technology",       # semis -- still tech for sector edge
    "JPM":  "Financials",
    "XOM":  "Energy",
    "UNH":  "Healthcare",
    "WMT":  "ConsumerStaples",
    "IWM":  "SmallCapEquity",
    "GLD":  "Commodity",
    "TLT":  "FixedIncome",
    "SPY":  "BroadMarket",
}

# Asset-class taxonomy (coarser than sector).  Used for the diversification
# claim "10 tickers across 3 asset classes": equities (single-name + small-
# cap + broad-market ETFs), commodity (gold), fixed income (long bonds).
ASSET_CLASS = {
    "AAPL": "Equity", "NVDA": "Equity", "JPM": "Equity",
    "XOM":  "Equity", "UNH":  "Equity", "WMT": "Equity",
    "IWM":  "Equity", "SPY":  "Equity",
    "GLD":  "Commodity",
    "TLT":  "FixedIncome",
}

# Tickers we know don't file 10-K/10-Q/8-K (ETFs, commodity trusts, bond
# funds).  data/sec_fetcher and sentiment/sec_scorer short-circuit on
# these tickers -- log "no SEC data, news-only sentiment" and continue
# rather than spamming "no filings in lookback window" or erroring out.
# Keep this in sync with `ASSET_CLASS != "Equity"` plus the broad-market
# / small-cap ETFs whose "filings" are N-CSR semi-annuals we don't score.
ETF_TICKERS = {"SPY", "IWM", "GLD", "TLT", "QQQ"}

# ---------------------------------------------------------------------------
# Data collection parameters
# ---------------------------------------------------------------------------
DATA_PARAMS = {
    "news_lookback_days": 30,       # How many days back to fetch news
    "iv_history_days": 252,         # Trading days for IV Rank calculation (~1 year)

    # Reddit backfill: target 90 days, but time_filter="year" + best-effort
    # search means we get whatever Reddit returns (often 30-60 days).
    "reddit_lookback_days": 90,
    "reddit_post_limit": 500,       # Max posts to pull per subreddit per query
    "reddit_subreddits": [
        "wallstreetbets",
        "stocks",
        "investing",
        "options",
        "StockMarket",
    ],

    # SEC EDGAR backfill
    "sec_lookback_years": 3,              # how far back to pull filings
    "sec_filing_types":    ["10-K", "10-Q", "8-K"],
    "sec_rate_limit_rps":  10,            # SEC enforces 10 requests/sec max
    "sec_request_timeout": 30,            # seconds per HTTP request
}

# ---------------------------------------------------------------------------
# Signal generation thresholds
# Tune these after running backtests
# ---------------------------------------------------------------------------
SIGNAL_PARAMS = {
    # Sentiment score range: -1.0 (very bearish) to +1.0 (very bullish)
    "bullish_sentiment_threshold": 0.25,   # Score above this = bullish signal
    "bearish_sentiment_threshold": -0.25,  # Score below this = bearish signal

    # IV Rank range: 0.0 (historically low vol) to 1.0 (historically high vol)
    # High IV Rank (>0.7) = options are expensive → favor selling premium
    # Low IV Rank (<0.3) = options are cheap → favor buying premium
    "high_iv_rank_threshold": 0.70,
    "low_iv_rank_threshold": 0.30,

    # Minimum number of news articles needed to trust the sentiment score
    "min_articles_required": 3,
}

# ---------------------------------------------------------------------------
# File paths (relative to project root)
# ---------------------------------------------------------------------------
RAW_DATA_DIR = "data/raw"

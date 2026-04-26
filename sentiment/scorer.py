# =============================================================================
# sentiment/scorer.py — Score news headlines with FinBERT
#
# FinBERT (ProsusAI/finbert) is a BERT model fine-tuned on financial text.
# It classifies each piece of text as: positive / negative / neutral
# along with a confidence score (0–1) for each label.
#
# HOW WE TURN LABELS INTO A NUMERIC SCORE (-1 to +1):
#   raw_score = (+1 × P(positive)) + (-1 × P(negative)) + (0 × P(neutral))
#             = P(positive) - P(negative)
#
#   This is a confidence-weighted score. A headline predicted "positive"
#   with 95% confidence gets score ≈ +0.95, while a weakly positive
#   prediction (55%/45%/0%) only scores ≈ +0.10.  Much more informative
#   than a flat +1/-1/0 mapping.
#
# DAILY AGGREGATION:
#   We average all article scores within a calendar day to produce one
#   number that the signal engine can act on.
#
# FIRST RUN NOTE:
#   HuggingFace will download ~440 MB of model weights on first use.
#   Subsequent runs load from the local cache (~/.cache/huggingface/).
# =============================================================================

import os
import sys
import glob
import datetime

import pandas as pd
from transformers import pipeline, logging as hf_logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

# Suppress the verbose "loading weights" info messages from HuggingFace
hf_logging.set_verbosity_error()


# ---------------------------------------------------------------------------
# Model loader — cached after first call so we only pay the load cost once
# ---------------------------------------------------------------------------

_pipeline_cache = None  # module-level cache; avoids reloading between calls

def _get_pipeline():
    """
    Load the FinBERT sentiment pipeline (downloads on first run).
    Uses a module-level cache so the model isn't reloaded on every call.
    """
    global _pipeline_cache
    if _pipeline_cache is None:
        print("[scorer] Loading FinBERT model (first run downloads ~440 MB)...")
        _pipeline_cache = pipeline(
            task="text-classification",
            model="ProsusAI/finbert",
            # Return scores for ALL three labels, not just the top one.
            # We need P(positive) and P(negative) separately for our formula.
            top_k=None,
            # Use GPU if available (cuda:0), otherwise CPU
            device=0 if _cuda_available() else -1,
        )
        print("[scorer] FinBERT loaded.")
    return _pipeline_cache


def _cuda_available() -> bool:
    """Return True if a CUDA GPU is detected (speeds up inference ~10x)."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Text preparation
# ---------------------------------------------------------------------------

def _build_text(headline: str, summary: str) -> str:
    """
    Combine headline + summary into a single string for the model.

    FinBERT was trained on short financial sentences, so we truncate
    aggressively.  The pipeline's tokenizer will hard-truncate at 512
    tokens anyway, but keeping things concise improves accuracy.

    Strategy: full headline + first ~200 chars of summary (one sentence
    of context is usually enough; beyond that the model can get confused).
    """
    headline = str(headline).strip() if pd.notna(headline) else ""
    summary = str(summary).strip() if pd.notna(summary) else ""

    # Take only the first 200 characters of the summary to stay focused
    summary_snippet = summary[:200]

    # Separator chosen to read naturally for a financial sentence
    if summary_snippet:
        return f"{headline}. {summary_snippet}"
    return headline


def _scores_to_numeric(label_scores: list[dict]) -> float:
    """
    Convert FinBERT's [{'label': 'positive', 'score': 0.92}, ...] output
    into a single float in [-1, +1].

    Formula:  numeric = P(positive) - P(negative)
    """
    score_map = {item["label"].lower(): item["score"] for item in label_scores}
    return score_map.get("positive", 0.0) - score_map.get("negative", 0.0)


# ---------------------------------------------------------------------------
# Core scoring function
# ---------------------------------------------------------------------------

BATCH_SIZE = 16  # Number of texts sent to the model at once.
                 # Larger = faster on GPU; smaller = safer on CPU RAM.

def score_articles(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a `sentiment_score` column to a news DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain at least 'headline' and 'summary' columns
        (output from news_fetcher.py).

    Returns
    -------
    pd.DataFrame
        Original DataFrame with three new columns:
          sentiment_score  – float in [-1, +1]
          sentiment_label  – 'positive' / 'negative' / 'neutral' (top label)
          sentiment_conf   – confidence of the top label (0–1)
    """
    nlp = _get_pipeline()

    # Build the combined text strings
    texts = [
        _build_text(row["headline"], row["summary"])
        for _, row in df.iterrows()
    ]

    # Filter out empty strings (avoid sending blanks to the model)
    valid_mask = [bool(t.strip()) for t in texts]
    valid_texts = [t for t, ok in zip(texts, valid_mask) if ok]

    print(f"[scorer] Scoring {len(valid_texts)} articles "
          f"({len(texts) - len(valid_texts)} empty skipped)...")

    # Run inference in batches
    # truncation=True tells the tokenizer to cut at 512 tokens safely
    raw_outputs = nlp(valid_texts, batch_size=BATCH_SIZE, truncation=True)

    # Map results back to their original row positions
    numeric_scores = []
    top_labels = []
    top_confs = []

    result_iter = iter(raw_outputs)
    for is_valid in valid_mask:
        if is_valid:
            label_scores = next(result_iter)
            numeric_scores.append(_scores_to_numeric(label_scores))
            # Top label = whichever has the highest score
            top = max(label_scores, key=lambda x: x["score"])
            top_labels.append(top["label"].lower())
            top_confs.append(round(top["score"], 4))
        else:
            # Empty text -> no signal, treat as neutral
            numeric_scores.append(0.0)
            top_labels.append("neutral")
            top_confs.append(0.0)

    df = df.copy()
    df["sentiment_score"] = [round(s, 4) for s in numeric_scores]
    df["sentiment_label"] = top_labels
    df["sentiment_conf"] = top_confs

    return df


# ---------------------------------------------------------------------------
# Daily aggregation
# ---------------------------------------------------------------------------

def aggregate_daily(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse article-level scores into one row per (ticker, date).

    Parameters
    ----------
    df : pd.DataFrame
        Output of score_articles() — must have 'ticker', 'date',
        'sentiment_score', 'sentiment_label' columns.

    Returns
    -------
    pd.DataFrame with columns:
        ticker, date, sentiment_score (mean), headline_count,
        bullish_pct, bearish_pct, neutral_pct
    """
    if df.empty:
        return pd.DataFrame(columns=[
            "ticker", "date", "sentiment_score", "headline_count",
            "bullish_pct", "bearish_pct", "neutral_pct",
        ])

    # Ensure 'date' is a proper date type for clean grouping
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    rows = []
    for (ticker, date), group in df.groupby(["ticker", "date"]):
        n = len(group)

        # Mean of confidence-weighted scores across all articles that day
        daily_score = round(group["sentiment_score"].mean(), 4)

        # Label breakdown as percentages (useful for debugging & display)
        label_counts = group["sentiment_label"].value_counts()
        bullish_pct  = round(label_counts.get("positive", 0) / n * 100, 1)
        bearish_pct  = round(label_counts.get("negative", 0) / n * 100, 1)
        neutral_pct  = round(label_counts.get("neutral",  0) / n * 100, 1)

        rows.append({
            "ticker":          ticker,
            "date":            date,
            "sentiment_score": daily_score,
            "headline_count":  n,
            "bullish_pct":     bullish_pct,
            "bearish_pct":     bearish_pct,
            "neutral_pct":     neutral_pct,
        })

    result = pd.DataFrame(rows).sort_values(["ticker", "date"])
    result.reset_index(drop=True, inplace=True)
    return result


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def score_from_csv(
    csv_path: str,
    save: bool = True,
    source_tag: str = "",
) -> pd.DataFrame:
    """
    Full pipeline: load a text CSV -> score each row -> aggregate daily.

    Works for both news CSVs (news_fetcher.py) and reddit CSVs
    (reddit_fetcher.py) because both share the columns `ticker`, `date`,
    `headline`, `summary`.

    Parameters
    ----------
    csv_path : str
        Path to e.g. news_{ticker}_{date}.csv or reddit_{ticker}_{date}.csv.
    save : bool
        If True, write a sentiment CSV to data/raw/.
    source_tag : str
        Optional suffix baked into the output filename so multiple sources
        (news, reddit, ...) don't overwrite each other:
          ""        -> sentiment_{ticker}_{date}.csv         (news)
          "reddit"  -> sentiment_{ticker}_reddit_{date}.csv  (reddit)
        The aggregator globs sentiment_{ticker}_*.csv so both are picked up.

    Returns
    -------
    pd.DataFrame
        Daily aggregated sentiment scores.
    """
    print(f"[scorer] Loading {os.path.basename(csv_path)}...")
    news_df = pd.read_csv(csv_path)

    if news_df.empty:
        print("[scorer] Empty CSV -- nothing to score.")
        return pd.DataFrame()

    # Infer ticker from the filename (news_AAPL_2025-01-15.csv -> AAPL,
    # reddit_AAPL_2025-01-15.csv -> AAPL).  Both put ticker at index 1.
    basename = os.path.basename(csv_path)
    ticker = basename.split("_")[1] if "_" in basename else "UNKNOWN"

    # Add ticker column if missing (it should be there, but be defensive)
    if "ticker" not in news_df.columns:
        news_df["ticker"] = ticker

    # Reddit posts sometimes have empty selftext; make sure it's a string so
    # _build_text doesn't choke on NaN.
    if "summary" not in news_df.columns:
        news_df["summary"] = ""

    # Score all articles / posts
    scored_df = score_articles(news_df)

    # Collapse to daily summary
    daily_df = aggregate_daily(scored_df)

    if save and not daily_df.empty:
        _save(daily_df, ticker, source_tag=source_tag)

    return daily_df


def _save(df: pd.DataFrame, ticker: str, source_tag: str = "") -> str:
    """Write daily sentiment DataFrame to data/raw/."""
    raw_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    os.makedirs(raw_dir, exist_ok=True)

    date_str = datetime.date.today().strftime("%Y-%m-%d")
    suffix   = f"_{source_tag}" if source_tag else ""
    filename = f"sentiment_{ticker}{suffix}_{date_str}.csv"
    filepath = os.path.normpath(os.path.join(raw_dir, filename))

    df.to_csv(filepath, index=False)
    print(f"[scorer] Saved -> {filepath}")
    return filepath


def _find_latest_news_csv(ticker: str) -> str | None:
    """
    Glob data/raw/ for the most recently modified news CSV for `ticker`.
    Returns the path, or None if nothing is found.
    """
    raw_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    pattern = os.path.join(raw_dir, f"news_{ticker}_*.csv")
    matches = sorted(glob.glob(pattern))   # sorted = oldest -> newest by filename date
    return matches[-1] if matches else None


def _find_latest_reddit_csv(ticker: str) -> str | None:
    """Glob data/raw/ for the most recent reddit_{ticker}_*.csv."""
    raw_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
    pattern = os.path.join(raw_dir, f"reddit_{ticker}_*.csv")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    # Accept an optional CSV path as a command-line argument;
    # otherwise, auto-discover the latest AAPL news CSV.
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = _find_latest_news_csv("AAPL")

    if not csv_path or not os.path.exists(csv_path):
        print(
            "ERROR: No AAPL news CSV found in data/raw/.\n"
            "Run `python data/news_fetcher.py` first, then retry."
        )
        sys.exit(1)

    print(f"Using: {csv_path}\n")
    daily = score_from_csv(csv_path)

    if not daily.empty:
        print("\n=== Daily Sentiment Scores (AAPL) ===")
        print(daily.to_string(index=False))

        print(f"\nOverall average sentiment : {daily['sentiment_score'].mean():.4f}")
        print(f"Most bullish day          : {daily.loc[daily['sentiment_score'].idxmax(), 'date']}")
        print(f"Most bearish day          : {daily.loc[daily['sentiment_score'].idxmin(), 'date']}")

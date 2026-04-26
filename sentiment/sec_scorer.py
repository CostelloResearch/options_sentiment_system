# =============================================================================
# sentiment/sec_scorer.py -- Score SEC filings with FinBERT
#
# SEC filings are LONG (10-Ks run 50k+ words).  FinBERT's underlying BERT
# model has a hard 512-token input cap, so we:
#   1. Tokenise the filing body with FinBERT's own tokenizer
#   2. Chunk into non-overlapping 512-token windows
#   3. Score each chunk -> (positive, negative, neutral) probabilities
#   4. Aggregate to one per-filing score, weighted by chunk length (in tokens)
#
# SCORE FORMULA (same as scorer.py for consistency):
#   chunk_score   = P(positive) - P(negative)
#   filing_score  = sum(chunk_score * chunk_tokens) / sum(chunk_tokens)
#
# We also record the most-bearish and most-bullish chunks verbatim so a human
# reviewer can audit *why* a filing got a given score.  This is essential for
# trust in interview demos.
#
# CHUNK OVERLAP
# -------------
# We use non-overlapping windows (overlap_tokens=0) by default: we're
# averaging across many chunks so minor semantic-unit splits don't matter,
# and overlap doubles compute time.  Overlap can be enabled via the
# `overlap_tokens` argument for higher fidelity.
#
# OUTPUT CSV (data/raw/sec_sentiment_{ticker}.csv):
#   ticker, filing_date, filing_type, sentiment_score, chunk_count,
#   bullish_pct, bearish_pct, neutral_pct, most_bearish_chunk,
#   most_bullish_chunk, total_tokens, source_path
# =============================================================================

import os
import sys
import glob
import re
from typing import Optional, List

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from sentiment.scorer import _get_pipeline   # reuse the same FinBERT instance

from transformers import AutoTokenizer

RAW_DIR     = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "raw")
)
RAW_SEC_DIR = os.path.join(RAW_DIR, "sec")

_MODEL_NAME   = "ProsusAI/finbert"
_MAX_TOKENS   = 512    # BERT hard limit

# Tokenizer is separate from the pipeline so we can count tokens *before*
# running inference (chunking is a pre-processing step).
_tokenizer_cache = None

def _get_tokenizer():
    global _tokenizer_cache
    if _tokenizer_cache is None:
        print("[sec_scorer] Loading FinBERT tokenizer...")
        _tokenizer_cache = AutoTokenizer.from_pretrained(_MODEL_NAME)
    return _tokenizer_cache


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _chunk_text(
    text: str,
    max_tokens: int = _MAX_TOKENS,
    overlap_tokens: int = 0,
) -> List[str]:
    """
    Split `text` into chunks whose token counts (per FinBERT's tokenizer) do
    not exceed `max_tokens`.  Returns a list of decoded strings -- each
    guaranteed to fit through the model without truncation.

    `max_tokens` accounts for special tokens: BERT inserts [CLS] + [SEP]
    (2 tokens), so the effective content budget is 512 - 2 = 510.  We use
    510 to be safe.
    """
    tokenizer = _get_tokenizer()

    # Account for [CLS]/[SEP]
    content_budget = max_tokens - 2
    step = content_budget - overlap_tokens
    if step <= 0:
        raise ValueError("overlap_tokens must be smaller than content budget")

    # Encode WITHOUT special tokens (we'll decode back to text)
    ids = tokenizer.encode(text, add_special_tokens=False,
                           truncation=False)

    chunks = []
    for start in range(0, len(ids), step):
        window = ids[start:start + content_budget]
        if not window:
            break
        chunk = tokenizer.decode(window, skip_special_tokens=True)
        chunks.append(chunk.strip())
        if start + content_budget >= len(ids):
            break
    return chunks


# ---------------------------------------------------------------------------
# Per-chunk scoring
# ---------------------------------------------------------------------------

def _score_chunk(chunk: str) -> dict:
    """
    Run FinBERT on a single chunk and return the label probabilities plus
    a numeric score in [-1, +1].
    """
    pipe = _get_pipeline()
    # pipeline(top_k=None) returns [[{label, score}, ...]] for a list input.
    out = pipe(chunk, truncation=True, max_length=_MAX_TOKENS)[0]
    probs = {item["label"].lower(): float(item["score"]) for item in out}

    p_pos = probs.get("positive", 0.0)
    p_neg = probs.get("negative", 0.0)
    p_neu = probs.get("neutral",  0.0)

    return {
        "score":       p_pos - p_neg,
        "positive":    p_pos,
        "negative":    p_neg,
        "neutral":     p_neu,
    }


# ---------------------------------------------------------------------------
# Score a whole filing
# ---------------------------------------------------------------------------

def score_filing(filing_path: str) -> dict:
    """
    Load a .txt filing, chunk it, score each chunk, and aggregate.

    Returns a dict with:
      filing_path, chunk_count, total_tokens, sentiment_score,
      bullish_pct, bearish_pct, neutral_pct,
      most_bearish_chunk, most_bullish_chunk,
      most_bearish_score, most_bullish_score
    """
    with open(filing_path, "r", encoding="utf-8") as f:
        text = f.read()

    text = _squeeze_whitespace(text)

    if len(text) < 200:
        # Too short to be meaningful
        return _empty_filing_result(filing_path, reason="too_short")

    chunks = _chunk_text(text)
    if not chunks:
        return _empty_filing_result(filing_path, reason="no_chunks")

    tokenizer = _get_tokenizer()
    chunk_scores   = []
    chunk_tokens   = []
    label_counts   = {"positive": 0, "negative": 0, "neutral": 0}

    most_bearish = {"score": +2.0, "text": ""}
    most_bullish = {"score": -2.0, "text": ""}

    for ch in chunks:
        n_tok = len(tokenizer.encode(ch, add_special_tokens=False))
        if n_tok == 0:
            continue
        res = _score_chunk(ch)

        chunk_scores.append(res["score"])
        chunk_tokens.append(n_tok)

        # Dominant label
        dominant = max(
            ("positive", res["positive"]),
            ("negative", res["negative"]),
            ("neutral",  res["neutral"]),
            key=lambda x: x[1],
        )[0]
        label_counts[dominant] += 1

        if res["score"] < most_bearish["score"]:
            most_bearish = {"score": res["score"], "text": ch}
        if res["score"] > most_bullish["score"]:
            most_bullish = {"score": res["score"], "text": ch}

    if not chunk_scores:
        return _empty_filing_result(filing_path, reason="all_chunks_empty")

    total_tokens = sum(chunk_tokens)
    # Token-weighted average: longer chunks (more content) carry more weight
    weighted = sum(s * t for s, t in zip(chunk_scores, chunk_tokens)) / total_tokens

    n_chunks = len(chunk_scores)
    bullish_pct = label_counts["positive"] / n_chunks * 100.0
    bearish_pct = label_counts["negative"] / n_chunks * 100.0
    neutral_pct = label_counts["neutral"]  / n_chunks * 100.0

    return {
        "filing_path":        filing_path,
        "chunk_count":        n_chunks,
        "total_tokens":       total_tokens,
        "sentiment_score":    round(float(weighted), 4),
        "bullish_pct":        round(bullish_pct, 2),
        "bearish_pct":        round(bearish_pct, 2),
        "neutral_pct":        round(neutral_pct, 2),
        "most_bearish_chunk": _truncate(most_bearish["text"], 500),
        "most_bullish_chunk": _truncate(most_bullish["text"], 500),
        "most_bearish_score": round(most_bearish["score"], 4),
        "most_bullish_score": round(most_bullish["score"], 4),
    }


def _empty_filing_result(path: str, reason: str) -> dict:
    return {
        "filing_path":        path,
        "chunk_count":        0,
        "total_tokens":       0,
        "sentiment_score":    0.0,
        "bullish_pct":        0.0,
        "bearish_pct":        0.0,
        "neutral_pct":        0.0,
        "most_bearish_chunk": f"[skipped: {reason}]",
        "most_bullish_chunk": f"[skipped: {reason}]",
        "most_bearish_score": 0.0,
        "most_bullish_score": 0.0,
    }


def _squeeze_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[:n - 1].rstrip() + "..."


# ---------------------------------------------------------------------------
# Discover filings already saved to disk
# ---------------------------------------------------------------------------

_FILENAME_RE = re.compile(
    r"(?P<form>10-K|10-Q|8-K|10_K|10_Q|8_K)[\w.]*_(?P<date>\d{4}-\d{2}-\d{2})\.txt$",
    re.IGNORECASE,
)


def _parse_filing_filename(path: str) -> Optional[dict]:
    """Extract form + date from a file path like '10-K_2024-11-01.txt'."""
    m = _FILENAME_RE.search(os.path.basename(path))
    if not m:
        return None
    form = m.group("form").replace("_", "-").upper()
    return {"form": form, "date": m.group("date")}


def list_ticker_filings(ticker: str) -> List[dict]:
    """
    Return all on-disk filings for `ticker` as dicts with
    path/form/date/subcategory.

    Subcategory taxonomy (used downstream for the merger's earnings-vs-other
    weighting split):
      * "10-K_mdna"             : 10-K form (any year)
      * "10-Q_mdna"             : 10-Q form (any quarter)
      * "8-K_earnings_prepared" : 8-K cover containing "Item 2.02 / Results
                                  of Operations" AND a companion
                                  `_exhibit99.txt` exists.  Score the
                                  EXHIBIT (the press release / prepared
                                  remarks), not the cover.
      * "8-K_earnings_cover"    : Item 2.02 8-K with NO exhibit on disk.
                                  Score the cover (will be ~boilerplate;
                                  rare).
      * "8-K_other"             : 8-K without Item 2.02.  Score the cover.

    Companion `_exhibit99.txt` files are NOT returned as standalone rows --
    they're attached to their parent 8-K via the `path` field when the
    subcategory says to score the exhibit.
    """
    folder = os.path.join(RAW_SEC_DIR, ticker.upper())
    if not os.path.isdir(folder):
        return []
    rows = []
    for path in sorted(glob.glob(os.path.join(folder, "*.txt"))):
        # Skip exhibit files in this loop -- they're handled via their parent 8-K.
        if path.endswith("_exhibit99.txt"):
            continue
        meta = _parse_filing_filename(path)
        if not meta:
            continue
        form = meta["form"]
        date = meta["date"]

        sub = ""
        score_path = path
        if form == "10-K":
            sub = "10-K_mdna"
        elif form == "10-Q":
            sub = "10-Q_mdna"
        elif form == "8-K":
            # Detect earnings-related 8-Ks.  Two filer conventions:
            #
            #   (1) Item 2.02 "Results of Operations and Financial
            #       Condition" -- the official earnings press release
            #       (Apple, NVIDIA, WMT, most large-cap industrials).
            #
            #   (2) Item 7.01 "Regulation FD Disclosure" + earnings
            #       keyword in the body -- some filers (notably JPM,
            #       XOM, parts of healthcare) furnish their earnings-
            #       call slide deck or investor presentation under the
            #       Reg-FD item rather than as an officially-filed
            #       press release.  The text is functionally
            #       equivalent prepared-remarks content (CFO commentary,
            #       financial highlights), so we treat both as the same
            #       earnings_prepared subcategory for sentiment
            #       weighting purposes.
            #
            # We read up to 16 KB of the cover (older XBRL-heavy filings
            # push the Item-code text well past the 4 KB the prior
            # version checked).
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cover = f.read(16000)
            except Exception:
                cover = ""
            is_2_02 = bool(re.search(
                r"item\s*2\.02|results of operations",
                cover, re.IGNORECASE,
            ))
            is_7_01_earnings = bool(re.search(
                r"item\s*7\.01", cover, re.IGNORECASE,
            )) and bool(re.search(
                r"earnings|quarterly results|investor presentation|"
                r"financial results|quarter ended|results for the",
                cover, re.IGNORECASE,
            ))
            is_earnings = is_2_02 or is_7_01_earnings
            ex_path = path.replace(".txt", "_exhibit99.txt")
            has_exhibit = os.path.exists(ex_path)

            if is_earnings and has_exhibit:
                sub = "8-K_earnings_prepared"
                score_path = ex_path
            elif is_earnings:
                sub = "8-K_earnings_cover"
            else:
                sub = "8-K_other"
        else:
            sub = form  # unknown form types pass through

        rows.append({
            "ticker":      ticker.upper(),
            "filing_type": form,
            "filing_date": date,
            "subcategory": sub,
            "path":        score_path,
            "cover_path":  path,
        })
    return rows


# ---------------------------------------------------------------------------
# Score every filing for a ticker and save CSV
# ---------------------------------------------------------------------------

def score_all_filings(ticker: str, save: bool = True,
                      verbose: bool = True) -> pd.DataFrame:
    """
    Score every saved filing for `ticker` and write a per-ticker CSV.
    Skips filings already present in the CSV so re-runs are incremental.

    ETFs / non-issuer tickers (config.ETF_TICKERS) return empty silently
    with an explicit "news-only" log line, so callers iterating over the
    full universe don't have to special-case them.
    """
    if ticker.upper() in getattr(config, "ETF_TICKERS", set()):
        if verbose:
            print(f"[sec_scorer] {ticker}: ETF / non-issuer -- "
                  f"no SEC data, news-only sentiment.")
        return pd.DataFrame()

    filings = list_ticker_filings(ticker)
    if not filings:
        if verbose:
            print(f"[sec_scorer] No filings found under {RAW_SEC_DIR}/{ticker}.")
        return pd.DataFrame()

    out_path = os.path.join(RAW_DIR, f"sec_sentiment_{ticker.upper()}.csv")

    # Incremental: skip filings already scored.  Skip key now includes
    # `subcategory` so that an 8-K previously scored as cover-only
    # ("8-K_other") can be re-scored as "8-K_earnings_prepared" once a
    # companion Exhibit 99.1 lands -- they have different `subcategory`
    # values, so the existing-key set won't suppress the new score.
    existing = None
    if os.path.exists(out_path):
        try:
            existing = pd.read_csv(out_path)
            # Backwards compat: if existing CSV has no `subcategory` column,
            # treat all existing rows as match-anything by leaving
            # subcategory absent from the key.
            if "subcategory" in existing.columns:
                existing_keys = set(zip(
                    existing["filing_type"].astype(str),
                    existing["filing_date"].astype(str),
                    existing["subcategory"].astype(str),
                ))
                key_fn = lambda f: (f["filing_type"], f["filing_date"],
                                    f.get("subcategory", ""))
            else:
                existing_keys = set(zip(
                    existing["filing_type"].astype(str),
                    existing["filing_date"].astype(str),
                ))
                key_fn = lambda f: (f["filing_type"], f["filing_date"])
            before = len(filings)
            filings = [f for f in filings if key_fn(f) not in existing_keys]
            if verbose and (before - len(filings)) > 0:
                print(f"[sec_scorer] {ticker}: skipping "
                      f"{before - len(filings)} already-scored filings.")
        except Exception:
            existing = None   # corrupt CSV, rebuild from scratch

    if not filings and existing is not None:
        if verbose:
            print(f"[sec_scorer] {ticker}: nothing new to score.")
        return existing

    if verbose:
        print(f"[sec_scorer] {ticker}: scoring {len(filings)} filings...")

    rows = []
    for i, f in enumerate(filings, 1):
        if verbose:
            sub = f.get("subcategory", "")
            print(f"  [{i}/{len(filings)}] {f['filing_type']} "
                  f"{f['filing_date']} ({sub})...")
        res = score_filing(f["path"])
        rows.append({
            "ticker":             f["ticker"],
            "filing_date":        f["filing_date"],
            "filing_type":        f["filing_type"],
            "subcategory":        f.get("subcategory", f["filing_type"]),
            "sentiment_score":    res["sentiment_score"],
            "chunk_count":        res["chunk_count"],
            "bullish_pct":        res["bullish_pct"],
            "bearish_pct":        res["bearish_pct"],
            "neutral_pct":        res["neutral_pct"],
            "most_bearish_chunk": res["most_bearish_chunk"],
            "most_bullish_chunk": res["most_bullish_chunk"],
            "total_tokens":       res["total_tokens"],
            "source_path":        res["filing_path"],
        })

    df_new = pd.DataFrame(rows)

    if existing is not None and not existing.empty:
        df = pd.concat([existing, df_new], ignore_index=True)
        df = df.drop_duplicates(subset=["ticker", "filing_type", "filing_date"],
                                keep="last")
    else:
        df = df_new

    df = df.sort_values(["filing_date", "filing_type"]).reset_index(drop=True)

    if save:
        df.to_csv(out_path, index=False)
        if verbose:
            print(f"[sec_scorer] Saved -> {out_path} ({len(df)} rows total)")

    return df


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", default="AAPL")
    args = p.parse_args()

    df = score_all_filings(args.ticker)
    if not df.empty:
        cols = ["filing_date", "filing_type", "sentiment_score",
                "chunk_count", "bullish_pct", "bearish_pct"]
        print("\n" + df[cols].to_string(index=False))

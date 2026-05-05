# =============================================================================
# scripts/redup_backfill.py -- Re-dedup the scored backfill corpus
#
# The prior scoring run (scripts/score_backfill_chunks.py) deduped by `url`,
# but Finnhub's url query parameter `id=` is generated per-request and is NOT
# stable per-article (verified empirically: AAPL/NVDA/SPY came in at dedup
# ratio 1.00, i.e. zero URL dedup despite ~28% expected chunk-overlap
# duplicates).  Practical impact: `headline_count` is inflated 5-30% on
# high-volume tickers; sentiment_score and label percentages are unbiased
# (identical headlines produce identical FinBERT scores so per-day means
# absorb duplicates).
#
# This script re-derives `data/raw/sentiment_{T}_real.csv` from the raw
# chunk CSVs using `(headline_normalized, date)` as the dedup key and
# applies a date-range filter to remove the ~0.5% out-of-window outliers
# the v3 spike documented (Finnhub occasionally returns articles with a
# back-filled / reset stored datetime far outside the requested window;
# AAPL/GLD long-tail reaches 2011, NVDA/WMT 2020).
#
# CORRECTIVE POST-PROCESS, not a pipeline change.  The original scoring
# script stays on disk as a record of what was tried.  This script
# overwrites the per-ticker output files only, with the same canonical
# 7-column schema downstream consumers already expect.
#
# REUSES, DOES NOT REIMPLEMENT.  `score_articles` and `aggregate_daily`
# from `sentiment/scorer.py` provide inference and aggregation.  Idempotent:
# tickers whose manifest entry has `dedup_method == "headline_date_v2"`
# are skipped.
#
# USAGE
# -----
#   python scripts/redup_backfill.py                   # full corpus
#   python scripts/redup_backfill.py --ticker TLT      # single ticker
#   python scripts/redup_backfill.py --dry-run         # plan only
#   python scripts/redup_backfill.py --device cpu      # force CPU
# =============================================================================

from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
import sys
import time

import pandas as pd

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402

RAW_DIR        = os.path.join(PROJECT_ROOT, "data", "raw")
MANIFEST_PATH  = os.path.join(RAW_DIR, "scored_chunks_manifest.json")
OUT_FNAME_TMPL = "sentiment_{ticker}_real.csv"

# Backfill coverage window (locked; see prompt's "DO NOT MODIFY" note)
DATE_RANGE_MIN = "2025-05-05"  # Finnhub 12-month wall reached at chunk 28
DATE_RANGE_MAX = "2026-05-04"  # backfill anchor date

DEDUP_METHOD_TAG = "headline_date_v2"


# ---------------------------------------------------------------------------
# Manifest I/O (atomic; mirrors score_backfill_chunks.py pattern)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def load_manifest() -> dict:
    """Fail loudly if the manifest is missing or unreadable.  Operator
    must rerun score_backfill_chunks.py first to regenerate it -- we do
    not want to silently lose the URL-method audit trail."""
    if not os.path.exists(MANIFEST_PATH):
        print(f"[redup] ERROR: manifest not found at {MANIFEST_PATH}.  "
              f"Run scripts/score_backfill_chunks.py first.", file=sys.stderr)
        sys.exit(2)
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict) or "tickers" not in m:
            raise ValueError("manifest missing 'tickers' key")
        return m
    except Exception as e:
        print(f"[redup] ERROR: manifest at {MANIFEST_PATH} unreadable: {e}.  "
              f"Operator must inspect or regenerate via "
              f"scripts/score_backfill_chunks.py.", file=sys.stderr)
        sys.exit(2)


def save_manifest(manifest: dict) -> None:
    manifest["last_updated_at"] = _now_iso()
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    os.replace(tmp, MANIFEST_PATH)


# ---------------------------------------------------------------------------
# Atomic CSV write
# ---------------------------------------------------------------------------

def _atomic_to_csv(df: pd.DataFrame, path: str) -> None:
    tmp = path + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Per-ticker chunk loading + corrected dedup
# ---------------------------------------------------------------------------

def _ticker_chunk_paths(ticker: str) -> list:
    return sorted(glob.glob(os.path.join(RAW_DIR, f"news_{ticker}_chunk_*.csv")))


def _normalize_date_col(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce `date` to a YYYY-MM-DD string for comparison/dedup."""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def load_concat_chunks(ticker: str) -> tuple[pd.DataFrame, int]:
    """Concat all chunk CSVs for ticker; return (df, n_raw)."""
    required = {"ticker", "date", "datetime", "headline", "summary",
                "source", "url"}
    frames = []
    n_raw = 0
    for p in _ticker_chunk_paths(ticker):
        try:
            df = pd.read_csv(p)
        except Exception as e:
            print(f"[redup] {ticker}: WARN unreadable chunk "
                  f"{os.path.basename(p)}: {e}")
            continue
        if df.empty:
            continue
        if not required.issubset(set(df.columns)):
            print(f"[redup] {ticker}: WARN chunk {os.path.basename(p)} "
                  f"missing required columns -- skipping")
            continue
        n_raw += len(df)
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=sorted(required)), 0
    return pd.concat(frames, ignore_index=True), n_raw


def url_dedup_count(df: pd.DataFrame) -> int:
    """For audit only: how many rows survive URL-keep-first dedup?"""
    if df.empty or "url" not in df.columns:
        return 0
    sub = df.dropna(subset=["url"])
    return int(sub.drop_duplicates(subset=["url"], keep="first").shape[0])


def headline_date_dedup(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """The corrective dedup.  Returns (deduped_df, n_empty_headlines_dropped)."""
    if df.empty:
        return df, 0
    df = df.copy()
    # Coerce headline to string and trim/lowercase for dedup
    df["headline"] = df["headline"].fillna("").astype(str)
    df["headline_normalized"] = df["headline"].str.strip().str.lower()

    empty_mask = df["headline_normalized"] == ""
    n_empty = int(empty_mask.sum())
    if n_empty:
        df = df[~empty_mask].copy()

    # date is already a YYYY-MM-DD string after _normalize_date_col
    df = df.drop_duplicates(
        subset=["headline_normalized", "date"], keep="first")
    return df, n_empty


def date_range_filter(df: pd.DataFrame) -> tuple[pd.DataFrame, int, list]:
    """Drop rows outside [DATE_RANGE_MIN, DATE_RANGE_MAX].  Returns
    (filtered_df, n_dropped, sample_dropped_dates)."""
    if df.empty:
        return df, 0, []
    in_window = (df["date"] >= DATE_RANGE_MIN) & (df["date"] <= DATE_RANGE_MAX)
    dropped = df[~in_window]
    n_dropped = int(len(dropped))
    sample_dates = sorted(dropped["date"].unique().tolist())[:8] if n_dropped else []
    return df[in_window].reset_index(drop=True), n_dropped, sample_dates


# ---------------------------------------------------------------------------
# Per-ticker redup (FinBERT re-score on the corrected dedup frame)
# ---------------------------------------------------------------------------

def redup_ticker(ticker: str, manifest: dict) -> dict:
    out_path = os.path.join(RAW_DIR, OUT_FNAME_TMPL.format(ticker=ticker))
    entry = manifest["tickers"].get(ticker)

    if entry is None:
        print(f"[redup] {ticker}: no manifest entry "
              f"(scoring run did not include this ticker).  Skipping.")
        return {"ticker": ticker, "status": "missing_manifest_entry",
                "n_raw": 0, "n_url_dedup": 0, "n_hd_dedup": 0,
                "n_oow_filtered": 0, "n_daily": 0,
                "elapsed": 0.0, "skipped": True}

    if entry.get("dedup_method") == DEDUP_METHOD_TAG:
        print(f"[redup] {ticker}: skip (already redupped, "
              f"method={DEDUP_METHOD_TAG})")
        return {
            "ticker": ticker,
            "status": "complete_skipped",
            "n_raw":          entry.get("n_articles_raw", 0),
            "n_url_dedup":    entry.get("n_articles_after_dedup", 0),
            "n_hd_dedup":     entry.get("n_articles_after_redup", 0),
            "n_oow_filtered": entry.get("out_of_window_articles_filtered", 0),
            "n_daily":        entry.get("n_daily_rows_written", 0),
            "elapsed":        entry.get("redup_seconds", 0.0),
            "skipped":        True,
        }

    t0 = time.monotonic()

    df, n_raw = load_concat_chunks(ticker)
    if n_raw == 0:
        print(f"[redup] {ticker}: no chunk data found -- leaving prior "
              f"output file untouched")
        return {"ticker": ticker, "status": "no_chunk_data",
                "n_raw": 0, "n_url_dedup": 0, "n_hd_dedup": 0,
                "n_oow_filtered": 0, "n_daily": 0,
                "elapsed": time.monotonic() - t0, "skipped": False}

    df = _normalize_date_col(df)
    nan_date_mask = df["date"].isna()
    if nan_date_mask.any():
        n_nan = int(nan_date_mask.sum())
        print(f"[redup] {ticker}: dropping {n_nan} rows with NaN date")
        df = df[~nan_date_mask].copy()

    # Audit-only URL count on the same frame
    n_url = url_dedup_count(df)

    # Corrective (headline_normalized, date) dedup
    deduped, n_empty_hd = headline_date_dedup(df)
    n_hd = int(len(deduped))
    if n_empty_hd:
        print(f"[redup] {ticker}: dropped {n_empty_hd} rows with empty "
              f"headline before dedup")

    # Date-range filter
    filtered, n_oow, oow_sample_dates = date_range_filter(deduped)
    n_after_filter = int(len(filtered))

    if n_after_filter == 0:
        print(f"[redup] {ticker}: ERROR -- 0 rows survive the date-range "
              f"filter.  Leaving prior output file untouched.")
        manifest["tickers"][ticker]["status"] = "failed_post_filter"
        save_manifest(manifest)
        return {"ticker": ticker, "status": "failed_post_filter",
                "n_raw": n_raw, "n_url_dedup": n_url, "n_hd_dedup": n_hd,
                "n_oow_filtered": n_oow, "n_daily": 0,
                "elapsed": time.monotonic() - t0, "skipped": False}

    # Score the corrected frame and aggregate
    from sentiment.scorer import score_articles, aggregate_daily

    print(f"[redup] {ticker}: scoring {n_after_filter} corrected-dedup "
          f"articles via FinBERT...")
    scored = score_articles(filtered)

    # aggregate_daily expects `date` as date type; coerce back from string
    scored = scored.copy()
    scored["date"] = pd.to_datetime(scored["date"], errors="coerce").dt.date

    daily = aggregate_daily(scored)
    if daily.empty:
        print(f"[redup] {ticker}: aggregate_daily returned empty -- "
              f"marking failed")
        manifest["tickers"][ticker]["status"] = "failed_post_filter"
        save_manifest(manifest)
        return {"ticker": ticker, "status": "failed_post_filter",
                "n_raw": n_raw, "n_url_dedup": n_url, "n_hd_dedup": n_hd,
                "n_oow_filtered": n_oow, "n_daily": 0,
                "elapsed": time.monotonic() - t0, "skipped": False}

    _atomic_to_csv(daily, out_path)

    elapsed = time.monotonic() - t0
    earliest = str(daily["date"].min())
    latest   = str(daily["date"].max())

    # Manifest update: PRESERVE existing fields, ADD new ones
    entry["dedup_method"]                    = DEDUP_METHOD_TAG
    entry["n_articles_after_redup"]          = int(n_after_filter)
    entry["dedup_ratio_redup"]               = round(n_after_filter / n_raw, 4) if n_raw else 0.0
    entry["out_of_window_articles_filtered"] = int(n_oow)
    entry["out_of_window_sample_dates"]      = oow_sample_dates
    entry["date_range_filter"] = {"min_date": DATE_RANGE_MIN,
                                  "max_date": DATE_RANGE_MAX}
    entry["n_daily_rows_written"]            = int(len(daily))
    entry["earliest_date"]                   = earliest
    entry["latest_date"]                     = latest
    entry["redup_seconds"]                   = round(elapsed, 2)
    entry["status"]                          = "complete"
    save_manifest(manifest)

    print(f"[redup] {ticker}: raw={n_raw} url_dedup={n_url} "
          f"hd_dedup={n_hd} oow_filtered={n_oow} "
          f"final={n_after_filter} daily_rows={len(daily)} "
          f"date_span={earliest}->{latest} elapsed={elapsed:.1f}s "
          f"-> {out_path}")

    return {
        "ticker":         ticker,
        "status":         "complete",
        "n_raw":          n_raw,
        "n_url_dedup":    n_url,
        "n_hd_dedup":     n_hd,
        "n_oow_filtered": n_oow,
        "n_daily":        int(len(daily)),
        "earliest":       earliest,
        "latest":         latest,
        "elapsed":        elapsed,
        "skipped":        False,
    }


# ---------------------------------------------------------------------------
# Dry-run plan (no FinBERT load, no scoring, no writes)
# ---------------------------------------------------------------------------

def _resolve_device(arg: str) -> str:
    if arg == "auto":
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    return arg


def print_dry_run(tickers: list, device: str) -> None:
    print(f"[redup] DRY RUN -- planning only, no FinBERT load, no writes.")
    print(f"[redup] device={device}, dedup_method={DEDUP_METHOD_TAG}, "
          f"date_range={DATE_RANGE_MIN}..{DATE_RANGE_MAX}")
    per_article_ms = 10.0 if device == "cuda" else 50.0
    grand_raw = 0
    grand_url = 0
    grand_hd  = 0
    grand_post = 0
    grand_seconds = 0.0
    for t in tickers:
        df, n_raw = load_concat_chunks(t)
        if n_raw == 0:
            print(f"  {t}: no chunk data")
            continue
        df = _normalize_date_col(df)
        df = df[~df["date"].isna()]
        n_url = url_dedup_count(df)
        deduped, _ = headline_date_dedup(df)
        n_hd = len(deduped)
        filtered, n_oow, _ = date_range_filter(deduped)
        n_post = len(filtered)
        est_seconds = n_post * per_article_ms / 1000.0
        grand_raw     += n_raw
        grand_url     += n_url
        grand_hd      += n_hd
        grand_post    += n_post
        grand_seconds += est_seconds
        print(f"  {t}: raw={n_raw} url_dedup={n_url} hd_dedup={n_hd} "
              f"oow_filtered={n_oow} post={n_post}  "
              f"~{est_seconds:.0f}s scoring")
    print(f"[redup] TOTAL: raw={grand_raw} url_dedup={grand_url} "
          f"hd_dedup={grand_hd} post={grand_post}, "
          f"~{grand_seconds/60:.1f} min scoring wall clock (estimate)")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(rows: list, total_elapsed: float) -> None:
    print()
    print("=" * 96)
    print("  REDUP SUMMARY")
    print("=" * 96)
    print(f"  {'ticker':<6}  {'status':<22}  {'n_raw':>6}  {'url':>6}  "
          f"{'hd':>6}  {'oow':>4}  {'rows':>5}  {'elapsed':>8}")
    sum_raw = sum_url = sum_hd = sum_oow = sum_daily = 0
    sum_elapsed = 0.0
    for r in rows:
        print(f"  {r['ticker']:<6}  {r['status']:<22}  "
              f"{r['n_raw']:>6}  {r['n_url_dedup']:>6}  "
              f"{r['n_hd_dedup']:>6}  {r['n_oow_filtered']:>4}  "
              f"{r['n_daily']:>5}  {r['elapsed']:>7.1f}s")
        sum_raw     += r["n_raw"]
        sum_url     += r["n_url_dedup"]
        sum_hd      += r["n_hd_dedup"]
        sum_oow     += r["n_oow_filtered"]
        sum_daily   += r["n_daily"]
        if not r["skipped"]:
            sum_elapsed += r["elapsed"]
    print(f"  {'TOTAL':<6}  {'':<22}  {sum_raw:>6}  {sum_url:>6}  "
          f"{sum_hd:>6}  {sum_oow:>4}  {sum_daily:>5}  "
          f"{sum_elapsed:>7.1f}s")
    print()
    print(f"  Wall clock (this run): {total_elapsed:.1f}s "
          f"({total_elapsed/60:.1f} min)")
    print("=" * 96)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Re-dedup the scored backfill corpus by "
                    "(headline_normalized, date) and apply a date-range "
                    "filter; overwrite per-ticker sentiment_*_real.csv."
    )
    ap.add_argument("--ticker",  type=str, default=None,
                    help="Redup one ticker only.  Default: all in config.TICKERS.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan only; no scoring, no writes.")
    ap.add_argument("--device",  choices=["cpu", "cuda", "auto"], default="auto",
                    help="Device override (default 'auto').")
    args = ap.parse_args()

    tickers = [args.ticker] if args.ticker else list(config.TICKERS)
    for t in tickers:
        if t not in config.TICKERS:
            print(f"[redup] WARNING: {t} is not in config.TICKERS")

    device = _resolve_device(args.device)

    if args.dry_run:
        print_dry_run(tickers, device)
        return

    manifest = load_manifest()

    # Top-level redup_run record (created once on first non-dry-run invocation,
    # extended on subsequent runs)
    if "redup_run" not in manifest:
        manifest["redup_run"] = {
            "started_at":        _now_iso(),
            "completed_at":      None,
            "method":            DEDUP_METHOD_TAG,
            "date_range_filter": {"min": DATE_RANGE_MIN, "max": DATE_RANGE_MAX},
            "total_seconds":     0.0,
        }
    save_manifest(manifest)

    t0 = time.monotonic()
    rows: list = []
    for i, ticker in enumerate(tickers):
        print()
        print(f"--- {ticker} ({i+1}/{len(tickers)}) ---")
        rows.append(redup_ticker(ticker, manifest))
    total_elapsed = time.monotonic() - t0

    manifest["redup_run"]["completed_at"]  = _now_iso()
    manifest["redup_run"]["total_seconds"] = round(
        manifest["redup_run"].get("total_seconds", 0.0) + total_elapsed, 2)
    save_manifest(manifest)

    print_summary(rows, total_elapsed)


if __name__ == "__main__":
    main()

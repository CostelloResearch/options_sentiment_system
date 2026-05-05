# =============================================================================
# scripts/score_backfill_chunks.py -- Score the chunked-backfill news corpus
#
# Reads `data/raw/news_{TICKER}_chunk_*.csv` produced by
# `scripts/backfill_news_history.py`, dedups across overlapping chunks (key:
# `url`), runs FinBERT scoring via the existing `sentiment/scorer.py`
# primitives, aggregates to per-(ticker, date) daily rows, and writes a
# single canonical `data/raw/sentiment_{TICKER}_real.csv` per ticker.
#
# IDEMPOTENT.  Manifest at `data/raw/scored_chunks_manifest.json` tracks
# which tickers have been scored; reruns skip completed tickers.  Manifest
# and CSV writes are atomic (tmp + os.replace).
#
# REUSES, DOES NOT REIMPLEMENT.  `score_articles` and `aggregate_daily` from
# `sentiment/scorer.py` are the inference and aggregation primitives.  The
# scorer's module-level FinBERT cache means the model loads once per
# process across all 10 tickers.
#
# DECOUPLED FROM FETCH.  No Finnhub API calls.  No new fetcher behaviour.
# The daily pipeline (`scripts/run_daily.py`) is unchanged and continues
# to produce `sentiment_{T}_{TODAY}.csv` files alongside the real-mode
# corpus this script writes.
#
# USAGE
# -----
#   python scripts/score_backfill_chunks.py                  # full corpus
#   python scripts/score_backfill_chunks.py --ticker GLD     # one ticker
#   python scripts/score_backfill_chunks.py --dry-run        # plan only
#   python scripts/score_backfill_chunks.py --reset          # ignore manifest
#   python scripts/score_backfill_chunks.py --device cpu     # force CPU
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

DEDUP_KEY              = "url"
DEDUP_RATIO_LO         = 0.55  # warn if surviving fraction is outside this band
DEDUP_RATIO_HI         = 0.80


# ---------------------------------------------------------------------------
# Manifest I/O (atomic; mirrors backfill_news_history.py pattern)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _new_manifest(device: str, batch_size: int) -> dict:
    return {
        "started_at":      _now_iso(),
        "last_updated_at": _now_iso(),
        "config": {
            "dedup_key":  DEDUP_KEY,
            "batch_size": batch_size,
            "device":     device,
        },
        "tickers": {},
        "totals":  {
            "n_articles_raw":         0,
            "n_articles_after_dedup": 0,
            "scoring_seconds":        0.0,
        },
    }


def load_manifest(reset: bool, device: str, batch_size: int) -> dict:
    if reset or not os.path.exists(MANIFEST_PATH):
        return _new_manifest(device, batch_size)
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            m = json.load(f)
        if not isinstance(m, dict) or "tickers" not in m:
            raise ValueError("manifest missing 'tickers' key")
        return m
    except Exception as e:
        print(f"[score] ERROR: existing manifest at {MANIFEST_PATH} "
              f"is unreadable: {e}", file=sys.stderr)
        print(f"[score] Refusing to overwrite without --reset.  "
              f"Inspect by hand or pass --reset to start fresh.",
              file=sys.stderr)
        sys.exit(2)


def save_manifest(manifest: dict) -> None:
    manifest["last_updated_at"] = _now_iso()
    os.makedirs(RAW_DIR, exist_ok=True)
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
# Per-ticker chunk loading + dedup
# ---------------------------------------------------------------------------

def _ticker_chunk_paths(ticker: str) -> list:
    return sorted(glob.glob(os.path.join(RAW_DIR, f"news_{ticker}_chunk_*.csv")))


def load_and_dedup(ticker: str) -> tuple[pd.DataFrame, int, int]:
    """Concat all chunk CSVs for ticker, dedup by url, sort ascending by
    datetime.  Returns (deduped_df, n_raw, n_after_dedup).  Malformed
    chunks (missing required columns) are skipped with a warning."""
    paths = _ticker_chunk_paths(ticker)
    required = {"ticker", "date", "datetime", "headline", "summary",
                "source", "url"}
    frames = []
    n_raw = 0
    for p in paths:
        try:
            df = pd.read_csv(p)
        except Exception as e:
            print(f"[score] {ticker}: WARN unreadable chunk {os.path.basename(p)}: {e}")
            continue
        if df.empty:
            continue
        missing = required - set(df.columns)
        if missing:
            print(f"[score] {ticker}: WARN chunk {os.path.basename(p)} "
                  f"missing columns {missing} -- skipping")
            continue
        n_raw += len(df)
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=sorted(required)), 0, 0

    df = pd.concat(frames, ignore_index=True)

    # Drop NaN urls before dedup -- they would all collapse to a single row
    nan_mask = df[DEDUP_KEY].isna()
    if nan_mask.any():
        n_nan = int(nan_mask.sum())
        print(f"[score] {ticker}: dropping {n_nan} rows with NaN url before dedup")
        df = df[~nan_mask].copy()

    df = df.drop_duplicates(subset=[DEDUP_KEY], keep="first")

    # Post-dedup invariant
    assert df[DEDUP_KEY].is_unique, f"{ticker}: dedup left non-unique urls"

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.sort_values("datetime", ascending=True).reset_index(drop=True)

    n_after = len(df)
    return df, n_raw, n_after


def _check_dedup_ratio(ticker: str, n_raw: int, n_after: int) -> None:
    if n_raw == 0:
        return
    ratio = n_after / n_raw
    if ratio < DEDUP_RATIO_LO or ratio > DEDUP_RATIO_HI:
        print(f"[score] {ticker}: WARN dedup ratio {ratio:.3f} outside "
              f"expected {DEDUP_RATIO_LO}-{DEDUP_RATIO_HI} band "
              f"({n_after}/{n_raw} surviving)")
    else:
        print(f"[score] {ticker}: dedup ratio {ratio:.3f} "
              f"({n_after}/{n_raw} surviving)")


# ---------------------------------------------------------------------------
# Per-ticker scoring (reuses sentiment/scorer.py)
# ---------------------------------------------------------------------------

def score_ticker(ticker: str, manifest: dict) -> dict:
    """Score one ticker end-to-end.  Mutates manifest; saves on completion.
    Returns stats dict for the summary table."""
    out_path = os.path.join(RAW_DIR, OUT_FNAME_TMPL.format(ticker=ticker))

    # Idempotency: if manifest says complete AND output file is on disk, skip
    entry = manifest["tickers"].get(ticker)
    if (entry is not None and entry.get("status") == "complete"
            and os.path.exists(out_path)):
        print(f"[score] {ticker}: skip (status=complete, "
              f"{entry.get('n_daily_rows_written', 0)} daily rows on file)")
        return {
            "ticker":     ticker,
            "status":     "complete",
            "n_raw":      entry.get("n_articles_raw", 0),
            "n_dedup":    entry.get("n_articles_after_dedup", 0),
            "n_daily":   entry.get("n_daily_rows_written", 0),
            "earliest":  entry.get("earliest_date"),
            "latest":    entry.get("latest_date"),
            "elapsed":   entry.get("scoring_seconds", 0.0),
            "skipped":   True,
        }

    t0 = time.monotonic()

    df, n_raw, n_after = load_and_dedup(ticker)
    if n_raw == 0:
        print(f"[score] {ticker}: no chunk data found")
        manifest["tickers"][ticker] = {
            "scored_chunks":          [],
            "n_articles_raw":         0,
            "n_articles_after_dedup": 0,
            "n_daily_rows_written":   0,
            "earliest_date":          None,
            "latest_date":            None,
            "status":                 "no_data",
            "scoring_seconds":        0.0,
        }
        save_manifest(manifest)
        return {"ticker": ticker, "status": "no_data", "n_raw": 0,
                "n_dedup": 0, "n_daily": 0, "earliest": None,
                "latest": None, "elapsed": 0.0, "skipped": False}

    _check_dedup_ratio(ticker, n_raw, n_after)

    # Inference + daily aggregation -- reuse scorer primitives
    from sentiment.scorer import score_articles, aggregate_daily

    # ensure date column is a date (aggregate_daily re-coerces, but keep clean)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

    print(f"[score] {ticker}: scoring {n_after} deduped articles via FinBERT...")
    scored = score_articles(df)
    daily  = aggregate_daily(scored)

    if daily.empty:
        print(f"[score] {ticker}: aggregate_daily returned empty -- "
              f"marking failed")
        manifest["tickers"][ticker] = {
            "scored_chunks":          [os.path.basename(p)
                                       for p in _ticker_chunk_paths(ticker)],
            "n_articles_raw":         n_raw,
            "n_articles_after_dedup": n_after,
            "n_daily_rows_written":   0,
            "earliest_date":          None,
            "latest_date":            None,
            "status":                 "failed",
            "scoring_seconds":        round(time.monotonic() - t0, 2),
        }
        save_manifest(manifest)
        return {"ticker": ticker, "status": "failed", "n_raw": n_raw,
                "n_dedup": n_after, "n_daily": 0, "earliest": None,
                "latest": None,
                "elapsed": time.monotonic() - t0, "skipped": False}

    _atomic_to_csv(daily, out_path)

    earliest_date = str(daily["date"].min())
    latest_date   = str(daily["date"].max())
    elapsed       = time.monotonic() - t0

    # Record to_date string of every chunk consumed -- aligns with backfill manifest
    chunk_to_dates = []
    for p in _ticker_chunk_paths(ticker):
        base = os.path.basename(p)
        # "news_{T}_chunk_{TO_DATE}.csv"
        prefix = f"news_{ticker}_chunk_"
        if base.startswith(prefix) and base.endswith(".csv"):
            chunk_to_dates.append(base[len(prefix):-4])

    manifest["tickers"][ticker] = {
        "scored_chunks":          chunk_to_dates,
        "n_articles_raw":         int(n_raw),
        "n_articles_after_dedup": int(n_after),
        "n_daily_rows_written":   int(len(daily)),
        "earliest_date":          earliest_date,
        "latest_date":            latest_date,
        "status":                 "complete",
        "scoring_seconds":        round(elapsed, 2),
    }
    # Update totals
    manifest["totals"]["n_articles_raw"] = sum(
        v.get("n_articles_raw", 0) for v in manifest["tickers"].values())
    manifest["totals"]["n_articles_after_dedup"] = sum(
        v.get("n_articles_after_dedup", 0) for v in manifest["tickers"].values())
    manifest["totals"]["scoring_seconds"] = round(sum(
        v.get("scoring_seconds", 0.0) for v in manifest["tickers"].values()), 2)
    save_manifest(manifest)

    print(f"[score] {ticker}: done raw={n_raw} dedup={n_after} "
          f"ratio={n_after/n_raw:.2f} daily_rows={len(daily)} "
          f"date_span={earliest_date}->{latest_date} elapsed={elapsed:.1f}s "
          f"-> {out_path}")

    return {
        "ticker":   ticker,
        "status":   "complete",
        "n_raw":    n_raw,
        "n_dedup":  n_after,
        "n_daily":  len(daily),
        "earliest": earliest_date,
        "latest":   latest_date,
        "elapsed":  elapsed,
        "skipped":  False,
    }


# ---------------------------------------------------------------------------
# Dry-run plan
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
    print(f"[score] DRY RUN -- planning only, no FinBERT load, no scoring.")
    print(f"[score] device={device}, dedup_key={DEDUP_KEY}")
    per_article_ms = 10.0 if device == "cuda" else 50.0
    grand_raw = 0
    grand_est_dedup = 0
    grand_seconds = 0.0
    for t in tickers:
        paths = _ticker_chunk_paths(t)
        n_raw = 0
        for p in paths:
            try:
                n_raw += sum(1 for _ in open(p, "r", encoding="utf-8")) - 1
            except Exception:
                pass
        n_raw = max(n_raw, 0)
        est_dedup = int(n_raw * 0.65)  # midpoint of 0.55-0.80 expected band
        est_seconds = est_dedup * per_article_ms / 1000.0
        grand_raw += n_raw
        grand_est_dedup += est_dedup
        grand_seconds += est_seconds
        print(f"  {t}: {len(paths)} chunks, ~{n_raw} raw articles, "
              f"~{est_dedup} after dedup, ~{est_seconds:.0f}s scoring "
              f"(at {per_article_ms:.0f} ms/article)")
    print(f"[score] TOTAL: ~{grand_raw} raw, ~{grand_est_dedup} deduped, "
          f"~{grand_seconds/60:.1f} min scoring wall clock (estimate)")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(rows: list, total_elapsed: float) -> None:
    print()
    print("=" * 84)
    print("  SCORING SUMMARY")
    print("=" * 84)
    print(f"  {'ticker':<6}  {'status':<10}  {'n_raw':>6}  "
          f"{'n_dedup':>7}  {'ratio':>5}  {'rows':>5}  "
          f"{'span':<24}  {'elapsed':>8}")
    sum_raw = sum_dedup = sum_daily = 0
    sum_elapsed = 0.0
    for r in rows:
        ratio = (r["n_dedup"] / r["n_raw"]) if r["n_raw"] else 0.0
        span = (f"{r['earliest']} -> {r['latest']}"
                if r["earliest"] and r["latest"] else "n/a")
        print(f"  {r['ticker']:<6}  {r['status']:<10}  "
              f"{r['n_raw']:>6}  {r['n_dedup']:>7}  "
              f"{ratio:>5.2f}  {r['n_daily']:>5}  "
              f"{span:<24}  {r['elapsed']:>7.1f}s")
        sum_raw     += r["n_raw"]
        sum_dedup   += r["n_dedup"]
        sum_daily   += r["n_daily"]
        if not r["skipped"]:
            sum_elapsed += r["elapsed"]
    print(f"  {'TOTAL':<6}  {'':<10}  {sum_raw:>6}  {sum_dedup:>7}  "
          f"{(sum_dedup/sum_raw if sum_raw else 0):>5.2f}  "
          f"{sum_daily:>5}  {'':<24}  {sum_elapsed:>7.1f}s")
    print()
    print(f"  Wall clock (this run): {total_elapsed:.1f}s "
          f"({total_elapsed/60:.1f} min)")
    print("=" * 84)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Score the chunked-backfill news corpus with FinBERT, "
                    "dedup across chunks, write per-ticker daily-aggregated "
                    "real-mode sentiment CSVs."
    )
    ap.add_argument("--ticker",  type=str, default=None,
                    help="Score one ticker only.  Default: all in config.TICKERS.")
    ap.add_argument("--reset",   action="store_true",
                    help="Ignore existing manifest and re-score from scratch.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan only.  No FinBERT load, no scoring.")
    ap.add_argument("--device",  choices=["cpu", "cuda", "auto"], default="auto",
                    help="Device override.  Default 'auto' uses cuda if available.")
    args = ap.parse_args()

    tickers = [args.ticker] if args.ticker else list(config.TICKERS)
    for t in tickers:
        if t not in config.TICKERS:
            print(f"[score] WARNING: {t} is not in config.TICKERS")

    device = _resolve_device(args.device)

    if args.dry_run:
        print_dry_run(tickers, device)
        return

    # Inspect scorer's BATCH_SIZE for the manifest config record (read only)
    from sentiment.scorer import BATCH_SIZE as SCORER_BATCH_SIZE

    manifest = load_manifest(reset=args.reset, device=device,
                             batch_size=SCORER_BATCH_SIZE)

    t0 = time.monotonic()
    rows: list = []
    for i, ticker in enumerate(tickers):
        print()
        print(f"--- {ticker} ({i+1}/{len(tickers)}) ---")
        rows.append(score_ticker(ticker, manifest))
    total_elapsed = time.monotonic() - t0

    print_summary(rows, total_elapsed)


if __name__ == "__main__":
    main()

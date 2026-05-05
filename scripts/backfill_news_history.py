# =============================================================================
# scripts/backfill_news_history.py -- Chunked Finnhub historical news backfill
#
# Walks `to=` backwards in 14-day chunks per ticker until either Finnhub
# returns zero articles (12-month free-tier depth ceiling) or MAX_CHUNKS_PER_TICKER
# is reached.  Writes raw `news_{TICKER}_chunk_{TO_DATE}.csv` files; FinBERT
# scoring is a follow-up prompt's job and is NOT done here.
#
# RESTARTABLE.  A manifest at data/raw/backfill_manifest.json tracks completed
# chunks per ticker; reruns skip chunks already on disk.  Manifest writes are
# atomic (tmp + os.replace) so a SIGKILL mid-write cannot corrupt it.
#
# RATE-LIMIT DEFENSIVE.  The orchestrator paces calls under the documented
# Finnhub free-tier 60/min cap and retries transient failures with exponential
# backoff (2s, 4s, 8s, 16s, 32s).  After 5 failed attempts the ticker is left
# `in_progress` and the next session will retry it.
#
# DEPTH-CEILING DETECTION.  An empty response after >=2 successful chunks is
# the 12-month wall (per spike-chain v3).  An empty response on the FIRST chunk
# is more likely an auth failure and is flagged for operator review rather
# than mistaken for ceiling.
#
# USAGE
# -----
#   python scripts/backfill_news_history.py                        # full run
#   python scripts/backfill_news_history.py --ticker AAPL          # one ticker
#   python scripts/backfill_news_history.py --max-chunks 3         # cap per ticker
#   python scripts/backfill_news_history.py --dry-run              # plan only
#   python scripts/backfill_news_history.py --reset                # ignore manifest
# =============================================================================

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402
from data.news_fetcher import fetch_news_chunk, BackfillFetchError  # noqa: E402

RAW_DIR       = os.path.join(PROJECT_ROOT, "data", "raw")
MANIFEST_PATH = os.path.join(RAW_DIR, "backfill_manifest.json")

# Tuning constants (top-of-file, justified inline per project convention)
DAYS_PER_CHUNK         = 14    # oversized window; expect 7-9 unique-date days back
TARGET_HORIZON_DAYS    = 380   # 12 months + 2 weeks of buffer; informational
MAX_CHUNKS_PER_TICKER  = 52    # ~1 chunk/week * 52 weeks; defensive ceiling
TICKER_PACING_SECONDS  = 1.5   # matches fetch_all_tickers in news_fetcher.py
CHUNK_PACING_SECONDS   = 1.0   # within-ticker; under 60/min documented cap
RETRY_MAX_ATTEMPTS     = 5
RETRY_BACKOFF_BASE     = 2.0   # 2s, 4s, 8s, 16s, 32s
RETRY_BACKOFF_CAP      = 32.0


# ---------------------------------------------------------------------------
# Manifest I/O (atomic)
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _empty_ticker_entry() -> dict:
    return {
        "completed_chunks":         [],
        "earliest_to_date_reached": None,
        "status":                   "in_progress",
    }


def _new_manifest() -> dict:
    return {
        "started_at":      _now_iso(),
        "last_updated_at": _now_iso(),
        "config": {
            "days_per_chunk":        DAYS_PER_CHUNK,
            "target_horizon_days":   TARGET_HORIZON_DAYS,
            "ticker_pacing_seconds": TICKER_PACING_SECONDS,
        },
        "tickers": {},
    }


def load_manifest(reset: bool) -> dict:
    """Read the manifest from disk.  On corruption: log and exit non-zero
    (do not silently overwrite the operator's data).  On --reset or
    fresh start: return a new empty manifest."""
    if reset or not os.path.exists(MANIFEST_PATH):
        return _new_manifest()
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            m = json.load(f)
        # Light schema sanity
        if not isinstance(m, dict) or "tickers" not in m:
            raise ValueError("manifest missing 'tickers' key")
        return m
    except Exception as e:
        print(f"[backfill] ERROR: existing manifest at {MANIFEST_PATH} "
              f"is unreadable: {e}", file=sys.stderr)
        print(f"[backfill] Refusing to overwrite without --reset.  "
              f"Inspect the file by hand or pass --reset to start fresh.",
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
# Idempotency reconciliation
# ---------------------------------------------------------------------------

def _chunk_csv_path(ticker: str, to_date: datetime.date) -> str:
    return os.path.join(RAW_DIR, f"news_{ticker}_chunk_{to_date.strftime('%Y-%m-%d')}.csv")


def reconcile_ticker(manifest: dict, ticker: str) -> None:
    """Cross-check the manifest's completed_chunks for `ticker` against
    on-disk chunk CSVs.  Two reconciliations:

      1. CSV exists on disk but not in manifest -> add to manifest
         (manifest write previously failed; chunk content is on disk).
      2. Manifest claims chunk completed but CSV is missing on disk ->
         drop from manifest, will be re-fetched.

    Mutates the manifest in place.  Caller is responsible for save."""
    if ticker not in manifest["tickers"]:
        manifest["tickers"][ticker] = _empty_ticker_entry()
    entry = manifest["tickers"][ticker]
    listed = {c["to_date"]: c for c in entry["completed_chunks"]}

    # Drop manifest entries whose CSV is gone
    kept = []
    for c in entry["completed_chunks"]:
        to_dt = datetime.date.fromisoformat(c["to_date"])
        if os.path.exists(_chunk_csv_path(ticker, to_dt)):
            kept.append(c)
        else:
            print(f"[backfill] {ticker}: manifest claims chunk to={c['to_date']} "
                  f"complete, but CSV missing -- will refetch")
    entry["completed_chunks"] = kept

    # Adopt orphan CSVs (on disk, missing from manifest) as completed
    prefix = f"news_{ticker}_chunk_"
    if os.path.isdir(RAW_DIR):
        for fname in sorted(os.listdir(RAW_DIR)):
            if not (fname.startswith(prefix) and fname.endswith(".csv")):
                continue
            to_str = fname[len(prefix):-4]  # strip prefix + ".csv"
            if to_str in {c["to_date"] for c in entry["completed_chunks"]}:
                continue
            try:
                to_dt = datetime.date.fromisoformat(to_str)
            except ValueError:
                continue
            from_dt = to_dt - datetime.timedelta(days=DAYS_PER_CHUNK)
            # Read row count for n_articles; tolerate read failure
            n_articles = _safe_csv_rowcount(_chunk_csv_path(ticker, to_dt))
            entry["completed_chunks"].append({
                "to_date":      to_str,
                "from_date":    from_dt.strftime("%Y-%m-%d"),
                "n_articles":   n_articles,
                "completed_at": _now_iso(),
            })
            print(f"[backfill] {ticker}: adopted orphan chunk to={to_str} "
                  f"(n_articles={n_articles}) into manifest")

    # Recompute earliest_to_date_reached
    if entry["completed_chunks"]:
        entry["earliest_to_date_reached"] = min(c["to_date"] for c in entry["completed_chunks"])
    else:
        entry["earliest_to_date_reached"] = None


def _safe_csv_rowcount(path: str) -> int:
    """Return data-row count of a CSV (header excluded), 0 on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            n = sum(1 for _ in f)
        return max(n - 1, 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Per-ticker chunk loop
# ---------------------------------------------------------------------------

def _next_to_date(entry: dict, today: datetime.date) -> datetime.date:
    """Walk-backwards step.  First chunk anchors to today; subsequent chunks
    advance by (DAYS_PER_CHUNK - 1) so adjacent chunks overlap by 1 day.
    The overlap is intentional defence against off-by-one boundary edge
    cases at the request -> response date-translation step."""
    if entry["earliest_to_date_reached"] is None:
        return today
    earliest = datetime.date.fromisoformat(entry["earliest_to_date_reached"])
    return earliest - datetime.timedelta(days=DAYS_PER_CHUNK - 1)


def _fetch_with_retry(ticker: str, to_date: datetime.date) -> "pd.DataFrame":
    """Wrap fetch_news_chunk with exponential-backoff retry on
    BackfillFetchError.  Returns the (possibly empty) DataFrame on success.
    Raises BackfillFetchError after RETRY_MAX_ATTEMPTS."""
    last_exc: Exception | None = None
    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            return fetch_news_chunk(
                ticker, to_date, days=DAYS_PER_CHUNK, save_dir=RAW_DIR,
            )
        except BackfillFetchError as e:
            last_exc = e
            wait = min(RETRY_BACKOFF_BASE ** attempt, RETRY_BACKOFF_CAP)
            print(f"[backfill] {ticker} to={to_date} attempt {attempt+1}/{RETRY_MAX_ATTEMPTS} "
                  f"failed: {e}.  Sleeping {wait:.0f}s then retrying.")
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


def run_ticker(manifest: dict, ticker: str, max_chunks: int) -> dict:
    """Execute the chunk loop for one ticker.  Mutates manifest; saves on
    every chunk.  Returns a stats dict for the end-of-run summary."""
    reconcile_ticker(manifest, ticker)
    save_manifest(manifest)
    entry = manifest["tickers"][ticker]

    if entry["status"] in ("complete", "depth_ceiling"):
        print(f"[backfill] {ticker}: skip (status={entry['status']}, "
              f"{len(entry['completed_chunks'])} chunks on file)")
        return {"ticker": ticker, "status": entry["status"],
                "chunks": len(entry["completed_chunks"]),
                "n_articles": sum(c["n_articles"] for c in entry["completed_chunks"]),
                "earliest_to_date": entry["earliest_to_date_reached"],
                "api_calls": 0}

    api_calls    = 0
    chunks_added = 0
    today        = datetime.date.today()

    while len(entry["completed_chunks"]) < max_chunks:
        to_date = _next_to_date(entry, today)

        # Skip if the file is already on disk for this to_date and the
        # manifest already lists it (reconcile() handled the orphan/missing
        # cases up front)
        already_done = any(c["to_date"] == to_date.strftime("%Y-%m-%d")
                           for c in entry["completed_chunks"])
        if already_done:
            print(f"[backfill] {ticker} to={to_date}: skip (already in manifest)")
            # Walk past this date
            entry["earliest_to_date_reached"] = to_date.strftime("%Y-%m-%d")
            continue

        try:
            df = _fetch_with_retry(ticker, to_date)
        except BackfillFetchError as e:
            print(f"[backfill] {ticker} to={to_date}: exhausted retries "
                  f"({e}).  Marking ticker in_progress; next session retries.")
            entry["status"] = "in_progress"
            save_manifest(manifest)
            break

        api_calls += 1

        if df.empty:
            # Empty result.  Distinguish depth ceiling from auth/zero-news
            # first-chunk case.  Per spike v3, a real ceiling shows up as
            # "non-empty chunks then an empty chunk" -- so require >= 2
            # prior successful chunks.
            if len(entry["completed_chunks"]) >= 2:
                print(f"[backfill] {ticker} to={to_date}: empty response "
                      f"after {len(entry['completed_chunks'])} successful "
                      f"chunks -- depth ceiling reached.")
                entry["status"] = "depth_ceiling"
            else:
                print(f"[backfill] {ticker} to={to_date}: empty response "
                      f"on chunk #{len(entry['completed_chunks'])+1}.  "
                      f"Likely auth or zero-news ticker, NOT depth ceiling.  "
                      f"Marking in_progress for operator review.")
                entry["status"] = "in_progress"
            save_manifest(manifest)
            break

        # Non-empty success: chunk CSV was written by fetch_news_chunk
        from_date = to_date - datetime.timedelta(days=DAYS_PER_CHUNK)
        entry["completed_chunks"].append({
            "to_date":      to_date.strftime("%Y-%m-%d"),
            "from_date":    from_date.strftime("%Y-%m-%d"),
            "n_articles":   int(len(df)),
            "completed_at": _now_iso(),
        })
        # Update earliest if this is a step backwards
        prev = entry["earliest_to_date_reached"]
        ts   = to_date.strftime("%Y-%m-%d")
        if prev is None or ts < prev:
            entry["earliest_to_date_reached"] = ts
        chunks_added += 1
        save_manifest(manifest)
        print(f"[backfill] {ticker} to={to_date}: ok, n_articles={len(df)} "
              f"(total chunks {len(entry['completed_chunks'])})")

        time.sleep(CHUNK_PACING_SECONDS)

    if len(entry["completed_chunks"]) >= max_chunks and entry["status"] == "in_progress":
        # Hit the hard cap before depth ceiling.  If max_chunks is the
        # default MAX_CHUNKS_PER_TICKER, mark complete; otherwise it's a
        # user-imposed test cap and we leave status as in_progress so the
        # next un-capped run can continue.
        if max_chunks >= MAX_CHUNKS_PER_TICKER:
            entry["status"] = "complete"
            save_manifest(manifest)
            print(f"[backfill] {ticker}: hit MAX_CHUNKS_PER_TICKER "
                  f"({MAX_CHUNKS_PER_TICKER}) before depth ceiling -- "
                  f"marking complete.")

    return {
        "ticker":           ticker,
        "status":           entry["status"],
        "chunks":           len(entry["completed_chunks"]),
        "n_articles":       sum(c["n_articles"] for c in entry["completed_chunks"]),
        "earliest_to_date": entry["earliest_to_date_reached"],
        "api_calls":        api_calls,
    }


# ---------------------------------------------------------------------------
# Dry-run plan
# ---------------------------------------------------------------------------

def print_dry_run(tickers: list, max_chunks: int) -> None:
    today = datetime.date.today()
    print(f"[backfill] DRY RUN -- planning only, no API calls.")
    print(f"[backfill] today={today}, max_chunks={max_chunks}, "
          f"days_per_chunk={DAYS_PER_CHUNK}, step={DAYS_PER_CHUNK-1}d")
    total_calls = 0
    for t in tickers:
        oldest_to = today - datetime.timedelta(days=(max_chunks - 1) * (DAYS_PER_CHUNK - 1))
        oldest_from = oldest_to - datetime.timedelta(days=DAYS_PER_CHUNK)
        total_calls += max_chunks
        print(f"  {t}: planned {max_chunks} chunks -- "
              f"first to={today}, last to={oldest_to}, "
              f"oldest from={oldest_from}")
    est_seconds = (total_calls * CHUNK_PACING_SECONDS
                   + len(tickers) * TICKER_PACING_SECONDS)
    print(f"[backfill] total planned API calls: {total_calls} "
          f"(~{est_seconds/60:.1f} min wall clock at current pacing)")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(stats_rows: list, elapsed: float, total_api_calls: int) -> None:
    print()
    print("=" * 72)
    print("  BACKFILL SUMMARY")
    print("=" * 72)
    print(f"  {'ticker':<6}  {'status':<14}  {'chunks':>6}  "
          f"{'articles':>9}  earliest_to_date")
    in_progress: list = []
    for r in stats_rows:
        earliest = r["earliest_to_date"] or "n/a"
        print(f"  {r['ticker']:<6}  {r['status']:<14}  {r['chunks']:>6d}  "
              f"{r['n_articles']:>9d}  {earliest}")
        if r["status"] == "in_progress":
            in_progress.append(r["ticker"])
    print()
    print(f"  Total API calls this run : {total_api_calls}")
    print(f"  Wall clock               : {elapsed:.1f}s ({elapsed/60:.1f} min)")
    if in_progress:
        print()
        print(f"  TICKERS NEEDING RE-RUN (status=in_progress): "
              f"{', '.join(in_progress)}")
    print("=" * 72)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Chunked Finnhub historical news backfill (raw, unscored).",
    )
    ap.add_argument("--ticker",     type=str, default=None,
                    help="Restrict to a single ticker (default: all in config.TICKERS).")
    ap.add_argument("--max-chunks", type=int, default=MAX_CHUNKS_PER_TICKER,
                    help=f"Cap chunks per ticker (default {MAX_CHUNKS_PER_TICKER}).")
    ap.add_argument("--dry-run",    action="store_true",
                    help="Print the planned schedule without making API calls.")
    ap.add_argument("--reset",      action="store_true",
                    help="Ignore any existing manifest and start fresh.")
    args = ap.parse_args()

    tickers = [args.ticker] if args.ticker else list(config.TICKERS)
    for t in tickers:
        if t not in config.TICKERS:
            print(f"[backfill] WARNING: {t} is not in config.TICKERS "
                  f"(continuing anyway)")

    if args.dry_run:
        print_dry_run(tickers, args.max_chunks)
        return

    manifest = load_manifest(reset=args.reset)

    t0 = time.monotonic()
    stats_rows: list = []
    total_api_calls = 0
    for i, ticker in enumerate(tickers):
        print()
        print(f"--- {ticker} ({i+1}/{len(tickers)}) ---")
        stats = run_ticker(manifest, ticker, max_chunks=args.max_chunks)
        stats_rows.append(stats)
        total_api_calls += stats["api_calls"]
        if i < len(tickers) - 1:
            time.sleep(TICKER_PACING_SECONDS)
    elapsed = time.monotonic() - t0

    print_summary(stats_rows, elapsed, total_api_calls)


if __name__ == "__main__":
    main()

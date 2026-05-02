# SEC Phase 1 Backfill Report — 2026-05-01

_Bumped `config.DATA_PARAMS["sec_lookback_years"]` from **3 → 10** for the
6 single-name tickers in the universe (AAPL, NVDA, JPM, XOM, UNH, WMT).
ETF tickers (SPY, IWM, GLD, TLT) are excluded by the existing
`ETF_TICKERS` short-circuit in the SEC fetcher.  No fetcher, scorer,
merger, aggregator, or engine code was modified — all depth changes
flow from the single-line config edit.  Downstream consumers ingest
the deepened history without modification (smoke-tested on NVDA,
§5)._

## 1. Pre-backfill state (captured BEFORE config edit)

| ticker | n_filings_pre | earliest_date_pre | latest_date_pre | by_subcategory_pre |
|---|---:|---|---|---|
| AAPL | 76 | 2020-04-30 | 2026-04-20 | 8-K_other 28, 8-K_earnings_prepared 24, 10-Q_mdna 18, 10-K_mdna 6 |
| NVDA | 39 | 2023-05-24 | 2026-03-06 | 8-K_other 15, 8-K_earnings_prepared 12, 10-Q_mdna 9, 10-K_mdna 3 |
| JPM  | 20 | 2025-05-01 | 2026-04-24 | 8-K_other 10, 8-K_earnings_prepared 6, 10-Q_mdna 3, 10-K_mdna 1 |
| XOM  | 59 | 2023-04-28 | 2026-04-08 | 8-K_earnings_prepared 26, 8-K_other 19, 10-Q_mdna 9, 10-K_mdna 3, 8-K_earnings_cover 2 |
| UNH  | 61 | 2023-04-28 | 2026-04-21 | 8-K_other 32, 8-K_earnings_prepared 13, 10-Q_mdna 9, 8-K_earnings_cover 4, 10-K_mdna 3 |
| WMT  | 49 | 2023-05-18 | 2026-03-27 | 8-K_other 26, 8-K_earnings_prepared 11, 10-Q_mdna 9, 10-K_mdna 3 |

Cross-check: raw `.txt` file counts in `data/raw/sec/{TICKER}/` were
102 / 51 / 26 / 88 / 81 / 67 respectively — higher than scored row
counts because the scorer skips cover-only 8-Ks where the exhibit is
already scored separately.

## 2. Backfill execution log

**Config edit** ([config.py:92](../config.py#L92)): single-line change,
`sec_lookback_years` 3 → 10.  Verified by `git diff` showing one line
modified.

**Fetcher run** (`data/sec_fetcher.fetch_all_filings(ticker, years_back=10)`,
sequential, EDGAR's 10 req/s throttle preserved by the existing module):

| ticker | filings_returned | elapsed | errors |
|---|---:|---:|---|
| AAPL | 131 | 78.2 s | none |
| NVDA |  85 | 51.0 s | none |
| JPM  |  27 | 10.0 s | none — but `recent`-block clipped (see §6) |
| XOM  | 130 | 97.7 s | none |
| UNH  | 112 | 70.9 s | none |
| WMT  |  59 | 23.6 s | none |

No HTTP retries triggered.  No 429 rate-limit responses.  No
User-Agent issues.  Total fetcher elapsed: ~5 min 32 s including the
ticker→CIK map load on the first ticker.

**Scorer run** (`sentiment.sec_scorer.score_all_filings(ticker, save=True)`,
sequential, idempotent filename-based dedup):

| ticker | already-scored skipped | newly-scored | rows_added | elapsed |
|---|---:|---:|---:|---:|
| AAPL | 76  | 55 | +55 | 302.2 s |
| NVDA | 39  | 46 | +46 |  87.8 s |
| JPM  | 20  |  1 | + 1 |  92.6 s |
| XOM  | 59  | 67 | +67 | 302.6 s |
| UNH  | 61  | 51 | +51 |  76.9 s |
| WMT  | 49  |  8 | + 8 |  51.8 s |

Skipped counts confirm dedup worked — no filing was re-scored.  Total
scoring elapsed: ~15 min 34 s.

## 3. Post-backfill state

| ticker | n_filings_post | earliest_date_post | latest_date_post | by_subcategory_post |
|---|---:|---|---|---|
| AAPL | 131 | 2016-06-22 | 2026-05-01 | 8-K_other 49, 8-K_earnings_prepared 41, 10-Q_mdna 30, 10-K_mdna 10, 8-K_earnings_cover 1 |
| NVDA |  85 | 2020-03-10 | 2026-04-27 | 8-K_other 35, 8-K_earnings_prepared 26, 10-Q_mdna 18, 10-K_mdna 6 |
| JPM  |  21 | 2025-05-01 | 2026-05-01 | 8-K_other 10, 8-K_earnings_prepared 6, 10-Q_mdna 4, 10-K_mdna 1 |
| XOM  | 126 | 2019-12-02 | 2026-05-01 | 8-K_earnings_prepared 54, 8-K_other 44, 10-Q_mdna 18, 10-K_mdna 7, 8-K_earnings_cover 3 |
| UNH  | 112 | 2020-10-14 | 2026-04-21 | 8-K_other 62, 8-K_earnings_prepared 24, 10-Q_mdna 16, 10-K_mdna 6, 8-K_earnings_cover 4 |
| WMT  |  57 | 2023-02-21 | 2026-04-30 | 8-K_other 32, 8-K_earnings_prepared 12, 10-Q_mdna 9, 10-K_mdna 4 |

Note: `latest_date_post` advances past `latest_date_pre` for several
tickers.  Reason: the fetch picked up brand-new filings (e.g. WMT
8-K 2026-04-30) that landed between the pre-snapshot and the
post-snapshot — not from the depth backfill.

## 4. Diff table

| ticker | filings_added | new_earliest | years_gained | regime_coverage |
|---|---:|---|---:|---|
| AAPL | +55 | 2016-06-22 | ~3.9y | **mixed** (2018-VolReturns: 10 new filings, 2020-COVID: 2 new filings) |
| NVDA | +46 | 2020-03-10 | ~3.2y | **mixed** (2020-COVID: 14, 2022-Inflation: 14) |
| JPM  | + 1 | 2025-05-01 | 0y    | **none-added** — recent-block cap (see §6) |
| XOM  | +67 | 2019-12-02 | ~3.4y | **mixed** (2020-COVID: 19, 2022-Inflation: 21) |
| UNH  | +51 | 2020-10-14 | ~2.5y | **mixed** (2020-COVID: 6, 2022-Inflation: 21) |
| WMT  | + 8 | 2023-02-21 | ~0.2y | **post-2023-only** (no filings from {2018, 2020, 2022} regime windows; 7 new filings all in Feb–May 2023) |

The regime-coverage column counts only filings strictly older than
each ticker's `earliest_date_pre`; new filings inside the existing
window (e.g. JPM's single 2026-05-01 entry, WMT's 8th row at
2026-04-30) are excluded from the regime tally to keep "regime gained"
distinct from "rolled forward."

**Read.** AAPL gained 4 years (2016-2020) including a meaningful 2018
sample — useful for any future "did the model handle the late-cycle
volatility return" question.  NVDA / XOM / UNH each gained ~3 years
spanning both the COVID and 2022 inflation regimes — these three are
the highest-leverage adds for OOS testing because the new history
covers structurally different macro regimes than the existing 2023+
window.  WMT's small add reflects EDGAR returning only ~10 additional
raw files for WMT in the deeper window (WMT files fewer 8-Ks than
peers; the `recent` block returned what it had).  JPM unchanged at
2025-05 and is the canonical example of the recent-block cap problem.

## 5. Smoke test (NVDA downstream consumption)

Confirmed:

- `pandas.read_csv('data/raw/sec_sentiment_NVDA.csv')` returns 85 rows
  with the same 13-column schema as before
  (`ticker, filing_date, filing_type, subcategory, sentiment_score,
  chunk_count, bullish_pct, bearish_pct, neutral_pct,
  most_bearish_chunk, most_bullish_chunk, total_tokens, source_path`).
  Dtypes unchanged.
- `sentiment.merger.load_sec_sentiment("NVDA")` returns the same
  shape `(85, 13)` and `filing_date` range now spans **2020-03-10 to
  2026-04-27** (was 2023-05-24 to 2026-03-06 pre-backfill — explicit
  acceptance criterion `min(date) < 2023-05-24` met).
- `sentiment.merger.build_combined("NVDA", save=False)` produces the
  full 3-stream weighted blend with shape `(1605, 24)` covering
  **2020-03-10 to 2026-05-01**.  No errors.  All 24 expected output
  columns present
  (`date, ticker, news_sentiment, news_headline_count, bullish_pct,
  bearish_pct, neutral_pct, sec_earnings_sentiment,
  sec_earnings_filing_date, sec_other_sentiment, sec_other_filing_type,
  sec_other_filing_date, sec_earnings_age_days, sec_other_age_days,
  sec_sentiment, sec_filing_type, sec_filing_date, sec_age_days,
  combined_sentiment, news_available, sec_earnings_available,
  sec_other_available, sec_available, sec_stale`).
- `r3_baseline.py` and `audit_walkforward.py` were **not** run, per
  the spec — those scripts use `today()`-anchored synthetic sentiment
  and would not exercise the new SEC depth.

The merger / engine path is ready to consume the deeper history;
no plumbing changes required downstream.

## 6. Known limitations preserved (Phase 2 scope)

This session deliberately did NOT address:

- **JPM `recent`-block ~1000-entry cap.**  JPM is a high-volume filer
  (lots of 8-Ks); EDGAR's submissions API `recent` block tops out
  around 1000 entries, and the fetcher only reads `recent` (not the
  `files` chain to older submission archives).  Result: even with
  `years_back=10`, JPM's earliest filing in the post state is still
  **2025-05-01** — exactly one year of history, unchanged from the
  pre state in earliest-date terms (the +1 row was the 2026-05-01
  10-Q filed today).  Already documented in PROJECT_STATE §10.3.
  Phase 2 work: walk the `files` chain to recover JPM's 2016-2025
  history.

- **AAPL pre-2022 iXBRL stub-extraction.**  The five AAPL 10-Q
  filings dated 2020-05-01, 2020-07-31, 2021-01-28, 2021-04-29 and
  2021-07-28 are known to encode narrative content inside
  `ix:nonNumeric` XBRL tags that don't surface through
  `BeautifulSoup.get_text()`, producing ~500-byte boilerplate stubs.
  The 2018-2020 backfill (53 new AAPL filings) likely hits more
  filings of this iXBRL-affected era — a sample inspection of the
  new AAPL row scores is recommended in a follow-up before relying
  on AAPL deep-history sentiment for OOS testing.  Phase 2 work:
  iXBRL-aware extraction (parse `ix:nonNumeric`, `R*.htm`,
  `FilingSummary.xml`).  Already documented in PROJECT_STATE §10.3.

- **Item 1A Risk Factors not extracted.**  The fetcher targets Item 7
  (MD&A) for 10-K/Q and the full body for 8-K only.  Item 1A risk
  factors — the most defensible "narrative shift" signal in the
  filings — are not extracted or scored anywhere.  Phase 2 candidate.

These three are flagged for a future Phase 2 session.  None block
the immediate value of the depth backfill (NVDA/XOM/UNH/AAPL all
gained 3-4 years of macro-regime coverage and are ready for OOS
testing on real-data corpus once 30-60 days of accumulated live
news joins them in the merger output).

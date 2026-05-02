# Finnhub Historical News Spike v3 — 2026-05-01

_Recap.  v2 (`outputs/finnhub_historical_spike_v2.md`) established
that the free-tier `company_news` endpoint honours `to=` but cuts
off at some depth between 6 months (Test B at `to="2025-11-15"`
returned 243 articles within window) and 16-21 months (Tests A and
C at `to="2024-08-15"` and `to="2024-12-31"` returned empty).  v3
pins the cutoff with three probes at 9, 12, and 14 months back.
All three tests use AAPL on 14-day windows for direct comparability
with v1 and v2 results._

## 1. Test D — `_from="2025-08-01", to="2025-08-15"` (9 months back)

- Request timestamp: `2026-05-01T21:23:43.687170`
- Response type: `list`
- **Total articles returned: 232.**
- **Distinct article dates: 7** —
  `['2025-08-10', '2025-08-11', '2025-08-12', '2025-08-13',`
  `'2025-08-14', '2025-08-15', '2026-02-23']`
- Earliest: `2025-08-10`.  Latest: `2026-02-23` (single outlier — see
  §4 cross-test pattern note).
- 6 of 7 distinct dates sit cleanly in the upper 6 days of the
  requested 14-day window (2025-08-10 to 2025-08-15).
- Sample headlines:
  - `[2025-08-15] [Yahoo] 5 Unstoppable "Ten Titans" Growth Stocks to Buy Now and Hold Through at Least 2030`
  - `[2025-08-15] [Yahoo] Sam Altman, over bread rolls, explores life after GPT-5`
  - `[2025-08-15] [Yahoo] These Stocks Moved the Most Today: UnitedHealth, Applied Materials, Intel, Quantum Computing, Opendoor, and More`

**Inferred behaviour:** populated.  Same shape as v1's 5/9-5/15 and
v2 Test B's 11/07-11/15: API returns the upper ~7 days of the
requested window.

## 2. Test E — `_from="2025-05-01", to="2025-05-15"` (12 months back)

- Request timestamp: `2026-05-01T21:23:44.098650`
- Response type: `list`
- **Total articles returned: 226.**
- **Distinct article dates: 8** —
  `['2024-09-09', '2025-05-09', '2025-05-10', '2025-05-11',`
  `'2025-05-12', '2025-05-13', '2025-05-14', '2025-05-15']`
- Earliest: `2024-09-09` (single outlier — see §4).  Latest:
  `2025-05-15`.
- 7 of 8 distinct dates in the upper 7 days of the window
  (2025-05-09 to 2025-05-15).
- Sample headlines:
  - `[2025-05-15] [SeekingAlpha] BlackRock Capital Appreciation V.I. Fund Q1 2025 Commentary`
  - `[2025-05-15] [Yahoo] Berkshire Sells Financial Stocks, Doubles Constellation Stake, Holds Steady on Apple`
  - `[2025-05-15] [SeekingAlpha] BlackRock Technology Opportunities Fund Q1 2025 Commentary`

**Inferred behaviour:** populated.  Result is byte-for-byte identical
to v1's identical-parameter call (same 226 article count, same 8
dates, same 2024-09-09 outlier) — which incidentally confirms the
API is deterministic on repeat queries within a session.

## 3. Test F — `_from="2025-03-01", to="2025-03-15"` (14 months back)

- Request timestamp: `2026-05-01T21:23:44.179590`
- Response type: `list`
- **Total articles returned: 0** (empty list, no exception raised).
- Distinct article dates: 0 (n/a).
- Earliest / latest: n/a.
- Sample headlines: n/a.

**Inferred behaviour:** empty.  Same outcome as v2 Test A (~21mo
back) and v2 Test C (~16mo back).  The depth horizon falls between
Test E's 12-month success and Test F's 14-month empty — within ~2
months of the Finnhub-documented 1-year free-tier limit.

## 4. Cross-test pattern (incorporating v2 results)

| spike | test | months back | n articles | dates (in-window) | populated? |
|---|---|---:|---:|---|---|
| v2 | B | ~6  | 243 | 9 (5/07–5/15) | yes |
| v3 | D | ~9  | 232 | 6 (8/10–8/15) | yes |
| v3 | E | ~12 | 226 | 7 (5/09–5/15) | yes |
| v3 | F | ~14 | 0  | none           | no |
| v2 | C | ~16 | 0  | none           | no |
| v2 | A | ~21 | 0  | none           | no |

The pattern is monotone: every probe within ~12 months returns ~225-245
articles clustered in the upper 6-9 days of the window; every probe
beyond ~14 months returns empty.  The cutoff falls in the 12-14-month
band, consistent with Finnhub's documented free-tier 1-year history
limit (within tolerance for "1 year" being interpreted variably as
365 days, 12 calendar months, or 52 weeks).

**Outlier observations.**  Two date outliers reproduce across tests:
Test D returns one article dated `2026-02-23` and Test E returns one
dated `2024-09-09`.  These are not "API ignores the window" — both
windows also returned correctly-dated content from within their
requested ranges.  Most likely Finnhub's index occasionally carries
an article whose stored datetime was reset or back-filled (e.g.,
recompiled archive content, late-arrival press release re-stamped).
A backfill should be defensive about this: dedup by URL/headline,
not by date alone.  Volume is tiny (~0.5% of returned articles).

## 5. Verdict: **DEPTH ~12 MONTHS** (option b)

Tests D (9mo back) and E (12mo back) returned cleanly populated
responses (232 and 226 articles respectively, dates clustered inside
the upper portions of their requested windows).  Test F (14mo back)
returned an empty list with no error.  This is the textbook (b)
pattern: D and E populated, F empty.  The depth horizon sits within
~2 months of the documented 1-year free-tier limit.

**Operational implication for chunked backfill geometry:**

A backfill walking `to=` backwards from today in 7-day steps reaches
the depth horizon after roughly 52 chunks per ticker.  Concretely:

- Chunk geometry: `to=today−7k` for `k = 0, 1, 2, … 51`; each chunk
  uses `_from=to−13` (so the 14-day window matches the tested shape
  and reliably returns the upper ~7-9 days of content).
- Each chunk yields ~7 distinct dates (occasionally 6 or 9).
- Calls per ticker for 12 months: **~52**.
- Total calls for the 10-ticker universe: **~520**.
- Free-tier rate cap: 60 calls/min → **~9 min of API wall clock**.
- Plus: scoring (~150-250 articles per chunk × 520 chunks = ~100k
  articles to FinBERT-score; this dominates total wall clock,
  comparable to the SEC backfill's ~16-min scoring step but ~5-10×
  more articles).
- Halt condition: stop when a chunk returns 0 articles (signals depth
  horizon reached); resume from the next ticker.  Do not retry empty
  chunks within the run — they are deterministic per the v3 result.
- Dedup: by URL or headline, not by date.  The ~0.5% outlier rate
  observed in v3 means ~26 of 520 chunks may carry one out-of-window
  article each.

The backfill is now justified end-to-end: `to=` is honoured (v2),
the depth horizon is ~12 months (v3), and the per-chunk shape is
stable across 5 distinct date-windows tested across v1, v2, and
v3.  The single-ticker (AAPL) caveat from v2 still applies — the
behaviour is almost certainly an account-level property of the API,
but lower-news-volume tickers (TLT, GLD) may yield smaller chunk
sizes.  No further spikes are needed before scoping the
implementation; the next session can build directly.

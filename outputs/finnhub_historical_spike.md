# Finnhub Historical News Spike — 2026-05-01

_Single verification call to determine whether Finnhub's free-tier
`company_news` endpoint actually serves more than the most-recent ~2
days observed during the 2026-05-01 reconnaissance.  No data persisted
to disk under `data/raw/` — this is verification only._

## 1. Test call details

```python
import finnhub
from config import FINNHUB_API_KEY
client = finnhub.Client(api_key=FINNHUB_API_KEY)
resp = client.company_news(symbol="AAPL", _from="2025-05-01", to="2025-05-15")
```

- **Endpoint:** Finnhub `/api/v1/company-news` (per the official
  `finnhub-python` SDK; the underlying URL is not exposed by the
  client object).
- **Symbol:** `AAPL` (chosen for high news volume).
- **Window requested:** 14 calendar days, **2025-05-01 to 2025-05-15**
  (~12 months before today, the spike target).
- **Response timestamp:** `2026-05-01T21:06:54.199540` (local time).
- **HTTP status:** implicit 200 (no exception raised; the SDK raises on
  non-2xx).

## 2. Result inventory

- **Total articles returned:** **226**.
- **Distinct article dates returned:** **8**.
- **Earliest article date:** `2024-09-09` (one outlier — see §3).
- **Latest article date:** `2025-05-15`.
- **All 8 distinct dates:**
  `['2024-09-09', '2025-05-09', '2025-05-10', '2025-05-11',`
  `'2025-05-12', '2025-05-13', '2025-05-14', '2025-05-15']`
- **Sample headlines:**
  - `[2025-05-15] [SeekingAlpha] BlackRock Capital Appreciation V.I. Fund Q1 2025 Commentary`
  - `[2025-05-15] [Yahoo] Berkshire Sells Financial Stocks, Doubles Constellation Stake, Holds Steady on Apple`
  - `[2025-05-15] [SeekingAlpha] BlackRock Technology Opportunities Fund Q1 2025 Commentary`

## 3. Diagnostic observations

The response shape is the load-bearing signal here, not just the row
count:

- **The 14-day requested window 2025-05-01 to 2025-05-15 is HALF empty.**
  Articles cluster in **2025-05-09 through 2025-05-15** (7 consecutive
  days).  No articles were returned for 2025-05-01 through 2025-05-08 —
  the lower half of the requested window.
- **The 2024-09-09 outlier** (1 article, 8 months before the requested
  window's lower bound) is more likely a metadata artifact (article
  re-indexed or timestamp-shifted in Finnhub's backend) than a sign that
  the API serves arbitrary history; it doesn't establish a backfill
  path.
- **Pattern matches the 2026-05-01 reconnaissance.**  That earlier
  test (no separate report — captured during data-layer recon) showed
  a 30-day request returning only the last ~2 days.  This spike's
  pattern — 14-day request returning the last ~7 days — is consistent
  with the hypothesis that the **free-tier `company_news` endpoint
  silently truncates the lower bound to roughly 7 days before
  whichever is earlier of `to=` or "now"**.  The previous "2 days"
  observation likely reflected `to=today` requests where the trailing
  days had no published content yet.

## 4. Verdict: **PARTIAL**

**The free-tier API returns articles, but only from the most recent
~7 calendar days of any requested window — not the full window
requested.**  The 14-day window 2025-05-01 to 2025-05-15 returned 226
articles spanning only 2025-05-09 to 2025-05-15 (the upper 7 days);
the first 8 days of the window were empty.

**Why not WORKS:** the spec's WORKS criterion is "≥7 distinct dates
with content" within the requested window.  Strictly read, we have 7
distinct in-window dates (5/9 through 5/15) — at the threshold.  But
the *shape* of the response is exactly what PARTIAL is meant to
capture: the API returns only the most-recent N days (here N=7) and
silently drops anything earlier than that, regardless of `_from`.
A WORKS verdict would imply you could `_from="2024-05-01", to="2025-05-01"`
and get a full year of articles in one call; this spike is direct
evidence you cannot.

**Why not BLOCKED:** content for the recent 7-day strip *is* returned
(226 articles, 7 dates, real content), so the API is responsive and
the key has access — it's just window-truncated.

**Quoted evidence (from §2):** _"Distinct article dates returned: 8 …
all 8 distinct dates: ['2024-09-09', '2025-05-09', '2025-05-10',
'2025-05-11', '2025-05-12', '2025-05-13', '2025-05-14', '2025-05-15']."_
The 7 in-window dates are the upper half of the requested 14-day
range; the lower half (2025-05-01 through 2025-05-08) returned zero
articles despite being inside the requested range.

**Implications for any future Finnhub backfill (out of scope this
session):**

- A one-shot 1-year backfill (`_from="2025-05-01", to="2026-05-01"`)
  will not work — it will return only the last ~7 days.
- A chunked backfill (52 weekly windows, sliding `to=` backward by 7
  days each iteration) is the only viable path on the free tier.
  Cost: ~52 API calls per ticker × 10 tickers = 520 calls.  At
  Finnhub free tier's stated 30 calls/min, this is ~17 min wall clock
  + dedup/scoring overhead.  Feasible but non-trivial — not a
  one-shot backfill.
- Each weekly chunk would need to anchor `to=` at the chunk midpoint
  rather than at "now", and the API's behaviour with `to=` set in
  the past is itself unverified.  A second spike (`_from="2025-04-24",
  to="2025-05-01"`) would test whether shifting `to=` into the past
  unlocks earlier history or whether the API anchors to "now"
  regardless.  **That second spike is recommended before scoping any
  backfill implementation.**

The decision to build a Finnhub historical backfill is now informed:
**possible but expensive** (chunked, paginated, ~520 calls across 10
tickers, with one residual unverified assumption about `to=` past-anchoring).
Compare against the SEC Phase 1 backfill (this session, 1 config edit
+ 21 minutes wall clock, deepened 5 of 6 single-name tickers by 2.5–4
years across 2018-VolReturns / 2020-COVID / 2022-Inflation regimes)
and the relative leverage is clear: SEC was the right first move.

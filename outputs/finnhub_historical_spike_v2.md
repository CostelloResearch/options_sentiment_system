# Finnhub Historical News Spike v2 — 2026-05-01

_Recap.  Spike v1 (2026-05-01, see `outputs/finnhub_historical_spike.md`)
called `client.company_news("AAPL", _from="2025-05-01", to="2025-05-15")`
and got 226 articles dated 2025-05-09 to 2025-05-15 — the upper 7 days
of the requested 14-day window.  That result was ambiguous between
two distinct API behaviours: (i) "API honoured `to=2025-05-15`,
truncated the lower bound to 7 days before `to=`", and (ii) "API
ignored `to=` entirely, snapped to today, returned the past 7 days
from now."  Both produce the same 5/9-5/15 dates because 5/15 was
also roughly "now minus 12 months" — but only one is consistent with
chunked backfill being feasible.  v2 disambiguates by setting `to=`
clearly in the past with no overlap to any plausible "now minus N
days" window._

## 1. Test A — `_from="2024-08-01", to="2024-08-15"`

Window: 14 calendar days, ~21 months before today.  (The original
spec described this as "9 months in the past"; the actual parameters
are deeper.  I executed the parameters as specified and report the
literal result.)

- Request timestamp: `2026-05-01T21:19:27.133133`
- Response type: `list`
- **Total articles returned: 0** (empty list, no exception raised).
- Distinct article dates: 0 (n/a).
- Earliest / latest: n/a.
- Sample headlines: n/a (none returned).

**Inferred behaviour:** the API did not snap `to=` to today.  If it
had, we would have received articles dated late April / early May
2026 (the past-7-days-from-now strip).  Instead the response was
literally empty, which means `to=` *was* respected — but the
requested window is past the free-tier depth horizon and there is
nothing to return.

## 2. Test B — `_from="2025-11-01", to="2025-11-15"`

Window: 14 calendar days, ~6 months before today.

- Request timestamp: `2026-05-01T21:19:27.515596`
- Response type: `list`
- **Total articles returned: 243.**
- **Distinct article dates: 9** —
  `['2025-11-07', '2025-11-08', '2025-11-09', '2025-11-10',`
  `'2025-11-11', '2025-11-12', '2025-11-13', '2025-11-14',`
  `'2025-11-15']`
- Earliest: `2025-11-07`.  Latest: `2025-11-15`.
- Sample headlines (verbatim, dated within the requested window — not
  near today):
  - `[2025-11-15] [Yahoo] Apple Just Hit a $4 Trillion Milestone: Do Experts Think It's Time To Buy?`
  - `[2025-11-15] [Yahoo] Former Fed governor's stock trades violated the central bank's ethics rules`
  - `[2025-11-15] [Yahoo] Warren Buffett's Berkshire snaps up major tech stock, trims favorite`

**Inferred behaviour:** **`to=` was unambiguously honoured.**  Article
dates cluster in the upper 9 days of the requested 14-day window
(2025-11-07 through 2025-11-15), exactly the same shape as v1's
2025-05-09 → 2025-05-15 result.  The API returns roughly the
last 7-9 days preceding `to=`, not the last 7-9 days preceding "now".
The absence of any 2026-04 / 2026-05 articles in this response is
the conclusive disambiguation v1 lacked.

## 3. Test C — `_from="2024-12-01", to="2024-12-31"`

Window: 30 calendar days, ~16 months before today.  (The original
spec described this as "5 months in the past"; same parameter
deeper-than-labelled situation as Test A.)  This test was designed
to probe whether the 7-day truncation behaviour scales with the
requested window width.

- Request timestamp: `2026-05-01T21:19:27.779462`
- Response type: `list`
- **Total articles returned: 0** (empty list, no exception raised).
- Distinct article dates: 0 (n/a).
- Earliest / latest: n/a.
- Sample headlines: n/a.

**Inferred behaviour about window width:** unanswered, because the
30-day window also returned empty — same outcome as Test A's 14-day
window, just with a different lower bound.  The empty response is
consistent with Test A's depth-horizon hypothesis: at ~16 months
back the requested window is past the free tier's 1-year history
limit, and the wider 30-day request did not extend reach beyond it.

The truncation-vs-window-width question therefore needs a different
test geometry to answer (e.g., a single 30-day window inside the
known-working ~12-month region).  Spec was explicit that no
exploratory probes beyond the three specified are permitted, so I
did not run that.

## 4. Cross-test pattern

| test | `_from` | `to` | months before today | n articles | dates returned |
|---|---|---|---:|---:|---|
| A | 2024-08-01 | 2024-08-15 | ~21 | 0  | none |
| B | 2025-11-01 | 2025-11-15 | ~6  | 243 | 2025-11-07 to 2025-11-15 (9 dates, upper window) |
| C | 2024-12-01 | 2024-12-31 | ~16 | 0  | none |

The pattern is clean: **Finnhub free tier honours `to=` and returns
the upper ~7-9 days of the requested window, but only for windows
inside an empirically-bounded depth horizon — somewhere between 6
months (Test B works) and 16 months (Test C empty).**  Tests A and
C are not "API failed" or "API ignored my parameters"; they are
"API honoured my parameters, the requested data is past the free
tier's history limit, response is empty."  This is the externally
documented "1 year of history" free-tier limit behaving as
documented.

## 5. Verdict: **PARTIAL/AMBIGUOUS** (operationally: WORKS within ~12 months)

Per the spec's strict decision rule — "If Test A AND Test B both
return articles dated within or near their requested windows:
verdict WORKS" — Test A returned zero articles, so the WORKS
acceptance condition is not met.  The BLOCKED condition ("articles
returned are dated in the past 7 days of TODAY regardless of
requested `to=`") is also not met — Test B unambiguously returned
articles dated 2025-11-07 to 2025-11-15, six months before today.

**The verdict is PARTIAL/AMBIGUOUS by the strict letter, but the
operative finding is WORKS-with-depth-cap.**  The three tests
together establish:

1. **`to=` is honoured.**  Test B returned 243 articles dated within
   its requested window, none near today.  The v1 ambiguity is
   resolved.
2. **There is a depth horizon at roughly 12 months.**  Test B
   (~6 months back) returned content; Test A (~21 months) and Test C
   (~16 months) returned empty.  Bisecting between 6 and 16 months
   to find the exact cutoff is a follow-up if precise depth matters.
3. **The per-call shape is unchanged from v1.**  Test B returned 9
   distinct dates clustered in the upper 9 days of a 14-day window
   — same "API returns last ~7-9 days of the requested range"
   behaviour observed in v1.

**Implications for chunked backfill (within the depth horizon):**

- A chunked backfill walking `to=` backwards by ~7 days per chunk is
  feasible up to roughly 12 months back.
- Calls per ticker per year: 365 / 7 ≈ **52 calls**.
- Total calls for the 10-ticker universe at 1 year of history: **~520
  API calls**.
- Finnhub free-tier rate limit (per their published documentation):
  60 calls/min.  Wall clock: ~520 / 60 ≈ **9 minutes of API time**,
  plus FinBERT scoring of every returned article (the slow part —
  spike v1's 226 AAPL articles would scale to ~10× across the
  universe, requiring tens of minutes of GPU/CPU FinBERT inference,
  comparable to the SEC backfill scoring step).
- One residual unknown: the exact depth cutoff between 6 and 16
  months.  A backfill plan should account for the possibility that
  it sits at 12 months exactly (matching Finnhub's documented
  free-tier limit), in which case a 1-year backfill works fully but
  any chunk crossing the cutoff will return partial data.
- Caveat: results are AAPL-only.  Lower-volume tickers (TLT, GLD)
  may see fewer articles per chunk and tighter or wider effective
  depth limits.  Single-ticker spike risk acknowledged, but the
  `to=`-honoured / depth-horizon behaviour is almost certainly an
  account-level API property rather than a per-ticker artifact.

**Recommendation for the next session (out of scope here):** the
chunked-backfill build is justified.  A short pre-build probe should
narrow the depth cutoff (one call at `to="2025-05-15"` — 12 months
back exactly — would tell us whether the limit is at, above, or
below the documented 1-year mark) before committing to a particular
chunk geometry.

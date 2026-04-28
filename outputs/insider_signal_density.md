# Insider Signal Density Audit

_Generated 2026-04-28.  Data source: Finnhub `/stock/insider-transactions` (free tier).
Infrastructure: `data/insider_fetcher.py` + `scripts/backfill_insider_history.py`._

---

## Summary finding

The opportunistic-insider classifier (`is_opportunistic = True` iff SEC Form 4
code "P", net acquisition, non-derivative, cash price > 0) is working correctly.
The signal simply does not exist on mega-cap tech over the 2021-2026 window,
and is extremely sparse on the banking name most expected to produce it.
**Signal concentration is a universe problem, not a code problem.**

---

## Per-ticker results

### AAPL — smoke test (12-month window, 2025-04-28 to 2026-04-28)

| Metric | Value |
|---|---|
| Total transactions | 112 |
| P-coded (open-market buy) | 0 |
| is_opportunistic = True | 0 (0.0%) |
| Dominant codes | M=53 (option exercises), S=27 (sales), A=17 (RSU grants), F=12 (tax withholding), G=3 (gifts) |

**Interpretation:** Expected and correct.  Apple's executive compensation is
almost entirely RSU-based.  Executives receive shares as restricted-stock-unit
grants (A-coded), exercise options on vesting (M-coded), then sell on schedule
(S-coded).  No cash flows into the company from the insider side — open-market
purchases simply do not occur.  This is structurally true across the 2020-2026
period per API research conducted in the prior session.

---

### NVDA — 5-year backfill (2021-07-01 to 2026-03-20)

| Metric | Value |
|---|---|
| Total transactions | 2,000 (Finnhub free-tier row cap hit) |
| P-coded (open-market buy) | 0 |
| is_opportunistic = True | 0 (0.0%) |
| Dominant codes | S=1,605 (sales), A=118 (RSU grants), F=115 (tax withholding), G=88 (gifts), M=54 (option exercises), J=20 (other) |
| "BUY" direction count | 182 (all A/M/G-coded — awards, exercises, gifts, not cash purchases) |

**Note on row cap:** Finnhub's free-tier endpoint caps responses at 2,000 rows.
NVDA's 2,000-row cap is not a data-completeness concern for the signal question —
with 1,605 S-coded sells and 0 P-coded buys, extending the history further would
only add more of the same pattern.  Jensen Huang's large-scale share sales
(widely reported, via 10b5-1 plan) are correctly classified as S-coded routine
sales, not opportunistic.

**Interpretation:** Same structural conclusion as AAPL.  Semi-conductor
executive compensation is RSU-heavy.  The 182 "buy-direction" rows are
award/exercise/gift events, not cash open-market purchases.  Zero opportunistic
signal over 5 years.

---

### JPM — 5-year backfill (2021-05-06 to 2026-04-15)

| Metric | Value |
|---|---|
| Total transactions | 1,022 |
| P-coded (open-market buy) | 2 |
| is_opportunistic = True | 2 (0.2%) |
| Dominant codes | M=428 (option exercises), A=274 (RSU grants), S=144 (sales), F=128 (tax withholding), G=44 (gifts), J=2 (other), P=2 |

**The 2 opportunistic transactions:**

| Date | Filing | Insider | Shares | Price | Total Value |
|---|---|---|---|---|---|
| 2022-01-19 | 2022-01-20 | Mellody Hobson (Director) | 670 | $149.68 | $100,285 |
| 2023-01-19 | 2023-01-20 | Mellody Hobson (Director) | 375 | $134.53 | $50,448 |

**Interpretation:**  The classifier correctly identifies 2 P-coded open-market
purchases and 1,020 non-opportunistic rows.  The `is_opportunistic` field
produces both True and False — the code is working.

However, two caveats on the signal quality:

1. **Same-date annual pattern.**  Both transactions are filed on January 20
   (transaction date January 19) in consecutive years.  A recurring same-date
   annual purchase is a hallmark of a scheduled program.  Under Cohen-Malloy-
   Pomorski (2012)'s stricter "opportunistic" definition — a trade is
   informative only if the same insider did NOT make a similar trade in the
   prior 12 months — these two rows would be reclassified as routine.
   The current module uses the looser "open-market purchase" definition
   (documented in the LIMITATIONS section of `data/insider_fetcher.py`);
   implementing the CMP pattern-filter is a deferred enhancement.

2. **Jamie Dimon's 2019 open-market purchase** (~$26.6M, widely cited in
   the insider-signal literature as a textbook opportunistic buy) predates
   the 5-year window (2021-2026) and does not appear in this dataset.

**Annualized signal rate:** 0.4 opportunistic transactions per year on JPM.

---

## Cross-ticker signal density summary

| Ticker | Window | Total txns | Opp txns | Opp rate | Structural reason |
|---|---|---|---|---|---|
| AAPL | 12 months | 112 | 0 | 0.0% | RSU-based comp, no cash insider buys |
| NVDA | 5 years | 2,000 (capped) | 0 | 0.0% | RSU-based comp, Huang sells via 10b5-1 |
| JPM | 5 years | 1,022 | 2 | 0.2% | P-coded buys by one director; sparse |
| XOM | not run | — | — | — | Expected higher; energy sector historically more insider-buy-friendly |
| UNH | not run | — | — | — | Healthcare; mixed expectation |
| WMT | not run | — | — | — | Walton family context; likely awards/gifts dominate |

---

## Honest assessment for integration planning

**The insider infrastructure is complete and correct.**  The fetcher, classifier,
and backfill script all work as designed.  The AAPL-zero result, the NVDA-zero
result, and the JPM-two result are all sensible given fundamental knowledge of
each company's compensation structure and ownership dynamics.

**The signal does not support integration into the current 6-stock universe.**
Two opportunistic transactions over 5 years on JPM — combined with structural
zeros on AAPL and NVDA — means the 6-stock universe would produce roughly
1-3 opportunistic signals per year in aggregate (optimistic estimate including
XOM/UNH/WMT).  That is insufficient to build any backtest statistics.

**Where the signal would work:**  Academic studies and practitioner implementations
of the Cohen-Malloy-Pomorski signal use broad mid-cap and small-cap universes
(Russell 2000-class) where insider ownership concentration is higher, cash
open-market purchases are more common, and executives are more likely to buy
ahead of information that isn't already priced by Wall Street coverage.

**Recommended next step before integration:**
1. Run the full backfill across XOM, UNH, WMT to quantify the full universe
   signal density (est. 1 additional API call per ticker, <10s total).
2. If aggregate opportunistic rate across all 6 individual stocks is < 5
   transactions per year, treat insider as a flag/override for existing signals
   (e.g. "if is_opportunistic=True and existing signal is neutral, bump to BUY")
   rather than a standalone signal source.
3. The CMP pattern-filter (exclude recurring same-date buys) should be
   implemented before any production use, given the JPM result.

---

## Infrastructure status

| Component | Status |
|---|---|
| `data/insider_fetcher.py` | Complete.  Fetches, normalizes, classifies. |
| `scripts/backfill_insider_history.py` | Complete.  Multi-ticker, --dry-run, --years flags. |
| `.gitignore` entry `data/raw/insider_*.csv` | Added 2026-04-28. |
| Integration into `signals/` or `backtest/` | Deferred.  See PROJECT_STATE §1 honest-status note. |
| CMP pattern-filter (per-insider history scan) | Not implemented.  Deferred. |
| Insider role / officer vs director split | Not implemented.  Finnhub free tier does not expose role. |

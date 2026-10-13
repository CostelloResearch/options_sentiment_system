# Audit status -- options-sentiment-system (synthesis of stages 1, 2, 3, 4a, 4b)

Audit dates 2026-10-10..13. Read-only. Sources: `audit/01_inventory.md`, `02_data.md`, `03_signals.md`, `04a_backtest_mechanics.md`, `04b_backtest_analyses.md`, and `audit/artifacts/`. Stage 5 (tests) was skipped because the repo has no tests (D13). Section numbers below are written "01 s8", "4b s5" and so on. **Canonical** numbers come from 4b (reproduced logs + 4a snapshot); on-disk numbers are labelled **as reported**.

## 1. Executive summary

What actually runs in real mode is narrow:
- A **BUY CALLS** bull-call debit spread, entered when a ticker's daily news-FinBERT mean is above +0.25 and its 30-day realized-vol rank is below 0.30.
- Option prices are Black-Scholes at realized vol; there is no historical options data.
- The test window is one 12-month bull market (2025-05 to 2026-05) across 10 hand-picked tickers.

SEC sentiment, the 3-stream merger, the learned confidence model, quintile sizing, the earnings filter, the decay-study "disable", and the credit structures are all decision-inert or never fire (s2).

Every positive real-mode headline (R3 +$9,697, R3 with bypass +$13,906, walk-forward +$7,786) **reproduces only approximately**: canonical results move with the price-download date. **None survives costs.** With commissions and a symmetric 1.5%-per-leg exit cost, the walk-forward daily Sharpe falls from 2.63 [+0.11, +4.50] to 0.54 [-2.16, +2.70]. Pre-cost P&L is directional exposure to a rising market (correlation 0.85-0.91 with the underlying's move; no trade won when its underlying fell), and XOM + GLD carry 71-80% of it. Sentiment adds at most a marginal +0.6% over 9 days on the underlying, with CIs touching zero; the low-volatility filter adds nothing.

Separately, the live pipeline has been broken since 2026-05-04. It scores a stale backfill file and reads a frozen sentiment file (D1, D2-1, D2-2), and it emits labels only (D5). All synthetic/demo results are placebo runs. The engine itself is deterministic, and record/replay are bit-identical (4a s7).

## 2. What the system actually is

Real-mode backtest decision path (03 s1.2; 4a s1):
1. Daily adjusted yfinance closes; RV30; IV rank = RV30 position in its trailing 252-day min-max range (engine.py:401-414).
2. Daily sentiment = unweighted mean of article FinBERT scores (P(pos) - P(neg)) per ET calendar date, including after-close articles (D2-3), from `sentiment_{T}_real.csv` plus stray dated files (engine.py:419-436).
3. Quadrant rule, strict thresholds (03 s3). Only BUY CALLS and BUY PUTS ever produce accepted spreads.
4. BUY CALLS gives BULL_CALL_DEBIT, 35 DTE, long strike at about 0.55 delta, short = long + $5/$2.50 on a $5 grid, BS at RV30, 1.5% entry friction per leg (engine.py:229-373).
5. Floors: debit > 70% of width or width = 0 is rejected.
6. Kelly path: negative-Kelly filter blocks BUY PUTS (in-sample and out-of-sample), then uniform 0.38% x $100k, 1-contract minimum, 6% cap **per ticker** (position_sizer.py:526-625).
7. Daily BS mark at RV30; exit on stop -80% / target +50% of max profit / 21-DTE time stop; exits at fair value, no friction.

| component | what it actually does | ref |
|---|---|---|
| SEC sentiment (10-K/10-Q/8-K) | Live: displayed confidence only. Backtest: `sec_aligned` feature for the gated model only. | 03 s4 |
| 3-stream merger (0.50/0.35/0.15) | Computed; affects no decision | 03 s4, s14 |
| Learned logistic confidence | `load_model()` returns None; never runs | 03 s12 |
| Confidence (legacy / tiered) | Logged and displayed; never filters or sizes | 03 s12 |
| Quintile sizing, strategy buckets | Off by flags; artifacts unused | 03 s12, s14 |
| Earnings filter / IV_CRUSH | Live labels only; not in backtest; IV_CRUSH has no structure | 03 s8 |
| SELL PUTS / SELL CALLS | Never accepted in any log (credit floor); no Kelly row | 03 s9 |
| Decay study "DISABLE" | Writes a report no code reads | 03 s9 |
| `min_articles_required`, `iv_history_days` | Never read | 01 D11 |
| Live path | Labels only: no spreads, sizing, or exits | D5 |

## 3. Result ledger

Canonical = 4b reproduced logs (4b s5). Sharpe "repo" = sqrt(252/5) per row, all rows. Daily = exit-date daily series, sqrt(252), block-bootstrap 95% CI. After-cost = commissions $0.65 x 4 leg-sides x contracts plus 1.5% per leg exit friction (4b s1, s5b).

| reported result | source | canonical repo-method | daily pre-cost Sharpe [CI] | after-cost Sharpe [CI] | status |
|---|---|---|---|---|---|
| Flat real -$18,983 / -0.90 / 449 | PROJECT_STATE.md:686-691 | -$19,744 / -0.920 / 452 | -1.93 [-3.83, +0.29] | -2.94 [-4.80, -0.84] | DOES NOT SURVIVE (loss) |
| R3 HEAD +$9,697 / 1.17 / 295 | PROJECT_STATE.md:686-691; commit 4a42db0 | +$10,217 / 1.281 / 298 | 3.08 [+0.74, +4.98] | 0.84 [-1.78, +3.06] | DOES NOT SURVIVE (in-sample filter D2-4; CI includes 0 after costs) |
| R3 WT +$13,906 / 0.908 / 314 | outputs/r3_production_baseline.md:19 (uncommitted) | +$13,184 / 0.858 / 315 | 2.35 [+0.15, +4.15] | 0.84 [-1.49, +2.94] | DOES NOT SURVIVE (plus in-sample-selected bypass, D3-18) |
| OOS 75/25 test fold +$2,077 / 0.98 (PARTIAL) | outputs/oos_audit_report_real.md:62-63,131 | +$2,970 / 1.359 (4a run d2) | not computed | not computed | NOT EVIDENCE (cost-unadjusted; its period lies inside the walk-forward sample, whose after-cost CI includes 0) |
| Walk-forward +$7,786 / 1.14 / 246 (WINDOW-DEPENDENT) | outputs/walkforward_audit_report_real.md:26-28,150 | +$8,341 / 1.274 / 249 (verdict flips to GENERALIZES) | 2.63 [+0.11, +4.50] | 0.54 [-2.16, +2.70] | DOES NOT SURVIVE |
| UNH BUY PUTS cohort +$3,994 / Sharpe 1.55 | PROJECT_STATE.md:2846-2860 | +$2,885 / 19 trades (4b s1) | -- | -- | NOT EVIDENCE (in-sample selection, D3-18) |
| Synthetic R3 +$6,775 / 0.41 / 357; flat +$17,913 | PROJECT_STATE.md:28-32; r3_baseline.py:60-72 | not reproducible (D7) | -- | -- | NOT EVIDENCE (placebo: synthetic sentiment is PRNG noise, 4a s3; in-sample filter; corpus not on disk, 03 s10b UNDETERMINED) |
| Synthetic OOS -0.60 / WF -0.05 (DEGRADES) | README.md:183-184 | values UNDETERMINED (03 s10b) | -- | -- | NOT EVIDENCE (placebo) |
| Synthetic OOS GENERALIZES +2.515 / WF -1.24 (on disk) | outputs/oos_audit_report.md:119; walkforward_audit_report.md:153 | -- | -- | -- | NOT EVIDENCE (placebo; mismatched reference corpus D3-6) |
| Option A Sharpe 0.51 to 0.50, DD -30% | README.md:185; outputs/option_a_uniform_sizing.md | -- | -- | -- | NOT EVIDENCE (placebo) |
| Segregated Kelly flat +$33k / 1.06 (5-ticker) | outputs/segregated_kelly_report.md:7 | -- | -- | -- | NOT EVIDENCE (placebo) |
| Regime study R3 +$12,604 / 0.46 | position_sizer.py:116-118; outputs/regime_comparison.md | -- | -- | -- | NOT EVIDENCE (placebo; pre-git) |
| Put structure Variant B (60 DTE/0.25 delta) +$32,457 / 1.98 | outputs/put_structure_study.md:17 | -- | -- | -- | NOT EVIDENCE (synthetic, 5-ticker, 5 confounded variants, chosen by maximum in-sample P&L; code version UNKNOWN; D3-14) |

## 4. Status ledger

**VALIDATED** ([RAN] evidence on real data; engineering only, no edge claims):
- Backtest engine is deterministic: record vs replay bit-identical on 20 logs + stats + report (4a s7).
- HEAD/WT code unchanged since the May runs: GLD (no dividend adjustment) bit-identical; all differences explained by price revision + truncation (4a s6.2).
- On-disk OOS/WF audits reproduce exactly from on-disk logs: +$2,077.04 / 0.9790; +$7,786.22 / 1.1369 (4a s6.1).
- Walk-forward refit uses only completed trades (`exit_date < T`) and is point-in-time safe (02 s3; 03 s10c).
- RV-rank (IV-rank proxy) computation is trailing and leak-free; recompute matches 507/507 logged rows (02 s3; 4b s1).
- Learned model, quintile and bucket sizing provably cannot affect current decisions (03 s12).
- Offline price/earnings snapshot plus replay harness works with no network (4a s8).

**PLAUSIBLE, UNTESTED:**
- Bullish sentiment adds about +0.6% over 9-10 days on the underlying within low-RV days; CI [+0.08, +1.10] at 9d, crosses 0 at 10d; multiplicity not corrected (4b s2).
- Leak-free subset shows a similar +0.6% at 5d [+0.10, +1.17] on only 74 bullish days (4b s2).
- Any edge outside a 12-month bull regime: untestable with data on disk (02 s5).
- Real option bid/ask vs BS-at-RV30 pricing error: direction and size unknown (4a s2; D4a-4).

**NOT WORKING / NOT EVIDENCE:**
- Live pipeline: stale news scored nightly (D2-1); frozen sentiment read (D1/D2-2); labels only (D5); signal CSVs unparseable (D2-16).
- Every positive real-mode headline after costs (s3).
- All synthetic/demo results (s3).
- BUY PUTS (flat -$27,953; blocked in all 134 walk-forward refits; 4b s1, 03 s10c).
- SELL PUTS / SELL CALLS / IV_CRUSH (never tradeable; 03 s7, s9).
- Low-RV filter as a source of edge (4b s2).
- 60-DTE BUY PUTS structure (D3-14).
- The "global" 6% cap (per ticker; 8-86 days above 6%; 4b s7).
- Repo Sharpe/DD conventions (D4a-2, D9).

## 5. Spec reconciliation (03 s15, updated)

| claim | live | backtest | note |
|---|---|---|---|
| Sentiment from news (Finnhub/NewsAPI), internet, SEC | Partial (Finnhub only, frozen) | Partial (news only drives decisions) | No NewsAPI/internet; SEC decision-inert |
| FinBERT scoring | Confirmed | Confirmed | Revision unpinned (D3-13) |
| Reddit removed | Confirmed | Confirmed | Log/doc remnants only (01 s11.4) |
| IV only a regime filter | Confirmed | Confirmed | Mid-IV vetoes trades; the filter adds no return (4b s2) |
| IV Rank selects debit vs credit | Confirmed (label) | Confirmed | Credit never accepted |
| Earnings filter before entry | Partial (labels) | Contradicted | Effect on backtest about $0, 14 trades (4b s9) |
| IV-crush logic | Partial (label) | Not found | -- |
| Logistic model filters/sizes | Contradicted | Contradicted | Gated off |
| SELL CALLS auto-disabled by decay study | Contradicted | Contradicted | Blocked by the credit floor |
| BUY PUTS fixed at 60 DTE | Confirmed (smoke `build_spread`) | Confirmed (R2 study: 45) | Provenance weak (D3-14) |
| Research/production parity | Contradicted | Contradicted | No tests; strike-selection divergence (D3-2) |
| Live and backtest share sizing/pricing/exits | Contradicted | Contradicted | Live executes none of them |

## 6. Defects ranked

CRITICAL and HIGH, deduplicated (highest severity kept):

| rank | id(s) | defect | location | consequence | status after 4b |
|---|---|---|---|---|---|
| 1 | D4b-1 | Positive results vanish after commissions and exit friction (CIs include 0) | engine/spread_builder cost model (D4a-3) | No real-mode edge evidence | confirmed |
| 2 | D1, D2-2 | Live reads frozen `sentiment_{T}_real.csv` | signal_engine.py:73-80,101 | All live signals since 2026-05-04 invalid | confirmed (101/143 rows) |
| 3 | D2-1 | Nightly scorer re-scores the stale backfill chunk | sentiment/scorer.py:311-319 | Fresh news never scored | confirmed (logs) |
| 4 | D2, D2-3 | No 16:00 cutoff: after-close news drives same-close entries | scorer.py:215; engine.py:609 | Look-ahead in every backtest signal | **resized**: present (386/505 days) but P&L not concentrated in leak days; magnitude not computable offline |
| 5 | D2-4 | Kelly filter fit on the full corpus it trades | r3_baseline.py:285-298 | R3 headlines in-sample | confirmed; BUY PUTS block also holds out of sample |
| 6 | D4b-2 | BUY CALLS P&L is directional beta; low-RV adds nothing | 4b s2, s4 | Result is market drift | confirmed |
| 7 | D4b-3 | XOM + GLD = 71-80% of BUY CALLS P&L | 4b s4 | Fragile, concentrated | confirmed |
| 8 | D2-7, D4a-4 | No historical options data; BS at RV30, no skew or VRP | engine.py:291-300,507 | P&L level unvalidated | confirmed |
| 9 | D3-18, D6 | Uncommitted UNH bypass, selected in-sample; active only via engine.py:874 | position_sizer.py:201,547-554 | Inflates WT headline (+$2,967 canonical) | resized (was +$3,994) |
| 10 | D4a-1, D2-15 | Results depend on the download date (dividend back-adjustment, no price cache) | engine.py:390 | 185/507 structures change; WF verdict flips | confirmed; snapshot mitigates for audit only |
| 11 | D4a-2, D9 | Repo Sharpe includes zero rows, sqrt(252/5); DD in ticker order | r3_baseline.py:123-175; metrics.py:85-103 | Headline Sharpe/DD not meaningful | confirmed (4b s5a/b) |
| 12 | D3-1 | 6% cap per ticker; audits use no cap | engine.py:692-698; position_sizer.py:592-599 | Aggregate risk to 11.1% (WT) | confirmed (8 / 86 days > 6%) |
| 13 | D3-2 | BULL_CALL short leg: fixed width (backtest) vs 0.30 delta (live) | engine.py:254-258 vs spread_builder.py:474-487 | Backtest doesn't test the live structure | confirmed |
| 14 | D5 | Live path emits labels only | run_daily.py:200-276 | No live trading exists | confirmed |
| 15 | D7 | Synthetic generator anchored to today() | engine.py:448 | Demo results irreproducible placebo | confirmed (4a s3) |
| 16 | D2-8 | Static hindsight-selected surviving universe | config.py:35-46 | Survivorship/selection bias | confirmed |
| 17 | D2-5 | Timezone-naive news timestamps (machine-local ET) | news_fetcher.py:105 | Date boundaries machine-dependent | confirmed |
| 18 | D4, D2-6 | Live IV rank: front-week IV vs a realized-vol range | options_fetcher.py:239-254 | Live regime not comparable to backtest | confirmed |
| 19 | D3 | Backtest skips the earnings filter | engine.py:712 | Parity gap | **resized**: 14 trades, -$22.60 (moot for P&L) |

MEDIUM:
- D8 (corpus mixes backfill + dated files)
- D10 (stats rebuild from all logs)
- D11 (dead config gates)
- D12 (SELL CALLS "disable" is not the decay study)
- D13 (no tests)
- D16 (key in git history; LOW if rotated)
- D2-9 (SEC filingDate only)
- D2-10 (EDGAR `recent` block only)
- D2-11 (MD&A fallback, 12 of 34 10-Ks)
- D2-12 (same-day filing collisions)
- D2-13 (no Item 1A)
- D2-14 (earnings not point-in-time)
- D2-16 (signal CSV schema drift)
- D3-3 (width-0 on $5 grid; 5 rejections)
- D3-4 (no-row strategies bypass Kelly)
- D3-5 (live emits untradeable labels)
- D3-6 (demo audit corpus mismatch)
- D3-7 (synthetic 75/25 column in real WF report)
- D3-8 (train-fold spill-over; **moot**: no decision change, 4b s10)
- D3-9 (one-sided friction; day-0 exits **moot**: 0 occurred)
- D3-14 (60-DTE provenance)
- D4a-3 (no exit costs)
- D4a-5 (no equity curve)
- D4b-6 (no capital-consistent return)

LOW:
- D14 (stale combined files)
- D15 (.gitignore encoding)
- D17 (merger comment)
- D18 (stale comments)
- D19 (README)
- D20 (unpinned deps)
- D21 (live vs backtest confidence)
- D2-17 (merger dup rows)
- D2-18 (after-hours chains)
- D2-19 (rank min_periods)
- D2-20 (bfill)
- D2-21 (stray rows)
- D3-10 (IV_CRUSH no structure)
- D3-11 (boundary inconsistencies)
- D3-12 (`--device`)
- D3-13 (FinBERT unpinned)
- D3-15 (PROJECT_STATE f* typo)
- D3-16 (r3 report template)
- D3-17 (broad 8-K regex)
- D4a-6 ("851 rows" prose)
- D4a-7 (Finnhub call in backtest)
- D4b-4 (4b replay tie order)
- D4b-5 (iv_rank logged at 4 dp)

## 7. Data readiness (02 s5 + 4a)

| source | status | depth on disk | 2008 / 2020 / 2022 | blocker |
|---|---|---|---|---|
| Finnhub news | partial; live scoring broken | 2025-05-08..2026-05-04 | none | cost (free tier ~12 months) |
| NewsAPI / internet | absent | -- | none | not built |
| SEC EDGAR | partial | AAPL 2016+; others 2019-2025 start; JPM 1 year | partial | not built (pagination, acceptance time, Item 1A) |
| Historical options / IV | absent | live front-week snapshots since 2026-04-23 | none | cost/access |
| Equity prices | on demand, not cached in repo | snapshot 2021-10-11..2026-10-09 (audit only) | 2022 only (burn-in) | not built (period, cache) |
| Earnings dates | live Finnhub, memory only | snapshot Yahoo-scrape 2020-10..2026-11, realized (audit only) | 2020+ realized | not point-in-time |
| Rates / dividends / universe membership | constant / absent / static | -- | -- | not built |

Reproducibility:
- The audit snapshot `audit/artifacts/stage4/yf_snapshot/` (10 price + 6 earnings pickles, manifest) makes the canonical logs and every 4b table replayable offline and bit-identically.
- The repo itself has no price cache, so its results remain download-date-dependent (D4a-1).

## 8. Signal-test summary (4b s2)

Low-RV days, mean forward close-to-close return. Bootstrap by date, blocks of h, 2,000 resamples, seed 0.

| h | bullish | neutral | all low-RV | all days (any RV) | bullish - neutral [CI] | bullish - all low-RV [CI] | leak-free bullish - all [CI] | momentum up5 - all [CI] |
|---|---|---|---|---|---|---|---|---|
| 1 | +0.09% | +0.08% | +0.10% | +0.12% | +0.00 [-0.22, +0.22] | -0.01 [-0.19, +0.15] | -0.02 [-0.20, +0.16] | -0.01 [-0.07, +0.05] |
| 5 | +0.90% | +0.61% | +0.65% | +0.64% | +0.28 [-0.16, +0.72] | +0.25 [-0.09, +0.58] | **+0.61 [+0.10, +1.17]** | -0.08 [-0.24, +0.10] |
| 9 (median hold) | +1.79% | +1.14% | +1.21% | +1.22% | **+0.65 [+0.03, +1.28]** | **+0.58 [+0.08, +1.10]** | +0.69 [-0.22, +1.56] | -0.14 [-0.48, +0.19] |
| 10 | +1.89% | +1.28% | +1.31% | +1.33% | +0.61 [-0.10, +1.29] | +0.58 [-0.01, +1.17] | +0.76 [-0.29, +1.72] | -0.12 [-0.49, +0.26] |

Reading:
- Low-RV days return the same as all days (+1.21% vs +1.22% at 9d), so the regime filter selects nothing.
- Bullish sentiment shows a positive point estimate at h >= 5, but only 3 of 16 pooled sentiment contrasts (two at h=9, one leak-free at h=5) exclude zero, with no multiplicity correction.
- Sentiment correlates 0.23 with the trailing 1-day return versus at most 0.11 with forward returns. Trailing momentum adds nothing.

## 9. Corrections across stages

| earlier statement | corrected by | final resolved statement |
|---|---|---|
| 01 D1: the daily summary shows "fresh" scores | 02 s0 | Daily-summary scores are stale too; the scorer reads the backfill chunk (D2-1) |
| 02 s2.1: 8 of 34 10-Ks fell back to the full document | 03 s0 (T1) | 12 of 34 10-Ks scored at full-document size; 4 AAPL 10-Q stubs scored as single 115-token chunks |
| 02 D2-4: BUY PUTS disabled by the in-sample Kelly | 03 s0 (T3) | Also blocked in all 134 walk-forward refits; in-sample inflation concerns the headline numbers |
| 01 s8 / CLAUDE.md: "global" 6% cap | 03 s0; 4b s7 | Per-ticker cap; aggregate peaks 6.77% (HEAD/WF) and 11.12% (WT) |
| 01 D6: bypass changes "production sizing" | 03 s0 | Backtest Kelly path only; live never sizes |
| 03 s11: UNH bypass adds +$3,994.40 (on-disk) | 4b s1 | Canonical +$2,967.34 (19 BUY PUTS +$2,885.26; 2 BUY CALLS lost to the cap) |
| 02 D2-3 rated CRITICAL look-ahead | 4b s3 | The leak exists (386/505 signal days); leak-free trades have the highest mean P&L; its effect on P&L is not computable offline. It remains a correctness defect but does not explain the result. |
| 03 D3 (earnings filter skipped) HIGH | 4b s9 | 14 affected trades, -$22.60: no P&L consequence |
| 03 D3-8 (OOS train spill-over) | 4b s10 | 30 spill-over trades; neither Kelly decision changes |
| 03 D3-9 (day-0 exits) | 4b s8 | 0 day-0 exits; exit friction (not day-0) is the material cost issue |
| 03 s7: R3 HEAD took 0 BUY PUTS [INFERRED] | 4a/4b s1 | Confirmed: canonical R3 HEAD = 298 BUY CALLS only |
| Reported WF verdict WINDOW-DEPENDENT; R3 +$9,697 / 1.17 | 4a s6.1 | Canonical WF +$8,341 / 1.274, verdict GENERALIZES; R3 +$10,217 / 1.281; both depend on the download date |
| 4b D4b-4 attributes a $12.82 WF DD gap to the repo's unstable sort | targeted read of 4a run d1 (runs/d1/walkforward_audit_report_real.md:29: -1,909.12, matching the report) | The repo script reproduces its own DD exactly; the gap is in 4b's re-implementation tie order. D4b-4 is an audit-replication note, not a repo defect. |
| PROJECT_STATE.md:2906: BUY PUTS gate f* = -0.0567 | 03 D3-15; 4a | Real f* = -0.5224 (on-disk) / -0.7536 (canonical) |

## 10. Security and repository hygiene

- **Finnhub key in history:** a literal API-key fallback exists in `f644ecc:config.py:17` on `origin/main` (01 D16). Commit 17b6a9b says the key was rotated; revocation is unverified. The value is not reproduced here. HEAD and both audit copies read `FINNHUB_API_KEY` from the environment with an empty fallback [RAN filename/pattern check, value not printed].
- **.gitignore:** line 41 (`.claude/`) is UTF-16LE encoded, so `.claude/` is not ignored (01 D15).
- **Secret-like files in the audit copies:** none. `find audit/artifacts/stage4/{head_src,wt_src} -iname '.env*' -o -iname '*secret*' -o -iname '*key*' -o -iname '*.pem'` returned no paths [RAN]. Nor are there any in the repo outside the copies.
- `audit/artifacts/stage4/yf_cache/cookies.db` and `tkr-tz.db` are yfinance session/timezone caches created by 4a (Yahoo session cookie; not opened).
- **Uncommitted working tree:** 12 tracked files modified (+480 / -218): PROJECT_STATE.md, backtest/engine.py, signals/position_sizer.py (`KELLY_FILTER_BYPASS`), scripts/audit_oos_split.py, scripts/audit_walkforward.py, scripts/sector_decay.py, and 6 outputs/*.md. Untracked: `.claude/`, `outputs/sector_decay_analysis_real.md`, `audit/`.
- No tests; dependencies have lower-bound pins only (D13, D20).

## 11. Decisions pending owner

1. Live path: keep, fix (glob-ordering bugs D1/D2-1, labels-only D5), or retire.
2. `KELLY_FILTER_BYPASS` (uncommitted, in-sample selected): commit, revert, or keep as a research flag.
3. Whether the R3 / walk-forward headlines in README, PROJECT_STATE and CLAUDE.md should be restated given the after-cost results.
4. Locked decision #1 (60 DTE / 0.25 delta BUY PUTS): whether its "validated" status stands given its provenance (D3-14).
5. Locked decisions #2 and #4 (Option A, "provisional pending real-data validation"): whether real-data validation is considered done, and on what criterion.
6. The cost model (exit friction, commissions, real quotes) the project treats as authoritative.
7. The data purchase question: historical options/IV, deeper news history, a point-in-time earnings calendar, or none.
8. The after-close cutoff (D2-3): whether to define a decision-time rule, and whether rescoring is worth the compute.
9. Universe definition (static hindsight list vs rule-based) and the XOM/GLD concentration.
10. Whether the synthetic/demo mode remains part of the reported workflow.
11. Whether to commit or discard the 12 uncommitted files, and whether to verify revocation of the historical Finnhub key.

## 12. Reproduction instructions (offline)

Prerequisites: the repo `.venv` (Python 3.14.4) and the 4a artifacts in `audit/artifacts/stage4/` (snapshot, `runs/a/raw`, `runs/b/raw`). No network.

```bash
cd "audit/artifacts/stage4b"
../../../.venv/Scripts/python.exe -I s1_checks.py > s1_out.txt          # checks, WF reconstruction, composition, costs
../../../.venv/Scripts/python.exe -I s8_validate_marks.py               # leg-mark validation
../../../.venv/Scripts/python.exe -I s2_signal_test.py > s2_out.txt     # section 2 signal test
../../../.venv/Scripts/python.exe -I s3_trade_analyses.py > s3_out.txt  # sections 3, 4, 8-11
../../../.venv/Scripts/python.exe -I s5_performance.py > s5_out.txt     # sections 5-7
../../../.venv/Scripts/python.exe -I s5b_after_costs.py                 # after-cost Sharpe
```

To regenerate the canonical logs themselves (4a run C, replay only, no network):

```bash
.venv/Scripts/python.exe -I audit/artifacts/stage4/yf_record_replay.py --mode replay --copy audit/artifacts/stage4/head_src --snapshot audit/artifacts/stage4/yf_snapshot --script scripts/segregated_kelly_report.py -- --real --skip-kelly
```

Then run the same command with `--script scripts/r3_baseline.py -- --real`. Restore `head_src/data/raw` from the repo first; use `wt_src` for the bypass variant.

## Final git status check

[RAN `git status --short` ; `git diff --stat`] after writing this file:

- Tracked diff identical to the stage-1 start state: 12 files changed, **+480 / -218**.
- Untracked: `.claude/`, `outputs/sector_decay_analysis_real.md` (pre-existing), `audit/`.
- This stage added only `audit/00_STATUS.md`. No prior stage file, repository doc or code was modified.

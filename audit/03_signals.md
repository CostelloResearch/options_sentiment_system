# Stage 3 -- Decision logic, signals, and filter provenance

Audit date 2026-10-10. Read-only. Prior files read first (rule 7): `audit/AUDIT_RULES.md`, `audit/01_inventory.md`, `audit/02_data.md`. Earlier findings are cited by ID (D1-D21 stage 1, D2-1..D2-21 stage 2) and not re-derived.

**Configurations.** **HEAD** = commit `4a42db0`. **WT** = working tree. Of the uncommitted files, only `signals/position_sizer.py` and `backtest/engine.py` change decision logic: `KELLY_FILTER_BYPASS`, and the `ticker=ticker` argument at engine.py:874 [RAN `git diff signals/position_sizer.py backtest/engine.py`]. The diffs to `audit_oos_split.py` and `audit_walkforward.py` change report wording only; their fitting and sizing lines are unchanged [RAN T4]. The `sector_decay.py` diff adds `--real` (research only). Unless a step is marked otherwise, HEAD and WT behave identically.

**Command legend (stage 3).** Helper scripts are under `audit/artifacts/stage3/`. They import no project modules, make no network calls, and write only their own stdout capture files in that folder.

| id | exact command | output file |
|---|---|---|
| T1 | `.venv/Scripts/python.exe -I audit/artifacts/stage3/t1_sec_verify.py "C:/Claude Code Project/options-sentiment-system/data/raw"` | t1_out.txt |
| T2 | `.venv/Scripts/python.exe -I audit/artifacts/stage3/t2_signal_census.py "<same>"` | t2_out.txt |
| T3 | `.venv/Scripts/python.exe -I audit/artifacts/stage3/t3_wf_kelly_replay.py "<same>" real` (and `... demo`) | t3_out_real.txt, t3_out_demo.txt |
| T4 | `git diff -U0 scripts/audit_oos_split.py scripts/audit_walkforward.py \| grep -E '^[-+]' ...` (logic lines only) | stdout |
| T5 | `ls -l --time-style=full-iso` on data/raw kelly/backtest/stats files and outputs/*audit*.md, r3 report | stdout |
| T6 | `git show HEAD:signals/position_sizer.py \| grep -nE 'KELLY_FILTER_BYPASS\|if raw_f <= 0'` ; `git show HEAD:backtest/engine.py \| grep -n 'ticker                = ticker'` | stdout |

T3 re-implements `compute_kelly_stats` (position_sizer.py:275-306) and the filter rule (:545-556) in about 20 lines. It reproduces the real walk-forward report's 246 trades and 134 refits exactly (outputs/walkforward_audit_report_real.md:23,11).

---

## 0. Corrections to earlier stages

| earlier item | correction | evidence |
|---|---|---|
| 02 section 2.1 / D2-11: "8 of 34 10-Ks (24%) likely full-document fallback" | **12 of 34 10-Ks (35%)** were scored at full-document size (135-525 chunks, 68k-268k tokens). The 8 flagged plus XOM 10-K 2023, 2024, 2025 and 2026 (148-161 chunks; raw files 337-366 KB, the same size as the flagged XOM full documents). All 4 AAPL 10-Q stubs were scored as one 115-token chunk (score about +0.004). | [RAN T1] |
| 02 D2-4 / 02 section 3: "BUY PUTS gets disabled because of its full-sample Kelly" | The **in-sample** filter is real (D2-4 stands). But BUY PUTS is **also** blocked out of sample: the walk-forward refits give BUY PUTS f* from -0.8729 to -0.1368 and block it in all 134 refits. The disabling decision is not merely an in-sample artifact; the in-sample inflation applies to the headline numbers. | [RAN T3] |
| 01 section 8 and CLAUDE.md "global 6% portfolio cap" | The 6% cap is enforced **per ticker per `run_backtest` call** (open positions tracked within one ticker's loop), not across the universe. The audits enforce no cap at all (`open_risk_dollars=0`). See D3-1. | [READ backtest/engine.py:692-698,774-779] [READ scripts/audit_oos_split.py:248] [READ scripts/audit_walkforward.py:402] |
| 01 D6: "changes production sizing" | Re-scoped. `KELLY_FILTER_BYPASS` affects only the backtest Kelly path (`engine.run_backtest` with `use_kelly_sizing=True`); the live path never calls `size_trade` (D5). Severity stays HIGH for **result provenance**: it adds +$3,994.40 / 20 trades to the on-disk headline. | [READ signals/position_sizer.py:547-554] [RAN T2] |
| 01 section 7, live/backtest strike selection | The divergence is larger than recorded. BULL_CALL_DEBIT's short leg is chosen by **delta 0.30** live but by **fixed width** in the backtest (D3-2). | [READ signals/spread_builder.py:481-483] [READ backtest/engine.py:256-257] |

## 1. Decision pipelines

### 1.1 Live path (`scripts/run_daily.py`; Task Scheduler Mon-Fri 18:30, `setup_scheduler.ps1:89-92`)

| # | step | path:line | notes |
|---|---|---|---|
| L0 | Weekend/holiday guard (skip unless `--force`) | scripts/run_daily.py:361-382 | 7 weekend-dated signal rows exist (02 section 4) |
| L1 | Fetch Finnhub news, 30-day window; dedup on headline; save `news_{T}_{today}.csv` | run_daily.py:204-206; data/news_fetcher.py:89,124,138-150 | |
| L2 | Fetch yfinance chain (nearest expiry at 7 DTE or more), ATM IV, IV rank; save `options_{T}_{today}.csv` | run_daily.py:218-221; data/options_fetcher.py:340-420 | D4, D2-6 |
| L3 | Pick "latest" news CSV, FinBERT score, daily mean; save `sentiment_{T}_{today}.csv` | run_daily.py:236-241; sentiment/scorer.py:311-319, 249-293 | **Picks the 2026-05-04 backfill chunk (D2-1)** |
| L4 | Aggregator summary (display only) | run_daily.py:242-250; sentiment/aggregator.py:232 | not read by L5 onward |
| L5 | `generate_signal`: load latest sentiment row | signals/signal_engine.py:456, 93-131 | **Reads `sentiment_{T}_real.csv` (D1/D2-2)** |
| L6 | **Filter 1, sentiment staleness**: > 3 days prints a WARNING only, never blocks | signal_engine.py:115-121 (MAX_SENTIMENT_AGE_DAYS :66) | |
| L7 | Load IV rank from row 0 of the latest options CSV | signal_engine.py:457, 134-167 | |
| L8 | Load latest SEC filing row and its age vs today | signal_engine.py:458, 403-432 | |
| L9 | **Filter 2, earnings window** (runs FIRST in classification): IV_CRUSH or SUPPRESS overrides any sentiment/IV outcome | signal_engine.py:460, 196-230; earnings_filter.py:163-246 | DIVERGENCE: backtest has no equivalent (D3) |
| L10 | **Filter 3, quadrant rule** (sentiment x IV regime), only when outside the window | signal_engine.py:230, 174-193 | section 3 |
| L11 | Confidence: learned model gated off, so `_tiered_confidence` (news strength + SEC agreement tiers) | signal_engine.py:471-520; confidence_model.py:345 | DIVERGENCE: backtest uses `_compute_confidence_legacy` |
| L12 | Kelly **metadata only**: `kelly_fraction_for` from kelly_stats.csv; `size_multiplier = kelly_f_frac x confidence`. **Does not suppress the label.** | signal_engine.py:534-538 | BUY PUTS labels still emitted live (3 rows; 02 section 4) |
| L13 | Append row to `signals_{T}.csv`; print card | signal_engine.py:582-583, 608-618 | D2-16 schema drift |
| -- | **END of live path.** No spread build, no credit/debit floor, no sizing, no risk limit, no exit management. | run_daily.py:264-276 (only `generate_signal` called) | D5 |

### 1.2 Real-mode backtest (`backtest/engine.run_backtest(demo_mode=False)`)

| # | step | path:line | notes |
|---|---|---|---|
| B1 | Prices: yfinance `auto_adjust=True`; 30d RV; IV rank from rolling 252 min/max of RV (min_periods 30); period 5y if lookback > 250 | engine.py:589-591, 380-416 | DIVERGENCE vs L2 (section 6); D2-15 |
| B2 | Sentiment: union of all `sentiment_{T}_*.csv`, keep last per (ticker, date) | engine.py:598, 419-436 | D8 / D2-21 |
| B3 | Inner join sentiment and price on date; `tail(lookback_days)` | engine.py:609-611 | D2-3 (after-close news on the same bar) |
| B4 | `sent_momentum_3d = diff(3)` over joined rows | engine.py:623-625 | feeds only the gated model and the log |
| B5 | SEC maps from `combined_sentiment_{T}.csv` (tags/features only) | engine.py:641-657 | section 4 |
| B6 | Earnings proximity function loaded (feature only) | engine.py:666-671 | **no earnings filter** (D3) |
| B7 | Kelly stats loaded only if `use_kelly_sizing=True` | engine.py:674 | |
| B8 | Confidence model: `load_model()` returns None (gated) | engine.py:684; confidence_model.py:345 | |
| B9 | **Filter A, quadrant rule** `_classify_signal`; NEUTRAL means skip (no log row) | engine.py:712-715 | no staleness check, no earnings filter |
| B10 | Confidence = `_compute_confidence_legacy` (strength only) | engine.py:749 | logged; no decision effect (section 12) |
| B11 | `sec_aligned`, `days_to_earnings` features computed and logged | engine.py:754-770 | no decision effect |
| B12 | Prune open positions for **this ticker**, sum open risk | engine.py:774-779 | per-ticker (D3-1) |
| B13 | Build spread: strategy map, DTE / short-delta override, strikes on a $5 grid, BS price x (1 +/- 1.5%) | engine.py:791, 229-300 | D2-7; D3-2, D3-3 |
| B14 | **Filter B, structure floors**: width = 0 rejected; debit > 70% of width rejected; credit < 33% of width rejected | engine.py:302-304, 324-332 | logged `rejected_risk_reward` (:832-852) |
| B15 | Flat path only: contracts = max(floor($200 / max_loss$), 1); no cap | engine.py:334-347, 908-914 | locked decision #7 |
| B16 | Kelly path: `size_trade` | engine.py:860-875 | |
| B16a | invalid max_loss means 0 contracts | position_sizer.py:526-531 | |
| B16b | **Filter C, negative-Kelly**: if stats row has count >= 10 and f* <= 0, return 0 contracts (`negative_kelly_{sig}`). WT: skipped for (ticker, signal) in `KELLY_FILTER_BYPASS`. | position_sizer.py:545-556 (HEAD :538) | section 10 |
| B16c | Per-trade fraction: uniform 0.38% (flags False) | position_sizer.py:569-575 | |
| B16d | **Filter D, risk cap**: budget = min(frac x $100k, 6% x $100k - open risk of this ticker); 0 means `portfolio_risk_cap` | position_sizer.py:592-610 | per-ticker |
| B16e | Contracts = max(floor(budget / loss per contract), 1); cap breach only **tagged** `floor_over_cap`, still traded | position_sizer.py:612-625 | 8 such trades in real Kelly logs [RAN T2] |
| B17 | 0 contracts means log row `rejected_by_kelly` | engine.py:882-900 | |
| B18 | Simulate daily: BS mark at RV; exits in order stop, then profit target, then time stop (21 DTE, not on entry day), then expiration | engine.py:916, 479-550; spread_builder.py:948-1052 | section 7 |
| B19 | Book open risk (`total_risk`) until exit_date | engine.py:924-928 | |

**Filter order, live:** earnings window, then quadrant (staleness is a warning only; Kelly is metadata only).
**Filter order, backtest:** quadrant, then structure floors (width/debit/credit), then negative-Kelly (Kelly path only), then per-ticker 6% cap, then MIN_CONTRACTS floor (can override the cap).

## 2. Sentiment construction

| item | finding | evidence |
|---|---|---|
| Model id / revision / device | `ProsusAI/finbert` via `transformers.pipeline("text-classification", top_k=None)`; **no `revision=` pin**; device = GPU 0 if `torch.cuda.is_available()` else CPU. `score_backfill_chunks --device` is only recorded in the manifest and never passed to the scorer [INFERRED: no call path]. | sentiment/scorer.py:47-63; scripts/score_backfill_chunks.py:67-74,327-334 |
| Input text | `f"{headline}. {summary[:200]}"`, or the headline alone if the summary is empty; empty strings are skipped and scored 0 / neutral | scorer.py:81-100, 147-149, 175-179 |
| 512-token handling | `truncation=True` at the tokenizer limit (headline + 200 chars rarely reaches it) | scorer.py:156-157 |
| Per-article score | P(positive) - P(negative), in [-1, 1] | scorer.py:104-112 |
| Daily aggregation | **Unweighted mean** of article scores per (ticker, local calendar date). `headline_count` = number of articles; it does **not** weight the score. bullish/bearish/neutral % come from the top label. | scorer.py:215-233 |
| Article-count gate | **None in any decision path.** `config.min_articles_required=3` is never read (D11). merger `NEWS_MIN_ARTICLES=1` affects only the merger output (unused for decisions). 10.7% of `_real` days have fewer than 3 headlines (02 section 4). | config.py:114; sentiment/merger.py:98, 332-333 |
| Dedup, daily path | Within one fetch, on `headline` (news_fetcher.py:124). No cross-fetch dedup: each nightly file re-scores a 30-day window, and the engine keeps the last file per date. | data/news_fetcher.py:124; engine.py:433 |
| Dedup, backfill path | Within chunk on `headline` (news_fetcher.py:258); across chunks on `url` (score_backfill_chunks.py:167); then rebuilt on (lower/strip headline, date) plus the 2025-05-05..2026-05-04 window (redup_backfill.py:169-178, 60-61) | as cited |
| Fallback scorer (VADER etc.) | **None reachable**; there is no alternative scorer in sentiment/*.py | [RAN `grep -rn -i "vader\|textblob\|fallback" sentiment/*.py`: no scorer fallback] |
| Momentum | Live: `sent_momentum_3d = 0.0` constant, consumed only by the learned model (gated, so it never runs). Backtest: `diff(3)` over joined trading rows (not calendar days), consumed only by the gated model and written to the log. | signal_engine.py:485-503; engine.py:623-625, 739-746 |
| Rolling summary | aggregator 5-day SMA + momentum label: **display only** (run_daily summary, dashboard) | aggregator.py:138-236; run_daily.py:242-250 |

## 3. Quadrant truth table

Rule: `bullish = s > +0.25`, `bearish = s < -0.25`, `cheap = iv < 0.30`, `expensive = iv > 0.70`; **all strict**. Thresholds come from config.py:104-111 [READ signals/signal_engine.py:179-193].

| sentiment \ IV rank | iv < 0.30 | 0.30 <= iv <= 0.70 | iv > 0.70 |
|---|---|---|---|
| s > +0.25 | BUY CALLS | NEUTRAL | SELL PUTS |
| -0.25 <= s <= +0.25 | NEUTRAL | NEUTRAL | NEUTRAL |
| s < -0.25 | BUY PUTS | NEUTRAL | SELL CALLS |

- Boundary values s = +/-0.25 and iv = 0.30 / 0.70 exactly all map to NEUTRAL.
- `_classify_signal` (backtest, engine.py:712) is exactly this table.
- `_classify_with_earnings` (live) applies the earnings window **before** this table [READ signal_engine.py:219-230; earnings_filter.py:204-246]. Inside the window it returns IV_CRUSH or NEUTRAL (SUPPRESS); otherwise the table above.

| earnings delta d = earnings_date - today (calendar days) | IV rank | live output |
|---|---|---|
| -1 <= d < 0 (day after) | any | NEUTRAL (SUPPRESS) |
| d = 0 | any | NEUTRAL (SUPPRESS) |
| 1 <= d <= 2 | iv >= 0.80 | **IV CRUSH** (regardless of sentiment) |
| 1 <= d <= 2 | iv < 0.80 | NEUTRAL (SUPPRESS) |
| d = 3 | any | NEUTRAL (SUPPRESS) |
| d > 3 or d < -1, or no dates | -- | quadrant table |

- The display-only `iv_rank_label` in options_fetcher uses `>=` / `<=` [READ data/options_fetcher.py:256-261], which does not match the classifier's strict comparisons.
- IV_CRUSH uses `>=` 0.80 [READ earnings_filter.py:226]; README.md:96 says "> 80%".

## 4. Real-mode signal input

| question | answer | evidence |
|---|---|---|
| Value driving `_classify_signal` | `sentiment_score` from `load_sentiment_history`, i.e. the **news-only daily FinBERT mean** (unweighted) from `sentiment_{T}_real.csv` plus stray rows from dated files (D2-21). **Not** the merger's `combined_sentiment`. | engine.py:598, 705, 712; engine.py:419-436 |
| Do SEC / merger values change any backtest decision? | **No.** They set `sec_aligned` (used only by the gated learned model and the log), `sentiment_source` (tag only), and `days_to_earnings` (gated feature). They don't affect accept/reject, strategy, strikes, size, or exits. | engine.py:641-657, 720-747, 754-789 |
| Live: what SEC affects | `_tiered_confidence` tier and value (HIGH when SEC agrees and is 180 days old or less, LOW when it disagrees, and so on). That confidence feeds `size_multiplier`. | signal_engine.py:286-345, 514-520, 538 |
| Is that live output consumed downstream? | **Display only**: the `signals_{T}.csv` columns, the printed card, and the dashboard overlay (dashboard/app.py:142-156). No code trades or sizes from it. | signal_engine.py:543-583, 654-742 |
| Net | The 3-stream merger weighting (0.50/0.35/0.15) affects **no** decision anywhere. SEC sentiment affects only a displayed confidence. | merger.py:92-94 |

## 5. SEC signal

| item | finding | evidence |
|---|---|---|
| Sections extracted | 10-K Item 7 MD&A; 10-Q Part I Item 2 MD&A; 8-K cover body; EX-99 exhibit for earnings 8-Ks. Falls back to the full document if the MD&A slice is under 500 chars. No Item 1A. | data/sec_fetcher.py:262-310, 380-408 (D2-11, D2-13) |
| Chunking | FinBERT tokenizer, non-overlapping 510-token content windows (512 minus 2 specials) | sentiment/sec_scorer.py:71-107 |
| Per-chunk score | P(pos) - P(neg), `truncation=True, max_length=512` | sec_scorer.py:113-133 |
| Cross-chunk aggregation | Token-weighted mean, sum(score_i x tokens_i) / sum(tokens_i). Texts under 200 chars after whitespace squeeze are skipped. | sec_scorer.py:153-155, 196-215 |
| Subcategory mapping | 10-K becomes `10-K_mdna`; 10-Q becomes `10-Q_mdna`. 8-K: if the cover matches `item 2.02\|results of operations`, or `item 7.01` plus an earnings keyword, it is earnings: `8-K_earnings_prepared` (score the EX-99) if the exhibit exists, else `8-K_earnings_cover`. Otherwise `8-K_other`. | sec_scorer.py:300-369 |
| D17 inconsistency | The merger puts **both** `8-K_earnings_prepared` and `8-K_earnings_cover` in the earnings stream (merger.py:245), while its comment (merger.py:239-240) lists the cover under "other". On disk: 163 prepared + 8 cover (02 section 4). | merger.py:239-245 |
| Persistence / staleness | Merger: earnings stream forward-filled for 90 days (`EARNINGS_STALE_DAYS`), other stream for 180 days (`SEC_STALE_DAYS`); earnings is preferred when fresh. Live: latest filing of any type; fresh if 180 days old or less (signal_engine.py:254); stale with base < 0.75 forces LOW. | merger.py:96-97, 323-348; signal_engine.py:314-342 |

**Extraction verification (12 flagged filings)** [RAN T1]:

| ticker | file | raw bytes | chunk_count | total_tokens | scored text |
|---|---|---:|---:|---:|---|
| AAPL | 10-Q_2020-07-31 | 594 | 1 | 115 | stub (score +0.0045) |
| AAPL | 10-Q_2021-01-28 | 595 | 1 | 115 | stub (+0.0040) |
| AAPL | 10-Q_2021-04-29 | 593 | 1 | 115 | stub (+0.0042) |
| AAPL | 10-Q_2021-07-28 | 594 | 1 | 115 | stub (+0.0046) |
| JPM | 10-K_2026-02-13 | 1,147,020 | 525 | 267,650 | full-document fallback |
| WMT | 10-K_2023-03-17 / 2024 / 2025 / 2026 | 328-351 KB | 135-146 | 68.8k-74.0k | full-document fallback (all 4) |
| XOM | 10-K_2020 / 2021 / 2022 | 318-336 KB | 138-145 | 70.3k-73.6k | full-document fallback (all 3) |

Counts: **8 of 8 flagged 10-Ks scored as full documents; 4 of 4 stubs scored as single 115-token chunks.** Population: 12 of 34 10-Ks have more than 100 chunks (XOM 2023-2026 added); 4 of 95 10-Qs have 1 chunk or fewer [RAN T1]. The scored sentiment for these filings is a whole-document (risk factors, financial statements) average, not MD&A. Under section 4 this changes only the live displayed confidence.

## 6. IV regime

| | live | backtest |
|---|---|---|
| Formula | `(real_iv - min(RV30_1y)) / (max(RV30_1y) - min(RV30_1y))`, clipped to [0,1]; falls back to RV30 in the numerator if real_iv is None | `(RV30_t - min252(RV30)) / (max252(RV30) - min252(RV30))`, min_periods 30, clipped; 0.5 if range < 1e-8 |
| Location | data/options_fetcher.py:239-254 (real_iv :293-337) | backtest/engine.py:401-414 |
| Measures | Front-week (7-13 DTE) ATM implied vol relative to a realized-vol range: a mixed vol-risk-premium measure, not IV rank (D2-6) | Realized-vol percentile-of-range, i.e. realized-vol regime, not implied |
| Thresholds | 0.30 / 0.70 strict (section 3); IV_CRUSH >= 0.80 | 0.30 / 0.70 strict |

**Regime to structure** [READ engine.py:205-210; spread_builder.py:658-663]: cheap means debit (BUY CALLS gives BULL_CALL_DEBIT, BUY PUTS gives BEAR_PUT_DEBIT); expensive means credit (SELL PUTS gives BULL_PUT_CREDIT, SELL CALLS gives BEAR_CALL_CREDIT); mid means no trade.

**Credit floor failure.** The trade is **rejected; there is no fallback to a debit structure or any other.**
- Backtest: `rejection_reason = f"net credit {net:.2f} < {CREDIT_MIN_PREMIUM_FR*100:.0f}% of width {width:.2f}"` (engine.py:330-332), recorded with `exit_reason="rejected_risk_reward"` and pnl 0 (engine.py:832-852).
- Live (`build_spread`, smoke test only): `f"net credit {net:.2f} < {CREDIT_MIN_PREMIUM_FR:.0%} of width {width:.2f}"` (spread_builder.py:813-816), giving `accepted=False` (:836-838).

**Does any IV-derived value feed a direction or a model feature?**
- Live: direction comes only from sentiment. IV rank selects regime/NEUTRAL and triggers IV_CRUSH (a vol label, not directional). `iv_conf` is a component of the displayed confidence (signal_engine.py:382-389). `iv_rank` is a learned-model feature (gated, so it never runs).
- Backtest: the same regime role. Sigma = RV30 drives strike selection, pricing and marking. `iv_rank` enters the legacy confidence (logged only) and the gated model.
- Never directional in either path. But a mid-range IV rank vetoes even strong-sentiment trades.

## 7. Strategy catalogue

| label | structure (legs) | entry conditions | strike selection | DTE | exit rules | roll | reject conditions | enabled HEAD | enabled WT | reachable live | reachable backtest |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BUY CALLS | BULL_CALL_DEBIT: long call, short higher call | s > 0.25, iv < 0.30 (live: outside earnings window) | Live: long 0.55 delta (0.50-0.60), short **0.30 delta** (0.25-0.35) above long. **Backtest: long closest to 0.55 delta on $5 grid, short = long + $5/$2.50 width (no delta)** | 35 (live window 30-45) | stop: pnl <= -80% of debit; target: pnl >= 50% of max profit; time stop at 21 DTE; else expiry | none | debit > 70% of width; width 0 (backtest); illiquid OI < 50 or bid-ask > 10% (live only); 1-contract risk > $200 (live only) | yes (f* +0.2416) | yes | label only | yes (295 accepted real flat; 294 taken Kelly WT) |
| BUY PUTS | BEAR_PUT_DEBIT: long put, short lower put | s < -0.25, iv < 0.30 | long 0.55 delta; short **0.25 delta** (live range 0.20-0.30, strictly below long; backtest closest to 0.25, forced to long - $5 if not below) | **60** (live window 50-70) | same | none | same + negative-Kelly (Kelly path) | **blocked** in Kelly path (f* -0.5224); traded in flat path | blocked except **UNH** (bypass) | label only (3 live rows) | flat: 154 accepted; Kelly HEAD: 0 taken [INFERRED from the 295-trade R3 HEAD figure]; Kelly WT: 20 taken (UNH) |
| SELL PUTS | BULL_PUT_CREDIT: short put, long lower put | s > 0.25, iv > 0.70 | short 0.20 delta; long = short - width | 35 | stop: value >= 2x credit; target 50%; time stop 21 DTE | none | **credit < 33% of width** | No kelly_stats row, so **not** Kelly-filtered; blocked only by the credit floor | same | label only (5 live rows) | **0 accepted in every log** (23 real, 30 demo, 427 archive rejected) [RAN T2] |
| SELL CALLS | BEAR_CALL_CREDIT: short call, long higher call | s < -0.25, iv > 0.70 | short 0.20 delta; long = short + width | 35 | same as SELL PUTS | none | credit < 33%; width 0 | same as SELL PUTS | same | label only (6 live rows, e.g. TLT 2026-09-25) | **0 accepted in every log** (27 real, 51 demo, 189 archive) |
| IV CRUSH | none defined (`_SIGNAL_TO_BUILDER` has no entry; README says "sell ATM straddle/strangle") | 1-2 days before earnings, iv >= 0.80 | -- | -- | -- | -- | `build_spread`: "no spread defined for signal 'IV CRUSH'" (spread_builder.py:726-728) | label only | label only | yes (1 live row) | **unreachable** (backtest never calls the earnings filter) |
| NEUTRAL | no trade | all other cells; SUPPRESS | -- | -- | -- | -- | -- | -- | -- | yes | yes (skipped before logging, engine.py:714-715) |

Evidence: engine.py:205-373; spread_builder.py:86-125, 474-663, 680-844, 948-1052; position_sizer.py:545-556; [RAN T2].

**BUY PUTS 60 DTE / 0.25 delta, every path:**

| path | DTE | short delta | evidence |
|---|---|---|---|
| backtest engine (all `run_backtest` entrypoints) | 60 | 0.25 | engine.py:221-226, 248-267; real flat logs: all 154 BEAR_PUT_DEBIT `dte_entry=60` [RAN T2] |
| live `build_spread` (smoke test only) | 60 target, window 50-70 | 0.25 (range 0.20-0.30) | spread_builder.py:538-539, 734-741 (literals duplicated, D7 stage 1) |
| put_structure_study Variant B | 60 | 0.25 | scripts/put_structure_study.py:104-111 |
| put_structure_study other variants | 20 / 45 / 45 single-leg / 35 baseline | 0.35 / 0.30 ($10 width) / n/a / 0.30 | put_structure_study.py:96-131 |
| regime_comparison R2 (monkeypatch) | **45** | none ($10 fixed width, long 0.55) | scripts/regime_comparison.py:84-87, 238-247, 505-509; 93 demo + 75 archive BEAR_PUT_DEBIT rows at `dte_entry=45` [RAN T2] |
| all other strategies | 35 | -- | engine.py:248 (`DTE_TARGET`, spread_builder.py:86) |

Realized deltas in the real flat log (accepted): BEAR_PUT_DEBIT short |delta| mean 0.206, median 0.233, min 0.003; BULL_CALL_DEBIT short |delta| mean 0.376 (the 0.30 target is not applied in the backtest) [RAN T2].

## 8. Earnings filter and IV crush

| item | finding | evidence |
|---|---|---|
| Rules | Nearest earnings date by absolute calendar distance; d = earnings - check_date. SUPPRESS for d in [-1, 0] and for d = 3, or for d in [1, 2] with iv < 0.80; IV_CRUSH for d in [1, 2] with iv >= 0.80. | earnings_filter.py:136-162, 188-246 |
| Units | **Calendar days** (`(d - check_date).days`); the docstring says "trading days" | earnings_filter.py:160, 181 |
| Order | First, before the quadrant table (live only) | signal_engine.py:219-230 |
| IV_CRUSH effect | Emits the label `IV CRUSH`; no structure, sizing, or trade exists anywhere | spread_builder.py:658-663, 726-728 |
| Backtest | Computes `days_to_earnings` from today's Finnhub window (D2-14) for the log/gated model; **never** calls `is_earnings_window`; no suppression. **D3 confirmed.** | engine.py:666-671, 712, 763-770 |
| Data | Finnhub calendar, today - 90 to today + 180 days, memory-only (D2-14); errors give [] and no suppression | earnings_filter.py:93-129 |

## 9. SELL CALLS and SELL PUTS

| question | finding | evidence |
|---|---|---|
| Emission paths, live | Quadrant cells (s > 0.25, iv > 0.70) and (s < -0.25, iv > 0.70) outside the earnings window. Labels emitted regardless of Kelly. Live rows: SELL PUTS 5, SELL CALLS 6. | signal_engine.py:190-192; 02 section 4 |
| Emission paths, backtest | The same quadrant cells; then the spread is built and the credit floor applied | engine.py:712, 791, 330-332 |
| What the decay study writes | `signal_decay.run_decay_analysis` writes `outputs/signal_decay_analysis.md` with TRADE/DISABLE rows; `run_kelly_study.py:175-224` prints them and copies them into its own markdown | signals/signal_decay.py:347-441, 443-541; scripts/run_kelly_study.py:175-224 |
| Does code read it? | **No.** No module reads `signal_decay_analysis.md` or any DISABLE flag | [RAN `grep -rn "signal_decay_analysis\|DISABLE" --include=*.py`: only writers and prose] |
| Negative-Kelly with **no** stats row | `s = stats.get(signal, {})` is falsy, so `kelly_f = 0.0` and the filter is **skipped**; the trade proceeds to uniform 0.38% sizing (MIN_TRADES_FOR_KELLY applies only when a row exists). It is **not** blocked and does **not** use DEFAULT_RISK_FRAC (that is reached only on the legacy bucket path). | position_sizer.py:534-536, 545-556, 559-575 |
| kelly_stats.csv rows | Only BUY CALLS and BUY PUTS, because SELL trades never reach `accepted=True` and `compute_kelly_stats` uses accepted rows only | data/raw/kelly_stats.csv; position_sizer.py:268-269 |
| Ever accepted? | **Never**, in any log on disk: real flat 0/50, real Kelly 0/50, demo flat 0/81, demo Kelly 0/227, demo r1/r2/r3/logistic/magnitude 0/285, archive 0/616. Reasons: "net credit # < 33% of width #" (credit floor) and "degenerate width=0". | [RAN T2] |
| Net mechanism | Both are disabled **de facto by the credit floor under BS-with-RV pricing** (synthetic credits too small; position_sizer.py:204-226 TODO). Not by the decay study, and not by Kelly. With real chains or higher sigma they would be sized uniformly with no edge check. | as above |

## 10. Kelly filter provenance

### 10a. Mechanics

| item | finding | evidence |
|---|---|---|
| Bucket | Per **signal label** across all tickers (no per-ticker or per-regime split) | position_sizer.py:275 (`groupby("signal")`) |
| Inputs | Accepted rows only; r = pnl_pct / 100 (fraction of max loss) | position_sizer.py:268-276, 234-240 |
| f* | p = share of r > 0; W = mean(win) / abs(mean(loss)); f* = (W p - (1 - p)) / W; 0 if either side is empty | position_sizer.py:281-291 |
| KELLY_FRACTION | `kelly_f_frac = 0.25 x max(f*, 0)`; under uniform sizing it's used only for live display (`kelly_fraction_for`) | position_sizer.py:293, 641-658 |
| Filter | If a row exists with count >= 10 and f* <= 0: 0 contracts. If the row exists with count < 10: f* treated as 0, no filter, trade proceeds. No row: no filter. | position_sizer.py:545-556 |
| Under uniform sizing | f* has no effect on size; it only gates | position_sizer.py:569-575 |

### 10b. Provenance table

| result | config | kelly stats read | producer script:line | input logs / window | overlap with filtered trades | class |
|---|---|---|---|---|---|---|
| Synthetic R3 +$6,775 / 0.41 / 357 (PROJECT_STATE.md:28-32; pinned scripts/r3_baseline.py:60-64) | pre-Option-A (quintile sizing + learned model on), dated 2026-04-25 | kelly_stats.csv as written by the study | scripts/regime_comparison.py:474-475 (stats from the full demo flat corpus), then the R3 run over the same dates :435, 515 | `backtest_{T}_demo.csv`, 10 tickers, 500-day synthetic window ending about 2026-04-25 (today()-anchored, D7); **logs not on disk** (current demo logs date from 2026-05-01) | 100% | **IN-SAMPLE FILTER** [READ code]; reproduction UNDETERMINED (corpus overwritten) |
| Real R3 +$9,697 / 1.17 / 295 (PROJECT_STATE.md:686-691; commit 4a42db0 message) | HEAD (no bypass) | data/raw/kelly_stats.csv (BC 295 / +0.2416; BP 154 / -0.5224) | scripts/r3_baseline.py:285-286 (stats from the full real flat corpus), then the Kelly run :291-298 | `backtest_{T}.csv` real, entries 2025-05-08..2026-05-04 (507 rows) | 100% | **IN-SAMPLE FILTER** |
| outputs/r3_production_baseline.md +$13,906 / 0.908 / 314 (uncommitted) | **WT** (bypass active) | same kelly_stats.csv (md5 unchanged per PROJECT_STATE.md:2846-2848) | r3_baseline.py `--real`, written 2026-05-05 15:13:59-15:14:12 [RAN T5; INFERRED from mtimes + PROJECT_STATE.md:2846-2852] | same real flat corpus | 100%; the bypass pair was chosen from real sector-decay on the same corpus (PROJECT_STATE.md:2879-2897) | **IN-SAMPLE FILTER** (and an in-sample-selected exception) |
| OOS real, test +$2,077 / 0.98, PARTIAL (outputs/oos_audit_report_real.md:60-68,131) | HEAD = WT (logic identical, T4) | in-memory train stats; also written to kelly_stats_oos_train_real.csv (BC 228 / +0.2587; BP 107 / -0.5972) | scripts/audit_oos_split.py:177-184, 950-975 | train = real flat `entry_date <= 2025-12-22` (382 rows); test = after (125 rows) | test fold: none, **except** train labels include trades exiting after the cutoff (filter is `entry_date <=`, :953), up to 60 days into the test window | **OUT-OF-SAMPLE FILTER** (boundary caveat, D3-8). Its "in-sample" column = the pre-bypass `_kelly` logs = IN-SAMPLE. |
| Walk-forward real +$7,786 / 1.14, WINDOW-DEPENDENT | HEAD = WT | in-memory per refit | scripts/audit_walkforward.py:314-357, 261-282 | real flat; train = accepted with `exit_date < T` | none | **OUT-OF-SAMPLE FILTER**. Its "75/25 OOS" column is the **synthetic** constant (audit_walkforward.py:143-150; D3-7). |
| OOS demo GENERALIZES, test Sharpe +2.515 (outputs/oos_audit_report.md:60-68,119) | HEAD = WT | train stats to kelly_stats_oos_train.csv (BC 78 / +0.2983; BP 54 / -0.605) | audit_oos_split.py (demo) | `backtest_{T}_demo.csv` from the 2026-05-01 run (283 rows; cutoff 2025-12-15) | test: none (same boundary caveat) | **OUT-OF-SAMPLE FILTER**, but the in-sample reference is `_demo_kelly` logs with **872** rows from a **different run** (D3-6); prose says "851 rows" (:14) |
| Walk-forward demo (Sharpe -1.24, DEGRADES) | HEAD = WT | in-memory | audit_walkforward.py (demo) | 283-row demo flat; 160 evaluable | none | **OUT-OF-SAMPLE FILTER** (same reference mismatch: n_signals 872 vs 160, outputs/walkforward_audit_report.md:37) |
| README.md:183-184 (OOS -0.60, WF -0.05) | 2026-04-27 commits 207cc64 / fe82ead | -- | same scripts at that time | synthetic corpus as of 2026-04-27, **not on disk** | -- | method OUT-OF-SAMPLE; values **UNDETERMINED** (corpus regenerated since; D7). Resolve by checking out 207cc64 and rerunning on a pinned date (needs network). |

### 10c. Walk-forward real, per-refit behaviour

- Per signal row in entry-date order: T = entry_date. Training = accepted rows with exit_date < T (sorted by exit_date, `iloc[:n]`, :314-345). Skip the row if fewer than 50 completed (99 rows skipped).
- Refit only when n grows: 134 refits, first 2025-07-29 (n=50), last 2026-04-30 (n=432).
- Size each accepted row with `size_trade(stats, open_risk_dollars=0, no ticker)`. The confidence model is refit and scored but **unused** (uniform sizing).
- Per-trade P&L = flat `pnl` x 100 x new contracts.

[RAN T3] Replay:

| quantity | value |
|---|---|
| taken by strategy | BUY CALLS **246**; BUY PUTS **0**; SELL PUTS / SELL CALLS 0 (never accepted) |
| blocked by negative Kelly | BUY PUTS 133 |
| refits with BUY PUTS **not** blocked | **0 of 134** (count already 10 or more at the first refit; f* in [-0.8729, -0.1368]) |
| refits with BUY CALLS blocked | 0 of 134 (f* first +0.339, last +0.249) |
| demo comparison | 43 refits; BUY PUTS unblocked in **11** refits (f* up to +0.1105); taken BC 87 / BP 27 |

The report's sampled refits (outputs/walkforward_audit_report_real.md:81-89) match T3's first and last values.

## 11. KELLY_FILTER_BYPASS

| item | finding | evidence |
|---|---|---|
| What | WT only: `KELLY_FILTER_BYPASS = {("UNH","BUY PUTS")}`. If `(ticker, signal)` is in the set, the negative-Kelly early return is skipped and `kelly_f` is set to 0, so uniform sizing proceeds. | signals/position_sizer.py:201, 547-554 |
| HEAD | Absent; `if raw_f <= 0:` at HEAD position_sizer.py:538 | [RAN T6] |
| Where read | Only inside `size_trade` | position_sizer.py:547 |
| Dependence on `ticker=ticker` | It needs the caller to pass `ticker`. Only engine.py:874 does (WT; absent at HEAD [RAN T6]). The audits (audit_oos_split.py:244-252, audit_walkforward.py:396-406), regime_comparison and live never pass it, so the bypass is inactive there. | as cited |
| Results produced with it | `data/raw/backtest_{T}_kelly.csv` (2026-05-05 15:14) and `outputs/r3_production_baseline.md` (15:14:12) [RAN T5]. The UNH BUY PUTS cohort is 20 of 21 taken (1 hit `portfolio_risk_cap`), +$3,994.40; the universe total excluding it is $9,911.73 over 294 trades [RAN T2]. | |
| Not produced with it | All four audit reports (written 11:19-11:21, before the 15:12 edit; and they never pass `ticker` anyway); sector_decay reports (flat logs) [RAN T5] | |
| Side effect | UNH BUY PUTS positions consume UNH's per-ticker cap: 1 UNH BUY CALLS blocked by `portfolio_risk_cap` (295 to 294 BC) [RAN T2] | |

## 12. Confidence and sizing

| item | finding | evidence |
|---|---|---|
| Live confidence | `_tiered_confidence`: base = legacy strength; HIGH [0.80, 1.0] if SEC is fresh and agrees; LOW [0, 0.50] if it disagrees or is stale with base < 0.75; else MEDIUM [0.50, 0.80] when base >= 0.5, otherwise LOW; scaled into the tier | signal_engine.py:286-345 |
| Backtest confidence | `_compute_confidence_legacy`: mean of the sentiment depth past threshold and the IV depth past threshold, clipped | signal_engine.py:348-390; engine.py:749 |
| Consumers (all flags False) | Backtest: written to the log; `size_trade` clips it but uniform sizing ignores it (:569-575); `compute_and_save_quintile_edges` writes `quintile_edges.json` (unused); research decay/quintile tables. Live: CSV, card, `size_multiplier`, dashboard. **Display / reporting only; never filters or sizes.** | position_sizer.py:533, 569-575; r3_baseline.py:289 |
| Uniform sizing | budget = min(0.0038 x notional, remaining cap); contracts = max(floor(budget / (max_loss x 100)), 1). Notional = **$100,000** (`KELLY_BACKTEST_NOTIONAL`, engine.py:105, 873), so about $380 per trade. Flat path: $10k x 2% = $200 budget, min 1 contract, no cap (engine.py:341-347). | position_sizer.py:574, 599, 612-613 |
| MAX_PORTFOLIO_RISK 6% | Kelly path only; **per ticker** (open positions tracked within one ticker's run, engine.py:692-698, 774-779); not enforced cross-ticker; `MIN_CONTRACTS` can exceed it (tagged `floor_over_cap`, traded: 8 real WT trades). The flat path has no cap. The audits use `open_risk_dollars=0`, i.e. no cap. | position_sizer.py:592-625; [RAN T2] |
| Concurrent-position limit | **None** (no count limit anywhere) | [READ engine.py:692-928] |
| Learned model | Features (fixed order): abs_sentiment, iv_rank, sent_momentum_3d, sec_aligned, log1p(headline_count clip 200), log1p(days_to_earnings clip 60) (confidence_model.py:97-104, 143-162). Label: `pnl_pct > 0` on accepted trades (:391). Training: flat trade log via fit_confidence_model / compare_* (on-disk JSON 2026-04-24; `sec_aligned` beta 0, consistent with synthetic training). Standardization: z-score using training mean/std (:194-204). Regularization: L2 lambda 0.5 inside IRLS, 50 iterations, tol 1e-6 (:108-112). | as cited; data/raw/confidence_model.json |
| Can it influence a current decision? | **No.** `load_model()` returns None (:345), so every live/backtest caller takes the legacy branch. The audits refit and score it, but uniform sizing ignores confidence. | confidence_model.py:340-345; position_sizer.py:569-575 |
| Magnitude model | Imported only by compare_confidence_models.py (01 section 6); outside every decision path | [RAN C16] |

## 13. 60-DTE provenance (outputs/put_structure_study.md)

| item | finding | evidence |
|---|---|---|
| Producer | `scripts/put_structure_study.py` `run()`: loads the BUY PUTS rows of the flat logs, rebuilds each with variant parameters (own builder :142-265), and simulates with `simulate_spread_pnl` on a 5y price cache | put_structure_study.py:325-343, 344-437 |
| Sentiment | **Synthetic**: the default is `demo=not args.real` and the report makes no real-mode statement | put_structure_study.py:490-493 [INFERRED: run without `--real`] |
| Universe | The report (mtime 2026-04-24) predates the 2026-04-25 10-ticker rebuild, so the 5-ticker universe (AAPL, NVDA, MSFT, SPY, QQQ). PROJECT_STATE.md:319-327 calls it "the same 5-ticker flat corpus". n = 168 BUY PUTS signals. | [INFERRED from mtime + PROJECT_STATE.md:319-327] |
| Grid | **Not a DTE x delta grid. 5 hand-picked variants** that change several knobs at once: A 20 DTE / 0.35 delta; B 60 / 0.25; C 45 / 0.30 / $10 width; D 45 DTE single long put 0.50 delta; Baseline 35 / 0.30. Only one cell at 60 DTE and one at 0.25 delta. | put_structure_study.py:95-132 |
| Selection | **Maximum in-sample total P&L** among variants with n_accepted > 0 | put_structure_study.py:431-437 |
| Sizing | 1 contract, BS-synthetic prices (D2-7) | put_structure_study.py header :37-40 |
| Code vs report | Format matches HEAD code (columns `variant,label,n_accepted,...,mean_ret_pct`, the "Premise"/"Results"/"Recommendation" text) | put_structure_study.py:401-480 |
| Code in git | Only in `f644ecc` (2026-04-25), unchanged since. The report (2026-04-24) was produced **before any commit**, so the exact code version that produced it is [UNKNOWN]. A rerun at HEAD would use 10 tickers, and its "Baseline (35 DTE, short 0.30)" label no longer describes production. | [RAN `git log --oneline -- scripts/put_structure_study.py`] |
| Docs vs code | CLAUDE.md:110-124 calls it "validated"; PROJECT_STATE.md:319-327 itself labels it in-sample and provisional | |

## 14. Parameter registry

Effective values per entrypoint. "HEAD vs WT differ" refers to code. "Live" means the run_daily path, or `build_spread` where noted as smoke.

| parameter | live value | live path:line | backtest value | backtest path:line | HEAD/WT differ | live = backtest | dead |
|---|---|---|---|---|---|---|---|
| bullish / bearish sentiment threshold | +/-0.25 strict | config.py:104-105; signal_engine.py:184-185 | same | engine.py:712 (same fn) | no | yes | no |
| low / high IV threshold | 0.30 / 0.70 strict | config.py:110-111 | same | same | no | yes (inputs differ, section 6) | no |
| min_articles_required | 3 | config.py:114 | -- | -- | no | -- | **dead** |
| iv_history_days | 252 | config.py:89 | -- | engine IV_RANK_WINDOW=252 (engine.py:93) | no | live uses a yfinance `period="1y"` window instead (options_fetcher.py:205) | **dead** |
| news_lookback_days | 30 | config.py:88; news_fetcher.py:81 | n/a (backfill 14-day chunks, backfill_news_history.py:51) | -- | no | differ | no |
| IV rank window | 1y of RV30, includes t | options_fetcher.py:199-254 | 252 rows of RV30, min_periods 30 | engine.py:406-407 | no | **no** | no |
| IV numerator | ATM mid IV, 7-13 DTE | options_fetcher.py:281-337 | RV30 | engine.py:401-405 | no | **no** | no |
| VOL_WINDOW | 30 (default arg) | options_fetcher.py:199,215 | 30 | engine.py:92 | no | yes | no |
| MAX_SENTIMENT_AGE_DAYS | 3 (warn only) | signal_engine.py:66 | not applied | -- | no | no | no |
| earnings PRE / POST / IV_CRUSH days / IV threshold | 3 / 1 / 2 / >= 0.80 | earnings_filter.py:49-52 | not applied | -- | no | **no** | no (backtest) |
| SEC_STALE_DAYS | 180 | signal_engine.py:254 | 180 (merger) | merger.py:97 | no | yes (different use) | no |
| EARNINGS_STALE_DAYS | -- | -- | 90 | merger.py:96 | no | -- | merger only |
| merger weights 0.50 / 0.35 / 0.15 | -- | -- | computed, not used for decisions | merger.py:92-94 | no | -- | **decision-dead** |
| CONFIDENCE floors 0.80 / 0.50 | display | signal_engine.py:249-250 | n/a | -- | no | no | display |
| sec_aligned threshold | +/-0.10 | signal_engine.py:480-483 (gated branch) | +/-0.10 | engine.py:727-760 | no | yes | gated |
| USE_LEARNED_MODEL | False | confidence_model.py:130 | False | same | no | yes | -- |
| DTE target / min / max | 35 / 30 / 45 (smoke) | spread_builder.py:86-88 | 35 fixed (no window) | engine.py:248-251 | no | partial | no |
| BUY PUTS DTE | 60 (window 50-70, smoke) | spread_builder.py:734-735 | 60; **45 under regime_comparison R2** | engine.py:221-223; regime_comparison.py:85,241 | no | yes (default) | no |
| BUY PUTS short delta | 0.25 (0.20-0.30) smoke | spread_builder.py:538-539 | 0.25 (no range) | engine.py:224-226 | no | partial | no |
| debit long delta | 0.55 (0.50-0.60) smoke | spread_builder.py:92-93 | 0.55 (no range) | engine.py:256,264 | no | partial | no |
| debit short delta (BULL_CALL) | 0.30 (0.25-0.35) smoke | spread_builder.py:94-95, 481-483 | **not used: fixed width** | engine.py:257 | no | **no** | backtest-dead |
| credit short delta | 0.20 (0.15-0.25) smoke | spread_builder.py:98-99 | 0.20 (no range) | engine.py:274,279 | no | partial | no |
| width $5 / $2.50, cut $100 | smoke | spread_builder.py:102-104, 293 | same, but rounded to the $5 `STRIKE_STEP` grid | engine.py:94, 129-131, 197-199 | no | **no for S < $100** (D3-3) | no |
| WIDTH_TOLERANCE | 2.50 smoke | spread_builder.py:105 | -- | -- | no | -- | backtest-dead |
| FRICTION_FRAC | 1.5% on ask/bid (smoke) | spread_builder.py:109, 421-431 | 1.5% on BS fair, entry only | engine.py:294-295 | no | partial (no exit friction either way) | no |
| DEBIT_MAX_COST / CREDIT_MIN_PREMIUM | 70% / 33% (smoke) | spread_builder.py:112-113, 808-816 | 70% / 33% | engine.py:327-332 | no | yes | no |
| MAX_BID_ASK_FRAC / MIN_OPEN_INTEREST | 10% / 50 (smoke) | spread_builder.py:114-115 | -- | -- | no | -- | backtest-dead |
| ACCOUNT_NOTIONAL / RISK_PER_TRADE_FRAC | $10k / 2% (smoke `size_position`) | spread_builder.py:118-119, 437-463 | flat: $10k x 2% floor 1 | engine.py:341-347 | no | partial (live rejects over budget; backtest floors) | no |
| KELLY_BACKTEST_NOTIONAL | -- | -- | $100k | engine.py:105; audit_oos_split.py:69; audit_walkforward.py:49 | no | -- | no |
| KELLY_FRACTION | 0.25 (display) | position_sizer.py:92, 658 | 0.25 (legacy bucket path only) | position_sizer.py:562 | no | -- | sizing-dead under flags |
| MIN_TRADES_FOR_KELLY | 10 (display) | position_sizer.py:193, 653 | 10 | position_sizer.py:545 | no | yes | no |
| UNIFORM_PER_TRADE_FRAC | -- | -- | 0.38% | position_sizer.py:163, 574 | no | -- | no |
| USE_QUINTILE_SIZING / USE_STRATEGY_BUCKETS | -- | -- | False / False | position_sizer.py:158, 146 | no | -- | QUINTILE_FRAC, STRATEGY_BUCKETS, DEFAULT_QUINTILE_EDGES, quintile_edges.json **dead** under flags (except regime_comparison monkeypatch :515) |
| MAX_RISK_PER_TRADE | -- | -- | 2% (clamp; never binds at 0.38%) | position_sizer.py:95, 574 | no | -- | effectively dead |
| MAX_PORTFOLIO_RISK | -- | -- | 6%, **per ticker**; 0 open risk in the audits | position_sizer.py:96, 594; engine.py:774-779 | no | -- | no |
| MIN_CONTRACTS | -- | -- | 1 (overrides cap) | position_sizer.py:97, 613 | no | -- | no |
| DEFAULT_RISK_FRAC | -- | -- | 2% (bucket path only) | position_sizer.py:184, 565 | no | -- | dead under flags |
| KELLY_FILTER_BYPASS | -- | -- | HEAD: absent; WT: {(UNH, BUY PUTS)}, engine only | position_sizer.py:201 | **yes** | -- | inactive in audits |
| stop debit / credit; profit target; time stop | -- (no live exits) | spread_builder.py:122-125 | 80% / 2x / 50% / 21 DTE | spread_builder.py:995-1029 | no | **live has none** | no |
| RISK_FREE_RATE | 4.5% (IV inversion) | options_fetcher.py:278 | 4.5% | spread_builder.py:83; engine.py:74 | no | yes (duplicated) | no |
| HOLD_DAYS | -- | -- | 5 (Sharpe annualization only) | engine.py:91 | no | -- | no |
| lookback_days | -- | -- | engine default 30; scripts default 500 (r3_baseline.py:462 etc.); main.py `--backtest` uses 30 | engine.py:560; main.py:97 | no | -- | no |
| history period | 1y (live RV) | options_fetcher.py:205 | 5y if lookback > 250 else 2y; put study 5y | engine.py:590; put_structure_study.py:339 | no | no | no |
| FinBERT model / batch / truncation | ProsusAI/finbert, 16, 512 | scorer.py:57, 119, 157 | same model (backfill via the same scorer) | score_backfill_chunks.py:242 | no | yes | no |
| summary chars | 200 | scorer.py:96 | 200 | same | no | yes | no |
| news dedup key | headline per fetch | news_fetcher.py:124 | url, then (headline, date) | score_backfill_chunks.py:167; redup_backfill.py:177-178 | no | **no** | no |
| OOS split / WF warmup | -- | -- | 0.75 by entry_date / 50 completed | audit_oos_split.py:71, 953; audit_walkforward.py:48 | no | -- | no |

## 15. Spec reconciliation

| claim | live status | backtest status | evidence | notes |
|---|---|---|---|---|
| a. Sentiment from news (Finnhub/NewsAPI), general internet, SEC | Partially implemented | Partially implemented | section 4; 02 section 1 | Finnhub only (frozen live, D2-1/D2-2); no NewsAPI or internet; SEC affects only displayed confidence |
| b. FinBERT scoring | Confirmed | Confirmed | section 2 | unpinned revision (D3-13) |
| c. Reddit fully removed | Confirmed (code) | Confirmed (code) | 01 section 11.4 | log/doc remnants only |
| d. IV only a regime filter, never directional | Confirmed | Confirmed | section 6 | IV_CRUSH is a vol label, not directional; the mid-IV zone vetoes trades |
| e. IV Rank selects debit vs credit | Confirmed (label only) | Confirmed | section 6, 7 | credit structures never accepted (section 9) |
| f. Earnings filter applied before entry | Partially implemented (label suppression, no entry exists) | Contradicted | section 8; D3 | |
| g. IV-crush logic applied | Partially implemented (label only, no structure) | Not found | section 7, 8 | |
| h. Logistic model filters and sizes trades | Contradicted (gated off) | Contradicted (gated off; uniform sizing) | section 12 | |
| i. SELL CALLS auto-disabled by decay analysis | Contradicted (label still emitted) | Contradicted (blocked by the credit floor; decay output unread) | section 9 | |
| j. BUY PUTS fixed at 60 DTE | Confirmed (`build_spread`, smoke only) | Confirmed (engine), except regime_comparison R2 = 45 | section 7 | BUY PUTS is zero-contracted in the Kelly path except the UNH bypass |
| k. Research/production parity | Contradicted | Contradicted | 01 section 7; sections 1, 6, 7, 14 | no parity tests (D13) |
| l. Live and backtest share sizing, pricing, exit code (CLAUDE.md:61-62) | Contradicted | Contradicted | D5; sections 1, 7, 14 | Only `bs_price`, `bs_delta`, `simulate_spread_pnl` and the threshold constants are shared; live executes none of them |

## 16. Defects / Open questions / Handoff notes

### Defects

| id | path:line | description | severity | how to confirm |
|---|---|---|---|---|
| D3-1 | backtest/engine.py:692-698, 774-779; position_sizer.py:592-599; audit_oos_split.py:248; audit_walkforward.py:402 | "Global" 6% portfolio cap is per ticker in the engine and absent in the audits; a 10-ticker book can carry up to 10 x 6% open risk; no concurrent-position limit | HIGH | Stage 4: sum open `total_risk` across tickers by date from the `_kelly` logs |
| D3-2 | backtest/engine.py:254-258 vs signals/spread_builder.py:474-487 | BULL_CALL_DEBIT short leg: fixed width in the backtest vs 0.30 delta live; backtest delta picks have no range check (realized short delta mean 0.376 BC, min 0.003 BP) | HIGH (parity; every reported trade is BC) | [RAN T2] deltas |
| D3-3 | backtest/engine.py:94, 129-131, 197-199, 302-304 | $2.50 width rounded on a $5 grid (Python banker's rounding) gives width 0 and rejection, or a $5 width, for S < $100 (TLT, WMT, XOM) | MEDIUM | [RAN T2]: 8 BC + 1 SC "degenerate width=0"; widths of 0 for TLT/WMT/XOM |
| D3-4 | position_sizer.py:534-556 | Signals with no kelly_stats row bypass the negative-Kelly filter and get uniform size; SELL PUTS/CALLS are blocked only by the credit floor under synthetic pricing | MEDIUM | section 9 |
| D3-5 | signal_engine.py:534-538 | Live emits labels the backtest would never trade (BUY PUTS for all tickers, SELL*, IV CRUSH); `kelly_tradable` is only a column | MEDIUM | 02 section 4 live counts |
| D3-6 | scripts/audit_oos_split.py:14-16 vs :60 (report); data/raw/backtest_*_demo.csv (283 rows) vs backtest_*_demo_kelly.csv (872 rows) | Demo OOS/WF audits compare folds from one synthetic run against an in-sample reference from a different run; the prose hardcodes "851 rows" | MEDIUM | [RAN T2] row counts; report lines |
| D3-7 | scripts/audit_walkforward.py:143-150, 691-715 | Real-mode WF report's 75/25 column is the hardcoded synthetic result | MEDIUM | outputs/walkforward_audit_report_real.md:37-49 footnote |
| D3-8 | scripts/audit_oos_split.py:953 | Train fold `entry_date <= cutoff` includes trades whose outcomes resolve after the cutoff (up to 60 DTE) | MEDIUM | Count train trades with exit_date > cutoff (stage 4) |
| D3-9 | spread_builder.py:948-1052; engine.py:291-300 | Entry pays 1.5% friction per leg; exits mark at BS fair value (no exit friction); stop/target can trigger on the entry day | MEDIUM | Stage 4: distribution of days_held = 0 and the friction share of P&L |
| D3-10 | spread_builder.py:658-663, 726-728 | IV CRUSH has no structure; emitted live, untradeable | LOW | |
| D3-11 | signal_engine.py:184-187 vs options_fetcher.py:256-261; earnings_filter.py:226 vs README.md:96 | Boundary inconsistencies (strict vs inclusive; >= 0.80 vs "> 80%") | LOW | |
| D3-12 | score_backfill_chunks.py:327-334; scorer.py:62 | `--device` flag not honoured | LOW | |
| D3-13 | scorer.py:55-63; sec_scorer.py (tokenizer `from_pretrained`) | FinBERT revision not pinned | LOW | |
| D3-14 | put_structure_study.py:95-132, 431-437 | 60 DTE chosen from 5 confounded variants by maximum in-sample synthetic total P&L on the 5-ticker corpus; generating code version unknown | MEDIUM (provenance of a locked decision) | section 13 |
| D3-15 | PROJECT_STATE.md:2906 | Says the BUY PUTS gate is f* = -0.0567; the real kelly_stats.csv has -0.5224 (-0.0567 is the old demo figure) | LOW | data/raw/kelly_stats.csv |
| D3-16 | scripts/r3_baseline.py:391-408 | Report template states "QUINTILE sizing" and prints no USE_QUINTILE_SIZING, UNIFORM_PER_TRADE_FRAC, or bypass state; the uncommitted report misdescribes its own config | LOW | outputs/r3_production_baseline.md:3-11 |
| D3-17 | sec_scorer.py:333-341 | Earnings 8-K regex `results of operations` is broad; full-document 10-Ks (12) and 1-chunk stubs (4) are scored as if they were MD&A | LOW (decision-inert; live display) | [RAN T1] |
| D3-18 | position_sizer.py:201 + PROJECT_STATE.md:2879-2897 | Bypass exception selected from real sector-decay on the same corpus it is then evaluated on (in-sample selection); inactive in every OOS harness | HIGH (result provenance) | section 11 |

Earlier IDs reaffirmed by stage-3 evidence: D3 (backtest skips earnings), D5 (live label-only), D6 (bypass, re-scoped in section 0), D11, D12, D21, D2-4 (refined in section 0), D2-11 (count raised in section 0), D2-16.

### Open questions

1. Code version that produced `outputs/put_structure_study.md`, `regime_comparison.md`, and the synthetic R3 pin (all pre-git, 2026-04-24/25). Can't be determined from git; it would need the owner's pre-git copies.
2. The order of the 2026-05-05 work. PROJECT_STATE lists the bypass entry before the audit-prose regeneration, but file mtimes put the audits (11:19-11:21) before the bypass edit (15:12) [RAN T5]. Mtimes are [INFERRED] evidence; I could not determine the order with certainty.
3. Whether the realized BEAR_PUT_DEBIT short deltas near 0 (min 0.003) come from the +/-25% strike-grid edge or from the `short_K >= long_K` adjustment (engine.py:269-270). Stage 4 can inspect those rows.
4. Whether the Kelly HEAD R3 run (+$9,697) took exactly 0 BUY PUTS. Inferred from 295 = BC taken, but those logs were overwritten at 15:14 on 2026-05-05.

### Handoff notes for stage 4

**Quantities to compute from the trade logs (offline):**
1. Real flat vs real Kelly-WT vs Kelly-WT minus UNH BUY PUTS: P&L, trade counts, and the UNH contribution (expect $13,906.13 / $9,911.73 / +$3,994.40 [RAN T2]).
2. The P&L effect of D2-3: recompute signals after moving after-close articles to d+1. This needs per-article scores, and FinBERT scores are not stored per article, so stage 4 must decide whether it can be done offline. If it can't, report the 386/505 exposure and leave it at that.
3. Cross-ticker open risk by date in `backtest_{T}_kelly.csv` (D3-1): the peak aggregate % of $100k.
4. Entry-day exits (days_held = 0) and the friction share of P&L (D3-9); exit-reason mix by strategy.
5. OOS train-fold boundary contamination: the number of train trades with exit_date > 2025-12-22 (D3-8).
6. Count and P&L of trades truncated by data end (`exit_reason=expiration` with exit before the nominal expiry; 17 real flat).
7. Sharpe recomputed on a daily equity curve vs the sqrt(252/5) per-trade convention (D9).
8. The demo corpus mismatch (D3-6): recompute the demo in-sample reference from the 283-row flat corpus.
9. The width-0 rejection rate and the share of BC P&L from tickers under $100 (D3-3).

**Regression-test targets** (describe only; stage 5): glob ordering for the news and sentiment pickers (D2-1, D1); the strict quadrant boundaries; the earnings-window boundaries in calendar days; credit-floor rejection with no fallback; `size_trade` with no stats row, with a row with count < 10, and with the bypass with and without `ticker`; per-ticker vs global cap accounting; BULL_CALL short-leg parity between `build_spread` and `_build_backtest_spread`; $2.50 width on the $5 grid; walk-forward slice equivalence (`iloc[:n]` vs the `exit_date < T` mask); `load_model()` gating; and that the live path never calls `size_trade`.

## Final git status check

[RAN `git status --short` ; `git diff --stat`] after writing this file:

- Tracked diff is unchanged from the stage-1 start state: the same 12 modified files, **12 files changed, +480 / -218**.
- Untracked: `.claude/` and `outputs/sector_decay_analysis_real.md` (pre-existing), and `audit/`.
- Stage 3 added `audit/03_signals.md` and `audit/artifacts/stage3/` (t1-t3 scripts and their `*_out*.txt` captures).
- Nothing outside `audit/` changed. No checkout, stash, reset, or commit was performed.

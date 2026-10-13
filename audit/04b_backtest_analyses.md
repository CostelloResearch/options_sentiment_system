# Stage 4b -- Backtest analyses (offline)

Audit date 2026-10-13. No network. Before starting I read AUDIT_RULES, 01_inventory, 02_data, 03_signals and 04a_backtest_mechanics (rule 7). Earlier findings are cited by ID.

**Sources.**
- Prices and earnings dates come only from the 4a snapshot `audit/artifacts/stage4/yf_snapshot/` (pandas pickle).
- Canonical logs are `audit/artifacts/stage4/runs/a/raw` (flat, R3 HEAD) and `runs/b/raw` (R3 WT, bypass active).
- Walk-forward (WF) trades are reconstructed by `s1_checks.wf_replay` (extends stage-3 T3 with uniform sizing).
- Original on-disk logs (`data/raw`) are used only in check 3b and sections 5e and 11.
- Seed 0 for every resample.

**Command legend.** Run from `audit/artifacts/stage4b/` with `PY` = `../../../.venv/Scripts/python.exe -I`. Each script writes only the CSVs named in the sections below, plus a `*_out.txt` stdout capture.

| id | command | outputs |
|---|---|---|
| U1 | `PY s1_checks.py > s1_out.txt` | s1_consistency_checks, s1_composition, s1_bypass_contribution, s1_commission_friction, wf_eval_canonical, wf_eval_original |
| U2 | `PY s8_validate_marks.py` | s8_mark_validation |
| U3 | `PY s2_signal_test.py > s2_out.txt` | s2_panel, s2_days_held, s2_group_table, s2_differences_bootstrap, s2_correlations |
| U4 | `PY s3_trade_analyses.py > s3_out.txt` | s3_leak_concentration, s4_*, s8_exit_mix, s8_friction, s9_*, s10_oos_boundary, s11_* |
| U5 | `PY s5_performance.py > s5_out.txt` | s5_performance, s5e_canonical_minus_original, s6_effective_n, s6_neff_cross_ticker, s6_corr_full_window, s7_exposure, s7_open_risk_daily_* |
| U6 | `PY s5b_after_costs.py` | s5b_after_costs (re-imports U5's module, which rewrites U5's CSVs identically) |

---

## 1. Composition and consistency checks

**Consistency checks (U1; s1_consistency_checks.csv): all pass.**

| check | got | expected | pass |
|---|---|---|---|
| 3a WF canonical | 249 trades / $8,340.87; warmup 102; 134 refits | 249 / 8,340.87 (4a d2) | yes |
| 3b WF original | 246 / $7,786.22; warmup 99; 134 refits | 246 / 7,786.22 | yes |
| 3c flat canonical | 452 accepted / -$19,743.51 | 452 / -19,743.51 | yes |
| 3c R3 HEAD canonical | 298 / $10,216.57 | 298 / 10,216.57 | yes |
| 3c R3 WT canonical | 315 / $13,183.91 | 315 / 13,183.91 | yes |
| 3d RV rank | 507/507 rows match | all | yes, **at 4 dp**: the engine logs `round(iv_rank, 4)` (engine.py:801), so a 1e-9 test against raw values is impossible; the test is round(recomputed, 4) vs logged, with tolerance 1e-9 |

Leg-mark validation (U2): re-derived BS leg values with RV30 match the logged entry/exit spread values and entry leg prices on all 767 trades (max abs error 5e-5, i.e. rounding). The exit-friction figures in sections 1 and 8 rest on this.

**Composition (s1_composition.csv)**

| set | BUY CALLS n / P&L | BUY PUTS n / P&L | total |
|---|---|---|---|
| flat | 298 / +$8,209.84 | 154 / -$27,953.35 | -$19,743.51 |
| R3 HEAD | 298 / +$10,216.57 | 0 | +$10,216.57 |
| R3 WT | 296 / +$10,298.65 | 19 (UNH) / +$2,885.26 | +$13,183.91 |
| WF | 249 / +$8,340.87 | 0 | +$8,340.87 |

BUY CALLS P&L by ticker:

| ticker | flat | R3 HEAD | WF |
|---|---|---|---|
| XOM | 3,446 | 5,043 | 4,133 |
| GLD | 2,390 | 2,390 | 2,516 |
| WMT | 708 | 1,330 | 1,426 |
| NVDA | 1,114 | 1,114 | 30 |
| AAPL | 554 | 420 | 744 |
| SPY | 443 | 443 | 305 |
| UNH | 372 | 372 | 372 |
| IWM | 258 | 258 | -53 |
| TLT | -240 | -319 | -319 |
| JPM | -836 | -836 | -813 |

Flat BUY PUTS by ticker: IWM -12,566, SPY -7,801, GLD -3,736, TLT -2,942, XOM -1,354, AAPL -1,220, JPM -991, WMT -856, NVDA -47, UNH +3,560.

- **Bypass contribution (R3 WT minus R3 HEAD) = +$2,967.34.** That breaks down as 19 UNH BUY PUTS trades (+$2,885.26), plus 2 UNH BUY CALLS present only in HEAD (UNH 2025-12-09 and 2025-12-17; -$82.08 net, blocked in WT by the per-ticker cap), plus 0 change on the 296 common trades (s1_bypass_contribution.csv). This replaces the on-disk +$3,994 (03 section 11), which used May prices.
- **R3 HEAD set = canonical flat BUY CALLS set: TRUE** (298 = 298 identical (ticker, entry_date); HEAD trades only BUY CALLS). R3 differs from flat BUY CALLS only through sizing (uniform $380 vs flat $200 budget).

**Commission and exit-friction sensitivity** (s1_commission_friction.csv). Commissions are $0.65 x 4 leg-sides x contracts. Exit friction is 1.5% of each leg's BS exit mark.

| set | P&L | commissions | after commissions | % of P&L | + exit friction | after both | % of P&L |
|---|---|---|---|---|---|---|---|
| flat | -19,743.51 | 1,248.00 | -20,991.51 | 6.3 | 8,456.42 | -29,447.93 | 49.2 |
| R3 HEAD | 10,216.57 | 904.80 | 9,311.77 | 8.9 | 6,814.30 | 2,497.47 | 75.6 |
| R3 WT | 13,183.91 | 949.00 | 12,234.91 | 7.2 | 7,865.20 | 4,369.71 | 66.9 |
| WF | 8,340.87 | 756.60 | 7,584.27 | 9.1 | 6,048.81 | 1,535.46 | 81.6 |

## 2. Signal test on underlying returns (U3)

**Holding period** (flat BUY CALLS, n=298; s2_days_held.csv): calendar days held median 14 (IQR 12-14, range 2-17); trading days median **9** (IQR 8-10, range 2-10). Horizons tested: h = 1, 5, 9, 10. No forward observation runs past the data end (snapshot runs to 2026-10-09); 0 dropped.

**Panel.**
- 2,127 ticker-days in 2025-05-05..2026-05-04 with both engine-equivalent sentiment and a trading-day close.
- Weekend/holiday sentiment rows are dropped by the inner join, as in the engine: AAPL 68, NVDA 42, JPM 101, XOM 95, UNH 93, WMT 109, IWM 113, GLD 89, TLT 75, SPY 76.
- Per-ticker n (low-RV / low-RV bullish): AAPL 154 (131/23), NVDA 100 (92/34), JPM 228 (175/45), XOM 243 (140/68), UNH 241 (138/37), WMT 237 (138/44), IWM 247 (208/4), GLD 246 (84/31), TLT 248 (185/10), SPY 183 (166/7).
- Buckets and regime use the strict rules from 03 section 3.

**Low-RV regime, mean forward return** (s2_group_table.csv has n, n_dates, median and hit rate for every cell):

| h | bullish (n=303, 162 dates) | neutral (1000) | bearish (154) | all low-RV (1457) | all days, all buckets (2127) |
|---|---|---|---|---|---|
| 1 | +0.087% (hit 56.8%) | +0.084% | +0.234% | +0.101% | +0.118% |
| 5 | +0.897% (62.7%) | +0.613% | +0.376% | +0.647% | +0.643% |
| 9 | +1.788% (63.4%) | +1.138% | +0.535% | +1.209% | +1.218% |
| 10 | +1.890% (67.3%) | +1.284% | +0.358% | +1.312% | +1.329% |

**Low-RV adds nothing.** The low-RV unconditional mean (+1.209% at 9d) equals the all-days mean (+1.218%). The base return available to any BUY CALLS entry in this window is the market's drift.

**Contrasts within low-RV, pooled** (block bootstrap by date, blocks of h trading days, 2,000 resamples, seed 0; s2_differences_bootstrap.csv):

| variant | h | bullish - neutral [95% CI] | bullish - all low-RV [95% CI] |
|---|---|---|---|
| full | 1 | +0.003% [-0.216, +0.215] | -0.013% [-0.187, +0.154] |
| full | 5 | +0.284% [-0.163, +0.715] | +0.250% [-0.093, +0.584] |
| full | 9 | **+0.651% [+0.034, +1.279]** | **+0.579% [+0.083, +1.103]** |
| full | 10 | +0.605% [-0.104, +1.287] | +0.577% [-0.008, +1.168] |
| leak-free | 1 | -0.075% [-0.394, +0.225] | -0.015% [-0.200, +0.162] |
| leak-free | 5 | +0.815% [-0.042, +1.757] | **+0.610% [+0.099, +1.165]** |
| leak-free | 9 | +0.544% [-1.029, +1.926] | +0.689% [-0.215, +1.559] |
| leak-free | 10 | +0.531% [-1.145, +1.883] | +0.758% [-0.289, +1.715] |
| momentum (up5 - down5 / up5 - all) | 1 | -0.028% [-0.181, +0.116] | -0.011% [-0.071, +0.045] |
| momentum | 5 | -0.192% [-0.612, +0.264] | -0.075% [-0.244, +0.101] |
| momentum | 9 | -0.368% [-1.251, +0.492] | -0.144% [-0.479, +0.194] |
| momentum | 10 | -0.296% [-1.256, +0.667] | -0.116% [-0.491, +0.257] |

**Reading.**
- 2 of 8 full-sample pooled contrasts (both at h = 9, the median hold) and 1 of 8 leak-free contrasts exclude zero. The point estimates are positive at h >= 5. There is no multiplicity correction across 4 horizons x 2 contrasts x 3 variants.
- **Bullish sentiment shows a weak, marginal incremental forward return of about +0.6% over 9-10 days, and the CIs touch or cross zero.** It does not survive cleanly.
- Trailing 5-day momentum adds nothing (estimates negative, all CIs include zero), so the sentiment effect is not simply a momentum proxy.
- Per ticker (40 contrasts per variant): 4/40 exclude zero for full sentiment, in both directions (SPY h=1 +; JPM h=5/9/10 negative). Leak-free: 8/32 and 7/32.
- Leak-free subset: only 328 of 2,127 ticker-days have zero articles timestamped 16:00 or later; 74 of them are low-RV bullish. 15 ticker-days with no chunk-article record are excluded from it.

**Correlations of daily sentiment** (s2_correlations.csv; Pearson / Spearman):

| scope | trailing 1d | trailing 5d | fwd 1 | fwd 5 | fwd 9 | fwd 10 |
|---|---|---|---|---|---|---|
| all days (n=2127) | 0.228 / 0.229 | 0.200 / 0.207 | 0.003 / 0.007 | 0.031 / 0.019 | 0.060 / 0.051 | 0.072 / 0.064 |
| low-RV (n=1457) | 0.235 / 0.216 | 0.211 / 0.222 | -0.011 / -0.005 | 0.049 / 0.049 | 0.100 / 0.087 | 0.114 / 0.101 |

Sentiment co-moves with the **trailing** return (r about 0.23, consistent with news describing price moves already made, and with D2-3) about 2-4x more strongly than with any forward return.

## 3. Leak concentration (U4; s3_leak_concentration.csv)

Entry-day share of articles timestamped 16:00 ET or later (redup_backfill dedup):

| set | bucket | n | total P&L | mean / trade | win rate |
|---|---|---|---|---|---|
| flat BUY CALLS | none | 72 | 3,974.78 | 55.21 | 0.681 |
| | >0 and <50% | 206 | 3,909.03 | 18.98 | 0.519 |
| | >=50% | 19 | 282.07 | 14.85 | 0.579 |
| | no article record | 1 | 43.96 | 43.96 | 1.000 |
| flat BUY PUTS | none | 31 | -7,705.46 | -248.56 | 0.226 |
| | <50% | 104 | -18,498.34 | -177.87 | 0.240 |
| | >=50% | 18 | -429.89 | -23.88 | 0.333 |
| | no record | 1 | -1,319.66 | -1,319.66 | 0 |
| WF BUY CALLS | none | 58 | 3,532.82 | 60.91 | 0.672 |
| | <50% | 172 | 4,702.71 | 27.34 | 0.529 |
| | >=50% | 18 | 61.38 | 3.41 | 0.556 |
| | no record | 1 | 43.96 | 43.96 | 1.000 |

**P&L is not concentrated in leak-exposed trades.** Trades with no after-close articles have the highest mean P&L. The D2-3 leak exists, but this evidence doesn't show it inflating BUY CALLS P&L. The effect of moving after-close articles to d+1 is **not computable offline** (no per-article scores stored; FinBERT prohibited).

## 4. Beta (U4)

Total return 2025-05-08 to 2026-05-04 (adjusted closes; s4_ticker_total_returns.csv): NVDA +69.2%, XOM +49.9%, AAPL +40.8%, IWM +39.6%, GLD +36.1%, WMT +35.0%, SPY +28.5%, JPM +23.7%, TLT +2.2%, UNH -1.1%.

| metric (s4_beta.csv) | flat BUY CALLS (n=298) | WF BUY CALLS (n=249) |
|---|---|---|
| corr(P&L $, underlying return over hold) | **0.914** | **0.854** |
| Spearman | 0.947 | 0.934 |
| corr(P&L, SPY return over hold) | 0.204 | 0.195 |
| share of trades with underlying up | 67.1% | 68.3% |
| win rate when underlying up / down | 84.0% / **0.0%** | 82.9% / **0.0%** |
| top-2 tickers | XOM + GLD = **71.1%** | XOM + GLD = **79.7%** |

**BUY CALLS P&L is essentially the sign and size of the underlying's 9-day move**, entered in a year when 9 of 10 names rose. No trade made money when its underlying fell. Two tickers, XOM and GLD, carry 71-80% of the total.

## 5. Performance recompute (U5, U6)

Capital bases:
- flat sizes from a $10k x 2% budget with a 1-contract floor (engine.py:341-347). On $10k the flat P&L is -197% of capital, which shows that flat is not a capital-consistent strategy. The $100k figure (-19.7%) is equally arbitrary.
- R3 and WF use $100k (`KELLY_BACKTEST_NOTIONAL`).
- Daily-series Sharpe is scale-invariant in capital.
- **The daily series is an approximation:** each trade's P&L is booked on its exit date, with zero on all other trading days; there is no daily mark-to-market (D4a-5).

### 5a-5d. Canonical logs (s5_performance.csv)

| set | trades | P&L | Sharpe repo (all rows) | repo (taken only) | daily exit-series | daily boot 95% CI | analytic 95% CI | DD repo order | DD date-ordered |
|---|---|---|---|---|---|---|---|---|---|
| flat | 452 | -19,743.51 | -0.920 | -0.975 | -1.933 | [-3.83, +0.29] incl. 0 | [-3.81, -0.05] excl. 0 | -28,819.76 | -25,056.86 |
| R3 HEAD | 298 | 10,216.57 | 1.281 | 1.689 | 3.082 | [+0.74, +4.98] **excl. 0** | [+1.12, +5.05] excl. 0 | -1,396.04 | -2,577.84 |
| R3 WT | 315 | 13,183.91 | 0.858 | 1.093 | 2.353 | [+0.15, +4.15] excl. 0 | [+0.39, +4.31] excl. 0 | -5,362.46 | -4,585.18 |
| WF | 249 | 8,340.87 | 1.274 | 1.640 | 2.626 | [+0.11, +4.50] excl. 0 | [+0.66, +4.59] excl. 0 | -2,106.65 | -2,577.82 |

The repo-method column reproduces the 4a/report values exactly (flat -0.9201, R3 HEAD 1.2812, R3 WT 0.8585, WF 1.2739, and their DDs). Daily windows: 276 trading days (flat) and 255 (others), 2025-05-08 to the last exit.

**After commissions + exit friction** (U6; s5b_after_costs.csv):

| set | P&L | daily Sharpe | boot 95% CI | analytic 95% CI |
|---|---|---|---|---|
| flat | -29,447.93 | -2.935 | [-4.80, -0.84] excl. 0 | [-4.82, -1.05] |
| R3 HEAD | 2,497.47 | 0.840 | [-1.78, +3.06] **incl. 0** | [-1.11, +2.79] |
| R3 WT | 4,369.71 | 0.842 | [-1.49, +2.94] incl. 0 | [-1.11, +2.79] |
| WF | 1,535.46 | 0.541 | [-2.16, +2.70] incl. 0 | [-1.41, +2.49] |

**Per-trade statistics (5c)**, with n_eff from section 6:

| set | mean | std | t naive | n_eff | t_eff |
|---|---|---|---|---|---|
| flat | -43.68 | 317.92 | -2.92 | 90.4 | -1.31 |
| R3 HEAD | 34.28 | 144.07 | 4.11 | 85.8 | **2.20** |
| R3 WT | 41.85 | 271.76 | 2.73 | 83.4 | 1.41 |
| WF | 33.50 | 145.00 | 3.65 | 71.1 | **1.95** |

### 5e. Sensitivity: canonical minus original logs (s5e_canonical_minus_original.csv)

The R3 HEAD original is a **proxy**: the on-disk WT `_kelly` logs with UNH BUY PUTS zeroed, because the true HEAD logs were overwritten (04a section 6.2).

| set | dP&L | dSharpe repo | dSharpe taken | dSharpe daily | dCI lo / hi (boot) | dDD repo | dDD date |
|---|---|---|---|---|---|---|---|
| flat | -760.21 | -0.021 | -0.019 | -0.099 | -0.121 / -0.277 | -1,771.58 | -647.25 |
| R3 HEAD (proxy) | +304.84 | +0.083 | +0.101 | -0.094 | -0.101 / -0.503 | +100.93 | +82.04 |
| R3 WT | -722.22 | -0.050 | -0.066 | -0.195 | -0.094 / -0.481 | -186.62 | -572.82 |
| WF | +554.65 | +0.137 | +0.165 | +0.003 | -0.123 / -0.412 | -184.71 | +82.05 |

Original-log levels (s5_performance.csv, logs=original):
- flat: -0.899 repo, -1.835 daily [-3.70, +0.57]
- R3 HEAD proxy: 1.198 / 3.176 [+0.84, +5.48]
- R3 WT: 0.908 / 2.548 [+0.25, +4.63]
- WF: 1.137 / 2.622 [+0.24, +4.91]

Repo-method DD for the original WF is -1,921.94 vs the reported -1,909.12: a $12.82 tie-order difference from the non-stable `sort_values("entry_date")` (audit_walkforward.py:314) on same-date rows. The rest match exactly.

**Immaterial input changes** (dividend back-adjustment, 17 completed trades) move P&L by up to 9% and WF repo Sharpe by +0.14, and they flip the WF verdict (04a section 6.1). Daily-series Sharpe moves by less than 0.2.

### 5f. Versus PROJECT_STATE / reports

| result | reported (PROJECT_STATE.md:686-691 / reports) | canonical, repo method | canonical, daily series (pre-cost) | canonical, after costs |
|---|---|---|---|---|
| flat | -18,983 / -0.90 / DD -27,048 | -19,744 / -0.92 / -28,820 | -1.93 | -2.94 |
| R3 HEAD | +9,697 / 1.17 / DD -1,550 | +10,217 / 1.28 / -1,396 | 3.08 | 0.84 (CI incl. 0) |
| R3 WT | +13,906 / 0.908 / DD -5,176 | +13,184 / 0.86 / -5,362 | 2.35 | 0.84 (CI incl. 0) |
| WF | +7,786 / 1.14 / DD -1,909 | +8,341 / 1.27 / -2,107 | 2.63 | 0.54 (CI incl. 0) |
| OOS test fold | +2,077 / 0.98 | +2,970 / 1.36 (4a d2) | not recomputed | not recomputed |

The repo's sqrt(252/5) per-row Sharpe **understates** the daily-series Sharpe of the pre-cost P&L (zero rows and the wrong annualization both pull it down). The pre-cost series is **not** the relevant one, however: costs reduce the Kelly-path Sharpe to 0.5-0.8, with CIs including zero.

## 6. Effective independent observations (U5; s6_effective_n.csv, s6_neff_cross_ticker.csv)

| item | flat | R3 HEAD | R3 WT | WF |
|---|---|---|---|---|
| avg concurrent open positions, portfolio | 22.84 | 10.04 | 11.36 | 8.38 |
| per ticker (max) | TLT 5.40 | XOM 2.32 | UNH 2.50 | XOM 1.96 |
| trades non-overlapping in time (greedy per ticker) | 117 | 111 | 108 | 92 |
| n_eff = non-overlapping x N_eff(10) / 10 | 90.4 | 85.8 | 83.4 | 71.1 |

- Cross-ticker N_eff (eigenvalue entropy, scripts/correlation_matrix.py:95-104) over the full window (248 days): **7.73** (mean pairwise correlation 0.126). Over the 60 trading days to 2026-04-24 it is **6.67**, which reproduces PROJECT_STATE's 6.66.
- Method: count the trades that don't overlap in time within each ticker, then scale by N_eff / number of traded tickers to account for cross-sectional correlation.
- Assumptions: non-overlapping trades in one ticker are independent; correlation is constant; within-ticker serial correlation of returns is ignored. The estimate is approximate and probably optimistic, given the common market-drift factor shown in section 4.

## 7. Exposure (D3-1) (U5; s7_exposure.csv, s7_open_risk_daily_*.csv)

Open risk = `total_risk` (contracts x max loss x $100), open from entry until the exit date (engine.py:774-779 semantics), summed across tickers:

| set | peak % of $100k | peak date | mean % (window) | days > 6% | max single-ticker % |
|---|---|---|---|---|---|
| R3 HEAD | 6.77 | 2025-10-21 | 2.61 | 8 | 2.41 |
| R3 WT | **11.12** | 2025-10-21 | 4.47 | **86** | **7.30** (UNH; MIN_CONTRACTS floor) |
| WF | 6.77 | 2025-10-21 | 2.19 | 8 | 2.41 |

The "global" 6% cap is not enforced across tickers. It is exceeded on 8 days (HEAD/WF) and 86 days (WT). The WT bypass also breaches the per-ticker 6%.

## 8. Exits and friction (D3-9) (U4; s8_exit_mix.csv, s8_friction.csv)

| strategy / exit reason | flat | R3 HEAD | R3 WT | WF |
|---|---|---|---|---|
| BULL_CALL_DEBIT profit_target | 105 | 105 | 105 | 90 |
| BULL_CALL_DEBIT stop_loss | 19 | 19 | 19 | 18 |
| BULL_CALL_DEBIT time_stop | 174 | 174 | 172 | 141 |
| BEAR_PUT_DEBIT profit_target / stop_loss / time_stop | 25 / 66 / 63 | -- | 10 / 3 / 6 | -- |

No canonical trade exits by `expiration` (all 17 truncations resolved, section 11).

| set | days_held = 0 | entry friction $ | gross P&L pre-friction | entry friction % of gross | exit friction $ | P&L with exit friction |
|---|---|---|---|---|---|---|
| flat | 0 (min held 2) | 7,327.58 | -12,415.93 | 59.0 | 8,456.42 | -28,199.93 |
| R3 HEAD | 0 | 5,116.87 | 15,333.44 | 33.4 | 6,814.30 | 3,402.27 |
| R3 WT | 0 | 5,754.86 | 18,938.77 | 30.4 | 7,865.20 | 5,318.71 |
| WF | 0 | 4,522.58 | 12,863.45 | 35.2 | 6,048.81 | 2,292.06 |

- Same-day exits never occurred, so D3-9's day-0 concern is moot on these logs.
- Entry friction comes from the logged leg prices (long/1.015, short/0.985).
- Exit friction comes from re-derived leg marks validated in section 1.
- **Time stops dominate** (58% of BUY CALLS exits). Profit targets are 35%.

## 9. Earnings exposure (D3) (U4; s9_*.csv)

Provenance: Yahoo earnings-page scrape via the 4a fallback parser (04a section 8 handoff); realized dates; single names only. ETFs (IWM, GLD, TLT, SPY) have no earnings dates and are excluded. The window rule is the live rule in calendar days (03 section 8). IV_CRUSH can't apply, since BUY CALLS entry requires RV rank < 0.30 and IV_CRUSH needs >= 0.80.

| set | single-name trades | entered in SUPPRESS window | P&L in window | P&L outside | in-window with after-close articles |
|---|---|---|---|---|---|
| flat BUY CALLS (= R3 HEAD set) | 248 | 14 | -22.60 | 5,380.79 | 13 |
| WF BUY CALLS | 206 | 14 | -22.60 | 5,914.57 | 13 |

In-window by ticker: AAPL 5 (+$408), JPM 3 (-$49), NVDA 1 (-$202), plus others (s9_trades_in_window_*.csv). Applying the live earnings filter to the backtest would remove 14 trades with about $0 net P&L, so D3 doesn't materially affect this result.

## 10. OOS boundary (D3-8) (U4; s10_oos_boundary.csv)

The canonical train fold (entry <= 2025-12-22) has **30 accepted trades exiting after the cutoff** (BUY PUTS 17, BUY CALLS 13).

| train stats | BUY CALLS count / f* | BUY PUTS count / f* |
|---|---|---|
| as the audit fits them | 230 / +0.2295 | 107 / -0.7096 |
| excluding the 30 spill-over trades | 217 / +0.2125 | 90 / -0.6914 |

**Neither decision changes:** BUY PUTS stays blocked and BUY CALLS still passes. D3-8 is a methodology defect with no effect on this result.

## 11. Truncated trades and width-0 (D3-3) (U4; s11_*.csv)

The 17 trades truncated at 2026-05-04 in the original flat logs, against their canonical outcomes:

| ticker | entry | signal | orig exit / P&L | canonical exit / P&L | diff |
|---|---|---|---|---|---|
| AAPL | 04-24, 04-28, 04-30, 05-01 | BUY CALLS | expiration: 38.81, 40.15, 31.71, -56.69 | profit_target: 141.45, 137.12, 126.31, 127.14 | +478.04 |
| NVDA | 04-24 | BUY CALLS | -113.86 | time_stop 43.96 | +157.82 |
| JPM | 04-21, 04-22 | BUY CALLS | -89.42, -88.39 | time_stop -72.29, -9.33 | +96.19 |
| UNH | 04-21, 04-22, 04-27, 04-28, 04-30 | BUY CALLS | 85.72, 41.99, 32.27, -34.17, -51.87 | 55.00, 30.04, 120.74, 109.34, 113.10 | +354.28 |
| SPY | 04-23 | BUY CALLS | 13.44 | profit_target 109.01 | +95.57 |
| TLT | 04-30, 05-04 | BUY PUTS | -13.64, -2.86 | 3.00, -74.19 | -54.69 |
| SPY | 04-24, 04-28 | BUY PUTS | -212.57, -298.24 | stop_loss -1,483.72, -1,319.66 | -2,292.57 |

**Net -$1,165.36** (BUY CALLS +$1,181.90; BUY PUTS -$2,347.26). Dates are 2026-MM-DD.

Width-0 rejections ("degenerate width=0"): canonical TLT 2, WMT 1, XOM 2 (all BUY CALLS); original TLT 6 (5 BC + 1 SELL CALLS), WMT 2, XOM 1.

**Share of BUY CALLS P&L from sub-$100-era tickers TLT, WMT, XOM:**

| set | total | TLT + WMT + XOM | share | excluding them |
|---|---|---|---|---|
| flat BUY CALLS | 8,209.84 | 3,913.87 | 47.7% | 4,295.97 |
| R3 HEAD | 10,216.57 | 6,054.46 | 59.3% | 4,162.11 |
| WF BUY CALLS | 8,340.87 | 5,240.05 | 62.8% | 3,100.82 |

## 12. Synthesis -- walk-forward BUY CALLS (+$8,340.87, 249 trades, canonical)

| factor | evidence | measured effect | direction where not measured |
|---|---|---|---|
| News look-ahead (D2-3) | sections 2, 3 | Leak-exposed trades have **lower** mean P&L ($27 / $3 vs $61 for leak-free); leak-free underlying contrast at 5d is +0.61% [+0.10, +1.17] | P&L effect of moving articles to d+1: **not computable offline** (needs FinBERT rescoring); no evidence it inflates this result |
| Beta / market drift | section 4 | corr(P&L, underlying move) 0.85; 0% wins when underlying fell; 9/10 names rose 22-69% (UNH -1%); XOM + GLD = 79.7% of P&L | -- |
| Momentum | section 2 | Trailing-5d sign adds nothing (up5 - all: -0.14% at 9d, CI includes 0) | -- |
| Low-RV condition | section 2 | Low-RV 9d mean +1.209% vs all days +1.218%: **no incremental effect** | -- |
| Sentiment condition | section 2 | +0.58% at 9d vs all low-RV [+0.08, +1.10]; at 10d [-0.01, +1.17]; at 1d and 5d no effect; 2/8 pooled contrasts exclude 0 | Marginal; multiplicity not corrected |
| Exit friction + commissions | sections 1, 8 | -$6,048.81 exit friction, -$756.60 commissions, leaving **+$1,535.46** (-81.6%) | -- |
| Same-day exits | section 8 | 0 trades | none |
| Exposure (D3-1) | section 7 | Peak 6.77% of $100k; 8 days > 6% | Slightly flatters (uncapped aggregate) |
| Earnings exposure (D3) | section 9 | 14 trades, -$22.60 | Negligible |
| OOS boundary (D3-8) | section 10 | No change to filter decisions | Negligible |
| Input sensitivity (5e) | section 5e; 04a | +$554.65 / +0.137 repo Sharpe vs original; verdict flips | -- |
| Statistical uncertainty (5d) | sections 5, 6 | Pre-cost daily Sharpe 2.63 [+0.11, +4.50]; **after costs 0.54 [-2.16, +2.70]**; t_eff 1.95 (n_eff 71) | -- |

**Bottom line.** After plausible costs, the WF BUY CALLS result is statistically indistinguishable from zero. Before costs it is explained mostly by long call exposure to a rising market, concentrated in two tickers. The sentiment condition contributes at most a marginal +0.6% over 9 days on the underlying, and the low-RV condition contributes nothing.

## 13. Defects / Open questions / Handoff notes

### Defects

| id | path:line | description | severity | how to confirm |
|---|---|---|---|---|
| D4b-1 | (strategy result) | After commissions and symmetric exit friction, R3 HEAD / R3 WT / WF Sharpe CIs all include zero; 67-82% of P&L is consumed by costs the engine omits (D4a-3) | CRITICAL (invalidates the positive real-mode headline as evidence of edge) | s5b_after_costs.csv, s1_commission_friction.csv |
| D4b-2 | (strategy result) | BUY CALLS P&L is directional beta (corr 0.85-0.91 with the underlying; 0% win on down moves); low-RV adds nothing; sentiment's incremental effect is marginal | HIGH | sections 2, 4 |
| D4b-3 | (strategy result) | Concentration: XOM + GLD carry 71-80% of BUY CALLS P&L; TLT/WMT/XOM 48-63% | HIGH | s4_pnl_by_ticker_*.csv, s11_sub100_share.csv |
| D4b-4 | scripts/audit_walkforward.py:314 | Non-stable sort on entry_date makes the repo DD depend on tie order (-$12.82 here) | LOW | section 5e |
| D4b-5 | backtest/engine.py:801 | `iv_rank` is logged at 4 dp, preventing exact audit replication of regime boundaries near 0.30 | LOW | section 1 |
| D4b-6 | (repo metrics) | Repo Sharpe and DD (D4a-2, D9) misstate risk in both directions vs the daily series; no capital-consistent return definition for flat | MEDIUM | section 5a/5b |

Earlier defects confirmed or resized here:
- D2-3 (present but not shown to inflate P&L)
- D3 (14 trades, about $0)
- D3-1 (quantified: 8 / 86 days > 6%)
- D3-8 (no decision change)
- D3-9 (0 day-0 exits; exit friction large)
- D3-3 (5 width-0 rejections canonical)
- D6 / D3-18 (bypass +$2,967 at canonical prices)

### Open questions

1. Can the after-close leak be quantified? This needs per-article FinBERT scores to recompute daily sentiment with a 16:00 cutoff; not possible under this audit's rules.
2. How do real option quotes compare with BS at RV30 (D4a-4)? Entry/exit friction assumptions (1.5% per leg) may be optimistic or pessimistic relative to real bid/ask; this needs historical chains.
3. A single 12-month bull regime: the result cannot be tested in 2008, 2020 or 2022 with the data on disk (02 section 5).

### Handoff notes for stage 6

- The only real-mode strategy that trades (BUY CALLS) shows no edge after costs that can be distinguished from zero. Its pre-cost profit is market drift in a rising year, concentrated in XOM and GLD. Sentiment adds a marginal, statistically fragile +0.6% over 9 days, and the low-RV filter adds nothing.
- BUY PUTS loses heavily in flat mode (-$27,953) and is blocked in-sample and out-of-sample. The UNH bypass (+$2,967) is in-sample selected (D3-18).
- The live path is broken independently of all this: frozen sentiment (D1, D2-1, D2-2), labels only (D5).
- All tables are reproducible from `audit/artifacts/stage4b/` with commands U1-U6 and the 4a snapshot, offline.

## Final git status check

[RAN `git status --short` ; `git diff --stat`] after writing this file:

- Tracked diff unchanged from the stage-1 start state: 12 files changed, **+480 / -218**.
- Untracked: `.claude/`, `outputs/sector_decay_analysis_real.md` (pre-existing), `audit/`.
- Stage 4b added only `audit/04b_backtest_analyses.md` and `audit/artifacts/stage4b/` (48 files: 7 scripts, 36 CSVs, 5 stdout captures).
- No network was used, nothing was installed, and nothing outside `audit/` changed.

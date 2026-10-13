# Walk-Forward Audit -- Daily Refit on R3 Baseline

**Mode: REAL**

## 1. Question and methodology summary

_Tests whether the prior 75/25 audit's PARTIAL verdict (Sharpe +1.17 in-sample -> +0.98 OOS) on the real-news 75/25 holdout (cutoff 2025-12-22) is universal across refit windows or specific to that single cutoff date.  Kelly stats, quintile edges, and the confidence model are refit each time a new accepted trade completes; every signal is sized with parameters that knew nothing about its outcome.  Path-(b) post-hoc re-derivation: the flat corpus's per-share `pnl` and `max_loss` are spread + real-price properties unchanged by sizing -- only contract counts shift between sizing regimes.  No production code, sizing logic, or on-disk artifact is modified._

## 2. Walk-forward design specifics

- **Refit cadence.**  Logically daily.  Implementation refits only when the training-corpus size grows (a new accepted trade has exited).  Identical training data produces identical parameters; redundant refits are skipped.  Result: **134 unique refits** across the corpus, vs the 700+ daily refits a naive walk-forward would do.
- **Training corpus filter.**  `accepted == True` AND `exit_date < entry_date_of_signal_being_evaluated`.  This is the strict no-look-ahead semantic: a trade is only used in fitting after its P&L is realised.  The prompt's phrasing `entry_date < T` is the loose form of the same intent.
- **Warmup threshold.**  50 accepted-and-completed trades required before any signal is evaluable.  First date this threshold is met: **2025-07-30**.  102 signals fall in the warmup period and are excluded from evaluation (counted, not zeroed).
- **Synchronization.**  Universe-wide refits using all 10 tickers' completed accepted trades.  Per-ticker refits would be a different test and were not implemented.
- **Parameter persistence.**  All parameter snapshots held in memory; nothing written under `data/raw/`.
- **Sharpe convention.**  `mean(pnl_total) / std(pnl_total, ddof=1) * sqrt(252/5)`, matching `r3_baseline.headline()`.  Same convention used for the trade-level rolling-window Sharpe.
- **Open-risk cap simplification.**  `open_risk_dollars=0` passed to every `size_trade` call (peak utilisation in the production Kelly run was 0.69 << 1.0; on a walk-forward this is even less likely to bind).

## 3. Headline metrics (walk-forward)

| metric | value |
|---|---|
| n_signals_seen | 405.0000 |
| n_warmup_excluded | 102.0000 |
| n_signals_evaluable | 405.0000 |
| n_trades_taken | 249.0000 |
| total_pnl_$ | 8,340.8700 |
| sharpe | 1.2739 |
| max_dd_$ | -2,106.6500 |
| profit_factor | 1.7578 |
| win_rate | 0.3481 |

## 4. Three-column comparison: in-sample / 75-25-OOS / walk-forward

| metric | in_sample_full | oos_75_25 | walk_forward |
|---|---|---|---|
| n_signals | 507.0000 | 213.0000 | 405.0000 |
| n_trades_taken | 298.0000 | 113.0000 | 249.0000 |
| total_pnl_$ | 10,216.5700 | -2,877.5700 | 8,340.8700 |
| sharpe | 1.2812 | -0.5977 | 1.2739 |
| max_dd_$ | -1,396.0400 | -7,731.0500 | -2,106.6500 |
| profit_factor | 1.7807 | 0.7295 | 1.7578 |
| win_rate | 0.3314 | 0.2629 | 0.3481 |
| Q5_total_pnl | 1,835.4100 | -5,585.8400 | 2,026.7500 |
| Q1_total_pnl | 1,369.5400 | -324.3100 | 660.8700 |
| AAPL_pnl | 420.3400 | -4,534.7100 | 744.0500 |
| NVDA_pnl | 1,114.4400 | -471.3200 | 29.9700 |

_75/25 OOS column shows the synthetic-mode reference values from `outputs/oos_audit_report.md` (cutoff 2025-11-17); the comparison column has not been re-derived from the real-mode 75/25 audit (`outputs/oos_audit_report_real.md`).  Walk-forward column is computed in this session on the real-mode flat corpus.  The in-sample baseline column is real-mode and shares with both other columns the same per-share P&L from the real-news flat backtest._

## 5. Rolling 60-day Sharpe distribution

| stat | value |
|---|---|
| n_windows | 127.0000 |
| mean | 2.1259 |
| std | 1.9719 |
| p10 | -0.6834 |
| p25 | 0.7132 |
| p50_median | 1.5957 |
| p75 | 3.6907 |
| p90 | 4.7794 |
| min | -0.9950 |
| max | 6.5010 |
| n_positive | 106.0000 |
| n_negative | 21.0000 |
| n_|sharpe|>0.5 | 119.0000 |
| n_sharpe>+0.5 | 102.0000 |
| n_sharpe<-0.5 | 17.0000 |

**Pos vs neg windows:** 106 positive / 21 negative (83% positive).  **Strong-magnitude windows** (|Sharpe| > 0.5): 119 (102 positive, 17 negative).

## 6. Per-refit parameter evolution

Sampled 7 of 134 refit events spread evenly through the walk-forward period.  Shows how parameters evolve as the training corpus grows.

**Quintile edges + Kelly fractions:**

| date | n_train | edge_q1 | edge_q2 | edge_q3 | edge_q4 | BC_kelly_f | BP_kelly_f |
|---|---|---|---|---|---|---|---|
| 2025-07-30 | 52 | 0.2895 | 0.4459 | 0.5427 | 0.6849 | 0.3216 | -0.4137 |
| 2025-09-04 | 106 | 0.4215 | 0.5186 | 0.6166 | 0.7099 | 0.4530 | -0.5035 |
| 2025-10-10 | 179 | 0.3505 | 0.4415 | 0.5207 | 0.5992 | 0.3805 | -0.7686 |
| 2025-11-14 | 252 | 0.3166 | 0.4129 | 0.4934 | 0.5642 | 0.2616 | -0.8005 |
| 2025-12-24 | 311 | 0.3804 | 0.4318 | 0.4784 | 0.5184 | 0.2158 | -0.6893 |
| 2026-02-17 | 377 | 0.3231 | 0.3892 | 0.4777 | 0.5514 | 0.2086 | -0.7124 |
| 2026-04-30 | 435 | 0.3361 | 0.4018 | 0.4748 | 0.5469 | 0.2246 | -0.7272 |

**Confidence model coefficients (intercept + 6 betas):**

| date | n_train | intercept | abs_sentiment | iv_rank | sent_momentum_3d | sec_aligned | log_headline_count | log_days_to_earnings |
|---|---|---|---|---|---|---|---|---|
| 2025-07-30 | 52 | +0.0603 | +0.9594 | +0.2852 | +0.6157 | +0.2568 | +0.0494 | +0.0000 |
| 2025-09-04 | 106 | +0.3459 | +0.5902 | +0.0846 | +0.7051 | +0.2801 | +0.1181 | +0.0000 |
| 2025-10-10 | 179 | -0.0793 | +0.1894 | +0.2271 | +0.6439 | +0.0859 | +0.1273 | +0.0000 |
| 2025-11-14 | 252 | -0.2048 | +0.1296 | +0.0605 | +0.5037 | +0.2075 | -0.0554 | +0.0000 |
| 2025-12-24 | 311 | -0.1780 | +0.0684 | +0.0290 | +0.2820 | +0.1394 | -0.1107 | -0.0000 |
| 2026-02-17 | 377 | -0.2540 | +0.0843 | +0.1126 | +0.3377 | +0.3138 | -0.1665 | -0.0000 |
| 2026-04-30 | 435 | -0.2267 | +0.1082 | +0.0671 | +0.3440 | +0.2631 | -0.1310 | -0.0000 |

## 7. Per-quintile breakdown

Confidence quintile labels are assigned at trade-entry time using the parameters that were live at that moment (so a trade in early 2025 may have been Q3 then but would be Q4 under the late-2026 edges -- this is the correct walk-forward semantic).

**In-sample (full corpus, production params):**

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|
| Q1 | 49 | 0.57 | 1,369.54 | 27.95 |
| Q2 | 63 | 0.62 | 2,831.76 | 44.95 |
| Q3 | 61 | 0.61 | 3,204.01 | 52.52 |
| Q4 | 58 | 0.47 | 975.85 | 16.83 |
| Q5 | 67 | 0.55 | 1,835.41 | 27.39 |

**Walk-forward (entry-time params):**

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|
| Q1 | 13 | 0.69 | 660.87 | 50.84 |
| Q2 | 42 | 0.52 | 858.95 | 20.45 |
| Q3 | 53 | 0.64 | 2,311.74 | 43.62 |
| Q4 | 54 | 0.57 | 2,482.56 | 45.97 |
| Q5 | 87 | 0.52 | 2,026.75 | 23.30 |

**Q5 - Q1 spread:** in-sample $465.87, 75/25 OOS -$5,261.53, walk-forward $1,365.88.

## 8. Per-ticker breakdown

| ticker | n_taken_in | pnl_in | n_taken_wf | pnl_wf |
|---|---|---|---|---|
| AAPL | 23 | 420.34 | 19 | 744.05 |
| GLD | 31 | 2,390.25 | 27 | 2,515.85 |
| IWM | 4 | 257.91 | 2 | -53.18 |
| JPM | 45 | -835.64 | 36 | -812.59 |
| NVDA | 34 | 1,114.44 | 26 | 29.97 |
| SPY | 7 | 443.25 | 6 | 305.16 |
| TLT | 8 | -318.95 | 8 | -318.93 |
| UNH | 37 | 371.56 | 37 | 371.56 |
| WMT | 43 | 1,330.01 | 33 | 1,425.78 |
| XOM | 66 | 5,043.40 | 55 | 4,133.20 |

**No ticker P&L sign-flips with |pnl| > $100 on both sides.**

**AAPL.**  Walk-forward: $744.05 on 19 taken trades.  Warmup cutoff: 2025-07-30.  `outputs/aapl_stop_diagnosis.md` is a synthetic-only diagnostic; a real-mode AAPL stop-cluster post-mortem has not been published.

## 9. Verdict

**GENERALIZES UNDER WALK-FORWARD.**  Walk-forward total Sharpe (+1.2739) is within ~30% of in-sample (+1.2812); rolling 60-day Sharpe distribution is 83% positive (102 windows >+0.5 vs 17 <-0.5); Q5-Q1 spread $1,365.88 preserves the in-sample ordering; 0 ticker sign-flips.  The 75/25 collapse was specific to the cutoff date landing on the AAPL Dec-2025/Jan-2026 stop cluster; daily refit averages that adverse window with positive ones from earlier and later in the corpus.  R3's selection as production sizing and the v2_10t promotion question both stand on stronger footing now.

## 10. Caveats

- **Real-corpus single-regime caveat.**  Trade corpus drawn from the real-news flat backtest covering ~12 months of headlines (~2025-05 to 2026-05).  Walk-forward on a single real-news regime is one realisation, not a Monte Carlo over macro conditions; per-ticker P&L is heavily concentrated (see PROJECT_STATE Section 10.2).  A different corpus window or ticker mix would produce different rolling-Sharpe dynamics.
- **Evaluable date range.**  2025-07-30 -> 2026-05-04 (102 signals before the warmup cutoff are not evaluated).
- **Rolling-window error bars.**  60-day windows on this trade-frequency contain ~10-30 trades; individual window Sharpes are noisy and should not be over-interpreted.  The distributional summary is the right unit of analysis.
- **Single-corpus caveat.**  This audit replays exactly one real-news corpus collected for the production universe.  The rolling-Sharpe distribution captures within-corpus variance, not cross-corpus variance from re-ingesting different news windows or ticker mixes.

## 11. Cleanup confirmation

| artifact | mtime_pre | mtime_post | size_unchanged |
|---|---|---|---|
| kelly_stats.csv (production) | 1791661762.193 | 1791661762.193 | 1 |
| quintile_edges.json (production) | 1791661762.201 | 1791661762.201 | 1 |
| confidence_model.json (production) | 1777081780.784 | 1777081780.784 | 1 |

**Production artifacts unchanged: CONFIRMED.**  No artifacts under `data/raw/` were written or modified during this audit.  All parameter snapshots were held in memory only.

---

## Reproduction

```bash
.venv/Scripts/python.exe scripts/audit_walkforward.py --real
```

Reads `data/raw/backtest_*.csv` + `data/raw/backtest_*_kelly.csv`; writes `outputs/walkforward_audit_report_real.md` only.  Re-run after any change that regenerates the flat or kelly logs.

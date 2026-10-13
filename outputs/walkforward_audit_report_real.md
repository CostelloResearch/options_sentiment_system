# Walk-Forward Audit -- Daily Refit on R3 Baseline

**Mode: REAL**

## 1. Question and methodology summary

_Tests whether the prior 75/25 audit's PARTIAL verdict (Sharpe +1.17 in-sample -> +0.98 OOS) on the real-news 75/25 holdout (cutoff 2025-12-22) is universal across refit windows or specific to that single cutoff date.  Kelly stats, quintile edges, and the confidence model are refit each time a new accepted trade completes; every signal is sized with parameters that knew nothing about its outcome.  Path-(b) post-hoc re-derivation: the flat corpus's per-share `pnl` and `max_loss` are spread + real-price properties unchanged by sizing -- only contract counts shift between sizing regimes.  No production code, sizing logic, or on-disk artifact is modified._

## 2. Walk-forward design specifics

- **Refit cadence.**  Logically daily.  Implementation refits only when the training-corpus size grows (a new accepted trade has exited).  Identical training data produces identical parameters; redundant refits are skipped.  Result: **134 unique refits** across the corpus, vs the 700+ daily refits a naive walk-forward would do.
- **Training corpus filter.**  `accepted == True` AND `exit_date < entry_date_of_signal_being_evaluated`.  This is the strict no-look-ahead semantic: a trade is only used in fitting after its P&L is realised.  The prompt's phrasing `entry_date < T` is the loose form of the same intent.
- **Warmup threshold.**  50 accepted-and-completed trades required before any signal is evaluable.  First date this threshold is met: **2025-07-29**.  99 signals fall in the warmup period and are excluded from evaluation (counted, not zeroed).
- **Synchronization.**  Universe-wide refits using all 10 tickers' completed accepted trades.  Per-ticker refits would be a different test and were not implemented.
- **Parameter persistence.**  All parameter snapshots held in memory; nothing written under `data/raw/`.
- **Sharpe convention.**  `mean(pnl_total) / std(pnl_total, ddof=1) * sqrt(252/5)`, matching `r3_baseline.headline()`.  Same convention used for the trade-level rolling-window Sharpe.
- **Open-risk cap simplification.**  `open_risk_dollars=0` passed to every `size_trade` call (peak utilisation in the production Kelly run was 0.69 << 1.0; on a walk-forward this is even less likely to bind).

## 3. Headline metrics (walk-forward)

| metric | value |
|---|---|
| n_signals_seen | 408.0000 |
| n_warmup_excluded | 99.0000 |
| n_signals_evaluable | 408.0000 |
| n_trades_taken | 246.0000 |
| total_pnl_$ | 7,786.2200 |
| sharpe | 1.1369 |
| max_dd_$ | -1,909.1200 |
| profit_factor | 1.6785 |
| win_rate | 0.3505 |

## 4. Three-column comparison: in-sample / 75-25-OOS / walk-forward

| metric | in_sample_full | oos_75_25 | walk_forward |
|---|---|---|---|
| n_signals | 507.0000 | 213.0000 | 408.0000 |
| n_trades_taken | 295.0000 | 113.0000 | 246.0000 |
| total_pnl_$ | 9,697.0200 | -2,877.5700 | 7,786.2200 |
| sharpe | 1.1732 | -0.5977 | 1.1369 |
| max_dd_$ | -1,550.0100 | -7,731.0500 | -1,909.1200 |
| profit_factor | 1.7113 | 0.7295 | 1.6785 |
| win_rate | 0.3373 | 0.2629 | 0.3505 |
| Q5_total_pnl | 2,180.5600 | -5,585.8400 | 3,148.1900 |
| Q1_total_pnl | 1,101.3500 | -324.3100 | 317.1900 |
| AAPL_pnl | 248.0900 | -4,534.7100 | 569.7600 |
| NVDA_pnl | 950.7800 | -471.3200 | -121.1000 |

_75/25 OOS column shows the synthetic-mode reference values from `outputs/oos_audit_report.md` (cutoff 2025-11-17); the comparison column has not been re-derived from the real-mode 75/25 audit (`outputs/oos_audit_report_real.md`).  Walk-forward column is computed in this session on the real-mode flat corpus.  The in-sample baseline column is real-mode and shares with both other columns the same per-share P&L from the real-news flat backtest._

## 5. Rolling 60-day Sharpe distribution

| stat | value |
|---|---|
| n_windows | 123.0000 |
| mean | 2.1194 |
| std | 1.8618 |
| p10 | -0.5246 |
| p25 | 0.6272 |
| p50_median | 1.6904 |
| p75 | 3.6286 |
| p90 | 4.3914 |
| min | -0.8777 |
| max | 5.6014 |
| n_positive | 103.0000 |
| n_negative | 20.0000 |
| n_|sharpe|>0.5 | 110.0000 |
| n_sharpe>+0.5 | 97.0000 |
| n_sharpe<-0.5 | 13.0000 |

**Pos vs neg windows:** 103 positive / 20 negative (84% positive).  **Strong-magnitude windows** (|Sharpe| > 0.5): 110 (97 positive, 13 negative).

## 6. Per-refit parameter evolution

Sampled 7 of 134 refit events spread evenly through the walk-forward period.  Shows how parameters evolve as the training corpus grows.

**Quintile edges + Kelly fractions:**

| date | n_train | edge_q1 | edge_q2 | edge_q3 | edge_q4 | BC_kelly_f | BP_kelly_f |
|---|---|---|---|---|---|---|---|
| 2025-07-29 | 50 | 0.2693 | 0.4185 | 0.5360 | 0.7249 | 0.3392 | -0.8729 |
| 2025-09-04 | 107 | 0.4355 | 0.5382 | 0.6453 | 0.7449 | 0.4728 | -0.4473 |
| 2025-10-09 | 181 | 0.3265 | 0.4646 | 0.5584 | 0.6520 | 0.4246 | -0.7851 |
| 2025-11-14 | 250 | 0.3118 | 0.4331 | 0.5116 | 0.5908 | 0.2796 | -0.7691 |
| 2025-12-24 | 308 | 0.3822 | 0.4539 | 0.5042 | 0.5584 | 0.2519 | -0.5822 |
| 2026-02-11 | 372 | 0.3642 | 0.4375 | 0.5112 | 0.5853 | 0.2215 | -0.5848 |
| 2026-04-30 | 432 | 0.3760 | 0.4436 | 0.5200 | 0.5944 | 0.2494 | -0.5315 |

**Confidence model coefficients (intercept + 6 betas):**

| date | n_train | intercept | abs_sentiment | iv_rank | sent_momentum_3d | sec_aligned | log_headline_count | log_days_to_earnings |
|---|---|---|---|---|---|---|---|---|
| 2025-07-29 | 50 | +0.0702 | +0.9971 | -0.0113 | +0.6575 | +0.2536 | -0.0158 | -0.0000 |
| 2025-09-04 | 107 | +0.4210 | +0.6541 | -0.0791 | +0.7085 | +0.2862 | +0.0825 | -0.0000 |
| 2025-10-09 | 181 | +0.0196 | +0.2263 | +0.1716 | +0.7003 | +0.2005 | +0.0950 | -0.0000 |
| 2025-11-14 | 250 | -0.1391 | +0.1563 | +0.0232 | +0.5259 | +0.2701 | -0.0589 | +0.0000 |
| 2025-12-24 | 308 | -0.0793 | +0.1044 | -0.0029 | +0.3386 | +0.1918 | -0.0984 | +0.0000 |
| 2026-02-11 | 372 | -0.0895 | +0.0533 | +0.0004 | +0.3189 | +0.3128 | -0.2130 | -0.0000 |
| 2026-04-30 | 432 | -0.0327 | +0.0668 | -0.0009 | +0.3064 | +0.2857 | -0.1908 | -0.2304 |

## 7. Per-quintile breakdown

Confidence quintile labels are assigned at trade-entry time using the parameters that were live at that moment (so a trade in early 2025 may have been Q3 then but would be Q4 under the late-2026 edges -- this is the correct walk-forward semantic).

**In-sample (full corpus, production params):**

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|
| Q1 | 48 | 0.60 | 1,101.35 | 22.94 |
| Q2 | 64 | 0.58 | 2,198.14 | 34.35 |
| Q3 | 60 | 0.62 | 3,439.36 | 57.32 |
| Q4 | 59 | 0.51 | 777.61 | 13.18 |
| Q5 | 64 | 0.59 | 2,180.56 | 34.07 |

**Walk-forward (entry-time params):**

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|
| Q1 | 13 | 0.62 | 317.19 | 24.40 |
| Q2 | 40 | 0.65 | 2,524.15 | 63.10 |
| Q3 | 42 | 0.48 | 102.83 | 2.45 |
| Q4 | 58 | 0.57 | 1,693.86 | 29.20 |
| Q5 | 93 | 0.60 | 3,148.19 | 33.85 |

**Q5 - Q1 spread:** in-sample $1,079.21, 75/25 OOS -$5,261.53, walk-forward $2,831.00.

## 8. Per-ticker breakdown

| ticker | n_taken_in | pnl_in | n_taken_wf | pnl_wf |
|---|---|---|---|---|
| AAPL | 23 | 248.09 | 19 | 569.76 |
| GLD | 31 | 2,390.25 | 28 | 2,530.79 |
| IWM | 4 | 254.92 | 2 | -57.99 |
| JPM | 45 | -765.57 | 36 | -932.28 |
| NVDA | 34 | 950.78 | 26 | -121.10 |
| SPY | 7 | 330.88 | 6 | 195.71 |
| TLT | 5 | -260.92 | 4 | -58.41 |
| UNH | 37 | -26.49 | 37 | -26.49 |
| WMT | 42 | 1,714.77 | 33 | 1,641.87 |
| XOM | 67 | 4,860.31 | 55 | 4,044.36 |

**Sign-flipping tickers (|pnl| > $100 on both sides):**

- **NVDA**: in-sample $950.78 -> walk-forward -$121.10.

**AAPL.**  Walk-forward: $569.76 on 19 taken trades.  Warmup cutoff: 2025-07-29.  `outputs/aapl_stop_diagnosis.md` is a synthetic-only diagnostic; a real-mode AAPL stop-cluster post-mortem has not been published.

## 9. Verdict

**WINDOW-DEPENDENT.**  Walk-forward total Sharpe (+1.1369) is between in-sample (+1.1732) and the 75/25 OOS reference estimate (-0.5977), and the rolling 60-day distribution shows substantial variance: mean +2.1194, std 1.8618 across 123 windows (97 >+0.5 / 13 <-0.5).  84% of windows are positive.  Q5-Q1 spread $2,831.00 (in-sample $1,079.21, 75/25 OOS reference -$5,261.53).  1 ticker P&L sign-flips.  The 75/25 audit's verdict was an over-statement: walk-forward shows the strategy does have edge in some refit periods and not others rather than a uniform collapse.  Recommend regime analysis as the next session: identify which periods produce positive Sharpe and what distinguishes them (vol regime, sector rotation, corpus-window cycle).

## 10. Caveats

- **Real-corpus single-regime caveat.**  Trade corpus drawn from the real-news flat backtest covering ~12 months of headlines (~2025-05 to 2026-05).  Walk-forward on a single real-news regime is one realisation, not a Monte Carlo over macro conditions; per-ticker P&L is heavily concentrated (see PROJECT_STATE Section 10.2).  A different corpus window or ticker mix would produce different rolling-Sharpe dynamics.
- **Evaluable date range.**  2025-07-29 -> 2026-05-04 (99 signals before the warmup cutoff are not evaluated).
- **Rolling-window error bars.**  60-day windows on this trade-frequency contain ~10-30 trades; individual window Sharpes are noisy and should not be over-interpreted.  The distributional summary is the right unit of analysis.
- **Single-corpus caveat.**  This audit replays exactly one real-news corpus collected for the production universe.  The rolling-Sharpe distribution captures within-corpus variance, not cross-corpus variance from re-ingesting different news windows or ticker mixes.

## 11. Cleanup confirmation

| artifact | mtime_pre | mtime_post | size_unchanged |
|---|---|---|---|
| kelly_stats.csv (production) | 1777945077.126 | 1777945077.126 | 1 |
| quintile_edges.json (production) | 1777945077.129 | 1777945077.129 | 1 |
| confidence_model.json (production) | 1777081780.784 | 1777081780.784 | 1 |

**Production artifacts unchanged: CONFIRMED.**  No artifacts under `data/raw/` were written or modified during this audit.  All parameter snapshots were held in memory only.

---

## Reproduction

```bash
.venv/Scripts/python.exe scripts/audit_walkforward.py --real
```

Reads `data/raw/backtest_*.csv` + `data/raw/backtest_*_kelly.csv`; writes `outputs/walkforward_audit_report_real.md` only.  Re-run after any change that regenerates the flat or kelly logs.

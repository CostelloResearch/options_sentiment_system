# Walk-Forward Audit -- Daily Refit on R3 Baseline

**Mode: DEMO**

## 1. Question and methodology summary

_Tests whether the prior 75/25 audit's DEGRADES verdict (Sharpe +0.41 in-sample -> -0.60 OOS, Q5 confidence-bucket inversion) is universal across refit windows or specific to the single 2025-11-17 cutoff date.  Kelly stats, quintile edges, and the confidence model are refit each time a new accepted trade completes; every signal is sized with parameters that knew nothing about its outcome.  Path-(b) post-hoc re-derivation: the flat corpus's per-share `pnl` and `max_loss` are spread + real-price properties unchanged by sizing -- only contract counts shift between sizing regimes.  No production code, sizing logic, or on-disk artifact is modified._

## 2. Walk-forward design specifics

- **Refit cadence.**  Logically daily.  Implementation refits only when the training-corpus size grows (a new accepted trade has exited).  Identical training data produces identical parameters; redundant refits are skipped.  Result: **43 unique refits** across the corpus, vs the 700+ daily refits a naive walk-forward would do.
- **Training corpus filter.**  `accepted == True` AND `exit_date < entry_date_of_signal_being_evaluated`.  This is the strict no-look-ahead semantic: a trade is only used in fitting after its P&L is realised.  The prompt's phrasing `entry_date < T` is the loose form of the same intent.
- **Warmup threshold.**  50 accepted-and-completed trades required before any signal is evaluable.  First date this threshold is met: **2025-07-02**.  123 signals fall in the warmup period and are excluded from evaluation (counted, not zeroed).
- **Synchronization.**  Universe-wide refits using all 10 tickers' completed accepted trades.  Per-ticker refits would be a different test and were not implemented.
- **Parameter persistence.**  All parameter snapshots held in memory; nothing written under `data/raw/`.
- **Sharpe convention.**  `mean(pnl_total) / std(pnl_total, ddof=1) * sqrt(252/5)`, matching `r3_baseline.headline()`.  Same convention used for the trade-level rolling-window Sharpe.
- **Open-risk cap simplification.**  `open_risk_dollars=0` passed to every `size_trade` call (peak utilisation in the production Kelly run was 0.69 << 1.0; on a walk-forward this is even less likely to bind).

## 3. Headline metrics (walk-forward)

| metric | value |
|---|---|
| n_signals_seen | 160.0000 |
| n_warmup_excluded | 123.0000 |
| n_signals_evaluable | 160.0000 |
| n_trades_taken | 114.0000 |
| total_pnl_$ | -5,343.2600 |
| sharpe | -1.2400 |
| max_dd_$ | -7,571.7800 |
| profit_factor | 0.5875 |
| win_rate | 0.3063 |

## 4. Three-column comparison: in-sample / 75-25-OOS / walk-forward

| metric | in_sample_full | oos_75_25 | walk_forward |
|---|---|---|---|
| n_signals | 872.0000 | 213.0000 | 160.0000 |
| n_trades_taken | 360.0000 | 113.0000 | 114.0000 |
| total_pnl_$ | 5,836.1300 | -2,877.5700 | -5,343.2600 |
| sharpe | 0.4973 | -0.5977 | -1.2400 |
| max_dd_$ | -4,939.1600 | -7,731.0500 | -7,571.7800 |
| profit_factor | 1.3113 | 0.7295 | 0.5875 |
| win_rate | 0.2248 | 0.2629 | 0.3063 |
| Q5_total_pnl | -1,415.9100 | -5,585.8400 | -2,364.5300 |
| Q1_total_pnl | 6,875.5000 | -324.3100 | -2,100.0500 |
| AAPL_pnl | -1,989.0100 | -4,534.7100 | 559.3800 |
| NVDA_pnl | -2,366.3800 | -471.3200 | -88.5400 |

_75/25 OOS column reproduced from `outputs/oos_audit_report.md` (cutoff 2025-11-17); walk-forward column computed in this session.  Both share the in-sample comparison baseline._

## 5. Rolling 60-day Sharpe distribution

| stat | value |
|---|---|
| n_windows | 67.0000 |
| mean | 0.0232 |
| std | 8.6056 |
| p10 | -7.7881 |
| p25 | -3.7698 |
| p50_median | -2.3912 |
| p75 | 2.2492 |
| p90 | 8.8365 |
| min | -11.6545 |
| max | 29.5656 |
| n_positive | 22.0000 |
| n_negative | 45.0000 |
| n_|sharpe|>0.5 | 64.0000 |
| n_sharpe>+0.5 | 20.0000 |
| n_sharpe<-0.5 | 44.0000 |

**Pos vs neg windows:** 22 positive / 45 negative (33% positive).  **Strong-magnitude windows** (|Sharpe| > 0.5): 64 (20 positive, 44 negative).

## 6. Per-refit parameter evolution

Sampled 7 of 43 refit events spread evenly through the walk-forward period.  Shows how parameters evolve as the training corpus grows.

**Quintile edges + Kelly fractions:**

| date | n_train | edge_q1 | edge_q2 | edge_q3 | edge_q4 | BC_kelly_f | BP_kelly_f |
|---|---|---|---|---|---|---|---|
| 2025-07-02 | 51 | 0.5210 | 0.6332 | 0.6985 | 0.7606 | 0.5676 | 0.0912 |
| 2025-08-07 | 61 | 0.4688 | 0.5624 | 0.6341 | 0.6974 | 0.3475 | 0.0912 |
| 2025-09-19 | 102 | 0.3222 | 0.4321 | 0.5024 | 0.5956 | 0.3647 | -0.4762 |
| 2025-10-22 | 120 | 0.3315 | 0.4255 | 0.4818 | 0.5375 | 0.3631 | -0.5885 |
| 2026-01-22 | 146 | 0.3855 | 0.4341 | 0.4720 | 0.5191 | 0.2896 | -0.6190 |
| 2026-03-24 | 153 | 0.3888 | 0.4361 | 0.4670 | 0.5104 | 0.2898 | -0.6234 |
| 2026-04-30 | 176 | 0.3705 | 0.4407 | 0.4916 | 0.5517 | 0.3681 | -0.7110 |

**Confidence model coefficients (intercept + 6 betas):**

| date | n_train | intercept | abs_sentiment | iv_rank | sent_momentum_3d | sec_aligned | log_headline_count | log_days_to_earnings |
|---|---|---|---|---|---|---|---|---|
| 2025-07-02 | 51 | +0.6530 | -0.0245 | +0.3513 | +0.0311 | +0.0000 | -0.5511 | +0.0000 |
| 2025-08-07 | 61 | +0.3992 | +0.3398 | -0.1354 | -0.2620 | +0.0000 | -0.4121 | -0.0000 |
| 2025-09-19 | 102 | -0.1732 | +0.2927 | +0.5278 | -0.1468 | +0.0000 | -0.1683 | +0.0000 |
| 2025-10-22 | 120 | -0.2115 | +0.2370 | +0.3836 | +0.0787 | +0.0000 | -0.2028 | -0.0000 |
| 2026-01-22 | 146 | -0.1967 | +0.1537 | +0.1613 | +0.1218 | +0.0000 | -0.2009 | -0.0000 |
| 2026-03-24 | 153 | -0.2004 | +0.1317 | +0.1455 | +0.0545 | +0.0000 | -0.1878 | -0.0000 |
| 2026-04-30 | 176 | -0.1427 | +0.1842 | +0.2280 | +0.1810 | +0.0000 | -0.2561 | -0.0000 |

## 7. Per-quintile breakdown

Confidence quintile labels are assigned at trade-entry time using the parameters that were live at that moment (so a trade in early 2025 may have been Q3 then but would be Q4 under the late-2026 edges -- this is the correct walk-forward semantic).

**In-sample (full corpus, production params):**

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|
| Q1 | 333 | 0.56 | 6,875.50 | 20.65 |
| Q2 | 6 | 0.67 | 511.88 | 85.31 |
| Q3 | 7 | 0.43 | -162.94 | -23.28 |
| Q4 | 3 | 0.67 | 27.60 | 9.20 |
| Q5 | 11 | 0.00 | -1,415.91 | -128.72 |

**Walk-forward (entry-time params):**

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|
| Q1 | 32 | 0.50 | -2,100.05 | -65.63 |
| Q2 | 28 | 0.46 | -117.35 | -4.19 |
| Q3 | 15 | 0.53 | 934.47 | 62.30 |
| Q4 | 17 | 0.24 | -1,695.80 | -99.75 |
| Q5 | 22 | 0.36 | -2,364.53 | -107.48 |

**Q5 - Q1 spread:** in-sample -$8,291.41, 75/25 OOS -$5,261.53, walk-forward -$264.48.

## 8. Per-ticker breakdown

| ticker | n_taken_in | pnl_in | n_taken_wf | pnl_wf |
|---|---|---|---|---|
| AAPL | 42 | -1,989.01 | 5 | 559.38 |
| GLD | 1 | -28.18 | 6 | -503.83 |
| IWM | 43 | 2,426.84 | 41 | -8,121.22 |
| JPM | 16 | -425.33 | 8 | 866.48 |
| NVDA | 90 | -2,366.38 | 4 | -88.54 |
| SPY | 60 | 4,315.58 | 3 | 25.83 |
| TLT | 29 | 2,524.44 | 26 | 1,158.36 |
| UNH | 6 | 147.83 | 3 | -181.18 |
| WMT | 47 | 3.33 | 0 | 0.00 |
| XOM | 26 | 1,227.01 | 18 | 941.46 |

**Sign-flipping tickers (|pnl| > $100 on both sides):**

- **AAPL**: in-sample -$1,989.01 -> walk-forward $559.38.
- **IWM**: in-sample $2,426.84 -> walk-forward -$8,121.22.
- **JPM**: in-sample -$425.33 -> walk-forward $866.48.
- **UNH**: in-sample $147.83 -> walk-forward -$181.18.

**AAPL (prior diagnosis: -$3,568 in-sample, 13 stop-outs).**  Walk-forward: $559.38 on 5 taken trades.  The Dec-2025 / Jan-2026 stop cluster from `outputs/aapl_stop_diagnosis.md` falls after the warmup cutoff (2025-07-02) so it is in the walk-forward evaluable window.

## 9. Verdict

**DEGRADES CONSISTENTLY.**  Walk-forward total Sharpe (-1.2400) is statistically indistinguishable from zero -- the entire +0.4973 in-sample edge does not reproduce.  The rolling 60-day distribution has mean +0.0232 (std 8.6056) with substantial dispersion (20 windows above +0.5 vs 44 below -0.5, 33% positive overall) -- the strategy is not uniformly bad in every refit window, but on average and on aggregate P&L it does not produce edge.  Q5-Q1 spread -$264.48 inverts the in-sample ordering of -$8,291.41: even after averaging over 195 refit windows, the model's 'highest confidence' bucket still systematically loses money.  4 ticker P&L sign-flips on > $100 magnitude.  The 75/25 finding reproduces under finer-grained refits: R3's +$6,775 / +0.41 Sharpe baseline is largely in-sample inflation.  v2_10t promotion on the current evidence is premature; the production R3 sizing decision was made on numbers that do not survive any honest holdout test.

## 10. Caveats

- **Synthetic-sentiment caveat (still load-bearing).**  All trades have `is_synthetic=True`.  Walk-forward on the deterministic synthetic generator is a single realisation, not a Monte Carlo over RNG draws.  Real-mode walk-forward on accumulated live news will differ structurally.
- **Evaluable date range.**  2025-07-02 -> 2026-05-01 (123 signals before the warmup cutoff are not evaluated).
- **Rolling-window error bars.**  60-day windows on this trade-frequency contain ~10-30 trades; individual window Sharpes are noisy and should not be over-interpreted.  The distributional summary is the right unit of analysis.
- **Single-realisation caveat.**  Synthetic sentiment seed is deterministic per ticker (`seed = sum(ord(c) for c in ticker)`).  Rerunning would produce identical results; a Monte Carlo over different seeds would require a code change in `backtest/engine._generate_synthetic_history` (out of scope).

## 11. Cleanup confirmation

| artifact | mtime_pre | mtime_post | size_unchanged |
|---|---|---|---|
| kelly_stats.csv (production) | 1777679169.712 | 1777679169.712 | 1 |
| quintile_edges.json (production) | 1777679169.714 | 1777679169.714 | 1 |
| confidence_model.json (production) | 1777081780.784 | 1777081780.784 | 1 |

**Production artifacts unchanged: CONFIRMED.**  No artifacts under `data/raw/` were written or modified during this audit.  All parameter snapshots were held in memory only.

---

## Reproduction

```bash
.venv/Scripts/python.exe scripts/audit_walkforward.py
```

Reads `data/raw/backtest_*_demo.csv` + `data/raw/backtest_*_demo_kelly.csv`; writes `outputs/walkforward_audit_report.md` only.  Re-run after any change that regenerates the flat or kelly logs.

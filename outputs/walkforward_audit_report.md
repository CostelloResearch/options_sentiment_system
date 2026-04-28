# Walk-Forward Audit -- Daily Refit on R3 Baseline

**Mode: DEMO**

## 1. Question and methodology summary

_Tests whether the prior 75/25 audit's DEGRADES verdict (Sharpe +0.41 in-sample -> -0.60 OOS, Q5 confidence-bucket inversion) is universal across refit windows or specific to the single 2025-11-17 cutoff date.  Kelly stats, quintile edges, and the confidence model are refit each time a new accepted trade completes; every signal is sized with parameters that knew nothing about its outcome.  Path-(b) post-hoc re-derivation: the flat corpus's per-share `pnl` and `max_loss` are spread + real-price properties unchanged by sizing -- only contract counts shift between sizing regimes.  No production code, sizing logic, or on-disk artifact is modified._

## 2. Walk-forward design specifics

- **Refit cadence.**  Logically daily.  Implementation refits only when the training-corpus size grows (a new accepted trade has exited).  Identical training data produces identical parameters; redundant refits are skipped.  Result: **195 unique refits** across the corpus, vs the 700+ daily refits a naive walk-forward would do.
- **Training corpus filter.**  `accepted == True` AND `exit_date < entry_date_of_signal_being_evaluated`.  This is the strict no-look-ahead semantic: a trade is only used in fitting after its P&L is realised.  The prompt's phrasing `entry_date < T` is the loose form of the same intent.
- **Warmup threshold.**  50 accepted-and-completed trades required before any signal is evaluable.  First date this threshold is met: **2025-01-06**.  153 signals fall in the warmup period and are excluded from evaluation (counted, not zeroed).
- **Synchronization.**  Universe-wide refits using all 10 tickers' completed accepted trades.  Per-ticker refits would be a different test and were not implemented.
- **Parameter persistence.**  All parameter snapshots held in memory; nothing written under `data/raw/`.
- **Sharpe convention.**  `mean(pnl_total) / std(pnl_total, ddof=1) * sqrt(252/5)`, matching `r3_baseline.headline()`.  Same convention used for the trade-level rolling-window Sharpe.
- **Open-risk cap simplification.**  `open_risk_dollars=0` passed to every `size_trade` call (peak utilisation in the production Kelly run was 0.69 << 1.0; on a walk-forward this is even less likely to bind).

## 3. Headline metrics (walk-forward)

| metric | value |
|---|---|
| n_signals_seen | 698.0000 |
| n_warmup_excluded | 153.0000 |
| n_signals_evaluable | 698.0000 |
| n_trades_taken | 400.0000 |
| total_pnl_$ | -1,181.2600 |
| sharpe | -0.0517 |
| max_dd_$ | -15,312.1500 |
| profit_factor | 0.9732 |
| win_rate | 0.2693 |

## 4. Three-column comparison: in-sample / 75-25-OOS / walk-forward

| metric | in_sample_full | oos_75_25 | walk_forward |
|---|---|---|---|
| n_signals | 851.0000 | 213.0000 | 698.0000 |
| n_trades_taken | 357.0000 | 113.0000 | 400.0000 |
| total_pnl_$ | 6,775.1400 | -2,877.5700 | -1,181.2600 |
| sharpe | 0.4103 | -0.5977 | -0.0517 |
| max_dd_$ | -6,243.9900 | -7,731.0500 | -15,312.1500 |
| profit_factor | 1.2675 | 0.7295 | 0.9732 |
| win_rate | 0.2186 | 0.2629 | 0.2693 |
| Q5_total_pnl | 5,504.5600 | -5,585.8400 | -5,685.3300 |
| Q1_total_pnl | -1,253.2700 | -324.3100 | 786.4800 |
| AAPL_pnl | -3,567.6100 | -4,534.7100 | -5,732.0300 |
| NVDA_pnl | 1,002.0100 | -471.3200 | -2,104.0200 |

_75/25 OOS column reproduced from `outputs/oos_audit_report.md` (cutoff 2025-11-17); walk-forward column computed in this session.  Both share the in-sample comparison baseline._

## 5. Rolling 60-day Sharpe distribution

| stat | value |
|---|---|
| n_windows | 201.0000 |
| mean | -0.8702 |
| std | 1.6038 |
| p10 | -3.3119 |
| p25 | -1.9666 |
| p50_median | -0.9012 |
| p75 | 0.3225 |
| p90 | 1.0751 |
| min | -5.0449 |
| max | 3.0247 |
| n_positive | 78.0000 |
| n_negative | 123.0000 |
| n_|sharpe|>0.5 | 153.0000 |
| n_sharpe>+0.5 | 41.0000 |
| n_sharpe<-0.5 | 112.0000 |

**Pos vs neg windows:** 78 positive / 123 negative (39% positive).  **Strong-magnitude windows** (|Sharpe| > 0.5): 153 (41 positive, 112 negative).

## 6. Per-refit parameter evolution

Sampled 7 of 195 refit events spread evenly through the walk-forward period.  Shows how parameters evolve as the training corpus grows.

**Quintile edges + Kelly fractions:**

| date | n_train | edge_q1 | edge_q2 | edge_q3 | edge_q4 | BC_kelly_f | BP_kelly_f |
|---|---|---|---|---|---|---|---|
| 2025-01-06 | 51 | 0.4713 | 0.5757 | 0.6703 | 0.7407 | 0.4199 | 0.0105 |
| 2025-06-26 | 118 | 0.4831 | 0.5434 | 0.5813 | 0.6411 | 0.1773 | 0.0830 |
| 2025-08-21 | 192 | 0.5304 | 0.5868 | 0.6418 | 0.7216 | 0.3290 | 0.1588 |
| 2025-10-20 | 318 | 0.5032 | 0.5153 | 0.5278 | 0.5412 | 0.2707 | -0.2591 |
| 2025-12-16 | 421 | 0.4473 | 0.4844 | 0.5150 | 0.5487 | 0.1290 | -0.1638 |
| 2026-02-24 | 499 | 0.4393 | 0.4712 | 0.4990 | 0.5300 | 0.0645 | -0.1554 |
| 2026-04-23 | 580 | 0.4700 | 0.4948 | 0.5196 | 0.5491 | 0.0641 | -0.0220 |

**Confidence model coefficients (intercept + 6 betas):**

| date | n_train | intercept | abs_sentiment | iv_rank | sent_momentum_3d | sec_aligned | log_headline_count | log_days_to_earnings |
|---|---|---|---|---|---|---|---|---|
| 2025-01-06 | 51 | +0.4918 | -0.2302 | -0.5717 | +0.1146 | +0.0000 | +0.4085 | +0.0000 |
| 2025-06-26 | 118 | +0.2862 | -0.0062 | -0.3277 | -0.2259 | +0.0000 | +0.0365 | +0.0000 |
| 2025-08-21 | 192 | +0.5114 | +0.0939 | -0.3808 | -0.2159 | +0.0000 | +0.1116 | +0.0000 |
| 2025-10-20 | 318 | +0.0883 | +0.0329 | -0.0664 | +0.0141 | +0.0000 | +0.0381 | -0.0000 |
| 2025-12-16 | 421 | -0.0047 | +0.0411 | -0.1924 | +0.0777 | +0.0000 | -0.0342 | -0.0000 |
| 2026-02-24 | 499 | -0.0606 | +0.0494 | -0.1647 | +0.0369 | +0.0000 | -0.0878 | +0.0000 |
| 2026-04-23 | 580 | +0.0349 | -0.0033 | -0.1281 | +0.0195 | +0.0000 | -0.1234 | +0.0000 |

## 7. Per-quintile breakdown

Confidence quintile labels are assigned at trade-entry time using the parameters that were live at that moment (so a trade in early 2025 may have been Q3 then but would be Q4 under the late-2026 edges -- this is the correct walk-forward semantic).

**In-sample (full corpus, production params):**

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|
| Q1 | 65 | 0.38 | -1,253.27 | -19.28 |
| Q2 | 75 | 0.55 | 828.05 | 11.04 |
| Q3 | 62 | 0.48 | -351.09 | -5.66 |
| Q4 | 77 | 0.60 | 2,046.89 | 26.58 |
| Q5 | 78 | 0.56 | 5,504.56 | 70.57 |

**Walk-forward (entry-time params):**

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|
| Q1 | 77 | 0.47 | 786.48 | 10.21 |
| Q2 | 69 | 0.42 | -973.80 | -14.11 |
| Q3 | 71 | 0.62 | 5,471.06 | 77.06 |
| Q4 | 82 | 0.48 | -779.67 | -9.51 |
| Q5 | 101 | 0.40 | -5,685.33 | -56.29 |

**Q5 - Q1 spread:** in-sample $6,757.83, 75/25 OOS -$5,261.53, walk-forward -$6,471.81.

## 8. Per-ticker breakdown

| ticker | n_taken_in | pnl_in | n_taken_wf | pnl_wf |
|---|---|---|---|---|
| AAPL | 44 | -3,567.61 | 41 | -5,732.03 |
| GLD | 3 | 145.00 | 10 | -990.98 |
| IWM | 38 | 1,617.84 | 65 | -4,996.50 |
| JPM | 14 | -62.67 | 34 | -4,673.73 |
| NVDA | 89 | 1,002.01 | 82 | -2,104.02 |
| SPY | 63 | 4,368.83 | 56 | 1,187.44 |
| TLT | 29 | 1,422.57 | 30 | 3,254.83 |
| UNH | 6 | -623.93 | 17 | 10,245.32 |
| WMT | 45 | 1,068.91 | 45 | 1,659.35 |
| XOM | 26 | 1,404.19 | 20 | 969.06 |

**Sign-flipping tickers (|pnl| > $100 on both sides):**

- **GLD**: in-sample $145.00 -> walk-forward -$990.98.
- **IWM**: in-sample $1,617.84 -> walk-forward -$4,996.50.
- **NVDA**: in-sample $1,002.01 -> walk-forward -$2,104.02.
- **UNH**: in-sample -$623.93 -> walk-forward $10,245.32.

**AAPL (prior diagnosis: -$3,568 in-sample, 13 stop-outs).**  Walk-forward: -$5,732.03 on 41 taken trades.  The Dec-2025 / Jan-2026 stop cluster from `outputs/aapl_stop_diagnosis.md` falls after the warmup cutoff (2025-01-06) so it is in the walk-forward evaluable window.

## 9. Verdict

**DEGRADES CONSISTENTLY.**  Walk-forward total Sharpe (-0.0517) is statistically indistinguishable from zero -- the entire +0.4103 in-sample edge does not reproduce.  The rolling 60-day distribution has mean -0.8702 (std 1.6038) with substantial dispersion (41 windows above +0.5 vs 112 below -0.5, 39% positive overall) -- the strategy is not uniformly bad in every refit window, but on average and on aggregate P&L it does not produce edge.  Q5-Q1 spread -$6,471.81 inverts the in-sample ordering of $6,757.83: even after averaging over 195 refit windows, the model's 'highest confidence' bucket still systematically loses money.  4 ticker P&L sign-flips on > $100 magnitude.  The 75/25 finding reproduces under finer-grained refits: R3's +$6,775 / +0.41 Sharpe baseline is largely in-sample inflation.  v2_10t promotion on the current evidence is premature; the production R3 sizing decision was made on numbers that do not survive any honest holdout test.

## 10. Caveats

- **Synthetic-sentiment caveat (still load-bearing).**  All trades have `is_synthetic=True`.  Walk-forward on the deterministic synthetic generator is a single realisation, not a Monte Carlo over RNG draws.  Real-mode walk-forward on accumulated live news will differ structurally.
- **Evaluable date range.**  2025-01-06 -> 2026-04-24 (153 signals before the warmup cutoff are not evaluated).
- **Rolling-window error bars.**  60-day windows on this trade-frequency contain ~10-30 trades; individual window Sharpes are noisy and should not be over-interpreted.  The distributional summary is the right unit of analysis.
- **Single-realisation caveat.**  Synthetic sentiment seed is deterministic per ticker (`seed = sum(ord(c) for c in ticker)`).  Rerunning would produce identical results; a Monte Carlo over different seeds would require a code change in `backtest/engine._generate_synthetic_history` (out of scope).

## 11. Cleanup confirmation

| artifact | mtime_pre | mtime_post | size_unchanged |
|---|---|---|---|
| kelly_stats.csv (production) | 1777156920.448 | 1777156920.448 | 1 |
| quintile_edges.json (production) | 1777156920.45 | 1777156920.45 | 1 |
| confidence_model.json (production) | 1777081780.784 | 1777081780.784 | 1 |

**Production artifacts unchanged: CONFIRMED.**  No artifacts under `data/raw/` were written or modified during this audit.  All parameter snapshots were held in memory only.

---

## Reproduction

```bash
.venv/Scripts/python.exe scripts/audit_walkforward.py
```

Reads `data/raw/backtest_*_demo.csv` + `data/raw/backtest_*_demo_kelly.csv`; writes `outputs/walkforward_audit_report.md` only.  Re-run after any change that regenerates the flat or kelly logs.

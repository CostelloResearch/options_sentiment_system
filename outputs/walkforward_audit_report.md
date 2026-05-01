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
| total_pnl_$ | -1,203.8200 |
| sharpe | -0.0617 |
| max_dd_$ | -10,704.6300 |
| profit_factor | 0.9671 |
| win_rate | 0.2693 |

## 4. Three-column comparison: in-sample / 75-25-OOS / walk-forward

| metric | in_sample_full | oos_75_25 | walk_forward |
|---|---|---|---|
| n_signals | 872.0000 | 213.0000 | 698.0000 |
| n_trades_taken | 360.0000 | 113.0000 | 400.0000 |
| total_pnl_$ | 5,836.1300 | -2,877.5700 | -1,203.8200 |
| sharpe | 0.4973 | -0.5977 | -0.0617 |
| max_dd_$ | -6,567.8800 | -7,731.0500 | -10,704.6300 |
| profit_factor | 1.3113 | 0.7295 | 0.9671 |
| win_rate | 0.2248 | 0.2629 | 0.2693 |
| Q5_total_pnl | -1,415.9100 | -5,585.8400 | -4,671.1400 |
| Q1_total_pnl | 6,875.5000 | -324.3100 | 1,155.8400 |
| AAPL_pnl | -1,989.0100 | -4,534.7100 | -2,260.8500 |
| NVDA_pnl | -2,366.3800 | -471.3200 | -1,339.9900 |

_75/25 OOS column reproduced from `outputs/oos_audit_report.md` (cutoff 2025-11-17); walk-forward column computed in this session.  Both share the in-sample comparison baseline._

## 5. Rolling 60-day Sharpe distribution

| stat | value |
|---|---|
| n_windows | 201.0000 |
| mean | -1.0687 |
| std | 1.8227 |
| p10 | -2.7639 |
| p25 | -1.8810 |
| p50_median | -1.0688 |
| p75 | 0.0968 |
| p90 | 0.8096 |
| min | -7.3958 |
| max | 2.6792 |
| n_positive | 64.0000 |
| n_negative | 137.0000 |
| n_|sharpe|>0.5 | 139.0000 |
| n_sharpe>+0.5 | 29.0000 |
| n_sharpe<-0.5 | 110.0000 |

**Pos vs neg windows:** 64 positive / 137 negative (32% positive).  **Strong-magnitude windows** (|Sharpe| > 0.5): 139 (29 positive, 110 negative).

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
| Q1 | 333 | 0.56 | 6,875.50 | 20.65 |
| Q2 | 6 | 0.67 | 511.88 | 85.31 |
| Q3 | 7 | 0.43 | -162.94 | -23.28 |
| Q4 | 3 | 0.67 | 27.60 | 9.20 |
| Q5 | 11 | 0.00 | -1,415.91 | -128.72 |

**Walk-forward (entry-time params):**

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|
| Q1 | 77 | 0.47 | 1,155.84 | 15.01 |
| Q2 | 69 | 0.42 | -1,469.32 | -21.29 |
| Q3 | 71 | 0.62 | 5,168.38 | 72.79 |
| Q4 | 82 | 0.48 | -1,387.58 | -16.92 |
| Q5 | 101 | 0.40 | -4,671.14 | -46.25 |

**Q5 - Q1 spread:** in-sample -$8,291.41, 75/25 OOS -$5,261.53, walk-forward -$5,826.98.

## 8. Per-ticker breakdown

| ticker | n_taken_in | pnl_in | n_taken_wf | pnl_wf |
|---|---|---|---|---|
| AAPL | 42 | -1,989.01 | 41 | -2,260.85 |
| GLD | 1 | -28.18 | 10 | -1,079.11 |
| IWM | 43 | 2,426.84 | 65 | -4,940.54 |
| JPM | 16 | -425.33 | 34 | -4,171.52 |
| NVDA | 90 | -2,366.38 | 82 | -1,339.99 |
| SPY | 60 | 4,315.58 | 56 | 1,090.90 |
| TLT | 29 | 2,524.44 | 30 | 113.92 |
| UNH | 6 | 147.83 | 17 | 10,245.32 |
| WMT | 47 | 3.33 | 45 | 265.56 |
| XOM | 26 | 1,227.01 | 20 | 872.49 |

**Sign-flipping tickers (|pnl| > $100 on both sides):**

- **IWM**: in-sample $2,426.84 -> walk-forward -$4,940.54.

**AAPL (prior diagnosis: -$3,568 in-sample, 13 stop-outs).**  Walk-forward: -$2,260.85 on 41 taken trades.  The Dec-2025 / Jan-2026 stop cluster from `outputs/aapl_stop_diagnosis.md` falls after the warmup cutoff (2025-01-06) so it is in the walk-forward evaluable window.

## 9. Verdict

**DEGRADES CONSISTENTLY.**  Walk-forward total Sharpe (-0.0617) is statistically indistinguishable from zero -- the entire +0.4973 in-sample edge does not reproduce.  The rolling 60-day distribution has mean -1.0687 (std 1.8227) with substantial dispersion (29 windows above +0.5 vs 110 below -0.5, 32% positive overall) -- the strategy is not uniformly bad in every refit window, but on average and on aggregate P&L it does not produce edge.  Q5-Q1 spread -$5,826.98 inverts the in-sample ordering of -$8,291.41: even after averaging over 195 refit windows, the model's 'highest confidence' bucket still systematically loses money.  1 ticker P&L sign-flips on > $100 magnitude.  The 75/25 finding reproduces under finer-grained refits: R3's +$6,775 / +0.41 Sharpe baseline is largely in-sample inflation.  v2_10t promotion on the current evidence is premature; the production R3 sizing decision was made on numbers that do not survive any honest holdout test.

## 10. Caveats

- **Synthetic-sentiment caveat (still load-bearing).**  All trades have `is_synthetic=True`.  Walk-forward on the deterministic synthetic generator is a single realisation, not a Monte Carlo over RNG draws.  Real-mode walk-forward on accumulated live news will differ structurally.
- **Evaluable date range.**  2025-01-06 -> 2026-04-24 (153 signals before the warmup cutoff are not evaluated).
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

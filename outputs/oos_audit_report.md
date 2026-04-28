# Out-of-Sample Audit -- 75/25 Chronological Holdout

**Mode: DEMO**

_Tests how much of the +$6,775 / Sharpe 0.41 / 357 trades R3 production baseline is in-sample inflation vs out-of-sample edge.  Fits Kelly stats, quintile edges, and confidence model on the earliest 75% of the flat corpus; re-derives Kelly sizing on the last 25% using those train-fitted parameters; reports headline metrics for full corpus (in-sample), train fold, test fold._

## 1. The audit's question

When the three in-sample-leakage parameters (Kelly stats, quintile edges, confidence model) are fit only on the chronologically-earliest 75% of the trade corpus and the strategy is evaluated only on the last 25%, do the headline metrics survive?  If they do, the +$6,775 is a defensible signal-edge measurement; if they collapse, the headline is in-sample inflation.

## 2. Methodology

- **Implementation choice:** Path (b) -- post-hoc re-derivation of Kelly sizing on the existing flat corpus.  The per-share `pnl` and `max_loss` columns in `backtest_*_demo.csv` are properties of the spread + price walk, not the sizing decision; only the contract count changes between in-sample and OOS evaluation.  Avoids re-running `engine.run_backtest` (slow) without losing fidelity.
- **Cutoff date:** 2025-11-17 (75th percentile of `entry_date` across all 851 flat-corpus rows).
- **Train fold:** 638 flat-corpus rows with `entry_date <= 2025-11-17`.
- **Test fold:** 213 flat-corpus rows with `entry_date > 2025-11-17`.
- **Sharpe convention:** `mean(pnl_total) / std(pnl_total, ddof=1) * sqrt(252/5)`, matching `r3_baseline.headline()` exactly.
- **Open-risk cap simplification:** `open_risk_dollars=0` is passed to every `size_trade` call.  In the production Kelly run the global 6% portfolio cap had peak utilisation 0.69 (`outputs/r3_production_baseline.md` Section 3); on smaller folds it binds even less, so this is a tight approximation.

**Per-ticker row counts (signals, not taken):**

| ticker | train_signals | test_signals | total |
|---|---|---|---|
| AAPL | 68 | 33 | 101 |
| NVDA | 69 | 57 | 126 |
| JPM | 73 | 10 | 83 |
| XOM | 30 | 4 | 34 |
| UNH | 75 | 29 | 104 |
| WMT | 66 | 6 | 72 |
| IWM | 79 | 9 | 88 |
| GLD | 59 | 16 | 75 |
| TLT | 41 | 10 | 51 |
| SPY | 78 | 39 | 117 |

**Date ranges:**

- Train: 2024-05-29 -> 2025-11-17
- Test:  2025-11-18 -> 2026-04-24

**Train-fold refit parameters:**

- `kelly_stats_oos_train.csv` -- per-signal counts/win/W/Kelly_f.
  Production vs train-fold Kelly_f comparison:

| signal | prod_n | prod_kelly_f | prod_tradable | train_n | train_kelly_f | train_tradable |
|---|---|---|---|---|---|---|
| BUY CALLS | 357 | 0.0789 | 1 | 244 | 0.1178 | 1 |
| BUY PUTS | 256 | -0.0567 | 0 | 169 | -0.1531 | 0 |

- `quintile_edges_oos_train.json` -- `[0.4571, 0.484, 0.5066, 0.5349]`
  Production edges (for comparison): `[0.544, 0.5618, 0.5779, 0.602]`
- `confidence_model_oos_train.json` -- logistic refit on 413 accepted train trades, converged=True in 2 IRLS iters, train_win_rate=0.496.

**Held constant from production (NOT refit):** all hand-set constants (`STOP_LOSS_DEBIT_FRAC=0.80`, `PROFIT_TARGET_FRAC=0.50`, `TIME_STOP_DTE=21`, `KELLY_FRACTION=0.25`, `MAX_PORTFOLIO_RISK=0.06`, `QUINTILE_FRAC` table, sentiment/IV thresholds, BUY PUTS structural override).  These are fixed parameters, not data-fitted, so they don't carry the in-sample-leakage concern.

## 3. Headline comparison

| metric | in_sample_full | train_fold | test_fold |
|---|---|---|---|
| n_signals | 851.0000 | 638.0000 | 213.0000 |
| n_trades_taken | 357.0000 | 244.0000 | 113.0000 |
| total_pnl_$ | 6,775.1400 | 10,146.6100 | -2,877.5700 |
| sharpe | 0.4103 | 0.7962 | -0.5977 |
| max_dd_$ | -6,243.9900 | -3,383.3100 | -7,731.0500 |
| profit_factor | 1.2675 | 1.6397 | 0.7295 |
| win_rate | 0.2186 | 0.2038 | 0.2629 |

**Test-fold result vs in-sample.**  Sharpe: -0.5977 test fold vs +0.4103 in-sample (ratio -1.46); P&L -$2,877.57 test fold vs $6,775.14 in-sample.  Note that test-fold P&L cannot be directly compared to in-sample P&L on absolute terms because the test fold contains only ~25% of the signal dates -- the like-for-like comparison is on Sharpe (which is sample-size invariant under the convention used).

## 4. Per-ticker breakdown

| ticker | n_taken_in | pnl_in | n_taken_train | pnl_train | n_taken_test | pnl_test |
|---|---|---|---|---|---|---|
| AAPL | 44 | -3,567.61 | 22 | -849.83 | 22 | -4,534.71 |
| GLD | 3 | 145.00 | 0 | 0.00 | 3 | 145.00 |
| IWM | 38 | 1,617.84 | 31 | 1,647.53 | 7 | 42.56 |
| JPM | 14 | -62.67 | 14 | -479.78 | 0 | 0.00 |
| NVDA | 89 | 1,002.01 | 37 | -45.83 | 52 | -471.32 |
| SPY | 63 | 4,368.83 | 52 | 4,042.31 | 11 | 1,258.93 |
| TLT | 29 | 1,422.57 | 21 | 2,725.53 | 8 | 517.42 |
| UNH | 6 | -623.93 | 0 | 0.00 | 6 | -623.94 |
| WMT | 45 | 1,068.91 | 44 | 2,481.52 | 1 | 174.40 |
| XOM | 26 | 1,404.19 | 23 | 625.16 | 3 | 614.09 |

**Sign-flipping tickers (|pnl| > $100 in both columns):**

- **NVDA**: in-sample $1,002.01 -> test fold -$471.32.

**AAPL (prior diagnosis: -$3,568 in-sample, 13 stop-outs).**  Train fold: -$849.83 on 22 taken trades.  Test fold: -$4,534.71 on 22 taken trades.  The Dec-2025/Jan-2026 stop cluster identified in `outputs/aapl_stop_diagnosis.md` falls in the TEST fold (cluster end 2026-01-12 vs cutoff 2025-11-17).

## 5. Per-quintile breakdown

Quintile binning uses the production edges for the in-sample column and the train-fitted edges for the train- and test-fold columns.  Confidence values for the in-sample column are the production-model values stored in the Kelly logs; for the train and test folds they are recomputed via the train-fitted logistic.

**In-sample (full corpus, production params):**

| label | quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|---|
| in_sample | Q1 | 65 | 0.38 | -1,253.27 | -19.28 |
| in_sample | Q2 | 75 | 0.55 | 828.05 | 11.04 |
| in_sample | Q3 | 62 | 0.48 | -351.09 | -5.66 |
| in_sample | Q4 | 77 | 0.60 | 2,046.89 | 26.58 |
| in_sample | Q5 | 78 | 0.56 | 5,504.56 | 70.57 |

**Train fold (train-fitted params, train trades):**

| label | quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|---|
| train_fold | Q1 | 40 | 0.40 | -844.62 | -21.12 |
| train_fold | Q2 | 51 | 0.49 | -364.83 | -7.15 |
| train_fold | Q3 | 43 | 0.49 | 821.72 | 19.11 |
| train_fold | Q4 | 44 | 0.52 | 1,025.02 | 23.30 |
| train_fold | Q5 | 66 | 0.68 | 9,509.32 | 144.08 |

**Test fold (train-fitted params, test trades):**

| label | quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|---|
| test_fold | Q1 | 33 | 0.39 | -324.31 | -9.83 |
| test_fold | Q2 | 23 | 0.61 | 717.70 | 31.20 |
| test_fold | Q3 | 15 | 0.73 | 998.55 | 66.57 |
| test_fold | Q4 | 22 | 0.64 | 1,316.33 | 59.83 |
| test_fold | Q5 | 20 | 0.20 | -5,585.84 | -279.29 |

**Q5 - Q1 total-P&L spread:**  in-sample $6,757.83, train fold $10,353.94, test fold -$5,261.53.  In-sample shows monotone Q1 < Q5 = +$6,758 ordering; the test-fold spread is the OOS test of whether the confidence-model ranking generalises.

## 6. Verdict

**DEGRADES.**  Test-fold Sharpe (-0.5977) is near zero or negative vs the in-sample +0.4103.  Q5-Q1 spread on the test fold (-$5,261.53) inverts the in-sample ordering; 1 ticker P&L sign-flips on > $100 magnitude.  The +$6,775 headline is largely or entirely in-sample inflation -- the strategy does not carry the claimed edge once parameters are fit on data the evaluation window does not see.  R3's selection as production sizing was made on numbers that do not reflect out-of-sample behaviour; the v2_10t promotion is premature on the current evidence; the +$6,775 figure should not be cited as a forward-looking performance estimate without an OOS qualifier.  This is the most consequential finding produced by any audit in this codebase to date.


## 7. Caveats

- **Synthetic-sentiment caveat (still load-bearing).**  Every trade in the corpus has `is_synthetic=True`.  This audit measures generalisation **within the synthetic generator's deterministic-seed walk**, not generalisation to live sentiment.  A real-mode run (`scripts/r3_baseline.py --real`) would produce a structurally different corpus.
- **Single-split caveat.**  A 75/25 chronological holdout is one sample of 'future data.'  Walk-forward refit-every-N-days would give a distribution of OOS Sharpe estimates rather than a single point.  Given this audit's outcome, walk-forward is the warranted next session.
- **Test-fold size caveat.**  The test fold contains 213 signals and 113 taken trades.  Sharpe at this sample size has wide error bars; the point estimate -0.5977 should be read with that in mind.  The standard error of an annualised Sharpe at this trade count is roughly 1/sqrt(113/5) per year-equivalent ~ 0.21, so the 95% CI is roughly +/- 0.42 around the point estimate.
- **Open-risk cap approximation.**  `size_trade` was called with `open_risk_dollars=0`, which assumes the global 6% cap never binds in the test fold.  The production Kelly run had peak utilisation 0.69 (well below 1.0); on a smaller fold this is even less likely to bind.

## 8. Cleanup confirmation

| artifact | mtime_pre | mtime_post | size_unchanged |
|---|---|---|---|
| kelly_stats.csv (production) | 1777156920.448 | 1777156920.448 | 1 |
| quintile_edges.json (production) | 1777156920.45 | 1777156920.45 | 1 |
| confidence_model.json (production) | 1777081780.784 | 1777081780.784 | 1 |

**Production artifacts unchanged: CONFIRMED.**  All OOS-specific outputs are in `*_oos_train.*` files (`data/raw/kelly_stats_oos_train.csv`, `data/raw/quintile_edges_oos_train.json`, `data/raw/confidence_model_oos_train.json`).

---

## Reproduction

```bash
.venv/Scripts/python.exe scripts/audit_oos_split.py
```

Reads `data/raw/backtest_*_demo.csv` + `data/raw/backtest_*_demo_kelly.csv`; writes `outputs/oos_audit_report.md` + the three `*_oos_train.*` artifacts under `data/raw/`.  Re-run after any change that regenerates the flat or kelly logs.

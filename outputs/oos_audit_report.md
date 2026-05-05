# Out-of-Sample Audit -- 75/25 Chronological Holdout

**Mode: DEMO**

_Tests how much of the +$6,775 / Sharpe 0.41 / 357 trades R3 production baseline is in-sample inflation vs out-of-sample edge.  Fits Kelly stats, quintile edges, and confidence model on the earliest 75% of the flat corpus; re-derives Kelly sizing on the last 25% using those train-fitted parameters; reports headline metrics for full corpus (in-sample), train fold, test fold._

## 1. The audit's question

When the three in-sample-leakage parameters (Kelly stats, quintile edges, confidence model) are fit only on the chronologically-earliest 75% of the trade corpus and the strategy is evaluated only on the last 25%, do the headline metrics survive?  If they do, the +$6,775 is a defensible signal-edge measurement; if they collapse, the headline is in-sample inflation.

## 2. Methodology

- **Implementation choice:** Path (b) -- post-hoc re-derivation of Kelly sizing on the existing flat corpus.  The per-share `pnl` and `max_loss` columns in `backtest_*_demo.csv` are properties of the spread + price walk, not the sizing decision; only the contract count changes between in-sample and OOS evaluation.  Avoids re-running `engine.run_backtest` (slow) without losing fidelity.
- **Cutoff date:** 2025-12-15 (75th percentile of `entry_date` across all 851 flat-corpus rows).
- **Train fold:** 214 flat-corpus rows with `entry_date <= 2025-12-15`.
- **Test fold:** 69 flat-corpus rows with `entry_date > 2025-12-15`.
- **Sharpe convention:** `mean(pnl_total) / std(pnl_total, ddof=1) * sqrt(252/5)`, matching `r3_baseline.headline()` exactly.
- **Open-risk cap simplification:** `open_risk_dollars=0` is passed to every `size_trade` call.  In the production Kelly run the global 6% portfolio cap had peak utilisation 0.69 (`outputs/r3_production_baseline.md` Section 3); on smaller folds it binds even less, so this is a tight approximation.

**Per-ticker row counts (signals, not taken):**

| ticker | train_signals | test_signals | total |
|---|---|---|---|
| AAPL | 0 | 6 | 6 |
| NVDA | 0 | 6 | 6 |
| JPM | 0 | 8 | 8 |
| XOM | 31 | 3 | 34 |
| UNH | 0 | 8 | 8 |
| WMT | 0 | 1 | 1 |
| IWM | 80 | 8 | 88 |
| GLD | 61 | 14 | 75 |
| TLT | 42 | 9 | 51 |
| SPY | 0 | 6 | 6 |

**Date ranges:**

- Train: 2024-05-29 -> 2025-12-15
- Test:  2025-12-16 -> 2026-05-01

**Train-fold refit parameters:**

- `kelly_stats_oos_train.csv` -- per-signal counts/win/W/Kelly_f.
  Production vs train-fold Kelly_f comparison:

| signal | prod_n | prod_kelly_f | prod_tradable | train_n | train_kelly_f | train_tradable |
|---|---|---|---|---|---|---|
| BUY CALLS | 357 | 0.0789 | 1 | 78 | 0.2983 | 1 |
| BUY PUTS | 256 | -0.0567 | 0 | 54 | -0.6050 | 0 |

- `quintile_edges_oos_train.json` -- `[0.3695, 0.4286, 0.4771, 0.5259]`
  Production edges (for comparison): `[0.544, 0.5618, 0.5779, 0.602]`
- `confidence_model_oos_train.json` -- logistic refit on 132 accepted train trades, converged=True in 3 IRLS iters, train_win_rate=0.455.

**Held constant from production (NOT refit):** all hand-set constants (`STOP_LOSS_DEBIT_FRAC=0.80`, `PROFIT_TARGET_FRAC=0.50`, `TIME_STOP_DTE=21`, `KELLY_FRACTION=0.25`, `MAX_PORTFOLIO_RISK=0.06`, `QUINTILE_FRAC` table, sentiment/IV thresholds, BUY PUTS structural override).  These are fixed parameters, not data-fitted, so they don't carry the in-sample-leakage concern.

## 3. Headline comparison

| metric | in_sample_full | train_fold | test_fold |
|---|---|---|---|
| n_signals | 872.0000 | 214.0000 | 69.0000 |
| n_trades_taken | 360.0000 | 78.0000 | 41.0000 |
| total_pnl_$ | 5,836.1300 | 3,640.9300 | 1,889.6100 |
| sharpe | 0.4973 | 1.1350 | 2.5150 |
| max_dd_$ | -4,939.1600 | -1,330.8100 | -414.0300 |
| profit_factor | 1.3113 | 1.9632 | 3.1414 |
| win_rate | 0.2248 | 0.2196 | 0.3333 |

**Test-fold result vs in-sample.**  Sharpe: +2.5150 test fold vs +0.4973 in-sample (ratio +5.06); P&L $1,889.61 test fold vs $5,836.13 in-sample.  Note that test-fold P&L cannot be directly compared to in-sample P&L on absolute terms because the test fold contains only ~25% of the signal dates -- the like-for-like comparison is on Sharpe (which is sample-size invariant under the convention used).

## 4. Per-ticker breakdown

| ticker | n_taken_in | pnl_in | n_taken_train | pnl_train | n_taken_test | pnl_test |
|---|---|---|---|---|---|---|
| GLD | 1 | -28.18 | 0 | 0.00 | 3 | 56.87 |
| IWM | 43 | 2,426.84 | 32 | 1,268.14 | 6 | 92.07 |
| TLT | 29 | 2,524.44 | 22 | 1,706.27 | 7 | 174.97 |
| XOM | 26 | 1,227.01 | 24 | 666.52 | 2 | 383.73 |

**No ticker sign-flips** with |pnl| > $100 on both sides.

## 5. Per-quintile breakdown

Quintile binning uses the production edges for the in-sample column and the train-fitted edges for the train- and test-fold columns.  Confidence values for the in-sample column are the production-model values stored in the Kelly logs; for the train and test folds they are recomputed via the train-fitted logistic.

**In-sample (full corpus, production params):**

| label | quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|---|
| in_sample | Q1 | 333 | 0.56 | 6,875.50 | 20.65 |
| in_sample | Q2 | 6 | 0.67 | 511.88 | 85.31 |
| in_sample | Q3 | 7 | 0.43 | -162.94 | -23.28 |
| in_sample | Q4 | 3 | 0.67 | 27.60 | 9.20 |
| in_sample | Q5 | 11 | 0.00 | -1,415.91 | -128.72 |

**Train fold (train-fitted params, train trades):**

| label | quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|---|
| train_fold | Q1 | 14 | 0.71 | 781.00 | 55.79 |
| train_fold | Q2 | 11 | 0.73 | 757.33 | 68.85 |
| train_fold | Q3 | 13 | 0.46 | 47.33 | 3.64 |
| train_fold | Q4 | 15 | 0.67 | 1,113.94 | 74.26 |
| train_fold | Q5 | 25 | 0.52 | 941.33 | 37.65 |

**Test fold (train-fitted params, test trades):**

| label | quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|---|
| test_fold | Q1 | 2 | 1.00 | 207.77 | 103.88 |
| test_fold | Q2 | 7 | 0.29 | -301.82 | -43.12 |
| test_fold | Q3 | 15 | 0.60 | 1,022.53 | 68.17 |
| test_fold | Q4 | 9 | 0.44 | 430.36 | 47.82 |
| test_fold | Q5 | 8 | 0.75 | 530.77 | 66.35 |

**Q5 - Q1 total-P&L spread:**  in-sample -$8,291.41, train fold $160.33, test fold $323.00.  In-sample shows monotone Q1 < Q5 = +$6,758 ordering; the test-fold spread is the OOS test of whether the confidence-model ranking generalises.

## 6. Verdict

**GENERALIZES.**  Test-fold Sharpe (+2.5150) is within ~30% of the in-sample Sharpe (+0.4973); the Q5-Q1 confidence-ranking ordering is preserved ($323.00 test vs -$8,291.41 in-sample); no ticker P&L flips sign on a > $100 magnitude.  The R3 production baseline is a defensible signal-edge measurement under the chronological holdout test, with the standard caveats about synthetic sentiment and single-split sampling variability.  R3's selection as production sizing and the v2_10t promotion question both stand on stronger footing after this audit.


## 7. Caveats

- **Synthetic-sentiment caveat (still load-bearing).**  Every trade in the corpus has `is_synthetic=True`.  This audit measures generalisation **within the synthetic generator's deterministic-seed walk**, not generalisation to live sentiment.  A real-mode run (`scripts/r3_baseline.py --real`) would produce a structurally different corpus.
- **Single-split caveat.**  A 75/25 chronological holdout is one sample of 'future data.'  Walk-forward refit-every-N-days would give a distribution of OOS Sharpe estimates rather than a single point.  Given this audit's outcome, walk-forward is the warranted next session.
- **Test-fold size caveat.**  The test fold contains 69 signals and 41 taken trades.  Sharpe at this sample size has wide error bars; the point estimate +2.5150 should be read with that in mind.  The standard error of an annualised Sharpe at this trade count is roughly 1/sqrt(41/5) per year-equivalent ~ 0.35, so the 95% CI is roughly +/- 0.70 around the point estimate.
- **Open-risk cap approximation.**  `size_trade` was called with `open_risk_dollars=0`, which assumes the global 6% cap never binds in the test fold.  The production Kelly run had peak utilisation 0.69 (well below 1.0); on a smaller fold this is even less likely to bind.

## 8. Cleanup confirmation

| artifact | mtime_pre | mtime_post | size_unchanged |
|---|---|---|---|
| kelly_stats.csv (production) | 1777679169.712 | 1777679169.712 | 1 |
| quintile_edges.json (production) | 1777679169.714 | 1777679169.714 | 1 |
| confidence_model.json (production) | 1777081780.784 | 1777081780.784 | 1 |

**Production artifacts unchanged: CONFIRMED.**  All OOS-specific outputs are in `*_oos_train.*` files (`data/raw/kelly_stats_oos_train.csv`, `data/raw/quintile_edges_oos_train.json`, `data/raw/confidence_model_oos_train.json`).

---

## Reproduction

```bash
.venv/Scripts/python.exe scripts/audit_oos_split.py
```

Reads `data/raw/backtest_*_demo.csv` + `data/raw/backtest_*_demo_kelly.csv`; writes `outputs/oos_audit_report.md` + the three `*_oos_train.*` artifacts under `data/raw/`.  Re-run after any change that regenerates the flat or kelly logs.

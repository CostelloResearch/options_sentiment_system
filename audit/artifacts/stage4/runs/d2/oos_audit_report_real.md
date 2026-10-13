# Out-of-Sample Audit -- 75/25 Chronological Holdout

**Mode: REAL**

_Tests how much of the +$9,697 / Sharpe 1.17 / 295 trades R3 production baseline is in-sample inflation vs out-of-sample edge.  Fits Kelly stats, quintile edges, and confidence model on the earliest 75% of the flat corpus; re-derives Kelly sizing on the last 25% using those train-fitted parameters; reports headline metrics for full corpus (in-sample), train fold, test fold._

## 1. The audit's question

When the three in-sample-leakage parameters (Kelly stats, quintile edges, confidence model) are fit only on the chronologically-earliest 75% of the trade corpus and the strategy is evaluated only on the last 25%, do the headline metrics survive?  If they do, the +$9,697 is a defensible signal-edge measurement; if they collapse, the headline is in-sample inflation.

## 2. Methodology

- **Implementation choice:** Path (b) -- post-hoc re-derivation of Kelly sizing on the existing flat corpus.  The per-share `pnl` and `max_loss` columns in `backtest_*.csv` are properties of the spread + price walk, not the sizing decision; only the contract count changes between in-sample and OOS evaluation.  Avoids re-running `engine.run_backtest` (slow) without losing fidelity.
- **Cutoff date:** 2025-12-22 (75th percentile of `entry_date` across all 851 flat-corpus rows).
- **Train fold:** 382 flat-corpus rows with `entry_date <= 2025-12-22`.
- **Test fold:** 125 flat-corpus rows with `entry_date > 2025-12-22`.
- **Sharpe convention:** `mean(pnl_total) / std(pnl_total, ddof=1) * sqrt(252/5)`, matching `r3_baseline.headline()` exactly.
- **Open-risk cap simplification:** `open_risk_dollars=0` is passed to every `size_trade` call.  In the production Kelly run the global 6% portfolio cap had peak utilisation 0.69 (`outputs/r3_production_baseline.md` Section 3); on smaller folds it binds even less, so this is a tight approximation.

**Per-ticker row counts (signals, not taken):**

| ticker | train_signals | test_signals | total |
|---|---|---|---|
| AAPL | 20 | 9 | 29 |
| NVDA | 29 | 7 | 36 |
| JPM | 39 | 9 | 48 |
| XOM | 72 | 5 | 77 |
| UNH | 42 | 21 | 63 |
| WMT | 36 | 12 | 48 |
| IWM | 24 | 21 | 45 |
| GLD | 58 | 12 | 70 |
| TLT | 51 | 20 | 71 |
| SPY | 11 | 9 | 20 |

**Date ranges:**

- Train: 2025-05-08 -> 2025-12-22
- Test:  2025-12-23 -> 2026-05-04

**Train-fold refit parameters:**

- `kelly_stats_oos_train.csv` -- per-signal counts/win/W/Kelly_f.
  Production vs train-fold Kelly_f comparison:

| signal | prod_n | prod_kelly_f | prod_tradable | train_n | train_kelly_f | train_tradable |
|---|---|---|---|---|---|---|
| BUY CALLS | 298 | 0.2431 | 1 | 230 | 0.2295 | 1 |
| BUY PUTS | 154 | -0.7536 | 0 | 107 | -0.7096 | 0 |

- `quintile_edges_oos_train.json` -- `[0.3336, 0.404, 0.472, 0.5297]`
  Production edges (for comparison): `[0.1814, 0.2959, 0.3915, 0.4948]`
- `confidence_model_oos_train.json` -- logistic refit on 337 accepted train trades, converged=True in 3 IRLS iters, train_win_rate=0.439.

**Held constant from production (NOT refit):** all hand-set constants (`STOP_LOSS_DEBIT_FRAC=0.80`, `PROFIT_TARGET_FRAC=0.50`, `TIME_STOP_DTE=21`, `KELLY_FRACTION=0.25`, `MAX_PORTFOLIO_RISK=0.06`, `QUINTILE_FRAC` table, sentiment/IV thresholds, BUY PUTS structural override).  These are fixed parameters, not data-fitted, so they don't carry the in-sample-leakage concern.

## 3. Headline comparison

| metric | in_sample_full | train_fold | test_fold |
|---|---|---|---|
| n_signals | 507.0000 | 382.0000 | 125.0000 |
| n_trades_taken | 298.0000 | 230.0000 | 68.0000 |
| total_pnl_$ | 10,216.5700 | 7,246.8900 | 2,969.6800 |
| sharpe | 1.2812 | 1.2537 | 1.3590 |
| max_dd_$ | -1,396.0400 | -2,106.6500 | -1,067.1900 |
| profit_factor | 1.7807 | 1.7334 | 1.9265 |
| win_rate | 0.3314 | 0.3298 | 0.3360 |

**Test-fold result vs in-sample.**  Sharpe: +1.3590 test fold vs +1.2812 in-sample (ratio +1.06); P&L $2,969.68 test fold vs $10,216.57 in-sample.  Note that test-fold P&L cannot be directly compared to in-sample P&L on absolute terms because the test fold contains only ~25% of the signal dates -- the like-for-like comparison is on Sharpe (which is sample-size invariant under the convention used).

## 4. Per-ticker breakdown

| ticker | n_taken_in | pnl_in | n_taken_train | pnl_train | n_taken_test | pnl_test |
|---|---|---|---|---|---|---|
| AAPL | 23 | 420.34 | 15 | 103.02 | 8 | 317.31 |
| GLD | 31 | 2,390.25 | 29 | 2,477.87 | 2 | -87.62 |
| IWM | 4 | 257.91 | 3 | 441.91 | 1 | -184.00 |
| JPM | 45 | -835.64 | 36 | -75.88 | 9 | -759.76 |
| NVDA | 34 | 1,114.44 | 27 | 1,278.73 | 7 | -164.29 |
| SPY | 7 | 443.25 | 2 | 168.53 | 5 | 274.72 |
| TLT | 8 | -318.95 | 6 | -88.62 | 2 | -230.31 |
| UNH | 37 | 371.56 | 19 | -623.38 | 18 | 994.94 |
| WMT | 43 | 1,330.01 | 31 | -455.72 | 12 | 1,785.73 |
| XOM | 66 | 5,043.40 | 62 | 4,020.43 | 4 | 1,022.96 |

**Sign-flipping tickers (|pnl| > $100 in both columns):**

- **IWM**: in-sample $257.91 -> test fold -$184.00.
- **NVDA**: in-sample $1,114.44 -> test fold -$164.29.

**AAPL.**  Train fold: $103.02 on 15 taken trades.  Test fold: $317.31 on 8 taken trades (cutoff 2025-12-22).  `outputs/aapl_stop_diagnosis.md` is a synthetic-only diagnostic; a real-mode AAPL stop-cluster post-mortem has not been published.

## 5. Per-quintile breakdown

Quintile binning uses the production edges for the in-sample column and the train-fitted edges for the train- and test-fold columns.  Confidence values for the in-sample column are the production-model values stored in the Kelly logs; for the train and test folds they are recomputed via the train-fitted logistic.

**In-sample (full corpus, production params):**

| label | quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|---|
| in_sample | Q1 | 49 | 0.57 | 1,369.54 | 27.95 |
| in_sample | Q2 | 63 | 0.62 | 2,831.76 | 44.95 |
| in_sample | Q3 | 61 | 0.61 | 3,204.01 | 52.52 |
| in_sample | Q4 | 58 | 0.47 | 975.85 | 16.83 |
| in_sample | Q5 | 67 | 0.55 | 1,835.41 | 27.39 |

**Train fold (train-fitted params, train trades):**

| label | quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|---|
| train_fold | Q1 | 5 | 0.60 | 233.70 | 46.74 |
| train_fold | Q2 | 33 | 0.48 | 488.29 | 14.80 |
| train_fold | Q3 | 59 | 0.56 | 1,890.75 | 32.05 |
| train_fold | Q4 | 66 | 0.61 | 2,655.50 | 40.23 |
| train_fold | Q5 | 67 | 0.51 | 1,978.65 | 29.53 |

**Test fold (train-fitted params, test trades):**

| label | quintile | n | win_rate | total_pnl | avg_pnl |
|---|---|---|---|---|---|
| test_fold | Q1 | 1 | 1.00 | 127.14 | 127.14 |
| test_fold | Q2 | 5 | 0.60 | 206.75 | 41.35 |
| test_fold | Q3 | 27 | 0.48 | -335.44 | -12.42 |
| test_fold | Q4 | 11 | 0.55 | 1,107.78 | 100.71 |
| test_fold | Q5 | 24 | 0.79 | 1,863.45 | 77.64 |

**Q5 - Q1 total-P&L spread:**  in-sample $465.87, train fold $1,744.95, test fold $1,736.31.  In-sample shows monotone Q1 < Q5 = +$6,758 ordering; the test-fold spread is the OOS test of whether the confidence-model ranking generalises.

## 6. Verdict

**PARTIAL.**  Test-fold Sharpe (+1.3590) shows meaningful degradation vs in-sample (+1.2812; -6%) but remains positive.  Q5-Q1 ordering: test fold $1,736.31 vs in-sample $465.87 (preserved).  2 ticker P&L sign-flips with |pnl| > $100.  The +$9,697 baseline is partly in-sample-inflated -- some of the headline is a property of fitting and testing on the same dates, but a real OOS edge survives.  The R3 selection decision was made on numbers that overstate the underlying edge by a factor of roughly 0.9x in Sharpe terms.  The v2_10t promotion question should not be made on the current in-sample numbers; refit + holdout-validate v2_10t on the same 75/25 split before any decision.


## 7. Caveats

- **Real-corpus single-regime caveat.**  Trade corpus drawn from the real-news flat backtest covering ~12 months of headlines (~2025-05 to 2026-05).  This audit measures generalisation **within a single news regime**, not across regimes; per-ticker P&L is heavily concentrated in a small subset of names (see PROJECT_STATE Section 10.2).  A structurally different corpus (different ticker mix, different macro window) would produce different in-sample-vs-OOS dynamics.
- **Single-split caveat.**  A 75/25 chronological holdout is one sample of 'future data.'  Walk-forward refit-every-N-days would give a distribution of OOS Sharpe estimates rather than a single point.  Given this audit's outcome, walk-forward is the warranted next session.
- **Test-fold size caveat.**  The test fold contains 125 signals and 68 taken trades.  Sharpe at this sample size has wide error bars; the point estimate +1.3590 should be read with that in mind.  The standard error of an annualised Sharpe at this trade count is roughly 1/sqrt(68/5) per year-equivalent ~ 0.27, so the 95% CI is roughly +/- 0.54 around the point estimate.
- **Open-risk cap approximation.**  `size_trade` was called with `open_risk_dollars=0`, which assumes the global 6% cap never binds in the test fold.  The production Kelly run had peak utilisation 0.69 (well below 1.0); on a smaller fold this is even less likely to bind.

## 8. Cleanup confirmation

| artifact | mtime_pre | mtime_post | size_unchanged |
|---|---|---|---|
| kelly_stats.csv (production) | 1791661762.193 | 1791661762.193 | 1 |
| quintile_edges.json (production) | 1791661762.201 | 1791661762.201 | 1 |
| confidence_model.json (production) | 1777081780.784 | 1777081780.784 | 1 |

**Production artifacts unchanged: CONFIRMED.**  All OOS-specific outputs are in `*_oos_train.*` files (`data/raw/kelly_stats_oos_train.csv`, `data/raw/quintile_edges_oos_train.json`, `data/raw/confidence_model_oos_train.json`).

---

## Reproduction

```bash
.venv/Scripts/python.exe scripts/audit_oos_split.py --real
```

Reads `data/raw/backtest_*.csv` + `data/raw/backtest_*_kelly.csv`; writes `outputs/oos_audit_report_real.md` + the three `*_oos_train_real.*` artifacts under `data/raw/`.  Re-run after any change that regenerates the flat or kelly logs.

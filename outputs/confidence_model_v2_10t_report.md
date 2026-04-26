# Logistic Confidence Refit -- v2_10t

_Refit on the 2026-04-25 universe rebuild (10 tickers, 613 accepted trades)._

_Versioned filename `confidence_model_v2_10t.json` -- production loader still reads `confidence_model.json` (the 5-ticker fit).  Promote by overwrite/rename when ready._

## 1. Fit summary

```
n=613  train_win_rate=0.502  converged=True in 2 iters  l2=0.5
intercept = +0.0100  (bias at mean-feature point)
coefficients (standardised space):
  abs_sentiment           -0.0301
  iv_rank                 -0.1373
  sent_momentum_3d        +0.0610
  sec_aligned             +0.0000
  log_headline_count      -0.0978
  log_days_to_earnings    -0.0000
train log-loss = 0.6890  brier = 0.2479
intercept = +0.0100
```

## 2. Coefficients (new vs old 5-ticker)

| feature | mean_new | std_new | beta_new | beta_old_5t |
|---|---|---|---|---|
| abs_sentiment | 0.3581 | 0.0946 | -0.0301 | -0.0302 |
| iv_rank | 0.1567 | 0.0833 | -0.1373 | -0.0763 |
| sent_momentum_3d | 0.0078 | 0.1906 | 0.0610 | 0.0380 |
| sec_aligned | 0.0000 | 1.0000 | 0.0000 | 0.0000 |
| log_headline_count | 3.0519 | 0.5293 | -0.0978 | -0.0931 |
| log_days_to_earnings | 4.1109 | 1.0000 | -0.0000 | 0.0000 |

## 3. In-sample quintile P&L (new v2 model)

| quintile | n | mean_p | mean_ret | win_rate |
|---|---|---|---|---|
| Q1 (lowest) | 123 | 0.4405 | -8.4822 | 0.3984 |
| Q2 | 122 | 0.4745 | 8.9348 | 0.5656 |
| Q3 | 123 | 0.5015 | -6.0907 | 0.4553 |
| Q4 | 122 | 0.5275 | 5.0489 | 0.5410 |
| Q5 (highest) | 123 | 0.5682 | 4.0524 | 0.5528 |

## 4. In-sample quintile P&L (OLD 5-ticker model on new corpus)

| quintile | n | mean_p | mean_ret | win_rate |
|---|---|---|---|---|
| Q1 (lowest) | 123 | 0.5290 | -6.5467 | 0.4065 |
| Q2 | 122 | 0.5533 | 6.6216 | 0.5574 |
| Q3 | 123 | 0.5699 | -6.7806 | 0.4472 |
| Q4 | 122 | 0.5893 | 3.2874 | 0.5492 |
| Q5 (highest) | 123 | 0.6184 | 6.8483 | 0.5528 |


**Q5-Q1 spread (NEW v2 model):** +12.5346 (Q1=-8.4822, Q5=+4.0524)

## 5. Notes

- Coefficient sign flips between the 5-ticker fit and this 10-ticker fit are diagnostic: a feature that mattered in tech may not survive on a sector-diverse corpus.  Interpret in the context of the per-sector decay results (`outputs/sector_decay_analysis.md`).
- Quintile edges in the production sizer (`data/raw/quintile_edges.json`) are NOT updated by this script -- they're still calibrated against the old model.  Promotion of the v2 model into production should refit the edges via `position_sizer.compute_and_save_quintile_edges` on the new corpus.
- The new corpus is a fresh strategy: do NOT compare the Q5-Q1 spread reported here against the +15.76pp documented in PROJECT_STATE for the 5-ticker fit.  Different universe, different trade distribution.

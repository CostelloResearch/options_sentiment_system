# Confidence Model Rebuild -- Logistic Regression

_Target: probability a trade closes with pnl_pct > 0.  Features documented in signals/confidence_model.py._

## Fit summary

```
n=417  train_win_rate=0.571  converged=True in 3 iters  l2=0.5
intercept = +0.2860  (bias at mean-feature point)
coefficients (standardised space):
  abs_sentiment           -0.0302
  iv_rank                 -0.0763
  sent_momentum_3d        +0.0380
  sec_aligned             +0.0000
  log_headline_count      -0.0931
  log_days_to_earnings    +0.0000
train log-loss = 0.6811  brier = 0.2440
```

## In-sample quintile performance

### LOGISTIC MODEL (new)

| quintile | n | mean_p | mean_ret | win_rate |
|---|---|---|---|---|
| Q1 (lowest) | 84 | 0.5284 | 0.7095 | 0.4762 |
| Q2 | 83 | 0.5536 | 10.3842 | 0.6024 |
| Q3 | 83 | 0.5692 | 12.3202 | 0.6506 |
| Q4 | 83 | 0.5874 | -0.9114 | 0.5060 |
| Q5 (highest) | 84 | 0.6151 | 10.7220 | 0.6190 |

### LEGACY TIERED (v1)

| quintile | n | mean_p | mean_ret | win_rate |
|---|---|---|---|---|
| Q1 (lowest) | 84 | 0.1036 | 2.6182 | 0.4881 |
| Q2 | 83 | 0.2063 | 8.1067 | 0.5783 |
| Q3 | 83 | 0.2845 | 9.9073 | 0.6024 |
| Q4 | 83 | 0.3672 | 19.0017 | 0.6506 |
| Q5 (highest) | 84 | 0.5163 | -6.2282 | 0.5357 |

**Q5 - Q1 spread, LEGACY:** -8.8464  (Q1=+2.6182, Q5=-6.2282)

**Q5 - Q1 spread, MODEL:**  +10.0125  (Q1=+0.7095, Q5=+10.7220)

## Verdict

PASS: Q5 outperforms Q1 under the logistic confidence.

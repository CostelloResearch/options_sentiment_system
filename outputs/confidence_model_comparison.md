# Confidence Model Comparison: Logistic vs Magnitude

## 1. Training summaries

### Logistic (p(win))
```
n=417  train_win_rate=0.571  converged=True in 3 iters  l2=0.5
intercept = +0.2860  (bias at mean-feature point)
coefficients (standardised space):
  abs_sentiment           -0.0302
  iv_rank                 -0.0763
  sent_momentum_3d        +0.0381
  sec_aligned             +0.0000
  log_headline_count      -0.0931
  log_days_to_earnings    -0.0000
train log-loss = 0.6811  brier = 0.2440
```

### Magnitude (6 features)
```
n=417  RMSE=55.629  R2=-0.0036  l2=0.5  interactions=False
intercept = +7.0394  (baseline expected pnl_pct at mean-feature point)
coefficients (standardised space, expected pnl_pct per 1-sd feature move):
  abs_sentiment           +4.6733
  iv_rank                 +4.3073
  sent_momentum_3d        -1.4234
  sec_aligned             +0.0000
  log_headline_count      -6.0177
  log_days_to_earnings    +0.0000
norm anchors (raw pnl_pct at 0/20/40/60/80/100 pct): [-13.54, -1.08, 4.22, 8.74, 14.9, 32.06]
```

### Magnitude (8 features with interactions)
```
n=417  RMSE=55.240  R2=+0.0104  l2=0.5  interactions=True
intercept = +4.3079  (baseline expected pnl_pct at mean-feature point)
coefficients (standardised space, expected pnl_pct per 1-sd feature move):
  abs_sentiment           +5.4052
  iv_rank                 +4.4331
  sent_momentum_3d        +10.9968
  sec_aligned             +0.0000
  log_headline_count      -5.3922
  log_days_to_earnings    -0.0000
  sent_x_ivrank           -4.8470
  sent_x_abs_sent         -18.7999
norm anchors (raw pnl_pct at 0/20/40/60/80/100 pct): [-44.18, -13.89, -4.5, 6.71, 21.46, 91.86]
```

## 2. Holdout validation (magnitude)

### 6-feature

#### time_75_25

- RMSE: **56.392**
- Q1 mean_ret: +37.319  -- Q5 mean_ret: -0.126  -- Q5-Q1: **-37.445**
- Best quintile: **Q1**  (Q5 highest? **False**)

| quintile | n | mean_p | mean_ret | win_rate |
|---|---|---|---|---|
| Q1 | 21 | 0.2939 | 37.3186 | 0.7619 |
| Q2 | 21 | 0.4905 | 36.4210 | 0.8095 |
| Q3 | 20 | 0.6387 | 27.8040 | 0.6500 |
| Q4 | 21 | 0.7772 | 18.7481 | 0.6190 |
| Q5 | 21 | 0.8835 | -0.1262 | 0.5238 |

#### ticker_LOO

- RMSE: **62.416**
- Q1 mean_ret: +10.233  -- Q5 mean_ret: -5.136  -- Q5-Q1: **-15.370**
- Best quintile: **Q3**  (Q5 highest? **False**)

| quintile | n | mean_p | mean_ret | win_rate |
|---|---|---|---|---|
| Q1 | 84 | 0.1318 | 10.2333 | 0.6548 |
| Q2 | 83 | 0.2863 | 5.9575 | 0.5783 |
| Q3 | 83 | 0.4432 | 14.9802 | 0.6265 |
| Q4 | 83 | 0.6633 | 7.2663 | 0.5301 |
| Q5 | 84 | 0.8440 | -5.1363 | 0.4643 |


### 8-feature

#### time_75_25

- RMSE: **59.281**
- Q1 mean_ret: -0.224  -- Q5 mean_ret: +31.387  -- Q5-Q1: **+31.611**
- Best quintile: **Q4**  (Q5 highest? **False**)

| quintile | n | mean_p | mean_ret | win_rate |
|---|---|---|---|---|
| Q1 | 21 | 0.1507 | -0.2238 | 0.4762 |
| Q2 | 21 | 0.2894 | 11.5671 | 0.6190 |
| Q3 | 20 | 0.4845 | 38.4870 | 0.8500 |
| Q4 | 21 | 0.6910 | 39.4567 | 0.7619 |
| Q5 | 21 | 0.8763 | 31.3871 | 0.6667 |

#### ticker_LOO

- RMSE: **64.968**
- Q1 mean_ret: +8.872  -- Q5 mean_ret: -4.918  -- Q5-Q1: **-13.790**
- Best quintile: **Q3**  (Q5 highest? **False**)

| quintile | n | mean_p | mean_ret | win_rate |
|---|---|---|---|---|
| Q1 | 84 | 0.1332 | 8.8723 | 0.6310 |
| Q2 | 83 | 0.2777 | 6.9717 | 0.5783 |
| Q3 | 83 | 0.4444 | 11.8771 | 0.6145 |
| Q4 | 83 | 0.6171 | 10.5118 | 0.5783 |
| Q5 | 84 | 0.8243 | -4.9181 | 0.4524 |


## 3. R3 backtest A/B

| model | n_signals | n_trades | total_pnl | sharpe | max_dd | profit_factor | win_rate |
|---|---|---|---|---|---|---|---|
| flat (1-contract baseline) | 562 | 417 | 33192.0200 | 1.0572 | -15328.3800 | 1.6469 | 0.4235 |
| R3 x logistic | 562 | 358 | 14872.4700 | 0.5415 | -15371.4200 | 1.3054 | 0.3416 |
| R3 x magnitude (6 features) [FAILED holdouts] | 562 | 358 | 13680.5400 | 0.5078 | -15352.5400 | 1.2917 | 0.3416 |

### Quintile P&L under LOGISTIC R3

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 71 | 0.5287 | 0.4366 | 25.1800 | 1787.7100 |
| Q2 | 73 | 0.5538 | 0.5616 | 53.2100 | 3884.5100 |
| Q3 | 72 | 0.5691 | 0.6111 | 88.8300 | 6395.8700 |
| Q4 | 67 | 0.5886 | 0.4776 | -12.1600 | -814.7500 |
| Q5 | 75 | 0.6150 | 0.5867 | 48.2600 | 3619.1300 |

### Quintile P&L under MAGNITUDE R3 (magnitude (6 features) [FAILED holdouts])

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 75 | 0.1333 | 0.5067 | -62.9500 | -4720.8800 |
| Q2 | 69 | 0.3056 | 0.5797 | 49.7800 | 3434.6200 |
| Q3 | 69 | 0.4878 | 0.5217 | 42.4500 | 2928.7700 |
| Q4 | 71 | 0.7068 | 0.5211 | 90.4900 | 6424.4800 |
| Q5 | 74 | 0.8626 | 0.5541 | 75.8600 | 5613.5500 |

## 4. Ranking disagreements (top 10)

_Signals where the two models disagree most about ranking (percent-rank of confidence across the accepted-trade population).  Large disagreements are candidate false-positive filters._

| ticker | entry_date | signal | sentiment_score | iv_rank | pnl_pct | conf_logistic | conf_magnitude | rank_diff |
|---|---|---|---|---|---|---|---|---|
| AAPL | 2026-04-23 00:00:00 | BUY PUTS | -0.7109 | 0.2405 | 4.2100 | 0.5017 | 0.9310 | 0.9736 |
| AAPL | 2026-04-22 00:00:00 | BUY PUTS | -0.6582 | 0.2406 | 3.3200 | 0.5107 | 0.8991 | 0.9400 |
| NVDA | 2025-06-17 00:00:00 | BUY CALLS | 0.2516 | 0.0149 | 69.7700 | 0.6141 | 0.0283 | -0.9161 |
| AAPL | 2026-04-24 00:00:00 | BUY PUTS | -0.6498 | 0.2299 | -2.4200 | 0.5261 | 0.9330 | 0.8993 |
| QQQ | 2025-10-09 00:00:00 | BUY CALLS | 0.2721 | 0.0144 | -11.1400 | 0.6216 | 0.1004 | -0.8969 |
| NVDA | 2025-06-25 00:00:00 | BUY CALLS | 0.2682 | 0.0000 | 54.5900 | 0.6141 | 0.0882 | -0.8825 |
| AAPL | 2025-01-10 00:00:00 | BUY CALLS | 0.6154 | 0.2909 | -77.2700 | 0.5031 | 0.8371 | 0.8729 |
| AAPL | 2025-12-24 00:00:00 | BUY CALLS | 0.3060 | 0.0112 | -85.0400 | 0.6234 | 0.1428 | -0.8585 |
| AAPL | 2026-01-08 00:00:00 | BUY CALLS | 0.2708 | 0.0000 | -90.0700 | 0.6111 | 0.1094 | -0.8441 |
| QQQ | 2025-07-24 00:00:00 | BUY CALLS | 0.3420 | 0.0000 | 7.2200 | 0.6112 | 0.1177 | -0.8345 |

## 5. Verdict

- 6-feature magnitude clears both holdouts: **False**
- 8-feature magnitude clears both holdouts: **False**
- R3 backtest: magnitude beats logistic: **False** (total_pnl +13,680.54 vs +14,872.47)
- Q5 flips positive under magnitude: **True** (Q5 pnl magnitude=+5,613.55 vs logistic=+3,619.13)

**Decision: KEEP logistic**

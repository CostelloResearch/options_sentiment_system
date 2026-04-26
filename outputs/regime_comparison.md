# Three-Regime Allocation Comparison

_Demo-mode, 500-day window, 5 tickers.  Flat corpus reused across all regimes; Kelly stats and confidence quintile edges rebuilt once from that corpus._

## 1. Headline metrics

| regime | n_signals | n_trades | total_pnl | sharpe | max_dd | profit_factor | win_rate |
|---|---|---|---|---|---|---|---|
| flat (baseline) | 562 | 417 | 33192.0200 | 1.0572 | -15328.3800 | 1.6469 | 0.4235 |
| segregated Kelly (current) | 562 | 288 | -3214.9000 | -0.1220 | -12864.9400 | 0.9233 | 0.2794 |
| REGIME 1: buckets 4.5/1.0/0.25/0.25 | 562 | 259 | 1654.6300 | 0.0540 | -14650.3300 | 1.0358 | 0.2509 |
| REGIME 2: Variant C BUY PUTS (45 DTE $10w) | 562 | 302 | -7487.8100 | -0.3286 | -12551.0300 | 0.8067 | 0.2883 |
| REGIME 3: no buckets, quintile per-trade | 562 | 358 | 12604.1700 | 0.4578 | -17054.9800 | 1.2541 | 0.3416 |

## 2. BUY PUTS bucket utilization + block rate

_For R3, `bucket_cap_$` = the global 6% portfolio cap ($6,000 on the $100k paper account); `pct_blocked` counts portfolio-cap rejections._

| regime | bucket_cap_$ | n_evaluations | mean_utilization | peak_utilization | n_blocked | pct_blocked |
|---|---|---|---|---|---|---|
| current | 3000.0000 | 168 | 0.8795 | 1.4259 | 98 | 0.5833 |
| R1 | 4500.0000 | 168 | 0.7741 | 1.2915 | 82 | 0.4881 |
| R2 | 3000.0000 | 168 | 0.7759 | 1.1938 | 84 | 0.5000 |
| R3 | 6000.0000 | 168 | 0.6063 | 1.2148 | 49 | 0.2917 |

## 3. Confidence quintile P&L after sizing

_Fixed quintile edges (derived once from flat corpus): [0.4745, 0.5114, 0.5492, 0.5973]_

### current segregated Kelly

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 47 | 0.4243 | 0.3830 | 29.3800 | 1381.0100 |
| Q2 | 56 | 0.4942 | 0.5357 | -15.4700 | -866.4700 |
| Q3 | 54 | 0.5301 | 0.6852 | 74.1600 | 4004.4300 |
| Q4 | 63 | 0.5725 | 0.5714 | -45.1100 | -2841.8300 |
| Q5 | 68 | 0.6333 | 0.5294 | -71.9400 | -4892.0400 |

### REGIME 1

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 41 | 0.4276 | 0.4146 | 100.3200 | 4113.1200 |
| Q2 | 52 | 0.4953 | 0.5000 | -2.9800 | -154.7600 |
| Q3 | 47 | 0.5310 | 0.6809 | 107.1700 | 5036.8900 |
| Q4 | 57 | 0.5724 | 0.5614 | -33.9900 | -1937.3500 |
| Q5 | 62 | 0.6327 | 0.5484 | -87.1500 | -5403.2700 |

### REGIME 2

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 50 | 0.4253 | 0.3800 | -17.4300 | -871.3900 |
| Q2 | 57 | 0.4944 | 0.4737 | -76.5700 | -4364.6700 |
| Q3 | 60 | 0.5307 | 0.6833 | 52.7500 | 3164.7200 |
| Q4 | 64 | 0.5718 | 0.5469 | -55.0200 | -3521.3500 |
| Q5 | 71 | 0.6321 | 0.5634 | -26.6900 | -1895.1200 |

### REGIME 3

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 71 | 0.4225 | 0.4648 | 130.6700 | 9277.2800 |
| Q2 | 74 | 0.4939 | 0.4865 | -14.2700 | -1056.0500 |
| Q3 | 70 | 0.5307 | 0.6571 | 102.2600 | 7158.1400 |
| Q4 | 68 | 0.5721 | 0.5588 | 6.5600 | 446.2500 |
| Q5 | 75 | 0.6324 | 0.5200 | -42.9500 | -3221.4500 |

## 4. Trade counts per strategy

| signal | flat | current | R1 | R2 | R3 |
|---|---|---|---|---|---|
| BUY CALLS | 249 | 218 | 173 | 218 | 239 |
| BUY PUTS | 168 | 70 | 86 | 84 | 119 |

## 5. Regime definitions

- **REGIME 1** -- STRATEGY_BUCKETS = {'BUY PUTS': 0.045, 'BUY CALLS': 0.01, 'SELL PUTS': 0.0025, 'SELL CALLS': 0.0025} (sum = 6.0%)
- **REGIME 2** -- BUY PUTS overridden to 45 DTE / $10 width / long 0.55 delta; buckets unchanged (3.0 / 1.5 / 0.75 / 0.75)
- **REGIME 3** -- STRATEGY_BUCKETS disabled; per-trade cap by confidence quintile: {'Q1': 0.001, 'Q2': 0.002, 'Q3': 0.003, 'Q4': 0.005, 'Q5': 0.008}

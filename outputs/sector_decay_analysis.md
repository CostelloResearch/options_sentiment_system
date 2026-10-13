# Signal Decay -- Per-Sector Segmentation

_2026-04-25 universe rebuild: 10 tickers across 9 sectors and 3 asset classes._

**Critical test:** is the historical BUY CALLS / BUY PUTS / SELL PUTS edge documented on the 5-ticker tech-heavy universe consistent across sectors, or was it concentrated in tech?

## 1. Headline by signal (universe-wide)

| segment | best_horizon_d | n_at_best | max_risk_adj | max_mean_ret | verdict |
|---|---|---|---|---|---|
| BUY CALLS | 20 | 118 | 0.9085 | 0.0354 | TRADE |
| BUY PUTS | 1 | 71 | -0.2290 | -0.0029 | DISABLE |
| SELL CALLS | 1 | 51 | -0.0809 | -0.0010 | DISABLE |
| SELL PUTS | 10 | 30 | 1.1106 | 0.0414 | TRADE |

## 2. Headline by sector

| segment | best_horizon_d | n_at_best | max_risk_adj | max_mean_ret | verdict |
|---|---|---|---|---|---|
| BroadMarket | 20 | 1 | 0.0000 | -0.0054 | DISABLE |
| Commodity | 1 | 75 | -0.1614 | -0.0024 | DISABLE |
| ConsumerStaples | 1 | 1 | 0.0000 | -0.0209 | DISABLE |
| Energy | 10 | 34 | 0.4151 | 0.0197 | TRADE |
| Financials | 20 | 7 | 3.6315 | 0.0760 | TRADE |
| FixedIncome | 10 | 51 | 0.4706 | 0.0102 | TRADE |
| Healthcare | 1 | 8 | -0.5785 | -0.0078 | DISABLE |
| SmallCapEquity | 20 | 87 | 0.3889 | 0.0227 | TRADE |
| Technology | 10 | 8 | 0.1154 | 0.0104 | TRADE |

## 3. Headline by asset class

| segment | best_horizon_d | n_at_best | max_risk_adj | max_mean_ret | verdict |
|---|---|---|---|---|---|
| Commodity | 1 | 75 | -0.1614 | -0.0024 | DISABLE |
| Equity | 10 | 145 | 0.1283 | 0.0075 | TRADE |
| FixedIncome | 10 | 51 | 0.4706 | 0.0102 | TRADE |

## 4. Sector x Signal cross-tab (headline)

`mean_ret_{h}d` = mean directional underlying return at horizon h, signed so + = trade went the right way. A row with positive numbers across horizons is a sector that carries that signal type. A mostly-negative row exposes a tech-only artifact.

| sector | signal | n_signals | mean_ret_5d | n_5d | mean_ret_10d | n_10d | mean_ret_20d | n_20d |
|---|---|---|---|---|---|---|---|---|
| BroadMarket | BUY CALLS | 3 | 0.0081 | 3 | - | 0 | - | 0 |
| Commodity | BUY CALLS | 3 | -0.0145 | 3 | -0.0005 | 3 | 0.0968 | 3 |
| Energy | BUY CALLS | 27 | 0.0029 | 27 | 0.0150 | 27 | 0.0362 | 27 |
| Financials | BUY CALLS | 8 | 0.0276 | 8 | 0.0713 | 7 | 0.0760 | 7 |
| FixedIncome | BUY CALLS | 40 | 0.0049 | 40 | 0.0106 | 40 | 0.0173 | 40 |
| Healthcare | BUY CALLS | 3 | - | 0 | - | 0 | - | 0 |
| SmallCapEquity | BUY CALLS | 38 | 0.0101 | 38 | 0.0162 | 38 | 0.0370 | 38 |
| Technology | BUY CALLS | 9 | 0.0160 | 7 | 0.0570 | 6 | 0.0945 | 3 |
| BroadMarket | BUY PUTS | 3 | -0.0401 | 3 | -0.0639 | 3 | -0.1262 | 1 |
| Commodity | BUY PUTS | 17 | -0.0215 | 17 | -0.0321 | 17 | -0.0485 | 17 |
| ConsumerStaples | BUY PUTS | 1 | -0.0209 | 1 | -0.0580 | 1 | -0.0726 | 1 |
| Energy | BUY PUTS | 1 | -0.0077 | 1 | -0.0292 | 1 | -0.1302 | 1 |
| FixedIncome | BUY PUTS | 6 | -0.0034 | 6 | 0.0007 | 6 | -0.0279 | 6 |
| Healthcare | BUY PUTS | 5 | -0.1006 | 5 | -0.1749 | 5 | -0.3562 | 5 |
| SmallCapEquity | BUY PUTS | 35 | -0.0046 | 35 | -0.0081 | 34 | -0.0080 | 34 |
| Technology | BUY PUTS | 3 | -0.0517 | 3 | -0.1293 | 2 | -0.2143 | 2 |
| Commodity | SELL CALLS | 39 | -0.0074 | 39 | -0.0105 | 39 | -0.0174 | 39 |
| Energy | SELL CALLS | 6 | 0.0095 | 6 | 0.0264 | 6 | -0.0297 | 6 |
| FixedIncome | SELL CALLS | 5 | 0.0061 | 5 | -0.0062 | 5 | -0.0007 | 5 |
| SmallCapEquity | SELL CALLS | 1 | -0.0083 | 1 | 0.0164 | 1 | -0.0395 | 1 |
| Commodity | SELL PUTS | 16 | 0.0135 | 16 | 0.0247 | 16 | 0.0226 | 16 |
| SmallCapEquity | SELL PUTS | 14 | 0.0225 | 14 | 0.0478 | 14 | 0.0630 | 14 |

## 5. Per-sector decay curves

### BroadMarket  -> **DISABLE**

Optimal horizon: **20d**  (risk_adj = +0.000, mean = -0.54%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |    6 | -0.54% | +1.30% | -0.418 | -6.644 |
|  3d |    6 | -1.37% | +1.86% | -0.741 | -6.788 |
|  5d |    6 | -1.60% | +2.71% | -0.589 | -4.182 |
| 10d |    3 | -6.39% | +3.06% | -2.085 | -10.465 |
| 20d |    1 | -12.62% | +0.00% | +0.000 | +0.000 |

### Commodity  -> **DISABLE**

Optimal horizon: **1d**  (risk_adj = -0.161, mean = -0.24%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   75 | -0.24% | +1.46% | -0.161 | -2.562 |
|  3d |   75 | -0.38% | +2.18% | -0.175 | -1.601 |
|  5d |   75 | -0.64% | +2.57% | -0.249 | -1.770 |
| 10d |   75 | -0.75% | +3.32% | -0.226 | -1.135 |
| 20d |   75 | -1.14% | +5.73% | -0.198 | -0.704 |

### ConsumerStaples  -> **DISABLE**

Optimal horizon: **1d**  (risk_adj = +0.000, mean = -2.09%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |    1 | -3.89% | +0.00% | +0.000 | +0.000 |
|  3d |    1 | -3.49% | +0.00% | +0.000 | +0.000 |
|  5d |    1 | -2.09% | +0.00% | +0.000 | +0.000 |
| 10d |    1 | -5.80% | +0.00% | +0.000 | +0.000 |
| 20d |    1 | -7.26% | +0.00% | +0.000 | +0.000 |

### Energy  -> **TRADE**

Optimal horizon: **10d**  (risk_adj = +0.415, mean = +1.97%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   34 | -0.00% | +1.35% | -0.000 | -0.006 |
|  3d |   34 | +0.24% | +1.94% | +0.127 | +1.159 |
|  5d |   34 | +0.37% | +2.54% | +0.147 | +1.041 |
| 10d |   34 | +1.57% | +3.79% | +0.415 | +2.084 |
| 20d |   34 | +1.97% | +5.81% | +0.339 | +1.205 |

### Financials  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +3.631, mean = +7.60%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |    8 | +0.02% | +1.93% | +0.011 | +0.175 |
|  3d |    8 | +0.55% | +2.96% | +0.185 | +1.694 |
|  5d |    8 | +2.76% | +2.75% | +1.005 | +7.132 |
| 10d |    7 | +7.13% | +2.64% | +2.699 | +13.549 |
| 20d |    7 | +7.60% | +2.09% | +3.631 | +12.891 |

### FixedIncome  -> **TRADE**

Optimal horizon: **10d**  (risk_adj = +0.471, mean = +1.02%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   51 | +0.07% | +0.72% | +0.095 | +1.503 |
|  3d |   51 | +0.26% | +1.06% | +0.248 | +2.274 |
|  5d |   51 | +0.41% | +1.36% | +0.298 | +2.118 |
| 10d |   51 | +0.78% | +1.65% | +0.471 | +2.362 |
| 20d |   51 | +1.02% | +2.41% | +0.425 | +1.508 |

### Healthcare  -> **DISABLE**

Optimal horizon: **1d**  (risk_adj = -0.579, mean = -0.78%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |    8 | -0.78% | +1.35% | -0.579 | -9.184 |
|  3d |    7 | -3.56% | +4.43% | -0.804 | -7.369 |
|  5d |    5 | -10.06% | +6.01% | -1.672 | -11.873 |
| 10d |    5 | -17.49% | +3.01% | -5.812 | -29.175 |
| 20d |    5 | -35.62% | +3.59% | -9.934 | -35.262 |

### SmallCapEquity  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.389, mean = +2.27%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   88 | +0.24% | +1.57% | +0.154 | +2.444 |
|  3d |   88 | +0.49% | +1.97% | +0.249 | +2.283 |
|  5d |   88 | +0.60% | +2.37% | +0.255 | +1.807 |
| 10d |   87 | +1.18% | +3.38% | +0.348 | +1.746 |
| 20d |   87 | +2.27% | +5.83% | +0.389 | +1.380 |

### Technology  -> **TRADE**

Optimal horizon: **10d**  (risk_adj = +0.115, mean = +1.04%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   12 | -0.00% | +1.33% | -0.002 | -0.025 |
|  3d |   11 | -0.61% | +3.38% | -0.180 | -1.650 |
|  5d |   10 | -0.43% | +5.20% | -0.083 | -0.591 |
| 10d |    8 | +1.04% | +9.03% | +0.115 | +0.580 |
| 20d |    5 | -2.90% | +17.89% | -0.162 | -0.575 |

## 6. Notes

- Sample sizes per sector are smaller than the universe-wide decay table by ~10x.  Treat sector verdicts as directional, not definitive; the small-sample warning from `outputs/signal_decay_analysis.md` applies a fortiori per sector.
- The cross-tab uses underlying directional returns, not option P&L, so structure choices (60 DTE BUY PUTS, 0.25-delta short, etc.) don't confound the comparison across sectors.
- An honest read: if BUY PUTS shows positive mean_ret in Technology and ~zero everywhere else, that is the answer.  Do not paper over it by widening confidence intervals.

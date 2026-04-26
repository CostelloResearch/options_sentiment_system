# Signal Decay -- Per-Sector Segmentation

_2026-04-25 universe rebuild: 10 tickers across 9 sectors and 3 asset classes._

**Critical test:** is the historical BUY CALLS / BUY PUTS / SELL PUTS edge documented on the 5-ticker tech-heavy universe consistent across sectors, or was it concentrated in tech?

## 1. Headline by signal (universe-wide)

| segment | best_horizon_d | n_at_best | max_risk_adj | max_mean_ret | verdict |
|---|---|---|---|---|---|
| BUY CALLS | 20 | 348 | 0.3979 | 0.0203 | TRADE |
| BUY PUTS | 20 | 228 | 0.0026 | 0.0002 | DISABLE |
| SELL CALLS | 10 | 114 | -0.1059 | -0.0041 | DISABLE |
| SELL PUTS | 10 | 108 | 0.2907 | 0.0197 | TRADE |

## 2. Headline by sector

| segment | best_horizon_d | n_at_best | max_risk_adj | max_mean_ret | verdict |
|---|---|---|---|---|---|
| BroadMarket | 10 | 116 | 0.2105 | 0.0070 | TRADE |
| Commodity | 1 | 75 | -0.1614 | -0.0024 | DISABLE |
| ConsumerStaples | 20 | 72 | 0.1143 | 0.0074 | TRADE |
| Energy | 10 | 34 | 0.4151 | 0.0197 | TRADE |
| Financials | 1 | 83 | -0.1123 | -0.0014 | DISABLE |
| FixedIncome | 10 | 51 | 0.4706 | 0.0102 | TRADE |
| Healthcare | 20 | 93 | 0.4931 | 0.0478 | TRADE |
| SmallCapEquity | 20 | 87 | 0.3889 | 0.0227 | TRADE |
| Technology | 20 | 199 | 0.0857 | 0.0068 | TRADE |

## 3. Headline by asset class

| segment | best_horizon_d | n_at_best | max_risk_adj | max_mean_ret | verdict |
|---|---|---|---|---|---|
| Commodity | 1 | 75 | -0.1614 | -0.0024 | DISABLE |
| Equity | 20 | 672 | 0.1662 | 0.0119 | TRADE |
| FixedIncome | 10 | 51 | 0.4706 | 0.0102 | TRADE |

## 4. Sector x Signal cross-tab (headline)

`mean_ret_{h}d` = mean directional underlying return at horizon h, signed so + = trade went the right way. A row with positive numbers across horizons is a sector that carries that signal type. A mostly-negative row exposes a tech-only artifact.

| sector | signal | n_signals | mean_ret_5d | n_5d | mean_ret_10d | n_10d | mean_ret_20d | n_20d |
|---|---|---|---|---|---|---|---|---|
| BroadMarket | BUY CALLS | 63 | 0.0089 | 63 | 0.0186 | 62 | 0.0236 | 55 |
| Commodity | BUY CALLS | 3 | -0.0145 | 3 | -0.0005 | 3 | 0.0968 | 3 |
| ConsumerStaples | BUY CALLS | 49 | 0.0022 | 49 | -0.0045 | 49 | 0.0117 | 49 |
| Energy | BUY CALLS | 27 | 0.0029 | 27 | 0.0150 | 27 | 0.0362 | 27 |
| Financials | BUY CALLS | 14 | 0.0083 | 14 | 0.0009 | 14 | 0.0269 | 14 |
| FixedIncome | BUY CALLS | 40 | 0.0049 | 40 | 0.0106 | 40 | 0.0173 | 40 |
| Healthcare | BUY CALLS | 6 | -0.0202 | 6 | -0.0147 | 6 | 0.1053 | 6 |
| SmallCapEquity | BUY CALLS | 38 | 0.0101 | 38 | 0.0162 | 38 | 0.0370 | 38 |
| Technology | BUY CALLS | 133 | 0.0063 | 131 | 0.0052 | 127 | 0.0071 | 116 |
| BroadMarket | BUY PUTS | 36 | 0.0044 | 36 | 0.0069 | 36 | 0.0002 | 36 |
| Commodity | BUY PUTS | 17 | -0.0215 | 17 | -0.0321 | 17 | -0.0485 | 17 |
| ConsumerStaples | BUY PUTS | 9 | -0.0336 | 9 | -0.0687 | 9 | -0.0820 | 9 |
| Energy | BUY PUTS | 1 | -0.0077 | 1 | -0.0292 | 1 | -0.1302 | 1 |
| Financials | BUY PUTS | 36 | -0.0124 | 36 | -0.0183 | 32 | -0.0193 | 31 |
| FixedIncome | BUY PUTS | 6 | -0.0034 | 6 | 0.0007 | 6 | -0.0279 | 6 |
| Healthcare | BUY PUTS | 63 | 0.0129 | 58 | 0.0329 | 56 | 0.0613 | 52 |
| SmallCapEquity | BUY PUTS | 35 | -0.0045 | 34 | -0.0081 | 34 | -0.0080 | 34 |
| Technology | BUY PUTS | 53 | -0.0109 | 48 | -0.0077 | 43 | -0.0100 | 42 |
| BroadMarket | SELL CALLS | 6 | -0.0223 | 6 | -0.0578 | 6 | -0.0953 | 6 |
| Commodity | SELL CALLS | 39 | -0.0074 | 39 | -0.0105 | 39 | -0.0174 | 39 |
| ConsumerStaples | SELL CALLS | 4 | 0.0652 | 4 | 0.0680 | 4 | 0.0478 | 4 |
| Energy | SELL CALLS | 6 | 0.0095 | 6 | 0.0264 | 6 | -0.0297 | 6 |
| Financials | SELL CALLS | 13 | -0.0201 | 13 | -0.0271 | 13 | -0.0718 | 13 |
| FixedIncome | SELL CALLS | 5 | 0.0061 | 5 | -0.0062 | 5 | -0.0007 | 5 |
| Healthcare | SELL CALLS | 12 | 0.0238 | 12 | 0.0470 | 12 | 0.0401 | 12 |
| SmallCapEquity | SELL CALLS | 1 | -0.0083 | 1 | 0.0164 | 1 | -0.0395 | 1 |
| Technology | SELL CALLS | 28 | -0.0399 | 28 | -0.0258 | 28 | 0.0062 | 28 |
| BroadMarket | SELL PUTS | 12 | -0.0062 | 12 | -0.0202 | 12 | -0.0402 | 12 |
| Commodity | SELL PUTS | 16 | 0.0135 | 16 | 0.0247 | 16 | 0.0226 | 16 |
| ConsumerStaples | SELL PUTS | 10 | 0.0123 | 10 | 0.0217 | 10 | 0.0510 | 10 |
| Financials | SELL PUTS | 20 | 0.0097 | 20 | 0.0020 | 20 | -0.0033 | 20 |
| Healthcare | SELL PUTS | 23 | -0.0026 | 23 | 0.0055 | 23 | 0.0061 | 23 |
| SmallCapEquity | SELL PUTS | 14 | 0.0225 | 14 | 0.0478 | 14 | 0.0630 | 14 |
| Technology | SELL PUTS | 13 | -0.0180 | 13 | 0.0222 | 13 | 0.0598 | 13 |

## 5. Per-sector decay curves

### BroadMarket  -> **TRADE**

Optimal horizon: **10d**  (risk_adj = +0.210, mean = +0.70%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  117 | +0.03% | +0.95% | +0.034 | +0.544 |
|  3d |  117 | +0.29% | +1.59% | +0.179 | +1.645 |
|  5d |  117 | +0.44% | +2.12% | +0.205 | +1.456 |
| 10d |  116 | +0.70% | +3.33% | +0.210 | +1.056 |
| 20d |  109 | +0.23% | +4.23% | +0.054 | +0.192 |

### Commodity  -> **DISABLE**

Optimal horizon: **1d**  (risk_adj = -0.161, mean = -0.24%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   75 | -0.24% | +1.46% | -0.161 | -2.562 |
|  3d |   75 | -0.38% | +2.18% | -0.175 | -1.601 |
|  5d |   75 | -0.64% | +2.57% | -0.249 | -1.770 |
| 10d |   75 | -0.75% | +3.32% | -0.226 | -1.135 |
| 20d |   75 | -1.14% | +5.73% | -0.198 | -0.704 |

### ConsumerStaples  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.114, mean = +0.74%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   72 | +0.01% | +1.65% | +0.008 | +0.129 |
|  3d |   72 | +0.14% | +2.75% | +0.052 | +0.480 |
|  5d |   72 | +0.26% | +3.88% | +0.067 | +0.477 |
| 10d |   72 | -0.48% | +5.26% | -0.092 | -0.462 |
| 20d |   72 | +0.74% | +6.50% | +0.114 | +0.406 |

### Energy  -> **TRADE**

Optimal horizon: **10d**  (risk_adj = +0.415, mean = +1.97%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   34 | -0.00% | +1.35% | -0.000 | -0.006 |
|  3d |   34 | +0.24% | +1.94% | +0.127 | +1.159 |
|  5d |   34 | +0.37% | +2.54% | +0.147 | +1.041 |
| 10d |   34 | +1.57% | +3.79% | +0.415 | +2.084 |
| 20d |   34 | +1.97% | +5.81% | +0.339 | +1.205 |

### Financials  -> **DISABLE**

Optimal horizon: **1d**  (risk_adj = -0.112, mean = -0.14%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   83 | -0.14% | +1.27% | -0.112 | -1.782 |
|  3d |   83 | -0.40% | +2.10% | -0.188 | -1.723 |
|  5d |   83 | -0.48% | +2.74% | -0.174 | -1.237 |
| 10d |   79 | -1.12% | +3.63% | -0.309 | -1.554 |
| 20d |   78 | -1.57% | +5.48% | -0.285 | -1.013 |

### FixedIncome  -> **TRADE**

Optimal horizon: **10d**  (risk_adj = +0.471, mean = +1.02%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   51 | +0.07% | +0.72% | +0.095 | +1.503 |
|  3d |   51 | +0.26% | +1.06% | +0.248 | +2.274 |
|  5d |   51 | +0.41% | +1.36% | +0.298 | +2.118 |
| 10d |   51 | +0.78% | +1.65% | +0.471 | +2.362 |
| 20d |   51 | +1.02% | +2.41% | +0.425 | +1.508 |

### Healthcare  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.493, mean = +4.78%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  103 | +0.10% | +2.93% | +0.032 | +0.512 |
|  3d |  101 | +0.33% | +5.34% | +0.062 | +0.566 |
|  5d |   99 | +0.86% | +6.75% | +0.127 | +0.904 |
| 10d |   97 | +2.52% | +8.63% | +0.292 | +1.465 |
| 20d |   93 | +4.78% | +9.69% | +0.493 | +1.750 |

### SmallCapEquity  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.389, mean = +2.27%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   87 | +0.25% | +1.58% | +0.156 | +2.479 |
|  3d |   87 | +0.48% | +1.97% | +0.241 | +2.213 |
|  5d |   87 | +0.62% | +2.38% | +0.261 | +1.854 |
| 10d |   87 | +1.18% | +3.38% | +0.348 | +1.746 |
| 20d |   87 | +2.27% | +5.83% | +0.389 | +1.380 |

### Technology  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.086, mean = +0.68%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  226 | -0.12% | +2.19% | -0.056 | -0.886 |
|  3d |  224 | -0.17% | +3.73% | -0.047 | -0.427 |
|  5d |  220 | -0.47% | +4.95% | -0.096 | -0.678 |
| 10d |  211 | -0.05% | +6.25% | -0.008 | -0.039 |
| 20d |  199 | +0.68% | +7.93% | +0.086 | +0.304 |

## 6. Notes

- Sample sizes per sector are smaller than the universe-wide decay table by ~10x.  Treat sector verdicts as directional, not definitive; the small-sample warning from `outputs/signal_decay_analysis.md` applies a fortiori per sector.
- The cross-tab uses underlying directional returns, not option P&L, so structure choices (60 DTE BUY PUTS, 0.25-delta short, etc.) don't confound the comparison across sectors.
- An honest read: if BUY PUTS shows positive mean_ret in Technology and ~zero everywhere else, that is the answer.  Do not paper over it by widening confidence intervals.

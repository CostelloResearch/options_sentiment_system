# Signal Decay -- Per-Sector Segmentation

_2026-04-25 universe rebuild: 10 tickers across 9 sectors and 3 asset classes._

**Critical test:** is the historical BUY CALLS / BUY PUTS / SELL PUTS edge documented on the 5-ticker tech-heavy universe consistent across sectors, or was it concentrated in tech?

## 1. Headline by signal (universe-wide)

| segment | best_horizon_d | n_at_best | max_risk_adj | max_mean_ret | verdict |
|---|---|---|---|---|---|
| BUY CALLS | 20 | 282 | 0.4586 | 0.0301 | TRADE |
| BUY PUTS | 10 | 150 | -0.0815 | -0.0023 | DISABLE |
| SELL CALLS | 10 | 27 | 0.1339 | 0.0083 | TRADE |
| SELL PUTS | 20 | 23 | 0.4263 | 0.0179 | TRADE |

## 2. Headline by sector

| segment | best_horizon_d | n_at_best | max_risk_adj | max_mean_ret | verdict |
|---|---|---|---|---|---|
| BroadMarket | 10 | 17 | 0.0739 | 0.0029 | TRADE |
| Commodity | 20 | 70 | 0.4719 | 0.0321 | TRADE |
| ConsumerStaples | 20 | 48 | 0.2803 | 0.0158 | TRADE |
| Energy | 20 | 77 | 0.6187 | 0.0309 | TRADE |
| Financials | 20 | 44 | 0.3706 | 0.0169 | TRADE |
| FixedIncome | 1 | 71 | -0.0549 | -0.0003 | DISABLE |
| Healthcare | 10 | 59 | 0.3851 | 0.0295 | TRADE |
| SmallCapEquity | 5 | 45 | -0.0644 | -0.0015 | DISABLE |
| Technology | 20 | 59 | 0.3830 | 0.0261 | TRADE |

## 3. Headline by asset class

| segment | best_horizon_d | n_at_best | max_risk_adj | max_mean_ret | verdict |
|---|---|---|---|---|---|
| Commodity | 20 | 70 | 0.4719 | 0.0321 | TRADE |
| Equity | 10 | 353 | 0.2065 | 0.0113 | TRADE |
| FixedIncome | 1 | 71 | -0.0549 | -0.0003 | DISABLE |

## 4. Sector x Signal cross-tab (headline)

`mean_ret_{h}d` = mean directional underlying return at horizon h, signed so + = trade went the right way. A row with positive numbers across horizons is a sector that carries that signal type. A mostly-negative row exposes a tech-only artifact.

| sector | signal | n_signals | mean_ret_5d | n_5d | mean_ret_10d | n_10d | mean_ret_20d | n_20d |
|---|---|---|---|---|---|---|---|---|
| BroadMarket | BUY CALLS | 7 | 0.0170 | 7 | 0.0359 | 6 | 0.0460 | 6 |
| Commodity | BUY CALLS | 31 | 0.0098 | 31 | 0.0269 | 31 | 0.0721 | 31 |
| ConsumerStaples | BUY CALLS | 44 | 0.0043 | 44 | 0.0081 | 44 | 0.0226 | 44 |
| Energy | BUY CALLS | 68 | 0.0132 | 68 | 0.0188 | 68 | 0.0376 | 68 |
| Financials | BUY CALLS | 45 | 0.0001 | 45 | 0.0014 | 44 | 0.0182 | 41 |
| FixedIncome | BUY CALLS | 10 | 0.0021 | 10 | 0.0025 | 10 | -0.0013 | 10 |
| Healthcare | BUY CALLS | 37 | 0.0073 | 36 | 0.0264 | 33 | -0.0080 | 27 |
| SmallCapEquity | BUY CALLS | 4 | 0.0200 | 4 | 0.0152 | 4 | 0.0211 | 4 |
| Technology | BUY CALLS | 57 | 0.0133 | 55 | 0.0254 | 52 | 0.0354 | 51 |
| BroadMarket | BUY PUTS | 11 | -0.0089 | 11 | -0.0146 | 9 | -0.0321 | 9 |
| Commodity | BUY PUTS | 8 | -0.0205 | 8 | -0.0274 | 8 | -0.0642 | 8 |
| ConsumerStaples | BUY PUTS | 4 | -0.0074 | 4 | -0.0077 | 4 | -0.0591 | 4 |
| Energy | BUY PUTS | 7 | -0.0049 | 7 | -0.0201 | 7 | -0.0323 | 7 |
| Financials | BUY PUTS | 2 | -0.0128 | 2 | 0.0171 | 2 | -0.0186 | 2 |
| FixedIncome | BUY PUTS | 59 | -0.0031 | 57 | -0.0032 | 57 | -0.0046 | 57 |
| Healthcare | BUY PUTS | 21 | 0.0127 | 21 | 0.0434 | 21 | 0.0267 | 21 |
| SmallCapEquity | BUY PUTS | 37 | -0.0038 | 37 | -0.0166 | 37 | -0.0455 | 37 |
| Technology | BUY PUTS | 5 | -0.0328 | 5 | -0.0249 | 5 | -0.0112 | 5 |
| BroadMarket | SELL CALLS | 1 | -0.0449 | 1 | -0.0319 | 1 | -0.0603 | 1 |
| Commodity | SELL CALLS | 15 | 0.0088 | 15 | 0.0211 | 15 | 0.0075 | 15 |
| FixedIncome | SELL CALLS | 2 | 0.0140 | 2 | 0.0131 | 2 | 0.0040 | 2 |
| Healthcare | SELL CALLS | 5 | -0.0173 | 5 | -0.0082 | 5 | -0.0437 | 5 |
| SmallCapEquity | SELL CALLS | 3 | 0.0088 | 3 | -0.0028 | 3 | -0.0138 | 3 |
| Technology | SELL CALLS | 1 | -0.0343 | 1 | -0.0376 | 1 | -0.0994 | 1 |
| BroadMarket | SELL PUTS | 1 | -0.0254 | 1 | -0.0025 | 1 | 0.0143 | 1 |
| Commodity | SELL PUTS | 16 | 0.0040 | 16 | 0.0180 | 16 | 0.0259 | 16 |
| Energy | SELL PUTS | 2 | -0.0400 | 2 | -0.0530 | 2 | 0.0237 | 2 |
| Financials | SELL PUTS | 1 | 0.0186 | 1 | 0.0202 | 1 | 0.0329 | 1 |
| SmallCapEquity | SELL PUTS | 1 | -0.0347 | 1 | -0.0197 | 1 | 0.0072 | 1 |
| Technology | SELL PUTS | 2 | -0.0190 | 2 | -0.0545 | 2 | -0.0525 | 2 |

## 5. Per-sector decay curves

### BroadMarket  -> **TRADE**

Optimal horizon: **10d**  (risk_adj = +0.074, mean = +0.29%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   20 | -0.02% | +0.97% | -0.016 | -0.257 |
|  3d |   20 | -0.45% | +1.70% | -0.267 | -2.448 |
|  5d |   20 | -0.24% | +2.47% | -0.099 | -0.703 |
| 10d |   17 | +0.29% | +3.92% | +0.074 | +0.371 |
| 20d |   17 | -0.35% | +5.39% | -0.065 | -0.229 |

### Commodity  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.472, mean = +3.21%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   70 | +0.08% | +1.32% | +0.064 | +1.018 |
|  3d |   70 | +0.26% | +2.31% | +0.111 | +1.016 |
|  5d |   70 | +0.48% | +3.19% | +0.150 | +1.064 |
| 10d |   70 | +1.74% | +4.70% | +0.370 | +1.855 |
| 20d |   70 | +3.21% | +6.81% | +0.472 | +1.675 |

### ConsumerStaples  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.280, mean = +1.58%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   48 | -0.12% | +1.28% | -0.092 | -1.466 |
|  3d |   48 | +0.14% | +2.11% | +0.066 | +0.605 |
|  5d |   48 | +0.33% | +2.94% | +0.113 | +0.802 |
| 10d |   48 | +0.68% | +4.76% | +0.143 | +0.720 |
| 20d |   48 | +1.58% | +5.65% | +0.280 | +0.995 |

### Energy  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.619, mean = +3.09%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   77 | +0.25% | +1.18% | +0.212 | +3.372 |
|  3d |   77 | +0.55% | +2.05% | +0.270 | +2.471 |
|  5d |   77 | +1.02% | +2.70% | +0.378 | +2.682 |
| 10d |   77 | +1.34% | +3.64% | +0.368 | +1.848 |
| 20d |   77 | +3.09% | +5.00% | +0.619 | +2.196 |

### Financials  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.371, mean = +1.69%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   48 | -0.04% | +1.21% | -0.031 | -0.485 |
|  3d |   48 | +0.24% | +1.90% | +0.124 | +1.135 |
|  5d |   48 | -0.00% | +2.50% | -0.001 | -0.005 |
| 10d |   47 | +0.25% | +3.38% | +0.073 | +0.368 |
| 20d |   44 | +1.69% | +4.56% | +0.371 | +1.316 |

### FixedIncome  -> **DISABLE**

Optimal horizon: **1d**  (risk_adj = -0.055, mean = -0.03%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   71 | -0.03% | +0.62% | -0.055 | -0.871 |
|  3d |   70 | -0.13% | +0.89% | -0.141 | -1.296 |
|  5d |   69 | -0.19% | +1.23% | -0.153 | -1.090 |
| 10d |   69 | -0.19% | +1.72% | -0.112 | -0.563 |
| 20d |   69 | -0.39% | +1.94% | -0.200 | -0.709 |

### Healthcare  -> **TRADE**

Optimal horizon: **10d**  (risk_adj = +0.385, mean = +2.95%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   63 | -0.18% | +3.40% | -0.053 | -0.835 |
|  3d |   63 | +0.42% | +4.72% | +0.089 | +0.820 |
|  5d |   62 | +0.71% | +5.14% | +0.138 | +0.982 |
| 10d |   59 | +2.95% | +7.67% | +0.385 | +1.933 |
| 20d |   53 | +0.24% | +11.79% | +0.021 | +0.073 |

### SmallCapEquity  -> **DISABLE**

Optimal horizon: **5d**  (risk_adj = -0.064, mean = -0.15%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   45 | -0.18% | +1.54% | -0.115 | -1.826 |
|  3d |   45 | -0.36% | +2.03% | -0.178 | -1.633 |
|  5d |   45 | -0.15% | +2.40% | -0.064 | -0.457 |
| 10d |   45 | -1.29% | +3.70% | -0.350 | -1.755 |
| 20d |   45 | -3.63% | +5.60% | -0.649 | -2.304 |

### Technology  -> **TRADE**

Optimal horizon: **20d**  (risk_adj = +0.383, mean = +2.61%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   65 | +0.08% | +1.88% | +0.042 | +0.671 |
|  3d |   64 | +0.10% | +3.39% | +0.029 | +0.269 |
|  5d |   63 | +0.78% | +4.41% | +0.178 | +1.261 |
| 10d |   60 | +1.75% | +5.57% | +0.314 | +1.575 |
| 20d |   59 | +2.61% | +6.83% | +0.383 | +1.359 |

## 6. Notes

- Sample sizes per sector are smaller than the universe-wide decay table by ~10x.  Treat sector verdicts as directional, not definitive; the small-sample warning from `outputs/signal_decay_analysis.md` applies a fortiori per sector.
- The cross-tab uses underlying directional returns, not option P&L, so structure choices (60 DTE BUY PUTS, 0.25-delta short, etc.) don't confound the comparison across sectors.
- An honest read: if BUY PUTS shows positive mean_ret in Technology and ~zero everywhere else, that is the answer.  Do not paper over it by widening confidence intervals.

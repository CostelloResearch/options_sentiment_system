# Signal Decay Analysis

- Horizons tested: 1d, 3d, 5d, 10d, 20d
- Total trades in corpus: **562**
- Edge threshold: risk-adjusted return >= 0.05 AND mean > 0 at some horizon

## Signals flagged for DISABLE

- **signal=SELL CALLS** -- no horizon produced mean > 0 (best risk_adj = -0.071, best mean = -0.18%)
- **confidence=Q1 (lowest)** -- no horizon produced mean > 0 (best risk_adj = -0.063, best mean = -0.14%)

## Decay by signal type

### BUY CALLS  -> **TRADE**
Optimal horizon: **20d**  (risk_adj = +0.240, mean = +1.33%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  249 | +0.09% | +1.45% | +0.062 | +0.990 |
|  3d |  249 | +0.33% | +2.58% | +0.129 | +1.182 |
|  5d |  248 | +0.71% | +3.34% | +0.214 | +1.521 |
| 10d |  243 | +0.91% | +4.55% | +0.201 | +1.007 |
| 20d |  226 | +1.33% | +5.56% | +0.240 | +0.850 |

### BUY PUTS  -> **TRADE**
Optimal horizon: **20d**  (risk_adj = +0.218, mean = +1.44%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  167 | -0.04% | +1.52% | -0.024 | -0.383 |
|  3d |  165 | -0.13% | +2.79% | -0.047 | -0.434 |
|  5d |  163 | +0.04% | +3.49% | +0.011 | +0.080 |
| 10d |  158 | +0.68% | +4.40% | +0.155 | +0.778 |
| 20d |  156 | +1.44% | +6.62% | +0.218 | +0.772 |

### SELL CALLS  -> **DISABLE**
Optimal horizon: **1d**  (risk_adj = -0.071, mean = -0.18%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   61 | -0.18% | +2.50% | -0.071 | -1.133 |
|  3d |   61 | -1.26% | +3.81% | -0.332 | -3.044 |
|  5d |   61 | -2.22% | +4.97% | -0.446 | -3.169 |
| 10d |   61 | -3.59% | +7.50% | -0.479 | -2.403 |
| 20d |   61 | -4.19% | +11.71% | -0.358 | -1.269 |

### SELL PUTS  -> **TRADE**
Optimal horizon: **20d**  (risk_adj = +0.130, mean = +0.86%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |   84 | -0.17% | +2.20% | -0.076 | -1.210 |
|  3d |   84 | -0.12% | +3.48% | -0.035 | -0.320 |
|  5d |   84 | -0.12% | +4.38% | -0.026 | -0.188 |
| 10d |   84 | +0.64% | +4.99% | +0.129 | +0.645 |
| 20d |   84 | +0.86% | +6.61% | +0.130 | +0.461 |

## Decay by confidence quintile

### Q1 (lowest)  -> **DISABLE**
Optimal horizon: **1d**  (risk_adj = -0.063, mean = -0.14%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  113 | -0.14% | +2.23% | -0.063 | -1.005 |
|  3d |  113 | -0.64% | +3.66% | -0.174 | -1.599 |
|  5d |  113 | -1.04% | +4.95% | -0.210 | -1.489 |
| 10d |  113 | -1.41% | +6.60% | -0.213 | -1.071 |
| 20d |  113 | -1.05% | +9.40% | -0.112 | -0.397 |

### Q2  -> **TRADE**
Optimal horizon: **20d**  (risk_adj = +0.149, mean = +1.15%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  111 | -0.06% | +1.94% | -0.029 | -0.463 |
|  3d |  109 | -0.10% | +3.02% | -0.032 | -0.289 |
|  5d |  107 | -0.01% | +3.60% | -0.004 | -0.025 |
| 10d |  102 | +0.18% | +5.70% | +0.031 | +0.155 |
| 20d |   94 | +1.15% | +7.73% | +0.149 | +0.528 |

### Q3  -> **TRADE**
Optimal horizon: **10d**  (risk_adj = +0.147, mean = +0.88%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  112 | +0.03% | +1.48% | +0.023 | +0.361 |
|  3d |  112 | +0.15% | +3.02% | +0.051 | +0.466 |
|  5d |  111 | +0.19% | +4.09% | +0.045 | +0.322 |
| 10d |  109 | +0.79% | +5.36% | +0.147 | +0.738 |
| 20d |   99 | +0.88% | +7.00% | +0.126 | +0.446 |

### Q4  -> **TRADE**
Optimal horizon: **10d**  (risk_adj = +0.328, mean = +1.50%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  112 | +0.14% | +1.66% | +0.083 | +1.310 |
|  3d |  112 | +0.42% | +2.82% | +0.150 | +1.375 |
|  5d |  112 | +0.86% | +3.31% | +0.259 | +1.836 |
| 10d |  109 | +1.22% | +3.73% | +0.328 | +1.645 |
| 20d |  108 | +1.50% | +5.57% | +0.269 | +0.956 |

### Q5 (highest)  -> **TRADE**
Optimal horizon: **10d**  (risk_adj = +0.224, mean = +0.92%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  113 | -0.05% | +1.20% | -0.040 | -0.627 |
|  3d |  113 | -0.07% | +2.06% | -0.037 | -0.335 |
|  5d |  113 | +0.36% | +2.70% | +0.134 | +0.951 |
| 10d |  113 | +0.77% | +3.41% | +0.224 | +1.125 |
| 20d |  113 | +0.92% | +5.36% | +0.172 | +0.610 |

## Decay by sentiment source

### synthetic_news  -> **TRADE**
Optimal horizon: **20d**  (risk_adj = +0.090, mean = +0.65%)

| horizon | n | mean ret | std | risk-adj | annualised |
|--------:|--:|---------:|----:|---------:|-----------:|
|  1d |  561 | -0.01% | +1.74% | -0.009 | -0.138 |
|  3d |  559 | -0.05% | +2.97% | -0.016 | -0.146 |
|  5d |  556 | +0.07% | +3.85% | +0.018 | +0.129 |
| 10d |  546 | +0.30% | +5.16% | +0.058 | +0.293 |
| 20d |  527 | +0.65% | +7.20% | +0.090 | +0.321 |

## Notes on interpretation

- `mean ret` is the average **directional** underlying return (positive = trade went the right way regardless of bull/bear).
- `risk-adj` = mean / std per trade.  Multiply by sqrt(252/horizon) for an annualised Sharpe-like number.
- Small-sample warning: segments with n < 30 have risk_adj errors comparable to the point estimate itself; treat as directional at best.
- Disablement rule is intentionally lenient (0.05 risk-adj floor) to avoid killing a signal on a 50-trade sample -- real go/no-go should use out-of-sample data.

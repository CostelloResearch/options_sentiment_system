# Universe Correlation Matrix

_Snapshot for 10 tickers: AAPL, NVDA, JPM, XOM, UNH, WMT, IWM, GLD, TLT, SPY._

_Threshold for flagging: |corr| > 0.70._

## 1. Effective number of independent bets

Eigenvalue-entropy diversification metric. `N_eff = exp(-sum(p_i log p_i))` where `p_i = lambda_i / sum(lambda)`. Perfectly uncorrelated -> `N_eff = N`; perfectly correlated -> `N_eff = 1`.

| window | n_tickers | n_eff | ratio |
|---|---|---|---|
| 60d | 10 | 6.6660 | 0.6670 |
| 252d | 10 | 7.7300 | 0.7730 |

## 2. 60-day correlation matrix

| ticker | AAPL | NVDA | JPM | XOM | UNH | WMT | IWM | GLD | TLT | SPY |
|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | 1.0000 | 0.3400 | 0.4200 | -0.1850 | -0.2240 | 0.0690 | 0.5020 | 0.0300 | -0.0520 | 0.5670 |
| NVDA | 0.3400 | 1.0000 | 0.3300 | -0.2230 | 0.1900 | -0.0430 | 0.6550 | 0.3050 | 0.0920 | 0.7430 |
| JPM | 0.4200 | 0.3300 | 1.0000 | -0.1460 | 0.2280 | 0.0580 | 0.6790 | 0.1440 | 0.0390 | 0.6130 |
| XOM | -0.1850 | -0.2230 | -0.1460 | 1.0000 | -0.0690 | -0.0370 | -0.2660 | 0.1290 | -0.2790 | -0.3610 |
| UNH | -0.2240 | 0.1900 | 0.2280 | -0.0690 | 1.0000 | -0.0110 | 0.3230 | 0.2210 | 0.0790 | 0.3290 |
| WMT | 0.0690 | -0.0430 | 0.0580 | -0.0370 | -0.0110 | 1.0000 | 0.1650 | 0.0680 | 0.1930 | 0.1120 |
| IWM | 0.5020 | 0.6550 | 0.6790 | -0.2660 | 0.3230 | 0.1650 | 1.0000 | 0.3840 | 0.2370 | 0.8970 |
| GLD | 0.0300 | 0.3050 | 0.1440 | 0.1290 | 0.2210 | 0.0680 | 0.3840 | 1.0000 | 0.1170 | 0.3200 |
| TLT | -0.0520 | 0.0920 | 0.0390 | -0.2790 | 0.0790 | 0.1930 | 0.2370 | 0.1170 | 1.0000 | 0.2160 |
| SPY | 0.5670 | 0.7430 | 0.6130 | -0.3610 | 0.3290 | 0.1120 | 0.8970 | 0.3200 | 0.2160 | 1.0000 |

### Flagged pairs (|corr| > 0.70, 60d)

| ticker_a | ticker_b | corr | abs_corr |
|---|---|---|---|
| IWM | SPY | 0.8972 | 0.8972 |
| NVDA | SPY | 0.7433 | 0.7433 |

_Discuss before proceeding -- correlated pairs give double exposure to the same risk factor._

## 3. 252-day correlation matrix (robustness)

| ticker | AAPL | NVDA | JPM | XOM | UNH | WMT | IWM | GLD | TLT | SPY |
|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | 1.0000 | 0.2720 | 0.2780 | -0.0110 | -0.0520 | 0.0660 | 0.3950 | -0.0500 | 0.0070 | 0.5410 |
| NVDA | 0.2720 | 1.0000 | 0.3140 | -0.1010 | -0.0620 | -0.1590 | 0.4220 | 0.0440 | -0.0360 | 0.6690 |
| JPM | 0.2780 | 0.3140 | 1.0000 | -0.0070 | 0.1030 | 0.0290 | 0.5700 | 0.0460 | -0.0410 | 0.5960 |
| XOM | -0.0110 | -0.1010 | -0.0070 | 1.0000 | -0.0290 | -0.0660 | 0.0250 | 0.0650 | -0.1400 | -0.0750 |
| UNH | -0.0520 | -0.0620 | 0.1030 | -0.0290 | 1.0000 | 0.0560 | 0.2000 | 0.0370 | 0.0300 | 0.1430 |
| WMT | 0.0660 | -0.1590 | 0.0290 | -0.0660 | 0.0560 | 1.0000 | 0.0660 | 0.0280 | 0.0860 | 0.0570 |
| IWM | 0.3950 | 0.4220 | 0.5700 | 0.0250 | 0.2000 | 0.0660 | 1.0000 | 0.1520 | 0.1190 | 0.8350 |
| GLD | -0.0500 | 0.0440 | 0.0460 | 0.0650 | 0.0370 | 0.0280 | 0.1520 | 1.0000 | 0.0800 | 0.0840 |
| TLT | 0.0070 | -0.0360 | -0.0410 | -0.1400 | 0.0300 | 0.0860 | 0.1190 | 0.0800 | 1.0000 | 0.1140 |
| SPY | 0.5410 | 0.6690 | 0.5960 | -0.0750 | 0.1430 | 0.0570 | 0.8350 | 0.0840 | 0.1140 | 1.0000 |

### Flagged pairs (|corr| > 0.70, 252d)

| ticker_a | ticker_b | corr | abs_corr |
|---|---|---|---|
| IWM | SPY | 0.8347 | 0.8347 |

## 4. Notes

- 60-day windows have high standard error on correlation estimates: rule of thumb `SE(rho) ~= (1 - rho^2) / sqrt(n - 1)`, so a 0.5 correlation on 60 obs has SE ~= 0.10. The 252-day panel above is the more reliable read.
- Pairs flagged at the 0.70 cutoff are candidates to drop or replace; pairs in 0.5--0.7 are 'noted but tolerable' for this universe.
- For the 2026-04-25 rebuild we expect AAPL/SPY, NVDA/SPY, and IWM/SPY to land in the 0.5--0.8 range (broad-market beta), and TLT/GLD to be near zero or slightly negative against the equity cluster.

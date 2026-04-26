# R3 Production Baseline

_Post-adoption confirmation: the QUINTILE sizing regime selected in `outputs/regime_comparison.md` is now the production default in `position_sizer.py` (`USE_STRATEGY_BUCKETS = False`).  This document locks in the numbers produced by the productionised code so any future drift is detectable._

## 1. Production configuration

- `USE_STRATEGY_BUCKETS` = `False`
- `QUINTILE_FRAC` = `{'Q1': 0.001, 'Q2': 0.002, 'Q3': 0.003, 'Q4': 0.005, 'Q5': 0.008}`
- Global cap: `MAX_PORTFOLIO_RISK` = 6.0%
- Per-trade cap: `MAX_RISK_PER_TRADE` = 2.0%
- Quintile edges (from flat corpus): `[0.544, 0.5618, 0.5779, 0.602]`
- Paper-account notional (Kelly path): $100,000

## 2. Headline metrics

| regime | n_signals | n_trades | total_pnl | sharpe | max_dd | profit_factor | win_rate |
|---|---|---|---|---|---|---|---|
| flat (baseline) | 851 | 613 | 17913.1200 | 0.4200 | -21692.1800 | 1.2321 | 0.3619 |
| R3 production (quintile, no buckets) | 851 | 357 | 6775.1400 | 0.4103 | -6243.9900 | 1.2675 | 0.2186 |

## 3. BUY PUTS cap utilization + block rate

_Under R3 the `cap` is the global 6% portfolio cap (no per-strategy buckets)._

| metric | value |
|---|---|
| n_evaluations | 0 |

## 4. Confidence quintile P&L

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 65 | 0.5283 | 0.3846 | -19.2800 | -1253.2700 |
| Q2 | 75 | 0.5536 | 0.5467 | 11.0400 | 828.0500 |
| Q3 | 62 | 0.5702 | 0.4839 | -5.6600 | -351.0900 |
| Q4 | 77 | 0.5893 | 0.5974 | 26.5800 | 2046.8900 |
| Q5 | 78 | 0.6202 | 0.5641 | 70.5700 | 5504.5600 |

## 5. Trade counts per strategy

| signal | flat | R3 |
|---|---|---|
| BUY CALLS | 357 | 357 |
| BUY PUTS | 256 | 0 |

## 6. Drift check vs regime_comparison study

| metric | production | study | drift |
|---|---|---|---|
| total_pnl | 6775.1400 | 6775.0000 | 0.1400 |
| sharpe | 0.4103 | 0.4100 | 0.0003 |
| n_trades | 357.0000 | 357.0000 | 0.0000 |

**Verdict:** `MATCH`

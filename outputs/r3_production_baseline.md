# R3 Production Baseline

_Post-adoption confirmation: the QUINTILE sizing regime selected in `outputs/regime_comparison.md` is now the production default in `position_sizer.py` (`USE_STRATEGY_BUCKETS = False`).  This document locks in the numbers produced by the productionised code so any future drift is detectable._

## 1. Production configuration

- `USE_STRATEGY_BUCKETS` = `False`
- `QUINTILE_FRAC` = `{'Q1': 0.001, 'Q2': 0.002, 'Q3': 0.003, 'Q4': 0.005, 'Q5': 0.008}`
- Global cap: `MAX_PORTFOLIO_RISK` = 6.0%
- Per-trade cap: `MAX_RISK_PER_TRADE` = 2.0%
- Quintile edges (from flat corpus): `[0.515, 0.5479, 0.5671, 0.5903]`
- Paper-account notional (Kelly path): $100,000

## 2. Headline metrics

| regime | n_signals | n_trades | total_pnl | sharpe | max_dd | profit_factor | win_rate |
|---|---|---|---|---|---|---|---|
| flat (baseline) | 283 | 190 | -16918.4300 | -1.6951 | -17503.6400 | 0.4083 | 0.2968 |
| R3 production (quintile, no buckets) | 872 | 360 | 5836.1300 | 0.4973 | -6567.8800 | 1.3113 | 0.2248 |

## 3. BUY PUTS cap utilization + block rate

_Under R3 the `cap` is the global 6% portfolio cap (no per-strategy buckets)._

| metric | value |
|---|---|
| n_evaluations | 0 |

## 4. Confidence quintile P&L

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 313 | 0.2837 | 0.5623 | 22.2300 | 6956.8000 |
| Q2 | 23 | 0.5292 | 0.5652 | 0.7400 | 16.9700 |
| Q3 | 7 | 0.5616 | 0.7143 | 98.5100 | 689.6000 |
| Q4 | 5 | 0.5763 | 0.2000 | -90.9600 | -454.8100 |
| Q5 | 12 | 0.6820 | 0.0833 | -114.3700 | -1372.4300 |

## 5. Trade counts per strategy

| signal | flat | R3 |
|---|---|---|
| BUY CALLS | 119 | 360 |
| BUY PUTS | 71 | 0 |

## 6. Drift check vs regime_comparison study

| metric | production | study | drift |
|---|---|---|---|
| total_pnl | 5836.1300 | 6775.0000 | -938.8700 |
| sharpe | 0.4973 | 0.4100 | 0.0873 |
| n_trades | 360.0000 | 357.0000 | 3.0000 |

**Verdict:** `DRIFT`

If verdict is DRIFT, investigate what changed in `position_sizer.size_trade`, `backtest/engine.py`, or the logistic confidence model.  The R3 study numbers are pinned in this script (R3_STUDY_TOTAL_PNL / R3_STUDY_SHARPE / R3_STUDY_N_TRADES) so any legitimate change in production should update those constants alongside.

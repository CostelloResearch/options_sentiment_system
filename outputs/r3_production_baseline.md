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
| R3 production (quintile, no buckets) | 872 | 360 | 5836.1300 | 0.4973 | -6567.8800 | 1.3113 | 0.2248 |

## 3. BUY PUTS cap utilization + block rate

_Under R3 the `cap` is the global 6% portfolio cap (no per-strategy buckets)._

| metric | value |
|---|---|
| n_evaluations | 0 |

## 4. Confidence quintile P&L

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 333 | 0.2983 | 0.5616 | 20.6500 | 6875.5000 |
| Q2 | 6 | 0.5507 | 0.6667 | 85.3100 | 511.8800 |
| Q3 | 7 | 0.5675 | 0.4286 | -23.2800 | -162.9400 |
| Q4 | 3 | 0.5893 | 0.6667 | 9.2000 | 27.6000 |
| Q5 | 11 | 0.6896 | 0.0000 | -128.7200 | -1415.9100 |

## 5. Trade counts per strategy

| signal | flat | R3 |
|---|---|---|
| BUY CALLS | 357 | 360 |
| BUY PUTS | 256 | 0 |

## 6. Drift check vs regime_comparison study

| metric | production | study | drift |
|---|---|---|---|
| total_pnl | 5836.1300 | 6775.0000 | -938.8700 |
| sharpe | 0.4973 | 0.4100 | 0.0873 |
| n_trades | 360.0000 | 357.0000 | 3.0000 |

**Verdict:** `DRIFT`

If verdict is DRIFT, investigate what changed in `position_sizer.size_trade`, `backtest/engine.py`, or the logistic confidence model.  The R3 study numbers are pinned in this script (R3_STUDY_TOTAL_PNL / R3_STUDY_SHARPE / R3_STUDY_N_TRADES) so any legitimate change in production should update those constants alongside.

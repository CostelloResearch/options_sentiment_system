# R3 Production Baseline

_Post-adoption confirmation: the QUINTILE sizing regime selected in `outputs/regime_comparison.md` is now the production default in `position_sizer.py` (`USE_STRATEGY_BUCKETS = False`).  This document locks in the numbers produced by the productionised code so any future drift is detectable._

## 1. Production configuration

- `USE_STRATEGY_BUCKETS` = `False`
- `QUINTILE_FRAC` = `{'Q1': 0.001, 'Q2': 0.002, 'Q3': 0.003, 'Q4': 0.005, 'Q5': 0.008}`
- Global cap: `MAX_PORTFOLIO_RISK` = 6.0%
- Per-trade cap: `MAX_RISK_PER_TRADE` = 2.0%
- Quintile edges (from flat corpus): `[0.1814, 0.2959, 0.3915, 0.4948]`
- Paper-account notional (Kelly path): $100,000

## 2. Headline metrics

| regime | n_signals | n_trades | total_pnl | sharpe | max_dd | profit_factor | win_rate |
|---|---|---|---|---|---|---|---|
| flat (baseline) | 507 | 452 | -19743.5100 | -0.9201 | -28819.7600 | 0.6484 | 0.4063 |
| R3 production (quintile, no buckets) | 507 | 298 | 10216.5700 | 1.2812 | -1396.0400 | 1.7807 | 0.3314 |

## 3. BUY PUTS cap utilization + block rate

_Under R3 the `cap` is the global 6% portfolio cap (no per-strategy buckets)._

| metric | value |
|---|---|
| n_evaluations | 0 |

## 4. Confidence quintile P&L

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 49 | 0.1250 | 0.5714 | 27.9500 | 1369.5400 |
| Q2 | 63 | 0.2425 | 0.6190 | 44.9500 | 2831.7600 |
| Q3 | 61 | 0.3455 | 0.6066 | 52.5200 | 3204.0100 |
| Q4 | 58 | 0.4345 | 0.4655 | 16.8200 | 975.8500 |
| Q5 | 67 | 0.5701 | 0.5522 | 27.3900 | 1835.4100 |

## 5. Trade counts per strategy

| signal | flat | R3 |
|---|---|---|
| BUY CALLS | 298 | 298 |
| BUY PUTS | 154 | 0 |

## 6. Drift check vs regime_comparison study

| metric | production | study | drift |
|---|---|---|---|
| total_pnl | 10216.5700 | 6775.0000 | 3441.5700 |
| sharpe | 1.2812 | 0.4100 | 0.8712 |
| n_trades | 298.0000 | 357.0000 | -59.0000 |

**Verdict:** `DRIFT`

If verdict is DRIFT, investigate what changed in `position_sizer.size_trade`, `backtest/engine.py`, or the logistic confidence model.  The R3 study numbers are pinned in this script (R3_STUDY_TOTAL_PNL / R3_STUDY_SHARPE / R3_STUDY_N_TRADES) so any legitimate change in production should update those constants alongside.

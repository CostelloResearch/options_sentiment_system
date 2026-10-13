# R3 Production Baseline

_Post-adoption confirmation: the QUINTILE sizing regime selected in `outputs/regime_comparison.md` is now the production default in `position_sizer.py` (`USE_STRATEGY_BUCKETS = False`).  This document locks in the numbers produced by the productionised code so any future drift is detectable._

## 1. Production configuration

- `USE_STRATEGY_BUCKETS` = `False`
- `QUINTILE_FRAC` = `{'Q1': 0.001, 'Q2': 0.002, 'Q3': 0.003, 'Q4': 0.005, 'Q5': 0.008}`
- Global cap: `MAX_PORTFOLIO_RISK` = 6.0%
- Per-trade cap: `MAX_RISK_PER_TRADE` = 2.0%
- Quintile edges (from flat corpus): `[0.1807, 0.2946, 0.3905, 0.4877]`
- Paper-account notional (Kelly path): $100,000

## 2. Headline metrics

| regime | n_signals | n_trades | total_pnl | sharpe | max_dd | profit_factor | win_rate |
|---|---|---|---|---|---|---|---|
| flat (baseline) | 507 | 449 | -18983.3000 | -0.8989 | -27048.1800 | 0.6571 | 0.4320 |
| R3 production (quintile, no buckets) | 507 | 314 | 13906.1300 | 0.9084 | -5175.8400 | 1.6878 | 0.3590 |

## 3. BUY PUTS cap utilization + block rate

_Under R3 the `cap` is the global 6% portfolio cap (no per-strategy buckets)._

| metric | value |
|---|---|
| cap_$ | 6000.0000 |
| n_evaluations | 21.0000 |
| mean_utilization | 0.5603 |
| peak_utilization | 1.0037 |
| n_blocked | 1.0000 |
| pct_blocked | 0.0476 |

## 4. Confidence quintile P&L

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 51 | 0.1203 | 0.6078 | 33.5700 | 1712.2400 |
| Q2 | 68 | 0.2417 | 0.6029 | 89.6000 | 6092.7900 |
| Q3 | 67 | 0.3461 | 0.5970 | 40.0100 | 2680.9000 |
| Q4 | 61 | 0.4343 | 0.4918 | 3.0100 | 183.9100 |
| Q5 | 67 | 0.5680 | 0.5970 | 48.3000 | 3236.2900 |

## 5. Trade counts per strategy

| signal | flat | R3 |
|---|---|---|
| BUY CALLS | 295 | 294 |
| BUY PUTS | 154 | 20 |

## 6. Drift check vs regime_comparison study

| metric | production | study | drift |
|---|---|---|---|
| total_pnl | 13906.1300 | 6775.0000 | 7131.1300 |
| sharpe | 0.9084 | 0.4100 | 0.4984 |
| n_trades | 314.0000 | 357.0000 | -43.0000 |

**Verdict:** `DRIFT`

If verdict is DRIFT, investigate what changed in `position_sizer.size_trade`, `backtest/engine.py`, or the logistic confidence model.  The R3 study numbers are pinned in this script (R3_STUDY_TOTAL_PNL / R3_STUDY_SHARPE / R3_STUDY_N_TRADES) so any legitimate change in production should update those constants alongside.

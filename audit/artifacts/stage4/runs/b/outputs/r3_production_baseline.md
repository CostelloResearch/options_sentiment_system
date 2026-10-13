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
| R3 production (quintile, no buckets) | 507 | 315 | 13183.9100 | 0.8585 | -5362.4600 | 1.6543 | 0.3511 |

## 3. BUY PUTS cap utilization + block rate

_Under R3 the `cap` is the global 6% portfolio cap (no per-strategy buckets)._

| metric | value |
|---|---|
| cap_$ | 6000.0000 |
| n_evaluations | 21.0000 |
| mean_utilization | 0.5385 |
| peak_utilization | 1.1240 |
| n_blocked | 2.0000 |
| pct_blocked | 0.0952 |

## 4. Confidence quintile P&L

| quintile | n | mean_conf | win_rate | avg_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 52 | 0.1227 | 0.5769 | 35.2900 | 1835.1000 |
| Q2 | 66 | 0.2421 | 0.6364 | 91.1800 | 6018.0100 |
| Q3 | 69 | 0.3460 | 0.5797 | 26.0900 | 1800.5000 |
| Q4 | 58 | 0.4352 | 0.4655 | 11.4200 | 662.4300 |
| Q5 | 70 | 0.5692 | 0.5571 | 40.9700 | 2867.8700 |

## 5. Trade counts per strategy

| signal | flat | R3 |
|---|---|---|
| BUY CALLS | 298 | 296 |
| BUY PUTS | 154 | 19 |

## 6. Drift check vs regime_comparison study

| metric | production | study | drift |
|---|---|---|---|
| total_pnl | 13183.9100 | 6775.0000 | 6408.9100 |
| sharpe | 0.8585 | 0.4100 | 0.4485 |
| n_trades | 315.0000 | 357.0000 | -42.0000 |

**Verdict:** `DRIFT`

If verdict is DRIFT, investigate what changed in `position_sizer.size_trade`, `backtest/engine.py`, or the logistic confidence model.  The R3 study numbers are pinned in this script (R3_STUDY_TOTAL_PNL / R3_STUDY_SHARPE / R3_STUDY_N_TRADES) so any legitimate change in production should update those constants alongside.

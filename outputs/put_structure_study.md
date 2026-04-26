# BUY PUTS Structure Study

_Premise: the decay analysis found BUY PUTS has underlying edge (+1.44% at 20d) but the default 35-DTE / 0.30delta bear-put spread loses money on execution.  This study compares alternative structures on the SAME set of BUY PUTS signal dates from the flat backtest._

## Results

| variant | label | n_accepted | n_rejected | total_pnl | avg_pnl | win_rate | mean_ret_pct | sharpe | max_dd |
|---|---|---|---|---|---|---|---|---|---|
| A | 20 DTE spread, short 0.35delta | 168 | 0 | -3910.6900 | -23.2800 | 0.3750 | -6.1200 | -1.5984 | -4450.7600 |
| B | 60 DTE spread, short 0.25delta | 168 | 0 | 32456.8400 | 193.2000 | 0.5952 | 15.4900 | 1.9759 | -13992.4700 |
| C | 45 DTE spread, $10 width | 168 | 0 | 4073.3000 | 24.2500 | 0.5417 | 4.4800 | 0.6741 | -7717.7200 |
| D | 45 DTE single long put 0.50delta | 168 | 0 | -56357.8300 | -335.4600 | 0.5060 | -26.6800 | -2.1983 | -69361.1200 |
| Baseline | Current (35 DTE, short 0.30delta) | 168 | 0 | 8395.9100 | 49.9800 | 0.5179 | 4.1200 | 0.8946 | -9017.6100 |

## Recommendation

**Variant B** -- _60 DTE spread, short 0.25delta_ -- delivered the highest total P&L (+32456.84) with Sharpe +1.9759.

Comparison to Baseline (35 DTE / 0.30delta short):
  - Baseline total_pnl = +8395.91, win_rate = 0.5179
  - Winner   total_pnl = +32456.84, win_rate = 0.5952

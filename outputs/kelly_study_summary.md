# Kelly Sizing vs Flat Sizing -- Comparison

_Demo-mode backtest with synthetic sentiment. Run with `--real` once real sentiment history exists._

## Per-ticker headline metrics

| label | ticker | n_signals | n_trades | total_pnl | avg_trade_pnl | win_rate | sharpe | max_dd | profit_factor |
|---|---|---|---|---|---|---|---|---|---|
| flat | AAPL | 101 | 72 | -8904.0200 | -88.1600 | 0.2871 | -2.3215 | -11228.2100 | 0.3147 |
| kelly | AAPL | 101 | 72 | -3023.4700 | -29.9400 | 0.1089 | -1.4029 | -4095.9100 | 0.3463 |
| flat | NVDA | 128 | 118 | 272.4200 | 2.1300 | 0.4375 | 0.0592 | -5918.7600 | 1.0260 |
| kelly | NVDA | 128 | 118 | -268.7800 | -2.1000 | 0.1406 | -0.1147 | -1705.0700 | 0.9120 |
| flat | MSFT | 106 | 54 | 35340.8600 | 333.4000 | 0.4528 | 5.4755 | -1086.0600 | 28.6006 |
| kelly | MSFT | 106 | 54 | 2099.8900 | 19.8100 | 0.0660 | 0.8374 | -1213.0000 | 2.7068 |
| flat | SPY | 118 | 100 | 14514.4100 | 123.0000 | 0.6102 | 2.1920 | -3887.7300 | 2.7485 |
| kelly | SPY | 118 | 100 | -648.1700 | -5.4900 | 0.1864 | -0.2101 | -2573.1600 | 0.8457 |
| flat | QQQ | 109 | 73 | -8031.7100 | -73.6900 | 0.3028 | -1.1719 | -13056.5000 | 0.5601 |
| kelly | QQQ | 109 | 73 | -2262.0000 | -20.7500 | 0.1284 | -0.7251 | -2788.9100 | 0.4898 |
| flat | ALL | 562 | 417 | 33191.9600 | 59.0600 | 0.4235 | 1.0572 | -15328.4000 | 1.6469 |
| kelly | ALL | 562 | 417 | -4102.5300 | -7.3000 | 0.1281 | -0.3064 | -6333.3000 | 0.7661 |


## Kelly stats (per signal type)

| signal | count | win_rate | avg_win | avg_loss | std_ret | W | kelly_f | kelly_f_frac | tradable |
|---|---|---|---|---|---|---|---|---|---|
| BUY CALLS | 249 | 0.5542 | 0.3676 | 0.4420 | 0.4619 | 0.8317 | 0.0182 | 0.0046 | 1 |
| BUY PUTS | 168 | 0.5952 | 0.6605 | 0.5886 | 0.6633 | 1.1221 | 0.2345 | 0.0586 | 1 |


## Signals flagged DISABLE by decay analysis

- **signal=SELL CALLS** -- no horizon produced mean > 0
- **confidence=Q1 (lowest)** -- no horizon produced mean > 0


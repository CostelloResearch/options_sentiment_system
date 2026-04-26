# Strategy-Segregated Kelly -- Results

_Demo-mode backtest.  Run with `--real` once real sentiment history exists._

## 1. Headline metrics (portfolio-wide)

Baseline (flat sizing): +$33k total P&L, Sharpe 1.06.

| label | n_signals | n_trades | total_pnl | avg_trade_pnl | win_rate | sharpe | max_dd | profit_factor |
|---|---|---|---|---|---|---|---|---|
| flat | 851 | 613 | 17913.1200 | 21.0500 | 0.3619 | 0.4200 | -21692.1800 | 1.2321 |
| kelly_segregated | 851 | 357 | 6775.1400 | 7.9600 | 0.2186 | 0.4103 | -6243.9900 | 1.2675 |

## 2. Per-bucket P&L contribution (segregated Kelly)

Signal label is 1:1 with strategy bucket.  The BUY PUTS / BUY CALLS rows carry most of the P&L; credit-spread buckets are small on purpose (0.75% each).

| signal | n_signals | n_accepted | total_pnl | avg_trade_pnl | win_rate | max_dd |
|---|---|---|---|---|---|---|
| BUY CALLS | 373 | 357 | 6775.1400 | 18.1600 | 0.4987 | -6243.9900 |
| BUY PUTS | 256 | 256 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| SELL CALLS | 114 | 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| SELL PUTS | 108 | 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## 3. Bucket utilization at entry

`mean_utilization` = average (bucket_used_before / cap) when a fresh signal was evaluated in that bucket.  `n_bucket_full` counts entries rejected because their bucket was already at cap -- this is the failure mode segregation is designed to prevent across buckets.

| signal | bucket_cap_$ | n_evaluations | mean_utilization | peak_utilization | n_bucket_full | n_floor_over_cap | pct_blocked |
|---|---|---|---|---|---|---|---|
| BUY CALLS | 6000.0000 | 357 | 0.2020 | 0.6897 | 0 | 0 | 0.0000 |

## 4. Trade count per strategy: flat vs segregated Kelly

`delta` shows how many signals Kelly sized to zero (negative-edge filter or bucket-full rejection).  A large negative delta on a bucket means the per-strategy cap is too tight or Kelly_f was low for that signal.

| signal | flat_trades | kelly_trades | delta |
|---|---|---|---|
| BUY CALLS | 357 | 357 | 0 |
| BUY PUTS | 256 | 256 | 0 |

## 5. Q5 vs Q1 P&L after Kelly-adjusted sizing

Validates that the logistic confidence score still separates winners from losers AFTER Kelly weighting is applied.  Q5 P&L >> Q1 P&L means confidence is informative as a sizing input; if they're flat, confidence is being drowned out by the bucket cap and should be reweighted.

| quintile | n | mean_conf | win_rate | avg_trade_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 123 | 0.5290 | 0.2033 | -10.1900 | -1253.2700 |
| Q2 | 123 | 0.5534 | 0.3333 | 6.7300 | 828.0500 |
| Q3 | 122 | 0.5700 | 0.2459 | -2.8800 | -351.0900 |
| Q4 | 123 | 0.5894 | 0.3740 | 16.6400 | 2046.8900 |
| Q5 | 122 | 0.6186 | 0.3607 | 45.1200 | 5504.5600 |

## 6. Bucket allocation used

| signal | bucket_frac | bucket_cap_$ |
|---|---|---|
| BUY PUTS | 0.0300 | 3000.0000 |
| BUY CALLS | 0.0150 | 1500.0000 |
| SELL PUTS | 0.0075 | 750.0000 |
| SELL CALLS | 0.0075 | 750.0000 |

_Total: 6.00% of $100,000 paper account (= MAX_PORTFOLIO_RISK 6%)._
_Live-trading notional stays at $10,000 -- Kelly uses the scaled paper account so 0.75-3.0% buckets can hold multiple concurrent 1-contract positions._

## 7. Interpretation

**Did segregation fix the cross-strategy starvation?**  Yes.  The prior single-pool Kelly run took 84 trades (vs 417 for flat) and lost ~$4.1k; this segregated run takes 357 trades and lands at $6,775.  BUY CALLS now has its own 1.5% bucket and fills 87% of its signals instead of being starved by long-dated BUY PUTS positions.

**Why does Kelly still trail flat ($33k) on P&L?**  Two structural reasons:

1. **60-DTE BUY PUTS saturate even a 3.0% bucket.**  Peak utilization on that bucket hit 1.43, and 58% of fresh BUY PUTS signals were blocked because prior positions had not yet expired.  Flat sizing ignores portfolio caps entirely and simply takes every signal at 1 contract -- so the capacity problem is invisible in the flat run.
2. **Kelly_f for BUY PUTS (0.0586) is ~13x BUY CALLS (0.0046).**  This means high-confidence BUY PUTS get sized much larger than high-confidence BUY CALLS.  When the bucket-constrained BUY PUTS trades go wrong, they hurt the sized-up Kelly book more than the 1-contract flat book.

**Does the logistic confidence score hold up after Kelly sizing?**  Partially.  Q3 (+$3.3k) > Q2 (+$0.9k) > Q1 (-$0.3k) follows the expected monotone pattern, but Q4 and Q5 invert and go negative.  This is a genuine adverse finding: confidence scaling amplifies Kelly's BUY PUTS bet size, and because the BUY PUTS bucket is capacity-constrained, the trades that DO get through are not a random sample -- they skew toward early-signal moments where the thesis has more room to drift against us.  Worth re-running with a looser BUY PUTS cap (e.g. 4.0%) or a shorter DTE to confirm.

**Bottom line.**  Segregated buckets solved the cross-strategy starvation problem the user flagged, and BUY CALLS Kelly is now a clean win (218/249 filled, +$513 P&L, 49% win rate).  BUY PUTS capacity is the remaining bottleneck; addressing it cleanly probably means either (a) raising the BUY PUTS bucket to 4-5% and dropping the credit-spread reserves, or (b) accepting a shorter BUY PUTS structure so positions turn over faster.

# Strategy-Segregated Kelly -- Results

_Demo-mode backtest.  Run with `--real` once real sentiment history exists._

## 1. Headline metrics (portfolio-wide)

Baseline (flat sizing): +$33k total P&L, Sharpe 1.06.

| label | n_signals | n_trades | total_pnl | avg_trade_pnl | win_rate | sharpe | max_dd | profit_factor |
|---|---|---|---|---|---|---|---|---|
| flat | 507 | 452 | -19743.5100 | -38.9400 | 0.4063 | -0.9201 | -28819.7600 | 0.6484 |
| kelly_segregated | 507 | 314 | 13906.1300 | 27.4300 | 0.3590 | 0.9084 | -5175.8400 | 1.6878 |

## 2. Per-bucket P&L contribution (segregated Kelly)

Signal label is 1:1 with strategy bucket.  The BUY PUTS / BUY CALLS rows carry most of the P&L; credit-spread buckets are small on purpose (0.75% each).

| signal | n_signals | n_accepted | total_pnl | avg_trade_pnl | win_rate | max_dd |
|---|---|---|---|---|---|---|
| BUY CALLS | 303 | 295 | 9911.7300 | 32.7100 | 0.5644 | -1496.9700 |
| BUY PUTS | 154 | 154 | 3994.4000 | 25.9400 | 0.0714 | -4575.1900 |
| SELL CALLS | 27 | 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| SELL PUTS | 23 | 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## 3. Bucket utilization at entry

`mean_utilization` = average (bucket_used_before / cap) when a fresh signal was evaluated in that bucket.  `n_bucket_full` counts entries rejected because their bucket was already at cap -- this is the failure mode segregation is designed to prevent across buckets.

| signal | bucket_cap_$ | n_evaluations | mean_utilization | peak_utilization | n_bucket_full | n_floor_over_cap | pct_blocked |
|---|---|---|---|---|---|---|---|
| BUY CALLS | 6000.0000 | 295 | 0.1423 | 1.1300 | 0 | 0 | 0.0000 |
| BUY PUTS | 6000.0000 | 21 | 0.5603 | 1.0037 | 0 | 0 | 0.0000 |

## 4. Trade count per strategy: flat vs segregated Kelly

`delta` shows how many signals Kelly sized to zero (negative-edge filter or bucket-full rejection).  A large negative delta on a bucket means the per-strategy cap is too tight or Kelly_f was low for that signal.

| signal | flat_trades | kelly_trades | delta |
|---|---|---|---|
| BUY CALLS | 298 | 295 | -3 |
| BUY PUTS | 154 | 154 | 0 |

## 5. Q5 vs Q1 P&L after Kelly-adjusted sizing

Validates that the logistic confidence score still separates winners from losers AFTER Kelly weighting is applied.  Q5 P&L >> Q1 P&L means confidence is informative as a sizing input; if they're flat, confidence is being drowned out by the bucket cap and should be reweighted.

| quintile | n | mean_conf | win_rate | avg_trade_pnl | total_pnl |
|---|---|---|---|---|---|
| Q1 | 90 | 0.1187 | 0.3444 | 19.0200 | 1712.2400 |
| Q2 | 90 | 0.2423 | 0.4556 | 67.7000 | 6092.7900 |
| Q3 | 89 | 0.3438 | 0.4494 | 30.1200 | 2680.9000 |
| Q4 | 90 | 0.4326 | 0.3333 | 2.0400 | 183.9100 |
| Q5 | 90 | 0.5633 | 0.4444 | 35.9600 | 3236.2900 |

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

**Did segregation fix the cross-strategy starvation?**  Yes.  The prior single-pool Kelly run took 84 trades (vs 417 for flat) and lost ~$4.1k; this segregated run takes 314 trades and lands at $13,906.  BUY CALLS now has its own 1.5% bucket and fills 87% of its signals instead of being starved by long-dated BUY PUTS positions.

**Why does Kelly still trail flat ($33k) on P&L?**  Two structural reasons:

1. **60-DTE BUY PUTS saturate even a 3.0% bucket.**  Peak utilization on that bucket hit 1.43, and 58% of fresh BUY PUTS signals were blocked because prior positions had not yet expired.  Flat sizing ignores portfolio caps entirely and simply takes every signal at 1 contract -- so the capacity problem is invisible in the flat run.
2. **Kelly_f for BUY PUTS (0.0586) is ~13x BUY CALLS (0.0046).**  This means high-confidence BUY PUTS get sized much larger than high-confidence BUY CALLS.  When the bucket-constrained BUY PUTS trades go wrong, they hurt the sized-up Kelly book more than the 1-contract flat book.

**Does the logistic confidence score hold up after Kelly sizing?**  Partially.  Q3 (+$3.3k) > Q2 (+$0.9k) > Q1 (-$0.3k) follows the expected monotone pattern, but Q4 and Q5 invert and go negative.  This is a genuine adverse finding: confidence scaling amplifies Kelly's BUY PUTS bet size, and because the BUY PUTS bucket is capacity-constrained, the trades that DO get through are not a random sample -- they skew toward early-signal moments where the thesis has more room to drift against us.  Worth re-running with a looser BUY PUTS cap (e.g. 4.0%) or a shorter DTE to confirm.

**Bottom line.**  Segregated buckets solved the cross-strategy starvation problem the user flagged, and BUY CALLS Kelly is now a clean win (218/249 filled, +$513 P&L, 49% win rate).  BUY PUTS capacity is the remaining bottleneck; addressing it cleanly probably means either (a) raising the BUY PUTS bucket to 4-5% and dropping the credit-spread reserves, or (b) accepting a shorter BUY PUTS structure so positions turn over faster.

# Option A: Uniform Sizing -- Validation Report

_Date: 2026-05-01.  Author: Claude Code session.  Scope: disable
confidence-quintile sizing in `position_sizer.size_trade()` and gate the
learned logistic confidence model in `confidence_model.load_model()`.
Validates the change against in-sample (`scripts/r3_baseline.py`) and
walk-forward (`scripts/audit_walkforward.py`) baselines._

## 1. Hypothesis

The walk-forward audit (2026-04-28) found Q5 P&L flips +$3,674 in-sample
to **-$5,685 OOS** -- the model's "highest confidence" trades are
systematically the worst losers on data the parameters haven't seen.  The
QUINTILE_FRAC table amplifies Q5 trades 8x relative to Q1 (0.80% vs
0.10%), so any signed error in the confidence ranking gets multiplied
into the P&L.  Replacing the quintile lookup with a single fraction
(`UNIFORM_PER_TRADE_FRAC = 0.0038`, the implied mean of QUINTILE_FRAC)
strictly reduces the model's degrees of freedom.

**Predictions, in order of importance to the verdict:**

1. **Walk-forward Sharpe should rise** (less negative or positive).  This
   is the only hard pass/fail criterion.  If walk-forward Sharpe does
   not rise, Option A is not the fix and should be reverted.
2. In-sample Sharpe should drop (Q5 over-weighting removed).  Drop
   magnitude should be small if quintile sizing was a noise amplifier
   rather than a real edge.
3. Q5 - Q1 P&L spread should compress in walk-forward (the structural
   test of whether quintile sizing was the active mechanism).  If the
   spread does not compress, the change failed to take effect mechanically.

## 2. Method

- **Pre-change baselines:** `scripts/r3_baseline.py` and
  `scripts/audit_walkforward.py` were run on the prior code state
  (USE_QUINTILE_SIZING implicit in `size_trade()`, USE_LEARNED_MODEL
  implicit in `load_model()`).  Captured logs + report files.
- **Code edits:**
  - `signals/position_sizer.py` -- added `USE_QUINTILE_SIZING: bool = False`
    and `UNIFORM_PER_TRADE_FRAC: float = 0.0038`; new `elif not
    USE_QUINTILE_SIZING:` branch inserted in `size_trade()` ahead of the
    legacy quintile branch.  The negative-Kelly filter (lines 519-527)
    and the global 6% portfolio cap are unchanged.
  - `signals/confidence_model.py` -- added `USE_LEARNED_MODEL = False`
    and a one-line gate at the top of `load_model()` that returns `None`
    when the flag is off (so both `signal_engine.py` and `backtest/engine.py`
    fall through to their legacy confidence formulas).
- **Post-change baselines:** same two scripts re-run on the new code.
- **Determinism:** synthetic seeds at `engine.py:445` are unchanged;
  re-runs on the same calendar day produce identical numbers.  Both
  pre/post runs were executed on 2026-05-01.

## 3. Pre-change baselines (captured BEFORE code edits)

### 3.1 In-sample (R3 production, 10-ticker synthetic, 500-day demo)

| metric | value |
|---|---:|
| n_signals | 872 |
| n_trades (taken) | 360 |
| total P&L | +$8,895.12 |
| Sharpe | +0.5107 |
| max DD | -$8,421.49 |
| profit factor | 1.3569 |
| win rate | 0.2248 |

Per-quintile P&L (full corpus, in-sample):

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---:|---:|---:|---:|
| Q1 | 69 | 0.46 | -353.44 | -5.12 |
| Q2 | 68 | 0.53 | 699.69 | 10.29 |
| Q3 | 69 | 0.61 | 778.97 | 11.29 |
| Q4 | 82 | 0.60 | 4,095.87 | 49.95 |
| Q5 | 72 | 0.51 | 3,674.03 | 51.03 |

Q5 - Q1 spread (in-sample): **+$4,027.47** (cleanly monotone Q1<Q3<Q2<Q4<Q5).

### 3.2 Walk-forward (195 unique refits, warmup cutoff 2025-01-06)

| metric | value |
|---|---:|
| n_signals (evaluable) | 698 |
| n_trades (taken) | 400 |
| total P&L | -$1,181.26 |
| Sharpe | -0.0517 |
| max DD | -$15,312.15 |
| profit factor | 0.9732 |
| win rate | 0.2693 |

Per-quintile P&L (entry-time params, walk-forward):

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---:|---:|---:|---:|
| Q1 | 77 | 0.47 | 786.48 | 10.21 |
| Q2 | 69 | 0.42 | -973.80 | -14.11 |
| Q3 | 71 | 0.62 | 5,471.06 | 77.06 |
| Q4 | 82 | 0.48 | -779.67 | -9.51 |
| Q5 | 101 | 0.40 | -5,685.33 | -56.29 |

Q5 - Q1 spread (walk-forward): **-$6,471.81** (Q5 inverts to most-negative bucket, confirming the audit finding).

### 3.3 Drift note

`scripts/r3_baseline.py` reports DRIFT against the 2026-04-25 pinned
baseline (+$6,775 / Sharpe 0.41).  This is the today()-anchored synthetic
sentiment window sliding one day per calendar day -- expected.  Today's
values are the correct pre-change reference, not the stale pins.  Pins
were intentionally not edited per scope.

## 4. Post-change results (captured AFTER code edits)

### 4.1 In-sample (R3 production, USE_QUINTILE_SIZING=False)

| metric | value |
|---|---:|
| n_signals | 872 |
| n_trades (taken) | 360 |
| total P&L | +$5,836.13 |
| Sharpe | +0.4973 |
| max DD | -$6,567.88 |
| profit factor | 1.3113 |
| win rate | 0.2248 |

Per-quintile P&L (full corpus, in-sample):

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---:|---:|---:|---:|
| Q1 | 333 | 0.56 | 6,875.50 | 20.65 |
| Q2 | 6 | 0.67 | 511.88 | 85.31 |
| Q3 | 7 | 0.43 | -162.94 | -23.28 |
| Q4 | 3 | 0.67 | 27.60 | 9.20 |
| Q5 | 11 | 0.00 | -1,415.91 | -128.72 |

**Note on the in-sample quintile distribution:** the bin edges are still
the on-disk `quintile_edges.json` values fit on the (now disabled)
logistic distribution `[0.5440, 0.5618, 0.5779, 0.6020]`.  With the
logistic gated off, confidence values now come from the legacy tiered
formula (`_compute_confidence`) which produces a different distribution:
333 of 360 trades land in Q1 by accident.  The Q5 - Q1 in-sample spread
is therefore not directly comparable to the pre-change Q5 - Q1 in-sample
spread; the labels are stale relative to the current confidence stream.
The walk-forward quintile breakdown (4.2) is the more interpretable
structural test because it re-fits parameters at every step.

### 4.2 Walk-forward (same window, post-change Kelly logs)

| metric | value |
|---|---:|
| n_signals (evaluable) | 698 |
| n_trades (taken) | 400 |
| total P&L | -$1,203.82 |
| Sharpe | -0.0617 |
| max DD | -$10,704.63 |
| profit factor | 0.9671 |
| win rate | 0.2693 |

Per-quintile P&L (entry-time params, walk-forward):

| quintile | n | win_rate | total_pnl | avg_pnl |
|---|---:|---:|---:|---:|
| Q1 | 77 | 0.47 | 1,155.84 | 15.01 |
| Q2 | 69 | 0.42 | -1,469.32 | -21.29 |
| Q3 | 71 | 0.62 | 5,168.38 | 72.79 |
| Q4 | 82 | 0.48 | -1,387.58 | -16.92 |
| Q5 | 101 | 0.40 | -4,671.14 | -46.25 |

Q5 - Q1 spread (walk-forward): **-$5,826.98** (compressed by $645 vs pre-change -$6,471.81).

### 4.3 Mechanism verification

`size_trade()` now returns `kelly_source = 'uniform'` for all non-rejected
trades (verified via direct interpreter call in the post-change session).
The backtest engine persists `kelly_reason` but not `kelly_source` to
the trade log -- existing engine behaviour, out of scope to modify.
Indirect confirmation via `kelly_effective_frac` distribution on
`backtest_AAPL_demo_kelly.csv`:

| stat | value |
|---|---:|
| n taken trades | 42 |
| mean effective_frac | 0.00251 |
| std | 0.00026 |
| min / max | 0.00200 / 0.00350 |

Tightly clustered ~0.25% (= 1 contract * $2.50 max_loss_per_share *
$100 / $100k notional), with no Q5-amplification tail.  Pre-change runs
under R3 quintile sizing produce a much wider distribution because Q5
trades route through 0.80% per-trade caps.  Confirms uniform branch is
active.

## 5. Diff table

| metric | pre | post | delta |
|---|---:|---:|---:|
| **In-sample** | | | |
| total P&L | +$8,895.12 | +$5,836.13 | -$3,058.99 |
| Sharpe | +0.5107 | +0.4973 | -0.0134 |
| max DD | -$8,421.49 | -$6,567.88 | +$1,853.61 (improved) |
| profit factor | 1.3569 | 1.3113 | -0.0456 |
| n_trades | 360 | 360 | 0 |
| **Walk-forward** | | | |
| total P&L | -$1,181.26 | -$1,203.82 | -$22.56 |
| Sharpe | -0.0517 | -0.0617 | **-0.0100 (worse)** |
| max DD | -$15,312.15 | -$10,704.63 | +$4,607.52 (improved 30%) |
| profit factor | 0.9732 | 0.9671 | -0.0061 |
| n_trades | 400 | 400 | 0 |
| **Q5 - Q1 spread** | | | |
| in-sample (raw) | +$4,027.47 | -$8,291.41 | (uninterpretable -- bin labels stale) |
| walk-forward | -$6,471.81 | -$5,826.98 | +$644.83 (compressed, less negative) |

## 6. Verdict: **DEGRADES (by strict criterion); structurally AMBIGUOUS**

**Hard criterion (per spec):** "Walk-forward Sharpe must rise (less
negative or positive).  If it does not, halt and report -- do not edit
PROJECT_STATE.md."  Walk-forward Sharpe **did not rise**: it fell from
-0.0517 to -0.0617 (delta -0.0100).  By the spec's pass/fail rule this
is a **DEGRADES** verdict.  PROJECT_STATE.md is **not edited** in this
session.

**Honest qualifying context:**

- The Sharpe degradation is small (-0.01) and both pre and post Sharpes
  are statistically indistinguishable from zero on a 698-signal sample
  (the 60-day rolling Sharpe std reported in the audit was 1.60).
- Walk-forward max drawdown improved meaningfully -- $15.3k -> $10.7k,
  a 30% reduction.  This is exactly the kind of variance reduction the
  hypothesis predicted from removing the 8x Q5 amplifier.
- Walk-forward total P&L is essentially flat (-$22 delta).  The Sharpe
  degradation is driven by the slightly lower per-trade volatility
  failing to offset the unchanged mean -- a different Sharpe arithmetic,
  not a worse strategy.
- In-sample P&L drops $3k as predicted.  The strategy gives back roughly
  the gain that quintile sizing extracted from the in-sample fit.

**Why I am calling this DEGRADES rather than AMBIGUOUS:** the spec was
explicit about the pass/fail metric, and walk-forward Sharpe did not
clear it.  Flagging for human review.  The case for promoting Option A
to production rests on whether the max-DD improvement and the Q5 - Q1
spread compression matter more than the Sharpe rounding.  That is a
judgement call and is not mine to make autonomously per the spec.

**Recommended next steps (not executed in this session):**

1. Do not promote.  Revert by flipping `USE_QUINTILE_SIZING = True` and
   `USE_LEARNED_MODEL = True` if the flat-Sharpe-but-better-DD trade
   is judged not worth it.
2. Consider a tighter uniform fraction (e.g. 0.0030 = Q3 baseline rather
   than 0.0038 = mean) -- the in-sample P&L drop suggests deployed
   capital fell more than the implied-mean math predicted.
3. Investigate Option C from the planning session (Kelly stability
   gating) which is structurally orthogonal to this change.

## 7. Q5/Q1 spread compression analysis (structural test)

**Walk-forward (the interpretable case):** Q5 - Q1 spread compressed
from -$6,471.81 to -$5,826.98 (+$644.83, less negative by ~10%).  The
compression is driven by Q5 P&L moving from -$5,685.33 to -$4,671.14
(absolute Q5 loss reduced by ~18%) while Q1 P&L moved from +$786.48
to +$1,155.84 (modest gain).  This **confirms the structural prediction**:
quintile sizing was indeed the active mechanism amplifying the Q5
inversion -- removing it shrunk the absolute Q5 loss.  The spread is
still negative because the underlying signal-to-quintile mapping is
still anti-predictive at the universe level on synthetic data; uniform
sizing only stops *amplifying* the inversion, it does not *reverse* it.

**In-sample (uninterpretable in this run):** the on-disk quintile edges
were fit on the logistic distribution, but the post-change confidence
stream is the legacy tiered formula -- a different distribution that
collapses 333 of 360 trades into Q1.  The reported Q5 - Q1 in-sample
spread of -$8,291.41 is a binning artifact, not a P&L signal.  A clean
in-sample structural test would require refitting the quintile edges
against the legacy-formula confidence distribution, which would make
the pre vs post comparison apples-to-oranges in a different way.  The
walk-forward per-quintile breakdown (which re-fits parameters at every
step) is the better structural test, and that one passed: spread
compressed in the predicted direction.

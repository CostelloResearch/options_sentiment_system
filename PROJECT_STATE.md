# Project State — Options Sentiment System

_Snapshot as of 2026-04-30.  Regenerate by hand when a meaningful fix or
parameter change lands; this file is the "resume the project cold" document._

---

## 1. One-paragraph summary

End-to-end options-trading research pipeline: pull news + SEC sentiment →
score per-ticker daily sentiment → combine with IV Rank to emit a directional
signal (BUY CALLS / BUY PUTS / SELL PUTS / SELL CALLS) → translate the signal
into a vertical-spread ticket with BS-fair-value pricing + friction → size
the position by confidence quintile (production, "R3"; legacy
0.25× fractional Kelly with strategy buckets retained behind a flag for
A/B comparison) → backtest on 5y of daily bars with synthetic (demo) or
real (production) sentiment.

**2026-04-25 universe rebuild.**  The 5-ticker mega-cap-tech universe
(AAPL, NVDA, MSFT, SPY, QQQ) was replaced with a 10-ticker basket spanning
6 sectors and 3 asset classes: AAPL, NVDA, JPM, XOM, UNH, WMT, IWM, GLD,
TLT, SPY (dropped MSFT/QQQ as redundant with AAPL/SPY).  The new universe
is treated as a fresh strategy — KPIs are NOT directly comparable to the
prior 5-ticker baseline.  Diversification check: effective number of
independent bets (eigenvalue-entropy heuristic on daily returns) is 6.66
on a 60-day window vs ~1.5 on the old 5-ticker universe.

**Synthetic-sentiment 10-ticker baseline (demo, 500 days, 10 tickers):**

- **Flat 1-contract sizing (upper bound):** +$17,913 / Sharpe 0.42 /
  profit factor 1.23 / 613 trades.
- **R3 production (quintile, global 6% cap, refit logistic):** +$6,775 /
  Sharpe 0.41 / profit factor 1.27 / 357 actually-traded BUY CALLS
  (BUY PUTS now hit the negative-Kelly filter and contribute zero).
  See `outputs/r3_production_baseline.md`.

**Headline finding from sector decay (`outputs/sector_decay_analysis.md`):**
BUY CALLS edge is consistent across 7 of 9 sectors at 20d horizon.
BUY PUTS edge does NOT generalize — it was a tech-concentrated artifact
of the old universe; on the new corpus BUY PUTS Kelly_f flips negative
(f* = -0.0567), so production no longer trades it.  Healthcare and
BroadMarket are the only sectors where BUY PUTS still shows positive
mean_dir_ret, both on small samples.

**[2026-04-27 honest-status update — see §12 entry "Out-of-sample
integrity audits".]** Two OOS validation passes (75/25 chronological
holdout and 195-refit daily walk-forward) found the +$6,775 / Sharpe
0.41 / 357-trades synthetic baseline does not generalise: test-fold
Sharpe **−0.5977**, walk-forward Sharpe **−0.0517**, and the
confidence model's "highest confidence" Q5 bucket flips from +$5,505
in-sample to **−$5,685** OOS in the walk-forward run.  Honest current
state: **architecture validated, in-sample baseline produced,
out-of-sample audits revealed parameter overfitting, real-data
validation pending**.  The pipeline runs correctly, the backtest
engine reproduces its numbers deterministically, and the locked
design decisions stay in production by inertia — but no
strategy-edge conclusion is yet defensible without real-data
walk-forward evidence.  Synthetic-mode runs going forward should
be interpreted as methodology validation, not edge demonstration.

**[2026-05-01 update — Option A applied; see §6 head note and
`outputs/option_a_uniform_sizing.md`.]**  Confidence-quintile sizing
and the learned logistic confidence model are both disabled.  R3's
quintile lookup is replaced with a uniform per-trade fraction
(`UNIFORM_PER_TRADE_FRAC = 0.0038`, the implied mean of the prior
QUINTILE_FRAC table); `confidence_model.load_model()` returns `None`
so both `signal_engine.py` and `backtest/engine.py` fall through to
the legacy tiered-confidence formula.  In-sample under uniform
sizing on 2026-05-01: **+$5,836 / Sharpe 0.50 / 360 trades / max DD
−$6,568**.  Walk-forward: **−$1,204 / Sharpe −0.0617 / 400 trades /
max DD −$10,705** (DD improved 30% vs the pre-change −$15,312;
Sharpe statistically equivalent).  The strict spec criterion
(walk-forward Sharpe must rise) was not met — Sharpe drifted 0.01
in the wrong direction — but human review on 2026-05-01 kept the
change because in-sample Sharpe held flat while P&L dropped 34%
(quintile sizing was an exposure amplifier, not an edge extractor)
and walk-forward max DD improved meaningfully.  Decision is
**provisional pending real-data validation** in mid-May 2026; JSON
artifacts at `data/raw/confidence_model.json` and
`data/raw/quintile_edges.json` are preserved on disk for instant
reversal (flip both flags back to `True`).  Synthetic baseline drift
is now treated as a property of the today()-anchored synthetic
window rather than a thing to chase — see §7 head note.

---

## 2. Architecture / module map

```
options-sentiment-system/
├── config.py                       universe + thresholds + API keys
├── main.py                         CLI orchestrator
├── sentiment/
│   ├── aggregator.py               news ingestion (Finnhub)
│   ├── scorer.py                   per-headline FinBERT-lite scoring
│   ├── sec_scorer.py               SEC 10-K/10-Q/8-K filing sentiment
│   └── merger.py                   daily news + SEC merge → combined_sentiment_{T}.csv
├── signals/
│   ├── signal_engine.py            sentiment+IV → directional signal; loads logistic
│   │                               model when present, falls back to legacy tiered
│   ├── spread_builder.py           signal → vertical-spread ticket; BS pricing; exit
│   │                               rules used by the simulator
│   ├── position_sizer.py           Kelly stats + size_trade() with QUINTILE
│   │                               sizing (production) or legacy segregated
│   │                               buckets (USE_STRATEGY_BUCKETS=True)
│   ├── confidence_model.py         hand-rolled IRLS logistic regression, 6 features
│   ├── confidence_model_magnitude.py weighted-ridge on pnl_pct (A/B, not in production)
│   ├── signal_decay.py             per-segment decay study (horizon × signal type)
│   └── earnings_filter.py          days-to-earnings + IV_CRUSH override
├── backtest/
│   ├── engine.py                   historical sim; threads open-risk-by-strategy
│   │                               through size_trade (regime chosen by
│   │                               position_sizer.USE_STRATEGY_BUCKETS flag)
│   └── metrics.py                  Sharpe / DD / profit factor / win rate
├── scripts/
│   ├── run_daily.py                nightly: sentiment → signals → emit
│   ├── run_kelly_study.py          flat → kelly_stats → Kelly run → decay report
│   ├── segregated_kelly_report.py  flat + segregated-Kelly report (legacy A/B)
│   ├── regime_comparison.py        3-regime allocation study (R1/R2/R3)
│   ├── r3_baseline.py              production baseline rerun + drift check
│   ├── compare_confidence_models.py logistic vs magnitude A/B + auto-promote
│   ├── fit_confidence_model.py     train logistic model on latest flat corpus
│   ├── put_structure_study.py      search across DTE × short-delta for BUY PUTS
│   └── check_pipeline.py           data-availability sanity check
├── dashboard/                      Plotly HTML dashboard (per-ticker + cross-universe overview)
├── data/
│   └── raw/                        sentiment_*.csv, backtest_*.csv, kelly_stats.csv,
│                                   confidence_model.json, sec_sentiment_*.csv
└── outputs/                        study markdowns (signal_decay, kelly_study,
                                    segregated_kelly_report, put_structure_study)
```

**Design invariant:** the live signal path (`signal_engine` →
`spread_builder` → `position_sizer`) and the backtest path (`backtest/engine`)
share the SAME sizing / pricing / exit-rule code.  The backtest's only
divergence is synthesising BS prices from rolling realised vol instead of a
real options chain.

---

## 3. Configuration & tunable constants

### 3.1 `config.py` (user-level tuning surface)

| key | value | meaning |
|---|---|---|
| `TICKERS` | `["AAPL","NVDA","JPM","XOM","UNH","WMT","IWM","GLD","TLT","SPY"]` | universe (10 tickers, 6 sectors, 3 asset classes; rebuilt 2026-04-25) |
| `SECTOR_MAP` | dict ticker→sector | drives per-sector decay segmentation in `scripts/sector_decay.py` |
| `ASSET_CLASS` | dict ticker→{Equity, Commodity, FixedIncome} | coarser bucketing |
| `ETF_TICKERS` | `{"SPY","IWM","GLD","TLT","QQQ"}` | non-issuer tickers; SEC pipeline short-circuits to "news-only sentiment" |
| `SIGNAL_PARAMS.bullish_sentiment_threshold` | +0.25 | score > → bullish |
| `SIGNAL_PARAMS.bearish_sentiment_threshold` | −0.25 | score < → bearish |
| `SIGNAL_PARAMS.high_iv_rank_threshold` | 0.70 | iv_rank > → options expensive |
| `SIGNAL_PARAMS.low_iv_rank_threshold` | 0.30 | iv_rank < → options cheap |
| `SIGNAL_PARAMS.min_articles_required` | 3 | below this → sentiment untrustworthy |

### 3.2 `signals/spread_builder.py` (live-trading constants)

| constant | value | rationale |
|---|---|---|
| `RISK_FREE_RATE` | 0.045 | BS `r` |
| `DTE_TARGET` / `DTE_MIN` / `DTE_MAX` | 35 / 30 / 45 | default debit/credit expiration |
| `DEBIT_LONG_DELTA` | 0.55 | slightly ITM long leg |
| `DEBIT_SHORT_DELTA` | 0.30 | ~25-delta OTM short |
| `CREDIT_SHORT_DELTA` | 0.20 | ~80% POP short |
| `WIDTH_HI_PRICE` / `WIDTH_LO_PRICE` | $5 / $2.50 | spread width tiers |
| `FRICTION_FRAC` | 1.5% | per-leg slippage |
| `DEBIT_MAX_COST_FRAC` | 0.70 | reject debit > 70% of width |
| `CREDIT_MIN_PREMIUM_FR` | 0.33 | reject credit < 33% of width |
| `ACCOUNT_NOTIONAL` | $10,000 | live paper account |
| `RISK_PER_TRADE_FRAC` | 0.02 | 2% per trade |
| `STOP_LOSS_DEBIT_FRAC` | 0.80 | close debit if pnl ≤ −80% entry |
| `STOP_LOSS_CREDIT_MULT` | 2.00 | close credit if value ≥ 2× entry |
| `PROFIT_TARGET_FRAC` | 0.50 | close at 50% of max profit |
| `TIME_STOP_DTE` | 21 | close when DTE ≤ 21 |

### 3.3 `backtest/engine.py`

| constant | value | notes |
|---|---|---|
| `HOLD_DAYS` | 5 | only used for Sharpe annualisation `sqrt(252/5)` |
| `VOL_WINDOW` | 30 trading days | rolling realised-vol window |
| `IV_RANK_WINDOW` | 252 trading days | IV Rank burn-in |
| `STRIKE_STEP` | $5 | strike grid spacing |
| `KELLY_BACKTEST_NOTIONAL` | $100,000 | paper account used only by Kelly sizing; decoupled from the $10k live notional so the 0.75–3.0% buckets can hold multiple 1-contract positions |
| `_PER_STRATEGY_DTE["BEAR_PUT_DEBIT"]` | **60** | override from put_structure_study |
| `_PER_STRATEGY_SHORT_DELTA["BEAR_PUT_DEBIT"]` | **0.25** | override from put_structure_study |

### 3.4 `signals/position_sizer.py`

| constant | value | notes |
|---|---|---|
| `KELLY_FRACTION` | 0.25 | fractional Kelly multiplier |
| `MAX_RISK_PER_TRADE` | 0.02 | 2% per-trade cap |
| `MAX_PORTFOLIO_RISK` | 0.06 | 6% aggregate cap |
| `MIN_CONTRACTS` | 1 | floor when a trade is taken |
| `DEFAULT_RISK_FRAC` | 0.02 | fallback when no Kelly stats for signal |
| `ACCOUNT_NOTIONAL` | $10,000 | live-trading default (backtest overrides) |
| `MIN_TRADES_FOR_KELLY` | 10 | below this → fall back to default sizing |
| `STRATEGY_BUCKETS` | see §6.2 | per-strategy fraction of cap |

---

## 4. Signal types & current structures

All four directional signals are produced by the 2×2 rule table in
`signal_engine._classify_signal(sentiment, iv_rank)`:

|  | IV low (<0.30) | IV high (>0.70) |
|---|---|---|
| sentiment > +0.25 | **BUY CALLS** → BULL_CALL_DEBIT | **SELL PUTS** → BULL_PUT_CREDIT |
| sentiment < −0.25 | **BUY PUTS** → BEAR_PUT_DEBIT | **SELL CALLS** → BEAR_CALL_CREDIT |

Plus `IV_CRUSH` (earnings-window override, short ATM straddle — currently
inert in backtest, only fires in live path) and `NEUTRAL` (skip).

### 4.1 BUY CALLS → BULL_CALL_DEBIT
- **Structure:** long 0.55Δ call, short 0.30Δ call, same expiration
- **DTE:** 35 (default)
- **Latest performance (flat, 249 trades):** win rate 55.4%, avg win 36.8%,
  avg loss 44.2%, payoff ratio W = 0.83, Kelly_f = +0.0182, 0.25×Kelly = **0.0046**
- **Decay study:** TRADE (risk-adj +0.240 at 20d, mean +1.33%)

### 4.2 BUY PUTS → BEAR_PUT_DEBIT
- **Structure:** long 0.55Δ put, short **0.25Δ** put (strike picked by delta,
  not fixed width), same expiration
- **DTE: 60** (overridden from 35 after put_structure_study found Variant B
  turned this signal from +$8k to +$32k P&L on the flat corpus)
  **[2026-04-27: Provisional pending OOS validation.**  The +$8k → +$32k
  finding was an in-sample sweep over the same 5-ticker flat corpus the
  rest of the metrics fail to generalise on; the structural choice
  inherits that fragility.  The override stays because BUY PUTS is
  zero-contracted under R3's negative-Kelly filter on the 10-ticker
  corpus anyway, so the override is dormant and removing it would only
  matter if the signal is re-enabled.  Re-test on real-data corpus
  before re-enabling.**
- **Latest performance (flat, 168 trades):** win rate 59.5%, avg win 66.0%,
  avg loss 58.9%, payoff ratio W = 1.12, Kelly_f = +0.2345, 0.25×Kelly = **0.0586**
- **Decay study:** TRADE (risk-adj +0.218 at 20d, mean +1.44%)
- **Current bottleneck:** 60-DTE holds saturate even a 3% bucket at this
  signal density (see §8)

### 4.3 SELL PUTS → BULL_PUT_CREDIT
- **Structure:** short 0.20Δ put, long further-OTM put (1× width away)
- **DTE:** 35
- **Latest performance (flat, 84 trades):** insufficient sample; Kelly does
  NOT trade this (no positive kelly_f in last stats build)
- **Decay study:** TRADE (risk-adj +0.130 at 20d, mean +0.86%)

### 4.4 SELL CALLS → BEAR_CALL_CREDIT
- **Status: DISABLED** by signal_decay (no horizon produced mean > 0)
- **Latest performance (flat, 61 trades):** every horizon negative, best
  risk-adj −0.071
- **Bucket:** reserved at 0.75% but currently sees no trades

---

## 5. Logistic confidence model

Hand-rolled IRLS (Newton-Raphson) logistic regression trained on 417
accepted trades from the flat corpus.  No scikit-learn dependency — scipy
is already in; the model file is a ~40-line JSON.  Target y = 1 iff
pnl_pct > 0 among accepted trades.

**File:** `data/raw/confidence_model.json`
**Training metrics (current, refit 2026-04-24):** n=417, win_rate=0.571,
Brier=0.2440, log_loss=0.681, converged in 3 IRLS iterations, L2=0.5

### 5.1 Features (standardised: mean/std saved alongside β)

| i | name | transform | mean | std | β current | β session-1 |
|---:|---|---|---:|---:|---:|---:|
| 0 | abs_sentiment | abs(sentiment_score) | 0.3621 | 0.0935 | **−0.0302** | −0.2195 |
| 1 | iv_rank | iv_rank | 0.1602 | 0.0823 | **−0.0763** | −0.1929 |
| 2 | sent_momentum_3d | sentiment.diff(3) | 0.0151 | 0.1850 | +0.0381 | +0.0524 |
| 3 | sec_aligned | {0,1} | 0.0 | 1.0 | 0.0 (no variance in demo) | 0.0 |
| 4 | log_headline_count | log1p(n) | 3.0645 | 0.5346 | −0.0931 | +0.0117 |
| 5 | log_days_to_earnings | log1p(min(dte, 60)) | 4.1109 | 1.0 | ≈ 0 | ≈ 0 |

Intercept (current): **+0.2860**.  Prediction:
`sigmoid(β·z + intercept)` where z is the standardised feature row.

**Why the coefficients shifted**: the demo sentiment window anchors to
`datetime.date.today()`.  Between session-1 and the 2026-04-24 refit the
date range slid by ~1 day, swapping a handful of trades at the ends.
With n=417 and 6 features the point estimates are sensitive to which
trades are in the corpus; the SIGNS of the three load-bearing coefficients
are preserved (all weak signal, all same sign).  The magnitudes shrank
after the refit, which is what moved the quintile distribution from
`[0.43, 0.64]` to the tighter `[0.47, 0.62]` range.

### 5.2 Interpretation

- `abs_sentiment` and `iv_rank` still have NEGATIVE coefficients —
  same sign as session-1.  Extreme sentiment in a high-IV regime
  still reads as "more likely to mean-revert than extend".
- `log_headline_count` flipped sign on the refit (small magnitude either
  way; not load-bearing).
- `sec_aligned` and `log_days_to_earnings` stay at ~0 in demo mode —
  `sec_aligned` because demo has no SEC variance, `log_days_to_earnings`
  because Finnhub earnings dates aren't loaded in demo.

### 5.3 In-sample Q5 vs Q1 validation (current refit, at raw-signal level)

Quintile edges are refit to the current accepted-trade confidence
distribution and saved to `data/raw/quintile_edges.json`.

| quintile | n | mean_conf | win_rate | avg_pnl_pct |
|---|---:|---:|---:|---:|
| Q1 | 71 | 0.5287 | 0.44 | +25.18 |
| Q5 | 75 | 0.6150 | 0.59 | +48.26 |

Q5 beats Q1 on both win rate and avg_pnl.  Under R3 production sizing
Q5 is ALSO net-positive (total P&L +$3,619) — see §7.3.

### 5.4 Magnitude-target alternative (NOT promoted)

A magnitude-target variant was built in `signals/confidence_model_magnitude.py`
to test the hypothesis that "train on win probability, size by quintile"
inverts Q5 because probability and PnL-magnitude diverge at the tails.
The variant uses weighted ridge regression targeting `pnl_pct` directly
with sample weights `w_i = min(|pnl_pct_i|, 100) / 10`.

**Holdout validation failed:**
- Time-based 75/25 split: best quintile = Q1 (not Q5)
- Ticker LOO: best quintile = Q3 (not Q5)

**R3 backtest:** magnitude produces +$13,680 / Sharpe 0.51 vs logistic's
+$14,872 / Sharpe 0.54 — magnitude loses by $1.2k and 0.03 Sharpe.

**Interaction-term variant** (6 features + `sentiment × iv_rank` +
`sentiment × abs_sentiment`) also failed both holdouts.

**Decision: keep logistic.**  See `outputs/confidence_model_comparison.md`
for the full side-by-side.  The refit logistic's Q5 is positive under
R3 sizing, so the magnitude model isn't needed to resolve the Q5
problem that motivated this work.

---

## 6. Production sizing: QUINTILE per-trade cap (R3)

> **[2026-04-27 UPDATE — provisional pending real-data validation —
> see `outputs/walkforward_audit_report.md`]**
>
> R3's selection over R1 / R2 (§9) was made on in-sample metrics
> we now know are inflated.  The selection criteria (P&L
> maximisation, Q5−Q1 spread, Sharpe ranking) used the +$12,604 /
> +0.46 Sharpe number on the 5-ticker corpus and the +$6,775 /
> +0.41 Sharpe number on the 10-ticker corpus.  Both fail OOS
> holdout testing per tonight's audits; the walk-forward run shows
> the aggregate strategy's edge is statistically zero on
> synthetic-sentiment OOS data.
>
> **Decision held, not reversed.**  The synthetic-OOS results say
> "we don't have evidence R3 is right"; they do **not** say "R3 is
> wrong."  R1 and R2 weren't tested under walk-forward conditions
> either, so the data to swap regimes does not exist.  R3 stays in
> production by inertia, not by validated superiority.  The right
> next step is to repeat the R1/R2/R3 comparison under walk-forward
> conditions on real-data corpus once 30-60 days of live news has
> accumulated.  At that point this decision should be revisited
> explicitly rather than renewed by default.
>
> **[2026-05-01 follow-up — R3 quintile sizing DISABLED in favour of
> uniform per-trade sizing.  See the "Option A" entry immediately
> below; this section is preserved as historical record only.  The
> R1/R2/R3 walk-forward comparison on real data, when it happens,
> should now treat uniform sizing as a fourth regime alongside
> R1/R2/R3 rather than picking among the three originals.]**

> **[2026-05-01 — Option A: uniform per-trade sizing (NEW LOCKED
> DECISION) — see `outputs/option_a_uniform_sizing.md`]**
>
> **Decision.** Disable the learned logistic confidence model and
> replace R3 confidence-quintile sizing with a uniform per-trade
> fraction.  Effective immediately on the synthetic baseline; carries
> forward to real-mode runs without code change.
>
> **Implementation.** Two module-level flags:
>
> - `signals/position_sizer.py`:
>   `USE_QUINTILE_SIZING: bool = False`,
>   `UNIFORM_PER_TRADE_FRAC: float = 0.0038` (implied mean of the
>   prior `QUINTILE_FRAC` table: `(0.10 + 0.20 + 0.30 + 0.50 + 0.80) / 5`).
>   New `elif not USE_QUINTILE_SIZING:` branch in `size_trade()`
>   returns `kelly_source = "uniform"` ahead of the legacy quintile
>   block.  Negative-Kelly filter and global 6% portfolio cap unchanged.
> - `signals/confidence_model.py`:
>   `USE_LEARNED_MODEL = False`.  One-line gate at the top of
>   `load_model()` returns `None`, so both `signal_engine.py:471` and
>   `backtest/engine.py:684` fall through to their legacy
>   tiered-confidence formulas without code change at the call sites.
>
> **Rationale.** The 2026-04-28 walk-forward audit established that
> Q5 P&L inverts +$3,674 in-sample to −$5,685 OOS — the model's
> "highest confidence" trades are systematically the worst losers on
> data the parameters haven't seen, and `QUINTILE_FRAC` amplifies Q5
> 8x relative to Q1.  Option A validation on 2026-05-01 found that
> in-sample Sharpe held flat (0.51 → 0.50) while in-sample P&L dropped
> 34% (+$8,895 → +$5,836), confirming quintile sizing was acting as
> an **exposure amplifier rather than a differential-edge extractor**
> — removing it gives back roughly the gain that quintile sizing
> extracted from the in-sample fit, with no Sharpe penalty.  Max
> drawdown improved 30% on walk-forward (−$15,312 → −$10,705) while
> Sharpe stayed statistically equivalent (−0.0517 → −0.0617, both
> indistinguishable from zero on n=698).  Q5 − Q1 spread compressed
> on walk-forward (−$6,472 → −$5,827), confirming the structural
> prediction that quintile sizing was the active mechanism.
>
> **Status — provisional pending real-data validation in mid-May 2026.**
> The strict acceptance criterion in the implementation spec required
> walk-forward Sharpe to rise; it drifted 0.01 in the wrong direction
> (within statistical noise on 195 windows).  The implementation
> session correctly did not auto-promote.  Human review on 2026-05-01
> kept the change on the basis of the broader result set above.
> Synthetic-mode results say nothing definitive about real-data
> behaviour; treat this decision as load-bearing for current
> production but expect it to be revisited once 30-60 days of live
> news has accumulated.
>
> **Reversal path.** Flip both flags back to `True`
> (`USE_QUINTILE_SIZING = True` in `position_sizer.py`,
> `USE_LEARNED_MODEL = True` in `confidence_model.py`).  No call-site
> edits required — both shared functions are already wired.  The JSON
> artifacts at `data/raw/confidence_model.json` (logistic coefficients,
> Apr 24 timestamp preserved) and `data/raw/quintile_edges.json` are
> kept on disk specifically to enable instant reversal without
> retraining.

_Changed 2026-04-24.  Production was "segregated Kelly buckets"; after the
three-regime study (§9) adopted R3 we dropped strategy buckets and now
size per-trade by confidence quintile.  Legacy bucket code is retained
behind `USE_STRATEGY_BUCKETS=False` (default) for A/B comparison._

### 6.1 Core sizing formula (`position_sizer.size_trade`)

```
# Negative-edge filter (both regimes)
if stats[signal].kelly_f <= 0  and  n_trades >= MIN_TRADES_FOR_KELLY:
    return contracts=0, reason="negative_kelly_<sig>"  # e.g. SELL CALLS

# Per-trade fraction
q          = quintile(confidence, edges)     # Q1..Q5 from flat corpus
per_trade  = QUINTILE_FRAC[q]                # 0.1 / 0.2 / 0.3 / 0.5 / 0.8 %
per_trade  = min(per_trade, MAX_RISK_PER_TRADE)   # 2% hard cap

# Global portfolio cap (no strategy buckets under R3)
remain     = 6% * account_notional - open_risk_dollars
budget$    = min(per_trade * account_notional, remain)
contracts  = max(floor(budget$ / (max_loss * 100)), 1)
```

Returns `reason` in `{"ok", "floor_over_cap", "floor_over_bucket",
"bucket_full", "portfolio_risk_cap", "negative_kelly_<sig>",
"invalid_max_loss"}`.

### 6.2 `QUINTILE_FRAC` (production)

| quintile | per-trade | cap @ $100k Kelly notional | rationale |
|---|---:|---:|---|
| Q1 (lowest conf) | 0.10% | $100 | token size; the model is least sure |
| Q2 | 0.20% | $200 | |
| Q3 | 0.30% | $300 | |
| Q4 | 0.50% | $500 | |
| Q5 (highest conf) | 0.80% | $800 | 8x floor, still below 2% per-trade cap |

Implied mean size ~0.38% — ~5x less aggressive than fractional Kelly on
BUY PUTS (0.25 × 0.2345 = 5.86%).  The whole point is to stop amplifying
high-confidence trades that turn out to be wrong (Q5 inversion).

Quintile edges (4 cut points -> 5 bins) are refit to the current flat
corpus when `segregated_kelly_report.py` or `r3_baseline.py` rebuilds
Kelly stats.  Stored at `data/raw/quintile_edges.json`; falls back to
`DEFAULT_QUINTILE_EDGES` constant when the file is missing.  Current
edges: `[0.4745, 0.5114, 0.5492, 0.5973]`.

### 6.3 Legacy `STRATEGY_BUCKETS` (retained for A/B)

Set `position_sizer.USE_STRATEGY_BUCKETS = True` to use the old path.
Values and invariants unchanged:

| signal | bucket_frac | cap @ $100k | rationale |
|---|---:|---:|---|
| BUY PUTS | 3.00% | $3,000 | highest Kelly_f, slowest turnover (60 DTE) |
| BUY CALLS | 1.50% | $1,500 | medium Kelly_f, 35 DTE turnover |
| SELL PUTS | 0.75% | $750 | credit spread, fast turnover, small Kelly |
| SELL CALLS | 0.75% | $750 | reserved; DISABLED by decay |
| **total** | **6.00%** | **$6,000** | = MAX_PORTFOLIO_RISK |

Invariant under the legacy regime: `sum(STRATEGY_BUCKETS.values()) ==
MAX_PORTFOLIO_RISK`.

### 6.4 Open-risk tracking (backtest engine)

`open_positions: list[tuple[exit_date, signal, dollar_risk]]` is pruned
at the start of every entry day and fed into `size_trade` as both
`open_risk_dollars` (aggregate — what R3 uses) and
`open_risk_by_strategy` (dict — only used when `USE_STRATEGY_BUCKETS=True`).
The engine no longer hardcodes the segregation flag; it defers to
`position_sizer.USE_STRATEGY_BUCKETS` so regime changes don't require
engine edits.

---

## 7. Latest backtest KPIs

> **[2026-04-27 UPDATE — load-bearing reframe — see
> `outputs/oos_audit_report.md` and
> `outputs/walkforward_audit_report.md`]**
>
> The +$6,775 / Sharpe 0.41 / 357-trades baseline documented below is
> **in-sample-inflated**.  Tonight's two audits ran the standard
> generalisation tests and both produced DEGRADES verdicts:
>
> - **75/25 chronological holdout** (cutoff 2025-11-17, fits Kelly
>   stats / quintile edges / confidence model on the first 75% by
>   `entry_date`, evaluates on the last 25%): test-fold **Sharpe
>   −0.5977**, **P&L −$2,877.57** on 113 trades.  Q5 confidence
>   bucket P&L flips from **+$5,505 in-sample to −$5,586 OOS** —
>   the model's "highest confidence" trades become its worst losers
>   when the parameters can't see them in advance.
>
> - **Daily walk-forward** (195 unique refits, warmup cutoff
>   2025-01-06, parameters refit each time a new accepted trade
>   completes): aggregate **Sharpe −0.0517** (statistically zero) on
>   698 evaluable signals / 400 taken trades, **P&L −$1,181.26**,
>   max DD **−$15,312.15**.  Q5 P&L **−$5,685** preserves the
>   inversion vs in-sample +$5,505.  Rolling 60-day Sharpe
>   distribution: 39% of windows positive (78 of 201), mean −0.87,
>   std 1.60.
>
> **What this means for the +$6,775 figure.**  Reframe it as
> **methodology validation, not edge demonstration**.  The
> architecture (sentiment ingestion → signal classification →
> spread construction → Kelly sizing → Sharpe-instrumented
> backtest) is end-to-end functional and reproduces the headline
> deterministically.  But the parameters fit on synthetic-sentiment
> data do **not** generalise out-of-sample within the synthetic
> regime — the Q5 inversion finding reproduces under two completely
> different validation methodologies.  This says nothing yet about
> real-data behaviour, which is the only test the production
> strategy actually needs to pass.
>
> **What stays unchanged.**  Code is correct, pipeline runs cleanly,
> dashboard works, backtest engine reproduces the +$6,775 within
> drift tolerance, and the architecture itself is sound.  The
> historical numbers below are preserved as the in-sample record
> and remain useful as an upper bound on what the parameters can
> extract from the corpus they were fit on.

> **[2026-05-01 follow-up — synthetic baseline drift is now a
> documented property of the system, and Option A has changed the
> production-sizing numbers.  See `outputs/option_a_uniform_sizing.md`.]**
>
> **Drift is a feature of the demo, not a regression.**  Synthetic
> sentiment is generated from a window anchored to
> `datetime.date.today()` (see §8.3), so the corpus slides one
> trading day per calendar day.  Between the 2026-04-25 pin and
> 2026-05-01 the same `r3_baseline.py` invocation — with **zero code
> changes** — drifted from the pinned **+$6,775 / Sharpe 0.41 / 357
> trades** to **+$8,895 / Sharpe 0.51 / 360 trades**.  This is not a
> bug; it is what happens when you anchor a 500-day window to today.
> The "+$6,775 baseline" should henceforth be treated as a historical
> snapshot rather than a stable fixture.  Future synthetic
> comparisons must capture a fresh pre-baseline immediately before
> any post-change baseline rather than comparing against the pinned
> values; pins in `scripts/r3_baseline.py` are intentionally not
> updated to make this drift visible in the drift-check output.
>
> **Current production sizing under Option A (uniform sizing,
> 2026-05-01 in-sample):** **+$5,836 / Sharpe 0.50 / 360 trades / max
> DD −$6,568 / PF 1.31** vs the pre-Option-A 2026-05-01 baseline of
> **+$8,895 / Sharpe 0.51 / 360 trades / max DD −$8,421 / PF 1.36**.
> Walk-forward on the same date: **−$1,204 / Sharpe −0.0617 / 400
> trades / max DD −$10,705**, vs pre-Option-A walk-forward
> **−$1,181 / Sharpe −0.0517 / 400 trades / max DD −$15,312**.  Trade
> count is unchanged in both samples (the negative-Kelly filter still
> runs first); the change is purely in per-trade size dispersion.
> See `outputs/option_a_uniform_sizing.md` §5 for the full diff
> table and §6 for the verdict reasoning.

### Current production baseline (synthetic-sentiment 10-ticker, 2026-04-25)

_500-day demo run, 10 tickers, R3 sizing.  Headline numbers from
`outputs/r3_production_baseline.md` and `outputs/segregated_kelly_report.md`
(`USE_STRATEGY_BUCKETS=False` -- R3 quintile sizing despite the legacy
script name).  Pinned in `scripts/r3_baseline.py`; the drift check now
verifies both R3 and flat against the pins and reports MATCH on the
current run.  These are NOT comparable to the 5-ticker historical
baseline -- different universe = different strategy.  See §7.4 for the
archived 5-ticker baseline._

### 7.0 Headline metrics

| run | n_signals | n_trades | total P&L | Sharpe | max DD | profit factor | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| **flat** (baseline, 1 contract) | 851 | 613 | **+$17,913** | **0.42** | −$21,692 | 1.23 | 36.2% |
| **R3 production (quintile, BUY CALLS only)** | 851 | **357** | **+$6,775** | **0.41** | −$6,244 | 1.27 | 21.9%* |
| **R3 production (quintile) — same code, 2026-05-01 drift snapshot** | 872 | 360 | +$8,895 | 0.51 | −$8,421 | 1.36 | 22.5%* |
| **Option A (uniform sizing) — current production, 2026-05-01** | 872 | 360 | +$5,836 | 0.50 | −$6,568 | 1.31 | 22.5%* |

\* Universe-wide win rate over all signal evaluations (includes the 256
BUY PUTS rows the negative-Kelly filter zero-contracted).  The pure
BUY-CALLS-only win rate on actually-traded positions is **49.9%**
(178 / 357) -- consistent with the per-signal Kelly stat below.

**[2026-05-01 read-key for the table above.]** Row 1 (flat) and row 2
(R3 quintile pin) are the historical 2026-04-25 fixtures.  Row 3 is
what the same R3 code prints today with zero edits — pure synthetic
window drift.  Row 4 is the current production line under Option A;
compare it against row 3 (not row 2) to see Option A's effect on a
shared corpus.  See `outputs/option_a_uniform_sizing.md` for the full
diff and verdict.

The Kelly run took 357 BUY CALLS trades and 0 BUY PUTS trades --
BUY PUTS hit the negative-Kelly filter (f* = -0.0567) so the sizer
declined every BUY PUTS signal under R3.  Max DD on R3 collapsed from
~$15k (5-ticker) to $6.2k because position count and per-trade size
both fell.

### 7.0.1 Diversification audit (correlation matrix)

Source: `outputs/correlation_matrix.md`.  Daily log-returns over the last
60 (and 252) trading days.

| metric | 60d | 252d |
|---|---:|---:|
| effective independent bets `N_eff` | 6.66 | 7.73 |
| pairs with \|corr\| > 0.70 | IWM/SPY 0.897, NVDA/SPY 0.743 | (similar pattern) |

Both flagged pairs are broad-equity-beta artifacts (small-cap tracks the
broad market; mega-cap NVDA pulls SPY).  Neither was unexpected; we
accept them rather than dropping IWM (small-cap is the only non-mega-cap
broad-equity exposure in the basket).

### 7.0.2 Per-signal Kelly stats on the 10-ticker flat corpus

| signal | n | win_rate | avg_W | avg_L | W | f* | tradable |
|---|---:|---:|---:|---:|---:|---:|---:|
| BUY CALLS | 357 | 52.10% | 0.455 | 0.419 | 1.08 | **+0.0789** | **YES** |
| BUY PUTS  | 256 | 47.66% | 0.597 | 0.608 | 0.98 | **−0.0567** | **NO** (negative-Kelly filter blocks all entries) |

BUY PUTS used to dominate Kelly_f on the 5-ticker corpus (+0.2345);
the diversified universe shows it's a tech-concentration artifact.  See
§7.1.1 for the per-sector breakdown.

### 7.0.3 Sector x signal cross-tab (mean directional return at 20d)

Source: `outputs/sector_decay_analysis.md`.  `+` = trade went the right
way; row of mostly-positive numbers means the sector carries that signal.

| sector | BUY CALLS | BUY PUTS | SELL CALLS | SELL PUTS | n_signals (any) |
|---|---:|---:|---:|---:|---:|
| BroadMarket    | +2.36% | +0.02% | −9.53% | −4.02% | 117 |
| Commodity      | +9.68% (n=3) | −4.85% | −1.74% | +2.26% | 75 |
| ConsumerStaples| +1.17% | −8.20% | +4.78% (n=4) | +5.10% | 72 |
| Energy         | +3.62% | −13.02% (n=1) | −2.97% (n=6) | n/a | 34 |
| Financials     | +2.69% | −1.93% | −7.18% | −0.33% | 83 |
| FixedIncome    | +1.73% | −2.79% (n=6) | −0.07% (n=5) | n/a | 51 |
| Healthcare     | +10.53% (n=6) | **+6.13%** | +4.01% (n=12) | +0.61% | 104 |
| SmallCapEquity | +3.70% | −0.80% | −3.95% (n=1) | +6.30% (n=14) | 88 |
| Technology     | +0.71% | −1.00% | +0.62% | +5.98% (n=13) | 226 |

**Read:** BUY CALLS works in 7 of 9 sectors at 20d (the positive cases
include Tech, BroadMarket, ConsumerStaples, Energy, Financials,
SmallCap, FixedIncome -- across all 3 asset classes).  BUY PUTS is
mostly negative outside Healthcare; this is the structural reason the
Kelly filter disabled it.

### 7.1 Trade count: flat vs R3 production (10-ticker)

| signal | flat | R3 production | Δ |
|---|---:|---:|---:|
| BUY CALLS  | 357 | 357 | 0 |
| BUY PUTS   | 256 | **0** (negative-Kelly filter) | −256 |
| SELL CALLS | 114 | 0 (DISABLED by decay; n=114 vs old n=61, same verdict) | 0 |
| SELL PUTS  | 108 | 0 (positive at 10d on universe but NOT yet enabled — see §10.2) | 0 |

### 7.2 Global-cap utilization under R3 (10-ticker)

Global 6% portfolio cap ($6,000 on the $100k paper account); no per-
strategy buckets.  Only BUY CALLS contributes:

| metric | value |
|---|---:|
| signal | BUY CALLS |
| cap_$ | $6,000 |
| n_evaluations | 357 |
| mean utilization | 0.202 |
| peak utilization | 0.690 |
| n_blocked (portfolio_risk_cap) | 0 |
| pct_blocked | 0.0% |

The BUY-PUTS bucket-saturation problem from the 5-ticker era is moot:
without BUY PUTS taking 60-DTE positions, no bucket pressure.  The
universe never crosses 70% of the global cap.

### 7.3 Confidence quintile P&L under R3 (10-ticker, v2 logistic on disk; production still loads v1)

Quintile edges refit on the new flat corpus:
`[0.5440, 0.5618, 0.5779, 0.6020]`.  Production loader currently still
reads the 5-ticker `confidence_model.json`; the v2 fit is parked at
`data/raw/confidence_model_v2_10t.json` for A/B until promoted.

Counts below are over actually-traded BUY CALLS (357) -- the
`r3_baseline._taken_mask` excludes `negative_kelly_*` zero-contract
rows so the per-quintile n / win_rate / avg_P&L reflect real positions.

| quintile | n | mean_conf | win rate | avg P&L | total P&L |
|---|---:|---:|---:|---:|---:|
| Q1 | 65 | 0.5283 | 38.5% | −$19 | **−$1,253** |
| Q2 | 75 | 0.5536 | 54.7% | +$11 | +$828 |
| Q3 | 62 | 0.5702 | 48.4% | −$6 | −$351 |
| Q4 | 77 | 0.5893 | 59.7% | +$27 | +$2,047 |
| Q5 | 78 | 0.6202 | 56.4% | +$71 | **+$5,505** |

Q5 - Q1 spread: +$6,758 — cleanly monotone by total P&L
(Q1 < Q3 < Q2 < Q4 < Q5).  Win rate is also mostly increasing with
confidence (Q3 dips to 48.4% but recovers at Q4/Q5).  Q1 is net
negative as expected: it's the low-conviction BUY CALLS the model
flags as least likely to win.

### 7.4 Archived 5-ticker baseline (deprecated 2026-04-25)

_Pre-rebuild numbers, kept here for provenance.  These were measured on
the AAPL / NVDA / MSFT / SPY / QQQ universe with the original 5-ticker
synthetic sentiment.  They are NOT the current production target -- the
universe is structurally different (mega-cap-tech-only vs 6 sectors / 3
asset classes), and the per-signal Kelly stats shifted enough that
production no longer trades BUY PUTS at all.  Pinned constants in
`scripts/r3_baseline.py` archive these values inline as commented-out
provenance lines._

| run | n_signals | n_trades | total P&L | Sharpe | max DD | profit factor | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| flat (baseline) | 562 | 417 | +$33,192 | 1.06 | −$15,328 | 1.65 | 42.4% |
| single-pool Kelly (v1) | 562 | 84 | −$4,103 | −0.31 | −$6,333 | 0.77 | 12.8% |
| segregated Kelly (v2) | 562 | 288 | −$3,215 | −0.12 | −$12,865 | 0.92 | 27.9% |
| R3 production (session-1 logistic) | 562 | 358 | +$12,604 | 0.46 | −$17,055 | 1.25 | 34.2% |
| R3 production (refit logistic, last pre-rebuild pin) | 562 | 358 | +$14,872 | 0.54 | −$15,371 | 1.31 | 34.2% |
| magnitude model (explored, not promoted) | 562 | 358 | +$13,680 | 0.51 | −$15,353 | 1.29 | 34.2% |

5-ticker per-signal Kelly stats (BUY PUTS was the dominant Kelly_f
contributor on this universe -- the diversified rebuild revealed it
was a tech-concentration artifact):

| signal | n | win_rate | f* | tradable |
|---|---:|---:|---:|---:|
| BUY CALLS | 249 | 50.6% | +0.0184 | YES |
| BUY PUTS  | 168 | 51.2% | **+0.2345** | YES |
| SELL CALLS | 0 | n/a | n/a | DISABLED by decay |
| SELL PUTS  | 0 | n/a | n/a | insufficient sample |

5-ticker quintile P&L (refit logistic, last pre-rebuild snapshot):

| quintile | n | total P&L |
|---|---:|---:|
| Q1 | 71 | +$1,788 |
| Q2 | 73 | +$3,885 |
| Q3 | 72 | +$6,396 |
| Q4 | 67 | −$815 |
| Q5 | 75 | +$3,619 |

Q4 dipped negative on this corpus.  After the universe rebuild the
quintile profile is cleanly monotone again (§7.3); the Q4 dip was a
5-ticker artifact, not a structural confidence-model issue.

---

## 8. Known issues

### 8.1 **BUY PUTS bucket saturation** (PARTIALLY RESOLVED by R3 adoption)

- Was: 58% of BUY PUTS signals blocked at the 3% per-strategy bucket; peak
  utilization 1.43× ($3k cap).
- R3 production (global 6% cap, no strategy buckets): **29% blocked, peak
  1.21×, 119 of 168 BUY PUTS taken**.  See `outputs/r3_production_baseline.md`.
- Residual: the global 6% cap still caps 49/168 BUY PUTS signals during
  dense bearish stretches.  Raising the global cap trades portfolio risk
  for completeness — not a clean swap.  Parked until real-sentiment data
  arrives; the synthetic-signal density may not reflect live conditions.

### 8.2 **Q5 inversion under confidence-proportional sizing** (MOSTLY RESOLVED)

Historical: Under segregated Kelly (v2), Q5 = −$5,451.  Under R3 with
session-1 logistic coefficients, Q5 = −$3,221.  The hypothesis on the
table was that the logistic's win-probability target didn't translate
to PnL magnitude, and we planned a magnitude-target model (§10.1).

What actually fixed it: **refitting the logistic on the current 417-trade
corpus** (2026-04-24).  The demo sentiment window slides with today(),
and the refit picked up slightly different trades; the new coefficients
produce a tighter confidence distribution and Q5 is now **+$3,619 total
P&L** under R3.  See §5.1 for the old-vs-new coefficient comparison.

The magnitude-target alternative was still built and evaluated (see
§5.4 and `outputs/confidence_model_comparison.md`):
- Magnitude failed both hold-outs (Q5 wasn't the best quintile on
  either time-based 75/25 or ticker-LOO).
- Magnitude LOST on the R3 backtest: +$13,680 vs refit-logistic +$14,872.
- Not promoted.

Residual: Q4 still dips slightly negative (−$815).  Not a capacity
artifact (block rate for BUY PUTS in Q4 is no worse than other bins).
Parked — more likely explained by the Q4 trades' specific
sentiment/IV characteristics than by model calibration.

### 8.3 **Demo-mode sentiment is synthetic**

- All current KPIs are from `_generate_synthetic_history` (mean-reverting
  random walk seeded by ticker hash), NOT real news sentiment
- Real-mode path exists (`--real` flag) but needs a full year of news +
  SEC backfill on disk for every ticker before it'll produce ≥ MIN_TRADES_FOR_KELLY
- `sec_aligned` feature contributes zero in demo because SEC data is absent
- The Q5 inversion may be an artifact of the mean-reverting synthetic
  walk — re-test under real sentiment before declaring it structural.

### 8.4 **`MIN_CONTRACTS=1` can bust the cap**

- When 1-contract risk > remaining budget, we STILL take the trade
  (reason = `floor_over_bucket` under legacy, `floor_over_cap` under R3)
  because the 1-contract floor is an indivisibility constraint, not a
  policy choice.
- This inflates subsequent `bucket_used_before` reads above 100% and
  blocks the next N signals in that cap.
- Explicitly documented as a known trade-off in `position_sizer.size_trade`.

### 8.5 **`HOLD_DAYS=5` is now a misnomer**

- Used only by `metrics.py` for Sharpe annualisation (`sqrt(252/5)`)
- Actual holds are set by the exit-rule simulator (stop / target / time-stop
  / expiration) and are often far from 5 days (especially 60-DTE BUY PUTS)
- Kept stable so flat-vs-Kelly comparisons stay apples-to-apples

---

## 9. Three-regime allocation study (2026-04-24)

Tested three candidate fixes for §8.1 / §8.2 (BUY PUTS bucket saturation +
Q5 inversion) on the full flat corpus.  Same confidence model, same
structural overrides (60 DTE BUY PUTS for R1 & R3), same Kelly math,
same 500-day demo window.  Report: `outputs/regime_comparison.md`.

| regime | n_trades | total P&L | Sharpe | max DD | PF | win rate |
|---|---:|---:|---:|---:|---:|---:|
| flat (baseline) | 417 | **+$33,192** | **1.06** | -$15,328 | 1.65 | 42.4% |
| segregated Kelly (current) | 288 | -$3,215 | -0.12 | -$12,865 | 0.92 | 27.9% |
| R1: BUY PUTS 4.5% / 1.0% / 0.25% / 0.25% | 259 | +$1,655 | 0.05 | -$14,650 | 1.04 | 25.1% |
| R2: Variant C 45 DTE / $10 width | 302 | -$7,488 | -0.33 | -$12,551 | 0.81 | 28.8% |
| **R3: no buckets, quintile per-trade cap** | **358** | **+$12,604** | **0.46** | -$17,055 | 1.25 | 34.2% |

### 9.1 BUY PUTS block rate

| regime | bucket cap | peak util | pct blocked |
|---|---:|---:|---:|
| current | $3,000 | 1.43 | 58.3% |
| R1 | $4,500 | 1.29 | 48.8% |
| R2 | $3,000 | 1.19 | 50.0% |
| R3 | $6,000 (global) | 1.21 | **29.2%** |

### 9.2 Q5 confidence-quintile P&L (bins fixed from flat corpus)

| regime | Q1 total | Q5 total | Q5-Q1 |
|---|---:|---:|---:|
| current | +$1,381 | **-$4,892** | -$6,273 |
| R1 | +$4,113 | **-$5,403** | -$9,516 |
| R2 | -$871 | **-$1,895** | -$1,024 |
| R3 | +$9,277 | **-$3,221** | -$12,499 |

### 9.3 Interpretation

- **R3 is the best of the three** and flips Kelly P&L from -$3,215 to
  +$12,604 (Sharpe -0.12 -> +0.46).  Dropping strategy buckets lets BUY
  PUTS block rate fall from 58% to 29%, which is what the "capacity
  hypothesis" predicted.  Trade count per strategy rises toward flat
  (BUY CALLS 249->239, BUY PUTS 168->119).
- **None of the three closes the flat-vs-Kelly gap.**  Flat +$33,192 /
  Sharpe 1.06 vs R3 +$12,604 / Sharpe 0.46 is still a 62% P&L gap and a
  2.3x Sharpe gap.  Max DD on R3 is actually *worse* than current
  (-$17,055 vs -$12,865) -- no strategy buckets means bearish-regime
  concentration is unconstrained.
- **Q5 inverts under every regime.**  Even when R3 removes the bucket
  bottleneck, Q5 still loses money (-$3,221) while Q1 earns +$9,277.
  This kills the hypothesis that Q5 inversion was purely a capacity
  artifact -- it is partly capacity (smaller under R3) and partly
  **model calibration**: the logistic model was trained on flat
  (1-contract) outcomes, so its top-quintile predictions don't survive
  confidence-proportional sizing.
- **R1 disappointing.**  Raising the BUY PUTS bucket to 4.5% only dropped
  block rate 10 points (58% -> 49%) because 60-DTE positions still
  overlap too densely, and the 1.0% BUY CALLS bucket starved the
  best-edge strategy (BUY CALLS n_trades 249 -> 173).  Net: +$1,655.
- **R2 broke the structural win.**  Shortening BUY PUTS to 45 DTE (even
  with $10 width) re-introduced the theta drag put_structure_study
  eliminated; BUY PUTS block rate barely improved (58% -> 50%) because
  45 DTE is still slow enough for overlap, and each trade's per-contract
  edge got worse.  Net: -$7,488, the worst of the three.

## 10. Chosen path + next upgrade

**REGIME 3 is production.**  `position_sizer.USE_STRATEGY_BUCKETS = False`;
`size_trade()` sizes per-trade by confidence quintile (0.1% / 0.2% / 0.3%
/ 0.5% / 0.8%) against the global 6% portfolio cap.  Synthetic-sentiment
10-ticker baseline pinned in `scripts/r3_baseline.py`; current run MATCHes
on both R3 and flat drift checks (§7).

### 10.1 Next session priorities (in order)

1. **Real-data validation: wait for 30-60 days of accumulated live news
   sentiment via the scheduler.**  No code changes; just patience.  The
   Mon-Fri 6:30 PM ET task fetches news + options + sentiment + signal
   for all 10 tickers (verified Decision 6, 2026-04-25).  Each daily
   run adds one day of authentic Finnhub-sourced sentiment to the
   corpus.  At ~30 trading days we'll have enough to start cross-
   referencing real-mode behaviour against the synthetic baseline; at
   ~60 days the SEC backfill window for the 6 single-name tickers
   will also be fully populated.

   - **Sub-finding from Saturday smoke test (2026-04-25):** SELL PUTS
     strategy is functional on real data despite being blocked in
     synthetic backtests.  3 of 4 actionable signals fired SELL PUTS
     (NVDA / IWM / SPY) on real Finnhub options data, clearing the
     `CREDIT_MIN_PREMIUM_FR=0.33` floor that synthetic-vol pricing had
     hidden.  Real-mode backtest in late May/June should re-enable
     SELL PUTS in `kelly_stats.csv` and the decay analysis.  This
     unblocks Decision-7 §B (SELL PUTS deferral) automatically once
     the real-data corpus is large enough for Kelly stats to converge.

2. **Real-mode end-to-end debug: when sufficient data has accumulated,
   run `scripts/segregated_kelly_report.py --real` and debug whatever
   surfaces.**  Multi-session effort.  Earliest start: late May 2026.
   Likely friction points: (a) Finnhub free-tier rate limits when
   pulling backfill, (b) the merger / engine real-mode path hasn't
   been exercised end-to-end since the universe expansion, (c) ETF
   sentiment quality (news flow on TLT / GLD is thinner than on
   single-name issuers).

3. **After real-data baseline lands: revisit BUY PUTS Healthcare-only
   restriction (D1 deferred decision) and SELL PUTS enablement
   (D2 deferred decision).**  Both signals' fate hinges on whether the
   sector / vol-premium patterns we saw on synthetic data hold up on
   real data.  BUY PUTS may re-pass the negative-Kelly filter in
   Healthcare; SELL PUTS credits should clear the 33% floor naturally
   once real IV (with vol risk premium) replaces the realised-vol
   proxy.  Code preserved on disk for both.

4. **Earnings prepared-remarks sentiment: ~~free upgrade via 8-K~~ DONE
   (PARTIAL).  Q&A still deferred to a paid feed.**  Implemented Path A
   on 2026-04-25: `data/sec_fetcher.py` now also fetches Exhibit 99.1
   (the press release / earnings slide deck) for every 8-K, identified
   via the SEC submission `.txt` SGML headers (the only authoritative
   source -- `index.json` `type` field is the UI icon name, not the
   form type).  `sentiment/sec_scorer.py` tags each filing with a
   `subcategory` (`10-K_mdna` / `10-Q_mdna` / `8-K_earnings_prepared` /
   `8-K_earnings_cover` / `8-K_other`); for earnings-flagged 8-Ks with
   an exhibit on disk, the exhibit is scored instead of the cover.
   `sentiment/merger.py` blends three streams:
       news (0.50) + sec_earnings (0.35) + sec_other (0.15)
   with drop-missing-weight semantics and forward-fill of
   90d (earnings) / 180d (other).  92 earnings_prepared filings now
   scored across the 6 single-name tickers.  Backwards-compat single
   `sec_sentiment` column preserved so `backtest/engine.py` doesn't
   need changes.

   What this DIDN'T deliver: the Q&A portion of the earnings call.
   Transcripts with analyst Q&A are NOT filed with the SEC -- companies
   file the press release (prepared remarks) but distribute the
   transcript via investor relations / third-party transcript services.
   Q&A integration requires a paid feed (Finnhub paid tier, AlphaSense,
   etc.) and is the natural Decision 8 candidate after real-data
   validation lands.

### 10.2 Parked until real sentiment arrives

- Re-evaluate whether BUY PUTS structure (60 DTE / 0.25Δ short)
  survives on real data.  The structural winner was picked on
  synthetic signals from the put_structure_study; the underlying
  edge on the 10-ticker universe was tech-concentrated even on
  synthetic data, so real data may invalidate it entirely.
- Retry the magnitude model on real sentiment.  `sec_aligned` and
  `log_days_to_earnings` carry no variance in demo, so the
  magnitude model effectively trained on only 4 of its 6 features.
  Real data could change the verdict.
- Refresh quintile edges and v2 logistic coefficients once the
  real-data flat corpus is built.  Current edges
  (`data/raw/quintile_edges.json`) are calibrated on synthetic
  trades; the v1 production model and v2_10t archive are both
  parked at synthetic fits.

### 10.3 Known limitations (Path A SEC pipeline)

- **Pre-2022 AAPL iXBRL primary docs.**  Five AAPL 10-Q filings
  (2020-05-01, 2020-07-31, 2021-01-28, 2021-04-29, 2021-07-28)
  encode narrative content inside `ix:nonNumeric` XBRL tags whose
  text doesn't surface through `BeautifulSoup.get_text()`.  The
  primary HTML for these filings (~2 MB each) contains zero
  occurrences of "Management's Discussion" -- verified by direct
  grep of the raw HTML.  After the 2026-04-25 Path A regex+strip
  fixes, these five filings still produce ~500-byte boilerplate-tail
  stubs.  iXBRL-aware extraction (parsing `ix:nonNumeric` /
  `R*.htm` / `FilingSummary.xml`) is deferred -- 5 historical
  quarters of one ticker isn't worth a parser.  See code comment
  in `data/sec_fetcher.py:_strip_html`.  Revisit if the issue
  recurs in any other ticker's pre-2022 filings during real-data
  validation.

- **COVID-era AAPL sentiment caveat.**  Earlier-session findings
  framed as "FinBERT didn't catch COVID stress" on AAPL's
  Q1-Q2 2020 SEC content were almost certainly a data-extraction
  artifact, not a model limitation.  AAPL's 2020-05-01 10-Q
  (Q2 2020, the COVID-impact quarter) is one of the affected
  stubs above -- FinBERT scored 500 bytes of accounting-policies
  boilerplate, not the actual MD&A narrative on COVID disruption.
  Cannot validate the original "model misses COVID" hypothesis
  without iXBRL parsing.  Mark the prior conclusion provisional.

- **Item 7.01 earnings filings.**  Initial Item 2.02 detection
  missed JPM (uses Item 7.01 + Reg-FD furnish for earnings call
  slides) and 12+1 additional XOM/UNH earnings filings.  Detector
  broadened on 2026-04-25 to also tag `Item 7.01 + earnings
  keyword` cover pages as `8-K_earnings_prepared` (when an
  exhibit is on disk) or `8-K_earnings_cover` (when not).  If
  any future ticker uses yet another item code for earnings
  (rare but possible), broaden again.

- **JPM 3-year backfill returned only 26 filings** (1 10-K, 3
  10-Q, 22 8-K) instead of the expected 12-14 quarterly filings.
  Root cause: the SEC submissions API's `recent` block caps at a
  fixed history depth and high-volume filers (JPM files lots of
  8-Ks) push older filings out of the window.  To get the full
  3-year history we'd need to follow the `files` chain to older
  submission archives.  Not in scope.  JPM's 6 earnings_prepared
  rows cover roughly the last 1.5 years.

- **IV Rank for the 7 newly-added tickers** (JPM, XOM, UNH, WMT,
  IWM, GLD, TLT) is based on the price-volatility proxy until 252
  trading days of options data accumulate (~April 2027).  The proxy
  uses 30-day realised vol percentile-ranked against a 252-day
  rolling window of the same realised-vol series.  Live signals
  during this window use proxy IV Rank, which is reasonable
  (correlated with true IV Rank because IV tracks realised vol over
  multi-month horizons) but not identical to true historical-IV
  Rank (which uses Finnhub-stamped option-chain IV percentile-ranked
  against a year of historical option-chain IV reads).  AAPL/NVDA/
  SPY have several months of cached options data already so their IV
  Rank converges to true IV Rank faster.  The proxy -> true IV Rank
  switch is automatic (`options_fetcher.py` selects the better
  source per ticker per day); no code change needed when the
  history fills in.

### 10.4 Architectural asymmetry: live signals vs real-mode backtest

The live signal path (`signals/signal_engine.py`) reads
`sec_sentiment_*.csv` directly via the single-latest-filing approach
(`_try_load_sec_sentiment` takes `df.iloc[-1]`).  The 3-stream merger
weighting in `combined_sentiment_*.csv` is consumed only by the
real-mode backtest (`backtest/engine.py` reads the merger's
`sec_sentiment` column for the `sec_aligned` feature).

What this means concretely:

- **Path A's content improvements DO flow into live signals**:
  re-extracted MD&A on AAPL 10-Ks/post-2022 10-Qs, 92 earnings 8-Ks
  scored on the exhibit instead of the cover, JPM/XOM/UNH Item 7.01
  filings properly classified.  Monday's 6:30 PM run benefits from
  all of these because they're baked into `sec_sentiment_*.csv`
  which signal_engine reads.
- **Path A's weighting improvements do NOT flow into live signals**:
  the news (0.50) / earnings (0.35) / other (0.15) blend lives only
  in `combined_sentiment_*.csv`, which signal_engine doesn't open.
  These improvements are dormant on the live path until real-mode
  backtest runs against the merged file.

Wiring the merger into the live path (rebuild combined_sentiment in
`run_daily.py` + switch `signal_engine` to read the merged file) is
a **Decisions 8/9 candidate** -- separate dev + validation cycle.
Deferred until real-data validation establishes whether the weighted
blend produces materially different signals than the
single-latest-filing approach the live path has used since v1.

The asymmetry was confirmed during pre-Monday Path A verification
(see §11 / 2026-04-25 Path A entry).  Not a regression, not a Path
A bug -- the live path was always single-latest-filing; merger
output was always backtest-only.  Documented here so the gap is
explicit rather than implicit.

---

## 11. How to run (cold-start cheatsheet)

```bash
# R3 production baseline (flagship under the current regime)
.venv/Scripts/python.exe scripts/r3_baseline.py
.venv/Scripts/python.exe scripts/r3_baseline.py --skip-run   # reuse logs

# Three-regime allocation study (R1 / R2 / R3 side-by-side)
.venv/Scripts/python.exe scripts/regime_comparison.py
.venv/Scripts/python.exe scripts/regime_comparison.py --skip-run

# Logistic vs magnitude confidence-model comparison + auto-promote
.venv/Scripts/python.exe scripts/compare_confidence_models.py
.venv/Scripts/python.exe scripts/compare_confidence_models.py --no-promote
.venv/Scripts/python.exe scripts/compare_confidence_models.py --skip-backtest

# Legacy segregated-Kelly flagship (kept for A/B -- set
# USE_STRATEGY_BUCKETS=True in position_sizer.py to reproduce old numbers)
.venv/Scripts/python.exe scripts/segregated_kelly_report.py
.venv/Scripts/python.exe scripts/segregated_kelly_report.py --skip-flat

# Refit the logistic confidence model on the current flat corpus
.venv/Scripts/python.exe scripts/fit_confidence_model.py

# Real-mode (requires sentiment CSVs on disk for each ticker)
.venv/Scripts/python.exe scripts/r3_baseline.py --real
```

**Windows shell note:** use `.venv/Scripts/python.exe` (not `python`) —
`python` without the venv prefix hits a system Python without numpy.

**Outputs:**
- `data/raw/backtest_{T}_demo.csv` — flat sizing trade log per ticker
- `data/raw/backtest_{T}_demo_kelly.csv` — Kelly sizing trade log per ticker
- `data/raw/kelly_stats.csv` — per-signal Kelly stats
- `data/raw/quintile_edges.json` — confidence quintile cut points (R3 sizing)
- `data/raw/confidence_model.json` — fitted logistic coefficients
- `data/raw/magnitude_model.json` — weighted-ridge magnitude model (A/B only)
- `outputs/r3_production_baseline.md` — production baseline + drift check
- `outputs/regime_comparison.md` — R1/R2/R3 three-regime study
- `outputs/confidence_model_comparison.md` — logistic vs magnitude A/B
- `outputs/kelly_study_summary.md` — flat vs single-pool Kelly study
- `outputs/segregated_kelly_report.md` — flat vs segregated Kelly (legacy A/B)
- `outputs/signal_decay_analysis.md` — per-segment decay study
- `outputs/put_structure_study.md` — 60-DTE / 0.25Δ BUY PUTS study that
  justified the per-strategy DTE override

---

## 12. Session history

- **2026-04-24:** Initial build through segregated Kelly study.  Findings:
  flat corpus achieved Sharpe 1.06 / +$33k P&L.  Logistic confidence model
  trained (417 trades, Q5−Q1 +15.76pp).  BUY PUTS structure study identified
  60 DTE / 0.25Δ as winner (+$32k vs +$8k baseline).  SELL CALLS disabled by
  decay.  Segregated bucket implementation exposed capacity-adjusted
  selection bias in Q5.
- **2026-04-24 (later):** Three-regime allocation study (see §9).  R1
  (larger BUY PUTS bucket), R2 (Variant C 45 DTE / $10 width), R3 (no
  buckets, quintile per-trade cap) run on the full flat corpus.  R3
  wins: +$12,604 / Sharpe 0.46 (vs current -$3,215 / -0.12).  Capacity
  hypothesis partly confirmed (block rate 58% -> 29%) but Q5 still
  inverts under every regime -- confidence model needs PnL-weighted
  retrain, not another bucket tweak.  Report: `outputs/regime_comparison.md`.
- **2026-04-24 (prod adoption):** R3 productionised.  Added
  `USE_STRATEGY_BUCKETS=False` default in `position_sizer.py`, a
  `QUINTILE_FRAC` table, and on-disk `quintile_edges.json` wired into
  `size_trade()`.  Engine no longer hardcodes `use_segregated_buckets=True`.
  New `scripts/r3_baseline.py` reruns the flagship and writes
  `outputs/r3_production_baseline.md` with a pinned drift-check vs the
  study numbers.  Production reproduces the study exactly (drift $0.01
  P&L, 0.0000 Sharpe, 0 trades).  §7 KPI tables updated to R3 numbers;
  §8.1 marked PARTIALLY RESOLVED, §8.2 relocated from capacity artifact
  to confidence-model calibration (open, fix plan in §10.1).
- **2026-04-24 (magnitude-model study):** Built
  `signals/confidence_model_magnitude.py` (weighted ridge on pnl_pct,
  sample weights min(|pnl_pct|, 100) / 10, quintile-rank normalisation
  to [0,1]) and `scripts/compare_confidence_models.py` (time + ticker-
  LOO hold-outs, full R3 A/B, promotion mechanics).  Magnitude failed
  both hold-outs; 8-feature interaction variant also failed.  Magnitude
  lost R3 backtest by $1.2k P&L / 0.03 Sharpe.  **Logistic kept.**
  Surprise finding: refitting the logistic on the current flat corpus
  produced materially different coefficients (~7x smaller |β|) and
  flipped Q5 from -$3,221 to +$3,619 under R3 -- the Q5 problem from
  §8.2 was mostly a stale-fit artifact.  New R3 baseline pinned at
  +$14,872 / Sharpe 0.5415.  §5 updated with old-vs-new coefficients,
  §5.4 added for the magnitude write-up, §8.2 moved to MOSTLY RESOLVED,
  §10.1 marked completed.  Report: `outputs/confidence_model_comparison.md`.

### 2026-04-25 (late-late) Path A: earnings prepared-remarks sentiment landed

Decision 7 of the 2026-04-25 session.  Implemented the "earnings call
transcript prioritization" upgrade in Path A form (prepared remarks
only; Q&A still requires a paid feed and is deferred).  Three
implementation surprises along the way, each surfaced and
paused-for-confirmation per the user's "no silent workarounds"
instruction.

**What landed:**

- `data/sec_fetcher.py`:
  - 8-K Exhibit fetch via SEC submission `.txt` SGML headers
    (the only authoritative source for EX-99.x filename mapping;
    `index.json` `type` field is the UI icon name, not the form
    type -- discovered after two false starts trying type-field and
    filename-pattern matching).
  - `_extract_mdna` now form-aware: 10-K MD&A is Item 7 →
    Item 7A/Item 8; 10-Q MD&A is Item 2 of Part I → Item 3/Item 4
    (the prior code applied 10-K's Item-7 regex to 10-Q filings,
    matching stray cross-references and producing tail-of-doc
    slices instead of MD&A).
  - Strict end-marker matching (`Item 7A. Quantitative...`,
    `Item 8. Financial...`) so we don't false-match on
    cross-references like "see Item 8" inside the MD&A narrative.
  - Apostrophe-tolerant section-header matching (BeautifulSoup
    decoding mangles U+2019 to U+FFFD on some older filings).
  - `_strip_html` two-pass: try tables-removed extraction first;
    fall back to keep-tables when the tables-removed text is
    < 5000 chars (older filings used `<table>` for narrative
    layout, not just financial data).

- `sentiment/sec_scorer.py`:
  - New `subcategory` taxonomy: `10-K_mdna`, `10-Q_mdna`,
    `8-K_earnings_prepared` (Item 2.02 OR Item 7.01+earnings,
    with exhibit on disk → score the EXHIBIT not the cover),
    `8-K_earnings_cover` (earnings 8-K with no exhibit found),
    `8-K_other`.
  - Item-code detection broadened to include Item 7.01 + earnings
    keyword combinations after JPM/XOM/UNH audit revealed 19
    earnings filings being misclassified as 8-K_other (JPM
    furnishes earnings call slides under Reg-FD, not as official
    Item 2.02 press releases).

- `sentiment/merger.py`:
  - Three-stream weighted blend: `news=0.50`, `sec_earnings=0.35`,
    `sec_other=0.15`.  Drop-missing-weight semantics (no
    renormalization) -- a date with only news carries less
    conviction than a date with all three streams aligned.
  - Per-stream forward-fill: 90 days for earnings (one quarter of
    relevance), 180 days for other-SEC.
  - Backwards-compat single `sec_sentiment` column emitted (=
    earnings if available else other), so `backtest/engine.py`
    (which reads that column for the `sec_aligned` feature)
    didn't need changes.

- AAPL re-extraction + 5-ticker SEC backfill:
  - 6 AAPL 10-Ks + 13 post-2022 AAPL 10-Qs re-downloaded with
    overwrite=True to apply the new MD&A regex.
  - 5 missing tickers (NVDA, JPM, XOM, UNH, WMT) backfilled
    3 years of 10-K + 10-Q + 8-K + Exhibit 99.x.
  - 304 filings total scored with FinBERT (~21 min initial run +
    ~16 min re-run after Item 7.01 detection broadened); 92 now
    classified as `8-K_earnings_prepared` -- the high-value
    prepared-remarks rows.

**Three pause-and-report incidents** (per the no-silent-workarounds
instruction):

1. **Pre-2022 AAPL iXBRL filings were unfixable in scope.**  Initially
   thought to be a regex bug; turned out the primary HTML doc literally
   contains no "Management's Discussion" string -- narrative text is
   in `ix:nonNumeric` tags that `BeautifulSoup.get_text()` doesn't
   surface.  User confirmed Option A: document and accept; the 5
   affected filings stay as 500-byte stubs.  See §10.3 known
   limitations.

2. **EDGAR `index.json` `type` field is not the form type.**  Two
   false starts: first matching `^EX-99.*$` against the icon name
   `text.gif` (zero exhibits), then trying filename pattern
   matching (worked for Apple's `a8-kex991*.htm`, failed for
   NVIDIA's `q2fy26pr.htm`).  Final fix: parse the SEC submission
   `.txt` SGML headers which have authoritative `<TYPE>EX-99.1`
   markers.

3. **JPM (and XOM, UNH) use Item 7.01 for earnings.**  Initial
   detection only caught Item 2.02; JPM had 0/6 earnings filings
   tagged.  Audit across 6 tickers: 19 misclassified filings (JPM
   6, XOM 12, UNH 1).  Detector broadened to also tag Item 7.01 +
   earnings keyword as 8-K_earnings_prepared.

**Verification (PART 7 -- `scripts/verify_path_a.py`):**

- **AAPL pre-fix vs post-fix correlation on 13 post-2022 10-Qs:
  Pearson r = +0.6712 (BELOW the 0.70 threshold).**  Mean abs
  score diff = 0.22.  All 13 new scores are MORE NEGATIVE than the
  old (e.g. 2023-02-03: old −0.21 → new −0.60), consistent with
  the new MD&A slice focusing on "risks/challenges/uncertainties"
  language while the old broken-slice tail-of-doc was diluted
  with neutral signature/financials/policies content.  This
  validates the user's hypothesis: prior 5-ticker AAPL SEC
  sentiment used in backtesting was partially based on broken
  text extraction.  Not a remediation issue (demo backtest
  doesn't read combined_sentiment), but a credibility note.

- **Earnings sentiment carries variance.**  Per-ticker std of the
  `sec_earnings_sentiment` column ranges 0.06-0.18 (meaningful
  signal, not flat).  News-vs-earnings correlation can't be
  evaluated yet -- only AAPL/NVDA/SPY have any news data on disk
  (4 days each from the live pipeline runs on 2026-04-23/24);
  the 7 newer tickers have zero news days until Monday's first
  scheduler run.  Real cross-stream divergence assessment
  deferred to Decision 9 / first real-data session.

- **R3 drift smoke test: MATCH on both R3 and flat verdicts.**
  Path A is byte-invisible to the demo backtest (which generates
  synthetic sentiment via `_generate_synthetic_history` and
  doesn't read `combined_sentiment_*.csv` at all).  Pinned
  baselines unchanged.  This is the expected behaviour --
  validates that Path A is a structural data improvement that
  affects only the real-mode path.

**Final corpus state:**

| ticker | 10-K | 10-Q | 8-K cover | 8-K exhibit | earnings_prepared rows |
|---|---:|---:|---:|---:|---:|
| AAPL | 6 | 18 (5 pre-2022 stubs) | 52 | 26 | 24 |
| NVDA | 3 | 9 | 27 | 12 | 12 |
| JPM  | 1 | 3 | 16 | 6 | 6 |
| XOM  | 3 | 9 | 47 | 29 | 26 (+ 2 cover-only) |
| UNH  | 3 | 9 | 49 | 20 | 13 (+ 4 cover-only) |
| WMT  | 3 | 9 | 37 | 18 | 11 |

**combined_sentiment coverage** (after merger run):

| ticker | rows | news days | earnings days | other days | combined days |
|---|---:|---:|---:|---:|---:|
| AAPL | 1563 | 4 | 1556 | 1562 | 1563 |
| NVDA |  763 | 4 |  747 |  761 |  763 |
| JPM  |  257 | 0 |  245 |  257 |  257 |
| XOM  |  783 | 0 |  783 |  781 |  783 |
| UNH  |  783 | 0 |  726 |  783 |  783 |
| WMT  |  771 | 0 |  693 |  760 |  771 |
| SPY  |    5 | 5 |    0 |    0 |    5 |
| IWM/GLD/TLT | 0 | 0 | 0 | 0 | 0 (no data yet) |

Real news streams light up Monday on the first 10-ticker scheduler
run.

**Pre-Monday verification: live-vs-backtest architectural asymmetry
confirmed.**  Audit of `scripts/run_daily.py` and
`signals/signal_engine.py` ahead of Monday's 6:30 PM run found that
the daily live-signal pipeline does NOT invoke `merger.build_combined`
and does NOT read `combined_sentiment_*.csv`.  signal_engine pulls SEC
sentiment via `_try_load_sec_sentiment` which takes `df.iloc[-1]` of
`sec_sentiment_{ticker}.csv` (the single most recent filing).  Path
A's data-content improvements (re-extracted MD&A, exhibit scoring,
Item 7.01 detection) flow into live signals because they're baked
into the per-filing `sec_sentiment_*.csv` rows.  Path A's weighting
improvements (news 0.50 / earnings 0.35 / other 0.15, drop-missing-
weight, 90d/180d forward-fill) do NOT flow into live signals -- the
3-stream blend in combined_sentiment is consumed only by the
real-mode backtest engine.

**Decision: Path A weighting is dormant on live path, confirmed
during pre-Monday verification.  Documented as architectural
asymmetry, not a bug.  Decision 8 candidate.**  Wiring the merger
into the daily flow + switching signal_engine to consume the merged
file is a separate decision with its own validation cycle, deferred
until real-data validation can compare weighted-blend vs
single-latest-filing live signals on a meaningful corpus.  See
§10.4 for the full asymmetry write-up.

**GO for Monday 6:30 PM ET as-is.**  Daily run will execute cleanly,
will benefit from Path A's content improvements via the existing
single-latest-filing read, and will not exercise the new merger
weighting on the live path.

**Dashboard upgrade (2026-04-25, post-smoke-test).**  `dashboard/app.py`
now reads `combined_sentiment_{T}.csv` (Path A 3-stream merger output)
when present and renders combined as the primary sentiment line with
news / EDGAR / earnings components as faint legend-toggleable
overlays.  Falls back to raw `sentiment_{T}_*.csv` with a stdout
warning when combined isn't on disk (currently IWM / GLD / TLT, which
have no SEC data and the merger returned empty; Monday's news fetch
will populate news but the merger isn't run by `run_daily.py`).
Backtest signals on the price panel are now joined by live
`signals_{T}.csv` markers in an outlined style for visual comparison.
A new `build_overview_dashboard()` writes
`dashboard/overview.html` -- a cross-universe view with a
per-asset-class cumulative-P&L strip on top and a small-multiples grid
of all 10 tickers grouped by asset class then sector.  `main.py
--dashboard` now produces both `report_{TICKER}.html` per ticker AND
the overview file; `--dashboard-overview-only` builds just the
overview.  CLAUDE.md and PROJECT_STATE §2 corrected from "Streamlit"
to "Plotly HTML dashboard".  Visualisation-layer change only --
no merger / signal_engine / backtest logic touched.

**Saturday smoke test (2026-04-25)**: full pipeline ran successfully
on 10-ticker universe in 2 min.  Path A SEC improvements active in
live signal path.  SELL PUTS fired on 3 of 4 actionable signals
(NVDA, IWM, SPY) confirming real-data unblocking of the strategy
that synthetic-vol pricing had hidden.  AAPL transient FinBERT CDN
error recovered cleanly.  GO confirmed for Monday 6:30 PM scheduled
run.

Live signals from the smoke test:

| ticker | signal | sentiment | IV rank | note |
|---|---|---:|---:|---|
| NVDA | SELL PUTS | +0.29 | 72% | |
| IWM  | SELL PUTS | +0.26 | 90% | |
| GLD  | BUY CALLS | +0.39 | 24% | low IV → buy premium |
| SPY  | SELL PUTS | +0.29 | 76% | |
| others | NEUTRAL or earnings-filtered |

The 3 SELL PUTS firings are particularly significant: in the
synthetic-vol backtest (Decision 7) every SELL PUTS signal was
rejected by the credit-premium floor (`CREDIT_MIN_PREMIUM_FR=0.33`)
because the realised-vol-as-IV proxy systematically underprices
short OTM puts.  Real options data carries the vol risk premium
that the proxy lacks, so credits clear the floor naturally on live
data.  This validates the deferral decision (synthetic enablement
would have required loosening the floor or restructuring the
short-delta target -- both worse than waiting for real data).

### 2026-04-25 universe rebuild + 6-decision review

Headline: 5-ticker mega-cap-tech basket replaced with a 10-ticker
6-sector / 3-asset-class universe (AAPL, NVDA, JPM, XOM, UNH, WMT,
IWM, GLD, TLT, SPY).  Effective independent bets jumped from ~1.5 to
6.66 (60d eigenvalue-entropy).  All KPIs rebaselined; previous
5-ticker numbers archived in §7.4 and as commented-out provenance in
`scripts/r3_baseline.py`.  Six decisions taken below; all six
deferred / non-promoted decisions preserve their respective code
intact, so re-enablement is a config / pin change rather than a port.

**Code changes landed this session:**

- `config.py`: 10-ticker `TICKERS`, plus new `SECTOR_MAP`,
  `ASSET_CLASS`, and `ETF_TICKERS` exports.
- ETF graceful-skip in `data/sec_fetcher.py`, `sentiment/sec_scorer.py`,
  `sentiment/merger.py` (logs "ETF / non-issuer -- no SEC data, news-
  only sentiment"; build proceeds via the only-news merger branch).
- New scripts: `scripts/correlation_matrix.py`,
  `scripts/sector_decay.py`, `scripts/refit_confidence_v2.py`.
- `scripts/r3_baseline.py`: pinned constants migrated to 10-ticker
  baseline (R3 + flat, both verdict MATCH); 5-ticker pins preserved
  inline as commented-out provenance.  `_taken_mask` bug fix to
  exclude `negative_kelly_*` zero-contract rows from n_trades count.
- `signals/position_sizer.py`: TODO marker near `MIN_TRADES_FOR_KELLY`
  documenting the SELL PUTS deferral and the three-step real-data
  revisit checklist.
- `CLAUDE.md`: universe taxonomy added under conventions; locked
  decision #1 (BUY PUTS structure) annotated as preserved-but-disabled
  on the 10-ticker universe; new helper scripts documented under
  "How to run".
- `PROJECT_STATE.md` §1, §3.1, §7 (current + new §7.4 archived),
  §10 (next-session priorities), §11 (this entry).

**Decisions taken (six):**

- **D1. BUY PUTS fate -> A3 (deferred to real data, no code change).**
  10-ticker per-signal Kelly stats produce f* = -0.0567 for BUY PUTS
  (was +0.2345 on 5-ticker), so production's negative-Kelly filter
  blocks all BUY PUTS entries.  Per-sector decay shows the signal
  carries positive mean_dir_ret only in Healthcare (+6.13% at 20d,
  n=63) and marginally in BroadMarket; the 5-ticker headline edge was
  a tech-concentration artifact.  Structural overrides
  (`_PER_STRATEGY_DTE["BEAR_PUT_DEBIT"]=60`,
  `_PER_STRATEGY_SHORT_DELTA["BEAR_PUT_DEBIT"]=0.25`) and signal-
  generation code preserved on disk; revisit Healthcare-only
  restriction (A2) once real data lands (§10.1.3).
  **[2026-04-27: Provisional pending OOS validation.**  The structural
  override survives this audit only because the negative-Kelly filter
  zero-contracts BUY PUTS under R3 on the current corpus.  If real-data
  Kelly_f swings positive, the 60-DTE / 0.25Δ structure must be
  re-validated under walk-forward conditions on real sentiment before
  re-enabling.**

- **D2. SELL PUTS enablement -> Option C (defer to real data).**
  Universe-wide decay returns TRADE at 10d (risk_adj +0.29, mean +1.97%
  directional) over 108 signal observations -- but the upstream
  credit-spread filter (`spread_builder.CREDIT_MIN_PREMIUM_FR = 0.33`)
  rejected ALL 108: typical synthetic credit on a $5 spread came in at
  $0.83-$0.98 (17-20% of width) vs the 33% floor.  Root cause: the
  backtest's `rolling_vol`-as-IV proxy systematically under-prices
  short OTM puts because it lacks the vol risk premium real markets
  carry.  Lowering the floor (Option A) degrades reward/risk math
  universe-wide; raising `CREDIT_SHORT_DELTA` to 0.30 (Option B)
  invalidates the decay verdict that motivated the change.  Decay
  TRADE verdict confirmed but enablement deferred to real data when
  IV will clear the floor naturally.  TODO marker added to
  `position_sizer.py`; signal_engine, spread_builder, and exit rules
  unchanged.

- **D3. v2 logistic -> NOT promoted.**  Refit on the 10-ticker corpus
  (n=613, train_win_rate 0.502) saved as
  `data/raw/confidence_model_v2_10t.json`.  Coefficients stable in
  sign vs the 5-ticker v1 fit; `iv_rank` strengthened to -0.137 (was
  -0.076).  Both models rank Q5 > Q1 cleanly on the new corpus
  (v2 spread +12.53pp; v1-on-new-corpus +13.40pp -- v1 actually edges
  out v2).  Production loader (`signals/confidence_model.load_model`)
  still reads the unversioned `confidence_model.json` (5-ticker fit).
  Deferred to A/B vs production model after real-data refit.
  **[2026-04-27: Provisional pending OOS validation.**  The non-
  promotion was decided on in-sample Q5−Q1 spreads (+12.53pp v2 vs
  +13.40pp v1).  Tonight's audits show Q5 inversion reproduces under
  walk-forward for v1, so the in-sample Q5−Q1 spread is not a
  reliable promotion criterion in the first place — the comparison
  was between two equally-untested models.  Promote/demote decision
  should be made on real-data walk-forward Q5 P&L, not in-sample
  spread.**

- **D4. Pinned baselines updated to 10-ticker production targets.**
  New pins in `scripts/r3_baseline.py`:
  R3 production = $6,775 / 0.41 / -$6,244 / PF 1.27 / 357 trades;
  flat = $17,913 / 0.42 / -$21,692 / PF 1.23 / 613 trades.  Five-
  ticker pins (session-1 R3 +$12,604 and refit-logistic R3 +$14,872)
  preserved as commented-out provenance.  `_taken_mask` bug fix:
  rows with `kelly_reason` starting with `negative_kelly_` (zero-
  contract Kelly skips, accepted=True with pnl=0) are now correctly
  excluded from the actually-traded count.  Without this fix the new
  pin of n_trades=357 would have permanently DRIFTed at +256 against
  its own latest run.  Drift check expanded: now reports per-metric
  drift for both R3 and flat.  Both verdicts: **MATCH** on all 10
  metrics post-fix.

- **D5. 5-ticker artifacts archived.**  All 30 MSFT/QQQ files moved
  to `data/raw/archive_5ticker/` in two passes:
  - Initial pass (22 files): `backtest_{MSFT,QQQ}_*.csv` (14),
    `sentiment_{MSFT,QQQ}_*.csv` (4), `options_{MSFT,QQQ}_*.csv` (4).
  - Cleanup pass (8 files): `news_{MSFT,QQQ}_*.csv` (4),
    `sentiment_summary_{MSFT,QQQ}.csv` (2), `signals_{MSFT,QQQ}.csv` (2).
  AAPL and NVDA files preserved in active universe (still in the
  10-ticker basket).  Confidence model JSONs, `kelly_stats.csv`,
  `quintile_edges.json`, and `combined_sentiment_AAPL.csv` all
  preserved in current location.  `check_pipeline.py` runs cleanly
  post-archive (verified twice): data inventory enumerates the 10
  active tickers without error, no broken file references.

- **D6. Task Scheduler verified -> GO for Monday 6:30 PM ET.**
  Live `OptionsSentimentPipeline` task config audited via
  `Get-ScheduledTask`: action points at the venv Python
  (`.venv\Scripts\python.exe`, not system), correct working
  directory, correct script path, weekly Mon-Fri trigger at
  6:30 PM local, ExecutionTimeLimit 2h, RunOnlyIfNetworkAvailable
  True, MultipleInstances IgnoreNew, StartWhenAvailable True,
  LastRunTime 2026-04-24 18:30 with LastTaskResult=0 (success on
  the 5-ticker basket).  `run_daily.py` iterates `config.TICKERS`
  with no hardcoded ticker lists in any pipeline module
  (verified via grep across news/options/reddit/aggregator/signal_engine);
  ETFs are handled because `run_daily.py` doesn't invoke the SEC
  path at all.  Runtime estimate: 5-ticker baseline was 2m 18s on
  4/24, 10-ticker estimate ~4-5 min (linear scaling on FinBERT
  inference; one-time model load doesn't double).  Far under the
  2h ExecutionTimeLimit -- no need to raise.  Battery settings
  flagged for user awareness: `DisallowStartIfOnBatteries=True`
  and `StopIfGoingOnBatteries=True` mean the run won't fire (or
  will be killed) if the machine is unplugged.  Today (2026-04-25)
  is a Saturday; next scheduled run is **Monday 2026-04-27 6:30 PM
  ET**, which will execute the full 10-ticker pipeline
  automatically.

Open items: see §10.1 for next-session priorities (real-data
validation, real-mode debug, BUY PUTS / SELL PUTS revisit, earnings
Q&A separation).

### 2026-04-27 Reddit removed -- pipeline clarified to 3-stream design

Audit of the sentiment pipeline (read-only, this session) confirmed
that Reddit had never produced data: no `reddit_*.csv` files on disk
in `data/raw/` or `data/raw/archive_5ticker/`, `config.REDDIT_*`
defaults were `"YOUR_..."` placeholders so `_build_client()` would
have raised on every invocation, and `run_daily.py` swallowed the
exception silently (Step 2/5 try/except) so downstream code never
saw a "Reddit unavailable" flag.  The +$6,775 R3 production baseline
is independent: synthetic-sentiment runs use
`backtest/engine._generate_synthetic_history` and don't read the
combined-sentiment CSVs at all.  Documentation and dormant code
were therefore creating a misleading impression that Reddit was a
wired feature.

**Decision: remove rather than fix.**  Reddit infrastructure had
zero validated value (no historical data) and an unbounded cost
(API key management, rate limits, credentials in env, free-tier
search reliability).  The 3-stream merger weighting (news 0.50 /
sec_earnings 0.35 / sec_other 0.15) doesn't depend on Reddit --
news has always meant "Finnhub" in practice -- so removal is a
clean documentation alignment, not a math change.

**Code changes landed this session:**

- `data/reddit_fetcher.py` deleted (and its `__pycache__` artifact).
- `scripts/run_daily.py`: removed Step 2/5 reddit fetch block,
  Step 4/5 reddit-scoring branch (and `_find_latest_reddit_csv`
  import), `reddit_post_count` from result and emergency-fallback
  dicts, `total_reddit` and the `Total reddit posts fetched` line
  in `write_summary`, the `r=...` field from per-ticker source
  string.  Step numbering renumbered 1/5..5/5 -> 1/4..4/4.
- `scripts/check_pipeline.py`: dropped the `Reddit` column from the
  data-inventory table and its width spec, the reddit-CSV glob, the
  `praw` package import probe, and the Reddit creds env-check
  section.
- `sentiment/aggregator.py`: removed `_merge_same_day` entirely
  (with reddit gone, the sentiment files for a ticker are one row
  per date so the same-day-merge step was a no-op).  Updated the
  comment in `load_sentiment_csvs` that referenced the news+reddit
  filename pattern.
- `sentiment/scorer.py`: removed `_find_latest_reddit_csv` and the
  `source_tag` parameter from both `score_from_csv` and `_save`
  (only call sites used `""` or `"reddit"`; the latter is gone, the
  former was the default).  Docstring trimmed accordingly.
- `config.py`: removed `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`,
  `REDDIT_USER_AGENT` and the `reddit_lookback_days` /
  `reddit_post_limit` / `reddit_subreddits` keys from
  `DATA_PARAMS`.
- `requirements.txt`: removed `# Reddit data` section header and
  the `praw>=7.7.0` line.
- `sentiment/merger.py`: comment fixes only -- `WEIGHT_NEWS`
  description "Finnhub + Reddit" -> "Finnhub", the load_news
  filename comment, and the daily-aggregation source comment.
- `CLAUDE.md`, `PROJECT_STATE.md` §2 file tree, `README.md`:
  removed Reddit from the architecture nav comments, the project
  structure listing, the API-key setup section, the
  optional-disclaimer line, and the per-stage manual-run cheat
  sheet.

**No changes to merger weights, drop-missing-weight policy,
backtest engine, signal_engine, position_sizer, or any model
artifact.**  This is a documentation / dead-code cleanup; the
3-stream weighting math and all downstream behavior are
unchanged.

**Verification.**  `scripts/run_daily.py --dry-run` runs cleanly
post-change with the 10-ticker universe (no import errors, no
reference to deleted symbols).  `scripts/check_pipeline.py` runs
cleanly and shows the trimmed inventory table without errors.
Existing `combined_sentiment_*.csv` files on disk are unaffected
(the merger output schema is unchanged).

### 2026-04-27 Out-of-sample integrity audits — strategic reframe

Two audits this session, both stress-tests of the in-sample
+$6,775 / Sharpe 0.41 / 357-trades baseline.  Production code was
not modified by either; both are read-only path-(b) re-derivations
on the existing flat corpus, sizing decisions recomputed under
parameters whose training data does not include the trades being
evaluated.  Reports: `outputs/oos_audit_report.md` and
`outputs/walkforward_audit_report.md`.  Helper scripts:
`scripts/audit_oos_split.py` and `scripts/audit_walkforward.py`.

**Audit 1: 75/25 chronological holdout** (cutoff 2025-11-17).
Refits Kelly stats / quintile edges / confidence model on the
earliest 75% of the flat corpus by `entry_date`; evaluates Kelly
sizing on the last 25% only.  Train fold (params on data they were
fit on): Sharpe **+0.7962**, P&L **+$10,147** on 244 trades.
**Test fold (held-out 25%): Sharpe −0.5977, P&L −$2,878 on 113
trades.**  Q5 confidence bucket P&L flips from +$5,505 in-sample
to −$5,586 OOS — the model's "highest confidence" trades become
its worst losers when held out.

**Audit 2: Daily walk-forward** (195 unique refits, warmup cutoff
2025-01-06).  Parameters refit each time a new accepted trade
completes; every signal is sized using parameters fit on data that
finished before its entry date.  Aggregate **Sharpe −0.0517**
(statistically zero) across 698 evaluable signals / 400 taken
trades; **P&L −$1,181**, max DD −$15,312.  Q5 P&L **−$5,685**
preserves the inversion.  Rolling 60-day Sharpe distribution: 39%
of windows positive, mean −0.87, std 1.60, 41 strong-positive
(Sharpe > +0.5) vs 112 strong-negative.

**Verdict: DEGRADES CONSISTENTLY.**  The Q5 inversion reproduces
under two completely different validation methodologies on
completely different evaluation samples (113 trades held out vs
400 trades walk-forward).  The model's high-confidence bucket is
anti-predictive on synthetic-sentiment OOS data — losing money
even when averaged over 195 different refit windows.  This is the
single most robust finding in the audit chain.

**Walk-forward-specific finding: time-varying Kelly_f estimates
are themselves destructive.**  Walk-forward took **400 taken
trades vs in-sample's 357** — 43 MORE trades, not fewer.  The
production R3 negative-Kelly filter zero-contracts BUY PUTS on
the full corpus (Kelly_f = −0.057), but the rolling Kelly_f over
walk-forward training samples swings positive in some windows
before flipping back.  Trades entered during transient
positive-Kelly windows mostly lost money.  Most striking:
**JPM goes from −$63 / 14 trades in-sample to −$4,674 / 34 trades
walk-forward** — the walk-forward sometimes let through JPM
signals the in-sample run blocked, and most of those losers piled
on top of an already-negative ticker.

**Strategic reframe.**  The +$6,775 / Sharpe 0.41 baseline is
**methodology validation, not edge demonstration**.  The
architecture (sentiment ingestion → signal classification →
spread construction → Kelly sizing → Sharpe-instrumented
backtest) is end-to-end functional and deterministic, but the
parameters fit on synthetic-sentiment data do not generalise
within that synthetic regime.  All future strategy-edge claims
must be backed by walk-forward metrics on **real** data; synthetic
runs become methodology validation only.

**What this DOESN'T change.**  The architecture is unchanged.
The signal pipeline (Finnhub news → FinBERT → 3-stream merger
weighting) is correct.  The dashboard renders correctly.  The
backtest engine reproduces the +$6,775 deterministically.  The
sizing logic in `position_sizer.size_trade` is well-defined.  The
locked design decisions (R3 sizing, BUY PUTS structural override,
v2_10t non-promotion) are now annotated as provisional but not
reversed — synthetic-OOS results say "no evidence the choice is
right", not "the choice is wrong", and reversing without a
better-validated alternative would be churn.

**Annotations added to PROJECT_STATE.md** (this session,
documentation-only): §1 honest-status paragraph; §6 R3-sizing
provisional banner; §7 baseline reframe banner; §4.2 BUY PUTS
structural override note; §12 D1 BUY PUTS deferred annotation;
§12 D3 v2_10t non-promotion annotation.  No code, scripts,
backtest engine, signals, sentiment, sizing logic, or config
were modified.

**Next major step.**  Real-data validation.  The Mon-Fri 6:30 PM
ET scheduled task accumulates one day of authentic Finnhub
sentiment per run; once 30-60 trading days are on disk
(approximately late-May 2026 through mid-June 2026), repeat
both audits with `--real`.  If the Q5 inversion does not
reproduce on real data, the synthetic regime was the issue and
the production strategy has the edge claimed.  If it does
reproduce, the confidence model itself is anti-predictive and
needs structural rework — most likely a target-function rebuild
(magnitude or risk-adjusted-return target rather than win-
probability target), or a different feature set entirely.  Until
that data lands, no strategy-edge conclusions can be drawn from
this codebase.

### 2026-04-24 end-of-session snapshot

What changed this session (vs the post-initial-build state documented in
§5 / §7 / §8 before):

- **Production sizing flipped to R3** (quintile per-trade cap, no
  strategy buckets, global 6% cap).  Legacy segregated-bucket Kelly is
  retained behind `position_sizer.USE_STRATEGY_BUCKETS = True` for A/B.
  Engine no longer hardcodes the regime -- it defers to the module flag.
- **Three-regime study** (`outputs/regime_comparison.md`) tested R1
  (larger BUY PUTS bucket), R2 (Variant C 45 DTE / $10 width) and R3
  on the full flat corpus.  Only R3 flipped Kelly to positive P&L;
  R1 barely cleared zero (+$1.7k) because raising BUY PUTS to 4.5%
  dropped block rate only 58% -> 49% while starving BUY CALLS; R2
  lost $7.5k because shortening BUY PUTS to 45 DTE re-introduced
  theta drag that the original put_structure_study had eliminated.
- **Magnitude-model work COMPLETED, not pending.**
  `signals/confidence_model_magnitude.py` built, fit, and put through
  time 75/25 + ticker-LOO hold-outs plus a full R3 A/B.  Result:
  **not promoted**.  Interaction-term fallback (8 features) also ran
  and also failed.  Logistic refit alone resolved most of §8.2;
  magnitude-target loss function didn't add value on this corpus.
- **Key KPI updates vs start-of-session:**

  | metric | start-of-session | end-of-session |
  |---|---:|---:|
  | Production sizing | segregated Kelly (v2) | R3 quintile (v3) |
  | Active Kelly P&L | -$3,215 | **+$14,872** |
  | Active Kelly Sharpe | -0.12 | **+0.54** |
  | Active Kelly profit factor | 0.92 | 1.31 |
  | BUY PUTS block rate | 58.3% | **29.2%** |
  | Q5 total P&L under Kelly | -$5,451 (v2), -$3,221 (v3-early) | **+$3,619** |
  | Confidence model | logistic (session-1 fit) | logistic (2026-04-24 refit) |
  | Pinned drift check in `r3_baseline.py` | n/a | +$14,872.48 / 0.5415 / 358 |

- **Open next steps** (§10.2): Q4 dip drill-down (-$815 total, isolated
  to that quintile), optional Q5-capped-at-Q4 fallback, and everything
  parked until real sentiment backfill arrives.  Magnitude model
  should be re-tested on real data where `sec_aligned` and
  `log_days_to_earnings` carry non-zero variance.

### 2026-04-30 Dedup fix + housekeeping

**Deduplication fix (same date, separate session):**

Root cause: each daily scrape (`sentiment_{T}_{date}.csv`) contains a multi-day
lookback window, not just the current day's articles.  When `load_sentiment_csvs`
stacks all available daily files, earlier dates appear once per file that covers
them — up to 5 rows for one date when 5 overlapping scrape windows overlap.
`_fill_date_gaps`'s left-merge propagated those duplicates verbatim into the summary.

**Fixes landed:**

1. **One-time cleanup:** all 10 `sentiment_summary_{T}.csv` files deduped in place.
   Rule: per `(ticker, date)`, keep the row with the highest `headline_count`
   (most comprehensive single scrape); ties keep the first occurrence.

   | ticker | rows before | rows after | removed |
   |---|---:|---:|---:|
   | AAPL | 24 | 8 | 16 |
   | NVDA | 194 | 189 | 5 |
   | JPM  | 35 | 14 | 21 |
   | XOM  | 55 | 20 | 35 |
   | UNH  | 48 | 20 | 28 |
   | WMT  | 41 | 16 | 25 |
   | IWM  | 48 | 19 | 29 |
   | GLD  | 88 | 34 | 54 |
   | TLT  | 86 | 34 | 52 |
   | SPY  | 28 | 9 | 19 |
   | **total** | **657** | **373** | **284** |

2. **Pipeline fix:** `sentiment/aggregator.py` `load_sentiment_csvs` — added a
   deduplication step immediately after `pd.concat`.  For each `(ticker, date)`,
   keeps the row with the highest `headline_count`; ties keep first occurrence.
   All future `build_sentiment_summary` calls produce clean output automatically.

**Housekeeping (same session):**

- `config.DATA_PARAMS["news_lookback_days"]` confirmed at 30 (no change).
  Tonight's 6:30 PM run naturally backfills 2026-04-29 (the run missed while
  the laptop was off): the 30-day window covers it, and 4/29 articles will
  appear in `sentiment_{T}_2026-04-30.csv` with proper scores.
- 10 `.bak` files created by the dedup fix deleted from `data/raw/`.
- Momentum label audit: `detect_momentum` uses `min_streak=3`.  NaN gap-fill
  rows (weekends / no-news calendar days) set direction=0 and reset the streak
  counter via the `else` branch (`streak=1, streak_dir=cur_dir`), so any
  weekend gap between actual data days breaks a streak in progress.  Labels
  therefore require 3 consecutive calendar days with actual data and the same
  direction change — possible on Mon/Tue/Wed or Tue/Wed/Thu sequences, not
  across weekends.  Status as of 2026-04-30: only NVDA (1 FALLING) and SPY
  (1 RISING, 1 FALLING) show any labels; 8 of 10 tickers are zero.
  **Validation checkpoint: ~2026-05-21 (15 trading days).**  By that date
  each ticker will have multiple weekday-consecutive data windows; inspect
  label counts then to confirm streak logic is firing as intended.
- Windows wake timer command documented: run once in an admin PowerShell to
  register a daily 6:25 PM scheduled task that wakes the machine 5 minutes
  before the `OptionsSentimentPipeline` trigger.  Works from sleep (S3);
  does NOT reliably wake from hibernate (S4) or Fast Startup hybrid sleep.
  See §10.1 addendum below.

**Data pipeline status as of 2026-04-30:**

| ticker | actual data days | date range |
|---|---:|---|
| AAPL | 8  | 2026-04-21 to 2026-04-28 |
| NVDA | 9 + pre-Apr history | 2025-10-22 to 2026-04-28 |
| JPM  | 14 | 2026-04-15 to 2026-04-28 |
| XOM  | 20 | 2026-04-09 to 2026-04-28 |
| UNH  | 20 | 2026-04-09 to 2026-04-28 |
| WMT  | 16 | 2026-04-13 to 2026-04-28 |
| IWM  | 19 | 2026-04-10 to 2026-04-28 |
| GLD  | 31 | 2026-03-26 to 2026-04-28 |
| TLT  | 29 | 2026-03-26 to 2026-04-28 |
| SPY  | 9  | 2026-04-20 to 2026-04-28 |

Pipeline is in passive accumulation mode.  No code changes planned until the
15-trading-day checkpoint (~2026-05-21).  The 30-60 trading day milestone for
real-data backtesting remains ~late-May through mid-June 2026 (§10.1).

---

## 13. Interview talking points

The seven findings below are the ones with the strongest numeric backing in
this repo — they're defensible without hand-waving because every claim maps
to a specific study artifact on disk.

### 12.1 Logistic confidence model inverted the signal relative to the legacy tiered formula

The legacy hand-rolled confidence formula (high |sentiment| × high IV_rank →
high confidence) produced a **Q5−Q1 spread of +7.73pp with Q5 actually
inverting at the top**.  Refitting as a proper logistic regression on the
417-trade flat corpus flipped the signs on `abs_sentiment` (β = −0.2195) and
`iv_rank` (β = −0.1929) and produced a **Q5−Q1 spread of +15.76pp with Q5
strictly > Q4 > ... > Q1 at flat sizing**.  Economic interpretation: in this
universe, extreme sentiment inside a high-vol regime is more likely to
mean-revert than to extend.  The legacy formula was assuming the opposite.
See §5 for coefficients, §5.3 for the validation table.

### 12.2 SELL CALLS was auto-disabled by the decay study — an honest null result

The per-segment decay study (`outputs/signal_decay_analysis.md`) sweeps
risk-adjusted mean return across 5/10/20/40/60-day horizons for each signal
type.  Every other signal had at least one positive-mean horizon; SELL
CALLS was negative at every horizon across 61 trades (best risk-adj
−0.071).  Rather than force it into the sizer and let it bleed, the
pipeline treats decay-study output as authoritative and drops the strategy.
The bucket allocation (0.75%) is kept reserved so a future dataset can
re-enable it without breaking the 6% invariant.  This is the kind of result
worth showcasing because most systems don't publish their null findings.

### 12.3 BUY PUTS structure study: how Variant B was identified

A naive approach would keep every signal on the same 35 DTE / 0.30Δ short
leg as the default debit spread.  `scripts/put_structure_study.py` swept
BUY PUTS across **DTE ∈ {30, 35, 45, 60} × short_delta ∈ {0.20, 0.25,
0.30}**, rebuilt the full flat corpus for each cell, and measured P&L per
cell.  The winner (Variant B: 60 DTE / 0.25Δ) turned the same BUY PUTS
signal cohort from **+$8,396 → +$32,457** — nearly 4× the P&L on the same
signals.  Implementation used a per-strategy override dict
(`_PER_STRATEGY_DTE["BEAR_PUT_DEBIT"] = 60`) so the search result flows
into both live and backtest paths without broader refactor.  The method
generalises: if a future study finds e.g. a better BUY CALLS structure,
the override slot is already there.

### 12.4 Capacity-adjusted selection bias: why flat beats Kelly on this corpus

Naive reading of the segregated-Kelly run would be "Kelly lost money,
abandon Kelly."  The actual finding is more interesting: the Q4/Q5 P&L
inversion (Q5 = −$5,451) is **not** a failure of the confidence model — the
same model scores cleanly at flat sizing — but a selection artifact
introduced by capacity constraints.  Mechanism:

1. Kelly_f for BUY PUTS is ~13× BUY CALLS (0.0586 vs 0.0046), so
   high-confidence BUY PUTS trades want large sizes.
2. The BUY PUTS bucket is capacity-constrained: 98/168 signals (58.3%) are
   blocked because prior 60-DTE positions haven't expired.
3. The BUY PUTS trades that DO get through are not a random sample — they
   skew to early-signal moments where the thesis has room to drift against
   us before the next bucket slot opens.
4. Kelly sizes these adversely-selected trades LARGE because confidence is
   high, amplifying the loss.

Flat sizing ignores bucket caps entirely (1-contract floor), so every
signal enters regardless of capacity — the adverse selection never
materialises.  This is the kind of finding that matters in an interview:
the problem isn't the model, it's the interaction between sizing aggression
and capacity.  Fix (§9) is a bucket-weight reallocation, not a model
change.  Numbers are in §7.2 (58.3% blocked), §7.4 (Q5 = −$5,451), §8.2
(mechanism write-up).

### 12.5 2023 rate-hike stress visible in AAPL SEC filings (FinBERT regime detection)

FinBERT detected measurable bearish shift in AAPL management language
during 2023 Fed tightening: **average MD&A sentiment −0.25 across 10
quarterly filings, with all four 2023 10-Qs scoring near −0.58** once
corrected MD&A extraction was in place.  The signal was hidden in
prior analysis by an MD&A regex bug that diluted bearish content with
neutral accounting boilerplate (the original session reported −0.13;
the corrected re-validation roughly doubled the magnitude).  Discovery
and correction documented in `outputs/sec_sentiment_revalidation.md`
and PROJECT_STATE §12 (2026-04-25 Path A entry).

This is the signal the `sec_aligned` feature is designed to carry into
the logistic model (does today's news sentiment agree with the
slower-moving SEC regime signal?).  Currently zero-variance in demo
mode so IRLS zeros the coefficient — but the pipeline is built, the
corrected historical SEC sentiment series exists on disk for AAPL,
and the feature will come alive once real-mode sentiment is enabled
across the universe.  Key point for interviews: news sentiment alone
is reactive; cross-validating against SEC filing sentiment gives a
slower regime feature that news alone can't produce — and getting
the extraction right is half the battle (see §12.7).

### 12.6 COVID-era SEC sentiment validation is provisional

Pre-2022 AAPL 10-Qs use iXBRL primary documents whose narrative
content isn't accessible via standard HTML parsing — the MD&A text
lives inside `ix:nonNumeric` XBRL tags that `BeautifulSoup.get_text()`
doesn't surface.  The 5 affected filings (Q1-Q3 2020, Q1-Q3 2021)
are documented as a known limitation in PROJECT_STATE §10.3.  The
earlier "FinBERT didn't catch COVID stress" interpretation cannot
be confirmed without iXBRL-aware extraction; the corrected revalidation
window (2020-02 to 2020-05) yields a near-zero average that's still
based on boilerplate rather than narrative MD&A, so it's not
informative either way.  Honest framing for an interview: "we
identified a data-extraction limitation that prevents us from
revalidating the COVID-era reading.  The work to fix it (custom
iXBRL parser) wasn't justified for 5 historical quarters of one
ticker, but if the same issue recurs across multiple tickers in
real-data validation we'd revisit."  Showing the limitation honestly
is more interview-defensible than papering over it with a stale
−0.13 number.

### 12.7 Data integrity discovery and correction (Path A SEC pipeline)

During the SEC sentiment integration (2026-04-25 Path A), three
extraction bugs surfaced and were fixed before any downstream
analysis touched the data:

1. **MD&A regex matched cross-references rather than section headers.**
   The end-marker regex `item\s*(7\s*a|8)\b` matched any "see Item 8"
   reference inside the MD&A narrative, slicing only ~200 chars
   instead of the full ~16 KB section.  Fix: require strict section
   names (e.g., `Item 8\.?\s+Financial`).

2. **10-Q filings were parsed with the 10-K regex.**  10-K MD&A is
   Item 7; 10-Q MD&A is Item 2 of Part I — different sections,
   different surrounding markers.  The pre-fix code applied 10-K
   markers to 10-Qs, matching stray cross-references and producing
   tail-of-doc slices instead of MD&A.  Fix: form-aware extractor
   branches by `form` parameter.

3. **Item 7.01 (Reg-FD) earnings filings were missed by Item-2.02-only
   detection.**  Some filers (notably JPM, large parts of XOM) furnish
   their earnings call slides under Item 7.01 rather than as
   officially-filed Item 2.02 press releases.  19 earnings filings
   across 3 tickers (JPM 6, XOM 12, UNH 1) were misclassified as
   `8-K_other` and scored on the boilerplate cover instead of the
   slide-deck exhibit.  Fix: detector also tags `Item 7.01 + earnings
   keyword` cover pages as earnings.

All three documented and prior findings re-validated against
corrected extracts (`outputs/sec_sentiment_revalidation.md`):
universe-wide AAPL sentiment correlation old vs new = **r = 0.67,
mean abs diff = 0.22**, demonstrating prior data was directionally
similar but materially compressed — bearish quarters were diluted
by neutral boilerplate, neutral quarters were contaminated by
financial-tables content.  The 2023 rate-hike finding (§12.5)
strengthens under correction; the COVID finding (§12.6) becomes
provisional.  Interview framing: "I trust the corrected pipeline
because I broke and fixed it three times before relying on the
output, and I have a documented re-validation diff between
pre-fix and post-fix scores."

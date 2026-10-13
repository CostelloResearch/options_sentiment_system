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

**[2026-05-01 update — data-layer backfill: SEC depth 3y → 10y;
Finnhub historical access verified at ~12-month depth.  See
`outputs/sec_phase1_backfill_report.md`,
`outputs/finnhub_historical_spike.md`,
`outputs/finnhub_historical_spike_v2.md`,
`outputs/finnhub_historical_spike_v3.md`.]**

- **SEC depth.**  `config.DATA_PARAMS["sec_lookback_years"]` bumped
  from 3 to 10.  Re-fetch + re-score added **228 new filings** across
  5 of 6 single-name tickers (AAPL +55 to 2016-06-22; NVDA +46 to
  2020-03-10; XOM +67 to 2019-12-02; UNH +51 to 2020-10-14; WMT +8
  to 2023-02-21; **JPM +1, still clipped at 2025-05-01** by EDGAR's
  `recent`-block ~1000-entry cap — Phase 2 work).  4 of the 6
  tickers (AAPL, NVDA, XOM, UNH) now span both the **2020-COVID and
  2022-Inflation** macro regimes; AAPL additionally covers
  **2018-VolReturns** (10 new filings).  Downstream consumers
  (`sentiment.merger.load_sec_sentiment`, `build_combined`, engine
  `sec_aligned` feature) ingest the deepened history without code
  change — verified by NVDA smoke test.

- **News data.**  Three-spike chain on Finnhub free-tier
  `company_news` established: `to=` parameter is honoured (v2 Test B
  returned 243 articles dated within window six months back, not
  near today); per-call window is truncated to the upper ~7-9 days
  of the requested range; depth horizon sits at **~12 months**
  (v3 Test E at 12mo populated, v3 Test F at 14mo empty).
  **Chunked backfill is unblocked but not yet built.**  Cost
  estimate: ~52 calls per ticker × 10 tickers = **~520 API calls
  (~9 min wall clock at 60 calls/min)** plus FinBERT scoring of
  ~100k articles.  Build scheduled as a separate session
  (Phase 1.5 candidate, ahead of the mid-May ~15-trading-day
  passive-accumulation checkpoint).

- **Options chains.**  **Unchanged.**  This session did not touch
  the BS-priced synthetic-pricing path in `backtest/engine.py`
  (still uses 30-day rolling realised vol as sigma, no smile or term
  structure) nor the forward-only `data/options_fetcher.py`
  yfinance snapshots.  No historical chain integration in scope.

**[2026-05-04 — REAL-MODE VALIDATION LANDED — see §7.0.0,
`outputs/oos_audit_report_real.md`,
`outputs/walkforward_audit_report_real.md`, and §12 entries from
this date.]**  Architecture validated end-to-end on real Finnhub
news sentiment.  ~50k articles backfilled across 12 months
(2025-05-08 -> 2026-05-04), FinBERT-scored, deduped, and consumed
by the engine to produce a real-mode flat corpus + Kelly logs.
Real-mode in-sample R3: **+$9,697 / Sharpe 1.17 / 295 trades / PF
1.71 / max DD −$1,550** (BUY CALLS only; BUY PUTS zero-contracted
by the negative-Kelly filter at f* = −0.5224).  Both OOS audits
returned positive verdicts:

- **75/25 chronological holdout (PARTIAL).**  Test-fold Sharpe
  **+0.9790**, P&L **+$2,077**, Q5−Q1 spread preserved at
  **+$1,101.14** (in-sample +$1,079.21).  Synthetic-data Q5
  inversion **does not reproduce on real data**.  3 ticker P&L
  sign-flips with |pnl| > $100 (AAPL, IWM, NVDA — all small
  magnitudes within statistical noise on the test fold's 67 trades).
- **Walk-forward (WINDOW-DEPENDENT).**  Aggregate Sharpe **+1.1369**
  across **134 unique refits / 246 trades**, P&L **+$7,786**.
  Rolling 60-day Sharpe distribution: **103 of 123 windows
  positive (84%)**, mean +2.1194 / std 1.8618; 97 strong-positive
  vs 13 strong-negative.  Q5−Q1 spread **+$2,831** (in-sample
  +$1,079.21).

The synthetic-data Option A justification (Q5 inversion under OOS,
2026-05-01) was a property of the synthetic generator's regime,
not the architecture.  Three caveats constrain how strong this
result is:

- **Single regime.**  ~12 months of real news (2025-05-08 to
  2026-05-04), predominantly bullish-equity conditions
  (Finnhub free-tier hard-caps at ~12 months, see §10.3).  Says
  nothing yet about regime-transition robustness.
- **Concentration.**  XOM (+$4,860, 50% of P&L), GLD (+$2,390,
  25%), and WMT (+$1,715, 18%) carry 93% of the total in-sample
  R3 P&L.  The remaining 7 tickers contribute ~$732 net (NVDA,
  SPY, IWM, AAPL positive; UNH, TLT, JPM negative — JPM at
  −$766 is the single largest contributor of negative P&L).
- **Single strategy.**  295 of 295 actually-traded positions are
  BUY CALLS.  BUY PUTS evaluations exist (154 signal days) but
  zero-contract under the negative-Kelly filter; SELL CALLS /
  SELL PUTS are decay-disabled and credit-floor-blocked
  respectively from earlier sessions.

Honest current state: **architecture validated, real-mode edge
demonstrated within a 12-month single-regime corpus with strategy
and ticker concentration caveats.  Not yet validated across
multiple regimes.**  The remaining structural limitation is
news-history depth, not pipeline correctness — see §10.1
priorities.

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

### 7.0.0 Real-mode validation (2026-05-04 -- first real-data validation)

_Source of truth: `outputs/oos_audit_report_real.md`,
`outputs/walkforward_audit_report_real.md`, and the on-disk
`data/raw/sentiment_{T}_real.csv` corpus (~50k articles, 2,967
daily-aggregated rows across 10 tickers, 2025-05-08 to
2026-05-04).  These are the **load-bearing validation result as of
2026-05-04**.  Synthetic baselines below (§7.0 onward) are
preserved as the in-sample synthetic record._

**Headline metrics:**

| run | n_signals | n_trades | total P&L | Sharpe | max DD | profit factor | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| **flat real-mode (1 contract)** | 507 | 449 | −$18,983 | −0.90 | −$27,048 | 0.66 | 43.2% |
| **R3 real-mode (Kelly, real-data params)** | 507 | 295 | **+$9,697** | **1.17** | −$1,550 | 1.71 | 33.7% |
| 75/25 OOS test fold | 125 | 67 | +$2,077 | 0.98 | −$960 | 1.63 | 31.2% |
| Walk-forward (134 refits) | 408 | 246 | +$7,786 | 1.14 | −$1,909 | 1.68 | 35.1% |

OOS verdict: **PARTIAL** (75/25 chronological holdout, cutoff
2025-12-22).  Walk-forward verdict: **WINDOW-DEPENDENT** (134
refits, warmup cutoff 2025-07-29; 84% of rolling 60d windows
positive).  Q5−Q1 spread preserves the in-sample +$1,079.21
ordering on both audits (test fold +$1,101.14, walk-forward
+$2,831.00).

**Per-signal Kelly stats (real-mode flat corpus):**

| signal | n | win_rate | f* | tradable |
|---|---:|---:|---:|---|
| BUY CALLS | 295 | 57.97% | **+0.2416** | YES |
| BUY PUTS | 154 | 31.17% | **−0.5224** | NO (negative-Kelly filter blocks) |

**Real-mode quintile edges:** `[0.1807, 0.2946, 0.3905, 0.4877]`
-- substantially lower than synthetic edges
`[0.5440, 0.5618, 0.5779, 0.6020]`.  The legacy tiered confidence
formula produces lower confidence values on real news than on
synthetic-generated sentiment, consistent with real news being
noisier (the synthetic generator was tuned for a tighter
sentiment-vs-direction relationship than real Finnhub headlines
exhibit).

**Per-ticker P&L contribution (in-sample real-mode R3, sorted by
magnitude):**

| ticker | n_taken | pnl | % of total |
|---|---:|---:|---:|
| XOM  | 67 | **+$4,860** | 50% |
| GLD  | 31 | +$2,390 | 25% |
| WMT  | 42 | +$1,715 | 18% |
| NVDA | 34 |   +$951 | 10% |
| SPY  |  7 |   +$331 |  3% |
| IWM  |  4 |   +$255 |  3% |
| AAPL | 23 |   +$248 |  3% |
| UNH  | 37 |    −$26 |  0% |
| TLT  |  5 |   −$261 | −3% |
| JPM  | 45 |   **−$766** | −8% |
| **Total** | **295** | **+$9,697** | **100%** |

**Strategic reframe vs the 2026-04-27 honest-status reframe (§7
banner above and §1).**  The 2026-04-27 OOS audits ran on the
synthetic-data corpus and surfaced a Q5 inversion that flipped
+$5,505 in-sample to −$5,685 walk-forward.  That inversion **does
not reproduce on real data** -- Q5 P&L on real data is +$2,180.56
in-sample and +$3,148.19 walk-forward, both positive and
preserving the Q5 > Q1 ordering.  The synthetic Option A
justification (Q5 inversion under OOS) was therefore a property
of the synthetic generator's deterministic-seed walk, not the
architecture.  Option A's reversal evaluation is now possible
using real-data evidence; flagged as §10.1 priority #4.

---

### Current production baseline (synthetic-sentiment 10-ticker, 2026-04-25)

_500-day demo run, 10 tickers, R3 sizing.  Headline numbers from
`outputs/r3_production_baseline.md` and `outputs/segregated_kelly_report.md`
(`USE_STRATEGY_BUCKETS=False` -- R3 quintile sizing despite the legacy
script name).  Pinned in `scripts/r3_baseline.py`; the drift check now
verifies both R3 and flat against the pins and reports MATCH on the
current run.  These are NOT comparable to the 5-ticker historical
baseline -- different universe = different strategy.  See §7.4 for the
archived 5-ticker baseline.  Synthetic baselines below preserved as
the in-sample synthetic record; the real-mode tables in §7.0.0 above
are the load-bearing validation result as of 2026-05-04._

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

_Re-prioritised 2026-05-04 after real-mode validation landed (§7.0.0).
The "wait for real data" priorities that anchored the prior list are
now retired -- real data has accumulated and validated the
architecture.  The new priorities are about hardening the result and
extending it across more regimes._

1. **Audit-report template fix.**  `outputs/oos_audit_report_real.md`
   and `outputs/walkforward_audit_report_real.md` contain real-data
   numerical findings but synthetic-baseline boilerplate prose
   ("the +$6,775 / Sharpe 0.41 / 357 trades baseline...", "All
   trades have `is_synthetic=True`...", etc.).  The `build_report`
   templates in both audit scripts didn't get updated when the
   `--real` plumbing landed earlier today; they still hard-code
   synthetic framing into prose strings while the table cells render
   real-mode data.  Small prompt: parameterise `build_report`'s
   prose against `mode_label`, re-run both audits in `--real` mode,
   verify the prose matches the data.

2. **Regime concentration analysis.**  Walk-forward rolling 60-day
   Sharpe distribution: 84% of windows positive but mean +2.12 / std
   +1.86 -- heavy-tailed.  Combined with XOM (+$4,860, 50% of
   in-sample R3 P&L) + GLD (+$2,390, 25%) + WMT (+$1,715, 18%)
   carrying 93% of total P&L, the question is whether positive
   windows rotate across tickers or are dominated by one or two.
   Concrete prompt: extend `audit_walkforward.py` with a
   "rolling-window contribution by ticker" table; re-run; if
   positive windows rotate across tickers the result is more robust
   than concentration suggests, if XOM+GLD+WMT dominate every
   positive window the strategy is closer to two-or-three-name beta
   than universe diversification.

3. **BUY PUTS deep-dive on real data.**  Real-mode BUY PUTS f* =
   −0.5224 (vs synthetic f* = −0.0567) -- much more negative.  154
   signals fired, all zero-contracted by the negative-Kelly filter.
   The earlier "Healthcare-only restriction might re-enable BUY
   PUTS" hypothesis (parked since the universe expansion) needs
   revisiting on real data.  Per-sector decay analysis on the real
   corpus would either confirm Healthcare BUY PUTS is positive
   (re-enable conditional) or kill the hypothesis entirely.  Use
   `scripts/sector_decay.py` adapted for `--real` if not already
   parameterised.

4. **Option A reversal evaluation.**  Option A disabled
   `USE_QUINTILE_SIZING` and `USE_LEARNED_MODEL` on 2026-05-01 with
   the explicit reversal trigger "real-data walk-forward Sharpe
   under quintile sizing exceeds uniform sizing by ≥X."  With
   real-mode results in hand, this evaluation is now possible.
   Concrete prompt: A/B run with both flag combinations
   (`USE_QUINTILE_SIZING ∈ {False, True}` × `USE_LEARNED_MODEL ∈
   {False, True}` = 4 runs), capture walk-forward Sharpe on each,
   document.  Note: §7.0.0 already shows real-mode Q5−Q1 spreads are
   positive and Q5 doesn't invert -- the quintile sizing case may
   now be defensible where it wasn't on synthetic data.

5. **Multi-regime data extension.**  The most fundamental constraint
   is **one-regime news coverage** (~12 months 2025-05 to 2026-05,
   predominantly bullish-equity).  SEC filings already span 10y for
   5 of 6 single-name tickers (§1 / 2026-05-01 backfill).  News is
   hard-capped at ~12 months on Finnhub free tier (verified by the
   v1/v2/v3 spike chain).  Options for extension: (a) paid Finnhub
   tier with longer history, (b) NewsAPI / RavenPack / similar
   alternatives, (c) accept the constraint and document in any
   write-up that real-mode validation is single-regime.  Decision
   deferred -- listed as priority #5 to flag the structural
   limitation rather than something to act on next session.

### 10.2 Resolved or moved (formerly "parked until real sentiment arrives")

_All bullets here were parked pending real-data validation.  That
landed 2026-05-04; the items have either been answered or relocated
to §10.1 priorities.  Preserved as historical record._

- ~~Re-evaluate whether BUY PUTS structure (60 DTE / 0.25Δ short)
  survives on real data.~~  **Answered (negatively).**  BUY PUTS
  f* = −0.5224 on real data, much worse than synthetic
  (f* = −0.0567).  Negative-Kelly filter zero-contracts all 154 BUY
  PUTS evaluations under R3.  Structural override (60 DTE /
  0.25Δ) stays preserved on disk for the day BUY PUTS gets
  re-enabled (Healthcare-only candidate, see §10.1 priority #3),
  but the universe-wide signal is dead under current sizing rules.
- ~~Retry the magnitude model on real sentiment.  `sec_aligned`
  and `log_days_to_earnings` carry no variance in demo.~~  **Open,
  not addressed yet.**  Real data does carry variance in those
  features; a magnitude-model rerun is now well-posed but was not
  in scope for this session.  Candidate prompt for a future session
  alongside §10.1 #4 (Option A reversal evaluation).
- ~~Refresh quintile edges and v2 logistic coefficients once the
  real-data flat corpus is built.~~  **Done partially.**  Real-mode
  quintile edges produced and saved during the
  `r3_baseline.py --real` run on 2026-05-04: `[0.1807, 0.2946,
  0.3905, 0.4877]`.  v2_10t logistic refit on real data is the
  remaining open item -- folded into §10.1 #4.

### 10.3 Known limitations (Path A SEC pipeline)

> **[2026-05-04 update — audit-report boilerplate prose mismatch.]**
> `outputs/oos_audit_report_real.md` and
> `outputs/walkforward_audit_report_real.md` contain accurate
> real-mode numerical findings but synthetic-baseline boilerplate
> prose still references "the +$6,775 / Sharpe 0.41 / 357 trades
> baseline" and "All trades have `is_synthetic=True`" -- artifacts
> of the `build_report` template strings not having been updated
> when the `--real` plumbing landed.  The numbers are correct; the
> prose framing is stale.  See §10.1 priority #1.

> **[2026-05-01 update — Phase 1 SEC depth backfill landed.  See
> `outputs/sec_phase1_backfill_report.md`.]**
>
> - **`sec_lookback_years = 3` is now `= 10`.**  Single-line config
>   edit, ran fetcher + scorer for the 6 single-name tickers.  +228
>   filings across 5 tickers.  AAPL deepened to 2016, NVDA/XOM/UNH
>   deepened to 2019-2020 (covering 2020-COVID + 2022-Inflation),
>   WMT only added 8 filings (Feb-May 2023 — no deeper history
>   returned for WMT; possibly EDGAR `recent`-block at a different
>   threshold or fewer 8-Ks per quarter).  **JPM still capped at
>   2025-05-01** (only +1 filing) — `recent`-block clipping
>   unchanged, see existing bullet below.
> - **JPM `recent`-block ~1000-entry cap** (existing bullet, unchanged
>   status): explicitly **Phase 2** work.  Walking the `files` chain
>   to older submission archives is the documented fix; not in scope
>   this session.
> - **AAPL pre-2022 iXBRL stub-extraction** (existing bullet, unchanged
>   status): explicitly **Phase 2** work.  The 2016-2020 backfill
>   likely added more iXBRL-affected 10-Q filings beyond the 5
>   already identified; sample inspection of new AAPL row scores
>   recommended before relying on AAPL deep-history sentiment for
>   OOS testing.
> - **Item 1A Risk Factors not extracted** (new Phase 2 backlog item):
>   the fetcher targets only Item 7 MD&A for 10-K/Q.  Risk Factors
>   would be additive narrative-shift signal and are recommended
>   alongside the iXBRL fix.
> - **WMT shallow backfill** (new anomaly to investigate): only +8
>   filings to 2023-02-21 despite the 10y depth bump.  Root cause
>   not yet identified — may be EDGAR `recent`-block at a different
>   threshold, fiscal-year offset shifting filing schedule, or simply
>   a filer with sparser 8-K cadence.  Tag for Phase 2 alongside JPM.
> - **Finnhub free-tier 12-month depth ceiling** (new, news pipeline
>   not SEC, but documented here for the data-limitations grouping):
>   three-spike verification chain
>   (`outputs/finnhub_historical_spike{,_v2,_v3}.md`) established
>   that the free-tier `company_news` endpoint serves at most ~12
>   months of history.  Beyond that, requests return empty (not
>   errors).  **Hard ceiling for news historical access on the
>   current API key** — extending past 12 months requires either
>   paid-tier upgrade or alternate news source (NewsAPI, RavenPack,
>   etc., not yet evaluated).


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

# OOS integrity audits (75/25 chronological holdout + walk-forward)
.venv/Scripts/python.exe scripts/audit_oos_split.py
.venv/Scripts/python.exe scripts/audit_oos_split.py --real
.venv/Scripts/python.exe scripts/audit_walkforward.py
.venv/Scripts/python.exe scripts/audit_walkforward.py --real
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

### 2026-05-04 Audit scripts -- partial-coverage relaxation + plumbing acknowledgement

Two changes to the OOS integrity audits, both scoped narrowly to the
audit scripts themselves (no production-code, no `signals/`,
`backtest/`, `sentiment/`, or `config.py` edits).

**Plumbing acknowledgement (work that landed before this session, not
previously logged).**  `scripts/audit_oos_split.py` and
`scripts/audit_walkforward.py` already had real-mode support
implemented end-to-end: `--real` argparse flag, real-mode loaders
(`backtest_{T}.csv` + `backtest_{T}_kelly.csv`), mode-dependent output
paths (`outputs/oos_audit_report_real.md`,
`outputs/walkforward_audit_report_real.md`), real-mode OOS artifact
paths (`data/raw/kelly_stats_oos_train_real.csv`, `..._real.json`,
`..._real.json`), and a fail-early guard against missing real-mode
corpus.  Logging the existence of that work here so the next session
doesn't duplicate it.

**Partial-coverage relaxation (this session).**  The fail-early guard
required all 10 tickers' real-mode flat + kelly logs on disk, which
would have meant zero audit signal until the full late-May real-data
validation milestone.  The guard now allows real-mode runs with `1 <=
N < 10` ticker coverage:

- Coverage detection in each script's `main()` builds
  `audit_tickers = sorted(set(present_flat) & set(present_kelly))`
  and `missing_tickers` with per-ticker reasons (`"flat missing"` /
  `"kelly missing"` / `"both missing"`).
- Real-mode partial: stderr `[oos_audit] partial coverage: N of 10
  tickers -- included: ... -- missing: ...` warning, audit proceeds.
- Real-mode zero: existing fail-early preserved.
- Demo-mode partial: still fails fast (demo coverage completeness is a
  regression signal, not relaxed).
- Full coverage: silent (no warning, no annotation).

Reports gain two annotations only when real-mode partial: the mode line
reads `**Mode: REAL (partial coverage: N of 10 tickers)**`, and
methodology gains a `**Coverage:**` subsection naming included +
missing tickers with reasons.  Per-ticker P&L tables get a
`_(N tickers in audit)_` caption suffix.  Loaders
(`load_flat_corpus`, `load_kelly_logs`) extended with optional
`tickers: list | None` parameter (default `None` → `config.TICKERS`,
preserving the prior signature behaviour).

**Edge-case fix (walkforward).**  Partial-coverage corpora smaller
than `WARMUP_N_TRADES = 50` exit `walk_forward()` with zero evaluable
rows.  The previous `pd.DataFrame(eval_rows)` returned an empty frame
with no columns, crashing downstream callers (`rolling_sharpe`,
`per_ticker`) on missing-column accesses.  Fix: `walk_forward` now
returns an empty frame with the expected schema (deduped against
overlapping `kelly_reason` between flat-log and wf-augmented columns);
`per_ticker` short-circuits with the schema-only frame; the AAPL/NVDA
P&L extraction in `build_report` uses a small helper that handles
empty/missing-column inputs.

**Follow-up audit (same date).**  Re-scanned both audit scripts for
analogous empty-frame access patterns.  One additional latent bug
fixed: `audit_oos_split.per_ticker()` was returning a no-columns
empty frame on empty input (would have triggered downstream
`KeyError` on `train_t[["ticker","n_taken","pnl"]]` selection in
`build_report`'s side-by-side merge under degenerate partial-coverage
scenarios, e.g. single-ticker 1-row corpora where the 75/25 split
produces a 0-row test fold).  Fix mirrors `audit_walkforward.per_ticker`:
explicit `columns=` on the empty return.  All other in-scope functions
(`headline`, `taken_mask`, `per_quintile`, `per_quintile_wf`,
`per_quintile_in_sample`, `evaluate_fold`, `rolling_sharpe`,
`fit_train_params`, `fit_params`) classify SAFE (existing
`if df.empty:` guards, pandas-native empty handling, or callers
length-guard the result).  Smoke tests re-run: 4/4 pass; demo-mode
output byte-identical to prior baseline; production artifacts
unchanged.

**Smoke tests run (4 of 4 pass).**

| # | scenario | expected | result |
|---|---|---|---|
| 1 | OOS, real-mode partial (3 of 10: AAPL/NVDA/JPM) | warn + annotated report | warning printed, `Mode: REAL (partial coverage: 3 of 10 tickers)`, Coverage subsection present, per-ticker table caption `_(3 tickers in audit)_`; production artifacts unchanged |
| 2 | OOS, real-mode zero coverage | fail-early exit 1 | matches existing format, exit=1 |
| 3 | OOS, demo full | structurally identical to baseline | section headers diff = empty, no Coverage / no partial annotation, production artifacts unchanged |
| 4 | All three repeated for `audit_walkforward.py` | same | partial: `[wf_audit] partial coverage: ...` + annotated report; zero: exit=1; demo: section headers identical |

Bonus check: temporarily renamed `backtest_AAPL_demo.csv` aside and ran
`scripts/audit_oos_split.py` (no `--real`); fail-early triggered
(`[oos_audit] ERROR: demo corpus partial -- 9 of 10 tickers present.
Missing: AAPL (flat missing).  Demo coverage completeness is a
regression signal; not relaxing the demo guard.`, exit=1).  File
restored after the test.

Production artifacts (`kelly_stats.csv`, `quintile_edges.json`,
`confidence_model.json`) verified bit-identical (mtime + size) before
and after every smoke test via the in-script `file_signature` snapshot
mechanism, which both audits already had.

### 2026-05-04 Finnhub chunked historical news backfill -- code only, smoke-tested

**What landed.**  Two additive code surfaces enabling the long-blocked
~12-month news backfill (PROJECT_STATE §1 / `outputs/finnhub_historical_spike*.md`):

- `data/news_fetcher.py::fetch_news_chunk(ticker, to_date, days=14, save_dir=None)`:
  sibling of `fetch_news` with explicit `to_date` so the orchestrator can
  walk backwards.  Atomic chunk-CSV write (tmp + `os.replace`).  Schema
  identical to the existing `news_*.csv` (`ticker, date, datetime,
  headline, summary, source, url`).  Sort: ascending by `datetime`
  (vs `fetch_news`'s descending eyeball-friendly order — backfill stitches
  chronologically).  Empty response -> empty DataFrame (depth-ceiling
  signal); any exception -> raised as `BackfillFetchError` (a new typed
  exception class added in the same file) so the orchestrator can
  distinguish API failure from depth ceiling.  **`fetch_news`,
  `fetch_all_tickers`, `_build_client`, `_save` unchanged**, verified
  via `git diff` (additions only, zero deletions inside existing
  functions).
- `scripts/backfill_news_history.py`: the orchestrator.  Argparse
  (`--ticker`, `--max-chunks`, `--dry-run`, `--reset`).  Manifest at
  `data/raw/backfill_manifest.json` tracks completed chunks per ticker
  with atomic writes after every chunk.  Idempotency: reconciles
  manifest vs disk on every restart (orphan CSVs adopted; manifest
  entries with missing CSVs dropped for re-fetch).  Retry on
  `BackfillFetchError` with exponential backoff (2s, 4s, 8s, 16s, 32s,
  cap 32s, 5 attempts).  Depth-ceiling detection requires `>= 2`
  successful chunks before an empty result counts as ceiling -- a
  first-chunk empty is more likely auth failure and is flagged
  `in_progress` for operator review.  Pacing: 1.0s within ticker, 1.5s
  between tickers; matches existing `fetch_all_tickers` cadence and
  stays well under the documented Finnhub free-tier 60/min cap.

**Decisions.**  14-day chunk window with 13-day backwards walk
(intentional 1-day overlap as defence against `to=` boundary
off-by-one); manifest-based idempotency with atomic writes (chunk
CSVs and manifest both); FinBERT scoring deliberately deferred to a
follow-up prompt that will consume the chunk CSVs.  No FinBERT
imports in either new file (verified -- `sentiment/scorer.py` is not
imported by `backfill_news_history.py` or by `fetch_news_chunk`).
No new top-level dependencies.

**Smoke tests run (4/4 pass).**

| # | scenario | result |
|---|---|---|
| 1 | `--dry-run` (10 tickers, default cap) | prints 520-call plan with per-ticker schedule + ~8.9 min wall-clock estimate; manifest NOT created on disk; zero API calls |
| 2 | `--ticker AAPL --max-chunks 3` | 3 chunks fetched (n_articles 246/240/239), oldest `to_date=2026-04-08` = today−26d (= 2 × 13d step), manifest contents match CSV row counts (verified via `pandas.read_csv` -- raw `wc -l` differs because summaries contain embedded newlines) |
| 3 | re-run `--ticker AAPL --max-chunks 3` after test 2 | **0 API calls**, 0 new chunks, summary line same as test 2's terminal state |
| 4 | daily-pipeline regression: `from data.news_fetcher import fetch_news` + `git diff` audit | `fetch_news` importable with unchanged docstring; `git diff data/news_fetcher.py` shows additions only (no `^-` deletion lines hit existing-function bodies); `scripts/run_daily.py` shows zero diff |

Bonus restart check: re-running with `--max-chunks 4` after the
3-chunk state walked exactly 1 new chunk back to `to=2026-03-26` (=
`2026-04-08 − 13d`) and made exactly 1 API call -- confirms the
backwards-walk geometry holds across resume boundaries.  **Side
effect of smoke testing: 4 real AAPL chunks (965 articles total)
remain on disk under `data/raw/news_AAPL_chunk_*.csv` plus the
manifest at `data/raw/backfill_manifest.json`.  These are valid
backfill data and are kept** for the follow-up scoring prompt to
consume; not cleaned up.

**Pre-existing doc drifts surfaced by the recon -- NOT fixed in this
prompt.**

- PROJECT_STATE §2 architecture map labels `sentiment/aggregator.py`
  as "news ingestion (Finnhub)".  The actual Finnhub fetcher is
  `data/news_fetcher.py`; `sentiment/aggregator.py` is the
  multi-day-aggregation layer that loads scored CSVs and computes
  rolling/momentum.  Flag for a separate doc-cleanup task.
- `data/news_fetcher.py:158` (was line 149 pre-edit) still carries the
  comment `"Finnhub free tier allows ~30 requests/minute"`.  Spike v2
  documents the official rate as 60/min.  Flag for a separate
  doc/comment-cleanup task; the 1.5s sleep stays valid under either
  figure.

**Next-step queue.**

1. **Full backfill run** (`scripts/backfill_news_history.py` no flags):
   ~520 calls, ~9 min API wall clock, ~10 tickers × ~52 chunks each;
   produces ~520 chunk CSVs (~100k raw articles).  Single command,
   restartable, no FinBERT involved.
2. **Follow-up scoring prompt** consuming the chunk CSVs and producing
   `sentiment_{T}_{DATE}.csv` outputs in the existing daily-aggregated
   schema (so `aggregator.py`, `signal_engine`, `merger.py` see no
   schema change).  FinBERT inference dominates wall clock there
   (~tens of minutes on CPU; ~5x faster on GPU; comparable to the
   SEC backfill scoring step).
3. (Separate) Doc cleanup: §2 fetcher attribution; news_fetcher.py
   stale 30/min comment.

### 2026-05-04 Real-mode sentiment corpus -- chunks scored, downstream-ready

**What landed.**  `scripts/score_backfill_chunks.py` consumes the 280
chunk CSVs from the prior backfill (50,598 raw articles), dedups by
`url` (keep-first), invokes `sentiment.scorer.score_articles` +
`aggregate_daily` (no scorer modifications), and writes one
canonical real-mode CSV per ticker at
`data/raw/sentiment_{TICKER}_real.csv` plus a manifest at
`data/raw/scored_chunks_manifest.json`.  All atomic writes (tmp +
`os.replace`).  Idempotent: `--ticker T` on a complete ticker
returns 0.0s; `--reset` re-scores from scratch.

**Per-ticker results (full corpus, 10/10 complete).**

| ticker | raw | dedup | ratio | rows | date_span | elapsed |
|---|---:|---:|---:|---:|---|---:|
| AAPL | 6,679 | 6,679 | 1.00 | 220 | 2011-06-07 -> 2026-05-04 | 288.5s |
| NVDA | 6,835 | 6,835 | 1.00 | 136 | 2020-06-12 -> 2026-05-04 | 285.9s |
| JPM  | 5,535 | 5,241 | 0.95 | 331 | 2023-03-14 -> 2026-05-04 | 219.7s |
| XOM  | 4,284 | 3,922 | 0.92 | 339 | 2023-04-03 -> 2026-05-04 | 164.0s |
| UNH  | 3,853 | 3,376 | 0.88 | 334 | 2025-05-13 -> 2026-05-04 | 153.1s |
| WMT  | 5,824 | 5,188 | 0.89 | 348 | 2020-06-11 -> 2026-05-04 | 210.9s |
| IWM  | 6,094 | 5,466 | 0.90 | 363 | 2017-04-16 -> 2026-05-04 | 191.8s |
| GLD  | 2,455 | 2,128 | 0.87 | 341 | 2011-04-13 -> 2026-05-04 | 81.1s |
| TLT  | 2,087 | 1,824 | 0.87 | 323 | 2025-05-08 -> 2026-05-04 | 54.8s |
| SPY  | 6,952 | 6,952 | 1.00 | 258 | 2023-03-15 -> 2026-05-04 | 315.8s |
| **TOTAL** | **50,598** | **47,611** | **0.94** | **2,993** | | **1965s (32.8 min)** |

Device: CPU.  Total wall clock for the orchestrator (including TLT
skip from the prior single-ticker smoke test): 1910s for the 9
tickers actually scored in the full run.

**Dedup-key reality vs prompt assumption.**  The prompt expected
0.55-0.80 surviving fraction (i.e., 20-45% URL duplicates from chunk
overlap).  Actual: AAPL/NVDA/SPY at **1.00** (zero URL dedup); the
other 7 tickers cluster 0.87-0.95.  Investigation: Finnhub's URLs
carry a randomised `id=` query parameter that **changes per
request**.  `news?id=ead391...` and `news?id=cea00d...` were
observed for the same headline pulled in different chunks.  URL is
therefore an unreliable dedup key in general; the 5-15% that *does*
dedup on the lower-volume tickers happens when Finnhub's edge cache
serves identical responses to overlapping calls.  Real impact is
bounded: `aggregate_daily` averages `sentiment_score` by
`(ticker, date)`, so identical-headline duplicates (same FinBERT
score) leave the per-day mean unchanged; only `headline_count` is
inflated (~1-13% across tickers, depending on syndication
patterns).  Sentiment ranking and signs are correct.  Prompt's URL
dedup spec preserved as-is; the band warning is informational.

**Sub-finding: 0.5% out-of-window outliers concentrate in the long
tail.**  AAPL/GLD `earliest_date` reaches 2011, NVDA/WMT 2020, IWM
2017 -- these are the v3 spike's "Finnhub occasionally returns an
article whose stored `datetime` was reset/back-filled" outliers
flowing through unfiltered (the prompt explicitly directed keeping
them).  Bulk of articles (>99%) sit inside the 2025-05 to 2026-05
12-month window the backfill targeted.  Downstream consumers can
filter on `date >= 2025-05-01` if a strict horizon is needed.

**Smoke tests run (6/6 pass).**

| # | scenario | result |
|---|---|---|
| 1 | `--dry-run` (10 tickers) | per-ticker plan + ~28.6 min wall-clock estimate; manifest NOT created on disk; zero FinBERT load |
| 2 | `--ticker TLT` (smallest, ~2087 raw) | `sentiment_TLT_real.csv` 323 rows; schema = canonical 7 cols; sentiment_score in [-0.96, 0.85]; manifest entry with `status=complete`; ratio 0.87 (band warning fired) |
| 3 | re-run `--ticker TLT` after test 2 | 0.0s elapsed, manifest mtime unchanged (verified via stat) |
| 4 | locked-files regression: `git diff sentiment/scorer.py sentiment/aggregator.py sentiment/merger.py data/news_fetcher.py scripts/run_daily.py scripts/backfill_news_history.py` | only `data/news_fetcher.py` shows changes (additions-only from the prior backfill prompt; zero `^-` deletion lines hit existing functions); other 5 files zero diff |
| 5 | full 10-ticker run | 9 fresh tickers scored (TLT skipped via manifest); 2,993 daily rows total; 1965s aggregate scoring time; manifest totals match per-ticker sums |
| 6 | downstream-loader auto-pickup | `sentiment.aggregator.build_sentiment_summary('TLT')` returns 362 rows over 2025-05-08 -> 2026-05-04 (merged real-mode + 6 stale daily-pipeline files via the existing `(ticker, date)` highest-headline_count dedup); `sentiment.merger.load_news_sentiment('TLT')` returns 323 rows in the merger's 7-col schema.  **Both loaders auto-pickup `sentiment_{T}_real.csv` via the existing `sentiment_{T}_*.csv` glob -- zero wiring changes needed downstream.** |

**Downstream-loader compatibility verdict: GREEN.**  Real-mode
sentiment is end-to-end consumable by `aggregator.py` and `merger.py`
without any code changes.  `signal_engine.py` reads the merger's
output (or the daily aggregator's) so it inherits the auto-pickup
transitively.  No follow-up wiring task surfaced.

**Decisions.**  URL dedup retained per prompt spec despite the
ratio-band miss (rationale above: aggregation absorbs the over-count).
FinBERT loaded once per process via the scorer's existing
`_pipeline_cache`; ~32.8 min CPU wall clock total.  No GPU available
on this machine.

**Pre-existing doc drifts surfaced earlier this session -- still
NOT fixed (separate prompt).**  PROJECT_STATE §2 architecture map
labels `sentiment/aggregator.py` as the news fetcher (actually
`data/news_fetcher.py`); `data/news_fetcher.py:158` carries a stale
"Finnhub free tier allows ~30 requests/minute" comment (actual
documented rate is 60/min).  Both flagged in the prior backfill
entry above; both still untouched.

**Next-step queue.**

1. **Real-mode `r3_baseline.py --real`** -- produces
   `outputs/r3_production_baseline_real.md` plus per-ticker
   `backtest_{T}.csv` and `backtest_{T}_kelly.csv` driven by the
   real-mode sentiment corpus that's now on disk.  Operator-driven;
   no code changes needed.
2. **Real-mode audits** (`scripts/audit_oos_split.py --real` and
   `scripts/audit_walkforward.py --real`) -- already partial-
   coverage-tolerant from this session's earlier prompts; will run
   on whatever subset of tickers test 1 produces flat + kelly logs
   for.
3. (Separate) Doc cleanup: §2 fetcher attribution; news_fetcher.py
   stale 30/min comment.

### 2026-05-04 Backfill redup -- (headline,date) key + date-range filter

**What landed.**  `scripts/redup_backfill.py` re-derives the per-
ticker `data/raw/sentiment_{T}_real.csv` files from the raw chunk
CSVs using `(headline_normalized, date)` dedup (replacing the prior
URL key) and a date-range filter `[2025-05-05, 2026-05-04]` to drop
the v3-spike-documented out-of-window outliers.  Reuses
`sentiment.scorer.score_articles` + `aggregate_daily` (no scorer
modifications).  Idempotent: tickers with `dedup_method =
"headline_date_v2"` skip on re-run.  Atomic writes for both CSVs
and manifest.  The original `score_backfill_chunks.py` remains on
disk as the audit trail of what URL dedup produced.

**Per-ticker results (full corpus, 10/10 redupped).**

| ticker | raw | url_dedup | hd_dedup | oow | final | rows | redup_s |
|---|---:|---:|---:|---:|---:|---:|---:|
| AAPL | 6,679 | 6,679 | 6,679 | 4 | 6,675 | 216 | 230.5s |
| NVDA | 6,835 | 6,835 | 6,835 | 4 | 6,831 | 132 | 250.5s |
| JPM  | 5,535 | 5,241 | 5,240 | 2 | 5,238 | 329 | 197.8s |
| XOM  | 4,284 | 3,922 | 3,922 | 1 | 3,921 | 338 | 148.3s |
| UNH  | 3,853 | 3,376 | 3,376 | 0 | 3,376 | 334 | 128.8s |
| WMT  | 5,824 | 5,188 | 5,185 | 2 | 5,183 | 346 | 197.5s |
| IWM  | 6,094 | 5,466 | 5,466 | 3 | 5,463 | 360 | 176.9s |
| GLD  | 2,455 | 2,128 | 2,128 | 6 | 2,122 | 335 | 75.4s |
| TLT  | 2,087 | 1,824 | 1,824 | 0 | 1,824 | 323 | 87.6s |
| SPY  | 6,952 | 6,952 | 6,952 | 4 | 6,948 | 254 | 291.1s |
| **TOTAL** | **50,598** | **47,611** | **47,607** | **26** | **47,581** | **2,967** | **1696.8s (28.3 min)** |

**Empirical finding -- `(headline, date)` is barely different from
URL dedup on this corpus.**  The prompt expected 5-30% additional
reduction on AAPL/NVDA/SPY (the URL-ratio-1.00 tickers).  Actual
additional reduction across all 10 tickers: **4 rows** (JPM −1, WMT
−3).  Root cause: when chunks contain "the same headline", they
sit on **different dates** -- typically syndicated columns
republished weekly or monthly (e.g., AAPL's "1 Unstoppable Stock to
Buy Before It Joins Nvidia, Apple, Mi..." appeared on 2025-11-02
*and* 2025-12-06; same headline, different content).  Both URL
dedup and `(headline, date)` dedup correctly preserve them as
distinct articles.  The earlier "URL-randomization broke dedup"
narrative was wrong: URL dedup didn't fail to catch chunk-overlap
duplicates -- there were no chunk-overlap duplicates to catch on
those tickers.  The corrected dedup key is still the right one to
standardize on (semantically defensible; URL has no stability
guarantee even if it happens to work as a dedup key for this run),
but the `headline_count` inflation we feared was largely imagined.

**What this prompt actually delivered.**

1. **Cleaner date ranges.**  AAPL had 4 long-tail outlier dates
   (2011-06-07, 2012-06-05, 2023-03-15, 2025-04-06).  NVDA, SPY,
   WMT, IWM, JPM, XOM, GLD: 1-6 outliers each, totaling **26 rows
   filtered** across 10 tickers (~0.05% of the corpus, matching the
   v3 spike's "~0.5%" estimate's lower bound).  Earliest dates
   collapse from 2011-2024 across tickers down to **2025-05-08 to
   2025-05-13** (depending on first-news-day per ticker), giving a
   tight, defensible 12-month window.
2. **Standardized dedup key.**  `dedup_method: "headline_date_v2"`
   recorded in the manifest per ticker.  Future operations on the
   corpus will use a stable key; the URL-method audit trail is
   preserved alongside.
3. **End-to-end downstream consumability validated.**  Both
   `sentiment.aggregator.build_sentiment_summary` and
   `sentiment.merger.load_news_sentiment` continue to auto-pick up
   `sentiment_{T}_real.csv` via the existing glob (filename
   unchanged).  AAPL aggregator returns 358 days over 2025-05-12 ->
   2026-05-04; merger returns 222 days.  No wiring changes needed
   downstream.

**Verified deltas on AAPL/NVDA/SPY/GLD (snapshotted before redup):**
on every matched in-window date, `headline_count` delta is exactly
**0** and `|sentiment_score|` delta max is **0.0001** (floating-
point noise from re-scoring the same articles).  The ONLY change
is dropping out-of-window dates entirely; in-window content is
bit-stable.

**Smoke tests run (6/6 pass).**

| # | scenario | result |
|---|---|---|
| 1 | `--dry-run` | per-ticker plan + ~39.7 min CPU estimate; manifest + TLT mtimes unchanged after run |
| 2 | `--ticker TLT` redup + before/after delta | TLT byte-identical (0 oow, identical url/hd dedup count); mtime updated; schema unchanged |
| 3 | restart `--ticker TLT` | 0.0s elapsed, TLT mtime unchanged on second invocation |
| 4 | locked-files regression | only `data/news_fetcher.py` shows changes (additions only from earlier prompts); 6 other locked files zero diff; scorer functions importable with unchanged docstrings |
| 5 | full 10-ticker run | 9 fresh tickers redupped (TLT skipped via manifest); 26 oow filtered; 2,967 daily rows total; 28.3 min wall clock |
| 6 | downstream loaders | aggregator + merger both auto-pickup; AAPL date_min cleaned to 2025-05-12 propagates end-to-end |

**Decisions.**  URL-method counts preserved in the manifest as
`n_articles_after_dedup` (existing field, untouched); new
`headline_date_v2` counts in `n_articles_after_redup`.  Top-level
`redup_run` field records the corrective pass once per run (never
overwritten on subsequent same-ticker re-runs since they short-
circuit on `dedup_method`).  No scoring-script modification; no
production-code changes.

**Pre-existing doc drifts STILL not fixed (separate prompt
candidate).**  PROJECT_STATE §2 mislabels `sentiment/aggregator.py`
as the news fetcher; `data/news_fetcher.py:158` carries the stale
"30 requests/minute" comment.

**Next-step queue (operator-driven).**  Real-mode `r3_baseline.py
--real` is now ready to run on a clean, date-bounded, dedup-
standardized corpus.  Real-mode `audit_oos_split.py --real` and
`audit_walkforward.py --real` follow once the first produces flat
+ kelly logs.

### 2026-05-04 r3_baseline.py --real bug fix (loader hardcoded `_demo`)

**Bug.**  `scripts/r3_baseline.py::_load_logs` (lines 123-129
pre-fix) read filenames as `backtest_{T}_demo{suffix}.csv` regardless
of the `demo` parameter passed to `main()`.  Per-ticker engine runs
under `--real` correctly wrote real-mode `backtest_{T}_kelly.csv`
files (verified: 30/37/49/78/64/49/46/71/72/21 rows on AAPL/NVDA/
JPM/XOM/UNH/WMT/IWM/GLD/TLT/SPY = 507 trades total, mtimes today),
but the headline-aggregation step kept reading `backtest_{T}_demo*
.csv` -- which were untouched (mtimes May 1 / Apr 25).  Result:
operator's `--real` run reported headline numbers identical to the
synthetic 2026-05-01 baseline, masking the actual real-mode behaviour.

**Prompt framing correction.**  The prompt premised "flat-loader
correct, Kelly-loader buggy".  Evidence shows BOTH `_load_logs`
calls (suffix=`""` and suffix=`"_kelly"`) shared the same hardcoded
`_demo` infix.  The operator's prior flat row of "283 signals,
-$16,918" was the *synthetic* flat row post-Option-A drift, not
real-mode flat -- demo_flat row counts sum to exactly 283, and
synthetic-mode regression below reproduces that exact line.  The
project's first real-mode validation hadn't actually surfaced
before this fix.

**Fix.**  Minimal patch at [scripts/r3_baseline.py](scripts/r3_baseline.py):
- `_load_logs` extended with `demo: bool = True` parameter; filename
  infix branches `"_demo" if demo else ""`
- Both call sites in `main()` updated: `_load_logs(tickers,
  suffix="", demo=demo)` and `_load_logs(tickers, suffix="_kelly",
  demo=demo)`
- Empty-corpus error messages now name the mode (`"No real-mode
  Kelly logs produced"` etc.)

No engine, signal, sizing, scorer, aggregator, merger, news_fetcher,
run_daily, backfill, score, redup script changes.

**Smoke tests (all pass).**

| # | scenario | result |
|---|---|---|
| 1 | post-fix `--real --skip-run` | flat row 2 / +$13.67 (only NVDA real-mode flat on disk); R3 row **507 signals / 295 trades / +$9,697 / Sharpe 1.17 / DD -$1,550 / PF 1.71 / WR 33.7%**; per-quintile P&L spans $77 (Q2) to $7,516 (Q1, n=231); R3 trade-counts table: BUY CALLS 295, BUY PUTS 0 (negative-Kelly filter holds, signal stays disabled in production) |
| 2 | post-fix `--skip-run` (synthetic) | flat 283/-$16,918, R3 872/360/+$5,836 -- byte-equivalent to PROJECT_STATE §7 post-Option-A drift snapshot |
| 3 | audit-script verification | `audit_oos_split.load_kelly_logs` and `load_flat_corpus`, plus the same in `audit_walkforward.py`, all already take `real_mode: bool = False` and both call sites in each `main()` pass `real_mode=real_mode` from parsed args (verified by `inspect.signature` + grep).  **No fix needed for audit scripts** -- the prior partial-coverage prompt's `--real` plumbing landed correctly |

**First real-mode R3 headline (with the bug fixed).**

| metric | real-mode | synthetic pin | drift |
|---|---:|---:|---:|
| total_pnl | +$9,697.01 | +$6,775.00 | +$2,922.01 |
| sharpe | +1.1732 | +0.4100 | +0.7632 |
| max_dd | -$1,550.01 | -$6,244.00 | +$4,693.99 |
| profit_factor | 1.7113 | 1.2700 | +0.4413 |
| n_trades | 295 | 357 | -62 |

Real-mode R3 outperforms the synthetic pin on every dimension --
roughly 3x the Sharpe, 4x lower drawdown, 1.5x the profit factor --
on 17% fewer taken trades.  This is in-sample on the real corpus
(the model and quintile edges were refit on it during this run).
**OOS audits are the next step before drawing edge conclusions.**
Synthetic comparisons stand only as methodology-validation; the
real-mode-vs-synthetic-pin DRIFT verdict is now meaningful and
informative rather than a synthetic-vs-synthetic mis-comparison.

**Real-mode flat corpus on disk is sparse.**  Only `backtest_NVDA.csv`
exists (3 lines / 2 data rows).  `r3_baseline.py` calls
`engine.run_backtest(t, ..., output_suffix="_kelly")` which writes
only the Kelly log, not a flat baseline.  To populate real-mode
flat for all tickers, the operator should run a real-mode flat
producer (e.g. `segregated_kelly_report.py --real` or equivalent
that calls `engine.run_backtest` without `output_suffix`) before
running the OOS audits.  Out of scope for this prompt.

**Per-signal Kelly stats from this run** (computed on the 2-row
real-mode flat corpus, so n is tiny):

| signal | n | WR | f* | tradable |
|---|---:|---:|---:|---|
| BUY CALLS | 2 | 50.00% | +0.1438 | False (n < min) |

These stats are not interpretable until the real-mode flat corpus
is fully populated.  The operator's earlier session reported
BUY CALLS f* +0.3242 / BUY PUTS f* -0.7300 -- those numbers were
computed against a stale or differently-sourced corpus and need
re-derivation once a clean real-mode flat baseline lands.

**Pre-existing doc drifts STILL not fixed.**  Same two as prior
entries: §2 architecture map mislabel; news_fetcher.py:158 stale
30/min comment.

**Next-step queue (operator-driven).**

1. Real-mode flat baseline producer (e.g. `segregated_kelly_report
   .py --real`) to populate `backtest_{T}.csv` for all 10 tickers
2. Re-run `r3_baseline.py --real` (full, not `--skip-run`) so the
   per-signal Kelly stats are re-derived against a complete
   real-mode flat corpus
3. Real-mode `audit_oos_split.py --real` -- already partial-coverage-
   tolerant, can run as soon as ≥1 ticker has both flat + kelly
   real-mode logs
4. Real-mode `audit_walkforward.py --real` -- same readiness
5. (Separate) Update r3_baseline.py drift pins to real-mode targets
   once a stable real-mode baseline is established; until then the
   DRIFT verdict against synthetic pins is informational

### 2026-05-04 -- Real-mode validation: full pipeline through OOS audits (session arc)

_Wrapper entry covering the day's arc.  The five entries above
this one document each sub-task individually; this consolidates
the arc and adds the operator-driven validation runs that landed
after the `r3_baseline.py --real` bug fix._

**Session timeline.**

- **Morning** -- Audit-script partial-coverage relaxation +
  follow-up audit of empty-frame access patterns (latent bug
  fixed in `audit_oos_split.per_ticker`).  See entry "Audit scripts
  -- partial-coverage relaxation + plumbing acknowledgement"
  above.
- **Late morning** -- CLAUDE.md locked-decision corrections for
  Option A (locked decisions #2 + #4 rewritten); project-purpose
  paragraph, file-naming bullet, and "How to run" section
  reorder.  Three small CLAUDE.md prompts.
- **Early afternoon** -- Finnhub recon (seven-question
  reconnaissance report), then chunked backfill orchestrator
  (`scripts/backfill_news_history.py` + `data/news_fetcher.py
  ::fetch_news_chunk`).  Smoke-tested on 3 AAPL chunks; full
  backfill run (operator-driven) produced 280 chunk CSVs / ~50,598
  raw articles across 10 tickers.
- **Mid-afternoon** -- FinBERT scoring orchestrator
  (`scripts/score_backfill_chunks.py`) consumed all 280 chunks
  via the existing `sentiment.scorer` primitives; ~32.8 min CPU
  wall clock; produced 10 `sentiment_{T}_real.csv` files.
- **Late afternoon** -- Backfill redup (`scripts/redup_backfill.py`)
  with `(headline_normalized, date)` dedup key + date-range filter
  `[2025-05-05, 2026-05-04]`.  Filtered 26 out-of-window outliers
  total; cleaned earliest dates from 2011-2024 down to 2025-05-08
  to 2025-05-13 per ticker.
- **Evening** -- `r3_baseline.py::_load_logs` bug fix (had
  hardcoded `_demo` infix regardless of mode); operator ran
  `segregated_kelly_report.py --real` to populate real-mode
  `backtest_{T}.csv` flat baselines, then `r3_baseline.py --real`
  with the fix to produce real-derived Kelly stats and quintile
  edges.  In-sample R3 result: **+$9,697 / Sharpe 1.17 / 295
  trades**.
- **Late evening** -- Operator ran `audit_oos_split.py --real`
  and `audit_walkforward.py --real`.  75/25 verdict PARTIAL
  (test-fold Sharpe +0.9790, P&L +$2,077).  Walk-forward verdict
  WINDOW-DEPENDENT (aggregate Sharpe +1.1369, 84% of rolling
  60-day windows positive).  Both reports written to
  `outputs/oos_audit_report_real.md` and
  `outputs/walkforward_audit_report_real.md`.

**Headline real-mode validation (full table in §7.0.0):**

| run | n_signals | n_trades | total P&L | Sharpe | max DD | PF | WR |
|---|---:|---:|---:|---:|---:|---:|---:|
| flat real-mode (1 contract) | 507 | 449 | −$18,983 | −0.90 | −$27,048 | 0.66 | 43.2% |
| **R3 real-mode** | 507 | 295 | **+$9,697** | **1.17** | −$1,550 | 1.71 | 33.7% |
| 75/25 OOS test fold | 125 | 67 | +$2,077 | 0.98 | −$960 | 1.63 | 31.2% |
| Walk-forward (134 refits) | 408 | 246 | +$7,786 | 1.14 | −$1,909 | 1.68 | 35.1% |

**Three caveats (also captured in §1).**  Single regime (~12
months bullish-equity); concentration (XOM+GLD+WMT carry 93% of
in-sample R3 P&L); single strategy (BUY CALLS only -- BUY PUTS,
SELL CALLS, SELL PUTS all blocked under real-data parameters).

**Key reframe vs 2026-04-27 honest-status update.**  The
synthetic-data Q5 inversion (the load-bearing finding behind
Option A) **does not reproduce on real data**: real-mode Q5 P&L
is +$2,180.56 in-sample and +$3,148.19 walk-forward (positive,
preserves Q5 > Q1 ordering).  The synthetic Q5 inversion was a
property of the synthetic generator's regime, not the
architecture.  Option A's reversal evaluation is now well-posed
and listed as §10.1 priority #4.

**Load-bearing artifacts on disk after this session:**

- `data/raw/news_{T}_chunk_*.csv` -- 280 chunk CSVs (~50,598 articles)
- `data/raw/sentiment_{T}_real.csv` -- 10 daily-aggregated
  sentiment CSVs (2,967 daily rows total, all in 2025-05-08 to
  2026-05-04 window post-redup)
- `data/raw/backtest_{T}.csv` -- 10 real-mode flat backtest logs
- `data/raw/backtest_{T}_kelly.csv` -- 10 real-mode Kelly logs
- `data/raw/kelly_stats.csv` -- real-derived per-signal Kelly
  fractions (BUY CALLS f* +0.2416 tradable; BUY PUTS f* −0.5224
  not tradable)
- `data/raw/quintile_edges.json` -- real-derived edges
  `[0.1807, 0.2946, 0.3905, 0.4877]`
- `data/raw/confidence_model.json` -- preserved on disk per Option
  A (`USE_LEARNED_MODEL=False`); not loaded by production
- `data/raw/backfill_manifest.json` + `scored_chunks_manifest.json`
  -- audit trail manifests
- `outputs/r3_production_baseline.md` -- real-mode (post-fix run)
- `outputs/oos_audit_report_real.md` -- 75/25 holdout, PARTIAL
- `outputs/walkforward_audit_report_real.md` -- 134-refit walk-
  forward, WINDOW-DEPENDENT

**Honest current state (architectural).**  Pipeline ingests real
news from a paid-tier-adjacent free API, scores it, sizes
positions, walks-forward through OOS audits, and produces a
positive-Sharpe headline -- end to end, deterministically, in
~33 min of CPU time on a 12-month real-news corpus.  The
remaining structural limitation is news-history depth, not
pipeline correctness.

**Next-session queue.**  See §10.1 -- five priorities re-ordered
post-validation.  #1 is the audit-report template fix (small);
#5 is multi-regime data extension (deferred / structural).

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

### 2026-05-05 Mechanism C: UNH BUY PUTS Kelly-filter bypass + Kelly-mode P&L

Added a research-probe `KELLY_FILTER_BYPASS` set at module level in
`signals/position_sizer.py` (currently `{("UNH", "BUY PUTS")}`),
threaded a `ticker: Optional[str] = None` kwarg into `size_trade()`,
and gated the negative-Kelly early-return so bypassed pairs skip the
filter and fall through to the uniform/quintile sizing path.  Engine
([backtest/engine.py:866](backtest/engine.py:866)) passes
`ticker=ticker` to the call site.  Total diff: 13 insertions / 2
deletions across the two files; all four sites confined to bypass
constant + signature kwarg + bypass branch + engine call.  Audit
scripts and `regime_comparison.py` not modified -- the kwarg's
`None` default keeps `(None, signal)` out of the bypass set so
audit refit paths and the regime A/B harness behave identically to
pre-prompt.  Locked decisions #1, #2, #4 untouched: spread builder
still applies 60-DTE / 0.25Δ for BEAR_PUT_DEBIT regardless of
sizing, Option A uniform sizing path is what runs after bypass,
legacy tiered confidence is upstream of the filter.  Reversal: set
`KELLY_FILTER_BYPASS = set()`.

Re-ran `r3_baseline.py --real` post-bypass.  `data/raw/kelly_stats.csv`,
`confidence_model.json`, `quintile_edges.json` byte-identical
pre/post (md5 unchanged) -- bypass does not leak into stats
computation.  Other 9 tickers' BUY PUTS rows still
`contracts=0, kelly_reason="negative_kelly_BUY PUTS"`
(spot-checked AAPL/NVDA/JPM).  Real-mode universe Kelly headline:
+$13,906 / Sharpe 0.91 / 314 trades (vs the prior +$9,697 / 1.17
/ 295 baseline -- the +$4,209 delta is the UNH BUY PUTS contribution
plus a one-day yfinance refresh on `expiration` exits).

UNH BUY PUTS Kelly-mode cohort: 20 of 21 signal rows now
`contracts > 0` (1 blocked by `portfolio_risk_cap`); 14 "ok" sized
+ 6 "floor_over_cap" reflecting MIN_CONTRACTS=1 over the
$380/trade UNIFORM_PER_TRADE_FRAC budget at $100k notional.  Stats:
**total +$3,994.40 / mean +$199.72 / median +$792.80 / std $913.20
/ win rate 0.55 / profit factor 1.60 / Sharpe +1.55 / max DD
-$4,575**.  Comparison to Path 1 1-contract flat baseline (+$3,255
/ 1.20 / 1.44, n=21): Kelly cohort posts +$739 higher total because
the cap-blocked entry was a loser, not because contract counts
differ (20 of 21 took at floor=1, identical per-trade pricing).
Verdict bucket: **SURVIVES** -- Kelly-mode numbers strengthen the
Path 1 finding rather than diluting it.  Regime split caveat
unchanged: profitable Jun-Aug / Oct-Nov 2025 cluster + losing
Nov 2025 - Mar 2026 cluster on time-stops as UNH rebounded.
Sample-size caveat unchanged (n=20).  Production decision (re-enable
BUY PUTS for UNH on a permanent basis vs treat as research probe
only) is the next session's question, conditional on a
walk-forward-style stability check.

### 2026-05-05 Sector-decay --real plumbing + Healthcare BUY PUTS read

`scripts/sector_decay.py` previously hardcoded `backtest_{T}_demo.csv`
in `_load_flat_logs_for` and the output filename
`outputs/sector_decay_analysis.md`.  Added `--real` (action="store_true")
matching the `r3_baseline.py` / `audit_oos_split.py` idiom, threaded
`real_mode` through `main()` into `_load_flat_logs_for(tickers,
real_mode)` (path-string ternary swap to `backtest_{T}.csv`), branched
the report path to `outputs/sector_decay_analysis_real.md` so demo
runs no longer get clobbered, and added a stderr warning when a flat
log is missing.  Diff: 11 insertions / 6 deletions, +5 net, confined
to argparse, `_load_flat_logs_for` signature/path, `main()` threading,
output-path branch.  `signals/signal_decay.py` byte-identical (price
loader is yfinance-backed and mode-agnostic).

Real-mode 10-ticker sector-decay finding (motivated by §10.1 #3,
Healthcare-only BUY PUTS re-enable hypothesis): at the 20d horizon
**Healthcare is the only sector with positive BUY PUTS mean directional
return (+2.67% on n=21)**.  All other sectors are negative at 20d --
BroadMarket -3.21%/n=9, Commodity -6.42%/n=8, ConsumerStaples
-5.91%/n=4, Energy -3.23%/n=7, Financials -1.86%/n=2, FixedIncome
-0.46%/n=57, SmallCapEquity -4.55%/n=37, Technology -1.12%/n=5.
Healthcare BUY PUTS is positive at all three crosstab horizons (5d
+1.27%, 10d +4.34%, 20d +2.67%) on n=21, so the signal is coherent
across horizons rather than a one-bar spike.  Sample size (n=21) is
above the small-sample floor but modest -- the Healthcare-only
re-enable hypothesis SURVIVES the underlying-direction sector-decay
test on real data; whether it survives the option-P&L conversion
(60 DTE / 0.25Δ structure + friction) is the separate follow-up
question.  Production sizing untouched -- BUY PUTS remains zero-
contracted under the current Kelly_f=-0.0567 universe-wide gate.
Report: `outputs/sector_decay_analysis_real.md`.

### 2026-05-05 Audit-report prose parameterised by mode (DEMO vs REAL)

`scripts/audit_oos_split.py` and `scripts/audit_walkforward.py`
report-builders previously hardcoded synthetic-baseline prose
(`+$6,775 / Sharpe 0.41 / 357 trades`, `is_synthetic=True`,
synthetic 75/25 verdict references, `+0.4103` / `-0.5977` Sharpe
constants in `compose_verdict`) so the four output markdowns
showed correct numerical tables but mode-mismatched narrative
when run with `--real`.  Added a `_baseline_phrases(mode_label)`
lookup near the top of each script returning mode-conditional
strings (baseline P&L/Sharpe/trade-count, prior-OOS verdict
phrase, 75/25-OOS column footnote, corpus caveat,
single-realisation caveat); threaded `mode_label` and the
phrase dict through `build_report` -> `_compose_verdict_paragraph`
/ `compose_verdict`; replaced hardcoded Sharpe constants in the
walk-forward verdict body with dynamic `{sh_in:+.4f}` /
`OOS_75_25['sharpe']` substitutions; gated AAPL stop-cluster
prose (synthetic-only `aapl_stop_diagnosis.md` reference) behind
`mode_label == "DEMO"` with a real-mode replacement that drops
the synthetic anchor.  Regenerated all four reports
(`outputs/oos_audit_report.md`, `outputs/oos_audit_report_real.md`,
`outputs/walkforward_audit_report.md`,
`outputs/walkforward_audit_report_real.md`); validated via grep
that real-mode reports contain no `+$6,775` / `Sharpe 0.41` /
`357 trades` / `is_synthetic=True` hits and synthetic reports
contain no `+$9,697` / `Sharpe 1.17` / `295 trades` hits.
No engine, signal, sizing, or config code touched;
re-run reproduces tables identical to the pre-fix versions for
each mode.

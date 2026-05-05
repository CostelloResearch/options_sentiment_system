# CLAUDE.md

Reference guide for Claude Code sessions.  **Stable** — edit only when core
conventions or locked decisions change.  For the living state of the project
(latest KPIs, open issues, next planned work), see
[PROJECT_STATE.md](PROJECT_STATE.md).

---

## Project purpose

End-to-end options-trading research pipeline: ingests news + SEC sentiment,
combines it with IV Rank to emit a directional signal, translates each signal
into a vertical-spread ticket (BS-fair-value pricing + friction), sizes the
position with a uniform per-trade fraction (0.38%) under a global 6%
portfolio cap (Option A, 2026-05-01; quintile-by-confidence and 0.25×
fractional Kelly with strategy-segregated buckets retained behind flags
for A/B), and backtests over 5 years of daily bars.  The system is
designed to be interview-defensible: every threshold, formula, and
abstraction is justified in code comments and validated by decay and OOS
audit studies.  Real-mode validation completed 2026-05-04 with both OOS
audits returning positive verdicts (PARTIAL on 75/25 chronological
holdout, WINDOW-DEPENDENT on walk-forward) on a 12-month real-news
corpus, with concentration and single-regime caveats documented in
PROJECT_STATE §1 and §10.

---

## Codebase navigation

```
config.py                          universe + thresholds + API keys
main.py                            CLI orchestrator
sentiment/
  aggregator.py                    news ingestion (Finnhub)
  scorer.py                        per-headline sentiment scoring
  sec_scorer.py                    SEC 10-K/10-Q/8-K filing sentiment
  merger.py                        news + SEC → combined_sentiment_{T}.csv
signals/
  signal_engine.py                 sentiment + IV → directional signal
  spread_builder.py                signal → vertical spread (pricing, exits)
  position_sizer.py                Kelly math + strategy-segregated buckets
  confidence_model.py              hand-rolled IRLS logistic regression
  signal_decay.py                  per-segment horizon decay study
  earnings_filter.py               earnings-window + IV_CRUSH override
backtest/
  engine.py                        historical sim (BS synthetic prices)
  metrics.py                       Sharpe / DD / profit factor / win rate
scripts/
  run_daily.py                     nightly signal emit
  run_kelly_study.py               flat → stats → Kelly → decay
  segregated_kelly_report.py       flagship: segregated-bucket Kelly report
  fit_confidence_model.py          refit logistic model on latest corpus
  put_structure_study.py           DTE × short-delta sweep for BUY PUTS
  check_pipeline.py                data-availability sanity check
dashboard/                         Plotly HTML dashboard (per-ticker + overview)
data/raw/                          CSVs + trained model JSON
outputs/                           study markdowns
```

**Design invariant:** the live signal path and the backtest path share the
SAME sizing / pricing / exit-rule code.  If you change a rule, change it in
one place and both paths pick it up.

---

## Core conventions

- **Python:** use `.venv/Scripts/python.exe` on Windows — the bare `python`
  hits a system interpreter without numpy.
- **Data lives under `data/raw/`.** Never write derived state to the
  project root.  Study outputs go to `outputs/`.
- **File naming:**
  - `sentiment_{TICKER}_{YYYY-MM-DD}.csv` — daily news sentiment
  - `sec_sentiment_{TICKER}.csv` — SEC filings
  - `combined_sentiment_{TICKER}.csv` — merger output
  - `backtest_{TICKER}_demo.csv` — flat-sizing trade log
  - `backtest_{TICKER}_demo_kelly.csv` — Kelly-sizing trade log
  - `kelly_stats.csv`, `confidence_model.json`, `quintile_edges.json` — fitted model artifacts.  Note: under Option A (2026-05-01), `confidence_model.json` and `quintile_edges.json` are preserved on disk for reversal but not loaded — see locked decisions #2 and #4.
  - Study markdowns: `outputs/{study_name}.md`
- **Config pattern:** user-level tuning (tickers, signal thresholds) lives
  in `config.py`.  Algorithmic constants (Kelly fraction, delta targets,
  DTE, friction, strategy-bucket fractions) live at the top of the module
  that uses them, with a comment explaining the choice.  Don't relocate
  these to `config.py` — keeping them next to the code that reads them
  makes the rationale legible.
- **Universe taxonomy:** `config.py` exports `TICKERS`,
  `SECTOR_MAP`, `ASSET_CLASS`, and `ETF_TICKERS`.  Sector/asset-class
  segmentation is consumed by `scripts/sector_decay.py`; ETF detection
  short-circuits the SEC fetch/score pipeline (no 10-K/10-Q/8-K to score
  for SPY/IWM/GLD/TLT, so they fall back to news-only sentiment without
  erroring).  Keep these four exports in sync when the universe changes.
- **No emojis in source or docs.**
- **Every code-change session ends with a PROJECT_STATE §12 entry.**
  Even a two-sentence note.  PROJECT_STATE is the cold-start
  reference; if a change isn't there, the next session has no record
  of it.  Documentation-only sessions (no code touched) are exempt.
- **Comments justify the *why*.** If a constant has a number, it has a
  docstring explaining why it's that number.  Match this style in new code.
- **No scikit-learn.** The logistic model is hand-rolled IRLS on top of
  numpy + scipy (interview-defensibility).  Don't pull in sklearn.

---

## Locked design decisions

These are load-bearing — changing any of them without discussion will
regress a validated result.  If you think one needs to change, flag it in
conversation first.

1. **BUY PUTS uses 60 DTE and 0.25Δ short leg** _(structure preserved;
   signal currently disabled on the 10-ticker universe by negative-Kelly
   filter)_.  Validated by `scripts/put_structure_study.py` on the
   5-ticker corpus: Variant B turned the same signal cohort from +$8,396
   (default 35 DTE / 0.30Δ) to +$32,457 P&L.  Overrides live in
   `backtest/engine.py` as `_PER_STRATEGY_DTE["BEAR_PUT_DEBIT"] = 60` and
   `_PER_STRATEGY_SHORT_DELTA["BEAR_PUT_DEBIT"] = 0.25`.  **Do not revert
   the structure overrides.**  After the 2026-04-25 universe rebuild,
   BUY PUTS Kelly_f went from +0.2345 (5-ticker) to −0.0567 (10-ticker)
   so production no longer trades the signal -- but the override stays
   in code for the day BUY PUTS gets re-enabled (e.g. Healthcare-only;
   see PROJECT_STATE §10.2.A).  See PROJECT_STATE §7.0.3 for the
   per-sector decay that flagged BUY PUTS as tech-concentrated.

2. **Production sizing is UNIFORM per-trade fractional sizing (Option
   A, 2026-05-01).**  `position_sizer.USE_QUINTILE_SIZING = False` and
   `USE_STRATEGY_BUCKETS = False`; `size_trade()` returns
   `UNIFORM_PER_TRADE_FRAC = 0.0038` per accepted trade (the implied
   mean of the prior `QUINTILE_FRAC` table) against the unchanged
   global 6% portfolio cap.  Adopted after the OOS audits (75/25 +
   walk-forward, see PROJECT_STATE §7 head note + §6 Option A entry)
   showed quintile sizing was an exposure amplifier rather than a
   differential-edge extractor: Q5 inverted +$3,674 in-sample to
   −$5,685 walk-forward, and disabling quintile sizing cut walk-forward
   max DD ~30% (−$15,312 → −$10,705) while leaving Sharpe statistically
   equivalent.  **Status: provisional pending real-data validation in
   mid-May 2026.**  Reversal path: set `USE_QUINTILE_SIZING = True` in
   `position_sizer.py` (paired with the locked-decision-#4 reversal).
   The JSON artifact at `data/raw/quintile_edges.json` is preserved on
   disk for instant reversal — no retraining required.  Legacy
   quintile sizing and segregated-bucket Kelly are both retained
   behind their respective flags for A/B comparison only.  Full Kelly
   is too variance-heavy on finite samples; we also don't use it.

3. **`STRATEGY_BUCKETS` is legacy-only.**  Values (3.00 / 1.50 / 0.75 /
   0.75) and the `sum == MAX_PORTFOLIO_RISK` invariant are kept so
   `USE_STRATEGY_BUCKETS=True` still works for A/B comparisons against
   historical runs.  Don't wire new production features to this dict.

4. **Confidence uses the legacy tiered formula (Option A, 2026-05-01).**
   `confidence_model.USE_LEARNED_MODEL = False`; a one-line gate at the
   top of `load_model()` returns `None` regardless of whether
   `data/raw/confidence_model.json` is on disk.  Both `signal_engine.py`
   and `backtest/engine.py` therefore fall through to their legacy
   tiered-confidence formulas on every call — no call-site changes
   needed.  Paired with locked decision #2: the audit chain (see
   PROJECT_STATE §6 Option A entry) found the learned model's
   "highest confidence" bucket was systematically anti-predictive on
   walk-forward data, and the quintile sizing that amplified those
   bets was the active loss mechanism.  **Status: provisional, reverses
   together with #2 if real-data validation favours the learned-model +
   quintile path.**  Reversal path: set `USE_LEARNED_MODEL = True` in
   `confidence_model.py`.  The JSON artifact at
   `data/raw/confidence_model.json` is preserved on disk for instant
   reversal — no retraining required.

5. **SELL CALLS is DISABLED by the decay study** (no horizon produced mean
   > 0 across 61 trades).  Its bucket is reserved but unused.  Don't
   re-enable without fresh decay data.

6. **Backtest Kelly sizes against a $100k paper account
   (`KELLY_BACKTEST_NOTIONAL`), live trading against $10k
   (`ACCOUNT_NOTIONAL`).**  They're decoupled on purpose — the small live
   account can't hold multiple concurrent 1-contract spreads per bucket,
   which would make the segregation study meaningless.  Keep them separate.

7. **`backtest/engine.py` flat sizing floors at 1 contract regardless of
   `RISK_PER_TRADE_FRAC`.**  The flat path is measuring signal edge, not
   capital deployment.  The Kelly path is the one that respects the caps.

---

## How to run

### R3 production baseline (flagship)

```bash
.venv/Scripts/python.exe scripts/r3_baseline.py
# Reuse existing flat + kelly logs on disk:
.venv/Scripts/python.exe scripts/r3_baseline.py --skip-run
# Real sentiment instead of synthetic demo (requires backfill on disk):
.venv/Scripts/python.exe scripts/r3_baseline.py --real
```

Writes `outputs/r3_production_baseline.md` plus per-ticker backtest CSVs
under `data/raw/`.  Drift-checks against pinned baselines so any change
to engine / sizing / signal code surfaces as a numeric diff in the
report header.  Under Option A (2026-05-01) the same script reproduces
the uniform-sizing production line; the in-code drift pins are updated
when the production regime changes.

### Legacy segregated-Kelly study (A/B only)

```bash
.venv/Scripts/python.exe scripts/segregated_kelly_report.py
# Skip the 5-ticker flat run, reuse logs on disk:
.venv/Scripts/python.exe scripts/segregated_kelly_report.py --skip-flat
# Real sentiment instead of synthetic demo (requires backfill on disk):
.venv/Scripts/python.exe scripts/segregated_kelly_report.py --real
```

Writes `outputs/segregated_kelly_report.md` plus per-ticker backtest CSVs
under `data/raw/`.  Retained for A/B comparison against the prior
segregated-bucket regime — set `position_sizer.USE_STRATEGY_BUCKETS = True`
to reproduce the historical numbers.  Not the current production
flagship (see locked decisions #2 and #3).

### Classic flat-vs-Kelly + decay study

```bash
.venv/Scripts/python.exe scripts/run_kelly_study.py
```

Writes `outputs/kelly_study_summary.md` and
`outputs/signal_decay_analysis.md`.

### Universe diversification audit + per-sector decay

```bash
.venv/Scripts/python.exe scripts/correlation_matrix.py
.venv/Scripts/python.exe scripts/sector_decay.py
```

`correlation_matrix.py` writes `outputs/correlation_matrix.md` (60d/252d
correlation tables, flagged pairs, eigenvalue-entropy `N_eff`).
`sector_decay.py` writes `outputs/sector_decay_analysis.md` (per-sector
and per-asset-class decay, plus a sector × signal cross-tab) -- this is
the test for whether a signal's edge generalises across sectors or is
universe-concentrated.

### Versioned logistic refit (don't overwrite production model)

```bash
.venv/Scripts/python.exe scripts/refit_confidence_v2.py
```

Saves to `data/raw/confidence_model_<tag>.json` (default tag
`v2_10t`).  The production loader in `signals/confidence_model.py`
always reads the unversioned `confidence_model.json`; promote a
versioned fit by overwrite/rename when ready.

### Refit the logistic confidence model

```bash
.venv/Scripts/python.exe scripts/fit_confidence_model.py
```

Reads the current flat corpus, writes
`data/raw/confidence_model.json`.  Run this after the flat backtest
changes materially.

### Nightly pipeline (live path)

```bash
.venv/Scripts/python.exe scripts/run_daily.py
```

Fetches news + options data, runs the signal engine, emits per-ticker signal
cards.  Scheduled via `scripts/setup_scheduler.ps1` on Windows.

### Dashboard

```bash
# Per-ticker report_{TICKER}.html for every config.TICKERS entry
# PLUS the cross-universe overview.html (asset-class P&L strip on top
# + small-multiples grid grouped by asset class then sector below)
.venv/Scripts/python.exe main.py --dashboard --demo

# Overview only (skips the 10 per-ticker files)
.venv/Scripts/python.exe main.py --dashboard-overview-only --demo
```

The Plotly figures are written to `dashboard/report_{TICKER}.html` and
`dashboard/overview.html` -- self-contained, open offline in any
browser.  Sentiment panel reads `combined_sentiment_{T}.csv` (the
Path-A 3-stream merger output) when present; falls back to raw
`sentiment_{T}_*.csv` with a stdout warning otherwise.  Live signals
from `signals_{T}.csv` are overlaid as outlined markers on the price
panel alongside the backtest signals (filled markers).  Drop `--demo`
for real mode.

### Sanity check

```bash
.venv/Scripts/python.exe scripts/check_pipeline.py
```

Verifies all required CSVs and models are on disk.  Useful first step when
a fresh clone doesn't run.

---

## Where to go next

- **Latest KPIs, open issues, next planned upgrade:**
  [PROJECT_STATE.md](PROJECT_STATE.md) — living document, updated as state
  changes.
- **Per-module rationale and math:** docstrings at the top of every
  `signals/*.py` and `backtest/*.py` file.
- **Study interpretations:** `outputs/*.md`.

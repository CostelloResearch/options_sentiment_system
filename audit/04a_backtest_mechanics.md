# Stage 4a -- Backtest mechanics, cost model, reproduction, and pinned snapshot

Audit date 2026-10-10. I read the prior files first (rule 7): AUDIT_RULES, 01_inventory, 02_data, 03_signals. Earlier findings are cited by ID. Code ran **only** in the isolated copies under `audit/artifacts/stage4/`. Network was used only for yfinance (this stage permits it); Finnhub, `requests` and any FinBERT/torch import were blocked at runtime by the harness.

**Command legend.** `$S` = `audit/artifacts/stage4`; `PY` = `.venv/Scripts/python.exe -I`. Every run's full stdout/stderr, with the exact command on line 1, is in `$S/logs/`.

| id | exact command | log |
|---|---|---|
| U1 | `PY $S/make_copies.py "C:/Claude Code Project/options-sentiment-system"` (git archive HEAD into head_src via tarfile; WT copy excluding .git, .venv, audit, __pycache__, .claude, logs, dashboard/*.html; data/raw copied into both; byte verification) | make_copies.log |
| U2 | for each of the 6 modified files: `git show HEAD:$p \| sha256sum` vs `tr -d '\r' < $S/head_src/$p \| sha256sum` | stdout (section 6.0) |
| E1 | `PY $S/yf_record_replay.py --mode record --snapshot $S/yf_snapshot --earnings AAPL NVDA JPM XOM UNH WMT` (1st attempt failed: lxml missing / host refused; 2nd attempt succeeded via fallback) | earnings_record.log, earnings_record2.log |
| D1 | `PY $S/yf_record_replay.py --mode replay --copy $S/wt_src --snapshot $S/yf_snapshot --script scripts/{audit_walkforward,audit_oos_split}.py -- --real` (on the **original** on-disk logs) | d1_*.log |
| A | `PY $S/yf_record_replay.py --mode record --copy $S/head_src --snapshot $S/yf_snapshot --script scripts/segregated_kelly_report.py -- --real --skip-kelly`, then `... --script scripts/r3_baseline.py -- --real` | a_*.log |
| B | the same two commands with `--mode replay --copy $S/wt_src` | b_*.log |
| C | head_src `data/raw` and `outputs/` restored from the repo / `git archive HEAD outputs`, then the same two commands with `--mode replay --copy $S/head_src` | c_*.log |
| D2 | `cp $S/runs/a/raw/backtest_*.csv $S/wt_src/data/raw/`, then the D1 commands again | d2_*.log |
| X1-X3 | `PY $S/diff_trades.py data/raw $S/runs/a/raw ""` ; `... $S/runs/b/raw "_kelly"` ; `... $S/runs/a/raw "_kelly" --drop-unh-bp-orig` | diff_flat_a.txt, diff_kelly_wt_b.txt, diff_kelly_head_a_proxy.txt |
| X4 | inline per-ticker attribution (`m.groupby('ticker')`: strike changes, truncated trades, P&L delta) | stdout (section 6.2) |

Run outputs are saved under `$S/runs/{a,b,c,d1,d2}/`.

**Arguments used.** PROJECT_STATE.md:2599-2605 records the HEAD real result as `segregated_kelly_report.py --real` (writes the flat `backtest_{T}.csv`) followed by `r3_baseline.py --real`. `r3_baseline.py` reads flat logs from disk and does **not** regenerate them (r3_baseline.py:274-283). So the flat producer was run first, with `--skip-kelly` (its Kelly pass is superseded by r3_baseline). Defaults: `--lookback-days 500` (segregated_kelly_report.py:505, r3_baseline.py:462), so `period="5y"` (engine.py:590); tickers = config.TICKERS.

---

## 1. Engine architecture

| item | finding | evidence |
|---|---|---|
| Loop structure | **Sequential per-ticker runs**: each script loops `for t in tickers: run_backtest(t, ...)`. Each run is independent; open positions, cap usage and logs are per ticker. There is no portfolio-level simulation. | segregated_kelly_report.py:305-307; r3_baseline.py:295-298; engine.py:692-698 |
| Bar frequency | Daily yfinance bars (adjusted closes only; no open/high/low used) | engine.py:389-399 |
| Decision timing | On each date d in the inner join of sentiment and price: sentiment = FinBERT mean of articles dated d in ET local time (all hours, D2-3); IV rank and sigma = RV30 through the close of d; **entry at the close of d** (`S_entry = close[d]`, spread priced with T = DTE/365 from d) | engine.py:609-611, 704-708, 791; 02 section 2.2 |
| Mark-to-market | Daily, at each subsequent close: BS value of both legs with the RV30 of that day as IV for both legs; exits checked in order stop, then target, then time stop, then expiration | spread_builder.py:948-1029; engine.py:506-515 |
| Data end | If prices end before expiry, the last available close is treated as expiration (`exit_reason="expiration"` with time value remaining) | engine.py:492-504; spread_builder.py:1032-1042 |
| Re-entry / overlap | A new trade can open every signal day while earlier ones are still open (same ticker), subject only to the per-ticker 6% cap in the Kelly path (D3-1) | engine.py:774-779, 924-928 |

## 2. Execution and cost model (BULL_CALL_DEBIT, the only traded structure)

| item | status | path:line | bias on BULL_CALL_DEBIT P&L | reason |
|---|---|---|---|---|
| Fill basis | simplified: BS fair value with sigma = RV30, no quotes | engine.py:291-292 | ambiguous | Synthetic prices can sit anywhere relative to real bid/ask [INFERRED] |
| Entry friction | implemented: long x 1.015, short x 0.985 | engine.py:294-295; spread_builder.py:109 | penalizes (correctly) | Charges about half a typical spread at entry [INFERRED] |
| Exit friction | **absent**: exits at BS fair value | spread_builder.py:1036-1048 | **flatters** | A real close pays the bid/ask again [INFERRED] |
| Slippage | absent (only the fixed % friction) | -- | flatters | No size/liquidity impact [INFERRED] |
| Commissions | absent | -- | flatters | 2 legs x 2 sides per trade not charged [INFERRED] |
| Bid-ask modeling | absent in backtest (live `build_spread` has bid-ask/OI filters, unused) | spread_builder.py:398-418 | flatters | Wide or illiquid strikes priced at fair value [INFERRED] |
| Early exercise / assignment | absent (European BS) | spread_builder.py:132-180 | flatters (slightly) | Short call assignment risk near ex-dividend ignored [INFERRED] |
| Expiry settlement | simplified: BS value at T=0 = intrinsic at the last close; truncated trades valued with time value left | spread_builder.py:1032-1046; engine.py:492-504 | ambiguous | Pin/settlement risk ignored; truncation marks open trades as closed [INFERRED] |
| Margin (credit spreads) | absent; n/a in practice (credit spreads never accepted, 03 section 9) | -- | n/a | -- |
| Capital base | flat: $10k x 2% budget, 1-contract floor; Kelly: $100k x 0.38%, floor 1; per-ticker 6% cap; no cash accounting, no compounding, no financing | engine.py:105, 341-347; position_sizer.py:574-613 | ambiguous | Totals are sums of independent per-ticker books (D3-1) [INFERRED] |
| Pricing sigma | RV30 for both legs: no skew, no term structure, no vol risk premium | engine.py:507; spread_builder.py:982 | ambiguous, likely flatters debit buyers | RV < IV on average makes debit spreads cheaper than in the market [INFERRED] |
| Dividends | absent (no q in BS); prices back-adjusted | engine.py:390; 02 section 2.4 | flatters calls slightly | Calls priced without the dividend drag [INFERRED] |
| Risk-free rate | constant 4.5% | spread_builder.py:83 | ambiguous | Small effect on 35-DTE debit spreads [INFERRED] |
| Same-day exits | possible: stop/target are checked on the entry day (only the time stop skips it) | spread_builder.py:995-1023 | penalizes (stop) / flatters (target) | Entry friction makes day-0 P&L negative, so day-0 stops are favoured [INFERRED] |
| Strike grid | $5 steps for every ticker; width rounded onto it (D3-3) | engine.py:94, 197-199 | ambiguous | Sub-$100 tickers get width 0 (rejected) or $5 [INFERRED] |

## 3. Synthetic generator verdict (engine.py:443-472, not run)

| input | path:line | class | reason |
|---|---|---|---|
| `ticker` (seed = sum of ord) | engine.py:445-446 | INDEPENDENT | Deterministic per name, unrelated to prices |
| `days` (= lookback_days) | engine.py:443, 448 | INDEPENDENT | Length only |
| `datetime.date.today()` (end of the date grid) | engine.py:448 | INDEPENDENT (non-reproducible) | Moves the noise path against real price dates on every run day (D7) |
| shocks `rng.uniform(-0.18, 0.18)`, AR(1) 0.90, clip [-1, 1] | engine.py:453-454 | INDEPENDENT | Pure PRNG noise |
| `headline_count = randint(5, 40)`; bullish/bearish % from score + noise | engine.py:456-459 | INDEPENDENT | Derived from the noise score |

**Verdict: INDEPENDENT.** No price, return, or outcome enters the generator, so it is not circular. In demo mode, synthetic sentiment is random noise. Demo P&L therefore reflects the IV-rank regime filter, the structures, and random sentiment luck aligned to a date grid that shifts daily. It is not evidence of a sentiment edge [INFERRED from the code].

## 4. Sample design

| item | finding | evidence |
|---|---|---|
| Real-mode date range | Entries 2025-05-08 to 2026-05-04 (sentiment `_real` window); prices 5y back from the run date | 02 section 4; snapshot manifest (2021-10-11 to 2026-10-09) |
| Tickers | 10 static (D2-8); trades per ticker AAPL 29 ... XOM 77 (507 signal days) | [RAN X4] |
| Regime coverage | One roughly 12-month window, during which SPY entries ranged $559 to $714 (rising market). No 2008, 2020 or 2022 in the signal sample. The 2022 drawdown is only in the IV-rank burn-in (prices from 2021-10). | 03 section 2 T2 S_entry; 02 section 5 |
| Strategy actually traded | BUY CALLS only in Kelly runs (HEAD); flat also trades BUY PUTS | 03 section 7, 10c |
| IS / OOS | 75/25 by entry date, cutoff 2025-12-22; train label boundary contamination (D3-8) | 03 section 10b |
| Walk-forward | Refit on `exit_date < T`, warmup 50, refit on growth; see 03 section 10c | 03 section 10c |
| Overlap of trades | Up to 35-60 day holds opened daily, so heavily overlapping, non-independent observations | engine.py:774-779, 924-928 |

## 5. Metrics methodology

| implementation | return unit | annualization | rf | ordering / equity curve | issues |
|---|---|---|---|---|---|
| `backtest/metrics.sharpe_ratio` | per-share `pnl` per trade | x sqrt(252 / HOLD_DAYS=5) | `risk_free_daily=0` default | per-trade series; `max_drawdown` = cumsum of per-trade pnl in log order | Holds are 1-60 days, not 5 (D9); per-share P&L mixes contract sizes |
| `r3_baseline.headline` (r3_baseline.py:159-175) | `pnl_total` $ over **all signal rows** (rejected rows count as 0) | x sqrt(252/5) | 0 | `cum = pnl.cumsum()` in **concatenation order** (`_load_logs` stacks tickers, r3_baseline.py:123-136; no sort) | Sharpe and win rate include about 200 zero rows (n_signals 507 vs 298 taken), which dilutes the mean and std. Drawdown runs ticker-block by ticker-block, so it is **not a time-ordered drawdown**. P&L is booked in entry order, not exit. |
| `audit_oos_split.headline` / `audit_walkforward.headline` (:193-209) | same as r3 | `SHARPE_ANN = sqrt(252/5)` (:60, :50) | 0 | fold frames sorted by entry_date | Same zero-row inclusion; P&L booked at entry date |
| `decompose_time_ticker.SHARPE_ANN` (:49) | same | sqrt(252/5) | 0 | by month | research only |
| Equity curve | **None exists.** There is no daily mark-to-market portfolio equity anywhere; all Sharpe and DD numbers are per-trade-row statistics. | -- | -- | -- | |

Methodological errors: (1) the sqrt(252/5) annualization does not match the actual holding period or overlap (D9); (2) zero rows are included in Sharpe and win rate; (3) drawdown is not computed in time order in r3_baseline (D4a-2); (4) no risk-free rate or capital base, so Sharpe is on dollar P&L, not returns.

## 6. Reproduction

### 6.0 Copy verification

- wt_src: 79 source files byte-identical to the repo working tree; data/raw 1,693 files identical in both copies [RAN U1].
- head_src: the 6 modified files equal `git show HEAD:<path>` after CR stripping (`core.autocrlf=true`, so `git archive` emits CRLF); all 6 sha256 prefixes match. `KELLY_FILTER_BYPASS` occurs 0 times in head_src and 3 times in wt_src [RAN U2].

### 6.1 Reproduction table

| result | config | command | reported | reproduced (record) | replay | match? | diagnosis |
|---|---|---|---|---|---|---|---|
| Flat real | HEAD | A (segregated `--skip-kelly`) | 449 accepted / -$18,983 / Sharpe -0.90 (PROJECT_STATE.md:686-691) | **452 / -$19,743.51 / -0.9201** (507 signals) | C: identical; B: identical | No (close) | Price revision (D2-15) + data-end truncation; no code difference (6.2) |
| R3 real | HEAD | A (r3_baseline `--real`) | 295 / +$9,697 / 1.17 | **298 / +$10,216.57 / 1.2812** (DD -$1,396) | C: identical | No (close) | Same, through flat; Kelly stats now BC 298 f* +0.2431, BP 154 f* -0.7536 (vs +0.2416 / -0.5224) |
| R3 real + bypass | WT | B | 314 / +$13,906 / 0.908 | **315 / +$13,183.91 / 0.8585** (replay; DD -$5,362) | -- | No (close) | Same attribution (X2) |
| OOS real, test fold | WT (= HEAD logic, 03 T4) | D1 (original logs) | +$2,077 / 0.98 | **+$2,077.04 / 0.9790** (67 trades) | D2 (reproduced logs): **+$2,969.68 / 1.3590** (68) | **D1 exact** | The audit is a deterministic function of the logs on disk. D1's in-sample column now reads +$13,906 / 0.9084 because the on-disk `_kelly` logs are post-bypass (03 section 11). |
| Walk-forward real | WT | D1 | 246 / +$7,786 / 1.14 | **246 / +$7,786.22 / 1.1369** | D2: **249 / +$8,340.87 / 1.2739**; verdict changes to **"GENERALIZES UNDER WALK-FORWARD"** (from WINDOW-DEPENDENT) | **D1 exact** | The verdict is sensitive to the price-download date |

### 6.2 Trade-level diff (reproduced run A/B vs on-disk originals) [RAN X1-X4]

| comparison | key matches | identical (signal, strategy, strikes, accepted) | differing | missing/new | P&L orig to repro | delta |
|---|---|---|---|---|---|---|
| flat: disk `backtest_{T}.csv` vs A | 507 / 507 | 322 | 185 | 0 / 0 | -18,983.30 to -19,743.51 | -760.21 |
| R3 WT: disk `_kelly` vs B | 507 / 507 | 322 | 185 | 0 / 0 | 13,906.13 to 13,183.91 | -722.22 |
| R3 HEAD proxy: disk `_kelly` with UNH BUY PUTS zeroed vs A | 507 / 507 | 322 | 185 | 0 / 0 | 9,911.73 to 10,216.57 | +304.84 (the original HEAD `_kelly` logs were overwritten 2026-05-05 15:14, so this is a proxy) |

What the differences are, flat (X1):
- 0 signal or sentiment differences.
- 185 strike changes, 7 accept/reject flips (all "degenerate width=0" on TLT, WMT and XOM, D3-3), and 86 exit-reason changes.
- P&L delta by bucket: strike change -712.86; accept flip -310.34; exit change +179.27; unchanged structure +83.72.
- The 17 original `expiration` exits all ended **before** their nominal expiry, because the 2026-05-04 run had no later prices. Their delta is -1,165.36.

Attribution (X4):

| ticker | S_entry repro/orig (min-max) | strike changes | truncated trades | P&L delta |
|---|---|---|---|---|
| GLD | 1.000000 | **0** | 0 | **0.00** (0 rows differ) |
| AAPL | 0.99818-0.99826 | 2 | 4 | +589.29 |
| NVDA | 0.99769-0.99775 | 3 | 1 | +167.49 |
| WMT | 0.99564-0.99579 | 5 | 0 | -461.37 |
| SPY | 0.99494-0.99497 | 16 | 3 | -1,591.25 |
| IWM | 0.99500-0.99506 | 18 | 0 | +2,166.94 |
| JPM | 0.99055-0.99060 | 25 | 2 | +13.75 |
| XOM | 0.98679-0.98695 | 25 | 0 | +82.60 |
| UNH | 0.98822-0.98826 | 55 | 5 | +702.55 |
| TLT | 0.98061-0.98079 | 36 | 2 | -2,430.21 |

- **Diagnosis: price revision, not code.** Each ticker's adjusted-close ratio is a near-constant factor below 1, in the order of its dividends paid between 2026-05-04 and 2026-10-09 (TLT pays monthly: 0.981; GLD pays none: 1.000).
- GLD is the control: identical prices give a bit-identical log.
- Strike changes come from re-rounding scaled spots onto the $5 grid (engine.py:124-127, 142-145). IV rank is unchanged to 1e-4 (RV is scale-invariant).
- The second cause is the trades that were truncated at the 2026-05-04 data end and now run to completion.
- `days_to_earnings`: originally 999 for 40.6% of rows, now 999 for 100% (Finnhub blocked). The field is decision-inert (03 sections 8 and 12), and no accept, strike or exit difference correlates with it (GLD has earnings-inert ETF rows and is identical).
- **There is no evidence of any code difference between the 2026-05-04/05 runs and HEAD/WT.**

## 7. Determinism

- **Record (A) vs replay (C), HEAD: bit-identical.** `cmp` on all 20 reproduced trade logs (`backtest_{T}.csv` and `_kelly.csv`), `kelly_stats.csv`, `quintile_edges.json` and `outputs/r3_production_baseline.md` found no differences [RAN C log + cmp loop].
- Replay runs (B, C, D1, D2) made 0 network fetches and had 0 snapshot misses, 0 blocked writes, and 0 blocked `requests` or curl calls.
- Finnhub was blocked 10 times per backtest script (one `earnings_calendar` attempt per ticker, caught by earnings_filter.py:126-129). That outcome is identical in record and replay.

## 8. Defects / Open questions / Handoff notes for 4b

### Defects

| id | path:line | description | severity | how to confirm |
|---|---|---|---|---|
| D4a-1 | backtest/engine.py:390, 492-498 (+ D2-15) | Results are a function of the download date: dividend back-adjustment and later data change 185/507 structures and flip the walk-forward verdict (WINDOW-DEPENDENT to GENERALIZES). Truncated "expiration" exits are treated as closed. | HIGH | section 6 |
| D4a-2 | scripts/r3_baseline.py:123-136, 159-175 | Headline drawdown uses ticker-concatenated order, not time; Sharpe and win rate include zero (rejected) rows | HIGH (headline DD and Sharpe not meaningful) | Recompute on a date-sorted taken-only series (4b) |
| D4a-3 | spread_builder.py:1036-1048 | No exit friction, commissions, or slippage; one-sided costs | MEDIUM | section 2 |
| D4a-4 | engine.py:291-300, 507 | Both legs priced at RV30: no skew, no VRP, no quotes; no historical options data (D2-7) | HIGH (P&L level) | section 2 |
| D4a-5 | (all scripts) | No portfolio equity curve or cash accounting; per-ticker books summed | MEDIUM | section 1, 5 |
| D4a-6 | scripts/audit_oos_split.py report prose | Real-mode report still says "851 flat-corpus rows" (D3-6 extends to the real report) | LOW | runs/d2/oos_audit_report_real.md:14 |
| D4a-7 | signals/earnings_filter.py:95-129 | Backtest makes a live Finnhub call per ticker per run; it silently degrades to 999 without a key, so logs depend on credentials | LOW (decision-inert) | section 6.2 |

### Open questions

1. What was the exact price state on 2026-05-04/05? It was never cached, so it can't be recovered. The trade-level diffs, with the GLD control, are the only evidence.
2. Whether Yahoo's earnings page dates (EST/EDT text stripped to naive datetimes in the snapshot) match the Finnhub dates used originally. That can't be checked without Finnhub.

### Handoff notes for 4b

- **Snapshot:** `audit/artifacts/stage4/yf_snapshot/` with manifest `manifest.jsonl`.
  - 10 price files `<hash>.pkl`: `Ticker.history(period='5y', auto_adjust=True)`, 1,255 rows, 2021-10-11 to 2026-10-09, fetched 2026-10-10T19:37-19:38Z.
  - 6 earnings files `earnings_{T}.pkl` (AAPL, NVDA, JPM, XOM, UNH, WMT): 25 rows each, 2020-10 to 2026-11, `date_kind` = 24 "realized (reported EPS present)" + 1 "scheduled/estimated as of fetch". These are realized dates, not point-in-time; they were parsed via the documented fallback because lxml is absent.
  - Format: pandas pickle, not parquet (no parquet engine installed; installs prohibited). Read with `pd.read_pickle`.
- **Canonical logs for 4b: the reproduced logs** in `audit/artifacts/stage4/runs/a/raw/` (HEAD: flat `backtest_{T}.csv` + R3 `backtest_{T}_kelly.csv`) and `runs/b/raw/` (WT bypass `_kelly`). They are bit-reproducible from the snapshot, while the on-disk originals depend on unrecoverable 2026-05 prices. Report the on-disk originals alongside as "as-reported", and use the section 6.2 deltas to translate between them.
- **Replay invocation:** `PY audit/artifacts/stage4/yf_record_replay.py --mode replay --copy audit/artifacts/stage4/<head_src|wt_src> --snapshot audit/artifacts/stage4/yf_snapshot --script <scripts/...py> -- <args>`. Any yfinance call not in the snapshot raises `SnapshotMiss`, and non-yfinance network is blocked. Restore `data/raw` from the repo first if a run must start from the original state (as in run C).
- 4b priorities: (1) taken-only, date-sorted Sharpe and DD (D4a-2, D9); (2) the D2-3 after-close cutoff effect (needs per-article scores, which are not stored, and FinBERT is prohibited, so 4b must decide feasibility); (3) cross-ticker aggregate open risk (D3-1); (4) exit-friction and commission sensitivity (D4a-3); (5) the 03 section 16 list.

## Final git status check

[RAN `git status --short` ; `git diff --stat`] after writing this file:

- Tracked diff is unchanged from the stage-1 start state: 12 files changed, **+480 / -218**.
- Untracked: `.claude/` and `outputs/sector_decay_analysis_real.md` (pre-existing), and `audit/`.
- All stage-4a writes are under `audit/`: `04a_backtest_mechanics.md` and `artifacts/stage4/` (copies, snapshot, yf_cache, logs, runs, scripts).
- The harness's write guard recorded 0 blocked writes in every run, so no script wrote outside its copy. Nothing in the repository outside `audit/` changed.

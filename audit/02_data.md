# Stage 2 -- Data sources, point-in-time integrity, data quality

Audit date 2026-10-10. Read-only; no network. Before starting I read `audit/AUDIT_RULES.md` and `audit/01_inventory.md` (rule 7).

**Command legend** (in addition to stage-1 C1-C29):

| id | exact command |
|---|---|
| S1 | `.venv/Scripts/python.exe -I <scratchpad>/dq.py "C:/Claude Code Project/options-sentiment-system/data/raw"`. Read-only pandas profile of every CSV group (rows, dtypes, date range, tickers, null %, duplicate keys, news hour histogram, glob order, engine-loader corpus reconstruction). Writes nothing. |
| S2 | `.venv/Scripts/python.exe -I <scratchpad>/sec_dq.py ".../data/raw/sec"`. Reads all 740 SEC .txt files; size distribution; flags 10-K/10-Q text that contains both "Item 1A Risk Factors" and "Item 8 Financial Statements" headings (likely full-document fallback) or is under 1,000 chars (stub). |
| S3 | `.venv/Scripts/python.exe -I <scratchpad>/leak_dq.py ".../data/raw"`. Dedups chunk articles on (lower-cased headline, date) in the window 2025-05-05 to 2026-05-04, which mirrors `redup_backfill` and reproduces its 2,967 day-rows exactly. Measures the share of articles timestamped 16:00 or later on each real-mode backtest signal day. |
| S4 | `(Get-TimeZone).Id` returned `Eastern Standard Time`, base offset -05:00 (Windows zone, DST-aware) |
| S5 | `grep -n "Loading news_AAPL" logs/pipeline_2026-05-04.log logs/pipeline_2026-05-07.log logs/pipeline_2026-09-25.log` |
| S6 | `awk -F, '{print NF}' data/raw/signals_AAPL.csv \| uniq -c` |
| S7 | Pattern-scan greps: `grep -nE '\.shift\('`, `'center\s*='`, `'bfill\|backfill\(\|method=.b\|ffill'`, `'merge_asof\|resample\('`, `'shuffle\|train_test_split\|sample\(frac\|permutation'`, `'\.rank\(\|pct=True\|quantile\(\|qcut\(\|percentile\|\.min\(\)\|\.max\(\)'`, `'dividend\|tz_localize\|tz_convert\|timezone\|utc'`, `'auto_adjust'` (all `--include=*.py -r . --exclude-dir=.venv --exclude-dir=audit`) |

**Correction to stage 1.** 01_inventory.md D1 said the daily summary shows "fresh scores (e.g. WMT +0.427)". That is wrong. The nightly scorer also reads a stale file (D2-1 below), so the daily-summary scores are stale as well.

---

## 1. Per-source table

| source | status | module / functions | real / synthetic | cache (format) | output schema | tickers on disk | date range on disk | rate limit / errors | evidence |
|---|---|---|---|---|---|---|---|---|---|
| SEC EDGAR | partial | `data/sec_fetcher.py`: `get_cik` :177, `_filings_index` :192, `list_filings` :216, `fetch_filing` :523; `sentiment/sec_scorer.py`: `list_ticker_filings` :265, `score_filing` :139; `sentiment/merger.py`: `load_sec_sentiment` :151 | real | `data/raw/sec/{T}/{form}_{date}[_exhibit99].txt` (text); `data/raw/sec_sentiment_{T}.csv` | sec_sentiment: ticker, filing_date (date string, no time, no tz), filing_type, subcategory, sentiment_score f64, chunk_count, bullish/bearish/neutral_pct, most_*_chunk, total_tokens, source_path | AAPL, JPM, NVDA, UNH, WMT, XOM (no ETFs, by design) | filings 2016-06-22 to 2026-05-01 overall. Per ticker: AAPL 2016-06, XOM 2019-12, NVDA 2020-03, UNH 2020-10, WMT 2023-02, JPM 2025-05. 532 scored filings. | Token-bucket throttle to 10 rps (`_throttle`); 404 returns None; other HTTP errors raise (`_http_get` :137-150); UA from `SEC_USER_AGENT` | [READ data/sec_fetcher.py:137-150,192-243] [RAN S1] |
| Finnhub news | partial (12-month depth) | `data/news_fetcher.py`: `fetch_news` :58, `fetch_news_chunk` :182; `scripts/backfill_news_history.py`; `sentiment/scorer.py`: `score_from_csv`, `aggregate_daily` :191; `scripts/score_backfill_chunks.py`, `scripts/redup_backfill.py` | real | `news_{T}_{date}.csv` (172 files), `news_{T}_chunk_{date}.csv` (280); scored: `sentiment_{T}_{date}.csv` (176), `sentiment_{T}_real.csv` (10) | news: ticker, date (str), datetime (naive str, **machine-local = ET**, see 2.2), headline, summary, source, url. sentiment: ticker, date, sentiment_score, headline_count, bullish/bearish/neutral_pct | all 10 | Daily pulls 2026-04-23 to 2026-09-25 (articles back to 2013 due to Finnhub timestamp resets). Backfill 2025-05-08 to 2026-05-04 after date filter. | Daily: `sleep(1.5)` between tickers, errors return an empty frame (:90-93). Backfill: 5 retries, exponential 2-32 s, `BackfillFetchError` (:57-58) | [READ data/news_fetcher.py:58-135,182-276] [READ scripts/backfill_news_history.py:51-58] [RAN S1] |
| NewsAPI | absent | none | n/a | none | n/a | none | none | n/a | Only mentioned as a future option [READ PROJECT_STATE.md:1136,1220] [RAN C20 vendor grep] |
| General internet sentiment | absent | none. Reddit was removed 2026-04-27 (f924e39). | n/a | none | n/a | none | none | n/a | [RAN C20] [READ sentiment/merger.py:60-63] (streams = news + SEC earnings + SEC other) |
| Historical options prices (GitHub ~15y / OptionsDX) | **absent** | none. The backtest synthesizes Black-Scholes prices (`backtest/engine.py:_build_backtest_spread` :229, `spread_builder.bs_price`). | synthetic (BS, sigma = 30d realized vol) | none | n/a | none | none | n/a | [READ backtest/engine.py:22-35,287-300] [RAN C20 vendor grep: no OptionsDX] |
| Live options chains | partial (snapshot only) | `data/options_fetcher.py`: `fetch_options_chain` :340, `_get_near_term_expiration` :281, `_compute_atm_real_iv` :293 | real (yfinance) | `options_{T}_{date}.csv` (179 files) | ticker, fetch_date, expiration, contractSymbol, strike, option_type, lastPrice, bid, ask, impliedVolatility (Yahoo), volume, openInterest, inTheMoney, real_iv, current_iv_proxy, iv_52w_high/low, iv_rank, iv_rank_pct, iv_rank_label | all 10 | 2026-04-23 to 2026-09-25. **One expiration per file, DTE 7-13 (mean 8.0)** | No retry, no throttle. IV-rank failure fills None (:403-409). Weekend runs happen (10 files). | [READ data/options_fetcher.py:281-420] [RAN S1] |
| Equity prices | complete (no cache) | `backtest/engine.load_price_history` :380; `options_fetcher._compute_rolling_vol` :199 | real (yfinance, `auto_adjust=True`) | **not cached**: downloaded every run, period "2y" / "5y" / "1y" relative to the run date | close, log_ret, rolling_vol, iv_rank; index = naive normalized date (`tz_localize(None)`, engine.py:395) | n/a on disk | n/a (not stored) | Retry wrappers only in some scripts (e.g. r3_baseline.py:107-115); the engine raises `ValueError` on empty | [READ backtest/engine.py:380-416] [RAN S7 auto_adjust] |
| IV (historical) | absent; proxy only | backtest: `rolling_vol` (30d close-to-close RV, annualized) as sigma and as the IV-rank input (engine.py:401-414) | proxy | n/a | n/a | n/a | n/a | n/a | [READ backtest/engine.py:30-35,401-414] |
| IV (live) | partial | `_compute_atm_real_iv` (BS inversion of ATM call and put mid, averaged); `calculate_iv_rank` :213 | real + proxy denominator | inside options CSV | real_iv, iv_rank (see 2.3) | all 10 | 2026-04-23 to 2026-09-25 | real_iv null in 1.7% of files | [READ data/options_fetcher.py:213-254,293-337] [RAN S1] |
| Earnings calendar | partial (live only, no history) | `signals/earnings_filter.py`: `fetch_earnings_dates` :67, `nearest_earnings` :136, `is_earnings_window` :163 | real (Finnhub) | **in-memory dict only** (`_earnings_cache`); nothing on disk | list[date]; no BMO/AMC hour | n/a | window = today - 90 d to today + 180 d at call time (:91-93) | Any exception: warn and return [] (:126-129) | [READ signals/earnings_filter.py:67-162] |
| Risk-free rate | stub (constant) | `RISK_FREE_RATE = 0.045` in spread_builder.py:83 and options_fetcher.py:278 | constant | n/a | n/a | n/a | n/a | n/a | [READ signals/spread_builder.py:83] [READ data/options_fetcher.py:278] |
| Dividends | absent | No dividend yield in any BS formula; no dividend input anywhere | n/a | n/a | n/a | n/a | n/a | n/a | [RAN S7 dividend grep: no hits in data/signals/backtest/sentiment] |
| Insider transactions (extra, shelved) | partial, unused | `data/insider_fetcher.py` | real (Finnhub) | `insider_{JPM,NVDA}.csv` | 15 cols incl. transaction_date, filing_date | JPM, NVDA | 2021-05-06 to 2026-04-15 | requests timeout; key check | [RAN S1] |
| Synthetic sentiment generator | complete | `backtest/engine._generate_synthetic_history` :443 | synthetic | **not written to disk** (in-memory). Demo trade logs `backtest_{T}_demo*.csv` carry `is_synthetic=True`, `sentiment_source='synthetic_news'`. | ticker, sentiment_score, headline_count, bullish/bearish/neutral_pct, is_synthetic | n/a | `bdate_range(end=today, periods=lookback)`, so the range moves with the run date | n/a | [READ backtest/engine.py:443-472] [RAN S1: demo logs 2024-05-29 to 2026-05-01, all is_synthetic=True] |

### 1.1 Trace: fetch, cache, loader, first consumer

| source | fetch | cache write | loader | first decision consumer |
|---|---|---|---|---|
| News (live) | news_fetcher.py:89 `company_news` | news_fetcher.py:138-150 `news_{T}_{today}.csv` | **scorer.py:311-319 `_find_latest_news_csv` returns the alphabetically last `news_{T}_*.csv`, i.e. `news_{T}_chunk_2026-05-04.csv`**, then `score_from_csv`, writing `sentiment_{T}_{today}.csv` | signal_engine.py:101 `load_sentiment` (alphabetically last `sentiment_{T}_*.csv` = `_real.csv`), then `_classify_with_earnings` :460 |
| News (backtest real) | backfill_news_history.py, then news_fetcher.py:233 | `news_{T}_chunk_{to}.csv` (:266-273) | score_backfill_chunks (url dedup :167), then redup_backfill ((headline, date) dedup :177-178, date filter :60-61), writing `sentiment_{T}_real.csv` | engine.py:419-436 `load_sentiment_history` (globs **all** `sentiment_{T}_*.csv`, keep last), then join :609, then `_classify_signal` :712 |
| SEC | sec_fetcher.py:192-243 | `sec/{T}/{form}_{filing_date}.txt` | sec_scorer.py:265 → `sec_sentiment_{T}.csv`; merger.py:151, 185 → `combined_sentiment_{T}.csv` | live: signal_engine.py:403-432 (latest row, age vs today) feeds `_tiered_confidence`. backtest: engine.py:641-657 `sec_map` / `sec_score_map` feed `sec_aligned` + `sentiment_source` (confidence model gated off, confidence_model.py:130) |
| Options (live) | options_fetcher.py:351-358 | `options_{T}_{today}.csv` (:422-429) | signal_engine.py:134-167 `load_iv_rank` (first row of latest file) | `_classify_with_earnings` :460 |
| Equity prices | engine.py:389-390 | none | in-memory | engine.py:609 join, then `_classify_signal(sentiment, iv_rank)` :712, then `_build_backtest_spread(S, sigma)` :791 |
| Earnings | earnings_filter.py:95-99 | memory only | `nearest_earnings` / `is_earnings_window` | live: signal override (signal_engine.py:219-227). backtest: `days_to_earnings` feature only (engine.py:763-770); **no suppression in backtest** (stage-1 D3) |

## 2. Point-in-time audit

### 2.1 EDGAR

| question | answer | evidence |
|---|---|---|
| Availability timestamp | **`filingDate` (date only)** from the submissions JSON. `acceptanceDateTime` and `reportDate` are not read. The filename and `sec_sentiment.filing_date` carry the filing date. The merger keys the daily grid on `filing_date`, so a filing counts as available on that whole date, including filings accepted after 16:00 ET. | [READ data/sec_fetcher.py:206-212] [READ sentiment/merger.py:245-258,266-275] |
| Amendments (10-K/A, 10-Q/A) | **Excluded**: `idx["form"].isin(["10-K","10-Q","8-K"])` is an exact match, so `/A` forms never enter, and no amendment can overwrite an original. No amendment-like filenames exist on disk. Side effect: restatements are ignored. | [READ data/sec_fetcher.py:241] [READ config.py:93] [RAN S2] |
| Same-date collisions | Files are named `{form}_{filing_date}.txt` and existing files are skipped (`have_cover and not overwrite`). A second 8-K filed the same day is therefore silently dropped (or, with `--overwrite`, overwrites the first). On disk there is at most 1 cover per ticker-date [RAN S2]. I could not determine how many filings were lost, because that requires the EDGAR index (network). | [READ data/sec_fetcher.py:552-561] |
| Index depth | Only the submissions `filings.recent` block is read ("roughly the last 1000 filings"); the older `filings.files` pages are never fetched. This may explain partial depth: JPM has only 21 filings from 2025-05, WMT from 2023-02, despite `sec_lookback_years=10`. | [READ data/sec_fetcher.py:193-202] [RAN S1] [INFERRED: JPM/WMT file 8-Ks heavily] |
| Risk-factor (Item 1A) diffing | **Not implemented.** Only MD&A (10-K Item 7, 10-Q Part I Item 2) and 8-K body / EX-99 are extracted. There is no Item 1A extraction and no prior-filing diff. | [READ data/sec_fetcher.py:1-30,262-310,380-405] |
| MD&A extraction method | Regex start `item 7 ... management.s discussion` (10-K) or `item 2 ...` (10-Q); end at the next Item 7A/8 or Item 3/4; the longest candidate slice is kept. **If the best slice is under 500 chars, the full cleaned document is returned** (silent fallback). No success flag is stored. | [READ data/sec_fetcher.py:288-310,380-405] |
| Measured extraction failure rate | Not measured in code. Offline heuristic [RAN S2]: **8 of 34 10-Ks (24%)** contain both the Item 1A and Item 8 headings, i.e. likely full-document fallback (JPM 2026; WMT 2023-2026; XOM 2020-2022). **4 of 95 10-Qs (4%)** are 583-585-char stubs (AAPL 2020-07 to 2021-07, which the code comment says was "fixed"). Heuristic only; stage 3 should confirm on the scored text. | [RAN S2] [READ data/sec_fetcher.py:265-271] |
| Filing date vs period | Not used: `reportDate` is not fetched. 10-K MD&A is used from its filing date onward, which is point-in-time correct apart from the intraday issue above. | [READ data/sec_fetcher.py:206-212] |

### 2.2 News

| question | answer | evidence |
|---|---|---|
| Publication vs ingestion time | Finnhub's `datetime` field (Unix seconds) is used, documented by Finnhub as the publication time [INFERRED from the field name and the API; no doc on disk]. Fetch time is not stored. Finnhub sometimes returns "back-filled / reset stored datetime" values far outside the requested window (articles dated 2011-2013 appear). | [READ data/news_fetcher.py:104-106] [READ scripts/redup_backfill.py:15-18] [RAN S1: daily files reach back to 2013-08-13, chunks to 2011-04-13; 26 chunk rows dated up to 304 days after the chunk's to_date] |
| Timezone | `datetime.datetime.fromtimestamp(ts)` converts to **machine-local time with no tz attached**; the CSV strings carry no offset (0% have one). The machine is set to Eastern (S4), so the stored values are naive ET. That is an assumption of the code, not something stated in the data. Any run on a non-ET machine would shift the date boundaries. | [READ data/news_fetcher.py:105, 241] [RAN S1] [RAN S4] |
| Cutoff rule to decision date t | **None.** `date = dt.date()` is the local calendar date (00:00-23:59). `aggregate_daily` groups by that date (scorer.py:215-222). The backtest inner-joins sentiment[date d] with the close of day d (engine.py:609) and enters at that close (engine.py:705-708, 791). So articles published 16:00-23:59 ET on day d drive a trade priced at day d's 16:00 close. | [READ sentiment/scorer.py:215-222] [READ backtest/engine.py:609-611,704-791] |
| Size of that leak | [RAN S3] 17.7% of deduped in-window articles are timestamped 16:00 ET or later. **386 of 505** matched real-mode backtest signal days contain at least one after-close article; on **44** days after-close articles are 50% or more of that day's articles. Median per-day after-close share is 15%. | [RAN S3] |
| Weekend / holiday articles | Dated Saturday/Sunday (769 weekend rows in `_real`); dropped by the inner join with trading days rather than rolled into Monday. Information loss, not leakage. | [RAN S1] [READ backtest/engine.py:609-611] |
| Latency publication to tradability | Not modeled anywhere. | [READ backtest/engine.py:600-800] |
| Live path cutoff | Live runs at 18:30 ET (setup_scheduler.ps1:92) and would trade the next session, which is point-in-time fine. **But live currently ignores fresh news entirely** (D2-1, D2-2). | [READ scripts/setup_scheduler.ps1:89-92] [RAN S5] |

### 2.3 Options and IV

| question | answer | evidence |
|---|---|---|
| Vendor vs computed IV | Live: **computed**. ATM call and put nearest to `fast_info["lastPrice"]` on the nearest expiration at 7 DTE or more; market price = (bid+ask)/2; BS inversion (Newton-Raphson with bisection fallback); call and put IVs averaged. Yahoo's `impliedVolatility` column is stored but not used for the rank. Backtest: no IV; sigma = 30d RV. | [READ data/options_fetcher.py:281-337] [READ backtest/engine.py:507] |
| Model inputs | European BS; r = 0.045 constant; **no dividend yield**; T = calendar days / 365 with a minimum of 1 day. Expiry is 7-13 DTE in practice (mean 8.0), so the IV is front-week, not 30-day. | [READ data/options_fetcher.py:278,307-309] [RAN S1] |
| IV Rank formula (live) | `(real_iv - min(RV30)) / (max(RV30) - min(RV30))`, clipped to [0,1]. Min and max come from 30d rolling RV over a `period="1y"` yfinance pull at run time, ending at today's close. Window is through t only. **Numerator and denominator are different quantities** (front-week implied vs realized), so the rank is biased: it hits 1.0 in 8.9% of files. Not an IV percentile. | [READ data/options_fetcher.py:199-254] [RAN S1] |
| IV Rank formula (backtest) | `(RV30_t - rolling_min_252(RV30)) / (rolling_max_252 - rolling_min_252)`, `min_periods=30`, clipped. Trailing window including t, so no look-ahead. Early bars use windows as short as 30 days. The returned frame drops only NaN `rolling_vol`, not NaN rank. | [READ backtest/engine.py:401-416] |
| Bid / ask / mid / last | Live IV: mid of bid/ask, requiring both > 0 at the chosen ATM strikes. Live spread pricing (`build_spread`, smoke-test only): pay ask x 1.015, receive bid x 0.985 (spread_builder.py:421-431). Backtest: BS fair value x (1 +/- 1.5%). | [READ data/options_fetcher.py:312-318] [READ backtest/engine.py:291-300] |
| Stale / zero-volume quotes | IV: rows with bid or ask equal to 0 are excluded. No volume or OI filter at the ATM pick, and no quote-timestamp check. Snapshots are taken after the close (18:30 ET) and sometimes on weekends (10 files), so quotes are end-of-day or stale. **20% of stored contracts have bid = 0**; volume is null in 5.7%. `build_spread` has OI >= 50 and bid-ask <= 10% filters (spread_builder.py:114-115, 398-418), but it is never called live. | [RAN S1] [READ signals/spread_builder.py:398-418] |

### 2.4 Equities

| question | answer | evidence |
|---|---|---|
| Adjusted or unadjusted | **Adjusted** (`auto_adjust=True`) everywhere: engine.py:390, options_fetcher.py:205, correlation_matrix.py:55, diagnose_aapl_stops.py:85. | [RAN S7] |
| Retroactive adjustment leakage | Yes, structurally. Back-adjusted closes on day t embed dividends and splits that happened after t, and they change with the download date (no cache). Effects: (a) BS spot, strikes and the $100 width cut (`WIDTH_PRICE_CUT`) are computed on adjusted, not traded, prices; (b) results are not reproducible across download dates. Returns-based quantities (RV, IV rank, direction) are barely affected [INFERRED: adjustment factors are smooth multiplicative scalars]. | [READ backtest/engine.py:129-131,380-416] [READ signals/spread_builder.py:102-104] |
| Halts | Not handled; no code references halts. Daily bars are taken as given. | [RAN grep -rni halt: no hits in code] |

### 2.5 Earnings dates

| question | answer | evidence |
|---|---|---|
| Known in advance at t? | **[UNKNOWN] / no point-in-time record.** Dates are fetched at call time for a window relative to today (today - 90 d to today + 180 d) and kept only in memory. Past entries are realized report dates as Finnhub now lists them [INFERRED]; future entries are Finnhub's current schedule. No historical snapshot of "what was scheduled as of t" is kept. Resolving this needs archived calendar snapshots or a vendor with as-of history. | [READ signals/earnings_filter.py:67-129] |
| Backtest use | `nearest_earnings(ticker, dt)` compares historical bars to **today's** window. Earnings in the backtest period that fall outside that window are missing. ETFs get 999, which accounts for exactly 40.6% of real-flat rows (206/507 = IWM 45 + GLD 70 + TLT 71 + SPY 20). The feature feeds only the gated-off confidence model, and no earnings suppression is applied in the backtest. | [READ backtest/engine.py:666-671,763-770] [RAN S1] |
| Time of day | BMO/AMC not captured; the window is in calendar days, though the docstring says "trading days". | [READ signals/earnings_filter.py:163-246] |

### 2.6 Universe

| question | answer | evidence |
|---|---|---|
| Definition | **Static, present-day hand-picked list** of 10 (6 large-cap single names + 4 ETFs), chosen 2026-04-25. | [READ config.py:30-46] |
| Survivorship / selection | Yes. All 10 are surviving mega-cap names or liquid ETFs, chosen in 2026. The 2026-04-25 rebuild was motivated partly by earlier backtest findings (BUY PUTS edge "tech-concentrated"), so selection was informed by results. | [READ config.py:30-34] [READ PROJECT_STATE.md:12-36] [INFERRED from documentation] |
| Delisted tickers | No handling; no historical constituent list; no point-in-time membership. | [READ config.py:35-46] [INFERRED: no code references delisting] |

## 3. Look-ahead pattern scan [RAN S7]

| pattern | hit (path:line) | class | justification |
|---|---|---|---|
| negative shift | none (only `.shift(1)`: engine.py:399, options_fetcher.py:208, correlation_matrix.py:71, diagnose_aapl_stops.py:357,607) | SAFE | Lag-1 log returns |
| `center=True` | none | SAFE | -- |
| bfill | signals/spread_builder.py:947 `iv_series.reindex(price_index).ffill().bfill()` | NEEDS REVIEW | bfill fills only leading NaNs from later values. The engine passes `rolling_vol` from a frame that already dropped NaN (engine.py:416), so it should be a no-op [INFERRED]. Any other caller passing a gappy series would back-fill entry-day IV from the future. |
| ffill | sentiment/merger.py:259, 275 | SAFE | Forward-fills SEC scores after their filing_date (staleness caps applied after). The same-day issue is listed under event joins below. |
| `merge_asof` / `resample` | none | SAFE | -- |
| shuffled splits | none (no shuffle / train_test_split / permutation) | SAFE | audit_oos_split cutoff = 75th percentile of entry_date, chronological (audit_oos_split.py:950) |
| trailing rank / min-max | backtest/engine.py:406-407 rolling 252 min/max | SAFE | Trailing, includes t |
| trailing rank / min-max | data/options_fetcher.py:242-243 1y min/max | SAFE | Live, ends at t |
| full-sample stats used in decisions | scripts/r3_baseline.py:285-289 (`compute_kelly_stats(flat)` + `compute_and_save_quintile_edges(flat)` on the whole corpus, then the Kelly backtest over the **same** dates :291-298); signals/position_sizer.py:379 qcut | **LEAK** | The R3 headline (real: +$9,697 / Sharpe 1.17; flat is -$18,983) uses a negative-Kelly filter fit on outcomes from the full period it then trades. BUY PUTS gets disabled because of its full-sample Kelly (kelly_stats.csv: BUY PUTS f* = -0.5224 on 154 trades). Mechanism: an outcome-derived per-signal filter is applied in-sample. Only the walk-forward and 75/25 audits remove it. |
| full-sample normalization | signals/confidence_model.py:196-204 z-score fit on training rows; scripts/fit_confidence_model.py on the full corpus | NEEDS REVIEW | Inert in production (`USE_LEARNED_MODEL=False`, confidence_model.py:130). Would be in-sample if re-enabled without the walk-forward. |
| full-sample percentile (research) | signals/signal_decay.py:196 qcut on full corpus; scripts/compare_confidence_models.py:427-428 `rank(pct=True)`; segregated_kelly_report.py:266; fit_confidence_model.py:99 | NEEDS REVIEW | Descriptive reports; in-sample by construction. Not used by live or audit decisions. |
| walk-forward refit slice | scripts/audit_walkforward.py:316, 333, 344 | SAFE | `accepted` sorted by exit_date (:316); `iloc[:n_completed]` equals `exit_date < T` |
| quintiles inside walk-forward | scripts/audit_walkforward.py:275 | SAFE | Fit on completed training rows only |
| event to same bar: news | sentiment/scorer.py:215 + backtest/engine.py:609, 705-791 | **LEAK** | Articles 16:00-23:59 ET on day d set the signal for a trade at day d's close; 386/505 signal days affected [RAN S3] |
| event to same bar: SEC | sentiment/merger.py:245-275 (date = filing_date) to engine.py:647-655 `sec_map[dt]`, `sec_score_map[dt]` | LEAK (inert) | After-close filings count on their filing date. They feed only `sec_aligned` (gated model) and the `sentiment_source` label. The live path computes age from today, so live is SAFE. Acceptance time is not stored, so the size can't be measured. |
| event to same bar: earnings | backtest/engine.py:763-770 | LEAK (inert) | Uses today's calendar (future-known dates) for historical bars; feature unused while the model is gated |
| retroactive price adjustment | backtest/engine.py:390 `auto_adjust=True` | LEAK (structural, low) | Post-t splits and dividends shape past price levels used for strikes and width (2.4) |
| synthetic window | backtest/engine.py:448 `bdate_range(end=today)` | SAFE (reproducibility issue) | Not a leak; results move with the run date (stage-1 D7) |
| aggregator rolling | sentiment/aggregator.py:120, 160-162 (`rolling(5, min_periods=1)`), :204 `.diff()` | SAFE | Trailing |
| momentum feature | backtest/engine.py:623-625 `diff(3)` | SAFE | Trailing |

## 4. Data quality (offline reads) [RAN S1] [RAN S2] [RAN S6]

| dataset | rows | date range | tickers | null % key cols | duplicate keys | anomalies |
|---|---|---|---|---|---|---|
| news daily (172 files) | 38,538 | article datetime 2013-08-13 to 2026-09-25 | 10 | summary 3.0% | 0 within file; 19,401 (ticker, url) repeats across files (overlapping 30-day pulls) | 3,025 weekend-dated rows; datetimes back to 2013 (Finnhub resets) |
| news chunks (280) | 50,598 | 2011-04-13 to 2026-05-04 | 10 | summary 6.8% | 2,987 (ticker, url) across chunks | 26 rows dated up to 304 days after their chunk window; 4,990 weekend |
| sentiment daily dated (176) | 2,118 | **2013-08-13 to 2026-05-04** | 10 | 0 | 0 within file | **No dates after 2026-05-04 although files run to 2026-09-25**: the nightly job re-scores the backfill chunk (D2-1). 12.2% of days have fewer than 3 headlines. |
| sentiment `_real` (10) | 2,967 | 2025-05-08 to 2026-05-04 | 10 (NVDA 132 to IWM 360 days) | 0 | 0 (ticker, date) | 769 weekend rows; 10.7% of days under 3 headlines (config gate `min_articles_required` is unused) |
| engine real-mode load (union of the above, keep-last) | 2,991 | IWM from 2017-04-16, GLD from 2013-08-13, SPY from 2018-08-17 | 10 | 0 | 0 after dedup | 24 rows come from dated daily files, not `_real` (AAPL 6, NVDA 10, SPY 6, IWM 1, GLD 1), including pre-2025 stray dates |
| sentiment_summary (10) | 13,286 | 2013-08-13 to 2026-05-04 | 10 | raw_score 77.5% | 0 | Calendar-day grid with long empty stretches (GLD 4,648 rows) |
| combined_sentiment (7) | 4,925 | 2020-04-30 to 2026-04-24 | 7 (no GLD/IWM/TLT; SPY 5 rows) | **news_sentiment 99.74%** | **9 duplicate (ticker, date)** | Built 2026-04-25, before the real backfill and the 2026-05-01 SEC rescore. "Combined" here is effectively SEC-only. |
| sec_sentiment (6) | 532 | 2016-06-22 to 2026-05-01 | 6 | 0 | 0 (ticker, date, type) | 403 8-K / 95 10-Q / 34 10-K; JPM only 21 rows (1 year) |
| sec raw text (6 dirs) | 740 files | 2016-06-22 to 2026-05-01 | 6 | n/a | max 1 cover per ticker-date | 24% of 10-Ks likely full-doc fallback; 4 AAPL 10-Q stubs of about 584 chars |
| options (179) | 21,214 contracts | fetch 2026-04-23 to 2026-09-25 | 10 | bid 0.17%, volume 5.7%, real_iv 2.9% | 0 (ticker, fetch_date, contract) | One expiry at 7-13 DTE per file (no 35/60 DTE data); 20% bid = 0; iv_rank = 1.0 in 8.9% of files; 10 weekend fetches |
| signals live (10) | 143 parsed (3 files fail) | 2026-04-25 to 2026-09-25 | 7 parsed | sec fields 42% | **24 duplicate (ticker, signal_date)** | **signals_AAPL/NVDA/SPY.csv unparseable**: rows appended with 16, then 22, then 30 columns under the original header [RAN S6]. 101/143 rows after 2026-05-06 have sentiment_date 2026-05-04. 7 weekend signal dates. |
| backtest real flat (10) | 507 | entry 2025-05-08 to 2026-05-04 | 10 | strategy_type 1.8% | 0 (ticker, entry_date) | is_synthetic all False; 449 accepted; days_to_earnings 999 in 40.6% (all ETF rows) |
| backtest demo flat (10) | 283 | entry 2024-05-29 to 2026-05-01 | 10 (WMT 1 row, IWM 88) | -- | 0 | is_synthetic all True; distinguishable from real by `is_synthetic`, `sentiment_source`, and the `_demo` suffix |
| insider (2) | 3,022 | 2021-05-06 to 2026-04-15 | JPM, NVDA | **insider_role 100%** | n/a | Shelved; unused by code |
| kelly_stats.csv | 2 rows | -- | -- | -- | -- | BUY CALLS n=295 f*=+0.2416; BUY PUTS n=154 f*=-0.5224. Fit on the real flat corpus; no SELL PUTS / SELL CALLS rows. |

**Mixed real and synthetic.** No synthetic sentiment is written to disk; demo is generated in memory [READ backtest/engine.py:594-596]. The trade logs are distinguishable as above. The engine's real-mode corpus mixes two real sources (the `_real` backfill plus the daily-scored stale chunk files) with no source column, so you can't tell them apart without the filename [RAN S1].

**On disk but not referenced by code:** `insider_*.csv`, `sec_sentiment_AAPL_pre-fix.csv`, `data/raw/archive_5ticker/*`, `correlation_matrix_*.csv` (write-only), `confidence_model_v2_10t.json` (not loaded by production), `*_oos_train*.json/csv` (audit outputs). **Referenced but missing:** `combined_sentiment_{GLD,IWM,TLT}.csv` (merger never run for them; engine falls back silently, engine.py:656-657).

## 5. Data readiness

| source | needed for | status | depth on disk now | depth needed (2008, 2020, 2022) | blocker |
|---|---|---|---|---|---|
| Finnhub news | signal (primary input) | partial; live scoring broken (D2-1) | 2025-05-08 to 2026-05-04 (about 12 months) | 2007 onward | **Cost**: free-tier depth wall about 12 months (outputs/finnhub_historical_spike_v3.md:97) |
| NewsAPI | intended second news source | absent | none | 2007 onward | Not built; free tier is short-history [INFERRED] |
| General internet | intended stream | absent | none | 2007 onward | Not built |
| SEC EDGAR | confidence tier (live), sec_aligned (gated) | partial | 2016 to 2026 for AAPL; 2019-2025 start for others; none for ETFs | 2007 onward | Not built: `filings.files` pagination, Item 1A, acceptance time. Free access. |
| Historical options prices | realistic spread P&L, IV | **absent** | none (live snapshots since 2026-04-23, front-week only) | 2007 onward | **Cost / access**: OptionsDX paid; GitHub dataset not integrated |
| Historical IV | regime filter (IV rank) | absent (RV proxy) | none | 2007 onward | Depends on options history |
| Equity prices | everything | available on demand | not cached; engine pulls 2y/5y (5y from 2026 starts about 2021-10, so **misses 2008 and 2020**) | 2007 onward | Not built (period hardcoded); free via yfinance. Reproducibility needs a cache. |
| Earnings calendar | live suppression; backtest (not applied) | partial | none stored | point-in-time 2007 onward | Access: needs as-of history; not built |
| Risk-free rate | BS pricing | constant 4.5% | n/a | daily series 2007 onward (2008 and 2020 near 0%, 2022 rising) | Not built (e.g. FRED, free) |
| Dividends | BS pricing (q) | absent | n/a | 2007 onward | Not built (yfinance has them) |
| Bloomberg | stated optional | absent | none | -- | Access |
| Universe membership | survivorship control | static list | n/a | point-in-time constituents | Not built |

**Net:** none of 2008, 2020, or 2022 is covered by the real sentiment corpus (2025-05 onward). The equity price pull also misses 2008 and 2020 at the default 5y. Every backtest result on disk uses synthetic option prices [READ backtest/engine.py:22-35].

---

## Defects

| id | path:line | description | severity | how to confirm |
|---|---|---|---|---|
| D2-1 | sentiment/scorer.py:311-319 | `_find_latest_news_csv` sorts filenames; `news_{T}_chunk_2026-05-04.csv` sorts after `news_{T}_2026-09-25.csv` ('c' > '2'). Since 2026-05-04 the nightly job re-scores the stale backfill chunk instead of the news it just fetched. Fresh news has never been scored. | CRITICAL (live) | [RAN S5]: pipeline_2026-05-04.log, 05-07 and 09-25 all "Loading news_AAPL_chunk_2026-05-04.csv"; S1 shows dated sentiment files end at 2026-05-04 |
| D2-2 | signals/signal_engine.py:73-80, 101 | (stage-1 D1, now confirmed with data) live signals read `sentiment_{T}_real.csv`; 101/143 live rows after 2026-05-06 carry sentiment_date 2026-05-04 | CRITICAL (live) | [RAN S1] |
| D2-3 | sentiment/scorer.py:215; data/news_fetcher.py:105; backtest/engine.py:609, 705-791 | No market-close cutoff: after-close (16:00 ET or later) articles drive same-day-close entries. 17.7% of articles; 386/505 real signal days. | **CRITICAL (look-ahead)** | [RAN S3]; stage 4: re-aggregate with a 16:00 cutoff and rerun |
| D2-4 | scripts/r3_baseline.py:285-298 | Kelly filter / quintile edges fit on the full corpus and applied to the same period. The R3 headline is in-sample. | HIGH (invalidates in-sample headline as edge evidence) | Compare with audit_walkforward_real (out-of-sample) |
| D2-5 | data/news_fetcher.py:105, 241 | Timezone-naive `fromtimestamp`: date boundaries depend on the machine TZ; no offset stored | HIGH | [RAN S1] 0% of strings have an offset; [RAN S4] |
| D2-6 | data/options_fetcher.py:239-254, 281-291 | IV rank mixes a front-week (7-13 DTE) implied numerator with a 30d realized-vol denominator range; pegs at 1.0 in 8.9% of files | HIGH | [RAN S1] |
| D2-7 | (absent) | No historical options or IV data; backtest P&L is BS-synthetic with RV sigma, no skew, no dividends, constant r | HIGH | [READ backtest/engine.py:22-35] |
| D2-8 | config.py:35-46 | Static, hindsight-selected universe of survivors; no delisting or point-in-time membership | HIGH (bias) | [READ] |
| D2-9 | data/sec_fetcher.py:206-212 | SEC availability = filingDate only; acceptance time dropped. After-close filings are usable same day in the backtest map. | MEDIUM (inert while model gated) | Fetch acceptanceDateTime (network, later stage) |
| D2-10 | data/sec_fetcher.py:193-202 | Only the `filings.recent` block is read. That likely truncates history (JPM 1 year, WMT 3 years vs 10y config). | MEDIUM | Compare with the EDGAR `filings.files` pages (network) |
| D2-11 | data/sec_fetcher.py:401-408 | MD&A extraction silently falls back to the full document; about 24% of 10-Ks affected, 4 stub 10-Qs remain; no success flag | MEDIUM | [RAN S2]; stage 3: inspect scored chunks |
| D2-12 | data/sec_fetcher.py:552-561 | `{form}_{date}` naming drops same-day second filings (or overwrites them with `--overwrite`) | MEDIUM | EDGAR index comparison (network) |
| D2-13 | data/sec_fetcher.py:1-30 | Item 1A risk factors not extracted; no prior-filing diff | MEDIUM (missing intended feature) | [READ] |
| D2-14 | signals/earnings_filter.py:93-129 | Earnings dates not point-in-time; memory-only cache; backtest uses today's window for historical bars | MEDIUM (inert for backtest decisions; live OK) | [READ]; [RAN S1] 999 share |
| D2-15 | backtest/engine.py:390 (+3 scripts) | `auto_adjust=True` back-adjustment; prices not cached, so results vary with the download date | MEDIUM | Re-download on two dates and diff (network, stage 4) |
| D2-16 | data/raw/signals_{AAPL,NVDA,SPY}.csv; signals/signal_engine.py:608-618 | Append-with-header-once while the schema changed (16, 22, 30 cols): live signal history is unparseable by pandas, and 24 duplicate (ticker, date) rows exist | MEDIUM | [RAN S6] |
| D2-17 | sentiment/merger.py:245-258, 266-275 | Merging SEC rows on `date` creates duplicate grid rows when two filings share a date (9 dups); combined files stale and missing 3 tickers | LOW | [RAN S1] |
| D2-18 | data/options_fetcher.py:281-291, 340-420 | Chains snapshotted after hours and on weekends; ATM pick ignores volume/OI; 20% bid=0 rows stored | LOW | [RAN S1] |
| D2-19 | backtest/engine.py:406-407 | IV-rank `min_periods=30` gives a rank on very short history in the first year of any pull | LOW | [READ] |
| D2-20 | signals/spread_builder.py:947 | `.bfill()` on the IV path could back-fill entry IV from the future for gappy inputs | LOW (no-op on the current caller) | Unit check in stage 5 |
| D2-21 | scripts/redup_backfill.py:60-61 vs backtest/engine.py:424-433 | The `_real` date filter is bypassed: the engine also loads dated files whose stale-chunk rows reach 2013, so 24 rows outside the backfill window enter the real corpus | LOW | [RAN S1] |

## Open questions

1. Finnhub `datetime` semantics: is it first publication, or last update? The "reset" values in 2011-2013 suggest it is sometimes neither. To resolve: Finnhub documentation, or compare against article pages (network).
2. Were the backfill chunks fetched while the machine was on Eastern time? The S4 reading is from today. To resolve: check chunk file mtimes against the log timestamps in the 2026-05-04 log (no TZ is recorded), or ask the owner.
3. How many SEC filings were lost to the `recent`-block limit and to same-date collisions? This needs the EDGAR index (network).
4. Does the extraction-fallback heuristic match what was actually scored? Check `sec_sentiment.chunk_count` against file length in stage 3.
5. Was the earnings calendar ever available point-in-time from Finnhub (as-of history)? Unknown without vendor docs.
6. The 2026-04-25 universe choice: what was examined before choosing it? PROJECT_STATE documents the rationale, but not whether candidate lists were screened on backtest P&L.

## Handoff notes for next stage

- **Stage 3 (sentiment/signal logic):**
  - The sentiment inputs the signal engine actually sees are wrong in both paths: live is stale (D2-1, D2-2); the backtest has a close-cutoff leak (D2-3).
  - The SEC text quality issues (D2-11, the AAPL 10-Q stubs, missing Item 1A) affect the live confidence tier.
  - FinBERT summary truncation and dedup method differ between the daily path (headline-only dedup) and the backfill (url, then (headline, date)).
- **Stage 4 (backtest):**
  - Re-run real mode with a 16:00 ET cutoff (shift after-close articles to d+1). This is the most important correction.
  - Treat the R3 in-sample numbers as non-evidence (D2-4); the walk-forward is the honest read.
  - Every re-run needs yfinance network and gives download-date-dependent prices (D2-15).
  - Option prices are synthetic throughout (D2-7).
- **Stage 5 (tests/parity):** Glob-ordering bugs (D2-1, D2-2) are prime targets for regression tests. The live and backtest sentiment loaders use different file sets.
- Scratchpad scripts S1-S3 are outside the repo; re-create them from the legend descriptions if needed.

## Final git status check

[RAN `git status --short` ; `git diff --stat`] after writing this file:

- Tracked changes are identical to the stage-1 start state: the same 12 modified files, diff stat 12 files +480 / -218.
- Untracked: `.claude/`, `outputs/sector_decay_analysis_real.md` (pre-existing), `audit/` (this audit).
- Stage 2 added only `audit/02_data.md`. The profiling scripts live in the session scratchpad outside the repo and wrote nothing.
- Conclusion: nothing outside `audit/` changed.

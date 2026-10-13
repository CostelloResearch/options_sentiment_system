# Stage 1 -- Repository inventory

Audit date 2026-10-10. Read-only. Rules: `audit/AUDIT_RULES.md`.

**Command legend.** `[RAN Cn]` points to the exact commands below. All were run from the repo root unless a path is given.

| id | exact command |
|---|---|
| C1 | `git status` |
| C2 | `git branch -a` |
| C3 | `git log -1 --format='%H %ci'` |
| C4 | `git rev-list --count HEAD` |
| C5 | `git log --reverse --format='%ci' \| head -1` |
| C6 | `git log -30 --format='%h\|%ci\|%s'` |
| C7 | `git log --graph --oneline` |
| C8 | `git show --stat 2b8a37e` ; `git show --stat f644ecc` ; `git show --stat f924e39` |
| C9 | `git diff --stat` ; `git diff signals/position_sizer.py backtest/engine.py scripts/sector_decay.py` |
| C10 | `find . -path ./.git -prune -o -path ./.venv -prune -o -name __pycache__ -prune -o -type d -print` |
| C11 | `find data -maxdepth 2 -type f \| sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}/DATE/; s/_(TICKERS)([_.])/_T\2/' \| sort \| uniq -c` |
| C12 | `du -sh <dir>` and `du -ch <glob> \| tail -1` per data group; `ls <glob> \| wc -l` |
| C13 | `ls -la --time-style=+%Y-%m-%d` on data/raw artifacts (json, kelly_stats, combined/sec/real sentiment, backtest_AAPL*) |
| C14 | `.venv/Scripts/python.exe --version` |
| C15 | `ls .venv/Lib/site-packages \| grep -iE '^(torch\|transformers\|finnhub\|yfinance\|plotly\|pandas\|numpy\|scipy\|requests\|python_dotenv\|scikit\|sklearn)'` |
| C16 | `grep -rnE '^\s*(from\|import)\s+(config\|main\|sentiment\|signals\|backtest\|dashboard\|data\|scripts)\b' --include=*.py . --exclude-dir=.venv` |
| C17 | `grep -rn --include=*.py -E '__name__ == .__main__.' . --exclude-dir=.venv` |
| C18 | `grep -rn --include=*.py -E 'add_argument\(' . --exclude-dir=.venv` |
| C19 | `grep -rn --include=*.py --include=*.ps1 -E 'os\.environ\|getenv\|load_dotenv\|\$env:' . --exclude-dir=.venv` |
| C20 | `grep -rniE 'reddit\|praw\|subreddit\|wallstreetbets' --exclude-dir=.venv --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=raw --exclude=*.html --exclude-dir=logs .` ; `grep -nic reddit logs/*.log` ; `find . -path ./.venv -prune -o -iname '*reddit*' -print` |
| C21 | `grep -rnwE 'TODO\|FIXME\|HACK\|XXX' --include=*.py --include=*.ps1 --include=*.md . --exclude-dir=.venv --exclude-dir=.git` |
| C22 | `git check-ignore -v .claude/launch.json` (exit code 1 = not ignored) |
| C23 | `grep -naP 'c\x00l\x00a' .gitignore \| od -c` |
| C24 | `grep -n "WARNING\|days old" logs/pipeline_2026-09-25.log` ; `cat logs/daily_summary.txt` |
| C25 | `ls -la dashboard` ; `find . -path ./.git -prune -o -path ./.venv -prune -o -type f -size +4M -print` |
| C26 | `wc -l $(git ls-files '*.py' '*.ps1') data/*.py` |
| C27 | `grep -rn "parity\|pytest\|unittest\|def test_" --include=*.py . --exclude-dir=.venv` ; `find . -name '*.ipynb' -o -name Makefile -o -name 'pyproject.toml' -o -name '*.lock'` (excluding .venv) |
| C28 | `git show f644ecc:config.py \| grep FINNHUB_API_KEY` (value NOT reproduced here) ; `git branch -r --contains f644ecc` |
| C29 | `grep -rn "<fn>" --include=*.py .` for each candidate dead function (see section 11) |

---

## 1. Repo snapshot

| item | value | evidence |
|---|---|---|
| git available / is repo | yes | [RAN C1] |
| current branch | `main`, up to date with `origin/main` | [RAN C1] |
| HEAD | `4a42db0faebd9b36b9f11d726a954e4703cb35cf`, 2026-05-04 22:00:52 -0400 | [RAN C3] |
| branches | `main`, `remotes/origin/main` (no other local or remote branches) | [RAN C2] |
| total commits (HEAD ancestry) | 21 | [RAN C4] |
| first commit date | 2026-04-25 20:28:58 -0400 (`f644ecc`) | [RAN C5] |
| last commit date | 2026-05-04 22:00:52 -0400 (`4a42db0`) | [RAN C3] |
| merge structure | one merge `5ef15d9` joining local history with a GitHub-created root `2b8a37e` (LICENSE + README stub) | [RAN C7] [RAN C8] |
| commit authors | two identities: "Thomas Costello" (local) and "CostelloResearch" (GitHub root commit) | [RAN C8] |

**Uncommitted / untracked at audit start** [RAN C1] [RAN C9]:

| path | state | diff size |
|---|---|---|
| PROJECT_STATE.md | modified | +112 lines |
| backtest/engine.py | modified | +1 (`ticker=ticker` passed to `size_trade`, engine.py:874) |
| signals/position_sizer.py | modified | +14 (new `KELLY_FILTER_BYPASS = {("UNH","BUY PUTS")}`, position_sizer.py:201, 547-554) |
| scripts/audit_oos_split.py | modified | 126 lines changed |
| scripts/audit_walkforward.py | modified | 197 lines changed |
| scripts/sector_decay.py | modified | +17 (adds `--real` mode) |
| outputs/oos_audit_report.md, oos_audit_report_real.md, r3_production_baseline.md, sector_decay_analysis.md, walkforward_audit_report.md, walkforward_audit_report_real.md | modified | regenerated reports |
| .claude/ | untracked | Claude Code session metadata |
| outputs/sector_decay_analysis_real.md | untracked | new report |

So the working tree is ahead of HEAD with **production-affecting** sizing code (`KELLY_FILTER_BYPASS`) that is not committed [RAN C9].

## 2. History

### 2.1 Last 30 commits (all 21 that exist) [RAN C6]

| hash | date | subject (truncated) |
|---|---|---|
| 4a42db0 | 2026-05-04 22:00 | Real-mode validation: backfill, scoring, audits land. PARTIAL/WINDOW-DEPENDENT verdicts... |
| 25c46a5 | 2026-05-01 22:05 | README: add Research Reports section linking audit findings |
| 5ef15d9 | 2026-05-01 22:01 | merge: keep local README, replace GitHub stub |
| 2b8a37e | 2026-05-01 21:59 | Initial commit (GitHub root: LICENSE, README) |
| 17b6a9b | 2026-05-01 21:57 | security: remove hardcoded Finnhub API key fallback (key rotated) |
| 8667940 | 2026-05-01 21:45 | Document SEC Phase 1 + Finnhub depth verdict in §1 and §10.3 |
| b22c7e1 | 2026-05-01 21:45 | Finnhub spikes v2 + v3: to= honored, depth confirmed at ~12 months |
| 3605f1c | 2026-05-01 21:15 | gitignore: exclude .claude/ session metadata |
| 5baecdf | 2026-05-01 21:15 | Phase 1 reports: SEC depth backfill (5/6 multi-regime), Finnhub spike PARTIAL |
| 29da2f9 | 2026-05-01 21:15 | SEC backfill Phase 1: bump sec_lookback_years 3 -> 10 |
| 74e142b | 2026-05-01 19:58 | Option A: disable confidence model, replace quintile sizing with uniform |
| 92bf8ac | 2026-05-01 19:58 | Document Option A: uniform sizing kept under human review |
| fe34f69 | 2026-04-30 14:48 | Fix duplicate dates in sentiment summaries; housekeeping |
| 8091050 | 2026-04-28 15:42 | Insider flows: build and validate infrastructure; ... shelve integration |
| e8a2eb3 | 2026-04-28 14:23 | Audit scripts: add --real flag for dual-mode operation |
| d48d744 | 2026-04-27 22:03 | PROJECT_STATE.md: annotate locked decisions and baseline as provisional |
| fe82ead | 2026-04-27 21:53 | Walk-forward audit: DEGRADES CONSISTENTLY (Sharpe -0.05, Q5 inversion) |
| 207cc64 | 2026-04-27 21:04 | OOS audit: DEGRADES verdict (Sharpe 0.41 in-sample -> -0.60 OOS) |
| 5203362 | 2026-04-27 20:22 | Diagnostic sessions: time/ticker decomposition + AAPL stop-loss diagnosis |
| f924e39 | 2026-04-27 19:23 | Remove Reddit infrastructure: never produced data |
| f644ecc | 2026-04-25 20:28 | Initial commit: baseline (10-ticker universe, Path-A merger, dashboard upgrade) |

### 2.2 Development phases [INFERRED from commit history]

| phase | dates | what happened |
|---|---|---|
| 0. Pre-git | before 2026-04-25 | The first commit already holds 62 files / 18,783 lines [RAN C8], so most of the design history (5-ticker universe, Kelly studies, regime study) happened outside git. File dates under `data/raw/archive_5ticker` (2026-04-23/24) and outputs dated 2026-04-24 back this up [RAN C12]. |
| 1. Baseline import | 2026-04-25 | 10-ticker universe, Path-A SEC merger, dashboard. |
| 2. Cleanup + synthetic OOS audits | 2026-04-27 | Reddit removed; diagnostics; 75/25 and walk-forward audits both returned DEGRADES on synthetic sentiment. |
| 3. Dual-mode audits, insider probe | 2026-04-28 | `--real` flags added; insider-flow work built then shelved. |
| 4. Option A + data depth | 2026-04-30 to 05-01 | Uniform sizing, learned confidence model turned off, SEC lookback raised to 10y, Finnhub depth probes, hardcoded key removed, GitHub publish. |
| 5. Real-data validation | 2026-05-04 | About 50k-article Finnhub backfill, FinBERT scoring, dedup, real-mode audits (PARTIAL / WINDOW-DEPENDENT). |
| 6. Uncommitted probe | 2026-05-05 | UNH BUY PUTS Kelly-filter bypass, sector-decay `--real`, audit prose by mode (PROJECT_STATE.md:2827-2937) [READ PROJECT_STATE.md:2827] [RAN C9]. |
| 7. Dormant | 2026-05-05 to 2026-10-10 | No commits. The scheduler kept running on and off: logs dated 2026-05-07 to 2026-09-25 with gaps [RAN C10] [READ logs/daily_summary.txt:2]. |

## 3. Directory tree (depth 3) [RAN C10] [RAN C12]

| path | annotation |
|---|---|
| `./` | Root: config.py, main.py, CLAUDE.md, PROJECT_STATE.md (2,937 lines), README.md, LICENSE, requirements.txt, .gitignore, `__pycache__/` |
| `.claude/` | Untracked Claude Code metadata (launch.json, settings.local.json, scheduled_tasks.lock). Not ignored, see D15. |
| `backtest/` | engine.py (BS-synthetic spread backtest), metrics.py |
| `dashboard/` | app.py (Plotly builder) plus 11 generated HTML reports of about 4.9-5.2 MB each (not opened) |
| `data/` | **Python package** of fetchers (news, options, sec, insider), plus `raw/`. The CLAUDE.md nav omits this package [READ CLAUDE.md:29-58]. |
| `data/raw/` | All CSV/JSON data and model artifacts (923 top-level files, 63 MB including subdirs) |
| `data/raw/archive_5ticker/` | 30 files from the deprecated 5-ticker universe (MSFT, QQQ, 2026-04-23/24) |
| `data/raw/sec/` | Raw SEC filing text by ticker: AAPL, JPM, NVDA, UNH, WMT, XOM (740 files, 18 MB) |
| `logs/` | Daily pipeline logs 2026-04-24 to 2026-09-25, plus daily_summary.txt |
| `outputs/` | 25 study markdown reports |
| `scripts/` | 22 Python CLIs plus setup_scheduler.ps1 |
| `sentiment/` | scorer (FinBERT), aggregator, merger, sec_scorer |
| `signals/` | signal_engine, spread_builder, position_sizer, confidence_model(+_magnitude), earnings_filter, signal_decay |
| (absent) | No `tests/`, no notebooks, no Makefile, no pyproject.toml, no lock file [RAN C27] |

Code size: about 22.9k lines of Python/PS1 [RAN C26]. Largest files: spread_builder.py 1,233; audit_walkforward.py 1,183; audit_oos_split.py 1,021; engine.py 971; dashboard/app.py 940.

## 4. Environment

| item | value | evidence |
|---|---|---|
| Python claimed | "Python 3.11+" | [READ README.md:40] |
| Python in .venv | 3.14.4; `__pycache__` files are `cpython-314` | [RAN C14] [RAN C11] |
| Minimum implied by code | at least 3.10 (PEP 604 `str \| None` evaluated at runtime with no `from __future__` import) | [READ signals/signal_engine.py:73] [INFERRED from syntax] |
| Dependency files | `requirements.txt` only; no lock file, no pyproject | [READ requirements.txt:1-21] [RAN C27] |

| package | requirement pin | installed in .venv | flag |
|---|---|---|---|
| pandas | >=2.0.0 | 3.0.2 | major version past the floor |
| numpy | >=1.24.0 | 2.4.4 | |
| scipy | >=1.11.0 | 1.17.1 | |
| yfinance | >=0.2.40 | 1.3.0 | network (Yahoo, no key) |
| finnhub-python | >=2.4.18 | 2.4.28 | **key-gated vendor SDK** (Finnhub; free tier used, paid tiers exist) |
| transformers | >=4.40.0 | 5.6.2 | **heavy**; downloads ProsusAI/finbert (~440 MB) on first use [READ sentiment/scorer.py:21-23] |
| torch | >=2.1.0 | 2.11.0 | **heavy** |
| plotly | >=5.20.0 | 6.7.0 | |
| python-dotenv | >=1.0.0 | 1.2.2 | installed but `load_dotenv` is never called [RAN C19] |
| requests | >=2.31.0 | 2.33.1 | used by insider_fetcher (Finnhub REST) and SEC fetcher |

Installed versions come from [RAN C15]; pins from [READ requirements.txt]. No scikit-learn installed [RAN C15]. That matches the CLAUDE.md "No scikit-learn" rule [READ CLAUDE.md:100].

Env vars referenced (names only): `FINNHUB_API_KEY` [READ config.py:17], `SEC_USER_AGENT` [READ config.py:22]. No other `os.environ` or `getenv` reads [RAN C19].

## 5. Entrypoints

Network column: "yes" means it calls yfinance, Finnhub, SEC EDGAR, or Hugging Face (first-run FinBERT download). FinBERT counts as "yes on first run" and "unknown" after that, since that depends on the local HF cache.

| path | what it does | args / env | network? | evidence |
|---|---|---|---|---|
| main.py | Stage orchestrator: fetch, sentiment, signals, backtest, dashboard. No flags runs everything. | `--fetch --sentiment --signals --backtest --dashboard --dashboard-overview-only --demo --tickers`; FINNHUB_API_KEY | yes | [READ main.py:53-116] |
| scripts/run_daily.py | **Live nightly path**: news fetch, options fetch, FinBERT score + aggregate, `generate_signal`. No spread build and no sizing. | `--force --dry-run --tickers`; FINNHUB_API_KEY | yes | [READ scripts/run_daily.py:200-276] |
| scripts/setup_scheduler.ps1 | Registers Windows task `OptionsSentimentPipeline`, Mon-Fri 18:30, running run_daily.py | none | n/a | [READ scripts/setup_scheduler.ps1:72-92] |
| .claude/launch.json | `python -m http.server 8000 --directory dashboard` (preview config, untracked) | none | local only | [READ .claude/launch.json:1-11] |
| scripts/r3_baseline.py | Flagship production-baseline backtest + drift check vs pinned numbers | `--tickers --lookback-days --real --skip-run` | yes unless `--skip-run` | [READ scripts/r3_baseline.py:60-79,105-115] [RAN C18] |
| scripts/segregated_kelly_report.py | Legacy segregated-bucket Kelly study | `--tickers --lookback-days --real --skip-flat --skip-kelly` | yes | [RAN C18] |
| scripts/run_kelly_study.py | Flat, then stats, then Kelly, then decay study | `--tickers --lookback-days --real --skip-flat --skip-kelly --skip-decay` | yes | [RAN C18] |
| scripts/regime_comparison.py | R1/R2/R3 allocation study (monkeypatches engine and sizer) | `--tickers --lookback-days --real --skip-run` | yes | [READ scripts/regime_comparison.py:404-430] |
| scripts/compare_confidence_models.py | Logistic vs magnitude model; can auto-promote | `--tickers --lookback-days --real --skip-backtest --no-promote` | yes | [RAN C18] |
| scripts/fit_confidence_model.py | Refit `confidence_model.json` | `--tickers --lookback-days --real --skip-backtest` | yes unless skip | [RAN C18] |
| scripts/refit_confidence_v2.py | Versioned refit to `confidence_model_<tag>.json` | `--tickers --real --version-tag` | no [INFERRED from imports C16] | [RAN C18] |
| scripts/put_structure_study.py | BUY PUTS DTE x short-delta sweep | `--tickers --real` | yes | [RAN C16] |
| scripts/audit_oos_split.py | 75/25 chronological holdout audit, re-evaluated from logs on disk | `--real` (C18 :1013) | no [INFERRED: run_backtest appears only in a string, :476] | [RAN C16] |
| scripts/audit_walkforward.py | Daily walk-forward refit audit from logs | `--real` | no [INFERRED from imports] | [RAN C16] |
| scripts/sector_decay.py | Per-sector decay (`--real` is uncommitted) | `--tickers --real` | yes (forward returns use yfinance via signal_decay.py:107) | [READ signals/signal_decay.py:107] |
| scripts/correlation_matrix.py | 60d/252d correlation, N_eff | `--tickers --threshold` | yes | [RAN C16] |
| scripts/decompose_time_ticker.py | Month/ticker P&L decomposition | none | no [INFERRED: imports config only] | [RAN C16] |
| scripts/diagnose_aapl_stops.py | AAPL stop-loss diagnosis | none | yes (yfinance) | [RAN C16] |
| scripts/backfill_news_history.py | Chunked Finnhub history backfill (14-day chunks) | `--ticker --max-chunks --dry-run --reset`; FINNHUB_API_KEY | yes (**key-gated**) | [READ scripts/backfill_news_history.py:51-58] |
| scripts/score_backfill_chunks.py | FinBERT-score backfill chunks, write `sentiment_{T}_real.csv` | `--ticker --reset --dry-run --device` | first run (HF) | [READ scripts/score_backfill_chunks.py:52-56] |
| scripts/redup_backfill.py | Re-dedup scored backfill on (headline, date) | `--ticker --dry-run --device` | first run (HF) | [READ scripts/redup_backfill.py:57-63] |
| scripts/backfill_insider_history.py | Finnhub insider transactions (shelved feature) | `--tickers --years --sleep --dry-run`; FINNHUB_API_KEY | yes (key-gated) | [RAN C18] |
| scripts/check_pipeline.py | Data-availability health check | none | yes (earnings_filter, yfinance probes) | [READ scripts/check_pipeline.py:225] |
| scripts/sec_report.py | Prints SEC sentiment report from CSV | `--ticker` | no | [RAN C18] |
| scripts/verify_path_a.py | Path-A verification checks | none | no [INFERRED from imports] | [RAN C16] |
| data/news_fetcher.py `__main__` | Fetch news for all tickers | FINNHUB_API_KEY | yes | [RAN C17] |
| data/options_fetcher.py `__main__` | Options chain + ATM IV + IV rank | none | yes | [RAN C17] |
| data/sec_fetcher.py `__main__` | EDGAR filing download | `--ticker --years --overwrite`; SEC_USER_AGENT | yes (SEC, no key) | [READ data/sec_fetcher.py:719-724] |
| data/insider_fetcher.py `__main__` | Insider fetch | FINNHUB_API_KEY | yes | [RAN C17] |
| sentiment/scorer.py, aggregator.py, merger.py, sec_scorer.py `__main__` | Scoring / summary / merge (`--ticker` on merger and sec_scorer) | | scorer and sec_scorer: first-run HF; merger and aggregator: no | [RAN C17] [RAN C18] |
| signals/signal_engine.py `__main__` | AAPL smoke signal | | yes (earnings filter calls Finnhub) | [READ signals/signal_engine.py:772-775] |
| signals/spread_builder.py `__main__` | AAPL smoke spread from live chain (the **only** caller of `build_spread`) | | yes | [READ signals/spread_builder.py:1071,1136,1232] |
| signals/position_sizer.py `__main__` | Rebuild `kelly_stats.csv` from **all** `backtest_*.csv` | | no | [READ signals/position_sizer.py:421-450,683-685] |
| signals/earnings_filter.py, signal_decay.py `__main__` | Smoke runs | | yes | [RAN C17] |
| backtest/engine.py `__main__` | AAPL backtest (`--demo` via argv) | | yes | [READ backtest/engine.py:961-971] |
| backtest/metrics.py `__main__` | Metrics on saved log | | no | [RAN C17] |
| dashboard/app.py `__main__` | AAPL report or `--overview` (`--demo`) | | yes | [READ dashboard/app.py:932-940] |

## 6. Module map

Import relations come from [RAN C16] plus the lazy imports listed there.

| path | responsibility | key public API | imported by | class |
|---|---|---|---|---|
| config.py | Tickers, taxonomy, thresholds, env keys | `TICKERS SECTOR_MAP ASSET_CLASS ETF_TICKERS DATA_PARAMS SIGNAL_PARAMS` | almost every module | shared |
| data/news_fetcher.py | Finnhub company news, 30-day lookback; chunk fetch for backfill | `fetch_news fetch_all_tickers fetch_news_chunk BackfillFetchError` | main, run_daily, backfill_news_history | production |
| data/options_fetcher.py | yfinance chain, BS IV inversion, IV rank | `fetch_options_chain calculate_iv_rank implied_vol fetch_all_tickers` | main, run_daily, spread_builder (smoke) | production |
| data/sec_fetcher.py | EDGAR 10-K/10-Q/8-K download, MD&A extraction | `get_cik list_filings fetch_filing fetch_all_filings fetch_all_tickers` | none (CLI only) | shared (data prep) |
| data/insider_fetcher.py | Finnhub insider transactions | `fetch_insider_transactions fetch_all_insider_history` | backfill_insider_history | research (shelved) |
| sentiment/scorer.py | FinBERT P(pos)-P(neg), daily mean by calendar date | `score_articles aggregate_daily score_from_csv` | main, run_daily, sec_scorer, score_backfill_chunks, redup_backfill | shared |
| sentiment/aggregator.py | Rolling summary + momentum, writes `sentiment_summary_{T}.csv` | `build_sentiment_summary compute_rolling_sentiment detect_momentum` | main, run_daily | production (output not read by signal_engine; see section 11) |
| sentiment/sec_scorer.py | FinBERT over SEC text, writes `sec_sentiment_{T}.csv` | `score_filing score_all_filings` | none (CLI only) | shared (data prep) |
| sentiment/merger.py | 3-stream blend 0.50/0.35/0.15, writes `combined_sentiment_{T}.csv` | `build_combined load_combined latest_combined_row` | backtest/engine (lazy, :643) | research (backtest-only consumer) |
| signals/signal_engine.py | 4-quadrant rule, earnings override, tiered confidence | `generate_signal _classify_signal _classify_with_earnings _compute_confidence_legacy print_signal_summary` | engine, spread_builder, dashboard, main, run_daily, fit_confidence_model | production |
| signals/earnings_filter.py | Finnhub earnings calendar, SUPPRESS / IV_CRUSH window | `fetch_earnings_dates nearest_earnings is_earnings_window` | signal_engine (lazy), engine (lazy), dashboard, check_pipeline | production |
| signals/spread_builder.py | BS pricing, delta targets, live-chain `build_spread`, `simulate_spread_pnl` exit rules | `bs_price bs_delta build_spread simulate_spread_pnl size_position` | engine, put_structure_study, regime_comparison | shared (primitives); `build_spread` effectively unused |
| signals/position_sizer.py | Kelly stats, negative-Kelly filter, uniform/quintile/bucket sizing | `compute_kelly_stats size_trade kelly_fraction_for load_stats compute_and_save_quintile_edges` | signal_engine, engine, audit_*, compare_*, r3_baseline, regime_comparison, run_kelly_study, segregated_kelly_report | shared |
| signals/confidence_model.py | Hand-rolled IRLS logistic; `load_model()` gated off | `fit_logistic predict_proba load_model fit_from_trade_log validate_quintiles` | signal_engine, engine, audit_*, compare_*, fit_*, refit_* | shared (disabled in prod) |
| signals/confidence_model_magnitude.py | Weighted-ridge alternative model | `fit_weighted_ridge predict_proba load_model` | compare_confidence_models only | research (not promoted) |
| signals/signal_decay.py | Forward-return decay by segment, writes TRADE/DISABLE report | `compute_forward_returns decay_by_segment classify_edge run_decay_analysis` | run_kelly_study, sector_decay | research |
| backtest/engine.py | Daily-bar BS-synthetic spread simulation | `run_backtest load_price_history load_sentiment_history _build_backtest_spread` | metrics, dashboard, main, 7 scripts, signal_decay (lazy) | research |
| backtest/metrics.py | Sharpe, DD, PF, win rate | `sharpe_ratio max_drawdown profit_factor print_summary cumulative_pnl_series` | dashboard, main, run_kelly_study | research |
| dashboard/app.py | Plotly per-ticker + overview HTML | `build_dashboard build_overview_dashboard` | main | research/reporting |
| scripts/*.py (22) | Studies, audits, backfills, live runner | see section 5 | not imported (scripts import each other: none) | research, except run_daily = production |

## 7. Research <-> production mapping (presence only)

| production component | research / backtest counterpart | parity test exists? |
|---|---|---|
| `signal_engine._classify_with_earnings` (live, applies earnings filter) [READ signals/signal_engine.py:460] | `engine.run_backtest` calls `_classify_signal`, **without** earnings [READ backtest/engine.py:712] | none [RAN C27] |
| `signal_engine._tiered_confidence` (news + SEC tiers) [READ signals/signal_engine.py:514-520] | `engine` uses `_compute_confidence_legacy` (strength only) [READ backtest/engine.py:749] | none |
| `options_fetcher.calculate_iv_rank` (real ATM IV vs 1y realized-vol range) [READ data/options_fetcher.py:239-254] | `engine.load_price_history` (30d RV vs 252d RV range, min_periods 30) [READ backtest/engine.py:401-414] | none |
| `spread_builder.build_spread` (live chain; BUY PUTS 60 DTE/0.25 delta set locally) [READ signals/spread_builder.py:538-539,734-735] | `engine._build_backtest_spread` (BS grid; `_PER_STRATEGY_DTE/_SHORT_DELTA`) [READ backtest/engine.py:221-226] | none |
| `spread_builder.size_position` (2% of $10k, reject if above) [READ signals/spread_builder.py:437-463] | `position_sizer.size_trade` (backtest Kelly path, $100k) [READ backtest/engine.py:866-875] | none |
| live sizing metadata `kelly_fraction_for` [READ signals/signal_engine.py:534-538] | `size_trade` | none |
| `signal_engine._try_load_sec_sentiment` (latest filing) [READ signals/signal_engine.py:403-432] | `merger.build_combined` blended series (backtest only) [READ backtest/engine.py:641-657] | none |
| `scorer.aggregate_daily` daily path (news_fetcher, 30-day window) | `score_backfill_chunks` (url dedup) + `redup_backfill` ((headline,date) dedup, fixed date range) [READ scripts/redup_backfill.py:60-63] | none |
| `confidence_model` (logistic, disabled) | `confidence_model_magnitude` | none |
| `backtest/metrics.sharpe_ratio` | Re-implemented `SHARPE_ANN` in audit_oos_split.py:60, audit_walkforward.py:50, decompose_time_ticker.py:49 | none |

No test files of any kind exist (no `test_*`, pytest, or unittest) [RAN C27]. The brief's claim of "parity-tested research vs production code" is not supported by anything on disk.

## 8. Config and parameters

Config files: `config.py` (only). `.env` / `config_local.py` are gitignored and absent [READ .gitignore] [RAN C10]. `.claude/settings.local.json` is tool permission config, not app config.

| parameter | value | path:line |
|---|---|---|
| bullish / bearish sentiment threshold | +0.25 / -0.25 | config.py:104-105 |
| high / low IV rank threshold | 0.70 / 0.30 | config.py:110-111 |
| min_articles_required | 3 (**not read anywhere**) | config.py:114 [RAN grep -rlw min_articles_required] |
| news_lookback_days | 30 | config.py:88; used data/news_fetcher.py:81 |
| iv_history_days | 252 (**not read anywhere**) | config.py:89 |
| sec_lookback_years | 10 (fallback 3 in code; CLI default `--years 3`) | config.py:92; data/sec_fetcher.py:227,723 |
| sec_rate_limit_rps / timeout | 10 / 30s | config.py:94-95 |
| ETF_TICKERS | SPY, IWM, GLD, TLT, QQQ | config.py:82 |
| MAX_SENTIMENT_AGE_DAYS | 3 | signals/signal_engine.py:66 |
| CONFIDENCE_HIGH / MEDIUM floor | 0.80 / 0.50 | signals/signal_engine.py:249-250 |
| SEC_STALE_DAYS | 180 (duplicated) | signals/signal_engine.py:254; sentiment/merger.py:97 |
| sec_aligned threshold | +/-0.10 | signals/signal_engine.py:480-483; backtest/engine.py:727-760 |
| model tier cutoffs | 0.60 / 0.50 | signals/signal_engine.py:506-511 |
| PRE / POST earnings window | 3 / 1 days | signals/earnings_filter.py:49-50 |
| IV_CRUSH entry days / IV threshold | 2 / 0.80 | signals/earnings_filter.py:51-52 |
| RISK_FREE_RATE | 0.045 (duplicated) | signals/spread_builder.py:83; data/options_fetcher.py:278 |
| DTE target / min / max | 35 / 30 / 45 | signals/spread_builder.py:86-88 |
| BUY PUTS DTE / window | 60 / (50,70) local dict | signals/spread_builder.py:734-735; backtest/engine.py:221-223 |
| BUY PUTS short delta / range | 0.25 / (0.20,0.30) local | signals/spread_builder.py:538-539; backtest/engine.py:224-226 |
| debit long / short delta (ranges) | 0.55 (0.50-0.60) / 0.30 (0.25-0.35) | signals/spread_builder.py:92-95 |
| credit short delta (range) | 0.20 (0.15-0.25) | signals/spread_builder.py:98-99 |
| width hi / lo / cut / tolerance | $5 / $2.50 / $100 / $2.50 | signals/spread_builder.py:102-105 |
| FRICTION_FRAC | 1.5% per leg | signals/spread_builder.py:109 |
| debit max cost / credit min premium | 70% / 33% of width | signals/spread_builder.py:112-113 |
| bid-ask max / min OI | 10% / 50 | signals/spread_builder.py:114-115 |
| ACCOUNT_NOTIONAL (live) | $10,000 (duplicated) | signals/spread_builder.py:118; signals/position_sizer.py:187 |
| RISK_PER_TRADE_FRAC | 2% | signals/spread_builder.py:119 |
| stop loss debit / credit | 80% of debit / 2x credit | signals/spread_builder.py:122-123 |
| profit target / time stop | 50% max profit / 21 DTE | signals/spread_builder.py:124-125 |
| HOLD_DAYS (Sharpe annualization only) | 5 | backtest/engine.py:91 |
| VOL_WINDOW / IV_RANK_WINDOW / STRIKE_STEP | 30 / 252 / $5 | backtest/engine.py:92-94 |
| strike grid | +/-25% of spot | backtest/engine.py:142-145 |
| KELLY_BACKTEST_NOTIONAL | $100,000 (duplicated) | backtest/engine.py:105; scripts/audit_oos_split.py:69; scripts/audit_walkforward.py:49 |
| history period switch | 5y if lookback>250 else 2y | backtest/engine.py:590 |
| default backtest lookback | 30 days (scripts default 500) | backtest/engine.py:560; scripts/r3_baseline.py:462 |
| synthetic sentiment walk | 0.90 decay, shock U(-0.18,0.18), seed sum(ord) | backtest/engine.py:445-454 |
| KELLY_FRACTION | 0.25 | signals/position_sizer.py:92 |
| MAX_RISK_PER_TRADE / MAX_PORTFOLIO_RISK / MIN_CONTRACTS | 2% / 6% / 1 | signals/position_sizer.py:95-97 |
| QUINTILE_FRAC | 0.10/0.20/0.30/0.50/0.80% | signals/position_sizer.py:136-142 |
| USE_STRATEGY_BUCKETS / USE_QUINTILE_SIZING | False / False | signals/position_sizer.py:146,158 |
| UNIFORM_PER_TRADE_FRAC | 0.38% | signals/position_sizer.py:163 |
| STRATEGY_BUCKETS | 3.0 / 1.5 / 0.75 / 0.75% | signals/position_sizer.py:168-173 |
| DEFAULT_QUINTILE_EDGES | [0.4745, 0.5114, 0.5492, 0.5973] | signals/position_sizer.py:180 |
| DEFAULT_RISK_FRAC / MIN_TRADES_FOR_KELLY | 2% / 10 | signals/position_sizer.py:184,193 |
| KELLY_FILTER_BYPASS (uncommitted) | {("UNH","BUY PUTS")} | signals/position_sizer.py:201 |
| USE_LEARNED_MODEL | False | signals/confidence_model.py:130 |
| L2_LAMBDA / IRLS iters / tol | 0.5 / 50 / 1e-6 | signals/confidence_model.py:108-112 |
| magnitude model L2 / weight cap / scale | 0.5 / 100 / 10 | signals/confidence_model_magnitude.py:100-106 |
| sentiment weights news / sec_earn / sec_other | 0.50 / 0.35 / 0.15 | sentiment/merger.py:92-94 |
| EARNINGS_STALE_DAYS / NEWS_MIN_ARTICLES | 90 / 1 | sentiment/merger.py:96,98 |
| FinBERT model / batch / max tokens | ProsusAI/finbert / 16 / 512 | sentiment/scorer.py:119; sentiment/sec_scorer.py:52-53 |
| summary truncation | first 200 chars | sentiment/scorer.py (`_build_text`) |
| decay horizons / edge floor | (1,3,5,10,20) / risk_adj 0.05 | signals/signal_decay.py:82,88 |
| OOS split / WF warmup / rolling window | 0.75 / 50 trades / 60d, min 10 trades | scripts/audit_oos_split.py:71; scripts/audit_walkforward.py:48,51-52 |
| backfill chunk / horizon / max chunks | 14d / 380d / 52 | scripts/backfill_news_history.py:51-53 |
| backfill date range | 2025-05-05 to 2026-05-04 | scripts/redup_backfill.py:60-61 |
| dedup ratio warn band | 0.55-0.80 | scripts/score_backfill_chunks.py:55-56 |
| R3 pinned drift baselines | PnL 6775, Sharpe 0.41, DD 6244, PF 1.27, n 357; flat 17913/0.42/21692/1.23/613 | scripts/r3_baseline.py:60-72 |
| regime study R2 overrides | DTE 45, width $10, long delta 0.55 | scripts/regime_comparison.py:85-87 |

## 9. Data on disk (metadata only, nothing opened) [RAN C11] [RAN C12] [RAN C13]

| directory / group | contents | format | size | files | date range (from filenames/mtime) |
|---|---|---|---|---|---|
| data/raw `news_{T}_{DATE}.csv` | Daily Finnhub pulls (30-day window each) | CSV | 16 MB | 172 | 2026-04-23 to 2026-09-25 |
| data/raw `news_{T}_chunk_{DATE}.csv` | Backfill chunks | CSV | 20 MB | 280 | chunk anchors 2025-05-18 to 2026-05-04 |
| data/raw `options_{T}_{DATE}.csv` | Daily chain + IV rank | CSV | 4.0 MB | 179 | 2026-04-23 to 2026-09-25 |
| data/raw `sentiment_{T}_{DATE}.csv` | Daily FinBERT aggregates | CSV | 518 KB | 176 | 2026-04-23 to 2026-09-25 |
| data/raw `sentiment_{T}_real.csv` | Scored + deduped backfill corpus | CSV | 144 KB | 10 | mtime 2026-05-04; contents deferred to stage 2 |
| data/raw `sentiment_summary_{T}.csv` | Aggregator output | CSV | 436 KB | 10 | deferred to stage 2 |
| data/raw `combined_sentiment_{T}.csv` | Merger output; **only 7 tickers (no GLD/IWM/TLT)** | CSV | about 690 KB | 7 | mtime 2026-04-25 |
| data/raw `sec_sentiment_{T}.csv` (+ `_AAPL_pre-fix`) | SEC filing scores | CSV | about 620 KB | 7 | mtime 2026-05-01 (pre-fix 04-25) |
| data/raw/sec/{T}/ | Raw filing text (AAPL: 10 10-K, 30 10-Q, 136 8-K) | TXT | 18 MB | 740 | filing dates 2016-06-22 to 2026-05-01 |
| data/raw `backtest_{T}*.csv` | Trade logs: real flat (10), real `_kelly` (10), `_demo` (10), `_demo_kelly` (10), `_demo_kelly_logistic/_magnitude/_r1/_r2/_r3` (3 each) | CSV | 1.4 MB | 55 | mtimes 2026-04-24 to 05-05 |
| data/raw `signals_{T}.csv` | Appended live signal history | CSV | 64 KB | 10 | last mtime 2026-09-25 |
| data/raw `insider_{JPM,NVDA}.csv` | Shelved insider data | CSV | about 400 KB | 2 | 2026-04-28 |
| data/raw model artifacts | kelly_stats(.csv, _oos_train, _oos_train_real), quintile_edges(.json x3), confidence_model(.json, _v2_10t, _oos_train, _oos_train_real), magnitude_model.json | CSV/JSON | under 10 KB | 11 | 2026-04-24 to 05-05; `confidence_model.json` 2026-04-24 |
| data/raw manifests | backfill_manifest.json, scored_chunks_manifest.json | JSON | 65 KB | 2 | 2026-05-04 |
| data/raw correlation | correlation_matrix_60d / _252d | CSV | 4 KB | 2 | 2026-04-25 |
| data/raw/archive_5ticker | MSFT/QQQ backtests, news, options, sentiment, signals | CSV | 1.1 MB | 30 | 2026-04-23/24 |
| dashboard/*.html | 11 generated reports, **each about 4.87-5.23 MB, not opened** (overview.html is 5,230,533 bytes, over 5 MB) | HTML | 53 MB | 11 | mtime 2026-05-07 [RAN C25] |
| logs/ | 22 pipeline logs + summary | text | 384 KB | 23 | 2026-04-24 to 2026-09-25 |

Git tracking: `data/raw/**/*.csv`, `data/raw/*.json`, `data/raw/sec/`, `dashboard/*.html`, and logs are gitignored [READ .gitignore]. All results therefore depend on untracked local artifacts. No symlinks found [RAN find . -type l]. No data stored outside the repo was found.

## 10. Documentation claims to verify

| source | claim | verify in |
|---|---|---|
| CLAUDE.md:21-27 | Real-mode validation 2026-05-04: PARTIAL (75/25) and WINDOW-DEPENDENT (walk-forward), positive | 4 |
| CLAUDE.md:61-62 | "live signal path and the backtest path share the SAME sizing / pricing / exit-rule code". **Contradicted**: live path never builds or sizes spreads (section 7) | 3, 5 |
| CLAUDE.md:110-124 | BUY PUTS Variant B +$32,457 vs +$8,396; also outputs/put_structure_study.md:17 (+32456.84, Sharpe 1.98) | 4 |
| CLAUDE.md:125-148 | Option A: walk-forward max DD -$15,312 to -$10,705; Q5 +$3,674 to -$5,685 | 4 |
| CLAUDE.md:167-168 | SELL CALLS DISABLED by decay study (61 trades). Code: block comes from the negative-Kelly filter in sizing; live engine still emits SELL CALLS (TLT 2026-09-25) [READ logs/daily_summary.txt:18] | 3 |
| CLAUDE.md:18 | "backtests over 5 years of daily bars". Code pulls 5y only when lookback>250 [READ backtest/engine.py:590] | 3 |
| README.md:3 / user brief | Multi-source sentiment incl. NewsAPI and "general internet". Code: Finnhub news + SEC (earnings / other) only; NewsAPI mentioned only as a future option [READ sentiment/merger.py:60-63] [READ PROJECT_STATE.md:1136] | 2 |
| README.md:19,25 | `signals/iv_rank.py`, `dashboard/report.html` exist. **Neither exists** [RAN C10] | 1 (confirmed false) |
| README.md:57-61 | Set key by editing config.py. Code reads env var [READ config.py:17] | -- |
| README.md:162-166 | Backtest = ATM single option, 30 DTE, 5-day exit. Code = vertical spreads, 35/60 DTE, rule-based exits [READ backtest/engine.py:1-20] | 3 |
| README.md:183-184 | OOS Sharpe 0.41 to -0.60 (DEGRADES); walk-forward -0.05. **On-disk (uncommitted) demo reports now say GENERALIZES, test Sharpe +2.515, and WF Sharpe -1.24** [READ outputs/oos_audit_report.md:119] [READ outputs/walkforward_audit_report.md:153] | 4 |
| README.md:185 | Option A in-sample Sharpe 0.51 to 0.50, drawdown improved 30% | 4 |
| README.md:186 / outputs/sec_phase1_backfill_report.md | SEC coverage 10 years, 5 of 6 tickers | 2 |
| PROJECT_STATE.md:22-24 | N_eff 6.66 (60d) vs about 1.5 old universe | 4 |
| PROJECT_STATE.md:28-32 | Synthetic R3 +$6,775 / Sharpe 0.41 / PF 1.27 / 357 trades; flat +$17,913 / 0.42 | 4 |
| PROJECT_STATE.md:686-691 | Real: flat -$18,983 / -0.90 / 449; R3 +$9,697 / 1.17 / 295; OOS +$2,077 / 0.98; WF +$7,786 / 1.14 | 4 |
| outputs/r3_production_baseline.md:5-19,59 | (uncommitted) R3 real +$13,906 / Sharpe 0.908 / 314 trades; DRIFT verdict; section 1 says QUINTILE regime is production, but code is uniform | 4 |
| outputs/walkforward_audit_report_real.md:150 | WINDOW-DEPENDENT; text compares against "75/25 OOS reference -0.5977", which is the synthetic figure inside a real-mode report | 4 |
| outputs/oos_audit_report_real.md:131 | PARTIAL, test Sharpe +0.979 vs in-sample +1.173 | 4 |
| PROJECT_STATE.md:1283-1316 | Live path reads latest SEC filing only; merger weighting is backtest-only. **Consistent with code** [READ signals/signal_engine.py:403-432] | -- |
| signals/position_sizer.py:70-71 | "backtest engine and the live signal emitter both call size_trade()". Live calls only `kelly_fraction_for` [READ signals/signal_engine.py:534-538] | 5 |
| signals/position_sizer.py:116-118 | R3 "+$12,604 / Sharpe 0.46" (differs from +$6,775 elsewhere) | 4 |
| backtest/engine.py:18-20 | Exit rules "matching the live trading rules exactly". No live trade execution or exit monitoring exists [READ scripts/run_daily.py:200-276] | 5 |
| signals/signal_engine.py:465-470 | Learned model preferred when fitted. Now gated off [READ signals/confidence_model.py:130,344-345] | -- |
| outputs/finnhub_historical_spike_v3.md:97 | Finnhub free-tier depth about 12 months | 2 |
| outputs/segregated_kelly_report.md:7 | Legacy flat +$33k, Sharpe 1.06 (5-ticker) | 4 |
| commit 17b6a9b | Hardcoded Finnhub key removed, "key rotated" | 6 / owner |

No notebooks exist, so there are no notebook-cell claims [RAN C27].

## 11. Red flags

### 11.1 TODO / FIXME / HACK / XXX
Total: **3 occurrences** (1 in code, 2 in PROJECT_STATE.md) [RAN C21]. Fewer than 20 exist, so all are listed:

| path:line | text |
|---|---|
| signals/position_sizer.py:204 | `TODO (2026-04-25, real-data session): re-enable SELL PUTS in production` (credits never clear the 33% floor under the RV-as-IV proxy) |
| PROJECT_STATE.md:1666 | references the TODO marker near `MIN_TRADES_FOR_KELLY` |
| PROJECT_STATE.md:1708 | references the same SELL PUTS TODO |

These are not marked TODO but act as deferred work in code: merger not wired to live (PROJECT_STATE.md:1306-1310); `sent_momentum_3d = 0.0` placeholder at live signal time [READ signals/signal_engine.py:485-489].

### 11.2 Dead-code candidates [RAN C16] [RAN C29]

| item | finding |
|---|---|
| `signals/confidence_model_magnitude.py` | Imported only by scripts/compare_confidence_models.py. Not promoted. |
| `data/insider_fetcher.py` | Only scripts/backfill_insider_history.py. Feature shelved (commit 8091050). |
| `spread_builder.build_spread`, `save_spread`, `size_position` | `build_spread` is called only from `_smoke_test_aapl` (spread_builder.py:1136). `save_spread`: no callers. `size_position`: only inside build_spread (:825). |
| `signal_engine.generate_all_signals` | no callers |
| `aggregator.build_all_summaries`, `merger.latest_combined_row`, `earnings_filter.get_all_earnings_dates`, `insider_fetcher.fetch_all_insider_history` | no callers |
| `backtest/engine.black_scholes` | no callers (kept "for legacy callers / notebooks", engine.py:111-113) |
| `sentiment_summary_{T}.csv` output | Read by check_pipeline, run_daily (display), and merger (excluded at merger.py:121); **not** read by signal_engine or engine |
| `config.min_articles_required`, `config.iv_history_days`, `config.RAW_DATA_DIR` | defined, never read |
| `data/sec_fetcher.py`, `sentiment/sec_scorer.py`, `sentiment/merger.build_combined` | not imported anywhere; manual CLIs only. Not dead, but not part of any automated job. |

### 11.3 Logic duplicated rather than shared

| logic | locations |
|---|---|
| BUY PUTS 60 DTE / 0.25 delta | backtest/engine.py:221-226 vs signals/spread_builder.py:538-539, 734-735 (local literals) |
| IV rank | data/options_fetcher.py:213-270 vs backtest/engine.py:401-414 (different inputs and windows) |
| sec_aligned rule (+/-0.10) | signals/signal_engine.py:477-483; backtest/engine.py:723-730 and again at 754-760 (twice in one loop) |
| days-to-earnings lookup | backtest/engine.py:731-738 and 763-770 (same call twice per bar) |
| Sharpe annualization sqrt(252/5) | backtest/metrics.py:101; scripts/audit_oos_split.py:60; scripts/audit_walkforward.py:50; scripts/decompose_time_ticker.py:49 |
| REJECT_REASONS sets | audit_oos_split.py:63; audit_walkforward.py:54; decompose_time_ticker.py:40; diagnose_aapl_stops.py:41 |
| constants | ACCOUNT_NOTIONAL (spread_builder:118, position_sizer:187); KELLY_BACKTEST_NOTIONAL (engine:105, audit_oos_split:69, audit_walkforward:49); RISK_FREE_RATE (spread_builder:83, options_fetcher:278); SEC_STALE_DAYS (signal_engine:254, merger:97); STOP_LOSS_DEBIT_FRAC (spread_builder:122, diagnose_aapl_stops:47); BS pricing (spread_builder:132-180, options_fetcher:68-126) |
| price-loader retry monkeypatch | r3_baseline.py:105; regime_comparison.py:404; compare_confidence_models.py:69 |

### 11.4 Reddit references [RAN C20]

| location | nature |
|---|---|
| Source code (.py, .ps1), requirements.txt, config.py | **none**. `praw` removed; no `*reddit*` files remain. |
| PROJECT_STATE.md:1767, 1784-1839 | Historical changelog describing the removal |
| logs/pipeline_2026-04-24.log (5 hits), pipeline_2026-04-25.log (10), pipeline_2026-04-27.log (10) | Pre-removal runs: "reddit fetch failed: Reddit API credentials not set" (e.g. pipeline_2026-04-27.log:15) |
| data/raw news CSVs (e.g. data/raw/news_AAPL_2026-05-01.csv:44) | Headlines that mention Reddit Inc. / WallStreetBets as news content. Not pipeline remnants. |

---

## 12. Defects

| id | path:line | description | severity | how to confirm |
|---|---|---|---|---|
| D1 | signals/signal_engine.py:73-80, 101 | `_latest_csv` takes the alphabetically last `sentiment_{T}_*.csv`. `sentiment_{T}_real.csv` sorts after every dated file ('r' > '2'), so **every live signal since 2026-05-04 uses frozen 2026-05-04 sentiment**. logs/pipeline_2026-09-25.log:34-277 warn "144 days old (last: 2026-05-04)" for all 10 tickers, while daily_summary shows fresh scores (e.g. WMT +0.427). | CRITICAL (live signals invalid) | Sort the glob for one ticker; compare the `sentiment_date` column in `signals_{T}.csv` to `signal_date` [RAN C24] |
| D2 | sentiment/scorer.py:215; backtest/engine.py:609, 704-708 | News is bucketed by calendar `date` with no market-close cutoff, and the backtest enters at that date's close. Articles published after the close on day d may drive a trade at d's close. | CRITICAL if confirmed (look-ahead) | Stage 2: check the timezone of the news `datetime` column and the share of articles after 16:00 ET; stage 3: trace the join |
| D3 | backtest/engine.py:712 vs signals/signal_engine.py:460 | Backtest skips earnings SUPPRESS / IV_CRUSH, so backtested signal set differs from live | HIGH | Count backtest trades inside earnings windows |
| D4 | data/options_fetcher.py:239-254 vs backtest/engine.py:401-414 | Live IV rank = implied ATM IV ranked against a realized-vol range (unit mismatch, biased high: TLT 100%); backtest = RV vs RV. Regime filter not comparable. | HIGH | Compare live `iv_rank` with the engine-computed value for the same date |
| D5 | scripts/run_daily.py:200-276; signals/spread_builder.py:1136 | Live path emits labels only: no spread construction, no sizing, no exits. That contradicts the CLAUDE.md design invariant and engine.py:18-20. | HIGH | grep callers of `build_spread` / `size_trade` |
| D6 | signals/position_sizer.py:201, 547-554; backtest/engine.py:874 | Uncommitted `KELLY_FILTER_BYPASS` changes production sizing (UNH BUY PUTS traded despite negative Kelly). Not in CLAUDE.md locked decisions. On-disk reports were regenerated with it. | HIGH | `git diff`; rerun r3_baseline `--skip-run --real` with and without it (stage 4) |
| D7 | backtest/engine.py:448 | Demo synthetic sentiment is anchored to `date.today()`, so demo KPIs change with run date. That explains README (DEGRADES, -0.60) vs on-disk demo (GENERALIZES, +2.515). | HIGH (synthetic results not reproducible) | Run demo twice on different dates (stage 4) |
| D8 | backtest/engine.py:424-433 | Real-mode loader globs `sentiment_{T}_*.csv`: it mixes the `_real` backfill with daily files (which now run to 2026-09-25), keeping the last file on duplicates. The corpus changes over time and mixes two dedup methods. | MEDIUM | List glob order; diff row counts vs PROJECT_STATE's 2,967 rows |
| D9 | backtest/metrics.py:85-103; engine.py:91 | Sharpe annualized as sqrt(252/5) on per-trade P&L, while holds run to 21-60 DTE and trades overlap. Sharpe levels are not standard. | MEDIUM | Recompute on a daily mark-to-market equity curve (stage 4) |
| D10 | signals/position_sizer.py:435, 683-685 | `__main__` rebuilds `kelly_stats.csv` from **all** `backtest_*.csv` (demo, real, kelly, r1-r3 mixed), overwriting the production stats file | MEDIUM | Inspect the glob; do not run |
| D11 | config.py:114, 89 | `min_articles_required` (3) and `iv_history_days` are never read; the documented article-count gate is not enforced | MEDIUM | grep (done) |
| D12 | signals/signal_decay.py:488-496; position_sizer.py:545-553 | "SELL CALLS auto-disabled by decay study": the decay study only writes a report. The block is the negative-Kelly sizing filter, and the live engine still emits SELL CALLS. | MEDIUM | Trace `kelly_stats.csv` SELL CALLS row |
| D13 | (repo) | No tests exist, including parity tests | MEDIUM | [RAN C27] |
| D14 | data/raw/combined_sentiment_*.csv (mtime 2026-04-25) | Merger output predates the 2026-05-01 SEC rescoring and is missing GLD/IWM/TLT. Real-mode `sec_aligned` / `sentiment_source` tags use stale SEC. Impact is limited while the model is gated. | LOW | Compare mtimes; rerun merger offline (stage 2) |
| D15 | .gitignore:41 | `.claude/` line is UTF-16LE encoded (`.\0c\0l\0...`), so it is ignored by nobody; `.claude/` shows as untracked (commit 3605f1c intent failed) | LOW | [RAN C22] exit 1; [RAN C23] |
| D16 | git history `f644ecc:config.py:17` (on origin/main) | A literal Finnhub API key fallback stays in pushed history; 17b6a9b says it was rotated | MEDIUM (LOW if rotation confirmed) | Owner confirms revocation with Finnhub [RAN C28] (value not reproduced) |
| D17 | sentiment/merger.py:239-245 | Comment says `8-K_earnings_cover` goes to "other", but `EARNINGS_SUBS` includes it in earnings | LOW | Read lines |
| D18 | position_sizer.py:156; engine.py:863; signal_engine.py:465-470 | Stale comments ("lines 519-527", "production = QUINTILE", "prefer fitted model") | LOW | Read lines |
| D19 | README.md:19, 25, 57-61, 162-166 | Stale structure, key setup, and backtest description | LOW | section 10 |
| D20 | requirements.txt:2-20 | Only lower-bound pins, no lock; installed pandas 3.0.2 vs `>=2.0`. Environment not reproducible. python-dotenv is listed but never loaded. | LOW | [RAN C15] |
| D21 | signals/signal_engine.py:514-520 vs backtest/engine.py:749 | Live confidence (SEC-tiered) is not the backtest confidence (strength only) that quintile edges and Kelly logs are fit on | LOW (no sizing effect under uniform) | Compare formulas (stage 3) |

## Open questions

1. Is the Windows task `OptionsSentimentPipeline` still registered and running? Logs run to 2026-09-25 with gaps. I could not check because querying Task Scheduler is outside filesystem/git inspection.
2. Timezone and publication time of the Finnhub `datetime` field in the news CSVs (needed for D2). Deferred because stage 1 does not open data.
3. Which run produced the uncommitted `outputs/r3_production_baseline.md` (+$13,906 / 314 trades vs PROJECT_STATE's +$9,697 / 295)? The PROJECT_STATE 2026-05-05 entry suggests the UNH bypass, but I did not confirm it against logs.
4. Was the historical Finnhub key actually revoked? The commit message says so; this cannot be verified offline.
5. Pre-git history: the first commit already contains 18.8k lines. Studies dated 2026-04-24 (put_structure_study, regime_comparison, kelly_study) were produced by code versions not in git, so they may not be reproducible from any commit.
6. `.claude/settings.local.json` references a `.tmp_redup/` directory and `/tmp` backups of data files. The directory is absent now; whether backups were restored correctly is unknown.
7. Whether yfinance `auto_adjust=True` (engine.py:390) and current-day downloads make historical runs non-reproducible. Deferred to stage 2/4.

## Handoff notes for next stage

- **Stage 2 (data):** First confirm D1 (glob ordering) and D2 (article timestamps vs the 16:00 ET cutoff). Profile `sentiment_{T}_real.csv` vs dated daily files (D8), `combined_sentiment` staleness (D14), SEC `filing_date` vs acceptance time (SEC forward-fill starts on filing date, merger.py:245-258), and the 12-month Finnhub depth. Large files: only the dashboard HTMLs (~5 MB each); no data file exceeds 5 MB.
- **Stage 3 (logic):** Signal path parity gaps D3, D4, D21; the live path is label-only (D5). The engine joins sentiment and price on the same date and enters at close (engine.py:609-791).
- **Stage 4 (results):** Every backtest re-run needs yfinance network, which the rules prohibit. `audit_oos_split.py`, `audit_walkforward.py`, `decompose_time_ticker.py`, `refit_confidence_v2.py`, `sec_report.py`, `verify_path_a.py` and `r3_baseline.py --skip-run` look offline-capable (inferred from imports). Demo mode is date-dependent (D7). The uncommitted bypass (D6) changes reported numbers.
- **Stage 5 (tests/parity):** No tests exist (D13). Use the section 7 table as the parity checklist.
- Working-tree state at audit start: see section 1. Treat the HEAD vs working-tree difference as material.

## Final git status check

[RAN `git status --short` ; `git diff --stat`] after writing this file:

- The same 12 modified tracked files as at audit start, with an identical diff stat (12 files, +480 / -218) [RAN C9 at start and at end].
- Untracked: `.claude/`, `outputs/sector_decay_analysis_real.md` (both present at start) and **`audit/` (new, the only change made by this stage)**.
- Conclusion: nothing outside `audit/` was modified, moved, staged, or committed by stage 1.

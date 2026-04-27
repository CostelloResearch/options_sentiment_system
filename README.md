# Options Sentiment & Volatility Signal System

Combines multi-source news sentiment (FinBERT) with options market data (IV Rank, earnings calendar) to generate daily trade signals on a watchlist of equities.

## Project Structure

```
options-sentiment-system/
  data/
    news_fetcher.py       Finnhub news -> CSV
    options_fetcher.py    yfinance options chain + real IV back-solver
    raw/                  All CSV output lands here
  sentiment/
    scorer.py             FinBERT pipeline, -1 to +1 per article
    aggregator.py         5-day rolling average + momentum detection
  signals/
    signal_engine.py      4-quadrant signal logic (BUY/SELL CALLS/PUTS)
    earnings_filter.py    Earnings calendar + IV_CRUSH signal
    iv_rank.py            IV Rank utilities
  backtest/
    engine.py             Black-Scholes P&L simulation over historical data
    metrics.py            Sharpe, win rate, max drawdown, profit factor
  dashboard/
    app.py                4-panel Plotly HTML report
    report.html           Latest generated report (open in browser)
  scripts/
    run_daily.py          Automated daily runner (weekday + holiday guard)
    check_pipeline.py     Health check — run anytime
    setup_scheduler.ps1   Register Windows Task Scheduler job
  logs/
    pipeline_YYYY-MM-DD.log   Full output from each run
    daily_summary.txt         Latest run summary (overwritten daily)
  config.py               API keys, ticker list, signal thresholds
  main.py                 CLI orchestrator
  requirements.txt
```

## Quick Start

### 1. Install Python 3.11+

Download from https://python.org/downloads — check **"Add Python to PATH"**.

### 2. Create virtual environment

```bash
cd "options-sentiment-system"
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

> First run of the sentiment scorer downloads FinBERT (~440 MB to `~/.cache/huggingface/`).

### 3. Set API keys

Edit `config.py`:

```python
FINNHUB_API_KEY      = "your_key_here"   # https://finnhub.io  (free tier is fine)
```

### 4. Run the full pipeline once

```bash
python main.py --fetch --sentiment --signals
```

Or run individual stages:

```bash
python data/news_fetcher.py          # fetch news for all tickers
python data/options_fetcher.py       # fetch options + real IV
python sentiment/scorer.py           # score with FinBERT
python signals/signal_engine.py      # generate today's signal
python dashboard/app.py --demo       # open interactive dashboard
```

### 5. Health check

```bash
python scripts/check_pipeline.py
```

---

## Signal Logic

| Sentiment | IV Rank | Signal |
|-----------|---------|--------|
| > +0.25 (bullish) | < 30% (cheap) | **BUY CALLS** |
| > +0.25 (bullish) | > 70% (expensive) | **SELL PUTS** |
| < -0.25 (bearish) | < 30% (cheap) | **BUY PUTS** |
| < -0.25 (bearish) | > 70% (expensive) | **SELL CALLS** |
| Either | Any | **NEUTRAL** |
| IV Rank > 80% AND 1-2 days before earnings | — | **IV CRUSH** |

Signals generated inside a 3-day pre-earnings / 1-day post-earnings window are **suppressed** (except IV_CRUSH) to avoid vol-spike exposure.

All thresholds are configurable in `config.py` under `SIGNAL_PARAMS`.

---

## Automation Setup

### Register the daily scheduler (Windows Task Scheduler)

Open PowerShell **as Administrator** and run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_scheduler.ps1
```

This registers a task called **OptionsSentimentPipeline** that runs `run_daily.py` Monday–Friday at **6:30 PM** (local time — set your machine to ET or adjust the time in the script).

The run_daily.py script:
- Skips weekends and NYSE holidays automatically
- Logs everything to `logs/pipeline_YYYY-MM-DD.log`
- Writes a one-page summary to `logs/daily_summary.txt`
- Continues processing remaining tickers if one fails

### Useful scheduler commands

```powershell
# Trigger a run immediately (useful for testing)
Start-ScheduledTask -TaskName "OptionsSentimentPipeline"

# Check last run result
Get-ScheduledTask "OptionsSentimentPipeline" | Get-ScheduledTaskInfo

# View today's summary
Get-Content logs\daily_summary.txt

# Remove the task
Unregister-ScheduledTask -TaskName "OptionsSentimentPipeline" -Confirm
```

### Manual run with options

```bash
python scripts/run_daily.py                      # normal (skips weekends/holidays)
python scripts/run_daily.py --force              # run regardless of date
python scripts/run_daily.py --dry-run            # preview without executing
python scripts/run_daily.py --tickers AAPL TSLA  # override ticker list
```

---

## IV Methodology

**Real IV** is back-solved from the live ATM options chain using Black-Scholes inversion (Newton-Raphson + bisection fallback). The ATM call and ATM put IVs are averaged to reduce skew bias.

**IV Rank** = (real_iv − 52w_low) / (52w_high − 52w_low)

Because free data sources don't provide historical IV, the 52-week range uses rolling 30-day realised volatility as a proxy. The **vol risk premium** (real_iv − proxy) is also displayed — a large positive premium near earnings is normal and expected.

---

## Backtest Notes

The backtest prices ATM options using Black-Scholes at entry and exit. Because free historical options prices are unavailable, this is an approximation. Key assumptions:

- Entry: ATM strike, 30 calendar DTE, pay ask (BS × 1.015)
- Exit: 5 trading days later, sell at mid (BS fair value)
- Risk-free rate: 4.5% (edit `RISK_FREE_RATE` in `backtest/engine.py`)

Use `--demo` mode for a 30-day synthetic backtest when real history is limited:

```bash
python main.py --backtest --demo
python main.py --dashboard --demo
```

Real backtest quality improves as you accumulate daily pipeline runs.

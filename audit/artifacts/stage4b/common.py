# Stage 4b shared loaders. Read-only: reads repo data/raw, stage-4 runs and the
# stage-4a yfinance snapshot. No project imports, no network.
import os, glob, re, json
import numpy as np
import pandas as pd

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
RAW = os.path.join(REPO, "data", "raw")
ST4 = os.path.join(REPO, "audit", "artifacts", "stage4")
OUT = os.path.join(REPO, "audit", "artifacts", "stage4b")
RUN_A = os.path.join(ST4, "runs", "a", "raw")
RUN_B = os.path.join(ST4, "runs", "b", "raw")
SNAP = os.path.join(ST4, "yf_snapshot")
TICKERS = ["AAPL", "NVDA", "JPM", "XOM", "UNH", "WMT", "IWM", "GLD", "TLT", "SPY"]  # config.py:35-46 order
SINGLE = ["AAPL", "NVDA", "JPM", "XOM", "UNH", "WMT"]
WIN_LO, WIN_HI = pd.Timestamp("2025-05-05"), pd.Timestamp("2026-05-04")   # redup_backfill.py:60-61
CUTOFF = pd.Timestamp("2025-12-22")                                       # 75/25 cutoff (03 sec 10b)
NOTIONAL = 100_000.0
R = 0.045

def save(df, name):
    p = os.path.join(OUT, name)
    df.to_csv(p, index=True if df.index.name else False)
    return p

def load_logs(d, suffix):
    """Concatenate per-ticker logs in config.TICKERS order (mirrors r3_baseline._load_logs)."""
    fr = []
    for t in TICKERS:
        p = os.path.join(d, f"backtest_{t}{suffix}.csv")
        if os.path.exists(p):
            fr.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    df = pd.concat(fr, ignore_index=True)
    df["accepted"] = df["accepted"].astype(bool)
    return df

def taken_flat(df):
    return df["accepted"]

def taken_kelly(df):
    return df["accepted"] & (df["contracts"].fillna(0) > 0)

# ---------------- prices (snapshot) ----------------
def load_prices():
    man = [json.loads(l) for l in open(os.path.join(SNAP, "manifest.jsonl"), encoding="utf-8")]
    out = {}
    for m in man:
        if m.get("kind") != "price_history":
            continue
        t = m["key"]["id"]
        h = pd.read_pickle(os.path.join(SNAP, m["file"]))
        idx = pd.to_datetime(h.index).tz_localize(None).normalize()
        out[t] = pd.Series(h["Close"].values, index=idx, name=t).sort_index()
    return out

def rv_rank_frame(close):
    """Exact re-implementation of backtest/engine.py:398-416."""
    df = pd.DataFrame({"close": close})
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
    df["rolling_vol"] = df["log_ret"].rolling(30, min_periods=30).std() * np.sqrt(252)
    lo = df["rolling_vol"].rolling(252, min_periods=30).min()
    hi = df["rolling_vol"].rolling(252, min_periods=30).max()
    rng = hi - lo
    df["iv_rank"] = np.where(rng > 1e-8, (df["rolling_vol"] - lo) / rng, 0.5)
    df["iv_rank"] = df["iv_rank"].clip(0.0, 1.0)
    return df.dropna(subset=["rolling_vol"])

def load_earnings():
    out = {}
    for t in SINGLE:
        p = os.path.join(SNAP, f"earnings_{t}.pkl")
        if os.path.exists(p):
            e = pd.read_pickle(p)
            out[t] = sorted(set(pd.to_datetime(e.index).normalize()))
    return out

# ---------------- sentiment (engine-equivalent union, engine.py:419-436) ----------------
def load_sentiment(t):
    files = sorted(glob.glob(os.path.join(RAW, f"sentiment_{t}_*.csv")))
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last").sort_values("date")
    return df.set_index("date")

# ---------------- news after-close flags (redup_backfill dedup) ----------------
def news_day_table():
    fr = []
    for f in glob.glob(os.path.join(RAW, "news_*_chunk_*.csv")):
        fr.append(pd.read_csv(f, usecols=["ticker", "date", "datetime", "headline"]))
    ch = pd.concat(fr, ignore_index=True)
    ch["headline_normalized"] = ch["headline"].fillna("").astype(str).str.strip().str.lower()   # redup_backfill.py:166-169
    ch = ch[ch["headline_normalized"] != ""]
    ch["date"] = pd.to_datetime(ch["date"], errors="coerce").dt.strftime("%Y-%m-%d")    # :122-124
    ch = ch.drop_duplicates(subset=["ticker", "headline_normalized", "date"], keep="first")  # :177-178 (redup runs per ticker)
    ch["date"] = pd.to_datetime(ch["date"])
    ch = ch[(ch["date"] >= WIN_LO) & (ch["date"] <= WIN_HI)]                            # :60-61
    ch["dt"] = pd.to_datetime(ch["datetime"], errors="coerce")
    ch["after"] = ch["dt"].dt.hour >= 16                                                 # naive ET (02 sec 2.2)
    day = ch.groupby(["ticker", "date"]).agg(n_articles=("after", "size"), n_after=("after", "sum")).reset_index()
    day["frac_after"] = day["n_after"] / day["n_articles"]
    return day

# ---------------- Black-Scholes (spread_builder.bs_price equivalent) ----------------
from math import erf, sqrt, log, exp
def _N(x):
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))
def bs_price(S, K, T, r, iv, is_call):
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        return max(S - K, 0.0) if is_call else max(K - S, 0.0)
    d1 = (log(S / K) + (r + 0.5 * iv * iv) * T) / (iv * sqrt(T))
    d2 = d1 - iv * sqrt(T)
    if is_call:
        return max(S * _N(d1) - K * exp(-r * T) * _N(d2), 0.0)
    return max(K * exp(-r * T) * _N(-d2) - S * _N(-d1), 0.0)

# ---------------- exit leg marks (re-derived; spread_builder.py:974-1046) ----------------
_RV_CACHE = {}
def rv_series(t, prices):
    if t not in _RV_CACHE:
        _RV_CACHE[t] = rv_rank_frame(prices[t])
    return _RV_CACHE[t]

def leg_marks(row, prices, at="exit"):
    """BS fair value of long and short legs at the exit (or entry) close, sigma = RV30 that day."""
    t = row["ticker"]
    rv = rv_series(t, prices)
    d = pd.Timestamp(row["exit_date"] if at == "exit" else row["entry_date"]).normalize()
    if d not in rv.index:
        return np.nan, np.nan
    S = float(rv.loc[d, "close"]); iv = float(rv.loc[d, "rolling_vol"])
    exp_d = pd.Timestamp(row["expiration"]).normalize()
    T = max((exp_d - d).days, 0) / 365.0
    is_call = row["strategy_type"] in ("BULL_CALL_DEBIT", "BEAR_CALL_CREDIT")
    return (bs_price(S, float(row["long_strike"]), T, R, iv, is_call),
            bs_price(S, float(row["short_strike"]), T, R, iv, is_call))

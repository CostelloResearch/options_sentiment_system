# Stage 4b section 2: does bullish sentiment add anything beyond low realized vol?
# Underlying close-to-close forward returns, no option pricing. Read-only.
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

prices = load_prices()
day = news_day_table().set_index(["ticker", "date"])

# ---------- panel ----------
rows = []
for t in TICKERS:
    rv = rv_rank_frame(prices[t])
    close = prices[t]
    pos = {d: i for i, d in enumerate(close.index)}
    s = load_sentiment(t)
    s = s[(s.index >= WIN_LO) & (s.index <= WIN_HI)]
    n_sent_all = len(s)
    j = s.join(rv[["close", "iv_rank"]], how="inner")       # engine.py:609 inner join; weekend rows drop here
    for d, r in j.iterrows():
        i = pos[d]
        rec = {"ticker": t, "date": d, "sent": float(r["sentiment_score"]), "rv_rank": float(r["iv_rank"]),
               "trail1": close.iloc[i] / close.iloc[i - 1] - 1 if i >= 1 else np.nan,
               "trail5": close.iloc[i] / close.iloc[i - 5] - 1 if i >= 5 else np.nan}
        for h in range(1, 22):
            rec[f"fwd{h}"] = close.iloc[i + h] / close.iloc[i] - 1 if i + h < len(close) else np.nan
        k = (t, d)
        rec["n_after"] = int(day.loc[k, "n_after"]) if k in day.index else -1
        rows.append(rec)
    print(f"{t}: sentiment rows in window {n_sent_all}, joined trading days {len(j)}, weekend/holiday rows dropped {n_sent_all - len(j)}")
P = pd.DataFrame(rows)
P["bucket"] = np.where(P["sent"] > 0.25, "bullish", np.where(P["sent"] < -0.25, "bearish", "neutral"))   # strict, signal_engine.py:184-185
P["low_rv"] = P["rv_rank"] < 0.30                                                                       # strict, signal_engine.py:186
P["mom"] = np.where(P["trail5"] > 0, "up5", np.where(P["trail5"] < 0, "down5", "flat5"))
save(P, "s2_panel.csv")

# ---------- holding period ----------
flat = load_logs(RUN_A, "")
bc = flat[taken_flat(flat) & (flat["signal"] == "BUY CALLS")].copy()
def tdays(r):
    idx = prices[r["ticker"]].index
    return int(((idx > r["entry_date"]) & (idx <= r["exit_date"])).sum())
bc["tdays_held"] = bc.apply(tdays, axis=1)
hold = pd.DataFrame({"stat": ["n", "mean", "median", "p25", "p75", "min", "max"],
                     "calendar_days_held": [len(bc), bc["days_held"].mean(), bc["days_held"].median(), bc["days_held"].quantile(.25),
                                            bc["days_held"].quantile(.75), bc["days_held"].min(), bc["days_held"].max()],
                     "trading_days_held": [len(bc), bc["tdays_held"].mean(), bc["tdays_held"].median(), bc["tdays_held"].quantile(.25),
                                           bc["tdays_held"].quantile(.75), bc["tdays_held"].min(), bc["tdays_held"].max()]})
save(hold.round(2), "s2_days_held.csv"); print(hold.round(2).to_string(index=False))
H_MED = int(round(bc["tdays_held"].median()))
print("median trading-day hold:", H_MED)
if H_MED not in (1, 5, 10, 21):
    for t in TICKERS:
        pass
HS = sorted(set([1, 5, 10, H_MED]))
for h in HS:
    if f"fwd{h}" not in P:
        raise SystemExit(f"horizon {h} not precomputed")
print("forward obs dropped past data end:", {h: int(P[f'fwd{h}'].isna().sum()) for h in HS})

# ---------- group table ----------
def group_table(df, key, label):
    out = []
    for h in HS:
        c = f"fwd{h}"; d = df.dropna(subset=[c])
        for reg, sub in (("low_rv", d[d["low_rv"]]), ("all_days", d)):
            for b, g in list(sub.groupby(key)) + [("ALL", sub)]:
                out.append({"variant": label, "h": h, "regime": reg, "bucket": b, "n_ticker_days": len(g),
                            "n_dates": g["date"].nunique(), "mean": g[c].mean(), "median": g[c].median(),
                            "hit_rate": (g[c] > 0).mean()})
    return pd.DataFrame(out)

# ---------- block bootstrap of differences (dates, blocks of h trading days) ----------
DATES = np.array(sorted(P["date"].unique()))
DPOS = {d: i for i, d in enumerate(DATES)}
def date_weights(h, B=2000):
    rng = np.random.default_rng(0)
    nD = len(DATES); k = math.ceil(nD / h)
    starts = rng.integers(0, nD - h + 1, size=(B, k))
    W = np.zeros((B, nD))
    for b in range(B):
        idx = (starts[b][:, None] + np.arange(h)[None, :]).ravel()[:nD]
        np.add.at(W[b], idx, 1.0)
    return W

def agg(df, c):
    s = np.zeros(len(DATES)); n = np.zeros(len(DATES))
    ix = df["date"].map(DPOS).values
    np.add.at(s, ix, df[c].values); np.add.at(n, ix, 1.0)
    return s, n

def diff_ci(dfa, dfb, c, W):
    sa, na = agg(dfa, c); sb, nb = agg(dfb, c)
    est = sa.sum() / na.sum() - sb.sum() / nb.sum()
    with np.errstate(invalid="ignore", divide="ignore"):
        bs = (W @ sa) / (W @ na) - (W @ sb) / (W @ nb)
    bs = bs[np.isfinite(bs)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return est, lo, hi, len(bs)

def diffs(df, key, pos_lab, neg_lab, label):
    out = []
    for h in HS:
        c = f"fwd{h}"; W = date_weights(h)
        d = df.dropna(subset=[c]); low = d[d["low_rv"]]
        scopes = [("POOLED", low)] + [(t, low[low["ticker"] == t]) for t in TICKERS]
        for sc, L in scopes:
            A = L[L[key] == pos_lab]
            for cmp_lab, Bset in ((neg_lab, L[L[key] == neg_lab]), ("all_low_rv", L)):
                if len(A) < 2 or len(Bset) < 2:
                    out.append({"variant": label, "h": h, "scope": sc, "contrast": f"{pos_lab} - {cmp_lab}",
                                "n_a": len(A), "n_b": len(Bset), "est": np.nan, "ci_lo": np.nan, "ci_hi": np.nan,
                                "excludes_zero": None}); continue
                est, lo, hi, nb = diff_ci(A, Bset, c, W)
                out.append({"variant": label, "h": h, "scope": sc, "contrast": f"{pos_lab} - {cmp_lab}",
                            "n_a": len(A), "n_b": len(Bset), "est": est, "ci_lo": lo, "ci_hi": hi,
                            "excludes_zero": bool(lo > 0 or hi < 0)})
    return pd.DataFrame(out)

full = P
lf = P[P["n_after"] == 0]
print("leak-free ticker-days:", len(lf), "of", len(P), "; ticker-days with no chunk-article record (excluded from leak-free):",
      int((P["n_after"] == -1).sum()))
gt = pd.concat([group_table(full, "bucket", "sentiment_full"), group_table(lf, "bucket", "sentiment_leakfree"),
                group_table(full, "mom", "momentum5_full")])
save(gt, "s2_group_table.csv")
dt = pd.concat([diffs(full, "bucket", "bullish", "neutral", "sentiment_full"),
                diffs(lf, "bucket", "bullish", "neutral", "sentiment_leakfree"),
                diffs(full, "mom", "up5", "down5", "momentum5_full")])
save(dt, "s2_differences_bootstrap.csv")
pd.set_option("display.width", 250)
print(gt[(gt["regime"] == "low_rv")].round(5).to_string(index=False))
print(dt[dt["scope"] == "POOLED"].round(5).to_string(index=False))
print(dt[(dt["scope"] != "POOLED") & (dt["contrast"] == "bullish - all_low_rv") & (dt["variant"] == "sentiment_full")].round(4).to_string(index=False))
# ---------- correlations ----------
cr = []
for scope, d in (("all_days", P), ("low_rv", P[P["low_rv"]])):
    for v in ["trail1", "trail5"] + [f"fwd{h}" for h in HS]:
        x = d[["sent", v]].dropna()
        cr.append({"scope": scope, "vs": v, "n": len(x), "pearson": x["sent"].corr(x[v]),
                   "spearman": x["sent"].corr(x[v], method="spearman")})
cr = pd.DataFrame(cr); save(cr, "s2_correlations.csv"); print(cr.round(4).to_string(index=False))
print("per-ticker n ticker-days / low-rv / low-rv bullish:")
print(P.groupby("ticker").agg(n=("date", "size"), low=("low_rv", "sum"),
                              low_bull=("bucket", lambda s: int(((s == "bullish") & P.loc[s.index, "low_rv"]).sum()))).to_string())

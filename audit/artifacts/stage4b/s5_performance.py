# Stage 4b sections 5, 6, 7 -- performance recompute, effective N, exposure. Read-only.
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from s1_checks import wf_replay
pd.set_option("display.width", 250)

prices = load_prices()
CAL = prices["SPY"].index            # trading-day calendar from the snapshot
START = pd.Timestamp("2025-05-08")

def build_sets(kind):
    if kind == "canonical":
        flat = load_logs(RUN_A, ""); r3h = load_logs(RUN_A, "_kelly"); r3w = load_logs(RUN_B, "_kelly")
        wf = pd.read_csv(os.path.join(OUT, "wf_eval_canonical.csv"), parse_dates=["entry_date", "exit_date"])
    else:
        flat = load_logs(RAW, ""); r3w = load_logs(RAW, "_kelly")
        r3h = r3w.copy()                                  # proxy: original HEAD _kelly logs were overwritten (04a 6.2)
        m = (r3h["ticker"] == "UNH") & (r3h["signal"] == "BUY PUTS")
        r3h.loc[m, ["contracts", "pnl_total"]] = [0, 0.0]
        wf = pd.read_csv(os.path.join(OUT, "wf_eval_original.csv"), parse_dates=["entry_date", "exit_date"])
    wf["accepted"] = wf["accepted"].astype(bool)
    return {"flat": (flat, taken_flat(flat), 10_000.0),
            "R3_HEAD" + ("" if kind == "canonical" else "_proxy"): (r3h, taken_kelly(r3h), NOTIONAL),
            "R3_WT": (r3w, taken_kelly(r3w), NOTIONAL),
            "WF": (wf, wf["wf_contracts"] > 0, NOTIONAL)}

def repo_sharpe_dd(pnl):
    std = pnl.std(ddof=1)
    sh = pnl.mean() / std * math.sqrt(252 / 5) if std > 0 else 0.0
    cum = pnl.cumsum(); dd = float((cum - cum.cummax()).min())
    return sh, dd

def daily_series(t):
    end = max(t["exit_date"].max(), pd.Timestamp("2026-05-04"))
    days = CAL[(CAL >= START) & (CAL <= end)]
    s = t.groupby(pd.to_datetime(t["exit_date"]).dt.normalize())["pnl_total"].sum()
    return s.reindex(days, fill_value=0.0)

def block_boot_sharpe(x, L=10, B=2000):
    rng = np.random.default_rng(0)
    n = len(x); k = math.ceil(n / L); x = np.asarray(x)
    out = np.empty(B)
    for b in range(B):
        st = rng.integers(0, n - L + 1, size=k)
        s = np.concatenate([x[i:i + L] for i in st])[:n]
        sd = s.std(ddof=1)
        out[b] = s.mean() / sd * math.sqrt(252) if sd > 0 else np.nan
    return np.nanpercentile(out, [2.5, 97.5])

# ---------- section 6 helpers ----------
def concurrency(t):
    days = CAL[(CAL >= START) & (CAL <= pd.Timestamp("2026-05-04"))]
    per = {}
    tot = np.zeros(len(days))
    for tk, g in t.groupby("ticker"):
        c = np.zeros(len(days))
        for r in g.itertuples():
            c += (days >= r.entry_date) & (days < r.exit_date)
        per[tk] = c.mean(); tot += c
    return tot.mean(), per

def indep_trades(t):
    """Greedy count of non-overlapping trades per ticker (entry >= previous kept exit)."""
    n = 0
    for _, g in t.sort_values("entry_date").groupby("ticker"):
        last = pd.Timestamp.min
        for r in g.itertuples():
            if r.entry_date >= last:
                n += 1; last = r.exit_date
    return n

def neff_entropy(corr):
    lam = np.clip(np.linalg.eigvalsh(corr), 1e-12, None); p = lam / lam.sum()
    return float(np.exp(-(p * np.log(p)).sum()))

rets = pd.DataFrame({t: np.log(prices[t] / prices[t].shift(1)) for t in TICKERS})
win = rets[(rets.index >= START) & (rets.index <= pd.Timestamp("2026-05-04"))].dropna()
n6 = [{"window": "2025-05-08..2026-05-04 (full)", "n_days": len(win), "N_eff_10": neff_entropy(win.corr().values),
       "mean_pairwise_corr": win.corr().values[np.triu_indices(10, 1)].mean()},
      {"window": "60 trading days to 2026-04-24 (PROJECT_STATE basis)",
       "n_days": 60, "N_eff_10": neff_entropy(rets[rets.index <= pd.Timestamp("2026-04-24")].dropna().iloc[-60:].corr().values),
       "mean_pairwise_corr": np.nan}]
save(win.corr().round(3), "s6_corr_full_window.csv")

perf, sens, eff = [], {}, []
for kind in ("canonical", "original"):
    for nm, (df, tk, cap) in build_sets(kind).items():
        t = df[tk].copy()
        # (a) repo method: all rows, file/eval order (r3_baseline.headline / audit_walkforward.headline)
        if nm == "WF":
            allrows = df.sort_values("entry_date", kind="quicksort").copy()   # eval rows already in entry order
            allrows = df
        else:
            allrows = df
        sh_repo, dd_repo = repo_sharpe_dd(allrows["pnl_total"].fillna(0.0))
        sh_taken, dd_taken = repo_sharpe_dd(t["pnl_total"])
        ds = daily_series(t)
        sd = ds.std(ddof=1); sr_d = ds.mean() / sd if sd > 0 else 0.0
        sh_daily = sr_d * math.sqrt(252)
        cum = ds.cumsum(); dd_date = float((cum - cum.cummax()).min())
        lo, hi = block_boot_sharpe(ds.values)
        se = math.sqrt((1 + 0.5 * sr_d ** 2) / len(ds)) * math.sqrt(252)
        n = len(t); mu = t["pnl_total"].mean(); sdv = t["pnl_total"].std(ddof=1)
        ni = indep_trades(t)
        conc_tot, conc_per = concurrency(t)
        traded = sorted(t["ticker"].unique())
        nef_tr = neff_entropy(win[traded].corr().values) if len(traded) > 1 else 1.0
        n_eff = ni * nef_tr / len(traded)
        row = {"logs": kind, "set": nm, "capital_base": cap, "rows_all": len(allrows), "trades": n,
               "total_pnl": t["pnl_total"].sum(), "return_on_capital": t["pnl_total"].sum() / cap,
               "sharpe_repo_all_rows": sh_repo, "sharpe_repo_taken_only": sh_taken,
               "sharpe_daily_exit_series": sh_daily, "daily_ci95_lo": lo, "daily_ci95_hi": hi,
               "ci_excludes_zero": bool(lo > 0 or hi < 0), "analytic_se_ann": se,
               "analytic_ci_lo": sh_daily - 1.96 * se, "analytic_ci_hi": sh_daily + 1.96 * se,
               "analytic_excludes_zero": bool(sh_daily - 1.96 * se > 0 or sh_daily + 1.96 * se < 0),
               "dd_repo_order": dd_repo, "dd_date_ordered_daily": dd_date, "n_days": len(ds),
               "mean_per_trade": mu, "std_per_trade": sdv, "t_naive": mu / sdv * math.sqrt(n),
               "n_independent_in_time": ni, "N_eff_traded_tickers": nef_tr, "n_eff": n_eff,
               "t_eff": mu / sdv * math.sqrt(n_eff), "avg_concurrent_portfolio": conc_tot}
        perf.append(row)
        if kind == "canonical":
            eff.append({"set": nm, **{f"conc_{k}": round(v, 3) for k, v in conc_per.items()}, "conc_portfolio": round(conc_tot, 3),
                        "trades": n, "indep_in_time": ni, "traded_tickers": len(traded), "N_eff_traded": round(nef_tr, 3),
                        "n_eff": round(n_eff, 1)})
P = pd.DataFrame(perf); save(P.round(4), "s5_performance.csv")
cols = ["logs", "set", "trades", "total_pnl", "sharpe_repo_all_rows", "sharpe_repo_taken_only", "sharpe_daily_exit_series",
        "daily_ci95_lo", "daily_ci95_hi", "analytic_ci_lo", "analytic_ci_hi", "dd_repo_order", "dd_date_ordered_daily"]
print(P[cols].round(3).to_string(index=False))
print(P[["logs", "set", "mean_per_trade", "std_per_trade", "t_naive", "n_eff", "t_eff", "return_on_capital", "n_days"]].round(3).to_string(index=False))
# 5e differences canonical - original (R3_HEAD vs R3_HEAD_proxy)
c = P[P["logs"] == "canonical"].set_index("set"); o = P[P["logs"] == "original"].copy()
o["set"] = o["set"].str.replace("_proxy", ""); o = o.set_index("set")
num = [k for k in cols if k not in ("logs", "set")]
D = (c[num] - o[num]); D.index.name = "set"; save(D.round(4), "s5e_canonical_minus_original.csv"); print(D.round(3).to_string())
E = pd.DataFrame(eff); save(E, "s6_effective_n.csv"); print(E.T.to_string())
N6 = pd.DataFrame(n6); save(N6.round(3), "s6_neff_cross_ticker.csv"); print(N6.round(3).to_string(index=False))

# ---------- section 7: aggregate open risk ----------
days = CAL[(CAL >= START) & (CAL <= pd.Timestamp("2026-06-30"))]
ex = []
for nm, (df, tk, cap) in build_sets("canonical").items():
    if nm == "flat":
        continue
    t = df[tk].copy()
    risk = (t["contracts"] * t["max_loss"] * 100.0) if nm == "WF" else t["total_risk"]
    agg = np.zeros(len(days)); per = {}
    for tkr in TICKERS:
        per[tkr] = np.zeros(len(days))
    for r, rk in zip(t.itertuples(), risk):
        m = (days >= r.entry_date) & (days < r.exit_date)       # engine.py:774-779 prune semantics
        agg += m * rk; per[r.ticker] += m * rk
    pct = agg / NOTIONAL * 100
    act = pct[(days <= pd.Timestamp("2026-05-04"))]
    ex.append({"set": nm, "peak_pct_of_100k": pct.max(), "peak_date": str(days[pct.argmax()].date()),
               "mean_pct_window": act.mean(), "days_above_6pct": int((pct > 6).sum()),
               "max_single_ticker_pct": max(v.max() for v in per.values()) / NOTIONAL * 100})
    save(pd.DataFrame({"date": days, "open_risk_pct": pct}), f"s7_open_risk_daily_{nm}.csv")
X = pd.DataFrame(ex); save(X.round(3), "s7_exposure.csv"); print(X.round(3).to_string(index=False))

# Stage 4b sections 3, 4, 8, 9, 10, 11 -- trade-level analyses. Read-only.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from s1_checks import kelly_stats
pd.set_option("display.width", 250)

prices = load_prices()
day = news_day_table().set_index(["ticker", "date"])
flat = load_logs(RUN_A, ""); r3h = load_logs(RUN_A, "_kelly"); r3w = load_logs(RUN_B, "_kelly")
wf = pd.read_csv(os.path.join(OUT, "wf_eval_canonical.csv"), parse_dates=["entry_date", "exit_date"])
wf["accepted"] = wf["accepted"].astype(bool)
flat_o = load_logs(RAW, "")

def after_share(r):
    k = (r["ticker"], pd.Timestamp(r["entry_date"]).normalize())
    return float(day.loc[k, "frac_after"]) if k in day.index else np.nan
def bucket(x):
    if pd.isna(x): return "no_article_record"
    if x == 0: return "none"
    return "<50%" if x < 0.5 else ">=50%"

sets = {"flat_BUY_CALLS": flat[taken_flat(flat) & (flat["signal"] == "BUY CALLS")].copy(),
        "flat_BUY_PUTS": flat[taken_flat(flat) & (flat["signal"] == "BUY PUTS")].copy(),
        "WF_BUY_CALLS": wf[(wf["wf_contracts"] > 0) & (wf["signal"] == "BUY CALLS")].copy()}
# ---------------- section 3: leak concentration ----------------
rows = []
for nm, t in sets.items():
    t["after_share"] = t.apply(after_share, axis=1); t["leak_bucket"] = t["after_share"].map(bucket)
    for b, g in t.groupby("leak_bucket"):
        rows.append({"set": nm, "bucket": b, "n": len(g), "total_pnl": round(g["pnl_total"].sum(), 2),
                     "mean_pnl": round(g["pnl_total"].mean(), 2), "win_rate": round((g["pnl_total"] > 0).mean(), 3)})
s3 = pd.DataFrame(rows); save(s3, "s3_leak_concentration.csv"); print("== S3\n", s3.to_string(index=False))

# ---------------- section 4: beta ----------------
a, b = pd.Timestamp("2025-05-08"), pd.Timestamp("2026-05-04")
tr = pd.DataFrame([{"ticker": t, "close_2025_05_08": prices[t].loc[a], "close_2026_05_04": prices[t].loc[b],
                    "total_return": prices[t].loc[b] / prices[t].loc[a] - 1} for t in TICKERS])
save(tr.round(4), "s4_ticker_total_returns.csv"); print("== S4 returns\n", tr.round(4).to_string(index=False))
br = []
for nm in ("flat_BUY_CALLS", "WF_BUY_CALLS"):
    t = sets[nm].copy()
    t["und_ret"] = [prices[r.ticker].loc[pd.Timestamp(r.exit_date).normalize()] / prices[r.ticker].loc[pd.Timestamp(r.entry_date).normalize()] - 1
                    for r in t.itertuples()]
    spy = prices["SPY"]
    t["spy_ret"] = [spy.loc[pd.Timestamp(r.exit_date).normalize()] / spy.loc[pd.Timestamp(r.entry_date).normalize()] - 1 for r in t.itertuples()]
    br.append({"set": nm, "n": len(t), "corr_pnl_total_vs_underlying_ret": t["pnl_total"].corr(t["und_ret"]),
               "corr_pnl_pct_vs_underlying_ret": t["pnl_pct"].corr(t["und_ret"]),
               "spearman_pnl_vs_underlying": t["pnl_total"].corr(t["und_ret"], method="spearman"),
               "corr_pnl_total_vs_SPY_ret": t["pnl_total"].corr(t["spy_ret"]),
               "share_trades_underlying_up": (t["und_ret"] > 0).mean(),
               "win_rate_when_up": (t.loc[t["und_ret"] > 0, "pnl_total"] > 0).mean(),
               "win_rate_when_down": (t.loc[t["und_ret"] <= 0, "pnl_total"] > 0).mean()})
    byt = t.groupby("ticker")["pnl_total"].agg(["count", "sum"]).sort_values("sum", ascending=False)
    tot = byt["sum"].sum(); top2 = byt["sum"].iloc[:2].sum()
    byt["share_of_total"] = byt["sum"] / tot
    save(byt.round(4), f"s4_pnl_by_ticker_{nm}.csv")
    print(f"== S4 {nm} by ticker (total {tot:.2f}; top-2 {list(byt.index[:2])} = {top2:.2f} = {top2/tot:.1%})\n", byt.round(3).to_string())
    br[-1].update({"total_pnl": tot, "top2": ",".join(byt.index[:2]), "top2_share": top2 / tot})
br = pd.DataFrame(br); save(br.round(4), "s4_beta.csv"); print(br.round(4).T.to_string())

# ---------------- section 8: exits and friction ----------------
ex = []
def add_exit(nm, t):
    for (st, er), g in t.groupby(["strategy_type", "exit_reason"]):
        ex.append({"set": nm, "strategy": st, "exit_reason": er, "n": len(g), "pnl": round(g["pnl_total"].sum(), 2)})
tsets = {"flat": flat[taken_flat(flat)], "R3_HEAD": r3h[taken_kelly(r3h)], "R3_WT": r3w[taken_kelly(r3w)],
         "WF": wf[wf["wf_contracts"] > 0]}
fr = []
for nm, t in tsets.items():
    t = t.copy(); add_exit(nm, t)
    d0 = t[t["days_held"] == 0]
    ent = (t["long_price"] / 1.015 * 0.015 + t["short_price"] / 0.985 * 0.015) * 100.0 * t["contracts"]
    exf = []
    for _, r in t.iterrows():
        lv, sv = leg_marks(r, prices, "exit"); exf.append(0.015 * (lv + sv) * 100.0 * r["contracts"])
    exf = np.array(exf)
    net = t["pnl_total"].sum(); gross = net + ent.sum()
    fr.append({"set": nm, "trades": len(t), "days_held_0_n": len(d0), "days_held_0_pnl": round(d0["pnl_total"].sum(), 2),
               "net_pnl": round(net, 2), "entry_friction_$": round(ent.sum(), 2), "gross_pnl_pre_friction": round(gross, 2),
               "entry_friction_pct_of_gross": round(100 * ent.sum() / abs(gross), 1),
               "exit_friction_$": round(exf.sum(), 2), "pnl_with_exit_friction": round(net - exf.sum(), 2),
               "min_days_held": int(t["days_held"].min())})
ex = pd.DataFrame(ex); save(ex, "s8_exit_mix.csv"); print("== S8 exits\n", ex.pivot_table(index=["strategy", "exit_reason"], columns="set", values="n", aggfunc="sum").to_string())
fr = pd.DataFrame(fr); save(fr, "s8_friction.csv"); print(fr.to_string(index=False))

# ---------------- section 9: earnings exposure ----------------
earn = load_earnings()
e_rows = []
for nm, t in (("flat_BUY_CALLS (= R3 HEAD set)", sets["flat_BUY_CALLS"]), ("WF_BUY_CALLS", sets["WF_BUY_CALLS"])):
    t = t[t["ticker"].isin(SINGLE)].copy()
    def win(r):
        dts = earn.get(r["ticker"], [])
        d = pd.Timestamp(r["entry_date"]).normalize()
        e = min(dts, key=lambda x: abs((x - d).days))
        delta = (e - d).days
        if -1 <= delta <= 3: return delta, "SUPPRESS"     # earnings_filter.py:204-246; IV_CRUSH needs iv>=0.80, impossible with rank<0.30
        return delta, "outside"
    w = t.apply(win, axis=1, result_type="expand"); t["delta"] = w[0]; t["window"] = w[1]
    t["after_share"] = t.apply(after_share, axis=1)
    ins = t[t["window"] == "SUPPRESS"]
    e_rows.append({"set": nm, "single_name_trades": len(t), "in_suppress_window": len(ins),
                   "pnl_in_window": round(ins["pnl_total"].sum(), 2), "pnl_outside": round(t.loc[t['window'] == 'outside', 'pnl_total'].sum(), 2),
                   "in_window_with_after_close_articles": int((ins["after_share"] > 0).sum()),
                   "by_ticker": ins.groupby("ticker")["pnl_total"].agg(["count", "sum"]).round(0).to_dict("index")})
    save(ins[["ticker", "entry_date", "delta", "pnl_total", "after_share"]], f"s9_trades_in_window_{nm.split()[0]}.csv")
e_rows = pd.DataFrame(e_rows); save(e_rows, "s9_earnings_exposure.csv"); print("== S9\n", e_rows.to_string(index=False))

# ---------------- section 10: OOS boundary ----------------
tr_fold = flat[flat["entry_date"] <= CUTOFF]
acc = tr_fold[tr_fold["accepted"]]
spill = acc[acc["exit_date"] > CUTOFF]
s_all = kelly_stats(tr_fold); s_clean = kelly_stats(tr_fold[~tr_fold.index.isin(spill.index)])
o10 = pd.DataFrame([{"variant": "train fold as in audit (entry<=cutoff)", **{f"{k}_{m}": v[m] for k, v in s_all.items() for m in ("count", "kelly_f")}},
                    {"variant": "excluding trades exiting after cutoff", **{f"{k}_{m}": v[m] for k, v in s_clean.items() for m in ("count", "kelly_f")}}])
o10["n_spill"] = len(spill); o10["spill_by_signal"] = str(spill["signal"].value_counts().to_dict())
save(o10, "s10_oos_boundary.csv"); print("== S10\n", o10.T.to_string())

# ---------------- section 11: truncation and width-0 ----------------
tr17 = flat_o[(flat_o["exit_reason"] == "expiration") & (pd.to_datetime(flat_o["exit_date"]) < pd.to_datetime(flat_o["expiration"]))]
m = tr17.merge(flat, on=["ticker", "entry_date"], suffixes=("_orig", "_canon"))
t11 = m[["ticker", "entry_date", "signal_orig", "exit_date_orig", "exit_reason_orig", "pnl_total_orig",
         "exit_date_canon", "exit_reason_canon", "pnl_total_canon"]].copy()
t11["diff"] = t11["pnl_total_canon"] - t11["pnl_total_orig"]
save(t11, "s11_truncated_trades.csv"); print("== S11 truncated\n", t11.to_string(index=False)); print("net diff:", round(t11["diff"].sum(), 2), "n:", len(t11))
w0 = []
for nm, df in (("canonical", flat), ("original", flat_o)):
    z = df[df["rejection_reason"].astype(str).str.contains("degenerate width")]
    for tk, g in z.groupby("ticker"):
        w0.append({"logs": nm, "ticker": tk, "n_width0": len(g), "signals": str(g["signal"].value_counts().to_dict())})
w0 = pd.DataFrame(w0); save(w0, "s11_width0.csv"); print(w0.to_string(index=False))
sh = []
for nm, t in (("flat_BUY_CALLS", sets["flat_BUY_CALLS"]), ("R3_HEAD", r3h[taken_kelly(r3h)]), ("WF_BUY_CALLS", sets["WF_BUY_CALLS"])):
    tot = t["pnl_total"].sum(); sub = t[t["ticker"].isin(["TLT", "WMT", "XOM"])]["pnl_total"].sum()
    sh.append({"set": nm, "total": round(tot, 2), "TLT_WMT_XOM": round(sub, 2), "share": round(sub / tot, 3),
               "ex_TLT_WMT_XOM": round(tot - sub, 2)})
sh = pd.DataFrame(sh); save(sh, "s11_sub100_share.csv"); print(sh.to_string(index=False))

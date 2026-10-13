# Stage 4b section 1: consistency checks, walk-forward reconstruction, composition,
# commission / exit-friction sensitivity. Read-only; writes CSVs to stage4b/.
import sys, os, math
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

# ---------- walk-forward reconstruction (extends audit/artifacts/stage3/t3_wf_kelly_replay.py) ----------
def kelly_stats(df):
    """signals/position_sizer.py:264-306, incl. 4-dp rounding of kelly_f."""
    out = {}
    df = df[df["accepted"]]
    for sig, g in df.groupby("signal"):
        r = g["pnl_pct"].astype(float) / 100.0
        w, l, n = r[r > 0], r[r < 0], len(r)
        p = len(w) / n if n else 0.0
        aw = float(w.mean()) if len(w) else 0.0
        al = float(abs(l.mean())) if len(l) else 0.0
        if al > 0 and aw > 0:
            W = aw / al; f = (W * p - (1 - p)) / W
        else:
            f = 0.0
        out[sig] = {"count": n, "kelly_f": round(f, 4), "win_rate": round(p, 4)}
    return out

def wf_replay(flat):
    """scripts/audit_walkforward.py:314-420 with uniform sizing (position_sizer.py:526-625, open_risk=0)."""
    flat = flat.sort_values("entry_date").reset_index(drop=True)
    acc = flat[flat["accepted"]].copy().sort_values("exit_date").reset_index(drop=True)
    last_n, stats, rows, excl, refits = -1, None, [], 0, 0
    for _, row in flat.iterrows():
        T = row["entry_date"]
        n = int((acc["exit_date"] < T).sum())
        if n < 50:
            excl += 1; continue
        if n != last_n:
            stats = kelly_stats(acc.iloc[:n]); last_n = n; refits += 1
        d = row.to_dict()
        if not row["accepted"]:
            d.update(wf_contracts=0, wf_reason="rejected_risk_reward", pnl_total=0.0); rows.append(d); continue
        ml = float(row.get("max_loss", 0.0) or 0.0)
        if ml <= 0:
            d.update(wf_contracts=0, wf_reason="invalid_max_loss", pnl_total=0.0); rows.append(d); continue
        s = stats.get(row["signal"], {})
        if s and int(s["count"]) >= 10 and float(s["kelly_f"]) <= 0:
            d.update(wf_contracts=0, wf_reason=f"negative_kelly_{row['signal']}", pnl_total=0.0); rows.append(d); continue
        per_trade = min(0.0038, 0.02)
        budget = min(per_trade * NOTIONAL, max(0.06 * NOTIONAL - 0.0, 0.0))
        c = max(int(math.floor(budget / (ml * 100.0))), 1)
        d.update(wf_contracts=c, wf_reason="ok", pnl_total=float(row["pnl"]) * 100.0 * c)
        rows.append(d)
    ev = pd.DataFrame(rows)
    ev["contracts"] = ev["wf_contracts"]
    return ev, excl, refits

def summarize(name, df, taken):
    t = df[taken]
    return {"set": name, "rows": len(df), "taken": int(taken.sum()), "pnl": round(float(t["pnl_total"].sum()), 2)}

if __name__ == "__main__":
    prices = load_prices()
    flat_c = load_logs(RUN_A, ""); r3h = load_logs(RUN_A, "_kelly"); r3w = load_logs(RUN_B, "_kelly")
    flat_o = load_logs(RAW, ""); r3w_o = load_logs(RAW, "_kelly")
    wf_c, ex_c, rf_c = wf_replay(flat_c)
    wf_o, ex_o, rf_o = wf_replay(flat_o)
    wf_c.to_csv(os.path.join(OUT, "wf_eval_canonical.csv"), index=False)
    wf_o.to_csv(os.path.join(OUT, "wf_eval_original.csv"), index=False)
    chk = []
    def add(name, got, exp, ok):
        chk.append({"check": name, "got": got, "expected": exp, "pass": bool(ok)})
    wtc = wf_c["wf_contracts"] > 0; wto = wf_o["wf_contracts"] > 0
    add("3a WF canonical trades/pnl", f"{int(wtc.sum())} / {wf_c.loc[wtc,'pnl_total'].sum():.2f}", "249 / 8340.87",
        int(wtc.sum()) == 249 and abs(wf_c.loc[wtc, "pnl_total"].sum() - 8340.87) < 0.01)
    add("3a WF canonical warmup/refits", f"{ex_c} / {rf_c}", "102 / (report)", ex_c == 102)
    add("3b WF original trades/pnl", f"{int(wto.sum())} / {wf_o.loc[wto,'pnl_total'].sum():.2f}", "246 / 7786.22",
        int(wto.sum()) == 246 and abs(wf_o.loc[wto, "pnl_total"].sum() - 7786.22) < 0.01)
    add("3b WF original warmup/refits", f"{ex_o} / {rf_o}", "99 / 134", ex_o == 99 and rf_o == 134)
    for nm, df, tk, en, ep in [("flat", flat_c, taken_flat(flat_c), 452, -19743.51),
                               ("R3 HEAD", r3h, taken_kelly(r3h), 298, 10216.57),
                               ("R3 WT", r3w, taken_kelly(r3w), 315, 13183.91)]:
        s = summarize(nm, df, tk)
        add(f"3c {nm} taken/pnl", f"{s['taken']} / {s['pnl']:.2f}", f"{en} / {ep}", s["taken"] == en and abs(s["pnl"] - ep) < 0.01)
    # 3d RV rank
    mism, n = [], 0
    for df in (flat_c,):
        for t, g in df.groupby("ticker"):
            rv = rv_rank_frame(prices[t])
            for _, r in g.iterrows():
                d = pd.Timestamp(r["entry_date"]).normalize()
                n += 1
                x = float(rv.loc[d, "iv_rank"])
                if abs(round(x, 4) - float(r["iv_rank"])) > 1e-9:
                    mism.append((t, str(d.date()), x, r["iv_rank"]))
    add("3d RV rank (recomputed rounded to 4dp == logged 4dp)", f"{n - len(mism)}/{n} match", "all", len(mism) == 0)
    chk = pd.DataFrame(chk); save(chk, "s1_consistency_checks.csv"); print(chk.to_string(index=False))
    if mism:
        print("RV mismatches:", mism[:10])
    # composition
    sets = {"flat": (flat_c, taken_flat(flat_c)), "R3_HEAD": (r3h, taken_kelly(r3h)),
            "R3_WT": (r3w, taken_kelly(r3w)), "WF": (wf_c, wf_c["wf_contracts"] > 0)}
    comp = []
    for nm, (df, tk) in sets.items():
        t = df[tk]
        for (sig, tic), g in t.groupby(["signal", "ticker"]):
            comp.append({"set": nm, "signal": sig, "ticker": tic, "n": len(g), "pnl": round(g["pnl_total"].sum(), 2)})
    comp = pd.DataFrame(comp); save(comp, "s1_composition.csv")
    print(comp.pivot_table(index=["signal", "ticker"], columns="set", values="pnl", aggfunc="sum").round(0).to_string())
    print(comp.groupby(["set", "signal"])[["n", "pnl"]].sum().to_string())
    # bypass contribution
    h = r3h[taken_kelly(r3h)].set_index(["ticker", "entry_date"]); w = r3w[taken_kelly(r3w)].set_index(["ticker", "entry_date"])
    only_w = w.index.difference(h.index); only_h = h.index.difference(w.index)
    common_ix = h.index.intersection(w.index)
    byp = pd.DataFrame([{"item": "R3_WT minus R3_HEAD total", "pnl": round(w["pnl_total"].sum() - h["pnl_total"].sum(), 2)},
                        {"item": f"trades only in WT (n={len(only_w)})", "pnl": round(w.loc[only_w, "pnl_total"].sum(), 2)},
                        {"item": f"trades only in HEAD (n={len(only_h)})", "pnl": round(-h.loc[only_h, "pnl_total"].sum(), 2)},
                        {"item": f"common trades P&L change (n={len(common_ix)})", "pnl": round((w.loc[common_ix, 'pnl_total'] - h.loc[common_ix, 'pnl_total']).sum(), 2)}])
    print(byp.to_string(index=False)); print("only_w signals:", w.loc[only_w, "signal"].value_counts().to_dict(),
                                              "only_h:", list(only_h))
    save(byp, "s1_bypass_contribution.csv")
    fbc = set(map(tuple, flat_c[taken_flat(flat_c) & (flat_c["signal"] == "BUY CALLS")][["ticker", "entry_date"]].astype(str).values))
    hbc = set(map(tuple, r3h[taken_kelly(r3h)][["ticker", "entry_date"]].astype(str).values))
    print("R3 HEAD set == flat BUY CALLS set:", fbc == hbc, len(fbc), len(hbc), "HEAD signals:", r3h[taken_kelly(r3h)]["signal"].value_counts().to_dict())
    # commissions + exit friction
    rows = []
    for nm, (df, tk) in sets.items():
        t = df[tk].copy()
        base = t["pnl_total"].sum()
        comm = (4 * 0.65 * t["contracts"]).sum()
        ef = []
        for _, r in t.iterrows():
            lv, sv = leg_marks(r, prices, "exit")
            ef.append(0.015 * (lv + sv) * 100.0 * r["contracts"])
        ef = float(np.nansum(ef)); n_nan = int(np.isnan(np.array([0.0])).sum())
        rows.append({"set": nm, "trades": len(t), "pnl": round(base, 2), "commission_$": round(comm, 2),
                     "pnl_after_comm": round(base - comm, 2), "comm_pct_of_pnl": round(100 * comm / abs(base), 1),
                     "exit_friction_$": round(ef, 2), "pnl_after_comm_and_exit_friction": round(base - comm - ef, 2),
                     "comm_plus_friction_pct_of_pnl": round(100 * (comm + ef) / abs(base), 1)})
    cf = pd.DataFrame(rows); save(cf, "s1_commission_friction.csv"); print(cf.to_string(index=False))

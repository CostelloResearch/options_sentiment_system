# Stage 4a: trade-level diff of reproduced vs on-disk trade logs. Read-only; stdout only.
# Usage: python -I diff_trades.py <orig_raw_dir> <repro_raw_dir> <suffix: "" | "_kelly"> [--drop-unh-bp-orig]
import sys, os, glob, re
import numpy as np
import pandas as pd

orig_dir, rep_dir, suffix = sys.argv[1], sys.argv[2], sys.argv[3]
drop_unh = "--drop-unh-bp-orig" in sys.argv
rx = re.compile(r"^backtest_([A-Z]+)" + re.escape(suffix) + r"\.csv$")

def load(d):
    fs = [f for f in glob.glob(os.path.join(d, "backtest_*.csv")) if rx.match(os.path.basename(f))]
    df = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    df["entry_date"] = pd.to_datetime(df["entry_date"]).dt.date
    return df

o, r = load(orig_dir), load(rep_dir)
taken = lambda d: d["accepted"].astype(bool) & (d["contracts"].fillna(0) > 0)
if drop_unh:
    m = (o["ticker"] == "UNH") & (o["signal"] == "BUY PUTS")
    o.loc[m, ["contracts", "pnl_total"]] = [0, 0.0]
    o.loc[m, "kelly_reason"] = "negative_kelly_BUY PUTS(proxy)"
key = ["ticker", "entry_date"]
m = o.merge(r, on=key, how="outer", suffixes=("_o", "_r"), indicator=True)
both = m[m["_merge"] == "both"].copy()
print(f"suffix={suffix!r} orig_rows={len(o)} repro_rows={len(r)} both={len(both)} "
      f"orig_only={int((m['_merge']=='left_only').sum())} repro_only={int((m['_merge']=='right_only').sum())}")
if (m["_merge"] != "both").any():
    print(m.loc[m["_merge"] != "both", key + ["signal_o", "signal_r", "_merge"]].to_string(index=False))

def same(a, b, tol=1e-9):
    return (both[a].fillna(-1e9) - both[b].fillna(-1e9)).abs() <= tol
both["sig_same"] = both["signal_o"] == both["signal_r"]
both["strat_same"] = both["strategy_type_o"].fillna("") == both["strategy_type_r"].fillna("")
both["strikes_same"] = same("long_strike_o", "long_strike_r") & same("short_strike_o", "short_strike_r")
both["acc_same"] = both["accepted_o"].astype(bool) == both["accepted_r"].astype(bool)
both["exit_same"] = both["exit_reason_o"] == both["exit_reason_r"]
both["sent_same"] = same("sentiment_score_o", "sentiment_score_r", 1e-6)
both["S_ratio"] = both["S_entry_r"] / both["S_entry_o"]
both["iv_d"] = both["iv_rank_r"] - both["iv_rank_o"]
full = both["sig_same"] & both["strat_same"] & both["strikes_same"] & both["acc_same"]
print(f"identical (signal, strategy, strikes, accepted): {int(full.sum())}; differing: {int((~full).sum())}")
print(f"signal differs: {int((~both['sig_same']).sum())}; strategy differs: {int((~both['strat_same']).sum())}; "
      f"strikes differ: {int((~both['strikes_same']).sum())}; accepted differs: {int((~both['acc_same']).sum())}; "
      f"exit_reason differs: {int((~both['exit_same']).sum())}; sentiment differs: {int((~both['sent_same']).sum())}")
print("S_entry repro/orig ratio by ticker (min, max):")
print(both.groupby("ticker")["S_ratio"].agg(["min", "max"]).round(6).to_string())
print("iv_rank abs diff by ticker (max):", both.groupby("ticker")["iv_d"].apply(lambda s: round(s.abs().max(), 4)).to_dict())
print("exit_reason transitions (orig -> repro), where different:")
print(both.loc[~both["exit_same"], ["exit_reason_o", "exit_reason_r"]].value_counts().to_string())
print("accepted transitions:", both.loc[~both["acc_same"], ["ticker", "entry_date", "signal_o", "accepted_o", "accepted_r", "rejection_reason_o", "rejection_reason_r"]].to_string(index=False))
# P&L
po = np.where(taken(o), o["pnl_total"], 0.0).sum() if suffix else o.loc[o["accepted"].astype(bool), "pnl_total"].sum()
pr = np.where(taken(r), r["pnl_total"], 0.0).sum() if suffix else r.loc[r["accepted"].astype(bool), "pnl_total"].sum()
print(f"P&L orig={po:.2f} repro={pr:.2f} delta={pr - po:+.2f}")
both["pnl_o"] = both["pnl_total_o"].fillna(0.0); both["pnl_r"] = both["pnl_total_r"].fillna(0.0)
both["dp"] = both["pnl_r"] - both["pnl_o"]
grp = np.select([~both["acc_same"], ~both["strikes_same"], ~both["exit_same"]],
                ["accept/reject flip", "strike change", "exit-reason change"], "same structure+exit")
both["bucket"] = grp
print("P&L delta by bucket:\n", both.groupby("bucket")["dp"].agg(["count", "sum"]).round(2).to_string())
if suffix:
    both["taken_o"] = both["accepted_o"].astype(bool) & (both["contracts_o"].fillna(0) > 0)
    both["taken_r"] = both["accepted_r"].astype(bool) & (both["contracts_r"].fillna(0) > 0)
    print("taken orig:", int(both["taken_o"].sum()), "taken repro:", int(both["taken_r"].sum()))
    print("kelly_reason transitions:\n", both.loc[both["kelly_reason_o"] != both["kelly_reason_r"], ["kelly_reason_o", "kelly_reason_r"]].value_counts().to_string())
    print("contracts differ:", int((both["contracts_o"].fillna(0) != both["contracts_r"].fillna(0)).sum()))
exp_o = both[both["exit_reason_o"] == "expiration"]
print("orig 'expiration' exits:", len(exp_o), " with exit_date before nominal expiration:",
      int((pd.to_datetime(exp_o["exit_date_o"]) < pd.to_datetime(exp_o["expiration_o"])).sum()),
      " their P&L delta:", round(exp_o["dp"].sum(), 2))
print("days_to_earnings: orig 999 share", round((o["days_to_earnings"] == 999).mean(), 3),
      " repro 999 share", round((r["days_to_earnings"] == 999).mean(), 3))

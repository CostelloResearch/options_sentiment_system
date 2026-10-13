# Validate re-derived BS leg marks against the logged entry/exit spread values (read-only).
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
prices = load_prices()
rows = []
for nm, d, suf, tk in [("flat", RUN_A, "", taken_flat), ("R3_WT", RUN_B, "_kelly", taken_kelly)]:
    df = load_logs(d, suf); t = df[tk(df)]
    for _, r in t.iterrows():
        le, se = leg_marks(r, prices, "entry"); lx, sx = leg_marks(r, prices, "exit")
        rows.append({"set": nm, "ticker": r["ticker"], "entry_date": r["entry_date"].date(),
                     "entry_err": (le - se) - r["entry_spread_value"], "exit_err": (lx - sx) - r["exit_spread_value"],
                     "long_fair_entry_vs_logged": le * 1.015 - r["long_price"], "short_fair_entry_vs_logged": se * 0.985 - r["short_price"]})
v = pd.DataFrame(rows); save(v, "s8_mark_validation.csv")
for c in ["entry_err", "exit_err", "long_fair_entry_vs_logged", "short_fair_entry_vs_logged"]:
    print(c, "max abs:", round(v[c].abs().max(), 6), " n>1e-3:", int((v[c].abs() > 1e-3).sum()), "of", len(v))

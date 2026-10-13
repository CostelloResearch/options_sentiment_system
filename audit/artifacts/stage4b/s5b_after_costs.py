# Daily exit-series Sharpe after commissions ($0.65 x 4 leg-sides x contracts) and 1.5%/leg exit friction. Read-only.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from s5_performance import build_sets, daily_series, block_boot_sharpe
import math
prices = load_prices(); rows = []
for nm, (df, tk, cap) in build_sets("canonical").items():
    t = df[tk].copy()
    ef = [0.015 * sum(leg_marks(r, prices, "exit")) * 100.0 * r["contracts"] for _, r in t.iterrows()]
    t["pnl_total"] = t["pnl_total"] - 4 * 0.65 * t["contracts"] - np.array(ef)
    ds = daily_series(t); sd = ds.std(ddof=1); srd = ds.mean() / sd
    lo, hi = block_boot_sharpe(ds.values); se = math.sqrt((1 + 0.5 * srd ** 2) / len(ds)) * math.sqrt(252)
    rows.append({"set": nm, "pnl_after_costs": round(t["pnl_total"].sum(), 2), "sharpe_daily": round(srd * math.sqrt(252), 3),
                 "boot_lo": round(lo, 3), "boot_hi": round(hi, 3), "boot_excludes_zero": bool(lo > 0 or hi < 0),
                 "analytic_lo": round(srd * math.sqrt(252) - 1.96 * se, 3), "analytic_hi": round(srd * math.sqrt(252) + 1.96 * se, 3),
                 "win_rate": round((t["pnl_total"] > 0).mean(), 3)})
R2 = pd.DataFrame(rows); save(R2, "s5b_after_costs.csv"); print(R2.to_string(index=False))

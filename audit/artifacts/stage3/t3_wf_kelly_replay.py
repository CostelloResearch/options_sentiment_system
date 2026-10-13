# T3 (stage 3, read-only): replay the walk-forward Kelly-filter decisions from the
# real flat corpus WITHOUT importing project code. Kelly formula re-implemented from
# signals/position_sizer.py:275-306; filter rule from position_sizer.py:545-556;
# walk-forward slicing from scripts/audit_walkforward.py:314-345.
import sys, os, glob, re
import pandas as pd

RAW = sys.argv[1]
MODE = sys.argv[2] if len(sys.argv) > 2 else "real"
rx = r"^backtest_[A-Z]+\.csv$" if MODE == "real" else r"^backtest_[A-Z]+_demo\.csv$"
fs = [f for f in glob.glob(os.path.join(RAW, "backtest_*.csv")) if re.search(rx, os.path.basename(f))]
flat = pd.concat([pd.read_csv(f, parse_dates=["entry_date", "exit_date"]) for f in fs], ignore_index=True)
flat["accepted"] = flat["accepted"].astype(bool)
MIN_TRADES = 10
WARMUP = 50

def kelly(df):
    out = {}
    for sig, g in df.groupby("signal"):
        r = g["pnl_pct"].astype(float) / 100.0
        w, l, n = r[r > 0], r[r < 0], len(r)
        p = len(w) / n if n else 0.0
        aw = w.mean() if len(w) else 0.0
        al = abs(l.mean()) if len(l) else 0.0
        f = ((aw / al) * p - (1 - p)) / (aw / al) if (aw > 0 and al > 0) else 0.0
        out[sig] = (n, f)
    return out

flat = flat.sort_values("entry_date").reset_index(drop=True)
acc = flat[flat["accepted"]].sort_values("exit_date").reset_index(drop=True)
last_n, stats = -1, None
refits = []
taken = {}
blocked = {}
excluded = 0
for _, row in flat.iterrows():
    T = row["entry_date"]
    n = int((acc["exit_date"] < T).sum())
    if n < WARMUP:
        excluded += 1
        continue
    if n != last_n:
        stats = kelly(acc.iloc[:n])
        refits.append((T, n, stats))
        last_n = n
    if not row["accepted"] or float(row.get("max_loss", 0) or 0) <= 0:
        continue
    s = stats.get(row["signal"])
    sig = row["signal"]
    if s is not None and s[0] >= MIN_TRADES and s[1] <= 0:
        blocked[sig] = blocked.get(sig, 0) + 1
    else:
        taken[sig] = taken.get(sig, 0) + 1

print(f"mode={MODE} flat_rows={len(flat)} accepted={len(acc)} warmup_excluded={excluded} refits={len(refits)}")
print("taken by signal:", taken)
print("blocked (negative Kelly) by signal:", blocked)
bp_en = [(str(t.date()), n, st.get("BUY PUTS")) for t, n, st in refits
         if st.get("BUY PUTS") is None or st["BUY PUTS"][0] < MIN_TRADES or st["BUY PUTS"][1] > 0]
print("refits where BUY PUTS is NOT blocked:", len(bp_en), bp_en[:10])
bc_bl = [(str(t.date()), n, st.get("BUY CALLS")) for t, n, st in refits
         if st.get("BUY CALLS") is not None and st["BUY CALLS"][0] >= MIN_TRADES and st["BUY CALLS"][1] <= 0]
print("refits where BUY CALLS IS blocked:", len(bc_bl), bc_bl[:5])
bp_f = [st["BUY PUTS"][1] for _, _, st in refits if st.get("BUY PUTS")]
if bp_f:
    print("BUY PUTS f* across refits: min %.4f max %.4f" % (min(bp_f), max(bp_f)))
print("first refit:", str(refits[0][0].date()), refits[0][1], refits[0][2])
print("last refit:", str(refits[-1][0].date()), refits[-1][1], refits[-1][2])
# signals with no stats row at evaluation time
print("signals present in flat:", flat["signal"].value_counts().to_dict())

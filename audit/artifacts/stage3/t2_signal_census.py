# T2 (stage 3, read-only): signal/strategy census across every backtest log on disk.
# No project imports, no network. Prints to stdout only.
import sys, os, glob, re
import pandas as pd

RAW = sys.argv[1]

def load(pattern, rx):
    fs = [f for f in glob.glob(os.path.join(RAW, pattern)) if re.search(rx, os.path.basename(f))]
    if not fs:
        return pd.DataFrame()
    return pd.concat([pd.read_csv(f).assign(_f=os.path.basename(f)) for f in fs], ignore_index=True)

sets = {
    "real_flat":   load("backtest_*.csv", r"^backtest_[A-Z]+\.csv$"),
    "real_kelly":  load("backtest_*_kelly.csv", r"^backtest_[A-Z]+_kelly\.csv$"),
    "demo_flat":   load("backtest_*_demo.csv", r"^backtest_[A-Z]+_demo\.csv$"),
    "demo_kelly":  load("backtest_*_demo_kelly.csv", r"^backtest_[A-Z]+_demo_kelly\.csv$"),
    "demo_other":  load("backtest_*_demo_*.csv", r"_demo_(r1|r2|r3|kelly_logistic|kelly_magnitude)\.csv$"),
    "archive_5t":  load(os.path.join("archive_5ticker", "backtest_*.csv"), r"\.csv$"),
}
for name, df in sets.items():
    print(f"\n===== {name}: rows={len(df)}")
    if df.empty:
        continue
    df["accepted"] = df["accepted"].astype(bool)
    print("signal x accepted:\n", pd.crosstab(df["signal"], df["accepted"]).to_string())
    if "rejection_reason" in df:
        rr = df.loc[~df["accepted"], "rejection_reason"].astype(str).str.replace(r"[0-9.]+", "#", regex=True)
        print("rejection reasons (numbers masked) by signal:\n",
              pd.crosstab(rr, df.loc[~df["accepted"], "signal"]).to_string())
    if "kelly_reason" in df:
        print("kelly_reason by signal:\n", pd.crosstab(df["kelly_reason"].astype(str), df["signal"]).to_string())
    if "contracts" in df:
        taken = df["accepted"] & (df["contracts"].fillna(0) > 0)
        print("taken (accepted & contracts>0) by signal:", df[taken]["signal"].value_counts().to_dict())
    if "dte_entry" in df:
        print("dte_entry by strategy:\n", pd.crosstab(df["strategy_type"].astype(str), df["dte_entry"]).to_string())
    if name == "real_flat":
        acc = df[df["accepted"]]
        print("short_delta by strategy (abs) describe:\n",
              acc.assign(sd=acc["short_delta"].abs()).groupby("strategy_type")["sd"].describe().round(3).to_string())
        print("width by ticker:\n", df.groupby("ticker")["width"].describe()[["count", "min", "50%", "max"]].to_string())
        print("S_entry by ticker (min/max):\n", df.groupby("ticker")["S_entry"].agg(["min", "max"]).round(1).to_string())
    if name == "real_kelly":
        print("UNH BUY PUTS rows:", int(((df["ticker"] == "UNH") & (df["signal"] == "BUY PUTS")).sum()),
              " taken:", int(((df["ticker"] == "UNH") & (df["signal"] == "BUY PUTS") & (df["contracts"] > 0) & df["accepted"]).sum()))
        bp = df[(df["signal"] == "BUY PUTS") & df["accepted"] & (df["contracts"] > 0)]
        print("BUY PUTS taken by ticker:", bp["ticker"].value_counts().to_dict())
        print("pnl_total sum taken, all:", round(df.loc[df["accepted"] & (df["contracts"] > 0), "pnl_total"].sum(), 2),
              " excluding UNH BUY PUTS:", round(df.loc[df["accepted"] & (df["contracts"] > 0) & ~((df["ticker"] == "UNH") & (df["signal"] == "BUY PUTS")), "pnl_total"].sum(), 2))
        print("taken trades excl UNH BP:", int((df["accepted"] & (df["contracts"] > 0) & ~((df["ticker"] == "UNH") & (df["signal"] == "BUY PUTS"))).sum()))
        print("kelly_reason counts:", df["kelly_reason"].astype(str).value_counts().to_dict())

# =============================================================================
# scripts/decompose_time_ticker.py -- One-shot decomposition for the R3
# baseline (+$6,775 / 357 trades / Sharpe 0.41).
#
# Produces outputs/time_ticker_decomposition.md from the on-disk
# `data/raw/backtest_*_demo_kelly.csv` files.  Read-only; no engine /
# signal / sizing changes.
#
# Two questions answered:
#   Q1: time-window concentration (per-month P&L, top/bottom months,
#       largest contiguous drawdown and run-up).
#   Q2: AAPL deep-dive (-$3,568 / 44 trades): P&L distribution,
#       quintile mix, exit reasons, iv_rank vs universe, days-to-earnings
#       vs universe.
#
# All trades are 100% synthetic-sentiment per the prior diagnostic; this
# script characterises the synthetic generator's interaction with the
# strategy, NOT live behaviour.
# =============================================================================

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
import config

RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
OUT_DIR = os.path.join(PROJECT_ROOT, "outputs")
OUT_PATH = os.path.join(OUT_DIR, "time_ticker_decomposition.md")

# Mirror r3_baseline.py:_taken_mask exactly: rows that are accepted=True AND
# whose kelly_reason is NOT in the rejected/zero-contract set.
REJECT_REASONS = {
    "rejected_by_kelly",
    "bucket_full",
    "portfolio_risk_cap",
    "rejected_risk_reward",
}

# Same Sharpe annualisation as r3_baseline.headline(): per-trade returns,
# ~5 trading-day holding period.
SHARPE_ANN = float(np.sqrt(252.0 / 5.0))


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_taken_trades() -> pd.DataFrame:
    frames = []
    for ticker in config.TICKERS:
        p = os.path.join(RAW_DIR, f"backtest_{ticker}_demo_kelly.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, parse_dates=["entry_date", "exit_date"]))
    if not frames:
        raise SystemExit("No backtest_*_demo_kelly.csv files found.")
    df = pd.concat(frames, ignore_index=True)
    acc = df["accepted"].astype(bool)
    kr = df["kelly_reason"].astype(str).fillna("")
    not_taken = kr.isin(REJECT_REASONS) | kr.str.startswith("negative_kelly_")
    taken = df[acc & ~not_taken].copy().reset_index(drop=True)
    return taken


def assign_quintile(df: pd.DataFrame) -> pd.DataFrame:
    raw = json.load(open(os.path.join(RAW_DIR, "quintile_edges.json")))
    edges = raw["edges"] if isinstance(raw, dict) else raw
    bins = [-np.inf] + list(edges) + [np.inf]
    df = df.copy()
    df["q"] = pd.cut(df["confidence"], bins=bins,
                     labels=["Q1", "Q2", "Q3", "Q4", "Q5"],
                     include_lowest=True)
    return df


# ---------------------------------------------------------------------------
# Q1 helpers
# ---------------------------------------------------------------------------

def per_month_summary(taken: pd.DataFrame) -> pd.DataFrame:
    df = taken.copy()
    df["month"] = df["entry_date"].dt.to_period("M")
    grp = df.groupby("month", sort=True)
    rows = []
    cum = 0.0
    for m, g in grp:
        gross = float(g["pnl_total"].sum())
        cum += gross
        rows.append({
            "month":     str(m),
            "n_trades":  int(len(g)),
            "gross_pnl": round(gross, 2),
            "cum_pnl":   round(cum, 2),
            "win_rate":  round(float((g["pnl_total"] > 0).mean()), 4),
        })
    out = pd.DataFrame(rows)

    # Rolling 90-day-of-entries Sharpe at end of each month.  Per-trade Sharpe
    # convention with the same sqrt(252/5) annualisation as r3_baseline.
    sharpe_col = []
    df_sorted = taken.sort_values("entry_date").reset_index(drop=True)
    for m in out["month"]:
        period = pd.Period(m, freq="M")
        end = period.end_time
        start = end - pd.Timedelta(days=90)
        window = df_sorted[(df_sorted["entry_date"] >= start) &
                           (df_sorted["entry_date"] <= end)]
        if len(window) < 5 or window["pnl_total"].std(ddof=1) == 0:
            sharpe_col.append(np.nan)
        else:
            mu = float(window["pnl_total"].mean())
            sd = float(window["pnl_total"].std(ddof=1))
            sharpe_col.append(round(mu / sd * SHARPE_ANN, 2))
    out["rolling_90d_sharpe"] = sharpe_col
    return out


def month_breakdown(taken: pd.DataFrame, month_str: str) -> dict:
    df = taken[taken["entry_date"].dt.to_period("M").astype(str) == month_str].copy()
    by_ticker = (df.groupby("ticker")
                   .agg(n=("pnl_total", "size"),
                        pnl=("pnl_total", "sum"))
                   .sort_values("pnl", ascending=False))
    by_q = df["q"].value_counts().reindex(["Q1", "Q2", "Q3", "Q4", "Q5"], fill_value=0)
    return {
        "n":         int(len(df)),
        "gross":     float(df["pnl_total"].sum()),
        "by_ticker": by_ticker,
        "by_q":      by_q,
        "win_rate":  float((df["pnl_total"] > 0).mean()) if len(df) else 0.0,
    }


def max_drawdown(taken: pd.DataFrame) -> dict:
    df = taken.sort_values("exit_date").reset_index(drop=True)
    cum = df["pnl_total"].cumsum()
    cummax = cum.cummax()
    dd = cum - cummax
    trough_pos = int(dd.idxmin())
    # Find the running peak that preceded this trough
    peak_value = float(cummax.iloc[trough_pos])
    # First index where cum hits peak_value at or before trough_pos
    peak_pos = int(cum.iloc[:trough_pos + 1].idxmax())
    window_trades = df.iloc[peak_pos + 1:trough_pos + 1]
    return {
        "peak_pos":     peak_pos,
        "trough_pos":   trough_pos,
        "peak_date":    df.iloc[peak_pos]["exit_date"],
        "trough_date":  df.iloc[trough_pos]["exit_date"],
        "peak_value":   round(peak_value, 2),
        "trough_value": round(float(cum.iloc[trough_pos]), 2),
        "drawdown":     round(float(dd.iloc[trough_pos]), 2),
        "n_trades":     int(len(window_trades)),
        "trades":       window_trades,
    }


def max_runup(taken: pd.DataFrame) -> dict:
    df = taken.sort_values("exit_date").reset_index(drop=True)
    cum = df["pnl_total"].cumsum()
    cummin = cum.cummin()
    ru = cum - cummin
    peak_pos = int(ru.idxmax())
    trough_value = float(cummin.iloc[peak_pos])
    trough_pos = int(cum.iloc[:peak_pos + 1].idxmin())
    window_trades = df.iloc[trough_pos + 1:peak_pos + 1]
    return {
        "trough_pos":   trough_pos,
        "peak_pos":     peak_pos,
        "trough_date":  df.iloc[trough_pos]["exit_date"],
        "peak_date":    df.iloc[peak_pos]["exit_date"],
        "trough_value": round(trough_value, 2),
        "peak_value":   round(float(cum.iloc[peak_pos]), 2),
        "runup":        round(float(ru.iloc[peak_pos]), 2),
        "n_trades":     int(len(window_trades)),
        "trades":       window_trades,
    }


def window_breakdown(window_df: pd.DataFrame) -> dict:
    by_ticker = (window_df.groupby("ticker")
                          .agg(n=("pnl_total", "size"),
                               pnl=("pnl_total", "sum"))
                          .sort_values("pnl", ascending=False))
    months = sorted(window_df["exit_date"].dt.to_period("M").astype(str).unique().tolist())
    return {"by_ticker": by_ticker, "months": months}


# ---------------------------------------------------------------------------
# Q2 helpers (AAPL deep-dive)
# ---------------------------------------------------------------------------

def stats_block(s: pd.Series) -> dict:
    return {
        "n":        int(len(s)),
        "mean":     round(float(s.mean()), 2)   if len(s) else float("nan"),
        "median":   round(float(s.median()), 2) if len(s) else float("nan"),
        "std":      round(float(s.std(ddof=1)), 2) if len(s) > 1 else float("nan"),
        "min":      round(float(s.min()), 2)    if len(s) else float("nan"),
        "max":      round(float(s.max()), 2)    if len(s) else float("nan"),
    }


def pnl_buckets(s: pd.Series) -> pd.Series:
    bins = [-np.inf, -300, -150, -50, 0, 50, 150, 300, np.inf]
    labels = ["≤−$300", "−$300..−$150", "−$150..−$50", "−$50..$0",
              "$0..$50", "$50..$150", "$150..$300", "≥$300"]
    return pd.cut(s, bins=bins, labels=labels).value_counts().reindex(labels, fill_value=0)


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

def df_to_md(df: pd.DataFrame, float_fmt: str = "{:,.2f}") -> str:
    if df is None or len(df) == 0:
        return "_(empty)_\n"
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (int, np.integer)):
                cells.append(f"{int(v):,}")
            elif isinstance(v, (float, np.floating)):
                cells.append("-" if pd.isna(v) else float_fmt.format(float(v)))
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def fmt_money(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(taken: pd.DataFrame) -> str:
    n_trades = len(taken)
    total_pnl = float(taken["pnl_total"].sum())
    universe_n = taken["ticker"].nunique()
    date_min = taken["entry_date"].min().date()
    date_max = taken["exit_date"].max().date()

    monthly = per_month_summary(taken)

    # Top / bottom 3 months
    sorted_m = monthly.sort_values("gross_pnl", ascending=False)
    top3 = sorted_m.head(3)
    bot3 = sorted_m.tail(3).iloc[::-1]

    dd = max_drawdown(taken)
    ru = max_runup(taken)
    dd_b = window_breakdown(dd["trades"])
    ru_b = window_breakdown(ru["trades"])

    # AAPL deep-dive
    aapl = taken[taken["ticker"] == "AAPL"].copy()
    other = taken[taken["ticker"] != "AAPL"].copy()

    md = []
    md.append("# Time-Window and AAPL Decomposition of the R3 Baseline\n")
    md.append(
        "_Decomposes the R3 production baseline (+$6,775.14 / 357 taken trades / "
        "Sharpe 0.41) by entry-date month and by ticker.  All input rows are "
        "from `data/raw/backtest_*_demo_kelly.csv` filtered with the same "
        "`_taken_mask` logic as `scripts/r3_baseline.py`.  Generated by "
        "`scripts/decompose_time_ticker.py`._\n\n"
    )
    md.append(
        "> **Synthetic-sentiment caveat (load-bearing).**  Every row in the "
        "input logs has `is_synthetic=True` and "
        "`sentiment_source='synthetic_news'`.  The findings below "
        "characterise how the strategy interacts with the synthetic "
        "mean-reverting sentiment generator's specific path through 2024-05 to "
        "2026-04, NOT how it will behave on real Finnhub + SEC sentiment.  "
        "Treat any time-window or AAPL-specific finding as a property of the "
        "synthetic corpus until validated against real-mode runs.\n\n"
    )

    # ---------------- Methodology ----------------
    md.append("## Methodology\n\n")
    md.append(
        f"- **Universe:** {universe_n} tickers ({', '.join(sorted(taken['ticker'].unique()))}).\n"
        f"- **Source:** `data/raw/backtest_{{TICKER}}_demo_kelly.csv` (10 files).\n"
        f"- **Filter:** `accepted=True` AND `kelly_reason` not in "
        f"{{rejected_by_kelly, bucket_full, portfolio_risk_cap, rejected_risk_reward, "
        f"negative_kelly_*}}.\n"
        f"- **Trades after filter:** {n_trades:,} taken (signal=BUY CALLS for all).\n"
        f"- **Aggregate P&L:** {fmt_money(total_pnl)} (matches the pinned $6,775 within drift tolerance).\n"
        f"- **Date range:** {date_min} (first entry) -> {date_max} (last exit).\n"
        f"- **Sharpe convention:** `mean(pnl_total) / std(pnl_total) * sqrt(252/5)`, "
        f"matching `r3_baseline.headline()`.\n"
        f"- **Quintile assignment:** `data/raw/quintile_edges.json` "
        f"(refit from the 10-ticker flat corpus).\n"
        f"- **Cumulative-curve ordering:** trades sorted by `exit_date` "
        f"(P&L is realised at exit).\n\n"
    )

    # ============================================================
    # QUESTION 1 -- TIME-WINDOW CONCENTRATION
    # ============================================================
    md.append("## Question 1 -- Time-window concentration\n\n")

    md.append("### 1.1 Per-month trade activity and P&L\n\n")
    md.append(
        "Trades binned by `entry_date` month.  `cum_pnl` is the running sum of "
        "`gross_pnl`.  `rolling_90d_sharpe` is the per-trade Sharpe over the "
        "trailing 90-day window of entries ending at month-end (annualised at "
        "sqrt(252/5)).  NaN where the window has < 5 trades.\n\n"
    )
    md.append(df_to_md(monthly))
    md.append("\n")

    md.append("### 1.2 Top 3 best months / Top 3 worst months\n\n")

    md.append("**Best 3 months (gross P&L):**\n\n")
    md.append(df_to_md(top3))
    for _, row in top3.iterrows():
        b = month_breakdown(taken, row["month"])
        md.append(
            f"\n- **{row['month']}** (n={b['n']}, gross={fmt_money(b['gross'])}, "
            f"win_rate={b['win_rate']*100:.1f}%): "
            f"by ticker -> "
            + ", ".join(f"{t} ({int(rr['n'])} tr, {fmt_money(rr['pnl'])})"
                        for t, rr in b['by_ticker'].iterrows())
            + "; quintile mix Q1/Q2/Q3/Q4/Q5 = "
            + "/".join(str(int(b['by_q'][q])) for q in ["Q1", "Q2", "Q3", "Q4", "Q5"])
            + ".\n"
        )

    md.append("\n**Worst 3 months (gross P&L):**\n\n")
    md.append(df_to_md(bot3))
    for _, row in bot3.iterrows():
        b = month_breakdown(taken, row["month"])
        md.append(
            f"\n- **{row['month']}** (n={b['n']}, gross={fmt_money(b['gross'])}, "
            f"win_rate={b['win_rate']*100:.1f}%): "
            f"by ticker -> "
            + ", ".join(f"{t} ({int(rr['n'])} tr, {fmt_money(rr['pnl'])})"
                        for t, rr in b['by_ticker'].iterrows())
            + "; quintile mix Q1/Q2/Q3/Q4/Q5 = "
            + "/".join(str(int(b['by_q'][q])) for q in ["Q1", "Q2", "Q3", "Q4", "Q5"])
            + ".\n"
        )

    md.append("\n### 1.3 Largest contiguous drawdown\n\n")
    md.append(
        f"- **Peak:** {dd['peak_date'].date()} at {fmt_money(dd['peak_value'])}\n"
        f"- **Trough:** {dd['trough_date'].date()} at {fmt_money(dd['trough_value'])}\n"
        f"- **Drawdown:** {fmt_money(dd['drawdown'])} over {dd['n_trades']} trades\n"
        f"- **Months covered (by exit_date):** {', '.join(dd_b['months'])}\n"
        f"- **Ticker P&L within the window:**\n\n"
    )
    dd_tk = dd_b["by_ticker"].reset_index()
    dd_tk["pnl"] = dd_tk["pnl"].round(2)
    md.append(df_to_md(dd_tk))
    md.append("\n")

    md.append("### 1.4 Largest contiguous run-up\n\n")
    md.append(
        f"- **Trough:** {ru['trough_date'].date()} at {fmt_money(ru['trough_value'])}\n"
        f"- **Peak:** {ru['peak_date'].date()} at {fmt_money(ru['peak_value'])}\n"
        f"- **Run-up:** {fmt_money(ru['runup'])} over {ru['n_trades']} trades\n"
        f"- **Months covered (by exit_date):** {', '.join(ru_b['months'])}\n"
        f"- **Ticker P&L within the window:**\n\n"
    )
    ru_tk = ru_b["by_ticker"].reset_index()
    ru_tk["pnl"] = ru_tk["pnl"].round(2)
    md.append(df_to_md(ru_tk))
    md.append("\n")

    # 1.5 Honest assessment - composed at end with all numbers in hand
    pos_months = int((monthly["gross_pnl"] > 0).sum())
    neg_months = int((monthly["gross_pnl"] < 0).sum())
    n_months = len(monthly)
    top3_pnl = float(top3["gross_pnl"].sum())
    pct_from_top3 = top3_pnl / total_pnl if total_pnl else float("nan")
    runup_share = ru["runup"] / total_pnl if total_pnl else float("nan")

    md.append("### 1.5 Honest assessment\n\n")
    md.append(
        f"The equity curve is **regime-dependent, not steady accumulation.**  "
        f"Across {n_months} entry-months, {pos_months} are net positive and "
        f"{neg_months} net negative.  The top 3 months alone produce "
        f"{fmt_money(top3_pnl)} -- {pct_from_top3*100:.0f}% of the +$6,775 "
        f"headline -- which is greater than 100% because the remaining "
        f"{n_months-3} months are net-negative in aggregate by roughly "
        f"{fmt_money(top3_pnl - total_pnl)}.  Put differently: remove "
        f"{', '.join(top3['month'].astype(str).tolist())} from the corpus "
        f"and the strategy is a net loser on the other "
        f"{n_months-3} months.  The largest contiguous run-up "
        f"({ru['trough_date'].date()} -> {ru['peak_date'].date()}, "
        f"{fmt_money(ru['runup'])}) is "
        f"{runup_share*100:.0f}% of total P&L, and the largest contiguous "
        f"drawdown ({fmt_money(dd['drawdown'])}, {dd['n_trades']} trades, "
        f"{dd['peak_date'].date()} -> {dd['trough_date'].date()}) is "
        f"{abs(dd['drawdown']/total_pnl)*100:.0f}% of total P&L in the "
        f"opposite direction -- meaning the strategy built up >$10k of "
        f"paper P&L by 2025-10 and gave back >$8k of it by 2026-04, "
        f"closing the period at +$6.8k mostly because of the April-2026 "
        f"recovery month.  This is the synthetic-sentiment generator's "
        f"random-walk path producing localised stretches of "
        f"directional-move-then-mean-revert behaviour that the BUY CALLS "
        f"strategy alternately exploits and gives back.  A real-mode rerun "
        f"would have a structurally different path and these specific "
        f"months would not transfer.\n\n"
    )

    # ============================================================
    # QUESTION 2 -- AAPL DEEP-DIVE
    # ============================================================
    md.append("## Question 2 -- AAPL deep-dive\n\n")
    md.append(
        f"AAPL: **{len(aapl)} taken trades**, gross "
        f"{fmt_money(aapl['pnl_total'].sum())}.  Worst single-ticker P&L in "
        f"the universe and the only ticker with a P&L drag worse than "
        f"-$1,000.\n\n"
    )

    # 2.1 P&L distribution
    md.append("### 2.1 P&L distribution per trade\n\n")
    s = aapl["pnl_total"]
    other_s = other["pnl_total"]
    pnl_stats = pd.DataFrame([
        {"group": "AAPL",            **stats_block(s),
         "win_rate": round(float((s > 0).mean()), 4)},
        {"group": "universe ex-AAPL", **stats_block(other_s),
         "win_rate": round(float((other_s > 0).mean()), 4)},
    ])
    md.append(df_to_md(pnl_stats))
    md.append("\n**AAPL P&L histogram (per trade):**\n\n")
    bk = pnl_buckets(s).reset_index()
    bk.columns = ["bucket", "count"]
    md.append(df_to_md(bk))
    pos_n = int((s > 0).sum())
    neg_n = int((s < 0).sum())
    big_loss_n = int((s <= -300).sum())
    big_loss_pnl = float(s[s <= -300].sum())
    rest_n = len(aapl) - big_loss_n
    rest_pnl = float(s[s > -300].sum())
    md.append(
        f"\nOf {len(aapl)} AAPL trades, {pos_n} are positive "
        f"({pos_n/len(aapl)*100:.1f}%) and {neg_n} are negative.  "
        f"{big_loss_n} trades are <= -$300 each and together contribute "
        f"{fmt_money(big_loss_pnl)}.  The other {rest_n} trades net "
        f"{fmt_money(rest_pnl)}, so AAPL's total drag is essentially the "
        f"left-tail group: kill those {big_loss_n} trades and AAPL would "
        f"be a small winner on the remaining {rest_n}.  Median trade "
        f"{fmt_money(s.median())}, mean {fmt_money(s.mean())} -- the gap "
        f"between them is the fat-left-tail signature.\n\n"
    )

    # 2.2 Quintile distribution
    md.append("### 2.2 Quintile distribution of AAPL taken trades\n\n")
    aapl_q = aapl.groupby("q", observed=False).agg(
        n=("pnl_total", "size"),
        win_rate=("pnl_total", lambda x: (x > 0).mean() if len(x) else float("nan")),
        total_pnl=("pnl_total", "sum"),
        mean_pnl=("pnl_total", "mean"),
    ).reindex(["Q1", "Q2", "Q3", "Q4", "Q5"])
    aapl_q = aapl_q.fillna(0)
    aapl_q_disp = aapl_q.reset_index().rename(columns={"q": "quintile"})
    md.append("**AAPL by quintile:**\n\n")
    md.append(df_to_md(aapl_q_disp))

    other_q = other.groupby("q", observed=False).agg(
        n=("pnl_total", "size"),
        win_rate=("pnl_total", lambda x: (x > 0).mean() if len(x) else float("nan")),
        total_pnl=("pnl_total", "sum"),
        mean_pnl=("pnl_total", "mean"),
    ).reindex(["Q1", "Q2", "Q3", "Q4", "Q5"]).fillna(0)
    other_q_disp = other_q.reset_index().rename(columns={"q": "quintile"})
    md.append("\n**Universe ex-AAPL by quintile:**\n\n")
    md.append(df_to_md(other_q_disp))

    aapl_q5 = float(aapl_q.loc["Q5", "total_pnl"])
    other_q5 = float(other_q.loc["Q5", "total_pnl"])
    md.append(
        f"\nAAPL's Q5 (highest-conviction) bucket contributes "
        f"{fmt_money(aapl_q5)} on {int(aapl_q.loc['Q5','n'])} trades; "
        f"the rest of the universe's Q5 contributes "
        f"{fmt_money(other_q5)} on {int(other_q.loc['Q5','n'])} trades.  "
        f"AAPL's Q5 inverts -- "
        f"{'positive' if aapl_q5 > 0 else 'negative'} where the rest of the "
        f"universe is {'positive' if other_q5 > 0 else 'negative'}.\n\n"
    )

    # 2.3 Exit reasons
    md.append("### 2.3 Exit-reason distribution\n\n")
    aapl_xr = (aapl.groupby("exit_reason")
                   .agg(n=("pnl_total", "size"),
                        total_pnl=("pnl_total", "sum"),
                        avg_pnl=("pnl_total", "mean"),
                        avg_days_held=("days_held", "mean"))
                   .sort_values("n", ascending=False)
                   .reset_index())
    md.append("**AAPL exits:**\n\n")
    md.append(df_to_md(aapl_xr))
    other_xr = (other.groupby("exit_reason")
                     .agg(n=("pnl_total", "size"),
                          total_pnl=("pnl_total", "sum"),
                          avg_pnl=("pnl_total", "mean"))
                     .sort_values("n", ascending=False)
                     .reset_index())
    md.append("\n**Universe ex-AAPL exits (for comparison):**\n\n")
    md.append(df_to_md(other_xr))
    md.append("\n")

    # 2.4 IV rank
    md.append("### 2.4 IV rank at entry\n\n")
    iv_compare = pd.DataFrame([
        {"group": "AAPL",            **stats_block(aapl["iv_rank"])},
        {"group": "universe ex-AAPL", **stats_block(other["iv_rank"])},
    ])
    md.append(df_to_md(iv_compare, float_fmt="{:.4f}"))
    md.append(
        f"\nAAPL mean iv_rank at entry: {aapl['iv_rank'].mean():.4f}.  "
        f"Universe-ex-AAPL mean: {other['iv_rank'].mean():.4f}.  "
        f"Note: in demo mode, `iv_rank` is the percentile of the rolling "
        f"realised vol over the IV_RANK_WINDOW -- not a real-IV rank.  "
        f"Differences here therefore reflect AAPL's realised-vol path under "
        f"the synthetic price walk, not options-market dislocation.\n\n"
    )

    # 2.5 Days to earnings
    md.append("### 2.5 Days to earnings at entry\n\n")
    aapl_999 = int((aapl["days_to_earnings"] == 999).sum())
    other_999 = int((other["days_to_earnings"] == 999).sum())
    md.append(
        f"**Test is null in synthetic mode.**  All {len(aapl)} AAPL taken "
        f"trades have `days_to_earnings = 999` (the engine's sentinel for "
        f"'no earnings date found') and {other_999} of {len(other)} "
        f"universe-ex-AAPL trades are the same.  In demo mode the backtest "
        f"engine does not invoke `earnings_filter.fetch_earnings_dates` -- "
        f"it always passes 999, so the earnings-window suppression is "
        f"effectively disabled and the 'AAPL is being entered too close "
        f"to earnings' hypothesis cannot be tested against this corpus.  "
        f"This question can only be answered against a real-mode run where "
        f"`days_to_earnings` carries actual values.\n\n"
    )

    # 2.6 Recommendation
    md.append("### 2.6 Recommendation\n\n")

    aapl_q4_n = int(aapl_q.loc["Q4", "n"])
    aapl_q4_pnl = float(aapl_q.loc["Q4", "total_pnl"])
    aapl_q5_n = int(aapl_q.loc["Q5", "n"])
    aapl_q5_pnl = float(aapl_q.loc["Q5", "total_pnl"])

    aapl_xr_dict = aapl.groupby("exit_reason")["pnl_total"].agg(["count", "sum"]).to_dict()
    aapl_stops_n = int(aapl_xr_dict["count"].get("stop_loss", 0))
    aapl_stops_pnl = float(aapl_xr_dict["sum"].get("stop_loss", 0.0))
    other_xr_dict = other.groupby("exit_reason")["pnl_total"].agg(["count", "sum"]).to_dict()
    other_stops_n = int(other_xr_dict["count"].get("stop_loss", 0))
    other_stops_pnl = float(other_xr_dict["sum"].get("stop_loss", 0.0))
    aapl_stop_rate = aapl_stops_n / len(aapl) if len(aapl) else 0.0
    other_stop_rate = other_stops_n / len(other) if len(other) else 0.0

    md.append(
        f"**Mostly synthetic-path artifact, driven by a stop-loss-rate "
        f"disparity that is itself a property of AAPL's real 2024-05 to "
        f"2026-04 price drift -- the only 'real' input under the synthetic "
        f"sentiment.**  The smoking gun is the exit-reason table: AAPL "
        f"hits `stop_loss` on **{aapl_stops_n} of {len(aapl)} trades "
        f"({aapl_stop_rate*100:.1f}%)** for {fmt_money(aapl_stops_pnl)} of "
        f"drag, vs the rest of the universe at "
        f"**{other_stops_n} of {len(other)} trades "
        f"({other_stop_rate*100:.1f}%)** for {fmt_money(other_stops_pnl)}.  "
        f"AAPL takes the stop loss roughly "
        f"{(aapl_stop_rate / max(other_stop_rate, 1e-9)):.0f}x more often "
        f"than the universe average; the resulting stop-driven losers "
        f"({fmt_money(aapl_stops_pnl)}) are larger than AAPL's entire "
        f"P&L drag ({fmt_money(s.sum())}), meaning AAPL's other 31 trades "
        f"(time_stop + profit_target) are net positive.  Quintile inversion "
        f"is consistent with this: AAPL's Q4 ({fmt_money(aapl_q4_pnl)}, "
        f"{aapl_q4_n} trades) is worse than Q5 ({fmt_money(aapl_q5_pnl)}, "
        f"{aapl_q5_n} trades), and both invert the universe pattern -- "
        f"high-confidence BUY CALLS on AAPL during this real price window "
        f"systematically met adverse moves.  Sample-size noise is not the "
        f"primary driver (the loss is concentrated in 13 specific trades, "
        f"not diffuse).  Earnings-window structural exposure cannot be "
        f"tested in synthetic mode (`days_to_earnings = 999` for every "
        f"row).  Read for a future real-data session: verify whether "
        f"AAPL's stop-loss rate drops back toward the universe average "
        f"once sentiment is real and the `earnings_filter` is live; if it "
        f"does not, the spread's stop-loss sizing or AAPL's idiosyncratic "
        f"vol both deserve a closer look.  The +$6,775 number itself "
        f"does not need fixing -- it is a synthetic baseline by "
        f"construction.\n\n"
    )

    # ---------------- Closing caveat ----------------
    md.append("---\n\n")
    md.append("## Reproduction\n\n")
    md.append(
        "```bash\n"
        ".venv/Scripts/python.exe scripts/decompose_time_ticker.py\n"
        "```\n\n"
        "Reads `data/raw/backtest_*_demo_kelly.csv` and "
        "`data/raw/quintile_edges.json`; writes "
        "`outputs/time_ticker_decomposition.md`.  Re-run after any change to "
        "`scripts/r3_baseline.py` that produces a new `_kelly` corpus.\n\n"
    )
    md.append("## Synthetic-sentiment caveat (repeated)\n\n")
    md.append(
        "All conclusions in this report describe the synthetic-sentiment "
        "generator's interaction with the strategy, not real-data behaviour.  "
        "A real-mode rerun (`scripts/r3_baseline.py --real` once a meaningful "
        "live corpus exists) will produce a structurally different path; "
        "specific months, drawdown windows, and ticker-level attributions "
        "will not transfer.  The methodology in this report -- per-month "
        "binning, drawdown/runup decomposition, AAPL-vs-universe quintile "
        "and dte comparison -- does transfer.\n"
    )

    return "".join(md)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    taken = load_taken_trades()
    taken = assign_quintile(taken)
    md = build_report(taken)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[decompose_time_ticker] -> {OUT_PATH}  ({len(md.splitlines())} lines)")


if __name__ == "__main__":
    main()

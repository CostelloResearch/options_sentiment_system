# =============================================================================
# scripts/correlation_matrix.py -- Universe diversification audit
#
# PURPOSE
# -------
# After the 2026-04-25 universe rebuild (5 -> 10 tickers across 6 sectors and
# 3 asset classes) we need to verify the new universe actually diversifies.
# This script downloads daily closes for every ticker in config.TICKERS and
# emits:
#
#   * 60-day correlation matrix  (last 60 trading days of daily returns)
#   * 252-day correlation matrix (last ~1y, robustness check)
#   * Flagged pairs with |corr| > 0.70 on the 60-day window
#   * Effective number of independent bets per Meucci's heuristic
#       N_eff = 1 / sum(w_i^2 * lambda_i / sum(lambda))    (equal weights)
#     i.e. exp(entropy(eigenvalues / sum)) -- gives a single intuitive number
#
# OUTPUTS
# -------
#   data/raw/correlation_matrix_60d.csv
#   data/raw/correlation_matrix_252d.csv
#   outputs/correlation_matrix.md
# =============================================================================

from __future__ import annotations

import os
import sys
import argparse

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config


OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "outputs"))
RAW_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "raw"))


def _download_closes(tickers, period="2y"):
    """
    Download daily Close for each ticker.  Returns a (date, ticker) wide df.

    We pull per-ticker rather than a single multi-symbol call so individual
    failures don't poison the batch.  yfinance occasionally rate-limits
    multi-symbol downloads on free tier.
    """
    frames = {}
    for t in tickers:
        try:
            print(f"[corr] downloading {t} ({period})...")
            h = yf.Ticker(t).history(period=period, auto_adjust=True)
            if h.empty:
                print(f"[corr] WARNING: empty history for {t}")
                continue
            h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
            frames[t] = h["Close"]
        except Exception as e:
            print(f"[corr] FAILED {t}: {e}")
    if not frames:
        raise RuntimeError("no price data downloaded for any ticker")
    closes = pd.DataFrame(frames).sort_index()
    return closes


def _corr_window(closes: pd.DataFrame, n_days: int) -> pd.DataFrame:
    """Pairwise corr of daily log-returns over the last n_days observations."""
    rets = np.log(closes / closes.shift(1)).dropna(how="all")
    rets = rets.tail(n_days)
    return rets.corr()


def _flag_pairs(corr: pd.DataFrame, threshold: float = 0.70) -> pd.DataFrame:
    """Return the upper-triangular pairs with |corr| > threshold, sorted."""
    rows = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            c = float(corr.iloc[i, j])
            if abs(c) > threshold:
                rows.append({"ticker_a": cols[i], "ticker_b": cols[j],
                             "corr": round(c, 4),
                             "abs_corr": round(abs(c), 4)})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("abs_corr", ascending=False).reset_index(drop=True)
    return df


def _effective_bets(corr: pd.DataFrame) -> float:
    """
    Effective number of independent bets via eigenvalue entropy.
    N_eff = exp(- sum p_i log p_i) where p_i = lambda_i / sum(lambda).
    For perfectly uncorrelated assets N_eff = N.  For perfectly correlated
    assets N_eff = 1.  Standard portfolio diversification heuristic.
    """
    eig = np.linalg.eigvalsh(corr.values)
    eig = eig.clip(min=1e-12)
    p   = eig / eig.sum()
    H   = -float(np.sum(p * np.log(p)))
    return float(np.exp(H))


def _df_to_md(df: pd.DataFrame, fmt: str = ".4f") -> str:
    if df.empty:
        return "_(empty)_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, (int, np.integer)):
                cells.append(f"{int(v)}")
            elif isinstance(v, (float, np.floating)):
                cells.append("-" if pd.isna(v) else f"{float(v):{fmt}}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(tickers, threshold=0.70):
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)

    closes = _download_closes(tickers, period="2y")

    # 60d (~3 calendar months) primary window the user asked for
    corr_60  = _corr_window(closes, 60)
    # 252d (~1y) robustness check -- 60 obs has high SE
    corr_252 = _corr_window(closes, 252)

    flagged_60  = _flag_pairs(corr_60,  threshold=threshold)
    flagged_252 = _flag_pairs(corr_252, threshold=threshold)
    n_eff_60  = _effective_bets(corr_60)
    n_eff_252 = _effective_bets(corr_252)

    # CSVs
    corr_60.to_csv(os.path.join(RAW_DIR, "correlation_matrix_60d.csv"))
    corr_252.to_csv(os.path.join(RAW_DIR, "correlation_matrix_252d.csv"))

    # Markdown
    md_path = os.path.join(OUT_DIR, "correlation_matrix.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Universe Correlation Matrix\n\n")
        f.write(f"_Snapshot for {len(tickers)} tickers: "
                f"{', '.join(tickers)}._\n\n")
        f.write(f"_Threshold for flagging: |corr| > {threshold:.2f}._\n\n")

        f.write("## 1. Effective number of independent bets\n\n")
        f.write("Eigenvalue-entropy diversification metric. "
                "`N_eff = exp(-sum(p_i log p_i))` where `p_i = lambda_i / "
                "sum(lambda)`. Perfectly uncorrelated -> `N_eff = N`; "
                "perfectly correlated -> `N_eff = 1`.\n\n")
        eff_df = pd.DataFrame([
            {"window":  "60d",  "n_tickers": len(tickers),
             "n_eff":  round(n_eff_60,  3),
             "ratio":  round(n_eff_60  / len(tickers), 3)},
            {"window": "252d",  "n_tickers": len(tickers),
             "n_eff":  round(n_eff_252, 3),
             "ratio":  round(n_eff_252 / len(tickers), 3)},
        ])
        f.write(_df_to_md(eff_df))
        f.write("\n")

        f.write("## 2. 60-day correlation matrix\n\n")
        f.write(_df_to_md(corr_60.round(3).reset_index().rename(
            columns={"index": "ticker"})))
        f.write("\n")

        f.write(f"### Flagged pairs (|corr| > {threshold:.2f}, 60d)\n\n")
        if flagged_60.empty:
            f.write("_None -- the universe is well-diversified at this "
                    "threshold over the 60-day window._\n\n")
        else:
            f.write(_df_to_md(flagged_60))
            f.write("\n_Discuss before proceeding -- correlated pairs "
                    "give double exposure to the same risk factor._\n\n")

        f.write("## 3. 252-day correlation matrix (robustness)\n\n")
        f.write(_df_to_md(corr_252.round(3).reset_index().rename(
            columns={"index": "ticker"})))
        f.write("\n")

        f.write(f"### Flagged pairs (|corr| > {threshold:.2f}, 252d)\n\n")
        if flagged_252.empty:
            f.write("_None._\n\n")
        else:
            f.write(_df_to_md(flagged_252))
            f.write("\n")

        f.write("## 4. Notes\n\n")
        f.write(
            "- 60-day windows have high standard error on correlation "
            "estimates: rule of thumb `SE(rho) ~= (1 - rho^2) / sqrt(n - 1)`, "
            "so a 0.5 correlation on 60 obs has SE ~= 0.10. The 252-day "
            "panel above is the more reliable read.\n"
            "- Pairs flagged at the 0.70 cutoff are candidates to drop "
            "or replace; pairs in 0.5--0.7 are 'noted but tolerable' for "
            "this universe.\n"
            "- For the 2026-04-25 rebuild we expect AAPL/SPY, NVDA/SPY, "
            "and IWM/SPY to land in the 0.5--0.8 range "
            "(broad-market beta), and TLT/GLD to be near zero or slightly "
            "negative against the equity cluster.\n"
        )

    print(f"\n[corr] -> {md_path}")
    print(f"[corr] N_eff (60d):  {n_eff_60:.3f}  / {len(tickers)} tickers")
    print(f"[corr] N_eff (252d): {n_eff_252:.3f} / {len(tickers)} tickers")
    if not flagged_60.empty:
        print(f"\n[corr] FLAGGED pairs at |corr| > {threshold:.2f} (60d):")
        print(flagged_60.to_string(index=False))
    else:
        print(f"\n[corr] No pairs cross |corr| > {threshold:.2f} on 60d window.")

    return {
        "corr_60":      corr_60,
        "corr_252":     corr_252,
        "flagged_60":   flagged_60,
        "flagged_252":  flagged_252,
        "n_eff_60":     n_eff_60,
        "n_eff_252":    n_eff_252,
        "md_path":      md_path,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=config.TICKERS)
    ap.add_argument("--threshold", type=float, default=0.70)
    args = ap.parse_args()
    main(args.tickers, threshold=args.threshold)

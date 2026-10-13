# T1 (stage 3, read-only): compare scored SEC rows to raw file length for the
# 12 filings flagged in audit/02_data.md section 2.1, plus all 10-K/10-Q.
# No project imports, no network, no writes outside stdout.
import sys, os, glob
import pandas as pd

RAW = sys.argv[1]
FLAGGED = [
    ("AAPL", "10-Q_2020-07-31.txt"), ("AAPL", "10-Q_2021-01-28.txt"),
    ("AAPL", "10-Q_2021-04-29.txt"), ("AAPL", "10-Q_2021-07-28.txt"),
    ("JPM", "10-K_2026-02-13.txt"), ("WMT", "10-K_2023-03-17.txt"),
    ("WMT", "10-K_2024-03-15.txt"), ("WMT", "10-K_2025-03-14.txt"),
    ("WMT", "10-K_2026-03-13.txt"), ("XOM", "10-K_2020-02-26.txt"),
    ("XOM", "10-K_2021-02-24.txt"), ("XOM", "10-K_2022-02-23.txt"),
]
frames = []
for f in glob.glob(os.path.join(RAW, "sec_sentiment_*.csv")):
    if "pre-fix" in f:
        continue
    frames.append(pd.read_csv(f))
sec = pd.concat(frames, ignore_index=True)
sec["base"] = sec["source_path"].astype(str).str.replace("\\", "/", regex=False).str.split("/").str[-1]

def flen(t, b):
    p = os.path.join(RAW, "sec", t, b)
    return os.path.getsize(p) if os.path.exists(p) else None

print("ticker,file,raw_bytes,scored,chunk_count,total_tokens,bytes_per_token,sentiment_score,verdict")
for t, b in FLAGGED:
    n = flen(t, b)
    r = sec[(sec["ticker"] == t) & (sec["base"] == b)]
    if r.empty:
        print(f"{t},{b},{n},NO,,,,,not scored")
        continue
    r = r.iloc[0]
    bpt = round(n / r["total_tokens"], 2) if r["total_tokens"] else None
    if n < 1000:
        v = "stub scored (1 chunk of boilerplate)" if r["chunk_count"] <= 1 else "stub"
    else:
        v = "full-document fallback scored" if r["chunk_count"] > 100 else "partial"
    print(f"{t},{b},{n},YES,{r['chunk_count']},{r['total_tokens']},{bpt},{r['sentiment_score']},{v}")

# Population view: bytes per token for all 10-K / 10-Q rows (MD&A-only should be well under full doc size)
rows = []
for _, r in sec[sec["filing_type"].isin(["10-K", "10-Q"])].iterrows():
    n = flen(r["ticker"], r["base"])
    rows.append((r["ticker"], r["filing_type"], r["base"], n, r["chunk_count"], r["total_tokens"]))
d = pd.DataFrame(rows, columns=["ticker", "form", "file", "bytes", "chunks", "tokens"])
print("\n10-K/10-Q chunk_count by form:", d.groupby("form")["chunks"].describe().round(1).to_dict("index"))
print("10-K rows with chunks>100:", int(((d["form"] == "10-K") & (d["chunks"] > 100)).sum()), "of", int((d["form"] == "10-K").sum()))
print("10-Q rows with chunks<=1:", int(((d["form"] == "10-Q") & (d["chunks"] <= 1)).sum()), "of", int((d["form"] == "10-Q").sum()))
print("top 10-K by chunks:\n", d[d["form"] == "10-K"].sort_values("chunks", ascending=False).head(12).to_string(index=False))

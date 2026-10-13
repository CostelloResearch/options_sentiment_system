# Stage 4a: yfinance RECORD / REPLAY harness for running repo scripts inside an
# isolated copy (audit/artifacts/stage4/{head_src,wt_src}) without editing them.
#
# Usage:
#   python -I yf_record_replay.py --mode record|replay --copy <copy_dir> \
#          --snapshot <snap_dir> --script scripts/r3_baseline.py -- --real
#   python -I yf_record_replay.py --mode record --snapshot <snap_dir> \
#          --earnings AAPL NVDA JPM XOM UNH WMT
#
# Guards (all runtime monkeypatches; no source edits):
#   * yfinance.Ticker.history and yfinance.download are intercepted. RECORD:
#     call through (3 retries, 2/4/8 s backoff) on first sight of a call key,
#     save the DataFrame to <snap>/<hash>.pkl (pandas pickle; parquet engines
#     are not installed and installs are prohibited) and append a manifest row;
#     identical later calls in the same snapshot reuse the saved response.
#     REPLAY: load from the snapshot; raise SnapshotMiss if absent.
#   * finnhub.Client, requests.Session.request: blocked (raise). Every attempt
#     is counted and reported. In REPLAY the curl_cffi session used by yfinance
#     is also blocked.
#   * Import of transformers/torch raises (FinBERT must never load).
#   * builtins.open / io.open / os.makedirs / os.replace in write mode outside the
#     allowed roots (copy dir, snapshot dir, yf cache dir) raise.
import argparse, builtins, datetime, hashlib, io, json, os, runpy, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("--mode", choices=["record", "replay"], required=True)
ap.add_argument("--copy", default=None)
ap.add_argument("--snapshot", required=True)
ap.add_argument("--script", default=None)
ap.add_argument("--earnings", nargs="*", default=None)
ap.add_argument("rest", nargs=argparse.REMAINDER)
A = ap.parse_args()
script_args = A.rest[1:] if A.rest[:1] == ["--"] else A.rest

SNAP = os.path.abspath(A.snapshot)
ST4 = os.path.dirname(os.path.abspath(__file__))
YF_CACHE = os.path.join(ST4, "yf_cache")
COPY = os.path.abspath(A.copy) if A.copy else None
os.makedirs(SNAP, exist_ok=True)
os.makedirs(YF_CACHE, exist_ok=True)
MANIFEST = os.path.join(SNAP, "manifest.jsonl")
ALLOWED = [p for p in (COPY, SNAP, YF_CACHE) if p]
STATS = {"yf_calls": 0, "yf_network_fetches": 0, "yf_reused": 0,
         "blocked_finnhub": 0, "blocked_requests": 0, "blocked_curl": 0,
         "blocked_writes": [], "misses": []}

# ---------------- import guard: no FinBERT / torch ----------------
class _NoHeavy:
    def find_spec(self, name, path=None, target=None):
        root = name.split(".")[0]
        if root in ("transformers", "torch"):
            raise ImportError(f"[guard] import of {name} blocked (FinBERT must not load)")
        return None
sys.meta_path.insert(0, _NoHeavy())

# ---------------- write guard ----------------
_orig_open = builtins.open
def _inside(p):
    ap_ = os.path.abspath(p)
    return any(os.path.commonpath([ap_, r]) == r for r in ALLOWED)
def _guard_open(file, mode="r", *a, **k):
    if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in "wax+"):
        if not _inside(os.fsdecode(file)):
            STATS["blocked_writes"].append(os.fsdecode(file))
            raise PermissionError(f"[guard] write outside allowed roots: {file}")
    return _orig_open(file, mode, *a, **k)
builtins.open = _guard_open
io.open = _guard_open
_orig_makedirs, _orig_replace = os.makedirs, os.replace
def _guard_makedirs(name, *a, **k):
    if not _inside(os.fsdecode(name)):
        STATS["blocked_writes"].append(os.fsdecode(name))
        raise PermissionError(f"[guard] makedirs outside allowed roots: {name}")
    return _orig_makedirs(name, *a, **k)
def _guard_replace(src, dst, *a, **k):
    if not _inside(os.fsdecode(dst)):
        STATS["blocked_writes"].append(os.fsdecode(dst))
        raise PermissionError(f"[guard] replace outside allowed roots: {dst}")
    return _orig_replace(src, dst, *a, **k)
os.makedirs, os.replace = _guard_makedirs, _guard_replace

# ---------------- network guards ----------------
import requests
def _blocked_request(self, method, url, *a, **k):
    STATS["blocked_requests"] += 1
    raise requests.ConnectionError(f"[guard] requests to {url} blocked")
requests.Session.request = _blocked_request
try:
    import finnhub
    class _BlockedFinnhub:
        def __init__(self, *a, **k):
            pass
        def __getattr__(self, name):
            def _f(*a, **k):
                STATS["blocked_finnhub"] += 1
                raise RuntimeError(f"[guard] finnhub.{name} blocked (no network to finnhub.io)")
            return _f
    finnhub.Client = _BlockedFinnhub
except ImportError:
    pass

import pandas as pd
import yfinance as yf
yf.set_tz_cache_location(YF_CACHE)  # sets tz + cookie + ISIN cache dirs (cache.py:637-638)
if A.mode == "replay":
    try:
        import curl_cffi.requests as _cr
        def _blocked_curl(self, *a, **k):
            STATS["blocked_curl"] += 1
            raise RuntimeError("[guard] curl_cffi network blocked in REPLAY")
        _cr.Session.request = _blocked_curl
    except Exception:
        pass

class SnapshotMiss(RuntimeError):
    pass

def _key(fn, ident, args, kwargs):
    d = {"fn": fn, "id": ident, "args": [repr(a) for a in args],
         "kwargs": {k: repr(v) for k, v in sorted(kwargs.items())}}
    s = json.dumps(d, sort_keys=True)
    return s, hashlib.sha256(s.encode()).hexdigest()[:20]

def _intercept(fn_name, ident, call):
    def wrapper(args, kwargs):
        STATS["yf_calls"] += 1
        ks, h = _key(fn_name, ident, args, kwargs)
        path = os.path.join(SNAP, f"{h}.pkl")
        if os.path.exists(path):
            if A.mode == "record":
                STATS["yf_reused"] += 1
            return pd.read_pickle(path)
        if A.mode == "replay":
            STATS["misses"].append(ks)
            raise SnapshotMiss(f"[replay] snapshot miss: {ks}")
        last = None
        for attempt in range(3):
            try:
                df = call(*args, **kwargs)
                break
            except Exception as e:
                last = e
                time.sleep(2 ** (attempt + 1))
        else:
            with _orig_open(MANIFEST, "a", encoding="utf-8") as f:
                f.write(json.dumps({"key": ks, "hash": h, "error": repr(last),
                                    "fetched_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}) + "\n")
            raise last
        STATS["yf_network_fetches"] += 1
        df.to_pickle(path)
        idx = df.index
        with _orig_open(MANIFEST, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "key": json.loads(ks), "hash": h, "file": os.path.basename(path),
                "fetched_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "rows": int(len(df)), "columns": [str(c) for c in df.columns],
                "first_index": str(idx[0]) if len(idx) else None,
                "last_index": str(idx[-1]) if len(idx) else None,
                "kind": "price_history"}) + "\n")
        return df
    return wrapper

_orig_history = yf.Ticker.history
def _history(self, *args, **kwargs):
    return _intercept("Ticker.history", self.ticker, lambda *a, **k: _orig_history(self, *a, **k))(args, kwargs)
yf.Ticker.history = _history
_orig_download = yf.download
def _download(*args, **kwargs):
    tick = kwargs.get("tickers", args[0] if args else None)
    return _intercept("download", repr(tick), _orig_download)(args, kwargs)
yf.download = _download

def _report():
    print("\n[yf_record_replay] mode=%s stats=%s" % (A.mode, json.dumps(STATS)))
    if COPY:
        cfg = sys.modules.get("config")
        print("[yf_record_replay] config module file:", getattr(cfg, "__file__", None))

# ---------------- earnings snapshot ----------------
if A.earnings is not None:
    assert A.mode == "record", "earnings snapshot only in record mode"
    for t in A.earnings:
        path = os.path.join(SNAP, f"earnings_{t}.pkl")
        err = None
        method = "Ticker.get_earnings_dates(limit=25)"
        for attempt in range(3):
            try:
                df = yf.Ticker(t).get_earnings_dates(limit=25)
                break
            except ImportError as e:
                # yfinance hands the table to pandas.read_html, which needs lxml
                # (not installed; installs prohibited). Fallback: fetch the SAME
                # Yahoo URL through yfinance's own session and parse the table
                # with BeautifulSoup's built-in html.parser.
                err = e; df = None
                try:
                    from bs4 import BeautifulSoup
                    tk = yf.Ticker(t)
                    url = ("https://finance.yahoo.com/calendar/earnings?symbol={}"
                           "&offset=0&size=25").format(t)
                    resp = tk._data.cache_get(url)
                    table = BeautifulSoup(resp.text, "html.parser").find("table")
                    hdr = [th.get_text(strip=True) for th in table.find_all("th")]
                    rows = [[td.get_text(strip=True) for td in tr.find_all("td")]
                            for tr in table.find_all("tr")[1:]]
                    df = pd.DataFrame(rows, columns=hdr)
                    dcol = next(c for c in df.columns if "Date" in c)
                    df.index = pd.to_datetime(df[dcol].str.replace(r"(AM|PM)\s*\w+$", r"\1", regex=True),
                                              errors="coerce", format="mixed")
                    df.index.name = "Earnings Date"
                    method = "fallback: yfinance session cache_get + bs4 html.parser"
                    break
                except Exception as e2:
                    err = e2; df = None; time.sleep(2 ** (attempt + 1))
            except Exception as e:
                err = e; df = None; time.sleep(2 ** (attempt + 1))
        fetched = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if df is None or len(df) == 0:
            print(f"[earnings] {t}: FAILED {err!r}")
            with _orig_open(MANIFEST, "a", encoding="utf-8") as f:
                f.write(json.dumps({"kind": "earnings", "ticker": t, "error": repr(err),
                                    "fetched_utc": fetched}) + "\n")
            continue
        df = df.copy()
        rep_col = next((c for c in df.columns if "Reported" in str(c)), None)
        if rep_col is None:
            df["date_kind"] = "realized"
        else:
            rep = pd.to_numeric(df[rep_col], errors="coerce")
            df["date_kind"] = rep.notna().map({True: "realized (reported EPS present)",
                                               False: "scheduled/estimated as of fetch"})
        df.to_pickle(path)
        with _orig_open(MANIFEST, "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "earnings", "ticker": t, "file": os.path.basename(path),
                                "fetched_utc": fetched, "rows": int(len(df)), "method": method,
                                "first_index": str(df.index.min()), "last_index": str(df.index.max()),
                                "note": "realized historical dates as listed by Yahoo at fetch time; not point-in-time"}) + "\n")
        print(f"[earnings] {t}: {len(df)} rows {df.index.min()} -> {df.index.max()}")
    _report()
    sys.exit(0)

# ---------------- run target script ----------------
assert COPY and A.script, "--copy and --script required"
script = os.path.join(COPY, A.script)
os.chdir(COPY)
sys.path.insert(0, COPY)
sys.argv = [script] + script_args
print(f"[yf_record_replay] mode={A.mode} copy={COPY} script={A.script} args={script_args}")
print(f"[yf_record_replay] start_utc={datetime.datetime.now(datetime.timezone.utc).isoformat()}")
rc = 0
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as e:
    rc = e.code or 0
except Exception as e:
    import traceback; traceback.print_exc(); rc = 1
finally:
    print(f"[yf_record_replay] end_utc={datetime.datetime.now(datetime.timezone.utc).isoformat()} rc={rc}")
    _report()
sys.exit(rc)

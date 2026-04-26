# =============================================================================
# data/sec_fetcher.py -- Fetch SEC EDGAR filings (10-K, 10-Q, 8-K)
#
# WHAT THIS MODULE DOES
# ---------------------
# For each ticker in config.TICKERS, pulls the company's recent annual
# (10-K), quarterly (10-Q), and material-event (8-K) filings from SEC
# EDGAR, extracts the relevant text, and saves one .txt per filing to
# data/raw/sec/{ticker}/{filing_type}_{YYYY-MM-DD}.txt.
#
# EDGAR ACCESS RULES (non-negotiable)
# -----------------------------------
#   * No API key needed, BUT a descriptive User-Agent containing a real
#     contact email is required.  SEC enforces this and will block bad UAs.
#   * Global rate limit: 10 requests/second.  We throttle ourselves with a
#     single-process token bucket.  Exceeding the limit returns 403.
#   * Respectful use: we fetch only as much as we need; skip re-downloading
#     filings we already have on disk.
#
# WHAT WE EXTRACT PER FILING TYPE
# -------------------------------
#   10-K / 10-Q : Item 7 "Management's Discussion and Analysis of Financial
#                 Condition and Results of Operations" (MD&A).  This is the
#                 forward-looking narrative where management explains
#                 business conditions -- the richest signal for sentiment.
#                 We extract from "Item 7" up to the next "Item 7A"/"Item 8".
#   8-K         : Whole body.  8-Ks are short (material events) -- earnings
#                 announcements, acquisitions, executive changes, etc.  No
#                 section extraction needed.
#
# EXTRACTION APPROACH
# -------------------
# Filings are submitted as HTML (or legacy .txt).  We:
#   1. Fetch the primary document (HTML) for each filing
#   2. Strip HTML with BeautifulSoup -> plain text
#   3. Collapse whitespace (EDGAR HTML is full of artifacts)
#   4. For 10-K/Q: regex-extract Item 7 -> next Item
#   5. For 8-K: return cleaned body
#
# This is best-effort.  Some filings use unusual formatting and the regex
# may fall short; we save the full cleaned body as a fallback so the
# scorer always has *something* to work with.
# =============================================================================

import os
import re
import sys
import time
import json
import datetime
from typing import Optional

import requests
import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

RAW_SEC_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "data", "raw", "sec")
)

# SEC endpoints
_TICKERS_URL       = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL   = "https://data.sec.gov/submissions/CIK{cik10}.json"
_ARCHIVES_BASE     = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no_dash}"

# Exhibit detection.
#
# WHY FILENAME, NOT TYPE:
# EDGAR's per-filing `index.json` has a `type` field, but it's the UI
# icon name ("text.gif", "image2.gif", "compressed.gif") -- NOT the
# SEC form type.  Confirmed by inspecting Apple's 2026-01-29 8-K index:
# the EX-99.1 file (a8-kex991q1202612272025.htm) has type='text.gif',
# same as the primary 8-K (aapl-20260129.htm) and unrelated XBRL
# schemas.  The `type` field is useless for distinguishing exhibits.
#
# So we identify EX-99.x exhibits by FILENAME pattern.  Common conventions
# across filers (Apple uses very long filenames, others are short):
#   * Apple:    a8-kex991q1202612272025.htm  (contains "ex991" with date suffix)
#   * Apple:    a8-kex991q3.htm
#   * Generic:  exhibit991.htm, ex-99.1.htm, ex99_1.htm, ex991.htm
#   * Bare:     991.htm, 99-1.htm
# The pattern matches the substring "ex" + optional separator + "99"
# (with optional trailing digit) ANYWHERE in the filename, OR the bare
# "99" + separator + "1" form near the start.  We don't anchor to the
# extension because filers often append a date / quarter suffix between
# the "ex991" marker and the .htm extension.  Excludes XBRL schemas,
# R-files, FilingSummary etc. via the negative match below.
_EX99_FILENAME_RE = re.compile(
    r"ex[-_. ]*99[-_. ]*\d*",
    re.IGNORECASE,
)
# Non-exhibit names to explicitly exclude (defense in depth)
_EX99_EXCLUDE_RE = re.compile(
    r"^(filingsummary|metalinks|report\.css|show\.js|"
    r"r\d+\.htm|\d{10}-\d{2}-\d{6}|.*\.xsd|.*_(?:def|lab|pre|cal)\.xml|"
    r".*_htm\.xml)$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Rate limiting -- single-process token bucket
# ---------------------------------------------------------------------------
# 10 requests/second = 1 every 100ms.  We track the last request time and
# sleep the remainder before each new request.  Simple and sufficient for
# a single-threaded fetcher.

_LAST_REQUEST_TIME = [0.0]   # list so we can mutate from nested scope

def _throttle(rps: int = None) -> None:
    rps = rps or config.DATA_PARAMS.get("sec_rate_limit_rps", 10)
    min_interval = 1.0 / rps
    now = time.monotonic()
    elapsed = now - _LAST_REQUEST_TIME[0]
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    _LAST_REQUEST_TIME[0] = time.monotonic()


def _headers() -> dict:
    ua = config.SEC_USER_AGENT
    if "your.email@example.com" in ua or not ua:
        raise ValueError(
            "config.SEC_USER_AGENT is still the placeholder. "
            "SEC blocks requests without a real contact email -- edit "
            "config.py and replace the placeholder with your email."
        )
    return {
        "User-Agent":      ua,
        "Accept-Encoding": "gzip, deflate",
        "Host":            None,    # set per-request by requests lib
    }


def _http_get(url: str, *, is_json: bool = False) -> Optional[object]:
    """
    Rate-limited GET with SEC-compliant headers.  Returns parsed JSON or
    raw text; returns None on 404 so callers can skip missing filings.
    """
    _throttle()
    headers = {k: v for k, v in _headers().items() if v is not None}
    timeout = config.DATA_PARAMS.get("sec_request_timeout", 30)
    resp = requests.get(url, headers=headers, timeout=timeout)

    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json() if is_json else resp.text


# ---------------------------------------------------------------------------
# Step 1 -- Ticker -> CIK resolution
# ---------------------------------------------------------------------------
# company_tickers.json maps every SEC registrant to a 10-digit CIK.  We cache
# the lookup on first call and reuse it for every ticker in the run.

_TICKER_MAP_CACHE: Optional[dict] = None

def _load_ticker_map() -> dict:
    global _TICKER_MAP_CACHE
    if _TICKER_MAP_CACHE is not None:
        return _TICKER_MAP_CACHE

    print("[sec_fetcher] Loading ticker -> CIK map from SEC...")
    data = _http_get(_TICKERS_URL, is_json=True) or {}
    # Shape is {index: {cik_str, ticker, title}}
    # Flip to {TICKER: cik_int}
    mp = {row["ticker"].upper(): int(row["cik_str"])
          for row in data.values()}
    _TICKER_MAP_CACHE = mp
    print(f"[sec_fetcher] Loaded {len(mp)} ticker/CIK pairs.")
    return mp


def get_cik(ticker: str) -> Optional[int]:
    """Return the 10-digit CIK for `ticker`, or None if not found."""
    mp = _load_ticker_map()
    return mp.get(ticker.upper())


def _cik10(cik: int) -> str:
    """Zero-pad CIK to 10 digits as EDGAR URLs require."""
    return str(cik).zfill(10)


# ---------------------------------------------------------------------------
# Step 2 -- List filings for a company
# ---------------------------------------------------------------------------

def _filings_index(cik: int) -> pd.DataFrame:
    """
    Fetch the recent-filings index for a CIK.  Returns a DataFrame with
    one row per filing and columns: form, filing_date, accession_no,
    primary_doc.  Only pulls the 'recent' block (roughly the last 1000
    filings -- plenty for 3 years of a single company).
    """
    url = _SUBMISSIONS_URL.format(cik10=_cik10(cik))
    data = _http_get(url, is_json=True) or {}
    recent = data.get("filings", {}).get("recent", {})

    if not recent:
        return pd.DataFrame()

    df = pd.DataFrame({
        "form":            recent.get("form", []),
        "filing_date":     recent.get("filingDate", []),
        "accession_no":    recent.get("accessionNumber", []),
        "primary_doc":     recent.get("primaryDocument", []),
    })
    df["filing_date"] = pd.to_datetime(df["filing_date"]).dt.date
    return df


def list_filings(
    ticker: str,
    years_back: int = None,
    forms: list = None,
) -> pd.DataFrame:
    """
    Return filings for `ticker` filtered to the last `years_back` years and
    the given form types.  Columns match _filings_index plus `ticker` and
    `cik`.
    """
    years_back = years_back if years_back is not None else \
                 config.DATA_PARAMS.get("sec_lookback_years", 3)
    forms = forms or config.DATA_PARAMS.get("sec_filing_types",
                                            ["10-K", "10-Q", "8-K"])

    cik = get_cik(ticker)
    if cik is None:
        print(f"[sec_fetcher] No CIK found for {ticker}.")
        return pd.DataFrame()

    idx = _filings_index(cik)
    if idx.empty:
        return idx

    cutoff = datetime.date.today() - datetime.timedelta(days=365 * years_back)
    idx = idx[(idx["filing_date"] >= cutoff) & (idx["form"].isin(forms))]
    idx = idx.sort_values("filing_date", ascending=False).reset_index(drop=True)
    idx["ticker"] = ticker.upper()
    idx["cik"]    = cik
    return idx


# ---------------------------------------------------------------------------
# Step 3 -- Download + extract a single filing
# ---------------------------------------------------------------------------

def _doc_url(cik: int, accession_no: str, primary_doc: str) -> str:
    """Build the URL to the primary document (HTML) for a filing."""
    acc_no_dash = accession_no.replace("-", "")
    base = _ARCHIVES_BASE.format(cik=cik, acc_no_dash=acc_no_dash)
    return f"{base}/{primary_doc}"


# Section markers.
#
# 10-K MD&A is Item 7 (ends at Item 7A "Quantitative and Qualitative
# Disclosures About Market Risk" or Item 8 "Financial Statements").
#
# 10-Q MD&A is Item 2 of Part I (ends at Item 3 "Quantitative and
# Qualitative Disclosures About Market Risk" or Item 4 "Controls and
# Procedures") -- this is a DIFFERENT item number from 10-K because the
# 10-Q form structure is unrelated to 10-K's.  The previous version of
# this module incorrectly applied the 10-K Item 7 regex to 10-Qs, which
# matched stray "Item 7 of Form 10-K" cross-references in the doc body
# and produced 500-byte stub extractions for AAPL 2020-2021 10-Qs.
#
# We require the section header to be FOLLOWED by "Management's
# Discussion" within ~80 chars so we don't false-match on cross-
# references like "as required by Item 7 of Form 10-K".  This is what
# the actual section heading looks like in every filer we've seen.
# 10-K Item 7 header.  We do NOT need a special "exclude Item 7A" guard
# because "Item 7A" is followed by "Quantitative and Qualitative
# Disclosures About Market Risk", not "Management's Discussion" -- so
# requiring "Management.s Discussion" right after the item number
# naturally excludes the 7A header.
#
# Apostrophe handling: BeautifulSoup decoding can corrupt the curly quote
# (U+2019) in older Apple filings into the Unicode replacement character
# U+FFFD, depending on the source HTML's declared encoding.  We use `.?`
# to accept ANY single character in the apostrophe position (or none) --
# straight ', curly ', U+FFFD, or absent.  This is more robust than
# enumerating specific apostrophe variants.
_MDNA_10K_START_RE = re.compile(
    r"item\s*7\.?\s+management.?s\s+discussion",
    re.IGNORECASE,
)
# End markers match the actual section heading text, not just the item
# number, so we don't false-match on "see Item 8" cross-references that
# appear inside the MD&A narrative itself.
#   10-K Item 7A : "Item 7A. Quantitative and Qualitative Disclosures..."
#   10-K Item 8  : "Item 8. Financial Statements and Supplementary Data"
#   10-Q Item 3  : "Item 3. Quantitative and Qualitative Disclosures..."
#   10-Q Item 4  : "Item 4. Controls and Procedures"
_MDNA_10K_END_RE = re.compile(
    r"item\s*(7\s*a\.?\s+quantitative|8\.?\s+financial)",
    re.IGNORECASE,
)
_MDNA_10Q_START_RE = re.compile(
    r"item\s*2\.?\s+management.?s\s+discussion",
    re.IGNORECASE,
)
_MDNA_10Q_END_RE = re.compile(
    r"item\s*(3\.?\s+quantitative|4\.?\s+controls)",
    re.IGNORECASE,
)


def _strip_html(html: str) -> str:
    """
    Remove tags + script/style + collapse whitespace.

    Two-pass strategy on `<table>` tags:
      1. Try a tables-removed extraction first.  Modern filings (Apple
         post-2022, most filers since the iXBRL-mandated formatting
         standardised) put MD&A inside `<div>` / `<p>` blocks and use
         `<table>` only for financial data, so dropping tables yields
         clean narrative text.
      2. If the tables-removed text is too short (< 5000 chars), older
         filings used `<table>` for DOCUMENT LAYOUT, including the MD&A
         narrative.  Apple's pre-2022 10-Qs are like this -- the entire
         body is a giant table.  Fall back to the keep-tables version
         so the narrative survives.  This costs us some financial-table
         numeric noise in old filings, but FinBERT's chunk-and-average
         scoring tolerates that fine; missing MD&A entirely is much
         worse than a few percent extra digits in the input.

    KNOWN LIMITATION: pre-2022 AAPL iXBRL primary docs (six 10-Q filings:
    2020-Q1/Q2/Q3, 2021-Q1/Q2/Q3) encode narrative content inside
    iXBRL `ix:nonNumeric` tags whose text doesn't surface through
    BeautifulSoup's `get_text()` -- the resulting plain text contains
    only XBRL tagged values + the boilerplate accounting-policies tail.
    For these specific six files the table-fallback ALSO yields no
    MD&A content because the narrative isn't in the primary doc HTML
    at all (it's distributed across the iXBRL R-files that the SEC
    viewer renders client-side).  Confirmed by direct grep of the
    raw 2.09 MB primary HTML: zero occurrences of "Management's
    Discussion".  iXBRL-aware extraction (parsing ix:nonNumeric / R*.htm
    / FilingSummary.xml) is deferred -- 6 historical quarters of one
    ticker isn't worth a parser.  Symptom: 500-byte stub files.  See
    PROJECT_STATE.md §10.2 known-limitations.  If this issue recurs
    in any other ticker's pre-2022 filings during real-data backfill,
    revisit the parser decision.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Always strip script/style -- never useful, sometimes huge.
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Pass 1: clone and strip tables
    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["table"]):
        tag.decompose()
    text_no_tables = re.sub(r"\s+", " ", clone.get_text(separator=" ")).strip()

    if len(text_no_tables) >= 5000:
        return text_no_tables

    # Pass 2 (fallback): keep tables (old layout-table filings)
    text_with_tables = re.sub(r"\s+", " ", soup.get_text(separator=" ")).strip()
    return text_with_tables


def _extract_mdna(text: str, form: str = "10-K") -> str:
    """
    Best-effort slice of the MD&A section from a 10-K/10-Q plain-text body.
    Returns the longest valid slice spanning from the form's MD&A header
    to the next section marker.  If no match is found, returns the full
    text (so the scorer still runs on something).

    Strategy: rather than picking a particular start match a priori (the
    old "use last Item 7 to skip TOC" heuristic landed on tail
    cross-references in older filings), we enumerate ALL plausible MD&A
    starts -- using a strict regex that requires "Management's Discussion"
    near the item number -- and pick the candidate with the LONGEST slice
    to the next end marker.  The TOC entry typically has its end marker
    just a few hundred chars later (the next TOC line); the actual
    section yields a much longer body.

    Branches by form:
      * 10-K:  Item 7  -> {Item 7A | Item 8}
      * 10-Q:  Item 2  -> {Item 3  | Item 4}
    """
    if form.startswith("10-Q"):
        start_re, end_re = _MDNA_10Q_START_RE, _MDNA_10Q_END_RE
    else:
        # Default to 10-K markers; harmless for 10-K/A and similar variants.
        start_re, end_re = _MDNA_10K_START_RE, _MDNA_10K_END_RE

    starts = list(start_re.finditer(text))
    if not starts:
        return text

    best_slice = ""
    for sm in starts:
        ends = [m for m in end_re.finditer(text) if m.start() > sm.end()]
        end_pos = ends[0].start() if ends else len(text)
        candidate = text[sm.end():end_pos].strip()
        if len(candidate) > len(best_slice):
            best_slice = candidate

    if len(best_slice) < 500:
        return text
    return best_slice


def _filing_index(cik: int, accession_no: str) -> Optional[dict]:
    """
    Fetch the per-filing `index.json` -- the directory listing of every
    document in the filing (primary doc + every exhibit).  Returns the
    parsed JSON dict, or None on 404 / parse error.
    """
    acc_no_dash = accession_no.replace("-", "")
    url = f"{_ARCHIVES_BASE.format(cik=cik, acc_no_dash=acc_no_dash)}/index.json"
    try:
        return _http_get(url, is_json=True)
    except Exception as e:
        print(f"[sec_fetcher] index.json fetch failed for {accession_no}: {e}")
        return None


def _submission_documents(cik: int, accession_no: str) -> list:
    """
    Parse the SEC submission `.txt` file's SGML headers to get an
    authoritative (TYPE, FILENAME) list for every document in the filing.

    Why this and not index.json: EDGAR's index.json `type` field is the
    UI icon name ("text.gif"), not the SEC form type.  And filename-based
    detection is filer-specific (Apple uses "a8-kex991*.htm", NVIDIA uses
    "q2fy26pr.htm", etc.) -- there's no universal regex.  The submission
    `.txt` is the only authoritative source: it's the SGML envelope that
    contains all sub-documents, each tagged with `<TYPE>` and `<FILENAME>`.

    Returns a list of dicts: [{"type": "EX-99.1", "filename": "...", ...}].

    To minimise bandwidth (full submissions can be 10s of MB), we use an
    HTTP Range header to fetch only the first 200 KB.  Document headers
    are at the top and rarely exceed ~50 KB total.
    """
    acc_no_dash = accession_no.replace("-", "")
    url = f"{_ARCHIVES_BASE.format(cik=cik, acc_no_dash=acc_no_dash)}/{accession_no}.txt"
    _throttle()
    headers = {k: v for k, v in _headers().items() if v is not None}
    headers["Range"] = "bytes=0-204800"   # first 200 KB
    timeout = config.DATA_PARAMS.get("sec_request_timeout", 30)
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code in (404,):
            return []
        # 200 (no range) or 206 (range honoured) both fine
        text = resp.text
    except Exception as e:
        print(f"[sec_fetcher] submission .txt fetch failed for {accession_no}: {e}")
        return []

    # SGML headers look like:
    #   <DOCUMENT>
    #   <TYPE>EX-99.1
    #   <SEQUENCE>2
    #   <FILENAME>a8-kex991q1...htm
    #   <DESCRIPTION>EXHIBIT 99.1
    #   <TEXT>
    #     ... content ...
    #   </TEXT>
    #   </DOCUMENT>
    # We use a non-greedy regex to capture each <DOCUMENT> block's headers
    # without pulling the body content.
    docs = []
    for m in re.finditer(
        r"<DOCUMENT>(.*?)<TEXT>",
        text, flags=re.IGNORECASE | re.DOTALL,
    ):
        block = m.group(1)
        t  = re.search(r"<TYPE>([^\s<]+)",     block, re.IGNORECASE)
        fn = re.search(r"<FILENAME>([^\s<]+)", block, re.IGNORECASE)
        sq = re.search(r"<SEQUENCE>(\d+)",     block, re.IGNORECASE)
        if t and fn:
            docs.append({
                "type":     t.group(1).strip().upper(),
                "filename": fn.group(1).strip(),
                "sequence": int(sq.group(1)) if sq else 0,
            })
    return docs


def _find_exhibit_99(submission_docs: list) -> Optional[str]:
    """
    Scan the parsed submission documents for an EX-99.x attachment and
    return its filename (relative to the filing directory).  Returns None
    if no 99.x exhibit exists.

    When multiple 99.x exhibits exist (rare: 99.1 + 99.2 on a single
    earnings 8-K), we prefer the lowest number -- 99.1 is the press
    release / prepared remarks, 99.2+ are appendices / supplements.
    """
    candidates = []
    for d in submission_docs or []:
        t = d.get("type", "")
        fn = d.get("filename", "")
        if not t or not fn:
            continue
        # Match EX-99, EX-99.1, EX-99.01, EX-99.2, etc.
        if not re.match(r"^EX-99(\.\d+)?$", t, re.IGNORECASE):
            continue
        # Only HTML / text exhibits are scoreable
        ext = os.path.splitext(fn)[1].lower()
        if ext not in (".htm", ".html", ".txt"):
            continue
        # Sort by the .N suffix; bare "EX-99" -> 0, "EX-99.1" -> 1
        m = re.search(r"\.(\d+)$", t)
        order = int(m.group(1)) if m else 0
        candidates.append((order, fn))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def fetch_filing(
    ticker: str,
    form: str,
    filing_date,
    accession_no: str,
    primary_doc: str,
    cik: int,
    overwrite: bool = False,
    fetch_exhibit: bool = True,
) -> Optional[str]:
    """
    Download one filing, extract the relevant text, and save to:
        data/raw/sec/{TICKER}/{FORM}_{YYYY-MM-DD}.txt

    For 8-K filings, ALSO attempt to fetch Exhibit 99.1 (the press release;
    on earnings-results 8-Ks this is the prepared-remarks document we
    actually want for sentiment).  Saved alongside as:
        data/raw/sec/{TICKER}/{FORM}_{YYYY-MM-DD}_exhibit99.txt
    Set `fetch_exhibit=False` to skip the exhibit pass (used for non-8-K
    forms or for the smoke test).

    Returns the path of the cover-page file on success, None if skipped
    or failed.  Existing files are skipped unless overwrite=True.
    """
    ticker = ticker.upper()
    out_dir = os.path.join(RAW_SEC_DIR, ticker)
    os.makedirs(out_dir, exist_ok=True)

    form_safe = form.replace("/", "_")
    filename  = f"{form_safe}_{filing_date}.txt"
    path      = os.path.join(out_dir, filename)
    ex_path   = os.path.join(out_dir, f"{form_safe}_{filing_date}_exhibit99.txt")

    have_cover   = os.path.exists(path)
    have_exhibit = os.path.exists(ex_path)
    is_8k        = form.startswith("8-K")

    # Skip cover-page fetch only when nothing needs to change
    skip_cover = have_cover and not overwrite

    # --- Cover-page fetch ---
    if not skip_cover:
        url  = _doc_url(cik, accession_no, primary_doc)
        try:
            html = _http_get(url, is_json=False)
        except requests.HTTPError as e:
            print(f"[sec_fetcher] HTTP {e.response.status_code} on {url} -- skip")
            return None
        if not html:
            return None

        text = _strip_html(html)
        # MD&A slicing branches by form type.  10-K MD&A is Item 7;
        # 10-Q MD&A is Item 2 of Part I -- different sections, different
        # surrounding markers.  See _extract_mdna.
        if form.startswith("10-"):
            body = _extract_mdna(text, form=form)
        else:
            body = text

        if len(body) < 500:
            # Too short to score -- usually means extraction missed.
            # Don't write the file, but still attempt the exhibit pass for 8-Ks.
            if not is_8k:
                return None
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)

    # --- Exhibit 99.x fetch (8-K only) ---
    # We do this for every 8-K (not just earnings-flagged ones), because
    # exhibit detection at this layer is structural -- the scorer
    # downstream decides whether to up-weight earnings-flagged exhibits.
    # Skip if we already have the exhibit and aren't overwriting.
    if is_8k and fetch_exhibit and (overwrite or not have_exhibit):
        docs = _submission_documents(cik, accession_no)
        ex_name = _find_exhibit_99(docs)
        if ex_name is None:
            # Log only for Item 2.02 8-Ks (where we expect a press release).
            # For non-earnings 8-Ks (M&A, exec changes, etc.) the absence
            # of 99.x is normal and unworthy of noise.
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    cover = f.read(2000)
                if re.search(r"item\s*2\.02|results of operations",
                             cover, re.IGNORECASE):
                    print(f"[sec_fetcher] {ticker} {filing_date}: Item 2.02 "
                          f"8-K with no Exhibit 99.x found -- manual review.")
        else:
            ex_url = f"{_ARCHIVES_BASE.format(cik=cik, acc_no_dash=accession_no.replace('-', ''))}/{ex_name}"
            try:
                ex_html = _http_get(ex_url, is_json=False)
            except requests.HTTPError as e:
                print(f"[sec_fetcher] HTTP {e.response.status_code} fetching "
                      f"exhibit {ex_name} for {ticker} {filing_date} -- skip")
                ex_html = None
            if ex_html:
                ex_text = _strip_html(ex_html)
                if len(ex_text) >= 500:
                    with open(ex_path, "w", encoding="utf-8") as f:
                        f.write(ex_text)

    return path if os.path.exists(path) else None


# ---------------------------------------------------------------------------
# Step 4 -- Batch runner
# ---------------------------------------------------------------------------

def fetch_all_filings(
    ticker: str,
    years_back: int = None,
    forms: list = None,
    overwrite: bool = False,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Download every filing for `ticker` within the lookback window.

    Returns a DataFrame with one row per filing that was successfully saved
    (columns: ticker, form, filing_date, accession_no, path).

    ETFs and other non-issuer tickers (config.ETF_TICKERS) short-circuit:
    they don't file 10-K/10-Q/8-K, so we log it once and return empty
    rather than wasting an EDGAR roundtrip and printing the misleading
    "no filings in lookback window" message.
    """
    if ticker.upper() in getattr(config, "ETF_TICKERS", set()):
        if verbose:
            print(f"[sec_fetcher] {ticker}: ETF / non-issuer -- "
                  f"no SEC data, news-only sentiment.")
        return pd.DataFrame()

    idx = list_filings(ticker, years_back=years_back, forms=forms)
    if idx.empty:
        if verbose:
            print(f"[sec_fetcher] {ticker}: no filings in lookback window.")
        return pd.DataFrame()

    if verbose:
        print(f"[sec_fetcher] {ticker}: {len(idx)} filings to process "
              f"(10-K={int((idx['form']=='10-K').sum())}, "
              f"10-Q={int((idx['form']=='10-Q').sum())}, "
              f"8-K={int((idx['form']=='8-K').sum())})")

    saved_rows = []
    for _, row in idx.iterrows():
        path = fetch_filing(
            ticker       = row["ticker"],
            form         = row["form"],
            filing_date  = row["filing_date"],
            accession_no = row["accession_no"],
            primary_doc  = row["primary_doc"],
            cik          = int(row["cik"]),
            overwrite    = overwrite,
        )
        if path:
            saved_rows.append({
                "ticker":       row["ticker"],
                "form":         row["form"],
                "filing_date":  row["filing_date"],
                "accession_no": row["accession_no"],
                "path":         path,
            })

    df = pd.DataFrame(saved_rows)
    if verbose:
        print(f"[sec_fetcher] {ticker}: saved {len(df)} filings to disk.")
    return df


def fetch_all_tickers(
    tickers: list = None,
    years_back: int = None,
    overwrite: bool = False,
) -> dict:
    """Convenience: run fetch_all_filings across a list of tickers."""
    tickers = tickers or config.TICKERS
    results = {}
    for t in tickers:
        try:
            results[t] = fetch_all_filings(t, years_back=years_back,
                                           overwrite=overwrite)
        except ValueError as e:
            # e.g. placeholder UA
            print(f"[sec_fetcher] ABORT: {e}")
            raise
        except Exception as e:
            print(f"[sec_fetcher] ERROR on {t}: {e}")
            results[t] = pd.DataFrame()
    return results


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", default="AAPL")
    p.add_argument("--years",  type=int, default=3)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    df = fetch_all_filings(args.ticker,
                           years_back=args.years,
                           overwrite=args.overwrite)
    if not df.empty:
        print(df.head(10).to_string(index=False))

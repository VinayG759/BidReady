"""Beyond GeM: latest tenders from other government e-procurement portals, read live by TinyFish Fetch.

Discovery only. CPPP-family portals (GePNIC) put tender documents behind a captcha, so eligibility is
checked on GeM bids; here we list what is open. TinyFish Fetch returns the portal home page as markdown,
and the "Latest Tenders" table is parsed by its header names, so a column reorder does not break it.
Each portal's result is cached for 6 hours in backend/corpus/portals/<key>.json.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import sources

CACHE_DIR = Path(__file__).resolve().parent / "corpus" / "portals"
TTL_SECONDS = 6 * 3600

# Only portals where TinyFish Fetch has returned tender rows. CANDIDATES are tried by hand before promotion.
PORTALS = [
    {"key": "cppp", "name": "CPPP", "full_name": "Central Public Procurement Portal",
     "url": "https://eprocure.gov.in/eprocure/app"},
    {"key": "etenders", "name": "Central eTenders", "full_name": "Government eTenders (NIC GePNIC)",
     "url": "https://etenders.gov.in/eprocure/app"},
    {"key": "maha", "name": "Maharashtra", "full_name": "Maharashtra e-Tenders", "url": "https://mahatenders.gov.in/nicgep/app"},
    {"key": "tn", "name": "Tamil Nadu", "full_name": "Tamil Nadu e-Tenders", "url": "https://tntenders.gov.in/nicgep/app"},
]
CANDIDATES = [  # Fetch returned almost no content (324 chars), so not listed
    {"key": "kppp", "name": "Karnataka", "full_name": "Karnataka Public Procurement Portal", "url": "https://kppp.karnataka.gov.in/"},
]
_BY_KEY = {p["key"]: p for p in PORTALS}

IT_KEYWORDS = ["laptop", "desktop", "computer", "printer", "switch", "network", "cctv", "ups", "server",
               "it hardware", "notebook", "scanner", "router", "firewall", "workstation", "projector"]

_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ---------------------------------------------------------------- parsing

def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_separator(cells):
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c)


def _tables(text):
    """Markdown tables in text -> [(header cells, [row cells])]."""
    out, block = [], []
    for line in (text or "").splitlines() + [""]:
        if line.strip().startswith("|"):
            block.append(_cells(line))
            continue
        if len(block) >= 2:
            if _is_separator(block[1]):
                out.append((block[0], [r for r in block[2:] if not _is_separator(r)]))
            else:
                out.append((block[0], block[1:]))
        block = []
    return out


def _plain(cell):
    """Cell text without markdown links, emphasis or a leading row number like '1.'."""
    t = _LINK_RE.sub(lambda m: m.group(1), cell or "")
    t = re.sub(r"[*_`]+", "", t)
    t = re.sub(r"<br\s*/?>", " ", t, flags=re.I)
    t = re.sub(r"^\s*\d+\s*[.)]\s+", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _link(cell, base):
    m = _LINK_RE.search(cell or "")
    if not m:
        return None
    href = m.group(2)
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        root = re.match(r"https?://[^/]+", base)
        return (root.group(0) if root else "") + href
    return base.rstrip("/") + "/" + href


def parse_date(s):
    """'05-Nov-2026 03:00 PM', '05-11-2026', '2026-11-05' -> '2026-11-05'; None if unparseable."""
    s = (s or "").strip()
    m = re.search(r"(\d{1,2})[-/ ]([A-Za-z]{3})[A-Za-z]*[-/ ,]+(\d{4})", s)
    if m and m.group(2).lower() in _MONTHS:
        d, mo, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
    else:
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
            if not m:
                return None
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d).date().isoformat()
    except ValueError:
        return None


_COLUMNS = {  # field -> header words, first match wins
    "title": ["tender title", "title", "work description", "description", "name of work"],
    "reference": ["reference", "ref no", "ref.", "tender id", "tender no"],
    "organisation": ["organisation", "organization", "department", "org", "buyer"],
    "closing": ["closing", "bid submission end", "last date", "due date"],
    "published": ["published", "e-published", "publish"],
}


def _column_map(header):
    h = [_plain(c).lower() for c in header]
    used, cols = set(), {}
    for field, words in _COLUMNS.items():
        for i, name in enumerate(h):
            if i not in used and any(w in name for w in words):
                cols[field] = i
                used.add(i)
                break
    return cols


_GEP_DATE = re.compile(r"\d{1,2}-[A-Za-z]{3}-\d{4}(?:\s+\d{1,2}:\d{2}\s*[AP]M)?$")


def parse_gepnic(text):
    """GePNIC home page (CPPP, eTenders, state NIC portals). TinyFish flattens its nested HTML tables into one
    line of cells, and drops the title for most rows (only some keep a numbered title such as '1. EOI for ...').
    So rows are found by their two dates: the cells before 'closing, opening' are [title,] reference."""
    start = re.search(r"Tender Title\s*\|\s*Reference No\s*\|\s*Closing Date\s*\|\s*Bid Opening Date", text or "")
    if not start:
        return None
    end = re.search(r"Latest Tenders updates|Corrigendum Title", text[start.end():])
    seg = text[start.end(): start.end() + end.start()] if end else text[start.end():]
    toks = [t.strip().replace("\\_", "_") for t in seg.split("|")]
    toks = [t for t in toks if t and not re.fullmatch(r":?-{3,}:?", t)]
    rows, buf, i = [], [], 0
    while i < len(toks):
        t = toks[i]
        if _GEP_DATE.match(t) and i + 1 < len(toks) and _GEP_DATE.match(toks[i + 1]):
            if buf:
                ref = buf[-1]
                title = re.sub(r"^\d+\s*[.)]\s*", "", buf[-2]).strip() if len(buf) >= 2 else None
                if title == ref:  # some rows repeat the reference where the title should be
                    title = None
                rows.append({"title": title or None, "reference": ref, "organisation": None,
                             "closing": parse_date(t), "closing_text": t,
                             "opening": parse_date(toks[i + 1]), "published": None, "link": None})
            buf, i = [], i + 2
            continue
        buf.append(t)
        i += 1
    return rows


def parse_tenders(text, base_url=""):
    """Tender rows from a portal page as TinyFish Fetch returns it: the GePNIC 'Latest Tenders' block when
    present, else any markdown table with a title column."""
    gep = parse_gepnic(text)
    if gep is not None:
        return gep
    rows = []
    for header, body in _tables(text):
        cols = _column_map(header)
        if "title" not in cols:
            continue
        for cells in body:
            get = lambda f: cells[cols[f]] if f in cols and cols[f] < len(cells) else ""
            title = _plain(get("title"))
            if not title or title.lower() in ("tender title", "title"):
                continue
            closing_raw = _plain(get("closing"))
            rows.append({
                "title": title,
                "reference": _plain(get("reference")) or None,
                "organisation": _plain(get("organisation")) or None,
                "closing": parse_date(closing_raw),
                "closing_text": closing_raw or None,
                "published": parse_date(_plain(get("published"))),
                "link": _link(get("title"), base_url) or _link(get("reference"), base_url),
            })
    return rows


def is_it(tender):
    hay = " ".join(str(tender.get(k) or "") for k in ("title", "reference", "organisation")).lower()
    return any(re.search(rf"(?<![a-z]){re.escape(k)}s?(?![a-z])", hay) for k in IT_KEYWORDS)


# ---------------------------------------------------------------- fetch + cache

def _cache_path(key):
    return CACHE_DIR / f"{key}.json"


def _read_cache(key):
    try:
        return json.loads(_cache_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(key, data):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(key).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001 - read-only filesystem on serverless; the live result is still returned
        pass


def read_portal(key, use_cache=True, live=True, fetch=None):
    """-> {portal, url, ms, fetched_at, tenders, raw_chars, cached} or {error, portal, url}.
    use_cache: return a cached read younger than 6 h. live=False never calls TinyFish. fetch: injectable for tests."""
    p = _BY_KEY.get(key)
    if not p:
        return {"error": f"unknown portal '{key}'"}
    cached = _read_cache(key)
    if cached and (not live or (use_cache and time.time() - cached.get("_ts", 0) < TTL_SECONDS)):
        return {k: v for k, v in cached.items() if k != "_ts"} | {"cached": True}
    if not live:
        return {"error": "not read yet", "portal": p["name"], "url": p["url"]}
    try:
        res = (fetch or sources.tinyfish_fetch)(p["url"])
    except sources.SourceError as e:
        out = {"error": str(e), "portal": p["name"], "url": p["url"]}
        if cached:  # stale but real beats nothing; say how old it is
            out["stale"] = {k: v for k, v in cached.items() if k != "_ts"} | {"cached": True}
        return out
    text = res.get("text") or ""
    data = {
        "portal": p["name"], "key": key, "url": p["url"], "ms": res.get("ms", 0),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tenders": parse_tenders(text, p["url"]), "raw_chars": len(text), "title": res.get("title") or "",
    }
    _write_cache(key, data | {"_ts": time.time()})
    return data | {"cached": False}


# ---------------------------------------------------------------- API

router = APIRouter()


@router.get("/api/portals")
def list_portals():
    out = []
    for p in PORTALS:
        c = _read_cache(p["key"])
        last = None
        if c:
            last = {"fetched_at": c.get("fetched_at"), "ms": c.get("ms"), "raw_chars": c.get("raw_chars"),
                    "tenders": len(c.get("tenders") or []), "fresh": time.time() - c.get("_ts", 0) < TTL_SECONDS}
        out.append({"key": p["key"], "name": p["name"], "full_name": p["full_name"], "url": p["url"], "last": last})
    return out


@router.get("/api/portals/{key}")
def get_portal(key: str, it_only: int = 0, refresh: int = 0):
    if key not in _BY_KEY:
        raise HTTPException(404, f"unknown portal '{key}'")
    r = read_portal(key, use_cache=not refresh, live=True)
    body = r.get("stale") if r.get("error") and r.get("stale") else r
    if "tenders" in body:
        body = dict(body)
        body["total"] = len(body["tenders"])
        body["it_count"] = sum(1 for t in body["tenders"] if is_it(t))
        if it_only:
            body["tenders"] = [t for t in body["tenders"] if is_it(t)]
        body["it_only"] = bool(it_only)
    if r.get("error"):
        body = dict(body)
        body["error"] = r["error"]  # stale data, if any, comes with the error that prevented a fresh read
    return body

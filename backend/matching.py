"""Tenders for you: open GeM bids that match what a supplier sells.

The supplier's categories come from its past orders and OEM letters. Two sources find bids:
- GeM BidPlus search, with plain item keywords per category ("laptop", "desktop computer", ...);
- TinyFish Search, with web queries that make tender sites return pages naming GeM bid numbers. Each number found
  is looked up on GeM itself, and only bids GeM lists as ongoing are kept.
Matches are merged by GeM document id and scored on category fit, brand and days left. No eligibility is run here;
that stays a separate step. Results are cached per profile for 10 minutes (memory + corpus/matches/).
"""

import json
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import data, sources
from .signals import _BID_RE

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))
CACHE_DIR = Path(__file__).resolve().parent / "corpus" / "matches"
CACHE_SECONDS = 600
MAX_MATCHES = 60
MAX_WEB_QUERIES = 4          # TinyFish searches per profile
MAX_RESOLVE = 20             # bid numbers from the web looked up on GeM per profile
PAGE2_BELOW = 15             # fetch GeM page 2 when page 1 leaves fewer kept bids than this

# Plain item keywords GeM's full-text search answers well, per category.
GEM_QUERIES = {
    "Laptops": ["laptop"],
    "Desktops": ["desktop computer", "all in one pc"],
    "Printers": ["multifunction printer", "laser printer"],
    "Networking": ["network switch", "wifi access point"],
    "CCTV": ["cctv camera", "network video recorder"],
    "UPS": ["online ups"],
}
WEB_WORDS = {
    "Laptops": "laptop", "Desktops": "desktop computer", "Printers": "printer",
    "Networking": "network switch", "CCTV": "cctv camera", "UPS": "online ups",
}
# Same idea as tools/build_corpus.py: service, consumable and furniture items are not what a hardware seller sells.
SKIP_RE = re.compile(r"\b(?:amc|maintenance|repair(?:ing)?|cartridges?|toners?|hiring|manpower|buyback|rental|"
                     r"furniture|tables?|chairs?|trolley|cover|bags?)\b|service\s*-", re.I)

_cache = {}


# ---------------------------------------------------------------- what the supplier sells

def categories_in(text):
    """Every category whose keyword appears as a whole word ("pc" in "PCs" counts, "specification" does not)."""
    t = (text or "").lower()
    return [c for c in data.CATEGORY_ORDER
            if any(re.search(r"\b" + re.escape(k) + r"s?\b", t) for k in data.CATEGORY_KEYWORDS[c])]


def primary_category(text):
    cats = categories_in(text)
    return cats[0] if cats else None


def profile_terms(profile):
    """-> {categories, brands, gem_queries, web_queries, orders_by_category, letters_by_category}"""
    orders, letters = {}, {}
    for o in profile.get("orders", []):
        for c in categories_in(o.get("item")):
            orders[c] = orders.get(c, 0) + 1
    for l in profile.get("oem_letters", []):
        for c in categories_in(l.get("scope")):
            letters.setdefault(c, []).append(l["brand"])
    # strongest first: past orders count most, a letter breaks ties
    cats = sorted(set(orders) | set(letters), key=lambda c: (-orders.get(c, 0), -len(letters.get(c, [])),
                                                             data.CATEGORY_ORDER.index(c)))
    brands = sorted({l["brand"] for l in profile.get("oem_letters", [])})
    gem_queries = [q for c in cats for q in GEM_QUERIES.get(c, [])]
    year = datetime.now(IST).year
    web_queries = [f'"GEM/{year}/B" {WEB_WORDS[c]} tender' for c in cats if c in WEB_WORDS][:MAX_WEB_QUERIES]
    return {"categories": cats, "brands": brands, "gem_queries": gem_queries, "web_queries": web_queries,
            "orders_by_category": orders, "letters_by_category": letters}


# ---------------------------------------------------------------- dates

def close_time(end):
    """GeM writes IST wall-clock time with a 'Z' suffix ("2026-11-20T15:00:00Z" closes at 15:00 IST)."""
    if not end:
        return None
    raw = re.sub(r"Z$", "", str(end).strip())
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


# ---------------------------------------------------------------- sources

def bid_numbers(result):
    """GeM bid numbers named in a TinyFish result's title, snippet or URL, as 'GEM/2026/B/8096659'."""
    text = " ".join(urllib.parse.unquote(result.get(k) or "") for k in ("title", "snippet", "url"))
    return list(dict.fromkeys(f"GEM/{m.group(1)}/B/{int(m.group(2))}" for m in _BID_RE.finditer(text)))


def _site(r):
    name = (r.get("site_name") or "").strip()
    if name:
        return name
    host = urllib.parse.urlparse(r.get("url") or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _gem_query(q):
    """Page 1, and page 2 when page 1 leaves too few bids worth showing. -> (bids, results, ms, error)"""
    bids, results, ms = [], 0, 0
    try:
        for page in (1, 2):
            res = sources.search_gem_bids(q, page=page)
            ms += res["ms"]
            results += len(res["bids"])
            bids += res["bids"]
            kept = [b for b in bids if not SKIP_RE.search(b.get("items") or "")]
            if len(kept) >= PAGE2_BELOW or len(bids) >= (res.get("total") or 0):
                break
        return bids, results, ms, None
    except sources.SourceError as e:
        return bids, results, ms, str(e)


def _resolve(number):
    """The GeM listing of one bid number, or None when GeM does not list it as ongoing."""
    try:
        res = sources.search_gem_bids(number)
    except sources.SourceError:
        return None, 0
    for b in res["bids"]:
        if (b.get("bid") or "").upper() == number.upper():
            return b, res["ms"]
    return None, res["ms"]


def _web_query(q):
    try:
        return sources.tinyfish_search(q), None
    except sources.SourceError as e:
        return None, str(e)


# ---------------------------------------------------------------- scoring

def _score(bid, terms, now):
    items = bid.get("items") or ""
    cat = primary_category(items)
    closes = close_time(bid.get("end"))
    days = (closes.date() - now.date()).days if closes else None
    score, reasons = 0, []
    n_orders = terms["orders_by_category"].get(cat, 0)
    letters = terms["letters_by_category"].get(cat, [])
    if n_orders:
        score += min(n_orders, 3) * 15
        reasons.append(f"{cat}: matches {n_orders} past order{'s' if n_orders > 1 else ''}")
    if letters:
        score += 15
        reasons.append(f"{cat}: you hold {' and '.join(letters)} OEM letter{'s' if len(letters) > 1 else ''}")
    named = [b for b in terms["brands"] if re.search(r"\b" + re.escape(b) + r"\b", items, re.I)]
    if named:
        score += 15
        reasons += [f"{b} named, you hold a {b} letter" for b in named]
    if days is not None:
        if days >= 7:
            score += 20
            reasons.append(f"closes in {days} days")
        elif days >= 3:
            score += 5
            reasons.append(f"closes in {days} days, tight")
        else:
            reasons.append(f"closes in {days} day{'s' if days != 1 else ''}, very tight")
    if len(bid["sources"]) > 1:
        score += 5
        reasons.append("found on GeM and on the web")
    return cat, closes, days, score, reasons


def _named(v):
    """GeM writes 'NA' when a bid leaves the department blank."""
    return v if v and str(v).strip().upper() not in ("NA", "N/A", "-") else None


def _library_ids():
    try:
        from . import main
        return set(main.TENDERS)
    except Exception:
        return set()


def build_matches(profile, gem_bids, web_bids, terms, now=None):
    """Merge both sources' bids by doc id, drop skipped, closed and off-category items, score and sort."""
    now = now or datetime.now(IST)
    merged = {}
    for b, src, sites in [(b, "GeM", []) for b in gem_bids] + [(b, "TinyFish", s) for b, s in web_bids]:
        doc = str(b.get("doc_id") or "")
        if not doc:
            continue
        m = merged.setdefault(doc, dict(b, sources=[], tinyfish_sites=[]))
        if src not in m["sources"]:
            m["sources"].append(src)
        m["tinyfish_sites"] += [s for s in sites if s not in m["tinyfish_sites"]]
    lib = _library_ids()
    out = []
    for doc, b in merged.items():
        items = b.get("items") or ""
        if SKIP_RE.search(items):
            continue
        cat, closes, days, score, reasons = _score(b, terms, now)
        if cat not in terms["categories"] or not closes or closes <= now:
            continue
        b["sources"].sort(key=["GeM", "TinyFish"].index)
        out.append({
            "doc_id": doc, "tender_id": f"g-{doc}", "bid": b.get("bid"), "title": items,
            "buyer": _named(b.get("department")) or _named(b.get("ministry")) or "", "ministry": _named(b.get("ministry")),
            "quantity": b.get("quantity"),
            "closes": closes.date().isoformat(), "closes_at": closes.isoformat(timespec="minutes"),
            "days_left": days, "category": cat, "score": min(score, 100), "reasons": reasons,
            "sources": b["sources"], "tinyfish_sites": b["tinyfish_sites"],
            "in_library": f"g-{doc}" in lib, "url": b.get("url") or sources.gem_document_url(doc),
        })
    out.sort(key=lambda m: (-m["score"], m["closes_at"]))
    return out[:MAX_MATCHES]


# ---------------------------------------------------------------- the whole search

def _cache_path(pid):
    return CACHE_DIR / (re.sub(r"[^A-Za-z0-9_-]", "_", pid) + ".json")


def _read_cache(pid):
    hit = _cache.get(pid)
    if not hit:
        try:
            hit = json.loads(_cache_path(pid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    if time.time() - hit.get("_at", 0) > CACHE_SECONDS:
        return None
    _cache[pid] = hit
    return hit


def _write_cache(pid, result):
    _cache[pid] = result
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _cache_path(pid).with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=1), encoding="utf-8")
        tmp.replace(_cache_path(pid))
    except OSError:
        pass


def find_matches(profile, use_cache=True):
    pid = profile["id"]
    if use_cache:
        hit = _read_cache(pid)
        if hit:
            return {k: v for k, v in hit.items() if k != "_at"} | {"cached": True}
    terms = profile_terms(profile)

    # GeM queries and TinyFish searches run side by side; neither waits for the other to fail.
    with ThreadPoolExecutor(max_workers=6) as pool:
        gem_jobs = [pool.submit(_gem_query, q) for q in terms["gem_queries"]]
        web_jobs = [pool.submit(_web_query, q) for q in terms["web_queries"]]
        t0 = time.perf_counter()
        gem_out = [j.result() for j in gem_jobs]
        web_out = [j.result() for j in web_jobs]
        web_ms_total = int((time.perf_counter() - t0) * 1000)

        gem_bids = [b for bids, _, _, _ in gem_out for b in bids]
        gem_errors = [e for _, _, _, e in gem_out if e]
        web_errors = [e for _, e in web_out if e]
        results = [r for res, _ in web_out if res for r in res.get("results", [])]
        sites_by_number = {}
        for r in results:
            for n in bid_numbers(r):
                sites_by_number.setdefault(n, [])
                if _site(r) and _site(r) not in sites_by_number[n]:
                    sites_by_number[n].append(_site(r))
        # Every TinyFish bid number is confirmed on GeM; when GeM refused all queries those lookups can only fail too.
        numbers = [] if len(gem_errors) == len(gem_out) else list(sites_by_number)[:MAX_RESOLVE]
        resolved = list(pool.map(_resolve, numbers))
    web_bids = [(b, sites_by_number[n]) for n, (b, _) in zip(numbers, resolved) if b]

    gem = {"queries": terms["gem_queries"], "results": sum(r for _, r, _, _ in gem_out),
           "ms": sum(ms for _, _, ms, _ in gem_out)}
    if gem_errors:
        gem["error"] = gem_errors[0] if len(gem_errors) == len(gem_out) else f"{len(gem_errors)} of {len(gem_out)} queries failed: {gem_errors[0]}"
    tf = {"queries": terms["web_queries"], "results": len(results), "bid_numbers": len(sites_by_number),
          "bids_found": len(web_bids), "ms": sum((res or {}).get("ms", 0) for res, _ in web_out) or web_ms_total}
    if web_errors:
        tf["error"] = web_errors[0] if len(web_errors) == len(web_out) else f"{len(web_errors)} of {len(web_out)} searches failed: {web_errors[0]}"

    public_terms = {k: terms[k] for k in ("categories", "brands", "gem_queries", "web_queries")}
    result = {
        "profile": {"id": pid, "name": profile.get("name"), "role": profile.get("role")},
        "terms": public_terms, "sources": {"gem": gem, "tinyfish": tf},
        "matches": build_matches(profile, gem_bids, web_bids, terms),
        "fetched_at": datetime.now(IST).isoformat(timespec="seconds"),
    }
    if gem.get("error") and len(gem_errors) == len(gem_out):
        # GeM unreachable from this server (e.g. a cloud region GeM refuses): show the saved snapshot, clearly labelled.
        snap = _read_snapshot(pid)
        if snap:
            return snap | {"cached": True, "snapshot": {"fetched_at": snap.get("fetched_at"), "reason": gem["error"]},
                           "sources": snap.get("sources", {}) | {"gem": gem}}
        return result | {"cached": False}       # a fully failed run is not cached, so the next request tries again
    _write_cache(pid, result | {"_at": time.time()})
    return result | {"cached": False}


SNAPSHOT_DIR = Path(__file__).resolve().parent / "corpus" / "matches_snapshot"


def _read_snapshot(pid):
    """A committed copy of a supplier's matches (refresh with python -m backend.tools.snapshot_matches)."""
    try:
        snap = json.loads((SNAPSHOT_DIR / (re.sub(r"[^A-Za-z0-9_-]", "_", pid) + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    today = datetime.now(IST).date().isoformat()
    snap["matches"] = [m for m in snap.get("matches", []) if (m.get("closes") or "9999") >= today]   # never show closed bids
    return snap


def _profile_by_id(pid):
    try:
        from . import main
        p = main.PROFILES.get(pid)
    except Exception:
        p = None
    return p or next((p for p in data.PROFILES if p["id"] == pid), None)


@router.get("/api/matches")
def matches(profile_id: str = "p-northstar", refresh: int = 0):
    profile = _profile_by_id(profile_id)
    if not profile:
        raise HTTPException(404, f"unknown profile {profile_id}")
    return find_matches(profile, use_cache=not refresh)

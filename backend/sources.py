"""Where real tender documents come from.

- GeM BidPlus public search (the same endpoint the bidplus.gem.gov.in "All Bids" page calls) lists open bids.
- GeM bid documents are public PDFs at /showbidDocument/<id>; we download them directly.
- TinyFish Search discovers tenders across the wider web; TinyFish Fetch reads non-PDF tender pages.
Every call returns timings so the pipeline can show what really happened.
"""

import http.cookiejar
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

GEM = "https://bidplus.gem.gov.in"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BidReady/1.0 (+eligibility pre-screen)"
TINYFISH_SEARCH_URL = os.environ.get("TINYFISH_SEARCH_URL") or "https://api.search.tinyfish.ai/"
TINYFISH_FETCH_URL = os.environ.get("TINYFISH_FETCH_URL") or "https://api.fetch.tinyfish.ai"


class SourceError(Exception):
    pass


def gem_document_url(doc_id):
    return f"{GEM}/showbidDocument/{int(doc_id)}"


def gem_doc_id(url):
    m = re.search(r"showbidDocument/(\d+)", url or "")
    return m.group(1) if m else None


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def search_gem_bids(keyword, page=1, sort="Bid-End-Date-Latest", timeout=30):
    """Open (ongoing) GeM bids matching a keyword. -> {"total", "bids": [...], "ms"}"""
    t0 = time.perf_counter()
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA), ("X-Requested-With", "XMLHttpRequest"), ("Referer", GEM + "/all-bids")]
    try:
        html = opener.open(GEM + "/all-bids", timeout=timeout).read().decode("utf-8", "ignore")
        token = re.search(r"'csrf_bd_gem_nk':\s*'([0-9a-f]+)'", html)
        if not token:
            raise SourceError("GeM search page changed: no CSRF token found")
        payload = {"param": {"searchBid": keyword, "searchType": "fullText"},
                   "filter": {"bidStatusType": "ongoing_bids", "byType": "all", "highBidValue": "",
                              "byEndDate": {"from": "", "to": ""}, "sort": sort}}
        if page and page > 1:
            payload["page"] = page
        body = urllib.parse.urlencode({"payload": json.dumps(payload), "csrf_bd_gem_nk": token.group(1)}).encode()
        data = json.loads(opener.open(GEM + "/all-bids-data", data=body, timeout=timeout).read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise SourceError(f"GeM search failed: {e}") from e
    if data.get("code") != 200:
        raise SourceError(f"GeM search returned code {data.get('code')}")
    resp = data["response"]["response"]
    bids = []
    for d in resp.get("docs", []):
        doc_id = str(_first(d.get("b_id")) or d.get("id"))
        bids.append({
            "doc_id": doc_id,
            "bid": _first(d.get("b_bid_number")),
            "items": _first(d.get("b_category_name")) or "",
            "ministry": _first(d.get("ba_official_details_minName")),
            "department": _first(d.get("ba_official_details_deptName")),
            "quantity": _first(d.get("b_total_quantity")),
            "start": _first(d.get("final_start_date_sort")),
            "end": _first(d.get("final_end_date_sort")),
            "url": gem_document_url(doc_id),
        })
    return {"total": resp.get("numFound", 0), "bids": bids, "ms": int((time.perf_counter() - t0) * 1000)}


def download(url, timeout=40, max_bytes=15_000_000):
    """-> {"bytes", "content_type", "ms", "final_url"}; raises SourceError."""
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/pdf,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes + 1)
            ctype = r.headers.get("Content-Type", "")
            final = r.geturl()
    except urllib.error.HTTPError as e:
        raise SourceError(f"HTTP {e.code} from {urllib.parse.urlparse(url).netloc}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise SourceError(f"could not reach {urllib.parse.urlparse(url).netloc}: {e}") from e
    if len(data) > max_bytes:
        raise SourceError("document is larger than 15 MB")
    if not data:
        raise SourceError("the source returned an empty body")
    return {"bytes": data, "content_type": ctype, "ms": int((time.perf_counter() - t0) * 1000), "final_url": final}


def _tinyfish_key():
    key = os.environ.get("TINYFISH_API_KEY", "").strip()
    if not key:
        raise SourceError("TINYFISH_API_KEY is not set")
    return key


def tinyfish_search(query, timeout=25):
    t0 = time.perf_counter()
    req = urllib.request.Request(TINYFISH_SEARCH_URL + "?" + urllib.parse.urlencode({"query": query}),
                                 headers={"X-API-Key": _tinyfish_key(), "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SourceError(f"TinyFish Search HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise SourceError(f"TinyFish Search failed: {e}") from e
    return {"results": payload.get("results", []), "ms": int((time.perf_counter() - t0) * 1000)}


def tinyfish_fetch(url, timeout=40):
    """Clean text of a web page via TinyFish Fetch. -> {"text", "title", "ms"}; raises SourceError (e.g. bot_blocked)."""
    t0 = time.perf_counter()
    body = json.dumps({"urls": [url], "format": "markdown"}).encode()
    req = urllib.request.Request(TINYFISH_FETCH_URL.rstrip("/") + "/", data=body,
                                 headers={"X-API-Key": _tinyfish_key(), "Content-Type": "application/json",
                                          "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SourceError(f"TinyFish Fetch HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise SourceError(f"TinyFish Fetch failed: {e}") from e
    errs = payload.get("errors") or []
    res = payload.get("results") or []
    if not res:
        raise SourceError(f"TinyFish Fetch: {(errs[0] or {}).get('error', 'no content') if errs else 'no content'}")
    return {"text": res[0].get("text") or "", "title": res[0].get("title") or "", "ms": int((time.perf_counter() - t0) * 1000)}

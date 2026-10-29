"""BidReady API. Run from the repo root: python -m uvicorn backend.main:app --port 8000"""

from . import config  # noqa: F401  (loads .env first)

import copy
import importlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import ai, data, library, pipeline, rules, sources
from .extract import build_tender, public_tender

ROOT = config.ROOT
STORE = Path(__file__).resolve().parent / "store.json"
IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="BidReady API", version=rules.RULE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------------------------------------------------------------- state

TENDERS = library.load()                      # real GeM bids: stored library, plus anything ingested this run
PROFILES = {p["id"]: p for p in data.fresh_profiles()}
ASSESSMENTS = {}                              # id -> Assessment (with internal _gap fields)
_counter = {"assessment": 0}


def public(obj):
    """Drop internal keys (leading underscore) before returning JSON."""
    if isinstance(obj, dict):
        return {k: public(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [public(v) for v in obj]
    return obj


def tender_summary(t):
    return public({k: v for k, v in t.items() if k != "clauses"})


def _save():
    try:
        STORE.write_text(json.dumps({"profiles": PROFILES}, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001 - read-only filesystem on serverless; memory still holds the change
        pass


def _load():
    if STORE.exists():
        try:
            PROFILES.update(json.loads(STORE.read_text(encoding="utf-8")).get("profiles", {}))
        except Exception:  # noqa: BLE001 - a bad store file must not stop the app booting
            pass


# ---------------------------------------------------------------- engine

def _kb(n):
    return f"{n / 1024:,.0f} KB"


def stages_for(tender, validation_logs, bad, result, profile, eval_ms):
    """What actually happened for this tender, from the records made when it was searched, fetched and read."""
    src = tender.get("_source") or {}
    log = tender.get("_log") or {}
    s = []
    if src.get("search"):
        q = src["search"]
        found = (f"{q['total']:,} open bids · {q.get('ms', 0)} ms" if q.get("total")
                 else f"library snapshot of {((src.get('fetch') or {}).get('snapshot') or '')[:10] or 'a past search'}")
        s.append(pipeline.stage("search", "Search", "GeM BidPlus", "ok", q.get("ms") or 0,
                                [f"POST bidplus.gem.gov.in/all-bids-data q=\"{q.get('keyword')}\" status=ongoing · {found}",
                                 f"selected {tender['bid']} · closes {tender.get('closes')}"]))
    elif tender["id"].startswith("u-"):
        s.append(pipeline.stage("search", "Search", "Upload", "ok", 1, [f"document uploaded by the user ({src.get('filename', 'PDF')})"]))
    else:
        s.append(pipeline.stage("search", "Search", "GeM BidPlus", "ok", 0, [f"bid {tender['bid']} opened by its GeM document link"]))

    f = src.get("fetch") or {}
    img = (tender.get("docs") or [{}])[0].get("image_only_pages") or []
    flog = []
    if f.get("url"):
        flog.append(f"GET {f['url'].replace('https://', '')} 200 · {_kb(f.get('bytes', 0))} · {f.get('ms', 0)} ms")
    flog.append(f"{tender['pages']} pages · {sum(len(p) for p in tender.get('_pages', [])):,} characters of text")
    if img:
        flog.append(f"warn page(s) {', '.join(map(str, img))} image-only, no extractable text")
    if f.get("snapshot"):
        flog.append(f"stored snapshot from {f['snapshot'][:10]} (sha256 {f.get('sha256', '')[:12]}) · verdict is pinned to this text")
    s.append(pipeline.stage("fetch", "Fetch", "Our code", "warn" if img else "ok", f.get("ms", 0), flog))

    gem_fields = sum(1 for v in (tender.get("_gem") or {}).values() if v)
    a = log.get("ai") or {}
    elog = [f"GeM template parser · {gem_fields} labelled fields read with exact quotes" if tender.get("_is_gem")
            else "not a GeM template document · relying on AI extraction"]
    if a.get("error"):
        elog.append(f"warn Claude extraction unavailable: {a['error']}")
    else:
        elog.append(f"Claude {a.get('model')} read the full text · {a.get('returned', 0)} eligibility clauses · "
                    + (f"{a.get('ms', 0):,} ms (cached)" if a.get("cached") else f"{a.get('ms', 0):,} ms"))
        elog.append(f"{a.get('verified', 0)} quotes verified verbatim · {a.get('rejected', 0)} rejected")
    for key, name in pipeline.CRITERIA:
        c = (tender.get("clauses") or {}).get(key)
        elog.append(f"  {name}: " + (f"\"{c['heading']}\" · p. {c['page']} · {c.get('source')}" if c else "not in this bid"))
    s.append(pipeline.stage("extract", "Extract", "Parser + Claude", "warn" if a.get("error") else "ok",
                            (a.get("ms") or 0) if not a.get("cached") else 40, elog))

    s.append(pipeline.stage("validate", "Validate", "Our code", "warn" if bad else "ok", 12, validation_logs))
    ev = [f"rules engine {rules.RULE_VERSION} · deterministic · 4 criteria vs {profile['name']} ({profile['role'].replace('_', ' ')})"]
    ev += [f"  {c['name']:<18} -> {c['status'].upper()}" for c in result["criteria"]]
    ev.append(f"verdict {result['verdict']} · coverage {result['coverage']}/4")
    s.append(pipeline.stage("evaluate", "Evaluate", "Our code", "ok", eval_ms, ev))
    s.append(pipeline.stage("report", "Report", "UI", "ok", 60,
                            [f"report ready · {result['coverage']}/4 criteria evidence-checked · {len(result['missing_docs'])} documents to gather"]))
    return s


def _signals_module():
    try:
        return importlib.import_module("backend.signals")
    except ImportError:
        return None


def web_check(tender, live):
    """TinyFish Search: where else this bid is listed, and any corrigendum / extension / cancellation signals."""
    mod = _signals_module()
    if not mod:
        return None
    try:
        return mod.web_signals(tender, live=live)
    except Exception as e:  # noqa: BLE001 - a web check must never break an assessment
        return {"error": f"{type(e).__name__}: {e}"[:200]}


def web_stage(sig):
    if not sig:
        return None
    if sig.get("error"):
        return pipeline.stage("watch", "Web check", "TinyFish", "warn", sig.get("ms") or 0,
                              [f"warn TinyFish Search unavailable: {sig['error']}"])
    sites = [x.get("site") for x in sig.get("listed_on") or []]
    logs = [f"GET api.search.tinyfish.ai q={sig.get('query', '')} · {sig.get('ms', 0):,} ms" + (" (cached)" if sig.get("cached") else ""),
            f"listed on {len(sites)} other site(s)" + (f": {', '.join(sites[:6])}" if sites else "")]
    for s in (sig.get("signals") or [])[:4]:
        logs.append(f"warn {s.get('kind')} signal on {s.get('site')}: {s.get('detail') or ''}".strip())
    if not sig.get("signals"):
        logs.append("ok no corrigendum, extension or cancellation signal found")
    return pipeline.stage("watch", "Web check", "TinyFish", "warn" if sig.get("signals") else "ok",
                          0 if sig.get("cached") else (sig.get("ms") or 0), logs)


def assess(tender, profile, created_at=None, store=True, kind="check", live_web=True):
    t0 = time.perf_counter()
    validations, vlogs, bad = pipeline.run_validation(tender)
    result = rules.evaluate(tender, profile, validations)
    eval_ms = max(1, round((time.perf_counter() - t0) * 1000))
    stages = stages_for(tender, vlogs, bad, result, profile, eval_ms)
    sig = web_check(tender, live=live_web)
    ws = web_stage(sig)
    if ws:
        stages.insert(1, ws)  # Search -> Web check -> Fetch -> ...
    _counter["assessment"] += 1
    a = {
        "id": f"a-{_counter['assessment']:04d}",
        "created_at": (created_at or datetime.now(IST)).isoformat(timespec="seconds"),
        "rule_version": rules.RULE_VERSION,
        "kind": kind,
        "seconds": round(sum(st["ms"] for st in stages) / 1000, 1),
        "tender": public_tender(tender),
        "profile": {"id": profile["id"], "name": profile["name"], "role": profile["role"]},
        "verdict": result["verdict"], "coverage": result["coverage"],
        "stages": stages, "criteria": result["criteria"],
        "missing_docs": result["missing_docs"], "unresolved": result["unresolved"],
        "scope_notice": result["scope_notice"],
        "web": sig,
    }
    if store:
        ASSESSMENTS[a["id"]] = a
    return a


def _screen_library():
    """Real assessments, run at start-up: the default supplier against every open bid in the library."""
    now = datetime.now(IST)
    p = PROFILES["p-northstar"]
    for i, t in enumerate(sorted(TENDERS.values(), key=lambda t: t.get("closes") or "")):
        if t.get("status") == "open":
            assess(t, p, created_at=now - timedelta(seconds=len(TENDERS) - i), kind="screen", live_web=False)


_load()
_screen_library()

# ---------------------------------------------------------------- routes


@app.get("/api/health")
def health():
    return {"ok": True, "rule_version": rules.RULE_VERSION, "mode": config.MODE, "live_search": True,
            "ai_extraction": ai.available(), "ai_model": ai.model(), "tenders": len(TENDERS)}


@app.get("/api/stats")
def stats():
    items = list(ASSESSMENTS.values())
    v = Counter(a["verdict"] for a in items)
    today = datetime.now(IST).date()
    by_day = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        c = Counter(a["verdict"] for a in items if a["created_at"][:10] == d.isoformat())
        by_day.append({"day": d.isoformat(), "eligible": c["eligible"], "relaxed": c["eligible_relaxation"],
                       "review": c["manual_review"], "not_eligible": c["not_eligible"]})
    by_cat = {}
    for a in items:
        c = by_cat.setdefault(a["tender"]["category"], Counter())
        c[a["verdict"]] += 1
    gaps = Counter(cr["_gap"] for a in items for cr in a["criteria"] if cr.get("_gap"))
    open_t = [t for t in TENDERS.values() if t.get("status") == "open"]
    # Time a bid takes the first time it is read (download + parser + Claude); later checks reuse that reading.
    reads = [((t.get("_source") or {}).get("fetch", {}).get("ms") or 0) + (((t.get("_log") or {}).get("ai") or {}).get("ms") or 0)
             for t in TENDERS.values() if ((t.get("_log") or {}).get("ai") or {}).get("ms")]
    return {
        "assessments": len(items),
        "eligible": v["eligible"] + v["eligible_relaxation"],
        "eligible_relaxation": v["eligible_relaxation"],
        "manual_review": v["manual_review"],
        "not_eligible": v["not_eligible"],
        "avg_seconds": round(sum(a["seconds"] for a in items) / len(items), 1) if items else 0,
        "first_read_seconds": round(sum(reads) / len(reads) / 1000, 1) if reads else None,
        "tenders_tracked": len(TENDERS),
        "open_tenders": len(open_t),
        "verdicts_by_day": by_day,
        "verdicts_by_category": [{"category": k, "eligible": c["eligible"], "relaxed": c["eligible_relaxation"],
                                  "review": c["manual_review"], "not_eligible": c["not_eligible"]}
                                 for k, c in sorted(by_cat.items(), key=lambda x: -sum(x[1].values()))],
        "top_gaps": [{"gap": g, "count": n} for g, n in gaps.most_common(5)],
        "ai": {"available": ai.available(), "model": ai.model()},
    }


@app.get("/api/tenders")
def list_tenders(q: str = ""):
    words = q.lower().split()
    out = []
    for t in sorted(TENDERS.values(), key=lambda t: (t.get("status") != "open", t.get("closes") or "")):
        hay = " ".join(str(t.get(k) or "") for k in ("bid", "title", "buyer", "portal", "category", "snippet")).lower()
        if all(w in hay for w in words):
            out.append(tender_summary(t))
    return out


def _tender(tid):
    t = TENDERS.get(tid)
    if t:
        return t
    m = re.fullmatch(r"g-(\d+)", tid or "")
    if m:  # serverless: ingested on another instance; GeM document ids are stable, so read it again
        return _ingest_doc(m.group(1))
    raise HTTPException(404, f"tender {tid} not found")


def _profile(pid):
    p = PROFILES.get(pid)
    if not p:
        raise HTTPException(404, f"profile {pid} not found")
    return p


@app.get("/api/tenders/{tid}")
def get_tender(tid: str):
    return public_tender(_tender(tid))


# ---------------------------------------------------------------- live GeM + ingest

@app.get("/api/gem-search")
def gem_search(q: str = "laptop", page: int = 1):
    """Open bids on GeM right now (GeM BidPlus public search)."""
    q = q.strip() or "laptop"
    try:
        res = sources.search_gem_bids(q, page=page)
    except sources.SourceError as e:
        return {"ok": False, "error": str(e)}
    for b in res["bids"]:
        b["in_library"] = f"g-{b['doc_id']}" in TENDERS
        b["category"] = data.category_of(b["items"])
    return {"ok": True, "source": "gem-bidplus", "query": q, "total": res["total"], "ms": res["ms"], "bids": res["bids"]}


def _ingest_doc(doc_id, search=None):
    tid = f"g-{doc_id}"
    if tid in TENDERS:
        return TENDERS[tid]
    url = sources.gem_document_url(doc_id)
    try:
        doc = sources.download(url)
    except sources.SourceError as e:
        raise HTTPException(502, f"Could not fetch the bid document: {e}") from e
    if doc["bytes"][:5] != b"%PDF-":
        raise HTTPException(422, "GeM did not return a PDF for this bid (it may have been withdrawn).")
    t, _ = build_tender(doc["bytes"], url, meta=search or {}, tid=tid)
    t["_source"] = {"search": search.get("_search") if search else None,
                    "fetch": {"url": url, "bytes": len(doc["bytes"]), "ms": doc["ms"]}}
    TENDERS[tid] = t
    return t


@app.post("/api/tenders/ingest")
def ingest(body: dict):
    """Fetch and read a real GeM bid: {doc_id} or {url: ".../showbidDocument/<id>"}."""
    doc_id = str(body.get("doc_id") or sources.gem_doc_id(body.get("url")) or "")
    if not doc_id.isdigit():
        raise HTTPException(422, "Give a GeM bid document id or a bidplus.gem.gov.in/showbidDocument/<id> link.")
    meta = {k: body.get(k) for k in ("bid", "items", "ministry", "end") if body.get(k)}
    if body.get("keyword"):
        meta["_search"] = {"keyword": body["keyword"], "total": body.get("total"), "ms": body.get("search_ms", 0)}
    t = _ingest_doc(doc_id, meta)
    return public_tender(t)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    raw = await file.read()
    if raw[:5] != b"%PDF-":
        raise HTTPException(422, "Please upload a PDF tender document.")
    if len(raw) > 15_000_000:
        raise HTTPException(413, "PDF is larger than 15 MB.")
    t0 = time.perf_counter()
    t, _ = build_tender(raw, f"uploaded:{file.filename}", meta={})
    t["_source"] = {"filename": file.filename,
                    "fetch": {"bytes": len(raw), "ms": int((time.perf_counter() - t0) * 1000)}}
    TENDERS[t["id"]] = t
    return public_tender(t)


@app.get("/api/live-search")
def live_search(q: str = ""):
    """Web discovery through TinyFish Search: metadata only, never eligibility evidence."""
    if not q.strip():
        return {"ok": False, "error": "empty query"}
    try:
        res = sources.tinyfish_search(q)
    except sources.SourceError as e:
        return {"ok": False, "error": str(e)}
    fields = ("position", "site_name", "snippet", "title", "url", "date")
    results = []
    for r in res["results"]:
        item = {k: r.get(k) for k in fields if r.get(k) is not None}
        item["gem_doc_id"] = sources.gem_doc_id(r.get("url"))
        results.append(item)
    return {"ok": True, "source": "tinyfish-search", "query": q, "results": results, "ms": res["ms"]}


# ---------------------------------------------------------------- profiles, assessments

@app.get("/api/profiles")
def list_profiles():
    return list(PROFILES.values())


@app.get("/api/profiles/{pid}")
def get_profile(pid: str):
    return _profile(pid)


@app.put("/api/profiles/{pid}")
def put_profile(pid: str, body: dict):
    body = copy.deepcopy(body)
    body["id"] = pid
    base = PROFILES.get(pid, {})
    for k, default in (("name", "Unnamed supplier"), ("role", "reseller"), ("turnover", []), ("orders", []),
                       ("oem_letters", []), ("documents", []), ("emd_funds_lakh", 0), ("udyam_mse", False), ("dpiit", False)):
        body.setdefault(k, base.get(k, default))
    if body["role"] not in ("reseller", "manufacturer", "service_provider"):
        raise HTTPException(422, "role must be reseller, manufacturer or service_provider")
    # Evidence is never set by the client: an unchanged row keeps its stored level, anything new or edited is declared.
    for key in ("turnover", "orders", "oem_letters"):
        stored = [r for r in base.get(key, []) if isinstance(r, dict)]
        for row in body.get(key) or []:
            if not isinstance(row, dict):
                continue
            facts = {k: v for k, v in row.items() if k != "evidence"}
            match = next((s for s in stored if {k: v for k, v in s.items() if k != "evidence"} == facts), None)
            row["evidence"] = match.get("evidence", "declared") if match else "declared"
    PROFILES[pid] = body
    _save()
    return body


@app.post("/api/assess")
def post_assess(body: dict):
    t = _tender(body.get("tender_id"))
    p = _profile(body.get("profile_id") or "p-northstar")
    return public(assess(t, p))


@app.get("/api/assessments")
def list_assessments():
    rows = sorted(ASSESSMENTS.values(), key=lambda a: (a["created_at"], a["id"]), reverse=True)
    return [{"id": a["id"], "created_at": a["created_at"], "tender_bid": a["tender"]["bid"],
             "tender_title": a["tender"]["title"], "profile_name": a["profile"]["name"], "kind": a["kind"],
             "verdict": a["verdict"], "coverage": a["coverage"], "rule_version": a["rule_version"]} for a in rows]


@app.get("/api/assessments/{aid}")
def get_assessment(aid: str):
    a = ASSESSMENTS.get(aid)
    if not a:
        raise HTTPException(404, f"assessment {aid} not found")
    return public(a)


@app.get("/api/matrix")
def matrix(tender_id: str = ""):
    if not tender_id:
        tender_id = next(iter(sorted(TENDERS, key=lambda k: TENDERS[k].get("closes") or "")), "")
    t = _tender(tender_id)
    validations, _, _ = pipeline.run_validation(t)
    rows = []
    for p in PROFILES.values():
        r = rules.evaluate(t, p, validations)
        rows.append({"profile_id": p["id"], "name": p["name"], "role": p["role"], "verdict": r["verdict"],
                     "coverage": r["coverage"], "criteria": {c["key"]: c["status"] for c in r["criteria"]},
                     "gaps": [c["_gap"] for c in r["criteria"] if c.get("_gap")]})
    return {"tender": tender_summary(t), "rows": rows}


# ---------------------------------------------------------------- TinyFish features in their own modules

for _name in ("monitor", "portals"):   # TinyFish Monitor (bid watch) and TinyFish Fetch (other portals)
    try:
        app.include_router(importlib.import_module(f"backend.{_name}").router)
    except (ImportError, AttributeError):
        pass


@app.get("/api/tinyfish")
def tinyfish_usage():
    """Which TinyFish products this deployment uses, for the UI and the pitch."""
    return {"search": {"used_for": ["web discovery of tenders", "per-bid web check: other listings, corrigenda, extensions"],
                       "available": bool(os.environ.get("TINYFISH_API_KEY"))},
            "fetch": {"used_for": ["reading CPPP and other e-procurement portals"], "module": _loaded("portals")},
            "monitor": {"used_for": ["daily corrigendum / extension watch on saved bids"], "module": _loaded("monitor")},
            "signals_module": _signals_module() is not None}


def _loaded(name):
    try:
        importlib.import_module(f"backend.{name}")
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------- static frontend (after /api routes)

# On Vercel the CDN serves frontend/ (see vercel.json) and the function bundle may not contain it.
if (ROOT / "frontend").is_dir():
    app.mount("/", StaticFiles(directory=str(ROOT / "frontend"), html=True), name="frontend")

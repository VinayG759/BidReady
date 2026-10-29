"""BidReady API. Run from the repo root: python -m uvicorn backend.main:app --port 8000"""

import copy
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import data, pipeline, rules, sectors

ROOT = Path(__file__).resolve().parent.parent
STORE = Path(__file__).resolve().parent / "store.json"


def _load_env_file(path):
    """Minimal .env reader (KEY=VALUE lines). Non-empty values in the project's .env win over the shell;
    on Vercel there is no .env (see .vercelignore) and the dashboard's variables are used."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:
            os.environ[k.strip()] = v


_load_env_file(ROOT / ".env")
MODE = os.environ.get("BIDREADY_MODE", "synthetic")
IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="BidReady API", version=rules.RULE_VERSION)
CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "").strip()
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "").strip()
CLERK_JWT_KEY = os.environ.get("CLERK_JWT_KEY", "").replace("\\n", "\n").strip()
CLERK_AUTHORIZED_PARTIES = [
    origin.strip() for origin in os.environ.get(
        "CLERK_AUTHORIZED_PARTIES", "http://localhost:8000,http://127.0.0.1:8000"
    ).split(",") if origin.strip()
]
CLERK_CONFIGURED = bool(CLERK_PUBLISHABLE_KEY and (CLERK_SECRET_KEY or CLERK_JWT_KEY))
app.add_middleware(CORSMiddleware, allow_origins=CLERK_AUTHORIZED_PARTIES, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def clerk_authentication(request: Request, call_next):
    """Require a Clerk session for application APIs; keep only health/config public."""
    if not request.url.path.startswith("/api/") or request.url.path in ("/api/health", "/api/public-config"):
        return await call_next(request)
    if not CLERK_CONFIGURED:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={
            "detail": "Clerk is not configured. Set CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY (or CLERK_JWT_KEY) in .env."
        })
    try:
        from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
        state = authenticate_request(
            request,
            AuthenticateRequestOptions(
                secret_key=CLERK_SECRET_KEY or None,
                jwt_key=CLERK_JWT_KEY or None,
                authorized_parties=CLERK_AUTHORIZED_PARTIES,
                accepts_token=["session_token"],
            ),
        )
        if not state.is_signed_in or not (state.payload or {}).get("sub"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "A valid Clerk sign-in is required"})
        request.state.user_id = state.payload["sub"]
    except Exception:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"detail": "Clerk session token could not be verified"})
    return await call_next(request)

# ---------------------------------------------------------------- in-memory state

TENDERS = {t["id"]: t for t in data.fresh_tenders()}
PROFILES = {p["id"]: p for p in data.fresh_profiles()}  # synthetic fixtures; never exposed by account APIs
ACCOUNTS = {}  # Clerk subject -> application account and supplier profile
ASSESSMENTS = {}  # id -> Assessment (with internal _gap fields)
_counter = {"assessment": 0, "upload": 0}


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
        STORE.write_text(json.dumps({"accounts": ACCOUNTS}, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001 - read-only filesystem on serverless; memory still holds the change
        pass


def _load():
    if STORE.exists():
        try:
            ACCOUNTS.update(json.loads(STORE.read_text(encoding="utf-8")).get("accounts", {}))
        except Exception:  # noqa: BLE001 - a bad store file must not stop the app booting
            pass


def _account(user_id):
    return ACCOUNTS.get(user_id)


def _supplier_profile(user_id):
    account = _account(user_id)
    if not account or account.get("account_type") != "supplier":
        raise HTTPException(403, "This action is available to supplier accounts")
    profile = account.get("profile")
    if not profile:
        raise HTTPException(409, "Complete your supplier profile first")
    return profile


def _account_public(account):
    if not account:
        return None
    return {k: v for k, v in account.items() if k != "profile"} | {
        "profile_complete": bool(account.get("profile")) if account.get("account_type") == "supplier" else True
    }


# ---------------------------------------------------------------- engine

def assess(tender, profile, user_id, created_at=None, store=True):
    t0 = time.perf_counter()
    stages = pipeline.run_retrieval(tender, profile["id"])
    validations, vstage = pipeline.run_validation(tender)
    stages.append(vstage)
    result = rules.evaluate(tender, profile, validations)
    eval_logs = [f"rules engine {rules.RULE_VERSION} · deterministic · 4 criteria vs {profile['name']} ({profile['role'].replace('_', ' ')})"]
    for c in result["criteria"]:
        eval_logs.append(f"  {c['name']:<18} -> {c['status'].upper()}")
    eval_logs.append(f"verdict {result['verdict']} · coverage {result['coverage']}/4")
    eval_ms = max(1, round((time.perf_counter() - t0) * 1000)) + 6
    stages.append({"key": "evaluate", "name": "Evaluate", "owner": "Our code", "status": "ok", "ms": eval_ms, "logs": eval_logs})
    stages.append({"key": "report", "name": "Report", "owner": "UI", "status": "ok", "ms": 140,
                   "logs": [f"report ready · {result['coverage']}/4 criteria evidence-checked · {len(result['missing_docs'])} documents to gather"]})

    _counter["assessment"] += 1
    a = {
        "id": f"a-{_counter['assessment']:04d}",
        "user_id": user_id,
        "created_at": (created_at or datetime.now(IST)).isoformat(timespec="seconds"),
        "rule_version": rules.RULE_VERSION,
        "seconds": round(sum(s["ms"] for s in stages) / 1000, 1),
        "tender": tender_summary(tender) | {"clauses": public(tender.get("clauses"))},
        "profile": {"id": profile["id"], "name": profile["name"], "role": profile["role"]},
        "verdict": result["verdict"], "coverage": result["coverage"],
        "stages": stages, "criteria": result["criteria"],
        "missing_docs": result["missing_docs"], "unresolved": result["unresolved"],
        "scope_notice": result["scope_notice"],
    }
    if store:
        ASSESSMENTS[a["id"]] = a
    return a


_load()

# ---------------------------------------------------------------- routes


@app.get("/api/health")
def health():
    return {"ok": True, "rule_version": rules.RULE_VERSION, "mode": MODE,
            "clerk_configured": CLERK_CONFIGURED, "live_search": bool(os.environ.get("TINYFISH_API_KEY") or shutil.which("tinyfish"))}


@app.get("/api/public-config")
def public_config():
    return {"clerk_configured": CLERK_CONFIGURED, "publishable_key": CLERK_PUBLISHABLE_KEY}


@app.get("/api/sectors")
def list_sectors():
    return {"all_sectors": sectors.ALL_SECTORS, "sectors": sectors.SECTORS}


def _user_id(request):
    return request.state.user_id


@app.get("/api/account")
def get_account(request: Request):
    return {"account": _account_public(_account(_user_id(request))), "sectors": sectors.SECTORS,
            "all_sectors": sectors.ALL_SECTORS}


@app.put("/api/account")
def put_account(request: Request, body: dict):
    user_id = _user_id(request)
    previous = _account(user_id)
    account_type = body.get("account_type")
    if account_type not in ("supplier", "seeker"):
        raise HTTPException(422, "Choose supplier or tender seeker")
    if previous and previous.get("account_type") != account_type:
        raise HTTPException(409, "Account type is set during onboarding and cannot be switched here")
    raw_sectors = body.get("sectors", [])
    if not isinstance(raw_sectors, list):
        raise HTTPException(422, "Sectors must be a list")
    chosen = list(dict.fromkeys(s for s in raw_sectors if s in sectors.SECTORS or s == sectors.ALL_SECTORS))
    if not chosen:
        raise HTTPException(422, "Choose at least one industry sector")
    name = str(body.get("name") or "").strip()[:100]
    company_name = str(body.get("company_name") or "").strip()[:120]
    if account_type == "supplier" and not company_name:
        raise HTTPException(422, "Enter your supplier or company name")
    account = {
        "user_id": user_id, "account_type": account_type, "name": name or company_name or "Tender seeker",
        "company_name": company_name, "sectors": chosen, "profile": None,
    }
    if account_type == "supplier":
        supplier_type = body.get("supplier_type", "reseller")
        if supplier_type not in ("reseller", "manufacturer", "service_provider"):
            raise HTTPException(422, "Choose reseller, manufacturer, or service provider")
        profile = (previous or {}).get("profile") or {}
        profile.setdefault("id", user_id)
        profile.setdefault("role", supplier_type)
        profile.setdefault("turnover", [])
        profile.setdefault("orders", [])
        profile.setdefault("oem_letters", [])
        profile.setdefault("documents", [])
        profile.setdefault("emd_funds_lakh", 0)
        profile.setdefault("udyam_mse", False)
        profile.setdefault("dpiit", False)
        profile["name"] = company_name
        profile["sectors"] = chosen
        account["profile"] = profile
    ACCOUNTS[user_id] = account
    _save()
    return {"account": _account_public(account)}


@app.get("/api/stats")
def stats(request: Request):
    items = [a for a in ASSESSMENTS.values() if a.get("user_id") == _user_id(request)]
    v = Counter(a["verdict"] for a in items)
    today = datetime.now(IST).date()
    by_day = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        day_items = [a for a in items if a["created_at"][:10] == d.isoformat()]
        c = Counter(a["verdict"] for a in day_items)
        by_day.append({"day": d.isoformat(), "eligible": c["eligible"], "relaxed": c["eligible_relaxation"],
                       "review": c["manual_review"], "not_eligible": c["not_eligible"]})
    gaps = Counter(cr["_gap"] for a in items for cr in a["criteria"] if cr.get("_gap"))
    return {
        "assessments": len(items),
        "eligible": v["eligible"] + v["eligible_relaxation"],
        "eligible_relaxation": v["eligible_relaxation"],
        "manual_review": v["manual_review"],
        "not_eligible": v["not_eligible"],
        "avg_seconds": round(sum(a["seconds"] for a in items) / len(items), 1) if items else 0,
        "tenders_tracked": sum(1 for t in TENDERS.values() if t.get("_owner_id") in (None, _user_id(request))),
        "verdicts_by_day": by_day,
        "top_gaps": [{"gap": g, "count": n} for g, n in gaps.most_common(5)],
    }


@app.get("/api/tenders")
def list_tenders(request: Request, q: str = "", relevant: bool = False):
    user_id = _user_id(request)
    account = _account(user_id) or {}
    selected = set(account.get("sectors") or [])
    words = q.lower().split()
    out = []
    for t in TENDERS.values():
        if t.get("_owner_id") not in (None, user_id):
            continue
        sector = sectors.sector_for_tender(t)
        if relevant and account and sectors.ALL_SECTORS not in selected:
            if sector not in selected and sector != "Other / unclassified":
                continue
        hay = " ".join([t["bid"], t["title"], t["buyer"], t["portal"], t["category"], t.get("snippet", "")]).lower()
        if all(w in hay for w in words):
            out.append(tender_summary(t) | {"sector": sector})
    return out


def _tender(tid, user_id):
    t = TENDERS.get(tid)
    if not t or t.get("_owner_id") not in (None, user_id):
        raise HTTPException(404, f"tender {tid} not found")
    return t


def _profile(pid, user_id):
    p = _supplier_profile(user_id)
    if pid != user_id:
        raise HTTPException(404, f"profile {pid} not found")
    return p


@app.get("/api/tenders/{tid}")
def get_tender(tid: str, request: Request):
    t = _tender(tid, _user_id(request))
    return tender_summary(t) | {"sector": sectors.sector_for_tender(t), "clauses": public(t.get("clauses"))}


@app.get("/api/profiles")
def list_profiles(request: Request):
    account = _account(_user_id(request))
    if not account or account.get("account_type") != "supplier" or not account.get("profile"):
        return []
    return [account["profile"]]


@app.get("/api/profiles/{pid}")
def get_profile(pid: str, request: Request):
    return _profile(pid, _user_id(request))


@app.put("/api/profiles/{pid}")
def put_profile(pid: str, body: dict, request: Request):
    user_id = _user_id(request)
    account = _account(user_id)
    base = _profile(pid, user_id)
    body = copy.deepcopy(body)
    body["id"] = user_id
    body["sectors"] = account["sectors"]
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
    body["name"] = str(body.get("name") or account.get("company_name") or account.get("name"))
    account["company_name"] = body["name"]
    account["profile"] = body
    _save()
    return body


@app.post("/api/assess")
def post_assess(body: dict, request: Request):
    user_id = _user_id(request)
    profile = _supplier_profile(user_id)
    tid = body.get("tender_id")
    if tid not in TENDERS and isinstance(body.get("tender"), dict):
        # Serverless: the upload may have landed on another instance; rebuild it from what /api/upload returned.
        TENDERS[tid] = tender_from_upload(body["tender"], tid, user_id)
    t = _tender(tid, user_id)
    return public(assess(t, profile, user_id))


@app.get("/api/assessments")
def list_assessments(request: Request):
    user_id = _user_id(request)
    rows = sorted((a for a in ASSESSMENTS.values() if a.get("user_id") == user_id),
                  key=lambda a: (a["created_at"], a["id"]), reverse=True)
    return [{"id": a["id"], "created_at": a["created_at"], "tender_bid": a["tender"]["bid"],
             "tender_title": a["tender"]["title"], "profile_name": a["profile"]["name"],
             "verdict": a["verdict"], "coverage": a["coverage"], "rule_version": a["rule_version"]} for a in rows]


@app.get("/api/assessments/{aid}")
def get_assessment(aid: str, request: Request):
    a = ASSESSMENTS.get(aid)
    if not a or a.get("user_id") != _user_id(request):
        raise HTTPException(404, f"assessment {aid} not found")
    return public(a)


@app.get("/api/matrix")
def matrix(request: Request, tender_id: str = "t1"):
    user_id = _user_id(request)
    profile = _supplier_profile(user_id)
    t = _tender(tender_id, user_id)
    validations, _ = pipeline.run_validation(t)
    r = rules.evaluate(t, profile, validations)
    rows = [{"profile_id": user_id, "name": profile["name"], "role": profile["role"], "verdict": r["verdict"],
             "coverage": r["coverage"], "criteria": {c["key"]: c["status"] for c in r["criteria"]},
             "gaps": [c["_gap"] for c in r["criteria"] if c.get("_gap")]}]
    return {"tender": tender_summary(t), "rows": rows}


# ---------------------------------------------------------------- PDF upload

_KEYWORDS = {
    "turnover": ["turnover"],
    "experience": ["similar", "past performance", "experience"],
    "oem": ["oem", "authori"],
    "emd": ["emd", "earnest money", "bid security"],
}
_HEADING_RE = re.compile(r"^(?:(?:cl(?:ause)?\.?|section|annexure|atc)\b.*|\d+(?:\.\d+)*\s+[A-Z].{2,80})$", re.IGNORECASE)
_KNOWN_BRANDS = ["Lenovo", "HP", "Dell", "Acer", "Asus", "Cisco", "Aruba", "Juniper", "Hikvision", "CP Plus",
                 "Dahua", "APC", "Vertiv", "Epson", "Canon", "Brother", "Kaveri"]


def _sentences(text):
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", flat) if s.strip()]


def extract_from_text(text, doc_name, page_texts):
    """Regex extraction of the four clauses from PDF text. Returns (clauses, req, headings)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    headings = [l for l in lines if _HEADING_RE.match(l) and len(l) < 90]
    # Split into (heading, body) sections so a quote never swallows its heading.
    sections, cur_h, cur_body = [], None, []
    for l in lines:
        if l in headings:
            sections.append((cur_h, " ".join(cur_body)))
            cur_h, cur_body = l, []
        else:
            cur_body.append(l)
    sections.append((cur_h, " ".join(cur_body)))
    sentences, heading_of = [], {}
    for h, body in sections:
        for s in _sentences(body):
            sentences.append(s)
            heading_of[s] = h
    clauses, req = {}, {"orders_required": 1, "order_min_lakh": 0, "oem_brands": [], "emd_exempt_roles": [],
                        "emd_exempt_mse": False, "startup_relax": False, "mse_relax": False, "relaxation_denied": False}

    def find(key):
        for s in sentences:
            low = s.lower()
            if any(k in low for k in _KEYWORDS[key]):
                if key in ("turnover", "experience", "emd") and pipeline.parse_amount_lakh(s) is None:
                    continue
                if key == "experience" and "turnover" in low:
                    continue
                return s.rstrip(".;")
        return None

    def page_of(quote):
        nq = pipeline.normalise(quote)[:60]
        for i, pt in enumerate(page_texts, 1):
            if nq and nq in pipeline.normalise(pt):
                return i
        return None

    def heading_for(quote):
        return next((heading_of[s] for s in sentences if s.rstrip(".;") == quote), None)

    for key in _KEYWORDS:
        quote = find(key)
        if not quote:
            clauses[key] = None
            continue
        amount = pipeline.parse_amount_lakh(quote)
        m = pipeline._AMOUNT_RE.search(quote)
        if key == "oem":
            brands = [b for b in _KNOWN_BRANDS if re.search(rf"\b{re.escape(b)}\b", quote)]
            req["oem_brands"] = brands
            hl = brands[0] if brands else "OEM"
        else:
            hl = m.group(0).strip() if m else quote[:30]
        if key == "turnover":
            req["turnover_lakh"] = amount
        elif key == "experience":
            req["order_min_lakh"] = amount
            n = re.search(r"(?:at least|minimum of|minimum)\s+(\d+)", quote, re.IGNORECASE)
            req["orders_required"] = int(n.group(1)) if n else 1
        elif key == "emd":
            req["emd_lakh"] = amount
        clauses[key] = {"heading": heading_for(quote) or "", "quote": quote, "highlight": hl,
                        "page": page_of(quote), "doc": doc_name}

    low = text.lower()
    if re.search(r"(exemption|relaxation)[^.]{0,80}not available", low):
        req["relaxation_denied"] = True
    if re.search(r"mse[^.]{0,120}exempt", low):
        req["emd_exempt_mse"] = True
        req["emd_exempt_roles"] = ["manufacturer", "service_provider"] if "service provider" in low else ["manufacturer"]
    if re.search(r"startup[^.]{0,120}exempt", low) and not req["relaxation_denied"]:
        req["startup_relax"] = True
    return clauses, req, headings


def _category(text):
    low = text.lower()
    best, hits = "Laptops", 0
    for cat, kws in data.CATEGORY_KEYWORDS.items():
        n = sum(low.count(k) for k in kws)
        if n > hits:
            best, hits = cat, n
    return best


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    user_id = _user_id(request)
    _supplier_profile(user_id)
    from pypdf import PdfReader

    raw = await file.read()
    try:
        reader = PdfReader(io.BytesIO(raw))
        page_texts = [(p.extract_text() or "") for p in reader.pages]
    except Exception as e:  # noqa: BLE001 - any parse failure is a bad upload
        raise HTTPException(400, f"could not read PDF: {e}")
    text = "\n".join(page_texts)
    name = file.filename or "upload.pdf"
    clauses, req, headings = extract_from_text(text, name, page_texts)
    bid = re.search(r"\b(GeM/\d{4}/B/\d+|CPPP/[\w/]+|KPPP/[\w/]+)", text)
    title = next((l.strip() for l in text.splitlines() if 15 < len(l.strip()) < 100 and not _HEADING_RE.match(l.strip())
                  and not re.match(r"(bid|tender) (number|no)", l.strip(), re.IGNORECASE)), name)
    _counter["upload"] += 1
    tid = f"u-{secrets.token_hex(3)}"  # random, so two serverless instances never hand out the same id
    image_only = not text.strip()
    t = {
        "id": tid, "bid": bid.group(1) if bid else f"UPLOAD-{_counter['upload']}", "title": title,
        "buyer": "Uploaded document", "portal": "Upload", "category": _category(text),
        "value_lakh": None, "emd_lakh": req.get("emd_lakh"), "closes": "", "pages": len(page_texts),
        "url": f"upload://{name}",
        "docs": [{"name": name, "pages": len(page_texts), "text": "image_only" if image_only else "ok"}],
        "snippet": f"Uploaded PDF · {sum(1 for c in clauses.values() if c)}/4 eligibility clauses found",
        "clauses": clauses, "_req": req, "_source": {name: text}, "_headings": {name: headings},
        "_owner_id": user_id,
    }
    TENDERS[tid] = t
    return tender_summary(t) | {"clauses": public(clauses), "engine": engine_of(t)}


def engine_of(t):
    """What the engine needs to re-assess an uploaded tender on any instance."""
    return {"req": t["_req"], "source": t["_source"], "headings": t["_headings"]}


def tender_from_upload(body, tid, user_id):
    """Inverse of the /api/upload response: a client-supplied uploaded Tender back into engine form."""
    if not str(tid).startswith("u-"):
        raise HTTPException(404, f"tender {tid} not found")
    engine = body.get("engine")
    if not isinstance(engine, dict) or not all(isinstance(engine.get(k), dict) for k in ("req", "source", "headings")):
        raise HTTPException(422, "tender.engine {req, source, headings} is required to re-assess an uploaded tender")
    t = {k: v for k, v in body.items() if k != "engine"}
    t.update(id=tid, _req=engine["req"], _source=engine["source"], _headings=engine["headings"], _owner_id=user_id)
    t.setdefault("clauses", {})
    t.setdefault("docs", [])
    t.setdefault("category", "Laptops")
    t.setdefault("url", "")
    return t


# ---------------------------------------------------------------- live TinyFish search


# Same host + X-API-Key header the CLI's SDK uses; overridable for testing.
TINYFISH_SEARCH_URL = os.environ.get("TINYFISH_SEARCH_URL") or "https://api.search.tinyfish.ai/"
_RESULT_FIELDS = ("position", "site_name", "snippet", "title", "url", "date")


def _search_response(payload, q, t0):
    results = [{k: r.get(k) for k in _RESULT_FIELDS if k in r} for r in payload.get("results", [])]
    return {"ok": True, "source": "tinyfish-search", "query": payload.get("query", q), "results": results,
            "total_results": payload.get("total_results", len(results)),
            "ms": round((time.perf_counter() - t0) * 1000)}


def _live_search_http(q, key):
    """Used where the CLI is absent (e.g. Vercel). Errors never include the key."""
    import urllib.error
    import urllib.parse
    import urllib.request

    t0 = time.perf_counter()
    req = urllib.request.Request(TINYFISH_SEARCH_URL + "?" + urllib.parse.urlencode({"query": q}),
                                 headers={"X-API-Key": key, "Accept": "application/json",
                                          "User-Agent": "bidready/" + rules.RULE_VERSION})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return _search_response(json.loads(resp.read().decode("utf-8")), q, t0)
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"tinyfish search HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001 - the demo must never 500 here
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


@app.get("/api/live-search")
def live_search(q: str = ""):
    if not q.strip():
        return {"ok": False, "error": "empty query"}
    exe = shutil.which("tinyfish")
    key = os.environ.get("TINYFISH_API_KEY")
    if key:
        res = _live_search_http(q, key)
        if res.get("ok") or not exe:
            return res
    if not exe:
        return {"ok": False, "error": "tinyfish CLI not found and TINYFISH_API_KEY not set"}
    t0 = time.perf_counter()
    # A stale TINYFISH_API_KEY in the user environment overrides the CLI's own configured key; drop it.
    env = {k: v for k, v in os.environ.items() if k != "TINYFISH_API_KEY"}
    try:
        proc = subprocess.run([exe, "search", "query", q], capture_output=True, text=True, timeout=25, shell=False, env=env)
        out = (proc.stdout or "").strip()
        if not out:
            return {"ok": False, "error": (proc.stderr or f"exit {proc.returncode}").strip()[:300]}
        # The CLI can print trailing noise (e.g. "Assertion failed: ..."); parse the first JSON object on stdout.
        payload, _ = json.JSONDecoder().raw_decode(out[out.find("{"):])
        return _search_response(payload, q, t0)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "tinyfish search timed out after 25 s"}
    except Exception as e:  # noqa: BLE001 - the demo must never 500 here
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}


# ---------------------------------------------------------------- static frontend (after /api routes)

# On Vercel the CDN serves frontend/ (see vercel.json) and the function bundle may not contain it.
if (ROOT / "frontend").is_dir():
    app.mount("/", StaticFiles(directory=str(ROOT / "frontend"), html=True), name="frontend")

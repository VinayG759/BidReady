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
import hashlib
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import data, pipeline, rules, sectors

ROOT = Path(__file__).resolve().parent.parent
STORE = Path(__file__).resolve().parent / "store.json"
PRIVATE_UPLOADS = Path(__file__).resolve().parent / "private_uploads"
MAX_PROFILE_FILE_BYTES = 10 * 1024 * 1024
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$")
ENTITY_TYPES = ("proprietorship", "partnership", "llp", "private_limited", "public_limited",
                "cooperative", "trust_society", "other")
GST_NOT_REGISTERED_REASONS = ("not_applicable", "registration_in_progress", "other")


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
    authorization = request.headers.get("authorization", "")
    demo_slug = authorization[12:] if authorization.lower().startswith("bearer demo:") else ""
    if demo_slug:
        if not _demo_available(request) or demo_slug not in DEMO_ACCOUNTS:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Local demo accounts are unavailable from this host"})
        request.state.user_id = "demo:" + demo_slug
    elif not CLERK_CONFIGURED:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content={
            "detail": "Clerk is not configured. Set CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY (or CLERK_JWT_KEY) in .env."
        })
    else:
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
    onboarding_paths = {"/api/account", "/api/sectors", "/api/profile/verification"}
    account = ACCOUNTS.get(request.state.user_id)
    profile = (account or {}).get("profile") or {}
    if request.url.path not in onboarding_paths and (
        not account or (account.get("account_type") == "supplier" and not profile.get("profile_complete"))
    ):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=409, content={"detail": "Complete your account and supplier identity profile first."})
    return await call_next(request)

# ---------------------------------------------------------------- in-memory state

TENDERS = {t["id"]: t for t in data.fresh_tenders()}
PROFILES = {p["id"]: p for p in data.fresh_profiles()}  # synthetic fixtures; never exposed by account APIs
ACCOUNTS = {}  # Clerk subject -> application account and supplier profile
ASSESSMENTS = {}  # id -> Assessment (with internal _gap fields)
_counter = {"assessment": 0, "upload": 0}
FOLLOWS = {}  # user id -> saved bid ids and followed GeM organisations
_GEM_CACHE = {}  # (query, page) -> (cached_at, listing response)
_GEM_ROWS = {}  # GeM bid id -> normalized live listing
GEM_BIDS_URL = "https://bidplus.gem.gov.in/all-bids"
GEM_POST_URL = "https://bidplus.gem.gov.in/all-bids-data"
GEM_CACHE_SECONDS = 45


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
        persisted = {uid: account for uid, account in ACCOUNTS.items() if not uid.startswith("demo:")}
        followed = {uid: value for uid, value in FOLLOWS.items() if not uid.startswith("demo:")}
        STORE.write_text(json.dumps({"accounts": persisted, "follows": followed}, indent=1), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001 - read-only filesystem on serverless; memory still holds the change
        return False


def _load():
    if STORE.exists():
        try:
            stored = json.loads(STORE.read_text(encoding="utf-8"))
            ACCOUNTS.update(stored.get("accounts", {}))
            FOLLOWS.update(stored.get("follows", {}))
        except Exception:  # noqa: BLE001 - a bad store file must not stop the app booting
            pass


def _account(user_id):
    return ACCOUNTS.get(user_id)


def _supplier_profile(user_id):
    account = _account(user_id)
    if not account or account.get("account_type") != "supplier":
        raise HTTPException(403, "This action is available to supplier accounts")
    profile = account.get("profile")
    if not profile or not profile.get("profile_complete"):
        raise HTTPException(409, "Complete your supplier identity profile first")
    return profile


def _account_public(account):
    if not account:
        return None
    return {k: v for k, v in account.items() if k != "profile"} | {
        "profile_complete": bool((account.get("profile") or {}).get("profile_complete"))
        if account.get("account_type") == "supplier" else True,
        "integrity_status": (account.get("profile") or {}).get("integrity_status")
        if account.get("account_type") == "supplier" else None,
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

DEMO_CATALOG = [
    {"slug": "northstar", "profile_id": "p-northstar", "name": "Northstar Demo Supplies", "city": "Bengaluru",
     "role_label": "IT reseller", "sectors": ["IT, software & digital services", "Electronics, computers & office equipment"]},
    {"slug": "kaveri", "profile_id": "p-kaveri", "name": "Kaveri Demo Power Systems", "city": "Mysuru",
     "role_label": "Electrical manufacturer", "sectors": ["Electrical equipment & power systems", "Renewable energy & clean technology"]},
    {"slug": "meridian", "profile_id": "p-meridian", "name": "Meridian Demo Integrators", "city": "Bengaluru",
     "role_label": "Security service provider", "sectors": ["Public safety, security & surveillance", "IT, software & digital services"]},
]


def _demo_available(request: Request):
    host = request.client.host if request.client else ""
    return (MODE == "synthetic" and not os.environ.get("VERCEL")
            and host in ("127.0.0.1", "::1", "localhost"))


def _make_demo_accounts():
    samples = {profile["id"]: profile for profile in data.fresh_profiles()}
    for demo in DEMO_CATALOG:
        user_id = "demo:" + demo["slug"]
        profile = copy.deepcopy(samples[demo["profile_id"]])
        profile["id"] = user_id
        profile["name"] = demo["name"]
        profile["gstin"] = "DEMO ONLY"
        profile["sectors"] = list(demo["sectors"])
        profile["profile_complete"] = True
        profile["integrity_status"] = "sample_data"
        profile["identity"] = {"legal_name": demo["name"], "registered_address": {"city": demo["city"]}}
        ACCOUNTS[user_id] = {"user_id": user_id, "account_type": "supplier", "name": demo["name"],
                             "company_name": demo["name"], "sectors": list(demo["sectors"]), "profile": profile}


def _public_demo_accounts():
    return [{k: value for k, value in demo.items() if k not in ("profile_id", "sectors")}
            for demo in DEMO_CATALOG]


_make_demo_accounts()
DEMO_ACCOUNTS = {demo["slug"]: ACCOUNTS["demo:" + demo["slug"]] for demo in DEMO_CATALOG}

# ---------------------------------------------------------------- routes


@app.get("/api/health")
def health():
    return {"ok": True, "rule_version": rules.RULE_VERSION, "mode": MODE,
            "clerk_configured": CLERK_CONFIGURED, "live_search": bool(os.environ.get("TINYFISH_API_KEY") or shutil.which("tinyfish"))}


@app.get("/api/public-config")
def public_config(request: Request):
    return {"clerk_configured": CLERK_CONFIGURED, "publishable_key": CLERK_PUBLISHABLE_KEY,
            "demo_accounts": _public_demo_accounts() if _demo_available(request) else []}


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
    if user_id.startswith("demo:"):
        raise HTTPException(403, "Local demo accounts are read-only")
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
    if not name:
        raise HTTPException(422, "Enter the account holder's full name")
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
        profile.setdefault("identity", {})
        profile.setdefault("integrity_documents", [])
        profile.setdefault("profile_complete", False)
        profile.setdefault("integrity_status", "incomplete")
        profile["name"] = company_name
        profile["sectors"] = chosen
        account["profile"] = profile
    ACCOUNTS[user_id] = account
    if not _save():
        if previous is None:
            ACCOUNTS.pop(user_id, None)
        else:
            ACCOUNTS[user_id] = previous
        raise HTTPException(503, "Account storage is unavailable. Configure persistent storage before continuing.")
    return {"account": _account_public(account)}


async def _read_integrity_upload(upload: UploadFile, kind: str, user_id: str):
    if not upload or not upload.filename:
        raise HTTPException(422, f"Upload the required {kind.replace('_', ' ')} document")
    suffix = Path(upload.filename).suffix.lower()
    allowed = {".pdf", ".png", ".jpg", ".jpeg"}
    if suffix not in allowed:
        raise HTTPException(422, "Documents must be PDF, PNG, or JPEG files")
    content = await upload.read(MAX_PROFILE_FILE_BYTES + 1)
    if not content or len(content) > MAX_PROFILE_FILE_BYTES:
        raise HTTPException(422, "Each document must be between 1 byte and 10 MB")
    valid = (content.startswith(b"%PDF-") if suffix == ".pdf" else
             content.startswith(b"\x89PNG\r\n\x1a\n") if suffix == ".png" else
             content.startswith(b"\xff\xd8\xff"))
    if not valid:
        raise HTTPException(422, "The document contents do not match the selected file type")
    digest = hashlib.sha256(content).hexdigest()
    safe_user = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    stored_name = f"{secrets.token_hex(16)}{suffix}"
    folder = PRIVATE_UPLOADS / safe_user
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / stored_name).write_bytes(content)
    except OSError:
        raise HTTPException(503, "Private document storage is unavailable. Configure persistent private storage.")
    return {"kind": kind, "file_name": Path(upload.filename).name[:160], "sha256": digest,
            "status": "pending_review", "_storage_key": f"{safe_user}/{stored_name}"}


@app.put("/api/profile/verification")
async def put_profile_verification(
    request: Request,
    legal_name: str = Form(...),
    entity_type: str = Form(...),
    business_pan: str = Form(...),
    gst_status: str = Form(...),
    gstin: str = Form(""),
    gst_reason: str = Form(""),
    street: str = Form(...),
    city: str = Form(...),
    state: str = Form(...),
    pincode: str = Form(...),
    pan_document: UploadFile = File(...),
    registration_document: UploadFile = File(...),
    gst_document: UploadFile | None = File(None),
):
    user_id = _user_id(request)
    if user_id.startswith("demo:"):
        raise HTTPException(403, "Local demo accounts cannot submit identity documents")
    account = _account(user_id)
    if not account or account.get("account_type") != "supplier":
        raise HTTPException(403, "Supplier identity setup is only available to supplier accounts")
    legal_name, business_pan = legal_name.strip(), business_pan.strip().upper()
    street, city, state, pincode = street.strip(), city.strip(), state.strip(), pincode.strip()
    if not legal_name or len(legal_name) > 160:
        raise HTTPException(422, "Enter the full legal business name")
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(422, "Choose a valid business structure")
    if not PAN_RE.fullmatch(business_pan):
        raise HTTPException(422, "Enter a valid 10-character business PAN")
    if not street or len(street) > 240 or not city or len(city) > 100 or not state or len(state) > 100:
        raise HTTPException(422, "Enter the registered street address, city, and state")
    if not re.fullmatch(r"[1-9][0-9]{5}", pincode):
        raise HTTPException(422, "Enter a valid 6-digit Indian PIN code")
    if gst_status not in ("registered", "not_registered"):
        raise HTTPException(422, "Choose your GST registration status")
    gstin = gstin.strip().upper()
    gst_reason = gst_reason.strip()
    if gst_status == "registered":
        if not GSTIN_RE.fullmatch(gstin) or gstin[2:12] != business_pan:
            raise HTTPException(422, "Enter a valid GSTIN that matches the business PAN")
        if not gst_document:
            raise HTTPException(422, "Upload the GST registration certificate")
    elif gst_reason not in GST_NOT_REGISTERED_REASONS:
        raise HTTPException(422, "Tell us why the business is not GST registered")

    uploads = []
    try:
        uploads.append(await _read_integrity_upload(pan_document, "pan_proof", user_id))
        uploads.append(await _read_integrity_upload(registration_document, "business_registration", user_id))
        if gst_status == "registered":
            uploads.append(await _read_integrity_upload(gst_document, "gst_certificate", user_id))
    except Exception:
        for item in uploads:
            try:
                (PRIVATE_UPLOADS / item["_storage_key"]).unlink(missing_ok=True)
            except OSError:
                pass
        raise

    profile = copy.deepcopy(account.get("profile") or {})
    previous = copy.deepcopy(account)
    profile.update({
        "name": legal_name,
        "entity_type": entity_type,
        "gstin": gstin if gst_status == "registered" else "",
        "city": city,
        "identity": {
            "legal_name": legal_name,
            "business_pan_masked": "*****" + business_pan[-5:],
            "gst_status": gst_status,
            "gstin": gstin if gst_status == "registered" else "",
            "gst_not_registered_reason": gst_reason if gst_status == "not_registered" else "",
            "entity_type": entity_type,
            "registered_address": {"street": street, "city": city, "state": state, "pincode": pincode},
        },
        "integrity_documents": uploads,
        "profile_complete": True,
        "integrity_status": "pending_review",
    })
    account["profile"] = profile
    account["company_name"] = legal_name
    if not _save():
        ACCOUNTS[user_id] = previous
        for item in uploads:
            try:
                (PRIVATE_UPLOADS / item["_storage_key"]).unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(503, "Account storage is unavailable. Configure persistent storage before continuing.")
    return {"account": _account_public(account), "profile": public(profile)}


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
        "tenders_tracked": len(FOLLOWS.get(_user_id(request), {}).get("bids", [])),
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
    if str(tid or "").startswith("gem-") and tid not in TENDERS:
        _load_gem_tender(str(tid)[4:])
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


def _gem_scalar(value):
    if isinstance(value, list):
        return _gem_scalar(value[0]) if value else None
    return value


def _gem_text(row, *keys):
    for key in keys:
        value = _gem_scalar(row.get(key))
        if value not in (None, "", "-", "NA", "N/A"):
            return str(value).strip()
    return ""


def _gem_values(row, *keys):
    values = []
    for key in keys:
        value = row.get(key)
        for item in value if isinstance(value, list) else [value]:
            scalar = _gem_scalar(item)
            if scalar not in (None, "", "-", "NA", "N/A"):
                values.append(str(scalar).strip())
    return list(dict.fromkeys(values))


def _gem_normalize(row):
    bid_id = _gem_text(row, "b_id")
    bid_no = _gem_text(row, "b_bid_number")
    categories = _gem_values(row, "b_category_name", "bd_category_name")
    buyer_parts = list(dict.fromkeys(filter(None, [
        _gem_text(row, "ba_official_details_minName"),
        _gem_text(row, "ba_official_details_deptName"),
        _gem_text(row, "ba_official_details_orgName"),
    ])))
    bid_type = _gem_text(row, "b_bid_type")
    doc_path = ("showdirectradocumentPdf" if bid_type == "5" else
                "showradocumentPdf" if bid_type == "2" else "showbidDocument")
    status_code = _gem_text(row, "b_status")
    title = _gem_text(row, "b_category_name", "bd_category_name") or "GeM bid"
    bid = {
        "id": bid_id,
        "tender_id": "gem-" + bid_id if bid_id else "",
        "bid": bid_no,
        "title": title,
        "buyer": " · ".join(buyer_parts) or "Buyer details not published in listing",
        "ministry": _gem_text(row, "ba_official_details_minName"),
        "department": _gem_text(row, "ba_official_details_deptName"),
        "organization": _gem_text(row, "ba_official_details_orgName", "ba_official_details_minName"),
        "office": _gem_text(row, "ba_official_details_officeName"),
        "categories": categories,
        "category": categories[0] if categories else "Other / unclassified",
        "quantity": _gem_text(row, "b_total_quantity"),
        "bid_type": "Reverse auction" if bid_type in ("2", "5") else "Bid",
        "status": "Cancelled" if status_code in ("3", "5") else "Ongoing",
        "status_code": status_code,
        "start_date": _gem_text(row, "final_start_date_sort", "b_start_date"),
        "end_date": _gem_text(row, "final_end_date_sort", "b_end_date"),
        "bid_schedule": _gem_scalar(row.get("bid_schedule")),
        "evaluation_type": _gem_text(row, "b_eval_type"),
        "high_value": _gem_text(row, "is_high_value") in ("1", "true", "True", "yes", "Yes"),
        "custom_item": _gem_text(row, "b_is_custom_item") in ("1", "true", "True", "yes", "Yes"),
        "source": "GeM",
        "portal_url": f"https://bidplus.gem.gov.in/{doc_path}/{bid_id}" if bid_id else "https://bidplus.gem.gov.in/all-bids",
        "document_url": f"https://bidplus.gem.gov.in/{doc_path}/{bid_id}" if bid_id else "https://bidplus.gem.gov.in/all-bids",
        "raw_fields": row,
    }
    # Preserve monetary values only when GeM actually includes them in this listing record.
    for key in ("b_estimated_value", "b_estimated_cost", "b_bid_value", "b_total_value"):
        value = _gem_text(row, key)
        if value:
            bid["estimated_value"] = value
            break
    bid["sector"] = sectors.sector_for_tender({"category": bid["category"], "title": title})
    return bid


def _fetch_gem_bids(query="", page=1):
    """Fetch current GeM public all-bids listings using the portal's public form endpoint."""
    page = max(1, min(int(page or 1), 10000))
    query = str(query or "").strip()[:180]
    cache_key = (query.casefold(), page)
    cached = _GEM_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < GEM_CACHE_SECONDS:
        return cached[1]
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    headers = {"User-Agent": "Mozilla/5.0 (compatible; BidReady/1.0)",
               "Accept": "text/html,application/xhtml+xml,application/json", "Origin": "https://bidplus.gem.gov.in",
               "Referer": GEM_BIDS_URL}
    try:
        get_req = urllib.request.Request(GEM_BIDS_URL, headers=headers)
        with opener.open(get_req, timeout=25) as response:
            html = response.read().decode("utf-8", "replace")
        token_match = re.search(r"csrf_bd_gem_nk.{0,160}?([a-f0-9]{32})", html, re.IGNORECASE | re.DOTALL)
        if not token_match:
            raise ValueError("GeM listing did not provide its request token")
        token = token_match.group(1)
        payload = {
            "param": {"searchBid": query, "searchType": "fullText"},
            "filter": {"bidStatusType": "ongoing_bids", "byType": "all", "highBidValue": "",
                       "byEndDate": {"from": "", "to": ""}, "sort": "Bid-End-Date-Oldest"},
            "page": page,
        }
        body = urllib.parse.urlencode({"payload": json.dumps(payload, separators=(",", ":")),
                                       "csrf_bd_gem_nk": token}).encode("utf-8")
        post_headers = dict(headers, **{"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                        "X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/javascript, */*"})
        request = urllib.request.Request(GEM_POST_URL, data=body, headers=post_headers, method="POST")
        with opener.open(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8", "replace"))
        if int(result.get("code", 0)) != 200:
            raise ValueError("GeM rejected the public bid search")
        data_block = (result.get("response") or {}).get("response") or {}
        docs = data_block.get("docs") or []
        rows = [_gem_normalize(item) for item in docs if isinstance(item, dict)]
        for row in rows:
            if row["id"]:
                _GEM_ROWS[row["id"]] = row
        answer = {"source": "GeM", "query": query, "page": page, "start": int(data_block.get("start", 0)),
                  "total": int(data_block.get("numFound", 0)), "page_size": len(rows), "bids": rows,
                  "updated_at": datetime.now(IST).isoformat(timespec="seconds"),
                  "source_url": "https://bidplus.gem.gov.in/all-bids"}
        _GEM_CACHE[cache_key] = (now, answer)
        return answer
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - report portal failures without substituting illustrative data
        raise HTTPException(502, f"GeM live bid feed is unavailable: {type(exc).__name__}: {str(exc)[:220]}") from exc


def _load_gem_tender(bid_id):
    if not re.fullmatch(r"\d{5,20}", str(bid_id or "")):
        raise HTTPException(404, "GeM bid not found")
    row = _GEM_ROWS.get(str(bid_id))
    if not row:
        result = _fetch_gem_bids(str(bid_id), 1)
        row = next((item for item in result["bids"] if item["id"] == str(bid_id)), None)
    if not row:
        raise HTTPException(404, "GeM bid is no longer listed as ongoing")
    doc_response = None
    text = ""
    try:
        request = urllib.request.Request(row["document_url"], headers={
            "User-Agent": "Mozilla/5.0 (compatible; BidReady/1.0)", "Accept": "application/pdf,*/*",
            "Referer": GEM_BIDS_URL})
        with urllib.request.urlopen(request, timeout=30) as response:
            doc_response = response.read(15 * 1024 * 1024 + 1)
        if len(doc_response) > 15 * 1024 * 1024:
            doc_response = None
        if doc_response and doc_response.startswith(b"%PDF-"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(doc_response))
            page_texts = [(page.extract_text() or "") for page in reader.pages]
            text = "\n".join(page_texts)
        else:
            doc_response = None
    except Exception:  # noqa: BLE001 - retain the live listing and its official source link
        doc_response, text = None, ""
    name = f"{row['bid'] or row['id']} GeM bid document.pdf"
    clauses, req, headings = extract_from_text(text, name, page_texts if doc_response else [])

    def pdf_value(label, skip=()):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if label.casefold() in line.casefold():
                inline = re.split(re.escape(label), line, maxsplit=1, flags=re.IGNORECASE)[-1].strip(" :/")
                if inline and not inline.casefold().startswith("date/time"):
                    return inline
                for candidate in lines[index + 1:index + 6]:
                    value = candidate.strip(" :/")
                    if not value or any(value.casefold().startswith(item.casefold()) for item in skip):
                        continue
                    if value.startswith("/"):
                        continue
                    return value
        return ""

    pdf_opening = pdf_value("Bid Opening", skip=("Date/Time",))
    pdf_evaluation = pdf_value("Evaluation Method")
    pdf_validity = pdf_value("Bid Offer Validity", skip=("days",))
    emd_match = re.search(r"/EMD\s+Detail[\s\S]{0,220}?/Required\s*(Yes|No)", text, re.IGNORECASE)
    epbg_match = re.search(r"/ePBG\s+Detail[\s\S]{0,220}?/Required\s*(Yes|No)", text, re.IGNORECASE)
    emd_required = emd_match.group(1).casefold() == "yes" if emd_match else None
    epbg_required = epbg_match.group(1).casefold() == "yes" if epbg_match else None
    if emd_required is False:
        req["emd_lakh"] = 0
    title = row["title"]
    tender = {
        "id": "gem-" + row["id"], "bid": row["bid"] or row["id"], "title": title,
        "buyer": row["buyer"], "portal": "GeM", "category": row["category"], "sector": row["sector"],
        "value_lakh": None, "emd_lakh": None if emd_required is False else req.get("emd_lakh"), "closes": row["end_date"],
        "emd_required": emd_required, "epbg_required": epbg_required,
        "pdf_opening_date": pdf_opening, "offer_validity": pdf_validity,
        "evaluation_description": pdf_evaluation or row["evaluation_type"],
        "pages": len(page_texts) if doc_response else None, "url": row["document_url"],
        "docs": [{"name": name, "pages": len(page_texts) if doc_response else None,
                  "text": "ok" if text else "unavailable"}],
        "snippet": f"Live GeM {row['bid_type'].lower()} · quantity {row['quantity'] or 'not listed'} · {row['status']}",
        "clauses": clauses, "_req": req, "_source": {name: text}, "_headings": {name: headings},
        "_owner_id": None,
    }
    TENDERS[tender["id"]] = tender
    return tender, text, row, bool(doc_response)


@app.get("/api/live-tenders")
def live_tenders(q: str = "", page: int = 1):
    return _fetch_gem_bids(q, page)


@app.get("/api/live-tenders/{bid_id}")
def live_tender_detail(bid_id: str):
    tender, document_text, row, document_available = _load_gem_tender(bid_id)
    return {"bid": row, "tender": tender_summary(tender), "clauses": public(tender["clauses"]),
            "engine": engine_of(tender), "document_text": document_text,
            "document_available": document_available,
            "document_note": "Full GeM bid PDF text is shown when the public document is accessible."}


@app.get("/api/follows")
def get_follows(request: Request):
    user_id = _user_id(request)
    return FOLLOWS.get(user_id, {"bids": [], "organizations": []})


@app.put("/api/follows")
def put_follows(body: dict, request: Request):
    user_id = _user_id(request)
    bids = list(dict.fromkeys(str(x) for x in body.get("bids", []) if re.fullmatch(r"\d{5,20}", str(x))))[:5000]
    organizations = list(dict.fromkeys(str(x).strip()[:240] for x in body.get("organizations", [])
                                        if str(x).strip()))[:1000]
    previous = FOLLOWS.get(user_id)
    FOLLOWS[user_id] = {"bids": bids, "organizations": organizations}
    if not _save():
        if previous is None:
            FOLLOWS.pop(user_id, None)
        else:
            FOLLOWS[user_id] = previous
        raise HTTPException(503, "Saved bids and followed organisations could not be persisted")
    return FOLLOWS[user_id]


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
    if user_id.startswith("demo:"):
        raise HTTPException(403, "Local demo supplier profiles are read-only")
    account = _account(user_id)
    base = _profile(pid, user_id)
    body = copy.deepcopy(body)
    body["id"] = user_id
    body["sectors"] = account["sectors"]
    for k, default in (("name", "Unnamed supplier"), ("role", "reseller"), ("turnover", []), ("orders", []),
                       ("oem_letters", []), ("documents", []), ("emd_funds_lakh", 0), ("udyam_mse", False), ("dpiit", False)):
        body.setdefault(k, base.get(k, default))
    # Identity and submitted evidence are server-controlled; edits to readiness
    # data must never erase or upgrade the business verification record.
    for key in ("identity", "integrity_documents", "profile_complete", "integrity_status", "entity_type", "gstin", "city"):
        if key in base:
            body[key] = copy.deepcopy(base[key])
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
    body["name"] = str((base.get("identity") or {}).get("legal_name") or base.get("name")
                       or account.get("company_name") or account.get("name"))
    previous = copy.deepcopy(account)
    account["company_name"] = body["name"]
    account["profile"] = body
    if not _save():
        ACCOUNTS[user_id] = previous
        raise HTTPException(503, "Account storage is unavailable. Configure persistent storage before continuing.")
    return public(body)


@app.post("/api/assess")
def post_assess(body: dict, request: Request):
    user_id = _user_id(request)
    profile = _supplier_profile(user_id)
    tid = body.get("tender_id")
    if tid not in TENDERS and isinstance(body.get("tender"), dict):
        # Uploads and live bids may have landed on a different serverless instance.
        if str(tid).startswith("u-"):
            TENDERS[tid] = tender_from_upload(body["tender"], tid, user_id)
    if str(tid or "").startswith("gem-") and tid not in TENDERS:
        _load_gem_tender(str(tid)[4:])
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
    clauses, req = {}, {"turnover_lakh": 0, "emd_lakh": 0, "orders_required": 1, "order_min_lakh": 0,
                        "oem_brands": [], "emd_exempt_roles": [],
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

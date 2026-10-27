"""Rules engine + evidence validator. Run from the repo root: python -m pytest backend/tests -q"""

import copy
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import data, main, pipeline, rules


def tender(tid):
    return copy.deepcopy(next(t for t in data.TENDERS if t["id"] == tid))


def profile(pid):
    return copy.deepcopy(next(p for p in data.PROFILES if p["id"] == pid))


def run(t, p):
    validations, _ = pipeline.run_validation(t)
    r = rules.evaluate(t, p, validations)
    return r, {c["key"]: c for c in r["criteria"]}


# ---------------------------------------------------------------- verdicts

def test_clean_eligible():
    r, c = run(tender("t1"), profile("p-northstar"))
    assert r["verdict"] == "eligible"
    assert r["coverage"] == 4
    assert all(x["status"] == "met" for x in c.values())


def test_relaxed_startup_and_mse_service_provider():
    r, c = run(tender("t1"), profile("p-brightloop"))
    assert r["verdict"] == "eligible_relaxation"
    assert c["turnover"]["status"] == "relaxed"
    assert c["experience"]["status"] == "relaxed"
    assert c["emd"]["status"] == "relaxed"


def test_not_met_on_turnover():
    r, c = run(tender("t5"), profile("p-northstar"))
    assert c["turnover"]["status"] == "not_met"
    assert r["verdict"] == "not_eligible"
    assert any("Rs" in s for s in c["experience"]["next_steps"])


def test_unresolved_image_only_annexure():
    r, c = run(tender("t4"), profile("p-northstar"))
    assert c["oem"]["status"] == "unresolved"
    assert c["oem"]["validation"]["quote_found"] is False
    assert r["verdict"] == "manual_review"
    assert r["coverage"] == 3
    assert r["unresolved"]


def test_trader_excluded_from_mse_emd_exemption():
    r, c = run(tender("t2"), profile("p-northstar"))
    assert c["emd"]["status"] == "not_met"
    assert "reseller" in c["emd"]["rule_result"]
    assert r["verdict"] == "not_eligible"
    # same tender, same MSE status, but a manufacturer gets the exemption
    p = profile("p-northstar")
    p["role"] = "manufacturer"
    _, c2 = run(tender("t2"), p)
    assert c2["emd"]["status"] == "relaxed"


def test_exemption_requires_proof():
    p = profile("p-kaveri")
    p["documents"] = [d for d in p["documents"] if d["name"] != "Udyam certificate"]
    p["emd_funds_lakh"] = 0
    _, c = run(tender("t6"), p)
    assert c["emd"]["status"] == "not_met"


def test_tender_denies_relaxation():
    t = tender("t3")
    p = profile("p-brightloop")  # DPIIT startup, below turnover
    _, c = run(t, p)
    assert c["turnover"]["status"] == "not_met"
    assert "NOT available" in c["turnover"]["rule_result"]
    # without the denial the same tender would relax it
    t["_req"]["relaxation_denied"] = False
    t["_req"]["startup_relax"] = True
    _, c2 = run(t, p)
    assert c2["turnover"]["status"] == "relaxed"


# ---------------------------------------------------------------- evidence validator

def test_quote_not_found_becomes_unresolved():
    t = tender("t1")
    t["clauses"]["turnover"]["quote"] = "average annual turnover shall be at least Rs. 40 Lakh in each of the last five years"
    r, c = run(t, profile("p-northstar"))
    assert c["turnover"]["validation"]["quote_found"] is False
    assert c["turnover"]["status"] == "unresolved"  # never falls back to the model's claim
    assert r["verdict"] == "manual_review"
    assert r["coverage"] == 3


def test_number_mismatch_becomes_unresolved():
    t = tender("t1")
    t["_req"]["turnover_lakh"] = 30  # extractor's structured value disagrees with the quoted Rs. 40 Lakh
    _, c = run(t, profile("p-northstar"))
    assert c["turnover"]["validation"] == {"quote_found": True, "number_match": False, "heading_match": True}
    assert c["turnover"]["status"] == "unresolved"


def test_heading_mismatch_becomes_unresolved():
    t = tender("t1")
    t["clauses"]["emd"]["heading"] = "Cl. 99 Invented Heading"
    _, c = run(t, profile("p-northstar"))
    assert c["emd"]["validation"]["heading_match"] is False
    assert c["emd"]["status"] == "unresolved"


@pytest.mark.parametrize("text,lakh", [
    ("Rs. 50 Lakh", 50), ("Rs. 1,50,000", 1.5), ("Rs. 80,000", 0.8), ("INR 2 Crore", 200), ("no amount", None),
])
def test_parse_amount(text, lakh):
    assert pipeline.parse_amount_lakh(text) == lakh


# ---------------------------------------------------------------- API

client = TestClient(main.app)


def test_routes_shape():
    assert client.get("/api/health").json()["rule_version"] == rules.RULE_VERSION
    a = client.post("/api/assess", json={"tender_id": "t1", "profile_id": "p-northstar"}).json()
    assert [s["key"] for s in a["stages"]] == ["search", "fetch", "extract", "validate", "evaluate", "report"]
    assert a["verdict"] == "eligible" and a["id"].startswith("a-")
    assert client.get(f"/api/assessments/{a['id']}").json()["id"] == a["id"]
    assert len(client.get("/api/assessments").json()) >= 8
    rows = client.get("/api/matrix?tender_id=t1").json()["rows"]
    assert {r["profile_id"] for r in rows} >= {"p-northstar", "p-kaveri", "p-brightloop", "p-meridian"}
    assert "_gap" not in json.dumps(a)


def test_upload_sample_pdf():
    pdf = Path(__file__).resolve().parent.parent / "samples" / "sample-gem-bid.pdf"
    t = client.post("/api/upload", files={"file": ("sample-gem-bid.pdf", pdf.read_bytes(), "application/pdf")}).json()
    assert t["id"].startswith("u-")
    assert all(t["clauses"][k] for k in ("turnover", "experience", "oem", "emd"))
    a = client.post("/api/assess", json={"tender_id": t["id"], "profile_id": "p-northstar"}).json()
    assert a["coverage"] == 4 and a["verdict"] == "eligible"


def test_live_search_shape(monkeypatch):
    sample = {"query": "gem laptops", "total_results": 1, "results": [
        {"position": 1, "site_name": "GeM", "snippet": "Bid for laptops", "title": "Laptop bid", "url": "https://gem.gov.in/x"}]}
    monkeypatch.setattr(main.shutil, "which", lambda name: "tinyfish")
    seen = {}

    def fake_run(*a, **k):
        seen["env"] = k.get("env")
        return subprocess.CompletedProcess(a[0], 0, stdout=json.dumps(sample) + "\nAssertion failed: x", stderr="")
    monkeypatch.setenv("TINYFISH_API_KEY", "expired")
    monkeypatch.setattr(main.subprocess, "run", fake_run)
    r = client.get("/api/live-search?q=gem laptops").json()
    assert "TINYFISH_API_KEY" not in seen["env"]
    assert r["ok"] is True and r["source"] == "tinyfish-search" and r["query"] == "gem laptops"
    assert r["results"][0]["url"] == "https://gem.gov.in/x" and isinstance(r["ms"], int)


def test_live_search_never_500(monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda name: "tinyfish")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("tinyfish", 25)
    monkeypatch.setattr(main.subprocess, "run", boom)
    r = client.get("/api/live-search?q=x")
    assert r.status_code == 200 and r.json()["ok"] is False


def test_live_search_http_fallback(monkeypatch):
    import io
    import urllib.request
    sample = {"query": "ups tender", "results": [{"position": 1, "title": "UPS bid", "url": "https://gem.gov.in/u", "snippet": "s"}]}
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen["url"], seen["key"] = req.full_url, req.get_header("X-api-key")
        return Resp(json.dumps(sample).encode())
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    monkeypatch.setenv("TINYFISH_API_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    r = client.get("/api/live-search?q=ups tender").json()
    assert r["ok"] is True and r["source"] == "tinyfish-search" and r["results"][0]["url"] == "https://gem.gov.in/u"
    assert seen["url"].startswith(main.TINYFISH_SEARCH_URL) and seen["key"] == "test-key"
    assert "test-key" not in json.dumps(r)


def test_live_search_no_cli_no_key(monkeypatch):
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    r = client.get("/api/live-search?q=x")
    assert r.status_code == 200 and r.json()["ok"] is False


def test_profile_put_survives_read_only_store(monkeypatch):
    class ReadOnly:
        def write_text(self, *a, **k):
            raise PermissionError("read-only file system")
    monkeypatch.setattr(main, "STORE", ReadOnly())
    p = client.get("/api/profiles/p-northstar").json()
    p["emd_funds_lakh"] = 2.0
    assert client.put("/api/profiles/p-northstar", json=p).json()["emd_funds_lakh"] == 2.0
    a = client.post("/api/assess", json={"tender_id": "t2", "profile_id": "p-northstar"}).json()
    assert {"stages", "criteria", "tender", "missing_docs", "scope_notice"} <= set(a)  # full Assessment
    p["emd_funds_lakh"] = 1.0
    client.put("/api/profiles/p-northstar", json=p)


def test_vercel_entry_imports():
    from api.index import app
    assert app is main.app

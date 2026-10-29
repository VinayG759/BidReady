"""Tests on real GeM bid documents from backend/corpus. No network and no paid API calls: Claude is either off
(use_ai=False) or replaced by a fake, so these run anywhere and give the same result every time."""

import copy
from pathlib import Path

import pytest

from backend import ai, data, extract, gem, pipeline, rules

CORPUS = Path(__file__).resolve().parent.parent / "corpus"


def pdf(doc_id):
    return (CORPUS / f"{doc_id}.pdf").read_bytes()


def tender(doc_id):
    t, _ = extract.build_tender(pdf(doc_id), f"https://bidplus.gem.gov.in/showbidDocument/{doc_id}",
                                tid=f"g-{doc_id}", use_ai=False)
    return t


def profile(pid="p-northstar", **changes):
    p = copy.deepcopy(next(p for p in data.PROFILES if p["id"] == pid))
    p.update(changes)
    return p


def run(t, p):
    validations, _, _ = pipeline.run_validation(t)
    r = rules.evaluate(t, p, validations)
    return r, {c["key"]: c for c in r["criteria"]}


# ---------------------------------------------------------------- GeM template parser

def test_parser_reads_network_switch_bid():
    g = gem.parse_gem(gem.read_pdf(pdf("9961835"))["pages"])
    assert g["bid_number"]["value"] == "GEM/2026/B/8096659"
    assert g["turnover_lakh"]["value"] == 60
    assert g["experience_years"]["value"] == 3
    assert g["emd_amount"]["value"] == 364542
    assert g["mse_relax_experience"]["value"]["granted"] is False
    assert g["emd_exemption_rule"] and "Traders are excluded" in g["emd_exemption_rule"]["quote"]
    assert gem.oem_authorisation_required(g)


def test_parser_reads_newer_turnover_label():
    g = gem.parse_gem(gem.read_pdf(pdf("9918572"))["pages"])
    assert g["turnover_lakh"]["value"] == 11.85
    assert "For the last 3 Financial Years" in g["turnover_lakh"]["quote"]


def test_every_parser_quote_is_on_its_page():
    for doc_id in ("9961835", "9918572", "10017120", "10093741"):
        pages = gem.read_pdf(pdf(doc_id))["pages"]
        for f in gem.parse_gem(pages).values():
            if f:
                assert pipeline.normalise(f["quote"]) in pipeline.normalise(pages[f["page"] - 1]), (doc_id, f["label"])


def test_amount_and_years_parsing():
    assert pipeline.parse_amount_lakh("Minimum Average Annual Turnover 60 Lakh (s)") == 60
    assert pipeline.parse_amount_lakh("2 Crore") == 200
    assert pipeline.parse_rupees("EMD Amount 364542") == 364542
    assert pipeline.parse_rupees("submit EMD of Rs.3,64,542/- in favour of") == 364542
    assert pipeline.parse_years("Experience Required 3 Year (s)") == 3
    assert rules.fy_of("2025-08-14") == "FY26" and rules.fy_of("2025-02-07") == "FY25"


# ---------------------------------------------------------------- rules on real bids

def test_reseller_mse_fails_switch_bid_on_turnover_and_emd():
    r, c = run(tender("9961835"), profile())
    assert c["turnover"]["status"] == "not_met"           # avg 44.7 L < 60 L, relaxation "No"
    assert c["emd"]["status"] == "not_met"
    assert "traders are excluded" in c["emd"]["rule_result"].lower()
    assert r["verdict"] == "not_eligible"


def test_mse_manufacturer_gets_emd_exemption_when_bid_grants_it():
    t = tender("9918572")                                 # desktops, EMD 72,000, exemption clause present
    _, c = run(t, profile("p-kaveri"))
    assert c["emd"]["status"] in ("met", "relaxed")
    poor = profile("p-kaveri", emd_funds_lakh=0.1)
    _, c = run(t, poor)
    assert c["emd"]["status"] == "relaxed"


def test_same_company_as_reseller_is_refused_the_exemption():
    t = tender("9918572")
    _, c = run(t, profile("p-kaveri", role="reseller", emd_funds_lakh=0.1))
    assert c["emd"]["status"] == "not_met"


def test_exemption_needs_proof():
    p = profile("p-kaveri", emd_funds_lakh=0.1)
    p["documents"] = [d for d in p["documents"] if "Udyam" not in d["name"]]
    _, c = run(tender("9918572"), p)
    assert c["emd"]["status"] == "not_met"
    assert any(not d["ok"] and "Udyam" in d["name"] for d in c["emd"]["docs"])


def test_no_turnover_threshold_is_not_required():
    t = tender("10042160")                                # laptop bid without a turnover field
    assert t["_req"]["turnover_lakh"] is None
    _, c = run(t, profile())
    assert c["turnover"]["status"] == "na"


def test_emd_not_required_is_met():
    _, c = run(tender("10042160"), profile())
    assert c["emd"]["status"] == "met"
    assert "no emd required" in c["emd"]["requirement"].lower()


def test_experience_counts_financial_years_of_similar_supply():
    t = tender("10042160")                                # laptops, 3 years
    _, c = run(t, profile())                              # Northstar: laptops in FY24, FY25, FY26
    assert c["experience"]["status"] == "met"
    _, c = run(t, profile("p-brightloop", udyam_mse=False, dpiit=False))
    assert c["experience"]["status"] == "not_met"


def test_relaxation_granted_by_bid_covers_experience_with_proof():
    t = tender("10017120")                                # MSE + startup relaxation "Yes Complete"
    assert t["_req"]["mse_relax_experience"]["granted"]
    _, c = run(t, profile("p-brightloop"))
    assert c["experience"]["status"] == "relaxed"


def test_manufacturer_authorises_itself_for_oem():
    _, c = run(tender("9918572"), profile("p-kaveri"))
    assert c["oem"]["status"] == "met"


# ---------------------------------------------------------------- the evidence gate

def test_tampered_quote_makes_criterion_unresolved():
    t = tender("9961835")
    t["clauses"]["turnover"] = dict(t["clauses"]["turnover"], quote="Minimum turnover of the bidder 5 Lakh")
    r, c = run(t, profile("p-meridian"))
    assert c["turnover"]["status"] == "unresolved"
    assert c["turnover"]["validation"]["quote_found"] is False


def test_number_mismatch_makes_criterion_unresolved():
    t = tender("9961835")
    t["_req"]["turnover_lakh"] = 50                       # rules would pass Meridian; quote says 60
    _, c = run(t, profile("p-meridian"))
    assert c["turnover"]["status"] == "unresolved"
    assert c["turnover"]["validation"]["number_match"] is False


def test_ai_quotes_not_in_document_are_rejected(monkeypatch):
    fake = {"clauses": [
        {"criterion": "experience", "kind": "requirement", "heading": "ATC 9", "page": 6, "quote":
         "The bidder must have executed five similar orders worth Rs 2 crore each", "turnover_lakh": None,
         "experience_years": 5, "emd_rupees": None, "summary": "invented"},
    ], "model": "fake", "ms": 1}
    monkeypatch.setattr(ai, "extract", lambda pages, **kw: fake)
    t, log = extract.build_tender(pdf("10042160"), "u", tid="g-x")
    assert log["ai"]["rejected"] == 1 and log["ai"]["verified"] == 0
    assert t["_req"]["experience_years"] == 3             # the parser's value stands; the fake 5 is ignored


def test_ai_verbatim_quote_is_kept_and_page_corrected(monkeypatch):
    pages = gem.read_pdf(pdf("9961835"))["pages"]
    real = gem.parse_gem(pages)["emd_exemption_rule"]["quote"]
    fake = {"clauses": [{"criterion": "emd", "kind": "relaxation_condition", "heading": "", "page": 1, "quote": real,
                         "turnover_lakh": None, "experience_years": None, "emd_rupees": None, "summary": "x"}],
            "model": "fake", "ms": 1}
    monkeypatch.setattr(ai, "extract", lambda pages, **kw: fake)
    t, log = extract.build_tender(pdf("9961835"), "u", tid="g-y")
    assert log["ai"]["verified"] == 1


def test_ai_without_key_or_cache_does_not_raise(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = ai.extract(["[nothing cached] some unique text 8a7f6e"], use_cache=False)
    assert out["clauses"] == [] and out["error"]


# ---------------------------------------------------------------- API

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from backend import main
    main._save = lambda: None
    return TestClient(main.app), main


def test_api_health_and_tenders(client):
    c, main = client
    h = c.get("/api/health").json()
    assert h["ok"] and h["tenders"] >= 20
    ts = c.get("/api/tenders").json()
    assert ts and all(t["bid"].startswith("GEM/") for t in ts)
    assert all("_pages" not in t for t in ts)


def test_api_assess_shape(client):
    c, main = client
    tid = next(t["id"] for t in c.get("/api/tenders").json())
    a = c.post("/api/assess", json={"tender_id": tid, "profile_id": "p-northstar"}).json()
    assert a["verdict"] in ("eligible", "eligible_relaxation", "not_eligible", "manual_review")
    assert [s["key"] for s in a["stages"]] == ["search", "fetch", "extract", "validate", "evaluate", "report"]
    assert len(a["criteria"]) == 4 and 0 <= a["coverage"] <= 4


def test_put_profile_cannot_upgrade_evidence(client):
    c, main = client
    saved = copy.deepcopy(main.PROFILES["p-northstar"])
    try:
        body = copy.deepcopy(saved)
        body["turnover"][0]["value_lakh"] = 999
        body["turnover"][0]["evidence"] = "verified"
        out = c.put("/api/profiles/p-northstar", json=body).json()
        assert out["turnover"][0]["evidence"] == "declared"
        assert out["turnover"][1]["evidence"] == saved["turnover"][1]["evidence"]
    finally:
        main.PROFILES["p-northstar"] = saved

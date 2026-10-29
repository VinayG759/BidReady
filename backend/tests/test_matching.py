"""Tenders for you (backend/matching.py). GeM search and TinyFish Search are replaced by fakes and the cache points at
a temp folder, so these tests make no network calls and never touch corpus/matches/."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import data, matching, sources

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=matching.IST)
NORTHSTAR = next(p for p in data.PROFILES if p["id"] == "p-northstar")


def bid(doc, items, end="2026-11-20T15:00:00Z", number=None):
    return {"doc_id": str(doc), "bid": number or f"GEM/2026/B/{doc}", "items": items, "ministry": "Ministry of Education",
            "department": "Department of Higher Education", "quantity": 10, "start": "2026-10-20T10:00:00Z",
            "end": end, "url": sources.gem_document_url(doc)}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(matching, "CACHE_DIR", tmp_path / "matches")
    monkeypatch.setattr(matching, "_cache", {})
    monkeypatch.setattr(matching, "_library_ids", lambda: {"g-111"})

    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(matching, "datetime", FixedNow)


def fake_gem(monkeypatch, by_query, calls=None, fail=()):
    def search(q, page=1, **kw):
        if calls is not None:
            calls.append((q, page))
        if q in fail:
            raise sources.SourceError("GeM search failed: timed out")
        bids = by_query.get((q, page), by_query.get(q, []) if page == 1 else [])
        return {"total": len(bids), "bids": bids, "ms": 7}
    monkeypatch.setattr(sources, "search_gem_bids", search)


def fake_web(monkeypatch, results=None, calls=None, error=None):
    def search(q):
        if calls is not None:
            calls.append(q)
        if error:
            raise sources.SourceError(error)
        return {"results": results or [], "ms": 11}
    monkeypatch.setattr(sources, "tinyfish_search", search)


def test_northstar_terms():
    t = matching.profile_terms(NORTHSTAR)
    assert t["categories"] == ["Laptops", "Desktops", "Printers"]
    assert t["brands"] == ["HP", "Lenovo"]
    assert t["orders_by_category"] == {"Laptops": 3, "Desktops": 2, "Printers": 1}
    assert "laptop" in t["gem_queries"] and "desktop computer" in t["gem_queries"]
    assert any("printer" in q for q in t["gem_queries"])
    assert t["web_queries"][0] == '"GEM/2026/B" laptop tender'
    assert len(t["web_queries"]) <= matching.MAX_WEB_QUERIES


def test_whole_word_categories():
    assert matching.categories_in("Laptops and desktop computers") == ["Laptops", "Desktops"]
    assert matching.primary_category("Laptop - Notebook") == "Laptops"
    assert matching.primary_category("Technical specification booklet") is None   # "pc" inside a word


def test_gem_z_time_is_ist():
    assert matching.close_time("2026-11-20T15:00:00Z").isoformat() == "2026-11-20T15:00:00+05:30"


def test_merge_dedupe_skip_and_closed(monkeypatch):
    fake_gem(monkeypatch, {
        "laptop": [bid(111, "Laptop - Notebook"), bid(222, "Repair of Laptop"), bid(333, "Toner Cartridge for HP Printer"),
                   bid(444, "Laptop - Notebook", end="2026-10-29T11:00:00Z")],      # closed an hour ago, IST
        "desktop computer": [bid(111, "Laptop - Notebook"), bid(555, "Desktop Computers"), bid(666, "Office Chair")],
    })
    fake_web(monkeypatch)
    res = matching.find_matches(NORTHSTAR)
    docs = [m["doc_id"] for m in res["matches"]]
    assert sorted(docs) == ["111", "555"]
    m = next(m for m in res["matches"] if m["doc_id"] == "111")
    assert m["tender_id"] == "g-111" and m["in_library"] is True and m["sources"] == ["GeM"]
    assert m["closes"] == "2026-11-20" and m["days_left"] == 22
    assert "Laptops: matches 3 past orders" in m["reasons"]
    assert any("Lenovo" in r for r in m["reasons"])
    assert docs[0] == "111"   # laptops outscore desktops for Northstar


def test_off_category_bids_are_dropped(monkeypatch):
    fake_gem(monkeypatch, {"laptop": [bid(777, "CCTV Camera"), bid(111, "Laptop - Notebook")]})
    fake_web(monkeypatch)
    assert [m["doc_id"] for m in matching.find_matches(NORTHSTAR)["matches"]] == ["111"]


def test_brand_named_and_days_left(monkeypatch):
    fake_gem(monkeypatch, {"laptop": [bid(801, "Lenovo ThinkPad Laptop"), bid(802, "Laptop - Notebook", end="2026-11-01T18:00:00Z")]})
    fake_web(monkeypatch)
    ms = {m["doc_id"]: m for m in matching.find_matches(NORTHSTAR)["matches"]}
    assert "Lenovo named, you hold a Lenovo letter" in ms["801"]["reasons"]
    assert ms["802"]["days_left"] == 3 and "closes in 3 days, tight" in ms["802"]["reasons"]
    assert ms["801"]["score"] > ms["802"]["score"]


def test_page_two_only_when_page_one_is_thin(monkeypatch):
    calls = []
    many = [bid(1000 + i, "Laptop - Notebook") for i in range(20)]
    fake_gem(monkeypatch, {("laptop", 1): many[:10], ("laptop", 2): many[10:]}, calls=calls)
    monkeypatch.setattr(sources, "search_gem_bids",
                        (lambda f: lambda q, page=1, **kw: dict(f(q, page), total=20))(sources.search_gem_bids))
    fake_web(monkeypatch)
    res = matching.find_matches(NORTHSTAR)
    assert ("laptop", 2) in calls
    assert sum(1 for m in res["matches"] if m["category"] == "Laptops") == 20


def test_tinyfish_bid_numbers_resolve_on_gem(monkeypatch):
    gem_calls = []
    fake_gem(monkeypatch, {
        "laptop": [bid(111, "Laptop - Notebook")],
        "GEM/2026/B/8096659": [bid(9961835, "Laptop - Notebook", number="GEM/2026/B/8096659")],
        "GEM/2026/B/8000001": [],                                           # not ongoing on GeM: dropped
        "GEM/2026/B/111": [bid(111, "Laptop - Notebook")],
    }, calls=gem_calls)
    fake_web(monkeypatch, results=[
        {"title": "Laptop tender GEM / 2026 / B / 8096659", "snippet": "Bid end 20 Nov", "url": "https://tender247.com/x",
         "site_name": "tender247"},
        {"title": "Laptops", "snippet": "see GEM/2026/B/8000001", "url": "https://bidassist.com/gem-2026-b-111-laptop",
         "site_name": ""},
    ])
    res = matching.find_matches(NORTHSTAR)
    ms = {m["doc_id"]: m for m in res["matches"]}
    assert ms["9961835"]["sources"] == ["TinyFish"] and ms["9961835"]["tinyfish_sites"] == ["tender247"]
    assert ms["111"]["sources"] == ["GeM", "TinyFish"] and ms["111"]["tinyfish_sites"] == ["bidassist.com"]
    assert "found on GeM and on the web" in ms["111"]["reasons"]
    assert res["sources"]["tinyfish"]["bid_numbers"] == 3 and res["sources"]["tinyfish"]["bids_found"] == 2
    assert ("GEM/2026/B/8096659", 1) in gem_calls


def test_tinyfish_failing_leaves_gem_answering(monkeypatch):
    fake_gem(monkeypatch, {"laptop": [bid(111, "Laptop - Notebook")]})
    fake_web(monkeypatch, error="TinyFish Search HTTP 401")
    res = matching.find_matches(NORTHSTAR)
    assert res["sources"]["tinyfish"]["error"] == "TinyFish Search HTTP 401"
    assert "error" not in res["sources"]["gem"]
    assert [m["doc_id"] for m in res["matches"]] == ["111"]


def test_gem_failing_leaves_tinyfish_answering(monkeypatch):
    queries = matching.profile_terms(NORTHSTAR)["gem_queries"]
    fake_gem(monkeypatch, {"GEM/2026/B/8096659": [bid(9961835, "Laptop - Notebook", number="GEM/2026/B/8096659")]},
             fail=queries)
    fake_web(monkeypatch, results=[{"title": "GEM/2026/B/8096659 laptops", "snippet": "", "url": "https://t.in/a",
                                    "site_name": "t.in"}])
    res = matching.find_matches(NORTHSTAR)
    assert res["sources"]["gem"]["error"].startswith("GeM search failed")
    assert [m["doc_id"] for m in res["matches"]] == ["9961835"]


def test_cache_memory_disk_and_refresh(monkeypatch):
    calls = []
    fake_gem(monkeypatch, {"laptop": [bid(111, "Laptop - Notebook")]}, calls=calls)
    fake_web(monkeypatch)
    first = matching.find_matches(NORTHSTAR)
    n = len(calls)
    assert first["cached"] is False
    assert matching.find_matches(NORTHSTAR)["cached"] is True and len(calls) == n
    matching._cache.clear()                                         # a fresh instance reads the disk copy
    assert matching.find_matches(NORTHSTAR)["matches"] == first["matches"] and len(calls) == n
    assert matching.find_matches(NORTHSTAR, use_cache=False)["cached"] is False and len(calls) > n


def test_cache_expires(monkeypatch):
    fake_gem(monkeypatch, {"laptop": [bid(111, "Laptop - Notebook")]})
    fake_web(monkeypatch)
    matching.find_matches(NORTHSTAR)
    t = matching.time.time()
    monkeypatch.setattr(matching.time, "time", lambda: t + matching.CACHE_SECONDS + 1)
    assert matching.find_matches(NORTHSTAR)["cached"] is False


def test_cache_write_failure_is_swallowed(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(matching, "CACHE_DIR", blocker / "matches")
    fake_gem(monkeypatch, {"laptop": [bid(111, "Laptop - Notebook")]})
    fake_web(monkeypatch)
    assert matching.find_matches(NORTHSTAR)["matches"]


def test_route_shape_and_unknown_profile(monkeypatch):
    monkeypatch.setattr(matching, "_profile_by_id", lambda pid: NORTHSTAR if pid == "p-northstar" else None)
    fake_gem(monkeypatch, {"laptop": [bid(111, "Laptop - Notebook")]})
    fake_web(monkeypatch)
    app = FastAPI()
    app.include_router(matching.router)
    c = TestClient(app)
    r = c.get("/api/matches", params={"profile_id": "p-northstar", "refresh": 1}).json()
    assert set(r) == {"profile", "terms", "sources", "matches", "fetched_at", "cached"}
    assert r["profile"] == {"id": "p-northstar", "name": "Northstar IT Supplies", "role": "reseller"}
    assert set(r["sources"]["gem"]) >= {"queries", "results", "ms"}
    assert set(r["sources"]["tinyfish"]) >= {"queries", "results", "bids_found", "ms"}
    assert set(r["matches"][0]) >= {"doc_id", "tender_id", "bid", "title", "buyer", "closes", "days_left", "category",
                                    "score", "reasons", "sources", "tinyfish_sites", "in_library", "url"}
    assert c.get("/api/matches", params={"profile_id": "p-nobody"}).status_code == 404


def test_na_department_falls_back_to_ministry(monkeypatch):
    b = dict(bid(111, "Laptop - Notebook"), department="NA")
    fake_gem(monkeypatch, {"laptop": [b]})
    fake_web(monkeypatch)
    assert matching.find_matches(NORTHSTAR)["matches"][0]["buyer"] == "Ministry of Education"

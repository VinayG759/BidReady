"""Batch eligibility check for matched tenders: library bids only (already read), so no paid calls."""

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import main


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(main, "web_check", lambda tender, live: None)   # no TinyFish calls from tests
    return TestClient(main.app)


def _wait(client, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        v = client.get(f"/api/matches/check/{job_id}").json()
        if v["status"] == "done":
            return v
        time.sleep(0.2)
    raise AssertionError("batch did not finish")


def test_batch_on_library_bids_is_free_and_grouped(client):
    ids = [tid[2:] for tid in list(main.TENDERS)[:5]]
    start = client.post("/api/matches/check", json={"profile_id": "p-northstar", "doc_ids": ids}).json()
    assert start["total"] == 5 and start["new_reads"] == 0 and start["est_cost_usd"] == 0
    v = _wait(client, start["job_id"])
    assert v["done"] == 5 and all(r["status"] == "ok" for r in v["results"])
    grouped = sum(len(v["groups"][k]) for k in ("eligible", "eligible_relaxation", "manual_review", "not_eligible"))
    assert grouped == 5
    for r in v["results"]:
        assert client.get(f"/api/assessments/{r['assessment_id']}").status_code == 200


def test_batch_rejects_more_than_twenty(client):
    r = client.post("/api/matches/check", json={"profile_id": "p-northstar", "doc_ids": [str(10_000_000 + i) for i in range(21)]})
    assert r.status_code == 422


def test_batch_needs_at_least_one(client):
    assert client.post("/api/matches/check", json={"profile_id": "p-northstar", "doc_ids": []}).status_code == 422


def test_a_failing_bid_becomes_an_error_row(client, monkeypatch):
    real = main._ingest_doc
    def ingest(doc_id, *a, **k):
        if doc_id == "99999999":
            raise HTTPException(502, "Could not fetch the bid document: HTTP 404")
        return real(doc_id, *a, **k)
    monkeypatch.setattr(main, "_ingest_doc", ingest)
    lib = next(iter(main.TENDERS))[2:]
    start = client.post("/api/matches/check", json={"profile_id": "p-kaveri", "doc_ids": [lib, "99999999"]}).json()
    assert start["new_reads"] == 1 and start["est_cost_usd"] == 0.11
    v = _wait(client, start["job_id"])
    assert v["groups"]["errors"] == ["99999999"]
    assert next(r for r in v["results"] if r["doc_id"] == "99999999")["error"].startswith("Could not fetch")

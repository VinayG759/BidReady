"""Sliding-window limits (backend/ratelimit.py): time is moved with monkeypatch, no sleeping."""

import pytest
from fastapi import HTTPException

from backend import ratelimit


class Req:
    def __init__(self, xff=None, host="198.51.100.7"):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": host})() if host else None


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    ratelimit.reset()
    now = [1_000_000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    return now


def test_client_ip_prefers_first_forwarded_address():
    assert ratelimit.client_ip(Req(xff="203.0.113.5, 10.0.0.2")) == "203.0.113.5"
    assert ratelimit.client_ip(Req()) == "198.51.100.7"
    assert ratelimit.client_ip(Req(host=None)) == "unknown"


def test_window_slides(clock):
    for _ in range(3):
        assert ratelimit.allow("b", "ip", 3, window=60)
    assert not ratelimit.allow("b", "ip", 3, window=60)
    clock[0] += 61                                                    # the oldest requests leave the window
    assert ratelimit.allow("b", "ip", 3, window=60)


def test_buckets_and_clients_are_separate():
    assert ratelimit.allow("a", "ip1", 1)
    assert not ratelimit.allow("a", "ip1", 1)
    assert ratelimit.allow("b", "ip1", 1) and ratelimit.allow("a", "ip2", 1)


def test_enforce_raises_429_with_detail():
    ratelimit.enforce(Req(), "x", 1, "slow down")
    with pytest.raises(HTTPException) as e:
        ratelimit.enforce(Req(), "x", 1, "slow down")
    assert e.value.status_code == 429 and e.value.detail == "slow down"

"""Corrigendum monitor. The TinyFish HTTP layer (monitor._call) is replaced by a fake, so no real monitors are
created and nothing is billed. watches.json is redirected to a temp file."""

import pytest

from backend import monitor

BID = "GEM/2026/B/8096659"
TENDER = {"id": "g-9961835", "bid": BID, "title": "Core Switch and Access Switch", "buyer": "GGSIPU, Delhi"}


def result(pos, title, snippet="", url="https://example.org/x"):
    return {"position": pos, "site_name": "example.org", "title": title, "snippet": snippet, "url": url}


class FakeTinyFish:
    def __init__(self, baseline=None, rerun=None, fail=None):
        self.calls = []
        self.baseline = baseline or []
        self.rerun = rerun or []
        self.fail = fail or {}

    def __call__(self, method, path, body=None, timeout=60):
        self.calls.append((method, path, body))
        if (method, path) in self.fail:
            raise monitor.MonitorError(self.fail[(method, path)])
        if method == "POST" and path == "/v1/monitors":
            return {"monitor": {"id": "mon_1", "schedule_cron": body["schedule_cron"], "status": "active",
                                "created_at": "2026-10-29T10:00:00Z", "last_error": None},
                    "run": {"id": "run_0", "status_code": 200, "results": self.baseline,
                            "new_result_positions": [], "created_at": "2026-10-29T10:00:01Z"}}
        if method == "GET" and path == "/v1/monitors/mon_1":
            return {"id": "mon_1", "status": "active", "schedule_cron": "0 3 * * *", "last_error": None}
        if method == "POST" and path == "/v1/monitors/mon_1/runs":
            return {"run": {"id": "run_1", "status_code": 200, "results": self.rerun,
                            "new_result_positions": [1], "created_at": "2026-10-30T03:00:00Z"}}
        if method == "DELETE" and path == "/v1/monitors/mon_1":
            return {"deleted": True, "id": "mon_1"}
        raise monitor.MonitorError(f"unexpected {method} {path}")


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "WATCHES", tmp_path / "watches.json")

    def install(**kw):
        f = FakeTinyFish(**kw)
        monkeypatch.setattr(monitor, "_call", f)
        return f
    return install


def test_detects_only_this_bid_with_a_change_word():
    rs = [result(1, f"Corrigendum to {BID}"),                         # bid + change word
          result(2, "GEM/2026/B/8096659 laptop tender"),              # bid, no change word
          result(3, "Bid end date extended", "for GEM/2026/B/1111111"),  # other bid
          result(4, "Date extension", "GEM-2026-B-8096659 extended to 30 Nov")]  # separators differ
    assert monitor.detect_changes(rs, BID) == [1, 4]


def test_menu_boilerplate_is_not_a_change():
    # real TinyFish results for this bid, 29 Oct 2026
    menu = result(2, "Core Switch, Distribution Switch ...",
                  f"Tender {BID} by Higher Education Department Delhi: Core Switch ... "
                  "Corrigendum (if any) � Pre-Bid Meeting Minutes � Amendments � FAQs � Contact ...")
    real = result(3, "Core Switch, Distribution Switch, Access Switch and 11 more ...",
                  f"... {BID} on GeM ... Corrigendum. 2 corrigenda · last on 23 Oct 2026. "
                  "Deadline moved26 Oct→23 Nov, 12:00 pmextended once.")
    assert monitor.detect_changes([menu, real], BID) == [3]


def test_create_sends_a_daily_search_monitor_and_stores_baseline(fake):
    f = fake(baseline=[result(1, "Bid listing", BID)])
    w = monitor.create_watch(TENDER)
    assert w["monitor_id"] == "mon_1" and w["bid"] == BID and w["tender_id"] == "g-9961835"
    assert w["change_detected"] is False and w["last_run"]["result_count"] == 1
    method, path, body = f.calls[0]
    assert (method, path) == ("POST", "/v1/monitors")
    assert body["type"] == "search" and body["schedule_cron"] == "0 3 * * *"
    assert body["config"]["query"] == f'"{BID}" corrigendum OR extension OR cancelled'
    assert monitor.list_watches()["watches"][0]["monitor_id"] == "mon_1"


def test_watching_the_same_tender_twice_does_not_create_a_second_billed_monitor(fake):
    f = fake()
    monitor.create_watch(TENDER)
    again = monitor.create_watch(TENDER)
    assert again["already_watching"] is True
    assert [c for c in f.calls if c[:2] == ("POST", "/v1/monitors")] == [("POST", "/v1/monitors", f.calls[0][2])]


def test_run_now_flags_a_corrigendum(fake):
    fake(rerun=[result(1, f"Corrigendum-1 for {BID}", "bid end date extended")])
    monitor.create_watch(TENDER)
    w = monitor.run_watch("mon_1")
    assert w["change_detected"] is True and w["last_run"]["change_positions"] == [1]
    assert monitor.get_watch("mon_1")["change_detected"] is True


def test_get_keeps_stored_results_when_tinyfish_is_unreachable(fake):
    fake(baseline=[result(1, "x")], fail={("GET", "/v1/monitors/mon_1"): "could not reach TinyFish"})
    monitor.create_watch(TENDER)
    w = monitor.get_watch("mon_1")
    assert w["last_run"]["result_count"] == 1 and "live_error" in w


def test_cancel_deletes_monitor_and_forgets_watch(fake):
    f = fake()
    monitor.create_watch(TENDER)
    assert monitor.cancel_watch("mon_1") == {"deleted": True, "monitor_id": "mon_1"}
    assert ("DELETE", "/v1/monitors/mon_1", None) in f.calls
    assert monitor.list_watches()["watches"] == []


def test_errors_come_back_as_dicts_never_raised(fake):
    fake(fail={("POST", "/v1/monitors"): "TinyFish Monitors HTTP 402: insufficient balance"})
    assert monitor.create_watch(TENDER) == {"error": "TinyFish Monitors HTTP 402: insufficient balance"}
    assert "error" in monitor.get_watch("nope")
    assert "error" in monitor.run_watch("nope")
    assert "error" in monitor.cancel_watch("nope")
    assert "error" in monitor.create_watch({"id": "x"})


def test_read_only_disk_does_not_break_create(fake, monkeypatch, tmp_path):
    fake()
    monkeypatch.setattr(monitor, "WATCHES", tmp_path / "missing-dir" / "watches.json")
    assert monitor.create_watch(TENDER)["monitor_id"] == "mon_1"

"""Bid watch (backend/signals.py). TinyFish Search is replaced by fake payloads and the cache points at a temp
folder, so these tests make no network calls and never touch corpus/signals/."""

import pytest

from backend import signals, sources

BID = "GEM/2026/B/8096659"
TENDER = {"id": "g-1", "bid": BID, "closes": "2026-11-23", "title": "Desktop computers", "buyer": "Some ministry"}


def res(site, snippet, title="", url=None):
    return {"position": 1, "site_name": site, "title": title, "snippet": snippet,
            "url": url or f"https://{site}/tender/{site}-listing"}


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "CACHE_DIR", tmp_path / "signals")


def fake_search(monkeypatch, results_by_query=None, results=None, calls=None):
    def search(q):
        if calls is not None:
            calls.append(q)
        rs = results_by_query.get(q, []) if results_by_query is not None else results
        return {"results": rs, "ms": 5}
    monkeypatch.setattr(sources, "tinyfish_search", search)


def test_bid_number_matches_any_separator_but_not_a_longer_serial():
    assert signals.mentions_bid("Bid No: GEM / 2026 / B /8096659 desktops", BID)
    assert signals.mentions_bid("https://x.in/gem-2026-b-8096659-desktops", BID)
    assert signals.mentions_bid("GEM%2F2026%2FB%2F8096659", BID)
    assert not signals.mentions_bid("GEM/2026/B/80966591", BID)
    assert not signals.mentions_bid("GEM/2026/B/8096660 corrigendum", BID)


def test_other_bids_corrigendum_is_ignored():
    payloads = [{"results": [
        res("tender247.com", f"{BID} Desktop computers. Submission: 23 Nov 2026"),
        res("bidassist.com", "Corrigendum for GEM/2026/B/8101234: date extended to 30 Nov 2026"),
    ]}]
    out = signals.build(TENDER, payloads)
    assert [x["site"] for x in out["listed_on"]] == ["tender247.com"]
    assert out["signals"] == []
    assert "none mention" in out["summary"]


def test_corrigendum_and_extension_are_classified_and_quoted():
    snippet = f"Corrigendum issued for {BID}: bid end date extended."
    out = signals.build(TENDER, [{"results": [res("indiantenders.in", snippet)]}])
    kinds = {s["kind"] for s in out["signals"]}
    assert kinds == {"corrigendum", "extension"}
    assert all(s["quote"] == snippet and s["site"] == "indiantenders.in" for s in out["signals"])


def test_cancel_and_retender_words():
    out = signals.build(TENDER, [{"results": [res("justsocial.in", f"{BID} cancelled, will be re-tendered")]}])
    assert {s["kind"] for s in out["signals"]} == {"cancelled", "retender"}


def test_full_closing_date_that_differs_is_a_mismatch():
    for text in (f"{BID} Submission: 26 Nov 2026", f"{BID} closing date 26-11-2026", f"{BID} Bid End Date: 2026-11-26"):
        out = signals.build(TENDER, [{"results": [res("tender247.com", text)]}])
        mm = [s for s in out["signals"] if s["kind"] == "date_mismatch"]
        assert len(mm) == 1, text
        assert "26 Nov 2026" in mm[0]["detail"] and "later than" in mm[0]["detail"]


def test_matching_date_is_not_a_mismatch():
    out = signals.build(TENDER, [{"results": [res("tender247.com", f"{BID} Submission: 23 Nov 2026")]}])
    assert out["signals"] == []


def test_bare_day_is_never_guessed():
    out = signals.build(TENDER, [{"results": [res("tender247.com", f"{BID} Submission: 26 ... Desktop computers")]}])
    assert out["signals"] == []
    assert signals.closing_dates("Submission: 26 ...") == []


def test_dedupe_by_site_across_both_queries():
    r = res("tender247.com", f"{BID} corrigendum")
    out = signals.build(TENDER, [{"results": [r]}, {"results": [dict(r)]}])
    assert len(out["listed_on"]) == 1
    assert [s["kind"] for s in out["signals"]] == ["corrigendum"]


def test_cache_hit_skips_tinyfish(monkeypatch):
    calls = []
    fake_search(monkeypatch, results=[res("tender247.com", f"{BID} listed")], calls=calls)
    first = signals.web_signals(TENDER)
    assert first["cached"] is False and len(calls) == 2
    second = signals.web_signals(TENDER)
    assert second["cached"] is True and len(calls) == 2
    assert second["listed_on"] == first["listed_on"]
    assert "_ts" not in second


def test_live_false_uses_cache_only(monkeypatch):
    calls = []
    fake_search(monkeypatch, results=[], calls=calls)
    assert "error" in signals.web_signals(TENDER, live=False)
    assert calls == []


def test_expired_cache_is_refreshed(monkeypatch):
    calls = []
    fake_search(monkeypatch, results=[], calls=calls)
    signals.web_signals(TENDER)
    monkeypatch.setattr(signals, "TTL_SECONDS", -1)
    assert signals.web_signals(TENDER)["cached"] is False
    assert len(calls) == 4


def test_search_error_returns_error_not_raise(monkeypatch):
    def boom(q):
        raise sources.SourceError("TinyFish Search HTTP 500")
    monkeypatch.setattr(sources, "tinyfish_search", boom)
    assert signals.web_signals(TENDER) == {"error": "TinyFish Search HTTP 500"}


def test_unexpected_error_and_bad_input_never_raise(monkeypatch):
    def broken(q):
        raise KeyError("results")  # not a SourceError: the catch-all must still hold
    monkeypatch.setattr(sources, "tinyfish_search", broken)
    assert "error" in signals.web_signals(TENDER)
    monkeypatch.setattr(sources, "tinyfish_search", lambda q: None)  # malformed payload reads as no results
    assert signals.web_signals(TENDER, use_cache=False)["listed_on"] == []
    assert "error" in signals.web_signals({"bid": None})
    assert "error" in signals.web_signals(None)


def test_unwritable_cache_is_swallowed(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(signals, "CACHE_DIR", blocker / "signals")  # mkdir under a file fails with OSError
    fake_search(monkeypatch, results=[res("tender247.com", f"{BID} listed")])
    out = signals.web_signals(TENDER)
    assert "error" not in out and out["listed_on"]


def test_page_about_another_bid_is_not_a_listing():
    other = res("justsocial.cloud", f"Similar Tenders. {BID} Active. Core Switch", title="GEM/2026/B/8195856: Solid work software")
    out = signals.build(TENDER, [{"results": [other]}])
    assert out["listed_on"] == [] and out["signals"] == []


def test_site_furniture_is_not_a_corrigendum():
    text = f"Tender {BID} by Higher Education Department Delhi ... Corrigendum (if any) · Pre-Bid Meeting Minutes · Amendments"
    out = signals.build(TENDER, [{"results": [res("minaions.yugasa.org", text)]}])
    assert out["listed_on"] and out["signals"] == []


def test_faq_question_alone_is_not_a_corrigendum_but_its_yes_answer_is():
    q = f"{BID}, Est. cost 1.22 Cr. ... Has a corrigendum been issued for this tender?"
    assert signals.build(TENDER, [{"results": [res("www.tender247.com", q)]}])["signals"] == []
    yes = q + " Yes, a corrigendum has been issued."
    kinds = [s["kind"] for s in signals.build(TENDER, [{"results": [res("www.tender247.com", yes)]}])["signals"]]
    assert kinds == ["corrigendum"]


def test_glued_extended_is_still_an_extension():
    text = f"{BID} on GeM ... 2 corrigenda, last on 23 Oct 2026. Deadline moved 26 Oct to 23 Nov, 12:00 pmextended once."
    kinds = {s["kind"] for s in signals.build(TENDER, [{"results": [res("tenderlelo.com", text)]}])["signals"]}
    assert kinds == {"corrigendum", "extension"}

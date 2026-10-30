"""When GeM refuses every connection (as from Vercel's US region), matching answers fast from the saved snapshot."""

from backend import data, matching, sources


def refused(*a, **k):
    raise sources.SourceError("GeM search failed: <urlopen error [Errno 111] Connection refused>")


def test_gem_down_serves_labelled_snapshot_without_resolving(monkeypatch):
    monkeypatch.setattr(sources, "search_gem_bids", refused)
    monkeypatch.setattr(matching, "_web_query", lambda q: ({"results": [{"title": "GEM/2026/B/8096659 laptop", "url": "u"}], "ms": 1}, None))
    resolved = []
    monkeypatch.setattr(matching, "_resolve", lambda n: resolved.append(n) or (None, None))
    p = next(p for p in data.fresh_profiles() if p["id"] == "p-northstar")
    r = matching.find_matches(p, use_cache=False)
    assert resolved == []                                   # no doomed GeM lookups
    assert r["snapshot"]["fetched_at"] and "Connection refused" in r["snapshot"]["reason"]
    assert r["matches"] and r["sources"]["gem"]["error"]


def test_snapshot_never_shows_closed_bids(monkeypatch, tmp_path):
    import json
    (tmp_path / "p-x.json").write_text(json.dumps({"fetched_at": "2026-10-01T00:00:00+05:30", "matches": [
        {"doc_id": "1", "closes": "2020-01-01"}, {"doc_id": "2", "closes": "2099-01-01"}]}), encoding="utf-8")
    monkeypatch.setattr(matching, "SNAPSHOT_DIR", tmp_path)
    assert [m["doc_id"] for m in matching._read_snapshot("p-x")["matches"]] == ["2"]


def test_no_snapshot_returns_the_error(monkeypatch, tmp_path):
    monkeypatch.setattr(sources, "search_gem_bids", refused)
    monkeypatch.setattr(matching, "_web_query", lambda q: (None, "TinyFish down"))
    monkeypatch.setattr(matching, "SNAPSHOT_DIR", tmp_path)
    p = next(p for p in data.fresh_profiles() if p["id"] == "p-kaveri")
    r = matching.find_matches(p, use_cache=False)
    assert "snapshot" not in r and r["sources"]["gem"]["error"] and r["matches"] == []

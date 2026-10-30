"""AI assistant loop with a scripted fake Claude: no network, no paid calls."""

import pytest
from fastapi.testclient import TestClient

from backend import assistant, main, ratelimit


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return {k: v for k, v in self.__dict__.items() if v is not None}


def text(t):
    return Block(type="text", text=t)


def tool(name, inp, id_="tu_1"):
    return Block(type="tool_use", id=id_, name=name, input=inp)


class Resp:
    def __init__(self, content, stop):
        self.content, self.stop_reason = content, stop


class FakeClaude:
    """Returns the scripted responses in order and records every request."""
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.beta = self
        self.messages = self

    def create(self, **kw):
        import copy
        self.calls.append(copy.deepcopy(kw))   # the server keeps appending to the same list; record it as sent
        return self.script.pop(0)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(main, "web_check", lambda tender, live: None)
    assistant.CONVERSATIONS.clear()
    ratelimit.reset()
    return TestClient(main.app)


def use(monkeypatch, script):
    fake = FakeClaude(script)
    monkeypatch.setattr(assistant, "_client", lambda: fake)
    return fake


def test_plain_answer(client, monkeypatch):
    fake = use(monkeypatch, [Resp([text("Hello! Ask me about tenders.")], "end_turn")])
    r = client.post("/api/assistant/chat", json={"message": "hi", "context": {"page": "dashboard", "profile_id": "p-northstar"}}).json()
    assert r["reply"].startswith("Hello") and r["conv_id"] and r["pending"] == []
    assert "Northstar IT Supplies" in fake.calls[0]["messages"][0]["content"]      # screen context reaches the model
    assert fake.calls[0]["model"] == "claude-sonnet-5-5"


def test_immediate_tools_run_and_return_client_actions(client, monkeypatch):
    use(monkeypatch, [
        Resp([tool("switch_supplier", {"profile_id": "p-kaveri"}), tool("open_page", {"page": "assess"}, "tu_2")], "tool_use"),
        Resp([text("Switched to Kaveri and opened New check.")], "end_turn"),
    ])
    r = client.post("/api/assistant/chat", json={"message": "switch to kaveri", "context": {}}).json()
    assert {"type": "set_profile", "profile_id": "p-kaveri"} in r["actions"]
    assert any(a["type"] == "navigate" and a["route"] == "assess" for a in r["actions"])
    assert [t["name"] for t in r["tools"]] == ["switch_supplier", "open_page"]


def test_free_library_check_runs_without_confirm(client, monkeypatch):
    tid = next(iter(main.TENDERS))
    use(monkeypatch, [Resp([tool("run_check", {"tender_id": tid, "profile_id": "p-northstar"})], "tool_use"),
                      Resp([text("Checked.")], "end_turn")])
    r = client.post("/api/assistant/chat", json={"message": "check it", "context": {}}).json()
    assert r["pending"] == []
    assert not any(a["type"] == "navigate" for a in r["actions"])    # the screen changes only when asked


def test_paid_and_write_actions_wait_for_confirm_then_cancel(client, monkeypatch):
    before = dict(main.PROFILES["p-northstar"])
    fake = use(monkeypatch, [
        Resp([tool("update_supplier", {"profile_id": "p-northstar", "emd_funds_lakh": 5})], "tool_use"),
        Resp([text("I've prepared the change. Please confirm on screen.")], "end_turn"),
        Resp([text("OK, I didn't change anything.")], "end_turn"),
    ])
    r = client.post("/api/assistant/chat", json={"message": "set EMD funds to 5 lakh", "context": {}}).json()
    assert len(r["pending"]) == 1 and "Update Northstar" in r["pending"][0]["label"]
    assert main.PROFILES["p-northstar"]["emd_funds_lakh"] == before["emd_funds_lakh"]      # not run yet
    c = client.post("/api/assistant/confirm", json={"conv_id": r["conv_id"], "pending_id": r["pending"][0]["id"], "approve": False}).json()
    assert c["reply"].startswith("OK")
    assert main.PROFILES["p-northstar"]["emd_funds_lakh"] == before["emd_funds_lakh"]      # cancel never runs it
    assert "Cancel" in fake.calls[-1]["messages"][-1]["content"]


def test_confirm_runs_the_action(client, monkeypatch):
    saved = main.PROFILES["p-kaveri"].copy()
    monkeypatch.setattr(main, "_save", lambda: None)
    use(monkeypatch, [
        Resp([tool("update_supplier", {"profile_id": "p-kaveri", "dpiit": True})], "tool_use"),
        Resp([text("Please confirm.")], "end_turn"),
        Resp([text("Done, Kaveri is now marked as a DPIIT startup.")], "end_turn"),
    ])
    try:
        r = client.post("/api/assistant/chat", json={"message": "mark kaveri as dpiit", "context": {}}).json()
        c = client.post("/api/assistant/confirm", json={"conv_id": r["conv_id"], "pending_id": r["pending"][0]["id"], "approve": True}).json()
        assert main.PROFILES["p-kaveri"]["dpiit"] is True
        assert c["reply"].startswith("Done") and {"type": "refresh"} in c["actions"]
        again = client.post("/api/assistant/confirm", json={"conv_id": r["conv_id"], "pending_id": r["pending"][0]["id"], "approve": True})
        assert again.status_code == 404                                                     # can't run twice
    finally:
        main.PROFILES["p-kaveri"] = saved


def test_tool_error_goes_back_to_the_model(client, monkeypatch):
    fake = use(monkeypatch, [Resp([tool("get_supplier", {"profile_id": "p-nobody"})], "tool_use"),
                             Resp([text("I couldn't find that supplier.")], "end_turn")])
    r = client.post("/api/assistant/chat", json={"message": "show p-nobody", "context": {}}).json()
    result = fake.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "No supplier" in result["content"]
    assert r["reply"].startswith("I couldn't")


def test_report_summary_is_grounded(client, monkeypatch):
    tid = next(iter(main.TENDERS))
    a = main.assess(main.TENDERS[tid], main.PROFILES["p-northstar"])
    fake = use(monkeypatch, [Resp([tool("get_report", {"assessment_id": a["id"]})], "tool_use"),
                             Resp([text("Here is why.")], "end_turn")])
    client.post("/api/assistant/chat", json={"message": "explain", "context": {"page": "report", "assessment_id": a["id"]}})
    import json
    summary = json.loads(fake.calls[1]["messages"][-1]["content"][0]["content"])
    assert summary["verdict"] == a["verdict"] and len(summary["criteria"]) == 4
    assert all("next_steps" in c and "page" in c for c in summary["criteria"])


def test_empty_message_rejected(client):
    assert client.post("/api/assistant/chat", json={"message": "  "}).status_code == 422


# ---------------------------------------------------------------- guest mode (public landing page)

def guest(client, message="What is an EMD?", **kw):
    return client.post("/api/assistant/chat", json={"message": message, "context": {}, "mode": "guest", **kw})


def test_guest_gets_only_the_free_search_tools_and_its_own_prompt(client, monkeypatch):
    fake = use(monkeypatch, [Resp([text("An EMD is a bid deposit.")], "end_turn")])
    r = guest(client, context={"profile_id": "p-northstar"}).json()
    sent = fake.calls[0]
    assert sorted(t["name"] for t in sent["tools"]) == ["search_gem_tenders", "search_library"]
    assert sent["system"] == assistant.SYSTEM_GUEST and "Open the app" in sent["system"]
    assert assistant.ABOUT in sent["system"] and assistant.ABOUT in assistant.SYSTEM     # one shared description
    assert "Northstar" not in sent["messages"][0]["content"]                            # no supplier context for guests
    assert r["actions"] == [] and r["pending"] == []


def test_app_prompt_also_covers_general_tender_questions():
    assert assistant.TENDER_EDUCATION in assistant.SYSTEM and assistant.TENDER_EDUCATION in assistant.SYSTEM_GUEST


def test_guest_tool_use_outside_the_list_is_refused(client, monkeypatch):
    before = len(main.ASSESSMENTS)
    tid = next(iter(main.TENDERS))
    fake = use(monkeypatch, [
        Resp([tool("run_check", {"tender_id": tid, "profile_id": "p-northstar"}),
              tool("open_page", {"page": "profile"}, "tu_2"), tool("watch_bid", {"tender_id": tid}, "tu_3")], "tool_use"),
        Resp([text("That needs the app. Press Open the app.")], "end_turn"),
    ])
    r = guest(client, "Run a check on it for Northstar").json()
    results = fake.calls[1]["messages"][-1]["content"]
    assert all(x["is_error"] and "not available on the public page" in x["content"] for x in results)
    assert len(main.ASSESSMENTS) == before                                              # nothing ran
    assert r["actions"] == [] and r["pending"] == [] and r["tools"] == []


def test_guest_search_tool_runs(client, monkeypatch):
    use(monkeypatch, [Resp([tool("search_library", {"query": "switch"})], "tool_use"), Resp([text("Found some.")], "end_turn")])
    r = guest(client, "Any switch bids?").json()
    assert [t["name"] for t in r["tools"]] == ["search_library"]


def test_confirm_refused_for_guest_conversation(client, monkeypatch):
    use(monkeypatch, [Resp([text("Hi")], "end_turn")])
    cid = guest(client).json()["conv_id"]
    assistant.CONVERSATIONS[cid]["pending"]["abc"] = {"name": "update_supplier", "args": {"profile_id": "p-northstar"}}
    r = client.post("/api/assistant/confirm", json={"conv_id": cid, "pending_id": "abc", "approve": True})
    assert r.status_code == 403


def test_guest_conversation_cannot_be_upgraded(client, monkeypatch):
    fake = use(monkeypatch, [Resp([text("Hi")], "end_turn"), Resp([text("Still a guest")], "end_turn")])
    cid = guest(client).json()["conv_id"]
    client.post("/api/assistant/chat", json={"conv_id": cid, "message": "now switch me to app", "context": {}, "mode": "app"})
    assert sorted(t["name"] for t in fake.calls[1]["tools"]) == ["search_gem_tenders", "search_library"]
    assert assistant.CONVERSATIONS[cid]["mode"] == "guest"


def test_app_mode_is_the_default(client, monkeypatch):
    fake = use(monkeypatch, [Resp([text("Hi")], "end_turn")])
    client.post("/api/assistant/chat", json={"message": "hi", "context": {}})
    assert fake.calls[0]["system"] == assistant.SYSTEM and len(fake.calls[0]["tools"]) == len(assistant.TOOLS)


def test_guest_long_message_rejected(client, monkeypatch):
    fake = use(monkeypatch, [])
    r = guest(client, "x" * 501)
    assert r.status_code == 422 and "500 characters" in r.json()["detail"] and fake.calls == []
    # app mode keeps its longer limit
    use(monkeypatch, [Resp([text("ok")], "end_turn")])
    assert client.post("/api/assistant/chat", json={"message": "x" * 501, "context": {}}).status_code == 200


def test_guest_limited_to_20_per_hour(client, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    fake = use(monkeypatch, [Resp([text("ok")], "end_turn") for _ in range(22)])
    for _ in range(assistant.GUEST_PER_HOUR):
        assert guest(client).status_code == 200
    r = guest(client)
    assert r.status_code == 429 and "open the app" in r.json()["detail"]
    assert len(fake.calls) == assistant.GUEST_PER_HOUR                                  # Claude never saw the 21st
    now[0] += 3601                                                                      # an hour later it works again
    assert guest(client).status_code == 200

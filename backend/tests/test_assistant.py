"""AI assistant loop with a scripted fake Claude: no network, no paid calls."""

import pytest
from fastapi.testclient import TestClient

from backend import assistant, main


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

"""Voice (backend/voice.py). Sarvam's HTTP layer is replaced by a fake, so these tests make no network calls and
never need a real key."""

import base64
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import voice

MP3 = b"ID3fake-mp3-bytes"


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(voice.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "test-key-not-real")
    monkeypatch.setattr(voice, "RETRY_WAIT", 0)


def fake_http(monkeypatch, replies):
    """replies: list of (status, payload), served in order. Returns the list of recorded calls."""
    calls = []

    def http(path, body, content_type, timeout=40):
        calls.append({"path": path, "body": body, "content_type": content_type})
        return replies[min(len(calls), len(replies)) - 1]
    monkeypatch.setattr(voice, "_http", http)
    return calls


def tts_reply():
    return 200, {"request_id": "r1", "audios": [base64.b64encode(MP3).decode()]}


def test_status(client):
    r = client.get("/api/voice/status").json()
    assert r == {"available": True, "stt_model": "saaras:v4", "tts_model": "bulbul:v4-flash",
                 "voices": {"en-IN": "simran_en_customer", "hi-IN": "ishita_hi_banking", "mixed": "ishita_enhi_customer"}}


def test_stt_success(client, monkeypatch):
    calls = fake_http(monkeypatch, [(200, {"request_id": "r", "transcript": " Am I eligible for the GGSIP bid? ",
                                           "language_code": "en-IN", "language_probability": 0.97})])
    r = client.post("/api/voice/stt", files={"file": ("rec.webm", b"\x1aE\xdf\xa3audio", "audio/webm")})
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == "Am I eligible for the GGSIP bid?"
    assert body["language_code"] == "en-IN" and body["language_probability"] == 0.97 and "ms" in body
    sent = calls[0]
    assert sent["path"] == "/speech-to-text" and sent["content_type"].startswith("multipart/form-data")
    for part in (b'name="model"\r\n\r\nsaaras:v4', b'name="mode"\r\n\r\ntranscribe',
                 b'name="language_code"\r\n\r\nunknown', b'filename="rec.webm"', b"audio/webm"):
        assert part in sent["body"]


def test_stt_drops_browser_codec_label(client, monkeypatch):
    # Chrome sends "audio/webm;codecs=opus"; Sarvam rejects anything but the bare type.
    calls = fake_http(monkeypatch, [(200, {"transcript": "hello", "language_code": "en-IN"})])
    r = client.post("/api/voice/stt", files={"file": ("rec.webm", b"x" * 10, "audio/webm;codecs=opus")})
    assert r.status_code == 200
    assert b"Content-Type: audio/webm" + bytes([13, 10]) in calls[0]["body"] and b"codecs" not in calls[0]["body"]


def test_stt_hindi_uses_codemix(client, monkeypatch):
    calls = fake_http(monkeypatch, [(200, {"transcript": "kya main eligible hoon", "language_code": "hi-IN"})])
    client.post("/api/voice/stt", files={"file": ("a.webm", b"x" * 10, "audio/webm")}, data={"language": "hi-IN"})
    assert b'name="mode"\r\n\r\ncodemix' in calls[0]["body"] and b"hi-IN" in calls[0]["body"]


def test_stt_rejects_empty_and_large(client, monkeypatch):
    calls = fake_http(monkeypatch, [(200, {})])
    r = client.post("/api/voice/stt", files={"file": ("a.webm", b"", "audio/webm")})
    assert r.status_code == 422 and "empty" in r.json()["detail"]
    r = client.post("/api/voice/stt", files={"file": ("a.webm", b"x" * (voice.MAX_AUDIO_BYTES + 1), "audio/webm")})
    assert r.status_code == 422 and "30 seconds" in r.json()["detail"]
    assert calls == []


def test_tts_success(client, monkeypatch):
    calls = fake_http(monkeypatch, [tts_reply()])
    r = client.post("/api/voice/tts", json={"text": "You are eligible for this bid."})
    assert r.status_code == 200
    body = r.json()
    assert base64.b64decode(body["audio_base64"]) == MP3
    assert body["format"] == "mp3" and body["speaker"] == "simran_en_customer" and body["language_code"] == "en-IN"
    sent = json.loads(calls[0]["body"])
    assert sent == {"text": "You are eligible for this bid.", "language_code": "en-IN", "speaker": "simran_en_customer",
                    "model": "bulbul:v4-flash", "pace": 1.05, "speech_sample_rate": 22050, "output_audio_codec": "mp3"}


def test_tts_joins_several_audio_chunks(client, monkeypatch):
    fake_http(monkeypatch, [(200, {"audios": [base64.b64encode(b"AB").decode(), base64.b64encode(b"CD").decode()]})])
    assert base64.b64decode(client.post("/api/voice/tts", json={"text": "Hi."}).json()["audio_base64"]) == b"ABCD"


@pytest.mark.parametrize("text,lang,voice_key", [
    ("आप इस बोली के लिए पात्र हैं।", "hi-IN", "hi-IN"),
    ("Aap is bid ke liye eligible hain, lekin EMD chahiye.", "en-IN", "mixed"),
    ("Northstar is not eligible: the turnover is too low.", "en-IN", "en-IN"),
    ("The EMD is not required for this bid, so you can go ahead.", "en-IN", "en-IN"),   # one stray "so" is not Hindi
])
def test_auto_language(text, lang, voice_key):
    assert voice.pick_language(text) == (lang, voice_key)


def test_tts_auto_picks_hindi_voice(client, monkeypatch):
    calls = fake_http(monkeypatch, [tts_reply()])
    body = client.post("/api/voice/tts", json={"text": "आप पात्र हैं।"}).json()
    assert body["speaker"] == "ishita_hi_banking" and json.loads(calls[0]["body"])["language_code"] == "hi-IN"


def test_markdown_is_stripped():
    md = ("## Verdict\n**Not eligible** for [GEM/2026/B/8096659](https://bidplus.gem.gov.in/x).\n"
          "- Turnover: Rs 44.7 L vs *Rs 60 L*\n- `OEM` letter missing\n\nSee https://example.com for more")
    assert voice.speakable(md) == ("Verdict. Not eligible for GEM/2026/B/8096659. Turnover: Rs 44.7 L vs Rs 60 L. "
                                   "OEM letter missing. See for more.")


def test_long_text_cut_at_sentence(client, monkeypatch):
    sentence = "This criterion is met on page three of the bid. "
    text = sentence * 80                                              # ~3900 chars
    cut = voice.cut(voice.speakable(text))
    assert len(cut) <= voice.MAX_SPEAK_CHARS and cut.endswith("bid.")
    calls = fake_http(monkeypatch, [tts_reply()])
    body = client.post("/api/voice/tts", json={"text": text}).json()
    assert len(json.loads(calls[0]["body"])["text"]) <= 2500 and body["chars"] == len(cut)


def test_402_is_friendly_and_not_retried(client, monkeypatch):
    calls = fake_http(monkeypatch, [(402, {"error": {"message": "Insufficient quota", "code": "insufficient_quota_error"}})])
    r = client.post("/api/voice/tts", json={"text": "Hello."})
    assert r.status_code == 402 and r.json()["detail"].startswith("Voice credits are used up")
    assert len(calls) == 1


def test_429_retried_once(client, monkeypatch):
    calls = fake_http(monkeypatch, [(429, {"error": {"message": "rate", "code": "rate_limit_exceeded_error"}}), tts_reply()])
    assert client.post("/api/voice/tts", json={"text": "Hello."}).status_code == 200
    assert len(calls) == 2


def test_503_twice_gives_plain_message(client, monkeypatch):
    calls = fake_http(monkeypatch, [(503, {}), (503, {})])
    r = client.post("/api/voice/tts", json={"text": "Hello."})
    assert r.status_code == 503 and "unavailable" in r.json()["detail"] and len(calls) == 2


def test_bad_request_message_never_includes_key(client, monkeypatch):
    fake_http(monkeypatch, [(400, {"error": {"message": "Invalid speaker", "code": "invalid_request_error"}})])
    r = client.post("/api/voice/tts", json={"text": "Hello."})
    assert r.status_code == 502 and "Invalid speaker" in r.json()["detail"]
    assert "test-key-not-real" not in r.text


def test_unexpected_error_is_handled(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("socket exploded")
    monkeypatch.setattr(voice, "_http", boom)
    r = client.post("/api/voice/tts", json={"text": "Hello."})
    assert r.status_code == 502 and "RuntimeError" in r.json()["detail"]


def test_empty_text_is_422(client, monkeypatch):
    calls = fake_http(monkeypatch, [tts_reply()])
    assert client.post("/api/voice/tts", json={"text": "  **  "}).status_code == 422 and calls == []


def test_missing_key(client, monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "")
    calls = fake_http(monkeypatch, [tts_reply()])
    assert client.get("/api/voice/status").json()["available"] is False
    r = client.post("/api/voice/tts", json={"text": "Hello."})
    assert r.status_code == 503 and "SARVAM_API_KEY" in r.json()["detail"]
    r = client.post("/api/voice/stt", files={"file": ("a.webm", b"x" * 10, "audio/webm")})
    assert r.status_code == 503
    assert calls == []

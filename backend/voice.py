"""Voice for the BidReady assistant, through Sarvam AI.

- Speech to text: Saaras v4 (auto-detects en-IN / hi-IN, handles Hinglish).
- Text to speech: Bulbul v4 flash, one voice each for English, Hindi and code-mixed Hinglish. Markdown is stripped
  before speaking, and long answers are cut at a sentence so the request stays under Sarvam's 2500-character limit.
The key is read from SARVAM_API_KEY and never returned or logged. Every Sarvam failure becomes a plain message.
"""

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from . import ratelimit

router = APIRouter()

SARVAM_URL = "https://api.sarvam.ai"
STT_MODEL = "saaras:v4"
TTS_MODEL = "bulbul:v4-flash"
VOICES = {"en-IN": "simran_en_customer", "hi-IN": "ishita_hi_banking", "mixed": "ishita_enhi_customer"}
PACE = 1.05
SAMPLE_RATE = 22050
MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_SPEAK_CHARS = 2400
RETRY_WAIT = 1.0
CALLS_PER_HOUR = 40          # per client IP, for speech-to-text and text-to-speech each (the landing page is public)
LIMIT_DETAIL = "Voice has been used a lot from here for now. Please try again in a little while, or type your question."

# Common romanised Hindi words: two or more of these in an English sentence means Hinglish.
HINGLISH = {
    "hai", "hain", "nahi", "nahin", "kya", "kyun", "kyon", "aap", "mein", "mera", "meri", "tum", "hum", "ho", "hoga",
    "karo", "karna", "kar", "kijiye", "batao", "bataiye", "accha", "achha", "theek", "thik", "lekin", "aur", "bhi",
    "toh", "yeh", "woh", "sab", "kuch", "bahut", "chahiye", "abhi", "matlab", "wala", "wali", "liye", "se", "ka",
    "ki", "ke", "ko", "na", "haan", "ji", "bhai", "dekho", "samjho",
}


class VoiceError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _key():
    return os.environ.get("SARVAM_API_KEY", "").strip()


def available():
    return bool(_key())


# ---------------------------------------------------------------- HTTP

def _http(path, body, content_type, timeout=40):
    """One request to Sarvam. -> (status, parsed JSON or {}). Network failures raise VoiceError."""
    req = urllib.request.Request(SARVAM_URL + path, data=body, method="POST",
                                 headers={"api-subscription-key": _key(), "Content-Type": content_type,
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            payload = {}
        return e.code, payload
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise VoiceError(502, f"Could not reach the voice service ({type(e).__name__}).") from None


def _message(status, payload):
    err = (payload or {}).get("error") or {}
    detail = err.get("message") if isinstance(err, dict) else str(err)
    code = err.get("code") if isinstance(err, dict) else None
    if status == 402 or code == "insufficient_quota_error":
        return 402, "Voice credits are used up. Top up the Sarvam account to use voice again."
    if status in (401, 403):
        return 502, "The voice service rejected the API key. Check SARVAM_API_KEY."
    if status == 429:
        return 503, "The voice service is busy right now. Try again in a moment."
    if status >= 500:
        return 503, "The voice service is unavailable right now. Try again in a moment."
    return 502, f"The voice service could not handle this request: {detail or f'HTTP {status}'}"


def _call(path, body, content_type):
    """Call Sarvam; retry once on 429/503; raise VoiceError with a plain message on any failure."""
    if not available():
        raise VoiceError(503, "Voice is not set up: SARVAM_API_KEY is missing.")
    for attempt in (1, 2):
        status, payload = _http(path, body, content_type)
        if 200 <= status < 300:
            return payload
        if status in (429, 503) and attempt == 1:
            time.sleep(RETRY_WAIT)
            continue
        raise VoiceError(*_message(status, payload))


def _multipart(fields, file_name, file_bytes, file_type):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
                 f'Content-Type: {file_type}\r\n\r\n'.encode() + file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------- text preparation

def speakable(text):
    """Markdown to plain sentences: links keep their text, URLs, code fences, emphasis, headings and bullets go."""
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)                      # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)                    # [text](url) -> text
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)                       # headings
    t = re.sub(r"(?m)^\s*(?:[-*+•]|\d+[.)])\s+", "", t)               # bullets and numbered items
    t = re.sub(r"(\*\*|__|\*|~~)(.+?)\1", r"\2", t)
    t = re.sub(r"(?m)^\s*\|?[\s:|-]+\|[\s:|-]*$", "", t)              # table rules
    t = t.replace("|", ", ")
    t = re.sub(r"(?m)^\s*>\s?", "", t)                                # quotes
    # line breaks become pauses: end a line that has no punctuation with a full stop
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    t = " ".join(ln if re.search(r"[.!?:;।,]$", ln) else ln + "." for ln in lines)
    return re.sub(r"\s{2,}", " ", t).strip()


def cut(text, limit=MAX_SPEAK_CHARS):
    """At most `limit` characters, ending at the last sentence end (or else the last space) before it."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?।](?=\s|$)", head)]
    if ends and ends[-1] > limit // 2:
        return head[:ends[-1]].strip()
    return head.rsplit(" ", 1)[0].strip()


def pick_language(text):
    """-> (language_code for Sarvam, voice key). Devanagari -> Hindi; English with Hindi words -> Hinglish voice."""
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "hi-IN", "hi-IN"
    words = re.findall(r"[a-z]+", (text or "").lower())
    hindi = sum(1 for w in words if w in HINGLISH)
    if hindi >= 2 and hindi >= 0.15 * len(words):
        return "en-IN", "mixed"
    return "en-IN", "en-IN"


# ---------------------------------------------------------------- operations

def transcribe(audio, file_name="speech.webm", content_type="audio/webm", language=None):
    if not audio:
        raise VoiceError(422, "The recording is empty. Hold the button and speak, then release.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise VoiceError(422, "The recording is too long. Keep it under 30 seconds.")
    lang = language if language in ("en-IN", "hi-IN") else "unknown"
    mode = "codemix" if language in ("hi-IN", "mixed") else "transcribe"
    # Browsers label recordings "audio/webm;codecs=opus"; Sarvam accepts only the bare type ("audio/webm").
    file_type = (content_type or "").split(";")[0].strip() or "application/octet-stream"
    body, ctype = _multipart({"model": STT_MODEL, "mode": mode, "language_code": lang},
                             file_name or "speech.webm", audio, file_type)
    t0 = time.perf_counter()
    payload = _call("/speech-to-text", body, ctype)
    return {"transcript": (payload.get("transcript") or "").strip(), "language_code": payload.get("language_code"),
            "language_probability": payload.get("language_probability"),
            "ms": int((time.perf_counter() - t0) * 1000)}


def speak(text, language_code=None):
    words = cut(speakable(text))
    if not re.search(r"\w", words):
        raise VoiceError(422, "There is nothing to say: the text is empty.")
    if language_code in ("en-IN", "hi-IN"):
        lang, voice = language_code, language_code
    elif language_code == "mixed":
        lang, voice = "en-IN", "mixed"
    else:
        lang, voice = pick_language(words)
    body = json.dumps({"text": words, "language_code": lang, "speaker": VOICES[voice], "model": TTS_MODEL,
                       "pace": PACE, "speech_sample_rate": SAMPLE_RATE, "output_audio_codec": "mp3"}).encode()
    t0 = time.perf_counter()
    payload = _call("/text-to-speech", body, "application/json")
    audios = payload.get("audios") or []
    if not audios:
        raise VoiceError(502, "The voice service returned no audio.")
    # several chunks are concatenated mp3 frames, which browsers play as one file
    audio = b"".join(base64.b64decode(a) for a in audios)
    return {"audio_base64": base64.b64encode(audio).decode("ascii"), "format": "mp3", "speaker": VOICES[voice],
            "language_code": lang, "voice": voice, "chars": len(words), "ms": int((time.perf_counter() - t0) * 1000)}


# ---------------------------------------------------------------- routes

def _guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except VoiceError as e:
        raise HTTPException(e.status, e.message) from None
    except HTTPException:
        raise
    except Exception as e:                                            # never an unhandled 500 with a traceback
        raise HTTPException(502, f"Voice failed unexpectedly ({type(e).__name__}).") from None


@router.get("/api/voice/status")
def status():
    return {"available": available(), "stt_model": STT_MODEL, "tts_model": TTS_MODEL, "voices": dict(VOICES)}


@router.post("/api/voice/stt")
async def stt(request: Request, file: UploadFile = File(...), language: str | None = Form(None)):
    ratelimit.enforce(request, "voice-stt", CALLS_PER_HOUR, LIMIT_DETAIL)
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    return _guard(transcribe, audio, file.filename, file.content_type, language)


class SpeakBody(BaseModel):
    text: str
    language_code: str | None = None


@router.post("/api/voice/tts")
def tts(body: SpeakBody, request: Request):
    ratelimit.enforce(request, "voice-tts", CALLS_PER_HOUR, LIMIT_DETAIL)
    return _guard(speak, body.text, body.language_code)

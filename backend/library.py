"""The stored library of real GeM bids (backend/corpus).

library.json holds each bid already parsed and read (parser fields, validated Claude clauses, page text), so the
app starts in well under a second and a verdict can always be traced to the exact text it was based on.
Rebuild it with:  python -m backend.tools.build_corpus --rebuild-library
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "corpus"
LIBRARY = CORPUS / "library.json"


def _status(t):
    today = datetime.now(timezone.utc).date().isoformat()
    closes = t.get("closes")
    return "open" if closes and closes >= today else ("closed" if closes else "unknown")


def build(use_ai=True, ai_live=False):
    """Parse every stored PDF (and read it with Claude, from cache unless ai_live) -> {tid: tender}."""
    from .extract import build_tender

    index = json.loads((CORPUS / "index.json").read_text(encoding="utf-8"))
    out = {}
    for e in index:
        pdf = (CORPUS / f"{e['doc_id']}.pdf").read_bytes()
        meta = {k: e.get(k) for k in ("bid", "items", "ministry", "end", "retrieved_at")}
        t, _ = build_tender(pdf, e["url"], meta=meta, tid=f"g-{e['doc_id']}", use_ai=use_ai, ai_live=ai_live)
        t["_source"] = {"search": {"keyword": e.get("keyword"), "total": e.get("total"), "ms": e.get("search_ms", 0)},
                        "fetch": {"url": e["url"], "bytes": len(pdf), "ms": e.get("fetch_ms", 0),
                                  "snapshot": e.get("retrieved_at"), "sha256": hashlib.sha256(pdf).hexdigest()}}
        out[t["id"]] = t
    return out


def save(tenders):
    LIBRARY.write_text(json.dumps(list(tenders.values()), ensure_ascii=False), encoding="utf-8")


def load():
    if LIBRARY.exists():
        try:
            tenders = {t["id"]: t for t in json.loads(LIBRARY.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            tenders = build(use_ai=True)
    else:
        tenders = build(use_ai=True)
    for t in tenders.values():
        t["status"] = _status(t)
    return tenders

"""Refresh the stored library of real, open GeM IT-hardware bids.

    python -m backend.tools.build_corpus            # default keywords, keeps up to 14 bids
    python -m backend.tools.build_corpus --max 20

Each kept bid is saved as backend/corpus/<doc_id>.pdf plus an entry in backend/corpus/index.json.
A stored copy lets the demo run when GeM is slow, and pins the exact text every verdict was based on.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from backend import gem, sources

CORPUS = Path(__file__).resolve().parent.parent / "corpus"
KEYWORDS = ["laptop", "desktop computer", "all in one pc", "multifunction printer",
            "network switch", "online ups", "cctv camera"]
SKIP_WORDS = ("amc", "maintenance", "repair", "cartridge", "toner", "hiring", "manpower", "service -", "buyback")


def richness(g):
    keys = ("turnover_lakh", "experience_years", "emd_required", "mse_relax_experience", "documents_required")
    return sum(1 for k in keys if g.get(k)) + (1 if gem.oem_authorisation_required(g) else 0)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=14)
    ap.add_argument("--per-keyword", type=int, default=3)
    ap.add_argument("--keywords", nargs="*", default=KEYWORDS)
    args = ap.parse_args(argv)
    CORPUS.mkdir(exist_ok=True)
    index_path = CORPUS / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
    have = {e["doc_id"] for e in index}
    now = datetime.now(timezone.utc).isoformat()
    for kw in args.keywords:
        if len(index) >= args.max:
            break
        try:
            res = sources.search_gem_bids(kw)
        except sources.SourceError as e:
            print("search failed:", kw, e)
            continue
        kept = 0
        for b in res["bids"]:
            if kept >= args.per_keyword or len(index) >= args.max:
                break
            if b["doc_id"] in have or any(w in b["items"].lower() for w in SKIP_WORDS):
                continue
            try:
                doc = sources.download(b["url"])
            except sources.SourceError as e:
                print("download failed:", b["bid"], e)
                continue
            if doc["bytes"][:5] != b"%PDF-":
                continue
            parsed = gem.read_pdf(doc["bytes"])
            g = gem.parse_gem(parsed["pages"])
            if richness(g) < 4:
                continue
            (CORPUS / f"{b['doc_id']}.pdf").write_bytes(doc["bytes"])
            index.append({"doc_id": b["doc_id"], "bid": b["bid"], "url": b["url"], "keyword": kw,
                          "items": b["items"], "ministry": b["ministry"], "end": b["end"], "retrieved_at": now,
                          "bytes": len(doc["bytes"]), "pages": len(parsed["pages"])})
            have.add(b["doc_id"])
            kept += 1
            print(f"kept {b['bid']} · {b['items'][:50]} · ends {b['end']} · richness {richness(g)}")
            time.sleep(0.5)
        print(f"{kw}: {res['total']} open bids, kept {kept}")
    index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"corpus: {len(index)} bids")


if __name__ == "__main__":
    sys.exit(main())

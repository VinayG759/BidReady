"""Simulated TinyFish stages (search / fetch / extract) and the real evidence validator.

The TinyFish calls are simulated (mode "synthetic"): they produce realistic log lines
and timings, deterministic per tender + profile. The validator is real code and is the
gate between "the model said so" and "the document says so".
"""

import random
import re

CRITERIA = [
    ("turnover", "Turnover"),
    ("experience", "Prior experience"),
    ("oem", "OEM authorisation"),
    ("emd", "EMD / exemption"),
]

# Which structured requirement each criterion's rupee amount must equal.
AMOUNT_FIELD = {"turnover": "turnover_lakh", "experience": "order_min_lakh", "emd": "emd_lakh"}

_AMOUNT_RE = re.compile(
    r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(lakhs?|lacs?|crores?|cr\b|l\b)?",
    re.IGNORECASE,
)


def normalise(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def parse_amount_lakh(text):
    """First rupee amount in text, in lakh. 'Rs. 50 Lakh'->50, 'Rs. 1,50,000'->1.5, 'Rs. 2 Crore'->200."""
    m = _AMOUNT_RE.search(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    if unit.startswith("cr"):
        return round(value * 100, 4)
    if unit.startswith("la") or unit == "l":
        return round(value, 4)
    return round(value / 100000, 4)


def validate_clause(tender, key):
    """Check one extracted clause against the retrieved text. Returns (validation, reason or None)."""
    clause = (tender.get("clauses") or {}).get(key)
    if not clause or not clause.get("quote"):
        return ({"quote_found": False, "number_match": False, "heading_match": False},
                "the clause was not found in the tender document")

    source = tender.get("_source", {})
    doc_text = source.get(clause.get("doc"), "")
    all_text = " ".join(source.values())
    quote_found = normalise(clause["quote"]) in normalise(doc_text or all_text)

    field = AMOUNT_FIELD.get(key)
    if field:
        expected = (tender.get("_req") or {}).get(field)
        found = parse_amount_lakh(clause["quote"])
        number_match = expected is not None and found is not None and abs(found - float(expected)) < 1e-6
    else:
        number_match = True  # no rupee amount in this criterion, nothing to contradict

    headings = tender.get("_headings", {}).get(clause.get("doc"), [])
    heading_match = normalise(clause.get("heading")) in [normalise(h) for h in headings]

    validation = {"quote_found": quote_found, "number_match": number_match, "heading_match": heading_match}
    reasons = []
    if not quote_found:
        doc = next((d for d in tender.get("docs", []) if d["name"] == clause.get("doc")), None)
        if doc and doc.get("text") == "image_only":
            reasons.append(f"the quote sits in '{clause.get('doc')}', an image-only scan with no extractable text")
        else:
            reasons.append("the quote was not found in the retrieved text")
    if not number_match:
        reasons.append("the amount in the quote does not match the extracted requirement")
    if not heading_match:
        reasons.append("the clause heading is not in the document's heading list")
    return validation, ("; ".join(reasons) or None)


def _rng(tender, profile_id):
    return random.Random(f"{tender['id']}|{profile_id}")


def _chars(tender):
    body = sum(len(t) for t in tender.get("_source", {}).values())
    return max(body, 1) * 37 + tender.get("pages", 1) * 113


def run_retrieval(tender, profile_id):
    """Simulated search/fetch/extract stages. Returns the three stage dicts."""
    r = _rng(tender, profile_id)
    portal_host = {"GeM": "bidplus.gem.gov.in", "CPPP": "eprocure.gov.in", "KPPP": "kppp.karnataka.gov.in"}.get(
        tender.get("portal"), "uploaded")
    uploaded = tender["id"].startswith("u-")

    ms = r.randint(320, 610)
    if uploaded:
        search_logs = [f"skip api.search.tinyfish.ai · document uploaded by user ({tender['docs'][0]['name']})"]
        ms = r.randint(4, 12)
    else:
        q = "+".join(tender["title"].lower().split()[:4])
        search_logs = [
            f"GET api.search.tinyfish.ai/v1/search?q={q}&site={portal_host} 200 · {r.randint(5, 14)} results · {ms} ms",
            f"match {tender['bid']} · score {r.uniform(0.91, 0.99):.2f}",
        ]
    search = {"key": "search", "name": "Search", "owner": "TinyFish", "status": "ok", "ms": ms, "logs": search_logs}

    fetch_logs, fetch_status, fetch_ms = [], "ok", 0
    for d in tender.get("docs", []):
        dms = r.randint(700, 1600)
        fetch_ms += dms
        chars = len(tender.get("_source", {}).get(d["name"], "")) * 37
        fetch_logs.append(f"POST api.fetch.tinyfish.ai url={tender['url']}#{d['name'].replace(' ', '%20')} 200 · "
                          f"{d['pages']} pages · {chars:,} chars · {dms} ms")
        if d.get("text") == "image_only":
            fetch_status = "warn"
            pages = tender.get("_image_only_pages", f"1-{d['pages']}")
            fetch_logs.append(f"warn pages {pages} image-only, no extractable text ({d['name']})")
    fetch_logs.append(f"total {tender.get('pages', 0)} pages · {_chars(tender):,} chars retrieved")
    fetch = {"key": "fetch", "name": "Fetch", "owner": "TinyFish", "status": fetch_status, "ms": fetch_ms, "logs": fetch_logs}

    ems = r.randint(1800, 3400)
    extract_logs = [f"POST agent.tinyfish.ai/v1/automation/run schema=EligibilityCriteria{{criterion,heading,quote,page,doc}} 200 · {ems} ms"]
    for key, name in CRITERIA:
        c = (tender.get("clauses") or {}).get(key)
        if c:
            extract_logs.append(f"  extracted {name} · \"{c['heading']}\" · p. {c.get('page')}")
        else:
            extract_logs.append(f"  {name} · no clause returned")
    missing = [k for k, _ in CRITERIA if not (tender.get("clauses") or {}).get(k)]
    extract = {"key": "extract", "name": "Extract", "owner": "TinyFish",
               "status": "warn" if missing else "ok", "ms": ems, "logs": extract_logs}
    return [search, fetch, extract]


def run_validation(tender):
    """Run the validator on every criterion. Returns (results by key, stage dict)."""
    results, logs, bad = {}, [], 0
    for key, name in CRITERIA:
        validation, reason = validate_clause(tender, key)
        results[key] = (validation, reason)
        if reason:
            bad += 1
            logs.append(f"x {name}: {reason} -> criterion unresolved")
        else:
            logs.append(f"ok {name}: quote found · amount matches · heading matches")
    logs.append(f"{len(CRITERIA) - bad}/{len(CRITERIA)} criteria evidence-validated")
    stage = {"key": "validate", "name": "Validate", "owner": "Our code", "status": "warn" if bad else "ok",
             "ms": random.Random(tender["id"]).randint(8, 30), "logs": logs}
    return results, stage

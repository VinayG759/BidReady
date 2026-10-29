"""Evidence validator and pipeline stage records.

The validator is the gate between "a parser or a model said so" and "the document says so": every clause quote must
appear in the retrieved page text, its number must equal the requirement the rules will use, and its heading or label
must be present on that page. Stage records describe what actually ran, with real timings.
"""

import re

CRITERIA = [
    ("turnover", "Turnover"),
    ("experience", "Prior experience"),
    ("oem", "OEM authorisation"),
    ("emd", "EMD / exemption"),
]

_LAKH_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(lakhs?|lacs?|crores?|cr\b)", re.I)
_RUPEE_RE = re.compile(r"(?:rs\.?|inr|₹|amount(?:\s*\(in inr\))?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)", re.I)
_YEARS_RE = re.compile(r"(\d+)\s*year", re.I)


def normalise(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def parse_amount_lakh(text):
    """First lakh/crore amount in text, in lakh: '60 Lakh (s)' -> 60, '2 Crore' -> 200; plain rupees -> lakh."""
    m = _LAKH_RE.search(text or "")
    if m:
        v = float(m.group(1).replace(",", ""))
        return round(v * 100, 4) if m.group(2).lower().startswith("cr") else round(v, 4)
    m = _RUPEE_RE.search(text or "")
    return round(float(m.group(1).replace(",", "")) / 100000, 4) if m else None


def parse_rupees(text):
    m = _RUPEE_RE.search(text or "")
    if m:
        return float(m.group(1).replace(",", ""))
    m = re.search(r"\b([0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]{4,})\b", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def parse_years(text):
    m = _YEARS_RE.search(text or "")
    return int(m.group(1)) if m else None


def validate_clause(tender, key):
    """-> (validation dict, reason or None). validation values: True / False, or None when not applicable."""
    clause = (tender.get("clauses") or {}).get(key)
    req = tender.get("_req") or {}
    if not clause or not clause.get("quote"):
        return {"quote_found": None, "number_match": None, "heading_match": None}, "no clause"

    pages = tender.get("_pages") or []
    page = clause.get("page")
    page_text = pages[page - 1] if page and 1 <= page <= len(pages) else ""
    quote_found = normalise(clause["quote"]) in normalise(page_text)

    if key == "turnover":
        expected, found = req.get("turnover_lakh"), parse_amount_lakh(clause["quote"])
    elif key == "experience":
        expected, found = req.get("experience_years"), parse_years(clause["quote"])
    elif key == "emd" and req.get("emd_rupees"):
        expected, found = req.get("emd_rupees"), parse_rupees(clause["quote"])
    else:
        expected = found = None
    number_match = None if expected is None else (found is not None and abs(float(found) - float(expected)) < 1e-6)

    heading = clause.get("heading") or ""
    heading_match = (normalise(heading) in normalise(page_text)) if clause.get("source") == "parser" and heading else None

    validation = {"quote_found": quote_found, "number_match": number_match, "heading_match": heading_match}
    reasons = []
    if not quote_found:
        img = (tender.get("docs") or [{}])[0].get("image_only_pages") or []
        reasons.append(f"the quote is not in the text of page {page}"
                       + (" (that page is an image-only scan)" if page in img else ""))
    if number_match is False:
        reasons.append("the number in the quote does not match the extracted requirement")
    if heading_match is False:
        reasons.append("the field label is not on that page")
    return validation, ("; ".join(reasons) or None)


def stage(key, name, owner, status, ms, logs):
    return {"key": key, "name": name, "owner": owner, "status": status, "ms": int(ms), "logs": logs}


def run_validation(tender):
    results, logs, bad = {}, [], 0
    for key, name in CRITERIA:
        validation, reason = validate_clause(tender, key)
        results[key] = (validation, None if reason == "no clause" else reason)
        if reason == "no clause":
            logs.append(f"- {name}: no clause in this bid")
        elif reason:
            bad += 1
            logs.append(f"x {name}: {reason} -> criterion unresolved")
        else:
            checks = [n for n, k in (("quote on page", "quote_found"), ("number matches", "number_match"),
                                     ("label on page", "heading_match")) if validation[k]]
            logs.append(f"ok {name}: " + " · ".join(checks))
    rej = tender.get("_ai_rejected") or []
    if rej:
        logs.append(f"x {len(rej)} AI-extracted clause(s) rejected: quote not found in the document")
    return results, logs, bad

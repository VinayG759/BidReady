"""Turn a real tender document into requirements + evidence clauses for the four criteria.

Order of trust: the GeM template parser first (exact labels, exact values); Claude's clauses second, and only
after their quotes pass the validator. Claude fills gaps (e.g. experience stated only in the ATC), adds tender-
specific conditions, and catches denials of relaxation. Nothing is invented: a criterion with no evidence is either
"not required by this bid" (when the bid has explicit fields and none mention it) or unresolved.
"""

import re
import secrets
from datetime import datetime, timezone

from . import ai, gem
from .data import category_of
from .pipeline import CRITERIA, normalise, parse_amount_lakh, parse_years

KNOWN_BRANDS = ["Lenovo", "HP", "Dell", "Acer", "Asus", "Apple", "Cisco", "Aruba", "Juniper", "D-Link", "Netgear",
                "TP-Link", "Hikvision", "CP Plus", "Dahua", "Honeywell", "Bosch", "Canon", "Epson", "Brother", "Ricoh",
                "Kyocera", "Konica", "Xerox", "APC", "Vertiv", "Microtek", "Luminous"]


def _clause(heading, quote, page, highlight="", doc="GeM bid document", source="parser"):
    return {"heading": heading, "quote": quote, "page": page, "highlight": highlight, "doc": doc, "source": source}


def _gem_clause(field, highlight_rx=None, source="parser"):
    if not field:
        return None
    q = field["quote"]
    hl = ""
    if highlight_rx:
        m = re.search(highlight_rx, q, re.I)
        hl = m.group(0) if m else ""
    return _clause(field["label"], q, field["page"], hl, source=source)


def _brands(text):
    found = []
    for b in KNOWN_BRANDS:
        if re.search(rf"(?<![A-Za-z]){re.escape(b)}(?![A-Za-z])", text or "", re.I) and b not in found:
            found.append(b)
    return found


def _iso_end(g, meta):
    end = (meta or {}).get("end")
    if end:
        return end[:10]
    v = (g.get("bid_end") or {}).get("value")
    if v:
        try:
            return datetime.strptime(v[:10], "%d-%m-%Y").date().isoformat()
        except ValueError:
            pass
    return None


def build_tender(pdf_bytes, url, meta=None, tid=None, use_ai=True, ai_live=True):
    """-> (tender, extraction_log). tender carries private fields (_pages, _req, ...) that public() strips.
    ai_live=False uses only cached Claude results (no paid call)."""
    meta = meta or {}
    doc = gem.read_pdf(pdf_bytes)
    pages = doc["pages"]
    is_gem = gem.is_gem(pages)
    g = gem.parse_gem(pages) if is_gem else {}
    v = lambda k: (g.get(k) or {}).get("value")
    log = {"parser": [], "ai": None}

    # ---- Claude reads the document; only validated quotes are kept
    ai_res = ai.extract(pages, live=ai_live) if use_ai else {"error": "AI extraction off", "clauses": []}
    full_norm = normalise(" ".join(pages))
    ai_ok, ai_bad = [], []
    for c in ai_res.get("clauses", []):
        page_text = pages[c["page"] - 1] if 1 <= c.get("page", 0) <= len(pages) else ""
        found_on_page = normalise(c["quote"]) in normalise(page_text)
        found_anywhere = found_on_page or normalise(c["quote"]) in full_norm
        if found_anywhere:
            if not found_on_page:  # right words, wrong page number: correct the page from the text
                c["page"] = next((i for i, t in enumerate(pages, 1) if normalise(c["quote"]) in normalise(t)), c["page"])
            ai_ok.append(c)
        else:
            ai_bad.append(c)
    log["ai"] = {k: ai_res.get(k) for k in ("model", "ms", "cached", "input_tokens", "output_tokens", "error")}
    log["ai"].update(returned=len(ai_res.get("clauses", [])), verified=len(ai_ok), rejected=len(ai_bad))

    def ai_for(crit, kinds=None):
        return [c for c in ai_ok if c["criterion"] == crit and (kinds is None or c["kind"] in kinds)]

    def ai_clause(c):
        return _clause(c.get("heading") or "Additional Terms and Conditions", c["quote"], c["page"], source="ai")

    title_text = v("item_category") or meta.get("items") or ""
    category = category_of(title_text + " " + (meta.get("items") or ""))
    req, clauses, extra, conditions = {}, {}, {k: [] for k, _ in CRITERIA}, []

    # ---- Turnover
    req["turnover_lakh"] = v("turnover_lakh")
    clauses["turnover"] = _gem_clause(g.get("turnover_lakh"), r"[\d,.]+\s*(Lakh|Crore)")
    if req["turnover_lakh"] is None:
        c = next((c for c in ai_for("turnover", ["requirement"]) if c.get("turnover_lakh")), None)
        if c:
            req["turnover_lakh"], clauses["turnover"] = c["turnover_lakh"], ai_clause(c)
    req["mse_relax_turnover"] = v("mse_relax_turnover")
    req["startup_relax_turnover"] = v("startup_relax_turnover")
    req["relax_turnover_clause"] = _gem_clause(g.get("mse_relax_turnover"), r"(Yes|No)\b.*")

    # ---- Experience (financial years with supplies of similar category to Govt/PSU)
    req["experience_years"] = v("experience_years")
    clauses["experience"] = _gem_clause(g.get("experience_years"), r"\d+\s*Year")
    if req["experience_years"] is None:
        c = next((c for c in ai_for("experience", ["requirement"]) if c.get("experience_years")), None)
        if c:
            req["experience_years"], clauses["experience"] = int(c["experience_years"]), ai_clause(c)
    req["mse_relax_experience"] = v("mse_relax_experience")
    req["startup_relax_experience"] = v("startup_relax_experience")
    req["relax_experience_clause"] = _gem_clause(g.get("mse_relax_experience"), r"(Yes|No)\b.*")
    docs_req = v("documents_required") or ""
    req["experience_docs_listed"] = "experience criteria" in docs_req.lower()

    # A relaxation the ATC explicitly denies overrides a template "Yes".
    for crit in ("turnover", "experience"):
        denial = next((c for c in ai_for(crit, ["relaxation_denied"])
                       if "relaxation for" not in normalise(c["quote"]) and "exemption for" not in normalise(c["quote"])), None)
        if denial:  # an ATC clause, not the template's own "Relaxation ... No" line
            req[f"relax_denied_{crit}"] = ai_clause(denial)

    # ---- OEM authorisation
    oem_ai = ai_for("oem", ["requirement", "document_required"])
    oem_auth_ai = [c for c in oem_ai if re.search(r"authori[sz]ation|\bMAF\b|manufacturer authori", c["quote"], re.I)]
    req["oem_required"] = gem.oem_authorisation_required(g) or bool(oem_auth_ai)
    req["oem_brands"] = _brands(title_text)
    req["oem_turnover_lakh"] = v("oem_turnover_lakh")
    if gem.oem_authorisation_required(g):
        clauses["oem"] = _gem_clause(g.get("documents_required"), r"OEM Authori[sz]ation Certificate")
    elif oem_auth_ai:
        clauses["oem"] = ai_clause(oem_auth_ai[0])
    else:
        clauses["oem"] = None

    # ---- EMD
    req["emd_required"] = v("emd_required")
    amount = v("emd_amount")
    if amount is None:
        c = next((c for c in ai_for("emd", ["requirement"]) if c.get("emd_rupees")), None)
        if c:
            amount = c["emd_rupees"]
            clauses["emd"] = ai_clause(c)
            if req["emd_required"] is None:
                req["emd_required"] = True
    req["emd_rupees"] = amount
    if not clauses.get("emd"):
        clauses["emd"] = _gem_clause(g.get("emd_amount") or g.get("emd_required"), r"[\d,]{3,}|Required\s*(Yes|No)")
    rule = g.get("emd_exemption_rule")
    if not rule:
        c = next((c for c in ai_for("emd", ["relaxation_condition", "relaxation_granted"])
                  if re.search(r"manufactur", c["quote"], re.I)), None)
        rule = {"label": c.get("heading") or "EMD exemption", "quote": c["quote"], "page": c["page"]} if c else None
    req["emd_exemption_clause"] = _clause(rule["label"], rule["quote"], rule["page"], "Traders are excluded") if rule else None

    # ---- additional validated clauses from Claude, attached to their criterion
    primary_quotes = {normalise((clauses.get(k) or {}).get("quote")) for k, _ in CRITERIA}
    for c in ai_ok:
        if normalise(c["quote"]) in primary_quotes:
            continue
        extra[c["criterion"]].append({"heading": c.get("heading") or "", "quote": c["quote"], "page": c["page"],
                                      "kind": c["kind"], "summary": c.get("summary", "")})

    # ---- conditions BidReady lists but does not decide
    if "past performance" in docs_req.lower():
        pct = v("past_performance_pct")
        conditions.append(f"Past performance: the bid asks for proof of past supplies"
                          + (f" of at least {pct}% of the bid quantity" if pct else
                             " of a share of the bid quantity (the percentage is printed in a non-text font on page "
                             f"{(g.get('documents_required') or {}).get('page', 1)}; read it in the PDF)")
                          + ". Not checked automatically.")
    if req["oem_turnover_lakh"]:
        conditions.append(f"OEM average turnover of at least Rs {req['oem_turnover_lakh']:g} L (last 3 years) applies to the "
                          "manufacturer of the offered product. Confirm with the OEM.")
    if v("traders_excluded"):
        conditions.append("MSE purchase preference: traders (resellers) are excluded; only the manufacturer/OEM of the "
                          "offered product or the service provider qualifies.")

    ministry = v("ministry") or meta.get("ministry") or ""
    org = v("organisation") or ""
    buyer = ", ".join(x for x in [org if org.lower() != "n/a" else "", ministry] if x) or (v("department") or "Buyer not stated")
    qty = v("quantity")
    closes = _iso_end(g, meta)
    today = datetime.now(timezone.utc).date().isoformat()
    tender = {
        "id": tid or ("u-" + secrets.token_hex(3)),
        "bid": v("bid_number") or meta.get("bid") or "Uploaded document",
        "title": (title_text or meta.get("items") or "Tender document")[:140] + (f" ({qty} units)" if qty and qty > 1 else ""),
        "buyer": buyer,
        "portal": "GeM" if is_gem else "Uploaded",
        "category": category,
        "value_lakh": round(v("estimated_value") / 100000, 2) if v("estimated_value") else None,
        "emd_lakh": round(amount / 100000, 4) if amount else (0 if req["emd_required"] is False else None),
        "closes": closes,
        "status": "open" if closes and closes >= today else ("closed" if closes else "unknown"),
        "pages": len(pages),
        "url": url,
        "docs": [{"name": "GeM bid document" if is_gem else "Tender document", "pages": len(pages),
                  "text": "image_only" if len(doc["image_only"]) == len(pages) else ("partial" if doc["image_only"] else "ok"),
                  "image_only_pages": doc["image_only"]}],
        "snippet": "; ".join(x for x in [
            f"Turnover >= Rs {req['turnover_lakh']:g} L" if req["turnover_lakh"] else "",
            f"{req['experience_years']} yr experience" if req["experience_years"] else "",
            f"EMD Rs {amount:,.0f}" if amount else ("No EMD" if req["emd_required"] is False else ""),
            "OEM authorisation" if req["oem_required"] else "",
        ] if x),
        "retrieved_at": meta.get("retrieved_at") or datetime.now(timezone.utc).isoformat(),
        "_pages": pages, "_gem": g, "_req": req, "clauses": clauses, "_extra": extra, "_conditions": conditions,
        "_is_gem": is_gem, "_log": log, "_ai_rejected": ai_bad,
    }
    return tender, log


def public_tender(t):
    out = {k: v for k, v in t.items() if not k.startswith("_")}
    out["clauses"] = {k: ({kk: vv for kk, vv in c.items()} if c else None) for k, c in (t.get("clauses") or {}).items()}
    return out

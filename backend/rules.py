"""Deterministic eligibility rules for real GeM bids. No LLM here: same tender + profile -> same result.

Each criterion is met / relaxed / not_met / unresolved, or na when the bid sets no such requirement.
A relaxation applies only if (a) the bid grants it, (b) the supplier's status matches, (c) the role qualifies
(MSE EMD exemption: manufacturers for goods, service providers for services, never traders), and (d) the proof
document is on file. A relaxation the terms explicitly deny is respected. If the evidence validator rejected a
clause, the criterion is unresolved whatever the rule would have said.
"""

from datetime import date

from .data import CATEGORY_KEYWORDS
from .pipeline import CRITERIA

RULE_VERSION = "2026.10-r4"

_EVIDENCE_RANK = {"declared": 0, "document": 1, "verified": 2}

SCOPE_NOTICE = ("Pre-screen of four eligibility criteria (turnover, experience, OEM authorisation, EMD) against the "
                "real bid document. Technical specifications, past-performance quantities, delivery, warranty and other "
                "conditions are not checked automatically. The bid document on GeM remains the source of truth.")


def L(v):
    return f"Rs {round(float(v), 2):g} L"


def rupees(v):
    v = float(v)
    s = f"{int(round(v)):,}" if v >= 1000 else f"{v:g}"
    # Indian grouping: 3,64,542
    n = str(int(round(v)))
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        head = ",".join([head[max(0, i - 2):i] for i in range(len(head), 0, -2)][::-1])
        s = head + "," + tail
    return "Rs " + s


def _weakest(items):
    levels = [i.get("evidence", "declared") for i in items] or ["declared"]
    return min(levels, key=lambda e: _EVIDENCE_RANK.get(e, 0))


def _has_doc(profile, name):
    name = name.lower()
    return any(name in d["name"].lower() and d.get("status") in ("valid", "expiring") for d in profile.get("documents", []))


def _similar(text, category):
    t = (text or "").lower()
    return any(k in t for k in CATEGORY_KEYWORDS.get(category, [category.lower()]))


def fy_of(iso):
    """Indian financial year label for a date: 2025-08-14 -> FY26 (Apr 2025 - Mar 2026)."""
    d = date.fromisoformat(iso[:10])
    return f"FY{(d.year + 1 if d.month >= 4 else d.year) % 100:02d}"


def _relax(req, profile, crit):
    """(status, label, proof_doc, reason) for an experience or turnover relaxation."""
    denial = req.get(f"relax_denied_{crit}")
    if denial:
        return "denied", None, None, f"the bid's terms deny it (p. {denial['page']})"
    for who, flag, key, doc in (("Startup", "dpiit", f"startup_relax_{crit}", "DPIIT recognition certificate"),
                                ("MSE", "udyam_mse", f"mse_relax_{crit}", "Udyam certificate")):
        r = req.get(key) or {}
        if r.get("granted") and profile.get(flag):
            label = f"{who} relaxation" + (f" ({r['extent']})" if r.get("extent") else "")
            if _has_doc(profile, doc):
                return "ok", label, doc, r.get("relaxed_to")
            return "no_proof", label, doc, f"the {doc} is not on file"
    granted = [w for w, k in (("startups", f"startup_relax_{crit}"), ("MSEs", f"mse_relax_{crit}"))
               if (req.get(k) or {}).get("granted")]
    if granted:
        return "status", None, None, f"the bid relaxes this only for {' and '.join(granted)}, which the supplier is not"
    if req.get(f"mse_relax_{crit}") or req.get(f"startup_relax_{crit}"):
        return "none", None, None, "the bid states no MSE or startup relaxation for this criterion"
    return "none", None, None, "the bid grants no relaxation for this criterion"


def _turnover(t, p):
    req = t["_req"]
    need = req.get("turnover_lakh")
    rows = sorted(p.get("turnover", []), key=lambda r: r["fy"])[-3:]
    avg = sum(r["value_lakh"] for r in rows) / len(rows) if rows else 0.0
    fact = (f"Average {L(avg)} over {' / '.join(r['fy'] for r in rows)}" if rows else "No turnover declared")
    out = {"supplier_fact": fact, "evidence": _weakest(rows), "docs": [], "next_steps": []}
    if need is None:
        out.update(status="na", requirement="No minimum bidder turnover in this bid",
                   rule_result="The bid details set no turnover threshold, so nothing to meet.")
        return out
    ca = _has_doc(p, "CA turnover certificate")
    out["requirement"] = f"Average annual turnover >= {L(need)} (last 3 financial years)"
    out["docs"].append({"name": "CA-certified turnover statement or audited balance sheets (last 3 FY)", "ok": ca})
    if not ca:
        out["next_steps"].append("Get a CA-certified turnover statement (with UDIN) for the last 3 financial years")
    if avg >= need:
        out.update(status="met", rule_result=f"{L(avg)} >= {L(need)} required.")
        return out
    rs, label, proof, extra = _relax(req, p, "turnover")
    if rs == "ok":
        out["docs"].append({"name": proof, "ok": True})
        out.update(status="relaxed", rule_result=f"{L(avg)} is below {L(need)}, but the bid grants {label} and the {proof} is on file.")
        out["next_steps"].append(f"Upload the {proof} with the bid; relaxation is subject to meeting quality and technical specifications")
        return out
    if rs == "no_proof":
        out["docs"].append({"name": proof, "ok": False})
        out["next_steps"].append(f"Add the {proof} to claim {label}")
    out.update(status="not_met", rule_result=f"Short by {L(need - avg)}; no relaxation applies because {extra}.",
               gap="Turnover below requirement")
    if rs != "no_proof":
        out["next_steps"].append(f"Average turnover must be {L(need - avg)} higher; look for bids with a lower threshold")
    return out


def _experience(t, p):
    req, cat = t["_req"], t["category"]
    need = req.get("experience_years")
    similar = [o for o in p.get("orders", []) if _similar(o.get("item"), cat) and o.get("date")]
    fys = sorted({fy_of(o["date"]) for o in similar})
    fact = (f"Supplied similar {cat.lower()} in {len(fys)} financial year(s): {', '.join(fys)}" if fys
            else f"No similar {cat.lower()} supplies recorded")
    out = {"supplier_fact": fact, "evidence": _weakest(similar), "docs": [], "next_steps": []}
    if need is None:
        if req.get("experience_docs_listed"):
            out.update(status="unresolved", requirement="Experience documents requested, but no number of years stated",
                       rule_result="The bid lists 'Experience Criteria' under documents required without a years field; "
                                   "the requirement must be read from the bid's terms.",
                       gap="Experience requirement not stated")
            out["next_steps"].append("Read the bid's Additional Terms and Conditions for the experience requirement")
            return out
        out.update(status="na", requirement="No years-of-experience filter in this bid",
                   rule_result="The bid applies no past-experience filter.")
        return out
    out["requirement"] = (f"Supplied similar {cat.lower()} to Central/State Govt or PSU in {need} financial year(s) "
                          "before bid opening")
    certs = bool(similar) and all(o.get("evidence") != "declared" for o in similar)
    out["docs"].append({"name": "Contracts and delivery acceptance certificates (e.g. CRAC) for each financial year", "ok": certs})
    declared = [o for o in similar if o.get("evidence") == "declared"]
    if declared:
        out["next_steps"].append(f"Upload the completion certificate for {declared[0]['buyer']} (currently declared only)")
    if len(fys) >= need:
        out.update(status="met", rule_result=f"{len(fys)} financial year(s) with supplies >= {need} required.")
        return out
    rs, label, proof, relaxed_to = _relax(req, p, "experience")
    if rs == "ok" and (relaxed_to is None or len(fys) >= relaxed_to):
        out["docs"].append({"name": proof, "ok": True})
        part = f" (partial: reduced to {relaxed_to:g} year)" if relaxed_to else ""
        out.update(status="relaxed", rule_result=f"{len(fys)} of {need} years, covered by {label}{part}; {proof} on file.")
        out["next_steps"].append(f"Upload the {proof} with the bid; relaxation is subject to meeting quality and technical specifications")
        return out
    short = need - len(fys)
    reason = relaxed_to if isinstance(relaxed_to, str) else (
        f"even the partial relaxation needs {relaxed_to:g} year(s)" if rs == "ok" else "")
    out.update(status="not_met", rule_result=f"{short} financial year(s) short of the {need} required"
                                             + (f"; no relaxation applies because {reason}." if reason else "."),
               gap="Too few years of similar supply")
    out["next_steps"].append(f"Need supplies of {cat.lower()} in {short} more financial year(s), or a bid with a lower experience filter")
    if rs == "no_proof":
        out["docs"].append({"name": proof, "ok": False})
        out["next_steps"].append(f"Add the {proof} to claim {label}")
    return out


def _oem(t, p):
    req, cat = t["_req"], t["category"]
    out = {"evidence": "declared", "docs": [], "next_steps": []}
    if not req.get("oem_required"):
        out.update(status="na", requirement="No OEM authorisation listed in this bid",
                   supplier_fact=f"{len(p.get('oem_letters', []))} OEM letter(s) on file",
                   rule_result="The bid's 'documents required' list does not include an OEM authorisation.")
        return out
    brands = req.get("oem_brands") or []
    brand_txt = " / ".join(brands) if brands else "the OEM of the offered product"
    out["requirement"] = f"OEM authorisation certificate from {brand_txt} for the offered {cat.lower()}"
    if p.get("role") == "manufacturer" and any(_similar(o.get("scope"), cat) for o in p.get("oem_letters", [])):
        own = next(o for o in p["oem_letters"] if _similar(o.get("scope"), cat))
        out.update(status="met", evidence=own.get("evidence", "declared"),
                   supplier_fact=f"Supplier is the manufacturer ({own['brand']}, scope: {own['scope']}).",
                   rule_result="A manufacturer bidding its own product authorises itself.")
        out["docs"].append({"name": "Manufacturer / OEM registration on GeM for the offered product", "ok": True})
        return out
    letters = [o for o in p.get("oem_letters", []) if not brands or o["brand"].lower() in [b.lower() for b in brands]]
    covering = [o for o in letters if _similar(o.get("scope"), cat)]
    closes = t.get("closes") or "9999-12-31"
    valid = [o for o in covering if (o.get("valid_until") or "9999") >= closes]
    if valid:
        o = valid[0]
        out.update(status="met", evidence=o.get("evidence", "declared"),
                   supplier_fact=f"{o['brand']} letter on file, scope: {o['scope']}, valid until {o['valid_until']}.",
                   rule_result=f"Brand and scope cover {cat.lower()}; valid past bid close ({closes}).")
        out["docs"].append({"name": f"{o['brand']} authorisation naming this bid and the offered model", "ok": o.get("evidence") != "declared"})
        out["next_steps"].append("GeM expects a bid-specific authorisation: ask the OEM for a letter naming this bid number")
        return out
    if covering:
        o = covering[0]
        out.update(status="not_met", evidence=o.get("evidence", "declared"),
                   supplier_fact=f"{o['brand']} letter on file but it expires {o['valid_until']}.",
                   rule_result=f"Letter expires before the bid closes ({closes}).", gap="OEM letter expires before bid close")
        out["docs"].append({"name": f"Renewed {o['brand']} authorisation", "ok": False})
        out["next_steps"].append(f"Renew the {o['brand']} authorisation before {closes}")
        return out
    have = ", ".join(f"{o['brand']} ({o['scope']})" for o in p.get("oem_letters", [])) or "none"
    if brands and letters:  # the named brand's letter exists, but its scope does not clearly cover this item
        o = letters[0]
        out.update(status="unresolved", evidence=o.get("evidence", "declared"),
                   supplier_fact=f"{o['brand']} letter on file, but its scope is \"{o['scope']}\".",
                   rule_result=f"Letter scope does not clearly cover {cat.lower()}; confirm with the OEM.",
                   gap="OEM letter scope unclear")
        out["next_steps"].append(f"Ask {o['brand']} for a letter covering {cat.lower()} and naming this bid")
        return out
    out.update(status="not_met", supplier_fact=f"No authorisation covering {cat.lower()}" + (f" from {brand_txt}" if brands else "")
                                                + f" (has: {have}).",
               rule_result=f"Required OEM authorisation for {cat.lower()} is missing.", gap="Missing OEM authorisation")
    out["docs"].append({"name": f"OEM authorisation for {cat.lower()}", "ok": False})
    out["next_steps"].append(f"Obtain a bid-specific authorisation from {brand_txt}")
    return out


def _emd(t, p):
    req = t["_req"]
    funds, role = p.get("emd_funds_lakh", 0) * 100000, p.get("role")
    out = {"supplier_fact": f"{rupees(funds)} available for EMD" + ("; Udyam MSE" if p.get("udyam_mse") else "")
                            + ("; DPIIT startup" if p.get("dpiit") else "") + f"; role: {role.replace('_', ' ')}",
           "evidence": "declared", "docs": [], "next_steps": []}
    need = req.get("emd_rupees")
    if req.get("emd_required") is False:
        out.update(status="met", requirement="No EMD required in this bid",
                   rule_result="The bid details state EMD is not required.")
        return out
    if req.get("emd_required") is None and need is None:
        out.update(status="unresolved", requirement="EMD details not found in the document",
                   rule_result="Neither the EMD detail nor an amount could be read.", gap="EMD terms not found")
        out["next_steps"].append("Check the EMD detail section of the bid on GeM")
        return out
    out["requirement"] = f"EMD of {rupees(need)}" if need else "EMD required (amount not stated)"
    rule = req.get("emd_exemption_clause")
    note = ""
    if p.get("udyam_mse") or p.get("dpiit"):
        if rule:
            if p.get("dpiit") and _has_doc(p, "DPIIT recognition certificate"):
                out["docs"].append({"name": "DPIIT recognition certificate", "ok": True})
                out.update(status="relaxed", evidence="document",
                           rule_result="EMD exempted for a DPIIT-recognised startup under the bid's EMD exemption clause (relevant category as per GeM GTC); certificate on file.")
                out["next_steps"].append("Upload the DPIIT certificate in the EMD exemption field")
                return out
            if p.get("udyam_mse") and role in ("manufacturer", "service_provider"):
                if _has_doc(p, "Udyam certificate"):
                    out["docs"].append({"name": "Udyam certificate listing the offered item", "ok": True})
                    out.update(status="relaxed", evidence="document",
                               rule_result=f"EMD exempted: MSE {role.replace('_', ' ')}, the bid's clause grants it, Udyam on file.")
                    out["next_steps"].append("The Udyam certificate must list the offered product; upload it in place of EMD")
                    return out
                note = " MSE exemption needs the Udyam certificate, which is not on file."
                out["docs"].append({"name": "Udyam certificate", "ok": False})
            elif p.get("udyam_mse"):
                note = (f" MSE exemption does not apply: the bid limits it to manufacturers for goods and service providers"
                        f" for services, and traders are excluded (p. {rule['page']}).")
        else:
            note = " The bid states no EMD exemption clause, so none is assumed."
    if need is not None and funds >= need:
        out["docs"].append({"name": f"EMD of {rupees(need)} (GeM EMD / bank guarantee as per bid)", "ok": True})
        out.update(status="met", rule_result=f"Can furnish {rupees(need)} from {rupees(funds)} available.{note}")
        return out
    if need is None:
        out.update(status="unresolved", rule_result="EMD is required but the amount is not readable." + note,
                   gap="EMD amount not stated")
        return out
    out["docs"].append({"name": f"EMD of {rupees(need)} (GeM EMD / bank guarantee as per bid)", "ok": False})
    out.update(status="not_met", rule_result=f"Short of the {rupees(need)} EMD by {rupees(need - funds)}.{note}",
               gap="Reseller excluded from MSE EMD exemption" if "traders are excluded" in note else "EMD shortfall")
    out["next_steps"].append(f"Arrange {rupees(need - funds)} more or a bank guarantee of {rupees(need)} before {t.get('closes')}")
    if "traders are excluded" in note:
        out["next_steps"].append("Udyam registration alone does not exempt a reseller; do not claim the exemption")
    return out


_RULES = {"turnover": _turnover, "experience": _experience, "oem": _oem, "emd": _emd}


def verdict_of(statuses):
    s = [x for x in statuses if x != "na"]
    if "not_met" in s:
        return "not_eligible"
    if "unresolved" in s:
        return "manual_review"
    if "relaxed" in s:
        return "eligible_relaxation"
    return "eligible"


def evaluate(tender, profile, validations):
    """validations: {key: (validation dict, reason or None)} from pipeline.run_validation."""
    criteria, coverage = [], 0
    extra = tender.get("_extra") or {}
    for key, name in CRITERIA:
        validation, reason = validations[key]
        clause = (tender.get("clauses") or {}).get(key)
        c = _RULES[key](tender, profile)
        if reason and c["status"] != "na":
            c["status"] = "unresolved"
            c["rule_result"] = f"Evidence could not be validated ({reason}), so no rule result is issued."
            c["gap"] = f"{name}: evidence not verifiable"
            c["next_steps"].insert(0, f"Read page {clause.get('page')} of the bid document and confirm the requirement")
        elif c["status"] == "na" or (clause and not reason):
            coverage += 1
        elif not clause and c["status"] not in ("unresolved",):
            coverage += 1  # e.g. EMD "not required" read from the bid details
        cl = clause or {}
        criteria.append({
            "key": key, "name": name, "status": c["status"], "requirement": c["requirement"],
            "supplier_fact": c["supplier_fact"], "evidence": c["evidence"], "rule_result": c["rule_result"],
            "clause": {"heading": cl.get("heading") or ("Not in this bid" if c["status"] == "na" else "Not found in document"),
                       "quote": cl.get("quote", ""), "highlight": cl.get("highlight", ""), "page": cl.get("page"),
                       "doc": cl.get("doc", ""), "url": tender.get("url", ""), "source": cl.get("source")},
            "validation": validation, "docs": c["docs"], "next_steps": c["next_steps"],
            "more_clauses": extra.get(key, [])[:4],
            "_gap": c.get("gap") if c["status"] in ("not_met", "unresolved") else None,
        })
    statuses = [c["status"] for c in criteria]
    missing = []
    for c in criteria:
        for d in c["docs"]:
            if not d["ok"] and d["name"] not in missing:
                missing.append(d["name"])
    unresolved = [f"{c['name']}: {c['rule_result']}" for c in criteria if c["status"] == "unresolved"]
    return {
        "verdict": verdict_of(statuses),
        "coverage": coverage,
        "criteria": criteria,
        "missing_docs": missing,
        "unresolved": unresolved + list(tender.get("_conditions") or []),
        "scope_notice": SCOPE_NOTICE,
    }

"""Deterministic eligibility rules. No LLM here: same tender + profile -> same result.

Each criterion is met / relaxed / not_met / unresolved. A relaxation applies only if
  (a) the tender grants it, (b) the supplier's status matches, (c) the role qualifies
  (MSE EMD exemption: manufacturer or service_provider only, never reseller), and
  (d) the proof document is on file.
A tender that explicitly denies relaxation is respected. If the evidence validator
rejected a clause, the criterion is unresolved whatever the rule would have said.
"""

from .data import CATEGORY_KEYWORDS
from .pipeline import CRITERIA

RULE_VERSION = "2026.10-r3"

_EVIDENCE_RANK = {"declared": 0, "document": 1, "verified": 2}

SCOPE_NOTICE = ("Pre-screen of four eligibility criteria only (turnover, experience, OEM authorisation, EMD). "
                "Technical specifications, delivery, warranty and other certifications are outside automated checks. "
                "The tender document remains the source of truth.")


def L(v):
    v = round(float(v), 2)
    return f"Rs {v:g} L"


def _weakest(items):
    levels = [i.get("evidence", "declared") for i in items] or ["declared"]
    return min(levels, key=lambda e: _EVIDENCE_RANK.get(e, 0))


def _has_doc(profile, name):
    name = name.lower()
    return any(name in d["name"].lower() and d.get("status") in ("valid", "expiring")
               for d in profile.get("documents", []))


def _similar(text, category):
    t = (text or "").lower()
    return any(k in t for k in CATEGORY_KEYWORDS.get(category, [category.lower()]))


def _relaxation(req, profile):
    """Turnover/experience relaxation for this tender + profile: (status, label, proof_doc, reason)."""
    if req.get("relaxation_denied"):
        return "denied", None, None, "the tender explicitly says turnover/experience exemption is NOT available to startups or MSEs"
    if req.get("startup_relax") and profile.get("dpiit"):
        if _has_doc(profile, "DPIIT recognition certificate"):
            return "ok", "DPIIT startup relaxation", "DPIIT recognition certificate", None
        return "no_proof", "DPIIT startup relaxation", "DPIIT recognition certificate", "the DPIIT recognition certificate is not on file"
    if req.get("mse_relax") and profile.get("udyam_mse"):
        if _has_doc(profile, "Udyam certificate"):
            return "ok", "MSE relaxation", "Udyam certificate", None
        return "no_proof", "MSE relaxation", "Udyam certificate", "the Udyam certificate is not on file"
    granted = [n for n, k in (("startups", "startup_relax"), ("MSEs", "mse_relax")) if req.get(k)]
    if granted:
        return "status", None, None, f"the tender relaxes this only for {' and '.join(granted)}, which the supplier is not"
    return "none", None, None, "the tender grants no relaxation for this criterion"


def _turnover(tender, profile):
    req = tender["_req"]
    need = req.get("turnover_lakh")
    rows = sorted(profile.get("turnover", []), key=lambda r: r["fy"])[-3:]
    avg = sum(r["value_lakh"] for r in rows) / len(rows) if rows else 0.0
    fact = (f"Average {L(avg)} over {' / '.join(r['fy'] for r in rows)} "
            f"({', '.join(L(r['value_lakh']) for r in rows)})") if rows else "No turnover declared"
    ca = _has_doc(profile, "CA turnover certificate")
    docs = [{"name": "CA turnover certificate (last 3 FY, with UDIN)", "ok": ca}]
    out = {"requirement": f"Average annual turnover >= {L(need)} (last 3 financial years)",
           "supplier_fact": fact, "evidence": _weakest(rows), "docs": docs, "next_steps": []}
    if not ca:
        out["next_steps"].append("Get a CA-certified turnover statement with UDIN for the last 3 financial years")
    if avg >= need:
        out.update(status="met", rule_result=f"{L(avg)} >= {L(need)} required.")
        return out
    rs, label, proof, reason = _relaxation(req, profile)
    if rs == "ok":
        docs.append({"name": proof, "ok": True})
        out.update(status="relaxed", rule_result=f"{L(avg)} is below {L(need)}, but the tender grants {label} and proof is on file.")
        out["next_steps"].append(f"Upload the {proof} with the bid; the relaxation is subject to meeting technical specifications")
        return out
    if rs == "no_proof":
        docs.append({"name": proof, "ok": False})
    out.update(status="not_met", rule_result=f"Short by {L(need - avg)}; relaxation does not apply because {reason}.",
               gap="Turnover below requirement")
    if rs == "no_proof":
        out["next_steps"].append(f"Add the {proof} to claim {label}")
    else:
        out["next_steps"].append(f"Average turnover must rise by {L(need - avg)}; consider a consortium or a smaller tender")
    return out


def _experience(tender, profile):
    req = tender["_req"]
    n_req, min_val, cat = req.get("orders_required", 1), req.get("order_min_lakh", 0), tender["category"]
    similar = [o for o in profile.get("orders", []) if _similar(o.get("item"), cat)]
    qualifying = [o for o in similar if o["value_lakh"] >= min_val]
    too_small = [o for o in similar if o["value_lakh"] < min_val]
    fact = f"{len(qualifying)} similar order(s) >= {L(min_val)}"
    if too_small:
        fact += f"; {len(too_small)} more similar but below value ({', '.join(L(o['value_lakh']) for o in too_small)})"
    certs = all(o.get("evidence") != "declared" for o in qualifying) and bool(qualifying)
    docs = [{"name": f"{n_req} purchase order(s) with completion certificates", "ok": len(qualifying) >= n_req and certs}]
    out = {"requirement": f"At least {n_req} similar {cat.lower()} order(s), each >= {L(min_val)}",
           "supplier_fact": fact, "evidence": _weakest(qualifying), "docs": docs, "next_steps": []}
    declared = [o for o in qualifying if o.get("evidence") == "declared"]
    if declared:
        out["next_steps"].append(f"Upload the completion certificate for {declared[0]['buyer']} (currently declared only)")
    if len(qualifying) >= n_req:
        out.update(status="met", rule_result=f"{len(qualifying)} >= {n_req} required.")
        return out
    rs, label, proof, reason = _relaxation(req, profile)
    if rs == "ok":
        docs.append({"name": proof, "ok": True})
        out.update(status="relaxed", rule_result=f"{len(qualifying)} of {n_req} orders, covered by {label} (proof on file).")
        return out
    short = n_req - len(qualifying)
    out.update(status="not_met", rule_result=f"{short} order(s) short of the {n_req} required; relaxation does not apply because {reason}.",
               gap="Too few similar orders")
    out["next_steps"].append(f"Need {short} more similar order{'s' if short > 1 else ''} >= {L(min_val)}")
    if rs == "no_proof":
        docs.append({"name": proof, "ok": False})
        out["next_steps"].append(f"Add the {proof} to claim {label}")
    return out


def _oem(tender, profile):
    req, cat = tender["_req"], tender["category"]
    brands = req.get("oem_brands") or []
    letters = [o for o in profile.get("oem_letters", []) if o["brand"].lower() in [b.lower() for b in brands]]
    covering = [o for o in letters if _similar(o.get("scope"), cat)]
    valid = [o for o in covering if (o.get("valid_until") or "9999") >= tender.get("closes", "")]
    brand_txt = " / ".join(brands) or "the OEM"
    out = {"requirement": f"OEM authorisation from {brand_txt} for the offered {cat.lower()} model",
           "evidence": "declared", "docs": [], "next_steps": []}
    if valid:
        o = valid[0]
        out.update(status="met", supplier_fact=f"{o['brand']} letter on file, scope: {o['scope']}, valid until {o['valid_until']}.",
                   evidence=o.get("evidence", "declared"),
                   rule_result=f"Brand and scope match the tender category ({cat}); valid past bid close.")
        out["docs"].append({"name": f"{o['brand']} authorisation naming the offered model", "ok": o.get("evidence") != "declared"})
        out["next_steps"].append("OEM letter must name the offered model and this bid number")
        return out
    if covering:
        o = covering[0]
        out.update(status="not_met", supplier_fact=f"{o['brand']} letter on file but it expires {o['valid_until']}.",
                   evidence=o.get("evidence", "declared"),
                   rule_result=f"Letter expires before the bid closes ({tender.get('closes')}).", gap="OEM letter expired")
        out["docs"].append({"name": f"Renewed {o['brand']} authorisation", "ok": False})
        out["next_steps"].append(f"Renew the {o['brand']} authorisation before {tender.get('closes')}")
        return out
    if letters:
        o = letters[0]
        out.update(status="unresolved", supplier_fact=f"{o['brand']} letter on file, but its scope is \"{o['scope']}\".",
                   evidence=o.get("evidence", "declared"),
                   rule_result=f"Letter scope does not clearly cover {cat}; confirm with the OEM.", gap="OEM letter scope unclear")
        out["docs"].append({"name": f"{o['brand']} authorisation covering {cat.lower()}", "ok": False})
        out["next_steps"].append(f"Ask {o['brand']} for a letter whose scope covers {cat.lower()} and names the offered model")
        return out
    have = ", ".join(o["brand"] for o in profile.get("oem_letters", [])) or "none"
    out.update(status="not_met", supplier_fact=f"No {brand_txt} authorisation on file (has: {have}).",
               rule_result=f"Required {brand_txt} authorisation missing.", gap="Missing OEM authorisation")
    out["docs"].append({"name": f"{brand_txt} authorisation", "ok": False})
    out["next_steps"].append(f"Obtain an authorisation from {brand_txt} naming the offered model")
    return out


def _emd(tender, profile):
    req = tender["_req"]
    need, funds, role = req.get("emd_lakh", 0), profile.get("emd_funds_lakh", 0), profile.get("role")
    roles = req.get("emd_exempt_roles") or []
    out = {"requirement": f"EMD of {L(need)}" + (f" (MSE exemption for {', '.join(r.replace('_', ' ') + 's' for r in roles)})"
                                                 if req.get("emd_exempt_mse") else ""),
           "supplier_fact": f"{L(funds)} available for EMD" + ("; Udyam MSE" if profile.get("udyam_mse") else "")
                            + f"; role: {role.replace('_', ' ')}",
           "evidence": "declared", "docs": [], "next_steps": []}
    note = ""
    if req.get("emd_exempt_mse") and profile.get("udyam_mse"):
        if role in roles:
            if _has_doc(profile, "Udyam certificate"):
                out["docs"].append({"name": "Udyam certificate covering the tendered item", "ok": True})
                out.update(status="relaxed", evidence="document",
                           rule_result=f"EMD of {L(need)} exempted: MSE {role.replace('_', ' ')}, tender grants the exemption, Udyam on file.")
                out["next_steps"].append("Udyam certificate must list the tendered item; upload it in place of EMD")
                return out
            note = " MSE exemption needs the Udyam certificate, which is not on file."
            out["docs"].append({"name": "Udyam certificate", "ok": False})
        else:
            note = (f" MSE exemption does not apply: the tender limits it to {' / '.join(r.replace('_', ' ') + 's' for r in roles)},"
                    f" and the supplier is a {role.replace('_', ' ')}.")
    if funds >= need:
        out["docs"].append({"name": f"EMD of {L(need)} (GeM EMD module or bank guarantee)", "ok": True})
        out.update(status="met", rule_result=f"Can furnish EMD of {L(need)} from {L(funds)} available.{note}")
        return out
    out["docs"].append({"name": f"EMD of {L(need)} (GeM EMD module or bank guarantee)", "ok": False})
    out.update(status="not_met", rule_result=f"Short of the {L(need)} EMD by {L(need - funds)}.{note}",
               gap="Reseller excluded from MSE EMD exemption" if note and "does not apply" in note else "EMD shortfall")
    out["next_steps"].append(f"Arrange {L(need - funds)} more, or a bank guarantee of {L(need)}, before {tender.get('closes')}")
    if "does not apply" in note:
        out["next_steps"].append("Udyam registration alone does not exempt a reseller; do not claim the exemption")
    return out


_RULES = {"turnover": _turnover, "experience": _experience, "oem": _oem, "emd": _emd}


def verdict_of(statuses):
    if "not_met" in statuses:
        return "not_eligible"
    if "unresolved" in statuses:
        return "manual_review"
    if "relaxed" in statuses:
        return "eligible_relaxation"
    return "eligible"


def evaluate(tender, profile, validations):
    """validations: {key: (validation dict, reason or None)} from pipeline.run_validation."""
    criteria, coverage = [], 0
    for key, name in CRITERIA:
        validation, reason = validations[key]
        clause = (tender.get("clauses") or {}).get(key) or {}
        c = _RULES[key](tender, profile)
        if reason:
            c["status"] = "unresolved"
            c["rule_result"] = f"Evidence could not be validated ({reason}), so no rule result is issued."
            c["gap"] = f"{name}: evidence not verifiable"
            c["next_steps"] = [f"Read {clause.get('heading') or 'the ' + name.lower() + ' clause'}"
                               f"{' on p. ' + str(clause['page']) if clause.get('page') else ''} manually and confirm the requirement"] + c["next_steps"]
            if key == "oem" and clause:
                c["next_steps"].insert(1, "OEM letter must name the offered model")
        else:
            coverage += 1
        criteria.append({
            "key": key, "name": name, "status": c["status"], "requirement": c["requirement"],
            "supplier_fact": c["supplier_fact"], "evidence": c["evidence"], "rule_result": c["rule_result"],
            "clause": {"heading": clause.get("heading", "Not found in document"), "quote": clause.get("quote", ""),
                       "highlight": clause.get("highlight", ""), "page": clause.get("page"),
                       "doc": clause.get("doc", ""), "url": tender.get("url", "")},
            "validation": validation, "docs": c["docs"], "next_steps": c["next_steps"],
            "_gap": c.get("gap") if c["status"] in ("not_met", "unresolved") else None,
        })
    statuses = [c["status"] for c in criteria]
    missing = []
    for c in criteria:
        for d in c["docs"]:
            if not d["ok"] and d["name"] not in missing:
                missing.append(d["name"])
    return {
        "verdict": verdict_of(statuses),
        "coverage": coverage,
        "criteria": criteria,
        "missing_docs": missing,
        "unresolved": [f"{c['name']}: {c['rule_result']}" for c in criteria if c["status"] == "unresolved"],
        "scope_notice": SCOPE_NOTICE,
    }

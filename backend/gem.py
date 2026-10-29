"""Real tender documents: PDF text per page, and a parser for the standard GeM bid-document template.

GeM bids print every field as "/Label" followed by its value, in English and Hindi. We keep the English,
drop layout debris, and return each field with the exact quote and page it came from, so the evidence
validator can check it against the same text.
"""

import io
import re

import pypdf

DEVANAGARI = re.compile(r"[ऀ-ॿ]+")
IMAGE_ONLY_CHARS = 40          # a page with less extractable text than this is treated as a scan


def _is_debris(line):
    """Layout leftovers such as "& &", "67 67", "( (" or "*": no word of three letters, and repeated or symbolic."""
    toks = line.split()
    if not toks:
        return True
    if any(re.search(r"[A-Za-z]{3}", t) for t in toks):
        return False
    if len(toks) == 1:
        return not re.search(r"\w", toks[0])
    return all(len(t) <= 3 for t in toks)


def clean_page(raw):
    text = DEVANAGARI.sub("", raw or "")
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line in ("/", "") or _is_debris(line.strip("/ ")):
            continue
        lines.append(line)
    text = " ".join(lines)
    # Inline debris: doubled glyph pairs such as "67 67", "R% R%", ">8 >8" printed by the bilingual layout.
    text = re.sub(r"(?<!\S)(\S{1,3}) \1(?!\S)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def read_pdf(data):
    """-> {"pages": [clean text per page], "image_only": [page numbers], "chars": int}"""
    reader = pypdf.PdfReader(io.BytesIO(data))
    pages, image_only = [], []
    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - a single broken page must not sink the document
            raw = ""
        clean = clean_page(raw)
        if len(clean) < IMAGE_ONLY_CHARS:
            image_only.append(i)
        pages.append(clean)
    return {"pages": pages, "image_only": image_only, "chars": sum(len(p) for p in pages)}


def is_gem(pages):
    head = " ".join(pages[:2])
    return bool(re.search(r"Bid Number\s*:?\s*GEM/\d{4}/B/\d+", head)) or ("EMD Detail" in head and "Item Category" in head)


# ---------------------------------------------------------------- field extraction

def _find(pages, pattern, flags=re.I):
    """First match across pages -> (match, page_no) or (None, None)."""
    rx = re.compile(pattern, flags)
    for no, text in enumerate(pages, start=1):
        m = rx.search(text)
        if m:
            return m, no
    return None, None


def _field(pages, label, pattern, conv=lambda m: m.group(1).strip()):
    m, page = _find(pages, pattern)
    if not m:
        return None
    return {"label": label, "value": conv(m), "quote": m.group(0).strip(" /"), "page": page}


def _num(s):
    return float(s.replace(",", ""))


def _text_after(pages, label, nxt):
    """Free-text value between a label and the next label, e.g. Organisation Name."""
    return _field(pages, label, rf"{label}\s+(.+?)\s*/\s*(?:{nxt})")


RELAX_RX = re.compile(
    r"(MSE|Startup)\s+(?:Relaxation|Exemption)\s+for\s+(Years\s+of\s+Experience\s+and\s+Turnover|Years\s+of\s+Experience|Turnover)"
    r"\s*(Yes|No)(?:\s*\|?\s*(Partial|Complete|Full)(?:\s*\|\s*[A-Za-z]+\s*-\s*[\d.]+\s*(?:year|lakh)\s*\(?s?\)?)?)?", re.I)


def _relaxations(pages):
    """MSE / Startup relaxation flags for experience and turnover. Layouts seen on GeM:
    "MSE Relaxation for Years Of Experience Yes | Partial | Experience - 1 year (s)", "MSE Relaxation for Turnover Yes
    Complete", and older "MSE Exemption for Years Of Experience and Turnover Yes"."""
    out = {}
    for no, text in enumerate(pages, start=1):
        for m in RELAX_RX.finditer(text):
            who = m.group(1).lower() if m.group(1).lower() == "mse" else "startup"
            scope = m.group(2).lower()
            targets = ["experience", "turnover"] if "and turnover" in scope else (["turnover"] if scope == "turnover" else ["experience"])
            val = {"granted": m.group(3).lower() == "yes", "extent": (m.group(4) or "").lower() or None}
            for what in targets:
                out.setdefault(f"{who}_relax_{what}", {"label": f"{m.group(1)} relaxation ({what})", "value": val,
                                                      "quote": m.group(0).strip(), "page": no})
    return out


def parse_gem(pages):
    """Extract the GeM template fields. Missing fields are None; nothing is guessed."""
    g = {}
    g["bid_number"] = _field(pages, "Bid Number", r"Bid Number\s*:?\s*(GEM/\d{4}/B/\d+)")
    g["dated"] = _field(pages, "Dated", r"Dated\s*:?\s*(\d{2}-\d{2}-\d{4})")
    g["bid_end"] = _field(pages, "Bid End Date/Time", r"Bid End Date/Time\s*(\d{2}-\d{2}-\d{4}(?:\s+\d{2}:\d{2}:\d{2})?)")
    g["ministry"] = _text_after(pages, "Ministry/State Name", "Department Name")
    g["department"] = _text_after(pages, "Department Name", "Organisation Name")
    g["organisation"] = _text_after(pages, "Organisation Name", "Office Name")
    g["office"] = _text_after(pages, "Office Name", "Total Quantity|Item Category|Buyer")
    g["quantity"] = _field(pages, "Total Quantity", r"Total Quantity\s*([\d,]+)", lambda m: int(_num(m.group(1))))
    g["item_category"] = _field(pages, "Item Category", r"Item Category\s+(.+?)\s*(?:/\s*[A-Z]|\*|$)")
    g["estimated_value"] = _field(pages, "Estimated Bid Value", r"Estimated Bid Value\s*([\d,]+(?:\.\d+)?)",
                                  lambda m: _num(m.group(1)))

    # Turnover: "Minimum Average Annual Turnover of the bidder (For 3 Years) 9 Lakh (s)"; may be in Crore.
    def lakh(m):
        v = _num(m.group(1))
        return v * 100 if m.group(2).lower().startswith("crore") else v
    g["turnover_lakh"] = _field(pages, "Minimum Average Annual Turnover of the bidder",
                                r"Minimum Average Annual Turnover of the\s*bidder(?:\s*\(For[^)]{0,40}\))?\s*([\d,.]+)\s*(Lakh|Crore)\s*\(?s?\)?", lakh)
    g["oem_turnover_lakh"] = _field(pages, "OEM Average Turnover (Last 3 Years)",
                                    r"OEM Average Turnover\s*\(Last 3 Years\)\s*([\d,.]+)\s*(Lakh|Crore)\s*\(?s?\)?", lakh)
    g["experience_years"] = _field(pages, "Years of Past Experience Required",
                                   r"Years of Past Experience Required(?:\s*for\s*same/similar\s*service)?\s*(\d+)\s*Year\s*\(?s?\)?",
                                   lambda m: int(m.group(1)))
    # The percentage is often printed in a glyph font that does not extract as text; keep only what is readable.
    g["past_performance_pct"] = _field(pages, "Past Performance", r"Past Performance\s*(\d+)\s*%", lambda m: int(m.group(1)))
    for k in ("mse_relax_experience", "startup_relax_experience", "mse_relax_turnover", "startup_relax_turnover"):
        g[k] = None
    g.update(_relaxations(pages))
    g["documents_required"] = _field(pages, "Document required from seller",
                                     r"Document required from seller\s+(.+?)(?=\s*\*In case|\s*/\s*Do you want|\s*/?\s*Bid Number|$)")

    # EMD: "EMD Detail / Required No" when none is due; otherwise GeM prints the advisory bank and "EMD Amount 30000".
    # Multi-schedule bids print "Schedule 1 EMD Amount (In INR) 28000 Schedule 2 ..."; the first schedule is used.
    g["emd_amount"] = _field(pages, "EMD Amount", r"EMD Amount\s*(?:\(In INR\))?\s*([\d,]+(?:\.\d+)?)", lambda m: _num(m.group(1)))
    g["emd_required"] = _field(pages, "EMD Detail", r"EMD Detail\s*(?:\S\s*)?/?\s*Required\s*(Yes|No)",
                               lambda m: m.group(1).lower() == "yes")
    if g["emd_required"] is None and g["emd_amount"]:
        g["emd_required"] = dict(g["emd_amount"], label="EMD Detail", value=True)
    g["emd_exemption_rule"] = _field(pages, "EMD Exemption",
                                     r"(Under MSE category,\s*only manufacturers for goods and Service Providers for Services are\s*eligible for exemption from EMD\.?\s*Traders are excluded[^.]*\.?)")
    g["traders_excluded"] = _field(pages, "MSE purchase preference",
                                   r"(Traders are excluded from the purview of Public Procurement Policy for Micro and Small Enterprises[^.]*\.)")
    return g


def oem_authorisation_required(g):
    docs = (g.get("documents_required") or {}).get("value", "")
    return "oem authori" in docs.lower()

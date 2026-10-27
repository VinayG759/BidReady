"""Synthetic but realistic data: tenders (with full source text), supplier profiles.

Everything here is invented for the demo (mode "synthetic"). Each tender carries:
  - the public fields of the API contract (Tender)
  - clauses: what the extractor "found" (heading, quote, highlight, page, doc)
  - _req: the structured requirement values the extractor produced
  - _source: the retrieved body text per document (what TinyFish fetch returned)
  - _headings: the heading list per document
The validator in pipeline.py checks clauses against _source/_headings; rules.py
checks _req against the supplier profile.
"""

import copy

# Words that make a past order or an OEM letter "similar" to the tender category.
CATEGORY_KEYWORDS = {
    "Laptops": ["laptop", "notebook"],
    "Printers": ["printer", "mfp"],
    "Networking": ["switch", "network", "wi-fi", "access point", "router"],
    "Desktops": ["desktop", "computer", "pc", "all-in-one"],
    "CCTV": ["cctv", "camera", "surveillance", "nvr"],
    "UPS": ["ups", "power backup", "inverter"],
}


def _doc_text(intro, sections, outro=""):
    """Build tender-style prose: intro, then 'heading' lines each followed by a paragraph."""
    parts = [intro]
    for heading, para in sections:
        parts.append(heading)
        parts.append(para)
    if outro:
        parts.append(outro)
    return "\n\n".join(parts)


# ---------------------------------------------------------------- tenders

def _t1():
    bid = "GeM/2026/B/6810423"
    main = "GeM Bid Document.pdf"
    atc = "ATC and Eligibility.pdf"
    h = {
        "turnover": "Cl. 4.1 Minimum Average Annual Turnover",
        "experience": "Cl. 4.2 Past Performance",
        "oem": "Cl. 6.3 OEM Authorisation",
        "emd": "Cl. 7.1 Earnest Money Deposit and Exemption",
    }
    q = {
        "turnover": "average annual turnover of the bidder during the last three financial years shall be at least Rs. 40 Lakh",
        "experience": "at least 2 similar orders each of value not less than Rs. 15 Lakh executed in the last three years",
        "oem": "bidder shall submit a valid OEM authorisation certificate from Lenovo for the offered make and model",
        "emd": "EMD of Rs. 80,000 is payable; MSEs registered for the tendered item as manufacturers or service providers are exempted",
    }
    atc_text = _doc_text(
        "Additional Terms and Conditions (ATC) forming part of bid " + bid + " for the supply of 120 business laptops "
        "to the State Polytechnic Board. The buyer reserves the right to verify every document uploaded by the bidder "
        "and to reject any bid found to contain false information.",
        [
            (h["turnover"], "The " + q["turnover"] + " (FY 2022-23, 2023-24 and 2024-25). A certificate from a Chartered "
             "Accountant stating the turnover for each year, with UDIN, shall be uploaded. Startups recognised by DPIIT "
             "are exempted from the prior turnover and experience criteria subject to meeting quality and technical specifications."),
            (h["experience"], "The bidder must have " + q["experience"] + " to any Central or State Government department, PSU "
             "or autonomous body. Copies of purchase orders together with completion or installation certificates are required."),
            (h["oem"], "The " + q["oem"] + ". The authorisation shall be addressed to the buyer, quote this bid number and remain "
             "valid until the end of the warranty period. Authorisations issued to a distributor are not acceptable."),
            (h["emd"], "An " + q["emd"] + " on submission of a valid Udyam certificate covering the tendered item. Traders and "
             "resellers are not covered by the exemption. EMD may be paid through the GeM EMD module or a bank guarantee."),
        ],
        "All other terms shall be as per the GeM General Terms and Conditions in force on the date of bid publication.",
    )
    main_text = ("Bid Details. Bid Number " + bid + ". Item category: Laptop - Notebook (Q2). Quantity 120. "
                 "Minimum average annual turnover of the bidder: refer ATC. Years of past experience required: 3. "
                 "Bid to RA enabled: Yes. Evaluation method: total value wise evaluation. Inspection: pre-dispatch by buyer.")
    return {
        "id": "t1", "bid": bid,
        "title": "Supply of 120 Business Laptops (Core i5, 16 GB, 512 GB SSD)",
        "buyer": "State Polytechnic Board, Karnataka", "portal": "GeM", "category": "Laptops",
        "value_lakh": 78.4, "emd_lakh": 0.8, "closes": "2026-11-06", "pages": 42,
        "url": "https://bidplus.gem.gov.in/showbidDocument/6810423",
        "docs": [{"name": main, "pages": 18, "text": "ok"}, {"name": atc, "pages": 24, "text": "ok"}],
        "snippet": "120 laptops, Lenovo authorisation, avg turnover Rs 40 L, 2 similar orders, EMD Rs 80,000 with MSE exemption.",
        "clauses": {
            "turnover": {"heading": h["turnover"], "quote": q["turnover"], "highlight": "at least Rs. 40 Lakh", "page": 9, "doc": atc},
            "experience": {"heading": h["experience"], "quote": q["experience"], "highlight": "at least 2 similar orders", "page": 10, "doc": atc},
            "oem": {"heading": h["oem"], "quote": q["oem"], "highlight": "OEM authorisation certificate from Lenovo", "page": 14, "doc": atc},
            "emd": {"heading": h["emd"], "quote": q["emd"], "highlight": "as manufacturers or service providers are exempted", "page": 17, "doc": atc},
        },
        "_req": {"turnover_lakh": 40, "orders_required": 2, "order_min_lakh": 15, "oem_brands": ["Lenovo"],
                 "emd_lakh": 0.8, "emd_exempt_mse": True, "emd_exempt_roles": ["manufacturer", "service_provider"],
                 "startup_relax": True, "mse_relax": False, "relaxation_denied": False},
        "_source": {main: main_text, atc: atc_text},
        "_headings": {main: ["Bid Details"], atc: list(h.values())},
    }


def _t2():
    bid = "GeM/2026/B/6822096"
    main = "GeM Bid Document.pdf"
    h = {
        "turnover": "Cl. 5.1 Financial Standing",
        "experience": "Cl. 5.2 Past Supplies",
        "oem": "Cl. 9.4 Manufacturer Authorisation",
        "emd": "Cl. 10 Bid Security and MSE Exemption",
    }
    q = {
        "turnover": "average annual turnover of not less than Rs. 25 Lakh during the preceding three financial years",
        "experience": "executed at least 1 supply order for printers of value not less than Rs. 10 Lakh to Government or PSU buyers",
        "oem": "Manufacturer Authorisation Form from HP for the quoted printer model is mandatory",
        "emd": "Bid security of Rs. 1,50,000 is required; exemption is available only to MSEs registered as manufacturers of the offered printers",
    }
    text = _doc_text(
        "Bid " + bid + ". Procurement of 60 A4 monochrome laser printers with three-year comprehensive on-site warranty "
        "for the District Health Society, Mysuru. Delivery within 30 days of the contract date at 14 primary health centres.",
        [
            (h["turnover"], "The bidder shall have an " + q["turnover"] + ". Audited balance sheets or a CA certificate are to be uploaded."),
            (h["experience"], "The bidder should have " + q["experience"] + " in the last three years. Order copies with proof of delivery are required."),
            (h["oem"], "A " + q["oem"] + ". The form must name the bidder, the buyer and the model offered."),
            (h["emd"], q["emd"][0].upper() + q["emd"][1:] + ", on production of a Udyam certificate listing the item. Traders, dealers "
             "and resellers registered as MSEs are not eligible for exemption and must furnish the bid security."),
        ],
        "Bids without bid security or a valid exemption document will be summarily rejected.",
    )
    return {
        "id": "t2", "bid": bid,
        "title": "A4 Monochrome Laser Printers, 60 Units with 3-yr Warranty",
        "buyer": "District Health Society, Mysuru", "portal": "GeM", "category": "Printers",
        "value_lakh": 17.9, "emd_lakh": 1.5, "closes": "2026-11-04", "pages": 28,
        "url": "https://bidplus.gem.gov.in/showbidDocument/6822096",
        "docs": [{"name": main, "pages": 28, "text": "ok"}],
        "snippet": "60 HP laser printers. EMD Rs 1.5 L; MSE exemption only for manufacturers, resellers excluded.",
        "clauses": {
            "turnover": {"heading": h["turnover"], "quote": q["turnover"], "highlight": "Rs. 25 Lakh", "page": 8, "doc": main},
            "experience": {"heading": h["experience"], "quote": q["experience"], "highlight": "at least 1 supply order", "page": 8, "doc": main},
            "oem": {"heading": h["oem"], "quote": q["oem"], "highlight": "from HP", "page": 15, "doc": main},
            "emd": {"heading": h["emd"], "quote": q["emd"], "highlight": "only to MSEs registered as manufacturers", "page": 16, "doc": main},
        },
        "_req": {"turnover_lakh": 25, "orders_required": 1, "order_min_lakh": 10, "oem_brands": ["HP"],
                 "emd_lakh": 1.5, "emd_exempt_mse": True, "emd_exempt_roles": ["manufacturer"],
                 "startup_relax": False, "mse_relax": False, "relaxation_denied": False},
        "_source": {main: text},
        "_headings": {main: list(h.values())},
    }


def _t3():
    bid = "CPPP/2026/NIC/118842"
    main = "NIT and Tender Document.pdf"
    h = {
        "turnover": "Section III, Cl. 2.1 Financial Capability",
        "experience": "Section III, Cl. 2.2 Technical Experience",
        "oem": "Section III, Cl. 2.4 OEM Authorisation",
        "emd": "Section II, Cl. 11 Earnest Money Deposit",
    }
    q = {
        "turnover": "minimum average annual turnover of Rs. 60 Lakh for the last three financial years",
        "experience": "at least 2 orders for supply and commissioning of similar networking equipment each of value not less than Rs. 25 Lakh",
        "oem": "authorisation from Cisco for the offered switches and access points with back-to-back warranty support",
        "emd": "Earnest Money Deposit of Rs. 1,20,000 shall be submitted",
    }
    deny = ("Exemption from prior turnover and prior experience is NOT available to Startups or MSEs for this tender, "
            "owing to the critical nature of the campus network.")
    text = _doc_text(
        "Notice Inviting Tender " + bid + ". Supply, installation and commissioning of managed L2 switches and Wi-Fi access "
        "points across 14 campuses of the City e-Governance Cell, Hubballi-Dharwad, with five years of on-site support.",
        [
            (h["turnover"], "The bidder shall have a " + q["turnover"] + ", certified by a Chartered Accountant. " + deny),
            (h["experience"], "The bidder must have completed " + q["experience"] + " during the last five years."),
            (h["oem"], "The bidder shall furnish " + q["oem"] + ", in the format at Annexure-IV."),
            (h["emd"], "An " + q["emd"] + " through the CPPP online payment gateway. Exemption is available only as per the "
             "Public Procurement Policy for MSEs, and not from the qualification criteria above."),
        ],
    )
    return {
        "id": "t3", "bid": bid,
        "title": "Managed L2 Switches and Wi-Fi Access Points for 14 Campuses",
        "buyer": "City e-Governance Cell, Hubballi-Dharwad", "portal": "CPPP", "category": "Networking",
        "value_lakh": 41.2, "emd_lakh": 1.2, "closes": "2026-11-12", "pages": 54,
        "url": "https://eprocure.gov.in/cppp/tendersfullview/118842",
        "docs": [{"name": main, "pages": 54, "text": "ok"}],
        "snippet": "Cisco switches and APs, avg turnover Rs 60 L. Startup/MSE relaxation explicitly NOT available.",
        "clauses": {
            "turnover": {"heading": h["turnover"], "quote": q["turnover"], "highlight": "Rs. 60 Lakh", "page": 21, "doc": main},
            "experience": {"heading": h["experience"], "quote": q["experience"], "highlight": "at least 2 orders", "page": 22, "doc": main},
            "oem": {"heading": h["oem"], "quote": q["oem"], "highlight": "authorisation from Cisco", "page": 23, "doc": main},
            "emd": {"heading": h["emd"], "quote": q["emd"], "highlight": "Rs. 1,20,000", "page": 12, "doc": main},
        },
        "_req": {"turnover_lakh": 60, "orders_required": 2, "order_min_lakh": 25, "oem_brands": ["Cisco"],
                 "emd_lakh": 1.2, "emd_exempt_mse": True, "emd_exempt_roles": ["manufacturer", "service_provider"],
                 "startup_relax": False, "mse_relax": False, "relaxation_denied": True,
                 "relaxation_denied_quote": deny},
        "_source": {main: text},
        "_headings": {main: list(h.values())},
    }


def _t4():
    bid = "KPPP/2026/DSERT/4471"
    main = "Tender Document.pdf"
    ann = "Annexure-V OEM Format (scanned).pdf"
    h = {
        "turnover": "Cl. 3 Bidder Turnover",
        "experience": "Cl. 4 Experience Criteria",
        "oem": "Annexure-V OEM Authorisation Format",
        "emd": "Cl. 8 EMD",
    }
    q = {
        "turnover": "minimum average annual turnover of Rs. 30 Lakh for the last three financial years",
        "experience": "supplied similar desktop computers in at least 1 order of value not less than Rs. 10 Lakh",
        "oem": "authorisation from Lenovo, Dell or HP for the offered desktop model with three-year warranty support",
        "emd": "Earnest Money Deposit of Rs. 50,000 shall be submitted",
    }
    text = _doc_text(
        "Tender " + bid + " on the Karnataka Public Procurement Portal. Supply of 200 desktop computers for "
        "government high school ICT labs under the Department of School Education. Bidders shall read the OEM "
        "authorisation format at Annexure-V, which forms part of this document.",
        [
            (h["turnover"], "The bidder should have a " + q["turnover"] + "."),
            (h["experience"], "The bidder must have " + q["experience"] + " to a Government department in the last three years."),
            (h["emd"], "An " + q["emd"] + " online through the KPPP e-payment system. Bidders claiming exemption shall upload proof."),
        ],
        "The OEM authorisation requirement and its format are set out in Annexure-V (pages 55 to 61).",
    )
    return {
        "id": "t4", "bid": bid,
        "title": "Desktop Computers for 200 School ICT Labs",
        "buyer": "Department of School Education, Karnataka", "portal": "KPPP", "category": "Desktops",
        "value_lakh": 92.0, "emd_lakh": 0.5, "closes": "2026-11-15", "pages": 61,
        "url": "https://kppp.karnataka.gov.in/tender/4471",
        "docs": [{"name": main, "pages": 54, "text": "ok"}, {"name": ann, "pages": 7, "text": "image_only"}],
        "snippet": "200 desktops. OEM clause sits in a scanned, image-only annexure, so it cannot be verified.",
        "clauses": {
            "turnover": {"heading": h["turnover"], "quote": q["turnover"], "highlight": "Rs. 30 Lakh", "page": 6, "doc": main},
            "experience": {"heading": h["experience"], "quote": q["experience"], "highlight": "at least 1 order", "page": 7, "doc": main},
            # The extractor "read" this from the scan; no retrieved text backs it, so the validator must reject it.
            "oem": {"heading": h["oem"], "quote": q["oem"], "highlight": "authorisation from Lenovo, Dell or HP", "page": 58, "doc": ann},
            "emd": {"heading": h["emd"], "quote": q["emd"], "highlight": "Rs. 50,000", "page": 11, "doc": main},
        },
        "_req": {"turnover_lakh": 30, "orders_required": 1, "order_min_lakh": 10, "oem_brands": ["Lenovo", "Dell", "HP"],
                 "emd_lakh": 0.5, "emd_exempt_mse": True, "emd_exempt_roles": ["manufacturer", "service_provider"],
                 "startup_relax": False, "mse_relax": False, "relaxation_denied": False},
        "_source": {main: text, ann: ""},
        "_headings": {main: [h["turnover"], h["experience"], h["emd"]], ann: []},
        "_image_only_pages": "55-61",
    }


def _t5():
    bid = "GeM/2026/B/6835512"
    main = "GeM Bid Document.pdf"
    h = {
        "turnover": "ATC Cl. 1 Turnover Criteria",
        "experience": "ATC Cl. 2 Experience Criteria",
        "oem": "ATC Cl. 5 OEM Authorisation",
        "emd": "ATC Cl. 7 EMD Detail",
    }
    q = {
        "turnover": "average annual turnover of at least Rs. 75 Lakh in the last three financial years",
        "experience": "at least 2 similar orders for CCTV surveillance systems each of value not less than Rs. 20 Lakh",
        "oem": "OEM authorisation from Hikvision or CP Plus for the offered cameras and NVR",
        "emd": "EMD amount of Rs. 1,00,000 is to be paid",
    }
    text = _doc_text(
        "Bid " + bid + ". Supply, installation, testing and commissioning of an IP CCTV surveillance system with 180 "
        "cameras and central NVR for the Mysuru City Corporation, including five years of comprehensive maintenance.",
        [
            (h["turnover"], "Bidder must have " + q["turnover"] + ". In case of a startup, exemption is as per GeM policy "
             "only if separately specified, and it is not specified for this bid."),
            (h["experience"], "Bidder must have completed " + q["experience"] + " for Government or PSU buyers."),
            (h["oem"], q["oem"] + " must be uploaded, naming the offered model numbers."),
            (h["emd"], "The " + q["emd"] + " via the GeM EMD module; MSE exemption as per GeM GTC."),
        ],
    )
    return {
        "id": "t5", "bid": bid,
        "title": "IP CCTV Surveillance System, 180 Cameras with NVR",
        "buyer": "Mysuru City Corporation", "portal": "GeM", "category": "CCTV",
        "value_lakh": 124.5, "emd_lakh": 1.0, "closes": "2026-11-18", "pages": 36,
        "url": "https://bidplus.gem.gov.in/showbidDocument/6835512",
        "docs": [{"name": main, "pages": 36, "text": "ok"}],
        "snippet": "180-camera CCTV with NVR. Avg turnover Rs 75 L and 2 orders of Rs 20 L+.",
        "clauses": {
            "turnover": {"heading": h["turnover"], "quote": q["turnover"], "highlight": "at least Rs. 75 Lakh", "page": 5, "doc": main},
            "experience": {"heading": h["experience"], "quote": q["experience"], "highlight": "at least 2 similar orders", "page": 5, "doc": main},
            "oem": {"heading": h["oem"], "quote": q["oem"], "highlight": "Hikvision or CP Plus", "page": 7, "doc": main},
            "emd": {"heading": h["emd"], "quote": q["emd"], "highlight": "Rs. 1,00,000", "page": 8, "doc": main},
        },
        "_req": {"turnover_lakh": 75, "orders_required": 2, "order_min_lakh": 20, "oem_brands": ["Hikvision", "CP Plus"],
                 "emd_lakh": 1.0, "emd_exempt_mse": True, "emd_exempt_roles": ["manufacturer", "service_provider"],
                 "startup_relax": False, "mse_relax": False, "relaxation_denied": False},
        "_source": {main: text},
        "_headings": {main: list(h.values())},
    }


def _t6():
    bid = "GeM/2026/B/6790021"
    main = "GeM Bid Document.pdf"
    h = {
        "turnover": "Cl. 2.1 Average Turnover",
        "experience": "Cl. 2.2 Similar Work Experience",
        "oem": "Cl. 3.1 OEM Authorisation",
        "emd": "Cl. 4 EMD and Exemption",
    }
    q = {
        "turnover": "average annual turnover of not less than Rs. 20 Lakh over the last three financial years",
        "experience": "at least 1 order for online UPS systems of value not less than Rs. 5 Lakh",
        "oem": "OEM authorisation from APC, Vertiv or Kaveri for the offered 10 kVA online UPS",
        "emd": "EMD of Rs. 2,00,000 is payable; MSEs registered as manufacturers of the item are exempted",
    }
    text = _doc_text(
        "Bid " + bid + ". Supply and installation of 24 online UPS systems of 10 kVA with 60-minute battery backup for "
        "taluk offices of the Revenue Department, including two years of on-site warranty.",
        [
            (h["turnover"], "The bidder shall have an " + q["turnover"] + ". MSEs and startups are exempted from the turnover "
             "and experience criteria subject to meeting quality and technical specifications."),
            (h["experience"], "Bidder shall have executed " + q["experience"] + " in the last three years."),
            (h["oem"], q["oem"] + " is required. A manufacturer bidding its own brand shall upload its BIS certificate instead."),
            (h["emd"], "An " + q["emd"] + " on uploading a Udyam certificate covering UPS. Traders are not eligible for the exemption."),
        ],
    )
    return {
        "id": "t6", "bid": bid,
        "title": "Online UPS 10 kVA with Battery Bank, 24 Units",
        "buyer": "Revenue Department, Karnataka", "portal": "GeM", "category": "UPS",
        "value_lakh": 11.4, "emd_lakh": 2.0, "closes": "2026-11-09", "pages": 22,
        "url": "https://bidplus.gem.gov.in/showbidDocument/6790021",
        "docs": [{"name": main, "pages": 22, "text": "ok"}],
        "snippet": "24 online UPS units. EMD Rs 2 L, exempt for MSE manufacturers; MSE/startup turnover relaxation allowed.",
        "clauses": {
            "turnover": {"heading": h["turnover"], "quote": q["turnover"], "highlight": "Rs. 20 Lakh", "page": 4, "doc": main},
            "experience": {"heading": h["experience"], "quote": q["experience"], "highlight": "at least 1 order", "page": 4, "doc": main},
            "oem": {"heading": h["oem"], "quote": q["oem"], "highlight": "APC, Vertiv or Kaveri", "page": 6, "doc": main},
            "emd": {"heading": h["emd"], "quote": q["emd"], "highlight": "manufacturers of the item are exempted", "page": 7, "doc": main},
        },
        "_req": {"turnover_lakh": 20, "orders_required": 1, "order_min_lakh": 5, "oem_brands": ["APC", "Vertiv", "Kaveri"],
                 "emd_lakh": 2.0, "emd_exempt_mse": True, "emd_exempt_roles": ["manufacturer"],
                 "startup_relax": True, "mse_relax": True, "relaxation_denied": False},
        "_source": {main: text},
        "_headings": {main: list(h.values())},
    }


TENDERS = [_t1(), _t2(), _t3(), _t4(), _t5(), _t6()]


# ---------------------------------------------------------------- profiles

def _docs(*items):
    return [{"name": n, "status": s, "expires": e} for n, s, e in items]


PROFILES = [
    {
        "id": "p-northstar", "name": "Northstar IT Supplies", "city": "Bengaluru",
        "entity_type": "Partnership firm", "role": "reseller",
        "gstin": "29AAKFN4821M1Z6", "udyam_mse": True, "dpiit": False,
        "turnover": [
            {"fy": "FY23", "value_lakh": 38.6, "evidence": "document"},
            {"fy": "FY24", "value_lakh": 44.1, "evidence": "document"},
            {"fy": "FY25", "value_lakh": 51.4, "evidence": "document"},
        ],
        "orders": [
            {"buyer": "Govt. Engineering College, Hassan", "item": "Laptops (60 units)", "value_lakh": 24.0, "date": "2025-08-14", "evidence": "document"},
            {"buyer": "Zilla Panchayat, Tumakuru", "item": "Laptops, desktop computers and laser printers", "value_lakh": 18.5, "date": "2024-11-02", "evidence": "declared"},
        ],
        "oem_letters": [
            {"brand": "Lenovo", "scope": "Laptops", "valid_until": "2027-03-31", "evidence": "document"},
            {"brand": "HP", "scope": "Printers", "valid_until": "2026-12-31", "evidence": "document"},
        ],
        "emd_funds_lakh": 1.0,
        "documents": _docs(
            ("GST registration", "valid", None),
            ("PAN", "valid", None),
            ("Udyam certificate", "valid", "2028-03-31"),
            ("CA turnover certificate FY23-FY25", "valid", None),
            ("Order completion certificates", "expiring", "2026-12-31"),
            ("DPIIT recognition certificate", "missing", None),
        ),
    },
    {
        "id": "p-kaveri", "name": "Kaveri Power Systems Pvt Ltd", "city": "Mysuru",
        "entity_type": "Private limited company", "role": "manufacturer",
        "gstin": "29AAGCK7713Q1Z2", "udyam_mse": True, "dpiit": False,
        "turnover": [
            {"fy": "FY23", "value_lakh": 210.0, "evidence": "verified"},
            {"fy": "FY24", "value_lakh": 246.5, "evidence": "verified"},
            {"fy": "FY25", "value_lakh": 268.0, "evidence": "verified"},
        ],
        "orders": [
            {"buyer": "BESCOM", "item": "Online UPS 10 kVA (40 units)", "value_lakh": 32.0, "date": "2025-06-20", "evidence": "verified"},
            {"buyer": "KPTCL", "item": "UPS and battery banks", "value_lakh": 14.2, "date": "2024-09-11", "evidence": "document"},
            {"buyer": "Mysuru Zilla Panchayat", "item": "Desktop computers (own brand)", "value_lakh": 11.0, "date": "2025-01-30", "evidence": "document"},
        ],
        "oem_letters": [
            {"brand": "Kaveri", "scope": "UPS, Desktops (own brand, manufacturer)", "valid_until": "2030-03-31", "evidence": "verified"},
        ],
        "emd_funds_lakh": 3.0,
        "documents": _docs(
            ("GST registration", "valid", None),
            ("PAN", "valid", None),
            ("Udyam certificate", "valid", "2029-03-31"),
            ("CA turnover certificate FY23-FY25", "valid", None),
            ("BIS certificate", "valid", "2027-06-30"),
            ("Order completion certificates", "valid", None),
        ),
    },
    {
        "id": "p-brightloop", "name": "Brightloop Technologies", "city": "Hubballi",
        "entity_type": "Private limited company (startup)", "role": "service_provider",
        "gstin": "29AAJCB2290L1Z9", "udyam_mse": True, "dpiit": True,
        "turnover": [
            {"fy": "FY24", "value_lakh": 12.5, "evidence": "document"},
            {"fy": "FY25", "value_lakh": 23.8, "evidence": "document"},
        ],
        "orders": [
            {"buyer": "Karnatak University, Dharwad", "item": "Laptops and Wi-Fi network setup", "value_lakh": 9.6, "date": "2025-10-05", "evidence": "document"},
        ],
        "oem_letters": [
            {"brand": "Lenovo", "scope": "Laptops, Desktops", "valid_until": "2027-06-30", "evidence": "document"},
            {"brand": "Cisco", "scope": "Networking switches, access points", "valid_until": "2026-09-30", "evidence": "declared"},
        ],
        "emd_funds_lakh": 0.6,
        "documents": _docs(
            ("GST registration", "valid", None),
            ("PAN", "valid", None),
            ("Udyam certificate", "valid", "2029-03-31"),
            ("DPIIT recognition certificate", "valid", "2031-02-28"),
            ("CA turnover certificate FY23-FY25", "missing", None),
        ),
    },
    {
        "id": "p-meridian", "name": "Meridian Systems Integrators Ltd", "city": "Bengaluru",
        "entity_type": "Public limited company", "role": "service_provider",
        "gstin": "29AAECM5521K1Z4", "udyam_mse": False, "dpiit": False,
        "turnover": [
            {"fy": "FY23", "value_lakh": 1840.0, "evidence": "verified"},
            {"fy": "FY24", "value_lakh": 2115.0, "evidence": "verified"},
            {"fy": "FY25", "value_lakh": 2390.0, "evidence": "verified"},
        ],
        "orders": [
            {"buyer": "Bengaluru Smart City Ltd", "item": "CCTV surveillance and command centre", "value_lakh": 410.0, "date": "2025-03-18", "evidence": "verified"},
            {"buyer": "Mangaluru Smart City", "item": "CCTV cameras and NVR", "value_lakh": 96.0, "date": "2024-07-22", "evidence": "verified"},
            {"buyer": "Karnataka State Data Centre", "item": "Network switches and routers", "value_lakh": 132.0, "date": "2025-01-09", "evidence": "verified"},
            {"buyer": "Visvesvaraya Technological University", "item": "Campus Wi-Fi network, access points", "value_lakh": 58.0, "date": "2024-05-16", "evidence": "document"},
            {"buyer": "Dept. of Collegiate Education", "item": "Desktop computers for labs", "value_lakh": 74.0, "date": "2025-08-02", "evidence": "document"},
        ],
        "oem_letters": [
            {"brand": "Cisco", "scope": "Networking switches, access points", "valid_until": "2027-12-31", "evidence": "verified"},
            {"brand": "Hikvision", "scope": "CCTV cameras, NVR", "valid_until": "2027-03-31", "evidence": "verified"},
            {"brand": "Dell", "scope": "Desktops, Laptops", "valid_until": "2027-03-31", "evidence": "document"},
        ],
        "emd_funds_lakh": 25.0,
        "documents": _docs(
            ("GST registration", "valid", None),
            ("PAN", "valid", None),
            ("CA turnover certificate FY23-FY25", "valid", None),
            ("ISO 9001 certificate", "expiring", "2026-11-30"),
            ("Order completion certificates", "valid", None),
        ),
    },
]


def fresh_tenders():
    return copy.deepcopy(TENDERS)


def fresh_profiles():
    return copy.deepcopy(PROFILES)

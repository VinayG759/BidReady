"""Supplier profiles and category vocabulary.

Tenders are real (backend/corpus and live GeM). Supplier profiles are sample businesses: real companies' financials
are not public, so these stand in for what a supplier enters about itself. Every fact carries an evidence level.
"""

import copy

# Words that make a past order, an OEM letter or a tender item belong to a category.
CATEGORY_KEYWORDS = {
    "Laptops": ["laptop", "notebook"],
    "Desktops": ["desktop", "all in one", "all-in-one", "aio", "workstation", "computer", "pc"],
    "Printers": ["printer", "mfp", "photocopier", "scanner", "multifunction"],
    "Networking": ["switch", "router", "access point", "wifi", "wi-fi", "network", "rack", "firewall"],
    "CCTV": ["cctv", "camera", "nvr", "surveillance"],
    "UPS": ["ups", "battery", "inverter"],
}
# Most specific first: "laptop computer" is a laptop, "network camera" is CCTV.
CATEGORY_ORDER = ["Laptops", "Printers", "CCTV", "UPS", "Networking", "Desktops"]


def category_of(text):
    t = (text or "").lower()
    for cat in CATEGORY_ORDER:
        if any(k in t for k in CATEGORY_KEYWORDS[cat]):
            return cat
    return "IT hardware"


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
            {"buyer": "Zilla Panchayat, Tumakuru", "item": "Laptops and desktop computers", "value_lakh": 18.5, "date": "2024-11-02", "evidence": "declared"},
            {"buyer": "Karnataka Police Housing Corp", "item": "Laptops (25 units)", "value_lakh": 11.2, "date": "2023-09-19", "evidence": "document"},
            {"buyer": "Kendriya Vidyalaya, Mysuru", "item": "Desktop computers and laser printers", "value_lakh": 8.4, "date": "2025-02-07", "evidence": "document"},
        ],
        "oem_letters": [
            {"brand": "Lenovo", "scope": "Laptops, Desktops", "valid_until": "2027-03-31", "evidence": "document"},
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
            {"buyer": "Hubballi-Dharwad Municipal Corp", "item": "Online UPS 20 kVA", "value_lakh": 9.8, "date": "2023-12-04", "evidence": "document"},
            {"buyer": "Mysuru Zilla Panchayat", "item": "Desktop computers (own brand)", "value_lakh": 11.0, "date": "2025-01-30", "evidence": "document"},
            {"buyer": "Mandya District Hospital", "item": "All in one PC (own brand)", "value_lakh": 6.5, "date": "2024-03-15", "evidence": "document"},
            {"buyer": "Chamarajanagar DIET", "item": "Desktop computers (own brand)", "value_lakh": 4.9, "date": "2023-07-28", "evidence": "document"},
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
        "entity_type": "Public limited company", "role": "reseller",
        "gstin": "29AAECM5521K1Z4", "udyam_mse": False, "dpiit": False,
        "turnover": [
            {"fy": "FY23", "value_lakh": 1840.0, "evidence": "verified"},
            {"fy": "FY24", "value_lakh": 2115.0, "evidence": "verified"},
            {"fy": "FY25", "value_lakh": 2390.0, "evidence": "verified"},
        ],
        "orders": [
            {"buyer": "Bengaluru Smart City Ltd", "item": "CCTV surveillance and command centre", "value_lakh": 410.0, "date": "2025-03-18", "evidence": "verified"},
            {"buyer": "Mangaluru Smart City", "item": "CCTV cameras and NVR", "value_lakh": 96.0, "date": "2024-07-22", "evidence": "verified"},
            {"buyer": "Belagavi Smart City", "item": "CCTV cameras", "value_lakh": 61.0, "date": "2023-10-12", "evidence": "verified"},
            {"buyer": "Karnataka State Data Centre", "item": "Network switches and routers", "value_lakh": 132.0, "date": "2025-01-09", "evidence": "verified"},
            {"buyer": "BSNL Karnataka Circle", "item": "Core and access network switches", "value_lakh": 88.0, "date": "2023-06-14", "evidence": "verified"},
            {"buyer": "Mysuru City Corporation", "item": "Network switches and Wi-Fi access points", "value_lakh": 41.0, "date": "2025-09-03", "evidence": "document"},
            {"buyer": "Visvesvaraya Technological University", "item": "Campus Wi-Fi network, access points", "value_lakh": 58.0, "date": "2024-05-16", "evidence": "document"},
            {"buyer": "Dept. of Collegiate Education", "item": "Desktop computers for labs", "value_lakh": 74.0, "date": "2025-08-02", "evidence": "document"},
            {"buyer": "Dept. of Technical Education", "item": "Desktop computers and laptops", "value_lakh": 52.0, "date": "2024-02-20", "evidence": "document"},
            {"buyer": "Karnataka Legislative Assembly", "item": "Laptops and multifunction printers", "value_lakh": 38.0, "date": "2023-08-30", "evidence": "document"},
        ],
        "oem_letters": [
            {"brand": "Cisco", "scope": "Networking switches, access points", "valid_until": "2027-12-31", "evidence": "verified"},
            {"brand": "Hikvision", "scope": "CCTV cameras, NVR", "valid_until": "2027-03-31", "evidence": "verified"},
            {"brand": "Dell", "scope": "Desktops, Laptops", "valid_until": "2027-03-31", "evidence": "document"},
            {"brand": "HP", "scope": "Printers, Laptops", "valid_until": "2027-03-31", "evidence": "document"},
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


def fresh_profiles():
    return copy.deepcopy(PROFILES)

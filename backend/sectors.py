"""Broad procurement sectors used for supplier and tender discovery filters.

These are intentionally wide and include an "Other / unclassified" fallback so a
tender is never hidden solely because its category does not match a known sector.
"""

SECTORS = [
    "Agriculture, forestry & fisheries",
    "Animal husbandry & veterinary",
    "Mining, minerals & metals",
    "Food, beverages & food processing",
    "Textiles, apparel & footwear",
    "Chemicals, petrochemicals & fertilizers",
    "Pharmaceuticals & biotechnology",
    "Healthcare, hospitals & medical devices",
    "Education, training & research",
    "IT, software & digital services",
    "Electronics, computers & office equipment",
    "Telecommunications & networking",
    "Electrical equipment & power systems",
    "Energy, oil, gas & utilities",
    "Renewable energy & clean technology",
    "Water, sanitation & wastewater",
    "Construction, civil works & infrastructure",
    "Real estate, housing & urban development",
    "Transportation, logistics & warehousing",
    "Automotive, mobility & electric vehicles",
    "Aerospace, aviation & defense",
    "Public safety, security & surveillance",
    "Environment, climate & waste management",
    "Banking, insurance & financial services",
    "Retail, wholesale & e-commerce",
    "Tourism, hospitality & catering",
    "Media, communications & printing",
    "Professional, consulting & facility services",
    "Government, public administration & e-governance",
    "Furniture, household & consumer goods",
    "Other / unclassified",
]

ALL_SECTORS = "All sectors"

CATEGORY_SECTOR = {
    "Laptops": "Electronics, computers & office equipment",
    "Printers": "Media, communications & printing",
    "Networking": "Telecommunications & networking",
    "Desktops": "Electronics, computers & office equipment",
    "CCTV": "Public safety, security & surveillance",
    "UPS": "Electrical equipment & power systems",
}


def sector_for_tender(tender):
    """Map known demo categories to a broad sector; never leave a tender unclassified."""
    explicit = tender.get("sector")
    if explicit in SECTORS:
        return explicit
    return CATEGORY_SECTOR.get(tender.get("category"), "Other / unclassified")

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

SECTOR_KEYWORDS = {
    "Agriculture, forestry & fisheries": ("agricultur", "farm", "seed", "crop", "fisher", "forestry", "tractor", "harvest"),
    "Animal husbandry & veterinary": ("veterinary", "animal feed", "livestock", "dairy", "poultry", "animal husbandry"),
    "Mining, minerals & metals": ("mining", "mineral", "steel", "iron ore", "copper", "aluminium", "metal scrap"),
    "Food, beverages & food processing": ("food", "beverage", "catering", "meal", "edible", "ration", "processed food"),
    "Textiles, apparel & footwear": ("textile", "fabric", "garment", "uniform", "apparel", "footwear", "shoe"),
    "Chemicals, petrochemicals & fertilizers": ("chemical", "resin", "petrochemical", "fertilizer", "fertiliser", "polymer", "paint", "solvent"),
    "Pharmaceuticals & biotechnology": ("pharmaceutical", "medicine", "drug", "vaccine", "biotechnology", "diagnostic reagent"),
    "Healthcare, hospitals & medical devices": ("medical", "hospital", "healthcare", "surgical", "patient care", "clinical", "diagnostic equipment"),
    "Education, training & research": ("education", "school", "training", "research", "laboratory", "academic"),
    "IT, software & digital services": ("software", "cloud service", "data center", "cybersecurity", "digital service", "application development", "it service"),
    "Electronics, computers & office equipment": ("computer", "laptop", "notebook", "desktop", "printer", "scanner", "office equipment", "electronic"),
    "Telecommunications & networking": ("telecom", "network switch", "router", "networking", "wifi", "wi-fi", "telephone", "optical fibre", "fiber optic"),
    "Electrical equipment & power systems": ("electrical", "transformer", "switchgear", "generator", "ups system", "cable", "power supply"),
    "Energy, oil, gas & utilities": ("oil", "natural gas", "petroleum", "utility", "fuel", "pipeline"),
    "Renewable energy & clean technology": ("solar", "wind turbine", "renewable", "photovoltaic", "clean energy"),
    "Water, sanitation & wastewater": ("water treatment", "wastewater", "sewage", "sanitation", "drainage", "water supply"),
    "Construction, civil works & infrastructure": ("construction", "civil work", "road work", "building work", "bridge", "infrastructure", "cement"),
    "Real estate, housing & urban development": ("real estate", "housing", "urban development", "township", "property management"),
    "Transportation, logistics & warehousing": ("logistics", "transportation", "freight", "warehouse", "warehousing", "cargo", "courier"),
    "Automotive, mobility & electric vehicles": ("automotive", "automobile", "electric vehicle", "ev charger", "vehicle", "bus", "car", "motorcycle"),
    "Aerospace, aviation & defense": ("aircraft", "aviation", "aerospace", "defence", "defense", "missile", "military", "armament"),
    "Public safety, security & surveillance": ("security", "surveillance", "cctv", "camera", "fire alarm", "access control", "police"),
    "Environment, climate & waste management": ("environment", "climate", "waste management", "recycling", "pollution", "solid waste"),
    "Banking, insurance & financial services": ("banking", "insurance", "financial service", "payment gateway", "audit service"),
    "Retail, wholesale & e-commerce": ("retail", "wholesale", "e-commerce", "point of sale", "pos terminal"),
    "Tourism, hospitality & catering": ("tourism", "hotel", "hospitality", "travel service", "guest house"),
    "Media, communications & printing": ("printing", "print service", "publication", "media", "newspaper", "communication service"),
    "Professional, consulting & facility services": ("consultancy", "consulting", "manpower", "housekeeping", "facility management", "legal service", "professional service"),
    "Government, public administration & e-governance": ("e-governance", "public administration", "government service", "citizen service"),
    "Furniture, household & consumer goods": ("furniture", "chair", "table", "household", "consumer goods", "appliance", "memorabilia"),
}


def sector_for_tender(tender):
    """Map a tender into the broad sector taxonomy; keep unfamiliar tenders visible."""
    explicit = tender.get("sector")
    if explicit in SECTORS:
        return explicit
    category = tender.get("category", "")
    known = CATEGORY_SECTOR.get(category)
    if known:
        return known
    text = " ".join(str(tender.get(key) or "") for key in ("category", "title", "buyer", "snippet")).casefold()
    ranked = [(sum(text.count(word) for word in words), sector) for sector, words in SECTOR_KEYWORDS.items()]
    score, match = max(ranked, key=lambda item: item[0], default=(0, "Other / unclassified"))
    return match if score else "Other / unclassified"

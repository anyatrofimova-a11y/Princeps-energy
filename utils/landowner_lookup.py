"""
Landowner Lookup — identify land ownership from free UK public records.

Sources: HMLR Price Paid (Land Registry), Companies House, OSM Nominatim.
All APIs are free and require no authentication.
"""

import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)
TIMEOUT = 15

# ── Land value benchmarks (England, 2025) ────────────────────────────────────

LAND_VALUE_PER_ACRE = {
    "agricultural": {"low": 7000, "mid": 9500, "high": 12000},
    "greenfield_planning": {"low": 50000, "mid": 120000, "high": 200000},
    "brownfield": {"low": 100000, "mid": 250000, "high": 500000},
    "industrial": {"low": 150000, "mid": 350000, "high": 600000},
    "residential": {"low": 500000, "mid": 1500000, "high": 4000000},
}

SOLAR_OPTION_FEES = {
    "option_per_acre_year": {"low": 800, "mid": 1000, "high": 1200},
    "lease_per_acre_year": {"low": 1000, "mid": 1500, "high": 2000},
    "option_term_years": 5,
    "lease_term_years": 25,
}

REGIONAL_FACTORS = {
    "london": 3.5, "south_east": 1.8, "east": 1.4, "south_west": 1.2,
    "west_midlands": 1.0, "east_midlands": 0.95, "yorkshire": 0.9,
    "north_west": 0.85, "north_east": 0.75, "wales": 0.7, "scotland": 0.65,
}


async def reverse_geocode(lat: float, lon: float) -> dict:
    """Reverse-geocode via OSM Nominatim (free, no key)."""
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1}
    headers = {"User-Agent": "Princeps/1.0 (energy site assessment)"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(url, params=params, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.warning("Nominatim reverse-geocode failed: %s", e)
        return {}


async def get_osm_land_context(lat: float, lon: float, radius_m: float = 200) -> dict:
    """Query OSM for land use and buildings near a point."""
    query = f"""
    [out:json][timeout:10];
    (
      way["landuse"](around:{radius_m},{lat},{lon});
      way["building"](around:{radius_m},{lat},{lon});
      relation["landuse"](around:{radius_m},{lat},{lon});
    );
    out tags center 10;
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post("https://overpass-api.de/api/interpreter", data={"data": query})
            r.raise_for_status()
            elements = r.json().get("elements", [])
    except Exception as e:
        log.warning("Overpass land context failed: %s", e)
        return {"land_uses": [], "buildings": []}

    land_uses = []
    buildings = []
    for el in elements:
        tags = el.get("tags", {})
        if "landuse" in tags:
            land_uses.append(tags["landuse"])
        if "building" in tags:
            buildings.append(tags.get("building", "yes"))

    return {"land_uses": list(set(land_uses)), "buildings": list(set(buildings)), "count": len(elements)}


async def nearby_land_transactions(lat: float, lon: float, radius_km: float = 2.0) -> list:
    """Fetch recent property transactions from HMLR Price Paid JSON API."""
    # HMLR linked data endpoint (SPARQL) — free, no auth
    postcode = await _get_postcode(lat, lon)
    if not postcode:
        return []

    # Strip space for partial match
    pc_prefix = postcode.split()[0] if " " in postcode else postcode[:4]

    sparql = f"""
    PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
    PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>

    SELECT ?date ?price ?address ?postcode ?type ?category
    WHERE {{
      ?tx lrppi:pricePaid ?price ;
          lrppi:transactionDate ?date ;
          lrppi:propertyAddress ?addr .
      ?addr lrcommon:postcode ?postcode .
      FILTER(STRSTARTS(STR(?postcode), "{pc_prefix}"))
      OPTIONAL {{ ?addr lrcommon:paon ?address }}
      OPTIONAL {{ ?tx lrppi:propertyType ?type }}
      OPTIONAL {{ ?tx lrppi:transactionCategory ?category }}
    }}
    ORDER BY DESC(?date)
    LIMIT 20
    """

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                "https://landregistry.data.gov.uk/app/root/qonsole/query",
                params={"query": sparql, "output": "json"},
                headers={"Accept": "application/sparql-results+json"},
            )
            if r.status_code != 200:
                # Fallback: simpler approach
                return await _fallback_transactions(postcode)
            data = r.json()
    except Exception:
        return await _fallback_transactions(postcode)

    results = []
    for binding in data.get("results", {}).get("bindings", []):
        results.append({
            "date": binding.get("date", {}).get("value"),
            "price_gbp": int(float(binding.get("price", {}).get("value", 0))),
            "address": binding.get("address", {}).get("value"),
            "postcode": binding.get("postcode", {}).get("value"),
            "type": binding.get("type", {}).get("value", "").split("/")[-1],
        })
    return results


async def _fallback_transactions(postcode: str) -> list:
    """Fallback: use postcode.io + estimated values."""
    return [{"note": f"HMLR SPARQL unavailable. Postcode: {postcode}. Use Land Registry portal for manual lookup."}]


async def _get_postcode(lat: float, lon: float) -> Optional[str]:
    """Get postcode from coordinates via postcodes.io (free)."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://api.postcodes.io/postcodes?lon={lon}&lat={lat}&limit=1")
            r.raise_for_status()
            result = r.json().get("result", [])
            if result:
                return result[0]["postcode"]
    except Exception:
        pass
    return None


async def search_companies_house(name: str) -> list:
    """Search Companies House for a corporate entity (free API, rate-limited)."""
    url = "https://api.company-information.service.gov.uk/search/companies"
    # Companies House API requires an API key but has a free tier
    # For demo, we'll note the requirement
    api_key = None  # Set COMPANIES_HOUSE_API_KEY env var

    if not api_key:
        import os
        api_key = os.getenv("COMPANIES_HOUSE_API_KEY")

    if not api_key:
        return [{
            "note": "Companies House API key required. Get free at https://developer.company-information.service.gov.uk/",
            "search_url": f"https://find-and-update.company-information.service.gov.uk/search?q={name}",
        }]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, auth=(api_key, "")) as c:
            r = await c.get(url, params={"q": name, "items_per_page": 5})
            r.raise_for_status()
            items = r.json().get("items", [])
    except Exception as e:
        return [{"error": str(e)}]

    return [{
        "company_name": item.get("title"),
        "company_number": item.get("company_number"),
        "status": item.get("company_status"),
        "type": item.get("company_type"),
        "address": item.get("address_snippet"),
        "date_of_creation": item.get("date_of_creation"),
    } for item in items]


async def get_company_detail(company_number: str) -> dict:
    """Get company profile from Companies House."""
    import os
    api_key = os.getenv("COMPANIES_HOUSE_API_KEY")
    if not api_key:
        return {"search_url": f"https://find-and-update.company-information.service.gov.uk/company/{company_number}"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, auth=(api_key, "")) as c:
            r = await c.get(f"https://api.company-information.service.gov.uk/company/{company_number}")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": str(e)}


async def estimate_land_value(lat: float, lon: float, area_ha: float = 5.0,
                                land_type: str = "agricultural") -> dict:
    """Estimate land value based on type, region, and nearby transactions."""
    area_acres = area_ha * 2.471

    # Determine region from coordinates
    region = "east_midlands"  # Default
    if lat > 55: region = "scotland"
    elif lat > 54: region = "north_east" if lon > -2 else "north_west"
    elif lat > 53: region = "yorkshire" if lon > -1.5 else "north_west"
    elif lat > 52: region = "east_midlands" if lon > -1.5 else "west_midlands"
    elif lat > 51.5: region = "east" if lon > 0 else "south_east"
    elif lat > 51: region = "south_east" if lon > -1 else "south_west"
    elif lon < -3: region = "wales"
    else: region = "south_west"

    factor = REGIONAL_FACTORS.get(region, 1.0)
    benchmarks = LAND_VALUE_PER_ACRE.get(land_type, LAND_VALUE_PER_ACRE["agricultural"])

    values = {
        "low": round(benchmarks["low"] * factor * area_acres),
        "mid": round(benchmarks["mid"] * factor * area_acres),
        "high": round(benchmarks["high"] * factor * area_acres),
    }

    solar_option = {
        "annual_fee": round(SOLAR_OPTION_FEES["option_per_acre_year"]["mid"] * area_acres),
        "lease_annual": round(SOLAR_OPTION_FEES["lease_per_acre_year"]["mid"] * area_acres),
        "option_term_years": SOLAR_OPTION_FEES["option_term_years"],
        "lease_term_years": SOLAR_OPTION_FEES["lease_term_years"],
        "total_option_value": round(SOLAR_OPTION_FEES["option_per_acre_year"]["mid"] * area_acres * SOLAR_OPTION_FEES["option_term_years"]),
        "total_lease_value": round(SOLAR_OPTION_FEES["lease_per_acre_year"]["mid"] * area_acres * SOLAR_OPTION_FEES["lease_term_years"]),
    }

    return {
        "area_ha": area_ha,
        "area_acres": round(area_acres, 1),
        "land_type": land_type,
        "region": region,
        "regional_factor": factor,
        "estimated_value_gbp": values,
        "per_acre_gbp": benchmarks,
        "solar_option": solar_option,
        "note": "Estimates based on 2025 UK benchmarks. Commission RICS Red Book valuation for accuracy.",
    }


async def lookup_landowner(lat: float, lon: float) -> dict:
    """Combined landowner lookup from all available sources."""
    geocode = await reverse_geocode(lat, lon)
    land_context = await get_osm_land_context(lat, lon)
    postcode = await _get_postcode(lat, lon)

    address = geocode.get("display_name", "Unknown")
    addr_detail = geocode.get("address", {})

    # Extract potential owner clues from address
    owner_clues = []
    if addr_detail.get("farm"):
        owner_clues.append(f"Farm: {addr_detail['farm']}")
    if addr_detail.get("hamlet"):
        owner_clues.append(f"Hamlet: {addr_detail['hamlet']}")

    return {
        "lat": lat,
        "lon": lon,
        "address": address,
        "postcode": postcode,
        "county": addr_detail.get("county"),
        "district": addr_detail.get("city_district") or addr_detail.get("town") or addr_detail.get("village"),
        "land_context": land_context,
        "owner_clues": owner_clues,
        "hmlr_title_search_url": f"https://search-property-information.service.gov.uk/search/search-by-inspire-id?lat={lat}&lng={lon}",
        "companies_house_url": "https://find-and-update.company-information.service.gov.uk/",
        "recommendation": "Use HMLR Title Search (£3 per title) for definitive ownership. Link above pre-fills coordinates.",
    }

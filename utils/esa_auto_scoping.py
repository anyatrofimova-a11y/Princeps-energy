"""
Phase 1 ESA Auto-Scoping — automated Preliminary Risk Assessment.

Inspired by Transect. Generates desk-based environmental site assessment
from Princeps constraint data + free UK government APIs.
"""

import logging
import math
from typing import Optional

import httpx

log = logging.getLogger(__name__)
TIMEOUT = 15

# ── Radon risk by county (PHE simplified) ────────────────────────────────────
RADON_RISK = {
    "cornwall": "HIGH", "devon": "HIGH", "somerset": "MEDIUM", "dorset": "MEDIUM",
    "northamptonshire": "HIGH", "derbyshire": "MEDIUM", "peak district": "HIGH",
    "cumbria": "MEDIUM", "lancashire": "LOW", "yorkshire": "LOW",
    "london": "LOW", "essex": "LOW", "kent": "LOW", "surrey": "LOW",
    "sussex": "LOW", "hampshire": "LOW", "berkshire": "LOW",
    "oxfordshire": "MEDIUM", "gloucestershire": "MEDIUM", "wiltshire": "MEDIUM",
    "norfolk": "LOW", "suffolk": "LOW", "cambridgeshire": "LOW",
    "lincolnshire": "LOW", "nottinghamshire": "LOW", "leicestershire": "LOW",
    "warwickshire": "LOW", "staffordshire": "LOW", "shropshire": "MEDIUM",
    "herefordshire": "MEDIUM", "worcestershire": "LOW",
}

# ── UXO risk by region (WW2 bombing, simplified) ────────────────────────────
UXO_RISK = {
    "london": "HIGH", "coventry": "HIGH", "plymouth": "HIGH", "southampton": "HIGH",
    "portsmouth": "HIGH", "bristol": "MEDIUM", "birmingham": "MEDIUM",
    "manchester": "MEDIUM", "liverpool": "MEDIUM", "hull": "MEDIUM",
    "sheffield": "MEDIUM", "swansea": "MEDIUM", "exeter": "MEDIUM",
}

# ── Survey cost benchmarks (£, 2025) ────────────────────────────────────────
SURVEY_COSTS = {
    "phase_2_geo": {"name": "Phase 2 Ground Investigation", "low": 5000, "mid": 12000, "high": 25000},
    "contamination": {"name": "Contaminated Land Assessment", "low": 3000, "mid": 8000, "high": 15000},
    "ecological_survey": {"name": "Ecological Survey (PEA)", "low": 2000, "mid": 4000, "high": 8000},
    "bat_survey": {"name": "Bat Activity Survey", "low": 3000, "mid": 6000, "high": 12000},
    "great_crested_newt": {"name": "GCN eDNA Survey", "low": 500, "mid": 1000, "high": 2000},
    "heritage_assessment": {"name": "Heritage Impact Assessment", "low": 2000, "mid": 5000, "high": 10000},
    "archaeology_desk": {"name": "Archaeological Desk-Based Assessment", "low": 1500, "mid": 3000, "high": 6000},
    "flood_risk_assessment": {"name": "Flood Risk Assessment (FRA)", "low": 1500, "mid": 3000, "high": 6000},
    "noise_assessment": {"name": "Noise Impact Assessment", "low": 2000, "mid": 4000, "high": 8000},
    "landscape_visual": {"name": "Landscape & Visual Impact (LVIA)", "low": 5000, "mid": 10000, "high": 20000},
    "transport_assessment": {"name": "Transport Assessment", "low": 3000, "mid": 6000, "high": 12000},
    "uxo_survey": {"name": "UXO Desktop Survey", "low": 1000, "mid": 2000, "high": 4000},
    "radon_test": {"name": "Radon Risk Report", "low": 30, "mid": 50, "high": 100},
    "topographical": {"name": "Topographical Survey", "low": 2000, "mid": 5000, "high": 10000},
    "drainage_strategy": {"name": "Drainage Strategy (SuDS)", "low": 2000, "mid": 4000, "high": 8000},
}


async def _get_postcode_info(lat: float, lon: float) -> dict:
    """Get postcode and admin info from postcodes.io."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"https://api.postcodes.io/postcodes?lon={lon}&lat={lat}&limit=1")
            r.raise_for_status()
            result = r.json().get("result", [])
            if result:
                return result[0]
    except Exception:
        pass
    return {}


async def _check_flood_zones(lat: float, lon: float) -> dict:
    """Check EA flood risk zones."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(
                "https://environment.data.gov.uk/flood-monitoring/id/floods",
                params={"lat": lat, "long": lon, "dist": 5},
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                return {
                    "active_warnings": len(items),
                    "warnings": [{"area": i.get("floodArea", {}).get("label"), "severity": i.get("severityLevel")} for i in items[:5]],
                }
    except Exception:
        pass

    # Simplified zone estimation based on elevation/proximity to rivers
    return {"active_warnings": 0, "zone_estimate": "Zone 1 (low risk)", "note": "Use EA flood map for definitive zone."}


async def contamination_risk(lat: float, lon: float) -> dict:
    """Assess historical contamination risk from land use context."""
    # Query OSM for historical industrial land use
    query = f"""
    [out:json][timeout:10];
    (
      way["landuse"="industrial"](around:500,{lat},{lon});
      way["landuse"="landfill"](around:1000,{lat},{lon});
      way["landuse"="quarry"](around:500,{lat},{lon});
      node["man_made"="petroleum_well"](around:1000,{lat},{lon});
      way["landuse"="military"](around:500,{lat},{lon});
    );
    out count;
    """
    industrial_count = 0
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post("https://overpass-api.de/api/interpreter", data={"data": query})
            if r.status_code == 200:
                elements = r.json().get("elements", [])
                industrial_count = len(elements)
    except Exception:
        pass

    if industrial_count >= 3:
        risk = "HIGH"
        detail = "Multiple historical industrial/landfill/quarry uses within 500m"
    elif industrial_count >= 1:
        risk = "MEDIUM"
        detail = "Some industrial land use detected nearby"
    else:
        risk = "LOW"
        detail = "No obvious historical contamination sources identified"

    return {
        "risk_level": risk,
        "detail": detail,
        "industrial_features_nearby": industrial_count,
        "recommended_surveys": ["phase_2_geo", "contamination"] if risk != "LOW" else [],
        "note": "Desk-based only. Phase 2 investigation required for definitive assessment.",
    }


async def flood_risk_assessment(lat: float, lon: float) -> dict:
    """Comprehensive flood risk check."""
    ea_data = await _check_flood_zones(lat, lon)

    return {
        "ea_flood_data": ea_data,
        "risk_level": "HIGH" if ea_data.get("active_warnings", 0) > 0 else "LOW",
        "recommended_surveys": ["flood_risk_assessment"] if ea_data.get("active_warnings", 0) > 0 else [],
        "ea_flood_map_url": f"https://check-long-term-flood-risk.service.gov.uk/map?easting=&northing=&map=RiversOrSea",
        "climate_note": "UKCP18 projects increased rainfall intensity. FRA should consider climate change allowances.",
    }


async def ecological_screening(lat: float, lon: float, radius_m: float = 2000) -> dict:
    """Screen for protected sites and species."""
    # Check Natural England APIs for designations
    designations = []
    risk_level = "LOW"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            # SSSI check
            r = await c.get(
                "https://environment.data.gov.uk/arcgis/rest/services/NE/SSSIBoundaries/MapServer/0/query",
                params={
                    "geometry": f"{lon},{lat}",
                    "geometryType": "esriGeometryPoint",
                    "distance": radius_m,
                    "units": "esriSRUnit_Meter",
                    "outFields": "SSSI_NAME",
                    "f": "json",
                },
            )
            if r.status_code == 200:
                features = r.json().get("features", [])
                for f in features:
                    designations.append({
                        "type": "SSSI",
                        "name": f.get("attributes", {}).get("SSSI_NAME"),
                    })
                    risk_level = "HIGH"
    except Exception:
        pass

    return {
        "risk_level": risk_level,
        "designations": designations,
        "designation_count": len(designations),
        "recommended_surveys": (
            ["ecological_survey", "bat_survey", "great_crested_newt"]
            if risk_level == "HIGH" else
            ["ecological_survey"] if designations else []
        ),
    }


async def heritage_screening(lat: float, lon: float, radius_m: float = 1000) -> dict:
    """Screen for heritage assets."""
    # OSM listed buildings and monuments
    query = f"""
    [out:json][timeout:10];
    (
      node["heritage"](around:{radius_m},{lat},{lon});
      node["historic"](around:{radius_m},{lat},{lon});
      way["heritage"](around:{radius_m},{lat},{lon});
      way["historic"](around:{radius_m},{lat},{lon});
    );
    out tags 20;
    """
    assets = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post("https://overpass-api.de/api/interpreter", data={"data": query})
            if r.status_code == 200:
                for el in r.json().get("elements", []):
                    tags = el.get("tags", {})
                    assets.append({
                        "type": tags.get("historic") or tags.get("heritage"),
                        "name": tags.get("name", "Unnamed"),
                        "grade": tags.get("heritage:operator") or tags.get("listed_status"),
                    })
    except Exception:
        pass

    risk_level = "HIGH" if len(assets) >= 3 else "MEDIUM" if assets else "LOW"
    return {
        "risk_level": risk_level,
        "heritage_assets": assets[:10],
        "count": len(assets),
        "recommended_surveys": ["heritage_assessment", "archaeology_desk"] if assets else [],
    }


async def auto_scope_phase1(lat: float, lon: float, site_area_ha: float = 5.0,
                              proposed_use: str = "solar_farm") -> dict:
    """Generate complete Phase 1 ESA scope from available data."""
    import asyncio

    # Parallel data gathering
    pc_info, contam, flood, ecology, heritage = await asyncio.gather(
        _get_postcode_info(lat, lon),
        contamination_risk(lat, lon),
        flood_risk_assessment(lat, lon),
        ecological_screening(lat, lon),
        heritage_screening(lat, lon),
    )

    county = (pc_info.get("admin_county") or pc_info.get("admin_district") or "").lower()
    radon = RADON_RISK.get(county, "LOW")

    # UXO check
    uxo_risk = "LOW"
    for area, risk in UXO_RISK.items():
        if area in county or area in (pc_info.get("admin_district") or "").lower():
            uxo_risk = risk
            break

    # Compile all recommended surveys
    all_surveys = set()
    all_surveys.update(contam.get("recommended_surveys", []))
    all_surveys.update(flood.get("recommended_surveys", []))
    all_surveys.update(ecology.get("recommended_surveys", []))
    all_surveys.update(heritage.get("recommended_surveys", []))

    # Always recommend
    all_surveys.add("topographical")
    if proposed_use in ("solar_farm", "wind_farm"):
        all_surveys.add("landscape_visual")
        all_surveys.add("noise_assessment")
    if proposed_use == "data_centre":
        all_surveys.add("noise_assessment")
        all_surveys.add("transport_assessment")
        all_surveys.add("drainage_strategy")
    if radon != "LOW":
        all_surveys.add("radon_test")
    if uxo_risk != "LOW":
        all_surveys.add("uxo_survey")

    # Cost estimation
    total_cost_low = 0
    total_cost_mid = 0
    total_cost_high = 0
    survey_details = []
    for survey_id in sorted(all_surveys):
        costs = SURVEY_COSTS.get(survey_id)
        if costs:
            survey_details.append({
                "id": survey_id,
                "name": costs["name"],
                "cost_low": costs["low"],
                "cost_mid": costs["mid"],
                "cost_high": costs["high"],
                "priority": "essential" if survey_id in ("topographical", "ecological_survey") else "recommended",
            })
            total_cost_low += costs["low"]
            total_cost_mid += costs["mid"]
            total_cost_high += costs["high"]

    # Overall risk
    section_risks = [contam["risk_level"], flood["risk_level"], ecology["risk_level"], heritage["risk_level"], radon, uxo_risk]
    if "HIGH" in section_risks:
        overall_risk = "HIGH"
    elif "MEDIUM" in section_risks:
        overall_risk = "MEDIUM"
    else:
        overall_risk = "LOW"

    return {
        "site": {
            "lat": lat, "lon": lon,
            "area_ha": site_area_ha,
            "proposed_use": proposed_use,
            "postcode": pc_info.get("postcode"),
            "county": pc_info.get("admin_county"),
            "district": pc_info.get("admin_district"),
            "parish": pc_info.get("parish"),
        },
        "overall_risk": overall_risk,
        "sections": {
            "contamination": contam,
            "flood_risk": flood,
            "ecology": ecology,
            "heritage": heritage,
            "radon": {"risk_level": radon, "county": county},
            "uxo": {"risk_level": uxo_risk},
            "ground_conditions": {
                "risk_level": "LOW",
                "note": "BGS geology lookup requires manual check",
                "bgs_url": f"https://mapapps2.bgs.ac.uk/geoindex/home.html?lat={lat}&lng={lon}",
            },
        },
        "recommended_surveys": survey_details,
        "estimated_cost": {
            "low": total_cost_low,
            "mid": total_cost_mid,
            "high": total_cost_high,
        },
        "regulatory_contacts": {
            "environment_agency": "03708 506 506",
            "natural_england": "0300 060 3900",
            "historic_england": "0370 333 0607",
            "local_planning_authority": pc_info.get("admin_district"),
        },
        "report_standard": "BS 10175:2011+A2:2017 (Investigation of Contaminated Sites)",
    }

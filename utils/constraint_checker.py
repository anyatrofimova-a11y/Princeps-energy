"""UK Planning Constraint Checker — automated checks via public APIs.

Checks: flood zones (EA), ecology (MAGIC), heritage (Historic England),
agricultural land classification (Natural England).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0, connect=10.0)


# ── Flood Zone (Environment Agency) ──────────────────────────────────────

async def check_flood_zone(lat: float, lon: float) -> dict[str, Any]:
    """Query EA Flood Map for Planning at a point."""
    url = (
        "https://environment.data.gov.uk/arcgis/rest/services/EA/"
        "FloodMapForPlanningRiversAndSeaFloodZone3/MapServer/0/query"
    )
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Check Zone 3
            r3 = await client.get(url, params=params)
            in_zone3 = bool(r3.json().get("features"))

            # Check Zone 2
            url2 = url.replace("FloodZone3", "FloodZone2")
            r2 = await client.get(url2, params=params)
            in_zone2 = bool(r2.json().get("features"))

        if in_zone3:
            return {"status": "NO-GO", "zone": "3", "detail": "Site is in Flood Zone 3 (high probability). DCs classified as 'less vulnerable' — appropriate in 3a but not 3b (functional floodplain)."}
        if in_zone2:
            return {"status": "CAUTION", "zone": "2", "detail": "Site is in Flood Zone 2 (medium probability). Acceptable for DCs but FRA required."}
        return {"status": "GO", "zone": "1", "detail": "Site is in Flood Zone 1 (low probability). No flood-related constraints."}
    except Exception as e:
        log.warning("Flood zone check failed: %s", e)
        return {"status": "UNKNOWN", "zone": None, "detail": f"Flood check failed: {e}", "error": True}


# ── Ecology (Natural England MAGIC) ──────────────────────────────────────

async def check_ecology(lat: float, lon: float, radius_km: float = 2.0) -> dict[str, Any]:
    """Check proximity to SSSI, SAC, SPA, Ramsar, Ancient Woodland."""
    designations = []

    layers = [
        ("SSSI", "https://environment.data.gov.uk/arcgis/rest/services/NE/SitesOfSpecialScientificInterestEngland/FeatureServer/0/query"),
        ("SAC", "https://environment.data.gov.uk/arcgis/rest/services/NE/SpecialAreasOfConservationEngland/FeatureServer/0/query"),
        ("SPA", "https://environment.data.gov.uk/arcgis/rest/services/NE/SpecialProtectionAreasEngland/FeatureServer/0/query"),
        ("AncientWoodland", "https://environment.data.gov.uk/arcgis/rest/services/NE/AncientWoodlandEngland/FeatureServer/0/query"),
    ]

    # Create a buffer circle around the point
    buf_deg = radius_km / 111.32
    ring = []
    for i in range(36):
        angle = math.radians(i * 10)
        ring.append([lon + buf_deg * math.cos(angle), lat + buf_deg * math.sin(angle)])
    ring.append(ring[0])
    envelope = {"rings": [[[p[0], p[1]] for p in ring]], "spatialReference": {"wkid": 4326}}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for name, url in layers:
            try:
                params = {
                    "geometry": str(envelope).replace("'", '"'),
                    "geometryType": "esriGeometryPolygon",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "NAME,SSSI_NAME,SAC_NAME,SPA_NAME",
                    "returnGeometry": "false",
                    "returnCountOnly": "true",
                    "f": "json",
                }
                r = await client.get(url, params=params)
                data = r.json()
                count = data.get("count", 0)
                if count > 0:
                    designations.append({"type": name, "count": count, "within_km": radius_km})
            except Exception as e:
                log.warning("Ecology check %s failed: %s", name, e)

    if any(d["type"] in ("SAC", "SPA") for d in designations):
        return {"status": "NO-GO", "designations": designations, "detail": f"Natura 2000 site (SAC/SPA) within {radius_km}km. Habitats Regulations Assessment required — likely showstopper."}
    if designations:
        types = ", ".join(d["type"] for d in designations)
        return {"status": "CAUTION", "designations": designations, "detail": f"Ecological designations within {radius_km}km: {types}. Ecological survey and BNG assessment required."}
    return {"status": "GO", "designations": [], "detail": f"No ecological designations within {radius_km}km."}


# ── Heritage (Historic England) ───────────────────────────────────────────

async def check_heritage(lat: float, lon: float, radius_km: float = 1.0) -> dict[str, Any]:
    """Check proximity to listed buildings and scheduled monuments."""
    results = []

    layers = [
        ("ListedBuilding", "https://environment.data.gov.uk/arcgis/rest/services/HE/ListedBuildingsEngland/FeatureServer/0/query"),
        ("ScheduledMonument", "https://environment.data.gov.uk/arcgis/rest/services/HE/ScheduledMonumentsEngland/FeatureServer/0/query"),
    ]

    buf_deg = radius_km / 111.32

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for name, url in layers:
            try:
                params = {
                    "geometry": f"{lon - buf_deg},{lat - buf_deg},{lon + buf_deg},{lat + buf_deg}",
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "NAME,GRADE,ListEntry",
                    "returnGeometry": "false",
                    "returnCountOnly": "true",
                    "f": "json",
                }
                r = await client.get(url, params=params)
                data = r.json()
                count = data.get("count", 0)
                if count > 0:
                    results.append({"type": name, "count": count, "within_km": radius_km})
            except Exception as e:
                log.warning("Heritage check %s failed: %s", name, e)

    if any(r["type"] == "ScheduledMonument" for r in results):
        return {"status": "NO-GO", "heritage": results, "detail": f"Scheduled Monument within {radius_km}km. Substantial harm presumption — very difficult to obtain consent."}
    if results:
        total = sum(r["count"] for r in results)
        return {"status": "CAUTION", "heritage": results, "detail": f"{total} heritage assets within {radius_km}km. Heritage Impact Assessment required."}
    return {"status": "GO", "heritage": [], "detail": f"No heritage constraints within {radius_km}km."}


# ── Agricultural Land Classification ──────────────────────────────────────

async def check_alc(lat: float, lon: float) -> dict[str, Any]:
    """Check Agricultural Land Classification grade at point."""
    url = (
        "https://environment.data.gov.uk/arcgis/rest/services/NE/"
        "AgriculturalLandClassificationProvisionalEngland/FeatureServer/0/query"
    )
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "ALC_GRADE",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, params=params)
            data = r.json()

        features = data.get("features", [])
        if not features:
            return {"status": "GO", "grade": None, "detail": "No ALC data available — likely urban or non-agricultural."}

        grade = features[0].get("attributes", {}).get("ALC_GRADE", "Unknown")

        if grade in ("Grade 1", "Grade 2"):
            return {"status": "NO-GO", "grade": grade, "detail": f"Best and Most Versatile (BMV) agricultural land — {grade}. NPPF strongly resists development on BMV land."}
        if grade == "Grade 3":
            return {"status": "CAUTION", "grade": grade, "detail": "Grade 3 agricultural land. May include 3a (BMV) or 3b — detailed ALC survey needed to distinguish."}
        return {"status": "GO", "grade": grade, "detail": f"Agricultural land grade: {grade}. No BMV constraint."}
    except Exception as e:
        log.warning("ALC check failed: %s", e)
        return {"status": "UNKNOWN", "grade": None, "detail": f"ALC check failed: {e}", "error": True}


# ── Aggregate Check ───────────────────────────────────────────────────────

async def check_all_constraints(lat: float, lon: float, radius_km: float = 2.0) -> dict[str, Any]:
    """Run all constraint checks and return aggregate verdict."""
    results = await asyncio.gather(
        check_flood_zone(lat, lon),
        check_ecology(lat, lon, radius_km),
        check_heritage(lat, lon, min(radius_km, 1.0)),
        check_alc(lat, lon),
        return_exceptions=True,
    )

    checks = {
        "flood": results[0] if not isinstance(results[0], Exception) else {"status": "UNKNOWN", "error": str(results[0])},
        "ecology": results[1] if not isinstance(results[1], Exception) else {"status": "UNKNOWN", "error": str(results[1])},
        "heritage": results[2] if not isinstance(results[2], Exception) else {"status": "UNKNOWN", "error": str(results[2])},
        "alc": results[3] if not isinstance(results[3], Exception) else {"status": "UNKNOWN", "error": str(results[3])},
    }

    statuses = [c["status"] for c in checks.values()]
    if "NO-GO" in statuses:
        verdict = "NO-GO"
    elif "CAUTION" in statuses:
        verdict = "CAUTION"
    elif "UNKNOWN" in statuses:
        verdict = "CAUTION"
    else:
        verdict = "GO"

    no_go_reasons = [f"{k}: {v['detail']}" for k, v in checks.items() if v["status"] == "NO-GO"]
    caution_reasons = [f"{k}: {v['detail']}" for k, v in checks.items() if v["status"] == "CAUTION"]

    return {
        "verdict": verdict,
        "checks": checks,
        "no_go_reasons": no_go_reasons,
        "caution_reasons": caution_reasons,
        "summary": "; ".join(no_go_reasons or caution_reasons or ["All constraints clear"]),
    }

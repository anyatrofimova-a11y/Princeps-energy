"""Environmental assessment — real UK data from EA, Natural England, MAGIC APIs."""

from __future__ import annotations

import asyncio
import json
import logging
import math

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.deps import get_pool

log = logging.getLogger("princeps.environment")
router = APIRouter(prefix="/api/environment", tags=["environment"])

_TIMEOUT = 15
_UA = "Princeps/1.0 environmental-assessment"


# ─── Environment Agency Flood Risk API ────────────────────────────────────────

async def _ea_flood_risk(lat: float, lon: float) -> dict:
    """Query Environment Agency flood zone data for a location."""
    result = {
        "flood_zone": None,
        "flood_risk_level": "UNKNOWN",
        "risk_for_insurance": None,
        "flood_alerts": [],
        "surface_water_risk": None,
        "source": "environment.data.gov.uk",
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        # 1. Flood risk zones (via EA flood monitoring stations nearby)
        try:
            resp = await client.get(
                "https://environment.data.gov.uk/flood-monitoring/id/stations",
                params={"lat": lat, "long": lon, "dist": 5},
            )
            if resp.status_code == 200:
                stations = resp.json().get("items", [])
                result["nearby_stations"] = len(stations)
                if stations:
                    result["nearest_station"] = stations[0].get("label", "Unknown")
        except Exception as e:
            log.debug("EA stations query failed: %s", e)

        # 2. Active flood warnings
        try:
            resp = await client.get(
                "https://environment.data.gov.uk/flood-monitoring/id/floods",
                params={"lat": lat, "long": lon, "dist": 10},
            )
            if resp.status_code == 200:
                floods = resp.json().get("items", [])
                result["flood_alerts"] = [
                    {
                        "severity": f.get("severityLevel"),
                        "description": f.get("description", "")[:200],
                        "area": f.get("floodArea", {}).get("label", ""),
                        "raised": f.get("timeRaised"),
                    }
                    for f in floods[:5]
                ]
                if any(f.get("severityLevel") in (1, 2) for f in floods):
                    result["flood_risk_level"] = "HIGH"
                elif floods:
                    result["flood_risk_level"] = "MEDIUM"
        except Exception as e:
            log.debug("EA floods query failed: %s", e)

        # 3. Long Term Flood Risk (LTFR) — GOV.UK
        try:
            resp = await client.get(
                f"https://check-long-term-flood-risk.service.gov.uk/api/risk?easting=0&northing=0",
                params={"lat": lat, "lon": lon},
            )
            # This endpoint may not be public — fallback to heuristic
        except Exception:
            pass

    # Heuristic flood zone from nearby stations and alerts
    if result["flood_risk_level"] == "UNKNOWN":
        if result.get("nearby_stations", 0) > 3:
            result["flood_risk_level"] = "MEDIUM"
            result["flood_zone"] = "2"
        elif result.get("nearby_stations", 0) > 0:
            result["flood_risk_level"] = "LOW"
            result["flood_zone"] = "1"
        else:
            result["flood_risk_level"] = "LOW"
            result["flood_zone"] = "1"

    return result


# ─── Natural England Designations (ArcGIS REST) ──────────────────────────────

NE_SERVICES = {
    "sssi": {
        "url": "https://services.arcgis.com/JJzESW51TqeY9uj5/arcgis/rest/services/SSSI_England/FeatureServer/0/query",
        "label": "Site of Special Scientific Interest",
        "severity": "hard",
    },
    "sac": {
        "url": "https://services.arcgis.com/JJzESW51TqeY9uj5/arcgis/rest/services/Special_Areas_of_Conservation_England/FeatureServer/0/query",
        "label": "Special Area of Conservation",
        "severity": "hard",
    },
    "spa": {
        "url": "https://services.arcgis.com/JJzESW51TqeY9uj5/arcgis/rest/services/Special_Protection_Areas_England/FeatureServer/0/query",
        "label": "Special Protection Area",
        "severity": "hard",
    },
    "ramsar": {
        "url": "https://services.arcgis.com/JJzESW51TqeY9uj5/arcgis/rest/services/Ramsar_England/FeatureServer/0/query",
        "label": "Ramsar Wetland",
        "severity": "hard",
    },
    "aonb": {
        "url": "https://services.arcgis.com/JJzESW51TqeY9uj5/arcgis/rest/services/Areas_of_Outstanding_Natural_Beauty_England/FeatureServer/0/query",
        "label": "Area of Outstanding Natural Beauty / National Landscape",
        "severity": "hard",
    },
    "ancient_woodland": {
        "url": "https://services.arcgis.com/JJzESW51TqeY9uj5/arcgis/rest/services/Ancient_Woodland_England/FeatureServer/0/query",
        "label": "Ancient Woodland",
        "severity": "soft",
    },
}


async def _check_ne_designation(client: httpx.AsyncClient, key: str, svc: dict, lat: float, lon: float, radius_m: float) -> dict | None:
    """Query a Natural England ArcGIS feature service for intersections."""
    try:
        params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "spatialRel": "esriSpatialRelIntersects",
            "distance": radius_m,
            "units": "esriSRUnit_Meter",
            "inSR": "4326",
            "outSR": "4326",
            "outFields": "OBJECTID,NAME,SSSI_NAME,SAC_NAME,SPA_NAME,SITE_NAME",
            "returnGeometry": "false",
            "resultRecordCount": 3,
            "f": "json",
        }
        resp = await client.get(svc["url"], params=params)
        if resp.status_code == 200:
            data = resp.json()
            features = data.get("features", [])
            if features:
                name = "Unknown"
                attrs = features[0].get("attributes", {})
                for field in ["NAME", "SSSI_NAME", "SAC_NAME", "SPA_NAME", "SITE_NAME"]:
                    if attrs.get(field):
                        name = attrs[field]
                        break
                return {
                    "type": key,
                    "label": svc["label"],
                    "name": name,
                    "severity": svc["severity"],
                    "count": len(features),
                    "status": "OVERLAP" if svc["severity"] == "hard" else "NEARBY",
                }
    except Exception as e:
        log.debug("NE %s query failed: %s", key, e)
    return None


async def _check_green_belt(client: httpx.AsyncClient, lat: float, lon: float) -> dict | None:
    """Check Green Belt via planning.data.gov.uk."""
    try:
        resp = await client.get(
            "https://www.planning.data.gov.uk/api/v1/entity.json",
            params={
                "dataset": "green-belt",
                "longitude": lon,
                "latitude": lat,
                "limit": 1,
            },
        )
        if resp.status_code == 200:
            entities = resp.json().get("entities", [])
            if entities:
                return {
                    "type": "green_belt",
                    "label": "Green Belt",
                    "name": entities[0].get("name", "Green Belt"),
                    "severity": "hard",
                    "count": len(entities),
                    "status": "OVERLAP",
                }
    except Exception as e:
        log.debug("Green Belt query failed: %s", e)
    return None


async def _natural_england_designations(lat: float, lon: float, radius_m: float = 1000) -> list[dict]:
    """Query all Natural England designation layers + Green Belt."""
    designations = []
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        import asyncio
        tasks = [_check_ne_designation(client, k, v, lat, lon, radius_m) for k, v in NE_SERVICES.items()]
        tasks.append(_check_green_belt(client, lat, lon))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, dict):
                designations.append(r)
    return designations


# ─── Carbon intensity (real regional) ────────────────────────────────────────

async def _regional_carbon_intensity(lat: float, lon: float) -> dict:
    """Get real carbon intensity from National Grid ESO Carbon Intensity API."""
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": _UA}) as client:
        try:
            resp = await client.get("https://api.carbonintensity.org.uk/intensity")
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if data:
                    intensity = data[0].get("intensity", {})
                    return {
                        "current_gco2_kwh": intensity.get("actual") or intensity.get("forecast"),
                        "forecast_gco2_kwh": intensity.get("forecast"),
                        "index": intensity.get("index"),
                        "source": "api.carbonintensity.org.uk",
                    }
        except Exception as e:
            log.debug("Carbon intensity query failed: %s", e)

    return {"current_gco2_kwh": 200, "forecast_gco2_kwh": 200, "index": "moderate", "source": "fallback"}


# ─── Main assessment endpoint ─────────────────────────────────────────────────

@router.get("/assess")
async def environmental_assessment(
    lat: float = Query(...),
    lon: float = Query(...),
    capacity_mw: float = Query(50.0),
    radius_m: float = Query(1000, description="Search radius for designations"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Comprehensive environmental assessment pulling real UK data:
    - EA flood risk (live flood warnings + monitoring stations)
    - Natural England statutory designations (SSSI, SAC, SPA, Ramsar, AONB, Ancient Woodland)
    - Green Belt (planning.data.gov.uk)
    - GeeFlow satellite data (NDVI, land use, flood risk from JRC)
    - Real-time carbon intensity (National Grid ESO)
    """
    import asyncio

    # Run all data fetches concurrently with overall timeout
    try:
        flood, designations, carbon = await asyncio.wait_for(
            asyncio.gather(
                _ea_flood_risk(lat, lon),
                _natural_england_designations(lat, lon, radius_m),
                _regional_carbon_intensity(lat, lon),
            ),
            timeout=20,
        )
    except asyncio.TimeoutError:
        log.warning("Environmental API calls timed out — using fallbacks")
        flood = {"flood_risk_level": "LOW", "flood_alerts": [], "nearby_stations": 0, "source": "timeout_fallback"}
        designations = []
        carbon = {"current_gco2_kwh": 200, "index": "moderate", "source": "timeout_fallback"}

    # DB queries — GeeFlow extractions (best-effort, non-blocking)
    geeflow_ndvi = None
    geeflow_landuse = None
    geeflow_flood = None

    try:
        async with pool.acquire(timeout=5) as conn:
            for mode, target in [("vegetation", "ndvi"), ("land_use", "landuse"), ("flood_risk", "flood")]:
                try:
                    row = await asyncio.wait_for(conn.fetchrow(
                        """SELECT result_data FROM geeflow_extractions
                           WHERE mode = $1
                           AND ST_DWithin(geometry, ST_SetSRID(ST_MakePoint($2, $3), 4326), 0.05)
                           ORDER BY created_at DESC LIMIT 1""",
                        mode, lon, lat,
                    ), timeout=3)
                    if row and row["result_data"]:
                        data = json.loads(row["result_data"]) if isinstance(row["result_data"], str) else row["result_data"]
                        if target == "ndvi": geeflow_ndvi = data
                        elif target == "landuse": geeflow_landuse = data
                        elif target == "flood": geeflow_flood = data
                except Exception:
                    pass

            # DC constraint zones (pre-ingested, best-effort)
            try:
                db_constraints = await asyncio.wait_for(conn.fetch(
                    """SELECT zone_type, zone_name
                       FROM dc_constraint_zones
                       WHERE ST_DWithin(
                           geometry,
                           ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                           $3
                       )
                       LIMIT 10""",
                    lon, lat, radius_m,
                ), timeout=5)
                for c in db_constraints:
                    if not any(d["type"] == c["zone_type"] for d in designations):
                        designations.append({
                            "type": c["zone_type"],
                            "label": c["zone_type"].upper().replace("_", " "),
                            "name": c["zone_name"],
                            "severity": "hard" if c["zone_type"] in ("sssi", "sac", "spa", "ramsar", "aonb", "green_belt") else "soft",
                            "status": "OVERLAP",
                            "source": "postgis",
                        })
            except Exception:
                pass
    except Exception as e:
        log.debug("DB queries skipped: %s", e)

    # Compute scores
    env_score = 85  # start optimistic
    planning_score = 80

    # Flood penalty
    if flood["flood_risk_level"] == "HIGH":
        env_score -= 30
        planning_score -= 25
    elif flood["flood_risk_level"] == "MEDIUM":
        env_score -= 15
        planning_score -= 10

    # JRC flood data
    jrc_risk = None
    if geeflow_flood:
        water_pct = geeflow_flood.get("water_occurrence_pct", 0)
        if water_pct > 25:
            jrc_risk = "HIGH"
            env_score -= 20
        elif water_pct > 5:
            jrc_risk = "MEDIUM"
            env_score -= 10
        else:
            jrc_risk = "LOW"

    # Designation penalties
    hard_count = sum(1 for d in designations if d["severity"] == "hard")
    soft_count = sum(1 for d in designations if d["severity"] == "soft")
    env_score -= hard_count * 25
    env_score -= soft_count * 10
    planning_score -= hard_count * 30
    planning_score -= soft_count * 5

    # NDVI
    ndvi_mean = geeflow_ndvi.get("mean_ndvi") if geeflow_ndvi else None
    if ndvi_mean is not None:
        if ndvi_mean > 0.7:
            env_score -= 10  # dense vegetation — ecologically sensitive
        elif ndvi_mean < 0.3:
            env_score += 5   # sparse — good for solar

    # Land use
    dominant_class = geeflow_landuse.get("dominant_class") if geeflow_landuse else None
    if dominant_class in ("trees", "water"):
        env_score -= 15
        planning_score -= 10

    env_score = max(5, min(95, env_score))
    planning_score = max(5, min(95, planning_score))

    # Carbon offset calculation (real intensity)
    ci = carbon.get("current_gco2_kwh") or 200
    # Solar CF ~11%, annual gen = capacity_mw * 8760 * 0.11
    annual_mwh = capacity_mw * 8760 * 0.11
    co2_avoided_tonnes = round(annual_mwh * ci / 1000, 0)
    co2_25yr = round(co2_avoided_tonnes * 25, 0)
    equivalent_cars = round(co2_avoided_tonnes / 2.3, 0)
    equivalent_homes = round(annual_mwh / 3.5, 0)

    # Verdict
    if hard_count > 0 or env_score < 30:
        verdict = "NO-GO"
    elif env_score < 60 or planning_score < 50:
        verdict = "CAUTION"
    else:
        verdict = "GO"

    return {
        "verdict": verdict,
        "environmental_score": env_score,
        "planning_score": planning_score,
        "flood_risk": {
            **flood,
            "jrc_risk_level": jrc_risk,
            "jrc_water_occurrence_pct": geeflow_flood.get("water_occurrence_pct") if geeflow_flood else None,
        },
        "designations": designations,
        "hard_constraints": hard_count,
        "soft_constraints": soft_count,
        "vegetation": {
            "mean_ndvi": ndvi_mean,
            "monthly_ndvi": geeflow_ndvi.get("monthly_ndvi") if geeflow_ndvi else None,
            "source": "sentinel2_geeflow" if geeflow_ndvi else None,
        },
        "land_use": {
            "dominant_class": dominant_class,
            "class_percentages": geeflow_landuse.get("class_percentages") if geeflow_landuse else None,
            "source": "dynamicworld_geeflow" if geeflow_landuse else None,
        },
        "carbon_impact": {
            "grid_intensity_gco2_kwh": ci,
            "intensity_index": carbon.get("index"),
            "annual_generation_mwh": round(annual_mwh, 0),
            "co2_avoided_tonnes_yr": co2_avoided_tonnes,
            "co2_avoided_25yr": co2_25yr,
            "equivalent_cars_removed": equivalent_cars,
            "equivalent_homes_powered": equivalent_homes,
        },
        "biodiversity": {
            "bng_required": True,
            "bng_minimum_pct": 10,
            "bng_measures": [
                "Wildflower meadow creation between panel rows",
                "Native hedgerow planting along site boundaries",
                "Habitat corridors connecting existing ecological features",
                "Pond and wetland creation for amphibians",
                "Bat and bird boxes on site infrastructure",
            ],
            "bng_metric": "DEFRA Biodiversity Metric 4.2",
        },
    }


# ─── Combined environmental & heritage constraints endpoint ──────────────────

@router.get("/constraints")
async def environmental_constraints(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_m: float = Query(2000, description="Search radius in metres"),
):
    """
    Check all environmental, flood, and heritage constraints at a location.

    Queries in parallel:
    - Natural England designations (SSSI, SAC, SPA, AONB, National Parks, Ramsar)
    - Environment Agency flood risk zones and warnings
    - Historic England listed buildings

    All data from free public UK government APIs (OGL licensed).
    """
    from utils.environmental_constraints import check_all_constraints

    try:
        result = await asyncio.wait_for(
            check_all_constraints(lat, lon, radius_m),
            timeout=25,
        )
        return result
    except asyncio.TimeoutError:
        log.warning("Environmental constraints check timed out for (%s, %s)", lat, lon)
        return {
            "lat": lat,
            "lon": lon,
            "radius_m": radius_m,
            "overall_risk_level": "unknown",
            "overall_planning_impact": "Constraint check timed out — retry or perform manual assessment.",
            "environmental": {"constraints_found": False, "designations": [], "risk_level": "unknown"},
            "flood": {"flood_zone": None, "risk_level": "unknown"},
            "heritage": {"listed_buildings": [], "risk_level": "unknown"},
            "error": "timeout",
        }

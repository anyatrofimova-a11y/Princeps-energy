"""
Environmental constraint data ingester — Natural England designations,
EA flood risk, Historic England listed buildings.

Sources (all free, public, OGL licensed):
- SSSI (Sites of Special Scientific Interest) — ~4,127 sites
- SAC (Special Areas of Conservation) — ~254 sites
- SPA (Special Protection Areas) — ~76 sites
- AONB (Areas of Outstanding Natural Beauty) — ~34 areas
- National Parks — 15 parks
- Ramsar wetlands — ~73 sites
- EA Flood Zones (Environment Agency)
- Listed Buildings (Historic England)

All data queried via ArcGIS REST / EA REST APIs with spatial filters.
No authentication required.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

import httpx

log = logging.getLogger("princeps.environmental_constraints")

_TIMEOUT = 15
_UA = "Princeps/1.0 environmental-constraints"

# ---------------------------------------------------------------------------
# Module-level cache — keyed by (lat rounded to 0.01, lon rounded to 0.01)
# Entries expire after 1 hour.
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 3600  # 1 hour


def _cache_key(prefix: str, lat: float, lon: float, radius_m: float = 0) -> str:
    return f"{prefix}:{round(lat, 2)}:{round(lon, 2)}:{int(radius_m)}"


def _cache_get(key: str) -> dict | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL:
        return entry[1]
    if entry:
        del _cache[key]
    return None


def _cache_set(key: str, value: dict) -> None:
    _cache[key] = (time.time(), value)
    # Prune if too large
    if len(_cache) > 500:
        cutoff = time.time() - _CACHE_TTL
        expired = [k for k, (t, _) in _cache.items() if t < cutoff]
        for k in expired:
            del _cache[k]


# ---------------------------------------------------------------------------
# 1. Natural England Designations (ArcGIS REST API)
# ---------------------------------------------------------------------------

# ArcGIS REST service base for Natural England
_NE_BASE = "https://services.arcgis.com/JJzESW51TqeY9uj4/arcgis/rest/services"

NE_LAYERS = {
    "SSSI": {
        "service": "Sites_of_Special_Scientific_Interest_England",
        "name_fields": ["SSSI_NAME", "NAME", "SITE_NAME"],
        "severity": "very_high",
    },
    "SAC": {
        "service": "Special_Areas_of_Conservation_England",
        "name_fields": ["SAC_NAME", "NAME", "SITE_NAME"],
        "severity": "very_high",
    },
    "SPA": {
        "service": "Special_Protection_Areas_England",
        "name_fields": ["SPA_NAME", "NAME", "SITE_NAME"],
        "severity": "very_high",
    },
    "AONB": {
        "service": "Areas_of_Outstanding_Natural_Beauty_England",
        "name_fields": ["AONB_NAME", "NAME", "DESIG_NAME"],
        "severity": "high",
    },
    "National_Park": {
        "service": "National_Parks_England",
        "name_fields": ["NAME", "NP_NAME", "DESIG_NAME"],
        "severity": "high",
    },
    "Ramsar": {
        "service": "Ramsar_England",
        "name_fields": ["NAME", "RAMSAR_NAM", "SITE_NAME"],
        "severity": "very_high",
    },
}


async def _query_ne_layer(
    client: httpx.AsyncClient,
    layer_type: str,
    cfg: dict,
    lat: float,
    lon: float,
    radius_m: float,
) -> list[dict]:
    """Query a single Natural England ArcGIS layer. Returns list of hits."""
    url = f"{_NE_BASE}/{cfg['service']}/FeatureServer/0/query"

    results = []

    # First query: check if point is INSIDE a designation (no buffer)
    inside_params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outSR": "4326",
        "outFields": "*",
        "returnGeometry": "false",
        "resultRecordCount": 5,
        "f": "json",
    }
    try:
        resp = await client.get(url, params=inside_params)
        if resp.status_code == 200:
            data = resp.json()
            for feat in data.get("features", []):
                attrs = feat.get("attributes", {})
                name = _extract_name(attrs, cfg["name_fields"])
                results.append({
                    "type": layer_type,
                    "name": name,
                    "distance_m": 0,
                    "inside": True,
                })
    except Exception as e:
        log.debug("NE %s inside query failed: %s", layer_type, e)

    # Second query: proximity search with buffer (only if not already inside)
    if not results and radius_m > 0:
        buffer_params = {
            "geometry": f"{lon},{lat}",
            "geometryType": "esriGeometryPoint",
            "spatialRel": "esriSpatialRelIntersects",
            "distance": radius_m,
            "units": "esriSRUnit_Meter",
            "inSR": "4326",
            "outSR": "4326",
            "outFields": "*",
            "returnGeometry": "true",
            "resultRecordCount": 5,
            "f": "json",
        }
        try:
            resp = await client.get(url, params=buffer_params)
            if resp.status_code == 200:
                data = resp.json()
                for feat in data.get("features", []):
                    attrs = feat.get("attributes", {})
                    name = _extract_name(attrs, cfg["name_fields"])
                    # Estimate distance from geometry if available
                    geom = feat.get("geometry")
                    dist = _estimate_distance(lat, lon, geom) if geom else radius_m / 2
                    results.append({
                        "type": layer_type,
                        "name": name,
                        "distance_m": round(dist),
                        "inside": False,
                    })
        except Exception as e:
            log.debug("NE %s buffer query failed: %s", layer_type, e)

    return results


def _extract_name(attrs: dict, name_fields: list[str]) -> str:
    """Extract the best name from ArcGIS attributes."""
    for f in name_fields:
        val = attrs.get(f)
        if val and str(val).strip() and str(val).strip().lower() != "none":
            return str(val).strip()
    # Fallback — try any attribute that looks like a name
    for k, v in attrs.items():
        if "name" in k.lower() and v and str(v).strip().lower() != "none":
            return str(v).strip()
    return "Unknown"


def _estimate_distance(lat: float, lon: float, geom: dict) -> float:
    """Rough distance estimate from a point to the nearest vertex of a geometry."""
    rings = geom.get("rings", [])
    if not rings:
        # Point geometry
        x, y = geom.get("x", lon), geom.get("y", lat)
        return _haversine(lat, lon, y, x)

    min_dist = float("inf")
    for ring in rings:
        for coord in ring:
            if len(coord) >= 2:
                d = _haversine(lat, lon, coord[1], coord[0])
                if d < min_dist:
                    min_dist = d
    return min_dist if min_dist < float("inf") else 500


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _risk_level_from_designations(designations: list[dict]) -> str:
    """Compute overall risk level from designation hits."""
    if not designations:
        return "low"
    inside_types = {d["type"] for d in designations if d.get("inside")}
    nearby_types = {d["type"] for d in designations if not d.get("inside")}
    nearby_dists = [d["distance_m"] for d in designations if not d.get("inside")]

    # Inside SSSI/SAC/SPA/Ramsar = very_high
    if inside_types & {"SSSI", "SAC", "SPA", "Ramsar"}:
        return "very_high"
    # Inside AONB/National Park = high
    if inside_types & {"AONB", "National_Park"}:
        return "high"
    # Within 500m of SSSI/SAC/SPA/Ramsar = high
    for d in designations:
        if not d.get("inside") and d["type"] in {"SSSI", "SAC", "SPA", "Ramsar"} and d["distance_m"] < 500:
            return "high"
    # Within 500m of anything = medium
    if any(dist < 500 for dist in nearby_dists):
        return "medium"
    # Within radius but >500m = low
    return "low"


def _planning_impact_text(designations: list[dict]) -> str:
    """Generate planning impact summary from designations."""
    if not designations:
        return "No environmental designations found within search radius. Standard planning assessment applies."

    impacts = []
    inside_types = {d["type"] for d in designations if d.get("inside")}
    nearby = [d for d in designations if not d.get("inside")]

    if "SSSI" in inside_types:
        impacts.append("Site is within a SSSI — development likely requires an Environmental Impact Assessment (EIA) and Natural England consent. Presumption against development unless exceptional circumstances.")
    if "SAC" in inside_types or "SPA" in inside_types:
        impacts.append("Site is within a Habitats Regulations site (SAC/SPA) — Appropriate Assessment required under Conservation of Habitats and Species Regulations 2017. Very high bar for planning consent.")
    if "Ramsar" in inside_types:
        impacts.append("Site is within a Ramsar wetland — treated as European site in planning policy. Appropriate Assessment required.")
    if "AONB" in inside_types:
        impacts.append("Site is within an AONB (National Landscape) — landscape impact assessment required. Major development only in exceptional circumstances (NPPF para 177).")
    if "National_Park" in inside_types:
        impacts.append("Site is within a National Park — highest level of landscape protection. Major development only in exceptional circumstances.")

    for d in nearby:
        if d["type"] in {"SSSI", "SAC", "SPA", "Ramsar"} and d["distance_m"] < 500:
            impacts.append(f"{d['type']} ({d['name']}) within {d['distance_m']}m — Natural England consultation triggered. Impact on designated features must be assessed.")
        elif d["type"] in {"AONB", "National_Park"} and d["distance_m"] < 1000:
            impacts.append(f"{d['type'].replace('_', ' ')} ({d['name']}) within {d['distance_m']}m — setting impact assessment may be required.")

    return " ".join(impacts) if impacts else "Environmental designations nearby but unlikely to prevent development. Standard ecological surveys recommended."


async def check_environmental_constraints(
    lat: float, lon: float, radius_m: float = 2000
) -> dict:
    """
    Check all Natural England environmental designations at a location.

    Returns dict with designations found, risk level, and planning impact.
    """
    ck = _cache_key("env", lat, lon, radius_m)
    cached = _cache_get(ck)
    if cached:
        return cached

    all_designations: list[dict] = []
    geojson_features: list[dict] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        tasks = [
            _query_ne_layer(client, ltype, cfg, lat, lon, radius_m)
            for ltype, cfg in NE_LAYERS.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                all_designations.extend(result)
            elif isinstance(result, Exception):
                log.debug("NE query exception: %s", result)

    # Build GeoJSON for map overlay (circles around designations for now)
    for d in all_designations:
        geojson_features.append({
            "type": "Feature",
            "properties": {
                "type": d["type"],
                "name": d["name"],
                "inside": d["inside"],
                "distance_m": d["distance_m"],
                "severity": NE_LAYERS.get(d["type"], {}).get("severity", "medium"),
            },
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
        })

    risk = _risk_level_from_designations(all_designations)
    impact = _planning_impact_text(all_designations)

    result = {
        "constraints_found": len(all_designations) > 0,
        "designations": all_designations,
        "risk_level": risk,
        "planning_impact": impact,
        "designation_count": len(all_designations),
        "inside_count": sum(1 for d in all_designations if d.get("inside")),
        "constraints_geojson": {
            "type": "FeatureCollection",
            "features": geojson_features,
        } if geojson_features else None,
        "source": "naturalengland-defra.opendata.arcgis.com",
    }

    _cache_set(ck, result)
    return result


# ---------------------------------------------------------------------------
# 2. Environment Agency Flood Risk
# ---------------------------------------------------------------------------

_EA_FLOOD_BASE = "https://environment.data.gov.uk/flood-monitoring"


async def check_flood_risk(lat: float, lon: float) -> dict:
    """
    Check Environment Agency flood risk at a location.

    Queries:
    - Flood monitoring areas (within 2km)
    - Active flood warnings
    - Flood zone classification
    """
    ck = _cache_key("flood", lat, lon)
    cached = _cache_get(ck)
    if cached:
        return cached

    result: dict[str, Any] = {
        "flood_zone": None,
        "risk_level": "unknown",
        "flood_areas": [],
        "active_warnings": [],
        "planning_impact": "",
        "source": "environment.data.gov.uk",
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        # 1. Flood areas near the point
        try:
            resp = await client.get(
                f"{_EA_FLOOD_BASE}/id/floodAreas",
                params={"lat": lat, "long": lon, "dist": 2},
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                for area in items[:10]:
                    result["flood_areas"].append({
                        "notation": area.get("notation", ""),
                        "label": area.get("label", ""),
                        "river_or_sea": area.get("riverOrSea", ""),
                        "flood_watch_area": area.get("floodWatchArea", {}).get("label", "") if isinstance(area.get("floodWatchArea"), dict) else "",
                    })
        except Exception as e:
            log.debug("EA flood areas query failed: %s", e)

        # 2. Active flood warnings
        try:
            resp = await client.get(
                f"{_EA_FLOOD_BASE}/id/floods",
                params={"lat": lat, "long": lon, "dist": 10},
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                for w in items[:5]:
                    result["active_warnings"].append({
                        "severity": w.get("severityLevel"),
                        "severity_label": w.get("severity", ""),
                        "description": (w.get("description") or "")[:200],
                        "area": w.get("floodArea", {}).get("label", "") if isinstance(w.get("floodArea"), dict) else "",
                        "time_raised": w.get("timeRaised"),
                        "message": (w.get("message") or "")[:300],
                    })
        except Exception as e:
            log.debug("EA flood warnings query failed: %s", e)

        # 3. Flood monitoring stations (density indicates flood-prone area)
        station_count = 0
        try:
            resp = await client.get(
                f"{_EA_FLOOD_BASE}/id/stations",
                params={"lat": lat, "long": lon, "dist": 3},
            )
            if resp.status_code == 200:
                stations = resp.json().get("items", [])
                station_count = len(stations)
        except Exception as e:
            log.debug("EA stations query failed: %s", e)

    # Determine flood zone and risk from available data
    warning_severities = [w.get("severity") for w in result["active_warnings"]]
    has_severe = any(s in (1, 2) for s in warning_severities if isinstance(s, int))
    has_warnings = len(result["active_warnings"]) > 0
    area_count = len(result["flood_areas"])

    if has_severe:
        result["flood_zone"] = "3"
        result["risk_level"] = "very_high"
    elif has_warnings:
        result["flood_zone"] = "3"
        result["risk_level"] = "high"
    elif area_count >= 3:
        result["flood_zone"] = "2"
        result["risk_level"] = "medium"
    elif area_count >= 1 or station_count > 3:
        result["flood_zone"] = "2"
        result["risk_level"] = "low"
    else:
        result["flood_zone"] = "1"
        result["risk_level"] = "low"

    # Planning impact text
    zone = result["flood_zone"]
    if zone == "3" or zone == "3b":
        result["planning_impact"] = (
            "Flood Zone 3 — high probability of flooding. Sequential and Exception Tests required. "
            "Solar/battery installations may be acceptable as 'less vulnerable' but require Flood Risk Assessment (FRA). "
            "Functional floodplain (3b) — only water-compatible development permitted."
        )
    elif zone == "2":
        result["planning_impact"] = (
            "Flood Zone 2 — medium probability of flooding. Sequential Test required. "
            "Renewable energy installations generally acceptable with site-specific Flood Risk Assessment."
        )
    else:
        result["planning_impact"] = (
            "Flood Zone 1 — low probability of flooding. No flood-related planning constraints. "
            "FRA only required for sites >1 hectare."
        )

    result["nearby_stations"] = station_count

    _cache_set(ck, result)
    return result


# ---------------------------------------------------------------------------
# 3. Historic England Listed Buildings (ArcGIS REST API)
# ---------------------------------------------------------------------------

_HE_LISTED_URL = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services/Listed_Buildings/FeatureServer/0/query"


async def check_heritage_constraints(
    lat: float, lon: float, radius_m: float = 1000
) -> dict:
    """
    Check Historic England listed buildings near a location.

    Returns listed buildings within radius with grade, distance, and planning impact.
    """
    ck = _cache_key("heritage", lat, lon, radius_m)
    cached = _cache_get(ck)
    if cached:
        return cached

    listed_buildings: list[dict] = []
    geojson_features: list[dict] = []

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as client:
        try:
            params = {
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "distance": radius_m,
                "units": "esriSRUnit_Meter",
                "inSR": "4326",
                "outSR": "4326",
                "outFields": "Name,Grade,ListEntry,Location",
                "returnGeometry": "true",
                "resultRecordCount": 50,
                "f": "json",
            }
            resp = await client.get(_HE_LISTED_URL, params=params)
            if resp.status_code == 200:
                data = resp.json()
                for feat in data.get("features", []):
                    attrs = feat.get("attributes", {})
                    geom = feat.get("geometry", {})

                    # Calculate distance
                    bx = geom.get("x", lon)
                    by = geom.get("y", lat)
                    dist = _haversine(lat, lon, by, bx)

                    grade = attrs.get("Grade", "II")
                    name = attrs.get("Name", "Unknown")
                    list_entry = attrs.get("ListEntry", "")

                    listed_buildings.append({
                        "name": name,
                        "grade": grade,
                        "distance_m": round(dist),
                        "list_entry": list_entry,
                    })

                    geojson_features.append({
                        "type": "Feature",
                        "properties": {
                            "name": name,
                            "grade": grade,
                            "list_entry": list_entry,
                            "distance_m": round(dist),
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [bx, by],
                        },
                    })
        except Exception as e:
            log.debug("Historic England query failed: %s", e)

    # Sort by distance
    listed_buildings.sort(key=lambda b: b["distance_m"])

    # Risk assessment
    grade_i = [b for b in listed_buildings if b["grade"] == "I"]
    grade_ii_star = [b for b in listed_buildings if b["grade"] == "II*"]
    grade_ii = [b for b in listed_buildings if b["grade"] == "II"]

    if any(b["distance_m"] < 100 for b in grade_i):
        risk_level = "very_high"
    elif any(b["distance_m"] < 200 for b in grade_i) or any(b["distance_m"] < 100 for b in grade_ii_star):
        risk_level = "high"
    elif any(b["distance_m"] < 200 for b in grade_ii_star) or any(b["distance_m"] < 100 for b in grade_ii):
        risk_level = "medium"
    elif listed_buildings:
        risk_level = "low"
    else:
        risk_level = "none"

    # Planning impact
    impacts = []
    if grade_i:
        nearest_gi = min(b["distance_m"] for b in grade_i)
        impacts.append(f"Grade I listed building within {nearest_gi}m — highest heritage significance. Development must demonstrate no harm to setting. Heritage Impact Assessment (HIA) essential.")
    if grade_ii_star:
        nearest_gii = min(b["distance_m"] for b in grade_ii_star)
        impacts.append(f"Grade II* listed building within {nearest_gii}m — very important heritage asset. Setting assessment required.")
    if grade_ii:
        nearest = min(b["distance_m"] for b in grade_ii)
        impacts.append(f"{len(grade_ii)} Grade II listed building(s), nearest at {nearest}m. Impact on setting should be considered.")

    if not impacts:
        planning_impact = "No listed buildings found within search radius. Standard heritage assessment applies."
    else:
        planning_impact = " ".join(impacts)

    result = {
        "listed_buildings": listed_buildings[:20],  # Cap at 20
        "total_count": len(listed_buildings),
        "grade_i_count": len(grade_i),
        "grade_ii_star_count": len(grade_ii_star),
        "grade_ii_count": len(grade_ii),
        "risk_level": risk_level,
        "planning_impact": planning_impact,
        "heritage_geojson": {
            "type": "FeatureCollection",
            "features": geojson_features[:20],
        } if geojson_features else None,
        "source": "historicengland.org.uk",
    }

    _cache_set(ck, result)
    return result


# ---------------------------------------------------------------------------
# 4. Combined constraint check
# ---------------------------------------------------------------------------


def _overall_risk(env_risk: str, flood_risk: str, heritage_risk: str) -> str:
    """Return the highest risk level across all constraint types."""
    levels = {"none": 0, "low": 1, "unknown": 1, "medium": 2, "high": 3, "very_high": 4}
    max_level = max(
        levels.get(env_risk, 1),
        levels.get(flood_risk, 1),
        levels.get(heritage_risk, 0),
    )
    for name, val in levels.items():
        if val == max_level and name not in ("none", "unknown"):
            return name
    return "low"


async def check_all_constraints(
    lat: float, lon: float, radius_m: float = 2000
) -> dict:
    """
    Run all three constraint checks in parallel and merge results.

    Returns a combined assessment with overall risk level.
    """
    ck = _cache_key("all", lat, lon, radius_m)
    cached = _cache_get(ck)
    if cached:
        return cached

    env_result, flood_result, heritage_result = await asyncio.gather(
        check_environmental_constraints(lat, lon, radius_m),
        check_flood_risk(lat, lon),
        check_heritage_constraints(lat, lon, min(radius_m, 1000)),
        return_exceptions=True,
    )

    # Handle exceptions
    if isinstance(env_result, Exception):
        log.warning("Environmental constraints check failed: %s", env_result)
        env_result = {"constraints_found": False, "designations": [], "risk_level": "unknown", "planning_impact": "Check failed — manual review needed."}
    if isinstance(flood_result, Exception):
        log.warning("Flood risk check failed: %s", flood_result)
        flood_result = {"flood_zone": None, "risk_level": "unknown", "flood_areas": [], "planning_impact": "Check failed — manual review needed."}
    if isinstance(heritage_result, Exception):
        log.warning("Heritage constraints check failed: %s", heritage_result)
        heritage_result = {"listed_buildings": [], "risk_level": "none", "planning_impact": "Check failed — manual review needed."}

    overall = _overall_risk(
        env_result.get("risk_level", "low"),
        flood_result.get("risk_level", "low"),
        heritage_result.get("risk_level", "none"),
    )

    # Merge all planning impacts
    all_impacts = []
    for r in (env_result, flood_result, heritage_result):
        impact = r.get("planning_impact", "")
        if impact:
            all_impacts.append(impact)

    # Build combined constraint GeoJSON for map overlay
    combined_features = []

    # Add environmental designations as polygons/points (red for SSSI, amber for AONB)
    env_geojson = env_result.get("constraints_geojson")
    if env_geojson and env_geojson.get("features"):
        for f in env_geojson["features"]:
            f["properties"]["constraint_category"] = "environmental"
            color = "#e53935" if f["properties"].get("severity") == "very_high" else "#ff8f00"
            f["properties"]["color"] = color
            combined_features.append(f)

    # Add heritage as purple dots
    heritage_geojson = heritage_result.get("heritage_geojson")
    if heritage_geojson and heritage_geojson.get("features"):
        for f in heritage_geojson["features"]:
            f["properties"]["constraint_category"] = "heritage"
            f["properties"]["color"] = "#9C27B0"
            combined_features.append(f)

    # Build flood zone indicator
    if flood_result.get("flood_zone") and flood_result["flood_zone"] != "1":
        combined_features.append({
            "type": "Feature",
            "properties": {
                "constraint_category": "flood",
                "flood_zone": flood_result["flood_zone"],
                "risk_level": flood_result["risk_level"],
                "color": "#1565c0",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
        })

    result = {
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "overall_risk_level": overall,
        "overall_planning_impact": " ".join(all_impacts),
        "environmental": env_result,
        "flood": flood_result,
        "heritage": heritage_result,
        "constraint_summary": {
            "designation_count": env_result.get("designation_count", 0),
            "inside_designation": env_result.get("inside_count", 0) > 0,
            "flood_zone": flood_result.get("flood_zone"),
            "listed_buildings_count": heritage_result.get("total_count", 0),
            "grade_i_buildings": heritage_result.get("grade_i_count", 0),
        },
        "constraints_geojson": {
            "type": "FeatureCollection",
            "features": combined_features,
        } if combined_features else None,
    }

    _cache_set(ck, result)
    return result

"""
DC Constraint Overlay Engine — hard/soft constraint checking for data centre site selection.

Evaluates prospective data centre sites against UK planning constraints:
  Hard exclusions (NO-GO): Flood Zone 2/3, SSSI, SAC, SPA, Ramsar, AONB, Green Belt, ALC Grade 1-2
  Soft penalties (scoring): Surface water risk, conservation areas, listed buildings,
                            residential proximity, ancient woodland

Data sources (PostGIS first, API fallback):
  - dc_constraint_zones table (pre-ingested boundaries)
  - Natural England ArcGIS REST services (SSSI, SAC, SPA, AONB, ALC, ancient woodland)
  - planning.data.gov.uk (Green Belt, conservation areas)
  - EA flood data (via geeflow_extractions table)

Called from FastAPI endpoints and agent module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.dc_constraints")

_TIMEOUT = 45
_USER_AGENT = "Princeps/1.0 dc-constraint-overlay"

# ─── Hard Constraint Types ────────────────────────────────────────────────

HARD_TYPES = ["sssi", "sac", "spa", "ramsar", "aonb", "green_belt", "alc_12"]

HARD_LABELS = {
    "sssi": "Site of Special Scientific Interest",
    "sac": "Special Area of Conservation",
    "spa": "Special Protection Area",
    "ramsar": "Ramsar Wetland",
    "aonb": "Area of Outstanding Natural Beauty / National Landscape",
    "green_belt": "Green Belt",
    "alc_12": "Grade 1-2 Agricultural Land (Best & Most Versatile)",
}

# ─── Soft Constraint Types & Penalties ────────────────────────────────────

SOFT_CONSTRAINTS = {
    "flood_surface_water": {"label": "Flood Zone 1 with surface water risk", "penalty": -10},
    "conservation_area": {"label": "Conservation area", "penalty": -15},
    "listed_building": {"label": "Listed building within 500m", "penalty": -10},
    "residential_proximity": {"label": "Residential proximity within 200m (noise)", "penalty": -20},
    "ancient_woodland": {"label": "Ancient woodland within 500m", "penalty": -10},
}

# ─── Natural England ArcGIS REST Endpoints ────────────────────────────────

NATURAL_ENGLAND_SERVICES = {
    "sssi": "https://services.arcgis.com/JJzESW51TqeY9uj9/arcgis/rest/services/SSSI_England/FeatureServer/0/query",
    "sac": "https://services.arcgis.com/JJzESW51TqeY9uj9/arcgis/rest/services/Special_Areas_of_Conservation_England/FeatureServer/0/query",
    "spa": "https://services.arcgis.com/JJzESW51TqeY9uj9/arcgis/rest/services/Special_Protection_Areas_England/FeatureServer/0/query",
    "aonb": "https://services.arcgis.com/JJzESW51TqeY9uj9/arcgis/rest/services/Areas_of_Outstanding_Natural_Beauty_England/FeatureServer/0/query",
    "ancient_woodland": "https://services.arcgis.com/JJzESW51TqeY9uj9/arcgis/rest/services/Ancient_Woodland_England/FeatureServer/0/query",
    "ramsar": "https://services.arcgis.com/JJzESW51TqeY9uj9/arcgis/rest/services/Ramsar_England/FeatureServer/0/query",
    "alc": "https://services.arcgis.com/JJzESW51TqeY9uj9/arcgis/rest/services/Provisional_Agricultural_Land_Classification_ALC_England/FeatureServer/0/query",
}

# Natural England feature name fields per layer
_NE_NAME_FIELDS = {
    "sssi": "SSSI_NAME",
    "sac": "SAC_NAME",
    "spa": "SPA_NAME",
    "aonb": "AONB_NAME",
    "ancient_woodland": "NAME",
    "ramsar": "NAME",
    "alc": "ALC_GRADE",
}

# planning.data.gov.uk entity endpoints
PLANNING_DATA_SERVICES = {
    "green_belt": "https://www.planning.data.gov.uk/api/v1/entity.geojson",
    "conservation_area": "https://www.planning.data.gov.uk/api/v1/entity.geojson",
}

PLANNING_DATA_DATASETS = {
    "green_belt": "green-belt",
    "conservation_area": "conservation-area",
}


# ─── Table DDL ────────────────────────────────────────────────────────────


async def setup_constraint_tables(conn: asyncpg.Connection) -> None:
    """Create the dc_constraint_zones table and indices if not present."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS dc_constraint_zones (
            zone_id       SERIAL PRIMARY KEY,
            zone_type     TEXT NOT NULL,
            name          TEXT,
            designation   TEXT,
            area_ha       DOUBLE PRECISION,
            lat           DOUBLE PRECISION,
            lon           DOUBLE PRECISION,
            geometry      GEOMETRY(Geometry, 27700),
            source        TEXT DEFAULT 'natural_england',
            created_at    TIMESTAMPTZ DEFAULT NOW(),
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dc_constraint_zones_geom "
        "ON dc_constraint_zones USING GIST (geometry)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dc_constraint_zones_type "
        "ON dc_constraint_zones (zone_type)"
    )
    log.info("dc_constraint_zones table ensured")


# ─── Main Entry Point ─────────────────────────────────────────────────────


async def check_constraints(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    radius_m: float = 1000,
) -> dict:
    """
    Check hard and soft planning constraints around a candidate DC site.

    Args:
        conn: asyncpg database connection.
        lat: WGS-84 latitude.
        lon: WGS-84 longitude.
        radius_m: Search radius in metres (default 1000).

    Returns:
        {
            "constraint_score": 0-100,
            "hard_constraints": [...],
            "soft_constraints": [...],
            "is_clear": bool,
            "total_penalty": int,
            "flood_zone": str | None,
            "green_belt": bool,
            "agricultural_grade": str | None,
            "summary": str,
        }
    """
    t0 = time.time()

    # Run hard and soft checks concurrently
    hard_task = _check_hard_constraints(conn, lat, lon, radius_m)
    soft_task = _check_soft_constraints(conn, lat, lon, radius_m)
    flood_task = _check_flood_zone(conn, lat, lon)

    hard_constraints, soft_constraints, flood_info = await asyncio.gather(
        hard_task, soft_task, flood_task,
    )

    # Determine flags
    green_belt = any(c["type"] == "green_belt" for c in hard_constraints)
    agricultural_grade = None
    for c in hard_constraints:
        if c["type"] == "alc_12":
            agricultural_grade = c.get("designation", "Grade 1-2")
            break

    flood_zone = flood_info.get("zone")

    # Add flood zone 2/3 as hard constraint if present
    if flood_zone in ("2", "3", "3a", "3b"):
        hard_constraints.append({
            "type": "flood_zone_23",
            "name": f"Flood Zone {flood_zone}",
            "distance_m": 0.0,
            "status": "NO-GO",
        })

    # Add surface water risk as soft constraint
    if flood_info.get("surface_water_risk") and flood_zone in (None, "1"):
        soft_constraints.append({
            "type": "flood_surface_water",
            "name": "Surface water flood risk present",
            "distance_m": 0.0,
            "penalty": SOFT_CONSTRAINTS["flood_surface_water"]["penalty"],
        })

    # Scoring
    is_clear = len(hard_constraints) == 0
    if not is_clear:
        constraint_score = 0
        total_penalty = -100
    else:
        total_penalty = sum(c["penalty"] for c in soft_constraints)
        constraint_score = max(0, 100 + total_penalty)

    # Summary text
    summary = _build_summary(
        hard_constraints, soft_constraints, constraint_score, flood_zone,
        green_belt, agricultural_grade,
    )

    elapsed = round(time.time() - t0, 2)
    log.info(
        "Constraint check for (%.5f, %.5f) r=%dm — score=%d, hard=%d, soft=%d [%.2fs]",
        lat, lon, int(radius_m), constraint_score,
        len(hard_constraints), len(soft_constraints), elapsed,
    )

    return {
        "constraint_score": constraint_score,
        "hard_constraints": hard_constraints,
        "soft_constraints": soft_constraints,
        "is_clear": is_clear,
        "total_penalty": total_penalty,
        "flood_zone": flood_zone,
        "green_belt": green_belt,
        "agricultural_grade": agricultural_grade,
        "summary": summary,
    }


# ─── Hard Constraint Checks ──────────────────────────────────────────────


async def _check_hard_constraints(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    radius_m: float,
) -> list[dict]:
    """Query all hard constraint zones intersecting the site buffer."""
    results: list[dict] = []

    # 1. Check PostGIS table first
    try:
        rows = await conn.fetch("""
            SELECT zone_type, name, designation,
                   ST_Distance(
                       geometry,
                       ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                   ) AS dist_m
            FROM dc_constraint_zones
            WHERE zone_type = ANY($3)
              AND ST_DWithin(
                  geometry,
                  ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                  $4
              )
            ORDER BY dist_m
        """, lon, lat, HARD_TYPES, radius_m)

        for row in rows:
            results.append({
                "type": row["zone_type"],
                "name": row["name"] or HARD_LABELS.get(row["zone_type"], row["zone_type"]),
                "distance_m": round(row["dist_m"], 1),
                "designation": row["designation"],
                "status": "NO-GO",
                "source": "postgis",
            })
    except Exception as exc:
        log.warning("PostGIS hard constraint query failed: %s", exc)

    # 2. If no results from PostGIS, fall back to API queries
    if not results:
        api_results = await _check_hard_constraints_api(lat, lon, radius_m)
        results.extend(api_results)

    return results


async def _check_hard_constraints_api(
    lat: float,
    lon: float,
    radius_m: float,
) -> list[dict]:
    """Check hard constraints via Natural England + planning.data.gov.uk APIs."""
    results: list[dict] = []

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        tasks = []
        # Natural England layers
        for zone_type in ("sssi", "sac", "spa", "ramsar", "aonb"):
            tasks.append(_query_natural_england(client, zone_type, lat, lon, radius_m))
        # ALC grade 1-2
        tasks.append(_query_alc_grade(client, lat, lon, radius_m))
        # Green Belt
        tasks.append(_query_planning_data(client, "green_belt", lat, lon, radius_m))

        api_results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in api_results:
            if isinstance(res, Exception):
                log.warning("API constraint query failed: %s", res)
                continue
            if isinstance(res, list):
                results.extend(res)

    return results


async def _query_natural_england(
    client: httpx.AsyncClient,
    zone_type: str,
    lat: float,
    lon: float,
    radius_m: float,
) -> list[dict]:
    """Query a Natural England ArcGIS REST endpoint for features near a point."""
    url = NATURAL_ENGLAND_SERVICES.get(zone_type)
    if not url:
        return []

    name_field = _NE_NAME_FIELDS.get(zone_type, "NAME")

    params = {
        "where": "1=1",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": radius_m,
        "units": "esriSRUnit_Meter",
        "outFields": name_field,
        "returnGeometry": "false",
        "f": "json",
    }

    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Natural England %s query failed: %s", zone_type, exc)
        return []

    features = data.get("features", [])
    results = []
    for feat in features:
        attrs = feat.get("attributes", {})
        name = attrs.get(name_field, zone_type.upper())
        results.append({
            "type": zone_type,
            "name": str(name),
            "distance_m": 0.0,  # ArcGIS buffer query — within radius
            "status": "NO-GO",
            "source": "natural_england_api",
        })

    return results


async def _query_alc_grade(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    radius_m: float,
) -> list[dict]:
    """Query ALC data for Grade 1 or 2 agricultural land."""
    url = NATURAL_ENGLAND_SERVICES.get("alc")
    if not url:
        return []

    params = {
        "where": "ALC_GRADE IN ('Grade 1', 'Grade 2')",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": radius_m,
        "units": "esriSRUnit_Meter",
        "outFields": "ALC_GRADE",
        "returnGeometry": "false",
        "f": "json",
    }

    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("ALC query failed: %s", exc)
        return []

    features = data.get("features", [])
    results = []
    for feat in features:
        attrs = feat.get("attributes", {})
        grade = attrs.get("ALC_GRADE", "Grade 1-2")
        results.append({
            "type": "alc_12",
            "name": f"Best & Most Versatile Agricultural Land ({grade})",
            "designation": str(grade),
            "distance_m": 0.0,
            "status": "NO-GO",
            "source": "natural_england_api",
        })

    return results


async def _query_planning_data(
    client: httpx.AsyncClient,
    zone_type: str,
    lat: float,
    lon: float,
    radius_m: float,
) -> list[dict]:
    """Query planning.data.gov.uk for a specific dataset near a point."""
    url = PLANNING_DATA_SERVICES.get(zone_type)
    dataset = PLANNING_DATA_DATASETS.get(zone_type)
    if not url or not dataset:
        return []

    params = {
        "dataset": dataset,
        "longitude": lon,
        "latitude": lat,
        "radius": radius_m,
        "limit": 50,
    }

    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("planning.data.gov.uk %s query failed: %s", zone_type, exc)
        return []

    features = data.get("features", [])
    results = []
    is_hard = zone_type in HARD_TYPES

    for feat in features:
        props = feat.get("properties", {})
        name = props.get("name") or props.get("reference") or zone_type.replace("_", " ").title()
        entry: dict[str, Any] = {
            "type": zone_type,
            "name": str(name),
            "distance_m": 0.0,
            "source": "planning_data_gov_uk",
        }
        if is_hard:
            entry["status"] = "NO-GO"
        else:
            penalty = SOFT_CONSTRAINTS.get(zone_type, {}).get("penalty", 0)
            entry["penalty"] = penalty

        results.append(entry)

    return results


# ─── Soft Constraint Checks ──────────────────────────────────────────────


async def _check_soft_constraints(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    radius_m: float,
) -> list[dict]:
    """Check soft constraint layers (scoring penalties)."""
    results: list[dict] = []

    # 1. PostGIS — conservation areas within radius
    try:
        rows = await conn.fetch("""
            SELECT zone_type, name,
                   ST_Distance(
                       geometry,
                       ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                   ) AS dist_m
            FROM dc_constraint_zones
            WHERE zone_type = 'conservation_area'
              AND ST_DWithin(
                  geometry,
                  ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                  $3
              )
            ORDER BY dist_m
        """, lon, lat, radius_m)

        for row in rows:
            results.append({
                "type": "conservation_area",
                "name": row["name"] or "Conservation Area",
                "distance_m": round(row["dist_m"], 1),
                "penalty": SOFT_CONSTRAINTS["conservation_area"]["penalty"],
                "source": "postgis",
            })
    except Exception as exc:
        log.warning("PostGIS conservation area query failed: %s", exc)

    # 2. PostGIS — ancient woodland within 500m
    try:
        rows = await conn.fetch("""
            SELECT zone_type, name,
                   ST_Distance(
                       geometry,
                       ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                   ) AS dist_m
            FROM dc_constraint_zones
            WHERE zone_type = 'ancient_woodland'
              AND ST_DWithin(
                  geometry,
                  ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                  500
              )
            ORDER BY dist_m
        """, lon, lat)

        for row in rows:
            results.append({
                "type": "ancient_woodland",
                "name": row["name"] or "Ancient Woodland",
                "distance_m": round(row["dist_m"], 1),
                "penalty": SOFT_CONSTRAINTS["ancient_woodland"]["penalty"],
                "source": "postgis",
            })
    except Exception as exc:
        log.warning("PostGIS ancient woodland query failed: %s", exc)

    # 3. PostGIS — listed buildings within 500m
    try:
        rows = await conn.fetch("""
            SELECT zone_type, name,
                   ST_Distance(
                       geometry,
                       ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                   ) AS dist_m
            FROM dc_constraint_zones
            WHERE zone_type = 'listed_building'
              AND ST_DWithin(
                  geometry,
                  ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                  500
              )
            ORDER BY dist_m
        """, lon, lat)

        for row in rows:
            results.append({
                "type": "listed_building",
                "name": row["name"] or "Listed Building",
                "distance_m": round(row["dist_m"], 1),
                "penalty": SOFT_CONSTRAINTS["listed_building"]["penalty"],
                "source": "postgis",
            })
    except Exception as exc:
        log.warning("PostGIS listed building query failed: %s", exc)

    # 4. PostGIS — residential areas within 200m (noise concern for DC)
    try:
        rows = await conn.fetch("""
            SELECT zone_type, name,
                   ST_Distance(
                       geometry,
                       ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                   ) AS dist_m
            FROM dc_constraint_zones
            WHERE zone_type = 'residential'
              AND ST_DWithin(
                  geometry,
                  ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                  200
              )
            ORDER BY dist_m
        """, lon, lat)

        for row in rows:
            results.append({
                "type": "residential_proximity",
                "name": row["name"] or "Residential Area",
                "distance_m": round(row["dist_m"], 1),
                "penalty": SOFT_CONSTRAINTS["residential_proximity"]["penalty"],
                "source": "postgis",
            })
    except Exception as exc:
        log.warning("PostGIS residential proximity query failed: %s", exc)

    # 5. API fallback for soft constraints if nothing found locally
    if not results:
        api_results = await _check_soft_constraints_api(lat, lon, radius_m)
        results.extend(api_results)

    return results


async def _check_soft_constraints_api(
    lat: float,
    lon: float,
    radius_m: float,
) -> list[dict]:
    """Fallback API queries for soft constraint layers."""
    results: list[dict] = []

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        tasks = [
            _query_natural_england(client, "ancient_woodland", lat, lon, 500),
            _query_planning_data(client, "conservation_area", lat, lon, radius_m),
        ]

        api_results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in api_results:
            if isinstance(res, Exception):
                log.warning("Soft constraint API query failed: %s", res)
                continue
            if isinstance(res, list):
                for item in res:
                    zone_type = item.get("type", "")
                    # Convert hard-format results to soft penalties
                    if zone_type == "ancient_woodland":
                        item.pop("status", None)
                        item["penalty"] = SOFT_CONSTRAINTS["ancient_woodland"]["penalty"]
                    elif zone_type == "conservation_area":
                        item.pop("status", None)
                        item["penalty"] = SOFT_CONSTRAINTS["conservation_area"]["penalty"]
                    results.append(item)

    return results


# ─── Flood Zone Check ─────────────────────────────────────────────────────


async def _check_flood_zone(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
) -> dict:
    """
    Check flood zone classification from existing geeflow_extractions
    and dc_constraint_zones tables.

    Returns:
        {"zone": str | None, "surface_water_risk": bool}
    """
    zone = None
    surface_water_risk = False

    # 1. Check geeflow_extractions for flood_risk mode
    try:
        row = await conn.fetchrow("""
            SELECT result
            FROM geeflow_extractions
            WHERE mode = 'flood_risk'
              AND ST_DWithin(
                  geometry,
                  ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                  100
              )
            ORDER BY created_at DESC
            LIMIT 1
        """, lon, lat)

        if row and row["result"]:
            result = row["result"] if isinstance(row["result"], dict) else json.loads(row["result"])
            zone = result.get("flood_zone") or result.get("zone")
            surface_water_risk = result.get("surface_water_risk", False)
    except Exception as exc:
        log.debug("geeflow_extractions flood check failed: %s", exc)

    # 2. Check dc_constraint_zones for flood zone polygons
    if zone is None:
        try:
            row = await conn.fetchrow("""
                SELECT designation
                FROM dc_constraint_zones
                WHERE zone_type LIKE 'flood_zone%%'
                  AND ST_Intersects(
                      geometry,
                      ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                  )
                ORDER BY designation DESC
                LIMIT 1
            """, lon, lat)

            if row:
                zone = row["designation"]
        except Exception as exc:
            log.debug("dc_constraint_zones flood check failed: %s", exc)

    return {"zone": zone, "surface_water_risk": surface_water_risk}


# ─── Summary Builder ──────────────────────────────────────────────────────


def _build_summary(
    hard_constraints: list[dict],
    soft_constraints: list[dict],
    score: int,
    flood_zone: str | None,
    green_belt: bool,
    agricultural_grade: str | None,
) -> str:
    """Build a human-readable summary of the constraint check."""
    parts: list[str] = []

    if hard_constraints:
        types = sorted({c["type"] for c in hard_constraints})
        labels = [HARD_LABELS.get(t, t) for t in types]
        parts.append(
            f"NO-GO: site intersects {len(hard_constraints)} hard constraint(s) — "
            + ", ".join(labels) + "."
        )
    else:
        parts.append("No hard constraints detected within search radius.")

    if soft_constraints:
        total_pen = sum(c["penalty"] for c in soft_constraints)
        parts.append(
            f"{len(soft_constraints)} soft constraint(s) found (total penalty: {total_pen} pts)."
        )
        for c in soft_constraints:
            label = SOFT_CONSTRAINTS.get(c["type"], {}).get("label", c["type"])
            dist = c.get("distance_m", 0)
            parts.append(f"  - {label}: {c['name']} ({dist:.0f}m away, {c['penalty']} pts)")

    if flood_zone:
        parts.append(f"Flood zone: {flood_zone}.")

    if green_belt:
        parts.append("Site is within Green Belt.")

    if agricultural_grade:
        parts.append(f"Agricultural land classification: {agricultural_grade}.")

    parts.append(f"Constraint score: {score}/100.")

    if score == 0:
        parts.append("Verdict: NO-GO — hard constraint overlap.")
    elif score >= 80:
        parts.append("Verdict: GO — minimal planning constraints.")
    elif score >= 50:
        parts.append("Verdict: CAUTION — soft constraints present, mitigation may be required.")
    else:
        parts.append("Verdict: CAUTION — significant soft constraints, detailed assessment needed.")

    return " ".join(parts)


# ─── GeoJSON Overlay Generation ──────────────────────────────────────────


async def constraint_overlay_geojson(
    conn: asyncpg.Connection,
    bbox: dict,
    zone_types: list[str] | None = None,
) -> dict:
    """
    Return GeoJSON FeatureCollection of constraint zones for map visualisation.

    Args:
        conn: asyncpg database connection.
        bbox: Bounding box dict with keys min_lon, min_lat, max_lon, max_lat (WGS-84).
        zone_types: Optional filter list (e.g. ['sssi', 'aonb']). None = all types.

    Returns:
        GeoJSON FeatureCollection with constraint zone polygons in EPSG:4326.
    """
    min_lon = bbox["min_lon"]
    min_lat = bbox["min_lat"]
    max_lon = bbox["max_lon"]
    max_lat = bbox["max_lat"]

    type_filter = ""
    args: list[Any] = [min_lon, min_lat, max_lon, max_lat]

    if zone_types:
        type_filter = "AND zone_type = ANY($5)"
        args.append(zone_types)

    query = f"""
        SELECT zone_id, zone_type, name, designation, area_ha,
               ST_AsGeoJSON(ST_Transform(geometry, 4326))::json AS geojson
        FROM dc_constraint_zones
        WHERE ST_Intersects(
            geometry,
            ST_Transform(
                ST_MakeEnvelope($1, $2, $3, $4, 4326),
                27700
            )
        )
        {type_filter}
        ORDER BY zone_type, name
    """

    try:
        rows = await conn.fetch(query, *args)
    except Exception as exc:
        log.error("Constraint overlay GeoJSON query failed: %s", exc)
        return {"type": "FeatureCollection", "features": []}

    features = []
    for row in rows:
        is_hard = row["zone_type"] in HARD_TYPES
        feature = {
            "type": "Feature",
            "geometry": row["geojson"],
            "properties": {
                "zone_id": row["zone_id"],
                "zone_type": row["zone_type"],
                "name": row["name"],
                "designation": row["designation"],
                "area_ha": row["area_ha"],
                "severity": "hard" if is_hard else "soft",
                "label": HARD_LABELS.get(row["zone_type"])
                    or SOFT_CONSTRAINTS.get(row["zone_type"], {}).get("label")
                    or row["zone_type"],
                "fill_color": _zone_color(row["zone_type"], is_hard),
            },
        }
        features.append(feature)

    log.info(
        "Constraint overlay: %d features in bbox (%.4f,%.4f)-(%.4f,%.4f)",
        len(features), min_lon, min_lat, max_lon, max_lat,
    )

    return {"type": "FeatureCollection", "features": features}


def _zone_color(zone_type: str, is_hard: bool) -> str:
    """Return a hex colour for map rendering based on zone type."""
    colours = {
        "sssi": "#e63946",
        "sac": "#d62828",
        "spa": "#c1121f",
        "ramsar": "#457b9d",
        "aonb": "#2a9d8f",
        "green_belt": "#52b788",
        "alc_12": "#bc6c25",
        "flood_zone_23": "#0077b6",
        "conservation_area": "#f4a261",
        "ancient_woodland": "#386641",
        "listed_building": "#9b5de5",
        "residential": "#adb5bd",
        "flood_surface_water": "#48cae4",
    }
    if zone_type in colours:
        return colours[zone_type]
    return "#e63946" if is_hard else "#f4a261"


# ─── Constraint Data Ingestion Helpers ────────────────────────────────────


async def ingest_natural_england_layer(
    conn: asyncpg.Connection,
    zone_type: str,
    bbox: dict | None = None,
    limit: int = 2000,
) -> int:
    """
    Fetch features from Natural England ArcGIS REST and insert into dc_constraint_zones.

    Args:
        conn: asyncpg database connection.
        zone_type: One of the NATURAL_ENGLAND_SERVICES keys.
        bbox: Optional bounding box dict (min_lon, min_lat, max_lon, max_lat).
        limit: Max features to fetch per call.

    Returns:
        Number of features ingested.
    """
    url = NATURAL_ENGLAND_SERVICES.get(zone_type)
    if not url:
        log.error("Unknown Natural England layer: %s", zone_type)
        return 0

    name_field = _NE_NAME_FIELDS.get(zone_type, "NAME")

    params: dict[str, Any] = {
        "where": "1=1",
        "outFields": f"{name_field},SHAPE__Area",
        "returnGeometry": "true",
        "outSR": "27700",
        "f": "json",
        "resultRecordCount": limit,
    }

    if bbox:
        params["geometry"] = (
            f"{bbox['min_lon']},{bbox['min_lat']},"
            f"{bbox['max_lon']},{bbox['max_lat']}"
        )
        params["geometryType"] = "esriGeometryEnvelope"
        params["inSR"] = "4326"
        params["spatialRel"] = "esriSpatialRelIntersects"

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("Failed to fetch %s from Natural England: %s", zone_type, exc)
            return 0

    features = data.get("features", [])
    if not features:
        log.info("No %s features returned from API", zone_type)
        return 0

    ingested = 0
    for feat in features:
        attrs = feat.get("attributes", {})
        geom = feat.get("geometry")
        if not geom:
            continue

        name = attrs.get(name_field, "")
        area_ha = (attrs.get("SHAPE__Area") or 0) / 10_000  # m² to ha

        # Convert ESRI rings/paths to WKT
        wkt = _esri_geometry_to_wkt(geom)
        if not wkt:
            continue

        # Handle ALC: only ingest Grade 1-2
        effective_type = zone_type
        designation = None
        if zone_type == "alc":
            grade = attrs.get("ALC_GRADE", "")
            if grade not in ("Grade 1", "Grade 2"):
                continue
            effective_type = "alc_12"
            designation = grade

        try:
            await conn.execute("""
                INSERT INTO dc_constraint_zones
                    (zone_type, name, designation, area_ha, geometry, source)
                VALUES ($1, $2, $3, $4, ST_GeomFromText($5, 27700), 'natural_england')
                ON CONFLICT DO NOTHING
            """, effective_type, name, designation, area_ha, wkt)
            ingested += 1
        except Exception as exc:
            log.debug("Insert failed for %s feature %s: %s", zone_type, name, exc)

    log.info("Ingested %d/%d %s features", ingested, len(features), zone_type)
    return ingested


async def ingest_planning_data_layer(
    conn: asyncpg.Connection,
    zone_type: str,
    bbox: dict | None = None,
    limit: int = 500,
) -> int:
    """
    Fetch features from planning.data.gov.uk and insert into dc_constraint_zones.

    Args:
        conn: asyncpg database connection.
        zone_type: One of the PLANNING_DATA_DATASETS keys.
        bbox: Optional bounding box dict.
        limit: Max features to fetch.

    Returns:
        Number of features ingested.
    """
    url = PLANNING_DATA_SERVICES.get(zone_type)
    dataset = PLANNING_DATA_DATASETS.get(zone_type)
    if not url or not dataset:
        log.error("Unknown planning data layer: %s", zone_type)
        return 0

    params: dict[str, Any] = {
        "dataset": dataset,
        "limit": limit,
    }

    if bbox:
        # planning.data.gov.uk supports bounding box via geometry parameters
        centre_lon = (bbox["min_lon"] + bbox["max_lon"]) / 2
        centre_lat = (bbox["min_lat"] + bbox["max_lat"]) / 2
        from math import radians, cos

        # Approximate radius from bbox diagonal
        dlat = bbox["max_lat"] - bbox["min_lat"]
        dlon = bbox["max_lon"] - bbox["min_lon"]
        radius_deg = ((dlat ** 2 + (dlon * cos(radians(centre_lat))) ** 2) ** 0.5) / 2
        radius_m = radius_deg * 111_320
        params["longitude"] = centre_lon
        params["latitude"] = centre_lat
        params["radius"] = min(radius_m, 50_000)

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("Failed to fetch %s from planning.data.gov.uk: %s", zone_type, exc)
            return 0

    features = data.get("features", [])
    if not features:
        log.info("No %s features returned from planning.data.gov.uk", zone_type)
        return 0

    ingested = 0
    for feat in features:
        props = feat.get("properties", {})
        geom = feat.get("geometry")
        if not geom:
            continue

        name = props.get("name") or props.get("reference") or ""
        designation = props.get("designation")

        # Convert GeoJSON geometry to WKT in SRID 4326, then transform to 27700 on insert
        geojson_str = json.dumps(geom)

        try:
            await conn.execute("""
                INSERT INTO dc_constraint_zones
                    (zone_type, name, designation, geometry, source)
                VALUES (
                    $1, $2, $3,
                    ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($4), 4326), 27700),
                    'planning_data_gov_uk'
                )
                ON CONFLICT DO NOTHING
            """, zone_type, name, designation, geojson_str)
            ingested += 1
        except Exception as exc:
            log.debug("Insert failed for %s feature %s: %s", zone_type, name, exc)

    log.info("Ingested %d/%d %s features from planning.data.gov.uk", ingested, len(features), zone_type)
    return ingested


async def ingest_all_constraint_layers(
    conn: asyncpg.Connection,
    bbox: dict | None = None,
) -> dict[str, int]:
    """
    Ingest all constraint layers (Natural England + planning.data.gov.uk) for a region.

    Args:
        conn: asyncpg database connection.
        bbox: Optional bounding box to restrict ingestion area.

    Returns:
        Dict mapping zone_type to count of features ingested.
    """
    await setup_constraint_tables(conn)

    results: dict[str, int] = {}

    # Natural England layers
    ne_types = ["sssi", "sac", "spa", "ramsar", "aonb", "ancient_woodland", "alc"]
    for zt in ne_types:
        count = await ingest_natural_england_layer(conn, zt, bbox=bbox)
        effective_type = "alc_12" if zt == "alc" else zt
        results[effective_type] = count

    # planning.data.gov.uk layers
    for zt in PLANNING_DATA_DATASETS:
        count = await ingest_planning_data_layer(conn, zt, bbox=bbox)
        results[zt] = count

    total = sum(results.values())
    log.info("Total constraint features ingested: %d across %d layers", total, len(results))
    return results


# ─── Geometry Helpers ─────────────────────────────────────────────────────


def _esri_geometry_to_wkt(geom: dict) -> str | None:
    """
    Convert ESRI JSON geometry (rings or paths) to WKT.

    Handles Polygon (rings) and Polyline (paths).
    Returns None if the geometry cannot be converted.
    """
    rings = geom.get("rings")
    if rings:
        # Polygon or MultiPolygon
        if len(rings) == 1:
            coords = ", ".join(f"{x} {y}" for x, y in rings[0])
            return f"POLYGON(({coords}))"
        else:
            polys = []
            for ring in rings:
                coords = ", ".join(f"{x} {y}" for x, y in ring)
                polys.append(f"(({coords}))")
            return f"MULTIPOLYGON({', '.join(polys)})"

    paths = geom.get("paths")
    if paths:
        if len(paths) == 1:
            coords = ", ".join(f"{x} {y}" for x, y in paths[0])
            return f"LINESTRING({coords})"
        else:
            lines = []
            for path in paths:
                coords = ", ".join(f"{x} {y}" for x, y in path)
                lines.append(f"({coords})")
            return f"MULTILINESTRING({', '.join(lines)})"

    # Point
    x = geom.get("x")
    y = geom.get("y")
    if x is not None and y is not None:
        return f"POINT({x} {y})"

    return None

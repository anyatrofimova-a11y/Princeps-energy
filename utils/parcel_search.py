"""Automated Parcel Search at Scale — PostGIS-based land parcel filtering and scoring."""

from __future__ import annotations
import logging
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "grid_proximity": 0.25, "terrain": 0.20, "land_use": 0.15,
    "flood_risk": 0.15, "area_suitability": 0.15, "access": 0.10,
}


async def search_parcels(conn, criteria: dict) -> dict[str, Any]:
    """Search and score parcels within criteria."""
    bbox = criteria.get("bbox")  # [minLon, minLat, maxLon, maxLat]
    min_area = criteria.get("min_area_ha", 5)
    max_area = criteria.get("max_area_ha", 500)
    max_sub_dist = criteria.get("max_distance_to_substation_km", 20)
    limit = criteria.get("limit", 50)

    if not bbox:
        return {"parcels": [], "total_found": 0, "error": "bbox required"}

    # Query parcels table (or inspire_parcels)
    # First check which table exists
    table = await conn.fetchval("""
        SELECT tablename FROM pg_tables WHERE tablename IN ('parcels', 'inspire_parcels') LIMIT 1
    """)

    if not table:
        return {"parcels": [], "total_found": 0, "error": "No parcel table found. Ingest INSPIRE data first."}

    geom_col = "geom" if table == "inspire_parcels" else "boundary"
    id_col = "inspire_id" if table == "inspire_parcels" else "parcel_id"

    rows = await conn.fetch(f"""
        WITH site_parcels AS (
            SELECT
                {id_col} AS parcel_id,
                {geom_col} AS geom,
                ST_Area({geom_col}) / 10000.0 AS area_ha
            FROM {table}
            WHERE ST_Intersects(
                {geom_col},
                ST_Transform(ST_MakeEnvelope($1, $2, $3, $4, 4326), 27700)
            )
            AND ST_Area({geom_col}) / 10000.0 BETWEEN $5 AND $6
        )
        SELECT
            sp.parcel_id,
            sp.area_ha,
            ST_AsGeoJSON(ST_Transform(sp.geom, 4326))::json AS geometry,
            COALESCE(
                (SELECT MIN(ST_Distance(sp.geom, gs.geom)) / 1000.0
                 FROM grid_substations gs
                 WHERE ST_DWithin(sp.geom, gs.geom, $7 * 1000)),
                999
            ) AS grid_distance_km,
            ST_Y(ST_Transform(ST_Centroid(sp.geom), 4326)) AS lat,
            ST_X(ST_Transform(ST_Centroid(sp.geom), 4326)) AS lon
        FROM site_parcels sp
        WHERE COALESCE(
            (SELECT MIN(ST_Distance(sp.geom, gs.geom)) / 1000.0
             FROM grid_substations gs
             WHERE ST_DWithin(sp.geom, gs.geom, $7 * 1000)),
            999
        ) <= $7
        ORDER BY grid_distance_km
        LIMIT $8
    """, bbox[0], bbox[1], bbox[2], bbox[3], min_area, max_area, max_sub_dist, limit)

    parcels = []
    for r in rows:
        score = _score_parcel_row(r)
        parcels.append({
            "parcel_id": str(r["parcel_id"]),
            "area_ha": round(float(r["area_ha"]), 2),
            "grid_distance_km": round(float(r["grid_distance_km"]), 1),
            "lat": round(float(r["lat"]), 4),
            "lon": round(float(r["lon"]), 4),
            "score": score["score"],
            "verdict": score["verdict"],
            "geometry": r["geometry"],
        })

    parcels.sort(key=lambda x: x["score"], reverse=True)

    return {"parcels": parcels, "total_found": len(parcels)}


def _score_parcel_row(row) -> dict:
    """Score a parcel from DB row data."""
    dist = float(row["grid_distance_km"])
    area = float(row["area_ha"])

    grid_score = 100 if dist < 2 else 80 if dist < 5 else 60 if dist < 10 else 20 if dist < 20 else 0
    area_score = 100 if 10 <= area <= 100 else 80 if 5 <= area <= 200 else 50

    # Simplified score (terrain, flood, land_use need separate data)
    w = DEFAULT_WEIGHTS
    score = round(
        grid_score * w["grid_proximity"] +
        70 * w["terrain"] +  # Assume moderate terrain for now
        70 * w["land_use"] +
        80 * w["flood_risk"] +  # Assume Zone 1 for now
        area_score * w["area_suitability"] +
        60 * w["access"]
    )

    return {"score": min(100, score), "verdict": "GO" if score >= 65 else "CAUTION" if score >= 40 else "NO-GO"}


async def score_parcel(conn, lat: float, lon: float, area_ha: float = None, weights: dict = None) -> dict[str, Any]:
    """Score a single parcel location."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    # Grid proximity
    sub = await conn.fetchrow("""
        SELECT ST_Distance(geom, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km,
               voltage_kv
        FROM grid_substations
        ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 1
    """, lon, lat)

    grid_dist = float(sub["dist_km"]) if sub else 999
    grid_score = 100 if grid_dist < 2 else 80 if grid_dist < 5 else 60 if grid_dist < 10 else 20 if grid_dist < 20 else 0

    # Area suitability
    area_score = 100 if area_ha and 10 <= area_ha <= 100 else 80 if area_ha and 5 <= area_ha <= 200 else 60

    # Defaults for missing data
    terrain_score = 70
    land_use_score = 70
    flood_score = 80
    access_score = 60

    total = round(
        grid_score * w["grid_proximity"] +
        terrain_score * w["terrain"] +
        land_use_score * w["land_use"] +
        flood_score * w["flood_risk"] +
        area_score * w["area_suitability"] +
        access_score * w["access"]
    )

    return {
        "score": min(100, total),
        "breakdown": {
            "grid_proximity": grid_score, "terrain": terrain_score,
            "land_use": land_use_score, "flood_risk": flood_score,
            "area_suitability": area_score, "access": access_score,
        },
        "grid_distance_km": round(grid_dist, 1),
        "nearest_substation_kv": float(sub["voltage_kv"]) if sub and sub["voltage_kv"] else None,
        "verdict": "GO" if total >= 65 else "CAUTION" if total >= 40 else "NO-GO",
    }

"""
Automated UK-Wide ML Site Prospector.

Scans all NGED substations and scores surrounding catchment areas for
energy development opportunity using multi-criteria analysis:
- Grid headroom (voltage-based capacity proxy)
- Solar resource (latitude-based GHI estimate)
- Development density (REPD projects within 10km)
- Competition (TEC queue depth at connection site)
- Constraint risk (placeholder for planning/environmental)

Uses PostGIS spatial queries for efficient radius searches across
2,059 NGED substations, 13,995 REPD projects, and ESO TEC register.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import asyncpg

log = logging.getLogger("princeps.auto_prospector")

# ---------------------------------------------------------------------------
# Voltage-based grid headroom score
# ---------------------------------------------------------------------------
VOLTAGE_SCORE: dict[int, int] = {
    400: 95, 275: 90, 132: 80, 66: 65, 33: 50, 11: 30,
}

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _grid_headroom_score(voltage_kv: float) -> int:
    """Higher voltage = more capacity available."""
    return VOLTAGE_SCORE.get(int(voltage_kv), 40)


def _solar_resource_score(lat: float) -> tuple[int, int]:
    """Latitude-based UK GHI estimate. Returns (ghi, score)."""
    if lat < 52:
        ghi = 1100
    elif lat < 54:
        ghi = 1000
    else:
        ghi = 900
    score = int((ghi - 600) / 6)
    return ghi, score


def _development_density_score(repd_count: int) -> int:
    """REPD projects within 10km — more = proven viable, but too many = saturated."""
    if repd_count < 10:
        return min(90, repd_count * 8)
    return max(30, 90 - (repd_count - 10) * 5)


def _competition_score(queue_depth: int) -> int:
    """TEC queue depth at connection site."""
    if queue_depth < 3:
        return 90
    if queue_depth < 8:
        return 70
    return 40


def _composite_score(
    voltage_score: int,
    solar_score: int,
    density_score: int,
    queue_score: int,
    constraint_score: int = 50,
) -> float:
    """Weighted composite: grid 30%, solar 25%, density 20%, queue 15%, constraint 10%."""
    return round(
        0.30 * voltage_score
        + 0.25 * solar_score
        + 0.20 * density_score
        + 0.15 * queue_score
        + 0.10 * constraint_score,
        1,
    )


def _recommendation(score: float) -> str:
    if score >= 75:
        return "HIGH_PRIORITY"
    if score >= 60:
        return "PROMISING"
    if score >= 45:
        return "MARGINAL"
    return "LOW_PRIORITY"


# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------

_SQL_SUBSTATIONS = """
    SELECT id, name, voltage_kv, region,
           ST_Y(geometry) AS lat, ST_X(geometry) AS lon
    FROM nged_substation
"""

_SQL_SUBSTATIONS_FILTERED = """
    SELECT id, name, voltage_kv, region,
           ST_Y(geometry) AS lat, ST_X(geometry) AS lon
    FROM nged_substation
    WHERE ($1::text IS NULL OR LOWER(region) = LOWER($1))
      AND ($2::float IS NULL OR voltage_kv >= $2)
"""

_SQL_SUBSTATION_BY_ID = """
    SELECT id, name, voltage_kv, region,
           ST_Y(geometry) AS lat, ST_X(geometry) AS lon
    FROM nged_substation
    WHERE id = $1
"""

_SQL_REPD_COUNT_WITHIN = """
    SELECT COUNT(*) AS cnt
    FROM repd_projects
    WHERE ($2::text IS NULL OR LOWER(tech_category) = LOWER($2))
      AND (6371 * acos(
            LEAST(1.0, cos(radians($3)) * cos(radians(lat))
            * cos(radians(lon) - radians($4))
            + sin(radians($3)) * sin(radians(lat)))
          )) <= $1
"""

_SQL_REPD_NEARBY = """
    SELECT repd_id, site_name, technology, tech_category,
           capacity_mw, status, lat, lon,
           (6371 * acos(
            LEAST(1.0, cos(radians($3)) * cos(radians(lat))
            * cos(radians(lon) - radians($4))
            + sin(radians($3)) * sin(radians(lat)))
           )) AS distance_km
    FROM repd_projects
    WHERE (6371 * acos(
            LEAST(1.0, cos(radians($3)) * cos(radians(lat))
            * cos(radians(lon) - radians($4))
            + sin(radians($3)) * sin(radians(lat)))
          )) <= $1
    ORDER BY distance_km
    LIMIT $2
"""

_SQL_TEC_QUEUE = """
    SELECT COUNT(*) AS cnt
    FROM eso_tec_register
    WHERE LOWER(connection_site) LIKE '%' || LOWER($1) || '%'
"""


# ---------------------------------------------------------------------------
# Core scanning engine
# ---------------------------------------------------------------------------

async def _score_substation(
    pool: asyncpg.Pool,
    sub: dict,
    radius_km: float = 10.0,
    technology: str | None = None,
) -> dict[str, Any]:
    """Score a single substation catchment area."""
    sid = sub["id"]
    name = sub["name"] or f"Substation {sid}"
    voltage_kv = sub["voltage_kv"] or 33
    lat = float(sub["lat"])
    lon = float(sub["lon"])

    # 1. Grid headroom
    v_score = _grid_headroom_score(voltage_kv)

    # 2. Solar resource
    ghi, s_score = _solar_resource_score(lat)

    # 3. Development density (REPD within radius)
    try:
        repd_count = await pool.fetchval(
            _SQL_REPD_COUNT_WITHIN, radius_km, technology, lat, lon,
        )
        repd_count = repd_count or 0
    except Exception:
        repd_count = 0
    d_score = _development_density_score(repd_count)

    # 4. Competition (TEC queue)
    try:
        queue_depth = await pool.fetchval(_SQL_TEC_QUEUE, name) or 0
    except Exception:
        queue_depth = 0
    q_score = _competition_score(queue_depth)

    # 5. Constraint risk (placeholder — default 50)
    c_score = 50

    composite = _composite_score(v_score, s_score, d_score, q_score, c_score)

    return {
        "substation_id": sid,
        "substation_name": name,
        "voltage_kv": voltage_kv,
        "region": sub.get("region") or "unknown",
        "lat": lat,
        "lon": lon,
        "composite_score": composite,
        "recommendation": _recommendation(composite),
        "scores": {
            "grid_headroom": v_score,
            "solar_resource": s_score,
            "development_density": d_score,
            "competition": q_score,
            "constraint_risk": c_score,
        },
        "metrics": {
            "ghi_kwh_m2_yr": ghi,
            "repd_within_10km": repd_count,
            "tec_queue_depth": queue_depth,
        },
    }


async def scan_all(
    pool: asyncpg.Pool,
    *,
    region: str | None = None,
    technology: str | None = None,
    min_capacity_mw: float | None = None,
    top_n: int = 50,
    radius_km: float = 10.0,
) -> dict[str, Any]:
    """
    Scan all NGED substations and return top-N opportunities.

    Parameters
    ----------
    region : optional filter (e.g. "east_midlands")
    technology : optional REPD tech filter (e.g. "solar")
    min_capacity_mw : if set, require voltage_kv >= threshold
        (11kV ~10MW, 33kV ~50MW, 132kV ~200MW)
    top_n : how many results to return (default 50)
    radius_km : catchment radius for REPD density (default 10)
    """
    # Map min_capacity_mw to a minimum voltage threshold
    min_voltage: float | None = None
    if min_capacity_mw is not None:
        if min_capacity_mw >= 200:
            min_voltage = 132
        elif min_capacity_mw >= 50:
            min_voltage = 33
        elif min_capacity_mw >= 10:
            min_voltage = 11

    rows = await pool.fetch(_SQL_SUBSTATIONS_FILTERED, region, min_voltage)
    log.info("Auto-prospector scanning %d substations (region=%s, tech=%s)", len(rows), region, technology)

    results: list[dict] = []
    for row in rows:
        sub = dict(row)
        try:
            scored = await _score_substation(pool, sub, radius_km, technology)
            results.append(scored)
        except Exception as exc:
            log.warning("Failed to score substation %s: %s", sub.get("id"), exc)

    results.sort(key=lambda r: r["composite_score"], reverse=True)
    top = results[:top_n]

    # Summary statistics
    scores = [r["composite_score"] for r in results]
    high = sum(1 for r in results if r["recommendation"] == "HIGH_PRIORITY")
    promising = sum(1 for r in results if r["recommendation"] == "PROMISING")

    return {
        "total_scanned": len(results),
        "top_n": len(top),
        "filters": {
            "region": region,
            "technology": technology,
            "min_capacity_mw": min_capacity_mw,
            "radius_km": radius_km,
        },
        "summary": {
            "high_priority": high,
            "promising": promising,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "min_score": min(scores) if scores else 0,
        },
        "opportunities": top,
    }


async def substation_detail(
    pool: asyncpg.Pool,
    sub_id: int,
    radius_km: float = 10.0,
) -> dict[str, Any]:
    """
    Detailed opportunity assessment for a single substation catchment.

    Includes nearby REPD projects, TEC queue detail, and full score breakdown.
    """
    row = await pool.fetchrow(_SQL_SUBSTATION_BY_ID, sub_id)
    if not row:
        return {"error": f"Substation {sub_id} not found"}

    sub = dict(row)
    lat = float(sub["lat"])
    lon = float(sub["lon"])
    name = sub["name"] or f"Substation {sub_id}"

    # Score the substation
    scored = await _score_substation(pool, sub, radius_km)

    # Nearby REPD projects (up to 25)
    try:
        repd_rows = await pool.fetch(_SQL_REPD_NEARBY, radius_km, 25, lat, lon)
        nearby_projects = [
            {
                "repd_id": r["repd_id"],
                "site_name": r["site_name"],
                "technology": r["technology"],
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] else None,
                "status": r["status"],
                "distance_km": round(float(r["distance_km"]), 1),
            }
            for r in repd_rows
        ]
    except Exception:
        nearby_projects = []

    # TEC queue entries
    try:
        tec_rows = await pool.fetch(
            "SELECT tec_id, connection_site, tec_mw, status "
            "FROM eso_tec_register "
            "WHERE LOWER(connection_site) LIKE '%' || LOWER($1) || '%'",
            name,
        )
        tec_queue = [
            {
                "tec_id": r["tec_id"],
                "connection_site": r["connection_site"],
                "tec_mw": float(r["tec_mw"]) if r["tec_mw"] else None,
                "status": r["status"],
            }
            for r in tec_rows
        ]
    except Exception:
        tec_queue = []

    # Technology breakdown of nearby REPD
    tech_breakdown: dict[str, int] = {}
    for p in nearby_projects:
        t = p.get("technology") or "unknown"
        tech_breakdown[t] = tech_breakdown.get(t, 0) + 1

    # Capacity sum of nearby REPD
    total_nearby_mw = sum(
        p["capacity_mw"] for p in nearby_projects if p["capacity_mw"]
    )

    scored["detail"] = {
        "nearby_repd_projects": nearby_projects,
        "nearby_total_mw": round(total_nearby_mw, 1),
        "technology_breakdown": tech_breakdown,
        "tec_queue": tec_queue,
        "tec_queue_depth": len(tec_queue),
        "catchment_radius_km": radius_km,
    }

    return scored


async def heatmap_geojson(
    pool: asyncpg.Pool,
    radius_km: float = 10.0,
) -> dict[str, Any]:
    """
    GeoJSON FeatureCollection of all substations colored by opportunity score.

    Each feature has properties: substation_id, name, voltage_kv, region,
    composite_score, recommendation, and individual score components.
    """
    rows = await pool.fetch(_SQL_SUBSTATIONS)
    log.info("Building heatmap for %d substations", len(rows))

    features: list[dict] = []
    for row in rows:
        sub = dict(row)
        try:
            scored = await _score_substation(pool, sub, radius_km)
        except Exception as exc:
            log.warning("Heatmap: failed to score %s: %s", sub.get("id"), exc)
            continue

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [scored["lon"], scored["lat"]],
            },
            "properties": {
                "substation_id": scored["substation_id"],
                "name": scored["substation_name"],
                "voltage_kv": scored["voltage_kv"],
                "region": scored["region"],
                "composite_score": scored["composite_score"],
                "recommendation": scored["recommendation"],
                **scored["scores"],
                **scored["metrics"],
            },
        }
        features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "total_substations": len(features),
            "catchment_radius_km": radius_km,
        },
    }

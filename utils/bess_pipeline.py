"""
UK BESS Pipeline Tracker — battery energy storage project intelligence.

Queries REPD + TEC register for all UK battery/storage projects.
Provides pipeline statistics, market intelligence, and GeoJSON for map overlay.
"""
from __future__ import annotations
import logging
from typing import Any, Optional
import asyncpg

log = logging.getLogger("princeps.bess_pipeline")

BESS_REVENUE_BENCHMARKS = {
    "ffr_dynamic": {"label": "FFR Dynamic", "gbp_mw_yr": {"low": 55000, "mid": 65000, "high": 75000}},
    "dynamic_containment": {"label": "Dynamic Containment", "gbp_mw_yr": {"low": 35000, "mid": 42000, "high": 48000}},
    "capacity_market": {"label": "Capacity Market", "gbp_mw_yr": {"low": 10000, "mid": 12500, "high": 15000}},
    "wholesale_arbitrage": {"label": "Wholesale Arbitrage", "gbp_mw_yr": {"low": 18000, "mid": 22000, "high": 25000}},
    "dno_peak_shaving": {"label": "DNO Peak Shaving", "gbp_mw_yr": {"low": 15000, "mid": 22000, "high": 30000}},
}

STATUS_GROUPS = {
    "pre_planning": ["Pre-Planning Application", "Scoping"],
    "submitted": ["Planning Application Submitted", "Appeal Submitted"],
    "approved": ["Awaiting Construction", "Planning Permission Granted"],
    "construction": ["Under Construction"],
    "operational": ["Operational"],
    "refused": ["Refused", "Appeal Refused"],
    "withdrawn": ["Withdrawn", "Abandoned", "Expired"],
}


async def get_bess_pipeline(pool: asyncpg.Pool, region: str = None,
                            min_mw: float = None, status: str = None,
                            limit: int = 200) -> dict:
    """Get full BESS project pipeline from REPD."""
    conditions = ["(technology ILIKE '%storage%' OR technology ILIKE '%battery%')"]
    params = []
    idx = 1

    if region:
        idx += 1
        conditions.append(f"county ILIKE ${idx}")
        params.append(f"%{region}%")
    if min_mw:
        idx += 1
        conditions.append(f"capacity_mw >= ${idx}")
        params.append(min_mw)
    if status:
        status_list = STATUS_GROUPS.get(status)
        if status_list:
            placeholders = ", ".join(f"${idx + i + 1}" for i in range(len(status_list)))
            conditions.append(f"dev_status IN ({placeholders})")
            params.extend(status_list)
            idx += len(status_list)

    where = " AND ".join(conditions)
    try:
        rows = await pool.fetch(f"""
            SELECT ref_id, site_name, technology, capacity_mw, dev_status,
                   county, operator, region,
                   ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon
            FROM repd_projects
            WHERE {where}
            ORDER BY capacity_mw DESC
            LIMIT {limit}
        """, *params)
        projects = [dict(r) for r in rows]
    except Exception as e:
        log.warning("BESS pipeline query failed: %s", e)
        projects = []

    return {
        "projects": projects,
        "count": len(projects),
        "total_mw": round(sum(p.get("capacity_mw", 0) or 0 for p in projects), 1),
    }


async def get_bess_statistics(pool: asyncpg.Pool) -> dict:
    """Aggregate UK BESS pipeline statistics."""
    try:
        # By status
        status_rows = await pool.fetch("""
            SELECT dev_status, COUNT(*) as count, COALESCE(SUM(capacity_mw), 0) as total_mw
            FROM repd_projects
            WHERE technology ILIKE '%storage%' OR technology ILIKE '%battery%'
            GROUP BY dev_status ORDER BY total_mw DESC
        """)
        by_status = {r["dev_status"]: {"count": r["count"], "mw": round(float(r["total_mw"]), 1)} for r in status_rows}

        # By region
        region_rows = await pool.fetch("""
            SELECT county, COUNT(*) as count, COALESCE(SUM(capacity_mw), 0) as total_mw
            FROM repd_projects
            WHERE (technology ILIKE '%storage%' OR technology ILIKE '%battery%')
            AND dev_status NOT IN ('Withdrawn', 'Abandoned', 'Expired')
            GROUP BY county ORDER BY total_mw DESC LIMIT 20
        """)
        by_region = [{"region": r["county"], "count": r["count"], "mw": round(float(r["total_mw"]), 1)} for r in region_rows]

        # Top developers
        dev_rows = await pool.fetch("""
            SELECT operator, COUNT(*) as count, COALESCE(SUM(capacity_mw), 0) as total_mw
            FROM repd_projects
            WHERE (technology ILIKE '%storage%' OR technology ILIKE '%battery%')
            AND operator IS NOT NULL AND operator != ''
            GROUP BY operator ORDER BY total_mw DESC LIMIT 15
        """)
        top_developers = [{"operator": r["operator"], "count": r["count"], "mw": round(float(r["total_mw"]), 1)} for r in dev_rows]

        # Totals
        total = await pool.fetchrow("""
            SELECT COUNT(*) as count, COALESCE(SUM(capacity_mw), 0) as total_mw
            FROM repd_projects
            WHERE technology ILIKE '%storage%' OR technology ILIKE '%battery%'
        """)

        operational = await pool.fetchrow("""
            SELECT COUNT(*) as count, COALESCE(SUM(capacity_mw), 0) as total_mw
            FROM repd_projects
            WHERE (technology ILIKE '%storage%' OR technology ILIKE '%battery%')
            AND dev_status = 'Operational'
        """)

    except Exception as e:
        log.warning("BESS statistics query failed: %s", e)
        return {"error": str(e)}

    return {
        "total_projects": total["count"] if total else 0,
        "total_pipeline_mw": round(float(total["total_mw"]), 1) if total else 0,
        "operational_mw": round(float(operational["total_mw"]), 1) if operational else 0,
        "operational_count": operational["count"] if operational else 0,
        "by_status": by_status,
        "by_region": by_region[:15],
        "top_developers": top_developers[:10],
        "revenue_benchmarks": BESS_REVENUE_BENCHMARKS,
    }


async def get_bess_geojson(pool: asyncpg.Pool, bbox: tuple = None) -> dict:
    """BESS projects as GeoJSON for map overlay."""
    conditions = ["(technology ILIKE '%storage%' OR technology ILIKE '%battery%')", "geom IS NOT NULL"]
    params = []
    if bbox:
        west, south, east, north = bbox
        conditions.append("ST_Within(geom::geometry, ST_MakeEnvelope($1,$2,$3,$4,4326))")
        params = [west, south, east, north]

    try:
        rows = await pool.fetch(f"""
            SELECT ref_id, site_name, capacity_mw, dev_status, technology, operator, county,
                   ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon
            FROM repd_projects
            WHERE {" AND ".join(conditions)}
            ORDER BY capacity_mw DESC LIMIT 500
        """, *params)
    except Exception as e:
        log.warning("BESS GeoJSON query failed: %s", e)
        return {"type": "FeatureCollection", "features": []}

    STATUS_COLORS = {
        "Operational": "#22c55e", "Under Construction": "#3b82f6",
        "Awaiting Construction": "#60a5fa", "Planning Permission Granted": "#60a5fa",
        "Planning Application Submitted": "#f59e0b",
        "Refused": "#ef4444", "Withdrawn": "#6b7280",
    }

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "ref_id": r["ref_id"],
                "name": r["site_name"],
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] else 0,
                "status": r["dev_status"],
                "technology": r["technology"],
                "operator": r["operator"],
                "county": r["county"],
                "color": STATUS_COLORS.get(r["dev_status"], "#9ca3af"),
                "radius": max(4, min(20, (float(r["capacity_mw"] or 1)) ** 0.5 * 3)),
            },
        })

    return {"type": "FeatureCollection", "features": features, "count": len(features)}

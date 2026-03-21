"""
Planning application density — shows energy planning applications near a site.

Data sources:
1. REPD projects (13,995 real records in DB) — all UK RE planning apps with status
2. planning_applications table (12 records) — scraped from planning portals

Groups nearby applications by status and technology to show:
- How many projects are competing for grid in the same area
- What the local planning authority's track record is
- What technologies are being approved/refused nearby
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("princeps.planning_density")

# Status → display color mapping
STATUS_COLORS = {
    "Operational": "#16a34a",       # green
    "Under Construction": "#84cc16", # lime
    "Awaiting Construction": "#f59e0b",  # amber
    "Planning Permission Expired": "#f97316",  # orange
    "Application Submitted": "#3b82f6",  # blue
    "Appeal Lodged": "#8b5cf6",     # violet
    "Refused": "#ef4444",           # red
    "Appeal Refused": "#dc2626",    # dark red
    "Withdrawn": "#6b7280",         # gray
    "Abandoned": "#9ca3af",         # light gray
    "No Application Required": "#06b6d4",  # cyan
}

DEFAULT_COLOR = "#a3a3a3"


def _status_color(status: str) -> str:
    """Map a dev_status_short to a hex color."""
    return STATUS_COLORS.get(status, DEFAULT_COLOR)


def _compute_density_score(total: int, by_status: dict, total_capacity_mw: float) -> tuple[int, str]:
    """
    Compute a competition density score 0-100 and risk level.

    Higher = more competitive / harder to get grid and planning.
    Factors:
    - Number of projects nearby
    - Proportion of active/approved projects (grid contention)
    - Total capacity competing for grid
    """
    if total == 0:
        return 0, "low"

    # Base score from project count (0-40)
    count_score = min(40, total * 2)

    # Active projects score (0-30) — operational + under construction + awaiting
    active = sum(
        by_status.get(s, 0)
        for s in ("Operational", "Under Construction", "Awaiting Construction", "Application Submitted")
    )
    active_ratio = active / total if total > 0 else 0
    active_score = active_ratio * 30

    # Capacity score (0-30) — more MW nearby = more grid contention
    if total_capacity_mw > 1000:
        cap_score = 30
    elif total_capacity_mw > 500:
        cap_score = 22
    elif total_capacity_mw > 200:
        cap_score = 15
    elif total_capacity_mw > 50:
        cap_score = 8
    else:
        cap_score = 3

    score = int(min(100, count_score + active_score + cap_score))

    if score >= 70:
        risk = "high"
    elif score >= 40:
        risk = "medium"
    else:
        risk = "low"

    return score, risk


async def get_planning_density(pool, lat: float, lon: float, radius_km: float = 10) -> dict:
    """
    Fetch planning application density around a point.

    Queries REPD projects within radius_km and returns:
    - GeoJSON FeatureCollection for map overlay
    - Summary statistics by status and technology
    - Density score (0-100) and risk level
    """
    radius_m = radius_km * 1000
    features: list[dict] = []
    by_status: dict[str, int] = {}
    by_technology: dict[str, int] = {}
    total_capacity_mw = 0.0
    approved_count = 0
    decided_count = 0

    try:
        rows = await pool.fetch("""
            SELECT ref_id, site_name, technology_type, installed_capacity_mw,
                   dev_status, dev_status_short, operator, region, county,
                   planning_authority, address,
                   ST_Y(geometry) AS lat, ST_X(geometry) AS lon,
                   ST_Distance(
                       geometry::geography,
                       ST_SetSRID(ST_Point($1, $2), 4326)::geography
                   ) AS distance_m
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                  geometry::geography,
                  ST_SetSRID(ST_Point($1, $2), 4326)::geography,
                  $3
              )
            ORDER BY distance_m ASC
            LIMIT 500
        """, lon, lat, radius_m)

        for r in rows:
            status = r["dev_status_short"] or r["dev_status"] or "Unknown"
            tech = r["technology_type"] or "Unknown"
            cap = float(r["installed_capacity_mw"] or 0)
            color = _status_color(status)

            # Aggregate stats
            by_status[status] = by_status.get(status, 0) + 1
            by_technology[tech] = by_technology.get(tech, 0) + 1
            total_capacity_mw += cap

            # Track approval rate
            if status in ("Operational", "Under Construction", "Awaiting Construction", "No Application Required"):
                approved_count += 1
                decided_count += 1
            elif status in ("Refused", "Appeal Refused"):
                decided_count += 1

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(r["lon"]), float(r["lat"])],
                },
                "properties": {
                    "ref_id": r["ref_id"],
                    "name": r["site_name"] or f"{cap:.0f}MW {tech}",
                    "technology": tech,
                    "capacity_mw": round(cap, 1),
                    "status": status,
                    "color": color,
                    "operator": r["operator"] or "",
                    "planning_authority": r["planning_authority"] or "",
                    "region": r["region"] or "",
                    "county": r["county"] or "",
                    "distance_km": round(float(r["distance_m"]) / 1000, 1),
                    "label": f"{r['site_name'] or tech} ({cap:.0f}MW)",
                },
            })

    except Exception as e:
        log.warning("Planning density query failed: %s", e)

    total = len(features)
    approval_rate = round(approved_count / decided_count, 2) if decided_count > 0 else None
    density_score, risk_level = _compute_density_score(total, by_status, total_capacity_mw)

    return {
        "geojson": {
            "type": "FeatureCollection",
            "features": features,
        },
        "summary": {
            "total": total,
            "by_status": dict(sorted(by_status.items(), key=lambda x: -x[1])),
            "by_technology": dict(sorted(by_technology.items(), key=lambda x: -x[1])),
            "approval_rate": approval_rate,
            "total_capacity_mw": round(total_capacity_mw, 1),
        },
        "density_score": density_score,
        "risk_level": risk_level,
        "radius_km": radius_km,
        "centre": {"lat": lat, "lon": lon},
    }

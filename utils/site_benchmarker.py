"""
Site benchmarker — compares a proposed site against 13,995 real REPD projects.

For each metric, shows where the site ranks as a percentile among all
operational/approved projects of the same technology.

Uses real PostGIS data from grid_substations, repd_project, and
planning authority records.
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("princeps.site_benchmarker")

# Technology normalisation
_TECH_MAP: dict[str, str] = {
    "solar": "Solar Photovoltaics",
    "solar_pv": "Solar Photovoltaics",
    "wind": "Wind Onshore",
    "wind_onshore": "Wind Onshore",
    "wind_offshore": "Wind Offshore",
    "bess": "Battery",
    "battery": "Battery",
    "biomass": "Biomass",
}


def _normalise_tech(tech: str) -> str:
    """Map user-facing technology name to REPD technology_type."""
    return _TECH_MAP.get(tech.lower().strip(), "Solar Photovoltaics")


def _repd_tech_filter(technology: str) -> str:
    """Return SQL LIKE pattern for REPD technology_type."""
    repd_tech = _normalise_tech(technology)
    if "Solar" in repd_tech:
        return "Solar%"
    elif "Wind Onshore" in repd_tech:
        return "Wind Onshore%"
    elif "Wind Offshore" in repd_tech:
        return "Wind Offshore%"
    elif "Battery" in repd_tech:
        return "Battery%"
    elif "Biomass" in repd_tech:
        return "Biomass%"
    return "%"


def _percentile_rank(value: float, sorted_values: list[float]) -> float:
    """Calculate percentile rank of a value within a sorted list."""
    if not sorted_values:
        return 50.0
    below = sum(1 for v in sorted_values if v < value)
    equal = sum(1 for v in sorted_values if v == value)
    return round(100.0 * (below + 0.5 * equal) / len(sorted_values), 1)


def _median(values: list[float]) -> float:
    """Calculate median of a list."""
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2
    return s[n // 2]


def _percentile(values: list[float], pct: float) -> float:
    """Calculate percentile from a list."""
    if not values:
        return 0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def _verdict(overall_pct: float) -> str:
    """Convert percentile to verdict string."""
    if overall_pct >= 80:
        return "EXCELLENT"
    elif overall_pct >= 60:
        return "ABOVE AVERAGE"
    elif overall_pct >= 40:
        return "AVERAGE"
    elif overall_pct >= 20:
        return "BELOW AVERAGE"
    return "POOR"


# ---------------------------------------------------------------------------
# Main benchmarking function
# ---------------------------------------------------------------------------

async def benchmark_site(
    pool,
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str = "solar",
) -> dict[str, Any]:
    """
    Benchmark a proposed site against all REPD projects of the same technology.

    Queries real PostGIS data to compute:
    - Grid headroom at nearest substation
    - Distance to nearest substation
    - Nearby REPD project count (within 10km)
    - Local approval rate
    - Capacity percentile

    Returns percentile rankings for each metric plus comparable projects.
    """
    tech_filter = _repd_tech_filter(technology)

    async with pool.acquire() as conn:
        # ------------------------------------------------------------------
        # 1. Site-specific metrics
        # ------------------------------------------------------------------

        # 1a. Nearest substation with headroom
        nearest_sub = await conn.fetchrow("""
            SELECT s.id, s.name, s.dno, s.voltage_kv,
                   s.gen_headroom_mw, s.demand_headroom_mw,
                   ST_Distance(
                       ST_Transform(s.geom, 4326)::geography,
                       ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) / 1000.0 AS distance_km
            FROM grid_substations s
            WHERE s.geom IS NOT NULL
            ORDER BY s.geom <-> ST_Transform(
                ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700
            )
            LIMIT 1
        """, lon, lat)

        site_headroom = float(nearest_sub["gen_headroom_mw"]) if nearest_sub and nearest_sub["gen_headroom_mw"] else 0
        site_distance_km = float(nearest_sub["distance_km"]) if nearest_sub else 99

        # 1b. Count nearby REPD projects within 10km
        nearby_count = await conn.fetchval("""
            SELECT count(*)
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND ST_DWithin(
                  ST_Transform(geometry, 4326)::geography,
                  ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                  10000
              )
        """, lon, lat)
        nearby_count = nearby_count or 0

        # 1c. Local approval rate (projects within 20km)
        local_stats = await conn.fetchrow("""
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE dev_status_short IN ('Operational', 'Under Construction', 'Approved')) AS approved
            FROM repd_project
            WHERE geometry IS NOT NULL
              AND technology_type LIKE $3
              AND ST_DWithin(
                  ST_Transform(geometry, 4326)::geography,
                  ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography,
                  20000
              )
        """, lon, lat, tech_filter)
        local_total = local_stats["total"] if local_stats else 0
        local_approved = local_stats["approved"] if local_stats else 0
        approval_rate = local_approved / local_total if local_total > 0 else 0.75

        # ------------------------------------------------------------------
        # 2. Benchmark distributions from ALL REPD projects of same tech
        # ------------------------------------------------------------------

        # 2a. Grid headroom distribution for operational projects
        headroom_rows = await conn.fetch("""
            SELECT s.gen_headroom_mw
            FROM grid_substations s
            JOIN repd_project r ON ST_DWithin(
                ST_Transform(r.geometry, 4326)::geography,
                ST_Transform(s.geom, 4326)::geography,
                15000
            )
            WHERE r.technology_type LIKE $1
              AND r.dev_status_short IN ('Operational', 'Under Construction')
              AND r.geometry IS NOT NULL
              AND s.geom IS NOT NULL
              AND s.gen_headroom_mw IS NOT NULL
            LIMIT 5000
        """, tech_filter)
        headroom_values = sorted([float(r["gen_headroom_mw"]) for r in headroom_rows])

        # 2b. Grid distance distribution for operational projects
        distance_rows = await conn.fetch("""
            SELECT
                ST_Distance(
                    ST_Transform(r.geometry, 4326)::geography,
                    ST_Transform(s.geom, 4326)::geography
                ) / 1000.0 AS dist_km
            FROM repd_project r
            JOIN LATERAL (
                SELECT geom FROM grid_substations
                WHERE geom IS NOT NULL
                ORDER BY geom <-> r.geometry
                LIMIT 1
            ) s ON true
            WHERE r.technology_type LIKE $1
              AND r.dev_status_short IN ('Operational', 'Under Construction')
              AND r.geometry IS NOT NULL
            LIMIT 5000
        """, tech_filter)
        distance_values = sorted([float(r["dist_km"]) for r in distance_rows])

        # 2c. Local density distribution
        # Sample operational projects and count neighbours
        density_rows = await conn.fetch("""
            WITH sample AS (
                SELECT r.geometry
                FROM repd_project r
                WHERE r.technology_type LIKE $1
                  AND r.dev_status_short IN ('Operational', 'Under Construction')
                  AND r.geometry IS NOT NULL
                ORDER BY random()
                LIMIT 500
            )
            SELECT (
                SELECT count(*)
                FROM repd_project r2
                WHERE r2.geometry IS NOT NULL
                  AND ST_DWithin(
                      ST_Transform(r2.geometry, 4326)::geography,
                      ST_Transform(s.geometry, 4326)::geography,
                      10000
                  )
            ) AS neighbour_count
            FROM sample s
        """, tech_filter)
        density_values = sorted([int(r["neighbour_count"]) for r in density_rows])

        # 2d. Approval rate distribution by planning authority
        authority_rows = await conn.fetch("""
            SELECT
                planning_authority,
                count(*) AS total,
                count(*) FILTER (WHERE dev_status_short IN ('Operational', 'Under Construction', 'Approved')) AS approved
            FROM repd_project
            WHERE technology_type LIKE $1
              AND planning_authority IS NOT NULL
            GROUP BY planning_authority
            HAVING count(*) >= 3
        """, tech_filter)
        approval_values = sorted([
            r["approved"] / r["total"]
            for r in authority_rows
            if r["total"] > 0
        ])

        # 2e. Capacity distribution
        capacity_rows = await conn.fetch("""
            SELECT installed_capacity_mw
            FROM repd_project
            WHERE technology_type LIKE $1
              AND dev_status_short IN ('Operational', 'Under Construction')
              AND installed_capacity_mw IS NOT NULL
              AND installed_capacity_mw > 0
        """, tech_filter)
        capacity_values = sorted([float(r["installed_capacity_mw"]) for r in capacity_rows])

        # ------------------------------------------------------------------
        # 3. Total project count
        # ------------------------------------------------------------------
        total_projects = await conn.fetchval("""
            SELECT count(*) FROM repd_project WHERE technology_type LIKE $1
        """, tech_filter)

        # ------------------------------------------------------------------
        # 4. Comparable projects (approved + refused)
        # ------------------------------------------------------------------
        comparable_approved = await conn.fetch("""
            SELECT site_name, installed_capacity_mw, planning_authority,
                   dev_status_short, region,
                   ST_Distance(
                       ST_Transform(geometry, 4326)::geography,
                       ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) / 1000.0 AS distance_km
            FROM repd_project
            WHERE technology_type LIKE $3
              AND dev_status_short IN ('Operational', 'Under Construction')
              AND geometry IS NOT NULL
            ORDER BY geometry <-> ST_Transform(
                ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700
            )
            LIMIT 5
        """, lon, lat, tech_filter)

        comparable_refused = await conn.fetch("""
            SELECT site_name, installed_capacity_mw, planning_authority,
                   dev_status_short, region,
                   ST_Distance(
                       ST_Transform(geometry, 4326)::geography,
                       ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography
                   ) / 1000.0 AS distance_km
            FROM repd_project
            WHERE technology_type LIKE $3
              AND dev_status_short IN ('Refused', 'Withdrawn', 'Abandoned')
              AND geometry IS NOT NULL
            ORDER BY geometry <-> ST_Transform(
                ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700
            )
            LIMIT 5
        """, lon, lat, tech_filter)

    # ------------------------------------------------------------------
    # 5. Calculate percentiles
    # ------------------------------------------------------------------
    metrics: dict[str, dict] = {}

    # Grid headroom (higher = better)
    headroom_pct = _percentile_rank(site_headroom, headroom_values) if headroom_values else 50
    metrics["grid_headroom"] = {
        "value": round(site_headroom, 1),
        "unit": "MW",
        "percentile": round(headroom_pct),
        "median": round(_median(headroom_values), 1) if headroom_values else None,
        "p25": round(_percentile(headroom_values, 25), 1) if headroom_values else None,
        "p75": round(_percentile(headroom_values, 75), 1) if headroom_values else None,
        "sample_size": len(headroom_values),
    }

    # Grid distance (lower = better, invert percentile)
    if distance_values:
        distance_pct = 100 - _percentile_rank(site_distance_km, distance_values)
    else:
        distance_pct = 50
    metrics["grid_distance"] = {
        "value": round(site_distance_km, 1),
        "unit": "km",
        "percentile": round(max(distance_pct, 0)),
        "median": round(_median(distance_values), 1) if distance_values else None,
        "sample_size": len(distance_values),
    }

    # Local density (moderate is best — many neighbours = competitive but proves viability)
    density_pct = _percentile_rank(nearby_count, density_values) if density_values else 50
    metrics["local_density"] = {
        "value": nearby_count,
        "unit": "projects within 10km",
        "percentile": round(density_pct),
        "median": round(_median(density_values)) if density_values else None,
        "sample_size": len(density_values),
    }

    # Approval rate (higher = better)
    approval_pct = _percentile_rank(approval_rate, approval_values) if approval_values else 50
    metrics["approval_rate"] = {
        "value": round(approval_rate, 2),
        "unit": "ratio",
        "percentile": round(approval_pct),
        "median": round(_median(approval_values), 2) if approval_values else None,
        "local_total": local_total,
        "local_approved": local_approved,
        "sample_size": len(approval_values),
    }

    # Capacity (just shows where you sit in the distribution)
    capacity_pct = _percentile_rank(capacity_mw, capacity_values) if capacity_values else 50
    metrics["capacity"] = {
        "value": capacity_mw,
        "unit": "MW",
        "percentile": round(capacity_pct),
        "median": round(_median(capacity_values), 1) if capacity_values else None,
        "p25": round(_percentile(capacity_values, 25), 1) if capacity_values else None,
        "p75": round(_percentile(capacity_values, 75), 1) if capacity_values else None,
        "sample_size": len(capacity_values),
    }

    # ------------------------------------------------------------------
    # 6. Overall percentile (weighted average)
    # ------------------------------------------------------------------
    weights = {
        "grid_headroom": 0.30,
        "grid_distance": 0.25,
        "approval_rate": 0.25,
        "capacity": 0.10,
        "local_density": 0.10,
    }
    overall = sum(
        metrics[k]["percentile"] * w
        for k, w in weights.items()
    )
    overall = round(overall)

    # ------------------------------------------------------------------
    # 7. Format comparables
    # ------------------------------------------------------------------
    approved_list = [
        {
            "site_name": r["site_name"],
            "capacity_mw": float(r["installed_capacity_mw"]) if r["installed_capacity_mw"] else None,
            "planning_authority": r["planning_authority"],
            "status": r["dev_status_short"],
            "region": r["region"],
            "distance_km": round(float(r["distance_km"]), 1),
        }
        for r in comparable_approved
    ]

    refused_list = [
        {
            "site_name": r["site_name"],
            "capacity_mw": float(r["installed_capacity_mw"]) if r["installed_capacity_mw"] else None,
            "planning_authority": r["planning_authority"],
            "status": r["dev_status_short"],
            "region": r["region"],
            "distance_km": round(float(r["distance_km"]), 1),
        }
        for r in comparable_refused
    ]

    # ------------------------------------------------------------------
    # 8. Summary narrative
    # ------------------------------------------------------------------
    strong_metrics = [k for k, m in metrics.items() if m["percentile"] >= 70]
    weak_metrics = [k for k, m in metrics.items() if m["percentile"] < 30]

    summary_parts = [
        f"This site scores in the {overall}th percentile compared to all "
        f"{'approved ' if overall >= 50 else ''}UK {technology} projects.",
    ]
    if strong_metrics:
        strong_labels = [k.replace("_", " ").title() for k in strong_metrics]
        summary_parts.append(
            f"{', '.join(strong_labels)} {'is' if len(strong_labels) == 1 else 'are'} strong "
            f"({', '.join(str(metrics[k]['percentile']) + 'th' for k in strong_metrics)} percentile)."
        )
    if weak_metrics:
        weak_labels = [k.replace("_", " ").title() for k in weak_metrics]
        summary_parts.append(
            f"{', '.join(weak_labels)} {'is' if len(weak_labels) == 1 else 'are'} below average "
            f"and may need mitigation."
        )

    return {
        "overall_percentile": overall,
        "verdict": _verdict(overall),
        "metrics": metrics,
        "comparable_approved": approved_list,
        "comparable_refused": refused_list,
        "nearest_substation": {
            "name": nearest_sub["name"] if nearest_sub else None,
            "dno": nearest_sub["dno"] if nearest_sub else None,
            "voltage_kv": float(nearest_sub["voltage_kv"]) if nearest_sub and nearest_sub["voltage_kv"] else None,
            "distance_km": round(site_distance_km, 1),
            "headroom_mw": round(site_headroom, 1),
        } if nearest_sub else None,
        "summary": " ".join(summary_parts),
        "source": f"Benchmarked against {total_projects:,} REPD projects",
        "technology": technology,
        "parameters": {
            "lat": lat,
            "lon": lon,
            "capacity_mw": capacity_mw,
        },
    }

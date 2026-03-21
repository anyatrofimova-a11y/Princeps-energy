"""
UK Large Load Connection Tracker — data centres, industrial, EV hubs.

Tracks large demand connections in the UK grid queue,
known DC cluster locations, and demand growth projections.
"""
from __future__ import annotations
import logging, math
from typing import Any, Optional
import asyncpg

log = logging.getLogger("princeps.large_load")

# Known UK data centre clusters (2025 data)
UK_DC_CLUSTERS = [
    {"name": "Slough / Langley", "lat": 51.51, "lon": -0.59, "estimated_mw": 500,
     "operators": ["Equinix", "CyrusOne", "Virtus", "KDDI"], "dno": "SSEN",
     "status": "mature", "growth": "constrained"},
    {"name": "London Docklands", "lat": 51.505, "lon": -0.02, "estimated_mw": 350,
     "operators": ["Telehouse", "Global Switch", "Equinix"], "dno": "UKPN",
     "status": "mature", "growth": "limited"},
    {"name": "Waltham Cross / Lee Valley", "lat": 51.685, "lon": -0.035, "estimated_mw": 180,
     "operators": ["Google", "Kao Data", "Equinix"], "dno": "UKPN",
     "status": "growing", "growth": "active"},
    {"name": "West London / Hayes", "lat": 51.50, "lon": -0.42, "estimated_mw": 280,
     "operators": ["Virtus", "Vantage", "ark"], "dno": "SSEN",
     "status": "growing", "growth": "active"},
    {"name": "Manchester", "lat": 53.48, "lon": -2.24, "estimated_mw": 120,
     "operators": ["Equinix", "TelecityGroup", "DataVita"], "dno": "ENWL",
     "status": "growing", "growth": "active"},
    {"name": "Edinburgh / Livingston", "lat": 55.88, "lon": -3.52, "estimated_mw": 60,
     "operators": ["DataVita", "Pulsant", "Colt"], "dno": "SPEN",
     "status": "emerging", "growth": "high"},
    {"name": "Newport / Cardiff", "lat": 51.59, "lon": -2.99, "estimated_mw": 180,
     "operators": ["Next Generation Data", "Vantage"], "dno": "NGED",
     "status": "growing", "growth": "active"},
    {"name": "Teesside", "lat": 54.57, "lon": -1.23, "estimated_mw": 40,
     "operators": ["Various (emerging)"], "dno": "NPg",
     "status": "emerging", "growth": "high"},
    {"name": "Cambridge / Harlow", "lat": 51.77, "lon": 0.09, "estimated_mw": 80,
     "operators": ["Kao Data", "GTT"], "dno": "UKPN",
     "status": "growing", "growth": "active"},
    {"name": "Reading / Winnersh", "lat": 51.43, "lon": -0.88, "estimated_mw": 70,
     "operators": ["Microsoft", "Various"], "dno": "SSEN",
     "status": "growing", "growth": "moderate"},
]

# UK data centre demand projection (GW)
DC_DEMAND_FORECAST = {
    2024: {"total_gw": 3.2, "source": "NESO/industry estimates"},
    2025: {"total_gw": 3.6, "source": "NESO FES"},
    2026: {"total_gw": 4.1, "source": "NESO FES interpolation"},
    2027: {"total_gw": 4.7, "source": "NESO FES interpolation"},
    2028: {"total_gw": 5.4, "source": "NESO FES interpolation"},
    2029: {"total_gw": 5.9, "source": "NESO FES interpolation"},
    2030: {"total_gw": 6.5, "source": "NESO FES Leading the Way"},
    2035: {"total_gw": 10.0, "source": "NESO FES high scenario"},
    2040: {"total_gw": 14.0, "source": "NESO FES high scenario"},
    2050: {"total_gw": 20.0, "source": "NESO FES high scenario"},
}

# DNO large load connection methodology
DNO_LARGE_LOAD = {
    "UKPN": {
        "threshold_mw": 1,
        "process": "Bespoke connection offer via Major Connections team",
        "typical_timeline_months": "12-24",
        "voltage_options": ["33kV", "132kV"],
        "notes": "Dedicated team for data centre connections. Demand connection charge based on ASC (Authorised Supply Capacity).",
    },
    "SSEN": {
        "threshold_mw": 1,
        "process": "Statement of Works (SoW) for transmission impact assessment",
        "typical_timeline_months": "18-30",
        "voltage_options": ["33kV", "132kV"],
        "notes": "Slough area heavily constrained. SoW required for >5MW in most areas.",
    },
    "NPg": {
        "threshold_mw": 1,
        "process": "Standard connection application with capacity study",
        "typical_timeline_months": "12-18",
        "voltage_options": ["33kV", "66kV", "132kV"],
        "notes": "Teesside emerging as DC cluster with available capacity.",
    },
    "NGED": {
        "threshold_mw": 1,
        "process": "Bespoke connection via Strategic Connections team",
        "typical_timeline_months": "12-24",
        "voltage_options": ["33kV", "132kV"],
        "notes": "Newport area has significant available capacity for DC development.",
    },
    "SPEN": {
        "threshold_mw": 1,
        "process": "Large customer connection application",
        "typical_timeline_months": "18-24",
        "voltage_options": ["33kV", "132kV"],
        "notes": "Edinburgh/Central Scotland growing DC market.",
    },
    "ENWL": {
        "threshold_mw": 1,
        "process": "Demand connection application",
        "typical_timeline_months": "12-18",
        "voltage_options": ["33kV", "132kV"],
        "notes": "Manchester region with moderate available capacity.",
    },
}


async def get_large_load_pipeline(pool: asyncpg.Pool, region: str = None, min_mw: float = None) -> dict:
    """Get large demand connection projects from TEC register + REPD."""
    projects = []

    # TEC register — transmission-connected demand
    try:
        conditions = ["capacity_mw >= 10"]
        params = []
        if region:
            conditions.append(f"connection_site ILIKE '%{region}%'")
        rows = await pool.fetch(f"""
            SELECT project_name, capacity_mw, connection_site, status, fuel_type,
                   ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon
            FROM eso_tec_register
            WHERE {" AND ".join(conditions)}
            AND (fuel_type ILIKE '%demand%' OR fuel_type ILIKE '%storage%' OR capacity_mw >= 50)
            ORDER BY capacity_mw DESC LIMIT 100
        """, *params)
        for r in rows:
            projects.append({
                "source": "tec_register", "name": r["project_name"],
                "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] else 0,
                "connection_site": r["connection_site"], "status": r["status"],
                "type": r["fuel_type"],
                "lat": float(r["lat"]) if r["lat"] else None,
                "lon": float(r["lon"]) if r["lon"] else None,
            })
    except Exception as e:
        log.debug("TEC large load query failed: %s", e)

    return {
        "projects": projects,
        "count": len(projects),
        "total_mw": round(sum(p.get("capacity_mw", 0) for p in projects), 1),
    }


async def get_dc_cluster_analysis(pool: asyncpg.Pool) -> dict:
    """Analyse UK data centre clusters with grid capacity context."""
    clusters = []
    for cluster in UK_DC_CLUSTERS:
        # Check grid capacity near cluster
        grid_info = {}
        try:
            row = await pool.fetchrow("""
                SELECT name, voltage_kv, demand_headroom_mw,
                       ST_Distance(geom, ST_SetSRID(ST_MakePoint($1,$2),4326)::geography)/1000 as dist_km
                FROM grid_substations
                WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint($1,$2),4326)::geography, 10000)
                ORDER BY dist_km LIMIT 1
            """, cluster["lon"], cluster["lat"])
            if row:
                grid_info = {
                    "nearest_substation": row["name"],
                    "voltage_kv": row["voltage_kv"],
                    "headroom_mw": round(float(row["demand_headroom_mw"]), 1) if row["demand_headroom_mw"] else None,
                    "distance_km": round(float(row["dist_km"]), 1),
                }
        except Exception:
            pass

        dno_info = DNO_LARGE_LOAD.get(cluster["dno"], {})
        clusters.append({
            **cluster,
            "grid": grid_info,
            "dno_process": dno_info.get("process", ""),
            "typical_timeline": dno_info.get("typical_timeline_months", ""),
        })

    return {
        "clusters": clusters,
        "total_uk_dc_mw": sum(c["estimated_mw"] for c in UK_DC_CLUSTERS),
        "active_growth_regions": [c["name"] for c in UK_DC_CLUSTERS if c["growth"] in ("active", "high")],
    }


def get_large_load_forecast() -> dict:
    """UK data centre demand growth projection."""
    return {
        "forecast": DC_DEMAND_FORECAST,
        "current_gw": DC_DEMAND_FORECAST[2024]["total_gw"],
        "projected_2030_gw": DC_DEMAND_FORECAST[2030]["total_gw"],
        "growth_rate_pct_yr": round(
            ((DC_DEMAND_FORECAST[2030]["total_gw"] / DC_DEMAND_FORECAST[2024]["total_gw"]) ** (1/6) - 1) * 100, 1
        ),
        "drivers": [
            "AI/ML training workloads (GPU-intensive, high density)",
            "Cloud migration (enterprise IT → hyperscale)",
            "Edge computing (5G, autonomous vehicles, IoT)",
            "Crypto/blockchain (variable, policy-dependent)",
            "Government digital services (NHS, HMRC modernisation)",
        ],
        "grid_implications": [
            "6.5GW by 2030 = ~13% of current UK peak demand",
            "Concentrated in SE England — grid reinforcement critical",
            "Behind-the-meter renewables needed to manage grid impact",
            "Flexibility services from DC UPS/BESS — revenue opportunity",
        ],
        "dno_connection_methodology": DNO_LARGE_LOAD,
    }

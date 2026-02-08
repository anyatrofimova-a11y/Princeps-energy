"""
UK Grid Data Platform — adapted from owen-saunders/Theridian.

Provides:
  - UK DNO substation registry with comprehensive technical data
  - Grid data source management (DNOs, APIs, open data)
  - ETL job tracking with status machine and retry logic
  - Time-series metrics collection for grid/solar monitoring
  - Dashboard statistics aggregation
  - System health check

All adapted for Princeps's asyncpg + FastAPI architecture (no Django/Celery).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# UK DNO Data Sources (the "tangled web" of UK grid data)
# ---------------------------------------------------------------------------

UK_DATA_SOURCES = [
    {
        "id": "ukpn",
        "name": "UK Power Networks",
        "source_type": "api",
        "regions": ["Eastern (EPN)", "London (LPN)", "South East (SPN)"],
        "url": "https://www.ukpowernetworks.co.uk/open-data",
        "datasets": ["substations", "demand", "generation", "faults"],
    },
    {
        "id": "ssen",
        "name": "Scottish & Southern Electricity Networks",
        "source_type": "api",
        "regions": ["Southern Scotland", "North of Scotland"],
        "url": "https://www.ssen.co.uk/about-ssen/our-data/",
        "datasets": ["substations", "network_capacity", "connections"],
    },
    {
        "id": "wpd",
        "name": "Western Power Distribution (National Grid ED)",
        "source_type": "api",
        "regions": ["West Midlands", "East Midlands", "South West", "South Wales"],
        "url": "https://connecteddata.nationalgrid.co.uk/",
        "datasets": ["substations", "capacity", "demand"],
    },
    {
        "id": "nged",
        "name": "National Grid Electricity Distribution",
        "source_type": "api",
        "regions": ["West Midlands", "East Midlands", "South West", "South Wales"],
        "url": "https://www.nationalgrid.co.uk/our-network",
        "datasets": ["substations", "network_headroom", "demand_forecasts"],
    },
    {
        "id": "enwl",
        "name": "Electricity North West",
        "source_type": "api",
        "regions": ["North West England"],
        "url": "https://www.enwl.co.uk/get-connected/network-information/",
        "datasets": ["substations", "capacity", "demand"],
    },
    {
        "id": "npg",
        "name": "Northern Powergrid",
        "source_type": "api",
        "regions": ["North East England", "Yorkshire"],
        "url": "https://www.northernpowergrid.com/network-data",
        "datasets": ["substations", "network_capacity", "faults"],
    },
    {
        "id": "neso",
        "name": "National Energy System Operator",
        "source_type": "api",
        "regions": ["National (GB)"],
        "url": "https://www.neso.energy/data-portal",
        "datasets": ["demand", "generation_mix", "frequency", "carbon_intensity"],
    },
    {
        "id": "elexon",
        "name": "Elexon (BSC Central Services)",
        "source_type": "api",
        "regions": ["National (GB)"],
        "url": "https://www.elexon.co.uk/data/",
        "datasets": ["settlement", "balancing", "generation", "demand"],
    },
]


# ---------------------------------------------------------------------------
# UK Substation Registry (sample data matching Theridian schema)
# ---------------------------------------------------------------------------

UK_SUBSTATIONS = [
    {
        "id": "SUB-001",
        "site_name": "CLIFF QUAY GRID 132KV",
        "licence_area": "Eastern Power Networks (EPN)",
        "site_type": "Grid Substation",
        "voltage_kv": 132,
        "risk_rating": "High",
        "asset_count": 67,
        "transformer_count": 4,
        "town": "IPSWICH",
        "county": "Suffolk",
        "postcode": "IP3 0BS",
        "lat": 52.034,
        "lon": 1.163,
        "demand_mw_winter": 85.0,
        "demand_mw_summer": 52.0,
        "headroom_mw": 15.0,
        "trans_rating_mva_winter": 100,
        "trans_rating_mva_summer": 90,
    },
    {
        "id": "SUB-002",
        "site_name": "BERKSWELL 132KV",
        "licence_area": "Western Power Distribution",
        "site_type": "Grid Substation",
        "voltage_kv": 132,
        "risk_rating": "Medium",
        "asset_count": 42,
        "transformer_count": 2,
        "town": "COVENTRY",
        "county": "West Midlands",
        "postcode": "CV7 7BQ",
        "lat": 52.395,
        "lon": -1.641,
        "demand_mw_winter": 60.0,
        "demand_mw_summer": 38.0,
        "headroom_mw": 25.0,
        "trans_rating_mva_winter": 85,
        "trans_rating_mva_summer": 75,
    },
    {
        "id": "SUB-003",
        "site_name": "BOLNEY 400KV",
        "licence_area": "UK Power Networks (SPN)",
        "site_type": "Grid Supply Point",
        "voltage_kv": 400,
        "risk_rating": "Low",
        "asset_count": 120,
        "transformer_count": 6,
        "town": "HAYWARDS HEATH",
        "county": "West Sussex",
        "postcode": "RH17 5QS",
        "lat": 50.992,
        "lon": -0.213,
        "demand_mw_winter": 320.0,
        "demand_mw_summer": 190.0,
        "headroom_mw": 80.0,
        "trans_rating_mva_winter": 400,
        "trans_rating_mva_summer": 360,
    },
    {
        "id": "SUB-004",
        "site_name": "EAST CLAYDON 33KV",
        "licence_area": "UK Power Networks (SPN)",
        "site_type": "Primary Substation",
        "voltage_kv": 33,
        "risk_rating": "Low",
        "asset_count": 18,
        "transformer_count": 2,
        "town": "BUCKINGHAM",
        "county": "Buckinghamshire",
        "postcode": "MK18 2LR",
        "lat": 51.899,
        "lon": -0.901,
        "demand_mw_winter": 12.0,
        "demand_mw_summer": 7.5,
        "headroom_mw": 8.0,
        "trans_rating_mva_winter": 20,
        "trans_rating_mva_summer": 18,
    },
    {
        "id": "SUB-005",
        "site_name": "DRAKELOW 132KV",
        "licence_area": "National Grid ED (West Midlands)",
        "site_type": "Grid Substation",
        "voltage_kv": 132,
        "risk_rating": "Medium",
        "asset_count": 55,
        "transformer_count": 3,
        "town": "BURTON UPON TRENT",
        "county": "Staffordshire",
        "postcode": "DE15 9UA",
        "lat": 52.780,
        "lon": -1.638,
        "demand_mw_winter": 70.0,
        "demand_mw_summer": 45.0,
        "headroom_mw": 20.0,
        "trans_rating_mva_winter": 90,
        "trans_rating_mva_summer": 80,
    },
    {
        "id": "SUB-006",
        "site_name": "FECKENHAM 132KV",
        "licence_area": "National Grid ED (West Midlands)",
        "site_type": "Grid Substation",
        "voltage_kv": 132,
        "risk_rating": "Low",
        "asset_count": 38,
        "transformer_count": 2,
        "town": "REDDITCH",
        "county": "Worcestershire",
        "postcode": "B96 6QJ",
        "lat": 52.274,
        "lon": -1.913,
        "demand_mw_winter": 45.0,
        "demand_mw_summer": 28.0,
        "headroom_mw": 35.0,
        "trans_rating_mva_winter": 80,
        "trans_rating_mva_summer": 70,
    },
    {
        "id": "SUB-007",
        "site_name": "BRAMLEY 400KV",
        "licence_area": "Scottish & Southern (Southern)",
        "site_type": "Grid Supply Point",
        "voltage_kv": 400,
        "risk_rating": "Low",
        "asset_count": 95,
        "transformer_count": 4,
        "town": "BASINGSTOKE",
        "county": "Hampshire",
        "postcode": "RG26 5AT",
        "lat": 51.339,
        "lon": -1.068,
        "demand_mw_winter": 280.0,
        "demand_mw_summer": 170.0,
        "headroom_mw": 120.0,
        "trans_rating_mva_winter": 400,
        "trans_rating_mva_summer": 360,
    },
    {
        "id": "SUB-008",
        "site_name": "EAKRING 132KV",
        "licence_area": "National Grid ED (East Midlands)",
        "site_type": "Grid Substation",
        "voltage_kv": 132,
        "risk_rating": "Medium",
        "asset_count": 48,
        "transformer_count": 3,
        "town": "NEWARK",
        "county": "Nottinghamshire",
        "postcode": "NG22 0DA",
        "lat": 53.130,
        "lon": -1.039,
        "demand_mw_winter": 55.0,
        "demand_mw_summer": 35.0,
        "headroom_mw": 30.0,
        "trans_rating_mva_winter": 85,
        "trans_rating_mva_summer": 75,
    },
]


# ---------------------------------------------------------------------------
# Metrics store (in-memory, mirrors Theridian's MetricData model)
# ---------------------------------------------------------------------------

_metrics: list[dict] = []


def record_metric(name: str, value: float, metric_type: str = "gauge",
                   labels: dict | None = None) -> dict:
    """Record a time-series metric."""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "metric_name": name,
        "metric_value": value,
        "metric_type": metric_type,
        "labels": labels or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _metrics.append(entry)
    # Keep max 10000 metrics in memory
    if len(_metrics) > 10000:
        _metrics.pop(0)
    return entry


def query_metrics(name: str | None = None, metric_type: str | None = None,
                   limit: int = 100) -> list[dict]:
    """Query stored metrics."""
    result = _metrics
    if name:
        result = [m for m in result if m["metric_name"] == name]
    if metric_type:
        result = [m for m in result if m["metric_type"] == metric_type]
    return list(reversed(result))[:limit]


# ---------------------------------------------------------------------------
# Dashboard stats (mirrors Theridian's DashboardStatsView)
# ---------------------------------------------------------------------------

def dashboard_stats(jobs_list: list[dict] | None = None) -> dict:
    """
    Generate dashboard statistics — grid data overview.
    Mirrors Theridian's DashboardStatsView pattern.
    """
    total_subs = len(UK_SUBSTATIONS)
    total_sources = len(UK_DATA_SOURCES)

    # Aggregate substation stats
    total_capacity_mva = sum(s["trans_rating_mva_winter"] for s in UK_SUBSTATIONS)
    total_headroom_mw = sum(s["headroom_mw"] for s in UK_SUBSTATIONS)
    avg_demand_mw = sum(s["demand_mw_winter"] for s in UK_SUBSTATIONS) / total_subs

    risk_counts = {}
    voltage_counts = {}
    for s in UK_SUBSTATIONS:
        risk_counts[s["risk_rating"]] = risk_counts.get(s["risk_rating"], 0) + 1
        vk = f"{s['voltage_kv']}kV"
        voltage_counts[vk] = voltage_counts.get(vk, 0) + 1

    # Job stats if provided
    job_stats = None
    if jobs_list:
        job_stats = {
            "total": len(jobs_list),
            "running": sum(1 for j in jobs_list if j.get("status") == "running"),
            "done": sum(1 for j in jobs_list if j.get("status") == "done"),
            "failed": sum(1 for j in jobs_list if j.get("status") == "failed"),
        }

    return {
        "grid_overview": {
            "total_substations": total_subs,
            "total_data_sources": total_sources,
            "total_transformer_capacity_mva": total_capacity_mva,
            "total_network_headroom_mw": total_headroom_mw,
            "avg_winter_demand_mw": round(avg_demand_mw, 1),
        },
        "risk_distribution": risk_counts,
        "voltage_distribution": voltage_counts,
        "data_sources": [
            {"id": ds["id"], "name": ds["name"], "datasets": len(ds["datasets"])}
            for ds in UK_DATA_SOURCES
        ],
        "jobs": job_stats,
        "metrics_count": len(_metrics),
    }


# ---------------------------------------------------------------------------
# Health check (mirrors Theridian's health_check endpoint)
# ---------------------------------------------------------------------------

async def health_check(pool) -> dict:
    """Multi-component health check."""
    checks = {}

    # Database
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        checks["database"] = {"status": "healthy", "latency_ms": 0}
    except Exception as e:
        checks["database"] = {"status": "unhealthy", "error": str(e)}

    # Check tables exist
    try:
        async with pool.acquire() as conn:
            tables = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            checks["tables"] = {
                "status": "healthy",
                "count": len(tables),
                "names": [t["tablename"] for t in tables],
            }
    except Exception as e:
        checks["tables"] = {"status": "unhealthy", "error": str(e)}

    # In-memory stores
    checks["metrics_store"] = {"status": "healthy", "entries": len(_metrics)}
    checks["substation_registry"] = {
        "status": "healthy",
        "substations": len(UK_SUBSTATIONS),
    }

    overall = all(
        c.get("status") == "healthy" for c in checks.values()
    )

    return {
        "status": "healthy" if overall else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Substation helpers
# ---------------------------------------------------------------------------

def find_nearest_substation(lat: float, lon: float, min_voltage_kv: int = 0) -> dict | None:
    """Find the nearest registered substation to a location."""
    import math

    best = None
    best_dist = float("inf")

    for sub in UK_SUBSTATIONS:
        if sub["voltage_kv"] < min_voltage_kv:
            continue
        dlat = math.radians(sub["lat"] - lat)
        dlon = math.radians(sub["lon"] - lon)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat)) * math.cos(math.radians(sub["lat"])) *
             math.sin(dlon / 2) ** 2)
        dist_km = 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        if dist_km < best_dist:
            best_dist = dist_km
            best = {**sub, "distance_km": round(dist_km, 2)}

    return best


def substations_in_radius(lat: float, lon: float, radius_km: float = 50) -> list[dict]:
    """Find all substations within a radius of a location."""
    import math
    results = []
    for sub in UK_SUBSTATIONS:
        dlat = math.radians(sub["lat"] - lat)
        dlon = math.radians(sub["lon"] - lon)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat)) * math.cos(math.radians(sub["lat"])) *
             math.sin(dlon / 2) ** 2)
        dist_km = 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        if dist_km <= radius_km:
            results.append({**sub, "distance_km": round(dist_km, 2)})
    results.sort(key=lambda s: s["distance_km"])
    return results


def connection_cost_estimate(distance_km: float, capacity_kw: float,
                              voltage_kv: int = 33) -> dict:
    """
    Estimate grid connection cost based on distance and capacity.
    UK DNO typical rates.
    """
    # Base costs (GBP)
    base_cost = 5000 if capacity_kw < 50 else 15000 if capacity_kw < 500 else 50000

    # Cable cost per km (varies by voltage)
    cable_cost_per_km = {
        11: 80000,   # 11kV
        33: 150000,  # 33kV
        132: 500000, # 132kV
    }.get(voltage_kv, 120000)

    cable_cost = distance_km * cable_cost_per_km

    # Transformer/switchgear
    transformer_cost = 0
    if capacity_kw > 1000:
        transformer_cost = 25000 + capacity_kw * 15
    elif capacity_kw > 100:
        transformer_cost = 10000

    # DNO fees and reinforcement
    dno_fee = max(5000, capacity_kw * 5)
    reinforcement = 0
    if capacity_kw > 5000:
        reinforcement = capacity_kw * 20

    total = base_cost + cable_cost + transformer_cost + dno_fee + reinforcement
    timeline_weeks = 12 if capacity_kw < 50 else 26 if capacity_kw < 1000 else 52

    return {
        "total_cost_gbp": round(total),
        "breakdown": {
            "base_cost": round(base_cost),
            "cable_cost": round(cable_cost),
            "transformer_switchgear": round(transformer_cost),
            "dno_fees": round(dno_fee),
            "reinforcement": round(reinforcement),
        },
        "distance_km": round(distance_km, 2),
        "capacity_kw": capacity_kw,
        "voltage_kv": voltage_kv,
        "estimated_timeline_weeks": timeline_weeks,
        "notes": _connection_notes(capacity_kw, distance_km, voltage_kv),
    }


def _connection_notes(capacity_kw: float, distance_km: float, voltage_kv: int) -> list[str]:
    """Generate connection advisory notes."""
    notes = []
    if capacity_kw > 50000:
        notes.append("Large-scale connection: National Grid ESO involvement likely required")
    if capacity_kw > 10000:
        notes.append("Major connection: Full grid study and reinforcement assessment needed")
    if distance_km > 5:
        notes.append(f"Long cable run ({distance_km:.1f} km): consider higher voltage to reduce losses")
    if voltage_kv == 11 and capacity_kw > 500:
        notes.append("Capacity exceeds typical 11kV limit: 33kV connection recommended")
    if capacity_kw < 3.68:
        notes.append("Below 3.68 kW: G98 notification only (no formal application needed)")
    elif capacity_kw <= 50:
        notes.append("G99 application required: typically 8-12 weeks")
    else:
        notes.append("Formal connection application required with detailed technical submission")
    return notes

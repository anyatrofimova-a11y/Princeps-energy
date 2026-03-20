"""
dc_colocation_scorer.py — Data centre co-location scoring engine for Princeps.

9-dimension scoring with facility profiles, proximity matrix, gate thresholds,
and REAL grid headroom from all 6 UK DNOs.  Follows site_prospector.py pattern.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import asyncpg

log = logging.getLogger("princeps.dc_scorer")

# ---------------------------------------------------------------------------
# Facility profiles — weights must sum to 100
# ---------------------------------------------------------------------------
FACILITY_PROFILES: dict[str, dict] = {
    "google_hyperscale": {
        "label": "Google Hyperscale",
        "capacity_range": "100-500+ MW",
        "description": "Google-class hyperscale data centres requiring bulk power, 24/7 CFE, and water-positive operations",
        "weights": {
            "power_capacity": 15, "grid_headroom": 15, "cfe_score": 15,
            "cooling_climate": 10, "constraint_clear": 10, "water_stress": 5,
            "fibre_proximity": 5, "ixp_proximity": 5, "latency": 5,
            "land_planning": 5, "resilience": 5, "connection_speed": 2,
            "incentives": 2, "regulatory_pathway": 1,
        },
        "gates": {
            "min_headroom_mw": 50, "max_fibre_km": 15, "max_ixp_km": 200,
            "max_water_km": 30, "min_voltage_kv": 132,
            "constraint_clear": True, "min_cfe_pct": 60,
        },
    },
    "hyperscale": {
        "label": "Hyperscale",
        "capacity_range": "30-200+ MW",
        "description": "Large-scale cloud / AI compute facilities requiring bulk power and cooling",
        "weights": {
            "power_capacity": 20, "grid_headroom": 20, "resilience": 15,
            "water_cooling": 10, "fibre_proximity": 10, "land_planning": 10,
            "latency": 5, "ixp_proximity": 5, "connection_speed": 5,
        },
        "gates": {
            "min_headroom_mw": 20, "max_fibre_km": 10, "max_ixp_km": 150,
            "max_water_km": 20, "min_voltage_kv": 132,
        },
    },
    "colocation": {
        "label": "Colocation",
        "capacity_range": "5-30 MW",
        "description": "Multi-tenant carrier-neutral data centres for enterprise and cloud on-ramps",
        "weights": {
            "fibre_proximity": 15, "latency": 15, "power_capacity": 15,
            "grid_headroom": 15, "ixp_proximity": 10, "land_planning": 10,
            "resilience": 10, "connection_speed": 5, "water_cooling": 5,
        },
        "gates": {
            "min_headroom_mw": 5, "max_fibre_km": 5, "max_ixp_km": 100,
            "max_water_km": 30, "min_voltage_kv": 33,
        },
    },
    "edge": {
        "label": "Edge",
        "capacity_range": "<5 MW",
        "description": "Low-latency edge compute nodes near population centres",
        "weights": {
            "latency": 25, "fibre_proximity": 15, "land_planning": 15,
            "power_capacity": 10, "grid_headroom": 10, "resilience": 10,
            "connection_speed": 10, "ixp_proximity": 5, "water_cooling": 0,
        },
        "gates": {
            "min_headroom_mw": 1, "max_fibre_km": 3, "max_ixp_km": 200,
            "max_water_km": 999, "min_voltage_kv": 11,
        },
    },
    "custom": {
        "label": "Custom",
        "capacity_range": "Any",
        "description": "User-configurable weighting across all dimensions",
        "weights": {
            "power_capacity": 12, "grid_headroom": 12, "resilience": 12,
            "water_cooling": 10, "fibre_proximity": 10, "land_planning": 10,
            "latency": 10, "ixp_proximity": 12, "connection_speed": 12,
        },
        "gates": {},
    },
}

# ---------------------------------------------------------------------------
# UK population centres for latency scoring
# ---------------------------------------------------------------------------
UK_POP_CENTRES = [
    {"name": "London", "lat": 51.5074, "lon": -0.1278, "pop_m": 9.0},
    {"name": "Manchester", "lat": 53.4808, "lon": -2.2426, "pop_m": 2.8},
    {"name": "Birmingham", "lat": 52.4862, "lon": -1.8904, "pop_m": 2.6},
    {"name": "Leeds", "lat": 53.8008, "lon": -1.5491, "pop_m": 1.9},
    {"name": "Edinburgh", "lat": 55.9533, "lon": -3.1883, "pop_m": 0.5},
    {"name": "Bristol", "lat": 51.4545, "lon": -2.5879, "pop_m": 0.7},
]

# Grid connection cost rates (£/km by voltage)
CONNECTION_COST_RATES = {
    11: 80_000, 33: 150_000, 66: 250_000, 132: 500_000, 275: 1_200_000, 400: 2_000_000,
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _distance_rating(km: float, excellent: float, good: float, moderate: float) -> str:
    if km <= excellent:
        return "Excellent"
    if km <= good:
        return "Good"
    if km <= moderate:
        return "Moderate"
    return "Far"


def _distance_score(km: float, excellent: float, good: float, moderate: float, far: float) -> float:
    """0-100 score based on distance thresholds."""
    if km <= excellent:
        return 100
    if km <= good:
        return 80 - (km - excellent) / (good - excellent) * 20
    if km <= moderate:
        return 50 - (km - good) / (moderate - good) * 20
    if km <= far:
        return 20 - (km - moderate) / (far - moderate) * 15
    return max(0, 5)


# ---------------------------------------------------------------------------
# Scoring dimensions
# ---------------------------------------------------------------------------
async def _score_power_capacity(conn: asyncpg.Connection, lat: float, lon: float,
                                 capacity_mw: float) -> tuple[float, dict]:
    """Score based on nearest substation capacity and voltage tier."""
    row = await conn.fetchrow("""
        SELECT name, voltage_kv, transformer_rating_mva AS capacity_mva, demand_headroom_mw, rag_demand,
               ST_Distance(geom, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km
        FROM grid_substations
        ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 1
    """, lon, lat)

    if not row:
        return 20.0, {"nearest_substation": None, "dist_km": None}

    dist_km = float(row["dist_km"])
    voltage = row["voltage_kv"] or 33
    capacity_mva = row["capacity_mva"] or 0

    # Voltage tier match for requested capacity
    voltage_score = 100
    if capacity_mw > 100 and voltage < 132:
        voltage_score = 30
    elif capacity_mw > 30 and voltage < 66:
        voltage_score = 40
    elif capacity_mw > 10 and voltage < 33:
        voltage_score = 50

    dist_score = _distance_score(dist_km, 1, 3, 8, 20)
    capacity_ratio = min(1.0, capacity_mva / max(capacity_mw, 1)) * 100 if capacity_mva else 50

    score = voltage_score * 0.35 + dist_score * 0.35 + capacity_ratio * 0.30

    return score, {
        "substation": row["name"],
        "dist_km": round(dist_km, 2),
        "voltage_kv": voltage,
        "capacity_mva": capacity_mva,
    }


async def _score_grid_headroom(conn: asyncpg.Connection, lat: float, lon: float,
                                capacity_mw: float) -> tuple[float, dict]:
    """KEY DIFFERENTIATOR — real demand headroom from DNO data."""
    rows = await conn.fetch("""
        SELECT name, voltage_kv, demand_headroom_mw, rag_demand, dno,
               ST_Distance(geom, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km
        FROM grid_substations
        WHERE demand_headroom_mw IS NOT NULL
        ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 5
    """, lon, lat)

    if not rows:
        return 15.0, {"headroom_mw": None, "source": "no_data"}

    best = rows[0]
    headroom = float(best["demand_headroom_mw"])
    dist_km = float(best["dist_km"])

    # Check ECR queue depth
    queue_count = await conn.fetchval("""
        SELECT count(*) FROM grid_ecr
        WHERE substation_name ILIKE '%' || $1 || '%'
    """, best["name"][:20]) or 0

    # Score headroom relative to requested capacity
    if headroom >= capacity_mw * 1.5:
        headroom_score = 100
    elif headroom >= capacity_mw:
        headroom_score = 75
    elif headroom >= capacity_mw * 0.5:
        headroom_score = 40
    elif headroom > 0:
        headroom_score = 20
    else:
        headroom_score = 5

    # Penalise queue
    queue_penalty = min(30, queue_count * 5)
    headroom_score = max(0, headroom_score - queue_penalty)

    # RAG colour bonus/penalty
    rag = (best["rag_demand"] or "").lower()
    if rag == "green":
        headroom_score = min(100, headroom_score + 10)
    elif rag == "red":
        headroom_score = max(0, headroom_score - 15)

    return headroom_score, {
        "headroom_mw": round(headroom, 2),
        "substation": best["name"],
        "voltage_kv": best["voltage_kv"],
        "rag_demand": best["rag_demand"],
        "dno": best["dno"],
        "dist_km": round(dist_km, 2),
        "queue_depth": queue_count,
        "nearby_substations": [
            {"name": r["name"], "headroom_mw": round(float(r["demand_headroom_mw"]), 2),
             "dist_km": round(float(r["dist_km"]), 2)}
            for r in rows[:3]
        ],
    }


async def _score_fibre_proximity(conn: asyncpg.Connection, lat: float, lon: float) -> tuple[float, dict]:
    row = await conn.fetchrow("""
        SELECT name, operator, pop_type,
               ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km
        FROM dc_fibre_pops
        ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 1
    """, lon, lat)

    if not row:
        return 10.0, {"distance_km": None, "name": None, "rating": "Unknown"}

    dist = float(row["dist_km"])
    score = _distance_score(dist, 1, 3, 8, 20)
    rating = _distance_rating(dist, 1, 3, 8)

    return score, {
        "distance_km": round(dist, 2),
        "name": row["name"],
        "provider": row["operator"] or "Unknown",
        "type": row["pop_type"],
        "rating": rating,
    }


async def _score_ixp_proximity(conn: asyncpg.Connection, lat: float, lon: float) -> tuple[float, dict]:
    row = await conn.fetchrow("""
        SELECT name, city, participants,
               ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km
        FROM dc_ixp_nodes
        ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 1
    """, lon, lat)

    if not row:
        return 10.0, {"distance_km": None, "name": None, "rating": "Unknown"}

    dist = float(row["dist_km"])
    score = _distance_score(dist, 20, 50, 100, 200)
    rating = _distance_rating(dist, 20, 50, 100)

    return score, {
        "distance_km": round(dist, 2),
        "name": row["name"],
        "participants": row["participants"],
        "rating": rating,
    }


async def _score_water_cooling(conn: asyncpg.Connection, lat: float, lon: float) -> tuple[float, dict]:
    row = await conn.fetchrow("""
        SELECT name, water_type,
               ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km
        FROM dc_water_bodies
        ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 1
    """, lon, lat)

    if not row:
        return 15.0, {"distance_km": None, "name": None, "rating": "Unknown"}

    dist = float(row["dist_km"])
    score = _distance_score(dist, 1, 5, 15, 30)
    rating = _distance_rating(dist, 1, 5, 15)

    # Bonus for rivers (continuous supply) vs lakes
    if row["water_type"] in ("river", "canal"):
        score = min(100, score + 5)

    return score, {
        "distance_km": round(dist, 2),
        "name": row["name"],
        "type": row["water_type"],
        "rating": rating,
    }


async def _score_latency(conn: asyncpg.Connection, lat: float, lon: float) -> tuple[float, dict]:
    """Composite latency: IXP distance + population centre proximity + fibre model."""
    # Nearest IXP distance
    ixp_row = await conn.fetchrow("""
        SELECT name,
               ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km
        FROM dc_ixp_nodes
        ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 1
    """, lon, lat)

    ixp_dist = float(ixp_row["dist_km"]) if ixp_row else 200
    ixp_latency_us = ixp_dist * 5  # ~5 µs/km fibre propagation

    # Nearest major population centre
    min_pop_dist = 999
    nearest_city = "Unknown"
    for pc in UK_POP_CENTRES:
        d = _haversine_km(lat, lon, pc["lat"], pc["lon"])
        if d < min_pop_dist:
            min_pop_dist = d
            nearest_city = pc["name"]

    pop_latency_us = min_pop_dist * 5

    # Composite score (lower latency = higher score)
    ixp_score = max(0, 100 - ixp_latency_us / 10)
    pop_score = max(0, 100 - pop_latency_us / 5)
    score = ixp_score * 0.6 + pop_score * 0.4

    return score, {
        "ixp_latency_us": round(ixp_latency_us, 1),
        "pop_latency_us": round(pop_latency_us, 1),
        "nearest_ixp": ixp_row["name"] if ixp_row else None,
        "nearest_city": nearest_city,
        "nearest_city_km": round(min_pop_dist, 1),
    }


async def _score_land_planning(conn: asyncpg.Connection, lat: float, lon: float) -> tuple[float, dict]:
    """Land use and planning score — brownfield bonus for DCs."""
    score = 65.0  # neutral baseline
    details: dict[str, Any] = {}

    # Check for brownfield / industrial land via GeeFlow
    geeflow = await conn.fetchrow("""
        SELECT result_data FROM geeflow_extractions
        WHERE mode = 'land_use'
          AND abs(lat - $1) < 0.02 AND abs(lon - $2) < 0.02
        ORDER BY created_at DESC LIMIT 1
    """, lat, lon)

    if geeflow:
        import json as _json
        rd = geeflow["result_data"]
        if isinstance(rd, str):
            rd = _json.loads(rd)
        dominant = rd.get("dominant_class", "")
        details["land_use"] = dominant
        if dominant in ("built", "built_area"):
            score += 15  # brownfield bonus
            details["brownfield"] = True
        elif dominant in ("crops", "grass"):
            score -= 5  # greenbelt caution
            details["brownfield"] = False

    # Check flood risk
    flood = await conn.fetchrow("""
        SELECT result_data FROM geeflow_extractions
        WHERE mode = 'flood_risk'
          AND abs(lat - $1) < 0.02 AND abs(lon - $2) < 0.02
        ORDER BY created_at DESC LIMIT 1
    """, lat, lon)

    if flood:
        import json as _json
        rd = flood["result_data"]
        if isinstance(rd, str):
            rd = _json.loads(rd)
        flood_pct = rd.get("flood_percentage", 0)
        details["flood_pct"] = flood_pct
        if flood_pct > 10:
            score -= 20
        elif flood_pct > 2:
            score -= 10

    return min(100, max(0, score)), details


async def _score_resilience(conn: asyncpg.Connection, lat: float, lon: float,
                             capacity_mw: float) -> tuple[float, dict]:
    """Count independent substations at different voltage tiers (dual-feed capability)."""
    rows = await conn.fetch("""
        SELECT name, voltage_kv, demand_headroom_mw,
               ST_Distance(geom, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km
        FROM grid_substations
        WHERE ST_DWithin(geom, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700), 30000)
        ORDER BY dist_km
        LIMIT 20
    """, lon, lat)

    voltage_tiers = set()
    substations_in_range = len(rows)
    dual_feed = False

    for r in rows:
        v = r["voltage_kv"]
        if v:
            voltage_tiers.add(v)
        h = r["demand_headroom_mw"]
        if h and float(h) >= capacity_mw and float(r["dist_km"]) < 15:
            dual_feed = True

    score = 30.0  # baseline
    if substations_in_range >= 3:
        score += 20
    elif substations_in_range >= 2:
        score += 10
    if len(voltage_tiers) >= 3:
        score += 20
    elif len(voltage_tiers) >= 2:
        score += 10
    if dual_feed:
        score += 20
    if any(v >= 132 for v in voltage_tiers):
        score += 10

    return min(100, score), {
        "substations_30km": substations_in_range,
        "voltage_tiers": sorted(voltage_tiers),
        "dual_feed_available": dual_feed,
    }


async def _score_connection_speed(conn: asyncpg.Connection, lat: float, lon: float) -> tuple[float, dict]:
    """Fibre provider density and carrier-neutral exchange proximity."""
    rows = await conn.fetch("""
        SELECT name, operator, pop_type,
               ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km
        FROM dc_fibre_pops
        WHERE ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700), 10000)
        ORDER BY dist_km
        LIMIT 20
    """, lon, lat)

    provider_count = len(set(r["operator"] for r in rows if r["operator"]))
    exchange_count = len(rows)

    score = 30.0
    if exchange_count >= 5:
        score += 30
    elif exchange_count >= 3:
        score += 20
    elif exchange_count >= 1:
        score += 10
    if provider_count >= 3:
        score += 25
    elif provider_count >= 2:
        score += 15
    elif provider_count >= 1:
        score += 5

    # Bonus for very close exchange
    if rows and float(rows[0]["dist_km"]) < 1:
        score += 15

    return min(100, score), {
        "exchanges_10km": exchange_count,
        "providers": provider_count,
        "nearest_km": round(float(rows[0]["dist_km"]), 2) if rows else None,
    }


# ---------------------------------------------------------------------------
# Gate check
# ---------------------------------------------------------------------------
def _check_gates(proximity: dict, scores: dict, profile: str,
                 custom_gates: dict | None = None) -> dict:
    """Check hard gate thresholds."""
    gates = dict(FACILITY_PROFILES.get(profile, {}).get("gates", {}))
    if custom_gates:
        gates.update(custom_gates)

    results = {}

    if "min_headroom_mw" in gates:
        headroom = scores.get("grid_headroom", {}).get("detail", {}).get("headroom_mw")
        passed = headroom is not None and headroom >= gates["min_headroom_mw"]
        results["min_headroom_mw"] = {
            "passed": passed, "value": headroom, "threshold": gates["min_headroom_mw"],
        }

    if "max_fibre_km" in gates:
        fibre_km = proximity.get("fibre", {}).get("distance_km")
        passed = fibre_km is not None and fibre_km <= gates["max_fibre_km"]
        results["max_fibre_km"] = {
            "passed": passed, "value": fibre_km, "threshold": gates["max_fibre_km"],
        }

    if "max_ixp_km" in gates:
        ixp_km = proximity.get("ixp", {}).get("distance_km")
        passed = ixp_km is not None and ixp_km <= gates["max_ixp_km"]
        results["max_ixp_km"] = {
            "passed": passed, "value": ixp_km, "threshold": gates["max_ixp_km"],
        }

    if "max_water_km" in gates:
        water_km = proximity.get("water", {}).get("distance_km")
        passed = water_km is None or water_km <= gates["max_water_km"]
        results["max_water_km"] = {
            "passed": passed, "value": water_km, "threshold": gates["max_water_km"],
        }

    return results


# ---------------------------------------------------------------------------
# Connection cost estimate
# ---------------------------------------------------------------------------
def _estimate_connection_cost(dist_km: float, voltage_kv: float, capacity_mw: float) -> dict:
    # Find appropriate voltage tier
    rate = CONNECTION_COST_RATES.get(int(voltage_kv), CONNECTION_COST_RATES.get(33, 150_000))
    base = dist_km * rate
    # Reinforcement premium for large loads
    reinforcement = 0
    if capacity_mw > 50:
        reinforcement = base * 0.4
    elif capacity_mw > 20:
        reinforcement = base * 0.2

    p50 = base + reinforcement
    return {
        "p10_gbp": round(p50 * 0.7),
        "p50_gbp": round(p50),
        "p90_gbp": round(p50 * 1.5),
        "rate_per_km": rate,
        "distance_km": round(dist_km, 2),
        "voltage_kv": voltage_kv,
    }


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------
async def score_dc_site(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    capacity_mw: float = 10,
    profile: str = "colocation",
    custom_weights: dict | None = None,
    custom_gates: dict | None = None,
) -> dict:
    """Score a site for data centre co-location suitability.

    Returns dc_score (0-100), verdict, confidence, scores breakdown,
    proximity matrix, gates status, grid connection detail, risks, opportunities.
    """
    prof = FACILITY_PROFILES.get(profile, FACILITY_PROFILES["colocation"])
    weights = dict(prof["weights"])
    if custom_weights:
        weights.update(custom_weights)
        # Normalise to sum=100
        total_w = sum(weights.values())
        if total_w > 0 and total_w != 100:
            weights = {k: v * 100 / total_w for k, v in weights.items()}

    # Run all 9 dimensions
    power_score, power_detail = await _score_power_capacity(conn, lat, lon, capacity_mw)
    headroom_score, headroom_detail = await _score_grid_headroom(conn, lat, lon, capacity_mw)
    fibre_score, fibre_detail = await _score_fibre_proximity(conn, lat, lon)
    ixp_score, ixp_detail = await _score_ixp_proximity(conn, lat, lon)
    water_score, water_detail = await _score_water_cooling(conn, lat, lon)
    latency_score, latency_detail = await _score_latency(conn, lat, lon)
    land_score, land_detail = await _score_land_planning(conn, lat, lon)
    resilience_score, resilience_detail = await _score_resilience(conn, lat, lon, capacity_mw)
    conn_speed_score, conn_speed_detail = await _score_connection_speed(conn, lat, lon)

    raw_scores = {
        "power_capacity":   {"score": round(power_score, 1),     "detail": power_detail},
        "grid_headroom":    {"score": round(headroom_score, 1),  "detail": headroom_detail},
        "fibre_proximity":  {"score": round(fibre_score, 1),     "detail": fibre_detail},
        "ixp_proximity":    {"score": round(ixp_score, 1),       "detail": ixp_detail},
        "water_cooling":    {"score": round(water_score, 1),     "detail": water_detail},
        "latency":          {"score": round(latency_score, 1),   "detail": latency_detail},
        "land_planning":    {"score": round(land_score, 1),      "detail": land_detail},
        "resilience":       {"score": round(resilience_score, 1), "detail": resilience_detail},
        "connection_speed": {"score": round(conn_speed_score, 1), "detail": conn_speed_detail},
    }

    # Weighted total
    dc_score = 0.0
    for dim, w in weights.items():
        s = raw_scores.get(dim, {}).get("score", 0)
        dc_score += s * w / 100.0
    dc_score = round(min(100, max(0, dc_score)), 1)

    # Proximity matrix (Peaknode-compatible format with REAL data)
    proximity = {
        "fibre": fibre_detail,
        "ixp": ixp_detail,
        "water": water_detail,
        "substation": {
            "distance_km": power_detail.get("dist_km"),
            "name": power_detail.get("substation"),
            "headroom_mw": headroom_detail.get("headroom_mw"),
            "voltage_kv": power_detail.get("voltage_kv"),
            "rating": _distance_rating(power_detail.get("dist_km", 99), 1, 3, 8),
        },
    }

    # Add nearest existing DC facility
    dc_fac = await conn.fetchrow("""
        SELECT name, operator,
               ST_Distance(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)) / 1000.0 AS dist_km
        FROM dc_facilities
        ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
        LIMIT 1
    """, lon, lat)
    if dc_fac:
        proximity["dc_facility"] = {
            "distance_km": round(float(dc_fac["dist_km"]), 2),
            "name": dc_fac["name"],
            "operator": dc_fac["operator"] or "Unknown",
            "rating": _distance_rating(float(dc_fac["dist_km"]), 5, 15, 30),
        }

    # Gates
    gates = _check_gates(proximity, raw_scores, profile, custom_gates)
    gates_passed = all(g["passed"] for g in gates.values()) if gates else True

    # Connection cost
    sub_dist = power_detail.get("dist_km", 5)
    sub_voltage = power_detail.get("voltage_kv", 33)
    cost = _estimate_connection_cost(sub_dist, sub_voltage, capacity_mw)

    # Verdict
    if dc_score >= 70 and gates_passed:
        verdict = "GO"
        confidence = min(0.95, 0.6 + dc_score / 300)
    elif dc_score >= 45 or (dc_score >= 35 and gates_passed):
        verdict = "CAUTION"
        confidence = 0.5 + dc_score / 400
    else:
        verdict = "NO-GO"
        confidence = max(0.3, 0.7 - dc_score / 200)

    # Risks & opportunities
    risks = []
    opportunities = []

    if headroom_detail.get("headroom_mw") is not None:
        h = headroom_detail["headroom_mw"]
        if h < capacity_mw:
            risks.append(f"Insufficient headroom: {h:.1f} MW available vs {capacity_mw} MW requested")
        elif h >= capacity_mw * 2:
            opportunities.append(f"Ample headroom: {h:.1f} MW available — room for expansion")

    if headroom_detail.get("queue_depth", 0) > 3:
        risks.append(f"High queue depth ({headroom_detail['queue_depth']} applications) at nearest substation")

    if fibre_detail.get("distance_km") and fibre_detail["distance_km"] > 5:
        risks.append(f"Fibre connectivity: {fibre_detail['distance_km']:.1f} km to nearest POP")
    elif fibre_detail.get("distance_km") and fibre_detail["distance_km"] < 1:
        opportunities.append("Excellent fibre: sub-1km to nearest exchange")

    if water_detail.get("rating") == "Far":
        risks.append("No nearby water source for cooling — air cooling only")

    if resilience_detail.get("dual_feed_available"):
        opportunities.append("Dual-feed capability available from independent substations")

    if land_detail.get("brownfield"):
        opportunities.append("Brownfield site — favourable planning for DC development")

    if land_detail.get("flood_pct", 0) > 5:
        risks.append(f"Flood risk: {land_detail['flood_pct']:.0f}% flood probability in area")

    return {
        "dc_score": dc_score,
        "verdict": verdict,
        "confidence": round(confidence, 2),
        "profile": profile,
        "capacity_mw": capacity_mw,
        "lat": lat,
        "lon": lon,
        "scores": raw_scores,
        "weights": weights,
        "proximity": proximity,
        "gates": gates,
        "gates_all_passed": gates_passed,
        "grid_connection": {
            "headroom_mw": headroom_detail.get("headroom_mw"),
            "rag_demand": headroom_detail.get("rag_demand"),
            "substation": headroom_detail.get("substation"),
            "dno": headroom_detail.get("dno"),
            "queue_depth": headroom_detail.get("queue_depth", 0),
            "cost_estimate": cost,
        },
        "risks": risks,
        "opportunities": opportunities,
    }


# ---------------------------------------------------------------------------
# Batch scan
# ---------------------------------------------------------------------------
async def scan_dc_sites(
    conn: asyncpg.Connection,
    profile: str = "colocation",
    capacity_mw: float = 10,
    bbox: dict | None = None,
    min_headroom_mw: float | None = None,
    limit: int = 50,
) -> dict:
    """Scan substations with demand headroom and score each for DC suitability."""
    conditions = ["demand_headroom_mw IS NOT NULL"]
    params: list[Any] = []
    idx = 1

    if min_headroom_mw is not None:
        conditions.append(f"demand_headroom_mw >= ${idx}")
        params.append(min_headroom_mw)
        idx += 1

    if bbox:
        conditions.append(f"""
            ST_Within(geom, ST_Transform(
                ST_MakeEnvelope(${idx}, ${idx + 1}, ${idx + 2}, ${idx + 3}, 4326), 27700))
        """)
        params.extend([bbox["west"], bbox["south"], bbox["east"], bbox["north"]])
        idx += 4

    where = " AND ".join(conditions)
    rows = await conn.fetch(f"""
        SELECT name, voltage_kv, demand_headroom_mw, dno,
               ST_Y(ST_Transform(geom, 4326)) AS lat,
               ST_X(ST_Transform(geom, 4326)) AS lon
        FROM grid_substations
        WHERE {where}
        ORDER BY demand_headroom_mw DESC
        LIMIT ${{idx}}
    """.replace("${idx}", f"${idx}"), *params, limit * 2)  # fetch extra, score top

    sites = []
    for r in rows[:limit]:
        try:
            result = await score_dc_site(conn, float(r["lat"]), float(r["lon"]),
                                          capacity_mw, profile)
            result["substation_name"] = r["name"]
            sites.append(result)
        except Exception as e:
            log.warning("Failed to score DC site at %s: %s", r["name"], e)

    sites.sort(key=lambda s: s["dc_score"], reverse=True)

    return {
        "profile": profile,
        "capacity_mw": capacity_mw,
        "count": len(sites),
        "sites": sites[:limit],
    }


# ---------------------------------------------------------------------------
# GeoJSON capacity map
# ---------------------------------------------------------------------------
async def dc_capacity_map_geojson(
    conn: asyncpg.Connection,
    profile: str = "colocation",
    min_headroom_mw: float = 5,
    bbox: dict | None = None,
) -> dict:
    """GeoJSON FeatureCollection of substations colored by DC suitability."""
    conditions = ["demand_headroom_mw IS NOT NULL", f"demand_headroom_mw >= {min_headroom_mw}"]

    if bbox:
        conditions.append(f"""
            ST_Within(geom, ST_Transform(
                ST_MakeEnvelope({bbox['west']}, {bbox['south']}, {bbox['east']}, {bbox['north']}, 4326), 27700))
        """)

    where = " AND ".join(conditions)
    rows = await conn.fetch(f"""
        SELECT name, voltage_kv, demand_headroom_mw, rag_demand, dno,
               ST_Y(ST_Transform(geom, 4326)) AS lat,
               ST_X(ST_Transform(geom, 4326)) AS lon
        FROM grid_substations
        WHERE {where}
        ORDER BY demand_headroom_mw DESC
        LIMIT 500
    """)

    prof = FACILITY_PROFILES.get(profile, FACILITY_PROFILES["colocation"])
    min_cap = prof.get("gates", {}).get("min_headroom_mw", 5)

    features = []
    for r in rows:
        headroom = float(r["demand_headroom_mw"])
        # Suitability color
        if headroom >= min_cap * 3:
            color = "#24a148"  # green — excellent
            suitability = "excellent"
        elif headroom >= min_cap:
            color = "#f1c21b"  # amber — suitable
            suitability = "suitable"
        else:
            color = "#da1e28"  # red — limited
            suitability = "limited"

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "name": r["name"],
                "voltage_kv": r["voltage_kv"],
                "headroom_mw": round(headroom, 2),
                "rag_demand": r["rag_demand"],
                "dno": r["dno"],
                "suitability": suitability,
                "color": color,
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "profile": profile,
            "min_headroom_mw": min_headroom_mw,
            "count": len(features),
        },
    }


# ---------------------------------------------------------------------------
# Profiles helper
# ---------------------------------------------------------------------------
def get_facility_profiles() -> dict:
    """Return available facility profiles with weights, gates, descriptions."""
    return FACILITY_PROFILES

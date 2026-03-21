"""
Cable Route Optimiser — cost-optimal routing from site to substation.

Computes cable routes with terrain-weighted costing, voltage auto-selection,
P10/P50/P90 cost bands, and multi-substation ranking.

Called from app/routers/cable_routing.py and agent module.
"""

from __future__ import annotations

import logging
import math
import random
import time
from typing import Any

log = logging.getLogger("princeps.cable_route_optimiser")

# ─── Cost Constants (UK typical, GBP) ────────────────────────────────────

TERRAIN_COSTS: dict[str, float] = {
    "field_open": 80,        # £/m — direct burial in open farmland
    "road_crossing": 500,    # £/m — boring under road
    "river_crossing": 2000,  # £/m — horizontal directional drilling
    "railway_crossing": 3000,# £/m — Network Rail crossing
    "woodland": 200,         # £/m — tree clearance + burial
    "urban": 400,            # £/m — built-up area, utilities avoidance
    "wetland": 350,          # £/m — environmental sensitivity
}

VOLTAGE_COSTS: dict[int, dict[str, float]] = {
    11:  {"cable_per_km": 80_000,  "jointing": 5_000,  "switchgear": 25_000},
    33:  {"cable_per_km": 150_000, "jointing": 12_000, "switchgear": 65_000},
    66:  {"cable_per_km": 300_000, "jointing": 25_000, "switchgear": 120_000},
    132: {"cable_per_km": 500_000, "jointing": 45_000, "switchgear": 250_000},
}

# Default terrain mix when no GeeFlow data is available (UK rural average)
DEFAULT_TERRAIN_MIX: dict[str, float] = {
    "field_open": 0.65,
    "road_crossing": 0.10,
    "woodland": 0.08,
    "urban": 0.07,
    "wetland": 0.05,
    "river_crossing": 0.03,
    "railway_crossing": 0.02,
}

# Routing factor range — cables never go perfectly straight
ROUTING_FACTOR_MIN = 1.15
ROUTING_FACTOR_MAX = 1.25

# Jointing interval (metres)
JOINTING_INTERVAL_M = 500

# Contingency percentage
CONTINGENCY_PCT = 0.15


# ─── Helpers ──────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two WGS-84 points."""
    R = 6371.0
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _auto_voltage(capacity_mw: float) -> int:
    """Select voltage level based on project capacity."""
    if capacity_mw <= 5:
        return 11
    elif capacity_mw <= 50:
        return 33
    elif capacity_mw <= 150:
        return 66
    else:
        return 132


def _interpolate_points(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    n_points: int = 10,
) -> list[list[float]]:
    """Generate intermediate waypoints along a route with slight random offsets.

    Returns list of [lon, lat] pairs (GeoJSON order).
    """
    points = [[lon1, lat1]]
    for i in range(1, n_points):
        frac = i / n_points
        lat = lat1 + (lat2 - lat1) * frac
        lon = lon1 + (lon2 - lon1) * frac
        # Small perpendicular jitter to simulate non-straight routing
        jitter = random.gauss(0, 0.0005)
        lat += jitter
        lon += jitter * 0.7
        points.append([round(lon, 6), round(lat, 6)])
    points.append([lon2, lat2])
    return points


def _terrain_mix_from_geeflow(extraction: dict | None) -> dict[str, float]:
    """Extract terrain mix from a GeeFlow land-use extraction.

    Maps DynamicWorld classes to our terrain categories.
    """
    if not extraction:
        return DEFAULT_TERRAIN_MIX.copy()

    result = extraction.get("result") or extraction.get("data") or {}
    land_use = result.get("land_use_distribution") or result.get("classes") or {}

    if not land_use:
        return DEFAULT_TERRAIN_MIX.copy()

    # DynamicWorld class mapping → our terrain categories
    dw_mapping = {
        "crops": "field_open",
        "grass": "field_open",
        "bare": "field_open",
        "shrub_and_scrub": "field_open",
        "trees": "woodland",
        "built": "urban",
        "water": "river_crossing",
        "flooded_vegetation": "wetland",
        "snow_and_ice": "field_open",
    }

    mix: dict[str, float] = {}
    total = 0.0
    for dw_class, pct in land_use.items():
        terrain = dw_mapping.get(dw_class.lower(), "field_open")
        val = float(pct) if isinstance(pct, (int, float)) else 0
        mix[terrain] = mix.get(terrain, 0) + val
        total += val

    if total <= 0:
        return DEFAULT_TERRAIN_MIX.copy()

    # Normalise to fractions
    for k in mix:
        mix[k] /= total

    # Ensure road and railway crossings are represented (not in satellite data)
    if "road_crossing" not in mix:
        # Steal proportionally from largest category
        mix["road_crossing"] = 0.08
        mix["railway_crossing"] = 0.02
        remaining = 1.0 - 0.08 - 0.02
        current_total = sum(mix[k] for k in mix if k not in ("road_crossing", "railway_crossing"))
        if current_total > 0:
            for k in mix:
                if k not in ("road_crossing", "railway_crossing"):
                    mix[k] = mix[k] / current_total * remaining

    return mix


def _generate_terrain_segments(
    distance_km: float, terrain_mix: dict[str, float],
) -> list[dict[str, Any]]:
    """Break route into terrain segments with individual costs."""
    segments = []
    for terrain, fraction in sorted(terrain_mix.items(), key=lambda x: -x[1]):
        if fraction <= 0:
            continue
        seg_km = round(distance_km * fraction, 3)
        seg_m = seg_km * 1000
        cost_per_m = TERRAIN_COSTS.get(terrain, TERRAIN_COSTS["field_open"])
        segments.append({
            "terrain": terrain,
            "fraction": round(fraction, 3),
            "distance_km": seg_km,
            "distance_m": round(seg_m, 1),
            "cost_per_m": cost_per_m,
            "civils_cost": round(seg_m * cost_per_m, 0),
        })
    return segments


def _cost_breakdown(
    distance_km: float,
    voltage_kv: int,
    terrain_mix: dict[str, float],
) -> dict[str, Any]:
    """Compute full cost breakdown for a cable route.

    Returns P10 (optimistic), P50 (expected), P90 (pessimistic) bands.
    """
    vc = VOLTAGE_COSTS.get(voltage_kv, VOLTAGE_COSTS[33])
    distance_m = distance_km * 1000

    # Cable supply cost
    cable_cost = distance_km * vc["cable_per_km"]

    # Jointing — one joint every 500m
    n_joints = max(1, int(distance_m / JOINTING_INTERVAL_M))
    jointing_cost = n_joints * vc["jointing"]

    # Switchgear at each end
    switchgear_cost = 2 * vc["switchgear"]

    # Civils — terrain-weighted
    civils_cost = 0.0
    for terrain, fraction in terrain_mix.items():
        seg_m = distance_m * fraction
        cost_per_m = TERRAIN_COSTS.get(terrain, TERRAIN_COSTS["field_open"])
        civils_cost += seg_m * cost_per_m

    # Subtotal before contingency
    subtotal = cable_cost + jointing_cost + switchgear_cost + civils_cost

    # Contingency
    contingency = subtotal * CONTINGENCY_PCT

    # P50 total
    p50_total = subtotal + contingency

    # P10 (optimistic: -15%) and P90 (pessimistic: +25%)
    p10_total = round(p50_total * 0.85, 0)
    p90_total = round(p50_total * 1.25, 0)

    return {
        "cable_supply": round(cable_cost, 0),
        "jointing": round(jointing_cost, 0),
        "jointing_count": n_joints,
        "switchgear": round(switchgear_cost, 0),
        "civils": round(civils_cost, 0),
        "subtotal": round(subtotal, 0),
        "contingency_pct": CONTINGENCY_PCT,
        "contingency": round(contingency, 0),
        "total_p10": p10_total,
        "total_p50": round(p50_total, 0),
        "total_p90": p90_total,
        "cost_per_km_p50": round(p50_total / distance_km, 0) if distance_km > 0 else 0,
    }


# ─── Public API ───────────────────────────────────────────────────────────

async def optimise_route(
    site_lat: float,
    site_lon: float,
    sub_lat: float,
    sub_lon: float,
    capacity_mw: float,
    voltage_kv: int | None = None,
    pool=None,
) -> dict[str, Any]:
    """Compute optimal cable route from site to target substation.

    Parameters
    ----------
    site_lat, site_lon : float
        Site (generation) location in WGS-84.
    sub_lat, sub_lon : float
        Target substation location in WGS-84.
    capacity_mw : float
        Project capacity in MW.
    voltage_kv : int | None
        Force voltage level; auto-selected from capacity if None.
    pool : asyncpg.Pool | None
        Database pool for GeeFlow terrain data lookup.

    Returns
    -------
    dict with route GeoJSON, distance, costs, voltage, terrain segments.
    """
    t0 = time.time()

    # Auto-select voltage
    if voltage_kv is None:
        voltage_kv = _auto_voltage(capacity_mw)
    if voltage_kv not in VOLTAGE_COSTS:
        voltage_kv = min(VOLTAGE_COSTS, key=lambda v: abs(v - voltage_kv))

    # Straight-line distance
    straight_km = _haversine_km(site_lat, site_lon, sub_lat, sub_lon)

    # Routing factor (cables never go straight)
    routing_factor = random.uniform(ROUTING_FACTOR_MIN, ROUTING_FACTOR_MAX)
    routed_km = round(straight_km * routing_factor, 3)

    # Terrain mix — try GeeFlow extraction if pool available
    terrain_mix = DEFAULT_TERRAIN_MIX.copy()
    geeflow_source = "default"

    if pool is not None:
        try:
            async with pool.acquire(timeout=5) as conn:
                # Look for GeeFlow land_use extraction near the midpoint
                mid_lat = (site_lat + sub_lat) / 2
                mid_lon = (site_lon + sub_lon) / 2
                row = await conn.fetchrow("""
                    SELECT result_json
                    FROM geeflow_extractions
                    WHERE mode = 'land_use'
                      AND ST_DWithin(
                          geom,
                          ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                          $3
                      )
                    ORDER BY created_at DESC
                    LIMIT 1
                """, mid_lon, mid_lat, max(routed_km * 1000, 5000))

                if row and row["result_json"]:
                    import json as _json
                    data = row["result_json"]
                    if isinstance(data, str):
                        data = _json.loads(data)
                    terrain_mix = _terrain_mix_from_geeflow(data)
                    geeflow_source = "geeflow"
        except Exception as e:
            log.warning("GeeFlow terrain lookup failed, using defaults: %s", e)

    # Terrain segments
    terrain_segments = _generate_terrain_segments(routed_km, terrain_mix)

    # Cost breakdown
    costs = _cost_breakdown(routed_km, voltage_kv, terrain_mix)

    # Generate route waypoints (GeoJSON LineString)
    n_waypoints = max(5, min(20, int(routed_km * 2)))
    waypoints = _interpolate_points(
        site_lat, site_lon, sub_lat, sub_lon, n_waypoints,
    )

    route_geojson = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": waypoints,
        },
        "properties": {
            "voltage_kv": voltage_kv,
            "capacity_mw": capacity_mw,
            "distance_km": routed_km,
            "total_cost_p50": costs["total_p50"],
        },
    }

    elapsed = round(time.time() - t0, 3)

    return {
        "route": route_geojson,
        "site": {"lat": site_lat, "lon": site_lon},
        "substation": {"lat": sub_lat, "lon": sub_lon},
        "straight_line_km": round(straight_km, 3),
        "routed_distance_km": routed_km,
        "routing_factor": round(routing_factor, 3),
        "voltage_kv": voltage_kv,
        "capacity_mw": capacity_mw,
        "terrain_source": geeflow_source,
        "terrain_segments": terrain_segments,
        "cost_breakdown": costs,
        "total_cost_p10": costs["total_p10"],
        "total_cost_p50": costs["total_p50"],
        "total_cost_p90": costs["total_p90"],
        "elapsed_s": elapsed,
    }


async def find_best_route(
    site_lat: float,
    site_lon: float,
    capacity_mw: float,
    pool,
    search_radius_km: float = 20.0,
    max_candidates: int = 5,
) -> dict[str, Any]:
    """Find and rank cable routes to multiple nearby substations.

    Queries grid_substations within radius, computes route to each,
    and returns ranked by total P50 cost with trade-off annotations.

    Parameters
    ----------
    site_lat, site_lon : float
        Site location in WGS-84.
    capacity_mw : float
        Project capacity in MW.
    pool : asyncpg.Pool
        Database connection pool.
    search_radius_km : float
        Search radius for substations (default 20km).
    max_candidates : int
        Maximum number of substation candidates to evaluate.

    Returns
    -------
    dict with ranked routes, best route, and comparison summary.
    """
    t0 = time.time()

    auto_voltage = _auto_voltage(capacity_mw)

    # Find nearby substations
    async with pool.acquire(timeout=10) as conn:
        rows = await conn.fetch("""
            SELECT
                id, external_id, name, dno, voltage_kv,
                demand_headroom_mw, gen_headroom_mw,
                ST_Distance(
                    geom,
                    ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
                ) / 1000.0 AS distance_km,
                ST_X(ST_Transform(geom, 4326)) AS sub_lon,
                ST_Y(ST_Transform(geom, 4326)) AS sub_lat
            FROM grid_substations
            WHERE ST_DWithin(
                geom,
                ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700),
                $3
            )
            ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            LIMIT $4
        """, site_lon, site_lat, search_radius_km * 1000, max_candidates)

    substations = [
        {
            "id": r["id"],
            "external_id": r["external_id"],
            "name": r["name"],
            "dno": r["dno"],
            "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
            "headroom_mw": float(r["gen_headroom_mw"]) if r["gen_headroom_mw"] else None,
            "distance_km": round(float(r["distance_km"]), 2),
            "lat": float(r["sub_lat"]),
            "lon": float(r["sub_lon"]),
        }
        for r in rows
    ]

    if not substations:
        return {
            "site": {"lat": site_lat, "lon": site_lon},
            "capacity_mw": capacity_mw,
            "search_radius_km": search_radius_km,
            "candidates_found": 0,
            "routes": [],
            "best_route": None,
            "summary": "No substations found within search radius.",
            "elapsed_s": round(time.time() - t0, 3),
        }

    # Compute route to each substation
    routes = []
    for sub in substations:
        # Determine voltage: use substation voltage if suitable, else auto
        sub_voltage = int(sub["voltage_kv"]) if sub["voltage_kv"] else None
        if sub_voltage and sub_voltage in VOLTAGE_COSTS and sub_voltage >= auto_voltage:
            use_voltage = sub_voltage
        else:
            use_voltage = auto_voltage

        route = await optimise_route(
            site_lat, site_lon,
            sub["lat"], sub["lon"],
            capacity_mw,
            voltage_kv=use_voltage,
            pool=pool,
        )

        # Annotate with substation info
        route["substation_id"] = sub["id"]
        route["substation_name"] = sub["name"]
        route["substation_dno"] = sub["dno"]
        route["substation_voltage_kv"] = sub["voltage_kv"]
        route["headroom_mw"] = sub["headroom_mw"]
        route["has_headroom"] = (
            sub["headroom_mw"] is not None and sub["headroom_mw"] >= capacity_mw
        )

        # Trade-off annotation
        trade_offs = []
        if route["routed_distance_km"] < 3:
            trade_offs.append("Very short route — low civils cost")
        elif route["routed_distance_km"] > 10:
            trade_offs.append("Long route — high civils cost but may have better headroom")

        if route["has_headroom"]:
            trade_offs.append(f"Sufficient headroom ({sub['headroom_mw']:.1f} MW)")
        elif sub["headroom_mw"] is not None:
            trade_offs.append(f"Insufficient headroom ({sub['headroom_mw']:.1f} MW) — reinforcement likely")

        if use_voltage > auto_voltage:
            trade_offs.append(f"Higher voltage ({use_voltage}kV) — more expensive cable but future-proof")
        elif use_voltage < 33 and capacity_mw > 3:
            trade_offs.append("Low voltage — may need upgrade for full capacity")

        route["trade_offs"] = trade_offs

        routes.append(route)

    # Rank by P50 cost
    routes.sort(key=lambda r: r["total_cost_p50"])

    # Add rank
    for i, r in enumerate(routes):
        r["rank"] = i + 1

    best = routes[0]

    elapsed = round(time.time() - t0, 3)

    return {
        "site": {"lat": site_lat, "lon": site_lon},
        "capacity_mw": capacity_mw,
        "auto_voltage_kv": auto_voltage,
        "search_radius_km": search_radius_km,
        "candidates_found": len(substations),
        "routes": routes,
        "best_route": best,
        "summary": (
            f"Best route to {best['substation_name']} — "
            f"{best['routed_distance_km']:.1f} km at {best['voltage_kv']}kV, "
            f"P50 cost £{best['total_cost_p50']:,.0f}"
        ),
        "elapsed_s": elapsed,
    }


def quick_cost_estimate(
    distance_km: float,
    voltage_kv: int = 33,
    terrain: str = "rural",
) -> dict[str, Any]:
    """Quick cost lookup without route computation.

    Parameters
    ----------
    distance_km : float
        Cable route length.
    voltage_kv : int
        Voltage level (11, 33, 66, 132).
    terrain : str
        Terrain type: "rural", "urban", "mixed", or specific terrain key.
    """
    if voltage_kv not in VOLTAGE_COSTS:
        voltage_kv = min(VOLTAGE_COSTS, key=lambda v: abs(v - voltage_kv))

    # Map terrain shorthand to mix
    terrain_mixes = {
        "rural": {"field_open": 0.75, "road_crossing": 0.10, "woodland": 0.08, "river_crossing": 0.02, "railway_crossing": 0.01, "wetland": 0.04},
        "urban": {"urban": 0.60, "road_crossing": 0.25, "field_open": 0.10, "river_crossing": 0.03, "railway_crossing": 0.02},
        "mixed": {"field_open": 0.40, "urban": 0.25, "road_crossing": 0.15, "woodland": 0.10, "river_crossing": 0.05, "railway_crossing": 0.03, "wetland": 0.02},
        "woodland": {"woodland": 0.60, "field_open": 0.25, "road_crossing": 0.10, "river_crossing": 0.03, "railway_crossing": 0.02},
    }

    mix = terrain_mixes.get(terrain, terrain_mixes["rural"])

    costs = _cost_breakdown(distance_km, voltage_kv, mix)
    segments = _generate_terrain_segments(distance_km, mix)

    return {
        "distance_km": distance_km,
        "voltage_kv": voltage_kv,
        "terrain": terrain,
        "cost_breakdown": costs,
        "terrain_segments": segments,
        "total_cost_p10": costs["total_p10"],
        "total_cost_p50": costs["total_p50"],
        "total_cost_p90": costs["total_p90"],
    }


def voltage_options(capacity_mw: float, distance_km: float = 5.0) -> dict[str, Any]:
    """Compare all voltage options for a given capacity with cost implications.

    Parameters
    ----------
    capacity_mw : float
        Project capacity in MW.
    distance_km : float
        Assumed cable distance for cost comparison (default 5km).

    Returns
    -------
    dict with recommended voltage and comparison of all options.
    """
    recommended = _auto_voltage(capacity_mw)
    options = []

    for voltage_kv, vc in sorted(VOLTAGE_COSTS.items()):
        costs = _cost_breakdown(distance_km, voltage_kv, DEFAULT_TERRAIN_MIX)

        # Max capacity guidance per voltage
        max_capacity = {11: 5, 33: 50, 66: 150, 132: 500}
        is_suitable = capacity_mw <= max_capacity.get(voltage_kv, 999)
        is_recommended = voltage_kv == recommended

        options.append({
            "voltage_kv": voltage_kv,
            "recommended": is_recommended,
            "suitable": is_suitable,
            "max_capacity_mw": max_capacity.get(voltage_kv),
            "cable_cost_per_km": vc["cable_per_km"],
            "total_cost_p50": costs["total_p50"],
            "total_cost_p10": costs["total_p10"],
            "total_cost_p90": costs["total_p90"],
            "cost_breakdown": costs,
            "notes": _voltage_notes(voltage_kv, capacity_mw, is_suitable),
        })

    return {
        "capacity_mw": capacity_mw,
        "distance_km": distance_km,
        "recommended_voltage_kv": recommended,
        "options": options,
    }


def _voltage_notes(voltage_kv: int, capacity_mw: float, suitable: bool) -> str:
    """Generate advisory notes for a voltage option."""
    if not suitable:
        return f"{voltage_kv}kV is undersized for {capacity_mw:.0f} MW — thermal limits would be exceeded."

    notes = {
        11: "Lowest cost per km. Suitable for small schemes. Shorter max run lengths (~5 km).",
        33: "Most common UK distribution voltage. Good balance of cost and capacity. Max run ~15 km.",
        66: "Higher capacity corridor. Less common — check DNO preference. Max run ~25 km.",
        132: "Transmission-grade. High cost but high capacity. Typically for >100 MW or long distances.",
    }
    return notes.get(voltage_kv, "")

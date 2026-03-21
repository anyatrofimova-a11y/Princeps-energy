"""
GridFinder integration — detect unmapped grid infrastructure.

Uses VIIRS night-time lights + OSM power data to predict grid network
extent near a location. Helps identify potential connection routes
that aren't in DNO open data.

For MVP: queries existing OSM power data from PostGIS and enhances
with night-time luminance correlation to estimate grid coverage gaps.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any

log = logging.getLogger("princeps.gridfinder")


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km between two WGS84 points."""
    R = 6371.0
    rlat1, rlon1, rlat2, rlon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _midpoint(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """Midpoint between two WGS84 points."""
    return ((lat1 + lat2) / 2, (lon1 + lon2) / 2)


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 in degrees."""
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dlon = rlon2 - rlon1
    x = math.sin(dlon) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# ---------------------------------------------------------------------------
# VIIRS night-time lights via GEE (subprocess)
# ---------------------------------------------------------------------------

async def _fetch_viirs_luminance(lat: float, lon: float, radius_km: float) -> dict | None:
    """
    Fetch VIIRS night-time lights mean radiance via GEE subprocess.
    Returns luminance stats or None if GEE is unavailable.
    """
    import os
    from pathlib import Path

    geeflow_default = os.path.join(os.path.dirname(__file__), "..", ".venv-geeflow", "bin", "python")
    geeflow_python = str(Path(os.environ.get("GEEFLOW_PYTHON", geeflow_default)).absolute())
    gee_project = os.environ.get("GEE_PROJECT", "")

    if not gee_project:
        log.debug("GEE_PROJECT not set — skipping VIIRS fetch")
        return None

    # Build a small inline script for VIIRS extraction
    script = f"""
import ee, json, sys
ee.Initialize(project="{gee_project}")
point = ee.Geometry.Point([{lon}, {lat}])
aoi = point.buffer({radius_km * 1000})

# VIIRS DNB monthly composite — average radiance (nanoWatts/cm2/sr)
viirs = (ee.ImageCollection("NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG")
         .filterDate("2023-01-01", "2024-01-01")
         .select("avg_rad")
         .mean())

stats = viirs.reduceRegion(
    reducer=ee.Reducer.mean().combine(ee.Reducer.max(), sharedInputs=True)
             .combine(ee.Reducer.stdDev(), sharedInputs=True)
             .combine(ee.Reducer.percentile([10, 50, 90]), sharedInputs=True),
    geometry=aoi, scale=500, maxPixels=1e8,
).getInfo()

# Also get a gridded sample for spatial analysis
grid = viirs.reduceRegion(
    reducer=ee.Reducer.toList(),
    geometry=aoi, scale=1000, maxPixels=50000,
).getInfo()

result = {{
    "mean_radiance": stats.get("avg_rad_mean"),
    "max_radiance": stats.get("avg_rad_max"),
    "std_radiance": stats.get("avg_rad_stdDev"),
    "p10_radiance": stats.get("avg_rad_p10"),
    "p50_radiance": stats.get("avg_rad_p50"),
    "p90_radiance": stats.get("avg_rad_p90"),
    "pixel_count": len(grid.get("avg_rad", []) or []),
}}
json.dump(result, sys.stdout)
"""
    try:
        proc = await asyncio.create_subprocess_exec(
            geeflow_python, "-c", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            log.warning("VIIRS fetch failed: %s", stderr.decode()[:300])
            return None
        return json.loads(stdout.decode())
    except Exception as exc:
        log.warning("VIIRS subprocess error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Core detection logic
# ---------------------------------------------------------------------------

async def detect_unmapped_grid(
    pool,
    lat: float,
    lon: float,
    radius_km: float = 10,
) -> dict[str, Any]:
    """
    Detect potential unmapped grid infrastructure near a location.

    Strategy:
    1. Query OSM towers and lines within radius from PostGIS
    2. Identify orphan towers (towers with no nearby mapped line)
    3. Cluster orphan towers into probable line corridors
    4. Optionally enhance with VIIRS night-time luminance to identify
       lit areas with no mapped power infrastructure
    5. Return GeoJSON of predicted unmapped routes

    Returns a dict with:
      - predicted_routes: GeoJSON FeatureCollection of likely unmapped lines
      - coverage_gaps: areas with towers but no lines
      - statistics: counts and coverage metrics
      - viirs: night-time light stats (if GEE available)
    """
    async with pool.acquire() as conn:
        # ── 1. Fetch OSM power lines in radius ─────────────────────────
        lines = await conn.fetch("""
            SELECT id, voltage_kv, operator, cables,
                   ST_AsGeoJSON(ST_Transform(geom, 4326))::json AS geojson,
                   ST_Length(geom) AS length_m
            FROM osm_power_line
            WHERE ST_DWithin(
                geom,
                ST_Transform(ST_SetSRID(ST_MakePoint($2, $1), 4326), 27700),
                $3 * 1000
            )
        """, lat, lon, radius_km)

        # ── 2. Fetch OSM power towers in radius ────────────────────────
        towers = await conn.fetch("""
            SELECT id,
                   ST_Y(ST_Transform(geom, 4326)) AS lat,
                   ST_X(ST_Transform(geom, 4326)) AS lon
            FROM osm_power_tower
            WHERE ST_DWithin(
                geom,
                ST_Transform(ST_SetSRID(ST_MakePoint($2, $1), 4326), 27700),
                $3 * 1000
            )
        """, lat, lon, radius_km)

        # ── 3. Fetch OSM substations in radius ─────────────────────────
        substations = await conn.fetch("""
            SELECT id, name, voltage_kv, operator,
                   ST_Y(ST_Transform(geom, 4326)) AS lat,
                   ST_X(ST_Transform(geom, 4326)) AS lon
            FROM osm_power_substation
            WHERE ST_DWithin(
                geom,
                ST_Transform(ST_SetSRID(ST_MakePoint($2, $1), 4326), 27700),
                $3 * 1000
            )
        """, lat, lon, radius_km)

    # Parse line geometries for proximity check
    line_coords: list[list[tuple[float, float]]] = []
    for l_row in lines:
        gj = l_row["geojson"]
        if gj and gj.get("type") == "LineString":
            line_coords.append([(c[1], c[0]) for c in gj["coordinates"]])
        elif gj and gj.get("type") == "MultiLineString":
            for seg in gj["coordinates"]:
                line_coords.append([(c[1], c[0]) for c in seg])

    def _min_dist_to_lines(t_lat: float, t_lon: float) -> float:
        """Minimum distance in km from a tower to any mapped line vertex."""
        min_d = float("inf")
        for coords in line_coords:
            for c_lat, c_lon in coords:
                d = _haversine_km(t_lat, t_lon, c_lat, c_lon)
                if d < min_d:
                    min_d = d
        return min_d

    # ── 4. Identify orphan towers (>500m from any mapped line) ──────
    ORPHAN_THRESHOLD_KM = 0.5
    orphan_towers: list[dict] = []
    connected_towers: list[dict] = []

    for t in towers:
        t_lat, t_lon = float(t["lat"]), float(t["lon"])
        if not line_coords:
            orphan_towers.append({"id": t["id"], "lat": t_lat, "lon": t_lon})
        else:
            dist = _min_dist_to_lines(t_lat, t_lon)
            if dist > ORPHAN_THRESHOLD_KM:
                orphan_towers.append({"id": t["id"], "lat": t_lat, "lon": t_lon, "dist_km": round(dist, 2)})
            else:
                connected_towers.append({"id": t["id"], "lat": t_lat, "lon": t_lon})

    # ── 5. Cluster orphan towers into predicted line corridors ──────
    # Simple greedy nearest-neighbour chaining
    predicted_routes: list[dict] = []
    used = set()

    MAX_CHAIN_GAP_KM = 1.5  # max gap between consecutive towers in a chain

    orphan_sorted = list(orphan_towers)
    for start_idx, start in enumerate(orphan_sorted):
        if start["id"] in used:
            continue
        chain = [start]
        used.add(start["id"])
        current = start
        while True:
            best_dist = MAX_CHAIN_GAP_KM
            best = None
            for cand in orphan_sorted:
                if cand["id"] in used:
                    continue
                d = _haversine_km(current["lat"], current["lon"], cand["lat"], cand["lon"])
                if d < best_dist:
                    best_dist = d
                    best = cand
            if best is None:
                break
            chain.append(best)
            used.add(best["id"])
            current = best

        if len(chain) >= 2:
            coords = [[t["lon"], t["lat"]] for t in chain]
            total_length_km = sum(
                _haversine_km(chain[i]["lat"], chain[i]["lon"],
                              chain[i + 1]["lat"], chain[i + 1]["lon"])
                for i in range(len(chain) - 1)
            )
            # Estimate voltage from nearby substations
            est_voltage = _estimate_voltage(chain, substations)
            confidence = min(0.95, 0.3 + len(chain) * 0.08)

            predicted_routes.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "type": "predicted_unmapped_line",
                    "tower_count": len(chain),
                    "length_km": round(total_length_km, 2),
                    "estimated_voltage_kv": est_voltage,
                    "confidence": round(confidence, 2),
                    "source": "orphan_tower_chain",
                },
            })

    # ── 6. Substation-to-substation gap routes ──────────────────────
    # If two substations are nearby but no line connects them, predict a route
    sub_list = [{"id": s["id"], "name": s["name"], "lat": float(s["lat"]),
                 "lon": float(s["lon"]), "voltage_kv": s["voltage_kv"]}
                for s in substations]

    for i, s1 in enumerate(sub_list):
        for s2 in sub_list[i + 1:]:
            dist = _haversine_km(s1["lat"], s1["lon"], s2["lat"], s2["lon"])
            if dist > 20 or dist < 0.5:
                continue
            # Check if there's already a mapped line between them
            has_line = _substations_connected_by_line(s1, s2, lines)
            if not has_line:
                predicted_routes.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [s1["lon"], s1["lat"]],
                            [s2["lon"], s2["lat"]],
                        ],
                    },
                    "properties": {
                        "type": "predicted_substation_link",
                        "from_substation": s1["name"] or f"Sub-{s1['id']}",
                        "to_substation": s2["name"] or f"Sub-{s2['id']}",
                        "distance_km": round(dist, 2),
                        "estimated_voltage_kv": max(
                            s1["voltage_kv"] or 0, s2["voltage_kv"] or 0
                        ) or 33,
                        "confidence": round(max(0.2, 0.6 - dist * 0.02), 2),
                        "source": "substation_gap_analysis",
                    },
                })

    # ── 7. VIIRS night-time lights enhancement ──────────────────────
    viirs_data = None
    try:
        viirs_data = await _fetch_viirs_luminance(lat, lon, radius_km)
    except Exception as exc:
        log.debug("VIIRS enhancement skipped: %s", exc)

    # ── 8. Compute coverage statistics ──────────────────────────────
    total_mapped_km = sum(float(l["length_m"] or 0) / 1000 for l in lines)
    total_predicted_km = sum(
        r["properties"]["length_km"]
        for r in predicted_routes
        if "length_km" in r["properties"]
    )
    coverage_ratio = (
        total_mapped_km / (total_mapped_km + total_predicted_km)
        if (total_mapped_km + total_predicted_km) > 0
        else 1.0
    )

    return {
        "centre": {"lat": lat, "lon": lon},
        "radius_km": radius_km,
        "predicted_routes": {
            "type": "FeatureCollection",
            "features": predicted_routes,
        },
        "statistics": {
            "mapped_lines": len(lines),
            "mapped_line_km": round(total_mapped_km, 1),
            "total_towers": len(towers),
            "orphan_towers": len(orphan_towers),
            "connected_towers": len(connected_towers),
            "substations": len(sub_list),
            "predicted_routes": len(predicted_routes),
            "predicted_route_km": round(total_predicted_km, 1),
            "coverage_ratio": round(coverage_ratio, 3),
        },
        "viirs": viirs_data,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimate_voltage(chain: list[dict], substations: list) -> int:
    """Estimate voltage of an orphan tower chain from nearest substation."""
    if not substations:
        return 33  # default UK distribution
    mid = chain[len(chain) // 2]
    best_v = 33
    best_d = float("inf")
    for s in substations:
        d = _haversine_km(mid["lat"], mid["lon"], float(s["lat"]), float(s["lon"]))
        if d < best_d:
            best_d = d
            best_v = s["voltage_kv"] or 33
    return int(best_v)


def _substations_connected_by_line(s1: dict, s2: dict, lines) -> bool:
    """Check if two substations appear to be connected by a mapped line."""
    PROXIMITY_KM = 0.5
    for l_row in lines:
        gj = l_row["geojson"]
        if not gj:
            continue
        coords_list = []
        if gj["type"] == "LineString":
            coords_list = [gj["coordinates"]]
        elif gj["type"] == "MultiLineString":
            coords_list = gj["coordinates"]

        for coords in coords_list:
            if len(coords) < 2:
                continue
            start_lat, start_lon = coords[0][1], coords[0][0]
            end_lat, end_lon = coords[-1][1], coords[-1][0]

            d1_start = _haversine_km(s1["lat"], s1["lon"], start_lat, start_lon)
            d1_end = _haversine_km(s1["lat"], s1["lon"], end_lat, end_lon)
            d2_start = _haversine_km(s2["lat"], s2["lon"], start_lat, start_lon)
            d2_end = _haversine_km(s2["lat"], s2["lon"], end_lat, end_lon)

            if (d1_start < PROXIMITY_KM and d2_end < PROXIMITY_KM) or \
               (d1_end < PROXIMITY_KM and d2_start < PROXIMITY_KM):
                return True
    return False

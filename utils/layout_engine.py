"""Layout Engine — Shapely-based auto-layout for solar, BESS, DC buildings.

Server-side mirror of the frontend Turf.js engine with higher precision.
Called directly from FastAPI endpoints (no subprocess needed — runs in main venv).
"""

from __future__ import annotations

import math
import logging
from typing import Any

from shapely.geometry import shape, mapping, Polygon, MultiPolygon, LineString, box
from shapely.ops import unary_union
from shapely.affinity import translate, rotate as shapely_rotate

log = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────

DEFAULT_SOLAR = {
    "gcr": 0.43,
    "row_pitch": 8,        # metres
    "panel_width": 2.1,
    "panel_length": 1.05,
    "tilt": 25,
    "azimuth": 180,
    "setback_m": 5,
    "watts_per_panel": 550,
}

DEFAULT_BESS = {
    "container_length": 12.2,
    "container_width": 2.44,
    "spacing_x": 3,
    "spacing_y": 4,
    "setback_m": 10,
    "kwh_per_container": 3700,
}

DEFAULT_DC = {
    "building_length": 120,
    "building_width": 60,
    "clearance_m": 15,
    "max_buildings": 4,
    "mw_per_building": 25,
}

# Approximate degrees-to-metres at UK latitudes (~52°N)
DEG_TO_M = 111320
DEG_TO_M_LON = DEG_TO_M * math.cos(math.radians(52))


def _to_shapely(geojson: dict) -> Polygon | MultiPolygon:
    """Convert GeoJSON geometry or Feature to Shapely."""
    if geojson.get("type") == "Feature":
        return shape(geojson["geometry"])
    if geojson.get("type") == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in geojson["features"] if f.get("geometry")]
        return unary_union(geoms) if geoms else Polygon()
    return shape(geojson)


def _to_geojson(geom, properties: dict = None) -> dict:
    """Convert Shapely geometry to GeoJSON Feature."""
    return {"type": "Feature", "geometry": mapping(geom), "properties": properties or {}}


def _safe_buffer(geom, dist_m: float):
    """Buffer in approximate metres (converting to/from degrees)."""
    if not geom or geom.is_empty:
        return geom
    dx = dist_m / DEG_TO_M_LON
    dy = dist_m / DEG_TO_M
    avg = (dx + dy) / 2
    try:
        return geom.buffer(avg)
    except Exception:
        return geom


def _subtract_exclusions(polygon, exclusions: list):
    """Subtract all exclusion geometries from polygon."""
    result = polygon
    for ex in exclusions:
        if ex is None or ex.is_empty:
            continue
        try:
            result = result.difference(ex)
        except Exception:
            pass
        if result.is_empty:
            return None
    return result


# ── Solar Layout ──────────────────────────────────────────────────────────

def generate_solar_layout(boundary_geojson: dict, exclusions: list[dict] = None, profile: dict = None) -> dict:
    """Generate solar panel rows within boundary, respecting exclusions."""
    p = {**DEFAULT_SOLAR, **(profile or {})}
    exclusions = exclusions or []

    boundary = _to_shapely(boundary_geojson)
    ex_geoms = [_to_shapely(e) for e in exclusions if e]

    # Buffer inward
    buffered = _safe_buffer(boundary, -p["setback_m"])
    if not buffered or buffered.is_empty:
        return {"type": "FeatureCollection", "features": [], "stats": {"panels": 0, "capacity_mw": 0, "area_ha": 0}}

    buildable = _subtract_exclusions(buffered, ex_geoms)
    if not buildable or buildable.is_empty:
        return {"type": "FeatureCollection", "features": [], "stats": {"panels": 0, "capacity_mw": 0, "area_ha": 0}}

    # Generate row lines perpendicular to azimuth
    minx, miny, maxx, maxy = buildable.bounds
    pitch_deg = p["row_pitch"] / DEG_TO_M
    row_width_deg = p["panel_width"] / DEG_TO_M
    az_rad = math.radians(p["azimuth"] - 90)

    diag = math.sqrt((maxx - minx) ** 2 + (maxy - miny) ** 2)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    num_rows = int(diag / pitch_deg * 1.5)

    features = []
    panel_count = 0

    for i in range(-num_rows, num_rows + 1):
        offset = i * pitch_deg
        oy = cy + offset * math.cos(az_rad)
        ox = cx + offset * math.sin(az_rad)

        dx = diag * math.cos(az_rad + math.pi / 2)
        dy = diag * math.sin(az_rad + math.pi / 2)

        line = LineString([(ox - dx, oy - dy), (ox + dx, oy + dy)])

        # Buffer line to create row strip
        row_strip = line.buffer(row_width_deg / 2, cap_style=2)
        try:
            clipped = row_strip.intersection(buildable)
        except Exception:
            continue

        if clipped.is_empty or clipped.area < 1e-12:
            continue

        # Count panels from clipped area
        area_m2 = clipped.area * DEG_TO_M * DEG_TO_M_LON
        panels = int(area_m2 / (p["panel_width"] * p["panel_length"]))
        panel_count += panels

        features.append(_to_geojson(clipped, {"featureType": "solar_row", "rowIndex": i, "panels": panels}))

    capacity_mw = round(panel_count * p["watts_per_panel"] / 1e6, 2)
    area_ha = round(buildable.area * DEG_TO_M * DEG_TO_M_LON / 10000, 1)

    return {
        "type": "FeatureCollection",
        "features": features,
        "stats": {"panels": panel_count, "capacity_mw": capacity_mw, "area_ha": area_ha, "rows": len(features)},
    }


# ── BESS Layout ───────────────────────────────────────────────────────────

def generate_bess_layout(boundary_geojson: dict, exclusions: list[dict] = None, profile: dict = None) -> dict:
    """Place BESS containers in a grid within boundary."""
    p = {**DEFAULT_BESS, **(profile or {})}
    exclusions = exclusions or []

    boundary = _to_shapely(boundary_geojson)
    ex_geoms = [_to_shapely(e) for e in exclusions if e]

    buffered = _safe_buffer(boundary, -p["setback_m"])
    if not buffered or buffered.is_empty:
        return {"type": "FeatureCollection", "features": [], "stats": {"containers": 0, "capacity_mwh": 0}}

    buildable = _subtract_exclusions(buffered, ex_geoms)
    if not buildable or buildable.is_empty:
        return {"type": "FeatureCollection", "features": [], "stats": {"containers": 0, "capacity_mwh": 0}}

    minx, miny, maxx, maxy = buildable.bounds
    cl = p["container_length"] / DEG_TO_M_LON
    cw = p["container_width"] / DEG_TO_M
    sx = (p["container_length"] + p["spacing_x"]) / DEG_TO_M_LON
    sy = (p["container_width"] + p["spacing_y"]) / DEG_TO_M

    features = []
    x = minx
    while x + cl <= maxx:
        y = miny
        while y + cw <= maxy:
            container = box(x, y, x + cl, y + cw)
            try:
                inter = container.intersection(buildable)
                if inter.area > container.area * 0.9:
                    features.append(_to_geojson(container, {"featureType": "bess_container", "index": len(features)}))
            except Exception:
                pass
            y += sy
        x += sx

    return {
        "type": "FeatureCollection",
        "features": features,
        "stats": {
            "containers": len(features),
            "capacity_mwh": round(len(features) * p["kwh_per_container"] / 1000, 1),
        },
    }


# ── DC Building Layout ────────────────────────────────────────────────────

def generate_dc_layout(boundary_geojson: dict, exclusions: list[dict] = None, profile: dict = None) -> dict:
    """Place DC building footprints within boundary."""
    p = {**DEFAULT_DC, **(profile or {})}
    exclusions = exclusions or []

    boundary = _to_shapely(boundary_geojson)
    ex_geoms = [_to_shapely(e) for e in exclusions if e]

    buffered = _safe_buffer(boundary, -p["clearance_m"])
    if not buffered or buffered.is_empty:
        return {"type": "FeatureCollection", "features": [], "stats": {"buildings": 0, "total_mw": 0}}

    buildable = _subtract_exclusions(buffered, ex_geoms)
    if not buildable or buildable.is_empty:
        return {"type": "FeatureCollection", "features": [], "stats": {"buildings": 0, "total_mw": 0}}

    minx, miny, maxx, maxy = buildable.bounds
    bl = p["building_length"] / DEG_TO_M_LON
    bw = p["building_width"] / DEG_TO_M
    gl = p["clearance_m"] / DEG_TO_M_LON
    gw = p["clearance_m"] / DEG_TO_M

    features = []
    x = minx
    while x + bl <= maxx and len(features) < p["max_buildings"]:
        y = miny
        while y + bw <= maxy and len(features) < p["max_buildings"]:
            bldg = box(x, y, x + bl, y + bw)
            try:
                inter = bldg.intersection(buildable)
                if inter.area > bldg.area * 0.85:
                    features.append(_to_geojson(bldg, {
                        "featureType": "dc_building",
                        "index": len(features),
                        "mw": p["mw_per_building"],
                        "label": f"DC Hall {len(features) + 1}",
                    }))
            except Exception:
                pass
            y += bw + gw
        x += bl + gl

    return {
        "type": "FeatureCollection",
        "features": features,
        "stats": {"buildings": len(features), "total_mw": len(features) * p["mw_per_building"]},
    }


# ── Buildable Area ────────────────────────────────────────────────────────

def compute_buildable_area(boundary_geojson: dict, constraints: dict = None) -> dict:
    """Compute buildable vs excluded areas given constraint layers."""
    constraints = constraints or {}
    boundary = _to_shapely(boundary_geojson)
    total_ha = round(boundary.area * DEG_TO_M * DEG_TO_M_LON / 10000, 1)

    setbacks = constraints.get("setbacks", {})
    buildable = boundary

    if setbacks.get("boundary"):
        buildable = _safe_buffer(buildable, -setbacks["boundary"])
        if not buildable or buildable.is_empty:
            return {"buildable": None, "excluded": mapping(boundary), "buildable_area_ha": 0, "total_area_ha": total_ha, "buildable_pct": 0}

    for key in ["flood_zones", "heritage", "ecology"]:
        for ex_geojson in constraints.get(key, []):
            if not ex_geojson:
                continue
            ex = _to_shapely(ex_geojson)
            buf = setbacks.get("watercourse", 0) if key == "flood_zones" else setbacks.get(key, 0)
            if buf:
                ex = _safe_buffer(ex, buf)
            try:
                buildable = buildable.difference(ex)
            except Exception:
                pass
            if buildable.is_empty:
                return {"buildable": None, "excluded": mapping(boundary), "buildable_area_ha": 0, "total_area_ha": total_ha, "buildable_pct": 0}

    buildable_ha = round(buildable.area * DEG_TO_M * DEG_TO_M_LON / 10000, 1)
    try:
        excluded = boundary.difference(buildable)
    except Exception:
        excluded = Polygon()

    return {
        "buildable": _to_geojson(buildable),
        "excluded": _to_geojson(excluded),
        "buildable_area_ha": buildable_ha,
        "total_area_ha": total_ha,
        "buildable_pct": round(buildable_ha / total_ha * 100) if total_ha else 0,
    }


# ── Hybrid Layout ─────────────────────────────────────────────────────────

def generate_hybrid_layout(boundary_geojson: dict, exclusions: list[dict] = None, config: dict = None) -> dict:
    """Combined solar + BESS + DC layout with phased allocation."""
    config = config or {}
    exclusions = exclusions or []

    # Phase 1: DC buildings first
    dc_result = generate_dc_layout(boundary_geojson, exclusions, config.get("dc_profile"))
    dc_exclusions = exclusions.copy()
    for f in dc_result["features"]:
        dc_exclusions.append(f["geometry"])

    # Phase 2: BESS near DC
    bess_result = generate_bess_layout(boundary_geojson, dc_exclusions, config.get("bess_profile"))
    bess_exclusions = dc_exclusions.copy()
    for f in bess_result["features"]:
        bess_exclusions.append(f["geometry"])

    # Phase 3: Solar fills remainder
    solar_result = generate_solar_layout(boundary_geojson, bess_exclusions, config.get("solar_profile"))

    all_features = dc_result["features"] + bess_result["features"] + solar_result["features"]

    boundary = _to_shapely(boundary_geojson)
    total_ha = round(boundary.area * DEG_TO_M * DEG_TO_M_LON / 10000, 1)

    return {
        "type": "FeatureCollection",
        "features": all_features,
        "stats": {
            "dc": dc_result["stats"],
            "bess": bess_result["stats"],
            "solar": solar_result["stats"],
            "total_area_ha": total_ha,
        },
    }

"""PV Layout Engine — RatedPower / PVcase-class automated solar layout generator.

Generates optimised utility-scale PV layouts with:
  - Array geometry: row spacing from GCR + winter solstice shading analysis
  - Terrain-aware placement: slope/aspect filtering, flood/building exclusions
  - Block decomposition with access roads every 500 m
  - Infrastructure: inverter stations, combiner boxes, transformers, substation
  - Full BOM and CAPEX/OPEX financial inputs
  - GeoJSON FeatureCollection for map visualisation

Coordinate handling:
  - Input/output in WGS84 (lon, lat)
  - Internal calculations in local metres using cos(lat) scaling

UK-calibrated defaults:
  - Module: 2.1 m x 1.05 m, 580 Wp bifacial (standard utility-scale)
  - Winter solstice min sun altitude ~ 15 deg at 52 deg N
  - GCR: 0.35-0.45 fixed, 0.25-0.35 tracker
  - Access roads 4 m wide every 500 m
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("princeps.pv_layout_engine")


def list_modules() -> list[dict]:
    """Return available PV module specifications."""
    return [
        {"model": "LONGi Hi-MO 7 580W", "watts": 580, "width_m": 1.05, "height_m": 2.1, "technology": "mono-PERC bifacial", "efficiency": 22.5},
        {"model": "JinkoSolar Tiger Neo 585W", "watts": 585, "width_m": 1.05, "height_m": 2.12, "technology": "n-type TOPCon", "efficiency": 22.8},
        {"model": "Trina Vertex S+ 445W", "watts": 445, "width_m": 1.04, "height_m": 1.76, "technology": "mono-PERC", "efficiency": 21.8},
        {"model": "Canadian Solar HiKu7 670W", "watts": 670, "width_m": 1.13, "height_m": 2.38, "technology": "n-type TOPCon bifacial", "efficiency": 22.5},
        {"model": "First Solar Series 7 540W", "watts": 540, "width_m": 1.20, "height_m": 2.01, "technology": "CdTe thin-film", "efficiency": 22.1},
    ]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Standard utility-scale bifacial module
DEFAULT_MODULE = {
    "model": "Generic 580W Bifacial",
    "manufacturer": "Utility-Scale",
    "watts": 580,
    "width_m": 1.05,     # east-west (landscape)
    "height_m": 2.10,    # north-south (along tilt)
    "efficiency_pct": 22.0,
    "bifacial": True,
    "weight_kg": 28.5,
    "voc_v": 49.5,
    "isc_a": 14.8,
}

# GCR ranges by technology
GCR_RANGES = {
    "fixed_tilt": (0.35, 0.45),
    "single_axis_tracker": (0.25, 0.35),
}

# Infrastructure sizing constants
MW_PER_INVERTER_STATION = 5.0      # 1 inverter station per 5 MW
MW_PER_COMBINER = 1.0              # 1 combiner box per 1 MW
MW_PER_TRANSFORMER = 10.0          # 1 transformer per 10 MW
ACCESS_ROAD_WIDTH_M = 4.0          # UK standard site road
ACCESS_ROAD_INTERVAL_M = 500.0     # Road every 500 m

# Slope/aspect exclusion defaults
MAX_SLOPE_DEG = 15.0
NORTH_FACING_MIN = 315.0           # Aspect 315-45 = north-facing
NORTH_FACING_MAX = 45.0
BUILDING_BUFFER_M = 50.0

# UK cost benchmarks (GBP, 2024-2025)
COST_BENCHMARKS = {
    "module_per_wp": 0.22,          # GBP/Wp
    "inverter_per_kw": 40.0,        # GBP/kW
    "mounting_per_kw": 55.0,        # GBP/kW (fixed tilt)
    "mounting_tracker_per_kw": 85.0,  # GBP/kW (single-axis tracker)
    "transformer_per_kva": 25.0,    # GBP/kVA
    "dc_cable_per_m": 3.50,         # GBP/m
    "ac_cable_per_m": 12.0,         # GBP/m
    "access_road_per_m2": 35.0,     # GBP/m2 (Type 1 aggregate)
    "fencing_per_m": 45.0,          # GBP/m (2.4m deer fence + CCTV)
    "epc_margin_pct": 0.10,         # 10% EPC margin
    "contingency_pct": 0.05,        # 5% contingency
    "dev_costs_per_kw": 30.0,       # GBP/kW (planning, legal, grid app)
    "opex_per_kw_yr": 10.0,         # GBP/kW/yr (O&M, insurance, land rent)
}


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _deg2rad(d: float) -> float:
    return d * math.pi / 180.0


def _rad2deg(r: float) -> float:
    return r * 180.0 / math.pi


def _metres_per_deg(lat: float) -> tuple[float, float]:
    """Return (m_per_deg_lon, m_per_deg_lat) at given latitude."""
    lat_rad = _deg2rad(lat)
    m_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
    m_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    return m_lon, m_lat


def _to_local(lon: float, lat: float, o_lon: float, o_lat: float,
              m_lon: float, m_lat: float) -> tuple[float, float]:
    return (lon - o_lon) * m_lon, (lat - o_lat) * m_lat


def _to_wgs84(x: float, y: float, o_lon: float, o_lat: float,
              m_lon: float, m_lat: float) -> tuple[float, float]:
    return o_lon + x / m_lon, o_lat + y / m_lat


def _polygon_area_m2(pts: list[tuple[float, float]]) -> float:
    """Shoelace formula — absolute area in local m2."""
    n = len(pts)
    area = 0.0
    j = n - 1
    for i in range(n):
        area += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1])
        j = i
    return abs(area) / 2.0


def _polygon_perimeter(pts: list[tuple[float, float]]) -> float:
    """Perimeter in local metres."""
    n = len(pts)
    perim = 0.0
    for i in range(n):
        j = (i + 1) % n
        perim += math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1])
    return perim


def _polygon_centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    """Centroid of a polygon in local coords."""
    n = len(pts)
    if n == 0:
        return (0.0, 0.0)
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    return cx, cy


def _point_in_polygon(px: float, py: float, poly: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _offset_polygon(pts: list[tuple[float, float]], dist: float) -> list[tuple[float, float]]:
    """Inward-offset (shrink) a polygon by dist metres."""
    n = len(pts)
    if n < 3:
        return pts
    closed = list(pts)
    if closed[0] != closed[-1]:
        closed.append(closed[0])
        n = len(closed)

    def _build_edges(sign: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        edges = []
        for i in range(n - 1):
            x1, y1 = closed[i]
            x2, y2 = closed[i + 1]
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            nx = sign * dy / length
            ny = sign * (-dx) / length
            edges.append((
                (x1 + nx * dist, y1 + ny * dist),
                (x2 + nx * dist, y2 + ny * dist),
            ))
        return edges

    edges = _build_edges(1.0)
    if len(edges) < 3:
        return pts
    test = edges[0][0]
    if not _point_in_polygon(test[0], test[1], pts):
        edges = _build_edges(-1.0)

    result: list[tuple[float, float]] = []
    ne = len(edges)
    for i in range(ne):
        j = (i + 1) % ne
        pt = _line_intersect(edges[i][0], edges[i][1], edges[j][0], edges[j][1])
        result.append(pt if pt else edges[i][1])
    return result


def _line_intersect(p1: tuple[float, float], p2: tuple[float, float],
                    p3: tuple[float, float], p4: tuple[float, float],
                    ) -> tuple[float, float] | None:
    x1, y1 = p1; x2, y2 = p2
    x3, y3 = p3; x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def _clip_line_to_polygon(
    x1: float, y: float, x2: float,
    poly: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Clip horizontal line segment [x1,x2] at height y to polygon.
    Returns list of (xa, xb) intervals inside the polygon.
    """
    dx = x2 - x1
    if abs(dx) < 1e-9:
        return []
    t_vals: list[float] = [0.0, 1.0]
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        ex1, ey1 = poly[i]
        ex2, ey2 = poly[j]
        edy = ey2 - ey1
        edx = ex2 - ex1
        if abs(edy) < 1e-12:
            continue
        s = (y - ey1) / edy
        if s < 0 or s > 1:
            continue
        x_int = ex1 + s * edx
        t = (x_int - x1) / dx
        if 0.0 <= t <= 1.0:
            t_vals.append(t)

    t_vals.sort()
    segments: list[tuple[float, float]] = []
    for i in range(len(t_vals) - 1):
        ta, tb = t_vals[i], t_vals[i + 1]
        if tb - ta < 1e-9:
            continue
        mx = x1 + (ta + tb) / 2.0 * dx
        if _point_in_polygon(mx, y, poly):
            xa = x1 + ta * dx
            xb = x1 + tb * dx
            if segments and abs(segments[-1][1] - xa) < 1e-6:
                segments[-1] = (segments[-1][0], xb)
            else:
                segments.append((xa, xb))
    return segments


def _bbox_from_area(lat: float, lon: float, area_ha: float) -> list[list[float]]:
    """Create a rectangular boundary from centre point and area in hectares.
    Assumes ~1.5:1 aspect ratio (typical site shape).
    """
    area_m2 = area_ha * 10_000
    # width:depth = 1.5:1 => width = sqrt(1.5 * area), depth = sqrt(area/1.5)
    width_m = math.sqrt(1.5 * area_m2)
    depth_m = area_m2 / width_m
    m_lon, m_lat = _metres_per_deg(lat)
    half_w = (width_m / 2.0) / m_lon
    half_d = (depth_m / 2.0) / m_lat
    return [
        [lon - half_w, lat - half_d],
        [lon + half_w, lat - half_d],
        [lon + half_w, lat + half_d],
        [lon - half_w, lat + half_d],
    ]


# ---------------------------------------------------------------------------
# Sun position / row spacing
# ---------------------------------------------------------------------------

def _min_solar_altitude(latitude_deg: float) -> float:
    """Minimum noon solar altitude on winter solstice (Dec 21).
    altitude = 90 - latitude + declination;  winter declination = -23.45 deg.
    """
    return 90.0 - abs(latitude_deg) - 23.45


def _optimal_row_spacing(
    panel_height_m: float,
    tilt_deg: float,
    latitude_deg: float,
    min_gap_m: float = 2.0,
) -> float:
    """Calculate row pitch to avoid inter-row shading at winter solstice.

    pitch = shadow_length + ground_projection
    shadow_length = panel_height * sin(tilt) / tan(min_sun_alt)
    """
    min_sun_alt = _min_solar_altitude(abs(latitude_deg))
    tilt_rad = _deg2rad(tilt_deg)
    sun_alt_rad = _deg2rad(max(min_sun_alt, 5.0))

    shadow_length = panel_height_m * math.sin(tilt_rad) / math.tan(sun_alt_rad)
    ground_proj = panel_height_m * math.cos(tilt_rad)
    pitch = shadow_length + ground_proj

    gap = pitch - ground_proj
    if gap < min_gap_m:
        pitch = ground_proj + min_gap_m

    return pitch


def _optimal_tilt(latitude_deg: float) -> float:
    """Optimal fixed tilt = ~0.7 * latitude for annual energy maximisation."""
    return round(0.7 * abs(latitude_deg), 1)


# ---------------------------------------------------------------------------
# Terrain / constraint filtering
# ---------------------------------------------------------------------------

@dataclass
class ExclusionZone:
    """An area to exclude from panel placement."""
    polygon_local: list[tuple[float, float]]
    reason: str


def _build_exclusion_zones(
    *,
    constraints: dict[str, Any] | None,
    avg_lon: float,
    avg_lat: float,
    m_lon: float,
    m_lat: float,
) -> list[ExclusionZone]:
    """Convert constraint data into local-coordinate exclusion polygons."""
    zones: list[ExclusionZone] = []
    if not constraints:
        return zones

    for key in ("buildings", "flood_zones", "trees", "exclusions"):
        items = constraints.get(key, [])
        if not items:
            continue
        reason = key.replace("_", " ")
        for item in items:
            coords = item if isinstance(item, list) else item.get("coordinates", [])
            if not coords or len(coords) < 3:
                continue
            local_pts = [
                _to_local(c[0], c[1], avg_lon, avg_lat, m_lon, m_lat)
                for c in coords
            ]
            # Apply buffer for buildings
            if key == "buildings" and BUILDING_BUFFER_M > 0:
                local_pts = _offset_polygon(local_pts, -BUILDING_BUFFER_M)
            zones.append(ExclusionZone(polygon_local=local_pts, reason=reason))

    return zones


def _point_excluded(
    x: float, y: float,
    exclusions: list[ExclusionZone],
) -> bool:
    """Check if a point falls within any exclusion zone."""
    for ez in exclusions:
        if _point_in_polygon(x, y, ez.polygon_local):
            return True
    return False


# ---------------------------------------------------------------------------
# Block decomposition
# ---------------------------------------------------------------------------

@dataclass
class Block:
    """A rectangular sub-area of the site separated by access roads."""
    id: str
    y_start: float          # local y of first row centre
    y_end: float            # local y of last row centre
    rows: list[dict] = field(default_factory=list)
    centre_x: float = 0.0
    centre_y: float = 0.0


def _decompose_into_blocks(
    min_y: float,
    max_y: float,
    row_pitch: float,
    ground_proj: float,
    road_interval_m: float = ACCESS_ROAD_INTERVAL_M,
    road_width_m: float = ACCESS_ROAD_WIDTH_M,
) -> list[Block]:
    """Split the site's y-extent into blocks separated by access roads."""
    blocks: list[Block] = []
    block_idx = 0
    y = min_y + ground_proj / 2.0
    block_start = y
    dist_since_road = 0.0

    while y <= max_y - ground_proj / 2.0:
        dist_since_road += row_pitch
        if dist_since_road >= road_interval_m and y + road_width_m + row_pitch < max_y:
            # End current block, insert road
            blocks.append(Block(
                id=f"BLK-{block_idx + 1:02d}",
                y_start=block_start,
                y_end=y,
            ))
            block_idx += 1
            y += road_width_m
            block_start = y + row_pitch
            dist_since_road = 0.0

        y += row_pitch

    # Final block
    blocks.append(Block(
        id=f"BLK-{block_idx + 1:02d}",
        y_start=block_start,
        y_end=y - row_pitch,  # last valid row position
    ))

    return blocks


# ---------------------------------------------------------------------------
# Specific yield estimation
# ---------------------------------------------------------------------------

def _estimate_specific_yield(lat: float, tilt_deg: float, technology: str) -> float:
    """Estimate annual specific yield (kWh/kWp) for UK/Northern Europe."""
    if abs(lat) < 35:
        base = 1450
    elif abs(lat) < 45:
        base = 1250
    elif abs(lat) < 50:
        base = 1100
    elif abs(lat) < 55:
        base = 1020
    elif abs(lat) < 60:
        base = 950
    else:
        base = 850

    optimal_tilt = 0.7 * abs(lat)
    tilt_diff = abs(tilt_deg - optimal_tilt)
    if tilt_diff > 10:
        base *= (1.0 - 0.003 * tilt_diff)

    # Tracker bonus: +15-20% yield vs fixed
    if technology == "single_axis_tracker":
        base *= 1.17

    return base


# ---------------------------------------------------------------------------
# Dominant aspect calculation
# ---------------------------------------------------------------------------

def _compute_dominant_aspect(
    terrain: dict[str, Any] | None,
) -> float:
    """Return the dominant south-facing aspect in degrees for array rotation.
    180 = due south, 0 = no rotation needed.
    """
    if not terrain:
        return 180.0
    aspects = terrain.get("aspect_samples", [])
    if not aspects:
        return terrain.get("dominant_aspect", 180.0)
    # Filter to south-facing (90-270 deg) and find mean
    south_aspects = [a for a in aspects if 90 <= a <= 270]
    if south_aspects:
        return sum(south_aspects) / len(south_aspects)
    return 180.0


# ---------------------------------------------------------------------------
# Main layout engine
# ---------------------------------------------------------------------------

def generate_pv_layout(
    lat: float,
    lon: float,
    capacity_mw: float,
    *,
    area_ha: float | None = None,
    boundary_coords: list[list[float]] | None = None,
    technology: str = "fixed_tilt",
    tilt_deg: float | None = None,
    gcr_target: float | None = None,
    module_watts: int = 580,
    module_width_m: float = 1.05,
    module_height_m: float = 2.10,
    setback_m: float = 10.0,
    terrain: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
    grid_connection_point: list[float] | None = None,
    dc_ac_ratio: float = 1.25,
    modules_per_string: int = 28,
) -> dict[str, Any]:
    """Generate an optimised PV layout for a utility-scale solar site.

    Parameters
    ----------
    lat : float
        Site centre latitude (WGS84).
    lon : float
        Site centre longitude (WGS84).
    capacity_mw : float
        Target DC capacity in MW.
    area_ha : float, optional
        Site area in hectares (auto-generates rectangular boundary if no boundary_coords).
    boundary_coords : [[lon, lat], ...], optional
        Polygon ring defining the site boundary in WGS84.
    technology : str
        'fixed_tilt' or 'single_axis_tracker'.
    tilt_deg : float, optional
        Panel tilt angle (None = auto from latitude: 0.7 * lat).
    gcr_target : float, optional
        Ground coverage ratio (None = midpoint of range for technology).
    module_watts : int
        Module rated power in Wp.
    module_width_m : float
        Module width (east-west) in metres.
    module_height_m : float
        Module height (north-south, along tilt) in metres.
    setback_m : float
        Boundary setback in metres.
    terrain : dict, optional
        Terrain data with 'slope_mean', 'aspect_samples', etc.
    constraints : dict, optional
        Constraint polygons: buildings, flood_zones, trees, exclusions.
    grid_connection_point : [lon, lat], optional
        Nearest grid connection for substation placement.
    dc_ac_ratio : float
        Target DC/AC ratio for inverter sizing.
    modules_per_string : int
        Modules per electrical string.

    Returns
    -------
    dict
        Complete layout with arrays, infrastructure, BOM, financial inputs.
    """
    # Validate technology
    if technology not in GCR_RANGES:
        raise ValueError(f"technology must be one of: {', '.join(GCR_RANGES.keys())}")

    # ── Resolve site boundary ──────────────────────────────────────
    if boundary_coords is not None and len(boundary_coords) >= 3:
        coords = boundary_coords
    elif area_ha is not None and area_ha > 0:
        coords = _bbox_from_area(lat, lon, area_ha)
    else:
        # Auto-size from capacity: ~2 ha/MW for fixed tilt, ~2.5 ha/MW for tracker
        ha_per_mw = 2.5 if technology == "single_axis_tracker" else 2.0
        auto_area = capacity_mw * ha_per_mw
        coords = _bbox_from_area(lat, lon, auto_area)
        area_ha = auto_area

    if len(coords) < 3:
        raise ValueError("Boundary must have at least 3 vertices")

    # ── Coordinate system ──────────────────────────────────────────
    avg_lat = sum(c[1] for c in coords) / len(coords)
    avg_lon = sum(c[0] for c in coords) / len(coords)
    m_lon, m_lat = _metres_per_deg(avg_lat)

    boundary_local = [_to_local(c[0], c[1], avg_lon, avg_lat, m_lon, m_lat) for c in coords]
    if boundary_local[0] != boundary_local[-1]:
        boundary_local.append(boundary_local[0])

    site_area_m2 = _polygon_area_m2(boundary_local[:-1])
    site_area_ha = site_area_m2 / 10_000.0
    site_perimeter_m = _polygon_perimeter(boundary_local[:-1])

    # ── Tilt and GCR ───────────────────────────────────────────────
    if tilt_deg is None:
        tilt_deg = _optimal_tilt(avg_lat)
        if technology == "single_axis_tracker":
            tilt_deg = 0.0  # Trackers have 0 deg static tilt (tracking handles it)

    if gcr_target is None:
        gcr_lo, gcr_hi = GCR_RANGES[technology]
        gcr_target = (gcr_lo + gcr_hi) / 2.0

    # ── Row spacing ────────────────────────────────────────────────
    effective_tilt = tilt_deg if technology == "fixed_tilt" else 25.0  # tracker max angle
    row_pitch = _optimal_row_spacing(module_height_m, effective_tilt, abs(avg_lat))

    tilt_rad = _deg2rad(effective_tilt)
    ground_proj = module_height_m * math.cos(tilt_rad)

    # Adjust pitch to hit GCR target (never denser than shading-free pitch)
    pitch_from_gcr = ground_proj / gcr_target
    row_pitch = max(row_pitch, pitch_from_gcr)
    gcr_actual = ground_proj / row_pitch

    # ── Apply setback ──────────────────────────────────────────────
    if setback_m > 0:
        usable = _offset_polygon(boundary_local[:-1], setback_m)
    else:
        usable = boundary_local[:-1]

    if len(usable) < 3:
        return _empty_result(site_area_ha, tilt_deg, technology)

    usable_area_m2 = _polygon_area_m2(usable)

    # ── Build exclusion zones ──────────────────────────────────────
    exclusions = _build_exclusion_zones(
        constraints=constraints,
        avg_lon=avg_lon, avg_lat=avg_lat,
        m_lon=m_lon, m_lat=m_lat,
    )

    # ── Terrain filtering setup ────────────────────────────────────
    slope_mean = terrain.get("slope_mean", 0) if terrain else 0
    terrain_excluded_pct = 0.0
    if terrain:
        # Estimate fraction excluded by slope/aspect
        slope_p90 = terrain.get("slope_p90", slope_mean)
        north_pct = terrain.get("north_facing_pct", 0)
        steep_pct = max(0, min(100, (slope_p90 - MAX_SLOPE_DEG) * 5)) if slope_p90 > MAX_SLOPE_DEG else 0
        terrain_excluded_pct = min(80, steep_pct + north_pct)

    # ── Dominant aspect for rotation ───────────────────────────────
    dominant_aspect = _compute_dominant_aspect(terrain)
    rotation_deg = round(dominant_aspect - 180.0, 1)  # 0 = due south

    # ── Block decomposition ────────────────────────────────────────
    xs = [p[0] for p in usable]
    ys = [p[1] for p in usable]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    blocks = _decompose_into_blocks(
        min_y, max_y, row_pitch, ground_proj,
        road_interval_m=ACCESS_ROAD_INTERVAL_M,
        road_width_m=ACCESS_ROAD_WIDTH_M,
    )

    # ── Place rows within blocks ───────────────────────────────────
    all_rows: list[dict[str, Any]] = []
    row_index = 0
    total_modules = 0
    target_modules = int(capacity_mw * 1_000_000 / module_watts)

    for block in blocks:
        y = block.y_start
        block_rows: list[dict[str, Any]] = []

        while y <= block.y_end:
            if total_modules >= target_modules:
                break

            segments = _clip_line_to_polygon(min_x, y, max_x, usable)

            for seg_xa, seg_xb in segments:
                if total_modules >= target_modules:
                    break

                # Check exclusion zones at segment midpoint
                seg_mid_x = (seg_xa + seg_xb) / 2.0
                if _point_excluded(seg_mid_x, y, exclusions):
                    continue

                seg_length = seg_xb - seg_xa
                n_modules = int(seg_length / module_width_m)
                if n_modules < 1:
                    continue

                # Cap modules if we'd exceed target
                remaining = target_modules - total_modules
                n_modules = min(n_modules, remaining)

                row_length = n_modules * module_width_m
                x_start = seg_xa + (seg_length - row_length) / 2.0
                x_end = x_start + row_length
                cx_local = (x_start + x_end) / 2.0

                row_lon, row_lat = _to_wgs84(cx_local, y, avg_lon, avg_lat, m_lon, m_lat)

                row_data = {
                    "id": f"R{row_index + 1:04d}",
                    "block_id": block.id,
                    "lat": round(row_lat, 7),
                    "lon": round(row_lon, 7),
                    "modules": n_modules,
                    "row_index": row_index,
                    "x_start": x_start,
                    "x_end": x_end,
                    "y_local": y,
                }
                block_rows.append(row_data)
                all_rows.append(row_data)
                total_modules += n_modules
                row_index += 1

            y += row_pitch

        # Compute block centre
        if block_rows:
            block.centre_x = sum(
                (r["x_start"] + r["x_end"]) / 2.0 for r in block_rows
            ) / len(block_rows)
            block.centre_y = sum(r["y_local"] for r in block_rows) / len(block_rows)
        block.rows = block_rows

    if total_modules == 0:
        return _empty_result(site_area_ha, tilt_deg, technology)

    # ── Capacity calculations ──────────────────────────────────────
    capacity_kwp = total_modules * module_watts / 1000.0
    capacity_mwp = capacity_kwp / 1000.0

    # ── Build arrays output (per block) ────────────────────────────
    arrays: list[dict[str, Any]] = []
    for block in blocks:
        if not block.rows:
            continue
        block_lon, block_lat = _to_wgs84(
            block.centre_x, block.centre_y, avg_lon, avg_lat, m_lon, m_lat
        )
        arrays.append({
            "block_id": block.id,
            "rows": len(block.rows),
            "modules_per_row": round(
                sum(r["modules"] for r in block.rows) / max(1, len(block.rows))
            ),
            "lat": round(block_lat, 7),
            "lon": round(block_lon, 7),
            "rotation_deg": rotation_deg,
        })

    # ── Infrastructure placement ───────────────────────────────────

    # Inverter stations: 1 per 5 MW, placed centrally in each block
    n_inverter_stations = max(1, math.ceil(capacity_mwp / MW_PER_INVERTER_STATION))
    inverter_capacity_kw = round(capacity_kwp / n_inverter_stations / dc_ac_ratio, 1)
    inverter_stations: list[dict[str, Any]] = []

    # Distribute inverter stations across blocks proportionally
    blocks_with_rows = [b for b in blocks if b.rows]
    inv_per_block = max(1, n_inverter_stations // max(1, len(blocks_with_rows)))
    inv_idx = 0

    for block in blocks_with_rows:
        n_inv_this_block = min(inv_per_block, n_inverter_stations - inv_idx)
        if n_inv_this_block <= 0:
            break

        for j in range(n_inv_this_block):
            # Place at block centre, slightly offset
            offset_x = (j - n_inv_this_block / 2.0) * 30.0
            inv_x = block.centre_x + offset_x
            inv_y = block.centre_y
            inv_lon, inv_lat = _to_wgs84(inv_x, inv_y, avg_lon, avg_lat, m_lon, m_lat)

            inverter_stations.append({
                "id": f"INV-{inv_idx + 1:02d}",
                "capacity_kw": inverter_capacity_kw,
                "lat": round(inv_lat, 7),
                "lon": round(inv_lon, 7),
                "block_id": block.id,
            })
            inv_idx += 1

    # Fill remaining inverters in last block
    while inv_idx < n_inverter_stations and blocks_with_rows:
        block = blocks_with_rows[-1]
        offset_x = (inv_idx - n_inverter_stations / 2.0) * 30.0
        inv_x = block.centre_x + offset_x
        inv_y = block.centre_y + 20.0
        inv_lon, inv_lat = _to_wgs84(inv_x, inv_y, avg_lon, avg_lat, m_lon, m_lat)
        inverter_stations.append({
            "id": f"INV-{inv_idx + 1:02d}",
            "capacity_kw": inverter_capacity_kw,
            "lat": round(inv_lat, 7),
            "lon": round(inv_lon, 7),
            "block_id": block.id,
        })
        inv_idx += 1

    # Combiner boxes: 1 per 1 MW, distributed along rows
    n_combiners = max(1, math.ceil(capacity_mwp / MW_PER_COMBINER))

    # Transformers: 1 per 10 MW, at edge near grid connection
    n_transformers = max(1, math.ceil(capacity_mwp / MW_PER_TRANSFORMER))
    transformer_kva = round(capacity_kwp / n_transformers, 0)
    # Voltage: <5 MW = 11 kV, 5-50 MW = 33 kV, >50 MW = 132 kV
    if capacity_mwp <= 5:
        tx_voltage_kv = 11
    elif capacity_mwp <= 50:
        tx_voltage_kv = 33
    else:
        tx_voltage_kv = 132

    transformers: list[dict[str, Any]] = []
    for ti in range(n_transformers):
        # Place transformers at site edge (south side)
        tx_x = min_x + (ti + 0.5) * (max_x - min_x) / n_transformers
        tx_y = min_y + setback_m / 2.0  # near southern edge
        tx_lon, tx_lat = _to_wgs84(tx_x, tx_y, avg_lon, avg_lat, m_lon, m_lat)
        transformers.append({
            "id": f"TX-{ti + 1:02d}",
            "voltage_kv": tx_voltage_kv,
            "capacity_kva": transformer_kva,
            "lat": round(tx_lat, 7),
            "lon": round(tx_lon, 7),
        })

    # Substation: 1, at site perimeter nearest to grid connection
    if grid_connection_point:
        gc_x, gc_y = _to_local(
            grid_connection_point[0], grid_connection_point[1],
            avg_lon, avg_lat, m_lon, m_lat,
        )
        # Find nearest boundary point
        best_dist = float("inf")
        sub_x, sub_y = min_x, min_y
        for pt in boundary_local[:-1]:
            d = math.hypot(pt[0] - gc_x, pt[1] - gc_y)
            if d < best_dist:
                best_dist = d
                sub_x, sub_y = pt
    else:
        # Default: south-west corner
        sub_x = min_x + setback_m
        sub_y = min_y + setback_m

    sub_lon, sub_lat = _to_wgs84(sub_x, sub_y, avg_lon, avg_lat, m_lon, m_lat)
    substation = {
        "id": "SUB-01",
        "voltage_kv": tx_voltage_kv,
        "lat": round(sub_lat, 7),
        "lon": round(sub_lon, 7),
    }

    # ── Access roads ───────────────────────────────────────────────
    access_roads: list[dict[str, Any]] = []

    # Horizontal roads between blocks
    for i in range(len(blocks) - 1):
        if not blocks[i].rows or not blocks[i + 1].rows:
            continue
        road_y = (blocks[i].y_end + blocks[i + 1].y_start) / 2.0
        segs = _clip_line_to_polygon(min_x, road_y, max_x, usable)
        for xa, xb in segs:
            p1_lon, p1_lat = _to_wgs84(xa, road_y, avg_lon, avg_lat, m_lon, m_lat)
            p2_lon, p2_lat = _to_wgs84(xb, road_y, avg_lon, avg_lat, m_lon, m_lat)
            road_length = xb - xa
            access_roads.append({
                "from": [round(p1_lat, 7), round(p1_lon, 7)],
                "to": [round(p2_lat, 7), round(p2_lon, 7)],
                "length_m": round(road_length, 1),
            })

    # Roads connecting inverter stations to nearest transformer
    for inv in inverter_stations:
        inv_x_local, inv_y_local = _to_local(
            inv["lon"], inv["lat"], avg_lon, avg_lat, m_lon, m_lat
        )
        nearest_tx = min(
            transformers,
            key=lambda t: math.hypot(
                _to_local(t["lon"], t["lat"], avg_lon, avg_lat, m_lon, m_lat)[0] - inv_x_local,
                _to_local(t["lon"], t["lat"], avg_lon, avg_lat, m_lon, m_lat)[1] - inv_y_local,
            ),
        )
        tx_x, tx_y = _to_local(
            nearest_tx["lon"], nearest_tx["lat"], avg_lon, avg_lat, m_lon, m_lat
        )
        road_len = math.hypot(inv_x_local - tx_x, inv_y_local - tx_y)
        if road_len > 5:
            access_roads.append({
                "from": [inv["lat"], inv["lon"]],
                "to": [nearest_tx["lat"], nearest_tx["lon"]],
                "length_m": round(road_len, 1),
            })

    # Road from first transformer to substation
    if transformers:
        tx0 = transformers[0]
        road_len = math.hypot(
            _to_local(tx0["lon"], tx0["lat"], avg_lon, avg_lat, m_lon, m_lat)[0] - sub_x,
            _to_local(tx0["lon"], tx0["lat"], avg_lon, avg_lat, m_lon, m_lat)[1] - sub_y,
        )
        if road_len > 5:
            access_roads.append({
                "from": [tx0["lat"], tx0["lon"]],
                "to": [substation["lat"], substation["lon"]],
                "length_m": round(road_len, 1),
            })

    total_road_length_m = sum(r["length_m"] for r in access_roads)

    # ── GeoJSON ────────────────────────────────────────────────────
    features: list[dict[str, Any]] = []
    half_ground = ground_proj / 2.0

    for row in all_rows:
        rect_local = [
            (row["x_start"], row["y_local"] - half_ground),
            (row["x_end"], row["y_local"] - half_ground),
            (row["x_end"], row["y_local"] + half_ground),
            (row["x_start"], row["y_local"] + half_ground),
            (row["x_start"], row["y_local"] - half_ground),
        ]
        rect_wgs = [
            [round(_to_wgs84(px, py, avg_lon, avg_lat, m_lon, m_lat)[0], 7),
             round(_to_wgs84(px, py, avg_lon, avg_lat, m_lon, m_lat)[1], 7)]
            for px, py in rect_local
        ]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [rect_wgs]},
            "properties": {
                "type": "panel_row",
                "row_id": row["id"],
                "block_id": row["block_id"],
                "modules": row["modules"],
                "tilt_deg": tilt_deg,
                "rotation_deg": rotation_deg,
            },
        })

    # Infrastructure as point features
    for inv in inverter_stations:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [inv["lon"], inv["lat"]]},
            "properties": {"type": "inverter_station", **inv},
        })
    for tx in transformers:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [tx["lon"], tx["lat"]]},
            "properties": {"type": "transformer", **tx},
        })
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [substation["lon"], substation["lat"]]},
        "properties": {"type": "substation", **substation},
    })

    # Access roads as LineStrings
    for road in access_roads:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [road["from"][1], road["from"][0]],
                    [road["to"][1], road["to"][0]],
                ],
            },
            "properties": {
                "type": "access_road",
                "width_m": ACCESS_ROAD_WIDTH_M,
                "length_m": road["length_m"],
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}

    # ── BOM ─────────────────────────────────────────────────────────
    dc_cable_m = round(total_modules * 2.5, 1)   # ~2.5 m per module average
    ac_cable_m = round(n_inverter_stations * 150 + n_transformers * 200, 1)
    mounting_structures = math.ceil(total_modules / 4)  # 4 modules per table
    fencing_m = round(site_perimeter_m, 1)

    bom = {
        "modules": {
            "count": total_modules,
            "model": f"{module_watts}W Bifacial",
            "total_kwp": round(capacity_kwp, 2),
        },
        "inverters": {
            "count": n_inverter_stations,
            "model": f"Central {round(inverter_capacity_kw)}kW",
            "capacity_kw": round(inverter_capacity_kw * n_inverter_stations, 1),
        },
        "transformers": {
            "count": n_transformers,
            "voltage_kv": tx_voltage_kv,
        },
        "combiner_boxes": n_combiners,
        "dc_cable_m": dc_cable_m,
        "ac_cable_m": ac_cable_m,
        "mounting_structures": mounting_structures,
        "fencing_m": fencing_m,
    }

    # ── Financial inputs ───────────────────────────────────────────
    cost = COST_BENCHMARKS
    is_tracker = technology == "single_axis_tracker"
    mounting_rate = cost["mounting_tracker_per_kw"] if is_tracker else cost["mounting_per_kw"]

    module_cost = total_modules * module_watts * cost["module_per_wp"] / 1000  # GBP (k)
    inverter_cost = capacity_kwp * cost["inverter_per_kw"]
    mounting_cost = capacity_kwp * mounting_rate
    transformer_cost = n_transformers * transformer_kva * cost["transformer_per_kva"]
    dc_cable_cost = dc_cable_m * cost["dc_cable_per_m"]
    ac_cable_cost = ac_cable_m * cost["ac_cable_per_m"]
    road_cost = total_road_length_m * ACCESS_ROAD_WIDTH_M * cost["access_road_per_m2"]
    fence_cost = fencing_m * cost["fencing_per_m"]
    dev_cost = capacity_kwp * cost["dev_costs_per_kw"]

    subtotal = (module_cost + inverter_cost + mounting_cost + transformer_cost
                + dc_cable_cost + ac_cable_cost + road_cost + fence_cost + dev_cost)
    epc_margin = subtotal * cost["epc_margin_pct"]
    contingency = subtotal * cost["contingency_pct"]
    capex_total = round(subtotal + epc_margin + contingency, 0)
    capex_per_kw = round(capex_total / capacity_kwp, 0) if capacity_kwp > 0 else 0

    annual_opex = round(capacity_kwp * cost["opex_per_kw_yr"], 0)

    specific_yield = _estimate_specific_yield(abs(avg_lat), tilt_deg, technology)
    estimated_yield_mwh = round(capacity_mwp * specific_yield, 1)

    financial_inputs = {
        "capex_total_gbp": capex_total,
        "capex_per_kw": capex_per_kw,
        "capex_breakdown": {
            "modules_gbp": round(module_cost, 0),
            "inverters_gbp": round(inverter_cost, 0),
            "mounting_gbp": round(mounting_cost, 0),
            "transformers_gbp": round(transformer_cost, 0),
            "dc_cabling_gbp": round(dc_cable_cost, 0),
            "ac_cabling_gbp": round(ac_cable_cost, 0),
            "roads_gbp": round(road_cost, 0),
            "fencing_gbp": round(fence_cost, 0),
            "development_gbp": round(dev_cost, 0),
            "epc_margin_gbp": round(epc_margin, 0),
            "contingency_gbp": round(contingency, 0),
        },
        "annual_opex_gbp": annual_opex,
        "estimated_yield_mwh": estimated_yield_mwh,
        "specific_yield_kwh_kwp": round(specific_yield, 0),
        "capacity_factor_pct": round(
            estimated_yield_mwh / (capacity_mwp * 8760) * 100, 1
        ) if capacity_mwp > 0 else 0,
    }

    # ── Buildable area ─────────────────────────────────────────────
    buildable_area_m2 = usable_area_m2 * (1 - terrain_excluded_pct / 100.0)
    buildable_area_ha = round(buildable_area_m2 / 10_000.0, 2)
    panel_area_m2 = total_modules * module_width_m * module_height_m
    utilization_pct = round(panel_area_m2 / buildable_area_m2 * 100, 1) if buildable_area_m2 > 0 else 0

    # ── Assemble result ────────────────────────────────────────────
    result = {
        "layout": {
            "modules_total": total_modules,
            "capacity_kwp": round(capacity_kwp, 2),
            "gcr": round(gcr_actual, 3),
            "tilt_deg": tilt_deg,
            "row_spacing_m": round(row_pitch, 2),
            "technology": technology,
            "module_spec": f"{module_width_m}m x {module_height_m}m, {module_watts}W bifacial",
            "arrays": arrays,
            "inverter_stations": inverter_stations,
            "transformers": transformers,
            "substation": substation,
            "combiner_boxes": n_combiners,
            "access_roads": access_roads,
        },
        "bom": bom,
        "financial_inputs": financial_inputs,
        "buildable_area_ha": buildable_area_ha,
        "total_site_area_ha": round(site_area_ha, 2),
        "utilization_pct": utilization_pct,
        "geojson": geojson,
        "statistics": {
            "total_modules": total_modules,
            "total_rows": len(all_rows),
            "total_blocks": len([b for b in blocks if b.rows]),
            "total_strings": math.ceil(total_modules / modules_per_string),
            "total_inverter_stations": n_inverter_stations,
            "total_transformers": n_transformers,
            "total_combiner_boxes": n_combiners,
            "total_access_roads": len(access_roads),
            "total_road_length_m": round(total_road_length_m, 1),
            "min_sun_altitude_deg": round(_min_solar_altitude(abs(avg_lat)), 1),
            "rotation_deg": rotation_deg,
            "slope_mean_deg": slope_mean,
            "terrain_excluded_pct": terrain_excluded_pct,
        },
    }

    log.info(
        "PV layout: %d modules (%.1f MWp) in %d rows, %d blocks, "
        "%d inverters, %d transformers on %.1f ha (%.0f%% utilisation)",
        total_modules, capacity_mwp, len(all_rows),
        len([b for b in blocks if b.rows]),
        n_inverter_stations, n_transformers,
        site_area_ha, utilization_pct,
    )

    return result


# ---------------------------------------------------------------------------
# Empty result helper
# ---------------------------------------------------------------------------

def _empty_result(site_area_ha: float, tilt_deg: float, technology: str) -> dict[str, Any]:
    return {
        "layout": {
            "modules_total": 0,
            "capacity_kwp": 0,
            "gcr": 0,
            "tilt_deg": tilt_deg,
            "row_spacing_m": 0,
            "technology": technology,
            "module_spec": "",
            "arrays": [],
            "inverter_stations": [],
            "transformers": [],
            "substation": None,
            "combiner_boxes": 0,
            "access_roads": [],
        },
        "bom": {
            "modules": {"count": 0, "model": "", "total_kwp": 0},
            "inverters": {"count": 0, "model": "", "capacity_kw": 0},
            "transformers": {"count": 0, "voltage_kv": 0},
            "combiner_boxes": 0,
            "dc_cable_m": 0,
            "ac_cable_m": 0,
            "mounting_structures": 0,
            "fencing_m": 0,
        },
        "financial_inputs": {
            "capex_total_gbp": 0,
            "capex_per_kw": 0,
            "annual_opex_gbp": 0,
            "estimated_yield_mwh": 0,
        },
        "buildable_area_ha": 0,
        "total_site_area_ha": round(site_area_ha, 2),
        "utilization_pct": 0,
        "geojson": {"type": "FeatureCollection", "features": []},
        "statistics": {},
    }

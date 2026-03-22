"""Solar farm auto-layout engine — generates optimal panel layouts from site boundaries.

Given a GeoJSON boundary polygon, produces a complete solar farm layout with proper
row spacing, setbacks, exclusion zones, stringing, cost estimates, and yield forecasts.

Coordinate handling:
  - Input/output in WGS84 (lon, lat)
  - Internal calculations in local metres using cos(lat) scaling
  - Row pitch from GCR, tilt geometry, and maintenance access requirements

Typical UK utility-scale parameters:
  - 600 Wp bifacial modules, landscape mount, GCR 0.35-0.45
  - Fixed tilt 20-30 deg (0.7 * latitude), due south azimuth
  - 5 m boundary setback, 2 m minimum row gap
"""

from __future__ import annotations

import math
import logging
from typing import Any

log = logging.getLogger("princeps.solar_layout")

# ---------------------------------------------------------------------------
# Panel presets (manufacturer catalogue)
# ---------------------------------------------------------------------------
PANEL_PRESETS: list[dict[str, Any]] = [
    {
        "id": "jinko_tiger_neo_600",
        "manufacturer": "Jinko Solar",
        "model": "Tiger Neo 600W",
        "watts": 600,
        "width_m": 1.134,
        "height_m": 2.278,
        "efficiency_pct": 22.3,
        "technology": "N-type TOPCon",
        "bifacial": True,
        "weight_kg": 31.2,
    },
    {
        "id": "trina_vertex_s_580",
        "manufacturer": "Trina Solar",
        "model": "Vertex S+ 580W",
        "watts": 580,
        "width_m": 1.134,
        "height_m": 2.176,
        "efficiency_pct": 21.8,
        "technology": "N-type TOPCon",
        "bifacial": True,
        "weight_kg": 29.8,
    },
    {
        "id": "longi_himo7_550",
        "manufacturer": "LONGi",
        "model": "Hi-MO 7 550W",
        "watts": 550,
        "width_m": 1.134,
        "height_m": 2.094,
        "efficiency_pct": 22.0,
        "technology": "HJT",
        "bifacial": True,
        "weight_kg": 27.5,
    },
    {
        "id": "canadian_hiku7_665",
        "manufacturer": "Canadian Solar",
        "model": "HiKu7 CS7N-665W",
        "watts": 665,
        "width_m": 1.134,
        "height_m": 2.384,
        "efficiency_pct": 22.5,
        "technology": "N-type TOPCon",
        "bifacial": True,
        "weight_kg": 33.4,
    },
]


# ---------------------------------------------------------------------------
# Geometry utilities — pure-Python, no external deps
# ---------------------------------------------------------------------------

def _deg2rad(d: float) -> float:
    return d * math.pi / 180.0


def _metres_per_deg(lat: float) -> tuple[float, float]:
    """Return (m_per_deg_lon, m_per_deg_lat) at the given latitude."""
    lat_rad = _deg2rad(lat)
    m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
    m_per_deg_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
    return m_per_deg_lon, m_per_deg_lat


def _to_local(lon: float, lat: float, origin_lon: float, origin_lat: float,
              m_lon: float, m_lat: float) -> tuple[float, float]:
    """WGS84 → local metres relative to origin."""
    return (lon - origin_lon) * m_lon, (lat - origin_lat) * m_lat


def _to_wgs84(x: float, y: float, origin_lon: float, origin_lat: float,
              m_lon: float, m_lat: float) -> tuple[float, float]:
    """Local metres → WGS84."""
    return origin_lon + x / m_lon, origin_lat + y / m_lat


def point_in_polygon(px: float, py: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test (local metre coords)."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _polygon_area(pts: list[tuple[float, float]]) -> float:
    """Shoelace formula for polygon area (local metre coords). Returns absolute area."""
    n = len(pts)
    area = 0.0
    j = n - 1
    for i in range(n):
        area += (pts[j][0] + pts[i][0]) * (pts[j][1] - pts[i][1])
        j = i
    return abs(area) / 2.0


def _polygon_centroid(pts: list[tuple[float, float]]) -> tuple[float, float]:
    """Centroid of a polygon (local metre coords)."""
    n = len(pts)
    cx = sum(p[0] for p in pts) / n
    cy = sum(p[1] for p in pts) / n
    return cx, cy


def _bounding_box(pts: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y)."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def offset_polygon(pts: list[tuple[float, float]], distance: float) -> list[tuple[float, float]]:
    """Inward offset (shrink) a polygon by `distance` metres.

    Uses the simple perpendicular-offset approach on each edge, then intersects
    adjacent offset edges. Works well for convex and mildly concave polygons.
    For highly concave polygons some edge cases may arise but it's sufficient
    for typical site boundaries.
    """
    n = len(pts)
    if n < 3:
        return pts

    # Close ring if needed
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
        n = len(pts)

    # Compute offset edges
    offset_edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for i in range(n - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue
        # Inward normal (for CCW polygon this is to the right; for CW to the left)
        # We'll detect winding and adjust
        nx = dy / length
        ny = -dx / length
        offset_edges.append((
            (x1 + nx * distance, y1 + ny * distance),
            (x2 + nx * distance, y2 + ny * distance),
        ))

    if len(offset_edges) < 3:
        return pts[:-1]

    # Check winding — if the offset polygon is larger, we used the wrong normal direction
    # Test by checking if the first offset point is inside the original polygon
    test_pt = offset_edges[0][0]
    if not point_in_polygon(test_pt[0], test_pt[1], pts[:-1]):
        # Wrong direction, flip all offsets
        offset_edges_new: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            dx = x2 - x1
            dy = y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            nx = -dy / length
            ny = dx / length
            offset_edges_new.append((
                (x1 + nx * distance, y1 + ny * distance),
                (x2 + nx * distance, y2 + ny * distance),
            ))
        offset_edges = offset_edges_new

    # Intersect adjacent edges to get offset polygon vertices
    result: list[tuple[float, float]] = []
    ne = len(offset_edges)
    for i in range(ne):
        j = (i + 1) % ne
        pt = _line_line_intersect(
            offset_edges[i][0], offset_edges[i][1],
            offset_edges[j][0], offset_edges[j][1],
        )
        if pt is not None:
            result.append(pt)
        else:
            # Parallel edges — use endpoint
            result.append(offset_edges[i][1])

    return result


def _line_line_intersect(
    p1: tuple[float, float], p2: tuple[float, float],
    p3: tuple[float, float], p4: tuple[float, float],
) -> tuple[float, float] | None:
    """Intersection of two infinite lines (p1-p2) and (p3-p4)."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    ix = x1 + t * (x2 - x1)
    iy = y1 + t * (y2 - y1)
    return (ix, iy)


def _clip_segment_to_polygon(
    x1: float, y1: float, x2: float, y2: float,
    polygon: list[tuple[float, float]],
) -> list[tuple[float, float, float, float]]:
    """Clip a horizontal line segment to a polygon, returning inside segments.

    Returns list of (xa, ya, xb, yb) segments that lie inside the polygon.
    Uses the Sutherland-Hodgman-style scan: find all intersection t-values
    with polygon edges, sort, and test midpoints.
    """
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return []

    # Collect all t values where the segment intersects polygon edges
    t_vals: list[float] = [0.0, 1.0]
    n = len(polygon)
    for i in range(n):
        j = (i + 1) % n
        ex1, ey1 = polygon[i]
        ex2, ey2 = polygon[j]
        # Parametric intersection: P1 + t*(P2-P1) = E1 + s*(E2-E1)
        edx = ex2 - ex1
        edy = ey2 - ey1
        denom = dx * edy - dy * edx
        if abs(denom) < 1e-12:
            continue
        t = ((ex1 - x1) * edy - (ey1 - y1) * edx) / denom
        s = ((ex1 - x1) * dy - (ey1 - y1) * dx) / denom
        if 0.0 <= t <= 1.0 and 0.0 <= s <= 1.0:
            t_vals.append(t)

    t_vals.sort()

    # For each consecutive pair, test midpoint
    segments: list[tuple[float, float, float, float]] = []
    for i in range(len(t_vals) - 1):
        ta, tb = t_vals[i], t_vals[i + 1]
        if tb - ta < 1e-9:
            continue
        mid_t = (ta + tb) / 2.0
        mx = x1 + mid_t * dx
        my = y1 + mid_t * dy
        if point_in_polygon(mx, my, polygon):
            xa = x1 + ta * dx
            ya = y1 + ta * dy
            xb = x1 + tb * dx
            yb = y1 + tb * dy
            segments.append((xa, ya, xb, yb))

    # Merge adjacent segments
    if len(segments) > 1:
        merged: list[tuple[float, float, float, float]] = [segments[0]]
        for seg in segments[1:]:
            prev = merged[-1]
            if abs(prev[2] - seg[0]) < 1e-6 and abs(prev[3] - seg[1]) < 1e-6:
                merged[-1] = (prev[0], prev[1], seg[2], seg[3])
            else:
                merged.append(seg)
        segments = merged

    return segments


def _subtract_exclusions(
    segments: list[tuple[float, float, float, float]],
    exclusion_polys: list[list[tuple[float, float]]],
    y: float,
) -> list[tuple[float, float, float, float]]:
    """Remove parts of row segments that overlap exclusion zones.

    For each exclusion polygon, find the x-range where the horizontal line at y
    intersects the polygon, and subtract those intervals from the segments.
    """
    if not exclusion_polys:
        return segments

    # Collect exclusion x-intervals at this y
    excl_intervals: list[tuple[float, float]] = []
    for poly in exclusion_polys:
        xs_at_y: list[float] = []
        n = len(poly)
        for i in range(n):
            j = (i + 1) % n
            y1, y2 = poly[i][1], poly[j][1]
            if (y1 <= y < y2) or (y2 <= y < y1):
                if abs(y2 - y1) < 1e-12:
                    continue
                t = (y - y1) / (y2 - y1)
                x_int = poly[i][0] + t * (poly[j][0] - poly[i][0])
                xs_at_y.append(x_int)
        xs_at_y.sort()
        # Pair up intersections
        for k in range(0, len(xs_at_y) - 1, 2):
            excl_intervals.append((xs_at_y[k], xs_at_y[k + 1]))

    if not excl_intervals:
        return segments

    # Subtract exclusion intervals from segments
    result: list[tuple[float, float, float, float]] = []
    for sx1, sy1, sx2, sy2 in segments:
        remaining: list[tuple[float, float]] = [(sx1, sx2)]
        for ex1, ex2 in excl_intervals:
            new_remaining: list[tuple[float, float]] = []
            for ra, rb in remaining:
                if ex2 <= ra or ex1 >= rb:
                    new_remaining.append((ra, rb))
                else:
                    if ra < ex1:
                        new_remaining.append((ra, ex1))
                    if rb > ex2:
                        new_remaining.append((ex2, rb))
            remaining = new_remaining
        for ra, rb in remaining:
            if rb - ra > 0.5:  # min 0.5m segment
                result.append((ra, y, rb, y))

    return result


# ---------------------------------------------------------------------------
# Main layout engine
# ---------------------------------------------------------------------------

def generate_layout(
    boundary_coords: list[list[float]],
    *,
    panel_type: str = "landscape",
    panel_watts: int = 600,
    panel_width_m: float | None = None,
    panel_height_m: float | None = None,
    modules_per_string: int = 24,
    tilt_deg: float | None = None,
    azimuth_deg: float = 180.0,
    gcr_target: float = 0.40,
    setback_m: float = 5.0,
    row_gap_min_m: float = 2.0,
    tracking: str = "fixed",
    exclusion_zones: list[list[list[float]]] | None = None,
    tables_high: int = 2,
    tables_wide: int = 2,
) -> dict[str, Any]:
    """Generate a complete solar farm layout from a site boundary polygon.

    Parameters
    ----------
    boundary_coords : list of [lon, lat] pairs
        Outer ring of the site boundary polygon in WGS84.
    panel_type : "landscape" or "portrait"
    panel_watts : Watt-peak rating per module.
    panel_width_m / panel_height_m : Override default module dimensions.
    modules_per_string : Modules wired in series per string.
    tilt_deg : Panel tilt angle. None = auto (0.7 * latitude).
    azimuth_deg : Panel facing direction (180 = due south).
    gcr_target : Target ground coverage ratio (0.2 – 0.6).
    setback_m : Distance to shrink boundary inward.
    row_gap_min_m : Minimum gap between row trailing and next row leading edge.
    tracking : "fixed", "single_axis", or "dual_axis".
    exclusion_zones : Optional list of polygon coordinate rings to avoid.
    tables_high : Module rows per table (typically 2 or 4).
    tables_wide : Modules across per table (typically 2).

    Returns
    -------
    dict with keys: layout (GeoJSON FeatureCollection), summary, yield_estimate, costs
    """
    # ── Validate inputs ──────────────────────────────────────────────
    if len(boundary_coords) < 3:
        raise ValueError("Boundary must have at least 3 coordinate pairs")

    gcr_target = max(0.15, min(0.65, gcr_target))

    # ── Determine panel dimensions ───────────────────────────────────
    if panel_type == "portrait":
        pw = panel_width_m or 1.134
        ph = panel_height_m or 2.278
    else:  # landscape
        pw = panel_width_m or 2.278
        ph = panel_height_m or 1.134

    # ── Coordinate system setup ──────────────────────────────────────
    # Use centroid of boundary as local origin
    avg_lat = sum(c[1] for c in boundary_coords) / len(boundary_coords)
    avg_lon = sum(c[0] for c in boundary_coords) / len(boundary_coords)
    m_lon, m_lat = _metres_per_deg(avg_lat)

    # Convert boundary to local metres
    boundary_local: list[tuple[float, float]] = [
        _to_local(c[0], c[1], avg_lon, avg_lat, m_lon, m_lat)
        for c in boundary_coords
    ]
    # Close ring if needed
    if boundary_local[0] != boundary_local[-1]:
        boundary_local.append(boundary_local[0])

    # Site area before setback
    site_area_m2 = _polygon_area(boundary_local[:-1])
    site_area_ha = site_area_m2 / 10000.0

    # ── Auto-calculate tilt from latitude ────────────────────────────
    if tilt_deg is None:
        if tracking == "single_axis":
            tilt_deg = 0.0  # single-axis trackers are typically horizontal
        elif tracking == "dual_axis":
            tilt_deg = 0.0
        else:
            tilt_deg = round(0.7 * abs(avg_lat), 1)

    # ── Calculate row pitch ──────────────────────────────────────────
    tilt_rad = _deg2rad(tilt_deg)

    # Table dimensions
    table_depth_m = ph * tables_high  # depth of one table along tilt direction
    table_width_m = pw * tables_wide  # width of one table along row direction

    # Projected ground coverage of a table row
    panel_ground_projection = table_depth_m * math.cos(tilt_rad)

    if tracking == "single_axis":
        # Standard single-axis spacing: ~2.5x module width
        row_pitch = pw * 2.5
    elif tracking == "dual_axis":
        row_pitch = pw * 3.5
    else:
        # Fixed tilt: pitch from GCR
        # GCR = panel_ground_projection / pitch
        row_pitch = panel_ground_projection / gcr_target

    # Enforce minimum row gap
    trailing_edge_height = table_depth_m * math.sin(tilt_rad)
    actual_gap = row_pitch - panel_ground_projection
    if actual_gap < row_gap_min_m:
        row_pitch = panel_ground_projection + row_gap_min_m

    # Recalculate actual GCR
    gcr_actual = panel_ground_projection / row_pitch

    # ── Apply setback ────────────────────────────────────────────────
    if setback_m > 0:
        usable_boundary = offset_polygon(boundary_local[:-1], setback_m)
    else:
        usable_boundary = boundary_local[:-1]

    if len(usable_boundary) < 3:
        return _empty_result(site_area_ha, tilt_deg, azimuth_deg, tracking, panel_type)

    # Close ring for usable boundary
    usable_closed = usable_boundary + [usable_boundary[0]]

    # ── Convert exclusion zones to local metres ──────────────────────
    excl_local: list[list[tuple[float, float]]] = []
    if exclusion_zones:
        for zone in exclusion_zones:
            zone_local = [
                _to_local(c[0], c[1], avg_lon, avg_lat, m_lon, m_lat)
                for c in zone
            ]
            excl_local.append(zone_local)

    # ── Generate rows ────────────────────────────────────────────────
    bbox = _bounding_box(usable_boundary)
    min_x, min_y, max_x, max_y = bbox

    features: list[dict[str, Any]] = []
    total_panels = 0
    total_tables = 0
    row_count = 0
    string_counter = 0
    panels_in_current_string = 0

    # Rows run east-west (constant y), spaced by row_pitch in the north-south direction
    y = min_y + panel_ground_projection / 2.0  # start half a projection in

    while y <= max_y - panel_ground_projection / 2.0:
        # Create a horizontal line across the bounding box at this y
        row_segments = _clip_segment_to_polygon(min_x, y, max_x, y, usable_boundary)

        # Subtract exclusion zones
        if excl_local:
            row_segments = _subtract_exclusions(row_segments, excl_local, y)

        for seg_x1, _, seg_x2, _ in row_segments:
            seg_length = seg_x2 - seg_x1

            # Place tables along this segment
            x = seg_x1
            table_in_row = 0

            while x + table_width_m <= seg_x2 + 0.01:  # small tolerance
                panels_in_table = tables_high * tables_wide

                # String assignment
                if panels_in_current_string + panels_in_table > modules_per_string:
                    if panels_in_current_string > 0:
                        string_counter += 1
                    panels_in_current_string = 0

                if panels_in_current_string == 0:
                    string_counter += 1
                    panels_in_current_string = 0

                panels_in_current_string += panels_in_table
                if panels_in_current_string >= modules_per_string:
                    panels_in_current_string = 0

                # Build table polygon (rectangle in local coords)
                # Table sits on the ground, tilted toward azimuth
                # For south-facing: table extends northward from the row line
                half_ground = panel_ground_projection / 2.0
                table_coords_local = [
                    (x, y - half_ground),
                    (x + table_width_m, y - half_ground),
                    (x + table_width_m, y + half_ground),
                    (x, y + half_ground),
                    (x, y - half_ground),  # close ring
                ]

                # Convert back to WGS84
                table_coords_wgs84 = [
                    list(_to_wgs84(px, py, avg_lon, avg_lat, m_lon, m_lat))
                    for px, py in table_coords_local
                ]

                string_id = f"S{string_counter:04d}"

                feature: dict[str, Any] = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [table_coords_wgs84],
                    },
                    "properties": {
                        "type": "panel_table",
                        "row": row_count,
                        "table": table_in_row,
                        "string_id": string_id,
                        "panels_in_table": panels_in_table,
                        "tilt_deg": tilt_deg,
                        "azimuth_deg": azimuth_deg,
                        "color": "#1a237e",
                    },
                }
                features.append(feature)
                total_panels += panels_in_table
                total_tables += 1
                table_in_row += 1

                x += table_width_m + 0.02  # 2cm gap between tables in a row

            if table_in_row > 0:
                row_count += 1

        y += row_pitch

    # Finalize strings count
    total_strings = string_counter

    # ── Summary calculations ─────────────────────────────────────────
    total_mwp = total_panels * panel_watts / 1_000_000.0
    panel_area_m2 = total_panels * pw * ph

    # ── Yield estimate ───────────────────────────────────────────────
    # UK-specific specific yield based on latitude and tracking
    base_specific_yield = _estimate_specific_yield(abs(avg_lat), tracking, tilt_deg)
    performance_ratio = 0.82 if tracking == "fixed" else 0.84
    annual_mwh_p50 = total_mwp * base_specific_yield
    capacity_factor = (annual_mwh_p50 / (total_mwp * 8760)) * 100 if total_mwp > 0 else 0

    yield_estimate: dict[str, Any] = {
        "annual_mwh_p50": round(annual_mwh_p50, 1),
        "capacity_factor_pct": round(capacity_factor, 1),
        "specific_yield_kwh_kwp": round(base_specific_yield, 0),
        "performance_ratio": performance_ratio,
    }

    # ── Cost estimate ────────────────────────────────────────────────
    panels_gbp = round(total_panels * 0.18 * panel_watts / 1000)
    mounting_gbp = round(total_panels * 25)
    inverters_gbp = round(total_mwp * 30000)
    cabling_gbp = round(total_mwp * 15000)
    civils_gbp = round(site_area_ha * 8000)
    total_epc_gbp = panels_gbp + mounting_gbp + inverters_gbp + cabling_gbp + civils_gbp
    gbp_per_mwp = round(total_epc_gbp / total_mwp) if total_mwp > 0 else 0

    costs: dict[str, Any] = {
        "panels_gbp": panels_gbp,
        "mounting_gbp": mounting_gbp,
        "inverters_gbp": inverters_gbp,
        "cabling_gbp": cabling_gbp,
        "civils_gbp": civils_gbp,
        "total_epc_gbp": total_epc_gbp,
        "gbp_per_mwp": gbp_per_mwp,
    }

    # ── Assemble result ──────────────────────────────────────────────
    summary: dict[str, Any] = {
        "total_panels": total_panels,
        "total_mwp": round(total_mwp, 3),
        "rows": row_count,
        "strings": total_strings,
        "tables": total_tables,
        "gcr_actual": round(gcr_actual, 3),
        "site_area_ha": round(site_area_ha, 2),
        "usable_area_ha": round(_polygon_area(usable_boundary) / 10000.0, 2),
        "panel_area_m2": round(panel_area_m2, 1),
        "tilt_deg": tilt_deg,
        "azimuth_deg": azimuth_deg,
        "tracking": tracking,
        "row_pitch_m": round(row_pitch, 2),
        "panel_type": panel_type,
        "tables_high": tables_high,
        "tables_wide": tables_wide,
        "panel_watts": panel_watts,
        "modules_per_string": modules_per_string,
    }

    layout: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": features,
    }

    log.info(
        "Solar layout: %d panels (%.1f MWp) in %d rows on %.1f ha site, GCR=%.2f",
        total_panels, total_mwp, row_count, site_area_ha, gcr_actual,
    )

    return {
        "layout": layout,
        "summary": summary,
        "yield_estimate": yield_estimate,
        "costs": costs,
    }


def _estimate_specific_yield(lat: float, tracking: str, tilt_deg: float) -> float:
    """Estimate annual specific yield (kWh/kWp) based on latitude and tracking.

    Calibrated for UK/Northern Europe latitudes (50-60 deg).
    """
    # Base yield at optimal tilt decreases with latitude
    # UK range: ~950-1100 kWh/kWp for fixed tilt
    if lat < 35:
        base = 1450
    elif lat < 45:
        base = 1250
    elif lat < 50:
        base = 1100
    elif lat < 55:
        base = 1020
    elif lat < 60:
        base = 950
    else:
        base = 850

    # Tracking bonus
    if tracking == "single_axis":
        base *= 1.20  # ~20% gain
    elif tracking == "dual_axis":
        base *= 1.35  # ~35% gain

    # Tilt sub-optimality penalty (for fixed mount)
    if tracking == "fixed":
        optimal_tilt = 0.7 * lat
        tilt_diff = abs(tilt_deg - optimal_tilt)
        if tilt_diff > 10:
            base *= (1.0 - 0.003 * tilt_diff)  # ~0.3% per degree off optimal

    return base


def _empty_result(site_area_ha: float, tilt: float, azimuth: float,
                  tracking: str, panel_type: str) -> dict[str, Any]:
    """Return an empty layout result when no panels can be placed."""
    return {
        "layout": {"type": "FeatureCollection", "features": []},
        "summary": {
            "total_panels": 0, "total_mwp": 0, "rows": 0, "strings": 0,
            "tables": 0, "gcr_actual": 0, "site_area_ha": round(site_area_ha, 2),
            "usable_area_ha": 0, "panel_area_m2": 0, "tilt_deg": tilt,
            "azimuth_deg": azimuth, "tracking": tracking, "row_pitch_m": 0,
            "panel_type": panel_type, "tables_high": 0, "tables_wide": 0,
            "panel_watts": 0, "modules_per_string": 0,
        },
        "yield_estimate": {
            "annual_mwh_p50": 0, "capacity_factor_pct": 0,
            "specific_yield_kwh_kwp": 0, "performance_ratio": 0,
        },
        "costs": {
            "panels_gbp": 0, "mounting_gbp": 0, "inverters_gbp": 0,
            "cabling_gbp": 0, "civils_gbp": 0, "total_epc_gbp": 0, "gbp_per_mwp": 0,
        },
    }


def quick_layout_from_point(
    lat: float,
    lon: float,
    area_ha: float = 50.0,
    capacity_mwp: float | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate a layout from a centre point and area.

    Creates a rectangular boundary centred on (lat, lon) sized to `area_ha`,
    then runs the full layout engine. If `capacity_mwp` is given, adjusts
    GCR to approximately hit that target.
    """
    # Create a square boundary
    side_m = math.sqrt(area_ha * 10000)
    half = side_m / 2.0

    m_lon, m_lat = _metres_per_deg(lat)
    d_lon = half / m_lon
    d_lat = half / m_lat

    boundary = [
        [lon - d_lon, lat - d_lat],
        [lon + d_lon, lat - d_lat],
        [lon + d_lon, lat + d_lat],
        [lon - d_lon, lat + d_lat],
    ]

    # If capacity target specified, adjust GCR
    if capacity_mwp is not None:
        panel_watts = kwargs.get("panel_watts", 600)
        pw = kwargs.get("panel_width_m", 2.278)
        ph = kwargs.get("panel_height_m", 1.134)
        panel_area = pw * ph
        # panels needed
        panels_needed = capacity_mwp * 1_000_000 / panel_watts
        panel_area_total = panels_needed * panel_area
        # GCR = panel_area_total / site_area
        gcr = panel_area_total / (area_ha * 10000)
        gcr = max(0.20, min(0.55, gcr))
        kwargs["gcr_target"] = gcr

    return generate_layout(boundary, **kwargs)


def get_panel_presets() -> list[dict[str, Any]]:
    """Return available panel presets."""
    return PANEL_PRESETS

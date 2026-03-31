"""
Site Auto-Designer — generates solar PV, BESS, and hybrid site layouts.

Given a GeoJSON boundary polygon, fills it with infrastructure:
  - Solar PV: panel rows at configurable tilt/spacing, access roads, setbacks
  - BESS: container grid, transformers, perimeter fence, tree screen, noise contours
  - Hybrid: splits boundary into solar + BESS zones

All coordinates are WGS84 (EPSG:4326). Distances use Haversine approximation
for sub-km accuracy which is adequate for site design purposes.
"""

import json
import math
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Geometry helpers (no external deps — pure Python)
# ---------------------------------------------------------------------------

DEG_TO_RAD = math.pi / 180
EARTH_R = 6_371_000  # metres


def _haversine(lon1, lat1, lon2, lat2):
    """Distance in metres between two WGS84 points."""
    dlon = (lon2 - lon1) * DEG_TO_RAD
    dlat = (lat2 - lat1) * DEG_TO_RAD
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * DEG_TO_RAD) * math.cos(lat2 * DEG_TO_RAD) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def _metres_per_deg(lat):
    """Approximate metres per degree at given latitude."""
    lat_r = lat * DEG_TO_RAD
    m_per_deg_lat = 111_132.92 - 559.82 * math.cos(2 * lat_r) + 1.175 * math.cos(4 * lat_r)
    m_per_deg_lon = 111_412.84 * math.cos(lat_r) - 93.5 * math.cos(3 * lat_r)
    return m_per_deg_lat, m_per_deg_lon


def _centroid(coords):
    """Centroid of a polygon ring."""
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _bbox(coords):
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return min(xs), min(ys), max(xs), max(ys)


def _polygon_area_m2(coords, lat):
    """Shoelface area in m^2 using local approximation."""
    m_lat, m_lon = _metres_per_deg(lat)
    area = 0
    n = len(coords)
    for i in range(n):
        j = (i + 1) % n
        xi, yi = coords[i][0] * m_lon, coords[i][1] * m_lat
        xj, yj = coords[j][0] * m_lon, coords[j][1] * m_lat
        area += xi * yj - xj * yi
    return abs(area) / 2


def _offset_point(lon, lat, dx_m, dy_m):
    """Offset a point by dx/dy metres."""
    m_lat, m_lon = _metres_per_deg(lat)
    return lon + dx_m / m_lon, lat + dy_m / m_lat


def _point_in_polygon(px, py, poly):
    """Ray-casting point-in-polygon test."""
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


def _shrink_polygon(coords, setback_m):
    """Inward offset (simplified — works for convex and mildly concave polygons)."""
    cx, cy = _centroid(coords)
    m_lat, m_lon = _metres_per_deg(cy)
    result = []
    for lon, lat in coords:
        dx = (lon - cx) * m_lon
        dy = (lat - cy) * m_lat
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 1:
            result.append((lon, lat))
            continue
        shrink = max(0, dist - setback_m) / dist
        new_lon = cx + (lon - cx) * shrink
        new_lat = cy + (lat - cy) * shrink
        result.append((new_lon, new_lat))
    return result


def _make_circle_ring(cx, cy, radius_m, segments=64):
    """Create a circle polygon ring around (cx, cy)."""
    ring = []
    for i in range(segments + 1):
        angle = 2 * math.pi * i / segments
        dx = radius_m * math.cos(angle)
        dy = radius_m * math.sin(angle)
        lon, lat = _offset_point(cx, cy, dx, dy)
        ring.append([lon, lat])
    return ring


# ---------------------------------------------------------------------------
# Solar PV auto-design
# ---------------------------------------------------------------------------

def auto_design_solar(
    boundary_geojson: dict,
    tilt: float = 25,
    azimuth: float = 180,
    row_spacing: float = 7.0,
    gcr: float = 0.4,
    panel_wp: int = 580,
    panel_width: float = 2.278,
    panel_height: float = 1.134,
    panels_per_string: int = 28,
    setback_m: float = 10.0,
    road_every_n_rows: int = 20,
    road_width_m: float = 4.0,
) -> dict:
    """Fill a polygon boundary with solar panel rows.

    Returns dict with panels, roads, infrastructure, exclusions, metrics.
    """
    # Extract ring
    geom = boundary_geojson.get("geometry", boundary_geojson)
    coords = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]

    cx, cy = _centroid(coords)
    m_lat, m_lon = _metres_per_deg(cy)
    total_area_m2 = _polygon_area_m2(coords, cy)

    # Inward setback
    inner = _shrink_polygon(coords, setback_m)
    xmin, ymin, xmax, ymax = _bbox(inner)

    # Panel row geometry (portrait orientation for fixed-tilt)
    row_length_m = panels_per_string * panel_width  # ~63.8m for 28 panels
    panel_depth_m = panel_height * math.cos(tilt * DEG_TO_RAD)

    # Scan rows south to north
    panels = []
    roads = []
    row_idx = 0
    total_panels = 0

    y = ymin
    row_dy = row_spacing / m_lat

    while y <= ymax:
        # Insert access road every N rows
        if row_idx > 0 and row_idx % road_every_n_rows == 0:
            road_y_start = y
            road_y_end = y + road_width_m / m_lat
            roads.append({
                "line": [[xmin, road_y_start], [xmax, road_y_start], [xmax, road_y_end], [xmin, road_y_end]],
                "type": "access_road",
            })
            y = road_y_end + row_dy * 0.3
            continue

        # Build row segments that fit inside the polygon
        x = xmin
        col_dx = row_length_m / m_lon
        panel_depth_dlat = panel_depth_m / m_lat

        while x + col_dx <= xmax:
            # Check if center of string is inside polygon
            mid_x = x + col_dx / 2
            mid_y = y + panel_depth_dlat / 2

            if _point_in_polygon(mid_x, mid_y, inner):
                poly = [
                    [x, y],
                    [x + col_dx, y],
                    [x + col_dx, y + panel_depth_dlat],
                    [x, y + panel_depth_dlat],
                    [x, y],  # close ring
                ]
                n_panels = panels_per_string
                cap_kwp = n_panels * panel_wp / 1000
                total_panels += n_panels
                panels.append({
                    "polygon": poly,
                    "label": f"Row {row_idx + 1}",
                    "capacity_kwp": round(cap_kwp, 2),
                    "panel_count": n_panels,
                    "row": row_idx,
                })
            x += col_dx + (2.0 / m_lon)  # 2m gap between strings

        row_idx += 1
        y += row_dy

    total_capacity_mwp = total_panels * panel_wp / 1_000_000
    usable_area = total_area_m2 - (setback_m * math.sqrt(total_area_m2) * 4)  # rough

    # Substation placement — center bottom
    sub_lon, sub_lat = _offset_point(cx, ymin + setback_m / m_lat, 0, -setback_m * 0.5)
    infrastructure = [
        {"point": [cx, ymin + (setback_m * 1.5) / m_lat], "type": "substation", "label": "Grid Substation"},
        {"point": [cx + 30 / m_lon, ymin + (setback_m * 1.5) / m_lat], "type": "inverter", "label": "Central Inverter"},
    ]

    # Boundary as exclusion ring (the setback area)
    exclusions = [{
        "polygon": coords + [coords[0]],
        "inner": inner + [inner[0]],
        "reason": f"{setback_m}m boundary setback",
    }]

    return {
        "panels": panels,
        "containers": [],
        "exclusions": exclusions,
        "roads": roads,
        "infrastructure": infrastructure,
        "noise_contours": [],
        "boundary": coords,
        "metrics": {
            "total_capacity_mwp": round(total_capacity_mwp, 2),
            "total_capacity_mwh": 0,
            "area_total_ha": round(total_area_m2 / 10_000, 2),
            "area_used_ha": round(len(panels) * row_length_m * panel_depth_m / 10_000, 2),
            "panel_count": total_panels,
            "container_count": 0,
            "row_count": row_idx,
            "string_count": len(panels),
            "tilt": tilt,
            "azimuth": azimuth,
            "row_spacing": row_spacing,
            "gcr": gcr,
            "panel_wp": panel_wp,
        },
    }


# ---------------------------------------------------------------------------
# BESS auto-design
# ---------------------------------------------------------------------------

def auto_design_bess(
    boundary_geojson: dict,
    total_mwh: float = 100,
    container_size: str = "40ft",
    mwh_per_container: float = 5.0,
    source_noise_dba: float = 85.0,
    setback_m: float = 8.0,
    tree_screen_depth_m: float = 5.0,
) -> dict:
    """Arrange BESS containers in a grid within the boundary.

    Returns containers, noise contours, perimeter fence, tree screen.
    """
    geom = boundary_geojson.get("geometry", boundary_geojson)
    coords = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]

    cx, cy = _centroid(coords)
    m_lat, m_lon = _metres_per_deg(cy)
    total_area_m2 = _polygon_area_m2(coords, cy)

    # Container dimensions
    if container_size == "40ft":
        c_len, c_wid, c_hgt = 12.2, 2.44, 2.59
    else:  # 20ft
        c_len, c_wid, c_hgt = 6.1, 2.44, 2.59

    n_containers = math.ceil(total_mwh / mwh_per_container)

    # Grid layout: rows and columns
    gap_x = 3.0  # between containers in a row
    gap_y = 6.0  # between rows

    # Calculate grid dimensions
    cols = max(1, math.ceil(math.sqrt(n_containers * 1.5)))
    rows = math.ceil(n_containers / cols)

    grid_width = cols * c_len + (cols - 1) * gap_x
    grid_depth = rows * c_wid + (rows - 1) * gap_y

    # Center the grid in the polygon
    start_x = cx - (grid_width / 2) / m_lon
    start_y = cy - (grid_depth / 2) / m_lat

    containers = []
    placed = 0
    for r in range(rows):
        for c in range(cols):
            if placed >= n_containers:
                break
            x = start_x + (c * (c_len + gap_x)) / m_lon
            y = start_y + (r * (c_wid + gap_y)) / m_lat
            center = [x + (c_len / 2) / m_lon, y + (c_wid / 2) / m_lat]

            containers.append({
                "center": center,
                "size": container_size,
                "type": "battery",
                "dimensions": [c_len, c_wid, c_hgt],
                "capacity_mwh": mwh_per_container,
                "row": r,
                "col": c,
                "label": f"BESS-{placed + 1:03d}",
            })
            placed += 1

    # Add transformer and inverter units (every 10 containers)
    n_transformers = max(1, n_containers // 10)
    for i in range(n_transformers):
        tx = start_x + grid_width / m_lon + (8.0 / m_lon)
        ty = start_y + (i * (gap_y + c_wid) * 2.5) / m_lat
        containers.append({
            "center": [tx, ty],
            "size": "20ft",
            "type": "transformer",
            "dimensions": [4.0, 2.5, 2.8],
            "capacity_mwh": 0,
            "label": f"TX-{i + 1:02d}",
        })

    # Perimeter fence — rectangular around the grid with margin
    fence_margin = 4.0
    fence = [
        [start_x - fence_margin / m_lon, start_y - fence_margin / m_lat],
        [start_x + (grid_width + fence_margin + 15) / m_lon, start_y - fence_margin / m_lat],
        [start_x + (grid_width + fence_margin + 15) / m_lon, start_y + (grid_depth + fence_margin) / m_lat],
        [start_x - fence_margin / m_lon, start_y + (grid_depth + fence_margin) / m_lat],
        [start_x - fence_margin / m_lon, start_y - fence_margin / m_lat],  # close
    ]

    # Tree screen — offset from fence
    tree_offset = fence_margin + tree_screen_depth_m
    tree_screen = [
        [start_x - tree_offset / m_lon, start_y - tree_offset / m_lat],
        [start_x + (grid_width + tree_offset + 15) / m_lon, start_y - tree_offset / m_lat],
        [start_x + (grid_width + tree_offset + 15) / m_lon, start_y + (grid_depth + tree_offset) / m_lat],
        [start_x - tree_offset / m_lon, start_y + (grid_depth + tree_offset) / m_lat],
        [start_x - tree_offset / m_lon, start_y - tree_offset / m_lat],
    ]

    # Fire break zones
    fire_break_width = 6.0
    fire_breaks = [{
        "polygon": [
            [start_x - (fence_margin + fire_break_width) / m_lon, start_y - (fence_margin + fire_break_width) / m_lat],
            [start_x + (grid_width + fence_margin + fire_break_width + 15) / m_lon, start_y - (fence_margin + fire_break_width) / m_lat],
            [start_x + (grid_width + fence_margin + fire_break_width + 15) / m_lon, start_y + (grid_depth + fence_margin + fire_break_width) / m_lat],
            [start_x - (fence_margin + fire_break_width) / m_lon, start_y + (grid_depth + fence_margin + fire_break_width) / m_lat],
            [start_x - (fence_margin + fire_break_width) / m_lon, start_y - (fence_margin + fire_break_width) / m_lat],
        ],
        "reason": "Fire break zone (6m clearance)",
    }]

    # Noise contours — inverse square law from BESS centre
    # SPL at distance d: L = L_source - 20 * log10(d / d_ref) where d_ref = 1m
    noise_contours = []
    for target_dba in [45, 40, 35]:
        # d = 10^((L_source - target) / 20)
        distance_m = 10 ** ((source_noise_dba - target_dba) / 20)
        ring = _make_circle_ring(cx, cy, distance_m, segments=48)
        noise_contours.append({
            "polygon": ring,
            "dba_level": target_dba,
            "radius_m": round(distance_m, 1),
        })

    infrastructure = [
        {"point": [cx, start_y - (fence_margin + 8) / m_lat], "type": "gate", "label": "Site Access Gate"},
        {"point": [start_x + (grid_width + 20) / m_lon, cy], "type": "substation", "label": "Grid Connection Point"},
    ]

    return {
        "panels": [],
        "containers": containers,
        "exclusions": fire_breaks,
        "roads": [],
        "infrastructure": infrastructure,
        "noise_contours": noise_contours,
        "fence": fence,
        "tree_screen": tree_screen,
        "boundary": coords,
        "metrics": {
            "total_capacity_mwp": 0,
            "total_capacity_mwh": round(n_containers * mwh_per_container, 1),
            "area_total_ha": round(total_area_m2 / 10_000, 2),
            "area_used_ha": round((grid_width * grid_depth) / 10_000, 3),
            "panel_count": 0,
            "container_count": n_containers,
            "transformer_count": n_transformers,
            "container_size": container_size,
            "mwh_per_container": mwh_per_container,
            "grid_rows": rows,
            "grid_cols": cols,
            "source_noise_dba": source_noise_dba,
            "noise_45dba_radius_m": round(10 ** ((source_noise_dba - 45) / 20), 1),
            "noise_40dba_radius_m": round(10 ** ((source_noise_dba - 40) / 20), 1),
            "noise_35dba_radius_m": round(10 ** ((source_noise_dba - 35) / 20), 1),
        },
    }


# ---------------------------------------------------------------------------
# Hybrid auto-design
# ---------------------------------------------------------------------------

def auto_design_hybrid(
    boundary_geojson: dict,
    solar_fraction: float = 0.7,
    total_mw: float = 50,
    bess_mwh: float = 100,
    **kwargs,
) -> dict:
    """Split boundary into solar and BESS zones, design both."""
    geom = boundary_geojson.get("geometry", boundary_geojson)
    coords = geom["coordinates"][0] if geom["type"] == "Polygon" else geom["coordinates"][0][0]

    cx, cy = _centroid(coords)
    m_lat, m_lon = _metres_per_deg(cy)
    xmin, ymin, xmax, ymax = _bbox(coords)

    # Split: solar takes the main area, BESS takes a rectangular zone at one edge
    split_x = xmin + (xmax - xmin) * solar_fraction

    # Solar zone — left portion
    solar_coords = []
    for lon, lat in coords:
        solar_coords.append([min(lon, split_x), lat])
    solar_geojson = {"type": "Polygon", "coordinates": [solar_coords]}

    # BESS zone — right portion
    bess_coords = [
        [split_x, ymin],
        [xmax, ymin],
        [xmax, ymax],
        [split_x, ymax],
        [split_x, ymin],
    ]
    bess_geojson = {"type": "Polygon", "coordinates": [bess_coords]}

    solar_result = auto_design_solar(solar_geojson, **{k: v for k, v in kwargs.items() if k in auto_design_solar.__code__.co_varnames})
    bess_result = auto_design_bess(bess_geojson, total_mwh=bess_mwh)

    # Combine
    combined = {
        "panels": solar_result["panels"],
        "containers": bess_result["containers"],
        "exclusions": solar_result.get("exclusions", []) + bess_result.get("exclusions", []),
        "roads": solar_result.get("roads", []),
        "infrastructure": solar_result.get("infrastructure", []) + bess_result.get("infrastructure", []),
        "noise_contours": bess_result.get("noise_contours", []),
        "fence": bess_result.get("fence"),
        "tree_screen": bess_result.get("tree_screen"),
        "boundary": coords,
        "solar_zone": solar_coords,
        "bess_zone": bess_coords,
        "metrics": {
            "total_capacity_mwp": solar_result["metrics"]["total_capacity_mwp"],
            "total_capacity_mwh": bess_result["metrics"]["total_capacity_mwh"],
            "area_total_ha": solar_result["metrics"]["area_total_ha"] + bess_result["metrics"]["area_total_ha"],
            "area_used_ha": solar_result["metrics"]["area_used_ha"] + bess_result["metrics"]["area_used_ha"],
            "panel_count": solar_result["metrics"]["panel_count"],
            "container_count": bess_result["metrics"]["container_count"],
            "solar_fraction": solar_fraction,
        },
    }
    return combined


# ---------------------------------------------------------------------------
# CLI / subprocess entry point
# ---------------------------------------------------------------------------

def main():
    """Read JSON from stdin, run design, write JSON to stdout."""
    payload = json.loads(sys.stdin.read())
    technology = payload.get("technology", "solar")
    boundary = payload.get("boundary_geojson")
    params = payload.get("params", {})

    if technology == "solar":
        result = auto_design_solar(boundary, **params)
    elif technology == "bess":
        result = auto_design_bess(boundary, **params)
    elif technology == "hybrid":
        result = auto_design_hybrid(boundary, **params)
    else:
        result = {"error": f"Unknown technology: {technology}"}

    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()

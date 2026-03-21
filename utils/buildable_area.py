"""
Buildable area calculator — determines what portion of a site is actually
developable for solar, BESS, and access infrastructure.

Uses terrain heightmap data (from LiDAR or NASADEM) plus optional constraint
overlays (NDVI, flood zones, building buffers) to compute usable area.

Output:
- Total site area (ha)
- Buildable area (ha) after excluding steep slopes, water, woodland
- Panel-suitable area (ha) — south-facing slopes <10 deg
- BESS-suitable area (ha) — flat areas <5 deg near grid connection
- Access road feasibility
- Slope band breakdown, aspect breakdown, max capacity estimate
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

log = logging.getLogger("princeps.buildable_area")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Slope thresholds (degrees)
SLOPE_FLAT = 2.0
SLOPE_GENTLE = 5.0
SLOPE_MODERATE = 10.0
SLOPE_STEEP = 15.0

# Development constraints
MAX_BUILDABLE_SLOPE_DEG = 15.0       # Exclude >15 deg from buildable
MAX_PANEL_SLOPE_DEG = 10.0           # Panel-suitable: south-facing <10 deg
MAX_BESS_SLOPE_DEG = 5.0             # BESS: flat <5 deg
MAX_ACCESS_ROAD_SLOPE_DEG = 12.0     # HGV access limit ~20%, 12 deg

# Aspect ranges (degrees, clockwise from north)
SOUTH_MIN, SOUTH_MAX = 135.0, 225.0  # South-facing
SE_MIN, SE_MAX = 90.0, 135.0
SW_MIN, SW_MAX = 225.0, 270.0
EAST_MIN, EAST_MAX = 45.0, 135.0
WEST_MIN, WEST_MAX = 225.0, 315.0
NORTH_MIN, NORTH_MAX = 315.0, 45.0   # wraps around 0/360

# NDVI threshold for dense vegetation exclusion
NDVI_DENSE_THRESHOLD = 0.7

# Buffer distances (metres)
BUILDING_NOISE_BUFFER_M = 50.0
BUILDING_VISUAL_BUFFER_M = 200.0

# Capacity density (ha per MW for UK ground-mount solar)
HA_PER_MW_SOLAR = 2.0

# BESS proximity to grid connection (metres)
BESS_GRID_PROXIMITY_M = 500.0


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _compute_slope_aspect(
    heightmap: np.ndarray,
    cell_size_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute slope (degrees) and aspect (degrees CW from north) from DEM.

    Uses numpy gradient (central differences) — equivalent to Horn's method
    on a regular grid.  Returns arrays same shape as input; edge pixels use
    forward/backward differences via numpy's edge handling.
    """
    # Gradient: dy is north-south (row axis), dx is east-west (col axis)
    # Row 0 is north, increasing row index goes south
    dy, dx = np.gradient(heightmap, cell_size_m)

    # Slope magnitude
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    slope_deg = np.degrees(slope_rad)

    # Aspect: atan2(-dy, dx) gives angle from east; convert to CW from north
    # dy is negated because row index increases southward
    aspect_rad = np.arctan2(-dx, dy)  # radians, 0 = north, CW positive
    aspect_deg = np.degrees(aspect_rad) % 360.0

    return slope_deg, aspect_deg


def _classify_slope_bands(slope_deg: np.ndarray) -> dict[str, float]:
    """Return percentage of cells in each slope band."""
    total = slope_deg.size
    if total == 0:
        return {"flat": 0, "gentle": 0, "moderate": 0, "steep": 0, "very_steep": 0}

    flat = np.sum(slope_deg < SLOPE_FLAT)
    gentle = np.sum((slope_deg >= SLOPE_FLAT) & (slope_deg < SLOPE_GENTLE))
    moderate = np.sum((slope_deg >= SLOPE_GENTLE) & (slope_deg < SLOPE_MODERATE))
    steep = np.sum((slope_deg >= SLOPE_MODERATE) & (slope_deg < SLOPE_STEEP))
    very_steep = np.sum(slope_deg >= SLOPE_STEEP)

    return {
        "flat": round(float(flat / total * 100), 1),
        "gentle": round(float(gentle / total * 100), 1),
        "moderate": round(float(moderate / total * 100), 1),
        "steep": round(float(steep / total * 100), 1),
        "very_steep": round(float(very_steep / total * 100), 1),
    }


def _classify_aspect(aspect_deg: np.ndarray) -> dict[str, float]:
    """Return percentage of cells in each aspect quadrant."""
    total = aspect_deg.size
    if total == 0:
        return {"north": 0, "east": 0, "south": 0, "west": 0}

    south = np.sum((aspect_deg >= SOUTH_MIN) & (aspect_deg <= SOUTH_MAX))
    east = np.sum((aspect_deg >= EAST_MIN) & (aspect_deg < SOUTH_MIN))
    west = np.sum((aspect_deg > SOUTH_MAX) & (aspect_deg <= WEST_MAX))
    north = total - south - east - west  # remainder wraps around 0/360

    return {
        "north": round(float(north / total * 100), 1),
        "east": round(float(east / total * 100), 1),
        "south": round(float(south / total * 100), 1),
        "west": round(float(west / total * 100), 1),
    }


def _build_constraint_mask(
    slope_deg: np.ndarray,
    aspect_deg: np.ndarray,
    cell_size_m: float,
    *,
    ndvi_grid: np.ndarray | None = None,
    flood_mask: np.ndarray | None = None,
    building_mask: np.ndarray | None = None,
    building_buffer_m: float = BUILDING_NOISE_BUFFER_M,
) -> tuple[np.ndarray, list[str]]:
    """Build boolean mask of excluded cells.  True = excluded.

    Returns (exclusion_mask, list_of_constraint_names_applied).
    """
    excluded = np.zeros_like(slope_deg, dtype=bool)
    constraints: list[str] = []

    # 1. Slope >15 deg
    steep = slope_deg > MAX_BUILDABLE_SLOPE_DEG
    if np.any(steep):
        excluded |= steep
        constraints.append(f"slope_gt_{MAX_BUILDABLE_SLOPE_DEG:.0f}deg")

    # 2. Dense vegetation (NDVI > 0.7)
    if ndvi_grid is not None:
        ndvi_arr = np.asarray(ndvi_grid, dtype=float)
        if ndvi_arr.shape == slope_deg.shape:
            dense = ndvi_arr > NDVI_DENSE_THRESHOLD
            if np.any(dense):
                excluded |= dense
                constraints.append(f"ndvi_gt_{NDVI_DENSE_THRESHOLD}")
        else:
            log.warning(
                "NDVI grid shape %s != heightmap shape %s — skipping",
                ndvi_arr.shape, slope_deg.shape,
            )

    # 3. Flood zones
    if flood_mask is not None:
        flood_arr = np.asarray(flood_mask, dtype=bool)
        if flood_arr.shape == slope_deg.shape:
            if np.any(flood_arr):
                excluded |= flood_arr
                constraints.append("flood_zone")
        else:
            log.warning(
                "Flood mask shape %s != heightmap shape %s — skipping",
                flood_arr.shape, slope_deg.shape,
            )

    # 4. Building buffer
    if building_mask is not None:
        bld_arr = np.asarray(building_mask, dtype=bool)
        if bld_arr.shape == slope_deg.shape:
            buffer_px = max(1, int(building_buffer_m / cell_size_m))
            # Dilate building mask by buffer distance
            buffered = _dilate_mask(bld_arr, buffer_px)
            if np.any(buffered):
                excluded |= buffered
                constraints.append(f"building_buffer_{building_buffer_m:.0f}m")
        else:
            log.warning(
                "Building mask shape %s != heightmap shape %s — skipping",
                bld_arr.shape, slope_deg.shape,
            )

    if not constraints:
        constraints.append("slope_only")

    return excluded, constraints


def _dilate_mask(mask: np.ndarray, radius_px: int) -> np.ndarray:
    """Binary dilation using a circular structuring element (pure numpy)."""
    if radius_px <= 0:
        return mask.copy()

    y, x = np.ogrid[-radius_px:radius_px + 1, -radius_px:radius_px + 1]
    kernel = (x**2 + y**2) <= radius_px**2

    rows, cols = mask.shape
    out = np.zeros_like(mask)

    # Pad to handle edges
    padded = np.pad(mask, radius_px, mode="constant", constant_values=False)
    for dy in range(-radius_px, radius_px + 1):
        for dx in range(-radius_px, radius_px + 1):
            if kernel[dy + radius_px, dx + radius_px]:
                shifted = padded[
                    radius_px + dy: radius_px + dy + rows,
                    radius_px + dx: radius_px + dx + cols,
                ]
                out |= shifted

    return out


def _assess_access_road(
    slope_deg: np.ndarray,
    cell_size_m: float,
) -> dict[str, Any]:
    """Assess whether an access road can reach the site interior.

    Uses a simple heuristic: checks if a path of cells with slope <12 deg
    can be found from any edge to the centre of the grid (BFS on the
    traversable mask).
    """
    traversable = slope_deg <= MAX_ACCESS_ROAD_SLOPE_DEG
    rows, cols = slope_deg.shape
    centre = (rows // 2, cols // 2)

    # BFS from all edge cells
    from collections import deque
    visited = np.zeros_like(traversable, dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    # Seed from all traversable edge cells
    for r in range(rows):
        for c in [0, cols - 1]:
            if traversable[r, c]:
                queue.append((r, c))
                visited[r, c] = True
    for c in range(cols):
        for r in [0, rows - 1]:
            if traversable[r, c] and not visited[r, c]:
                queue.append((r, c))
                visited[r, c] = True

    # BFS
    while queue:
        r, c = queue.popleft()
        if (r, c) == centre:
            return {
                "feasible": True,
                "max_road_slope_deg": MAX_ACCESS_ROAD_SLOPE_DEG,
                "note": "Access road can reach site centre within slope limits.",
            }
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and not visited[nr, nc] and traversable[nr, nc]:
                visited[nr, nc] = True
                queue.append((nr, nc))

    # Check how far we got
    reachable_pct = float(np.sum(visited) / traversable.size * 100)

    return {
        "feasible": False,
        "max_road_slope_deg": MAX_ACCESS_ROAD_SLOPE_DEG,
        "reachable_from_edge_pct": round(reachable_pct, 1),
        "note": (
            "No low-gradient path from site edge to centre. "
            "Significant earthworks or alternative access route required."
        ),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def calculate_buildable_area(
    heightmap_values: list[list[float]],
    cell_size_m: float,
    *,
    ndvi_grid: list[list[float]] | None = None,
    flood_mask: list[list[bool]] | None = None,
    building_mask: list[list[bool]] | None = None,
    building_buffer_m: float = BUILDING_NOISE_BUFFER_M,
    grid_connection_point: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Calculate buildable area from a heightmap grid.

    Parameters
    ----------
    heightmap_values : 2D list of elevations (metres)
    cell_size_m : ground resolution per pixel (metres)
    ndvi_grid : optional 2D NDVI values (same shape as heightmap)
    flood_mask : optional 2D boolean flood zone mask
    building_mask : optional 2D boolean mask of building locations
    building_buffer_m : buffer distance from buildings (default 50m)
    grid_connection_point : optional (row, col) of nearest grid connection
        for BESS proximity calculation; defaults to grid centre.

    Returns
    -------
    dict with buildable area breakdown, slope/aspect analysis, capacity estimate.
    """
    dem = np.asarray(heightmap_values, dtype=float)
    rows, cols = dem.shape
    total_cells = rows * cols
    cell_area_m2 = cell_size_m * cell_size_m
    total_area_m2 = total_cells * cell_area_m2
    total_area_ha = total_area_m2 / 10_000.0

    # --- Slope & aspect ---
    slope_deg, aspect_deg = _compute_slope_aspect(dem, cell_size_m)

    slope_bands = _classify_slope_bands(slope_deg)
    aspect_breakdown = _classify_aspect(aspect_deg)

    # --- Constraint mask ---
    ndvi_arr = np.asarray(ndvi_grid, dtype=float) if ndvi_grid is not None else None
    flood_arr = np.asarray(flood_mask, dtype=bool) if flood_mask is not None else None
    bld_arr = np.asarray(building_mask, dtype=bool) if building_mask is not None else None

    excluded, constraints = _build_constraint_mask(
        slope_deg, aspect_deg, cell_size_m,
        ndvi_grid=ndvi_arr,
        flood_mask=flood_arr,
        building_mask=bld_arr,
        building_buffer_m=building_buffer_m,
    )

    buildable = ~excluded
    buildable_cells = int(np.sum(buildable))
    buildable_area_ha = buildable_cells * cell_area_m2 / 10_000.0
    buildable_pct = buildable_cells / total_cells * 100 if total_cells > 0 else 0.0

    # --- Panel-suitable: south-facing + slope <10 deg + not excluded ---
    south_facing = (aspect_deg >= SOUTH_MIN) & (aspect_deg <= SOUTH_MAX)
    panel_ok = buildable & south_facing & (slope_deg < MAX_PANEL_SLOPE_DEG)
    panel_cells = int(np.sum(panel_ok))
    panel_area_ha = panel_cells * cell_area_m2 / 10_000.0

    # --- BESS-suitable: flat <5 deg + not excluded + near grid connection ---
    flat_ok = buildable & (slope_deg < MAX_BESS_SLOPE_DEG)

    if grid_connection_point is not None:
        gc_r, gc_c = grid_connection_point
    else:
        gc_r, gc_c = rows // 2, cols // 2

    # Distance mask: within BESS_GRID_PROXIMITY_M of grid connection point
    rr, cc = np.mgrid[0:rows, 0:cols]
    dist_to_gc = np.sqrt(((rr - gc_r) * cell_size_m) ** 2 + ((cc - gc_c) * cell_size_m) ** 2)
    bess_ok = flat_ok & (dist_to_gc <= BESS_GRID_PROXIMITY_M)
    bess_cells = int(np.sum(bess_ok))
    bess_area_ha = bess_cells * cell_area_m2 / 10_000.0

    # --- Access road feasibility ---
    access = _assess_access_road(slope_deg, cell_size_m)

    # --- Max capacity estimate ---
    max_capacity_mw = panel_area_ha / HA_PER_MW_SOLAR if panel_area_ha > 0 else 0.0

    # --- Slope statistics ---
    slope_stats = {
        "mean_deg": round(float(np.mean(slope_deg)), 2),
        "max_deg": round(float(np.max(slope_deg)), 2),
        "min_deg": round(float(np.min(slope_deg)), 2),
        "std_deg": round(float(np.std(slope_deg)), 2),
        "median_deg": round(float(np.median(slope_deg)), 2),
    }

    # --- Elevation statistics ---
    elev_stats = {
        "mean_m": round(float(np.mean(dem)), 2),
        "min_m": round(float(np.min(dem)), 2),
        "max_m": round(float(np.max(dem)), 2),
        "range_m": round(float(np.ptp(dem)), 2),
    }

    return {
        "total_area_ha": round(total_area_ha, 3),
        "buildable_area_ha": round(buildable_area_ha, 3),
        "buildable_pct": round(buildable_pct, 1),
        "panel_suitable_ha": round(panel_area_ha, 3),
        "bess_suitable_ha": round(bess_area_ha, 3),
        "max_capacity_mw": round(max_capacity_mw, 2),
        "slope_bands": slope_bands,
        "aspect_breakdown": aspect_breakdown,
        "slope_stats": slope_stats,
        "elevation": elev_stats,
        "access_road": access,
        "constraints_applied": constraints,
        "excluded_pct": round(100.0 - buildable_pct, 1),
        "grid_size": {"rows": rows, "cols": cols},
        "cell_size_m": cell_size_m,
    }


# ---------------------------------------------------------------------------
# Async wrapper for use from endpoints
# ---------------------------------------------------------------------------

async def compute_buildable_area(
    lat: float,
    lon: float,
    radius_m: float = 500,
    *,
    ndvi_grid: list[list[float]] | None = None,
    flood_mask: list[list[bool]] | None = None,
    building_mask: list[list[bool]] | None = None,
    building_buffer_m: float = BUILDING_NOISE_BUFFER_M,
    grid_connection_point: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Fetch terrain data then calculate buildable area.

    Calls the LiDAR terrain endpoint internally, then runs the buildable
    area calculation on the returned heightmap.
    """
    import asyncio
    from utils.lidar_terrain import fetch_lidar_terrain

    terrain = await fetch_lidar_terrain(lat, lon, radius_m=radius_m, resolution_m=2)

    if "error" in terrain:
        return terrain

    heightmap = terrain.get("heightmap", {})
    values = heightmap.get("values")
    cell_size = heightmap.get("resolution_m", 2.0)

    if not values or not isinstance(values, list) or not values[0]:
        return {"error": "No heightmap data returned from terrain service"}

    # Run CPU-bound calculation in thread pool
    result = await asyncio.to_thread(
        calculate_buildable_area,
        values,
        cell_size,
        ndvi_grid=ndvi_grid,
        flood_mask=flood_mask,
        building_mask=building_mask,
        building_buffer_m=building_buffer_m,
        grid_connection_point=grid_connection_point,
    )

    result["source"] = terrain.get("source", "unknown")
    result["lat"] = lat
    result["lon"] = lon
    result["radius_m"] = radius_m

    return result

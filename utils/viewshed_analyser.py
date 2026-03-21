"""
Visual impact and viewshed analysis for energy developments.

Provides:
- Photomontage camera parameter generation for 3D rendering
- Zone of Theoretical Visibility (ZTV) estimation
- Visual impact magnitude scoring per Landscape Institute GLVIA3
- DEM-based viewshed calculation (WhiteboxTools or numpy fallback)
- Hydrological analysis: TWI, flow accumulation, drainage risk

Standard UK planning methodology:
- Observer height: 1.6m (eye level)
- Target height: panel tip (3m solar), hub height (80-150m wind)
- Study area: 2km radius (solar), 5km (wind), 10km (wind >50m hub)
- Output: ZTV polygon GeoJSON for map overlay

Used for UK planning applications (LVIA — Landscape & Visual Impact Assessment).
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("princeps.viewshed")

# Temp directory for raster I/O
TEMP_DIR = Path("/tmp/princeps-terrain")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Earth radius for curvature correction (metres)
EARTH_RADIUS_M = 6_371_000.0

# Standard atmospheric refraction coefficient
REFRACTION_COEFF = 0.13


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points."""
    r = EARTH_RADIUS_M
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing (degrees, 0=N, clockwise) from point 1 to point 2."""
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _earth_curvature_drop(distance_m: float) -> float:
    """
    Calculate earth curvature drop at a given distance.

    Corrected for standard atmospheric refraction (k=0.13).
    Drop = d^2 / (2R) * (1 - k)
    """
    return (distance_m ** 2) / (2.0 * EARTH_RADIUS_M) * (1.0 - REFRACTION_COEFF)


def generate_photomontage_camera(
    site_lat: float,
    site_lon: float,
    viewpoint_lat: float,
    viewpoint_lon: float,
    target_height_m: float = 80.0,
    viewpoint_elevation_m: float = 0.0,
    site_elevation_m: float = 0.0,
    sensor_width_mm: float = 36.0,
    focal_length_mm: float = 50.0,
) -> dict[str, Any]:
    """
    Generate Three.js / deck.gl camera parameters for photomontage rendering.

    Computes camera position, look-at target, field of view, and perspective
    parameters that match a real-world viewpoint looking at a development site.

    Parameters
    ----------
    site_lat, site_lon : float
        WGS84 coordinates of the development centre.
    viewpoint_lat, viewpoint_lon : float
        WGS84 coordinates of the viewpoint (camera position).
    target_height_m : float
        Height of the tallest structure at the site (e.g., turbine hub height).
    viewpoint_elevation_m : float
        Ground elevation at the viewpoint (metres AOD).
    site_elevation_m : float
        Ground elevation at the site (metres AOD).
    sensor_width_mm : float
        Camera sensor width for FOV calculation (36mm = full frame).
    focal_length_mm : float
        Lens focal length in mm (50mm standard).

    Returns
    -------
    dict with camera config for Three.js / deck.gl rendering.
    """
    # Distance and bearing
    distance_m = _haversine_distance(site_lat, site_lon, viewpoint_lat, viewpoint_lon)
    bearing_deg = _bearing(viewpoint_lat, viewpoint_lon, site_lat, site_lon)

    # Earth curvature drop
    curvature_drop_m = _earth_curvature_drop(distance_m)

    # Effective height difference (viewpoint to target top)
    # Positive = target is above viewpoint
    height_diff = (site_elevation_m + target_height_m) - viewpoint_elevation_m - curvature_drop_m

    # Vertical angle from viewpoint to target top (degrees)
    vertical_angle_deg = math.degrees(math.atan2(height_diff, distance_m))

    # Horizontal FOV (degrees)
    fov_horizontal = 2.0 * math.degrees(math.atan(sensor_width_mm / (2.0 * focal_length_mm)))
    # Vertical FOV (assuming 3:2 aspect ratio)
    fov_vertical = fov_horizontal * (2.0 / 3.0)

    # Angular size of the target (apparent height in degrees)
    apparent_height_deg = math.degrees(math.atan2(target_height_m, distance_m))

    # Camera position in local coordinate system (metres from site centre)
    dx = distance_m * math.sin(math.radians(bearing_deg + 180))  # reverse bearing
    dy = distance_m * math.cos(math.radians(bearing_deg + 180))

    # Three.js camera parameters
    camera_config = {
        "type": "PerspectiveCamera",
        "fov": round(fov_vertical, 2),
        "aspect": 1.5,  # 3:2
        "near": 1.0,
        "far": max(50000, distance_m * 3),
        "position": {
            "x": round(dx, 1),
            "y": round(viewpoint_elevation_m + 1.65, 1),  # eye height
            "z": round(dy, 1),
        },
        "lookAt": {
            "x": 0.0,
            "y": round(site_elevation_m + target_height_m / 2.0, 1),
            "z": 0.0,
        },
        "up": {"x": 0.0, "y": 1.0, "z": 0.0},
    }

    # deck.gl viewState
    deck_view_state = {
        "longitude": viewpoint_lon,
        "latitude": viewpoint_lat,
        "zoom": _distance_to_zoom(distance_m),
        "pitch": max(0, min(85, -vertical_angle_deg + 10)),
        "bearing": bearing_deg,
    }

    # Visual impact magnitude (GLVIA3 guidelines)
    if distance_m < 500:
        magnitude = "Major"
        magnitude_score = 5
    elif distance_m < 2000:
        magnitude = "Moderate"
        magnitude_score = 3
    elif distance_m < 5000:
        magnitude = "Minor"
        magnitude_score = 2
    else:
        magnitude = "Negligible"
        magnitude_score = 1

    # Proportion of view occupied
    view_proportion_pct = round(apparent_height_deg / fov_vertical * 100, 1)

    return {
        "camera_threejs": camera_config,
        "view_state_deckgl": deck_view_state,
        "geometry": {
            "distance_m": round(distance_m, 1),
            "distance_km": round(distance_m / 1000, 2),
            "bearing_deg": round(bearing_deg, 1),
            "vertical_angle_deg": round(vertical_angle_deg, 2),
            "curvature_drop_m": round(curvature_drop_m, 2),
            "height_difference_m": round(height_diff, 1),
        },
        "optics": {
            "focal_length_mm": focal_length_mm,
            "sensor_width_mm": sensor_width_mm,
            "fov_horizontal_deg": round(fov_horizontal, 1),
            "fov_vertical_deg": round(fov_vertical, 1),
        },
        "visual_impact": {
            "magnitude": magnitude,
            "magnitude_score": magnitude_score,
            "apparent_height_deg": round(apparent_height_deg, 3),
            "view_proportion_pct": view_proportion_pct,
            "target_height_m": target_height_m,
        },
        "viewpoint": {
            "lat": viewpoint_lat,
            "lon": viewpoint_lon,
            "elevation_m": viewpoint_elevation_m,
        },
        "site": {
            "lat": site_lat,
            "lon": site_lon,
            "elevation_m": site_elevation_m,
        },
    }


def _distance_to_zoom(distance_m: float) -> float:
    """Approximate Mapbox zoom level for a given viewing distance."""
    if distance_m <= 0:
        return 18
    # At zoom 0, one tile covers ~40075 km
    # Each zoom level halves the ground distance per pixel
    # For a 512px viewport, pixels per metre at zoom z = 2^z * 512 / 40075000
    # We want the target to occupy roughly 1/3 of the viewport
    target_pixels = 170  # ~1/3 of 512
    pixels_per_m_needed = target_pixels / distance_m
    zoom = math.log2(pixels_per_m_needed * 40_075_000 / 512)
    return round(max(1, min(20, zoom)), 1)


def estimate_ztv_radius(
    target_height_m: float,
    observer_height_m: float = 1.65,
    terrain_screen_angle_deg: float = 0.0,
) -> float:
    """
    Estimate the maximum Zone of Theoretical Visibility radius.

    Based on geometric visibility accounting for earth curvature and
    standard atmospheric refraction.

    Parameters
    ----------
    target_height_m : float
        Height of the structure (e.g., turbine tip height).
    observer_height_m : float
        Observer eye height (default 1.65m standing).
    terrain_screen_angle_deg : float
        Average terrain screening angle (0 = flat).

    Returns
    -------
    float : Maximum visibility distance in metres.
    """
    # Geometric horizon distance for observer
    d_observer = math.sqrt(2 * EARTH_RADIUS_M * observer_height_m / (1 - REFRACTION_COEFF))

    # Geometric horizon distance for target
    d_target = math.sqrt(2 * EARTH_RADIUS_M * target_height_m / (1 - REFRACTION_COEFF))

    max_distance = d_observer + d_target

    # Reduce for terrain screening
    if terrain_screen_angle_deg > 0:
        screen_reduction = 1.0 - min(0.9, terrain_screen_angle_deg / 10.0)
        max_distance *= screen_reduction

    return round(max_distance, 0)


def assess_visual_impact(
    site_lat: float,
    site_lon: float,
    target_height_m: float,
    viewpoints: list[dict[str, Any]],
    site_elevation_m: float = 0.0,
) -> dict[str, Any]:
    """
    Assess visual impact from multiple viewpoints (GLVIA3 methodology).

    Parameters
    ----------
    site_lat, site_lon : float
        Development site centre.
    target_height_m : float
        Maximum structure height.
    viewpoints : list of dict
        Each with: lat, lon, name, sensitivity (high/medium/low), elevation_m.

    Returns
    -------
    dict with per-viewpoint assessments and overall impact rating.
    """
    ztv_radius = estimate_ztv_radius(target_height_m)

    assessments = []
    for vp in viewpoints:
        distance_m = _haversine_distance(site_lat, site_lon, vp["lat"], vp["lon"])
        bearing_deg = _bearing(vp["lat"], vp["lon"], site_lat, site_lon)

        # Check if within ZTV
        if distance_m > ztv_radius:
            assessments.append({
                "name": vp.get("name", "Viewpoint"),
                "distance_km": round(distance_m / 1000, 2),
                "visible": False,
                "magnitude": "None",
                "significance": "None",
            })
            continue

        # Apparent height
        vp_elev = vp.get("elevation_m", 0.0)
        curvature_drop = _earth_curvature_drop(distance_m)
        effective_height = (
            site_elevation_m + target_height_m - vp_elev - curvature_drop
        )
        apparent_deg = math.degrees(math.atan2(max(0, effective_height), distance_m))

        # Magnitude
        if distance_m < 500:
            magnitude = "Major"
            mag_score = 5
        elif distance_m < 2000:
            magnitude = "Moderate"
            mag_score = 3
        elif distance_m < 5000:
            magnitude = "Minor"
            mag_score = 2
        else:
            magnitude = "Negligible"
            mag_score = 1

        # Sensitivity
        sensitivity = vp.get("sensitivity", "medium")
        sens_map = {"high": 5, "medium": 3, "low": 1}
        sens_score = sens_map.get(sensitivity, 3)

        # Significance = magnitude x sensitivity (GLVIA3 matrix)
        sig_score = mag_score * sens_score
        if sig_score >= 15:
            significance = "Major Adverse"
        elif sig_score >= 9:
            significance = "Moderate Adverse"
        elif sig_score >= 3:
            significance = "Minor Adverse"
        else:
            significance = "Negligible"

        assessments.append({
            "name": vp.get("name", "Viewpoint"),
            "lat": vp["lat"],
            "lon": vp["lon"],
            "distance_km": round(distance_m / 1000, 2),
            "bearing_deg": round(bearing_deg, 1),
            "visible": True,
            "apparent_height_deg": round(apparent_deg, 3),
            "magnitude": magnitude,
            "magnitude_score": mag_score,
            "sensitivity": sensitivity,
            "sensitivity_score": sens_score,
            "significance": significance,
            "significance_score": sig_score,
        })

    # Overall worst-case
    visible_assessments = [a for a in assessments if a.get("visible")]
    if visible_assessments:
        worst = max(visible_assessments, key=lambda a: a.get("significance_score", 0))
        overall = worst["significance"]
    else:
        overall = "No significant visual impact"

    return {
        "site": {"lat": site_lat, "lon": site_lon, "target_height_m": target_height_m},
        "ztv_radius_km": round(ztv_radius / 1000, 1),
        "viewpoints_assessed": len(assessments),
        "viewpoints_with_visibility": len(visible_assessments),
        "assessments": assessments,
        "overall_visual_impact": overall,
        "methodology": "GLVIA3 (Landscape Institute, 2013)",
    }


# ---------------------------------------------------------------------------
# WhiteboxTools availability check
# ---------------------------------------------------------------------------

def _whitebox_available() -> bool:
    """Check if WhiteboxTools Python package is installed."""
    try:
        import whitebox
        return True
    except ImportError:
        return False


def _write_geotiff(data: np.ndarray, filepath: str, lat: float, lon: float, resolution_m: float) -> bool:
    """Write a 2D numpy array as a single-band GeoTIFF using rasterio if available."""
    try:
        import rasterio
        from rasterio.transform import from_bounds

        h, w = data.shape
        half_extent_deg = (resolution_m * max(h, w) / 2) / 111320

        west = lon - half_extent_deg
        east = lon + half_extent_deg
        south = lat - half_extent_deg
        north = lat + half_extent_deg

        transform = from_bounds(west, south, east, north, w, h)

        with rasterio.open(
            filepath, "w",
            driver="GTiff",
            height=h, width=w,
            count=1,
            dtype=data.dtype,
            crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(data, 1)
        return True
    except ImportError:
        np.save(filepath.replace(".tif", ".npy"), data)
        return False


def _read_raster(filepath: str) -> np.ndarray | None:
    """Read a raster file to numpy array."""
    try:
        import rasterio
        with rasterio.open(filepath) as src:
            return src.read(1)
    except ImportError:
        npy_path = filepath.replace(".tif", ".npy")
        if os.path.exists(npy_path):
            return np.load(npy_path)
    return None


# ---------------------------------------------------------------------------
# Viewshed — WhiteboxTools implementation
# ---------------------------------------------------------------------------

async def _viewshed_whitebox(
    dem_array: np.ndarray, lat: float, lon: float,
    target_height_m: float, observer_height_m: float, resolution_m: float,
) -> dict:
    """Calculate viewshed using WhiteboxTools."""
    import whitebox

    wbt = whitebox.WhiteboxTools()
    wbt.set_verbose_mode(False)
    wbt.set_working_dir(str(TEMP_DIR))

    dem_path = str(TEMP_DIR / "dem_viewshed.tif")
    output_path = str(TEMP_DIR / "viewshed_out.tif")

    if not _write_geotiff(dem_array, dem_path, lat, lon, resolution_m):
        return {"error": "Could not write GeoTIFF (rasterio not installed)"}

    h, w = dem_array.shape
    centre_row = h // 2
    centre_col = w // 2

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: wbt.viewshed(
            dem_path, output_path,
            [centre_col], [centre_row],
            height=target_height_m,
        ))
    except Exception as e:
        log.warning("WhiteboxTools viewshed failed: %s — using fallback", e)
        return await _viewshed_fallback(dem_array, target_height_m, observer_height_m, resolution_m)

    result_array = _read_raster(output_path)
    if result_array is None:
        return {"error": "Failed to read viewshed output"}

    visible_pixels = int(np.count_nonzero(result_array > 0))
    total_pixels = int(result_array.size)
    visible_pct = round(visible_pixels / total_pixels * 100, 1) if total_pixels > 0 else 0

    pixel_area_m2 = resolution_m * resolution_m
    visible_area_ha = round(visible_pixels * pixel_area_m2 / 10000, 2)
    total_area_ha = round(total_pixels * pixel_area_m2 / 10000, 2)

    ztv_geojson = _viewshed_to_geojson(result_array, lat, lon, resolution_m)
    receptor_estimate = int(visible_area_ha * 5)

    for f in [dem_path, output_path]:
        try:
            os.remove(f)
        except OSError:
            pass

    return {
        "visible_area_pct": visible_pct,
        "visible_area_ha": visible_area_ha,
        "total_area_ha": total_area_ha,
        "ztv_geojson": ztv_geojson,
        "receptor_count_estimate": receptor_estimate,
        "method": "WhiteboxTools",
        "target_height_m": target_height_m,
        "observer_height_m": observer_height_m,
    }


# ---------------------------------------------------------------------------
# Viewshed — numpy ray-casting fallback
# ---------------------------------------------------------------------------

async def _viewshed_fallback(
    dem_array: np.ndarray, target_height_m: float, observer_height_m: float,
    resolution_m: float,
) -> dict:
    """Simplified viewshed using numpy ray-casting."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, _compute_viewshed_numpy, dem_array, target_height_m, observer_height_m, resolution_m,
    )
    return result


def _compute_viewshed_numpy(
    dem: np.ndarray, target_height_m: float, observer_height_m: float,
    resolution_m: float,
) -> dict:
    """Pure numpy viewshed via ray-casting from centre pixel.

    From the development location (centre), cast rays to all edge pixels.
    Along each ray, track the maximum elevation angle seen so far.
    A pixel is visible if its elevation angle exceeds all previous angles.
    """
    h, w = dem.shape
    cy, cx = h // 2, w // 2
    target_elev = dem[cy, cx] + target_height_m

    visibility = np.zeros((h, w), dtype=np.uint8)
    visibility[cy, cx] = 1

    edge_pixels = set()
    for x in range(w):
        edge_pixels.add((0, x))
        edge_pixels.add((h - 1, x))
    for y in range(h):
        edge_pixels.add((y, 0))
        edge_pixels.add((y, w - 1))

    for ey, ex in edge_pixels:
        _trace_ray_vis(dem, visibility, cy, cx, ey, ex, target_elev, observer_height_m, resolution_m)

    visible_pixels = int(np.count_nonzero(visibility))
    total_pixels = int(visibility.size)
    visible_pct = round(visible_pixels / total_pixels * 100, 1) if total_pixels > 0 else 0

    pixel_area_m2 = resolution_m * resolution_m
    visible_area_ha = round(visible_pixels * pixel_area_m2 / 10000, 2)
    total_area_ha = round(total_pixels * pixel_area_m2 / 10000, 2)
    receptor_estimate = int(visible_area_ha * 5)

    return {
        "visible_area_pct": visible_pct,
        "visible_area_ha": visible_area_ha,
        "total_area_ha": total_area_ha,
        "ztv_geojson": None,
        "receptor_count_estimate": receptor_estimate,
        "method": "numpy_raycasting",
        "target_height_m": target_height_m,
        "observer_height_m": observer_height_m,
    }


def _trace_ray_vis(
    dem: np.ndarray, visibility: np.ndarray,
    cy: int, cx: int, ey: int, ex: int,
    target_elev: float, observer_height: float, resolution_m: float,
):
    """Trace a single ray from centre to edge using Bresenham-like stepping."""
    dy = ey - cy
    dx = ex - cx
    steps = max(abs(dy), abs(dx))
    if steps == 0:
        return

    y_step = dy / steps
    x_step = dx / steps
    max_angle = -math.inf

    for i in range(1, steps + 1):
        py = int(round(cy + y_step * i))
        px = int(round(cx + x_step * i))

        if py < 0 or py >= dem.shape[0] or px < 0 or px >= dem.shape[1]:
            break

        dist_m = math.sqrt((py - cy) ** 2 + (px - cx) ** 2) * resolution_m
        if dist_m < 0.01:
            continue

        observer_elev = dem[py, px] + observer_height
        angle = math.atan2(observer_elev - target_elev, dist_m)

        if angle > max_angle:
            max_angle = angle
            visibility[py, px] = 1


def _viewshed_to_geojson(
    visibility: np.ndarray, lat: float, lon: float, resolution_m: float,
) -> dict:
    """Convert visibility raster to simplified GeoJSON polygon."""
    h, w = visibility.shape
    half_extent_deg = (resolution_m * max(h, w) / 2) / 111320

    west = lon - half_extent_deg
    east = lon + half_extent_deg
    south = lat - half_extent_deg
    north = lat + half_extent_deg

    visible_rows, visible_cols = np.where(visibility > 0)
    if len(visible_rows) == 0:
        return {"type": "FeatureCollection", "features": []}

    angles = np.linspace(0, 2 * math.pi, 36, endpoint=False)
    boundary_points = []
    cy, cx = h // 2, w // 2

    for angle in angles:
        max_dist = 0
        for d in range(1, max(h, w)):
            py = int(round(cy + d * math.sin(angle)))
            px = int(round(cx + d * math.cos(angle)))
            if 0 <= py < h and 0 <= px < w and visibility[py, px] > 0:
                max_dist = d
            elif max_dist > 0:
                break

        if max_dist > 0:
            py_f = cy + max_dist * math.sin(angle)
            px_f = cx + max_dist * math.cos(angle)
            frac_x = px_f / w
            frac_y = 1.0 - (py_f / h)
            pt_lon = west + frac_x * (east - west)
            pt_lat = south + frac_y * (north - south)
            boundary_points.append([round(pt_lon, 6), round(pt_lat, 6)])

    if len(boundary_points) < 3:
        return {"type": "FeatureCollection", "features": []}

    boundary_points.append(boundary_points[0])

    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "zone": "visible",
                "visible_pct": round(np.count_nonzero(visibility) / visibility.size * 100, 1),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [boundary_points],
            },
        }],
    }


# ---------------------------------------------------------------------------
# Public API: DEM-based viewshed
# ---------------------------------------------------------------------------

async def calculate_viewshed(
    lat: float, lon: float, *,
    target_height_m: float = 3.0,
    radius_m: float = 2000,
    observer_height_m: float = 1.6,
    dem_data: dict | None = None,
) -> dict:
    """Calculate Zone of Theoretical Visibility (ZTV) for a proposed development.

    Parameters:
        lat, lon: Site location
        target_height_m: Height of proposed structure (3m solar panels, 80-150m wind)
        radius_m: Study area radius (2km solar, 5-10km wind)
        observer_height_m: Eye-level height (1.6m standard)
        dem_data: Pre-fetched DEM data dict with 'heightmap.values'. If None, fetches LiDAR.

    Returns:
        ZTV analysis with visible area percentage, area in hectares,
        GeoJSON polygon for map overlay, and receptor count estimate.
    """
    if dem_data is None:
        from utils.lidar_terrain import fetch_lidar_terrain
        dem_data = await fetch_lidar_terrain(lat, lon, radius_m=radius_m, resolution_m=5)

    if "error" in dem_data:
        return {"error": f"Could not fetch terrain data: {dem_data['error']}"}

    heightmap = dem_data.get("heightmap", {})
    values = heightmap.get("values", [])
    resolution_m = heightmap.get("resolution_m", 5)

    if not values:
        return {"error": "No heightmap data available"}

    dem_array = np.array(values, dtype=np.float64)

    if _whitebox_available():
        result = await _viewshed_whitebox(
            dem_array, lat, lon, target_height_m, observer_height_m, resolution_m,
        )
    else:
        result = await _viewshed_fallback(
            dem_array, target_height_m, observer_height_m, resolution_m,
        )
        if result.get("ztv_geojson") is None:
            vis = np.zeros_like(dem_array, dtype=np.uint8)
            h, w = dem_array.shape
            cy, cx = h // 2, w // 2
            target_elev = dem_array[cy, cx] + target_height_m
            edge_pixels = set()
            for x in range(w):
                edge_pixels.add((0, x))
                edge_pixels.add((h - 1, x))
            for y in range(h):
                edge_pixels.add((y, 0))
                edge_pixels.add((y, w - 1))
            for ey, ex in edge_pixels:
                _trace_ray_vis(dem_array, vis, cy, cx, ey, ex, target_elev, observer_height_m, resolution_m)
            result["ztv_geojson"] = _viewshed_to_geojson(vis, lat, lon, resolution_m)

    result["lat"] = lat
    result["lon"] = lon
    result["radius_m"] = radius_m

    visible_pct = result.get("visible_area_pct", 0)
    if visible_pct < 10:
        result["visual_impact"] = "LOW"
        result["visual_note"] = "Minimal visibility. Limited visual impact expected."
    elif visible_pct < 30:
        result["visual_impact"] = "MODERATE"
        result["visual_note"] = "Moderate visibility. Landscape screening may be beneficial."
    elif visible_pct < 60:
        result["visual_impact"] = "HIGH"
        result["visual_note"] = "Significant visibility. Mitigation measures recommended."
    else:
        result["visual_impact"] = "VERY HIGH"
        result["visual_note"] = "Extensively visible. Full LVIA required."

    return result


# ---------------------------------------------------------------------------
# Hydrology analysis
# ---------------------------------------------------------------------------

async def calculate_hydrology(
    lat: float, lon: float, radius_m: float = 500,
    dem_data: dict | None = None,
) -> dict:
    """Hydrological analysis from DEM data.

    Computes:
    - Topographic Wetness Index (TWI = ln(contributing_area / tan(slope)))
    - Flow accumulation (identifies drainage paths)
    - Depression / waterlogging risk areas
    - Flood/drainage risk classification

    Parameters:
        lat, lon: Site location
        radius_m: Study area radius
        dem_data: Pre-fetched DEM dict with heightmap. If None, fetches LiDAR.
    """
    if dem_data is None:
        from utils.lidar_terrain import fetch_lidar_terrain
        dem_data = await fetch_lidar_terrain(lat, lon, radius_m=radius_m, resolution_m=2)

    if "error" in dem_data:
        return {"error": f"Could not fetch terrain data: {dem_data['error']}"}

    heightmap = dem_data.get("heightmap", {})
    values = heightmap.get("values", [])
    resolution_m_actual = heightmap.get("resolution_m", 2)

    if not values:
        return {"error": "No heightmap data available"}

    dem = np.array(values, dtype=np.float64)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, _compute_hydrology, dem, lat, lon, resolution_m_actual, radius_m,
    )
    return result


def _compute_hydrology(
    dem: np.ndarray, lat: float, lon: float, resolution_m: float, radius_m: float,
) -> dict:
    """Pure numpy hydrological analysis: slope, D8 flow direction, flow accumulation, TWI."""
    h, w = dem.shape
    if h < 3 or w < 3:
        return {"error": "DEM too small for hydrological analysis"}

    pixel_area = resolution_m * resolution_m

    # Slope
    dy, dx = np.gradient(dem, resolution_m)
    slope_rad = np.arctan(np.sqrt(dx ** 2 + dy ** 2))
    slope_deg = np.degrees(slope_rad)

    tan_slope = np.tan(slope_rad)
    tan_slope = np.where(tan_slope < 0.001, 0.001, tan_slope)

    # D8 flow direction and accumulation
    d8_offsets = [
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    ]
    d8_dists = [
        math.sqrt(2), 1.0, math.sqrt(2),
        1.0,                1.0,
        math.sqrt(2), 1.0, math.sqrt(2),
    ]

    flow_dir = np.full((h, w), -1, dtype=np.int8)
    flow_accum = np.ones((h, w), dtype=np.float64)

    for y in range(1, h - 1):
        for x in range(1, w - 1):
            max_slope = 0
            max_dir = -1
            for i, (dy_off, dx_off) in enumerate(d8_offsets):
                ny, nx = y + dy_off, x + dx_off
                drop = dem[y, x] - dem[ny, nx]
                s = drop / (d8_dists[i] * resolution_m)
                if s > max_slope:
                    max_slope = s
                    max_dir = i
            flow_dir[y, x] = max_dir

    # Flow accumulation — sort highest first, route downhill
    flat_indices = np.argsort(-dem.ravel())
    for idx in flat_indices:
        y, x = divmod(int(idx), w)
        if y < 1 or y >= h - 1 or x < 1 or x >= w - 1:
            continue
        d = flow_dir[y, x]
        if d >= 0:
            dy_off, dx_off = d8_offsets[d]
            ny, nx = y + dy_off, x + dx_off
            if 0 <= ny < h and 0 <= nx < w:
                flow_accum[ny, nx] += flow_accum[y, x]

    # Topographic Wetness Index
    specific_area = flow_accum * pixel_area / resolution_m
    twi = np.log(specific_area / tan_slope)
    twi = np.clip(twi, 0, 30)

    twi_mean = float(np.mean(twi))
    twi_std = float(np.std(twi))
    twi_max = float(np.max(twi))

    # Depression detection
    depressions = np.zeros((h, w), dtype=np.uint8)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            is_depression = True
            for dy_off, dx_off in d8_offsets:
                ny, nx = y + dy_off, x + dx_off
                if dem[ny, nx] <= dem[y, x]:
                    is_depression = False
                    break
            if is_depression:
                depressions[y, x] = 1

    depression_count = int(np.sum(depressions))
    depression_pct = round(depression_count / (h * w) * 100, 2)

    # Waterlogging risk: high TWI + flat
    waterlogged_mask = (twi > 12) & (slope_deg < 2)
    waterlogged_pct = round(float(np.mean(waterlogged_mask)) * 100, 1)

    # Drainage paths
    threshold = np.percentile(flow_accum, 95)
    drainage_mask = flow_accum > threshold

    flow_paths_geojson = _flow_paths_to_geojson(drainage_mask, lat, lon, resolution_m)

    # Risk classification
    if waterlogged_pct > 25 or twi_mean > 14:
        drainage_risk = "high"
        drainage_note = "Significant waterlogging risk. Comprehensive drainage design required."
    elif waterlogged_pct > 10 or twi_mean > 10:
        drainage_risk = "medium"
        drainage_note = "Moderate drainage concern. Standard SUDS design should suffice."
    else:
        drainage_risk = "low"
        drainage_note = "Well-drained terrain. Minimal drainage intervention needed."

    return {
        "twi": {
            "mean": round(twi_mean, 2),
            "std": round(twi_std, 2),
            "max": round(twi_max, 2),
        },
        "waterlogged_pct": waterlogged_pct,
        "depression_count": depression_count,
        "depression_pct": depression_pct,
        "drainage_risk": drainage_risk,
        "drainage_note": drainage_note,
        "slope_stats": {
            "mean_deg": round(float(np.mean(slope_deg)), 2),
            "max_deg": round(float(np.max(slope_deg)), 2),
        },
        "flow_paths_geojson": flow_paths_geojson,
        "method": "D8_numpy",
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
    }


def _flow_paths_to_geojson(
    drainage_mask: np.ndarray, lat: float, lon: float, resolution_m: float,
) -> dict:
    """Convert high-flow-accumulation cells to simplified GeoJSON lines."""
    h, w = drainage_mask.shape
    half_extent_deg = (resolution_m * max(h, w) / 2) / 111320

    west = lon - half_extent_deg
    east = lon + half_extent_deg
    south = lat - half_extent_deg
    north = lat + half_extent_deg

    drainage_points = np.argwhere(drainage_mask)
    if len(drainage_points) == 0:
        return {"type": "FeatureCollection", "features": []}

    step = max(1, len(drainage_points) // 200)
    sampled = drainage_points[::step]
    sampled = sampled[sampled[:, 0].argsort()]

    features = []
    segment_size = max(5, len(sampled) // 10)
    for i in range(0, len(sampled), segment_size):
        segment = sampled[i:i + segment_size]
        if len(segment) < 2:
            continue

        coords = []
        for py, px in segment:
            frac_x = px / w
            frac_y = 1.0 - (py / h)
            pt_lon = west + frac_x * (east - west)
            pt_lat = south + frac_y * (north - south)
            coords.append([round(pt_lon, 6), round(pt_lat, 6)])

        features.append({
            "type": "Feature",
            "properties": {"type": "drainage_path"},
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
        })

    return {"type": "FeatureCollection", "features": features}

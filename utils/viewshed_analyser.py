"""
Visual impact and viewshed analysis for energy developments.

Provides:
- Photomontage camera parameter generation for 3D rendering
- Zone of Theoretical Visibility (ZTV) estimation
- Visual impact magnitude scoring per Landscape Institute GLVIA3

Used for UK planning applications (LVIA — Landscape & Visual Impact Assessment).
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("princeps.viewshed")

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

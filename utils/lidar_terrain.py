"""
EA LiDAR 1m terrain analysis — survey-grade elevation data for UK sites.

Sources:
- EA LiDAR DTM 1m via GEE: UK/EA/ENGLAND_1M_TERRAIN/2022
- EA LiDAR DSM 1m via GEE: UK/EA/ENGLAND_1M_DSM/2022
- Fallback: NASADEM 30m (already in GeeFlow)

Provides:
- High-resolution heightmap for 3D digital twin
- Slope/aspect analysis for solar panel orientation
- Cut/fill volume estimation for site preparation
- Surface roughness for wind resource assessment
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("princeps.lidar_terrain")

# Subprocess config — same pattern as geeflow_runner
_geeflow_default = os.path.join(os.path.dirname(__file__), "..", ".venv-geeflow", "bin", "python")
GEEFLOW_PYTHON = str(Path(os.environ.get("GEEFLOW_PYTHON", _geeflow_default)).absolute())
LIDAR_RUNNER = str(Path(os.path.join(os.path.dirname(__file__), "lidar_runner.py")).resolve())
GEE_PROJECT = os.environ.get("GEE_PROJECT", "hopeful-subject-486905-e5")


# ---------------------------------------------------------------------------
# Subprocess bridge to lidar_runner.py
# ---------------------------------------------------------------------------

async def _run_lidar_subprocess(
    mode: str, lat: float, lon: float,
    radius_m: float = 500, resolution_m: float = 2,
    grid_size: int = 128, timeout: int = 300,
) -> dict[str, Any]:
    """Run lidar_runner.py in .venv-geeflow subprocess."""
    if not GEE_PROJECT:
        return {"error": "GEE_PROJECT not configured"}

    cmd = [
        GEEFLOW_PYTHON, LIDAR_RUNNER,
        "--mode", mode,
        "--lat", str(lat),
        "--lon", str(lon),
        "--radius_m", str(radius_m),
        "--resolution_m", str(resolution_m),
        "--grid_size", str(grid_size),
        "--gee_project", GEE_PROJECT,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        err_msg = stderr.decode()[:500] if stderr else "Unknown error"
        log.error("LiDAR subprocess failed: %s", err_msg)
        return {"error": f"LiDAR extraction failed: {err_msg}"}
    return json.loads(stdout.decode())


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------

async def fetch_lidar_terrain(
    lat: float, lon: float, radius_m: float = 500, resolution_m: float = 2,
) -> dict:
    """Fetch EA LiDAR 1m DTM terrain data for a site.

    Returns heightmap grid, elevation stats, slope/aspect analysis.
    Falls back to NASADEM 30m outside England LiDAR coverage.
    """
    grid_size = min(256, max(32, int(radius_m * 2 / resolution_m)))
    grid_size = min(grid_size, 128)  # cap to stay within GEE sampleRectangle limit

    result = await _run_lidar_subprocess(
        "lidar_terrain", lat, lon,
        radius_m=radius_m,
        resolution_m=resolution_m,
        grid_size=grid_size,
    )
    return result


async def fetch_lidar_dsm(
    lat: float, lon: float, radius_m: float = 500, resolution_m: float = 2,
) -> dict:
    """Fetch EA LiDAR 1m DSM (surface model including trees/buildings)."""
    grid_size = min(128, max(32, int(radius_m * 2 / resolution_m)))

    result = await _run_lidar_subprocess(
        "lidar_dsm", lat, lon,
        radius_m=radius_m,
        resolution_m=resolution_m,
        grid_size=grid_size,
    )
    return result


async def analyse_terrain(lat: float, lon: float, radius_m: float = 500) -> dict:
    """Full terrain suitability assessment for energy development.

    Fetches LiDAR terrain then computes:
    - Slope statistics and suitability classification
    - Aspect distribution (south-facing percentage)
    - Elevation range and flatness score
    - Cut/fill volume estimate for site levelling
    - Surface roughness classification for wind assessment
    """
    terrain = await fetch_lidar_terrain(lat, lon, radius_m=radius_m, resolution_m=2)

    if "error" in terrain:
        return terrain

    elev = terrain.get("elevation", {})
    slope_data = terrain.get("slope", {})
    aspect_data = terrain.get("aspect", {})
    heightmap = terrain.get("heightmap", {})

    # --- Flatness score (0-100, 100 = perfectly flat) ---
    elev_range = elev.get("range_m", 0)
    slope_mean = slope_data.get("mean_deg", 0)
    slope_p90 = slope_data.get("p90_deg", 0)

    flatness = max(0, min(100, int(
        100
        - elev_range * 2          # penalise elevation range
        - slope_mean * 8          # penalise average slope
        - max(0, slope_p90 - 5) * 4  # penalise steep areas
    )))

    # --- Slope suitability classification ---
    if slope_mean < 3:
        slope_class = "excellent"
        slope_note = "Minimal grading needed. Ideal for ground-mount solar."
    elif slope_mean < 7:
        slope_class = "good"
        slope_note = "Minor earthworks may be needed. Suitable for solar with tracking."
    elif slope_mean < 15:
        slope_class = "moderate"
        slope_note = "Significant grading required. Fixed-tilt solar feasible."
    else:
        slope_class = "poor"
        slope_note = "Steep terrain. Major earthworks needed. Consider alternative layout."

    # --- Aspect suitability ---
    south_pct = aspect_data.get("south_facing_pct", 0)
    if south_pct > 60:
        aspect_class = "excellent"
        aspect_note = f"{south_pct:.0f}% south-facing. Optimal solar orientation."
    elif south_pct > 40:
        aspect_class = "good"
        aspect_note = f"{south_pct:.0f}% south-facing. Good solar potential."
    elif south_pct > 25:
        aspect_class = "moderate"
        aspect_note = f"{south_pct:.0f}% south-facing. Consider east-west tracking."
    else:
        aspect_class = "poor"
        aspect_note = f"{south_pct:.0f}% south-facing. North-facing slopes reduce yield."

    # --- Cut/fill estimation ---
    # Simple estimate: volume of earth to move to achieve flat platform at mean elevation
    values = heightmap.get("values", [])
    res = heightmap.get("resolution_m", 2)
    pixel_area = res * res

    mean_elev = elev.get("mean_m", 0)
    cut_volume = 0.0
    fill_volume = 0.0
    for row in values:
        for v in row:
            diff = v - mean_elev
            if diff > 0:
                cut_volume += diff * pixel_area
            else:
                fill_volume += abs(diff) * pixel_area

    # --- Surface roughness (Davenport classification proxy) ---
    slope_std = slope_data.get("std_deg", 0)
    if slope_std < 1:
        roughness_class = "smooth"
        roughness_note = "Low roughness. Minimal turbulence for wind."
    elif slope_std < 3:
        roughness_class = "moderate"
        roughness_note = "Moderate terrain variation."
    else:
        roughness_class = "rough"
        roughness_note = "High terrain variation. Significant turbulence expected."

    # --- Overall terrain score (0-100) ---
    terrain_score = max(0, min(100, int(
        flatness * 0.4
        + min(100, south_pct * 1.5) * 0.3
        + (100 - min(100, slope_mean * 7)) * 0.3
    )))

    return {
        "terrain_score": terrain_score,
        "flatness_score": flatness,
        "source": terrain.get("source", "unknown"),
        "elevation": elev,
        "slope": {
            **slope_data,
            "suitability": slope_class,
            "note": slope_note,
        },
        "aspect": {
            **aspect_data,
            "suitability": aspect_class,
            "note": aspect_note,
        },
        "cut_fill": {
            "cut_volume_m3": round(cut_volume, 0),
            "fill_volume_m3": round(fill_volume, 0),
            "net_volume_m3": round(abs(cut_volume - fill_volume), 0),
            "balance_ratio": round(min(cut_volume, fill_volume) / max(cut_volume, fill_volume, 1), 2),
            "note": (
                "Good cut/fill balance — earth can be redistributed on-site."
                if abs(cut_volume - fill_volume) < (cut_volume + fill_volume) * 0.3
                else "Unbalanced cut/fill — import/export of material likely needed."
            ),
        },
        "surface_roughness": {
            "class": roughness_class,
            "note": roughness_note,
            "slope_std_deg": slope_std,
        },
        "heightmap": heightmap,
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
    }

"""
Google Open Buildings integration — building footprint detection.

Queries Google's Open Buildings dataset via Earth Engine for
building footprints near a location. Used for:
- Estimating proximity to residential areas (planning constraints)
- Identifying industrial buildings near substations
- Rooftop solar potential estimation

Uses the GeeFlow subprocess bridge (.venv-geeflow/bin/python) to query
the GOOGLE/Research/open-buildings/v3/polygons collection in GEE.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from pathlib import Path
from typing import Any

log = logging.getLogger("princeps.open_buildings")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_geeflow_default = os.path.join(os.path.dirname(__file__), "..", ".venv-geeflow", "bin", "python")
GEEFLOW_PYTHON = str(Path(os.environ.get("GEEFLOW_PYTHON", _geeflow_default)).absolute())
GEE_PROJECT = os.environ.get("GEE_PROJECT", "")


# ---------------------------------------------------------------------------
# GEE subprocess script template
# ---------------------------------------------------------------------------

_GEE_SCRIPT_TEMPLATE = '''
import ee, json, sys

ee.Initialize(project="{project}")

point = ee.Geometry.Point([{lon}, {lat}])
aoi = point.buffer({radius_m})

# Google Open Buildings v3 — building footprints from satellite imagery
buildings = (ee.FeatureCollection("GOOGLE/Research/open-buildings/v3/polygons")
             .filterBounds(aoi))

# Limit to avoid timeouts on dense urban areas
count = buildings.size().getInfo()
if count > {max_buildings}:
    buildings = buildings.limit({max_buildings})
    limited = True
else:
    limited = False

features = []
fc_info = buildings.getInfo()
if fc_info and "features" in fc_info:
    for f in fc_info["features"]:
        props = f.get("properties", {{}})
        geom = f.get("geometry", {{}})
        area = props.get("area_in_meters", 0)
        confidence = props.get("confidence", 0)
        # Estimate building height from footprint area (heuristic)
        # Small: likely 1-2 storey, Medium: 2-4 storey, Large: industrial
        if area < 80:
            height_est = 6.0   # 2 storey residential
        elif area < 200:
            height_est = 9.0   # 3 storey
        elif area < 500:
            height_est = 12.0  # 4 storey / commercial
        elif area < 2000:
            height_est = 8.0   # industrial (wide, low)
        else:
            height_est = 6.0   # warehouse / large industrial
        features.append({{
            "type": "Feature",
            "geometry": geom,
            "properties": {{
                "area_m2": round(area, 1),
                "confidence": round(confidence, 3),
                "height_est": height_est,
                "full_plus_code": props.get("full_plus_code", ""),
            }},
        }})

# Summary statistics
areas = [f["properties"]["area_m2"] for f in features]
total_area = sum(areas)
residential = [a for a in areas if a < 200]
commercial = [a for a in areas if 200 <= a < 1000]
industrial = [a for a in areas if a >= 1000]

result = {{
    "type": "FeatureCollection",
    "features": features,
    "metadata": {{
        "total_buildings": len(features),
        "total_count_in_area": count,
        "limited": limited,
        "total_footprint_m2": round(total_area, 1),
        "residential_count": len(residential),
        "commercial_count": len(commercial),
        "industrial_count": len(industrial),
        "mean_area_m2": round(total_area / max(len(areas), 1), 1),
        "lat": {lat},
        "lon": {lon},
        "radius_m": {radius_m},
        "source": "Google Open Buildings v3",
    }},
}}
json.dump(result, sys.stdout)
'''


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_building_footprints(
    lat: float,
    lon: float,
    radius_m: float = 500,
    max_buildings: int = 2000,
    timeout: int = 120,
) -> dict[str, Any]:
    """
    Fetch Google Open Buildings footprints via GEE subprocess.

    Args:
        lat: Latitude (WGS84)
        lon: Longitude (WGS84)
        radius_m: Search radius in metres (default 500)
        max_buildings: Maximum buildings to return (default 2000)
        timeout: Subprocess timeout in seconds

    Returns:
        GeoJSON FeatureCollection with properties:
          area_m2, confidence, height_est, full_plus_code
        Plus metadata with summary statistics.
    """
    if not GEE_PROJECT:
        return _fallback_response(lat, lon, radius_m,
                                  error="GEE_PROJECT not configured")

    script = _GEE_SCRIPT_TEMPLATE.format(
        project=GEE_PROJECT,
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        max_buildings=max_buildings,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            GEEFLOW_PYTHON, "-c", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if proc.returncode != 0:
            err_msg = stderr.decode()[:500]
            log.warning("Open Buildings GEE subprocess failed: %s", err_msg)
            return _fallback_response(lat, lon, radius_m, error=err_msg)

        result = json.loads(stdout.decode())
        return result

    except asyncio.TimeoutError:
        log.warning("Open Buildings GEE subprocess timed out after %ds", timeout)
        return _fallback_response(lat, lon, radius_m, error="GEE timeout")
    except json.JSONDecodeError as exc:
        log.warning("Open Buildings JSON decode error: %s", exc)
        return _fallback_response(lat, lon, radius_m, error=str(exc))
    except Exception as exc:
        log.warning("Open Buildings error: %s", exc)
        return _fallback_response(lat, lon, radius_m, error=str(exc))


async def get_building_summary(
    lat: float,
    lon: float,
    radius_m: float = 1000,
) -> dict[str, Any]:
    """
    Quick building density summary without fetching full geometries.
    Useful for planning constraint checks.
    """
    result = await get_building_footprints(lat, lon, radius_m, max_buildings=5000)
    meta = result.get("metadata", {})

    total = meta.get("total_count_in_area", 0)
    area_km2 = math.pi * (radius_m / 1000) ** 2

    density = total / max(area_km2, 0.01)

    # Classification
    if density > 5000:
        classification = "urban"
    elif density > 1000:
        classification = "suburban"
    elif density > 100:
        classification = "rural_settlement"
    elif density > 10:
        classification = "sparse_rural"
    else:
        classification = "remote"

    # Planning constraint assessment
    if density > 2000:
        planning_risk = "HIGH"
        planning_note = "Dense built environment — significant planning constraints expected"
    elif density > 500:
        planning_risk = "MEDIUM"
        planning_note = "Moderate building density — residential proximity may require screening"
    elif density > 50:
        planning_risk = "LOW"
        planning_note = "Low building density — fewer planning objections expected"
    else:
        planning_risk = "MINIMAL"
        planning_note = "Very sparse development — minimal residential constraints"

    # Rooftop solar potential
    residential_count = meta.get("residential_count", 0)
    mean_area = meta.get("mean_area_m2", 100)
    rooftop_kwp = round(residential_count * min(mean_area * 0.3, 30) * 0.18, 0)

    return {
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "total_buildings": total,
        "area_km2": round(area_km2, 3),
        "density_per_km2": round(density, 0),
        "classification": classification,
        "residential_count": meta.get("residential_count", 0),
        "commercial_count": meta.get("commercial_count", 0),
        "industrial_count": meta.get("industrial_count", 0),
        "total_footprint_m2": meta.get("total_footprint_m2", 0),
        "planning_risk": planning_risk,
        "planning_note": planning_note,
        "rooftop_solar_kwp_estimate": rooftop_kwp,
        "source": "Google Open Buildings v3",
    }


# ---------------------------------------------------------------------------
# Fallback (when GEE is unavailable)
# ---------------------------------------------------------------------------

def _fallback_response(
    lat: float, lon: float, radius_m: float, error: str = ""
) -> dict[str, Any]:
    """Return a valid but empty response when GEE is unavailable."""
    return {
        "type": "FeatureCollection",
        "features": [],
        "metadata": {
            "total_buildings": 0,
            "total_count_in_area": 0,
            "limited": False,
            "total_footprint_m2": 0,
            "residential_count": 0,
            "commercial_count": 0,
            "industrial_count": 0,
            "mean_area_m2": 0,
            "lat": lat,
            "lon": lon,
            "radius_m": radius_m,
            "source": "Google Open Buildings v3",
            "error": error,
        },
    }

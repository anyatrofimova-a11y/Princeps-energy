"""
EA LiDAR 1m terrain runner — standalone CLI for Google Earth Engine.

Runs inside .venv-geeflow/ (Python 3.12 with earthengine-api).
Accepts CLI args, prints JSON to stdout (same pattern as geeflow_runner.py).

Modes:
  lidar_terrain   — EA LiDAR 1m DTM heightmap + slope + aspect
  lidar_dsm       — EA LiDAR 1m DSM (surface model, includes trees/buildings)
  lidar_both      — DTM + DSM combined (for canopy/building height extraction)
"""

import argparse
import json
import math
import sys

import ee


def init_ee(project: str):
    """Initialise Earth Engine with project credentials."""
    try:
        ee.Initialize(project=project)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project)


def make_buffer(lat: float, lon: float, radius_m: float) -> ee.Geometry:
    """Create a circular buffer geometry around a point."""
    point = ee.Geometry.Point([lon, lat])
    return point.buffer(radius_m)


# ---------------------------------------------------------------------------
# EA LiDAR DTM 1m
# ---------------------------------------------------------------------------

EA_DTM_ASSET = "UK/EA/ENGLAND_1M_TERRAIN/2022"
EA_DSM_ASSET = "UK/EA/ENGLAND_1M_DSM/2022"
NASADEM_ASSET = "NASA/NASADEM_HGT/001"


def extract_lidar_terrain(
    lat: float, lon: float, radius_m: float, resolution_m: float, grid_size: int,
) -> dict:
    """Extract EA LiDAR 1m DTM heightmap with slope and aspect.

    Tries EA LiDAR first; falls back to NASADEM 30m if outside England coverage.
    Returns a 2D grid of elevation values plus slope/aspect statistics.
    """
    point = ee.Geometry.Point([lon, lat])
    aoi = point.buffer(radius_m).bounds()

    # Try EA LiDAR DTM first
    source = "EA LiDAR DTM 1m (2022)"
    try:
        dem = ee.Image(EA_DTM_ASSET).select(0)
        # Check if data exists at this location
        sample_val = dem.reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=point.buffer(50),
            scale=1,
            maxPixels=1e4,
        ).getInfo()
        pixel_count = list(sample_val.values())[0] if sample_val else 0
        if not pixel_count or pixel_count == 0:
            raise ValueError("No EA LiDAR coverage")
    except Exception:
        # Fallback to NASADEM
        dem = ee.Image(NASADEM_ASSET).select("elevation")
        source = "NASADEM 30m (fallback)"
        resolution_m = max(resolution_m, 30)

    # Compute slope and aspect from DEM
    slope = ee.Terrain.slope(dem)
    aspect = ee.Terrain.aspect(dem)

    # Resample to target resolution and extract grid
    scale = max(resolution_m, radius_m * 2 / grid_size)

    dem_resampled = dem.resample("bilinear").reproject(
        crs="EPSG:4326",
        scale=scale,
    )

    # Extract heightmap as 2D array via sampleRectangle
    try:
        sample = dem_resampled.sampleRectangle(region=aoi, defaultValue=0)
        band_name = dem_resampled.bandNames().getInfo()[0]
        array = sample.get(band_name).getInfo()
    except Exception as e:
        # If sampleRectangle fails (too many pixels), reduce grid_size
        scale = radius_m * 2 / min(grid_size, 64)
        dem_resampled = dem.resample("bilinear").reproject(crs="EPSG:4326", scale=scale)
        sample = dem_resampled.sampleRectangle(region=aoi, defaultValue=0)
        band_name = dem_resampled.bandNames().getInfo()[0]
        array = sample.get(band_name).getInfo()

    if not array or not isinstance(array, list):
        return {"mode": "lidar_terrain", "error": "No elevation data returned"}

    # Clean values
    values = []
    all_vals = []
    for row in array:
        clean_row = []
        for v in row:
            val = round(v, 2) if v is not None else 0.0
            clean_row.append(val)
            if v is not None:
                all_vals.append(val)
        values.append(clean_row)

    h = len(values)
    w = len(values[0]) if h > 0 else 0

    min_elev = min(all_vals) if all_vals else 0
    max_elev = max(all_vals) if all_vals else 0
    mean_elev = sum(all_vals) / len(all_vals) if all_vals else 0

    # Slope and aspect statistics
    circ_aoi = make_buffer(lat, lon, radius_m)

    slope_stats = slope.reduceRegion(
        reducer=ee.Reducer.mean()
            .combine(ee.Reducer.minMax(), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True)
            .combine(ee.Reducer.percentile([90]), sharedInputs=True),
        geometry=circ_aoi,
        scale=max(resolution_m, 2),
        maxPixels=1e8,
    ).getInfo()

    aspect_stats = aspect.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=circ_aoi,
        scale=max(resolution_m, 2),
        maxPixels=1e8,
    ).getInfo()

    # South-facing percentage (135-225 degrees)
    south_facing = aspect.gte(135).And(aspect.lte(225))
    south_pct_raw = south_facing.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=circ_aoi,
        scale=max(resolution_m, 2),
        maxPixels=1e8,
    ).getInfo()

    # Extract slope stat values (band name may vary)
    def _get_stat(stats_dict, suffix):
        for k, v in stats_dict.items():
            if k.endswith(suffix):
                return v
        return 0

    south_val = list(south_pct_raw.values())[0] if south_pct_raw else 0

    return {
        "mode": "lidar_terrain",
        "source": source,
        "heightmap": {
            "width": w,
            "height": h,
            "values": values,
            "resolution_m": round(scale, 2),
        },
        "elevation": {
            "min_m": round(min_elev, 2),
            "max_m": round(max_elev, 2),
            "mean_m": round(mean_elev, 2),
            "range_m": round(max_elev - min_elev, 2),
        },
        "slope": {
            "mean_deg": round(_get_stat(slope_stats, "_mean") or 0, 2),
            "max_deg": round(_get_stat(slope_stats, "_max") or 0, 2),
            "p90_deg": round(_get_stat(slope_stats, "_p90") or 0, 2),
            "std_deg": round(_get_stat(slope_stats, "_stdDev") or 0, 2),
        },
        "aspect": {
            "mean_deg": round(list(aspect_stats.values())[0] if aspect_stats else 0, 1),
            "south_facing_pct": round((south_val or 0) * 100, 1),
        },
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
    }


def extract_lidar_dsm(
    lat: float, lon: float, radius_m: float, resolution_m: float, grid_size: int,
) -> dict:
    """Extract EA LiDAR 1m DSM (Digital Surface Model, includes trees/buildings)."""
    point = ee.Geometry.Point([lon, lat])
    aoi = point.buffer(radius_m).bounds()

    source = "EA LiDAR DSM 1m (2022)"
    try:
        dsm = ee.Image(EA_DSM_ASSET).select(0)
        sample_val = dsm.reduceRegion(
            reducer=ee.Reducer.count(),
            geometry=point.buffer(50),
            scale=1,
            maxPixels=1e4,
        ).getInfo()
        pixel_count = list(sample_val.values())[0] if sample_val else 0
        if not pixel_count or pixel_count == 0:
            return {"mode": "lidar_dsm", "error": "No EA LiDAR DSM coverage at this location"}
    except Exception as e:
        return {"mode": "lidar_dsm", "error": f"EA LiDAR DSM not available: {str(e)[:200]}"}

    scale = max(resolution_m, radius_m * 2 / grid_size)
    dsm_resampled = dsm.resample("bilinear").reproject(crs="EPSG:4326", scale=scale)

    sample = dsm_resampled.sampleRectangle(region=aoi, defaultValue=0)
    band_name = dsm_resampled.bandNames().getInfo()[0]
    array = sample.get(band_name).getInfo()

    if not array or not isinstance(array, list):
        return {"mode": "lidar_dsm", "error": "No DSM data returned"}

    values = []
    all_vals = []
    for row in array:
        clean_row = []
        for v in row:
            val = round(v, 2) if v is not None else 0.0
            clean_row.append(val)
            if v is not None:
                all_vals.append(val)
        values.append(clean_row)

    return {
        "mode": "lidar_dsm",
        "source": source,
        "heightmap": {
            "width": len(values[0]) if values else 0,
            "height": len(values),
            "values": values,
            "resolution_m": round(scale, 2),
        },
        "elevation": {
            "min_m": round(min(all_vals), 2) if all_vals else 0,
            "max_m": round(max(all_vals), 2) if all_vals else 0,
            "mean_m": round(sum(all_vals) / len(all_vals), 2) if all_vals else 0,
        },
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

MODE_MAP = {
    "lidar_terrain": extract_lidar_terrain,
    "lidar_dsm": extract_lidar_dsm,
}


def main():
    parser = argparse.ArgumentParser(description="EA LiDAR terrain extraction via GEE")
    parser.add_argument("--mode", required=True, choices=list(MODE_MAP.keys()))
    parser.add_argument("--lat", required=True, type=float)
    parser.add_argument("--lon", required=True, type=float)
    parser.add_argument("--radius_m", type=float, default=500)
    parser.add_argument("--resolution_m", type=float, default=2)
    parser.add_argument("--grid_size", type=int, default=128)
    parser.add_argument("--gee_project", required=True)
    args = parser.parse_args()

    init_ee(args.gee_project)

    func = MODE_MAP[args.mode]
    result = func(args.lat, args.lon, args.radius_m, args.resolution_m, args.grid_size)

    json.dump(result, sys.stdout, indent=2)


if __name__ == "__main__":
    main()

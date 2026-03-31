#!/usr/bin/env python3
"""
atlite capacity factor map runner — standalone subprocess script.

Called from the FastAPI backend via subprocess because atlite has heavy
dependencies (xarray, dask, geopandas, rasterio) in .venv-atlite/.

Usage (stdin/stdout JSON bridge):
    echo '{"bounds": [-2.0, 51.0, -1.0, 52.0], "year": 2023, "technology": "pv"}' | \
        .venv-atlite/bin/python utils/atlite_runner.py

Input JSON:
    {
        "bounds": [lon_min, lat_min, lon_max, lat_max],
        "year": 2023,
        "technology": "pv" | "wind",
        "turbine": "Vestas_V112_3MW"  (optional, wind only)
    }

Output JSON:
    {
        "ok": true,
        "technology": "pv",
        "bounds": [...],
        "year": 2023,
        "grid_resolution": 0.25,
        "capacity_factors": [[lat, lon, cf], ...],
        "mean_cf": 0.11,
        "p50_cf": 0.10,
        "p90_cf": 0.14,
        "geojson": { "type": "FeatureCollection", ... }
    }
"""

import json
import sys
import traceback


def compute_capacity_map(bounds, year=2023, technology="pv", turbine=None):
    """
    Compute gridded capacity factor map using atlite with ERA5 backend.

    Args:
        bounds: [lon_min, lat_min, lon_max, lat_max]
        year: data year
        technology: 'pv' or 'wind'
        turbine: turbine model name for wind (default Vestas_V112_3MW)

    Returns:
        dict with gridded capacity factors, stats, GeoJSON
    """
    import numpy as np

    try:
        import atlite
    except ImportError:
        return {"ok": False, "error": "atlite not installed in this venv"}

    lon_min, lat_min, lon_max, lat_max = bounds

    # Ensure minimum span for atlite (needs at least ~0.25 deg)
    if (lon_max - lon_min) < 0.25:
        mid = (lon_max + lon_min) / 2
        lon_min, lon_max = mid - 0.125, mid + 0.125
    if (lat_max - lat_min) < 0.25:
        mid = (lat_max + lat_min) / 2
        lat_min, lat_max = mid - 0.125, mid + 0.125

    # Create cutout — atlite will download ERA5 data
    cutout = atlite.Cutout(
        path=f"cutouts/{technology}_{year}_{lat_min:.2f}_{lon_min:.2f}",
        module="era5",
        x=slice(lon_min, lon_max),
        y=slice(lat_min, lat_max),
        time=f"{year}",
    )
    cutout.prepare()

    # Compute capacity factors
    if technology == "pv":
        cap_factors = cutout.pv(
            panel="CSi",
            orientation={"slope": 35.0, "azimuth": 180.0},
            per_unit=True,
        )
    elif technology == "wind":
        turb = turbine or "Vestas_V112_3MW"
        cap_factors = cutout.wind(
            turbine=turb,
            per_unit=True,
        )
    else:
        return {"ok": False, "error": f"Unknown technology: {technology}"}

    # Annual mean capacity factors per grid cell
    annual_cf = cap_factors.mean(dim="time")

    # Extract grid coordinates and values
    lats = annual_cf.coords["y"].values
    lons = annual_cf.coords["x"].values
    values = annual_cf.values

    # Build gridded results
    grid_points = []
    all_cfs = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            cf = float(values[i, j]) if values.ndim == 2 else float(values[j])
            if not np.isnan(cf):
                grid_points.append([round(float(lat), 4), round(float(lon), 4), round(cf, 4)])
                all_cfs.append(cf)

    if not all_cfs:
        return {"ok": False, "error": "No valid capacity factor data in region"}

    all_cfs_arr = np.array(all_cfs)
    mean_cf = float(np.mean(all_cfs_arr))
    p50_cf = float(np.percentile(all_cfs_arr, 50))
    p90_cf = float(np.percentile(all_cfs_arr, 90))

    # Build GeoJSON FeatureCollection
    features = []
    dx = (lon_max - lon_min) / max(len(lons) - 1, 1) / 2 if len(lons) > 1 else 0.125
    dy = (lat_max - lat_min) / max(len(lats) - 1, 1) / 2 if len(lats) > 1 else 0.125

    for pt in grid_points:
        lat_c, lon_c, cf = pt
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [lon_c - dx, lat_c - dy],
                    [lon_c + dx, lat_c - dy],
                    [lon_c + dx, lat_c + dy],
                    [lon_c - dx, lat_c + dy],
                    [lon_c - dx, lat_c - dy],
                ]],
            },
            "properties": {
                "capacity_factor": cf,
                "capacity_factor_pct": round(cf * 100, 1),
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}

    return {
        "ok": True,
        "technology": technology,
        "bounds": bounds,
        "year": year,
        "grid_resolution": round(dx * 2, 4),
        "capacity_factors": grid_points,
        "num_cells": len(grid_points),
        "mean_cf": round(mean_cf, 4),
        "p50_cf": round(p50_cf, 4),
        "p90_cf": round(p90_cf, 4),
        "geojson": geojson,
    }


def main():
    """Read JSON from stdin, compute capacity map, write JSON to stdout."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({"ok": False, "error": "Empty input"}))
            sys.exit(1)

        data = json.loads(raw)
        bounds = data.get("bounds")
        if not bounds or len(bounds) != 4:
            print(json.dumps({"ok": False, "error": "bounds must be [lon_min, lat_min, lon_max, lat_max]"}))
            sys.exit(1)

        result = compute_capacity_map(
            bounds=bounds,
            year=data.get("year", 2023),
            technology=data.get("technology", "pv"),
            turbine=data.get("turbine"),
        )
        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "traceback": traceback.format_exc()}))
        sys.exit(1)


if __name__ == "__main__":
    main()

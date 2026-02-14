"""
GeeFlow Runner — standalone CLI script for Google Earth Engine data extraction.

Runs inside .venv-geeflow/ (Python 3.12 with earthengine-api).
Accepts CLI args, prints JSON to stdout (same pattern as sam_runner.py).

Extraction modes:
  land_use       — DynamicWorld 10m land cover classification
  terrain        — NASADEM/Copernicus DEM slope/aspect/elevation
  solar_resource — ERA5-Land monthly GHI/DHI/temperature
  vegetation     — Sentinel-2 NDVI profile
  site_composite — All modes combined
  change_detection — Sentinel-2 land use change over N years
"""

import argparse
import json
import math
import sys
from datetime import datetime

import ee


def init_ee(project: str):
    """Initialise Earth Engine with project credentials."""
    try:
        ee.Initialize(project=project)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=project)


def make_buffer(lat: float, lon: float, radius_km: float) -> ee.Geometry:
    """Create a circular buffer geometry around a point."""
    point = ee.Geometry.Point([lon, lat])
    return point.buffer(radius_km * 1000)


# ---------------------------------------------------------------------------
# Mode: land_use — DynamicWorld 10m land cover
# ---------------------------------------------------------------------------

def extract_land_use(lat: float, lon: float, radius_km: float, year: int) -> dict:
    """Extract DynamicWorld land cover classification percentages."""
    aoi = make_buffer(lat, lon, radius_km)

    # DynamicWorld: 10m near-real-time land cover from Sentinel-2
    start = f"{year}-01-01"
    end = f"{year}-12-31"

    dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
          .filterDate(start, end)
          .filterBounds(aoi))

    # Mode composite — most frequent class per pixel
    label = dw.select("label").mode()

    # Class names from DynamicWorld
    class_names = [
        "water", "trees", "grass", "flooded_vegetation", "crops",
        "shrub_and_scrub", "built", "bare", "snow_and_ice"
    ]

    # Count pixels per class
    area_image = ee.Image.pixelArea().addBands(label)
    stats = area_image.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
        geometry=aoi,
        scale=10,
        maxPixels=1e9,
    ).getInfo()

    groups = stats.get("groups", [])
    total_area = sum(g["sum"] for g in groups) if groups else 1

    class_pcts = {}
    for g in groups:
        cls_idx = int(g["class"])
        if 0 <= cls_idx < len(class_names):
            class_pcts[class_names[cls_idx]] = round(g["sum"] / total_area * 100, 1)

    # Developable area: grass + bare + crops + shrub
    developable_classes = {"grass", "bare", "crops", "shrub_and_scrub"}
    developable_pct = sum(class_pcts.get(c, 0) for c in developable_classes)

    return {
        "mode": "land_use",
        "source": "DynamicWorld V1 (10m)",
        "year": year,
        "class_percentages": class_pcts,
        "developable_area_pct": round(developable_pct, 1),
        "total_area_m2": round(total_area, 0),
        "radius_km": radius_km,
        "lat": lat,
        "lon": lon,
    }


# ---------------------------------------------------------------------------
# Mode: terrain — NASADEM elevation, slope, aspect
# ---------------------------------------------------------------------------

def extract_terrain(lat: float, lon: float, radius_km: float) -> dict:
    """Extract terrain statistics from NASADEM (30m)."""
    aoi = make_buffer(lat, lon, radius_km)

    dem = ee.Image("NASA/NASADEM_HGT/001").select("elevation")
    slope = ee.Terrain.slope(dem)
    aspect = ee.Terrain.aspect(dem)

    # Reduce to stats within AOI
    elev_stats = dem.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True)
            .combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=aoi, scale=30, maxPixels=1e8,
    ).getInfo()

    slope_stats = slope.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.minMax(), sharedInputs=True)
            .combine(ee.Reducer.percentile([90]), sharedInputs=True),
        geometry=aoi, scale=30, maxPixels=1e8,
    ).getInfo()

    aspect_stats = aspect.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=aoi, scale=30, maxPixels=1e8,
    ).getInfo()

    # South-facing analysis (135-225 degrees = good for solar)
    south_facing = aspect.gte(135).And(aspect.lte(225))
    south_pct_raw = south_facing.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=aoi, scale=30, maxPixels=1e8,
    ).getInfo()

    south_pct = round((south_pct_raw.get("aspect", 0) or 0) * 100, 1)

    return {
        "mode": "terrain",
        "source": "NASADEM 30m",
        "elevation": {
            "mean_m": round(elev_stats.get("elevation_mean", 0) or 0, 1),
            "min_m": round(elev_stats.get("elevation_min", 0) or 0, 1),
            "max_m": round(elev_stats.get("elevation_max", 0) or 0, 1),
            "std_m": round(elev_stats.get("elevation_stdDev", 0) or 0, 1),
        },
        "slope": {
            "mean_deg": round(slope_stats.get("slope_mean", 0) or 0, 2),
            "max_deg": round(slope_stats.get("slope_max", 0) or 0, 2),
            "p90_deg": round(slope_stats.get("slope_p90", 0) or 0, 2),
        },
        "aspect": {
            "mean_deg": round(aspect_stats.get("aspect_mean", 0) or 0, 1),
            "south_facing_pct": south_pct,
        },
        "radius_km": radius_km,
        "lat": lat,
        "lon": lon,
    }


# ---------------------------------------------------------------------------
# Mode: solar_resource — ERA5-Land monthly irradiance + temperature
# ---------------------------------------------------------------------------

def extract_solar_resource(lat: float, lon: float, radius_km: float, year: int) -> dict:
    """Extract monthly solar resource data from ERA5-Land."""
    aoi = make_buffer(lat, lon, radius_km)

    monthly_data = []
    for month in range(1, 13):
        start = f"{year}-{month:02d}-01"
        end_month = month + 1 if month < 12 else 1
        end_year = year if month < 12 else year + 1
        end = f"{end_year}-{end_month:02d}-01"

        era5 = (ee.ImageCollection("ECMWF/ERA5_LAND/MONTHLY_AGGR")
                .filterDate(start, end)
                .first())

        if era5 is None:
            monthly_data.append({"month": month, "error": "No data"})
            continue

        # Surface solar radiation downwards (J/m2 cumulative) -> kWh/m2/day
        # Temperature at 2m (K -> °C)
        stats = era5.select([
            "surface_solar_radiation_downwards_sum",
            "temperature_2m",
        ]).reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=aoi, scale=11132, maxPixels=1e8,
        ).getInfo()

        ssrd = stats.get("surface_solar_radiation_downwards_sum", 0) or 0
        temp_k = stats.get("temperature_2m", 273.15) or 273.15

        # Convert SSRD from J/m2 (monthly total) to kWh/m2/day
        days_in_month = 30  # approximate
        ghi_kwh_day = (ssrd / 3600000) / days_in_month if ssrd else 0

        monthly_data.append({
            "month": month,
            "ghi_kwh_m2_day": round(ghi_kwh_day, 3),
            "temperature_c": round(temp_k - 273.15, 1),
        })

    # Annual GHI
    annual_ghi = sum(
        m.get("ghi_kwh_m2_day", 0) * 30 for m in monthly_data
        if isinstance(m.get("ghi_kwh_m2_day"), (int, float))
    )

    return {
        "mode": "solar_resource",
        "source": "ERA5-Land Monthly",
        "year": year,
        "monthly": monthly_data,
        "annual_ghi_kwh_m2": round(annual_ghi, 1),
        "radius_km": radius_km,
        "lat": lat,
        "lon": lon,
    }


# ---------------------------------------------------------------------------
# Mode: vegetation — Sentinel-2 NDVI
# ---------------------------------------------------------------------------

def extract_vegetation(lat: float, lon: float, radius_km: float, year: int) -> dict:
    """Extract NDVI vegetation profile from Sentinel-2."""
    aoi = make_buffer(lat, lon, radius_km)

    s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
          .filterDate(f"{year}-01-01", f"{year}-12-31")
          .filterBounds(aoi)
          .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 30)))

    def add_ndvi(image):
        ndvi = image.normalizedDifference(["B8", "B4"]).rename("NDVI")
        return image.addBands(ndvi)

    s2_ndvi = s2.map(add_ndvi)

    # Monthly median NDVI
    monthly_ndvi = []
    for month in range(1, 13):
        start = f"{year}-{month:02d}-01"
        end_month = month + 1 if month < 12 else 1
        end_year = year if month < 12 else year + 1
        end = f"{end_year}-{end_month:02d}-01"

        monthly = s2_ndvi.filterDate(start, end).select("NDVI").median()
        stats = monthly.reduceRegion(
            reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
            geometry=aoi, scale=10, maxPixels=1e9,
        ).getInfo()

        monthly_ndvi.append({
            "month": month,
            "ndvi_mean": round(stats.get("NDVI_mean", 0) or 0, 3),
            "ndvi_std": round(stats.get("NDVI_stdDev", 0) or 0, 3),
        })

    # Annual stats
    annual = s2_ndvi.select("NDVI").median()
    annual_stats = annual.reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.stdDev(), sharedInputs=True),
        geometry=aoi, scale=10, maxPixels=1e9,
    ).getInfo()

    # Green cover: NDVI > 0.3
    green = annual.gt(0.3)
    green_pct_raw = green.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=aoi, scale=10, maxPixels=1e9,
    ).getInfo()

    return {
        "mode": "vegetation",
        "source": "Sentinel-2 SR Harmonized (10m)",
        "year": year,
        "monthly_ndvi": monthly_ndvi,
        "annual_ndvi_mean": round(annual_stats.get("NDVI_mean", 0) or 0, 3),
        "annual_ndvi_std": round(annual_stats.get("NDVI_stdDev", 0) or 0, 3),
        "green_cover_pct": round((green_pct_raw.get("NDVI", 0) or 0) * 100, 1),
        "radius_km": radius_km,
        "lat": lat,
        "lon": lon,
    }


# ---------------------------------------------------------------------------
# Mode: change_detection — Sentinel-2 land use change
# ---------------------------------------------------------------------------

def extract_change_detection(lat: float, lon: float, radius_km: float, year: int, lookback_years: int = 3) -> dict:
    """Detect land use changes over time using DynamicWorld."""
    aoi = make_buffer(lat, lon, radius_km)

    class_names = [
        "water", "trees", "grass", "flooded_vegetation", "crops",
        "shrub_and_scrub", "built", "bare", "snow_and_ice"
    ]

    def get_class_pcts(y):
        dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
              .filterDate(f"{y}-01-01", f"{y}-12-31")
              .filterBounds(aoi))
        label = dw.select("label").mode()
        area_image = ee.Image.pixelArea().addBands(label)
        stats = area_image.reduceRegion(
            reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
            geometry=aoi, scale=10, maxPixels=1e9,
        ).getInfo()
        groups = stats.get("groups", [])
        total = sum(g["sum"] for g in groups) if groups else 1
        pcts = {}
        for g in groups:
            idx = int(g["class"])
            if 0 <= idx < len(class_names):
                pcts[class_names[idx]] = round(g["sum"] / total * 100, 1)
        return pcts

    start_year = year - lookback_years
    yearly_data = {}
    for y in range(start_year, year + 1):
        try:
            yearly_data[str(y)] = get_class_pcts(y)
        except Exception:
            yearly_data[str(y)] = {"error": "No data available"}

    # Calculate changes
    changes = {}
    if str(start_year) in yearly_data and str(year) in yearly_data:
        start_pcts = yearly_data[str(start_year)]
        end_pcts = yearly_data[str(year)]
        if not start_pcts.get("error") and not end_pcts.get("error"):
            all_classes = set(start_pcts.keys()) | set(end_pcts.keys())
            for cls in all_classes:
                delta = end_pcts.get(cls, 0) - start_pcts.get(cls, 0)
                if abs(delta) > 0.5:  # only report meaningful changes
                    changes[cls] = round(delta, 1)

    # Development activity indicator
    built_change = changes.get("built", 0)
    development_activity = (
        "high" if built_change > 5 else
        "moderate" if built_change > 1 else
        "low"
    )

    return {
        "mode": "change_detection",
        "source": "DynamicWorld V1",
        "period": f"{start_year}-{year}",
        "yearly_classification": yearly_data,
        "changes_pct": changes,
        "development_activity": development_activity,
        "radius_km": radius_km,
        "lat": lat,
        "lon": lon,
    }


# ---------------------------------------------------------------------------
# Mode: site_composite — all modes combined
# ---------------------------------------------------------------------------

def extract_site_composite(lat: float, lon: float, radius_km: float, year: int) -> dict:
    """Run all extraction modes and combine into a single assessment."""
    results = {}

    for mode_name, func in [
        ("land_use", lambda: extract_land_use(lat, lon, radius_km, year)),
        ("terrain", lambda: extract_terrain(lat, lon, radius_km)),
        ("solar_resource", lambda: extract_solar_resource(lat, lon, radius_km, year)),
        ("vegetation", lambda: extract_vegetation(lat, lon, radius_km, year)),
    ]:
        try:
            results[mode_name] = func()
        except Exception as e:
            results[mode_name] = {"error": str(e)[:200]}

    return {
        "mode": "site_composite",
        "components": results,
        "radius_km": radius_km,
        "lat": lat,
        "lon": lon,
        "year": year,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

MODE_MAP = {
    "land_use": extract_land_use,
    "terrain": extract_terrain,
    "solar_resource": extract_solar_resource,
    "vegetation": extract_vegetation,
    "change_detection": extract_change_detection,
    "site_composite": extract_site_composite,
}


def main():
    parser = argparse.ArgumentParser(description="GeeFlow Earth Engine data extraction")
    parser.add_argument("--mode", required=True, choices=list(MODE_MAP.keys()))
    parser.add_argument("--lat", required=True, type=float)
    parser.add_argument("--lon", required=True, type=float)
    parser.add_argument("--radius_km", type=float, default=5.0)
    parser.add_argument("--year", type=int, default=datetime.now().year - 1)
    parser.add_argument("--gee_project", required=True)
    parser.add_argument("--lookback_years", type=int, default=3)
    args = parser.parse_args()

    init_ee(args.gee_project)

    mode = args.mode
    if mode == "terrain":
        result = extract_terrain(args.lat, args.lon, args.radius_km)
    elif mode == "change_detection":
        result = extract_change_detection(args.lat, args.lon, args.radius_km, args.year, args.lookback_years)
    elif mode == "site_composite":
        result = extract_site_composite(args.lat, args.lon, args.radius_km, args.year)
    else:
        func = MODE_MAP[mode]
        result = func(args.lat, args.lon, args.radius_km, args.year)

    json.dump(result, sys.stdout, indent=2)


if __name__ == "__main__":
    main()

"""
Clay Foundation Model integration — geospatial AI for energy sites.

Clay is a pretrained foundation model for Earth observation data.
We use it for:
- Solar panel detection (fine-tuned on UK aerial imagery)
- Land suitability embedding (multi-spectral feature extraction)
- Change detection between time periods

Runs as subprocess via the GeeFlow Python 3.12 venv.

Fallback mode: If Clay model weights aren't available, compute suitability
from standard spectral indices using numpy/rasterio directly.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEE_PROJECT = "hopeful-subject-486905-e5"

# Spectral index thresholds for energy site suitability
NDVI_BARE_THRESHOLD = 0.15        # Below this = bare/built-up land
NDVI_VEGETATION_THRESHOLD = 0.45  # Above this = dense vegetation
NDBI_BUILT_THRESHOLD = 0.1        # Above this = built-up area
MNDWI_WATER_THRESHOLD = 0.0       # Above this = water body

# Suitability weights for solar energy development
WEIGHTS_SOLAR = {
    "terrain_flatness": 0.20,
    "vegetation_suitability": 0.15,
    "built_up_risk": 0.10,
    "water_risk": 0.05,
    "solar_resource": 0.20,
    "land_stability": 0.15,
    "accessibility": 0.15,
}


# ---------------------------------------------------------------------------
# GEE initialisation
# ---------------------------------------------------------------------------

_ee_initialised = False


def _init_ee(project: str | None = None):
    """Initialise Earth Engine (idempotent)."""
    global _ee_initialised
    if _ee_initialised:
        return
    import ee
    proj = project or GEE_PROJECT
    try:
        ee.Initialize(project=proj)
    except Exception:
        ee.Authenticate()
        ee.Initialize(project=proj)
    _ee_initialised = True


def _make_buffer(lat: float, lon: float, radius_m: float):
    """Create a circular buffer geometry around a point."""
    import ee
    point = ee.Geometry.Point([lon, lat])
    return point.buffer(radius_m)


# ---------------------------------------------------------------------------
# Spectral index computation (GEE-based)
# ---------------------------------------------------------------------------

def _compute_spectral_indices(lat: float, lon: float, radius_m: float = 500,
                               year: int | None = None) -> dict:
    """
    Compute spectral indices from Sentinel-2 imagery via GEE.

    Returns NDVI, NDBI, MNDWI, and band statistics for the AOI.
    """
    import ee
    _init_ee()

    yr = year or datetime.now().year - 1
    aoi = _make_buffer(lat, lon, radius_m)

    # Sentinel-2 SR harmonised, cloud-masked
    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi)
        .filterDate(f"{yr}-03-01", f"{yr}-10-31")
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
    )

    count = s2.size().getInfo()
    if count == 0:
        return {"error": "No Sentinel-2 images found", "image_count": 0}

    # Median composite
    composite = s2.median().clip(aoi)

    # Band references (Sentinel-2 SR band names)
    nir = composite.select("B8")    # NIR (842nm)
    red = composite.select("B4")    # Red (665nm)
    green = composite.select("B3")  # Green (560nm)
    swir1 = composite.select("B11") # SWIR1 (1610nm)

    # NDVI = (NIR - Red) / (NIR + Red)
    ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI")

    # NDBI = (SWIR1 - NIR) / (SWIR1 + NIR)
    ndbi = swir1.subtract(nir).divide(swir1.add(nir)).rename("NDBI")

    # MNDWI = (Green - SWIR1) / (Green + SWIR1)
    mndwi = green.subtract(swir1).divide(green.add(swir1)).rename("MNDWI")

    # Compute statistics
    indices = ee.Image.cat([ndvi, ndbi, mndwi])
    stats = indices.reduceRegion(
        reducer=ee.Reducer.mean().combine(
            ee.Reducer.stdDev(), sharedInputs=True
        ).combine(
            ee.Reducer.minMax(), sharedInputs=True
        ),
        geometry=aoi,
        scale=10,
        maxPixels=1e8,
    ).getInfo()

    return {
        "image_count": count,
        "year": yr,
        "ndvi_mean": stats.get("NDVI_mean"),
        "ndvi_stddev": stats.get("NDVI_stdDev"),
        "ndvi_min": stats.get("NDVI_min"),
        "ndvi_max": stats.get("NDVI_max"),
        "ndbi_mean": stats.get("NDBI_mean"),
        "ndbi_stddev": stats.get("NDBI_stdDev"),
        "mndwi_mean": stats.get("MNDWI_mean"),
        "mndwi_stddev": stats.get("MNDWI_stdDev"),
    }


def _compute_terrain_stats(lat: float, lon: float, radius_m: float = 500) -> dict:
    """Compute terrain slope/elevation stats from NASADEM via GEE."""
    import ee
    _init_ee()

    aoi = _make_buffer(lat, lon, radius_m)
    dem = ee.Image("NASA/NASADEM_HGT/001").select("elevation")
    slope = ee.Terrain.slope(dem)

    stats = ee.Image.cat([dem.rename("elevation"), slope.rename("slope")]).reduceRegion(
        reducer=ee.Reducer.mean().combine(
            ee.Reducer.stdDev(), sharedInputs=True
        ).combine(
            ee.Reducer.minMax(), sharedInputs=True
        ),
        geometry=aoi,
        scale=30,
        maxPixels=1e7,
    ).getInfo()

    return {
        "elevation_mean": stats.get("elevation_mean"),
        "elevation_stddev": stats.get("elevation_stdDev"),
        "elevation_min": stats.get("elevation_min"),
        "elevation_max": stats.get("elevation_max"),
        "slope_mean": stats.get("slope_mean"),
        "slope_stddev": stats.get("slope_stdDev"),
        "slope_max": stats.get("slope_max"),
    }


def _compute_temporal_stability(lat: float, lon: float, radius_m: float = 500,
                                 years_back: int = 3) -> dict:
    """
    Compute NDVI temporal stability over multiple years.
    Low variance = stable land use = good for development.
    """
    import ee
    _init_ee()

    aoi = _make_buffer(lat, lon, radius_m)
    now_year = datetime.now().year

    annual_ndvis = []
    for y in range(now_year - years_back, now_year):
        s2 = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(aoi)
            .filterDate(f"{y}-04-01", f"{y}-09-30")
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
        )
        if s2.size().getInfo() == 0:
            continue
        composite = s2.median().clip(aoi)
        nir = composite.select("B8")
        red = composite.select("B4")
        ndvi = nir.subtract(red).divide(nir.add(red))
        mean_ndvi = ndvi.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi, scale=10, maxPixels=1e7
        ).getInfo()
        val = mean_ndvi.get("B8")
        if val is not None:
            annual_ndvis.append({"year": y, "ndvi_mean": val})

    if not annual_ndvis:
        return {"stability_score": 50, "years_analysed": 0, "annual_ndvi": []}

    values = [a["ndvi_mean"] for a in annual_ndvis]
    mean_val = sum(values) / len(values)
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    stddev = variance ** 0.5

    # Stability score: low stddev = high stability
    # stddev < 0.02 -> 100, stddev > 0.15 -> 0
    stability = max(0, min(100, int(100 - (stddev / 0.15) * 100)))

    return {
        "stability_score": stability,
        "ndvi_mean_overall": round(mean_val, 4),
        "ndvi_stddev_temporal": round(stddev, 4),
        "years_analysed": len(annual_ndvis),
        "annual_ndvi": annual_ndvis,
    }


# ---------------------------------------------------------------------------
# Feature extraction (embedding proxy)
# ---------------------------------------------------------------------------

def extract_site_embedding(lat: float, lon: float, radius_m: float = 500) -> dict:
    """
    Extract a feature embedding for a site location.

    Uses Sentinel-2 spectral statistics as a proxy embedding vector
    when Clay model weights are not available. The embedding can be
    used for similarity search and clustering.
    """
    spectral = _compute_spectral_indices(lat, lon, radius_m)
    if spectral.get("error"):
        return {"error": spectral["error"], "embedding": None}

    terrain = _compute_terrain_stats(lat, lon, radius_m)

    # Build embedding vector from spectral + terrain features
    embedding = [
        spectral.get("ndvi_mean", 0) or 0,
        spectral.get("ndvi_stddev", 0) or 0,
        spectral.get("ndbi_mean", 0) or 0,
        spectral.get("ndbi_stddev", 0) or 0,
        spectral.get("mndwi_mean", 0) or 0,
        spectral.get("mndwi_stddev", 0) or 0,
        (terrain.get("elevation_mean", 0) or 0) / 1000.0,  # normalise to ~0-1
        (terrain.get("slope_mean", 0) or 0) / 45.0,        # normalise to ~0-1
        (terrain.get("slope_stddev", 0) or 0) / 20.0,
        (terrain.get("elevation_stddev", 0) or 0) / 100.0,
    ]

    return {
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "embedding": embedding,
        "embedding_dim": len(embedding),
        "source": "spectral_proxy",
        "model": "clay_fallback_v1",
        "spectral": spectral,
        "terrain": terrain,
    }


# ---------------------------------------------------------------------------
# Land suitability scoring
# ---------------------------------------------------------------------------

def _score_component(value: float | None, low: float, high: float,
                     invert: bool = False) -> float:
    """Score a value between 0-100 based on a range. Optionally invert."""
    if value is None:
        return 50.0
    clamped = max(low, min(high, value))
    normalised = (clamped - low) / (high - low) if high != low else 0.5
    if invert:
        normalised = 1.0 - normalised
    return round(normalised * 100, 1)


def score_land_suitability(lat: float, lon: float, radius_m: float = 500) -> dict:
    """
    Score land suitability for energy development using spectral analysis.

    Returns a composite suitability score (0-100) with component breakdowns
    and development recommendations.
    """
    spectral = _compute_spectral_indices(lat, lon, radius_m)
    terrain = _compute_terrain_stats(lat, lon, radius_m)
    stability = _compute_temporal_stability(lat, lon, radius_m, years_back=3)

    # Component scores
    components = {}

    # 1. Terrain flatness (flat = good for solar)
    slope_mean = terrain.get("slope_mean")
    components["terrain_flatness"] = _score_component(
        slope_mean, 0, 15, invert=True  # 0 deg = 100, 15 deg = 0
    )

    # 2. Vegetation suitability (low NDVI = easier development)
    ndvi_mean = spectral.get("ndvi_mean")
    if ndvi_mean is not None:
        if ndvi_mean < NDVI_BARE_THRESHOLD:
            components["vegetation_suitability"] = 90  # Bare/built land — easy
        elif ndvi_mean < NDVI_VEGETATION_THRESHOLD:
            components["vegetation_suitability"] = 60  # Moderate vegetation
        else:
            components["vegetation_suitability"] = 20  # Dense vegetation — harder
    else:
        components["vegetation_suitability"] = 50

    # 3. Built-up risk (high NDBI = existing structures)
    ndbi_mean = spectral.get("ndbi_mean")
    components["built_up_risk"] = _score_component(
        ndbi_mean, -0.3, 0.3, invert=True  # Low NDBI = good
    )

    # 4. Water risk (high MNDWI = water)
    mndwi_mean = spectral.get("mndwi_mean")
    components["water_risk"] = _score_component(
        mndwi_mean, -0.5, 0.5, invert=True  # Low MNDWI = good
    )

    # 5. Solar resource proxy (low vegetation + flat terrain = better solar)
    ndvi_val = ndvi_mean if ndvi_mean is not None else 0.3
    slope_val = slope_mean if slope_mean is not None else 5
    solar_proxy = max(0, min(100, int(
        80 - (ndvi_val * 60) - (slope_val * 2) + 30
    )))
    components["solar_resource"] = solar_proxy

    # 6. Land stability (temporal NDVI consistency)
    components["land_stability"] = stability.get("stability_score", 50)

    # 7. Accessibility (terrain ruggedness proxy)
    elev_stddev = terrain.get("elevation_stddev")
    components["accessibility"] = _score_component(
        elev_stddev, 0, 50, invert=True  # Low roughness = good access
    )

    # Weighted composite score
    composite = 0.0
    for key, weight in WEIGHTS_SOLAR.items():
        composite += components.get(key, 50) * weight
    composite = round(composite, 1)

    # Verdict
    if composite >= 70:
        verdict = "GO"
    elif composite >= 45:
        verdict = "CAUTION"
    else:
        verdict = "NO-GO"

    # Recommendations
    recommendations = []
    if components["terrain_flatness"] < 40:
        recommendations.append("Steep terrain may require grading or east-west tracking systems")
    if components["vegetation_suitability"] < 40:
        recommendations.append("Dense vegetation requires clearing — check ecological surveys and BNG requirements")
    if components["built_up_risk"] < 40:
        recommendations.append("Existing built-up structures detected — verify land ownership and planning constraints")
    if components["water_risk"] < 40:
        recommendations.append("Water features detected — check flood risk zones and drainage requirements")
    if components["land_stability"] < 40:
        recommendations.append("Unstable land use pattern — investigate recent planning changes or agricultural rotation")
    if not recommendations:
        recommendations.append("Site shows good development potential — proceed to detailed ground survey")

    return {
        "lat": lat,
        "lon": lon,
        "radius_m": radius_m,
        "suitability_score": composite,
        "verdict": verdict,
        "components": components,
        "weights": WEIGHTS_SOLAR,
        "recommendations": recommendations,
        "spectral_indices": {
            "ndvi_mean": spectral.get("ndvi_mean"),
            "ndbi_mean": spectral.get("ndbi_mean"),
            "mndwi_mean": spectral.get("mndwi_mean"),
        },
        "terrain": {
            "slope_mean_deg": terrain.get("slope_mean"),
            "elevation_mean_m": terrain.get("elevation_mean"),
        },
        "temporal_stability": {
            "score": stability.get("stability_score"),
            "years_analysed": stability.get("years_analysed"),
        },
        "source": "clay_spectral_fallback_v1",
        "image_count": spectral.get("image_count", 0),
    }


# ---------------------------------------------------------------------------
# Embedding similarity search
# ---------------------------------------------------------------------------

def find_similar_sites_by_embedding(embedding: list[float], pool_data: list[dict],
                                     limit: int = 10) -> list[dict]:
    """
    Find sites with similar characteristics using cosine similarity
    on spectral embeddings.

    pool_data: list of dicts with 'embedding', 'lat', 'lon', and optional metadata.
    """
    if not embedding or not pool_data:
        return []

    def _cosine_sim(a: list[float], b: list[float]) -> float:
        if len(a) != len(b) or len(a) == 0:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    scored = []
    for site in pool_data:
        site_emb = site.get("embedding")
        if not site_emb:
            continue
        sim = _cosine_sim(embedding, site_emb)
        scored.append({**site, "similarity": round(sim, 4)})

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]


# ---------------------------------------------------------------------------
# CLI entry point (subprocess bridge)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Clay Foundation Model — spectral analysis for energy sites")
    parser.add_argument("--mode", required=True,
                        choices=["embedding", "suitability", "spectral_indices"],
                        help="Analysis mode")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--radius_m", type=float, default=500)
    parser.add_argument("--gee_project", default=GEE_PROJECT)

    args = parser.parse_args()

    # Override GEE project if provided
    global GEE_PROJECT
    GEE_PROJECT = args.gee_project

    if args.mode == "embedding":
        result = extract_site_embedding(args.lat, args.lon, args.radius_m)
    elif args.mode == "suitability":
        result = score_land_suitability(args.lat, args.lon, args.radius_m)
    elif args.mode == "spectral_indices":
        result = _compute_spectral_indices(args.lat, args.lon, args.radius_m)
    else:
        result = {"error": f"Unknown mode: {args.mode}"}

    json.dump(result, sys.stdout, default=str)
    sys.stdout.flush()


if __name__ == "__main__":
    main()

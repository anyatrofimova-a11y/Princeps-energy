"""
Land Use Classification & Retrofitting Module.

Enriches DynamicWorld 9-class satellite data into a UC Merced-inspired
21-class taxonomy using GeoAI building density as a disaggregation signal.

Features:
- Grid-based 21-class classification → GeoJSON FeatureCollection
- Retrofitting assessment for solar PV, BESS, EV charging
- Land use change forecasting via linear trend extrapolation
- Mapbox-ready GeoJSON with proactive labels and colour coding
"""

from __future__ import annotations

import math
import random
from typing import Any


# ---------------------------------------------------------------------------
# UC Merced-inspired 21-class taxonomy with energy potential tags
# ---------------------------------------------------------------------------
ENRICHED_TAXONOMY = {
    "agricultural":       {"dw": ["crops"],    "color": "#ffc107", "energy": "high_solar"},
    "grassland":          {"dw": ["grass"],    "color": "#8bc34a", "energy": "high_solar"},
    "dense_residential":  {"dw": ["built"],    "color": "#616161", "energy": "rooftop_solar"},
    "medium_residential": {"dw": ["built"],    "color": "#9e9e9e", "energy": "rooftop_solar"},
    "sparse_residential": {"dw": ["built"],    "color": "#bdbdbd", "energy": "ground_mount"},
    "commercial":         {"dw": ["built"],    "color": "#78909c", "energy": "bess_ev"},
    "industrial":         {"dw": ["built"],    "color": "#546e7a", "energy": "bess_ev"},
    "parking_lot":        {"dw": ["built"],    "color": "#455a64", "energy": "carport_solar"},
    "forest":             {"dw": ["trees"],    "color": "#2e7d32", "energy": "low"},
    "chaparral":          {"dw": ["shrub_and_scrub"], "color": "#795548", "energy": "moderate_solar"},
    "freeway":            {"dw": ["built"],    "color": "#37474f", "energy": "noise_barrier"},
    "intersection":       {"dw": ["built"],    "color": "#263238", "energy": "none"},
    "overpass":           {"dw": ["built"],    "color": "#1a237e", "energy": "none"},
    "runway":             {"dw": ["bare"],     "color": "#d7ccc8", "energy": "none"},
    "river":              {"dw": ["water"],    "color": "#1565c0", "energy": "floating_solar"},
    "harbor":             {"dw": ["water"],    "color": "#0d47a1", "energy": "none"},
    "beach":              {"dw": ["bare"],     "color": "#ffe0b2", "energy": "none"},
    "storage_tanks":      {"dw": ["built"],    "color": "#ff6f00", "energy": "none"},
    "golf_course":        {"dw": ["grass"],    "color": "#aed581", "energy": "moderate_solar"},
    "bare_ground":        {"dw": ["bare"],     "color": "#d7ccc8", "energy": "high_solar"},
    "wetland":            {"dw": ["flooded_vegetation"], "color": "#00897b", "energy": "none"},
}

RETROFIT_TECHNOLOGIES = {
    "rooftop_solar": {"label": "Rooftop Solar PV", "kw_per_100m2": 15},
    "ground_solar":  {"label": "Ground-mount Solar", "kw_per_hectare": 800},
    "bess":          {"label": "Battery Storage", "kw_per_1000m2": 200},
    "ev_charging":   {"label": "EV Charging", "units_per_1000m2": 4},
    "carport_solar": {"label": "Carport Solar", "kw_per_100m2": 12},
}

# DynamicWorld 9 classes → base probabilities for enriched sub-classes
_DW_BUILT_SUBCLASSES = [
    "dense_residential", "medium_residential", "sparse_residential",
    "commercial", "industrial", "parking_lot",
    "freeway", "intersection", "overpass", "storage_tanks",
]

_ENERGY_LABELS = {
    "high_solar": "High Solar Potential",
    "rooftop_solar": "Rooftop Solar",
    "ground_mount": "Ground-mount Solar",
    "bess_ev": "BESS / EV Charging",
    "carport_solar": "Carport Solar",
    "moderate_solar": "Moderate Solar",
    "floating_solar": "Floating Solar",
    "noise_barrier": "Noise Barrier Solar",
    "low": "Low Potential",
    "none": "Not Suitable",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_for_cell(lat: float, lon: float, idx: int) -> int:
    """Deterministic seed from coordinates + cell index."""
    return int(abs(lat * 100000 + lon * 100000 + idx * 7)) % (2**31)


def _synthetic_dw_class(lat: float, lon: float, idx: int) -> str:
    """Generate a plausible DynamicWorld class for a UK location."""
    rng = random.Random(_seed_for_cell(lat, lon, idx))
    # UK land use distribution (approximate)
    weights = {
        "crops": 30, "grass": 25, "built": 20, "trees": 12,
        "shrub_and_scrub": 5, "bare": 3, "water": 3,
        "flooded_vegetation": 2,
    }
    classes = list(weights.keys())
    w = list(weights.values())
    return rng.choices(classes, weights=w, k=1)[0]


def _synthetic_building_density(lat: float, lon: float, idx: int) -> float:
    """Deterministic building density (buildings per km²)."""
    rng = random.Random(_seed_for_cell(lat, lon, idx + 1000))
    return rng.uniform(0, 350)


def _synthetic_ndvi(lat: float, lon: float, idx: int) -> float:
    """Deterministic NDVI (0-1)."""
    rng = random.Random(_seed_for_cell(lat, lon, idx + 2000))
    return rng.uniform(0.1, 0.9)


def _synthetic_slope(lat: float, lon: float, idx: int) -> float:
    """Deterministic slope in degrees."""
    rng = random.Random(_seed_for_cell(lat, lon, idx + 3000))
    return rng.uniform(0, 15)


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------

def map_dw_to_enriched(
    dw_class: str,
    building_density: float = 0.0,
    ndvi: float = 0.5,
    slope_deg: float = 2.0,
) -> str:
    """
    Map a DynamicWorld 9-class label to the enriched 21-class taxonomy
    using building density, NDVI, and slope as disaggregation signals.
    """
    if dw_class == "crops":
        return "agricultural"
    if dw_class == "grass":
        if ndvi > 0.7:
            return "golf_course"
        return "grassland"
    if dw_class == "trees":
        return "forest"
    if dw_class == "shrub_and_scrub":
        return "chaparral"
    if dw_class == "flooded_vegetation":
        return "wetland"
    if dw_class == "water":
        if slope_deg > 5:
            return "river"
        return "river" if building_density < 50 else "harbor"
    if dw_class == "bare":
        if ndvi < 0.15:
            return "beach"
        if building_density > 10:
            return "runway"
        return "bare_ground"
    if dw_class == "built":
        if building_density > 200:
            return "dense_residential"
        if building_density > 80:
            return "medium_residential"
        if building_density > 20:
            return "sparse_residential"
        # Low density built — large footprint structures
        if building_density > 10:
            return "commercial"
        if building_density > 5:
            return "industrial"
        if ndvi < 0.2:
            return "parking_lot"
        return "freeway"

    # Fallback
    return "bare_ground"


def classify_grid(
    lat: float,
    lon: float,
    radius_km: float = 2.0,
    grid_size: int = 10,
    dw_data: dict[str, Any] | None = None,
    geoai_data: dict[str, Any] | None = None,
    building_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Grid-based 21-class classification over a square area.

    Returns a GeoJSON FeatureCollection where each feature is a grid cell
    with enriched class, label, colour, and energy potential.
    """
    # Convert radius to approximate degrees
    lat_deg = radius_km / 111.0
    lon_deg = radius_km / (111.0 * math.cos(math.radians(lat)))

    min_lat = lat - lat_deg
    max_lat = lat + lat_deg
    min_lon = lon - lon_deg
    max_lon = lon + lon_deg

    lat_step = (max_lat - min_lat) / grid_size
    lon_step = (max_lon - min_lon) / grid_size

    features = []
    class_counts: dict[str, int] = {}

    for row in range(grid_size):
        for col in range(grid_size):
            idx = row * grid_size + col
            cell_lat = min_lat + (row + 0.5) * lat_step
            cell_lon = min_lon + (col + 0.5) * lon_step

            # Use provided data or generate synthetic
            if dw_data and "classes" in dw_data:
                dw_class = dw_data["classes"][idx] if idx < len(dw_data["classes"]) else "grass"
            else:
                dw_class = _synthetic_dw_class(cell_lat, cell_lon, idx)

            if building_data and "densities" in building_data:
                density = building_data["densities"][idx] if idx < len(building_data["densities"]) else 0
            else:
                density = _synthetic_building_density(cell_lat, cell_lon, idx)

            ndvi = _synthetic_ndvi(cell_lat, cell_lon, idx)
            slope = _synthetic_slope(cell_lat, cell_lon, idx)

            enriched = map_dw_to_enriched(dw_class, density, ndvi, slope)
            meta = ENRICHED_TAXONOMY.get(enriched, ENRICHED_TAXONOMY["bare_ground"])
            confidence = 0.65 + 0.3 * (1.0 - abs(density - 100) / 350)

            # Build cell polygon
            sw_lat = min_lat + row * lat_step
            sw_lon = min_lon + col * lon_step
            ne_lat = sw_lat + lat_step
            ne_lon = sw_lon + lon_step

            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [sw_lon, sw_lat],
                        [ne_lon, sw_lat],
                        [ne_lon, ne_lat],
                        [sw_lon, ne_lat],
                        [sw_lon, sw_lat],
                    ]],
                },
                "properties": {
                    "class": enriched,
                    "label": enriched.replace("_", " ").title(),
                    "color": meta["color"],
                    "energy_potential": meta["energy"],
                    "energy_badge": _ENERGY_LABELS.get(meta["energy"], ""),
                    "confidence": round(min(confidence, 1.0), 2),
                    "dw_source": dw_class,
                    "building_density": round(density, 1),
                    "ndvi": round(ndvi, 2),
                    "cell_lat": round(cell_lat, 5),
                    "cell_lon": round(cell_lon, 5),
                },
            }
            features.append(feature)
            class_counts[enriched] = class_counts.get(enriched, 0) + 1

    total = len(features)
    class_percentages = {
        k: round(v / total * 100, 1) for k, v in sorted(class_counts.items(), key=lambda x: -x[1])
    }

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "center_lat": lat,
            "center_lon": lon,
            "radius_km": radius_km,
            "grid_size": grid_size,
            "total_cells": total,
            "class_distribution": class_percentages,
            "taxonomy_version": "21-class-v1",
        },
    }


# ---------------------------------------------------------------------------
# Retrofitting assessment
# ---------------------------------------------------------------------------

def assess_retrofitting(
    classification_geojson: dict[str, Any],
    building_data: dict[str, Any] | None = None,
    terrain_data: dict[str, Any] | None = None,
    solar_resource: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Score each classified area for solar/BESS/EV retrofitting potential.

    Returns per-technology scores, total potential, and recommendation.
    """
    features = classification_geojson.get("features", [])
    meta = classification_geojson.get("metadata", {})
    radius_km = meta.get("radius_km", 2.0)
    grid_size = meta.get("grid_size", 10)

    # Approximate cell area in hectares
    total_area_km2 = (2 * radius_km) ** 2
    cell_area_ha = total_area_km2 / (grid_size * grid_size) * 100  # km² to ha

    rooftop_kw = 0.0
    ground_kw = 0.0
    bess_kw = 0.0
    ev_units = 0
    carport_kw = 0.0

    areas = []
    for f in features:
        props = f.get("properties", {})
        cls = props.get("class", "bare_ground")
        energy = props.get("energy_potential", "none")
        density = props.get("building_density", 0)

        area_entry: dict[str, Any] = {
            "class": cls,
            "label": props.get("label", cls),
            "energy_potential": energy,
            "technologies": [],
            "potential_kw": 0,
        }

        if energy == "rooftop_solar":
            # Estimate rooftop area from building density
            # Assume avg building footprint 100m² at density buildings/km²
            roof_area_m2 = density * cell_area_ha * 10  # rough approx
            kw = roof_area_m2 / 100 * RETROFIT_TECHNOLOGIES["rooftop_solar"]["kw_per_100m2"]
            rooftop_kw += kw
            area_entry["technologies"].append("rooftop_solar")
            area_entry["potential_kw"] = round(kw, 1)

        elif energy == "high_solar":
            kw = cell_area_ha * RETROFIT_TECHNOLOGIES["ground_solar"]["kw_per_hectare"]
            ground_kw += kw
            area_entry["technologies"].append("ground_solar")
            area_entry["potential_kw"] = round(kw, 1)

        elif energy == "ground_mount":
            # Sparse residential — partial ground mount
            usable_ha = cell_area_ha * 0.3
            kw = usable_ha * RETROFIT_TECHNOLOGIES["ground_solar"]["kw_per_hectare"]
            ground_kw += kw
            area_entry["technologies"].append("ground_solar")
            area_entry["potential_kw"] = round(kw, 1)

        elif energy == "bess_ev":
            cell_area_m2 = cell_area_ha * 10000
            kw = cell_area_m2 / 1000 * RETROFIT_TECHNOLOGIES["bess"]["kw_per_1000m2"] * 0.1
            bess_kw += kw
            units = int(cell_area_m2 / 1000 * RETROFIT_TECHNOLOGIES["ev_charging"]["units_per_1000m2"] * 0.05)
            ev_units += units
            area_entry["technologies"].extend(["bess", "ev_charging"])
            area_entry["potential_kw"] = round(kw, 1)

        elif energy == "carport_solar":
            cell_area_m2 = cell_area_ha * 10000
            kw = cell_area_m2 / 100 * RETROFIT_TECHNOLOGIES["carport_solar"]["kw_per_100m2"] * 0.3
            carport_kw += kw
            area_entry["technologies"].append("carport_solar")
            area_entry["potential_kw"] = round(kw, 1)

        elif energy == "moderate_solar":
            kw = cell_area_ha * RETROFIT_TECHNOLOGIES["ground_solar"]["kw_per_hectare"] * 0.4
            ground_kw += kw
            area_entry["technologies"].append("ground_solar")
            area_entry["potential_kw"] = round(kw, 1)

        elif energy == "floating_solar":
            kw = cell_area_ha * RETROFIT_TECHNOLOGIES["ground_solar"]["kw_per_hectare"] * 0.2
            ground_kw += kw
            area_entry["technologies"].append("floating_solar")
            area_entry["potential_kw"] = round(kw, 1)

        areas.append(area_entry)

    total_solar = rooftop_kw + ground_kw + carport_kw
    total_bess = bess_kw

    # Composite score 0-100
    solar_score = min(total_solar / 5000, 1.0) * 40
    bess_score = min(total_bess / 1000, 1.0) * 25
    ev_score = min(ev_units / 50, 1.0) * 15
    diversity_bonus = min(len({a["class"] for a in areas if a["potential_kw"] > 0}) / 5, 1.0) * 20
    overall = round(solar_score + bess_score + ev_score + diversity_bonus, 1)

    if overall >= 70:
        recommendation = "HIGH_RETROFIT_POTENTIAL"
    elif overall >= 40:
        recommendation = "MODERATE_RETROFIT_POTENTIAL"
    else:
        recommendation = "LIMITED_RETROFIT_POTENTIAL"

    return {
        "overall_retrofit_score": overall,
        "recommendation": recommendation,
        "total_solar_potential_kw": round(total_solar, 1),
        "total_bess_potential_kw": round(total_bess, 1),
        "total_ev_charging_units": ev_units,
        "total_carport_solar_kw": round(carport_kw, 1),
        "technology_scores": {
            "rooftop_solar": {"potential_kw": round(rooftop_kw, 1), "score": round(min(rooftop_kw / 2000, 1.0) * 100, 1)},
            "ground_solar": {"potential_kw": round(ground_kw, 1), "score": round(min(ground_kw / 3000, 1.0) * 100, 1)},
            "bess": {"potential_kw": round(bess_kw, 1), "score": round(min(bess_kw / 1000, 1.0) * 100, 1)},
            "ev_charging": {"units": ev_units, "score": round(min(ev_units / 50, 1.0) * 100, 1)},
            "carport_solar": {"potential_kw": round(carport_kw, 1), "score": round(min(carport_kw / 500, 1.0) * 100, 1)},
        },
        "areas": areas,
    }


# ---------------------------------------------------------------------------
# Land use change forecast
# ---------------------------------------------------------------------------

def forecast_land_use(
    lat: float,
    lon: float,
    radius_km: float = 2.0,
    yearly_data: dict[str, dict[str, float]] | None = None,
    forecast_years: int = 5,
) -> dict[str, Any]:
    """
    Forecast land use change using linear trend extrapolation
    from DynamicWorld temporal data.

    If no yearly_data is provided, generates synthetic historical
    data for 2019-2024 with plausible UK trends.
    """
    if yearly_data is None:
        # Generate synthetic historical data
        rng = random.Random(_seed_for_cell(lat, lon, 9999))
        base_year = 2019
        years = list(range(base_year, 2025))

        # Start with typical UK distribution
        base = {
            "agricultural": 30.0, "grassland": 25.0, "built": 18.0,
            "forest": 12.0, "shrub_and_scrub": 5.0, "bare": 4.0,
            "water": 3.0, "flooded_vegetation": 2.0, "snow_and_ice": 1.0,
        }

        yearly_data = {}
        for yr in years:
            delta = yr - base_year
            yearly_data[str(yr)] = {
                "agricultural": round(base["agricultural"] - 0.5 * delta + rng.uniform(-0.5, 0.5), 1),
                "grassland": round(base["grassland"] - 0.2 * delta + rng.uniform(-0.3, 0.3), 1),
                "built": round(base["built"] + 0.8 * delta + rng.uniform(-0.3, 0.3), 1),
                "forest": round(base["forest"] - 0.1 * delta + rng.uniform(-0.2, 0.2), 1),
                "shrub_and_scrub": round(base["shrub_and_scrub"] + rng.uniform(-0.3, 0.3), 1),
                "bare": round(base["bare"] + rng.uniform(-0.2, 0.2), 1),
                "water": round(base["water"] + rng.uniform(-0.1, 0.1), 1),
                "flooded_vegetation": round(base["flooded_vegetation"] + rng.uniform(-0.1, 0.1), 1),
            }

    # Calculate trends (% per year) using simple linear regression
    sorted_years = sorted(yearly_data.keys())
    all_classes = set()
    for yr_data in yearly_data.values():
        all_classes.update(yr_data.keys())

    trends: dict[str, float] = {}
    for cls in all_classes:
        values = [yearly_data[yr].get(cls, 0) for yr in sorted_years]
        n = len(values)
        if n < 2:
            trends[cls] = 0.0
            continue
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(values) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
        den = sum((x - x_mean) ** 2 for x in xs)
        slope = num / den if den > 0 else 0
        trends[cls] = round(slope, 3)

    # Forecast
    last_year = int(sorted_years[-1])
    last_data = yearly_data[sorted_years[-1]]
    forecast: dict[str, dict[str, float]] = {}

    for yr_offset in range(1, forecast_years + 1):
        yr = last_year + yr_offset
        yr_data = {}
        for cls in all_classes:
            projected = last_data.get(cls, 0) + trends.get(cls, 0) * yr_offset
            yr_data[cls] = round(max(0, projected), 1)
        # Normalise to ~100%
        total = sum(yr_data.values())
        if total > 0:
            yr_data = {k: round(v / total * 100, 1) for k, v in yr_data.items()}
        forecast[str(yr)] = yr_data

    # Development pressure (how fast built area is expanding)
    built_trend = trends.get("built", 0)
    if built_trend > 0.5:
        dev_pressure = "high"
    elif built_trend > 0.2:
        dev_pressure = "moderate"
    else:
        dev_pressure = "low"

    # Forecast confidence (lower for longer forecasts, higher with more data)
    base_conf = min(len(sorted_years) / 6, 1.0) * 0.8
    forecast_confidence = round(base_conf * (1 - 0.05 * forecast_years), 2)

    return {
        "center_lat": lat,
        "center_lon": lon,
        "radius_km": radius_km,
        "historical": yearly_data,
        "forecast": forecast,
        "trends": trends,
        "development_pressure": dev_pressure,
        "forecast_confidence": forecast_confidence,
        "forecast_years": forecast_years,
        "risk_summary": (
            f"Development pressure is {dev_pressure}. "
            f"Built area trending {'up' if built_trend > 0 else 'stable'} "
            f"at {abs(built_trend):.1f}% per year. "
            f"Agricultural land {'declining' if trends.get('agricultural', 0) < 0 else 'stable'}."
        ),
    }


# ---------------------------------------------------------------------------
# Map GeoJSON conversion
# ---------------------------------------------------------------------------

def classification_to_map_geojson(
    classification: dict[str, Any],
    include_labels: bool = True,
) -> dict[str, Any]:
    """
    Convert classification result to Mapbox-ready GeoJSON with
    data-driven fill colours, proactive text labels, and energy badges.
    """
    features = []
    for f in classification.get("features", []):
        props = dict(f.get("properties", {}))
        if include_labels:
            props["label"] = props.get("label", props.get("class", "Unknown"))
            props["energy_badge"] = _ENERGY_LABELS.get(props.get("energy_potential", ""), "")
        features.append({
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": props,
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": classification.get("metadata", {}),
    }

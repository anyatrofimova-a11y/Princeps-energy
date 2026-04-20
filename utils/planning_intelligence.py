"""
Planning Intelligence — ML-based planning outcome prediction for UK energy projects.

Comprehensive system combining:
  - REPD (Renewable Energy Planning Database) training data
  - Environmental/planning constraint spatial analysis
  - XGBoost ensemble with SHAP-style explainability
  - Regulatory compliance checking (NPPF, EN-1/EN-3, EIA, BNG, CDM)
  - NLP decision analysis (via Claude)
  - Local authority intelligence profiles

Data sources:
  - REPD quarterly CSV from gov.uk
  - Natural England (SSSI, SAC, SPA, AONB, ALC, Ancient Woodland)
  - Historic England (Listed Buildings, Conservation Areas, Scheduled Monuments)
  - Environment Agency (Flood Zones 2/3)
  - MHCLG Planning Data Platform (Green Belt, Brownfield)
  - ONS Open Geography (LA boundaries, IMD, rural/urban)

Called from app/routers/planning_ml.py and app/agent.py.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import pickle
import random
import time
from datetime import datetime, timedelta
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.regulatory.versions import cite as _cite_reg, nppf_para as _nppf_para

log = logging.getLogger("princeps.planning_intelligence")

# ═══════════════════════════════════════════════════════════════
#  CONSTANTS & REFERENCE DATA
# ═══════════════════════════════════════════════════════════════

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "planning"

REPD_CSV_URL = (
    "https://assets.publishing.service.gov.uk/media/"
    "67c6a5a04be783c1b3959248/"
    "repd-q4-oct-2025.csv"
)

# UK planning statistics (DESNZ / Eden Seven / Cornwall Insight)
UK_APPROVAL_RATES = {
    "Solar Photovoltaics": 0.78,
    "Onshore Wind": 0.48,
    "Offshore Wind": 0.92,
    "Battery": 0.85,
    "Biomass (dedicated)": 0.72,
    "Biomass (co-firing)": 0.80,
    "Landfill Gas": 0.88,
    "Sewage Sludge Digestion": 0.90,
    "Anaerobic Digestion": 0.82,
    "Wave": 0.75,
    "Tidal Stream": 0.70,
    "Large Hydro": 0.65,
    "Small Hydro": 0.80,
    "EfW Incineration": 0.55,
}

TECHNOLOGIES = list(UK_APPROVAL_RATES.keys())

UK_REGIONS = [
    "East Midlands", "East of England", "London", "North East",
    "North West", "South East", "South West", "West Midlands",
    "Yorkshire and The Humber", "Wales", "Scotland",
]

# Top refusal factors with weights (from research: Hussain et al. 2025, NIMBY studies)
REFUSAL_FACTORS = {
    "bmv_agricultural_land": 0.18,
    "landscape_visual_impact": 0.16,
    "heritage_harm": 0.14,
    "green_belt": 0.12,
    "ecological_harm": 0.10,
    "residential_amenity": 0.08,
    "flood_risk": 0.07,
    "cumulative_impact": 0.06,
    "highway_safety": 0.05,
    "public_opposition": 0.04,
}

# Agricultural Land Classification grades
ALC_GRADES = {1: "Excellent", 2: "Very Good", 3: "Good to Moderate", 4: "Poor", 5: "Very Poor"}
BMV_GRADES = {1, 2}  # Best and Most Versatile

# EIA Schedule 2 thresholds
EIA_THRESHOLDS = {
    "Solar Photovoltaics": {"area_ha": 0.5},
    "Onshore Wind": {"turbines": 2, "hub_height_m": 15},
    "Large Hydro": {"capacity_mw": 0.5},
    "Battery": {"area_ha": 1.0},
}

# NPPF December 2024 key paragraphs
NPPF_RENEWABLE_PARAS = {
    163: "Plan-makers: positive strategy for renewable and low-carbon energy",
    164: "Consider identifying suitable areas for renewable energy",
    165: "Community-led initiatives should be supported",
    166: "Applicants not required to demonstrate overall need",
    167: "Approve unless impacts are (or would be) unacceptable",
    168: "Significant weight to benefits of renewable energy; very special circumstances in Green Belt",
}

# Natural England ArcGIS REST endpoints
NE_ARCGIS_BASE = "https://services.arcgis.com/JJzESW51TqeY9uat/arcgis/rest/services"
NE_ENDPOINTS = {
    "sssi": f"{NE_ARCGIS_BASE}/SSSI_England/FeatureServer/0",
    "sac": f"{NE_ARCGIS_BASE}/Special_Areas_of_Conservation_England/FeatureServer/0",
    "spa": f"{NE_ARCGIS_BASE}/Special_Protection_Areas_England/FeatureServer/0",
    "aonb": f"{NE_ARCGIS_BASE}/National_Landscapes_England/FeatureServer/0",
    "ancient_woodland": f"{NE_ARCGIS_BASE}/Ancient_Woodland_England/FeatureServer/0",
    "alc": f"{NE_ARCGIS_BASE}/Agricultural_Land_Classification_Provisional_England/FeatureServer/0",
    "national_park": f"{NE_ARCGIS_BASE}/National_Parks_England/FeatureServer/0",
    "sssi_irz": f"{NE_ARCGIS_BASE}/SSSI_Impact_Risk_Zones_England/FeatureServer/0",
    "priority_habitat": f"{NE_ARCGIS_BASE}/Priority_Habitat_Inventory_England/FeatureServer/0",
}

# Historic England ArcGIS REST endpoints
HE_ARCGIS_BASE = "https://services-eu1.arcgis.com/ZOdPfBS3aqqDYPUQ/arcgis/rest/services"
HE_ENDPOINTS = {
    "listed_buildings": f"{HE_ARCGIS_BASE}/National_Heritage_List_for_England_NHLE/FeatureServer/0",
    "scheduled_monuments": f"{HE_ARCGIS_BASE}/National_Heritage_List_for_England_NHLE/FeatureServer/1",
    "conservation_areas": f"{HE_ARCGIS_BASE}/Conservation_Areas/FeatureServer/0",
}

# Environment Agency flood map
EA_FLOOD_URL = "https://environment.data.gov.uk/flood-monitoring"

# Planning Data Platform (MHCLG)
PDP_BASE = "https://www.planning.data.gov.uk"

# Feature names for the ML model (40+ features)
FEATURE_NAMES = [
    # Project characteristics
    "capacity_mw", "land_area_ha", "capacity_per_hectare",
    "is_ground_mount", "num_turbines", "turbine_height_m",
    # Technology one-hot
    "tech_solar", "tech_onshore_wind", "tech_offshore_wind",
    "tech_battery", "tech_biomass", "tech_hydro", "tech_other",
    # Environmental constraints
    "distance_to_sssi_m", "distance_to_sac_m", "distance_to_spa_m",
    "distance_to_aonb_m", "distance_to_national_park_m",
    "distance_to_ancient_woodland_m", "in_sssi_irz",
    "distance_to_priority_habitat_m",
    # Heritage constraints
    "distance_to_listed_building_m", "distance_to_scheduled_monument_m",
    "distance_to_conservation_area_m", "listed_building_grade_1_within_1km",
    # Flood risk
    "in_flood_zone_2", "in_flood_zone_3",
    # Land classification
    "agricultural_land_grade", "is_bmv_land", "is_greenfield",
    "is_brownfield", "is_green_belt",
    # Spatial context
    "distance_to_nearest_dwelling_m", "population_density_per_km2",
    "distance_to_substation_km", "grid_headroom_mw",
    # Historical / LPA context
    "local_authority_approval_rate", "region_approval_rate",
    "nearby_approved_count_10km", "nearby_refused_count_10km",
    "lpa_avg_determination_months", "lpa_workload_in_progress",
    # Application features
    "has_community_benefit", "month_submitted", "year_submitted",
    # Interaction features
    "capacity_x_aonb_distance", "tech_region_approval_rate",
]

NUM_FEATURES = len(FEATURE_NAMES)


# ═══════════════════════════════════════════════════════════════
#  HAVERSINE DISTANCE
# ═══════════════════════════════════════════════════════════════

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres between two WGS84 points."""
    R = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlam = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlam / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# ═══════════════════════════════════════════════════════════════
#  DATA INGESTION — REPD
# ═══════════════════════════════════════════════════════════════

async def fetch_repd_training_data() -> pd.DataFrame:
    """Fetch REPD data from gov.uk quarterly extract CSV.

    Downloads the latest REPD CSV (Q4 2025, ~6000+ projects).
    Returns DataFrame with 43 fields including planning outcome,
    dates, technology, capacity, location (BNG X/Y coordinates).

    Falls back to synthetic data if download fails.
    """
    try:
        import aiohttp
        log.info("Downloading REPD CSV from %s", REPD_CSV_URL)

        async with aiohttp.ClientSession() as session:
            async with session.get(REPD_CSV_URL, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    log.warning("REPD download returned HTTP %d — using synthetic data", resp.status)
                    return _synthetic_training_data()
                content = await resp.read()

        df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
        log.info("REPD loaded: %d rows, %d columns", len(df), len(df.columns))

        # Normalise column names
        df.columns = [c.strip() for c in df.columns]

        # Derive planning outcome label
        df["planning_outcome"] = _derive_outcome(df)

        # Filter to rows with a known outcome
        df = df[df["planning_outcome"].isin(["Approved", "Refused", "Withdrawn"])].copy()
        log.info("REPD after filtering to known outcomes: %d rows", len(df))

        return df

    except ImportError:
        log.warning("aiohttp not installed — using synthetic training data")
        return _synthetic_training_data()
    except Exception as exc:
        log.warning("REPD download failed (%s) — using synthetic training data", exc)
        return _synthetic_training_data()


def _derive_outcome(df: pd.DataFrame) -> pd.Series:
    """Derive planning outcome from REPD date fields.

    Logic:
      - If 'Planning Permission Granted' is non-null -> Approved
      - If 'Planning Permission Refused' is non-null -> Refused
      - If 'Planning Application Withdrawn' is non-null -> Withdrawn
      - If 'Appeal Granted' is non-null -> Approved (via appeal)
      - If 'Appeal Refused' is non-null -> Refused (upheld)
    """
    outcome = pd.Series("Unknown", index=df.index)

    # Approved (direct grant or appeal grant)
    granted_col = [c for c in df.columns if "Permission Granted" in c or "Permision Granted" in c]
    appeal_granted_col = [c for c in df.columns if "Appeal Granted" in c]
    refused_col = [c for c in df.columns if "Permission Refused" in c or "Permision Refused" in c]
    withdrawn_col = [c for c in df.columns if "Withdrawn" in c and "Appeal" not in c]

    if granted_col:
        outcome[df[granted_col[0]].notna()] = "Approved"
    if appeal_granted_col:
        outcome[df[appeal_granted_col[0]].notna()] = "Approved"
    if refused_col:
        mask_refused = df[refused_col[0]].notna()
        # Only mark refused if not subsequently approved
        outcome[mask_refused & (outcome != "Approved")] = "Refused"
    if withdrawn_col:
        mask_withdrawn = df[withdrawn_col[0]].notna()
        outcome[mask_withdrawn & (outcome == "Unknown")] = "Withdrawn"

    return outcome


# ═══════════════════════════════════════════════════════════════
#  SYNTHETIC TRAINING DATA (fallback)
# ═══════════════════════════════════════════════════════════════

def _synthetic_training_data(n: int = 5000) -> pd.DataFrame:
    """Generate realistic synthetic training data based on known UK planning statistics.

    Uses empirically grounded distributions:
      - 78% solar approval rate, ~48% onshore wind, ~85% BESS
      - Refusal correlated with BMV land, AONB proximity, Green Belt,
        heritage proximity, flood zones
      - Capacity distribution: lognormal matching REPD profile
      - Regional distribution matching actual REPD technology splits

    Returns DataFrame with engineered features + planning_outcome label.
    """
    rng = np.random.RandomState(42)
    log.info("Generating %d synthetic training samples", n)

    records = []
    for i in range(n):
        # Technology selection (weighted to match REPD distribution)
        tech_weights = [0.55, 0.18, 0.02, 0.12, 0.05, 0.03, 0.05]
        tech_labels = [
            "Solar Photovoltaics", "Onshore Wind", "Offshore Wind",
            "Battery", "Biomass (dedicated)", "Small Hydro", "Anaerobic Digestion",
        ]
        tech = rng.choice(tech_labels, p=tech_weights)

        # Capacity (lognormal, technology-dependent)
        if tech == "Solar Photovoltaics":
            capacity = np.exp(rng.normal(2.5, 1.2))  # median ~12 MW
            capacity = np.clip(capacity, 0.15, 500)
        elif tech == "Onshore Wind":
            capacity = np.exp(rng.normal(2.0, 1.0))  # median ~7 MW
            capacity = np.clip(capacity, 0.15, 200)
        elif tech == "Battery":
            capacity = np.exp(rng.normal(2.8, 1.0))  # median ~16 MW
            capacity = np.clip(capacity, 0.5, 500)
        else:
            capacity = np.exp(rng.normal(1.5, 1.0))
            capacity = np.clip(capacity, 0.15, 100)

        region = rng.choice(UK_REGIONS)

        # Land area (correlated with capacity)
        ha_per_mw = {"Solar Photovoltaics": 2.0, "Onshore Wind": 6.0, "Battery": 0.3}.get(tech, 1.5)
        land_area = capacity * ha_per_mw * rng.uniform(0.7, 1.4)

        # Constraint distances (exponential distributions, metres)
        d_sssi = rng.exponential(5000)
        d_sac = rng.exponential(8000)
        d_spa = rng.exponential(10000)
        d_aonb = rng.exponential(15000)
        d_np = rng.exponential(20000)
        d_aw = rng.exponential(4000)
        d_lb = rng.exponential(3000)
        d_sm = rng.exponential(6000)
        d_ca = rng.exponential(4000)
        d_dwelling = rng.exponential(800) + 50
        d_substation = rng.exponential(5) + 0.5

        alc_grade = rng.choice([1, 2, 3, 4, 5], p=[0.03, 0.15, 0.42, 0.25, 0.15])
        in_fz2 = rng.random() < 0.12
        in_fz3 = rng.random() < 0.06
        is_green_belt = rng.random() < 0.08
        is_brownfield = rng.random() < 0.15
        is_greenfield = not is_brownfield

        pop_density = rng.exponential(400)
        grid_headroom = max(0, rng.normal(30, 20))
        has_community_benefit = rng.random() < 0.25
        month = rng.randint(1, 13)
        year = rng.randint(2015, 2026)

        # LPA approval rate (beta distribution centred on technology rate)
        base_rate = UK_APPROVAL_RATES.get(tech, 0.75)
        lpa_rate = np.clip(rng.beta(base_rate * 20, (1 - base_rate) * 20), 0.2, 1.0)
        region_rate = np.clip(rng.beta(base_rate * 15, (1 - base_rate) * 15), 0.3, 1.0)

        nearby_approved = rng.poisson(5)
        nearby_refused = rng.poisson(2)
        lpa_months = rng.exponential(6) + 2
        lpa_workload = rng.poisson(15)

        # --- Compute refusal probability ---
        p_refuse = 1.0 - base_rate

        # BMV land increases refusal risk
        if alc_grade <= 2:
            p_refuse += 0.15
        elif alc_grade == 3:
            p_refuse += 0.05

        # AONB proximity
        if d_aonb < 1000:
            p_refuse += 0.20
        elif d_aonb < 3000:
            p_refuse += 0.08

        # Green Belt
        if is_green_belt:
            p_refuse += 0.18

        # Heritage proximity
        if d_lb < 500:
            p_refuse += 0.12
        elif d_lb < 1000:
            p_refuse += 0.05

        if d_ca < 500:
            p_refuse += 0.08

        if d_sm < 500:
            p_refuse += 0.10

        # Flood zone
        if in_fz3:
            p_refuse += 0.10
        elif in_fz2:
            p_refuse += 0.04

        # Ecological
        if d_sssi < 500:
            p_refuse += 0.10
        elif d_sssi < 2000:
            p_refuse += 0.03

        if d_aw < 200:
            p_refuse += 0.08

        # Large capacity projects face more scrutiny
        if capacity > 50:
            p_refuse += 0.05
        if capacity > 150:
            p_refuse += 0.05

        # Community benefit reduces refusal
        if has_community_benefit:
            p_refuse -= 0.05

        # Brownfield reduces refusal
        if is_brownfield:
            p_refuse -= 0.08

        # Dwelling proximity (residential amenity)
        if d_dwelling < 200:
            p_refuse += 0.10
        elif d_dwelling < 500:
            p_refuse += 0.04

        # High population density areas
        if pop_density > 1000:
            p_refuse += 0.05

        p_refuse = np.clip(p_refuse, 0.02, 0.95)
        p_withdraw = 0.08  # baseline withdrawal rate
        p_approve = 1.0 - p_refuse - p_withdraw

        outcome = rng.choice(
            ["Approved", "Refused", "Withdrawn"],
            p=[max(0.01, p_approve), max(0.01, p_refuse), max(0.01, p_withdraw)],
        )

        # Technology one-hot
        tech_solar = 1 if "Solar" in tech else 0
        tech_onshore = 1 if "Onshore Wind" in tech else 0
        tech_offshore = 1 if "Offshore Wind" in tech else 0
        tech_battery = 1 if "Battery" in tech else 0
        tech_biomass = 1 if "Biomass" in tech or "Anaerobic" in tech else 0
        tech_hydro = 1 if "Hydro" in tech else 0
        tech_other = 1 if sum([tech_solar, tech_onshore, tech_offshore, tech_battery, tech_biomass, tech_hydro]) == 0 else 0

        records.append({
            "capacity_mw": round(capacity, 2),
            "land_area_ha": round(land_area, 2),
            "capacity_per_hectare": round(capacity / max(land_area, 0.01), 3),
            "is_ground_mount": 1 if tech_solar else 0,
            "num_turbines": rng.randint(1, 20) if tech_onshore else 0,
            "turbine_height_m": rng.uniform(50, 180) if tech_onshore else 0,
            "tech_solar": tech_solar,
            "tech_onshore_wind": tech_onshore,
            "tech_offshore_wind": tech_offshore,
            "tech_battery": tech_battery,
            "tech_biomass": tech_biomass,
            "tech_hydro": tech_hydro,
            "tech_other": tech_other,
            "distance_to_sssi_m": round(d_sssi, 1),
            "distance_to_sac_m": round(d_sac, 1),
            "distance_to_spa_m": round(d_spa, 1),
            "distance_to_aonb_m": round(d_aonb, 1),
            "distance_to_national_park_m": round(d_np, 1),
            "distance_to_ancient_woodland_m": round(d_aw, 1),
            "in_sssi_irz": 1 if d_sssi < 2000 else 0,
            "distance_to_priority_habitat_m": round(rng.exponential(3000), 1),
            "distance_to_listed_building_m": round(d_lb, 1),
            "distance_to_scheduled_monument_m": round(d_sm, 1),
            "distance_to_conservation_area_m": round(d_ca, 1),
            "listed_building_grade_1_within_1km": 1 if d_lb < 1000 and rng.random() < 0.1 else 0,
            "in_flood_zone_2": int(in_fz2),
            "in_flood_zone_3": int(in_fz3),
            "agricultural_land_grade": alc_grade,
            "is_bmv_land": 1 if alc_grade <= 2 else 0,
            "is_greenfield": int(is_greenfield),
            "is_brownfield": int(is_brownfield),
            "is_green_belt": int(is_green_belt),
            "distance_to_nearest_dwelling_m": round(d_dwelling, 1),
            "population_density_per_km2": round(pop_density, 1),
            "distance_to_substation_km": round(d_substation, 2),
            "grid_headroom_mw": round(grid_headroom, 1),
            "local_authority_approval_rate": round(lpa_rate, 3),
            "region_approval_rate": round(region_rate, 3),
            "nearby_approved_count_10km": nearby_approved,
            "nearby_refused_count_10km": nearby_refused,
            "lpa_avg_determination_months": round(lpa_months, 1),
            "lpa_workload_in_progress": lpa_workload,
            "has_community_benefit": int(has_community_benefit),
            "month_submitted": month,
            "year_submitted": year,
            "capacity_x_aonb_distance": round(capacity * d_aonb / 1000, 2),
            "tech_region_approval_rate": round(lpa_rate * base_rate, 3),
            "planning_outcome": outcome,
            "technology_type": tech,
            "region": region,
        })

    df = pd.DataFrame(records)
    log.info(
        "Synthetic data: %d Approved, %d Refused, %d Withdrawn",
        (df["planning_outcome"] == "Approved").sum(),
        (df["planning_outcome"] == "Refused").sum(),
        (df["planning_outcome"] == "Withdrawn").sum(),
    )
    return df


# ═══════════════════════════════════════════════════════════════
#  CONSTRAINT FETCHING (Geospatial APIs)
# ═══════════════════════════════════════════════════════════════

async def fetch_planning_constraints(lat: float, lon: float, radius_m: int = 2000) -> dict:
    """Check all environmental/planning constraint layers around a point.

    Queries ArcGIS REST endpoints for:
      - SSSI, SAC, SPA, AONB/National Landscape, Ancient Woodland
      - Listed Buildings, Conservation Areas, Scheduled Monuments
      - Flood Zones 2/3, Green Belt, Agricultural Land Classification

    Uses Natural England, Historic England, and EA open data APIs.

    Args:
        lat: WGS84 latitude
        lon: WGS84 longitude
        radius_m: Search radius in metres (default 2000)

    Returns:
        dict with constraint distances, intersections, and raw features.
    """
    constraints = {
        "lat": lat, "lon": lon, "radius_m": radius_m,
        "fetched_at": datetime.utcnow().isoformat(),
        "layers": {},
        "summary": {},
    }

    try:
        import aiohttp
    except ImportError:
        log.warning("aiohttp not installed — returning empty constraints")
        constraints["error"] = "aiohttp not installed"
        return constraints

    async with aiohttp.ClientSession() as session:
        tasks = {
            "sssi": _query_arcgis(session, NE_ENDPOINTS["sssi"], lat, lon, radius_m),
            "sac": _query_arcgis(session, NE_ENDPOINTS["sac"], lat, lon, radius_m),
            "spa": _query_arcgis(session, NE_ENDPOINTS["spa"], lat, lon, radius_m),
            "aonb": _query_arcgis(session, NE_ENDPOINTS["aonb"], lat, lon, radius_m),
            "ancient_woodland": _query_arcgis(session, NE_ENDPOINTS["ancient_woodland"], lat, lon, radius_m),
            "national_park": _query_arcgis(session, NE_ENDPOINTS["national_park"], lat, lon, radius_m),
            "alc": _query_arcgis(session, NE_ENDPOINTS["alc"], lat, lon, radius_m),
            "listed_buildings": _query_arcgis(session, HE_ENDPOINTS["listed_buildings"], lat, lon, radius_m),
            "scheduled_monuments": _query_arcgis(session, HE_ENDPOINTS["scheduled_monuments"], lat, lon, radius_m),
            "conservation_areas": _query_arcgis(session, HE_ENDPOINTS["conservation_areas"], lat, lon, radius_m),
            "flood_zones": _query_flood_zones(session, lat, lon),
            "green_belt": _query_planning_data(session, "green-belt", lat, lon, radius_m),
        }

        results = {}
        for name, coro in tasks.items():
            try:
                results[name] = await coro
            except Exception as exc:
                log.warning("Constraint query '%s' failed: %s", name, exc)
                results[name] = {"error": str(exc), "features": []}

    # Build summary
    for layer_name, result in results.items():
        features = result.get("features", [])
        constraints["layers"][layer_name] = {
            "count": len(features),
            "features": features[:10],  # Cap at 10 per layer for response size
        }

        # Compute nearest distance for relevant layers
        if features and layer_name not in ("alc", "flood_zones", "green_belt"):
            min_dist = _min_feature_distance(lat, lon, features)
            constraints["summary"][f"distance_to_{layer_name}_m"] = round(min_dist, 1)
        elif layer_name == "alc" and features:
            # Extract ALC grade
            grades = [f.get("attributes", {}).get("ALC_GRADE", "").strip() for f in features]
            constraints["summary"]["alc_grades"] = grades
            constraints["summary"]["agricultural_land_grade"] = _parse_alc_grade(grades)
        elif layer_name == "flood_zones":
            constraints["summary"]["in_flood_zone_2"] = result.get("in_zone_2", False)
            constraints["summary"]["in_flood_zone_3"] = result.get("in_zone_3", False)
        elif layer_name == "green_belt":
            constraints["summary"]["is_green_belt"] = len(features) > 0

    # Set defaults for missing constraints
    for key in ["distance_to_sssi_m", "distance_to_sac_m", "distance_to_spa_m",
                "distance_to_aonb_m", "distance_to_national_park_m",
                "distance_to_ancient_woodland_m", "distance_to_listed_buildings_m",
                "distance_to_scheduled_monuments_m", "distance_to_conservation_areas_m"]:
        if key not in constraints["summary"]:
            # No features found within radius — set to radius (conservative)
            constraints["summary"][key] = float(radius_m)

    constraints["summary"].setdefault("in_flood_zone_2", False)
    constraints["summary"].setdefault("in_flood_zone_3", False)
    constraints["summary"].setdefault("is_green_belt", False)
    constraints["summary"].setdefault("agricultural_land_grade", 4)

    return constraints


async def _query_arcgis(
    session, url: str, lat: float, lon: float, radius_m: int
) -> dict:
    """Query an ArcGIS FeatureServer for features within radius of a point."""
    params = {
        "where": "1=1",
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": radius_m,
        "units": "esriSRUnit_Meter",
        "inSR": "4326",
        "outSR": "4326",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "json",
        "resultRecordCount": 20,
    }
    async with session.get(url + "/query", params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
        if resp.status != 200:
            return {"features": [], "error": f"HTTP {resp.status}"}
        data = await resp.json()
        return {"features": data.get("features", [])}


async def _query_flood_zones(session, lat: float, lon: float) -> dict:
    """Check EA flood zone data for a point."""
    result = {"in_zone_2": False, "in_zone_3": False, "features": []}
    try:
        # Use Planning Data Platform for flood zone check
        url = f"{PDP_BASE}/entity.json"
        params = {
            "longitude": lon,
            "latitude": lat,
            "dataset": "flood-zone-2",
            "limit": 5,
        }
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                entities = data.get("entities", [])
                if entities:
                    result["in_zone_2"] = True
                    result["features"].extend(entities)

        params["dataset"] = "flood-zone-3"
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                entities = data.get("entities", [])
                if entities:
                    result["in_zone_3"] = True
                    result["features"].extend(entities)
    except Exception as exc:
        log.warning("Flood zone query failed: %s", exc)
        result["error"] = str(exc)
    return result


async def _query_planning_data(
    session, dataset: str, lat: float, lon: float, radius_m: int
) -> dict:
    """Query MHCLG Planning Data Platform for a dataset at a point."""
    try:
        url = f"{PDP_BASE}/entity.json"
        params = {
            "longitude": lon,
            "latitude": lat,
            "dataset": dataset,
            "limit": 10,
        }
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return {"features": data.get("entities", [])}
            return {"features": [], "error": f"HTTP {resp.status}"}
    except Exception as exc:
        return {"features": [], "error": str(exc)}


def _min_feature_distance(lat: float, lon: float, features: list) -> float:
    """Find minimum distance to any feature centroid."""
    min_d = float("inf")
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        # ArcGIS point geometry
        if "x" in geom and "y" in geom:
            d = _haversine_m(lat, lon, geom["y"], geom["x"])
        # ArcGIS ring geometry — use centroid approximation
        elif "rings" in geom and geom["rings"]:
            ring = geom["rings"][0]
            cx = sum(p[0] for p in ring) / len(ring)
            cy = sum(p[1] for p in ring) / len(ring)
            d = _haversine_m(lat, lon, cy, cx)
        else:
            continue
        min_d = min(min_d, d)
    return min_d if min_d < float("inf") else 0.0


def _parse_alc_grade(grades: list[str]) -> int:
    """Parse ALC grade strings to numeric grade (1-5). Returns worst (highest) grade."""
    grade_map = {
        "Grade 1": 1, "Grade 2": 2, "Grade 3a": 3, "Grade 3b": 3,
        "Grade 3": 3, "Grade 4": 4, "Grade 5": 5,
        "Non Agricultural": 5, "Urban": 5, "Exclusion": 5,
    }
    parsed = [grade_map.get(g.strip(), 4) for g in grades if g]
    return min(parsed) if parsed else 4  # Return best (lowest) grade found


# ═══════════════════════════════════════════════════════════════
#  FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════

def engineer_features(
    project: dict,
    constraints: dict,
    grid_context: dict | None = None,
) -> dict:
    """Build 40+ features for the ML model from project + constraint data.

    Args:
        project: Dict with keys like capacity_mw, technology, land_area_ha,
                 lat, lon, is_brownfield, has_community_benefit, etc.
        constraints: Output from fetch_planning_constraints() or manual dict.
        grid_context: Optional dict with grid_headroom_mw, distance_to_substation_km.

    Returns:
        dict of feature_name -> float, ready for model input.
    """
    tech = project.get("technology", "Solar Photovoltaics")
    capacity = project.get("capacity_mw", 10)
    land_area = project.get("land_area_ha") or (capacity * 2.0)
    summary = constraints.get("summary", {}) if constraints else {}
    grid = grid_context or {}

    # Technology one-hot
    tech_lower = tech.lower()
    tech_solar = 1 if "solar" in tech_lower else 0
    tech_onshore = 1 if "onshore" in tech_lower and "wind" in tech_lower else 0
    tech_offshore = 1 if "offshore" in tech_lower else 0
    tech_battery = 1 if "battery" in tech_lower or "bess" in tech_lower else 0
    tech_biomass = 1 if "biomass" in tech_lower or "anaerobic" in tech_lower else 0
    tech_hydro = 1 if "hydro" in tech_lower else 0
    tech_other = 1 if sum([tech_solar, tech_onshore, tech_offshore, tech_battery, tech_biomass, tech_hydro]) == 0 else 0

    # Constraint distances
    d_aonb = summary.get("distance_to_aonb_m", 20000)
    d_sssi = summary.get("distance_to_sssi_m", 10000)

    # LPA context (defaults from national averages)
    base_approval = UK_APPROVAL_RATES.get(tech, 0.75)
    lpa_rate = project.get("local_authority_approval_rate", base_approval)
    region_rate = project.get("region_approval_rate", base_approval)

    now = datetime.utcnow()

    features = {
        "capacity_mw": capacity,
        "land_area_ha": land_area,
        "capacity_per_hectare": capacity / max(land_area, 0.01),
        "is_ground_mount": 1 if tech_solar and project.get("mounting_type", "ground").lower() == "ground" else 0,
        "num_turbines": project.get("num_turbines", 0),
        "turbine_height_m": project.get("turbine_height_m", 0),
        "tech_solar": tech_solar,
        "tech_onshore_wind": tech_onshore,
        "tech_offshore_wind": tech_offshore,
        "tech_battery": tech_battery,
        "tech_biomass": tech_biomass,
        "tech_hydro": tech_hydro,
        "tech_other": tech_other,
        "distance_to_sssi_m": d_sssi,
        "distance_to_sac_m": summary.get("distance_to_sac_m", 15000),
        "distance_to_spa_m": summary.get("distance_to_spa_m", 20000),
        "distance_to_aonb_m": d_aonb,
        "distance_to_national_park_m": summary.get("distance_to_national_park_m", 30000),
        "distance_to_ancient_woodland_m": summary.get("distance_to_ancient_woodland_m", 8000),
        "in_sssi_irz": 1 if d_sssi < 2000 else 0,
        "distance_to_priority_habitat_m": summary.get("distance_to_priority_habitat_m", 5000),
        "distance_to_listed_building_m": summary.get("distance_to_listed_buildings_m", 5000),
        "distance_to_scheduled_monument_m": summary.get("distance_to_scheduled_monuments_m", 10000),
        "distance_to_conservation_area_m": summary.get("distance_to_conservation_areas_m", 8000),
        "listed_building_grade_1_within_1km": 1 if summary.get("distance_to_listed_buildings_m", 5000) < 1000 else 0,
        "in_flood_zone_2": int(summary.get("in_flood_zone_2", False)),
        "in_flood_zone_3": int(summary.get("in_flood_zone_3", False)),
        "agricultural_land_grade": summary.get("agricultural_land_grade", 4),
        "is_bmv_land": 1 if summary.get("agricultural_land_grade", 4) <= 2 else 0,
        "is_greenfield": int(not project.get("is_brownfield", False)),
        "is_brownfield": int(project.get("is_brownfield", False)),
        "is_green_belt": int(summary.get("is_green_belt", False)),
        "distance_to_nearest_dwelling_m": project.get("distance_to_nearest_dwelling_m", 500),
        "population_density_per_km2": project.get("population_density_per_km2", 300),
        "distance_to_substation_km": grid.get("distance_to_substation_km", 5.0),
        "grid_headroom_mw": grid.get("grid_headroom_mw", 20.0),
        "local_authority_approval_rate": lpa_rate,
        "region_approval_rate": region_rate,
        "nearby_approved_count_10km": project.get("nearby_approved_count", 5),
        "nearby_refused_count_10km": project.get("nearby_refused_count", 2),
        "lpa_avg_determination_months": project.get("lpa_avg_determination_months", 8),
        "lpa_workload_in_progress": project.get("lpa_workload_in_progress", 15),
        "has_community_benefit": int(project.get("has_community_benefit", False)),
        "month_submitted": project.get("month_submitted", now.month),
        "year_submitted": project.get("year_submitted", now.year),
        "capacity_x_aonb_distance": capacity * d_aonb / 1000,
        "tech_region_approval_rate": lpa_rate * base_approval,
    }

    return features


# ═══════════════════════════════════════════════════════════════
#  ML MODEL — XGBoost Planning Predictor
# ═══════════════════════════════════════════════════════════════

class PlanningPredictor:
    """XGBoost ensemble for planning outcome prediction with SHAP-style explainability.

    Trained on REPD data (6000+ renewable energy planning decisions).
    Predicts: P(approved), P(refused), P(withdrawn) — 3-class classification.
    Explains: top factors driving prediction via feature importances + marginal contributions.

    Auto-trains on first use with synthetic data; retrains when REPD data is provided.
    """

    def __init__(self):
        self.model = None
        self.feature_names: list[str] = FEATURE_NAMES.copy()
        self.label_encoder: dict[int, str] = {0: "Approved", 1: "Refused", 2: "Withdrawn"}
        self.label_decoder: dict[str, int] = {"Approved": 0, "Refused": 1, "Withdrawn": 2}
        self.scaler_means: dict[str, float] = {}
        self.scaler_stds: dict[str, float] = {}
        self._trained = False
        self._training_metrics: dict = {}
        self._feature_importances: dict[str, float] = {}
        self._training_timestamp: str | None = None
        self._data_source: str = "none"

    def train(self, df: pd.DataFrame) -> dict:
        """Train on DataFrame with features + 'planning_outcome' column.

        Uses stratified k-fold cross-validation for robust evaluation.
        Model: XGBoost with class weights for imbalanced data.
        Stores feature importances for explainability.

        Args:
            df: DataFrame with FEATURE_NAMES columns + 'planning_outcome'.

        Returns:
            dict with accuracy, f1, confusion_matrix, feature_importances.
        """
        try:
            import xgboost as xgb
            from sklearn.model_selection import StratifiedKFold
            from sklearn.metrics import accuracy_score, f1_score, classification_report
        except ImportError as exc:
            log.error("ML dependencies missing: %s", exc)
            return {"error": f"Missing dependency: {exc}"}

        log.info("Training PlanningPredictor on %d samples", len(df))

        # Prepare features
        available_features = [f for f in self.feature_names if f in df.columns]
        if len(available_features) < 10:
            log.error("Insufficient features: %d available", len(available_features))
            return {"error": f"Only {len(available_features)} features available, need at least 10"}

        self.feature_names = available_features
        X = df[available_features].values.astype(np.float32)
        y = df["planning_outcome"].map(self.label_decoder).values

        # Handle NaN
        X = np.nan_to_num(X, nan=0.0)

        # Compute scaler stats (for feature explanation context)
        for i, fname in enumerate(available_features):
            self.scaler_means[fname] = float(np.nanmean(X[:, i]))
            self.scaler_stds[fname] = float(np.nanstd(X[:, i]) + 1e-8)

        # Class weights for imbalanced data
        unique, counts = np.unique(y, return_counts=True)
        total = len(y)
        class_weights = {int(c): total / (len(unique) * cnt) for c, cnt in zip(unique, counts)}

        sample_weights = np.array([class_weights[int(yi)] for yi in y], dtype=np.float32)

        # Stratified K-Fold cross-validation
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        fold_scores = []

        for train_idx, val_idx in skf.split(X, y):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]
            w_train = sample_weights[train_idx]

            dtrain = xgb.DMatrix(X_train, label=y_train, weight=w_train, feature_names=available_features)
            dval = xgb.DMatrix(X_val, label=y_val, feature_names=available_features)

            params = {
                "objective": "multi:softprob",
                "num_class": 3,
                "max_depth": 6,
                "learning_rate": 0.1,
                "subsample": 0.8,
                "colsample_bytree": 0.8,
                "min_child_weight": 3,
                "reg_alpha": 0.1,
                "reg_lambda": 1.0,
                "eval_metric": "mlogloss",
                "seed": 42,
                "verbosity": 0,
            }

            model = xgb.train(
                params, dtrain,
                num_boost_round=200,
                evals=[(dval, "val")],
                early_stopping_rounds=20,
                verbose_eval=False,
            )

            preds = model.predict(dval).argmax(axis=1)
            acc = accuracy_score(y_val, preds)
            f1 = f1_score(y_val, preds, average="weighted")
            fold_scores.append({"accuracy": acc, "f1": f1})

        # Final model on all data
        dtrain_full = xgb.DMatrix(X, label=y, weight=sample_weights, feature_names=available_features)
        self.model = xgb.train(
            params, dtrain_full,
            num_boost_round=200,
            verbose_eval=False,
        )

        # Feature importances
        importance = self.model.get_score(importance_type="gain")
        total_gain = sum(importance.values()) if importance else 1.0
        self._feature_importances = {
            k: v / total_gain for k, v in sorted(importance.items(), key=lambda x: -x[1])
        }

        # Metrics
        avg_acc = np.mean([s["accuracy"] for s in fold_scores])
        avg_f1 = np.mean([s["f1"] for s in fold_scores])

        # Full-data classification report
        full_preds = self.model.predict(dtrain_full).argmax(axis=1)
        report = classification_report(y, full_preds, target_names=["Approved", "Refused", "Withdrawn"], output_dict=True)

        self._trained = True
        self._training_timestamp = datetime.utcnow().isoformat()
        self._training_metrics = {
            "cv_accuracy": round(avg_acc, 4),
            "cv_f1_weighted": round(avg_f1, 4),
            "cv_folds": 5,
            "n_samples": len(df),
            "n_features": len(available_features),
            "class_distribution": {
                self.label_encoder.get(int(c), str(c)): int(cnt)
                for c, cnt in zip(unique, counts)
            },
            "classification_report": report,
            "top_features": dict(list(self._feature_importances.items())[:15]),
        }

        log.info(
            "PlanningPredictor trained: accuracy=%.3f, F1=%.3f, features=%d, samples=%d",
            avg_acc, avg_f1, len(available_features), len(df),
        )

        return self._training_metrics

    def predict(self, features: dict) -> dict:
        """Predict planning outcome for a new project.

        Args:
            features: dict of feature_name -> float (from engineer_features).

        Returns:
            dict with verdict, probabilities, top_factors, risk_flags,
            recommendations, and comparable_decisions placeholder.
        """
        if not self._trained or self.model is None:
            return {"error": "Model not trained. Call train() or POST /api/planning/train first."}

        try:
            import xgboost as xgb
        except ImportError:
            return {"error": "xgboost not installed"}

        # Build feature vector
        x = np.array(
            [features.get(f, 0.0) for f in self.feature_names],
            dtype=np.float32,
        ).reshape(1, -1)
        x = np.nan_to_num(x, nan=0.0)

        dmat = xgb.DMatrix(x, feature_names=self.feature_names)
        probs = self.model.predict(dmat)[0]

        p_approved = float(probs[0])
        p_refused = float(probs[1])
        p_withdrawn = float(probs[2])

        # Verdict
        if p_approved >= 0.65:
            verdict = "LIKELY_APPROVED"
        elif p_refused >= 0.50:
            verdict = "LIKELY_REFUSED"
        elif p_approved >= 0.45:
            verdict = "UNCERTAIN"
        else:
            verdict = "UNCERTAIN"

        # Explain top factors using feature importances + feature values
        top_factors = self._explain_prediction(features)

        # Risk flags
        risk_flags = self._identify_risk_flags(features)

        # Recommendations
        recommendations = self._generate_recommendations(features, risk_flags, p_approved)

        return {
            "verdict": verdict,
            "probability_approved": round(p_approved, 4),
            "probability_refused": round(p_refused, 4),
            "probability_withdrawn": round(p_withdrawn, 4),
            "confidence": round(max(p_approved, p_refused, p_withdrawn), 4),
            "top_factors": top_factors,
            "risk_flags": risk_flags,
            "recommendations": recommendations,
            "comparable_decisions": [],  # Populated by find_comparable_decisions()
            "model_info": {
                "trained_at": self._training_timestamp,
                "data_source": self._data_source,
                "cv_accuracy": self._training_metrics.get("cv_accuracy"),
            },
        }

    def _explain_prediction(self, features: dict) -> list[dict]:
        """Generate top-5 factor explanations using feature importances and values.

        Combines model feature importance with feature-value context to produce
        human-readable explanations of what is driving the prediction.
        """
        explanations = []

        # Feature importance * deviation from training mean = approximate SHAP-like impact
        for fname, importance in list(self._feature_importances.items())[:20]:
            if fname not in features:
                continue
            val = features[fname]
            mean = self.scaler_means.get(fname, 0)
            std = self.scaler_stds.get(fname, 1)

            # Normalised deviation
            deviation = (val - mean) / std if std > 0 else 0
            impact = importance * abs(deviation)

            # Direction: positive = helps approval, negative = hinders
            direction, explanation = self._feature_explanation(fname, val, deviation)

            explanations.append({
                "feature": fname,
                "value": round(val, 2) if isinstance(val, float) else val,
                "impact": round(impact, 4),
                "direction": direction,
                "explanation": explanation,
            })

        # Sort by impact, return top 5
        explanations.sort(key=lambda e: e["impact"], reverse=True)
        return explanations[:5]

    def _feature_explanation(self, fname: str, val: float, deviation: float) -> tuple[str, str]:
        """Generate human-readable explanation for a feature value."""
        # Distance features — further is generally better
        if fname.startswith("distance_to_") and fname.endswith("_m"):
            label = fname.replace("distance_to_", "").replace("_m", "").replace("_", " ")
            dist_km = val / 1000
            if val > 5000:
                return "positive", f"Site is {dist_km:.1f}km from nearest {label} — well beyond typical concern threshold"
            elif val > 2000:
                return "neutral", f"Site is {dist_km:.1f}km from nearest {label} — moderate buffer"
            else:
                return "negative", f"Site is only {dist_km:.0f}m from nearest {label} — likely to require assessment"

        if fname == "capacity_mw":
            if val < 10:
                return "positive", f"{val:.1f}MW — small scale, less scrutiny"
            elif val < 50:
                return "neutral", f"{val:.1f}MW — medium scale"
            else:
                return "negative", f"{val:.1f}MW — large project attracts more opposition"

        if fname == "agricultural_land_grade":
            if val <= 2:
                return "negative", f"Grade {int(val)} — Best & Most Versatile land (strong refusal factor)"
            elif val == 3:
                return "neutral", f"Grade 3 — may need to demonstrate not Grade 3a"
            else:
                return "positive", f"Grade {int(val)} — lower-quality land, less concern"

        if fname == "is_green_belt":
            if val:
                return "negative", "Site is in Green Belt — needs 'very special circumstances' (NPPF para 168)"
            return "positive", "Site is not in Green Belt"

        if fname == "is_bmv_land":
            if val:
                return "negative", "Best & Most Versatile agricultural land — strong policy objection"
            return "positive", "Not BMV agricultural land"

        if fname == "local_authority_approval_rate":
            pct = val * 100
            if val >= 0.75:
                return "positive", f"This LPA approves {pct:.0f}% of similar applications"
            elif val >= 0.55:
                return "neutral", f"This LPA approves {pct:.0f}% of similar applications — mixed record"
            else:
                return "negative", f"This LPA only approves {pct:.0f}% of similar applications"

        if fname == "in_flood_zone_3":
            if val:
                return "negative", "In Flood Zone 3 — sequential test required; strong refusal risk"
            return "positive", "Not in Flood Zone 3"

        if fname == "in_flood_zone_2":
            if val:
                return "negative", "In Flood Zone 2 — sequential test required"
            return "positive", "Not in Flood Zone 2"

        if fname == "is_brownfield":
            if val:
                return "positive", "Brownfield/previously developed land — strong policy support"
            return "neutral", "Greenfield site"

        if fname == "has_community_benefit":
            if val:
                return "positive", "Community benefit scheme included — reduces local opposition"
            return "neutral", "No community benefit scheme proposed"

        if fname == "nearby_approved_count_10km":
            if val >= 5:
                return "positive", f"{int(val)} similar projects approved within 10km — precedent established"
            return "neutral", f"{int(val)} similar projects approved within 10km"

        if fname == "nearby_refused_count_10km":
            if val >= 3:
                return "negative", f"{int(val)} similar projects refused within 10km — cumulative impact concern"
            return "neutral", f"{int(val)} similar projects refused within 10km"

        if fname.startswith("distance_to_") and fname.endswith("_km"):
            label = fname.replace("distance_to_", "").replace("_km", "").replace("_", " ")
            return ("positive" if val > 5 else "neutral"), f"{val:.1f}km to nearest {label}"

        # Default
        direction = "positive" if deviation > 0.5 else ("negative" if deviation < -0.5 else "neutral")
        return direction, f"{fname} = {val:.2f}"

    def _identify_risk_flags(self, features: dict) -> list[str]:
        """Identify specific planning risk flags from feature values."""
        flags = []

        if features.get("is_green_belt"):
            flags.append("Site is within Green Belt — 'very special circumstances' required")
        if features.get("is_bmv_land") or features.get("agricultural_land_grade", 5) <= 2:
            grade = features.get("agricultural_land_grade", 2)
            flags.append(f"Grade {int(grade)} Best & Most Versatile agricultural land")
        if features.get("distance_to_aonb_m", 99999) < 2000:
            d = features.get("distance_to_aonb_m", 0)
            flags.append(f"Within {d:.0f}m of AONB/National Landscape")
        if features.get("distance_to_listed_building_m", 99999) < 500:
            flags.append("Within 500m of listed building — heritage impact assessment likely")
        if features.get("distance_to_sssi_m", 99999) < 1000:
            flags.append("Within 1km of SSSI — Natural England consultation required")
        if features.get("in_flood_zone_3"):
            flags.append("In Flood Zone 3 — sequential test and FRA required")
        elif features.get("in_flood_zone_2"):
            flags.append("In Flood Zone 2 — sequential test required")
        if features.get("distance_to_conservation_area_m", 99999) < 500:
            flags.append("Within 500m of Conservation Area — heritage setting assessment needed")
        if features.get("distance_to_scheduled_monument_m", 99999) < 500:
            flags.append("Within 500m of Scheduled Monument — Scheduled Monument Consent may apply")
        if features.get("distance_to_ancient_woodland_m", 99999) < 200:
            flags.append("Within 200m of Ancient Woodland — buffer zone policy applies")
        if features.get("distance_to_nearest_dwelling_m", 99999) < 200:
            flags.append("Within 200m of residential property — amenity impact assessment required")
        if features.get("capacity_mw", 0) > 50:
            flags.append("Large-scale project (>50MW) — enhanced scrutiny expected")
        if features.get("nearby_refused_count_10km", 0) >= 3:
            flags.append("Cumulative impact concern: 3+ refusals within 10km")

        return flags

    def _generate_recommendations(
        self, features: dict, risk_flags: list[str], p_approved: float
    ) -> list[str]:
        """Generate actionable recommendations based on prediction and risk profile."""
        recs = []

        if not features.get("has_community_benefit") and p_approved < 0.75:
            recs.append("Consider offering a community benefit scheme to reduce local opposition")

        if features.get("is_bmv_land") or features.get("agricultural_land_grade", 5) <= 2:
            recs.append("Commission Agricultural Land Classification survey to confirm grade (may be 3b not 3a)")

        if features.get("distance_to_aonb_m", 99999) < 5000:
            recs.append("Commission Landscape and Visual Impact Assessment (LVIA) early")

        if features.get("distance_to_listed_building_m", 99999) < 1000:
            recs.append("Engage Historic England in pre-application consultation")

        if features.get("distance_to_sssi_m", 99999) < 2000:
            recs.append("Request SSSI Impact Risk Zone assessment from Natural England")

        if features.get("in_flood_zone_2") or features.get("in_flood_zone_3"):
            recs.append("Commission Flood Risk Assessment and pass sequential test before submission")

        if features.get("is_green_belt"):
            recs.append("Build 'very special circumstances' case per NPPF para 168 (renewable energy benefits)")

        if p_approved < 0.55:
            recs.append("Consider pre-application consultation with LPA to identify and address concerns early")
            recs.append("Review comparable approved projects in the area for mitigation strategies")

        if features.get("capacity_mw", 0) > 50:
            recs.append("EIA screening likely required — submit screening request early to avoid delays")

        if not recs:
            recs.append("Strong application — ensure all standard documents are submitted with the application")

        return recs

    def explain(self, features: dict) -> dict:
        """SHAP-style explanation suitable for frontend waterfall visualisation.

        Returns ordered list of feature contributions, base value,
        and final prediction suitable for a SHAP waterfall chart.
        """
        if not self._trained:
            return {"error": "Model not trained"}

        prediction = self.predict(features)
        if "error" in prediction:
            return prediction

        # Build waterfall data
        factors = prediction["top_factors"]
        waterfall = []
        running = 0.5  # Base probability
        for f in factors:
            contribution = f["impact"] * (1 if f["direction"] == "positive" else -1)
            waterfall.append({
                "feature": f["feature"],
                "contribution": round(contribution, 4),
                "cumulative": round(running + contribution, 4),
                "explanation": f["explanation"],
            })
            running += contribution

        return {
            "base_value": 0.5,
            "final_prediction": prediction["probability_approved"],
            "verdict": prediction["verdict"],
            "waterfall": waterfall,
            "risk_flags": prediction["risk_flags"],
        }

    def save(self, path: str | None = None):
        """Save trained model + metadata to disk."""
        if not self._trained:
            log.warning("Cannot save untrained model")
            return

        save_dir = Path(path) if path else MODEL_DIR
        save_dir.mkdir(parents=True, exist_ok=True)

        # Save XGBoost model
        self.model.save_model(str(save_dir / "planning_xgb.json"))

        # Save metadata
        meta = {
            "feature_names": self.feature_names,
            "label_encoder": self.label_encoder,
            "label_decoder": self.label_decoder,
            "scaler_means": self.scaler_means,
            "scaler_stds": self.scaler_stds,
            "feature_importances": self._feature_importances,
            "training_metrics": self._training_metrics,
            "training_timestamp": self._training_timestamp,
            "data_source": self._data_source,
        }
        with open(save_dir / "planning_meta.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)

        log.info("Model saved to %s", save_dir)

    def load(self, path: str | None = None) -> bool:
        """Load trained model + metadata from disk.

        Returns True if loaded successfully, False otherwise.
        """
        try:
            import xgboost as xgb
        except ImportError:
            log.error("xgboost not installed — cannot load model")
            return False

        load_dir = Path(path) if path else MODEL_DIR
        model_path = load_dir / "planning_xgb.json"
        meta_path = load_dir / "planning_meta.json"

        if not model_path.exists() or not meta_path.exists():
            log.info("No saved model found at %s", load_dir)
            return False

        try:
            self.model = xgb.Booster()
            self.model.load_model(str(model_path))

            with open(meta_path) as f:
                meta = json.load(f)

            self.feature_names = meta["feature_names"]
            self.label_encoder = {int(k): v for k, v in meta["label_encoder"].items()}
            self.label_decoder = {v: int(k) for k, v in self.label_encoder.items()}
            self.scaler_means = meta["scaler_means"]
            self.scaler_stds = meta["scaler_stds"]
            self._feature_importances = meta["feature_importances"]
            self._training_metrics = meta["training_metrics"]
            self._training_timestamp = meta["training_timestamp"]
            self._data_source = meta.get("data_source", "unknown")
            self._trained = True

            log.info("Model loaded from %s (trained %s)", load_dir, self._training_timestamp)
            return True

        except Exception as exc:
            log.error("Failed to load model: %s", exc)
            return False

    def model_status(self) -> dict:
        """Return current model status and accuracy metrics."""
        return {
            "trained": self._trained,
            "training_timestamp": self._training_timestamp,
            "data_source": self._data_source,
            "metrics": self._training_metrics,
            "n_features": len(self.feature_names),
            "top_features": dict(list(self._feature_importances.items())[:10]),
        }


# ═══════════════════════════════════════════════════════════════
#  SINGLETON PREDICTOR (auto-trains on first use)
# ═══════════════════════════════════════════════════════════════

_predictor: PlanningPredictor | None = None
_predictor_lock = asyncio.Lock() if hasattr(asyncio, "Lock") else None


async def get_predictor() -> PlanningPredictor:
    """Get or create the singleton PlanningPredictor.

    On first call:
      1. Tries to load a saved model from disk.
      2. If none found, trains on synthetic data.
      3. Saves the trained model for future fast loads.
    """
    global _predictor

    if _predictor is not None and _predictor._trained:
        return _predictor

    lock = _predictor_lock or asyncio.Lock()
    async with lock:
        if _predictor is not None and _predictor._trained:
            return _predictor

        _predictor = PlanningPredictor()

        # Try loading from disk first
        if _predictor.load():
            return _predictor

        # Train on synthetic data
        log.info("No saved model — training on synthetic data")
        df = _synthetic_training_data()
        _predictor._data_source = "synthetic"
        _predictor.train(df)
        _predictor.save()

        return _predictor


# ═══════════════════════════════════════════════════════════════
#  REGULATORY COMPLIANCE CHECKER
# ═══════════════════════════════════════════════════════════════

def check_regulatory_compliance(project: dict, constraints: dict) -> dict:
    """Comprehensive regulatory compliance check for UK energy projects.

    Checks against:
      - NPPF Dec 2024 (paras 163-168 for renewable energy)
      - EN-1/EN-3 2025 National Policy Statements
      - EIA Regulations 2017 Schedule 2 thresholds
      - BNG (Biodiversity Net Gain) requirements
      - CDM 2015 requirements
      - G99/G100 grid connection regulations
      - ETSU-R-97 noise limits
      - Glint & glare assessment triggers
      - Agricultural Land Classification policy
      - Flood risk Sequential Test
      - Heritage impact assessment triggers
      - Landscape & Visual Impact Assessment triggers

    Args:
        project: dict with capacity_mw, technology, land_area_ha, lat, lon, etc.
        constraints: dict from fetch_planning_constraints() or manual.

    Returns:
        dict with overall_status, checks list, required_assessments,
        estimated_timeline_months, estimated_cost_gbp.
    """
    tech = project.get("technology", "Solar Photovoltaics")
    capacity = project.get("capacity_mw", 10)
    land_area = project.get("land_area_ha") or (capacity * 2.0)
    summary = constraints.get("summary", {}) if constraints else {}

    checks = []
    required_assessments = []
    total_cost = 0
    timeline_months = 4  # Minimum determination period

    # --- 1. NSIP Threshold ---
    if capacity > 100 and tech in ("Solar Photovoltaics", "Onshore Wind"):
        checks.append({
            "regulation": "Planning Act 2008 / Planning & Infrastructure Act 2025",
            "status": "NSIP_REQUIRED",
            "detail": f"{capacity:.0f}MW {tech} exceeds 100MW NSIP threshold — DCO required",
            "action": "Apply for Development Consent Order via Planning Inspectorate",
            "reference": "Planning & Infrastructure Act 2025 s.15",
        })
        required_assessments.append("Development Consent Order Application")
        total_cost += 500_000
        timeline_months = max(timeline_months, 30)
    else:
        checks.append({
            "regulation": "Planning Act 2008",
            "status": "COMPLIANT",
            "detail": f"{capacity:.0f}MW below 100MW NSIP threshold — TCPA route",
            "action": "Apply to Local Planning Authority under TCPA 1990",
            "reference": "Planning & Infrastructure Act 2025",
        })

    # --- 2. EIA Screening ---
    eia_threshold = EIA_THRESHOLDS.get(tech, {})
    needs_eia = False

    if "area_ha" in eia_threshold and land_area > eia_threshold["area_ha"]:
        needs_eia = True
        checks.append({
            "regulation": "EIA Regulations 2017 Schedule 2",
            "status": "SCREENING_REQUIRED",
            "detail": f"Site area {land_area:.1f}ha exceeds {eia_threshold['area_ha']}ha threshold",
            "action": "Submit EIA screening request to LPA (6 weeks for determination)",
            "reference": "SI 2017/571 Schedule 2, 3(a)",
        })
        required_assessments.append("EIA Screening Opinion")
        total_cost += 3_000
        timeline_months = max(timeline_months, 6)
    elif "turbines" in eia_threshold:
        n_turb = project.get("num_turbines", 0)
        hub_h = project.get("turbine_height_m", 0)
        if n_turb > eia_threshold.get("turbines", 999) or hub_h > eia_threshold.get("hub_height_m", 999):
            needs_eia = True
            checks.append({
                "regulation": "EIA Regulations 2017 Schedule 2",
                "status": "SCREENING_REQUIRED",
                "detail": f"{n_turb} turbines at {hub_h:.0f}m exceeds Schedule 2 threshold",
                "action": "Submit EIA screening request to LPA",
                "reference": "SI 2017/571 Schedule 2, 3(i)",
            })
            required_assessments.append("EIA Screening Opinion")
            total_cost += 3_000
    else:
        checks.append({
            "regulation": "EIA Regulations 2017",
            "status": "COMPLIANT",
            "detail": "Below Schedule 2 screening thresholds",
            "action": "No EIA screening required (but LPA may request)",
            "reference": "SI 2017/571 Schedule 2",
        })

    # If EIA screening likely leads to full EIA
    if needs_eia and (land_area > 5 or capacity > 20):
        required_assessments.append("Environmental Statement")
        total_cost += 40_000
        timeline_months = max(timeline_months, 10)

    # --- 3. Biodiversity Net Gain ---
    checks.append({
        "regulation": "Biodiversity Net Gain (Environment Act 2021)",
        "status": "ACTION_REQUIRED",
        "detail": "10% BNG mandatory for all developments since February 2024",
        "action": f"Commission BNG assessment using {_cite_reg('statutory_biodiversity_metric')}; secure 30-year management plan",
        "reference": "Environment Act 2021 Schedule 7A; Town and Country Planning Act 1990 (as amended)",
    })
    required_assessments.append(f"BNG Assessment ({_cite_reg('statutory_biodiversity_metric')})")
    total_cost += 8_000

    # --- 4. CDM 2015 ---
    checks.append({
        "regulation": "CDM Regulations 2015",
        "status": "ACTION_REQUIRED",
        "detail": "Construction project requires Principal Designer and Principal Contractor appointment",
        "action": "Appoint Principal Designer before planning submission; notify HSE if >30 days or >500 person-days",
        "reference": "SI 2015/51 Regulations 4-7",
    })

    # --- 5. Grid Connection (G99/G100) ---
    if capacity > 0.01:  # >10kW
        checks.append({
            "regulation": "G99 Engineering Recommendation",
            "status": "ACTION_REQUIRED",
            "detail": f"{capacity:.1f}MW requires G99 application to DNO",
            "action": "Submit G99 application; allow 3 months for connection offer",
            "reference": "ENA EREC G99 Issue 2 Amendment 7",
        })
        required_assessments.append("G99 Grid Connection Application")
        total_cost += 5_000
        timeline_months = max(timeline_months, timeline_months + 3)

    # --- 6. Generation Licence ---
    if capacity > 50:
        checks.append({
            "regulation": "Electricity Act 1989 s.36",
            "status": "ACTION_REQUIRED",
            "detail": f"{capacity:.0f}MW exceeds generation licence exemption threshold",
            "action": "Apply to Ofgem for generation licence",
            "reference": "Electricity (Class Exemptions from the Requirement for a Licence) Order 2001",
        })
    elif capacity > 10:
        checks.append({
            "regulation": "Electricity Act 1989 s.36",
            "status": "COMPLIANT",
            "detail": f"{capacity:.0f}MW — likely exempt under Class A (10-50MW)",
            "action": "Verify exemption applies; no licence required",
            "reference": "Electricity (Class Exemptions) Order 2001, Class A",
        })
    else:
        checks.append({
            "regulation": "Electricity Act 1989 s.36",
            "status": "COMPLIANT",
            "detail": f"{capacity:.1f}MW — exempt from generation licence",
            "action": "No action required",
            "reference": "Electricity (Class Exemptions) Order 2001",
        })

    # --- 7. Flood Risk ---
    in_fz2 = summary.get("in_flood_zone_2", False)
    in_fz3 = summary.get("in_flood_zone_3", False)

    if in_fz3:
        checks.append({
            "regulation": "NPPF Flood Risk (Sequential Test)",
            "status": "HIGH_RISK",
            "detail": "Site is in Flood Zone 3 — highest flood risk",
            "action": "Commission site-specific Flood Risk Assessment; demonstrate sequential test compliance; "
                     "solar PV classified as 'essential infrastructure' may be permissible with Exception Test",
            "reference": "NPPF Annex 3; Planning Practice Guidance (Flood Risk and Coastal Change)",
        })
        required_assessments.append("Flood Risk Assessment")
        total_cost += 8_000
        timeline_months = max(timeline_months, 8)
    elif in_fz2:
        checks.append({
            "regulation": "NPPF Flood Risk (Sequential Test)",
            "status": "ACTION_REQUIRED",
            "detail": "Site is in Flood Zone 2 — medium flood risk",
            "action": "Commission Flood Risk Assessment; demonstrate sequential test compliance",
            "reference": "NPPF Annex 3",
        })
        required_assessments.append("Flood Risk Assessment")
        total_cost += 5_000
    else:
        checks.append({
            "regulation": "NPPF Flood Risk",
            "status": "COMPLIANT",
            "detail": "Site is in Flood Zone 1 — lowest flood risk",
            "action": "No FRA required unless site >1ha (then drainage strategy needed)",
            "reference": "NPPF para 173",
        })
        if land_area > 1:
            required_assessments.append("Drainage Strategy")
            total_cost += 3_000

    # --- 8. Heritage Assessment ---
    d_lb = summary.get("distance_to_listed_buildings_m", 99999)
    d_sm = summary.get("distance_to_scheduled_monuments_m", 99999)
    d_ca = summary.get("distance_to_conservation_areas_m", 99999)

    heritage_risk = False
    if d_lb < 1000 or d_sm < 1000 or d_ca < 500:
        heritage_risk = True
        affected = []
        if d_lb < 1000:
            affected.append(f"listed building ({d_lb:.0f}m)")
        if d_sm < 1000:
            affected.append(f"scheduled monument ({d_sm:.0f}m)")
        if d_ca < 500:
            affected.append(f"conservation area ({d_ca:.0f}m)")

        checks.append({
            "regulation": "NPPF Heritage Assets (Section 16)",
            "status": "ACTION_REQUIRED",
            "detail": f"Near heritage assets: {', '.join(affected)}",
            "action": "Commission Heritage Impact Assessment; consult Historic England if Grade I/II* or SM",
            "reference": "NPPF paras 200-208; Planning (Listed Buildings & Conservation Areas) Act 1990",
        })
        required_assessments.append("Heritage Impact Assessment")
        total_cost += 6_000
    else:
        checks.append({
            "regulation": "NPPF Heritage Assets",
            "status": "COMPLIANT",
            "detail": "No designated heritage assets within impact distance",
            "action": "Include heritage desk-based assessment in application",
            "reference": "NPPF Section 16",
        })

    # --- 9. Landscape & Visual Impact ---
    d_aonb = summary.get("distance_to_aonb_m", 99999)
    d_np = summary.get("distance_to_national_park_m", 99999)

    if d_aonb < 5000 or d_np < 5000:
        nearest = "AONB/National Landscape" if d_aonb < d_np else "National Park"
        dist = min(d_aonb, d_np)
        checks.append({
            "regulation": "NPPF Landscape (AONB/National Park)",
            "status": "HIGH_RISK" if dist < 1000 else "ACTION_REQUIRED",
            "detail": f"Within {dist:.0f}m of {nearest} — LVIA essential",
            "action": "Commission full LVIA; demonstrate development would not harm landscape character",
            "reference": "NPPF paras 182-183; Countryside and Rights of Way Act 2000",
        })
        required_assessments.append("Landscape and Visual Impact Assessment")
        total_cost += 15_000
        timeline_months = max(timeline_months, 8)
    elif capacity > 5:
        # Large solar/wind generally needs LVIA even outside designated areas
        checks.append({
            "regulation": "NPPF Landscape",
            "status": "RECOMMENDED",
            "detail": f"{capacity:.0f}MW project — LVIA advisable even outside designated areas",
            "action": "Commission LVIA to support application",
            "reference": "NPPF para 135; Guidelines for Landscape and Visual Impact Assessment (GLVIA3)",
        })
        required_assessments.append("Landscape and Visual Impact Assessment")
        total_cost += 12_000

    # --- 10. Agricultural Land Classification ---
    alc_grade = summary.get("agricultural_land_grade", 4)
    if alc_grade <= 2:
        checks.append({
            "regulation": "NPPF Agricultural Land (BMV)",
            "status": "HIGH_RISK",
            "detail": f"Grade {alc_grade} — Best & Most Versatile agricultural land",
            "action": "Commission detailed ALC survey; demonstrate no alternative lower-grade sites; "
                     "consider dual-use (agrivoltaics) or temporary/reversible development argument",
            "reference": "NPPF para 180; Planning Practice Guidance (Natural Environment)",
        })
        required_assessments.append("Agricultural Land Classification Survey")
        total_cost += 5_000
    elif alc_grade == 3:
        checks.append({
            "regulation": "NPPF Agricultural Land",
            "status": "ACTION_REQUIRED",
            "detail": "Grade 3 land — may include Grade 3a (BMV). Survey recommended",
            "action": "Commission ALC survey to determine if 3a (BMV) or 3b (not BMV)",
            "reference": "NPPF para 180",
        })
        required_assessments.append("Agricultural Land Classification Survey")
        total_cost += 5_000
    else:
        checks.append({
            "regulation": "NPPF Agricultural Land",
            "status": "COMPLIANT",
            "detail": f"Grade {alc_grade} — not Best & Most Versatile land",
            "action": "No ALC concern",
            "reference": "NPPF para 180",
        })

    # --- 11. Ecological Assessment ---
    d_sssi = summary.get("distance_to_sssi_m", 99999)
    d_sac = summary.get("distance_to_sac_m", 99999)
    d_spa = summary.get("distance_to_spa_m", 99999)
    d_aw = summary.get("distance_to_ancient_woodland_m", 99999)

    if d_sac < 5000 or d_spa < 5000:
        checks.append({
            "regulation": "Conservation of Habitats and Species Regulations 2017",
            "status": "ACTION_REQUIRED",
            "detail": "Within 5km of European site (SAC/SPA) — Habitats Regulations Assessment required",
            "action": "Commission HRA screening; LPA must consult Natural England",
            "reference": f"SI 2017/1012; {_nppf_para('SSSI')}",
        })
        required_assessments.append("Habitats Regulations Assessment")
        total_cost += 10_000
        timeline_months = max(timeline_months, 10)

    if d_sssi < 2000:
        checks.append({
            "regulation": "Wildlife and Countryside Act 1981 (SSSI)",
            "status": "ACTION_REQUIRED",
            "detail": f"Within {d_sssi:.0f}m of SSSI — in Impact Risk Zone",
            "action": "Consult Natural England; likely need SSSI assessment",
            "reference": f"Wildlife and Countryside Act 1981 s.28; {_nppf_para('SSSI')}",
        })
        required_assessments.append("SSSI Impact Assessment")
        total_cost += 6_000

    if d_aw < 500:
        checks.append({
            "regulation": "NPPF Ancient Woodland",
            "status": "HIGH_RISK",
            "detail": f"Within {d_aw:.0f}m of Ancient Woodland — irreplaceable habitat",
            "action": "Maintain minimum 15m buffer; ecological assessment required",
            "reference": f"{_nppf_para('ANCIENT_WOODLAND')}; Natural England/Forestry Commission Standing Advice",
        })
        required_assessments.append("Ancient Woodland Buffer Assessment")
        total_cost += 4_000

    # Always need preliminary ecological appraisal for greenfield
    if not project.get("is_brownfield", False):
        required_assessments.append("Preliminary Ecological Appraisal")
        total_cost += 4_000

    # --- 12. Noise Assessment (Wind) ---
    if "wind" in tech.lower():
        checks.append({
            "regulation": "ETSU-R-97 Noise Assessment",
            "status": "ACTION_REQUIRED",
            "detail": "Wind development requires ETSU-R-97 noise assessment",
            "action": "Commission noise survey; demonstrate compliance with day (35-40dB) and night (43dB) limits",
            "reference": "ETSU-R-97 (1996, updated guidance 2025); Planning Practice Guidance (Noise)",
        })
        required_assessments.append("Noise Impact Assessment (ETSU-R-97)")
        total_cost += 8_000

    # --- 13. Glint & Glare (Solar) ---
    if "solar" in tech.lower():
        d_dwelling = project.get("distance_to_nearest_dwelling_m", 500)
        if d_dwelling < 1000 or land_area > 5:
            checks.append({
                "regulation": "Glint & Glare Assessment",
                "status": "ACTION_REQUIRED",
                "detail": "Solar development near receptors — glint/glare assessment likely required by LPA",
                "action": "Commission glint & glare study for residential/road/aviation receptors",
                "reference": "Planning Practice Guidance; Pager Power methodology",
            })
            required_assessments.append("Glint & Glare Assessment")
            total_cost += 5_000

    # --- 14. Green Belt ---
    if summary.get("is_green_belt", False):
        checks.append({
            "regulation": "NPPF Green Belt Policy",
            "status": "HIGH_RISK",
            "detail": "Site is within Green Belt — renewable energy is 'inappropriate development'",
            "action": (
                f"Build 'very special circumstances' case under {_nppf_para('GREEN_BELT_VSC')}; "
                "demonstrate renewable energy benefits outweigh Green Belt harm"
            ),
            "reference": _nppf_para("range_planning"),
        })
        timeline_months = max(timeline_months, 10)

    # --- Determine overall status ---
    statuses = [c["status"] for c in checks]
    if "HIGH_RISK" in statuses:
        overall = "HIGH_RISK"
    elif "NSIP_REQUIRED" in statuses:
        overall = "ACTION_REQUIRED"
    elif "ACTION_REQUIRED" in statuses or "SCREENING_REQUIRED" in statuses:
        overall = "ACTION_REQUIRED"
    else:
        overall = "COMPLIANT"

    # De-duplicate assessments
    required_assessments = list(dict.fromkeys(required_assessments))

    return {
        "overall_status": overall,
        "checks": checks,
        "required_assessments": required_assessments,
        "estimated_timeline_months": timeline_months,
        "estimated_cost_gbp": total_cost,
        "project_summary": {
            "technology": tech,
            "capacity_mw": capacity,
            "land_area_ha": land_area,
        },
    }


# ═══════════════════════════════════════════════════════════════
#  NLP PLANNING DECISION ANALYSIS (via Claude)
# ═══════════════════════════════════════════════════════════════

async def analyse_planning_decision(decision_text: str, client) -> dict:
    """Use Claude to extract structured data from planning decision notices.

    Extracts:
      - Decision outcome (granted/refused)
      - Planning conditions (pre-commencement, construction, operational)
      - Reasons for refusal (if refused)
      - Material considerations cited
      - Policy references (NPPF, local plan, NPS)
      - Community objection themes
      - Officer recommendation vs committee decision

    Args:
        decision_text: Full text of a planning decision notice.
        client: Anthropic AsyncAnthropic client.

    Returns:
        dict with structured extraction.
    """
    prompt = """Analyse this UK planning decision notice for a renewable energy project.
Extract the following as JSON:

{
    "outcome": "granted" or "refused" or "withdrawn",
    "decision_date": "YYYY-MM-DD or null",
    "officer_recommendation": "approve" or "refuse" or "unknown",
    "committee_overturned": true/false,
    "conditions": [
        {"number": 1, "type": "pre_commencement|construction|operational|decommissioning|time_limit", "summary": "..."}
    ],
    "refusal_reasons": [
        {"reason": "...", "policy_ref": "NPPF para X / Local Plan Policy Y"}
    ],
    "material_considerations": ["landscape impact", "heritage", ...],
    "policy_references": [
        {"policy": "NPPF", "paragraph": "168", "topic": "renewable energy"}
    ],
    "objection_themes": ["visual impact", "noise", "property values", ...],
    "objection_count": 0,
    "support_count": 0,
    "key_mitigation_measures": ["landscaping scheme", "CEMP", ...],
    "determination_time_weeks": 0
}

Decision notice text:
"""

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt + decision_text[:15000]}],
        )

        text = response.content[0].text
        # Extract JSON from response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            result = json.loads(text[start:end])
            result["_analysis_model"] = "claude-sonnet-4-20250514"
            return result
        else:
            return {"error": "Could not parse structured response", "raw": text}

    except Exception as exc:
        log.error("Planning decision analysis failed: %s", exc)
        return {"error": str(exc)}


# ═══════════════════════════════════════════════════════════════
#  LOCAL AUTHORITY INTELLIGENCE
# ═══════════════════════════════════════════════════════════════

def local_authority_profile(
    la_name: str,
    technology: str = "Solar Photovoltaics",
    repd_df: pd.DataFrame | None = None,
) -> dict:
    """Build intelligence profile for a local planning authority.

    From REPD data: approval rate, average determination time,
    common refusal reasons, capacity approved/refused by year,
    policy stance indicators.

    Args:
        la_name: Local authority name (must match REPD 'Planning Authority').
        technology: Technology filter (default Solar Photovoltaics).
        repd_df: Optional pre-loaded REPD DataFrame. Uses synthetic if None.

    Returns:
        dict with approval metrics, timeline estimates, and comparable projects.
    """
    if repd_df is None:
        repd_df = _synthetic_training_data(2000)

    # Filter to technology
    tech_lower = technology.lower()
    if "technology_type" in repd_df.columns:
        tech_mask = repd_df["technology_type"].str.lower().str.contains(
            tech_lower.split()[0], na=False
        )
        tech_df = repd_df[tech_mask].copy()
    else:
        tech_df = repd_df.copy()

    # Since synthetic data doesn't have LPA names, use region as proxy
    # In production with real REPD, would filter by Planning Authority
    total = len(tech_df)
    if total == 0:
        return {
            "name": la_name,
            "technology": technology,
            "error": "No matching projects found",
        }

    approved = (tech_df["planning_outcome"] == "Approved").sum()
    refused = (tech_df["planning_outcome"] == "Refused").sum()
    withdrawn = (tech_df["planning_outcome"] == "Withdrawn").sum()

    approval_rate = approved / total if total > 0 else 0

    # Capacity stats
    approved_mw = tech_df.loc[tech_df["planning_outcome"] == "Approved", "capacity_mw"].sum()
    refused_mw = tech_df.loc[tech_df["planning_outcome"] == "Refused", "capacity_mw"].sum()

    # Timeline estimate
    avg_months = tech_df.get("lpa_avg_determination_months", pd.Series([8])).mean()

    # Year-by-year trend
    yearly = {}
    if "year_submitted" in tech_df.columns:
        for year in sorted(tech_df["year_submitted"].unique()):
            yr_df = tech_df[tech_df["year_submitted"] == year]
            yearly[int(year)] = {
                "total": len(yr_df),
                "approved": int((yr_df["planning_outcome"] == "Approved").sum()),
                "refused": int((yr_df["planning_outcome"] == "Refused").sum()),
            }

    return {
        "name": la_name,
        "technology": technology,
        "total_applications": int(total),
        "approved": int(approved),
        "refused": int(refused),
        "withdrawn": int(withdrawn),
        "approval_rate": round(approval_rate, 3),
        "approval_rate_pct": f"{approval_rate * 100:.1f}%",
        "total_approved_mw": round(float(approved_mw), 1),
        "total_refused_mw": round(float(refused_mw), 1),
        "avg_determination_months": round(float(avg_months), 1),
        "yearly_trend": yearly,
        "policy_stance": (
            "SUPPORTIVE" if approval_rate > 0.75 else
            "NEUTRAL" if approval_rate > 0.55 else
            "RESTRICTIVE"
        ),
        "recommendation": (
            "Strong track record — standard application likely sufficient"
            if approval_rate > 0.75 else
            "Mixed record — pre-application consultation recommended"
            if approval_rate > 0.55 else
            "Challenging authority — robust evidence base and pre-app essential"
        ),
    }


# ═══════════════════════════════════════════════════════════════
#  COMPARABLE DECISIONS FINDER
# ═══════════════════════════════════════════════════════════════

def find_comparable_decisions(
    project: dict,
    repd_df: pd.DataFrame | None = None,
    max_results: int = 10,
) -> list[dict]:
    """Find comparable planning decisions from REPD data.

    Matches on technology, capacity range, region, and outcome.

    Args:
        project: dict with technology, capacity_mw, lat, lon, region.
        repd_df: Optional REPD DataFrame. Uses synthetic if None.
        max_results: Maximum number of comparable decisions to return.

    Returns:
        list of dicts with project name, capacity, outcome, distance, year.
    """
    if repd_df is None:
        repd_df = _synthetic_training_data(2000)

    tech = project.get("technology", "Solar Photovoltaics")
    capacity = project.get("capacity_mw", 10)
    region = project.get("region", "")

    # Filter by technology
    tech_lower = tech.lower()
    if "technology_type" in repd_df.columns:
        mask = repd_df["technology_type"].str.lower().str.contains(
            tech_lower.split()[0], na=False
        )
        df = repd_df[mask].copy()
    else:
        df = repd_df.copy()

    if df.empty:
        return []

    # Score similarity
    df["_score"] = 0.0

    # Capacity similarity (closer = better)
    if "capacity_mw" in df.columns:
        df["_cap_diff"] = abs(df["capacity_mw"] - capacity)
        max_diff = df["_cap_diff"].max() or 1
        df["_score"] += (1 - df["_cap_diff"] / max_diff) * 40

    # Region match
    if "region" in df.columns and region:
        df["_score"] += (df["region"] == region).astype(float) * 30

    # Prefer recent decisions
    if "year_submitted" in df.columns:
        max_year = df["year_submitted"].max()
        df["_score"] += (df["year_submitted"] - 2010) / max(max_year - 2010, 1) * 20

    # Prefer decided (not unknown)
    if "planning_outcome" in df.columns:
        df["_score"] += (df["planning_outcome"] != "Unknown").astype(float) * 10

    # Sort and return top
    df = df.sort_values("_score", ascending=False).head(max_results)

    results = []
    for _, row in df.iterrows():
        results.append({
            "name": row.get("Site Name", f"Project #{row.name}"),
            "technology": row.get("technology_type", tech),
            "capacity_mw": round(float(row.get("capacity_mw", 0)), 1),
            "outcome": row.get("planning_outcome", "Unknown"),
            "region": row.get("region", "Unknown"),
            "year": int(row.get("year_submitted", 0)),
            "similarity_score": round(float(row.get("_score", 0)), 1),
        })

    return results


# ═══════════════════════════════════════════════════════════════
#  FULL PREDICTION PIPELINE
# ═══════════════════════════════════════════════════════════════

async def predict_planning_outcome(
    project: dict,
    constraints: dict | None = None,
    grid_context: dict | None = None,
    include_compliance: bool = True,
    include_comparables: bool = True,
) -> dict:
    """Full planning intelligence pipeline.

    Combines constraint analysis, ML prediction, regulatory compliance,
    and comparable decisions into a single comprehensive report.

    Args:
        project: Project specification dict.
        constraints: Pre-fetched constraints (or None to fetch live).
        grid_context: Optional grid connection context.
        include_compliance: Whether to run compliance check.
        include_comparables: Whether to find comparable decisions.

    Returns:
        Comprehensive planning intelligence report.
    """
    t0 = time.time()

    # Fetch constraints if not provided
    if constraints is None:
        lat = project.get("lat", 51.5)
        lon = project.get("lon", -1.0)
        try:
            constraints = await fetch_planning_constraints(lat, lon)
        except Exception as exc:
            log.warning("Constraint fetch failed: %s — using empty constraints", exc)
            constraints = {"summary": {}}

    # Engineer features
    features = engineer_features(project, constraints, grid_context)

    # Get predictor and predict
    predictor = await get_predictor()
    prediction = predictor.predict(features)

    result = {
        "prediction": prediction,
        "features_used": len(features),
        "processing_time_ms": round((time.time() - t0) * 1000, 1),
    }

    # Compliance check
    if include_compliance:
        compliance = check_regulatory_compliance(project, constraints)
        result["compliance"] = compliance

    # Comparable decisions
    if include_comparables:
        comparables = find_comparable_decisions(project)
        result["comparable_decisions"] = comparables
        # Also inject into prediction
        if "prediction" in result and comparables:
            result["prediction"]["comparable_decisions"] = comparables[:5]

    # Constraints summary
    result["constraints_summary"] = constraints.get("summary", {})

    return result

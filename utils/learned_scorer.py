"""
Learned Site Scorer — XGBoost + SHAP + site fingerprinting.

Bootstraps from rule-based scores, then improves with real outcome data.
Provides SHAP explanations for each prediction and composite site fingerprints
for pgvector similarity search.
"""

from __future__ import annotations

import math
import os
import pickle
from pathlib import Path
from typing import Any

MODEL_PATH = Path(os.environ.get("SCORER_MODEL_PATH", "models/site_scorer_xgb.pkl"))

# Feature definitions (17 scalar features)
FEATURE_NAMES = [
    "ghi_kwh_m2_yr",       # Solar resource
    "wind_speed_ms",        # Wind resource
    "slope_mean_deg",       # Terrain slope
    "slope_p90_deg",        # Terrain slope p90
    "south_facing_pct",     # Aspect
    "elevation_m",          # Elevation
    "developable_pct",      # Land use
    "built_pct",            # Urbanisation
    "trees_pct",            # Forest cover
    "water_pct",            # Water bodies
    "grid_distance_km",     # Grid access
    "grid_headroom_mw",     # Grid capacity
    "flood_risk_score",     # Flood risk (0-100)
    "ndvi_mean",            # Vegetation density
    "ndvi_trend_slope",     # NDVI trend direction
    "sar_vv_mean_db",       # SAR backscatter
    "cloud_clear_pct",      # Cloud-free percentage
]


def extract_features(
    lat: float, lon: float,
    terrain: dict | None = None,
    land_use: dict | None = None,
    solar: dict | None = None,
    grid: dict | None = None,
    flood: dict | None = None,
    ndvi_ts: dict | None = None,
    sar: dict | None = None,
    cloud: dict | None = None,
) -> list[float]:
    """
    Extract 17 scalar features from available satellite/grid data.

    Missing data gets UK-average defaults.
    """
    from utils.site_prospector import get_region, UK_REGIONAL_RESOURCE

    region = get_region(lat, lon)
    resource = UK_REGIONAL_RESOURCE.get(region, UK_REGIONAL_RESOURCE["midlands"])

    features = []

    # 1. GHI
    if solar and solar.get("annual_ghi_kwh_m2"):
        features.append(solar["annual_ghi_kwh_m2"])
    else:
        features.append(resource["ghi_kwh_m2_yr"])

    # 2. Wind speed
    features.append(resource["wind_ms"])

    # 3-4. Slope
    if terrain:
        features.append(terrain.get("slope", {}).get("mean_deg", 5))
        features.append(terrain.get("slope", {}).get("p90_deg", 8))
    else:
        features.extend([5.0, 8.0])

    # 5. South-facing
    if terrain:
        features.append(terrain.get("aspect", {}).get("south_facing_pct", 40))
    else:
        features.append(40.0)

    # 6. Elevation
    if terrain:
        features.append(terrain.get("elevation", {}).get("mean_m", 100))
    else:
        features.append(100.0)

    # 7-10. Land use
    if land_use:
        features.append(land_use.get("developable_area_pct", 55))
        cp = land_use.get("class_percentages", {})
        features.append(cp.get("built", 12))
        features.append(cp.get("trees", 13))
        features.append(cp.get("water", 3))
    else:
        features.extend([55.0, 12.0, 13.0, 3.0])

    # 11-12. Grid
    if grid:
        features.append(grid.get("distance_km", 5))
        features.append(grid.get("headroom_mw", 5))
    else:
        features.extend([5.0, 5.0])

    # 13. Flood risk
    if flood:
        features.append(flood.get("flood_risk_score", 10))
    else:
        features.append(10.0)

    # 14-15. NDVI
    if ndvi_ts:
        ad = ndvi_ts.get("annual_data", [])
        if ad:
            features.append(ad[-1].get("ndvi_mean", 0.45))
        else:
            features.append(0.45)
        features.append(ndvi_ts.get("trend", {}).get("slope", 0))
    else:
        features.extend([0.45, 0.0])

    # 16. SAR
    if sar:
        features.append(sar.get("backscatter", {}).get("vv_mean_db", -12))
    else:
        features.append(-12.0)

    # 17. Cloud clear
    if cloud:
        features.append(cloud.get("clear_pct", 42))
    else:
        features.append(42.0)

    return features


def _load_model():
    """Load trained XGBoost model if available."""
    if MODEL_PATH.exists():
        with open(MODEL_PATH, "rb") as f:
            return pickle.load(f)
    return None


def _bootstrap_score(features: list[float]) -> float:
    """
    Generate a rule-based score from features for bootstrapping.

    This serves as the training target until real outcome data is available.
    """
    score = 50.0  # baseline

    # Resource
    ghi = features[0]
    score += ((ghi - 900) / 250) * 15  # +/- 15 from GHI

    # Slope penalty
    slope = features[2]
    if slope > 15:
        score -= 15
    elif slope > 10:
        score -= 8
    elif slope > 5:
        score -= 3

    # South-facing bonus
    south = features[4]
    score += (south - 25) / 75 * 5

    # Developable area
    dev = features[6]
    score += (dev - 30) / 70 * 10

    # Grid access
    dist = features[10]
    if dist > 10:
        score -= 10
    elif dist > 5:
        score -= 5

    headroom = features[11]
    if headroom < 1:
        score -= 8
    elif headroom < 3:
        score -= 3

    # Flood penalty
    flood = features[12]
    score -= flood * 0.1

    return max(0, min(100, round(score, 1)))


def train_model(training_data: list[dict] | None = None) -> dict:
    """
    Train XGBoost scorer on rule-based scores (bootstrap) or real outcomes.

    training_data: list of {"features": [...], "score": float}
    If None, generates synthetic training set from UK coordinate grid.
    """
    try:
        import numpy as np
        from xgboost import XGBRegressor
    except ImportError:
        return {"error": "xgboost not installed — pip install xgboost"}

    if training_data is None:
        # Generate bootstrap training data from UK grid
        import random
        random.seed(42)
        training_data = []
        for _ in range(500):
            lat = random.uniform(50.5, 57.0)
            lon = random.uniform(-5.0, 1.5)
            feats = extract_features(lat, lon)
            score = _bootstrap_score(feats)
            training_data.append({"features": feats, "score": score})

    X = np.array([d["features"] for d in training_data])
    y = np.array([d["score"] for d in training_data])

    model = XGBRegressor(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
    )
    model.fit(X, y)

    # Save model
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)

    return {
        "status": "trained",
        "samples": len(training_data),
        "model_path": str(MODEL_PATH),
        "feature_names": FEATURE_NAMES,
    }


def learned_score(lat: float, lon: float, **data_kwargs) -> dict:
    """
    Get learned (XGBoost) score with SHAP explanations.

    Falls back to bootstrap rule-based score if model not trained.
    """
    features = extract_features(lat, lon, **data_kwargs)
    model = _load_model()

    if model is None:
        # No trained model — return bootstrap
        bs = _bootstrap_score(features)
        return {
            "score": bs,
            "method": "bootstrap_rule_based",
            "note": "XGBoost model not yet trained — call /scoring/train first",
            "features": dict(zip(FEATURE_NAMES, features)),
        }

    try:
        import numpy as np
        X = np.array([features])
        pred = float(model.predict(X)[0])
        pred = max(0, min(100, round(pred, 1)))

        # SHAP explanations
        shap_values = None
        top_drivers = []
        try:
            import shap
            explainer = shap.TreeExplainer(model)
            sv = explainer.shap_values(X)
            shap_values = sv[0].tolist()
            # Top 5 drivers by absolute SHAP value
            indexed = list(enumerate(shap_values))
            indexed.sort(key=lambda x: abs(x[1]), reverse=True)
            for idx, val in indexed[:5]:
                top_drivers.append({
                    "feature": FEATURE_NAMES[idx],
                    "value": features[idx],
                    "shap_impact": round(val, 2),
                    "direction": "positive" if val > 0 else "negative",
                })
        except ImportError:
            top_drivers = [{"note": "Install shap for explanations: pip install shap"}]

        return {
            "score": pred,
            "method": "xgboost_learned",
            "top_drivers": top_drivers,
            "features": dict(zip(FEATURE_NAMES, features)),
        }
    except Exception as e:
        bs = _bootstrap_score(features)
        return {
            "score": bs,
            "method": "bootstrap_fallback",
            "error": str(e)[:200],
            "features": dict(zip(FEATURE_NAMES, features)),
        }


def compute_site_fingerprint(
    prithvi_embedding: list[float] | None = None,
    dino_embedding: list[float] | None = None,
    scalar_features: list[float] | None = None,
) -> list[float]:
    """
    Compute composite site fingerprint (1809-dim):
    Prithvi(768) + DINOv3(1024) + scalar(17), weighted 0.4/0.4/0.2.

    Each component is L2-normalized before weighting.
    """
    import math

    def _l2_normalize(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    # Defaults
    if prithvi_embedding is None:
        prithvi_embedding = [0.0] * 768
    if dino_embedding is None:
        dino_embedding = [0.0] * 1024
    if scalar_features is None:
        scalar_features = [0.0] * 17

    # Pad/truncate to expected dimensions
    prithvi_embedding = (prithvi_embedding + [0.0] * 768)[:768]
    dino_embedding = (dino_embedding + [0.0] * 1024)[:1024]
    scalar_features = (scalar_features + [0.0] * 17)[:17]

    # L2 normalize
    p_norm = _l2_normalize(prithvi_embedding)
    d_norm = _l2_normalize(dino_embedding)
    s_norm = _l2_normalize(scalar_features)

    # Apply weights
    fingerprint = (
        [v * 0.4 for v in p_norm] +
        [v * 0.4 for v in d_norm] +
        [v * 0.2 for v in s_norm]
    )

    return fingerprint

"""
ML Grid Asset Classifier — identifies and classifies energy infrastructure
from grid topology, satellite imagery features, and operational characteristics.

Models:
1. Asset Type Classifier — substations, solar farms, wind farms, BESS, gas peakers, etc.
2. Capacity Estimator — predict MW capacity from observable features
3. Condition Scorer — assess asset condition from age, technology, utilisation patterns
4. Upgrade Priority Ranker — rank assets by reinforcement priority

Trained on synthetic UK grid data matching REPD, TEC register, and DNO datasets.
Can be retrained on real data as it accumulates in the database.
"""
from __future__ import annotations

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("princeps.ml_grid_assets")
DATA_DIR = Path(os.environ.get("PRINCEPS_DATA_DIR", "data"))

# ═══════════════════════════════════════════════════════════════
#  ASSET TYPE TAXONOMY
# ═══════════════════════════════════════════════════════════════

ASSET_TYPES = [
    "substation_primary",      # 33/66kV primary substation
    "substation_grid",         # 132/275/400kV grid supply point
    "solar_farm",              # Ground-mount solar PV
    "solar_rooftop",           # Commercial rooftop solar
    "wind_onshore",            # Onshore wind farm
    "wind_offshore",           # Offshore wind farm
    "bess",                    # Battery energy storage system
    "gas_peaker",              # Gas peaking plant / OCGT
    "gas_ccgt",                # Combined cycle gas turbine
    "biomass",                 # Biomass generation
    "hydro",                   # Hydroelectric
    "interconnector",          # HVDC interconnector terminal
    "ev_charging_hub",         # Large-scale EV charging
    "data_centre",             # Data centre (large power consumer)
]

ASSET_FEATURES = [
    "voltage_kv",              # Connection voltage
    "capacity_mw",             # Registered capacity (if known)
    "demand_mw",               # Average demand draw
    "generation_mw",           # Average generation output
    "area_m2",                 # Footprint area from satellite
    "building_count",          # Number of buildings detected
    "panel_area_m2",           # Solar panel area (from SolarPanelDetector)
    "turbine_count",           # Wind turbine count
    "height_m",                # Max structure height
    "distance_to_grid_km",     # Distance to nearest substation
    "year_commissioned",       # Age indicator
    "latitude",                # Geographic features
    "longitude",
    "elevation_m",             # Terrain
    "ndvi_mean",               # Vegetation (solar sites have low NDVI)
    "built_pct",               # Built-up percentage
    "is_coastal",              # Near coast (offshore wind indicator)
    "has_chimney",             # Thermal plant indicator
    "transformer_count",       # Number of transformers visible
    "container_count",         # BESS containers
]

ASSET_DEFAULTS = {
    "voltage_kv": 33, "capacity_mw": 0, "demand_mw": 0, "generation_mw": 0,
    "area_m2": 5000, "building_count": 2, "panel_area_m2": 0, "turbine_count": 0,
    "height_m": 10, "distance_to_grid_km": 1, "year_commissioned": 2020,
    "latitude": 52.0, "longitude": -1.0, "elevation_m": 80, "ndvi_mean": 0.4,
    "built_pct": 15, "is_coastal": 0, "has_chimney": 0, "transformer_count": 1,
    "container_count": 0,
}

CLASSIFIER_PATH = DATA_DIR / "grid_asset_classifier.pkl"
CAPACITY_PATH = DATA_DIR / "grid_asset_capacity.pkl"
CONDITION_PATH = DATA_DIR / "grid_asset_condition.pkl"

_classifier = None
_capacity_model = None
_condition_model = None


# ═══════════════════════════════════════════════════════════════
#  SYNTHETIC TRAINING DATA
# ═══════════════════════════════════════════════════════════════

def _generate_asset_data(n_per_type=120):
    """Generate synthetic UK grid asset training data."""
    rng = np.random.default_rng(42)
    X_all, y_type, y_cap, y_cond = [], [], [], []
    type_to_idx = {}  # remap to contiguous 0..N

    profiles = {
        "substation_primary": {
            "voltage_kv": (33, 5), "capacity_mw": (30, 15), "demand_mw": (15, 8),
            "generation_mw": (0, 0), "area_m2": (2000, 800), "building_count": (3, 1),
            "panel_area_m2": (0, 0), "turbine_count": (0, 0), "height_m": (8, 3),
            "transformer_count": (3, 1), "container_count": (0, 0),
            "ndvi_mean": (0.2, 0.1), "built_pct": (60, 15), "has_chimney": 0,
        },
        "substation_grid": {
            "voltage_kv": (132, 50), "capacity_mw": (200, 100), "demand_mw": (100, 50),
            "generation_mw": (0, 0), "area_m2": (15000, 5000), "building_count": (5, 2),
            "panel_area_m2": (0, 0), "turbine_count": (0, 0), "height_m": (15, 5),
            "transformer_count": (6, 2), "container_count": (0, 0),
            "ndvi_mean": (0.15, 0.08), "built_pct": (70, 12), "has_chimney": 0,
        },
        "solar_farm": {
            "voltage_kv": (33, 10), "capacity_mw": (20, 15), "demand_mw": (0, 0),
            "generation_mw": (5, 4), "area_m2": (80000, 40000), "building_count": (2, 1),
            "panel_area_m2": (50000, 25000), "turbine_count": (0, 0), "height_m": (3, 1),
            "transformer_count": (2, 1), "container_count": (0, 0),
            "ndvi_mean": (0.15, 0.05), "built_pct": (5, 3), "has_chimney": 0,
        },
        "wind_onshore": {
            "voltage_kv": (33, 10), "capacity_mw": (30, 20), "demand_mw": (0, 0),
            "generation_mw": (10, 7), "area_m2": (200000, 100000), "building_count": (1, 1),
            "panel_area_m2": (0, 0), "turbine_count": (8, 5), "height_m": (100, 30),
            "transformer_count": (1, 1), "container_count": (0, 0),
            "ndvi_mean": (0.5, 0.15), "built_pct": (2, 1), "has_chimney": 0,
        },
        "bess": {
            "voltage_kv": (33, 10), "capacity_mw": (50, 30), "demand_mw": (10, 8),
            "generation_mw": (10, 8), "area_m2": (5000, 3000), "building_count": (1, 1),
            "panel_area_m2": (0, 0), "turbine_count": (0, 0), "height_m": (4, 1),
            "transformer_count": (2, 1), "container_count": (15, 8),
            "ndvi_mean": (0.2, 0.1), "built_pct": (40, 15), "has_chimney": 0,
        },
        "gas_peaker": {
            "voltage_kv": (33, 15), "capacity_mw": (50, 30), "demand_mw": (2, 1),
            "generation_mw": (25, 15), "area_m2": (8000, 4000), "building_count": (3, 2),
            "panel_area_m2": (0, 0), "turbine_count": (0, 0), "height_m": (15, 5),
            "transformer_count": (2, 1), "container_count": (0, 0),
            "ndvi_mean": (0.1, 0.05), "built_pct": (50, 15), "has_chimney": 1,
        },
        "data_centre": {
            "voltage_kv": (132, 50), "capacity_mw": (100, 60), "demand_mw": (80, 40),
            "generation_mw": (0, 0), "area_m2": (20000, 10000), "building_count": (3, 2),
            "panel_area_m2": (0, 0), "turbine_count": (0, 0), "height_m": (12, 4),
            "transformer_count": (4, 2), "container_count": (0, 0),
            "ndvi_mean": (0.1, 0.05), "built_pct": (65, 12), "has_chimney": 0,
        },
    }

    trained_types = list(profiles.keys())
    for asset_type, profile in profiles.items():
        if asset_type not in type_to_idx:
            type_to_idx[asset_type] = len(type_to_idx)
        type_idx = type_to_idx[asset_type]
        n = n_per_type

        for _ in range(n):
            features = []
            for feat in ASSET_FEATURES:
                if feat in profile:
                    val = profile[feat]
                    if isinstance(val, tuple):
                        mean, std = val
                        features.append(max(0, rng.normal(mean, std)))
                    else:
                        features.append(float(val))
                elif feat == "latitude":
                    features.append(rng.uniform(50.5, 56))
                elif feat == "longitude":
                    features.append(rng.uniform(-5, 1.5))
                elif feat == "elevation_m":
                    features.append(rng.normal(80, 50))
                elif feat == "distance_to_grid_km":
                    features.append(rng.exponential(2))
                elif feat == "year_commissioned":
                    features.append(rng.integers(2000, 2025))
                elif feat == "is_coastal":
                    features.append(1 if asset_type == "wind_offshore" else rng.binomial(1, 0.1))
                else:
                    features.append(ASSET_DEFAULTS.get(feat, 0))

            X_all.append(features)
            y_type.append(type_idx)

            # Capacity = stated with noise
            cap = profile.get("capacity_mw", (10, 5))
            real_cap = max(0.1, rng.normal(cap[0], cap[1]) if isinstance(cap, tuple) else cap)
            y_cap.append(real_cap)

            # Condition: 0-100, newer = better
            year = features[ASSET_FEATURES.index("year_commissioned")]
            age = 2025 - year
            condition = max(10, min(100, 95 - age * 2.5 + rng.normal(0, 5)))
            y_cond.append(condition)

    return np.array(X_all), np.array(y_type), np.array(y_cap), np.array(y_cond)


# ═══════════════════════════════════════════════════════════════
#  TRAINING
# ═══════════════════════════════════════════════════════════════

def train_all_models(n_per_type: int = 120) -> dict:
    """Train all three grid asset models."""
    global _classifier, _capacity_model, _condition_model
    from xgboost import XGBClassifier, XGBRegressor
    from sklearn.metrics import accuracy_score, mean_absolute_error, r2_score

    X, y_type, y_cap, y_cond = _generate_asset_data(n_per_type)
    split = int(0.8 * len(X))
    idx = np.random.default_rng(42).permutation(len(X))
    X, y_type, y_cap, y_cond = X[idx], y_type[idx], y_cap[idx], y_cond[idx]

    # 1. Asset type classifier
    clf = XGBClassifier(n_estimators=200, max_depth=6, learning_rate=0.1,
                        use_label_encoder=False, eval_metric="mlogloss", random_state=42)
    clf.fit(X[:split], y_type[:split], eval_set=[(X[split:], y_type[split:])], verbose=False)
    acc = accuracy_score(y_type[split:], clf.predict(X[split:]))
    log.info("Asset classifier: %.1f%% accuracy", acc * 100)

    # 2. Capacity estimator
    cap_reg = XGBRegressor(n_estimators=200, max_depth=5, learning_rate=0.1, random_state=42)
    cap_reg.fit(X[:split], y_cap[:split], eval_set=[(X[split:], y_cap[split:])], verbose=False)
    cap_preds = cap_reg.predict(X[split:])
    cap_mae = mean_absolute_error(y_cap[split:], cap_preds)
    cap_r2 = r2_score(y_cap[split:], cap_preds)
    log.info("Capacity estimator: MAE=%.1f MW, R²=%.3f", cap_mae, cap_r2)

    # 3. Condition scorer
    cond_reg = XGBRegressor(n_estimators=150, max_depth=4, learning_rate=0.1, random_state=42)
    cond_reg.fit(X[:split], y_cond[:split], eval_set=[(X[split:], y_cond[split:])], verbose=False)
    cond_preds = cond_reg.predict(X[split:])
    cond_mae = mean_absolute_error(y_cond[split:], cond_preds)

    # Save — include type mapping
    DATA_DIR.mkdir(exist_ok=True)
    idx_to_type = {v: k for k, v in type_to_idx.items()}
    with open(CLASSIFIER_PATH, "wb") as f:
        pickle.dump({"model": clf, "idx_to_type": idx_to_type, "trained_types": trained_types}, f)
    with open(CAPACITY_PATH, "wb") as f:
        pickle.dump(cap_reg, f)
    with open(CONDITION_PATH, "wb") as f:
        pickle.dump(cond_reg, f)

    _classifier, _capacity_model, _condition_model = clf, cap_reg, cond_reg

    meta = {
        "n_types": len(set(y_type)),
        "n_samples": len(X),
        "classifier_accuracy": round(acc, 3),
        "capacity_mae_mw": round(cap_mae, 1),
        "capacity_r2": round(cap_r2, 3),
        "condition_mae": round(cond_mae, 1),
    }
    with open(DATA_DIR / "grid_asset_model_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    return meta


_idx_to_type = {}

def _load_models():
    global _classifier, _capacity_model, _condition_model, _idx_to_type
    if _classifier is not None:
        return
    if CLASSIFIER_PATH.exists():
        with open(CLASSIFIER_PATH, "rb") as f:
            data = pickle.load(f)
            if isinstance(data, dict):
                _classifier = data["model"]
                _idx_to_type = data.get("idx_to_type", {})
            else:
                _classifier = data
    if CAPACITY_PATH.exists():
        with open(CAPACITY_PATH, "rb") as f:
            _capacity_model = pickle.load(f)
    if CONDITION_PATH.exists():
        with open(CONDITION_PATH, "rb") as f:
            _condition_model = pickle.load(f)
    if _classifier is None:
        train_all_models()


# ═══════════════════════════════════════════════════════════════
#  PREDICTION
# ═══════════════════════════════════════════════════════════════

def classify_asset(features: dict) -> dict:
    """
    Classify an energy asset from observable features.

    Returns: asset type, confidence, estimated capacity, condition score,
    upgrade priority, SHAP factors.
    """
    _load_models()
    x = np.array([[features.get(f, ASSET_DEFAULTS[f]) for f in ASSET_FEATURES]])

    # Type classification
    proba = _classifier.predict_proba(x)[0]
    pred_idx = int(np.argmax(proba))
    asset_type = _idx_to_type.get(pred_idx, ASSET_TYPES[min(pred_idx, len(ASSET_TYPES) - 1)])
    confidence = float(proba[pred_idx])

    # Top 3 candidates
    top3_idx = np.argsort(proba)[::-1][:3]
    candidates = [{"type": _idx_to_type.get(int(i), f"type_{i}"), "probability": round(float(proba[i]), 3)} for i in top3_idx]

    # Capacity estimation
    est_capacity = float(_capacity_model.predict(x)[0])

    # Condition assessment
    condition = float(_condition_model.predict(x)[0])
    condition = max(0, min(100, condition))
    if condition >= 80:
        condition_label = "GOOD"
    elif condition >= 50:
        condition_label = "FAIR"
    elif condition >= 30:
        condition_label = "POOR"
    else:
        condition_label = "CRITICAL"

    # Upgrade priority
    year = features.get("year_commissioned", 2020)
    age = 2025 - year
    capacity = features.get("capacity_mw", est_capacity)
    utilisation = features.get("demand_mw", 0) / max(capacity, 0.1)
    upgrade_score = (
        (100 - condition) * 0.4 +
        min(age * 3, 40) +
        min(utilisation * 30, 30) * (1 if utilisation > 0.8 else 0)
    )
    upgrade_score = max(0, min(100, upgrade_score))
    if upgrade_score >= 70:
        upgrade_priority = "HIGH"
    elif upgrade_score >= 40:
        upgrade_priority = "MEDIUM"
    else:
        upgrade_priority = "LOW"

    # SHAP
    top_factors = []
    try:
        import shap
        explainer = shap.TreeExplainer(_classifier)
        sv = explainer.shap_values(x)
        if isinstance(sv, list):
            sv_pred = sv[pred_idx][0]
        elif sv.ndim == 3:
            sv_pred = sv[0, :, pred_idx]
        else:
            sv_pred = sv[0]
        indices = np.argsort(np.abs(sv_pred))[::-1][:5]
        for i in indices:
            top_factors.append({
                "feature": ASSET_FEATURES[i],
                "value": round(float(x[0, i]), 2),
                "impact": round(float(sv_pred[i]), 3),
                "direction": "supports classification" if sv_pred[i] > 0 else "against classification",
            })
    except Exception:
        pass

    return {
        "asset_type": asset_type,
        "confidence": round(confidence, 3),
        "candidates": candidates,
        "estimated_capacity_mw": round(est_capacity, 1),
        "condition": {
            "score": round(condition, 1),
            "label": condition_label,
            "age_years": age,
        },
        "upgrade": {
            "priority": upgrade_priority,
            "score": round(upgrade_score, 1),
            "utilisation_pct": round(utilisation * 100, 1),
        },
        "top_factors": top_factors,
        "model": "grid_asset_xgb_v1",
    }


def classify_batch(assets: list[dict]) -> list[dict]:
    """Classify multiple assets in batch. Returns list with rankings."""
    results = []
    for i, asset in enumerate(assets):
        result = classify_asset(asset)
        result["index"] = i
        result["name"] = asset.get("name", f"Asset {i+1}")
        results.append(result)

    # Rank by upgrade priority
    results.sort(key=lambda r: r["upgrade"]["score"], reverse=True)
    for rank, r in enumerate(results, 1):
        r["upgrade_rank"] = rank

    return results


def identify_grid_assets_in_area(substations: list[dict], generators: list[dict] = None) -> list[dict]:
    """
    Classify all known grid assets in an area from substation + generator data.

    Input: lists of substation/generator dicts with voltage_kv, capacity_mw, lat, lon, etc.
    Output: classified assets with type, condition, upgrade priority, capacity estimates
    """
    all_assets = []

    for sub in substations:
        features = {
            "voltage_kv": sub.get("voltage_kv", 33),
            "capacity_mw": sub.get("capacity_mw") or sub.get("headroom_mw", 30),
            "demand_mw": sub.get("demand_mw", 15),
            "generation_mw": 0,
            "area_m2": 2000,
            "building_count": 3,
            "transformer_count": sub.get("transformer_count", 2),
            "latitude": sub.get("lat", 52),
            "longitude": sub.get("lon", -1),
            "year_commissioned": sub.get("year", 2010),
            "name": sub.get("name", "Unknown Substation"),
        }
        result = classify_asset(features)
        result["source_data"] = sub
        all_assets.append(result)

    for gen in (generators or []):
        tech = gen.get("technology", "").lower()
        features = {
            "voltage_kv": gen.get("voltage_kv", 33),
            "capacity_mw": gen.get("capacity_mw", 5),
            "demand_mw": 0,
            "generation_mw": gen.get("capacity_mw", 5) * 0.3,
            "area_m2": gen.get("area_m2", 10000),
            "panel_area_m2": gen.get("capacity_mw", 0) * 2000 if "solar" in tech else 0,
            "turbine_count": gen.get("turbine_count", 0) if "wind" in tech else 0,
            "container_count": gen.get("container_count", 0) if "batt" in tech or "bess" in tech else 0,
            "has_chimney": 1 if "gas" in tech else 0,
            "latitude": gen.get("lat", 52),
            "longitude": gen.get("lon", -1),
            "year_commissioned": gen.get("year", 2020),
            "name": gen.get("name", f"{tech.title()} Generator"),
        }
        result = classify_asset(features)
        result["source_data"] = gen
        all_assets.append(result)

    # Sort by upgrade priority
    all_assets.sort(key=lambda a: a["upgrade"]["score"], reverse=True)
    for rank, a in enumerate(all_assets, 1):
        a["upgrade_rank"] = rank

    return all_assets

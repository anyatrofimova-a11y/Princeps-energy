"""
Advanced ML models for Princeps site analysis.

Three XGBoost models:
1. Planning Risk Predictor — classifies planning outcome (APPROVED/CONDITIONAL/REFUSED)
2. Financial IRR Predictor — regresses project IRR (%)
3. Site Ranking Model — LambdaRank-style pairwise ranker for candidate sites

Trained on synthetic UK data; retrain on real outcomes via train_and_save_*().
"""

from __future__ import annotations

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("princeps.ml_advanced_models")

DATA_DIR = Path(os.environ.get("PRINCEPS_DATA_DIR", "data"))

# Model file paths
PLANNING_CLF_PATH = DATA_DIR / "planning_risk_xgb.pkl"
PLANNING_META_PATH = DATA_DIR / "planning_risk_meta.json"
IRR_REG_PATH = DATA_DIR / "financial_irr_xgb.pkl"
IRR_META_PATH = DATA_DIR / "financial_irr_meta.json"
RANKER_PATH = DATA_DIR / "site_ranker_xgb.pkl"
RANKER_META_PATH = DATA_DIR / "site_ranker_meta.json"

# ============================================================================
# 1. Planning Risk Predictor
# ============================================================================

PLANNING_FEATURES = [
    "distance_to_residential_km",
    "num_nearby_solar_farms",
    "aonb_proximity_km",
    "green_belt",
    "flood_zone",
    "agricultural_grade",
    "local_authority_approval_rate",
    "capacity_mw",
    "height_above_ground_m",
    "landscape_sensitivity",
]

PLANNING_DEFAULTS = {
    "distance_to_residential_km": 1.5,
    "num_nearby_solar_farms": 2,
    "aonb_proximity_km": 15.0,
    "green_belt": 0.0,
    "flood_zone": 1,
    "agricultural_grade": 3,
    "local_authority_approval_rate": 0.75,
    "capacity_mw": 30.0,
    "height_above_ground_m": 3.0,
    "landscape_sensitivity": 3,
}

PLANNING_LABELS = {0: "APPROVED", 1: "CONDITIONAL", 2: "REFUSED"}
PLANNING_LABELS_INV = {v: k for k, v in PLANNING_LABELS.items()}


def _generate_planning_data(n: int = 800, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Generate n synthetic UK planning application samples.

    UK solar approval rate ~85% (APPROVED + CONDITIONAL), refusal ~15%.
    Distribution: ~50% APPROVED, ~35% CONDITIONAL, ~15% REFUSED.
    """
    rng = np.random.default_rng(seed)
    X = np.zeros((n, 10), dtype=np.float64)

    # 0: distance_to_residential_km — 0.1-10km, log-normal, median ~1.5km
    X[:, 0] = rng.lognormal(0.4, 0.6, n).clip(0.1, 15.0)

    # 1: num_nearby_solar_farms — 0-8, Poisson(2)
    X[:, 1] = rng.poisson(2, n).clip(0, 12).astype(np.float64)

    # 2: aonb_proximity_km — 0-50, exponential, most sites far from AONB
    X[:, 2] = rng.exponential(12, n).clip(0.1, 60.0)

    # 3: green_belt — binary, ~12% of England is green belt
    X[:, 3] = (rng.random(n) < 0.12).astype(np.float64)

    # 4: flood_zone — 1 (low), 2 (medium), 3 (high), most are zone 1
    fz_probs = rng.random(n)
    X[:, 4] = np.where(fz_probs < 0.70, 1, np.where(fz_probs < 0.90, 2, 3)).astype(np.float64)

    # 5: agricultural_grade — 1 (best) to 5 (worst), most UK land is 3
    ag_probs = rng.random(n)
    X[:, 5] = np.where(ag_probs < 0.05, 1,
              np.where(ag_probs < 0.20, 2,
              np.where(ag_probs < 0.65, 3,
              np.where(ag_probs < 0.85, 4, 5)))).astype(np.float64)

    # 6: local_authority_approval_rate — 0.5-0.95, beta distribution
    X[:, 6] = rng.beta(8, 2.5, n).clip(0.4, 0.98)

    # 7: capacity_mw — 1-200MW, log-normal
    X[:, 7] = rng.lognormal(2.8, 0.8, n).clip(0.5, 500)

    # 8: height_above_ground_m — 2-5m for solar panels, fixed rows
    X[:, 8] = rng.normal(3.0, 0.5, n).clip(1.5, 6.0)

    # 9: landscape_sensitivity — 1-5, most medium
    ls_probs = rng.random(n)
    X[:, 9] = np.where(ls_probs < 0.10, 1,
              np.where(ls_probs < 0.35, 2,
              np.where(ls_probs < 0.65, 3,
              np.where(ls_probs < 0.85, 4, 5)))).astype(np.float64)

    # --- Compute labels from domain rules ---
    scores = np.full(n, 70.0)  # Start optimistic (UK 85% approval)

    # Distance to residential: closer = more objections
    scores -= np.where(X[:, 0] < 0.3, 25,
              np.where(X[:, 0] < 0.5, 15,
              np.where(X[:, 0] < 1.0, 8,
              np.where(X[:, 0] < 2.0, 3, 0))))

    # Nearby solar farms: precedent helps, but too many = cumulative impact
    scores += np.where(X[:, 1] > 0, 3, 0)  # Precedent bonus
    scores -= np.where(X[:, 1] > 5, 8, 0)  # Saturation penalty

    # AONB proximity: very close = strong refusal signal
    scores -= np.where(X[:, 2] < 1.0, 25,
              np.where(X[:, 2] < 3.0, 12,
              np.where(X[:, 2] < 5.0, 5, 0)))

    # Green belt: strong planning constraint in England
    scores -= X[:, 3] * 30

    # Flood zone: zone 3 = sequential test required
    scores -= np.where(X[:, 4] == 3, 18,
              np.where(X[:, 4] == 2, 6, 0))

    # Agricultural grade: grade 1-2 (BMV) strongly resisted
    scores -= np.where(X[:, 5] == 1, 22,
              np.where(X[:, 5] == 2, 12,
              np.where(X[:, 5] == 3, 0,
              np.where(X[:, 5] == 4, -3, -5))))  # Grade 4-5 = easier

    # Local authority approval rate
    scores += (X[:, 6] - 0.7) * 30

    # Capacity: very large projects face more scrutiny (NSIP > 50MW)
    scores -= np.where(X[:, 7] > 50, 10,
              np.where(X[:, 7] > 100, 18, 0))

    # Landscape sensitivity
    scores -= np.where(X[:, 9] >= 5, 15,
              np.where(X[:, 9] >= 4, 8,
              np.where(X[:, 9] >= 3, 2, 0)))

    # Add noise
    scores += rng.normal(0, 4, n)
    scores = scores.clip(0, 100)

    # Map to classes: APPROVED (>= 60), CONDITIONAL (40-60), REFUSED (< 40)
    y = np.where(scores >= 60, 0,  # APPROVED
         np.where(scores >= 40, 1,  # CONDITIONAL
                  2))               # REFUSED

    return X, y


# Cached model
_planning_cache: Any = None


def _load_planning_model():
    global _planning_cache
    if _planning_cache is None and PLANNING_CLF_PATH.exists():
        with open(PLANNING_CLF_PATH, "rb") as f:
            _planning_cache = pickle.load(f)
    return _planning_cache


def train_and_save_planning(n_samples: int = 800, seed: int = 42) -> dict:
    """Train XGBoost planning risk classifier on synthetic data."""
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, classification_report
    from xgboost import XGBClassifier

    X, y = _generate_planning_data(n_samples, seed)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y,
    )

    clf = XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=seed,
        eval_metric="mlogloss",
    )
    clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    report = classification_report(
        y_test, y_pred,
        target_names=["APPROVED", "CONDITIONAL", "REFUSED"],
        output_dict=True,
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PLANNING_CLF_PATH, "wb") as f:
        pickle.dump(clf, f)

    meta = {
        "model": "planning_risk_predictor",
        "n_samples": n_samples,
        "seed": seed,
        "features": PLANNING_FEATURES,
        "accuracy": round(acc, 4),
        "report": report,
        "class_distribution": {
            PLANNING_LABELS[k]: int(v)
            for k, v in zip(*np.unique(y, return_counts=True))
        },
    }
    with open(PLANNING_META_PATH, "w") as f:
        json.dump(meta, f, indent=2, default=str)

    global _planning_cache
    _planning_cache = None

    log.info("Trained planning risk predictor: accuracy=%.3f", acc)
    return meta


def predict_planning_risk(features: dict[str, float]) -> dict:
    """Predict planning outcome from 10 features.

    Returns dict with outcome, probabilities, shap_values, top_factors.
    """
    clf = _load_planning_model()
    if clf is None:
        # Auto-train
        log.info("Planning model not found, training on first use...")
        train_and_save_planning()
        clf = _load_planning_model()
        if clf is None:
            return {"error": "Planning model training failed."}

    vec = np.array(
        [[features.get(f, PLANNING_DEFAULTS[f]) for f in PLANNING_FEATURES]],
        dtype=np.float64,
    )

    pred = int(clf.predict(vec)[0])
    proba = clf.predict_proba(vec)[0]
    outcome = PLANNING_LABELS[pred]
    confidence = float(round(proba[pred] * 100, 1))

    # SHAP
    shap_dict = {}
    top_factors = []
    try:
        import shap
        explainer = shap.TreeExplainer(clf)
        sv = explainer.shap_values(vec)
        # For multi-class, sv is list of arrays; use the predicted class
        if isinstance(sv, list):
            shap_arr = sv[pred][0]
        else:
            shap_arr = sv[0]
        shap_dict = {
            PLANNING_FEATURES[i]: round(float(shap_arr[i]), 3)
            for i in range(len(PLANNING_FEATURES))
        }
        indexed = sorted(enumerate(shap_arr), key=lambda x: abs(x[1]), reverse=True)
        for idx, val in indexed[:5]:
            top_factors.append({
                "feature": PLANNING_FEATURES[idx],
                "value": round(float(vec[0, idx]), 3),
                "shap_impact": round(float(val), 3),
                "direction": "positive" if val > 0 else "negative",
                "explanation": _explain_planning(PLANNING_FEATURES[idx], float(vec[0, idx]), float(val)),
            })
    except Exception as e:
        log.warning("SHAP explanation failed for planning model: %s", e)
        top_factors = [{"note": f"SHAP unavailable: {e}"}]

    return {
        "outcome": outcome,
        "confidence": confidence,
        "probabilities": {
            PLANNING_LABELS[i]: round(float(proba[i]) * 100, 1) for i in range(3)
        },
        "shap_values": shap_dict,
        "top_factors": top_factors,
    }


def _explain_planning(name: str, value: float, shap_val: float) -> str:
    direction = "supports approval" if shap_val > 0 else "increases risk"
    explanations = {
        "distance_to_residential_km": f"Distance of {value:.1f} km to nearest residential area {direction}",
        "num_nearby_solar_farms": f"{int(value)} nearby solar farms {'set precedent' if shap_val > 0 else 'raise cumulative impact concerns'}",
        "aonb_proximity_km": f"AONB {value:.1f} km away {direction}",
        "green_belt": f"{'In' if value > 0.5 else 'Not in'} green belt {direction}",
        "flood_zone": f"Flood zone {int(value)} {direction}",
        "agricultural_grade": f"Agricultural grade {int(value)} land {direction}",
        "local_authority_approval_rate": f"LA approval rate of {value:.0%} {direction}",
        "capacity_mw": f"Proposed {value:.0f} MW capacity {direction}",
        "height_above_ground_m": f"Panel height of {value:.1f} m {direction}",
        "landscape_sensitivity": f"Landscape sensitivity level {int(value)} {direction}",
    }
    return explanations.get(name, f"{name}={value:.2f} {direction}")


# ============================================================================
# 2. Financial IRR Predictor
# ============================================================================

IRR_FEATURES = [
    "capacity_mw",
    "annual_yield_mwh",
    "grid_distance_km",
    "connection_cost_gbp",
    "ppa_price_gbp_mwh",
    "capex_per_kw",
    "opex_per_kw_yr",
    "degradation_pct",
    "project_life_years",
    "wacc_pct",
    "land_rent_per_ha",
]

IRR_DEFAULTS = {
    "capacity_mw": 30.0,
    "annual_yield_mwh": 28000.0,
    "grid_distance_km": 5.0,
    "connection_cost_gbp": 1_500_000.0,
    "ppa_price_gbp_mwh": 55.0,
    "capex_per_kw": 550.0,
    "opex_per_kw_yr": 10.0,
    "degradation_pct": 0.5,
    "project_life_years": 25,
    "wacc_pct": 6.0,
    "land_rent_per_ha": 1200.0,
}

_irr_cache: Any = None


def _load_irr_model():
    global _irr_cache
    if _irr_cache is None and IRR_REG_PATH.exists():
        with open(IRR_REG_PATH, "rb") as f:
            _irr_cache = pickle.load(f)
    return _irr_cache


def _generate_irr_data(n: int = 600, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Generate n synthetic UK solar project IRR samples.

    UK solar IRR typically 6-15%.
    """
    rng = np.random.default_rng(seed)
    X = np.zeros((n, 11), dtype=np.float64)

    # 0: capacity_mw — 1-200, log-normal
    X[:, 0] = rng.lognormal(2.8, 0.7, n).clip(0.5, 500)

    # 1: annual_yield_mwh — correlated with capacity, ~900-1050 MWh/MWp in UK
    capacity_factor = rng.normal(0.105, 0.015, n).clip(0.08, 0.14)
    X[:, 1] = X[:, 0] * 1000 * capacity_factor * 8760  # MWh/yr
    # Simplify: yield = capacity * specific_yield
    specific_yield = rng.normal(950, 60, n).clip(800, 1100)  # kWh/kWp
    X[:, 1] = X[:, 0] * 1000 * specific_yield / 1000  # MWh/yr

    # 2: grid_distance_km — 0.5-25
    X[:, 2] = rng.lognormal(1.0, 0.7, n).clip(0.3, 30)

    # 3: connection_cost_gbp — correlated with distance + capacity
    base_cost = X[:, 2] * rng.normal(100_000, 30_000, n).clip(50_000, 200_000)
    capacity_cost = X[:, 0] * rng.normal(20_000, 5_000, n).clip(10_000, 40_000)
    X[:, 3] = (base_cost + capacity_cost).clip(50_000, 20_000_000)

    # 4: ppa_price_gbp_mwh — 40-80 £/MWh, normal
    X[:, 4] = rng.normal(55, 10, n).clip(35, 90)

    # 5: capex_per_kw — 400-800 £/kW, trending down
    X[:, 5] = rng.normal(550, 80, n).clip(350, 900)

    # 6: opex_per_kw_yr — 8-15 £/kW/yr
    X[:, 6] = rng.normal(10.5, 2.0, n).clip(6, 20)

    # 7: degradation_pct — 0.3-0.8%/yr
    X[:, 7] = rng.normal(0.5, 0.1, n).clip(0.2, 1.0)

    # 8: project_life_years — 20-35
    X[:, 8] = rng.choice([20, 25, 30, 35], n, p=[0.1, 0.5, 0.3, 0.1]).astype(np.float64)

    # 9: wacc_pct — 4-10%
    X[:, 9] = rng.normal(6.5, 1.2, n).clip(3.5, 12)

    # 10: land_rent_per_ha — 800-2000 £/ha/yr
    X[:, 10] = rng.normal(1200, 250, n).clip(500, 3000)

    # --- Compute IRR from simplified DCF logic ---
    y = _compute_irr_labels(X, rng)

    return X, y


def _compute_irr_labels(X: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Approximate IRR from project economics."""
    n = X.shape[0]

    capacity_kw = X[:, 0] * 1000
    annual_yield = X[:, 1]  # MWh
    ppa_price = X[:, 4]
    capex_per_kw = X[:, 5]
    opex_per_kw = X[:, 6]
    degradation = X[:, 7] / 100
    project_life = X[:, 8]
    connection_cost = X[:, 3]
    land_rent = X[:, 10]

    # Total CAPEX
    total_capex = capacity_kw * capex_per_kw + connection_cost

    # Annual revenue (year 1)
    annual_revenue = annual_yield * ppa_price

    # Annual opex
    area_ha = capacity_kw / 1000 * 1.8  # ~1.8 ha/MW for UK ground-mount
    annual_opex = capacity_kw * opex_per_kw + area_ha * land_rent

    # Simplified IRR approximation: use average annual cashflow over project life
    # Account for degradation by using mid-life yield
    mid_life_factor = (1 - degradation) ** (project_life / 2)
    avg_revenue = annual_revenue * mid_life_factor
    avg_net_cashflow = avg_revenue - annual_opex

    # Simple IRR ≈ (avg_cashflow / capex) adjusted for project length
    # More accurate: use annuity factor approximation
    irr_approx = np.where(
        total_capex > 0,
        (avg_net_cashflow / total_capex) * 100 * (1 - 1 / project_life * 3),
        0,
    )

    # Add noise and clip to realistic UK range
    irr_approx += rng.normal(0, 0.8, n)
    irr_approx = irr_approx.clip(1, 25).round(2)

    return irr_approx


def train_and_save_irr(n_samples: int = 600, seed: int = 42) -> dict:
    """Train XGBoost IRR regressor on synthetic data."""
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_error, r2_score
    from xgboost import XGBRegressor

    X, y = _generate_irr_data(n_samples, seed)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed,
    )

    reg = XGBRegressor(
        n_estimators=250,
        max_depth=6,
        learning_rate=0.06,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=seed,
    )
    reg.fit(X_train, y_train)
    y_pred = reg.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(IRR_REG_PATH, "wb") as f:
        pickle.dump(reg, f)

    meta = {
        "model": "financial_irr_predictor",
        "n_samples": n_samples,
        "seed": seed,
        "features": IRR_FEATURES,
        "mae": round(mae, 3),
        "r2": round(r2, 4),
        "irr_range": {"min": round(float(y.min()), 2), "max": round(float(y.max()), 2)},
        "irr_mean": round(float(y.mean()), 2),
    }
    with open(IRR_META_PATH, "w") as f:
        json.dump(meta, f, indent=2, default=str)

    global _irr_cache
    _irr_cache = None

    log.info("Trained financial IRR predictor: MAE=%.3f R2=%.3f", mae, r2)
    return meta


def predict_financial_irr(features: dict[str, float]) -> dict:
    """Predict project IRR from 11 features.

    Returns dict with irr_pct, confidence_interval, shap_values, top_factors.
    """
    reg = _load_irr_model()
    if reg is None:
        log.info("IRR model not found, training on first use...")
        train_and_save_irr()
        reg = _load_irr_model()
        if reg is None:
            return {"error": "IRR model training failed."}

    vec = np.array(
        [[features.get(f, IRR_DEFAULTS[f]) for f in IRR_FEATURES]],
        dtype=np.float64,
    )

    irr_pred = float(reg.predict(vec)[0])
    irr_pred = round(max(0, min(30, irr_pred)), 2)

    # Confidence interval (bootstrap-style estimate from training MAE)
    try:
        with open(IRR_META_PATH) as f:
            meta = json.load(f)
        mae = meta.get("mae", 1.0)
    except Exception:
        mae = 1.0

    ci_lower = round(max(0, irr_pred - 1.96 * mae), 2)
    ci_upper = round(min(30, irr_pred + 1.96 * mae), 2)

    # SHAP
    shap_dict = {}
    top_factors = []
    try:
        import shap
        explainer = shap.TreeExplainer(reg)
        sv = explainer.shap_values(vec)
        shap_arr = sv[0]
        shap_dict = {
            IRR_FEATURES[i]: round(float(shap_arr[i]), 3)
            for i in range(len(IRR_FEATURES))
        }
        indexed = sorted(enumerate(shap_arr), key=lambda x: abs(x[1]), reverse=True)
        for idx, val in indexed[:5]:
            top_factors.append({
                "feature": IRR_FEATURES[idx],
                "value": round(float(vec[0, idx]), 3),
                "shap_impact": round(float(val), 3),
                "direction": "positive" if val > 0 else "negative",
                "explanation": _explain_irr(IRR_FEATURES[idx], float(vec[0, idx]), float(val)),
            })
    except Exception as e:
        log.warning("SHAP explanation failed for IRR model: %s", e)
        top_factors = [{"note": f"SHAP unavailable: {e}"}]

    # Viability assessment
    if irr_pred >= 10:
        viability = "STRONG"
    elif irr_pred >= 7:
        viability = "VIABLE"
    elif irr_pred >= 5:
        viability = "MARGINAL"
    else:
        viability = "UNVIABLE"

    return {
        "irr_pct": irr_pred,
        "viability": viability,
        "confidence_interval": {"lower": ci_lower, "upper": ci_upper, "level": "95%"},
        "shap_values": shap_dict,
        "top_factors": top_factors,
    }


def _explain_irr(name: str, value: float, shap_val: float) -> str:
    direction = "improves" if shap_val > 0 else "reduces"
    explanations = {
        "capacity_mw": f"Project size of {value:.0f} MW {direction} returns through scale",
        "annual_yield_mwh": f"Annual yield of {value:,.0f} MWh {direction} revenue",
        "grid_distance_km": f"Grid distance of {value:.1f} km {direction} connection economics",
        "connection_cost_gbp": f"Connection cost of \u00a3{value:,.0f} {direction} IRR",
        "ppa_price_gbp_mwh": f"PPA price of \u00a3{value:.0f}/MWh {direction} revenue certainty",
        "capex_per_kw": f"CAPEX of \u00a3{value:.0f}/kW {direction} capital efficiency",
        "opex_per_kw_yr": f"OPEX of \u00a3{value:.1f}/kW/yr {direction} operating margin",
        "degradation_pct": f"Degradation of {value:.1f}%/yr {direction} lifetime yield",
        "project_life_years": f"Project life of {int(value)} years {direction} total returns",
        "wacc_pct": f"WACC of {value:.1f}% {direction} hurdle rate comparison",
        "land_rent_per_ha": f"Land rent of \u00a3{value:,.0f}/ha/yr {direction} operating cost",
    }
    return explanations.get(name, f"{name}={value:.2f} {direction} IRR")


# ============================================================================
# 3. Site Ranking Model (LambdaRank-style pairwise XGBoost)
# ============================================================================

# 17 base features (same as ml_site_classifier) + planning_risk_score + financial_irr
RANKER_FEATURES = [
    "ghi_kwh_m2_yr",
    "wind_speed_ms",
    "slope_mean_deg",
    "slope_p90_deg",
    "south_facing_pct",
    "elevation_m",
    "developable_pct",
    "built_pct",
    "trees_pct",
    "water_pct",
    "grid_distance_km",
    "grid_headroom_mw",
    "flood_risk_score",
    "ndvi_mean",
    "ndvi_trend_slope",
    "sar_vv_mean_db",
    "cloud_clear_pct",
    "planning_risk_score",
    "financial_irr",
]

RANKER_DEFAULTS = {
    "ghi_kwh_m2_yr": 1000.0,
    "wind_speed_ms": 6.0,
    "slope_mean_deg": 5.0,
    "slope_p90_deg": 8.0,
    "south_facing_pct": 40.0,
    "elevation_m": 100.0,
    "developable_pct": 55.0,
    "built_pct": 12.0,
    "trees_pct": 13.0,
    "water_pct": 3.0,
    "grid_distance_km": 5.0,
    "grid_headroom_mw": 5.0,
    "flood_risk_score": 10.0,
    "ndvi_mean": 0.45,
    "ndvi_trend_slope": 0.0,
    "sar_vv_mean_db": -12.0,
    "cloud_clear_pct": 42.0,
    "planning_risk_score": 70.0,
    "financial_irr": 9.0,
}

_ranker_cache: Any = None


def _load_ranker():
    global _ranker_cache
    if _ranker_cache is None and RANKER_PATH.exists():
        with open(RANKER_PATH, "rb") as f:
            _ranker_cache = pickle.load(f)
    return _ranker_cache


def _generate_ranker_data(n_groups: int = 80, group_size: int = 8, seed: int = 42) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate pairwise ranking data: groups of sites with relevance labels.

    Returns (X, y_relevance, group_sizes) where y_relevance in [0, 4].
    """
    rng = np.random.default_rng(seed)
    n = n_groups * group_size
    X = np.zeros((n, 19), dtype=np.float64)

    # Base site features (same distributions as ml_site_classifier)
    X[:, 0] = rng.normal(1000, 50, n).clip(850, 1150)   # GHI
    X[:, 1] = rng.normal(6.0, 1.2, n).clip(3, 12)       # Wind
    X[:, 2] = rng.exponential(3.0, n).clip(0, 25)        # Slope mean
    X[:, 3] = X[:, 2] * rng.uniform(1.2, 2.0, n)        # Slope p90
    X[:, 4] = rng.normal(45, 15, n).clip(10, 90)         # South facing
    X[:, 5] = rng.exponential(80, n).clip(5, 600)        # Elevation
    X[:, 6] = (rng.beta(3, 1.5, n) * 80 + 15).clip(5, 98)  # Developable
    X[:, 7] = rng.exponential(8, n).clip(0, 60)          # Built
    X[:, 8] = rng.exponential(10, n).clip(0, 60)         # Trees
    X[:, 9] = rng.exponential(2, n).clip(0, 30)          # Water
    X[:, 10] = rng.lognormal(1.2, 0.7, n).clip(0.3, 30) # Grid dist
    X[:, 11] = rng.exponential(15, n).clip(0, 120)       # Grid headroom
    X[:, 12] = rng.exponential(12, n).clip(0, 100)       # Flood risk
    X[:, 13] = rng.normal(0.45, 0.12, n).clip(0.1, 0.9) # NDVI
    X[:, 14] = rng.normal(0, 0.01, n).clip(-0.05, 0.05) # NDVI trend
    X[:, 15] = rng.normal(-12, 2.5, n).clip(-20, -3)     # SAR VV
    X[:, 16] = rng.normal(42, 6, n).clip(25, 65)         # Cloud clear

    # Planning risk score (0-100, higher = more likely approved)
    X[:, 17] = rng.beta(5, 2, n).clip(0.1, 0.99) * 100

    # Financial IRR (%)
    X[:, 18] = rng.normal(9, 3, n).clip(1, 25)

    # Compute composite quality score for relevance labels
    scores = np.full(n, 50.0)
    scores += ((X[:, 0] - 950) / 200) * 15       # Solar resource
    scores -= np.where(X[:, 2] > 10, 10, X[:, 2] * 0.3)  # Slope
    scores += ((X[:, 4] - 30) / 60) * 8           # South facing
    scores += ((X[:, 6] - 40) / 60) * 10          # Developable
    scores -= X[:, 7] * 0.15                       # Built penalty
    scores -= np.where(X[:, 10] > 10, 12, X[:, 10] * 0.6)  # Grid distance
    scores += np.where(X[:, 11] > 10, 8, X[:, 11] * 0.4)   # Grid headroom
    scores -= X[:, 12] * 0.12                      # Flood risk
    scores += ((X[:, 16] - 35) / 25) * 5          # Cloud clear
    scores += (X[:, 17] - 50) * 0.2               # Planning risk
    scores += (X[:, 18] - 6) * 1.5                # IRR
    scores += rng.normal(0, 2, n)
    scores = scores.clip(0, 100)

    # Convert to relevance labels 0-4 (5-point scale)
    y = np.digitize(scores, bins=[25, 40, 55, 70]) .astype(np.float64)

    group_sizes = np.full(n_groups, group_size)

    return X, y, group_sizes


def train_and_save_ranker(n_groups: int = 80, group_size: int = 8, seed: int = 42) -> dict:
    """Train XGBoost LambdaRank model for site ranking."""
    from sklearn.model_selection import GroupShuffleSplit
    from xgboost import XGBRanker

    X, y, group_sizes = _generate_ranker_data(n_groups, group_size, seed)

    # Create group IDs for splitting
    group_ids = np.repeat(np.arange(n_groups), group_size)

    # Train/test split by group
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    train_idx, test_idx = next(splitter.split(X, y, groups=group_ids))

    X_train, X_test = X[train_idx], X[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]

    # Recompute group sizes for train/test
    train_groups = group_ids[train_idx]
    test_groups = group_ids[test_idx]
    _, train_group_sizes = np.unique(train_groups, return_counts=True)
    _, test_group_sizes = np.unique(test_groups, return_counts=True)

    ranker = XGBRanker(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=seed,
        objective="rank:ndcg",
        lambdarank_num_pair_per_sample=8,
    )
    ranker.fit(
        X_train, y_train,
        qid=train_groups,
    )

    # Evaluate: compute NDCG@5 on test groups
    test_scores = ranker.predict(X_test)
    ndcg_scores = []
    offset = 0
    for gs in test_group_sizes:
        group_y = y_test[offset:offset + gs]
        group_s = test_scores[offset:offset + gs]
        # NDCG calculation
        ndcg = _compute_ndcg(group_y, group_s, k=min(5, gs))
        ndcg_scores.append(ndcg)
        offset += gs
    mean_ndcg = float(np.mean(ndcg_scores))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RANKER_PATH, "wb") as f:
        pickle.dump(ranker, f)

    meta = {
        "model": "site_ranker_lambdarank",
        "n_groups": n_groups,
        "group_size": group_size,
        "total_samples": int(n_groups * group_size),
        "seed": seed,
        "features": RANKER_FEATURES,
        "ndcg_at_5": round(mean_ndcg, 4),
    }
    with open(RANKER_META_PATH, "w") as f:
        json.dump(meta, f, indent=2, default=str)

    global _ranker_cache
    _ranker_cache = None

    log.info("Trained site ranker: NDCG@5=%.3f", mean_ndcg)
    return meta


def _compute_ndcg(y_true: np.ndarray, y_pred: np.ndarray, k: int = 5) -> float:
    """Compute NDCG@k."""
    order = np.argsort(-y_pred)[:k]
    dcg = np.sum((2 ** y_true[order] - 1) / np.log2(np.arange(2, k + 2)))

    ideal_order = np.argsort(-y_true)[:k]
    idcg = np.sum((2 ** y_true[ideal_order] - 1) / np.log2(np.arange(2, k + 2)))

    return float(dcg / idcg) if idcg > 0 else 0.0


def rank_sites(sites: list[dict]) -> list[dict]:
    """Rank multiple candidate sites by predicted quality.

    Parameters
    ----------
    sites : list[dict]
        Each dict has keys from RANKER_FEATURES (missing get defaults).
        Optionally include 'name' or 'id' for identification.

    Returns
    -------
    list[dict] sorted by rank_score descending, with rank, rank_score,
    and shap top factors for each site.
    """
    if not sites:
        return []

    ranker = _load_ranker()
    if ranker is None:
        log.info("Ranker model not found, training on first use...")
        train_and_save_ranker()
        ranker = _load_ranker()
        if ranker is None:
            return [{"error": "Ranker model training failed."}]

    n = len(sites)
    X = np.zeros((n, 19), dtype=np.float64)
    for i, site in enumerate(sites):
        for j, feat in enumerate(RANKER_FEATURES):
            X[i, j] = float(site.get(feat, RANKER_DEFAULTS[feat]))

    # Predict ranking scores
    raw_scores = ranker.predict(X)

    # Normalise to 0-100
    if raw_scores.max() != raw_scores.min():
        norm_scores = (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min()) * 100
    else:
        norm_scores = np.full(n, 50.0)

    # SHAP for top factors per site
    site_shaps = []
    try:
        import shap
        explainer = shap.TreeExplainer(ranker)
        sv = explainer.shap_values(X)
        for i in range(n):
            shap_arr = sv[i]
            indexed = sorted(enumerate(shap_arr), key=lambda x: abs(x[1]), reverse=True)
            top = []
            for idx, val in indexed[:3]:
                top.append({
                    "feature": RANKER_FEATURES[idx],
                    "value": round(float(X[i, idx]), 3),
                    "shap_impact": round(float(val), 3),
                    "direction": "positive" if val > 0 else "negative",
                })
            site_shaps.append(top)
    except Exception as e:
        log.warning("SHAP failed for ranker: %s", e)
        site_shaps = [[] for _ in range(n)]

    # Build results sorted by score
    order = np.argsort(-norm_scores)
    results = []
    for rank_pos, idx in enumerate(order, 1):
        site_out = dict(sites[idx])  # Preserve original fields
        site_out["rank"] = rank_pos
        site_out["rank_score"] = round(float(norm_scores[idx]), 1)
        site_out["raw_score"] = round(float(raw_scores[idx]), 4)
        site_out["top_factors"] = site_shaps[idx]
        results.append(site_out)

    return results


# ============================================================================
# Auto-train on import if models don't exist
# ============================================================================

def _ensure_models():
    """Train any missing models. Called lazily on first prediction."""
    if not PLANNING_CLF_PATH.exists():
        log.info("Auto-training planning risk predictor...")
        train_and_save_planning()
    if not IRR_REG_PATH.exists():
        log.info("Auto-training financial IRR predictor...")
        train_and_save_irr()
    if not RANKER_PATH.exists():
        log.info("Auto-training site ranker...")
        train_and_save_ranker()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Training advanced ML models for Princeps...\n")

    print("1. Planning Risk Predictor")
    meta = train_and_save_planning(n_samples=800)
    print(f"   Accuracy: {meta['accuracy']:.1%}")
    print(f"   Distribution: {meta['class_distribution']}\n")

    print("2. Financial IRR Predictor")
    meta = train_and_save_irr(n_samples=600)
    print(f"   MAE: {meta['mae']:.3f}%, R2: {meta['r2']:.3f}")
    print(f"   IRR range: {meta['irr_range']['min']:.1f}% - {meta['irr_range']['max']:.1f}%\n")

    print("3. Site Ranker (LambdaRank)")
    meta = train_and_save_ranker()
    print(f"   NDCG@5: {meta['ndcg_at_5']:.3f}\n")

    # Demo predictions
    print("--- Demo: Planning Risk ---")
    result = predict_planning_risk({
        "distance_to_residential_km": 2.0,
        "aonb_proximity_km": 20.0,
        "green_belt": 0,
        "flood_zone": 1,
        "agricultural_grade": 3,
        "local_authority_approval_rate": 0.8,
        "capacity_mw": 30,
    })
    print(f"   Outcome: {result['outcome']} (confidence: {result['confidence']}%)")

    print("\n--- Demo: Financial IRR ---")
    result = predict_financial_irr({
        "capacity_mw": 50,
        "annual_yield_mwh": 47500,
        "ppa_price_gbp_mwh": 55,
        "capex_per_kw": 500,
        "opex_per_kw_yr": 10,
    })
    print(f"   IRR: {result['irr_pct']:.1f}% ({result['viability']})")

    print("\n--- Demo: Site Ranking ---")
    demo_sites = [
        {"name": "Site A", "ghi_kwh_m2_yr": 1080, "grid_distance_km": 2, "developable_pct": 85},
        {"name": "Site B", "ghi_kwh_m2_yr": 950, "grid_distance_km": 12, "developable_pct": 60},
        {"name": "Site C", "ghi_kwh_m2_yr": 1020, "grid_distance_km": 5, "developable_pct": 70},
    ]
    ranked = rank_sites(demo_sites)
    for s in ranked:
        print(f"   #{s['rank']}: {s.get('name', '?')} — score {s['rank_score']}")

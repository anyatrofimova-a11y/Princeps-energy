"""
XGBoost Site Viability Classifier for Princeps.

Three-class classifier (GO / CAUTION / NO-GO) plus continuous 0-100 regressor,
with SHAP explanations and an ensemble meta-scorer that blends rule-based,
ML-based, and agent-confidence signals.

Trained on synthetic UK site data; retrain on real outcomes via train_and_save().
"""

from __future__ import annotations

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("princeps.ml_site_classifier")

DATA_DIR = Path(os.environ.get("PRINCEPS_DATA_DIR", "data"))
CLASSIFIER_PATH = DATA_DIR / "site_classifier_xgb.pkl"
REGRESSOR_PATH = DATA_DIR / "site_regressor_xgb.pkl"
META_PATH = DATA_DIR / "site_model_meta.json"

# 17 features — must match learned_scorer.FEATURE_NAMES
FEATURE_NAMES = [
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
]

LABEL_MAP = {0: "NO-GO", 1: "CAUTION", 2: "GO"}
LABEL_INV = {v: k for k, v in LABEL_MAP.items()}


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------

def _generate_synthetic_data(n: int = 1000, seed: int = 42) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Generate n synthetic UK solar sites with realistic feature distributions.

    Returns (X, y_class, y_score) where y_class in {0,1,2} and y_score in [0,100].
    """
    rng = np.random.default_rng(seed)

    X = np.zeros((n, 17), dtype=np.float64)

    # 0: GHI — UK range 900-1100, mean ~1000, slightly right-skewed in south
    X[:, 0] = rng.normal(1000, 50, n).clip(850, 1150)

    # 1: Wind speed — 4-9 m/s, higher in Scotland/coast
    X[:, 1] = rng.normal(6.0, 1.2, n).clip(3, 12)

    # 2: Slope mean — mostly 0-5, tail to 15
    X[:, 2] = rng.exponential(3.0, n).clip(0, 25)

    # 3: Slope p90 — slightly higher than mean
    X[:, 3] = X[:, 2] * rng.uniform(1.2, 2.0, n)
    X[:, 3] = X[:, 3].clip(0, 35)

    # 4: South-facing % — 20-80, uniform-ish
    X[:, 4] = rng.normal(45, 15, n).clip(10, 90)

    # 5: Elevation — 10-400m, most lowland
    X[:, 5] = rng.exponential(80, n).clip(5, 600)

    # 6: Developable % — 20-95, bimodal (greenfield vs constrained)
    X[:, 6] = rng.beta(3, 1.5, n) * 80 + 15
    X[:, 6] = X[:, 6].clip(5, 98)

    # 7: Built % — mostly low for solar sites
    X[:, 7] = rng.exponential(8, n).clip(0, 60)

    # 8: Trees % — 0-40
    X[:, 8] = rng.exponential(10, n).clip(0, 60)

    # 9: Water % — mostly 0-5
    X[:, 9] = rng.exponential(2, n).clip(0, 30)

    # 10: Grid distance km — 0.5-20, log-normal
    X[:, 10] = rng.lognormal(1.2, 0.7, n).clip(0.3, 30)

    # 11: Grid headroom MW — 0-100, many constrained
    X[:, 11] = rng.exponential(15, n).clip(0, 120)

    # 12: Flood risk score 0-100, mostly low
    X[:, 12] = rng.exponential(12, n).clip(0, 100)

    # 13: NDVI mean — 0.2-0.8
    X[:, 13] = rng.normal(0.45, 0.12, n).clip(0.1, 0.9)

    # 14: NDVI trend slope — small, centered 0
    X[:, 14] = rng.normal(0, 0.01, n).clip(-0.05, 0.05)

    # 15: SAR VV mean dB — typically -15 to -5
    X[:, 15] = rng.normal(-12, 2.5, n).clip(-20, -3)

    # 16: Cloud clear % — UK 35-55
    X[:, 16] = rng.normal(42, 6, n).clip(25, 65)

    # --- Compute labels from domain rules ---
    y_score = _compute_scores(X)
    y_class = np.where(y_score >= 65, 2, np.where(y_score >= 40, 1, 0))

    return X, y_class, y_score


def _compute_scores(X: np.ndarray) -> np.ndarray:
    """Deterministic rule-based scoring for label generation."""
    n = X.shape[0]
    scores = np.full(n, 50.0)

    # Solar resource: higher GHI -> better
    scores += ((X[:, 0] - 950) / 200) * 18

    # Wind (minor bonus for hybrid potential)
    scores += ((X[:, 1] - 5) / 5) * 3

    # Slope penalty (steep = bad for solar)
    scores -= np.where(X[:, 2] > 15, 18,
              np.where(X[:, 2] > 10, 10,
              np.where(X[:, 2] > 5, 4, 0)))

    # South-facing bonus
    scores += ((X[:, 4] - 30) / 60) * 8

    # Elevation penalty above 300m
    scores -= np.where(X[:, 5] > 300, 6,
              np.where(X[:, 5] > 200, 2, 0))

    # Developable land
    scores += ((X[:, 6] - 40) / 60) * 12

    # Built area penalty
    scores -= np.where(X[:, 7] > 30, 8,
              np.where(X[:, 7] > 15, 3, 0))

    # Trees penalty
    scores -= np.where(X[:, 8] > 25, 5,
              np.where(X[:, 8] > 15, 2, 0))

    # Water penalty
    scores -= np.where(X[:, 9] > 10, 4, X[:, 9] * 0.2)

    # Grid distance (critical)
    scores -= np.where(X[:, 10] > 15, 14,
              np.where(X[:, 10] > 10, 9,
              np.where(X[:, 10] > 5, 4, 0)))

    # Grid headroom
    scores += np.where(X[:, 11] > 30, 8,
              np.where(X[:, 11] > 10, 5,
              np.where(X[:, 11] > 3, 2,
              np.where(X[:, 11] < 1, -10, -3))))

    # Flood risk
    scores -= X[:, 12] * 0.15

    # NDVI (moderate vegetation = farmland = good)
    scores += np.where((X[:, 13] > 0.3) & (X[:, 13] < 0.6), 3, -1)

    # Cloud-free bonus
    scores += ((X[:, 16] - 35) / 25) * 5

    # Add small noise to prevent exact rule replication
    rng = np.random.default_rng(99)
    scores += rng.normal(0, 2, n)

    return scores.clip(0, 100).round(1)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_and_save(n_samples: int = 1000, seed: int = 42) -> dict:
    """
    Train XGBoost classifier + regressor on synthetic data and save to DATA_DIR.

    Returns training metrics.
    """
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import (
        accuracy_score, classification_report,
        mean_absolute_error, r2_score,
    )
    from xgboost import XGBClassifier, XGBRegressor

    X, y_class, y_score = _generate_synthetic_data(n_samples, seed)
    X_train, X_test, yc_train, yc_test, ys_train, ys_test = train_test_split(
        X, y_class, y_score, test_size=0.2, random_state=seed, stratify=y_class,
    )

    # --- Classifier (GO / CAUTION / NO-GO) ---
    clf = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=seed,
        eval_metric="mlogloss",
    )
    clf.fit(X_train, yc_train)
    yc_pred = clf.predict(X_test)
    clf_acc = accuracy_score(yc_test, yc_pred)
    clf_report = classification_report(
        yc_test, yc_pred, target_names=["NO-GO", "CAUTION", "GO"], output_dict=True,
    )

    # --- Regressor (0-100 score) ---
    reg = XGBRegressor(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=seed,
    )
    reg.fit(X_train, ys_train)
    ys_pred = reg.predict(X_test)
    reg_mae = mean_absolute_error(ys_test, ys_pred)
    reg_r2 = r2_score(ys_test, ys_pred)

    # --- Save models ---
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CLASSIFIER_PATH, "wb") as f:
        pickle.dump(clf, f)
    with open(REGRESSOR_PATH, "wb") as f:
        pickle.dump(reg, f)

    meta = {
        "n_samples": n_samples,
        "seed": seed,
        "features": FEATURE_NAMES,
        "classifier_accuracy": round(clf_acc, 4),
        "classifier_report": clf_report,
        "regressor_mae": round(reg_mae, 2),
        "regressor_r2": round(reg_r2, 4),
        "class_distribution": {
            LABEL_MAP[k]: int(v) for k, v in zip(*np.unique(y_class, return_counts=True))
        },
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2, default=str)

    log.info(
        "Trained site classifier: acc=%.3f | regressor: MAE=%.2f R2=%.3f",
        clf_acc, reg_mae, reg_r2,
    )
    return meta


# ---------------------------------------------------------------------------
# Model loading (cached singletons)
# ---------------------------------------------------------------------------

_clf_cache: Any = None
_reg_cache: Any = None


def _load_classifier():
    global _clf_cache
    if _clf_cache is None and CLASSIFIER_PATH.exists():
        with open(CLASSIFIER_PATH, "rb") as f:
            _clf_cache = pickle.load(f)
    return _clf_cache


def _load_regressor():
    global _reg_cache
    if _reg_cache is None and REGRESSOR_PATH.exists():
        with open(REGRESSOR_PATH, "rb") as f:
            _reg_cache = pickle.load(f)
    return _reg_cache


def _invalidate_cache():
    global _clf_cache, _reg_cache
    _clf_cache = None
    _reg_cache = None


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------

def predict_site(features: dict[str, float]) -> dict:
    """
    Predict site viability from 17 features.

    Parameters
    ----------
    features : dict
        Keys matching FEATURE_NAMES, values as floats.
        Missing features get UK-average defaults.

    Returns
    -------
    dict with keys: verdict, score, confidence, shap_values, top_factors
    """
    # Build feature vector with defaults
    defaults = {
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
    }

    vec = np.array([[features.get(f, defaults[f]) for f in FEATURE_NAMES]], dtype=np.float64)

    clf = _load_classifier()
    reg = _load_regressor()

    if clf is None or reg is None:
        return {
            "error": "Models not trained. Call train_and_save() first.",
            "verdict": "CAUTION",
            "score": 50.0,
            "confidence": 0.0,
            "shap_values": {},
            "top_factors": [],
        }

    # Classification
    class_pred = int(clf.predict(vec)[0])
    class_proba = clf.predict_proba(vec)[0]
    verdict = LABEL_MAP[class_pred]
    confidence = float(round(class_proba[class_pred] * 100, 1))

    # Regression
    score = float(reg.predict(vec)[0])
    score = round(max(0, min(100, score)), 1)

    # SHAP explanations
    shap_dict = {}
    top_factors = []
    try:
        import shap
        explainer = shap.TreeExplainer(reg)
        sv = explainer.shap_values(vec)
        shap_arr = sv[0]
        shap_dict = {FEATURE_NAMES[i]: round(float(shap_arr[i]), 3) for i in range(17)}

        # Top 5 factors by |SHAP|
        indexed = sorted(enumerate(shap_arr), key=lambda x: abs(x[1]), reverse=True)
        for idx, val in indexed[:5]:
            top_factors.append({
                "feature": FEATURE_NAMES[idx],
                "value": round(float(vec[0, idx]), 3),
                "shap_impact": round(float(val), 3),
                "direction": "positive" if val > 0 else "negative",
                "explanation": _explain_feature(FEATURE_NAMES[idx], float(vec[0, idx]), float(val)),
            })
    except Exception as e:
        log.warning("SHAP explanation failed: %s", e)
        top_factors = [{"note": f"SHAP unavailable: {e}"}]

    return {
        "verdict": verdict,
        "score": score,
        "confidence": confidence,
        "class_probabilities": {
            LABEL_MAP[i]: round(float(class_proba[i]) * 100, 1) for i in range(3)
        },
        "shap_values": shap_dict,
        "top_factors": top_factors,
    }


def _explain_feature(name: str, value: float, shap_val: float) -> str:
    """Generate a human-readable explanation for a SHAP-important feature."""
    direction = "helps" if shap_val > 0 else "hurts"
    explanations = {
        "ghi_kwh_m2_yr": f"Solar resource of {value:.0f} kWh/m2/yr {direction} viability",
        "wind_speed_ms": f"Wind speed of {value:.1f} m/s {direction} hybrid potential",
        "slope_mean_deg": f"Mean slope of {value:.1f} deg {direction} buildability",
        "slope_p90_deg": f"P90 slope of {value:.1f} deg {direction} site grading cost",
        "south_facing_pct": f"{value:.0f}% south-facing terrain {direction} solar yield",
        "elevation_m": f"Elevation of {value:.0f}m {direction} accessibility",
        "developable_pct": f"{value:.0f}% developable land {direction} layout efficiency",
        "built_pct": f"{value:.0f}% built-up area {direction} planning risk",
        "trees_pct": f"{value:.0f}% tree cover {direction} clearing cost",
        "water_pct": f"{value:.0f}% water coverage {direction} usable area",
        "grid_distance_km": f"Grid distance of {value:.1f} km {direction} connection cost",
        "grid_headroom_mw": f"Grid headroom of {value:.1f} MW {direction} capacity margin",
        "flood_risk_score": f"Flood risk score of {value:.0f} {direction} insurance/planning",
        "ndvi_mean": f"NDVI of {value:.2f} {direction} land condition assessment",
        "ndvi_trend_slope": f"NDVI trend of {value:.4f} {direction} land stability",
        "sar_vv_mean_db": f"SAR backscatter of {value:.1f} dB {direction} surface assessment",
        "cloud_clear_pct": f"Cloud-free fraction of {value:.0f}% {direction} solar yield",
    }
    return explanations.get(name, f"{name}={value:.2f} {direction} score")


# ---------------------------------------------------------------------------
# Ensemble meta-scorer
# ---------------------------------------------------------------------------

def ensemble_score(
    rule_score: float,
    ml_result: dict | None = None,
    agent_confidence: float | None = None,
    weights: dict[str, float] | None = None,
) -> dict:
    """
    Combine rule-based score, ML score, and agent confidence into a final verdict.

    Parameters
    ----------
    rule_score : float
        Rule-based score from learned_scorer._bootstrap_score (0-100).
    ml_result : dict | None
        Output from predict_site(). If None, ML weight redistributed to rule.
    agent_confidence : float | None
        Agent confidence 0-100 from structured analysis. If None, ignored.
    weights : dict | None
        Override default weights {"rule": 0.3, "ml": 0.5, "agent": 0.2}.

    Returns
    -------
    dict with final_score, final_verdict, component_scores, weights_used
    """
    w = weights or {"rule": 0.30, "ml": 0.50, "agent": 0.20}

    ml_score = ml_result["score"] if ml_result and "score" in ml_result else None
    ml_verdict = ml_result.get("verdict") if ml_result else None

    # Redistribute weights if components missing
    active_w = {}
    if rule_score is not None:
        active_w["rule"] = w["rule"]
    if ml_score is not None:
        active_w["ml"] = w["ml"]
    if agent_confidence is not None:
        active_w["agent"] = w["agent"]

    if not active_w:
        return {
            "final_score": 50.0,
            "final_verdict": "CAUTION",
            "component_scores": {},
            "weights_used": {},
        }

    # Normalise weights
    total_w = sum(active_w.values())
    norm_w = {k: v / total_w for k, v in active_w.items()}

    # Compute weighted score
    final = 0.0
    components = {}
    if "rule" in norm_w:
        final += norm_w["rule"] * rule_score
        components["rule"] = round(rule_score, 1)
    if "ml" in norm_w:
        final += norm_w["ml"] * ml_score
        components["ml"] = round(ml_score, 1)
    if "agent" in norm_w:
        final += norm_w["agent"] * agent_confidence
        components["agent"] = round(agent_confidence, 1)

    final = round(max(0, min(100, final)), 1)

    # Verdict from final score
    if final >= 65:
        verdict = "GO"
    elif final >= 40:
        verdict = "CAUTION"
    else:
        verdict = "NO-GO"

    # Agreement check — flag if ML and rule disagree
    disagreement = None
    if ml_verdict:
        rule_verdict = "GO" if rule_score >= 65 else ("CAUTION" if rule_score >= 40 else "NO-GO")
        if rule_verdict != ml_verdict:
            disagreement = {
                "rule_says": rule_verdict,
                "ml_says": ml_verdict,
                "note": "Rule-based and ML models disagree — review top SHAP factors.",
            }

    return {
        "final_score": final,
        "final_verdict": verdict,
        "component_scores": components,
        "weights_used": {k: round(v, 3) for k, v in norm_w.items()},
        "disagreement": disagreement,
        "ml_shap_top": (ml_result or {}).get("top_factors", [])[:3],
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    print("Training XGBoost site viability models...")
    meta = train_and_save(n_samples=1000)
    print(f"Classifier accuracy: {meta['classifier_accuracy']:.1%}")
    print(f"Regressor MAE: {meta['regressor_mae']:.2f}, R2: {meta['regressor_r2']:.3f}")
    print(f"Class distribution: {meta['class_distribution']}")
    print(f"Models saved to {DATA_DIR}/")

    # Quick demo prediction
    demo = predict_site({
        "ghi_kwh_m2_yr": 1050,
        "slope_mean_deg": 3,
        "grid_distance_km": 2.5,
        "grid_headroom_mw": 25,
        "flood_risk_score": 5,
        "developable_pct": 80,
    })
    print(f"\nDemo prediction: {demo['verdict']} (score={demo['score']}, confidence={demo['confidence']}%)")
    for f in demo.get("top_factors", [])[:3]:
        if "feature" in f:
            print(f"  {f['feature']}: SHAP={f['shap_impact']:+.2f} — {f['explanation']}")

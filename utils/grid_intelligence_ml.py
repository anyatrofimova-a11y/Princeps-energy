"""
NESO Grid Intelligence ML Agent.

Trained on structured NESO NETS Status Report data (real + synthetic augmentation).
Provides four prediction capabilities:

1. **Balancing Cost Predictor** — Forecasts 24h BM spend (£k) from demand, wind,
   solar, margin, and interconnector conditions.
2. **System Risk Classifier** — Predicts risk level (LOW/MEDIUM/HIGH/CRITICAL)
   from current grid state.
3. **Embedded Generation Forecaster** — Predicts solar peak and wind average
   from temporal and weather features.
4. **Market Price Range Estimator** — Forecasts cash-out price range from
   supply-demand balance indicators.

Models: scikit-learn GradientBoosting (regression + classification).
Training: ~365 daily observations, NESO-derived seasonal patterns.
"""

import json
import logging
import math
import os
from datetime import date, datetime

import numpy as np

log = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
BM_MODEL_PATH = os.path.join(MODEL_DIR, "neso_bm_cost_model.joblib")
RISK_MODEL_PATH = os.path.join(MODEL_DIR, "neso_risk_model.joblib")
SOLAR_MODEL_PATH = os.path.join(MODEL_DIR, "neso_solar_model.joblib")
WIND_MODEL_PATH = os.path.join(MODEL_DIR, "neso_wind_model.joblib")
PRICE_MODEL_PATH = os.path.join(MODEL_DIR, "neso_price_model.joblib")

# Feature columns for each model
BM_FEATURES = [
    "day_of_year", "day_of_week", "is_weekend", "month",
    "peak_demand_mw", "min_demand_mw", "demand_range_mw",
    "min_derated_margin_mw", "risk_score", "amber_count",
    "embedded_solar_peak_mw", "embedded_wind_avg_mw",
    "ic_availability_frac", "weather_severity", "flood_warnings_total",
]

RISK_FEATURES = [
    "day_of_year", "month", "is_weekend",
    "peak_demand_mw", "min_derated_margin_mw",
    "embedded_wind_avg_mw", "embedded_solar_peak_mw",
    "ic_availability_frac", "weather_severity",
    "flood_warnings_total", "demand_range_mw",
]

GEN_FEATURES = [
    "day_of_year", "month", "is_weekend", "weather_severity",
    "day_of_year_sin", "day_of_year_cos",
]

PRICE_FEATURES = [
    "day_of_year", "month", "is_weekend",
    "peak_demand_mw", "min_derated_margin_mw",
    "embedded_wind_avg_mw", "embedded_solar_peak_mw",
    "ic_availability_frac", "weather_severity",
    "bm_spend_24h_k",
    "day_of_year_sin", "day_of_year_cos",
]

# Risk level thresholds (on composite risk score from features)
RISK_LABELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# Cached models (lazy-loaded)
_models = {}


def _classify_risk(row: dict) -> int:
    """Classify grid risk level from feature vector (for training labels)."""
    margin = row.get("min_derated_margin_mw", 20000)
    risk_score = row.get("risk_score", 0)
    weather = row.get("weather_severity", 0)
    demand = row.get("peak_demand_mw", 30000)

    score = 0
    if margin < 8000:
        score += 3
    elif margin < 12000:
        score += 2
    elif margin < 16000:
        score += 1

    score += risk_score  # 0-10 range in practice

    if weather >= 2:
        score += 2
    elif weather >= 1:
        score += 1

    if demand > 42000:
        score += 2
    elif demand > 38000:
        score += 1

    # Map to 4 levels
    if score >= 8:
        return 3  # CRITICAL
    elif score >= 5:
        return 2  # HIGH
    elif score >= 2:
        return 1  # MEDIUM
    return 0  # LOW


def train_all_models():
    """Train all grid intelligence models from NESO data."""
    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
    from sklearn.model_selection import cross_val_score
    import joblib

    from utils.neso_report_parser import generate_training_dataset

    log.info("Generating training dataset...")
    dataset = generate_training_dataset()
    log.info(f"Training on {len(dataset)} samples")

    # Convert to numpy
    all_keys = list(dataset[0].keys())

    def extract(rows, feature_names):
        X = np.array([[r[f] for f in feature_names] for r in rows], dtype=np.float32)
        return X

    # ── 1. BM Cost Predictor ──
    log.info("Training BM cost predictor...")
    X_bm = extract(dataset, BM_FEATURES)
    y_bm = np.array([r["bm_spend_24h_k"] for r in dataset], dtype=np.float32)

    bm_model = GradientBoostingRegressor(
        n_estimators=200, max_depth=5, learning_rate=0.08,
        subsample=0.8, min_samples_leaf=5, random_state=42,
    )
    bm_model.fit(X_bm, y_bm)
    cv_bm = cross_val_score(bm_model, X_bm, y_bm, cv=5, scoring="r2")
    log.info(f"  BM cost R²: {cv_bm.mean():.3f} ± {cv_bm.std():.3f}")

    # Feature importance
    bm_importance = dict(zip(BM_FEATURES, bm_model.feature_importances_))
    log.info(f"  Top features: {sorted(bm_importance.items(), key=lambda x: -x[1])[:5]}")

    # ── 2. Risk Classifier ──
    log.info("Training risk classifier...")
    X_risk = extract(dataset, RISK_FEATURES)
    y_risk = np.array([_classify_risk(r) for r in dataset], dtype=np.int32)

    risk_model = GradientBoostingClassifier(
        n_estimators=150, max_depth=4, learning_rate=0.1,
        subsample=0.8, min_samples_leaf=3, random_state=42,
    )
    risk_model.fit(X_risk, y_risk)
    cv_risk = cross_val_score(risk_model, X_risk, y_risk, cv=5, scoring="accuracy")
    log.info(f"  Risk accuracy: {cv_risk.mean():.3f} ± {cv_risk.std():.3f}")

    # ── 3. Embedded Solar Peak Predictor ──
    log.info("Training solar peak predictor...")
    X_gen = extract(dataset, GEN_FEATURES)
    y_solar = np.array([r["embedded_solar_peak_mw"] for r in dataset], dtype=np.float32)

    solar_model = GradientBoostingRegressor(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        subsample=0.85, min_samples_leaf=3, random_state=42,
    )
    solar_model.fit(X_gen, y_solar)
    cv_solar = cross_val_score(solar_model, X_gen, y_solar, cv=5, scoring="r2")
    log.info(f"  Solar R²: {cv_solar.mean():.3f} ± {cv_solar.std():.3f}")

    # ── 4. Embedded Wind Avg Predictor ──
    log.info("Training wind avg predictor...")
    y_wind = np.array([r["embedded_wind_avg_mw"] for r in dataset], dtype=np.float32)

    wind_model = GradientBoostingRegressor(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        subsample=0.85, min_samples_leaf=3, random_state=42,
    )
    wind_model.fit(X_gen, y_wind)
    cv_wind = cross_val_score(wind_model, X_gen, y_wind, cv=5, scoring="r2")
    log.info(f"  Wind R²: {cv_wind.mean():.3f} ± {cv_wind.std():.3f}")

    # ── 5. Cash-Out Max Price Predictor ──
    log.info("Training price predictor...")
    X_price = extract(dataset, PRICE_FEATURES)
    y_price = np.array([r["cash_out_max_mwh"] for r in dataset], dtype=np.float32)

    price_model = GradientBoostingRegressor(
        n_estimators=150, max_depth=4, learning_rate=0.1,
        subsample=0.8, random_state=42,
    )
    price_model.fit(X_price, y_price)
    cv_price = cross_val_score(price_model, X_price, y_price, cv=5, scoring="r2")
    log.info(f"  Price R²: {cv_price.mean():.3f} ± {cv_price.std():.3f}")

    # ── Save all models ──
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(bm_model, BM_MODEL_PATH)
    joblib.dump(risk_model, RISK_MODEL_PATH)
    joblib.dump(solar_model, SOLAR_MODEL_PATH)
    joblib.dump(wind_model, WIND_MODEL_PATH)
    joblib.dump(price_model, PRICE_MODEL_PATH)

    metrics = {
        "bm_cost_r2": round(cv_bm.mean(), 4),
        "risk_accuracy": round(cv_risk.mean(), 4),
        "solar_r2": round(cv_solar.mean(), 4),
        "wind_r2": round(cv_wind.mean(), 4),
        "price_r2": round(cv_price.mean(), 4),
        "training_samples": len(dataset),
        "bm_feature_importance": {k: round(v, 4) for k, v in bm_importance.items()},
    }

    metrics_path = os.path.join(MODEL_DIR, "neso_model_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)

    log.info(f"All models saved to {MODEL_DIR}")
    return metrics


def _load_models():
    """Lazy-load trained models."""
    if _models:
        return

    try:
        import joblib
        if os.path.exists(BM_MODEL_PATH):
            _models["bm"] = joblib.load(BM_MODEL_PATH)
        if os.path.exists(RISK_MODEL_PATH):
            _models["risk"] = joblib.load(RISK_MODEL_PATH)
        if os.path.exists(SOLAR_MODEL_PATH):
            _models["solar"] = joblib.load(SOLAR_MODEL_PATH)
        if os.path.exists(WIND_MODEL_PATH):
            _models["wind"] = joblib.load(WIND_MODEL_PATH)
        if os.path.exists(PRICE_MODEL_PATH):
            _models["price"] = joblib.load(PRICE_MODEL_PATH)
        log.info(f"Loaded {len(_models)} NESO ML models")
    except Exception as e:
        log.warning(f"Could not load NESO models: {e}")


def predict_grid_intelligence(
    target_date: date | None = None,
    peak_demand_mw: float | None = None,
    min_demand_mw: float | None = None,
    wind_avg_mw: float | None = None,
    solar_peak_mw: float | None = None,
    margin_mw: float | None = None,
    weather_severity: int = 0,
    ic_availability: float = 1.0,
) -> dict:
    """
    Run all NESO grid intelligence predictions.

    Parameters can be overridden; defaults come from the latest NESO snapshot
    and temporal/seasonal models.

    Returns a dict with predictions, confidence, and advisory text.
    """
    _load_models()

    from utils.neso_report_parser import get_latest_neso_snapshot

    snapshot = get_latest_neso_snapshot()
    features = snapshot["features"]

    # Use target date or today
    if target_date is None:
        target_date = date.today()

    day_of_year = target_date.timetuple().tm_yday
    month = target_date.month
    dow = target_date.weekday()
    is_weekend = int(dow >= 5)

    # Override features with provided values or use snapshot defaults
    f = {
        "day_of_year": day_of_year,
        "day_of_week": dow,
        "is_weekend": is_weekend,
        "month": month,
        "peak_demand_mw": peak_demand_mw or features["peak_demand_mw"],
        "min_demand_mw": min_demand_mw or features["min_demand_mw"],
        "demand_range_mw": (peak_demand_mw or features["peak_demand_mw"]) - (min_demand_mw or features["min_demand_mw"]),
        "min_derated_margin_mw": margin_mw or features["min_derated_margin_mw"],
        "risk_score": features["risk_score"],
        "risk_max_level": features["risk_max_level"],
        "amber_count": features["amber_count"],
        "embedded_solar_peak_mw": solar_peak_mw if solar_peak_mw is not None else features["embedded_solar_peak_mw"],
        "embedded_wind_avg_mw": wind_avg_mw if wind_avg_mw is not None else features["embedded_wind_avg_mw"],
        "ic_availability_frac": ic_availability,
        "weather_severity": weather_severity,
        "flood_warnings_total": features["flood_warnings_total"],
        "cash_out_max_mwh": features["cash_out_max_mwh"],
        "cash_out_min_mwh": features["cash_out_min_mwh"],
        "cash_out_spread_mwh": features["cash_out_spread_mwh"],
        "bm_spend_24h_k": features["bm_spend_24h_k"],
        # Cyclic temporal
        "day_of_year_sin": math.sin(2 * math.pi * day_of_year / 365),
        "day_of_year_cos": math.cos(2 * math.pi * day_of_year / 365),
    }

    result = {
        "target_date": target_date.isoformat(),
        "source_report_date": snapshot["report_date"],
        "input_features": {k: round(v, 2) if isinstance(v, float) else v for k, v in f.items()},
        "predictions": {},
        "advisory": [],
    }

    # ── BM Cost Prediction ──
    if "bm" in _models:
        X = np.array([[f[k] for k in BM_FEATURES]], dtype=np.float32)
        pred_bm = float(_models["bm"].predict(X)[0])
        result["predictions"]["bm_spend_24h_k"] = round(pred_bm, 0)
        result["predictions"]["bm_spend_24h_m"] = round(pred_bm / 1000, 2)

        if pred_bm > 12000:
            result["advisory"].append(
                f"High balancing costs expected (~£{pred_bm/1000:.1f}M). "
                "Consider deferring flexible loads or activating storage."
            )
        elif pred_bm < 4000:
            result["advisory"].append(
                f"Low balancing costs expected (~£{pred_bm/1000:.1f}M). "
                "Favourable conditions for grid export."
            )

    # ── Risk Classification ──
    if "risk" in _models:
        X = np.array([[f[k] for k in RISK_FEATURES]], dtype=np.float32)
        pred_class = int(_models["risk"].predict(X)[0])
        proba = _models["risk"].predict_proba(X)[0]
        risk_label = RISK_LABELS[min(pred_class, len(RISK_LABELS) - 1)]
        confidence = float(proba[pred_class])

        result["predictions"]["risk_level"] = risk_label
        result["predictions"]["risk_confidence"] = round(confidence, 3)
        result["predictions"]["risk_probabilities"] = {
            RISK_LABELS[i]: round(float(p), 3) for i, p in enumerate(proba)
        }

        if pred_class >= 2:
            result["advisory"].append(
                f"Grid risk assessed as {risk_label} (confidence {confidence:.0%}). "
                "Monitor NESO warnings and ensure backup capacity."
            )

    # ── Generation Forecast ──
    if "solar" in _models:
        X = np.array([[f[k] for k in GEN_FEATURES]], dtype=np.float32)
        pred_solar = max(0, float(_models["solar"].predict(X)[0]))
        result["predictions"]["embedded_solar_peak_mw"] = round(pred_solar, 0)

    if "wind" in _models:
        X = np.array([[f[k] for k in GEN_FEATURES]], dtype=np.float32)
        pred_wind = max(0, float(_models["wind"].predict(X)[0]))
        result["predictions"]["embedded_wind_avg_mw"] = round(pred_wind, 0)

        total_embedded = (result["predictions"].get("embedded_solar_peak_mw", 0)
                         + pred_wind)
        result["predictions"]["total_embedded_gen_mw"] = round(total_embedded, 0)

        if pred_wind > 4000:
            result["advisory"].append(
                f"High embedded wind ({pred_wind:.0f} MW) — expect curtailment risk "
                "and potential negative pricing periods."
            )

    # ── Price Prediction ──
    if "price" in _models:
        X = np.array([[f[k] for k in PRICE_FEATURES]], dtype=np.float32)
        pred_price_max = max(0, float(_models["price"].predict(X)[0]))
        result["predictions"]["cash_out_max_mwh"] = round(pred_price_max, 2)
        result["predictions"]["cash_out_min_est_mwh"] = round(pred_price_max * 0.42, 2)

        if pred_price_max > 150:
            result["advisory"].append(
                f"High cash-out prices expected (up to £{pred_price_max:.0f}/MWh). "
                "Opportunity for battery storage arbitrage."
            )

    # ── System Snapshot (from latest real NESO data) ──
    result["latest_neso"] = {
        "report_date": snapshot["report_date"],
        "risk_status": snapshot["risk_status"],
        "interconnectors": snapshot["interconnectors"],
        "bm_spend_24h_k": snapshot["bm_spend_24h_k"],
        "peak_demand_mw": snapshot["peak_demand_mw"],
        "min_demand_mw": snapshot["min_demand_mw"],
        "margin_mw": snapshot["min_derated_margin_mw"],
        "weather": snapshot["weather_summary"],
        "weather_severity": snapshot["weather_severity"],
    }

    # ── Solar Site Advisory ──
    margin = f["min_derated_margin_mw"]
    demand = f["peak_demand_mw"]
    if margin > 15000 and demand < 35000:
        result["advisory"].append(
            "Grid has ample headroom — good conditions for new solar connections."
        )
    elif margin < 8000:
        result["advisory"].append(
            "Tight system margins — new connections may face constraints. "
            "Check DNO headroom before proceeding."
        )

    if not result["advisory"]:
        result["advisory"].append("Grid conditions nominal. No specific concerns.")

    return result


def get_model_metrics() -> dict | None:
    """Return saved model performance metrics."""
    metrics_path = os.path.join(MODEL_DIR, "neso_model_metrics.json")
    if os.path.exists(metrics_path):
        with open(metrics_path) as f:
            return json.load(f)
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    import sys
    if "--train" in sys.argv:
        metrics = train_all_models()
        print(f"\nTraining complete. Metrics:\n{json.dumps(metrics, indent=2)}")
    else:
        result = predict_grid_intelligence()
        print(json.dumps(result, indent=2))

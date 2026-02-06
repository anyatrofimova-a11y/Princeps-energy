#!/usr/bin/env python3
"""
ML-based solar energy predictor — reimplemented from ColasGael/Machine-Learning-for-Solar-Energy-Prediction.

Original: LSTM RNN (Keras/Theano) with 12 weather features → hourly kWh.
This version: scikit-learn GradientBoostingRegressor (portable, no GPU needed).

Training data: 6,028 hourly samples from Urbana-Champaign solar farm.
Features: hour, day, month, year, cloud_coverage, visibility, temperature,
          dew_point, humidity, wind_speed, station_pressure, altimeter.
Target: hourly solar energy output (Wh).

Usage:
    # Train and save model
    python ml_solar_predictor.py --train

    # Predict 24h profile for a location/day
    python ml_solar_predictor.py --predict --lat 52.5 --lon -1.5 --day_of_year 172

    # Predict with custom capacity scaling
    python ml_solar_predictor.py --predict --lat 52.5 --lon -1.5 --day_of_year 172 --capacity_kw 100
"""

import argparse
import json
import math
import os
import sys

import numpy as np

DATASET_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "Machine-Learning-for-Solar-Energy-Prediction",
    "Datasets",
    "hourly",
)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ml_solar_model.joblib")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "ml_solar_scaler.joblib")

FEATURE_NAMES = [
    "hour", "day", "month", "year",
    "cloud_coverage", "visibility",
    "temperature", "dew_point",
    "humidity", "wind_speed",
    "station_pressure", "altimeter",
]


def load_training_data():
    """Load and concatenate the semicolon-delimited training CSVs."""
    dfs = []
    for fname in ["weather_train.csv", "weather_dev.csv", "weather_test.csv"]:
        fpath = os.path.join(DATASET_DIR, fname)
        if not os.path.isfile(fpath):
            print(f"Warning: {fpath} not found, skipping", file=sys.stderr)
            continue
        data = np.loadtxt(fpath, delimiter=";", dtype=np.float32)
        dfs.append(data)
    if not dfs:
        raise FileNotFoundError(f"No training data found in {DATASET_DIR}")
    return np.vstack(dfs)


def train_model():
    """Train a GradientBoostingRegressor on the included solar dataset."""
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.preprocessing import StandardScaler
    import joblib

    print("Loading training data...", file=sys.stderr)
    data = load_training_data()
    print(f"Loaded {data.shape[0]} samples, {data.shape[1]} columns", file=sys.stderr)

    X = data[:, :12]  # 12 features
    y = data[:, 12]   # solar energy output (Wh)

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    print("Training GradientBoostingRegressor...", file=sys.stderr)
    model = GradientBoostingRegressor(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.1,
        subsample=0.8,
        min_samples_split=5,
        min_samples_leaf=3,
        random_state=42,
    )
    model.fit(X_scaled, y)

    # Evaluate
    from sklearn.metrics import mean_squared_error, r2_score
    y_pred = model.predict(X_scaled)
    mse = mean_squared_error(y, y_pred)
    r2 = r2_score(y, y_pred)
    print(f"Training MSE: {mse:.2f}, R²: {r2:.4f}", file=sys.stderr)

    # Save model and scaler
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    print(f"Model saved to {MODEL_PATH}", file=sys.stderr)
    print(f"Scaler saved to {SCALER_PATH}", file=sys.stderr)

    # Feature importance
    importances = model.feature_importances_
    for name, imp in sorted(zip(FEATURE_NAMES, importances), key=lambda x: -x[1]):
        print(f"  {name}: {imp:.4f}", file=sys.stderr)

    return model, scaler


def load_model():
    """Load a previously trained model and scaler."""
    import joblib
    if not os.path.isfile(MODEL_PATH):
        raise FileNotFoundError(
            f"Model not found at {MODEL_PATH}. Run with --train first."
        )
    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)
    return model, scaler


def generate_weather_features(lat: float, lon: float, day_of_year: int) -> np.ndarray:
    """
    Generate synthetic 24-hour weather features for a given location and day.
    Returns shape (24, 12) — one row per hour.

    Uses simplified atmospheric models to estimate:
    - Cloud coverage from latitude/season
    - Temperature from seasonal + diurnal model
    - Humidity, wind, pressure from UK averages
    """
    features = np.zeros((24, 12), dtype=np.float32)

    # Seasonal factors
    day_angle = 2 * math.pi * (day_of_year - 1) / 365
    # Solar declination
    decl = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))

    for h in range(24):
        # Time features
        features[h, 0] = h                      # hour
        features[h, 1] = (day_of_year - 1) % 31 + 1  # day (approx)
        features[h, 2] = min(12, max(1, (day_of_year - 1) // 30 + 1))  # month
        features[h, 3] = 2024                    # year

        # Solar elevation for cloud/visibility estimation
        hour_angle = (h - 12) * 15
        sin_elev = (
            math.sin(math.radians(lat)) * math.sin(math.radians(decl))
            + math.cos(math.radians(lat))
            * math.cos(math.radians(decl))
            * math.cos(math.radians(hour_angle))
        )

        # Cloud coverage (0-1): UK average ~0.6, lower in summer
        seasonal_cloud = 0.55 + 0.15 * math.cos(day_angle)
        # Slightly less cloud during daytime
        diurnal_cloud = -0.1 if sin_elev > 0.1 else 0.05
        cloud = max(0, min(1, seasonal_cloud + diurnal_cloud))
        features[h, 4] = cloud

        # Visibility (miles): UK average 6-10, lower with cloud
        features[h, 5] = max(1, 10 - cloud * 5)

        # Temperature (C): seasonal 5-20C + diurnal ±3C
        seasonal_t = 10 + 7 * math.sin(day_angle - math.pi / 6)
        diurnal_t = 3 * math.sin(math.radians(15 * (h - 6)))
        temp_c = seasonal_t + diurnal_t
        # Convert to Fahrenheit (training data uses F)
        temp_f = temp_c * 9 / 5 + 32
        features[h, 6] = temp_f

        # Dew point (F): roughly temp - 5-10F
        features[h, 7] = temp_f - 7

        # Relative humidity (%)
        features[h, 8] = 65 + 20 * cloud - 10 * math.sin(math.radians(15 * (h - 6)))

        # Wind speed (mph)
        features[h, 9] = 8 + 3 * math.sin(day_angle + math.pi / 4)

        # Station pressure (inHg) — UK sea level ~29.92
        features[h, 10] = 29.2 + 0.3 * math.cos(day_angle)

        # Altimeter (inHg) — similar to station pressure
        features[h, 11] = features[h, 10] + 0.8

    return features


def predict_24h(lat: float, lon: float, day_of_year: int, capacity_kw: float = 100.0) -> dict:
    """
    Predict 24-hour solar energy profile for a given location and day.

    The model was trained on a specific solar farm's output, so we scale
    predictions relative to capacity_kw for generalization.
    """
    model, scaler = load_model()

    features = generate_weather_features(lat, lon, day_of_year)
    X_scaled = scaler.transform(features)
    predictions = model.predict(X_scaled)

    # The training data's solar farm capacity is not documented precisely,
    # but peak outputs in the data suggest ~5kW capacity.
    # Scale predictions to the requested capacity.
    reference_capacity_wh = 5000  # estimated reference farm peak (Wh)
    scale = (capacity_kw * 1000) / reference_capacity_wh

    # Zero out nighttime predictions (model was trained on daytime data only)
    decl = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    for h in range(24):
        hour_angle = (h - 12) * 15
        sin_elev = (
            math.sin(math.radians(lat)) * math.sin(math.radians(decl))
            + math.cos(math.radians(lat))
            * math.cos(math.radians(decl))
            * math.cos(math.radians(hour_angle))
        )
        if sin_elev <= 0.05:
            predictions[h] = 0

    hourly_wh = [max(0, float(p * scale)) for p in predictions]
    hourly_kwh = [round(wh / 1000, 4) for wh in hourly_wh]
    daily_total = round(sum(hourly_kwh), 2)

    # Estimate annual from daily (rough — scale by seasonal factor)
    # Summer days produce ~1.5x average, winter ~0.5x
    seasonal_factor = 0.7 + 0.3 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    avg_daily = daily_total / seasonal_factor if seasonal_factor > 0 else daily_total
    annual_estimate = round(avg_daily * 365, 2)

    return {
        "day_of_year": day_of_year,
        "hourly_kwh": hourly_kwh,
        "daily_total_kwh": daily_total,
        "annual_estimate_kwh": annual_estimate,
        "capacity_kw": capacity_kw,
        "location": {"lat": lat, "lon": lon},
        "model": "GradientBoostingRegressor",
        "note": "ML prediction based on weather features; complement with SAM physics model",
    }


def main():
    parser = argparse.ArgumentParser(description="ML solar energy predictor")
    parser.add_argument("--train", action="store_true", help="Train model on included dataset")
    parser.add_argument("--predict", action="store_true", help="Predict 24h solar profile")
    parser.add_argument("--lat", type=float, default=52.5)
    parser.add_argument("--lon", type=float, default=-1.5)
    parser.add_argument("--day_of_year", type=int, default=172)
    parser.add_argument("--capacity_kw", type=float, default=100.0)

    args = parser.parse_args()

    if args.train:
        train_model()
    elif args.predict:
        result = predict_24h(args.lat, args.lon, args.day_of_year, args.capacity_kw)
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

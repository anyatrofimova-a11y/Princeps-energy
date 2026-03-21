#!/usr/bin/env python3
"""
Carbon intensity forecaster — Princeps
Fetches UK carbon intensity history from National Grid ESO API,
then forecasts using Prophet, Darts TFT, or analytical model.

Runs as subprocess via JSON stdin/stdout bridge (same pattern as demand_forecaster.py).

Commands:
  {"command": "fetch_history", "region_id": 13, "days": 30}
  {"command": "forecast_analytical", "region_id": 13, "horizon_hours": 48}
  {"command": "forecast_prophet", "region_id": 13, "horizon_hours": 48, "history_days": 30}
  {"command": "forecast_tft", "region_id": 13, "horizon_hours": 48, "history_days": 30, "epochs": 15}
"""

import json
import sys
import math
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

warnings.filterwarnings("ignore")

# ─── UK Carbon Intensity API ──────────────────────────────────────────────────

API_BASE = "https://api.carbonintensity.org.uk"

# Regional averages (gCO2/kWh) — fallback when API fails
REGIONAL_AVERAGES = {
    1: 180, 2: 170, 3: 160, 4: 165, 5: 175,
    6: 155, 7: 145, 8: 150, 9: 140, 10: 135,
    11: 130, 12: 120, 13: 110, 14: 100, 15: 45,
    16: 50, 17: 55,
}

REGION_NAMES = {
    1: "North Scotland", 2: "South Scotland", 3: "North West England",
    4: "North East England", 5: "Yorkshire", 6: "North Wales & Merseyside",
    7: "South Wales", 8: "West Midlands", 9: "East Midlands",
    10: "East England", 11: "South West England", 12: "South England",
    13: "London", 14: "South East England", 15: "England", 16: "Scotland", 17: "Wales",
}


def fetch_history(region_id: int = 13, days: int = 30) -> dict:
    """Fetch half-hourly carbon intensity history from National Grid ESO API."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    all_records = []
    # API allows max 14-day windows
    chunk_days = 7
    cursor = start

    while cursor < end:
        chunk_end = min(cursor + timedelta(days=chunk_days), end)
        from_str = cursor.strftime("%Y-%m-%dT%H:%MZ")
        to_str = chunk_end.strftime("%Y-%m-%dT%H:%MZ")

        try:
            if region_id and region_id <= 17:
                url = f"{API_BASE}/regional/intensity/{from_str}/{to_str}/regionid/{region_id}"
            else:
                url = f"{API_BASE}/intensity/{from_str}/{to_str}"

            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("data", {})

                if isinstance(data, dict):
                    # Regional response format
                    for entry in data.get("data", []):
                        for region in entry.get("regions", []):
                            if region.get("regionid") == region_id:
                                all_records.append({
                                    "timestamp_utc": entry["from"],
                                    "forecast": region.get("intensity", {}).get("forecast"),
                                    "actual": region.get("intensity", {}).get("actual") or region.get("intensity", {}).get("forecast"),
                                    "index": region.get("intensity", {}).get("index"),
                                })
                elif isinstance(data, list):
                    # National response format
                    for entry in data:
                        all_records.append({
                            "timestamp_utc": entry.get("from"),
                            "forecast": entry.get("intensity", {}).get("forecast"),
                            "actual": entry.get("intensity", {}).get("actual") or entry.get("intensity", {}).get("forecast"),
                            "index": entry.get("intensity", {}).get("index"),
                        })
        except Exception:
            pass

        cursor = chunk_end

    if not all_records:
        return _generate_synthetic_history(region_id, days)

    # Deduplicate and sort
    df = pd.DataFrame(all_records)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.drop_duplicates(subset="timestamp_utc").sort_values("timestamp_utc").reset_index(drop=True)

    # Fill gaps
    df["intensity_gco2"] = pd.to_numeric(df["actual"], errors="coerce").fillna(
        pd.to_numeric(df["forecast"], errors="coerce")
    )
    df = df.dropna(subset=["intensity_gco2"])

    # Resample to hourly
    df = df.set_index("timestamp_utc")
    hourly = df["intensity_gco2"].resample("1h").mean().dropna()

    records = [
        {"timestamp_utc": ts.isoformat(), "intensity_gco2": round(float(val), 1)}
        for ts, val in hourly.items()
    ]

    return {
        "region_id": region_id,
        "region_name": REGION_NAMES.get(region_id, "GB"),
        "days": days,
        "points": len(records),
        "avg_intensity": round(float(hourly.mean()), 1),
        "min_intensity": round(float(hourly.min()), 1),
        "max_intensity": round(float(hourly.max()), 1),
        "history": records,
    }


def _generate_synthetic_history(region_id: int, days: int) -> dict:
    """Generate synthetic carbon intensity when API is unavailable."""
    base = REGIONAL_AVERAGES.get(region_id, 150)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    records = []
    ts = start
    while ts < now:
        hour = ts.hour + ts.minute / 60.0
        day_of_year = ts.timetuple().tm_yday

        # Diurnal: lower at midday (solar), higher morning/evening
        diurnal = 1.0 + 0.25 * math.cos(2 * math.pi * (hour - 13) / 24)
        # Seasonal: higher in winter (gas), lower in summer (renewables)
        seasonal = 1.0 + 0.2 * math.cos(2 * math.pi * (day_of_year - 172) / 365)
        # Weekend effect: ~10% lower
        weekend = 0.9 if ts.weekday() >= 5 else 1.0
        # Noise
        noise = 1.0 + np.random.normal(0, 0.08)

        intensity = max(15, base * diurnal * seasonal * weekend * noise)
        records.append({
            "timestamp_utc": ts.isoformat(),
            "intensity_gco2": round(intensity, 1),
        })
        ts += timedelta(hours=1)

    intensities = [r["intensity_gco2"] for r in records]
    return {
        "region_id": region_id,
        "region_name": REGION_NAMES.get(region_id, "GB"),
        "days": days,
        "points": len(records),
        "avg_intensity": round(float(np.mean(intensities)), 1),
        "min_intensity": round(float(np.min(intensities)), 1),
        "max_intensity": round(float(np.max(intensities)), 1),
        "synthetic": True,
        "history": records,
    }


# ─── Analytical forecast (instant) ───────────────────────────────────────────

def forecast_analytical(region_id: int = 13, horizon_hours: int = 48) -> dict:
    """Fast analytical carbon intensity forecast — no ML, instant response."""
    base = REGIONAL_AVERAGES.get(region_id, 150)
    now = datetime.now(timezone.utc)

    # Try to get current actual from API for calibration
    try:
        resp = requests.get(f"{API_BASE}/intensity", timeout=5)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if data:
                actual = data[0].get("intensity", {}).get("actual")
                if actual:
                    base = actual
    except Exception:
        pass

    forecasts = []
    for i in range(horizon_hours):
        ts = now + timedelta(hours=i)
        hour = ts.hour + ts.minute / 60.0
        day_of_year = ts.timetuple().tm_yday

        # Diurnal pattern: solar dip midday, gas ramp morning/evening
        diurnal = 1.0 + 0.25 * math.cos(2 * math.pi * (hour - 13) / 24)
        # Seasonal: winter higher, summer lower
        seasonal = 1.0 + 0.2 * math.cos(2 * math.pi * (day_of_year - 172) / 365)
        # Weekend
        weekend = 0.9 if ts.weekday() >= 5 else 1.0

        p50 = max(15, base * diurnal * seasonal * weekend)

        # Uncertainty grows with horizon
        spread = p50 * 0.08 * (1 + 0.03 * i)  # +3% per hour
        p10 = max(10, p50 - 1.28 * spread)
        p90 = p50 + 1.28 * spread

        forecasts.append({
            "timestamp_utc": ts.isoformat(),
            "p10_gco2": round(p10, 1),
            "p50_gco2": round(p50, 1),
            "p90_gco2": round(p90, 1),
        })

    return {
        "region_id": region_id,
        "region_name": REGION_NAMES.get(region_id, "GB"),
        "model": "analytical",
        "horizon_hours": horizon_hours,
        "forecast_from": now.isoformat(),
        "points": len(forecasts),
        "forecasts": forecasts,
    }


# ─── Prophet forecast ─────────────────────────────────────────────────────────

def forecast_prophet(region_id: int = 13, horizon_hours: int = 48,
                     history_days: int = 30) -> dict:
    """Prophet-based carbon intensity forecast with P10/P50/P90 bands."""
    from prophet import Prophet

    hist = fetch_history(region_id, history_days)
    if not hist.get("history"):
        return {"error": "Failed to fetch carbon intensity history"}

    df = pd.DataFrame(hist["history"])
    df = df.rename(columns={"timestamp_utc": "ds", "intensity_gco2": "y"})
    df["ds"] = pd.to_datetime(df["ds"], utc=True).dt.tz_localize(None)
    df = df[["ds", "y"]].dropna().sort_values("ds").reset_index(drop=True)

    if len(df) < 48:
        return {"error": f"Insufficient history: {len(df)} points (need >=48)"}

    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=True,
        interval_width=0.8,
        changepoint_prior_scale=0.05,
    )
    m.fit(df)

    future = m.make_future_dataframe(periods=horizon_hours, freq="1h")
    fc = m.predict(future)
    fc_only = fc.iloc[len(df):].copy()

    forecasts = []
    for _, row in fc_only.iterrows():
        forecasts.append({
            "timestamp_utc": row["ds"].isoformat() + "Z",
            "p10_gco2": round(max(10, float(row["yhat_lower"])), 1),
            "p50_gco2": round(max(10, float(row["yhat"])), 1),
            "p90_gco2": round(float(row["yhat_upper"]), 1),
        })

    return {
        "region_id": region_id,
        "region_name": REGION_NAMES.get(region_id, "GB"),
        "model": "prophet",
        "horizon_hours": horizon_hours,
        "history_days": history_days,
        "history_points": len(df),
        "forecast_from": df["ds"].iloc[-1].isoformat() + "Z",
        "points": len(forecasts),
        "avg_historical_intensity": round(float(df["y"].mean()), 1),
        "forecasts": forecasts,
    }


# ─── Darts TFT forecast ──────────────────────────────────────────────────────

def forecast_tft(region_id: int = 13, horizon_hours: int = 48,
                 history_days: int = 30, epochs: int = 15) -> dict:
    """Temporal Fusion Transformer carbon intensity forecast with P10/P50/P90."""
    from darts import TimeSeries, concatenate
    from darts.models import TFTModel
    from darts.dataprocessing.transformers import Scaler
    from darts.utils.timeseries_generation import datetime_attribute_timeseries

    hist = fetch_history(region_id, history_days)
    if not hist.get("history"):
        return {"error": "Failed to fetch carbon intensity history"}

    df = pd.DataFrame(hist["history"])
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.rename(columns={"intensity_gco2": "y"})
    df = df[["timestamp_utc", "y"]].dropna().sort_values("timestamp_utc")
    df = df.set_index("timestamp_utc")

    # Ensure hourly frequency
    df = df.asfreq("1h", method="ffill")

    if len(df) < 96:
        return {"error": f"Insufficient history: {len(df)} points (need >=96)"}

    # Create Darts TimeSeries
    series = TimeSeries.from_dataframe(df, value_cols="y", freq="1h")

    # Scale
    scaler = Scaler()
    scaled = scaler.fit_transform(series)

    # Time covariates
    hour_cov = datetime_attribute_timeseries(scaled, attribute="hour", one_hot=False)
    dow_cov = datetime_attribute_timeseries(scaled, attribute="dayofweek", one_hot=False)
    month_cov = datetime_attribute_timeseries(scaled, attribute="month", one_hot=False)
    covariates = concatenate([hour_cov, dow_cov, month_cov], axis=1)

    # Forecast horizon
    output_chunk = min(horizon_hours, 336)
    input_chunk = min(len(scaled) - output_chunk, 336)

    if input_chunk < 48:
        return {"error": "Not enough history for TFT (need longer history or shorter horizon)"}

    # Future covariates
    future_index = pd.date_range(
        start=df.index[-1] + pd.Timedelta(hours=1),
        periods=output_chunk, freq="1h",
    )
    future_df = pd.DataFrame({"placeholder": [0] * len(future_index)}, index=future_index)
    future_series = TimeSeries.from_dataframe(future_df, freq="1h")
    hour_fut = datetime_attribute_timeseries(future_series, attribute="hour", one_hot=False)
    dow_fut = datetime_attribute_timeseries(future_series, attribute="dayofweek", one_hot=False)
    month_fut = datetime_attribute_timeseries(future_series, attribute="month", one_hot=False)
    future_covs = concatenate([hour_fut, dow_fut, month_fut], axis=1)
    full_covs = covariates.append(future_covs)

    # Train TFT
    model = TFTModel(
        input_chunk_length=input_chunk,
        output_chunk_length=output_chunk,
        hidden_size=32,
        lstm_layers=1,
        num_attention_heads=4,
        dropout=0.1,
        batch_size=32,
        n_epochs=epochs,
        likelihood=None,
        random_state=42,
        pl_trainer_kwargs={"enable_progress_bar": False, "accelerator": "cpu"},
    )

    model.fit(scaled, future_covariates=full_covs)

    # Predict
    pred = model.predict(
        n=output_chunk, series=scaled,
        future_covariates=full_covs, num_samples=100,
    )

    pred_rescaled = scaler.inverse_transform(pred)

    p10 = pred_rescaled.quantile_df(0.1)
    p50 = pred_rescaled.quantile_df(0.5)
    p90 = pred_rescaled.quantile_df(0.9)

    forecasts = []
    for i in range(len(p50)):
        ts = p50.index[i]
        forecasts.append({
            "timestamp_utc": ts.isoformat() + "Z",
            "p10_gco2": round(max(10, float(p10.iloc[i, 0])), 1),
            "p50_gco2": round(max(10, float(p50.iloc[i, 0])), 1),
            "p90_gco2": round(float(p90.iloc[i, 0]), 1),
        })

    return {
        "region_id": region_id,
        "region_name": REGION_NAMES.get(region_id, "GB"),
        "model": "tft",
        "horizon_hours": horizon_hours,
        "history_days": history_days,
        "history_points": len(df),
        "epochs": epochs,
        "forecast_from": df.index[-1].isoformat() + "Z",
        "points": len(forecasts),
        "avg_historical_intensity": round(float(df["y"].mean()), 1),
        "forecasts": forecasts,
    }


# ─── Subprocess bridge ────────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "fetch_history":
            result = fetch_history(
                region_id=req.get("region_id", 13),
                days=req.get("days", 30),
            )
        elif cmd == "forecast_analytical":
            result = forecast_analytical(
                region_id=req.get("region_id", 13),
                horizon_hours=req.get("horizon_hours", 48),
            )
        elif cmd == "forecast_prophet":
            result = forecast_prophet(
                region_id=req.get("region_id", 13),
                horizon_hours=req.get("horizon_hours", 48),
                history_days=req.get("history_days", 30),
            )
        elif cmd == "forecast_tft":
            result = forecast_tft(
                region_id=req.get("region_id", 13),
                horizon_hours=req.get("horizon_hours", 48),
                history_days=req.get("history_days", 30),
                epochs=req.get("epochs", 15),
            )
        else:
            result = {"error": f"Unknown command: {cmd}"}

        json.dump(result, sys.stdout)

    except Exception as e:
        import traceback
        json.dump({"error": str(e), "traceback": traceback.format_exc()}, sys.stdout)


if __name__ == "__main__":
    main()

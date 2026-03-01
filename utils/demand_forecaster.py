#!/usr/bin/env python3
"""
Demand forecaster — Princeps Phase 5
Prophet baseline + Darts TFT probabilistic forecasting.
Runs as subprocess via JSON stdin/stdout bridge.

Commands:
  {"command": "forecast_prophet", "gsp_id": "ABHA", "history": [...], "horizon_hours": 168}
  {"command": "forecast_tft", "gsp_id": "ABHA", "history": [...], "horizon_hours": 168}
  {"command": "scenario_forecast", "gsp_id": "ABHA", "history": [...], "scenarios": {...}, "years_ahead": 5}
  {"command": "quick_forecast", "gsp_id": "ABHA", "peak_mw": 285, "min_mw": 95, "capacity_mw": 360, "horizon_hours": 168}
"""

import json
import sys
import math
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─── Prophet baseline ───────────────────────────────────────────────────────

def forecast_prophet(history: list[dict], horizon_hours: int = 168,
                     gsp_id: str = "unknown") -> dict:
    """
    Prophet baseline forecast with quantile intervals.
    Returns P10/P50/P90 for each future timestep.
    """
    from prophet import Prophet

    # Build DataFrame: ds (datetime), y (demand)
    df = pd.DataFrame(history)
    if "timestamp_utc" in df.columns:
        df = df.rename(columns={"timestamp_utc": "ds", "demand_mw": "y"})
    elif "ds" not in df.columns:
        return {"error": "History must have 'timestamp_utc' or 'ds' column"}

    df["ds"] = pd.to_datetime(df["ds"], utc=True).dt.tz_localize(None)
    df = df[["ds", "y"]].dropna().sort_values("ds").reset_index(drop=True)

    if len(df) < 48:  # Need at least 1 day of half-hourly data
        return {"error": f"Insufficient history: {len(df)} points (need >=48)"}

    # Detect frequency
    freq_mins = int((df["ds"].iloc[1] - df["ds"].iloc[0]).total_seconds() / 60)
    periods = horizon_hours * 60 // freq_mins

    # Fit Prophet
    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=True,
        daily_seasonality=True,
        interval_width=0.8,  # 80% interval ~ P10/P90
        changepoint_prior_scale=0.05,
    )
    m.fit(df)

    # Forecast
    future = m.make_future_dataframe(periods=periods, freq=f"{freq_mins}min")
    fc = m.predict(future)

    # Extract forecast-only rows
    fc_only = fc.iloc[len(df):].copy()

    forecasts = []
    for _, row in fc_only.iterrows():
        forecasts.append({
            "timestamp_utc": row["ds"].isoformat() + "Z",
            "p10_mw": round(float(row["yhat_lower"]), 1),
            "p50_mw": round(float(row["yhat"]), 1),
            "p90_mw": round(float(row["yhat_upper"]), 1),
        })

    return {
        "gsp_id": gsp_id,
        "model": "prophet",
        "horizon_hours": horizon_hours,
        "frequency_mins": freq_mins,
        "forecast_from": df["ds"].iloc[-1].isoformat() + "Z",
        "points": len(forecasts),
        "forecasts": forecasts,
    }


# ─── Darts TFT probabilistic ────────────────────────────────────────────────

def forecast_tft(history: list[dict], horizon_hours: int = 168,
                 gsp_id: str = "unknown", epochs: int = 20) -> dict:
    """
    Temporal Fusion Transformer via Darts.
    Returns P10/P50/P90 quantile forecasts.
    """
    from darts import TimeSeries
    from darts.models import TFTModel
    from darts.dataprocessing.transformers import Scaler

    df = pd.DataFrame(history)
    if "timestamp_utc" in df.columns:
        df = df.rename(columns={"timestamp_utc": "ds", "demand_mw": "y"})

    df["ds"] = pd.to_datetime(df["ds"], utc=True)
    df = df[["ds", "y"]].dropna().sort_values("ds").reset_index(drop=True)
    df = df.set_index("ds")

    if len(df) < 96:  # Need >= 2 days for TFT
        return {"error": f"Insufficient history: {len(df)} points (need >=96)"}

    # Detect frequency
    freq = pd.infer_freq(df.index)
    if not freq:
        freq = "30min"
        df = df.asfreq("30min", method="ffill")

    # Create Darts TimeSeries
    series = TimeSeries.from_dataframe(df, value_cols="y", freq=freq)

    # Scale
    scaler = Scaler()
    scaled = scaler.fit_transform(series)

    # Time covariates (hour, day_of_week, month)
    from darts.utils.timeseries_generation import datetime_attribute_timeseries
    hour_cov = datetime_attribute_timeseries(scaled, attribute="hour", one_hot=False)
    dow_cov = datetime_attribute_timeseries(scaled, attribute="dayofweek", one_hot=False)
    month_cov = datetime_attribute_timeseries(scaled, attribute="month", one_hot=False)

    from darts import concatenate
    covariates = concatenate([hour_cov, dow_cov, month_cov], axis=1)

    # Extend covariates for forecast horizon
    freq_mins = 30 if "30" in str(freq) else 60
    output_chunk = min(horizon_hours * 60 // freq_mins, 336)  # Cap at 7 days of HH
    input_chunk = min(len(scaled) - output_chunk, 336)

    if input_chunk < 48:
        return {"error": "Not enough data for TFT training"}

    # Future covariates for prediction
    future_index = pd.date_range(
        start=df.index[-1] + pd.Timedelta(minutes=freq_mins),
        periods=output_chunk,
        freq=freq,
    )
    future_df = pd.DataFrame({"placeholder": [0] * len(future_index)}, index=future_index)
    future_series = TimeSeries.from_dataframe(future_df, freq=freq)
    hour_fut = datetime_attribute_timeseries(future_series, attribute="hour", one_hot=False)
    dow_fut = datetime_attribute_timeseries(future_series, attribute="dayofweek", one_hot=False)
    month_fut = datetime_attribute_timeseries(future_series, attribute="month", one_hot=False)
    future_covs = concatenate([hour_fut, dow_fut, month_fut], axis=1)
    full_covs = covariates.append(future_covs)

    # TFT model
    model = TFTModel(
        input_chunk_length=input_chunk,
        output_chunk_length=output_chunk,
        hidden_size=32,
        lstm_layers=1,
        num_attention_heads=4,
        dropout=0.1,
        batch_size=32,
        n_epochs=epochs,
        likelihood=None,  # Use quantile regression
        random_state=42,
        pl_trainer_kwargs={"enable_progress_bar": False, "accelerator": "cpu"},
    )

    model.fit(scaled, future_covariates=full_covs)

    # Predict with quantiles
    pred = model.predict(
        n=output_chunk,
        series=scaled,
        future_covariates=full_covs,
        num_samples=100,
    )

    # Inverse scale
    pred_rescaled = scaler.inverse_transform(pred)

    # Extract quantiles
    p10 = pred_rescaled.quantile_df(0.1)
    p50 = pred_rescaled.quantile_df(0.5)
    p90 = pred_rescaled.quantile_df(0.9)

    forecasts = []
    for i in range(len(p50)):
        ts = p50.index[i]
        forecasts.append({
            "timestamp_utc": ts.isoformat() + "Z",
            "p10_mw": round(float(p10.iloc[i, 0]), 1),
            "p50_mw": round(float(p50.iloc[i, 0]), 1),
            "p90_mw": round(float(p90.iloc[i, 0]), 1),
        })

    return {
        "gsp_id": gsp_id,
        "model": "tft",
        "horizon_hours": horizon_hours,
        "frequency_mins": freq_mins,
        "forecast_from": df.index[-1].isoformat() + "Z",
        "points": len(forecasts),
        "forecasts": forecasts,
    }


# ─── Scenario-weighted long-term forecast ────────────────────────────────────

def scenario_forecast(peak_mw: float, min_mw: float, capacity_mw: float,
                      gsp_id: str = "unknown", years_ahead: int = 10,
                      scenarios: dict = None) -> dict:
    """
    Long-term scenario-weighted demand forecast.
    Uses NESO FES growth rates to project future demand trajectories.
    Returns annual P10/P50/P90 + capacity exceedance probability.
    """
    default_scenarios = {
        "leading_the_way": {"growth": 0.035, "weight": 0.2, "label": "Leading the Way"},
        "consumer_transformation": {"growth": 0.028, "weight": 0.3, "label": "Consumer Transformation"},
        "system_transformation": {"growth": 0.022, "weight": 0.3, "label": "System Transformation"},
        "falling_short": {"growth": 0.012, "weight": 0.2, "label": "Falling Short"},
    }
    scens = scenarios or default_scenarios

    base_year = 2024
    annual_results = []

    for yr in range(years_ahead + 1):
        year = base_year + yr
        samples = []

        for sname, sdata in scens.items():
            growth = sdata["growth"]
            weight = sdata["weight"]

            # Compound growth with noise
            for _ in range(200):
                annual_growth = growth * (1 + np.random.normal(0, 0.15))
                projected_peak = peak_mw * (1 + annual_growth) ** yr
                # Add Monte Carlo noise
                projected_peak *= (1 + np.random.normal(0, 0.03))
                samples.extend([projected_peak] * max(1, int(weight * 10)))

        samples = np.array(samples)
        p10 = float(np.percentile(samples, 10))
        p50 = float(np.percentile(samples, 50))
        p90 = float(np.percentile(samples, 90))

        # Probability of exceeding capacity
        exceed_prob = float(np.mean(samples > capacity_mw))

        # Time-to-constraint: year when P50 > 80% capacity
        utilisation = p50 / capacity_mw

        annual_results.append({
            "year": year,
            "p10_mw": round(p10, 1),
            "p50_mw": round(p50, 1),
            "p90_mw": round(p90, 1),
            "capacity_mw": capacity_mw,
            "utilisation": round(utilisation, 3),
            "exceedance_probability": round(exceed_prob, 3),
        })

    # Find time-to-constraint
    constraint_year = None
    for r in annual_results:
        if r["utilisation"] >= 0.8:
            constraint_year = r["year"]
            break

    # Per-scenario trajectories
    scenario_trajectories = {}
    for sname, sdata in scens.items():
        traj = []
        for yr in range(years_ahead + 1):
            proj = peak_mw * (1 + sdata["growth"]) ** yr
            traj.append({
                "year": base_year + yr,
                "peak_demand_mw": round(proj, 1),
                "capacity_mw": capacity_mw,
            })
        scenario_trajectories[sname] = {
            "label": sdata.get("label", sname),
            "annual_growth_rate": sdata["growth"],
            "trajectory": traj,
        }

    return {
        "gsp_id": gsp_id,
        "model": "scenario_ensemble",
        "base_year": base_year,
        "years_ahead": years_ahead,
        "current_peak_mw": peak_mw,
        "current_min_mw": min_mw,
        "capacity_mw": capacity_mw,
        "time_to_constraint_year": constraint_year,
        "annual_forecasts": annual_results,
        "scenarios": scenario_trajectories,
    }


# ─── Quick forecast (no training, analytical model) ─────────────────────────

def quick_forecast(peak_mw: float, min_mw: float, capacity_mw: float,
                   gsp_id: str = "unknown", horizon_hours: int = 168,
                   start_date: str = None) -> dict:
    """
    Fast analytical forecast — no ML training needed.
    Uses sinusoidal demand model with noise for P10/P50/P90 bands.
    Good for instant UI display while TFT trains.
    """
    if start_date:
        start = datetime.fromisoformat(start_date.replace("Z", ""))
    else:
        start = datetime.utcnow()

    forecasts = []
    n_points = horizon_hours * 2  # Half-hourly

    for i in range(n_points):
        ts = start + timedelta(minutes=30 * i)
        hour = ts.hour + ts.minute / 60.0
        day_of_year = ts.timetuple().tm_yday

        # Diurnal pattern
        morning = math.exp(-0.5 * ((hour - 8.5) / 1.8) ** 2) * 0.85
        evening = math.exp(-0.5 * ((hour - 17.5) / 2.0) ** 2) * 1.0
        night = 0.35 + 0.15 * math.cos(2 * math.pi * (hour - 3) / 24)
        diurnal = max(night, morning, evening)

        # Seasonal
        seasonal = 0.7 + 0.3 * math.cos(2 * math.pi * (day_of_year - 15) / 365)

        base = min_mw + (peak_mw - min_mw) * diurnal * seasonal

        # Uncertainty grows with horizon
        horizon_factor = 1 + 0.02 * (i / (2 * 24))  # +2% per day ahead
        spread = base * 0.08 * horizon_factor

        forecasts.append({
            "timestamp_utc": ts.isoformat() + "Z",
            "p10_mw": round(base - 1.28 * spread, 1),
            "p50_mw": round(base, 1),
            "p90_mw": round(base + 1.28 * spread, 1),
        })

    return {
        "gsp_id": gsp_id,
        "model": "analytical",
        "horizon_hours": horizon_hours,
        "frequency_mins": 30,
        "forecast_from": start.isoformat() + "Z",
        "points": len(forecasts),
        "capacity_mw": capacity_mw,
        "peak_demand_mw": peak_mw,
        "forecasts": forecasts,
    }


# ─── Subprocess bridge ──────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "forecast_prophet":
            result = forecast_prophet(
                history=req.get("history", []),
                horizon_hours=req.get("horizon_hours", 168),
                gsp_id=req.get("gsp_id", "unknown"),
            )
            json.dump(result, sys.stdout)

        elif cmd == "forecast_tft":
            result = forecast_tft(
                history=req.get("history", []),
                horizon_hours=req.get("horizon_hours", 168),
                gsp_id=req.get("gsp_id", "unknown"),
                epochs=req.get("epochs", 20),
            )
            json.dump(result, sys.stdout)

        elif cmd == "scenario_forecast":
            result = scenario_forecast(
                peak_mw=req.get("peak_mw", 285),
                min_mw=req.get("min_mw", 95),
                capacity_mw=req.get("capacity_mw", 360),
                gsp_id=req.get("gsp_id", "unknown"),
                years_ahead=req.get("years_ahead", 10),
                scenarios=req.get("scenarios"),
            )
            json.dump(result, sys.stdout)

        elif cmd == "quick_forecast":
            result = quick_forecast(
                peak_mw=req.get("peak_mw", 285),
                min_mw=req.get("min_mw", 95),
                capacity_mw=req.get("capacity_mw", 360),
                gsp_id=req.get("gsp_id", "unknown"),
                horizon_hours=req.get("horizon_hours", 168),
                start_date=req.get("start_date"),
            )
            json.dump(result, sys.stdout)

        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)

    except Exception as e:
        import traceback
        json.dump({"error": str(e), "traceback": traceback.format_exc()}, sys.stdout)


if __name__ == "__main__":
    main()

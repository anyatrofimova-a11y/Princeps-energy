"""
UK Grid Demand & Generation Analyser
Extracted from CarlosYazid/Energy-UK (LSTM/GRU approach).

Uses 15 years of half-hourly UK grid data (277K records) and 8 years of
daily weather data to provide:
  - Historical demand profiles (hourly, monthly, seasonal)
  - Embedded solar generation patterns
  - Grid curtailment risk scoring
  - Lightweight demand forecasting (sklearn instead of TensorFlow)
"""

import math
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import MinMaxScaler

DATA_DIR = Path(__file__).parent.parent / "Energy-UK"
ELEC_CSV = DATA_DIR / "uk_electricity.csv"
WEATHER_CSV = DATA_DIR / "uk_weather.csv"
MODEL_PATH = Path(__file__).parent.parent / "data" / "uk_demand_model.pkl"

# Cached DataFrames
_elec_df: pd.DataFrame | None = None
_weather_df: pd.DataFrame | None = None


def load_electricity() -> pd.DataFrame:
    """Load and cache UK electricity grid data (277K half-hourly records, 2009-2024)."""
    global _elec_df
    if _elec_df is not None:
        return _elec_df
    if not ELEC_CSV.exists():
        raise FileNotFoundError(f"Missing {ELEC_CSV}")
    df = pd.read_csv(
        ELEC_CSV,
        parse_dates=["settlement_date"],
        dtype={
            "settlement_period": "int8",
            "nd": "int32",
            "tsd": "int32",
            "england_wales_demand": "int32",
            "embedded_wind_generation": "int16",
            "embedded_solar_generation": "int16",
        },
    )
    df.fillna(0, inplace=True)
    df = df.set_index("settlement_date").sort_index()
    _elec_df = df
    return df


def load_weather() -> pd.DataFrame:
    """Load and cache UK weather data (3K daily records, 2016-2024)."""
    global _weather_df
    if _weather_df is not None:
        return _weather_df
    if not WEATHER_CSV.exists():
        raise FileNotFoundError(f"Missing {WEATHER_CSV}")
    df = pd.read_csv(WEATHER_CSV, parse_dates=["datetime"], index_col="datetime")
    df.fillna(0, inplace=True)
    df = df.sort_index()
    # Calculate sunshine hours if sunrise/sunset present
    if "sunrise" in df.columns and "sunset" in df.columns:
        df["sunrise"] = pd.to_datetime(df["sunrise"])
        df["sunset"] = pd.to_datetime(df["sunset"])
        df["sunshine_hours"] = (df["sunset"] - df["sunrise"]).dt.total_seconds() / 3600
        df = df.drop(columns=["sunrise", "sunset"])
    _weather_df = df
    return df


def demand_profile_hourly() -> dict:
    """Average national demand (MW) by hour of day, across full dataset."""
    df = load_electricity()
    hourly = df.groupby(df["period_hour"].round().astype(int))["nd"].mean()
    return {
        "hours": list(range(24)),
        "avg_demand_mw": [round(float(hourly.get(h, 0)), 0) for h in range(24)],
    }


def demand_profile_monthly() -> dict:
    """Average national demand (MW) by month."""
    df = load_electricity()
    monthly = df.groupby(df.index.month)["nd"].mean()
    return {
        "months": list(range(1, 13)),
        "avg_demand_mw": [round(float(monthly.get(m, 0)), 0) for m in range(1, 13)],
    }


def solar_generation_hourly() -> dict:
    """Average embedded solar generation (MW) by hour of day."""
    df = load_electricity()
    # Filter to years with meaningful solar data (2012+)
    df_solar = df[df.index.year >= 2012]
    hourly = df_solar.groupby(df_solar["period_hour"].round().astype(int))["embedded_solar_generation"].mean()
    return {
        "hours": list(range(24)),
        "avg_solar_mw": [round(float(max(0, hourly.get(h, 0))), 1) for h in range(24)],
    }


def solar_generation_monthly() -> dict:
    """Average embedded solar generation (MW) by month."""
    df = load_electricity()
    df_solar = df[df.index.year >= 2012]
    monthly = df_solar.groupby(df_solar.index.month)["embedded_solar_generation"].mean()
    return {
        "months": list(range(1, 13)),
        "avg_solar_mw": [round(float(max(0, monthly.get(m, 0))), 1) for m in range(1, 13)],
    }


def grid_summary() -> dict:
    """Key statistics from the full electricity dataset."""
    df = load_electricity()
    return {
        "records": len(df),
        "date_range": [str(df.index.min().date()), str(df.index.max().date())],
        "demand_mw": {
            "mean": round(float(df["nd"].mean()), 0),
            "min": int(df["nd"].min()),
            "max": int(df["nd"].max()),
            "std": round(float(df["nd"].std()), 0),
        },
        "embedded_solar_mw": {
            "mean": round(float(df["embedded_solar_generation"].mean()), 1),
            "max": int(df["embedded_solar_generation"].max()),
        },
        "embedded_wind_mw": {
            "mean": round(float(df["embedded_wind_generation"].mean()), 1),
            "max": int(df["embedded_wind_generation"].max()),
        },
    }


def curtailment_risk(day_of_year: int = 172) -> dict:
    """
    Estimate grid curtailment risk for a given day.
    When embedded solar is high relative to demand, export prices
    can drop or curtailment may occur.

    Returns hourly risk profile (0-1 scale) and summary metrics.
    """
    df = load_electricity()
    df_solar = df[df.index.year >= 2016]  # Better solar coverage

    # Filter to the requested day of year
    mask = df_solar.index.dayofyear == day_of_year
    day_data = df_solar[mask]

    if len(day_data) == 0:
        return {"hourly_risk": [0.0] * 24, "avg_risk": 0.0, "peak_risk_hour": 12}

    # Group by hour
    hourly = day_data.groupby(day_data["period_hour"].round().astype(int)).agg({
        "nd": "mean",
        "embedded_solar_generation": "mean",
        "embedded_wind_generation": "mean",
    })

    risk_scores = []
    for h in range(24):
        if h not in hourly.index:
            risk_scores.append(0.0)
            continue
        demand = hourly.loc[h, "nd"]
        solar = max(0, hourly.loc[h, "embedded_solar_generation"])
        wind = max(0, hourly.loc[h, "embedded_wind_generation"])
        renewables = solar + wind
        # Risk = ratio of renewables to demand (higher ratio = more curtailment risk)
        ratio = renewables / max(demand, 1)
        risk = min(1.0, ratio * 2.0)  # Scale so 50% penetration = 1.0
        risk_scores.append(round(risk, 3))

    peak_idx = int(np.argmax(risk_scores))
    return {
        "hourly_risk": risk_scores,
        "avg_risk": round(float(np.mean(risk_scores)), 3),
        "peak_risk": round(float(max(risk_scores)), 3),
        "peak_risk_hour": peak_idx,
        "day_of_year": day_of_year,
    }


def demand_for_day(day_of_year: int = 172) -> dict:
    """
    Historical average demand profile for a specific day of year.
    Returns 24-hour profile and statistics.
    """
    df = load_electricity()
    mask = df.index.dayofyear == day_of_year
    day_data = df[mask]

    if len(day_data) == 0:
        return {"hourly_demand_mw": [30000] * 24, "daily_avg": 30000}

    hourly = day_data.groupby(day_data["period_hour"].round().astype(int))["nd"].mean()
    profile = [round(float(hourly.get(h, 30000)), 0) for h in range(24)]
    peak_idx = int(np.argmax(profile))
    trough_idx = int(np.argmin(profile))

    return {
        "hourly_demand_mw": profile,
        "daily_avg": round(float(np.mean(profile)), 0),
        "peak_demand": round(float(max(profile)), 0),
        "peak_hour": peak_idx,
        "trough_demand": round(float(min(profile)), 0),
        "trough_hour": trough_idx,
        "day_of_year": day_of_year,
    }


def weather_for_day(day_of_year: int = 172) -> dict:
    """Historical average weather for a specific day of year."""
    df = load_weather()
    mask = df.index.dayofyear == day_of_year
    day_data = df[mask]

    if len(day_data) == 0:
        return {
            "temp_avg": 15.0, "cloud_cover": 60.0,
            "solar_radiation": 80.0, "solar_energy": 7.0,
        }

    return {
        "temp_avg": round(float(day_data["temp"].mean()), 1),
        "temp_max": round(float(day_data["tempmax"].mean()), 1),
        "temp_min": round(float(day_data["tempmin"].mean()), 1),
        "cloud_cover": round(float(day_data["cloudcover"].mean()), 1),
        "solar_radiation": round(float(day_data["solarradiation"].mean()), 1),
        "solar_energy": round(float(day_data["solarenergy"].mean()), 1),
        "wind_speed": round(float(day_data["windspeed"].mean()), 1),
        "uv_index": round(float(day_data["uvindex"].mean()), 1),
        "sunshine_hours": round(float(day_data.get("sunshine_hours", pd.Series([12])).mean()), 1),
        "day_of_year": day_of_year,
    }


def full_grid_context(day_of_year: int = 172) -> dict:
    """
    Comprehensive grid context for a day: demand, generation, weather, curtailment.
    This is the main integration point for the frontend.
    """
    return {
        "demand": demand_for_day(day_of_year),
        "solar_generation": {
            "hourly": solar_generation_hourly(),
            "monthly": solar_generation_monthly(),
        },
        "weather": weather_for_day(day_of_year),
        "curtailment": curtailment_risk(day_of_year),
        "summary": grid_summary(),
    }


if __name__ == "__main__":
    print("Loading UK grid data...")
    summary = grid_summary()
    print(f"Records: {summary['records']:,}")
    print(f"Date range: {summary['date_range'][0]} to {summary['date_range'][1]}")
    print(f"Demand: mean {summary['demand_mw']['mean']:,.0f} MW, "
          f"min {summary['demand_mw']['min']:,} MW, max {summary['demand_mw']['max']:,} MW")
    print(f"Embedded solar: mean {summary['embedded_solar_mw']['mean']:,.1f} MW, "
          f"max {summary['embedded_solar_mw']['max']:,} MW")
    print(f"Embedded wind: mean {summary['embedded_wind_mw']['mean']:,.1f} MW, "
          f"max {summary['embedded_wind_mw']['max']:,} MW")

    print("\nMidsummer demand profile:")
    demand = demand_for_day(172)
    print(f"  Avg: {demand['daily_avg']:,.0f} MW")
    print(f"  Peak: {demand['peak_demand']:,.0f} MW at {demand['peak_hour']}:00")
    print(f"  Trough: {demand['trough_demand']:,.0f} MW at {demand['trough_hour']}:00")

    print("\nCurtailment risk (midsummer):")
    curt = curtailment_risk(172)
    print(f"  Avg risk: {curt['avg_risk']:.3f}")
    print(f"  Peak risk: {curt['peak_risk']:.3f} at {curt['peak_risk_hour']}:00")


def enhanced_grid_context(day_of_year: int = 172, geeflow_data: dict | None = None) -> dict:
    """
    Merge standard grid context with satellite-derived data for
    a comprehensive grid connection assessment.
    """
    from utils.geeflow_grid_analysis import enhanced_grid_context as _enhance
    base = full_grid_context(day_of_year)
    return _enhance(base, geeflow_data)

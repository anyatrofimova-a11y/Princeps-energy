"""
UK Day-Ahead Electricity Price Forecaster
Extracted from Perrupi/energy-price-forecast (XGBoost approach).

Generates synthetic UK price patterns when historical data is unavailable,
trains an XGBoost model, and provides 24h price forecasts at 1-hour resolution.
Integrates with SAM/ML solar output to estimate site revenue.
"""

import math
import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path

import holidays
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

MODEL_PATH = Path(__file__).parent.parent / "data" / "energy_price_model.pkl"
UK_HOLIDAYS = holidays.UK()


def create_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create temporal features from datetime index."""
    idx = df.index
    df = df.copy()
    df["hour"] = idx.hour
    df["dayofweek"] = idx.dayofweek
    df["quarter"] = idx.quarter
    df["month"] = idx.month
    df["dayofyear"] = idx.dayofyear
    df["dayofmonth"] = idx.day
    df["weekofyear"] = idx.isocalendar().week.astype(int)
    df["weekend"] = (idx.dayofweek >= 5).astype(int)
    df["holiday"] = idx.map(lambda d: 1 if d in UK_HOLIDAYS else 0)
    return df


def add_lags(df: pd.DataFrame) -> pd.DataFrame:
    """Add price lag features (8h, 16h, 24h)."""
    df = df.copy()
    if "da_price" in df.columns:
        df["lag8"] = df["da_price"].shift(8)
        df["lag16"] = df["da_price"].shift(16)
        df["lag24"] = df["da_price"].shift(24)
    return df


def generate_synthetic_prices(days: int = 730) -> pd.DataFrame:
    """
    Generate realistic synthetic UK day-ahead electricity prices.
    Based on typical UK market patterns: ~GBP 50-200/MWh range,
    morning/evening peaks, seasonal variation, weekend dips.
    """
    rng = np.random.default_rng(42)
    start = datetime(2023, 1, 1)
    hours = days * 24
    idx = pd.date_range(start, periods=hours, freq="h")

    prices = np.zeros(hours)
    for i, dt in enumerate(idx):
        # Base price: seasonal (higher in winter)
        seasonal = 80 + 30 * math.cos(2 * math.pi * (dt.timetuple().tm_yday - 15) / 365)

        # Diurnal pattern: morning peak (7-9), evening peak (17-20), night trough
        h = dt.hour
        if 7 <= h <= 9:
            diurnal = 35 + 10 * rng.standard_normal()
        elif 17 <= h <= 20:
            diurnal = 45 + 12 * rng.standard_normal()
        elif 0 <= h <= 5:
            diurnal = -25 + 5 * rng.standard_normal()
        else:
            diurnal = 5 + 8 * rng.standard_normal()

        # Weekend discount
        weekend = -15 if dt.weekday() >= 5 else 0

        # Random walk component
        walk = 20 * rng.standard_normal()

        prices[i] = max(seasonal + diurnal + weekend + walk, -10)

    # Synthetic demand and renewables
    demand = np.array([
        8000 + 2000 * math.sin(2 * math.pi * (dt.hour - 6) / 24)
        + 1000 * math.cos(2 * math.pi * dt.timetuple().tm_yday / 365)
        + 500 * rng.standard_normal()
        for dt in idx
    ])

    solar = np.array([
        max(0, 3000 * math.sin(math.pi * max(0, dt.hour - 6) / 12)
            * (0.4 + 0.6 * math.sin(math.pi * dt.timetuple().tm_yday / 365))
            + 200 * rng.standard_normal())
        if 6 <= dt.hour <= 20 else 0
        for dt in idx
    ])

    wind = np.array([
        max(50, 1500 + 800 * math.cos(2 * math.pi * dt.timetuple().tm_yday / 365)
            + 600 * rng.standard_normal())
        for dt in idx
    ])

    df = pd.DataFrame({
        "da_price": prices,
        "power_demand_forecast": demand,
        "solar_forecast": solar,
        "wind_forecast": wind,
    }, index=idx)
    df.index.name = "delivery_time_utc"
    return df


FEATURE_COLS = [
    "power_demand_forecast", "solar_forecast", "wind_forecast",
    "hour", "dayofweek", "quarter", "month", "dayofyear",
    "dayofmonth", "weekofyear", "weekend", "holiday",
    "lag8", "lag16", "lag24",
]


def train_model(df: pd.DataFrame | None = None) -> XGBRegressor:
    """Train XGBoost price forecast model. Uses synthetic data if none provided."""
    if df is None:
        df = generate_synthetic_prices()

    df = create_features(df)
    df = add_lags(df)
    df = df.dropna()

    X = df[FEATURE_COLS]
    y = df["da_price"]

    model = XGBRegressor(
        n_estimators=500,
        max_depth=3,
        learning_rate=0.01,
        objective="reg:squarederror",
        colsample_bytree=0.6,
        subsample=0.6,
        reg_alpha=1,
    )
    model.fit(X, y, verbose=False)

    # Save model
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model, f)

    return model


def load_model() -> XGBRegressor:
    """Load trained model, training on synthetic data if no model exists."""
    if MODEL_PATH.exists():
        with open(MODEL_PATH, "rb") as f:
            return pickle.load(f)
    return train_model()


def predict_24h(
    day_of_year: int = 172,
    lat: float = 52.5,
    demand_base_mw: float = 9000,
    wind_base_mw: float = 1500,
) -> dict:
    """
    Predict 24h of UK day-ahead electricity prices for a given day.

    Returns dict with:
      - hourly_price_gbp: list of 24 prices (GBP/MWh)
      - daily_avg: average price
      - daily_min/max: min/max price
      - peak_price/peak_hour: highest price and when
      - trough_price/trough_hour: lowest price and when
    """
    model = load_model()

    year = datetime.now().year
    base_date = datetime(year, 1, 1) + timedelta(days=day_of_year - 1)

    # Build feature rows for 24+24 hours (need 24h lag lookback)
    hours_needed = 48
    start = base_date - timedelta(hours=24)
    idx = pd.date_range(start, periods=hours_needed, freq="h")

    rng = np.random.default_rng(day_of_year)

    # Generate synthetic context data for the forecast period
    demand = [
        demand_base_mw + 2000 * math.sin(2 * math.pi * (dt.hour - 6) / 24)
        + 300 * rng.standard_normal()
        for dt in idx
    ]
    solar = [
        max(0, 3000 * math.sin(math.pi * max(0, dt.hour - 6) / 12)
            * (0.4 + 0.6 * math.sin(math.pi * day_of_year / 365))
            + 100 * rng.standard_normal())
        if 6 <= dt.hour <= 20 else 0
        for dt in idx
    ]
    wind = [
        max(50, wind_base_mw + 600 * math.cos(2 * math.pi * day_of_year / 365)
            + 400 * rng.standard_normal())
        for dt in idx
    ]

    # Use synthetic "previous" prices for lags
    prev_prices = [
        80 + 30 * math.cos(2 * math.pi * (day_of_year - 15) / 365)
        + 20 * math.sin(2 * math.pi * (dt.hour - 6) / 24)
        + 10 * rng.standard_normal()
        for dt in idx
    ]

    df = pd.DataFrame({
        "da_price": prev_prices,
        "power_demand_forecast": demand,
        "solar_forecast": solar,
        "wind_forecast": wind,
    }, index=idx)

    df = create_features(df)
    df = add_lags(df)
    df = df.dropna()

    # Take only the target day (last 24 rows)
    df_today = df.iloc[-24:]
    X = df_today[FEATURE_COLS]

    prices = model.predict(X).tolist()
    prices = [round(max(p, 0), 2) for p in prices]

    peak_idx = int(np.argmax(prices))
    trough_idx = int(np.argmin(prices))

    return {
        "hourly_price_gbp": prices,
        "daily_avg": round(float(np.mean(prices)), 2),
        "daily_min": round(float(np.min(prices)), 2),
        "daily_max": round(float(np.max(prices)), 2),
        "peak_price": prices[peak_idx],
        "peak_hour": peak_idx,
        "trough_price": prices[trough_idx],
        "trough_hour": trough_idx,
        "day_of_year": day_of_year,
    }


def estimate_revenue(
    solar_hourly_kwh: list[float],
    price_hourly_gbp: list[float],
    export_tariff_p_kwh: float = 5.0,
) -> dict:
    """
    Estimate daily revenue from solar generation using price forecast.

    solar_hourly_kwh: 24 values of solar output (kWh per hour)
    price_hourly_gbp: 24 values of day-ahead price (GBP/MWh)
    export_tariff_p_kwh: fallback export tariff in pence/kWh (SEG rate)

    Returns revenue breakdown: market-rate vs fixed tariff.
    """
    if len(solar_hourly_kwh) != 24 or len(price_hourly_gbp) != 24:
        raise ValueError("Both inputs must have exactly 24 values")

    market_revenue = 0.0
    fixed_revenue = 0.0
    hourly_revenue = []

    for kwh, price_mwh in zip(solar_hourly_kwh, price_hourly_gbp):
        # Convert: price is GBP/MWh → GBP/kWh = price/1000
        market_gbp = kwh * (price_mwh / 1000.0)
        fixed_gbp = kwh * (export_tariff_p_kwh / 100.0)  # pence to GBP
        market_revenue += market_gbp
        fixed_revenue += fixed_gbp
        hourly_revenue.append(round(market_gbp, 4))

    return {
        "market_revenue_gbp": round(market_revenue, 2),
        "fixed_tariff_revenue_gbp": round(fixed_revenue, 2),
        "premium_pct": round(
            ((market_revenue - fixed_revenue) / fixed_revenue * 100)
            if fixed_revenue > 0 else 0, 1
        ),
        "hourly_revenue_gbp": hourly_revenue,
        "annual_market_estimate_gbp": round(market_revenue * 365, 0),
        "annual_fixed_estimate_gbp": round(fixed_revenue * 365, 0),
    }


if __name__ == "__main__":
    print("Training energy price model on synthetic data...")
    model = train_model()
    print(f"Model saved to {MODEL_PATH}")

    result = predict_24h(day_of_year=172)
    print(f"\nMidsummer price forecast:")
    print(f"  Avg: GBP {result['daily_avg']}/MWh")
    print(f"  Peak: GBP {result['peak_price']}/MWh at {result['peak_hour']}:00")
    print(f"  Trough: GBP {result['trough_price']}/MWh at {result['trough_hour']}:00")

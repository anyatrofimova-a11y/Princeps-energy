#!/usr/bin/env python3
"""
Constraint forecaster — Princeps Phase 9
Predicts grid constraint windows 24-48h ahead using weather,
demand, and generation profiles per UK transmission boundary.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "forecast", "hours_ahead": 48, "date": "2025-01-15",
   "wind_capacity_gw": 30, "solar_capacity_gw": 18}
  {"command": "boundary_forecast", "boundary_id": "B1", "hours_ahead": 48}
  {"command": "constraint_windows", "hours_ahead": 48, "threshold": 0.5}
"""

import json
import math
import random
import sys
from datetime import datetime, timedelta

# ── UK transmission boundaries ─────────────────────────────────────────────
BOUNDARIES = {
    "B1": {"name": "Scotland–England", "capacity_gw": 5.7, "typical_flow_gw": 3.2,
            "wind_sensitivity": 1.8, "solar_sensitivity": 0.1, "constraint_cost_mwh": 65},
    "B2": {"name": "North–Midlands", "capacity_gw": 8.5, "typical_flow_gw": 4.1,
            "wind_sensitivity": 1.2, "solar_sensitivity": 0.3, "constraint_cost_mwh": 52},
    "B4": {"name": "Midlands–South", "capacity_gw": 11.2, "typical_flow_gw": 5.8,
            "wind_sensitivity": 0.6, "solar_sensitivity": 0.7, "constraint_cost_mwh": 40},
    "B6": {"name": "South–London", "capacity_gw": 7.8, "typical_flow_gw": 6.2,
            "wind_sensitivity": 0.3, "solar_sensitivity": 0.5, "constraint_cost_mwh": 35},
    "B7": {"name": "Wales–Midlands", "capacity_gw": 3.2, "typical_flow_gw": 1.8,
            "wind_sensitivity": 1.4, "solar_sensitivity": 0.3, "constraint_cost_mwh": 48},
    "B8": {"name": "East–South", "capacity_gw": 6.5, "typical_flow_gw": 3.4,
            "wind_sensitivity": 0.8, "solar_sensitivity": 0.8, "constraint_cost_mwh": 42},
    "B9": {"name": "Cheviot", "capacity_gw": 3.3, "typical_flow_gw": 2.8,
            "wind_sensitivity": 1.9, "solar_sensitivity": 0.1, "constraint_cost_mwh": 70},
}

# Approximate boundary zone polygons (WGS84) — simplified corridors
# Each boundary is a polygon strip across GB where the constraint applies
BOUNDARY_ZONES = {
    "B1": [[-4.5, 55.2], [-2.0, 55.2], [-2.0, 55.9], [-4.5, 55.9], [-4.5, 55.2]],
    "B2": [[-3.5, 53.5], [-0.5, 53.5], [-0.5, 54.2], [-3.5, 54.2], [-3.5, 53.5]],
    "B4": [[-3.0, 52.0], [0.5, 52.0], [0.5, 52.7], [-3.0, 52.7], [-3.0, 52.0]],
    "B6": [[-1.0, 51.2], [0.5, 51.2], [0.5, 51.7], [-1.0, 51.7], [-1.0, 51.2]],
    "B7": [[-4.5, 52.2], [-2.5, 52.2], [-2.5, 52.9], [-4.5, 52.9], [-4.5, 52.2]],
    "B8": [0.0, 51.5, 1.5, 51.5, 1.5, 52.2, 0.0, 52.2, 0.0, 51.5],
    "B9": [[-3.0, 55.4], [-1.5, 55.4], [-1.5, 56.0], [-3.0, 56.0], [-3.0, 55.4]],
}
# Fix B8 to nested list format
BOUNDARY_ZONES["B8"] = [[0.0, 51.5], [1.5, 51.5], [1.5, 52.2], [0.0, 52.2], [0.0, 51.5]]


def constraints_to_geojson(hours_ahead: int = 48, date: str = None) -> dict:
    """Return constraint forecast as GeoJSON FeatureCollection with polygon zones."""
    full = forecast_constraints(hours_ahead, date)
    features = []
    for b_id, bf in full["boundaries"].items():
        coords = BOUNDARY_ZONES.get(b_id)
        if not coords:
            continue
        # Current hour stats (first entry)
        current = bf["hourly"][0] if bf["hourly"] else {}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "boundary_id": b_id,
                "name": bf["name"],
                "capacity_gw": bf["capacity_gw"],
                "peak_loading_pct": bf["peak_loading_pct"],
                "peak_constraint_prob": bf["peak_constraint_prob"],
                "constrained_hours": bf["constrained_hours"],
                "current_loading_pct": current.get("loading_pct", 0),
                "current_flow_gw": current.get("flow_gw", 0),
                "current_prob": current.get("constraint_probability", 0),
                "risk_level": "HIGH" if bf["peak_constraint_prob"] > 0.6
                              else "MEDIUM" if bf["peak_constraint_prob"] > 0.3
                              else "LOW",
                "constraint_cost_gbp_mwh": BOUNDARIES[b_id]["constraint_cost_mwh"],
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "summary": full["summary"],
        "constraint_windows": full["constraint_windows"][:10],
    }

# Typical UK weather patterns for forecast
def _weather_forecast(start_dt: datetime, hours: int) -> list:
    """Generate synthetic weather forecast (wind, solar, temperature, demand)."""
    random.seed(int(start_dt.timestamp()) % 100000)
    month = start_dt.month
    forecasts = []

    # Base seasonal values
    winter_factor = 0.5 + 0.5 * math.cos(2 * math.pi * (month - 1) / 12)
    summer_factor = 1 - winter_factor

    for h in range(hours):
        dt = start_dt + timedelta(hours=h)
        hour = dt.hour
        dow = dt.weekday()

        # Wind speed (m/s) — higher in winter, slight nocturnal peak
        wind_base = 6 + 4 * winter_factor
        wind_diurnal = -1.5 * math.sin(math.pi * (hour - 6) / 12)
        wind = max(0, wind_base + wind_diurnal + random.gauss(0, 2))

        # Wind generation (GW) — UK installed ~30GW
        wind_cf = min(1.0, (wind / 12) ** 2 * 0.8)
        wind_gen = 30 * wind_cf + random.gauss(0, 1.5)
        wind_gen = max(0, min(30, wind_gen))

        # Solar irradiance (W/m²)
        if 5 <= hour <= 20:
            solar_peak = 200 + 650 * summer_factor
            solar = solar_peak * max(0, math.sin(math.pi * (hour - 5) / 15))
        else:
            solar = 0
        solar_gen = 18 * (solar / 1000) * (0.7 + 0.3 * summer_factor)
        solar_gen = max(0, solar_gen)

        # Temperature (°C)
        temp_base = 3 + 15 * summer_factor
        temp = temp_base + 4 * math.sin(math.pi * (hour - 6) / 12) + random.gauss(0, 1.5)

        # Demand (GW) — 25-50 GW typical UK range
        demand_base = 32 + 12 * winter_factor
        morning_peak = 0.85 * math.exp(-0.5 * ((hour - 8.5) / 2.0) ** 2)
        evening_peak = 1.0 * math.exp(-0.5 * ((hour - 17.5) / 2.5) ** 2)
        night_dip = 0.35 + 0.15 * math.cos(2 * math.pi * (hour - 3) / 24)
        diurnal = max(night_dip, morning_peak, evening_peak)
        weekend = 0.92 if dow >= 5 else 1.0
        demand = demand_base * (0.6 + 0.4 * diurnal) * weekend
        demand += max(0, (10 - temp)) * 0.8  # Cold weather boost
        demand = max(20, demand + random.gauss(0, 1))

        forecasts.append({
            "hour_offset": h,
            "datetime": dt.strftime("%Y-%m-%d %H:%M"),
            "hour": hour,
            "wind_speed_ms": round(wind, 1),
            "wind_gen_gw": round(wind_gen, 1),
            "solar_irradiance_wm2": round(solar, 0),
            "solar_gen_gw": round(solar_gen, 1),
            "temperature_c": round(temp, 1),
            "demand_gw": round(demand, 1),
        })

    return forecasts


def _boundary_loading(boundary: dict, weather: dict) -> dict:
    """Calculate boundary loading and constraint probability for one timestep."""
    cap = boundary["capacity_gw"]
    typical = boundary["typical_flow_gw"]

    demand_factor = weather["demand_gw"] / 42.0
    wind_factor = 1.0 + (weather["wind_gen_gw"] / 15.0) * boundary["wind_sensitivity"] * 0.5
    solar_factor = 1.0 - (weather["solar_gen_gw"] / 12.0) * boundary["solar_sensitivity"] * 0.2
    temp_factor = 1.0 + max(0, (10 - weather["temperature_c"])) * 0.015

    flow = typical * demand_factor * wind_factor * solar_factor * temp_factor
    loading = flow / cap
    prob = 1.0 / (1.0 + math.exp(-12 * (loading - 0.82)))

    return {
        "flow_gw": round(flow, 2),
        "loading_pct": round(loading * 100, 1),
        "constraint_probability": round(min(prob, 0.99), 3),
        "risk_level": "HIGH" if prob > 0.6 else "MEDIUM" if prob > 0.3 else "LOW",
        "constraint_cost_gbp_mwh": boundary["constraint_cost_mwh"],
    }


def forecast_constraints(hours_ahead: int = 48, date: str = None,
                          wind_capacity_gw: float = 30,
                          solar_capacity_gw: float = 18) -> dict:
    """
    Forecast grid constraints for all boundaries over the next N hours.
    """
    if date:
        start = datetime.fromisoformat(date)
    else:
        start = datetime.now().replace(minute=0, second=0, microsecond=0)

    weather = _weather_forecast(start, hours_ahead)

    # Forecast per boundary
    boundary_forecasts = {}
    for b_id, b_data in BOUNDARIES.items():
        hourly = []
        for w in weather:
            loading = _boundary_loading(b_data, w)
            hourly.append({
                "hour_offset": w["hour_offset"],
                "datetime": w["datetime"],
                **loading,
            })
        boundary_forecasts[b_id] = {
            "name": b_data["name"],
            "capacity_gw": b_data["capacity_gw"],
            "hourly": hourly,
            "peak_loading_pct": round(max(h["loading_pct"] for h in hourly), 1),
            "peak_constraint_prob": round(max(h["constraint_probability"] for h in hourly), 3),
            "constrained_hours": sum(1 for h in hourly if h["constraint_probability"] > 0.5),
        }

    # System summary
    all_peaks = [bf["peak_constraint_prob"] for bf in boundary_forecasts.values()]
    total_constrained = sum(bf["constrained_hours"] for bf in boundary_forecasts.values())

    # Constraint windows (periods of sustained high risk)
    windows = []
    for b_id, bf in boundary_forecasts.items():
        in_window = False
        window_start = None
        for h in bf["hourly"]:
            if h["constraint_probability"] > 0.5 and not in_window:
                in_window = True
                window_start = h
            elif h["constraint_probability"] <= 0.5 and in_window:
                windows.append({
                    "boundary_id": b_id,
                    "boundary_name": bf["name"],
                    "start": window_start["datetime"],
                    "end": h["datetime"],
                    "peak_prob": round(max(
                        x["constraint_probability"]
                        for x in bf["hourly"]
                        if window_start["hour_offset"] <= x["hour_offset"] <= h["hour_offset"]
                    ), 3),
                    "duration_hours": h["hour_offset"] - window_start["hour_offset"],
                })
                in_window = False

    windows.sort(key=lambda w: -w["peak_prob"])

    return {
        "forecast_start": start.strftime("%Y-%m-%d %H:%M"),
        "hours_ahead": hours_ahead,
        "weather": weather,
        "boundaries": boundary_forecasts,
        "constraint_windows": windows[:15],
        "summary": {
            "max_system_constraint_prob": round(max(all_peaks), 3),
            "total_constrained_boundary_hours": total_constrained,
            "boundaries_at_risk": sum(1 for p in all_peaks if p > 0.5),
            "system_risk": "HIGH" if max(all_peaks) > 0.6 else "MEDIUM" if max(all_peaks) > 0.3 else "LOW",
        },
    }


def boundary_forecast(boundary_id: str = "B1", hours_ahead: int = 48,
                       date: str = None) -> dict:
    """Detailed forecast for a single boundary."""
    full = forecast_constraints(hours_ahead, date)
    bf = full["boundaries"].get(boundary_id)
    if not bf:
        return {"error": f"Unknown boundary: {boundary_id}"}
    return {
        "boundary_id": boundary_id,
        **bf,
        "weather": full["weather"],
    }


def constraint_windows(hours_ahead: int = 48, threshold: float = 0.5,
                        date: str = None) -> dict:
    """Extract constraint windows above threshold."""
    full = forecast_constraints(hours_ahead, date)
    filtered = [w for w in full["constraint_windows"] if w["peak_prob"] >= threshold]
    return {
        "threshold": threshold,
        "windows": filtered,
        "total_windows": len(filtered),
        "summary": full["summary"],
    }


# ── Subprocess bridge ──────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "forecast":
            result = forecast_constraints(
                hours_ahead=req.get("hours_ahead", 48),
                date=req.get("date"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "boundary_forecast":
            result = boundary_forecast(
                boundary_id=req.get("boundary_id", "B1"),
                hours_ahead=req.get("hours_ahead", 48),
                date=req.get("date"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "constraint_windows":
            result = constraint_windows(
                hours_ahead=req.get("hours_ahead", 48),
                threshold=req.get("threshold", 0.5),
                date=req.get("date"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()

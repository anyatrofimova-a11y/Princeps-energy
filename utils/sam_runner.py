#!/usr/bin/env python3
"""
SAM PvWattsv8 runner — standalone script for solar yield estimation.

Called as a subprocess from the FastAPI backend because PySAM requires
Python ≤3.12 (the main backend may run a newer interpreter).

Usage:
    python sam_runner.py --lat 52.5 --lon -1.5 --capacity_kw 100 \
                         --tilt 25 --azimuth 180 --losses 14

Prints a JSON object to stdout with annual energy, capacity factor,
monthly generation, and hourly generation profile.
"""

import argparse
import json
import os
import sys

import PySAM.Pvwattsv8 as pw


# Default weather file bundled with SAM repo (Phoenix, AZ).
# In production, replace with site-specific TMY data or NSRDB download.
DEFAULT_WEATHER = os.path.join(
    os.path.dirname(__file__),
    "..",
    "SAM",
    "deploy",
    "solar_resource",
    "phoenix_az_33.450495_-111.983688_psmv3_60_tmy.csv",
)

# UK-approximate synthetic approach: if no local weather file is found,
# we generate a simple weather dict with representative UK irradiance.
# For production, download from PVGIS or NSRDB.


def build_uk_synthetic_weather(lat: float, lon: float) -> dict:
    """
    Build a minimal synthetic weather dictionary for UK latitudes.
    PvWattsv8 accepts solar_resource_data as a dict with specific keys.
    This uses simplified UK-average irradiance patterns.
    """
    import math

    hours_per_year = 8760
    dn = []  # DNI
    df = []  # DHI
    gh = []  # GHI
    tdry = []  # temperature
    wspd = []  # wind speed
    year = []
    month = []
    day = []
    hour = []
    minute = []

    for h in range(hours_per_year):
        day_of_year = h // 24 + 1
        hour_of_day = h % 24

        # Simple solar elevation model
        decl = 23.45 * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
        hour_angle = (hour_of_day - 12) * 15
        sin_elev = (
            math.sin(math.radians(lat)) * math.sin(math.radians(decl))
            + math.cos(math.radians(lat))
            * math.cos(math.radians(decl))
            * math.cos(math.radians(hour_angle))
        )
        elev = max(0, math.degrees(math.asin(max(-1, min(1, sin_elev)))))

        # UK clearness index ~0.45 average
        clearness = 0.45
        # Extra-terrestrial irradiance
        ghi_ext = max(0, 1361 * sin_elev)
        ghi_val = ghi_ext * clearness if elev > 2 else 0
        # Split into DNI/DHI using Erbs model (simplified)
        if ghi_val > 0 and sin_elev > 0.05:
            kt = min(1.0, ghi_val / (1361 * sin_elev))
            if kt <= 0.22:
                dhi_frac = 1.0 - 0.09 * kt
            elif kt <= 0.80:
                dhi_frac = 0.9511 - 0.1604 * kt + 4.388 * kt**2 - 16.638 * kt**3 + 12.336 * kt**4
            else:
                dhi_frac = 0.165
            dhi_val = ghi_val * dhi_frac
            dni_val = (ghi_val - dhi_val) / max(0.05, sin_elev)
        else:
            dhi_val = 0
            dni_val = 0

        dn.append(max(0, dni_val))
        df.append(max(0, dhi_val))
        gh.append(max(0, ghi_val))

        # UK temperature: ~5-20C seasonal variation
        seasonal_t = 10 + 7 * math.sin(math.radians(360 / 365 * (day_of_year - 100)))
        diurnal_t = 3 * math.sin(math.radians(360 / 24 * (hour_of_day - 6)))
        tdry.append(seasonal_t + diurnal_t)
        wspd.append(4.5)  # UK average ~4.5 m/s

        # Date components
        import datetime
        dt = datetime.datetime(2023, 1, 1) + datetime.timedelta(hours=h)
        year.append(dt.year)
        month.append(dt.month)
        day.append(dt.day)
        hour.append(dt.hour)
        minute.append(0)

    return {
        "lat": lat,
        "lon": lon,
        "tz": 0,  # GMT
        "elev": 50,  # metres, UK average
        "year": year,
        "month": month,
        "day": day,
        "hour": hour,
        "minute": minute,
        "dn": dn,
        "df": df,
        "gh": gh,
        "tdry": tdry,
        "wspd": wspd,
    }


def run_pvwatts(
    lat: float,
    lon: float,
    capacity_kw: float,
    tilt: float = 25.0,
    azimuth: float = 180.0,
    losses: float = 14.0,
    module_type: int = 0,
    array_type: int = 0,
    dc_ac_ratio: float = 1.2,
    inv_eff: float = 96.0,
    gcr: float = 0.4,
    weather_file: str | None = None,
) -> dict:
    """Run PvWattsv8 and return results as a dict."""
    model = pw.new()

    # Weather data
    if weather_file and os.path.isfile(weather_file):
        model.SolarResource.solar_resource_file = weather_file
    else:
        # Use synthetic UK weather
        weather = build_uk_synthetic_weather(lat, lon)
        model.SolarResource.solar_resource_data = weather

    # System design
    model.SystemDesign.system_capacity = capacity_kw
    model.SystemDesign.module_type = module_type
    model.SystemDesign.dc_ac_ratio = dc_ac_ratio
    model.SystemDesign.array_type = array_type
    model.SystemDesign.azimuth = azimuth
    model.SystemDesign.tilt = tilt
    model.SystemDesign.losses = losses
    model.SystemDesign.inv_eff = inv_eff
    model.SystemDesign.gcr = gcr

    model.execute()

    # Extract outputs
    gen_hourly = list(model.Outputs.gen)  # 8760 values (kW)
    monthly = list(model.Outputs.monthly_energy)  # 12 values (kWh)

    return {
        "annual_energy_kwh": round(model.Outputs.annual_energy, 2),
        "capacity_factor_pct": round(model.Outputs.capacity_factor, 2),
        "annual_solar_radiation_kwh_m2_day": round(model.Outputs.solrad_annual, 3),
        "monthly_energy_kwh": [round(m, 2) for m in monthly],
        "hourly_gen_kw": [round(g, 4) for g in gen_hourly],
        "system": {
            "capacity_kw": capacity_kw,
            "tilt_deg": tilt,
            "azimuth_deg": azimuth,
            "losses_pct": losses,
            "module_type": module_type,
            "array_type": array_type,
            "dc_ac_ratio": dc_ac_ratio,
        },
        "location": {
            "lat": lat,
            "lon": lon,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="SAM PvWattsv8 solar yield estimator")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--capacity_kw", type=float, default=100.0)
    parser.add_argument("--tilt", type=float, default=25.0)
    parser.add_argument("--azimuth", type=float, default=180.0)
    parser.add_argument("--losses", type=float, default=14.0)
    parser.add_argument("--module_type", type=int, default=0)
    parser.add_argument("--array_type", type=int, default=0)
    parser.add_argument("--dc_ac_ratio", type=float, default=1.2)
    parser.add_argument("--inv_eff", type=float, default=96.0)
    parser.add_argument("--gcr", type=float, default=0.4)
    parser.add_argument("--weather_file", type=str, default=None)

    args = parser.parse_args()

    result = run_pvwatts(
        lat=args.lat,
        lon=args.lon,
        capacity_kw=args.capacity_kw,
        tilt=args.tilt,
        azimuth=args.azimuth,
        losses=args.losses,
        module_type=args.module_type,
        array_type=args.array_type,
        dc_ac_ratio=args.dc_ac_ratio,
        inv_eff=args.inv_eff,
        gcr=args.gcr,
        weather_file=args.weather_file,
    )

    # Print compact JSON (hourly is large — only include summary by default)
    summary = {k: v for k, v in result.items() if k != "hourly_gen_kw"}
    summary["hourly_gen_kw_count"] = len(result["hourly_gen_kw"])
    # Include hourly as a flat list (caller can truncate)
    summary["hourly_gen_kw"] = result["hourly_gen_kw"]

    json.dump(summary, sys.stdout)


if __name__ == "__main__":
    main()

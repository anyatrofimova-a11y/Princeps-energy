#!/usr/bin/env python3
"""pvlib runner — subprocess bridge for advanced PV simulation.

Run in .venv-grid/ (Python 3.12).
Needs: pip install pvlib

Usage: echo '{"action":"simulate","params":{...}}' | .venv-grid/bin/python utils/pvlib_runner.py
"""

import sys
import json
import logging
from datetime import datetime

log = logging.getLogger(__name__)


def simulate_pv(params: dict) -> dict:
    """Full PV simulation with CEC module/inverter database."""
    import pvlib
    from pvlib.pvsystem import PVSystem
    from pvlib.location import Location
    from pvlib.modelchain import ModelChain
    import pandas as pd

    lat = params["lat"]
    lon = params["lon"]
    capacity_kw = params.get("capacity_kw", 100)
    tilt = params.get("tilt", None)
    azimuth = params.get("azimuth", 180)
    year = params.get("year", 2023)

    loc = Location(lat, lon, tz="UTC")

    # Use optimal tilt if not specified
    if tilt is None:
        tilt = max(0, abs(lat) - 10)

    # Get TMY-like clearsky data for annual simulation
    times = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h", tz="UTC")
    cs = loc.get_clearsky(times)

    # Apply typical UK cloudiness factor (~0.45 clearness index)
    cloud_factor = params.get("cloud_factor", 0.45)
    cs["ghi"] *= cloud_factor
    cs["dni"] *= cloud_factor
    cs["dhi"] = cs["ghi"] * 0.6  # Diffuse fraction for cloudy UK

    # Use CEC module database
    module_db = pvlib.pvsystem.retrieve_sam("CECMod")
    module_name = params.get("module", "Canadian_Solar_Inc__CS6K_280M")
    if module_name not in module_db.columns:
        module_name = module_db.columns[0]
    module = module_db[module_name]

    inverter_db = pvlib.pvsystem.retrieve_sam("CECInverter")
    inverter_name = params.get("inverter", "ABB__MICRO_0_25_I_OUTD_US_208__208V_")
    if inverter_name not in inverter_db.columns:
        inverter_name = inverter_db.columns[0]
    inverter = inverter_db[inverter_name]

    # Scale system
    modules_per_string = int(capacity_kw * 1000 / module.get("STC", 280))
    system = PVSystem(
        surface_tilt=tilt, surface_azimuth=azimuth,
        module_parameters=module, inverter_parameters=inverter,
        modules_per_string=max(1, modules_per_string), strings_per_inverter=1,
    )

    mc = ModelChain(system, loc, aoi_model="physical", spectral_model="no_loss")
    mc.run_model(cs)

    ac_power = mc.results.ac
    if hasattr(ac_power, "values"):
        ac_hourly = [max(0, float(v)) / 1000 for v in ac_power.values]  # kW
    else:
        ac_hourly = []

    annual_kwh = sum(ac_hourly)
    capacity_factor = annual_kwh / (capacity_kw * 8760) if capacity_kw else 0

    return {
        "annual_kwh": round(annual_kwh, 1),
        "capacity_factor": round(capacity_factor * 100, 2),
        "monthly_kwh": [round(sum(ac_hourly[i * 730:(i + 1) * 730]), 1) for i in range(12)],
        "peak_kw": round(max(ac_hourly) if ac_hourly else 0, 1),
        "module": module_name,
        "tilt": tilt,
        "azimuth": azimuth,
    }


def bifacial_yield(params: dict) -> dict:
    """Estimate bifacial gain."""
    import pvlib

    lat = params["lat"]
    lon = params["lon"]
    albedo = params.get("albedo", 0.25)
    gcr = params.get("gcr", 0.4)
    height = params.get("height", 1.5)

    # Simplified bifacial gain estimation
    # Rear irradiance ~ albedo * GHI * view_factor
    view_factor = min(1.0, height / (height + 2.0)) * (1 - gcr)
    bifacial_gain_pct = albedo * view_factor * 100 * 0.7  # 70% of theoretical (cell efficiency)

    return {
        "bifacial_gain_pct": round(bifacial_gain_pct, 1),
        "albedo": albedo,
        "gcr": gcr,
        "height_m": height,
        "view_factor": round(view_factor, 3),
    }


def optimal_tilt(params: dict) -> dict:
    """Calculate optimal fixed tilt angle for a latitude."""
    lat = params["lat"]
    # Rule of thumb: optimal tilt ≈ latitude - 10° (for annual max)
    opt = max(0, abs(lat) - 10)
    # Summer optimum (June): latitude - 20°
    summer = max(0, abs(lat) - 20)
    # Winter optimum (Dec): latitude + 10°
    winter = min(90, abs(lat) + 10)

    return {
        "annual_optimal_tilt": round(opt, 1),
        "summer_optimal_tilt": round(summer, 1),
        "winter_optimal_tilt": round(winter, 1),
        "latitude": lat,
    }


def irradiance_components(params: dict) -> dict:
    """Decompose GHI into DNI and DHI at a location."""
    import pvlib
    from pvlib.location import Location
    import pandas as pd

    lat = params["lat"]
    lon = params["lon"]
    date = params.get("date", "2023-06-21")

    loc = Location(lat, lon, tz="UTC")
    times = pd.date_range(f"{date} 00:00", f"{date} 23:00", freq="h", tz="UTC")
    cs = loc.get_clearsky(times)

    cloud_factor = params.get("cloud_factor", 0.45)

    return {
        "date": date,
        "ghi_clear": [round(float(v), 1) for v in cs["ghi"].values],
        "dni_clear": [round(float(v), 1) for v in cs["dni"].values],
        "dhi_clear": [round(float(v), 1) for v in cs["dhi"].values],
        "ghi_typical": [round(float(v) * cloud_factor, 1) for v in cs["ghi"].values],
        "daily_ghi_kwh_m2": round(float(cs["ghi"].sum()) * cloud_factor / 1000, 2),
    }


ACTIONS = {
    "simulate": simulate_pv,
    "bifacial": bifacial_yield,
    "optimal_tilt": optimal_tilt,
    "irradiance": irradiance_components,
}


def main():
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    action = data.get("action")
    if action not in ACTIONS:
        json.dump({"error": f"Unknown action: {action}. Valid: {list(ACTIONS.keys())}"}, sys.stdout)
        return

    try:
        result = ACTIONS[action](data.get("params", {}))
        json.dump(result, sys.stdout, default=str)
    except Exception as e:
        json.dump({"error": str(e), "type": type(e).__name__}, sys.stdout)


if __name__ == "__main__":
    main()

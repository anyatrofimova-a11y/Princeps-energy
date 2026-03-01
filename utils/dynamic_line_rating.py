#!/usr/bin/env python3
"""
Dynamic Line Rating (DLR) calculator — Princeps Phase 7
IEEE 738 / CIGRE TB601 thermal rating model.
Calculates real-time ampacity based on weather conditions.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "rate", "conductor": "Lynx", "ambient_temp_c": 15, "wind_speed_ms": 2.0,
   "wind_angle_deg": 45, "solar_irradiance_wm2": 500}
  {"command": "rate_line", "voltage_kv": 132, "ambient_temp_c": 15, "wind_speed_ms": 2.0,
   "wind_angle_deg": 45, "solar_irradiance_wm2": 500}
  {"command": "seasonal_profile", "conductor": "Lynx", "lat": 52.0}
"""

import json
import math
import sys

# ─── UK overhead line conductor catalogue ────────────────────────────────────
# ACSR conductors commonly used on UK transmission/distribution
CONDUCTORS = {
    # name: {diameter_mm, resistance_ohm_per_km_20c, emissivity, absorptivity,
    #         static_rating_a, max_temp_c, weight_kg_per_m}
    "Lynx": {
        "diameter_mm": 19.53, "resistance_20c": 0.2733, "emissivity": 0.5,
        "absorptivity": 0.5, "static_rating_a": 535, "max_temp_c": 75,
        "weight_kg_m": 0.842, "voltage_kv": [33, 66],
    },
    "Zebra": {
        "diameter_mm": 28.62, "resistance_20c": 0.0684, "emissivity": 0.5,
        "absorptivity": 0.5, "static_rating_a": 830, "max_temp_c": 75,
        "weight_kg_m": 1.621, "voltage_kv": [132, 275],
    },
    "Rubus": {
        "diameter_mm": 31.77, "resistance_20c": 0.0561, "emissivity": 0.5,
        "absorptivity": 0.5, "static_rating_a": 960, "max_temp_c": 80,
        "weight_kg_m": 1.951, "voltage_kv": [275, 400],
    },
    "Matthew": {
        "diameter_mm": 36.25, "resistance_20c": 0.0427, "emissivity": 0.5,
        "absorptivity": 0.5, "static_rating_a": 1100, "max_temp_c": 80,
        "weight_kg_m": 2.556, "voltage_kv": [400],
    },
    "Araucaria": {
        "diameter_mm": 39.78, "resistance_20c": 0.0360, "emissivity": 0.5,
        "absorptivity": 0.5, "static_rating_a": 1260, "max_temp_c": 80,
        "weight_kg_m": 3.045, "voltage_kv": [400],
    },
}

# Default conductor by voltage level
VOLTAGE_CONDUCTOR = {
    11: "Lynx", 33: "Lynx", 66: "Lynx",
    132: "Zebra", 275: "Rubus", 400: "Matthew",
}

# ─── IEEE 738 steady-state thermal model ────────────────────────────────────

STEFAN_BOLTZMANN = 5.67e-8  # W/m²·K⁴
AIR_DENSITY_SEA = 1.225     # kg/m³ at sea level 15°C


def _air_properties(t_film_c: float) -> dict:
    """Dynamic viscosity + thermal conductivity of air at film temperature."""
    t_k = t_film_c + 273.15
    # Sutherland's law for viscosity
    mu = 1.458e-6 * t_k ** 1.5 / (t_k + 110.4)
    # Thermal conductivity approximation
    k = 0.0241 * (t_k / 293) ** 0.8
    return {"viscosity": mu, "conductivity": k}


def _convective_heat_loss(diameter_m: float, wind_speed: float, wind_angle_deg: float,
                          t_surface_c: float, t_ambient_c: float) -> float:
    """
    Convective heat loss per unit length (W/m).
    IEEE 738 Sections 4.4.3-4.4.5.
    """
    if wind_speed < 0.1:
        wind_speed = 0.1  # Natural convection minimum

    t_film = (t_surface_c + t_ambient_c) / 2.0
    air = _air_properties(t_film)
    rho = AIR_DENSITY_SEA * 288.15 / (t_film + 273.15)  # Ideal gas correction

    # Reynolds number
    re = rho * wind_speed * diameter_m / air["viscosity"]

    # Wind direction factor (Kangle)
    phi_rad = math.radians(wind_angle_deg)
    k_angle = 1.194 - math.cos(phi_rad) + 0.194 * math.cos(2 * phi_rad) + 0.368 * math.sin(2 * phi_rad)
    k_angle = max(k_angle, 0.388)  # Minimum for parallel wind

    # Forced convection (IEEE 738 Eq 3a/3b)
    if re < 1000:
        q_forced = k_angle * (1.01 + 1.35 * re ** 0.52) * air["conductivity"] * (t_surface_c - t_ambient_c)
    else:
        q_forced = k_angle * 0.754 * re ** 0.6 * air["conductivity"] * (t_surface_c - t_ambient_c)

    # Natural convection (IEEE 738 Eq 5)
    q_natural = 3.645 * rho ** 0.5 * diameter_m ** 0.75 * (t_surface_c - t_ambient_c) ** 1.25

    return max(q_forced, q_natural)


def _radiative_heat_loss(diameter_m: float, emissivity: float,
                         t_surface_c: float, t_ambient_c: float) -> float:
    """Radiative heat loss per unit length (W/m). IEEE 738 Eq 7."""
    t_s = t_surface_c + 273.15
    t_a = t_ambient_c + 273.15
    return math.pi * diameter_m * emissivity * STEFAN_BOLTZMANN * (t_s ** 4 - t_a ** 4)


def _solar_heat_gain(diameter_m: float, absorptivity: float,
                     solar_irradiance: float) -> float:
    """Solar heat gain per unit length (W/m). IEEE 738 Eq 8."""
    return absorptivity * solar_irradiance * diameter_m


def _resistance_at_temp(r_20c: float, temp_c: float) -> float:
    """Conductor AC resistance at temperature (per km). α = 0.00403 for aluminium."""
    alpha = 0.00403
    return r_20c * (1 + alpha * (temp_c - 20))


def calculate_ampacity(conductor_name: str, ambient_temp_c: float = 20.0,
                       wind_speed_ms: float = 0.5, wind_angle_deg: float = 45.0,
                       solar_irradiance_wm2: float = 0.0) -> dict:
    """
    Calculate dynamic thermal rating using IEEE 738.
    Returns ampacity (A), capacity (MW at given voltage), and uplift vs static.
    """
    cond = CONDUCTORS.get(conductor_name)
    if not cond:
        return {"error": f"Unknown conductor: {conductor_name}"}

    d_m = cond["diameter_mm"] / 1000.0
    t_max = cond["max_temp_c"]
    r_20c_per_km = cond["resistance_20c"]
    static_rating = cond["static_rating_a"]

    # Resistance at max operating temperature (per metre)
    r_per_m = _resistance_at_temp(r_20c_per_km, t_max) / 1000.0

    # Heat balance: I²R = q_conv + q_rad - q_solar
    q_conv = _convective_heat_loss(d_m, wind_speed_ms, wind_angle_deg, t_max, ambient_temp_c)
    q_rad = _radiative_heat_loss(d_m, cond["emissivity"], t_max, ambient_temp_c)
    q_solar = _solar_heat_gain(d_m, cond["absorptivity"], solar_irradiance_wm2)

    heat_dissipated = q_conv + q_rad - q_solar

    if heat_dissipated <= 0:
        # Solar gain exceeds cooling — conductor cannot operate at max temp
        ampacity = static_rating * 0.5
        limited = True
    else:
        ampacity = math.sqrt(heat_dissipated / r_per_m)
        limited = False

    uplift_pct = (ampacity / static_rating - 1) * 100 if static_rating > 0 else 0

    # MW capacity at typical voltages
    voltages = cond.get("voltage_kv", [132])
    capacities = {}
    for v in voltages:
        # P = √3 × V × I × pf (assume pf=0.95)
        mw = math.sqrt(3) * v * ampacity * 0.95 / 1000
        capacities[f"{v}kV"] = round(mw, 1)

    return {
        "conductor": conductor_name,
        "ampacity_a": round(ampacity, 1),
        "static_rating_a": static_rating,
        "uplift_pct": round(uplift_pct, 1),
        "limited_by_solar": limited,
        "max_temp_c": t_max,
        "conditions": {
            "ambient_temp_c": ambient_temp_c,
            "wind_speed_ms": wind_speed_ms,
            "wind_angle_deg": wind_angle_deg,
            "solar_irradiance_wm2": solar_irradiance_wm2,
        },
        "heat_balance_wm": {
            "convective": round(q_conv, 2),
            "radiative": round(q_rad, 2),
            "solar_gain": round(q_solar, 2),
            "net_cooling": round(heat_dissipated, 2),
        },
        "capacity_mw": capacities,
    }


def rate_line(voltage_kv: int, **kwargs) -> dict:
    """Rate a line by voltage level using default conductor."""
    conductor = VOLTAGE_CONDUCTOR.get(voltage_kv, "Zebra")
    return calculate_ampacity(conductor, **kwargs)


def seasonal_profile(conductor_name: str, lat: float = 52.0) -> dict:
    """
    Seasonal DLR profile showing uplift across typical UK conditions.
    Returns hourly ratings for summer/winter/spring day.
    """
    seasons = {
        "winter": {"temp_range": (-2, 6), "solar_peak": 200, "wind_mean": 5.0, "day_hours": (8, 16)},
        "spring": {"temp_range": (5, 14), "solar_peak": 600, "wind_mean": 3.5, "day_hours": (6, 19)},
        "summer": {"temp_range": (14, 25), "solar_peak": 850, "wind_mean": 2.5, "day_hours": (5, 21)},
    }

    profiles = {}
    for sname, sdata in seasons.items():
        hourly = []
        for hour in range(24):
            # Temperature: sinusoidal peak at 15:00
            t_range = sdata["temp_range"]
            t = t_range[0] + (t_range[1] - t_range[0]) * (0.5 + 0.5 * math.sin(math.pi * (hour - 6) / 12))

            # Solar: bell curve during daylight
            dawn, dusk = sdata["day_hours"]
            if dawn <= hour <= dusk:
                solar = sdata["solar_peak"] * max(0, math.sin(math.pi * (hour - dawn) / (dusk - dawn)))
            else:
                solar = 0

            # Wind: slightly higher at night
            wind = sdata["wind_mean"] * (1.1 - 0.2 * math.sin(math.pi * (hour - 6) / 12))
            wind = max(0.3, wind)

            result = calculate_ampacity(conductor_name, t, wind, 45, solar)
            hourly.append({
                "hour": hour,
                "ampacity_a": result["ampacity_a"],
                "static_rating_a": result["static_rating_a"],
                "uplift_pct": result["uplift_pct"],
                "ambient_temp_c": round(t, 1),
                "wind_speed_ms": round(wind, 1),
                "solar_wm2": round(solar, 0),
            })

        profiles[sname] = hourly

    return {
        "conductor": conductor_name,
        "lat": lat,
        "profiles": profiles,
        "summary": {
            s: {
                "min_uplift_pct": round(min(h["uplift_pct"] for h in hrs), 1),
                "max_uplift_pct": round(max(h["uplift_pct"] for h in hrs), 1),
                "mean_uplift_pct": round(sum(h["uplift_pct"] for h in hrs) / 24, 1),
            }
            for s, hrs in profiles.items()
        },
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
        if cmd == "rate":
            result = calculate_ampacity(
                req.get("conductor", "Zebra"),
                ambient_temp_c=req.get("ambient_temp_c", 20),
                wind_speed_ms=req.get("wind_speed_ms", 0.5),
                wind_angle_deg=req.get("wind_angle_deg", 45),
                solar_irradiance_wm2=req.get("solar_irradiance_wm2", 0),
            )
            json.dump(result, sys.stdout)

        elif cmd == "rate_line":
            result = rate_line(
                req.get("voltage_kv", 132),
                ambient_temp_c=req.get("ambient_temp_c", 20),
                wind_speed_ms=req.get("wind_speed_ms", 0.5),
                wind_angle_deg=req.get("wind_angle_deg", 45),
                solar_irradiance_wm2=req.get("solar_irradiance_wm2", 0),
            )
            json.dump(result, sys.stdout)

        elif cmd == "seasonal_profile":
            result = seasonal_profile(
                req.get("conductor", "Zebra"),
                lat=req.get("lat", 52.0),
            )
            json.dump(result, sys.stdout)

        elif cmd == "list_conductors":
            json.dump({
                "conductors": {
                    name: {
                        "diameter_mm": c["diameter_mm"],
                        "static_rating_a": c["static_rating_a"],
                        "max_temp_c": c["max_temp_c"],
                        "voltage_kv": c["voltage_kv"],
                    }
                    for name, c in CONDUCTORS.items()
                }
            }, sys.stdout)

        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)

    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()

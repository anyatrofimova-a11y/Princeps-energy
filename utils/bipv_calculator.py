"""
BIPV (Building-Integrated Photovoltaics) calculator.

Ported from SolarBIPV (github.com/tejas-raskar/SolarBIPV) and adapted
for UK locations with latitude-aware sun position and UK solar irradiance data.

Key calculations:
  - Sun position (altitude, azimuth) from date/time/location
  - Instantaneous GHI and DNI from monthly averages
  - Effective irradiance (direct + diffuse) accounting for angle of incidence
  - Instantaneous and daily/annual BIPV power generation
  - Shadow factor estimation based on roof pitch and obstructions
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# UK monthly solar irradiance data (kWh/m²/day)
# Source: PVGIS / Met Office — representative of central England (~52°N)
# ---------------------------------------------------------------------------

UK_MONTHLY_GHI = [0.70, 1.20, 2.20, 3.40, 4.30, 4.70, 4.50, 3.80, 2.70, 1.60, 0.85, 0.55]
UK_MONTHLY_DNI = [0.90, 1.50, 2.50, 3.30, 3.80, 3.90, 3.70, 3.20, 2.40, 1.40, 0.95, 0.70]

# NYC reference data from SolarBIPV (for validation/comparison)
NYC_MONTHLY_GHI = [2.0, 2.89, 3.91, 4.77, 5.51, 5.85, 5.85, 5.17, 4.3, 3.03, 2.08, 1.75]
NYC_MONTHLY_DNI = [3.23, 3.89, 3.91, 4.1, 4.16, 4.23, 4.32, 4.18, 4.1, 3.42, 2.79, 2.97]

# BIPV module types with typical efficiencies
BIPV_MODULES = {
    "mono_roof_tile": {
        "name": "Monocrystalline Roof Tile",
        "efficiency": 0.20,
        "cost_gbp_m2": 280,
        "weight_kg_m2": 12,
        "description": "Standard efficiency BIPV roof tiles, replace conventional tiles",
    },
    "thin_film_facade": {
        "name": "Thin-Film Facade Panel",
        "efficiency": 0.12,
        "cost_gbp_m2": 180,
        "weight_kg_m2": 8,
        "description": "Semi-transparent facade cladding, suitable for curtain walls",
    },
    "solar_glass": {
        "name": "Solar Glass (Transparent)",
        "efficiency": 0.08,
        "cost_gbp_m2": 350,
        "weight_kg_m2": 15,
        "description": "Transparent PV glazing for windows and skylights",
    },
    "colored_facade": {
        "name": "Coloured Facade Module",
        "efficiency": 0.15,
        "cost_gbp_m2": 250,
        "weight_kg_m2": 10,
        "description": "Aesthetically customisable facade panels in various colours",
    },
    "flexible_membrane": {
        "name": "Flexible PV Membrane",
        "efficiency": 0.14,
        "cost_gbp_m2": 150,
        "weight_kg_m2": 3,
        "description": "Lightweight flexible membrane for flat roofs and curved surfaces",
    },
    "shingle": {
        "name": "Solar Shingle",
        "efficiency": 0.18,
        "cost_gbp_m2": 320,
        "weight_kg_m2": 11,
        "description": "Replaces asphalt shingles with integrated PV cells",
    },
}

# Building surface types
SURFACE_TYPES = {
    "flat_roof": {"tilt_deg": 0, "azimuth_deg": 180, "shadow_factor": 0.05},
    "pitched_roof_south": {"tilt_deg": 35, "azimuth_deg": 180, "shadow_factor": 0.08},
    "pitched_roof_east": {"tilt_deg": 35, "azimuth_deg": 90, "shadow_factor": 0.12},
    "pitched_roof_west": {"tilt_deg": 35, "azimuth_deg": 270, "shadow_factor": 0.12},
    "pitched_roof_north": {"tilt_deg": 35, "azimuth_deg": 0, "shadow_factor": 0.25},
    "facade_south": {"tilt_deg": 90, "azimuth_deg": 180, "shadow_factor": 0.20},
    "facade_east": {"tilt_deg": 90, "azimuth_deg": 90, "shadow_factor": 0.30},
    "facade_west": {"tilt_deg": 90, "azimuth_deg": 270, "shadow_factor": 0.30},
    "facade_north": {"tilt_deg": 90, "azimuth_deg": 0, "shadow_factor": 0.50},
}


# ---------------------------------------------------------------------------
# Sun position calculations (replaces SunCalc.js)
# ---------------------------------------------------------------------------

def _julian_day(dt: datetime) -> float:
    """Julian day number from datetime."""
    a = (14 - dt.month) // 12
    y = dt.year + 4800 - a
    m = dt.month + 12 * a - 3
    jdn = dt.day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    return jdn + (dt.hour - 12) / 24.0 + dt.minute / 1440.0 + dt.second / 86400.0


def sun_position(lat: float, lon: float, dt: datetime) -> dict:
    """
    Calculate solar altitude and azimuth angles.

    Returns dict with altitude (radians), azimuth (radians),
    altitude_deg, azimuth_deg, and direction vector (x, y, z).
    """
    jd = _julian_day(dt)
    n = jd - 2451545.0  # days since J2000.0

    # Solar mean longitude and mean anomaly
    L = math.radians((280.460 + 0.9856474 * n) % 360)
    g = math.radians((357.528 + 0.9856003 * n) % 360)

    # Ecliptic longitude
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)

    # Obliquity of ecliptic
    eps = math.radians(23.439 - 0.0000004 * n)

    # Right ascension and declination
    sin_lam = math.sin(lam)
    cos_lam = math.cos(lam)
    ra = math.atan2(math.cos(eps) * sin_lam, cos_lam)
    dec = math.asin(math.sin(eps) * sin_lam)

    # Greenwich sidereal time
    gmst = (280.46061837 + 360.98564736629 * n) % 360
    lst = math.radians(gmst + lon)

    # Hour angle
    ha = lst - ra

    # Altitude
    lat_r = math.radians(lat)
    sin_alt = (math.sin(lat_r) * math.sin(dec) +
               math.cos(lat_r) * math.cos(dec) * math.cos(ha))
    altitude = math.asin(max(-1, min(1, sin_alt)))

    # Azimuth (from north, clockwise)
    cos_az = ((math.sin(dec) - math.sin(altitude) * math.sin(lat_r)) /
              (math.cos(altitude) * math.cos(lat_r) + 1e-10))
    cos_az = max(-1, min(1, cos_az))
    azimuth = math.acos(cos_az)
    if math.sin(ha) > 0:
        azimuth = 2 * math.pi - azimuth

    # Direction vector (matching SolarBIPV convention)
    x = math.cos(altitude) * math.sin(azimuth)
    y = math.sin(altitude)
    z = math.cos(azimuth) * math.cos(altitude)
    norm = math.sqrt(x * x + y * y + z * z) or 1
    direction = (x / norm, y / norm, z / norm)

    return {
        "altitude": altitude,
        "azimuth": azimuth,
        "altitude_deg": math.degrees(altitude),
        "azimuth_deg": math.degrees(azimuth),
        "direction": direction,
    }


def max_solar_altitude(lat: float) -> float:
    """Maximum solar altitude angle (radians) at summer solstice."""
    return math.radians(90 - lat + 23.5)


# ---------------------------------------------------------------------------
# Irradiance calculations
# ---------------------------------------------------------------------------

def instantaneous_irradiance(
    lat: float,
    lon: float,
    dt: datetime,
    monthly_ghi: list[float] | None = None,
    monthly_dni: list[float] | None = None,
) -> dict:
    """
    Calculate instantaneous GHI and DNI (W/m²) from monthly averages.

    Follows the SolarBIPV approach: scale monthly average by sin(altitude)/sin(max_altitude).
    """
    ghi_data = monthly_ghi or UK_MONTHLY_GHI
    dni_data = monthly_dni or UK_MONTHLY_DNI

    month_idx = dt.month - 1
    ghi_daily = ghi_data[month_idx]
    dni_daily = dni_data[month_idx]

    sp = sun_position(lat, lon, dt)
    altitude = sp["altitude"]
    max_alt = max_solar_altitude(lat)

    if altitude <= 0:
        return {
            "ghi_wm2": 0.0,
            "dni_wm2": 0.0,
            "ghi_daily_kwh": ghi_daily,
            "dni_daily_kwh": dni_daily,
            "sun": sp,
        }

    ghi_instant = (ghi_daily * math.sin(altitude) / math.sin(max_alt)) * 1000 / 24
    dni_instant = dni_daily * 1000 / 24

    return {
        "ghi_wm2": round(ghi_instant, 2),
        "dni_wm2": round(dni_instant, 2),
        "ghi_daily_kwh": ghi_daily,
        "dni_daily_kwh": dni_daily,
        "sun": sp,
    }


# ---------------------------------------------------------------------------
# BIPV power calculation
# ---------------------------------------------------------------------------

def calculate_bipv(
    lat: float,
    lon: float,
    dt: datetime,
    area_m2: float,
    module_type: str = "mono_roof_tile",
    surface_type: str = "pitched_roof_south",
    shadow_factor: float | None = None,
    efficiency_override: float | None = None,
) -> dict:
    """
    Calculate instantaneous BIPV power output.

    Ported from SolarBIPV calculateBIPV() with UK adaptations:
    - Uses UK monthly GHI/DNI data
    - Accounts for surface tilt and orientation
    - Uses predefined shadow factors per surface type

    Args:
        lat, lon: Location coordinates
        dt: Datetime (UTC)
        area_m2: Active BIPV surface area
        module_type: Key from BIPV_MODULES
        surface_type: Key from SURFACE_TYPES
        shadow_factor: Override shadow fraction (0=no shadow, 1=full shadow)
        efficiency_override: Override module efficiency

    Returns:
        Dict with power, irradiance, and component details
    """
    module = BIPV_MODULES.get(module_type, BIPV_MODULES["mono_roof_tile"])
    surface = SURFACE_TYPES.get(surface_type, SURFACE_TYPES["pitched_roof_south"])
    efficiency = efficiency_override if efficiency_override is not None else module["efficiency"]
    sf = shadow_factor if shadow_factor is not None else surface["shadow_factor"]

    irr = instantaneous_irradiance(lat, lon, dt)
    ghi = irr["ghi_wm2"]
    dni = irr["dni_wm2"]
    sp = irr["sun"]

    # Angle of incidence: dot product of surface normal and sun direction
    tilt_rad = math.radians(surface["tilt_deg"])
    az_rad = math.radians(surface["azimuth_deg"])

    # Surface normal vector
    nx = math.sin(tilt_rad) * math.sin(az_rad)
    ny = math.cos(tilt_rad)
    nz = math.sin(tilt_rad) * math.cos(az_rad)

    # Sun direction
    sx, sy, sz = sp["direction"]

    cos_theta = max(0.0, nx * sx + ny * sy + nz * sz)

    # Effective irradiance (matching SolarBIPV formula)
    direct = dni * cos_theta * (1 - sf)
    diffuse = ghi * 0.2  # 20% of GHI as diffuse component
    effective = direct + diffuse

    # Instantaneous power
    power_w = effective * area_m2 * efficiency
    power_kw = power_w / 1000

    return {
        "power_w": round(power_w, 1),
        "power_kw": round(power_kw, 3),
        "effective_irradiance_wm2": round(effective, 2),
        "direct_irradiance_wm2": round(direct, 2),
        "diffuse_irradiance_wm2": round(diffuse, 2),
        "ghi_wm2": round(ghi, 2),
        "dni_wm2": round(dni, 2),
        "cos_theta": round(cos_theta, 4),
        "shadow_factor": round(sf, 3),
        "efficiency": efficiency,
        "area_m2": area_m2,
        "module": module_type,
        "surface": surface_type,
        "sun_altitude_deg": round(sp["altitude_deg"], 2),
        "sun_azimuth_deg": round(sp["azimuth_deg"], 2),
    }


def bipv_24h_profile(
    lat: float,
    lon: float,
    date_str: str,
    area_m2: float,
    module_type: str = "mono_roof_tile",
    surface_type: str = "pitched_roof_south",
    shadow_factor: float | None = None,
) -> dict:
    """
    Calculate 24-hour BIPV power profile (hourly values).

    Returns hourly power, total daily energy, and peak power.
    """
    year, month, day = map(int, date_str.split("-"))
    hourly_power_w = []
    hourly_irradiance = []

    for hour in range(24):
        dt = datetime(year, month, day, hour, 30, tzinfo=timezone.utc)
        result = calculate_bipv(
            lat, lon, dt, area_m2,
            module_type=module_type,
            surface_type=surface_type,
            shadow_factor=shadow_factor,
        )
        hourly_power_w.append(round(result["power_w"], 1))
        hourly_irradiance.append(round(result["effective_irradiance_wm2"], 2))

    daily_energy_wh = sum(hourly_power_w)
    daily_energy_kwh = round(daily_energy_wh / 1000, 2)
    peak_power_w = max(hourly_power_w)
    peak_hour = hourly_power_w.index(peak_power_w)

    return {
        "hourly_power_w": hourly_power_w,
        "hourly_irradiance_wm2": hourly_irradiance,
        "daily_energy_kwh": daily_energy_kwh,
        "peak_power_w": round(peak_power_w, 1),
        "peak_hour": peak_hour,
    }


def bipv_annual_estimate(
    lat: float,
    lon: float,
    area_m2: float,
    module_type: str = "mono_roof_tile",
    surface_type: str = "pitched_roof_south",
    shadow_factor: float | None = None,
) -> dict:
    """
    Estimate annual BIPV generation using monthly representative days.

    Returns monthly and annual energy estimates, plus financial projections.
    """
    module = BIPV_MODULES.get(module_type, BIPV_MODULES["mono_roof_tile"])
    days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    mid_days = [15, 14, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15]

    monthly_kwh = []
    for m in range(12):
        date_str = f"2025-{m + 1:02d}-{mid_days[m]:02d}"
        profile = bipv_24h_profile(
            lat, lon, date_str, area_m2,
            module_type=module_type,
            surface_type=surface_type,
            shadow_factor=shadow_factor,
        )
        month_kwh = profile["daily_energy_kwh"] * days_in_month[m]
        monthly_kwh.append(round(month_kwh, 1))

    annual_kwh = round(sum(monthly_kwh), 1)

    # Financial estimates (UK context)
    seg_tariff_p_kwh = 5.5  # pence/kWh SEG tariff
    install_cost = area_m2 * module["cost_gbp_m2"]
    annual_revenue = annual_kwh * seg_tariff_p_kwh / 100
    payback_years = round(install_cost / annual_revenue, 1) if annual_revenue > 0 else None

    # Self-consumption savings (assume 30% self-consumed at 30p/kWh import tariff)
    self_consumption_pct = 0.30
    import_tariff_p = 30
    savings = annual_kwh * self_consumption_pct * import_tariff_p / 100
    total_annual_benefit = annual_revenue * (1 - self_consumption_pct) + savings

    return {
        "monthly_kwh": monthly_kwh,
        "annual_kwh": annual_kwh,
        "peak_capacity_kw": round(area_m2 * module["efficiency"] * 1.0, 2),  # at 1 kW/m² STC
        "install_cost_gbp": round(install_cost),
        "annual_export_revenue_gbp": round(annual_revenue),
        "annual_self_consumption_savings_gbp": round(savings),
        "total_annual_benefit_gbp": round(total_annual_benefit),
        "payback_years": payback_years,
        "co2_avoided_kg_yr": round(annual_kwh * 0.207),  # UK grid factor 2024
        "module": module,
        "surface_type": surface_type,
    }


def bipv_multi_surface(
    lat: float,
    lon: float,
    surfaces: list[dict[str, Any]],
    module_type: str = "mono_roof_tile",
) -> dict:
    """
    Analyse multiple building surfaces for BIPV potential.

    Each surface dict: {"type": "pitched_roof_south", "area_m2": 100, ...}

    Returns per-surface and aggregate results.
    """
    results = []
    total_annual_kwh = 0
    total_cost = 0
    total_area = 0
    total_co2 = 0

    for surf in surfaces:
        stype = surf.get("type", "pitched_roof_south")
        area = surf.get("area_m2", 0)
        sf = surf.get("shadow_factor")
        mt = surf.get("module_type", module_type)

        est = bipv_annual_estimate(lat, lon, area, module_type=mt, surface_type=stype, shadow_factor=sf)
        results.append({
            "surface_type": stype,
            "area_m2": area,
            "module_type": mt,
            "annual_kwh": est["annual_kwh"],
            "install_cost_gbp": est["install_cost_gbp"],
            "payback_years": est["payback_years"],
        })
        total_annual_kwh += est["annual_kwh"]
        total_cost += est["install_cost_gbp"]
        total_area += area
        total_co2 += est["co2_avoided_kg_yr"]

    total_benefit = total_annual_kwh * 0.055 * 0.7 + total_annual_kwh * 0.30 * 0.30
    payback = round(total_cost / total_benefit, 1) if total_benefit > 0 else None

    return {
        "surfaces": results,
        "totals": {
            "total_area_m2": round(total_area, 1),
            "total_annual_kwh": round(total_annual_kwh, 1),
            "total_install_cost_gbp": round(total_cost),
            "combined_payback_years": payback,
            "co2_avoided_kg_yr": round(total_co2),
        },
    }


def bipv_catalogue() -> dict:
    """Return available BIPV module types and building surface types."""
    return {
        "modules": {k: {**v} for k, v in BIPV_MODULES.items()},
        "surface_types": {k: {**v} for k, v in SURFACE_TYPES.items()},
    }

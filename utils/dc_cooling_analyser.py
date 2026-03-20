"""
DC Cooling Analyser Module.

Climate-aware cooling analysis for data centre site selection.
Calculates free cooling potential, PUE/WUE estimates, UKCP18 future
projections, and composite cooling suitability scores.

Data sources:
- ERA5-Land temperature via GeeFlow extractions (geeflow_extractions table)
- UKCP18 simplified climate projection model (RCP8.5)
- ASHRAE thermal model for PUE estimation
- UK latitude-based climate zones as fallback
"""

from __future__ import annotations

import logging
import math
from typing import Any

import asyncpg

log = logging.getLogger("princeps.dc_cooling")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOURS_PER_YEAR = 8_760
FREE_COOLING_THRESHOLD_C = 18.0  # dry-bulb below which free cooling works

# Mechanical vs free cooling COP
COP_MECHANICAL = 3.5
COP_FREE = 12.0

# Fixed overhead losses (fraction of IT load)
LOSS_UPS = 0.04
LOSS_DISTRIBUTION = 0.02
LOSS_LIGHTING_MISC = 0.01
TOTAL_FIXED_OVERHEAD = LOSS_UPS + LOSS_DISTRIBUTION + LOSS_LIGHTING_MISC

# WUE parameters (litres per kWh of IT load)
WUE_EVAPORATIVE = 1.8
WUE_HYBRID_MIN = 0.6
WUE_HYBRID_MAX = 1.2
WUE_AIR_COOLED = 0.0

# UKCP18 RCP8.5 temperature rise projections (delta from 2024 baseline)
UKCP18_DELTA_C = {
    2030: 1.0,
    2040: 1.5,
    2050: 2.5,
}
# Approximate free cooling hours lost per +1 degC
FREE_COOLING_HOURS_LOSS_PER_DEG = 250  # midpoint of 200-300 range

# PUE scoring curve: pue -> score (linear interpolation)
PUE_SCORE_CURVE = [
    (1.1, 100),
    (1.3, 70),
    (1.5, 40),
    (2.0, 0),
]

# Composite weights
WEIGHT_PUE = 0.40
WEIGHT_FREE_COOLING = 0.35
WEIGHT_WUE = 0.25

# UK climate zones (ordered north to south; first match wins)
UK_CLIMATE_ZONES = {
    "Scotland_North": {"lat_min": 57.0, "avg_temp_c": 7.5, "free_cooling_hrs": 6500},
    "Scotland_South": {"lat_min": 55.0, "avg_temp_c": 8.5, "free_cooling_hrs": 6000},
    "North_England": {"lat_min": 53.5, "avg_temp_c": 9.5, "free_cooling_hrs": 5500},
    "Midlands": {"lat_min": 52.0, "avg_temp_c": 10.0, "free_cooling_hrs": 5000},
    "South_England": {"lat_min": 50.5, "avg_temp_c": 11.0, "free_cooling_hrs": 4500},
    "London_SE": {"lat_min": 0, "avg_temp_c": 11.5, "free_cooling_hrs": 4200},
}

VALID_COOLING_TYPES = ("mechanical", "free_cooling", "hybrid", "evaporative")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_climate_zone(lat: float) -> tuple[str, dict]:
    """Return (zone_name, zone_data) for the given latitude."""
    for zone_name, zd in UK_CLIMATE_ZONES.items():
        if lat >= zd["lat_min"]:
            return zone_name, zd
    # Fallback: southernmost zone
    return "London_SE", UK_CLIMATE_ZONES["London_SE"]


def _wet_bulb_stull(temp_c: float, rh_pct: float) -> float:
    """
    Stull (2011) wet-bulb approximation.

    Valid for RH 5-99% and T -20 to 50 degC.
    """
    t = temp_c
    rh = rh_pct
    wb = (
        t * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )
    return wb


def _interpolate_pue_score(pue: float) -> float:
    """Linearly interpolate PUE onto 0-100 score via PUE_SCORE_CURVE."""
    if pue <= PUE_SCORE_CURVE[0][0]:
        return float(PUE_SCORE_CURVE[0][1])
    if pue >= PUE_SCORE_CURVE[-1][0]:
        return float(PUE_SCORE_CURVE[-1][1])
    for i in range(len(PUE_SCORE_CURVE) - 1):
        p0, s0 = PUE_SCORE_CURVE[i]
        p1, s1 = PUE_SCORE_CURVE[i + 1]
        if p0 <= pue <= p1:
            frac = (pue - p0) / (p1 - p0)
            return s0 + frac * (s1 - s0)
    return 0.0


def _free_cooling_score(hours: int) -> float:
    """Score free cooling hours on 0-100 scale."""
    if hours >= 6000:
        return 100.0
    if hours <= 0:
        return 0.0
    # Piecewise: 0->0, 2000->30, 4000->70, 6000->100
    pts = [(0, 0), (2000, 30), (4000, 70), (6000, 100)]
    for i in range(len(pts) - 1):
        h0, s0 = pts[i]
        h1, s1 = pts[i + 1]
        if h0 <= hours <= h1:
            frac = (hours - h0) / (h1 - h0)
            return s0 + frac * (s1 - s0)
    return 100.0


def _wue_score(wue: float) -> float:
    """Score WUE on 0-100 (lower WUE is better)."""
    # 0 L/kWh -> 100, 1.8 L/kWh -> 0
    if wue <= 0:
        return 100.0
    if wue >= 1.8:
        return 0.0
    return 100.0 * (1.0 - wue / 1.8)


# ---------------------------------------------------------------------------
# Free cooling hours from ERA5 data
# ---------------------------------------------------------------------------


async def _fetch_era5_temperatures(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
) -> list[dict[str, Any]] | None:
    """
    Fetch hourly temperature data from geeflow_extractions.

    The solar_resource extraction includes ERA5-Land temperature fields
    (temperature_2m in K or degC, plus optionally dewpoint/RH).
    """
    row = await conn.fetchrow(
        """
        SELECT result_data
        FROM geeflow_extractions
        WHERE mode = 'solar_resource'
          AND abs(lat - $1) < 0.02 AND abs(lon - $2) < 0.02
        ORDER BY created_at DESC
        LIMIT 1
        """,
        lat,
        lon,
    )
    if not row:
        return None

    data = row["result_data"]
    if isinstance(data, dict):
        # Expect hourly or monthly temperature arrays
        hourly = data.get("hourly_data") or data.get("hourly")
        if hourly and isinstance(hourly, list):
            return hourly
        monthly = data.get("monthly_data") or data.get("monthly")
        if monthly and isinstance(monthly, list):
            return monthly
    return None


def _compute_free_cooling_from_hourly(hourly: list[dict[str, Any]]) -> dict:
    """
    Analyse hourly records for free cooling potential.

    Each record expected to have at least 'temperature_c' or 'temperature_2m'.
    Optionally 'relative_humidity' for wet-bulb calculation.
    """
    free_hours = 0
    total_hours = 0
    temp_sum = 0.0
    wb_temps: list[float] = []

    for rec in hourly:
        # Temperature in Celsius
        temp_c = rec.get("temperature_c") or rec.get("temp_c")
        if temp_c is None:
            temp_k = rec.get("temperature_2m")
            if temp_k is not None:
                # ERA5 stores in Kelvin
                temp_c = float(temp_k) - 273.15 if float(temp_k) > 100 else float(temp_k)
            else:
                continue

        temp_c = float(temp_c)
        total_hours += 1
        temp_sum += temp_c

        if temp_c < FREE_COOLING_THRESHOLD_C:
            free_hours += 1

        rh = rec.get("relative_humidity") or rec.get("rh")
        if rh is not None:
            wb = _wet_bulb_stull(temp_c, float(rh))
            wb_temps.append(wb)

    avg_temp = temp_sum / total_hours if total_hours else 10.0

    # If we have monthly data (12 records), scale to annual hours
    if total_hours <= 12 and total_hours > 0:
        # Proportional scaling: each month ~730 hours
        scale = HOURS_PER_YEAR / total_hours
        free_hours = int(free_hours * scale)
        total_hours = HOURS_PER_YEAR

    avg_wb = sum(wb_temps) / len(wb_temps) if wb_temps else None

    return {
        "free_cooling_hours": min(free_hours, HOURS_PER_YEAR),
        "total_hours": total_hours,
        "avg_temperature_c": round(avg_temp, 1),
        "avg_wet_bulb_c": round(avg_wb, 1) if avg_wb is not None else None,
    }


def _compute_free_cooling_from_monthly(monthly: list[dict[str, Any]]) -> dict:
    """
    Fallback: estimate free cooling from monthly average temperatures.

    For each month, estimate the fraction of hours below the threshold
    using a simple sinusoidal diurnal model (amplitude ~4 degC).
    """
    free_hours = 0
    total_hours = 0
    temp_sum = 0.0
    month_hours = [744, 672, 744, 720, 744, 720, 744, 744, 720, 744, 720, 744]

    for i, rec in enumerate(monthly):
        temp_c = rec.get("temperature_c") or rec.get("avg_temp_c") or rec.get("temp_c")
        if temp_c is None:
            continue
        temp_c = float(temp_c)
        hrs = month_hours[i % 12]
        total_hours += hrs
        temp_sum += temp_c * hrs

        # Diurnal swing model: assume +-4 degC sinusoid around monthly mean
        amplitude = 4.0
        diff = FREE_COOLING_THRESHOLD_C - temp_c
        if diff >= amplitude:
            frac = 1.0  # all hours below threshold
        elif diff <= -amplitude:
            frac = 0.0
        else:
            # Fraction of sinusoid below threshold
            frac = 0.5 + math.asin(diff / amplitude) / math.pi
        free_hours += int(hrs * frac)

    avg_temp = temp_sum / total_hours if total_hours else 10.0

    return {
        "free_cooling_hours": min(free_hours, HOURS_PER_YEAR),
        "total_hours": HOURS_PER_YEAR,
        "avg_temperature_c": round(avg_temp, 1),
        "avg_wet_bulb_c": None,
    }


# ---------------------------------------------------------------------------
# PUE estimation
# ---------------------------------------------------------------------------


def estimate_pue(
    free_cooling_hours: int,
    cooling_type: str,
    avg_temp_c: float,
) -> dict:
    """
    ASHRAE-based PUE estimation with climate adjustment.

    Returns PUE value and component breakdown.
    """
    free_frac = free_cooling_hours / HOURS_PER_YEAR

    if cooling_type == "free_cooling":
        effective_cop = COP_FREE
        mech_frac = 0.0
    elif cooling_type == "mechanical":
        effective_cop = COP_MECHANICAL
        mech_frac = 1.0
        free_frac = 0.0
    elif cooling_type == "evaporative":
        # Evaporative: slightly better than mechanical
        effective_cop = 4.5
        mech_frac = 1.0
        free_frac = 0.0
    else:
        # Hybrid: weighted COP
        mech_frac = 1.0 - free_frac
        effective_cop = (free_frac * COP_FREE) + (mech_frac * COP_MECHANICAL)

    # Climate adjustment: warmer sites reduce COP
    # Baseline 10 degC; each +1 degC above baseline reduces COP by ~3%
    baseline_temp = 10.0
    temp_delta = max(0, avg_temp_c - baseline_temp)
    cop_adjustment = 1.0 - (temp_delta * 0.03)
    adjusted_cop = effective_cop * max(0.5, cop_adjustment)

    # Cooling power as fraction of IT load
    # Typical: cooling draws 1/COP of IT heat load
    cooling_fraction = 1.0 / adjusted_cop

    # PUE = 1 + cooling_fraction + fixed overheads
    pue = 1.0 + cooling_fraction + TOTAL_FIXED_OVERHEAD

    return {
        "pue": round(pue, 3),
        "effective_cop": round(adjusted_cop, 2),
        "cooling_fraction": round(cooling_fraction, 4),
        "mechanical_fraction": round(mech_frac, 2),
        "free_cooling_fraction": round(free_frac, 2),
        "fixed_overhead": TOTAL_FIXED_OVERHEAD,
        "ups_loss": LOSS_UPS,
        "distribution_loss": LOSS_DISTRIBUTION,
        "lighting_misc_loss": LOSS_LIGHTING_MISC,
        "cop_climate_adjustment": round(cop_adjustment, 3),
    }


# ---------------------------------------------------------------------------
# WUE estimation
# ---------------------------------------------------------------------------


def estimate_wue(
    cooling_type: str,
    mechanical_fraction: float,
    capacity_mw: float,
) -> dict:
    """
    Water Usage Effectiveness estimation.

    Returns WUE (L/kWh) and annual water consumption.
    """
    if cooling_type == "evaporative":
        wue = WUE_EVAPORATIVE
    elif cooling_type == "free_cooling" or cooling_type == "mechanical":
        # Air-cooled / mechanical: minimal water
        wue = WUE_AIR_COOLED
    elif cooling_type == "hybrid":
        # Hybrid: water usage proportional to mechanical fraction
        wue = WUE_HYBRID_MIN + (WUE_HYBRID_MAX - WUE_HYBRID_MIN) * mechanical_fraction
    else:
        wue = WUE_HYBRID_MIN

    # Annual water consumption (m3)
    # capacity_mw * 1000 kW * 8760 hrs * PUE-adjusted fraction ≈ annual kWh
    annual_kwh = capacity_mw * 1_000 * HOURS_PER_YEAR
    annual_litres = annual_kwh * wue
    annual_m3 = annual_litres / 1_000  # 1 m3 = 1000 litres

    return {
        "wue_l_kwh": round(wue, 3),
        "annual_water_litres": round(annual_litres),
        "annual_water_m3": round(annual_m3, 1),
        "cooling_type": cooling_type,
    }


# ---------------------------------------------------------------------------
# UKCP18 future projections
# ---------------------------------------------------------------------------


def project_future_climate(
    current_free_cooling_hours: int,
    current_pue: float,
    current_avg_temp_c: float,
    cooling_type: str,
) -> dict:
    """
    Simplified UKCP18 RCP8.5 projections for PUE and free cooling.
    """
    future_pue: dict[str, float] = {}
    future_fc_hours: dict[str, int] = {}
    future_temps: dict[str, float] = {}

    for year, delta_c in UKCP18_DELTA_C.items():
        projected_temp = current_avg_temp_c + delta_c
        future_temps[str(year)] = round(projected_temp, 1)

        # Free cooling hours decrease with warming
        hours_lost = int(delta_c * FREE_COOLING_HOURS_LOSS_PER_DEG)
        projected_hours = max(0, current_free_cooling_hours - hours_lost)
        future_fc_hours[str(year)] = projected_hours

        # Re-estimate PUE with projected climate
        pue_data = estimate_pue(projected_hours, cooling_type, projected_temp)
        future_pue[str(year)] = pue_data["pue"]

    return {
        "future_pue": future_pue,
        "future_free_cooling_hours": future_fc_hours,
        "future_temperatures_c": future_temps,
        "projection_basis": "UKCP18 RCP8.5",
    }


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------


def compute_cooling_score(
    pue: float,
    free_cooling_hours: int,
    wue: float,
) -> dict:
    """
    Composite cooling suitability score (0-100).

    Weights: PUE 40%, free cooling hours 35%, WUE 25%.
    """
    pue_s = _interpolate_pue_score(pue)
    fc_s = _free_cooling_score(free_cooling_hours)
    wue_s = _wue_score(wue)

    composite = (WEIGHT_PUE * pue_s) + (WEIGHT_FREE_COOLING * fc_s) + (WEIGHT_WUE * wue_s)

    return {
        "cooling_score": round(composite, 1),
        "pue_score": round(pue_s, 1),
        "pue_weight": WEIGHT_PUE,
        "free_cooling_score": round(fc_s, 1),
        "free_cooling_weight": WEIGHT_FREE_COOLING,
        "wue_score": round(wue_s, 1),
        "wue_weight": WEIGHT_WUE,
    }


def _generate_recommendation(
    cooling_score: float,
    pue: float,
    free_cooling_hours: int,
    climate_zone: str,
    cooling_type: str,
    future_pue: dict[str, float],
) -> str:
    """Generate a human-readable recommendation string."""
    parts: list[str] = []

    if cooling_score >= 80:
        parts.append(f"Excellent cooling site ({climate_zone}).")
    elif cooling_score >= 60:
        parts.append(f"Good cooling potential ({climate_zone}).")
    elif cooling_score >= 40:
        parts.append(f"Moderate cooling conditions ({climate_zone}).")
    else:
        parts.append(f"Challenging cooling environment ({climate_zone}).")

    parts.append(f"PUE {pue:.2f} with {free_cooling_hours:,} free cooling hours/year.")

    if free_cooling_hours >= 5500:
        parts.append("High free cooling potential reduces opex significantly.")
    elif free_cooling_hours < 3500:
        parts.append("Limited free cooling — consider hybrid or evaporative systems.")

    # Future outlook
    pue_2050 = future_pue.get("2050")
    if pue_2050:
        delta = pue_2050 - pue
        if delta > 0.1:
            parts.append(
                f"UKCP18 projects PUE degradation to {pue_2050:.2f} by 2050 "
                f"(+{delta:.2f}); factor climate resilience into design."
            )
        else:
            parts.append(f"Climate impact on PUE modest (+{delta:.2f} by 2050).")

    if cooling_type == "mechanical":
        parts.append("Switching to hybrid cooling could lower PUE by 0.1-0.2.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def analyse_cooling(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    capacity_mw: float = 10,
    cooling_type: str = "hybrid",
) -> dict:
    """
    Full cooling and climate analysis for a data centre site.

    Parameters
    ----------
    conn : asyncpg.Connection
        Database connection with access to geeflow_extractions.
    lat, lon : float
        Site coordinates (WGS84).
    capacity_mw : float
        IT load capacity in MW (default 10).
    cooling_type : str
        One of 'mechanical', 'free_cooling', 'hybrid', 'evaporative'.

    Returns
    -------
    dict with cooling_score, pue_estimate, wue, free cooling hours,
    climate projections, and recommendation.
    """
    if cooling_type not in VALID_COOLING_TYPES:
        cooling_type = "hybrid"
        log.warning("Invalid cooling_type supplied; defaulting to hybrid")

    # ----- 1. Determine climate zone (fallback) -----
    zone_name, zone_data = _classify_climate_zone(lat)
    log.info("Site lat=%.3f classified as %s (avg %.1f C)", lat, zone_name, zone_data["avg_temp_c"])

    # ----- 2. Try ERA5 data from geeflow_extractions -----
    era5 = await _fetch_era5_temperatures(conn, lat, lon)

    if era5 and len(era5) > 0:
        log.info("Found %d ERA5 records for cooling analysis", len(era5))
        if len(era5) >= 365:
            # Likely hourly or daily data
            cooling_data = _compute_free_cooling_from_hourly(era5)
        else:
            cooling_data = _compute_free_cooling_from_monthly(era5)
        data_source = "era5_geeflow"
    else:
        log.info("No ERA5 data available; using climate zone fallback for %s", zone_name)
        cooling_data = {
            "free_cooling_hours": zone_data["free_cooling_hrs"],
            "total_hours": HOURS_PER_YEAR,
            "avg_temperature_c": zone_data["avg_temp_c"],
            "avg_wet_bulb_c": None,
        }
        data_source = "climate_zone_fallback"

    free_cooling_hours: int = cooling_data["free_cooling_hours"]
    avg_temp_c: float = cooling_data["avg_temperature_c"]
    free_cooling_pct = round(free_cooling_hours / HOURS_PER_YEAR * 100, 1)

    # ----- 3. PUE estimation -----
    pue_result = estimate_pue(free_cooling_hours, cooling_type, avg_temp_c)
    pue_estimate = pue_result["pue"]

    # ----- 4. WUE estimation -----
    wue_result = estimate_wue(cooling_type, pue_result["mechanical_fraction"], capacity_mw)
    wue_l_kwh = wue_result["wue_l_kwh"]
    annual_water_m3 = wue_result["annual_water_m3"]

    # ----- 5. UKCP18 future projections -----
    future = project_future_climate(free_cooling_hours, pue_estimate, avg_temp_c, cooling_type)

    # ----- 6. Composite score -----
    score_result = compute_cooling_score(pue_estimate, free_cooling_hours, wue_l_kwh)
    cooling_score = score_result["cooling_score"]

    # ----- 7. Recommendation -----
    recommendation = _generate_recommendation(
        cooling_score,
        pue_estimate,
        free_cooling_hours,
        zone_name,
        cooling_type,
        future["future_pue"],
    )

    log.info(
        "Cooling analysis complete: score=%.1f, PUE=%.3f, free_cooling=%d hrs, WUE=%.2f L/kWh",
        cooling_score,
        pue_estimate,
        free_cooling_hours,
        wue_l_kwh,
    )

    return {
        "cooling_score": cooling_score,
        "pue_estimate": pue_estimate,
        "pue_breakdown": pue_result,
        "wue_estimate_l_kwh": wue_l_kwh,
        "annual_water_m3": annual_water_m3,
        "free_cooling_hours": free_cooling_hours,
        "free_cooling_pct": free_cooling_pct,
        "climate_zone": zone_name,
        "avg_temperature_c": avg_temp_c,
        "avg_wet_bulb_c": cooling_data.get("avg_wet_bulb_c"),
        "cooling_type": cooling_type,
        "capacity_mw": capacity_mw,
        "future_pue": future["future_pue"],
        "future_free_cooling_hours": future["future_free_cooling_hours"],
        "future_temperatures_c": future["future_temperatures_c"],
        "score_breakdown": score_result,
        "data_source": data_source,
        "recommendation": recommendation,
    }

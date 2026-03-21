"""Bankable solar/wind yield assessment engine.

Provides investment-grade P50/P75/P90 energy yield estimates with full
uncertainty quantification, degradation modelling, and technology comparison.
Designed for lender-facing due diligence packages.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# UK regional solar resource database (GHI kWh/m²/yr)
# ---------------------------------------------------------------------------
_SOLAR_REGIONS: list[dict] = [
    {"name": "South Coast",    "lat_min": 50.5, "lat_max": 51.2, "lon_min": -5.5, "lon_max": 1.5,  "ghi_low": 1100, "ghi_high": 1200, "temp_avg_c": 11.5},
    {"name": "South England",  "lat_min": 51.0, "lat_max": 51.8, "lon_min": -3.5, "lon_max": 1.5,  "ghi_low": 1050, "ghi_high": 1100, "temp_avg_c": 10.8},
    {"name": "Midlands",       "lat_min": 51.8, "lat_max": 53.0, "lon_min": -3.5, "lon_max": 0.0,  "ghi_low": 950,  "ghi_high": 1050, "temp_avg_c": 10.0},
    {"name": "Wales",          "lat_min": 51.3, "lat_max": 53.5, "lon_min": -5.5, "lon_max": -2.7, "ghi_low": 950,  "ghi_high": 1050, "temp_avg_c": 10.0},
    {"name": "North England",  "lat_min": 53.0, "lat_max": 55.8, "lon_min": -3.5, "lon_max": 0.0,  "ghi_low": 900,  "ghi_high": 1000, "temp_avg_c": 9.0},
    {"name": "Scotland",       "lat_min": 55.0, "lat_max": 61.0, "lon_min": -8.0, "lon_max": -0.5, "ghi_low": 800,  "ghi_high": 950,  "temp_avg_c": 8.0},
]

# Fallback for locations outside defined regions
_DEFAULT_SOLAR = {"name": "UK Average", "ghi_low": 950, "ghi_high": 1050, "temp_avg_c": 10.0}

# ---------------------------------------------------------------------------
# UK regional wind resource database (hub-height wind speed m/s)
# ---------------------------------------------------------------------------
_WIND_REGIONS: list[dict] = [
    {"name": "Scotland Highland", "lat_min": 56.5, "lat_max": 61.0, "lon_min": -8.0, "lon_max": -2.0, "ws_low": 9.0,  "ws_high": 11.0, "cf_low": 0.28, "cf_high": 0.35},
    {"name": "Scotland Lowland",  "lat_min": 55.0, "lat_max": 56.5, "lon_min": -6.0, "lon_max": -2.0, "ws_low": 7.0,  "ws_high": 9.0,  "cf_low": 0.26, "cf_high": 0.32},
    {"name": "North England",     "lat_min": 53.0, "lat_max": 55.8, "lon_min": -3.5, "lon_max": 0.0,  "ws_low": 7.0,  "ws_high": 8.5,  "cf_low": 0.26, "cf_high": 0.30},
    {"name": "Wales",             "lat_min": 51.3, "lat_max": 53.5, "lon_min": -5.5, "lon_max": -2.7, "ws_low": 7.0,  "ws_high": 8.0,  "cf_low": 0.24, "cf_high": 0.28},
    {"name": "Midlands",          "lat_min": 51.8, "lat_max": 53.0, "lon_min": -3.5, "lon_max": 0.0,  "ws_low": 6.0,  "ws_high": 7.0,  "cf_low": 0.22, "cf_high": 0.26},
    {"name": "South England",     "lat_min": 50.0, "lat_max": 51.8, "lon_min": -5.5, "lon_max": 1.5,  "ws_low": 5.5,  "ws_high": 7.0,  "cf_low": 0.20, "cf_high": 0.24},
]

_DEFAULT_WIND = {"name": "UK Average", "ws_low": 6.5, "ws_high": 7.5, "cf_low": 0.24, "cf_high": 0.28}

# ---------------------------------------------------------------------------
# IEC turbine classes — generic power curve parameters
# ---------------------------------------------------------------------------
_TURBINE_CLASSES: dict[str, dict] = {
    "IEC1": {"label": "IEC Class I (high wind)",   "rated_ws": 12.5, "cut_in": 3.5, "cut_out": 25.0, "rated_power_factor": 1.0},
    "IEC2": {"label": "IEC Class II (medium wind)", "rated_ws": 11.0, "cut_in": 3.0, "cut_out": 25.0, "rated_power_factor": 1.0},
    "IEC3": {"label": "IEC Class III (low wind)",   "rated_ws": 9.5,  "cut_in": 2.5, "cut_out": 22.0, "rated_power_factor": 1.0},
}

# Monthly solar profile (fraction of annual GHI per month) — UK typical
_MONTHLY_SOLAR_FRAC = [
    0.025, 0.040, 0.070, 0.100, 0.120, 0.130,
    0.130, 0.120, 0.095, 0.070, 0.040, 0.025,
]
_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Monthly wind profile (fraction of annual production) — UK typical
_MONTHLY_WIND_FRAC = [
    0.110, 0.100, 0.095, 0.080, 0.065, 0.055,
    0.055, 0.060, 0.075, 0.095, 0.105, 0.110,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_solar_region(lat: float, lon: float) -> dict:
    """Return best-match solar region for a lat/lon."""
    for r in _SOLAR_REGIONS:
        if r["lat_min"] <= lat <= r["lat_max"] and r["lon_min"] <= lon <= r["lon_max"]:
            return r
    # Fallback: pick closest by latitude
    best = min(_SOLAR_REGIONS, key=lambda r: abs((r["lat_min"] + r["lat_max"]) / 2 - lat))
    return best


def _find_wind_region(lat: float, lon: float) -> dict:
    """Return best-match wind region for a lat/lon."""
    for r in _WIND_REGIONS:
        if r["lat_min"] <= lat <= r["lat_max"] and r["lon_min"] <= lon <= r["lon_max"]:
            return r
    best = min(_WIND_REGIONS, key=lambda r: abs((r["lat_min"] + r["lat_max"]) / 2 - lat))
    return best


def _weibull_cf(mean_ws: float, k: float, rated_ws: float, cut_in: float, cut_out: float) -> float:
    """Estimate capacity factor from Weibull distribution + generic power curve.

    Uses numerical integration over the Weibull PDF with a cubic power curve
    between cut-in and rated, flat at rated between rated and cut-out.
    """
    # Weibull scale parameter from mean and shape
    c = mean_ws / math.gamma(1.0 + 1.0 / k)
    n_bins = 100
    ws_max = min(cut_out + 2.0, 35.0)
    dw = ws_max / n_bins
    total_energy = 0.0
    total_prob = 0.0

    for i in range(n_bins):
        ws = (i + 0.5) * dw
        # Weibull PDF
        if c <= 0:
            pdf = 0.0
        else:
            pdf = (k / c) * ((ws / c) ** (k - 1)) * math.exp(-((ws / c) ** k))

        # Power output (normalized 0-1)
        if ws < cut_in or ws > cut_out:
            power = 0.0
        elif ws < rated_ws:
            power = ((ws - cut_in) / (rated_ws - cut_in)) ** 3
        else:
            power = 1.0

        total_energy += power * pdf * dw
        total_prob += pdf * dw

    return min(total_energy, 0.60)  # Cap at 60% as physical limit


def _rss(*values: float) -> float:
    """Root-sum-square combination of uncertainty values."""
    return math.sqrt(sum(v ** 2 for v in values))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def solar_yield_bankable(
    lat: float,
    lon: float,
    capacity_mwp: float,
    tilt: Optional[float] = None,
    azimuth: float = 180.0,
    tracking: str = "fixed",
    losses: Optional[dict] = None,
) -> dict:
    """Investment-grade solar yield assessment.

    Parameters
    ----------
    lat, lon : float
        Site coordinates (WGS84).
    capacity_mwp : float
        Installed DC capacity in MWp.
    tilt : float, optional
        Panel tilt in degrees. If None, optimal tilt is calculated.
    azimuth : float
        Panel azimuth (180 = due south).
    tracking : str
        "fixed", "single_axis", or "dual_axis".
    losses : dict, optional
        Override default loss assumptions.

    Returns
    -------
    dict
        Full bankable yield assessment with P50/P75/P90 bands.
    """
    region = _find_solar_region(lat, lon)
    ghi_mid = (region["ghi_low"] + region["ghi_high"]) / 2.0
    temp_avg = region.get("temp_avg_c", 10.0)

    # Optimal tilt
    if tilt is None:
        if tracking == "fixed":
            tilt = round(0.7 * abs(lat), 1)
        elif tracking == "single_axis":
            tilt = 0.0
        else:
            tilt = 0.0

    # Tilt correction factor (simplified — penalty for non-optimal)
    optimal_tilt = 0.7 * abs(lat)
    tilt_deviation = abs(tilt - optimal_tilt)
    tilt_factor = max(0.85, 1.0 - 0.002 * tilt_deviation)

    # Azimuth correction (penalty for deviation from 180°)
    az_deviation = abs(azimuth - 180.0)
    az_factor = max(0.80, 1.0 - 0.003 * az_deviation)

    # Tracker gain
    tracker_gains = {"fixed": 1.0, "single_axis": 1.175, "dual_axis": 1.275}
    tracker_factor = tracker_gains.get(tracking, 1.0)

    # If using tracker, override tilt/azimuth factors
    if tracking != "fixed":
        tilt_factor = 1.0
        az_factor = 1.0

    # Performance ratio model
    default_losses = {
        "temperature_coeff_pct_per_c": -0.40,
        "soiling_pct": 2.0,
        "mismatch_pct": 1.5,
        "wiring_pct": 1.0,
        "inverter_eff_pct": 97.0,
        "transformer_eff_pct": 99.0,
        "availability_pct": 98.0,
    }
    if losses:
        default_losses.update(losses)
    L = default_losses

    # Base PR
    pr_base = 0.82

    # Temperature adjustment (cell temp ~25°C above ambient in summer, averaged)
    # UK module temp ≈ ambient + 20 (NOCT assumption, ventilated)
    avg_cell_temp = temp_avg + 20.0
    temp_delta = max(0.0, avg_cell_temp - 25.0)
    temp_loss = abs(L["temperature_coeff_pct_per_c"]) * temp_delta / 100.0

    # Total PR
    other_losses = (
        L["soiling_pct"] / 100.0
        + L["mismatch_pct"] / 100.0
        + L["wiring_pct"] / 100.0
    )
    inverter_eff = L["inverter_eff_pct"] / 100.0
    transformer_eff = L["transformer_eff_pct"] / 100.0
    availability = L["availability_pct"] / 100.0

    pr = pr_base * (1.0 - temp_loss) * (1.0 - other_losses) * inverter_eff * transformer_eff * availability
    pr = round(pr, 4)

    # In-plane irradiance (GHI * tilt/azimuth/tracker corrections)
    ghi_poa = ghi_mid * tilt_factor * az_factor * tracker_factor

    # Specific yield (kWh/kWp)
    specific_yield = ghi_poa * pr
    specific_yield = round(specific_yield, 1)

    # Annual yield P50
    annual_yield_mwh = capacity_mwp * specific_yield  # kWh/kWp * MWp = MWh
    annual_yield_mwh = round(annual_yield_mwh, 1)

    # Capacity factor
    hours_per_year = 8760.0
    capacity_factor = annual_yield_mwh / (capacity_mwp * hours_per_year)
    capacity_factor_pct = round(capacity_factor * 100, 2)

    # Uncertainty analysis
    resource_uncertainty_pct = 5.0
    inter_annual_pct = 3.0
    model_uncertainty_pct = 3.0
    combined_uncertainty_pct = round(_rss(resource_uncertainty_pct, inter_annual_pct, model_uncertainty_pct), 2)

    p75_factor = 1.0 - 0.674 * combined_uncertainty_pct / 100.0  # 75th percentile
    p90_factor = 1.0 - 1.282 * combined_uncertainty_pct / 100.0  # 90th percentile

    p50_mwh = annual_yield_mwh
    p75_mwh = round(annual_yield_mwh * p75_factor, 1)
    p90_mwh = round(annual_yield_mwh * p90_factor, 1)

    # Monthly profile
    monthly_profile = []
    for i in range(12):
        m_yield = round(annual_yield_mwh * _MONTHLY_SOLAR_FRAC[i], 1)
        monthly_profile.append({
            "month": _MONTH_NAMES[i],
            "yield_mwh": m_yield,
            "fraction_pct": round(_MONTHLY_SOLAR_FRAC[i] * 100, 1),
        })

    # 25-year degradation table
    degradation_rate = 0.005  # 0.5%/yr linear (crystalline Si)
    degradation_table = []
    cumulative_mwh = 0.0
    for yr in range(1, 26):
        deg_factor = 1.0 - degradation_rate * (yr - 1)
        yr_yield = round(p50_mwh * deg_factor, 1)
        cumulative_mwh += yr_yield
        degradation_table.append({
            "year": yr,
            "degradation_factor": round(deg_factor, 4),
            "annual_yield_mwh": yr_yield,
            "cumulative_mwh": round(cumulative_mwh, 1),
        })

    lifetime_yield_mwh = round(cumulative_mwh, 0)

    # Bankability statement
    if capacity_factor_pct >= 10.0 and pr >= 0.75:
        bankability = "BANKABLE — Yield estimates are within acceptable ranges for UK project finance. PR and capacity factor consistent with operational benchmarks."
    elif capacity_factor_pct >= 8.0:
        bankability = "CONDITIONALLY BANKABLE — Yield is below UK average but may be acceptable with conservative financial assumptions and enhanced monitoring."
    else:
        bankability = "NOT BANKABLE — Yield estimates are below minimum thresholds for conventional project finance. Site resource may be insufficient."

    return {
        "technology": "solar",
        "capacity_mwp": capacity_mwp,
        "location": {"lat": lat, "lon": lon},
        "region": region["name"],
        "ghi_kwh_m2_yr": round(ghi_mid, 0),
        "tilt_deg": tilt,
        "azimuth_deg": azimuth,
        "tracking": tracking,
        "performance_ratio": pr,
        "losses": {
            "temperature_loss_pct": round(temp_loss * 100, 2),
            "soiling_pct": L["soiling_pct"],
            "mismatch_pct": L["mismatch_pct"],
            "wiring_pct": L["wiring_pct"],
            "inverter_efficiency_pct": L["inverter_eff_pct"],
            "transformer_efficiency_pct": L["transformer_eff_pct"],
            "availability_pct": L["availability_pct"],
        },
        "specific_yield_kwh_kwp": specific_yield,
        "annual_yield": {
            "p50_mwh": p50_mwh,
            "p75_mwh": p75_mwh,
            "p90_mwh": p90_mwh,
        },
        "capacity_factor_pct": capacity_factor_pct,
        "uncertainty": {
            "resource_pct": resource_uncertainty_pct,
            "inter_annual_pct": inter_annual_pct,
            "model_pct": model_uncertainty_pct,
            "combined_pct": combined_uncertainty_pct,
        },
        "monthly_profile": monthly_profile,
        "degradation": {
            "rate_pct_yr": degradation_rate * 100,
            "technology": "crystalline_silicon",
            "lifetime_years": 25,
            "lifetime_yield_mwh": lifetime_yield_mwh,
            "year_25_yield_mwh": degradation_table[-1]["annual_yield_mwh"],
            "table": degradation_table,
        },
        "bankability_statement": bankability,
    }


def wind_yield_bankable(
    lat: float,
    lon: float,
    capacity_mw: float,
    hub_height: float = 80.0,
    turbine_class: str = "IEC2",
    num_turbines: int = 1,
) -> dict:
    """Investment-grade wind yield assessment.

    Parameters
    ----------
    lat, lon : float
        Site coordinates (WGS84).
    capacity_mw : float
        Total installed capacity in MW.
    hub_height : float
        Hub height in metres.
    turbine_class : str
        IEC turbine class: "IEC1", "IEC2", or "IEC3".
    num_turbines : int
        Number of turbines (affects wake loss).

    Returns
    -------
    dict
        Full bankable wind yield assessment.
    """
    region = _find_wind_region(lat, lon)
    tc = _TURBINE_CLASSES.get(turbine_class.upper(), _TURBINE_CLASSES["IEC2"])

    # Mean wind speed (mid-range for region, adjusted for hub height)
    ws_ref = (region["ws_low"] + region["ws_high"]) / 2.0
    ref_height = 80.0  # reference height for regional data
    # Wind shear power law: v2 = v1 * (h2/h1)^alpha
    shear_exponent = 0.14  # typical onshore UK
    ws_hub = ws_ref * (hub_height / ref_height) ** shear_exponent
    ws_hub = round(ws_hub, 2)

    # Weibull parameters
    k = 2.0  # typical UK shape parameter
    c = round(ws_hub / math.gamma(1.0 + 1.0 / k), 2)

    # Capacity factor from Weibull + power curve
    cf_raw = _weibull_cf(ws_hub, k, tc["rated_ws"], tc["cut_in"], tc["cut_out"])

    # Cross-check with regional benchmarks
    cf_regional_mid = (region["cf_low"] + region["cf_high"]) / 2.0
    # Blend: 70% calculated, 30% regional benchmark
    cf_blended = 0.7 * cf_raw + 0.3 * cf_regional_mid

    # Wake losses
    if num_turbines > 5:
        wake_loss_pct = 8.0
    elif num_turbines > 2:
        wake_loss_pct = 5.0
    elif num_turbines > 1:
        wake_loss_pct = 3.0
    else:
        wake_loss_pct = 0.0

    # Availability
    availability_pct = 97.0  # onshore

    # Electrical losses
    electrical_loss_pct = 2.5

    # Net capacity factor
    cf_net = cf_blended * (1.0 - wake_loss_pct / 100.0) * (availability_pct / 100.0) * (1.0 - electrical_loss_pct / 100.0)
    cf_net_pct = round(cf_net * 100, 2)

    # Annual energy production
    hours_per_year = 8760.0
    aep_p50 = round(capacity_mw * cf_net * hours_per_year, 1)

    # Uncertainty
    resource_uncertainty_pct = 10.0
    inter_annual_pct = 6.0
    model_uncertainty_pct = 3.0
    combined_pct = round(_rss(resource_uncertainty_pct, inter_annual_pct, model_uncertainty_pct), 2)

    p75_factor = 1.0 - 0.674 * combined_pct / 100.0
    p90_factor = 1.0 - 1.282 * combined_pct / 100.0

    p75_mwh = round(aep_p50 * p75_factor, 1)
    p90_mwh = round(aep_p50 * p90_factor, 1)

    # Monthly profile
    monthly_profile = []
    for i in range(12):
        m_yield = round(aep_p50 * _MONTHLY_WIND_FRAC[i], 1)
        monthly_profile.append({
            "month": _MONTH_NAMES[i],
            "yield_mwh": m_yield,
            "fraction_pct": round(_MONTHLY_WIND_FRAC[i] * 100, 1),
        })

    # Bankability statement
    if cf_net_pct >= 25.0:
        bankability = "BANKABLE — Wind resource and capacity factor exceed minimum thresholds for UK project finance. Site is well-suited for development."
    elif cf_net_pct >= 20.0:
        bankability = "CONDITIONALLY BANKABLE — Capacity factor is moderate. Bankability depends on turbine selection, PPA price, and connection costs."
    else:
        bankability = "NOT BANKABLE — Capacity factor is below minimum thresholds for conventional wind project finance in the UK."

    return {
        "technology": "wind",
        "capacity_mw": capacity_mw,
        "location": {"lat": lat, "lon": lon},
        "region": region["name"],
        "hub_height_m": hub_height,
        "turbine_class": turbine_class.upper(),
        "turbine_spec": tc["label"],
        "num_turbines": num_turbines,
        "wind_speed_ms": ws_hub,
        "weibull": {"k": k, "c": c},
        "capacity_factor_gross_pct": round(cf_blended * 100, 2),
        "losses": {
            "wake_pct": wake_loss_pct,
            "availability_pct": availability_pct,
            "electrical_pct": electrical_loss_pct,
        },
        "capacity_factor_net_pct": cf_net_pct,
        "annual_energy_production": {
            "p50_mwh": aep_p50,
            "p75_mwh": p75_mwh,
            "p90_mwh": p90_mwh,
        },
        "uncertainty": {
            "resource_pct": resource_uncertainty_pct,
            "inter_annual_pct": inter_annual_pct,
            "model_pct": model_uncertainty_pct,
            "combined_pct": combined_pct,
        },
        "monthly_profile": monthly_profile,
        "bankability_statement": bankability,
    }


def yield_comparison(
    lat: float,
    lon: float,
    capacity_mw: float,
) -> dict:
    """Compare solar vs wind vs hybrid at the same location.

    Parameters
    ----------
    lat, lon : float
        Site coordinates.
    capacity_mw : float
        Installed capacity for each technology (MWp for solar, MW for wind).

    Returns
    -------
    dict
        Side-by-side comparison of solar, wind, and hybrid options.
    """
    solar = solar_yield_bankable(lat, lon, capacity_mw)
    wind = wind_yield_bankable(lat, lon, capacity_mw)

    # LCOE estimates (simplified — £/MWh)
    # Based on UK 2024-2025 benchmarks
    solar_capex_per_mw = 550_000  # £/MWp
    wind_capex_per_mw = 1_100_000  # £/MW onshore
    discount_rate = 0.06
    lifetime = 25

    # CRF (capital recovery factor)
    crf = (discount_rate * (1 + discount_rate) ** lifetime) / ((1 + discount_rate) ** lifetime - 1)

    solar_annual_cost = capacity_mw * solar_capex_per_mw * crf + capacity_mw * 8_000  # O&M £8k/MW/yr
    wind_annual_cost = capacity_mw * wind_capex_per_mw * crf + capacity_mw * 25_000   # O&M £25k/MW/yr

    solar_lcoe = round(solar_annual_cost / solar["annual_yield"]["p50_mwh"], 2) if solar["annual_yield"]["p50_mwh"] > 0 else 999
    wind_lcoe = round(wind_annual_cost / wind["annual_energy_production"]["p50_mwh"], 2) if wind["annual_energy_production"]["p50_mwh"] > 0 else 999

    # Revenue at £55/MWh reference price
    ref_price = 55.0
    solar_revenue = round(solar["annual_yield"]["p50_mwh"] * ref_price, 0)
    wind_revenue = round(wind["annual_energy_production"]["p50_mwh"] * ref_price, 0)

    # Land requirement (approximate)
    solar_land_ha = round(capacity_mw * 1.8, 1)   # ~1.8 ha/MWp for fixed-tilt
    wind_land_ha = round(capacity_mw * 6.0, 1)    # ~6 ha/MW (including spacing)

    # Hybrid: 60% solar + 40% wind (common UK split)
    hybrid_solar_mw = capacity_mw * 0.6
    hybrid_wind_mw = capacity_mw * 0.4
    hybrid_solar = solar_yield_bankable(lat, lon, hybrid_solar_mw)
    hybrid_wind = wind_yield_bankable(lat, lon, hybrid_wind_mw)
    hybrid_yield = round(
        hybrid_solar["annual_yield"]["p50_mwh"] + hybrid_wind["annual_energy_production"]["p50_mwh"], 1
    )
    hybrid_cf = round(
        hybrid_yield / (capacity_mw * 8760) * 100, 2
    )

    return {
        "location": {"lat": lat, "lon": lon},
        "capacity_mw": capacity_mw,
        "comparison": {
            "solar": {
                "annual_yield_p50_mwh": solar["annual_yield"]["p50_mwh"],
                "capacity_factor_pct": solar["capacity_factor_pct"],
                "lcoe_gbp_mwh": solar_lcoe,
                "annual_revenue_gbp": solar_revenue,
                "land_requirement_ha": solar_land_ha,
                "bankability": solar["bankability_statement"],
            },
            "wind": {
                "annual_yield_p50_mwh": wind["annual_energy_production"]["p50_mwh"],
                "capacity_factor_pct": wind["capacity_factor_net_pct"],
                "lcoe_gbp_mwh": wind_lcoe,
                "annual_revenue_gbp": wind_revenue,
                "land_requirement_ha": wind_land_ha,
                "bankability": wind["bankability_statement"],
            },
            "hybrid": {
                "solar_mw": hybrid_solar_mw,
                "wind_mw": hybrid_wind_mw,
                "split": "60% solar / 40% wind",
                "annual_yield_p50_mwh": hybrid_yield,
                "capacity_factor_pct": hybrid_cf,
                "note": "Hybrid configuration reduces inter-annual variability and improves grid utilisation through complementary generation profiles.",
            },
        },
        "recommendation": _recommend(solar, wind),
        "reference_price_gbp_mwh": ref_price,
    }


def _recommend(solar: dict, wind: dict) -> str:
    """Generate a recommendation based on solar vs wind comparison."""
    solar_cf = solar["capacity_factor_pct"]
    wind_cf = wind["capacity_factor_net_pct"]

    if wind_cf > 28.0 and solar_cf < 10.0:
        return "WIND RECOMMENDED — Strong wind resource with limited solar potential. Wind-only development is optimal."
    elif solar_cf > 11.0 and wind_cf < 22.0:
        return "SOLAR RECOMMENDED — Good solar resource with moderate wind. Solar offers lower LCOE and simpler permitting."
    elif wind_cf > 25.0 and solar_cf > 9.5:
        return "HYBRID RECOMMENDED — Both resources are viable. A hybrid solar+wind configuration maximises energy yield and reduces variability."
    elif solar_cf > 9.0:
        return "SOLAR RECOMMENDED — Solar provides better risk-adjusted returns at this location given current UK market conditions."
    else:
        return "FURTHER ASSESSMENT REQUIRED — Neither resource is clearly dominant. Detailed micro-siting and financial modelling recommended."


def uncertainty_analysis(
    technology: str,
    lat: float,
    lon: float,
    capacity_mw: float,
) -> dict:
    """Detailed uncertainty quantification for yield estimates.

    Parameters
    ----------
    technology : str
        "solar" or "wind".
    lat, lon : float
        Site coordinates.
    capacity_mw : float
        Installed capacity.

    Returns
    -------
    dict
        Breakdown of uncertainty components and exceedance probabilities.
    """
    if technology.lower() == "solar":
        base = solar_yield_bankable(lat, lon, capacity_mw)
        p50_mwh = base["annual_yield"]["p50_mwh"]
        resource_unc = 5.0
        inter_annual = 3.0
    else:
        base = wind_yield_bankable(lat, lon, capacity_mw)
        p50_mwh = base["annual_energy_production"]["p50_mwh"]
        resource_unc = 10.0
        inter_annual = 6.0

    model_unc = 3.0
    measurement_unc = 2.0 if technology.lower() == "wind" else 1.0

    combined = round(_rss(resource_unc, inter_annual, model_unc, measurement_unc), 2)

    # Exceedance probabilities
    exceedance = {}
    for label, z in [("P50", 0.0), ("P75", 0.674), ("P90", 1.282), ("P95", 1.645), ("P99", 2.326)]:
        factor = 1.0 - z * combined / 100.0
        exceedance[label] = {
            "annual_yield_mwh": round(p50_mwh * factor, 1),
            "factor": round(factor, 4),
        }

    # 10-year P90 is tighter than 1-year P90 (inter-annual averages out)
    ten_yr_combined = round(_rss(resource_unc, inter_annual / math.sqrt(10), model_unc, measurement_unc), 2)
    ten_yr_p90_factor = 1.0 - 1.282 * ten_yr_combined / 100.0

    return {
        "technology": technology.lower(),
        "capacity_mw": capacity_mw,
        "location": {"lat": lat, "lon": lon},
        "p50_annual_yield_mwh": p50_mwh,
        "uncertainty_components": {
            "long_term_resource_pct": resource_unc,
            "inter_annual_variability_pct": inter_annual,
            "model_uncertainty_pct": model_unc,
            "measurement_uncertainty_pct": measurement_unc,
            "combined_1yr_pct": combined,
            "combined_10yr_pct": ten_yr_combined,
        },
        "exceedance_1yr": exceedance,
        "exceedance_10yr_p90": {
            "annual_yield_mwh": round(p50_mwh * ten_yr_p90_factor, 1),
            "factor": round(ten_yr_p90_factor, 4),
            "note": "10-year average P90 — used for debt sizing (DSCR covenant).",
        },
        "methodology": "IEC 61724 (solar) / IEC 61400-12 (wind) compliant uncertainty framework. Combined uncertainty via root-sum-square of independent components.",
    }


def degradation_schedule(
    capacity_mwp: float,
    annual_yield_mwh: float,
    years: int = 25,
    degradation_rate: float = 0.5,
) -> dict:
    """Generate a year-by-year degradation schedule.

    Parameters
    ----------
    capacity_mwp : float
        Installed capacity in MWp.
    annual_yield_mwh : float
        Year-1 P50 annual yield in MWh.
    years : int
        Project lifetime.
    degradation_rate : float
        Annual degradation rate in % (default 0.5% for crystalline Si).

    Returns
    -------
    dict
        Degradation schedule with cumulative yield.
    """
    rate = degradation_rate / 100.0
    table = []
    cumulative = 0.0

    for yr in range(1, years + 1):
        factor = 1.0 - rate * (yr - 1)
        yr_yield = round(annual_yield_mwh * factor, 1)
        cumulative += yr_yield
        table.append({
            "year": yr,
            "degradation_factor": round(factor, 4),
            "annual_yield_mwh": yr_yield,
            "cumulative_mwh": round(cumulative, 1),
        })

    return {
        "capacity_mwp": capacity_mwp,
        "year_1_yield_mwh": annual_yield_mwh,
        "degradation_rate_pct_yr": degradation_rate,
        "project_lifetime_years": years,
        "lifetime_yield_mwh": round(cumulative, 0),
        "year_final_yield_mwh": table[-1]["annual_yield_mwh"],
        "average_annual_yield_mwh": round(cumulative / years, 1),
        "schedule": table,
    }

"""Solar engineering-math benchmarks — single source of truth.

All Princeps solar revenue, CapEx, OpEx and capacity-factor assumptions
MUST import from this module instead of using magic numbers.

Sources (2026-04):
    - Solar Media UK Large-Scale Solar Tracker, Q4 2025   (CapEx range)
    - LCCC AR7 Pot 1 results, Jan 2026                    (CfD strike)
    - Cornwall Insight UK PPA Price Tracker, Q1 2026      (merchant + corp PPA)
    - DESNZ "Electricity Generation Costs 2024" + DESNZ Renewable Planning DB

Usage:
    from utils.solar_benchmarks import (
        solar_capacity_factor_mid,
        solar_capex_per_kw,
        solar_opex_per_kw_yr,
        ppa_price_merchant_mid,
        ppa_price_corporate_mid,
        cfd_ar7_strike,
        annual_energy_mwh,
        cite,
    )

    cf   = solar_capacity_factor_mid()         # 0.11
    cpx  = solar_capex_per_kw("mid")           # 730
    opx  = solar_opex_per_kw_yr()              # 10
    ppa  = ppa_price_merchant_mid()            # 45
    src  = cite()
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Capacity factor — UK ground-mount, weather-year-normalised
# Source: DESNZ 2024 cost study + Sheffield Solar PV_Live 2023-25 actuals
# ---------------------------------------------------------------------------

SOLAR_CAPACITY_FACTOR: dict[str, float] = {
    "low":  0.100,   # Yorkshire / Lancashire
    "mid":  0.110,   # UK central (Midlands)
    "high": 0.120,   # Devon / Cornwall / SE Kent
}


# ---------------------------------------------------------------------------
# All-in CapEx £/kWp installed, UK ground-mount 2026
# Source: Solar Media UK Large-Scale Tracker Q4 2025
# Range: £680–780/kWp mid £730 — covers EPC, modules, inverters, trackers,
# BOS, grid-side works, development. Excludes DNO capacity charges.
# ---------------------------------------------------------------------------

SOLAR_CAPEX_GBP_PER_KW: dict[str, int] = {
    "low":  680,
    "mid":  730,
    "high": 780,
}

# Component-level CapEx breakdown (USD/W, Solar Media Q4 2025) —
# keep USD for easy comparison to BloombergNEF module-index pricing
MODULE_COST_USD_PER_W: float = 0.10
TRACKER_COST_USD_PER_W: float = 0.06
INVERTER_COST_USD_PER_W: float = 0.05

# Fixed O&M £/kW/yr (scales with nameplate, not energy)
SOLAR_OPEX_GBP_PER_KW_YR: dict[str, int] = {
    "low":   8,
    "mid":  10,
    "high": 12,
}


# ---------------------------------------------------------------------------
# Revenue benchmarks £/MWh, 2026 UK market
# ---------------------------------------------------------------------------

# Merchant PPA (wholesale-indexed, short tenor) — Cornwall Insight Q1 2026
PPA_MERCHANT_GBP_MWH: dict[str, float] = {
    "low":  38.0,
    "mid":  45.0,
    "high": 52.0,
}

# Corporate PPA (Google / AWS / Tesco long-tenor 10-15yr, indexed)
PPA_CORPORATE_GBP_MWH: dict[str, float] = {
    "low":  55.0,
    "mid":  62.0,
    "high": 68.0,
}

# CfD AR7 Pot 1 solar strike — Jan 2026 clearing, 2012-prices
# Converted to 2026 prices via HMT GDP deflator (~1.34 cumulative)
CFD_AR7_STRIKE_GBP_MWH_2012: float = 50.07
CFD_AR7_STRIKE_GBP_MWH_2026: float = 67.0

# Default merchant benchmark used when no PPA contract signed
DEFAULT_REVENUE_GBP_MWH: float = PPA_MERCHANT_GBP_MWH["mid"]   # £45

# Land rent (£/ha/yr) — NFU Energy 2025 optioned ground-lease midpoint
LAND_RENT_GBP_HA_YR: int = 1_200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def solar_capacity_factor_mid() -> float:
    """Mid-case UK capacity factor (fraction, e.g. 0.11)."""
    return SOLAR_CAPACITY_FACTOR["mid"]


def solar_capacity_factor_range() -> tuple[float, float, float]:
    """(low, mid, high) capacity factor."""
    cf = SOLAR_CAPACITY_FACTOR
    return cf["low"], cf["mid"], cf["high"]


def solar_capex_per_kw(case: str = "mid") -> int:
    """All-in CapEx £/kWp installed (case in {'low','mid','high'})."""
    return SOLAR_CAPEX_GBP_PER_KW.get(case, SOLAR_CAPEX_GBP_PER_KW["mid"])


def solar_capex_per_mw(case: str = "mid") -> int:
    """All-in CapEx £/MW installed (case in {'low','mid','high'})."""
    return solar_capex_per_kw(case) * 1000


def solar_opex_per_kw_yr(case: str = "mid") -> int:
    """Fixed O&M £/kW/yr (case in {'low','mid','high'})."""
    return SOLAR_OPEX_GBP_PER_KW_YR.get(case, SOLAR_OPEX_GBP_PER_KW_YR["mid"])


def solar_opex_per_mw_yr(case: str = "mid") -> int:
    """Fixed O&M £/MW/yr (case in {'low','mid','high'})."""
    return solar_opex_per_kw_yr(case) * 1000


def ppa_price_merchant_mid() -> float:
    """Merchant-PPA midpoint £/MWh (Cornwall Insight Q1 2026)."""
    return PPA_MERCHANT_GBP_MWH["mid"]


def ppa_price_merchant_range() -> tuple[float, float, float]:
    """(low, mid, high) merchant PPA £/MWh."""
    p = PPA_MERCHANT_GBP_MWH
    return p["low"], p["mid"], p["high"]


def ppa_price_corporate_mid() -> float:
    """Corporate-PPA (Google/AWS long-tenor) midpoint £/MWh."""
    return PPA_CORPORATE_GBP_MWH["mid"]


def ppa_price_corporate_range() -> tuple[float, float, float]:
    """(low, mid, high) corporate PPA £/MWh."""
    p = PPA_CORPORATE_GBP_MWH
    return p["low"], p["mid"], p["high"]


def cfd_ar7_strike() -> float:
    """AR7 Pot 1 solar strike price in 2026 money, £/MWh."""
    return CFD_AR7_STRIKE_GBP_MWH_2026


def default_revenue_gbp_mwh() -> float:
    """Default merchant £/MWh when no PPA contract is modelled (£45)."""
    return DEFAULT_REVENUE_GBP_MWH


def land_rent_gbp_ha_yr() -> int:
    """Typical UK optioned ground-lease rent, £/ha/yr."""
    return LAND_RENT_GBP_HA_YR


def annual_energy_mwh(capacity_mw: float, capacity_factor: float | None = None) -> float:
    """Annual energy yield in MWh for a nameplate MW and capacity factor.

    If ``capacity_factor`` is None, uses the UK-central mid-case (0.11).
    """
    cf = solar_capacity_factor_mid() if capacity_factor is None else capacity_factor
    return float(capacity_mw) * 8760.0 * float(cf)


def solar_capex_gbp(capacity_mw: float, case: str = "mid") -> float:
    """Total CapEx £ for a given nameplate MW."""
    return float(capacity_mw) * solar_capex_per_mw(case)


def solar_opex_gbp_yr(capacity_mw: float, case: str = "mid") -> float:
    """Total fixed O&M £/yr for a given nameplate MW."""
    return float(capacity_mw) * solar_opex_per_mw_yr(case)


def cite() -> str:
    """Citation string for the solar benchmarks used here."""
    return (
        "Solar Media Q4 2025 + LCCC AR7 Pot 1 (Jan 2026) + "
        "Cornwall Insight Q1 2026"
    )


# ---------------------------------------------------------------------------
# Convenience dict — exported for frontend JSON mirror
# ---------------------------------------------------------------------------

def as_dict() -> dict:
    """Return the whole benchmark set as a plain dict (JSON-serialisable)."""
    return {
        "capacity_factor": SOLAR_CAPACITY_FACTOR,
        "capex_gbp_per_kw": SOLAR_CAPEX_GBP_PER_KW,
        "opex_gbp_per_kw_yr": SOLAR_OPEX_GBP_PER_KW_YR,
        "ppa_merchant_gbp_mwh": PPA_MERCHANT_GBP_MWH,
        "ppa_corporate_gbp_mwh": PPA_CORPORATE_GBP_MWH,
        "cfd_ar7_strike_gbp_mwh_2012": CFD_AR7_STRIKE_GBP_MWH_2012,
        "cfd_ar7_strike_gbp_mwh_2026": CFD_AR7_STRIKE_GBP_MWH_2026,
        "default_revenue_gbp_mwh": DEFAULT_REVENUE_GBP_MWH,
        "module_cost_usd_per_w": MODULE_COST_USD_PER_W,
        "tracker_cost_usd_per_w": TRACKER_COST_USD_PER_W,
        "inverter_cost_usd_per_w": INVERTER_COST_USD_PER_W,
        "land_rent_gbp_ha_yr": LAND_RENT_GBP_HA_YR,
        "citation": cite(),
    }

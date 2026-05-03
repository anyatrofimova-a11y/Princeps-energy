"""UK corporate PPA benchmark curves by tenor, region, and technology.

These are the market levels a generation project can realistically sign
today for a multi-year offtake, broken out by contract structure
(pay-as-produced vs baseload), tenor, tech, and vintage.

Sources (all versioned):
  - Cornwall Insight UK PPA Tracker Q1 2026 (Feb 2026 data)
  - Pexapark PPA Pricing Monitor Q4 2025 (EU-wide + UK) + Q1 2026
  - LCP Delta AR7 Pre-Clearing Analysis (Dec 2025)
  - LCCC (Low Carbon Contracts Co) AR7 Final Budget Notice (Dec 2025)
  - LevelTen Energy PPA Price Index Q1 2026 — corporate PPA proxies
  - BNEF 1H 2026 Corporate Energy Market Outlook

The convention used here matches Cornwall Insight:

  - "pay_as_produced" (PAYP) — offtaker buys whatever the asset generates
  - "baseload" — generator delivers a fixed MW, must buy in the gap from
    the wholesale market if the asset underperforms (shape risk)
  - Baseload PPAs trade at a discount to PAYP because the generator
    carries the shape risk. Typical spread: 8-12% for solar, 3-5% for
    wind (wind is shape-closer to baseload).

Usage:
    from utils.ppa_benchmarks import (
        ppa_curve, pay_as_produced_vs_baseload_premium,
        cfd_round_clearing_forecast,
    )
"""

from __future__ import annotations

from typing import Literal

from utils.finance_benchmarks import (
    CFD_AR7_OFFSHORE_STRIKE_GBP_MWH_2026,
    CFD_AR7_STRIKE_GBP_MWH_2026,
    CPI_LONG_RUN,
    PPA_MERCHANT_BY_TECH_GBP_MWH,
)

# ---------------------------------------------------------------------------
# Core PPA price curves — Cornwall Insight UK PPA Tracker Q1 2026
# These are midpoints for a 10yr PAYP contract in GB south.
# Tenor adjustments below.
# ---------------------------------------------------------------------------

# £/MWh midpoint for a 10yr PAYP, GB south, 2026 vintage start
# (Cornwall Insight Q1 2026 tracker + LevelTen Q1 2026 EU PPA index crosscheck)
PPA_10YR_PAYP_MID_GBP_MWH: dict[str, float] = {
    "solar":         58.5,   # Cornwall Q1 2026: 10yr solar PAYP £58/MWh ±£2
    "wind":          62.0,   # Onshore wind — slightly higher than solar
    "offshore_wind": 76.0,   # Corporate offshore wind PPAs — BNEF 1H26
    "bess":          70.0,   # Blended revenue proxy, Modo (not a true PPA)
    "dc":            90.0,   # Hyperscaler corp PPA, LevelTen US-read-across
}

# Discount factor applied when moving from PAYP to baseload
# (i.e. multiply PAYP price by this to get baseload price)
# Source: Pexapark PPA Pricing Monitor Q4 2025 spread charts
PAYP_VS_BASELOAD_DISCOUNT: dict[str, float] = {
    "solar":         0.90,   # baseload ~10% below PAYP for solar
    "wind":          0.96,   # only ~4% for wind (shape closer to flat)
    "offshore_wind": 0.95,
    "bess":          1.00,   # BESS always pay-for-service
    "dc":            1.00,
}

# Tenor premium — shorter tenors trade at discount; longer at premium
# (Cornwall Insight Q1 2026: 5yr -12%, 10yr baseline, 15yr +4%, 20yr +6%)
TENOR_FACTOR_BY_YEARS: dict[int, float] = {
    3:  0.82,
    5:  0.88,
    7:  0.94,
    10: 1.00,    # reference tenor
    12: 1.02,
    15: 1.04,
    20: 1.06,
    25: 1.06,
}

# Regional factor — shares the wholesale locational spread
# (Cornwall Insight GB Zonal Price Outlook Q1 2026 — shadowing REMA)
PPA_REGION_FACTOR: dict[str, float] = {
    "gb":              1.00,
    "south_east":      1.03,
    "london":          1.04,
    "east_of_england": 1.01,
    "east_midlands":   1.00,
    "south_west":      0.99,
    "west_midlands":   0.99,
    "yorkshire":       0.97,
    "north_west":      0.95,
    "north_east":      0.93,
    "scotland":        0.87,   # transmission-constrained north
    "wales":           0.94,
}

# PPA premium over merchant — Cornwall Insight Q1 2026:
#   PPAs trade at ~85-95% of expected merchant capture price
#   (generator pays away 5-15% for offtake certainty / credit enhancement).
# Stored as "PPA price ÷ merchant capture" for the 10yr tenor, central case.
PPA_VS_MERCHANT_DISCOUNT: dict[str, float] = {
    "solar":         0.88,
    "wind":          0.90,
    "offshore_wind": 0.92,
    "bess":          1.00,
    "dc":            1.00,
}


# ---------------------------------------------------------------------------
# CfD AR7 (Jan 2026) clearing + AR8 forecast
# ---------------------------------------------------------------------------

# AR7 final clearing (LCCC AR7 Final Budget Notice + LCP Delta post-round
# commentary Jan 2026). Strike prices in 2012 real prices per LCCC convention.
AR7_RESULTS_2012_GBP_MWH: dict[str, float] = {
    "solar_pot1":         50.07,    # LCCC AR7 Allocation Framework
    "onshore_wind_pot1":  52.29,
    "offshore_wind_pot3": 72.49,    # Pot 3 established AR5, cleared AR7 wide
    "tidal_stream":      172.00,    # Pot 2 emerging tech
}

# Published 2026 nominal strike (GDP deflator ×1.34 from 2012 prices)
# Cross-check: LCCC final results table Jan 2026
AR7_RESULTS_2026_GBP_MWH: dict[str, float] = {
    "solar_pot1":         CFD_AR7_STRIKE_GBP_MWH_2026,                # 67.0
    "onshore_wind_pot1":  70.0,
    "offshore_wind_pot3": CFD_AR7_OFFSHORE_STRIKE_GBP_MWH_2026,       # 85.0
    "tidal_stream":      230.0,
}

# AR8 forecast (LCP Delta "AR8 Outlook" Mar 2026, pre-round)
# Expected clearing for scheduled Jan 2027 round
AR8_FORECAST_2026_GBP_MWH: dict[str, float] = {
    "solar_pot1":         65.0,     # LCP Delta: £63-68 range, mid 65
    "onshore_wind_pot1":  68.0,
    "offshore_wind_pot3": 82.0,     # slight easing post-Dogger C landing
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ppa_curve(
    tech: str,
    tenor_yrs: int = 10,
    region: str = "gb",
    year_start: int = 2026,
    structure: Literal["pay_as_produced", "baseload"] = "pay_as_produced",
    inflation: float | None = None,
) -> dict:
    """£/MWh year-by-year PPA price curve.

    Returns a dict with:
      - ``year_by_year``: list of {year, gbp_mwh}
      - ``level_price``: flat blended level equivalent
      - ``premium_over_merchant``: PPA price / merchant price ratio (first yr)
      - ``structure``: echoed back

    The real-terms curve is a flat level adjusted for:
      - tech baseline (10yr PAYP reference)
      - tenor factor
      - regional factor
      - structure (PAYP vs baseload)

    Then it escalates each year by ``inflation`` (default = CPI long-run).
    Cites Cornwall Insight UK PPA Tracker Q1 2026 for levels.
    """
    t = (tech or "solar").lower()
    base = PPA_10YR_PAYP_MID_GBP_MWH.get(t, PPA_10YR_PAYP_MID_GBP_MWH["solar"])
    tenor_key = _nearest_tenor(tenor_yrs)
    tenor_adj = TENOR_FACTOR_BY_YEARS[tenor_key]
    region_adj = PPA_REGION_FACTOR.get((region or "gb").lower(), 1.0)

    structure_adj = 1.0
    if structure == "baseload":
        structure_adj = PAYP_VS_BASELOAD_DISCOUNT.get(t, 1.0)

    level = base * tenor_adj * region_adj * structure_adj
    inf = CPI_LONG_RUN if inflation is None else inflation

    year_by_year: list[dict] = []
    for i in range(tenor_yrs):
        yr = year_start + i
        # PPA curves in UK market are typically CPI-linked — Cornwall
        # Insight models indexation at full CPI for corporate PPAs.
        price = level * ((1.0 + inf) ** i)
        year_by_year.append({"year": yr, "gbp_mwh": round(price, 2)})

    # Merchant comparator — for premium calculation
    merchant_range = PPA_MERCHANT_BY_TECH_GBP_MWH.get(
        t, PPA_MERCHANT_BY_TECH_GBP_MWH["solar"]
    )
    merchant_mid = merchant_range["mid"]
    premium_over_merchant = round(level / merchant_mid, 3) if merchant_mid else 1.0

    return {
        "tech": t,
        "tenor_yrs": tenor_yrs,
        "structure": structure,
        "region": region,
        "year_start": year_start,
        "inflation_pct": round(inf * 100, 2),
        "level_price_gbp_mwh": round(level, 2),
        "year_by_year": year_by_year,
        "merchant_mid_gbp_mwh": merchant_mid,
        "premium_over_merchant": premium_over_merchant,
        "citation": cite(),
    }


def pay_as_produced_vs_baseload_premium(tech: str) -> dict:
    """Discount baseload carries vs PAYP — i.e. generator takes shape risk.

    Return format: {tech, baseload_factor, payp_factor, spread_pct, citation}
    where spread_pct is (1 - baseload_factor) × 100.

    Pexapark Q4 2025 Monitor: solar baseload trades at £5-6/MWh discount
    to PAYP for 10yr UK contracts; wind at £2-3/MWh (shape closer).
    """
    t = (tech or "solar").lower()
    baseload = PAYP_VS_BASELOAD_DISCOUNT.get(t, 0.95)
    spread = round((1.0 - baseload) * 100, 2)
    return {
        "tech": t,
        "baseload_factor": baseload,
        "payp_factor": 1.00,
        "spread_pct": spread,
        "citation": "Pexapark PPA Pricing Monitor Q4 2025 — "
                    "GB baseload vs PAYP spread",
    }


def cfd_round_clearing_forecast(
    round_name: str = "AR8",
    tech: str = "solar",
    pot: int = 1,
) -> dict:
    """CfD round strike forecast or actual result.

    - round_name='AR7' returns actual clearing (LCCC Jan 2026 Final Notice)
    - round_name='AR8' returns LCP Delta Mar 2026 pre-round forecast
    - round_name='AR9' returns LCP Delta extrapolation (flag as forecast)

    Parameters
    ----------
    round_name : 'AR7' | 'AR8' | 'AR9'
    tech       : solar | onshore_wind | offshore_wind | tidal_stream
    pot        : 1 (established onshore), 2 (emerging), 3 (established offshore)

    Returns {round, tech, pot, strike_2026_gbp_mwh, strike_2012_gbp_mwh,
             source, forecast_or_actual}.
    """
    tech_key = _cfd_tech_key(tech, pot)
    r = round_name.upper()
    if r == "AR7":
        strike_2026 = AR7_RESULTS_2026_GBP_MWH.get(tech_key)
        strike_2012 = AR7_RESULTS_2012_GBP_MWH.get(tech_key)
        return {
            "round": "AR7",
            "tech": tech_key,
            "pot": pot,
            "strike_2026_gbp_mwh": strike_2026,
            "strike_2012_gbp_mwh": strike_2012,
            "forecast_or_actual": "actual",
            "source": "LCCC AR7 Final Budget Notice Jan 2026",
        }
    if r == "AR8":
        return {
            "round": "AR8",
            "tech": tech_key,
            "pot": pot,
            "strike_2026_gbp_mwh": AR8_FORECAST_2026_GBP_MWH.get(tech_key),
            "strike_2012_gbp_mwh": None,
            "forecast_or_actual": "forecast",
            "source": "LCP Delta AR8 Outlook Mar 2026 (pre-round)",
        }
    # AR9 rough extrapolation — LCP Delta long-term CfD outlook
    # Assume 2% annual nominal inflation in clearing from AR8
    ar8 = AR8_FORECAST_2026_GBP_MWH.get(tech_key, 0.0)
    return {
        "round": r,
        "tech": tech_key,
        "pot": pot,
        "strike_2026_gbp_mwh": round(ar8 * 1.04, 2),    # ~2 yrs × 2%
        "strike_2012_gbp_mwh": None,
        "forecast_or_actual": "forecast",
        "source": "LCP Delta long-term CfD outlook Q1 2026 "
                  "(assumed 2%/yr nominal drift)",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _nearest_tenor(yrs: int) -> int:
    """Snap to the nearest tenor bucket we have a factor for."""
    keys = sorted(TENOR_FACTOR_BY_YEARS.keys())
    return min(keys, key=lambda k: abs(k - yrs))


def _cfd_tech_key(tech: str, pot: int) -> str:
    """Map tech+pot to the canonical AR-results dict key."""
    t = (tech or "solar").lower()
    if t == "solar":
        return "solar_pot1"
    if t in {"onshore_wind", "wind"}:
        return "onshore_wind_pot1"
    if t == "offshore_wind":
        return "offshore_wind_pot3"
    if t == "tidal_stream":
        return "tidal_stream"
    return "solar_pot1"


def cite() -> str:
    """Primary sources for the UK PPA curves used here."""
    return (
        "Cornwall Insight UK PPA Tracker Q1 2026 + "
        "Pexapark PPA Pricing Monitor Q4 2025 + Q1 2026 + "
        "LevelTen Energy PPA Price Index Q1 2026 + "
        "BNEF 1H 2026 Corporate Energy Market Outlook + "
        "LCCC AR7 Final Budget Notice Jan 2026 + "
        "LCP Delta AR8 Outlook Mar 2026"
    )


__all__ = [
    "ppa_curve",
    "pay_as_produced_vs_baseload_premium",
    "cfd_round_clearing_forecast",
    "cite",
    "PPA_10YR_PAYP_MID_GBP_MWH",
    "PAYP_VS_BASELOAD_DISCOUNT",
    "TENOR_FACTOR_BY_YEARS",
    "PPA_REGION_FACTOR",
    "AR7_RESULTS_2026_GBP_MWH",
    "AR8_FORECAST_2026_GBP_MWH",
]

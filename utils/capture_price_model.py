"""Merchant capture-price modelling for UK generation assets.

The *captured price* is the volume-weighted wholesale price a generator
actually receives — NOT the time-average baseload. Solar captures less
than baseload because it over-supplies at midday (the "duck curve"),
wind captures closer to baseload (wider dispatch window). Both fall as
more of the same tech enters the grid — this is *cannibalisation*.

This module returns pathway-aware £/MWh capture prices by year and
region, using published forecasts from Cornwall Insight, Aurora Energy
Research, and NESO FES 2024.

Sources (all dated / versioned):
  - Cornwall Insight "Solar & Wind Capture Price Forecast GB 2025-35",
    Q1 2026 edition (Feb 2026 data)
  - Aurora Energy Research SolAR3 & WIM methodology notes 2025
  - Aurora GB Power Market Forecast Q4 2025
  - NESO FES 2024 — four pathways (LW / CT / ST / FS)
  - Modo Energy GB BESS Index, Mar 2026 (BESS arb & stacking)
  - NESO BSUoS auction clearing prices Jan-Mar 2026 (ancillary £/MW/h)
  - LCP Delta "GB Ancillary Services Outlook" Q1 2026

Usage:
    from utils.capture_price_model import (
        capture_price_solar,
        capture_price_wind,
        capture_price_bess_arb,
        capture_price_bess_ancillary,
        cannibalisation_factor,
    )

    # £/MWh a 2028 solar farm in East Midlands captures under System
    # Transformation pathway
    p = capture_price_solar(2028, "east_midlands", "system_transformation")
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Installed-capacity pathway projections (GW) — NESO FES 2024 Data Workbook
# Values read from "ES.1.1 Electricity Capacity" sheet, Feb 2024 release.
# GB-only; excludes NI.
# ---------------------------------------------------------------------------

# year -> GW installed solar PV, per pathway
SOLAR_INSTALLED_GW: dict[str, dict[int, float]] = {
    # Leading the Way — fastest net-zero path (FES 2024 Data Workbook)
    "leading_the_way":        {2025: 18, 2028: 35, 2030: 50, 2035: 80, 2040: 95, 2050: 110},
    "consumer_transformation": {2025: 17, 2028: 32, 2030: 45, 2035: 72, 2040: 88, 2050: 100},
    "system_transformation":   {2025: 16, 2028: 28, 2030: 40, 2035: 65, 2040: 78, 2050: 90},
    "falling_short":           {2025: 15, 2028: 22, 2030: 30, 2035: 45, 2040: 55, 2050: 62},
}

# year -> GW installed wind (onshore + offshore), per pathway
WIND_INSTALLED_GW: dict[str, dict[int, float]] = {
    # NESO FES 2024 ES.1.1
    "leading_the_way":        {2025: 30, 2028: 50, 2030: 70, 2035: 110, 2040: 130, 2050: 160},
    "consumer_transformation": {2025: 29, 2028: 46, 2030: 60, 2035: 95,  2040: 120, 2050: 150},
    "system_transformation":   {2025: 28, 2028: 42, 2030: 55, 2035: 85,  2040: 105, 2050: 130},
    "falling_short":           {2025: 27, 2028: 36, 2030: 45, 2035: 65,  2040: 80,  2050: 95},
}

# Regional capture-price adjustment factors vs GB average
# Source: Cornwall Insight "GB Zonal Price Outlook" Q1 2026 — reflects
# locational spread that will widen if REMA zonal pricing is adopted.
REGION_FACTOR_SOLAR: dict[str, float] = {
    "gb":              1.00,
    "south_east":      1.04,  # higher demand, higher captured
    "london":          1.06,
    "east_midlands":   1.01,
    "east_of_england": 1.02,
    "south_west":      1.00,
    "west_midlands":   0.99,
    "yorkshire":       0.97,
    "north_west":      0.96,
    "north_east":      0.94,
    "scotland":        0.88,  # export-constrained north
    "wales":           0.95,
}

REGION_FACTOR_WIND: dict[str, float] = {
    "gb":              1.00,
    "south_east":      1.05,
    "london":          1.07,
    "east_midlands":   1.02,
    "east_of_england": 1.03,
    "south_west":      1.01,
    "west_midlands":   1.00,
    "yorkshire":       0.97,
    "north_west":      0.95,
    "north_east":      0.92,
    "scotland":        0.82,  # TEC-constrained, significant curtailment
    "wales":           0.93,
}

# ---------------------------------------------------------------------------
# Baseline capture prices (£/MWh, 2026 real) at a reference GW level.
# From Cornwall Insight Q1 2026 capture-price curves.
# Solar curve anchor: 2025 solar capture = £52/MWh at 17 GW installed.
# Wind  curve anchor: 2025 wind  capture = £59/MWh at 29 GW installed.
# ---------------------------------------------------------------------------

# (year, £/MWh baseline GB capture) — Cornwall Insight Q1 2026 central
SOLAR_BASELINE_GBP_MWH: dict[int, float] = {
    2025: 52.0, 2026: 49.0, 2027: 46.5, 2028: 44.0, 2029: 42.0,
    2030: 40.5, 2031: 39.5, 2032: 38.0, 2033: 37.0, 2034: 36.5,
    2035: 36.0, 2040: 34.0, 2045: 33.0, 2050: 32.0,
}
WIND_BASELINE_GBP_MWH: dict[int, float] = {
    2025: 59.0, 2026: 57.0, 2027: 55.0, 2028: 53.5, 2029: 52.0,
    2030: 51.0, 2031: 50.0, 2032: 49.0, 2033: 48.5, 2034: 48.0,
    2035: 47.5, 2040: 46.0, 2045: 45.0, 2050: 44.0,
}

# ---------------------------------------------------------------------------
# Cannibalisation — multiplier on captured price as more of same tech adds.
# Solar cannibalisation above 40 GW is non-linear (Aurora SolAR3 2025).
# Each additional 10 GW solar over the 40 GW threshold chops ~5 £/MWh.
# Wind is gentler: each 20 GW ~3 £/MWh.
# ---------------------------------------------------------------------------

SOLAR_CANNIBAL_THRESHOLD_GW: float = 40.0   # Aurora SolAR3 2025 "knee"
SOLAR_CANNIBAL_GBP_PER_GW: float = 0.5      # Above the knee, £/MWh per GW
WIND_CANNIBAL_GBP_PER_GW: float = 0.15      # Aurora WIM 2025 gentler slope

# ---------------------------------------------------------------------------
# BESS arb & ancillary — Modo GB BESS Index Mar 2026
# 2h arb dropped from £110k/MW/yr (2023) to £85k (2026) to £45k (2032F).
# ---------------------------------------------------------------------------

BESS_ARB_BY_YEAR_2H_GBP_MW_YR: dict[int, float] = {
    # Modo Energy GB BESS Index, March 2026 report
    2024: 100_000, 2025: 92_000, 2026: 85_000, 2027: 78_000,
    2028: 70_000,  2029: 62_000, 2030: 55_000, 2031: 50_000,
    2032: 45_000,  2033: 42_000, 2035: 38_000,
}

# Duration scalars vs 2h (Modo "Duration Premium" chart Mar 2026)
BESS_DURATION_SCALAR: dict[int, float] = {
    1: 0.65,
    2: 1.00,
    4: 1.35,   # 35% premium 4h over 2h
    8: 1.55,   # 55% premium 8h over 2h
}

# Ancillary capacity revenues (£/MW/h clearing) — NESO BSUoS monthly auctions
# Jan-Mar 2026 trailing 3mo average. LCP Delta Q1 2026 outlook.
# All normalised to £/MW/yr assuming stated availability fraction.
ANCILLARY_GBP_MW_YR: dict[str, float] = {
    # NESO DC-L Jan-Mar 2026 avg £8.5/MW/h * 24*365 * 70% availability
    "DC_L": 52_000,   # Dynamic Containment Low
    "DC_H": 48_000,   # Dynamic Containment High — slightly thinner market
    "FFR":  24_000,   # Firm Frequency Response — legacy, thinning
    "DR":   38_000,   # Dynamic Regulation (new service launched 2023)
    "DM":   40_000,   # Dynamic Moderation
}


# ---------------------------------------------------------------------------
# Helpers — interpolation
# ---------------------------------------------------------------------------

def _interp(series: dict[int, float], year: int) -> float:
    """Linear interp / clip into a {year: value} series."""
    if not series:
        return 0.0
    years = sorted(series.keys())
    if year <= years[0]:
        return series[years[0]]
    if year >= years[-1]:
        return series[years[-1]]
    # find bracket
    for i in range(len(years) - 1):
        y0, y1 = years[i], years[i + 1]
        if y0 <= year <= y1:
            v0, v1 = series[y0], series[y1]
            return v0 + (v1 - v0) * (year - y0) / (y1 - y0)
    return series[years[-1]]


def installed_solar_gw(year: int, pathway: str = "central") -> float:
    """Installed GW solar PV by year, under given FES 2024 pathway.

    ``central`` maps to System Transformation (FES 2024 central case per
    Ofgem/NESO 2024 FES workshop slides).
    """
    p = _normalise_pathway(pathway)
    return _interp(SOLAR_INSTALLED_GW[p], year)


def installed_wind_gw(year: int, pathway: str = "central") -> float:
    """Installed GW wind (on+offshore) by year, per pathway."""
    p = _normalise_pathway(pathway)
    return _interp(WIND_INSTALLED_GW[p], year)


def _normalise_pathway(pathway: str) -> str:
    p = (pathway or "central").lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "central": "system_transformation",  # NESO FES 2024 "central" ≈ ST
        "lw":      "leading_the_way",
        "ct":      "consumer_transformation",
        "st":      "system_transformation",
        "fs":      "falling_short",
    }
    return aliases.get(p, p) if p in SOLAR_INSTALLED_GW or p in aliases else "system_transformation"


# ---------------------------------------------------------------------------
# Public API — capture prices
# ---------------------------------------------------------------------------

def capture_price_solar(
    year: int,
    region: str = "gb",
    pathway: str = "central",
) -> float:
    """UK solar captured £/MWh in ``year`` under ``pathway`` for ``region``.

    Formula:
        capture = baseline(year) * region_factor * cannibal(gw_installed)

    The baseline already embeds expected merit-order shift to 2050 per
    Cornwall Insight Q1 2026 central case. Cannibal kicks in above
    ``SOLAR_CANNIBAL_THRESHOLD_GW`` per Aurora SolAR3.
    """
    base = _interp(SOLAR_BASELINE_GBP_MWH, year)
    gw = installed_solar_gw(year, pathway)
    cann = cannibalisation_factor("solar", year, gw, pathway)
    rf = REGION_FACTOR_SOLAR.get((region or "gb").lower(), 1.0)
    return round(base * rf * cann, 2)


def capture_price_wind(
    year: int,
    region: str = "gb",
    pathway: str = "central",
) -> float:
    """UK wind captured £/MWh in ``year`` under ``pathway`` for ``region``."""
    base = _interp(WIND_BASELINE_GBP_MWH, year)
    gw = installed_wind_gw(year, pathway)
    cann = cannibalisation_factor("wind", year, gw, pathway)
    rf = REGION_FACTOR_WIND.get((region or "gb").lower(), 1.0)
    return round(base * rf * cann, 2)


def capture_price_bess_arb(
    year: int,
    duration_h: int = 2,
    region: str = "gb",
) -> float:
    """BESS wholesale-arb revenue £/MW/yr for a ``duration_h``-hour battery.

    duration=2 maps to the Modo "2h reference" benchmark. Other durations
    scale via ``BESS_DURATION_SCALAR``. Regional factor uses the same
    wind regional factor because BESS wholesale arb tracks wind-adjacent
    nodal congestion more than demand-adjacent (LCP Delta Q1 2026).
    """
    base = _interp(BESS_ARB_BY_YEAR_2H_GBP_MW_YR, year)
    scalar = BESS_DURATION_SCALAR.get(int(duration_h), 1.0)
    rf = REGION_FACTOR_WIND.get((region or "gb").lower(), 1.0)
    return round(base * scalar * rf, 0)


def capture_price_bess_ancillary(
    year: int,
    service: Literal["DC_L", "DC_H", "FFR", "DR", "DM"] = "DC_L",
) -> float:
    """Expected £/MW/yr for a single ancillary service, assuming a single
    BESS wins clearing at average price.

    Services saturate as more batteries enter — we apply a decay curve:
    DC-L 2026 £52k → 2030 £30k → 2035 £18k (LCP Delta Q1 2026 outlook).
    """
    base = ANCILLARY_GBP_MW_YR.get(service.upper(), 0.0)
    # Saturation decay — doubles every 5 years from 2026 baseline
    decay_years = max(0, year - 2026)
    decay = 0.5 ** (decay_years / 5.0)
    return round(base * decay, 0)


def cannibalisation_factor(
    tech: str,
    year: int,
    gb_installed_mw: float | None = None,
    pathway: str = "central",
) -> float:
    """Multiplier to apply to baseline-capture price given deployment.

    Returns ≤1.0 once the cannibal threshold is crossed. Aurora SolAR3
    methodology: f = 1 − (installed_gw − threshold)/gw_sensitivity.
    Floored at 0.45 so the math never goes negative — deepest Aurora
    2050 tail scenario is ~0.5 (solar 110 GW / Leading the Way).
    """
    t = (tech or "solar").lower()
    if gb_installed_mw is None:
        # Default: look up installed capacity for the year+pathway
        if t == "solar":
            gw = installed_solar_gw(year, pathway)
        elif t in {"wind", "onshore_wind", "offshore_wind"}:
            gw = installed_wind_gw(year, pathway)
        else:
            return 1.0
    else:
        gw = gb_installed_mw / 1000.0  # accept MW for ergonomics

    if t == "solar":
        if gw <= SOLAR_CANNIBAL_THRESHOLD_GW:
            return 1.0
        # Above threshold: baseline already prices in some cannibal,
        # we model the residual delta above the forecast.
        excess_gw = gw - SOLAR_CANNIBAL_THRESHOLD_GW
        # Aurora SolAR3: ~£5/MWh shed per 10 GW above 40 GW, on a ~£40 base.
        # That's a ~12%/10GW multiplier drop.
        factor = 1.0 - (excess_gw * SOLAR_CANNIBAL_GBP_PER_GW / 40.0)
        return round(max(0.45, factor), 3)

    if t in {"wind", "onshore_wind", "offshore_wind"}:
        # Wind gentler — Aurora WIM 2025: ~£3/MWh shed per 20 GW.
        excess_gw = max(0.0, gw - 40.0)  # baseline tuned to 2025 ~30 GW
        factor = 1.0 - (excess_gw * WIND_CANNIBAL_GBP_PER_GW / 50.0)
        return round(max(0.55, factor), 3)

    return 1.0


# ---------------------------------------------------------------------------
# Curve export — for frontend charting & Monte Carlo integration
# ---------------------------------------------------------------------------

def capture_curve(
    tech: str,
    year_start: int = 2026,
    year_end: int = 2040,
    region: str = "gb",
    pathway: str = "central",
) -> list[dict]:
    """Return {year, gbp_mwh, cannibal, installed_gw} series for charting."""
    t = (tech or "solar").lower()
    rows: list[dict] = []
    for yr in range(year_start, year_end + 1):
        if t == "solar":
            price = capture_price_solar(yr, region, pathway)
            gw = installed_solar_gw(yr, pathway)
        elif t in {"wind", "onshore_wind", "offshore_wind"}:
            price = capture_price_wind(yr, region, pathway)
            gw = installed_wind_gw(yr, pathway)
        else:
            price = 0.0
            gw = 0.0
        rows.append({
            "year": yr,
            "gbp_mwh": price,
            "cannibal_factor": cannibalisation_factor(t, yr, None, pathway),
            "installed_gw": round(gw, 1),
        })
    return rows


def stacked_bess_revenue(
    year: int,
    duration_h: int = 2,
    region: str = "gb",
    services: tuple[str, ...] = ("arb", "DC_L"),
) -> dict:
    """Naive stacked revenue proxy — delegates to dispatch_model for
    the full LP-style allocation. Here just sums without availability
    conflicts (upper bound).
    """
    stack: list[dict] = []
    total = 0.0
    for s in services:
        if s == "arb":
            v = capture_price_bess_arb(year, duration_h, region)
            stack.append({"service": "Wholesale arbitrage", "gbp_mw_yr": v})
            total += v
        elif s.upper() in ANCILLARY_GBP_MW_YR:
            v = capture_price_bess_ancillary(year, s.upper())  # type: ignore[arg-type]
            stack.append({"service": s.upper(), "gbp_mw_yr": v})
            total += v
    return {"year": year, "duration_h": duration_h, "stack": stack,
            "total_gbp_mw_yr": round(total, 0)}


def cite() -> str:
    """Sources used throughout this module."""
    return (
        "Cornwall Insight GB Solar+Wind Capture Price Forecast Q1 2026 + "
        "Aurora Energy Research SolAR3/WIM 2025 + "
        "NESO FES 2024 Data Workbook (Feb 2024) + "
        "Modo Energy GB BESS Index Mar 2026 + "
        "NESO BSUoS auction clearing Jan-Mar 2026 + "
        "LCP Delta GB Ancillary Services Outlook Q1 2026"
    )

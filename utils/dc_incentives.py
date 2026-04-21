"""
dc_incentives.py — UK Enterprise Zone, Freeport & incentive scoring for DC site selection.

Calculates financial incentive value from proximity to UK Freeports,
Investment Zones, and Enterprise Zones.  Produces a 0-100 incentive score
and 10-year incentive value estimate for TCO modelling.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import asyncpg

from utils import dc_benchmarks as _bench

log = logging.getLogger("princeps.dc_incentives")

# ---------------------------------------------------------------------------
# UK Enterprise Zones with DC-relevant incentives
# ---------------------------------------------------------------------------
#
# NOTE (2026-04 audit): ``rates_relief_5yr`` is NOT a flat per-zone constant.
# HMT Freeport / Investment Zone / Enterprise Zone relief scales with
# rateable value, which for a data centre scales with IT load. The zone
# table below only records the *scheme type*; actual £ relief is computed
# by ``utils.dc_benchmarks.rates_relief_5yr_gbp(it_load_mw, zone_type)``.
#
# Previously all 7 freeports carried the same £275_000 number, which is
# correct for a ~2 MW pilot but understates a 100 MW hyperscaler by ~20×.
UK_ENTERPRISE_ZONES: list[dict[str, Any]] = [
    {"name": "Humber", "lat": 53.74, "lon": -0.35, "radius_km": 15, "type": "freeport",
     "capital_allowance_pct": 100, "notes": "Freeport tax site"},
    {"name": "Teesside", "lat": 54.60, "lon": -1.07, "radius_km": 20, "type": "freeport_ai_zone",
     "capital_allowance_pct": 100,
     "notes": "Freeport + AI Growth Zone — streamlined DC planning"},
    {"name": "Thames Freeport", "lat": 51.49, "lon": 0.27, "radius_km": 15, "type": "freeport",
     "capital_allowance_pct": 100, "notes": "London Gateway + Tilbury"},
    {"name": "Liverpool City Region Freeport", "lat": 53.35, "lon": -2.98, "radius_km": 15,
     "type": "freeport", "capital_allowance_pct": 100,
     "notes": "Wirral Waters + Liverpool2"},
    {"name": "Solent Freeport", "lat": 50.80, "lon": -1.30, "radius_km": 15, "type": "freeport",
     "capital_allowance_pct": 100, "notes": "Southampton + Isle of Wight"},
    {"name": "East Midlands Freeport", "lat": 52.83, "lon": -1.33, "radius_km": 15,
     "type": "freeport", "capital_allowance_pct": 100,
     "notes": "East Midlands Airport + Ratcliffe-on-Soar"},
    {"name": "Plymouth & South Devon Freeport", "lat": 50.37, "lon": -4.14, "radius_km": 10,
     "type": "freeport", "capital_allowance_pct": 100, "notes": "Devonport"},
    {"name": "West Midlands Investment Zone", "lat": 52.48, "lon": -1.89, "radius_km": 20,
     "type": "investment_zone", "capital_allowance_pct": 0,
     "notes": "£160M funding"},
    {"name": "Greater Manchester Investment Zone", "lat": 53.48, "lon": -2.24, "radius_km": 20,
     "type": "investment_zone", "capital_allowance_pct": 0,
     "notes": "Advanced manufacturing focus"},
    {"name": "West Yorkshire Investment Zone", "lat": 53.80, "lon": -1.55, "radius_km": 15,
     "type": "investment_zone", "capital_allowance_pct": 0,
     "notes": "Life sciences + digital"},
    {"name": "Doncaster (Amazon HQ2 area)", "lat": 53.52, "lon": -1.13, "radius_km": 10,
     "type": "enterprise_zone", "capital_allowance_pct": 0,
     "notes": "iPort logistics hub"},
    {"name": "Harlow Enterprise Zone", "lat": 51.77, "lon": 0.10, "radius_km": 5,
     "type": "enterprise_zone", "capital_allowance_pct": 0,
     "notes": "Near M11 corridor"},
]

# Default CAPEX estimate per MW (GBP) if not provided — sourced from
# dc_benchmarks so it stays in sync with the H1 2025 Cushman midpoint
# (£4.2 M/MW IT Tier 3 all-in). Was £8 M/MW pre-audit — 90% above market.
DEFAULT_CAPEX_PER_MW_GBP = int(_bench.capex_per_mw_m(tier=3, redundancy="N+1") * 1_000_000)

# Business rates for DC (approximate GBP per MW of IT load per year).
# Kept for backward compat — canonical source is dc_benchmarks.RATES_PER_MW_YR.
DC_RATES_PER_MW_YR = _bench.RATES_PER_MW_YR


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(min(1.0, math.sqrt(a)))


# ---------------------------------------------------------------------------
# Zone matching
# ---------------------------------------------------------------------------

def _find_qualifying_zones(
    lat: float,
    lon: float,
    max_distance_km: float = 50.0,
    capacity_mw: float = 2.0,
) -> list[dict[str, Any]]:
    """
    Find all Enterprise Zones / Freeports / Investment Zones within
    max_distance_km of the site, sorted by distance.

    ``rates_relief_5yr`` is computed per-zone via
    ``dc_benchmarks.rates_relief_5yr_gbp(capacity_mw, zone_type)`` so that
    a 50 MW hyperscaler gets a realistic multi-million £ number rather
    than the 2 MW anchor of £275k.
    """
    results: list[dict[str, Any]] = []
    for zone in UK_ENTERPRISE_ZONES:
        dist = _haversine(lat, lon, zone["lat"], zone["lon"])
        if dist <= max_distance_km:
            results.append({
                "name": zone["name"],
                "type": zone["type"],
                "distance_km": round(dist, 1),
                "within_boundary": dist <= zone["radius_km"],
                "rates_relief_5yr": _bench.rates_relief_5yr_gbp(capacity_mw, zone["type"]),
                "capital_allowance_pct": zone["capital_allowance_pct"],
                "notes": zone["notes"],
            })
    results.sort(key=lambda z: z["distance_km"])
    return results


def _score_zone_type(zone_type: str) -> int:
    """Base score for a zone type when site is within boundary."""
    scores = {
        "freeport_ai_zone": 100,
        "freeport": 80,
        "investment_zone": 60,
        "enterprise_zone": 40,
    }
    return scores.get(zone_type, 20)


def _compute_incentive_score(
    zones: list[dict[str, Any]],
) -> int:
    """
    Compute 0-100 incentive score from qualifying zones.

    Scoring:
    - 100 if inside a Freeport + AI Zone boundary
    - 80  if inside a Freeport boundary
    - 60  if inside an Investment Zone boundary
    - 40  if inside an Enterprise Zone boundary
    - 20  if within 20 km of any zone
    - 10  if within 50 km of any zone
    - 5   otherwise (no zones nearby)
    """
    if not zones:
        return 5

    # Check for zones where site is within boundary
    for z in zones:
        if z["within_boundary"]:
            return _score_zone_type(z["type"])

    # Not inside any zone — score by proximity
    nearest = zones[0]["distance_km"]
    if nearest <= 20:
        return 20
    if nearest <= 50:
        return 10
    return 5


def _compute_incentive_value_10yr(
    zones: list[dict[str, Any]],
    capacity_mw: float,
    capex_gbp: float,
) -> int:
    """
    Estimate 10-year incentive value in GBP.

    Includes:
    - Business rates relief (5-year, pro-rated to 10yr at 50% for years 6-10)
    - Enhanced capital allowances (first-year 100% write-off)
    - Estimated SDLT relief for Freeport sites
    """
    if not zones:
        return 0

    # Use the best qualifying zone (within boundary preferred)
    best = None
    for z in zones:
        if z["within_boundary"]:
            best = z
            break
    if best is None:
        # No zone boundary match — minimal benefit
        return 0

    # Rates relief: 5yr full + 5yr at 50% (discretionary extension).
    # ``best["rates_relief_5yr"]`` is already the full 5-yr figure scaled
    # for site IT load (computed in ``_find_qualifying_zones`` via
    # ``dc_benchmarks.rates_relief_5yr_gbp``), so we use it directly.
    annual_rates = DC_RATES_PER_MW_YR * capacity_mw
    rates_5yr = min(best["rates_relief_5yr"], int(annual_rates * 5))
    rates_10yr = rates_5yr + int(rates_5yr * 0.5)  # 50% extension years 6-10

    # Enhanced capital allowances
    allowance_pct = best["capital_allowance_pct"]
    # Tax saving = allowance * effective rate (25% corporation tax)
    capital_allowance_saving = int(capex_gbp * (allowance_pct / 100.0) * 0.25)

    # SDLT relief (Freeport only, ~2% of land value, assume 5% of CAPEX)
    sdlt_saving = 0
    if "freeport" in best["type"]:
        estimated_land_value = capex_gbp * 0.05
        sdlt_saving = int(estimated_land_value * 0.02)

    total = rates_10yr + capital_allowance_saving + sdlt_saving
    return total


# ---------------------------------------------------------------------------
# Main assessment
# ---------------------------------------------------------------------------

async def score_incentives(
    conn: asyncpg.Connection,
    lat: float,
    lon: float,
    capacity_mw: float = 100,
    capex_gbp: float | None = None,
) -> dict[str, Any]:
    """
    Score UK incentive eligibility for a data-centre site.

    Parameters
    ----------
    conn : asyncpg.Connection
        Database connection (reserved for future DB-backed zone boundaries).
    lat, lon : float
        Site coordinates in WGS84.
    capacity_mw : float
        Proposed IT load in MW.
    capex_gbp : float | None
        Total capital expenditure.  Defaults to capacity_mw * 8M.

    Returns
    -------
    dict with keys:
        incentive_score         : int   (0-100)
        zones                   : list  (qualifying zones with distance/relief)
        total_rates_relief_5yr  : int   (GBP)
        total_capital_allowance_pct : int
        incentive_value_10yr_gbp: int   (GBP)
        incentive_pct_of_tco    : float (percentage of 10yr TCO)
        ai_growth_zone          : bool
        streamlined_planning    : bool
    """
    log.info("Scoring incentives at (%.4f, %.4f) for %s MW DC", lat, lon, capacity_mw)

    if capex_gbp is None:
        capex_gbp = capacity_mw * DEFAULT_CAPEX_PER_MW_GBP

    # Find qualifying zones — pass capacity so rates relief scales correctly
    zones = _find_qualifying_zones(lat, lon, max_distance_km=50.0, capacity_mw=capacity_mw)

    # Compute score
    score = _compute_incentive_score(zones)

    # Aggregate relief from best qualifying zone within boundary
    best_within = None
    for z in zones:
        if z["within_boundary"]:
            best_within = z
            break

    total_rates_5yr = best_within["rates_relief_5yr"] if best_within else 0
    total_cap_allow = best_within["capital_allowance_pct"] if best_within else 0

    # 10yr incentive value
    incentive_value = _compute_incentive_value_10yr(zones, capacity_mw, capex_gbp)

    # TCO estimate (10yr): CAPEX + OPEX (power + staff + maintenance).
    # Sourced from dc_benchmarks.opex_total_gbp_yr — 2026 UK baseline at
    # PUE 1.3, utilisation 0.85, £110/MWh PPA-mid. Prior £1.2M/MW/yr was a
    # 2023 figure that understated 2026 power costs for baseload IT loads.
    annual_opex = _bench.opex_total_gbp_yr(
        it_load_mw=capacity_mw,
        tier=3,
        workload_type="colo",
    )["total_gbp"]
    tco_10yr = capex_gbp + (annual_opex * 10)
    incentive_pct = round((incentive_value / tco_10yr * 100), 2) if tco_10yr > 0 else 0.0

    # AI Growth Zone flags
    ai_growth = any(
        z["within_boundary"] and z["type"] == "freeport_ai_zone"
        for z in zones
    )
    streamlined = ai_growth  # AI Growth Zones have streamlined DC planning

    result: dict[str, Any] = {
        "incentive_score": score,
        "zones": zones,
        "total_rates_relief_5yr": total_rates_5yr,
        "total_capital_allowance_pct": total_cap_allow,
        "incentive_value_10yr_gbp": incentive_value,
        "incentive_pct_of_tco": incentive_pct,
        "ai_growth_zone": ai_growth,
        "streamlined_planning": streamlined,
    }

    log.info("Incentive result: score=%d zones=%d value_10yr=£%s ai_zone=%s",
             score, len(zones), f"{incentive_value:,}", ai_growth)
    return result

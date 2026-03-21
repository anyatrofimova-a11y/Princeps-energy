"""
PPA Origination Engine.

Automated matching of renewable energy sites to corporate PPA buyers.
Calculates indicative PPA prices based on technology, capacity, location,
contract structure, and buyer preferences. Returns ranked counterparty
lists with match scores and pricing.

UK market focus with real corporate buyer profiles.
"""

from __future__ import annotations

import math
import random
from typing import Any


# ---------------------------------------------------------------------------
# UK Corporate PPA Buyer Database
# ---------------------------------------------------------------------------
BUYERS: list[dict[str, Any]] = [
    {
        "id": "google",
        "name": "Google",
        "type": "tech_hyperscaler",
        "min_mw": 50,
        "max_mw": 500,
        "technologies": ["solar", "wind"],
        "regions": ["all"],
        "structure": "fixed",
        "term_years": 15,
        "additionality": True,
        "24_7_cfe": True,
        "price_premium_pct": 5,
        "credit_rating": "AA+",
        "re100_member": True,
        "notes": "24/7 CFE matching programme; prefers co-located BESS",
    },
    {
        "id": "amazon_aws",
        "name": "Amazon (AWS)",
        "type": "tech_hyperscaler",
        "min_mw": 30,
        "max_mw": 400,
        "technologies": ["solar", "wind"],
        "regions": ["all"],
        "structure": "fixed",
        "term_years": 12,
        "additionality": True,
        "24_7_cfe": False,
        "price_premium_pct": 3,
        "credit_rating": "AA",
        "re100_member": True,
        "notes": "Largest global corporate PPA buyer; volume aggregator",
    },
    {
        "id": "microsoft",
        "name": "Microsoft",
        "type": "tech_hyperscaler",
        "min_mw": 50,
        "max_mw": 300,
        "technologies": ["solar", "wind"],
        "regions": ["all"],
        "structure": "pay_as_produced",
        "term_years": 15,
        "additionality": True,
        "24_7_cfe": True,
        "price_premium_pct": 5,
        "credit_rating": "AAA",
        "re100_member": True,
        "notes": "100/100/0 carbon negative commitment; 24/7 CFE pilot",
    },
    {
        "id": "tesco",
        "name": "Tesco",
        "type": "corporate",
        "min_mw": 5,
        "max_mw": 50,
        "technologies": ["solar"],
        "regions": ["England"],
        "structure": "fixed",
        "term_years": 10,
        "additionality": False,
        "24_7_cfe": False,
        "price_premium_pct": 0,
        "credit_rating": "BBB+",
        "re100_member": True,
        "notes": "UK-focused; prefers England sites near distribution centres",
    },
    {
        "id": "bt_group",
        "name": "BT Group",
        "type": "corporate",
        "min_mw": 10,
        "max_mw": 100,
        "technologies": ["solar", "wind"],
        "regions": ["all"],
        "structure": "fixed",
        "term_years": 12,
        "additionality": False,
        "24_7_cfe": False,
        "price_premium_pct": 1,
        "credit_rating": "BBB",
        "re100_member": True,
        "notes": "Net-zero by 2030; large telecoms demand profile",
    },
    {
        "id": "unilever",
        "name": "Unilever",
        "type": "corporate",
        "min_mw": 5,
        "max_mw": 30,
        "technologies": ["solar", "wind"],
        "regions": ["England"],
        "structure": "pay_as_produced",
        "term_years": 10,
        "additionality": False,
        "24_7_cfe": False,
        "price_premium_pct": 0,
        "credit_rating": "A+",
        "re100_member": True,
        "notes": "Clean Future strategy; prefers near manufacturing sites",
    },
    {
        "id": "nestle_uk",
        "name": "Nestle UK",
        "type": "corporate",
        "min_mw": 3,
        "max_mw": 25,
        "technologies": ["solar"],
        "regions": ["England", "Wales"],
        "structure": "fixed",
        "term_years": 10,
        "additionality": False,
        "24_7_cfe": False,
        "price_premium_pct": 0,
        "credit_rating": "AA-",
        "re100_member": True,
        "notes": "RE100 member; prefers solar near UK factories",
    },
    {
        "id": "national_grid_eso",
        "name": "National Grid ESO",
        "type": "utility",
        "min_mw": 50,
        "max_mw": 1000,
        "technologies": ["solar", "wind", "bess"],
        "regions": ["all"],
        "structure": "cfd",
        "term_years": 15,
        "additionality": True,
        "24_7_cfe": False,
        "price_premium_pct": 0,
        "credit_rating": "A",
        "re100_member": False,
        "notes": "CfD allocation round buyer; system balancing",
    },
    {
        "id": "edf_energy",
        "name": "EDF Energy",
        "type": "utility",
        "min_mw": 10,
        "max_mw": 200,
        "technologies": ["solar", "wind"],
        "regions": ["all"],
        "structure": "route_to_market",
        "term_years": 5,
        "additionality": False,
        "24_7_cfe": False,
        "price_premium_pct": -2,
        "credit_rating": "A-",
        "re100_member": False,
        "notes": "Route-to-market aggregator; flexible short-term deals",
    },
    {
        "id": "octopus_energy",
        "name": "Octopus Energy",
        "type": "supplier",
        "min_mw": 1,
        "max_mw": 50,
        "technologies": ["solar", "wind"],
        "regions": ["all"],
        "structure": "sleeved",
        "term_years": 5,
        "additionality": False,
        "24_7_cfe": False,
        "price_premium_pct": 0,
        "credit_rating": "BB+",
        "re100_member": False,
        "notes": "Sleeved PPA specialist; fast deal execution",
    },
    {
        "id": "shell_energy",
        "name": "Shell Energy",
        "type": "utility",
        "min_mw": 20,
        "max_mw": 300,
        "technologies": ["solar", "wind", "bess"],
        "regions": ["all"],
        "structure": "route_to_market",
        "term_years": 7,
        "additionality": False,
        "24_7_cfe": False,
        "price_premium_pct": -1,
        "credit_rating": "AA-",
        "re100_member": False,
        "notes": "Large portfolio aggregator; BESS-hybrid welcome",
    },
    {
        "id": "bp_lightsource",
        "name": "BP Lightsource",
        "type": "developer_offtaker",
        "min_mw": 10,
        "max_mw": 100,
        "technologies": ["solar"],
        "regions": ["all"],
        "structure": "fixed",
        "term_years": 15,
        "additionality": True,
        "24_7_cfe": False,
        "price_premium_pct": 2,
        "credit_rating": "A",
        "re100_member": False,
        "notes": "Solar specialist developer; co-development possible",
    },
]


# ---------------------------------------------------------------------------
# PPA Structure Definitions
# ---------------------------------------------------------------------------
PPA_STRUCTURES: dict[str, dict[str, Any]] = {
    "fixed": {
        "name": "Fixed-Price PPA",
        "description": "Developer receives a fixed price per MWh for the contract term. "
                       "Buyer bears wholesale price risk; developer has revenue certainty.",
        "risk_profile": "low_developer",
        "bankability": "high",
        "typical_term_years": "10-15",
        "price_adjustment": 0.0,
        "pros": [
            "Revenue certainty for developer",
            "Bankable for project finance",
            "Simple accounting treatment",
        ],
        "cons": [
            "Developer misses upside if prices rise",
            "Buyer locked in if prices fall",
            "Inflation risk over long term",
        ],
    },
    "pay_as_produced": {
        "name": "Pay-As-Produced PPA",
        "description": "Buyer purchases all output at an agreed price but only pays for "
                       "actual generation. Volume risk sits with the buyer.",
        "risk_profile": "medium",
        "bankability": "high",
        "typical_term_years": "10-15",
        "price_adjustment": -4.0,  # discount vs fixed
        "pros": [
            "No volume risk for developer",
            "Transparent pricing",
            "Works well for wind (variable output)",
        ],
        "cons": [
            "Buyer exposed to volume variability",
            "May need balancing arrangements",
            "Lower price than fixed (volume discount)",
        ],
    },
    "sleeved": {
        "name": "Sleeved PPA",
        "description": "A utility/supplier acts as intermediary, 'sleeving' power from "
                       "generator to corporate buyer. Provides shape management.",
        "risk_profile": "medium",
        "bankability": "medium",
        "typical_term_years": "3-7",
        "price_adjustment": -2.0,  # sleeve fee reduces net price
        "pros": [
            "Corporate buyer gets green credentials without complexity",
            "Shape management by sleeve provider",
            "Lower credit risk for developer",
        ],
        "cons": [
            "Sleeve fee reduces net revenue",
            "Shorter terms typically",
            "Less revenue certainty",
        ],
    },
    "cfd": {
        "name": "Contract for Difference (CfD)",
        "description": "Government-backed strike price. When wholesale < strike, "
                       "generator receives top-up. When wholesale > strike, generator pays back.",
        "risk_profile": "very_low",
        "bankability": "very_high",
        "typical_term_years": "15",
        "price_adjustment": -6.0,  # lower strike vs corporate PPA
        "pros": [
            "Government-backed revenue certainty",
            "Highest bankability",
            "15-year visibility",
        ],
        "cons": [
            "Competitive allocation round (may not win)",
            "Strike prices trending down",
            "Must return revenue when prices high",
        ],
    },
    "route_to_market": {
        "name": "Route-to-Market (RtM)",
        "description": "Generator sells power via a utility/trader who manages wholesale "
                       "market access. Typically short-term, rolling arrangements.",
        "risk_profile": "high",
        "bankability": "low",
        "typical_term_years": "1-5",
        "price_adjustment": -3.0,
        "pros": [
            "Flexibility to switch offtaker",
            "Capture wholesale upside",
            "Quick to execute",
        ],
        "cons": [
            "Wholesale price exposure",
            "Poor bankability for project finance",
            "RtM fee reduces revenue",
        ],
    },
}


# ---------------------------------------------------------------------------
# UK Region Mapping (lat/lon to named region)
# ---------------------------------------------------------------------------
_UK_REGIONS = {
    "Scotland": {"lat_range": (55.0, 61.0), "lon_range": (-8.0, -0.5)},
    "North East": {"lat_range": (54.0, 55.8), "lon_range": (-2.5, 0.0)},
    "North West": {"lat_range": (53.0, 55.5), "lon_range": (-3.5, -2.0)},
    "Yorkshire": {"lat_range": (53.3, 54.5), "lon_range": (-2.0, 0.0)},
    "Wales": {"lat_range": (51.3, 53.5), "lon_range": (-5.5, -2.6)},
    "Midlands": {"lat_range": (52.0, 53.3), "lon_range": (-2.5, -0.5)},
    "East Anglia": {"lat_range": (51.8, 53.0), "lon_range": (0.0, 2.0)},
    "South East": {"lat_range": (50.5, 52.0), "lon_range": (-1.5, 1.8)},
    "South West": {"lat_range": (50.0, 51.8), "lon_range": (-5.7, -1.5)},
}


def get_uk_region(lat: float, lon: float) -> str:
    """Map lat/lon to a UK region name."""
    for name, bounds in _UK_REGIONS.items():
        if (bounds["lat_range"][0] <= lat <= bounds["lat_range"][1]
                and bounds["lon_range"][0] <= lon <= bounds["lon_range"][1]):
            return name
    return "Midlands"  # default for ambiguous coords


def get_country(region: str) -> str:
    """Map region to country for buyer region-preference matching."""
    if region == "Scotland":
        return "Scotland"
    if region == "Wales":
        return "Wales"
    return "England"


# ---------------------------------------------------------------------------
# PPA Price Model
# ---------------------------------------------------------------------------
# Base prices by technology (GBP/MWh, 2025 real)
_BASE_PRICES = {
    "solar": {"low": 45.0, "mid": 50.0, "high": 55.0},
    "onshore_wind": {"low": 50.0, "mid": 55.0, "high": 60.0},
    "wind": {"low": 50.0, "mid": 55.0, "high": 60.0},  # alias
    "offshore_wind": {"low": 55.0, "mid": 62.0, "high": 70.0},
    "bess": {"low": 60.0, "mid": 70.0, "high": 85.0},  # tolling/capacity
}

# Adjustments (GBP/MWh)
_ADDITIONALITY_PREMIUM = (2.0, 5.0)   # min, max
_CFE_247_PREMIUM = (3.0, 8.0)         # 24/7 Carbon-Free Energy matching
_PAY_AS_PRODUCED_DISCOUNT = (-5.0, -3.0)
_SLEEVED_DISCOUNT = (-3.0, -1.0)
_RTM_DISCOUNT = (-4.0, -2.0)
_CFD_DISCOUNT = (-8.0, -4.0)

# Term adjustment: each year beyond 10 reduces price by 0.3 GBP/MWh
_TERM_ADJUSTMENT_PER_YEAR = -0.3
_TERM_BASE_YEARS = 10

# Location adjustments
_LOCATION_ADJUSTMENTS = {
    "Scotland": {"wind": 2.0, "onshore_wind": 2.0, "solar": -1.0},
    "South East": {"solar": 1.0, "wind": -1.0},
    "South West": {"solar": 1.5, "wind": 0.0},
    "Wales": {"wind": 1.0, "solar": -0.5},
    "East Anglia": {"solar": 0.5, "wind": 0.5},
}

# Capacity scale adjustment: larger projects get slightly better price
_CAPACITY_THRESHOLDS = [
    (100, -1.5),   # >100 MW: -1.5 GBP/MWh
    (50, -0.5),    # >50 MW: -0.5
    (10, 0.0),     # >10 MW: par
    (0, 1.5),      # <10 MW: +1.5 (small project premium)
]


def calculate_ppa_price(
    technology: str,
    capacity_mw: float,
    region: str = "Midlands",
    structure: str = "fixed",
    term_years: int = 15,
    additionality: bool = False,
    cfe_247: bool = False,
) -> dict[str, Any]:
    """
    Calculate indicative PPA price range (P10/P50/P90) for given parameters.

    Returns dict with price_p10, price_p50, price_p90, adjustments breakdown.
    """
    tech_key = technology.lower().replace(" ", "_")
    if tech_key not in _BASE_PRICES:
        tech_key = "solar"

    base = _BASE_PRICES[tech_key]

    adjustments: list[dict[str, Any]] = []

    # Structure adjustment
    struct_info = PPA_STRUCTURES.get(structure, PPA_STRUCTURES["fixed"])
    struct_adj = struct_info["price_adjustment"]
    if struct_adj != 0:
        adjustments.append({"factor": f"structure_{structure}", "gbp_mwh": struct_adj})

    # Term adjustment
    term_adj = max((term_years - _TERM_BASE_YEARS), 0) * _TERM_ADJUSTMENT_PER_YEAR
    if term_adj != 0:
        adjustments.append({"factor": "term_length", "gbp_mwh": round(term_adj, 1)})

    # Location adjustment
    loc_adj = _LOCATION_ADJUSTMENTS.get(region, {}).get(tech_key, 0.0)
    if loc_adj != 0:
        adjustments.append({"factor": f"location_{region}", "gbp_mwh": loc_adj})

    # Capacity scale
    cap_adj = 0.0
    for threshold, adj in _CAPACITY_THRESHOLDS:
        if capacity_mw >= threshold:
            cap_adj = adj
            break
    if cap_adj != 0:
        adjustments.append({"factor": "capacity_scale", "gbp_mwh": cap_adj})

    # Additionality premium
    add_adj = 0.0
    if additionality:
        add_adj = sum(_ADDITIONALITY_PREMIUM) / 2
        adjustments.append({"factor": "additionality_premium", "gbp_mwh": round(add_adj, 1)})

    # 24/7 CFE premium
    cfe_adj = 0.0
    if cfe_247:
        cfe_adj = sum(_CFE_247_PREMIUM) / 2
        adjustments.append({"factor": "24_7_cfe_matching", "gbp_mwh": round(cfe_adj, 1)})

    total_adj = struct_adj + term_adj + loc_adj + cap_adj + add_adj + cfe_adj

    # P10/P50/P90 spread: +/-10% from mid
    p50 = round(base["mid"] + total_adj, 1)
    p10 = round(base["low"] + total_adj * 0.8, 1)
    p90 = round(base["high"] + total_adj * 1.2, 1)

    return {
        "technology": technology,
        "capacity_mw": capacity_mw,
        "region": region,
        "structure": structure,
        "term_years": term_years,
        "base_price_gbp_mwh": base["mid"],
        "price_p10_gbp_mwh": p10,
        "price_p50_gbp_mwh": p50,
        "price_p90_gbp_mwh": p90,
        "total_adjustment_gbp_mwh": round(total_adj, 1),
        "adjustments": adjustments,
        "annual_revenue_estimate_gbp": {
            "p10": round(p10 * capacity_mw * _capacity_factor(tech_key) * 8760 / 1000, 0),
            "p50": round(p50 * capacity_mw * _capacity_factor(tech_key) * 8760 / 1000, 0),
            "p90": round(p90 * capacity_mw * _capacity_factor(tech_key) * 8760 / 1000, 0),
        },
        "currency": "GBP",
        "price_basis": "2025 real",
    }


def _capacity_factor(tech: str) -> float:
    """Approximate UK capacity factor by technology."""
    return {
        "solar": 0.11,
        "wind": 0.28,
        "onshore_wind": 0.28,
        "offshore_wind": 0.40,
        "bess": 0.15,  # effective utilisation
    }.get(tech, 0.20)


# ---------------------------------------------------------------------------
# Buyer Matching Engine
# ---------------------------------------------------------------------------

def match_buyers(
    technology: str,
    capacity_mw: float,
    lat: float | None = None,
    lon: float | None = None,
    region: str | None = None,
    preferred_structure: str | None = None,
    term_years: int | None = None,
    additionality: bool | None = None,
) -> list[dict[str, Any]]:
    """
    Match site characteristics to PPA buyer preferences.

    Returns ranked list of buyers with match scores and indicative prices.
    Each match includes:
    - match_score (0-100)
    - score breakdown (technology, capacity, region, structure, additionality)
    - indicative PPA price range
    - buyer profile summary
    """
    if region is None and lat is not None and lon is not None:
        region = get_uk_region(lat, lon)
    elif region is None:
        region = "Midlands"

    country = get_country(region)
    tech_key = technology.lower().replace(" ", "_")

    results = []

    for buyer in BUYERS:
        scores = {}
        disqualified = False

        # 1. Technology match (binary gate)
        buyer_techs = [t.lower().replace(" ", "_") for t in buyer["technologies"]]
        if tech_key not in buyer_techs and technology.lower() not in buyer_techs:
            continue  # hard filter
        scores["technology"] = 100

        # 2. Capacity fit
        if capacity_mw < buyer["min_mw"]:
            # Below minimum -- penalise but don't exclude
            ratio = capacity_mw / buyer["min_mw"]
            scores["capacity"] = max(0, int(ratio * 60))
            if ratio < 0.3:
                continue  # too far below minimum
        elif capacity_mw > buyer["max_mw"]:
            ratio = buyer["max_mw"] / capacity_mw
            scores["capacity"] = max(0, int(ratio * 60))
            if ratio < 0.3:
                continue
        else:
            # Within range -- score based on sweet spot (mid-range)
            mid = (buyer["min_mw"] + buyer["max_mw"]) / 2
            dist = abs(capacity_mw - mid) / mid
            scores["capacity"] = max(60, int(100 - dist * 40))

        # 3. Region preference
        buyer_regions = [r.lower() for r in buyer["regions"]]
        if "all" in buyer_regions:
            scores["region"] = 90  # slight preference for local but accepts all
        elif country.lower() in buyer_regions or region.lower() in buyer_regions:
            scores["region"] = 100
        else:
            scores["region"] = 30  # poor match but not disqualifying

        # 4. Structure alignment
        if preferred_structure:
            if preferred_structure == buyer["structure"]:
                scores["structure"] = 100
            elif preferred_structure in ("fixed", "pay_as_produced") and buyer["structure"] in ("fixed", "pay_as_produced"):
                scores["structure"] = 70  # similar enough
            else:
                scores["structure"] = 40
        else:
            scores["structure"] = 80  # no preference = neutral

        # 5. Term alignment
        if term_years:
            diff = abs(term_years - buyer["term_years"])
            scores["term"] = max(30, int(100 - diff * 8))
        else:
            scores["term"] = 80

        # 6. Additionality
        if buyer.get("additionality"):
            if additionality is True:
                scores["additionality"] = 100
            elif additionality is False:
                scores["additionality"] = 40  # buyer wants it, site doesn't offer
            else:
                scores["additionality"] = 70
        else:
            scores["additionality"] = 80  # buyer doesn't require it

        # Weighted composite score
        weights = {
            "technology": 0.25,
            "capacity": 0.20,
            "region": 0.15,
            "structure": 0.15,
            "term": 0.10,
            "additionality": 0.15,
        }
        composite = sum(scores[k] * weights[k] for k in weights)

        # Calculate indicative price for this buyer
        buyer_structure = preferred_structure or buyer["structure"]
        buyer_term = term_years or buyer["term_years"]
        price = calculate_ppa_price(
            technology=technology,
            capacity_mw=capacity_mw,
            region=region,
            structure=buyer_structure,
            term_years=buyer_term,
            additionality=buyer.get("additionality", False),
            cfe_247=buyer.get("24_7_cfe", False),
        )

        # Apply buyer-specific premium
        premium_pct = buyer.get("price_premium_pct", 0)
        if premium_pct:
            for key in ("price_p10_gbp_mwh", "price_p50_gbp_mwh", "price_p90_gbp_mwh"):
                price[key] = round(price[key] * (1 + premium_pct / 100), 1)

        results.append({
            "buyer": {
                "id": buyer["id"],
                "name": buyer["name"],
                "type": buyer["type"],
                "credit_rating": buyer.get("credit_rating", "N/A"),
                "re100_member": buyer.get("re100_member", False),
                "preferred_structure": buyer["structure"],
                "preferred_term_years": buyer["term_years"],
                "capacity_range_mw": f"{buyer['min_mw']}-{buyer['max_mw']}",
                "technologies": buyer["technologies"],
                "additionality_required": buyer.get("additionality", False),
                "24_7_cfe": buyer.get("24_7_cfe", False),
                "notes": buyer.get("notes", ""),
            },
            "match_score": round(composite),
            "score_breakdown": scores,
            "indicative_price": {
                "p10_gbp_mwh": price["price_p10_gbp_mwh"],
                "p50_gbp_mwh": price["price_p50_gbp_mwh"],
                "p90_gbp_mwh": price["price_p90_gbp_mwh"],
                "structure": buyer_structure,
                "term_years": buyer_term,
                "annual_revenue_p50_gbp": price["annual_revenue_estimate_gbp"]["p50"],
            },
            "match_quality": _quality_label(composite),
        })

    # Sort by match score descending
    results.sort(key=lambda r: r["match_score"], reverse=True)
    return results


def _quality_label(score: float) -> str:
    """Human-readable match quality label."""
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 55:
        return "moderate"
    if score >= 40:
        return "marginal"
    return "poor"


# ---------------------------------------------------------------------------
# Public API Functions
# ---------------------------------------------------------------------------

def list_buyers() -> list[dict[str, Any]]:
    """Return all buyer profiles (sanitised for API consumption)."""
    return [
        {
            "id": b["id"],
            "name": b["name"],
            "type": b["type"],
            "min_mw": b["min_mw"],
            "max_mw": b["max_mw"],
            "technologies": b["technologies"],
            "regions": b["regions"],
            "structure": b["structure"],
            "term_years": b["term_years"],
            "additionality": b.get("additionality", False),
            "24_7_cfe": b.get("24_7_cfe", False),
            "credit_rating": b.get("credit_rating", "N/A"),
            "re100_member": b.get("re100_member", False),
            "notes": b.get("notes", ""),
        }
        for b in BUYERS
    ]


def list_structures() -> dict[str, Any]:
    """Return PPA structure definitions and comparison."""
    return {
        "structures": PPA_STRUCTURES,
        "comparison_summary": {
            "most_bankable": "cfd",
            "highest_price": "fixed",
            "fastest_execution": "route_to_market",
            "best_for_corporates": "sleeved",
            "lowest_risk": "cfd",
        },
        "market_context": {
            "uk_cfd_ar6_solar_strike": 47.0,
            "uk_cfd_ar6_onshore_wind_strike": 53.0,
            "uk_corporate_ppa_trend": "increasing demand, 15% YoY growth",
            "average_uk_ppa_term_years": 12,
            "total_uk_corporate_ppas_gw": 8.5,
        },
    }


def get_price_estimate(
    technology: str,
    capacity_mw: float = 50,
    region: str = "Midlands",
    term_years: int = 15,
    structure: str = "fixed",
) -> dict[str, Any]:
    """Standalone price estimate without buyer matching."""
    return calculate_ppa_price(
        technology=technology,
        capacity_mw=capacity_mw,
        region=region,
        structure=structure,
        term_years=term_years,
    )

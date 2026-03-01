#!/usr/bin/env python3
"""
Carbon & ESG tracker — Princeps Phase 11
Lifecycle carbon accounting, grid displacement, ESG scoring.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "carbon_footprint", "capacity_mw": 50, "technology": "wind",
   "project_life_years": 25}
  {"command": "grid_displacement", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland"}
  {"command": "esg_score", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland", "community_fund": true}
"""

import json
import math
import sys

# ── Lifecycle carbon intensity (tCO2e/MW) ─────────────────────────────────

LIFECYCLE_EMISSIONS = {
    "wind": {
        "construction": {"materials": 520, "transport": 45, "installation": 30},
        "operation": {"maintenance": 8, "grid_losses": 3},  # per year
        "decommission": {"removal": 25, "recycling_credit": -15},
    },
    "solar": {
        "construction": {"materials": 680, "transport": 35, "installation": 20},
        "operation": {"maintenance": 4, "grid_losses": 2},
        "decommission": {"removal": 18, "recycling_credit": -12},
    },
    "bess": {
        "construction": {"materials": 380, "transport": 25, "installation": 15},
        "operation": {"maintenance": 5, "grid_losses": 4},
        "decommission": {"removal": 30, "recycling_credit": -20},
    },
}

# UK grid carbon intensity by region (gCO2/kWh) — 2024 averages
GRID_INTENSITY = {
    "Scotland": 95,   # High renewables penetration
    "North": 155,
    "Wales": 140,
    "Midlands": 175,
    "East": 165,
    "South": 180,
    "London": 190,
}

# Marginal grid intensity (displaced generation)
MARGINAL_INTENSITY = {
    "Scotland": 320,   # Displaces CCGT
    "North": 380,
    "Wales": 350,
    "Midlands": 410,
    "East": 390,
    "South": 420,
    "London": 430,
}

# Carbon credit price (£/tCO2e)
CARBON_PRICE = {
    "uk_ets": 48,
    "voluntary": 25,
    "corporate_offset": 35,
}

CAPACITY_FACTORS = {"wind": 0.287, "solar": 0.11, "bess": 0.90}

# ESG scoring weights
ESG_WEIGHTS = {
    "environmental": 0.40,
    "social": 0.30,
    "governance": 0.30,
}


def carbon_footprint(capacity_mw: float = 50, technology: str = "wind",
                      project_life_years: int = 25) -> dict:
    """Calculate lifecycle carbon footprint."""
    lc = LIFECYCLE_EMISSIONS.get(technology, LIFECYCLE_EMISSIONS["wind"])

    # Construction emissions
    construction = sum(lc["construction"].values()) * capacity_mw
    construction_breakdown = {k: round(v * capacity_mw) for k, v in lc["construction"].items()}

    # Operational emissions (annual)
    annual_ops = sum(lc["operation"].values()) * capacity_mw
    total_ops = annual_ops * project_life_years
    ops_breakdown = {k: round(v * capacity_mw * project_life_years) for k, v in lc["operation"].items()}

    # Decommissioning
    decom = sum(lc["decommission"].values()) * capacity_mw
    decom_breakdown = {k: round(v * capacity_mw) for k, v in lc["decommission"].items()}

    total = construction + total_ops + decom

    # Generation-intensity (gCO2/kWh)
    cf = CAPACITY_FACTORS.get(technology, 0.25)
    lifetime_gen_mwh = capacity_mw * cf * 8760 * project_life_years
    intensity_g_kwh = (total * 1000) / max(lifetime_gen_mwh, 1)  # tCO2e → kgCO2e → gCO2/kWh

    # Carbon payback (vs average grid)
    avg_grid = 170  # gCO2/kWh UK average
    annual_displacement = capacity_mw * cf * 8760 * avg_grid / 1e3  # MWh * gCO2/kWh / 1000 → tCO2e/yr
    payback_months = round(construction / max(annual_displacement, 1) * 12)

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "project_life_years": project_life_years,
        },
        "lifecycle_emissions_tco2e": {
            "construction": round(construction),
            "construction_breakdown": construction_breakdown,
            "operation": round(total_ops),
            "operation_breakdown": ops_breakdown,
            "decommissioning": round(decom),
            "decommission_breakdown": decom_breakdown,
            "total": round(total),
        },
        "intensity": {
            "g_co2_per_kwh": round(intensity_g_kwh, 1),
            "vs_gas_ccgt": f"{round(intensity_g_kwh / 400 * 100)}% of gas",
            "vs_coal": f"{round(intensity_g_kwh / 900 * 100)}% of coal",
            "vs_grid_avg": f"{round(intensity_g_kwh / avg_grid * 100)}% of grid",
        },
        "carbon_payback": {
            "months": payback_months,
            "years": round(payback_months / 12, 1),
            "lifetime_net_savings_tco2e": round(annual_displacement * project_life_years - total),
        },
        "carbon_credit_value": {
            "uk_ets_gbp": round(total * CARBON_PRICE["uk_ets"]),
            "voluntary_gbp": round(total * CARBON_PRICE["voluntary"]),
            "annual_displacement_credits_gbp": round(annual_displacement * CARBON_PRICE["corporate_offset"]),
        },
    }


def grid_displacement(capacity_mw: float = 50, technology: str = "wind",
                       region: str = "Scotland",
                       project_life_years: int = 25) -> dict:
    """Calculate grid carbon displacement by region."""
    cf = CAPACITY_FACTORS.get(technology, 0.25)
    annual_gen_mwh = capacity_mw * cf * 8760

    # Average displacement
    avg_intensity = GRID_INTENSITY.get(region, 170)
    avg_displaced = annual_gen_mwh * avg_intensity / 1e3  # MWh * gCO2/kWh / 1000 → tCO2e/yr

    # Marginal displacement (what we actually displace)
    marginal = MARGINAL_INTENSITY.get(region, 400)
    marginal_displaced = annual_gen_mwh * marginal / 1e3

    # Hourly profile (simplified — higher displacement at peak)
    hourly = []
    for h in range(24):
        # Grid intensity varies by hour
        peak_factor = 0.7 + 0.6 * max(
            math.exp(-0.5 * ((h - 8) / 3) ** 2),
            math.exp(-0.5 * ((h - 17) / 3) ** 2),
        )
        hour_intensity = marginal * peak_factor
        hour_gen = annual_gen_mwh / 8760  # Simplified flat
        hour_displaced = hour_gen * hour_intensity / 1e3 * 365

        hourly.append({
            "hour": h,
            "marginal_intensity_g_kwh": round(hour_intensity),
            "annual_displaced_tco2e": round(hour_displaced, 1),
        })

    # Lifetime totals
    lifetime_displaced = marginal_displaced * project_life_years

    # Equivalents
    homes_heated = round(marginal_displaced / 2.7)  # avg UK home ~2.7 tCO2/yr
    flights_ldn_nyc = round(marginal_displaced / 0.99)  # ~0.99 tCO2 per flight
    cars_removed = round(marginal_displaced / 1.8)  # avg UK car ~1.8 tCO2/yr

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
        },
        "annual_displacement": {
            "average_tco2e": round(avg_displaced),
            "marginal_tco2e": round(marginal_displaced),
            "marginal_intensity_g_kwh": marginal,
            "grid_avg_intensity_g_kwh": avg_intensity,
        },
        "lifetime": {
            "total_displaced_tco2e": round(lifetime_displaced),
            "carbon_value_gbp": round(lifetime_displaced * CARBON_PRICE["corporate_offset"]),
        },
        "equivalents": {
            "homes_heated_gas": homes_heated,
            "flights_ldn_nyc": flights_ldn_nyc,
            "cars_removed": cars_removed,
        },
        "hourly_profile": hourly,
    }


def esg_score(capacity_mw: float = 50, technology: str = "wind",
               region: str = "Scotland", community_fund: bool = True,
               shared_ownership: bool = False,
               biodiversity_net_gain: bool = True) -> dict:
    """Comprehensive ESG scoring across 3 pillars."""

    # Environmental pillar (0-100)
    cf = CAPACITY_FACTORS.get(technology, 0.25)
    annual_gen_mwh = capacity_mw * cf * 8760
    marginal = MARGINAL_INTENSITY.get(region, 400)
    displaced_tco2 = annual_gen_mwh * marginal / 1e3

    env_scores = {
        "carbon_displacement": min(100, round(displaced_tco2 / 50 * 100)),  # 50 tCO2 = 100
        "lifecycle_intensity": {"wind": 92, "solar": 88, "bess": 75}.get(technology, 80),
        "land_use_efficiency": {"wind": 85, "solar": 70, "bess": 90}.get(technology, 75),
        "biodiversity": 80 if biodiversity_net_gain else 45,
        "water_impact": {"wind": 95, "solar": 90, "bess": 85}.get(technology, 85),
    }
    env_total = round(sum(env_scores.values()) / len(env_scores))

    # Social pillar (0-100)
    soc_scores = {
        "community_fund": 85 if community_fund else 30,
        "shared_ownership": 90 if shared_ownership else 40,
        "local_employment": min(100, round(capacity_mw * 0.8)),  # Jobs scale with size
        "visual_impact": {"wind": 55, "solar": 75, "bess": 85}.get(technology, 70),
        "noise_impact": {"wind": 60, "solar": 95, "bess": 90}.get(technology, 75),
    }
    soc_total = round(sum(soc_scores.values()) / len(soc_scores))

    # Governance pillar (0-100)
    gov_scores = {
        "planning_compliance": 80,
        "grid_code_compliance": 85,
        "environmental_reporting": 75 if biodiversity_net_gain else 55,
        "stakeholder_engagement": 85 if community_fund else 60,
        "supply_chain_ethics": {"wind": 70, "solar": 65, "bess": 60}.get(technology, 65),
    }
    gov_total = round(sum(gov_scores.values()) / len(gov_scores))

    # Composite
    composite = round(
        env_total * ESG_WEIGHTS["environmental"] +
        soc_total * ESG_WEIGHTS["social"] +
        gov_total * ESG_WEIGHTS["governance"]
    )

    rating = (
        "AAA" if composite >= 90 else
        "AA" if composite >= 80 else
        "A" if composite >= 70 else
        "BBB" if composite >= 60 else
        "BB" if composite >= 50 else
        "B"
    )

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "community_fund": community_fund,
            "shared_ownership": shared_ownership,
            "biodiversity_net_gain": biodiversity_net_gain,
        },
        "environmental": {"score": env_total, "components": env_scores},
        "social": {"score": soc_total, "components": soc_scores},
        "governance": {"score": gov_total, "components": gov_scores},
        "composite": {
            "score": composite,
            "rating": rating,
            "percentile": min(99, round(composite * 1.05)),
        },
        "recommendations": [
            r for r in [
                "Enable shared ownership to boost Social score by ~10pts" if not shared_ownership else None,
                "Establish community fund to improve stakeholder engagement" if not community_fund else None,
                "Implement BNG plan for biodiversity uplift" if not biodiversity_net_gain else None,
                "Consider supply chain audit for governance improvement",
            ] if r
        ],
    }


# ── Subprocess bridge ──────────────────────────────────────────────────────

def main():
    raw = sys.stdin.read()
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    cmd = req.get("command", "")
    try:
        if cmd == "carbon_footprint":
            result = carbon_footprint(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                project_life_years=req.get("project_life_years", 25),
            )
            json.dump(result, sys.stdout)
        elif cmd == "grid_displacement":
            result = grid_displacement(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                project_life_years=req.get("project_life_years", 25),
            )
            json.dump(result, sys.stdout)
        elif cmd == "esg_score":
            result = esg_score(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                community_fund=req.get("community_fund", True),
                shared_ownership=req.get("shared_ownership", False),
                biodiversity_net_gain=req.get("biodiversity_net_gain", True),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()

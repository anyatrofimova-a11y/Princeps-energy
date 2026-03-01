#!/usr/bin/env python3
"""
Curtailment estimator — Princeps Phase 8
Estimates annual curtailment (MWh lost) based on congestion probability,
DLR headroom, and Active Network Management (ANM) constraints.

Uses statistical modelling of UK grid constraint patterns.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "estimate_annual", "capacity_mw": 50, "voltage_kv": 132,
   "region": "Scotland", "connection_type": "firm"}
  {"command": "monthly_profile", "capacity_mw": 50, "region": "Scotland"}
  {"command": "revenue_impact", "capacity_mw": 50, "region": "Scotland",
   "wholesale_price_mwh": 55, "cfd_price_mwh": 0}
"""

import json
import math
import random
import sys

# ── UK regional constraint patterns (based on NESO outturn data) ──────────
# Annual curtailment rates (% of potential generation) by region
REGIONAL_CONSTRAINT_PROFILES = {
    "Scotland": {
        "base_curtailment_pct": 8.5,   # High wind constraint
        "wind_sensitivity": 1.8,        # Strong correlation with wind output
        "solar_sensitivity": 0.2,
        "seasonal_peak_month": 1,       # Jan peak (winter wind)
        "boundary": "B1",              # Scotland–England boundary
        "typical_constraint_cost_mwh": 65,
    },
    "North": {
        "base_curtailment_pct": 4.2,
        "wind_sensitivity": 1.2,
        "solar_sensitivity": 0.3,
        "seasonal_peak_month": 1,
        "boundary": "B2",
        "typical_constraint_cost_mwh": 52,
    },
    "Wales": {
        "base_curtailment_pct": 5.1,
        "wind_sensitivity": 1.4,
        "solar_sensitivity": 0.3,
        "seasonal_peak_month": 12,
        "boundary": "B7",
        "typical_constraint_cost_mwh": 48,
    },
    "Midlands": {
        "base_curtailment_pct": 2.8,
        "wind_sensitivity": 0.7,
        "solar_sensitivity": 0.5,
        "seasonal_peak_month": 7,
        "boundary": "B4",
        "typical_constraint_cost_mwh": 40,
    },
    "East": {
        "base_curtailment_pct": 3.5,
        "wind_sensitivity": 0.9,
        "solar_sensitivity": 0.6,
        "seasonal_peak_month": 7,
        "boundary": "B8",
        "typical_constraint_cost_mwh": 42,
    },
    "South": {
        "base_curtailment_pct": 2.1,
        "wind_sensitivity": 0.4,
        "solar_sensitivity": 0.8,
        "seasonal_peak_month": 7,
        "boundary": "B4",
        "typical_constraint_cost_mwh": 38,
    },
    "London": {
        "base_curtailment_pct": 1.2,
        "wind_sensitivity": 0.2,
        "solar_sensitivity": 0.3,
        "seasonal_peak_month": 7,
        "boundary": "B6",
        "typical_constraint_cost_mwh": 35,
    },
}

# Connection type multipliers on curtailment
CONNECTION_TYPE_FACTORS = {
    "firm": 0.15,      # Firm connections have very low curtailment (priority dispatch)
    "non_firm": 1.0,   # Non-firm bears full curtailment
    "anm": 0.65,       # ANM — managed curtailment, reduced but not eliminated
    "flexible": 0.75,  # Flexible connection — some curtailment expected
    "timed": 0.50,     # Timed export — restricted hours but firm during window
}

# UK capacity factors by technology and region (annual average)
CAPACITY_FACTORS = {
    "solar": {
        "Scotland": 0.095, "North": 0.100, "Wales": 0.102, "Midlands": 0.108,
        "East": 0.112, "South": 0.115, "London": 0.105,
    },
    "wind": {
        "Scotland": 0.32, "North": 0.28, "Wales": 0.30, "Midlands": 0.22,
        "East": 0.26, "South": 0.24, "London": 0.18,
    },
    "bess": {  # BESS curtailment relates to import/export constraints
        "Scotland": 0.15, "North": 0.15, "Wales": 0.15, "Midlands": 0.15,
        "East": 0.15, "South": 0.15, "London": 0.15,
    },
}

N_SAMPLES = 1500


def _monthly_curtailment_profile(region: str, technology: str = "solar") -> list:
    """Generate monthly curtailment percentage profile."""
    profile = REGIONAL_CONSTRAINT_PROFILES.get(region, REGIONAL_CONSTRAINT_PROFILES["Midlands"])
    base = profile["base_curtailment_pct"]
    peak_month = profile["seasonal_peak_month"]

    monthly = []
    for month in range(1, 13):
        # Seasonal pattern — peaks around the dominant constraint month
        seasonal = 1.0 + 0.6 * math.cos(2 * math.pi * (month - peak_month) / 12)

        # Technology-specific pattern
        if technology == "solar":
            # Solar curtailment peaks in summer (high output + daytime demand constraint)
            solar_factor = 0.5 + 0.5 * math.sin(math.pi * (month - 3) / 6)
            solar_factor = max(0.3, solar_factor)
            tech_factor = profile["solar_sensitivity"] * solar_factor
        elif technology == "wind":
            # Wind curtailment peaks in winter (high wind output vs boundary limits)
            wind_factor = 0.5 + 0.5 * math.cos(2 * math.pi * (month - 1) / 12)
            tech_factor = profile["wind_sensitivity"] * wind_factor
        else:
            tech_factor = 0.5

        curtail_pct = base * seasonal * (0.5 + tech_factor)
        curtail_pct = max(0.1, min(curtail_pct, 35))
        monthly.append(round(curtail_pct, 2))

    return monthly


def estimate_annual_curtailment(capacity_mw: float, voltage_kv: int = 132,
                                 region: str = "Midlands",
                                 technology: str = "solar",
                                 connection_type: str = "firm",
                                 queue_depth: int = 0) -> dict:
    """
    Estimate annual curtailment with Monte Carlo uncertainty.
    Returns P10/P50/P90 for curtailment hours, MWh lost, and availability.
    """
    profile = REGIONAL_CONSTRAINT_PROFILES.get(region, REGIONAL_CONSTRAINT_PROFILES["Midlands"])
    cf = CAPACITY_FACTORS.get(technology, CAPACITY_FACTORS["solar"]).get(region, 0.10)
    conn_factor = CONNECTION_TYPE_FACTORS.get(connection_type, 1.0)

    # Queue depth increases curtailment risk (more projects → more constraints)
    queue_factor = 1.0 + queue_depth * 0.08

    # Voltage level effect — lower voltage = more local constraints
    voltage_factor = 1.0
    if voltage_kv <= 33:
        voltage_factor = 1.5
    elif voltage_kv <= 66:
        voltage_factor = 1.2
    elif voltage_kv >= 275:
        voltage_factor = 0.7

    monthly_profile = _monthly_curtailment_profile(region, technology)

    # Monte Carlo simulation
    annual_mwh_samples = []
    annual_hours_samples = []
    hours_year = 8760

    for _ in range(N_SAMPLES):
        total_curtailed_mwh = 0
        total_curtailed_hours = 0

        for month_idx, base_curtail_pct in enumerate(monthly_profile):
            month_hours = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month_idx] * 24

            # Add random variation
            noise = random.gauss(1.0, 0.25)
            curtail_pct = base_curtail_pct * conn_factor * queue_factor * voltage_factor * max(0.3, noise)
            curtail_pct = max(0, min(curtail_pct, 60))

            # Hours curtailed this month
            curtailed_hours = month_hours * curtail_pct / 100.0

            # MWh lost (capacity × CF × curtailment fraction)
            month_potential_mwh = capacity_mw * month_hours * cf
            curtailed_mwh = month_potential_mwh * curtail_pct / 100.0

            total_curtailed_hours += curtailed_hours
            total_curtailed_mwh += curtailed_mwh

        annual_hours_samples.append(total_curtailed_hours)
        annual_mwh_samples.append(total_curtailed_mwh)

    annual_hours_samples.sort()
    annual_mwh_samples.sort()

    # Potential generation without curtailment
    potential_mwh = capacity_mw * hours_year * cf

    # Percentile extraction
    def pcts(samples):
        return {
            "p10": round(samples[int(len(samples) * 0.1)], 1),
            "p50": round(samples[int(len(samples) * 0.5)], 1),
            "p90": round(samples[int(len(samples) * 0.9)], 1),
            "mean": round(sum(samples) / len(samples), 1),
        }

    hours_stats = pcts(annual_hours_samples)
    mwh_stats = pcts(annual_mwh_samples)

    # Availability = 1 - curtailment fraction
    availability = {
        "p10": round(1 - hours_stats["p90"] / hours_year, 4),
        "p50": round(1 - hours_stats["p50"] / hours_year, 4),
        "p90": round(1 - hours_stats["p10"] / hours_year, 4),
    }

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "voltage_kv": voltage_kv,
            "region": region,
            "technology": technology,
            "connection_type": connection_type,
            "queue_depth": queue_depth,
            "capacity_factor": cf,
        },
        "curtailment_hours": hours_stats,
        "curtailment_mwh": mwh_stats,
        "potential_generation_mwh": round(potential_mwh, 0),
        "curtailment_rate_pct": {
            "p10": round(mwh_stats["p10"] / potential_mwh * 100, 2) if potential_mwh > 0 else 0,
            "p50": round(mwh_stats["p50"] / potential_mwh * 100, 2) if potential_mwh > 0 else 0,
            "p90": round(mwh_stats["p90"] / potential_mwh * 100, 2) if potential_mwh > 0 else 0,
        },
        "availability": availability,
        "monthly_curtailment_pct": monthly_profile,
        "boundary": profile["boundary"],
        "monte_carlo_samples": N_SAMPLES,
    }


def revenue_impact(capacity_mw: float, region: str = "Midlands",
                    technology: str = "solar", connection_type: str = "firm",
                    wholesale_price_mwh: float = 55,
                    cfd_price_mwh: float = 0,
                    roc_value_mwh: float = 0,
                    years: int = 25) -> dict:
    """
    Calculate revenue impact of curtailment over project lifetime.
    """
    est = estimate_annual_curtailment(capacity_mw, 132, region, technology, connection_type)
    cf = est["parameters"]["capacity_factor"]

    # Annual potential revenue
    potential_mwh = est["potential_generation_mwh"]
    effective_price = wholesale_price_mwh + cfd_price_mwh + roc_value_mwh

    annual_potential_revenue = potential_mwh * effective_price
    lost_revenue_p50 = est["curtailment_mwh"]["p50"] * effective_price
    lost_revenue_p90 = est["curtailment_mwh"]["p90"] * effective_price

    # Lifetime impact (with 2% annual price escalation)
    lifetime_lost_p50 = 0
    lifetime_lost_p90 = 0
    yearly_breakdown = []
    for yr in range(1, years + 1):
        escalation = (1.02) ** (yr - 1)
        yr_lost_p50 = lost_revenue_p50 * escalation
        yr_lost_p90 = lost_revenue_p90 * escalation
        lifetime_lost_p50 += yr_lost_p50
        lifetime_lost_p90 += yr_lost_p90
        yearly_breakdown.append({
            "year": yr,
            "lost_revenue_p50_gbp": round(yr_lost_p50),
            "lost_revenue_p90_gbp": round(yr_lost_p90),
        })

    # NPV of lost revenue (discount rate 8%)
    npv_lost_p50 = sum(
        lost_revenue_p50 * (1.02 ** (yr - 1)) / (1.08 ** yr)
        for yr in range(1, years + 1)
    )

    return {
        "annual": {
            "potential_generation_mwh": round(potential_mwh),
            "potential_revenue_gbp": round(annual_potential_revenue),
            "lost_revenue_p50_gbp": round(lost_revenue_p50),
            "lost_revenue_p90_gbp": round(lost_revenue_p90),
            "effective_price_mwh": effective_price,
        },
        "lifetime": {
            "years": years,
            "total_lost_p50_gbp": round(lifetime_lost_p50),
            "total_lost_p90_gbp": round(lifetime_lost_p90),
            "npv_lost_p50_gbp": round(npv_lost_p50),
        },
        "curtailment": {
            "rate_p50_pct": est["curtailment_rate_pct"]["p50"],
            "mwh_lost_p50": est["curtailment_mwh"]["p50"],
            "hours_p50": est["curtailment_hours"]["p50"],
        },
        "yearly_breakdown": yearly_breakdown[:5],  # First 5 years for compactness
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
        if cmd == "estimate_annual":
            result = estimate_annual_curtailment(
                capacity_mw=req.get("capacity_mw", 50),
                voltage_kv=req.get("voltage_kv", 132),
                region=req.get("region", "Midlands"),
                technology=req.get("technology", "solar"),
                connection_type=req.get("connection_type", "firm"),
                queue_depth=req.get("queue_depth", 0),
            )
            json.dump(result, sys.stdout)
        elif cmd == "monthly_profile":
            profile = _monthly_curtailment_profile(
                req.get("region", "Midlands"),
                req.get("technology", "solar"),
            )
            json.dump({"region": req.get("region", "Midlands"), "monthly_curtailment_pct": profile}, sys.stdout)
        elif cmd == "revenue_impact":
            result = revenue_impact(
                capacity_mw=req.get("capacity_mw", 50),
                region=req.get("region", "Midlands"),
                technology=req.get("technology", "solar"),
                connection_type=req.get("connection_type", "firm"),
                wholesale_price_mwh=req.get("wholesale_price_mwh", 55),
                cfd_price_mwh=req.get("cfd_price_mwh", 0),
                roc_value_mwh=req.get("roc_value_mwh", 0),
                years=req.get("years", 25),
            )
            json.dump(result, sys.stdout)
        elif cmd == "regions":
            json.dump({
                "regions": list(REGIONAL_CONSTRAINT_PROFILES.keys()),
                "connection_types": list(CONNECTION_TYPE_FACTORS.keys()),
            }, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Revenue tracker — Princeps Phase 9
Multi-market revenue stacking: wholesale, CfD, capacity market,
frequency response, BM, embedded benefits, Triad avoidance.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "revenue_stack", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland", "connection_type": "anm", "headroom_mw": 30}
  {"command": "monthly_breakdown", "capacity_mw": 50, "technology": "solar",
   "region": "Midlands"}
  {"command": "scenario_comparison", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland"}
"""

import json
import math
import random
import sys

# ── UK energy market revenue streams ──────────────────────────────────────

# Wholesale baseload prices (£/MWh) by season
WHOLESALE_PRICES = {
    "winter": 62,   # Higher demand
    "spring": 42,
    "summer": 38,
    "autumn": 48,
}

# CfD strike prices (£/MWh) — AR6 reference
CFD_STRIKE = {
    "wind_onshore": 52.29,
    "wind_offshore": 73.00,
    "solar": 47.00,
    "bess": 0,  # No CfD for storage
}

# Capacity Market de-rating factors & clearing price
CM_DERATION = {
    "wind": 0.085,    # ~8.5% for onshore wind
    "solar": 0.035,   # ~3.5% for solar
    "bess": 0.96,     # High availability
}
CM_CLEARING_PRICE = 42000  # £/MW de-rated/year (T-4 typical)

# Frequency Response rates (£/MW/hr)
FR_RATES = {
    "dc": {"rate": 17, "availability_pct": 0.40},   # Dynamic Containment
    "dm": {"rate": 8, "availability_pct": 0.35},     # Dynamic Moderation
    "dr": {"rate": 10, "availability_pct": 0.30},    # Dynamic Regulation
    "ffr": {"rate": 12, "availability_pct": 0.45},   # Firm Frequency Response
}

# BM revenue benchmarks (£/MW/year by region)
BM_REVENUE_RATE = {
    "Scotland": {"wind": 108000, "solar": 42000, "bess": 85000},
    "North": {"wind": 72000, "solar": 35000, "bess": 78000},
    "Midlands": {"wind": 38000, "solar": 22000, "bess": 68000},
    "South": {"wind": 25000, "solar": 18000, "bess": 62000},
}

# Embedded benefits (£/MWh or £/MW/year)
EMBEDDED_BENEFITS = {
    "tnuos_demand": 5.80,     # TNUoS demand residual (£/MWh at Triad)
    "bsuos": 2.10,            # BSUoS (£/MWh)
    "tnuos_gen": -3.50,       # TNUoS generation (credit for embedded, £/MWh)
    "duos": 1.80,             # DUoS credit (£/MWh)
    "reactive_power": 2500,   # Reactive power (£/MW/year)
}

# Triad avoidance value by region (£/kW/year)
TRIAD_VALUE = {
    "Scotland": 28,
    "North": 38,
    "Midlands": 45,
    "South": 52,
    "London": 58,
}

# Technology capacity factors
CAPACITY_FACTORS = {
    "wind": {"winter": 0.35, "spring": 0.28, "summer": 0.22, "autumn": 0.30},
    "solar": {"winter": 0.08, "spring": 0.12, "summer": 0.14, "autumn": 0.10},
    "bess": {"winter": 0.92, "spring": 0.92, "summer": 0.92, "autumn": 0.92},
}

# Curtailment factors by connection type
CURTAILMENT = {
    "firm": 0.02,
    "anm": 0.12,
    "non_firm": 0.22,
    "timed": 0.08,
}

SEASONS = ["winter", "spring", "summer", "autumn"]
SEASON_MONTHS = {
    "winter": [12, 1, 2],
    "spring": [3, 4, 5],
    "summer": [6, 7, 8],
    "autumn": [9, 10, 11],
}


def revenue_stack(capacity_mw: float = 50, technology: str = "wind",
                  region: str = "Scotland", connection_type: str = "anm",
                  headroom_mw: float = 30, cfd_enabled: bool = True,
                  project_life_years: int = 25) -> dict:
    """
    Calculate full revenue stack across all available UK energy markets.
    """
    curtailment_pct = CURTAILMENT.get(connection_type, 0.10)
    export_mw = min(capacity_mw, headroom_mw) if connection_type != "firm" else capacity_mw
    cf = CAPACITY_FACTORS.get(technology, CAPACITY_FACTORS["wind"])

    # Annual generation
    annual_cf = sum(cf[s] for s in SEASONS) / 4
    gross_gen_mwh = capacity_mw * annual_cf * 8760
    net_gen_mwh = gross_gen_mwh * (1 - curtailment_pct)
    export_gen_mwh = min(net_gen_mwh, export_mw * annual_cf * 8760)

    # 1. Wholesale revenue
    wholesale_rev = 0
    for s in SEASONS:
        season_hours = 8760 / 4
        season_gen = capacity_mw * cf[s] * season_hours * (1 - curtailment_pct)
        season_export = min(season_gen, export_mw * cf[s] * season_hours)
        wholesale_rev += season_export * WHOLESALE_PRICES[s]

    # 2. CfD revenue (replaces wholesale if active)
    cfd_key = f"{technology}_onshore" if technology == "wind" else technology
    strike = CFD_STRIKE.get(cfd_key, CFD_STRIKE.get(technology, 0))
    if cfd_enabled and strike > 0:
        avg_wholesale = sum(WHOLESALE_PRICES[s] for s in SEASONS) / 4
        cfd_topup = max(0, strike - avg_wholesale)
        cfd_revenue = export_gen_mwh * cfd_topup
        # With CfD, total merchant = wholesale + CfD top-up
        total_energy_rev = export_gen_mwh * strike
    else:
        cfd_revenue = 0
        total_energy_rev = wholesale_rev

    # 3. Capacity Market
    deration = CM_DERATION.get(technology, 0.05)
    cm_revenue = capacity_mw * deration * CM_CLEARING_PRICE

    # 4. Frequency Response (BESS only meaningful)
    fr_revenue = 0
    fr_breakdown = {}
    if technology == "bess":
        for fr_name, fr_data in FR_RATES.items():
            avail_mw = export_mw * fr_data["availability_pct"]
            rev = avail_mw * fr_data["rate"] * 8760
            fr_revenue += rev
            fr_breakdown[fr_name] = round(rev)
    else:
        # Wind/solar can provide limited FFR
        ffr_avail = export_mw * 0.05
        fr_revenue = ffr_avail * FR_RATES["ffr"]["rate"] * 8760
        fr_breakdown["ffr"] = round(fr_revenue)

    # 5. BM revenue
    bm_rates = BM_REVENUE_RATE.get(region, BM_REVENUE_RATE["Midlands"])
    bm_rev = capacity_mw * bm_rates.get(technology, 30000) / 50  # Normalise to /MW then scale

    # 6. Embedded benefits
    embed_energy = export_gen_mwh * (EMBEDDED_BENEFITS["bsuos"] + EMBEDDED_BENEFITS["duos"])
    embed_tnuos = export_gen_mwh * abs(EMBEDDED_BENEFITS["tnuos_gen"])
    embed_reactive = capacity_mw * EMBEDDED_BENEFITS["reactive_power"]
    embedded_total = embed_energy + embed_tnuos + embed_reactive

    # 7. Triad avoidance
    triad_rate = TRIAD_VALUE.get(region, 40)
    # Triad: 3 peak half-hours Nov-Feb; value based on average export during Triad
    triad_export_pct = 0.6 if technology == "bess" else (0.3 if technology == "wind" else 0.05)
    triad_revenue = capacity_mw * triad_rate * triad_export_pct * 1000 / 1000  # £/kW → £/MW

    # Total annual revenue
    total_annual = (total_energy_rev + cm_revenue + fr_revenue +
                    bm_rev + embedded_total + triad_revenue)

    # Revenue per MW
    rev_per_mw = total_annual / max(capacity_mw, 1)

    # Lifetime NPV (8% discount)
    discount_rate = 0.08
    escalation = 0.02
    npv = sum(
        total_annual * (1 + escalation) ** y / (1 + discount_rate) ** y
        for y in range(project_life_years)
    )

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "connection_type": connection_type,
            "headroom_mw": headroom_mw,
            "cfd_enabled": cfd_enabled,
            "project_life_years": project_life_years,
        },
        "generation": {
            "annual_capacity_factor": round(annual_cf, 3),
            "gross_generation_mwh": round(gross_gen_mwh),
            "curtailment_pct": round(curtailment_pct * 100, 1),
            "net_generation_mwh": round(net_gen_mwh),
            "export_generation_mwh": round(export_gen_mwh),
        },
        "revenue_stack": {
            "wholesale_gbp": round(wholesale_rev),
            "cfd_topup_gbp": round(cfd_revenue),
            "total_energy_gbp": round(total_energy_rev),
            "capacity_market_gbp": round(cm_revenue),
            "frequency_response_gbp": round(fr_revenue),
            "fr_breakdown": fr_breakdown,
            "balancing_mechanism_gbp": round(bm_rev),
            "embedded_benefits_gbp": round(embedded_total),
            "triad_avoidance_gbp": round(triad_revenue),
            "total_annual_gbp": round(total_annual),
            "revenue_per_mw_gbp": round(rev_per_mw),
        },
        "revenue_shares": {
            "energy_pct": round(total_energy_rev / max(total_annual, 1) * 100, 1),
            "capacity_market_pct": round(cm_revenue / max(total_annual, 1) * 100, 1),
            "frequency_response_pct": round(fr_revenue / max(total_annual, 1) * 100, 1),
            "bm_pct": round(bm_rev / max(total_annual, 1) * 100, 1),
            "embedded_pct": round(embedded_total / max(total_annual, 1) * 100, 1),
            "triad_pct": round(triad_revenue / max(total_annual, 1) * 100, 1),
        },
        "lifetime": {
            "npv_gbp": round(npv),
            "undiscounted_total_gbp": round(total_annual * project_life_years),
            "discount_rate": discount_rate,
            "escalation_rate": escalation,
        },
    }


def monthly_breakdown(capacity_mw: float = 50, technology: str = "solar",
                       region: str = "Midlands", connection_type: str = "anm",
                       headroom_mw: float = 30) -> dict:
    """
    Monthly revenue breakdown across all markets.
    """
    curtailment_pct = CURTAILMENT.get(connection_type, 0.10)
    export_mw = min(capacity_mw, headroom_mw) if connection_type != "firm" else capacity_mw
    cf = CAPACITY_FACTORS.get(technology, CAPACITY_FACTORS["wind"])
    bm_rates = BM_REVENUE_RATE.get(region, BM_REVENUE_RATE["Midlands"])
    bm_per_mw = bm_rates.get(technology, 30000) / 50

    monthly = []
    total_gen = 0
    total_rev = 0

    for m in range(1, 13):
        # Determine season
        season = next(s for s, months in SEASON_MONTHS.items() if m in months)
        days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        hours = days * 24

        # Generation
        gen_mwh = capacity_mw * cf[season] * hours * (1 - curtailment_pct)
        export_mwh = min(gen_mwh, export_mw * cf[season] * hours)

        # Wholesale
        wholesale = export_mwh * WHOLESALE_PRICES[season]

        # CfD top-up
        cfd_key = f"{technology}_onshore" if technology == "wind" else technology
        strike = CFD_STRIKE.get(cfd_key, CFD_STRIKE.get(technology, 0))
        cfd = export_mwh * max(0, strike - WHOLESALE_PRICES[season]) if strike > 0 else 0

        # CM (monthly split)
        deration = CM_DERATION.get(technology, 0.05)
        cm = capacity_mw * deration * CM_CLEARING_PRICE / 12

        # BM (monthly split)
        bm = capacity_mw * bm_per_mw / 12

        # Embedded
        embed = export_mwh * (EMBEDDED_BENEFITS["bsuos"] + EMBEDDED_BENEFITS["duos"] +
                               abs(EMBEDDED_BENEFITS["tnuos_gen"]))
        embed += capacity_mw * EMBEDDED_BENEFITS["reactive_power"] / 12

        # FR (BESS monthly)
        fr = 0
        if technology == "bess":
            for fr_data in FR_RATES.values():
                fr += export_mw * fr_data["availability_pct"] * fr_data["rate"] * hours

        month_total = wholesale + cfd + cm + bm + embed + fr
        total_gen += gen_mwh
        total_rev += month_total

        monthly.append({
            "month": m,
            "month_name": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1],
            "season": season,
            "generation_mwh": round(gen_mwh),
            "export_mwh": round(export_mwh),
            "wholesale_gbp": round(wholesale),
            "cfd_topup_gbp": round(cfd),
            "capacity_market_gbp": round(cm),
            "bm_gbp": round(bm),
            "embedded_gbp": round(embed),
            "frequency_response_gbp": round(fr),
            "total_gbp": round(month_total),
        })

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
            "connection_type": connection_type,
        },
        "monthly": monthly,
        "annual_summary": {
            "total_generation_mwh": round(total_gen),
            "total_revenue_gbp": round(total_rev),
            "avg_monthly_gbp": round(total_rev / 12),
            "best_month": max(monthly, key=lambda m: m["total_gbp"])["month_name"],
            "worst_month": min(monthly, key=lambda m: m["total_gbp"])["month_name"],
            "seasonal_variation_pct": round(
                (max(m["total_gbp"] for m in monthly) - min(m["total_gbp"] for m in monthly))
                / max(1, min(m["total_gbp"] for m in monthly)) * 100, 1
            ),
        },
    }


def scenario_comparison(capacity_mw: float = 50, technology: str = "wind",
                         region: str = "Scotland") -> dict:
    """
    Compare revenue across scenarios: base, high wholesale, low wholesale,
    no CfD, high CM, BESS colocation.
    """
    scenarios = {
        "base": {"cfd": True, "price_mult": 1.0, "cm_mult": 1.0, "label": "Base Case"},
        "high_prices": {"cfd": True, "price_mult": 1.35, "cm_mult": 1.0, "label": "High Wholesale (+35%)"},
        "low_prices": {"cfd": True, "price_mult": 0.65, "cm_mult": 1.0, "label": "Low Wholesale (-35%)"},
        "no_cfd": {"cfd": False, "price_mult": 1.0, "cm_mult": 1.0, "label": "Merchant (No CfD)"},
        "high_cm": {"cfd": True, "price_mult": 1.0, "cm_mult": 1.8, "label": "High CM Price (+80%)"},
    }

    results = []
    for scenario_id, params in scenarios.items():
        # Temporarily adjust globals for scenario
        orig_prices = dict(WHOLESALE_PRICES)
        orig_cm = CM_CLEARING_PRICE

        for s in WHOLESALE_PRICES:
            WHOLESALE_PRICES[s] = round(orig_prices[s] * params["price_mult"])

        stack = revenue_stack(
            capacity_mw=capacity_mw,
            technology=technology,
            region=region,
            connection_type="anm",
            headroom_mw=capacity_mw * 0.6,
            cfd_enabled=params["cfd"],
        )

        # Adjust CM if needed
        cm_adj = stack["revenue_stack"]["capacity_market_gbp"] * params["cm_mult"]
        total_adj = (stack["revenue_stack"]["total_annual_gbp"]
                     - stack["revenue_stack"]["capacity_market_gbp"] + cm_adj)

        results.append({
            "scenario": scenario_id,
            "label": params["label"],
            "total_annual_gbp": round(total_adj),
            "energy_gbp": stack["revenue_stack"]["total_energy_gbp"],
            "cm_gbp": round(cm_adj),
            "bm_gbp": stack["revenue_stack"]["balancing_mechanism_gbp"],
            "fr_gbp": stack["revenue_stack"]["frequency_response_gbp"],
            "embedded_gbp": stack["revenue_stack"]["embedded_benefits_gbp"],
            "revenue_per_mw_gbp": round(total_adj / max(capacity_mw, 1)),
            "npv_25yr_gbp": round(total_adj * 11.53),  # ~11.53 PV annuity factor at 8%
        })

        # Restore globals
        for s in orig_prices:
            WHOLESALE_PRICES[s] = orig_prices[s]

    results.sort(key=lambda r: -r["total_annual_gbp"])

    # Sensitivity range
    revenues = [r["total_annual_gbp"] for r in results]

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
        },
        "scenarios": results,
        "analysis": {
            "best_scenario": results[0]["label"],
            "worst_scenario": results[-1]["label"],
            "revenue_range_gbp": [min(revenues), max(revenues)],
            "range_pct": round((max(revenues) - min(revenues)) / max(1, min(revenues)) * 100, 1),
            "cfd_value_gbp": round(
                next(r for r in results if r["scenario"] == "base")["total_annual_gbp"]
                - next(r for r in results if r["scenario"] == "no_cfd")["total_annual_gbp"]
            ),
        },
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
        if cmd == "revenue_stack":
            result = revenue_stack(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
                connection_type=req.get("connection_type", "anm"),
                headroom_mw=req.get("headroom_mw", 30),
                cfd_enabled=req.get("cfd_enabled", True),
                project_life_years=req.get("project_life_years", 25),
            )
            json.dump(result, sys.stdout)
        elif cmd == "monthly_breakdown":
            result = monthly_breakdown(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "solar"),
                region=req.get("region", "Midlands"),
                connection_type=req.get("connection_type", "anm"),
                headroom_mw=req.get("headroom_mw", 30),
            )
            json.dump(result, sys.stdout)
        elif cmd == "scenario_comparison":
            result = scenario_comparison(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()

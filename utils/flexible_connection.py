#!/usr/bin/env python3
"""
Flexible connection modeller — Princeps Phase 8
Compares firm vs ANM vs timed export connection options.
Models curtailment-aware optimal sizing and export profiles.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "compare", "capacity_mw": 50, "headroom_mw": 30,
   "region": "Midlands", "technology": "solar", "voltage_kv": 132}
  {"command": "anm_profile", "capacity_mw": 50, "headroom_mw": 30,
   "technology": "solar"}
  {"command": "optimal_sizing", "headroom_mw": 30, "region": "Midlands",
   "technology": "solar", "target_curtailment_pct": 5}
"""

import json
import math
import random
import sys

# ── Connection option templates ──────────────────────────────────────────
CONNECTION_OPTIONS = {
    "firm": {
        "label": "Firm Connection",
        "description": "Full export capacity guaranteed, no curtailment risk",
        "curtailment_factor": 0.02,   # ~2% unavoidable transmission curtailment
        "cost_multiplier": 1.0,       # Full reinforcement cost
        "timeline_months": 24,        # Longer due to reinforcement
        "priority_dispatch": True,
    },
    "non_firm": {
        "label": "Non-Firm Connection",
        "description": "No export guarantee, curtailed during constraints",
        "curtailment_factor": 1.0,
        "cost_multiplier": 0.35,      # Much cheaper — no reinforcement
        "timeline_months": 12,
        "priority_dispatch": False,
    },
    "anm": {
        "label": "Active Network Management",
        "description": "DNO-managed curtailment via real-time control",
        "curtailment_factor": 0.55,
        "cost_multiplier": 0.45,
        "timeline_months": 14,
        "priority_dispatch": False,
    },
    "timed": {
        "label": "Timed Export",
        "description": "Firm export during specified hours (e.g., peak demand)",
        "curtailment_factor": 0.40,
        "cost_multiplier": 0.50,
        "timeline_months": 16,
        "priority_dispatch": True,    # During contracted hours
    },
    "intertrip": {
        "label": "Intertrip Scheme",
        "description": "Automatic disconnection during specific fault conditions",
        "curtailment_factor": 0.15,
        "cost_multiplier": 0.70,
        "timeline_months": 18,
        "priority_dispatch": True,    # Unless tripped
    },
}

# Typical UK wholesale electricity prices by hour (£/MWh)
HOURLY_PRICE_PROFILE = [
    32, 28, 25, 23, 22, 25, 38, 55,   # 00-07
    62, 58, 52, 48, 45, 42, 45, 52,   # 08-15
    65, 78, 85, 72, 58, 48, 42, 36,   # 16-23
]

# Solar generation profile (normalised, summer day)
SOLAR_PROFILE = [
    0, 0, 0, 0, 0.02, 0.08, 0.20, 0.40,
    0.60, 0.78, 0.90, 0.96, 1.00, 0.98, 0.92, 0.80,
    0.62, 0.40, 0.18, 0.05, 0, 0, 0, 0,
]

# Wind generation profile (normalised, typical)
WIND_PROFILE = [
    0.72, 0.75, 0.78, 0.80, 0.82, 0.78, 0.70, 0.62,
    0.55, 0.50, 0.48, 0.45, 0.42, 0.45, 0.50, 0.55,
    0.60, 0.65, 0.68, 0.70, 0.72, 0.74, 0.73, 0.72,
]


def _generation_profile(technology: str) -> list:
    if technology == "wind":
        return WIND_PROFILE
    return SOLAR_PROFILE


def compare_options(capacity_mw: float, headroom_mw: float = 30,
                    region: str = "Midlands", technology: str = "solar",
                    voltage_kv: int = 132,
                    base_reinforcement_cost: float = None) -> dict:
    """
    Compare all connection options for a given project.
    Returns side-by-side analysis with NPV, curtailment, cost, timeline.
    """
    # Base reinforcement cost estimate (if not provided)
    if base_reinforcement_cost is None:
        cable_rate = {11: 95000, 33: 200000, 66: 400000, 132: 700000, 275: 1200000}.get(voltage_kv, 500000)
        base_reinforcement_cost = cable_rate * 5 + 900000 + 250000 + 80000  # cable + switchgear + civils + design

    # Capacity factor by region
    cf_map = {"Scotland": 0.095, "North": 0.100, "Wales": 0.102, "Midlands": 0.108,
              "East": 0.112, "South": 0.115, "London": 0.105}
    if technology == "wind":
        cf_map = {"Scotland": 0.32, "North": 0.28, "Wales": 0.30, "Midlands": 0.22,
                  "East": 0.26, "South": 0.24, "London": 0.18}
    cf = cf_map.get(region, 0.10)

    # Base curtailment rate for region
    base_curtail = {"Scotland": 8.5, "North": 4.2, "Wales": 5.1, "Midlands": 2.8,
                    "East": 3.5, "South": 2.1, "London": 1.2}.get(region, 3.0)

    # Headroom shortfall amplifies curtailment
    shortfall_ratio = max(0, (capacity_mw - headroom_mw)) / max(capacity_mw, 1)
    curtailment_amplifier = 1.0 + shortfall_ratio * 2.5

    gen_profile = _generation_profile(technology)
    annual_potential_mwh = capacity_mw * 8760 * cf
    avg_wholesale = sum(HOURLY_PRICE_PROFILE) / 24

    options = []
    for opt_id, opt in CONNECTION_OPTIONS.items():
        # Curtailment
        effective_curtailment_pct = base_curtail * opt["curtailment_factor"] * curtailment_amplifier
        effective_curtailment_pct = max(0, min(effective_curtailment_pct, 50))

        curtailed_mwh = annual_potential_mwh * effective_curtailment_pct / 100
        delivered_mwh = annual_potential_mwh - curtailed_mwh

        # Connection cost
        connection_cost = base_reinforcement_cost * opt["cost_multiplier"]

        # Revenue — weighted by hourly price × generation profile
        total_weighted = sum(p * g for p, g in zip(HOURLY_PRICE_PROFILE, gen_profile))
        avg_weighted_price = total_weighted / max(sum(gen_profile), 0.01)
        annual_revenue = delivered_mwh * avg_weighted_price

        # Lost revenue from curtailment
        annual_lost_revenue = curtailed_mwh * avg_weighted_price

        # O&M cost (~£10/kW/yr for solar, £25/kW/yr for wind)
        om_per_kw = 10 if technology == "solar" else 25
        annual_om = capacity_mw * 1000 * om_per_kw

        # CAPEX (£/MW for project, excluding connection)
        project_capex_per_mw = 450000 if technology == "solar" else 1200000
        project_capex = capacity_mw * project_capex_per_mw

        total_capex = project_capex + connection_cost

        # 25-year NPV at 8% discount
        npv = -total_capex
        for yr in range(1, 26):
            net_cashflow = (annual_revenue - annual_om) * (1.02 ** (yr - 1))
            npv += net_cashflow / (1.08 ** yr)

        # IRR approximation (simple)
        annual_net = annual_revenue - annual_om
        payback = total_capex / annual_net if annual_net > 0 else 999

        # LCOE
        lcoe = total_capex / (delivered_mwh * 25) * 1000 + annual_om / delivered_mwh if delivered_mwh > 0 else 999

        options.append({
            "id": opt_id,
            "label": opt["label"],
            "description": opt["description"],
            "curtailment_pct": round(effective_curtailment_pct, 2),
            "curtailed_mwh": round(curtailed_mwh),
            "delivered_mwh": round(delivered_mwh),
            "connection_cost_gbp": round(connection_cost),
            "total_capex_gbp": round(total_capex),
            "annual_revenue_gbp": round(annual_revenue),
            "annual_lost_revenue_gbp": round(annual_lost_revenue),
            "npv_25yr_gbp": round(npv),
            "payback_years": round(payback, 1),
            "lcoe_gbp_mwh": round(lcoe, 2),
            "timeline_months": opt["timeline_months"],
            "priority_dispatch": opt["priority_dispatch"],
        })

    # Sort by NPV descending
    options.sort(key=lambda x: -x["npv_25yr_gbp"])

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "headroom_mw": headroom_mw,
            "region": region,
            "technology": technology,
            "voltage_kv": voltage_kv,
            "capacity_factor": cf,
        },
        "options": options,
        "recommended": options[0]["id"] if options else None,
        "annual_potential_mwh": round(annual_potential_mwh),
        "base_reinforcement_cost_gbp": round(base_reinforcement_cost),
    }


def anm_profile(capacity_mw: float, headroom_mw: float = 30,
                technology: str = "solar") -> dict:
    """
    Generate 24-hour ANM export profile showing curtailment windows.
    """
    gen_profile = _generation_profile(technology)
    export_limit_mw = headroom_mw

    hourly = []
    total_generated = 0
    total_exported = 0
    total_curtailed = 0
    total_revenue = 0
    total_lost_revenue = 0

    for hour in range(24):
        generated_mw = capacity_mw * gen_profile[hour]
        exported_mw = min(generated_mw, export_limit_mw)
        curtailed_mw = max(0, generated_mw - export_limit_mw)
        price = HOURLY_PRICE_PROFILE[hour]

        total_generated += generated_mw
        total_exported += exported_mw
        total_curtailed += curtailed_mw
        total_revenue += exported_mw * price
        total_lost_revenue += curtailed_mw * price

        hourly.append({
            "hour": hour,
            "generated_mw": round(generated_mw, 2),
            "exported_mw": round(exported_mw, 2),
            "curtailed_mw": round(curtailed_mw, 2),
            "export_limit_mw": export_limit_mw,
            "price_gbp_mwh": price,
            "revenue_gbp": round(exported_mw * price, 2),
            "lost_revenue_gbp": round(curtailed_mw * price, 2),
        })

    return {
        "capacity_mw": capacity_mw,
        "export_limit_mw": export_limit_mw,
        "technology": technology,
        "hourly": hourly,
        "daily_summary": {
            "total_generated_mwh": round(total_generated, 1),
            "total_exported_mwh": round(total_exported, 1),
            "total_curtailed_mwh": round(total_curtailed, 1),
            "curtailment_pct": round(total_curtailed / max(total_generated, 0.01) * 100, 1),
            "total_revenue_gbp": round(total_revenue),
            "total_lost_revenue_gbp": round(total_lost_revenue),
        },
    }


def optimal_sizing(headroom_mw: float = 30, region: str = "Midlands",
                   technology: str = "solar",
                   target_curtailment_pct: float = 5) -> dict:
    """
    Find optimal plant capacity for a given headroom and target curtailment.
    Tests multiple sizes and finds the best balance.
    """
    results = []
    test_sizes = [headroom_mw * f for f in [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]]

    for size in test_sizes:
        comp = compare_options(size, headroom_mw, region, technology)
        # Use ANM option as the flexible baseline
        anm_opt = next((o for o in comp["options"] if o["id"] == "anm"), comp["options"][0])
        firm_opt = next((o for o in comp["options"] if o["id"] == "firm"), comp["options"][0])

        results.append({
            "capacity_mw": round(size, 1),
            "ratio_to_headroom": round(size / headroom_mw, 2),
            "anm_curtailment_pct": anm_opt["curtailment_pct"],
            "anm_npv_gbp": anm_opt["npv_25yr_gbp"],
            "anm_lcoe_gbp_mwh": anm_opt["lcoe_gbp_mwh"],
            "firm_npv_gbp": firm_opt["npv_25yr_gbp"],
            "firm_lcoe_gbp_mwh": firm_opt["lcoe_gbp_mwh"],
        })

    # Find optimal — highest NPV with curtailment below target
    viable = [r for r in results if r["anm_curtailment_pct"] <= target_curtailment_pct]
    if not viable:
        viable = results  # Fall back to all

    optimal = max(viable, key=lambda r: r["anm_npv_gbp"])

    return {
        "headroom_mw": headroom_mw,
        "region": region,
        "technology": technology,
        "target_curtailment_pct": target_curtailment_pct,
        "optimal_capacity_mw": optimal["capacity_mw"],
        "optimal_ratio": optimal["ratio_to_headroom"],
        "sizing_curve": results,
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
        if cmd == "compare":
            result = compare_options(
                capacity_mw=req.get("capacity_mw", 50),
                headroom_mw=req.get("headroom_mw", 30),
                region=req.get("region", "Midlands"),
                technology=req.get("technology", "solar"),
                voltage_kv=req.get("voltage_kv", 132),
            )
            json.dump(result, sys.stdout)
        elif cmd == "anm_profile":
            result = anm_profile(
                capacity_mw=req.get("capacity_mw", 50),
                headroom_mw=req.get("headroom_mw", 30),
                technology=req.get("technology", "solar"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "optimal_sizing":
            result = optimal_sizing(
                headroom_mw=req.get("headroom_mw", 30),
                region=req.get("region", "Midlands"),
                technology=req.get("technology", "solar"),
                target_curtailment_pct=req.get("target_curtailment_pct", 5),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()

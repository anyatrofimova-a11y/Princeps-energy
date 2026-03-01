#!/usr/bin/env python3
"""
Decommissioning planner — Princeps Phase 11
End-of-life planning: decommissioning cost, repowering comparison,
material recovery, bond sizing.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "decommission_estimate", "capacity_mw": 50, "technology": "wind",
   "age_years": 25}
  {"command": "repowering_comparison", "capacity_mw": 50, "technology": "wind",
   "region": "Scotland"}
  {"command": "material_recovery", "capacity_mw": 50, "technology": "wind"}
"""

import json
import math
import sys

# ── Decommissioning cost benchmarks (£/MW) ───────────────────────────────

DECOM_COSTS = {
    "wind": {
        "turbine_removal": 45000,
        "foundation_removal": 22000,
        "cable_removal": 8000,
        "access_road_restoration": 5000,
        "site_restoration": 12000,
        "grid_disconnection": 3000,
        "project_management": 8000,
        "contingency_pct": 15,
    },
    "solar": {
        "panel_removal": 18000,
        "mounting_removal": 8000,
        "cable_removal": 5000,
        "inverter_removal": 3000,
        "site_restoration": 6000,
        "grid_disconnection": 2000,
        "project_management": 4000,
        "contingency_pct": 10,
    },
    "bess": {
        "battery_removal": 35000,
        "container_removal": 12000,
        "cable_removal": 5000,
        "foundation_removal": 4000,
        "site_restoration": 5000,
        "grid_disconnection": 3000,
        "hazmat_handling": 8000,
        "project_management": 6000,
        "contingency_pct": 12,
    },
}

# Material composition (tonnes/MW)
MATERIALS = {
    "wind": {
        "steel": {"qty_per_mw": 120, "recovery_pct": 95, "scrap_value_per_t": 250},
        "concrete": {"qty_per_mw": 450, "recovery_pct": 80, "scrap_value_per_t": 8},
        "copper": {"qty_per_mw": 3.5, "recovery_pct": 98, "scrap_value_per_t": 7500},
        "fibreglass": {"qty_per_mw": 15, "recovery_pct": 30, "scrap_value_per_t": -150},  # Disposal cost
        "rare_earth": {"qty_per_mw": 0.6, "recovery_pct": 60, "scrap_value_per_t": 25000},
        "aluminium": {"qty_per_mw": 5, "recovery_pct": 95, "scrap_value_per_t": 1800},
    },
    "solar": {
        "silicon": {"qty_per_mw": 4, "recovery_pct": 85, "scrap_value_per_t": 3000},
        "glass": {"qty_per_mw": 60, "recovery_pct": 90, "scrap_value_per_t": 35},
        "aluminium": {"qty_per_mw": 18, "recovery_pct": 95, "scrap_value_per_t": 1800},
        "copper": {"qty_per_mw": 4, "recovery_pct": 98, "scrap_value_per_t": 7500},
        "steel": {"qty_per_mw": 25, "recovery_pct": 95, "scrap_value_per_t": 250},
        "plastic": {"qty_per_mw": 8, "recovery_pct": 40, "scrap_value_per_t": -80},
    },
    "bess": {
        "lithium": {"qty_per_mw": 1.2, "recovery_pct": 70, "scrap_value_per_t": 45000},
        "cobalt": {"qty_per_mw": 0.8, "recovery_pct": 85, "scrap_value_per_t": 35000},
        "nickel": {"qty_per_mw": 2.5, "recovery_pct": 90, "scrap_value_per_t": 18000},
        "steel": {"qty_per_mw": 30, "recovery_pct": 95, "scrap_value_per_t": 250},
        "copper": {"qty_per_mw": 5, "recovery_pct": 98, "scrap_value_per_t": 7500},
        "aluminium": {"qty_per_mw": 8, "recovery_pct": 95, "scrap_value_per_t": 1800},
    },
}

# Repowering parameters
REPOWERING = {
    "wind": {"new_capex_pct": 75, "capacity_uplift_pct": 50, "reuse_foundation_pct": 30,
             "reuse_grid_pct": 70, "planning_risk": "MEDIUM"},
    "solar": {"new_capex_pct": 60, "capacity_uplift_pct": 30, "reuse_foundation_pct": 80,
              "reuse_grid_pct": 90, "planning_risk": "LOW"},
    "bess": {"new_capex_pct": 55, "capacity_uplift_pct": 40, "reuse_foundation_pct": 90,
             "reuse_grid_pct": 95, "planning_risk": "LOW"},
}

CAPEX_PER_MW = {"wind": 1200000, "solar": 650000, "bess": 500000}
CAPACITY_FACTORS = {"wind": 0.287, "solar": 0.11, "bess": 0.90}


def decommission_estimate(capacity_mw: float = 50, technology: str = "wind",
                            age_years: int = 25) -> dict:
    """Estimate decommissioning cost."""
    costs = DECOM_COSTS.get(technology, DECOM_COSTS["wind"])
    contingency_pct = costs.get("contingency_pct", 15)

    line_items = {k: v for k, v in costs.items() if k != "contingency_pct" and isinstance(v, (int, float))}
    base_cost = sum(line_items.values()) * capacity_mw
    contingency = base_cost * contingency_pct / 100
    total = base_cost + contingency

    # Age adjustment (older = more expensive)
    age_factor = 1 + max(0, age_years - 20) * 0.02
    total_adjusted = total * age_factor

    breakdown = {k: round(v * capacity_mw) for k, v in line_items.items()}
    breakdown["contingency"] = round(contingency)

    # Material recovery credit
    materials = MATERIALS.get(technology, {})
    recovery_credit = 0
    mat_details = []
    for mat, data in materials.items():
        qty = data["qty_per_mw"] * capacity_mw
        recovered = qty * data["recovery_pct"] / 100
        value = recovered * data["scrap_value_per_t"]
        recovery_credit += value
        mat_details.append({
            "material": mat,
            "total_tonnes": round(qty, 1),
            "recovered_tonnes": round(recovered, 1),
            "recovery_pct": data["recovery_pct"],
            "scrap_value_gbp": round(value),
        })

    net_cost = total_adjusted - recovery_credit

    # Bond / escrow sizing
    discount_rate = 0.04
    remaining_life = max(1, 25 - age_years)
    bond_pv = net_cost / (1 + discount_rate) ** remaining_life

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "age_years": age_years,
        },
        "cost_breakdown": breakdown,
        "totals": {
            "base_cost_gbp": round(base_cost),
            "contingency_gbp": round(contingency),
            "age_adjusted_total_gbp": round(total_adjusted),
            "material_recovery_credit_gbp": round(recovery_credit),
            "net_decommission_cost_gbp": round(net_cost),
            "cost_per_mw_gbp": round(net_cost / max(capacity_mw, 1)),
        },
        "material_recovery": mat_details,
        "bond_escrow": {
            "required_bond_gbp": round(bond_pv),
            "discount_rate": discount_rate,
            "years_to_decom": remaining_life,
            "annual_provision_gbp": round(bond_pv / max(remaining_life, 1)),
        },
        "regulatory": {
            "planning_condition": "Section 106 / condition requiring site restoration",
            "grid_notice_months": 12,
            "environmental_survey_required": True,
            "waste_regulations": "WEEE (solar), Hazardous Waste (BESS)" if technology != "wind" else "Standard waste regs",
        },
    }


def repowering_comparison(capacity_mw: float = 50, technology: str = "wind",
                            region: str = "Scotland") -> dict:
    """Compare repowering vs full decommission + new build."""
    rep = REPOWERING.get(technology, REPOWERING["wind"])
    original_capex = capacity_mw * CAPEX_PER_MW.get(technology, 900000)
    cf = CAPACITY_FACTORS.get(technology, 0.25)

    # Decommission option
    decom = decommission_estimate(capacity_mw, technology, 25)
    decom_cost = decom["totals"]["net_decommission_cost_gbp"]

    # Option 1: Full decommission
    opt1_cost = decom_cost
    opt1_revenue = 0
    opt1_npv = -opt1_cost

    # Option 2: Repower
    repower_capacity = capacity_mw * (1 + rep["capacity_uplift_pct"] / 100)
    repower_capex = original_capex * rep["new_capex_pct"] / 100
    foundation_saving = original_capex * 0.15 * rep["reuse_foundation_pct"] / 100
    grid_saving = original_capex * 0.10 * rep["reuse_grid_pct"] / 100
    partial_decom = decom_cost * 0.4  # Partial removal needed
    net_repower_cost = repower_capex - foundation_saving - grid_saving + partial_decom

    repower_gen = repower_capacity * cf * 8760
    repower_revenue = repower_gen * 48
    repower_opex = repower_capacity * {"wind": 35000, "solar": 12000, "bess": 18000}.get(technology, 25000)
    repower_profit = repower_revenue - repower_opex

    repower_npv = sum(repower_profit * 1.02 ** y / 1.08 ** y for y in range(25)) - net_repower_cost

    # Option 3: New build on different site (for comparison)
    new_capex = repower_capacity * CAPEX_PER_MW.get(technology, 900000)
    new_npv = sum(repower_profit * 1.02 ** y / 1.08 ** y for y in range(25)) - new_capex + decom_cost * 0  # No recovery if abandoned

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
            "region": region,
        },
        "options": [
            {
                "option": "repower",
                "label": "Repower Existing Site",
                "new_capacity_mw": round(repower_capacity, 1),
                "cost_gbp": round(net_repower_cost),
                "annual_revenue_gbp": round(repower_revenue),
                "npv_25yr_gbp": round(repower_npv),
                "planning_risk": rep["planning_risk"],
                "timeline_months": 18,
                "recommendation": "RECOMMENDED" if repower_npv > new_npv else "ALTERNATIVE",
            },
            {
                "option": "new_build",
                "label": "Decommission + New Build",
                "new_capacity_mw": round(repower_capacity, 1),
                "cost_gbp": round(new_capex + decom_cost),
                "annual_revenue_gbp": round(repower_revenue),
                "npv_25yr_gbp": round(new_npv - decom_cost),
                "planning_risk": "HIGH",
                "timeline_months": 36,
                "recommendation": "RECOMMENDED" if new_npv - decom_cost > repower_npv else "ALTERNATIVE",
            },
            {
                "option": "decommission",
                "label": "Full Decommission (Exit)",
                "new_capacity_mw": 0,
                "cost_gbp": round(decom_cost),
                "annual_revenue_gbp": 0,
                "npv_25yr_gbp": round(opt1_npv),
                "planning_risk": "LOW",
                "timeline_months": 12,
                "recommendation": "LAST_RESORT",
            },
        ],
        "savings": {
            "repower_vs_new_gbp": round(new_capex + decom_cost - net_repower_cost),
            "foundation_reuse_gbp": round(foundation_saving),
            "grid_reuse_gbp": round(grid_saving),
            "capacity_uplift_pct": rep["capacity_uplift_pct"],
        },
    }


def material_recovery(capacity_mw: float = 50, technology: str = "wind") -> dict:
    """Detailed material recovery and circular economy analysis."""
    materials = MATERIALS.get(technology, {})

    total_mass = 0
    total_recovered = 0
    total_value = 0
    total_landfill = 0
    details = []

    for mat, data in materials.items():
        qty = data["qty_per_mw"] * capacity_mw
        recovered = qty * data["recovery_pct"] / 100
        landfill = qty - recovered
        value = recovered * data["scrap_value_per_t"]

        total_mass += qty
        total_recovered += recovered
        total_value += value
        total_landfill += landfill

        details.append({
            "material": mat,
            "total_tonnes": round(qty, 1),
            "recovered_tonnes": round(recovered, 1),
            "landfill_tonnes": round(landfill, 1),
            "recovery_pct": data["recovery_pct"],
            "scrap_value_per_t_gbp": data["scrap_value_per_t"],
            "total_value_gbp": round(value),
            "circular_score": "HIGH" if data["recovery_pct"] >= 90 else "MEDIUM" if data["recovery_pct"] >= 60 else "LOW",
        })

    overall_recovery = total_recovered / max(total_mass, 1) * 100
    landfill_diversion = overall_recovery

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "technology": technology,
        },
        "materials": details,
        "summary": {
            "total_mass_tonnes": round(total_mass),
            "total_recovered_tonnes": round(total_recovered),
            "total_landfill_tonnes": round(total_landfill),
            "overall_recovery_pct": round(overall_recovery, 1),
            "landfill_diversion_pct": round(landfill_diversion, 1),
            "total_scrap_value_gbp": round(total_value),
            "circular_economy_rating": (
                "EXEMPLARY" if overall_recovery >= 90
                else "GOOD" if overall_recovery >= 75
                else "STANDARD" if overall_recovery >= 60
                else "POOR"
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
        if cmd == "decommission_estimate":
            result = decommission_estimate(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                age_years=req.get("age_years", 25),
            )
            json.dump(result, sys.stdout)
        elif cmd == "repowering_comparison":
            result = repowering_comparison(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
                region=req.get("region", "Scotland"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "material_recovery":
            result = material_recovery(
                capacity_mw=req.get("capacity_mw", 50),
                technology=req.get("technology", "wind"),
            )
            json.dump(result, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()

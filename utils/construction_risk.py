"""Construction Risk & Supply Chain Intelligence."""

from __future__ import annotations
import random
import math
import logging
from typing import Any

log = logging.getLogger(__name__)

# ── Task networks by project type ─────────────────────────────────────────
TASK_NETWORKS = {
    "dc": [
        {"name": "Planning & Permitting", "p10": 6, "p50": 9, "p90": 14, "deps": []},
        {"name": "Site Preparation", "p10": 2, "p50": 4, "p90": 7, "deps": ["Planning & Permitting"]},
        {"name": "Civils & Foundations", "p10": 5, "p50": 7, "p90": 10, "deps": ["Site Preparation"]},
        {"name": "MEP Installation", "p10": 8, "p50": 11, "p90": 14, "deps": ["Civils & Foundations"]},
        {"name": "Fit-out & Testing", "p10": 3, "p50": 5, "p90": 7, "deps": ["MEP Installation"]},
        {"name": "Commissioning", "p10": 2, "p50": 3, "p90": 4, "deps": ["Fit-out & Testing"]},
    ],
    "solar": [
        {"name": "Planning & Design", "p10": 3, "p50": 5, "p90": 8, "deps": []},
        {"name": "Site Preparation", "p10": 1, "p50": 2, "p90": 3, "deps": ["Planning & Design"]},
        {"name": "Mounting & Piling", "p10": 2, "p50": 3, "p90": 5, "deps": ["Site Preparation"]},
        {"name": "Panel Installation", "p10": 1, "p50": 2, "p90": 3, "deps": ["Mounting & Piling"]},
        {"name": "Electrical & Grid", "p10": 2, "p50": 3, "p90": 5, "deps": ["Panel Installation"]},
        {"name": "Commissioning", "p10": 1, "p50": 1, "p90": 2, "deps": ["Electrical & Grid"]},
    ],
    "bess": [
        {"name": "Planning & Design", "p10": 2, "p50": 4, "p90": 6, "deps": []},
        {"name": "Civils & Foundations", "p10": 2, "p50": 3, "p90": 4, "deps": ["Planning & Design"]},
        {"name": "Container Installation", "p10": 1, "p50": 2, "p90": 3, "deps": ["Civils & Foundations"]},
        {"name": "Electrical & Grid", "p10": 2, "p50": 3, "p90": 4, "deps": ["Container Installation"]},
        {"name": "Commissioning", "p10": 1, "p50": 1, "p90": 2, "deps": ["Electrical & Grid"]},
    ],
}

# ── Equipment lead times ──────────────────────────────────────────────────
EQUIPMENT_DB = {
    "hv_transformer_132kv": {"name": "HV Transformer (132kV)", "lead_weeks": (78, 104, 156), "cost_per_unit": 2_500_000, "risk": "critical"},
    "mv_transformer_33kv": {"name": "MV Transformer (33kV)", "lead_weeks": (24, 36, 52), "cost_per_unit": 350_000, "risk": "high"},
    "switchgear_132kv": {"name": "Switchgear (132kV)", "lead_weeks": (52, 72, 96), "cost_per_unit": 800_000, "risk": "high"},
    "solar_panels": {"name": "Solar Panels", "lead_weeks": (8, 12, 16), "cost_per_mw": 280_000, "risk": "medium"},
    "inverters_utility": {"name": "Utility Inverters", "lead_weeks": (12, 16, 20), "cost_per_mw": 45_000, "risk": "medium"},
    "bess_containers": {"name": "BESS Containers", "lead_weeks": (16, 20, 28), "cost_per_mwh": 180_000, "risk": "medium"},
    "diesel_gensets": {"name": "Diesel Gensets", "lead_weeks": (8, 12, 16), "cost_per_mw": 150_000, "risk": "low"},
    "cooling_units": {"name": "DC Cooling Units", "lead_weeks": (16, 20, 28), "cost_per_mw": 200_000, "risk": "medium"},
    "hv_cable": {"name": "HV Cable", "lead_weeks": (8, 10, 14), "cost_per_km": 500_000, "risk": "low"},
}


def estimate_construction_timeline(project_type: str, capacity_mw: float = 50) -> dict[str, Any]:
    """Estimate construction timeline by project type."""
    tasks = TASK_NETWORKS.get(project_type, TASK_NETWORKS["solar"])
    # Scale duration by capacity
    scale = 1 + math.log10(max(capacity_mw, 1)) * 0.15

    phases = []
    for t in tasks:
        phases.append({
            "name": t["name"],
            "p10_months": round(t["p10"] * scale, 1),
            "p50_months": round(t["p50"] * scale, 1),
            "p90_months": round(t["p90"] * scale, 1),
            "dependencies": t["deps"],
        })

    total_p10 = sum(p["p10_months"] for p in phases)
    total_p50 = sum(p["p50_months"] for p in phases)
    total_p90 = sum(p["p90_months"] for p in phases)

    return {
        "project_type": project_type,
        "capacity_mw": capacity_mw,
        "phases": phases,
        "total_months_p10": round(total_p10, 1),
        "total_months_p50": round(total_p50, 1),
        "total_months_p90": round(total_p90, 1),
        "critical_path": [p["name"] for p in phases],
    }


def monte_carlo_schedule(project_type: str, capacity_mw: float = 50, simulations: int = 1000) -> dict[str, Any]:
    """Monte Carlo simulation of construction schedule."""
    tasks = TASK_NETWORKS.get(project_type, TASK_NETWORKS["solar"])
    scale = 1 + math.log10(max(capacity_mw, 1)) * 0.15

    totals = []
    for _ in range(simulations):
        total = 0
        for t in tasks:
            # Triangular distribution
            lo = t["p10"] * scale
            mid = t["p50"] * scale
            hi = t["p90"] * scale
            duration = random.triangular(lo, hi, mid)
            total += duration
        totals.append(total)

    totals.sort()
    p10 = totals[int(simulations * 0.1)]
    p50 = totals[int(simulations * 0.5)]
    p90 = totals[int(simulations * 0.9)]

    # Histogram buckets
    min_m, max_m = int(totals[0]), int(totals[-1]) + 1
    histogram = []
    for m in range(min_m, max_m + 1):
        count = sum(1 for t in totals if m <= t < m + 1)
        histogram.append({"month": m, "probability": round(count / simulations, 3)})

    return {
        "simulations": simulations,
        "p10_months": round(p10, 1),
        "p50_months": round(p50, 1),
        "p90_months": round(p90, 1),
        "mean_months": round(sum(totals) / len(totals), 1),
        "histogram": histogram,
        "risk_factors": [
            "HV transformer lead time (18-30 months)" if project_type in ("dc", "solar") else None,
            "Planning permission delays",
            "Grid connection works programme",
            "Labour availability in region",
            "Weather delays (UK winter)" if project_type == "solar" else None,
        ],
    }


def assess_supply_chain(project_type: str, capacity_mw: float = 50) -> dict[str, Any]:
    """Assess supply chain risks and lead times."""
    items = []

    if project_type in ("dc", "solar", "bess", "hybrid"):
        items.append({**EQUIPMENT_DB["hv_transformer_132kv"], "quantity": max(1, int(capacity_mw / 50))})
        items.append({**EQUIPMENT_DB["mv_transformer_33kv"], "quantity": max(1, int(capacity_mw / 10))})
        items.append({**EQUIPMENT_DB["switchgear_132kv"], "quantity": 1})

    if project_type in ("solar", "hybrid"):
        items.append({**EQUIPMENT_DB["solar_panels"], "quantity": 1, "cost_total": int(capacity_mw * EQUIPMENT_DB["solar_panels"]["cost_per_mw"])})
        items.append({**EQUIPMENT_DB["inverters_utility"], "quantity": max(1, int(capacity_mw / 5))})

    if project_type in ("bess", "hybrid"):
        items.append({**EQUIPMENT_DB["bess_containers"], "quantity": max(1, int(capacity_mw * 4 / 3.7))})

    if project_type == "dc":
        items.append({**EQUIPMENT_DB["cooling_units"], "quantity": max(1, int(capacity_mw / 5))})
        items.append({**EQUIPMENT_DB["diesel_gensets"], "quantity": max(2, int(capacity_mw / 2))})

    long_lead = []
    total_cost = 0
    critical_item = None
    max_lead = 0

    for item in items:
        weeks_p50 = item["lead_weeks"][1] if isinstance(item.get("lead_weeks"), tuple) else 12
        cost = item.get("cost_total") or item.get("cost_per_unit", 0) * item.get("quantity", 1)
        total_cost += cost

        entry = {"item": item["name"], "lead_time_weeks_p50": weeks_p50, "cost_gbp": cost, "risk": item.get("risk", "medium"), "quantity": item.get("quantity", 1)}
        long_lead.append(entry)

        if weeks_p50 > max_lead:
            max_lead = weeks_p50
            critical_item = item["name"]

    long_lead.sort(key=lambda x: x["lead_time_weeks_p50"], reverse=True)

    return {
        "long_lead_items": long_lead,
        "total_equipment_cost_gbp": total_cost,
        "critical_path_item": critical_item,
        "critical_path_weeks": max_lead,
    }


def estimate_construction_cost(project_type: str, capacity_mw: float = 50) -> dict[str, Any]:
    """Estimate total construction cost."""
    cost_models = {
        "dc": {"equipment_pct": 0.45, "civils_pct": 0.25, "electrical_pct": 0.15, "fees_pct": 0.08, "contingency_pct": 0.07, "cost_per_mw": (10_000_000, 15_000_000)},
        "solar": {"equipment_pct": 0.55, "civils_pct": 0.15, "electrical_pct": 0.18, "fees_pct": 0.05, "contingency_pct": 0.07, "cost_per_mw": (500_000, 800_000)},
        "bess": {"equipment_pct": 0.60, "civils_pct": 0.12, "electrical_pct": 0.16, "fees_pct": 0.05, "contingency_pct": 0.07, "cost_per_mw": (800_000, 1_400_000)},
        "wind": {"equipment_pct": 0.65, "civils_pct": 0.15, "electrical_pct": 0.10, "fees_pct": 0.05, "contingency_pct": 0.05, "cost_per_mw": (1_200_000, 1_800_000)},
    }

    model = cost_models.get(project_type, cost_models["solar"])
    avg_cost = sum(model["cost_per_mw"]) / 2
    total = avg_cost * capacity_mw

    return {
        "project_type": project_type,
        "capacity_mw": capacity_mw,
        "total_capex_gbp": round(total),
        "cost_per_mw_gbp": round(avg_cost),
        "breakdown": {
            "equipment": round(total * model["equipment_pct"]),
            "civils": round(total * model["civils_pct"]),
            "electrical": round(total * model["electrical_pct"]),
            "professional_fees": round(total * model["fees_pct"]),
            "contingency": round(total * model["contingency_pct"]),
        },
        "contingency_pct": model["contingency_pct"] * 100,
    }

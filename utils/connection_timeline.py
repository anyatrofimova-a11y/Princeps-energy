#!/usr/bin/env python3
"""
Connection timeline generator — Princeps Phase 8
Models UK grid connection process milestones for G99/CUSC applications.
Generates Gantt-style timeline with critical path analysis.

Subprocess bridge: JSON stdin/stdout.

Commands:
  {"command": "generate", "capacity_mw": 50, "voltage_kv": 132,
   "connection_type": "firm", "start_date": "2025-03-01"}
  {"command": "milestones", "capacity_mw": 50}
  {"command": "critical_path", "capacity_mw": 50, "voltage_kv": 132}
"""

import json
import math
import sys
from datetime import datetime, timedelta

# ── UK grid connection process milestones ────────────────────────────────
# Durations in months, based on typical DNO/NESO timescales

MILESTONE_TEMPLATES = {
    "pre_application": {
        "label": "Pre-Application",
        "description": "Site assessment, feasibility study, initial DNO engagement",
        "category": "planning",
        "duration_months": {"small": 1, "medium": 2, "large": 3},
        "dependencies": [],
        "risk_factors": ["planning_complexity", "site_access"],
    },
    "grid_study": {
        "label": "Grid Connection Study",
        "description": "DNO/NESO connection study (G99 or CUSC application)",
        "category": "grid",
        "duration_months": {"small": 2, "medium": 4, "large": 8},
        "dependencies": ["pre_application"],
        "risk_factors": ["dno_workload", "study_complexity"],
    },
    "connection_offer": {
        "label": "Connection Offer",
        "description": "Receive and evaluate DNO connection offer",
        "category": "grid",
        "duration_months": {"small": 1, "medium": 2, "large": 3},
        "dependencies": ["grid_study"],
        "risk_factors": ["dno_workload", "reinforcement_scope"],
    },
    "offer_acceptance": {
        "label": "Offer Acceptance & Agreements",
        "description": "Legal review, accept offer, sign connection agreement",
        "category": "legal",
        "duration_months": {"small": 1, "medium": 1, "large": 2},
        "dependencies": ["connection_offer"],
        "risk_factors": ["legal_complexity"],
    },
    "planning_application": {
        "label": "Planning Application",
        "description": "Submit and determine planning permission (EIA if required)",
        "category": "planning",
        "duration_months": {"small": 3, "medium": 6, "large": 12},
        "dependencies": ["pre_application"],
        "risk_factors": ["planning_complexity", "eia_required", "public_objection"],
    },
    "detailed_design": {
        "label": "Detailed Design",
        "description": "Detailed electrical and civil design, procurement specs",
        "category": "engineering",
        "duration_months": {"small": 2, "medium": 3, "large": 5},
        "dependencies": ["offer_acceptance", "planning_application"],
        "risk_factors": ["design_complexity", "specialist_availability"],
    },
    "procurement": {
        "label": "Equipment Procurement",
        "description": "Procure switchgear, transformer, cable, protection",
        "category": "procurement",
        "duration_months": {"small": 3, "medium": 6, "large": 12},
        "dependencies": ["detailed_design"],
        "risk_factors": ["supply_chain", "transformer_lead_time"],
    },
    "wayleaves": {
        "label": "Wayleaves & Land Rights",
        "description": "Negotiate wayleaves, easements, land agreements",
        "category": "legal",
        "duration_months": {"small": 2, "medium": 4, "large": 8},
        "dependencies": ["offer_acceptance"],
        "risk_factors": ["landowner_negotiation", "compulsory_purchase"],
    },
    "dno_reinforcement": {
        "label": "DNO Reinforcement Works",
        "description": "Network reinforcement by DNO (if required)",
        "category": "construction",
        "duration_months": {"small": 0, "medium": 6, "large": 18},
        "dependencies": ["offer_acceptance"],
        "risk_factors": ["reinforcement_scope", "dno_workload", "outage_planning"],
    },
    "construction": {
        "label": "Construction",
        "description": "Site civil works, cable laying, equipment installation",
        "category": "construction",
        "duration_months": {"small": 3, "medium": 6, "large": 12},
        "dependencies": ["procurement", "wayleaves", "dno_reinforcement"],
        "risk_factors": ["weather", "site_access", "supply_chain"],
    },
    "testing": {
        "label": "Testing & Commissioning",
        "description": "Protection testing, G99 compliance, SAT/FAT",
        "category": "commissioning",
        "duration_months": {"small": 1, "medium": 2, "large": 3},
        "dependencies": ["construction"],
        "risk_factors": ["test_failures", "dno_availability"],
    },
    "energisation": {
        "label": "Energisation",
        "description": "DNO energisation, final connection, export start",
        "category": "commissioning",
        "duration_months": {"small": 0.5, "medium": 1, "large": 2},
        "dependencies": ["testing"],
        "risk_factors": ["dno_availability", "outage_planning"],
    },
}

# Risk probability and delay impact (months)
RISK_CATALOGUE = {
    "planning_complexity": {"probability": 0.3, "delay_months": 3, "label": "Planning complexity"},
    "eia_required": {"probability": 0.4, "delay_months": 6, "label": "EIA required"},
    "public_objection": {"probability": 0.25, "delay_months": 4, "label": "Public objection"},
    "dno_workload": {"probability": 0.5, "delay_months": 3, "label": "DNO backlog"},
    "study_complexity": {"probability": 0.3, "delay_months": 2, "label": "Study complexity"},
    "reinforcement_scope": {"probability": 0.4, "delay_months": 6, "label": "Reinforcement scope"},
    "legal_complexity": {"probability": 0.15, "delay_months": 2, "label": "Legal complexity"},
    "design_complexity": {"probability": 0.2, "delay_months": 2, "label": "Design complexity"},
    "specialist_availability": {"probability": 0.3, "delay_months": 2, "label": "Specialist shortage"},
    "supply_chain": {"probability": 0.4, "delay_months": 4, "label": "Supply chain delays"},
    "transformer_lead_time": {"probability": 0.5, "delay_months": 6, "label": "Transformer lead time"},
    "landowner_negotiation": {"probability": 0.35, "delay_months": 4, "label": "Landowner negotiation"},
    "compulsory_purchase": {"probability": 0.1, "delay_months": 12, "label": "Compulsory purchase"},
    "weather": {"probability": 0.3, "delay_months": 2, "label": "Weather delays"},
    "site_access": {"probability": 0.2, "delay_months": 2, "label": "Site access issues"},
    "test_failures": {"probability": 0.2, "delay_months": 1, "label": "Test failures"},
    "dno_availability": {"probability": 0.4, "delay_months": 2, "label": "DNO availability"},
    "outage_planning": {"probability": 0.3, "delay_months": 3, "label": "Outage planning"},
}

# Size categories
def _size_category(capacity_mw: float) -> str:
    if capacity_mw <= 5:
        return "small"
    elif capacity_mw <= 50:
        return "medium"
    return "large"

CATEGORY_COLORS = {
    "planning": "#fa8c16",
    "grid": "#1890ff",
    "legal": "#722ed1",
    "engineering": "#13c2c2",
    "procurement": "#eb2f96",
    "construction": "#52c41a",
    "commissioning": "#f5222d",
}


def generate_timeline(capacity_mw: float = 50, voltage_kv: int = 132,
                       connection_type: str = "firm",
                       start_date: str = "2025-03-01",
                       needs_reinforcement: bool = None) -> dict:
    """
    Generate a full connection timeline with milestones, critical path, and risks.
    """
    size = _size_category(capacity_mw)
    start = datetime.fromisoformat(start_date)

    # Determine if reinforcement needed
    if needs_reinforcement is None:
        needs_reinforcement = connection_type == "firm" and capacity_mw > 10

    # Build milestone schedule
    milestones = {}
    for m_id, template in MILESTONE_TEMPLATES.items():
        # Skip reinforcement milestone if not needed
        if m_id == "dno_reinforcement" and not needs_reinforcement:
            continue

        duration = template["duration_months"][size]

        # Connection type adjustments
        if connection_type == "anm" and m_id == "dno_reinforcement":
            duration = 0
        if connection_type in ("anm", "non_firm") and m_id == "grid_study":
            duration = max(1, duration - 1)

        milestones[m_id] = {
            "id": m_id,
            "label": template["label"],
            "description": template["description"],
            "category": template["category"],
            "color": CATEGORY_COLORS.get(template["category"], "#999"),
            "duration_months": duration,
            "dependencies": [d for d in template["dependencies"] if d in MILESTONE_TEMPLATES and
                             (d != "dno_reinforcement" or needs_reinforcement)],
            "risk_factors": template["risk_factors"],
        }

    # Forward pass — earliest start/finish
    def earliest_finish(m_id):
        m = milestones[m_id]
        if not m["dependencies"]:
            return m["duration_months"]
        dep_finishes = [earliest_finish(d) for d in m["dependencies"] if d in milestones]
        return max(dep_finishes) + m["duration_months"] if dep_finishes else m["duration_months"]

    # Calculate dates
    for m_id, m in milestones.items():
        ef = earliest_finish(m_id)
        es = ef - m["duration_months"]
        m["start_month"] = round(es, 1)
        m["end_month"] = round(ef, 1)
        m["start_date"] = (start + timedelta(days=int(es * 30.44))).strftime("%Y-%m-%d")
        m["end_date"] = (start + timedelta(days=int(ef * 30.44))).strftime("%Y-%m-%d")

    # Total duration
    total_months = max(m["end_month"] for m in milestones.values())
    completion_date = start + timedelta(days=int(total_months * 30.44))

    # Critical path — find the longest chain
    def chain_duration(m_id, visited=None):
        if visited is None:
            visited = set()
        if m_id in visited:
            return 0
        visited.add(m_id)
        m = milestones[m_id]
        if not m["dependencies"]:
            return m["duration_months"]
        return m["duration_months"] + max(
            (chain_duration(d, visited.copy()) for d in m["dependencies"] if d in milestones),
            default=0
        )

    # Find milestones on critical path
    critical_path = []
    end_milestones = [m_id for m_id, m in milestones.items()
                       if not any(m_id in other["dependencies"] for other in milestones.values())]
    longest_end = max(end_milestones, key=lambda m: milestones[m]["end_month"])

    def trace_critical(m_id):
        critical_path.append(m_id)
        m = milestones[m_id]
        if m["dependencies"]:
            deps_in = [d for d in m["dependencies"] if d in milestones]
            if deps_in:
                longest_dep = max(deps_in, key=lambda d: milestones[d]["end_month"])
                trace_critical(longest_dep)

    trace_critical(longest_end)
    critical_path.reverse()

    for m_id in milestones:
        milestones[m_id]["on_critical_path"] = m_id in critical_path

    # Risk analysis
    risks = []
    total_risk_delay = 0
    for m_id, m in milestones.items():
        for rf in m["risk_factors"]:
            if rf in RISK_CATALOGUE:
                r = RISK_CATALOGUE[rf]
                expected_delay = r["probability"] * r["delay_months"]
                total_risk_delay += expected_delay
                if r["probability"] >= 0.3:
                    risks.append({
                        "milestone": m["label"],
                        "risk": r["label"],
                        "probability": r["probability"],
                        "delay_months": r["delay_months"],
                        "expected_delay": round(expected_delay, 1),
                        "on_critical_path": m_id in critical_path,
                    })

    risks.sort(key=lambda r: -r["expected_delay"])

    p90_months = total_months + total_risk_delay * 0.8
    p90_date = start + timedelta(days=int(p90_months * 30.44))

    return {
        "parameters": {
            "capacity_mw": capacity_mw,
            "voltage_kv": voltage_kv,
            "connection_type": connection_type,
            "start_date": start_date,
            "size_category": size,
            "needs_reinforcement": needs_reinforcement,
        },
        "milestones": list(milestones.values()),
        "critical_path": critical_path,
        "total_months_p50": round(total_months, 1),
        "total_months_p90": round(p90_months, 1),
        "completion_date_p50": completion_date.strftime("%Y-%m-%d"),
        "completion_date_p90": p90_date.strftime("%Y-%m-%d"),
        "start_date": start_date,
        "risks": risks[:10],
        "risk_summary": {
            "total_expected_delay_months": round(total_risk_delay, 1),
            "critical_path_risks": len([r for r in risks if r["on_critical_path"]]),
            "high_probability_risks": len([r for r in risks if r["probability"] >= 0.4]),
        },
    }


def get_milestones(capacity_mw: float = 50) -> dict:
    """Return milestone templates with durations for given capacity."""
    size = _size_category(capacity_mw)
    return {
        "size_category": size,
        "milestones": {
            m_id: {
                "label": t["label"],
                "category": t["category"],
                "duration_months": t["duration_months"][size],
                "dependencies": t["dependencies"],
            }
            for m_id, t in MILESTONE_TEMPLATES.items()
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
        if cmd == "generate":
            result = generate_timeline(
                capacity_mw=req.get("capacity_mw", 50),
                voltage_kv=req.get("voltage_kv", 132),
                connection_type=req.get("connection_type", "firm"),
                start_date=req.get("start_date", "2025-03-01"),
                needs_reinforcement=req.get("needs_reinforcement"),
            )
            json.dump(result, sys.stdout)
        elif cmd == "milestones":
            result = get_milestones(req.get("capacity_mw", 50))
            json.dump(result, sys.stdout)
        elif cmd == "critical_path":
            result = generate_timeline(
                capacity_mw=req.get("capacity_mw", 50),
                voltage_kv=req.get("voltage_kv", 132),
            )
            # Return just critical path info
            json.dump({
                "critical_path": result["critical_path"],
                "total_months_p50": result["total_months_p50"],
                "total_months_p90": result["total_months_p90"],
                "risks": result["risks"],
            }, sys.stdout)
        else:
            json.dump({"error": f"Unknown command: {cmd}"}, sys.stdout)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()

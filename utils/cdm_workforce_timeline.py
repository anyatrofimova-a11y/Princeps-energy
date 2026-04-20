"""
CDM construction workforce headcount timeline.

Builds a phase-by-phase construction headcount curve keyed off project
capacity (MW) and technology. Output feeds the F10 Notification
(peak workers / person-days) and the PCI Section 2 welfare arrangements
(Schedule 2 of the Construction (Design and Management) Regulations 2015
requires welfare provision proportionate to workforce size).

Phases follow the standard UK solar/BESS/DC/wind construction sequence:

    Phase                               Drives headcount by...
    ----------------------------------------------------------
    mobilisation / enabling             site size
    civils / earthworks / foundations   capacity + ground risk
    racking / mechanical                capacity (labour-intensive for PV)
    module / cell install (PV/BESS)     capacity (gang size scales)
    HV electrical / grid connection     capacity / voltage
    commissioning / handover            fixed core team

Each phase entry returns:
    {phase, start_week, duration_weeks, avg_workers, peak_workers,
     trades (list), key_activities (list)}

Plus top-line {peak_headcount, avg_headcount, total_person_days,
f10_trigger_met, phase_count, total_duration_weeks}.

Subprocess bridge available for the Princeps subprocess pattern.
"""
from __future__ import annotations

import json
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Phase templates (week durations and headcount elasticities)
# ---------------------------------------------------------------------------
# Each phase has:
#   name, base_weeks, week_alpha (scale vs MW),
#   base_peak, peak_alpha (scale vs MW),
#   avg_ratio (avg / peak), trades, activities
# ---------------------------------------------------------------------------

_PHASE_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "solar": [
        {
            "phase": "mobilisation",
            "base_weeks": 3, "week_alpha": 0.04,
            "base_peak": 8, "peak_alpha": 0.20,
            "avg_ratio": 0.7,
            "trades": ["site manager", "H&S officer", "groundworker", "fencing gang"],
            "activities": ["site compound setup", "Heras fencing", "welfare cabins", "site roads"],
        },
        {
            "phase": "foundations_and_civils",
            "base_weeks": 5, "week_alpha": 0.15,
            "base_peak": 14, "peak_alpha": 0.30,
            "avg_ratio": 0.65,
            "trades": ["piling crew", "groundworker", "plant operator", "setting-out engineer"],
            "activities": ["pile/screw install", "inverter stations", "substation pad", "cable trenching"],
        },
        {
            "phase": "racking_and_mechanical",
            "base_weeks": 6, "week_alpha": 0.22,
            "base_peak": 30, "peak_alpha": 0.45,
            "avg_ratio": 0.7,
            "trades": ["mechanical install gang", "crane banksman", "supervisor"],
            "activities": ["rail install", "tracker assembly", "torque-down"],
        },
        {
            "phase": "pv_module_install",
            "base_weeks": 8, "week_alpha": 0.28,
            "base_peak": 60, "peak_alpha": 0.55,
            "avg_ratio": 0.75,
            "trades": ["module install gang", "DC electrician", "QC technician"],
            "activities": ["module placement", "DC string wiring", "IV curve test"],
        },
        {
            "phase": "hv_electrical_and_grid",
            "base_weeks": 5, "week_alpha": 0.15,
            "base_peak": 14, "peak_alpha": 0.25,
            "avg_ratio": 0.65,
            "trades": ["HV jointer", "SAP", "cable gang", "commissioning engineer"],
            "activities": ["33 kV cable pull", "transformer set", "ring main", "DNO point-of-connection"],
        },
        {
            "phase": "commissioning",
            "base_weeks": 4, "week_alpha": 0.08,
            "base_peak": 10, "peak_alpha": 0.15,
            "avg_ratio": 0.55,
            "trades": ["commissioning engineer", "SAP", "OEM rep", "client engineer"],
            "activities": ["G99 commissioning", "EREC compliance testing", "SCADA proving", "take-over"],
        },
    ],
    "bess": [
        {
            "phase": "mobilisation",
            "base_weeks": 2, "week_alpha": 0.03,
            "base_peak": 6, "peak_alpha": 0.15,
            "avg_ratio": 0.7,
            "trades": ["site manager", "H&S officer", "fencing gang"],
            "activities": ["compound", "fencing", "fire-water connection (if required)"],
        },
        {
            "phase": "foundations_and_civils",
            "base_weeks": 4, "week_alpha": 0.20,
            "base_peak": 12, "peak_alpha": 0.35,
            "avg_ratio": 0.65,
            "trades": ["groundworker", "reinforcement gang", "concrete gang"],
            "activities": ["RC slab", "bunding", "drainage", "cable trench"],
        },
        {
            "phase": "container_install",
            "base_weeks": 3, "week_alpha": 0.18,
            "base_peak": 12, "peak_alpha": 0.40,
            "avg_ratio": 0.70,
            "trades": ["appointed person (lifts)", "crane banksman", "riggers", "mechanical fitter"],
            "activities": ["DC block delivery", "lift plan execution", "alignment to pad", "fire gap verify"],
        },
        {
            "phase": "hv_electrical_and_grid",
            "base_weeks": 6, "week_alpha": 0.20,
            "base_peak": 18, "peak_alpha": 0.30,
            "avg_ratio": 0.65,
            "trades": ["HV jointer", "SAP", "cable gang", "PCS engineer"],
            "activities": ["PCS set", "transformer set", "33 kV ring", "protection relay set"],
        },
        {
            "phase": "commissioning",
            "base_weeks": 5, "week_alpha": 0.10,
            "base_peak": 10, "peak_alpha": 0.15,
            "avg_ratio": 0.60,
            "trades": ["OEM rep", "commissioning engineer", "SAP"],
            "activities": ["BMS proving", "cell balancing", "fire test", "G99 compliance", "market accreditation"],
        },
    ],
    "wind": [
        {
            "phase": "mobilisation",
            "base_weeks": 4, "week_alpha": 0.05,
            "base_peak": 12, "peak_alpha": 0.20,
            "avg_ratio": 0.7,
            "trades": ["site manager", "H&S officer", "groundworker", "fencing gang"],
            "activities": ["site roads", "crane pads", "laydown"],
        },
        {
            "phase": "foundations_and_civils",
            "base_weeks": 8, "week_alpha": 0.18,
            "base_peak": 20, "peak_alpha": 0.30,
            "avg_ratio": 0.65,
            "trades": ["piling crew", "rebar gang", "concrete gang"],
            "activities": ["turbine base piles", "gravity bases", "mass-pour concrete"],
        },
        {
            "phase": "turbine_erection",
            "base_weeks": 6, "week_alpha": 0.22,
            "base_peak": 25, "peak_alpha": 0.40,
            "avg_ratio": 0.65,
            "trades": ["appointed person", "crawler crane crew", "rigger", "tower fitter"],
            "activities": ["tower section lifts", "nacelle lift", "blade tandem lift"],
        },
        {
            "phase": "hv_electrical_and_grid",
            "base_weeks": 6, "week_alpha": 0.20,
            "base_peak": 16, "peak_alpha": 0.30,
            "avg_ratio": 0.65,
            "trades": ["HV jointer", "SAP", "cable gang"],
            "activities": ["collector cables", "substation build", "DNO interface"],
        },
        {
            "phase": "commissioning",
            "base_weeks": 6, "week_alpha": 0.10,
            "base_peak": 12, "peak_alpha": 0.20,
            "avg_ratio": 0.55,
            "trades": ["OEM commissioning", "SAP"],
            "activities": ["first roll", "power curve", "G99 proving", "availability acceptance"],
        },
    ],
    "dc": [
        {
            "phase": "mobilisation",
            "base_weeks": 4, "week_alpha": 0.05,
            "base_peak": 15, "peak_alpha": 0.20,
            "avg_ratio": 0.7,
            "trades": ["site manager", "H&S officer", "fencing/hoarding gang", "traffic marshal"],
            "activities": ["hoarding", "welfare", "site compound", "traffic plan"],
        },
        {
            "phase": "foundations_and_civils",
            "base_weeks": 12, "week_alpha": 0.20,
            "base_peak": 40, "peak_alpha": 0.35,
            "avg_ratio": 0.65,
            "trades": ["piling", "groundworker", "formwork", "concrete gang"],
            "activities": ["piled foundations", "slab pour", "basement / plant rooms"],
        },
        {
            "phase": "base_build",
            "base_weeks": 18, "week_alpha": 0.25,
            "base_peak": 90, "peak_alpha": 0.50,
            "avg_ratio": 0.70,
            "trades": ["steel erector", "roofer", "cladder", "general labour"],
            "activities": ["steel frame", "envelope", "roof", "doors"],
        },
        {
            "phase": "mechanical_electrical_fitout",
            "base_weeks": 18, "week_alpha": 0.28,
            "base_peak": 110, "peak_alpha": 0.55,
            "avg_ratio": 0.75,
            "trades": ["M&E fitter", "pipefitter", "electrician", "cooling spec", "commissioning"],
            "activities": ["chillers", "CRAH/CRAC", "busway", "UPS", "generators"],
        },
        {
            "phase": "hv_electrical_and_grid",
            "base_weeks": 12, "week_alpha": 0.20,
            "base_peak": 30, "peak_alpha": 0.30,
            "avg_ratio": 0.65,
            "trades": ["HV jointer", "SAP", "switchgear engineer"],
            "activities": ["33 kV intake", "transformers", "switchgear", "protection"],
        },
        {
            "phase": "commissioning",
            "base_weeks": 10, "week_alpha": 0.12,
            "base_peak": 35, "peak_alpha": 0.20,
            "avg_ratio": 0.60,
            "trades": ["commissioning engineer", "OEM", "SAP", "Cx authority"],
            "activities": ["L4 integrated systems test", "5-day pull", "white-space handover"],
        },
    ],
}


def _scale_weeks(base: int, alpha: float, capacity_mw: float) -> int:
    import math
    mw = max(1.0, capacity_mw)
    return max(1, round(base * (1 + alpha * math.log10(mw))))


def _scale_peak(base: int, alpha: float, capacity_mw: float) -> int:
    import math
    mw = max(1.0, capacity_mw)
    return max(2, round(base * (1 + alpha * math.log10(mw))))


def _resolve_tech(tech_type: str | None) -> str:
    if not tech_type:
        return "solar"
    t = tech_type.lower().strip()
    if t.startswith("solar") or t == "pv":
        return "solar"
    if t.startswith("bess") or "batter" in t:
        return "bess"
    if "wind" in t:
        return "wind"
    if t in ("dc", "datacentre", "data_centre", "data-center", "datacenter"):
        return "dc"
    return "solar"


def generate_workforce_timeline(
    capacity_mw: float = 50.0,
    tech_type: str = "solar",
    complexity: str = "med",
) -> dict:
    """Build the construction workforce timeline.

    Args:
        capacity_mw: installed capacity in MW (drives headcount scaling).
        tech_type: solar | bess | wind | dc (selects phase template).
        complexity: low | med | high (multiplier on weeks and peak).

    Returns:
        {phases: [...], summary: {...}, assumptions: {...}}
    """
    tech = _resolve_tech(tech_type)
    template = _PHASE_TEMPLATES.get(tech, _PHASE_TEMPLATES["solar"])
    mult_weeks = {"low": 0.85, "med": 1.0, "high": 1.25}.get(complexity, 1.0)
    mult_peak = {"low": 0.90, "med": 1.0, "high": 1.15}.get(complexity, 1.0)

    phases: list[dict] = []
    start_week = 0
    for phase_def in template:
        weeks = max(1, round(
            _scale_weeks(phase_def["base_weeks"], phase_def["week_alpha"],
                         capacity_mw) * mult_weeks
        ))
        peak = max(2, round(
            _scale_peak(phase_def["base_peak"], phase_def["peak_alpha"],
                        capacity_mw) * mult_peak
        ))
        avg = max(1, round(peak * phase_def["avg_ratio"]))
        phases.append({
            "phase": phase_def["phase"],
            "start_week": start_week,
            "end_week": start_week + weeks,
            "duration_weeks": weeks,
            "avg_workers": avg,
            "peak_workers": peak,
            "trades": list(phase_def["trades"]),
            "key_activities": list(phase_def["activities"]),
            "person_days": int(weeks * 5 * avg),  # 5-day working week
        })
        start_week += weeks

    total_weeks = start_week
    total_days = sum(p["person_days"] for p in phases)
    peak_headcount = max(p["peak_workers"] for p in phases)
    avg_headcount = round(sum(p["avg_workers"] * p["duration_weeks"] for p in phases)
                          / max(1, total_weeks))

    # F10 triggers under CDM 2015 Reg 6 — notifiable if BOTH
    #   (a) construction >30 working days with >20 workers simultaneously
    #   (b) OR >500 person-days total
    working_days = total_weeks * 5
    trigger_a = working_days > 30 and peak_headcount > 20
    trigger_b = total_days > 500
    f10_required = trigger_a or trigger_b

    return {
        "phases": phases,
        "summary": {
            "technology": tech,
            "capacity_mw": capacity_mw,
            "complexity": complexity,
            "total_duration_weeks": total_weeks,
            "total_duration_months": round(total_weeks / 4.33, 1),
            "total_working_days": working_days,
            "total_person_days": total_days,
            "peak_headcount": peak_headcount,
            "avg_headcount": avg_headcount,
            "phase_count": len(phases),
        },
        "f10_notification": {
            "required": f10_required,
            "trigger_30d_20w": trigger_a,
            "trigger_500pd": trigger_b,
            "reference": "CDM Regulations 2015 (SI 2015/51), Regulation 6",
            "form_link": "https://www.hse.gov.uk/forms/notification/f10.htm",
        },
        "assumptions": {
            "working_week_days": 5,
            "welfare_provision_ref": "CDM 2015, Schedule 2 — welfare facilities scaled to peak headcount",
            "citation": (
                "CDM Regulations 2015 (SI 2015/51); HSE L153 ACoP "
                "— Managing health and safety in construction"
            ),
        },
    }


# ---------------------------------------------------------------------------
# Subprocess bridge
# ---------------------------------------------------------------------------

def main() -> None:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        json.dump({"error": f"Invalid JSON: {e}"}, sys.stdout)
        return

    try:
        result = generate_workforce_timeline(
            capacity_mw=float(req.get("capacity_mw", 50) or 50),
            tech_type=req.get("tech_type", req.get("technology", "solar")),
            complexity=req.get("complexity", "med"),
        )
        json.dump(result, sys.stdout)
    except Exception as e:  # pragma: no cover
        json.dump({"error": str(e)}, sys.stdout)


if __name__ == "__main__":
    main()

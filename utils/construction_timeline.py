"""Construction Timeline Engine — Gantt-style timelines for solar, wind & BESS projects.

Generates phase-by-phase construction programmes with technology-specific durations,
dependency chains, milestones, and SVG Gantt chart export.

UK planning pathways:
  - <50MW: Local Planning Authority (Town & Country Planning Act 1990)
  - >=50MW: NSIP / DCO route via Planning Inspectorate (Planning Act 2008)

Typical programme durations:
  - Solar <50MW:  18-24 months
  - Solar >=50MW: 24-36 months (DCO adds ~12 months)
  - Wind:         24-36 months (LVIA, noise, shadow flicker extend planning)
  - BESS:         12-18 months (simpler planning, shorter construction)
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger("princeps.construction_timeline")

# ---------------------------------------------------------------------------
# Phase colour palette (for SVG Gantt)
# ---------------------------------------------------------------------------
PHASE_COLOURS: dict[str, str] = {
    "pre_development": "#6366f1",   # indigo
    "planning":        "#f59e0b",   # amber
    "grid_connection": "#0ea5e9",   # sky
    "detailed_design": "#8b5cf6",   # violet
    "enabling_works":  "#78909c",   # blue-grey
    "construction":    "#16a34a",   # green
    "commissioning":   "#ef4444",   # red
    "handover":        "#06b6d4",   # cyan
}

# ---------------------------------------------------------------------------
# Base phase templates per technology
# ---------------------------------------------------------------------------
# Each value: (start_month, end_month) for a "standard" project.
# These get scaled by capacity, fast-track, and modular factors.

_SOLAR_BASE: list[dict[str, Any]] = [
    {
        "id": "pre_development",
        "name": "Pre-Development",
        "start": 0, "end": 6,
        "description": "Site selection, land option, environmental screening, grid pre-application",
        "milestones": ["Land option signed", "Desktop environmental screening complete", "Grid pre-application submitted"],
    },
    {
        "id": "planning",
        "name": "Planning & Consents",
        "start": 3, "end": 12,
        "description": "EIA scoping, planning application, public consultation, determination",
        "milestones": ["EIA Scoping Opinion received", "Planning application submitted", "Public consultation complete", "Planning permission granted"],
    },
    {
        "id": "grid_connection",
        "name": "Grid Connection",
        "start": 6, "end": 18,
        "description": "G99 application, connection offer, acceptance, works programme",
        "milestones": ["G99 application submitted", "Connection offer received", "Offer accepted", "DNO works programme agreed"],
    },
    {
        "id": "detailed_design",
        "name": "Detailed Design",
        "start": 12, "end": 15,
        "description": "Procurement, detailed engineering, BOM finalisation",
        "milestones": ["EPC contract awarded", "Module procurement complete", "Detailed design frozen"],
    },
    {
        "id": "enabling_works",
        "name": "Enabling Works",
        "start": 15, "end": 18,
        "description": "Access road, fencing, drainage, cable trenching",
        "milestones": ["Access road complete", "Perimeter fencing installed", "Cable trenches excavated"],
    },
    {
        "id": "construction",
        "name": "Construction",
        "start": 18, "end": 24,
        "description": "Foundation, mounting structures, panel installation, electrical balance of plant",
        "milestones": ["Piling / foundations complete", "Mounting structures erected", "Panel installation complete", "Inverter & transformer installation complete"],
    },
    {
        "id": "commissioning",
        "name": "Commissioning",
        "start": 24, "end": 25,
        "description": "Testing, G99 compliance, energisation",
        "milestones": ["Protection relay testing complete", "G99 witness test passed", "First export / energisation"],
    },
    {
        "id": "handover",
        "name": "Handover",
        "start": 25, "end": 26,
        "description": "Defects period start, O&M contract, monitoring setup",
        "milestones": ["Practical completion certificate issued", "O&M contract executed", "SCADA / monitoring live"],
    },
]

_WIND_BASE: list[dict[str, Any]] = [
    {
        "id": "pre_development",
        "name": "Pre-Development",
        "start": 0, "end": 8,
        "description": "Site selection, wind resource measurement, land option, environmental screening, grid pre-application",
        "milestones": ["Met mast / LiDAR installed", "Land option signed", "Grid pre-application submitted"],
    },
    {
        "id": "planning",
        "name": "Planning & Consents",
        "start": 4, "end": 18,
        "description": "EIA scoping, LVIA, noise assessment, shadow flicker study, planning application, public consultation, determination",
        "milestones": ["EIA Scoping Opinion received", "LVIA complete", "Noise assessment complete", "Planning application submitted", "Planning permission granted"],
    },
    {
        "id": "grid_connection",
        "name": "Grid Connection",
        "start": 8, "end": 22,
        "description": "G99 application, connection offer, acceptance, works programme",
        "milestones": ["G99 application submitted", "Connection offer received", "Offer accepted", "DNO works programme agreed"],
    },
    {
        "id": "detailed_design",
        "name": "Detailed Design",
        "start": 18, "end": 22,
        "description": "Turbine procurement, foundation design, electrical design, BOM finalisation",
        "milestones": ["Turbine supply agreement signed", "Foundation design approved", "Detailed design frozen"],
    },
    {
        "id": "enabling_works",
        "name": "Enabling Works",
        "start": 22, "end": 26,
        "description": "Access road upgrade, crane hardstandings, cable trenching, temporary compound",
        "milestones": ["Access road upgrade complete", "Crane pads constructed", "Cable trenches excavated"],
    },
    {
        "id": "construction",
        "name": "Construction",
        "start": 26, "end": 34,
        "description": "Foundation construction, turbine erection, electrical balance of plant, substation build",
        "milestones": ["Foundations poured", "Turbine erection complete", "Substation energised", "Cable installation complete"],
    },
    {
        "id": "commissioning",
        "name": "Commissioning",
        "start": 34, "end": 36,
        "description": "Individual turbine commissioning, G99 compliance, grid compliance testing",
        "milestones": ["Individual turbine commissioning complete", "G99 witness test passed", "First export / energisation"],
    },
    {
        "id": "handover",
        "name": "Handover",
        "start": 36, "end": 37,
        "description": "Defects period start, O&M contract, SCADA handover",
        "milestones": ["Practical completion certificate issued", "O&M contract executed", "SCADA / monitoring live"],
    },
]

_BESS_BASE: list[dict[str, Any]] = [
    {
        "id": "pre_development",
        "name": "Pre-Development",
        "start": 0, "end": 4,
        "description": "Site selection, land option, environmental screening, grid pre-application",
        "milestones": ["Land option signed", "Desktop environmental screening complete", "Grid pre-application submitted"],
    },
    {
        "id": "planning",
        "name": "Planning & Consents",
        "start": 2, "end": 8,
        "description": "Planning application, battery safety assessment, public consultation, determination",
        "milestones": ["Battery safety assessment complete", "Planning application submitted", "Planning permission granted"],
    },
    {
        "id": "grid_connection",
        "name": "Grid Connection",
        "start": 4, "end": 12,
        "description": "G99 application, connection offer, acceptance, works programme",
        "milestones": ["G99 application submitted", "Connection offer received", "Offer accepted"],
    },
    {
        "id": "detailed_design",
        "name": "Detailed Design",
        "start": 8, "end": 10,
        "description": "Battery procurement, containerised unit specification, electrical design",
        "milestones": ["Battery supply agreement signed", "Container layout finalised", "Detailed design frozen"],
    },
    {
        "id": "enabling_works",
        "name": "Enabling Works",
        "start": 10, "end": 12,
        "description": "Site preparation, concrete pads, fencing, cable trenching",
        "milestones": ["Concrete pads poured", "Perimeter fencing installed", "Cable trenches excavated"],
    },
    {
        "id": "construction",
        "name": "Construction",
        "start": 12, "end": 15,
        "description": "Battery container placement, inverter/transformer install, cabling, fire suppression",
        "milestones": ["Battery containers placed", "Inverter & transformer installed", "Fire suppression system commissioned"],
    },
    {
        "id": "commissioning",
        "name": "Commissioning",
        "start": 15, "end": 16,
        "description": "Battery management system testing, G99 compliance, energisation",
        "milestones": ["BMS testing complete", "G99 witness test passed", "First charge/discharge cycle"],
    },
    {
        "id": "handover",
        "name": "Handover",
        "start": 16, "end": 17,
        "description": "Defects period start, O&M contract, revenue optimisation platform setup",
        "milestones": ["Practical completion certificate issued", "O&M contract executed", "Revenue optimisation platform live"],
    },
]

TECH_BASES: dict[str, list[dict[str, Any]]] = {
    "solar": _SOLAR_BASE,
    "wind": _WIND_BASE,
    "bess": _BESS_BASE,
}


# ---------------------------------------------------------------------------
# Timeline generation
# ---------------------------------------------------------------------------

def construction_timeline(
    capacity_mw: float = 50.0,
    technology: str = "solar",
    has_planning: bool = False,
    has_grid: bool = False,
    fast_track: bool = False,
    modular: bool = False,
) -> dict[str, Any]:
    """Generate a Gantt-style construction timeline for a renewable energy project.

    Parameters
    ----------
    capacity_mw : float
        Proposed project capacity in MW.
    technology : str
        One of 'solar', 'wind', or 'bess'.
    has_planning : bool
        If True, planning phase is marked complete and skipped.
    has_grid : bool
        If True, grid connection phase is marked complete and skipped.
    fast_track : bool
        If True, overlaps parallel activities more aggressively (~20% shorter).
    modular : bool
        If True, uses prefab/modular construction (~25% shorter construction).

    Returns
    -------
    dict
        phases, total_months, critical_path, summary.
    """
    tech = technology.lower().strip()
    if tech not in TECH_BASES:
        raise ValueError(f"Unknown technology '{technology}'. Must be one of: solar, wind, bess")

    base_phases = TECH_BASES[tech]

    # --- Capacity scaling factor ---
    # Large projects take longer (diminishing returns via log)
    if tech == "solar":
        if capacity_mw >= 50:
            # NSIP / DCO route — extends planning significantly
            capacity_factor = 1.0 + 0.15 * math.log2(max(1, capacity_mw / 50))
        else:
            capacity_factor = 0.85 + 0.15 * (capacity_mw / 50)
    elif tech == "wind":
        capacity_factor = 0.9 + 0.1 * math.log2(max(1, capacity_mw / 20))
    else:  # bess
        capacity_factor = 0.8 + 0.2 * (min(capacity_mw, 200) / 200)

    # --- Modifiers ---
    fast_track_factor = 0.80 if fast_track else 1.0
    modular_factor = 0.75 if modular else 1.0

    # NSIP threshold for solar
    is_nsip = tech == "solar" and capacity_mw >= 50

    # --- Build adjusted phases ---
    phases: list[dict[str, Any]] = []
    skip_ids = set()
    if has_planning:
        skip_ids.add("planning")
    if has_grid:
        skip_ids.add("grid_connection")

    # First pass: compute raw adjusted months
    adjusted: list[dict[str, Any]] = []
    for bp in base_phases:
        phase_id = bp["id"]
        raw_start = bp["start"]
        raw_end = bp["end"]
        raw_duration = raw_end - raw_start

        if phase_id in skip_ids:
            adjusted.append({
                **bp,
                "start": 0, "end": 0, "duration": 0,
                "skipped": True,
            })
            continue

        # Scale duration by capacity + modifiers
        duration = raw_duration * capacity_factor
        # Construction and enabling benefit from modular
        if phase_id in ("construction", "enabling_works"):
            duration *= modular_factor
        # Fast-track compresses everything except pre-dev and handover
        if phase_id not in ("pre_development", "handover"):
            duration *= fast_track_factor
        # NSIP extends planning by ~50%
        if phase_id == "planning" and is_nsip:
            duration *= 1.5

        duration = max(1, round(duration))
        adjusted.append({
            **bp,
            "start": raw_start,  # placeholder, recalculated below
            "end": raw_start + duration,
            "duration": duration,
            "skipped": False,
        })

    # Second pass: recalculate starts based on dependencies and overlap.
    # The base templates encode natural overlap (e.g. planning starts month 3
    # while pre-dev runs 0-6). We preserve the proportional overlap but
    # adjust for skipped phases and scaling.
    phase_by_id: dict[str, dict] = {}
    for ap in adjusted:
        pid = ap["id"]
        if ap.get("skipped"):
            phase_by_id[pid] = {"start": 0, "end": 0, "duration": 0, "skipped": True}
            continue

        bp = next(b for b in base_phases if b["id"] == pid)
        raw_start = bp["start"]

        # Find earliest base phase that this one could depend on
        # (i.e. phases with base end > this base start)
        deps = _infer_dependencies(pid, base_phases)

        if not deps:
            # First phase — starts at 0
            actual_start = 0
        else:
            # Start is the latest dependency end minus the proportional overlap
            dep_ends = []
            for dep_id in deps:
                dep_info = phase_by_id.get(dep_id)
                if dep_info and not dep_info.get("skipped"):
                    dep_ends.append(dep_info["end"])
            if dep_ends:
                # Original overlap between this phase start and its dep's end
                dep_bp = next(b for b in base_phases if b["id"] == deps[0])
                original_overlap = max(0, dep_bp["end"] - raw_start)
                scaled_overlap = round(original_overlap * capacity_factor)
                if fast_track:
                    scaled_overlap = round(scaled_overlap * 1.2)  # more overlap in fast-track
                actual_start = max(0, max(dep_ends) - scaled_overlap)
            else:
                actual_start = 0

        actual_end = actual_start + ap["duration"]
        phase_by_id[pid] = {
            "start": actual_start,
            "end": actual_end,
            "duration": ap["duration"],
            "skipped": False,
        }

    # Third pass: build output
    for ap in adjusted:
        pid = ap["id"]
        info = phase_by_id[pid]

        if info.get("skipped"):
            phases.append({
                "id": pid,
                "name": ap["name"],
                "start_month": 0,
                "end_month": 0,
                "duration_months": 0,
                "status": "complete",
                "dependencies": [],
                "milestones": [],
                "description": "Already secured — skipped",
                "colour": PHASE_COLOURS.get(pid, "#9e9e9e"),
            })
            continue

        deps = _infer_dependencies(pid, base_phases)
        # Filter out skipped deps
        active_deps = [d for d in deps if not phase_by_id.get(d, {}).get("skipped")]

        phases.append({
            "id": pid,
            "name": ap["name"],
            "start_month": info["start"],
            "end_month": info["end"],
            "duration_months": info["duration"],
            "status": "pending",
            "dependencies": active_deps,
            "milestones": ap.get("milestones", []),
            "description": ap["description"],
            "colour": PHASE_COLOURS.get(pid, "#9e9e9e"),
        })

    total_months = max((p["end_month"] for p in phases), default=0)

    # Critical path: longest sequential chain
    critical_path = [p["name"] for p in phases if p["status"] != "complete" and p["duration_months"] > 0]

    return {
        "technology": tech,
        "capacity_mw": capacity_mw,
        "phases": phases,
        "total_months": total_months,
        "total_years": round(total_months / 12, 1),
        "critical_path": critical_path,
        "is_nsip": is_nsip,
        "summary": {
            "technology": tech,
            "capacity_mw": capacity_mw,
            "total_months": total_months,
            "total_years": round(total_months / 12, 1),
            "planning_route": "NSIP / DCO (Planning Inspectorate)" if is_nsip else "LPA (Town & Country Planning)",
            "has_planning": has_planning,
            "has_grid": has_grid,
            "fast_track": fast_track,
            "modular": modular,
            "note": _summary_note(tech, capacity_mw, fast_track, modular),
        },
    }


def _infer_dependencies(phase_id: str, base_phases: list[dict]) -> list[str]:
    """Infer which phases a given phase depends on from the base template ordering."""
    phase_ids = [p["id"] for p in base_phases]
    idx = phase_ids.index(phase_id)
    if idx == 0:
        return []

    bp = next(b for b in base_phases if b["id"] == phase_id)
    raw_start = bp["start"]

    # A phase depends on any earlier phase whose base start < this phase's base start
    # and whose base end >= this phase's base start (i.e. they overlap or abut)
    deps = []
    for earlier in base_phases[:idx]:
        if earlier["start"] < raw_start:
            deps.append(earlier["id"])
        elif earlier["start"] == raw_start and earlier["end"] <= bp["end"]:
            # Concurrent phase — not a dependency
            pass
    # If no explicit deps found, depend on the immediately preceding phase
    if not deps and idx > 0:
        deps = [base_phases[idx - 1]["id"]]
    return deps


def _summary_note(tech: str, capacity_mw: float, fast_track: bool, modular: bool) -> str:
    parts = []
    if tech == "solar":
        if capacity_mw >= 50:
            parts.append(f"{capacity_mw:.0f}MW solar — NSIP/DCO route (Planning Inspectorate)")
        else:
            parts.append(f"{capacity_mw:.0f}MW solar — LPA planning route")
    elif tech == "wind":
        parts.append(f"{capacity_mw:.0f}MW wind — extended planning for LVIA & noise assessment")
    else:
        parts.append(f"{capacity_mw:.0f}MW BESS — accelerated programme")

    if fast_track:
        parts.append("Fast-track: parallel activities compressed ~20%")
    if modular:
        parts.append("Modular/prefab: construction phase compressed ~25%")
    return ". ".join(parts)


# ---------------------------------------------------------------------------
# SVG Gantt chart generation
# ---------------------------------------------------------------------------

def gantt_svg(
    timeline: dict[str, Any],
    width: int = 1200,
    row_height: int = 44,
    label_width: int = 200,
    margin_top: int = 50,
    margin_bottom: int = 30,
    margin_right: int = 30,
) -> str:
    """Render a timeline dict as an SVG Gantt chart.

    Parameters
    ----------
    timeline : dict
        Output of ``construction_timeline()``.
    width : int
        Total SVG width in pixels.
    row_height : int
        Height per phase row.
    label_width : int
        Width reserved for phase labels on the left.

    Returns
    -------
    str
        SVG markup string.
    """
    phases = [p for p in timeline["phases"] if p["duration_months"] > 0]
    if not phases:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="60"><text x="20" y="30" font-family="sans-serif" font-size="14" fill="#666">No phases to display</text></svg>'

    total_months = timeline["total_months"]
    n_phases = len(phases)
    chart_width = width - label_width - margin_right
    height = margin_top + n_phases * row_height + margin_bottom

    lines: list[str] = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">')
    lines.append('<defs>')
    lines.append('  <style>')
    lines.append('    .gantt-label { font-family: "Inter", "Segoe UI", sans-serif; font-size: 13px; fill: #334155; }')
    lines.append('    .gantt-month { font-family: "Inter", "Segoe UI", sans-serif; font-size: 11px; fill: #94a3b8; }')
    lines.append('    .gantt-title { font-family: "Inter", "Segoe UI", sans-serif; font-size: 16px; font-weight: 600; fill: #1e293b; }')
    lines.append('    .gantt-bar { rx: 4; ry: 4; }')
    lines.append('    .gantt-duration { font-family: "Inter", "Segoe UI", sans-serif; font-size: 11px; fill: #fff; font-weight: 500; }')
    lines.append('    .gantt-grid { stroke: #e2e8f0; stroke-width: 0.5; }')
    lines.append('  </style>')
    lines.append('</defs>')

    # Background
    lines.append(f'<rect width="{width}" height="{height}" fill="#f8fafc" rx="8"/>')

    # Title
    tech_label = timeline.get("technology", "").upper()
    cap = timeline.get("capacity_mw", 0)
    title = f"{cap:.0f}MW {tech_label} — Construction Programme ({total_months} months)"
    lines.append(f'<text x="{label_width}" y="28" class="gantt-title">{title}</text>')

    # Month grid lines and labels
    month_step = 1 if total_months <= 18 else (3 if total_months <= 48 else 6)
    for m in range(0, total_months + 1, month_step):
        x = label_width + (m / total_months) * chart_width
        lines.append(f'<line x1="{x:.1f}" y1="{margin_top}" x2="{x:.1f}" y2="{margin_top + n_phases * row_height}" class="gantt-grid"/>')
        lines.append(f'<text x="{x:.1f}" y="{margin_top - 6}" text-anchor="middle" class="gantt-month">M{m}</text>')

    # Phase rows
    for i, phase in enumerate(phases):
        y = margin_top + i * row_height
        # Alternating row background
        if i % 2 == 0:
            lines.append(f'<rect x="0" y="{y}" width="{width}" height="{row_height}" fill="#f1f5f9" opacity="0.5"/>')

        # Label
        label = phase["name"]
        if len(label) > 22:
            label = label[:20] + "…"
        lines.append(f'<text x="{label_width - 10}" y="{y + row_height * 0.6}" text-anchor="end" class="gantt-label">{_xml_escape(label)}</text>')

        # Bar
        bar_x = label_width + (phase["start_month"] / total_months) * chart_width
        bar_w = max(8, (phase["duration_months"] / total_months) * chart_width)
        bar_y = y + 8
        bar_h = row_height - 16
        colour = phase.get("colour", "#6366f1")
        lines.append(f'<rect x="{bar_x:.1f}" y="{bar_y}" width="{bar_w:.1f}" height="{bar_h}" fill="{colour}" class="gantt-bar" opacity="0.9"/>')

        # Duration text inside bar (if bar is wide enough)
        dur_text = f'{phase["duration_months"]}mo'
        if bar_w > 40:
            text_x = bar_x + bar_w / 2
            lines.append(f'<text x="{text_x:.1f}" y="{bar_y + bar_h * 0.7}" text-anchor="middle" class="gantt-duration">{dur_text}</text>')

    lines.append('</svg>')
    return "\n".join(lines)


def _xml_escape(s: str) -> str:
    """Minimal XML entity escaping."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

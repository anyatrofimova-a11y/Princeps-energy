"""GRIP-stage construction schedule builder with CPM critical-path analysis.

Builds a Gantt-compatible schedule for four UK energy project types:
  • solar          – solar farm (PV + BOP)
  • bess           – stand-alone grid-scale battery storage
  • dc             – data centre (base build + power/cooling fit-out)
  • wind_onshore   – onshore wind farm

Stages follow the NG ET Governance for Railway Investment Projects (GRIP)
framework adapted by National Grid / DNOs for generation connections:

    GRIP 1  Output definition
    GRIP 2  Feasibility
    GRIP 3  Option selection
    GRIP 4  Single-option development
    GRIP 5  Detailed design
    GRIP 6  Construction, test & commission
    GRIP 7  Scheme hand-back
    GRIP 8  Project close-out

Durations scale as:   d = d0 · (1 + α · log10(MW)) · complexity_multiplier
where α is a task-specific elasticity.  Dependencies are encoded as a simple
adjacency list and the critical path is found via classical CPM (forward
+ backward pass).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from datetime import date, timedelta
from typing import Literal


ProjectType = Literal["solar", "bess", "dc", "wind_onshore"]
Complexity = Literal["low", "med", "high"]

_COMPLEXITY_MULT: dict[str, float] = {"low": 0.85, "med": 1.00, "high": 1.25}


# ---------------------------------------------------------------------------
# Task templates — each entry: (id, name, grip_stage, base_days, mw_alpha, preds)
# ---------------------------------------------------------------------------
# `mw_alpha` is the scaling exponent; 0 means MW-independent, 0.15 means a
# 10× MW increase adds ~15 % duration.
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, list[tuple[str, str, int, int, float, list[str]]]] = {
    "solar": [
        ("T01", "Output definition & stakeholder map",                1,  20,  0.00, []),
        ("T02", "Feasibility & yield study",                          2,  30,  0.05, ["T01"]),
        ("T03", "Grid connection offer (DNO G99 ModA)",               2,  65,  0.10, ["T02"]),
        ("T04", "Land option / lease heads of terms",                 2,  45,  0.00, ["T01"]),
        ("T05", "Environmental scoping & EIA screening",              3,  60,  0.10, ["T02"]),
        ("T06", "Planning application (TCPA / NSIP)",                 3, 120,  0.20, ["T04", "T05"]),
        ("T07", "Planning consent decision",                          4, 180,  0.00, ["T06"]),
        ("T08", "Detailed design & procurement",                      5, 150,  0.15, ["T03", "T07"]),
        ("T09", "DNO connection agreement & works programme",         5,  90,  0.10, ["T07"]),
        ("T10", "Site mobilisation & access roads",                   6,  45,  0.15, ["T08"]),
        ("T11", "Piling & mounting structures",                       6,  90,  0.25, ["T10"]),
        ("T12", "Module & cable install",                             6,  90,  0.30, ["T11"]),
        ("T13", "Substation civils & plant",                          6, 120,  0.15, ["T10", "T09"]),
        ("T14", "DC/AC commissioning",                                6,  45,  0.10, ["T12", "T13"]),
        ("T15", "G99 witness & energisation",                         6,  20,  0.00, ["T14"]),
        ("T16", "Performance ratio test & takeover",                  7,  30,  0.05, ["T15"]),
        ("T17", "Project close-out & O&M handover",                   8,  20,  0.00, ["T16"]),
    ],
    "bess": [
        ("T01", "Output definition",                                  1,  15,  0.00, []),
        ("T02", "Feasibility & revenue stacking (BM/DC/capacity)",    2,  30,  0.05, ["T01"]),
        ("T03", "Grid connection offer (G99)",                        2,  75,  0.10, ["T02"]),
        ("T04", "Land option",                                        2,  30,  0.00, ["T01"]),
        ("T05", "Fire / DSEAR safety case & NFCC pre-app",            3,  45,  0.05, ["T04"]),
        ("T06", "Planning application",                               3,  90,  0.15, ["T04", "T05"]),
        ("T07", "Planning consent",                                   4, 150,  0.00, ["T06"]),
        ("T08", "Detailed design (FEED) & OEM selection",             5, 120,  0.15, ["T03", "T07"]),
        ("T09", "Connection agreement",                               5,  90,  0.10, ["T07"]),
        ("T10", "Civils & fire walls",                                6,  60,  0.15, ["T08"]),
        ("T11", "Container / enclosure install",                      6,  60,  0.20, ["T10"]),
        ("T12", "Inverter & MV cable",                                6,  45,  0.15, ["T11"]),
        ("T13", "Substation works",                                   6,  90,  0.10, ["T09", "T10"]),
        ("T14", "Commissioning & black-start tests",                  6,  45,  0.05, ["T12", "T13"]),
        ("T15", "Energisation",                                       6,  15,  0.00, ["T14"]),
        ("T16", "BMU registration & go-live",                         7,  30,  0.00, ["T15"]),
        ("T17", "Close-out",                                          8,  15,  0.00, ["T16"]),
    ],
    "dc": [
        ("T01", "Programme definition & brief",                       1,  30,  0.00, []),
        ("T02", "Feasibility, site search, power study",              2,  60,  0.10, ["T01"]),
        ("T03", "Grid offer / ESO application (≥50 MW)",              2, 120,  0.15, ["T02"]),
        ("T04", "Land option / lease",                                2,  60,  0.00, ["T01"]),
        ("T05", "EIA & planning pre-app",                             3,  90,  0.10, ["T04"]),
        ("T06", "Planning (DCO / TCPA)",                              3, 180,  0.20, ["T05"]),
        ("T07", "Consent decision",                                   4, 240,  0.00, ["T06"]),
        ("T08", "RIBA 4 detailed design",                             5, 180,  0.15, ["T03", "T07"]),
        ("T09", "Long-lead procurement (transformers, chillers)",     5, 270,  0.20, ["T08"]),
        ("T10", "Enabling works & earthworks",                        6,  90,  0.20, ["T07"]),
        ("T11", "Shell & core construction",                          6, 330,  0.25, ["T10"]),
        ("T12", "MEP fit-out (power, cooling)",                       6, 270,  0.30, ["T11", "T09"]),
        ("T13", "Grid substation build",                              6, 300,  0.20, ["T03"]),
        ("T14", "Integrated Systems Test (IST)",                      6,  60,  0.10, ["T12", "T13"]),
        ("T15", "Customer handover & go-live",                        7,  45,  0.05, ["T14"]),
        ("T16", "Close-out & snagging",                               8,  60,  0.00, ["T15"]),
    ],
    "wind_onshore": [
        ("T01", "Output definition",                                  1,  20,  0.00, []),
        ("T02", "Feasibility (wind resource, bats, birds)",           2,  90,  0.10, ["T01"]),
        ("T03", "Grid connection offer",                              2,  75,  0.10, ["T02"]),
        ("T04", "Land options & community engagement",                2, 120,  0.00, ["T01"]),
        ("T05", "EIA scoping & 12-mo ecology survey",                 3, 365,  0.00, ["T02"]),
        ("T06", "Planning (Section 36 / TCPA)",                       3, 365,  0.10, ["T05", "T04"]),
        ("T07", "Consent decision (likely inquiry)",                  4, 400,  0.00, ["T06"]),
        ("T08", "Detailed design & turbine procurement",              5, 240,  0.15, ["T07", "T03"]),
        ("T09", "Connection agreement",                               5,  90,  0.10, ["T07"]),
        ("T10", "Access tracks & crane hardstandings",                6,  90,  0.15, ["T08"]),
        ("T11", "Foundations",                                        6, 120,  0.20, ["T10"]),
        ("T12", "Turbine delivery & erection",                        6, 120,  0.25, ["T11"]),
        ("T13", "Substation & network works",                         6, 150,  0.10, ["T09", "T10"]),
        ("T14", "Commissioning / G99 witness",                        6,  60,  0.05, ["T12", "T13"]),
        ("T15", "Energisation & power-curve test",                    6,  45,  0.00, ["T14"]),
        ("T16", "Takeover & handover",                                7,  30,  0.00, ["T15"]),
        ("T17", "Close-out",                                          8,  15,  0.00, ["T16"]),
    ],
}


@dataclass
class Task:
    id: str
    name: str
    stage: int
    start: str              # ISO date
    end: str                # ISO date
    duration_days: int
    predecessors: list[str]
    early_start: int = 0    # day offsets for CPM debugging
    early_finish: int = 0
    late_start: int = 0
    late_finish: int = 0
    float_days: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Schedule:
    project_type: str
    mw: float
    site_complexity: str
    start_date: str
    end_date: str
    total_duration_days: int
    critical_path: list[str]
    tasks: list[dict]
    standard: str = "National Grid GRIP 1-8 (adapted for generation connections)"

    def to_dict(self) -> dict:
        return asdict(self)


def _scale_duration(base_days: int, mw: float, alpha: float, complexity_mult: float) -> int:
    scale = 1.0 + alpha * math.log10(max(mw, 1.0))
    return max(1, round(base_days * scale * complexity_mult))


def critical_path_method(tasks: list[dict]) -> list[str]:
    """Classical forward + backward pass CPM.

    `tasks` is a list of dicts with keys `id`, `duration_days`, `predecessors`.
    Returns the ordered list of task IDs lying on the critical path (zero-float
    tasks chained from the earliest end-of-path successor back to origin).
    """
    by_id = {t["id"]: dict(t) for t in tasks}
    order = _topological_order(by_id)

    # Forward pass
    for tid in order:
        t = by_id[tid]
        preds = t.get("predecessors") or []
        es = max((by_id[p]["_ef"] for p in preds), default=0)
        t["_es"] = es
        t["_ef"] = es + t["duration_days"]

    project_end = max(t["_ef"] for t in by_id.values())

    # Backward pass
    for tid in reversed(order):
        t = by_id[tid]
        successors = [s for s in by_id.values() if tid in (s.get("predecessors") or [])]
        if not successors:
            t["_lf"] = project_end
        else:
            t["_lf"] = min(s["_ls"] for s in successors)
        t["_ls"] = t["_lf"] - t["duration_days"]
        t["_float"] = t["_ls"] - t["_es"]

    # Trace critical path: zero float, longest chain
    critical = [t for t in by_id.values() if t["_float"] == 0]
    critical.sort(key=lambda t: t["_es"])
    path_ids = [t["id"] for t in critical]
    return path_ids


def _topological_order(by_id: dict[str, dict]) -> list[str]:
    indeg = {tid: 0 for tid in by_id}
    for tid, t in by_id.items():
        for p in (t.get("predecessors") or []):
            indeg[tid] += 1
    q = [tid for tid, v in indeg.items() if v == 0]
    out: list[str] = []
    visited = set()
    while q:
        tid = q.pop(0)
        if tid in visited:
            continue
        visited.add(tid)
        out.append(tid)
        for other_id, other in by_id.items():
            if tid in (other.get("predecessors") or []) and other_id not in visited:
                # Remove dependency
                if indeg.get(other_id, 0) > 0:
                    indeg[other_id] -= 1
                if indeg[other_id] == 0:
                    q.append(other_id)
    # Fallback: append any unordered tasks (in case of cycles, defensive)
    for tid in by_id:
        if tid not in visited:
            out.append(tid)
    return out


def build_schedule(
    project_type: ProjectType,
    mw: float,
    start_date: date,
    site_complexity: Complexity = "med",
) -> Schedule:
    """Assemble a full GRIP schedule and compute its critical path."""
    if project_type not in _TEMPLATES:
        raise ValueError(f"Unsupported project_type {project_type!r}")
    if mw <= 0:
        raise ValueError("mw must be > 0")
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)

    cmult = _COMPLEXITY_MULT[site_complexity]
    tmpl = _TEMPLATES[project_type]

    # Compose raw tasks
    raw = []
    for tid, name, stage, base, alpha, preds in tmpl:
        raw.append({
            "id": tid,
            "name": name,
            "stage": stage,
            "duration_days": _scale_duration(base, mw, alpha, cmult),
            "predecessors": list(preds),
        })

    # CPM -> dates
    critical = critical_path_method(raw)
    order = _topological_order({t["id"]: t for t in raw})

    by_id = {t["id"]: t for t in raw}
    out_tasks: list[Task] = []
    for tid in order:
        t = by_id[tid]
        preds = t["predecessors"]
        earliest_preds = [by_id[p]["_end_offset"] for p in preds] if preds else [0]
        start_off = max(earliest_preds) if earliest_preds else 0
        end_off = start_off + t["duration_days"]
        t["_start_offset"] = start_off
        t["_end_offset"] = end_off
        # Convert _es / _ls from CPM for debugging
        out_tasks.append(Task(
            id=t["id"],
            name=t["name"],
            stage=t["stage"],
            start=(start_date + timedelta(days=start_off)).isoformat(),
            end=(start_date + timedelta(days=end_off)).isoformat(),
            duration_days=t["duration_days"],
            predecessors=list(t["predecessors"]),
            early_start=t.get("_es", start_off),
            early_finish=t.get("_ef", end_off),
            late_start=t.get("_ls", start_off),
            late_finish=t.get("_lf", end_off),
            float_days=t.get("_float", 0),
        ))

    total = max(t.early_finish for t in out_tasks)
    end_date = start_date + timedelta(days=total)

    # Preserve template-original ordering in output
    template_order = [t[0] for t in tmpl]
    out_tasks.sort(key=lambda x: template_order.index(x.id))

    return Schedule(
        project_type=project_type,
        mw=mw,
        site_complexity=site_complexity,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        total_duration_days=total,
        critical_path=critical,
        tasks=[t.to_dict() for t in out_tasks],
    )

"""DC Planner — package facade.

Re-exports the legacy ``plan_facility`` and ``simulate_telemetry`` entry points
from ``facility.py`` so existing imports keep working, and surfaces the new
``auto_design`` orchestrator.
"""

from __future__ import annotations

from utils.dc_planner.facility import (
    plan_facility,
    simulate_telemetry,
    estimate_carbon_footprint,
    estimate_construction_timeline,
    estimate_land_area,
    COST_BENCHMARKS,
    UK_ELEC_PENCE_KWH,
)
from utils.dc_planner.auto_design import (
    auto_design,
    DcDesign,
    AutoDesignParams,
)

__all__ = [
    "plan_facility",
    "simulate_telemetry",
    "estimate_carbon_footprint",
    "estimate_construction_timeline",
    "estimate_land_area",
    "COST_BENCHMARKS",
    "UK_ELEC_PENCE_KWH",
    "auto_design",
    "DcDesign",
    "AutoDesignParams",
]

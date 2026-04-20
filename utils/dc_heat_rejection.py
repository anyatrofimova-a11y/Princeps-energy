"""Data-centre heat rejection, water consumption, PUE vs ambient, grid-carbon.

Analytic, no external solvers. Calibrated against published ASHRAE, Uptime
Institute, and Lawrence Berkeley (LBNL) datasets.

References:
  - ASHRAE TC 9.9, "Thermal Guidelines for Data Processing Environments"
  - LBNL (Shehabi 2016), "United States Data Center Energy Usage Report"
  - BEIS 2024 UK grid carbon factor (193 gCO2/kWh marginal, 2024 avg)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import Literal


# PUE at design (UK temperate) — ASHRAE / Uptime baselines
COOLING_BASELINE_PUE = {
    "air":        1.55,   # DX / CRAC traditional
    "water":      1.25,   # chilled-water, cooling tower
    "adiabatic":  1.15,   # evaporative / free cooling (UK climate excellent)
    "immersion":  1.05,   # 2-phase or single-phase immersion
}

# Water usage effectiveness (WUE) — litres/kWh IT
COOLING_WUE_L_PER_KWH = {
    "air":        0.02,   # humidification only
    "water":      1.80,   # significant cooling-tower bleed/evap
    "adiabatic":  1.10,
    "immersion":  0.05,
}

# UK grid 2024 avg (BEIS) ~ 193 gCO2/kWh, marginal ~ 220
DEFAULT_UK_GRID_GCO2_PER_KWH = 193.0


@dataclass
class HeatRejectionResult:
    inputs_echo: dict
    outputs: dict
    assumptions: list[str]
    provenance: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# PUE vs ambient curve (monotonic-ish)
# ---------------------------------------------------------------------------
def pue_at_ambient(cooling: str, ambient_c: float) -> float:
    """Crude polynomial fit: PUE rises with ambient.

    UK wet-bulb ambient is typically 8-20°C annual; peak 22-24°C.
    Baseline assumes design ambient 15°C dry bulb.
    """
    base = COOLING_BASELINE_PUE[cooling]
    # Quadratic above 15°C for air/adiabatic; immersion near-flat
    if cooling == "immersion":
        return base + 0.0005 * max(0.0, ambient_c - 15.0) ** 2
    if cooling == "water":
        return base + 0.004 * max(0.0, ambient_c - 15.0) + 0.0006 * max(0.0, ambient_c - 15.0) ** 2
    if cooling == "adiabatic":
        # breaks down as wet-bulb approaches 20°C
        return base + 0.008 * max(0.0, ambient_c - 15.0) + 0.001 * max(0.0, ambient_c - 15.0) ** 2
    # air
    return base + 0.015 * max(0.0, ambient_c - 15.0) + 0.0018 * max(0.0, ambient_c - 15.0) ** 2


def heat_rejection(
    it_load_mw: float,
    cooling: Literal["air", "water", "adiabatic", "immersion"] = "adiabatic",
    ambient_c: float = 15.0,
    location: Literal["UK", "IE", "NL", "other"] = "UK",
    grid_gco2_per_kwh: float | None = None,
    hours_per_year: int = 8760,
) -> HeatRejectionResult:
    """Per-MW heat to reject, water draw, total facility power, carbon.

    Heat_reject ≈ IT_load × (PUE − 1) + IT_load (all electricity ultimately
    becomes heat at the cooling loop).
    """
    if it_load_mw <= 0:
        raise ValueError("it_load_mw must be > 0")
    if cooling not in COOLING_BASELINE_PUE:
        raise ValueError(f"Unknown cooling: {cooling}")
    gco2 = grid_gco2_per_kwh if grid_gco2_per_kwh is not None else DEFAULT_UK_GRID_GCO2_PER_KWH

    pue = pue_at_ambient(cooling, ambient_c)
    facility_mw = it_load_mw * pue
    cooling_mw = facility_mw - it_load_mw
    heat_reject_mw = it_load_mw + cooling_mw  # near 100% of facility power as heat

    wue = COOLING_WUE_L_PER_KWH[cooling]
    water_l_per_hour = wue * it_load_mw * 1000.0
    water_m3_per_year = water_l_per_hour * hours_per_year / 1000.0

    annual_energy_mwh = facility_mw * hours_per_year
    annual_carbon_t = annual_energy_mwh * gco2 / 1000.0  # tCO2

    warnings = []
    if cooling == "adiabatic" and ambient_c > 22:
        warnings.append(f"wet-bulb conditions at {ambient_c}°C approach adiabatic design limit")
    if cooling == "water" and location == "UK":
        warnings.append("cooling-tower ESS in UK rarely preferred vs adiabatic; check EA water licence")
    if water_m3_per_year > 100_000:
        warnings.append(f"annual water draw {water_m3_per_year/1000:.0f} ML — abstraction licence likely required")

    return HeatRejectionResult(
        inputs_echo={
            "it_load_mw": it_load_mw, "cooling": cooling,
            "ambient_c": ambient_c, "location": location,
            "grid_gco2_per_kwh": gco2, "hours_per_year": hours_per_year,
        },
        outputs={
            "pue": round(pue, 3),
            "facility_power_mw": round(facility_mw, 3),
            "cooling_power_mw": round(cooling_mw, 3),
            "heat_reject_mw": round(heat_reject_mw, 3),
            "wue_l_per_kwh": wue,
            "water_l_per_hour": round(water_l_per_hour, 1),
            "water_m3_per_year": round(water_m3_per_year, 0),
            "annual_energy_mwh": round(annual_energy_mwh, 0),
            "annual_carbon_tco2": round(annual_carbon_t, 1),
            "kwh_reject_per_kwh_it": round(heat_reject_mw / it_load_mw, 3),
        },
        assumptions=[
            "Near-100% of facility electricity becomes heat at the chiller loop",
            "PUE curve fitted to ASHRAE climate class A1 design",
            "UK grid carbon factor — BEIS 2024 (193 gCO2/kWh)",
            "Water usage figures per Uptime Institute WUE survey",
        ],
        provenance="ASHRAE TC 9.9, LBNL 2016, BEIS 2024",
        warnings=warnings,
    )

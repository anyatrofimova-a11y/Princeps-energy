"""BESS thermal, cycle-life, augmentation and NFPA 855 safety zoning.

Analytic models, no external solvers. Covers LFP and NMC chemistries.

References:
  - NFPA 855 (2023) — Standard for the Installation of Stationary ESS
  - IEC 62933-5-2 — Safety requirements for electrochemical-based ESS
  - Arrhenius degradation model (k = A · exp(-Ea/RT))
  - Wang et al. (2014), J. Power Sources — cycle/calendar life LFP/NMC

See also: :mod:`utils.tdd.bess_commercial` for the commercial / compliance
layer (augmentation plan, UL 9540A audit, PAS 63100 cross-walk).  That
module is exposed at the bottom of this file for convenience so existing
callers that import ``from utils.bess_thermal import augmentation_plan``
can upgrade to the richer commercial plan without touching layout code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import Literal


# ---------------------------------------------------------------------------
# Chemistry parameters
# ---------------------------------------------------------------------------
# Activation energies and pre-exponentials calibrated against published cycling
# data (Wang 2014, NREL 2019). Calendar fade at 25°C ≈ 2-3%/yr LFP, 3-4%/yr NMC.
CHEMISTRY = {
    "LFP": {
        "nominal_cycles_at_80_dod_25c": 6000,
        "calendar_fade_per_yr_25c": 0.022,
        "Ea_cycle_kJ_mol": 24.5,     # cycle ageing
        "Ea_calendar_kJ_mol": 58.0,  # calendar ageing
        "thermal_runaway_onset_c": 180.0,
        "specific_heat_j_kg_k": 1050.0,
        "nfpa_max_unit_kwh": 600.0,    # NFPA 855 Table 15.9.2.1.1
        "nfpa_min_separation_m": 3.0,
        "energy_density_wh_kg": 140.0,
    },
    "NMC": {
        "nominal_cycles_at_80_dod_25c": 3500,
        "calendar_fade_per_yr_25c": 0.035,
        "Ea_cycle_kJ_mol": 22.0,
        "Ea_calendar_kJ_mol": 52.0,
        "thermal_runaway_onset_c": 150.0,
        "specific_heat_j_kg_k": 1100.0,
        "nfpa_max_unit_kwh": 600.0,
        "nfpa_min_separation_m": 3.0,
        "energy_density_wh_kg": 220.0,
    },
}

R_GAS_J_MOL_K = 8.314


def _arrhenius_multiplier(ea_kj_mol: float, t_ref_c: float, t_op_c: float) -> float:
    """Return degradation-rate multiplier at t_op relative to t_ref."""
    t_ref_k = t_ref_c + 273.15
    t_op_k = t_op_c + 273.15
    return math.exp(
        (ea_kj_mol * 1000 / R_GAS_J_MOL_K) * (1.0 / t_ref_k - 1.0 / t_op_k)
    )


# ---------------------------------------------------------------------------
# Results dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ThermalResult:
    inputs_echo: dict
    outputs: dict
    assumptions: list[str]
    provenance: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Cell thermal — steady-state with ambient + duty cycle heat source
# ---------------------------------------------------------------------------
def cell_thermal(
    ambient_c: float,
    c_rate: float,
    cycles_per_day: float,
    cooling: Literal["passive", "forced_air", "liquid"] = "forced_air",
    chemistry: Literal["LFP", "NMC"] = "LFP",
) -> ThermalResult:
    """Estimate cell surface temperature from ambient + duty losses.

    I^2 R losses dominate at higher C-rates. We apply a simple thermal
    resistance model R_th depending on cooling medium.
    """
    if chemistry not in CHEMISTRY:
        raise ValueError(f"Unsupported chemistry: {chemistry}")
    if c_rate <= 0 or cycles_per_day <= 0:
        raise ValueError("c_rate and cycles_per_day must be > 0")

    # Equivalent internal resistance heat load (W/kg) at given C-rate.
    # LFP cells dissipate ~3-5% of energy through the cell at 1C.
    loss_fraction = 0.035 + 0.015 * (c_rate - 1.0) if c_rate > 1.0 else 0.035 * c_rate
    loss_fraction = max(0.015, min(0.12, loss_fraction))

    # Thermal resistance cell-to-ambient (K / (W/kg))
    r_th = {"passive": 3.5, "forced_air": 1.2, "liquid": 0.4}[cooling]

    duty_factor = min(1.0, cycles_per_day / 2.0)  # 2 cyc/day ~ continuous
    heat_w_per_kg = loss_fraction * c_rate * 30.0 * duty_factor  # scale ~30 W/kg nominal
    dt = heat_w_per_kg * r_th
    cell_c = round(ambient_c + dt, 1)

    params = CHEMISTRY[chemistry]
    warnings = []
    if cell_c > params["thermal_runaway_onset_c"] * 0.45:
        warnings.append(f"cell temperature {cell_c}°C exceeds 45% of runaway onset")
    if cell_c > 50:
        warnings.append("cell temperature > 50°C — accelerated ageing and warranty risk")

    return ThermalResult(
        inputs_echo={
            "ambient_c": ambient_c, "c_rate": c_rate,
            "cycles_per_day": cycles_per_day,
            "cooling": cooling, "chemistry": chemistry,
        },
        outputs={
            "cell_temp_c": cell_c,
            "cell_delta_t_c": round(dt, 1),
            "heat_dissipation_w_per_kg": round(heat_w_per_kg, 2),
            "loss_fraction": round(loss_fraction, 4),
            "thermal_resistance_k_per_w_kg": r_th,
            "runaway_margin_c": round(params["thermal_runaway_onset_c"] - cell_c, 1),
        },
        assumptions=[
            "Steady-state lumped-mass model (no transient thermal runaway)",
            f"Thermal resistance {r_th} K/(W/kg) for {cooling}",
            "Loss fraction scales linearly above 1C",
            f"Thermal runaway onset {params['thermal_runaway_onset_c']}°C for {chemistry}",
        ],
        provenance="IEC 62933-5-2, NREL battery thermal studies",
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Cycle-life degradation
# ---------------------------------------------------------------------------
def cycle_life(
    chemistry: Literal["LFP", "NMC"],
    avg_temp_c: float,
    avg_dod_pct: float,
    cycles_per_day: float,
    years: int = 15,
) -> ThermalResult:
    """Project SoH degradation over `years` with an Arrhenius + DoD model."""
    if chemistry not in CHEMISTRY:
        raise ValueError(f"Unsupported chemistry: {chemistry}")
    if not (0 < avg_dod_pct <= 100):
        raise ValueError("avg_dod_pct in (0, 100]")

    p = CHEMISTRY[chemistry]
    k_cycle = _arrhenius_multiplier(p["Ea_cycle_kJ_mol"], 25.0, avg_temp_c)
    k_cal = _arrhenius_multiplier(p["Ea_calendar_kJ_mol"], 25.0, avg_temp_c)

    # DoD scaling — Wang fit, exponent ~2 for LFP, ~2.5 for NMC.
    dod_scale = (avg_dod_pct / 80.0) ** (2.0 if chemistry == "LFP" else 2.5)

    cycles_total = cycles_per_day * 365 * years
    # Nominal cycles = cycles to 80% SoH (industry EOL), so 20% fade over
    # rated cycle count. Scale by DoD & Arrhenius.
    cycle_fade = 0.20 * (cycles_total / p["nominal_cycles_at_80_dod_25c"]) * dod_scale * k_cycle
    cal_fade = p["calendar_fade_per_yr_25c"] * years * k_cal
    total_fade = cycle_fade + cal_fade
    eol_soh = max(0.0, 1.0 - total_fade)

    warnings = []
    if eol_soh < 0.7:
        warnings.append(f"projected SoH {eol_soh:.0%} < 70% — augmentation required")
    if avg_temp_c > 35:
        warnings.append(f"avg cell temp {avg_temp_c}°C accelerates ageing (Arrhenius ×{k_cycle:.2f})")

    return ThermalResult(
        inputs_echo={
            "chemistry": chemistry, "avg_temp_c": avg_temp_c,
            "avg_dod_pct": avg_dod_pct,
            "cycles_per_day": cycles_per_day, "years": years,
        },
        outputs={
            "end_of_period_soh": round(eol_soh, 4),
            "cycle_fade_fraction": round(cycle_fade, 4),
            "calendar_fade_fraction": round(cal_fade, 4),
            "total_fade_fraction": round(total_fade, 4),
            "arrhenius_cycle_multiplier": round(k_cycle, 3),
            "arrhenius_calendar_multiplier": round(k_cal, 3),
            "equivalent_full_cycles": round(cycles_total, 0),
        },
        assumptions=[
            "Arrhenius reference: 25°C",
            "DoD exponent: 2.0 (LFP), 2.5 (NMC) — Wang 2014",
            "Cycle + calendar fade sum linearly (approximation)",
            "Nominal rated life at 80% DoD, 25°C",
        ],
        provenance="Wang 2014 J. Power Sources; NREL SAM battery model",
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Augmentation sizing — hold nameplate for `hold_years`
# ---------------------------------------------------------------------------
def augmentation_plan(
    nameplate_mwh: float,
    chemistry: Literal["LFP", "NMC"],
    avg_temp_c: float = 25.0,
    avg_dod_pct: float = 80.0,
    cycles_per_day: float = 1.0,
    hold_years: int = 15,
    eol_threshold: float = 0.70,
) -> ThermalResult:
    """Produce a year-by-year augmentation schedule to keep energy ≥ nameplate.

    Simple heuristic: cumulative fade is checked each year; when it crosses
    (1 − eol_threshold), we "top up" with new cells sized to restore nameplate.
    """
    if nameplate_mwh <= 0:
        raise ValueError("nameplate_mwh must be > 0")

    schedule: list[dict] = []
    remaining_capacity = nameplate_mwh
    cumulative_new_mwh = 0.0

    for yr in range(1, hold_years + 1):
        ann = cycle_life(
            chemistry=chemistry, avg_temp_c=avg_temp_c,
            avg_dod_pct=avg_dod_pct, cycles_per_day=cycles_per_day, years=1,
        )
        fade = ann.outputs["total_fade_fraction"]
        remaining_capacity *= (1.0 - fade)
        if remaining_capacity < nameplate_mwh * eol_threshold:
            top_up = nameplate_mwh - remaining_capacity
            cumulative_new_mwh += top_up
            schedule.append({
                "year": yr,
                "action": "augment",
                "top_up_mwh": round(top_up, 3),
                "remaining_before_mwh": round(remaining_capacity, 3),
            })
            remaining_capacity = nameplate_mwh
        else:
            schedule.append({
                "year": yr,
                "action": "hold",
                "remaining_mwh": round(remaining_capacity, 3),
            })

    # Rule-of-thumb oversize at day-0
    annual_fade_pct = CHEMISTRY[chemistry]["calendar_fade_per_yr_25c"] * 100.0
    initial_oversize_pct = max(10.0, annual_fade_pct * hold_years * 0.6)

    return ThermalResult(
        inputs_echo={
            "nameplate_mwh": nameplate_mwh, "chemistry": chemistry,
            "avg_temp_c": avg_temp_c, "avg_dod_pct": avg_dod_pct,
            "cycles_per_day": cycles_per_day, "hold_years": hold_years,
            "eol_threshold": eol_threshold,
        },
        outputs={
            "annual_schedule": schedule,
            "total_augmentation_mwh": round(cumulative_new_mwh, 3),
            "recommended_day0_oversize_pct": round(initial_oversize_pct, 1),
            "n_augmentations": sum(1 for s in schedule if s["action"] == "augment"),
        },
        assumptions=[
            "Annual fade treated as step-change at year end",
            f"Augmentation triggered below {eol_threshold*100:.0f}% of nameplate",
            "Augmentation cells assumed fresh (SoH = 1.0)",
        ],
        provenance="Industry practice (RWE, Fluence, Wärtsilä augmentation guides)",
        warnings=[],
    )


# ---------------------------------------------------------------------------
# NFPA 855 safety-zone buffers
# ---------------------------------------------------------------------------
def nfpa_855_safety_zones(
    enclosure_kwh: float,
    chemistry: Literal["LFP", "NMC"],
    n_enclosures: int,
    near_residential: bool = False,
    near_ignition_source: bool = False,
) -> ThermalResult:
    """Derive NFPA 855 separation distances, exposure-hazard zone radii.

    NFPA 855 requires:
      - 3 ft (0.9 m) min between groups of ESS units < 50 kWh.
      - Large format groups (> 600 kWh) need 10 ft (3 m) separation plus
        explicit fire-test data (UL 9540A). Outdoor walk-in ESS typically 3 m.
    """
    if enclosure_kwh <= 0 or n_enclosures <= 0:
        raise ValueError("enclosure_kwh and n_enclosures must be > 0")

    p = CHEMISTRY[chemistry]
    warnings = []

    min_sep = p["nfpa_min_separation_m"]
    # Unit size rule
    if enclosure_kwh > p["nfpa_max_unit_kwh"]:
        warnings.append(
            f"enclosure {enclosure_kwh} kWh > NFPA 855 max {p['nfpa_max_unit_kwh']} kWh — requires UL 9540A"
        )
        min_sep = max(min_sep, 6.0)

    # Exposure separation distances (outdoors)
    # Lot-line to critical asset — NFPA 855 Chapter 15 & 5
    sep_to_lot_line = 3.0
    sep_to_building_opening = 3.0
    sep_to_vegetation = 3.0
    sep_to_public_way = 3.0
    sep_to_residential = 7.6 if chemistry == "NMC" else 4.5

    if near_residential:
        warnings.append("residential receptors within 10 m — fire-engineered solution likely required")
    if near_ignition_source:
        warnings.append("ignition source within 10 m — additional detection/suppression required")

    total_footprint_m2 = n_enclosures * 20.0 * (1.0 + (min_sep / 12.0))  # ~20 m² ea + aisle

    return ThermalResult(
        inputs_echo={
            "enclosure_kwh": enclosure_kwh, "chemistry": chemistry,
            "n_enclosures": n_enclosures,
            "near_residential": near_residential,
            "near_ignition_source": near_ignition_source,
        },
        outputs={
            "min_enclosure_separation_m": min_sep,
            "separation_to_lot_line_m": sep_to_lot_line,
            "separation_to_building_opening_m": sep_to_building_opening,
            "separation_to_vegetation_m": sep_to_vegetation,
            "separation_to_public_way_m": sep_to_public_way,
            "separation_to_residential_m": sep_to_residential,
            "estimated_footprint_m2": round(total_footprint_m2, 0),
            "ul_9540a_required": enclosure_kwh > p["nfpa_max_unit_kwh"],
        },
        assumptions=[
            "NFPA 855 2023 edition, outdoor walk-in ESS assumption",
            "Distances per Chapter 15.9 (lithium-ion)",
            f"Chemistry-specific residential offset ({sep_to_residential} m)",
        ],
        provenance="NFPA 855 (2023), IEC 62933-5-2",
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Commercial-compliance re-exports (additive — see utils.tdd.bess_commercial)
# ---------------------------------------------------------------------------
# These are imported lazily to avoid introducing import cycles when
# utils.tdd.bess_commercial pulls ``CHEMISTRY`` and ``cycle_life`` from
# above.  They let downstream callers write::
#
#     from utils.bess_thermal import (
#         augmentation_plan,            # legacy thermodynamic schedule
#         build_augmentation_plan,      # richer commercial plan (£ + SoH)
#         run_ul_9540a_audit,           # UL 9540A conformance check
#         build_pas_63100_crosswalk,    # PAS 63100:2024 cross-walk
#     )
#
# while keeping the heavyweight commercial module out of the module-level
# import path for the thermodynamic API consumers.
def _commercial_exports() -> dict:
    from utils.tdd.bess_commercial import (  # noqa: WPS433 — local import
        AugmentationPlan,
        AugmentationEvent,
        CapacityRetentionPoint,
        UL9540AAudit,
        UL9540AFinding,
        PAS63100CrossWalk,
        PAS63100Mapping,
        build_augmentation_plan,
        run_ul_9540a_audit,
        build_pas_63100_crosswalk,
    )
    return {
        "AugmentationPlan": AugmentationPlan,
        "AugmentationEvent": AugmentationEvent,
        "CapacityRetentionPoint": CapacityRetentionPoint,
        "UL9540AAudit": UL9540AAudit,
        "UL9540AFinding": UL9540AFinding,
        "PAS63100CrossWalk": PAS63100CrossWalk,
        "PAS63100Mapping": PAS63100Mapping,
        "build_augmentation_plan": build_augmentation_plan,
        "run_ul_9540a_audit": run_ul_9540a_audit,
        "build_pas_63100_crosswalk": build_pas_63100_crosswalk,
    }


_COMMERCIAL_NAMES = frozenset({
    "AugmentationPlan", "AugmentationEvent", "CapacityRetentionPoint",
    "UL9540AAudit", "UL9540AFinding", "PAS63100CrossWalk", "PAS63100Mapping",
    "build_augmentation_plan", "run_ul_9540a_audit", "build_pas_63100_crosswalk",
})


def __getattr__(name):  # pragma: no cover - trivial lazy re-export
    # Only dispatch into utils.tdd.bess_commercial for *known* commercial
    # export names.  Unknown names raise AttributeError immediately so
    # Python's normal module-loader / dunder probes (__path__, __spec__,
    # __all__, …) never trigger the downstream import, avoiding a circular
    # import during utils.tdd package initialisation.
    if name in _COMMERCIAL_NAMES:
        exports = _commercial_exports()
        if name in exports:
            return exports[name]
    raise AttributeError(f"module 'utils.bess_thermal' has no attribute {name!r}")

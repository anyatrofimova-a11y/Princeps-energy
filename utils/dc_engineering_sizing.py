"""
DC Engineering Sizing — shared engineering-grade sizing helpers.

Canonical transformer / UPS / generator / switchgear sizing for data centres.
All other DC planning / design modules (``dc_planner``, ``dc_design_engine``,
``dc_hyperscaler_connection``, ``document_automation``) should defer to the
functions in this module instead of repeating the math inline.

Standards referenced
--------------------
- Uptime Institute "Tier Standard: Topology" (Tiers I–IV, concurrent maintainability,
  fault tolerance, 12–72 h onsite fuel).
- IEEE 241 "Recommended Practice for Electric Power Systems in Commercial
  Buildings" (transformer sizing, redundancy, diversity).
- IEEE 3006 "Recommended Practice for Evaluating Data Center Electrical
  Distribution Reliability".
- BS 7671:2018 + A2 "IET Wiring Regulations" (UK cable / switchgear /
  earthing).
- EN 50600-2-2:2019 "Information technology — Data centre facilities and
  infrastructures — Part 2-2: Power distribution" (availability classes 1–4).
- BS EN ISO 8528 "Reciprocating internal combustion engine driven alternating
  current generating sets" (genset sizing, classes G1–G4, prime vs. standby).
- Engineering Recommendation G99 (DNO connection of generation >16 A / phase).
- IEC 62040-3 "Uninterruptible power systems (UPS) — Method of specifying
  performance and test requirements".

Bug this module fixes
---------------------
The legacy sizing in ``dc_planner.plan_facility`` and
``dc_design_engine.power_density_design`` computed the facility's *total*
transformer capacity in MVA and then divided by a 2.5 MVA unit rating —
producing 32 "transformers" at the aggregate rating (e.g. 32× 78.7 MVA for a
50 MW Tier 3 N+1 design). That was nonsense on two fronts:

1. 2.5 MVA is a *rack-packaged / outdoor pad* unit — far too small for a
   primary 33/11 kV step-down on a hyperscale site, where 2-4 units in the
   20-80 MVA range per unit is industry practice.
2. The UI then displayed ``{count}× {aggregate_mva}``, presenting the
   facility-wide aggregate as the per-unit rating — a 50× over-statement of
   installed transformer capacity.

The same class of bug existed for gensets (32 units for 65 MW) and UPS
modules. This module sizes each component to realistic unit ratings that
match UK 2024–2026 hyperscale practice (e.g. Kao Data, Virtus, Ada, EdgeCore).
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Redundancy semantics
# ---------------------------------------------------------------------------

# Uptime Institute + EN 50600-2-2 definitions:
#   N       — base capacity, no redundancy (Tier I / Class 1).
#   N+1     — one spare unit (Tier II / III, Class 2 / 3).
#   2N      — two independent, concurrent trains (Tier IV / Class 4).
#   2N+1    — two trains plus a common spare.
#
# IMPORTANT: the "factor" is a CAPACITY multiplier for *sum-of-installed* kW,
# not a sizing factor per unit. Per-unit sizing is done separately so that the
# loss of one unit still leaves ≥ N units online.

_REDUNDANCY_EXTRA_UNITS = {"N": 0, "N+1": 1, "2N": 0, "2N+1": 1}  # spare count
_REDUNDANCY_TRAINS = {"N": 1, "N+1": 1, "2N": 2, "2N+1": 2}       # parallel trains


def _normalise_redundancy(scheme: str) -> str:
    s = (scheme or "N+1").upper().replace(" ", "")
    return s if s in _REDUNDANCY_EXTRA_UNITS else "N+1"


def redundancy_capacity_factor(scheme: str) -> float:
    """Installed-capacity multiplier for a given redundancy scheme.

    This is what downstream CAPEX / load-flow code historically wanted: the
    ratio of installed capacity to the N baseline. Kept for backward
    compatibility only — new code should use :func:`size_component`.

    ``N``    → 1.00
    ``N+1``  → 1 + 1/N (asymptotic 1.0 for large N; clamped to 1.15 for the
               rule-of-thumb planning number used by the solar/civil code).
    ``2N``   → 2.00
    ``2N+1`` → 2 + 1/N (clamped to 2.15).
    """
    s = _normalise_redundancy(scheme)
    return {"N": 1.0, "N+1": 1.15, "2N": 2.0, "2N+1": 2.15}[s]


# ---------------------------------------------------------------------------
# Transformer sizing  (IEEE 241 §10, BS 7671 Ch 43, EN 50600-2-2 §6)
# ---------------------------------------------------------------------------

# Typical primary step-down transformer unit ratings used at UK DC sites.
# Picked large enough that a 50 MW site lands 2-4 units, not 32.
#   - 11 kV / 415 V secondary distribution: 2.5 MVA (small / package).
#   - 33 kV / 11 kV primary:                 20 MVA.
#   - 132 kV / 33 kV bulk supply:            60 MVA  (GSP-scale).
# See IEEE C57.12 + NGET TS 2.01 for standard ratings.
_PRIMARY_TX_MVA_BY_LOAD = [
    # (facility_mw_threshold, unit_mva)
    (5,   2.5),   # edge: 11 kV package substations
    (20,  5.0),   # small: 11 kV / 415 V site substation
    (60,  20.0),  # mid / colo: 33 / 11 kV primary
    (200, 40.0),  # hyperscale: 33 / 11 kV primary pair
    (1e9, 60.0),  # giga: 132 / 33 kV GSP connection
]


def recommended_primary_mva(facility_mw: float) -> float:
    """Return a sensible primary transformer unit rating for the site size."""
    for threshold, mva in _PRIMARY_TX_MVA_BY_LOAD:
        if facility_mw <= threshold:
            return mva
    return 60.0


def size_transformers(
    facility_kw: float,
    redundancy: str = "N+1",
    power_factor: float = 0.95,
    unit_mva: float | None = None,
) -> dict[str, Any]:
    """Size primary step-down transformers for a DC facility.

    Parameters
    ----------
    facility_kw : float
        Total facility load (IT × PUE) in kW. Includes cooling and losses.
    redundancy : str
        ``N``, ``N+1``, ``2N``, or ``2N+1``. The returned count always allows
        the loss of one unit while still meeting full facility demand.
    power_factor : float
        Assumed load power factor (UK DC typical: 0.95 @ UPS output, 0.90 @
        facility boundary — 0.95 used as default for sizing).
    unit_mva : float | None
        Override the per-unit MVA rating; otherwise picked from
        :func:`recommended_primary_mva`.

    Returns
    -------
    dict
        ``unit_mva`` — nameplate rating of each transformer.
        ``count`` — total number of transformers installed (N + spares / trains).
        ``n_base`` — minimum number needed to carry full load without spare.
        ``load_mva`` — apparent power required at the facility boundary.
        ``installed_mva`` — count × unit_mva (headroom over load_mva).
        ``utilisation_pct`` — load_mva / installed_mva × 100.
        ``voltage_primary_kv`` / ``voltage_secondary_kv`` — UK hierarchy.

    Standards
    ---------
    Sizing rule: IEEE 241 §10.3 (transformer capacity ≥ connected load / PF,
    with margin for harmonics and future growth). Redundancy rule: Uptime
    Tier Standard — Tier III/IV requires concurrent maintainability, which
    is satisfied when ``count - n_base ≥ 1`` and each path is isolatable.
    """
    scheme = _normalise_redundancy(redundancy)
    facility_mw = max(facility_kw, 1.0) / 1000.0

    # Apparent power at facility boundary
    load_mva = facility_kw / 1000.0 / max(power_factor, 0.5)

    unit = float(unit_mva) if unit_mva else recommended_primary_mva(facility_mw)
    unit = max(unit, 0.5)  # don't divide by zero

    # Minimum units needed to carry full load
    n_base = max(1, math.ceil(load_mva / unit))

    trains = _REDUNDANCY_TRAINS[scheme]
    spare = _REDUNDANCY_EXTRA_UNITS[scheme]

    if scheme in ("2N", "2N+1"):
        # Two independent, fully-rated trains. Each train must carry full load.
        count = n_base * trains + spare
    else:
        # Single train with optional spare.
        count = n_base + spare

    installed_mva = count * unit
    util = (load_mva / installed_mva) * 100.0 if installed_mva else 0.0

    # UK voltage hierarchy
    if facility_mw < 5:
        v_primary_kv, v_secondary_kv = 11, 0.415
    elif facility_mw < 60:
        v_primary_kv, v_secondary_kv = 33, 11
    else:
        v_primary_kv, v_secondary_kv = 132, 33

    return {
        "count": count,
        "n_base": n_base,
        "trains": trains,
        "spares": spare,
        "unit_mva": round(unit, 2),
        "load_mva": round(load_mva, 2),
        "installed_mva": round(installed_mva, 2),
        "utilisation_pct": round(util, 1),
        "redundancy": scheme,
        "power_factor": power_factor,
        "voltage_primary_kv": v_primary_kv,
        "voltage_secondary_kv": v_secondary_kv,
        "standards": [
            "IEEE 241 §10.3 (transformer sizing)",
            "BS 7671 Chapter 43 (protection against overcurrent)",
            "EN 50600-2-2 §6 (power distribution availability)",
            "Uptime Institute Tier Standard: Topology",
        ],
    }


# ---------------------------------------------------------------------------
# Generator sizing  (BS EN ISO 8528, Uptime Tier, G99)
# ---------------------------------------------------------------------------

# Typical DC backup genset unit ratings. Real sites use a handful of large
# Perkins / MTU / Caterpillar 16V-class units, not dozens of 2 MW package sets.
_GENSET_KW_BY_LOAD = [
    (5,    1_500),   # edge: 1.5 MW packaged (CAT 3516)
    (20,   2_000),   # small: 2 MW packaged (MTU 16V2000)
    (80,   2_500),   # mid / colo: 2.5 MW (MTU 20V4000)
    (200,  3_000),   # hyperscale: 3 MW (CAT 3516C HD)
    (1e9,  3_250),   # giga: 3.25 MW (Rolls-Royce mtu 20V4000)
]


def recommended_genset_kw(facility_mw: float) -> int:
    for threshold, kw in _GENSET_KW_BY_LOAD:
        if facility_mw <= threshold:
            return kw
    return 3_250


def size_generators(
    facility_kw: float,
    redundancy: str = "N+1",
    tier: int = 3,
    headroom_pct: float = 10.0,
    unit_kw: int | None = None,
    fuel_hours: int | None = None,
) -> dict[str, Any]:
    """Size standby diesel generators for full facility cover.

    Each generator is sized for "prime running" at >= facility_kw × (1 + headroom).
    N+1 supplies one spare so the loss of any single genset still covers full
    facility load. Tier III requires ≥12 h onsite fuel per Uptime Institute;
    ≥72 h is the Uptime "target" (matches UK noise / RDE /ERA regs for test
    hours). Tier IV is 2N — two independent fully rated trains.

    Standards
    ---------
    - BS EN ISO 8528-1 (reciprocating genset rating definitions: COP / PRP /
      LTP / ESP; DC standby uses PRP / LTP class).
    - Uptime Institute Tier Standard: Topology (fuel onsite: ≥12 h Tier III,
      per industry practice 48–72 h; Tier IV requires 2N).
    - Engineering Recommendation G99 §A8 (any genset capable of export or
      parallel operation needs G99 Relevant Electrical Standards testing).
    """
    scheme = _normalise_redundancy(redundancy)
    facility_mw = max(facility_kw, 1.0) / 1000.0
    required_kw = facility_kw * (1.0 + headroom_pct / 100.0)

    unit = int(unit_kw) if unit_kw else recommended_genset_kw(facility_mw)
    unit = max(unit, 500)

    n_base = max(1, math.ceil(required_kw / unit))

    trains = _REDUNDANCY_TRAINS[scheme]
    spare = _REDUNDANCY_EXTRA_UNITS[scheme]

    if scheme in ("2N", "2N+1"):
        count = n_base * trains + spare
    else:
        count = n_base + spare

    installed_kw = count * unit
    util = (required_kw / installed_kw) * 100.0 if installed_kw else 0.0

    # Tier fuel-hour defaults
    if fuel_hours is None:
        fuel_hours = {1: 8, 2: 12, 3: 48, 4: 72}.get(tier, 48)

    # Diesel consumption ≈ 0.21 L/kWh @ prime running (MTU/CAT typical)
    fuel_litres = installed_kw * fuel_hours * 0.21

    return {
        "count": count,
        "n_base": n_base,
        "trains": trains,
        "spares": spare,
        "unit_kw": unit,
        "unit_mw": round(unit / 1000, 2),
        "required_kw": round(required_kw),
        "installed_kw": installed_kw,
        "installed_mw": round(installed_kw / 1000, 2),
        "utilisation_pct": round(util, 1),
        "redundancy": scheme,
        "headroom_pct": headroom_pct,
        "tier_fuel_hours": fuel_hours,
        "fuel_litres_onsite": round(fuel_litres),
        "black_start_capable": True,
        "standards": [
            "BS EN ISO 8528-1 (genset rating: PRP/LTP)",
            "Uptime Institute Tier Standard: onsite fuel ≥12 h Tier III",
            "Engineering Recommendation G99 §A8",
        ],
    }


# ---------------------------------------------------------------------------
# UPS sizing  (IEC 62040-3, IEEE 446, EN 50600-2-2)
# ---------------------------------------------------------------------------

# Typical modular UPS module ratings (Schneider Galaxy VL / Eaton 93PM /
# Vertiv Liebert). Large DC sites use 250–500 kW modules.
def recommended_ups_module_kw(facility_mw: float) -> int:
    if facility_mw < 2:
        return 100
    if facility_mw < 10:
        return 250
    if facility_mw < 100:
        return 500
    return 625  # e.g. Schneider Galaxy VXL


def size_ups(
    it_load_kw: float,
    redundancy: str = "N+1",
    module_kw: int | None = None,
    autonomy_minutes: int = 5,
    cover_cooling: bool = False,
    cooling_kw: float = 0.0,
) -> dict[str, Any]:
    """Size UPS modules to cover IT load (optionally including critical cooling).

    DC industry practice is to UPS-back the IT load only; mechanical cooling
    rides through on generators. Some hyperscale / Tier IV designs back
    critical cooling pumps and CRAH fans (not chillers) — toggle with
    ``cover_cooling``.

    Autonomy is the ride-through time at full load, nominally 5–10 min for
    Tier III to bridge genset start (IEC 62040-3, EN 50600-2-2 §6.4.2).
    """
    scheme = _normalise_redundancy(redundancy)
    facility_mw = max(it_load_kw, 1.0) / 1000.0

    protected_kw = it_load_kw + (cooling_kw if cover_cooling else 0.0)
    module = int(module_kw) if module_kw else recommended_ups_module_kw(facility_mw)
    module = max(module, 25)

    n_base = max(1, math.ceil(protected_kw / module))

    trains = _REDUNDANCY_TRAINS[scheme]
    spare = _REDUNDANCY_EXTRA_UNITS[scheme]

    if scheme in ("2N", "2N+1"):
        count = n_base * trains + spare
    else:
        count = n_base + spare

    installed_kw = count * module
    util = (protected_kw / installed_kw) * 100.0 if installed_kw else 0.0

    # Battery energy at full load
    battery_kwh = installed_kw * autonomy_minutes / 60.0

    return {
        "count": count,
        "n_base": n_base,
        "trains": trains,
        "spares": spare,
        "module_kw": module,
        "protected_kw": round(protected_kw),
        "installed_kw": installed_kw,
        "installed_mw": round(installed_kw / 1000, 2),
        "utilisation_pct": round(util, 1),
        "redundancy": scheme,
        "autonomy_minutes": autonomy_minutes,
        "battery_kwh": round(battery_kwh),
        "covers_cooling": cover_cooling,
        "standards": [
            "IEC 62040-3 (UPS performance classes: VFI-SS-111)",
            "IEEE 446 §4 (emergency and standby power for industrial and "
            "commercial applications)",
            "EN 50600-2-2 §6.4 (UPS autonomy for Classes 1–4)",
        ],
    }


# ---------------------------------------------------------------------------
# Switchgear panel count  (BS EN 61439, BS 7671)
# ---------------------------------------------------------------------------

def size_switchgear(
    transformer_count: int,
    genset_count: int,
    redundancy: str = "N+1",
    halls: int = 1,
) -> dict[str, Any]:
    """Estimate main switchgear panel count.

    Each TX feeds an incoming MV/LV panel. Each hall has an A + B distribution
    board. Each generator connects via a synchronising panel. Dual-bus sites
    add a bus-tie panel.

    Standards: BS EN 61439 (LV switchgear), BS EN 62271 (MV switchgear),
    BS 7671 §530 (selection and erection).
    """
    scheme = _normalise_redundancy(redundancy)
    is_dual_bus = scheme in ("2N", "2N+1")

    incomers = transformer_count
    hall_boards = halls * (2 if is_dual_bus else 1)
    gen_sync = genset_count
    bus_ties = 2 if is_dual_bus else 1
    maint_bypass = max(1, halls // 2)  # shared maintenance bypass panels

    total = incomers + hall_boards + gen_sync + bus_ties + maint_bypass

    return {
        "main_panels": total,
        "breakdown": {
            "transformer_incomers": incomers,
            "hall_distribution_boards": hall_boards,
            "generator_sync_panels": gen_sync,
            "bus_tie_panels": bus_ties,
            "maintenance_bypass_panels": maint_bypass,
        },
        "redundancy": scheme,
        "standards": [
            "BS EN 61439 (low-voltage switchgear and controlgear assemblies)",
            "BS EN 62271 (high-voltage switchgear)",
            "BS 7671 §530 (selection and erection of switchgear)",
        ],
    }


# ---------------------------------------------------------------------------
# PUE consistency check
# ---------------------------------------------------------------------------

def check_pue_consistency(
    it_load_kw: float,
    cooling_kw: float,
    ups_loss_kw: float,
    distribution_loss_kw: float,
    stated_pue: float,
    tol: float = 0.05,
) -> dict[str, Any]:
    """Return whether the PUE derived from the breakdown matches the stated PUE.

    PUE = Total Facility Power / IT Load Power (The Green Grid).
    """
    total = it_load_kw + cooling_kw + ups_loss_kw + distribution_loss_kw
    derived = total / max(it_load_kw, 1.0)
    return {
        "derived_pue": round(derived, 3),
        "stated_pue": round(stated_pue, 3),
        "delta": round(derived - stated_pue, 3),
        "consistent": abs(derived - stated_pue) <= tol,
        "it_load_kw": round(it_load_kw),
        "total_facility_kw": round(total),
    }


# ---------------------------------------------------------------------------
# Full engineering design bundle
# ---------------------------------------------------------------------------

def engineering_design(
    it_load_kw: float,
    pue: float = 1.3,
    redundancy: str = "N+1",
    tier: int = 3,
    halls: int = 1,
    power_factor: float = 0.95,
) -> dict[str, Any]:
    """One-shot engineering sizing for a DC facility.

    Returns properly-redundant counts for all major electrical assets. Use
    this instead of the legacy per-module calculations in ``dc_planner`` /
    ``dc_design_engine`` — those are now thin wrappers around this function.
    """
    scheme = _normalise_redundancy(redundancy)
    facility_kw = it_load_kw * pue

    tx = size_transformers(facility_kw, redundancy=scheme, power_factor=power_factor)
    ups_cooling = facility_kw - it_load_kw
    ups = size_ups(it_load_kw, redundancy=scheme)
    gen = size_generators(facility_kw, redundancy=scheme, tier=tier)
    sw = size_switchgear(tx["count"], gen["count"], redundancy=scheme, halls=halls)

    return {
        "it_load_kw": round(it_load_kw),
        "facility_kw": round(facility_kw),
        "pue": pue,
        "redundancy": scheme,
        "tier": tier,
        "transformers": tx,
        "ups": ups,
        "generators": gen,
        "switchgear": sw,
    }

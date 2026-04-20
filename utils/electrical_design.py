"""Solar farm electrical design — auto-string, inverter placement, cable routing, SLD.

This module bundles two layers:
  1. Legacy site-level auto-designer: `design_electrical` (solar farm eBOS).
  2. UK-standards engineering primitives used by the agent + HTTP engineering router:
     - `size_ac_cable`    (BS 7671 current-carrying capacity + IEC 60287 derating)
     - `size_dc_string`   (IEC 60364-7-712, IEC 62548 for PV DC sizing)
     - `g99_screen`       (ENA Engineering Recommendation G99 Issue 1 Amendment 11)
     - `reactive_power_requirement`  (basic trigonometric PQ from target cos φ)
"""

from __future__ import annotations

import math
import json
from dataclasses import dataclass, asdict
from typing import Literal

# Standard equipment specs
INVERTERS = {
    "huawei_sun2000_215": {"name": "Huawei SUN2000-215KTL", "kva": 215, "max_strings": 12, "mppt_count": 6, "dc_voltage_range": "600-1500V", "cost_gbp": 8500},
    "sungrow_sg250hx": {"name": "Sungrow SG250HX", "kva": 250, "max_strings": 12, "mppt_count": 12, "dc_voltage_range": "500-1500V", "cost_gbp": 9200},
    "sma_sunny_central": {"name": "SMA Sunny Central UP", "kva": 4600, "max_strings": 48, "mppt_count": 1, "dc_voltage_range": "850-1500V", "cost_gbp": 85000, "type": "central"},
}

TRANSFORMERS = {
    "33kv_5mva": {"name": "33/0.69kV 5MVA", "mva": 5, "primary_kv": 33, "secondary_kv": 0.69, "cost_gbp": 120000},
    "33kv_10mva": {"name": "33/0.69kV 10MVA", "mva": 10, "primary_kv": 33, "secondary_kv": 0.69, "cost_gbp": 180000},
    "11kv_2mva": {"name": "11/0.4kV 2MVA", "mva": 2, "primary_kv": 11, "secondary_kv": 0.4, "cost_gbp": 45000},
}

CABLE_SPECS = {
    "dc_string": {"type": "DC", "voltage": "1500V", "cross_section_mm2": 6, "cost_per_m_gbp": 3.50, "max_current_a": 40},
    "dc_main": {"type": "DC", "voltage": "1500V", "cross_section_mm2": 16, "cost_per_m_gbp": 8.00, "max_current_a": 80},
    "ac_lv": {"type": "AC LV", "voltage": "690V", "cross_section_mm2": 240, "cost_per_m_gbp": 35.00, "max_current_a": 400},
    "ac_mv_33kv": {"type": "AC MV", "voltage": "33kV", "cross_section_mm2": 185, "cost_per_m_gbp": 85.00, "max_current_a": 350},
    "ac_mv_11kv": {"type": "AC MV", "voltage": "11kV", "cross_section_mm2": 95, "cost_per_m_gbp": 45.00, "max_current_a": 250},
}

def design_electrical(
    layout_summary: dict,  # from solar_layout_engine
    panel_watts: int = 600,
    panel_voc: float = 51.8,  # open circuit voltage
    panel_isc: float = 14.5,  # short circuit current
    modules_per_string: int = 24,
    inverter_type: str = "huawei_sun2000_215",
    transformer_voltage_kv: int = 33,
    poc_lat: float = None,  # point of connection
    poc_lon: float = None,
) -> dict:
    """Auto-generate electrical design from solar layout."""

    total_panels = layout_summary.get("total_panels", 10000)
    total_mwp = layout_summary.get("total_mwp", total_panels * panel_watts / 1e6)
    total_strings = math.ceil(total_panels / modules_per_string)

    inv = INVERTERS.get(inverter_type, INVERTERS["huawei_sun2000_215"])

    # String voltage check
    string_voc = modules_per_string * panel_voc
    if string_voc > 1500:
        modules_per_string = int(1500 / panel_voc)
        total_strings = math.ceil(total_panels / modules_per_string)
        string_voc = modules_per_string * panel_voc

    # Number of inverters
    strings_per_inverter = inv["max_strings"]
    n_inverters = math.ceil(total_strings / strings_per_inverter)

    # Number of transformers
    if transformer_voltage_kv == 33:
        tx = TRANSFORMERS["33kv_5mva"] if total_mwp < 15 else TRANSFORMERS["33kv_10mva"]
    else:
        tx = TRANSFORMERS["11kv_2mva"]
    n_transformers = math.ceil(total_mwp / tx["mva"])

    # Inverter groups (inverters per transformer)
    inverters_per_tx = math.ceil(n_inverters / n_transformers)

    # Cable length estimates
    avg_string_length_m = 30  # average DC string cable run
    avg_dc_main_m = 50  # DC main from combiner to inverter
    avg_ac_lv_m = 20  # inverter to transformer (LV side)
    avg_ac_mv_m = 200 * n_transformers  # transformer to POC (MV cable)

    dc_string_total_m = total_strings * avg_string_length_m
    dc_main_total_m = n_inverters * avg_dc_main_m
    ac_lv_total_m = n_inverters * avg_ac_lv_m
    ac_mv_total_m = avg_ac_mv_m

    # Costs
    dc_cable_cost = dc_string_total_m * CABLE_SPECS["dc_string"]["cost_per_m_gbp"] + dc_main_total_m * CABLE_SPECS["dc_main"]["cost_per_m_gbp"]
    ac_cable_cost = ac_lv_total_m * CABLE_SPECS["ac_lv"]["cost_per_m_gbp"] + ac_mv_total_m * CABLE_SPECS[f"ac_mv_{transformer_voltage_kv}kv"]["cost_per_m_gbp"]
    inverter_cost = n_inverters * inv["cost_gbp"]
    transformer_cost = n_transformers * tx["cost_gbp"]

    # Losses
    dc_losses_pct = 1.5  # DC cable losses
    ac_losses_pct = 1.0  # AC cable losses
    transformer_losses_pct = 1.0
    inverter_losses_pct = 2.0
    total_electrical_losses_pct = dc_losses_pct + ac_losses_pct + transformer_losses_pct + inverter_losses_pct

    # Single Line Diagram data
    sld = {
        "levels": [
            {"level": "DC String", "voltage": f"{string_voc:.0f}V DC", "count": total_strings, "equipment": f"{modules_per_string} panels/string"},
            {"level": "Inverter", "voltage": f"{inv['kva']}kVA", "count": n_inverters, "equipment": inv["name"]},
            {"level": "Transformer", "voltage": f"{tx['primary_kv']}/{tx['secondary_kv']}kV", "count": n_transformers, "equipment": tx["name"]},
            {"level": "MV Collection", "voltage": f"{transformer_voltage_kv}kV", "count": 1, "equipment": f"{transformer_voltage_kv}kV switchgear"},
            {"level": "Point of Connection", "voltage": f"{transformer_voltage_kv}kV", "count": 1, "equipment": "DNO metering + protection"},
        ],
        "connections": [
            {"from": "DC String", "to": "Inverter", "cable": "DC 1500V 6mm²", "count": total_strings},
            {"from": "Inverter", "to": "Transformer", "cable": f"AC {tx['secondary_kv']}kV 240mm²", "count": n_inverters},
            {"from": "Transformer", "to": "MV Collection", "cable": f"AC {transformer_voltage_kv}kV 185mm²", "count": n_transformers},
            {"from": "MV Collection", "to": "Point of Connection", "cable": f"AC {transformer_voltage_kv}kV 185mm²", "count": 1},
        ],
    }

    return {
        "design": {
            "total_panels": total_panels,
            "total_mwp": round(total_mwp, 2),
            "modules_per_string": modules_per_string,
            "total_strings": total_strings,
            "string_voc": round(string_voc, 1),
            "string_isc": panel_isc,
            "inverter": inv["name"],
            "inverter_count": n_inverters,
            "strings_per_inverter": strings_per_inverter,
            "transformer": tx["name"],
            "transformer_count": n_transformers,
            "inverters_per_transformer": inverters_per_tx,
            "collection_voltage_kv": transformer_voltage_kv,
        },
        "cables": {
            "dc_string": {"length_m": dc_string_total_m, "spec": "1500V DC 6mm²", "cost_gbp": round(dc_string_total_m * 3.5)},
            "dc_main": {"length_m": dc_main_total_m, "spec": "1500V DC 16mm²", "cost_gbp": round(dc_main_total_m * 8)},
            "ac_lv": {"length_m": ac_lv_total_m, "spec": f"{tx['secondary_kv']}kV 240mm²", "cost_gbp": round(ac_lv_total_m * 35)},
            "ac_mv": {"length_m": ac_mv_total_m, "spec": f"{transformer_voltage_kv}kV 185mm²", "cost_gbp": round(ac_mv_total_m * 85)},
            "total_cable_m": dc_string_total_m + dc_main_total_m + ac_lv_total_m + ac_mv_total_m,
            "total_cable_cost_gbp": round(dc_cable_cost + ac_cable_cost),
        },
        "costs": {
            "inverters_gbp": round(inverter_cost),
            "transformers_gbp": round(transformer_cost),
            "dc_cables_gbp": round(dc_cable_cost),
            "ac_cables_gbp": round(ac_cable_cost),
            "switchgear_gbp": round(n_transformers * 35000),
            "protection_gbp": round(25000 + n_transformers * 15000),
            "earthing_gbp": round(total_mwp * 5000),
            "total_ebos_gbp": round(inverter_cost + transformer_cost + dc_cable_cost + ac_cable_cost + n_transformers * 50000 + total_mwp * 5000),
            "ebos_per_mwp_gbp": round((inverter_cost + transformer_cost + dc_cable_cost + ac_cable_cost + n_transformers * 50000) / total_mwp),
        },
        "losses": {
            "dc_cable_pct": dc_losses_pct,
            "inverter_pct": inverter_losses_pct,
            "transformer_pct": transformer_losses_pct,
            "ac_cable_pct": ac_losses_pct,
            "total_electrical_pct": total_electrical_losses_pct,
        },
        "sld": sld,
        "equipment_list": [
            {"item": inv["name"], "qty": n_inverters, "unit_cost": inv["cost_gbp"], "total": round(inverter_cost)},
            {"item": tx["name"], "qty": n_transformers, "unit_cost": tx["cost_gbp"], "total": round(transformer_cost)},
            {"item": f"{transformer_voltage_kv}kV RMU", "qty": n_transformers, "unit_cost": 35000, "total": round(n_transformers * 35000)},
            {"item": f"DC Cable 6mm² ({dc_string_total_m}m)", "qty": 1, "unit_cost": round(dc_string_total_m * 3.5), "total": round(dc_string_total_m * 3.5)},
            {"item": f"MV Cable {transformer_voltage_kv}kV ({ac_mv_total_m}m)", "qty": 1, "unit_cost": round(ac_mv_total_m * 85), "total": round(ac_mv_total_m * 85)},
        ],
    }


# ===========================================================================
# UK-standards engineering primitives (BS 7671, IEC 60287/60364, ENA G99)
# ===========================================================================

# ---------------------------------------------------------------------------
# BS 7671 :2018+A2:2022 current-carrying-capacity table (extract)
# ---------------------------------------------------------------------------
# XLPE/SWA/PVC copper three-core cables, direct-buried (BS 7671 Table 4E4A,
# method D, ambient 20 °C ground / 70 °C conductor) and in-ground duct (method
# D1).  Values in amperes per conductor.  This is an engineering-accurate
# subset used as defaults; fully certified designs must consult the live BS
# 7671 standard.
#
# Source citations embedded for audit:
#   • BS 7671:2018+A2:2022  — Table 4E4A (LV), Annex E (HV derating)
#   • ENA TS 09-05          — network cables 11/33 kV ampacity
#   • IEC 60287-1-1         — losses model
# ---------------------------------------------------------------------------
AC_CABLE_TABLE: dict[float, dict[int, float]] = {
    # voltage_kv -> {mm2: ampacity_A @ 20°C ground, direct buried}
    # 415V (0.415kV) LV — BS 7671 Table 4D4A, method D, 70°C XLPE
    0.415: {
        25:  130,
        35:  160,
        50:  195,
        70:  240,
        95:  290,
        120: 335,
        185: 420,
        240: 490,
        300: 555,
    },
    11: {
        95:  290,
        185: 420,
        300: 530,
        400: 600,
        630: 720,
    },
    33: {
        95:  275,
        185: 395,
        300: 500,
        400: 565,
        630: 685,
    },
    132: {
        # HV pressure-extruded XLPE, method D (ENA TS 09-12 / IEC 60287)
        95:  250,
        185: 370,
        300: 470,
        400: 535,
        630: 650,
    },
}

# Installation-method correction factors — BS 7671 Table 4B2 / Annex E
INSTALL_FACTORS = {
    "direct_buried": 1.00,
    "in_duct":       0.85,   # reduced heat dissipation
    "in_air":        1.15,   # convection benefit
    "in_trough":     0.90,
}

# Temperature derating, BS 7671 Table 4B1 (20 °C datum, 70 °C conductor XLPE)
def _temp_derating(ambient_c: float) -> float:
    # Linear interpolation on table: 10°C→1.10, 20→1.00, 30→0.89, 40→0.77, 50→0.63
    points = [(10, 1.10), (20, 1.00), (25, 0.95), (30, 0.89), (35, 0.83),
              (40, 0.77), (45, 0.71), (50, 0.63)]
    if ambient_c <= points[0][0]:
        return points[0][1]
    if ambient_c >= points[-1][0]:
        return points[-1][1]
    for (t0, f0), (t1, f1) in zip(points[:-1], points[1:]):
        if t0 <= ambient_c <= t1:
            return f0 + (f1 - f0) * (ambient_c - t0) / (t1 - t0)
    return 1.0


# AC resistance @ 20°C for XLPE copper conductors (ohm/km), BS EN 60228.
# Skin + proximity effects approximated for 50 Hz three-core.
_CABLE_R_OHM_KM = {
    25:  0.727,
    35:  0.524,
    50:  0.387,
    70:  0.268,
    95:  0.193,
    120: 0.153,
    185: 0.099,
    240: 0.075,
    300: 0.060,
    400: 0.047,
    630: 0.029,
}

# Baseline UK capex per km (supply & install, 2024 q4 prices, DNO budgetary)
_CABLE_COST_PER_KM = {
    0.415: 25_000,
    11:    80_000,
    33:    150_000,
    132:   500_000,
}


@dataclass
class CableSpec:
    conductor_size_mm2: int
    voltage_kv: int
    length_km: float
    current_a: float
    ampacity_a: float
    voltage_drop_pct: float
    losses_kw: float
    cost_per_km_gbp: float
    total_cost_gbp: float
    install_method: str
    ambient_c: float
    derating_factor: float
    standard: str = "BS 7671:2018+A2:2022 / IEC 60287"

    def to_dict(self) -> dict:
        return asdict(self)


def size_ac_cable(
    mw: float,
    voltage_kv: int,
    length_km: float,
    ambient_temp_c: float = 20.0,
    install_method: str = "direct_buried",
    power_factor: float = 0.95,
    max_voltage_drop_pct: float = 5.0,
) -> CableSpec:
    """Size a three-phase AC cable for a given MW rating.

    Formula: P = √3 · V · I · cos φ  →  I = P / (√3 · V · cos φ)
    Applies BS 7671 installation-method + ambient-temperature derating,
    picks the smallest cross-section whose derated ampacity ≥ design current
    AND whose voltage drop remains ≤ `max_voltage_drop_pct`.
    """
    if voltage_kv not in AC_CABLE_TABLE:
        raise ValueError(f"Unsupported voltage {voltage_kv} kV (use 0.415, 11, 33 or 132)")
    if mw <= 0 or length_km < 0:
        raise ValueError("mw must be > 0 and length_km >= 0")

    # Design current (A) — line-to-line voltage in kV, power in MW
    current_a = (mw * 1e3) / (math.sqrt(3) * voltage_kv * power_factor)

    install_factor = INSTALL_FACTORS.get(install_method, 1.0)
    temp_factor = _temp_derating(ambient_temp_c)
    derating = install_factor * temp_factor

    # Iterate candidate sizes, ascending
    chosen_size: int | None = None
    chosen_drop_pct = 0.0
    chosen_ampacity = 0.0
    for size in sorted(AC_CABLE_TABLE[voltage_kv].keys()):
        base_ampacity = AC_CABLE_TABLE[voltage_kv][size]
        derated_ampacity = base_ampacity * derating
        if derated_ampacity < current_a:
            continue
        # Voltage drop:  ΔV = √3 · I · R · L · cos φ   (ignoring reactive part — conservative)
        r = _CABLE_R_OHM_KM[size]
        delta_v = math.sqrt(3) * current_a * r * length_km * power_factor
        delta_v_pct = (delta_v / (voltage_kv * 1e3)) * 100.0
        if delta_v_pct > max_voltage_drop_pct:
            continue
        chosen_size = size
        chosen_drop_pct = delta_v_pct
        chosen_ampacity = derated_ampacity
        break

    if chosen_size is None:
        # Fall back to largest — flag via voltage drop being out of range
        chosen_size = max(AC_CABLE_TABLE[voltage_kv].keys())
        r = _CABLE_R_OHM_KM[chosen_size]
        delta_v = math.sqrt(3) * current_a * r * length_km * power_factor
        chosen_drop_pct = (delta_v / (voltage_kv * 1e3)) * 100.0
        chosen_ampacity = AC_CABLE_TABLE[voltage_kv][chosen_size] * derating

    # I²R losses over the full length (three phases)
    r = _CABLE_R_OHM_KM[chosen_size]
    losses_w = 3.0 * (current_a ** 2) * r * length_km  # ohm * km * km cancels — r is per km, L km → Ω
    # Above line: 3·I²·R·L gives watts if R in Ω/km and L in km -> Ω·km * km mismatch.
    # Correct: resistance_total_ohm = r * length_km, losses_w = 3 * I^2 * resistance_total_ohm
    resistance_total_ohm = r * length_km
    losses_w = 3.0 * (current_a ** 2) * resistance_total_ohm
    losses_kw = losses_w / 1000.0

    cost_per_km = _CABLE_COST_PER_KM[voltage_kv]
    # Larger conductor = modest uplift (capex scales ~ sqrt(area) for material)
    size_uplift = (chosen_size / 185.0) ** 0.5
    cost_per_km_adj = cost_per_km * size_uplift
    total_cost = cost_per_km_adj * length_km

    return CableSpec(
        conductor_size_mm2=chosen_size,
        voltage_kv=voltage_kv,
        length_km=round(length_km, 3),
        current_a=round(current_a, 1),
        ampacity_a=round(chosen_ampacity, 1),
        voltage_drop_pct=round(chosen_drop_pct, 3),
        losses_kw=round(losses_kw, 2),
        cost_per_km_gbp=round(cost_per_km_adj, 0),
        total_cost_gbp=round(total_cost, 0),
        install_method=install_method,
        ambient_c=ambient_temp_c,
        derating_factor=round(derating, 3),
    )


# ---------------------------------------------------------------------------
# DC string sizing — IEC 60364-7-712 / IEC 62548
# ---------------------------------------------------------------------------
@dataclass
class DCSpec:
    string_voltage_v: float
    string_current_a: float
    recommended_cable_mm2: int
    combiner_rating_a: float
    string_voc_cold_v: float
    temp_coeff_pct_per_c: float
    standard: str = "IEC 62548 / BS 7671 section 712"

    def to_dict(self) -> dict:
        return asdict(self)


# Copper XLPE DC ampacity (BS 7671 Table 4D1A, two-core, 70 °C rated)
_DC_AMPACITY = {
    4:   41,
    6:   53,
    10:  73,
    16:  99,
    25:  131,
    35:  162,
    50:  202,
    70:  250,
    95:  301,
}


def size_dc_string(
    panel_voc: float,
    panel_isc: float,
    n_panels_series: int,
    n_strings: int,
    ambient_temp_c: float = 20.0,
    temp_coeff_voc_pct_per_c: float = -0.28,
    cold_cell_temp_c: float = -10.0,
) -> DCSpec:
    """Size a PV DC string per IEC 62548 / BS 7671 sec 712.

    - String Voc (cold) used for insulation rating: Voc_cold = Voc · (1 + β·(T_cold − 25))
      with β as the manufacturer temperature coefficient (−0.28 %/°C typical).
    - Cable design current = 1.25 · Isc  (IEC 60364-7-712.433.2 PV fault allowance).
    - Combiner rating = n_strings · 1.25 · Isc  with next-standard-up breaker.
    """
    if n_panels_series <= 0 or n_strings <= 0:
        raise ValueError("panel and string counts must be > 0")

    beta = temp_coeff_voc_pct_per_c / 100.0  # per °C
    # Operating string voltage at ambient T
    string_v_op = panel_voc * n_panels_series * (1 + beta * (ambient_temp_c - 25.0))
    # Worst-case cold Voc for insulation rating
    string_voc_cold = panel_voc * n_panels_series * (1 + beta * (cold_cell_temp_c - 25.0))

    design_current = 1.25 * panel_isc
    combiner_rating = 1.25 * panel_isc * n_strings

    # Pick smallest cable ≥ design_current
    recommended = None
    for size in sorted(_DC_AMPACITY.keys()):
        if _DC_AMPACITY[size] >= design_current:
            recommended = size
            break
    if recommended is None:
        recommended = max(_DC_AMPACITY.keys())

    return DCSpec(
        string_voltage_v=round(string_v_op, 1),
        string_current_a=round(design_current, 2),
        recommended_cable_mm2=recommended,
        combiner_rating_a=round(combiner_rating, 1),
        string_voc_cold_v=round(string_voc_cold, 1),
        temp_coeff_pct_per_c=temp_coeff_voc_pct_per_c,
    )


# ---------------------------------------------------------------------------
# ENA Engineering Recommendation G99 — fast-track / standard / detailed study
# ---------------------------------------------------------------------------
@dataclass
class G99Result:
    fault_contribution_ka: float
    voltage_step_change_pct: float
    application_route: str
    threshold_mw: float
    voltage_kv: int
    poc_fault_level_mva: float
    reactive_power_mvar: float
    flags: list[str]
    standard: str = "ENA Engineering Recommendation G99 Issue 1 Amendment 11"

    def to_dict(self) -> dict:
        return asdict(self)


def g99_screen(
    mw: float,
    voltage_kv: int,
    poc_fault_level_mva: float = 500.0,
    poc_type: Literal["11kV", "33kV", "132kV"] = "33kV",
) -> G99Result:
    """Screen a generator against G99 Issue 1 Am 11 connection routes.

    • I_k″  = S / (√3 · V) · k   with k≈5 as the typical inverter fault-current
      multiplier (G99 Type B/C inverter SC contribution factor).
    • ΔV_step = (MW / S_sc) · 100 %   — the P28/P29 voltage step metric.
    • Routing per G99 Issue 1 Am 11 A.5:
        – ΔV < 3 %  AND  ≤ 50 MW  AND  voltage ≤ 33 kV → Fast Track (Type A/B)
        – ΔV < 4 %  AND  ≤ 50 MW                      → Standard (Type B/C)
        – otherwise                                    → Detailed Study (Type C/D)
    """
    if mw <= 0 or voltage_kv <= 0 or poc_fault_level_mva <= 0:
        raise ValueError("mw, voltage_kv and poc_fault_level_mva must be > 0")

    # Fault contribution (inverter-dominated): multiplier 5× nominal
    nominal_current_ka = (mw) / (math.sqrt(3) * voltage_kv)  # kA
    fault_contribution_ka = nominal_current_ka * 5.0

    # Voltage step (ER P28 form), neglecting grid impedance angle — conservative
    v_step_pct = (mw / poc_fault_level_mva) * 100.0

    # G99 thresholds
    flags: list[str] = []
    if v_step_pct < 3.0 and mw <= 50.0 and voltage_kv <= 33:
        route = "Fast Track"
        flags.append("G99 Clause A.5.1 (Fast Track Type A/B, ΔV < 3 %, MW ≤ 50)")
    elif v_step_pct < 4.0 and mw <= 50.0:
        route = "Standard"
        flags.append("G99 Clause A.5.2 (Standard Type B/C application)")
    else:
        route = "Detailed Study"
        flags.append("G99 Clause A.5.3 (Detailed study required — DNO/ESO)")

    # P28/P29 screen
    if v_step_pct >= 3.0:
        flags.append("ER P28 Issue 2 — voltage fluctuation limits engaged")
    if mw >= 50.0:
        flags.append("G99 Type C (≥ 50 MW) — bilateral agreement required")
    if mw >= 100.0 or voltage_kv >= 132:
        flags.append("G99 Type D (≥ 100 MW or ≥ 110 kV) — Grid Code compliance")
    if fault_contribution_ka > 25.0:
        flags.append("Fault contribution > 25 kA — switchgear fault-rating review")

    # Reactive-power obligation at 0.95 lagging (G99 Type B+ requirement)
    q_req_mvar = reactive_power_requirement(mw, pf_target=0.95, operating_pf=1.0)

    return G99Result(
        fault_contribution_ka=round(fault_contribution_ka, 3),
        voltage_step_change_pct=round(v_step_pct, 3),
        application_route=route,
        threshold_mw=mw,
        voltage_kv=voltage_kv,
        poc_fault_level_mva=poc_fault_level_mva,
        reactive_power_mvar=round(q_req_mvar, 2),
        flags=flags,
    )


def reactive_power_requirement(
    mw: float,
    pf_target: float = 0.95,
    operating_pf: float = 1.0,
) -> float:
    """Return MVAr needed to move from `operating_pf` to `pf_target`.

    Q = P · (tan(acos(pf_target)) − tan(acos(operating_pf)))
    Positive value = reactive import (lagging) required from the plant.
    """
    if not (0 < pf_target <= 1.0) or not (0 < operating_pf <= 1.0):
        raise ValueError("Power factors must be in (0, 1]")
    q_target = mw * math.tan(math.acos(pf_target))
    q_op = mw * math.tan(math.acos(operating_pf))
    return q_target - q_op


# ---------------------------------------------------------------------------
# HARMONIC DISTORTION (IEC 61000-3-6 / ENA G5/5)
# ---------------------------------------------------------------------------
@dataclass
class HarmonicResult:
    inputs_echo: dict
    outputs: dict
    assumptions: list[str]
    provenance: str
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


# Typical per-harmonic emission limits (%) at PCC from ENA ER G5/5
# (planning levels for MV systems). Only orders 5, 7, 11, 13 modelled.
_G5_LIMITS = {5: 5.0, 7: 4.0, 11: 3.0, 13: 2.5}


def estimate_harmonic_distortion(
    mw: float,
    voltage_kv: float,
    inverter_thd_pct: float = 3.0,
    n_inverters: int = 1,
    short_circuit_mva: float = 500.0,
    filter_attenuation_pct: float = 0.0,
) -> HarmonicResult:
    """Estimate voltage THD at PCC from inverter current harmonics.

    Uses the standard approximation THD_v ≈ (I_source / I_sc) · THD_i · k
    where k ≈ 1 for non-resonant MV networks. Per-harmonic compared to
    ENA ER G5/5 planning levels.
    """
    if mw <= 0 or short_circuit_mva <= 0:
        raise ValueError("mw and short_circuit_mva must be > 0")

    # Diversity — incoherent summation reduces THD with multiple units
    diversity = 1.0 if n_inverters <= 1 else 1.0 / math.sqrt(n_inverters)
    net_thd_i = inverter_thd_pct * diversity * (1.0 - filter_attenuation_pct / 100.0)
    ratio = mw / short_circuit_mva  # stiffness ratio
    thd_v_pct = round(net_thd_i * ratio, 3)  # THD_v ≈ THD_i × (S/S_sc), both in %

    # Distribute across dominant orders (IEC 61000 typical spectrum shape)
    spectrum = {5: 0.55, 7: 0.25, 11: 0.12, 13: 0.08}
    per_order = {}
    exceedances = []
    for h, share in spectrum.items():
        v_h = round(thd_v_pct * share, 3)
        per_order[h] = v_h
        if v_h > _G5_LIMITS[h]:
            exceedances.append(f"order-{h}: {v_h}% > G5/5 limit {_G5_LIMITS[h]}%")

    total_v_thd_limit = 5.0 if voltage_kv < 35 else 3.0  # G5/5 compatibility
    warnings = list(exceedances)
    if thd_v_pct > total_v_thd_limit:
        warnings.append(f"total V-THD {thd_v_pct}% > G5/5 limit {total_v_thd_limit}% at {voltage_kv}kV")

    return HarmonicResult(
        inputs_echo={
            "mw": mw, "voltage_kv": voltage_kv,
            "inverter_thd_pct": inverter_thd_pct,
            "n_inverters": n_inverters,
            "short_circuit_mva": short_circuit_mva,
            "filter_attenuation_pct": filter_attenuation_pct,
        },
        outputs={
            "total_voltage_thd_pct": thd_v_pct,
            "per_order_voltage_pct": per_order,
            "g5_compatibility_limit_pct": total_v_thd_limit,
            "stiffness_ratio": round(ratio, 4),
            "diversity_factor": round(diversity, 3),
            "exceeds_limits": bool(exceedances) or thd_v_pct > total_v_thd_limit,
        },
        assumptions=[
            "Spectrum weights: h5=55%, h7=25%, h11=12%, h13=8% (IEC 61000-3-6 typical)",
            "Incoherent summation: diversity = 1/sqrt(N) for N inverters",
            "Stiffness approximation: THD_v ≈ (S/S_sc) · THD_i",
            "G5/5 planning levels assumed for comparison",
        ],
        provenance="IEC 61000-3-6, ENA Engineering Recommendation G5/5",
        warnings=warnings,
    )

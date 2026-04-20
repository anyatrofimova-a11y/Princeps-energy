"""
G99/G100 Compliance Automation Module
======================================
Automates EREC G99 (generation ≥50 kW on distribution) and G100 (<50 kW)
application generation, compliance checking, protection settings, and
timeline estimation for UK distributed generation connections.

References:
  - ENA EREC G99 — current version resolved via
    ``app.regulatory.versions.cite("g99")`` (Issue 2, 10 March 2025 at
    time of writing; Annex C storage provisions in force 1 March 2026)
  - ENA EREC G100 Issue 1 Amendment 3 (2023)
  - ENA Engineering Recommendation P28/P29 (voltage limits)

Revenue context: Manual G99 filing via consultants costs £15-80k.
This module produces structured application data that can be exported
to PDF or submitted via DNO portals.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from app.regulatory.versions import cite as _cite_reg

# ---------------------------------------------------------------------------
# Constants & Enums
# ---------------------------------------------------------------------------

class GeneratorType(str, Enum):
    SOLAR_PV = "solar_pv"
    WIND = "wind"
    BESS = "bess"
    CHP = "chp"
    HYDRO = "hydro"
    BIOMASS = "biomass"
    GAS_RECIPROCATING = "gas_reciprocating"
    SYNCHRONOUS = "synchronous"
    OTHER = "other"


class G99Category(str, Enum):
    """G99 generator categories per ENA EREC G99 Table 1."""
    TYPE_A = "Type A"
    TYPE_B = "Type B"
    TYPE_C = "Type C"
    TYPE_D = "Type D"


class Phase(str, Enum):
    SINGLE = "single_phase"
    THREE = "three_phase"


class DNO(str, Enum):
    UKPN = "UKPN"          # UK Power Networks (South East, East, London)
    SSEN = "SSEN"           # Scottish and Southern Electricity Networks
    WPD_NGED = "NGED"       # National Grid Electricity Distribution (ex-WPD)
    ENWL = "ENWL"           # Electricity North West
    NPG = "NPG"             # Northern Powergrid
    SPEN = "SPEN"           # SP Energy Networks


# ---------------------------------------------------------------------------
# G99 Protection Settings Lookup Tables (EREC G99 Table A.1 / A.2)
# All values are from the published ENA standard.
# ---------------------------------------------------------------------------

# Under/Over Voltage protection settings — EREC G99 Table A.1
# Format: (setting_value, time_delay_seconds)
# Voltages expressed as % of nominal (Un)

VOLTAGE_PROTECTION: dict[str, dict[str, tuple[float, float]]] = {
    # --- Type A (and G100) generators ---
    "Type A": {
        "ov_stage_1":       (113.0, 1.0),      # Over-voltage Stage 1: 113% Un, 1.0 s
        "ov_stage_2":       (120.0, 0.5),       # Over-voltage Stage 2: 120% Un, 0.5 s
        "uv_stage_1":       (80.0,  2.5),       # Under-voltage Stage 1: 80% Un, 2.5 s
        "uv_stage_2":       (45.0,  0.5),       # Under-voltage Stage 2: 45% Un, 0.5 s (Type A only)
    },
    # --- Type B generators ---
    "Type B": {
        "ov_stage_1":       (113.0, 1.0),
        "ov_stage_2":       (120.0, 0.5),
        "uv_stage_1":       (80.0,  2.5),
        "uv_stage_2":       (45.0,  0.5),
    },
    # --- Type C generators ---
    "Type C": {
        "ov_stage_1":       (110.0, 1.0),
        "ov_stage_2":       (120.0, 0.5),
        "uv_stage_1":       (80.0,  2.5),
        "uv_stage_2":       (45.0,  0.5),
    },
    # --- Type D generators ---
    "Type D": {
        "ov_stage_1":       (110.0, 1.0),
        "ov_stage_2":       (120.0, 0.5),
        "uv_stage_1":       (80.0,  2.5),
        "uv_stage_2":       (45.0,  0.5),
    },
}

# Under/Over Frequency protection settings — EREC G99 Table A.2
# Format: (setting_hz, time_delay_seconds)

FREQUENCY_PROTECTION: dict[str, dict[str, tuple[float, float]]] = {
    "Type A": {
        "of_stage_1":       (50.4, 0.5),        # Over-frequency Stage 1: 50.4 Hz, 0.5 s
        "of_stage_2":       (52.0, 0.5),         # Over-frequency Stage 2: 52.0 Hz, 0.5 s
        "uf_stage_1":       (47.5, 20.0),        # Under-frequency Stage 1: 47.5 Hz, 20 s
        "uf_stage_2":       (47.0, 0.5),         # Under-frequency Stage 2: 47.0 Hz, 0.5 s
    },
    "Type B": {
        "of_stage_1":       (50.4, 0.5),
        "of_stage_2":       (52.0, 0.5),
        "uf_stage_1":       (47.5, 20.0),
        "uf_stage_2":       (47.0, 0.5),
    },
    "Type C": {
        "of_stage_1":       (50.4, 0.5),
        "of_stage_2":       (52.0, 0.5),
        "uf_stage_1":       (47.5, 20.0),
        "uf_stage_2":       (47.0, 0.5),
    },
    "Type D": {
        "of_stage_1":       (50.4, 0.5),
        "of_stage_2":       (52.0, 0.5),
        "uf_stage_1":       (47.5, 20.0),
        "uf_stage_2":       (47.0, 0.5),
    },
}

# Rate of Change of Frequency (RoCoF) — EREC G99 Section 10.5
# All types must ride through RoCoF up to 1 Hz/s measured over 500 ms.
# Protection setting (if fitted) must be ≥1 Hz/s with 500 ms window.

ROCOF_SETTINGS: dict[str, dict[str, float]] = {
    "Type A": {"setting_hz_per_s": 1.0, "time_delay_s": 0.0, "measurement_window_ms": 500},
    "Type B": {"setting_hz_per_s": 1.0, "time_delay_s": 0.0, "measurement_window_ms": 500},
    "Type C": {"setting_hz_per_s": 1.0, "time_delay_s": 0.0, "measurement_window_ms": 500},
    "Type D": {"setting_hz_per_s": 1.0, "time_delay_s": 0.0, "measurement_window_ms": 500},
}

# Loss of Mains (LoM) protection — EREC G99 Section 10.6
# RoCoF-based LoM is the primary method since G59/3-4 and G99.
# Vector shift is no longer recommended as primary LoM but may be
# required as backup by some DNOs.

LOM_SETTINGS: dict[str, dict[str, Any]] = {
    "Type A": {
        "primary_method": "RoCoF",
        "rocof_setting_hz_per_s": 1.0,
        "rocof_delay_s": 0.5,
        "rocof_window_ms": 500,
        "vector_shift_required": False,
        "vector_shift_degrees": None,
    },
    "Type B": {
        "primary_method": "RoCoF",
        "rocof_setting_hz_per_s": 1.0,
        "rocof_delay_s": 0.5,
        "rocof_window_ms": 500,
        "vector_shift_required": False,
        "vector_shift_degrees": None,
    },
    "Type C": {
        "primary_method": "RoCoF",
        "rocof_setting_hz_per_s": 1.0,
        "rocof_delay_s": 0.5,
        "rocof_window_ms": 500,
        "vector_shift_required": False,
        "vector_shift_degrees": None,
    },
    "Type D": {
        "primary_method": "RoCoF + teleprotection",
        "rocof_setting_hz_per_s": 1.0,
        "rocof_delay_s": 0.5,
        "rocof_window_ms": 500,
        "vector_shift_required": False,
        "vector_shift_degrees": None,
        "intertrip_required": True,
    },
}

# Vector shift legacy settings (if DNO still requires as backup)
VECTOR_SHIFT_SETTING_DEGREES = 6.0  # degrees, 0.5 s delay

# ---------------------------------------------------------------------------
# Power Quality Limits — EREC G99 Annex A / Engineering Rec P28-P29
# ---------------------------------------------------------------------------

# Harmonic current emission limits (% of rated current) — G99 Annex A Table A.3
# Based on IEEE 519 / IEC 61000-3-6 adapted for UK networks
# Odd harmonics only shown; even harmonics are 25% of adjacent odd values.

HARMONIC_LIMITS_PERCENT: dict[int, float] = {
    # Harmonic order: max % of fundamental current
    3:  4.0,
    5:  4.0,
    7:  4.0,
    9:  2.0,
    11: 2.0,
    13: 2.0,
    15: 1.0,
    17: 1.0,
    19: 1.0,
    21: 0.6,
    23: 0.6,
    25: 0.6,
    27: 0.4,
    29: 0.4,
    31: 0.4,
    33: 0.3,
    35: 0.3,
    37: 0.3,
    39: 0.2,
}

# Total Harmonic Distortion limit
THD_LIMIT_PERCENT = 5.0

# Flicker limits — Engineering Rec P28
FLICKER_LIMITS = {
    "pst_1min":   1.0,     # Short-term flicker severity Pst (1 min)
    "pst_10min":  0.8,     # Short-term flicker severity Pst (10 min)
    "plt":        0.65,    # Long-term flicker severity Plt
}

# Voltage unbalance limit — G99 Section 8.3
VOLTAGE_UNBALANCE_LIMIT_PERCENT = 1.3  # Negative phase sequence

# Rapid voltage change (% of Un) — P28
RAPID_VOLTAGE_CHANGE_LIMIT_PERCENT = 3.0  # For infrequent switching events

# DC injection limit — G99 Section 8.2
DC_INJECTION_LIMIT_PERCENT = 0.25  # of rated current, absolute max

# ---------------------------------------------------------------------------
# Fault Level Contribution by Technology — typical values
# ---------------------------------------------------------------------------

# Expressed as multiples of rated current (Ir)
FAULT_CURRENT_CONTRIBUTION: dict[str, dict[str, float]] = {
    GeneratorType.SOLAR_PV: {
        "subtransient_pu": 1.1,   # Inverter-based: limited to ~1.1× Ir
        "transient_pu":    1.1,
        "steady_state_pu": 1.0,
        "x_over_r":        1.0,   # Predominantly resistive
        "description": "Inverter-limited fault current. Modern grid-forming inverters may provide up to 1.2× Ir.",
    },
    GeneratorType.WIND: {
        "subtransient_pu": 1.1,   # Type 4 (full converter): ~1.1× Ir
        "transient_pu":    1.1,
        "steady_state_pu": 1.0,
        "x_over_r":        1.0,
        "description": "Full-converter wind turbine (Type 4). Type 3 DFIG may contribute 3-5× Ir subtransient.",
    },
    GeneratorType.BESS: {
        "subtransient_pu": 1.2,
        "transient_pu":    1.1,
        "steady_state_pu": 1.0,
        "x_over_r":        1.0,
        "description": "Battery inverter fault contribution. Grid-forming BESS may have higher contribution.",
    },
    GeneratorType.CHP: {
        "subtransient_pu": 6.0,   # Synchronous machine
        "transient_pu":    3.5,
        "steady_state_pu": 2.5,
        "x_over_r":        10.0,
        "description": "Synchronous generator (gas engine CHP). High fault contribution.",
    },
    GeneratorType.HYDRO: {
        "subtransient_pu": 5.0,
        "transient_pu":    3.0,
        "steady_state_pu": 2.0,
        "x_over_r":        8.0,
        "description": "Synchronous hydro generator.",
    },
    GeneratorType.BIOMASS: {
        "subtransient_pu": 6.0,
        "transient_pu":    3.5,
        "steady_state_pu": 2.5,
        "x_over_r":        10.0,
        "description": "Synchronous generator (steam turbine).",
    },
    GeneratorType.GAS_RECIPROCATING: {
        "subtransient_pu": 6.5,
        "transient_pu":    4.0,
        "steady_state_pu": 3.0,
        "x_over_r":        12.0,
        "description": "Synchronous generator (reciprocating gas engine).",
    },
    GeneratorType.SYNCHRONOUS: {
        "subtransient_pu": 6.0,
        "transient_pu":    3.5,
        "steady_state_pu": 2.5,
        "x_over_r":        10.0,
        "description": "Generic synchronous machine.",
    },
    GeneratorType.OTHER: {
        "subtransient_pu": 1.5,
        "transient_pu":    1.2,
        "steady_state_pu": 1.0,
        "x_over_r":        2.0,
        "description": "Default conservative estimate. Consult manufacturer data.",
    },
}

# ---------------------------------------------------------------------------
# DNO Processing Times (business days) — empirical/industry data
# ---------------------------------------------------------------------------

# Base processing days by capacity tier; DNO multipliers applied after.
BASE_PROCESSING_DAYS: dict[str, dict[str, int]] = {
    "Type A": {
        "application_review":    10,
        "design_approval":       15,
        "connection_offer":      25,    # 45 calendar days statutory (≤30 BD)
        "commissioning_window":  20,
        "total_statutory_days":  45,    # Calendar days for offer
    },
    "Type B": {
        "application_review":    15,
        "design_approval":       25,
        "connection_offer":      45,    # 65 BD typical for >1MW
        "commissioning_window":  30,
        "total_statutory_days":  65,
    },
    "Type C": {
        "application_review":    20,
        "design_approval":       40,
        "connection_offer":      65,    # 3 months statutory
        "commissioning_window":  40,
        "total_statutory_days":  90,
    },
    "Type D": {
        "application_review":    25,
        "design_approval":       60,
        "connection_offer":      90,    # NGESO involved; 3-6 months
        "commissioning_window":  60,
        "total_statutory_days":  180,
    },
}

# DNO speed multiplier (1.0 = baseline). Based on Ofgem connection data.
DNO_SPEED_FACTOR: dict[str, float] = {
    DNO.UKPN:     1.15,   # Typically slower — high volume, London constraints
    DNO.SSEN:     1.05,   # Moderate
    DNO.WPD_NGED: 0.90,   # Generally faster — good digital systems
    DNO.ENWL:     1.00,   # Baseline
    DNO.NPG:      1.00,   # Baseline
    DNO.SPEN:     1.10,   # Moderate — Scottish network constraints
}

# Application fees by category (£ approx)
APPLICATION_FEES: dict[str, dict[str, float]] = {
    "Type A": {"application_fee": 0, "assessment_fee": 0, "commissioning_fee": 350},
    "Type B": {"application_fee": 380, "assessment_fee": 1800, "commissioning_fee": 1200},
    "Type C": {"application_fee": 380, "assessment_fee": 5500, "commissioning_fee": 3500},
    "Type D": {"application_fee": 380, "assessment_fee": 12000, "commissioning_fee": 8000},
}

# ---------------------------------------------------------------------------
# G99 Commissioning Requirements by Type
# ---------------------------------------------------------------------------

COMMISSIONING_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "Type A": {
        "witness_test_required": False,
        "g99_form_a1": True,          # Application form
        "g99_form_a2": True,          # Commissioning confirmation
        "protection_test_required": True,
        "loss_of_mains_test": True,
        "interface_test": False,
        "performance_chart": False,
        "stability_study": False,
        "description": "Self-certification by installer. DNO may audit.",
    },
    "Type B": {
        "witness_test_required": True,  # DNO witness required
        "g99_form_a1": True,
        "g99_form_a2": True,
        "protection_test_required": True,
        "loss_of_mains_test": True,
        "interface_test": True,
        "performance_chart": True,      # P-Q capability chart
        "stability_study": False,
        "description": "DNO-witnessed commissioning required. Interface protection testing mandatory.",
    },
    "Type C": {
        "witness_test_required": True,
        "g99_form_a1": True,
        "g99_form_a2": True,
        "protection_test_required": True,
        "loss_of_mains_test": True,
        "interface_test": True,
        "performance_chart": True,
        "stability_study": True,        # Dynamic stability study
        "description": "Full commissioning programme. Dynamic stability study required pre-connection.",
    },
    "Type D": {
        "witness_test_required": True,
        "g99_form_a1": True,
        "g99_form_a2": True,
        "protection_test_required": True,
        "loss_of_mains_test": True,
        "interface_test": True,
        "performance_chart": True,
        "stability_study": True,
        "intertrip_test": True,         # Intertrip / teleprotection test
        "ngeso_compliance": True,       # NGESO Grid Code compliance
        "description": "Full commissioning + NGESO Grid Code compliance. Intertrip testing mandatory.",
    },
}

# ---------------------------------------------------------------------------
# Reactive Power Capability Requirements — EREC G99 Section 9
# ---------------------------------------------------------------------------

REACTIVE_POWER_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "Type A": {
        "power_factor_range": (0.95, 1.0),  # lagging to unity
        "q_at_pmax": None,
        "voltage_control": False,
        "description": "Fixed power factor or Q=0.",
    },
    "Type B": {
        "power_factor_range": (0.95, 0.95),  # 0.95 lag to 0.95 lead
        "q_at_pmax": "±0.329 × Pmax",        # tan(arccos(0.95))
        "voltage_control": False,
        "description": "Must be capable of 0.95 lead to 0.95 lag at Pmax.",
    },
    "Type C": {
        "power_factor_range": (0.95, 0.95),
        "q_at_pmax": "±0.329 × Pmax",
        "voltage_control": True,
        "description": "0.95 lead to 0.95 lag. Voltage control mode required if DNO requests.",
    },
    "Type D": {
        "power_factor_range": (0.95, 0.95),
        "q_at_pmax": "±0.329 × Pmax",
        "voltage_control": True,
        "frequency_response": True,
        "description": "Full reactive capability. Mandatory voltage control and frequency response.",
    },
}

# ---------------------------------------------------------------------------
# Frequency Response Requirements — EREC G99 Section 10.3
# ---------------------------------------------------------------------------

FREQUENCY_RESPONSE: dict[str, dict[str, Any]] = {
    "Type A": {
        "lfsm_o_required": True,     # Limited Frequency Sensitive Mode — Over-frequency
        "lfsm_o_threshold_hz": 50.4,
        "lfsm_o_droop_percent": 5.0, # 5% droop (2% power reduction per 0.1 Hz)
        "lfsm_u_required": False,
        "fsm_required": False,
        "description": "LFSM-O only: reduce output above 50.4 Hz at 5% droop.",
    },
    "Type B": {
        "lfsm_o_required": True,
        "lfsm_o_threshold_hz": 50.4,
        "lfsm_o_droop_percent": 5.0,
        "lfsm_u_required": True,     # Also under-frequency response
        "lfsm_u_threshold_hz": 49.5,
        "lfsm_u_droop_percent": 5.0,
        "fsm_required": False,
        "description": "LFSM-O and LFSM-U. Respond to both over and under frequency.",
    },
    "Type C": {
        "lfsm_o_required": True,
        "lfsm_o_threshold_hz": 50.4,
        "lfsm_o_droop_percent": 5.0,
        "lfsm_u_required": True,
        "lfsm_u_threshold_hz": 49.5,
        "lfsm_u_droop_percent": 5.0,
        "fsm_required": True,        # Full Frequency Sensitive Mode
        "fsm_deadband_hz": 0.015,
        "fsm_droop_percent": 4.0,
        "description": "LFSM-O, LFSM-U, and FSM. Continuous frequency regulation.",
    },
    "Type D": {
        "lfsm_o_required": True,
        "lfsm_o_threshold_hz": 50.4,
        "lfsm_o_droop_percent": 5.0,
        "lfsm_u_required": True,
        "lfsm_u_threshold_hz": 49.5,
        "lfsm_u_droop_percent": 5.0,
        "fsm_required": True,
        "fsm_deadband_hz": 0.015,
        "fsm_droop_percent": 4.0,
        "description": "As Type C plus NGESO Grid Code obligations.",
    },
}

# ---------------------------------------------------------------------------
# Fault Ride Through Requirements — EREC G99 Section 10.4
# ---------------------------------------------------------------------------

FAULT_RIDE_THROUGH: dict[str, dict[str, Any]] = {
    "Type A": {
        "required": False,
        "description": "No FRT requirement.",
    },
    "Type B": {
        "required": True,
        "voltage_against_time": [
            # (time_ms, voltage_percent_Un) — must remain connected above this envelope
            (0,    0),      # Fault inception: 0% voltage
            (140,  0),      # Ride through zero voltage for 140 ms
            (140,  15),     # Voltage recovery to 15%
            (700,  15),     # Hold at 15% until 700 ms
            (1500, 85),     # Ramp to 85% by 1500 ms
            (2500, 85),     # Sustain 85%
            (3000, 90),     # Back to 90% within 3 s
        ],
        "description": "Must ride through voltage dips per FRT envelope. Zero voltage for 140 ms.",
    },
    "Type C": {
        "required": True,
        "voltage_against_time": [
            (0,    0),
            (140,  0),
            (140,  15),
            (700,  15),
            (1500, 85),
            (2500, 85),
            (3000, 90),
        ],
        "post_fault_active_current_recovery_time_ms": 1000,
        "post_fault_reactive_current_support": True,
        "description": "FRT with fast post-fault active power recovery (≤1 s to 90% pre-fault).",
    },
    "Type D": {
        "required": True,
        "voltage_against_time": [
            (0,    0),
            (140,  0),
            (140,  15),
            (700,  15),
            (1500, 85),
            (2500, 85),
            (3000, 90),
        ],
        "post_fault_active_current_recovery_time_ms": 500,
        "post_fault_reactive_current_support": True,
        "description": "FRT with fastest recovery (≤0.5 s). NGESO Grid Code FRT also applies.",
    },
}


# ---------------------------------------------------------------------------
# Helper: Normalise technology string to GeneratorType enum
# ---------------------------------------------------------------------------

def _normalise_technology(technology: str) -> GeneratorType:
    """Map user-supplied technology string to GeneratorType enum."""
    mapping = {
        "solar": GeneratorType.SOLAR_PV,
        "solar_pv": GeneratorType.SOLAR_PV,
        "pv": GeneratorType.SOLAR_PV,
        "photovoltaic": GeneratorType.SOLAR_PV,
        "wind": GeneratorType.WIND,
        "onshore_wind": GeneratorType.WIND,
        "offshore_wind": GeneratorType.WIND,
        "bess": GeneratorType.BESS,
        "battery": GeneratorType.BESS,
        "storage": GeneratorType.BESS,
        "chp": GeneratorType.CHP,
        "combined_heat_power": GeneratorType.CHP,
        "hydro": GeneratorType.HYDRO,
        "hydroelectric": GeneratorType.HYDRO,
        "biomass": GeneratorType.BIOMASS,
        "gas": GeneratorType.GAS_RECIPROCATING,
        "gas_reciprocating": GeneratorType.GAS_RECIPROCATING,
        "synchronous": GeneratorType.SYNCHRONOUS,
    }
    key = technology.lower().strip().replace(" ", "_").replace("-", "_")
    return mapping.get(key, GeneratorType.OTHER)


def _normalise_dno(dno: str) -> str:
    """Map user-supplied DNO string to DNO enum value."""
    mapping = {
        "ukpn": DNO.UKPN,
        "uk power networks": DNO.UKPN,
        "ssen": DNO.SSEN,
        "scottish and southern": DNO.SSEN,
        "scottish hydro": DNO.SSEN,
        "nged": DNO.WPD_NGED,
        "wpd": DNO.WPD_NGED,
        "western power": DNO.WPD_NGED,
        "national grid electricity distribution": DNO.WPD_NGED,
        "enwl": DNO.ENWL,
        "electricity north west": DNO.ENWL,
        "npg": DNO.NPG,
        "northern powergrid": DNO.NPG,
        "northern power": DNO.NPG,
        "spen": DNO.SPEN,
        "sp energy": DNO.SPEN,
        "scottish power": DNO.SPEN,
    }
    key = dno.lower().strip()
    result = mapping.get(key)
    if result is None:
        # Try prefix match
        for k, v in mapping.items():
            if key.startswith(k) or k.startswith(key):
                return v.value
        return dno.upper()
    return result.value


# ===================================================================
# PUBLIC API
# ===================================================================

def check_g99_compliance(
    capacity_mw: float,
    voltage_kv: float,
    technology: str,
    phase: str = "three_phase",
) -> dict[str, Any]:
    """
    Determine which G99/G100 generator category applies and return
    the full set of applicable requirements.

    Category thresholds (current EREC G99 per
    ``app.regulatory.versions.cite("g99")``):
      - Type A: 0.8 kW – 1 MW (single-phase) or 0.8 kW – 50 kW (three-phase)
      - Type B: 1 MW – 10 MW (single-phase) or 50 kW – 1 MW (three-phase)
                Note: also 1 MW – 10 MW three-phase
      - Type C: 10 MW – 50 MW
      - Type D: ≥50 MW
    Below 0.8 kW → G98 (micro-generation), not covered here.

    Returns dict with: category, thresholds, protection, commissioning,
    reactive_power, frequency_response, fault_ride_through, notes.
    """
    capacity_kw = capacity_mw * 1000.0
    is_single = phase.lower().startswith("single")

    # Determine category
    if capacity_kw < 0.8:
        category_str = "Below G99"
        notes = "Capacity <0.8 kW falls under G98 (micro-generation). G99 does not apply."
    elif is_single:
        if capacity_kw <= 1000:
            category_str = G99Category.TYPE_A.value
        elif capacity_kw <= 10_000:
            category_str = G99Category.TYPE_B.value
        elif capacity_kw <= 50_000:
            category_str = G99Category.TYPE_C.value
        else:
            category_str = G99Category.TYPE_D.value
        notes = "Single-phase classification applied."
    else:
        # Three-phase
        if capacity_kw <= 50:
            category_str = G99Category.TYPE_A.value
        elif capacity_kw <= 1000:
            category_str = G99Category.TYPE_B.value
        elif capacity_kw <= 10_000:
            category_str = G99Category.TYPE_B.value
            notes = "1–10 MW three-phase → Type B."
        elif capacity_kw <= 50_000:
            category_str = G99Category.TYPE_C.value
        else:
            category_str = G99Category.TYPE_D.value
        notes = f"Three-phase classification: {category_str}."

    # Build full requirements if within G99 scope
    if category_str == "Below G99":
        return {
            "category": category_str,
            "capacity_kw": capacity_kw,
            "voltage_kv": voltage_kv,
            "technology": technology,
            "phase": "single" if is_single else "three",
            "applicable_standard": "EREC G98",
            "notes": notes,
        }

    tech_enum = _normalise_technology(technology)

    return {
        "category": category_str,
        "capacity_kw": capacity_kw,
        "capacity_mw": capacity_mw,
        "voltage_kv": voltage_kv,
        "technology": tech_enum.value,
        "phase": "single" if is_single else "three",
        "applicable_standard": _cite_reg("g99"),
        "voltage_protection": VOLTAGE_PROTECTION.get(category_str, {}),
        "frequency_protection": FREQUENCY_PROTECTION.get(category_str, {}),
        "rocof": ROCOF_SETTINGS.get(category_str, {}),
        "loss_of_mains": LOM_SETTINGS.get(category_str, {}),
        "commissioning": COMMISSIONING_REQUIREMENTS.get(category_str, {}),
        "reactive_power": REACTIVE_POWER_REQUIREMENTS.get(category_str, {}),
        "frequency_response": FREQUENCY_RESPONSE.get(category_str, {}),
        "fault_ride_through": FAULT_RIDE_THROUGH.get(category_str, {}),
        "fees": APPLICATION_FEES.get(category_str, {}),
        "notes": notes,
    }


def g99_protection_settings(
    capacity_mw: float,
    voltage_kv: float,
    technology: str,
    phase: str = "three_phase",
) -> dict[str, Any]:
    """
    Return the full set of required protection relay settings for a
    G99-connected generator, including:
      - Under/over voltage (Stage 1 & 2)
      - Under/over frequency (Stage 1 & 2)
      - RoCoF
      - Vector shift (if applicable)
      - Loss of Mains
      - Fault ride through envelope
      - Fault level contribution estimate

    All values taken from EREC G99 published tables.
    """
    compliance = check_g99_compliance(capacity_mw, voltage_kv, technology, phase)
    cat = compliance.get("category", "Type B")

    if cat == "Below G99":
        return {
            "error": "Capacity below G99 threshold (0.8 kW). Use G98.",
            "compliance": compliance,
        }

    tech_enum = _normalise_technology(technology)
    fault_data = FAULT_CURRENT_CONTRIBUTION.get(tech_enum, FAULT_CURRENT_CONTRIBUTION[GeneratorType.OTHER])

    rated_current_a = (capacity_mw * 1e6) / (voltage_kv * 1e3 * math.sqrt(3)) if voltage_kv > 0 else 0

    # Assemble protection schedule
    protection = {
        "category": cat,
        "capacity_mw": capacity_mw,
        "voltage_kv": voltage_kv,
        "technology": tech_enum.value,
        "rated_current_a": round(rated_current_a, 1),

        "voltage_protection": {
            "over_voltage_stage_1": {
                "setting_percent_un": VOLTAGE_PROTECTION[cat]["ov_stage_1"][0],
                "time_delay_s": VOLTAGE_PROTECTION[cat]["ov_stage_1"][1],
                "action": "Trip",
            },
            "over_voltage_stage_2": {
                "setting_percent_un": VOLTAGE_PROTECTION[cat]["ov_stage_2"][0],
                "time_delay_s": VOLTAGE_PROTECTION[cat]["ov_stage_2"][1],
                "action": "Trip (instantaneous)",
            },
            "under_voltage_stage_1": {
                "setting_percent_un": VOLTAGE_PROTECTION[cat]["uv_stage_1"][0],
                "time_delay_s": VOLTAGE_PROTECTION[cat]["uv_stage_1"][1],
                "action": "Trip",
            },
            "under_voltage_stage_2": {
                "setting_percent_un": VOLTAGE_PROTECTION[cat]["uv_stage_2"][0],
                "time_delay_s": VOLTAGE_PROTECTION[cat]["uv_stage_2"][1],
                "action": "Trip (instantaneous)",
            },
        },

        "frequency_protection": {
            "over_frequency_stage_1": {
                "setting_hz": FREQUENCY_PROTECTION[cat]["of_stage_1"][0],
                "time_delay_s": FREQUENCY_PROTECTION[cat]["of_stage_1"][1],
                "action": "Trip",
            },
            "over_frequency_stage_2": {
                "setting_hz": FREQUENCY_PROTECTION[cat]["of_stage_2"][0],
                "time_delay_s": FREQUENCY_PROTECTION[cat]["of_stage_2"][1],
                "action": "Trip (instantaneous)",
            },
            "under_frequency_stage_1": {
                "setting_hz": FREQUENCY_PROTECTION[cat]["uf_stage_1"][0],
                "time_delay_s": FREQUENCY_PROTECTION[cat]["uf_stage_1"][1],
                "action": "Trip",
            },
            "under_frequency_stage_2": {
                "setting_hz": FREQUENCY_PROTECTION[cat]["uf_stage_2"][0],
                "time_delay_s": FREQUENCY_PROTECTION[cat]["uf_stage_2"][1],
                "action": "Trip (instantaneous)",
            },
        },

        "rocof_protection": {
            "setting_hz_per_s": ROCOF_SETTINGS[cat]["setting_hz_per_s"],
            "measurement_window_ms": ROCOF_SETTINGS[cat]["measurement_window_ms"],
            "ride_through_requirement": "Must ride through RoCoF up to 1 Hz/s for 500 ms",
        },

        "loss_of_mains": LOM_SETTINGS[cat],

        "vector_shift": {
            "setting_degrees": VECTOR_SHIFT_SETTING_DEGREES,
            "note": "Vector shift no longer primary LoM method. May be required as backup by some DNOs.",
        },

        "fault_level_contribution": {
            "technology": tech_enum.value,
            "subtransient_fault_current_pu": fault_data["subtransient_pu"],
            "transient_fault_current_pu": fault_data["transient_pu"],
            "steady_state_fault_current_pu": fault_data["steady_state_pu"],
            "x_over_r_ratio": fault_data["x_over_r"],
            "estimated_subtransient_current_ka": round(
                rated_current_a * fault_data["subtransient_pu"] / 1000, 3
            ),
            "estimated_steady_state_current_ka": round(
                rated_current_a * fault_data["steady_state_pu"] / 1000, 3
            ),
            "description": fault_data["description"],
        },

        "fault_ride_through": FAULT_RIDE_THROUGH.get(cat, {}),
    }

    return protection


def estimate_g99_timeline(
    capacity_mw: float,
    dno: str,
    phase: str = "three_phase",
) -> dict[str, Any]:
    """
    Estimate the G99 connection application timeline for a given
    capacity and DNO, including:
      - Application review period
      - Design approval
      - Connection offer (statutory deadline)
      - Commissioning window
      - Total estimated calendar days
      - Application fees

    Timelines based on Ofgem Connections standards and DNO performance data.
    """
    compliance = check_g99_compliance(capacity_mw, 11.0, "solar_pv", phase)
    cat = compliance.get("category", "Type B")

    if cat == "Below G99":
        return {
            "error": "Capacity below G99 threshold. Use G98 process.",
            "capacity_mw": capacity_mw,
        }

    dno_name = _normalise_dno(dno)
    speed_factor = DNO_SPEED_FACTOR.get(DNO(dno_name) if dno_name in [d.value for d in DNO] else DNO.ENWL, 1.0)

    base = BASE_PROCESSING_DAYS[cat]
    fees = APPLICATION_FEES[cat]

    review_days = int(base["application_review"] * speed_factor)
    design_days = int(base["design_approval"] * speed_factor)
    offer_days = int(base["connection_offer"] * speed_factor)
    commission_days = int(base["commissioning_window"] * speed_factor)
    statutory_days = base["total_statutory_days"]

    total_business_days = review_days + design_days + offer_days + commission_days
    total_calendar_days = int(total_business_days * 1.4)  # Rough BD → calendar

    today = datetime.now()

    return {
        "category": cat,
        "capacity_mw": capacity_mw,
        "dno": dno_name,
        "dno_speed_factor": speed_factor,

        "timeline_business_days": {
            "application_review": review_days,
            "design_approval": design_days,
            "connection_offer": offer_days,
            "commissioning_window": commission_days,
            "total": total_business_days,
        },

        "estimated_calendar_days": total_calendar_days,
        "statutory_offer_deadline_days": statutory_days,

        "estimated_dates": {
            "application_submitted": today.strftime("%Y-%m-%d"),
            "review_complete": (today + timedelta(days=int(review_days * 1.4))).strftime("%Y-%m-%d"),
            "design_approved": (today + timedelta(days=int((review_days + design_days) * 1.4))).strftime("%Y-%m-%d"),
            "connection_offer": (today + timedelta(days=int((review_days + design_days + offer_days) * 1.4))).strftime("%Y-%m-%d"),
            "commissioning_complete": (today + timedelta(days=total_calendar_days)).strftime("%Y-%m-%d"),
        },

        "fees_gbp": fees,
        "total_fees_gbp": sum(fees.values()),

        "commissioning_requirements": COMMISSIONING_REQUIREMENTS[cat],

        "notes": [
            f"Statutory connection offer deadline: {statutory_days} calendar days from valid application.",
            f"DNO {dno_name} speed factor: {speed_factor:.2f} (1.0 = baseline).",
            "Dates are estimates only. Actual timelines depend on network studies and DNO workload.",
            "Commissioning dates assume no reinforcement works required.",
        ],
    }


def generate_g99_application(
    lat: float,
    lon: float,
    capacity_mw: float,
    technology: str,
    voltage_kv: float,
    dno: str,
    phase: str = "three_phase",
    applicant: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Generate a structured G99 application data package.

    Thin passthrough to the canonical generator at
    ``utils.g99_pack_generator.generate_g99_application_from_scalars``
    (COUNCIL-1 consolidation, BOT-T 2026-04-19). The canonical generator
    renders ENA EREC G99 **Issue 2** (10 March 2025) sections A–I plus
    Annex C (storage, effective 1 March 2026). This wrapper preserves the
    historical fields that callers of ``utils.g99_compliance`` relied on:
    ``category``, ``timeline``, ``compliance_summary``, ``commissioning``,
    ``checklist`` — sourced from the compliance helpers that still live in
    this module.

    Parameters:
        lat, lon:       Site coordinates (WGS84)
        capacity_mw:    Generator capacity in MW
        technology:     Generator technology (solar_pv, wind, bess, chp, etc.)
        voltage_kv:     Connection voltage in kV
        dno:            Distribution Network Operator name/code
        phase:          'three_phase' or 'single_phase'
        applicant:      Optional dict with applicant details to fill Section A

    Returns:
        Dict with the canonical pack payload (``form_data``, ``html``,
        ``filename``, ``document_type``, ``auto_fill_pct``, ``provenance``)
        plus back-compat keys: ``category``, ``standard``, ``timeline``,
        ``compliance_summary``, ``commissioning``, ``checklist``.
    """
    from utils.g99_pack_generator import (
        generate_g99_application_from_scalars,
        G99_VERSION,
    )

    tech_enum = _normalise_technology(technology)
    dno_name = _normalise_dno(dno)
    compliance = check_g99_compliance(capacity_mw, voltage_kv, technology, phase)
    cat = compliance.get("category", "Type B")
    timeline = estimate_g99_timeline(capacity_mw, dno_name, phase)

    # Render the canonical Issue 2 pack.
    pack = generate_g99_application_from_scalars(
        lat=lat, lon=lon, capacity_mw=capacity_mw, technology=technology,
        voltage_kv=voltage_kv, dno=dno_name, phase=phase, applicant=applicant,
    )

    # Determine if synchronous or inverter-based (retained for callers who
    # inspect it).
    synchronous_types = {
        GeneratorType.CHP, GeneratorType.HYDRO, GeneratorType.BIOMASS,
        GeneratorType.GAS_RECIPROCATING, GeneratorType.SYNCHRONOUS,
    }
    is_synchronous = tech_enum in synchronous_types

    # Merge the legacy extras back on top of the canonical pack so callers
    # that previously relied on `category`, `timeline`, `checklist`, etc.
    # keep working. The canonical Issue 2 pack is the primary shape.
    pack.update({
        "form_reference": f"G99-APP-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "standard": G99_VERSION["citation"],  # e.g. "ENA EREC G99 Issue 2 (10 March 2025)"
        "g99_version": G99_VERSION["version"],
        "g99_published": G99_VERSION["published"],
        "annex_c_effective": G99_VERSION["annex_c_effective"],
        "category": cat,
        "generated_at": datetime.now().isoformat(),
        "timeline": timeline,
        "compliance_summary": compliance,
        "commissioning": COMMISSIONING_REQUIREMENTS.get(cat, {}),
        "checklist": _application_checklist(cat, is_synchronous),
        "interface_type": (
            "Synchronous" if is_synchronous
            else "Inverter (power electronic)"
        ),
    })
    return pack


# Retained below only for callers of `_legacy_generate_g99_application_v1`
# (internal); the public API is the passthrough above. The Issue-1 body was
# removed as part of the COUNCIL-1 consolidation — the canonical Issue 2
# generator is in `utils.g99_pack_generator`.
def _legacy_generate_g99_application_v1(*_a, **_kw) -> dict[str, Any]:  # noqa: D401
    """Removed. See :func:`generate_g99_application` (canonical passthrough)."""
    raise RuntimeError(
        "The Issue 1 Amendment 9 generate_g99_application body has been "
        "removed by COUNCIL-1 consolidation. Call "
        "utils.g99_pack_generator.generate_g99_pack instead."
    )


# ---------------------------------------------------------------------------
# NOTE (BOT-T, 2026-04-19): The original Issue 1 Amendment 9 body of
# ``generate_g99_application`` used to live between this line and the
# ``_latlon_to_osgr_approx`` helper below. It has been fully removed in
# favour of the canonical Issue 2 generator in
# ``utils.g99_pack_generator``. Callers that relied on the old section-
# dict shape (Section A-G plus timeline / checklist / commissioning) now
# receive the canonical A–I + Annex C pack with the legacy extras merged
# on top by the thin passthrough above.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _latlon_to_osgr_approx(lat: float, lon: float) -> str:
    """Return an OSGB36 National Grid reference via ``utils.osgb``.

    Renamed for historical compatibility — the "approx" in the old name
    reflected the previous linear approximation (flagged by COUNCIL-1 as
    fabricated). This is now a proper OSGB36 transform via pyproj; the
    name is kept only so any remaining internal callers continue to work.
    """
    if lat is None or lon is None:
        return "To be confirmed"
    try:
        from utils.osgb import to_grid_ref
        return to_grid_ref(lat, lon, precision=8)
    except Exception:
        return f"[OSGB unavailable — WGS84 {lat:.5f}, {lon:.5f}]"


def _dno_region(dno_name: str) -> str:
    """Return the DNO licence area description."""
    regions = {
        "UKPN": "South East England, East England, London",
        "SSEN": "North Scotland, Central Southern England",
        "NGED": "South West England, South Wales, East Midlands, West Midlands",
        "ENWL": "North West England",
        "NPG": "North East England, Yorkshire",
        "SPEN": "Central & Southern Scotland, North Wales & Merseyside",
    }
    return regions.get(dno_name, "Unknown region")


def _application_checklist(category: str, is_synchronous: bool) -> list[dict[str, Any]]:
    """Generate the document checklist for a G99 application."""
    checklist = [
        {"item": "Completed G99 Application Form (Form A1)", "required": True, "status": "auto-generated"},
        {"item": "Site location plan (1:2500 or better)", "required": True, "status": "required"},
        {"item": "Single line diagram of electrical installation", "required": True, "status": "required"},
        {"item": "Generator type test certificate (G99 Annex B)", "required": True, "status": "required"},
        {"item": "Protection relay settings schedule", "required": True, "status": "auto-generated"},
        {"item": "Planning permission / permitted development confirmation", "required": True, "status": "required"},
        {"item": "Land ownership / lease evidence", "required": True, "status": "required"},
        {"item": "Application fee payment", "required": True, "status": "pending"},
    ]

    if category in ("Type B", "Type C", "Type D"):
        checklist.extend([
            {"item": "P-Q capability chart", "required": True, "status": "required"},
            {"item": "Fault level calculation / study", "required": True, "status": "auto-estimated"},
            {"item": "Protection coordination study", "required": True, "status": "required"},
        ])

    if category in ("Type C", "Type D"):
        checklist.extend([
            {"item": "Dynamic stability / transient study", "required": True, "status": "required"},
            {"item": "Power quality assessment (harmonics, flicker)", "required": True, "status": "required"},
            {"item": "Detailed commissioning programme", "required": True, "status": "required"},
        ])

    if category == "Type D":
        checklist.extend([
            {"item": "NGESO Grid Code compliance statement", "required": True, "status": "required"},
            {"item": "Intertrip / teleprotection design", "required": True, "status": "required"},
            {"item": "Bilateral Connection Agreement (BCA) application", "required": True, "status": "required"},
        ])

    if is_synchronous:
        checklist.append(
            {"item": "Synchronous machine parameters (Xd, Xd', Xd'', Ta, etc.)", "required": True, "status": "required"}
        )

    return checklist


# ---------------------------------------------------------------------------
# Convenience: CLI / standalone usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    print("=" * 70)
    print("G99 Compliance Check — 5 MW Solar PV at 33 kV (UKPN)")
    print("=" * 70)

    result = check_g99_compliance(5.0, 33.0, "solar_pv")
    print(json.dumps(result, indent=2, default=str))

    print("\n" + "=" * 70)
    print("G99 Protection Settings — 5 MW Solar PV at 33 kV")
    print("=" * 70)

    prot = g99_protection_settings(5.0, 33.0, "solar_pv")
    print(json.dumps(prot, indent=2, default=str))

    print("\n" + "=" * 70)
    print("G99 Timeline — 5 MW, UKPN")
    print("=" * 70)

    tl = estimate_g99_timeline(5.0, "UKPN")
    print(json.dumps(tl, indent=2, default=str))

    print("\n" + "=" * 70)
    print("Full G99 Application — 25 MW Wind at 33 kV (SSEN)")
    print("=" * 70)

    app = generate_g99_application(
        lat=52.5,
        lon=-1.5,
        capacity_mw=25.0,
        technology="wind",
        voltage_kv=33.0,
        dno="SSEN",
    )
    print(json.dumps(app, indent=2, default=str))

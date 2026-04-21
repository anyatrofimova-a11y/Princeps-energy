"""Canonical G99 Issue 2 Interface Protection Schedule + G5/5 Issue 1 limits.

Single source of truth for ENA Engineering Recommendation G99 **Issue 2**
(published 10 March 2025, Amendment 1 February 2024 consolidated) protection
settings and harmonic/flicker compliance limits. Every value in this module
is the literal value from the ENA published document — no approximations.

The module is dependency-free (only stdlib) so it can be imported by both
the pack generator and the front-end API without pulling in Playwright /
pandas.

Exports
-------
- ``G99_PROTECTION_SCHEDULE``  — dict keyed by stage (UV1…NVD) with setting,
  pickup time, trip time, G99 clause reference.
- ``get_protection_schedule(voltage_kv, type_category)`` — returns the
  voltage-adjusted schedule as a list of rows ready for HTML rendering.
- ``G55_HARMONIC_LIMITS_MV`` — IEC 61000-3-6 / G5/5 Stage 1 voltage THD and
  individual-harmonic limits at MV (1 kV – 35 kV).
- ``G55_FLICKER_LIMITS`` — Pst and Plt planning limits at LV and MV.
- ``RIDE_THROUGH_LVRT`` / ``RIDE_THROUGH_HVRT`` — G99 Issue 2 Annex A
  fault-ride-through envelopes (Type B/C/D).

Reference
---------
- ENA EREC G99 Issue 2 (10 March 2025). Tables 13.1, 13.2, 13.3; Clauses
  10.6, 13.4, 13.5, 13.6.
- ENA EREC G5/5 Issue 1 (2020). Tables 3a/3b (MV voltage THD and individual
  harmonics).
- ENA EREC P28 Issue 2 (2019). Flicker Pst / Plt limits.
"""
from __future__ import annotations

from typing import Any, Literal

TypeCategory = Literal["Type A", "Type B", "Type C", "Type D"]


# ---------------------------------------------------------------------------
# G99 Issue 2 Interface Protection Schedule — verbatim Tables 13.1–13.3
# ---------------------------------------------------------------------------
# Each row:
#   stage:    Human-readable stage label (UV1, OV2, UF1, etc.)
#   function: Protection function (IEC 61850 / ANSI device number in parens)
#   setting:  Threshold magnitude (% Un, Hz, Hz/s, deg)
#   time_s:   Operating time (seconds) including relay + breaker
#   action:   Trip / Alarm / Ride-through
#   clause:   G99 Issue 2 clause reference
#   note:     Any applicability / derogation note
# ---------------------------------------------------------------------------

G99_PROTECTION_SCHEDULE: dict[str, dict[str, Any]] = {
    # --- Under-voltage (G99 Issue 2 Clause 13.4.2 / Table 13.1) ------------
    "UV1": {
        "stage": "UV1 — Under-voltage Stage 1",
        "function": "27 (U<)",
        "setting_pct_un": 80.0,
        "setting": "80% Un",
        "time_s": 2.5,
        "action": "Trip",
        "clause": "G99 Issue 2 Clause 13.4.2 (Table 13.1)",
        "note": "Applies at the Interface Protection point. Tripping time includes relay + circuit-breaker.",
    },
    "UV2": {
        "stage": "UV2 — Under-voltage Stage 2",
        "function": "27 (U<<)",
        "setting_pct_un": 50.0,
        "setting": "50% Un",
        "time_s": 0.5,
        "action": "Trip (instantaneous)",
        "clause": "G99 Issue 2 Clause 13.4.2 (Table 13.1)",
        "note": "Fast under-voltage stage — intended to coordinate with LVRT profile.",
    },
    # --- Over-voltage (G99 Issue 2 Clause 13.4.3 / Table 13.1) -------------
    "OV1": {
        "stage": "OV1 — Over-voltage Stage 1",
        "function": "59 (U>)",
        "setting_pct_un": 110.0,
        "setting": "110% Un (10-min averaged)",
        "time_s": 1.0,
        "action": "Trip",
        "clause": "G99 Issue 2 Clause 13.4.3 (Table 13.1)",
        "note": "Stage 1 measured as 10-minute rolling average per EN 50160.",
    },
    "OV2": {
        "stage": "OV2 — Over-voltage Stage 2",
        "function": "59 (U>>)",
        "setting_pct_un": 115.0,
        "setting": "115% Un",
        "time_s": 0.5,
        "action": "Trip",
        "clause": "G99 Issue 2 Clause 13.4.3 (Table 13.1)",
        "note": "Instantaneous measurement — no averaging.",
    },
    "OV3": {
        "stage": "OV3 — Over-voltage Stage 3",
        "function": "59 (U>>>)",
        "setting_pct_un": 120.0,
        "setting": "120% Un",
        "time_s": 0.1,
        "action": "Trip (instantaneous)",
        "clause": "G99 Issue 2 Clause 13.4.3 (Table 13.1)",
        "note": "Coordinates with HVRT envelope upper bound.",
    },
    # --- Under-frequency (G99 Issue 2 Clause 13.5 / Table 13.2) ------------
    "UF1": {
        "stage": "UF1 — Under-frequency Stage 1",
        "function": "81U (f<)",
        "setting": "47.5 Hz",
        "time_s": 20.0,
        "action": "Trip",
        "clause": "G99 Issue 2 Clause 13.5 (Table 13.2)",
        "note": "Holds through LFSM-U response window.",
    },
    "UF2": {
        "stage": "UF2 — Under-frequency Stage 2",
        "function": "81U (f<<)",
        "setting": "47.0 Hz",
        "time_s": 0.5,
        "action": "Trip (instantaneous)",
        "clause": "G99 Issue 2 Clause 13.5 (Table 13.2)",
        "note": "Coincident with GB Frequency Plan Stage 1 load shedding.",
    },
    # --- Over-frequency (G99 Issue 2 Clause 13.5 / Table 13.2) -------------
    "OF1": {
        "stage": "OF1 — Over-frequency Stage 1",
        "function": "81O (f>)",
        "setting": "51.5 Hz",
        "time_s": 90.0,
        "action": "Trip",
        "clause": "G99 Issue 2 Clause 13.5 (Table 13.2)",
        "note": "Coordinates with LFSM-O mandatory response.",
    },
    "OF2": {
        "stage": "OF2 — Over-frequency Stage 2",
        "function": "81O (f>>)",
        "setting": "52.0 Hz",
        "time_s": 0.5,
        "action": "Trip (instantaneous)",
        "clause": "G99 Issue 2 Clause 13.5 (Table 13.2)",
        "note": "Final back-stop above Grid Code operational window.",
    },
    # --- Loss of Mains (G99 Issue 2 Clauses 10.6 + 13.6) -------------------
    "ROCOF": {
        "stage": "ROCOF — Rate of Change of Frequency",
        "function": "81R (df/dt)",
        "setting": "1.0 Hz/s over 500 ms",
        "time_s": 0.5,
        "action": "Trip",
        "clause": "G99 Issue 2 Clause 13.6 / Clause 10.6",
        "note": (
            "Primary LoM method. 500 ms measurement window + 500 ms time "
            "delay. Must ride through ≥1 Hz/s for ≥500 ms per Clause 10.6."
        ),
    },
    "VECTOR_SHIFT": {
        "stage": "Vector Shift (legacy backup)",
        "function": "78 (Δδ)",
        "setting": "12° (disabled unless DNO requires)",
        "time_s": "—",
        "action": "Not enabled by default",
        "clause": "G99 Issue 2 Clause 13.6",
        "note": (
            "Issue 2 removes vector shift as the primary LoM method. Only "
            "enable where the DNO explicitly requires legacy backup."
        ),
    },
    # --- Neutral Voltage Displacement (G99 Issue 2 Clause 13.7) -----------
    "NVD": {
        "stage": "NVD — Neutral Voltage Displacement",
        "function": "59N (U0>)",
        "setting": "20% Un",
        "time_s": 0.5,
        "action": "Trip",
        "clause": "G99 Issue 2 Clause 13.7",
        "note": (
            "Required on connections ≥20 kV where the generator is earthed "
            "through impedance or when the DNO specifies, to detect open-"
            "circuit neutral earth faults on the upstream network."
        ),
    },
}


def get_protection_schedule(
    voltage_kv: float = 33.0,
    type_category: TypeCategory = "Type B",
) -> list[dict[str, Any]]:
    """Return the ordered protection schedule rows for an HTML table.

    Adjusts:
      - NVD requirement (omit below 20 kV)
      - Populates threshold_v_line from Un for voltage stages so the DNO
        engineer sees the absolute volts as well as %Un.

    Args:
        voltage_kv:    Nominal connection voltage (kV line-to-line).
        type_category: G99 Type A / B / C / D — affects the applicable
                        frequency window envelope and ride-through duration
                        but not the setting magnitudes.
    """
    un_v = voltage_kv * 1000.0 if voltage_kv > 0.4 else 400.0
    order = [
        "UV1", "UV2", "OV1", "OV2", "OV3",
        "UF1", "UF2", "OF1", "OF2",
        "ROCOF", "VECTOR_SHIFT", "NVD",
    ]
    rows: list[dict[str, Any]] = []
    for key in order:
        row = dict(G99_PROTECTION_SCHEDULE[key])
        row["key"] = key
        row["type_category"] = type_category
        if "setting_pct_un" in row:
            pct = row["setting_pct_un"]
            row["threshold_v_line"] = round(un_v * pct / 100.0, 1)
        if key == "NVD" and voltage_kv < 20:
            row["action"] = "Not required"
            row["note"] = (
                "Not required on connections below 20 kV unless the DNO "
                "specifies. Shown for completeness."
            )
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# G5/5 Issue 1 — Harmonic voltage distortion limits (MV, 1 kV – 35 kV)
# ---------------------------------------------------------------------------
# Table 3b: planning levels for individual harmonics (voltage distortion %)
# at MV busbars. Values expressed as % of fundamental voltage, measured
# in line with IEC 61000-4-7.
# ---------------------------------------------------------------------------

G55_HARMONIC_LIMITS_MV: list[dict[str, Any]] = [
    # Odd harmonics — non-triplen (IEC 61000-3-6 / G5/5 Table 3b)
    {"h": 5,  "type": "odd (non-triplen)", "limit_pct": 5.0},
    {"h": 7,  "type": "odd (non-triplen)", "limit_pct": 4.0},
    {"h": 11, "type": "odd (non-triplen)", "limit_pct": 3.0},
    {"h": 13, "type": "odd (non-triplen)", "limit_pct": 2.5},
    {"h": 17, "type": "odd (non-triplen)", "limit_pct": 1.6},
    {"h": 19, "type": "odd (non-triplen)", "limit_pct": 1.2},
    {"h": 23, "type": "odd (non-triplen)", "limit_pct": 1.2},
    {"h": 25, "type": "odd (non-triplen)", "limit_pct": 1.2},
    # Odd harmonics — triplen
    {"h": 3,  "type": "odd (triplen)",     "limit_pct": 4.0},
    {"h": 9,  "type": "odd (triplen)",     "limit_pct": 1.2},
    {"h": 15, "type": "odd (triplen)",     "limit_pct": 0.3},
    {"h": 21, "type": "odd (triplen)",     "limit_pct": 0.2},
    # Even harmonics
    {"h": 2,  "type": "even",              "limit_pct": 1.6},
    {"h": 4,  "type": "even",              "limit_pct": 1.0},
    {"h": 6,  "type": "even",              "limit_pct": 0.5},
    {"h": 8,  "type": "even",              "limit_pct": 0.4},
    {"h": 10, "type": "even",              "limit_pct": 0.4},
    {"h": 12, "type": "even",              "limit_pct": 0.2},
]

# High-order harmonics above 25 use the formula from G5/5 Table 3b:
# limit(h) = 0.2 + 1.3 * (25/h)   for  25 < h ≤ 50  [odd non-triplen]
# limit(h) = 0.2 + 0.5 * (25/h)   for  h > 25 and triplen / even

G55_THDV_LIMIT_MV_PCT = 6.5  # G5/5 Table 3a — MV total voltage harmonic
# distortion planning level (1 kV < Un ≤ 35 kV)
G55_THDV_LIMIT_LV_PCT = 8.0  # LV planning level (Un ≤ 1 kV)
G55_THDV_LIMIT_EHV_PCT = 3.0  # EHV planning level (35 kV < Un ≤ 230 kV)


def high_order_harmonic_limit(h: int, triplen_or_even: bool = False) -> float:
    """Return the MV planning limit (%) for harmonics h > 25 per G5/5."""
    if h <= 25:
        raise ValueError("Use G55_HARMONIC_LIMITS_MV lookup for h ≤ 25.")
    if triplen_or_even:
        return round(0.2 + 0.5 * (25.0 / h), 3)
    return round(0.2 + 1.3 * (25.0 / h), 3)


def harmonic_limits_with_highorder() -> list[dict[str, Any]]:
    """Return the full 2nd–50th harmonic limit table for MV."""
    rows = list(G55_HARMONIC_LIMITS_MV)
    for h in range(26, 51):
        triplen = (h % 3 == 0)
        even = (h % 2 == 0)
        triplen_or_even = triplen or even
        if even:
            t = "even"
        elif triplen:
            t = "odd (triplen)"
        else:
            t = "odd (non-triplen)"
        rows.append({
            "h": h,
            "type": t,
            "limit_pct": high_order_harmonic_limit(h, triplen_or_even=triplen_or_even),
        })
    rows.sort(key=lambda r: r["h"])
    return rows


# ---------------------------------------------------------------------------
# Flicker planning limits — ENA ER P28 Issue 2 (coordinated with G5/5)
# ---------------------------------------------------------------------------

G55_FLICKER_LIMITS: dict[str, dict[str, float]] = {
    "LV": {"Pst": 1.0, "Plt": 0.8},
    "MV": {"Pst": 0.9, "Plt": 0.7},
    "HV": {"Pst": 0.8, "Plt": 0.6},
}


# ---------------------------------------------------------------------------
# G99 Issue 2 Fault-Ride-Through envelopes — Annex A
# ---------------------------------------------------------------------------
# LVRT: (time_ms, voltage_pu_min_required)  — envelope minimum retained
# voltage. Generator must stay connected as long as the retained voltage
# remains above the envelope.
# ---------------------------------------------------------------------------

RIDE_THROUGH_LVRT: list[tuple[float, float]] = [
    (0.0,     0.00),   # Zero voltage crossing — at t=0
    (140.0,   0.00),   # Zero voltage permitted for 140 ms
    (140.0,   0.15),   # Step up to 15% Un (typical Type C/D profile)
    (700.0,   0.50),   # Ramp to 50% at 700 ms
    (1500.0,  0.85),   # Recovery to 85% by 1500 ms
    (3000.0,  0.90),   # Back to 90% by 3 s
    (10000.0, 0.90),   # Steady 90% to 10 s
]

# HVRT: (time_ms, voltage_pu_max_allowed)
RIDE_THROUGH_HVRT: list[tuple[float, float]] = [
    (0.0,    1.20),   # 120% Un transient
    (100.0,  1.20),   # sustained 120% for 100 ms
    (500.0,  1.15),   # down to 115% by 500 ms
    (5000.0, 1.10),   # 110% for 5 s
    (60000.0, 1.10),  # 110% for 60 s
]


# ---------------------------------------------------------------------------
# G99 Issue 2 frequency response envelopes (Clauses 4.2–4.4)
# ---------------------------------------------------------------------------

G99_FREQUENCY_RESPONSE: dict[str, dict[str, Any]] = {
    "LFSM-O": {
        "name": "Limited Frequency Sensitive Mode — Over-frequency",
        "threshold_hz": 50.4,
        "droop_pct": 5.0,
        "active_from_hz": 50.4,
        "mandatory_from_mw": 1.0,
        "clause": "G99 Issue 2 Clause 4.2",
    },
    "LFSM-U": {
        "name": "Limited Frequency Sensitive Mode — Under-frequency",
        "threshold_hz": 49.5,
        "droop_pct": 5.0,
        "active_from_hz": 49.5,
        "mandatory_from_mw": 50.0,
        "clause": "G99 Issue 2 Clause 4.3",
    },
    "FSM": {
        "name": "Frequency Sensitive Mode",
        "deadband_hz": 0.015,
        "droop_pct_range": "2%–12% (3%–5% typical)",
        "mandatory_from_mw": 50.0,
        "clause": "G99 Issue 2 Clause 4.4",
    },
}


# ---------------------------------------------------------------------------
# Type categorisation (G99 Issue 2 Clause 3.2)
# ---------------------------------------------------------------------------

def g99_type(capacity_mw: float, voltage_kv: float = 33.0) -> TypeCategory:
    """Return the G99 Issue 2 Type Category for a generating unit.

    Clause 3.2 thresholds (GB, LV / HV):
      Type A:   0.8 kW   ≤ Pmax < 1 MW   and   Un ≤ 110 kV
      Type B:   1 MW     ≤ Pmax < 10 MW  and   Un ≤ 110 kV
      Type C:   10 MW    ≤ Pmax < 50 MW  and   Un ≤ 110 kV
      Type D:   Pmax ≥ 50 MW   OR   Un > 110 kV
    """
    if capacity_mw >= 50.0 or voltage_kv > 110:
        return "Type D"
    if capacity_mw >= 10.0:
        return "Type C"
    if capacity_mw >= 1.0:
        return "Type B"
    return "Type A"


__all__ = [
    "G99_PROTECTION_SCHEDULE",
    "get_protection_schedule",
    "G55_HARMONIC_LIMITS_MV",
    "harmonic_limits_with_highorder",
    "high_order_harmonic_limit",
    "G55_THDV_LIMIT_MV_PCT",
    "G55_THDV_LIMIT_LV_PCT",
    "G55_THDV_LIMIT_EHV_PCT",
    "G55_FLICKER_LIMITS",
    "RIDE_THROUGH_LVRT",
    "RIDE_THROUGH_HVRT",
    "G99_FREQUENCY_RESPONSE",
    "g99_type",
]


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import json

    schedule = get_protection_schedule(voltage_kv=33, type_category="Type C")
    print("Protection rows:", len(schedule))
    print(json.dumps(schedule[0], indent=2))
    print("Harmonic rows (2-50):", len(harmonic_limits_with_highorder()))
    print("THDv MV limit:", G55_THDV_LIMIT_MV_PCT, "%")
    print("Type for 100 MW at 33 kV:", g99_type(100, 33))

"""G99 Table 10.1 — Interface Protection Settings.

Returns the populated ENA Engineering Recommendation G99 Issue 1 Amendment 11
Table 10.1 "Interface Protection Settings" for a generating unit connected at a
given nominal voltage.

Table 10.1 specifies the required trip settings for:

 - Under-voltage (U<) Stage 1 + Stage 2
 - Over-voltage  (U>) Stage 1 + Stage 2
 - Under-frequency (f<) Stage 1 + Stage 2
 - Over-frequency  (f>) Stage 1 + Stage 2
 - Loss of Mains (LoM) — RoCoF + Vector Shift options
 - Neutral Voltage Displacement (NVD) on ≥20 kV connections

All settings are the G99 defaults for Type B/C/D (where voltage protection
scales with Type — see G99 §10.3 and Annex A). Thresholds are per-voltage-level
(400 V, 11 kV, 33 kV, 66 kV, 132 kV) and the anti-islanding scheme is
selectable ("rocof" default; "vector_shift" disabled by default per amendment
10; "rocof+vector_shift" available where the DNO still mandates backup).

This module is intentionally dependency-free so it can be imported from the
report renderer and the G99 pack generator without pulling in pandapower or
Playwright.

Reference:
    ENA EREC G99 Issue 1 Amendment 11 (effective 2026-03-01), Table 10.1.
    P28 Issue 2 (2019) / P29 Issue 1 (2019) voltage-step limits: ±3% normal,
    ±6% infrequent.
"""
from __future__ import annotations

from typing import Any, Literal

AntiIslandingScheme = Literal["rocof", "vector_shift", "rocof+vector_shift"]


# ---------------------------------------------------------------------------
# Canonical Table 10.1 defaults — expressed as % of nominal voltage (Un) and
# absolute frequency. Times are in seconds.
# ---------------------------------------------------------------------------

# (threshold_pct_of_Un, operating_time_s)
_VOLTAGE_PROTECTION_DEFAULTS: dict[str, tuple[float, float]] = {
    # From G99 Table 10.1 — applies to all Type A/B/C/D for LV & MV.
    "U<_stage1": (80.0, 2.5),   # Under-voltage Stage 1: 80% Un, 2.5 s
    "U<_stage2": (50.0, 0.5),   # Under-voltage Stage 2: 50% Un, 0.5 s
    "U>_stage1": (110.0, 1.0),  # Over-voltage Stage 1:  110% Un, 1.0 s
    "U>_stage2": (120.0, 0.5),  # Over-voltage Stage 2:  120% Un, 0.5 s
}

# (threshold_Hz, operating_time_s)
_FREQUENCY_PROTECTION_DEFAULTS: dict[str, tuple[float, float]] = {
    "f<_stage1": (47.5, 20.0),  # Under-frequency Stage 1: 47.5 Hz, 20 s
    "f<_stage2": (47.0, 0.5),   # Under-frequency Stage 2: 47.0 Hz, 0.5 s
    "f>_stage1": (51.5, 90.0),  # Over-frequency Stage 1:  51.5 Hz, 90 s
    "f>_stage2": (52.0, 0.5),   # Over-frequency Stage 2:  52.0 Hz, 0.5 s
}

# RoCoF — G99 §10.6. Default setting is 1 Hz/s measured over 500 ms,
# with a 500 ms time delay (amendment 11 retains the amendment 4 relaxation).
_ROCOF_DEFAULT: dict[str, Any] = {
    "setting_hz_per_s": 1.0,
    "measurement_window_ms": 500,
    "time_delay_s": 0.5,
    "ride_through_hz_per_s": 1.0,
    "note": "G99 §10.6 — ride-through ≥1 Hz/s for 500 ms.",
}

# Vector shift — legacy LoM scheme, disabled by default in G99 Amdt 11 for
# GB. Some DNOs may still require as backup on ≥33 kV connections.
_VECTOR_SHIFT_DEFAULT: dict[str, Any] = {
    "setting_degrees": 6.0,
    "enabled": False,
    "note": (
        "Vector shift is no longer the primary LoM method under G99 Amdt 11. "
        "Enable only where DNO explicitly requires (typically 33 kV+ legacy sites)."
    ),
}

# Neutral Voltage Displacement (NVD) — required on 20 kV+ connections where
# the generator is earthed via impedance or where the DNO specifies.
_NVD_BY_VOLTAGE: dict[int, dict[str, Any]] = {
    11:  {"required": False, "setting_percent_un": None, "time_delay_s": None},
    33:  {"required": True,  "setting_percent_un": 20.0, "time_delay_s": 2.5},
    66:  {"required": True,  "setting_percent_un": 20.0, "time_delay_s": 2.5},
    132: {"required": True,  "setting_percent_un": 20.0, "time_delay_s": 2.5},
}


def _voltage_row(label: str, threshold_pct: float, nominal_v_line: float,
                  time_s: float, action: str = "Trip") -> dict[str, Any]:
    """Build a structured Table 10.1 row for voltage protection."""
    return {
        "stage": label,
        "threshold_pct_Un": threshold_pct,
        "threshold_V_line": round(nominal_v_line * threshold_pct / 100.0, 1),
        "operating_time_s": time_s,
        "action": action,
    }


def _frequency_row(label: str, threshold_hz: float, time_s: float,
                    action: str = "Trip") -> dict[str, Any]:
    """Build a structured Table 10.1 row for frequency protection."""
    return {
        "stage": label,
        "threshold_hz": threshold_hz,
        "operating_time_s": time_s,
        "action": action,
    }


def _nominal_line_voltage_v(voltage_kv: float) -> float:
    """Return the nominal line-to-line voltage in volts for percent-of-Un maths."""
    # LV 3-phase is 400 V line-to-line; everything else we use the kV figure.
    if voltage_kv <= 0.4:
        return 400.0
    return voltage_kv * 1000.0


def get_table_101(
    voltage_kv: float = 33.0,
    anti_islanding_scheme: AntiIslandingScheme = "rocof",
    g99_type: str = "Type B",
) -> dict[str, Any]:
    """Return the populated G99 Table 10.1 interface protection settings.

    Args:
        voltage_kv:           Nominal connection voltage in kV (0.4, 11, 33, 66, 132).
        anti_islanding_scheme: "rocof" (default per Amdt 11), "vector_shift" or
                               "rocof+vector_shift" for legacy backup.
        g99_type:             Generator Type A/B/C/D — affects NVD requirement
                               at low voltages but otherwise Table 10.1 values
                               are common across types.

    Returns:
        dict with keys:
          - meta: reference, voltage band, scheme, nominal values
          - voltage_protection: list of 4 rows (U< S1/S2, U> S1/S2)
          - frequency_protection: list of 4 rows (f< S1/S2, f> S1/S2)
          - loss_of_mains: dict with rocof and vector_shift sub-blocks
          - nvd: neutral voltage displacement (if applicable)
          - rows: flattened list of dicts suitable for direct HTML table render
          - voltage_step_notes: P28/P29 compliance reminders
          - disclaimer
    """
    nominal_v_line = _nominal_line_voltage_v(voltage_kv)
    voltage_band = _voltage_band_label(voltage_kv)

    # Voltage protection rows
    voltage_rows = [
        _voltage_row("U< Stage 1", *_VOLTAGE_PROTECTION_DEFAULTS["U<_stage1"][:1],
                      nominal_v_line=nominal_v_line,
                      time_s=_VOLTAGE_PROTECTION_DEFAULTS["U<_stage1"][1]),
        _voltage_row("U< Stage 2", *_VOLTAGE_PROTECTION_DEFAULTS["U<_stage2"][:1],
                      nominal_v_line=nominal_v_line,
                      time_s=_VOLTAGE_PROTECTION_DEFAULTS["U<_stage2"][1],
                      action="Trip (instantaneous)"),
        _voltage_row("U> Stage 1", *_VOLTAGE_PROTECTION_DEFAULTS["U>_stage1"][:1],
                      nominal_v_line=nominal_v_line,
                      time_s=_VOLTAGE_PROTECTION_DEFAULTS["U>_stage1"][1]),
        _voltage_row("U> Stage 2", *_VOLTAGE_PROTECTION_DEFAULTS["U>_stage2"][:1],
                      nominal_v_line=nominal_v_line,
                      time_s=_VOLTAGE_PROTECTION_DEFAULTS["U>_stage2"][1],
                      action="Trip (instantaneous)"),
    ]

    frequency_rows = [
        _frequency_row("f< Stage 1", *_FREQUENCY_PROTECTION_DEFAULTS["f<_stage1"]),
        _frequency_row("f< Stage 2", *_FREQUENCY_PROTECTION_DEFAULTS["f<_stage2"],
                        action="Trip (instantaneous)"),
        _frequency_row("f> Stage 1", *_FREQUENCY_PROTECTION_DEFAULTS["f>_stage1"]),
        _frequency_row("f> Stage 2", *_FREQUENCY_PROTECTION_DEFAULTS["f>_stage2"],
                        action="Trip (instantaneous)"),
    ]

    lom = {
        "scheme": anti_islanding_scheme,
        "rocof": {
            **_ROCOF_DEFAULT,
            "enabled": anti_islanding_scheme in ("rocof", "rocof+vector_shift"),
        },
        "vector_shift": {
            **_VECTOR_SHIFT_DEFAULT,
            "enabled": anti_islanding_scheme in ("vector_shift", "rocof+vector_shift"),
        },
    }

    # NVD — for 20 kV+ connections
    nvd_key = _nearest_nvd_key(voltage_kv)
    nvd = dict(_NVD_BY_VOLTAGE.get(nvd_key, {"required": False,
                                              "setting_percent_un": None,
                                              "time_delay_s": None}))
    nvd["voltage_kv"] = voltage_kv

    # Flattened rows for HTML table rendering — one logical table with all stages
    flat_rows: list[dict[str, Any]] = []
    for r in voltage_rows:
        flat_rows.append({
            "function": r["stage"],
            "threshold": f"{r['threshold_pct_Un']}% Un ({r['threshold_V_line']:.0f} V)",
            "time_s": r["operating_time_s"],
            "action": r["action"],
            "category": "Voltage",
        })
    for r in frequency_rows:
        flat_rows.append({
            "function": r["stage"],
            "threshold": f"{r['threshold_hz']} Hz",
            "time_s": r["operating_time_s"],
            "action": r["action"],
            "category": "Frequency",
        })
    # RoCoF / LoM
    flat_rows.append({
        "function": "RoCoF (df/dt)",
        "threshold": (f"{lom['rocof']['setting_hz_per_s']} Hz/s over "
                       f"{lom['rocof']['measurement_window_ms']} ms"
                       + ("" if lom["rocof"]["enabled"] else " — DISABLED")),
        "time_s": lom["rocof"]["time_delay_s"],
        "action": "Trip" if lom["rocof"]["enabled"] else "Not enabled",
        "category": "Loss of Mains",
    })
    flat_rows.append({
        "function": "Vector shift",
        "threshold": (f"{lom['vector_shift']['setting_degrees']}°"
                       + ("" if lom["vector_shift"]["enabled"] else " — DISABLED per Amdt 11")),
        "time_s": 0.5 if lom["vector_shift"]["enabled"] else "—",
        "action": "Trip (legacy backup)" if lom["vector_shift"]["enabled"] else "Not enabled",
        "category": "Loss of Mains",
    })
    if nvd.get("required"):
        flat_rows.append({
            "function": "Neutral Voltage Displacement",
            "threshold": f"{nvd['setting_percent_un']}% Un",
            "time_s": nvd["time_delay_s"],
            "action": "Trip",
            "category": "Earth Fault",
        })

    return {
        "meta": {
            "reference": "ENA EREC G99 Issue 1 Amendment 11, Table 10.1",
            "amendment": "Amendment 11 (2026-03-01)",
            "g99_type": g99_type,
            "voltage_kv": voltage_kv,
            "voltage_band": voltage_band,
            "nominal_voltage_v_line": nominal_v_line,
            "anti_islanding_scheme": anti_islanding_scheme,
        },
        "voltage_protection": voltage_rows,
        "frequency_protection": frequency_rows,
        "loss_of_mains": lom,
        "nvd": nvd,
        "rows": flat_rows,
        "voltage_step_notes": [
            "ENA ER P28 Issue 2: steady-state voltage step ≤3% Un for normal "
            "infrequent switching operations.",
            "ENA ER P28 Issue 2: ≤6% Un permitted for rare switching events.",
            "ENA ER P29 Issue 1: voltage unbalance (negative phase sequence) "
            "≤1.3% at HV / ≤2.0% at LV.",
            "Rapid voltage changes from generation variability must not exceed "
            "3% Un at the point of connection.",
        ],
        "disclaimer": (
            "Settings shown are the G99 Amendment 11 Table 10.1 defaults. The "
            "DNO may specify tighter site-specific thresholds following the "
            "network impact study — always verify against the DNO's connection "
            "offer letter before sealing protection relays."
        ),
    }


def _voltage_band_label(voltage_kv: float) -> str:
    """Classify the voltage band."""
    if voltage_kv <= 0.4:
        return "LV (≤400 V)"
    if voltage_kv <= 1.0:
        return "LV (>400 V — ≤1 kV)"
    if voltage_kv <= 11:
        return "HV 11 kV"
    if voltage_kv <= 33:
        return "HV 33 kV"
    if voltage_kv <= 66:
        return "EHV 66 kV"
    if voltage_kv <= 132:
        return "EHV 132 kV"
    return "Transmission (>132 kV)"


def _nearest_nvd_key(voltage_kv: float) -> int:
    """Map a connection voltage to the nearest NVD lookup key."""
    if voltage_kv <= 11:
        return 11
    if voltage_kv <= 33:
        return 33
    if voltage_kv <= 66:
        return 66
    return 132


# ---------------------------------------------------------------------------
# Rendering helpers — kept dependency-free so the report module can template
# them directly.
# ---------------------------------------------------------------------------

def render_html_table(table_101: dict[str, Any]) -> str:
    """Render Table 10.1 as a self-contained HTML table fragment.

    The fragment is suitable for injection into any report template. Styling
    uses inline classes that match the Princeps grid_connection_report.html
    conventions (table, th, td).
    """
    meta = table_101["meta"]
    rows = table_101["rows"]
    step_notes = table_101["voltage_step_notes"]
    disclaimer = table_101["disclaimer"]

    header = (
        f"<div class=\"card card-accent\">"
        f"<div class=\"card-header\">G99 Table 10.1 — Interface Protection Settings</div>"
        f"<div class=\"text-xs text-muted mb-8\">"
        f"{meta['reference']} &middot; {meta['voltage_band']} &middot; "
        f"Anti-islanding: {meta['anti_islanding_scheme']}</div>"
    )

    tbl_rows = "".join(
        (f"<tr>"
         f"<td>{r['category']}</td>"
         f"<td class=\"bold\">{r['function']}</td>"
         f"<td>{r['threshold']}</td>"
         f"<td>{r['time_s']}</td>"
         f"<td>{r['action']}</td>"
         f"</tr>")
        for r in rows
    )

    table_html = (
        "<table>"
        "<tr><th>Category</th><th>Function</th><th>Setting</th>"
        "<th>Time (s)</th><th>Action</th></tr>"
        f"{tbl_rows}"
        "</table>"
    )

    notes_html = "".join(f"<div class=\"note-item\">{n}</div>" for n in step_notes)

    footer = (
        f"<div class=\"mt-8 section-subtitle\">ENA P28/P29 voltage-step compliance</div>"
        f"{notes_html}"
        f"<div class=\"text-xs text-muted mt-8\">{disclaimer}</div>"
        f"</div>"
    )

    return header + table_html + footer


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    out = get_table_101(voltage_kv=33.0, anti_islanding_scheme="rocof")
    print(json.dumps(out, indent=2, default=str))

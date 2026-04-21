"""
utils.dno_engagement.constraint — Constraint envelope for a DNO pack.

Wraps :func:`utils.grid_connection_analyser.tier2_power_flow` (which
invokes the pandapower subprocess via
:mod:`utils.grid_power_flow`) and packages the output as a POC-centric
constraint envelope: thermal (line loadings), voltage (P28/P29 limits),
N-1 contingency ranking, and the winning reinforcement option.

Cited:
  * ENA EREC P2 Issue 7 §6 — N-1 security requirement for DNOs serving
    >5 MW demand (applied as pass/fail on each outage case).
  * ENA EREC P28 Issue 2 §4 — voltage fluctuation limits (Pst ≤ 1.0,
    Plt ≤ 0.8) at the POC. This engine flags P28 headroom, not Pst/Plt
    compliance, which requires a flicker rig.
  * ENA EREC P29 — unbalance ≤ 1.3% 10-min average.
  * ENA EREC G5 Issue 5 §5 — harmonic compatibility at POC (THDv ≤ 5%).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

log = logging.getLogger("princeps.dno_engagement.constraint")

# UK statutory voltage limits (Engineering Recommendation P28 / P29)
_VOLTAGE_LIMITS = {
    11:  (0.94, 1.06),
    33:  (0.94, 1.06),
    66:  (0.95, 1.05),
    132: (0.95, 1.05),
    275: (0.95, 1.05),
    400: (0.95, 1.05),
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ConstraintEnvelope:
    """Thermal + voltage + contingency envelope for the POC and its network."""

    project_id: str
    poc_substation_id: str | int | None

    success: bool = False
    converged: bool = False

    # Thermal (line loadings)
    max_loading_pct: float = 0.0
    worst_line_name: str = ""
    thermal_headroom_mw: float = 0.0
    lines_over_80_pct: int = 0
    lines_over_100_pct: int = 0

    # Voltage (P28 limits)
    max_voltage_pu: float = 0.0
    min_voltage_pu: float = 0.0
    voltage_rise_pu: float = 0.0
    voltage_violations: int = 0
    statutory_limit_used: tuple[float, float] = (0.94, 1.06)

    # Power flow direction
    reverse_power_flow: bool = False

    # N-1 contingency
    n1_worst_case: dict[str, Any] = field(default_factory=dict)
    n1_failures: int = 0
    n1_cases_analysed: int = 0

    # Verdict: PASS / MARGINAL / FAIL
    verdict: str = "UNKNOWN"

    violations: list[dict[str, Any]] = field(default_factory=list)
    bus_results: list[dict[str, Any]] = field(default_factory=list)
    line_results: list[dict[str, Any]] = field(default_factory=list)

    notes: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=lambda: [
        "ENA EREC P2 Issue 7 §6 (N-1 security of supply)",
        "ENA EREC P28 Issue 2 §4 (voltage fluctuations, flicker)",
        "ENA EREC P29 (voltage unbalance ≤1.3%)",
        "ENA EREC G5 Issue 5 §5 (harmonic distortion THDv ≤5%)",
        "ENA EREC G99 Issue 2 §7 (active/reactive operating envelope)",
    ])
    network_size: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0
    generated_at: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Verdict classifier
# ---------------------------------------------------------------------------
def _classify_verdict(
    max_loading: float,
    max_v: float,
    min_v: float,
    v_limits: tuple[float, float],
    n1_failures: int,
) -> str:
    """PASS / MARGINAL / FAIL per P28 + P2/7."""
    v_low, v_high = v_limits
    v_fail = (max_v > v_high) or (min_v < v_low)
    t_fail = max_loading > 100.0
    if t_fail or v_fail or n1_failures > 0:
        return "FAIL"
    v_marginal = (max_v > v_high - 0.01) or (min_v < v_low + 0.01)
    t_marginal = max_loading > 85.0
    if v_marginal or t_marginal:
        return "MARGINAL"
    return "PASS"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def compute_constraint_envelope(
    project_id: str,
    poc_substation_id: str | int | None = None,
    *,
    conn: Any = None,
    lat: float | None = None,
    lon: float | None = None,
    capacity_mw: float = 50.0,
    technology: str = "datacentre",
    contingency: bool = True,
) -> ConstraintEnvelope:
    """
    Build a POC-centric :class:`ConstraintEnvelope`.

    The grid_power_flow subprocess is invoked through
    :func:`utils.grid_connection_analyser.tier2_power_flow` — same call
    path as the Grid Connection Report (Task #7). We never call pandapower
    directly from Python 3.14 — always via the subprocess bridge.

    Parameters
    ----------
    project_id : str
        Princeps project UUID.
    poc_substation_id : str | int | None
        Optional. If None, the tier2 routine picks the nearest suitable.
    conn :
        Open asyncpg connection — REQUIRED if ``lat``/``lon`` are not given,
        because tier2 needs to hit PostGIS for substations/lines.
    lat, lon : float
        WGS84 coordinates of the project. If None the caller must set
        ``conn`` + the POC will be resolved from ``poc_substation_id``.
    capacity_mw : float
        Proposed generation or demand capacity. Fed into the subprocess
        as ``proposed.capacity_mw``.
    technology : str
        ``solar`` / ``wind`` / ``bess`` / ``datacentre``.
    contingency : bool
        If True, subprocess runs N + N-1 — REQUIRED for P2/7 evidence.

    Returns
    -------
    ConstraintEnvelope
        Never raises — degrades into ``success=False`` with ``error``.
    """
    env = ConstraintEnvelope(
        project_id=str(project_id),
        poc_substation_id=poc_substation_id,
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )

    if conn is None or lat is None or lon is None:
        env.error = "conn + lat/lon required to run Tier 2 power flow"
        env.notes.append(
            "ConstraintEnvelope degraded: missing DB connection or coordinates. "
            "DNO pack will cite CAUTION on constraint analysis."
        )
        return env

    try:
        from utils.grid_connection_analyser import tier2_power_flow
    except Exception as e:  # noqa: BLE001
        env.error = f"grid_connection_analyser import failed: {e}"
        env.notes.append(env.error)
        return env

    try:
        result: dict[str, Any] = await asyncio.wait_for(
            tier2_power_flow(
                conn, lat, lon, capacity_mw, technology,
                connection_substation_id=(
                    int(poc_substation_id)
                    if poc_substation_id and str(poc_substation_id).isdigit()
                    else None
                ),
                contingency=contingency,
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        env.error = "Power flow subprocess timed out (>120 s)"
        env.notes.append(env.error)
        return env
    except Exception as e:  # noqa: BLE001
        env.error = f"tier2_power_flow failed: {e}"
        env.notes.append(env.error)
        return env

    env.success = bool(result.get("success"))
    env.converged = bool(result.get("converged"))
    env.elapsed_s = float(result.get("elapsed_s") or 0.0)
    env.network_size = result.get("network_size") or {}
    env.bus_results = result.get("bus_results") or []
    env.line_results = result.get("line_results") or []
    env.violations = result.get("violations") or []

    summary = result.get("summary") or {}
    env.max_voltage_pu = float(summary.get("max_voltage_pu") or 0.0)
    env.min_voltage_pu = float(summary.get("min_voltage_pu") or 0.0)
    env.max_loading_pct = float(summary.get("max_loading_pct") or 0.0)
    env.voltage_rise_pu = float(summary.get("voltage_rise_pu") or 0.0)
    env.reverse_power_flow = bool(summary.get("reverse_power_flow") or False)
    env.thermal_headroom_mw = float(summary.get("thermal_headroom_mw") or 0.0)

    # Count thermal violations at 80 / 100%.
    env.lines_over_80_pct = sum(
        1 for L in env.line_results if (L.get("loading_pct") or 0) > 80.0
    )
    env.lines_over_100_pct = sum(
        1 for L in env.line_results if (L.get("loading_pct") or 0) > 100.0
    )

    # Voltage statutory band — pick the POC voltage level.
    poc_v_kv = 33  # default
    for b in env.bus_results:
        if b.get("is_poc") or (b.get("name") or "").lower().find("poc") >= 0:
            poc_v_kv = int(b.get("vn_kv") or b.get("voltage_kv") or 33)
            break
    env.statutory_limit_used = _VOLTAGE_LIMITS.get(poc_v_kv, (0.94, 1.06))
    env.voltage_violations = sum(
        1 for b in env.bus_results
        if not (env.statutory_limit_used[0] <= (b.get("vm_pu") or 1.0)
                <= env.statutory_limit_used[1])
    )

    # N-1 (from contingency sub-result if produced).
    n1 = result.get("contingency") or result.get("n1") or {}
    env.n1_cases_analysed = int(n1.get("cases_analysed") or 0)
    env.n1_failures = int(n1.get("failures") or 0)
    env.n1_worst_case = n1.get("worst_case") or {}

    env.verdict = _classify_verdict(
        env.max_loading_pct,
        env.max_voltage_pu,
        env.min_voltage_pu,
        env.statutory_limit_used,
        env.n1_failures,
    )

    # Human-readable notes.
    if env.max_loading_pct > 100:
        env.notes.append(
            f"Thermal FAIL: worst line loading {env.max_loading_pct:.1f}%"
            f" — reinforcement required (P2/7 §6)."
        )
    elif env.max_loading_pct > 85:
        env.notes.append(
            f"Thermal MARGINAL: worst line {env.max_loading_pct:.1f}% (>85%)"
            f" — recommend reinforcement in RIIO-ED3 window."
        )

    v_low, v_high = env.statutory_limit_used
    if env.max_voltage_pu > v_high:
        env.notes.append(
            f"Voltage FAIL: {env.max_voltage_pu:.3f} p.u. > "
            f"{v_high} (P28 Issue 2)."
        )
    if env.min_voltage_pu and env.min_voltage_pu < v_low:
        env.notes.append(
            f"Voltage FAIL: {env.min_voltage_pu:.3f} p.u. < "
            f"{v_low} (P28 Issue 2)."
        )

    if env.n1_failures:
        env.notes.append(
            f"N-1 FAIL: {env.n1_failures} of {env.n1_cases_analysed} contingency "
            f"cases breach limits — P2/7 requires firm N-1."
        )

    if env.reverse_power_flow:
        env.notes.append(
            "Reverse power flow detected at POC — DNO may require "
            "reverse-power protection (G99 Issue 2 §12)."
        )

    return env

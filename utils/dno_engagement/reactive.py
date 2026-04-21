"""
utils.dno_engagement.reactive — reactive power offer for the DNO pack.

Generates a Q(V) curve, STATCOM / grid-forming reactive envelope,
overnight reactive-import schedule, and voltage droop slope.

Cited:
  * ENA EREC G99 Issue 2 §9.3 — Q(V) control & active/reactive priority
    (Type B / C / D inverters shall provide ±0.95 PF at rated active).
  * ENA EREC P28 Issue 2 §5 — reactive capability that keeps Pst ≤ 1 at POC.
  * ENA EREC P29 — balanced reactive injection.
  * Distribution Code DPC4.5 — reactive power ancillary service offer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

# Default droop slope (p.u. Q per p.u. V) per G99 Issue 2 §9.3.4 — 4% is
# the canonical starting point; DNO can request 2-8%.
_DEFAULT_DROOP_SLOPE = 4.0

# Q / P ratios — what fraction of apparent power capacity is available
# for reactive by technology class. Values taken from:
#   - Solar: G99 §9.3.3 — ±0.95 PF at 100% Pmax → |Q| ≤ 0.329 × Pmax.
#   - Wind: G99 §10 — ±0.95 PF similar.
#   - BESS: higher — 4-quadrant inverters typically ±0.9 PF → |Q| ≤ 0.484.
#   - DC: on-site low-voltage AHF delivers ±0.2 Pmax without STATCOM.
_Q_FRACTION_BY_TECH = {
    "solar":      0.329,
    "wind":       0.329,
    "bess":       0.484,
    "datacentre": 0.200,
    "dc":         0.200,
}


@dataclass
class ReactiveProfile:
    """Q(V) curve + STATCOM envelope + overnight import schedule + droop."""

    project_id: str
    technology: str
    capacity_mw: float

    # Q(V) curve — list of (voltage_pu, q_mvar) control points.
    qv_curve: list[dict[str, float]] = field(default_factory=list)
    droop_slope_pct: float = _DEFAULT_DROOP_SLOPE

    # Active inverter reactive envelope at rated active power.
    q_max_export_mvar: float = 0.0      # overexcited / VAr injection
    q_max_import_mvar: float = 0.0      # underexcited / VAr absorption
    power_factor_limits: tuple[float, float] = (-0.95, 0.95)

    # STATCOM offer — optional on top of inverter capability.
    statcom_mvar_offered: float = 0.0
    statcom_control_mode: str = "voltage"   # "voltage" | "pf" | "q"
    statcom_response_ms: int = 100

    # Overnight reactive-import schedule (00:00 to 06:00) — DC / BESS often
    # offer to absorb VArs overnight to compensate feeder capacitance.
    overnight_import_schedule: list[dict[str, Any]] = field(default_factory=list)

    # Compliance notes
    fault_ride_through: str = "G99 Issue 2 §12 — 3-phase FRT curve applied"
    notes: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=lambda: [
        "ENA EREC G99 Issue 2 §9.3 (Q(V) & PF envelope)",
        "ENA EREC G99 Issue 2 §12 (fault ride-through)",
        "ENA EREC P28 Issue 2 §5 (reactive-managed flicker)",
        "ENA EREC P29 (unbalance)",
        "Distribution Code DPC4.5 (ancillary reactive service)",
    ])
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _q_fraction_for(tech: str) -> float:
    return _Q_FRACTION_BY_TECH.get((tech or "").lower(), 0.300)


def _build_qv_curve(q_max: float, droop_pct: float) -> list[dict[str, float]]:
    """
    Piecewise Q(V) per G99 Issue 2 §9.3.4.

    A five-point curve (V dead-band ±0.5%, active band up to ±3%, clip to
    |Q|_max at ±3%). This is the canonical DNO-pack shape — a real project
    will swap to the DNO's preferred curve set by the Connection Offer.
    """
    # dead-band around 1.00 p.u.: ±0.5%
    # active slope: droop_pct % per 1% voltage change
    # clipped at ±3% / ±Q_max
    deadband = 0.005
    v_points = [0.94, 1.0 - deadband, 1.0, 1.0 + deadband, 1.06]
    q_points = []
    for v in v_points:
        # Q positive when V low (absorb less / inject more).
        dv = v - 1.0
        if abs(dv) < deadband:
            q = 0.0
        else:
            # droop_pct% per 1% — so 4% droop = 1 pu Q per 25% V. In
            # practice V excursions ≤6% → Q clipped at the max.
            slope = q_max / max(droop_pct / 100.0, 1e-6) * 0.01
            q = -slope * dv   # V high → Q absorb (negative export)
            q = max(-q_max, min(q_max, q))
        q_points.append(round(q, 3))
    return [{"v_pu": round(v, 3), "q_mvar": q} for v, q in zip(v_points, q_points)]


def _overnight_import_schedule(q_max_import: float) -> list[dict[str, Any]]:
    """12 × 30-minute slots from 00:00 to 06:00 offering reactive absorption."""
    slots = []
    for i in range(12):
        hh = i // 2
        mm = (i % 2) * 30
        # Offer ramp: 30% of Q_import for hour 0, 70% by hour 2, 90% by 4-6h.
        if hh < 1:
            k = 0.30
        elif hh < 2:
            k = 0.50
        elif hh < 4:
            k = 0.70
        else:
            k = 0.90
        slots.append({
            "start_hh": f"{hh:02d}:{mm:02d}",
            "end_hh": f"{hh:02d}:{mm + 30:02d}" if mm == 0 else f"{hh + 1:02d}:00",
            "q_offer_mvar": round(-q_max_import * k, 3),  # negative = absorb
            "mode": "voltage-triggered",
        })
    return slots


def compute_reactive_offer(
    project_id: str,
    tech: str,
    capacity_mw: float = 50.0,
    *,
    droop_slope_pct: float | None = None,
    statcom_mvar: float | None = None,
) -> ReactiveProfile:
    """
    Build a DNO-ready reactive offer.

    Parameters
    ----------
    project_id : str
        Princeps project UUID.
    tech : str
        ``solar`` / ``wind`` / ``bess`` / ``datacentre``.
    capacity_mw : float
        Nameplate active power (MW). Reactive envelope is derived from
        technology-specific Q/P fractions (see ``_Q_FRACTION_BY_TECH``).
    droop_slope_pct : float | None
        Optional override for the Q(V) droop in %. Defaults to 4% per
        G99 §9.3.4.
    statcom_mvar : float | None
        Optional STATCOM offer on top of the inverter capability.

    Returns
    -------
    ReactiveProfile
    """
    tech_u = (tech or "datacentre").lower()
    q_frac = _q_fraction_for(tech_u)
    q_max = round(capacity_mw * q_frac, 3)
    droop = float(droop_slope_pct or _DEFAULT_DROOP_SLOPE)

    # Inverter-side PF limits — ±0.95 for Type B/C wind/PV, ±0.9 for BESS.
    if tech_u == "bess":
        pf_limits = (-0.9, 0.9)
    elif tech_u in ("datacentre", "dc"):
        pf_limits = (-0.98, 0.98)   # AHF typically tighter than PF 0.95
    else:
        pf_limits = (-0.95, 0.95)

    qv = _build_qv_curve(q_max, droop)

    statcom_mvar_val = float(statcom_mvar or 0.0)
    overnight = _overnight_import_schedule(q_max + statcom_mvar_val)

    notes = [
        f"Inverter Q envelope: ±{q_max:.2f} MVAr at {capacity_mw:.1f} MW Pmax "
        f"(Q/P = {q_frac:.3f}, tech={tech_u}).",
        f"Q(V) droop: {droop:.1f}% per G99 Issue 2 §9.3.4 — DNO may tune 2-8%.",
        "Priority on active during FRT: active power restored within "
        "1 s of voltage recovery (G99 §12.5).",
    ]
    if statcom_mvar_val > 0:
        notes.append(
            f"STATCOM offered: ±{statcom_mvar_val:.1f} MVAr, "
            f"voltage-control mode, ≤100 ms response."
        )
    notes.append(
        "Overnight (00:00-06:00) voluntary VAr absorption schedule "
        "offered to offset feeder capacitance — DPC4.5 ancillary service."
    )

    return ReactiveProfile(
        project_id=str(project_id),
        technology=tech_u,
        capacity_mw=capacity_mw,
        qv_curve=qv,
        droop_slope_pct=droop,
        q_max_export_mvar=q_max,
        q_max_import_mvar=q_max,
        power_factor_limits=pf_limits,
        statcom_mvar_offered=statcom_mvar_val,
        statcom_control_mode="voltage",
        statcom_response_ms=100,
        overnight_import_schedule=overnight,
        notes=notes,
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )

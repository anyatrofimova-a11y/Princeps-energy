"""
utils.dno_engagement.mitigation — BESS + DSR + behind-meter stack.

Assembles the technical + commercial mitigation options offered to the
DNO to bring the connection from the raw nameplate MW down to a firm
import number the DNO can support without upstream reinforcement.

Layers (applied in order of increasing cost / complexity):
  (a) Behind-the-meter PV / wind / on-site generation    → ACTIVE reduction.
  (b) On-site BESS                                      → PEAK SHAVING.
  (c) Demand-Side Response (DSR) — workload shift        → ADAPTIVE reduction.
  (d) Backup genset (G99 + BS EN ISO 8528 G2)           → ISLAND capability.

Defers all per-component sizing to :mod:`utils.dc_engineering_sizing`
(genset, transformer). BESS sizing uses a simple hours × peak-shave-MW
model — project-level BESS optimisation lives in ``utils.bess_optimiser``.

Cited:
  * BS EN ISO 8528-1 — genset classification G1-G4, prime vs standby.
  * ENA EREC G99 Issue 2 §9 — synchronised on-site generation connection.
  * Ofgem Demand Flexibility Service (DFS) 2024 — DSR MW/£/MWh baseline.
  * Distribution Code DPC9 — islanding & transfer schemes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


@dataclass
class MitigationStack:
    project_id: str
    target_mw: float
    target_capacity_factor: float

    # Layer breakdown
    btm_generation_mw: float = 0.0       # (a)
    bess_peak_shave_mw: float = 0.0      # (b) rated power
    bess_energy_mwh: float = 0.0         # (b) rated energy
    dsr_adaptive_mw: float = 0.0         # (c)
    genset_standby_mw: float = 0.0       # (d)

    # Rolled-up result
    gross_demand_mw: float = 0.0         # pre-mitigation peak
    firm_request_mw: float = 0.0         # net demand the DNO must serve
    mitigation_mw_total: float = 0.0
    annual_mwh_shifted: float = 0.0

    # Per-layer cost (CAPEX estimates)
    layer_capex: dict[str, float] = field(default_factory=dict)
    total_capex_gbp: float = 0.0

    # Per-layer explanations + citations
    layers: list[dict[str, Any]] = field(default_factory=list)

    # Compliance & risk
    g99_notes: list[str] = field(default_factory=list)
    standards: list[str] = field(default_factory=lambda: [
        "BS EN ISO 8528-1 (genset classification)",
        "ENA EREC G99 Issue 2 §9 (synchronised on-site gen)",
        "Ofgem DFS 2024 (DSR baselining)",
        "Distribution Code DPC9 (islanding / transfer)",
        "CCCM v19 Sch.1 §C (avoidable reinforcement)",
    ])
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Layer-level defaults — £/kW or £/kWh UK 2024-2026 benchmarks.
# ---------------------------------------------------------------------------
_BTM_GEN_GBP_PER_KW = {
    "solar":      720.0,    # ground-mount PV EPC (industry 2025).
    "wind":       1_400.0,  # onshore wind turbine installed cost.
    "chp":        950.0,    # gas CHP.
}
_BESS_GBP_PER_KW = 420.0     # 2024-2026 4h Li-ion EPC.
_BESS_GBP_PER_KWH = 185.0
_DSR_GBP_PER_KW = 45.0       # DSR aggregator setup — Ofgem DFS baseline.
_GENSET_GBP_PER_KW = 380.0   # BS EN ISO 8528 G2 standby diesel.


def _btm_layer(target_mw: float, target_cf: float, tech_hint: str | None) -> dict[str, Any]:
    """
    BTM on-site generation. Sized to shave 15% of peak for DC / industrial,
    clipped to 10 MW for a first pack — bigger sites need a standalone grid
    application anyway.
    """
    shave = round(min(10.0, target_mw * 0.15), 3)
    rate = _BTM_GEN_GBP_PER_KW.get((tech_hint or "solar").lower(), 720.0)
    capex = round(shave * 1000.0 * rate, 0)
    return {
        "layer": "BTM generation",
        "rated_mw": shave,
        "technology_hint": tech_hint or "solar",
        "annual_cf": round(target_cf * 0.8, 3),
        "capex_gbp": capex,
        "citation": "CCCM v19 Sch.1 §C — BTM reduces DNO import footprint",
    }


def _bess_layer(target_mw: float) -> dict[str, Any]:
    """Peak-shaving BESS sized to clip ~20% of peak for 2 hours."""
    pmw = round(target_mw * 0.20, 3)
    emwh = round(pmw * 2.0, 3)   # 2-hour duration default
    capex = round(pmw * 1000.0 * _BESS_GBP_PER_KW
                  + emwh * 1000.0 * _BESS_GBP_PER_KWH, 0)
    return {
        "layer": "BESS peak-shave",
        "rated_mw": pmw,
        "rated_mwh": emwh,
        "duration_h": 2.0,
        "cycles_per_year": 300,
        "capex_gbp": capex,
        "citation": "CCCM v19 Sch.1 §C (avoidable reinforcement) + "
                    "ENA EREC G99 Issue 2 §9.2",
    }


def _dsr_layer(target_mw: float) -> dict[str, Any]:
    """DSR / workload-shift capacity — 5% of peak, rule-of-thumb."""
    dmw = round(target_mw * 0.05, 3)
    capex = round(dmw * 1000.0 * _DSR_GBP_PER_KW, 0)
    return {
        "layer": "Demand-side response",
        "rated_mw": dmw,
        "baseline": "Ofgem DFS 2024 baseline (CBL adjusted by weather)",
        "availability": "4-8 windows/year, 2h each",
        "capex_gbp": capex,
        "citation": "Ofgem Demand Flexibility Service 2024",
    }


def _genset_layer(target_mw: float) -> dict[str, Any]:
    """Standby genset layer — BS EN ISO 8528 Class G2, 2N redundancy."""
    # For DC: standby = full facility; for others, 50% peak.
    gmw = round(target_mw * 0.50, 3)
    capex = round(gmw * 1000.0 * _GENSET_GBP_PER_KW, 0)
    return {
        "layer": "Standby genset",
        "rated_mw": gmw,
        "class": "BS EN ISO 8528 G2 (prime ≤10 s start)",
        "redundancy": "N+1",
        "fuel_spec": "Diesel, 48h on-site tank per ENA EREC G74 / DPC9",
        "capex_gbp": capex,
        "citation": "BS EN ISO 8528-1; G99 Issue 2 §9 (synchronised); DPC9",
    }


def compute_mitigation_stack(
    project_id: str,
    target_mw: float,
    target_capacity_factor: float = 0.35,
    *,
    gross_demand_mw: float | None = None,
    technology_hint: str | None = None,
    include_btm: bool = True,
    include_bess: bool = True,
    include_dsr: bool = True,
    include_genset: bool = True,
) -> MitigationStack:
    """
    Build the BESS + DSR + BTM + genset mitigation stack for the DNO pack.

    Parameters
    ----------
    project_id : str
        Princeps project UUID.
    target_mw : float
        Target firm MW the pack is asking the DNO to commit to.
    target_capacity_factor : float
        Expected capacity factor — drives annual MWh shifted.
    gross_demand_mw : float | None
        Pre-mitigation peak. Defaults to ``target_mw × 1.3``.
    technology_hint : str | None
        ``solar`` / ``wind`` / ``chp``. Drives BTM £/kW default.
    include_btm, include_bess, include_dsr, include_genset : bool
        Enable / disable individual layers (pack composer may set these).

    Returns
    -------
    MitigationStack
    """
    gross = float(gross_demand_mw if gross_demand_mw is not None
                  else target_mw * 1.3)

    layers = []
    if include_btm:
        layers.append(_btm_layer(gross, target_capacity_factor, technology_hint))
    if include_bess:
        layers.append(_bess_layer(gross))
    if include_dsr:
        layers.append(_dsr_layer(gross))
    if include_genset:
        layers.append(_genset_layer(gross))

    btm_mw = next((L["rated_mw"] for L in layers if L["layer"] == "BTM generation"), 0.0)
    bess_mw = next((L["rated_mw"] for L in layers if L["layer"] == "BESS peak-shave"), 0.0)
    bess_mwh = next((L["rated_mwh"] for L in layers if L["layer"] == "BESS peak-shave"), 0.0)
    dsr_mw = next((L["rated_mw"] for L in layers if L["layer"] == "Demand-side response"), 0.0)
    gen_mw = next((L["rated_mw"] for L in layers if L["layer"] == "Standby genset"), 0.0)

    # BTM + BESS + DSR reduce firm request. Genset is a standby — does NOT
    # reduce firm DNO ask (runs only during outages), so excluded from the
    # firm net but included in G99 citation pack.
    active_mitigation = btm_mw + bess_mw + dsr_mw
    firm = max(0.0, gross - active_mitigation)

    annual_mwh_shifted = (
        bess_mw * 2.0 * 300            # 2h × 300 cycles
        + dsr_mw * 2.0 * 6             # 2h × 6 events
        + btm_mw * 8760.0 * target_capacity_factor * 0.8
    )

    layer_capex = {L["layer"]: L["capex_gbp"] for L in layers}
    total_capex = sum(layer_capex.values())

    g99_notes = [
        "Each BTM generator ≥3.68 kW must register under G98 (≤16 A/phase) "
        "or G99 (≥16 A/phase) — use G99 Type A/B/C/D per rating.",
        "Standby genset run-on interlock per G99 Issue 2 §12 — genset must "
        "disconnect from mains on grid loss within 0.5 s unless DNO agrees "
        "an islanding scheme under DPC9.",
        "BESS operates in grid-forming or grid-following — if grid-forming "
        "requires extended G99 §9.4 fast-frequency response envelope.",
    ]

    return MitigationStack(
        project_id=str(project_id),
        target_mw=float(target_mw),
        target_capacity_factor=float(target_capacity_factor),
        btm_generation_mw=btm_mw,
        bess_peak_shave_mw=bess_mw,
        bess_energy_mwh=bess_mwh,
        dsr_adaptive_mw=dsr_mw,
        genset_standby_mw=gen_mw,
        gross_demand_mw=round(gross, 3),
        firm_request_mw=round(firm, 3),
        mitigation_mw_total=round(active_mitigation, 3),
        annual_mwh_shifted=round(annual_mwh_shifted, 1),
        layer_capex=layer_capex,
        total_capex_gbp=round(total_capex, 0),
        layers=layers,
        g99_notes=g99_notes,
        generated_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
    )

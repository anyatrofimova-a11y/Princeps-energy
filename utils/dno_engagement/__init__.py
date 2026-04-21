"""
utils.dno_engagement — DNO Engagement Pack engine (Task #18).

Produces an institutional-grade pre-application pack for DNO connection
teams. Sixteen-section document covering site / proposal / hypothetical
demand profile / mitigation stack / constraint analysis / disruption
Monte Carlo / reactive offer / risk / connection options / CCCM cost /
timeline / asks / appendices.

Wraps existing Princeps primitives — it does NOT re-implement power flow,
demand forecasting, or CCCM cost engine:
  * ``utils.demand_forecaster``       — seasonal + diurnal profiles
  * ``utils.grid_power_flow``         — constraint envelope (via the
                                        subprocess bridge in
                                        ``utils.grid_connection_analyser``)
  * ``utils.grid_connection_analyser``— POC identification, CCCM cost
  * ``utils.dc_engineering_sizing``   — all electrical sizing
  * ``utils.bess_optimiser``          — BESS mitigation
  * ``app.analysis.headroom``         — headroom analysis

Regulatory citations (every numerical claim is traceable):
  * ENA EREC G99 Issue 2 (10 Mar 2025) — Type A/B/C/D connection, Table
    10.1 protection settings, fault ride-through, Q(V).
  * Ofgem-approved Common Connection Charging Methodology (CCCM) v19.
  * ENA EREC P28 Issue 2 — voltage fluctuations (flicker, Pst/Plt).
  * ENA EREC P29 — voltage unbalance limits (≤1.3% 10-min average).
  * ENA EREC P2 Issue 7 — security of supply / N-1 obligations.
  * ENA EREC G5 Issue 5 — harmonic distortion limits (THD).
  * BS EN ISO 8528-1 — reciprocating genset classification G1–G4.
  * NESO System Operability Framework (SOF) annual report — demand +
    generation scenarios out to 2050 (FES pathway tie-in).
"""

from __future__ import annotations

__all__ = [
    "compose_dno_pack",
    "compute_seasonal_demand_profile",
    "compute_constraint_envelope",
    "compute_reactive_offer",
    "compute_disruption_scenarios",
    "compute_mitigation_stack",
    "generate_dno_asks",
    "SeasonalProfile",
    "DiurnalEnvelope",
    "ConstraintEnvelope",
    "ReactiveProfile",
    "DisruptionReport",
    "MitigationStack",
    "Ask",
    "DnoPackPayload",
]

# Re-export the public surface so callers can do
# ``from utils.dno_engagement import compose_dno_pack`` etc.
from .profiles import (  # noqa: E402
    SeasonalProfile,
    DiurnalEnvelope,
    compute_seasonal_demand_profile,
)
from .constraint import (  # noqa: E402
    ConstraintEnvelope,
    compute_constraint_envelope,
)
from .reactive import (  # noqa: E402
    ReactiveProfile,
    compute_reactive_offer,
)
from .disruption import (  # noqa: E402
    DisruptionReport,
    compute_disruption_scenarios,
)
from .mitigation import (  # noqa: E402
    MitigationStack,
    compute_mitigation_stack,
)
from .asks import (  # noqa: E402
    Ask,
    generate_dno_asks,
)
from .compose import (  # noqa: E402
    DnoPackPayload,
    compose_dno_pack,
)

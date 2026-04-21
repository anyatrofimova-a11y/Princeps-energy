"""Pydantic schema for the UK N-1 Contingency Map manufactured dataset.

Every primary substation yields exactly one `N1Contingency` record. The
record enumerates each credible single-asset outage within 2 electrical
hops and reports the worst downstream impact.

Field conventions
-----------------
* `substation_id`        — UUID v5 derived from `grid_substations.id`
                           (deterministic, so the same SERIAL row always maps
                           to the same UUID across batch runs).
* `reliability_score_0_100` — 100 means no credible N-1 outage overloads any
                           downstream feeder. 0 means the substation is
                           completely uncovered by redundancy. The scoring
                           curve is defined in `_derive_reliability_score`.
* `est_downtime_hours`   — BSC P2/7 statutory restoration targets:
                           0.25 h (15 min) urban, 1.0 h (60 min) rural.
                           We stretch to 4 h where post-fault loading >130%
                           because that requires sustained load-shedding.

The schema is versioned via `MODEL_VERSION` so downstream consumers can
reason about compatibility as the scoring / restoration logic evolves.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------
MODEL_VERSION = "v1.0.0"


# ---------------------------------------------------------------------------
# Enums (kept as Literal so JSON round-trip is transparent)
# ---------------------------------------------------------------------------
OutageAssetType = Literal["line", "transformer", "busbar"]


# ---------------------------------------------------------------------------
# Per-event record
# ---------------------------------------------------------------------------
class N1Event(BaseModel):
    """One credible single-asset outage + its downstream impact."""

    outage_asset_id: str = Field(
        ...,
        description=(
            "Stable identifier of the asset whose outage is modelled. "
            "Format: '{asset_type}:{db_id}' e.g. 'line:4821', 'trafo:77'."
        ),
    )
    outage_asset_type: OutageAssetType = Field(
        ...,
        description="line | transformer | busbar",
    )
    outage_asset_name: str = Field(
        ...,
        description="Human-readable asset name for the reliability report.",
    )

    overload_pct: float = Field(
        ...,
        ge=0,
        description=(
            "Worst post-contingency thermal loading on any downstream branch, "
            "as % of rated capacity. Values >100 indicate an actual overload."
        ),
    )
    affected_feeders: list[str] = Field(
        default_factory=list,
        description=(
            "Names of branches (lines / transformers) that exceed 100% loading "
            "following this outage. Empty list = the network absorbs the outage."
        ),
    )
    affected_mw: float = Field(
        default=0.0,
        ge=0,
        description="Downstream demand (MW) that would be at risk of shedding.",
    )
    est_downtime_hours: float = Field(
        ...,
        ge=0,
        description=(
            "Expected customer restoration time per BSC Supply Security "
            "Standard P2/7 — 0.25 h urban, 1.0 h rural, stretched where "
            "post-fault loading exceeds 130%."
        ),
    )
    restoration_path: str = Field(
        default="automatic",
        description=(
            "How service is restored: 'automatic' (reclosers / feeder "
            "transfer), 'manual_switching' (SCADA-directed), or "
            "'repair_required' (no redundancy — wait for crew)."
        ),
    )
    converged: bool = Field(
        default=True,
        description="Whether the post-contingency power flow converged.",
    )


# ---------------------------------------------------------------------------
# Per-substation record
# ---------------------------------------------------------------------------
class N1Contingency(BaseModel):
    """One row of the UK N-1 Contingency Map manufactured dataset."""

    substation_id: UUID = Field(
        ...,
        description=(
            "Princeps canonical substation UUID — deterministically derived "
            "from grid_substations.id via UUID5 (namespace = Princeps)."
        ),
    )
    substation_name: str
    voltage_kv: float = Field(..., gt=0)
    dno: Optional[str] = Field(
        default=None,
        description="Licensee slug — ukpn / ssen / spen / nged / npg / enwl.",
    )

    n1_outage_events: list[N1Event] = Field(
        default_factory=list,
        description="One entry per credible upstream asset outage, sorted worst-first.",
    )

    worst_case_overload_pct: float = Field(
        default=0.0,
        ge=0,
        description="max() of event overload_pct across all events.",
    )
    worst_case_affected_mw: float = Field(
        default=0.0,
        ge=0,
        description="max() of event affected_mw across all events.",
    )
    reliability_score_0_100: float = Field(
        ...,
        ge=0,
        le=100,
        description=(
            "100 = no credible N-1 outage causes any overload. "
            "0 = every upstream outage overloads at least one feeder beyond 130%."
        ),
    )

    # Coordinates carried for map rendering — WGS84 to match GeoJSON output.
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)

    last_computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    model_version: str = Field(default=MODEL_VERSION)

    # Diagnostic counters (exposed by /api/n1/worst-cases for observability).
    upstream_assets_scanned: int = Field(default=0, ge=0)
    failed_outages: int = Field(
        default=0,
        ge=0,
        description="Number of upstream assets where pandapower did not converge.",
    )
    notes: list[str] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Derived-field validators
    # ------------------------------------------------------------------
    @field_validator("reliability_score_0_100")
    @classmethod
    def _round_score(cls, v: float) -> float:
        return round(float(v), 2)

    @field_validator("worst_case_overload_pct", "worst_case_affected_mw")
    @classmethod
    def _round_2dp(cls, v: float) -> float:
        return round(float(v), 2)


# ---------------------------------------------------------------------------
# Scoring helpers (used by analyser.py, kept here so downstream consumers can
# re-derive the score from events if needed without importing the analyser)
# ---------------------------------------------------------------------------
def derive_reliability_score(events: list[N1Event]) -> float:
    """Curve:

        * no events with overload_pct > 100           -> 100
        * worst overload in (100, 110]                -> 80
        * worst overload in (110, 130]                -> 50
        * worst overload in (130, 150]                -> 25
        * worst overload > 150                        -> 5
        * >=1 non-converged outage (islanded)         -> 0

    Then linearly interpolate within bands and subtract 5 points for every
    additional overloading event beyond the first (cap at -25).
    """
    if not events:
        return 100.0

    non_converged = [e for e in events if not e.converged]
    if non_converged:
        return 0.0

    overloading = [e for e in events if e.overload_pct > 100]
    if not overloading:
        return 100.0

    worst = max(e.overload_pct for e in overloading)

    if worst <= 110:
        base = 80 - (worst - 100) * (80 - 65) / 10       # 80 → 65
    elif worst <= 130:
        base = 65 - (worst - 110) * (65 - 40) / 20       # 65 → 40
    elif worst <= 150:
        base = 40 - (worst - 130) * (40 - 15) / 20       # 40 → 15
    else:
        base = max(5.0, 15 - (worst - 150) * 0.1)        # gently down to 5

    penalty = min(25.0, 5.0 * (len(overloading) - 1))
    return round(max(0.0, base - penalty), 2)


def derive_downtime_hours(overload_pct: float, is_urban: bool) -> float:
    """BSC P2/7 restoration targets, stretched for deep overloads."""
    if overload_pct <= 100:
        return 0.0  # no overload → nothing to restore
    base = 0.25 if is_urban else 1.0
    if overload_pct <= 110:
        return base
    if overload_pct <= 130:
        return base * 2
    if overload_pct <= 150:
        return 4.0
    return 8.0


def derive_restoration_path(overload_pct: float, has_redundancy: bool) -> str:
    if overload_pct <= 100:
        return "automatic"
    if not has_redundancy:
        return "repair_required"
    if overload_pct <= 110:
        return "automatic"
    if overload_pct <= 130:
        return "manual_switching"
    return "repair_required"

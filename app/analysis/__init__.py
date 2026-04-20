"""Unified analysis package for Princeps.

Every analysis is a pure async function of
``(ontology_object, horizon, scenario) -> Analysis`` that reads the DB,
delegates to domain utilities, and returns a structured probabilistic
result.
"""

from __future__ import annotations

from dataclasses import asdict

from app.analysis.types import (
    Analysis,
    Horizon,
    Scenario,
    ProvenanceEntry,
    coerce_horizon,
    coerce_scenario,
    degraded,
    truncate,
    utcnow,
)

# Aliases kept so legacy ``app.analysis.buildable`` (and any other older
# callers) continue to import ``_utcnow`` / ``_truncate`` from this package.
_utcnow = utcnow
_truncate = truncate

from app.analysis.headroom import headroom, analyse_headroom  # noqa: E402
from app.analysis.buildable_area import buildable_area, analyse_buildable_area  # noqa: E402
from app.analysis.ownership import ownership, analyse_ownership  # noqa: E402
from app.analysis.site_load_forecast import site_load_forecast  # noqa: E402

# Legacy re-exports (do not rely on in new code).
try:
    from app.analysis.buildable import BuildableFilters, analyse_buildable  # noqa: E402,F401
except Exception:  # noqa: BLE001
    BuildableFilters = None  # type: ignore[assignment]
    analyse_buildable = analyse_buildable_area  # type: ignore[assignment]


# Dispatcher used by the router.
ANALYSES = {
    "headroom": headroom,
    "buildable_area": buildable_area,
    "ownership": ownership,
    "site_load_forecast": site_load_forecast,
}


__all__ = [
    "Analysis",
    "Horizon",
    "Scenario",
    "ProvenanceEntry",
    "asdict",
    "coerce_horizon",
    "coerce_scenario",
    "degraded",
    "truncate",
    "utcnow",
    "headroom",
    "buildable_area",
    "ownership",
    "site_load_forecast",
    "analyse_headroom",
    "analyse_buildable_area",
    "analyse_ownership",
    "ANALYSES",
    # legacy
    "BuildableFilters",
    "analyse_buildable",
]

"""Per-site probabilistic demand forecasting for Princeps.

Wraps the existing subprocess-based Prophet/TFT forecasters (utils/demand_forecaster.py)
with site-specific typology curves (SIC codes) and behind-the-meter overlays
(PV, BESS, EV, heat pump penetration).

Public API:
- ForecastResult, Horizon, Interval, Scenario — types
- SIC_TYPOLOGIES, get_typology, list_typologies — library
- apply_behind_meter — overlay calculator
- forecast_site_load — main entry
- dirty_sites, mark_dirty — event triggers
"""

from __future__ import annotations

from app.forecast.types import (
    ForecastResult,
    Horizon,
    Interval,
    Scenario,
    SeriesPoint,
    Provenance,
)
from app.forecast.sic_typology import (
    SIC_TYPOLOGIES,
    Typology,
    get_typology,
    list_typologies,
    gross_profile,
)
from app.forecast.behind_meter import (
    BehindMeterAssets,
    apply_behind_meter,
)
from app.forecast.site_load import forecast_site_load
from app.forecast.triggers import (
    mark_dirty,
    dirty_sites,
    clear_dirty,
    note_ecr_change,
)

__all__ = [
    "ForecastResult",
    "Horizon",
    "Interval",
    "Scenario",
    "SeriesPoint",
    "Provenance",
    "SIC_TYPOLOGIES",
    "Typology",
    "get_typology",
    "list_typologies",
    "gross_profile",
    "BehindMeterAssets",
    "apply_behind_meter",
    "forecast_site_load",
    "mark_dirty",
    "dirty_sites",
    "clear_dirty",
    "note_ecr_change",
]

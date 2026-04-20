"""Forecast result types — enums, dataclasses, JSON-safe shapes."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Horizon(str, Enum):
    INTRADAY = "intraday"        # next 6 hours, 30-min resolution
    DAY_AHEAD = "day_ahead"      # next 24 h, 30-min
    WEEK_AHEAD = "week_ahead"    # next 168 h, 1-h
    MONTH_AHEAD = "month_ahead"  # next 30 days, 1-h
    YEAR_AHEAD = "year_ahead"    # next 8760 h, 1-h
    LONG_TERM = "long_term"      # annual projection to 2050


class Interval(str, Enum):
    HALF_HOURLY = "30min"
    HOURLY = "60min"
    DAILY = "1d"
    ANNUAL = "1y"


class Scenario(str, Enum):
    LEADING_THE_WAY = "leading_the_way"
    CONSUMER_TRANSFORMATION = "consumer_transformation"
    SYSTEM_TRANSFORMATION = "system_transformation"
    FALLING_SHORT = "falling_short"
    CENTRAL = "central"


HORIZON_CONFIG: dict[Horizon, tuple[int, Interval]] = {
    Horizon.INTRADAY:    (6,    Interval.HALF_HOURLY),
    Horizon.DAY_AHEAD:   (24,   Interval.HALF_HOURLY),
    Horizon.WEEK_AHEAD:  (168,  Interval.HOURLY),
    Horizon.MONTH_AHEAD: (720,  Interval.HOURLY),
    Horizon.YEAR_AHEAD:  (8760, Interval.HOURLY),
    Horizon.LONG_TERM:   (26,   Interval.ANNUAL),  # 2024-2050 annual
}


@dataclass
class SeriesPoint:
    t: str           # ISO-8601 timestamp or year label for long_term
    p10: float       # MW
    p50: float
    p90: float


@dataclass
class Provenance:
    typology_source: str = ""
    history_source: str = ""
    upstream_model: str = ""
    subprocess_ok: bool = False
    data_coverage: float = 0.0   # 0-1
    notes: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ForecastResult:
    site_id: str
    typology: str
    horizon: str
    interval: str
    scenario: str
    series_p10: list[float]
    series_p50: list[float]
    series_p90: list[float]
    timestamps: list[str]
    peak_mw_p50: float
    energy_mwh_p50: float
    confidence: float                      # 0-1
    explanation: str
    provenance: dict[str, Any]
    computed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

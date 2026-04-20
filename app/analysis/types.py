"""Core dataclasses and enums for the analysis package.

An ``Analysis`` is the single return shape for every analysis function:
point estimate, probabilistic band, a confidence, a short explanation,
and provenance entries so downstream agents can cite sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal


class Horizon(str, Enum):
    DAY_AHEAD = "day_ahead"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    DECADE = "decade"


class Scenario(str, Enum):
    CENTRAL = "central"
    LEADING_THE_WAY = "leading_the_way"
    CONSUMER_TRANSFORMATION = "consumer_transformation"
    SYSTEM_TRANSFORMATION = "system_transformation"
    FALLING_SHORT = "falling_short"


ProvenanceKind = Literal["live", "cached", "synthetic", "missing"]


@dataclass
class ProvenanceEntry:
    source: str
    kind: ProvenanceKind
    age_s: float | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "age_s": self.age_s,
            "detail": self.detail,
        }


@dataclass
class Analysis:
    value: float | None
    p10: float | None
    p90: float | None
    confidence: float
    explanation: str
    provenance: list[ProvenanceEntry] = field(default_factory=list)
    computed_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    kind: str = ""
    target_key: str = ""
    units: str = ""
    p50: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["provenance"] = [p.to_dict() if isinstance(p, ProvenanceEntry) else p for p in self.provenance]
        d["computed_utc"] = self.computed_utc.isoformat()
        return d


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def truncate(text: str, limit: int = 399) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def coerce_horizon(h: str | Horizon) -> Horizon:
    if isinstance(h, Horizon):
        return h
    try:
        return Horizon(h)
    except ValueError:
        return Horizon.DAY_AHEAD


def coerce_scenario(s: str | Scenario) -> Scenario:
    if isinstance(s, Scenario):
        return s
    try:
        return Scenario(s)
    except ValueError:
        return Scenario.CENTRAL


def degraded(
    kind: str,
    target_key: str,
    reason: str,
    *,
    units: str = "",
    provenance: list[ProvenanceEntry] | None = None,
) -> Analysis:
    return Analysis(
        value=None,
        p10=None,
        p50=None,
        p90=None,
        confidence=0.0,
        explanation=truncate(f"{kind} unavailable: {reason}"),
        provenance=provenance or [ProvenanceEntry(source=kind, kind="missing", detail=reason)],
        kind=kind,
        target_key=target_key,
        units=units,
    )

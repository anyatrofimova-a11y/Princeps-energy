"""IEC 61970 OperationalLimits — current and voltage limits."""

from __future__ import annotations

from .base import IdentifiedObject

__all__ = [
    "OperationalLimitSet",
    "CurrentLimit",
    "VoltageLimit",
]


class OperationalLimitSet(IdentifiedObject):
    """A set of operational limits for a terminal or piece of equipment."""

    terminal_id: str | None = None
    equipment_id: str | None = None


class CurrentLimit(IdentifiedObject):
    """Maximum allowable current (Amps)."""

    operational_limit_set_id: str
    value_a: float
    limit_type: str = "patl"  # patl | tatl


class VoltageLimit(IdentifiedObject):
    """Voltage limit (kV)."""

    operational_limit_set_id: str
    value_kv: float
    limit_type: str = "high"  # high | low

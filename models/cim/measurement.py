"""IEC 61970 Measurement package — analog measurements and values."""

from __future__ import annotations

from pydantic import BaseModel

from .base import IdentifiedObject

__all__ = [
    "Analog",
    "AnalogValue",
]


class Analog(IdentifiedObject):
    """A measurement definition (e.g. voltage at a terminal)."""

    terminal_id: str | None = None
    power_system_resource_id: str | None = None
    measurement_type: str  # "ThreePhaseActivePower", "Voltage", etc.
    unit_symbol: str  # "W", "V", "A"
    positive_flow_in: bool = True


class AnalogValue(BaseModel):
    """A single measured value for an Analog."""

    analog_id: str
    value: float
    timestamp: str | None = None

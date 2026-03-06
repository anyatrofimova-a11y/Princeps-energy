"""IEC 61970 Core package — containers, voltage levels, regions."""

from __future__ import annotations

from .base import IdentifiedObject, PowerSystemResource

__all__ = [
    "BaseVoltage",
    "GeographicalRegion",
    "SubGeographicalRegion",
    "Substation",
    "VoltageLevel",
    "Bay",
]


class BaseVoltage(IdentifiedObject):
    """Defines a system base voltage (CIM uses kV natively)."""

    nominal_voltage_kv: float


class GeographicalRegion(IdentifiedObject):
    """Top-level geographical region (e.g. 'East Midlands')."""

    pass


class SubGeographicalRegion(IdentifiedObject):
    """Sub-region within a GeographicalRegion."""

    region_id: str | None = None


class Substation(PowerSystemResource):
    """Physical substation — container for voltage levels and equipment."""

    region: str | None = None
    sub_geographical_region_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class VoltageLevel(IdentifiedObject):
    """A voltage level within a substation."""

    substation_id: str
    base_voltage_id: str | None = None
    base_kv: float | None = None
    high_voltage_limit_kv: float | None = None
    low_voltage_limit_kv: float | None = None


class Bay(IdentifiedObject):
    """A switching bay within a voltage level."""

    voltage_level_id: str

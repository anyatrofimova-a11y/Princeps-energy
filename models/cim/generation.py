"""IEC 61970 Generation package — generating units and machines."""

from __future__ import annotations

from .base import ConductingEquipment, Equipment

__all__ = [
    "GeneratingUnit",
    "SolarGeneratingUnit",
    "WindGeneratingUnit",
    "SynchronousMachine",
]


class GeneratingUnit(Equipment):
    """A single generating unit (any fuel type)."""

    max_operating_mw: float | None = None
    min_operating_mw: float | None = None
    rated_gross_max_mw: float | None = None
    fuel_type: str | None = None  # solar, wind, gas, etc.


class SolarGeneratingUnit(GeneratingUnit):
    """PV solar generating unit."""

    panel_count: int | None = None
    installed_capacity_kw: float | None = None


class WindGeneratingUnit(GeneratingUnit):
    """Wind turbine generating unit."""

    turbine_count: int | None = None
    rotor_diameter_m: float | None = None


class SynchronousMachine(ConductingEquipment):
    """Rotating machine — generator or synchronous condenser."""

    generating_unit_id: str | None = None
    rated_mva: float | None = None
    type: str = "generator"  # generator | condenser

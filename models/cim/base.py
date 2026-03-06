"""IEC 61970 base classes — IdentifiedObject through ConductingEquipment."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "IdentifiedObject",
    "PowerSystemResource",
    "Equipment",
    "ConductingEquipment",
]


class IdentifiedObject(BaseModel):
    """Root of the CIM hierarchy — every named object has an MRID."""

    mrid: str = Field(..., description="Master Resource Identifier (rdf:ID)")
    name: str | None = None
    description: str | None = None
    alias_name: str | None = None


class PowerSystemResource(IdentifiedObject):
    """Base for all power system equipment and containers."""

    pass


class Equipment(PowerSystemResource):
    """Physical device installed in the power system."""

    aggregate: bool = False
    normally_in_service: bool = True
    equipment_container_id: str | None = None


class ConductingEquipment(Equipment):
    """Equipment that carries current."""

    base_voltage_id: str | None = None

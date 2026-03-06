"""IEC 61970-301 Wires package — transformers, lines, loads, switches."""

from __future__ import annotations

from .base import ConductingEquipment, IdentifiedObject

__all__ = [
    "PowerTransformer",
    "PowerTransformerEnd",
    "ACLineSegment",
    "EnergyConsumer",
    "ShuntCompensator",
    "LinearShuntCompensator",
    "StaticVarCompensator",
    "Switch",
    "Breaker",
    "Disconnector",
    "LoadBreakSwitch",
    "BusbarSection",
]


class PowerTransformer(ConductingEquipment):
    """Two- or three-winding power transformer."""

    rated_mva: float | None = None
    substation_id: str | None = None
    vector_group: str | None = None  # e.g. "Dyn11"


class PowerTransformerEnd(IdentifiedObject):
    """One winding end of a PowerTransformer."""

    power_transformer_id: str
    end_number: int = 1
    rated_mva: float | None = None
    rated_kv: float | None = None
    r_ohm: float | None = None
    x_ohm: float | None = None
    connection_kind: str | None = None  # "D", "Y", "Z"


class ACLineSegment(ConductingEquipment):
    """An AC overhead line or cable segment."""

    length_km: float | None = None
    r_ohm: float | None = None
    x_ohm: float | None = None
    b_siemens: float | None = None
    rated_current_a: float | None = None
    region: str | None = None


class EnergyConsumer(ConductingEquipment):
    """Generic load (demand point)."""

    p_mw: float | None = None
    q_mvar: float | None = None
    customer_count: int | None = None
    substation_id: str | None = None


class ShuntCompensator(ConductingEquipment):
    """Shunt capacitor or reactor for reactive power compensation.

    IEC 61970: single or multi-section switched shunt device.
    Positive Q = capacitive (injects VARs), negative = inductive (absorbs).
    """

    nom_q_mvar: float | None = None  # Nominal reactive power at nominal voltage
    sections: int = 1  # Number of switchable sections
    max_sections: int = 1
    b_per_section_siemens: float | None = None  # Susceptance per section
    voltage_regulation_on: bool = False
    target_voltage_pu: float | None = None  # Target voltage for AVR mode
    grounded: bool = True
    substation_id: str | None = None


class LinearShuntCompensator(ShuntCompensator):
    """Shunt compensator with linear susceptance characteristic.

    Each section adds a fixed b (capacitive) and g (conductive) increment.
    """

    b_per_section_siemens: float | None = None
    g_per_section_siemens: float | None = None


class StaticVarCompensator(ConductingEquipment):
    """STATCOM / SVC — continuously variable reactive power device.

    IEC 61970: power-electronics-based compensator providing fast,
    continuously variable Q injection/absorption.
    """

    capacitive_rating_mvar: float | None = None  # Max capacitive output
    inductive_rating_mvar: float | None = None  # Max inductive absorption
    slope: float | None = None  # Voltage/reactive power droop (%)
    voltage_setpoint_pu: float | None = None  # Target bus voltage
    q_mvar: float | None = None  # Current operating point
    svc_control_mode: str = "voltage"  # voltage | reactive_power | off
    substation_id: str | None = None


class Switch(ConductingEquipment):
    """Base class for all switching devices."""

    normal_open: bool = False
    retained: bool = False


class Breaker(Switch):
    """Circuit breaker."""

    pass


class Disconnector(Switch):
    """Isolating disconnector."""

    pass


class LoadBreakSwitch(Switch):
    """Load break switch — can interrupt load current."""

    pass


class BusbarSection(ConductingEquipment):
    """Busbar within a substation."""

    ip_max_ka: float | None = None

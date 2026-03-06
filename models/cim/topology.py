"""IEC 61970-301 Topology — connectivity nodes, terminals, topological nodes."""

from __future__ import annotations

from .base import IdentifiedObject

__all__ = [
    "ConnectivityNode",
    "Terminal",
    "TopologicalNode",
]


class ConnectivityNode(IdentifiedObject):
    """Point where conducting equipment terminals connect."""

    connectivity_node_container_id: str | None = None


class Terminal(IdentifiedObject):
    """An electrical connection point on ConductingEquipment."""

    conducting_equipment_id: str
    connectivity_node_id: str | None = None
    sequence_number: int = 1
    connected: bool = True


class TopologicalNode(IdentifiedObject):
    """Merged set of ConnectivityNodes at same voltage (bus-branch model)."""

    base_voltage_id: str | None = None
    connectivity_node_ids: list[str] = []

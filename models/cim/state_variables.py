"""IEC 61970-301 StateVariables — power flow results (Phase 7 foundation)."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "SvVoltage",
    "SvPowerFlow",
    "SvStatus",
]


class SvVoltage(BaseModel):
    """Voltage magnitude and angle at a TopologicalNode."""

    topological_node_id: str
    v_pu: float
    angle_deg: float


class SvPowerFlow(BaseModel):
    """Active/reactive power flow through a Terminal."""

    terminal_id: str
    p_mw: float
    q_mvar: float


class SvStatus(BaseModel):
    """In-service status of conducting equipment."""

    conducting_equipment_id: str
    in_service: bool

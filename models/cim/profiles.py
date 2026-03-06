"""CGMES profile definitions — maps CIM profiles to their model classes."""

from __future__ import annotations

from enum import Enum


class CIMProfile(str, Enum):
    EQ = "Equipment"
    TP = "Topology"
    SV = "StateVariables"
    DY = "Dynamics"
    GL = "GeographicalLocation"
    DL = "DiagramLayout"
    SSH = "SteadyStateHypothesis"


# Lazy import to avoid circular refs — populated at first access
_cgmes_profiles: dict | None = None


def _build_profiles() -> dict[CIMProfile, list[type]]:
    from .core import (
        BaseVoltage,
        Bay,
        GeographicalRegion,
        SubGeographicalRegion,
        Substation,
        VoltageLevel,
    )
    from .generation import (
        GeneratingUnit,
        SolarGeneratingUnit,
        SynchronousMachine,
        WindGeneratingUnit,
    )
    from .measurement import Analog, AnalogValue
    from .operational_limits import CurrentLimit, OperationalLimitSet, VoltageLimit
    from .state_variables import SvPowerFlow, SvStatus, SvVoltage
    from .topology import ConnectivityNode, Terminal, TopologicalNode
    from .wires import (
        ACLineSegment,
        Breaker,
        BusbarSection,
        Disconnector,
        EnergyConsumer,
        LinearShuntCompensator,
        LoadBreakSwitch,
        PowerTransformer,
        PowerTransformerEnd,
        ShuntCompensator,
        StaticVarCompensator,
        Switch,
    )

    return {
        CIMProfile.EQ: [
            GeographicalRegion,
            SubGeographicalRegion,
            Substation,
            VoltageLevel,
            Bay,
            BaseVoltage,
            ConnectivityNode,
            Terminal,
            PowerTransformer,
            PowerTransformerEnd,
            ACLineSegment,
            EnergyConsumer,
            Switch,
            Breaker,
            Disconnector,
            LoadBreakSwitch,
            BusbarSection,
            ShuntCompensator,
            LinearShuntCompensator,
            StaticVarCompensator,
            GeneratingUnit,
            SolarGeneratingUnit,
            WindGeneratingUnit,
            SynchronousMachine,
            OperationalLimitSet,
            CurrentLimit,
            VoltageLimit,
            Analog,
        ],
        CIMProfile.TP: [
            TopologicalNode,
            ConnectivityNode,
            Terminal,
        ],
        CIMProfile.SV: [
            SvVoltage,
            SvPowerFlow,
            SvStatus,
        ],
        CIMProfile.SSH: [
            EnergyConsumer,
            GeneratingUnit,
            SynchronousMachine,
            Switch,
            Breaker,
            Disconnector,
            LoadBreakSwitch,
            AnalogValue,
        ],
    }


def get_cgmes_profiles() -> dict[CIMProfile, list[type]]:
    global _cgmes_profiles
    if _cgmes_profiles is None:
        _cgmes_profiles = _build_profiles()
    return _cgmes_profiles


CGMES_PROFILES = property(lambda self: get_cgmes_profiles())

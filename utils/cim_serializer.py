"""CIM Serializer — IEC 61970-552 RDF/XML and IEC 61970-556 JSON-LD.

Export Princeps CIM Pydantic models to standard interchange formats and
import CIM documents back into typed models.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

from models.cim.base import (
    ConductingEquipment,
    Equipment,
    IdentifiedObject,
    PowerSystemResource,
)
from models.cim.core import (
    BaseVoltage,
    Bay,
    GeographicalRegion,
    SubGeographicalRegion,
    Substation,
    VoltageLevel,
)
from models.cim.generation import (
    GeneratingUnit,
    SolarGeneratingUnit,
    SynchronousMachine,
    WindGeneratingUnit,
)
from models.cim.measurement import Analog, AnalogValue
from models.cim.operational_limits import (
    CurrentLimit,
    OperationalLimitSet,
    VoltageLimit,
)
from models.cim.profiles import CIMProfile
from models.cim.state_variables import SvPowerFlow, SvStatus, SvVoltage
from models.cim.topology import ConnectivityNode, Terminal, TopologicalNode
from models.cim.wires import (
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

log = logging.getLogger("princeps.cim_serializer")

# ---------------------------------------------------------------------------
# CIM / RDF namespaces
# ---------------------------------------------------------------------------
CIM_NS = "http://iec.ch/TC57/CIM100#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
MD_NS = "http://iec.ch/TC57/61970-552/ModelDescription/1#"
CIM16_NS = "http://iec.ch/TC57/2013/CIM-schema-cim16#"

# Register namespace prefixes for clean XML output
ET.register_namespace("cim", CIM_NS)
ET.register_namespace("rdf", RDF_NS)
ET.register_namespace("md", MD_NS)

# ---------------------------------------------------------------------------
# Python field → CIM property mapping + unit conversions
# ---------------------------------------------------------------------------
# Format: "PythonField": ("cim:Class.property", conversion)
# Conversions: None = passthrough, "ref" = rdf:resource, "mva_to_va" etc.


def _mva_to_va(v: float) -> float:
    return v * 1e6


def _va_to_mva(v: float) -> float:
    return v / 1e6 if abs(v) > 1000 else v


def _mw_to_w(v: float) -> float:
    return v * 1e6


def _w_to_mw(v: float) -> float:
    return v / 1e6 if abs(v) > 10000 else v


def _km_to_m(v: float) -> float:
    return v * 1000


def _m_to_km(v: float) -> float:
    return v / 1000 if v > 100 else v


_CONVERTERS = {
    "mva_to_va": _mva_to_va,
    "mw_to_w": _mw_to_w,
    "km_to_m": _km_to_m,
}

_REVERSE_CONVERTERS = {
    "mva_to_va": _va_to_mva,
    "mw_to_w": _w_to_mw,
    "km_to_m": _m_to_km,
}

# Maps: CIM class name -> { python_field: (cim_property_path, converter_key | "ref" | None) }
CIM_FIELD_MAP: dict[str, dict[str, tuple[str, str | None]]] = {
    "IdentifiedObject": {
        "name": ("cim:IdentifiedObject.name", None),
        "description": ("cim:IdentifiedObject.description", None),
        "alias_name": ("cim:IdentifiedObject.aliasName", None),
    },
    "Equipment": {
        "aggregate": ("cim:Equipment.aggregate", None),
        "normally_in_service": ("cim:Equipment.normallyInService", None),
        "equipment_container_id": ("cim:Equipment.EquipmentContainer", "ref"),
    },
    "ConductingEquipment": {
        "base_voltage_id": ("cim:ConductingEquipment.BaseVoltage", "ref"),
    },
    "BaseVoltage": {
        "nominal_voltage_kv": ("cim:BaseVoltage.nominalVoltage", None),
    },
    "GeographicalRegion": {},
    "SubGeographicalRegion": {
        "region_id": ("cim:SubGeographicalRegion.Region", "ref"),
    },
    "Substation": {
        "region": ("cim:Substation.Region", "ref"),
        "sub_geographical_region_id": (
            "cim:Substation.SubGeographicalRegion",
            "ref",
        ),
    },
    "VoltageLevel": {
        "substation_id": ("cim:VoltageLevel.Substation", "ref"),
        "base_voltage_id": ("cim:VoltageLevel.BaseVoltage", "ref"),
        "base_kv": ("cim:VoltageLevel.highVoltageLimit", None),
        "high_voltage_limit_kv": ("cim:VoltageLevel.highVoltageLimit", None),
        "low_voltage_limit_kv": ("cim:VoltageLevel.lowVoltageLimit", None),
    },
    "Bay": {
        "voltage_level_id": ("cim:Bay.VoltageLevel", "ref"),
    },
    "ConnectivityNode": {
        "connectivity_node_container_id": (
            "cim:ConnectivityNode.ConnectivityNodeContainer",
            "ref",
        ),
    },
    "Terminal": {
        "conducting_equipment_id": (
            "cim:Terminal.ConductingEquipment",
            "ref",
        ),
        "connectivity_node_id": ("cim:Terminal.ConnectivityNode", "ref"),
        "sequence_number": ("cim:Terminal.sequenceNumber", None),
        "connected": ("cim:Terminal.connected", None),
    },
    "TopologicalNode": {
        "base_voltage_id": ("cim:TopologicalNode.BaseVoltage", "ref"),
    },
    "PowerTransformer": {
        "rated_mva": ("cim:PowerTransformer.ratedS", "mva_to_va"),
        "substation_id": ("cim:Equipment.EquipmentContainer", "ref"),
        "vector_group": ("cim:PowerTransformer.vectorGroup", None),
    },
    "PowerTransformerEnd": {
        "power_transformer_id": (
            "cim:PowerTransformerEnd.PowerTransformer",
            "ref",
        ),
        "end_number": ("cim:TransformerEnd.endNumber", None),
        "rated_mva": ("cim:PowerTransformerEnd.ratedS", "mva_to_va"),
        "rated_kv": ("cim:PowerTransformerEnd.ratedU", None),
        "r_ohm": ("cim:PowerTransformerEnd.r", None),
        "x_ohm": ("cim:PowerTransformerEnd.x", None),
        "connection_kind": ("cim:PowerTransformerEnd.connectionKind", None),
    },
    "ACLineSegment": {
        "length_km": ("cim:Conductor.length", "km_to_m"),
        "r_ohm": ("cim:ACLineSegment.r", None),
        "x_ohm": ("cim:ACLineSegment.x", None),
        "b_siemens": ("cim:ACLineSegment.bch", None),
        "rated_current_a": ("cim:ACLineSegment.ratedCurrent", None),
    },
    "EnergyConsumer": {
        "p_mw": ("cim:EnergyConsumer.pfixed", "mw_to_w"),
        "q_mvar": ("cim:EnergyConsumer.qfixed", "mw_to_w"),
        "customer_count": ("cim:EnergyConsumer.customerCount", None),
        "substation_id": ("cim:Equipment.EquipmentContainer", "ref"),
    },
    "Switch": {
        "normal_open": ("cim:Switch.normalOpen", None),
        "retained": ("cim:Switch.retained", None),
    },
    "Breaker": {},
    "Disconnector": {},
    "LoadBreakSwitch": {},
    "BusbarSection": {
        "ip_max_ka": ("cim:BusbarSection.ipMax", None),
    },
    "ShuntCompensator": {
        "nom_q_mvar": ("cim:ShuntCompensator.nomQ", "mw_to_w"),
        "sections": ("cim:ShuntCompensator.sections", None),
        "max_sections": ("cim:ShuntCompensator.maximumSections", None),
        "b_per_section_siemens": ("cim:ShuntCompensator.bPerSection", None),
        "voltage_regulation_on": ("cim:ShuntCompensator.voltageRegulationOn", None),
        "target_voltage_pu": ("cim:ShuntCompensator.targetV", None),
        "grounded": ("cim:ShuntCompensator.grounded", None),
        "substation_id": ("cim:Equipment.EquipmentContainer", "ref"),
    },
    "LinearShuntCompensator": {
        "b_per_section_siemens": ("cim:LinearShuntCompensator.bPerSection", None),
        "g_per_section_siemens": ("cim:LinearShuntCompensator.gPerSection", None),
    },
    "StaticVarCompensator": {
        "capacitive_rating_mvar": ("cim:StaticVarCompensator.capacitiveRating", "mw_to_w"),
        "inductive_rating_mvar": ("cim:StaticVarCompensator.inductiveRating", "mw_to_w"),
        "slope": ("cim:StaticVarCompensator.slope", None),
        "voltage_setpoint_pu": ("cim:StaticVarCompensator.voltageSetPoint", None),
        "q_mvar": ("cim:StaticVarCompensator.q", "mw_to_w"),
        "svc_control_mode": ("cim:StaticVarCompensator.sVCControlMode", None),
        "substation_id": ("cim:Equipment.EquipmentContainer", "ref"),
    },
    "GeneratingUnit": {
        "max_operating_mw": ("cim:GeneratingUnit.maxOperatingP", "mw_to_w"),
        "min_operating_mw": ("cim:GeneratingUnit.minOperatingP", "mw_to_w"),
        "rated_gross_max_mw": (
            "cim:GeneratingUnit.ratedGrossMaxP",
            "mw_to_w",
        ),
        "fuel_type": ("cim:GeneratingUnit.fuelType", None),
    },
    "SolarGeneratingUnit": {
        "panel_count": ("cim:SolarGeneratingUnit.panelCount", None),
        "installed_capacity_kw": (
            "cim:SolarGeneratingUnit.installedCapacity",
            None,
        ),
    },
    "WindGeneratingUnit": {
        "turbine_count": ("cim:WindGeneratingUnit.turbineCount", None),
        "rotor_diameter_m": ("cim:WindGeneratingUnit.rotorDiameter", None),
    },
    "SynchronousMachine": {
        "generating_unit_id": (
            "cim:SynchronousMachine.GeneratingUnit",
            "ref",
        ),
        "rated_mva": ("cim:SynchronousMachine.ratedS", "mva_to_va"),
        "type": ("cim:SynchronousMachine.type", None),
    },
    "OperationalLimitSet": {
        "terminal_id": ("cim:OperationalLimitSet.Terminal", "ref"),
        "equipment_id": ("cim:OperationalLimitSet.Equipment", "ref"),
    },
    "CurrentLimit": {
        "operational_limit_set_id": (
            "cim:OperationalLimit.OperationalLimitSet",
            "ref",
        ),
        "value_a": ("cim:CurrentLimit.value", None),
        "limit_type": ("cim:OperationalLimit.limitType", None),
    },
    "VoltageLimit": {
        "operational_limit_set_id": (
            "cim:OperationalLimit.OperationalLimitSet",
            "ref",
        ),
        "value_kv": ("cim:VoltageLimit.value", None),
        "limit_type": ("cim:OperationalLimit.limitType", None),
    },
    "Analog": {
        "terminal_id": ("cim:Measurement.Terminal", "ref"),
        "power_system_resource_id": (
            "cim:Measurement.PowerSystemResource",
            "ref",
        ),
        "measurement_type": ("cim:Measurement.measurementType", None),
        "unit_symbol": ("cim:Measurement.unitSymbol", None),
        "positive_flow_in": ("cim:Analog.positiveFlowIn", None),
    },
}

# Map CIM class names to Pydantic model classes
_CIM_CLASS_MAP: dict[str, type[IdentifiedObject]] = {
    "BaseVoltage": BaseVoltage,
    "GeographicalRegion": GeographicalRegion,
    "SubGeographicalRegion": SubGeographicalRegion,
    "Substation": Substation,
    "VoltageLevel": VoltageLevel,
    "Bay": Bay,
    "ConnectivityNode": ConnectivityNode,
    "Terminal": Terminal,
    "TopologicalNode": TopologicalNode,
    "PowerTransformer": PowerTransformer,
    "PowerTransformerEnd": PowerTransformerEnd,
    "ACLineSegment": ACLineSegment,
    "EnergyConsumer": EnergyConsumer,
    "Switch": Switch,
    "Breaker": Breaker,
    "Disconnector": Disconnector,
    "LoadBreakSwitch": LoadBreakSwitch,
    "BusbarSection": BusbarSection,
    "ShuntCompensator": ShuntCompensator,
    "LinearShuntCompensator": LinearShuntCompensator,
    "StaticVarCompensator": StaticVarCompensator,
    "GeneratingUnit": GeneratingUnit,
    "SolarGeneratingUnit": SolarGeneratingUnit,
    "WindGeneratingUnit": WindGeneratingUnit,
    "SynchronousMachine": SynchronousMachine,
    "OperationalLimitSet": OperationalLimitSet,
    "CurrentLimit": CurrentLimit,
    "VoltageLimit": VoltageLimit,
    "Analog": Analog,
}

# Reverse map: CIM property path → (python_field, reverse_converter_key)
_CIM_PROPERTY_REVERSE: dict[str, dict[str, tuple[str, str | None]]] = {}


def _build_reverse_map():
    """Build reverse lookup: cim_property → python_field for import."""
    for cls_name, fields in CIM_FIELD_MAP.items():
        if cls_name not in _CIM_PROPERTY_REVERSE:
            _CIM_PROPERTY_REVERSE[cls_name] = {}
        for py_field, (cim_prop, conv) in fields.items():
            _CIM_PROPERTY_REVERSE[cls_name][cim_prop] = (py_field, conv)


_build_reverse_map()


# ---------------------------------------------------------------------------
# Resolve the full field map for a model class (walk MRO)
# ---------------------------------------------------------------------------
def _resolve_field_map(cls_name: str) -> dict[str, tuple[str, str | None]]:
    """Collect field mappings from the class and all its CIM parents."""
    result = {}
    # Walk the MRO of known CIM base class names
    mro_names = []
    cls = _CIM_CLASS_MAP.get(cls_name)
    if cls:
        for base in cls.__mro__:
            base_name = base.__name__
            if base_name in CIM_FIELD_MAP:
                mro_names.append(base_name)
    # Apply base-first so subclass fields override
    for name in reversed(mro_names):
        result.update(CIM_FIELD_MAP[name])
    return result


# ═══════════════════════════════════════════════════════════════════════════
# RDF/XML Export (IEC 61970-552)
# ═══════════════════════════════════════════════════════════════════════════
def to_rdf_xml(
    models: dict[str, list],
    profile: CIMProfile = CIMProfile.EQ,
    model_id: str | None = None,
    description: str = "Princeps CIM Export",
) -> bytes:
    """Serialize CIM Pydantic models to IEC 61970-552 RDF/XML.

    Args:
        models: Dict of collection name → list of IdentifiedObject instances.
        profile: CGMES profile (EQ, TP, SV, etc.).
        model_id: Unique model identifier (generated if None).
        description: Human-readable model description.

    Returns:
        UTF-8 encoded XML bytes.
    """
    if model_id is None:
        model_id = f"urn:uuid:{uuid.uuid4()}"

    root = ET.Element(f"{{{RDF_NS}}}RDF")

    # FullModel header
    fm = ET.SubElement(root, f"{{{MD_NS}}}FullModel")
    fm.set(f"{{{RDF_NS}}}about", model_id)
    _add_text_elem(fm, f"{{{MD_NS}}}Model.description", description)
    _add_text_elem(fm, f"{{{MD_NS}}}Model.profile", f"http://iec.ch/TC57/61970-552/{profile.value}")
    _add_text_elem(
        fm,
        f"{{{MD_NS}}}Model.created",
        datetime.now(timezone.utc).isoformat(),
    )
    _add_text_elem(fm, f"{{{MD_NS}}}Model.modelingAuthoritySet", "Princeps")

    # Serialize each model object
    for _collection_name, items in models.items():
        for obj in items:
            _serialize_object(root, obj)

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _add_text_elem(parent: ET.Element, tag: str, text: str):
    elem = ET.SubElement(parent, tag)
    elem.text = str(text)


def _serialize_object(root: ET.Element, obj: IdentifiedObject):
    """Serialize one Pydantic CIM model to an RDF/XML element."""
    cls_name = type(obj).__name__
    field_map = _resolve_field_map(cls_name)

    elem = ET.SubElement(root, f"{{{CIM_NS}}}{cls_name}")
    elem.set(f"{{{RDF_NS}}}ID", f"_{obj.mrid}")

    data = obj.model_dump(exclude_none=True, exclude={"mrid"})

    for py_field, value in data.items():
        mapping = field_map.get(py_field)
        if mapping is None:
            continue
        cim_prop, conv = mapping

        # Split cim:Class.property into namespace + local
        prop_tag = f"{{{CIM_NS}}}{cim_prop.removeprefix('cim:')}"

        if conv == "ref":
            # Reference → rdf:resource
            child = ET.SubElement(elem, prop_tag)
            child.set(f"{{{RDF_NS}}}resource", f"#_{value}")
        elif conv and conv in _CONVERTERS:
            if isinstance(value, (int, float)):
                child = ET.SubElement(elem, prop_tag)
                child.text = str(_CONVERTERS[conv](value))
        else:
            child = ET.SubElement(elem, prop_tag)
            if isinstance(value, bool):
                child.text = "true" if value else "false"
            else:
                child.text = str(value)


# ═══════════════════════════════════════════════════════════════════════════
# JSON-LD Export (IEC 61970-556)
# ═══════════════════════════════════════════════════════════════════════════
def to_jsonld(
    models: dict[str, list],
    profile: CIMProfile = CIMProfile.EQ,
    model_id: str | None = None,
    description: str = "Princeps CIM Export",
) -> dict:
    """Serialize CIM models to IEC 61970-556 JSON-LD.

    Returns a dict suitable for json.dumps().
    """
    if model_id is None:
        model_id = f"urn:uuid:{uuid.uuid4()}"

    context = {
        "cim": CIM_NS,
        "rdf": RDF_NS,
        "md": MD_NS,
        "xsd": "http://www.w3.org/2001/XMLSchema#",
    }

    graph: list[dict] = []

    # FullModel header node
    graph.append(
        {
            "@id": model_id,
            "@type": "md:FullModel",
            "md:Model.description": description,
            "md:Model.profile": f"http://iec.ch/TC57/61970-552/{profile.value}",
            "md:Model.created": datetime.now(timezone.utc).isoformat(),
            "md:Model.modelingAuthoritySet": "Princeps",
        }
    )

    for _collection_name, items in models.items():
        for obj in items:
            graph.append(_jsonld_object(obj))

    return {"@context": context, "@graph": graph}


def _jsonld_object(obj: IdentifiedObject) -> dict:
    """Convert one Pydantic CIM model to a JSON-LD node."""
    cls_name = type(obj).__name__
    field_map = _resolve_field_map(cls_name)

    node: dict[str, Any] = {
        "@id": f"urn:uuid:{obj.mrid}",
        "@type": f"cim:{cls_name}",
    }

    data = obj.model_dump(exclude_none=True, exclude={"mrid"})

    for py_field, value in data.items():
        mapping = field_map.get(py_field)
        if mapping is None:
            continue
        cim_prop, conv = mapping

        if conv == "ref":
            node[cim_prop] = {"@id": f"urn:uuid:{value}"}
        elif conv and conv in _CONVERTERS:
            if isinstance(value, (int, float)):
                node[cim_prop] = _CONVERTERS[conv](value)
        else:
            node[cim_prop] = value

    return node


# ═══════════════════════════════════════════════════════════════════════════
# RDF/XML Import (IEC 61970-552)
# ═══════════════════════════════════════════════════════════════════════════
def from_rdf_xml(xml_bytes: bytes) -> dict[str, list]:
    """Parse CIM RDF/XML into typed Pydantic models.

    Auto-detects CIM16 vs CIM100 namespace (same strategy as nged_cim.py).
    Returns dict keyed by collection name → list of model instances.
    """
    root = ET.fromstring(xml_bytes)

    # Auto-detect namespace
    cim_ns = CIM_NS
    if root.findall(f"{{{CIM16_NS}}}Substation"):
        cim_ns = CIM16_NS

    result: dict[str, list] = {}

    # Multi-pass: parse in dependency order
    parse_order = [
        "BaseVoltage",
        "GeographicalRegion",
        "SubGeographicalRegion",
        "Substation",
        "VoltageLevel",
        "Bay",
        "ConnectivityNode",
        "Terminal",
        "TopologicalNode",
        "PowerTransformer",
        "PowerTransformerEnd",
        "ACLineSegment",
        "EnergyConsumer",
        "Switch",
        "Breaker",
        "Disconnector",
        "LoadBreakSwitch",
        "BusbarSection",
        "ShuntCompensator",
        "LinearShuntCompensator",
        "StaticVarCompensator",
        "GeneratingUnit",
        "SolarGeneratingUnit",
        "WindGeneratingUnit",
        "SynchronousMachine",
        "OperationalLimitSet",
        "CurrentLimit",
        "VoltageLimit",
        "Analog",
    ]

    for cls_name in parse_order:
        model_cls = _CIM_CLASS_MAP.get(cls_name)
        if model_cls is None:
            continue

        elements = root.findall(f"{{{cim_ns}}}{cls_name}")
        if not elements:
            continue

        items = []
        for elem in elements:
            obj = _parse_rdf_element(elem, cls_name, model_cls, cim_ns)
            if obj:
                items.append(obj)

        if items:
            # Use plural snake_case collection name
            collection = _pluralize(cls_name)
            result[collection] = items

    return result


def _parse_rdf_element(
    elem: ET.Element,
    cls_name: str,
    model_cls: type,
    cim_ns: str,
) -> IdentifiedObject | None:
    """Parse a single RDF element into a Pydantic model."""
    mrid = _extract_rdf_id(elem)
    if not mrid:
        return None

    field_map = _resolve_field_map(cls_name)
    kwargs: dict[str, Any] = {"mrid": mrid}

    for py_field, (cim_prop, conv) in field_map.items():
        local_name = cim_prop.removeprefix("cim:")
        tag = f"{{{cim_ns}}}{local_name}"
        child = elem.find(tag)
        if child is None:
            continue

        if conv == "ref":
            ref = child.get(f"{{{RDF_NS}}}resource", "")
            ref = ref.lstrip("#").lstrip("_")
            if ref:
                kwargs[py_field] = ref
        else:
            text = child.text
            if text is None:
                continue
            text = text.strip()

            # Determine target type from the model field
            field_info = model_cls.model_fields.get(py_field)
            if field_info is None:
                continue

            # Apply reverse unit conversion
            rev_conv = _REVERSE_CONVERTERS.get(conv) if conv else None
            try:
                if _is_bool_field(field_info):
                    kwargs[py_field] = text.lower() in ("true", "1", "yes")
                elif _is_int_field(field_info):
                    kwargs[py_field] = int(float(text))
                elif _is_float_field(field_info):
                    val = float(text)
                    if rev_conv:
                        val = rev_conv(val)
                    kwargs[py_field] = val
                else:
                    kwargs[py_field] = text
            except (ValueError, TypeError):
                pass

    try:
        return model_cls(**kwargs)
    except Exception as exc:
        log.warning("Failed to parse %s mrid=%s: %s", cls_name, mrid, exc)
        return None


def _extract_rdf_id(elem: ET.Element) -> str:
    """Extract rdf:ID or rdf:about, stripping leading _ prefix."""
    raw = (
        elem.get(f"{{{RDF_NS}}}ID")
        or elem.get(f"{{{RDF_NS}}}about", "").lstrip("#")
        or ""
    )
    return raw.lstrip("_") if raw else ""


def _is_bool_field(field_info) -> bool:
    ann = field_info.annotation
    return ann is bool or (hasattr(ann, "__origin__") and bool in getattr(ann, "__args__", ()))


def _is_int_field(field_info) -> bool:
    ann = field_info.annotation
    return ann is int or (hasattr(ann, "__origin__") and int in getattr(ann, "__args__", ()))


def _is_float_field(field_info) -> bool:
    ann = field_info.annotation
    return ann is float or (hasattr(ann, "__origin__") and float in getattr(ann, "__args__", ()))


def _pluralize(cls_name: str) -> str:
    """Convert CIM class name to plural snake_case collection key."""
    import re

    # Insert _ before uppercase that follows lowercase or before a run of
    # uppercase followed by a lowercase (handles "ACLine" → "ac_line")
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", cls_name)
    snake = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", snake)
    snake = snake.lower()
    # Simple pluralisation
    if snake.endswith("y") and not snake.endswith("ay"):
        return snake[:-1] + "ies"
    if snake.endswith("s") or snake.endswith("x"):
        return snake + "es"
    return snake + "s"


# ═══════════════════════════════════════════════════════════════════════════
# JSON-LD Import (IEC 61970-556)
# ═══════════════════════════════════════════════════════════════════════════
def from_jsonld(data: dict) -> dict[str, list]:
    """Parse CIM JSON-LD into typed Pydantic models.

    Expects {"@context": {...}, "@graph": [...]}.
    """
    graph = data.get("@graph", [])
    result: dict[str, list] = {}

    for node in graph:
        type_str = node.get("@type", "")
        # Strip cim: prefix
        cls_name = type_str.removeprefix("cim:")
        if cls_name.startswith("md:"):
            continue  # Skip FullModel header

        model_cls = _CIM_CLASS_MAP.get(cls_name)
        if model_cls is None:
            continue

        obj = _parse_jsonld_node(node, cls_name, model_cls)
        if obj:
            collection = _pluralize(cls_name)
            result.setdefault(collection, []).append(obj)

    return result


def _parse_jsonld_node(
    node: dict,
    cls_name: str,
    model_cls: type,
) -> IdentifiedObject | None:
    """Parse a single JSON-LD @graph node into a Pydantic model."""
    # Extract MRID from @id
    node_id = node.get("@id", "")
    mrid = node_id.removeprefix("urn:uuid:")
    if not mrid:
        return None

    field_map = _resolve_field_map(cls_name)
    kwargs: dict[str, Any] = {"mrid": mrid}

    for py_field, (cim_prop, conv) in field_map.items():
        value = node.get(cim_prop)
        if value is None:
            continue

        if conv == "ref":
            # JSON-LD references: {"@id": "urn:uuid:xxx"}
            if isinstance(value, dict):
                ref = value.get("@id", "")
                kwargs[py_field] = ref.removeprefix("urn:uuid:")
            elif isinstance(value, str):
                kwargs[py_field] = value.removeprefix("urn:uuid:")
        else:
            rev_conv = _REVERSE_CONVERTERS.get(conv) if conv else None
            field_info = model_cls.model_fields.get(py_field)
            if field_info is None:
                continue
            try:
                if _is_bool_field(field_info):
                    kwargs[py_field] = bool(value) if not isinstance(value, bool) else value
                elif _is_int_field(field_info):
                    val = float(value) if not isinstance(value, (int, float)) else value
                    kwargs[py_field] = int(val)
                elif _is_float_field(field_info):
                    val = float(value) if not isinstance(value, (int, float)) else value
                    if rev_conv:
                        val = rev_conv(val)
                    kwargs[py_field] = val
                else:
                    kwargs[py_field] = str(value)
            except (ValueError, TypeError):
                pass

    try:
        return model_cls(**kwargs)
    except Exception as exc:
        log.warning("Failed to parse JSON-LD %s mrid=%s: %s", cls_name, mrid, exc)
        return None

"""IFC4 generation pipeline — converts a Princeps twin hierarchy into a
valid IFC4 model via IfcOpenShell 0.8.x.

Each twin_instance becomes a typed IFC entity (IfcSite / IfcBuilding /
IfcSpace / IfcEquipment) with a stable IFC GlobalId derived from the
Princeps RID via UUIDv5 — this is the tag-binding spine that lets the
3D viewer pick a mesh and hand back the matching RID.

v1 emits a valid spatial hierarchy without 3D body geometry. Geometry
representations land in the next iteration via the `geometry` API
(extruded box per IfcSpace / IfcEquipment).
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger("princeps.twin.cad")

# UUIDv5 namespace — stable RID → GlobalId mapping.
_RID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def rid_to_global_id(rid: str) -> str:
    """Stable IFC GlobalId for any Princeps RID. Two calls with the same
    RID always return the same 22-char compressed GUID.
    """
    import ifcopenshell.guid  # lazy
    u = uuid.uuid5(_RID_NAMESPACE, rid)
    return ifcopenshell.guid.compress(u.hex)


def _api(op, f=None, **kwargs):
    """ifcopenshell.api.run dispatcher wrapper — `op` is the operation
    name (e.g. 'root.create_entity'). Renamed from `name` to avoid
    collision with the very common `name=...` kwarg on entity creation.
    """
    import ifcopenshell.api  # lazy
    if f is None:
        return ifcopenshell.api.run(op, **kwargs)
    return ifcopenshell.api.run(op, f, **kwargs)


def _add_box(f, body_context, product, w, d, h, x=0, y=0, z=0):
    """Attach an extruded-box geometry body to an IfcProduct, placed at
    world (x, y, z). The ShapeBuilder.extrude `position` kwarg bakes the
    placement directly into the IfcExtrudedAreaSolid — much cleaner than
    futzing with IfcLocalPlacement matrices afterwards.
    """
    import ifcopenshell.api  # lazy
    import ifcopenshell.util.shape_builder as _sb
    try:
        builder = _sb.ShapeBuilder(f)
        # Centre the rectangle on the local origin so x,y of position is the box centroid.
        profile = builder.rectangle(size=(float(w), float(d)))
        # Position is the (x, y, z) of the extrusion base in world coords.
        # Offset by (-w/2, -d/2) so the position kwarg refers to the box CENTRE.
        solid = builder.extrude(
            profile,
            magnitude=float(h),
            position=(float(x) - float(w) / 2, float(y) - float(d) / 2, float(z)),
        )
        rep = builder.get_representation(body_context, [solid])
        ifcopenshell.api.run(
            "geometry.assign_representation",
            f, product=product, representation=rep,
        )
    except Exception as exc:
        log.warning("geometry skipped on %s %s: %s",
                    product.is_a(), getattr(product, "Name", "?"), exc)


def _translation_matrix(x, y, z):
    """4×4 row-major translation matrix as a numpy array (or list fallback)."""
    try:
        import numpy as np
        m = np.eye(4)
        m[0, 3] = x; m[1, 3] = y; m[2, 3] = z
        return m
    except ImportError:
        return [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]]


def convert_ifc_to_glb(ifc_path: Path, glb_path: Path) -> dict[str, Any]:
    """Convert an IFC file to glTF binary (.glb) via ifcopenshell.geom's
    SWIG-bound GltfSerializer. Streams shapes via the iterator pattern.
    """
    import ifcopenshell           # lazy
    import ifcopenshell.geom      # lazy

    ifc_file = ifcopenshell.open(str(ifc_path))
    settings = ifcopenshell.geom.settings()
    ser_settings = ifcopenshell.geom.serializer_settings()

    serializer = ifcopenshell.geom.serializers.gltf(
        str(glb_path), settings, ser_settings,
    )
    serializer.setFile(ifc_file)
    serializer.setUnitNameAndMagnitude("METRE", 1.0)
    serializer.writeHeader()

    iterator = ifcopenshell.geom.iterator(settings, ifc_file)
    shapes_written = 0
    if iterator.initialize():
        while True:
            try:
                shape = iterator.get()
                serializer.write(shape)
                shapes_written += 1
            except Exception as exc:
                log.warning("glTF write failed for shape: %s", exc)
            if not iterator.next():
                break
    serializer.finalize()

    return {"glb_path": str(glb_path), "shapes_written": shapes_written}


def build_dc_ifc(subtree: dict, out_path: Path) -> dict[str, Any]:
    """Build a valid IFC4 model from a DataCentre subtree.

    Args:
        subtree: {nodes: [...], edges: [...]} from /api/workshop/scene/<rid>.
        out_path: where to write the .ifc file.

    Returns:
        {ifc_path, node_count, ifc_entity_count, halls, aisles}
    """
    f = _api("project.create_file")
    project = _api("root.create_entity", f, ifc_class="IfcProject", name="Princeps DC Twin")
    _api("unit.assign_unit", f)
    model_ctx = _api("context.add_context", f, context_type="Model")
    body_ctx = _api("context.add_context", f, context_type="Model",
                    context_identifier="Body", target_view="MODEL_VIEW",
                    parent=model_ctx)

    nodes_by_rid = {n["rid"]: n for n in subtree.get("nodes", [])}
    edges = subtree.get("edges", [])

    root = next((n for n in subtree["nodes"]
                 if n["dtmi"] == "dtmi:com:princeps:DataCentre;1"), None)
    if not root:
        raise ValueError("No DataCentre root in subtree")

    site = _api("root.create_entity", f, ifc_class="IfcSite",
                name=root["properties"].get("name", "Site"))
    site.GlobalId = rid_to_global_id(root["rid"] + ":site")
    _api("aggregate.assign_object", f, products=[site], relating_object=project)

    building = _api("root.create_entity", f, ifc_class="IfcBuilding",
                    name=root["properties"].get("name", "DataCentre"))
    building.GlobalId = rid_to_global_id(root["rid"])
    _api("aggregate.assign_object", f, products=[building], relating_object=site)

    halls = [n for n in subtree["nodes"]
             if n["dtmi"] == "dtmi:com:princeps:DcHall;1"]
    space_by_rid: dict[str, Any] = {}

    # Layout halls along X — 50 m W × 30 m D × 8 m H, 8 m gap.
    HALL_W, HALL_D, HALL_H, HALL_GAP = 50.0, 30.0, 8.0, 8.0
    total_w = len(halls) * HALL_W + max(0, len(halls) - 1) * HALL_GAP
    start_x = -total_w / 2 + HALL_W / 2

    for i, hall in enumerate(halls):
        cx = start_x + i * (HALL_W + HALL_GAP)
        space = _api("root.create_entity", f, ifc_class="IfcSpace",
                     name=hall["properties"].get("hallId", "HALL"))
        space.GlobalId = rid_to_global_id(hall["rid"])
        space_by_rid[hall["rid"]] = space
        _api("aggregate.assign_object", f, products=[space], relating_object=building)
        _add_box(f, body_ctx, space, HALL_W, HALL_D, HALL_H, x=cx, y=0, z=0)

    aisles_by_hall: dict[str, list[str]] = {}
    for e in edges:
        if e.get("rel_name") == "containsAisle":
            aisles_by_hall.setdefault(e["from_rid"], []).append(e["to_rid"])

    AISLE_W, AISLE_D, AISLE_H = HALL_W * 0.85, 1.6, 2.4
    aisle_count = 0
    for hall_rid, aisle_rids in aisles_by_hall.items():
        hall_space = space_by_rid.get(hall_rid)
        if not hall_space:
            continue
        hall_idx = next((i for i, h in enumerate(halls) if h["rid"] == hall_rid), 0)
        hcx = start_x + hall_idx * (HALL_W + HALL_GAP)
        spacing = HALL_D / (len(aisle_rids) + 1)
        for j, aisle_rid in enumerate(aisle_rids):
            n = nodes_by_rid.get(aisle_rid)
            if not n:
                continue
            aisle = _api("root.create_entity", f, ifc_class="IfcSpace",
                         name=n["properties"].get("aisleId", "AISLE"))
            aisle.GlobalId = rid_to_global_id(aisle_rid)
            _api("aggregate.assign_object", f, products=[aisle], relating_object=hall_space)
            cz = -HALL_D / 2 + (j + 1) * spacing
            _add_box(f, body_ctx, aisle, AISLE_W, AISLE_D, AISLE_H, x=hcx, y=cz, z=0.2)
            aisle_count += 1

    f.write(str(out_path))

    return {
        "ifc_path": str(out_path),
        "node_count": len(subtree["nodes"]),
        "ifc_entity_count": len(f.by_type("IfcRoot")),
        "halls": len(halls),
        "aisles": aisle_count,
    }


def build_bess_ifc(subtree: dict, out_path: Path) -> dict[str, Any]:
    """Build IFC4 from a BESSUnit subtree. Blocks → IfcSpace, Racks → IfcEquipment."""
    f = _api("project.create_file")
    project = _api("root.create_entity", f, ifc_class="IfcProject", name="Princeps BESS Twin")
    _api("unit.assign_unit", f)
    model_ctx = _api("context.add_context", f, context_type="Model")
    body_ctx = _api("context.add_context", f, context_type="Model",
                    context_identifier="Body", target_view="MODEL_VIEW",
                    parent=model_ctx)

    nodes = subtree.get("nodes", [])
    nodes_by_rid = {n["rid"]: n for n in nodes}
    edges = subtree.get("edges", [])

    root = next((n for n in nodes
                 if n["dtmi"] == "dtmi:com:princeps:BESSUnit;1"), None)
    if not root:
        raise ValueError("No BESSUnit root in subtree")

    site = _api("root.create_entity", f, ifc_class="IfcSite",
                name=root["properties"].get("name", "BESS Site"))
    site.GlobalId = rid_to_global_id(root["rid"] + ":site")
    _api("aggregate.assign_object", f, products=[site], relating_object=project)

    facility = _api("root.create_entity", f, ifc_class="IfcBuilding",
                    name=root["properties"].get("name", "BESS Facility"))
    facility.GlobalId = rid_to_global_id(root["rid"])
    _api("aggregate.assign_object", f, products=[facility], relating_object=site)

    blocks = [n for n in nodes if n["dtmi"] == "dtmi:com:princeps:BessBlock;1"]
    block_by_rid: dict[str, Any] = {}

    BLOCK_W, BLOCK_D, BLOCK_H, GAP = 12.0, 2.5, 2.6, 2.0
    total_w = len(blocks) * BLOCK_W + max(0, len(blocks) - 1) * GAP
    start_x = -total_w / 2 + BLOCK_W / 2

    for i, block in enumerate(blocks):
        cx = start_x + i * (BLOCK_W + GAP)
        space = _api("root.create_entity", f, ifc_class="IfcSpace",
                     name=block["properties"].get("blockId", "BLK"))
        space.GlobalId = rid_to_global_id(block["rid"])
        block_by_rid[block["rid"]] = space
        _api("aggregate.assign_object", f, products=[space], relating_object=facility)
        _add_box(f, body_ctx, space, BLOCK_W, BLOCK_D, BLOCK_H, x=cx, y=0, z=0)

    racks_by_block: dict[str, list[str]] = {}
    for e in edges:
        if e.get("rel_name") == "containsRack":
            racks_by_block.setdefault(e["from_rid"], []).append(e["to_rid"])

    rack_count = 0
    for block_rid, rack_rids in racks_by_block.items():
        block_space = block_by_rid.get(block_rid)
        if not block_space:
            continue
        block_idx = next((i for i, b in enumerate(blocks) if b["rid"] == block_rid), 0)
        bcx = start_x + block_idx * (BLOCK_W + GAP)
        rack_w = (BLOCK_W - 1.2) / max(len(rack_rids), 1)
        for j, rack_rid in enumerate(rack_rids):
            n = nodes_by_rid.get(rack_rid)
            if not n:
                continue
            equip = _api("root.create_entity", f, ifc_class="IfcBuildingElementProxy",
                         name=n["properties"].get("rackId", "RACK"))
            equip.GlobalId = rid_to_global_id(rack_rid)
            _api("aggregate.assign_object", f, products=[equip], relating_object=block_space)
            rx = bcx - BLOCK_W / 2 + 0.6 + (j + 0.5) * rack_w
            _add_box(f, body_ctx, equip, rack_w * 0.6, BLOCK_D * 0.45, BLOCK_H * 0.85,
                     x=rx, y=0, z=0.05)
            rack_count += 1

    f.write(str(out_path))
    return {
        "ifc_path": str(out_path),
        "node_count": len(nodes),
        "ifc_entity_count": len(f.by_type("IfcRoot")),
        "blocks": len(blocks),
        "racks": rack_count,
    }

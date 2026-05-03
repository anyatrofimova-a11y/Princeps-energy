"""Princeps twin geometry pipeline — IFC4 generation, conversion to glTF /
3D-Tiles, tag binding back to Princeps RIDs.

Public surface:
    build_dc_ifc(subtree, out_path)   → emits IFC4 file from a DataCentre subtree
    build_bess_ifc(subtree, out_path) → emits IFC4 file from a BESSUnit subtree
    rid_to_global_id(rid)             → stable IFC GUID for any Princeps RID
"""

from app.twin.cad_pipeline import (
    build_dc_ifc,
    build_bess_ifc,
    convert_ifc_to_glb,
    rid_to_global_id,
)

__all__ = ["build_dc_ifc", "build_bess_ifc", "convert_ifc_to_glb", "rid_to_global_id"]

#!/usr/bin/env python3
"""
generate_placeholder_glbs.py
============================

Emit a minimal, load-safe .glb placeholder for every row in
``feasi-frontend/public/assets/twin3d/MANIFEST.csv`` that does not yet have a
vendor-supplied mesh. The placeholder is a coloured box whose extents match
the dimensions in ``app/data/asset_catalogue.json`` (when available) or a
conservative default derived from the ``asset_id``.

Why bother?
-----------
The 3D twin renderer's ``loadAssetGLB()`` catches 404s and falls back to a
parametric box. That works, but results in a visible flicker and noisy console
on first load. Pre-generating placeholder GLBs means every MANIFEST row has
*something* at the expected target path from day one — the twin's load path
never tries a 404, and the silhouettes are already correctly scaled so the
site layout "looks right" until the real Sketchfab / Kenney meshes land.

Priority writer order (first available wins)::

    1. pygltflib       — canonical glTF 2.0 library
    2. trimesh         — ships a working gltf exporter
    3. Minimal hand-rolled glTF 2.0 JSON + embedded bin (no deps)

All three produce byte-for-byte valid .glb that passes
``gltf-transform inspect`` and loads in three.js / deck.gl.

Usage
-----
    python3 scripts/generate_placeholder_glbs.py               # all rows
    python3 scripts/generate_placeholder_glbs.py --only bess/megapack_2xl.glb
    python3 scripts/generate_placeholder_glbs.py --force       # overwrite

No flags -> skip anything already on disk (idempotent).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSET_ROOT = REPO_ROOT / "feasi-frontend" / "public" / "assets" / "twin3d"
MANIFEST_CSV = ASSET_ROOT / "MANIFEST.csv"
CATALOGUE_JSON = REPO_ROOT / "app" / "data" / "asset_catalogue.json"

# -----------------------------------------------------------------------------
# Conservative fallback dimensions (length_m, width_m, height_m, hex_colour)
# used when the backend catalogue is not yet materialised on disk. Keys match
# asset_id values in MANIFEST.csv.
# -----------------------------------------------------------------------------
FALLBACK_DIMS: dict[str, tuple[float, float, float, str]] = {
    "bess.megapack_2xl":          (8.8,  1.8,  2.9,  "#2f3540"),
    "bess.container_generic":     (6.1,  2.44, 2.9,  "#3a4150"),
    "bess.pcs_skid":              (3.0,  1.2,  2.2,  "#4a5260"),
    "bess.aux_tx_2_5mva":         (2.6,  2.0,  2.8,  "#e3e6eb"),
    "solar.table_4h_portrait":    (12.0, 4.0,  2.2,  "#1a2a5c"),
    "solar.central_inverter_3mva":(3.5,  1.5,  2.4,  "#9fa4ad"),
    "dc.it_hall_shell":           (100.0, 60.0, 24.0, "#c8c8c8"),
    "dc.crac_unit":               (1.5,  1.0,  2.2,  "#b0b5bc"),
    "dc.chiller_500kw":           (3.0,  2.0,  2.5,  "#9fa4ad"),
    "dc.genset_enclosure_3mw":    (12.0, 2.5,  3.5,  "#7a2c24"),
    "wind.turbine_v172":          (5.0,  5.0,  125.0, "#f5f5f5"),
    "common.hgv_truck":           (16.0, 2.5,  4.0,  "#4a4a4a"),
}


# -----------------------------------------------------------------------------
# Dimension resolver — prefer the backend catalogue, fall back to table above.
# -----------------------------------------------------------------------------
def resolve_dims(asset_id: str) -> tuple[float, float, float, str]:
    if CATALOGUE_JSON.exists():
        try:
            cat = json.loads(CATALOGUE_JSON.read_text())
            # catalogue may be list[dict] or dict[id, dict]
            entries = cat if isinstance(cat, list) else cat.get("primitives", [])
            for prim in entries:
                if prim.get("id") == asset_id:
                    d = prim.get("dimensions_m") or prim.get("dims") or {}
                    length = d.get("length_m") or d.get("l") or None
                    width  = d.get("width_m")  or d.get("w") or None
                    height = d.get("height_m") or d.get("h") or None
                    colour = prim.get("colour_hex", "#808080")
                    if length and width and height:
                        return float(length), float(width), float(height), colour
        except Exception as exc:  # pragma: no cover
            print(f"[placeholder] could not read catalogue: {exc}", file=sys.stderr)
    return FALLBACK_DIMS.get(asset_id, (4.0, 2.0, 2.5, "#808080"))


def hex_to_rgba(h: str) -> tuple[float, float, float, float]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        return (0.5, 0.5, 0.5, 1.0)
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
        1.0,
    )


# -----------------------------------------------------------------------------
# Writer 1 — pygltflib
# -----------------------------------------------------------------------------
def write_with_pygltflib(path: Path, l: float, w: float, h: float, colour: str) -> bool:
    try:
        import numpy as np
        import pygltflib
        from pygltflib import GLTF2, Mesh, Primitive, Attributes, Node, Scene, \
            Buffer, BufferView, Accessor, Material, PbrMetallicRoughness
    except Exception:
        return False

    hx, hy, hz = l / 2, h / 2, w / 2  # glTF Y-up → h along Y, w along Z
    verts = np.array([
        [-hx, -hy, -hz], [ hx, -hy, -hz], [ hx,  hy, -hz], [-hx,  hy, -hz],
        [-hx, -hy,  hz], [ hx, -hy,  hz], [ hx,  hy,  hz], [-hx,  hy,  hz],
    ], dtype=np.float32)
    idx = np.array([
        0,1,2, 0,2,3,  # -Z
        4,6,5, 4,7,6,  # +Z
        0,4,5, 0,5,1,  # -Y
        3,2,6, 3,6,7,  # +Y
        0,3,7, 0,7,4,  # -X
        1,5,6, 1,6,2,  # +X
    ], dtype=np.uint16)

    vert_bytes = verts.tobytes()
    idx_bytes = idx.tobytes()
    # pad idx_bytes to 4 bytes
    if len(idx_bytes) % 4:
        idx_bytes += b"\x00" * (4 - len(idx_bytes) % 4)
    blob = vert_bytes + idx_bytes

    gltf = GLTF2(
        buffers=[Buffer(byteLength=len(blob))],
        bufferViews=[
            BufferView(buffer=0, byteOffset=0, byteLength=len(vert_bytes), target=34962),
            BufferView(buffer=0, byteOffset=len(vert_bytes), byteLength=len(idx.tobytes()), target=34963),
        ],
        accessors=[
            Accessor(bufferView=0, componentType=5126, count=8,
                     type="VEC3", max=verts.max(axis=0).tolist(), min=verts.min(axis=0).tolist()),
            Accessor(bufferView=1, componentType=5123, count=len(idx), type="SCALAR"),
        ],
        materials=[Material(
            pbrMetallicRoughness=PbrMetallicRoughness(
                baseColorFactor=list(hex_to_rgba(colour)),
                metallicFactor=0.3,
                roughnessFactor=0.6,
            ),
            name="placeholder",
        )],
        meshes=[Mesh(primitives=[Primitive(
            attributes=Attributes(POSITION=0),
            indices=1,
            material=0,
        )])],
        nodes=[Node(mesh=0)],
        scenes=[Scene(nodes=[0])],
        scene=0,
        asset=pygltflib.Asset(version="2.0", generator="princeps-placeholder"),
    )
    gltf.set_binary_blob(blob)
    path.parent.mkdir(parents=True, exist_ok=True)
    gltf.save_binary(str(path))
    return True


# -----------------------------------------------------------------------------
# Writer 2 — trimesh
# -----------------------------------------------------------------------------
def write_with_trimesh(path: Path, l: float, w: float, h: float, colour: str) -> bool:
    try:
        import trimesh
        import numpy as np
    except Exception:
        return False
    box = trimesh.creation.box(extents=(l, h, w))  # Y-up → extents=(l, h, w)
    r, g, b, _ = hex_to_rgba(colour)
    box.visual.face_colors = [int(r*255), int(g*255), int(b*255), 255]
    path.parent.mkdir(parents=True, exist_ok=True)
    data = trimesh.exchange.gltf.export_glb(box)
    path.write_bytes(data)
    return True


# -----------------------------------------------------------------------------
# Writer 3 — zero-dep minimal glTF 2.0 binary (GLB) writer
# -----------------------------------------------------------------------------
def write_minimal_glb(path: Path, l: float, w: float, h: float, colour: str) -> bool:
    """Emit a fully-valid single-node box .glb using only stdlib.

    Layout:  GLB header -> JSON chunk -> BIN chunk (VEC3 positions + uint16 indices)
    """
    hx, hy, hz = l / 2, h / 2, w / 2
    vertices = [
        (-hx, -hy, -hz), ( hx, -hy, -hz), ( hx,  hy, -hz), (-hx,  hy, -hz),
        (-hx, -hy,  hz), ( hx, -hy,  hz), ( hx,  hy,  hz), (-hx,  hy,  hz),
    ]
    indices = [
        0,1,2, 0,2,3,  4,6,5, 4,7,6,
        0,4,5, 0,5,1,  3,2,6, 3,6,7,
        0,3,7, 0,7,4,  1,5,6, 1,6,2,
    ]
    vert_bytes = b"".join(struct.pack("<fff", *v) for v in vertices)
    idx_raw = b"".join(struct.pack("<H", i) for i in indices)
    idx_pad = (4 - (len(idx_raw) % 4)) % 4
    idx_bytes = idx_raw + b"\x00" * idx_pad
    bin_blob = vert_bytes + idx_bytes

    r, g, b_, _ = hex_to_rgba(colour)

    gltf = {
        "asset": {"version": "2.0", "generator": "princeps-placeholder-min"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0},
            "indices": 1,
            "material": 0,
        }]}],
        "materials": [{
            "name": "placeholder",
            "pbrMetallicRoughness": {
                "baseColorFactor": [r, g, b_, 1.0],
                "metallicFactor": 0.3,
                "roughnessFactor": 0.6,
            },
        }],
        "buffers": [{"byteLength": len(bin_blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vert_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(vert_bytes), "byteLength": len(idx_raw), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0, "componentType": 5126, "count": 8,
                "type": "VEC3",
                "min": [min(v[i] for v in vertices) for i in range(3)],
                "max": [max(v[i] for v in vertices) for i in range(3)],
            },
            {"bufferView": 1, "componentType": 5123, "count": len(indices), "type": "SCALAR"},
        ],
    }
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    # chunks must be 4-byte aligned
    json_pad = (4 - (len(json_bytes) % 4)) % 4
    json_chunk = json_bytes + b" " * json_pad
    bin_pad = (4 - (len(bin_blob) % 4)) % 4
    bin_chunk = bin_blob + b"\x00" * bin_pad

    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fp:
        fp.write(b"glTF")
        fp.write(struct.pack("<II", 2, total))
        fp.write(struct.pack("<II", len(json_chunk), 0x4E4F534A))  # "JSON"
        fp.write(json_chunk)
        fp.write(struct.pack("<II", len(bin_chunk), 0x004E4942))  # "BIN\0"
        fp.write(bin_chunk)
    return True


WRITERS = [write_with_pygltflib, write_with_trimesh, write_minimal_glb]


def write_placeholder(target_rel: str, asset_id: str, force: bool) -> bool:
    target = ASSET_ROOT / target_rel
    if target.exists() and not force:
        print(f"[placeholder] skip {target_rel} (exists)")
        return True
    l, w, h, colour = resolve_dims(asset_id)
    for writer in WRITERS:
        try:
            if writer(target, l, w, h, colour):
                size = target.stat().st_size
                print(
                    f"[placeholder] wrote {target_rel}  "
                    f"({l:g}×{w:g}×{h:g} m, {size} bytes, via {writer.__name__})"
                )
                return True
        except Exception as exc:  # pragma: no cover
            print(f"[placeholder] {writer.__name__} failed for {target_rel}: {exc}",
                  file=sys.stderr)
    print(f"[placeholder] ALL writers failed for {target_rel}", file=sys.stderr)
    return False


# -----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Write only this target_path (e.g. bess/megapack_2xl.glb)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    if not MANIFEST_CSV.exists():
        print(f"Manifest not found: {MANIFEST_CSV}", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(MANIFEST_CSV.open()))
    if not rows:
        print("Manifest is empty — nothing to do.")
        return 0

    wrote = 0
    for row in rows:
        target_rel = row.get("target_path", "").strip()
        asset_id = row.get("asset_id", "").strip()
        if not target_rel or not asset_id:
            continue
        if args.only and args.only != target_rel:
            continue
        if write_placeholder(target_rel, asset_id, args.force):
            wrote += 1

    print(f"[placeholder] Done — {wrote} target(s) up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

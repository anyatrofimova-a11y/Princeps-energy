"""OpenUSD scene exporter for Princeps.

Generates USDA (ASCII) files compatible with NVIDIA Omniverse DSX Blueprint.
No binary dependencies — pure string-based USDA generation.

Exports site terrain, substations, power lines, and placed assets
(solar arrays, BESS, transformers, DC buildings) as a complete 3D scene.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("princeps.usd_exporter")

# ---------------------------------------------------------------------------
# Princeps colour scheme (linear RGB, 0-1)
# ---------------------------------------------------------------------------

COLORS = {
    "terrain":     (0.35, 0.55, 0.25),   # muted green
    "substation":  (0.75, 0.20, 0.20),   # red
    "solar":       (0.15, 0.25, 0.65),   # dark blue
    "bess":        (0.20, 0.70, 0.35),   # green
    "transformer": (0.85, 0.55, 0.10),   # amber
    "dc_building": (0.50, 0.50, 0.55),   # grey
    "power_line":  (0.10, 0.10, 0.10),   # near-black
    "default":     (0.60, 0.60, 0.60),   # mid grey
}

# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _latlon_to_local(lat: float, lon: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    """Convert WGS84 lat/lon to local metres relative to an origin point.

    Uses equirectangular approximation — accurate within ~50 km of origin.
    Returns (x_east, z_north) in metres.  Y is up in the USD scene.
    """
    R = 6_371_000.0  # Earth radius in metres
    d_lat = math.radians(lat - origin_lat)
    d_lon = math.radians(lon - origin_lon)
    cos_lat = math.cos(math.radians(origin_lat))
    x = d_lon * R * cos_lat
    z = d_lat * R
    return (round(x, 2), round(z, 2))


def _sanitize_name(name: str) -> str:
    """Make a string safe for use as a USD prim name (alphanumeric + underscore)."""
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        elif ch in (" ", "-", "/", "."):
            out.append("_")
    result = "".join(out)
    # Must start with a letter or underscore
    if result and result[0].isdigit():
        result = "_" + result
    return result or "Unnamed"


# ---------------------------------------------------------------------------
# USDA primitives
# ---------------------------------------------------------------------------

def _indent(text: str, level: int = 1) -> str:
    pad = "    " * level
    return "\n".join(pad + line for line in text.splitlines())


def _material_block(name: str, color: tuple[float, float, float]) -> str:
    """Generate a UsdPreviewSurface material definition."""
    r, g, b = color
    return f'''def Material "{name}"
{{
    token outputs:surface.connect = </{name}/PBRShader.outputs:surface>

    def Shader "PBRShader"
    {{
        uniform token info:id = "UsdPreviewSurface"
        color3f inputs:diffuseColor = ({r:.3f}, {g:.3f}, {b:.3f})
        float inputs:roughness = 0.7
        float inputs:metallic = 0.1
        token outputs:surface
    }}
}}'''


def _xform_translate(x: float, y: float, z: float) -> str:
    return (
        f"double3 xformOp:translate = ({x}, {y}, {z})\n"
        f"        uniform token[] xformOpOrder = [\"xformOp:translate\", \"xformOp:scale\"]"
    )


def _xform_translate_scale(
    tx: float, ty: float, tz: float,
    sx: float, sy: float, sz: float,
) -> str:
    return (
        f"double3 xformOp:translate = ({tx}, {ty}, {tz})\n"
        f"        double3 xformOp:scale = ({sx}, {sy}, {sz})\n"
        f"        uniform token[] xformOpOrder = [\"xformOp:translate\", \"xformOp:scale\"]"
    )


# ---------------------------------------------------------------------------
# Terrain mesh
# ---------------------------------------------------------------------------

def _terrain_mesh(
    heightmap: dict | None,
    origin_lat: float,
    origin_lon: float,
) -> str:
    """Generate a ground plane Mesh prim.

    If *heightmap* is provided it should contain:
        width, height: grid dimensions
        data: list of elevation values (row-major)
        cell_size_m: spacing between samples
        origin_lat, origin_lon: SW corner of the grid (optional, defaults to site origin)
    Otherwise a flat 2 km x 2 km quad is emitted.
    """
    if heightmap and heightmap.get("data"):
        return _terrain_from_heightmap(heightmap, origin_lat, origin_lon)

    # Flat ground plane: 2 km square centred on origin
    half = 1000.0
    return f'''def Mesh "Terrain"
{{
    int[] faceVertexCounts = [4]
    int[] faceVertexIndices = [0, 1, 2, 3]
    point3f[] points = [({-half}, 0, {-half}), ({half}, 0, {-half}), ({half}, 0, {half}), ({-half}, 0, {half})]
    normal3f[] normals = [(0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0)]
    uniform token subdivisionScheme = "none"
    rel material:binding = </World/Materials/TerrainMat>
    custom string princeps:type = "terrain"
}}'''


def _terrain_from_heightmap(hm: dict, origin_lat: float, origin_lon: float) -> str:
    """Build a triangulated mesh from a heightmap grid."""
    w = int(hm.get("width", 0))
    h = int(hm.get("height", 0))
    cell = float(hm.get("cell_size_m", 10))
    data = hm["data"]

    if w * h != len(data):
        log.warning("Heightmap size mismatch %d x %d != %d, falling back to flat", w, h, len(data))
        return _terrain_mesh(None, origin_lat, origin_lon)

    # Centre the grid on origin
    x_off = -(w - 1) * cell / 2
    z_off = -(h - 1) * cell / 2

    points = []
    for row in range(h):
        for col in range(w):
            px = x_off + col * cell
            py = float(data[row * w + col])
            pz = z_off + row * cell
            points.append(f"({px:.2f}, {py:.2f}, {pz:.2f})")

    # Quads — each cell is one quad
    face_counts = []
    face_indices = []
    for row in range(h - 1):
        for col in range(w - 1):
            i0 = row * w + col
            i1 = i0 + 1
            i2 = i0 + w + 1
            i3 = i0 + w
            face_counts.append("4")
            face_indices.extend([str(i0), str(i1), str(i2), str(i3)])

    pts_str = ", ".join(points)
    fc_str = ", ".join(face_counts)
    fi_str = ", ".join(face_indices)

    return f'''def Mesh "Terrain"
{{
    int[] faceVertexCounts = [{fc_str}]
    int[] faceVertexIndices = [{fi_str}]
    point3f[] points = [{pts_str}]
    uniform token subdivisionScheme = "none"
    rel material:binding = </World/Materials/TerrainMat>
    custom string princeps:type = "terrain"
}}'''


# ---------------------------------------------------------------------------
# Substations
# ---------------------------------------------------------------------------

def _substation_prims(substations: list[dict], origin_lat: float, origin_lon: float) -> str:
    """Generate Cube prims for each substation."""
    if not substations:
        return 'def Xform "Substations" {}'

    children: list[str] = []
    for sub in substations:
        name = _sanitize_name(sub.get("name", "Substation"))
        lat = float(sub.get("lat", sub.get("latitude", origin_lat)))
        lon = float(sub.get("lon", sub.get("longitude", origin_lon)))
        voltage_kv = float(sub.get("voltage_kv", 33))
        demand_mw = float(sub.get("demand_mw", sub.get("capacity_mw", 10)))

        x, z = _latlon_to_local(lat, lon, origin_lat, origin_lon)
        # Scale: width proportional to voltage tier, height to demand
        w = max(5, voltage_kv / 10)
        h = max(3, demand_mw / 2)

        block = f'''def Cube "{name}"
{{
    {_xform_translate_scale(x, h / 2, z, w, h, w)}
    rel material:binding = </World/Materials/SubstationMat>
    custom string princeps:type = "substation"
    custom string princeps:voltage = "{voltage_kv} kV"
    custom double princeps:demand_mw = {demand_mw}
}}'''
        children.append(block)

    inner = "\n\n".join("    " + "\n    ".join(c.splitlines()) for c in children)
    return f'def Xform "Substations"\n{{\n{inner}\n}}'


# ---------------------------------------------------------------------------
# Power lines (BasisCurves)
# ---------------------------------------------------------------------------

def _power_line_prims(
    power_lines: list[dict] | None,
    substations: list[dict],
    origin_lat: float,
    origin_lon: float,
) -> str:
    """Generate BasisCurves prims for power lines.

    Each line dict should have:
        from_lat, from_lon, to_lat, to_lon  (or from_name/to_name matching substations)
        voltage_kv (optional)
    """
    if not power_lines:
        return 'def Xform "PowerLines" {}'

    # Build lookup by name for substations
    sub_lookup: dict[str, tuple[float, float]] = {}
    for s in substations:
        nm = s.get("name", "")
        lat = float(s.get("lat", s.get("latitude", origin_lat)))
        lon = float(s.get("lon", s.get("longitude", origin_lon)))
        sub_lookup[nm] = (lat, lon)

    children: list[str] = []
    for i, line in enumerate(power_lines):
        name = _sanitize_name(line.get("name", f"Line_{i}"))

        # Resolve endpoints
        if "from_lat" in line and "to_lat" in line:
            x0, z0 = _latlon_to_local(float(line["from_lat"]), float(line["from_lon"]), origin_lat, origin_lon)
            x1, z1 = _latlon_to_local(float(line["to_lat"]), float(line["to_lon"]), origin_lat, origin_lon)
        elif "from_name" in line and "to_name" in line:
            fl = sub_lookup.get(line["from_name"], (origin_lat, origin_lon))
            tl = sub_lookup.get(line["to_name"], (origin_lat, origin_lon))
            x0, z0 = _latlon_to_local(fl[0], fl[1], origin_lat, origin_lon)
            x1, z1 = _latlon_to_local(tl[0], tl[1], origin_lat, origin_lon)
        else:
            continue

        voltage_kv = float(line.get("voltage_kv", 33))
        height = max(8, voltage_kv / 10)  # cable sag height

        block = f'''def BasisCurves "{name}"
{{
    uniform token type = "linear"
    int[] curveVertexCounts = [3]
    point3f[] points = [({x0}, {height}, {z0}), ({(x0 + x1) / 2}, {height * 0.85}, {(z0 + z1) / 2}), ({x1}, {height}, {z1})]
    float[] widths = [0.3, 0.3, 0.3]
    uniform token wrap = "nonperiodic"
    rel material:binding = </World/Materials/PowerLineMat>
    custom string princeps:type = "power_line"
    custom double princeps:voltage_kv = {voltage_kv}
}}'''
        children.append(block)

    inner = "\n\n".join("    " + "\n    ".join(c.splitlines()) for c in children)
    return f'def Xform "PowerLines"\n{{\n{inner}\n}}'


# ---------------------------------------------------------------------------
# Placed assets
# ---------------------------------------------------------------------------

_ASSET_GEOMETRY: dict[str, dict[str, Any]] = {
    "solar": {
        "prim": "Cube",
        "scale": (12, 0.3, 6),    # flat panel array
        "color_key": "solar",
    },
    "solar_array": {
        "prim": "Cube",
        "scale": (12, 0.3, 6),
        "color_key": "solar",
    },
    "bess": {
        "prim": "Cube",
        "scale": (6, 4, 3),        # tall container
        "color_key": "bess",
    },
    "battery": {
        "prim": "Cube",
        "scale": (6, 4, 3),
        "color_key": "bess",
    },
    "transformer": {
        "prim": "Cylinder",
        "scale": (2, 3, 2),
        "color_key": "transformer",
    },
    "inverter": {
        "prim": "Cube",
        "scale": (2, 2, 1.5),
        "color_key": "transformer",
    },
    "dc_building": {
        "prim": "Cube",
        "scale": (20, 8, 15),       # large building
        "color_key": "dc_building",
    },
    "data_centre": {
        "prim": "Cube",
        "scale": (20, 8, 15),
        "color_key": "dc_building",
    },
}


def _asset_prims(assets: list[dict], origin_lat: float, origin_lon: float) -> str:
    """Generate geometry prims for placed assets."""
    if not assets:
        return 'def Xform "Assets" {}'

    children: list[str] = []
    counts: dict[str, int] = {}

    for asset in assets:
        atype = asset.get("type", asset.get("asset_type", "default")).lower().strip()
        geo = _ASSET_GEOMETRY.get(atype, {
            "prim": "Cube",
            "scale": (4, 3, 4),
            "color_key": "default",
        })

        # Deduplicate names
        base_name = _sanitize_name(asset.get("name", atype))
        counts[base_name] = counts.get(base_name, 0) + 1
        if counts[base_name] > 1:
            prim_name = f"{base_name}_{counts[base_name]}"
        else:
            prim_name = base_name

        lat = float(asset.get("lat", asset.get("latitude", origin_lat)))
        lon = float(asset.get("lon", asset.get("longitude", origin_lon)))
        x, z = _latlon_to_local(lat, lon, origin_lat, origin_lon)

        sx, sy, sz = geo["scale"]
        # If asset has capacity, scale proportionally
        cap = float(asset.get("capacity_kw", asset.get("capacity_mw", 0) * 1000) or 0)
        if cap > 0:
            factor = max(0.5, min(3.0, cap / 5000))
            sx *= factor
            sz *= factor

        mat_name = geo["color_key"].title().replace("_", "") + "Mat"
        prim_type = geo["prim"]

        block = f'''def {prim_type} "{prim_name}"
{{
    {_xform_translate_scale(x, sy / 2, z, sx, sy, sz)}
    rel material:binding = </World/Materials/{mat_name}>
    custom string princeps:type = "{atype}"
    custom string princeps:name = "{asset.get('name', atype)}"
    custom double princeps:capacity_kw = {cap}
}}'''
        children.append(block)

    inner = "\n\n".join("    " + "\n    ".join(c.splitlines()) for c in children)
    return f'def Xform "Assets"\n{{\n{inner}\n}}'


# ---------------------------------------------------------------------------
# Materials group
# ---------------------------------------------------------------------------

def _materials_block() -> str:
    """All Princeps materials in a single Scope."""
    mats = [
        _material_block("TerrainMat", COLORS["terrain"]),
        _material_block("SubstationMat", COLORS["substation"]),
        _material_block("SolarMat", COLORS["solar"]),
        _material_block("BessMat", COLORS["bess"]),
        _material_block("TransformerMat", COLORS["transformer"]),
        _material_block("DcbuildingMat", COLORS["dc_building"]),
        _material_block("PowerLineMat", COLORS["power_line"]),
        _material_block("DefaultMat", COLORS["default"]),
    ]
    inner = "\n\n".join("    " + "\n    ".join(m.splitlines()) for m in mats)
    return f'def Scope "Materials"\n{{\n{inner}\n}}'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_usd_scene(
    site: dict,
    substations: list[dict],
    assets: list[dict],
    heightmap: dict | None = None,
    power_lines: list[dict] | None = None,
) -> str:
    """Generate a complete USDA scene as a string.

    Parameters
    ----------
    site : dict
        Must contain at least ``lat``, ``lon``.
        Optional: ``name``, ``capacity_mw``, ``verdict``.
    substations : list[dict]
        Each with ``name``, ``lat``/``lon``, ``voltage_kv``, ``demand_mw``.
    assets : list[dict]
        Placed assets — ``type``, ``lat``/``lon``, ``capacity_kw``, ``name``.
    heightmap : dict, optional
        LiDAR / DEM heightmap grid.
    power_lines : list[dict], optional
        Connections between substations.

    Returns
    -------
    str
        Complete USDA file content.
    """
    origin_lat = float(site.get("lat", site.get("latitude", 51.5)))
    origin_lon = float(site.get("lon", site.get("longitude", -0.1)))
    site_name = site.get("name", "Princeps Site")
    capacity_mw = site.get("capacity_mw", 0)
    verdict = site.get("verdict", "")
    export_ts = datetime.now(timezone.utc).isoformat()

    terrain = _terrain_mesh(heightmap, origin_lat, origin_lon)
    subs = _substation_prims(substations, origin_lat, origin_lon)
    lines = _power_line_prims(power_lines, substations, origin_lat, origin_lon)
    asset_block = _asset_prims(assets, origin_lat, origin_lon)
    materials = _materials_block()

    # Indent all children under World
    children = [terrain, materials, subs, lines, asset_block]
    children_str = "\n\n".join("    " + "\n    ".join(c.splitlines()) for c in children)

    usda = f'''#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Y"
    doc = "Princeps OpenUSD scene export"
    customLayerData = {{
        string princeps:site_name = "{site_name}"
        double princeps:capacity_mw = {capacity_mw}
        string princeps:verdict = "{verdict}"
        string princeps:export_timestamp = "{export_ts}"
        double princeps:origin_lat = {origin_lat}
        double princeps:origin_lon = {origin_lon}
    }}
)

def Xform "World"
{{
{children_str}
}}
'''
    return usda


def export_usd_file(scene_text: str, filepath: str) -> str:
    """Write USDA text to a file. Returns the absolute path written."""
    import os
    filepath = os.path.abspath(filepath)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(scene_text)
    log.info("Wrote USDA scene to %s (%d bytes)", filepath, len(scene_text))
    return filepath


def generate_metadata(
    site: dict,
    substations: list[dict],
    assets: list[dict],
    power_lines: list[dict] | None = None,
) -> dict:
    """Generate companion JSON metadata for Omniverse integration."""
    origin_lat = float(site.get("lat", site.get("latitude", 51.5)))
    origin_lon = float(site.get("lon", site.get("longitude", -0.1)))

    return {
        "princeps_version": "2.0",
        "format": "USDA 1.0",
        "omniverse_compatible": True,
        "site": {
            "name": site.get("name", "Princeps Site"),
            "lat": origin_lat,
            "lon": origin_lon,
            "capacity_mw": site.get("capacity_mw", 0),
            "verdict": site.get("verdict", ""),
        },
        "coordinate_reference": {
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "srid": 4326,
            "projection": "equirectangular_local",
            "units": "metres",
            "up_axis": "Y",
        },
        "substations": [
            {
                "name": s.get("name", ""),
                "lat": float(s.get("lat", s.get("latitude", 0))),
                "lon": float(s.get("lon", s.get("longitude", 0))),
                "voltage_kv": s.get("voltage_kv"),
                "demand_mw": s.get("demand_mw", s.get("capacity_mw")),
            }
            for s in substations
        ],
        "assets": [
            {
                "type": a.get("type", a.get("asset_type", "unknown")),
                "name": a.get("name", ""),
                "lat": float(a.get("lat", a.get("latitude", 0))),
                "lon": float(a.get("lon", a.get("longitude", 0))),
                "capacity_kw": a.get("capacity_kw", (a.get("capacity_mw", 0) or 0) * 1000),
            }
            for a in assets
        ],
        "power_lines_count": len(power_lines) if power_lines else 0,
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
    }

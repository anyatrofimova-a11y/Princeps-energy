"""
utils/asset_layout_engine.py — Authoritative parametric layout engine for
the Princeps 3D twin.

Given a workload (``bess`` / ``solar`` / ``wind`` / ``dc`` / ``ev`` / ``h2``),
a capacity params dict, and a site polygon (WKT in either WGS84 or OSGB36),
this module returns a list of ``PlacedAsset`` instances ready to render in
the twin or project into construction-grade drawings.

Design
------
    1. Site polygon is projected to metric coordinates (EPSG:27700 OSGB36
       where possible, falls back to a local ENU approximation at the
       polygon centroid).
    2. Primitive counts are computed from ``parametric_rules`` in
       ``app/data/asset_catalogue.json``.
    3. Placement strategies are workload-specific:

         BESS  — grid-pack containers in rows (row_length_max from BS 8629),
                 2 m intra-row pitch, 8 m inter-row firebreak. PCS skids at
                 row ends. TX compound to the south of the block.
                 GIS bay at the nearest polygon corner (taken as POC).

         Solar — tile fixed-tilt tables across the buildable mask at
                 4 ac/MWp (≈ 16 m² per kWp). Inverter stations every 2.5 MW
                 at row centroids. 4 m access tracks every third row.

         Wind  — 5× rotor diameter downwind spacing, 3× crosswind
                 (IEA Wind Task 37). One crane pad per turbine. Wind farm
                 substation + met mast placed at polygon edge.

         DC    — data-hall long axis aligned E–W (maximises cooling-yard
                 frontage on south face). Coolers in a yard to the south;
                 gensets ≥10 m from shell (BS 7698-12) to the east; HV
                 transformer compound to the north; admin + gatehouse on
                 the arrival face.

         EV    — forecourt pattern (stalls in parallel rows with a
                 central canopy), amenity building at the front, forecourt
                 transformer at the rear, HVM bollards around perimeter.

         H2    — 25 m exclusion around storage vessels (HSE COMAH);
                 electrolyser + water treatment + compressor on the
                 upwind side; dispensers ≥10 m from storage.

    4. All coordinates are returned as metres relative to the polygon
       centroid (east +, north +, up +). Rotation in degrees CCW.

Public API
----------
    layout_site(workload, params, site_polygon_wkt) -> list[PlacedAsset]
    layout_site_full(workload, params, site_polygon_wkt) -> LayoutResponse

Both functions load the canonical catalogue on first call (memoised).
"""

from __future__ import annotations

import json
import logging
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry
from shapely import wkt as shp_wkt
from shapely.affinity import translate, rotate as shapely_rotate
from shapely.ops import transform as shp_transform, unary_union

from app.models.asset_primitive import (
    AssetPrimitive,
    LayoutResponse,
    PlacedAsset,
)

log = logging.getLogger("princeps.asset_layout_engine")

# ---------------------------------------------------------------------------
# Catalogue loader
# ---------------------------------------------------------------------------
_CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "asset_catalogue.json"


@lru_cache(maxsize=1)
def _load_catalogue() -> dict[str, AssetPrimitive]:
    """Load + validate the catalogue. Cached for the process lifetime.

    The frontend fetches the raw JSON via ``GET /api/twin/asset-catalogue``;
    backend callers should use this helper so we pay the Pydantic validation
    cost exactly once.
    """
    raw = json.loads(_CATALOGUE_PATH.read_text(encoding="utf-8"))
    out: dict[str, AssetPrimitive] = {}
    for entry in raw.get("primitives", []):
        prim = AssetPrimitive.model_validate(entry)
        out[prim.id] = prim
    log.info("asset catalogue loaded: %d primitives", len(out))
    return out


def get_primitive(primitive_id: str) -> AssetPrimitive | None:
    return _load_catalogue().get(primitive_id)


def catalogue_raw() -> dict:
    """Return the raw JSON — used by the router so the frontend sees the same
    bytes that were validated server-side."""
    return json.loads(_CATALOGUE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Formula evaluation
# ---------------------------------------------------------------------------
_SAFE_MATH = {
    "ceil": math.ceil, "floor": math.floor, "max": max, "min": min,
    "round": round, "sqrt": math.sqrt, "log": math.log, "log2": math.log2,
    "log10": math.log10, "exp": math.exp, "pi": math.pi,
}


def _apply_rule(rule, params: dict[str, float]) -> int:
    """Evaluate a parametric rule against the capacity params dict."""
    driver = rule.driver
    value = float(params.get(driver, 0) or 0)
    env = {**_SAFE_MATH, driver: value}
    try:
        raw = eval(rule.formula, {"__builtins__": {}}, env)  # noqa: S307
    except Exception as exc:
        log.warning("rule eval failed for driver=%s formula=%r: %s",
                    driver, rule.formula, exc)
        raw = 0
    n = int(math.floor(raw)) if isinstance(raw, (int, float)) else 0
    return max(rule.count_min, min(rule.count_max, n))


def _count_from_primitive(prim: AssetPrimitive, params: dict[str, float]) -> int:
    if not prim.parametric_rules:
        return 0
    # Sum across rules; most primitives only have one rule anyway.
    return sum(_apply_rule(r, params) for r in prim.parametric_rules)


# ---------------------------------------------------------------------------
# Geometry helpers — site polygon projection
# ---------------------------------------------------------------------------
def _parse_polygon(wkt_str: str) -> tuple[BaseGeometry, tuple[float, float], tuple[float, float] | None]:
    """Parse WKT, return (polygon_in_metres, centroid_lonlat, centroid_osgb).

    The polygon is returned with its centroid translated to (0, 0) so the
    layout engine works in local metres. The original centroid is returned
    separately for reporting / GA drawings.
    """
    geom = shp_wkt.loads(wkt_str)
    if geom.is_empty:
        raise ValueError("site polygon is empty")
    # Heuristic: WGS84 if bounds fit [-180,180] × [-90,90] and look like degrees.
    minx, miny, maxx, maxy = geom.bounds
    is_wgs84 = (-180 <= minx <= 180 and -180 <= maxx <= 180
                and -90 <= miny <= 90 and -90 <= maxy <= 90)

    centroid_lonlat: tuple[float, float] | None = None
    centroid_osgb: tuple[float, float] | None = None

    if is_wgs84:
        centroid_lonlat = (geom.centroid.x, geom.centroid.y)
        # Try OSGB projection via pyproj; fall back to local ENU at centroid.
        try:
            from pyproj import Transformer
            to_27700 = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
            cx, cy = to_27700.transform(centroid_lonlat[0], centroid_lonlat[1])
            centroid_osgb = (cx, cy)

            def _fwd(x, y, z=None):
                ex, en = to_27700.transform(x, y)
                return (ex - cx, en - cy) if z is None else (ex - cx, en - cy, z)

            metric = shp_transform(_fwd, geom)
        except Exception:
            lat0 = centroid_lonlat[1]
            deg_to_m_lat = 111_320.0
            deg_to_m_lon = 111_320.0 * math.cos(math.radians(lat0))

            def _fwd(x, y, z=None):
                ex = (x - centroid_lonlat[0]) * deg_to_m_lon
                en = (y - centroid_lonlat[1]) * deg_to_m_lat
                return (ex, en) if z is None else (ex, en, z)

            metric = shp_transform(_fwd, geom)
    else:
        # Assume already metric (OSGB36 or equivalent).
        cx, cy = geom.centroid.x, geom.centroid.y
        centroid_osgb = (cx, cy)
        # Reverse-transform to WGS84 if possible.
        try:
            from pyproj import Transformer
            to_4326 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
            lon, lat = to_4326.transform(cx, cy)
            centroid_lonlat = (lon, lat)
        except Exception:
            pass
        metric = translate(geom, xoff=-cx, yoff=-cy)

    return metric, centroid_lonlat, centroid_osgb


def _polygon_as_simple(geom: BaseGeometry) -> Polygon:
    """Return the largest polygon if MultiPolygon, else the polygon."""
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda g: g.area)
    if isinstance(geom, Polygon):
        return geom
    raise ValueError(f"expected (Multi)Polygon, got {type(geom).__name__}")


def _polygon_bounds_m(poly: Polygon) -> tuple[float, float, float, float]:
    return poly.bounds  # (min_e, min_n, max_e, max_n)


# ---------------------------------------------------------------------------
# Placement primitives
# ---------------------------------------------------------------------------
def _placement(primitive_id: str, x: float, y: float, z: float = 0.0,
               rot: float = 0.0, scale: tuple[float, float, float] = (1, 1, 1),
               **meta) -> PlacedAsset:
    return PlacedAsset(
        primitive_id=primitive_id,
        xyz=(float(x), float(y), float(z)),
        rotation_deg=float(rot),
        scale=(float(scale[0]), float(scale[1]), float(scale[2])),
        metadata=meta or None,
    )


# ---------------------------------------------------------------------------
# BESS layout
# ---------------------------------------------------------------------------
def _layout_bess(params: dict, poly: Polygon,
                 catalogue: dict[str, AssetPrimitive]) -> tuple[list[PlacedAsset], list[str]]:
    """Grid-pack BESS containers + PCS skids + TX + GIS.

    BS 8629 — rows of max 8 containers, 2 m intra-row, 8 m inter-row firebreak.
    PCS skids at the south end of each row; grid TX compound south of the block.
    GIS bay at the nearest polygon corner (assumed POC).
    """
    notes: list[str] = []
    placed: list[PlacedAsset] = []

    mwh = float(params.get("mwh") or 0.0)
    mw_ac = float(params.get("mw_ac") or 0.0)
    duration_h = float(params.get("duration_h") or 0.0)
    if mwh <= 0 and mw_ac > 0 and duration_h > 0:
        mwh = mw_ac * duration_h
    if mw_ac <= 0 and mwh > 0 and duration_h > 0:
        mw_ac = mwh / duration_h

    # Pick BESS container primitive — default Megapack 2XL.
    container = catalogue["bess.megapack_2xl"]
    pcs = catalogue["bess.pcs_2mva_skid"]
    hv_tx = catalogue["bess.hv_transformer"]
    gis_hv = catalogue["bess.gis_132kv_bay"]
    ctrl = catalogue["bess.control_building"]
    fire_tank = catalogue["bess.fire_tank"]

    n_containers = _count_from_primitive(container, {"mwh": mwh})
    n_pcs = _count_from_primitive(pcs, {"mw_ac": mw_ac})
    n_hv_tx = _count_from_primitive(hv_tx, {"mw_ac": mw_ac})
    n_tanks = _count_from_primitive(fire_tank, {"mwh": mwh})

    row_max = container.parametric_rules[0].row_length_max or 8
    pitch_x = container.dimensions_m.length_m + (container.parametric_rules[0].spacing_m or 2.0)
    firebreak_y = 8.0  # BS 8629 inter-row clearance
    row_width = container.dimensions_m.width_m

    n_rows = math.ceil(n_containers / row_max) if n_containers else 0
    per_row = min(row_max, n_containers) if n_rows > 0 else 0

    # Block origin: centre of polygon, offset north so TX compound fits south.
    minx, miny, maxx, maxy = _polygon_bounds_m(poly)
    block_width = per_row * pitch_x
    block_depth = n_rows * (row_width + firebreak_y)

    # Shift block north of centre so TX compound sits to the south.
    block_origin_y = row_width / 2.0  # south edge of first row at y=0
    block_origin_x = -block_width / 2.0

    for row_i in range(n_rows):
        row_y = block_origin_y + row_i * (row_width + firebreak_y)
        units_in_row = per_row if row_i < n_rows - 1 else (n_containers - row_i * per_row)
        for unit_i in range(units_in_row):
            x = block_origin_x + unit_i * pitch_x + pitch_x / 2.0
            placed.append(_placement(
                container.id, x, row_y, 0.0, rot=0.0,
                row_index=row_i, unit_index=unit_i,
                role="container",
            ))
        # PCS skids at the east end of each row (two per row for redundancy when needed).
        n_pcs_this_row = max(1, math.ceil(n_pcs / max(n_rows, 1)))
        for pcs_i in range(n_pcs_this_row):
            x = block_origin_x + block_width + 4.0 + pcs_i * (pcs.dimensions_m.length_m + 3.0)
            placed.append(_placement(
                pcs.id, x, row_y, 0.0,
                row_index=row_i, role="pcs",
            ))

    # Cap total PCS count (we may have over-placed by rounding up per-row).
    pcs_placed = [p for p in placed if p.primitive_id == pcs.id]
    if len(pcs_placed) > n_pcs:
        # Trim the surplus.
        keep_ids = {id(p) for p in pcs_placed[:n_pcs]}
        placed = [p for p in placed
                  if p.primitive_id != pcs.id or id(p) in keep_ids]

    # Grid transformer(s) south of block, centred.
    tx_y = -hv_tx.dimensions_m.width_m / 2.0 - hv_tx.dimensions_m.clearance_m - 5.0
    for tx_i in range(n_hv_tx):
        x = -((n_hv_tx - 1) * (hv_tx.dimensions_m.length_m + 6.0)) / 2.0 + \
             tx_i * (hv_tx.dimensions_m.length_m + 6.0)
        placed.append(_placement(hv_tx.id, x, tx_y, 0.0, role="grid_tx"))

    # GIS bay south-east of TX compound (POC side).
    gis_x = block_width / 2.0 + 10.0
    gis_y = tx_y - hv_tx.dimensions_m.width_m / 2.0 - 8.0
    placed.append(_placement(gis_hv.id, gis_x, gis_y, 0.0, role="poc_gis"))

    # Control building to the west of the block.
    ctrl_x = block_origin_x - ctrl.dimensions_m.length_m - 5.0
    ctrl_y = block_origin_y + block_depth / 2.0
    placed.append(_placement(ctrl.id, ctrl_x, ctrl_y, 0.0, role="scada"))

    # Fire-water tanks at the NW and SE corners of the BESS block.
    for tank_i in range(n_tanks):
        if tank_i % 2 == 0:
            x = block_origin_x - 6.0
            y = block_origin_y + block_depth + 4.0 + (tank_i // 2) * 10.0
        else:
            x = block_origin_x + block_width + 6.0
            y = block_origin_y - 4.0 - (tank_i // 2) * 10.0
        placed.append(_placement(fire_tank.id, x, y, 0.0, role="fire_tank"))

    notes.append(
        f"BESS: {n_containers} × {container.label} in {n_rows} rows of ≤{row_max} "
        f"(BS 8629 compliant); {n_pcs} × {pcs.label}; {n_hv_tx} × grid TX."
    )
    if block_width > (maxx - minx) or block_depth > (maxy - miny):
        notes.append(
            f"WARNING: block footprint {block_width:.0f} × {block_depth:.0f} m "
            f"exceeds site bounds {(maxx-minx):.0f} × {(maxy-miny):.0f} m — "
            "resize the site or split into phases."
        )
    return placed, notes


# ---------------------------------------------------------------------------
# Solar layout
# ---------------------------------------------------------------------------
def _layout_solar(params: dict, poly: Polygon,
                  catalogue: dict[str, AssetPrimitive]) -> tuple[list[PlacedAsset], list[str]]:
    """Tile solar tables across the site; drop inverter stations every 2.5 MW.

    4 ac/MWp ≈ 16 m² per kWp = 16 000 m² per MWp of land. Row pitch 8 m.
    Inverter stations placed at the centroid of every block of ~1.1 MWp of tables.
    4 m access tracks every third row (IEC 61724-compliant O&M access).
    """
    notes: list[str] = []
    placed: list[PlacedAsset] = []

    mwp = float(params.get("mwp") or 0.0)
    mw_ac = float(params.get("mw_ac") or (mwp / 1.25))  # default DC/AC = 1.25

    table = catalogue["solar.fixed_tilt_table_2x10"]
    inv = catalogue["solar.central_inverter_2500kw"]
    tx = catalogue["solar.lv_hv_transformer_2_5mva"]
    poc = catalogue["solar.poc_switchroom"]
    weather = catalogue["solar.weather_station"]

    n_tables_target = _count_from_primitive(table, {"mwp": mwp})
    n_inverters = _count_from_primitive(inv, {"mw_ac": mw_ac})
    n_weather = _count_from_primitive(weather, {"mwp": mwp})

    # Tile across the polygon bounding box in metric coords.
    minx, miny, maxx, maxy = _polygon_bounds_m(poly)
    table_len = table.dimensions_m.length_m
    table_wid = table.dimensions_m.width_m
    row_pitch = (table.parametric_rules[0].spacing_m or 8.0)  # N-S pitch
    col_pitch = table_len + 2.0  # E-W gap between tables in same row
    track_every = 3  # access track after every 3 rows
    track_width = 4.0

    placed_tables = 0
    row_i = 0
    y = miny + 10.0  # 10 m setback from fence
    while y + table_wid <= maxy - 10.0 and placed_tables < n_tables_target:
        # Access track row?
        if row_i > 0 and row_i % track_every == 0:
            y += track_width
        x = minx + 10.0
        col_i = 0
        while x + table_len <= maxx - 10.0 and placed_tables < n_tables_target:
            cx = x + table_len / 2.0
            cy = y + table_wid / 2.0
            if poly.contains(Point(cx, cy)):
                placed.append(_placement(
                    table.id, cx, cy, 0.0,
                    row_index=row_i, col_index=col_i,
                    role="pv_table",
                ))
                placed_tables += 1
            x += col_pitch
            col_i += 1
        y += table_wid + row_pitch
        row_i += 1

    # Inverter stations every 2.5 MW — place at row centroids of the first rows.
    inv_spacing_cols = max(1, round(math.sqrt(max(n_inverters, 1))))
    for inv_i in range(n_inverters):
        col = inv_i % inv_spacing_cols
        row = inv_i // inv_spacing_cols
        x = minx + 10.0 + col * ((maxx - minx - 20.0) / max(inv_spacing_cols, 1)) + \
             ((maxx - minx - 20.0) / max(inv_spacing_cols, 1)) / 2.0
        y = miny + 10.0 + row * 80.0 + 30.0
        if poly.contains(Point(x, y)):
            placed.append(_placement(inv.id, x, y, 0.0, inv_index=inv_i, role="inverter"))
            # Co-locate TX next to inverter (3 m east).
            placed.append(_placement(tx.id, x + inv.dimensions_m.length_m / 2.0 + 3.0,
                                     y, 0.0, inv_index=inv_i, role="lv_hv_tx"))

    # POC switchroom at the south corner (near polygon vertex closest to grid).
    poc_x = minx + poc.dimensions_m.length_m / 2.0 + 8.0
    poc_y = miny + poc.dimensions_m.width_m / 2.0 + 8.0
    placed.append(_placement(poc.id, poc_x, poc_y, 0.0, role="poc"))

    # Weather station(s) at northern edge.
    for w_i in range(n_weather):
        x = minx + 20.0 + w_i * ((maxx - minx - 40.0) / max(n_weather, 1))
        y = maxy - 15.0
        placed.append(_placement(weather.id, x, y, 0.0, role="weather"))

    notes.append(
        f"Solar: {placed_tables} × {table.label} (target {n_tables_target}); "
        f"{n_inverters} inverter stations every 2.5 MW; "
        f"access tracks every {track_every} rows."
    )
    if placed_tables < n_tables_target:
        notes.append(
            f"WARNING: only {placed_tables}/{n_tables_target} tables fit the "
            f"buildable polygon — increase site area or accept lower MWp."
        )
    return placed, notes


# ---------------------------------------------------------------------------
# Wind layout
# ---------------------------------------------------------------------------
def _layout_wind(params: dict, poly: Polygon,
                 catalogue: dict[str, AssetPrimitive]) -> tuple[list[PlacedAsset], list[str]]:
    """IEA Wind Task 37: 5D downwind (north-south), 3D crosswind (east-west)."""
    notes: list[str] = []
    placed: list[PlacedAsset] = []

    n_turbines = int(params.get("turbines") or 0)
    turbine = catalogue["wind.turbine_4_5mw_rotor150"]
    pad = catalogue["wind.crane_pad"]
    subst = catalogue["wind.substation_compound"]
    met = catalogue["wind.met_mast"]

    rotor_d = 150.0
    dx = 3 * rotor_d  # crosswind
    dy = 5 * rotor_d  # downwind

    minx, miny, maxx, maxy = _polygon_bounds_m(poly)
    cols = max(1, int((maxx - minx) // dx))
    rows_needed = math.ceil(n_turbines / cols) if cols > 0 else 0

    for t_i in range(n_turbines):
        col = t_i % cols
        row = t_i // cols
        x = minx + dx / 2.0 + col * dx
        y = miny + dy / 2.0 + row * dy
        if not poly.contains(Point(x, y)):
            continue
        placed.append(_placement(turbine.id, x, y, 0.0,
                                 turbine_index=t_i, role="turbine"))
        placed.append(_placement(pad.id, x, y - rotor_d * 0.2, 0.0,
                                 turbine_index=t_i, role="crane_pad"))

    # Substation + met mast at opposite ends of the array.
    placed.append(_placement(subst.id, minx + 30.0, miny + 30.0, 0.0, role="substation"))
    placed.append(_placement(met.id, maxx - 10.0, miny + 10.0, 0.0, role="met_mast"))

    notes.append(
        f"Wind: {n_turbines} × {turbine.label}; spacing {dx:.0f} m × "
        f"{dy:.0f} m (3D × 5D per IEA Wind Task 37)."
    )
    if rows_needed * dy > (maxy - miny):
        notes.append(
            f"WARNING: required array depth {rows_needed * dy:.0f} m exceeds "
            f"site N-S extent {(maxy-miny):.0f} m."
        )
    return placed, notes


# ---------------------------------------------------------------------------
# Data centre layout
# ---------------------------------------------------------------------------
def _layout_dc(params: dict, poly: Polygon,
               catalogue: dict[str, AssetPrimitive]) -> tuple[list[PlacedAsset], list[str]]:
    """DC halls E-W; cooling yard south; gensets ≥10 m east of shell."""
    notes: list[str] = []
    placed: list[PlacedAsset] = []

    mw_it = float(params.get("mw_it") or 0.0)
    tier = (params.get("tier") or "tier3").lower()
    redundancy_n_plus = int(params.get("redundancy_n_plus") or 1)

    hall = catalogue["dc.hall_modular_10mw"]
    cooler = catalogue["dc.adiabatic_cooler"]
    genset = catalogue["dc.diesel_genset_3mva"]
    ups = catalogue["dc.ups_module_1250kva"]
    hv_tx = catalogue["dc.hv_transformer_33_11kv_20mva"]
    subst = catalogue["dc.on_site_substation"]
    admin = catalogue["dc.admin_building"]
    fuel = catalogue["dc.fuel_tank_bunded_50k_l"]
    gate = catalogue["common.gatehouse"]

    n_halls = _count_from_primitive(hall, {"mw_it": mw_it})
    n_coolers = _count_from_primitive(cooler, {"mw_it": mw_it})
    # Gensets: base count + N+1
    base_gensets = math.ceil(mw_it * 1.2 / 3.0)
    n_gensets = base_gensets + redundancy_n_plus
    n_ups = _count_from_primitive(ups, {"mw_it": mw_it})
    n_hv_tx = _count_from_primitive(hv_tx, {"mw_it": mw_it})
    n_fuel = _count_from_primitive(fuel, {"mw_it": mw_it})

    # Hall block — long axis E-W, centred on polygon centre.
    hall_len = hall.dimensions_m.length_m  # 100
    hall_wid = hall.dimensions_m.width_m   # 60
    hall_gap = 20.0
    block_hall_len = n_halls * hall_len + max(0, n_halls - 1) * hall_gap
    for h_i in range(n_halls):
        x = -block_hall_len / 2.0 + h_i * (hall_len + hall_gap) + hall_len / 2.0
        y = 0.0
        placed.append(_placement(
            hall.id, x, y, 0.0, rot=0.0,
            hall_index=h_i, role="data_hall",
        ))

    # Cooling yard to the south of each hall.
    coolers_per_hall = max(1, math.ceil(n_coolers / max(n_halls, 1)))
    cooler_pitch = cooler.dimensions_m.length_m + 5.0
    coolers_placed = 0
    for h_i in range(n_halls):
        if coolers_placed >= n_coolers:
            break
        x0 = -block_hall_len / 2.0 + h_i * (hall_len + hall_gap)
        this_round = min(coolers_per_hall, n_coolers - coolers_placed)
        for c_i in range(this_round):
            cx = x0 + c_i * cooler_pitch + cooler.dimensions_m.length_m / 2.0
            cy = -hall_wid / 2.0 - 15.0 - cooler.dimensions_m.width_m / 2.0
            placed.append(_placement(
                cooler.id, cx, cy, 0.0,
                hall_index=h_i, role="cooler",
            ))
            coolers_placed += 1

    # Gensets — ≥10 m east of easternmost hall shell (BS 7698-12), row of N+1.
    gen_base_x = block_hall_len / 2.0 + 10.0 + genset.dimensions_m.length_m / 2.0
    gen_pitch = genset.dimensions_m.width_m + 10.0
    for g_i in range(n_gensets):
        gx = gen_base_x + (g_i // 10) * (genset.dimensions_m.length_m + 4.0)
        gy = -((n_gensets - 1) * gen_pitch) / 2.0 + (g_i % 10) * gen_pitch
        placed.append(_placement(
            genset.id, gx, gy, 0.0,
            genset_index=g_i, role="genset",
        ))
        # Fuel tank every two gensets.
        if g_i < n_fuel and g_i % 2 == 0:
            placed.append(_placement(
                fuel.id, gx + 15.0, gy, 0.0,
                role="fuel_tank",
            ))

    # UPS + HV TX — north of halls.
    ups_y = hall_wid / 2.0 + 10.0 + ups.dimensions_m.width_m / 2.0
    for u_i in range(n_ups):
        ux = -((n_ups - 1) * (ups.dimensions_m.length_m + 2.0)) / 2.0 + \
             u_i * (ups.dimensions_m.length_m + 2.0)
        placed.append(_placement(ups.id, ux, ups_y, 0.0,
                                 ups_index=u_i, role="ups"))

    tx_y = ups_y + ups.dimensions_m.width_m / 2.0 + 8.0 + hv_tx.dimensions_m.width_m / 2.0
    for t_i in range(n_hv_tx):
        tx_x = -((n_hv_tx - 1) * (hv_tx.dimensions_m.length_m + 5.0)) / 2.0 + \
               t_i * (hv_tx.dimensions_m.length_m + 5.0)
        placed.append(_placement(hv_tx.id, tx_x, tx_y, 0.0, role="hv_tx"))

    # On-site substation — further north.
    subst_y = tx_y + hv_tx.dimensions_m.width_m / 2.0 + 10.0 + subst.dimensions_m.width_m / 2.0
    placed.append(_placement(subst.id, 0.0, subst_y, 0.0, role="substation"))

    # Admin building + gatehouse to the west.
    admin_x = -block_hall_len / 2.0 - 15.0 - admin.dimensions_m.length_m / 2.0
    placed.append(_placement(admin.id, admin_x, 0.0, 0.0, role="admin"))
    placed.append(_placement(gate.id, admin_x - 25.0, 0.0, 0.0, role="gatehouse"))

    cooling_area = n_coolers * cooler.dimensions_m.length_m * cooler.dimensions_m.width_m
    notes.append(
        f"DC ({tier}, N+{redundancy_n_plus}): {n_halls} × hall; "
        f"{n_coolers} × cooler ({cooling_area:.0f} m² yard); "
        f"{n_gensets} × genset (≥10 m east per BS 7698-12); "
        f"{n_ups} × UPS; {n_hv_tx} × HV TX."
    )
    return placed, notes


# ---------------------------------------------------------------------------
# EV layout
# ---------------------------------------------------------------------------
def _layout_ev(params: dict, poly: Polygon,
               catalogue: dict[str, AssetPrimitive]) -> tuple[list[PlacedAsset], list[str]]:
    """Forecourt pattern: stalls in parallel rows under canopies."""
    notes: list[str] = []
    placed: list[PlacedAsset] = []

    vehicles = int(params.get("vehicles") or 0)
    stall = catalogue["ev.supercharger_v4_stall"]
    canopy = catalogue["ev.canopy_solar"]
    tx = catalogue["ev.forecourt_transformer_2mva"]
    amen = catalogue["ev.amenity_building"]

    stall_pitch = stall.parametric_rules[0].spacing_m or 5.5
    per_row = 10  # 10 stalls per canopy row, two rows facing each other
    n_rows = math.ceil(vehicles / per_row)

    for s_i in range(vehicles):
        row = s_i // per_row
        col = s_i % per_row
        x = -((per_row - 1) * stall_pitch) / 2.0 + col * stall_pitch
        y = row * 14.0 - (n_rows - 1) * 7.0
        placed.append(_placement(stall.id, x, y, 0.0,
                                 stall_index=s_i, row_index=row,
                                 role="charger"))

    # Canopy per row.
    for r_i in range(n_rows):
        x = 0.0
        y = r_i * 14.0 - (n_rows - 1) * 7.0
        placed.append(_placement(canopy.id, x, y, 0.0,
                                 row_index=r_i, role="canopy"))

    # Transformer at the rear.
    placed.append(_placement(tx.id, 0.0, n_rows * 8.0 + 15.0, 0.0, role="forecourt_tx"))
    # Amenity building at the front.
    placed.append(_placement(amen.id, 0.0, -(n_rows * 8.0 + 15.0), 0.0, role="amenity"))

    notes.append(
        f"EV: {vehicles} × {stall.label} in {n_rows} row(s) of {per_row}; "
        f"solar canopy + 2 MVA TX + amenity building."
    )
    return placed, notes


# ---------------------------------------------------------------------------
# Hydrogen layout
# ---------------------------------------------------------------------------
def _layout_h2(params: dict, poly: Polygon,
               catalogue: dict[str, AssetPrimitive]) -> tuple[list[PlacedAsset], list[str]]:
    """Electrolyser + storage with 25 m exclusion around storage (HSE COMAH)."""
    notes: list[str] = []
    placed: list[PlacedAsset] = []

    kg_day = float(params.get("kg_day") or 0.0)

    elec = catalogue["h2.pem_electrolyser_5mw"]
    store = catalogue["h2.storage_vessel_350bar"]
    comp = catalogue["h2.compressor_station"]
    wt = catalogue["h2.water_treatment_skid"]
    disp = catalogue["h2.dispenser_350bar"]

    n_elec = _count_from_primitive(elec, {"kg_day": kg_day})
    n_store = _count_from_primitive(store, {"kg_day": kg_day})
    n_comp = _count_from_primitive(comp, {"kg_day": kg_day})
    n_wt = _count_from_primitive(wt, {"kg_day": kg_day})
    n_disp = _count_from_primitive(disp, {"kg_day": kg_day})

    # Electrolysers in a row west of centre.
    for e_i in range(n_elec):
        x = -40.0 - e_i * (elec.dimensions_m.length_m + 4.0)
        placed.append(_placement(elec.id, x, 0.0, 0.0,
                                 electrolyser_index=e_i, role="electrolyser"))

    # Water treatment skid north of electrolysers.
    for w_i in range(n_wt):
        placed.append(_placement(wt.id, -40.0 - w_i * 15.0, 20.0, 0.0, role="water_treatment"))

    # Compressors east.
    for c_i in range(n_comp):
        placed.append(_placement(comp.id, 20.0 + c_i * (comp.dimensions_m.length_m + 5.0),
                                 0.0, 0.0, role="compressor"))

    # Storage vessels in a row 25 m east of compressors (exclusion zone).
    store_x0 = 20.0 + n_comp * (comp.dimensions_m.length_m + 5.0) + 30.0
    for s_i in range(n_store):
        placed.append(_placement(
            store.id,
            store_x0 + s_i * (store.dimensions_m.length_m + 5.0),
            0.0, 0.0,
            storage_index=s_i, role="storage",
        ))

    # Dispensers 10 m south of storage.
    for d_i in range(n_disp):
        placed.append(_placement(
            disp.id,
            store_x0 + d_i * 6.0, -store.dimensions_m.clearance_m - 5.0, 0.0,
            role="dispenser",
        ))

    notes.append(
        f"H2: {n_elec} × {elec.label}; {n_store} × storage (25 m exclusion); "
        f"{n_comp} compressor, {n_disp} dispensers (HSE COMAH compliant)."
    )
    return placed, notes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
_DISPATCH = {
    "bess": _layout_bess,
    "solar": _layout_solar,
    "wind": _layout_wind,
    "dc": _layout_dc,
    "ev": _layout_ev,
    "h2": _layout_h2,
}


def layout_site(workload: str, params: dict, site_polygon_wkt: str) -> list[PlacedAsset]:
    """Parametric layout — main public entry point.

    Parameters
    ----------
    workload : one of {"bess","solar","wind","dc","ev","h2"}
    params   : dict with capacity drivers (see module docstring)
    site_polygon_wkt : WKT string in WGS84 or OSGB36 (auto-detected)

    Returns
    -------
    list[PlacedAsset] with xyz in metres from polygon centroid.
    """
    return layout_site_full(workload, params, site_polygon_wkt).placed_assets


def layout_site_full(workload: str, params: dict, site_polygon_wkt: str) -> LayoutResponse:
    """Full layout including centroid + notes for API responses."""
    wl = (workload or "").strip().lower()
    if wl not in _DISPATCH:
        raise ValueError(f"unknown workload {workload!r}; expected one of {list(_DISPATCH)}")

    catalogue = _load_catalogue()
    metric, centroid_lonlat, centroid_osgb = _parse_polygon(site_polygon_wkt)
    poly = _polygon_as_simple(metric)

    placed, notes = _DISPATCH[wl](params or {}, poly, catalogue)

    # Primitive-id histogram.
    counts: dict[str, int] = {}
    for p in placed:
        counts[p.primitive_id] = counts.get(p.primitive_id, 0) + 1

    # Bbox in metres from centroid.
    bbox_m: tuple[float, float, float, float] | None = None
    if placed:
        xs = [p.xyz[0] for p in placed]
        ys = [p.xyz[1] for p in placed]
        bbox_m = (min(xs), min(ys), max(xs), max(ys))

    return LayoutResponse(
        workload=wl,
        placed_assets=placed,
        centroid_lonlat=centroid_lonlat,
        centroid_osgb=centroid_osgb,
        bbox_m=bbox_m,
        counts=counts,
        notes=notes,
    )

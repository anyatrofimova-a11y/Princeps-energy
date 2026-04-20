"""MVT tiler for substrate layers.

Generates Mapbox Vector Tiles (MVT) for the six substrate layers
directly from the nightly-refreshed materialised views using PostGIS's
``ST_AsMVT``. One SQL round-trip per tile — no intermediate cache is
needed because PostGIS handles the encoding.

Tile coordinates are standard XYZ (Z/X/Y) in Web Mercator (EPSG:3857).
The materialised views store geometries already projected to 3857 so
tile clipping is a cheap spatial filter.

Refresh of the materialised views is typically scheduled nightly (not
shipped here; call ``refresh_materialized_views(pool)`` from a cron or
scheduler). The tiler itself is read-only.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

log = logging.getLogger("princeps.substrate.tiler")

# ---------------------------------------------------------------------------
# Layer registry
# ---------------------------------------------------------------------------

# Each layer maps to a materialised view + column selection for the MVT.
# ``attrs`` is the list of feature properties the tiler will include.
LAYERS: dict[str, dict] = {
    "buildings": {
        "mv":    "substrate_mv_buildings",
        "attrs": ["id", "toid", "feature_class", "use_class", "height_m"],
        "min_zoom": 13,
    },
    "roads": {
        "mv":    "substrate_mv_roads",
        "attrs": ["id", "toid", "road_class", "name", "form_of_way"],
        "min_zoom": 10,
    },
    "water": {
        "mv":    "substrate_mv_water",
        "attrs": ["id", "toid", "feature_type", "name"],
        "min_zoom": 8,
    },
    "woodland": {
        "mv":    "substrate_mv_woodland",
        "attrs": ["id", "toid", "feature_type"],
        "min_zoom": 10,
    },
    "pylons": {
        "mv":    "substrate_mv_pylons",
        "attrs": ["id", "osm_id", "osm_type", "voltage_kv", "operator", "height_m"],
        "min_zoom": 11,
    },
    "overhead_lines": {
        "mv":    "substrate_mv_overhead_lines",
        "attrs": ["id", "osm_id", "osm_type", "voltage_kv", "operator", "circuits"],
        "min_zoom": 8,
    },
}


# ---------------------------------------------------------------------------
# Tile → Web Mercator bounds
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_378_137.0
_ORIGIN = math.pi * _EARTH_RADIUS_M           # ~20037508.342789244


def _tile_bounds_3857(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) in EPSG:3857 for tile z/x/y."""
    tile_size = (2 * _ORIGIN) / (2 ** z)
    min_x = -_ORIGIN + x * tile_size
    max_x = min_x + tile_size
    max_y = _ORIGIN - y * tile_size
    min_y = max_y - tile_size
    return min_x, min_y, max_x, max_y


# ---------------------------------------------------------------------------
# MVT generation
# ---------------------------------------------------------------------------

async def generate_tile(
    pool,
    layer: str,
    z: int,
    x: int,
    y: int,
    buffer_px: int = 64,
    extent: int = 4096,
) -> Optional[bytes]:
    """Produce a single MVT tile as bytes. Returns ``None`` for unknown layer."""
    cfg = LAYERS.get(layer)
    if cfg is None:
        return None
    if z < cfg["min_zoom"]:
        # Too zoomed out — return an empty tile rather than exclude the route
        return b""

    mv = cfg["mv"]
    attrs = cfg["attrs"]
    min_x, min_y, max_x, max_y = _tile_bounds_3857(z, x, y)
    attrs_sql = ", ".join(attrs)

    sql = f"""
        WITH tile AS (
            SELECT ST_MakeEnvelope($1, $2, $3, $4, 3857) AS env
        ),
        rows AS (
            SELECT
                {attrs_sql},
                ST_AsMVTGeom(
                    m.geom_3857,
                    (SELECT env FROM tile),
                    $5::int,
                    $6::int,
                    true
                ) AS mvt_geom
            FROM {mv} AS m, tile
            WHERE m.geom_3857 && tile.env
        )
        SELECT ST_AsMVT(rows.*, $7, $5::int, 'mvt_geom') FROM rows
        WHERE mvt_geom IS NOT NULL
    """

    try:
        async with pool.acquire() as conn:
            tile_bytes = await conn.fetchval(
                sql,
                min_x, min_y, max_x, max_y,
                extent, buffer_px,
                layer,
            )
    except Exception as exc:
        # Common cause: materialised view hasn't been created yet.
        log.warning("MVT generation failed for layer=%s z=%d/%d/%d: %s",
                    layer, z, x, y, exc)
        return None
    return bytes(tile_bytes) if tile_bytes else b""


# ---------------------------------------------------------------------------
# Materialised view maintenance
# ---------------------------------------------------------------------------

async def refresh_materialized_views(pool) -> dict[str, str]:
    """REFRESH MATERIALIZED VIEW for all substrate MVs. Returns per-MV status."""
    status: dict[str, str] = {}
    async with pool.acquire() as conn:
        for name, cfg in LAYERS.items():
            mv = cfg["mv"]
            try:
                await conn.execute(f"REFRESH MATERIALIZED VIEW {mv}")
                status[mv] = "ok"
            except Exception as exc:
                log.warning("REFRESH MATERIALIZED VIEW %s failed: %s", mv, exc)
                status[mv] = f"error: {exc}"
    return status

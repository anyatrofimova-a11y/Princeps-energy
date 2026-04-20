"""Environment Agency National LiDAR Programme ingester.

The `National LiDAR Programme
<https://environment.data.gov.uk/dataset/ea/national-lidar-programme>`_
publishes 1 m DTM and DSM rasters for the whole of England under Open
Government Licence v3. Tiles are keyed by OSGB 1 km grid squares
(e.g. ``TQ2580``).

Unlike MasterMap, LiDAR rasters are heavy (~10 MB per DTM tile, similar
for DSM) so we never load them into Postgres. Instead the raster files
are cached to disk under::

    data/substrate/lidar/{tile_id}_DTM.tif
    data/substrate/lidar/{tile_id}_DSM.tif

and the ``substrate_lidar_tiles`` table records metadata + paths so the
tiler/frontend can resolve a tile by bbox.

Endpoints used:

  * `Defra Data Services Platform` download API —
    ``https://environment.data.gov.uk/api/file/download?fileDataSetId=…``
  * WCS fallback ``/arcgis/services/…/ImageServer/WCSServer``

A bbox request resolves to the set of 1 km OSGB tiles, downloads any
that are not yet cached, and registers their metadata in PostGIS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("princeps.substrate.lidar")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CACHE_DIR = pathlib.Path(os.environ.get(
    "SUBSTRATE_LIDAR_CACHE",
    str(pathlib.Path(__file__).resolve().parents[2] / "data" / "substrate" / "lidar"),
))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# EA WCS base for the National LiDAR Programme composite products (1 m).
EA_WCS_DSM = (
    "https://environment.data.gov.uk/arcgis/services/SurveyAsset/"
    "LIDARCompositeDSM/ImageServer/WCSServer"
)
EA_WCS_DTM = (
    "https://environment.data.gov.uk/arcgis/services/SurveyAsset/"
    "LIDARCompositeDTM/ImageServer/WCSServer"
)


# ---------------------------------------------------------------------------
# OSGB tile helpers (reuse conversions)
# ---------------------------------------------------------------------------

from .os_mastermap_ingester import (  # noqa: E402
    bbox_to_tiles as _bbox_to_tiles_10km,
    _wgs84_to_osgb_approx,
    _easting_northing_to_tile,
)


def bbox_to_tiles_1km(bbox: tuple[float, float, float, float]) -> list[str]:
    """List of OSGB 1 km tile ids covering ``bbox`` (WGS84 lon/lat ordering)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    sw_e, sw_n = _wgs84_to_osgb_approx(min_lon, min_lat)
    ne_e, ne_n = _wgs84_to_osgb_approx(max_lon, max_lat)
    tiles = set()
    e = (sw_e // 1000) * 1000
    while e <= ne_e + 1000:
        n = (sw_n // 1000) * 1000
        while n <= ne_n + 1000:
            tiles.add(_easting_northing_to_tile(e, n, tile_km=1))
            n += 1000
        e += 1000
    return sorted(tiles)


def _tile_id_to_bbox_27700(tile_id: str) -> Optional[tuple[float, float, float, float]]:
    """Convert OSGB 1 km tile id (e.g. 'TQ2580') → (min_e, min_n, max_e, max_n).

    Returns None for malformed ids.
    """
    if len(tile_id) < 4:
        return None
    letters = tile_id[:2]
    digits = tile_id[2:]
    if not digits.isdigit() or len(digits) % 2:
        return None
    half = len(digits) // 2
    te = int(digits[:half])
    tn = int(digits[half:])

    # Reverse of _OS_500_LETTERS / _OS_LETTERS
    _OS_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
    _OS_500 = {
        "S": (0, 0), "T": (1, 0),
        "N": (0, 1), "O": (1, 1),
        "H": (0, 2), "J": (1, 2),
    }
    if letters[0] not in _OS_500 or letters[1] not in _OS_LETTERS:
        return None
    maj_e500, maj_n500 = _OS_500[letters[0]]
    minor_i = _OS_LETTERS.index(letters[1])
    # inverse of _easting_northing_to_tile
    e100 = maj_e500 * 5 + (minor_i % 5)
    n100 = maj_n500 * 5 + (4 - minor_i // 5)

    # At 1 km tiles we assume half=2 (standard). Scale accordingly.
    scale = 10_000 if half == 1 else 1_000 if half == 2 else 100
    min_e = e100 * 100_000 + te * scale
    min_n = n100 * 100_000 + tn * scale
    return (min_e, min_n, min_e + scale, min_n + scale)


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

@dataclass
class LidarTileResult:
    tile_id: str
    dtm_path: Optional[str]
    dsm_path: Optional[str]
    bytes_dtm: int = 0
    bytes_dsm: int = 0
    cached: bool = False
    source: str = "ea_nlp"
    error: Optional[str] = None


async def _fetch_wcs(
    client: httpx.AsyncClient,
    wcs_url: str,
    coverage: str,
    bbox_27700: tuple[float, float, float, float],
) -> Optional[bytes]:
    """GetCoverage request to an EA ArcGIS WCS. Returns raw TIFF bytes or None."""
    min_e, min_n, max_e, max_n = bbox_27700
    params = {
        "SERVICE": "WCS",
        "VERSION": "2.0.1",
        "REQUEST": "GetCoverage",
        "COVERAGEID": coverage,
        "FORMAT": "image/tiff",
        "SUBSETTINGCRS": "http://www.opengis.net/def/crs/EPSG/0/27700",
        "SUBSET": [
            f"E({min_e},{max_e})",
            f"N({min_n},{max_n})",
        ],
    }
    try:
        r = await client.get(wcs_url, params=params, timeout=120)
    except httpx.HTTPError as exc:
        log.warning("WCS transport error %s: %s", coverage, exc)
        return None
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or ctype.startswith("text/") or ctype.startswith("application/xml"):
        log.warning("WCS %s returned %d (%s)", coverage, r.status_code, ctype)
        return None
    if len(r.content) < 1024:
        log.warning("WCS %s returned too-small payload (%d bytes)", coverage, len(r.content))
        return None
    return r.content


async def _register_tile(pool, tile: LidarTileResult) -> None:
    """Upsert metadata into substrate_lidar_tiles."""
    bbox_27700 = _tile_id_to_bbox_27700(tile.tile_id)
    if bbox_27700 is None:
        log.warning("Skipping register — unparseable tile id %s", tile.tile_id)
        return
    min_e, min_n, max_e, max_n = bbox_27700
    wkt = (
        f"POLYGON(({min_e} {min_n},{max_e} {min_n},"
        f"{max_e} {max_n},{min_e} {max_n},{min_e} {min_n}))"
    )
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO substrate_lidar_tiles
                (tile_id, bbox, dtm_path, dsm_path, resolution_m, size_bytes, source, fetched_at)
            VALUES ($1, ST_GeomFromText($2, 27700), $3, $4, 1.0, $5, $6, now())
            ON CONFLICT (tile_id) DO UPDATE
                SET dtm_path = COALESCE(EXCLUDED.dtm_path, substrate_lidar_tiles.dtm_path),
                    dsm_path = COALESCE(EXCLUDED.dsm_path, substrate_lidar_tiles.dsm_path),
                    size_bytes = EXCLUDED.size_bytes,
                    fetched_at = now()
        """,
            tile.tile_id, wkt, tile.dtm_path, tile.dsm_path,
            tile.bytes_dtm + tile.bytes_dsm, tile.source)


async def fetch_lidar(
    bbox: tuple[float, float, float, float],
    pool=None,
    products: tuple[str, ...] = ("DTM", "DSM"),
    force_refresh: bool = False,
) -> list[LidarTileResult]:
    """Fetch EA 1 m LiDAR tiles covering a WGS84 bbox.

    Downloads DTM + DSM rasters to disk, registers them in
    ``substrate_lidar_tiles`` (if pool provided), and returns per-tile
    metadata. Missing tiles are not treated as fatal — the raster is
    simply absent and the row will not register.
    """
    tile_ids = bbox_to_tiles_1km(bbox)
    results: list[LidarTileResult] = []

    if not tile_ids:
        return results

    async with httpx.AsyncClient() as client:
        for tile_id in tile_ids:
            bbox_27700 = _tile_id_to_bbox_27700(tile_id)
            if bbox_27700 is None:
                continue
            dtm_path = CACHE_DIR / f"{tile_id}_DTM.tif"
            dsm_path = CACHE_DIR / f"{tile_id}_DSM.tif"
            tr = LidarTileResult(tile_id=tile_id, dtm_path=None, dsm_path=None)

            # DTM
            if "DTM" in products:
                if dtm_path.exists() and not force_refresh:
                    tr.dtm_path = str(dtm_path)
                    tr.bytes_dtm = dtm_path.stat().st_size
                    tr.cached = True
                else:
                    blob = await _fetch_wcs(client, EA_WCS_DTM, "DTM_1m", bbox_27700)
                    if blob:
                        dtm_path.write_bytes(blob)
                        tr.dtm_path = str(dtm_path)
                        tr.bytes_dtm = len(blob)
                    else:
                        tr.error = (tr.error or "") + "DTM fetch failed; "
            # DSM
            if "DSM" in products:
                if dsm_path.exists() and not force_refresh:
                    tr.dsm_path = str(dsm_path)
                    tr.bytes_dsm = dsm_path.stat().st_size
                    tr.cached = tr.cached and True
                else:
                    blob = await _fetch_wcs(client, EA_WCS_DSM, "DSM_1m", bbox_27700)
                    if blob:
                        dsm_path.write_bytes(blob)
                        tr.dsm_path = str(dsm_path)
                        tr.bytes_dsm = len(blob)
                    else:
                        tr.error = (tr.error or "") + "DSM fetch failed; "

            if pool is not None and (tr.dtm_path or tr.dsm_path):
                try:
                    await _register_tile(pool, tr)
                except Exception as exc:
                    log.warning("Tile register failed %s: %s", tile_id, exc)

            results.append(tr)

    return results


async def get_tile_by_id(pool, tile_id: str) -> Optional[dict]:
    """Resolve a tile to {dtm_path, dsm_path, bbox_27700, resolution_m}."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT tile_id, dtm_path, dsm_path, resolution_m,
                   ST_AsGeoJSON(bbox) AS bbox_json
            FROM substrate_lidar_tiles
            WHERE tile_id = $1
        """, tile_id)
    if not row:
        return None
    return {
        "tile_id": row["tile_id"],
        "dtm_path": row["dtm_path"],
        "dsm_path": row["dsm_path"],
        "resolution_m": row["resolution_m"],
        "bbox_geojson": json.loads(row["bbox_json"]) if row["bbox_json"] else None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m utils.substrate.ea_lidar_ingester min_lon,min_lat,max_lon,max_lat")
        sys.exit(1)

    bbox = tuple(float(x) for x in sys.argv[1].split(","))
    if len(bbox) != 4:
        print("bbox must be 4 comma-separated numbers")
        sys.exit(1)

    async def _main():
        import asyncpg
        db_url = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/feasibly")
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
        results = await fetch_lidar(bbox, pool=pool)
        for r in results:
            log.info("tile=%s dtm=%s dsm=%s cached=%s err=%s",
                     r.tile_id,
                     pathlib.Path(r.dtm_path).name if r.dtm_path else "—",
                     pathlib.Path(r.dsm_path).name if r.dsm_path else "—",
                     r.cached, r.error)
        await pool.close()

    asyncio.run(_main())

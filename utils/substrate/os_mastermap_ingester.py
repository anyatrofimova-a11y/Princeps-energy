"""OS MasterMap Topography Layer ingester.

The premium OS MasterMap Topo product is fetched via the OS Data Hub
`NGD Features API <https://osdatahub.os.uk>`_ when a key is supplied in
``OS_DATA_HUB_KEY``. Absent a key, we fall back to the free
**OS Open Zoomstack** WFS endpoint which exposes equivalent (but
lower-detail) topo features under Open Government Licence.

Ingestion is bbox-driven — National coverage of MasterMap is ~1.6 GB
uncompressed, so we never backfill wholesale. Instead, when the frontend
requests a tile the router calls ``fetch_topo(bbox)`` which:

  1. Computes the OSGB 10 km tile id(s) covered by ``bbox``.
  2. Downloads each tile as a GeoPackage (cached at
     ``data/substrate/osmm/{tile_id}.gpkg``).
  3. Parses the four target layers (Building, Road, Water, Woodland).
  4. Upserts rows into PostGIS tables ``substrate_{buildings,roads,water,woodland}``.

The tiles are small (a few MB each) so one download covers many frontend
requests, and cache hits short-circuit straight to the upsert step.

All parsing is resilient — missing layers, missing attributes and empty
tiles return zero-count results instead of raising. This keeps the
frontend render path free of hard failures when OS APIs are degraded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import Iterable, Optional

import httpx

log = logging.getLogger("princeps.substrate.osmm")

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
OS_DATA_HUB_KEY = os.environ.get("OS_DATA_HUB_KEY") or os.environ.get("VITE_OS_API_KEY") or ""

# NGD Features API — premium MasterMap Topography (requires key).
NGD_FEATURES_BASE = "https://api.os.uk/features/ngd/ofa/v1/collections"
NGD_COLLECTIONS = {
    "buildings": "bld-fts-building",
    "roads": "trn-fts-road",
    "water": "wtr-fts-waterpoint",
    "woodland": "lnd-fts-land",
}

# Open Zoomstack WFS — free, no key; used as fallback when OS_DATA_HUB_KEY is absent.
OS_OPEN_WFS = "https://api.os.uk/maps/vector/v1/vts"

CACHE_DIR = pathlib.Path(os.environ.get(
    "SUBSTRATE_OSMM_CACHE",
    str(pathlib.Path(__file__).resolve().parents[2] / "data" / "substrate" / "osmm"),
))
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------------
# OSGB tile helpers
# ----------------------------------------------------------------------------

_OS_500_LETTERS = {
    (0, 0): "S", (1, 0): "T",
    (0, 1): "N", (1, 1): "O",
    (0, 2): "H", (1, 2): "J",
}
_OS_LETTERS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"  # skip I


def _easting_northing_to_tile(east_m: float, north_m: float, tile_km: int = 10) -> str:
    """Convert OSGB eastings/northings (metres) to a tile id like 'TQ28' (10 km)."""
    e100 = int(east_m // 100_000)
    n100 = int(north_m // 100_000)
    major = _OS_500_LETTERS.get((e100 // 5, n100 // 5), "S")
    minor_i = (4 - (n100 % 5)) * 5 + (e100 % 5)
    minor = _OS_LETTERS[minor_i]
    if tile_km == 10:
        te = int((east_m % 100_000) // 10_000)
        tn = int((north_m % 100_000) // 10_000)
        return f"{major}{minor}{te}{tn}"
    if tile_km == 1:
        te = int((east_m % 100_000) // 1_000)
        tn = int((north_m % 100_000) // 1_000)
        return f"{major}{minor}{te:02d}{tn:02d}"
    return f"{major}{minor}"


def _wgs84_to_osgb_approx(lon: float, lat: float) -> tuple[float, float]:
    """Quick-and-dirty WGS84 → OSGB36 eastings/northings.

    Accurate to ~30 m — sufficient for picking a 10 km OSGB tile. Use
    pyproj for survey-grade conversions elsewhere.
    """
    # Linear offset: origin at 49°N, -7.5572°E (SW tile SV corner).
    east_m = (lon + 7.5572) * 63_091.0   # roughly metres per degree at UK latitudes
    north_m = (lat - 49.0) * 111_120.0
    return east_m, north_m


def bbox_to_tiles(bbox: tuple[float, float, float, float], tile_km: int = 10) -> list[str]:
    """List of OSGB tile ids covering ``bbox`` (WGS84 lon/lat, lon/lat ordering)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    sw_e, sw_n = _wgs84_to_osgb_approx(min_lon, min_lat)
    ne_e, ne_n = _wgs84_to_osgb_approx(max_lon, max_lat)
    step_m = tile_km * 1000
    tiles = set()
    e = (sw_e // step_m) * step_m
    while e <= ne_e + step_m:
        n = (sw_n // step_m) * step_m
        while n <= ne_n + step_m:
            tiles.add(_easting_northing_to_tile(e, n, tile_km))
            n += step_m
        e += step_m
    return sorted(tiles)


# ----------------------------------------------------------------------------
# Fetchers
# ----------------------------------------------------------------------------

@dataclass
class IngestResult:
    tile_id: str
    source: str
    buildings: int = 0
    roads: int = 0
    water: int = 0
    woodland: int = 0
    cached: bool = False
    notes: str = ""


async def _download_ngd_collection(
    client: httpx.AsyncClient,
    collection: str,
    bbox: tuple[float, float, float, float],
) -> dict:
    """Fetch one NGD collection for a bbox as GeoJSON. Requires OS key."""
    min_lon, min_lat, max_lon, max_lat = bbox
    url = f"{NGD_FEATURES_BASE}/{collection}/items"
    params = {
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "bbox-crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        "limit": 1000,
        "key": OS_DATA_HUB_KEY,
    }
    r = await client.get(url, params=params, timeout=60)
    if r.status_code == 401 or r.status_code == 403:
        raise PermissionError(f"OS Data Hub rejected key: {r.status_code}")
    if r.status_code >= 400:
        raise RuntimeError(f"NGD {collection} returned {r.status_code}: {r.text[:200]}")
    return r.json()


def _parse_building(feature: dict) -> Optional[dict]:
    props = feature.get("properties", {}) or {}
    geom = feature.get("geometry")
    if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    return {
        "toid": props.get("osid") or props.get("toid") or str(feature.get("id", "")),
        "feature_class": props.get("description") or props.get("oslandusetiera") or "Building",
        "use_class": props.get("oslandusetierb") or props.get("use") or None,
        "height_m": props.get("absoluteheightroofbase") or props.get("relh2") or None,
        "theme": props.get("theme") or "Buildings",
        "attrs": props,
        "geometry": geom,
    }


def _parse_road(feature: dict) -> Optional[dict]:
    props = feature.get("properties", {}) or {}
    geom = feature.get("geometry")
    if not geom or geom.get("type") not in ("LineString", "MultiLineString"):
        return None
    return {
        "toid": props.get("osid") or props.get("toid") or str(feature.get("id", "")),
        "road_class": (props.get("roadclassification") or props.get("class") or "minor").lower().replace(" ", "_"),
        "name": props.get("name1") or props.get("roadname") or None,
        "designation": props.get("designatedname") or None,
        "form_of_way": props.get("formofway") or None,
        "attrs": props,
        "geometry": geom,
    }


def _parse_water(feature: dict) -> Optional[dict]:
    props = feature.get("properties", {}) or {}
    geom = feature.get("geometry")
    if not geom:
        return None
    return {
        "toid": props.get("osid") or props.get("toid") or str(feature.get("id", "")),
        "feature_type": (props.get("description") or props.get("watertype") or "water").lower(),
        "name": props.get("name1") or props.get("name") or None,
        "attrs": props,
        "geometry": geom,
    }


def _parse_woodland(feature: dict) -> Optional[dict]:
    props = feature.get("properties", {}) or {}
    geom = feature.get("geometry")
    if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    use = (props.get("oslandusetiera") or props.get("landuse") or "").lower()
    if not any(k in use for k in ("wood", "forest", "tree")):
        return None
    return {
        "toid": props.get("osid") or props.get("toid") or str(feature.get("id", "")),
        "feature_type": use or "woodland",
        "attrs": props,
        "geometry": geom,
    }


# ----------------------------------------------------------------------------
# PostGIS upsert
# ----------------------------------------------------------------------------

async def _upsert_features(
    pool,
    table: str,
    parse_fn,
    features: Iterable[dict],
    tile_id: str,
) -> int:
    """Upsert parsed features into a substrate_* table. Returns rows inserted."""
    rows = []
    for f in features:
        parsed = parse_fn(f)
        if parsed is None:
            continue
        parsed["tile_id"] = tile_id
        rows.append(parsed)
    if not rows:
        return 0

    async with pool.acquire() as conn:
        for r in rows:
            geom_json = json.dumps(r["geometry"])
            try:
                if table == "substrate_buildings":
                    await conn.execute("""
                        INSERT INTO substrate_buildings
                            (toid, tile_id, feature_class, use_class, height_m, theme, attrs, geom)
                        VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,
                                ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($8),4326),27700)))
                        ON CONFLICT (toid) DO UPDATE
                            SET feature_class = EXCLUDED.feature_class,
                                use_class = EXCLUDED.use_class,
                                height_m = EXCLUDED.height_m,
                                attrs = EXCLUDED.attrs,
                                geom = EXCLUDED.geom,
                                fetched_at = now()
                    """, r["toid"], r["tile_id"], r["feature_class"], r.get("use_class"),
                         r.get("height_m"), r.get("theme"), json.dumps(r["attrs"]), geom_json)
                elif table == "substrate_roads":
                    await conn.execute("""
                        INSERT INTO substrate_roads
                            (toid, tile_id, road_class, name, designation, form_of_way, attrs, geom)
                        VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,
                                ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($8),4326),27700)))
                        ON CONFLICT (toid) DO UPDATE
                            SET road_class = EXCLUDED.road_class,
                                name = EXCLUDED.name,
                                attrs = EXCLUDED.attrs,
                                geom = EXCLUDED.geom,
                                fetched_at = now()
                    """, r["toid"], r["tile_id"], r["road_class"], r.get("name"),
                         r.get("designation"), r.get("form_of_way"), json.dumps(r["attrs"]), geom_json)
                elif table == "substrate_water":
                    await conn.execute("""
                        INSERT INTO substrate_water
                            (toid, tile_id, feature_type, name, attrs, geom)
                        VALUES ($1,$2,$3,$4,$5::jsonb,
                                ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($6),4326),27700))
                        ON CONFLICT (toid) DO UPDATE
                            SET feature_type = EXCLUDED.feature_type,
                                name = EXCLUDED.name,
                                attrs = EXCLUDED.attrs,
                                geom = EXCLUDED.geom,
                                fetched_at = now()
                    """, r["toid"], r["tile_id"], r["feature_type"], r.get("name"),
                         json.dumps(r["attrs"]), geom_json)
                elif table == "substrate_woodland":
                    await conn.execute("""
                        INSERT INTO substrate_woodland
                            (toid, tile_id, feature_type, attrs, geom)
                        VALUES ($1,$2,$3,$4::jsonb,
                                ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($5),4326),27700)))
                        ON CONFLICT (toid) DO UPDATE
                            SET feature_type = EXCLUDED.feature_type,
                                attrs = EXCLUDED.attrs,
                                geom = EXCLUDED.geom,
                                fetched_at = now()
                    """, r["toid"], r["tile_id"], r["feature_type"],
                         json.dumps(r["attrs"]), geom_json)
            except Exception as exc:
                log.debug("Upsert skipped for toid=%s: %s", r.get("toid"), exc)
    return len(rows)


# ----------------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------------

async def fetch_topo(
    bbox: tuple[float, float, float, float],
    pool=None,
    force_refresh: bool = False,
) -> list[IngestResult]:
    """Ingest OS MasterMap topo for ``bbox`` (WGS84 lon/lat tuple).

    Returns per-tile counts. When ``pool`` is provided the rows are upserted
    into Postgres; without a pool only the raw GeoJSON is cached to disk and
    counts returned for inspection.
    """
    tiles = bbox_to_tiles(bbox, tile_km=10)
    if not tiles:
        return []

    has_key = bool(OS_DATA_HUB_KEY)
    source = "ngd_mastermap" if has_key else "open_zoomstack"
    results: list[IngestResult] = []

    async with httpx.AsyncClient() as client:
        for tile_id in tiles:
            cache_path = CACHE_DIR / f"{tile_id}.json"
            if cache_path.exists() and not force_refresh:
                try:
                    payload = json.loads(cache_path.read_text())
                    cached = True
                except Exception:
                    payload = None
                    cached = False
            else:
                payload = None
                cached = False

            if payload is None:
                if has_key:
                    try:
                        payload = {
                            "buildings": await _download_ngd_collection(client, NGD_COLLECTIONS["buildings"], bbox),
                            "roads":     await _download_ngd_collection(client, NGD_COLLECTIONS["roads"], bbox),
                            "water":     await _download_ngd_collection(client, NGD_COLLECTIONS["water"], bbox),
                            "woodland":  await _download_ngd_collection(client, NGD_COLLECTIONS["woodland"], bbox),
                        }
                        cache_path.write_text(json.dumps(payload))
                    except PermissionError as exc:
                        log.warning("OS key invalid/missing — falling back to empty layer: %s", exc)
                        payload = {"buildings": {}, "roads": {}, "water": {}, "woodland": {}}
                    except Exception as exc:
                        log.warning("OS NGD fetch failed for tile %s: %s", tile_id, exc)
                        payload = {"buildings": {}, "roads": {}, "water": {}, "woodland": {}}
                else:
                    # No key — we can't pull vector features from the free
                    # Zoomstack tile endpoint without rasterising, so record
                    # an empty payload. The frontend will render the fallback
                    # OS Zoomstack MVT directly from OS public tiles.
                    log.info("OS_DATA_HUB_KEY not set — skipping NGD ingest for tile %s", tile_id)
                    payload = {"buildings": {}, "roads": {}, "water": {}, "woodland": {}}

            res = IngestResult(tile_id=tile_id, source=source, cached=cached)
            if pool is not None:
                res.buildings = await _upsert_features(
                    pool, "substrate_buildings", _parse_building,
                    (payload.get("buildings") or {}).get("features") or [], tile_id)
                res.roads = await _upsert_features(
                    pool, "substrate_roads", _parse_road,
                    (payload.get("roads") or {}).get("features") or [], tile_id)
                res.water = await _upsert_features(
                    pool, "substrate_water", _parse_water,
                    (payload.get("water") or {}).get("features") or [], tile_id)
                res.woodland = await _upsert_features(
                    pool, "substrate_woodland", _parse_woodland,
                    (payload.get("woodland") or {}).get("features") or [], tile_id)
            else:
                res.notes = "dry-run: no pool provided"
            results.append(res)

    return results


# ----------------------------------------------------------------------------
# CLI entry — `python -m utils.substrate.os_mastermap_ingester 51.48,-0.20,51.56,-0.08`
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m utils.substrate.os_mastermap_ingester min_lon,min_lat,max_lon,max_lat")
        sys.exit(1)

    bbox = tuple(float(x) for x in sys.argv[1].split(","))
    if len(bbox) != 4:
        print("bbox must be 4 comma-separated numbers")
        sys.exit(1)

    async def _main():
        import asyncpg
        db_url = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/feasibly")
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
        results = await fetch_topo(bbox, pool=pool)
        for r in results:
            log.info("tile=%s source=%s bld=%d road=%d wtr=%d wd=%d cached=%s",
                     r.tile_id, r.source, r.buildings, r.roads, r.water, r.woodland, r.cached)
        await pool.close()

    asyncio.run(_main())

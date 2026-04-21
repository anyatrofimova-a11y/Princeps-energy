"""
CAA aerodrome safeguarding ingester.

Populates ``caa_airspace_buffers`` with the two statutory consultation
rings around licensed UK aerodromes:

  * **Inner 6 km**  — tall-structure consultation (any structure above
                       defined obstacle limitation surfaces).
  * **Outer 15 km** — wind turbine / large-array consultation
                       (CAP 738 §3.3, ODPM Circular 01/2003).

The CAA does not currently publish a public WFS for aerodrome
safeguarding rings (the raw data lives in each aerodrome's
safeguarding map which is individually licensed). The ingester
therefore works in two modes:

1. **Live mode** — if ``CAA_SAFEGUARDING_WFS`` env var is set, fetch
   from a WFS/ArcGIS FeatureServer bbox query and upsert.

2. **Fixture mode** (default) — bundle rings synthesised from the top
   50 GB aerodromes' ARP (see ``app/dockets/data/caa_aerodromes_gb.json``).
   Rings are generated server-side with PostGIS ``ST_Buffer`` so they're
   true great-circle polygons on the geography type.

Usage::

    python -m utils.substrate.caa_airspace_ingester            # fixture mode, all
    python -m utils.substrate.caa_airspace_ingester -0.5,51,0.5,52  # bbox

Library::

    from utils.substrate.caa_airspace_ingester import ingest_caa_airspace
    await ingest_caa_airspace(pool, bbox=None)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import sys
from typing import Any

import httpx

log = logging.getLogger("princeps.substrate.caa_airspace")

SOURCE = "caa_airspace"

_FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "app" / "dockets" / "data" / "caa_aerodromes_gb.json"
)

_WFS_URL = os.environ.get("CAA_SAFEGUARDING_WFS", "")

# CAP 738 standard buffers (metres).
_INNER_RING_M = 6_000
_OUTER_RING_M = 15_000


# ───────────────────────── Fixture loader ──────────────────────────────

def _load_fixture() -> list[dict[str, Any]]:
    try:
        with _FIXTURE_PATH.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        return doc.get("aerodromes") or []
    except FileNotFoundError:
        log.warning("CAA aerodromes fixture missing at %s", _FIXTURE_PATH)
        return []
    except json.JSONDecodeError as e:
        log.warning("CAA aerodromes fixture invalid JSON: %s", e)
        return []


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float] | None) -> bool:
    if bbox is None:
        return True
    min_lon, min_lat, max_lon, max_lat = bbox
    # 15 km is ~0.14° latitude / ~0.21° longitude at 51°N — expand bbox so
    # we catch aerodromes whose outer ring just clips into the query bbox.
    pad_lat, pad_lon = 0.20, 0.30
    return (
        (min_lat - pad_lat) <= lat <= (max_lat + pad_lat)
        and (min_lon - pad_lon) <= lon <= (max_lon + pad_lon)
    )


# ───────────────────────── Live WFS fetcher ────────────────────────────

async def _fetch_wfs(
    bbox: tuple[float, float, float, float],
    *, client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Hit the operator-configured CAA WFS/FeatureServer. Must return
    GeoJSON features with at least ``icao``, ``name``, ``lat``, ``lon``
    properties (or polygon geometries already buffered)."""
    if not _WFS_URL:
        return []
    min_lon, min_lat, max_lon, max_lat = bbox
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "outputFormat": "application/json", "srsName": "EPSG:4326",
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326",
    }
    try:
        resp = await client.get(_WFS_URL, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        log.warning("CAA WFS fetch failed, falling back to fixture: %s", e)
        return []
    return payload.get("features") or []


# ───────────────────────── Upsert ──────────────────────────────────────

_UPSERT_SQL = """
    INSERT INTO caa_airspace_buffers
        (feature_id, aerodrome_icao, aerodrome_name, zone_class,
         height_limit_m, buffer_m, geom, raw)
    VALUES ($1, $2, $3, $4, $5, $6,
            ST_Multi(
                ST_Buffer(
                    ST_SetSRID(ST_MakePoint($7, $8), 4326)::geography,
                    $6
                )::geometry
            )::geography,
            $9::jsonb)
    ON CONFLICT (feature_id) DO UPDATE SET
        aerodrome_name = EXCLUDED.aerodrome_name,
        zone_class     = EXCLUDED.zone_class,
        height_limit_m = EXCLUDED.height_limit_m,
        buffer_m       = EXCLUDED.buffer_m,
        geom           = EXCLUDED.geom,
        raw            = EXCLUDED.raw,
        source_updated_at = now()
    RETURNING (xmax = 0) AS inserted
"""


async def _upsert_aerodrome_rings(pool, aerodrome: dict[str, Any]) -> tuple[int, int]:
    """Insert both 6 km and 15 km rings for a single aerodrome."""
    icao = aerodrome.get("icao")
    name = aerodrome.get("name")
    lat = aerodrome.get("lat")
    lon = aerodrome.get("lon")
    if not (icao and lat is not None and lon is not None):
        return 0, 0

    rings = [
        ("inner_6km", _INNER_RING_M, 45.0),
        ("outer_15km", _OUTER_RING_M, 150.0),
    ]
    inserted = updated = 0
    async with pool.acquire() as conn:
        for zone_class, buffer_m, height_limit_m in rings:
            feature_id = f"caa:{icao}:{zone_class}"
            try:
                row = await conn.fetchrow(
                    _UPSERT_SQL,
                    feature_id, icao, name, zone_class,
                    height_limit_m, buffer_m,
                    float(lon), float(lat),
                    json.dumps({"icao": icao, "name": name, "lat": lat, "lon": lon}),
                )
                if row and row["inserted"]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                log.warning("CAA upsert %s/%s failed: %s", icao, zone_class, e)
    return inserted, updated


async def _upsert_wfs_feature(pool, feat: dict[str, Any]) -> tuple[int, int]:
    """Upsert a WFS-returned feature that already carries its own polygon
    geometry. Preserves the polygon rather than regenerating from a point."""
    props = feat.get("properties") or {}
    geom = feat.get("geometry")
    icao = props.get("icao") or props.get("ICAO") or props.get("aerodrome_icao")
    name = props.get("name") or props.get("NAME") or props.get("aerodrome_name")
    zone_class = (props.get("zone_class") or props.get("ZONE_CLASS")
                  or "tall_structure_consultation")
    buffer_m = props.get("buffer_m") or props.get("BUFFER_M") or _OUTER_RING_M
    height_limit_m = props.get("height_limit_m")
    feature_id = (props.get("feature_id") or props.get("OBJECTID")
                  or f"caa:{icao}:{zone_class}")

    if not geom or not icao:
        return 0, 0

    sql = """
        INSERT INTO caa_airspace_buffers
            (feature_id, aerodrome_icao, aerodrome_name, zone_class,
             height_limit_m, buffer_m, geom, raw)
        VALUES ($1, $2, $3, $4, $5, $6,
                ST_Multi(ST_GeomFromGeoJSON($7))::geography,
                $8::jsonb)
        ON CONFLICT (feature_id) DO UPDATE SET
            aerodrome_name = EXCLUDED.aerodrome_name,
            zone_class     = EXCLUDED.zone_class,
            height_limit_m = EXCLUDED.height_limit_m,
            buffer_m       = EXCLUDED.buffer_m,
            geom           = EXCLUDED.geom,
            raw            = EXCLUDED.raw,
            source_updated_at = now()
        RETURNING (xmax = 0) AS inserted
    """
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                sql,
                str(feature_id), icao, name, zone_class,
                float(height_limit_m) if height_limit_m is not None else None,
                int(buffer_m),
                json.dumps(geom),
                json.dumps(props),
            )
            return (1, 0) if (row and row["inserted"]) else (0, 1)
        except Exception as e:
            log.warning("CAA WFS upsert %s failed: %s", feature_id, e)
            return 0, 0


# ───────────────────────── Entry point ─────────────────────────────────

async def ingest_caa_airspace(
    pool,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Ingest CAA airspace buffers for a bbox (or the full fixture).

    Live WFS is tried first if ``CAA_SAFEGUARDING_WFS`` is set and the
    bbox is supplied. Otherwise, the bundled fixture is used to generate
    6 km / 15 km rings with ST_Buffer.
    """
    run_id = None
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            "INSERT INTO constraint_layers_ingest_log (layer, bbox, started_at) "
            "VALUES ($1, $2::jsonb, now()) RETURNING id",
            "caa_airspace", json.dumps(list(bbox)) if bbox else None,
        )

    inserted = updated = 0
    used_source = "fixture"

    try:
        # 1. Try live WFS if configured.
        if _WFS_URL and bbox is not None:
            async with httpx.AsyncClient(headers={
                "User-Agent": "Princeps CAA airspace ingester (contact@princeps.energy)",
                "Accept": "application/json",
            }) as client:
                feats = await _fetch_wfs(bbox, client=client)
            if feats:
                used_source = "wfs"
                for feat in feats:
                    i, u = await _upsert_wfs_feature(pool, feat)
                    inserted += i
                    updated += u

        # 2. Fall back to fixture if WFS empty or unconfigured.
        if used_source == "fixture":
            aerodromes = _load_fixture()
            for a in aerodromes:
                if not _in_bbox(a.get("lat"), a.get("lon"), bbox):
                    continue
                i, u = await _upsert_aerodrome_rings(pool, a)
                inserted += i
                updated += u

    except Exception as e:
        log.exception("CAA airspace ingest failed")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE constraint_layers_ingest_log "
                "SET finished_at=now(), status='failed', error_message=$1 WHERE id=$2",
                str(e), run_id,
            )
        return {"layer": "caa_airspace", "error": str(e),
                "inserted": inserted, "updated": updated}

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE constraint_layers_ingest_log "
            "SET finished_at=now(), status='ok', rows_inserted=$1, rows_updated=$2 "
            "WHERE id=$3",
            inserted, updated, run_id,
        )
    log.info("CAA airspace ingest done (source=%s): inserted=%d updated=%d",
             used_source, inserted, updated)
    return {
        "layer": "caa_airspace", "source": used_source,
        "inserted": inserted, "updated": updated, "bbox": bbox,
    }


# ───────────────────────── CLI ─────────────────────────────────────────

def _parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must be minLon,minLat,maxLon,maxLat — got {s!r}")
    return tuple(parts)  # type: ignore[return-value]


async def _cli():
    bbox = _parse_bbox(sys.argv[1]) if len(sys.argv) > 1 else None
    from app.deps import get_pool
    pool = await get_pool()
    try:
        result = await ingest_caa_airspace(pool, bbox)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_cli())

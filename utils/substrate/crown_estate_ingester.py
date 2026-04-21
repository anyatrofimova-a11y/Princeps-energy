"""
Crown Estate onshore + foreshore land ingester.

The Crown Estate publishes an ArcGIS Hub at
``https://crownestateuk.maps.arcgis.com/`` with public GIS layers for:

  * Rural estates (Windsor, Savernake, Ascot, Dunnose, Glenlivet, etc.)
  * Urban estates (Regents Park & St James's, central London)
  * Foreshore / seabed (12 nm belt around England + Wales)
  * Minerals under rural portfolios
  * Offshore wind seabed leases (Round 1-4 + Celtic Sea)

There is no stable single FeatureServer URL — the Hub exposes a catalogue
and individual layer IDs change. This ingester therefore:

1. Tries a configured FeatureServer URL (``CROWN_ESTATE_FS`` env var).
2. Falls back to a bundled fixture of well-known holdings so the
   consultee resolver gets *something* rather than fail-open.

Usage::

    python -m utils.substrate.crown_estate_ingester             # fixture only
    python -m utils.substrate.crown_estate_ingester -0.5,51,0.5,52   # bbox

Library::

    from utils.substrate.crown_estate_ingester import ingest_crown_estate
    await ingest_crown_estate(pool, bbox=None)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

import httpx

log = logging.getLogger("princeps.substrate.crown_estate")

SOURCE = "crown_estate_land"

_FS_URL = os.environ.get("CROWN_ESTATE_FS", "")


# Well-known Crown Estate holdings — approximate bounding polygons for
# the landowner-consultation layer. WKT (SRID 4326), small enough to
# treat as polygons directly without shapefile ingestion.
#
# Sources:
#   * Crown Estate Annual Reports 2022-2024 (land register summaries)
#   * OS OpenData boundaries (sanity-checked)
#
# These are deliberately coarse — they're used only for the ``crown_land``
# layer predicate in consultee_resolver, not for legal boundaries.
_FIXTURE: list[dict[str, Any]] = [
    {
        "feature_id": "ce:windsor_estate",
        "name": "Windsor Great Park & Home Park",
        "land_class": "rural_estate",
        "holding_type": "freehold",
        "area_ha": 5900,
        # Approx bounding polygon covering Windsor Great Park + Home Park.
        "wkt": (
            "POLYGON(("
            "-0.660 51.395,-0.560 51.395,-0.560 51.495,"
            "-0.660 51.495,-0.660 51.395))"
        ),
    },
    {
        "feature_id": "ce:regents_park",
        "name": "Regent's Park (St James's / Regents)",
        "land_class": "urban_estate",
        "holding_type": "freehold",
        "area_ha": 166,
        "wkt": (
            "POLYGON(("
            "-0.168 51.524,-0.144 51.524,-0.144 51.538,"
            "-0.168 51.538,-0.168 51.524))"
        ),
    },
    {
        "feature_id": "ce:st_jamess",
        "name": "St James's Estate",
        "land_class": "urban_estate",
        "holding_type": "freehold",
        "area_ha": 18,
        "wkt": (
            "POLYGON(("
            "-0.144 51.503,-0.130 51.503,-0.130 51.512,"
            "-0.144 51.512,-0.144 51.503))"
        ),
    },
    {
        "feature_id": "ce:savernake",
        "name": "Savernake Forest (historic lease — Marquess of Ailesbury)",
        "land_class": "rural_estate",
        "holding_type": "leasehold",
        "area_ha": 1800,
        "wkt": (
            "POLYGON(("
            "-1.700 51.365,-1.620 51.365,-1.620 51.430,"
            "-1.700 51.430,-1.700 51.365))"
        ),
    },
    {
        "feature_id": "ce:glenlivet",
        "name": "Glenlivet Estate",
        "land_class": "rural_estate",
        "holding_type": "freehold",
        "area_ha": 23000,
        "wkt": (
            "POLYGON(("
            "-3.450 57.180,-3.150 57.180,-3.150 57.370,"
            "-3.450 57.370,-3.450 57.180))"
        ),
    },
    {
        "feature_id": "ce:ascot_racecourse",
        "name": "Ascot Racecourse",
        "land_class": "rural_estate",
        "holding_type": "freehold",
        "area_ha": 73,
        "wkt": (
            "POLYGON(("
            "-0.682 51.410,-0.660 51.410,-0.660 51.420,"
            "-0.682 51.420,-0.682 51.410))"
        ),
    },
    # Foreshore / seabed — single coarse polygon for E+W coast. This is
    # intentionally wide (the statutory foreshore strip is narrow but
    # varies with tide); the resolver uses ST_DWithin so a coarse boundary
    # is a safe fail-open.
    {
        "feature_id": "ce:foreshore_ew",
        "name": "Crown Estate foreshore — England & Wales",
        "land_class": "foreshore",
        "holding_type": "freehold",
        "area_ha": None,
        # Represented as England+Wales bounding box. Real consultations
        # should trigger a live FeatureServer query via CROWN_ESTATE_FS.
        "wkt": (
            "POLYGON(("
            "-6.500 49.800,2.100 49.800,2.100 56.000,"
            "-6.500 56.000,-6.500 49.800))"
        ),
    },
]


def _bbox_overlaps(wkt: str, bbox: tuple[float, float, float, float] | None) -> bool:
    """Cheap WKT-envelope overlap test so fixture-mode can still honour
    bbox filtering without a round-trip to PostGIS."""
    if bbox is None:
        return True
    try:
        coords = wkt.split("((", 1)[1].split("))", 1)[0]
        pts = [tuple(map(float, p.strip().split())) for p in coords.split(",")]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        f_min_lon, f_max_lon = min(xs), max(xs)
        f_min_lat, f_max_lat = min(ys), max(ys)
    except Exception:
        return True
    min_lon, min_lat, max_lon, max_lat = bbox
    return not (
        f_max_lon < min_lon or f_min_lon > max_lon
        or f_max_lat < min_lat or f_min_lat > max_lat
    )


# ───────────────────────── Live FeatureServer fetcher ──────────────────

async def _fetch_fs(
    bbox: tuple[float, float, float, float],
    *, client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    if not _FS_URL:
        return []
    min_lon, min_lat, max_lon, max_lat = bbox
    params = {
        "where": "1=1",
        "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4326",
        "outFields": "*",
        "f": "geojson",
        "resultRecordCount": "5000",
    }
    try:
        resp = await client.get(_FS_URL, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        log.warning("Crown Estate FS fetch failed: %s", e)
        return []
    return payload.get("features") or []


# ───────────────────────── Upsert ──────────────────────────────────────

_UPSERT_WKT_SQL = """
    INSERT INTO crown_estate_land
        (feature_id, name, land_class, holding_type, area_ha,
         source_updated_at, geom, raw)
    VALUES ($1, $2, $3, $4, $5, now(),
            ST_SetSRID(ST_GeomFromText($6), 4326)::geography,
            $7::jsonb)
    ON CONFLICT (feature_id) DO UPDATE SET
        name = EXCLUDED.name,
        land_class = EXCLUDED.land_class,
        holding_type = EXCLUDED.holding_type,
        area_ha = EXCLUDED.area_ha,
        source_updated_at = EXCLUDED.source_updated_at,
        geom = EXCLUDED.geom,
        raw  = EXCLUDED.raw
    RETURNING (xmax = 0) AS inserted
"""

_UPSERT_GEOJSON_SQL = """
    INSERT INTO crown_estate_land
        (feature_id, name, land_class, holding_type, area_ha,
         source_updated_at, geom, raw)
    VALUES ($1, $2, $3, $4, $5, now(),
            ST_SetSRID(ST_GeomFromGeoJSON($6), 4326)::geography,
            $7::jsonb)
    ON CONFLICT (feature_id) DO UPDATE SET
        name = EXCLUDED.name,
        land_class = EXCLUDED.land_class,
        holding_type = EXCLUDED.holding_type,
        area_ha = EXCLUDED.area_ha,
        source_updated_at = EXCLUDED.source_updated_at,
        geom = EXCLUDED.geom,
        raw  = EXCLUDED.raw
    RETURNING (xmax = 0) AS inserted
"""


def _classify(raw_class: str | None) -> str:
    if not raw_class:
        return "other"
    c = raw_class.lower()
    for key in ("foreshore", "seabed", "rural_estate", "urban_estate",
                "mineral_rights", "windfarm_lease"):
        if key.replace("_", "") in c.replace(" ", "").replace("_", ""):
            return key
    return "other"


async def ingest_crown_estate(
    pool,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    """Upsert Crown Estate holdings. Live FeatureServer if ``CROWN_ESTATE_FS``
    is configured and bbox given; otherwise the bundled fixture."""
    run_id = None
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            "INSERT INTO constraint_layers_ingest_log (layer, bbox, started_at) "
            "VALUES ($1, $2::jsonb, now()) RETURNING id",
            "crown_estate_land", json.dumps(list(bbox)) if bbox else None,
        )

    inserted = updated = 0
    used_source = "fixture"

    try:
        # 1. Live FS (if configured + bbox present).
        if _FS_URL and bbox is not None:
            async with httpx.AsyncClient(headers={
                "User-Agent": "Princeps Crown Estate ingester (contact@princeps.energy)",
                "Accept": "application/json",
            }) as client:
                feats = await _fetch_fs(bbox, client=client)
            if feats:
                used_source = "arcgis"
                async with pool.acquire() as conn:
                    for feat in feats:
                        props = feat.get("properties") or {}
                        geom = feat.get("geometry")
                        if not geom:
                            continue
                        fid = str(props.get("feature_id") or props.get("OBJECTID") or "")
                        if not fid:
                            continue
                        try:
                            row = await conn.fetchrow(
                                _UPSERT_GEOJSON_SQL,
                                fid,
                                props.get("name") or props.get("NAME"),
                                _classify(props.get("land_class") or props.get("LAND_CLASS")),
                                props.get("holding_type") or props.get("HOLDING_TYPE"),
                                float(props["area_ha"]) if props.get("area_ha") else None,
                                json.dumps(geom),
                                json.dumps(props),
                            )
                            if row and row["inserted"]:
                                inserted += 1
                            else:
                                updated += 1
                        except Exception as e:
                            log.warning("Crown Estate FS upsert %s failed: %s", fid, e)

        # 2. Fixture fallback.
        if used_source == "fixture":
            async with pool.acquire() as conn:
                for rec in _FIXTURE:
                    if not _bbox_overlaps(rec["wkt"], bbox):
                        continue
                    try:
                        row = await conn.fetchrow(
                            _UPSERT_WKT_SQL,
                            rec["feature_id"],
                            rec["name"],
                            rec["land_class"],
                            rec.get("holding_type"),
                            rec.get("area_ha"),
                            rec["wkt"],
                            json.dumps({k: v for k, v in rec.items() if k != "wkt"}),
                        )
                        if row and row["inserted"]:
                            inserted += 1
                        else:
                            updated += 1
                    except Exception as e:
                        log.warning("Crown Estate fixture upsert %s failed: %s",
                                    rec["feature_id"], e)

    except Exception as e:
        log.exception("Crown Estate ingest failed")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE constraint_layers_ingest_log "
                "SET finished_at=now(), status='failed', error_message=$1 WHERE id=$2",
                str(e), run_id,
            )
        return {"layer": "crown_estate_land", "error": str(e),
                "inserted": inserted, "updated": updated}

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE constraint_layers_ingest_log "
            "SET finished_at=now(), status='ok', rows_inserted=$1, rows_updated=$2 "
            "WHERE id=$3",
            inserted, updated, run_id,
        )
    log.info("Crown Estate ingest (source=%s): inserted=%d updated=%d",
             used_source, inserted, updated)
    return {"layer": "crown_estate_land", "source": used_source,
            "inserted": inserted, "updated": updated, "bbox": bbox}


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
        result = await ingest_crown_estate(pool, bbox)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_cli())

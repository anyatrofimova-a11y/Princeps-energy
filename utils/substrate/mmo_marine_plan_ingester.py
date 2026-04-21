"""
Marine Management Organisation (MMO) marine plan areas ingester.

MMO publishes 11 adopted marine plans covering English waters under the
Marine & Coastal Access Act 2009. Welsh + Scottish + Northern Irish
plans are handled by Welsh Government / Marine Scotland / DAERA and can
re-use this table via ``tier=regional_admin``.

Primary source: MMO / UKHO Marine Data Exchange + data.gov.uk

    https://www.gov.uk/government/collections/marine-planning-in-england

A stable public FeatureServer isn't always available — UKHO publishes
shapefile bundles. This ingester:

1. Tries a configured ArcGIS FeatureServer / WFS URL
   (``MMO_MARINE_PLAN_URL`` env var), bbox-filtered.
2. Falls back to a bundled list of the 11 English plans with approximate
   bounding boxes so the consultee resolver's ``marine_plan_area`` rule
   surfaces the relevant plan even if the live source is unreachable.

Usage::

    python -m utils.substrate.mmo_marine_plan_ingester
    python -m utils.substrate.mmo_marine_plan_ingester 0,50.5,2,52.5

Library::

    from utils.substrate.mmo_marine_plan_ingester import ingest_marine_plans
    await ingest_marine_plans(pool, bbox=None)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import date
from typing import Any

import httpx

log = logging.getLogger("princeps.substrate.mmo_marine_plan")

SOURCE = "marine_plan_areas"

_FS_URL = os.environ.get("MMO_MARINE_PLAN_URL", "")


# The 11 adopted English marine plans (as of Apr 2026). Bounding boxes
# are generous approximations — fine for consultation triage, not for
# legal boundary determination.
_FIXTURE: list[dict[str, Any]] = [
    # (plan_code, plan_name, tier, adopted, (min_lon, min_lat, max_lon, max_lat))
    {"plan_code": "NE_inshore", "plan_name": "North East Inshore Marine Plan",
     "tier": "inshore", "adopted_date": "2014-04-02",
     "bbox": (-2.20, 53.70, -0.10, 55.85)},
    {"plan_code": "NE_offshore", "plan_name": "North East Offshore Marine Plan",
     "tier": "offshore", "adopted_date": "2014-04-02",
     "bbox": (-1.80, 53.60, 3.50, 56.00)},
    {"plan_code": "E_inshore", "plan_name": "East Inshore Marine Plan",
     "tier": "inshore", "adopted_date": "2014-04-02",
     "bbox": (-0.50, 52.20, 1.90, 53.70)},
    {"plan_code": "E_offshore", "plan_name": "East Offshore Marine Plan",
     "tier": "offshore", "adopted_date": "2014-04-02",
     "bbox": (0.50, 52.20, 3.80, 54.00)},
    {"plan_code": "S_inshore", "plan_name": "South Inshore Marine Plan",
     "tier": "inshore", "adopted_date": "2018-07-17",
     "bbox": (-3.50, 50.10, -0.30, 50.95)},
    {"plan_code": "S_offshore", "plan_name": "South Offshore Marine Plan",
     "tier": "offshore", "adopted_date": "2018-07-17",
     "bbox": (-3.50, 49.40, -0.30, 50.30)},
    {"plan_code": "SE_inshore", "plan_name": "South East Inshore Marine Plan",
     "tier": "inshore", "adopted_date": "2021-06-28",
     "bbox": (-0.30, 50.70, 1.50, 51.60)},
    {"plan_code": "NW_inshore", "plan_name": "North West Inshore Marine Plan",
     "tier": "inshore", "adopted_date": "2021-06-28",
     "bbox": (-5.20, 52.90, -2.70, 54.80)},
    {"plan_code": "NW_offshore", "plan_name": "North West Offshore Marine Plan",
     "tier": "offshore", "adopted_date": "2021-06-28",
     "bbox": (-6.00, 52.50, -3.00, 54.80)},
    {"plan_code": "SW_inshore", "plan_name": "South West Inshore Marine Plan",
     "tier": "inshore", "adopted_date": "2021-06-28",
     "bbox": (-6.50, 49.80, -3.00, 51.50)},
    {"plan_code": "SW_offshore", "plan_name": "South West Offshore Marine Plan",
     "tier": "offshore", "adopted_date": "2021-06-28",
     "bbox": (-7.50, 49.20, -3.30, 51.40)},
]


def _bbox_to_wkt(b: tuple[float, float, float, float]) -> str:
    min_lon, min_lat, max_lon, max_lat = b
    return (
        f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},"
        f"{max_lon} {max_lat},{min_lon} {max_lat},{min_lon} {min_lat}))"
    )


def _bbox_overlaps(a: tuple[float, float, float, float],
                   b: tuple[float, float, float, float] | None) -> bool:
    if b is None:
        return True
    a_min_lon, a_min_lat, a_max_lon, a_max_lat = a
    b_min_lon, b_min_lat, b_max_lon, b_max_lat = b
    return not (
        a_max_lon < b_min_lon or a_min_lon > b_max_lon
        or a_max_lat < b_min_lat or a_min_lat > b_max_lat
    )


# ───────────────────────── Live FS fetcher ─────────────────────────────

async def _fetch_fs(
    bbox: tuple[float, float, float, float],
    *, client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    if not _FS_URL:
        return []
    min_lon, min_lat, max_lon, max_lat = bbox
    # Assume ArcGIS FeatureServer query syntax — covers both the UKHO and
    # data.gov.uk adapters we've seen.
    params = {
        "where": "1=1",
        "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4326",
        "outFields": "*",
        "f": "geojson",
        "resultRecordCount": "1000",
    }
    try:
        resp = await client.get(_FS_URL, params=params, timeout=60)
        resp.raise_for_status()
        return (resp.json() or {}).get("features") or []
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        log.warning("MMO marine plan FS fetch failed: %s", e)
        return []


# ───────────────────────── Upsert ──────────────────────────────────────

_UPSERT_WKT_SQL = """
    INSERT INTO marine_plan_areas
        (feature_id, plan_name, plan_code, tier, adopted_date,
         source_updated_at, geom, raw)
    VALUES ($1, $2, $3, $4, $5::date, now(),
            ST_SetSRID(ST_GeomFromText($6), 4326)::geography,
            $7::jsonb)
    ON CONFLICT (feature_id) DO UPDATE SET
        plan_name = EXCLUDED.plan_name,
        plan_code = EXCLUDED.plan_code,
        tier = EXCLUDED.tier,
        adopted_date = EXCLUDED.adopted_date,
        source_updated_at = EXCLUDED.source_updated_at,
        geom = EXCLUDED.geom,
        raw  = EXCLUDED.raw
    RETURNING (xmax = 0) AS inserted
"""

_UPSERT_GEOJSON_SQL = """
    INSERT INTO marine_plan_areas
        (feature_id, plan_name, plan_code, tier, adopted_date,
         source_updated_at, geom, raw)
    VALUES ($1, $2, $3, $4, $5::date, now(),
            ST_SetSRID(ST_GeomFromGeoJSON($6), 4326)::geography,
            $7::jsonb)
    ON CONFLICT (feature_id) DO UPDATE SET
        plan_name = EXCLUDED.plan_name,
        plan_code = EXCLUDED.plan_code,
        tier = EXCLUDED.tier,
        adopted_date = EXCLUDED.adopted_date,
        source_updated_at = EXCLUDED.source_updated_at,
        geom = EXCLUDED.geom,
        raw  = EXCLUDED.raw
    RETURNING (xmax = 0) AS inserted
"""


async def ingest_marine_plans(
    pool,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    run_id = None
    async with pool.acquire() as conn:
        run_id = await conn.fetchval(
            "INSERT INTO constraint_layers_ingest_log (layer, bbox, started_at) "
            "VALUES ($1, $2::jsonb, now()) RETURNING id",
            "marine_plan_areas", json.dumps(list(bbox)) if bbox else None,
        )

    inserted = updated = 0
    used_source = "fixture"

    try:
        # 1. Live FS.
        if _FS_URL and bbox is not None:
            async with httpx.AsyncClient(headers={
                "User-Agent": "Princeps MMO marine-plan ingester (contact@princeps.energy)",
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
                        fid = str(
                            props.get("feature_id") or props.get("OBJECTID")
                            or props.get("plan_code") or ""
                        )
                        if not fid:
                            continue
                        try:
                            row = await conn.fetchrow(
                                _UPSERT_GEOJSON_SQL,
                                fid,
                                props.get("plan_name") or props.get("PlanName") or props.get("NAME"),
                                props.get("plan_code") or props.get("PlanCode"),
                                (props.get("tier") or "inshore").lower(),
                                props.get("adopted_date") or None,
                                json.dumps(geom),
                                json.dumps(props),
                            )
                            if row and row["inserted"]:
                                inserted += 1
                            else:
                                updated += 1
                        except Exception as e:
                            log.warning("MMO FS upsert %s failed: %s", fid, e)

        # 2. Fixture fallback.
        if used_source == "fixture":
            async with pool.acquire() as conn:
                for rec in _FIXTURE:
                    if not _bbox_overlaps(rec["bbox"], bbox):
                        continue
                    try:
                        row = await conn.fetchrow(
                            _UPSERT_WKT_SQL,
                            f"mmo:{rec['plan_code']}",
                            rec["plan_name"],
                            rec["plan_code"],
                            rec["tier"],
                            rec["adopted_date"],
                            _bbox_to_wkt(rec["bbox"]),
                            json.dumps({k: v for k, v in rec.items() if k != "bbox"}),
                        )
                        if row and row["inserted"]:
                            inserted += 1
                        else:
                            updated += 1
                    except Exception as e:
                        log.warning("MMO fixture upsert %s failed: %s",
                                    rec["plan_code"], e)

    except Exception as e:
        log.exception("MMO marine plan ingest failed")
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE constraint_layers_ingest_log "
                "SET finished_at=now(), status='failed', error_message=$1 WHERE id=$2",
                str(e), run_id,
            )
        return {"layer": "marine_plan_areas", "error": str(e),
                "inserted": inserted, "updated": updated}

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE constraint_layers_ingest_log "
            "SET finished_at=now(), status='ok', rows_inserted=$1, rows_updated=$2 "
            "WHERE id=$3",
            inserted, updated, run_id,
        )
    log.info("MMO marine plan ingest (source=%s): inserted=%d updated=%d",
             used_source, inserted, updated)
    return {"layer": "marine_plan_areas", "source": used_source,
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
        result = await ingest_marine_plans(pool, bbox)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_cli())

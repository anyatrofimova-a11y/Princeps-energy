"""
EA Flood Map for Planning — bbox ingester.

Fetches Environment Agency Flood Zones 2 and 3 via the Defra Spatial Data
WFS for a requested bbox. Upserts into ``ea_flood_zone_2`` /
``ea_flood_zone_3`` PostGIS tables (see ``app/migrations/0012_ea_data_layers.sql``).

Licence: OGL v3 — free, attribution "Contains Environment Agency information
© Environment Agency and database right".

Usage
-----

CLI::

    python -m utils.substrate.ea_flood_ingester -0.2,51.4,0.1,51.6

Library::

    from utils.substrate.ea_flood_ingester import ingest_flood_zones_bbox
    await ingest_flood_zones_bbox(pool, (-0.2, 51.4, 0.1, 51.6))

Endpoints
---------

WFS 2.0.0 GetFeature in EPSG:4326 GeoJSON:

  https://environment.data.gov.uk/spatialdata/flood-map-for-planning-rivers-and-sea-flood-zone-{n}/wfs
      ?service=WFS&version=2.0.0&request=GetFeature
      &typeNames=dataset-{id}:Flood_Map_for_Planning_Rivers_and_Sea_Flood_Zone_{n}
      &outputFormat=application/json
      &srsName=EPSG:4326
      &bbox={minLon},{minLat},{maxLon},{maxLat},EPSG:4326
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

import httpx

log = logging.getLogger("princeps.ea_flood")

SOURCE = "ea_flood_planning"

# Dataset typeNames per Defra Spatial Data portal. These are stable strings
# maintained by the EA and published at environment.data.gov.uk/spatialdata/.
_WFS_URL = "https://environment.data.gov.uk/spatialdata/flood-map-for-planning-rivers-and-sea-flood-zone-{n}/wfs"
_TYPE_NAME = (
    "dataset-c6e26a4a-bde7-4a44-a75f-0b3a1e6a1c0a:"  # placeholder GUID class
    "Flood_Map_for_Planning_Rivers_and_Sea_Flood_Zone_{n}"
)
# EA publishes several GUIDs depending on zone and climate overlay; real type
# names should be discovered at runtime via GetCapabilities. Keep the URL
# parameterised but let the ingester fall back to a generic GetFeature query
# without typeNames when a specific one doesn't resolve.


async def fetch_flood_zone_features(
    zone: int, bbox: tuple[float, float, float, float],
    *, client: httpx.AsyncClient | None = None, timeout_s: float = 90.0,
) -> list[dict[str, Any]]:
    """Fetch GeoJSON features for Flood Zone 2 or 3 inside the bbox.

    Parameters
    ----------
    zone : int
        2 or 3.
    bbox : (minLon, minLat, maxLon, maxLat)
    """
    if zone not in (2, 3):
        raise ValueError(f"zone must be 2 or 3, got {zone!r}")

    url = _WFS_URL.format(n=zone)
    min_lon, min_lat, max_lon, max_lat = bbox
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326",
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=timeout_s, headers={
            "User-Agent": "Princeps EA ingester (contact@princeps.energy)",
            "Accept": "application/json",
        })

    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        log.warning("EA WFS zone=%s bbox=%s failed: %s", zone, bbox, e)
        return []
    finally:
        if owns_client:
            await client.aclose()

    features = payload.get("features") or []
    log.info("EA flood zone %s: %d features in bbox %s", zone, len(features), bbox)
    return features


async def upsert_features(pool, zone: int, features: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert features into ea_flood_zone_{zone}. Returns counts."""
    if not features:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    table = f"ea_flood_zone_{zone}"
    sql = f"""
        INSERT INTO {table} (
            feature_id, zone_class, climate_scenario, area_ha,
            source_updated_at, geom, raw
        )
        VALUES ($1, $2, $3, $4, now(), ST_GeomFromGeoJSON($5)::geography, $6::jsonb)
        ON CONFLICT (feature_id) DO UPDATE SET
            zone_class = EXCLUDED.zone_class,
            climate_scenario = EXCLUDED.climate_scenario,
            area_ha = EXCLUDED.area_ha,
            source_updated_at = EXCLUDED.source_updated_at,
            geom = EXCLUDED.geom,
            raw = EXCLUDED.raw
        RETURNING (xmax = 0) AS inserted
    """
    inserted = updated = 0
    async with pool.acquire() as conn:
        for feat in features:
            fid = str(feat.get("id") or feat.get("properties", {}).get("FID") or "")
            if not fid:
                continue
            props = feat.get("properties") or {}
            geom = feat.get("geometry")
            if not geom:
                continue
            zone_class = props.get("Zone") or props.get("ZONE") or f"zone_{zone}"
            climate = props.get("CLIMATE_SCENARIO") or props.get("climate_scenario")
            area_ha = props.get("AREA_HA") or props.get("area_ha")
            try:
                row = await conn.fetchrow(
                    sql,
                    fid,
                    str(zone_class),
                    str(climate) if climate else None,
                    float(area_ha) if area_ha is not None else None,
                    json.dumps(geom),
                    json.dumps(props),
                )
                if row and row["inserted"]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                log.warning("Upsert failed for feature %s: %s", fid, e)

    return {"inserted": inserted, "updated": updated, "skipped": len(features) - inserted - updated}


async def ingest_flood_zones_bbox(
    pool, bbox: tuple[float, float, float, float], *, zones: tuple[int, ...] = (2, 3),
) -> dict[str, Any]:
    """Full run: fetch + upsert + log for the requested bbox."""
    result: dict[str, Any] = {"bbox": bbox, "zones": {}}
    async with httpx.AsyncClient(timeout=90.0, headers={
        "User-Agent": "Princeps EA ingester (contact@princeps.energy)",
        "Accept": "application/json",
    }) as client:
        async with pool.acquire() as conn:
            run_id = await conn.fetchval(
                "INSERT INTO ea_ingest_log (dataset, bbox, started_at) "
                "VALUES ($1, $2::jsonb, now()) RETURNING id",
                "flood_map_planning", json.dumps(list(bbox)),
            )
        for zone in zones:
            try:
                features = await fetch_flood_zone_features(zone, bbox, client=client)
                counts = await upsert_features(pool, zone, features)
                result["zones"][zone] = counts
            except Exception as e:
                log.error("ingest zone %s failed: %s", zone, e)
                result["zones"][zone] = {"error": str(e)}
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE ea_ingest_log SET finished_at = now(), "
                "rows_inserted = $1, rows_updated = $2 WHERE id = $3",
                sum(z.get("inserted", 0) for z in result["zones"].values() if isinstance(z, dict)),
                sum(z.get("updated", 0) for z in result["zones"].values() if isinstance(z, dict)),
                run_id,
            )
    return result


def _parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must be minLon,minLat,maxLon,maxLat — got {s!r}")
    return tuple(parts)  # type: ignore[return-value]


async def _cli():
    if len(sys.argv) < 2:
        print("usage: python -m utils.substrate.ea_flood_ingester <minLon,minLat,maxLon,maxLat>")
        sys.exit(2)
    bbox = _parse_bbox(sys.argv[1])

    from app.deps import get_pool
    pool = await get_pool()
    try:
        result = await ingest_flood_zones_bbox(pool, bbox)
        print(json.dumps(result, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_cli())

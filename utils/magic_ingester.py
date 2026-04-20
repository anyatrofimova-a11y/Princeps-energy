"""
Defra MAGIC constraints ingester — SSSI, AONB / National Landscapes,
Flood Zones 2 & 3, Priority Habitat Inventory.

All layers are hosted via ArcGIS REST at
``https://environment.data.gov.uk/arcgis/rest/services/``. The service
returns features as GeoJSON when ``f=geojson`` is requested, along
with ``resultRecordCount`` paging via ``resultOffset``. We pull by
bbox (EPSG:4326) and upsert into ``magic_constraints``.

CLI
~~~
    python -m utils.magic_ingester --layers sssi,aonb --bbox "-0.2,51.4,0.1,51.6"
    python -m utils.magic_ingester --layers flood2,flood3,habitat --dry-run

Layer slugs map to upstream MapServer / FeatureServer paths (these are
published by Defra / Natural England and do not require auth for
read). Slugs may shift when Defra reorganises MAGIC; update LAYERS
below if a request starts 404-ing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.magic_ingester")

USER_AGENT = "Princeps/1.0 overlay-ingester"
TIMEOUT = 120
RATE_DELAY = 0.5
PAGE_SIZE = 2000

# (layer_slug -> ArcGIS REST FeatureServer/MapServer query endpoint)
LAYERS: dict[str, dict[str, str]] = {
    "sssi": {
        "url": (
            "https://environment.data.gov.uk/arcgis/rest/services/"
            "NE/SitesOfSpecialScientificInterestEngland/MapServer/0/query"
        ),
        "name_field": "SSSI_NAME",
        "id_field": "OBJECTID",
        "designation": "Site of Special Scientific Interest",
    },
    "aonb": {
        "url": (
            "https://environment.data.gov.uk/arcgis/rest/services/"
            "NE/AreasOfOutstandingNaturalBeautyEngland/MapServer/0/query"
        ),
        "name_field": "NAME",
        "id_field": "OBJECTID",
        "designation": "National Landscape (AONB)",
    },
    "flood2": {
        "url": (
            "https://environment.data.gov.uk/arcgis/rest/services/"
            "EA/FloodMapForPlanningRiversAndSeaFloodZone2/MapServer/0/query"
        ),
        "name_field": "ZONE",
        "id_field": "OBJECTID",
        "designation": "Flood Zone 2",
    },
    "flood3": {
        "url": (
            "https://environment.data.gov.uk/arcgis/rest/services/"
            "EA/FloodMapForPlanningRiversAndSeaFloodZone3/MapServer/0/query"
        ),
        "name_field": "ZONE",
        "id_field": "OBJECTID",
        "designation": "Flood Zone 3",
    },
    "habitat": {
        "url": (
            "https://environment.data.gov.uk/arcgis/rest/services/"
            "NE/PriorityHabitatInventoryEngland/MapServer/0/query"
        ),
        "name_field": "MAIN_HABIT",
        "id_field": "OBJECTID",
        "designation": "Priority Habitat",
    },
}

# Convenience alias — the CLI accepts the plain words too.
LAYER_ALIASES = {
    "flood": ["flood2", "flood3"],
    "flood_zone_2": ["flood2"],
    "flood_zone_3": ["flood3"],
    "priority_habitat": ["habitat"],
}


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://anyatrofimova@localhost:5432/feasibly",
    )


def _resolve_layers(requested: list[str]) -> list[str]:
    out: list[str] = []
    for r in requested:
        r = r.strip().lower()
        if r in LAYERS:
            out.append(r)
        elif r in LAYER_ALIASES:
            out.extend(LAYER_ALIASES[r])
        else:
            log.warning("Unknown MAGIC layer: %s — skipping", r)
    return out


async def fetch_layer(
    slug: str,
    bbox: tuple[float, float, float, float] | None,
) -> list[dict[str, Any]]:
    """Fetch all features for a layer (paged)."""
    cfg = LAYERS[slug]
    params: dict[str, Any] = {
        "where": "1=1",
        "outFields": "*",
        "f": "geojson",
        "returnGeometry": "true",
        "outSR": 4326,
        "resultRecordCount": PAGE_SIZE,
    }
    if bbox:
        minlon, minlat, maxlon, maxlat = bbox
        params["geometry"] = f"{minlon},{minlat},{maxlon},{maxlat}"
        params["geometryType"] = "esriGeometryEnvelope"
        params["inSR"] = 4326
        params["spatialRel"] = "esriSpatialRelIntersects"

    headers = {"User-Agent": USER_AGENT}
    features: list[dict[str, Any]] = []
    offset = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers, follow_redirects=True) as client:
        while True:
            params["resultOffset"] = offset
            r = await client.get(cfg["url"], params=params)
            if r.status_code != 200:
                log.warning("MAGIC %s HTTP %s: %s", slug, r.status_code, r.text[:200])
                break
            try:
                data = r.json()
            except Exception as e:
                log.warning("MAGIC %s json decode failed: %s", slug, e)
                break
            page = data.get("features", []) or []
            features.extend(page)
            log.info("[%s] offset=%d page=%d total=%d", slug, offset, len(page), len(features))
            if len(page) < PAGE_SIZE:
                break
            offset += len(page)
            await asyncio.sleep(RATE_DELAY)
    return features


async def upsert_layer(
    conn: asyncpg.Connection,
    slug: str,
    features: list[dict[str, Any]],
) -> int:
    cfg = LAYERS[slug]
    sql = """
        INSERT INTO magic_constraints
            (source_layer, feature_id, name, designation, area_ha, geom, raw_data, ingested_at)
        VALUES (
            $1, $2, $3, $4, $5,
            ST_GeogFromText('SRID=4326;' || ST_AsText(ST_GeomFromGeoJSON($6))),
            $7::jsonb,
            NOW()
        )
        ON CONFLICT (source_layer, feature_id) DO UPDATE SET
            name        = EXCLUDED.name,
            designation = EXCLUDED.designation,
            area_ha     = EXCLUDED.area_ha,
            geom        = EXCLUDED.geom,
            raw_data    = EXCLUDED.raw_data,
            ingested_at = NOW()
    """
    n = 0
    for feat in features:
        try:
            props = feat.get("properties", {}) or {}
            geom = feat.get("geometry")
            if geom is None:
                continue
            fid = str(props.get(cfg["id_field"]) or props.get("OBJECTID") or props.get("objectid") or "")
            if not fid:
                continue
            name = props.get(cfg["name_field"]) or props.get("NAME") or cfg["designation"]
            area_ha = (
                props.get("AREA_HA")
                or props.get("Shape_Area")
                or props.get("SHAPE_Area")
            )
            try:
                area_ha = float(area_ha) / 10000.0 if area_ha and float(area_ha) > 1000 else float(area_ha or 0.0)
            except Exception:
                area_ha = None
            await conn.execute(
                sql,
                slug,
                fid,
                str(name)[:500],
                cfg["designation"],
                area_ha,
                json.dumps(geom),
                json.dumps(props),
            )
            n += 1
        except Exception as e:
            log.warning("[%s] upsert %s failed: %s", slug, feat.get("properties", {}).get("OBJECTID"), e)
    return n


async def ingest(
    layers: list[str],
    bbox: tuple[float, float, float, float] | None,
    dry_run: bool,
) -> dict[str, Any]:
    slugs = _resolve_layers(layers)
    summary: dict[str, Any] = {"layers": {}, "total_features": 0, "dry_run": dry_run}
    if not slugs:
        return summary

    if dry_run:
        for slug in slugs:
            feats = await fetch_layer(slug, bbox)
            summary["layers"][slug] = {"status": "dry", "features": len(feats)}
            summary["total_features"] += len(feats)
            await asyncio.sleep(RATE_DELAY)
        return summary

    conn = await asyncpg.connect(_db_url())
    try:
        for slug in slugs:
            feats = await fetch_layer(slug, bbox)
            n = await upsert_layer(conn, slug, feats)
            summary["layers"][slug] = {"status": "ok", "features": n}
            summary["total_features"] += n
            await asyncio.sleep(RATE_DELAY)
    finally:
        await conn.close()
    return summary


def _parse_bbox(s: str | None) -> tuple[float, float, float, float] | None:
    if not s:
        return None
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox must be minlon,minlat,maxlon,maxlat")
    return (parts[0], parts[1], parts[2], parts[3])


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Ingest Defra MAGIC constraint layers.")
    ap.add_argument("--layers", type=str, default="sssi,aonb,flood2,flood3,habitat",
                    help="Comma-separated layer slugs: sssi,aonb,flood2,flood3,habitat")
    ap.add_argument("--bbox", type=str, help="minlon,minlat,maxlon,maxlat (EPSG:4326)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    layers = [x.strip() for x in args.layers.split(",") if x.strip()]
    bbox = _parse_bbox(args.bbox)
    result = asyncio.run(ingest(layers, bbox, args.dry_run))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()

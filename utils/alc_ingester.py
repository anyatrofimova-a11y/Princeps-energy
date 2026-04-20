"""
Agricultural Land Classification (ALC) — Post-1988 England ingester.

Source
------
Natural England publish the ALC Post-1988 grade polygons on
naturalengland-defra.opendata.arcgis.com, fronted by an ArcGIS REST
FeatureServer. No auth is required; ``f=geojson`` returns GeoJSON
with standard ``resultOffset`` paging.

CLI
~~~
    python -m utils.alc_ingester --bbox "-1.5,51.0,0.5,52.0"
    python -m utils.alc_ingester --dry-run
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

log = logging.getLogger("princeps.alc_ingester")

USER_AGENT = "Princeps/1.0 overlay-ingester"
TIMEOUT = 120
RATE_DELAY = 0.5
PAGE_SIZE = 2000

# Public FeatureServer; slug follows Natural England's portal naming.
ALC_QUERY_URL = (
    "https://services.arcgis.com/JJzESW51TqeY9uat/arcgis/rest/services/"
    "Agricultural_Land_Classification_Provisional_England/FeatureServer/0/query"
)
# Post-1988 grade field candidates (portal has varied column casing over time)
GRADE_FIELDS = ("ALC_GRADE", "alc_grade", "Grade", "GRADE", "ALCGRADE")


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://anyatrofimova@localhost:5432/feasibly",
    )


def _extract_grade(props: dict[str, Any]) -> str | None:
    for f in GRADE_FIELDS:
        v = props.get(f)
        if v:
            return str(v).strip()
    return None


async def fetch_features(
    bbox: tuple[float, float, float, float] | None,
) -> list[dict[str, Any]]:
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
            r = await client.get(ALC_QUERY_URL, params=params)
            if r.status_code != 200:
                log.warning("ALC HTTP %s: %s", r.status_code, r.text[:200])
                break
            try:
                data = r.json()
            except Exception as e:
                log.warning("ALC json decode failed: %s", e)
                break
            page = data.get("features", []) or []
            features.extend(page)
            log.info("ALC offset=%d page=%d total=%d", offset, len(page), len(features))
            if len(page) < PAGE_SIZE:
                break
            offset += len(page)
            await asyncio.sleep(RATE_DELAY)
    return features


async def upsert_features(
    conn: asyncpg.Connection, features: list[dict[str, Any]],
) -> int:
    sql = """
        INSERT INTO alc_grades (feature_id, alc_grade, area_ha, geom, raw_data, ingested_at)
        VALUES (
            $1, $2, $3,
            ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($4), 4326)),
            $5::jsonb,
            NOW()
        )
        ON CONFLICT (feature_id) DO UPDATE SET
            alc_grade   = EXCLUDED.alc_grade,
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
            fid = str(props.get("OBJECTID") or props.get("objectid") or props.get("FID") or "")
            if not fid:
                continue
            grade = _extract_grade(props) or "Unknown"
            area_ha = props.get("AREA_HA") or props.get("Shape_Area")
            try:
                # Shape_Area in BNG square metres; divide by 10000 for ha if it looks that way.
                if area_ha and float(area_ha) > 10000:
                    area_ha = float(area_ha) / 10000.0
                else:
                    area_ha = float(area_ha) if area_ha else None
            except Exception:
                area_ha = None
            await conn.execute(
                sql,
                fid, grade, area_ha,
                json.dumps(geom),
                json.dumps(props),
            )
            n += 1
        except Exception as e:
            log.warning("alc upsert %s failed: %s", feat.get("properties", {}).get("OBJECTID"), e)
    return n


async def ingest(
    bbox: tuple[float, float, float, float] | None,
    dry_run: bool,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"dry_run": dry_run}
    feats = await fetch_features(bbox)
    summary["fetched"] = len(feats)
    if dry_run:
        summary["status"] = "dry"
        return summary

    conn = await asyncpg.connect(_db_url())
    try:
        n = await upsert_features(conn, feats)
    finally:
        await conn.close()
    summary["written"] = n
    summary["status"] = "ok"
    return summary


def _parse_bbox(s: str | None) -> tuple[float, float, float, float] | None:
    if not s:
        return None
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox must be minlon,minlat,maxlon,maxlat")
    return tuple(parts)  # type: ignore[return-value]


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Ingest Natural England ALC (post-1988) polygons.")
    ap.add_argument("--bbox", type=str, help="minlon,minlat,maxlon,maxlat (EPSG:4326)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    bbox = _parse_bbox(args.bbox)
    result = asyncio.run(ingest(bbox, args.dry_run))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()

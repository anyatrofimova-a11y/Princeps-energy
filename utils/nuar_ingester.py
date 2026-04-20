"""NUAR — National Underground Asset Register ingester.

Source
------
NUAR is the UK Geospatial Commission's statutory underground-assets map. Full-
dataset access is gated behind an asset-owner or authorised-user agreement
(see https://www.gov.uk/guidance/national-underground-asset-register-nuar),
so bulk automated pulls are not available to third parties.

This ingester therefore exposes **three** paths, all compatible with the
existing ``nuar_assets`` table (see ``sql/migrate_nuar.sql``):

1. ``register_nuar_request(pool, area_bbox, contact_email)``
   Records a formal NUAR access request to the ``nuar_requests`` table. The
   returned row is typically attached to a project so the user can see what
   is gated on NUAR access.

2. ``ingest_nuar_response(pool, path)``
   Parses a GeoJSON or GML export provided by the NUAR programme and
   upserts features into ``nuar_assets``. Gracefully handles mixed geometry
   types (lines / points / polygons).

3. ``ingest_sample_overpass(pool, bbox)``
   Fallback for dev environments without an NUAR agreement — pulls the
   subset of OSM ``power=line``, ``power=cable`` and ``utility=*``
   underground features, tags them as "osm_proxy", and inserts them so
   downstream consumers have *something* to render. Not a substitute for
   NUAR in production.

CLI
~~~
    python -m utils.nuar_ingester --request --bbox 51.48,-0.63,51.55,-0.55 \
        --email dev@example.com
    python -m utils.nuar_ingester --geojson ./nuar_export.geojson
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.ingest.nuar")

NUAR_DOC_URL = "https://www.gov.uk/guidance/national-underground-asset-register-nuar"

_ASSET_TYPES = {"water", "gas", "electric", "electricity", "telecom", "telecoms", "sewer", "other"}


def _db_url() -> str:
    return os.environ.get("DATABASE_URL") or "postgresql://localhost:5432/feasibly"


REQUESTS_DDL = """
CREATE TABLE IF NOT EXISTS nuar_requests (
    id              SERIAL PRIMARY KEY,
    contact_email   TEXT NOT NULL,
    area_bbox       JSONB NOT NULL,
    purpose         TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending / submitted / granted / denied
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    external_ref    TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_nuar_requests_status ON nuar_requests (status);
"""


@dataclass
class NuarIngestReport:
    source: str
    inserted: int
    skipped: int
    warnings: list[str]
    started_at: datetime
    finished_at: datetime

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "rows_upserted": self.inserted,
            "skipped": self.skipped,
            "warnings": self.warnings,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
        }


async def ensure_tables(pool: asyncpg.Pool | asyncpg.Connection) -> None:
    if isinstance(pool, asyncpg.Pool):
        async with pool.acquire() as c:
            await c.execute(REQUESTS_DDL)
    else:
        await pool.execute(REQUESTS_DDL)


async def register_nuar_request(
    pool: asyncpg.Pool,
    *,
    area_bbox: dict[str, float],  # {min_lon, min_lat, max_lon, max_lat}
    contact_email: str,
    purpose: str | None = None,
) -> dict:
    """Record a NUAR access request. Returns the row as a dict.

    This does NOT call NUAR — real access goes via the Geospatial Commission's
    onboarding process. The row is a placeholder the UI can surface so users
    understand the dependency.
    """
    await ensure_tables(pool)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO nuar_requests (contact_email, area_bbox, purpose, status)
               VALUES ($1, $2, $3, 'pending')
               RETURNING id, contact_email, area_bbox, purpose, status, created_at""",
            contact_email,
            json.dumps(area_bbox),
            purpose,
        )
    log.info("NUAR request registered id=%s email=%s bbox=%s", row["id"], contact_email, area_bbox)
    return {
        "id": row["id"],
        "contact_email": row["contact_email"],
        "area_bbox": json.loads(row["area_bbox"]) if isinstance(row["area_bbox"], str) else row["area_bbox"],
        "purpose": row["purpose"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat(),
        "doc_url": NUAR_DOC_URL,
    }


def _normalise_asset_type(raw: Any) -> str:
    s = (str(raw or "other")).strip().lower()
    if s in ("electricity",):
        return "electric"
    if s in ("telecoms",):
        return "telecom"
    if s not in _ASSET_TYPES:
        return "other"
    return s


def _feature_to_row(feat: dict, source: str) -> dict | None:
    """Extract an nuar_assets row from a GeoJSON Feature."""
    geom = feat.get("geometry")
    props = feat.get("properties") or {}
    if not geom or not geom.get("coordinates"):
        return None
    return {
        "nuar_id": props.get("nuar_id") or props.get("id"),
        "asset_type": _normalise_asset_type(
            props.get("asset_type") or props.get("type") or props.get("utility")
        ),
        "owner": props.get("owner") or props.get("operator"),
        "material": props.get("material"),
        "diameter_mm": props.get("diameter_mm") or props.get("diameter"),
        "voltage_kv": props.get("voltage_kv") or props.get("voltage"),
        "depth_m": props.get("depth_m") or props.get("depth"),
        "installed_year": props.get("installed_year") or props.get("year"),
        "geom_geojson": json.dumps(geom),
        "raw_data": json.dumps({**props, "_source": source}),
    }


async def ingest_nuar_response(
    pool: asyncpg.Pool,
    path: str | Path,
    *,
    source_label: str | None = None,
) -> NuarIngestReport:
    """Ingest a GeoJSON or GML file exported from the NUAR programme.

    GML is expected to already be the lightweight GeoJSON-compatible export
    NUAR ships for authorised users; raw OGR-style GML would require a fuller
    parser and is out of scope here. If you have raw GML, convert via ``ogr2ogr
    -f GeoJSON out.geojson in.gml`` first.
    """
    started = datetime.now(timezone.utc)
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    raw = path.read_text()
    try:
        fc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"expected GeoJSON FeatureCollection: {e}")
    if fc.get("type") != "FeatureCollection":
        raise ValueError("not a GeoJSON FeatureCollection")

    features = fc.get("features") or []
    inserted = 0
    skipped = 0
    warnings: list[str] = []
    source = source_label or path.stem

    await ensure_tables(pool)
    async with pool.acquire() as conn:
        for feat in features:
            row = _feature_to_row(feat, source=source)
            if row is None:
                skipped += 1
                continue
            try:
                await conn.execute(
                    """INSERT INTO nuar_assets
                        (nuar_id, asset_type, owner, material, diameter_mm,
                         voltage_kv, depth_m, installed_year, geom, raw_data)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8,
                               ST_SetSRID(ST_GeomFromGeoJSON($9), 4326), $10::jsonb)""",
                    row["nuar_id"], row["asset_type"], row["owner"], row["material"],
                    row["diameter_mm"], row["voltage_kv"], row["depth_m"],
                    row["installed_year"], row["geom_geojson"], row["raw_data"],
                )
                inserted += 1
            except Exception as e:  # noqa: BLE001
                warnings.append(f"feature {inserted+skipped}: {type(e).__name__}: {e}")
                skipped += 1

    finished = datetime.now(timezone.utc)
    log.info("NUAR ingest %s: %d inserted, %d skipped", source, inserted, skipped)
    return NuarIngestReport(
        source=source, inserted=inserted, skipped=skipped, warnings=warnings,
        started_at=started, finished_at=finished,
    )


OVERPASS_URL = "https://overpass-api.de/api/interpreter"


async def ingest_sample_overpass(
    pool: asyncpg.Pool,
    *,
    bbox: tuple[float, float, float, float],  # (min_lat, min_lon, max_lat, max_lon)
) -> NuarIngestReport:
    """Fallback for dev: pull underground utility proxies from OSM via Overpass.

    Tagged with owner='osm_proxy' so it can be distinguished from real NUAR
    data in queries.
    """
    started = datetime.now(timezone.utc)
    south, west, north, east = bbox
    q = f"""
    [out:json][timeout:25];
    (
      way["power"="cable"]({south},{west},{north},{east});
      way["location"="underground"]({south},{west},{north},{east});
      way["utility"]({south},{west},{north},{east});
    );
    out body geom;
    """.strip()
    warnings: list[str] = []
    inserted = 0
    skipped = 0
    async with httpx.AsyncClient(timeout=60) as c:
        try:
            r = await c.post(OVERPASS_URL, data={"data": q})
            r.raise_for_status()
            payload = r.json()
        except Exception as e:  # noqa: BLE001
            warnings.append(f"overpass: {type(e).__name__}: {e}")
            return NuarIngestReport(
                source="overpass_proxy", inserted=0, skipped=0, warnings=warnings,
                started_at=started, finished_at=datetime.now(timezone.utc),
            )

    await ensure_tables(pool)
    async with pool.acquire() as conn:
        for el in payload.get("elements", []):
            if el.get("type") != "way" or not el.get("geometry"):
                skipped += 1
                continue
            coords = [[pt["lon"], pt["lat"]] for pt in el["geometry"]]
            if len(coords) < 2:
                skipped += 1
                continue
            tags = el.get("tags") or {}
            asset_type = _normalise_asset_type(
                tags.get("power") or tags.get("utility") or tags.get("substance") or "other"
            )
            gj = {"type": "LineString", "coordinates": coords}
            try:
                await conn.execute(
                    """INSERT INTO nuar_assets
                        (nuar_id, asset_type, owner, raw_data, geom)
                       VALUES ($1, $2, 'osm_proxy', $3::jsonb,
                               ST_SetSRID(ST_GeomFromGeoJSON($4), 4326))""",
                    str(el["id"]), asset_type, json.dumps(tags), json.dumps(gj),
                )
                inserted += 1
            except Exception as e:  # noqa: BLE001
                warnings.append(f"way {el.get('id')}: {type(e).__name__}: {e}")
                skipped += 1

    finished = datetime.now(timezone.utc)
    log.info("NUAR overpass proxy: %d inserted, %d skipped", inserted, skipped)
    return NuarIngestReport(
        source="overpass_proxy", inserted=inserted, skipped=skipped, warnings=warnings,
        started_at=started, finished_at=finished,
    )


# ── CLI ─────────────────────────────────────────────────────────────────────

async def _cli_main(args) -> None:
    pool = await asyncpg.create_pool(_db_url(), min_size=1, max_size=3)
    try:
        if args.request:
            lat_min, lon_min, lat_max, lon_max = [float(x) for x in args.bbox.split(",")]
            row = await register_nuar_request(
                pool,
                area_bbox={"min_lat": lat_min, "min_lon": lon_min,
                           "max_lat": lat_max, "max_lon": lon_max},
                contact_email=args.email,
                purpose=args.purpose,
            )
            print(json.dumps(row, indent=2))
        elif args.geojson:
            report = await ingest_nuar_response(pool, args.geojson, source_label=args.source)
            print(json.dumps(report.as_dict(), indent=2))
        elif args.overpass_bbox:
            south, west, north, east = [float(x) for x in args.overpass_bbox.split(",")]
            report = await ingest_sample_overpass(pool, bbox=(south, west, north, east))
            print(json.dumps(report.as_dict(), indent=2))
        else:
            print("specify --request, --geojson, or --overpass-bbox")
    finally:
        await pool.close()


def main() -> None:
    ap = argparse.ArgumentParser("nuar_ingester")
    ap.add_argument("--request", action="store_true", help="register a NUAR access request")
    ap.add_argument("--bbox", help="min_lat,min_lon,max_lat,max_lon for --request")
    ap.add_argument("--email", help="contact email for --request")
    ap.add_argument("--purpose", help="purpose string for --request")
    ap.add_argument("--geojson", help="path to NUAR GeoJSON export to ingest")
    ap.add_argument("--source", help="source label (default = filename stem)")
    ap.add_argument("--overpass-bbox", help="south,west,north,east for OSM fallback")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_cli_main(args))


if __name__ == "__main__":
    main()

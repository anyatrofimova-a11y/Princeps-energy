"""Shared helpers for designation connectors.

Two upstream families are in play:

1. **planning.data.gov.uk** — MHCLG's unified planning data API. Returns
   JSON rows whose ``geometry`` field is a WKT ``MULTIPOLYGON`` in WGS84.
   Paginated with ``limit`` (max 500) and ``offset``; supports bbox via
   ``geometry_relation=intersects&geometry=<WKT>``.

2. **Natural England ArcGIS FeatureServers** (services.arcgis.com/JJzESW51TqeY9uat).
   Returns GeoJSON FeatureCollections. Paginated with ``resultOffset``
   + ``resultRecordCount`` (default cap 1000-2000). Supports bbox via
   ``geometry=minlon,minlat,maxlon,maxlat&geometryType=esriGeometryEnvelope``.

UK bounding box for chunked bbox ingest: roughly
``(-7.0, 49.5, 2.0, 58.8)`` in WGS84 (lon/lat). We use a coarse 1deg grid
when a single full-country pull is rate-limited.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import asyncpg
import httpx

log = logging.getLogger("princeps.connectors.designations")

USER_AGENT = "Princeps/1.0 designations-connector"
HTTP_TIMEOUT = 60.0
PAGE_SIZE_PLANNING = 500
PAGE_SIZE_ARCGIS = 2000
RATE_DELAY_S = 0.3

# UK extent in WGS84 (lon_min, lat_min, lon_max, lat_max)
UK_BBOX_WGS84 = (-7.0, 49.5, 2.0, 58.8)


# ---------------------------------------------------------------------------
# Bbox helpers
# ---------------------------------------------------------------------------

def uk_bbox_chunks(step_deg: float = 1.0) -> list[tuple[float, float, float, float]]:
    """Grid the UK extent into `step_deg` tiles (lon_min, lat_min, lon_max, lat_max)."""
    x0, y0, x1, y1 = UK_BBOX_WGS84
    out: list[tuple[float, float, float, float]] = []
    x = x0
    while x < x1:
        y = y0
        while y < y1:
            out.append((x, y, min(x + step_deg, x1), min(y + step_deg, y1)))
            y += step_deg
        x += step_deg
    return out


def bbox_to_wkt(bbox: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = bbox
    return (
        f"POLYGON(({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"
    )


# ---------------------------------------------------------------------------
# planning.data.gov.uk — paginated entity.json
# ---------------------------------------------------------------------------

PLANNING_BASE = "https://www.planning.data.gov.uk/entity.json"


async def planning_fetch_all(
    dataset: str,
    *,
    bbox_wgs84: Optional[tuple[float, float, float, float]] = None,
    client: Optional[httpx.AsyncClient] = None,
    max_pages: int = 5000,
) -> AsyncIterator[dict[str, Any]]:
    """Async-iterate every entity for ``dataset``.

    ``bbox_wgs84`` narrows to a spatial window (used for big datasets like
    flood-risk-zone). Without bbox it pulls the full dataset by offset.
    """
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    try:
        params: dict[str, Any] = {
            "dataset": dataset,
            "limit": PAGE_SIZE_PLANNING,
        }
        if bbox_wgs84:
            params["geometry_relation"] = "intersects"
            params["geometry"] = bbox_to_wkt(bbox_wgs84)

        offset = 0
        pages = 0
        while pages < max_pages:
            params["offset"] = offset
            try:
                r = await client.get(PLANNING_BASE, params=params)
            except httpx.HTTPError as e:
                log.warning("planning.data.gov.uk HTTP error ds=%s off=%d: %s",
                            dataset, offset, e)
                break
            if r.status_code != 200:
                log.warning("planning.data.gov.uk %s off=%d status=%d body=%s",
                            dataset, offset, r.status_code, r.text[:180])
                break
            try:
                data = r.json()
            except Exception as e:
                log.warning("planning.data.gov.uk json decode ds=%s: %s", dataset, e)
                break
            entities = data.get("entities", []) or []
            for ent in entities:
                yield ent
            if len(entities) < PAGE_SIZE_PLANNING:
                return
            offset += len(entities)
            pages += 1
            await asyncio.sleep(RATE_DELAY_S)
    finally:
        if owns_client and client is not None:
            await client.aclose()


# ---------------------------------------------------------------------------
# Natural England ArcGIS REST FeatureServer — GeoJSON
# ---------------------------------------------------------------------------

async def arcgis_fetch_all(
    query_url: str,
    *,
    bbox_wgs84: Optional[tuple[float, float, float, float]] = None,
    out_sr: int = 4326,
    client: Optional[httpx.AsyncClient] = None,
    max_pages: int = 5000,
    page_size: int = PAGE_SIZE_ARCGIS,
) -> AsyncIterator[dict[str, Any]]:
    """Async-iterate every feature from an ArcGIS FeatureServer layer query URL."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    try:
        params: dict[str, Any] = {
            "where": "1=1",
            "outFields": "*",
            "f": "geojson",
            "returnGeometry": "true",
            "outSR": out_sr,
            "resultRecordCount": page_size,
        }
        if bbox_wgs84:
            lon0, lat0, lon1, lat1 = bbox_wgs84
            params.update({
                "geometry": f"{lon0},{lat0},{lon1},{lat1}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
            })
        offset = 0
        pages = 0
        while pages < max_pages:
            params["resultOffset"] = offset
            try:
                r = await client.get(query_url, params=params)
            except httpx.HTTPError as e:
                log.warning("ArcGIS HTTP error %s off=%d: %s", query_url, offset, e)
                break
            if r.status_code != 200:
                log.warning("ArcGIS %s off=%d status=%d body=%s",
                            query_url, offset, r.status_code, r.text[:180])
                break
            try:
                data = r.json()
            except Exception as e:
                log.warning("ArcGIS json decode %s: %s", query_url, e)
                break
            feats = data.get("features", []) or []
            for feat in feats:
                yield feat
            if len(feats) < page_size:
                return
            offset += len(feats)
            pages += 1
            await asyncio.sleep(RATE_DELAY_S)
    finally:
        if owns_client and client is not None:
            await client.aclose()


# ---------------------------------------------------------------------------
# Upsert helpers — convert incoming geometry to 27700 MULTIPOLYGON
# ---------------------------------------------------------------------------

UPSERT_SQL_TEMPLATE = """
INSERT INTO {table} (
    feature_id, source_ref, name, reference, {extra_cols}
    properties, geom, ingested_at
) VALUES (
    $1, $2, $3, $4, {extra_placeholders}
    $5::jsonb,
    ST_Multi(
        ST_Transform(
            ST_SetSRID(ST_GeomFromText($6), $7),
            27700
        )
    ),
    now()
)
ON CONFLICT (feature_id) DO UPDATE SET
    source_ref  = EXCLUDED.source_ref,
    name        = EXCLUDED.name,
    reference   = EXCLUDED.reference,
    {extra_updates}
    properties  = EXCLUDED.properties,
    geom        = EXCLUDED.geom,
    ingested_at = now()
"""


def build_upsert_sql(table: str, extra_cols: list[str]) -> str:
    """Build an ON CONFLICT upsert for a designation table with optional
    extra columns (e.g. flood_zone, alc_grade, local_authority)."""
    if extra_cols:
        cols_str = ", ".join(extra_cols) + ","
        placeholders_str = ", ".join(
            f"${i + 8}" for i in range(len(extra_cols))
        ) + ","
        updates_str = ", ".join(f"{c} = EXCLUDED.{c}" for c in extra_cols) + ","
    else:
        cols_str = ""
        placeholders_str = ""
        updates_str = ""

    return UPSERT_SQL_TEMPLATE.format(
        table=table,
        extra_cols=cols_str,
        extra_placeholders=placeholders_str,
        extra_updates=updates_str,
    )


async def upsert_row(
    conn: asyncpg.Connection,
    sql: str,
    *,
    feature_id: str,
    source_ref: str,
    name: str,
    reference: str,
    properties: dict[str, Any],
    wkt: str,
    src_srid: int,
    extras: Optional[list[Any]] = None,
) -> None:
    """Execute a prebuilt upsert SQL. ``extras`` go between reference and properties."""
    args: list[Any] = [feature_id, source_ref, name, reference]
    args.append(json.dumps(properties))
    args.append(wkt)
    args.append(src_srid)
    if extras:
        args.extend(extras)
    await conn.execute(sql, *args)


# ---------------------------------------------------------------------------
# ArcGIS GeoJSON geometry -> WKT (we keep it simple: let PostGIS do the work)
# ---------------------------------------------------------------------------

def geojson_to_wkt(geom: dict[str, Any]) -> Optional[str]:
    """Return a WKT string for a GeoJSON geometry, or None if unusable.

    We deliberately push conversion to PostGIS via ST_GeomFromGeoJSON elsewhere
    when convenient — but the upsert path wants WKT so we do the conversion
    here for MultiPolygon / Polygon geometries only.
    """
    if not geom:
        return None
    t = geom.get("type")
    if t == "Polygon":
        coords = geom.get("coordinates") or []
        return _poly_to_wkt(coords)
    if t == "MultiPolygon":
        polys = geom.get("coordinates") or []
        parts = [_poly_to_wkt(p, bare=True) for p in polys]
        return "MULTIPOLYGON(" + ", ".join(parts) + ")"
    return None


def _poly_to_wkt(rings: list[list[list[float]]], *, bare: bool = False) -> str:
    ring_strs = []
    for ring in rings:
        pts = ", ".join(f"{c[0]} {c[1]}" for c in ring)
        ring_strs.append(f"({pts})")
    body = ", ".join(ring_strs)
    return f"({body})" if bare else f"POLYGON({body})"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

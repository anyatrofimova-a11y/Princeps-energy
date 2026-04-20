"""HMLR INSPIRE index-polygon lookup.

Data source: ``hmlr_inspire_parcels`` (SRID 27700, GeometryType MultiPolygon).
Monthly publication by HM Land Registry — free, OGL-licensed. Contains every
registered land title extent in England & Wales.

Title Numbers themselves are NOT in this dataset.  A Title Number requires
an HMLR Official Copy search (£3/title — the paid tier).  We return the
INSPIRE ID (unique parcel identifier) and attach a structured TODO describing
what's required to obtain the Title Number.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import asyncpg

log = logging.getLogger("princeps.site_enrichment.hmlr")

_TABLE = "hmlr_inspire_parcels"


async def _table_exists(conn: asyncpg.Connection) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{_TABLE}"))


async def lookup(
    lat: float,
    lon: float,
    *,
    pool: Optional[asyncpg.Pool] = None,
) -> dict[str, Any]:
    """Return the HMLR INSPIRE parcel covering (lat, lon).

    Returns::
        {
          "title_number": None,              # paid tier, not purchased
          "inspire_id": "26-1234567",
          "parcel_area_ha": 4.73,
          "parcel_geom_geojson": {...},
          "todo": "Order HMLR Official Copy (Register entry) to resolve title_number."
        }
    """
    if pool is None:
        raise ValueError("hmlr: no DB pool provided")

    async with pool.acquire() as conn:
        if not await _table_exists(conn):
            return {
                "title_number": None,
                "inspire_id": None,
                "parcel_area_ha": None,
                "parcel_geom_geojson": None,
                "todo": (
                    f"Table '{_TABLE}' not ingested. "
                    "Run `python -m utils.hmlr_inspire_ingester --zipfile <export.zip> "
                    "--authority \"<LAD name>\"` to populate."
                ),
            }

        # INSPIRE parcels are stored in SRID 27700 — transform the input
        # POINT(4326) to BNG for the intersect. Emit the output geometry
        # back to 4326 for map-friendly JSON.
        row = await conn.fetchrow(
            f"""
            SELECT
                inspire_id,
                area_m2,
                ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geom_4326
            FROM {_TABLE}
            WHERE ST_Intersects(
                geom,
                ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700)
            )
            LIMIT 1
            """,
            lon, lat,
        )
        if row is None:
            return {
                "title_number": None,
                "inspire_id": None,
                "parcel_area_ha": None,
                "parcel_geom_geojson": None,
                "todo": "No INSPIRE parcel intersects this point (may be highway / unregistered land).",
            }

        area_m2 = float(row["area_m2"]) if row["area_m2"] is not None else None
        try:
            geojson = json.loads(row["geom_4326"]) if row["geom_4326"] else None
        except Exception:
            geojson = None

        return {
            "title_number": None,
            "inspire_id": row["inspire_id"],
            "parcel_area_ha": round(area_m2 / 10_000.0, 4) if area_m2 else None,
            "parcel_geom_geojson": geojson,
            "todo": (
                "Title number resolution requires HMLR Official Copy purchase "
                "(£3/title via land-registry.data.gov.uk Business Gateway)."
            ),
        }

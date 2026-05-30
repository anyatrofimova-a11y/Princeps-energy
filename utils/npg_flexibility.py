"""
npg_flexibility — Northern Powergrid Flexibility datasets ingester.

Pulls 6 production datasets from https://northernpowergrid.opendatasoft.com:
  * npg-flexibility-dispatch-ehv-zone — historical EHV-zone dispatch
  * slc31e-dispatch                   — SLC31E flexibility dispatch records
  * slc31e-procurement                — SLC31E procurement / tender outcomes
  * slc31e-procurement-locational     — locational procurement breakdown
  * distribution-network-options-assessment-dnoa
                                      — DNOA per-substation MW gap forecasts
  * npg-network-development-report-upcoming-flexibility-services
                                      — upcoming flexibility needs by GSP

Normalised into a single ``npg_flexibility_zones`` table with a
``dataset`` discriminator. Each row carries spatial fields (when present)
in OSGB36 / EPSG:27700 so it joins cleanly to our existing grid ontology.

Licence: Northern Powergrid Open Data Licence v1.0 — free reuse with
attribution required on derived public surfaces.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from pyproj import Transformer

log = logging.getLogger("princeps.npg_flexibility")

BASE = "https://northernpowergrid.opendatasoft.com/api/explore/v2.1"

# Dataset slugs we ingest. Empty dataset (`npg-flexibility-dispatch-ehv-zone`
# returned 0 records at scan time) is included so the polling job picks it up
# automatically when NPg backfills.
DATASETS = [
    "slc31e-dispatch",
    "slc31e-procurement",
    "slc31e-procurement-locational",
    "distribution-network-options-assessment-dnoa",
    "npg-network-development-report-upcoming-flexibility-services",
    "npg-flexibility-dispatch-ehv-zone",
]

_T_WGS84_TO_27700 = Transformer.from_crs(4326, 27700, always_xy=True)


# --- normalisation helpers ---------------------------------------------------
def _num(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _int(v) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


def _to_27700_point(geo_point_2d) -> tuple[float, float] | None:
    """OpenDataSoft geo_point_2d is {lat, lon} (or [lat, lon])."""
    if geo_point_2d is None:
        return None
    if isinstance(geo_point_2d, dict):
        lat = geo_point_2d.get("lat") or geo_point_2d.get("latitude")
        lon = geo_point_2d.get("lon") or geo_point_2d.get("longitude")
    elif isinstance(geo_point_2d, (list, tuple)) and len(geo_point_2d) >= 2:
        lat, lon = geo_point_2d[0], geo_point_2d[1]
    else:
        return None
    if lat is None or lon is None:
        return None
    try:
        e, n = _T_WGS84_TO_27700.transform(float(lon), float(lat))
        return (e, n)
    except Exception:
        return None


def _row_slc31e_dispatch(r: dict) -> dict:
    return {
        "dataset": "slc31e-dispatch",
        "gsp_name": r.get("incident_location_grid_supply_point"),
        "substation_name": None,
        "constraint_zone": r.get("constraint_management_zone_name"),
        "postcode": None,
        "licence_area": r.get("constraint_licence_area"),
        "region": None,
        "geom": None,
        "constraint_trigger": r.get("constraint_trigger"),
        "product": r.get("product"),
        "forecast_year": None,
        "delivery_year": None,
        "flexibility_required_mw": _num(r.get("dispatch_capacity_mw")),
        "flexibility_procured_mw": None,
        "capacity_mva": None,
        "voltage_kv": _num(r.get("maximum_connection_voltage")),
        "provider": r.get("accepting_party"),
        "external_id": r.get("tender_reference"),
        "attrs": r,
    }


def _row_slc31e_procurement(r: dict) -> dict:
    return {
        "dataset": "slc31e-procurement",
        "gsp_name": r.get("service_location_grid_supply_point"),
        "substation_name": None,
        "constraint_zone": r.get("constraint_management_zone_name"),
        "postcode": None,
        "licence_area": r.get("constraint_licence_area"),
        "region": None,
        "geom": _to_27700_point(r.get("geo_point_2d")),
        "constraint_trigger": r.get("constraint_trigger"),
        "product": r.get("product"),
        "forecast_year": None,
        "delivery_year": str(r.get("delivery_year") or "")[:10] or None,
        "flexibility_required_mw": _num(r.get("peak_flexible_capacity_in_mw")),
        "flexibility_procured_mw": _num(r.get("peak_flexible_capacity_in_mw"))
        if str(r.get("bid_outcome", "")).lower().startswith(("accept", "award"))
        else None,
        "capacity_mva": None,
        "voltage_kv": _num(r.get("connection_voltage_in_kv")),
        "provider": r.get("service_provider"),
        "external_id": r.get("tender_reference"),
        "attrs": r,
    }


def _row_slc31e_procurement_locational(r: dict) -> dict:
    # Pick the most recent delivery-year peak forecast as the headline MW.
    fy = (
        _num(r.get("delivery_year_25_26_peak_forecasted_in_delivery_year_mw"))
        or _num(r.get("delivery_year_24_25_peak_forecasted_in_delivery_year_mw"))
        or _num(r.get("delivery_year_26_27_peak_forecasted_in_delivery_year_mw"))
    )
    return {
        "dataset": "slc31e-procurement-locational",
        "gsp_name": None,
        "substation_name": None,
        "constraint_zone": r.get("constraint_management_zone"),
        "postcode": None,
        "licence_area": r.get("constraint_licence_area"),
        "region": None,
        "geom": None,
        "constraint_trigger": r.get("constraint_trigger"),
        "product": r.get("product"),
        "forecast_year": None,
        "delivery_year": None,
        "flexibility_required_mw": fy,
        "flexibility_procured_mw": _num(
            r.get("delivery_year_24_25_total_contracted_in_reporting_year_mw")
        ),
        "capacity_mva": None,
        "voltage_kv": None,
        "provider": None,
        "external_id": None,
        "attrs": r,
    }


def _row_dnoa(r: dict) -> dict:
    return {
        "dataset": "distribution-network-options-assessment-dnoa",
        "gsp_name": None,
        "substation_name": r.get("substation_name"),
        "constraint_zone": None,
        "postcode": r.get("substation_postcode"),
        "licence_area": r.get("licence_area"),
        "region": r.get("npg_region"),
        "geom": _to_27700_point(r.get("geo_point_2d")),
        "constraint_trigger": r.get("dnoa_intervention_decision"),
        "product": r.get("substation_class"),
        "forecast_year": _int(r.get("forecast_constraint_year")),
        "delivery_year": None,
        "flexibility_required_mw": _num(r.get("flexibility_required_mw_2026_27_y1")),
        "flexibility_procured_mw": _num(r.get("flexibility_procured_mw_y1_2026_27")),
        "capacity_mva": _num(r.get("substation_capacity_mva")),
        "voltage_kv": _num(r.get("voltage_kv")),
        "provider": None,
        "external_id": r.get("dnoa_version"),
        "attrs": r,
    }


def _row_upcoming(r: dict) -> dict:
    return {
        "dataset": "npg-network-development-report-upcoming-flexibility-services",
        "gsp_name": r.get("gsp_name_match") or r.get("grid_supply_point"),
        "substation_name": r.get("upcoming_flexibility_needs_substation"),
        "constraint_zone": None,
        "postcode": r.get("gsp_postcode") or r.get("substation_postcode"),
        "licence_area": r.get("licence_area"),
        "region": r.get("northern_powergrid_operational_region"),
        "geom": _to_27700_point(r.get("geo_point_2d")),
        "constraint_trigger": r.get("driver"),
        "product": r.get("point_of_flexibility_substation_type"),
        "forecast_year": _int(r.get("flexibility_needs_start_year")),
        "delivery_year": None,
        "flexibility_required_mw": None,
        "flexibility_procured_mw": None,
        "capacity_mva": None,
        "voltage_kv": None,
        "provider": r.get("scheme_status"),
        "external_id": str(r.get("row_number") or ""),
        "attrs": r,
    }


def _row_ehv_zone(r: dict) -> dict:
    return {
        "dataset": "npg-flexibility-dispatch-ehv-zone",
        "gsp_name": r.get("grid_supply_point") or r.get("gsp"),
        "substation_name": None,
        "constraint_zone": r.get("constraint_management_zone") or r.get("ehv_zone"),
        "postcode": None,
        "licence_area": r.get("licence_area"),
        "region": None,
        "geom": _to_27700_point(r.get("geo_point_2d")),
        "constraint_trigger": r.get("constraint_trigger"),
        "product": r.get("product"),
        "forecast_year": None,
        "delivery_year": None,
        "flexibility_required_mw": _num(r.get("dispatch_capacity_mw")),
        "flexibility_procured_mw": None,
        "capacity_mva": None,
        "voltage_kv": None,
        "provider": r.get("provider") or r.get("accepting_party"),
        "external_id": r.get("tender_reference"),
        "attrs": r,
    }


ROW_NORMALISERS = {
    "slc31e-dispatch": _row_slc31e_dispatch,
    "slc31e-procurement": _row_slc31e_procurement,
    "slc31e-procurement-locational": _row_slc31e_procurement_locational,
    "distribution-network-options-assessment-dnoa": _row_dnoa,
    "npg-network-development-report-upcoming-flexibility-services": _row_upcoming,
    "npg-flexibility-dispatch-ehv-zone": _row_ehv_zone,
}


# --- fetching ----------------------------------------------------------------
async def fetch_dataset(
    client: httpx.AsyncClient, slug: str, *, batch: int = 100, max_records: int = 10_000
) -> list[dict]:
    """Stream all rows from an OpenDataSoft dataset, paginated."""
    rows: list[dict] = []
    offset = 0
    while offset < max_records:
        params = {"limit": str(batch), "offset": str(offset)}
        r = await client.get(
            f"{BASE}/catalog/datasets/{slug}/records", params=params, timeout=30.0
        )
        if r.status_code != 200:
            log.warning("NPg %s offset=%d HTTP %s", slug, offset, r.status_code)
            break
        body = r.json()
        results = body.get("results", [])
        if not results:
            break
        rows.extend(results)
        if len(results) < batch:
            break
        offset += batch
        await asyncio.sleep(0.1)  # polite jitter
    return rows


# --- upsert -------------------------------------------------------------------
UPSERT_SQL = """
INSERT INTO uk_flexibility_zones
  (dno, dataset, external_id, gsp_name, substation_name, constraint_zone, postcode,
   licence_area, region, geom, constraint_trigger, product, forecast_year,
   delivery_year, flexibility_required_mw, flexibility_procured_mw,
   capacity_mva, voltage_kv, provider, attrs, ingested_at)
VALUES (
  'NPG', $1, $2, $3, $4, $5, $6, $7, $8,
  CASE WHEN $9::float[] IS NULL THEN NULL
       ELSE ST_SetSRID(ST_MakePoint(($9::float[])[1], ($9::float[])[2]), 27700) END,
  $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, NOW()
)
ON CONFLICT (dataset, external_id_key) DO UPDATE SET
  gsp_name = EXCLUDED.gsp_name,
  substation_name = EXCLUDED.substation_name,
  constraint_zone = EXCLUDED.constraint_zone,
  postcode = EXCLUDED.postcode,
  licence_area = EXCLUDED.licence_area,
  region = EXCLUDED.region,
  geom = EXCLUDED.geom,
  constraint_trigger = EXCLUDED.constraint_trigger,
  product = EXCLUDED.product,
  forecast_year = EXCLUDED.forecast_year,
  delivery_year = EXCLUDED.delivery_year,
  flexibility_required_mw = EXCLUDED.flexibility_required_mw,
  flexibility_procured_mw = EXCLUDED.flexibility_procured_mw,
  capacity_mva = EXCLUDED.capacity_mva,
  voltage_kv = EXCLUDED.voltage_kv,
  provider = EXCLUDED.provider,
  attrs = EXCLUDED.attrs,
  ingested_at = NOW()
"""


async def upsert_rows(conn, rows: list[dict]) -> int:
    import hashlib

    n = 0
    for r in rows:
        # external_id_key — synthesise a TRULY stable key from the full row
        # payload so multiple records sharing a tender_reference (one record
        # per dispatch incident within a tender) don't collide on UPSERT.
        attrs_blob = json.dumps(r.get("attrs") or {}, sort_keys=True, default=str)
        row_hash = hashlib.sha1(attrs_blob.encode()).hexdigest()[:16]
        external_id = f"{r.get('external_id') or 'nokey'}|{row_hash}"
        geom = r.get("geom")  # tuple (e,n) or None
        try:
            await conn.execute(
                UPSERT_SQL,
                r["dataset"],
                external_id,
                r.get("gsp_name"),
                r.get("substation_name"),
                r.get("constraint_zone"),
                r.get("postcode"),
                r.get("licence_area"),
                r.get("region"),
                list(geom) if geom else None,
                r.get("constraint_trigger"),
                r.get("product"),
                r.get("forecast_year"),
                r.get("delivery_year"),
                r.get("flexibility_required_mw"),
                r.get("flexibility_procured_mw"),
                r.get("capacity_mva"),
                r.get("voltage_kv"),
                r.get("provider"),
                json.dumps(r.get("attrs") or {}),
            )
            n += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("npg_flexibility upsert skip %s: %s", r.get("dataset"), exc)
    return n


async def refresh_all(pool, datasets: list[str] | None = None) -> dict[str, int]:
    """Refresh all NPg Flexibility datasets. Returns {slug: rows_written}."""
    slugs = datasets or DATASETS
    summary: dict[str, int] = {}
    async with httpx.AsyncClient(
        headers={"User-Agent": "Princeps/1.0 (princeps.energy)"}
    ) as client:
        for slug in slugs:
            log.info("[npg_flexibility] fetching %s", slug)
            try:
                raw = await fetch_dataset(client, slug)
            except Exception as exc:  # noqa: BLE001
                log.warning("[npg_flexibility] fetch failed %s: %s", slug, exc)
                summary[slug] = -1
                continue
            normaliser = ROW_NORMALISERS.get(slug)
            if not normaliser:
                summary[slug] = 0
                continue
            rows = [normaliser(r) for r in raw]
            async with pool.acquire() as conn:
                async with conn.transaction():
                    n = await upsert_rows(conn, rows)
            summary[slug] = n
            log.info("[npg_flexibility] %s: %d rows written", slug, n)
    return summary


# --- agent context ------------------------------------------------------------
async def flexibility_context(pool, *, lat: float, lon: float, radius_m: float = 5000):
    """Return a structured + human-readable context block for the agent.

    Caller passes WGS84 lat/lon (Princeps standard). We search for NPg
    flexibility events whose ``geom`` is within ``radius_m`` metres of the
    site or whose ``postcode``/``substation_name`` matches the closest grid
    asset.
    """
    rows = await pool.fetch(
        """
        SELECT dataset, gsp_name, substation_name, constraint_zone,
               constraint_trigger, product, forecast_year, delivery_year,
               flexibility_required_mw, flexibility_procured_mw,
               capacity_mva, voltage_kv, provider, region,
               ST_Distance(geom, ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326),27700)) AS dist_m
        FROM npg_flexibility_zones
        WHERE geom IS NOT NULL
          AND ST_DWithin(geom,
                ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326),27700), $3)
        ORDER BY dist_m ASC
        LIMIT 25
        """,
        lon, lat, radius_m,
    )
    return [dict(r) for r in rows]

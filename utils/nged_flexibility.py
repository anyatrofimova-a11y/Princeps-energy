"""
nged_flexibility — National Grid Electricity Distribution (NGED, formerly WPD)
Flexibility ingester via the CKAN data portal.

Source: https://connecteddata.nationalgrid.co.uk/  (CKAN v3 API)
Licence: NGED Open Data Licence (UK gov OGL-style)

Pulls the HOW-MUCH HV Zones CSV under `flexibility-forecasts` and writes
each (CMZ, financial year, scenario) row into the unified
``uk_flexibility_zones`` table with ``dno='NGED'``.

Forecast scenarios mirror the NESO FES pathways (Holistic Transition,
Falling Short, etc.). Spatial geom is not provided in the CSV — that
ships in the WHERE All Polygons GPKG resource and is deferred to a
separate Phase-2 enrichment step.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
from typing import Any

import httpx

log = logging.getLogger("princeps.nged_flexibility")

CKAN_BASE = "https://connecteddata.nationalgrid.co.uk/api/3/action"

# Dataset (CKAN package) → list of resource-name patterns to ingest.
# We pick the CSVs only; ZIPs and gpkgs deferred to Phase 2.
DATASETS_CSV = {
    "flexibility-forecasts": [
        "HOW MUCH HV Zones",
        "HOW MUCH and WHEN LV Zones",
        "OVERVIEW All Zones",
    ],
    "flexibility-charts": [],  # crawl all CSVs
    "flexibility-trades-data-and-results": [],
    "flexibility-primacy": [],
    "flexibility-reports": [],
}


def _num(v) -> float | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(str(v).replace(",", "").replace("£", "").strip())
    except (TypeError, ValueError):
        return None


def _int(v) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


async def package_show(client: httpx.AsyncClient, package_id: str) -> dict[str, Any]:
    r = await client.get(f"{CKAN_BASE}/package_show", params={"id": package_id}, timeout=30.0)
    r.raise_for_status()
    return r.json().get("result", {})


async def fetch_csv_rows(client: httpx.AsyncClient, url: str) -> list[dict[str, str]]:
    """Stream a CKAN CSV resource as a list of dict rows."""
    r = await client.get(url, timeout=120.0, follow_redirects=True)
    r.raise_for_status()
    # NGED CSVs are sometimes latin-1 (£ sign etc.) — try utf-8 first, fall back.
    try:
        text = r.content.decode("utf-8")
    except UnicodeDecodeError:
        text = r.content.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def _row_how_much(slug: str, source_name: str, row: dict[str, str]) -> dict[str, Any]:
    """Normalise a 'HOW MUCH HV Zones' / 'HOW MUCH and WHEN LV Zones' row.

    Columns observed (encoding may garble £ → '?'):
      CMZ Code, Zone name, Scenario, Financial Year,
      Main flexibility product, Peak capacity required [MW],
      Estimated availability energy [MWh], Estimated utilisation energy [MWh],
      Availability ceiling price [£/MW/h], Utilisation ceiling price [£/MWh]
    """
    cmz = (row.get("CMZ Code") or row.get("CMZ code") or "").strip()
    return {
        "dno": "NGED",
        "dataset": f"nged-{slug}-{source_name.lower().replace(' ', '-')}"[:80],
        "external_id": cmz or None,
        "gsp_name": None,
        "substation_name": None,
        "constraint_zone": (row.get("Zone name") or row.get("Zone Name") or "").strip() or None,
        "postcode": None,
        "licence_area": "NGED",
        "region": None,
        "geom": None,
        "constraint_trigger": (row.get("Main flexibility product") or "").strip() or None,
        "product": (row.get("Main flexibility product") or "").strip() or None,
        "forecast_year": _int(row.get("Financial Year")),
        "delivery_year": (row.get("Financial Year") or "").strip() or None,
        "flexibility_required_mw": _num(row.get("Peak capacity required [MW]")),
        "flexibility_procured_mw": None,
        "capacity_mva": None,
        "voltage_kv": None,
        "provider": (row.get("Scenario") or "").strip() or None,
        "attrs": row,
    }


def _row_generic(slug: str, source_name: str, row: dict[str, str]) -> dict[str, Any]:
    """Best-effort normaliser for unknown NGED CSV shapes — captures common
    fields by heuristic match so we can still UPSERT the raw payload.
    """
    def first(*keys):
        for k in keys:
            v = row.get(k)
            if v not in (None, "", "-"):
                return v
        return None

    return {
        "dno": "NGED",
        "dataset": f"nged-{slug}-{source_name.lower().replace(' ', '-')}"[:80],
        "external_id": first("CMZ Code", "Zone Code", "ID", "Id", "Tender Reference"),
        "gsp_name": first("GSP", "GSP Name", "Grid Supply Point"),
        "substation_name": first("Substation", "Substation Name"),
        "constraint_zone": first("Zone name", "Zone Name", "CMZ Name"),
        "postcode": first("Postcode", "Outcode"),
        "licence_area": "NGED",
        "region": first("Region", "Licence Area"),
        "geom": None,
        "constraint_trigger": first("Constraint Trigger", "Driver", "Main flexibility product"),
        "product": first("Product", "Main flexibility product", "Service"),
        "forecast_year": _int(first("Financial Year", "Forecast Year", "Year")),
        "delivery_year": first("Delivery Year", "Financial Year"),
        "flexibility_required_mw": _num(
            first("Peak capacity required [MW]", "MW Required", "Capacity MW",
                  "Peak Required MW")
        ),
        "flexibility_procured_mw": _num(
            first("MW Procured", "Awarded MW", "Capacity Awarded [MW]")
        ),
        "capacity_mva": _num(first("Capacity MVA", "MVA")),
        "voltage_kv": _num(first("Voltage", "Voltage [kV]", "kV")),
        "provider": first("Provider", "Service Provider", "Awardee", "Scenario"),
        "attrs": row,
    }


UPSERT_SQL = """
INSERT INTO uk_flexibility_zones
  (dno, dataset, external_id, gsp_name, substation_name, constraint_zone,
   postcode, licence_area, region, geom, constraint_trigger, product,
   forecast_year, delivery_year, flexibility_required_mw,
   flexibility_procured_mw, capacity_mva, voltage_kv, provider, attrs,
   ingested_at)
VALUES (
  $1, $2, $3, $4, $5, $6, $7, $8, $9, NULL,
  $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, NOW()
)
ON CONFLICT (dataset, external_id_key) DO UPDATE SET
  gsp_name = EXCLUDED.gsp_name,
  substation_name = EXCLUDED.substation_name,
  constraint_zone = EXCLUDED.constraint_zone,
  postcode = EXCLUDED.postcode,
  region = EXCLUDED.region,
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


async def upsert_rows(conn, rows: list[dict[str, Any]]) -> int:
    n = 0
    for r in rows:
        attrs_blob = json.dumps(r.get("attrs") or {}, sort_keys=True, default=str)
        row_hash = hashlib.sha1(attrs_blob.encode()).hexdigest()[:16]
        external_id = f"{r.get('external_id') or 'nokey'}|{row_hash}"
        try:
            await conn.execute(
                UPSERT_SQL,
                r["dno"], r["dataset"], external_id,
                r.get("gsp_name"), r.get("substation_name"),
                r.get("constraint_zone"), r.get("postcode"),
                r.get("licence_area"), r.get("region"),
                r.get("constraint_trigger"), r.get("product"),
                r.get("forecast_year"), r.get("delivery_year"),
                r.get("flexibility_required_mw"),
                r.get("flexibility_procured_mw"),
                r.get("capacity_mva"), r.get("voltage_kv"),
                r.get("provider"),
                json.dumps(r.get("attrs") or {}, default=str),
            )
            n += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("nged upsert skip %s: %s", r.get("dataset"), exc)
    return n


async def refresh_all(pool, slugs: list[str] | None = None) -> dict[str, int]:
    """Ingest NGED Flexibility CSV resources. Returns {dataset_resource: rows}."""
    pkgs = slugs or list(DATASETS_CSV.keys())
    summary: dict[str, int] = {}
    async with httpx.AsyncClient(
        headers={"User-Agent": "Princeps/1.0 (princeps.energy)"}
    ) as client:
        for slug in pkgs:
            try:
                pkg = await package_show(client, slug)
            except Exception as exc:  # noqa: BLE001
                log.warning("nged: package_show failed for %s: %s", slug, exc)
                continue
            allowed_names = DATASETS_CSV.get(slug) or []
            for res in pkg.get("resources", []):
                name = res.get("name", "")
                fmt = (res.get("format") or "").upper()
                if fmt != "CSV":
                    continue
                if allowed_names and not any(p.lower() in name.lower() for p in allowed_names):
                    continue
                url = res.get("url")
                if not url:
                    continue
                log.info("[nged %s] fetching %s", slug, name)
                try:
                    csv_rows = await fetch_csv_rows(client, url)
                except Exception as exc:  # noqa: BLE001
                    log.warning("[nged %s] CSV fetch failed %s: %s", slug, name, exc)
                    continue

                normaliser = (
                    _row_how_much
                    if "HOW MUCH" in name.upper()
                    else _row_generic
                )
                rows = [normaliser(slug, name, r) for r in csv_rows]
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        n = await upsert_rows(conn, rows)
                summary[f"{slug}:{name[:40]}"] = n
                log.info("[nged %s] %s: %d rows written", slug, name, n)
                await asyncio.sleep(0.2)
    return summary

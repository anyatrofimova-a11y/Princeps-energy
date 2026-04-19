"""
PeeringDB ingester — Internet Exchange + data-centre facility footprint.

Layers fibre density onto Princeps's site-prospecting / DC-twin / demand forecast.
Free JSON API (https://www.peeringdb.com/api), no auth needed for reads.

Writes to: peering_facilities, peering_ixs, peering_ixfac (SRID 4326).

CLI:
    python -m utils.peeringdb_ingester --country GB
    python -m utils.peeringdb_ingester --country GB DE NL
    python -m utils.peeringdb_ingester --all
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

log = logging.getLogger("princeps.peeringdb_ingester")

PDB_BASE = "https://www.peeringdb.com/api"
USER_AGENT = "Princeps/1.0 peeringdb-ingester"
TIMEOUT = 60
RATE_DELAY = 1.1  # PeeringDB anon rate limit ~1 req/s


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://anyatrofimova@localhost:5432/feasibly",
    )


def _get(path: str, params: dict[str, Any] | None = None) -> list[dict]:
    import time as _t

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    api_key = os.environ.get("PEERINGDB_API_KEY")
    if api_key:
        headers["Authorization"] = f"Api-Key {api_key}"
    url = f"{PDB_BASE}/{path.lstrip('/')}"
    with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
        for attempt in range(5):
            r = client.get(url, params=params or {})
            if r.status_code == 429:
                wait = int(r.headers.get("retry-after", "30"))
                log.warning("429 on %s — sleeping %ds (attempt %d/5)", path, wait, attempt + 1)
                _t.sleep(wait)
                continue
            r.raise_for_status()
            return r.json().get("data", [])
    raise RuntimeError(f"PeeringDB {path} rate-limited 5x")


def fetch_facilities(country: str | None = None) -> list[dict]:
    params: dict[str, Any] = {"depth": 0}
    if country:
        params["country"] = country
    log.info("fetching /fac country=%s ...", country or "ALL")
    return _get("fac", params)


def fetch_ixs(country: str | None = None) -> list[dict]:
    params: dict[str, Any] = {"depth": 0}
    if country:
        params["country"] = country
    log.info("fetching /ix country=%s ...", country or "ALL")
    return _get("ix", params)


def fetch_ixfac(country: str | None = None) -> list[dict]:
    params: dict[str, Any] = {"depth": 0}
    if country:
        params["country"] = country
    log.info("fetching /ixfac country=%s ...", country or "ALL")
    return _get("ixfac", params)


async def upsert_facilities(conn: asyncpg.Connection, rows: list[dict]) -> int:
    sql = """
        INSERT INTO peering_facilities
            (pdb_id, name, org_id, org_name, city, country, region, address1,
             zipcode, clli, rencode, net_count, ix_count, status,
             latitude, longitude, geom, raw_data, updated_at)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
             $15::double precision, $16::double precision,
             CASE WHEN $15::double precision IS NOT NULL
                   AND $16::double precision IS NOT NULL
                  THEN ST_SetSRID(ST_MakePoint($16::double precision,
                                               $15::double precision), 4326)
                  ELSE NULL END,
             $17::jsonb, NOW())
        ON CONFLICT (pdb_id) DO UPDATE SET
            name = EXCLUDED.name,
            org_id = EXCLUDED.org_id,
            org_name = EXCLUDED.org_name,
            city = EXCLUDED.city,
            country = EXCLUDED.country,
            region = EXCLUDED.region,
            address1 = EXCLUDED.address1,
            zipcode = EXCLUDED.zipcode,
            clli = EXCLUDED.clli,
            rencode = EXCLUDED.rencode,
            net_count = EXCLUDED.net_count,
            ix_count = EXCLUDED.ix_count,
            status = EXCLUDED.status,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            geom = EXCLUDED.geom,
            raw_data = EXCLUDED.raw_data,
            updated_at = NOW();
    """
    n = 0
    for row in rows:
        try:
            await conn.execute(
                sql,
                row["id"],
                row.get("name"),
                row.get("org_id"),
                row.get("org_name"),
                row.get("city"),
                row.get("country"),
                row.get("region_continent"),
                row.get("address1"),
                row.get("zipcode"),
                row.get("clli"),
                row.get("rencode"),
                row.get("net_count") or 0,
                row.get("ix_count") or 0,
                row.get("status"),
                row.get("latitude"),
                row.get("longitude"),
                json.dumps(row),
            )
            n += 1
        except Exception as e:
            log.warning("upsert fac %s failed: %s", row.get("id"), e)
    return n


async def upsert_ixs(conn: asyncpg.Connection, rows: list[dict]) -> int:
    sql = """
        INSERT INTO peering_ixs
            (pdb_id, name, name_long, city, country, region, media,
             net_count, fac_count, status, website, raw_data, updated_at)
        VALUES
            ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, NOW())
        ON CONFLICT (pdb_id) DO UPDATE SET
            name = EXCLUDED.name,
            name_long = EXCLUDED.name_long,
            city = EXCLUDED.city,
            country = EXCLUDED.country,
            region = EXCLUDED.region,
            media = EXCLUDED.media,
            net_count = EXCLUDED.net_count,
            fac_count = EXCLUDED.fac_count,
            status = EXCLUDED.status,
            website = EXCLUDED.website,
            raw_data = EXCLUDED.raw_data,
            updated_at = NOW();
    """
    n = 0
    for row in rows:
        try:
            await conn.execute(
                sql,
                row["id"],
                row.get("name"),
                row.get("name_long"),
                row.get("city"),
                row.get("country"),
                row.get("region_continent"),
                row.get("media"),
                row.get("net_count") or 0,
                row.get("fac_count") or 0,
                row.get("status"),
                row.get("website"),
                json.dumps(row),
            )
            n += 1
        except Exception as e:
            log.warning("upsert ix %s failed: %s", row.get("id"), e)
    return n


async def upsert_ixfac(conn: asyncpg.Connection, rows: list[dict]) -> int:
    sql = """
        INSERT INTO peering_ixfac (pdb_id, ix_pdb_id, fac_pdb_id, status)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (pdb_id) DO UPDATE SET
            ix_pdb_id = EXCLUDED.ix_pdb_id,
            fac_pdb_id = EXCLUDED.fac_pdb_id,
            status = EXCLUDED.status;
    """
    n = 0
    for row in rows:
        try:
            await conn.execute(
                sql,
                row["id"],
                row.get("ix_id"),
                row.get("fac_id"),
                row.get("status"),
            )
            n += 1
        except Exception as e:
            log.warning("upsert ixfac %s failed: %s", row.get("id"), e)
    return n


async def ingest(countries: list[str] | None) -> dict:
    targets = countries or [None]
    total_fac = total_ix = total_link = 0
    conn = await asyncpg.connect(_db_url())
    try:
        for c in targets:
            fac = fetch_facilities(c)
            total_fac += await upsert_facilities(conn, fac)
            await asyncio.sleep(RATE_DELAY)

            ixs = fetch_ixs(c)
            total_ix += await upsert_ixs(conn, ixs)
            await asyncio.sleep(RATE_DELAY)

            links = fetch_ixfac(c)
            total_link += await upsert_ixfac(conn, links)
            await asyncio.sleep(RATE_DELAY)
    finally:
        await conn.close()
    return {"facilities": total_fac, "ixs": total_ix, "ixfac": total_link}


def _cli() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", nargs="*", default=["GB"],
                    help="ISO-2 country codes (default GB). Use --all for global.")
    ap.add_argument("--all", action="store_true", help="Ingest every country.")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    countries = None if args.all else args.country
    result = asyncio.run(ingest(countries))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _cli()

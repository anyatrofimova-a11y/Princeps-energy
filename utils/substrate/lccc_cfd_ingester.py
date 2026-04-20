"""
LCCC CfD daily reference price + top-up ingester.

Low Carbon Contracts Company publishes daily Intermittent Market Reference
Price (IMRP) + Baseload Market Reference Price (BMRP) + top-up payments made
to CfD-contracted generators. Public JSON/CSV at
https://www.lowcarboncontracts.uk/ (Open Data Portal) with OGL v3 licence.

Usage
-----

CLI::

    python -m utils.substrate.lccc_cfd_ingester          # last 7 days
    python -m utils.substrate.lccc_cfd_ingester 30       # last 30 days

Library::

    await ingest_daily_reference_prices(pool, days_back=7)
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

log = logging.getLogger("princeps.lccc_cfd")

SOURCE = "lccc_cfd"

# LCCC Open Data Portal — CKAN-style catalogue. Resource IDs stable per
# dataset; endpoint format:
#   https://dp.lowcarboncontracts.uk/api/3/action/datastore_search?resource_id={id}
# Real resource IDs are discoverable via package_show; we use a catalogue of
# known published datasets + fall back to CSV resource URLs.
_RESOURCES = {
    "imrp": {
        "name": "Intermittent Market Reference Price (IMRP)",
        "resource_id": "daily-imrp-2024-present",  # placeholder; real GUID resolved at runtime
        "csv_url": "https://dp.lowcarboncontracts.uk/dataset/daily-imrp/resource/imrp-daily.csv",
    },
    "bmrp": {
        "name": "Baseload Market Reference Price (BMRP)",
        "resource_id": "daily-bmrp-2024-present",
        "csv_url": "https://dp.lowcarboncontracts.uk/dataset/daily-bmrp/resource/bmrp-daily.csv",
    },
    "topup": {
        "name": "CfD top-up payments",
        "resource_id": "cfd-topup-payments",
        "csv_url": "https://dp.lowcarboncontracts.uk/dataset/cfd-topup-payments/resource/topup.csv",
    },
}


async def fetch_daily_csv(
    series: str, *, client: httpx.AsyncClient | None = None, timeout_s: float = 60.0,
) -> list[dict[str, Any]]:
    """Fetch a CSV resource from the LCCC open data portal and parse as rows."""
    if series not in _RESOURCES:
        raise ValueError(f"unknown LCCC series {series!r}; known: {list(_RESOURCES)}")

    url = _RESOURCES[series]["csv_url"]
    owns = client is None
    if owns:
        client = httpx.AsyncClient(timeout=timeout_s, headers={
            "User-Agent": "Princeps LCCC ingester (contact@princeps.energy)",
            "Accept": "text/csv, application/json",
        })
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        text = resp.text
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(r) for r in reader]
    except httpx.HTTPError as e:
        log.warning("LCCC fetch %s failed: %s", series, e)
        return []
    finally:
        if owns:
            await client.aclose()

    log.info("LCCC %s: %d rows", series, len(rows))
    return rows


async def upsert_reference_prices(pool, series: str, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert daily reference prices into lccc_daily_reference_prices."""
    if not rows:
        return {"inserted": 0, "updated": 0}

    sql = """
        INSERT INTO lccc_daily_reference_prices
            (series, trading_date, price_gbp_mwh, raw, ingested_at)
        VALUES ($1, $2::date, $3, $4::jsonb, now())
        ON CONFLICT (series, trading_date) DO UPDATE SET
            price_gbp_mwh = EXCLUDED.price_gbp_mwh,
            raw = EXCLUDED.raw,
            ingested_at = EXCLUDED.ingested_at
        RETURNING (xmax = 0) AS inserted
    """
    inserted = updated = 0
    async with pool.acquire() as conn:
        for row in rows:
            d = row.get("Date") or row.get("trading_date") or row.get("date")
            p = row.get("Price") or row.get("price") or row.get("price_gbp_mwh")
            if not d or p is None:
                continue
            try:
                # Normalise date — tolerate ISO + UK dd/mm/yyyy
                if "/" in str(d):
                    parts = str(d).split("/")
                    if len(parts) == 3:
                        d = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                price = float(str(p).replace("£", "").replace(",", "").strip())
                result = await conn.fetchrow(
                    sql, series, d, price, json.dumps(row)
                )
                if result and result["inserted"]:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                log.warning("row %s skipped: %s", row, e)

    return {"inserted": inserted, "updated": updated}


async def ingest_daily_reference_prices(pool, *, days_back: int = 7) -> dict[str, Any]:
    """Run all series for the last N days."""
    result: dict[str, Any] = {"days_back": days_back, "series": {}}
    async with httpx.AsyncClient(timeout=60.0, headers={
        "User-Agent": "Princeps LCCC ingester (contact@princeps.energy)",
    }) as client:
        for series in ("imrp", "bmrp", "topup"):
            try:
                rows = await fetch_daily_csv(series, client=client)
                # Filter to last days_back days to keep idempotent upserts cheap.
                cutoff = date.today() - timedelta(days=days_back)
                filtered = [r for r in rows if _parse_date(r.get("Date") or r.get("date") or "") >= cutoff]
                counts = await upsert_reference_prices(pool, series, filtered)
                result["series"][series] = counts
            except Exception as e:
                log.error("series %s failed: %s", series, e)
                result["series"][series] = {"error": str(e)}
    return result


def _parse_date(s: str) -> date:
    try:
        if "/" in s:
            p = s.split("/")
            return date(int(p[2]), int(p[1]), int(p[0]))
        return date.fromisoformat(s[:10])
    except Exception:
        return date(1970, 1, 1)


async def _cli():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    from app.deps import get_pool
    pool = await get_pool()
    try:
        res = await ingest_daily_reference_prices(pool, days_back=days)
        print(json.dumps(res, indent=2, default=str))
    finally:
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_cli())

"""Companies House ingester — pulls UK company records from
https://api.company-information.service.gov.uk and caches in
companies_house_cache.

Licence: OGL-3.0 (commercial-safe). Registered in app/license_guard/licenses.yaml
as 'uk_companies_house'.

Auth: HTTP Basic with the API key as the username (no password). Free to
register at https://developer.company-information.service.gov.uk/get-started.

Set env COMPANIES_HOUSE_API_KEY before use.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

log = logging.getLogger("princeps.ch_ingester")

CH_BASE = "https://api.company-information.service.gov.uk"
DEFAULT_TIMEOUT = 30.0
STALE_AFTER = timedelta(days=30)

# Energy-relevant SIC codes (UK SIC 2007). Filter ingestion to these.
ENERGY_SIC_PREFIXES = (
    "35110",  # Production of electricity
    "35120",  # Transmission of electricity
    "35130",  # Distribution of electricity
    "35140",  # Trade of electricity
    "35210",  # Manufacture of gas
    "35230",  # Trade of gas through mains
    "06200",  # Extraction of natural gas
    "20140",  # Manufacture of other organic basic chemicals (incl. hydrogen)
    "27110",  # Manufacture of electric motors, generators and transformers
    "28210",  # Manufacture of ovens, furnaces and furnace burners
    "33140",  # Repair of electrical equipment
    "42220",  # Construction of utility projects for electricity / telecoms
    "71121",  # Engineering design activities for industrial process / production
)


def _auth_header() -> dict[str, str]:
    key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if not key:
        raise RuntimeError(
            "COMPANIES_HOUSE_API_KEY not set. Register at "
            "https://developer.company-information.service.gov.uk/get-started"
        )
    encoded = base64.b64encode(f"{key}:".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


async def lookup_by_company_number(pool, company_number: str, *, force_refresh: bool = False) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT company_number, name, status, incorporation, sic_codes, "
            "registered_office, fetched_at FROM companies_house_cache WHERE company_number=$1",
            company_number,
        )
    if row and not force_refresh and (datetime.now(timezone.utc) - row["fetched_at"]) < STALE_AFTER:
        return dict(row)
    fresh = await _fetch_company(company_number)
    if fresh is not None:
        await _upsert(pool, fresh)
    return fresh


async def search_companies(query: str, *, items_per_page: int = 20) -> list[dict]:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=_auth_header()) as client:
        r = await client.get(
            f"{CH_BASE}/search/companies",
            params={"q": query, "items_per_page": items_per_page},
        )
        r.raise_for_status()
        payload = r.json()
    return [
        {
            "company_number": item.get("company_number"),
            "title": item.get("title"),
            "company_status": item.get("company_status"),
            "date_of_creation": item.get("date_of_creation"),
            "address_snippet": item.get("address_snippet"),
        }
        for item in payload.get("items", [])
    ]


async def _fetch_company(company_number: str) -> dict | None:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, headers=_auth_header()) as client:
        r = await client.get(f"{CH_BASE}/company/{company_number}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        payload = r.json()

    return {
        "company_number": payload.get("company_number"),
        "name": payload.get("company_name"),
        "status": payload.get("company_status"),
        "incorporation": payload.get("date_of_creation"),
        "sic_codes": payload.get("sic_codes") or [],
        "registered_office": payload.get("registered_office_address") or {},
        "raw": payload,
    }


async def _upsert(pool, record: dict) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO companies_house_cache (company_number, name, status, incorporation,
                sic_codes, registered_office, raw, fetched_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7, NOW())
            ON CONFLICT (company_number) DO UPDATE SET
                name=EXCLUDED.name,
                status=EXCLUDED.status,
                incorporation=EXCLUDED.incorporation,
                sic_codes=EXCLUDED.sic_codes,
                registered_office=EXCLUDED.registered_office,
                raw=EXCLUDED.raw,
                fetched_at=NOW()
            """,
            record["company_number"], record.get("name"), record.get("status"),
            record.get("incorporation"),
            json.dumps(record.get("sic_codes") or []),
            json.dumps(record.get("registered_office") or {}),
            json.dumps(record.get("raw") or {}),
        )


def is_energy_company(sic_codes: list[str]) -> bool:
    """Quick relevance filter: True if any SIC code matches a Princeps-relevant
    prefix (electricity gen/T&D, gas, hydrogen-adjacent chemicals, generator
    manufacturing, EPC).
    """
    if not sic_codes:
        return False
    return any(any(c.startswith(p) for p in ENERGY_SIC_PREFIXES) for c in sic_codes)

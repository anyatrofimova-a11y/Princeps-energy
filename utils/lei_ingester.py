"""GLEIF LEI ingester — pulls Legal Entity Identifier records from the GLEIF
public API (https://api.gleif.org/api/v1/lei-records) and caches them in
Postgres `gleif_lei_cache`.

Licence: CC0-1.0 (commercial-safe). Registered in app/license_guard/licenses.yaml
as 'gleif_lei'.

Strategy:
  • Search by legal name → LEI candidates.
  • Lookup by LEI → full record (parent + ultimate parent relationships).
  • Cache hit / miss policy: refresh records older than 30 days on read.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Iterable

import httpx

log = logging.getLogger("princeps.lei_ingester")

GLEIF_BASE = "https://api.gleif.org/api/v1"
DEFAULT_TIMEOUT = 30.0
STALE_AFTER = timedelta(days=30)


async def lookup_by_lei(pool, lei: str, *, force_refresh: bool = False) -> dict | None:
    """Return cached LEI record, refreshing from GLEIF if missing or stale."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT lei, legal_name, status, parent_lei, ultimate_lei, address, "
            "fetched_at FROM gleif_lei_cache WHERE lei=$1", lei,
        )
    if row and not force_refresh and (datetime.now(timezone.utc) - row["fetched_at"]) < STALE_AFTER:
        return dict(row)
    fresh = await _fetch_lei_from_gleif(lei)
    if fresh is not None:
        await _upsert(pool, fresh)
    return fresh


async def search_by_name(name: str, *, limit: int = 10) -> list[dict]:
    """GLEIF fulltext search on legal name. Returns [{lei, legal_name, jurisdiction}]."""
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(
            f"{GLEIF_BASE}/lei-records",
            params={"filter[entity.legalName]": name, "page[size]": limit},
        )
        r.raise_for_status()
        payload = r.json()
    out = []
    for item in payload.get("data", []):
        attrs = item.get("attributes", {})
        out.append({
            "lei": item.get("id"),
            "legal_name": (attrs.get("entity") or {}).get("legalName", {}).get("name"),
            "jurisdiction": (attrs.get("entity") or {}).get("jurisdiction"),
            "status": (attrs.get("entity") or {}).get("status"),
        })
    return out


async def _fetch_lei_from_gleif(lei: str) -> dict | None:
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        r = await client.get(f"{GLEIF_BASE}/lei-records/{lei}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        payload = r.json()

    attrs = payload.get("data", {}).get("attributes", {})
    entity = attrs.get("entity", {}) or {}
    rels = payload.get("data", {}).get("relationships", {}) or {}
    parent_id = (((rels.get("direct-parent") or {}).get("data") or {}) or {}).get("id")
    ultimate_id = (((rels.get("ultimate-parent") or {}).get("data") or {}) or {}).get("id")

    return {
        "lei": payload["data"]["id"],
        "legal_name": (entity.get("legalName") or {}).get("name"),
        "legal_form_code": ((entity.get("legalForm") or {}).get("id")),
        "jurisdiction": entity.get("jurisdiction"),
        "status": entity.get("status"),
        "parent_lei": parent_id,
        "ultimate_lei": ultimate_id,
        "address": entity.get("legalAddress") or {},
        "raw": payload,
    }


async def _upsert(pool, record: dict) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO gleif_lei_cache (lei, legal_name, legal_form_code, jurisdiction,
                status, parent_lei, ultimate_lei, address, raw, fetched_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9, NOW())
            ON CONFLICT (lei) DO UPDATE SET
                legal_name=EXCLUDED.legal_name,
                legal_form_code=EXCLUDED.legal_form_code,
                jurisdiction=EXCLUDED.jurisdiction,
                status=EXCLUDED.status,
                parent_lei=EXCLUDED.parent_lei,
                ultimate_lei=EXCLUDED.ultimate_lei,
                address=EXCLUDED.address,
                raw=EXCLUDED.raw,
                fetched_at=NOW()
            """,
            record["lei"], record["legal_name"], record.get("legal_form_code"),
            record.get("jurisdiction"), record.get("status"),
            record.get("parent_lei"), record.get("ultimate_lei"),
            json.dumps(record.get("address") or {}),
            json.dumps(record.get("raw") or {}),
        )


async def crawl_corporate_tree(pool, root_lei: str, *, max_hops: int = 4) -> list[dict]:
    """BFS up the parent chain (and one hop down to children) from a starting
    LEI. Useful for resolving "who actually owns this developer".
    """
    seen, frontier, results = set(), [root_lei], []
    hops = 0
    while frontier and hops < max_hops:
        next_frontier = []
        for lei in frontier:
            if lei in seen:
                continue
            seen.add(lei)
            rec = await lookup_by_lei(pool, lei)
            if not rec:
                continue
            results.append(rec)
            for parent_field in ("parent_lei", "ultimate_lei"):
                p = rec.get(parent_field)
                if p and p not in seen:
                    next_frontier.append(p)
        frontier = next_frontier
        hops += 1
    return results

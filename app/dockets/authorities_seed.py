"""
app/dockets/authorities_seed.py — idempotent seed of the UK authorities registry.

Loads ``app/dockets/data/authorities_seed.json`` and upserts each row into
``authorities``. Slugs are the stable key; downstream rules
(``consultee_requirements``) resolve authority FKs via slug lookup so they
survive re-seeds.

Called from ``app/startup.py`` when ``PRINCEPS_SEED_AUTHORITIES=true``.

TODO — expand LPA coverage to the full 317/32/22/11 set by pulling the
ONS LAD24CD/LAD24NM register. The current JSON has the most docket-active
councils; the resolver and consultee rules degrade gracefully for unknown
LPAs (they still surface via the geometry intersection layer).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import asyncpg

log = logging.getLogger("princeps.dockets.authorities_seed")

_SEED_PATH = Path(__file__).resolve().parent / "data" / "authorities_seed.json"


def _load_seed_rows() -> list[dict[str, Any]]:
    """Read the JSON fixture. Returns [] on any error (log and continue)."""
    try:
        payload = json.loads(_SEED_PATH.read_text())
    except FileNotFoundError:
        log.warning("authorities_seed.json not found at %s — skipping", _SEED_PATH)
        return []
    except json.JSONDecodeError as exc:
        log.error("authorities_seed.json is invalid JSON: %s", exc)
        return []
    rows = payload.get("authorities") or []
    if not isinstance(rows, list):
        log.error("authorities_seed.json 'authorities' key is not a list")
        return []
    return rows


async def seed_authorities(pool: asyncpg.Pool) -> int:
    """Idempotently seed / refresh the authorities registry.

    Returns the number of rows upserted (insert + update).
    """
    rows = _load_seed_rows()
    if not rows:
        return 0

    # Pre-check: is the table there? Migration 0001 creates it; we don't
    # want to explode if the migration hasn't landed yet on a cold DB.
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.authorities') IS NOT NULL"
        )
        if not exists:
            log.info("seed_authorities: authorities table missing — skipping")
            return 0

        upserted = 0
        for r in rows:
            slug = r.get("slug")
            if not slug:
                continue
            try:
                await conn.execute(
                    """
                    INSERT INTO authorities
                        (slug, name, acronym, type, jurisdiction,
                         home_url, logo_url, api_available)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (slug) DO UPDATE SET
                        name          = EXCLUDED.name,
                        acronym       = EXCLUDED.acronym,
                        type          = EXCLUDED.type,
                        jurisdiction  = EXCLUDED.jurisdiction,
                        home_url      = COALESCE(EXCLUDED.home_url,   authorities.home_url),
                        logo_url      = COALESCE(EXCLUDED.logo_url,   authorities.logo_url),
                        api_available = EXCLUDED.api_available
                    """,
                    slug,
                    r.get("name", slug),
                    r.get("acronym"),
                    r.get("type", "authority"),
                    r.get("jurisdiction", "UK"),
                    r.get("home_url"),
                    r.get("logo_url"),
                    bool(r.get("api_available", False)),
                )
                upserted += 1
            except Exception as exc:
                log.warning("seed_authorities: failed for slug=%s: %s", slug, exc)
                continue

    log.info("seed_authorities: upserted %d / %d rows", upserted, len(rows))
    return upserted


async def resolve_authority_id(
    conn: asyncpg.Connection, slug: str
) -> str | None:
    """Helper for other seeds / resolvers. Returns the authority UUID for a
    slug, or None if not seeded yet."""
    row = await conn.fetchrow(
        "SELECT id FROM authorities WHERE slug = $1", slug
    )
    return str(row["id"]) if row else None


__all__ = ["seed_authorities", "resolve_authority_id"]

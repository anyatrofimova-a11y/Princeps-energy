"""Seed the `uk-n1-contingency-map` row in `data_subscriptions`.

The Princeps Datasets registry uses the `data_subscriptions` table as the
source of truth for paid / public data products. This module upserts one
row describing the UK N-1 Contingency Map and is idempotent — safe to call
repeatedly on startup.

Price: Enterprise-only at £15,000 / month. Refresh: quarterly for
subscribers (weekly internally for freshness, but most users don't need
sub-weekly resolution and the compute cost is non-trivial).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

log = logging.getLogger("princeps.seed.n1_datasets")


N1_SUBSCRIPTION = {
    "slug": "uk-n1-contingency-map",
    "title": "UK N-1 Contingency Map",
    "description": (
        "Pre-computed N-1 outage impact for every primary substation in GB. "
        "For each primary we enumerate every credible upstream line / "
        "transformer outage, flag downstream feeders that would exceed 100% "
        "thermal rating, estimate BSC P2/7 restoration time (15 min urban / "
        "60 min rural), and return a 0-100 reliability score. Published as "
        "GeoJSON + per-substation JSON via /api/n1/*."
    ),
    # Refresh: 90 days = quarterly for subscribers. Internally the batch
    # runner executes weekly (≈168 h), but from a subscription-contract POV
    # we commit to quarterly freshness.
    "refresh_interval_hours": 90 * 24,
    "is_public": False,
    "price_tier": "enterprise",
    "schema": {
        "endpoints": {
            "record": "GET /api/n1/substation/{id}",
            "map": "GET /api/n1/map?bbox=&score_lt=&voltage_kv=&dno=",
            "ranked": "GET /api/n1/worst-cases?limit=50&voltage_kv=&dno=",
            "recompute": "POST /api/n1/rerun/{substation_id}  (admin only)",
        },
        "fields": [
            "substation_id (uuid)",
            "substation_name",
            "voltage_kv",
            "dno",
            "worst_case_overload_pct",
            "worst_case_affected_mw",
            "reliability_score_0_100",
            "n1_outage_events[]",
            "upstream_assets_scanned",
            "failed_outages",
            "last_computed_at",
            "model_version",
        ],
        "pricing": {
            "tier": "enterprise",
            "monthly_gbp": 15000,
            "contract_min_months": 12,
        },
        "refresh_cadence": "quarterly",
        "internal_build_cadence": "weekly",
        "coverage": "GB primary substations (11 kV, 33 kV, 66 kV, 132 kV)",
        "model_version": "v1.0.0",
    },
}


async def _do_upsert(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        INSERT INTO data_subscriptions
            (slug, title, description, refresh_interval_hours,
             is_public, price_tier, schema)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        ON CONFLICT (slug) DO UPDATE SET
            title                  = EXCLUDED.title,
            description            = EXCLUDED.description,
            refresh_interval_hours = EXCLUDED.refresh_interval_hours,
            is_public              = EXCLUDED.is_public,
            price_tier             = EXCLUDED.price_tier,
            schema                 = EXCLUDED.schema,
            updated_at             = now()
        """,
        N1_SUBSCRIPTION["slug"],
        N1_SUBSCRIPTION["title"],
        N1_SUBSCRIPTION["description"],
        N1_SUBSCRIPTION["refresh_interval_hours"],
        N1_SUBSCRIPTION["is_public"],
        N1_SUBSCRIPTION["price_tier"],
        json.dumps(N1_SUBSCRIPTION["schema"]),
    )


async def seed(conn_or_pool: Any) -> None:
    """Upsert the N-1 dataset row into `data_subscriptions`.

    Accepts either an asyncpg.Connection (matches `db_setup.py` convention)
    or an asyncpg.Pool (matches the common seed-call pattern elsewhere).
    """
    # Pool-vs-connection duck-typing
    if hasattr(conn_or_pool, "acquire"):
        async with conn_or_pool.acquire() as conn:
            await _do_upsert(conn)
    else:
        await _do_upsert(conn_or_pool)
    log.info("Seeded data_subscriptions row '%s'", N1_SUBSCRIPTION["slug"])


async def seed_if_table_present(conn_or_pool: Any) -> None:
    """Safe wrapper — skips if `data_subscriptions` hasn't been created yet
    (e.g. 0001_intelligence_schema.sql failed on a partial install)."""

    async def _check(conn: asyncpg.Connection) -> bool:
        return bool(await conn.fetchval(
            "SELECT to_regclass('public.data_subscriptions') IS NOT NULL"
        ))

    if hasattr(conn_or_pool, "acquire"):
        async with conn_or_pool.acquire() as conn:
            if not await _check(conn):
                log.warning(
                    "data_subscriptions table missing — skipping N-1 dataset seed"
                )
                return
            await _do_upsert(conn)
    else:
        if not await _check(conn_or_pool):
            log.warning(
                "data_subscriptions table missing — skipping N-1 dataset seed"
            )
            return
        await _do_upsert(conn_or_pool)
    log.info("Seeded data_subscriptions row '%s' (if-present path)", N1_SUBSCRIPTION["slug"])

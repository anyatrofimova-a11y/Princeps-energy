"""``/api/datasets`` — Magritte dataset catalogue REST surface.

Endpoints
---------

  GET  /api/datasets
       List every registered dataset with its current health pill.

  GET  /api/datasets/{slug}
       Detail for one dataset, including the last 10 refresh-log rows.

  POST /api/datasets/{slug}/refresh
       Trigger Connector.ingest() in the background. Returns the
       refresh-log row id so callers can poll for completion.

  GET  /api/datasets/{slug}/health
       Recompute health on demand (live count(*) + persist).

  GET  /api/datasets/{slug}/lineage
       Walk dataset_lineage upstream + downstream from this dataset.

Lives separately from ``app/routers/connectors.py`` (which serves the
legacy ``connectors_registry`` table). Both can coexist — different URL
prefixes, different backing tables.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.connectors import registry as connector_registry
from app.connectors.health import compute_health, update_health
from app.deps import get_pool

log = logging.getLogger("princeps.datasets")

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


async def _trigger_ingest(pool: asyncpg.Pool, slug: str, request: Request) -> None:
    """Background-task wrapper around Connector.ingest()."""
    cls = connector_registry.get(slug)
    if cls is None:
        log.warning("background refresh: connector %r vanished", slug)
        return
    try:
        await cls().ingest(pool, request=request)
    except Exception as exc:
        # ingest() already records the failure into princeps_datasets +
        # dataset_refresh_log. We just log here so the task doesn't die
        # silently.
        log.warning("background refresh slug=%s failed: %s", slug, exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def list_datasets(pool: asyncpg.Pool = Depends(get_pool)) -> dict[str, Any]:
    """List all datasets registered in ``princeps_datasets``.

    Order is registration-time newest first (``created_at DESC``) so the
    UI surfaces the most recently added connectors at the top.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT slug, title, source_url, license, refresh_cadence,
                   table_name, last_refreshed_at, last_refresh_ok,
                   last_refresh_error, last_row_count,
                   freshness_threshold_hours, health_status,
                   health_checked_at, created_at, updated_at
            FROM princeps_datasets
            ORDER BY created_at DESC
            """
        )
    datasets = [_row_to_dict(r) for r in rows]
    # Annotate each row with whether it's currently runnable (i.e. has a
    # connector class registered) so the UI can grey out the refresh
    # button for catalogue rows that no longer have code behind them.
    runnable = {cls.slug for cls in connector_registry.all_connectors()}
    for d in datasets:
        d["runnable"] = d["slug"] in runnable
    return {"datasets": datasets, "count": len(datasets)}


@router.get("/{slug}")
async def dataset_detail(
    slug: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Full record for one dataset, including the last 10 refresh runs."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM princeps_datasets WHERE slug = $1", slug,
        )
        if row is None:
            raise HTTPException(404, f"dataset {slug!r} not found")
        log_rows = await conn.fetch(
            """
            SELECT id, started_at, completed_at, ok,
                   rows_ingested, rows_total, error, duration_ms
            FROM dataset_refresh_log
            WHERE slug = $1
            ORDER BY started_at DESC
            LIMIT 10
            """,
            slug,
        )
    return {
        "dataset": _row_to_dict(row),
        "recent_runs": [_row_to_dict(r) for r in log_rows],
        "runnable": connector_registry.get(slug) is not None,
    }


@router.post("/{slug}/refresh")
async def refresh_dataset(
    slug: str,
    background: BackgroundTasks,
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Trigger an ingest in the background.

    Returns the refresh-log row id so the UI can poll
    ``/api/datasets/{slug}`` for the new row to appear in
    ``recent_runs``.
    """
    cls = connector_registry.get(slug)
    if cls is None:
        # Allow refresh on registered-but-no-class datasets only by failing
        # loudly — those are catalogue-only entries (e.g. manual SQL load).
        raise HTTPException(
            404, f"no connector class registered for slug {slug!r}",
        )

    # Sanity-check the dataset is in the registry before kicking off the
    # background task; this also returns the upcoming log_id stably.
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM princeps_datasets WHERE slug = $1", slug,
        )
    if not exists:
        raise HTTPException(
            404,
            f"dataset {slug!r} not in princeps_datasets — restart so "
            f"register_all_connectors() can run, or call register() manually",
        )

    background.add_task(_trigger_ingest, pool, slug, request)
    return {"started": True, "slug": slug}


@router.get("/{slug}/health")
async def dataset_health(
    slug: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Recompute health for a dataset (live ``count(*)`` + persist)."""
    # update_health both computes and writes the new status back into
    # princeps_datasets.health_status / health_checked_at.
    hc = await update_health(pool, slug)
    return {"slug": slug, **hc.to_json()}


@router.get("/{slug}/lineage")
async def dataset_lineage(
    slug: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """One-hop lineage walk — upstream + downstream of this dataset.

    A deeper recursive walk is overkill for the MVP; the UI renders one
    hop in either direction and lets the user click through to follow
    the chain.
    """
    async with pool.acquire() as conn:
        upstream = await conn.fetch(
            """
            SELECT l.upstream_slug AS slug, l.relationship,
                   d.title, d.health_status
            FROM dataset_lineage l
            LEFT JOIN princeps_datasets d ON d.slug = l.upstream_slug
            WHERE l.downstream_slug = $1
            ORDER BY l.upstream_slug
            """,
            slug,
        )
        downstream = await conn.fetch(
            """
            SELECT l.downstream_slug AS slug, l.relationship,
                   d.title, d.health_status
            FROM dataset_lineage l
            LEFT JOIN princeps_datasets d ON d.slug = l.downstream_slug
            WHERE l.upstream_slug = $1
            ORDER BY l.downstream_slug
            """,
            slug,
        )
    return {
        "slug": slug,
        "upstream": [_row_to_dict(r) for r in upstream],
        "downstream": [_row_to_dict(r) for r in downstream],
    }


__all__ = ["router"]

"""
scripts/refresh_planning_data_uk.py — daily bulk refresh job (Task #17).

For each slug in TOP21 (excluding the bulk-blocklisted
``flood-risk-zone``):

  1. HEAD ``files.planning.data.gov.uk/dataset/<slug>.geojson`` for ETag /
     Last-Modified.
  2. Compare against the value stored in ``planning_designations_etag``.
  3. On miss → conditional GET, stream-parse the GeoJSON FeatureCollection,
     reproject 4326 -> 27700, UPSERT into ``planning_designations`` in
     batches of 1000.

The script is safe to run manually (CLI) or from the APScheduler job
in app/startup.py:
    python -m scripts.refresh_planning_data_uk
    python -m scripts.refresh_planning_data_uk --slug listed-building
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, AsyncIterator

import asyncpg
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.planning_data_uk import (
    BULK,
    BULK_BLOCKLIST,
    SEVERITY,
    TOP21,
    USER_AGENT,
    ensure_schema,
    record_etag,
    stored_etag,
    upsert_designation_rows,
)

log = logging.getLogger("princeps.refresh_planning_data_uk")

BATCH_SIZE = 1000
STREAM_TIMEOUT = 600.0  # some files are >100 MB


def _db_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://anyatrofimova@localhost:5432/feasibly",
    )


def _iter_features(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract feature list from a parsed GeoJSON FeatureCollection."""
    if not isinstance(payload, dict):
        return []
    if payload.get("type") == "FeatureCollection":
        return list(payload.get("features") or [])
    if payload.get("type") == "Feature":
        return [payload]
    return []


async def _head(client: httpx.AsyncClient, url: str) -> tuple[str | None, str | None, int]:
    try:
        r = await client.head(url, follow_redirects=True)
        return (
            r.headers.get("ETag"),
            r.headers.get("Last-Modified"),
            r.status_code,
        )
    except Exception as exc:
        log.warning("HEAD %s failed: %s", url, exc)
        return (None, None, 0)


def _row_from_feature(slug: str, feat: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a raw GeoJSON feature into the UPSERT row shape."""
    props = feat.get("properties") or {}
    geom = feat.get("geometry")
    if not geom:
        return None
    entity = props.get("entity") or props.get("entity_id")
    if entity is None:
        return None
    try:
        entity = int(entity)
    except (TypeError, ValueError):
        return None
    src = f"https://www.planning.data.gov.uk/entity/{entity}"
    return {
        "entity_id": entity,
        "dataset": slug,
        "reference": props.get("reference"),
        "name": props.get("name"),
        "organisation_entity": str(props.get("organisation-entity"))
            if props.get("organisation-entity") is not None else None,
        "quality": props.get("quality") or props.get("data-quality"),
        "entry_date": props.get("entry-date") or props.get("entry_date"),
        "start_date": props.get("start-date") or props.get("start_date"),
        "end_date": props.get("end-date") or props.get("end_date"),
        "attrs": {k: v for k, v in props.items() if v is not None},
        "geom_geojson": geom,
        "source_url": src,
    }


async def refresh_slug(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    slug: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Refresh one dataset slug. Returns a per-slug status dict."""
    summary: dict[str, Any] = {"slug": slug}

    if slug in BULK_BLOCKLIST:
        summary["status"] = "skipped_bulk_blocklist"
        log.info("[%s] in bulk blocklist — skipping (use API only)", slug)
        return summary

    url = f"{BULK}/{slug}.geojson"
    new_etag, new_lm, head_code = await _head(client, url)
    summary["etag"] = new_etag
    summary["last_modified"] = new_lm
    summary["head_status"] = head_code

    async with pool.acquire() as conn:
        prev_etag, prev_lm = await stored_etag(conn, slug)

    if not force and new_etag and prev_etag == new_etag:
        summary["status"] = "unchanged"
        log.info("[%s] ETag unchanged — skipping", slug)
        return summary

    headers = {
        "Accept": "application/geo+json",
        "User-Agent": USER_AGENT,
    }
    if prev_etag and not force:
        headers["If-None-Match"] = prev_etag

    try:
        r = await client.get(url, headers=headers, timeout=STREAM_TIMEOUT)
    except Exception as exc:
        log.warning("[%s] GET failed: %s", slug, exc)
        async with pool.acquire() as conn:
            await record_etag(
                conn, slug,
                etag=new_etag, last_modified=new_lm,
                rows_loaded=0, status=f"error:{exc.__class__.__name__}",
            )
        summary["status"] = "fetch_error"
        summary["error"] = str(exc)
        return summary

    if r.status_code == 304:
        summary["status"] = "not_modified"
        log.info("[%s] 304 not modified", slug)
        async with pool.acquire() as conn:
            await record_etag(
                conn, slug,
                etag=new_etag, last_modified=new_lm,
                rows_loaded=0, status="not_modified",
            )
        return summary

    if r.status_code != 200:
        summary["status"] = f"http_{r.status_code}"
        log.warning("[%s] HTTP %s", slug, r.status_code)
        return summary

    try:
        payload = r.json()
    except Exception as exc:
        summary["status"] = "json_decode_error"
        summary["error"] = str(exc)
        log.warning("[%s] JSON decode failed: %s", slug, exc)
        return summary

    feats = _iter_features(payload)
    summary["feature_count"] = len(feats)
    log.info("[%s] %d features fetched", slug, len(feats))

    rows: list[dict[str, Any]] = []
    written = 0
    for feat in feats:
        row = _row_from_feature(slug, feat)
        if row is None:
            continue
        rows.append(row)
        if len(rows) >= BATCH_SIZE:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    written += await upsert_designation_rows(conn, rows)
            rows = []
    if rows:
        async with pool.acquire() as conn:
            async with conn.transaction():
                written += await upsert_designation_rows(conn, rows)

    summary["rows_written"] = written
    summary["status"] = "ok"

    async with pool.acquire() as conn:
        await record_etag(
            conn, slug,
            etag=new_etag, last_modified=new_lm,
            rows_loaded=written, status="ok",
        )
    log.info("[%s] upsert complete: %d rows", slug, written)
    return summary


async def refresh_all(
    pool: asyncpg.Pool,
    slugs: list[str] | None = None,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Refresh every slug in TOP21 (minus blocklist) sequentially."""
    await ensure_schema(pool)
    slugs = slugs or [s for s in TOP21 if s not in BULK_BLOCKLIST]
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=STREAM_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        for slug in slugs:
            try:
                summary = await refresh_slug(pool, client, slug, force=force)
            except Exception as exc:
                log.exception("[%s] refresh failed: %s", slug, exc)
                summary = {"slug": slug, "status": "exception", "error": str(exc)}
            results.append(summary)
    return results


async def _cli_main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    pool = await asyncpg.create_pool(
        _db_url(), min_size=1, max_size=4, command_timeout=120,
        statement_cache_size=0,  # Supabase pooler (pgbouncer transaction mode) requires this
    )
    try:
        slugs = [args.slug] if args.slug else None
        summary = await refresh_all(pool, slugs=slugs, force=args.force)
    finally:
        await pool.close()
    print(json.dumps(summary, indent=2, default=str))
    return 0


def _cli() -> None:
    ap = argparse.ArgumentParser(
        description="Refresh planning.data.gov.uk Top-21 datasets (OGL v3.0)."
    )
    ap.add_argument("--slug", type=str, help="Refresh a single slug")
    ap.add_argument("--force", action="store_true", help="Skip ETag short-circuit")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_cli_main(args)))


if __name__ == "__main__":
    _cli()

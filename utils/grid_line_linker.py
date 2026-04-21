"""
grid_line_linker.py — Post-ingest spatial linker for grid_lines endpoints.

Many of the 1.6M+ rows in ``grid_lines`` land in the table with NULL
``from_sub_id`` / ``to_sub_id`` because the OSM power-line ingesters don't
carry explicit substation references — they only ship geometry.

This module does a spatial snap: for each line's StartPoint / EndPoint,
find the nearest substation in ``grid_substations`` within a threshold
(default 100m) and write the FK. Lines whose endpoints don't fall near any
substation stay NULL (so subsequent re-runs pick them up if the substation
catalog fills in later).

Entry points
------------
- ``link_grid_lines(conn, *, max_distance_m=100, dry_run=False, batch_size=5000)``
- CLI: ``python -m utils.grid_line_linker --max-distance-m 100 [--dry-run]``
- FastAPI startup hook (gated on ``PRINCEPS_LINK_GRID_LINES_ON_STARTUP=true``)

Strategy
--------
The heavy lift is a single SQL UPDATE that runs per batch. We look up the
nearest neighbour with an ``ORDER BY geom <-> point LIMIT 1`` subquery
guarded by an ``ST_DWithin`` filter so the GIST index kicks in. The
``ST_DWithin`` threshold is ``max_distance_m`` (SRID 27700 is metric —
1 unit = 1 metre).

We only touch rows where at least one of the endpoint IDs is NULL. Updates
are idempotent — re-running does no work once every line is either linked
or confirmed unlinkable.

Counts returned
---------------
``linked_from`` — rows where from_sub_id was set this run
``linked_to``   — rows where to_sub_id was set this run
``both``        — rows where both ends were linked in the same pass
``unlinked``    — rows where neither end matched any substation (leftover NULLs)
``total_processed`` — rows visited (NULL-at-least-one-end candidates)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

import asyncpg

log = logging.getLogger("princeps.grid_line_linker")

DEFAULT_MAX_DISTANCE_M = 100
DEFAULT_BATCH_SIZE = 5000


async def _count_candidates(conn: asyncpg.Connection) -> int:
    """How many rows still need at least one endpoint linked?"""
    return await conn.fetchval(
        """
        SELECT count(*) FROM grid_lines
        WHERE geom IS NOT NULL
          AND (from_sub_id IS NULL OR to_sub_id IS NULL)
        """
    ) or 0


async def _probe_batch(
    conn: asyncpg.Connection,
    *,
    max_distance_m: float,
    sample: int,
) -> dict[str, int]:
    """Run the nearest-neighbour query without writing.

    Used by ``dry_run`` and the POST route's immediate probe response so we
    can give an instant estimate before the background task finishes.
    """
    row = await conn.fetchrow(
        """
        WITH sample AS (
            SELECT id, geom
            FROM grid_lines
            WHERE geom IS NOT NULL
              AND (from_sub_id IS NULL OR to_sub_id IS NULL)
            LIMIT $2
        ),
        probe AS (
            SELECT
                s.id,
                (
                    SELECT gs.id FROM grid_substations gs
                    WHERE gs.geom IS NOT NULL
                      AND ST_DWithin(gs.geom, ST_StartPoint(s.geom), $1)
                    ORDER BY gs.geom <-> ST_StartPoint(s.geom)
                    LIMIT 1
                ) AS from_id,
                (
                    SELECT gs.id FROM grid_substations gs
                    WHERE gs.geom IS NOT NULL
                      AND ST_DWithin(gs.geom, ST_EndPoint(s.geom), $1)
                    ORDER BY gs.geom <-> ST_EndPoint(s.geom)
                    LIMIT 1
                ) AS to_id
            FROM sample s
        )
        SELECT
            count(*)                                            AS seen,
            count(from_id)                                      AS hit_from,
            count(to_id)                                        AS hit_to,
            count(CASE WHEN from_id IS NOT NULL AND to_id IS NOT NULL THEN 1 END) AS hit_both,
            count(CASE WHEN from_id IS NULL AND to_id IS NULL THEN 1 END)         AS miss_both
        FROM probe
        """,
        max_distance_m,
        sample,
    )
    return {
        "sampled": row["seen"] or 0,
        "linked_from": row["hit_from"] or 0,
        "linked_to": row["hit_to"] or 0,
        "both": row["hit_both"] or 0,
        "unlinked": row["miss_both"] or 0,
    }


async def _link_batch(
    conn: asyncpg.Connection,
    *,
    max_distance_m: float,
    batch_size: int,
) -> dict[str, int]:
    """Process one batch: find candidates, pick nearest subs, UPDATE in one shot.

    Returns per-batch tallies. An empty-result dict with ``seen=0`` signals
    the caller to stop looping.
    """
    # Pull a batch of candidate IDs first, then do the nearest-neighbour
    # work in a single UPDATE bounded by that set. This lets us report
    # clean per-batch counts and keeps the WHERE/INDEX scan predictable.
    ids = [
        r["id"]
        for r in await conn.fetch(
            """
            SELECT id FROM grid_lines
            WHERE geom IS NOT NULL
              AND (from_sub_id IS NULL OR to_sub_id IS NULL)
            ORDER BY id
            LIMIT $1
            """,
            batch_size,
        )
    ]
    if not ids:
        return {
            "seen": 0, "linked_from": 0, "linked_to": 0,
            "both": 0, "unlinked": 0,
        }

    result = await conn.fetch(
        """
        WITH batch AS (
            SELECT id, geom, from_sub_id, to_sub_id
            FROM grid_lines
            WHERE id = ANY($2::int[])
        ),
        resolved AS (
            SELECT
                b.id,
                b.from_sub_id AS old_from,
                b.to_sub_id   AS old_to,
                CASE WHEN b.from_sub_id IS NULL THEN (
                    SELECT gs.id FROM grid_substations gs
                    WHERE gs.geom IS NOT NULL
                      AND ST_DWithin(gs.geom, ST_StartPoint(b.geom), $1)
                    ORDER BY gs.geom <-> ST_StartPoint(b.geom)
                    LIMIT 1
                ) ELSE b.from_sub_id END AS new_from,
                CASE WHEN b.to_sub_id IS NULL THEN (
                    SELECT gs.id FROM grid_substations gs
                    WHERE gs.geom IS NOT NULL
                      AND ST_DWithin(gs.geom, ST_EndPoint(b.geom), $1)
                    ORDER BY gs.geom <-> ST_EndPoint(b.geom)
                    LIMIT 1
                ) ELSE b.to_sub_id END AS new_to
            FROM batch b
        ),
        updated AS (
            UPDATE grid_lines gl
            SET from_sub_id = r.new_from,
                to_sub_id   = r.new_to
            FROM resolved r
            WHERE gl.id = r.id
              AND (
                  (gl.from_sub_id IS DISTINCT FROM r.new_from)
                  OR (gl.to_sub_id IS DISTINCT FROM r.new_to)
              )
            RETURNING r.id, r.old_from, r.old_to, r.new_from, r.new_to
        )
        SELECT
            count(*) FILTER (WHERE old_from IS NULL AND new_from IS NOT NULL) AS linked_from,
            count(*) FILTER (WHERE old_to   IS NULL AND new_to   IS NOT NULL) AS linked_to,
            count(*) FILTER (WHERE old_from IS NULL AND new_from IS NOT NULL
                             AND old_to   IS NULL AND new_to   IS NOT NULL) AS both,
            count(*) FILTER (WHERE (old_from IS NULL AND new_from IS NULL)
                             OR (old_to IS NULL AND new_to IS NULL)) AS partial_or_miss
        FROM updated
        """,
        max_distance_m,
        ids,
    )
    row = result[0] if result else None
    return {
        "seen": len(ids),
        "linked_from": (row["linked_from"] if row else 0) or 0,
        "linked_to": (row["linked_to"] if row else 0) or 0,
        "both": (row["both"] if row else 0) or 0,
        "unlinked": 0,  # filled post-hoc: candidates - linked_from - linked_to double-count risk
    }


async def link_grid_lines(
    conn_or_pool: asyncpg.Connection | asyncpg.Pool,
    *,
    max_distance_m: float = DEFAULT_MAX_DISTANCE_M,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rows: int | None = None,
    progress_every: int = 10,
) -> dict[str, Any]:
    """Snap line endpoints to the nearest substation.

    Accepts either a live ``asyncpg.Connection`` or a ``Pool`` — for CLI /
    background-task callers that hold a pool, we acquire on their behalf.

    Parameters
    ----------
    max_distance_m : float
        Threshold for the nearest-neighbour snap. Endpoints outside this
        distance leave ``from_sub_id`` / ``to_sub_id`` NULL.
    dry_run : bool
        If True, run the nearest-neighbour probe over a 5000-row sample and
        return estimated counts without writing.
    batch_size : int
        UPDATE batch size. Small batches keep single-transaction cost
        predictable on a 1.6M-row table.
    max_rows : int | None
        Hard cap on rows processed (useful for time-boxed partial runs).
        None means "run until no candidates left".

    Returns
    -------
    dict with ``linked_from``, ``linked_to``, ``both``, ``unlinked``,
    ``total_processed``, ``batches``, ``mode``, ``max_distance_m``.
    """
    # Normalise: if a pool was passed, acquire a connection.
    if isinstance(conn_or_pool, asyncpg.Pool):
        async with conn_or_pool.acquire() as conn:
            return await link_grid_lines(
                conn,
                max_distance_m=max_distance_m,
                dry_run=dry_run,
                batch_size=batch_size,
                max_rows=max_rows,
                progress_every=progress_every,
            )
    conn = conn_or_pool

    candidates = await _count_candidates(conn)
    log.info(
        "grid_line_linker: %d candidate rows (NULL from or to), threshold=%.1fm, dry_run=%s",
        candidates, max_distance_m, dry_run,
    )

    if dry_run:
        probe = await _probe_batch(
            conn,
            max_distance_m=max_distance_m,
            sample=min(batch_size, max(1000, candidates)),
        )
        return {
            "mode": "dry_run",
            "max_distance_m": max_distance_m,
            "candidates": candidates,
            **probe,
            "total_processed": 0,
            "batches": 0,
        }

    totals = {
        "linked_from": 0, "linked_to": 0, "both": 0,
        "total_processed": 0, "batches": 0,
    }
    target = candidates if max_rows is None else min(candidates, max_rows)
    if target == 0:
        log.info("grid_line_linker: nothing to do — exiting.")
        return {
            "mode": "live",
            "max_distance_m": max_distance_m,
            "unlinked": 0,
            **totals,
        }

    while totals["total_processed"] < target:
        remaining = target - totals["total_processed"]
        this_batch = min(batch_size, remaining)

        async with conn.transaction():
            stats = await _link_batch(
                conn,
                max_distance_m=max_distance_m,
                batch_size=this_batch,
            )
        if stats["seen"] == 0:
            break

        totals["linked_from"] += stats["linked_from"]
        totals["linked_to"] += stats["linked_to"]
        totals["both"] += stats["both"]
        totals["total_processed"] += stats["seen"]
        totals["batches"] += 1

        if totals["batches"] % progress_every == 0:
            log.info(
                "grid_line_linker: batch %d — processed=%d linked_from=%d linked_to=%d both=%d",
                totals["batches"], totals["total_processed"],
                totals["linked_from"], totals["linked_to"], totals["both"],
            )

    # Post-hoc unlinked count = candidates that still have a NULL end among
    # the rows we actually touched. Cheapest: re-query on the residue.
    unlinked = await conn.fetchval(
        """
        SELECT count(*) FROM grid_lines
        WHERE geom IS NOT NULL
          AND (from_sub_id IS NULL OR to_sub_id IS NULL)
        """
    ) or 0

    summary = {
        "mode": "live",
        "max_distance_m": max_distance_m,
        "candidates_at_start": candidates,
        "unlinked": unlinked,
        **totals,
    }
    log.info("grid_line_linker: done — %s", summary)
    return summary


# ─────────────────────────────────────────────────────────────────────────
# CLI
# Run with: python -m utils.grid_line_linker [--max-distance-m 100]
#                                             [--dry-run] [--batch-size 5000]
#                                             [--max-rows 100000]
# ─────────────────────────────────────────────────────────────────────────


async def _cli_main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill grid_lines.from_sub_id / to_sub_id via spatial snap.",
    )
    parser.add_argument("--max-distance-m", type=float, default=DEFAULT_MAX_DISTANCE_M,
                        help="Snap threshold in metres (SRID 27700).")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="Rows per UPDATE batch.")
    parser.add_argument("--max-rows", type=int, default=None,
                        help="Cap on total rows processed (default: all candidates).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Probe only — don't write.")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"),
                        help="Postgres DSN (defaults to $DATABASE_URL).")
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not args.db_url:
        log.error("No DATABASE_URL set and --db-url not passed. Aborting.")
        return 2

    pool = await asyncpg.create_pool(args.db_url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            summary = await link_grid_lines(
                conn,
                max_distance_m=args.max_distance_m,
                dry_run=args.dry_run,
                batch_size=args.batch_size,
                max_rows=args.max_rows,
            )
        import json as _json
        print(_json.dumps(summary, indent=2, default=str))
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli_main()))

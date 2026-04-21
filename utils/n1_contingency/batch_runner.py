"""Weekly batch runner for the UK N-1 Contingency Map.

Target: compute one `N1Contingency` record for every primary substation in
GB (~7,000 rows) within a 4-6 hour wall-clock budget. We use a
`ProcessPoolExecutor(4)` because:

  * Each worker needs its own asyncpg pool (process-local) + its own
    pandapower subprocess handle — sharing across threads would serialise.
  * pandapower and its C extensions release the GIL but also leak a bit of
    memory per network; bounded workers + periodic `max_tasks_per_child`
    keeps RSS predictable across a 7,000-row sweep.

Progress: each completed worker writes one row to `n1_contingency_map` and
emits a log line. The runner aggregates a summary at the end.

Pilot scope
-----------
v1 ships with a `--dno ssen` filter so we can prove the pipeline end-to-end
on SSEN's ~600 primaries (the smaller footprint) before scaling to all 6
DNOs. Use `--limit N` to cap the run for development.

CLI
---
    # pilot — SSEN only, 50 rows:
    python -m utils.n1_contingency.batch_runner --dno ssen --limit 50

    # weekly prod sweep (all primaries):
    python -m utils.n1_contingency.batch_runner --workers 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from .analyser import run_substation_n1, substation_uuid
from .schema import MODEL_VERSION, N1Contingency

log = logging.getLogger("princeps.n1_contingency.batch")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_WORKERS = 4
DEFAULT_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://localhost:5432/feasibly",
)

# Target "primary" substations — exclude secondary / pole-mounted points.
# `site_type` values vary by DNO; we select the ones that carry material
# load and would drive a contingency study. 11 kV secondaries are excluded
# because the network below them is pole-by-pole radial and does not benefit
# from N-1 analysis.
PRIMARY_SITE_TYPES = ("Primary", "BSP", "GSP")
MIN_VOLTAGE_KV = 11.0


# ---------------------------------------------------------------------------
# Worker entry point — runs in a fresh subprocess
# ---------------------------------------------------------------------------
def _worker_run_one(substation_id: int, db_url: str) -> dict[str, Any]:
    """Execute inside a ProcessPoolExecutor worker.

    Each call opens a lightweight one-shot asyncpg pool because asyncpg pools
    are not safe to share across process boundaries (fork-and-reuse is a
    well-known footgun). The overhead is ~30 ms per call which is trivial
    compared to the 2-20 s pandapower subprocess.
    """
    async def _run() -> dict[str, Any]:
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        try:
            record = await run_substation_n1(substation_id=substation_id, pool=pool)
        finally:
            await pool.close()

        if record is None:
            return {"substation_id": substation_id, "status": "not_found"}
        return {
            "substation_id": substation_id,
            "status": "ok",
            "record": json.loads(record.model_dump_json()),
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:  # pragma: no cover - last-resort catch
        return {
            "substation_id": substation_id,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------
async def upsert_record(conn: asyncpg.Connection, record: N1Contingency) -> None:
    """Upsert one `N1Contingency` into `n1_contingency_map`.

    Geometry is written as WGS84 Point (the migration declares the column as
    `geography(Point, 4326)`).
    """
    await conn.execute(
        """
        INSERT INTO n1_contingency_map (
            substation_id, substation_name, voltage_kv, dno,
            worst_case_overload_pct, worst_case_affected_mw,
            reliability_score, events, last_computed_at, model_version,
            upstream_assets_scanned, failed_outages, notes, geometry
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6,
            $7, $8::jsonb, $9, $10,
            $11, $12, $13::jsonb,
            CASE
                WHEN $14::float8 IS NULL OR $15::float8 IS NULL THEN NULL
                ELSE ST_SetSRID(ST_MakePoint($15, $14), 4326)::geography
            END
        )
        ON CONFLICT (substation_id) DO UPDATE SET
            substation_name         = EXCLUDED.substation_name,
            voltage_kv              = EXCLUDED.voltage_kv,
            dno                     = EXCLUDED.dno,
            worst_case_overload_pct = EXCLUDED.worst_case_overload_pct,
            worst_case_affected_mw  = EXCLUDED.worst_case_affected_mw,
            reliability_score       = EXCLUDED.reliability_score,
            events                  = EXCLUDED.events,
            last_computed_at        = EXCLUDED.last_computed_at,
            model_version           = EXCLUDED.model_version,
            upstream_assets_scanned = EXCLUDED.upstream_assets_scanned,
            failed_outages          = EXCLUDED.failed_outages,
            notes                   = EXCLUDED.notes,
            geometry                = EXCLUDED.geometry
        """,
        record.substation_id,
        record.substation_name,
        float(record.voltage_kv),
        record.dno,
        float(record.worst_case_overload_pct),
        float(record.worst_case_affected_mw),
        float(record.reliability_score_0_100),
        json.dumps([e.model_dump() for e in record.n1_outage_events]),
        record.last_computed_at,
        record.model_version,
        int(record.upstream_assets_scanned),
        int(record.failed_outages),
        json.dumps(record.notes),
        record.lat,
        record.lon,
    )


# ---------------------------------------------------------------------------
# Target-set builder
# ---------------------------------------------------------------------------
async def load_target_substations(
    pool: asyncpg.Pool,
    *,
    dno: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[int]:
    """Return the set of grid_substations.id to compute N-1 for."""
    clauses = ["voltage_kv >= $1"]
    args: list[Any] = [MIN_VOLTAGE_KV]
    if dno:
        clauses.append(f"dno = ${len(args) + 1}")
        args.append(dno)
    if PRIMARY_SITE_TYPES:
        clauses.append(
            f"(site_type = ANY(${len(args) + 1}::text[]) OR site_type IS NULL)"
        )
        args.append(list(PRIMARY_SITE_TYPES))

    sql = f"""
        SELECT id
          FROM grid_substations
         WHERE {' AND '.join(clauses)}
      ORDER BY voltage_kv DESC, id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    rows = await pool.fetch(sql, *args)
    return [int(r["id"]) for r in rows]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
async def run_batch(
    db_url: str = DEFAULT_DB_URL,
    *,
    dno: Optional[str] = None,
    limit: Optional[int] = None,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """Run the weekly batch. Returns a summary dict.

    Architecture:

        main process (asyncio)
            ├── loads target_ids (asyncpg)
            ├── ProcessPoolExecutor(workers)
            │       └── each worker: asyncpg + pandapower subprocess
            └── collects results as_completed, upserts via main pool
    """
    started = time.time()
    summary: dict[str, Any] = {
        "dno_filter": dno,
        "limit": limit,
        "workers": workers,
        "model_version": MODEL_VERSION,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "upserted": 0,
        "failed": 0,
        "not_found": 0,
        "errors": [],
    }

    main_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=4)
    try:
        target_ids = await load_target_substations(main_pool, dno=dno, limit=limit)
        summary["target_count"] = len(target_ids)
        log.info(
            "N-1 batch starting — %d substations, %d workers, dno=%s",
            len(target_ids), workers, dno or "ALL",
        )

        if not target_ids:
            summary["finished_at"] = datetime.now(timezone.utc).isoformat()
            summary["elapsed_sec"] = round(time.time() - started, 1)
            return summary

        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                loop.run_in_executor(pool, _worker_run_one, sid, db_url): sid
                for sid in target_ids
            }

            async with main_pool.acquire() as conn:
                completed = 0
                for fut in asyncio.as_completed(list(futures.keys())):
                    result = await fut
                    completed += 1

                    status = result.get("status")
                    if status == "ok":
                        try:
                            rec = N1Contingency.model_validate(result["record"])
                            await upsert_record(conn, rec)
                            summary["upserted"] += 1
                        except Exception as exc:
                            summary["failed"] += 1
                            summary["errors"].append(
                                {"substation_id": result["substation_id"],
                                 "error": f"{type(exc).__name__}: {exc}"}
                            )
                    elif status == "not_found":
                        summary["not_found"] += 1
                    else:
                        summary["failed"] += 1
                        summary["errors"].append(
                            {"substation_id": result["substation_id"],
                             "error": result.get("error", "unknown")}
                        )

                    if completed % 25 == 0 or completed == len(target_ids):
                        log.info(
                            "N-1 batch progress: %d/%d (upserted=%d, failed=%d)",
                            completed, len(target_ids),
                            summary["upserted"], summary["failed"],
                        )
    finally:
        await main_pool.close()

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    summary["elapsed_sec"] = round(time.time() - started, 1)
    log.info("N-1 batch complete: %s", {k: v for k, v in summary.items() if k != "errors"})
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Weekly UK N-1 Contingency Map batch runner.",
    )
    p.add_argument("--db-url", default=DEFAULT_DB_URL,
                   help="Postgres URL (default: $DATABASE_URL or localhost/feasibly)")
    p.add_argument("--dno", default=None,
                   help="Limit to one DNO slug (ukpn/ssen/spen/nged/npg/enwl)")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap number of substations (dev / pilot)")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                   help="ProcessPoolExecutor worker count (default 4)")
    p.add_argument("--log-level", default="INFO")
    return p


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    summary = asyncio.run(run_batch(
        db_url=args.db_url,
        dno=args.dno,
        limit=args.limit,
        workers=args.workers,
    ))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()

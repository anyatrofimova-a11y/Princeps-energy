"""Pipeline Builder — declarative DAG executor over connectors / SQL / sets.

  GET    /api/pipelines                 — list
  GET    /api/pipelines/{slug}          — detail + recent runs
  POST   /api/pipelines                 — create {slug, title, manifest}
  PATCH  /api/pipelines/{slug}          — update
  DELETE /api/pipelines/{slug}          — discard
  POST   /api/pipelines/{slug}/run      — execute now; returns {run_id}
  GET    /api/pipelines/runs/{run_id}   — run detail + per-node log

Manifest shape:
  {
    "nodes": [
      {"id": "n1", "kind": "connector_source", "props": {"slug": "bmrs_settlement_prices"}},
      {"id": "n2", "kind": "sql_transform", "props": {"sql": "SELECT * FROM bmrs_settlement_prices WHERE settlement_date > NOW() - INTERVAL '7 days'"}},
      {"id": "n3", "kind": "set_filter", "props": {"set_slug": "operational-bess-50mw"}},
      {"id": "n4", "kind": "dataset_sink", "props": {"table": "pipeline_output_demo", "if_exists": "replace"}}
    ],
    "edges": [
      {"from": "n1", "to": "n2"},
      {"from": "n2", "to": "n4"},
      {"from": "n3", "to": "n4"}
    ]
  }

V1 executor is SQL-only — no Python sandbox. Sufficient for pipeline-as-
data-flow patterns. sql_transform receives `${input}` placeholders that
expand to the prior node's row count or table reference.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.deps import get_pool as _raw_pool  # noqa: F401
from app.middleware.tenant_jwt import get_tenant_pool as get_pool

log = logging.getLogger("princeps.pipelines")
router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


def _parse_uuid(s: str) -> UUID:
    try:
        return UUID(s)
    except (ValueError, TypeError):
        raise HTTPException(400, f"invalid uuid: {s}")


def _row_to_dict(r) -> dict:
    return {
        "pipeline_id": str(r["pipeline_id"]),
        "slug": r["slug"],
        "title": r["title"],
        "description": r["description"],
        "manifest": r["manifest"] if isinstance(r["manifest"], dict) else json.loads(r["manifest"] or "{}"),
        "cadence": r["cadence"],
        "enabled": r["enabled"],
        "created_by": r["created_by"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        "last_run_at": r["last_run_at"].isoformat() if r["last_run_at"] else None,
        "last_run_ok": r["last_run_ok"],
    }


@router.get("")
async def list_pipelines(
    limit: int = Query(50, ge=1, le=500),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM data_pipelines ORDER BY updated_at DESC LIMIT $1",
            limit,
        )
    return {"pipelines": [_row_to_dict(r) for r in rows], "count": len(rows)}


@router.post("")
async def create_pipeline(
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    slug = body.get("slug")
    title = body.get("title")
    manifest = body.get("manifest")
    if not slug or not title or not isinstance(manifest, dict):
        raise HTTPException(400, "slug, title, manifest(dict) required")
    nodes = manifest.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        raise HTTPException(400, "manifest.nodes must be a non-empty list")

    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO data_pipelines
                  (slug, title, description, manifest, cadence, enabled, created_by)
                VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7)
                RETURNING *
                """,
                slug, title, body.get("description"),
                json.dumps(manifest, default=str),
                body.get("cadence", "on_demand"),
                bool(body.get("enabled", True)),
                body.get("created_by", "anonymous"),
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"slug '{slug}' already exists")
    return _row_to_dict(row)


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    rid = _parse_uuid(run_id)
    async with pool.acquire() as conn:
        run = await conn.fetchrow("SELECT * FROM pipeline_runs WHERE run_id = $1", rid)
        if not run:
            raise HTTPException(404, "run not found")
        nodes = await conn.fetch(
            """
            SELECT * FROM pipeline_node_runs WHERE run_id = $1
            ORDER BY started_at
            """,
            rid,
        )
    return {
        "run_id": str(run["run_id"]),
        "pipeline_id": str(run["pipeline_id"]),
        "started_at": run["started_at"].isoformat() if run["started_at"] else None,
        "completed_at": run["completed_at"].isoformat() if run["completed_at"] else None,
        "ok": run["ok"],
        "rows_processed": run["rows_processed"],
        "duration_ms": run["duration_ms"],
        "error": run["error"],
        "triggered_by": run["triggered_by"],
        "node_runs": [
            {
                "node_id": n["node_id"],
                "node_kind": n["node_kind"],
                "started_at": n["started_at"].isoformat() if n["started_at"] else None,
                "completed_at": n["completed_at"].isoformat() if n["completed_at"] else None,
                "ok": n["ok"],
                "rows_in": n["rows_in"],
                "rows_out": n["rows_out"],
                "duration_ms": n["duration_ms"],
                "error": n["error"],
                "result_summary": n["result_summary"] if isinstance(n["result_summary"], dict) else json.loads(n["result_summary"] or "{}"),
            } for n in nodes
        ],
    }


@router.get("/{slug}")
async def get_pipeline(
    slug: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM data_pipelines WHERE slug = $1", slug)
        if not row:
            raise HTTPException(404, "not found")
        runs = await conn.fetch(
            """
            SELECT run_id, started_at, completed_at, ok, rows_processed, duration_ms, error, triggered_by
            FROM pipeline_runs WHERE pipeline_id = $1
            ORDER BY started_at DESC LIMIT 10
            """,
            row["pipeline_id"],
        )
    out = _row_to_dict(row)
    out["recent_runs"] = [
        {
            "run_id": str(r["run_id"]),
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "ok": r["ok"],
            "rows_processed": r["rows_processed"],
            "duration_ms": r["duration_ms"],
            "error": r["error"],
            "triggered_by": r["triggered_by"],
        } for r in runs
    ]
    return out


@router.patch("/{slug}")
async def patch_pipeline(
    slug: str,
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    sets = []
    params: list[Any] = []
    def _b(v):
        params.append(v); return f"${len(params)}"
    if "title" in body: sets.append(f"title = {_b(body['title'])}")
    if "description" in body: sets.append(f"description = {_b(body['description'])}")
    if "manifest" in body:
        if not isinstance(body["manifest"], dict):
            raise HTTPException(400, "manifest must be a dict")
        sets.append(f"manifest = {_b(json.dumps(body['manifest']))}::jsonb")
    if "cadence" in body: sets.append(f"cadence = {_b(body['cadence'])}")
    if "enabled" in body: sets.append(f"enabled = {_b(bool(body['enabled']))}")
    if not sets:
        raise HTTPException(400, "no editable fields")
    params.append(slug)
    sql = f"UPDATE data_pipelines SET {', '.join(sets)} WHERE slug = ${len(params)} RETURNING *"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
    if not row: raise HTTPException(404, "not found")
    return _row_to_dict(row)


@router.get("/scheduler/status")
async def scheduler_status():
    """Status of the cadence-based pipeline scheduler."""
    from app.startup import get_pipeline_scheduler
    ps = get_pipeline_scheduler()
    if not ps:
        return {"status": "not_started", "scheduled": []}
    return {"status": "running", "scheduled": ps.status()}


@router.post("/scheduler/{slug}/fire-now")
async def scheduler_fire_now(slug: str):
    from app.startup import get_pipeline_scheduler
    ps = get_pipeline_scheduler()
    if not ps:
        raise HTTPException(503, "scheduler not started")
    ok = ps.fire_now(slug)
    if not ok:
        raise HTTPException(404, f"no scheduled job for slug '{slug}'")
    return {"slug": slug, "fired": True}


@router.delete("/{slug}")
async def delete_pipeline(slug: str, pool: asyncpg.Pool = Depends(get_pool)):
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM data_pipelines WHERE slug = $1", slug)
    if result == "DELETE 0":
        raise HTTPException(404, "not found")
    return {"slug": slug, "deleted": True}


@router.post("/{slug}/run")
async def run_pipeline(
    slug: str,
    body: dict[str, Any] | None = Body(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    triggered_by = (body or {}).get("triggered_by", "anonymous")
    async with pool.acquire() as conn:
        pipe = await conn.fetchrow("SELECT * FROM data_pipelines WHERE slug = $1", slug)
        if not pipe:
            raise HTTPException(404, "pipeline not found")
        if not pipe["enabled"]:
            raise HTTPException(409, "pipeline disabled")

        # Open a run row
        run_row = await conn.fetchrow(
            """
            INSERT INTO pipeline_runs (pipeline_id, triggered_by)
            VALUES ($1, $2) RETURNING *
            """,
            pipe["pipeline_id"], triggered_by,
        )
    run_id = run_row["run_id"]

    manifest = pipe["manifest"] if isinstance(pipe["manifest"], dict) else json.loads(pipe["manifest"])
    nodes_by_id = {n["id"]: n for n in manifest.get("nodes", [])}
    edges = manifest.get("edges", [])

    # Build adjacency + in-degree for topo sort
    children: dict[str, list[str]] = {nid: [] for nid in nodes_by_id}
    in_deg: dict[str, int] = {nid: 0 for nid in nodes_by_id}
    parents: dict[str, list[str]] = {nid: [] for nid in nodes_by_id}
    for e in edges:
        f, t = e.get("from"), e.get("to")
        if f not in nodes_by_id or t not in nodes_by_id:
            continue
        children[f].append(t)
        parents[t].append(f)
        in_deg[t] += 1

    # Kahn's algorithm
    queue = [n for n, d in in_deg.items() if d == 0]
    order: list[str] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for c in children[n]:
            in_deg[c] -= 1
            if in_deg[c] == 0:
                queue.append(c)
    if len(order) != len(nodes_by_id):
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE pipeline_runs SET ok=FALSE, completed_at=NOW(), error=$2 WHERE run_id=$1",
                run_id, "cycle detected in DAG",
            )
        raise HTTPException(400, "cycle detected in pipeline DAG")

    # Execute
    started = time.time()
    node_results: dict[str, dict] = {}
    overall_rows = 0
    overall_ok = True
    err_summary = None

    # Retry policy — pulled from manifest, falls back to single-attempt
    retry_policy = manifest.get("retry_policy") or {}
    max_attempts = max(1, min(int(retry_policy.get("max_attempts", 1)), 10))
    backoff_ms = max(0, min(int(retry_policy.get("backoff_ms", 500)), 30000))

    for nid in order:
        node = nodes_by_id[nid]
        kind = node.get("kind")
        props = node.get("props") or {}
        input_summaries = [node_results.get(p, {}) for p in parents[nid]]
        rows_in = sum(int(s.get("rows_out", 0) or 0) for s in input_summaries)

        last_exc = None
        result = None
        attempt_used = 0
        for attempt in range(1, max_attempts + 1):
            attempt_used = attempt
            node_started = time.time()
            try:
                result = await _exec_node(pool, kind, props, input_summaries)
                duration_ms = int((time.time() - node_started) * 1000)
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO pipeline_node_runs
                          (run_id, node_id, node_kind, started_at, completed_at, ok,
                           rows_in, rows_out, duration_ms, result_summary,
                           attempt_number, attempts_total)
                        VALUES ($1,$2,$3,NOW() - ($4 * INTERVAL '1 ms'), NOW(), TRUE,
                                $5, $6, $4, $7::jsonb, $8, $9)
                        """,
                        run_id, nid, kind, int(duration_ms), int(rows_in),
                        int(result.get("rows_out", 0) or 0),
                        json.dumps(result, default=str),
                        attempt, max_attempts,
                    )
                last_exc = None
                break  # success — drop out of retry loop
            except Exception as exc:
                last_exc = exc
                duration_ms = int((time.time() - node_started) * 1000)
                will_retry = attempt < max_attempts
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO pipeline_node_runs
                          (run_id, node_id, node_kind, started_at, completed_at, ok,
                           rows_in, duration_ms, error,
                           attempt_number, attempts_total, retry_reason)
                        VALUES ($1,$2,$3,NOW() - ($4 * INTERVAL '1 ms'), NOW(), FALSE,
                                0, $4, $5, $6, $7, $8)
                        """,
                        run_id, nid, kind, int(duration_ms), str(exc),
                        attempt, max_attempts,
                        "will_retry" if will_retry else "max_attempts_reached",
                    )
                if will_retry:
                    delay_ms = backoff_ms * (2 ** (attempt - 1))
                    log.warning(
                        "pipeline node %s attempt %d/%d failed: %s — retrying in %dms",
                        nid, attempt, max_attempts, exc, delay_ms,
                    )
                    await asyncio.sleep(delay_ms / 1000.0)
                else:
                    log.exception("pipeline node %s exhausted retries", nid)

        if last_exc is not None:
            overall_ok = False
            err_summary = f"node {nid} ({kind}) after {attempt_used} attempts: {last_exc}"
            break

        node_results[nid] = result
        overall_rows += int((result or {}).get("rows_out", 0) or 0)

    total_dur = int((time.time() - started) * 1000)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE pipeline_runs
               SET ok = $2, rows_processed = $3, duration_ms = $4,
                   completed_at = NOW(), error = $5
             WHERE run_id = $1
            """,
            run_id, overall_ok, overall_rows, total_dur, err_summary,
        )
        await conn.execute(
            "UPDATE data_pipelines SET last_run_at = NOW(), last_run_ok = $2 WHERE pipeline_id = $1",
            pipe["pipeline_id"], overall_ok,
        )

    return {
        "run_id": str(run_id),
        "ok": overall_ok,
        "rows_processed": overall_rows,
        "duration_ms": total_dur,
        "error": err_summary,
        "node_count": len(order),
    }


async def _exec_node(pool, kind: str, props: dict, inputs: list[dict]) -> dict:
    """Run one node. Returns a small summary; caller persists."""
    if kind == "connector_source":
        slug = props.get("slug")
        if not slug:
            raise ValueError("connector_source needs props.slug")
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT slug, table_name, last_row_count FROM princeps_datasets WHERE slug = $1",
                slug,
            )
            if not row:
                raise ValueError(f"connector '{slug}' not registered")
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {row['table_name']}")
        return {"kind": kind, "source_slug": slug, "table": row["table_name"], "rows_out": count or 0}

    if kind == "sql_transform":
        sql = props.get("sql")
        if not sql or not isinstance(sql, str):
            raise ValueError("sql_transform needs props.sql (string)")
        # Hard guard: read-only via a simple keyword check
        upper = sql.strip().upper()
        if not upper.startswith("SELECT") and not upper.startswith("WITH"):
            raise ValueError("sql_transform: only SELECT / WITH allowed")
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
        # Echo `sql` in the summary so a downstream dataset_sink can pick it up
        # for CTAS without re-deriving it from the manifest.
        return {
            "kind": kind, "rows_out": len(rows),
            "sample_keys": list(rows[0].keys()) if rows else [],
            "sql": sql,
        }

    if kind == "set_filter":
        slug = props.get("set_slug")
        if not slug:
            raise ValueError("set_filter needs props.set_slug")
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM object_sets WHERE slug = $1", slug)
            if not row:
                raise ValueError(f"set '{slug}' not found")
            from app.routers.object_sets import _resolve_one  # local import to avoid cycle
            ids = await _resolve_one(conn, row, limit=2000)
        return {"kind": kind, "set_slug": slug, "rows_out": len(ids)}

    if kind == "dataset_sink":
        target = props.get("table")
        if not target:
            raise ValueError("dataset_sink needs props.table")
        # Sanitise target — only [a-z0-9_], must start with a letter, max 60ch
        import re as _re
        if not _re.match(r"^[a-z][a-z0-9_]{0,59}$", target):
            raise ValueError(f"dataset_sink target '{target}' must be snake_case [a-z][a-z0-9_]")

        # Find the upstream sql_transform's SQL — first input that has it wins
        upstream_sql = None
        for i in inputs:
            if isinstance(i, dict) and i.get("sql"):
                upstream_sql = i["sql"]
                break
        if not upstream_sql:
            # No SQL upstream → soft-record the sink (as before)
            return {
                "kind": kind, "target_table": target,
                "materialised": False,
                "rows_out": sum(int(i.get("rows_out", 0) or 0) for i in inputs),
                "note": "no upstream sql_transform — sink recorded only",
            }

        if_exists = (props.get("if_exists") or "replace").lower()
        if if_exists not in {"replace", "append", "skip"}:
            raise ValueError("if_exists must be replace|append|skip")

        # Materialise via CTAS
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                target,
            )
            if exists and if_exists == "skip":
                rows_out = await conn.fetchval(f"SELECT COUNT(*) FROM {target}")
                return {"kind": kind, "target_table": target, "materialised": False,
                        "rows_out": rows_out or 0, "note": "exists, if_exists=skip"}
            if exists and if_exists == "replace":
                await conn.execute(f"DROP TABLE {target}")
                exists = False
            if exists and if_exists == "append":
                await conn.execute(f"INSERT INTO {target} {upstream_sql}")
            else:
                await conn.execute(f"CREATE TABLE {target} AS {upstream_sql}")

            rows_out = await conn.fetchval(f"SELECT COUNT(*) FROM {target}")

            # Register in princeps_datasets so it shows up in the catalogue
            slug = f"pipeline_{target}"
            await conn.execute(
                """
                INSERT INTO princeps_datasets
                  (slug, title, source_url, license, refresh_cadence,
                   table_name, last_refreshed_at, last_refresh_ok,
                   last_row_count, health_status, health_checked_at, metadata)
                VALUES ($1,$2,$3,'OGL-3.0','on_demand',$4,NOW(),TRUE,
                        $5,'green',NOW(),$6::jsonb)
                ON CONFLICT (slug) DO UPDATE
                  SET last_refreshed_at = NOW(), last_refresh_ok = TRUE,
                      last_row_count = EXCLUDED.last_row_count,
                      health_status = 'green', health_checked_at = NOW(),
                      metadata = EXCLUDED.metadata,
                      updated_at = NOW()
                """,
                slug, f"Pipeline output: {target}",
                f"princeps://pipeline/{target}", target,
                rows_out or 0,
                json.dumps({"materialised_by": "pipeline_dataset_sink",
                            "if_exists": if_exists}),
            )

            # Lineage edge — register the connector→table relationship in
            # dataset_lineage so the lineage-graph endpoint sees the derivation.
            await conn.execute(
                """
                INSERT INTO dataset_lineage(upstream_slug, downstream_slug, relationship)
                VALUES ($1, $2, 'derives_from')
                ON CONFLICT DO NOTHING
                """,
                "pipeline:" + (props.get("pipeline_slug") or "unknown"),
                slug,
            )

        return {
            "kind": kind, "target_table": target,
            "materialised": True, "if_exists": if_exists,
            "rows_out": rows_out or 0,
            "registered_slug": slug,
        }

    raise ValueError(f"unknown node kind: {kind}")

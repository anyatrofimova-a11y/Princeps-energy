"""Persistent workflow engine — templates, runs, pause/resume."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import asyncpg

from app.deps import get_pool, get_optional_user

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows-v1"])


class TemplateCreateRequest(BaseModel):
    name: str
    description: str | None = None
    steps: list[dict]


class RunCreateRequest(BaseModel):
    template_id: str | None = None
    preset: str | None = None
    parcel_id: str
    project_id: str | None = None
    capacity_kw: float = 100.0


@router.get("/templates")
async def list_templates(pool: asyncpg.Pool = Depends(get_pool)):
    """List available workflow templates."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT template_id, name, description, steps, is_system, created_at
               FROM workflow_templates ORDER BY is_system DESC, name"""
        )
    return [
        {
            "template_id": str(r["template_id"]),
            "name": r["name"],
            "description": r["description"],
            "steps": json.loads(r["steps"]) if isinstance(r["steps"], str) else r["steps"],
            "is_system": r["is_system"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.post("/templates")
async def create_template(
    body: TemplateCreateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Create a custom workflow template."""
    user_id = user["user_id"] if user else None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO workflow_templates (user_id, name, description, steps)
               VALUES ($1, $2, $3, $4)
               RETURNING template_id, created_at""",
            user_id, body.name, body.description, json.dumps(body.steps),
        )
    return {
        "template_id": str(row["template_id"]),
        "created_at": row["created_at"].isoformat(),
    }


@router.post("/run")
async def start_run(
    body: RunCreateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Start a workflow run."""
    user_id = user["user_id"] if user else None
    template_id = UUID(body.template_id) if body.template_id else None
    parcel_id = UUID(body.parcel_id)
    project_id = UUID(body.project_id) if body.project_id else None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO workflow_runs
                   (template_id, user_id, parcel_id, project_id, status, started_at)
               VALUES ($1, $2, $3, $4, 'running', NOW())
               RETURNING run_id, created_at""",
            template_id, user_id, parcel_id, project_id,
        )
    return {
        "run_id": str(row["run_id"]),
        "status": "running",
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/run/{run_id}")
async def get_run(run_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Get run status + step results."""
    rid = UUID(run_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM workflow_runs WHERE run_id = $1", rid
        )
    if not row:
        raise HTTPException(404, "Run not found")
    return {
        "run_id": str(row["run_id"]),
        "template_id": str(row["template_id"]) if row["template_id"] else None,
        "parcel_id": str(row["parcel_id"]) if row["parcel_id"] else None,
        "project_id": str(row["project_id"]) if row["project_id"] else None,
        "status": row["status"],
        "current_step": row["current_step"],
        "steps_completed": json.loads(row["steps_completed"]) if isinstance(row["steps_completed"], str) else row["steps_completed"],
        "overall_verdict": row["overall_verdict"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
    }


@router.post("/run/{run_id}/pause")
async def pause_run(run_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Pause at next step boundary."""
    rid = UUID(run_id)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE workflow_runs SET status = 'paused' WHERE run_id = $1 AND status = 'running'",
            rid,
        )
    return {"run_id": run_id, "status": "paused"}


@router.post("/run/{run_id}/resume")
async def resume_run(run_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Resume a paused run."""
    rid = UUID(run_id)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE workflow_runs SET status = 'running' WHERE run_id = $1 AND status = 'paused'",
            rid,
        )
    return {"run_id": run_id, "status": "running"}


@router.get("/history")
async def list_runs(
    project_id: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """List workflow runs for user/project."""
    async with pool.acquire() as conn:
        if project_id:
            rows = await conn.fetch(
                """SELECT run_id, template_id, parcel_id, status, overall_verdict,
                          started_at, finished_at, created_at
                   FROM workflow_runs WHERE project_id = $1
                   ORDER BY created_at DESC LIMIT $2""",
                UUID(project_id), limit,
            )
        elif user:
            rows = await conn.fetch(
                """SELECT run_id, template_id, parcel_id, status, overall_verdict,
                          started_at, finished_at, created_at
                   FROM workflow_runs WHERE user_id = $1
                   ORDER BY created_at DESC LIMIT $2""",
                user["user_id"], limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT run_id, template_id, parcel_id, status, overall_verdict,
                          started_at, finished_at, created_at
                   FROM workflow_runs ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
    return [
        {
            "run_id": str(r["run_id"]),
            "template_id": str(r["template_id"]) if r["template_id"] else None,
            "parcel_id": str(r["parcel_id"]) if r["parcel_id"] else None,
            "status": r["status"],
            "overall_verdict": r["overall_verdict"],
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
        }
        for r in rows
    ]

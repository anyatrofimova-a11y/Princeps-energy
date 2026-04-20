"""Project pipeline — CRUD for projects with stage management and documents."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncpg

from app.deps import get_pool, get_optional_user

DOCUMENTS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "documents"
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

VALID_STAGES = [
    "prospect", "screened", "grid_applied", "grid_offer",
    "planning", "fid", "construction", "energised",
]
VALID_TECHNOLOGIES = ["solar", "bess", "wind", "dc", "hybrid"]
VALID_VERDICTS = ["GO", "CAUTION", "NO-GO"]


class ProjectCreateRequest(BaseModel):
    name: str
    technology: str | None = None
    capacity_mw: float | None = None
    stage: str = "prospect"
    verdict: str | None = None
    lat: float | None = None
    lon: float | None = None
    blocker: str | None = None
    description: str | None = None
    parcel_id: str | None = None
    repd_id: str | None = None
    tec_id: str | None = None
    metadata: dict | None = None
    portfolio_id: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    technology: str | None = None
    capacity_mw: float | None = None
    stage: str | None = None
    verdict: str | None = None
    lat: float | None = None
    lon: float | None = None
    blocker: str | None = None
    description: str | None = None
    metadata: dict | None = None
    portfolio_id: str | None = None


class CandidateSiteRequest(BaseModel):
    name: str | None = None
    lat: float
    lon: float
    capacity_mw: float | None = None
    scores: dict | None = None
    lcoe: float | None = None
    verdict: str | None = None
    is_preferred: bool = False


class CandidateSiteUpdate(BaseModel):
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    capacity_mw: float | None = None
    scores: dict | None = None
    lcoe: float | None = None
    verdict: str | None = None
    is_preferred: bool | None = None


def _row_to_dict(row) -> dict:
    return {
        "project_id": str(row["project_id"]),
        "user_id": str(row["user_id"]) if row["user_id"] else None,
        "portfolio_id": str(row["portfolio_id"]) if "portfolio_id" in row and row["portfolio_id"] else None,
        "name": row["name"],
        "description": row["description"],
        "technology": row["technology"],
        "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] else None,
        "stage": row["stage"],
        "verdict": row["verdict"],
        "lat": float(row["lat"]) if row["lat"] else None,
        "lon": float(row["lon"]) if row["lon"] else None,
        "blocker": row["blocker"],
        "repd_id": row["repd_id"],
        "tec_id": row["tec_id"],
        "stage_entered_at": row["stage_entered_at"].isoformat() if row["stage_entered_at"] else None,
        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _candidate_row(row) -> dict:
    return {
        "candidate_id": str(row["candidate_id"]),
        "project_id": str(row["project_id"]),
        "name": row["name"],
        "lat": float(row["lat"]) if row["lat"] else None,
        "lon": float(row["lon"]) if row["lon"] else None,
        "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] else None,
        "scores": json.loads(row["scores"]) if isinstance(row["scores"], str) else (row["scores"] or {}),
        "lcoe": float(row["lcoe"]) if row["lcoe"] else None,
        "verdict": row["verdict"],
        "is_preferred": row["is_preferred"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


@router.post("")
async def create_project(
    body: ProjectCreateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Create a new pipeline project."""
    if body.stage and body.stage not in VALID_STAGES:
        raise HTTPException(400, f"Invalid stage: {body.stage}. Must be one of {VALID_STAGES}")
    if body.technology and body.technology not in VALID_TECHNOLOGIES:
        raise HTTPException(400, f"Invalid technology: {body.technology}. Must be one of {VALID_TECHNOLOGIES}")
    if body.verdict and body.verdict not in VALID_VERDICTS:
        raise HTTPException(400, f"Invalid verdict: {body.verdict}. Must be one of {VALID_VERDICTS}")

    user_id = user["user_id"] if user else None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO projects
                   (user_id, name, description, technology, capacity_mw,
                    stage, verdict, lat, lon, blocker, stage_entered_at,
                    repd_id, tec_id, metadata, portfolio_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW(), $11, $12, $13, $14)
               RETURNING *""",
            user_id, body.name, body.description, body.technology,
            body.capacity_mw, body.stage or "prospect", body.verdict,
            body.lat, body.lon, body.blocker,
            body.repd_id, body.tec_id,
            json.dumps(body.metadata) if body.metadata else "{}",
            UUID(body.portfolio_id) if body.portfolio_id else None,
        )

        # Record initial stage
        await conn.execute(
            """INSERT INTO project_stage_history (project_id, to_stage, changed_by, notes)
               VALUES ($1, $2, $3, 'Project created')""",
            row["project_id"], body.stage or "prospect", user_id,
        )

        # Link to parcel if provided
        if body.parcel_id:
            await conn.execute(
                """INSERT INTO project_sites (project_id, parcel_id)
                   VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                row["project_id"], UUID(body.parcel_id),
            )

    return _row_to_dict(row)


@router.get("")
async def list_projects(
    stage: str | None = Query(None),
    technology: str | None = Query(None),
    verdict: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List all pipeline projects with optional filters."""
    conditions = []
    params = []
    idx = 1

    if stage:
        conditions.append(f"stage = ${idx}")
        params.append(stage)
        idx += 1
    if technology:
        conditions.append(f"technology = ${idx}")
        params.append(technology)
        idx += 1
    if verdict:
        conditions.append(f"verdict = ${idx}")
        params.append(verdict)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT * FROM projects {where}
                ORDER BY updated_at DESC NULLS LAST
                LIMIT ${idx} OFFSET ${idx + 1}""",
            *params, limit, offset,
        )
        total = await conn.fetchval(
            f"SELECT count(*) FROM projects {where}", *params
        )

    return {
        "projects": [_row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/summary")
async def pipeline_summary(pool: asyncpg.Pool = Depends(get_pool)):
    """Aggregate pipeline stats — counts and MW by stage, technology, verdict."""
    async with pool.acquire() as conn:
        by_stage = await conn.fetch(
            """SELECT stage, count(*) AS count, COALESCE(sum(capacity_mw), 0) AS total_mw
               FROM projects GROUP BY stage ORDER BY stage"""
        )
        by_tech = await conn.fetch(
            """SELECT technology, count(*) AS count, COALESCE(sum(capacity_mw), 0) AS total_mw
               FROM projects WHERE technology IS NOT NULL
               GROUP BY technology ORDER BY total_mw DESC"""
        )
        by_verdict = await conn.fetch(
            """SELECT verdict, count(*) AS count
               FROM projects WHERE verdict IS NOT NULL
               GROUP BY verdict"""
        )
        totals = await conn.fetchrow(
            """SELECT count(*) AS total_projects,
                      COALESCE(sum(capacity_mw), 0) AS total_mw,
                      count(*) FILTER (WHERE stage != 'energised') AS in_progress,
                      count(*) FILTER (WHERE blocker IS NOT NULL) AS blocked
               FROM projects"""
        )

    return {
        "total_projects": totals["total_projects"],
        "total_mw": float(totals["total_mw"]),
        "in_progress": totals["in_progress"],
        "blocked": totals["blocked"],
        "by_stage": [
            {"stage": r["stage"], "count": r["count"], "total_mw": float(r["total_mw"])}
            for r in by_stage
        ],
        "by_technology": [
            {"technology": r["technology"], "count": r["count"], "total_mw": float(r["total_mw"])}
            for r in by_tech
        ],
        "by_verdict": {r["verdict"]: r["count"] for r in by_verdict},
    }


@router.get("/{project_id}")
async def get_project(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Get full project details including linked parcels."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM projects WHERE project_id = $1", pid)
        if not row:
            raise HTTPException(404, "Project not found")

        parcels = await conn.fetch(
            """SELECT ps.parcel_id, ps.added_at,
                      ST_Y(ST_Transform(p.centroid, 4326)) AS lat,
                      ST_X(ST_Transform(p.centroid, 4326)) AS lon,
                      p.area_m2
               FROM project_sites ps
               LEFT JOIN parcels p ON p.parcel_id = ps.parcel_id
               WHERE ps.project_id = $1""",
            pid,
        )

    result = _row_to_dict(row)
    result["parcels"] = [
        {
            "parcel_id": str(p["parcel_id"]),
            "lat": float(p["lat"]) if p["lat"] else None,
            "lon": float(p["lon"]) if p["lon"] else None,
            "area_m2": float(p["area_m2"]) if p["area_m2"] else None,
            "added_at": p["added_at"].isoformat(),
        }
        for p in parcels
    ]
    return result


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body: ProjectUpdateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Update project fields. Stage changes are tracked in history."""
    pid = UUID(project_id)
    user_id = user["user_id"] if user else None

    if body.stage and body.stage not in VALID_STAGES:
        raise HTTPException(400, f"Invalid stage: {body.stage}")
    if body.verdict and body.verdict not in VALID_VERDICTS:
        raise HTTPException(400, f"Invalid verdict: {body.verdict}")

    async with pool.acquire() as conn:
        current = await conn.fetchrow("SELECT * FROM projects WHERE project_id = $1", pid)
        if not current:
            raise HTTPException(404, "Project not found")

        # Build SET clause dynamically from non-None fields
        updates = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.technology is not None:
            updates["technology"] = body.technology
        if body.capacity_mw is not None:
            updates["capacity_mw"] = body.capacity_mw
        if body.verdict is not None:
            updates["verdict"] = body.verdict
        if body.lat is not None:
            updates["lat"] = body.lat
        if body.lon is not None:
            updates["lon"] = body.lon
        if body.blocker is not None:
            updates["blocker"] = body.blocker
        if body.description is not None:
            updates["description"] = body.description
        if body.metadata is not None:
            updates["metadata"] = json.dumps(body.metadata)

        # Stage change — track in history + reset stage_entered_at
        stage_changed = body.stage and body.stage != current["stage"]
        if stage_changed:
            updates["stage"] = body.stage
            updates["stage_entered_at"] = "NOW()"

        if not updates:
            return _row_to_dict(current)

        # Build parameterised UPDATE
        set_parts = []
        params = []
        idx = 1
        for col, val in updates.items():
            if val == "NOW()":
                set_parts.append(f"{col} = NOW()")
            else:
                set_parts.append(f"{col} = ${idx}")
                params.append(val)
                idx += 1
        set_parts.append("updated_at = NOW()")
        params.append(pid)

        row = await conn.fetchrow(
            f"UPDATE projects SET {', '.join(set_parts)} WHERE project_id = ${idx} RETURNING *",
            *params,
        )

        # Record stage transition
        if stage_changed:
            await conn.execute(
                """INSERT INTO project_stage_history
                       (project_id, from_stage, to_stage, changed_by)
                   VALUES ($1, $2, $3, $4)""",
                pid, current["stage"], body.stage, user_id,
            )

    return _row_to_dict(row)


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Delete a project and its stage history."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(
            "DELETE FROM projects WHERE project_id = $1 RETURNING project_id", pid
        )
        if not deleted:
            raise HTTPException(404, "Project not found")
    return {"deleted": True, "project_id": project_id}


@router.get("/{project_id}/timeline")
async def project_timeline(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Stage history for a project — audit trail of stage transitions."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT h.history_id, h.from_stage, h.to_stage, h.notes,
                      h.created_at, u.name AS changed_by_name
               FROM project_stage_history h
               LEFT JOIN users u ON u.user_id = h.changed_by
               WHERE h.project_id = $1
               ORDER BY h.created_at""",
            pid,
        )
    return {
        "project_id": project_id,
        "transitions": [
            {
                "from_stage": r["from_stage"],
                "to_stage": r["to_stage"],
                "notes": r["notes"],
                "changed_by": r["changed_by_name"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/import-repd/{repd_id}")
async def import_from_repd(
    repd_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Import a project from REPD data into the pipeline."""
    user_id = user["user_id"] if user else None

    async with pool.acquire() as conn:
        repd = await conn.fetchrow(
            "SELECT * FROM repd_projects WHERE repd_id = $1", repd_id
        )
        if not repd:
            raise HTTPException(404, f"REPD project {repd_id} not found")

        # Check for existing import
        existing = await conn.fetchval(
            "SELECT project_id FROM projects WHERE repd_id = $1", repd_id
        )
        if existing:
            raise HTTPException(409, f"REPD project already imported as {existing}")

        # Map REPD status to pipeline stage
        status_map = {
            "Operational": "energised",
            "Under Construction": "construction",
            "Awaiting Construction": "fid",
            "Approved": "planning",
            "Submitted": "grid_applied",
            "Appeal": "planning",
            "Refused": "prospect",
            "Withdrawn": "prospect",
            "Decommissioned": "energised",
        }
        stage = status_map.get(repd["status"], "prospect")

        # Map REPD tech_category
        tech_map = {
            "solar": "solar",
            "wind": "wind",
            "bess": "bess",
            "biomass": "solar",  # fallback
            "hydro": "solar",    # fallback
        }
        technology = tech_map.get(repd.get("tech_category"), None)

        row = await conn.fetchrow(
            """INSERT INTO projects
                   (user_id, name, description, technology, capacity_mw,
                    stage, lat, lon, stage_entered_at, repd_id, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10)
               RETURNING *""",
            user_id,
            repd["site_name"],
            f"Imported from REPD — {repd['status']}",
            technology,
            float(repd["capacity_mw"]) if repd["capacity_mw"] else None,
            stage,
            float(repd["lat"]) if repd.get("lat") else None,
            float(repd["lon"]) if repd.get("lon") else None,
            repd_id,
            json.dumps({
                "repd_status": repd["status"],
                "developer": repd.get("developer"),
                "planning_authority": repd.get("planning_authority"),
                "county": repd.get("county"),
                "region": repd.get("region"),
            }),
        )

        await conn.execute(
            """INSERT INTO project_stage_history (project_id, to_stage, changed_by, notes)
               VALUES ($1, $2, $3, $4)""",
            row["project_id"], stage, user_id,
            f"Imported from REPD ({repd['status']})",
        )

    return _row_to_dict(row)


@router.post("/import-tec/{tec_id}")
async def import_from_tec(
    tec_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Import a project from ESO TEC register into the pipeline."""
    user_id = user["user_id"] if user else None

    async with pool.acquire() as conn:
        tec = await conn.fetchrow(
            "SELECT * FROM eso_tec_register WHERE tec_id = $1", tec_id
        )
        if not tec:
            raise HTTPException(404, f"TEC entry {tec_id} not found")

        existing = await conn.fetchval(
            "SELECT project_id FROM projects WHERE tec_id = $1", tec_id
        )
        if existing:
            raise HTTPException(409, f"TEC entry already imported as {existing}")

        status_map = {
            "Contractual": "grid_offer",
            "Operational": "energised",
            "Under Construction": "construction",
            "Scoping": "prospect",
        }
        stage = status_map.get(tec.get("status"), "grid_applied")

        tech_map = {
            "Solar": "solar", "Wind": "wind", "Battery": "bess",
            "BESS": "bess", "Gas": None, "Nuclear": None,
        }
        technology = tech_map.get(tec.get("fuel_type")) or tech_map.get(tec.get("tech_category"))

        row = await conn.fetchrow(
            """INSERT INTO projects
                   (user_id, name, description, technology, capacity_mw,
                    stage, lat, lon, stage_entered_at, tec_id, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10)
               RETURNING *""",
            user_id,
            tec.get("customer_name", f"TEC-{tec_id}"),
            f"Imported from ESO TEC — {tec.get('connection_site', 'Unknown site')}",
            technology,
            float(tec["tec_mw"]) if tec.get("tec_mw") else None,
            stage,
            float(tec["lat"]) if tec.get("lat") else None,
            float(tec["lon"]) if tec.get("lon") else None,
            tec_id,
            json.dumps({
                "tec_status": tec.get("status"),
                "connection_site": tec.get("connection_site"),
                "voltage_kv": float(tec["voltage_kv"]) if tec.get("voltage_kv") else None,
                "fuel_type": tec.get("fuel_type"),
                "zone": tec.get("zone"),
                "queue_position": tec.get("queue_position"),
            }),
        )

        await conn.execute(
            """INSERT INTO project_stage_history (project_id, to_stage, changed_by, notes)
               VALUES ($1, $2, $3, $4)""",
            row["project_id"], stage, user_id,
            f"Imported from ESO TEC ({tec.get('connection_site', '')})",
        )

    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Bulk REPD Import
# ---------------------------------------------------------------------------

@router.post("/import-repd-bulk")
async def bulk_import_repd(
    technology: str = Query(None, description="Filter: solar, wind, bess"),
    min_capacity_mw: float = Query(10, ge=0),
    max_capacity_mw: float = Query(500),
    status: str = Query(None, description="Filter: Operational, Approved, Submitted, etc."),
    region: str = Query(None),
    limit: int = Query(500, le=5000),
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Bulk import REPD projects into the pipeline. Skips already-imported projects."""
    user_id = user["user_id"] if user else None

    status_map = {
        "Operational": "energised",
        "Under Construction": "construction",
        "Awaiting Construction": "fid",
        "Approved": "planning",
        "Submitted": "grid_applied",
        "Appeal": "planning",
        "Refused": "prospect",
        "Withdrawn": "prospect",
        "Decommissioned": "energised",
    }
    tech_map = {"solar": "solar", "wind": "wind", "bess": "bess", "biomass": "solar", "hydro": "solar"}

    async with pool.acquire() as conn:
        # Build query — repd_projects stores lat/lon as a SRID 27700 geometry,
        # so transform to WGS84 on read and filter on geometry presence.
        conditions = ["r.capacity_mw >= $1", "r.capacity_mw <= $2", "r.geometry IS NOT NULL"]
        params = [min_capacity_mw, max_capacity_mw]
        idx = 3

        if technology:
            conditions.append(f"r.tech_category ILIKE ${idx}")
            params.append(f"%{technology}%")
            idx += 1
        if status:
            conditions.append(f"r.status = ${idx}")
            params.append(status)
            idx += 1
        if region:
            conditions.append(f"r.region ILIKE ${idx}")
            params.append(f"%{region}%")
            idx += 1

        where = " AND ".join(conditions)
        rows = await conn.fetch(
            f"""SELECT r.repd_id, r.site_name, r.status, r.tech_category, r.capacity_mw,
                       r.developer, r.planning_authority, r.county, r.region,
                       ST_Y(ST_Transform(r.geometry, 4326)) AS lat,
                       ST_X(ST_Transform(r.geometry, 4326)) AS lon
                FROM repd_projects r
                LEFT JOIN projects p ON p.repd_id = r.repd_id
                WHERE {where} AND p.project_id IS NULL
                ORDER BY r.capacity_mw DESC
                LIMIT ${idx}""",
            *params, limit,
        )

        imported = 0
        skipped = 0
        for r in rows:
            stage = status_map.get(r["status"], "prospect")
            tech = tech_map.get(r.get("tech_category"), None)
            try:
                row = await conn.fetchrow(
                    """INSERT INTO projects
                           (user_id, name, description, technology, capacity_mw,
                            stage, lat, lon, stage_entered_at, repd_id, metadata)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), $9, $10)
                       ON CONFLICT (repd_id) DO NOTHING
                       RETURNING project_id""",
                    user_id,
                    r["site_name"],
                    f"Bulk imported from REPD — {r['status']}",
                    tech,
                    float(r["capacity_mw"]) if r["capacity_mw"] else None,
                    stage,
                    float(r["lat"]) if r.get("lat") else None,
                    float(r["lon"]) if r.get("lon") else None,
                    r["repd_id"],
                    json.dumps({
                        "repd_status": r["status"],
                        "developer": r.get("developer"),
                        "planning_authority": r.get("planning_authority"),
                        "county": r.get("county"),
                        "region": r.get("region"),
                        "source": "bulk_import",
                    }),
                )
                if row:
                    imported += 1
                    await conn.execute(
                        """INSERT INTO project_stage_history (project_id, to_stage, changed_by, notes)
                           VALUES ($1, $2, $3, $4)""",
                        row["project_id"], stage, user_id,
                        f"Bulk imported from REPD ({r['status']})",
                    )
                else:
                    skipped += 1
            except Exception:
                skipped += 1

    return {
        "imported": imported,
        "skipped": skipped,
        "total_available": len(rows),
        "filters": {"technology": technology, "min_mw": min_capacity_mw, "max_mw": max_capacity_mw, "status": status, "region": region},
    }


# ---------------------------------------------------------------------------
# Phase 2 — Document storage
# ---------------------------------------------------------------------------

VALID_DOC_TYPES = [
    "report", "grid_offer", "planning_app", "epc_contract",
    "ppa", "land_option", "environmental", "financial",
    "technical", "correspondence", "other",
]


@router.post("/{project_id}/documents")
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    title: str = Form(None),
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Upload a document to a project."""
    pid = UUID(project_id)
    user_id = user["user_id"] if user else None

    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM projects WHERE project_id = $1", pid)
        if not exists:
            raise HTTPException(404, "Project not found")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large. Max {MAX_FILE_SIZE // (1024*1024)} MB")

    project_dir = DOCUMENTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    safe_name = file.filename.replace("/", "_").replace("\\", "_").replace("..", "_")
    file_path = project_dir / safe_name

    if file_path.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 1
        while file_path.exists():
            file_path = project_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        safe_name = file_path.name

    file_path.write_bytes(content)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO project_documents
                   (project_id, doc_type, title, filename, content_type,
                    size_bytes, storage_path, uploaded_by)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING doc_id, created_at""",
            pid, doc_type, title or safe_name, safe_name,
            file.content_type or "application/octet-stream",
            len(content), str(file_path.relative_to(DOCUMENTS_DIR)),
            user_id,
        )

    return {
        "doc_id": str(row["doc_id"]),
        "filename": safe_name,
        "doc_type": doc_type,
        "size_bytes": len(content),
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/{project_id}/documents")
async def list_documents(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """List all documents for a project."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT doc_id, doc_type, title, filename, content_type,
                      size_bytes, created_at
               FROM project_documents WHERE project_id = $1
               ORDER BY created_at DESC""",
            pid,
        )
    return [
        {
            "doc_id": str(r["doc_id"]),
            "doc_type": r["doc_type"],
            "title": r["title"],
            "filename": r["filename"],
            "content_type": r["content_type"],
            "size_bytes": r["size_bytes"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/documents/{doc_id}/download")
async def download_document(doc_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Download a document by ID."""
    did = UUID(doc_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT storage_path, filename, content_type FROM project_documents WHERE doc_id = $1",
            did,
        )
    if not row:
        raise HTTPException(404, "Document not found")

    file_path = DOCUMENTS_DIR / row["storage_path"]
    if not file_path.is_file():
        raise HTTPException(404, "File not found on disk")

    return FileResponse(
        path=str(file_path), filename=row["filename"], media_type=row["content_type"],
    )


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Delete a document."""
    did = UUID(doc_id)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM project_documents WHERE doc_id = $1 RETURNING storage_path", did,
        )
    if not row:
        raise HTTPException(404, "Document not found")

    file_path = DOCUMENTS_DIR / row["storage_path"]
    if file_path.is_file():
        file_path.unlink()

    return {"deleted": True, "doc_id": doc_id}


# ─────────────────────────────────────────────────────────────────────────────
# Candidate sites — distinct from project_sites junction. These are multi-criteria
# scored candidates used by the Sites tab (COA comparison) in the redesigned UI.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{project_id}/candidate-sites")
async def list_candidate_sites(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM project_candidate_sites
               WHERE project_id = $1
               ORDER BY is_preferred DESC, created_at ASC""",
            pid,
        )
    return {"project_id": project_id, "candidates": [_candidate_row(r) for r in rows]}


@router.post("/{project_id}/candidate-sites")
async def create_candidate_site(
    project_id: str,
    body: CandidateSiteRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM projects WHERE project_id = $1", pid)
        if not exists:
            raise HTTPException(404, "Project not found")
        row = await conn.fetchrow(
            """INSERT INTO project_candidate_sites
                   (project_id, name, lat, lon, capacity_mw, scores, lcoe, verdict, is_preferred)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
               RETURNING *""",
            pid, body.name, body.lat, body.lon, body.capacity_mw,
            json.dumps(body.scores or {}), body.lcoe, body.verdict, body.is_preferred,
        )
    return _candidate_row(row)


@router.patch("/{project_id}/candidate-sites/{candidate_id}")
async def update_candidate_site(
    project_id: str,
    candidate_id: str,
    body: CandidateSiteUpdate,
    pool: asyncpg.Pool = Depends(get_pool),
):
    cid = UUID(candidate_id)
    sets, params = [], []
    idx = 1
    for field in ("name", "lat", "lon", "capacity_mw", "lcoe", "verdict", "is_preferred"):
        v = getattr(body, field)
        if v is not None:
            sets.append(f"{field} = ${idx}")
            params.append(v); idx += 1
    if body.scores is not None:
        sets.append(f"scores = ${idx}::jsonb")
        params.append(json.dumps(body.scores)); idx += 1
    if not sets:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM project_candidate_sites WHERE candidate_id = $1", cid)
    else:
        params.append(cid)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE project_candidate_sites SET {', '.join(sets)} WHERE candidate_id = ${idx} RETURNING *",
                *params,
            )
    if not row:
        raise HTTPException(404, "Candidate site not found")
    return _candidate_row(row)


@router.delete("/{project_id}/candidate-sites/{candidate_id}")
async def delete_candidate_site(
    project_id: str,
    candidate_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    cid = UUID(candidate_id)
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM project_candidate_sites WHERE candidate_id = $1", cid
        )
    if res == "DELETE 0":
        raise HTTPException(404, "Candidate site not found")
    return {"deleted": candidate_id}


# ─── Godmode #8 — Project share-link (read-only public view) ──────────────

import hmac as _hmac
import hashlib as _hashlib
import base64 as _b64
import time as _time

_SHARE_SECRET = os.environ.get("PRINCEPS_SHARE_SECRET", "princeps-dev-secret-change-me").encode()


def _sign_share_token(project_id: str, expires_ts: int) -> str:
    payload = f"{project_id}.{expires_ts}".encode()
    sig = _hmac.new(_SHARE_SECRET, payload, _hashlib.sha256).digest()[:12]
    token = _b64.urlsafe_b64encode(payload + b"." + sig).decode().rstrip("=")
    return token


def _verify_share_token(token: str) -> str | None:
    try:
        pad = "=" * (-len(token) % 4)
        raw = _b64.urlsafe_b64decode(token + pad)
        # raw = project_id.expires_ts.sig
        project_id_b, expires_b, sig = raw.rsplit(b".", 2)
        project_id = project_id_b.decode()
        expires_ts = int(expires_b.decode())
        expected = _hmac.new(
            _SHARE_SECRET, f"{project_id}.{expires_ts}".encode(), _hashlib.sha256
        ).digest()[:12]
        if not _hmac.compare_digest(sig, expected):
            return None
        if _time.time() > expires_ts:
            return None
        return project_id
    except Exception:
        return None


class _ShareRequest(BaseModel):
    ttl_days: int = 30


@router.post("/{project_id}/share")
async def create_share_link(
    project_id: str,
    body: _ShareRequest | None = None,
):
    """Generate a signed read-only share token for a project.

    Token payload: `{project_id}.{expires_ts}.{hmac_sig[:12]}` base64url-encoded.
    Stateless — no DB writes. Verify via GET /api/public/share/{token}.
    """
    ttl = (body.ttl_days if body else 30)
    ttl = max(1, min(365, ttl))
    expires = int(_time.time()) + ttl * 86400
    token = _sign_share_token(project_id, expires)
    return {
        "token": token,
        "expires_at": expires,
        "path": f"/p/{token}",
    }


# The corresponding GET /api/public/share/{token} endpoint lives in grid.py's
# prefix-less router (it can't live here because this router has prefix
# /api/v1/projects). The helpers above are imported by grid.py.


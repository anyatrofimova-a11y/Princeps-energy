"""Assessment snapshots — versioned decisions with evidence."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import asyncpg

from app.deps import get_pool, get_current_user, get_optional_user

router = APIRouter(prefix="/api/v1/assessments", tags=["assessments"])


class SnapshotCreateRequest(BaseModel):
    parcel_id: str
    project_id: str | None = None
    label: str | None = None


class EvidenceRequest(BaseModel):
    evidence_type: str
    title: str | None = None
    content_ref: str | None = None
    content_data: dict | None = None


class NoteRequest(BaseModel):
    text: str


@router.post("/snapshot")
async def create_snapshot(
    body: SnapshotCreateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Create an assessment snapshot from current site state + linked analyses."""
    parcel_id = UUID(body.parcel_id)
    project_id = UUID(body.project_id) if body.project_id else None
    user_id = user["user_id"] if user else None

    async with pool.acquire() as conn:
        # Get next version
        max_ver = await conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM assessment_snapshots WHERE parcel_id = $1",
            parcel_id,
        )
        version = max_ver + 1

        # Gather current site data
        site_row = await conn.fetchrow(
            """SELECT p.area_m2, p.nearest_substation_id, p.distance_to_sub_km,
                      p.nearest_sub_capacity_kw,
                      ST_Y(ST_Transform(p.centroid, 4326)) AS lat,
                      ST_X(ST_Transform(p.centroid, 4326)) AS lon
               FROM parcels p WHERE p.parcel_id = $1""",
            parcel_id,
        )
        if not site_row:
            raise HTTPException(404, "Parcel not found")

        site_data = {
            "area_m2": float(site_row["area_m2"]) if site_row["area_m2"] else None,
            "lat": float(site_row["lat"]) if site_row["lat"] else None,
            "lon": float(site_row["lon"]) if site_row["lon"] else None,
            "distance_to_sub_km": float(site_row["distance_to_sub_km"]) if site_row["distance_to_sub_km"] else None,
        }

        # Gather latest agent analyses for this parcel
        analyses = await conn.fetch(
            """SELECT intent, verdict, confidence, summary
               FROM agent_analyses WHERE parcel_id = $1
               ORDER BY created_at DESC""",
            parcel_id,
        )
        intent_verdicts = {}
        for a in analyses:
            intent = a["intent"]
            if intent not in intent_verdicts:
                intent_verdicts[intent] = {
                    "verdict": a["verdict"],
                    "confidence": a["confidence"],
                    "summary": a["summary"],
                }

        # Compute overall verdict
        verdicts = [v["verdict"] for v in intent_verdicts.values()]
        if "NO-GO" in verdicts:
            overall = "NO-GO"
        elif "CAUTION" in verdicts:
            overall = "CAUTION"
        elif verdicts:
            overall = "GO"
        else:
            overall = None

        confidences = [v["confidence"] for v in intent_verdicts.values() if v["confidence"]]
        overall_conf = sum(confidences) / len(confidences) if confidences else None

        row = await conn.fetchrow(
            """INSERT INTO assessment_snapshots
                   (parcel_id, project_id, user_id, version, label,
                    overall_verdict, overall_confidence, intent_verdicts, site_data)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
               RETURNING snapshot_id, version, created_at""",
            parcel_id, project_id, user_id, version,
            body.label or f"Assessment v{version}",
            overall, overall_conf,
            json.dumps(intent_verdicts), json.dumps(site_data),
        )

    return {
        "snapshot_id": str(row["snapshot_id"]),
        "version": row["version"],
        "overall_verdict": overall,
        "overall_confidence": overall_conf,
        "intent_count": len(intent_verdicts),
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/{parcel_id}")
async def list_snapshots(parcel_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """List all snapshots for a site, ordered by version."""
    pid = UUID(parcel_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT snapshot_id, version, label, overall_verdict, overall_confidence,
                      created_at
               FROM assessment_snapshots WHERE parcel_id = $1
               ORDER BY version DESC""",
            pid,
        )
    return [
        {
            "snapshot_id": str(r["snapshot_id"]),
            "version": r["version"],
            "label": r["label"],
            "overall_verdict": r["overall_verdict"],
            "overall_confidence": r["overall_confidence"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/snapshot/{snapshot_id}")
async def get_snapshot(snapshot_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Full snapshot with evidence."""
    sid = UUID(snapshot_id)
    async with pool.acquire() as conn:
        snap = await conn.fetchrow(
            """SELECT * FROM assessment_snapshots WHERE snapshot_id = $1""", sid
        )
        if not snap:
            raise HTTPException(404, "Snapshot not found")

        evidence = await conn.fetch(
            """SELECT evidence_id, evidence_type, title, content_ref, content_data, created_at
               FROM assessment_evidence WHERE snapshot_id = $1
               ORDER BY created_at""",
            sid,
        )

    return {
        "snapshot_id": str(snap["snapshot_id"]),
        "parcel_id": str(snap["parcel_id"]),
        "project_id": str(snap["project_id"]) if snap["project_id"] else None,
        "version": snap["version"],
        "label": snap["label"],
        "overall_verdict": snap["overall_verdict"],
        "overall_confidence": snap["overall_confidence"],
        "intent_verdicts": json.loads(snap["intent_verdicts"]) if snap["intent_verdicts"] else {},
        "site_data": json.loads(snap["site_data"]) if snap["site_data"] else {},
        "metadata": json.loads(snap["metadata"]) if snap["metadata"] else {},
        "created_at": snap["created_at"].isoformat(),
        "evidence": [
            {
                "evidence_id": str(e["evidence_id"]),
                "evidence_type": e["evidence_type"],
                "title": e["title"],
                "content_ref": e["content_ref"],
                "content_data": json.loads(e["content_data"]) if e["content_data"] else None,
                "created_at": e["created_at"].isoformat(),
            }
            for e in evidence
        ],
    }


@router.post("/snapshot/{snapshot_id}/evidence")
async def attach_evidence(
    snapshot_id: str,
    body: EvidenceRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Attach evidence to a snapshot."""
    sid = UUID(snapshot_id)
    user_id = user["user_id"] if user else None
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM assessment_snapshots WHERE snapshot_id = $1", sid
        )
        if not exists:
            raise HTTPException(404, "Snapshot not found")

        row = await conn.fetchrow(
            """INSERT INTO assessment_evidence
                   (snapshot_id, evidence_type, title, content_ref, content_data, created_by)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING evidence_id, created_at""",
            sid, body.evidence_type, body.title, body.content_ref,
            json.dumps(body.content_data) if body.content_data else None,
            user_id,
        )
    return {
        "evidence_id": str(row["evidence_id"]),
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/compare/{snapshot_a}/{snapshot_b}")
async def compare_snapshots(
    snapshot_a: str,
    snapshot_b: str,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Diff two snapshots."""
    sid_a, sid_b = UUID(snapshot_a), UUID(snapshot_b)
    async with pool.acquire() as conn:
        a = await conn.fetchrow("SELECT * FROM assessment_snapshots WHERE snapshot_id = $1", sid_a)
        b = await conn.fetchrow("SELECT * FROM assessment_snapshots WHERE snapshot_id = $1", sid_b)
        if not a or not b:
            raise HTTPException(404, "One or both snapshots not found")

    iv_a = json.loads(a["intent_verdicts"]) if a["intent_verdicts"] else {}
    iv_b = json.loads(b["intent_verdicts"]) if b["intent_verdicts"] else {}

    diff = {
        "verdict_changed": a["overall_verdict"] != b["overall_verdict"],
        "verdict_a": a["overall_verdict"],
        "verdict_b": b["overall_verdict"],
        "confidence_delta": (b["overall_confidence"] or 0) - (a["overall_confidence"] or 0),
        "intents_added": [k for k in iv_b if k not in iv_a],
        "intents_removed": [k for k in iv_a if k not in iv_b],
        "intents_changed": [
            k for k in iv_a if k in iv_b and iv_a[k].get("verdict") != iv_b[k].get("verdict")
        ],
    }

    # Store comparison
    user_id = user["user_id"] if user else None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO assessment_comparisons (snapshot_a, snapshot_b, diff_data, created_by)
               VALUES ($1, $2, $3, $4)
               RETURNING comparison_id""",
            sid_a, sid_b, json.dumps(diff), user_id,
        )

    return {
        "comparison_id": str(row["comparison_id"]),
        "snapshot_a": {"id": snapshot_a, "version": a["version"], "label": a["label"]},
        "snapshot_b": {"id": snapshot_b, "version": b["version"], "label": b["label"]},
        "diff": diff,
    }


@router.post("/snapshot/{snapshot_id}/note")
async def add_note(
    snapshot_id: str,
    body: NoteRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Add a note to a snapshot (stored as evidence of type 'note')."""
    sid = UUID(snapshot_id)
    user_id = user["user_id"] if user else None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO assessment_evidence
                   (snapshot_id, evidence_type, title, content_data, created_by)
               VALUES ($1, 'note', 'Note', $2, $3)
               RETURNING evidence_id, created_at""",
            sid, json.dumps({"text": body.text}), user_id,
        )
    return {"evidence_id": str(row["evidence_id"]), "created_at": row["created_at"].isoformat()}


@router.get("/projects/{project_id}")
async def project_assessments(
    project_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """All assessment snapshots across all sites in a project."""
    pid = UUID(project_id)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT s.snapshot_id, s.parcel_id, s.version, s.label,
                      s.overall_verdict, s.overall_confidence, s.created_at
               FROM assessment_snapshots s
               WHERE s.project_id = $1
               ORDER BY s.created_at DESC""",
            pid,
        )
    return {
        "project_id": project_id,
        "snapshots": [
            {
                "snapshot_id": str(r["snapshot_id"]),
                "parcel_id": str(r["parcel_id"]),
                "version": r["version"],
                "label": r["label"],
                "overall_verdict": r["overall_verdict"],
                "overall_confidence": r["overall_confidence"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
    }

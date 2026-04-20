"""Project ontology object — backed by ``projects`` table.

Actions: create, advance_stage, set_verdict, archive, link_site.
Heavy logic lives in app/routers/projects.py; actions here are thin
wrappers that keep mutations auditable through the dispatch layer.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .base import ActionResult, ObjectNotFound


def _parse_jsonb(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            return json.loads(value) or {}
        except Exception:
            return {}
    return dict(value)

TYPE = "project"
VALID_STAGES = ["prospect", "scoping", "screened", "grid_applied", "grid_offer",
                "planning", "fid", "construction", "energised", "archived"]
VALID_VERDICTS = ["GO", "CAUTION", "NO-GO"]


@dataclass(frozen=True)
class Project:
    id: str
    type: str = TYPE
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def load_from_db(cls, pool, id: str) -> "Project":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT project_id, name, stage, verdict, status, technology, "
                "capacity_mw, metadata FROM projects WHERE project_id = $1::uuid",
                id,
            )
        if not row:
            raise ObjectNotFound(f"project:{id}")
        meta = _parse_jsonb(row["metadata"])
        meta.update({
            "name": row["name"], "stage": row["stage"], "verdict": row["verdict"],
            "status": row["status"], "technology": row["technology"],
            "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] else None,
        })
        return cls(id=str(row["project_id"]), metadata=meta)

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "metadata": self.metadata}


# ── Action input schemas ────────────────────────────────────────────────────

class CreateArgs(BaseModel):
    name: str
    technology: str | None = None
    capacity_mw: float | None = None
    stage: str = "prospect"


class AdvanceStageArgs(BaseModel):
    to_stage: str = Field(..., description="Target stage")
    notes: str | None = None


class SetVerdictArgs(BaseModel):
    verdict: str
    blocker: str | None = None


class LinkSiteArgs(BaseModel):
    parcel_id: str


class ArchiveArgs(BaseModel):
    reason: str | None = None


# ── Action handlers ─────────────────────────────────────────────────────────

async def create(obj: Project | None, pool, **kwargs) -> ActionResult:
    args = CreateArgs(**kwargs)
    new_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO projects (project_id, name, technology, capacity_mw, stage) "
            "VALUES ($1::uuid, $2, $3, $4, $5)",
            new_id, args.name, args.technology, args.capacity_mw, args.stage,
        )
    return ActionResult(
        ok=True, object_key=f"{TYPE}:{new_id}",
        object_after={"id": new_id, "name": args.name, "stage": args.stage},
        provenance={"source": "ontology.project.create"},
    )


async def advance_stage(obj: Project, pool, **kwargs) -> ActionResult:
    args = AdvanceStageArgs(**kwargs)
    if args.to_stage not in VALID_STAGES:
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                            error=f"invalid stage: {args.to_stage}")
    from_stage = obj.metadata.get("stage")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE projects SET stage=$1, stage_entered_at=now(), updated_at=now() "
                "WHERE project_id=$2::uuid",
                args.to_stage, obj.id,
            )
            await conn.execute(
                "INSERT INTO project_stage_history (project_id, from_stage, to_stage, notes) "
                "VALUES ($1::uuid, $2, $3, $4)",
                obj.id, from_stage, args.to_stage, args.notes,
            )
    return ActionResult(
        ok=True, object_key=f"{TYPE}:{obj.id}",
        diff={"stage": {"from": from_stage, "to": args.to_stage}},
        object_after={"id": obj.id, "stage": args.to_stage},
        side_effects=[{"table": "project_stage_history", "op": "insert"}],
        provenance={"source": "ontology.project.advance_stage"},
    )


async def set_verdict(obj: Project, pool, **kwargs) -> ActionResult:
    args = SetVerdictArgs(**kwargs)
    if args.verdict not in VALID_VERDICTS:
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                            error=f"invalid verdict: {args.verdict}")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE projects SET verdict=$1, blocker=$2, updated_at=now() "
            "WHERE project_id=$3::uuid",
            args.verdict, args.blocker, obj.id,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        diff={"verdict": args.verdict, "blocker": args.blocker},
                        object_after={"id": obj.id, "verdict": args.verdict})


async def archive(obj: Project, pool, **kwargs) -> ActionResult:
    ArchiveArgs(**kwargs)  # validation only
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE projects SET status='archived', stage='archived', updated_at=now() "
            "WHERE project_id=$1::uuid",
            obj.id,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        object_after={"id": obj.id, "status": "archived"})


async def link_site(obj: Project, pool, **kwargs) -> ActionResult:
    args = LinkSiteArgs(**kwargs)
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO project_sites (project_id, parcel_id) "
                "VALUES ($1::uuid, $2::uuid) ON CONFLICT DO NOTHING",
                obj.id, args.parcel_id,
            )
        except Exception as e:
            return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}", error=str(e))
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        side_effects=[{"table": "project_sites", "parcel_id": args.parcel_id}])


ACTIONS = {
    "create": (create, CreateArgs, False),
    "advance_stage": (advance_stage, AdvanceStageArgs, True),
    "set_verdict": (set_verdict, SetVerdictArgs, True),
    "archive": (archive, ArchiveArgs, True),
    "link_site": (link_site, LinkSiteArgs, True),
}

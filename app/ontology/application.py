"""Planning Application ontology object — backed by ``planning_applications_submitted``.

Actions: draft, submit, respond_to_query, withdraw.
Uses its own submission-tracking table so we don't pollute the scraped
``planning_applications`` ingestion table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .base import ActionResult, ObjectNotFound

TYPE = "application"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS planning_applications_submitted (
    application_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     uuid REFERENCES projects(project_id) ON DELETE CASCADE,
    lpa            text,
    reference      text,
    status         text NOT NULL DEFAULT 'draft',
    drafted_at     timestamptz NOT NULL DEFAULT now(),
    submitted_at   timestamptz,
    decided_at     timestamptz,
    decision       text,
    payload        jsonb NOT NULL DEFAULT '{}'::jsonb,
    history        jsonb NOT NULL DEFAULT '[]'::jsonb
);
"""


async def _ensure_table(pool):
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)


@dataclass(frozen=True)
class Application:
    id: str
    type: str = TYPE
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def load_from_db(cls, pool, id: str) -> "Application":
        await _ensure_table(pool)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT application_id, project_id, lpa, reference, status, payload "
                "FROM planning_applications_submitted WHERE application_id = $1::uuid", id,
            )
        if not row:
            raise ObjectNotFound(f"application:{id}")
        meta = dict(row)
        meta["application_id"] = str(meta["application_id"])
        meta["project_id"] = str(meta["project_id"]) if meta["project_id"] else None
        return cls(id=str(row["application_id"]), metadata=meta)

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "metadata": self.metadata}


class DraftArgs(BaseModel):
    project_id: str
    lpa: str
    reference: str | None = None
    payload: dict[str, Any] | None = None


class SubmitArgs(BaseModel):
    confirm: bool = True


class RespondArgs(BaseModel):
    note: str
    attachments: list[str] | None = None


class WithdrawArgs(BaseModel):
    reason: str | None = None


async def draft(obj: Application | None, pool, **kwargs) -> ActionResult:
    args = DraftArgs(**kwargs)
    await _ensure_table(pool)
    new_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO planning_applications_submitted "
            "(application_id, project_id, lpa, reference, status, payload) "
            "VALUES ($1::uuid, $2::uuid, $3, $4, 'draft', $5::jsonb)",
            new_id, args.project_id, args.lpa, args.reference,
            __import__("json").dumps(args.payload or {}),
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{new_id}",
                        object_after={"id": new_id, "status": "draft", "lpa": args.lpa})


async def submit(obj: Application, pool, **kwargs) -> ActionResult:
    SubmitArgs(**kwargs)
    await _ensure_table(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE planning_applications_submitted SET status='submitted', "
            "submitted_at=now() WHERE application_id=$1::uuid", obj.id,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        diff={"status": {"from": obj.metadata.get("status"), "to": "submitted"}})


async def respond_to_query(obj: Application, pool, **kwargs) -> ActionResult:
    args = RespondArgs(**kwargs)
    await _ensure_table(pool)
    entry = {"note": args.note, "attachments": args.attachments or []}
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE planning_applications_submitted "
            "SET history = history || $1::jsonb WHERE application_id=$2::uuid",
            __import__("json").dumps([entry]), obj.id,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        side_effects=[{"history_append": entry}])


async def withdraw(obj: Application, pool, **kwargs) -> ActionResult:
    WithdrawArgs(**kwargs)
    await _ensure_table(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE planning_applications_submitted SET status='withdrawn', "
            "decided_at=now(), decision='withdrawn' WHERE application_id=$1::uuid", obj.id,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        diff={"status": "withdrawn"})


ACTIONS = {
    "draft": (draft, DraftArgs, True),
    "submit": (submit, SubmitArgs, True),
    "respond_to_query": (respond_to_query, RespondArgs, True),
    "withdraw": (withdraw, WithdrawArgs, True),
}

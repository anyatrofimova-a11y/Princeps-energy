"""Connector ontology object — backed by ``connectors_registry`` (BOT-G).

Actions: refresh, pause, health.
All operations guarded with IF EXISTS checks so the ontology loads cleanly
even if BOT-G has not shipped the table yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .base import ActionResult, ObjectNotFound

TYPE = "connector"


async def _table_exists(pool) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='connectors_registry'"
        )
    return bool(row)


@dataclass(frozen=True)
class Connector:
    id: str
    type: str = TYPE
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def load_from_db(cls, pool, id: str) -> "Connector":
        if not await _table_exists(pool):
            # Return an object skeleton so actions can return a consistent
            # "not_implemented: table missing" error without 500-ing.
            return cls(id=id, metadata={"table_missing": True})
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM connectors_registry WHERE connector_id = $1", id,
            )
        if not row:
            raise ObjectNotFound(f"connector:{id}")
        return cls(id=id, metadata=dict(row))

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "metadata": self.metadata}


class RefreshArgs(BaseModel):
    force: bool = False


class PauseArgs(BaseModel):
    reason: str | None = None


class HealthArgs(BaseModel):
    pass


async def refresh(obj: Connector, pool, **kwargs) -> ActionResult:
    RefreshArgs(**kwargs)
    if obj.metadata.get("table_missing"):
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                            error="not_implemented: connectors_registry table not created (BOT-G)")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE connectors_registry SET last_refresh_requested_at=now() "
            "WHERE connector_id=$1", obj.id,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        side_effects=[{"queued": "refresh"}])


async def pause(obj: Connector, pool, **kwargs) -> ActionResult:
    args = PauseArgs(**kwargs)
    if obj.metadata.get("table_missing"):
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                            error="not_implemented: connectors_registry table not created (BOT-G)")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE connectors_registry SET status='paused', pause_reason=$2 "
            "WHERE connector_id=$1", obj.id, args.reason,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        diff={"status": "paused", "reason": args.reason})


async def health(obj: Connector, pool, **kwargs) -> ActionResult:
    HealthArgs(**kwargs)
    if obj.metadata.get("table_missing"):
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                            error="not_implemented: connectors_registry table not created (BOT-G)")
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        object_after={"id": obj.id,
                                      "status": obj.metadata.get("status"),
                                      "last_ok_at": str(obj.metadata.get("last_ok_at"))})


ACTIONS = {
    "refresh": (refresh, RefreshArgs, False),
    "pause": (pause, PauseArgs, True),
    "health": (health, HealthArgs, False),
}

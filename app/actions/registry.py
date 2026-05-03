"""Typed action registry — the Foundry "Action Type" pattern in Pydantic.

Lifecycle of an action call:

    1. Caller (REST endpoint or agent tool call) provides {action_id, params}
    2. Registry resolves to the concrete ActionType subclass
    3. Pydantic validates params
    4. ActionType.preview(ctx) — optional dry-run; returns description only
    5. ActionType.execute(ctx) — atomic ontology mutation + side effects
    6. Audit log is appended (rid, user, params, result_summary, ts)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

from pydantic import BaseModel

log = logging.getLogger("princeps.actions")


@dataclass
class ActionContext:
    """Carries request-scoped resources to the action. Not a FastAPI Request —
    deliberately decoupled so actions are testable without an HTTP layer.
    """
    user_id: str | None
    tenant_id: str | None
    pool: Any = None              # asyncpg pool
    request: Any = None           # FastAPI Request (when available)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    ok: bool
    summary: str
    rid: str
    side_effects: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


class ActionType(BaseModel):
    """Subclass per action. Override ``execute()`` (and optionally ``preview()``).

    Example::

        class RunFeasibility(ActionType):
            ACTION_ID: ClassVar[str] = "run_feasibility"
            site_rid: str
            scenario: Literal["base","optimistic","stress"] = "base"
            async def execute(self, ctx: ActionContext) -> ActionResult:
                ...
    """

    ACTION_ID: ClassVar[str] = ""

    async def preview(self, ctx: ActionContext) -> str:
        return f"Run {self.ACTION_ID} with {self.model_dump()}"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        raise NotImplementedError(f"{type(self).__name__}.execute() not implemented")


class ActionRegistry:
    def __init__(self):
        self._actions: dict[str, type[ActionType]] = {}

    def register(self, action_id: str, cls: type[ActionType]) -> None:
        if not action_id:
            raise ValueError("action_id must be non-empty")
        if action_id in self._actions:
            raise ValueError(f"action {action_id!r} already registered")
        cls.ACTION_ID = action_id
        self._actions[action_id] = cls
        log.debug("registered action %s -> %s", action_id, cls.__name__)

    def get(self, action_id: str) -> type[ActionType]:
        if action_id not in self._actions:
            raise KeyError(f"unknown action: {action_id!r}")
        return self._actions[action_id]

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "id": aid,
                "class": cls.__name__,
                "schema": cls.model_json_schema(),
                "doc": (cls.__doc__ or "").strip(),
            }
            for aid, cls in sorted(self._actions.items())
        ]

    async def invoke(self, action_id: str, params: dict, ctx: ActionContext, *,
                     preview: bool = False) -> ActionResult | str:
        cls = self.get(action_id)
        instance = cls.model_validate(params)
        rid = f"rid.princeps.action_call.{uuid.uuid4()}"
        if preview:
            return await instance.preview(ctx)
        log.info("invoke action=%s rid=%s user=%s", action_id, rid, ctx.user_id)
        result = await instance.execute(ctx)
        result.rid = rid
        await _audit(ctx, action_id, params, result)
        return result


registry = ActionRegistry()


def action(action_id: str):
    """Decorator: ``@action("run_feasibility")`` on an ActionType subclass."""
    def _wrap(cls):
        registry.register(action_id, cls)
        return cls
    return _wrap


async def _audit(ctx: ActionContext, action_id: str, params: dict, result: ActionResult) -> None:
    if ctx.pool is None:
        return
    try:
        async with ctx.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO action_audit_log
                    (rid, action_id, user_id, tenant_id, params, ok, summary, side_effects, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                """,
                result.rid, action_id, ctx.user_id, ctx.tenant_id,
                params, result.ok, result.summary, result.side_effects,
            )
    except Exception as exc:
        log.warning("action audit log insert failed: %s", exc)

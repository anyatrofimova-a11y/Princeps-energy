"""
Ontology primitives — Object, Action, Registry.

Design notes
------------
* ``Object`` is a shell around a DB row. It doesn't own the SQL — each
  object type provides its own ``fetch`` / ``save`` implementation —
  but it does own identity (``kind + id``), timestamps, and audit hooks.

* ``Action`` is the only legal mutation path. ``preview`` returns a
  structured diff; ``commit`` mutates + writes one row to
  ``ontology_action_log``. Preview and commit MUST share their logic so
  that "show me what would happen" cannot diverge from "do it".

* ``registry`` is populated at import time by ``@register`` decorators
  on action classes. Import order matters only in the sense that every
  action module must be imported somewhere before the registry is read
  — ``app.ontology`` does this via explicit sub-imports.

The registry intentionally exposes actions to three consumers:

    1. ``POST /api/actions/dispatch`` — the UI clicks an action button.
    2. ``app.chat`` — Claude gets actions as tool-use schemas and can
       invoke them by name, seeing only actions it's permitted to call.
    3. Any Python code — ``await registry["Project.advance_stage"]
       .commit(pool, **payload)`` is a one-liner from anywhere.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

from pydantic import BaseModel, Field

log = logging.getLogger("princeps.ontology")


# ── Errors ──────────────────────────────────────────────────────────────────


class ObjectNotFound(LookupError):
    """Raised when fetch() cannot resolve a kind+id."""


class ActionForbidden(PermissionError):
    """Raised when an action's precondition check rejects the caller.

    Not the same as a validation error — validation errors are Pydantic-
    shaped and surfaced as 422s by FastAPI.
    """


# ── Object base ─────────────────────────────────────────────────────────────


@dataclass
class Object:
    """Base class for typed domain objects.

    Subclasses must set ``kind`` (class attribute) and implement
    ``fetch`` + ``save``. Everything else — identity, logging, action
    routing — is shared.
    """

    kind: ClassVar[str] = "object"

    id: str
    data: dict[str, Any] = field(default_factory=dict)

    # ── identity / serialisation ─────────────────────────────────────────────

    def key(self) -> str:
        """Globally unique handle used in logs, chat tool calls, and URLs."""
        return f"{self.kind}:{self.id}"

    def to_dict(self) -> dict:
        return {"kind": self.kind, "id": self.id, **self.data}

    # ── DB contract (subclasses override) ────────────────────────────────────

    @classmethod
    async def fetch(cls, pool, id: str) -> "Object":
        raise NotImplementedError

    async def save(self, pool) -> None:
        raise NotImplementedError


# ── Action base ─────────────────────────────────────────────────────────────


@dataclass
class ActionResult:
    """Return payload of ``preview()`` and ``commit()``.

    ``preview`` sets ``committed=False`` and fills ``diff`` with what
    *would* change. ``commit`` sets ``committed=True`` and fills
    ``committed_object`` with the post-mutation state.
    """

    ok: bool
    object_key: str
    diff: dict[str, Any] = field(default_factory=dict)
    committed: bool = False
    committed_object: dict[str, Any] | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "object_key": self.object_key,
            "diff": self.diff,
            "committed": self.committed,
            "committed_object": self.committed_object,
            "reason": self.reason,
        }


class Action:
    """Base class for typed, auditable mutations on an object.

    Subclasses set ``name`` (``"<ObjectKind>.<verb>"``) and ``Input``
    (a Pydantic model). They then implement:

      * ``async def _preview(self, pool, input) -> ActionResult``
        — compute the diff without writing.

      * ``async def _commit(self, pool, input) -> ActionResult``
        — write the mutation inside a transaction.

    The base class wraps both with audit-log writes and a call count
    instrument. Chat / REST / Python callers all go through
    ``self.preview(...)`` / ``self.commit(...)``.
    """

    name: ClassVar[str] = "Object.verb"
    summary: ClassVar[str] = ""             # 1-line human description for tool-use docs
    requires_review: ClassVar[bool] = False  # True → UI must show preview + confirm
    Input: ClassVar[type[BaseModel]]

    # ── Public API ───────────────────────────────────────────────────────────

    async def preview(self, pool, **kwargs) -> ActionResult:
        obj_kind, _ = self.name.split(".", 1)
        try:
            payload = self.Input(**kwargs)
        except Exception as e:
            return ActionResult(ok=False, object_key=f"{obj_kind}:?", reason=f"invalid input: {e}")
        try:
            return await self._preview(pool, payload)
        except ObjectNotFound as e:
            return ActionResult(ok=False, object_key=f"{obj_kind}:?", reason=f"not found: {e}")
        except ActionForbidden as e:
            return ActionResult(ok=False, object_key=f"{obj_kind}:?", reason=f"forbidden: {e}")

    async def commit(self, pool, *, actor: str | None = None, **kwargs) -> ActionResult:
        obj_kind, _ = self.name.split(".", 1)
        try:
            payload = self.Input(**kwargs)
        except Exception as e:
            return ActionResult(ok=False, object_key=f"{obj_kind}:?", reason=f"invalid input: {e}")

        run_id = str(uuid.uuid4())
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    result = await self._commit_inner(conn, payload)
                    await self._log(
                        conn, run_id=run_id, actor=actor, ok=result.ok,
                        payload=payload, result=result,
                    )
            return result
        except ObjectNotFound as e:
            await _safe_log(pool, run_id, actor, self.name, False, kwargs, str(e))
            return ActionResult(ok=False, object_key=f"{obj_kind}:?", reason=f"not found: {e}")
        except ActionForbidden as e:
            await _safe_log(pool, run_id, actor, self.name, False, kwargs, str(e))
            return ActionResult(ok=False, object_key=f"{obj_kind}:?", reason=f"forbidden: {e}")
        except Exception:
            log.exception("action.commit_failed name=%s run_id=%s", self.name, run_id)
            await _safe_log(pool, run_id, actor, self.name, False, kwargs, "unhandled exception")
            raise

    # ── Subclass hooks ───────────────────────────────────────────────────────

    async def _preview(self, pool, input: BaseModel) -> ActionResult:
        raise NotImplementedError

    async def _commit(self, conn, input: BaseModel) -> ActionResult:
        """Run inside an open transaction (conn). Override this, not commit()."""
        raise NotImplementedError

    async def _commit_inner(self, conn, payload: BaseModel) -> ActionResult:
        """Shim so transactional subclass implementations can stay simple."""
        return await self._commit(conn, payload)

    # ── Audit ────────────────────────────────────────────────────────────────

    async def _log(
        self,
        conn,
        *,
        run_id: str,
        actor: str | None,
        ok: bool,
        payload: BaseModel,
        result: ActionResult,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO ontology_action_log (
                run_id, action_name, actor, ok, object_key,
                input_json, diff_json, result_json, recorded_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, now())
            """,
            run_id,
            self.name,
            actor,
            ok,
            result.object_key,
            payload.model_dump_json(),
            json.dumps(result.diff, default=str),
            json.dumps(result.to_dict(), default=str),
        )

    # ── Introspection for tool-use schemas ──────────────────────────────────

    @classmethod
    def tool_schema(cls) -> dict:
        """Anthropic tool-use schema for this action. Used by chat."""
        return {
            "name": cls.name.replace(".", "__"),
            "description": cls.summary or cls.name,
            "input_schema": cls.Input.model_json_schema(),
        }


# ── Registry ────────────────────────────────────────────────────────────────


registry: dict[str, Action] = {}


def register(action_cls: type[Action]) -> type[Action]:
    """Decorator. Instantiates the action and stores it by name."""
    instance = action_cls()
    if action_cls.name in registry:
        raise RuntimeError(f"duplicate action registered: {action_cls.name}")
    registry[action_cls.name] = instance
    log.debug("ontology.register %s", action_cls.name)
    return action_cls


# ── Safe fallback logger ────────────────────────────────────────────────────


async def _safe_log(
    pool, run_id: str, actor: str | None, action_name: str,
    ok: bool, input_kwargs: dict, reason: str,
) -> None:
    """Write an audit row even when the main transaction was rolled back."""
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ontology_action_log (
                    run_id, action_name, actor, ok, object_key,
                    input_json, diff_json, result_json, recorded_at
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, '{}'::jsonb, $7::jsonb, now())
                """,
                run_id, action_name, actor, ok, "unknown",
                json.dumps(input_kwargs, default=str),
                json.dumps({"reason": reason}),
            )
    except Exception:
        log.exception("ontology: even the fallback log failed for %s", action_name)

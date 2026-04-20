"""Dispatch layer — routes ``(object_type, action_name)`` to the handler.

The public surface is:

  * ``OBJECTS`` — type string → dataclass (each with ``load_from_db``)
  * ``ACTIONS`` — type string → {action_name: (handler, InputModel, needs_object)}
  * ``dispatch(pool, object_type, object_id, action_name, actor, args)``

``dispatch`` is what the REST router and future agent loops call. It
handles: object load, arg validation (via the handler's own Pydantic
model), timing, and audit-log writes to ``ontology_action_log``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .base import ActionResult, ObjectNotFound
from . import project as project_mod
from . import site as site_mod
from . import substation as substation_mod
from . import layout as layout_mod
from . import application as application_mod
from . import tender as tender_mod
from . import connector as connector_mod

log = logging.getLogger("princeps.ontology.dispatch")

OBJECTS = {
    "project": project_mod.Project,
    "site": site_mod.Site,
    "substation": substation_mod.Substation,
    "layout": layout_mod.Layout,
    "application": application_mod.Application,
    "tender": tender_mod.Tender,
    "connector": connector_mod.Connector,
}

ACTIONS = {
    "project": project_mod.ACTIONS,
    "site": site_mod.ACTIONS,
    "substation": substation_mod.ACTIONS,
    "layout": layout_mod.ACTIONS,
    "application": application_mod.ACTIONS,
    "tender": tender_mod.ACTIONS,
    "connector": connector_mod.ACTIONS,
}


def catalog() -> dict[str, list[str]]:
    """Return ``{object_type: [action_name, ...]}`` — used by chat/agent."""
    return {otype: list(amap.keys()) for otype, amap in ACTIONS.items()}


async def _log_action(
    pool, *, object_type: str, object_id: str, action: str, actor: str | None,
    ok: bool, args: dict, result: ActionResult, started_utc, completed_utc,
    duration_ms: int, error: str | None,
) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ontology_action_log (
                    object_type, object_id, action, actor, ok,
                    args_json, result_json, error, duration_ms,
                    started_utc, completed_utc
                ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9,$10,$11)
                """,
                object_type, object_id, action, actor, ok,
                json.dumps(args, default=str),
                json.dumps(result.to_dict(), default=str),
                error, duration_ms, started_utc, completed_utc,
            )
    except Exception:
        log.exception("ontology.dispatch: audit log write failed "
                      "object=%s:%s action=%s", object_type, object_id, action)


async def dispatch(
    pool,
    object_type: str,
    object_id: str,
    action_name: str,
    *,
    actor: str | None = None,
    args: dict[str, Any] | None = None,
) -> ActionResult:
    """Load → validate → execute → audit. Returns an ``ActionResult``."""
    args = args or {}
    started = time.time()
    from datetime import datetime, timezone
    started_utc = datetime.now(timezone.utc)

    if object_type not in ACTIONS:
        return ActionResult(ok=False, object_key=f"{object_type}:{object_id}",
                            error=f"unknown_object_type: {object_type}")
    action_map = ACTIONS[object_type]
    if action_name not in action_map:
        return ActionResult(ok=False, object_key=f"{object_type}:{object_id}",
                            error=f"unknown_action: {object_type}.{action_name}")

    handler, InputModel, needs_object = action_map[action_name]

    # Validate args up front so we return 422-like errors before DB load.
    try:
        InputModel(**args)
    except Exception as e:
        dur = int((time.time() - started) * 1000)
        result = ActionResult(ok=False, object_key=f"{object_type}:{object_id}",
                              error=f"invalid_args: {e}", duration_ms=dur)
        await _log_action(pool, object_type=object_type, object_id=object_id,
                          action=action_name, actor=actor, ok=False, args=args,
                          result=result, started_utc=started_utc,
                          completed_utc=datetime.now(timezone.utc),
                          duration_ms=dur, error=result.error)
        return result

    # Load object when required.
    obj = None
    if needs_object:
        try:
            obj = await OBJECTS[object_type].load_from_db(pool, object_id)
        except ObjectNotFound as e:
            dur = int((time.time() - started) * 1000)
            result = ActionResult(ok=False,
                                  object_key=f"{object_type}:{object_id}",
                                  error=f"not_found: {e}", duration_ms=dur)
            await _log_action(pool, object_type=object_type, object_id=object_id,
                              action=action_name, actor=actor, ok=False, args=args,
                              result=result, started_utc=started_utc,
                              completed_utc=datetime.now(timezone.utc),
                              duration_ms=dur, error=result.error)
            return result

    # Execute.
    try:
        result = await handler(obj, pool, **args)
    except Exception as e:
        log.exception("ontology.dispatch: handler raised %s:%s.%s",
                      object_type, object_id, action_name)
        dur = int((time.time() - started) * 1000)
        result = ActionResult(ok=False, object_key=f"{object_type}:{object_id}",
                              error=f"handler_exception: {e}", duration_ms=dur)

    result.duration_ms = int((time.time() - started) * 1000)
    completed_utc = datetime.now(timezone.utc)
    await _log_action(pool, object_type=object_type, object_id=object_id,
                      action=action_name, actor=actor, ok=result.ok, args=args,
                      result=result, started_utc=started_utc,
                      completed_utc=completed_utc,
                      duration_ms=result.duration_ms, error=result.error)
    return result

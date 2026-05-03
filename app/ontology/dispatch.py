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

# Lowercase ontology type → DTDL label used in graph_nodes. Drives the
# graph_sync hook + cardinality trigger. Falls back to capitalised type
# when not declared here.
_TYPE_TO_LABEL = {
    "project": "Project",
    "site": "Site",
    "substation": "Substation",
    "layout": "Layout",
    "application": "Application",
    "tender": "Tender",
    "connector": "Connector",
}


async def _sync_to_graph(pool, object_type: str, object_id: str) -> None:
    """Mirror the affected object into ``graph_nodes`` after a successful
    action so the auto-emit trigger fires + the Cypher shim sees the
    latest state. Best-effort — never surfaces to the caller.

    The trigger ``trg_graph_nodes_emit`` writes an ``ObjectMutated`` row
    to ``ontology_action_log`` automatically; we don't repeat that here.
    """
    if object_type not in OBJECTS:
        return
    label = _TYPE_TO_LABEL.get(object_type, object_type.capitalize())
    rid = f"rid.princeps.{object_type}.{object_id}"
    try:
        obj = await OBJECTS[object_type].load_from_db(pool, object_id)
    except ObjectNotFound:
        # Action may have archived/deleted — best-effort delete from graph
        try:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM graph_nodes WHERE rid = $1", rid)
        except Exception as exc:
            log.warning("graph_sync delete failed for %s: %s", rid, exc)
        return
    except Exception as exc:
        log.warning("graph_sync load failed for %s:%s: %s", object_type, object_id, exc)
        return

    props = getattr(obj, "metadata", None) or {}
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO graph_nodes (rid, label, props, updated_at)
                VALUES ($1, $2, $3::jsonb, NOW())
                ON CONFLICT (rid) DO UPDATE
                  SET label = EXCLUDED.label,
                      props = EXCLUDED.props,
                      updated_at = NOW()
                """,
                rid, label, json.dumps(props, default=str),
            )
    except Exception as exc:
        log.warning("graph_sync upsert failed for %s: %s", rid, exc)


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
    # Normalise object_id to the canonical rid form so this row joins
    # cleanly with auto-emitted ObjectMutated / EdgeMutated rows.
    rid = (
        object_id if str(object_id).startswith("rid.princeps.")
        else f"rid.princeps.{object_type}.{object_id}"
    )
    # Use the DTDL-style label as object_type for consistency.
    label = _TYPE_TO_LABEL.get(object_type, object_type.capitalize() if object_type else "unknown")
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
                label, rid, action, actor, ok,
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

    # Mirror the affected object into graph_nodes so:
    #   1. the auto-emit trigger writes a fine-grained ObjectMutated row
    #      (with before/after props) to ontology_action_log
    #   2. the Cypher shim + graph endpoints see the latest state
    # Only on successful actions — failed handlers leave the graph alone.
    if result.ok:
        await _sync_to_graph(pool, object_type, object_id)

    return result

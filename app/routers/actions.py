"""REST surface for the typed Action Registry (Swarm 8).

Endpoints:
  GET  /api/actions                    — list all registered actions + JSON schemas
  GET  /api/actions/{action_id}/schema — schema for one action
  POST /api/actions/{action_id}        — execute action (body = params dict)
  POST /api/actions/{action_id}/preview — preview without executing

The agent layer (app/chat.py / app/agent.py) discovers tools via
``GET /api/actions`` and surfaces them as Claude tools. UI components
(workshop/ActionButton.jsx) call POST /api/actions/{id}.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

# Import side-effect: registers all @action-decorated types.
import app.actions.types  # noqa: F401
from app.actions import ActionContext, ActionResult, registry

log = logging.getLogger("princeps.actions_router")

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("")
async def list_actions():
    return {"actions": registry.list()}


@router.get("/{action_id}/schema")
async def get_schema(action_id: str):
    try:
        cls = registry.get(action_id)
    except KeyError:
        raise HTTPException(404, f"unknown action: {action_id}")
    return {"id": action_id, "class": cls.__name__,
            "schema": cls.model_json_schema(), "doc": (cls.__doc__ or "").strip()}


@router.post("/{action_id}")
async def execute_action(action_id: str, body: dict, request: Request):
    ctx = _ctx(request)
    try:
        result = await registry.invoke(action_id, body, ctx)
    except KeyError:
        raise HTTPException(404, f"unknown action: {action_id}")
    except ValidationError as ve:
        raise HTTPException(400, {"validation_errors": ve.errors()})
    if not isinstance(result, ActionResult):
        raise HTTPException(500, "invoke returned a non-ActionResult; preview path leaked")
    return _serialise(result)


@router.post("/{action_id}/preview")
async def preview_action(action_id: str, body: dict, request: Request):
    ctx = _ctx(request)
    try:
        preview = await registry.invoke(action_id, body, ctx, preview=True)
    except KeyError:
        raise HTTPException(404, f"unknown action: {action_id}")
    except ValidationError as ve:
        raise HTTPException(400, {"validation_errors": ve.errors()})
    return {"preview": preview}


def _ctx(request: Request) -> ActionContext:
    return ActionContext(
        user_id=getattr(request.state, "user_id", None),
        tenant_id=getattr(request.state, "tenant_id", None),
        pool=request.app.state.pool,
        request=request,
    )


def _serialise(r: ActionResult) -> dict:
    return {
        "ok": r.ok, "rid": r.rid, "summary": r.summary,
        "side_effects": r.side_effects, "payload": r.payload,
    }

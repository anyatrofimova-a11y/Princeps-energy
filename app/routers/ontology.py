"""REST surface for the ontology dispatch layer.

Endpoints
---------
* ``GET  /api/ontology/catalog``
    Discover registered objects and actions.

* ``POST /api/ontology/{object_type}/{object_id}/{action_name}``
    Dispatch an action. Body is the action's Pydantic args.

* ``GET  /api/ontology/{object_type}/{object_id}``
    Hydrate an object (useful for UI preview before action dispatch).

* ``GET  /api/ontology/log``
    Recent audit entries; filter by object / action.

The router is deliberately thin — all policy lives in
``app.ontology.dispatch``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.deps import get_pool, get_optional_user
from app.ontology import dispatch as ont_dispatch
from app.ontology.base import ObjectNotFound

log = logging.getLogger("princeps.routers.ontology")

router = APIRouter(prefix="/api/ontology", tags=["ontology"])


@router.get("/catalog")
async def catalog_endpoint():
    """Introspection — what objects and actions exist today."""
    return {"objects": ont_dispatch.catalog()}


@router.get("/{object_type}/{object_id}")
async def get_object(object_type: str, object_id: str, pool=Depends(get_pool)):
    if object_type not in ont_dispatch.OBJECTS:
        raise HTTPException(404, f"unknown object type: {object_type}")
    try:
        obj = await ont_dispatch.OBJECTS[object_type].load_from_db(pool, object_id)
    except ObjectNotFound as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"load_failed: {e}")
    return obj.to_dict()


@router.post("/{object_type}/{object_id}/{action_name}")
async def dispatch_action(
    object_type: str,
    object_id: str,
    action_name: str,
    request: Request,
    pool=Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Dispatch ``(object_type, object_id, action_name)`` with JSON body args."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")

    actor = None
    if user and isinstance(user, dict):
        actor = str(user.get("user_id") or user.get("email") or "")
    elif user:
        actor = str(getattr(user, "user_id", None) or getattr(user, "email", ""))

    result = await ont_dispatch.dispatch(
        pool, object_type, object_id, action_name,
        actor=actor, args=body,
    )
    return result.to_dict()


@router.get("/log")
async def log_endpoint(
    object_type: str | None = Query(None),
    object_id: str | None = Query(None),
    action: str | None = Query(None),
    limit: int = Query(50, le=500),
    pool=Depends(get_pool),
):
    """Recent ontology action log, most recent first."""
    where: list[str] = []
    params: list[Any] = []
    if object_type:
        params.append(object_type)
        where.append(f"object_type = ${len(params)}")
    if object_id:
        params.append(object_id)
        where.append(f"object_id = ${len(params)}")
    if action:
        params.append(action)
        where.append(f"action = ${len(params)}")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    sql = (
        "SELECT log_id, object_type, object_id, action, actor, ok, "
        "       args_json, result_json, error, duration_ms, "
        "       started_utc, completed_utc "
        f"FROM ontology_action_log {clause} "
        f"ORDER BY started_utc DESC LIMIT ${len(params)}"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [{k: (str(v) if k.endswith("_utc") or k == "log_id" else v)
             for k, v in dict(r).items()} for r in rows]

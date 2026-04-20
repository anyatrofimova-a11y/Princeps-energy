"""
app/enterprise/acl.py — tenant-aware access control (Task #13).

Exposes a FastAPI dependency factory :func:`require_tenant_access` that can
be bolted onto any route to guarantee the authenticated user has the
required role in the tenant that owns the resource being operated on.

Usage
-----

::

    from app.enterprise.acl import require_tenant_access

    @router.get("/api/projects/{project_id}/secret")
    async def secret(
        project_id: UUID,
        _ = Depends(require_tenant_access(
            resource_type="project",
            resource_id_param="project_id",
            min_role="member",
        )),
    ):
        ...

Semantics
---------
* If the resource's ``tenant_id`` is NULL (legacy single-tenant row), the
  dependency returns ``"legacy"`` without blocking. Enforcement switches on
  once backfill is complete.
* If the resource does not exist, returns 404 — this is intentional to avoid
  leaking tenant topology to unauthenticated probes.
* If the user has no membership in the owning tenant, returns 403.
* If the user has a membership below the required role rank, returns 403.
* The dependency returns a small dict (``{tenant_id, role}``) that the route
  can use to audit-log or drive UI state.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request
import asyncpg

from app.deps import get_current_user, get_pool
from app.enterprise.tenants import (
    Role,
    get_user_role,
    role_at_least,
    tenant_for_resource,
)

log = logging.getLogger("princeps.enterprise.acl")


def require_tenant_access(
    *,
    resource_type: str,
    resource_id_param: str,
    min_role: Role = "member",
) -> Callable:
    """Return a FastAPI dependency that enforces tenant membership + role.

    Parameters
    ----------
    resource_type
        Logical resource kind. Must be one of the keys registered in
        ``tenants._RESOURCE_TENANT_QUERY``. Passing an unknown kind results
        in a 500 at request time, which is the correct failure mode — wiring
        a route against an unregistered resource type is a dev-time bug.
    resource_id_param
        Name of the path / query / body parameter carrying the resource
        identifier. The dependency looks it up on ``request.path_params``.
    min_role
        Minimum role the caller must hold in the tenant that owns the
        resource. Total ordering: ``owner > admin > member > viewer``.
    """

    async def _dep(
        request: Request,
        pool: asyncpg.Pool = Depends(get_pool),
        user = Depends(get_current_user),
    ) -> dict[str, Any]:
        resource_id = request.path_params.get(resource_id_param)
        if resource_id is None:
            # Also check query params and JSON body (best-effort).
            resource_id = request.query_params.get(resource_id_param)
        if resource_id is None:
            raise HTTPException(
                status_code=400,
                detail=f"Missing path/query param '{resource_id_param}'",
            )

        try:
            resource_uuid = UUID(str(resource_id))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid resource id")

        tenant_id = await tenant_for_resource(
            pool,
            resource_type=resource_type,
            resource_id=resource_uuid,
        )

        # Legacy single-tenant row — pass through without enforcement until
        # the backfill is complete. Application code can tighten this later
        # by setting PRINCEPS_ACL_STRICT=true.
        if tenant_id is None:
            import os
            if os.getenv("PRINCEPS_ACL_STRICT", "false").lower() == "true":
                raise HTTPException(status_code=404, detail="Resource not found")
            log.debug(
                "ACL bypass (legacy): %s/%s has no tenant_id",
                resource_type, resource_uuid,
            )
            return {"tenant_id": None, "role": "legacy", "user_id": str(user["user_id"])}

        role = await get_user_role(
            pool,
            tenant_id=UUID(tenant_id),
            user_id=UUID(str(user["user_id"])),
        )
        if not role:
            raise HTTPException(status_code=403, detail="Not a member of this tenant")

        if not role_at_least(role, min_role):
            raise HTTPException(
                status_code=403,
                detail=f"Requires role >= {min_role} (current: {role})",
            )

        return {
            "tenant_id": tenant_id,
            "role": role,
            "user_id": str(user["user_id"]),
        }

    return _dep


async def assert_tenant_access(
    pool: asyncpg.Pool,
    *,
    user_id: str | UUID,
    tenant_id: str | UUID,
    min_role: Role = "member",
) -> str:
    """Imperative form for code paths that aren't FastAPI routes (workers,
    chat tool calls). Returns the caller's role on success; raises
    ``PermissionError`` otherwise.
    """
    role = await get_user_role(pool, tenant_id=tenant_id, user_id=user_id)
    if not role:
        raise PermissionError("Not a member of this tenant")
    if not role_at_least(role, min_role):
        raise PermissionError(f"Requires role >= {min_role} (current: {role})")
    return role


__all__ = ["require_tenant_access", "assert_tenant_access"]

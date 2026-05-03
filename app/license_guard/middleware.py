"""FastAPI middleware that enforces the license registry at the response boundary.

This is defense-in-depth — the primary check is the per-call
``assert_commercial_safe(artifact_id)`` invocation inside each inference path.
The middleware catches anything that leaked through.

How inference paths integrate:

    from fastapi import Request
    from app.license_guard import record_artifact_use, assert_commercial_safe

    @router.get("/api/forecast/demand")
    async def demand(request: Request, gsp: str):
        assert_commercial_safe("timesfm_weights")        # raises if NC
        record_artifact_use(request, "timesfm_weights")  # tag for middleware

For a research-only endpoint (NC artifacts allowed), use the
``/api/research/...`` or ``/api/internal/validation/...`` prefix; the
middleware skips enforcement on those paths.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.license_guard.audit import record_artifact_use as _record_use  # noqa: F401  (re-export for back-compat)
from app.license_guard.registry import get_license, get_policies

logger = logging.getLogger("princeps.license_guard")


class LicenseGuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._policies = get_policies()

    async def dispatch(self, request: Request, call_next):
        is_research = any(
            request.url.path.startswith(p) for p in self._policies.research_path_prefixes
        )
        request.state.commercial_context = not is_research
        request.state.license_artifacts_used = set()

        response = await call_next(request)

        if not request.state.commercial_context:
            return response

        used: set[str] = getattr(request.state, "license_artifacts_used", set())
        blocked: list[dict] = []
        for aid in used:
            lic = get_license(aid)
            if not lic.commercial_use:
                blocked.append(
                    {
                        "artifact_id": aid,
                        "license": lic.license,
                        "source": lic.source,
                        "alternative": lic.alternative,
                    }
                )

        if blocked:
            logger.error(
                "license_guard: blocked commercial response on %s using %s",
                request.url.path,
                [b["artifact_id"] for b in blocked],
            )
            raise HTTPException(
                status_code=451,
                detail={
                    "error": "license_blocked",
                    "message": (
                        "Response was generated using non-commercial artifacts on a "
                        "commercial endpoint. Move to a /api/research/... path or "
                        "swap to a commercial-safe alternative."
                    ),
                    "artifacts": blocked,
                },
            )

        return response


# record_artifact_use lives in app/license_guard/audit.py to keep it
# importable from non-FastAPI venvs. Re-exported above for back-compat.

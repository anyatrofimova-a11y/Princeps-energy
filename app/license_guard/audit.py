"""Audit primitives for the license guard.

Lives separately from middleware.py so that callers in non-FastAPI venvs
(.venv-forecast, .venv-grid, .venv-sam) can record artifact usage without
pulling FastAPI.

The `request` argument is duck-typed: anything with a `.state` attribute
that exposes (mutable) attribute storage will work — FastAPI Request,
SimpleNamespace, or a test stub.
"""

from __future__ import annotations


def record_artifact_use(request, artifact_id: str) -> None:
    """Tag an artifact as used by this request.

    Reading side: LicenseGuardMiddleware inspects request.state.license_artifacts_used
    on the way out and blocks the response if any artifact is non-commercial
    on a commercial endpoint.
    """
    if request is None:
        return
    used = getattr(request.state, "license_artifacts_used", None)
    if used is None:
        used = set()
        request.state.license_artifacts_used = used
    used.add(artifact_id)

"""Princeps License Guard.

Hard-block at the API boundary for non-commercial-licensed artifacts on
commercial endpoints. See :mod:`app.license_guard.registry` for the
registered artifacts and :mod:`app.license_guard.middleware` for the
FastAPI middleware.

Public surface:

    assert_commercial_safe("graphcast_weights")  # raises LicenseBlockedError
    record_artifact_use(request, "timesfm_weights")
    LicenseGuardMiddleware  # add to FastAPI app

In ``app/main.py``::

    from app.license_guard import LicenseGuardMiddleware
    app.add_middleware(LicenseGuardMiddleware)

The FastAPI middleware is loaded lazily on attribute access so callers
in non-FastAPI venvs (.venv-forecast, .venv-grid, .venv-sam) can use
the registry + audit functions without installing FastAPI.
"""

from app.license_guard.audit import record_artifact_use
from app.license_guard.registry import (
    ArtifactLicense,
    LicenseBlockedError,
    Policies,
    assert_commercial_safe,
    get_license,
    get_policies,
    is_commercial_safe,
    list_artifacts,
)


def __getattr__(name):
    # Lazy-load the FastAPI middleware only when explicitly imported.
    if name == "LicenseGuardMiddleware":
        from app.license_guard.middleware import LicenseGuardMiddleware as _M
        return _M
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ArtifactLicense",
    "LicenseBlockedError",
    "LicenseGuardMiddleware",
    "Policies",
    "assert_commercial_safe",
    "get_license",
    "get_policies",
    "is_commercial_safe",
    "list_artifacts",
    "record_artifact_use",
]

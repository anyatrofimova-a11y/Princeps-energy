"""Princeps FastAPI middleware bundle.

Public surface:

    from app.middleware import TenantJWTMiddleware

Wired in ``app/main.py`` after the existing CORS + SecurityHeaders chain.
"""

from app.middleware.tenant_jwt import TenantJWTMiddleware

__all__ = ["TenantJWTMiddleware"]

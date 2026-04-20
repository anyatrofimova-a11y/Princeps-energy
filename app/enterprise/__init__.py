"""
app/enterprise — Princeps enterprise readiness scaffolding (Task #13).

Ships the foundations that utility / hyperscaler / DNO procurement flat-out
require before they will sign a contract:

* ``sso``           — OIDC SSO (Google / Azure / Okta / generic OIDC) with
                      per-tenant IdP configuration and JIT provisioning.
* ``tenants``       — multi-tenant primitives: ``tenants`` + ``tenant_memberships``
                      tables, plus additive ``tenant_id`` columns on isolatable
                      resources.
* ``acl``           — FastAPI dependency ``require_tenant_access`` that returns
                      403 unless the caller has the required role in the tenant
                      that owns the resource.
* ``audit_log``     — ASGI middleware that captures every request and writes a
                      structured entry to ``audit_log_v2`` asynchronously
                      (fire-and-forget; never blocks).
* ``trust_center``  — ``/api/trust`` router returning MVP-credible
                      certifications / subprocessors / DPA / security-report
                      responses.
* ``encryption``    — AES-GCM helpers for the SSO ``client_secret`` field.

External ISO 27001 / SOC 2 engagement is a separate 3-6 month track; this
module is the in-app surface that those audits will map onto.

All features are gated behind explicit env flags so existing dev / test flows
continue to work unchanged:

* ``PRINCEPS_AUDIT_ENABLED``     — turn on the audit middleware (default off).
* ``PRINCEPS_SSO_ENABLED``       — turn on the SSO endpoints (default off).
* ``PRINCEPS_ENCRYPTION_KEY``    — base64-encoded 32-byte AES-GCM key. Required
                                   only when SSO is enabled.
"""

from __future__ import annotations

__all__ = [
    "sso",
    "tenants",
    "acl",
    "audit_log",
    "trust_center",
    "encryption",
]

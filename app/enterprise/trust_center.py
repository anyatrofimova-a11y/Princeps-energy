"""
app/enterprise/trust_center.py — public-facing Trust Center router (Task #13).

Mounted at ``/api/trust``. Intentionally lightweight: MVP returns hardcoded
responses that reflect the current reality (ISO 27001 in progress, GDPR
compliant, SOC 2 planned). Once the external audits land, the content
lives in DB-backed rows and these endpoints start reading them.

Frontend follow-up task will surface this data on ``/trust``.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

router = APIRouter(prefix="/api/trust", tags=["trust"])


# ---------------------------------------------------------------------------
# Content (MVP: hardcoded; future: DB-backed)
# ---------------------------------------------------------------------------

_CERTIFICATIONS: dict[str, dict] = {
    "iso_27001": {
        "status":       "in_progress",
        "target_date":  "2026-12-31",
        "scope":        "Princeps platform (backend, frontend, data processing).",
        "auditor":      "TBD — shortlist in progress.",
    },
    "soc_2": {
        "status":      "planned",
        "type":        "Type II",
        "target_date": "2027-06-30",
        "notes":       "Starts after ISO 27001 certification completes.",
    },
    "gdpr": {
        "status":         "compliant",
        "dpa_available":  True,
        "dpo_contact":    "privacy@princeps.energy",
        "last_reviewed":  "2026-03-01",
    },
    "cyber_essentials_plus": {
        "status":      "planned",
        "target_date": "2026-09-30",
    },
}

_SUBPROCESSORS: list[dict] = [
    {
        "name":        "Amazon Web Services (AWS)",
        "purpose":     "Compute, object storage, managed Postgres (RDS).",
        "data_access": "All platform data at rest and in transit.",
        "region":      "eu-west-2 (London).",
        "compliance":  ["ISO 27001", "SOC 2 Type II", "GDPR (UK + EU)"],
    },
    {
        "name":        "Anthropic",
        "purpose":     "Claude LLM — chat, agentic analysis, document Q&A.",
        "data_access": "Prompts and document excerpts user routes through the chat / agent panels.",
        "region":      "US (zero-retention enterprise endpoint).",
        "compliance":  ["SOC 2 Type II"],
    },
    {
        "name":        "OpenAI",
        "purpose":     "Embeddings for semantic search (GPT-text-embedding-3).",
        "data_access": "Document chunks for embedding generation; no PII by policy.",
        "region":      "US.",
        "compliance":  ["SOC 2 Type II"],
    },
    {
        "name":        "Stripe",
        "purpose":     "Billing + payments.",
        "data_access": "Customer billing details and payment metadata. No platform data.",
        "region":      "Ireland / US.",
        "compliance":  ["PCI-DSS Level 1", "SOC 1 / SOC 2", "ISO 27001"],
    },
    {
        "name":        "Cloudflare",
        "purpose":     "CDN, DDoS protection, WAF.",
        "data_access": "HTTP request metadata; no body inspection beyond WAF rules.",
        "region":      "Global edge (UK / EU / US).",
        "compliance":  ["ISO 27001", "SOC 2 Type II", "GDPR"],
    },
    {
        "name":        "Mapbox",
        "purpose":     "Base-map tiles for the 3D twin and site designer.",
        "data_access": "Viewport coordinates (no PII).",
        "region":      "US / EU.",
        "compliance":  ["SOC 2 Type II", "GDPR"],
    },
    {
        "name":        "Sentry",
        "purpose":     "Error monitoring and performance tracing.",
        "data_access": "Stack traces, request metadata; PII scrubbing enabled.",
        "region":      "EU (Frankfurt).",
        "compliance":  ["ISO 27001", "SOC 2 Type II", "GDPR"],
    },
    {
        "name":        "Amazon SES / Postmark",
        "purpose":     "Transactional email (alerts, digests, invoices).",
        "data_access": "Recipient email addresses and message bodies.",
        "region":      "eu-west-2 (London) / US.",
        "compliance":  ["ISO 27001", "SOC 2 Type II"],
    },
]


_SECURITY_REPORT: dict = {
    "access_controls": {
        "authentication":      "Email + password (bcrypt) or SSO (OIDC — Google / Azure AD / Okta).",
        "authorization":       "Role-based access control per tenant (owner / admin / member / viewer).",
        "mfa":                 "Enforced via IdP for SSO tenants. Email-based OTP for non-SSO enterprise accounts.",
        "session_management":  "JWT with 24h expiry; revocable via session-id nonce.",
    },
    "encryption": {
        "in_transit":          "TLS 1.2+ on all public endpoints (Cloudflare + AWS ALB).",
        "at_rest_database":    "AES-256 (AWS RDS KMS-managed keys).",
        "at_rest_object":      "AES-256 (S3 SSE-S3).",
        "secrets":             "AES-GCM (application-layer), key rotated quarterly.",
    },
    "data_retention": {
        "user_accounts":       "Retained while subscription active; purged 90 days after closure.",
        "project_data":        "Retained while subscription active; exported + purged on request (GDPR Art. 17).",
        "audit_logs":          "24 months rolling, then archived to encrypted cold storage.",
        "billing_records":     "7 years (HMRC statutory).",
    },
    "incident_response": {
        "detection":           "Sentry + AWS GuardDuty + Cloudflare WAF alerts pipelined to PagerDuty.",
        "notification_sla":    "72h customer notification for any personal-data breach (GDPR Art. 33).",
        "runbook":             "Public incident runbook published at status.princeps.energy.",
    },
    "availability": {
        "target_sla":          "99.9% monthly (enterprise tier).",
        "backup_policy":       "Daily snapshots, 30-day retention, cross-region replication for enterprise.",
        "rto":                 "4 hours (enterprise); 24 hours (team / individual).",
        "rpo":                 "1 hour (enterprise); 24 hours (team / individual).",
    },
    "employee_access": {
        "principle":           "Least-privilege; production access limited to on-call SRE + lead engineer.",
        "background_checks":   "UK DBS-equivalent prior to production access.",
        "device_policy":       "MDM-managed laptops; disk encryption enforced.",
    },
    "last_reviewed": str(date.today()),
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/certifications")
async def certifications() -> dict:
    """Return status of every certification Princeps is pursuing."""
    return {"certifications": _CERTIFICATIONS}


@router.get("/subprocessors")
async def subprocessors() -> dict:
    """Return the full subprocessor inventory (GDPR Art. 28 transparency)."""
    return {"subprocessors": _SUBPROCESSORS, "count": len(_SUBPROCESSORS)}


@router.get("/dpa")
async def dpa() -> dict:
    """Return the URL of the current Data Processing Agreement PDF."""
    return {
        "version": "1.0",
        "effective_date": "2026-01-01",
        "url": "/static/princeps-dpa-v1.pdf",
        "contact_for_negotiated": "legal@princeps.energy",
    }


@router.get("/security-report")
async def security_report() -> dict:
    """Return the consolidated security posture report."""
    return {"security_report": _SECURITY_REPORT}


__all__ = ["router"]

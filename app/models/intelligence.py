"""
app/models/intelligence.py — Pydantic v2 models for the Phase 7a Intelligence schema.

One-to-one with the tables declared in
``app/migrations/0001_intelligence_schema.sql``. These models are the canonical
shape for rows as they flow between asyncpg, the ingester bots, the router
layer and the frontend. They are also used to validate inbound payloads for
create / update endpoints.

Conventions
-----------
- Optional columns in SQL become ``| None`` with a default of ``None``.
- ``jsonb`` columns become ``dict[str, Any]`` or ``list[Any]``.
- ``uuid``/``timestamptz``/``date`` use stdlib types.
- ``geometry`` / ``geography`` columns are serialised as GeoJSON-shaped dicts
  on the wire; at the DB boundary the routers are expected to
  ``ST_AsGeoJSON`` / ``ST_GeomFromGeoJSON`` as they already do elsewhere in
  the codebase. We carry them here as ``dict | None`` to stay transport-agnostic.
- ``vector(1536)`` embeddings become ``list[float] | None``.
- ``text[]`` arrays become ``list[str]``.

The ``CHECK`` enums from the DDL are mirrored as ``Literal[...]`` types so
Pydantic rejects invalid values before they ever hit Postgres.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Shared enum-ish literal aliases (mirrors CHECK constraints) ─────────────

AuthorityType = Literal[
    "regulator", "authority", "lpa", "dno", "to", "gso",
    "statutory_consultee", "appeal_body", "community", "ngo",
    "political", "legal", "industry_body", "lender", "devolved", "crown",
]

Jurisdiction = Literal["E", "W", "S", "NI", "GB", "UK", "EU"]

CaseType = Literal[
    "nsip_dco", "lpa_planning", "section36", "scottish_dns",
    "ofgem_consultation", "ofgem_decision", "code_mod", "cfd_round",
    "cm_auction", "riio_control", "dno_connection_case", "appeal",
    "call_in", "cma_appeal", "judicial_review", "hse_comah", "ea_permit",
    "cmp", "gc", "cusc", "bsc_pmod", "dcusa_dcp", "stc", "misc",
]

Industry = Literal[
    "electricity", "gas", "hydrogen", "heat", "interconnector", "other",
]

DocketStage = Literal[
    "pre_app", "acceptance", "pre_examination", "examination",
    "recommendation", "decision", "challenge", "post_consent",
    "made", "withdrawn", "suspended", "closed",
]

StakeholderRole = Literal[
    "applicant", "co_applicant", "spv", "statutory_consultee",
    "regulator", "network_operator", "lpa", "parish_council",
    "county_council", "consumer_body", "industry_body", "objector",
    "supporter", "interested_party", "government_agency", "political",
    "legal_rep", "technical_reviewer", "lender", "neutral", "intervenor",
    "consultee",
]

StakeholderPosition = Literal[
    "for", "against", "conditions", "neutral", "unknown", "withdrawn",
]

AlertCadence = Literal[
    "realtime", "daily", "weekday",
    "weekly_mon", "weekly_tue", "weekly_wed", "weekly_thu", "weekly_fri",
    "biweekly", "monthly",
]

WatchCadence = Literal["realtime", "daily", "weekly", "on_deadline"]

PriceTier = Literal["free", "individual", "team", "enterprise"]

PinRole = Literal["evidence", "precedent", "constraint", "counterfactual"]


# ── Base config ─────────────────────────────────────────────────────────────

class _Base(BaseModel):
    """Shared Pydantic config for all intelligence-schema models."""

    model_config = ConfigDict(
        from_attributes=True,       # allow instantiation from asyncpg.Record
        populate_by_name=True,
        arbitrary_types_allowed=False,
    )


# ── AUTHORITIES ─────────────────────────────────────────────────────────────

class Authority(_Base):
    """Row of ``authorities``."""

    id: UUID | None = None
    slug: str
    name: str
    acronym: str | None = None
    type: AuthorityType
    jurisdiction: Jurisdiction
    home_url: str | None = None
    logo_url: str | None = None
    api_available: bool = False
    geometry: dict[str, Any] | None = None  # GeoJSON
    created_at: datetime | None = None


# ── DOCKETS ─────────────────────────────────────────────────────────────────

class Docket(_Base):
    """Row of ``dockets``."""

    docket_id: UUID | None = None
    source: str
    source_docket_id: str | None = None
    publisher_id: UUID | None = None
    title: str
    description: str | None = None
    case_type: CaseType | None = None
    industry: Industry | None = None
    status: str | None = None
    stage: DocketStage | None = None
    applicant_name: str | None = None
    account_name: str | None = None
    statutory_deadline: date | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    geometry: dict[str, Any] | None = None
    exec_summary_text: str | None = None
    exec_summary_cached_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── DOCUMENTS ───────────────────────────────────────────────────────────────

class Document(_Base):
    """Row of ``documents``."""

    doc_id: UUID | None = None
    source: str
    source_url: str
    docket_id: UUID | None = None
    commission_authority: str | None = None
    filing_type: str | None = None
    procedural_stage: str | None = None
    title: str
    body_text: str | None = None
    body_pdf_path: str | None = None
    pages: int | None = None
    published_at: datetime | None = None
    ingested_at: datetime | None = None
    topic_tags: dict[str, Any] | list[Any] | None = None
    extracted_fields: dict[str, Any] | None = None
    embedding: list[float] | None = None
    geometry: dict[str, Any] | None = None  # GeoJSON Point
    stakeholder_id: UUID | None = None
    # tsv is a generated column — read-only from Python's perspective, excluded from writes.
    tsv: str | None = Field(default=None, exclude=True)
    created_at: datetime | None = None


# ── STAKEHOLDERS ────────────────────────────────────────────────────────────

class Stakeholder(_Base):
    """Row of ``stakeholders``."""

    id: UUID | None = None
    docket_id: UUID
    authority_id: UUID | None = None
    company_number: str | None = None
    person_name: str | None = None
    display_name: str
    role: StakeholderRole
    position: StakeholderPosition = "unknown"
    represented_by: UUID | None = None
    first_submission_at: datetime | None = None
    last_submission_at: datetime | None = None
    submission_count: int = 0
    created_at: datetime | None = None


# ── STAKEHOLDER_SUBMISSIONS ────────────────────────────────────────────────

class StakeholderSubmission(_Base):
    """Row of ``stakeholder_submissions``."""

    id: UUID | None = None
    stakeholder_id: UUID
    doc_id: UUID
    submission_type: str | None = None
    submitted_at: datetime
    position_change: str | None = None
    created_at: datetime | None = None


# ── DOCKET_TIMELINE_EVENTS ─────────────────────────────────────────────────

class DocketTimelineEvent(_Base):
    """Row of ``docket_timeline_events``."""

    id: UUID | None = None
    docket_id: UUID
    event_type: str
    event_at: date
    summary_text: str | None = None
    doc_id: UUID | None = None
    forward_looking: bool = False
    deadline_at: date | None = None
    created_at: datetime | None = None


# ── CONSULTEE_REQUIREMENTS ─────────────────────────────────────────────────

class ConsulteeRequirement(_Base):
    """Row of ``consultee_requirements``.

    ``trigger`` is a free-form JSONB blob; typical shape:
    ``{"geometry_pred": "within", "capacity_threshold_mw": 50,
       "tech": "solar", "proximity_km": 2, "buffer_m": 500}``.
    """

    id: UUID | None = None
    case_type: str
    trigger: dict[str, Any]
    authority_id: UUID
    mandatory: bool = True
    consultation_period_days: int | None = None
    statutory_basis: str | None = None
    reason_code: str | None = None
    draft_letter_slug: str | None = None
    created_at: datetime | None = None


# ── ALERT_DEFINITIONS ──────────────────────────────────────────────────────

class AlertDefinition(_Base):
    """Row of ``alert_definitions``."""

    id: UUID | None = None
    slug: str
    title: str
    description: str | None = None
    cluster: str | None = None
    source_filter: dict[str, Any]
    llm_prompt: str | None = None
    cadence: AlertCadence
    est_docs_per_digest: int | None = None
    icp_tags: list[str] = Field(default_factory=list)
    created_by: UUID | None = None
    is_public: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── ALERT_SUBSCRIPTIONS ────────────────────────────────────────────────────

class AlertSubscription(_Base):
    """Row of ``alert_subscriptions``."""

    id: UUID | None = None
    user_id: str
    alert_id: UUID
    delivery_channels: dict[str, Any] = Field(
        default_factory=lambda: {"email": True, "in_app": True, "slack": False}
    )
    pinned_project_id: UUID | None = None
    muted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── ALERT_DIGESTS ──────────────────────────────────────────────────────────

class AlertDigest(_Base):
    """Row of ``alert_digests``."""

    id: UUID | None = None
    alert_id: UUID
    run_at: datetime
    document_ids: list[UUID] = Field(default_factory=list)
    llm_extract: str | None = None
    llm_structured: dict[str, Any] | None = None
    sent_at: datetime | None = None
    created_at: datetime | None = None


# ── DATA_SUBSCRIPTIONS ─────────────────────────────────────────────────────

class DataSubscription(_Base):
    """Row of ``data_subscriptions``."""

    id: UUID | None = None
    slug: str
    title: str
    description: str | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    refresh_interval_hours: int = 24
    last_refreshed_at: datetime | None = None
    is_public: bool = False
    price_tier: PriceTier = "enterprise"
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ── DATA_SUBSCRIPTION_ROWS ─────────────────────────────────────────────────

class DataSubscriptionRow(_Base):
    """Row of ``data_subscription_rows``."""

    id: UUID | None = None
    subscription_id: UUID
    external_id: str | None = None
    row: dict[str, Any]
    geom: dict[str, Any] | None = None   # GeoJSON
    added_at: datetime | None = None
    removed_at: datetime | None = None
    changed_fields: dict[str, Any] | None = None
    created_at: datetime | None = None


# ── DOCUMENT_PROJECT_PINS ──────────────────────────────────────────────────

class DocumentProjectPin(_Base):
    """Row of ``document_project_pins``."""

    id: UUID | None = None
    project_id: UUID
    doc_id: UUID
    pinned_by: str
    role: PinRole = "evidence"
    note: str | None = None
    created_at: datetime | None = None


# ── PROJECT_DOCKET_PINS ────────────────────────────────────────────────────

class ProjectDocketPin(_Base):
    """Row of ``project_docket_pins`` (composite PK: project_id + docket_id)."""

    project_id: UUID
    docket_id: UUID
    pinned_by: str
    note: str | None = None
    agent_verdict_impact: dict[str, Any] | None = None
    created_at: datetime | None = None


# ── DOCKET_WATCHES ─────────────────────────────────────────────────────────

class DocketWatch(_Base):
    """Row of ``docket_watches``."""

    id: UUID | None = None
    user_id: str
    docket_id: UUID
    cadence: WatchCadence = "daily"
    channels: dict[str, Any] = Field(
        default_factory=lambda: {"email": True, "in_app": True, "slack": False}
    )
    filters: dict[str, Any] | None = None
    created_at: datetime | None = None


# ── DOCKET_QA_CACHE ────────────────────────────────────────────────────────

class DocketQaCache(_Base):
    """Row of ``docket_qa_cache``."""

    id: UUID | None = None
    docket_id: UUID
    question: str
    answer: str
    citations: dict[str, Any] | list[Any] | None = None
    generated_at: datetime | None = None


# ── Exports ─────────────────────────────────────────────────────────────────

__all__ = [
    # enum literals
    "AuthorityType", "Jurisdiction", "CaseType", "Industry", "DocketStage",
    "StakeholderRole", "StakeholderPosition", "AlertCadence", "WatchCadence",
    "PriceTier", "PinRole",
    # models
    "Authority",
    "Docket",
    "Document",
    "Stakeholder",
    "StakeholderSubmission",
    "DocketTimelineEvent",
    "ConsulteeRequirement",
    "AlertDefinition",
    "AlertSubscription",
    "AlertDigest",
    "DataSubscription",
    "DataSubscriptionRow",
    "DocumentProjectPin",
    "ProjectDocketPin",
    "DocketWatch",
    "DocketQaCache",
]

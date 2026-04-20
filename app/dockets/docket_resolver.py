"""
app/dockets/docket_resolver.py — source -> docket_id mapping.

Every document that lands in ``documents`` can be associated with a single
proceeding. This module implements the "which docket?" decision for each
upstream source (PINS, Ofgem, LPAs, NESO, ECU, PEDW …) and upserts the
row when it hasn't been seen before.

Used by the ingestion bots (other agent) to pre-group documents before
they hit the router layer.

The mapping logic is deliberately declarative — each source has a
``source_docket_id`` extraction rule plus a default title / case_type
classifier. If the ingester already passes those in, we use them
verbatim; otherwise we infer.

Source registry
---------------
- ``pins``          : EN010XXX / EN020XXX / EN030XXX / EN040XXX / EN070XXX
- ``ofgem``         : CMP### / GC### / BSC-P### / CUSC-CMP### / DCUSA-DCP### / STC###
- ``lpa``           : ``{lpa_code}:{app_id}``
- ``neso``          : gate2_cohort_ids (e.g. GATE2-2026-Q1-####)
- ``ecu``           : ECU00001234
- ``pedw``          : DNS/NNNN/NNNN
- ``daera_ni``      : NI-EN/#####
- ``cfd``           : AR{n} round identifier
- ``cm``            : T-{year}-{round}
- ``custom``        : virtual docket, caller supplies id
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

import asyncpg

log = logging.getLogger("princeps.dockets.docket_resolver")


# ── ID pattern matchers ─────────────────────────────────────────────────

_PINS_RE      = re.compile(r"EN0\d{5}", re.IGNORECASE)
_OFGEM_CMP_RE = re.compile(r"CMP\d{2,4}",   re.IGNORECASE)
_OFGEM_GC_RE  = re.compile(r"GC\d{3,4}",    re.IGNORECASE)
_OFGEM_BSC_RE = re.compile(r"BSC-?P\d{2,4}",re.IGNORECASE)
_OFGEM_CUSC_RE= re.compile(r"CUSC-?CMP\d+", re.IGNORECASE)
_OFGEM_DCUSA_RE= re.compile(r"DCUSA-?DCP\d+",re.IGNORECASE)
_OFGEM_STC_RE = re.compile(r"STC\d+",       re.IGNORECASE)
_ECU_RE       = re.compile(r"ECU\d{8}",     re.IGNORECASE)
_PEDW_RE      = re.compile(r"DNS/\d{4}/\d{4}", re.IGNORECASE)
_NESO_GATE2_RE= re.compile(r"GATE2-\d{4}-Q[1-4]-\d{1,4}", re.IGNORECASE)
_CFD_RE       = re.compile(r"AR[1-9]\d*",   re.IGNORECASE)
_CM_RE        = re.compile(r"T-\d{4}-\d",   re.IGNORECASE)


# ── Case-type inference by source ──────────────────────────────────────

_SOURCE_DEFAULT_CASE_TYPE: dict[str, str] = {
    "pins":     "nsip_dco",
    "ofgem":    "ofgem_consultation",  # caller may override to code_mod / cmp / etc.
    "lpa":      "lpa_planning",
    "ecu":      "section36",
    "pedw":     "scottish_dns",  # Welsh DNS uses the same enum per spec
    "neso":     "dno_connection_case",
    "daera_ni": "lpa_planning",
    "cfd":      "cfd_round",
    "cm":       "cm_auction",
    "custom":   "misc",
}


def _extract_source_docket_id(source: str, metadata: dict[str, Any]) -> str | None:
    """Try hard to pull a stable external ID from metadata first, then
    regex-scan candidate fields as a fallback."""
    # Explicit wins.
    for key in ("source_docket_id", "docket_id", "case_ref", "case_id",
                "project_id", "ref", "id", "reference"):
        val = metadata.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # LPA composite key: need both lpa_code + app_id.
    if source == "lpa":
        lpa = metadata.get("lpa_code") or metadata.get("lpa")
        app = metadata.get("app_id") or metadata.get("application_id")
        if lpa and app:
            return f"{lpa}:{app}"

    # Regex sweep across title / description / url.
    haystack_parts: list[str] = []
    for key in ("title", "description", "source_url", "url", "subject"):
        val = metadata.get(key)
        if isinstance(val, str):
            haystack_parts.append(val)
    haystack = " ".join(haystack_parts)

    if source == "pins":
        m = _PINS_RE.search(haystack)
        if m: return m.group(0).upper()
    if source == "ofgem":
        for rx in (_OFGEM_CMP_RE, _OFGEM_GC_RE, _OFGEM_BSC_RE,
                   _OFGEM_CUSC_RE, _OFGEM_DCUSA_RE, _OFGEM_STC_RE):
            m = rx.search(haystack)
            if m: return m.group(0).upper()
    if source == "ecu":
        m = _ECU_RE.search(haystack)
        if m: return m.group(0).upper()
    if source == "pedw":
        m = _PEDW_RE.search(haystack)
        if m: return m.group(0).upper()
    if source == "neso":
        m = _NESO_GATE2_RE.search(haystack)
        if m: return m.group(0).upper()
    if source == "cfd":
        m = _CFD_RE.search(haystack)
        if m: return m.group(0).upper()
    if source == "cm":
        m = _CM_RE.search(haystack)
        if m: return m.group(0).upper()

    return None


def _infer_case_type(source: str, metadata: dict[str, Any]) -> str:
    """Resolve the case_type. Explicit metadata overrides the per-source
    default; Ofgem is further split by the source_docket_id prefix."""
    explicit = metadata.get("case_type")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    src = (source or "").lower()
    if src == "ofgem":
        sdid = (metadata.get("source_docket_id") or "").upper()
        if sdid.startswith("CMP"):        return "cmp"
        if sdid.startswith("GC"):         return "gc"
        if sdid.startswith("BSC"):        return "bsc_pmod"
        if sdid.startswith("CUSC"):       return "cusc"
        if sdid.startswith("DCUSA"):      return "dcusa_dcp"
        if sdid.startswith("STC"):        return "stc"
        return "ofgem_consultation"
    return _SOURCE_DEFAULT_CASE_TYPE.get(src, "misc")


async def _resolve_docket_id(
    conn: asyncpg.Connection,
    source: str,
    metadata: dict[str, Any],
) -> UUID:
    """Return the docket UUID for a (source, metadata) pair, creating the
    row if it doesn't exist.

    ``metadata`` is the ingester's grab-bag: title, url, case_ref, geometry,
    applicant_name, status, stage, opened_at, statutory_deadline, etc.
    """
    if not source:
        raise ValueError("docket_resolver: source is required")

    source = source.lower().strip()
    source_docket_id = _extract_source_docket_id(source, metadata)

    # Try to find an existing row by (source, source_docket_id) first.
    if source_docket_id:
        row = await conn.fetchrow(
            """SELECT docket_id FROM dockets
               WHERE source = $1 AND source_docket_id = $2""",
            source, source_docket_id,
        )
        if row:
            return row["docket_id"]

    # Otherwise fall back to title match within the same source (soft dedup).
    title = (metadata.get("title") or "").strip()
    if source_docket_id is None and title:
        row = await conn.fetchrow(
            """SELECT docket_id FROM dockets
               WHERE source = $1 AND title = $2
               ORDER BY created_at DESC LIMIT 1""",
            source, title,
        )
        if row:
            return row["docket_id"]

    # Create the docket.
    case_type = _infer_case_type(source, metadata)
    industry = metadata.get("industry") or "electricity"

    # Coerce stage / status if upstream passed them.
    stage = metadata.get("stage")
    status = metadata.get("status")
    applicant_name = metadata.get("applicant_name")
    account_name = metadata.get("account_name")
    statutory_deadline = metadata.get("statutory_deadline")
    opened_at = metadata.get("opened_at")

    # Resolve publisher_id (authority slug → UUID) if supplied.
    publisher_id: str | None = None
    publisher_slug = metadata.get("publisher") or metadata.get("publisher_slug")
    if publisher_slug:
        pub = await conn.fetchrow(
            "SELECT id FROM authorities WHERE slug = $1", publisher_slug
        )
        if pub:
            publisher_id = pub["id"]

    # Geometry: accept GeoJSON dict or WKT string; we pass the encoded
    # form as a single $14 parameter and let Postgres detect which
    # parser to use.
    import json as _json
    geom_val: str | None = None
    geom_in = metadata.get("geometry")
    if isinstance(geom_in, dict):
        geom_val = _json.dumps(geom_in)
    elif isinstance(geom_in, str) and geom_in.strip():
        geom_val = geom_in.strip()

    fallback_title = (
        title
        or (f"[{source.upper()}] {source_docket_id}" if source_docket_id else None)
        or f"[{source.upper()}] untitled docket"
    )

    if geom_val is not None:
        row = await conn.fetchrow(
            """
            INSERT INTO dockets
                (source, source_docket_id, publisher_id, title, description,
                 case_type, industry, status, stage, applicant_name, account_name,
                 statutory_deadline, opened_at, geometry)
            VALUES ($1, $2, $3, $4, $5,
                    $6, $7, $8, $9, $10, $11, $12, $13,
                    ST_SetSRID(
                      CASE WHEN $14::text LIKE '{%' THEN ST_GeomFromGeoJSON($14::text)
                           ELSE ST_GeomFromText($14::text) END,
                      4326)::geography)
            RETURNING docket_id
            """,
            source, source_docket_id, publisher_id, fallback_title,
            metadata.get("description"),
            case_type, industry, status, stage,
            applicant_name, account_name, statutory_deadline, opened_at,
            geom_val,
        )
    else:
        row = await conn.fetchrow(
            """
            INSERT INTO dockets
                (source, source_docket_id, publisher_id, title, description,
                 case_type, industry, status, stage, applicant_name, account_name,
                 statutory_deadline, opened_at)
            VALUES ($1, $2, $3, $4, $5,
                    $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING docket_id
            """,
            source, source_docket_id, publisher_id, fallback_title,
            metadata.get("description"),
            case_type, industry, status, stage,
            applicant_name, account_name, statutory_deadline, opened_at,
        )
    log.info(
        "docket_resolver: created docket %s for source=%s external_id=%s",
        row["docket_id"], source, source_docket_id,
    )
    return row["docket_id"]


__all__ = [
    "_resolve_docket_id",
    "_extract_source_docket_id",
    "_infer_case_type",
]

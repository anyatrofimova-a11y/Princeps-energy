"""
app/ingestion/pins_nsip.py — PINS NSIP (DCO) ingestion worker.

Reuses ``utils.pins_nsip.fetch_nsip_projects`` for the list of live
Nationally Significant Infrastructure Projects, then — for each case —
creates:

  * a ``dockets`` row (case_type='nsip_dco', one per NSIP case)
  * one or more ``documents`` rows for the key case filings we can
    resolve (project overview page + any linked case PDFs we can reach
    from the project slug).

``procedural_stage`` is mapped from the PINS "Stage" column to the
dockets-enum values: pre_app / acceptance / pre_examination / examination
/ recommendation / decision / post_consent.

Schedule: daily at 00:30 UTC (see :mod:`app.ingestion.scheduler`).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.ingestion.base import IngestionWorker, RawItem, stable_source_url

log = logging.getLogger("princeps.ingestion.pins_nsip")


# Map PINS "Stage" labels to documents.procedural_stage + dockets.stage enums.
_STAGE_MAP = {
    "pre-application":          ("pre_app",          "pre_app"),
    "pre application":          ("pre_app",          "pre_app"),
    "acceptance":               ("acceptance",       "acceptance"),
    "pre-examination":          ("pre_examination",  "pre_examination"),
    "pre examination":          ("pre_examination",  "pre_examination"),
    "examination":              ("examination",      "examination"),
    "recommendation":           ("recommendation",   "recommendation"),
    "decision":                 ("decision",         "decision"),
    "post-decision":            ("post_consent",     "post_consent"),
    "post decision":            ("post_consent",     "post_consent"),
    "decided":                  ("decision",         "decision"),
    "withdrawn":                ("decision",         "withdrawn"),
}


class PinsNsipWorker(IngestionWorker):
    """Poll PINS NSIP register → dockets + documents."""

    SOURCE = "pins_nsip"
    req_per_sec = 0.5

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        # Delegate to the existing utils scraper — it already tries CSV +
        # JSON endpoints and caches the result in-process.
        from utils.pins_nsip import fetch_nsip_projects
        projects = await fetch_nsip_projects()
        log.info("pins_nsip: %d live projects from PINS", len(projects))
        return projects

    async def parse(self, fetched: list[dict[str, Any]]) -> list[RawItem]:
        if not fetched:
            return []

        async with self.pool.acquire() as conn:
            out: list[RawItem] = []
            for proj in fetched:
                try:
                    items = await self._handle_project(conn, proj)
                    out.extend(items)
                except Exception as e:
                    log.warning(
                        "pins_nsip: skipping project %s — %s",
                        proj.get("name") or proj.get("reference"), e,
                    )
            return out

    async def _handle_project(
        self, conn, proj: dict[str, Any],
    ) -> list[RawItem]:
        ref = (proj.get("reference") or "").strip() or _derive_ref(proj)
        name = (proj.get("name") or "").strip()
        if not name or not ref:
            return []

        url = proj.get("url") or f"https://infrastructure.planninginspectorate.gov.uk/projects/{_slugify(name)}/"
        stage_label = (proj.get("status") or "").strip().lower()
        doc_stage, docket_stage = _STAGE_MAP.get(stage_label, (None, None))

        # Upsert the docket for this case
        docket_id = await self._upsert_docket(
            conn,
            ref=ref, name=name, description=proj.get("description"),
            applicant=proj.get("applicant") or "",
            status=proj.get("status"),
            stage=docket_stage,
            decision_date=proj.get("decision_date"),
            submission_date=proj.get("submission_date"),
            lat=proj.get("lat"), lon=proj.get("lon"),
        )

        # Base doc — project overview row
        items: list[RawItem] = [RawItem(
            source_url=url,
            title=f"NSIP {ref}: {name}",
            body_text=proj.get("description"),
            published_at=_parse_date(
                proj.get("decision_date") or proj.get("submission_date")
            ),
            filing_type="project_overview",
            procedural_stage=doc_stage,
            commission_authority="pins",
            pages=None,
            body_pdf_path=None,
            lat=proj.get("lat"),
            lon=proj.get("lon"),
            docket_id=str(docket_id),
            raw={
                "type": proj.get("type"),
                "capacity_mw": proj.get("capacity_mw"),
                "applicant": proj.get("applicant"),
                "location": proj.get("location"),
                "sector": proj.get("sector"),
                "reference": ref,
                "stage_label": proj.get("status"),
            },
        )]

        # If decision_date is populated we also seed a synthetic "decision"
        # doc so the timeline view has something to hang off.
        if proj.get("decision_date") and stage_label in ("decided", "decision", "post-decision"):
            decision_url = stable_source_url(self.SOURCE, f"{ref}/decision")
            items.append(RawItem(
                source_url=decision_url,
                title=f"NSIP {ref}: Decision",
                body_text=f"Decision published {proj.get('decision_date')}.",
                published_at=_parse_date(proj.get("decision_date")),
                filing_type="decision",
                procedural_stage="decision",
                commission_authority="pins",
                pages=None,
                body_pdf_path=None,
                lat=proj.get("lat"),
                lon=proj.get("lon"),
                docket_id=str(docket_id),
                raw={"reference": ref, "stage_label": "decision"},
            ))

        return items

    async def _upsert_docket(
        self, conn, *, ref: str, name: str,
        description: str | None, applicant: str,
        status: str | None, stage: str | None,
        decision_date: Any, submission_date: Any,
        lat: float | None, lon: float | None,
    ) -> Any:
        row = await conn.fetchrow(
            """INSERT INTO dockets
                   (source, source_docket_id, title, description, case_type,
                    industry, status, stage, applicant_name, opened_at,
                    geometry)
               VALUES ($1, $2, $3, $4, 'nsip_dco', 'electricity', $5, $6, $7, $8,
                       CASE WHEN $9::double precision IS NOT NULL
                             AND $10::double precision IS NOT NULL
                            THEN ST_SetSRID(ST_MakePoint($10, $9), 4326)::geography
                            ELSE NULL END)
               ON CONFLICT (source, source_docket_id) DO UPDATE
                 SET title       = EXCLUDED.title,
                     description = COALESCE(EXCLUDED.description, dockets.description),
                     status      = COALESCE(EXCLUDED.status, dockets.status),
                     stage       = COALESCE(EXCLUDED.stage, dockets.stage),
                     applicant_name = COALESCE(EXCLUDED.applicant_name, dockets.applicant_name),
                     geometry    = COALESCE(EXCLUDED.geometry, dockets.geometry),
                     updated_at  = now()
               RETURNING docket_id""",
            self.SOURCE, ref, f"NSIP {ref}: {name}",
            description, status, stage, applicant or None,
            _parse_date(submission_date) or datetime.now(timezone.utc),
            lat, lon,
        )
        return row["docket_id"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s[:80]


def _derive_ref(proj: dict[str, Any]) -> str:
    """When PINS doesn't publish a reference, synthesise one from the name."""
    base = (proj.get("name") or "").strip()
    if not base:
        return ""
    return "NSIP-" + re.sub(r"[^A-Za-z0-9]+", "-", base)[:40].strip("-")


def _parse_date(val: Any) -> datetime | None:
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                "%d/%m/%Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def run_once(pool):
    """Convenience entry point for APScheduler + manual CLI invocation."""
    worker = PinsNsipWorker(pool)
    return await worker.run()

"""PINS NSIP / DCO register connector — slug ``pins_nsip_dco``.

Pulls Nationally Significant Infrastructure Projects from the Planning
Inspectorate WP-JSON endpoint. Falls back to a 30-row fixture on any
upstream failure so the catalogue stays green-able offline.

License: OGL-3.0. Cadence: weekly.
Source: https://infrastructure.planninginspectorate.gov.uk/
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from app.connectors.base import Connector, IngestResult
from app.connectors.registry import register

log = logging.getLogger("princeps.connectors.pins_nsip_dco")

_BASE = "https://infrastructure.planninginspectorate.gov.uk"
_LIST_URL = f"{_BASE}/wp-json/wp/v2/projects"
_FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "pins_nsip_sample.json"
_HTTP_TIMEOUT = 30.0
_MAX_PAGES = 6  # 100/page × 6 = 600 rows ceiling.

_DDL = """
CREATE TABLE IF NOT EXISTS pins_nsip_dco (
  id BIGSERIAL PRIMARY KEY,
  case_ref TEXT NOT NULL, wp_id INT, title TEXT NOT NULL,
  sector TEXT, status TEXT, promoter TEXT, region TEXT,
  applied_date DATE, accepted_date DATE, decision_date DATE,
  location_lat NUMERIC, location_lng NUMERIC, capacity_mw NUMERIC,
  source_url TEXT, ingested_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ux_pins_case_ref UNIQUE(case_ref)
);
CREATE INDEX IF NOT EXISTS idx_pins_sector ON pins_nsip_dco(sector);
CREATE INDEX IF NOT EXISTS idx_pins_status ON pins_nsip_dco(status);
"""

_UPSERT_SQL = """
INSERT INTO pins_nsip_dco
  (case_ref, wp_id, title, sector, status, promoter, region,
   applied_date, accepted_date, decision_date,
   location_lat, location_lng, capacity_mw, source_url)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
ON CONFLICT (case_ref) DO UPDATE SET
  wp_id=EXCLUDED.wp_id, title=EXCLUDED.title, sector=EXCLUDED.sector,
  status=EXCLUDED.status, promoter=EXCLUDED.promoter, region=EXCLUDED.region,
  applied_date=EXCLUDED.applied_date, accepted_date=EXCLUDED.accepted_date,
  decision_date=EXCLUDED.decision_date,
  location_lat=EXCLUDED.location_lat, location_lng=EXCLUDED.location_lng,
  capacity_mw=EXCLUDED.capacity_mw, source_url=EXCLUDED.source_url,
  ingested_at=NOW()
"""


def _coerce_date(value: Any) -> date | None:
    """Coerce a YYYY-MM-DD-like string (or full ISO ts) into a ``date``.

    asyncpg requires real Python date objects for DATE columns; an
    ``::date`` cast on the SQL parameter is not enough.
    """
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalise_remote(item: dict) -> dict | None:
    """Map a WP-JSON projects item to our column dict; skip if no case_ref."""
    acf = item.get("acf") or {}
    case_ref = acf.get("case_reference") or acf.get("case_ref") or item.get("slug")
    title = (item.get("title") or {}).get("rendered") or acf.get("project_name")
    if not case_ref or not title:
        return None
    return {
        "case_ref": str(case_ref).strip(),
        "wp_id": item.get("id"),
        "title": str(title).strip(),
        "sector": acf.get("sector") or acf.get("project_sector"),
        "status": acf.get("stage") or acf.get("project_status"),
        "promoter": acf.get("promoter") or acf.get("applicant"),
        "region": acf.get("region"),
        "applied_date": acf.get("application_submitted") or acf.get("applied_date"),
        "accepted_date": acf.get("application_accepted") or acf.get("accepted_date"),
        "decision_date": acf.get("decision_issued") or acf.get("decision_date"),
        "location_lat": acf.get("latitude") or acf.get("location_lat"),
        "location_lng": acf.get("longitude") or acf.get("location_lng"),
        "capacity_mw": acf.get("capacity_mw") or acf.get("capacity"),
        "source_url": item.get("link") or _BASE,
    }


@register
class NsipDcoConnector(Connector):
    slug = "pins_nsip_dco"
    title = "PINS NSIP / DCO Register"
    source_url = "https://infrastructure.planninginspectorate.gov.uk/projects/"
    license = "OGL-3.0"
    refresh_cadence = "weekly"
    table_name = "pins_nsip_dco"
    freshness_threshold_hours = 24 * 9  # weekly + 2d slack

    async def ensure_schema(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            await conn.execute(_DDL)

    async def fetch(self) -> list[dict]:
        """Paginate WP-JSON; fall back to fixture on any failure."""
        rows: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
                for page in range(1, _MAX_PAGES + 1):
                    resp = await client.get(_LIST_URL, params={"per_page": 100, "page": page})
                    if resp.status_code == 400:  # WP signals "past last page".
                        break
                    resp.raise_for_status()
                    items = resp.json()
                    if not isinstance(items, list) or not items:
                        break
                    rows.extend(r for r in (_normalise_remote(i) for i in items) if r)
                    if len(items) < 100:
                        break
            if rows:
                log.info("pins_nsip_dco: %d rows from WP-JSON", len(rows))
                return rows
            raise RuntimeError("WP-JSON returned 0 normalisable rows")
        except Exception as exc:
            log.warning("pins_nsip_dco upstream unreachable (%s) — using fixture", exc)
            with _FIXTURE.open("r", encoding="utf-8") as f:
                rows = json.load(f)
            log.info("pins_nsip_dco: %d rows from fixture", len(rows))
            return rows

    async def upsert(self, pool: asyncpg.Pool, rows: list[dict]) -> IngestResult:
        ingested = 0
        errors: list[str] = []
        async with pool.acquire() as conn:
            if rows:
                async with conn.transaction():
                    for row in rows:
                        try:
                            await conn.execute(
                                _UPSERT_SQL,
                                row["case_ref"], row.get("wp_id"), row["title"],
                                row.get("sector"), row.get("status"), row.get("promoter"),
                                row.get("region"),
                                _coerce_date(row.get("applied_date")),
                                _coerce_date(row.get("accepted_date")),
                                _coerce_date(row.get("decision_date")),
                                row.get("location_lat"), row.get("location_lng"),
                                row.get("capacity_mw"), row.get("source_url"),
                            )
                            ingested += 1
                        except Exception as exc:
                            errors.append(f"{row.get('case_ref')}: {exc}")
            total = await conn.fetchval("SELECT count(*) FROM pins_nsip_dco")
        return IngestResult(rows_ingested=ingested, rows_total=int(total or 0), errors=errors)


__all__ = ["NsipDcoConnector"]

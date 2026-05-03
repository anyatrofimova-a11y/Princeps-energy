"""HSE major incidents (RIDDOR) — slug ``hse_riddor_incidents``.

Pulls the HSE major-incidents CSV from data.gov.uk; falls back to a
50-row BESS/grid-relevant fixture on upstream failure. License: OGL-3.0.
Cadence: quarterly.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

import asyncpg
import httpx

from app.connectors.base import Connector, IngestResult
from app.connectors.registry import register

log = logging.getLogger("princeps.connectors.hse_riddor_incidents")

_DATA_GOV_DATASET = "https://www.data.gov.uk/dataset/hse-major-incidents"
_FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "hse_incidents_sample.json"
_HTTP_TIMEOUT = 30.0

_DDL = """
CREATE TABLE IF NOT EXISTS hse_major_incidents (
  id BIGSERIAL PRIMARY KEY,
  incident_id TEXT NOT NULL,
  date_reported DATE,
  industry_sector TEXT, incident_type TEXT, location_postcode TEXT,
  summary TEXT, fatalities INT DEFAULT 0, injuries INT DEFAULT 0,
  source_url TEXT, ingested_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ux_hse_incident UNIQUE(incident_id)
);
CREATE INDEX IF NOT EXISTS idx_hse_sector ON hse_major_incidents(industry_sector);
CREATE INDEX IF NOT EXISTS idx_hse_date ON hse_major_incidents(date_reported DESC);
"""

_UPSERT_SQL = """
INSERT INTO hse_major_incidents
  (incident_id, date_reported, industry_sector, incident_type,
   location_postcode, summary, fatalities, injuries, source_url)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
ON CONFLICT (incident_id) DO UPDATE SET
  date_reported=EXCLUDED.date_reported,
  industry_sector=EXCLUDED.industry_sector,
  incident_type=EXCLUDED.incident_type,
  location_postcode=EXCLUDED.location_postcode,
  summary=EXCLUDED.summary,
  fatalities=EXCLUDED.fatalities, injuries=EXCLUDED.injuries,
  source_url=EXCLUDED.source_url, ingested_at=NOW()
"""

_CSV_ALIASES = {
    "incident_id": ["incident_id", "id", "ref", "reference"],
    "date_reported": ["date_reported", "report_date", "incident_date", "date"],
    "industry_sector": ["industry_sector", "sector", "industry"],
    "incident_type": ["incident_type", "type", "kind"],
    "location_postcode": ["location_postcode", "postcode", "location"],
    "summary": ["summary", "description", "details"],
    "fatalities": ["fatalities", "fatal", "deaths"],
    "injuries": ["injuries", "injured", "injury_count"],
    "source_url": ["source_url", "source", "url"]}


def _norm_text(v, max_len=None):
    if v is None: return None
    s = str(v).strip()
    return None if not s else (s[:max_len] if max_len else s)


def _norm_int(v):
    try: return int(float(v))
    except (TypeError, ValueError): return 0


def _norm_date(v) -> date | None:
    """Coerce a string/date to ``datetime.date`` (asyncpg requires real dates)."""
    if v in (None, ""): return None
    if isinstance(v, date): return v
    if not isinstance(v, str): return None
    s = v.strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try: return datetime.strptime(s, fmt).date()
        except ValueError: continue
    return None


def _pick(row: dict, key: str):
    """Case-insensitive lookup against ``_CSV_ALIASES``."""
    lookup = {k.lower().strip().replace(" ", "_"): v for k, v in row.items()}
    for alias in _CSV_ALIASES[key]:
        if alias in lookup:
            return lookup[alias]
    return None


def _normalise_csv(row: dict) -> dict | None:
    incident_id = _norm_text(_pick(row, "incident_id"))
    if not incident_id:
        return None
    return {
        "incident_id": incident_id,
        "date_reported": _norm_text(_pick(row, "date_reported")),
        "industry_sector": _norm_text(_pick(row, "industry_sector")),
        "incident_type": _norm_text(_pick(row, "incident_type")),
        "location_postcode": _norm_text(_pick(row, "location_postcode"), 16),
        "summary": _norm_text(_pick(row, "summary"), 200),
        "fatalities": _norm_int(_pick(row, "fatalities")),
        "injuries": _norm_int(_pick(row, "injuries")),
        "source_url": _norm_text(_pick(row, "source_url")) or _DATA_GOV_DATASET}


@register
class HseIncidentsConnector(Connector):
    slug = "hse_riddor_incidents"
    title = "HSE Major Incidents (RIDDOR)"
    source_url = _DATA_GOV_DATASET
    license = "OGL-3.0"
    refresh_cadence = "quarterly"
    table_name = "hse_major_incidents"
    freshness_threshold_hours = 24 * 100  # quarterly + ~10d slack

    async def ensure_schema(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            await conn.execute(_DDL)

    async def fetch(self) -> list[dict]:
        """Discover the first CSV link on the data.gov.uk page; else fixture."""
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
                page = await client.get(_DATA_GOV_DATASET)
                page.raise_for_status()
                csv_links = re.findall(
                    r'href="(https?://[^"]+\.csv)"', page.text, flags=re.IGNORECASE,
                )
                if not csv_links:
                    raise RuntimeError("no CSV resources on dataset page")
                resp = await client.get(csv_links[0])
                resp.raise_for_status()
                reader = csv.DictReader(io.StringIO(resp.text))
                rows = [r for r in (_normalise_csv(raw) for raw in reader) if r]
            if not rows:
                raise RuntimeError("CSV parsed to 0 rows")
            log.info("hse_riddor_incidents: %d rows from %s", len(rows), csv_links[0])
            return rows
        except Exception as exc:
            log.warning("hse_riddor_incidents upstream failed (%s) — using fixture", exc)
            with _FIXTURE.open("r", encoding="utf-8") as f:
                rows = json.load(f)
            log.info("hse_riddor_incidents: %d rows from fixture", len(rows))
            return rows

    async def upsert(self, pool: asyncpg.Pool, rows: list[dict]) -> IngestResult:
        ingested, errors = 0, []
        async with pool.acquire() as conn:
            if rows:
                async with conn.transaction():
                    for r in rows:
                        try:
                            await conn.execute(
                                _UPSERT_SQL,
                                r["incident_id"], _norm_date(r.get("date_reported")),
                                r.get("industry_sector"), r.get("incident_type"),
                                r.get("location_postcode"), r.get("summary"),
                                int(r.get("fatalities") or 0), int(r.get("injuries") or 0),
                                r.get("source_url"))
                            ingested += 1
                        except Exception as exc:
                            errors.append(f"{r.get('incident_id')}: {exc}")
            total = await conn.fetchval("SELECT count(*) FROM hse_major_incidents")
        return IngestResult(rows_ingested=ingested, rows_total=int(total or 0), errors=errors)


__all__ = ["HseIncidentsConnector"]

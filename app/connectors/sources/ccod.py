"""HM Land Registry — Corporate & Commercial Ownership Data (CCOD).

Magritte connector for the monthly CCOD snapshot published by HM Land
Registry under OGL-3.0. Source:
https://use-land-property-data.service.gov.uk/datasets/ccod

The live download requires a free public API key from gov.uk; when
``LAND_REGISTRY_API_KEY`` is unset the connector falls back to a
50-row commercial-flavoured fixture at ``tests/fixtures/ccod_sample.csv``
so smoke tests pass in any developer environment.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import asyncpg
import httpx

from app.connectors.base import Connector, IngestResult
from app.connectors.registry import register

log = logging.getLogger("princeps.connectors.ccod")

# CSV column → destination column mapping. Column names are the canonical
# CCOD headers (Title Case with parens) — kept in this single dict so the
# parser stays declarative.
_COL_MAP = {
    "Title Number": "title_number",
    "Tenure": "tenure",
    "Proprietor Name (1)": "proprietor_name_1",
    "Company Registration No. (1)": "company_registration_no_1",
    "Proprietorship Category (1)": "proprietorship_category_1",
    "Country Incorporated (1)": "country_incorporated_1",
    "Proprietor Name (2)": "proprietor_name_2",
    "Company Registration No. (2)": "company_registration_no_2",
    "Proprietor Name (3)": "proprietor_name_3",
    "Company Registration No. (3)": "company_registration_no_3",
    "Proprietor Name (4)": "proprietor_name_4",
    "Company Registration No. (4)": "company_registration_no_4",
    "Property Address": "property_address",
    "District": "district",
    "County": "county",
    "Region": "region",
    "Postcode": "postcode",
    "Date Proprietor Added": "date_proprietor_added",
    "Multiple Address Indicator": "multiple_address_indicator",
    "Change Indicator": "change_indicator",
    "Change Date": "change_date",
}

_DATE_COLS = {"date_proprietor_added", "change_date"}

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "ccod_sample.csv"
)

_LIVE_URL_TEMPLATE = (
    "https://use-land-property-data.service.gov.uk/datasets/ccod/download/"
    "CCOD_FULL_{year}_{month:02d}.csv"
)


def _parse_date(raw: str | None) -> Optional[date]:
    """Parse CCOD date strings (DD/MM/YYYY or YYYY-MM-DD); return None on junk."""
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_csv(text: str) -> list[dict[str, Any]]:
    """Parse CCOD CSV text into row dicts keyed on destination columns."""
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for raw in reader:
        out: dict[str, Any] = {}
        for src, dst in _COL_MAP.items():
            val = raw.get(src)
            if val is not None:
                val = val.strip()
                if not val:
                    val = None
            if dst in _DATE_COLS:
                val = _parse_date(val)
            out[dst] = val
        if out.get("title_number"):
            rows.append(out)
    return rows


@register
class CCODConnector(Connector):
    """HM Land Registry Corporate & Commercial Ownership Data."""

    slug = "hm_land_registry_ccod"
    title = "HM Land Registry — Corporate Ownership"
    source_url = "https://use-land-property-data.service.gov.uk/datasets/ccod"
    license = "OGL-3.0"
    refresh_cadence = "monthly"
    table_name = "hm_land_registry_ccod"
    freshness_threshold_hours = 30 * 24 + 24  # 31 days — monthly + slack

    async def ensure_schema(self, pool: asyncpg.Pool) -> None:
        # Migration migrations/2026_05_03_ccod_destination.sql owns the schema.
        return None

    async def fetch(self) -> list[dict[str, Any]]:
        api_key = os.environ.get("LAND_REGISTRY_API_KEY")
        if api_key:
            today = date.today()
            url = _LIVE_URL_TEMPLATE.format(year=today.year, month=today.month)
            headers = {"Authorization": api_key, "Accept": "text/csv"}
            log.info("ccod: fetching live snapshot %s", url)
            async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as cx:
                resp = await cx.get(url, headers=headers)
                if resp.status_code == 404 and today.day < 15:
                    # Snapshot for the current month not published yet — fall
                    # back to last month's file rather than failing the run.
                    prev_year = today.year if today.month > 1 else today.year - 1
                    prev_month = today.month - 1 if today.month > 1 else 12
                    url = _LIVE_URL_TEMPLATE.format(year=prev_year, month=prev_month)
                    log.info("ccod: current month 404, retrying %s", url)
                    resp = await cx.get(url, headers=headers)
                resp.raise_for_status()
                return _parse_csv(resp.text)

        # Fixture fallback — keep dev/CI deterministic without an API key.
        if not _FIXTURE_PATH.exists():
            raise FileNotFoundError(
                f"ccod fixture missing at {_FIXTURE_PATH} and "
                f"LAND_REGISTRY_API_KEY not set",
            )
        log.info("ccod: LAND_REGISTRY_API_KEY unset, using fixture %s", _FIXTURE_PATH)
        return _parse_csv(_FIXTURE_PATH.read_text(encoding="utf-8-sig"))

    async def upsert(
        self, pool: asyncpg.Pool, rows: list[dict[str, Any]],
    ) -> IngestResult:
        if not rows:
            async with pool.acquire() as conn:
                total = await conn.fetchval(
                    "SELECT count(*) FROM hm_land_registry_ccod",
                )
            return IngestResult(rows_ingested=0, rows_total=int(total or 0))

        cols = list(_COL_MAP.values())
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        update_cols = [c for c in cols if c != "title_number"]
        update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        sql = (
            f"INSERT INTO hm_land_registry_ccod ({', '.join(cols)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (title_number) DO UPDATE SET {update_set}, "
            f"ingested_at = NOW()"
        )
        records = [tuple(r.get(c) for c in cols) for r in rows]

        ingested = 0
        errors: list[str] = []
        async with pool.acquire() as conn:
            async with conn.transaction():
                # executemany swallows duplicates inside the same batch — chunk
                # so a malformed row only loses its chunk, not the whole pull.
                CHUNK = 1000
                for i in range(0, len(records), CHUNK):
                    batch = records[i:i + CHUNK]
                    try:
                        await conn.executemany(sql, batch)
                        ingested += len(batch)
                    except Exception as exc:  # pragma: no cover - defensive
                        errors.append(f"chunk {i}: {type(exc).__name__}: {exc}")
            total = await conn.fetchval("SELECT count(*) FROM hm_land_registry_ccod")

        return IngestResult(
            rows_ingested=ingested, rows_total=int(total or 0), errors=errors,
        )


__all__ = ["CCODConnector"]

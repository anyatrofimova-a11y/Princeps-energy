"""ENTSO-E day-ahead price connector — slug ``entsoe_da_prices_gb``.

Pulls hourly DA prices for the GB bidding zone (EIC ``10Y1001A1001A92E``)
for the last 7 days from the Transparency REST API (documentType A44).
Falls back to a 168-row fixture if ``ENTSOE_TOKEN`` is unset or the
upstream is unreachable.

License: ENTSO-E EULA (treated as CC-BY-4.0). Cadence: daily.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import asyncpg
import httpx

from app.connectors.base import Connector, IngestResult
from app.connectors.registry import register

log = logging.getLogger("princeps.connectors.entsoe_da_prices_gb")

_API = "https://web-api.tp.entsoe.eu/api"
_GB_EIC = "10Y1001A1001A92E"
_FIXTURE = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "entsoe_da_prices_sample.json"
_HTTP_TIMEOUT = 30.0

_DDL = """
CREATE TABLE IF NOT EXISTS entsoe_da_prices_gb (
  id BIGSERIAL PRIMARY KEY,
  bidding_zone TEXT NOT NULL DEFAULT 'GB',
  datetime_utc TIMESTAMPTZ NOT NULL,
  price_eur_mwh NUMERIC(10,2),
  currency TEXT DEFAULT 'EUR',
  document_id TEXT,
  ingested_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ux_entsoe_da UNIQUE(bidding_zone, datetime_utc)
);
CREATE INDEX IF NOT EXISTS idx_entsoe_da_dt ON entsoe_da_prices_gb(datetime_utc DESC);
"""

_UPSERT_SQL = """
INSERT INTO entsoe_da_prices_gb
  (bidding_zone, datetime_utc, price_eur_mwh, currency, document_id)
VALUES ('GB', $1, $2, $3, $4)
ON CONFLICT (bidding_zone, datetime_utc) DO UPDATE SET
  price_eur_mwh = EXCLUDED.price_eur_mwh,
  currency = EXCLUDED.currency,
  document_id = EXCLUDED.document_id,
  ingested_at = NOW()
"""


def _parse_publication_xml(xml_text: str) -> list[dict]:
    """Parse a Publication_MarketDocument; strip default ns for clean XPath.

    Each ``Point`` has a 1-based position against ``period.timeInterval/start``;
    DA resolution is PT60M (15-minute bidding zones use PT15M).
    """
    text = re.sub(r'\sxmlns="[^"]+"', "", xml_text, count=1) if 'xmlns=' in xml_text else xml_text
    root = ET.fromstring(text)
    doc_id = (root.findtext("mRID") or "").strip() or None
    rows: list[dict] = []
    for ts in root.findall("TimeSeries"):
        for period in ts.findall("Period"):
            start_text = period.findtext("timeInterval/start")
            if not start_text:
                continue
            start = datetime.strptime(start_text, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
            step = timedelta(minutes=15) if (period.findtext("resolution") or "").strip() == "PT15M" else timedelta(minutes=60)
            for pt in period.findall("Point"):
                try:
                    pos = int(pt.findtext("position") or "0")
                    price = float(pt.findtext("price.amount") or "nan")
                except (TypeError, ValueError):
                    continue
                if pos < 1:
                    continue
                dt = start + step * (pos - 1)
                rows.append({
                    "datetime_utc": dt,
                    "price_eur_mwh": round(price, 2),
                    "currency": "EUR",
                    "document_id": doc_id,
                })
    return rows


@register
class EntsoeDaPricesGBConnector(Connector):
    slug = "entsoe_da_prices_gb"
    title = "ENTSO-E Day-Ahead Prices (GB)"
    source_url = "https://transparency.entsoe.eu/transmission-domain/r2/dayAheadPrices"
    license = "CC-BY-4.0"
    refresh_cadence = "daily"
    table_name = "entsoe_da_prices_gb"
    freshness_threshold_hours = 36  # daily + 12h slack

    async def ensure_schema(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            await conn.execute(_DDL)

    async def fetch(self) -> list[dict]:
        """Pull last-7-days DA prices; fall back to fixture on any failure."""
        token = os.environ.get("ENTSOE_TOKEN")
        if not token:
            log.info("ENTSOE_TOKEN not set — using fixture")
            return self._load_fixture()
        end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=7)
        params = {
            "securityToken": token,
            "documentType": "A44",
            "in_Domain": _GB_EIC,
            "out_Domain": _GB_EIC,
            "periodStart": start.strftime("%Y%m%d%H%M"),
            "periodEnd": end.strftime("%Y%m%d%H%M"),
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(_API, params=params)
                resp.raise_for_status()
                rows = _parse_publication_xml(resp.text)
            if not rows:
                raise RuntimeError("ENTSO-E XML parsed to 0 rows")
            log.info("entsoe_da_prices_gb: %d rows from API", len(rows))
            return rows
        except Exception as exc:
            log.warning("entsoe_da_prices_gb upstream failed (%s) — using fixture", exc)
            return self._load_fixture()

    @staticmethod
    def _load_fixture() -> list[dict]:
        with _FIXTURE.open("r", encoding="utf-8") as f:
            rows = json.load(f)
        log.info("entsoe_da_prices_gb: %d rows from fixture", len(rows))
        return rows

    async def upsert(self, pool: asyncpg.Pool, rows: list[dict]) -> IngestResult:
        ingested = 0
        errors: list[str] = []
        async with pool.acquire() as conn:
            if rows:
                async with conn.transaction():
                    for row in rows:
                        try:
                            dt_value = row["datetime_utc"]
                            if isinstance(dt_value, str):
                                dt_value = datetime.fromisoformat(dt_value.replace("Z", "+00:00"))
                            await conn.execute(
                                _UPSERT_SQL, dt_value,
                                row.get("price_eur_mwh"),
                                row.get("currency", "EUR"),
                                row.get("document_id"),
                            )
                            ingested += 1
                        except Exception as exc:
                            errors.append(f"{row.get('datetime_utc')}: {exc}")
            total = await conn.fetchval("SELECT count(*) FROM entsoe_da_prices_gb")
        return IngestResult(rows_ingested=ingested, rows_total=int(total or 0), errors=errors)


__all__ = ["EntsoeDaPricesGBConnector"]

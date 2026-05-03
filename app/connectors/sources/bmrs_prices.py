"""BMRS settlement-period system prices.

Magritte connector for the Elexon BMRS Insights v1 system-prices endpoint.
Pulls settlement-period sell/buy prices for the last 30 days as a rolling
window; on first run this is a backfill, subsequent runs upsert the
overlapping window so late-arriving / corrected prints are picked up.

API docs: https://bmrs.elexon.co.uk/api-documentation
Open data — covered by the NESO open licence (treated as OGL-3.0 here).

Prior art for the URL pattern + 7-day pagination idiom is at
``utils/demand_data_ingester.py`` (national demand fetch).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

import asyncpg
import httpx

from app.connectors.base import Connector, IngestResult
from app.connectors.registry import register

log = logging.getLogger("princeps.connectors.bmrs_prices")

_BMRS_URL = (
    "https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices/"
    "{settlement_date}?settlementPeriodFrom=1&settlementPeriodTo=48&format=json"
)

_BACKFILL_DAYS = 30
_REQUEST_TIMEOUT = 30.0


def _decimal(raw: Any) -> Optional[Decimal]:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _to_bool(raw: Any) -> Optional[bool]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in {"true", "1", "yes", "y"}:
        return True
    if s in {"false", "0", "no", "n"}:
        return False
    return None


def _parse_settlement_date(raw: Any) -> Optional[date]:
    if not raw:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    s = str(raw)
    # Elexon returns either '2024-05-01' or '2024-05-01T00:00:00Z'
    if "T" in s:
        s = s.split("T", 1)[0]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalise_records(payload: Any) -> Iterable[dict[str, Any]]:
    """Yield row dicts from a Elexon system-prices payload."""
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("results") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    for it in items:
        if not isinstance(it, dict):
            continue
        sd = _parse_settlement_date(it.get("settlementDate"))
        sp = it.get("settlementPeriod")
        if sd is None or sp is None:
            continue
        try:
            sp_int = int(sp)
        except (TypeError, ValueError):
            continue
        yield {
            "settlement_date": sd,
            "settlement_period": sp_int,
            "system_sell_price": _decimal(it.get("systemSellPrice")),
            "system_buy_price": _decimal(it.get("systemBuyPrice")),
            "bsad_defaulted": _to_bool(it.get("bsadDefaulted")),
            "price_derivation_code": (
                str(it.get("priceDerivationCode")).strip()
                if it.get("priceDerivationCode") is not None
                else None
            ),
            "reserve_scarcity_price": _decimal(it.get("reserveScarcityPrice")),
            "indicative_net_imbalance_volume": _decimal(
                it.get("indicativeNetImbalanceVolume"),
            ),
        }


@register
class BmrsPricesConnector(Connector):
    """BMRS settlement-period system buy/sell prices (last 30 days rolling)."""

    slug = "bmrs_settlement_prices"
    title = "BMRS — System Prices (Settlement Period)"
    source_url = (
        "https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/system-prices"
    )
    license = "OGL-3.0"
    refresh_cadence = "daily"
    table_name = "bmrs_settlement_prices"
    freshness_threshold_hours = 36  # daily refresh + 12h slack

    async def ensure_schema(self, pool: asyncpg.Pool) -> None:
        # Migration migrations/2026_05_03_bmrs_prices.sql owns the schema.
        return None

    async def fetch(self) -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=_BACKFILL_DAYS - 1)
        rows: list[dict[str, Any]] = []
        ok_days = 0
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as cx:
            cur = start
            while cur <= today:
                url = _BMRS_URL.format(settlement_date=cur.isoformat())
                try:
                    resp = await cx.get(url, headers={"Accept": "application/json"})
                    if resp.status_code == 404:
                        log.debug("bmrs: no data for %s (404)", cur)
                    else:
                        resp.raise_for_status()
                        rows.extend(_normalise_records(resp.json()))
                        ok_days += 1
                except httpx.HTTPError as exc:
                    log.warning("bmrs: fetch failed for %s: %s", cur, exc)
                cur += timedelta(days=1)
        log.info(
            "bmrs: pulled %d rows across %d/%d days",
            len(rows), ok_days, _BACKFILL_DAYS,
        )
        return rows

    async def upsert(
        self, pool: asyncpg.Pool, rows: list[dict[str, Any]],
    ) -> IngestResult:
        if not rows:
            async with pool.acquire() as conn:
                total = await conn.fetchval(
                    "SELECT count(*) FROM bmrs_settlement_prices",
                )
            return IngestResult(
                rows_ingested=0,
                rows_total=int(total or 0),
                errors=["no rows fetched from BMRS — endpoint empty or unreachable"],
            )

        cols = [
            "settlement_date",
            "settlement_period",
            "system_sell_price",
            "system_buy_price",
            "bsad_defaulted",
            "price_derivation_code",
            "reserve_scarcity_price",
            "indicative_net_imbalance_volume",
        ]
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        update_cols = [c for c in cols if c not in ("settlement_date", "settlement_period")]
        update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        sql = (
            f"INSERT INTO bmrs_settlement_prices ({', '.join(cols)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (settlement_date, settlement_period) DO UPDATE SET "
            f"{update_set}, ingested_at = NOW()"
        )
        records = [tuple(r.get(c) for c in cols) for r in rows]

        ingested = 0
        errors: list[str] = []
        async with pool.acquire() as conn:
            async with conn.transaction():
                CHUNK = 500
                for i in range(0, len(records), CHUNK):
                    batch = records[i:i + CHUNK]
                    try:
                        await conn.executemany(sql, batch)
                        ingested += len(batch)
                    except Exception as exc:  # pragma: no cover - defensive
                        errors.append(f"chunk {i}: {type(exc).__name__}: {exc}")
            total = await conn.fetchval("SELECT count(*) FROM bmrs_settlement_prices")

        return IngestResult(
            rows_ingested=ingested, rows_total=int(total or 0), errors=errors,
        )


__all__ = ["BmrsPricesConnector"]

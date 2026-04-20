"""
app/ingestion/bmrs.py — BMRS balancing-event ingester.

The existing ``utils.demand_data_ingester`` pulls demand outturn. This
worker complements it with *events* — anything that shows up on the
BMRS balancing / system feeds as an exceptional signal and might
warrant a dispatch alert:

  * accepted BOAs with an unusually high bid price (>£2,500/MWh)
  * transmission constraints (BC1.4 notices)
  * emergency & reserve declarations (EIRs, EMNs)
  * margin / System Warnings

Each event is materialised as a ``documents`` row with
``source='bmrs'``. Rolling 7-day digest — on each run we re-pull the
last 24h + the last 7d of notifications and upsert; the UNIQUE
``source_url`` handles repeats.

Schedule: every 15min (near-realtime for market events).

BMRS Insights API v1 — no auth required for these endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.ingestion.base import IngestionWorker, RawItem, stable_source_url

log = logging.getLogger("princeps.ingestion.bmrs")

_BMRS_BASE = "https://data.elexon.co.uk/bmrs/api/v1"

# BOAs with bid > this (£/MWh) are considered "high" and worth surfacing.
_HIGH_BOA_PRICE_GBP_PER_MWH = 2500.0


class BmrsWorker(IngestionWorker):
    """Poll BMRS Insights for balancing events → documents(source='bmrs')."""

    SOURCE = "bmrs"
    req_per_sec = 1.0
    # Keep LLM off — these are heavily templated, regex-class is enough.
    classify_inline = True
    extract_inline = False

    async def fetch(self, client: httpx.AsyncClient) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start_7d = now - timedelta(days=7)
        from_ts = start_7d.strftime("%Y-%m-%dT%H:%M:%SZ")
        to_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        out: dict[str, Any] = {"boas": [], "warnings": [], "constraints": []}

        # ── High-priced BOAs ─────────────────────────────────────────────────
        try:
            await self._throttle()
            r = await client.get(
                f"{_BMRS_BASE}/balancing/acceptances/all",
                params={"from": from_ts, "to": to_ts, "format": "json"},
            )
            if r.status_code == 200:
                payload = r.json()
                records = payload if isinstance(payload, list) else payload.get("data") or []
                for rec in records:
                    bid_price = _num(rec.get("bidPrice") or rec.get("acceptancePrice"))
                    if bid_price is not None and bid_price >= _HIGH_BOA_PRICE_GBP_PER_MWH:
                        out["boas"].append(rec)
        except Exception as e:
            log.info("bmrs: BOA fetch failed (non-fatal): %s", e)

        # ── System warnings ──────────────────────────────────────────────────
        try:
            await self._throttle()
            r = await client.get(
                f"{_BMRS_BASE}/system/warnings",
                params={"from": from_ts, "to": to_ts, "format": "json"},
            )
            if r.status_code == 200:
                payload = r.json()
                records = payload if isinstance(payload, list) else payload.get("data") or []
                out["warnings"].extend(records)
        except Exception as e:
            log.info("bmrs: warnings fetch failed (non-fatal): %s", e)

        # ── Transmission constraints (BC1.4 notices) ─────────────────────────
        try:
            await self._throttle()
            r = await client.get(
                f"{_BMRS_BASE}/balancing/constraint/notices",
                params={"from": from_ts, "to": to_ts, "format": "json"},
            )
            if r.status_code == 200:
                payload = r.json()
                records = payload if isinstance(payload, list) else payload.get("data") or []
                out["constraints"].extend(records)
        except Exception as e:
            log.info("bmrs: constraint notices fetch failed (non-fatal): %s", e)

        log.info("bmrs: fetched BOAs=%d warnings=%d constraints=%d",
                 len(out["boas"]), len(out["warnings"]), len(out["constraints"]))
        return out

    async def parse(self, fetched: dict[str, Any]) -> list[RawItem]:
        items: list[RawItem] = []
        for rec in fetched.get("boas", []):
            items.append(self._boa_to_item(rec))
        for rec in fetched.get("warnings", []):
            items.append(self._warning_to_item(rec))
        for rec in fetched.get("constraints", []):
            items.append(self._constraint_to_item(rec))
        return [i for i in items if i is not None]

    # ── Record → RawItem ────────────────────────────────────────────────────

    def _boa_to_item(self, rec: dict[str, Any]) -> RawItem | None:
        bmu = rec.get("bmUnit") or rec.get("bmUnitId") or rec.get("settlementUnit")
        ts = rec.get("timeFrom") or rec.get("acceptanceTime") or rec.get("timestamp")
        price = _num(rec.get("bidPrice") or rec.get("acceptancePrice"))
        level = _num(rec.get("acceptanceLevel") or rec.get("mw"))
        if not bmu or ts is None:
            return None
        key = f"boa/{bmu}/{ts}"
        title = f"High-priced BOA — {bmu} @ £{price:.0f}/MWh"
        body_lines = [f"BMU: {bmu}", f"Time: {ts}",
                      f"Bid price: £{price}/MWh" if price is not None else "Bid price: ?",
                      f"Level: {level} MW" if level is not None else "Level: ?"]
        return RawItem(
            source_url=stable_source_url(self.SOURCE, key),
            title=title[:500],
            body_text="\n".join(body_lines),
            published_at=_parse_ts(ts),
            filing_type="boa_high_price",
            procedural_stage=None,
            commission_authority="neso",
            pages=None,
            body_pdf_path=None,
            raw={"bmu": bmu, "price_gbp_per_mwh": price, "mw": level,
                 "timeFrom": ts},
        )

    def _warning_to_item(self, rec: dict[str, Any]) -> RawItem | None:
        ref = rec.get("warningId") or rec.get("noticeId") or rec.get("id")
        ts = rec.get("publishTime") or rec.get("issueTime") or rec.get("timestamp")
        wtype = rec.get("warningType") or rec.get("type") or "system_warning"
        msg = rec.get("message") or rec.get("messageText") or rec.get("description") or ""
        if not ref:
            return None
        key = f"warning/{wtype}/{ref}"
        title = f"NESO {wtype} — {ref}"
        body = (msg or f"{wtype} notice {ref}")[:8000]
        return RawItem(
            source_url=stable_source_url(self.SOURCE, key),
            title=title[:500],
            body_text=body,
            published_at=_parse_ts(ts),
            filing_type=str(wtype).lower(),
            procedural_stage=None,
            commission_authority="neso",
            pages=None,
            body_pdf_path=None,
            raw=dict(rec),
        )

    def _constraint_to_item(self, rec: dict[str, Any]) -> RawItem | None:
        ref = rec.get("noticeId") or rec.get("id") or rec.get("mrid")
        ts = rec.get("publishTime") or rec.get("effectiveFrom") or rec.get("timestamp")
        group = rec.get("constraintGroup") or rec.get("group") or rec.get("boundary") or ""
        msg = rec.get("message") or rec.get("description") or ""
        if not ref:
            return None
        key = f"constraint/{ref}"
        title = f"Transmission constraint {group or ref}".strip()
        body = (msg or f"Constraint group {group} notice {ref}")[:8000]
        return RawItem(
            source_url=stable_source_url(self.SOURCE, key),
            title=title[:500],
            body_text=body,
            published_at=_parse_ts(ts),
            filing_type="constraint_notice",
            procedural_stage=None,
            commission_authority="neso",
            pages=None,
            body_pdf_path=None,
            raw=dict(rec),
        )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    s = str(v)
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


async def run_once(pool):
    """Convenience entry point for APScheduler + manual CLI invocation."""
    worker = BmrsWorker(pool)
    return await worker.run()

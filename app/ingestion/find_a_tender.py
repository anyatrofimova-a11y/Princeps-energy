"""
app/ingestion/find_a_tender.py — UK Find-a-Tender (OCDS) ingester.

Find-a-Tender is the post-Brexit UK replacement for TED. It publishes
all above-threshold public-sector procurement notices in the OCDS 1.1
JSON schema:

    https://www.find-tender.service.gov.uk/

OCDS bulk download endpoint (JSON, gzipped):

    https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?updatedFrom=<ISO>

Each release package contains an ``releases`` array; each release is a
tender / award notice. We filter to CPV prefixes for energy +
infrastructure and upsert one ``documents`` row per release.

Schedule: daily @ 02:00 UTC.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.ingestion.base import IngestionWorker, RawItem

log = logging.getLogger("princeps.ingestion.find_a_tender")


_FAT_OCDS_URL = "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"

# CPV prefixes — filter on the first 2 digits (energy/infrastructure).
#   09xx: petroleum / fuel
#   31xx: electrical equipment (substations, switchgear, cables)
#   44xx: construction structures and materials
#   45xx: construction works (45230000 is "Utility works")
#   65xx: public utilities (electricity supply, water)
#   71xx: engineering services
_CPV_PREFIXES = ("09", "31", "44", "45", "65", "71")

# Broad keyword filter for tenders whose CPV is missing/generic.
_ENERGY_KEYWORDS = (
    "solar", "battery", "bess", "wind", "grid", "substation", "cable",
    "energy storage", "hydrogen", "photovoltaic", "renewable",
    "electric vehicle", "ev charging", "data centre", "data center",
    "transmission", "distribution network",
)


class FindATenderWorker(IngestionWorker):
    """Poll OCDS release-packages feed; filter energy/infra; upsert docs."""

    SOURCE = "find_a_tender"
    req_per_sec = 1.0
    classify_inline = True
    extract_inline = True

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        releases: list[dict[str, Any]] = []
        cursor: str | None = since

        # Simple page-chasing. OCDS feeds return `links.next` when paging.
        for _ in range(20):  # hard cap — 20 pages * 100 = 2000 releases
            params: dict[str, Any] = {}
            if cursor:
                params["updatedFrom"] = cursor
            await self._throttle()
            try:
                r = await client.get(_FAT_OCDS_URL, params=params,
                                     timeout=self.http_timeout_s)
                if r.status_code != 200:
                    log.info("find_a_tender: %d on page fetch", r.status_code)
                    break
                payload = r.json()
            except Exception as e:
                log.warning("find_a_tender: fetch failed: %s", e)
                break

            packages = payload.get("releasePackages") or payload.get("packages") or []
            if isinstance(payload.get("releases"), list):
                # Some mirrors flatten packages
                packages = [{"releases": payload["releases"]}]

            for pkg in packages:
                for rel in pkg.get("releases") or []:
                    if _is_relevant(rel):
                        releases.append(rel)

            nxt = (payload.get("links") or {}).get("next")
            if not nxt or nxt == _FAT_OCDS_URL:
                break
            # Derive next cursor from the response if the API provides one.
            next_cursor = payload.get("links", {}).get("next_cursor") or \
                          (payload.get("releases") or [{}])[-1].get("date") if payload.get("releases") else None
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        log.info("find_a_tender: %d relevant releases", len(releases))
        return releases

    async def parse(self, fetched: list[dict[str, Any]]) -> list[RawItem]:
        items: list[RawItem] = []
        for rel in fetched:
            ocid = rel.get("ocid") or rel.get("id")
            tender = rel.get("tender") or {}
            title = tender.get("title") or rel.get("title") or "Tender"
            desc = tender.get("description") or rel.get("description") or ""
            url = (
                (rel.get("tag") and f"https://www.find-tender.service.gov.uk/notice/{ocid}")
                or rel.get("url")
                or f"https://www.find-tender.service.gov.uk/ocds/{ocid}"
            )

            value = ((tender.get("value") or {}).get("amount"))
            currency = ((tender.get("value") or {}).get("currency"))
            buyer = ((rel.get("buyer") or {}).get("name"))

            items.append(RawItem(
                source_url=url,
                title=f"{buyer or 'UK public body'}: {title}"[:500],
                body_text=desc,
                published_at=_parse_ocds_date(rel.get("date") or (tender.get("tenderPeriod") or {}).get("startDate")),
                filing_type=_classify_tender_type(rel.get("tag")),
                procedural_stage=None,
                commission_authority=_buyer_authority(buyer),
                pages=None,
                body_pdf_path=None,
                raw={
                    "ocid": ocid,
                    "buyer": buyer,
                    "value": value,
                    "currency": currency,
                    "cpvs": _extract_cpvs(tender),
                    "procurement_method": tender.get("procurementMethod"),
                },
            ))
        return items


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_relevant(rel: dict[str, Any]) -> bool:
    tender = rel.get("tender") or {}
    cpvs = _extract_cpvs(tender)
    for cpv in cpvs:
        if str(cpv).startswith(_CPV_PREFIXES):
            return True
    # Keyword fallback on title + description
    txt = (f"{tender.get('title') or ''} {tender.get('description') or ''}").lower()
    return any(k in txt for k in _ENERGY_KEYWORDS)


def _extract_cpvs(tender: dict[str, Any]) -> list[str]:
    out: list[str] = []
    cat = tender.get("classification") or {}
    if cat.get("scheme") in ("CPV", "cpv") and cat.get("id"):
        out.append(str(cat["id"]))
    for extra in tender.get("additionalClassifications") or []:
        if extra.get("scheme") in ("CPV", "cpv") and extra.get("id"):
            out.append(str(extra["id"]))
    return out


def _classify_tender_type(tag: Any) -> str:
    tags = tag if isinstance(tag, list) else ([tag] if tag else [])
    tags = [str(t).lower() for t in tags]
    if "award" in tags or "awardnotice" in tags:
        return "award_notice"
    if "contract" in tags:
        return "contract_notice"
    if "tender" in tags:
        return "tender_notice"
    if "planning" in tags:
        return "prior_information"
    return "tender"


def _buyer_authority(buyer: str | None) -> str:
    if not buyer:
        return "uk_public_body"
    return (buyer or "").strip().lower().replace(" ", "_")[:64]


def _parse_ocds_date(v: Any) -> datetime | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
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
    worker = FindATenderWorker(pool)
    return await worker.run()

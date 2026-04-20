"""
app/ingestion/companies_house.py — Companies House API polling.

The Companies House REST API (https://api.company-information.service.gov.uk/)
is free but rate-limited (600 req / 5 min per key). We poll for three
signal types relevant to the UK energy-developer intelligence layer:

  1. **SPV incorporations** — new companies with ``officers`` matching
     a watchlist of known-developer director names OR with energy-sector
     SIC codes (35110, 35120, 35130, 35140, 40100).
  2. **Charge filings** (MR01 / MR04) on companies with energy SIC codes —
     a strong proxy for project finance draw-down.
  3. **PSC changes** on energy-sector SPVs.

Each filing is a ``documents`` row, grouped under a ``dockets`` row per
SPV (one docket per company_number, case_type='misc').

Schedule: daily at 01:00 UTC.

Credentials:
    COMPANIES_HOUSE_API_KEY — REST API key (free). Without it the worker
    logs a warning and no-ops.

Watchlist:
    The developer-director watchlist lives in a JSONB row on
    ``data_subscriptions`` with slug ``ch-developer-watchlist`` so it
    can be edited via the admin UI without redeploy. The worker reads it
    on each run; absent watchlist → SIC-filter-only mode.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.ingestion.base import IngestionWorker, RawItem, stable_source_url

log = logging.getLogger("princeps.ingestion.companies_house")


_CH_BASE = "https://api.company-information.service.gov.uk"

# SIC codes considered "energy sector" for the filter.
_ENERGY_SIC = {
    "35110",   # Production of electricity
    "35120",   # Transmission of electricity
    "35130",   # Distribution of electricity
    "35140",   # Trade of electricity
    "35220",   # Distribution of gaseous fuels through mains
    "35230",   # Trade of gas through mains
    "40100",   # (legacy) Electric power generation
    "71122",   # Engineering related scientific/technical consultancy
    "42220",   # Construction of utility projects for electricity
}


class CompaniesHouseWorker(IngestionWorker):
    """Daily CH polling — energy-sector SPV incorporations, charges, PSC."""

    SOURCE = "companies_house"
    # CH rate limit: 600 / 5 min = 2 req/sec. Stay comfortably below.
    req_per_sec = 1.5
    classify_inline = True
    extract_inline = False

    async def fetch(self, client: httpx.AsyncClient) -> dict[str, Any]:
        key = os.getenv("COMPANIES_HOUSE_API_KEY")
        if not key:
            log.warning("COMPANIES_HOUSE_API_KEY not set — CH ingestion disabled")
            return {}

        auth = httpx.BasicAuth(key, "")
        out: dict[str, Any] = {
            "incorporations": [],
            "charges": [],
            "psc_changes": [],
        }
        watchlist = await self._load_watchlist()

        # Advanced search for energy-SIC incorporations in the last 7 days.
        # CH's advanced-search endpoint supports date filtering on
        # incorporated_from / incorporated_to.
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        for sic in sorted(_ENERGY_SIC):
            await self._throttle()
            try:
                r = await client.get(
                    f"{_CH_BASE}/advanced-search/companies",
                    params={
                        "sic_codes": sic,
                        "incorporated_from": since,
                        "size": 100,
                    },
                    auth=auth,
                    timeout=self.http_timeout_s,
                )
                if r.status_code != 200:
                    log.info("CH search sic=%s returned %d", sic, r.status_code)
                    continue
                payload = r.json()
                for item in payload.get("items") or []:
                    out["incorporations"].append(item)
            except Exception as e:
                log.info("CH SIC search failed for %s: %s", sic, e)

        # Watchlist sweep — one company/person search per director name.
        # Only active officers are useful for SPV-spotting.
        for name in watchlist[:200]:
            await self._throttle()
            try:
                r = await client.get(
                    f"{_CH_BASE}/search/officers",
                    params={"q": name, "items_per_page": 20},
                    auth=auth,
                    timeout=self.http_timeout_s,
                )
                if r.status_code != 200:
                    continue
                payload = r.json()
                for item in payload.get("items") or []:
                    out["incorporations"].append({
                        **(item.get("appointments_summary") or {}),
                        "_matched_officer": name,
                        "company_name": item.get("company_name") or item.get("title"),
                        "company_number": item.get("company_number") or item.get("links", {}).get("self", "").split("/")[-1],
                    })
            except Exception as e:
                log.debug("CH officer search failed for %s: %s", name, e)

        # Per-company charges + PSC checks. Bound to the first 50 incorporations
        # to cap request volume.
        seen_nums: set[str] = set()
        for item in out["incorporations"][:50]:
            num = (item.get("company_number") or "").strip()
            if not num or num in seen_nums:
                continue
            seen_nums.add(num)

            # Charges
            await self._throttle()
            try:
                r = await client.get(
                    f"{_CH_BASE}/company/{num}/charges",
                    auth=auth, timeout=self.http_timeout_s,
                )
                if r.status_code == 200:
                    for charge in (r.json().get("items") or []):
                        out["charges"].append({**charge, "company_number": num})
            except Exception:
                pass

            # PSC
            await self._throttle()
            try:
                r = await client.get(
                    f"{_CH_BASE}/company/{num}/persons-with-significant-control",
                    auth=auth, timeout=self.http_timeout_s,
                )
                if r.status_code == 200:
                    for psc in (r.json().get("items") or []):
                        out["psc_changes"].append({**psc, "company_number": num})
            except Exception:
                pass

        log.info(
            "companies_house: incorporations=%d charges=%d psc=%d",
            len(out["incorporations"]), len(out["charges"]), len(out["psc_changes"]),
        )
        return out

    async def parse(self, fetched: dict[str, Any]) -> list[RawItem]:
        if not fetched:
            return []
        items: list[RawItem] = []
        async with self.pool.acquire() as conn:
            # Group by company_number so we create one docket per SPV
            docket_cache: dict[str, Any] = {}

            for inc in fetched.get("incorporations", []):
                num = (inc.get("company_number") or "").strip()
                if not num:
                    continue
                did = docket_cache.get(num) or await self._upsert_company_docket(
                    conn, inc,
                )
                docket_cache[num] = did
                items.append(self._inc_to_item(inc, did))

            for charge in fetched.get("charges", []):
                num = (charge.get("company_number") or "").strip()
                did = docket_cache.get(num)
                if not did:
                    continue
                items.append(self._charge_to_item(charge, did))

            for psc in fetched.get("psc_changes", []):
                num = (psc.get("company_number") or "").strip()
                did = docket_cache.get(num)
                if not did:
                    continue
                items.append(self._psc_to_item(psc, did))

        return [i for i in items if i is not None]

    # ── Record → RawItem ────────────────────────────────────────────────────

    async def _upsert_company_docket(self, conn, inc: dict[str, Any]) -> Any:
        num = inc.get("company_number")
        name = inc.get("company_name") or inc.get("title") or num
        row = await conn.fetchrow(
            """INSERT INTO dockets
                   (source, source_docket_id, title, description, case_type,
                    industry, status, opened_at)
               VALUES ($1, $2, $3, $4, 'misc', 'electricity', 'active', now())
               ON CONFLICT (source, source_docket_id) DO UPDATE
                 SET title = EXCLUDED.title,
                     updated_at = now()
               RETURNING docket_id""",
            self.SOURCE, num, f"CH {num}: {name}",
            "Companies House filings for energy-sector SPV.",
        )
        return row["docket_id"]

    def _inc_to_item(self, inc: dict[str, Any], docket_id: Any) -> RawItem:
        num = inc.get("company_number")
        name = inc.get("company_name") or inc.get("title") or num
        ts = inc.get("date_of_creation") or inc.get("incorporated_on")
        url = f"https://find-and-update.company-information.service.gov.uk/company/{num}"
        return RawItem(
            source_url=url,
            title=f"Incorporation — {name} ({num})"[:500],
            body_text=f"Company {name} ({num}) filed at Companies House.\nSIC: {inc.get('sic_codes') or ''}\nOfficer match: {inc.get('_matched_officer') or ''}",
            published_at=_parse_date(ts),
            filing_type="incorporation",
            procedural_stage=None,
            commission_authority="companies_house",
            pages=None,
            body_pdf_path=None,
            docket_id=str(docket_id),
            raw=dict(inc),
        )

    def _charge_to_item(self, charge: dict[str, Any], docket_id: Any) -> RawItem:
        num = charge.get("company_number")
        cid = charge.get("id") or charge.get("charge_code") or charge.get("charge_number")
        ts = charge.get("created_on") or charge.get("delivered_on")
        key = f"charge/{num}/{cid}"
        persons = ", ".join([p.get("name") or "" for p in (charge.get("persons_entitled") or [])])
        return RawItem(
            source_url=stable_source_url(self.SOURCE, key),
            title=f"Charge filed — {num} ({cid})"[:500],
            body_text=f"Charge {cid} for company {num}.\nPersons entitled: {persons}\nStatus: {charge.get('status','')}",
            published_at=_parse_date(ts),
            filing_type="charge_filing",
            procedural_stage=None,
            commission_authority="companies_house",
            pages=None,
            body_pdf_path=None,
            docket_id=str(docket_id),
            raw=dict(charge),
        )

    def _psc_to_item(self, psc: dict[str, Any], docket_id: Any) -> RawItem:
        num = psc.get("company_number")
        pid = psc.get("etag") or psc.get("id") or (psc.get("name") or "")[:40]
        ts = psc.get("notified_on")
        key = f"psc/{num}/{pid}"
        return RawItem(
            source_url=stable_source_url(self.SOURCE, key),
            title=f"PSC update — {num}"[:500],
            body_text=f"Person with significant control update for {num}.\n"
                      f"Name: {psc.get('name','')}\nKind: {psc.get('kind','')}\nNotified: {ts}",
            published_at=_parse_date(ts),
            filing_type="psc_change",
            procedural_stage=None,
            commission_authority="companies_house",
            pages=None,
            body_pdf_path=None,
            docket_id=str(docket_id),
            raw=dict(psc),
        )

    async def _load_watchlist(self) -> list[str]:
        """Pull the developer-director watchlist from data_subscriptions."""
        async with self.pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """SELECT description
                         FROM data_subscriptions
                        WHERE slug = 'ch-developer-watchlist'"""
                )
            except Exception:
                return []
        if not row:
            return []
        # Stored as newline-delimited names in the description, for ease
        # of admin editing. Empty by default.
        raw = row["description"] or ""
        return [n.strip() for n in raw.splitlines() if n.strip()]


def _parse_date(v: Any) -> datetime | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def run_once(pool):
    """Convenience entry point for APScheduler + manual CLI invocation."""
    worker = CompaniesHouseWorker(pool)
    return await worker.run()

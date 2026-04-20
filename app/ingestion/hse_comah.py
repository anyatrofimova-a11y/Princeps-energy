"""
app/ingestion/hse_comah.py — HSE COMAH public register scrape.

HSE publishes COMAH (Control of Major Accident Hazards) enforcement
notices and public-register entries here:

    https://resources.hse.gov.uk/notices/               (enforcement)
    https://www.hse.gov.uk/comah/public-information.htm (register index)

The schema tolerates scaffold state — we fetch the HTML, run a loose
regex to surface energy-sector incidents (battery fires, substation
fires, grid asset faults, chemical incidents at energy sites) and upsert
each as a ``documents`` row.

Schedule: weekly Friday 09:00 UTC.

NOTE: This worker is scaffolded with working HTTP + parser scaffolding,
but the live HSE HTML structure changes frequently and the energy-sector
filter is deliberately conservative. Treat this as a starting point; when
HSE adds a machine-readable feed it should be swapped in here.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.ingestion.base import IngestionWorker, RawItem

log = logging.getLogger("princeps.ingestion.hse_comah")


# HSE notices listing — HTML page with a paginated list of notices.
_HSE_NOTICES_URL = "https://resources.hse.gov.uk/notices/"

# Keyword filters — conservative list for the energy sector.
_ENERGY_KEYWORDS = re.compile(
    r"\b(battery|BESS|substation|transformer|energy storage|"
    r"photovoltaic|solar farm|wind (?:farm|turbine)|hydrogen|"
    r"power station|electricity|gas network|anaerobic digest|"
    r"CCGT|biomass|thermal runaway)\b",
    re.I,
)

# Notice row-ish pattern — HSE Notices pages render a table-like list.
_NOTICE_ROW_RE = re.compile(
    r'<a[^>]+href="([^"]*notice[^"]*)"[^>]*>([^<]+)</a>'
    r'.*?<td[^>]*>([^<]+)</td>'       # date cell
    r'.*?<td[^>]*>([^<]+)</td>',      # authority / company cell
    re.I | re.DOTALL,
)


class HseComahWorker(IngestionWorker):
    """Weekly HSE COMAH / notices scrape — energy-sector incidents only."""

    SOURCE = "hse_comah"
    req_per_sec = 0.5
    # Scaffolded — keep classify/extract on but tolerant of sparse text
    classify_inline = True
    extract_inline = True

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        try:
            r = await client.get(_HSE_NOTICES_URL, timeout=self.http_timeout_s)
            if r.status_code != 200:
                log.info("hse_comah: notices index returned %d", r.status_code)
                return []
            html = r.text
        except Exception as e:
            log.warning("hse_comah: fetch failed: %s", e)
            return []

        out: list[dict[str, Any]] = []
        for m in _NOTICE_ROW_RE.finditer(html):
            href, title, date_txt, party = m.groups()
            if not _ENERGY_KEYWORDS.search(f"{title} {party}"):
                continue
            url = href if href.startswith("http") else f"https://resources.hse.gov.uk{href}"
            out.append({
                "url": url,
                "title": _clean(title),
                "date": _clean(date_txt),
                "party": _clean(party),
            })

        # Enrich: pull the notice detail page for a body paragraph
        enriched: list[dict[str, Any]] = []
        for stub in out[:100]:
            await self._throttle()
            detail = await self._fetch_notice_detail(client, stub["url"])
            enriched.append({**stub, **detail})

        log.info("hse_comah: %d energy-relevant notices found", len(enriched))
        return enriched

    async def parse(self, fetched: list[dict[str, Any]]) -> list[RawItem]:
        items: list[RawItem] = []
        for f in fetched:
            url = f.get("url")
            title = f.get("title")
            if not url or not title:
                continue
            items.append(RawItem(
                source_url=url,
                title=title[:500],
                body_text=f.get("body_text") or f"HSE notice against {f.get('party','')} dated {f.get('date','')}.",
                published_at=_parse_hse_date(f.get("date")),
                filing_type="enforcement_notice",
                procedural_stage=None,
                commission_authority="hse",
                pages=None,
                body_pdf_path=None,
                raw={
                    "party": f.get("party"),
                    "notice_date_text": f.get("date"),
                    "source": "hse_notices",
                },
            ))
        return items

    async def _fetch_notice_detail(
        self, client: httpx.AsyncClient, url: str,
    ) -> dict[str, Any]:
        try:
            r = await client.get(url, timeout=self.http_timeout_s)
            if r.status_code != 200:
                return {}
            html = r.text
        except Exception:
            return {}
        # Strip tags for a body snippet
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return {"body_text": text[:2000]}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _parse_hse_date(v: Any) -> datetime | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def run_once(pool):
    """Convenience entry point for APScheduler + manual CLI invocation."""
    worker = HseComahWorker(pool)
    return await worker.run()

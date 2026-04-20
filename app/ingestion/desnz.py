"""
app/ingestion/desnz.py — GOV.UK ATOM feed for DESNZ publications.

DESNZ (Department for Energy Security & Net Zero) publishes every
consultation, policy paper, NPS designation, AR round announcement and
Capacity Market notice under:

    https://www.gov.uk/government/organisations/department-for-energy-security-and-net-zero

The GOV.UK ATOM feed for that organisation is:

    https://www.gov.uk/government/organisations/department-for-energy-security-and-net-zero.atom

Schedule: daily @ 00:30 UTC.

Classifies ``filing_type`` into: consultation / response / nps_designation /
ar7 / capacity_market / guidance / press_release / misc.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from app.ingestion.base import IngestionWorker, RawItem

log = logging.getLogger("princeps.ingestion.desnz")


_ATOM_URL = (
    "https://www.gov.uk/government/organisations/"
    "department-for-energy-security-and-net-zero.atom"
)

# ATOM namespace
_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Classifier rules — each (regex, filing_type), first-match wins.
_CLASS_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bAR\s*7\b|allocation round 7", re.I), "ar7"),
    (re.compile(r"\bAR\s*8\b|allocation round 8", re.I), "ar8"),
    (re.compile(r"\bCfD\b|contracts? for difference", re.I), "cfd_round"),
    (re.compile(r"capacity market|\bT-\d+\b", re.I), "capacity_market"),
    (re.compile(r"designation|designated|national policy statement|\bNPS\b", re.I), "nps_designation"),
    (re.compile(r"government response|response to (?:the )?consultation", re.I), "consultation_response"),
    (re.compile(r"\bconsultation\b", re.I), "consultation"),
    (re.compile(r"press release|written statement|announcement", re.I), "press_release"),
    (re.compile(r"\bguidance\b", re.I), "guidance"),
    (re.compile(r"\bpolicy paper\b|\bpolicy\b", re.I), "policy"),
]


class DesnzWorker(IngestionWorker):
    """Poll DESNZ ATOM feed → documents(source='desnz')."""

    SOURCE = "desnz"
    req_per_sec = 1.0

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        try:
            r = await client.get(_ATOM_URL, timeout=self.http_timeout_s)
            r.raise_for_status()
        except Exception as e:
            log.warning("desnz: ATOM fetch failed: %s", e)
            return []

        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as e:
            log.warning("desnz: ATOM parse failed: %s", e)
            return []

        entries: list[dict[str, Any]] = []
        for entry in root.findall("atom:entry", _NS):
            title_el = entry.find("atom:title", _NS)
            link_el = entry.find("atom:link", _NS)
            summary_el = entry.find("atom:summary", _NS)
            content_el = entry.find("atom:content", _NS)
            updated_el = entry.find("atom:updated", _NS)
            pub_el = entry.find("atom:published", _NS)
            id_el = entry.find("atom:id", _NS)

            title = (title_el.text or "").strip() if title_el is not None else ""
            url = (link_el.get("href") if link_el is not None else "") or (
                id_el.text if id_el is not None else ""
            )
            summary = (summary_el.text or "").strip() if summary_el is not None else ""
            content = (content_el.text or "").strip() if content_el is not None else ""
            updated = (updated_el.text or "").strip() if updated_el is not None else ""
            published = (pub_el.text or "").strip() if pub_el is not None else updated

            if not title or not url:
                continue

            entries.append({
                "title": title,
                "url": url,
                "body_text": _strip_html(content or summary),
                "published_at": published,
            })

        log.info("desnz: parsed %d ATOM entries", len(entries))
        return entries

    async def parse(self, fetched: list[dict[str, Any]]) -> list[RawItem]:
        items: list[RawItem] = []
        for f in fetched:
            filing_type = _classify_filing_type(f.get("title", ""), f.get("body_text", ""))
            items.append(RawItem(
                source_url=f["url"],
                title=f["title"],
                body_text=f.get("body_text"),
                published_at=_parse_atom_date(f.get("published_at")),
                filing_type=filing_type,
                procedural_stage=None,
                commission_authority="desnz",
                pages=None,
                body_pdf_path=None,
                raw={
                    "feed": "gov.uk/atom",
                },
            ))
        return items


# ── Helpers ──────────────────────────────────────────────────────────────────

def _classify_filing_type(title: str, body: str) -> str:
    hay = f"{title} {body or ''}"
    for pattern, ftype in _CLASS_RULES:
        if pattern.search(hay):
            return ftype
    return "misc"


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(s: str) -> str:
    if not s:
        return ""
    out = _HTML_TAG_RE.sub(" ", s)
    return _WS_RE.sub(" ", out).strip()


def _parse_atom_date(val: str | None) -> datetime | None:
    if not val:
        return None
    s = val.strip()
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d",
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
    worker = DesnzWorker(pool)
    return await worker.run()

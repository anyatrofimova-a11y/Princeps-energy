"""
app/ingestion/ofgem.py — Playwright-driven scrape of Ofgem publications.

Ofgem publishes consultations, decisions, code modifications and open
letters at https://www.ofgem.gov.uk/publications. The page is heavily
JS-rendered (React-like) so a plain httpx fetch returns an empty body;
we use Playwright in headless Chromium mode to wait for the results
list to hydrate, then extract title / date / publication-type / PDF URL
per row.

Schedule: every 6h (see :mod:`app.ingestion.scheduler`).

Output:
  - One :class:`documents` row per publication (source='ofgem').
  - Body text pulled from the linked PDF via pdfplumber when available.
  - ``filing_type`` mirrors the Ofgem publication-type badge
    (``consultation`` / ``decision`` / ``open_letter`` / ``policy`` …).
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.ingestion.base import IngestionWorker, RawItem

log = logging.getLogger("princeps.ingestion.ofgem")


_PUB_LIST_URL = "https://www.ofgem.gov.uk/publications"
_OFGEM_BASE = "https://www.ofgem.gov.uk"


# Known publication-type labels on the Ofgem UI, mapped to the
# ``documents.filing_type`` convention.
_TYPE_MAP = {
    "consultation":          "consultation",
    "open consultation":     "consultation",
    "closed consultation":   "consultation",
    "decision":              "decision",
    "policy decision":       "decision",
    "open letter":           "open_letter",
    "statutory consultation":"consultation",
    "code modification":     "code_modification",
    "tariff":                "tariff",
    "policy":                "policy",
    "guidance":              "guidance",
    "statement":             "statement",
    "investigation":         "investigation",
    "report":                "report",
}


class OfgemWorker(IngestionWorker):
    """Scrape Ofgem /publications via Playwright and upsert to documents."""

    SOURCE = "ofgem"
    req_per_sec = 0.5  # respectful of the render workload
    # Modest cap per run — Ofgem publishes ~15-30 items a week.
    MAX_ITEMS = 60

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Use Playwright to pull the rendered publication list."""
        publications = await self._scrape_publication_list()
        log.info("ofgem: scraped %d publication stubs", len(publications))

        # For each stub, fetch the detail page + the primary PDF if present.
        enriched: list[dict[str, Any]] = []
        for i, pub in enumerate(publications[: self.MAX_ITEMS]):
            await self._throttle()
            detail = await self._fetch_detail(client, pub["url"])
            pdf_url = detail.get("pdf_url") or pub.get("pdf_url")
            body_text: str | None = None
            pages: int | None = None
            if pdf_url:
                body_text, pages = await self._fetch_pdf_text(client, pdf_url)
            enriched.append({
                **pub,
                **detail,
                "pdf_url": pdf_url,
                "body_text": body_text,
                "pages": pages,
            })
            if (i + 1) % 10 == 0:
                log.info("ofgem: enriched %d/%d", i + 1, len(publications[: self.MAX_ITEMS]))

        return enriched

    async def parse(self, fetched: list[dict[str, Any]]) -> list[RawItem]:
        items: list[RawItem] = []
        for f in fetched:
            url = f.get("url") or f.get("pdf_url")
            if not url:
                continue
            title = (f.get("title") or "").strip()
            if not title:
                continue
            pub_at = _parse_date(f.get("published_at"))
            filing_type = _normalise_type(f.get("publication_type"))
            items.append(RawItem(
                source_url=url,
                title=title,
                body_text=f.get("body_text"),
                published_at=pub_at,
                filing_type=filing_type,
                procedural_stage=None,
                commission_authority="ofgem",
                pages=f.get("pages"),
                body_pdf_path=f.get("pdf_url"),
                raw={
                    "publication_type_label": f.get("publication_type"),
                    "topic_area": f.get("topic_area"),
                    "docket_refs": f.get("docket_refs", []),
                },
            ))
        return items

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _scrape_publication_list(self) -> list[dict[str, Any]]:
        """
        Render https://www.ofgem.gov.uk/publications and extract stubs
        ``{title, url, publication_type, published_at, topic_area}``.

        Falls back to an empty list with a warning if Playwright isn't
        installed — useful in CI / container images that haven't run
        ``playwright install``.
        """
        try:
            from playwright.async_api import async_playwright
        except Exception as e:
            log.warning("playwright not importable — ofgem ingestion disabled: %s", e)
            return []

        pubs: list[dict[str, Any]] = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(_PUB_LIST_URL, wait_until="networkidle", timeout=60_000)
                # Try to click through results loading — Ofgem uses a
                # client-side paginator. A single hydration pass gives us
                # the first ~20 items, which is enough for a 6-hour cadence.
                try:
                    await page.wait_for_selector("article, .publication, [class*=result]",
                                                  timeout=20_000)
                except Exception:
                    pass

                # Grab anchors that look like publication links.
                anchors = await page.evaluate(
                    """() => {
                        const out = [];
                        const nodes = document.querySelectorAll('a[href*="/publications/"]');
                        nodes.forEach(a => {
                            const title = (a.innerText || a.textContent || '').trim();
                            if (!title) return;
                            const href = a.href;
                            if (!href.includes('/publications/')) return;
                            if (href.endsWith('/publications') || href.endsWith('/publications/')) return;
                            // Best-effort metadata from a surrounding container
                            const card = a.closest('article, li, div');
                            let pubType = '';
                            let publishedAt = '';
                            let topicArea = '';
                            if (card) {
                                const typeEl = card.querySelector('[class*=type], [class*=category], [class*=badge]');
                                if (typeEl) pubType = typeEl.innerText.trim();
                                const dateEl = card.querySelector('time, [class*=date]');
                                if (dateEl) publishedAt = (dateEl.getAttribute('datetime') || dateEl.innerText || '').trim();
                                const topicEl = card.querySelector('[class*=topic], [class*=tag]');
                                if (topicEl) topicArea = topicEl.innerText.trim();
                            }
                            out.push({
                                title, url: href,
                                publication_type: pubType,
                                published_at: publishedAt,
                                topic_area: topicArea,
                            });
                        });
                        return out;
                    }"""
                )

                # Dedupe on URL, preserve order
                seen: set[str] = set()
                for item in anchors or []:
                    url = item.get("url")
                    if url and url not in seen and "/publications/" in url:
                        seen.add(url)
                        pubs.append(item)

                await browser.close()
        except Exception as e:
            log.exception("ofgem: playwright scrape failed: %s", e)
            return []

        return pubs

    async def _fetch_detail(
        self, client: httpx.AsyncClient, url: str,
    ) -> dict[str, Any]:
        """Fetch the publication detail page and extract a PDF link, if any."""
        try:
            r = await client.get(url, timeout=self.http_timeout_s)
            if r.status_code != 200:
                return {}
            html = r.text
        except Exception as e:
            log.debug("ofgem: detail fetch failed %s: %s", url, e)
            return {}

        out: dict[str, Any] = {}
        pdf_match = re.search(
            r'href="([^"]*\.pdf)"', html, re.I,
        )
        if pdf_match:
            pdf = pdf_match.group(1)
            if pdf.startswith("/"):
                pdf = _OFGEM_BASE + pdf
            out["pdf_url"] = pdf

        # Extract docket-like refs (e.g. CMP / CUSC / BSC P-numbers).
        refs = set(re.findall(r"\b(?:CMP|CUSC|GC|BSC\s*P|DCP)\s*\d+[A-Za-z]?", html, re.I))
        if refs:
            out["docket_refs"] = sorted(refs)
        return out

    async def _fetch_pdf_text(
        self, client: httpx.AsyncClient, pdf_url: str,
    ) -> tuple[str | None, int | None]:
        """Download the PDF and extract text via pdfplumber. Returns (text, pages)."""
        try:
            r = await client.get(pdf_url, timeout=self.http_timeout_s)
            if r.status_code != 200:
                return None, None
            payload = r.content
        except Exception as e:
            log.debug("ofgem: PDF fetch failed %s: %s", pdf_url, e)
            return None, None

        try:
            import pdfplumber
        except Exception as e:
            log.warning("pdfplumber not importable — Ofgem PDFs will have empty body: %s", e)
            return None, None

        try:
            buf = io.BytesIO(payload)
            text_chunks: list[str] = []
            pages: int = 0
            with pdfplumber.open(buf) as pdf:
                pages = len(pdf.pages)
                # Cap extraction at 60 pages; most Ofgem docs are ≤30.
                for p in pdf.pages[:60]:
                    try:
                        chunk = p.extract_text() or ""
                    except Exception:
                        chunk = ""
                    if chunk:
                        text_chunks.append(chunk)
            text = "\n\n".join(text_chunks).strip()
            # Hard cap — too much text blows the documents.body_text row size and
            # downstream embed token budget.
            if len(text) > 200_000:
                text = text[:200_000]
            return (text or None, pages or None)
        except Exception as e:
            log.debug("ofgem: PDF parse failed %s: %s", pdf_url, e)
            return None, None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _normalise_type(label: str | None) -> str | None:
    if not label:
        return None
    clean = label.strip().lower()
    if clean in _TYPE_MAP:
        return _TYPE_MAP[clean]
    for k, v in _TYPE_MAP.items():
        if k in clean:
            return v
    return clean or None


_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d",
    "%d %B %Y",
    "%d %b %Y",
]


def _parse_date(val: str | None) -> datetime | None:
    if not val:
        return None
    val = val.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(val, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def run_once(pool):
    """Convenience entry point for APScheduler + manual CLI invocation."""
    worker = OfgemWorker(pool)
    return await worker.run()

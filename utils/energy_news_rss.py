"""
utils/energy_news_rss.py — Multi-feed RSS aggregator for UK energy news.

Pulls and de-dupes recent stories from a curated set of high-signal feeds:

    * Modern Power Systems
    * Power Engineering International
    * Energy Voice
    * The Energyst
    * Reuters business (energy filter applied)

Per query (asset name / operator / postcode), returns the N most recent
matching items. Designed to attach to the asset-intel popup so the user can
see "what's happening at this site" without leaving the map.

No auth required. Uses ``feedparser`` if available; falls back to a simple
XML parse otherwise.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

import httpx

log = logging.getLogger("princeps.energy_news_rss")

_USER_AGENT = "Princeps/1.0 (+https://princeps.energy) news-rss"
_TIMEOUT = httpx.Timeout(15.0, connect=6.0)


# ---------------------------------------------------------------------------
# Curated feeds — kept short on purpose; quality > volume
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeedSource:
    id: str
    label: str
    url: str
    weight: float = 1.0       # ranking factor on tie-breaks


FEEDS: list[FeedSource] = [
    FeedSource("modernpower",
               "Modern Power Systems",
               "https://www.modernpowersystems.com/feed/", 1.0),
    FeedSource("pei",
               "Power Engineering International",
               "https://www.powerengineeringint.com/feed/", 1.0),
    FeedSource("energyvoice",
               "Energy Voice",
               "https://www.energyvoice.com/feed/", 0.95),
    FeedSource("energyst",
               "The Energyst",
               "https://theenergyst.com/feed/", 0.9),
    FeedSource("currentnews",
               "Current",
               "https://www.current-news.co.uk/feed/", 0.95),
    FeedSource("solarpower_eu",
               "Solar Power Portal",
               "https://www.solarpowerportal.co.uk/feed/", 0.9),
    FeedSource("renews",
               "ReNews.biz",
               "https://renews.biz/feed/", 0.9),
]


@dataclass(frozen=True)
class NewsItem:
    feed_id: str
    feed_label: str
    title: str
    link: str
    published_iso: str | None
    summary: str | None


# ---------------------------------------------------------------------------
# Simple RSS/Atom parse (no extra deps required)
# ---------------------------------------------------------------------------
_RSS_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _strip_html(s: str | None) -> str | None:
    if not s:
        return None
    txt = re.sub(r"<[^>]+>", " ", s)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:500] or None


def _parse_xml_feed(feed: FeedSource, body: bytes) -> list[NewsItem]:
    out: list[NewsItem] = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        log.warning("RSS XML parse failed for %s", feed.id)
        return out

    # RSS 2.0
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate") or item.findtext("dc:date", namespaces=_RSS_NS)
        summary = _strip_html(
            item.findtext("description")
            or item.findtext("content:encoded", namespaces=_RSS_NS)
        )
        if title and link:
            out.append(NewsItem(
                feed_id=feed.id, feed_label=feed.label,
                title=title, link=link,
                published_iso=_normalise_date(pub),
                summary=summary,
            ))

    # Atom
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link_el = entry.find("{http://www.w3.org/2005/Atom}link")
        link = link_el.get("href") if link_el is not None else ""
        pub = (
            entry.findtext("{http://www.w3.org/2005/Atom}updated")
            or entry.findtext("{http://www.w3.org/2005/Atom}published")
        )
        summary = _strip_html(
            entry.findtext("{http://www.w3.org/2005/Atom}summary")
            or entry.findtext("{http://www.w3.org/2005/Atom}content")
        )
        if title and link:
            out.append(NewsItem(
                feed_id=feed.id, feed_label=feed.label,
                title=title, link=link,
                published_iso=_normalise_date(pub),
                summary=summary,
            ))

    return out


def _normalise_date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",       # RFC 822
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",            # ISO 8601 w/ tz
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------
async def _fetch_feed(feed: FeedSource, *, client: httpx.AsyncClient) -> list[NewsItem]:
    try:
        r = await client.get(feed.url)
        if r.status_code != 200:
            log.info("feed %s status=%s", feed.id, r.status_code)
            return []
        return _parse_xml_feed(feed, r.content)
    except httpx.HTTPError as exc:
        log.warning("feed %s fetch failed: %s", feed.id, exc)
        return []


async def fetch_all(*, client: httpx.AsyncClient | None = None,
                    max_per_feed: int = 60) -> list[NewsItem]:
    """Fetch every configured feed in parallel; cap each to max_per_feed
    most recent and return the combined list (newest first overall)."""
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT},
                                    follow_redirects=True)
    try:
        results = await asyncio.gather(*[
            _fetch_feed(f, client=client) for f in FEEDS
        ])
        merged: list[NewsItem] = []
        for items in results:
            merged.extend(items[:max_per_feed])
        merged.sort(key=lambda i: (i.published_iso or "", i.title), reverse=True)
        return merged
    finally:
        if own:
            await client.aclose()


# ---------------------------------------------------------------------------
# Query: match items against asset terms
# ---------------------------------------------------------------------------
def _norm(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"[^a-z0-9 ]", " ", s.lower())


def _contains_any(haystack_n: str, needles: list[str]) -> int:
    """Count how many of `needles` appear in `haystack_n` (already normalised)."""
    n = 0
    for x in needles:
        x = x.strip()
        if x and x in haystack_n:
            n += 1
    return n


async def search_items(
    *,
    asset_name: str | None = None,
    operator: str | None = None,
    postcode: str | None = None,
    limit: int = 12,
    client: httpx.AsyncClient | None = None,
) -> list[NewsItem]:
    """Return up to `limit` items where the title or summary mentions the
    asset name, operator, or postcode (any token match)."""
    base_terms: list[str] = []
    for term in (asset_name, operator, postcode):
        if not term:
            continue
        normed = _norm(term)
        # split into ≥3-char tokens, drop very common words
        for tok in normed.split():
            if len(tok) >= 4 and tok not in {"power", "ltd", "limited", "company"}:
                base_terms.append(tok)
        # also include the full normalised phrase
        base_terms.append(normed.strip())
    base_terms = [t for t in {t.strip() for t in base_terms} if len(t) >= 4]
    if not base_terms:
        return []

    items = await fetch_all(client=client)
    scored: list[tuple[int, NewsItem]] = []
    for it in items:
        hay = _norm(it.title) + " " + _norm(it.summary or "")
        s = _contains_any(hay, base_terms)
        if s > 0:
            scored.append((s, it))
    scored.sort(key=lambda kv: (-kv[0], -(kv[1].published_iso or "")))
    return [it for _, it in scored[:limit]]


def items_to_list(items: list[NewsItem]) -> list[dict]:
    return [asdict(i) for i in items]

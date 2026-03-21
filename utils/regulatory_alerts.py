"""
Regulatory Alert System — monitors Ofgem, NESO, and DNO policy changes.

Surfaces relevant developments for energy developers building grid-connected
projects in the UK.  Uses keyword-based relevance classification (HIGH/MEDIUM/LOW)
and caches results for 1 hour to avoid hammering source websites.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

log = logging.getLogger("princeps.regulatory_alerts")

_TIMEOUT = 25  # seconds per HTTP request
_CACHE_TTL = 3600  # 1 hour

# ── In-memory cache ──────────────────────────────────────────────────────

_cache: dict[str, dict[str, Any]] = {}


def _cache_get(key: str) -> list[dict] | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data: list[dict]):
    _cache[key] = {"ts": time.time(), "data": data}


# ── Keyword relevance classification ────────────────────────────────────

HIGH_KEYWORDS = [
    "grid connection", "g99", "g98", "queue reform", "connection charging",
    "distributed generation", "export limitation", "anm",
    "active network management", "flexibility", "connection offer",
    "queue management", "connection application", "connection policy",
    "significant code review", "access scr", "tme reform",
]

MEDIUM_KEYWORDS = [
    "network capacity", "reinforcement", "riio", "price control",
    "embedded generation", "network access", "constraint", "curtailment",
    "dno", "distribution network", "transmission", "storage",
    "battery", "demand connection", "generation capacity",
    "network charges", "use of system", "duos", "tnuos",
]

LOW_KEYWORDS = [
    "energy", "electricity", "ofgem", "licence", "code", "regulation",
    "consultation", "decision", "policy", "network", "power",
]

IMPACT_KEYWORD_MAP = {
    "grid_connection": [
        "grid connection", "connection offer", "connection application",
        "g99", "g98", "queue", "connection charging", "connection cost",
    ],
    "charging": [
        "connection charging", "charging methodology", "duos", "tnuos",
        "use of system", "network charges", "tariff",
    ],
    "capacity": [
        "network capacity", "headroom", "constraint", "curtailment",
        "reinforcement", "capacity", "demand",
    ],
    "flexibility": [
        "flexibility", "anm", "active network management",
        "export limitation", "curtailment", "demand side response",
    ],
    "queue_reform": [
        "queue reform", "queue management", "connection queue",
        "gate closure", "milestone", "tme",
    ],
    "planning": [
        "planning", "consent", "epr", "dco", "nsip", "eia",
    ],
    "storage": [
        "storage", "battery", "bess", "co-location",
    ],
}

# ── Category classification ─────────────────────────────────────────────

OFGEM_CATEGORY_KEYWORDS = {
    "connection_policy": [
        "connection", "g99", "g98", "queue", "offer", "application",
    ],
    "charging_methodology": [
        "charging", "duos", "tnuos", "tariff", "use of system",
        "network charges",
    ],
    "licence_changes": [
        "licence", "license", "obligation", "condition",
    ],
    "code_modifications": [
        "code modification", "cusc", "dcusa", "grid code", "bsc",
        "significant code review",
    ],
    "enforcement": [
        "enforcement", "penalty", "compliance", "investigation",
    ],
}

NESO_CATEGORY_KEYWORDS = {
    "scenarios": [
        "future energy scenarios", "fes", "pathway", "scenario",
    ],
    "capacity": [
        "capacity", "etys", "electricity ten year", "network options",
        "noa", "operability",
    ],
    "queue": [
        "queue", "connection", "tec", "transmission entry",
    ],
    "operability": [
        "operability", "stability", "inertia", "frequency", "voltage",
        "balancing",
    ],
}


def _classify_relevance(text: str) -> str:
    """Return HIGH / MEDIUM / LOW based on keyword presence."""
    lower = text.lower()
    for kw in HIGH_KEYWORDS:
        if kw in lower:
            return "HIGH"
    for kw in MEDIUM_KEYWORDS:
        if kw in lower:
            return "MEDIUM"
    return "LOW"


def _classify_category(text: str, keyword_map: dict[str, list[str]]) -> str:
    """Return best-matching category from a keyword map."""
    lower = text.lower()
    best, best_count = "general", 0
    for category, keywords in keyword_map.items():
        count = sum(1 for kw in keywords if kw in lower)
        if count > best_count:
            best, best_count = category, count
    return best


def _extract_impact_areas(text: str) -> list[str]:
    """Return list of impact area tags based on keyword matches."""
    lower = text.lower()
    areas = []
    for area, keywords in IMPACT_KEYWORD_MAP.items():
        if any(kw in lower for kw in keywords):
            areas.append(area)
    return areas or ["general"]


def _make_alert(
    source: str,
    title: str,
    summary: str,
    url: str,
    published: str | None,
    category_map: dict[str, list[str]],
) -> dict:
    """Build a standardised alert dict."""
    combined = f"{title} {summary}"
    alert_id = hashlib.sha256(f"{source}:{url}:{title}".encode()).hexdigest()[:16]
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "id": alert_id,
        "source": source,
        "title": title.strip(),
        "summary": summary.strip()[:500],
        "url": url,
        "published": published or now_iso,
        "category": _classify_category(combined, category_map),
        "relevance": _classify_relevance(combined),
        "impact_areas": _extract_impact_areas(combined),
        "fetched_at": now_iso,
    }


# ── HTTP helpers ────────────────────────────────────────────────────────

async def _fetch_text(url: str, params: dict | None = None) -> str | None:
    """GET a URL and return body text, or None on failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Princeps/1.0 (energy-feasibility)"},
        ) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        log.warning("Failed to fetch %s: %s", url, exc)
        return None


async def _fetch_json(url: str, params: dict | None = None) -> Any | None:
    """GET a URL and return parsed JSON, or None on failure."""
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Princeps/1.0 (energy-feasibility)"},
        ) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        log.warning("Failed to fetch JSON %s: %s", url, exc)
        return None


# ── HTML extraction helpers ─────────────────────────────────────────────

def _extract_links_from_html(html: str, base_url: str) -> list[dict]:
    """
    Extract title/url/summary from HTML list pages.
    Looks for <a> tags inside heading or list-item structures.
    Returns list of {title, url, summary}.
    """
    results = []
    # Match heading links: <h2|h3|h4 ...><a href="...">title</a>
    heading_pattern = re.compile(
        r'<h[2-4][^>]*>\s*<a\s+href="([^"]+)"[^>]*>([^<]+)</a>',
        re.IGNORECASE,
    )
    for match in heading_pattern.finditer(html):
        href, title = match.group(1), match.group(2)
        if not href.startswith("http"):
            href = base_url.rstrip("/") + "/" + href.lstrip("/")
        # Try to grab a summary from the next <p> or <div> after the heading
        after = html[match.end(): match.end() + 500]
        summary_match = re.search(r"<p[^>]*>([^<]{10,300})</p>", after, re.IGNORECASE)
        summary = summary_match.group(1).strip() if summary_match else ""
        results.append({"title": title.strip(), "url": href, "summary": summary})

    # Also match <a> inside <li> items (common on gov/regulatory sites)
    li_pattern = re.compile(
        r'<li[^>]*>\s*<a\s+href="([^"]+)"[^>]*>([^<]+)</a>',
        re.IGNORECASE,
    )
    seen_urls = {r["url"] for r in results}
    for match in li_pattern.finditer(html):
        href, title = match.group(1), match.group(2)
        if not href.startswith("http"):
            href = base_url.rstrip("/") + "/" + href.lstrip("/")
        if href not in seen_urls:
            results.append({"title": title.strip(), "url": href, "summary": ""})
            seen_urls.add(href)

    return results


def _extract_date_from_text(text: str) -> str | None:
    """Try to extract a date from nearby text (DD Month YYYY or YYYY-MM-DD)."""
    patterns = [
        (r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
         r"September|October|November|December)\s+(\d{4})", "%d %B %Y"),
        (r"(\d{4})-(\d{2})-(\d{2})", None),
    ]
    for pat, fmt in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            if fmt:
                try:
                    dt = datetime.strptime(m.group(0), fmt)
                    return dt.replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    pass
            else:
                try:
                    dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                  tzinfo=timezone.utc)
                    return dt.isoformat()
                except ValueError:
                    pass
    return None


# ═══════════════════════════════════════════════════════════════════════
# Ofgem alerts
# ═══════════════════════════════════════════════════════════════════════

OFGEM_BASE = "https://www.ofgem.gov.uk"
OFGEM_PUBLICATIONS_URL = f"{OFGEM_BASE}/publications"
OFGEM_RSS_URL = f"{OFGEM_BASE}/publications/rss"

# Ofgem search queries targeting connection/DG policy
OFGEM_SEARCH_QUERIES = [
    "connection charging",
    "distributed generation",
    "network access",
    "grid connection",
    "queue reform",
    "significant code review",
    "flexibility",
]


async def fetch_ofgem_alerts() -> list[dict]:
    """
    Fetch recent Ofgem publications relevant to energy developers.
    Tries RSS first, falls back to HTML scraping of the publications page.
    """
    cached = _cache_get("ofgem")
    if cached is not None:
        return cached

    alerts: list[dict] = []
    seen_urls: set[str] = set()

    # 1) Try RSS feed
    rss_text = await _fetch_text(OFGEM_RSS_URL)
    if rss_text and "<item" in rss_text.lower():
        alerts.extend(_parse_ofgem_rss(rss_text, seen_urls))

    # 2) Scrape the publications listing page
    html = await _fetch_text(OFGEM_PUBLICATIONS_URL)
    if html:
        for item in _extract_links_from_html(html, OFGEM_BASE):
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            pub_date = _extract_date_from_text(item.get("summary", ""))
            alerts.append(
                _make_alert(
                    source="ofgem",
                    title=item["title"],
                    summary=item.get("summary", ""),
                    url=item["url"],
                    published=pub_date,
                    category_map=OFGEM_CATEGORY_KEYWORDS,
                )
            )

    # 3) Targeted search for connection/DG topics via Ofgem site search
    for query in OFGEM_SEARCH_QUERIES[:3]:  # limit to avoid rate-limiting
        search_url = f"{OFGEM_BASE}/search/site/{query.replace(' ', '%20')}"
        search_html = await _fetch_text(search_url)
        if search_html:
            for item in _extract_links_from_html(search_html, OFGEM_BASE):
                if item["url"] in seen_urls:
                    continue
                seen_urls.add(item["url"])
                pub_date = _extract_date_from_text(item.get("summary", ""))
                alerts.append(
                    _make_alert(
                        source="ofgem",
                        title=item["title"],
                        summary=item.get("summary", ""),
                        url=item["url"],
                        published=pub_date,
                        category_map=OFGEM_CATEGORY_KEYWORDS,
                    )
                )

    # Sort by relevance (HIGH first) then by published date descending
    relevance_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    alerts.sort(key=lambda a: (relevance_order.get(a["relevance"], 3), a["published"] or ""), reverse=False)

    _cache_set("ofgem", alerts)
    log.info("Fetched %d Ofgem alerts", len(alerts))
    return alerts


def _parse_ofgem_rss(rss_text: str, seen_urls: set[str]) -> list[dict]:
    """Parse a basic RSS feed for Ofgem publications."""
    alerts = []
    items = re.findall(r"<item>(.*?)</item>", rss_text, re.DOTALL | re.IGNORECASE)
    for item_xml in items:
        title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item_xml, re.DOTALL)
        link_m = re.search(r"<link>(.*?)</link>", item_xml, re.DOTALL)
        desc_m = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", item_xml, re.DOTALL)
        pub_m = re.search(r"<pubDate>(.*?)</pubDate>", item_xml, re.DOTALL)

        title = title_m.group(1).strip() if title_m else "Untitled"
        url = link_m.group(1).strip() if link_m else ""
        summary = desc_m.group(1).strip() if desc_m else ""
        # Strip HTML tags from summary
        summary = re.sub(r"<[^>]+>", "", summary)

        pub_date = None
        if pub_m:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pub_m.group(1).strip())
                pub_date = dt.isoformat()
            except Exception:
                pub_date = _extract_date_from_text(pub_m.group(1))

        if url and url not in seen_urls:
            seen_urls.add(url)
            alerts.append(
                _make_alert(
                    source="ofgem",
                    title=title,
                    summary=summary,
                    url=url,
                    published=pub_date,
                    category_map=OFGEM_CATEGORY_KEYWORDS,
                )
            )
    return alerts


# ═══════════════════════════════════════════════════════════════════════
# NESO alerts
# ═══════════════════════════════════════════════════════════════════════

NESO_BASE = "https://www.neso.energy"
NESO_PUBLICATIONS_URL = f"{NESO_BASE}/publications"

# Known NESO landing pages for key reports
NESO_KEY_PAGES = [
    (f"{NESO_BASE}/publications/future-energy-scenarios-fes", "FES (Future Energy Scenarios)"),
    (f"{NESO_BASE}/publications/electricity-ten-year-statement-etys", "ETYS"),
    (f"{NESO_BASE}/publications/network-options-assessment-noa", "NOA (Network Options Assessment)"),
    (f"{NESO_BASE}/publications/connections", "Connection Queue Reports"),
    (f"{NESO_BASE}/publications/operability", "Operability Reports"),
]


async def fetch_neso_alerts() -> list[dict]:
    """
    Fetch recent NESO publications relevant to energy developers.
    Scrapes publications listing and key report pages.
    """
    cached = _cache_get("neso")
    if cached is not None:
        return cached

    alerts: list[dict] = []
    seen_urls: set[str] = set()

    # 1) Main publications listing
    html = await _fetch_text(NESO_PUBLICATIONS_URL)
    if html:
        for item in _extract_links_from_html(html, NESO_BASE):
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            pub_date = _extract_date_from_text(item.get("summary", ""))
            alerts.append(
                _make_alert(
                    source="neso",
                    title=item["title"],
                    summary=item.get("summary", ""),
                    url=item["url"],
                    published=pub_date,
                    category_map=NESO_CATEGORY_KEYWORDS,
                )
            )

    # 2) Scrape known key report pages for sub-links
    for page_url, page_label in NESO_KEY_PAGES:
        page_html = await _fetch_text(page_url)
        if page_html:
            for item in _extract_links_from_html(page_html, NESO_BASE):
                if item["url"] in seen_urls:
                    continue
                seen_urls.add(item["url"])
                pub_date = _extract_date_from_text(item.get("summary", ""))
                combined_title = item["title"]
                if page_label and page_label.lower() not in combined_title.lower():
                    combined_title = f"{page_label}: {combined_title}"
                alerts.append(
                    _make_alert(
                        source="neso",
                        title=combined_title,
                        summary=item.get("summary", ""),
                        url=item["url"],
                        published=pub_date,
                        category_map=NESO_CATEGORY_KEYWORDS,
                    )
                )

    relevance_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    alerts.sort(key=lambda a: (relevance_order.get(a["relevance"], 3),))

    _cache_set("neso", alerts)
    log.info("Fetched %d NESO alerts", len(alerts))
    return alerts


# ═══════════════════════════════════════════════════════════════════════
# DNO alerts
# ═══════════════════════════════════════════════════════════════════════

# Known DNO connection policy pages
DNO_SOURCES = {
    "dno_ukpn": {
        "name": "UK Power Networks",
        "base": "https://www.ukpowernetworks.co.uk",
        "pages": [
            "https://www.ukpowernetworks.co.uk/electricity/distribution-energy-resource/connection-offers",
            "https://www.ukpowernetworks.co.uk/electricity/distribution-energy-resource/flexible-connections",
            "https://www.ukpowernetworks.co.uk/about-us/connection-charging",
        ],
    },
    "dno_ssen": {
        "name": "Scottish and Southern Electricity Networks",
        "base": "https://www.ssen.co.uk",
        "pages": [
            "https://www.ssen.co.uk/connections/generation-connections/",
            "https://www.ssen.co.uk/about-ssen/dso/flexibility/",
            "https://www.ssen.co.uk/about-ssen/our-charges/connection-charging/",
        ],
    },
    "dno_npg": {
        "name": "Northern Powergrid",
        "base": "https://www.northernpowergrid.com",
        "pages": [
            "https://www.northernpowergrid.com/connections/generation",
            "https://www.northernpowergrid.com/asset-management/flexibility",
            "https://www.northernpowergrid.com/connections/connection-charging",
        ],
    },
    "dno_nged": {
        "name": "National Grid Electricity Distribution",
        "base": "https://www.nationalgrid.co.uk",
        "pages": [
            "https://www.nationalgrid.co.uk/connections/generation-connections",
            "https://www.nationalgrid.co.uk/our-network/flexibility-hub",
            "https://connecteddata.nationalgrid.co.uk/",
        ],
    },
    "dno_spen": {
        "name": "SP Energy Networks",
        "base": "https://www.spenergynetworks.co.uk",
        "pages": [
            "https://www.spenergynetworks.co.uk/pages/generation_connections.aspx",
            "https://www.spenergynetworks.co.uk/pages/connection_charging.aspx",
            "https://www.spenergynetworks.co.uk/pages/flexibility.aspx",
        ],
    },
    "dno_enwl": {
        "name": "Electricity North West",
        "base": "https://www.enwl.co.uk",
        "pages": [
            "https://www.enwl.co.uk/get-connected/generation-and-storage/",
            "https://www.enwl.co.uk/get-connected/connection-charging/",
            "https://www.enwl.co.uk/future-energy/flexibility/",
        ],
    },
}


async def fetch_dno_alerts() -> list[dict]:
    """
    Fetch connection policy updates from all 6 UK DNO websites.
    Scrapes each DNO's connection policy / charging / flexibility pages
    and extracts any publication links.
    """
    cached = _cache_get("dno")
    if cached is not None:
        return cached

    alerts: list[dict] = []
    seen_urls: set[str] = set()

    for source_key, dno_info in DNO_SOURCES.items():
        dno_name = dno_info["name"]
        base = dno_info["base"]

        for page_url in dno_info["pages"]:
            html = await _fetch_text(page_url)
            if not html:
                continue

            for item in _extract_links_from_html(html, base):
                url = item["url"]
                if url in seen_urls:
                    continue
                # Filter out non-relevant links (navigation, footer, etc.)
                title_lower = item["title"].lower()
                if len(item["title"]) < 10:
                    continue
                if any(skip in title_lower for skip in [
                    "cookie", "privacy", "terms", "contact us", "sitemap",
                    "login", "register", "home", "search", "menu",
                ]):
                    continue

                seen_urls.add(url)
                pub_date = _extract_date_from_text(item.get("summary", ""))
                alerts.append(
                    _make_alert(
                        source=source_key,
                        title=f"[{dno_name}] {item['title']}",
                        summary=item.get("summary", ""),
                        url=url,
                        published=pub_date,
                        category_map=OFGEM_CATEGORY_KEYWORDS,  # reuse — same concepts
                    )
                )

    relevance_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    alerts.sort(key=lambda a: (relevance_order.get(a["relevance"], 3),))

    _cache_set("dno", alerts)
    log.info("Fetched %d DNO alerts", len(alerts))
    return alerts


# ═══════════════════════════════════════════════════════════════════════
# Combined API
# ═══════════════════════════════════════════════════════════════════════

async def get_all_regulatory_alerts(
    filter_relevance: str | None = None,
    filter_source: str | None = None,
    filter_category: str | None = None,
    filter_impact: str | None = None,
    limit: int = 50,
) -> dict:
    """
    Aggregate alerts from all sources, apply optional filters, return
    sorted by relevance then date.

    Parameters
    ----------
    filter_relevance : HIGH, MEDIUM, or LOW — only return this level.
    filter_source    : ofgem, neso, dno_ukpn, etc. — restrict to one source.
    filter_category  : connection_policy, charging_methodology, scenarios, etc.
    filter_impact    : grid_connection, charging, capacity, flexibility, etc.
    limit            : max alerts to return (default 50).
    """
    import asyncio

    # Fetch all three sources concurrently
    ofgem_task = asyncio.create_task(fetch_ofgem_alerts())
    neso_task = asyncio.create_task(fetch_neso_alerts())
    dno_task = asyncio.create_task(fetch_dno_alerts())

    ofgem_alerts = await ofgem_task
    neso_alerts = await neso_task
    dno_alerts = await dno_task

    all_alerts = ofgem_alerts + neso_alerts + dno_alerts

    # Apply filters
    if filter_relevance:
        filter_relevance = filter_relevance.upper()
        all_alerts = [a for a in all_alerts if a["relevance"] == filter_relevance]

    if filter_source:
        all_alerts = [a for a in all_alerts if a["source"] == filter_source]

    if filter_category:
        all_alerts = [a for a in all_alerts if a["category"] == filter_category]

    if filter_impact:
        all_alerts = [a for a in all_alerts if filter_impact in a["impact_areas"]]

    # Sort: HIGH first, then by published desc
    relevance_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    all_alerts.sort(
        key=lambda a: (
            relevance_order.get(a["relevance"], 3),
            a.get("published") or "",
        ),
    )
    # HIGH items: most recent first (reverse published within HIGH)
    # We do a stable two-pass: first reverse by date, then stable sort by relevance
    all_alerts.sort(key=lambda a: a.get("published") or "", reverse=True)
    all_alerts.sort(key=lambda a: relevance_order.get(a["relevance"], 3))

    total = len(all_alerts)
    all_alerts = all_alerts[:limit]

    # Summary counts
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    source_counts: dict[str, int] = {}
    for a in all_alerts:
        counts[a["relevance"]] = counts.get(a["relevance"], 0) + 1
        source_counts[a["source"]] = source_counts.get(a["source"], 0) + 1

    return {
        "total": total,
        "returned": len(all_alerts),
        "relevance_counts": counts,
        "source_counts": source_counts,
        "alerts": all_alerts,
    }


def clear_cache():
    """Clear all cached alerts (useful for testing or forced refresh)."""
    _cache.clear()
    log.info("Regulatory alerts cache cleared")

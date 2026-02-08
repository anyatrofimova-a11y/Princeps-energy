"""
UK Energy Tender Tracker
Queries 3 UK government procurement APIs for battery/energy storage tenders.
Sources: Sell2Wales, Find a Tender, Contracts Finder.
"""

import json
import asyncio
import time
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen, Request
from urllib.parse import quote_plus
from typing import Optional

# Simple in-memory cache (refresh every 4 hours)
_cache = {"data": None, "ts": 0}
_CACHE_TTL = 4 * 3600  # 4 hours

KEYWORDS = [
    "battery", "batteries", "energy storage", "bess",
    "solar pv", "photovoltaic", "renewable energy",
    "inverter", "ev charging", "electric vehicle charging",
    "microgrid", "grid connection", "substation",
    "heat pump", "district heating", "hydrogen",
]

KEYWORD_QUERY = " OR ".join(f'"{k}"' for k in KEYWORDS[:6])  # API query limit


def _fetch_json(url: str, timeout: int = 15) -> Optional[dict]:
    """Fetch JSON from a URL, return None on failure."""
    try:
        req = Request(url, headers={"Accept": "application/json", "User-Agent": "Feasibly/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _matches_keywords(text: str) -> bool:
    """Check if text matches any energy keyword."""
    lower = text.lower()
    return any(kw in lower for kw in KEYWORDS)


def _parse_date(s: Optional[str]) -> Optional[str]:
    """Parse ISO date string to YYYY-MM-DD."""
    if not s:
        return None
    try:
        return s[:10]
    except Exception:
        return None


def fetch_sell2wales() -> list[dict]:
    """Query Sell2Wales (Welsh Government) OCDS API."""
    results = []
    since = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%dT00:00:00Z")
    for stage in ["tender", "planning", "award", "contract"]:
        url = (
            f"https://api.sell2wales.gov.wales/ocds/releases?"
            f"publishedFrom={quote_plus(since)}&stage={stage}&size=100"
        )
        data = _fetch_json(url)
        if not data or "releases" not in data:
            continue
        for rel in data["releases"]:
            tender = rel.get("tender", {})
            title = tender.get("title", "") or rel.get("tag", [""])[0]
            desc = tender.get("description", "")
            combined = f"{title} {desc}"
            if not _matches_keywords(combined):
                continue
            buyer = ""
            parties = rel.get("parties", [])
            for p in parties:
                if "buyer" in p.get("roles", []):
                    buyer = p.get("name", "")
                    break

            value = tender.get("value", {})
            results.append({
                "title": title,
                "description": (desc or "")[:300],
                "buyer": buyer,
                "value_gbp": value.get("amount"),
                "currency": value.get("currency", "GBP"),
                "deadline": _parse_date(tender.get("tenderPeriod", {}).get("endDate")),
                "published": _parse_date(rel.get("date")),
                "source": "Sell2Wales",
                "url": f"https://www.sell2wales.gov.wales/search/search_switch.aspx?ID={rel.get('ocid', '')}",
            })
    return results


def fetch_find_a_tender() -> list[dict]:
    """Query Find a Tender (UK central government, post-Brexit OJEU replacement)."""
    results = []
    since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
    base = "https://find-tender.service.gov.uk/api/1.0/ocdsReleasePackages"
    page = 1
    while page <= 5:  # max 5 pages
        url = f"{base}?publishedFrom={quote_plus(since)}&size=200&page={page}"
        data = _fetch_json(url)
        if not data:
            break
        releases = data.get("releases") or data.get("results", [])
        if not releases:
            break
        for rel in releases:
            tender = rel.get("tender", {})
            title = tender.get("title", "")
            desc = tender.get("description", "")
            combined = f"{title} {desc}"
            if not _matches_keywords(combined):
                continue
            buyer = ""
            parties = rel.get("parties", [])
            for p in parties:
                if "buyer" in p.get("roles", []):
                    buyer = p.get("name", "")
                    break

            value = tender.get("value", {})
            ocid = rel.get("ocid", "")
            results.append({
                "title": title,
                "description": (desc or "")[:300],
                "buyer": buyer,
                "value_gbp": value.get("amount"),
                "currency": value.get("currency", "GBP"),
                "deadline": _parse_date(tender.get("tenderPeriod", {}).get("endDate")),
                "published": _parse_date(rel.get("date")),
                "source": "Find a Tender",
                "url": f"https://find-tender.service.gov.uk/Notice/{ocid.split('-')[-1]}" if ocid else "",
            })
        page += 1
    return results


def fetch_contracts_finder() -> list[dict]:
    """Query Contracts Finder (English public sector procurement)."""
    results = []
    since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT00:00:00Z")
    base = "https://contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
    page = 1
    while page <= 5:
        url = f"{base}?publishedFrom={quote_plus(since)}&size=200&page={page}"
        data = _fetch_json(url)
        if not data:
            break
        releases = data.get("releases", [])
        if not releases:
            break
        for rel in releases:
            tender = rel.get("tender", {})
            title = tender.get("title", "")
            desc = tender.get("description", "")
            combined = f"{title} {desc}"
            if not _matches_keywords(combined):
                continue
            buyer = ""
            parties = rel.get("parties", [])
            for p in parties:
                if "buyer" in p.get("roles", []):
                    buyer = p.get("name", "")
                    break

            value = tender.get("value", {})
            ocid = rel.get("ocid", "")
            results.append({
                "title": title,
                "description": (desc or "")[:300],
                "buyer": buyer,
                "value_gbp": value.get("amount"),
                "currency": value.get("currency", "GBP"),
                "deadline": _parse_date(tender.get("tenderPeriod", {}).get("endDate")),
                "published": _parse_date(rel.get("date")),
                "source": "Contracts Finder",
                "url": f"https://contractsfinder.service.gov.uk/Notice/{ocid.split('-')[-1]}" if ocid else "",
            })
        page += 1
    return results


def fetch_all_tenders() -> dict:
    """Fetch from all 3 sources, merge, deduplicate, sort by deadline. Cached 4h."""
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    all_tenders = []
    errors = []

    for name, fetcher in [
        ("Sell2Wales", fetch_sell2wales),
        ("Find a Tender", fetch_find_a_tender),
        ("Contracts Finder", fetch_contracts_finder),
    ]:
        try:
            tenders = fetcher()
            all_tenders.extend(tenders)
        except Exception as e:
            errors.append(f"{name}: {e}")

    # Deduplicate by title similarity
    seen_titles = set()
    unique = []
    for t in all_tenders:
        key = t["title"].lower().strip()[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(t)

    # Sort by deadline (nearest first), nulls last
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    unique.sort(key=lambda t: t.get("deadline") or "9999-12-31")

    # Split into active (deadline >= today) and expired
    active = [t for t in unique if (t.get("deadline") or "9999") >= today]
    expired = [t for t in unique if t.get("deadline") and t["deadline"] < today]

    # Summary stats
    total_value = sum(t["value_gbp"] for t in active if t.get("value_gbp"))
    by_source = {}
    for t in active:
        by_source[t["source"]] = by_source.get(t["source"], 0) + 1

    result = {
        "tenders": active[:50],  # cap at 50 most urgent
        "expired_count": len(expired),
        "total_active": len(active),
        "total_value_gbp": total_value,
        "by_source": by_source,
        "keywords": KEYWORDS,
        "errors": errors,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache["data"] = result
    _cache["ts"] = time.time()
    return result

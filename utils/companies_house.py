"""
Companies House integration — identify landowner companies near development sites.

Uses the free Companies House API to:
- Search companies by postcode/address
- Get company details (directors, filing history)
- Cross-reference with land registry data

API docs: https://developer.company-information.service.gov.uk/
Rate limit: 600 requests per 5 minutes (free tier)

Note: API key needed — set COMPANIES_HOUSE_API_KEY env var.
Falls back gracefully if key not set.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

log = logging.getLogger("princeps.companies_house")

# ── Config ──
API_KEY = os.environ.get("COMPANIES_HOUSE_API_KEY", "")
BASE_URL = "https://api.company-information.service.gov.uk"
POSTCODES_IO = "https://api.postcodes.io"

# ── Cache ── (in-memory, 24h TTL)
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 86400  # 24 hours


def _cache_get(key: str) -> Any | None:
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return data
        del _cache[key]
    return None


def _cache_set(key: str, data: Any) -> None:
    _cache[key] = (time.time(), data)
    # Prune if cache gets too large
    if len(_cache) > 2000:
        cutoff = time.time() - CACHE_TTL
        expired = [k for k, (ts, _) in _cache.items() if ts < cutoff]
        for k in expired:
            del _cache[k]


# ── SIC code filters for energy/land relevance ──
# Agriculture: 01xxx, Real estate: 68xxx, Electricity: 35xxx, Construction: 41-43xxx
# Also include: mining/quarrying (06-09), water (36-39), land transport (49)
RELEVANT_SIC_PREFIXES = (
    "01",   # Agriculture, forestry, fishing
    "02",   # Forestry and logging
    "06",   # Extraction of crude petroleum/gas
    "08",   # Other mining and quarrying
    "35",   # Electricity, gas, steam, air conditioning
    "36",   # Water collection, treatment, supply
    "38",   # Waste collection, treatment, disposal
    "41",   # Construction of buildings
    "42",   # Civil engineering
    "43",   # Specialised construction activities
    "46.73", # Wholesale of wood/construction materials
    "68",   # Real estate activities
    "70",   # Activities of head offices; management consultancy
    "71",   # Architectural/engineering activities
    "81.30", # Landscape service activities
)

SIC_CATEGORY_MAP = {
    "01": "agriculture",
    "02": "forestry",
    "06": "energy_extraction",
    "08": "mining",
    "35": "electricity_gas",
    "36": "water",
    "38": "waste",
    "41": "construction",
    "42": "civil_engineering",
    "43": "construction_specialist",
    "68": "real_estate",
    "70": "management",
    "71": "engineering",
    "81": "landscape",
}


def _classify_sic(sic_codes: list[str]) -> list[str]:
    """Return human-readable categories for SIC codes."""
    categories = []
    for sic in sic_codes:
        for prefix, cat in SIC_CATEGORY_MAP.items():
            if sic.startswith(prefix):
                if cat not in categories:
                    categories.append(cat)
                break
    return categories


def _is_relevant_sic(sic_codes: list[str]) -> bool:
    """Check if any SIC codes match land/energy/property relevance."""
    if not sic_codes:
        return False
    return any(
        sic.startswith(prefix)
        for sic in sic_codes
        for prefix in RELEVANT_SIC_PREFIXES
    )


def _relevance_score(company: dict, sic_codes: list[str]) -> float:
    """Score 0-100 for how relevant a company is to energy land development."""
    score = 0.0

    # SIC-based scoring
    for sic in sic_codes:
        if sic.startswith("68"):    # Real estate — highest relevance
            score += 30
        elif sic.startswith("01"):  # Agriculture — land owners
            score += 25
        elif sic.startswith("35"):  # Electricity/energy
            score += 25
        elif sic.startswith("42"):  # Civil engineering
            score += 15
        elif sic.startswith("41") or sic.startswith("43"):  # Construction
            score += 10
        elif sic.startswith("71"):  # Architecture/engineering
            score += 10
        elif sic.startswith("02"):  # Forestry
            score += 15

    # Company type bonus
    ctype = company.get("company_type", "").lower()
    if "llp" in ctype or "limited" in ctype:
        score += 5

    # Active status bonus
    if company.get("company_status", "").lower() == "active":
        score += 10

    return min(score, 100)


def _auth() -> tuple[str, str]:
    """Basic auth tuple: API key as username, empty password."""
    return (API_KEY, "")


async def _latlon_to_postcode(lat: float, lon: float) -> str | None:
    """Convert lat/lon to UK postcode using postcodes.io (free, no key)."""
    cache_key = f"pc:{lat:.4f},{lon:.4f}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{POSTCODES_IO}/postcodes",
                params={"lon": lon, "lat": lat, "limit": 1},
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("result")
                if results and len(results) > 0:
                    pc = results[0].get("postcode")
                    _cache_set(cache_key, pc)
                    return pc
    except Exception as e:
        log.warning("postcodes.io reverse geocode failed: %s", e)
    return None


async def search_companies_near(
    postcode: str,
    *,
    radius_km: float = 5,
    size: int = 100,
) -> list[dict]:
    """
    Search Companies House for active companies near a postcode.

    Uses the advanced search endpoint with location filter.
    Filters for relevant SIC codes (agriculture, real estate, electricity, construction).

    Returns list of:
        {"company_number", "name", "address", "type", "status", "sic_codes", "categories"}
    """
    if not API_KEY:
        return []

    cache_key = f"ch_near:{postcode}:{radius_km}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    results = []

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # Companies House advanced search
            resp = await client.get(
                f"{BASE_URL}/advanced-search/companies",
                params={
                    "location": postcode,
                    "within": f"{radius_km}km",
                    "company_status": "active",
                    "size": str(min(size, 500)),
                },
                auth=_auth(),
            )

            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                for item in items:
                    sic_codes = item.get("sic_codes") or []
                    if not _is_relevant_sic(sic_codes):
                        continue

                    addr = item.get("registered_office_address", {})
                    address_str = ", ".join(
                        filter(None, [
                            addr.get("address_line_1"),
                            addr.get("address_line_2"),
                            addr.get("locality"),
                            addr.get("postal_code"),
                        ])
                    )

                    company = {
                        "company_number": item.get("company_number"),
                        "name": item.get("company_name"),
                        "address": address_str,
                        "type": item.get("company_type"),
                        "status": item.get("company_status"),
                        "sic_codes": sic_codes,
                        "categories": _classify_sic(sic_codes),
                        "date_of_creation": item.get("date_of_creation"),
                    }
                    company["relevance_score"] = _relevance_score(company, sic_codes)
                    results.append(company)

                # Sort by relevance
                results.sort(key=lambda c: c["relevance_score"], reverse=True)
            elif resp.status_code == 401:
                log.error("Companies House API key invalid or expired")
            elif resp.status_code == 416:
                # Advanced search not available — fall back to basic search
                log.info("Advanced search not available, falling back to basic search")
                results = await _basic_search_fallback(postcode, radius_km, size)
            else:
                log.warning("Companies House search returned %s: %s", resp.status_code, resp.text[:200])

    except httpx.TimeoutException:
        log.warning("Companies House API timeout for postcode %s", postcode)
    except Exception as e:
        log.exception("Companies House search failed: %s", e)

    _cache_set(cache_key, results)
    return results


async def _basic_search_fallback(
    postcode: str, radius_km: float, size: int
) -> list[dict]:
    """Fallback: use basic /search/companies if advanced search is unavailable."""
    results = []
    # Search for companies with the postcode in their name/address
    # This is less precise but works without advanced search
    clean_pc = postcode.strip().replace(" ", "").upper()
    # Use outward code (first part) for broader search
    outward = postcode.strip().split()[0] if " " in postcode.strip() else clean_pc[:4]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for query in [outward, f"farm {outward}", f"land {outward}", f"energy {outward}"]:
                resp = await client.get(
                    f"{BASE_URL}/search/companies",
                    params={"q": query, "items_per_page": str(min(size, 100))},
                    auth=_auth(),
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                seen = {r["company_number"] for r in results}
                for item in data.get("items", []):
                    cn = item.get("company_number")
                    if cn in seen:
                        continue
                    seen.add(cn)

                    sic_codes = item.get("sic_codes") or []
                    addr = item.get("address", {})
                    address_str = ", ".join(
                        filter(None, [
                            addr.get("address_line_1"),
                            addr.get("address_line_2"),
                            addr.get("locality"),
                            addr.get("postal_code"),
                        ])
                    )

                    company = {
                        "company_number": cn,
                        "name": item.get("title"),
                        "address": address_str,
                        "type": item.get("company_type"),
                        "status": item.get("company_status"),
                        "sic_codes": sic_codes,
                        "categories": _classify_sic(sic_codes),
                        "date_of_creation": item.get("date_of_creation"),
                    }
                    company["relevance_score"] = _relevance_score(company, sic_codes)

                    if _is_relevant_sic(sic_codes) or company["relevance_score"] > 0:
                        results.append(company)

        results.sort(key=lambda c: c["relevance_score"], reverse=True)
    except Exception as e:
        log.warning("Basic search fallback failed: %s", e)

    return results


async def get_company_detail(company_number: str) -> dict:
    """
    Fetch full company details + officers from Companies House.

    Returns:
        {"company": {...}, "officers": [...], "filing_history_count": int}
    """
    if not API_KEY:
        return {"error": "COMPANIES_HOUSE_API_KEY not set", "company": None, "officers": []}

    cache_key = f"ch_detail:{company_number}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    result: dict[str, Any] = {"company": None, "officers": [], "filing_history_count": 0}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Company profile
            resp = await client.get(
                f"{BASE_URL}/company/{company_number}",
                auth=_auth(),
            )
            if resp.status_code == 200:
                profile = resp.json()
                addr = profile.get("registered_office_address", {})
                result["company"] = {
                    "company_number": profile.get("company_number"),
                    "name": profile.get("company_name"),
                    "type": profile.get("type"),
                    "status": profile.get("company_status"),
                    "date_of_creation": profile.get("date_of_creation"),
                    "sic_codes": profile.get("sic_codes", []),
                    "address": ", ".join(filter(None, [
                        addr.get("address_line_1"),
                        addr.get("address_line_2"),
                        addr.get("locality"),
                        addr.get("region"),
                        addr.get("postal_code"),
                    ])),
                    "accounts_next_due": profile.get("accounts", {}).get("next_due"),
                    "confirmation_next_due": profile.get("confirmation_statement", {}).get("next_due"),
                    "has_charges": profile.get("has_charges", False),
                    "has_insolvency_history": profile.get("has_insolvency_history", False),
                }
            elif resp.status_code == 404:
                result["error"] = f"Company {company_number} not found"
                return result

            # Officers
            resp = await client.get(
                f"{BASE_URL}/company/{company_number}/officers",
                auth=_auth(),
            )
            if resp.status_code == 200:
                officers_data = resp.json()
                for off in officers_data.get("items", []):
                    if off.get("resigned_on"):
                        continue  # Skip resigned officers
                    result["officers"].append({
                        "name": off.get("name"),
                        "role": off.get("officer_role"),
                        "appointed_on": off.get("appointed_on"),
                        "nationality": off.get("nationality"),
                        "occupation": off.get("occupation"),
                    })

            # Filing history count
            resp = await client.get(
                f"{BASE_URL}/company/{company_number}/filing-history",
                params={"items_per_page": "0"},
                auth=_auth(),
            )
            if resp.status_code == 200:
                result["filing_history_count"] = resp.json().get("total_count", 0)

    except httpx.TimeoutException:
        log.warning("Companies House detail timeout for %s", company_number)
        result["error"] = "API timeout"
    except Exception as e:
        log.exception("Companies House detail failed: %s", e)
        result["error"] = str(e)[:200]

    _cache_set(cache_key, result)
    return result


async def search_landowner_companies(
    lat: float,
    lon: float,
    radius_km: float = 5,
) -> list[dict]:
    """
    Search for land/property/agriculture/energy companies near a location.

    Converts lat/lon to postcode, searches Companies House, filters
    for relevant SIC codes, and returns enriched results with relevance scoring.

    Returns:
        list of {"company_number", "name", "address", "type", "status",
                 "sic_codes", "categories", "relevance_score", "date_of_creation"}

    Returns empty list with note if API key not set.
    """
    if not API_KEY:
        return [{
            "note": "COMPANIES_HOUSE_API_KEY not set — register free at https://developer.company-information.service.gov.uk/",
            "companies": [],
        }]

    # Convert lat/lon to postcode
    postcode = await _latlon_to_postcode(lat, lon)
    if not postcode:
        log.warning("Could not resolve postcode for %.4f, %.4f", lat, lon)
        return [{
            "note": f"Could not resolve UK postcode for coordinates ({lat:.4f}, {lon:.4f}). Location may be outside UK.",
            "companies": [],
        }]

    companies = await search_companies_near(postcode, radius_km=radius_km)

    return {
        "postcode": postcode,
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "total": len(companies),
        "companies": companies[:50],  # Cap at 50 for response size
        "note": f"Found {len(companies)} relevant companies near {postcode} within {radius_km}km"
        + (" (agriculture, real estate, energy, construction)" if companies else ""),
    }

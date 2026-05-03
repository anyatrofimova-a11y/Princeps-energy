"""
utils/capacity_market.py — UK Capacity Market register lookup.

The EMR Delivery Body publishes the live CM register via the NESO Open Data
Portal as two CKAN tables:

    Capacity Market Unit (CMU)
        resource_id = 25a5fa2e-873d-41c5-8aaf-fbc2b06d79e6
        Fields: CMU ID, Auction Name, Type, Auction, Delivery Year,
                Name of Applicant, Parent Company, Transmission/Distribution,
                CM Unit Type, Primary Fuel Type, CMU Technology,
                Pre-Qualification Decision, ...

    Components
        resource_id = 790f5fa0-f8eb-4d82-b98d-0d34d3e404e8
        Fields: CMU ID, Component ID, Type, Generating Technology Class,
                Permitted on-Site Generating Unit, Primary Fuel of Component,
                Connection / DSR Capacity, De-Rated Capacity,
                Pre-Refurbishing De-Rated Capacity,
                Post-Refurbishing De-Rated Capacity,
                Description of CMU Components,
                Location and Post Code, OS Grid Reference

Full-text search via CKAN's `q=` parameter is fast (no need to bulk-ingest
1.8 M components). For the asset-intel popup we:

    search_cmus(query)        — CMU rows matching a free-text query
    cmu_components(cmu_id)    — all components for one CMU
    lookup_for_asset(...)     — convenience: dedupe by CMU ID, return a
                                summary suitable for the popup
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, asdict
from typing import Any

import httpx

log = logging.getLogger("princeps.capacity_market")

_NESO_BASE = "https://api.neso.energy/api/3/action"
_USER_AGENT = "Princeps/1.0 (+https://princeps.energy) capacity-market"
_TIMEOUT = httpx.Timeout(30.0, connect=8.0)

# Resource ids — discovered via /package_show?id=capacity-market-register.
# These rotate with each weekly publication; the easiest way to keep them
# fresh is to re-resolve the package metadata once a day.
RESOURCE_CMU = "25a5fa2e-873d-41c5-8aaf-fbc2b06d79e6"
RESOURCE_COMPONENTS = "790f5fa0-f8eb-4d82-b98d-0d34d3e404e8"
RESOURCE_CMU_HISTORY = "cd034839-73e7-4c37-b4e5-6ebea25627d8"
RESOURCE_COMPONENTS_HISTORY = "015453e0-c73c-416a-901d-623f914c8e70"


@dataclass(frozen=True)
class CmuRow:
    cmu_id: str
    auction_name: str | None
    type: str | None              # "T-1" / "T-4" / "TR"
    delivery_year: str | None
    applicant: str | None
    parent_company: str | None
    cmu_technology: str | None
    primary_fuel: str | None
    transmission_or_distribution: str | None
    cmu_type: str | None
    cmu_category: str | None
    prequal_decision: str | None
    opt_out_status: str | None
    storage_facility: str | None
    raw: dict | None = None


@dataclass(frozen=True)
class CmuComponent:
    cmu_id: str
    component_id: str | None
    type: str | None
    technology_class: str | None
    primary_fuel: str | None
    connection_dsr_capacity_mw: float | None
    de_rated_capacity_mw: float | None
    location: str | None
    os_grid_ref: str | None
    description: str | None
    auction_name: str | None
    delivery_year: str | None


# ---------------------------------------------------------------------------
# Resource-id refresh (covers weekly republication)
# ---------------------------------------------------------------------------
async def refresh_resource_ids(*, client: httpx.AsyncClient | None = None) -> dict:
    """Re-resolve the four resource ids from the parent package metadata.
    Returns a dict updateable into the module-level constants if needed."""
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    try:
        r = await client.get(f"{_NESO_BASE}/package_show",
                              params={"id": "capacity-market-register"})
        r.raise_for_status()
        out: dict[str, str] = {}
        for res in (r.json().get("result", {}).get("resources") or []):
            name = (res.get("name") or "").strip().lower()
            if "history" in name and "cmu" in name:
                out["cmu_history"] = res["id"]
            elif "history" in name:
                out["components_history"] = res["id"]
            elif "cmu" in name:
                out["cmu"] = res["id"]
            elif "component" in name:
                out["components"] = res["id"]
        return out
    finally:
        if own:
            await client.aclose()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def _to_float(v: Any) -> float | None:
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row_to_cmu(rec: dict) -> CmuRow:
    return CmuRow(
        cmu_id=str(rec.get("CMU ID") or "").strip(),
        auction_name=rec.get("Auction Name"),
        type=rec.get("Type"),
        delivery_year=str(rec.get("Delivery Year") or "") or None,
        applicant=rec.get("Name of Applicant"),
        parent_company=rec.get("Parent Company") if rec.get("Parent Company") not in (None, "None") else None,
        cmu_technology=rec.get("CMU Technology"),
        primary_fuel=rec.get("Primary Fuel Type") if rec.get("Primary Fuel Type") not in (None, "None") else None,
        transmission_or_distribution=rec.get("Transmission / Distribution"),
        cmu_type=rec.get("CM Unit Type"),
        cmu_category=rec.get("CM Unit Category"),
        prequal_decision=rec.get("Pre-Qualification Decision"),
        opt_out_status=rec.get("Opt Out Status"),
        storage_facility=rec.get("Storage Facility"),
        raw=None,
    )


def _row_to_component(rec: dict) -> CmuComponent:
    return CmuComponent(
        cmu_id=str(rec.get("CMU ID") or "").strip(),
        component_id=rec.get("Component ID"),
        type=rec.get("Type"),
        technology_class=rec.get("Generating Technology Class"),
        primary_fuel=rec.get("Primary Fuel of Component"),
        connection_dsr_capacity_mw=_to_float(rec.get("Connection / DSR Capacity")),
        de_rated_capacity_mw=_to_float(rec.get("De-Rated Capacity")),
        location=rec.get("Location and Post Code") if rec.get("Location and Post Code") not in (None, "None") else None,
        os_grid_ref=rec.get("OS Grid Reference") if rec.get("OS Grid Reference") not in (None, "None") else None,
        description=rec.get("Description of CMU Components"),
        auction_name=rec.get("Auction Name"),
        delivery_year=str(rec.get("Delivery Year") or "") or None,
    )


async def search_cmus(
    query: str,
    *,
    limit: int = 100,
    client: httpx.AsyncClient | None = None,
) -> list[CmuRow]:
    """CKAN full-text search across the live CMU register. Returns up to
    `limit` matches, ordered by the CKAN scoring."""
    if not query or not query.strip():
        return []
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    try:
        r = await client.get(
            f"{_NESO_BASE}/datastore_search",
            params={"resource_id": RESOURCE_CMU, "q": query, "limit": limit},
        )
        if r.status_code != 200:
            return []
        return [_row_to_cmu(rec) for rec in (r.json().get("result", {}).get("records") or [])]
    finally:
        if own:
            await client.aclose()


async def cmu_components(
    cmu_id: str,
    *,
    limit: int = 200,
    client: httpx.AsyncClient | None = None,
) -> list[CmuComponent]:
    """All component entries (across all auctions) for one CMU."""
    if not cmu_id:
        return []
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    try:
        r = await client.get(
            f"{_NESO_BASE}/datastore_search",
            params={
                "resource_id": RESOURCE_COMPONENTS,
                "filters": f'{{"CMU ID":"{cmu_id}"}}',
                "limit": limit,
            },
        )
        if r.status_code != 200:
            return []
        return [_row_to_component(rec) for rec in (r.json().get("result", {}).get("records") or [])]
    finally:
        if own:
            await client.aclose()


# ---------------------------------------------------------------------------
# Convenience for asset-intel popup
# ---------------------------------------------------------------------------
def _dedupe_latest_per_cmu(rows: list[CmuRow]) -> list[CmuRow]:
    """Each CMU appears once per delivery_year (T-1 and T-4 are separate
    rows). Reduce to one row per CMU keeping the most recent delivery year."""
    by_id: dict[str, CmuRow] = {}
    for row in rows:
        prev = by_id.get(row.cmu_id)
        if prev is None or (row.delivery_year or "") > (prev.delivery_year or ""):
            by_id[row.cmu_id] = row
    return sorted(by_id.values(), key=lambda r: -(int(r.delivery_year or 0)))


async def lookup_for_asset(
    *,
    asset_name: str | None,
    operator: str | None = None,
    postcode: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict | None:
    """One-shot lookup for the asset-intel popup. Returns a structured
    summary covering up to ~5 most-recent CMUs and their components.

    Search strategy:
      1. If asset_name is provided, try it as the CKAN q-string first.
      2. If nothing comes back, try the operator (without limited liability /
         Limited / Ltd suffixes which can suppress matches).
      3. Components for each found CMU are fetched in parallel.
    """
    queries = [q for q in (asset_name, operator, postcode) if q]
    if not queries:
        return None
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    try:
        rows: list[CmuRow] = []
        used_query: str | None = None
        for q in queries:
            cleaned = q
            if " Limited" in cleaned:
                cleaned = cleaned.replace(" Limited", "")
            if " Ltd" in cleaned:
                cleaned = cleaned.replace(" Ltd", "")
            rows = await search_cmus(cleaned, limit=80, client=client)
            if rows:
                used_query = cleaned
                break
        if not rows:
            return None

        deduped = _dedupe_latest_per_cmu(rows)[:5]

        comps = await asyncio.gather(*[
            cmu_components(r.cmu_id, limit=20, client=client)
            for r in deduped
        ])

        out_cmus = []
        total_de_rated = 0.0
        latest_year: str | None = None
        for cmu, comps_for_cmu in zip(deduped, comps):
            de_rated = sum(
                (c.de_rated_capacity_mw or 0.0) for c in comps_for_cmu
            )
            connection = sum(
                (c.connection_dsr_capacity_mw or 0.0) for c in comps_for_cmu
            )
            total_de_rated += de_rated
            if cmu.delivery_year and (latest_year is None or cmu.delivery_year > latest_year):
                latest_year = cmu.delivery_year
            out_cmus.append({
                "cmu": asdict(cmu),
                "components": [asdict(c) for c in comps_for_cmu[:8]],
                "n_components": len(comps_for_cmu),
                "sum_de_rated_capacity_mw": round(de_rated, 2),
                "sum_connection_capacity_mw": round(connection, 2),
            })

        return {
            "query_used": used_query,
            "n_cmus": len(out_cmus),
            "latest_delivery_year": latest_year,
            "sum_de_rated_capacity_mw": round(total_de_rated, 2),
            "cmus": out_cmus,
            "source": "NESO Open Data Portal — Capacity Market Register",
        }
    finally:
        if own:
            await client.aclose()

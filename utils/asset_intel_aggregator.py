"""
utils/asset_intel_aggregator.py — Single-call enrichment for any energy
asset on the map.

Given a (lat, lon) and optional name/tech, this module fans out to every
data source we already pay a license / proxy / crawler bill for:

    * PlanIt spatial    — every planning application within Xkm, no
                          keyword filter (covers ~350 UK LPAs)
    * Wikidata          — biography for the nearest power-station entity
                          (operator, owner, OEM, capacity, commission year,
                           image, Wikipedia URL)
    * REPD nearby       — renewable projects ≥150 kW within Xkm with full
                          metadata (status, capacity, planning ref)
    * NESO TEC nearby   — transmission connection queue entries within Xkm
    * Grid substations  — closest UKPN/DNO substation with headroom
    * Companies House   — operator company profile if discoverable from
                          REPD applicant or Wikidata owner
    * Carbon intensity  — current GB carbon intensity for context

Returns a single ``AssetProfile`` dict that the frontend renders as a
multi-tab side panel.

Designed to be cheap on the first call, fast on subsequent calls (PlanIt
results cached for 12 h via planit_spatial.fetch_nearby_cached).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

import httpx

from utils.planit_spatial import (
    fetch_nearby_cached as planit_fetch_nearby_cached,
    classify as planit_classify,
)
from utils.wikidata_assets import (
    nearest_asset as wd_nearest,
    biography as wd_biography,
    biography_to_dict,
)
from utils.bmrs_bmu import asset_dispatch_summary as bmrs_dispatch
from utils.capacity_market import lookup_for_asset as cm_lookup
from utils.energy_news_rss import search_items as news_search, items_to_list
from utils.ea_pollution_inventory import asset_emissions_summary as ea_emissions

log = logging.getLogger("princeps.asset_intel")

_USER_AGENT = "Princeps/1.0 (+https://princeps.energy) asset-intel"
_TIMEOUT = httpx.Timeout(15.0, connect=6.0)


# ---------------------------------------------------------------------------
# Source: REPD nearby
# ---------------------------------------------------------------------------
async def _repd_nearby(pool, lat: float, lon: float, radius_km: float) -> list[dict]:
    """REPD renewables ≥150 kW within radius_km."""
    if pool is None:
        return []
    try:
        async with pool.acquire() as c:
            if not await c.fetchval("SELECT to_regclass('repd_projects')"):
                return []
            rows = await c.fetch(
                """
                WITH q AS (
                    SELECT ST_Transform(
                               ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700
                           ) AS pt
                )
                SELECT repd_id, site_name, technology, tech_category,
                       capacity_mw, status, developer, operator,
                       planning_authority, planning_ref, planning_url,
                       date_submitted, date_decided, date_operational,
                       battery_mwh, turbines,
                       ST_Distance(geometry, q.pt) / 1000.0 AS distance_km
                FROM repd_projects, q
                WHERE geometry IS NOT NULL
                  AND ST_DWithin(geometry, q.pt, $3 * 1000)
                ORDER BY geometry <-> q.pt
                LIMIT 60
                """,
                lon, lat, radius_km,
            )
            return [
                {
                    "repd_id": r["repd_id"],
                    "site_name": r["site_name"],
                    "technology": r["technology"],
                    "tech_category": r["tech_category"],
                    "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] is not None else None,
                    "battery_mwh": float(r["battery_mwh"]) if r["battery_mwh"] is not None else None,
                    "turbines": r["turbines"],
                    "status": r["status"],
                    "developer": r["developer"],
                    "operator": r["operator"],
                    "planning_authority": r["planning_authority"],
                    "planning_ref": r["planning_ref"],
                    "planning_url": r["planning_url"],
                    "date_submitted": str(r["date_submitted"]) if r["date_submitted"] else None,
                    "date_decided": str(r["date_decided"]) if r["date_decided"] else None,
                    "date_operational": str(r["date_operational"]) if r["date_operational"] else None,
                    "distance_km": round(float(r["distance_km"]), 3),
                }
                for r in rows
            ]
    except Exception as exc:
        log.warning("repd_nearby failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Source: NESO TEC register nearby
# ---------------------------------------------------------------------------
async def _tec_nearby(pool, lat: float, lon: float, radius_km: float) -> list[dict]:
    """NESO TEC register entries within radius_km."""
    if pool is None:
        return []
    try:
        async with pool.acquire() as c:
            if not await c.fetchval("SELECT to_regclass('eso_tec_register')"):
                return []
            rows = await c.fetch(
                """
                WITH q AS (
                    SELECT ST_Transform(
                               ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700
                           ) AS pt
                )
                SELECT tec_id, customer_name, parent_company, spv_name,
                       connection_site, fuel_type, tech_category,
                       tec_mw, dnc_mw, status, voltage_kv, zone,
                       effective_from, effective_to, connection_date,
                       queue_position,
                       ST_Distance(geometry, q.pt) / 1000.0 AS distance_km
                FROM eso_tec_register, q
                WHERE geometry IS NOT NULL
                  AND ST_DWithin(geometry, q.pt, $3 * 1000)
                ORDER BY geometry <-> q.pt
                LIMIT 40
                """,
                lon, lat, radius_km,
            )
            return [
                {
                    "tec_id": r["tec_id"],
                    "customer_name": r["customer_name"],
                    "parent_company": r["parent_company"],
                    "spv_name": r["spv_name"],
                    "connection_site": r["connection_site"],
                    "fuel_type": r["fuel_type"],
                    "tech_category": r["tech_category"],
                    "tec_mw": float(r["tec_mw"]) if r["tec_mw"] is not None else None,
                    "dnc_mw": float(r["dnc_mw"]) if r["dnc_mw"] is not None else None,
                    "status": r["status"],
                    "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] is not None else None,
                    "zone": r["zone"],
                    "effective_from": str(r["effective_from"]) if r["effective_from"] else None,
                    "effective_to": str(r["effective_to"]) if r["effective_to"] else None,
                    "connection_date": str(r["connection_date"]) if r["connection_date"] else None,
                    "queue_position": r["queue_position"],
                    "distance_km": round(float(r["distance_km"]), 3),
                }
                for r in rows
            ]
    except Exception as exc:
        log.warning("tec_nearby failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Source: closest grid substation
# ---------------------------------------------------------------------------
async def _nearest_substation(pool, lat: float, lon: float) -> dict | None:
    """Closest DNO/TO substation with headroom + RAG."""
    if pool is None:
        return None
    try:
        async with pool.acquire() as c:
            if not await c.fetchval("SELECT to_regclass('grid_substations')"):
                return None
            r = await c.fetchrow(
                """
                WITH q AS (
                    SELECT ST_Transform(
                               ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700
                           ) AS pt
                )
                SELECT name, dno, region, voltage_kv, site_type,
                       demand_mw, generation_mw,
                       demand_headroom_mw, gen_headroom_mw,
                       transformer_rating_mva, fault_level_ka,
                       rag_demand, rag_generation,
                       postcode, town, county,
                       ST_Distance(geom, q.pt) / 1000.0 AS distance_km
                FROM grid_substations, q
                WHERE geom IS NOT NULL
                ORDER BY geom <-> q.pt
                LIMIT 1
                """,
                lon, lat,
            )
            if not r:
                return None
            return {
                "name": r["name"],
                "dno": r["dno"],
                "region": r["region"],
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] is not None else None,
                "site_type": r["site_type"],
                "demand_mw": float(r["demand_mw"]) if r["demand_mw"] is not None else None,
                "generation_mw": float(r["generation_mw"]) if r["generation_mw"] is not None else None,
                "demand_headroom_mw": float(r["demand_headroom_mw"]) if r["demand_headroom_mw"] is not None else None,
                "gen_headroom_mw": float(r["gen_headroom_mw"]) if r["gen_headroom_mw"] is not None else None,
                "transformer_rating_mva": float(r["transformer_rating_mva"]) if r["transformer_rating_mva"] is not None else None,
                "fault_level_ka": float(r["fault_level_ka"]) if r["fault_level_ka"] is not None else None,
                "rag_demand": r["rag_demand"],
                "rag_generation": r["rag_generation"],
                "postcode": r["postcode"],
                "town": r["town"],
                "county": r["county"],
                "distance_km": round(float(r["distance_km"]), 3),
            }
    except Exception as exc:
        log.warning("nearest_substation failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Source: Companies House — best-effort profile from a free-text company name
# ---------------------------------------------------------------------------
_CH_BASE = "https://api.company-information.service.gov.uk"


async def _companies_house(name: str | None, *, api_key: str | None) -> dict | None:
    if not name or not api_key:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT},
            auth=(api_key, ""),
        ) as cli:
            r = await cli.get(f"{_CH_BASE}/search/companies",
                              params={"q": name, "items_per_page": 3})
            if r.status_code != 200:
                return None
            items = r.json().get("items") or []
            if not items:
                return None
            top = items[0]
            cn = top.get("company_number")
            profile = None
            if cn:
                pr = await cli.get(f"{_CH_BASE}/company/{cn}")
                if pr.status_code == 200:
                    profile = pr.json()
            base = {
                "company_number": cn,
                "title": top.get("title"),
                "address_snippet": top.get("address_snippet"),
                "company_status": top.get("company_status"),
                "date_of_creation": top.get("date_of_creation"),
                "company_type": top.get("company_type"),
                "match_score": top.get("matches", {}),
            }
            if profile:
                base.update({
                    "registered_office_address": profile.get("registered_office_address"),
                    "sic_codes": profile.get("sic_codes"),
                    "accounts_next_due": (profile.get("accounts") or {}).get("next_due"),
                    "last_full_members_list_date": profile.get("last_full_members_list_date"),
                })
            return base
    except Exception as exc:
        log.warning("companies_house failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Source: GB carbon intensity (cheap context)
# ---------------------------------------------------------------------------
async def _carbon_intensity_now() -> dict | None:
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT},
        ) as cli:
            r = await cli.get("https://api.carbonintensity.org.uk/intensity")
            if r.status_code != 200:
                return None
            d = (r.json().get("data") or [{}])[0]
            return {
                "from": d.get("from"), "to": d.get("to"),
                "intensity": (d.get("intensity") or {}),
            }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
async def aggregate(
    pool,
    *,
    lat: float,
    lon: float,
    radius_km: float = 5.0,
    name: str | None = None,
    tech: str | None = None,
    companies_house_api_key: str | None = None,
) -> dict:
    """Run all sources in parallel and merge.

    Parameters
    ----------
    pool : asyncpg.Pool | None
        Optional — DB sources are skipped if ``pool`` is None.
    lat, lon : float
        WGS84 of the asset.
    radius_km : float
        Spatial fan-out radius for PlanIt / REPD / TEC.
    name : str | None
        Optional hint used to short-circuit Wikidata label search and to
        seed the Companies House search.
    tech : str | None
        e.g. "ccgt" / "bess" / "solar" — surfaced in the response.
    companies_house_api_key : str | None
        If set, a Companies House profile is fetched for the candidate
        operator/owner from Wikidata; otherwise that block is omitted.
    """
    started = datetime.now(timezone.utc)

    async def _safe(coro, label):
        try:
            return await coro
        except Exception as exc:
            log.warning("aggregator branch %s failed: %s", label, exc)
            return None

    # Wikidata first so we have a candidate name if the caller didn't pass one
    wd_near = await _safe(wd_nearest(lat, lon, radius_km=2.0), "wd_nearest")
    wd_qid = (wd_near or {}).get("qid")
    wd_label = (wd_near or {}).get("label")

    bio_task = wd_biography(wd_qid or name) if (wd_qid or name) else None

    # Run remaining sources concurrently
    candidate_name = name or wd_label
    coros = [
        _safe(planit_fetch_nearby_cached(pool, lat, lon, radius_km, since_days=365 * 5,
                                         max_records=600), "planit"),
        _safe(_repd_nearby(pool, lat, lon, radius_km), "repd"),
        _safe(_tec_nearby(pool, lat, lon, radius_km), "tec"),
        _safe(_nearest_substation(pool, lat, lon), "substation"),
        _safe(_carbon_intensity_now(), "carbon"),
        _safe(bmrs_dispatch(asset_name=candidate_name, operator=None, days=14), "bmrs"),
        _safe(cm_lookup(asset_name=candidate_name, operator=None), "capacity_market"),
        _safe(news_search(asset_name=candidate_name, operator=None, limit=12), "news"),
        _safe(ea_emissions(name=candidate_name, lat=lat, lon=lon), "ea_pi"),
    ]
    if bio_task:
        coros.insert(0, _safe(bio_task, "wd_biography"))

    results = await asyncio.gather(*coros)
    bio = None
    if bio_task:
        (bio, planit_apps, repd_apps, tec_apps, substation, carbon,
         bmrs_summary, cm_summary, news_items, ea_summary) = results
    else:
        (planit_apps, repd_apps, tec_apps, substation, carbon,
         bmrs_summary, cm_summary, news_items, ea_summary) = results

    planit_apps = planit_apps or []
    repd_apps = repd_apps or []
    tec_apps = tec_apps or []

    # Companies House best-effort
    ch_profile = None
    if companies_house_api_key and bio:
        candidate = bio.owner or bio.operator
        if candidate:
            ch_profile = await _safe(
                _companies_house(candidate, api_key=companies_house_api_key),
                "companies_house",
            )

    elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return {
        "query": {
            "lat": lat, "lon": lon, "radius_km": radius_km,
            "name": name or wd_label, "tech": tech,
            "elapsed_ms": elapsed_ms,
            "fetched_at": started.isoformat(),
        },
        "biography": biography_to_dict(bio),
        "wikidata_nearest": wd_near,
        "planning": {
            "summary": planit_classify([
                _planit_dictify(p) for p in planit_apps
            ]) if planit_apps else None,
            "applications": [asdict(p) if not isinstance(p, dict) else p
                             for p in planit_apps][:200],
        },
        "repd_nearby": repd_apps,
        "tec_nearby": tec_apps,
        "nearest_substation": substation,
        "companies_house": ch_profile,
        "carbon_intensity": carbon,
        "bmrs_dispatch": bmrs_summary,
        "capacity_market": cm_summary,
        "ea_pollution_inventory": ea_summary,
        "news": items_to_list(news_items) if news_items else [],
        "sources": {
            "planit": "https://www.planit.org.uk/api",
            "wikidata": "https://query.wikidata.org/sparql",
            "repd": "DESNZ REPD Q4 2025 (local mirror)",
            "tec_register": "NESO TEC register (local mirror)",
            "grid_substations": "DNO open data (local mirror)",
            "carbon_intensity": "api.carbonintensity.org.uk",
            "bmrs_bmu": "data.elexon.co.uk/bmrs/api/v1 (PN + MELS streams)",
            "capacity_market": "NESO CKAN — capacity-market-register",
            "ea_pollution_inventory": "data.gov.uk — pollution-inventory (annual ZIP)",
            "news_rss": "Modern Power · Energy Voice · ReNews · The Energyst · Solar Power Portal · Current",
            "companies_house": "api.company-information.service.gov.uk"
                               if companies_house_api_key else "skipped (no API key)",
        },
    }


def _planit_dictify(p) -> Any:
    """planit_classify expects NearbyApplication objects; if we re-hydrated
    from cache as plain dicts, mimic the attribute access shape it needs."""
    from utils.planit_spatial import NearbyApplication
    if isinstance(p, NearbyApplication):
        return p
    if isinstance(p, dict):
        return NearbyApplication(
            uid=p.get("uid", ""),
            name=p.get("name") or "",
            description=p.get("description"),
            lat=p.get("lat"),
            lng=p.get("lng"),
            distance_km=p.get("distance_km"),
            authority_name=p.get("authority_name"),
            authority_id=p.get("authority_id"),
            area_name=p.get("area_name"),
            app_type=p.get("app_type"),
            app_state=p.get("app_state"),
            decision=p.get("decision"),
            start_date=p.get("start_date"),
            decided_date=p.get("decided_date"),
            consulted_date=p.get("consulted_date"),
            associated_url=p.get("associated_url"),
            planit_url=p.get("planit_url"),
            raw=None,
        )
    return None

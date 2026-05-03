"""
app/routers/asset_intel.py — Single endpoint for the multi-source asset
enrichment used by the map popup / asset detail page.

GET /api/asset-intel?lat=51.535&lon=-2.685&radius_km=5&name=Seabank&tech=ccgt

Returns the merged output of utils.asset_intel_aggregator.aggregate(...).
The UI replaces the 5-line popup ("Type / Capacity / Voltage / Operator /
Status") with tabbed content drawn from this payload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from utils.asset_intel_aggregator import aggregate as run_aggregate
from utils.asset_intel_aggregator import (
    _repd_nearby,
    _tec_nearby,
    _nearest_substation,
    _carbon_intensity_now,
)
from utils.wikidata_assets import nearest_asset as wd_nearest, biography as wd_biography
from utils.planit_spatial import fetch_nearby_cached as planit_fetch_nearby_cached
from utils.bmrs_bmu import asset_dispatch_summary as bmrs_dispatch
from utils.capacity_market import lookup_for_asset as cm_lookup
from utils.energy_news_rss import search_items as news_search
from utils.ea_pollution_inventory import asset_emissions_summary as ea_emissions

log = logging.getLogger("princeps.asset_intel")
router = APIRouter(tags=["asset-intel"], prefix="")


# ── Streaming endpoint — yields each source as it completes via SSE so the
# panel can render progressively (Build.inc / MeanderX / Kongsberg pattern)
# instead of waiting 10-20s for the slowest source. ────────────────────────
def _normalize(v):
    """Convert dataclasses to dicts recursively so json.dumps doesn't fall
    back to str(). Dataclass detection via __dataclass_fields__."""
    from dataclasses import is_dataclass, asdict
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if is_dataclass(v) and not isinstance(v, type):
        return asdict(v)
    if isinstance(v, dict):
        return {k: _normalize(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_normalize(x) for x in v]
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


async def _labeled(label: str, coro):
    try:
        result = _normalize(await coro)
        return label, {"data": result, "error": None}
    except Exception as exc:
        log.warning("asset-intel/stream %s failed: %s", label, exc)
        return label, {"data": None, "error": f"{type(exc).__name__}: {exc}"}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


@router.get("/api/asset-intel/stream")
async def stream_asset_intel(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=30),
    name: str | None = Query(None, max_length=200),
    tech: str | None = Query(None, max_length=40),
):
    """SSE — fans out 9 sources, yields one event per source as it resolves.

    Event shapes:
      data: {"event": "started", "sources": [...], "fetched_at": "..."}
      data: {"event": "source",  "label": "biography", "ok": true,  "data": {...}}
      data: {"event": "source",  "label": "planning",  "ok": false, "error": "..."}
      data: {"event": "done",    "elapsed_ms": 9123}
    """
    pool = getattr(request.app.state, "pool", None)
    ch_key = os.environ.get("CH_API_KEY") or os.environ.get("COMPANIES_HOUSE_API_KEY")
    started = datetime.now(timezone.utc)

    SOURCES = [
        "wd_nearest",
        "biography",
        "planning",
        "repd",
        "tec",
        "substation",
        "carbon",
        "bmrs",
        "capacity_market",
        "news",
        "ea_pollution_inventory",
    ]

    async def gen():
        yield _sse({
            "event": "started",
            "sources": SOURCES,
            "fetched_at": started.isoformat(),
            "query": {"lat": lat, "lon": lon, "radius_km": radius_km, "name": name, "tech": tech},
        })

        # Phase 1 — Wikidata nearest (cheap, gives us a candidate name).
        wd_label_task = _labeled("wd_nearest", wd_nearest(lat, lon, radius_km=2.0))
        wd_near_label, wd_near_payload = await wd_label_task
        yield _sse({"event": "source", "label": wd_near_label,
                    "ok": wd_near_payload["error"] is None,
                    "data": wd_near_payload["data"],
                    "error": wd_near_payload["error"]})

        wd_qid = ((wd_near_payload.get("data") or {}) or {}).get("qid")
        wd_label = ((wd_near_payload.get("data") or {}) or {}).get("label")
        candidate_name = name or wd_label

        # Phase 2 — fan out remaining sources concurrently.
        tasks = [
            _labeled("biography", wd_biography(wd_qid or name)) if (wd_qid or name) else None,
            _labeled("planning", planit_fetch_nearby_cached(pool, lat, lon, radius_km,
                                                            since_days=365 * 5, max_records=600)),
            _labeled("repd", _repd_nearby(pool, lat, lon, radius_km)),
            _labeled("tec", _tec_nearby(pool, lat, lon, radius_km)),
            _labeled("substation", _nearest_substation(pool, lat, lon)),
            _labeled("carbon", _carbon_intensity_now()),
            _labeled("bmrs", bmrs_dispatch(asset_name=candidate_name, operator=None, days=14)),
            _labeled("capacity_market", cm_lookup(asset_name=candidate_name, operator=None)),
            _labeled("news", news_search(asset_name=candidate_name, operator=None, limit=12)),
            _labeled("ea_pollution_inventory", ea_emissions(name=candidate_name, lat=lat, lon=lon)),
        ]
        tasks = [t for t in tasks if t is not None]

        for fut in asyncio.as_completed(tasks):
            if await request.is_disconnected():
                return
            label, payload = await fut
            yield _sse({"event": "source", "label": label,
                        "ok": payload["error"] is None,
                        "data": payload["data"],
                        "error": payload["error"]})

        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        yield _sse({"event": "done", "elapsed_ms": elapsed_ms})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


@router.get("/api/asset-intel")
async def get_asset_intel(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=30),
    name: str | None = Query(None, max_length=200),
    tech: str | None = Query(None, max_length=40),
):
    """Multi-source asset enrichment for map clicks.

    Sources fanned out in parallel:
      * PlanIt (every UK LPA application within radius_km — no keyword filter)
      * Wikidata SPARQL (biography of nearest power-station entity)
      * REPD (renewable projects within radius_km)
      * NESO TEC register (transmission queue entries)
      * Closest grid substation
      * Companies House (when CH_API_KEY env var is set)
      * GB carbon intensity (current half-hour)

    Cache: PlanIt results are pinned for 12 h in the planit_nearby_cache
    table, so the second click on the same asset is sub-second.
    """
    pool = getattr(request.app.state, "pool", None)
    ch_key = os.environ.get("CH_API_KEY") or os.environ.get("COMPANIES_HOUSE_API_KEY")
    try:
        return await run_aggregate(
            pool,
            lat=lat, lon=lon, radius_km=radius_km,
            name=name, tech=tech,
            companies_house_api_key=ch_key,
        )
    except Exception as exc:
        log.exception("asset-intel aggregate failed")
        raise HTTPException(500, f"asset-intel failed: {exc}")


@router.get("/api/asset-intel/healthz")
async def healthz():
    """Lightweight liveness probe — confirms the aggregator imports cleanly."""
    return {"ok": True, "router": "asset-intel"}

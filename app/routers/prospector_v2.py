"""Automated UK-Wide ML Site Prospector (v2) router.

Scans all 2,059 NGED substations and scores surrounding catchment areas
using grid headroom, solar resource, REPD development density, TEC queue
competition, and constraint risk. Returns ranked opportunities, detailed
substation assessments, and GeoJSON heatmaps.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, Query

from app.deps import get_pool

router = APIRouter(prefix="/api/v2/prospect", tags=["prospector-v2"])


@router.get("/scan")
async def scan_opportunities(
    region: str | None = Query(None, description="UK region filter (e.g. east_midlands)"),
    technology: str | None = Query(None, description="Technology filter (e.g. solar, wind)"),
    min_capacity_mw: float | None = Query(None, ge=0, description="Min capacity threshold (MW)"),
    top_n: int = Query(50, ge=1, le=500, description="Number of top results to return"),
    radius_km: float = Query(10.0, ge=1, le=50, description="Catchment radius (km)"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Scan all UK substations and return top opportunities ranked by composite score.

    Queries all NGED substations, scores each catchment area on grid headroom,
    solar resource, REPD development density, TEC queue competition, and
    constraint risk. Supports filtering by region, technology, and minimum
    capacity.
    """
    from utils.auto_prospector import scan_all
    return await scan_all(
        pool,
        region=region,
        technology=technology,
        min_capacity_mw=min_capacity_mw,
        top_n=top_n,
        radius_km=radius_km,
    )


@router.get("/substation/{sub_id}")
async def substation_assessment(
    sub_id: int,
    radius_km: float = Query(10.0, ge=1, le=50, description="Catchment radius (km)"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Detailed opportunity assessment for a single substation catchment.

    Returns full score breakdown, nearby REPD projects, TEC queue entries,
    technology mix, and total nearby generation capacity.
    """
    from utils.auto_prospector import substation_detail
    return await substation_detail(pool, sub_id, radius_km)


@router.get("/heatmap")
async def opportunity_heatmap(
    radius_km: float = Query(10.0, ge=1, le=50, description="Catchment radius (km)"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GeoJSON FeatureCollection of all substations colored by opportunity score.

    Each feature includes composite score, recommendation tier, and individual
    scoring dimensions. Suitable for direct rendering on a Mapbox/deck.gl layer.
    """
    from utils.auto_prospector import heatmap_geojson
    return await heatmap_geojson(pool, radius_km)


# ─── Godmode #2 — Reverse-search (natural language → ranked parcels) ───────

from pydantic import BaseModel as _BM
from fastapi import Request as _Req
import re as _re


class ReverseSearchRequest(_BM):
    query: str
    top_n: int = 40


@router.post("/reverse-search")
async def reverse_search(
    body: ReverseSearchRequest,
    request: _Req,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Parse a one-line brief into structured search params, then rank UK
    substation catchments.

    Examples of briefs that should work:
      "80 MW, by Q3 2027, ≤150ms to London"
      "20 MW BESS, East Midlands, 2h duration"
      "200 MW hyperscale DC, anywhere in the north, water <5Ml/yr"
    """
    q = body.query.strip()
    # --- Heuristic parser (fast path, no Claude roundtrip) -------------------
    params = {"top_n": body.top_n, "radius_km": 10.0}
    m_mw = _re.search(r"(\d+(?:\.\d+)?)\s*(?:MW|mw|megawatt)", q)
    if m_mw:
        params["min_capacity_mw"] = float(m_mw.group(1))
    ql = q.lower()
    tech = None
    if "bess" in ql or "battery" in ql or "storage" in ql:
        tech = "bess"
    elif "data centre" in ql or "data center" in ql or "hyperscale" in ql or " dc " in ql + " ":
        tech = "dc"
    elif "solar" in ql or "pv" in ql:
        tech = "solar"
    elif "wind" in ql:
        tech = "wind"
    if tech:
        params["technology"] = tech
    for token, region in [
        ("east midlands", "east_midlands"), ("west midlands", "west_midlands"),
        ("midlands", "east_midlands"),
        ("north west", "north_west"), ("north east", "north_east"),
        ("north", "north_west"), ("south west", "south_west"),
        ("south east", "south_east"), ("south", "south_east"),
        ("scotland", "scotland"), ("wales", "wales"),
        ("london", "london"),
    ]:
        if token in ql:
            params["region"] = region
            break

    # --- Optional Claude pass for anything the heuristic missed (latency tax
    # only applies if the caller explicitly asks for it via ?llm=1). --------
    try:
        use_llm = request.query_params.get("llm", "0") in ("1", "true", "yes")
    except Exception:
        use_llm = False

    if use_llm:
        try:
            claude = getattr(request.app.state, "claude", None)
            if claude is not None:
                from app.helpers import CLAUDE_MODEL
                sys_prompt = (
                    "Extract JSON {technology, min_capacity_mw, region} from the "
                    "user brief. region enum: east_midlands, west_midlands, "
                    "north_west, north_east, south_west, south_east, london, "
                    "scotland, wales. technology enum: bess, solar, wind, dc. "
                    "Return ONLY valid JSON."
                )
                r = await claude.messages.create(
                    model=CLAUDE_MODEL, max_tokens=200, system=sys_prompt,
                    messages=[{"role": "user", "content": q}],
                )
                text = "".join(b.text for b in r.content if b.type == "text")
                import json as _json
                m = _re.search(r"\{[^}]+\}", text)
                if m:
                    extra = _json.loads(m.group(0))
                    for k in ("technology", "min_capacity_mw", "region"):
                        if k in extra and extra[k]:
                            params[k] = extra[k]
        except Exception:
            pass

    # --- Run the ranker -------------------------------------------------------
    from utils.auto_prospector import scan_all
    result = await scan_all(pool, **params)
    return {
        "query": q,
        "parsed_params": params,
        "results": result,
    }

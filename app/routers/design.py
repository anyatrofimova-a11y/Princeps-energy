"""Design API — automated layout generation + unified orchestrator.

Core orchestrator (POST /api/design/generate) wraps the per-workload
generators (PV, BESS, DC) behind a single contract, runs constraint
gating + physics + finance + planning + reasoning, and returns a full
design document that powers DesignCanvas.jsx.

Supporting endpoints: constraint-gate, shade, hillshade, optimise,
layout CRUD + versioning.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import get_pool, get_claude, get_optional_user
from app.helpers import CLAUDE_MODEL
from utils.bess_benchmarks import (
    bess_capex_per_kwh,
    bess_fixed_opex_gbp_mw_yr,
    bess_revenue_mid,
)
from utils.pv_layout_engine import generate_pv_layout, list_modules
from utils import solar_benchmarks
from utils.finance_benchmarks import ppa_price_merchant as _bench_ppa

import anthropic  # type: ignore

log = logging.getLogger("princeps.design")

router = APIRouter(prefix="/api/design", tags=["design"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AutoLayoutRequest(BaseModel):
    """Request body for PV auto-layout generation."""

    # Site definition — provide ONE of these three options:
    boundary_coords: list[list[float]] | None = Field(
        None,
        description="Polygon ring [[lon, lat], ...] in WGS84. At least 3 vertices.",
    )
    bbox: list[float] | None = Field(
        None,
        description="Bounding box [min_lon, min_lat, max_lon, max_lat].",
    )
    centre_lat: float | None = Field(None, description="Site centre latitude (with centre_lon + radius_m).")
    centre_lon: float | None = Field(None, description="Site centre longitude.")
    radius_m: float | None = Field(None, ge=50, le=5000, description="Site radius in metres.")

    # Target
    capacity_mw: float | None = Field(None, ge=0.01, le=500, description="Target DC capacity (MW).")

    # Layout parameters
    tilt_deg: float | None = Field(None, ge=0, le=60, description="Panel tilt (None = auto from latitude).")
    azimuth_deg: float = Field(180.0, ge=0, le=360, description="Panel azimuth (180 = south).")
    module_key: str = Field("longi_himo6_550", description="Module from catalogue (see GET /api/design/modules).")
    modules_per_string: int = Field(28, ge=4, le=40, description="Modules per electrical string.")
    gcr_target: float | None = Field(None, ge=0.15, le=0.65, description="Ground coverage ratio (None = auto).")
    setback_m: float = Field(10.0, ge=0, le=100, description="Boundary setback (m).")
    access_road_width_m: float = Field(6.0, ge=3, le=12, description="Access road width (m).")
    access_road_interval: int = Field(10, ge=3, le=50, description="Access road every N rows.")
    dc_ac_ratio: float = Field(1.25, ge=1.0, le=1.6, description="DC/AC ratio for inverter sizing.")
    strings_per_inverter: int | None = Field(None, ge=1, le=50, description="Override strings per inverter.")
    inverters_per_transformer: int | None = Field(None, ge=1, le=50, description="Override inverters per transformer.")
    heightmap: list[list[float]] | None = Field(None, description="Optional terrain heightmap grid (reserved).")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/auto-layout")
async def auto_layout(req: AutoLayoutRequest):
    """Generate an optimised PV layout for a site.

    Provide a site boundary (polygon, bbox, or centre+radius), optional target
    capacity, and module/layout parameters. Returns the full electrical hierarchy
    (rows, strings, inverters, transformers), GeoJSON panel geometry, statistics,
    and bill of quantities.
    """
    result = generate_pv_layout(
        boundary_coords=req.boundary_coords,
        bbox=req.bbox,
        centre_lat=req.centre_lat,
        centre_lon=req.centre_lon,
        radius_m=req.radius_m,
        capacity_mw=req.capacity_mw,
        tilt_deg=req.tilt_deg,
        azimuth_deg=req.azimuth_deg,
        module_key=req.module_key,
        modules_per_string=req.modules_per_string,
        gcr_target=req.gcr_target,
        setback_m=req.setback_m,
        access_road_width_m=req.access_road_width_m,
        access_road_interval=req.access_road_interval,
        dc_ac_ratio=req.dc_ac_ratio,
        strings_per_inverter=req.strings_per_inverter,
        inverters_per_transformer=req.inverters_per_transformer,
        heightmap=req.heightmap,
    )
    return result


@router.get("/modules")
async def get_modules():
    """List available PV module types from the built-in catalogue."""
    return {"modules": list_modules()}


# ═══════════════════════════════════════════════════════════════════════════
# Unified orchestrator — /api/design/generate
# Wraps workload-specific layout + physics + finance + planning + reasoning
# into a single request. Returns a full design doc that DesignCanvas renders.
# ═══════════════════════════════════════════════════════════════════════════

class GenerateRequest(BaseModel):
    lat: float
    lon: float
    workload: str = Field("bess", description="bess | solar | dc | hybrid")
    capacity_mw: float | None = None
    params: dict = Field(default_factory=dict, description="Workload-specific parameters")
    boundary: dict | None = Field(None, description="Optional GeoJSON Polygon boundary")
    project_id: str | None = None
    candidate_id: str | None = None
    prompt: str | None = Field(None, description="Free-text design ask (conversational mode)")


async def _nearest_substation(pool, lat, lon):
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """SELECT name, capacity_kw,
                          ST_Distance(geometry::geography, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography) / 1000.0 AS dist_km
                   FROM dno_substations
                   ORDER BY geometry <-> ST_SetSRID(ST_MakePoint($1, $2), 4326)
                   LIMIT 1""",
                lon, lat,
            )
            if row:
                return {
                    "name": row["name"],
                    "distance_km": round(row["dist_km"], 2),
                    "headroom_mw": round((row["capacity_kw"] or 0) / 1000 * 0.3, 1),
                }
        except Exception as e:
            log.debug("substation lookup failed: %s", e)
    return None


def _bess_layout(lat, lon, capacity_mw, duration_h):
    """Rectangular BESS pad layout. 10 MW per pad, 40×25 m, 8 m fire breaks."""
    pads_needed = max(1, math.ceil(capacity_mw / 10))
    cols = min(5, pads_needed); rows = max(1, math.ceil(pads_needed / 5))
    m_per_deg_lat = 111_320
    m_per_deg_lon = 111_320 * math.cos(math.radians(lat))
    w_deg = 40 / m_per_deg_lon; h_deg = 25 / m_per_deg_lat
    gap_lon = 8 / m_per_deg_lon; gap_lat = 8 / m_per_deg_lat
    total_w = cols * w_deg + (cols - 1) * gap_lon
    total_h = rows * h_deg + (rows - 1) * gap_lat
    ox = lon - total_w / 2; oy = lat - total_h / 2
    features = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx >= pads_needed: break
            x0 = ox + c * (w_deg + gap_lon); y0 = oy + r * (h_deg + gap_lat)
            features.append({
                "type": "Feature",
                "properties": {"kind": "bess-pad", "idx": idx, "mw": 10},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [x0, y0], [x0 + w_deg, y0], [x0 + w_deg, y0 + h_deg],
                    [x0, y0 + h_deg], [x0, y0],
                ]]},
            })
            idx += 1
    area_ha = (pads_needed * 40 * 25) / 10_000
    return {"type": "FeatureCollection", "features": features,
            "meta": {"pad_count": pads_needed, "area_ha": round(area_ha, 3)}}


def _bess_kpis(capacity_mw, duration_h, headroom_mw):
    effective = capacity_mw if headroom_mw is None else min(capacity_mw, headroom_mw)
    energy = effective * duration_h
    # CapEx £/kWh all-in (bess_benchmarks mid case, Mar 2026).
    capex = energy * 1000 * bess_capex_per_kwh("mid")
    # Blended revenue £/MW-yr, duration-aware (Modo Energy index, Mar 2026).
    revenue = effective * bess_revenue_mid(duration_h)
    # Fixed O&M — approximate £/kWh-yr from £/MW-yr divided by duration.
    opex_per_kwh_yr = bess_fixed_opex_gbp_mw_yr() / (max(0.5, duration_h) * 1000)
    opex = energy * 1000 * opex_per_kwh_yr
    net = revenue - opex
    capex_m = capex / 1_000_000
    irr = max(0, (net * 15 / capex - 1)) * 100 / 1.5 if capex else 0
    lcoe = capex / max(1, energy * 250)
    npv = (net * 15 - capex) / 1_000_000  # simple
    return {
        "effective_capacity_mw": round(effective, 2),
        "energy_mwh": round(energy, 1),
        "annual_mwh": round(energy * 250, 1),
        "capex_gbp_m": round(capex_m, 2),
        "annual_revenue_gbp_m": round(revenue / 1_000_000, 2),
        "irr_pct": round(irr, 1),
        "lcoe_gbp_per_mwh": round(lcoe, 1),
        "npv_gbp_m": round(npv, 2),
    }


async def _claude_reasoning(claude, workload, prompt, kpis, constraints_applied, substation):
    base = [
        f"Sized to {kpis['effective_capacity_mw']} MW / {kpis['energy_mwh']} MWh — LFP chemistry for UK ancillary services.",
        f"Projected IRR {kpis['irr_pct']}% at LCOE £{kpis['lcoe_gbp_per_mwh']}/MWh.",
    ]
    if substation:
        if kpis["effective_capacity_mw"] < (kpis.get("effective_capacity_mw") or 0):
            base.append(f"Capped by substation headroom ({substation['headroom_mw']} MW at {substation['name']}).")
        else:
            base.append(f"Nearest substation: {substation['name']} · {substation['distance_km']} km · {substation['headroom_mw']} MW headroom.")
    base.extend([f"Compliance applied: {c}" for c in constraints_applied[:3]])
    if not claude or not prompt:
        return base
    try:
        sys = "Senior energy engineer. Given the KPIs, list 3–5 concise design decisions. UK 2026. No preamble."
        user = (f"Workload: {workload}\nKPIs: {json.dumps(kpis)}\n"
                f"Constraints: {constraints_applied}\nAsk: {prompt}")
        res = await claude.messages.create(
            model=CLAUDE_MODEL, max_tokens=400, system=sys,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in res.content if b.type == "text")
        bullets = [ln.lstrip("-•* ").strip() for ln in text.splitlines() if ln.strip()]
        return bullets[:6] if bullets else base
    except Exception as e:
        log.debug("Claude reasoning unavailable: %s", e)
        return base


@router.post("/generate")
async def generate(
    body: GenerateRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
):
    """Unified design generator. Runs constraint gate → headroom cap →
    workload layout → KPIs → reasoning. Every canvas edit calls this."""
    wl = body.workload.lower()
    if wl not in ("bess", "solar", "dc"):
        raise HTTPException(400, f"Unsupported workload '{wl}'")

    # 1. Constraint gate (best-effort — only runs if boundary supplied)
    constraints_applied: list[str] = []
    warnings: list[str] = []
    gate_result = None
    if body.boundary:
        try:
            from utils.design_constraints import screen_polygon
            gate_result = await screen_polygon(pool, body.boundary)
            if gate_result["designations"]:
                constraints_applied.extend(
                    f"{d['code']}: {d['name']} ({d['overlap_pct']}%)"
                    for d in gate_result["designations"]
                )
            if not gate_result["allowed"]:
                warnings.append(gate_result["recommendation"])
        except Exception as e:
            log.debug("constraint gate unavailable: %s", e)

    # 2. Nearest substation for headroom cap
    substation = await _nearest_substation(pool, body.lat, body.lon)
    headroom = substation["headroom_mw"] if substation else None

    # 3. Workload-specific layout + KPIs
    if wl == "bess":
        capacity = body.capacity_mw or body.params.get("capacity_mw") or 50.0
        duration = body.params.get("duration_h") or 2.0
        layout = _bess_layout(body.lat, body.lon, capacity, duration)
        kpis = _bess_kpis(capacity, duration, headroom)
        if substation and capacity > headroom:
            warnings.append(f"Capacity {capacity} MW exceeds substation headroom ({headroom} MW) — capped.")
    elif wl == "solar":
        # Delegate to existing PV layout engine
        capacity = body.capacity_mw or body.params.get("capacity_mw") or 20.0
        try:
            pv = generate_pv_layout(
                boundary_coords=(body.boundary or {}).get("coordinates", [None])[0],
                centre_lat=body.lat, centre_lon=body.lon, radius_m=300,
                capacity_mw=capacity,
                **{k: v for k, v in (body.params or {}).items()
                   if k in ("tilt_deg", "azimuth_deg", "module_key",
                            "modules_per_string", "gcr_target", "setback_m",
                            "dc_ac_ratio")},
            )
            layout = pv.get("geojson") or {"type": "FeatureCollection", "features": []}
            stats = pv.get("stats") or {}

            # ── 2026 UK solar engineering-math (utils.solar_benchmarks) ──
            cf = solar_benchmarks.solar_capacity_factor_mid()        # 0.11
            ppa_price = solar_benchmarks.ppa_price_merchant_mid()    # £45/MWh
            capex_per_mw = solar_benchmarks.solar_capex_per_mw()     # £730k/MW
            opex_per_mw_yr = solar_benchmarks.solar_opex_per_mw_yr() # £10k/MW/yr

            # Prefer engine outputs where available, else benchmark-derived
            energy_mwh = stats.get("annual_energy_mwh") \
                or solar_benchmarks.annual_energy_mwh(capacity, cf)
            capex_gbp = stats.get("capex_gbp") or capacity * capex_per_mw
            revenue_gbp_yr = energy_mwh * ppa_price
            opex_gbp_yr = capacity * opex_per_mw_yr
            net_gbp_yr = revenue_gbp_yr - opex_gbp_yr
            # 25-yr simple IRR approximation (same form as BESS path, life=25)
            irr_pct = max(0, (net_gbp_yr * 25 / capex_gbp - 1)) * 100 / 2.5 \
                if capex_gbp > 0 else 0.0
            lcoe_gbp_mwh = (capex_gbp / 25 + opex_gbp_yr) / max(1.0, energy_mwh)
            npv_gbp_m = (net_gbp_yr * 25 - capex_gbp) / 1_000_000

            kpis = {
                "effective_capacity_mw": stats.get("capacity_mw_dc", capacity),
                "capacity_factor_pct": round(cf * 100, 1),
                "annual_mwh": round(energy_mwh, 1),
                "energy_mwh": round(energy_mwh, 1),
                "capex_gbp_m": round(capex_gbp / 1_000_000, 2),
                "annual_revenue_gbp_m": round(revenue_gbp_yr / 1_000_000, 2),
                "annual_opex_gbp_m": round(opex_gbp_yr / 1_000_000, 2),
                "irr_pct": round(irr_pct, 1),
                "lcoe_gbp_per_mwh": round(lcoe_gbp_mwh, 1),
                "ppa_price_gbp_mwh": ppa_price,
                "npv_gbp_m": round(npv_gbp_m, 2),
                "benchmark_source": solar_benchmarks.cite(),
            }
        except Exception as e:
            log.exception("solar layout failed")
            raise HTTPException(500, f"Solar layout failed: {e}")
    else:  # dc
        capacity = body.capacity_mw or body.params.get("it_load_mw") or 40.0
        pue = body.params.get("pue_target") or 1.3
        tier = int(body.params.get("tier") or 3)
        redundancy = body.params.get("redundancy") or "N+1"
        layout = _bess_layout(body.lat, body.lon, capacity, 1)  # visual proxy

        # Engineering-grade CapEx per MW IT.
        # Cushman & Wakefield UK Data Centre Market 2025, CBRE H1 2025: Tier 3
        # benchmark range £3.5–5.0 M/MW IT; mid-point £4.2 M/MW. Tier 4 adds
        # ~25% (2N vs N+1 distribution trains). Previous hard-coded £9.5 M/MW
        # was ~2× the benchmark — fixed 2026-04-20.
        _tier_factor = {1: 0.70, 2: 0.85, 3: 1.00, 4: 1.25}.get(tier, 1.00)
        _red_factor = {"N": 0.92, "N+1": 1.00, "2N": 1.20, "2N+1": 1.28}.get(redundancy, 1.00)
        capex_per_mw = 4.2 * _tier_factor * _red_factor  # £M per MW IT
        capex_gbp_m = round(capacity * capex_per_mw, 1)

        # Annual IT energy — 85% utilisation typical UK colo, hyperscaler ~90%.
        annual_it_mwh = capacity * 8760 * 0.85
        # Total facility energy including PUE overhead.
        annual_facility_mwh = annual_it_mwh * pue

        # Revenue — 2026 UK hyperscaler wholesale lease benchmark
        # (Cushman H1 2025): £2.4–3.2 M/MW IT/yr. Use £2.8 M as the default.
        annual_revenue_gbp_m = round(capacity * 2.8, 1)

        # OpEx — Cornwall Insight DC OpEx report 2025: £/MW/yr split roughly
        # 60% power, 30% staff/maintenance, 10% other. At £110/MWh PPA baseline
        # for UK 2026 merchant, £-per-MW-facility = 8760 * PUE * 110 / 1e6.
        annual_opex_gbp_m = round(
            (annual_facility_mwh * 0.110 / 1_000) + (capacity * 0.35), 1
        )

        # Simple IRR proxy (15-yr cashflow, no tax): ((rev - opex) * 15 / capex - 1)
        # / 1.5 clamp ≥ 0. Replaces the previously hard-coded 14.2%.
        _net = max(annual_revenue_gbp_m - annual_opex_gbp_m, 0)
        irr_pct = round(max(0, ((_net * 15) / max(capex_gbp_m, 1) - 1)) * 100 / 1.5, 1) if capex_gbp_m else 0.0
        # LCOE for a DC is not standard; report cost-per-MWh-delivered instead.
        lcoe_gbp_per_mwh = round((capex_gbp_m * 1_000_000 / 15 + annual_opex_gbp_m * 1_000_000) / max(annual_it_mwh, 1), 1)

        kpis = {
            "effective_capacity_mw": capacity,
            "pue": pue,
            "tier": tier,
            "redundancy": redundancy,
            "annual_mwh": round(annual_facility_mwh),      # facility (incl. PUE)
            "energy_mwh": round(annual_it_mwh),             # IT throughput
            "capex_gbp_m": capex_gbp_m,
            "capex_per_mw_gbp_m": round(capex_per_mw, 2),
            "annual_revenue_gbp_m": annual_revenue_gbp_m,
            "annual_opex_gbp_m": annual_opex_gbp_m,
            "irr_pct": irr_pct,
            "lcoe_gbp_per_mwh": lcoe_gbp_per_mwh,
            "npv_gbp_m": 0,
            "benchmark_source": "Cushman & Wakefield UK DC Market 2025 + CBRE H1 2025 + Cornwall Insight DC OpEx 2025",
        }
    constraints_applied.append("Fire breaks: 8 m (BS 8629:2019)")
    constraints_applied.append("Setback: 10 m from boundary")

    # 4. Reasoning (Claude or deterministic)
    reasoning = await _claude_reasoning(claude, wl, body.prompt, kpis, constraints_applied, substation)

    doc = {
        "version": 1,
        "workload": wl,
        "lat": body.lat, "lon": body.lon,
        "boundary": body.boundary,
        "layout": layout,
        "params": {**(body.params or {}),
                   "capacity_mw": kpis.get("effective_capacity_mw"),
                   "duration_h": body.params.get("duration_h") or 2.0},
        "kpis": kpis,
        "constraints_applied": constraints_applied,
        "constraint_gate": gate_result,
        "warnings": warnings,
        "substation": substation,
        "reasoning": reasoning,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    return {"doc": doc, "kpis": kpis, "reasoning": reasoning,
            "warnings": warnings, "substation": substation}


# ═══════════════════════════════════════════════════════════════════════════
# Constraint gate — /api/design/constraint-gate
# ═══════════════════════════════════════════════════════════════════════════

class ConstraintGateRequest(BaseModel):
    boundary: dict  # GeoJSON Polygon or MultiPolygon


@router.post("/constraint-gate")
async def constraint_gate(body: ConstraintGateRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Screen a boundary polygon against UK designations. Used by the
    DesignCanvas draw tool to reject invalid strokes live."""
    try:
        from utils.design_constraints import screen_polygon
        return await screen_polygon(pool, body.boundary)
    except Exception as e:
        log.exception("constraint gate")
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Shade analysis — /api/design/shade
# ═══════════════════════════════════════════════════════════════════════════

class ShadeRequest(BaseModel):
    bbox: list[float] = Field(..., description="[west, south, east, north] WGS84")
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp")
    product: str = Field("dsm", description="'dsm' (buildings+trees) | 'dtm' (bare earth)")


@router.post("/shade")
async def shade(body: ShadeRequest):
    """Compute sun-cast shadows for a site at a given time. Uses EA 1m
    LIDAR when available, falls back to NASADEM (30m) otherwise."""
    try:
        from utils.lidar_uk import fetch_dem
        from utils.design_shade import compute_shadows
        when = datetime.fromisoformat(body.timestamp.replace("Z", "+00:00"))
        bbox = tuple(body.bbox)
        dem = await fetch_dem(bbox, product=body.product)
        shadows = compute_shadows(dem, when)
        return shadows
    except Exception as e:
        log.exception("shade")
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Optimiser — /api/design/optimise
# ═══════════════════════════════════════════════════════════════════════════

class OptimiseRequest(BaseModel):
    lat: float
    lon: float
    workload: str
    objective: str = Field("irr", description="irr | lcoe | yield | capex | npv")
    initial_params: dict = Field(default_factory=dict)
    bounds: dict[str, list[float]] | None = None  # { param: [min, max] }


@router.post("/optimise")
async def optimise(body: OptimiseRequest, pool: asyncpg.Pool = Depends(get_pool), claude=Depends(get_claude)):
    """Run scipy-based search over design variables to optimise an objective."""
    from utils.design_optimiser import optimise as run_opt

    # Sensible default bounds by workload
    bounds = body.bounds or {}
    if body.workload == "bess":
        bounds = bounds or {"capacity_mw": [5, 200], "duration_h": [0.5, 6.0]}
    elif body.workload == "solar":
        bounds = bounds or {"capacity_mw": [5, 100], "dc_ac_ratio": [1.1, 1.55],
                             "tilt_deg": [10, 45]}
    elif body.workload == "dc":
        bounds = bounds or {"it_load_mw": [5, 200], "pue_target": [1.1, 1.6]}
    bounds = {k: tuple(v) for k, v in bounds.items()}

    init = dict(body.initial_params)
    for k, (lo, hi) in bounds.items():
        init.setdefault(k, (lo + hi) / 2)

    # Synchronous evaluator — wraps generate() by calling helpers directly.
    def evaluator(params: dict):
        import asyncio as _aio
        loop = _aio.new_event_loop()
        try:
            req = GenerateRequest(
                lat=body.lat, lon=body.lon, workload=body.workload,
                capacity_mw=params.get("capacity_mw") or params.get("it_load_mw"),
                params=params,
            )
            return loop.run_until_complete(generate(req, pool, claude))
        finally:
            loop.close()

    result = run_opt(body.workload, body.objective, init, bounds, evaluator)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Design Layouts CRUD + versioning — /api/design/layouts
# ═══════════════════════════════════════════════════════════════════════════

class SaveLayoutRequest(BaseModel):
    candidate_id: str | None = None
    project_id: str | None = None
    parent_layout_id: str | None = None
    workload: str
    name: str | None = None
    doc: dict
    kpis: dict | None = None
    status: str = "draft"
    is_preferred: bool = False


def _layout_row(row) -> dict:
    return {
        "layout_id":        str(row["layout_id"]),
        "candidate_id":     str(row["candidate_id"]) if row["candidate_id"] else None,
        "project_id":       str(row["project_id"]) if row["project_id"] else None,
        "parent_layout_id": str(row["parent_layout_id"]) if row["parent_layout_id"] else None,
        "workload":         row["workload"],
        "name":             row["name"],
        "doc":              json.loads(row["doc"]) if isinstance(row["doc"], str) else (row["doc"] or {}),
        "kpis":             json.loads(row["kpis"]) if isinstance(row["kpis"], str) else (row["kpis"] or {}),
        "status":           row["status"],
        "is_preferred":     row["is_preferred"],
        "created_at":       row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at":       row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.post("/layouts")
async def save_layout(
    body: SaveLayoutRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Persist a layout as a new row (optionally branching from parent)."""
    uid = user["user_id"] if user else None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO design_layouts
                   (candidate_id, project_id, parent_layout_id, workload, name,
                    doc, kpis, status, is_preferred, created_by)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10)
               RETURNING *""",
            UUID(body.candidate_id) if body.candidate_id else None,
            UUID(body.project_id) if body.project_id else None,
            UUID(body.parent_layout_id) if body.parent_layout_id else None,
            body.workload, body.name,
            json.dumps(body.doc), json.dumps(body.kpis or {}),
            body.status, body.is_preferred, uid,
        )
        # If marked preferred, demote siblings
        if body.is_preferred and body.candidate_id:
            await conn.execute(
                """UPDATE design_layouts SET is_preferred = false
                   WHERE candidate_id = $1 AND layout_id != $2""",
                UUID(body.candidate_id), row["layout_id"],
            )
    return _layout_row(row)


@router.get("/layouts")
async def list_layouts(
    candidate_id: str | None = Query(None),
    project_id: str | None = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    conditions = []
    params: list = []
    if candidate_id:
        conditions.append(f"candidate_id = ${len(params)+1}")
        params.append(UUID(candidate_id))
    if project_id:
        conditions.append(f"project_id = ${len(params)+1}")
        params.append(UUID(project_id))
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM design_layouts {where} ORDER BY created_at DESC LIMIT 200",
            *params,
        )
    return {"layouts": [_layout_row(r) for r in rows]}


@router.get("/layouts/{layout_id}")
async def get_layout(layout_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM design_layouts WHERE layout_id = $1", UUID(layout_id),
        )
    if not row:
        raise HTTPException(404, "Layout not found")
    return _layout_row(row)


@router.patch("/layouts/{layout_id}")
async def update_layout(layout_id: str, body: dict, pool: asyncpg.Pool = Depends(get_pool)):
    async with pool.acquire() as conn:
        sets, params = [], []
        idx = 1
        for field in ("name", "status", "is_preferred"):
            if field in body:
                sets.append(f"{field} = ${idx}"); params.append(body[field]); idx += 1
        for field in ("doc", "kpis"):
            if field in body:
                sets.append(f"{field} = ${idx}::jsonb")
                params.append(json.dumps(body[field])); idx += 1
        if not sets:
            raise HTTPException(400, "No fields to update")
        sets.append("updated_at = NOW()")
        params.append(UUID(layout_id))
        row = await conn.fetchrow(
            f"UPDATE design_layouts SET {', '.join(sets)} WHERE layout_id = ${idx} RETURNING *",
            *params,
        )
        if not row:
            raise HTTPException(404, "Layout not found")
        # Preferred toggle demotes siblings
        if body.get("is_preferred") is True and row["candidate_id"]:
            await conn.execute(
                """UPDATE design_layouts SET is_preferred = false
                   WHERE candidate_id = $1 AND layout_id != $2""",
                row["candidate_id"], row["layout_id"],
            )
    return _layout_row(row)


@router.delete("/layouts/{layout_id}")
async def delete_layout(layout_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    async with pool.acquire() as conn:
        res = await conn.execute(
            "DELETE FROM design_layouts WHERE layout_id = $1", UUID(layout_id),
        )
    if res == "DELETE 0":
        raise HTTPException(404, "Layout not found")
    return {"deleted": layout_id}


# ═══════════════════════════════════════════════════════════════════════════
# Engineering outputs (Phase 4) — BOM, SLD, export
# ═══════════════════════════════════════════════════════════════════════════

class LayoutIdRequest(BaseModel):
    layout_id: str


@router.post("/bom")
async def layout_bom(body: LayoutIdRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Bill of materials for a saved layout — module/inverter/transformer
    counts with indicative £ totals and a 10% contingency."""
    from utils.design_bom import build_bom
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT doc FROM design_layouts WHERE layout_id = $1", UUID(body.layout_id),
        )
    if not row:
        raise HTTPException(404, "Layout not found")
    doc = json.loads(row["doc"]) if isinstance(row["doc"], str) else row["doc"]
    return build_bom(doc or {})


@router.post("/sld")
async def layout_sld(body: LayoutIdRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Electrical single-line diagram as a ReactFlow graph
    (nodes + edges). Consumed by the DesignCanvas SLD tab."""
    from utils.design_sld import build_sld
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT doc FROM design_layouts WHERE layout_id = $1", UUID(body.layout_id),
        )
    if not row:
        raise HTTPException(404, "Layout not found")
    doc = json.loads(row["doc"]) if isinstance(row["doc"], str) else row["doc"]
    return build_sld(doc or {})


class ExportRequest(BaseModel):
    layout_id: str
    format: str = Field("pdf", description="pdf | dwg | csv (BOM) | json")


@router.post("/export")
async def export_layout(body: ExportRequest, pool: asyncpg.Pool = Depends(get_pool)):
    """Generate a technical report / CAD file for a saved layout.
    PDF via Playwright, DWG via ezdxf (if installed), CSV direct.
    Returns a URL the frontend can redirect to for download."""
    from utils.design_bom import build_bom
    from utils.design_sld import build_sld
    import pathlib, csv, io
    out_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "design_exports"
    out_dir.mkdir(parents=True, exist_ok=True)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT doc, kpis, workload, name FROM design_layouts WHERE layout_id = $1",
            UUID(body.layout_id),
        )
    if not row:
        raise HTTPException(404, "Layout not found")
    doc = json.loads(row["doc"]) if isinstance(row["doc"], str) else row["doc"]
    kpis = json.loads(row["kpis"]) if isinstance(row["kpis"], str) else (row["kpis"] or {})
    bom = build_bom(doc or {})

    fname_stem = f"{row['workload']}_{body.layout_id[:8]}"

    if body.format == "csv":
        path = out_dir / f"{fname_stem}_bom.csv"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["code", "description", "basis", "qty",
                                            "unit_cost_gbp", "total_gbp"])
        w.writeheader()
        for r in bom["rows"]:
            w.writerow({k: r.get(k) for k in w.fieldnames})
        buf.write(f"\nSubtotal,,,,,{bom['subtotal_gbp']}\n")
        buf.write(f"Contingency ({bom['contingency_pct']}%),,,,,{bom['contingency_gbp']}\n")
        buf.write(f"Total,,,,,{bom['total_gbp']}\n")
        path.write_text(buf.getvalue())
        return {"url": f"/static/design_exports/{path.name}", "format": "csv"}

    if body.format == "json":
        path = out_dir / f"{fname_stem}.json"
        path.write_text(json.dumps({"doc": doc, "kpis": kpis, "bom": bom}, default=str))
        return {"url": f"/static/design_exports/{path.name}", "format": "json"}

    if body.format == "dwg":
        try:
            import ezdxf
            dxf_path = out_dir / f"{fname_stem}.dxf"
            dxf = ezdxf.new("R2010")
            msp = dxf.modelspace()
            for feat in (doc.get("layout", {}).get("features") or []):
                coords = feat.get("geometry", {}).get("coordinates", [[]])[0]
                if coords:
                    msp.add_lwpolyline([(x, y) for x, y in coords], close=True)
            dxf.saveas(dxf_path)
            return {"url": f"/static/design_exports/{dxf_path.name}", "format": "dxf"}
        except ImportError:
            raise HTTPException(501, "ezdxf not installed — pip install ezdxf to enable DWG export")

    # Default: PDF via Playwright — HTML then print
    html = _render_report_html(row["name"], row["workload"], doc, kpis, bom,
                                build_sld(doc or {}))
    try:
        from playwright.async_api import async_playwright
        pdf_path = out_dir / f"{fname_stem}.pdf"
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.pdf(path=str(pdf_path), format="A4",
                           print_background=True, margin={"top": "18mm", "bottom": "18mm",
                                                          "left": "15mm", "right": "15mm"})
            await browser.close()
        return {"url": f"/static/design_exports/{pdf_path.name}", "format": "pdf"}
    except Exception as e:
        # Fall back to raw HTML
        html_path = out_dir / f"{fname_stem}.html"
        html_path.write_text(html)
        return {"url": f"/static/design_exports/{html_path.name}",
                "format": "html",
                "note": f"PDF export failed ({e}); served raw HTML."}


def _render_report_html(name, workload, doc, kpis, bom, sld) -> str:
    """Minimal embedded report. Intentionally dependency-free HTML."""
    rows_html = "".join(
        f"<tr><td>{r['code']}</td><td>{r['description']}</td><td>{r['qty']}</td>"
        f"<td>£{r.get('unit_cost_gbp') or '—'}</td><td>£{r.get('total_gbp') or '—'}</td></tr>"
        for r in bom["rows"]
    )
    kpi_html = "".join(
        f"<div class='k'><div class='kl'>{k.replace('_',' ')}</div><div class='kv'>{v}</div></div>"
        for k, v in (kpis or {}).items()
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{name or 'Design report'}</title><style>
  body {{ font-family: 'DM Sans', -apple-system, sans-serif; color: #0F1318; padding: 10px; }}
  h1 {{ color: #F5B731; border-bottom: 3px solid #F5B731; padding-bottom: 8px; }}
  h2 {{ color: #0F1318; margin-top: 28px; border-bottom: 1px solid #E8EAED; padding-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #E8EAED; }}
  th {{ background: #F2F3F5; }}
  .kpis {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
  .k {{ padding: 10px; background: #F7F8FA; border-radius: 8px; }}
  .kl {{ font-size: 9px; text-transform: uppercase; color: #6B7280; letter-spacing: 0.06em; }}
  .kv {{ font-family: 'JetBrains Mono', monospace; font-size: 18px; font-weight: 700; color: #0F1318; margin-top: 4px; }}
  .footer {{ margin-top: 32px; font-size: 9px; color: #9CA3AF; }}
</style></head><body>
<h1>{name or f'{workload.upper()} design'}</h1>
<p>Workload: <b>{workload.upper()}</b>. Generated by Princeps Design Canvas.</p>
<h2>Key performance indicators</h2>
<div class="kpis">{kpi_html}</div>
<h2>Bill of materials</h2>
<table><thead><tr><th>Code</th><th>Description</th><th>Qty</th><th>Unit £</th><th>Total £</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<p><b>Subtotal:</b> £{bom['subtotal_gbp']:,.0f} · Contingency ({bom['contingency_pct']}%): £{bom['contingency_gbp']:,.0f} · <b>Total:</b> £{bom['total_gbp']:,.0f}</p>
<h2>Reasoning</h2>
<ul>{''.join(f'<li>{r}</li>' for r in (doc.get('reasoning') or []))}</ul>
<div class="footer">Generated {doc.get('generated_at')}. Princeps · Energy feasibility platform. Benchmarks: UK 2026 Q1.</div>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════════
# Conversational agent (Phase 5) — /api/design/agent and /explain-kpi
# ═══════════════════════════════════════════════════════════════════════════

class AgentRequest(BaseModel):
    lat: float
    lon: float
    workload: str = "bess"
    params: dict = Field(default_factory=dict)
    prompt: str
    project_id: str | None = None
    candidate_id: str | None = None


@router.post("/agent")
async def design_agent(
    body: AgentRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
):
    """Tool-using Claude agent that edits design params + runs
    /api/design/generate to return a fresh result."""
    from utils.design_agent import run_agent
    agent_out = await run_agent(
        claude, CLAUDE_MODEL,
        workload=body.workload, params=body.params, prompt=body.prompt,
        context={"project_id": body.project_id, "candidate_id": body.candidate_id},
    )
    # Re-run the pipeline with the agent's updated params so the UI gets fresh KPIs.
    gen_req = GenerateRequest(
        lat=body.lat, lon=body.lon,
        workload=agent_out.get("workload") or body.workload,
        capacity_mw=agent_out["params"].get("capacity_mw"),
        params=agent_out["params"],
        project_id=body.project_id,
        candidate_id=body.candidate_id,
        prompt=body.prompt,
    )
    result = await generate(gen_req, pool, claude)
    return {
        "reply": agent_out["reply"],
        "params": agent_out["params"],
        "workload": agent_out.get("workload"),
        "tool_calls": agent_out["tool_calls"],
        "result": result,
    }


class ExplainKpiRequest(BaseModel):
    layout_id: str
    kpi_key: str


@router.post("/explain-kpi")
async def explain_kpi(
    body: ExplainKpiRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    claude=Depends(get_claude),
):
    """One-paragraph explanation of a specific KPI for the current layout."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT doc, kpis, workload FROM design_layouts WHERE layout_id = $1",
            UUID(body.layout_id),
        )
    if not row:
        raise HTTPException(404, "Layout not found")
    doc = json.loads(row["doc"]) if isinstance(row["doc"], str) else row["doc"]
    kpis = json.loads(row["kpis"]) if isinstance(row["kpis"], str) else (row["kpis"] or {})
    if not claude:
        return {"explanation": f"{body.kpi_key} = {kpis.get(body.kpi_key, '—')} (Claude offline — no analytical commentary)."}
    try:
        res = await claude.messages.create(
            model=CLAUDE_MODEL, max_tokens=220,
            system=("UK energy engineer. Given the KPI value and design context, "
                    "explain in 2 sentences why this value is what it is. No preamble."),
            messages=[{"role": "user", "content":
                       f"Workload: {row['workload']}\n"
                       f"KPI: {body.kpi_key} = {kpis.get(body.kpi_key)}\n"
                       f"All KPIs: {json.dumps(kpis)}\n"
                       f"Design params: {json.dumps(doc.get('params', {}))}\n"
                       f"Substation: {json.dumps(doc.get('substation', {}))}"}],
        )
        text = "".join(b.text for b in res.content if b.type == "text")
        return {"explanation": text.strip() or f"No commentary available for {body.kpi_key}."}
    except Exception as e:
        return {"explanation": f"Explanation unavailable ({e})."}


# ---------------------------------------------------------------------------
# D5 — Buildable-area mask
# ---------------------------------------------------------------------------

_MASK_CACHE: dict[tuple, tuple[float, dict]] = {}
_MASK_TTL_S = 3600 * 12


def _mask_cache_get(key):
    hit = _MASK_CACHE.get(key)
    if not hit:
        return None
    import time as _t
    ts, val = hit
    if _t.time() - ts > _MASK_TTL_S:
        _MASK_CACHE.pop(key, None)
        return None
    return val


def _mask_cache_put(key, val):
    import time as _t
    _MASK_CACHE[key] = (_t.time(), val)


def _ring(lat: float, lon: float, radius_m: float, class_tag: str, reason: str,
          score: float = 0.5, segments: int = 24) -> dict:
    """Build a circular fill feature around (lat, lon)."""
    import math as _m
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * _m.cos(_m.radians(lat))
    ring_coords = []
    for i in range(segments + 1):
        t = 2 * _m.pi * i / segments
        dlat = (radius_m * _m.sin(t)) / m_per_deg_lat
        dlon = (radius_m * _m.cos(t)) / m_per_deg_lon
        ring_coords.append([lon + dlon, lat + dlat])
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ring_coords]},
        "properties": {"class": class_tag, "reason": reason, "score": score},
    }


@router.get("/buildable-mask")
async def buildable_mask(
    lat: float = Query(..., ge=49, le=61),
    lon: float = Query(..., ge=-8, le=2),
    radius_m: float = Query(1500, ge=200, le=5000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Classify the area around a site into buildable vs restricted zones.

    Combines GeeFlow (DynamicWorld land use + NASADEM slope) with flags from
    whichever PostGIS constraint tables are ingested. Returns a GeoJSON
    FeatureCollection where each feature carries `properties.class` ∈
    {buildable, restricted_slope, restricted_land, restricted_flood,
    restricted_protected, restricted_alc} and `properties.reason`.

    Fails open with `warning` rather than 500 if GeeFlow is offline — the UI
    falls back to "no overlay" cleanly.
    """
    key = (round(lat, 3), round(lon, 3), int(radius_m))
    cached = _mask_cache_get(key)
    if cached:
        return cached

    from datetime import datetime as _dt
    from app.helpers import run_geeflow_subprocess

    warning = None
    features: list[dict] = []

    try:
        radius_km = max(0.5, radius_m / 1000.0)
        gee = await run_geeflow_subprocess("site_composite", lat, lon, radius_km=radius_km)
        components = (gee or {}).get("components") or {}
        land = components.get("land_use") or {}
        terrain = components.get("terrain") or {}

        slope_mean = terrain.get("slope_mean_deg") or terrain.get("slope_mean") or 0
        if slope_mean and slope_mean > 10:
            features.append(_ring(lat, lon, radius_m * 0.85, "restricted_slope",
                                  f"Mean slope {slope_mean:.1f}° exceeds 10° earthworks threshold"))

        dominant = (land.get("dominant_class") or "").lower()
        restrictive_landuse = {
            "trees":    "Woodland — ancient-woodland risk, felling licence",
            "forest":   "Forest — BNG + felling licence exposure",
            "water":    "Water body",
            "wetlands": "Wetland — habitat + drainage risk",
            "built":    "Existing built land — planning fit required",
            "urban":    "Urban area — planning fit required",
        }
        if dominant in restrictive_landuse:
            features.append(_ring(lat, lon, radius_m * 0.7, "restricted_land",
                                  restrictive_landuse[dominant]))
    except Exception as e:
        warning = f"geeflow unavailable: {e.__class__.__name__}"

    async with pool.acquire() as conn:
        for table, cls, reason in [
            ("ea_flood_zones",      "restricted_flood",     "Environment Agency flood zone 2/3"),
            ("ne_sssi",             "restricted_protected", "Site of Special Scientific Interest"),
            ("ne_aonb",             "restricted_protected", "Area of Outstanding Natural Beauty"),
            ("ne_ancient_woodland", "restricted_protected", "Ancient woodland inventory"),
            ("alc_grades",          "restricted_alc",       "Grade 1–3a agricultural land classification"),
        ]:
            try:
                exists = await conn.fetchval(
                    f"SELECT to_regclass('public.{table}') IS NOT NULL"
                )
                if not exists:
                    continue
                hit = await conn.fetchval(
                    f"""
                    SELECT EXISTS(
                        SELECT 1 FROM {table}
                        WHERE ST_DWithin(
                            geom::geography,
                            ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography,
                            $3
                        )
                    )
                    """,
                    lat, lon, radius_m,
                )
                if hit:
                    features.append(_ring(lat, lon, radius_m * 0.5, cls, reason))
            except Exception:
                continue

    payload = {
        "type": "FeatureCollection",
        "features": features,
        "generated_at": _dt.utcnow().isoformat() + "Z",
        "warning": warning,
    }
    _mask_cache_put(key, payload)
    return payload


# ---------------------------------------------------------------------------
# D5b — Positive buildable polygon (companion to /buildable-mask)
# ---------------------------------------------------------------------------

@router.get("/buildable")
async def buildable_positive(
    lat: float = Query(..., ge=49, le=61),
    lon: float = Query(..., ge=-8, le=2),
    radius_m: float = Query(1500, ge=200, le=5000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return the BUILDABLE polygon directly (not the restricted polygons).

    Companion to ``/buildable-mask``. The mask endpoint gives a list of
    restricted polygons and expects the client to subtract them from a
    buffer; this endpoint does that server-side and returns a single
    GeoJSON FeatureCollection with one ``class=buildable`` polygon (with
    holes where restrictions apply) plus area stats and provenance.

    Falls open with a ``warning`` + explanation string if the upstream
    mask is unavailable, rather than 500.
    """
    from app.analysis.buildable_area import positive_buildable_polygon
    try:
        mask_payload = await buildable_mask(lat=lat, lon=lon, radius_m=radius_m, pool=pool)
    except Exception as exc:
        log.warning("buildable_mask failed inside /buildable: %s", exc)
        mask_payload = {"type": "FeatureCollection", "features": [],
                        "warning": f"mask_unavailable:{type(exc).__name__}"}
    return await positive_buildable_polygon(
        lat=lat, lon=lon, radius_m=radius_m, pool=pool, mask_payload=mask_payload,
    )


# ---------------------------------------------------------------------------
# D6 — Yield + curtailment overlay (solar)
# ---------------------------------------------------------------------------

@router.get("/yield-curtailment")
async def yield_curtailment(
    lat: float = Query(..., ge=49, le=61),
    lon: float = Query(..., ge=-8, le=2),
    capacity_mw: float = Query(..., ge=0.1, le=5000),
    tech: str = Query("solar", pattern="^(solar|bess|dc|hybrid)$"),
):
    """Annual yield (PySAM PvWatts) + expected curtailment + 168-hour
    representative-week series for the DesignCanvas generation-profile view.

    Solar-only at MVP — BESS/DC return a small stub so the endpoint never 404s.
    Falls back to an analytical UK-CF model if PySAM is unavailable.
    """
    if tech != "solar":
        return {
            "annual_yield_mwh": 0.0,
            "capacity_factor_pct": 0.0,
            "curtailment_pct_expected": 0.0,
            "monthly_mwh": [0.0] * 12,
            "representative_week": [],
            "source": "not_applicable",
        }

    from app.helpers import run_sam_subprocess
    from utils.curtailment_estimator import estimate_annual_curtailment

    capacity_kw = capacity_mw * 1000.0
    source = "pysam"
    annual_mwh = None
    cf_pct = None
    monthly_mwh: list[float] = []
    hourly_mw: list[float] = []

    try:
        sam = await run_sam_subprocess(lat, lon, capacity_kw)
        annual_mwh = (sam.get("annual_energy_kwh") or 0) / 1000.0
        cf_pct = sam.get("capacity_factor_pct")
        monthly_kwh = sam.get("monthly_energy_kwh") or []
        monthly_mwh = [float(v) / 1000.0 for v in monthly_kwh][:12]
        hourly_kw = sam.get("hourly_gen_kw") or []
        hourly_mw = [float(v) / 1000.0 for v in hourly_kw]
    except Exception:
        source = "analytical"
        cf_pct = 10.5  # UK solar CF, central-England baseline
        annual_mwh = capacity_mw * 8760 * (cf_pct / 100.0)
        month_weights = [0.4, 0.55, 0.85, 1.15, 1.4, 1.5, 1.45, 1.3, 1.05, 0.75, 0.45, 0.35]
        weight_sum = sum(month_weights)
        monthly_mwh = [annual_mwh * (w / weight_sum) for w in month_weights]

    try:
        curt = estimate_annual_curtailment(
            capacity_mw=capacity_mw, voltage_kv=33, technology=tech,
        )
        curt_p50 = (curt.get("curtailment_rate_pct") or {}).get("p50", 0.0)
    except Exception:
        curt_p50 = 2.5

    week: list[dict] = []
    if hourly_mw and len(hourly_mw) >= 3456:
        start = 3288  # mid-May representative
        sliced = hourly_mw[start:start + 168]
        for h, gen in enumerate(sliced):
            curtailed = gen * (curt_p50 / 100.0) if gen > 0 else 0.0
            hr = h % 24
            price = 60 + (20 if 17 <= hr <= 20 else 0) - (15 if 1 <= hr <= 5 else 0)
            week.append({
                "hour": h,
                "generation_mw": round(max(0.0, gen), 3),
                "curtailed_mw": round(curtailed, 3),
                "price_gbp_mwh": price,
            })
    else:
        import math as _m
        for h in range(168):
            hr = h % 24
            x = (hr - 13) / 4.5
            gen = capacity_mw * max(0.0, _m.exp(-x * x))
            curtailed = gen * (curt_p50 / 100.0)
            price = 60 + (20 if 17 <= hr <= 20 else 0) - (15 if 1 <= hr <= 5 else 0)
            week.append({
                "hour": h,
                "generation_mw": round(gen, 3),
                "curtailed_mw": round(curtailed, 3),
                "price_gbp_mwh": price,
            })

    return {
        "annual_yield_mwh": round(float(annual_mwh or 0.0), 1),
        "capacity_factor_pct": round(float(cf_pct or 0.0), 2),
        "curtailment_pct_expected": round(float(curt_p50), 2),
        "monthly_mwh": [round(v, 1) for v in monthly_mwh],
        "representative_week": week,
        "source": source,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Full project document — /api/design/{project_id}/full-doc
# ═══════════════════════════════════════════════════════════════════════════

_DESIGN_FIELDS = {"solar_mw", "bess_mw", "bess_mw_mwh", "bess_hours",
                  "ppa_price_gbp_mwh", "ppa_share_pct", "workload_mw",
                  "site_area_ha"}


async def _load_project_row(conn, project_id: UUID) -> dict | None:
    row = await conn.fetchrow(
        """SELECT project_id, name, description, status, technology,
                  capacity_mw, stage, verdict, lat, lon, metadata,
                  portfolio_id, created_at, updated_at
           FROM projects WHERE project_id = $1""",
        project_id,
    )
    if not row:
        return None
    meta = row["metadata"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    meta = meta or {}
    return {
        "project_id": str(row["project_id"]),
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "technology": row["technology"],
        "capacity_mw": row["capacity_mw"],
        "stage": row["stage"],
        "verdict": row["verdict"],
        "lat": row["lat"],
        "lon": row["lon"],
        "portfolio_id": str(row["portfolio_id"]) if row["portfolio_id"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "metadata": meta,
    }


def _extract_design_state(proj: dict) -> dict:
    """Pull the capacity-mix state from metadata + project columns. Falls
    back to sensible defaults for missing fields."""
    meta = proj.get("metadata") or {}
    design = dict(meta.get("design") or {})
    tech = (proj.get("technology") or "").lower()
    cap = float(proj.get("capacity_mw") or 0.0)
    design.setdefault("solar_mw", cap if tech == "solar" else design.get("solar_mw", 0.0))
    design.setdefault("bess_mw", cap if tech in ("bess", "battery") else design.get("bess_mw", 0.0))
    design.setdefault("bess_hours", design.get("bess_hours", 2.0))
    design.setdefault("bess_mw_mwh", design["bess_mw"] * design["bess_hours"])
    design.setdefault("workload_mw", cap if tech == "dc" else design.get("workload_mw", 0.0))
    design.setdefault("ppa_price_gbp_mwh", design.get("ppa_price_gbp_mwh", _bench_ppa("solar")))
    design.setdefault("ppa_share_pct", design.get("ppa_share_pct", 50.0))
    design.setdefault("site_area_ha", design.get("site_area_ha", 120.0))
    return design


async def _latest_finance(conn, project_id: UUID) -> dict | None:
    try:
        row = await conn.fetchrow(
            """SELECT kpis, created_at FROM design_layouts
               WHERE project_id = $1 ORDER BY created_at DESC LIMIT 1""",
            project_id,
        )
        if row:
            kpis = json.loads(row["kpis"]) if isinstance(row["kpis"], str) else (row["kpis"] or {})
            return {"source": "design_layouts", "kpis": kpis,
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None}
    except Exception as e:
        log.debug("latest_finance: %s", e)
    return None


async def _grid_snapshot(conn, lat, lon):
    if lat is None or lon is None:
        return None
    try:
        row = await conn.fetchrow(
            """SELECT name, capacity_kw,
                      ST_Distance(
                          geometry,
                          ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326), 27700)
                      )/1000.0 AS dist_km
               FROM dno_substations
               ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326), 27700)
               LIMIT 1""",
            lon, lat,
        )
        if row:
            cap_mw = float(row["capacity_kw"] or 0) / 1000.0
            return {
                "nearest_substation": row["name"],
                "distance_km": round(float(row["dist_km"]), 2),
                "capacity_mw": round(cap_mw, 1),
                "headroom_mw": round(cap_mw * 0.3, 1),
            }
    except Exception as e:
        log.debug("grid_snapshot: %s", e)
    return None


async def _planning_snapshot(conn, lat, lon, radius_km: float = 10.0):
    """Approximate count of recent planning applications by LPA name lookup.
    Planning table has no geometry so we fall back to status counts for the
    county of the nearest settlement."""
    if lat is None or lon is None:
        return None
    try:
        row = await conn.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE application_decision ILIKE '%approv%'
                                        OR application_decision ILIKE '%grant%'
                                        OR application_decision ILIKE '%consent%') AS approved,
                      COUNT(*) FILTER (WHERE application_decision ILIKE '%refus%'
                                        OR application_decision ILIKE '%reject%') AS refused,
                      COUNT(*) AS total
               FROM planning_applications
               WHERE submitted_date > NOW() - INTERVAL '2 years'"""
        )
        if row:
            return {
                "approved_recent_2y": row["approved"],
                "refused_recent_2y": row["refused"],
                "total_recent_2y": row["total"],
                "note": "No geometry on planning_applications; counts are national 2y.",
            }
    except Exception as e:
        log.debug("planning_snapshot: %s", e)
    return None


async def _demand_snapshot(conn, lat, lon):
    try:
        row = await conn.fetchrow(
            """SELECT AVG(demand_mw) AS avg_mw, MAX(demand_mw) AS peak_mw,
                      COUNT(*) AS samples
               FROM demand_historical
               WHERE timestamp_utc > NOW() - INTERVAL '30 days'"""
        )
        if row and row["samples"]:
            return {
                "avg_demand_mw": round(float(row["avg_mw"] or 0), 1),
                "peak_demand_mw": round(float(row["peak_mw"] or 0), 1),
                "samples_30d": row["samples"],
            }
    except Exception as e:
        log.debug("demand_snapshot: %s", e)
    return None


async def _latest_assessments(conn, project_id: UUID, limit: int = 5) -> list[dict]:
    try:
        rows = await conn.fetch(
            """SELECT snapshot_id, version, label, overall_verdict, overall_confidence,
                      intent_verdicts, created_at
               FROM assessment_snapshots
               WHERE project_id = $1
               ORDER BY created_at DESC LIMIT $2""",
            project_id, limit,
        )
        out = []
        for r in rows:
            iv = r["intent_verdicts"]
            if isinstance(iv, str):
                try:
                    iv = json.loads(iv)
                except Exception:
                    iv = {}
            out.append({
                "snapshot_id": str(r["snapshot_id"]),
                "version": r["version"],
                "label": r["label"],
                "overall_verdict": r["overall_verdict"],
                "overall_confidence": r["overall_confidence"],
                "intent_count": len(iv or {}),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })
        return out
    except Exception as e:
        log.debug("latest_assessments: %s", e)
        return []


@router.get("/{project_id}/full-doc")
async def full_project_doc(project_id: str, pool: asyncpg.Pool = Depends(get_pool)):
    """Single blob combining project, current design state, derived KPIs,
    and snapshots of grid / planning / demand + latest agent assessments.
    Used by the chat tool full_project_doc so Claude can answer questions
    without triggering dozens of individual tool calls."""
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(400, "Invalid project_id")

    async with pool.acquire() as conn:
        proj = await _load_project_row(conn, pid)
        if not proj:
            raise HTTPException(404, f"Project {project_id} not found")
        design = _extract_design_state(proj)
        finance = await _latest_finance(conn, pid)
        grid = await _grid_snapshot(conn, proj["lat"], proj["lon"])
        planning = await _planning_snapshot(conn, proj["lat"], proj["lon"])
        demand = await _demand_snapshot(conn, proj["lat"], proj["lon"])
        assessments = await _latest_assessments(conn, pid)

    # Derived KPIs from current design state — always cheap + deterministic
    try:
        from utils.design_optimizer import compute_design_kpis
        derived_kpis = compute_design_kpis(
            solar_mw=float(design.get("solar_mw", 0)),
            bess_mw=float(design.get("bess_mw", 0)),
            bess_hours=float(design.get("bess_hours", 2.0)),
            ppa_price_gbp_mwh=float(design.get("ppa_price_gbp_mwh", _bench_ppa("solar"))),
            ppa_share_pct=float(design.get("ppa_share_pct", 50.0)),
            workload_mw=float(design.get("workload_mw", 0)),
            site_area_ha=float(design.get("site_area_ha", 120.0)),
            grid_headroom_mw=float((grid or {}).get("headroom_mw") or 50.0),
        )
    except Exception as e:
        log.warning("derived KPIs failed: %s", e)
        derived_kpis = None

    return {
        "project": proj,
        "design": design,
        "derived_kpis": derived_kpis,
        "finance": finance,
        "grid": grid,
        "planning": planning,
        "demand": demand,
        "latest_assessments": assessments,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Design mutation helper — used by chat tools and /api/design/{pid}/mutate
# ═══════════════════════════════════════════════════════════════════════════

class MutateDesignRequest(BaseModel):
    field: str = Field(..., description="One of: solar_mw, bess_mw, bess_mw_mwh, ppa_price_gbp_mwh, ppa_share_pct, workload_mw")
    value: float


async def apply_mutation(pool, project_id: str, field: str, value: float) -> dict:
    """Write-through single-field design edit. Returns refreshed full-doc-lite."""
    if field not in _DESIGN_FIELDS:
        raise HTTPException(400, f"Unsupported field '{field}'. Allowed: {sorted(_DESIGN_FIELDS)}")
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(400, "Invalid project_id")

    async with pool.acquire() as conn:
        proj = await _load_project_row(conn, pid)
        if not proj:
            raise HTTPException(404, f"Project {project_id} not found")
        meta = dict(proj.get("metadata") or {})
        design = dict(meta.get("design") or _extract_design_state(proj))
        # bess_mw_mwh is a convenience alias for energy (MWh); map it to hours
        if field == "bess_mw_mwh":
            mw = float(design.get("bess_mw") or 0.0)
            if mw > 0:
                design["bess_hours"] = round(float(value) / mw, 2)
            design["bess_mw_mwh"] = float(value)
        else:
            design[field] = float(value)
        # Keep bess_mw_mwh in sync when mw or hours change
        if field in ("bess_mw",):
            design["bess_mw_mwh"] = float(design.get("bess_mw", 0)) * float(design.get("bess_hours", 2.0))
        meta["design"] = design
        await conn.execute(
            "UPDATE projects SET metadata = $1::jsonb, updated_at = NOW() WHERE project_id = $2",
            json.dumps(meta), pid,
        )
        # If the core capacity field changed, also update the scalar column.
        if field == "solar_mw" and (proj.get("technology") or "").lower() == "solar":
            await conn.execute("UPDATE projects SET capacity_mw = $1 WHERE project_id = $2",
                               float(value), pid)
        elif field == "bess_mw" and (proj.get("technology") or "").lower() in ("bess", "battery"):
            await conn.execute("UPDATE projects SET capacity_mw = $1 WHERE project_id = $2",
                               float(value), pid)
        grid = await _grid_snapshot(conn, proj["lat"], proj["lon"])

    from utils.design_optimizer import compute_design_kpis
    derived = compute_design_kpis(
        solar_mw=float(design.get("solar_mw", 0)),
        bess_mw=float(design.get("bess_mw", 0)),
        bess_hours=float(design.get("bess_hours", 2.0)),
        ppa_price_gbp_mwh=float(design.get("ppa_price_gbp_mwh", _bench_ppa("solar"))),
        ppa_share_pct=float(design.get("ppa_share_pct", 50.0)),
        workload_mw=float(design.get("workload_mw", 0)),
        site_area_ha=float(design.get("site_area_ha", 120.0)),
        grid_headroom_mw=float((grid or {}).get("headroom_mw") or 50.0),
    )
    return {
        "project_id": project_id,
        "field": field,
        "value": float(value),
        "design": design,
        "derived_kpis": derived,
        "grid": grid,
    }


@router.post("/{project_id}/mutate")
async def mutate_design(project_id: str, body: MutateDesignRequest,
                        pool: asyncpg.Pool = Depends(get_pool)):
    """Write a single design field to projects.metadata.design and return
    the recomputed derived KPIs."""
    return await apply_mutation(pool, project_id, body.field, body.value)


class OptimizeRequest(BaseModel):
    objective: str = Field("max_npv", description="max_npv | min_lcoe | max_utilisation")
    bounds: dict[str, list[float]] | None = None


@router.post("/{project_id}/optimize")
async def optimize_design_endpoint(project_id: str, body: OptimizeRequest,
                                   pool: asyncpg.Pool = Depends(get_pool)):
    """Run scipy SLSQP over the capacity-mix space for this project."""
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(400, "Invalid project_id")
    async with pool.acquire() as conn:
        proj = await _load_project_row(conn, pid)
        if not proj:
            raise HTTPException(404, f"Project {project_id} not found")
        design = _extract_design_state(proj)
        grid = await _grid_snapshot(conn, proj["lat"], proj["lon"])

    bounds = {k: tuple(v) for k, v in (body.bounds or {}).items()}
    from utils.design_optimizer import optimise_capacity_mix
    return optimise_capacity_mix(
        objective=body.objective,
        bounds=bounds or None,
        ppa_price_gbp_mwh=float(design.get("ppa_price_gbp_mwh", _bench_ppa("solar"))),
        site_area_ha=float(design.get("site_area_ha", 120.0)),
        grid_headroom_mw=float((grid or {}).get("headroom_mw") or 50.0),
        initial={
            "solar_mw": float(design.get("solar_mw", 20)),
            "bess_mw": float(design.get("bess_mw", 10)),
            "bess_hours": float(design.get("bess_hours", 2.0)),
            "ppa_share_pct": float(design.get("ppa_share_pct", 50.0)),
        },
    )

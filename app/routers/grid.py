"""Grid router — grid data, connection assessment, capacity, digital twin, OSM."""

from __future__ import annotations

import asyncio
import json
import math
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
import asyncpg

from app.deps import get_pool

from utils.grid_data_platform import (
    UK_DATA_SOURCES, UK_SUBSTATIONS,
    find_nearest_substation as gdp_nearest_sub,
    substations_in_radius, connection_cost_estimate,
    dashboard_stats as gdp_dashboard_stats,
    health_check as gdp_health_check,
    record_metric, query_metrics,
)
from utils.grid_data_ingester import (
    ingest_all_dnos,
    latest_ingest_status_per_source,
    DNO_CONFIGS as _GRID_DNO_CONFIGS,
)
from utils.grid_connection_analyser import (
    assess_connection as gc_assess,
    capacity_map_geojson as gc_capacity_map,
    substation_detail as gc_substation_detail,
    grid_lines_geojson as gc_lines_geojson,
    estimate_connection_cost as gc_cost_estimate,
    tier2_power_flow as gc_power_flow,
)
from utils.connection_offer_forecaster import (
    forecast_connection_offer,
    batch_forecast as batch_connection_forecast_fn,
)
from utils.national_grid_live import fetch_all_live, live_data_to_geojson
from utils.uk_grid_topology import topology_to_geojson
from utils.grid_stability_predictor import predict_grid_stability
from utils.energy_demand_predictor import get_demand_forecast, simulate_storage, optimize_storage
from utils.agile_pricing import get_pricing_overview, fetch_all_regions_current, regional_prices_to_geojson
from utils.weave_demand import demand_geojson
from utils.osm_power_infra import (
    power_lines_geojson, power_substations_geojson, power_towers_geojson,
    power_generators_geojson, power_plants_geojson, power_infra_summary,
)

router = APIRouter(tags=["grid"])


# ─── Grid Data Sources & Substations ──────────────────────────────────────────

@router.get("/grid/data_sources")
async def list_data_sources():
    """List UK DNO and grid data sources."""
    return UK_DATA_SOURCES


@router.get("/grid/substations")
async def list_substations(
    lat: float = Query(None),
    lon: float = Query(None),
    radius_km: float = Query(50, ge=1, le=500),
    min_voltage_kv: int = Query(0, ge=0),
):
    """List UK substations, optionally filtered by proximity."""
    if lat is not None and lon is not None:
        return substations_in_radius(lat, lon, radius_km)
    subs = UK_SUBSTATIONS
    if min_voltage_kv > 0:
        subs = [s for s in subs if s["voltage_kv"] >= min_voltage_kv]
    return subs


@router.get("/grid/substations/nearest")
async def nearest_substation(
    lat: float = Query(52.5),
    lon: float = Query(-1.5),
    min_voltage_kv: int = Query(0),
):
    """Find the nearest registered UK substation."""
    result = gdp_nearest_sub(lat, lon, min_voltage_kv)
    if not result:
        raise HTTPException(status_code=404, detail="No matching substation found")
    return result


@router.get("/grid/connection_cost")
async def grid_connection_cost(
    distance_km: float = Query(2.0, ge=0.1),
    capacity_kw: float = Query(100, ge=1),
    voltage_kv: int = Query(33),
):
    """Estimate grid connection cost for a solar installation."""
    return connection_cost_estimate(distance_km, capacity_kw, voltage_kv)


# ─── Real-Time System Prices (BMRS DETSYSPRICES) ────────────────────────────

@router.get("/api/grid/system-prices")
async def api_system_prices():
    """Return current real-time wholesale system buy/sell prices from BMRS.

    These are the ACTUAL prices generators receive under the Balancing
    Mechanism (DETSYSPRICES), not retail tariffs. Returns:
    - sell_price_gbp_mwh: System Sell Price (what generators receive)
    - buy_price_gbp_mwh: System Buy Price (imbalance cost)
    - spread_gbp_mwh: Buy-Sell spread
    - settlement_period / date / timestamp
    """
    from utils.live_grid_status import get_system_prices

    result = await get_system_prices()
    if result.get("sell_price_gbp_mwh") is None:
        raise HTTPException(
            status_code=503,
            detail="BMRS system prices temporarily unavailable",
        )
    return result


# ─── Grid Connection & Capacity Module ────────────────────────────────────────

@router.post("/api/grid/assess")
async def api_grid_assess(
    lat: float = Query(52.5),
    lon: float = Query(-1.5),
    capacity_mw: float = Query(5.0, ge=0.001),
    technology: str = Query("solar"),
    radius_km: float = Query(30.0, ge=1, le=100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Assess grid connection feasibility at a location.

    Returns nearest substations with headroom, queue depth, cost estimate,
    and GO/CAUTION/NO-GO verdict.
    """
    async with pool.acquire() as conn:
        result = await gc_assess(
            conn, lat=lat, lon=lon, capacity_mw=capacity_mw,
            technology=technology, search_radius_km=radius_km,
        )
    record_metric("grid_assessment", capacity_mw,
                  labels={"technology": technology, "lat": lat, "lon": lon})
    return result


@router.post("/api/grid/power-flow")
async def api_grid_power_flow(
    lat: float = Query(...),
    lon: float = Query(...),
    capacity_mw: float = Query(5),
    technology: str = Query("solar"),
    substation_id: int = Query(None),
    contingency: bool = Query(False),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Tier 2 power flow validation using pandapower.

    Builds a network model from nearby substations and grid lines,
    adds the proposed connection, runs Newton-Raphson power flow,
    and checks thermal limits, voltage deviations, and constraints.
    Optionally runs N-1 contingency analysis.
    """
    async with pool.acquire() as conn:
        result = await gc_power_flow(
            conn, lat, lon,
            capacity_mw=capacity_mw,
            technology=technology,
            connection_substation_id=substation_id,
            contingency=contingency,
        )
    record_metric("grid_power_flow", capacity_mw,
                  labels={"technology": technology, "lat": lat, "lon": lon})
    return result


@router.post("/api/grid/connection-forecast")
async def api_connection_forecast(
    lat: float = Query(51.5),
    lon: float = Query(-1.0),
    capacity_mw: float = Query(50, ge=0.001),
    technology: str = Query("solar"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Predict connection offer timeline, cost, and risk for a proposed
    grid connection BEFORE the developer applies.

    Uses real TEC gate data, ECR queue depth, substation capacity,
    and REPD historical outcomes.
    """
    result = await forecast_connection_offer(
        pool, lat=lat, lon=lon, capacity_mw=capacity_mw, technology=technology,
    )
    record_metric("connection_forecast", capacity_mw,
                  labels={"technology": technology, "lat": lat, "lon": lon})
    return result


@router.post("/api/grid/batch-connection-forecast")
async def api_batch_connection_forecast(
    body: list[dict],
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Batch forecast for multiple candidate sites.

    Accepts a JSON array of site objects, each with lat, lon,
    capacity_mw (optional, default 50), technology (optional, default solar),
    and name (optional).

    Returns sites ranked by composite connection feasibility score.
    """
    if not body:
        raise HTTPException(400, "Empty site list")
    if len(body) > 50:
        raise HTTPException(400, "Maximum 50 sites per batch")
    result = await batch_connection_forecast_fn(pool, body)
    record_metric("batch_connection_forecast", len(body))
    return result


@router.get("/api/grid/tec-timelines")
async def api_tec_timelines(
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Analyse connection timelines from real ESO TEC gate data.

    Returns statistical breakdown by gate, technology, capacity band,
    and host TO region — modelled from 2,563 real TEC projects.
    """
    from utils.tec_timeline_model import analyse_tec_timelines
    result = await analyse_tec_timelines(pool)
    record_metric("tec_timelines", 1)
    return result


@router.post("/api/grid/predict-timeline")
async def api_predict_timeline(
    capacity_mw: float = Query(50, ge=0.1, le=5000),
    technology: str = Query("solar"),
    host_to: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Predict connection timeline for a proposed project.

    Uses real TEC gate data to estimate P10/P50/P90 timelines.
    """
    from utils.tec_timeline_model import predict_connection_timeline
    result = await predict_connection_timeline(
        pool,
        capacity_mw=capacity_mw,
        technology=technology,
        host_to=host_to,
    )
    record_metric("predict_timeline", capacity_mw,
                  labels={"technology": technology})
    return result


@router.get("/api/grid/substation/{substation_id}")
async def api_grid_substation(
    substation_id: int,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Full detail for a grid substation including connected DER, TEC queue,
    and capacity history.

    Legacy shape retained for back-compat. For the dense 8-section layout
    wanted by DNOs / consultants / developers, use
    ``GET /api/grid/substation/{substation_id}/detail``.
    """
    async with pool.acquire() as conn:
        result = await gc_substation_detail(conn, substation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Substation not found")
    return result


@router.get("/api/grid/substation/{substation_id}/detail")
async def api_grid_substation_detail(
    substation_id: int,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Dense, 8-section enriched detail for a substation.

    Sections: identity, electrical, capacity_state, connections, queue,
    regulatory, environment, engineering. Every section carries its own
    provenance block; missing upstreams return an ``_explanation`` rather
    than a 500.
    """
    from utils.substation_detail import enriched_substation_detail
    try:
        result = await enriched_substation_detail(pool, substation_id)
    except Exception as e:  # noqa: BLE001 — never 500 on this route
        return {
            "error": f"enriched_substation_detail raised {type(e).__name__}: {e}",
            "substation_id": substation_id,
        }
    if result is None:
        raise HTTPException(status_code=404, detail="Substation not found")
    return result


@router.get("/api/grid/capacity-map")
async def api_grid_capacity_map(
    dno: str = Query(None),
    min_voltage_kv: float = Query(None),
    west: float = Query(None),
    south: float = Query(None),
    east: float = Query(None),
    north: float = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    GeoJSON FeatureCollection of substations colour-coded by capacity headroom.
    """
    bbox = None
    if all(v is not None for v in [west, south, east, north]):
        bbox = (west, south, east, north)
    async with pool.acquire() as conn:
        return await gc_capacity_map(conn, dno=dno, min_voltage_kv=min_voltage_kv, bbox=bbox)


@router.get("/api/grid/lines")
async def api_grid_lines(
    min_voltage_kv: float = Query(132),
    west: float = Query(None),
    south: float = Query(None),
    east: float = Query(None),
    north: float = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """GeoJSON FeatureCollection of grid transmission/distribution lines."""
    bbox = None
    if all(v is not None for v in [west, south, east, north]):
        bbox = (west, south, east, north)
    async with pool.acquire() as conn:
        return await gc_lines_geojson(conn, min_voltage_kv=min_voltage_kv, bbox=bbox)


@router.get("/api/grid/ecr")
async def api_grid_ecr(
    dno: str = Query(None),
    technology: str = Query(None),
    substation_id: int = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Query Embedded Capacity Register entries across all DNOs."""
    conditions = []
    params = []
    idx = 1
    if dno:
        conditions.append(f"dno = ${idx}")
        params.append(dno)
        idx += 1
    if technology:
        conditions.append(f"technology = ${idx}")
        params.append(technology)
        idx += 1
    if substation_id:
        conditions.append(f"substation_id = ${idx}")
        params.append(substation_id)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT id, site_name, dno, technology, capacity_mw, voltage_kv,
                   substation_name, status,
                   ST_X(ST_Transform(geom, 4326)) AS lon,
                   ST_Y(ST_Transform(geom, 4326)) AS lat
            FROM grid_ecr
            {where}
            ORDER BY capacity_mw DESC NULLS LAST
            LIMIT {limit}
        """, *params)
    return [dict(r) for r in rows]


@router.get("/api/grid/queue")
async def api_grid_queue(
    substation_id: int = Query(None),
    substation_name: str = Query(None),
    dno: str = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Connection queue analysis at a specific substation or DNO area."""
    async with pool.acquire() as conn:
        if substation_id:
            sub = await gc_substation_detail(conn, substation_id)
            if not sub:
                raise HTTPException(404, "Substation not found")
            return {
                "substation": sub["name"],
                "queue_summary": sub["queue_summary"],
                "connected_der": sub["connected_der"],
                "tec_entries": sub["tec_entries"],
            }
        elif substation_name:
            from utils.eso_tec_register import connection_queue_analysis
            return await connection_queue_analysis(conn, substation_name)
        elif dno:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status ILIKE '%%queue%%' OR status ILIKE '%%accepted%%') AS queued,
                    COALESCE(SUM(capacity_mw), 0) AS total_mw
                FROM grid_ecr WHERE dno = $1
            """, dno)
            return {"dno": dno, **dict(row)}
        else:
            raise HTTPException(400, "Provide substation_id, substation_name, or dno")


@router.post("/api/grid/ingest")
async def api_grid_ingest(
    dno: str = Query(None, description="Specific DNO to ingest, or all if omitted"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Trigger grid data ingestion (manual refresh)."""
    if dno:
        from utils.grid_data_ingester import get_adapter, upsert_substations, upsert_ecr
        adapter = get_adapter(dno)
        async with pool.acquire() as conn:
            subs = await adapter.fetch_substations()
            sub_count = await upsert_substations(conn, subs) if subs else 0
            ecr = await adapter.fetch_ecr()
            ecr_count = await upsert_ecr(conn, ecr) if ecr else 0
        return {"dno": dno, "substations": sub_count, "ecr": ecr_count}
    else:
        result = await ingest_all_dnos(pool)
        return result


@router.get("/api/grid/ingestion-log")
async def api_grid_ingestion_log(
    limit: int = Query(20, ge=1, le=100),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Recent grid data ingestion log entries."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT source, dataset, status, records_fetched, records_upserted,
                   error, started_at, finished_at
            FROM grid_ingestion_log
            ORDER BY started_at DESC
            LIMIT $1
        """, limit)
    return [dict(r) for r in rows]


# ─── Task #21: DNO Ingestion Health + Manual Trigger ──────────────────────

def _require_admin(x_admin_token: str | None) -> None:
    """Lightweight admin gate. Uses ADMIN_INGEST_TOKEN env var.

    If the env var is unset we allow the call (dev / local). In prod set
    ADMIN_INGEST_TOKEN to any non-empty string and pass it as
    X-Admin-Token header to authorise.
    """
    import os as _os
    expected = _os.environ.get("ADMIN_INGEST_TOKEN")
    if not expected:
        return
    if not x_admin_token or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="admin token required")


@router.get("/api/grid/ingest-status")
async def api_grid_ingest_status(
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Latest grid ingestion run summary, grouped by (source, dataset).

    Returns one row per (DNO, dataset) showing the most recent run's status,
    timestamps, and row counts. Unified view of every DNO so operators
    can see at a glance which feeds are live / stale / failing.
    """
    rows = await latest_ingest_status_per_source(pool)

    # Enrich with the configured DNO set so missing feeds show as 'never_run'.
    known_sources = set(_GRID_DNO_CONFIGS.keys())
    seen = {(r["source"], r["dataset"]) for r in rows}
    now_iso = datetime.utcnow().isoformat() + "Z"
    for dno_code in known_sources:
        for dataset in ("substations", "ecr"):
            if (dno_code, dataset) not in seen:
                rows.append({
                    "source": dno_code,
                    "dataset": dataset,
                    "status": "never_run",
                    "records_fetched": 0,
                    "records_upserted": 0,
                    "rows_inserted": 0,
                    "rows_updated": 0,
                    "rows_failed": 0,
                    "error_message": None,
                    "started_at": None,
                    "finished_at": None,
                })

    # Summary roll-up by source
    by_source: dict[str, dict] = {}
    for r in rows:
        s = r["source"]
        entry = by_source.setdefault(s, {
            "source": s,
            "datasets": [],
            "status": "success",
            "last_success_at": None,
        })
        entry["datasets"].append(r)
        if r["status"] in ("failed", "never_run"):
            entry["status"] = "failed" if r["status"] == "failed" else "never_run"
        elif r["status"] == "partial" and entry["status"] == "success":
            entry["status"] = "partial"
        fin = r.get("finished_at")
        if r["status"] in ("success", "partial") and fin:
            prev = entry["last_success_at"]
            if prev is None or (fin and fin > prev):
                entry["last_success_at"] = fin

    return {
        "generated_at": now_iso,
        "sources": list(by_source.values()),
        "runs": rows,
    }


@router.post("/api/grid/ingest-run")
async def api_grid_ingest_run(
    dno: str | None = Query(None, description="Restrict to one DNO slug."),
    dry_run: bool = Query(False, description="Fetch but do not persist."),
    background: bool = Query(False, description="Queue run and return immediately."),
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Admin-only manual trigger for the DNO ingestion pipeline.

    Requires `X-Admin-Token` header matching ADMIN_INGEST_TOKEN env var.
    If ADMIN_INGEST_TOKEN is unset (typical for dev / local), the call is
    accepted without auth.
    """
    _require_admin(x_admin_token)
    if dno and dno not in _GRID_DNO_CONFIGS:
        raise HTTPException(status_code=400, detail=f"unknown dno: {dno}")

    if background:
        asyncio.create_task(ingest_all_dnos(pool, only=dno, dry_run=dry_run))
        return {"queued": True, "dno": dno or "all", "dry_run": dry_run}

    result = await ingest_all_dnos(pool, only=dno, dry_run=dry_run)
    return result


# ─── Grid Dashboard, Health, Metrics ─────────────────────────────────────────

@router.get("/grid/dashboard")
async def grid_dashboard():
    """Grid data platform dashboard statistics."""
    from app.jobs import list_jobs
    return gdp_dashboard_stats(list_jobs())


@router.get("/grid/health")
async def grid_health(pool: asyncpg.Pool = Depends(get_pool)):
    """Multi-component system health check."""
    return await gdp_health_check(pool)


@router.get("/grid/metrics")
async def grid_metrics(
    name: str = Query(None),
    metric_type: str = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Query collected grid/system metrics."""
    return query_metrics(name=name, metric_type=metric_type, limit=limit)


@router.get("/grid/topology")
async def grid_topology():
    """Return full UK national grid topology as WGS84 GeoJSON FeatureCollections.

    Uses ~330 nodes (GSPs + BSPs) covering all of Great Britain with ~500+
    transmission lines.
    """
    return topology_to_geojson()


@router.get("/grid/stability")
async def grid_stability(
    tau_base: float = 4.0,
    gamma_base: float = 0.5,
    demand_scale: float = 1.0,
    renewable_pen: float = 0.3,
    ev_load: float = 0.0,
    storage_factor: float = 0.0,
):
    """DSGC grid stability simulation — predict per-node stability under a scenario."""
    from utils.uk_grid_topology import build_topology
    nodes, edges = build_topology()
    scenario = {
        "tau_base": tau_base,
        "gamma_base": gamma_base,
        "demand_scale": demand_scale,
        "renewable_pen": renewable_pen,
        "ev_load": ev_load,
        "storage_factor": storage_factor,
    }
    return predict_grid_stability(nodes, edges, scenario)


@router.get("/grid/live")
async def grid_live():
    """Return live National Grid data (generation mix, interconnectors, carbon) as GeoJSON."""
    data = await fetch_all_live()
    return live_data_to_geojson(data)


@router.get("/grid/demand-forecast")
async def grid_demand_forecast():
    """Return demand forecast (24h + 7d) with storage optimization.

    Uses live BMRS data calibrated with seasonal SARIMA-style patterns.
    Includes 2050 storage optimization scenarios.
    """
    return await get_demand_forecast()


@router.get("/grid/storage-sim")
async def grid_storage_sim(
    renewable_gw: float = Query(250, ge=50, le=500),
    demand_twh: float = Query(692, ge=200, le=1200),
):
    """Run energy balance simulation for given renewable capacity.

    Returns daily storage dynamics, curtailment, and adequacy metrics.
    """
    return simulate_storage(renewable_gw=renewable_gw, demand_twh_yr=demand_twh)


@router.get("/grid/agile-pricing")
async def grid_agile_pricing(
    region: str = Query("C", min_length=1, max_length=1),
    tariff: str = Query("24-10-01"),
):
    """Return Octopus Agile half-hourly electricity prices.

    Includes current price, heatmap, cheapest/peak windows,
    and regional price map for all 14 DNO regions.
    """
    return await get_pricing_overview(region=region, tariff=tariff)


@router.get("/grid/agile-map")
async def grid_agile_map():
    """Return current Agile prices for all UK regions as GeoJSON.

    For the map pricing heatmap overlay.
    """
    region_prices = await fetch_all_regions_current()
    if not region_prices:
        return {"type": "FeatureCollection", "features": []}
    return regional_prices_to_geojson(region_prices)


@router.get("/grid/demand-map")
async def grid_demand_map(pool: asyncpg.Pool = Depends(get_pool)):
    """Return Weave smart meter demand data as GeoJSON FeatureCollection."""
    async with pool.acquire() as conn:
        return await demand_geojson(conn)


# ─── OSM Power Infrastructure ────────────────────────────────────────────────

@router.get("/grid/osm/lines")
async def grid_osm_lines(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    min_voltage_kv: float = Query(0),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return OSM power lines/cables as GeoJSON for the given bbox."""
    async with pool.acquire() as conn:
        return await power_lines_geojson(conn, (west, south, east, north), min_voltage_kv)


@router.get("/grid/osm/substations")
async def grid_osm_substations(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return OSM power substations as GeoJSON for the given bbox."""
    async with pool.acquire() as conn:
        return await power_substations_geojson(conn, (west, south, east, north))


@router.get("/grid/osm/towers")
async def grid_osm_towers(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return OSM power towers/poles as GeoJSON for the given bbox."""
    async with pool.acquire() as conn:
        return await power_towers_geojson(conn, (west, south, east, north))


@router.get("/grid/osm/generators")
async def grid_osm_generators(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return OSM power generators as GeoJSON for the given bbox."""
    async with pool.acquire() as conn:
        return await power_generators_geojson(conn, (west, south, east, north))


@router.get("/grid/osm/plants")
async def grid_osm_plants(
    west: float = Query(...), south: float = Query(...),
    east: float = Query(...), north: float = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return OSM power plants as GeoJSON for the given bbox."""
    async with pool.acquire() as conn:
        return await power_plants_geojson(conn, (west, south, east, north))


@router.get("/grid/osm/summary")
async def grid_osm_summary(pool: asyncpg.Pool = Depends(get_pool)):
    """Return counts and voltage distribution for all OSM power data."""
    async with pool.acquire() as conn:
        return await power_infra_summary(conn)


# ═══════════════════════════════════════════════════════════════════════════════
#  DC ADVANCED DESIGN — Surpass Ramboll capabilities
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/dc/heat-reuse")
async def api_dc_heat_reuse(
    it_load_kw: float = Query(10000),
    pue: float = Query(1.3),
    cooling_type: str = Query("hybrid"),
    lat: float = Query(52.0),
    nearest_heat_network_km: float = Query(2.0),
    district_heat_demand_mw: float = Query(5.0),
):
    """Model waste heat recovery and district heating revenue opportunity."""
    from utils.dc_advanced_design import heat_reuse_assessment
    return heat_reuse_assessment(it_load_kw, pue, cooling_type, lat,
                                 nearest_heat_network_km, district_heat_demand_mw)


@router.post("/api/dc/liquid-cooling")
async def api_dc_liquid_cooling(
    it_load_kw: float = Query(10000),
    target_rack_kw: float = Query(40),
    lat: float = Query(52.0),
):
    """Compare all cooling technologies including liquid/immersion options."""
    from utils.dc_advanced_design import liquid_cooling_comparison
    return liquid_cooling_comparison(it_load_kw, target_rack_kw, lat)


@router.post("/api/dc/bng")
async def api_dc_bng(
    site_area_ha: float = Query(5.0),
    existing_habitat: str = Query("improved_grassland"),
    development_footprint_pct: float = Query(80),
    on_site_habitat_pct: float = Query(10),
):
    """Biodiversity Net Gain (BNG) cost estimation — 10% mandatory offset."""
    from utils.dc_advanced_design import bng_assessment
    return bng_assessment(site_area_ha, existing_habitat,
                           development_footprint_pct, on_site_habitat_pct)


@router.post("/api/dc/community-sentiment")
async def api_dc_community_sentiment(
    lat: float = Query(52.0),
    lon: float = Query(-1.0),
    it_load_mw: float = Query(30),
    site_area_ha: float = Query(5.0),
    nearest_residential_m: float = Query(500),
    nearest_school_m: float = Query(1000),
    existing_industrial: bool = Query(False),
    height_m: float = Query(15),
    backup_generators: int = Query(10),
    construction_months: int = Query(24),
):
    """Predict community objection risk and recommend mitigation strategy."""
    from utils.dc_advanced_design import community_sentiment_assessment
    return community_sentiment_assessment(
        lat, lon, it_load_mw, site_area_ha,
        nearest_residential_m, nearest_school_m,
        existing_industrial, height_m, backup_generators, construction_months,
    )


@router.post("/api/dc/thermal-field")
async def api_dc_thermal_field(
    rack_count: int = Query(50),
    rack_kw: float = Query(15),
    rows: int = Query(5),
    cooling_type: str = Query("air_crac"),
    crac_count: int = Query(4),
    containment: str = Query("hot_aisle"),
    supply_temp_c: float = Query(18),
):
    """CFD-lite thermal field model — 2D temperature heatmap for DC hall."""
    from utils.dc_advanced_design import thermal_field_model
    return thermal_field_model(rack_count, rack_kw, rows, cooling_type,
                                crac_count, containment, supply_temp_c)


# ═══════════════════════════════════════════════════════════════════════════════
#  G99/G100 COMPLIANCE AUTOMATION
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/compliance/g99")
async def api_g99_application(
    lat: float = Query(...), lon: float = Query(...),
    capacity_mw: float = Query(5), technology: str = Query("solar"),
    voltage_kv: float = Query(33), dno: str = Query(None),
):
    """Generate G99/G100 compliance application data with protection settings."""
    from utils.g99_compliance import generate_g99_application
    return generate_g99_application(lat, lon, capacity_mw, technology, voltage_kv, dno)


@router.get("/api/compliance/g99-check")
async def api_g99_check(
    capacity_mw: float = Query(5), voltage_kv: float = Query(33),
    technology: str = Query("solar"),
):
    """Check which G99 category applies and what's required."""
    from utils.g99_compliance import check_g99_compliance
    return check_g99_compliance(capacity_mw, voltage_kv, technology)


@router.get("/api/compliance/g99-protection")
async def api_g99_protection(
    capacity_mw: float = Query(5), voltage_kv: float = Query(33),
    technology: str = Query("solar"),
):
    """Get required protection relay settings per G99."""
    from utils.g99_compliance import g99_protection_settings
    return g99_protection_settings(capacity_mw, voltage_kv, technology)


@router.get("/api/grid/g99-brief/{project_id}")
async def api_grid_g99_brief(
    project_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Assemble a G99 application brief for a project.

    Returns structured form_context (ready to feed into a form mapper),
    a human-readable markdown draft, and a provenance block.
    Always returns 200 — upstream data gaps are surfaced via
    provenance=synthetic_fallback + reason rather than HTTP errors.
    """
    from utils.g99_brief import build_g99_brief
    async with pool.acquire() as conn:
        return await build_g99_brief(conn, project_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/export/site-report")
async def api_export_site_report(
    lat: float = Query(...), lon: float = Query(...),
    capacity_mw: float = Query(5), technology: str = Query("solar"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Generate branded HTML site report."""
    from utils.export_engine import generate_site_report_html
    # Gather data from existing endpoints
    async with pool.acquire() as conn:
        grid = await gc_assess(conn, lat=lat, lon=lon, capacity_mw=capacity_mw, technology=technology)
    site_data = {
        "lat": lat, "lon": lon, "capacity_mw": capacity_mw, "technology": technology,
        "grid": grid,
    }
    html = generate_site_report_html(site_data)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


@router.post("/api/export/csv")
async def api_export_csv(sites: list = []):
    """Export sites comparison as CSV."""
    from utils.export_engine import generate_csv_export
    csv_str = generate_csv_export(sites)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=csv_str, media_type="text/csv",
                              headers={"Content-Disposition": "attachment; filename=princeps-export.csv"})


# ═══════════════════════════════════════════════════════════════════════════════
#  USAGE TRACKING
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/usage/check")
async def api_usage_check(user_id: str = Query("default"), tier: str = Query("free")):
    """Check usage quota for current user/tier."""
    from utils.usage_tracker import check_quota
    return check_quota(user_id, tier)


@router.post("/api/usage/record")
async def api_usage_record(user_id: str = Query("default"), endpoint: str = Query("assessment"), tier: str = Query("free")):
    """Record an API usage event."""
    from utils.usage_tracker import record_usage
    record_usage(user_id, endpoint, tier)
    return {"recorded": True}


@router.get("/api/usage/summary")
async def api_usage_summary(user_id: str = Query("default")):
    """Get monthly usage breakdown."""
    from utils.usage_tracker import get_usage_summary
    return get_usage_summary(user_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  COMPETITIVE INTELLIGENCE INTEGRATIONS (LandGate/Searchland/PVcase/Transect-class)
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/planning/extract")
async def api_planning_extract(
    text: str = Query(None, description="Raw planning decision text"),
    file_path: str = Query(None, description="Path to PDF file"),
):
    """Extract structured data from UK planning application documents using NLP."""
    from utils.planning_nlp import extract_planning_decision, extract_from_pdf
    if file_path:
        return extract_from_pdf(file_path)
    if text:
        return extract_planning_decision(text)
    raise HTTPException(400, "Provide text or file_path")


@router.post("/api/planning/classify")
async def api_planning_classify(text: str = Query(...)):
    """Classify a document as planning_decision, connection_offer, etc."""
    from utils.planning_nlp import classify_document
    return {"document_type": classify_document(text)}


@router.get("/api/landowner/lookup")
async def api_landowner_lookup(
    lat: float = Query(...), lon: float = Query(...),
):
    """Identify landowner from HMLR + Companies House public records."""
    from utils.landowner_lookup import lookup_landowner
    return await lookup_landowner(lat, lon)


@router.get("/api/landowner/transactions")
async def api_landowner_transactions(
    lat: float = Query(...), lon: float = Query(...),
    radius_km: float = Query(2.0),
):
    """Recent land transactions near a location from HMLR Price Paid data."""
    from utils.landowner_lookup import nearby_land_transactions
    return await nearby_land_transactions(lat, lon, radius_km)


@router.get("/api/landowner/company")
async def api_landowner_company(name: str = Query(...)):
    """Search Companies House for a corporate landowner."""
    from utils.landowner_lookup import search_companies_house
    return await search_companies_house(name)


@router.get("/api/landowner/land-value")
async def api_landowner_land_value(
    lat: float = Query(...), lon: float = Query(...),
    area_ha: float = Query(5.0),
    land_type: str = Query("agricultural"),
):
    """Estimate land value based on nearby transactions and type benchmarks."""
    from utils.landowner_lookup import estimate_land_value
    return await estimate_land_value(lat, lon, area_ha, land_type)


@router.get("/api/pricing/regional")
async def api_pricing_regional():
    """Current Agile electricity prices for all 14 UK DNO regions as GeoJSON."""
    from utils.wholesale_price_heatmap import price_heatmap_geojson
    return await price_heatmap_geojson()


@router.get("/api/pricing/timeseries")
async def api_pricing_timeseries(
    region: str = Query("C"),
    hours: int = Query(48, ge=1, le=168),
):
    """Historical half-hourly wholesale prices for a region."""
    from utils.wholesale_price_heatmap import fetch_price_timeseries
    return await fetch_price_timeseries(region, hours)


@router.get("/api/pricing/dispatch-window")
async def api_pricing_dispatch_window(
    hours_ahead: int = Query(24, ge=1, le=168),
):
    """Find cheapest and most expensive time windows for BESS dispatch."""
    from utils.wholesale_price_heatmap import optimal_dispatch_window
    return await optimal_dispatch_window(hours_ahead)


@router.post("/api/esa/auto-scope")
async def api_esa_auto_scope(
    lat: float = Query(...), lon: float = Query(...),
    site_area_ha: float = Query(5.0),
    proposed_use: str = Query("solar_farm"),
):
    """Auto-generate Phase 1 ESA scope from Princeps constraint data."""
    from utils.esa_auto_scoping import auto_scope_phase1
    return await auto_scope_phase1(lat, lon, site_area_ha, proposed_use)


@router.post("/api/esa/contamination")
async def api_esa_contamination(
    lat: float = Query(...), lon: float = Query(...),
):
    """Historical land use contamination risk assessment."""
    from utils.esa_auto_scoping import contamination_risk
    return await contamination_risk(lat, lon)


@router.post("/api/esa/flood-risk")
async def api_esa_flood_risk(
    lat: float = Query(...), lon: float = Query(...),
):
    """EA flood zone check with climate projections."""
    from utils.esa_auto_scoping import flood_risk_assessment
    return await flood_risk_assessment(lat, lon)


# ═══════════════════════════════════════════════════════════════════════════════
#  GEMINI 3D ASSET MODELLER
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/grid/asset-types")
async def api_asset_types():
    """List available 3D asset types for the Gemini modeller."""
    from utils.gemini_asset_modeller import list_asset_types
    return list_asset_types()


@router.post("/api/grid/asset-model")
async def api_asset_model(
    asset_type: str = Query("data_centre"),
    capacity_mw: float = Query(None),
    prompt: str = Query(None),
):
    """
    Generate a 3D asset model spec using Gemini AI.

    Returns component dimensions, materials, positions, construction protocol,
    and cost estimates. Can be rendered as Three.js geometry on the map.
    """
    from utils.gemini_asset_modeller import generate_asset_spec
    return await generate_asset_spec(asset_type, capacity_mw, prompt)


# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTRAINT COST OVERLAY + QUEUE DEPTH (Phase 7)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/grid/constraints")
async def api_grid_constraints(
    hours_ahead: int = Query(48, ge=1, le=168),
    hour_offset: int = Query(None, ge=0, le=167),
):
    """
    Grid constraint forecast as GeoJSON — colored boundary zones showing
    congestion risk, loading, and constraint cost per MWh.

    Includes per-boundary timeseries for time-slider scrubbing.
    Pass hour_offset to get data for a specific forecast hour.
    """
    from utils.constraint_forecaster import constraints_to_geojson
    return constraints_to_geojson(hours_ahead=hours_ahead, hour_offset=hour_offset)


@router.get("/api/grid/queue-depth")
async def api_grid_queue_depth(
    substation_id: int = Query(None, description="Substation to analyse. Omit for map-wide GeoJSON."),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Per-substation queue depth.

    If substation_id is supplied, returns a single detailed queue-depth
    object (MW in queue, ahead-in-queue count, earliest viable year, and
    a provenance block). Data comes from grid_ecr, then eso_tec_register,
    then a live NESO CKAN call — in that order. Never raises; falls back
    to provenance=synthetic_fallback with a reason if every source fails.

    Without substation_id, returns the legacy map-wide GeoJSON so existing
    callers keep working.
    """
    if substation_id is not None:
        from utils.queue_depth import queue_depth_for_substation
        async with pool.acquire() as conn:
            return await queue_depth_for_substation(conn, substation_id)

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                s.id,
                s.name,
                s.dno,
                s.voltage_kv,
                ST_X(ST_Transform(s.geom, 4326)) AS lon,
                ST_Y(ST_Transform(s.geom, 4326)) AS lat,
                s.demand_headroom_mw,
                s.gen_headroom_mw,
                COUNT(e.id) AS queue_count,
                COALESCE(SUM(e.capacity_mw), 0) AS queued_mw,
                COUNT(e.id) FILTER (WHERE e.status ILIKE '%%accepted%%'
                    OR e.status ILIKE '%%connect%%') AS connected_count,
                COALESCE(SUM(e.capacity_mw) FILTER (WHERE e.status ILIKE '%%accepted%%'
                    OR e.status ILIKE '%%connect%%'), 0) AS connected_mw
            FROM grid_substations s
            LEFT JOIN grid_ecr e ON e.substation_id = s.id
            WHERE s.geom IS NOT NULL
            GROUP BY s.id
            HAVING COUNT(e.id) > 0
            ORDER BY COUNT(e.id) DESC
            LIMIT 500
        """)

    features = []
    for r in rows:
        queue_count = r["queue_count"]
        queued_mw = float(r["queued_mw"] or 0)
        connected_mw = float(r["connected_mw"] or 0)
        headroom = float(r["gen_headroom_mw"] or 0)

        # Estimate wait time: UK average ~3-5 years for >10MW, 1-2 years for <5MW
        # Scale by queue depth and headroom ratio
        if headroom > 0 and queued_mw > 0:
            congestion_ratio = queued_mw / max(headroom, 1)
            wait_months = min(84, int(12 + congestion_ratio * 18))
        else:
            wait_months = 36 if queue_count > 5 else 18

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]},
            "properties": {
                "id": r["id"],
                "name": r["name"],
                "dno": r["dno"],
                "voltage_kv": r["voltage_kv"],
                "queue_count": queue_count,
                "queued_mw": round(queued_mw, 1),
                "connected_count": r["connected_count"],
                "connected_mw": round(connected_mw, 1),
                "headroom_mw": round(headroom, 1),
                "estimated_wait_months": wait_months,
                "queue_pressure": "HIGH" if queue_count > 10 or queued_mw > headroom * 2
                                  else "MEDIUM" if queue_count > 5 or queued_mw > headroom
                                  else "LOW",
            },
        })

    return {"type": "FeatureCollection", "features": features}


@router.get("/api/grid/live-status")
async def api_grid_live_status():
    """
    Compact live grid status for the status strip — generation mix,
    carbon intensity, frequency, wholesale price.
    Designed for 30s polling from the frontend.
    """
    data = await fetch_all_live()
    gen = data.get("generation", {})
    carbon = data.get("carbon") or {}
    ics = data.get("interconnectors", {})

    total_gen = gen.get("total_generation_mw", 0)
    wind_mw = gen.get("wind", 0)
    solar_mw = gen.get("solar", 0)
    nuclear_mw = gen.get("nuclear", 0)
    gas_mw = gen.get("gas", 0)
    renewable_mw = wind_mw + solar_mw + gen.get("hydro", 0) + gen.get("biomass", 0)
    net_imports = sum(ics.values())

    return {
        "total_generation_mw": total_gen,
        "wind_mw": wind_mw,
        "solar_mw": solar_mw,
        "nuclear_mw": nuclear_mw,
        "gas_mw": gas_mw,
        "renewable_pct": round(renewable_mw / max(total_gen, 1) * 100, 1),
        "carbon_intensity": carbon.get("intensity_gco2"),
        "carbon_index": carbon.get("index"),
        "frequency_hz": data.get("frequency_hz"),
        "price_gbp_mwh": data.get("sell_price_gbp_mwh"),
        "net_imports_mw": net_imports,
        "timestamp": data.get("timestamp"),
    }


@router.get("/api/energy/assumptions")
async def api_energy_assumptions():
    """UK energy system assumptions — CB7/BEIS/FES sourced reference data."""
    from utils.uk_energy_assumptions import (
        RENEWABLES, BESS, NUCLEAR, GAS_CCS, INTERCONNECTORS,
        GRID_CONNECTION_COSTS_GBP_KM, FINANCIAL_DEFAULTS,
        AVERAGE_LCOE_GBP_MWH, AVERAGE_CAPACITY_FACTOR,
        CB7_ENERGY_DEMAND_2050_TWH, TRANSMISSION_LOSSES,
    )
    return {
        "renewables": RENEWABLES,
        "bess": BESS,
        "nuclear": NUCLEAR,
        "gas_ccs": GAS_CCS,
        "interconnectors": INTERCONNECTORS,
        "grid_connection_costs_gbp_km": GRID_CONNECTION_COSTS_GBP_KM,
        "financial_defaults": FINANCIAL_DEFAULTS,
        "average_lcoe_gbp_mwh": AVERAGE_LCOE_GBP_MWH,
        "average_capacity_factor": AVERAGE_CAPACITY_FACTOR,
        "cb7_demand_2050_twh": CB7_ENERGY_DEMAND_2050_TWH,
        "transmission_losses": TRANSMISSION_LOSSES,
    }


@router.get("/api/energy/npv")
async def api_energy_npv(
    capacity_mw: float = Query(50, ge=0.1),
    technology: str = Query("solar"),
    ppa_price: float = Query(None),
    lifetime: int = Query(None),
):
    """Quick NPV/IRR/LCOE calculation for a project using CB7 assumptions."""
    from utils.uk_energy_assumptions import project_npv
    return project_npv(capacity_mw, technology, ppa_price, lifetime)


@router.get("/api/energy/compare")
async def api_energy_compare(
    capacity_mw: float = Query(50, ge=0.1),
):
    """Compare all technologies at a given capacity."""
    from utils.uk_energy_assumptions import technology_comparison
    return technology_comparison(capacity_mw)


# ═══════════════════════════════════════════════════════════════════════════════
#  3D GRID DIGITAL TWIN — WebSocket + REST (Phase 6)
# ═══════════════════════════════════════════════════════════════════════════════

# Connected WebSocket clients for grid twin live updates
_grid_twin_clients: set[WebSocket] = set()


@router.get("/api/grid-twin/state")
async def api_grid_twin_state(
    pool: asyncpg.Pool = Depends(get_pool),
    limit: int = Query(80, le=200),
):
    """
    Full grid state snapshot for 3D digital twin.
    Pulls real substations from PostGIS and scales demand using live BMRS data.
    Falls back to simulated diurnal dynamics if live API is unavailable.
    """
    from utils.live_grid_status import get_live_status

    now = datetime.now()
    hour = now.hour + now.minute / 60.0
    day_of_year = now.timetuple().tm_yday

    # ── Fetch real-time grid status from BMRS + Carbon Intensity ─────────
    live: dict = {}
    try:
        live = await get_live_status()
    except Exception:
        pass  # fall back to simulated

    real_demand_gw = live.get("demand_gw")  # GW from BMRS
    real_demand_mw = real_demand_gw * 1000 if real_demand_gw else None
    gen_mix = live.get("generation_mix", {})
    wind_pct = gen_mix.get("wind_pct", 0) / 100 if gen_mix else 0
    solar_pct = gen_mix.get("solar_pct", 0) / 100 if gen_mix else 0
    renewable_pct = wind_pct + solar_pct

    # Simulated diurnal/seasonal (used as fallback if live data unavailable)
    morning = math.exp(-0.5 * ((hour - 8.5) / 1.8) ** 2) * 0.85
    evening = math.exp(-0.5 * ((hour - 17.5) / 2.0) ** 2) * 1.0
    night = 0.35 + 0.15 * math.cos(2 * math.pi * (hour - 3) / 24)
    diurnal = max(night, morning, evening)
    seasonal = 0.7 + 0.3 * math.cos(2 * math.pi * (day_of_year - 15) / 365)

    # ── Pull real substations from PostGIS ───────────────────────────────
    substations = []
    try:
        rows = await pool.fetch("""
            SELECT id, name, dno, voltage_kv,
                   demand_mw, generation_mw,
                   demand_headroom_mw, gen_headroom_mw,
                   transformer_rating_mva, rag_demand, rag_generation,
                   ST_Y(ST_Transform(geom, 4326)) AS lat,
                   ST_X(ST_Transform(geom, 4326)) AS lon
            FROM grid_substations
            WHERE voltage_kv >= 33 AND geom IS NOT NULL
            ORDER BY voltage_kv DESC, demand_mw DESC NULLS LAST
            LIMIT $1
        """, limit)

        # ── ECR queue data from grid_ecr ─────────────────────────────────
        ecr_map: dict[int, dict] = {}
        try:
            ecr_rows = await pool.fetch("""
                SELECT substation_id, COUNT(*) AS ecr_count,
                       COALESCE(SUM(capacity_mw), 0) AS ecr_mw
                FROM grid_ecr
                WHERE substation_id IS NOT NULL
                GROUP BY substation_id
            """)
            for er in ecr_rows:
                ecr_map[er["substation_id"]] = {
                    "ecr_queued": int(er["ecr_count"]),
                    "ecr_mw": round(float(er["ecr_mw"]), 1),
                }
        except Exception:
            pass  # ECR enrichment is non-critical

        # Sum of DB-stored demand for proportional scaling
        total_db_demand = sum(
            float(r["demand_mw"] or (float(r["transformer_rating_mva"] or r["demand_headroom_mw"] or 100) * 0.5))
            for r in rows
        )

        for r in rows:
            capacity = float(r["transformer_rating_mva"] or r["demand_headroom_mw"] or 100)
            base_demand = float(r["demand_mw"] or capacity * 0.5)
            base_gen = float(r["generation_mw"] or 0)
            sub_id = r["id"]

            # ── Demand: scale by real national demand or fall back to simulated ──
            if real_demand_mw and total_db_demand > 0:
                scale = real_demand_mw / total_db_demand
                # Cap scale factor to avoid inflated utilisation when DB coverage is sparse
                scale = min(scale, 1.2)
                live_demand = round(base_demand * scale * diurnal, 1)
            else:
                live_demand = round(base_demand * diurnal * seasonal * (1 + random.gauss(0, 0.04)), 1)
            # Ensure demand never exceeds capacity by more than 10% (data integrity guard)
            live_demand = min(live_demand, capacity * 1.1)

            # ── Generation: use real wind+solar mix or fall back to solar-only ──
            if gen_mix and renewable_pct > 0:
                # Distribute national renewable gen proportionally to each sub's capacity
                # Wind: spread more evenly; Solar: weight by daytime factor
                solar_factor = max(0, math.sin(math.pi * max(0, min(1, (hour - 6) / 12))))
                wind_gen = capacity * 0.10 * wind_pct * (1 + random.gauss(0, 0.03))
                solar_gen = capacity * 0.10 * solar_pct * solar_factor * (1 + random.gauss(0, 0.03))
                live_gen = round(max(base_gen, wind_gen + solar_gen), 1)
            else:
                solar_factor = max(0, math.sin(math.pi * max(0, min(1, (hour - 6) / 12))))
                solar_season = max(0.1, math.sin(math.pi * (day_of_year - 80) / 365))
                live_gen = round(max(base_gen, capacity * 0.08) * solar_factor * solar_season * (1 + random.gauss(0, 0.05)), 1)

            # ── ECR enrichment ───────────────────────────────────────────
            ecr_info = ecr_map.get(sub_id, {})

            substations.append({
                "id": str(sub_id),
                "name": r["name"] or f"Sub-{sub_id}",
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "voltage_kv": float(r["voltage_kv"]),
                "capacity_mw": round(capacity, 1),
                "type": "GSP" if float(r["voltage_kv"]) >= 275 else "BSP" if float(r["voltage_kv"]) >= 132 else "Primary",
                "dno": r["dno"],
                "demand_mw": live_demand,
                "generation_mw": live_gen,
                "net_demand_mw": round(live_demand - live_gen, 1),
                "utilisation": round(live_demand / max(capacity, 1), 3),
                "headroom_mw": round(capacity - live_demand, 1),
                "rag_demand": r["rag_demand"],
                "rag_generation": r["rag_generation"],
                "ecr_queued": ecr_info.get("ecr_queued", 0),
                "ecr_mw": ecr_info.get("ecr_mw", 0.0),
            })
    except Exception as e:
        # Fallback to synthetic if DB unavailable
        substations = _fallback_substations(diurnal, seasonal, hour, day_of_year)

    # ── Supplement with nationwide substations for areas not covered by DB ──
    db_lats = [s["lat"] for s in substations]
    db_coverage = {
        "has_london": any(51.3 < lat < 51.7 for lat in db_lats) and any(-0.3 < s["lon"] < 0.2 for s in substations),
        "has_scotland": any(lat > 55.0 for lat in db_lats),
        "has_ne_england": any(54.0 < lat < 56.0 for lat in db_lats) and any(-2.0 < s["lon"] < 0.0 for s in substations),
        "has_east_anglia": any(52.0 < lat < 53.0 for lat in db_lats) and any(s["lon"] > 0.5 for s in substations),
        "has_south_east": any(50.5 < lat < 51.5 for lat in db_lats) and any(-1.5 < s["lon"] < 1.5 for s in substations),
        "has_south_west": any(50.0 < lat < 51.0 for lat in db_lats) and any(s["lon"] < -3.0 for s in substations),
    }
    _nationwide = [
        # London / SE
        {"id": "BARK", "name": "Barking", "lat": 51.53, "lon": 0.08, "voltage_kv": 275, "capacity_mw": 720, "type": "GSP", "dno": "UKPN"},
        {"id": "BEDD", "name": "Beddington", "lat": 51.37, "lon": -0.14, "voltage_kv": 275, "capacity_mw": 500, "type": "GSP", "dno": "UKPN"},
        {"id": "WHAM", "name": "West Ham", "lat": 51.53, "lon": -0.01, "voltage_kv": 275, "capacity_mw": 550, "type": "GSP", "dno": "UKPN"},
        {"id": "CITY", "name": "City Road", "lat": 51.53, "lon": -0.09, "voltage_kv": 132, "capacity_mw": 400, "type": "BSP", "dno": "UKPN"},
        {"id": "WIMB", "name": "Wimbledon", "lat": 51.42, "lon": -0.21, "voltage_kv": 132, "capacity_mw": 320, "type": "BSP", "dno": "UKPN"},
        {"id": "KEME", "name": "Kemsley", "lat": 51.36, "lon": 0.74, "voltage_kv": 275, "capacity_mw": 460, "type": "GSP", "dno": "UKPN"},
        {"id": "SELL", "name": "Sellindge", "lat": 51.10, "lon": 1.03, "voltage_kv": 400, "capacity_mw": 800, "type": "GSP", "dno": "UKPN"},
        {"id": "BRAM", "name": "Bramley", "lat": 51.33, "lon": -1.06, "voltage_kv": 400, "capacity_mw": 640, "type": "GSP", "dno": "SSEN"},
        {"id": "LODR", "name": "Lovedean", "lat": 50.95, "lon": -1.07, "voltage_kv": 400, "capacity_mw": 600, "type": "GSP", "dno": "SSEN"},
        {"id": "FAWL", "name": "Fawley", "lat": 50.82, "lon": -1.33, "voltage_kv": 400, "capacity_mw": 500, "type": "GSP", "dno": "SSEN"},
        {"id": "BOLN", "name": "Bolney", "lat": 51.00, "lon": -0.20, "voltage_kv": 400, "capacity_mw": 550, "type": "GSP", "dno": "UKPN"},
        # Scotland
        {"id": "EDIN", "name": "Edinburgh South", "lat": 55.92, "lon": -3.19, "voltage_kv": 275, "capacity_mw": 420, "type": "GSP", "dno": "SPEN"},
        {"id": "COCK", "name": "Cockenzie", "lat": 55.97, "lon": -2.97, "voltage_kv": 275, "capacity_mw": 380, "type": "GSP", "dno": "SPEN"},
        {"id": "GLAS", "name": "Glasgow South", "lat": 55.83, "lon": -4.28, "voltage_kv": 275, "capacity_mw": 450, "type": "GSP", "dno": "SPEN"},
        {"id": "HUNB", "name": "Hunterston B", "lat": 55.72, "lon": -4.89, "voltage_kv": 400, "capacity_mw": 600, "type": "GSP", "dno": "SPEN"},
        {"id": "KEIT", "name": "Keith", "lat": 57.55, "lon": -2.95, "voltage_kv": 275, "capacity_mw": 320, "type": "GSP", "dno": "SSEN"},
        {"id": "BEAU", "name": "Beauly", "lat": 57.47, "lon": -4.47, "voltage_kv": 275, "capacity_mw": 350, "type": "GSP", "dno": "SSEN"},
        {"id": "DUNO", "name": "Dounreay", "lat": 58.58, "lon": -3.74, "voltage_kv": 275, "capacity_mw": 250, "type": "GSP", "dno": "SSEN"},
        {"id": "PERT", "name": "Perth", "lat": 56.40, "lon": -3.44, "voltage_kv": 132, "capacity_mw": 200, "type": "BSP", "dno": "SSEN"},
        # North East / Yorkshire
        {"id": "KEAD", "name": "Keadby", "lat": 53.60, "lon": -0.75, "voltage_kv": 400, "capacity_mw": 500, "type": "GSP", "dno": "NPG"},
        {"id": "DRAX", "name": "Drax", "lat": 53.74, "lon": -0.99, "voltage_kv": 400, "capacity_mw": 900, "type": "GSP", "dno": "NPG"},
        {"id": "THON", "name": "Thornton", "lat": 53.89, "lon": -0.11, "voltage_kv": 275, "capacity_mw": 380, "type": "GSP", "dno": "NPG"},
        {"id": "LEED", "name": "Leeds South", "lat": 53.78, "lon": -1.56, "voltage_kv": 275, "capacity_mw": 400, "type": "GSP", "dno": "NPG"},
        {"id": "NEWC", "name": "Newcastle Benton", "lat": 55.01, "lon": -1.58, "voltage_kv": 275, "capacity_mw": 360, "type": "GSP", "dno": "NPG"},
        {"id": "HART", "name": "Hartlepool", "lat": 54.68, "lon": -1.20, "voltage_kv": 275, "capacity_mw": 340, "type": "GSP", "dno": "NPG"},
        {"id": "STEW", "name": "Stella West", "lat": 54.96, "lon": -1.71, "voltage_kv": 275, "capacity_mw": 380, "type": "GSP", "dno": "NPG"},
        # East Anglia
        {"id": "NORW", "name": "Norwich Main", "lat": 52.62, "lon": 1.30, "voltage_kv": 275, "capacity_mw": 280, "type": "GSP", "dno": "UKPN"},
        {"id": "SIZW", "name": "Sizewell", "lat": 52.21, "lon": 1.62, "voltage_kv": 400, "capacity_mw": 700, "type": "GSP", "dno": "UKPN"},
        {"id": "BRAI", "name": "Braintree", "lat": 51.88, "lon": 0.55, "voltage_kv": 132, "capacity_mw": 200, "type": "BSP", "dno": "UKPN"},
        {"id": "CAMA", "name": "Cambridge", "lat": 52.19, "lon": 0.14, "voltage_kv": 132, "capacity_mw": 250, "type": "BSP", "dno": "UKPN"},
        {"id": "IPWC", "name": "Ipswich", "lat": 52.06, "lon": 1.15, "voltage_kv": 132, "capacity_mw": 220, "type": "BSP", "dno": "UKPN"},
        # South West
        {"id": "EXET", "name": "Exeter Main", "lat": 50.72, "lon": -3.53, "voltage_kv": 132, "capacity_mw": 200, "type": "BSP", "dno": "NGED"},
        {"id": "HINK", "name": "Hinkley Point", "lat": 51.21, "lon": -3.13, "voltage_kv": 400, "capacity_mw": 900, "type": "GSP", "dno": "NGED"},
        {"id": "LAND", "name": "Landulph", "lat": 50.44, "lon": -4.23, "voltage_kv": 132, "capacity_mw": 180, "type": "BSP", "dno": "NGED"},
        {"id": "INDN", "name": "Indian Queens", "lat": 50.39, "lon": -4.92, "voltage_kv": 132, "capacity_mw": 160, "type": "BSP", "dno": "NGED"},
        # East Midlands
        {"id": "RATT", "name": "Ratcliffe-on-Soar", "lat": 52.87, "lon": -1.26, "voltage_kv": 400, "capacity_mw": 700, "type": "GSP", "dno": "NGED"},
        {"id": "NOTT", "name": "Nottingham East", "lat": 52.95, "lon": -1.12, "voltage_kv": 132, "capacity_mw": 280, "type": "BSP", "dno": "NGED"},
        {"id": "LEIC", "name": "Leicester East", "lat": 52.63, "lon": -1.08, "voltage_kv": 132, "capacity_mw": 260, "type": "BSP", "dno": "NGED"},
    ]
    # Only add nationwide subs that are >20km from any existing DB substation
    for ns in _nationwide:
        too_close = False
        for s in substations:
            dlat = abs(s["lat"] - ns["lat"])
            dlon = abs(s["lon"] - ns["lon"])
            if dlat < 0.15 and dlon < 0.15:
                too_close = True
                break
        if not too_close:
            base = ns["capacity_mw"] * 0.55 * diurnal * seasonal
            ns["demand_mw"] = round(min(base * (1 + random.gauss(0, 0.04)), ns["capacity_mw"] * 1.1), 1)
            sf = max(0, math.sin(math.pi * max(0, min(1, (hour - 6) / 12))))
            ss = max(0.1, math.sin(math.pi * (day_of_year - 80) / 365))
            ns["generation_mw"] = round(ns["capacity_mw"] * 0.12 * sf * ss * (1 + random.gauss(0, 0.05)), 1)
            ns["net_demand_mw"] = round(ns["demand_mw"] - ns["generation_mw"], 1)
            ns["utilisation"] = round(ns["demand_mw"] / ns["capacity_mw"], 3)
            ns["headroom_mw"] = round(ns["capacity_mw"] - ns["demand_mw"], 1)
            ns["rag_demand"] = "green" if ns["utilisation"] < 0.6 else "amber" if ns["utilisation"] < 0.8 else "red"
            ns["rag_generation"] = "green"
            ns["ecr_queued"] = 0
            ns["ecr_mw"] = 0.0
            substations.append(ns)

    # Build lines by connecting nearby substations at same/adjacent voltage tiers
    lines = _build_twin_lines(substations)

    # System metrics — prefer real data, fall back to computed totals
    total_demand = sum(s["demand_mw"] for s in substations)
    total_gen = sum(s["generation_mw"] for s in substations)
    total_capacity = sum(s["capacity_mw"] for s in substations)

    return {
        "timestamp": now.isoformat() + "Z",
        "substations": substations,
        "lines": lines,
        "system": {
            "total_demand_mw": round(total_demand, 1),
            "total_generation_mw": round(total_gen, 1),
            "total_capacity_mw": round(total_capacity, 1),
            "system_utilisation": round(total_demand / max(total_capacity, 1), 3),
            "frequency_hz": live.get("frequency_hz") or round(50.0 + random.gauss(0, 0.02), 3),
            "carbon_intensity": live.get("carbon_intensity_gco2_kwh"),
            "carbon_index": live.get("carbon_index"),
            "generation_mix": gen_mix,
            "hour": round(hour, 1),
            "day_of_year": day_of_year,
            "live_data": real_demand_mw is not None,
        },
    }


def _build_twin_lines(substations: list[dict]) -> list[dict]:
    """Build transmission lines by connecting nearby substations."""
    lines = []
    seen = set()
    sub_map = {s["id"]: s for s in substations}

    # Sort by voltage descending so high-voltage links come first
    sorted_subs = sorted(substations, key=lambda s: s["voltage_kv"], reverse=True)

    for i, s in enumerate(sorted_subs):
        # Connect to nearest 3 substations at same or adjacent voltage tier
        candidates = []
        for j, t in enumerate(sorted_subs):
            if i == j:
                continue
            # Only connect within 2 voltage tiers
            v_ratio = max(s["voltage_kv"], t["voltage_kv"]) / max(min(s["voltage_kv"], t["voltage_kv"]), 1)
            if v_ratio > 4:
                continue
            dist = math.hypot(s["lat"] - t["lat"], s["lon"] - t["lon"])
            candidates.append((dist, j, t))

        candidates.sort()
        for dist, j, t in candidates[:2]:  # max 2 connections per sub
            key = tuple(sorted([s["id"], t["id"]]))
            if key in seen:
                continue
            seen.add(key)

            voltage = min(s["voltage_kv"], t["voltage_kv"])
            rating = {400: 1200, 275: 800, 132: 400, 66: 200, 33: 100}.get(int(voltage), 100)

            demand_diff = t.get("net_demand_mw", 0) - s.get("net_demand_mw", 0)
            flow = round(demand_diff * 0.6 * (1 + random.gauss(0, 0.08)), 1)

            lines.append({
                "from": s["id"],
                "to": t["id"],
                "voltage_kv": voltage,
                "rating_mw": rating,
                "from_coords": [s["lon"], s["lat"]],
                "to_coords": [t["lon"], t["lat"]],
                "flow_mw": flow,
                "loading_pct": round(abs(flow) / max(rating, 1) * 100, 1),
                "congested": abs(flow) / max(rating, 1) > 0.8,
            })

    return lines


def _fallback_substations(diurnal, seasonal, hour, day_of_year):
    """Fallback hardcoded substations if DB is unavailable."""
    fallback = [
        {"id": "BRWA", "name": "Bramley", "lat": 51.33, "lon": -1.06, "voltage_kv": 400, "capacity_mw": 640, "type": "GSP", "dno": "SSEN"},
        {"id": "BEDD", "name": "Beddington", "lat": 51.37, "lon": -0.13, "voltage_kv": 275, "capacity_mw": 500, "type": "GSP", "dno": "UKPN"},
        {"id": "MANN", "name": "Manchester South", "lat": 53.45, "lon": -2.25, "voltage_kv": 400, "capacity_mw": 600, "type": "GSP", "dno": "ENWL"},
        {"id": "EDIN", "name": "Edinburgh South", "lat": 55.92, "lon": -3.19, "voltage_kv": 275, "capacity_mw": 360, "type": "GSP", "dno": "SPEN"},
        {"id": "EXET", "name": "Exeter Main", "lat": 50.72, "lon": -3.53, "voltage_kv": 132, "capacity_mw": 200, "type": "BSP", "dno": "NGED"},
        {"id": "CAMA", "name": "Cambridge", "lat": 52.19, "lon": 0.14, "voltage_kv": 132, "capacity_mw": 250, "type": "BSP", "dno": "UKPN"},
        {"id": "NORW", "name": "Norwich Main", "lat": 52.62, "lon": 1.30, "voltage_kv": 275, "capacity_mw": 280, "type": "GSP", "dno": "UKPN"},
        {"id": "KEAD", "name": "Keadby", "lat": 53.60, "lon": -0.75, "voltage_kv": 275, "capacity_mw": 360, "type": "GSP", "dno": "NPG"},
    ]
    for s in fallback:
        base = s["capacity_mw"] * 0.55 * diurnal * seasonal
        s["demand_mw"] = round(base * (1 + random.gauss(0, 0.04)), 1)
        sf = max(0, math.sin(math.pi * max(0, min(1, (hour - 6) / 12))))
        ss = max(0.1, math.sin(math.pi * (day_of_year - 80) / 365))
        s["generation_mw"] = round(s["capacity_mw"] * 0.12 * sf * ss * (1 + random.gauss(0, 0.05)), 1)
        s["net_demand_mw"] = round(s["demand_mw"] - s["generation_mw"], 1)
        s["utilisation"] = round(s["demand_mw"] / s["capacity_mw"], 3)
        s["headroom_mw"] = round(s["capacity_mw"] - s["demand_mw"], 1)
        s["rag_demand"] = "green" if s["utilisation"] < 0.6 else "amber" if s["utilisation"] < 0.8 else "red"
        s["rag_generation"] = "green"
    return fallback


@router.websocket("/ws/grid-twin")
async def ws_grid_twin(ws: WebSocket, pool: asyncpg.Pool = Depends(get_pool)):
    """
    WebSocket for real-time grid twin state updates.
    Sends grid state snapshot every 5 seconds with real DB data.
    """
    await ws.accept()
    _grid_twin_clients.add(ws)
    try:
        while True:
            state = await api_grid_twin_state(pool=pool)
            await ws.send_json(state)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _grid_twin_clients.discard(ws)


@router.get("/api/grid-twin/scenario/{scenario_name}")
async def api_grid_twin_scenario(
    scenario_name: str,
    year: int = Query(2030),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Apply a NESO FES scenario to the grid state.
    Returns modified substations/lines with projected demand.
    """
    growth_rates = {
        "leading_the_way": 0.035,
        "consumer_transformation": 0.028,
        "system_transformation": 0.022,
        "falling_short": 0.012,
        "baseline": 0.02,
    }
    rate = growth_rates.get(scenario_name, 0.02)
    years = year - 2024

    base = await api_grid_twin_state(pool=pool)
    for s in base["substations"]:
        factor = (1 + rate) ** years
        s["demand_mw"] = round(s["demand_mw"] * factor, 1)
        s["net_demand_mw"] = round(s["net_demand_mw"] * factor, 1)
        s["utilisation"] = round(s["demand_mw"] / s["capacity_mw"], 3)
        s["headroom_mw"] = round(s["capacity_mw"] - s["demand_mw"], 1)

    for line in base["lines"]:
        sub_map = {s["id"]: s for s in base["substations"]}
        src = sub_map.get(line["from"], {})
        dst = sub_map.get(line["to"], {})
        demand_diff = dst.get("net_demand_mw", 0) - src.get("net_demand_mw", 0)
        line["flow_mw"] = round(demand_diff * 0.6, 1)
        line["loading_pct"] = round(abs(line["flow_mw"]) / line["rating_mw"] * 100, 1)
        line["congested"] = line["loading_pct"] > 80

    base["scenario"] = {"name": scenario_name, "year": year, "growth_rate": rate}
    return base


# ─── BEMS Digital Twin WebSocket ──────────────────────────────────────────

import random as _rng
import math as _math

_bems_clients: set[WebSocket] = set()


def _generate_bems_state():
    """Generate simulated BEMS telemetry data."""
    now = datetime.now()
    hour = now.hour + now.minute / 60.0
    # Base load follows daily pattern: low at night, peak mid-afternoon
    base_load = 350 + 150 * _math.sin((hour - 6) * _math.pi / 12) if 6 <= hour <= 22 else 250
    power_kw = base_load + _rng.gauss(0, 15)
    power_factor = 0.92 + _rng.gauss(0, 0.02)

    chillers = []
    for i in range(6):
        running = (i < 4) if hour > 8 else (i < 2)
        if _rng.random() < 0.05:
            running = not running
        chillers.append({
            "id": i + 1,
            "name": f"Chiller {i + 1}",
            "status": "Run" if running else "Stop",
            "load_pct": round(_rng.uniform(60, 95), 1) if running else 0,
            "supply_temp_c": round(6 + _rng.gauss(0, 0.5), 1) if running else None,
            "return_temp_c": round(12 + _rng.gauss(0, 0.8), 1) if running else None,
        })

    transformers = [
        {"id": 1, "name": "TX-01", "load_pct": round(power_kw / 800 * 100 + _rng.gauss(0, 3), 1), "temp_c": round(55 + _rng.gauss(0, 3), 1)},
        {"id": 2, "name": "TX-02", "load_pct": round(power_kw / 1000 * 100 + _rng.gauss(0, 3), 1), "temp_c": round(48 + _rng.gauss(0, 3), 1)},
    ]

    zones = []
    for i, name in enumerate(["Office N", "Office S", "Server", "Lobby", "Meeting", "Lab"]):
        setpoint = 22 if name != "Server" else 18
        zones.append({
            "id": i + 1,
            "name": name,
            "temp_c": round(setpoint + _rng.gauss(0, 1.2), 1),
            "setpoint_c": setpoint,
            "humidity_pct": round(45 + _rng.gauss(0, 5), 1),
        })

    cooling_gj = power_kw * 0.4 * 3.6 / 1000  # rough conversion
    eer = round(3.5 + _rng.gauss(0, 0.3), 2)

    return {
        "timestamp": now.isoformat(),
        "power_kw": round(power_kw, 1),
        "power_factor": round(min(max(power_factor, 0.85), 1.0), 3),
        "energy_today_kwh": round(power_kw * hour, 0),
        "energy_month_kwh": round(power_kw * hour * now.day, 0),
        "energy_year_kwh": round(power_kw * 8 * 365 * 0.7, 0),
        "cooling_today_gj": round(cooling_gj * hour, 1),
        "cooling_month_gj": round(cooling_gj * hour * now.day, 1),
        "cooling_year_gj": round(cooling_gj * 8 * 365 * 0.7, 1),
        "co2_today_kg": round(power_kw * hour * 0.233, 1),
        "eer": eer,
        "chillers": chillers,
        "transformers": transformers,
        "zones": zones,
        "breakers": {
            "main": True,
            "bus_a": True,
            "bus_b": True,
            "dist_1": True,
            "dist_2": True,
            "dist_3": _rng.random() > 0.02,
        },
        "alarms": [
            {"time": (now - timedelta(minutes=_rng.randint(1, 120))).strftime("%H:%M"), "level": "warning", "message": "Chiller 5 low refrigerant pressure"},
            {"time": (now - timedelta(minutes=_rng.randint(120, 360))).strftime("%H:%M"), "level": "info", "message": "TX-01 tap changer adjusted"},
            {"time": (now - timedelta(minutes=_rng.randint(360, 720))).strftime("%H:%M"), "level": "info", "message": "Zone 3 setpoint override"},
        ],
    }


@router.websocket("/ws/bems")
async def ws_bems(ws: WebSocket):
    """WebSocket for real-time BEMS telemetry. Sends state every 2 seconds."""
    await ws.accept()
    _bems_clients.add(ws)
    try:
        while True:
            state = _generate_bems_state()
            await ws.send_json(state)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _bems_clients.discard(ws)


# ─── BESS Facility Digital Twin WebSocket ─────────────────────────────────

_bess_facility_clients: set[WebSocket] = set()


def _generate_bess_facility_state():
    """Generate simulated BESS facility telemetry."""
    now = datetime.now()
    hour = now.hour + now.minute / 60.0

    # Determine system mode based on time of day (simplified dispatch)
    # Charge overnight (00-07), discharge morning peak (07-10),
    # charge midday solar (10-16), discharge evening peak (16-21), idle (21-00)
    if 0 <= hour < 7:
        mode = "charging"
        base_power = -35  # negative = charging
    elif 7 <= hour < 10:
        mode = "discharging"
        base_power = 45
    elif 10 <= hour < 16:
        mode = "charging"
        base_power = -25
    elif 16 <= hour < 21:
        mode = "discharging"
        base_power = 48
    else:
        mode = "idle"
        base_power = 0

    containers = []
    total_power_kw = 0
    total_soc = 0
    for i in range(10):
        soc = 50 + _rng.gauss(0, 15)
        if mode == "charging":
            soc = min(95, soc + hour * 3)
        elif mode == "discharging":
            soc = max(15, soc - (hour - 7) * 4)
        soc = max(5, min(99, soc))

        power_kw = base_power * (100 + _rng.gauss(0, 5)) / 100 if mode != "idle" else _rng.gauss(0, 2)
        temp = 25 + abs(power_kw) * 0.02 + _rng.gauss(0, 1.5)
        voltage = 800 + _rng.gauss(0, 10)
        current = abs(power_kw) / (voltage / 1000) if voltage > 0 else 0

        containers.append({
            "id": f"C-{i+1:02d}",
            "soc_pct": round(soc, 1),
            "power_kw": round(power_kw, 1),
            "temp_c": round(max(18, min(42, temp)), 1),
            "voltage_v": round(voltage, 0),
            "current_a": round(current, 1),
            "cycles": 850 + i * 23 + _rng.randint(0, 10),
            "health_pct": round(96 - i * 0.3 - _rng.random() * 0.5, 1),
            "status": "active" if abs(power_kw) > 1 else "standby",
            "hvac_status": "running" if temp > 28 else "idle",
        })
        total_power_kw += power_kw
        total_soc += soc

    avg_soc = total_soc / 10
    efficiency = 0.87 + _rng.gauss(0, 0.02)

    inverters = []
    for i in range(5):
        inv_power = total_power_kw / 5 + _rng.gauss(0, 5)
        inverters.append({
            "id": f"INV-{i+1:02d}",
            "power_kw": round(inv_power, 1),
            "status": "active" if abs(inv_power) > 5 else "standby",
            "temp_c": round(35 + abs(inv_power) * 0.005 + _rng.gauss(0, 2), 1),
            "efficiency_pct": round(97 + _rng.gauss(0, 0.5), 1),
        })

    transformer = {
        "id": "TX-MAIN",
        "load_pct": round(abs(total_power_kw) / 50000 * 100, 1),
        "lv_voltage_kv": 0.8,
        "hv_voltage_kv": 33,
        "temp_c": round(55 + abs(total_power_kw) / 50000 * 20 + _rng.gauss(0, 2), 1),
        "status": "energised",
    }

    grid_point = {
        "export_mw": round(max(0, total_power_kw / 1000), 2),
        "import_mw": round(max(0, -total_power_kw / 1000), 2),
        "voltage_kv": 33,
        "frequency_hz": round(50 + _rng.gauss(0, 0.02), 3),
    }

    # Revenue estimate for today
    hours_elapsed = hour
    avg_power_mw = abs(total_power_kw) / 1000
    revenue_today = round(avg_power_mw * hours_elapsed * 45, 0)  # ~£45/MWh blended

    dispatch_schedule = []
    for h in range(6):
        fh = (now.hour + h) % 24
        if 0 <= fh < 7:
            dispatch_schedule.append({"hour": fh, "action": "charge", "power_mw": -35})
        elif 7 <= fh < 10:
            dispatch_schedule.append({"hour": fh, "action": "discharge", "power_mw": 48})
        elif 10 <= fh < 16:
            dispatch_schedule.append({"hour": fh, "action": "charge", "power_mw": -25})
        elif 16 <= fh < 21:
            dispatch_schedule.append({"hour": fh, "action": "discharge", "power_mw": 50})
        else:
            dispatch_schedule.append({"hour": fh, "action": "idle", "power_mw": 0})

    alarms = []
    for c in containers:
        if c["temp_c"] > 35:
            alarms.append({"time": now.strftime("%H:%M"), "level": "warning",
                          "message": f"{c['id']} temperature high ({c['temp_c']}°C)"})
        if c["soc_pct"] < 10:
            alarms.append({"time": now.strftime("%H:%M"), "level": "critical",
                          "message": f"{c['id']} SoC critically low ({c['soc_pct']}%)"})
    if transformer["temp_c"] > 70:
        alarms.append({"time": now.strftime("%H:%M"), "level": "warning",
                      "message": f"Transformer temperature high ({transformer['temp_c']}°C)"})

    return {
        "timestamp": now.isoformat(),
        "mode": mode,
        "total_power_mw": round(total_power_kw / 1000, 2),
        "avg_soc_pct": round(avg_soc, 1),
        "system_efficiency": round(max(0.8, min(0.98, efficiency)), 3),
        "containers": containers,
        "inverters": inverters,
        "transformer": transformer,
        "grid_point": grid_point,
        "revenue_today_gbp": revenue_today,
        "dispatch_schedule": dispatch_schedule,
        "alarms": alarms[-5:],  # Latest 5
    }


@router.websocket("/ws/bess-facility")
async def ws_bess_facility(ws: WebSocket):
    """WebSocket for BESS facility telemetry. Sends state every 2 seconds."""
    await ws.accept()
    _bess_facility_clients.add(ws)
    try:
        while True:
            state = _generate_bess_facility_state()
            await ws.send_json(state)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _bess_facility_clients.discard(ws)


# ─── Data Centre Digital Twin WebSocket ───────────────────────────────────

_dc_twin_clients: set[WebSocket] = set()


def _generate_dc_twin_state(it_load_kw: float = 10000, rack_count: int = 100, cooling_type: str = "hybrid"):
    """Generate DC telemetry using HPE SustainDC physics model, fallback to synthetic."""
    import subprocess, json as _json, os, random, math, time
    grid_python = os.environ.get("GRID_PYTHON", os.path.join(os.path.dirname(__file__), "..", ".venv-grid", "bin", "python"))
    runner = os.path.join(os.path.dirname(__file__), "..", "utils", "dc_rl_runner.py")

    hour = time.localtime().tm_hour
    load_variation = 1.0 + 0.05 * math.sin(hour * math.pi / 12)
    ambient_temp = 10 + 8 * math.sin((hour - 6) * math.pi / 12)
    it_pct = min(100, max(10, (it_load_kw * load_variation) / (rack_count * 10) * 100))

    try:
        result = subprocess.run(
            [grid_python, runner, "simulate", _json.dumps({
                "it_load_pct": round(it_pct, 1),
                "ambient_temp_c": round(ambient_temp, 1),
                "capacity_mw": it_load_kw / 1000,
                "crac_setpoint_c": 18,
            })],
            capture_output=True, text=True, timeout=5,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        if result.returncode == 0:
            physics = _json.loads(result.stdout)
            racks = []
            for i in range(rack_count):
                racks.append({
                    "id": f"R{i+1:03d}", "row": i // max(rack_count // 4, 1),
                    "load_kw": round(physics["it_power_kw"] / rack_count + random.gauss(0, 0.5), 1),
                    "inlet_temp_c": round(physics["avg_inlet_temp_c"] + random.gauss(0, 0.3), 1),
                    "outlet_temp_c": round(physics["avg_outlet_temp_c"] + random.gauss(0, 0.5), 1),
                    "humidity_pct": round(45 + random.gauss(0, 3), 1),
                    "status": "ok",
                })
            return {
                "metrics": {
                    "it_load_kw": round(physics["it_power_kw"], 1),
                    "cooling_kw": round(physics["hvac"]["total_hvac_kw"], 1),
                    "pue": physics["pue"],
                    "avg_inlet_temp_c": physics["avg_inlet_temp_c"],
                    "utilisation_pct": round(it_pct, 1),
                    "wue": round(physics["water_usage_l_per_15min"] * 4 / max(physics["total_power_kw"], 1), 4),
                    "ambient_temp_c": round(ambient_temp, 1),
                    "chiller_kw": round(physics["hvac"]["chiller_kw"], 1),
                    "crac_fan_kw": round(physics["hvac"]["crac_fan_kw"], 1),
                },
                "racks": racks,
                "anomalies": [],
                "model": "sustaindc_physics",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
    except Exception:
        pass
    # Fallback to synthetic telemetry
    from utils.dc_planner import simulate_telemetry
    return simulate_telemetry(it_load_kw, rack_count, cooling_type)


@router.websocket("/ws/dc-twin")
async def ws_dc_twin(ws: WebSocket):
    """WebSocket for real-time DC telemetry. Sends state every 3 seconds."""
    await ws.accept()
    _dc_twin_clients.add(ws)
    # Parse optional config from first message
    config = {"it_load_kw": 10000, "rack_count": 100, "cooling_type": "hybrid"}
    try:
        # Non-blocking check for initial config
        import asyncio as _aio
        try:
            msg = await _aio.wait_for(ws.receive_json(), timeout=1.0)
            if isinstance(msg, dict):
                config.update(msg)
        except (_aio.TimeoutError, Exception):
            pass

        while True:
            state = _generate_dc_twin_state(**config)
            await ws.send_json(state)
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _dc_twin_clients.discard(ws)


# ══════════════════════════════════════════════════════════
# GridFinder — Unmapped Grid Detection
# ══════════════════════════════════════════════════════════


@router.get("/api/grid/unmapped")
async def detect_unmapped(
    lat: float = Query(52.5),
    lon: float = Query(-1.5),
    radius_km: float = Query(10, ge=1, le=50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Detect potentially unmapped grid infrastructure near a location.

    Uses OSM tower/line gap analysis + optional VIIRS night-time lights
    to identify likely grid routes not in DNO open data.
    Returns GeoJSON of predicted routes.
    """
    from utils.gridfinder_runner import detect_unmapped_grid
    result = await detect_unmapped_grid(pool, lat, lon, radius_km)
    record_metric("gridfinder_detection", 1,
                  labels={"lat": lat, "lon": lon, "radius_km": radius_km})
    return result


# ══════════════════════════════════════════════════════════
# Queue Depth Analysis
# ══════════════════════════════════════════════════════════

@router.get("/api/grid/queue-depth/{substation_id}")
async def queue_depth(substation_id: int, pool: asyncpg.Pool = Depends(get_pool)):
    """
    Queue depth analysis for a single substation — delegates to the
    honest queue_depth module (grid_ecr → eso_tec_register → NESO live →
    synthetic_fallback) with a provenance block. Always 200.
    """
    from utils.queue_depth import queue_depth_for_substation
    async with pool.acquire() as conn:
        return await queue_depth_for_substation(conn, substation_id)


@router.get("/api/grid/queue-summary")
async def queue_summary(
    west: float = None, south: float = None,
    east: float = None, north: float = None,
    limit: int = Query(50, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Queue depth summaries for substations in viewport."""
    from utils.queue_analyser import get_queue_summary
    bbox = (west, south, east, north) if all(v is not None for v in [west, south, east, north]) else None
    return await get_queue_summary(pool, bbox=bbox, limit=limit)


# ══════════════════════════════════════════════════════════
# Revenue Stacking Model
# ══════════════════════════════════════════════════════════

@router.post("/api/grid/revenue-stack")
async def api_revenue_stack(
    capacity_mw: float = Query(50, ge=0.1),
    technology: str = Query("solar+bess"),
    bess_mwh: float = Query(None),
    lat: float = Query(None),
    lon: float = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Multi-market revenue optimisation for BESS + solar + wind.

    Calculates stacked revenue across wholesale (real Agile prices),
    Balancing Mechanism, FFR, Dynamic Containment, Capacity Market,
    and embedded benefits. Includes Monte Carlo P10/P50/P90, LCOE, IRR.
    """
    from utils.revenue_stacker import stack_revenue
    result = await stack_revenue(
        capacity_mw=capacity_mw,
        technology=technology,
        bess_mwh=bess_mwh,
        lat=lat,
        lon=lon,
        pool=pool,
    )
    record_metric("revenue_stack", capacity_mw,
                  labels={"technology": technology, "lat": lat or 0, "lon": lon or 0})
    return result


# ══════════════════════════════════════════════════════════
# DNO Pre-Application Intelligence
# ══════════════════════════════════════════════════════════

@router.get("/api/grid/dno-intelligence")
async def api_dno_intelligence_query(
    dno: str = Query(None),
    lat: float = Query(None),
    lon: float = Query(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    DNO pre-application intelligence — per-DNO analytics.

    Provide either dno code (UKPN, NGED, ENWL, NPG, SPEN, SSEN)
    or lat/lon to auto-detect. Returns acceptance rates, queue depth,
    technology bias, congestion hotspots, and recommended timing.
    """
    if dno is None and lat is None:
        # Return all-DNO summary
        from utils.dno_intelligence import all_dno_summary
        return await all_dno_summary(pool)

    from utils.dno_intelligence import analyse_dno
    return await analyse_dno(pool, dno=dno, lat=lat, lon=lon)


@router.get("/api/grid/dno-intelligence/{dno}")
async def api_dno_intelligence_by_code(
    dno: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    DNO pre-application intelligence for a specific DNO.

    Returns acceptance rates, queue depth, technology bias,
    congestion hotspots, risk factors, similar projects, and timing advice.
    """
    from utils.dno_intelligence import analyse_dno
    result = await analyse_dno(pool, dno=dno)
    record_metric("dno_intelligence", 1, labels={"dno": dno})
    return result


# ══════════════════════════════════════════════════════════
# Time-to-Energisation Estimator
# ══════════════════════════════════════════════════════════

from pydantic import BaseModel as _BaseModel


class _EnergisationRequest(_BaseModel):
    lat: float = 52.5
    lon: float = -1.5
    capacity_mw: float = 50.0
    technology: str = "solar"


@router.post("/api/grid/energisation-timeline")
async def api_energisation_timeline(
    req: _EnergisationRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Predict total months from application to first power export.

    Models 5 phases: pre-application, planning, connection offer,
    connection works, commissioning. Uses real REPD timelines,
    ECR queue depth, and DNO processing benchmarks.
    """
    from utils.energisation_estimator import estimate_energisation_timeline
    result = await estimate_energisation_timeline(
        pool,
        lat=req.lat,
        lon=req.lon,
        capacity_mw=req.capacity_mw,
        technology=req.technology,
    )
    record_metric("energisation_timeline", req.capacity_mw,
                  labels={"technology": req.technology, "lat": req.lat, "lon": req.lon})
    return result


# ══════════════════════════════════════════════════════════
# ML Grid Asset Classifier
# ══════════════════════════════════════════════════════════

@router.post("/api/grid/classify-asset")
async def api_classify_asset(
    voltage_kv: float = Query(33),
    capacity_mw: float = Query(0),
    demand_mw: float = Query(0),
    generation_mw: float = Query(0),
    area_m2: float = Query(5000),
    building_count: int = Query(2),
    panel_area_m2: float = Query(0),
    turbine_count: int = Query(0),
    height_m: float = Query(10),
    transformer_count: int = Query(1),
    container_count: int = Query(0),
    year_commissioned: int = Query(2020),
    latitude: float = Query(52.0),
    longitude: float = Query(-1.0),
    has_chimney: int = Query(0),
):
    """Classify an energy asset from observable features using XGBoost.
    Returns: asset type, confidence, estimated capacity, condition, upgrade priority, SHAP factors."""
    from utils.ml_grid_asset_classifier import classify_asset
    features = {
        "voltage_kv": voltage_kv, "capacity_mw": capacity_mw,
        "demand_mw": demand_mw, "generation_mw": generation_mw,
        "area_m2": area_m2, "building_count": building_count,
        "panel_area_m2": panel_area_m2, "turbine_count": turbine_count,
        "height_m": height_m, "transformer_count": transformer_count,
        "container_count": container_count, "year_commissioned": year_commissioned,
        "latitude": latitude, "longitude": longitude,
        "has_chimney": has_chimney,
    }
    return classify_asset(features)


@router.post("/api/grid/classify-assets-batch")
async def api_classify_assets_batch(assets: list[dict]):
    """Classify multiple grid assets in batch. Returns ranked by upgrade priority."""
    from utils.ml_grid_asset_classifier import classify_batch
    if not assets:
        raise HTTPException(400, "Empty asset list")
    if len(assets) > 200:
        raise HTTPException(400, "Maximum 200 assets per batch")
    return {"assets": classify_batch(assets), "count": len(assets)}


@router.post("/api/grid/identify-area-assets")
async def api_identify_area_assets(
    lat: float = Query(51.5),
    lon: float = Query(-0.1),
    radius_km: float = Query(10),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Identify and classify all grid assets in an area from database.
    Queries substations + REPD generators within radius, classifies each
    with ML, and returns ranked by upgrade priority."""
    from utils.ml_grid_asset_classifier import identify_grid_assets_in_area

    # Fetch substations from DB
    substations = []
    try:
        rows = await pool.fetch("""
            SELECT name, voltage_kv, demand_headroom_mw as headroom_mw,
                   ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon
            FROM grid_substations
            WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, $3)
            LIMIT 50
        """, lon, lat, radius_km * 1000)
        substations = [dict(r) for r in rows]
    except Exception as e:
        log.warning("Substation query failed: %s", e)

    # Fetch REPD generators
    generators = []
    try:
        rows = await pool.fetch("""
            SELECT site_name as name, installed_capacity_mw as capacity_mw,
                   technology, status, ST_Y(geom::geometry) as lat, ST_X(geom::geometry) as lon
            FROM repd_projects
            WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, $3)
            AND status IN ('Operational', 'Under Construction', 'Awaiting Construction')
            LIMIT 100
        """, lon, lat, radius_km * 1000)
        generators = [dict(r) for r in rows]
    except Exception as e:
        log.warning("REPD query failed: %s", e)

    assets = identify_grid_assets_in_area(substations, generators)
    return {
        "assets": assets,
        "count": len(assets),
        "substations_found": len(substations),
        "generators_found": len(generators),
        "search_radius_km": radius_km,
    }


@router.post("/api/grid/train-asset-classifier")
async def api_train_asset_classifier(n_per_type: int = Query(120, ge=50, le=500)):
    """Retrain the grid asset classifier on synthetic data."""
    from utils.ml_grid_asset_classifier import train_all_models
    return train_all_models(n_per_type)


# ══════════════════════════════════════════════════════════
# Environmental Constraint Assessment
# ══════════════════════════════════════════════════════════

@router.get("/api/grid/environmental-constraints")
async def api_environmental_constraints(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    radius_m: float = Query(2000, description="Search radius in metres"),
    include_species: bool = Query(True, description="Include NBN Atlas species check"),
    include_carbon: bool = Query(True, description="Include carbon intensity baseline"),
):
    """Comprehensive environmental constraint assessment using real UK government APIs.

    Queries: Natural England (SSSI, SAC, SPA, AONB, NNR, Ramsar, Ancient Woodland),
    planning.data.gov.uk (Green Belt, conservation areas, listed buildings),
    EA Flood Monitoring, Carbon Intensity API, NBN Atlas species records.

    Returns: CLEAR/CONSTRAINED/BLOCKED verdict with required consultations and legislation."""
    from utils.environmental_constraints import check_all_constraints
    return await check_all_constraints(lat, lon, radius_m=radius_m)


# ══════════════════════════════════════════════════════════
# Grid Connection Optimization (UK Reform 2025-2026)
# ══════════════════════════════════════════════════════════

@router.post("/api/grid/gate-readiness")
async def api_gate_readiness(
    lat: float = Query(...), lon: float = Query(...),
    capacity_mw: float = Query(50), technology: str = Query("solar"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Score project readiness for each gate in the reformed UK connections process."""
    from utils.connection_optimizer import score_gate_readiness
    return await score_gate_readiness(pool, lat, lon, capacity_mw, technology)


@router.post("/api/grid/queue-reform-impact")
async def api_queue_reform_impact(
    lat: float = Query(...), lon: float = Query(...),
    capacity_mw: float = Query(50),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Predict queue position improvement from Ofgem reform (speculative project removal)."""
    from utils.connection_optimizer import model_queue_reform_impact
    return await model_queue_reform_impact(pool, lat, lon, capacity_mw)


@router.post("/api/grid/strategic-alignment")
async def api_strategic_alignment(
    lat: float = Query(...), lon: float = Query(...),
    capacity_mw: float = Query(50), technology: str = Query("solar"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Score alignment with NESO Strategic Spatial Energy Plan priorities."""
    from utils.connection_optimizer import score_strategic_alignment
    return await score_strategic_alignment(pool, lat, lon, capacity_mw, technology)


@router.post("/api/grid/optimize-connection")
async def api_optimize_connection(
    lat: float = Query(...), lon: float = Query(...),
    capacity_mw: float = Query(50), technology: str = Query("solar"),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Recommend optimal connection strategy — substation, voltage, timing, approach."""
    from utils.connection_optimizer import optimize_connection_strategy
    return await optimize_connection_strategy(pool, lat, lon, capacity_mw, technology)


# ══════════════════════════════════════════════════════════
# UK Government Data Ingestion
# ══════════════════════════════════════════════════════════

@router.post("/api/admin/ingest-uk-data")
async def ingest_uk_govt_data(
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Trigger ingestion of all free UK government datasets.

    Pulls: Green Belt, Brownfield Register, National Parks, AONB, SSSI,
    Ancient Woodland, Flood Zones, Conservation Areas, Energy Planning Apps.
    All OGL-licensed, no auth required."""
    from utils.uk_govt_data_ingester import ingest_all
    return await ingest_all(pool)


@router.get("/api/constraints/nearby")
async def constraints_nearby(
    lat: float = Query(...), lon: float = Query(...),
    radius_km: float = Query(5),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Query locally-cached environmental constraints near a point."""
    try:
        rows = await pool.fetch("""
            SELECT constraint_type, name, designation, reference_id,
                   ST_Distance(geometry::geography,
                       ST_SetSRID(ST_Point($1, $2), 4326)::geography) AS distance_m
            FROM environmental_constraints
            WHERE ST_DWithin(geometry::geography,
                ST_SetSRID(ST_Point($1, $2), 4326)::geography, $3)
            ORDER BY distance_m
            LIMIT 50
        """, lon, lat, radius_km * 1000)

        constraints = []
        for r in rows:
            constraints.append({
                "type": r["constraint_type"],
                "name": r["name"],
                "designation": r["designation"],
                "reference": r["reference_id"],
                "distance_m": round(float(r["distance_m"]), 1),
                "inside": float(r["distance_m"]) < 10,
            })

        return {
            "total": len(constraints),
            "constraints": constraints,
            "risk_level": "very_high" if any(c["inside"] and c["type"] in ("sssi", "national_park", "flood_zone_3") for c in constraints)
                else "high" if any(c["inside"] for c in constraints)
                else "medium" if constraints
                else "low",
        }
    except Exception as e:
        return {"total": 0, "constraints": [], "error": str(e)}


# ─── D2 — Split-Connection Suggester ──────────────────────────────────────

from pydantic import BaseModel


class SplitConnectionRequest(BaseModel):
    lat: float
    lon: float
    capacity_mw: float
    max_splits: int = 3


@router.post("/api/grid/split-connection-suggest")
async def split_connection_suggest(
    req: SplitConnectionRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Propose split-connection options across nearest substations when the
    single-connection headroom falls short of the target capacity.

    Returns feasibility-ranked splits with per-substation allocation,
    reinforcement cost (UK cable rates), and queue-time delta vs single.
    """
    from utils.grid_connection_analyser import (
        _find_nearest_substations,
        estimate_connection_cost,
    )

    async with pool.acquire() as conn:
        subs = await _find_nearest_substations(
            conn, req.lat, req.lon,
            radius_km=30.0, limit=max(3, req.max_splits + 2),
        )

    if not subs:
        return {
            "single_connection_feasible": False,
            "splits": [],
            "warning": "No substations with data within 30 km — consider Tier 2 study.",
        }

    # Determine single-connection feasibility from best candidate.
    best = subs[0]
    best_headroom = float(best.get("gen_headroom_mw") or best.get("demand_headroom_mw") or 0)
    single_ok = best_headroom >= req.capacity_mw

    # Greedy split across top N subs: allocate min(remaining, sub_headroom) to each.
    splits: list[dict] = []
    for n in (2, 3)[: max(1, req.max_splits - 1)]:
        picks = subs[:n]
        remaining = req.capacity_mw
        allocations = []
        total_cost_m = 0.0
        max_months = 0
        for s in picks:
            hr = float(s.get("gen_headroom_mw") or s.get("demand_headroom_mw") or 0)
            mw = min(remaining, hr)
            if mw <= 0:
                continue
            try:
                cost = estimate_connection_cost(
                    distance_km=float(s.get("distance_km") or 0),
                    capacity_mw=mw,
                    voltage_kv=int(s.get("voltage_kv") or 33),
                )
                # estimate_connection_cost returns {p10, p50, p90} in £.
                total_cost_m += (cost.get("p50", 0) if isinstance(cost, dict) else float(cost)) / 1_000_000.0
            except Exception:
                total_cost_m += float(s.get("distance_km") or 0) * 0.15  # fallback £150k/km
            # Crude queue-time proxy: more subs → more coordination.
            max_months = max(max_months, 6 + n * 3)
            allocations.append({
                "id": str(s.get("id") or s.get("external_id") or ""),
                "name": s.get("name", ""),
                "mw_allocated": round(mw, 2),
                "distance_km": round(float(s.get("distance_km") or 0), 2),
                "voltage_kv": int(s.get("voltage_kv") or 33),
            })
            remaining -= mw
        total_mw = req.capacity_mw - remaining
        if total_mw <= 0:
            continue
        conf = (
            "high" if total_mw >= req.capacity_mw * 0.98
            else "medium" if total_mw >= req.capacity_mw * 0.85
            else "low"
        )
        splits.append({
            "substations": allocations,
            "total_mw": round(total_mw, 2),
            "reinforcement_cost_gbp_m": round(total_cost_m, 2),
            "queue_months_added": max_months,
            "confidence": conf,
        })

    # Rank: feasibility first, then cost.
    splits.sort(
        key=lambda s: (s["total_mw"] < req.capacity_mw, s["reinforcement_cost_gbp_m"]),
    )
    return {
        "single_connection_feasible": single_ok,
        "splits": splits,
    }


# ─── D3 — Lightweight agent/analyze for the DesignCanvas verdict rail ────

class _AnalyzeRequest(BaseModel):
    intent: str
    context: dict = {}


@router.post("/api/agent/analyze", tags=["agent"])
async def agent_analyze(
    body: _AnalyzeRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    request: Request = None,
):
    """Minimal wrapper around app.agent.run_structured_agent. Takes
    `{intent, context}`, returns the structured agent output (`verdict`,
    `summary`, `risks`, `opportunities`, `next_steps`).

    Used by the DesignCanvas verdict rail (4 parallel intents) and any
    other surface that wants a one-shot verdict without the full
    /site/{parcel_id}/agent plumbing.
    """
    from app.agent import (
        run_structured_agent,
        INTENT_PROMPTS,
        _default_actions,
    )
    from app.helpers import CLAUDE_MODEL

    if body.intent not in INTENT_PROMPTS:
        raise HTTPException(400, f"Unknown intent: {body.intent}")

    ctx = dict(body.context or {})
    ctx.setdefault("intent", body.intent)

    claude = None
    try:
        claude = getattr(request.app.state, "claude", None) if request else None
    except Exception:
        claude = None

    if claude is None:
        return {
            "verdict": "CAUTION",
            "confidence": 0.3,
            "summary": "Agent offline — no Claude client configured.",
            "risks": ["Agent unavailable"],
            "opportunities": [],
            "next_steps": [],
            "actions": _default_actions(body.intent, ctx),
            "intent": body.intent,
        }

    try:
        return await run_structured_agent(
            client=claude,
            model=CLAUDE_MODEL,
            context=ctx,
            intent=body.intent,
            pool=pool,
        )
    except Exception as e:
        return {
            "verdict": "CAUTION",
            "confidence": 0.3,
            "summary": f"Agent error ({e.__class__.__name__}) — heuristic fallback.",
            "risks": ["Agent error"],
            "opportunities": [],
            "next_steps": [],
            "actions": _default_actions(body.intent, ctx),
            "intent": body.intent,
        }


# ─── Godmode #1 — Headroom-Now ticker feed ─────────────────────────────────

@router.get("/api/grid/headroom-deltas")
async def headroom_deltas(
    window_h: int = Query(24, ge=1, le=168, description="Lookback window (hours)"),
    limit: int = Query(40, ge=1, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Recent DNO headroom changes as a ticker-shaped list.

    Pulls from the `grid_events` table when available; falls back to a
    top-K capacity tour from `grid_substations` so the ticker always has
    something to show.
    """
    try:
        async with pool.acquire() as conn:
            has_events = await conn.fetchval(
                "SELECT to_regclass('public.grid_events') IS NOT NULL"
            )
            if has_events:
                rows = await conn.fetch(
                    """
                    SELECT event_type, severity, substation_name, dno, region,
                           delta_mw, detected_at, geometry,
                           ST_Y(ST_Transform(geometry, 4326)) AS lat,
                           ST_X(ST_Transform(geometry, 4326)) AS lon
                    FROM grid_events
                    WHERE detected_at >= NOW() - ($1 || ' hours')::interval
                      AND delta_mw IS NOT NULL
                    ORDER BY detected_at DESC
                    LIMIT $2
                    """,
                    str(window_h), limit,
                )
                if rows:
                    return {
                        "source": "grid_events",
                        "window_h": window_h,
                        "deltas": [
                            {
                                "substation": r["substation_name"] or "",
                                "dno": r["dno"] or "",
                                "region": r["region"] or "",
                                "delta_mw": round(float(r["delta_mw"] or 0), 1),
                                "event_type": r["event_type"] or "",
                                "severity": r["severity"] or "info",
                                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                                "lat": float(r["lat"]) if r["lat"] is not None else None,
                                "lon": float(r["lon"]) if r["lon"] is not None else None,
                            }
                            for r in rows
                        ],
                    }
            # Fallback: show top-headroom substations as static chips.
            rows = await conn.fetch(
                """
                SELECT name, dno, region, gen_headroom_mw, demand_headroom_mw, voltage_kv,
                       ST_Y(ST_Transform(geom, 4326)) AS lat,
                       ST_X(ST_Transform(geom, 4326)) AS lon
                FROM grid_substations
                WHERE COALESCE(gen_headroom_mw, demand_headroom_mw) IS NOT NULL
                ORDER BY COALESCE(gen_headroom_mw, 0) DESC
                LIMIT $1
                """,
                limit,
            )
            return {
                "source": "static_top_headroom",
                "window_h": window_h,
                "deltas": [
                    {
                        "substation": r["name"] or "",
                        "dno": r["dno"] or "",
                        "region": r["region"] or "",
                        "delta_mw": round(float(r["gen_headroom_mw"] or r["demand_headroom_mw"] or 0), 1),
                        "event_type": "baseline",
                        "severity": "info",
                        "lat": float(r["lat"]) if r["lat"] is not None else None,
                        "lon": float(r["lon"]) if r["lon"] is not None else None,
                    }
                    for r in rows
                ],
            }
    except Exception as e:
        return {"source": "error", "window_h": window_h, "deltas": [], "error": str(e)}


# ─── Godmode #5 — N-1 Stress Test ──────────────────────────────────────────

class N1StressRequest(BaseModel):
    lat: float
    lon: float
    capacity_mw: float
    substation_name: str | None = None
    break_element: str | None = None  # "line:XYZ" or "trafo:ABC" — specific outage


@router.post("/api/grid/n1-stress-test")
async def n1_stress_test(
    body: N1StressRequest,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """N-1 contingency stress test around a connection site.

    Builds a small pandapower network around the target, runs contingency
    (each line/transformer out-of-service in turn), reports voltage
    violations and curtailment/reactive mitigations.
    """
    import os, asyncio, json as _json

    grid_python = os.getenv("GRID_PYTHON")
    runner = os.path.join(os.getenv("FEASIBLY_ROOT", os.path.dirname(os.path.dirname(__file__))), "..", "utils", "grid_power_flow.py")
    if not grid_python or not os.path.exists(runner):
        return {
            "ok": False,
            "reason": "grid subprocess unavailable",
            "summary": "Pandapower bridge not configured (set GRID_PYTHON).",
            "violations": [],
            "mitigations": [],
        }

    payload = {
        "lat": body.lat, "lon": body.lon,
        "capacity_mw": body.capacity_mw,
        "substation_name": body.substation_name,
        "break_element": body.break_element,
        "options": {"contingency": True, "verbose": False},
    }

    try:
        proc = await asyncio.create_subprocess_exec(
            grid_python, runner, "--mode", "n1_stress", "--json",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(_json.dumps(payload).encode()), timeout=60,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "reason": "subprocess_nonzero",
                "summary": f"Solver error: {stderr.decode()[:300]}",
                "violations": [],
                "mitigations": [],
            }
        result = _json.loads(stdout.decode())
    except asyncio.TimeoutError:
        return {
            "ok": False, "reason": "timeout",
            "summary": "Power-flow solver timed out after 60 s.",
            "violations": [], "mitigations": [],
        }
    except Exception as e:
        return {
            "ok": False, "reason": "exception",
            "summary": f"{e.__class__.__name__}: {e}",
            "violations": [], "mitigations": [],
        }

    violations = result.get("violations", []) or result.get("contingency", {}).get("violations", [])
    worst = max((abs(v.get("deviation_pct", 0)) for v in violations), default=0)
    if worst == 0:
        verdict_summary = f"Under N-1 with {body.capacity_mw:.0f} MW connected, all voltages stay within ±5%. No mitigation required."
    else:
        mvar = round(body.capacity_mw * worst * 0.12, 1)
        curtail = round(body.capacity_mw * worst * 0.003, 1)
        verdict_summary = (
            f"Under N-1, worst undervoltage {worst:.1f}% at {violations[0].get('bus', 'bus')}. "
            f"Mitigation: {mvar} MVAr reactive support or {curtail} MW curtailment contract."
        )

    return {
        "ok": True,
        "summary": verdict_summary,
        "violations": violations,
        "mitigations": result.get("mitigations", []),
        "converged": result.get("converged", True),
        "elapsed_s": result.get("elapsed_s"),
    }


# ─── Godmode #8 — Public read-only share view ─────────────────────────────

from uuid import UUID as _UUID


@router.get("/api/public/share/{token}")
async def public_share_view(
    token: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Stateless read-only view of a shared project.

    Validates the HMAC token minted by POST /api/v1/projects/{id}/share,
    returns a pruned public snapshot — no writes, no editing, no auth
    cookies. Designed to be linked from `princeps.app/p/{token}`.
    """
    from app.routers.projects import _verify_share_token
    project_id = _verify_share_token(token)
    if not project_id:
        raise HTTPException(404, "Share link invalid or expired")
    try:
        pid = _UUID(project_id)
    except ValueError:
        raise HTTPException(404, "Share link invalid")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT project_id, name, workload_type, stage, capacity_mw, created_at "
            "FROM projects WHERE project_id = $1",
            pid,
        )
        if not row:
            raise HTTPException(404, "Project not found")
        sites = await conn.fetch(
            """
            SELECT candidate_id, name,
                   ST_Y(ST_Transform(centroid, 4326)) AS lat,
                   ST_X(ST_Transform(centroid, 4326)) AS lon,
                   capacity_mw, scores
            FROM project_candidate_sites
            WHERE project_id = $1 LIMIT 25
            """,
            pid,
        )

    return {
        "project": {
            "project_id": str(row["project_id"]),
            "name": row["name"] or "Shared Project",
            "workload_type": row["workload_type"] or "bess",
            "stage": row["stage"] or "prospect",
            "capacity_mw": float(row["capacity_mw"] or 0),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        },
        "candidate_sites": [
            {
                "candidate_id": str(r["candidate_id"]),
                "name": r["name"] or "",
                "lat": float(r["lat"]) if r["lat"] is not None else None,
                "lon": float(r["lon"]) if r["lon"] is not None else None,
                "capacity_mw": float(r["capacity_mw"] or 0),
                "scores": r["scores"] if r["scores"] else {},
            }
            for r in sites
        ],
        "watermark": "Princeps · read-only shared view",
    }

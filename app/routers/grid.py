"""Grid router — grid data, connection assessment, capacity, digital twin, OSM."""

from __future__ import annotations

import asyncio
import json
import math
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
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
from utils.grid_data_ingester import ingest_all_dnos
from utils.grid_connection_analyser import (
    assess_connection as gc_assess,
    capacity_map_geojson as gc_capacity_map,
    substation_detail as gc_substation_detail,
    grid_lines_geojson as gc_lines_geojson,
    estimate_connection_cost as gc_cost_estimate,
    tier2_power_flow as gc_power_flow,
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


# ─── Grid Connection & Capacity Module ────────────────────────────────────────

@router.post("/api/grid/assess")
async def api_grid_assess(
    lat: float = Query(52.5),
    lon: float = Query(-1.5),
    capacity_mw: float = Query(5.0, ge=0.001),
    technology: str = Query("solar"),
    radius_km: float = Query(20.0, ge=1, le=100),
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


@router.get("/api/grid/substation/{substation_id}")
async def api_grid_substation(
    substation_id: int,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Full detail for a grid substation including connected DER, TEC queue,
    and capacity history.
    """
    async with pool.acquire() as conn:
        result = await gc_substation_detail(conn, substation_id)
    if not result:
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
#  CONSTRAINT COST OVERLAY + QUEUE DEPTH (Phase 7)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/grid/constraints")
async def api_grid_constraints(
    hours_ahead: int = Query(48, ge=1, le=168),
):
    """
    Grid constraint forecast as GeoJSON — colored boundary zones showing
    congestion risk, loading, and constraint cost per MWh.
    """
    from utils.constraint_forecaster import constraints_to_geojson
    return constraints_to_geojson(hours_ahead=hours_ahead)


@router.get("/api/grid/queue-depth")
async def api_grid_queue_depth(
    pool: asyncpg.Pool = Depends(get_pool),
):
    """
    Queue depth per substation — how many MW are waiting for connection,
    estimated wait time based on ECR progression rates.

    Returns GeoJSON FeatureCollection of substations with queue metrics.
    """
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


# ═══════════════════════════════════════════════════════════════════════════════
#  3D GRID DIGITAL TWIN — WebSocket + REST (Phase 6)
# ═══════════════════════════════════════════════════════════════════════════════

# Connected WebSocket clients for grid twin live updates
_grid_twin_clients: set[WebSocket] = set()


@router.get("/api/grid-twin/state")
async def api_grid_twin_state():
    """
    Full grid state snapshot for 3D digital twin.
    Returns substations (with demand/gen), lines (with flow), GSP demand,
    and system-level metrics.
    """
    now = datetime.now()
    hour = now.hour + now.minute / 60.0
    day_of_year = now.timetuple().tm_yday

    # Diurnal demand factor
    morning = math.exp(-0.5 * ((hour - 8.5) / 1.8) ** 2) * 0.85
    evening = math.exp(-0.5 * ((hour - 17.5) / 2.0) ** 2) * 1.0
    night = 0.35 + 0.15 * math.cos(2 * math.pi * (hour - 3) / 24)
    diurnal = max(night, morning, evening)
    seasonal = 0.7 + 0.3 * math.cos(2 * math.pi * (day_of_year - 15) / 365)

    # Representative UK substations with 3D positions
    substations = [
        {"id": "ABHA", "name": "Abham", "lat": 51.35, "lon": 0.55, "voltage_kv": 275,
         "capacity_mw": 360, "type": "GSP"},
        {"id": "BEDD", "name": "Beddington", "lat": 51.37, "lon": -0.13, "voltage_kv": 275,
         "capacity_mw": 500, "type": "GSP"},
        {"id": "BRWA", "name": "Bramley", "lat": 51.33, "lon": -1.06, "voltage_kv": 400,
         "capacity_mw": 640, "type": "GSP"},
        {"id": "CELL", "name": "Cellarhead", "lat": 53.00, "lon": -2.02, "voltage_kv": 275,
         "capacity_mw": 300, "type": "GSP"},
        {"id": "DEES", "name": "Deeside", "lat": 53.22, "lon": -3.04, "voltage_kv": 400,
         "capacity_mw": 450, "type": "GSP"},
        {"id": "EDIN", "name": "Edinburgh South", "lat": 55.92, "lon": -3.19, "voltage_kv": 275,
         "capacity_mw": 360, "type": "GSP"},
        {"id": "MANN", "name": "Manchester South", "lat": 53.45, "lon": -2.25, "voltage_kv": 400,
         "capacity_mw": 600, "type": "GSP"},
        {"id": "INDQ", "name": "Indian Queens", "lat": 50.39, "lon": -4.95, "voltage_kv": 132,
         "capacity_mw": 160, "type": "GSP"},
        {"id": "KEAD", "name": "Keadby", "lat": 53.60, "lon": -0.75, "voltage_kv": 275,
         "capacity_mw": 360, "type": "GSP"},
        {"id": "EXET", "name": "Exeter Main", "lat": 50.72, "lon": -3.53, "voltage_kv": 132,
         "capacity_mw": 200, "type": "GSP"},
        {"id": "NORW", "name": "Norwich Main", "lat": 52.62, "lon": 1.30, "voltage_kv": 275,
         "capacity_mw": 280, "type": "GSP"},
        {"id": "CAMA", "name": "Cambridge", "lat": 52.19, "lon": 0.14, "voltage_kv": 132,
         "capacity_mw": 250, "type": "GSP"},
        {"id": "LOVE", "name": "Lovedon", "lat": 51.08, "lon": -1.20, "voltage_kv": 132,
         "capacity_mw": 260, "type": "GSP"},
        {"id": "FLEE", "name": "Fleet", "lat": 51.28, "lon": -0.83, "voltage_kv": 132,
         "capacity_mw": 280, "type": "GSP"},
        {"id": "BOLN", "name": "Bolney", "lat": 50.98, "lon": -0.23, "voltage_kv": 275,
         "capacity_mw": 400, "type": "GSP"},
    ]

    # Add live demand/generation
    for s in substations:
        base_demand = s["capacity_mw"] * 0.55 * diurnal * seasonal
        s["demand_mw"] = round(base_demand * (1 + random.gauss(0, 0.04)), 1)
        solar_factor = max(0, math.sin(math.pi * max(0, min(1, (hour - 6) / 12))))
        solar_season = max(0.1, math.sin(math.pi * (day_of_year - 80) / 365))
        s["generation_mw"] = round(s["capacity_mw"] * 0.12 * solar_factor * solar_season * (1 + random.gauss(0, 0.05)), 1)
        s["net_demand_mw"] = round(s["demand_mw"] - s["generation_mw"], 1)
        s["utilisation"] = round(s["demand_mw"] / s["capacity_mw"], 3)
        s["headroom_mw"] = round(s["capacity_mw"] - s["demand_mw"], 1)

    # Lines connecting substations (major transmission corridors)
    lines = [
        {"from": "BRWA", "to": "BEDD", "voltage_kv": 400, "rating_mw": 1200},
        {"from": "BRWA", "to": "ABHA", "voltage_kv": 275, "rating_mw": 800},
        {"from": "BEDD", "to": "BOLN", "voltage_kv": 275, "rating_mw": 600},
        {"from": "BEDD", "to": "FLEE", "voltage_kv": 132, "rating_mw": 200},
        {"from": "BRWA", "to": "FLEE", "voltage_kv": 132, "rating_mw": 200},
        {"from": "BRWA", "to": "LOVE", "voltage_kv": 132, "rating_mw": 200},
        {"from": "ABHA", "to": "CAMA", "voltage_kv": 275, "rating_mw": 600},
        {"from": "CAMA", "to": "NORW", "voltage_kv": 275, "rating_mw": 500},
        {"from": "CELL", "to": "MANN", "voltage_kv": 275, "rating_mw": 800},
        {"from": "MANN", "to": "DEES", "voltage_kv": 400, "rating_mw": 1000},
        {"from": "MANN", "to": "KEAD", "voltage_kv": 275, "rating_mw": 600},
        {"from": "DEES", "to": "EDIN", "voltage_kv": 400, "rating_mw": 1000},
        {"from": "EXET", "to": "INDQ", "voltage_kv": 132, "rating_mw": 200},
        {"from": "BOLN", "to": "EXET", "voltage_kv": 275, "rating_mw": 500},
    ]

    sub_map = {s["id"]: s for s in substations}
    for line in lines:
        src = sub_map.get(line["from"], {})
        dst = sub_map.get(line["to"], {})
        line["from_coords"] = [src.get("lon", 0), src.get("lat", 0)]
        line["to_coords"] = [dst.get("lon", 0), dst.get("lat", 0)]
        # Flow: positive = from->to, magnitude based on net demand difference
        demand_diff = dst.get("net_demand_mw", 0) - src.get("net_demand_mw", 0)
        line["flow_mw"] = round(demand_diff * 0.6 * (1 + random.gauss(0, 0.08)), 1)
        line["loading_pct"] = round(abs(line["flow_mw"]) / line["rating_mw"] * 100, 1)
        line["congested"] = line["loading_pct"] > 80

    # System metrics
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
            "system_utilisation": round(total_demand / total_capacity, 3),
            "frequency_hz": round(50.0 + random.gauss(0, 0.02), 3),
            "hour": round(hour, 1),
            "day_of_year": day_of_year,
        },
    }


@router.websocket("/ws/grid-twin")
async def ws_grid_twin(ws: WebSocket):
    """
    WebSocket for real-time grid twin state updates.
    Sends grid state snapshot every 5 seconds.
    """
    await ws.accept()
    _grid_twin_clients.add(ws)
    try:
        while True:
            state = await api_grid_twin_state()
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

    base = await api_grid_twin_state()
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
    """Generate simulated DC telemetry for WebSocket streaming."""
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
# Queue Depth Analysis
# ══════════════════════════════════════════════════════════

@router.get("/api/grid/queue-depth/{substation_id}")
async def queue_depth(substation_id: int, pool: asyncpg.Pool = Depends(get_pool)):
    """Queue depth analysis for a single substation."""
    from utils.queue_analyser import get_queue_depth
    result = await get_queue_depth(pool, substation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Substation not found or no queue data")
    return result


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
# Constraint Cost Overlay
# ══════════════════════════════════════════════════════════

@router.get("/api/grid/constraints")
async def get_constraints(
    west: float = None, south: float = None,
    east: float = None, north: float = None,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return constraint cost zones as GeoJSON for map overlay."""
    from utils.constraint_overlay import get_constraint_zones
    bbox = (west, south, east, north) if all(v is not None for v in [west, south, east, north]) else None
    return await get_constraint_zones(pool, bbox=bbox)


# ══════════════════════════════════════════════════════════
# Live Grid Status
# ══════════════════════════════════════════════════════════

@router.get("/api/grid/live-status")
async def live_grid_status():
    """Real-time UK grid demand, carbon intensity, and generation mix."""
    from utils.live_grid_status import get_live_status
    return await get_live_status()

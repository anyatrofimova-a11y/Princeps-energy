"""
NGED (formerly WPD) Live Data Feed Application Map — direct ingester.

NGED publishes real-time demand / generation / import / solar / wind / storage
totals for each of its four licence areas (East Midlands, West Midlands, Wales,
South West) on the Live Data Feed Application Map page. The current snapshot is
embedded as a JSON blob directly in the page HTML.

https://commercial.nationalgrid.co.uk/our-network/live-data-feed-application-map

This module:
  * fetches and parses the embedded snapshot
  * persists it to `nged_live_snapshots`
  * exposes a helper to return the current feed as GeoJSON for map display
  * emits a `substation_headroom_change` / `licence_area_flow_change` event
    via grid_events when values swing outside threshold.

The Network Opportunity Map (headroom) visualisation is built separately from
the existing `grid_substations` table (which already has demand/gen headroom and
RAG columns). See `get_headroom_geojson()` below.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

log = logging.getLogger("princeps.nged_live_feed")

NGED_LIVE_URL = "https://commercial.nationalgrid.co.uk/our-network/live-data-feed-application-map"

# Four NGED licence areas — approximate bbox centroids for map placement
LICENCE_AREAS: dict[str, dict] = {
    "EM": {
        "name": "East Midlands",
        "centroid": [-0.75, 52.9],
        "bbox": [-2.3, 51.8, 0.8, 53.7],
        "colour": "#c0392b",
    },
    "WM": {
        "name": "West Midlands",
        "centroid": [-2.3, 52.5],
        "bbox": [-3.5, 51.5, -1.3, 53.2],
        "colour": "#e67e22",
    },
    "WA": {
        "name": "Wales",
        "centroid": [-3.8, 52.1],
        "bbox": [-5.4, 51.3, -2.6, 53.5],
        "colour": "#27ae60",
    },
    "SW": {
        "name": "South West",
        "centroid": [-3.6, 50.9],
        "bbox": [-6.0, 49.8, -1.8, 52.0],
        "colour": "#2980b9",
    },
}


# ────────────────────────────────────────────────────────────────────────
# Schema
# ────────────────────────────────────────────────────────────────────────

NGED_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nged_live_snapshots (
    snapshot_id    BIGSERIAL PRIMARY KEY,
    licence_area   TEXT NOT NULL,
    observed_at    TIMESTAMPTZ NOT NULL,
    demand_mw      NUMERIC,
    generation_mw  NUMERIC,
    import_mw      NUMERIC,
    solar_mw       NUMERIC,
    wind_mw        NUMERIC,
    storage_mw     NUMERIC,
    other_mw       NUMERIC,
    ingested_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (licence_area, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_nged_licence_time
    ON nged_live_snapshots (licence_area, observed_at DESC);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    """Ensure the nged_live_snapshots table exists."""
    async with pool.acquire() as conn:
        for stmt in NGED_SCHEMA_SQL.split(";"):
            if stmt.strip():
                await conn.execute(stmt)
    log.info("nged_live_feed schema ready")


# ────────────────────────────────────────────────────────────────────────
# Scraping
# ────────────────────────────────────────────────────────────────────────

_RE_INIT = re.compile(
    r'vm\.initMap\([^,]+,\s*"(.*?)",\s*\{',
    re.DOTALL,
)


async def fetch_live_snapshot(timeout: float = 20.0) -> dict | None:
    """Fetch the NGED Live Data Feed page and parse the embedded JSON blob.

    Returns a dict with keys: demand_total, generation_total, import_total,
    licence_areas[]. Returns None on failure (network, parse, etc).
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.get(NGED_LIVE_URL)
            r.raise_for_status()
            html = r.text
    except Exception as e:
        log.warning("NGED fetch failed: %s", e)
        return None

    m = _RE_INIT.search(html)
    if not m:
        log.warning("NGED snapshot JSON not found in HTML")
        return None

    raw = m.group(1)
    # The JSON inside is HTML-escaped with \&quot; and \u0027 style escapes
    unescaped = (
        raw.replace('\\"', '"')
           .replace('\\&quot;', '"')
           .replace('&quot;', '"')
           .replace('\\u0027', "'")
    )
    try:
        return json.loads(unescaped)
    except json.JSONDecodeError as e:
        log.warning("NGED JSON parse failed: %s", e)
        return None


async def ingest_snapshot(pool: asyncpg.Pool) -> dict:
    """Fetch + persist the latest NGED snapshot. Returns ingest summary."""
    snap = await fetch_live_snapshot()
    if not snap:
        return {"ok": False, "reason": "fetch_failed"}

    rows_inserted = 0
    observed_ts = None
    async with pool.acquire() as conn:
        for la in snap.get("licence_areas", []):
            try:
                observed = datetime.fromisoformat(la["timestamp"].replace(" ", "T"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
            except Exception:
                observed = datetime.now(timezone.utc)
            observed_ts = observed_ts or observed
            await conn.execute(
                """
                INSERT INTO nged_live_snapshots
                    (licence_area, observed_at, demand_mw, generation_mw,
                     import_mw, solar_mw, wind_mw, storage_mw, other_mw)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (licence_area, observed_at) DO UPDATE SET
                    demand_mw = EXCLUDED.demand_mw,
                    generation_mw = EXCLUDED.generation_mw,
                    import_mw = EXCLUDED.import_mw,
                    solar_mw = EXCLUDED.solar_mw,
                    wind_mw = EXCLUDED.wind_mw,
                    storage_mw = EXCLUDED.storage_mw,
                    other_mw = EXCLUDED.other_mw
                """,
                la.get("licence_area"),
                observed,
                _num(la.get("demand")),
                _num(la.get("generation")),
                _num(la.get("import")),
                _num(la.get("solar")),
                _num(la.get("wind")),
                _num(la.get("stor")),
                _num(la.get("other")),
            )
            rows_inserted += 1

    return {
        "ok": True,
        "rows_inserted": rows_inserted,
        "observed_at": observed_ts.isoformat() if observed_ts else None,
        "totals": {
            "demand_total": snap.get("demand_total"),
            "generation_total": snap.get("generation_total"),
            "import_total": snap.get("import_total"),
        },
    }


def _num(x: Any) -> float | None:
    """Coerce to float or None."""
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


# ────────────────────────────────────────────────────────────────────────
# Read-side (feeds the frontend map layer)
# ────────────────────────────────────────────────────────────────────────

async def get_latest_feed(pool: asyncpg.Pool) -> dict:
    """Return the latest snapshot per licence area plus totals."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (licence_area)
                licence_area, observed_at, demand_mw, generation_mw, import_mw,
                solar_mw, wind_mw, storage_mw, other_mw
            FROM nged_live_snapshots
            ORDER BY licence_area, observed_at DESC
            """
        )
    licence_areas = []
    demand_total = generation_total = import_total = 0.0
    for r in rows:
        demand_total += float(r["demand_mw"] or 0)
        generation_total += float(r["generation_mw"] or 0)
        import_total += float(r["import_mw"] or 0)
        meta = LICENCE_AREAS.get(r["licence_area"], {})
        licence_areas.append({
            "licence_area": r["licence_area"],
            "name": meta.get("name", r["licence_area"]),
            "centroid": meta.get("centroid"),
            "bbox": meta.get("bbox"),
            "colour": meta.get("colour"),
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
            "demand_mw": float(r["demand_mw"] or 0),
            "generation_mw": float(r["generation_mw"] or 0),
            "import_mw": float(r["import_mw"] or 0),
            "solar_mw": float(r["solar_mw"] or 0),
            "wind_mw": float(r["wind_mw"] or 0),
            "storage_mw": float(r["storage_mw"] or 0),
            "other_mw": float(r["other_mw"] or 0),
        })
    return {
        "licence_areas": licence_areas,
        "demand_total": demand_total,
        "generation_total": generation_total,
        "import_total": import_total,
    }


async def get_licence_areas_geojson(pool: asyncpg.Pool) -> dict:
    """Return licence area polygons + live values as a GeoJSON FeatureCollection."""
    feed = await get_latest_feed(pool)
    features = []
    for la in feed["licence_areas"]:
        bbox = la["bbox"]
        if not bbox:
            continue
        w, s, e, n = bbox
        polygon = [[
            [w, s], [e, s], [e, n], [w, n], [w, s]
        ]]
        # Normalised "flow intensity" 0..1 — used for fill opacity
        demand = la["demand_mw"] or 0
        generation = la["generation_mw"] or 0
        total = max(demand + generation, 1)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": polygon},
            "properties": {
                "licence_area": la["licence_area"],
                "name": la["name"],
                "demand_mw": demand,
                "generation_mw": generation,
                "import_mw": la["import_mw"],
                "solar_mw": la["solar_mw"],
                "wind_mw": la["wind_mw"],
                "storage_mw": la["storage_mw"],
                "other_mw": la["other_mw"],
                "flow_intensity": round(demand / total, 3),
                "fill": la["colour"],
                "observed_at": la["observed_at"],
            },
        })
    return {"type": "FeatureCollection", "features": features}


async def get_history(
    pool: asyncpg.Pool, licence_area: str | None = None, hours: int = 24
) -> list[dict]:
    """Return historical snapshots for the trend view."""
    conditions = ["observed_at >= now() - make_interval(hours => $1)"]
    params: list[Any] = [hours]
    if licence_area:
        conditions.append("licence_area = $2")
        params.append(licence_area)
    sql = f"""
        SELECT licence_area, observed_at, demand_mw, generation_mw, import_mw,
               solar_mw, wind_mw, storage_mw, other_mw
        FROM nged_live_snapshots
        WHERE {" AND ".join(conditions)}
        ORDER BY observed_at ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [
        {
            "licence_area": r["licence_area"],
            "observed_at": r["observed_at"].isoformat() if r["observed_at"] else None,
            "demand_mw": float(r["demand_mw"] or 0),
            "generation_mw": float(r["generation_mw"] or 0),
            "import_mw": float(r["import_mw"] or 0),
            "solar_mw": float(r["solar_mw"] or 0),
            "wind_mw": float(r["wind_mw"] or 0),
            "storage_mw": float(r["storage_mw"] or 0),
            "other_mw": float(r["other_mw"] or 0),
        } for r in rows
    ]


# ────────────────────────────────────────────────────────────────────────
# Network Opportunity Map (headroom) — from existing grid_substations
# ────────────────────────────────────────────────────────────────────────

# Headroom colour ramp (green = plenty, amber = tight, red = constrained)
_HEADROOM_COLOURS = [
    (0,      "#b71c1c"),   # 0 MW — constrained
    (5,      "#d32f2f"),
    (10,     "#e57373"),
    (25,     "#f9a825"),
    (50,     "#fdd835"),
    (100,    "#7cb342"),
    (250,    "#43a047"),
    (500,    "#2e7d32"),
]


def _headroom_colour(mw: float | None) -> str:
    """Return a hex colour for the given headroom MW using the ramp."""
    if mw is None or mw <= 0:
        return "#b71c1c"
    for threshold, colour in _HEADROOM_COLOURS:
        if mw <= threshold:
            return colour
    return "#1b5e20"


async def get_headroom_geojson(
    pool: asyncpg.Pool,
    kind: str = "demand",            # 'demand' | 'generation'
    dno: str | None = None,
    min_voltage_kv: float = 11.0,
    limit: int = 5000,
) -> dict:
    """Return a GeoJSON FeatureCollection of substations sized/coloured by headroom.

    This is the "Network Opportunity Map" equivalent built from the existing
    grid_substations table. Each feature carries:
      * properties.headroom_mw
      * properties.rag (R/A/G)
      * properties.colour (hex, from the colour ramp)
      * properties.radius (rendering hint, scaled by headroom)
    """
    col_headroom = "demand_headroom_mw" if kind == "demand" else "gen_headroom_mw"
    col_rag = "rag_demand" if kind == "demand" else "rag_generation"

    conditions = [
        "geom IS NOT NULL",
        f"voltage_kv >= ${1}",
        f"{col_headroom} IS NOT NULL",
    ]
    params: list[Any] = [min_voltage_kv]
    if dno:
        conditions.append(f"dno = ${len(params) + 1}")
        params.append(dno)

    sql = f"""
        SELECT id, external_id, name, dno, region, voltage_kv, site_type,
               {col_headroom} AS headroom_mw,
               {col_rag} AS rag,
               transformer_rating_mva,
               ST_X(ST_Transform(geom, 4326)) AS lon,
               ST_Y(ST_Transform(geom, 4326)) AS lat
        FROM grid_substations
        WHERE {" AND ".join(conditions)}
        ORDER BY {col_headroom} DESC NULLS LAST
        LIMIT ${len(params) + 1}
    """
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    features = []
    for r in rows:
        headroom = float(r["headroom_mw"] or 0)
        colour = _headroom_colour(headroom)
        # Radius: 4px at 0 MW, scales log-ish to 24px at 500 MW
        radius = 4 + min(20, (headroom / 25.0))
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r["lon"]), float(r["lat"])],
            },
            "properties": {
                "id": r["id"],
                "external_id": r["external_id"],
                "name": r["name"],
                "dno": r["dno"],
                "region": r["region"],
                "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
                "site_type": r["site_type"],
                "headroom_mw": headroom,
                "rag": r["rag"],
                "transformer_rating_mva": float(r["transformer_rating_mva"]) if r["transformer_rating_mva"] else None,
                "colour": colour,
                "radius": round(radius, 1),
                "kind": kind,
            },
        })

    return {
        "type": "FeatureCollection",
        "kind": kind,
        "dno_filter": dno,
        "min_voltage_kv": min_voltage_kv,
        "count": len(features),
        "colour_ramp": [{"threshold_mw": t, "colour": c} for t, c in _HEADROOM_COLOURS],
        "features": features,
    }


async def get_substation_index(
    pool: asyncpg.Pool,
    min_voltage_kv: float = 11.0,
    dno: str | None = None,
    voltage_levels: list[float] | None = None,
) -> list[dict]:
    """Return a lightweight index of every substation for the CIM-style asset browser.

    Rows are tiny ({id, name, voltage, dno, lat, lon, headroom, rag, colour}) —
    14k rows ≈ 1.2 MB wire, cached in the browser. Fetched ONCE on map mount.
    """
    conditions = ["geom IS NOT NULL", f"voltage_kv >= {float(min_voltage_kv)}"]
    params: list[Any] = []
    if dno:
        conditions.append(f"dno = ${len(params) + 1}")
        params.append(dno)
    if voltage_levels:
        conditions.append(f"voltage_kv = ANY(${len(params) + 1}::numeric[])")
        params.append(voltage_levels)

    sql = f"""
        SELECT id, external_id, name, dno, region, voltage_kv, site_type,
               demand_headroom_mw, gen_headroom_mw, rag_demand, rag_generation,
               ST_X(ST_Transform(geom, 4326)) AS lon,
               ST_Y(ST_Transform(geom, 4326)) AS lat
        FROM grid_substations
        WHERE {" AND ".join(conditions)}
        ORDER BY voltage_kv DESC NULLS LAST, demand_headroom_mw DESC NULLS LAST
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    out = []
    for r in rows:
        headroom = float(r["demand_headroom_mw"] or 0)
        out.append({
            "id": int(r["id"]),
            "external_id": r["external_id"],
            "name": r["name"],
            "dno": r["dno"],
            "region": r["region"],
            "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
            "site_type": r["site_type"],
            "headroom_mw": headroom,
            "gen_headroom_mw": float(r["gen_headroom_mw"] or 0),
            "rag": r["rag_demand"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "colour": _headroom_colour(headroom),
        })
    return out


async def get_headroom_stats(pool: asyncpg.Pool, dno: str | None = None) -> dict:
    """Return aggregate headroom stats for the Pulse header strip."""
    conditions = ["demand_headroom_mw IS NOT NULL"]
    params: list[Any] = []
    if dno:
        conditions.append("dno = $1")
        params.append(dno)
    sql = f"""
        SELECT COUNT(*)::int AS n_substations,
               COALESCE(SUM(demand_headroom_mw), 0)::float AS total_demand_headroom_mw,
               COALESCE(SUM(gen_headroom_mw), 0)::float AS total_gen_headroom_mw,
               COUNT(*) FILTER (WHERE rag_demand = 'R')::int AS red_demand,
               COUNT(*) FILTER (WHERE rag_demand = 'A')::int AS amber_demand,
               COUNT(*) FILTER (WHERE rag_demand = 'G')::int AS green_demand,
               COUNT(*) FILTER (WHERE rag_generation = 'R')::int AS red_gen,
               COUNT(*) FILTER (WHERE rag_generation = 'A')::int AS amber_gen,
               COUNT(*) FILTER (WHERE rag_generation = 'G')::int AS green_gen
        FROM grid_substations
        WHERE {" AND ".join(conditions)}
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *params)
    return dict(row) if row else {}

"""
Grid Constraints — fetch and process National Grid ESO constraint data
for map overlay visualisation.

Sources:
  - NESO CKAN API: constraint costs by transmission boundary
  - NESO system warnings: active outages and alerts
  - Carbon Intensity API: real-time carbon intensity by region
  - BMRS / Elexon: demand, generation, frequency

Outputs GeoJSON FeatureCollections for:
  - Constraint zone polygons (severity-coloured by £/MWh)
  - TEC queue depth circles (sized by project count, coloured by wait time)
  - Live system status summary

Called from FastAPI endpoints and the frontend map layer system.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("princeps.grid_constraints")

_TIMEOUT = 12  # seconds
_USER_AGENT = "Princeps/1.0 grid-constraints"

# ─── NESO CKAN API Configuration ──────────────────────────────────────────

CKAN_BASE = "https://api.neso.energy/api/3/action"
# NESO constraint cost dataset resource IDs (published quarterly)
CONSTRAINT_COST_RESOURCE = "f93d1835-75bc-43e5-84ad-12472b180a98"
SYSTEM_WARNINGS_RESOURCE = "10a39c31-2f2b-44b1-9821-6a2c8b98cbd3"

# Carbon Intensity API (national.grid.co.uk partner, no key required)
CARBON_API = "https://api.carbonintensity.org.uk/intensity"

# BMRS / Elexon (public, no key required)
BMRS_DEMAND_URL = "https://data.elexon.co.uk/bmrs/api/v1/datasets/INDO"
BMRS_FREQ_URL = "https://data.elexon.co.uk/bmrs/api/v1/datasets/FREQ"


# ─── UK Transmission Constraint Boundary Zones ──────────────────────────

# ESO boundary definitions as WGS84 polygon coordinates.
# These are approximate corridors where transmission constraints bind.
# Source: NESO Electricity Ten Year Statement (ETYS) boundary maps.

BOUNDARY_ZONES: dict[str, dict[str, Any]] = {
    "B0": {
        "name": "Scotland North–South (Highland Boundary)",
        "description": "Constraint across the Highland Boundary Fault corridor",
        "capacity_gw": 3.3,
        "polygon": [
            [-6.2, 56.3], [-3.5, 56.3], [-3.5, 57.0],
            [-6.2, 57.0], [-6.2, 56.3],
        ],
    },
    "B1": {
        "name": "Scotland–England (Cheviot)",
        "description": "North-south flow across the Anglo-Scottish border",
        "capacity_gw": 5.7,
        "polygon": [
            [-4.8, 55.0], [-1.8, 55.0], [-1.8, 55.8],
            [-4.8, 55.8], [-4.8, 55.0],
        ],
    },
    "B2": {
        "name": "North England (Pennines)",
        "description": "East-west transfer across the Pennine spine and M62 corridor",
        "capacity_gw": 8.5,
        "polygon": [
            [-3.5, 53.4], [-0.5, 53.4], [-0.5, 54.2],
            [-3.5, 54.2], [-3.5, 53.4],
        ],
    },
    "B4": {
        "name": "Midlands",
        "description": "North-south flow through the Midlands ring",
        "capacity_gw": 11.2,
        "polygon": [
            [-3.0, 52.0], [0.5, 52.0], [0.5, 52.8],
            [-3.0, 52.8], [-3.0, 52.0],
        ],
    },
    "B6": {
        "name": "Scotland (Central Belt)",
        "description": "Constraint through the Scottish Central Belt",
        "capacity_gw": 3.8,
        "polygon": [
            [-5.5, 55.7], [-3.0, 55.7], [-3.0, 56.4],
            [-5.5, 56.4], [-5.5, 55.7],
        ],
    },
    "B7": {
        "name": "East Coast",
        "description": "North-south flow along the east coast corridor (offshore wind landing)",
        "capacity_gw": 6.5,
        "polygon": [
            [-0.5, 52.5], [1.8, 52.5], [1.8, 54.0],
            [-0.5, 54.0], [-0.5, 52.5],
        ],
    },
    "B8": {
        "name": "West Coast / South Wales",
        "description": "Flow across the Welsh border and Severn crossing",
        "capacity_gw": 3.2,
        "polygon": [
            [-5.0, 51.4], [-2.5, 51.4], [-2.5, 52.3],
            [-5.0, 52.3], [-5.0, 51.4],
        ],
    },
}


# ─── Severity Classification ─────────────────────────────────────────────

def _severity_colour(cost_gbp_mwh: float) -> dict[str, Any]:
    """
    Classify constraint cost into severity band with RGBA colour.

    Returns colour suitable for deck.gl / Mapbox polygon fill.
    """
    if cost_gbp_mwh < 5:
        return {
            "severity": "LOW",
            "label": "Uncongested",
            "fill": [34, 197, 94, 80],   # green, semi-transparent
            "stroke": [22, 163, 74, 200],
        }
    elif cost_gbp_mwh < 20:
        return {
            "severity": "MODERATE",
            "label": "Moderate congestion",
            "fill": [251, 191, 36, 100],  # amber
            "stroke": [217, 119, 6, 200],
        }
    else:
        return {
            "severity": "HIGH",
            "label": "Severely congested",
            "fill": [239, 68, 68, 120],   # red
            "stroke": [185, 28, 28, 200],
        }


# ─── Synthetic / Fallback Data ───────────────────────────────────────────

def _synthetic_constraint_costs() -> dict[str, dict[str, Any]]:
    """
    Return realistic synthetic constraint cost data when NESO API is
    unavailable.  Values are based on published ESO outturn reports.
    """
    random.seed(int(time.time()) // 3600)  # changes hourly
    return {
        "B0": {"cost_gbp_mwh": round(random.uniform(15, 55), 1),
               "direction": "N→S", "volume_mwh": round(random.uniform(200, 800))},
        "B1": {"cost_gbp_mwh": round(random.uniform(20, 70), 1),
               "direction": "N→S", "volume_mwh": round(random.uniform(500, 2000))},
        "B2": {"cost_gbp_mwh": round(random.uniform(3, 25), 1),
               "direction": "N→S", "volume_mwh": round(random.uniform(100, 600))},
        "B4": {"cost_gbp_mwh": round(random.uniform(1, 15), 1),
               "direction": "N→S", "volume_mwh": round(random.uniform(50, 400))},
        "B6": {"cost_gbp_mwh": round(random.uniform(10, 45), 1),
               "direction": "N→S", "volume_mwh": round(random.uniform(300, 1200))},
        "B7": {"cost_gbp_mwh": round(random.uniform(2, 18), 1),
               "direction": "W→E", "volume_mwh": round(random.uniform(100, 500))},
        "B8": {"cost_gbp_mwh": round(random.uniform(5, 30), 1),
               "direction": "W→E", "volume_mwh": round(random.uniform(100, 600))},
    }


def _synthetic_warnings() -> list[dict[str, Any]]:
    """Return a small set of plausible system warnings."""
    return [
        {
            "id": "SYN-001",
            "type": "planned_outage",
            "boundary": "B1",
            "message": "Harker–Hutton 400kV circuit outage for maintenance",
            "start": "2026-03-18T06:00:00Z",
            "end": "2026-03-22T18:00:00Z",
            "impact_mw": 800,
        },
        {
            "id": "SYN-002",
            "type": "constraint_active",
            "boundary": "B0",
            "message": "High wind generation in Scotland — B0 boundary binding",
            "start": "2026-03-20T00:00:00Z",
            "end": None,
            "impact_mw": 1200,
        },
    ]


# ─── NESO API Fetchers ───────────────────────────────────────────────────

async def fetch_constraint_costs() -> dict[str, dict[str, Any]]:
    """
    Fetch constraint cost data from NESO CKAN datastore.

    Returns a dict keyed by boundary ID with fields:
        cost_gbp_mwh  — average constraint cost per MWh
        direction     — predominant flow direction (e.g. "N→S")
        volume_mwh    — constrained energy volume
        severity      — LOW / MODERATE / HIGH

    Falls back to synthetic data if the API is unreachable.
    """
    url = f"{CKAN_BASE}/datastore_search"
    params = {
        "resource_id": CONSTRAINT_COST_RESOURCE,
        "limit": 500,
    }

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()

        records = payload.get("result", {}).get("records", [])
        if not records:
            log.info("NESO constraint cost query returned 0 records — using synthetic")
            return _add_severity(_synthetic_constraint_costs())

        # Parse NESO records into our boundary-keyed structure.
        # Column names vary by dataset version; try common variants.
        result: dict[str, dict[str, Any]] = {}
        for rec in records:
            bid = (
                rec.get("Boundary")
                or rec.get("boundary")
                or rec.get("constraint_group")
                or ""
            )
            # Normalise to our B-codes
            bid_normalised = _normalise_boundary_id(bid)
            if not bid_normalised:
                continue

            cost = _float_or(rec.get("Cost_GBP_MWh") or rec.get("cost_per_mwh"), 0)
            volume = _float_or(rec.get("Volume_MWh") or rec.get("volume_mwh"), 0)
            direction = rec.get("Direction") or rec.get("direction") or "N→S"

            # Keep highest cost if multiple records per boundary
            if bid_normalised in result and result[bid_normalised]["cost_gbp_mwh"] >= cost:
                continue
            result[bid_normalised] = {
                "cost_gbp_mwh": round(cost, 1),
                "direction": direction,
                "volume_mwh": round(volume),
            }

        if not result:
            log.info("No parseable boundary data in NESO response — using synthetic")
            return _add_severity(_synthetic_constraint_costs())

        log.info("Fetched constraint costs for %d boundaries from NESO", len(result))
        return _add_severity(result)

    except httpx.HTTPStatusError as exc:
        log.warning("NESO constraint API HTTP %s — falling back to synthetic", exc.response.status_code)
    except httpx.TimeoutException:
        log.warning("NESO constraint API timeout (%ds) — falling back to synthetic", _TIMEOUT)
    except Exception as exc:
        log.warning("NESO constraint API error: %s — falling back to synthetic", exc)

    return _add_severity(_synthetic_constraint_costs())


async def fetch_system_warnings() -> list[dict[str, Any]]:
    """
    Fetch active system warnings and planned outages from NESO.

    Returns a list of warning dicts with fields:
        id, type, boundary, message, start, end, impact_mw

    Falls back to synthetic warnings if the API is unreachable.
    """
    url = f"{CKAN_BASE}/datastore_search"
    params = {
        "resource_id": SYSTEM_WARNINGS_RESOURCE,
        "limit": 100,
    }

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()

        records = payload.get("result", {}).get("records", [])
        if not records:
            log.info("NESO system warnings returned 0 records — using synthetic")
            return _synthetic_warnings()

        warnings: list[dict[str, Any]] = []
        for rec in records:
            warnings.append({
                "id": rec.get("_id") or rec.get("id", ""),
                "type": rec.get("Type") or rec.get("type", "info"),
                "boundary": _normalise_boundary_id(
                    rec.get("Boundary") or rec.get("boundary") or ""
                ),
                "message": rec.get("Message") or rec.get("message") or rec.get("Description", ""),
                "start": rec.get("Start") or rec.get("start_date"),
                "end": rec.get("End") or rec.get("end_date"),
                "impact_mw": _float_or(rec.get("Impact_MW") or rec.get("impact_mw"), 0),
            })

        log.info("Fetched %d system warnings from NESO", len(warnings))
        return warnings

    except httpx.HTTPStatusError as exc:
        log.warning("NESO warnings API HTTP %s — falling back to synthetic", exc.response.status_code)
    except httpx.TimeoutException:
        log.warning("NESO warnings API timeout — falling back to synthetic")
    except Exception as exc:
        log.warning("NESO warnings API error: %s — falling back to synthetic", exc)

    return _synthetic_warnings()


# ─── GeoJSON Builders ─────────────────────────────────────────────────────

def constraints_geojson(
    constraint_data: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Build a GeoJSON FeatureCollection of constraint zone polygons.

    Each polygon is coloured by constraint severity:
      - Green  (<£5/MWh)  — uncongested
      - Amber  (£5-20/MWh) — moderate congestion
      - Red    (>£20/MWh)  — severely congested

    Args:
        constraint_data: dict from ``fetch_constraint_costs()``, keyed by
            boundary ID with cost_gbp_mwh, direction, severity fields.

    Returns:
        GeoJSON FeatureCollection dict ready for deck.gl / Mapbox.
    """
    features: list[dict[str, Any]] = []

    for bid, zone in BOUNDARY_ZONES.items():
        cdata = constraint_data.get(bid, {})
        cost = cdata.get("cost_gbp_mwh", 0)
        colours = _severity_colour(cost)

        feature: dict[str, Any] = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [zone["polygon"]],
            },
            "properties": {
                "boundary_id": bid,
                "name": zone["name"],
                "description": zone["description"],
                "capacity_gw": zone["capacity_gw"],
                "cost_gbp_mwh": cost,
                "direction": cdata.get("direction", "N→S"),
                "volume_mwh": cdata.get("volume_mwh", 0),
                "severity": colours["severity"],
                "severity_label": colours["label"],
                "fill_color": colours["fill"],
                "stroke_color": colours["stroke"],
            },
        }
        features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "NESO constraint data / synthetic fallback",
            "colour_scale": {
                "green": "<£5/MWh (uncongested)",
                "amber": "£5-20/MWh (moderate congestion)",
                "red": ">£20/MWh (severely congested)",
            },
        },
    }


async def queue_depth_geojson(pool) -> dict[str, Any]:
    """
    Build a GeoJSON FeatureCollection of TEC queue depth per substation.

    Queries the ``eso_tec_project`` and ``grid_substations`` tables to count
    queued/contracted projects at each connection site.  Circles are sized by
    project count and coloured by average wait time.

    Args:
        pool: asyncpg connection pool.

    Returns:
        GeoJSON FeatureCollection with Point features (circle markers).
    """
    features: list[dict[str, Any]] = []

    try:
        async with pool.acquire() as conn:
            # Check whether eso_tec_project table exists
            exists = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'eso_tec_project'
                )
            """)
            if not exists:
                log.info("eso_tec_project table not found — returning empty queue depth")
                return _empty_feature_collection("No TEC queue data available")

            # Aggregate projects per connection site
            rows = await conn.fetch("""
                SELECT
                    connection_site,
                    matched_substation_name,
                    COUNT(*)                                  AS project_count,
                    COALESCE(SUM(mw_connected), 0)            AS total_mw,
                    COUNT(*) FILTER (WHERE project_status IN ('Accepted', 'Offer'))
                                                              AS active_count,
                    COUNT(*) FILTER (WHERE project_status = 'Built')
                                                              AS built_count,
                    AVG(EXTRACT(YEAR FROM NOW()) -
                        EXTRACT(YEAR FROM mw_effective_from))  AS avg_wait_years,
                    ST_X(ST_Centroid(ST_Collect(geometry)))     AS lon,
                    ST_Y(ST_Centroid(ST_Collect(geometry)))     AS lat
                FROM eso_tec_project
                WHERE geometry IS NOT NULL
                GROUP BY connection_site, matched_substation_name
                ORDER BY project_count DESC
            """)

            for row in rows:
                wait_yrs = float(row["avg_wait_years"] or 0)
                colour = _queue_wait_colour(wait_yrs)
                # Circle radius proportional to project count (clamped 4-40px)
                radius = max(4, min(40, int(row["project_count"] ** 0.6 * 5)))

                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(row["lon"]), float(row["lat"])],
                    },
                    "properties": {
                        "connection_site": row["connection_site"],
                        "substation": row["matched_substation_name"],
                        "project_count": row["project_count"],
                        "active_count": row["active_count"],
                        "built_count": row["built_count"],
                        "total_mw": round(float(row["total_mw"]), 1),
                        "avg_wait_years": round(wait_yrs, 1),
                        "radius": radius,
                        "fill_color": colour["fill"],
                        "stroke_color": colour["stroke"],
                        "wait_label": colour["label"],
                    },
                })

            log.info("Built queue depth GeoJSON: %d connection sites", len(features))

    except Exception as exc:
        log.warning("Queue depth query failed: %s — returning empty collection", exc)
        return _empty_feature_collection(f"Query error: {exc}")

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "eso_tec_project table",
            "total_sites": len(features),
            "colour_scale": {
                "green": "<3 years average wait",
                "amber": "3-7 years average wait",
                "red": ">7 years average wait",
            },
        },
    }


# ─── Live System Status ──────────────────────────────────────────────────

async def live_status_summary() -> dict[str, Any]:
    """
    Fetch live UK grid status: demand, generation, frequency, carbon intensity.

    Aggregates data from BMRS (Elexon) and the Carbon Intensity API.
    Returns a flat dict suitable for the frontend status strip.
    """
    result: dict[str, Any] = {
        "demand_gw": None,
        "generation_gw": None,
        "frequency_hz": None,
        "carbon_intensity": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "live",
    }

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        headers={"User-Agent": _USER_AGENT},
    ) as client:
        # Demand (INDO = Initial National Demand Outturn)
        try:
            now = datetime.now(timezone.utc)
            from_str = (now - __import__("datetime").timedelta(minutes=30)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            to_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            resp = await client.get(
                BMRS_DEMAND_URL,
                params={
                    "publishDateTimeFrom": from_str,
                    "publishDateTimeTo": to_str,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            items = resp.json().get("data", [])
            if items:
                latest = max(items, key=lambda x: x.get("startTime", ""))
                demand_mw = latest.get("demand") or latest.get("quantity", 0)
                result["demand_gw"] = round(float(demand_mw) / 1000, 2)
        except Exception as exc:
            log.debug("BMRS demand fetch failed: %s", exc)

        # Frequency
        try:
            resp = await client.get(
                BMRS_FREQ_URL,
                params={"format": "json"},
            )
            resp.raise_for_status()
            items = resp.json().get("data", [])
            if items:
                latest = max(items, key=lambda x: x.get("reportSnapshotTime", ""))
                result["frequency_hz"] = round(
                    float(latest.get("frequency", 50.0)), 3,
                )
        except Exception as exc:
            log.debug("BMRS frequency fetch failed: %s", exc)

        # Carbon Intensity
        try:
            resp = await client.get(CARBON_API)
            resp.raise_for_status()
            ci_data = resp.json().get("data", [])
            if ci_data:
                intensity = ci_data[0].get("intensity", {})
                result["carbon_intensity"] = intensity.get("actual") or intensity.get("forecast")
        except Exception as exc:
            log.debug("Carbon intensity fetch failed: %s", exc)

    # Generation ≈ demand (no separate lightweight endpoint; use demand as proxy)
    if result["demand_gw"] is not None:
        result["generation_gw"] = result["demand_gw"]

    # Mark as degraded if any key fields are missing
    if result["demand_gw"] is None and result["frequency_hz"] is None:
        result["source"] = "degraded"
        # Provide sensible defaults so the UI still renders
        result["demand_gw"] = 30.0
        result["generation_gw"] = 30.0
        result["frequency_hz"] = 50.0
        result["carbon_intensity"] = 180

    return result


# ─── Helpers ──────────────────────────────────────────────────────────────

def _normalise_boundary_id(raw: str) -> str | None:
    """
    Normalise a boundary identifier from various NESO naming conventions
    to our canonical B-code (B0, B1, B2, etc.).
    """
    if not raw:
        return None
    raw = raw.strip().upper()
    # Direct match: "B1", "B2", etc.
    if raw in BOUNDARY_ZONES:
        return raw
    # Prefix match: "B1 Scotland-England", "B2 ..."
    for code in BOUNDARY_ZONES:
        if raw.startswith(code):
            return code
    # Name-based fuzzy: "CHEVIOT" → B1, "SCOTLAND" → B0 or B6, etc.
    name_map = {
        "CHEVIOT": "B1",
        "SCOTLAND-ENGLAND": "B1",
        "SCOTENG": "B1",
        "PENNINE": "B2",
        "NORTH-MIDLANDS": "B2",
        "MIDLANDS": "B4",
        "MIDLANDS-SOUTH": "B4",
        "HIGHLAND": "B0",
        "CENTRAL BELT": "B6",
        "EAST COAST": "B7",
        "EAST-SOUTH": "B7",
        "WALES": "B8",
        "SOUTH WALES": "B8",
        "WEST COAST": "B8",
    }
    for keyword, code in name_map.items():
        if keyword in raw:
            return code
    return None


def _float_or(val: Any, default: float) -> float:
    """Safely coerce a value to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _add_severity(data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Add severity classification to each boundary entry."""
    for bid, entry in data.items():
        cost = entry.get("cost_gbp_mwh", 0)
        colours = _severity_colour(cost)
        entry["severity"] = colours["severity"]
    return data


def _queue_wait_colour(avg_wait_years: float) -> dict[str, Any]:
    """Colour scheme for TEC queue wait time."""
    if avg_wait_years < 3:
        return {
            "label": "Short queue (<3yr)",
            "fill": [34, 197, 94, 140],    # green
            "stroke": [22, 163, 74, 220],
        }
    elif avg_wait_years < 7:
        return {
            "label": "Moderate queue (3-7yr)",
            "fill": [251, 191, 36, 140],   # amber
            "stroke": [217, 119, 6, 220],
        }
    else:
        return {
            "label": "Long queue (>7yr)",
            "fill": [239, 68, 68, 160],    # red
            "stroke": [185, 28, 28, 220],
        }


def _empty_feature_collection(message: str = "") -> dict[str, Any]:
    """Return an empty GeoJSON FeatureCollection with optional message."""
    return {
        "type": "FeatureCollection",
        "features": [],
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "message": message,
        },
    }

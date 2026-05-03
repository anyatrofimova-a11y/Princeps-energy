"""
Agentic AI Chat — multi-turn conversational panel with Claude tool use.

Session-based, streaming SSE responses with tool call transparency.
Reuses existing backend utilities (SAM, grid, pricing, planning, etc.).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from typing import Any

import anthropic
import pandas as pd

log = logging.getLogger("princeps.chat")

# ---------------------------------------------------------------------------
# Session storage — in-memory cache + PostgreSQL write-through
# ---------------------------------------------------------------------------

# Optional pool — set via ``init_pool()`` at startup so we can persist.
_pool = None


def init_pool(pool) -> None:
    """Set the asyncpg pool for write-through persistence."""
    global _pool
    _pool = pool


@dataclass
class ChatSession:
    id: str
    messages: list[dict] = field(default_factory=list)
    parcel_id: str | None = None
    # BOT-CHC 2026-04-19 — session remembers the project it was born under
    # and the most recent UI snapshot the frontend sent. Either may be None.
    project_id: str | None = None
    ui_context: dict | None = None
    # Project summary hydrated once at session create from /api/v1/projects/{id}
    # so turn-1 system prompt has name/tech/capacity/stage/DNO/TEC even if the
    # frontend page_context hasn't landed yet.
    project_summary: dict | None = None
    uploaded_files: list[dict] = field(default_factory=list)
    map_layers: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


_sessions: dict[str, ChatSession] = {}


async def _db_persist_session(session: ChatSession) -> None:
    """Write-through session to chat_sessions table (best-effort)."""
    if _pool is None:
        return
    try:
        # Strip non-serialisable uploaded_files.content_bytes before persisting
        safe_messages = json.dumps(session.messages, default=str)
        parcel_uuid = None
        if session.parcel_id:
            try:
                from uuid import UUID as _UUID
                parcel_uuid = _UUID(session.parcel_id)
            except (ValueError, TypeError):
                pass
        await _pool.execute(
            """INSERT INTO chat_sessions (session_id, parcel_id, messages, updated_at)
               VALUES ($1, $2, $3::jsonb, NOW())
               ON CONFLICT (session_id) DO UPDATE SET
                 messages = EXCLUDED.messages,
                 updated_at = NOW()""",
            session.id, parcel_uuid, safe_messages,
        )
    except Exception as e:
        log.warning("Failed to persist chat session %s: %s", session.id, e)


def create_session(
    parcel_id: str | None = None,
    project_id: str | None = None,
) -> ChatSession:
    sid = uuid.uuid4().hex[:12]
    session = ChatSession(id=sid, parcel_id=parcel_id, project_id=project_id)
    _sessions[sid] = session
    # Fire-and-forget persistence
    if _pool is not None:
        asyncio.ensure_future(_db_persist_session(session))
    return session


def get_session(session_id: str) -> ChatSession | None:
    return _sessions.get(session_id)


async def hydrate_project_summary(
    session: ChatSession,
    project_id: str,
    pool,
) -> dict | None:
    """
    BOT-CHC 2026-04-19 — pre-fetch project name/tech/capacity/stage/DNO/TEC/lat/lon
    and stash on ``session.project_summary`` so build_system_prompt can render a
    "You are currently viewing project: …" block from turn 1, before any
    page_context arrives over the wire.

    Best-effort: returns None on any failure; never raises.
    """
    if not project_id or pool is None:
        return None
    try:
        from uuid import UUID as _UUID
        try:
            pid = _UUID(project_id)
        except (ValueError, TypeError):
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM projects WHERE project_id = $1", pid,
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
        summary = {
            "id": str(row["project_id"]),
            "name": row["name"],
            "technology": row["technology"],
            "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] else None,
            "stage": row["stage"],
            "verdict": row["verdict"],
            "lat": float(row["lat"]) if row["lat"] else None,
            "lon": float(row["lon"]) if row["lon"] else None,
            "dno": meta.get("dno"),
            "tec_mw": meta.get("tec_mw") or meta.get("tec_capacity_mw"),
        }
        session.project_summary = summary
        return summary
    except Exception as e:
        log.warning("hydrate_project_summary(%s) failed: %s", project_id, e)
        return None


# ---------------------------------------------------------------------------
# Tool definitions for Claude
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "run_solar_yield",
        "description": "Run a PvWatts v8 solar simulation via NREL SAM for a location. Returns annual energy (kWh), capacity factor, and monthly breakdown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "capacity_kw": {"type": "number", "description": "System capacity in kW", "default": 100},
                "tilt": {"type": "number", "description": "Panel tilt in degrees", "default": 25},
                "azimuth": {"type": "number", "description": "Panel azimuth in degrees (180=south)", "default": 180},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "get_site_context",
        "description": "Get full feasibility context for a site parcel including scores, overlays, grid connection, slope. Requires a parcel_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "parcel_id": {"type": "string", "description": "UUID of the site parcel"},
            },
            "required": ["parcel_id"],
        },
    },
    {
        "name": "create_site_parcel",
        "description": "Create a new site parcel from a lat/lon location. Returns parcel_id and basic site info.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "area_m2": {"type": "number", "description": "Approximate site area in m²", "default": 50000},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "get_grid_connection",
        "description": "Get grid connection info for a parcel: nearest substation, distance, capacity, connection cost estimate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "parcel_id": {"type": "string", "description": "UUID of the site parcel"},
                "capacity_kw": {"type": "number", "description": "Proposed system capacity in kW", "default": 100},
            },
            "required": ["parcel_id"],
        },
    },
    {
        "name": "run_power_flow",
        "description": "Run a Tier 2 pandapower Newton-Raphson power flow simulation. Analyses voltage impact, thermal loading, and N-1 contingency for connecting generation at a specific location. Returns voltage deviation, line loading, losses, and connection feasibility verdict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Site latitude (WGS84)"},
                "lon": {"type": "number", "description": "Site longitude (WGS84)"},
                "capacity_mw": {"type": "number", "description": "Proposed generation capacity in MW", "default": 50},
                "technology": {"type": "string", "description": "Technology type: solar, wind, bess", "default": "solar"},
                "substation_id": {"type": "string", "description": "Optional: specific substation ID to connect to"},
                "contingency": {"type": "boolean", "description": "Run N-1 contingency analysis", "default": False},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "run_financial_analysis",
        "description": "Run energy price forecast and revenue estimation for a solar system. Returns 24h price forecast and estimated annual revenue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude"},
                "lon": {"type": "number", "description": "Longitude"},
                "capacity_kw": {"type": "number", "description": "System capacity in kW", "default": 100},
                "day_of_year": {"type": "integer", "description": "Day of year for price profile", "default": 172},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "get_energy_prices",
        "description": "Get current Octopus Agile energy pricing overview including current rate, daily stats, and regional comparison.",
        "input_schema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "description": "DNO region code (e.g. 'C' for South England)", "default": "C"},
            },
        },
    },
    {
        "name": "get_demand_forecast",
        "description": "Get UK national electricity demand forecast with peak/off-peak analysis and storage simulation.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "query_planning_apps",
        "description": "Query energy-related planning applications. Can filter by category, status, and search text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Energy category filter (e.g. 'solar', 'wind', 'battery')"},
                "status": {"type": "string", "description": "Application status filter"},
                "search": {"type": "string", "description": "Free text search"},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
            },
        },
    },
    {
        "name": "run_bipv_analysis",
        "description": "Calculate Building-Integrated PV performance for a surface. Returns energy yield, cost savings, and payback period.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude"},
                "lon": {"type": "number", "description": "Longitude"},
                "area_m2": {"type": "number", "description": "Surface area in m²", "default": 50},
                "surface_type": {"type": "string", "description": "Surface type: flat_roof, pitched_roof_south, pitched_roof_east, pitched_roof_west, facade_south, facade_east, facade_west", "default": "pitched_roof_south"},
                "module_type": {"type": "string", "description": "BIPV module: mono_roof_tile, thin_film_facade, solar_glass, colored_facade, flexible_membrane, shingle", "default": "mono_roof_tile"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "get_inventory_bom",
        "description": "Generate a Bill of Materials for a solar installation at a parcel. Lists panels, inverters, mounting, cabling, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "parcel_id": {"type": "string", "description": "UUID of the site parcel"},
                "capacity_kw": {"type": "number", "description": "System capacity in kW", "default": 100},
            },
            "required": ["parcel_id"],
        },
    },
    {
        "name": "search_substations",
        "description": "Search for electrical substations within a radius of a point. Returns list with name, capacity, distance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Centre latitude"},
                "lon": {"type": "number", "description": "Centre longitude"},
                "radius_km": {"type": "number", "description": "Search radius in km", "default": 10},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "get_grid_live",
        "description": "Get live UK National Grid generation mix data — real-time fuel type breakdown (gas, wind, solar, nuclear, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "search_nged_network",
        "description": "Search NGED distribution network for substations with available connection headroom near a location. Returns substations ranked by spare capacity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Centre latitude"},
                "lon": {"type": "number", "description": "Centre longitude"},
                "radius_km": {"type": "number", "description": "Search radius in km", "default": 15},
                "min_headroom_mw": {"type": "number", "description": "Minimum spare capacity in MW", "default": 1.0},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "create_map_layer",
        "description": (
            "Create a GeoJSON layer on the map. Supports multiple visualisation styles:\n"
            "- circle: Point markers (default)\n"
            "- fill: Solid polygon fills with optional data-driven colour\n"
            "- fill-pattern: Hatched/patterned polygons for constraint zones (flood risk, AONB, green belt). "
            "Available patterns: hatch-blue, hatch-red, hatch-green, hatch-amber, hatch-grey, crosshatch-red, crosshatch-blue\n"
            "- symbol: Icon-based points. Available icons: substation, exchange, hazard, optimal-site, power-source, flight-path, fibre-pop, flood-zone. "
            "Set style.icon to the icon name. Use style.icon_field to pick icon per feature from a GeoJSON property.\n"
            "- line: Polylines with optional dashing and per-feature colour. Set style.dash_array for dashed lines (e.g. [4,3]).\n"
            "- heatmap: Heat density visualisation\n\n"
            "For data-driven colours on circle/line layers, set style.color_field and style.color_map (e.g. {\"Supplier1\": \"#2196F3\", \"Supplier2\": \"#9C27B0\"})."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name for the layer"},
                "geojson": {
                    "type": "object",
                    "description": "GeoJSON FeatureCollection to render on the map",
                },
                "layer_type": {
                    "type": "string",
                    "enum": ["circle", "fill", "fill-pattern", "symbol", "line", "heatmap"],
                    "description": "Map layer rendering type",
                    "default": "circle",
                },
                "color": {"type": "string", "description": "Primary colour for the layer", "default": "#00e5ff"},
                "style": {
                    "type": "object",
                    "description": "Advanced styling options",
                    "properties": {
                        "icon": {"type": "string", "description": "Icon name for symbol layers (e.g. 'substation', 'hazard')"},
                        "icon_field": {"type": "string", "description": "GeoJSON property to pick icon per feature"},
                        "icon_size": {"type": "number", "description": "Icon scale (default 0.55)"},
                        "label_field": {"type": "string", "description": "GeoJSON property to use as text label"},
                        "pattern": {"type": "string", "description": "Fill pattern name for fill-pattern layers"},
                        "dash_array": {"type": "array", "items": {"type": "number"}, "description": "Line dash pattern [dash, gap]"},
                        "line_width": {"type": "number", "description": "Line width in pixels"},
                        "line_cap": {"type": "string", "enum": ["butt", "round", "square"]},
                        "color_field": {"type": "string", "description": "GeoJSON property for data-driven colour"},
                        "color_map": {"type": "object", "description": "Mapping of property values to colours"},
                        "opacity": {"type": "number", "description": "Layer opacity 0-1"},
                        "radius": {"type": "number", "description": "Circle radius in pixels"},
                    },
                },
            },
            "required": ["name", "geojson"],
        },
    },
    {
        "name": "zoom_to_location",
        "description": "Zoom the map to a specific location. Use this ALWAYS when you mention, identify, or discuss a geographic location, site, substation, or area — even if you also create a map layer. This ensures the user can see what you're talking about.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "zoom": {"type": "number", "description": "Map zoom level (1-20, default 14)", "default": 14},
                "label": {"type": "string", "description": "Optional label to show on the map at this location"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "process_uploaded_file",
        "description": "Analyse an uploaded file (CSV or Excel). Returns column info, row count, summary statistics, and detected energy-related fields.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Name of the uploaded file to process"},
            },
            "required": ["filename"],
        },
    },
    {
        "name": "query_energy_scenario",
        "description": "Run a UK energy system scenario analysis — shows how a site fits in the national energy context with capacity mix and carbon impact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "capacity_kw": {"type": "number", "description": "Site capacity in kW", "default": 100},
                "technology": {"type": "string", "description": "Technology type: solar, wind, battery", "default": "solar"},
            },
        },
    },
    {
        "name": "get_electricity_map",
        "description": "Get real-time electricity carbon intensity and power generation breakdown for a European zone from Electricity Maps. Useful for comparing grid cleanliness across countries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone": {"type": "string", "description": "Electricity Maps zone code (e.g. 'GB', 'DE', 'FR', 'ES', 'NL', 'DK-DK1', 'NO-NO1')"},
                "metric": {"type": "string", "enum": ["carbon_intensity", "power_breakdown", "both"], "description": "Which data to fetch", "default": "both"},
            },
            "required": ["zone"],
        },
    },
    {
        "name": "run_satellite_analysis",
        "description": "Run satellite Earth observation analysis using Google Earth Engine (GeeFlow). Extracts land use (DynamicWorld 10m), terrain (NASADEM), solar resource (ERA5), vegetation (Sentinel-2 NDVI), SAR backscatter (Sentinel-1), flood risk (JRC), and NDVI timeseries for a location. Returns a background job ID for polling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "radius_km": {"type": "number", "description": "Analysis radius in km", "default": 5},
                "modes": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["land_use", "terrain", "solar_resource", "vegetation", "change_detection", "site_composite", "sar_backscatter", "flood_risk", "ndvi_timeseries"]},
                    "description": "Extraction modes to run",
                    "default": ["land_use", "terrain", "solar_resource", "vegetation"],
                },
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "score_tender_sites",
        "description": "Score multiple candidate sites for a tender using satellite data, grid connection data, and planning records. Returns sites ranked by composite suitability score (0-100) with GO/CAUTION/NO-GO recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sites": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Site name or identifier"},
                            "lat": {"type": "number", "description": "Latitude (WGS84)"},
                            "lon": {"type": "number", "description": "Longitude (WGS84)"},
                        },
                        "required": ["name", "lat", "lon"],
                    },
                    "description": "List of candidate sites to score",
                },
                "technology": {"type": "string", "enum": ["solar", "battery", "wind"], "description": "Target technology", "default": "solar"},
            },
            "required": ["sites"],
        },
    },
    {
        "name": "query_legacy_assets",
        "description": "Query legacy energy assets (solar farms, wind farms, substations, batteries) near a location. Returns asset details, condition scores, and lifecycle status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "radius_km": {"type": "number", "description": "Search radius in km", "default": 25},
                "asset_type": {"type": "string", "description": "Filter by type: solar_farm, wind_farm, battery_storage, substation"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "run_geoai_analysis",
        "description": "Run GeoAI deep learning analysis: building footprints, solar panels, change detection, land cover, canopy height, asset condition, cloud masking, super-resolution, foundation embeddings (Prithvi), patch similarity (DINOv3), site captioning (Moondream), infrastructure detection (GroundedSAM), or enhanced change detection (torchange).",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "mode": {
                    "type": "string",
                    "enum": ["building_footprints", "solar_panel_detect", "change_detection", "land_cover", "canopy_height", "asset_condition", "cloud_mask", "super_resolution", "foundation_embeddings", "patch_similarity", "site_caption", "infrastructure_detect", "enhanced_change"],
                    "description": "Analysis mode",
                    "default": "asset_condition",
                },
                "radius_km": {"type": "number", "description": "Analysis radius in km", "default": 2.0},
                "asset_type": {"type": "string", "description": "Asset type for condition assessment", "default": "solar_farm"},
                "satellite": {"type": "string", "enum": ["sentinel2", "landsat8"], "description": "Satellite for cloud_mask mode", "default": "sentinel2"},
                "model_size": {"type": "string", "enum": ["tiny", "small", "base", "100M-TL", "300M-TL", "600M-TL"], "description": "Prithvi model size for foundation_embeddings", "default": "100M-TL"},
                "ref_lat": {"type": "number", "description": "Reference latitude for patch_similarity mode"},
                "ref_lon": {"type": "number", "description": "Reference longitude for patch_similarity mode"},
                "targets": {"type": "string", "description": "Comma-separated detection targets for infrastructure_detect", "default": "pylons,substations,solar_panels,wind_turbines"},
                "questions": {"type": "string", "description": "Comma-separated questions for site_caption VQA"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "assess_asset_lifecycle",
        "description": "Get lifecycle assessment for an energy asset including compliance milestones, repowering analysis, and decommissioning estimate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_type": {"type": "string", "enum": ["solar_farm", "wind_farm", "battery_storage", "substation", "transformer", "inverter"], "default": "solar_farm"},
                "commissioning_date": {"type": "string", "description": "Commissioning date (YYYY-MM-DD)"},
                "capacity_kw": {"type": "number", "description": "Installed capacity in kW", "default": 100},
            },
            "required": ["commissioning_date"],
        },
    },
    {
        "name": "score_candidate_site_prospector",
        "description": "Score a candidate site for energy development potential using multi-criteria analysis (resource quality, terrain, land use, grid access, planning/environment). Returns 0-100 score with component breakdown and recommendation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "technology": {"type": "string", "enum": ["solar", "solar_pv", "wind", "wind_onshore", "battery"], "default": "solar"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "scan_region_for_sites",
        "description": "Scan a UK region for new energy site opportunities. Generates and scores a grid of candidate points. Returns ranked list with top sites.",
        "input_schema": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "enum": ["south_east", "south_west", "east_anglia", "midlands", "wales", "north_west", "north_east", "scotland_central", "scotland_north"], "default": "south_west"},
                "technology": {"type": "string", "enum": ["solar", "wind", "battery"], "default": "solar"},
                "grid_points": {"type": "integer", "description": "Number of candidate points to evaluate", "default": 25},
            },
        },
    },
    {
        "name": "find_similar_sites",
        "description": "Find sites similar to a reference location for energy development. Uses multi-dimensional feature matching across terrain, resource, and grid access.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Reference latitude (WGS84)"},
                "lon": {"type": "number", "description": "Reference longitude (WGS84)"},
                "radius_km": {"type": "number", "description": "Search radius in km", "default": 50},
                "technology": {"type": "string", "enum": ["solar", "wind", "battery"], "default": "solar"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "estimate_grid_losses",
        "description": "Estimate transmission/distribution line losses for a grid connection. Considers voltage level, distance, and loading factor.",
        "input_schema": {
            "type": "object",
            "properties": {
                "distance_km": {"type": "number", "description": "Line distance in km"},
                "voltage_kv": {"type": "number", "description": "Voltage level in kV (e.g. 11, 33, 132, 275, 400)"},
                "load_mw": {"type": "number", "description": "Power flow in MW"},
                "capacity_mva": {"type": "number", "description": "Line capacity in MVA"},
            },
            "required": ["distance_km", "voltage_kv", "load_mw"],
        },
    },
    {
        "name": "assess_substation_health",
        "description": "Assess health of substations using age, utilisation, and satellite condition data. Returns health score and issues.",
        "input_schema": {
            "type": "object",
            "properties": {
                "substations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "capacity_mva": {"type": "number"},
                            "headroom_mw": {"type": "number"},
                            "age_years": {"type": "number"},
                        },
                    },
                    "description": "List of substations to assess",
                },
            },
            "required": ["substations"],
        },
    },
    {
        "name": "check_environmental_constraints",
        "description": "Check all environmental, flood, and heritage constraints at a UK location. Queries Natural England designations (SSSI, SAC, SPA, AONB, National Parks, Ramsar), Environment Agency flood zones, and Historic England listed buildings. Returns risk level, planning impact, and constraint map layers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "radius_m": {"type": "number", "description": "Search radius in metres", "default": 2000},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "get_procurement_pipeline",
        "description": "Get procurement pipeline analytics — tender counts by technology, total value, urgent deadlines, and cost benchmarks.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "assess_bid_viability",
        "description": "Assess viability of bidding on an energy tender. Returns score (0-100) with STRONG_BID / CONDITIONAL_BID / NO_BID recommendation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Tender title"},
                "description": {"type": "string", "description": "Tender description"},
                "value_gbp": {"type": "number", "description": "Contract value in GBP"},
                "deadline": {"type": "string", "description": "Tender deadline (ISO date)"},
                "site_score": {"type": "number", "description": "Site suitability score (0-100)"},
                "grid_headroom_mw": {"type": "number", "description": "Available grid headroom in MW"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "run_vision_analysis",
        "description": "Analyse site imagery using Vision AI. Fetches a satellite screenshot and runs Claude Vision instant analysis to assess terrain, shading, access, vegetation, and suitability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude"},
                "lon": {"type": "number", "description": "Longitude"},
                "image_type": {"type": "string", "description": "Image type: satellite, drone, aerial", "default": "satellite"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "assess_home_retrofit",
        "description": "Run a UK residential home retrofit assessment using case-based reasoning. Matches the property to similar approved projects, generates retrofit option packages (Quick Wins, Fabric First, Extension+Energy, Full Retrofit), estimates costs, energy savings, EPC improvement, and planning routes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "house_type": {"type": "string", "description": "House archetype: victorian_terrace_mid, victorian_terrace_end, edwardian_semi, 1930s_semi, 1930s_detached, 1950s_semi, 1960s_detached, 1970s_bungalow, 1980s_semi, 1990s_detached, 2000s_townhouse, modern_newbuild", "default": "1930s_semi"},
                "plot_width_m": {"type": "number", "description": "Plot width in metres", "default": 8.0},
                "plot_depth_m": {"type": "number", "description": "Plot depth in metres", "default": 25.0},
                "storeys": {"type": "integer", "description": "Number of storeys", "default": 2},
                "epc_rating": {"type": "string", "description": "Current EPC rating (A-G)", "default": "D"},
                "heating": {"type": "string", "description": "Heating system: gas_boiler, gas_combi, oil_boiler, electric_storage, ashp, gshp, lpg", "default": "gas_boiler"},
                "conservation": {"type": "boolean", "description": "In a conservation area?", "default": False},
                "listed": {"type": "string", "description": "Listed building grade: I, II*, II, or null"},
                "budget_gbp": {"type": "number", "description": "Optional budget constraint in GBP"},
                "lat": {"type": "number", "description": "Latitude"},
                "lon": {"type": "number", "description": "Longitude"},
            },
            "required": ["house_type"],
        },
    },
    {
        "name": "assess_dc_colocation",
        "description": "Assess a site for data centre co-location suitability. Scores 9 dimensions (power capacity, REAL grid headroom from all 6 UK DNOs, fibre proximity, IXP proximity, water cooling, latency, land/planning, resilience, connection speed). Returns DC-SCORE (0-100) with GO/CAUTION/NO-GO verdict, proximity matrix, gate compliance, and connection cost estimate. Unlike competitors, headroom values are REAL — not N/A.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "capacity_mw": {"type": "number", "description": "Required IT load in MW", "default": 10},
                "profile": {"type": "string", "enum": ["google_hyperscale", "hyperscale", "colocation", "edge", "custom"], "description": "Facility profile", "default": "colocation"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "score_dc_site_extended",
        "description": "Extended 15-dimension DC site scoring including 24/7 CFE%, cooling (PUE/WUE), constraint overlay (SSSI/AONB/Green Belt), water stress, incentives (Enterprise Zones/Freeports), and regulatory pathway (NSIP/TM04+). Use for Google hyperscale assessments requiring full analysis. Returns DC-SCORE with all 15 dimension breakdowns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "capacity_mw": {"type": "number", "description": "Required IT load in MW", "default": 100},
                "profile": {"type": "string", "enum": ["google_hyperscale", "hyperscale", "colocation", "edge"], "description": "Facility profile", "default": "google_hyperscale"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "compare_dc_sites",
        "description": "Compare multiple candidate sites for data centre suitability across all 15 dimensions. Returns ranked sites with radar chart data, dimension-by-dimension comparison, and recommendation. Ideal for shortlisting between 2-6 candidate locations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sites": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "lat": {"type": "number"}, "lon": {"type": "number"}}, "required": ["lat", "lon"]}, "description": "Candidate sites to compare"},
                "capacity_mw": {"type": "number", "description": "Required IT load in MW", "default": 100},
                "profile": {"type": "string", "default": "google_hyperscale"},
            },
            "required": ["sites"],
        },
    },
    {
        "name": "search_colocation_opportunities",
        "description": "Search for co-location opportunities by linking grid substations with available land parcels, REPD stalled projects, landowner companies, and ALC grades. Returns ranked opportunities where grid headroom + land + ownership align. Use when asked about finding sites, land availability, co-location, behind-the-meter, or where to build.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Search centre latitude"},
                "lon": {"type": "number", "description": "Search centre longitude"},
                "radius_km": {"type": "number", "description": "Search radius in km", "default": 10},
                "technology": {"type": "string", "enum": ["solar", "wind", "bess", "data_centre"], "default": "solar"},
                "min_capacity_mw": {"type": "number", "description": "Minimum grid headroom MW", "default": 5},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "benchmark_lease_rate",
        "description": "Benchmark a land lease rate against UK market data (Knight Frank / Savills / RICS 2024-25). Returns low/mid/high rates by technology, ALC grade, and UK region. Use when asked about land costs, rental rates, lease terms, or whether a deal is fair.",
        "input_schema": {
            "type": "object",
            "properties": {
                "technology": {"type": "string", "enum": ["solar", "wind", "bess", "data_centre"], "default": "solar"},
                "alc_grade": {"type": "string", "description": "ALC grade e.g. Grade 3b", "default": "Grade 3b"},
                "region": {"type": "string", "description": "UK region e.g. South East, Midlands", "default": "default"},
                "area_ha": {"type": "number", "description": "Site area in hectares", "default": 10},
            },
        },
    },
    {
        "name": "match_landowner",
        "description": "Fuzzy-match a landowner name to Companies House entities near a location. Uses Levenshtein distance + token overlap. Use when asked about who owns land, finding the landowner company, or connecting a name to a registered entity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "landowner_name": {"type": "string", "description": "Landowner name to search for"},
                "lat": {"type": "number", "description": "Search centre latitude"},
                "lon": {"type": "number", "description": "Search centre longitude"},
                "radius_km": {"type": "number", "default": 5},
            },
            "required": ["landowner_name", "lat", "lon"],
        },
    },
    {
        "name": "find_dc_sites",
        "description": "AI-driven site discovery for data centres. Scans substations with adequate headroom and scores them with the full 15-dimension engine. Use natural language queries like 'Find 200+ acre sites near London with >100MW'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language site criteria"},
                "capacity_mw": {"type": "number", "default": 100},
                "min_headroom_mw": {"type": "number", "default": 50},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "analyse_land_suitability",
        "description": "Analyse land suitability for energy development using satellite imagery and spectral analysis. Returns suitability score, spectral indices, and development recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude"},
                "lon": {"type": "number", "description": "Longitude"},
                "radius_m": {"type": "number", "description": "Analysis radius in metres", "default": 500},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "forecast_grid_connection",
        "description": (
            "Predict when a developer will receive a grid connection offer and at what cost, "
            "BEFORE they apply. Uses real TEC gate data, ECR queue depth, substation headroom, "
            "and REPD historical outcomes. Returns time-to-offer (months), likely voltage, "
            "reinforcement cost, queue position, P10/P50/P90 connection cost, risk factors, "
            "recommended substations, and historical comparisons from nearby projects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "capacity_mw": {"type": "number", "description": "Proposed capacity in MW", "default": 50},
                "technology": {
                    "type": "string",
                    "description": "Technology type: solar, wind, battery",
                    "default": "solar",
                },
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "score_planning_risk",
        "description": "Score planning risk for a proposed energy site. Checks REPD outcomes, residential proximity, agricultural land classification, grid queue congestion, environmental designations, and technology-specific risk. Returns 0-100 risk score with GO/CAUTION/NO-GO verdict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "capacity_mw": {"type": "number", "description": "Proposed capacity in MW", "default": 10},
                "technology": {"type": "string", "description": "Technology type: solar, wind, battery, bess, hydrogen", "default": "solar"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "batch_screen_sites",
        "description": "Batch screen multiple candidate sites for energy development. Scores each site on grid headroom, planning risk, solar resource, land suitability, and constraint cost. Returns ranked shortlist with composite scores.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "description": "List of candidate sites to screen",
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"},
                            "capacity_mw": {"type": "number", "default": 10},
                            "technology": {"type": "string", "default": "solar"},
                            "name": {"type": "string"},
                        },
                        "required": ["lat", "lon"],
                    },
                },
                "top_n": {"type": "integer", "description": "Return top N sites", "default": 20},
            },
            "required": ["candidates"],
        },
    },
    {
        "name": "calculate_shadow_flicker",
        "description": "Calculate shadow flicker from wind turbines on nearby receptors (dwellings). Models hourly blade shadow patterns for 365 days. UK threshold: 30 hrs/year, 30 min/day. Auto-detects receptors from PostGIS if none provided.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Site latitude (WGS84)"},
                "lon": {"type": "number", "description": "Site longitude (WGS84)"},
                "turbine_specs": {
                    "type": "object",
                    "description": "Turbine specifications",
                    "properties": {
                        "hub_height_m": {"type": "number", "default": 80},
                        "rotor_diameter_m": {"type": "number", "default": 100},
                        "count": {"type": "integer", "default": 1},
                        "positions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "lat": {"type": "number"},
                                    "lon": {"type": "number"},
                                },
                            },
                        },
                    },
                },
                "receptors": {
                    "type": "array",
                    "description": "Receptor locations (houses, roads). If empty, auto-detected from DB.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"},
                            "name": {"type": "string"},
                            "height_m": {"type": "number", "default": 6},
                        },
                    },
                },
            },
            "required": ["lat", "lon", "turbine_specs"],
        },
    },
    {
        "name": "calculate_glint_glare",
        "description": "Calculate glint-glare from solar panels towards nearby receptors. Models specular reflection using hourly solar geometry for 365 days. Checks reflected beam intersection within 2-degree cone. Auto-detects receptors if none provided.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Site latitude (WGS84)"},
                "lon": {"type": "number", "description": "Site longitude (WGS84)"},
                "panel_specs": {
                    "type": "object",
                    "description": "Solar panel specifications",
                    "properties": {
                        "tilt_deg": {"type": "number", "default": 25},
                        "azimuth_deg": {"type": "number", "default": 180},
                        "width_m": {"type": "number", "default": 2},
                        "height_m": {"type": "number", "default": 1},
                        "area_ha": {"type": "number", "default": 20},
                        "reflectivity": {"type": "number", "default": 0.05},
                    },
                },
                "receptors": {
                    "type": "array",
                    "description": "Receptor locations. If empty, auto-detected from DB.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "lat": {"type": "number"},
                            "lon": {"type": "number"},
                            "name": {"type": "string"},
                            "height_m": {"type": "number", "default": 6},
                            "is_aviation": {"type": "boolean", "default": False},
                        },
                    },
                },
            },
            "required": ["lat", "lon", "panel_specs"],
        },
    },
    {
        "name": "estimate_energisation_timeline",
        "description": "Predict total months from application to first power export for a proposed energy project. Models 5 phases: pre-application, planning, connection offer, connection works, commissioning. Uses REPD benchmarks, ECR queue depth, and DNO processing times.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "capacity_mw": {"type": "number", "description": "Proposed capacity in MW", "default": 50},
                "technology": {"type": "string", "description": "Technology: solar, wind, bess, solar+bess", "default": "solar"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "search_nearby_companies",
        "description": "Search Companies House for land/property/agriculture/energy companies near a location. Useful for identifying potential landowners, site operators, or local energy companies for outreach. Filters by relevant SIC codes and returns relevance-scored results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "radius_km": {"type": "number", "description": "Search radius in km", "default": 5},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "check_nsip_conflicts",
        "description": "Check for Nationally Significant Infrastructure Projects (NSIP) near a location. NSIPs are large energy projects (>50MW solar, >100MW wind, nuclear, data centres) using the DCO process. Identifies competing grid connections, cumulative impact risks, and planning precedent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "radius_km": {"type": "number", "description": "Search radius in km", "default": 20},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "calculate_noise_contours",
        "description": "Calculate ISO 9613-2 noise propagation contours for energy infrastructure (wind turbines, BESS inverters, transformers). Returns GeoJSON noise contour polygons at 35/40/45/50/55 dB(A) and compliance assessment against UK planning limits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "description": "Noise sources: [{type: 'wind_turbine'|'bess_inverter'|'transformer', lat, lon, power_level_dba?, hub_height_m?/height_m?}]",
                    "items": {"type": "object"},
                },
                "compliance_limit_dba": {"type": "number", "description": "Compliance limit in dB(A)", "default": 40},
                "study_radius_m": {"type": "number", "description": "Study area radius in metres", "default": 2000},
                "tonal_penalty": {"type": "boolean", "description": "Apply +5dB tonal penalty", "default": False},
            },
            "required": ["sources"],
        },
    },
    {
        "name": "generate_construction_schedule",
        "description": "Generate a parametric construction schedule for a solar, wind, or BESS energy project. Returns phases with durations, workforce, HGV counts, and cost breakdown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "capacity_mw": {"type": "number", "description": "Project capacity in MW"},
                "technology": {"type": "string", "description": "Technology: solar, wind, bess", "default": "solar"},
                "site_area_ha": {"type": "number", "description": "Site area in hectares"},
                "grid_distance_km": {"type": "number", "description": "Grid connection distance in km"},
            },
            "required": ["capacity_mw"],
        },
    },
    {
        "name": "estimate_construction_traffic",
        "description": "Estimate construction traffic impacts for a CTMP (Construction Traffic Management Plan). Returns total HGV movements, peak daily movements, abnormal loads, access road specifications, and mitigation measures.",
        "input_schema": {
            "type": "object",
            "properties": {
                "capacity_mw": {"type": "number", "description": "Project capacity in MW"},
                "technology": {"type": "string", "description": "Technology: solar, wind, bess", "default": "solar"},
                "site_area_ha": {"type": "number", "description": "Site area in hectares"},
                "grid_distance_km": {"type": "number", "description": "Grid connection distance in km"},
            },
            "required": ["capacity_mw"],
        },
    },
    {
        "name": "fetch_lidar_terrain",
        "description": "Fetch high-resolution EA LiDAR 1m terrain data for a UK site. Returns survey-grade heightmap, elevation stats, slope/aspect analysis. Falls back to NASADEM 30m outside England LiDAR coverage. Use for 3D digital twin terrain, solar panel orientation, cut/fill estimation, and wind surface roughness.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "radius_m": {"type": "number", "description": "Study area radius in metres", "default": 500},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "calculate_viewshed",
        "description": "Calculate Zone of Theoretical Visibility (ZTV) for a proposed energy development. Standard UK planning methodology. Shows which areas can see the development from ground level. Returns visible area percentage, GeoJSON polygon for map overlay, visual impact classification, and receptor count estimate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "target_height_m": {"type": "number", "description": "Height of proposed structure in metres (3m solar, 80-150m wind)", "default": 3.0},
                "radius_m": {"type": "number", "description": "Study area radius in metres (2000 solar, 5000-10000 wind)", "default": 2000},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "calculate_hydrology",
        "description": "Hydrological analysis for a site — Topographic Wetness Index, flow accumulation, drainage paths, depression/waterlogging risk. Essential for site drainage design and flood risk assessment in planning applications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "radius_m": {"type": "number", "description": "Study area radius in metres", "default": 500},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "predict_planning_approval",
        "description": "Predict planning approval probability using an ML model trained on 14,000 real UK renewable energy planning outcomes (REPD database). Uses GradientBoosting with spatial features: nearby project density, local authority approval rate, technology, capacity, region. Returns approval probability (0-1), verdict (LIKELY APPROVED / UNCERTAIN / LIKELY REFUSED), risk factors, comparable projects, and model accuracy stats.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "capacity_mw": {"type": "number", "description": "Proposed capacity in MW", "default": 50},
                "technology": {"type": "string", "description": "Technology type: solar, wind, bess, battery, biomass, hydrogen", "default": "solar"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "predict_connection_timeline",
        "description": "Predict grid connection timeline using real ESO TEC gate data from 2,563 transmission projects. Returns P10/P50/P90 month estimates, gate-by-gate breakdown, DNO region comparison, and benchmark against similar projects. Use when developers ask 'how long will grid connection take?' or about connection timelines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "capacity_mw": {"type": "number", "description": "Proposed capacity in MW", "default": 50},
                "technology": {"type": "string", "description": "Technology type: solar, wind, bess, gas, nuclear", "default": "solar"},
                "host_to": {"type": "string", "description": "Host Transmission Owner / DNO region (e.g. NGET, SHET, SPT)"},
            },
            "required": [],
        },
    },
    {
        "name": "benchmark_site",
        "description": "Benchmark a proposed site against 13,995 real UK REPD projects. Shows percentile ranking for grid headroom, grid distance, local project density, approval rate, and capacity. Returns overall percentile, verdict (EXCELLENT/ABOVE AVERAGE/AVERAGE/BELOW AVERAGE/POOR), comparable approved and refused projects, and narrative summary. Use when developers ask 'is this a good site?' or want to compare their site against the UK average.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "capacity_mw": {"type": "number", "description": "Proposed capacity in MW", "default": 50},
                "technology": {"type": "string", "description": "Technology: solar, wind, bess, battery", "default": "solar"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "mutate_design",
        "description": "Edit a single capacity-mix field on a project and return the re-computed KPIs (capex, NPV, IRR, LCOE, utilisation, land usage). Persists to projects.metadata.design. Use when the user says things like 'bump solar to 80MW', 'set PPA price to 65', 'make the battery 20MW/4h'. Returns the new design state and derived KPIs immediately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "UUID of the project"},
                "field": {"type": "string", "description": "Field to set",
                          "enum": ["solar_mw", "bess_mw", "bess_mw_mwh", "bess_hours",
                                   "ppa_price_gbp_mwh", "ppa_share_pct", "workload_mw",
                                   "site_area_ha"]},
                "value": {"type": "number", "description": "New value"},
            },
            "required": ["project_id", "field", "value"],
        },
    },
    {
        "name": "optimize_design",
        "description": "Run scipy SLSQP to find the optimal capacity mix (solar MW, BESS MW, BESS hours, PPA share) that maximises NPV / minimises LCOE / maximises grid utilisation for a project, subject to land area and grid headroom constraints. Returns best params + KPIs + provenance (scipy_slsqp or analytic_fallback).",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "UUID of the project"},
                "objective": {"type": "string", "enum": ["max_npv", "min_lcoe", "max_utilisation"], "default": "max_npv"},
                "bounds": {
                    "type": "object",
                    "description": "Optional tighter bounds, e.g. {\"solar_mw\": [10, 60], \"bess_mw\": [0, 30]}",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "full_project_doc",
        "description": "Fetch the full project document in one call: project record, current design state, derived KPIs, latest finance layout, nearest-substation grid snapshot, nearby planning applications, recent demand, and the last agent assessments. Use this instead of chaining many smaller tool calls when the user asks something broad like 'summarise the project' or 'what's the status?'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "UUID of the project"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_pinned_dockets",
        "description": (
            "Return a compact JSON digest of all regulatory dockets pinned to a Princeps project "
            "(NSIP DCO examinations, Ofgem code mods, LPA planning applications, CfD rounds, s36 "
            "consents, DNO connection cases, etc.). Use this when you need to factor live "
            "regulatory context into a GO/CAUTION/NO-GO verdict, identify deadlines, or surface "
            "key stakeholder positions. Returns an empty list if no dockets are pinned to this "
            "project. Each docket includes case_type, stage, applicant_name, statutory_deadline, "
            "exec_summary_text (≤400 chars), next_deadline, stakeholder_position_breakdown, "
            "timeline_next_3_events, and key_stakeholder_positions (top 5 by submission count)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Princeps project UUID"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "get_dno_engagement_status",
        "description": (
            "Return a compact JSON digest of the project's DNO engagement workflow: the latest "
            "pack version sent, status (drafting/previewing/sent/responded/withdrawn/superseded), "
            "a summary of the most recent DNO response (sentiment, requested_info, proposed_poc, "
            "timeline_revision), any outstanding deadlines derived from the response, and the "
            "delta between the latest response and the previous one (firm/non-firm split change, "
            "timeline shift, POC changes, newly requested info, capacity_mw delta). Use this "
            "when the user asks about connection application status, when the agent needs to "
            "factor DNO feedback into a GO/CAUTION/NO-GO verdict, or when drafting a follow-up "
            "pack. Returns `{latest_pack_version: 0, status: 'none'}` if no pack has ever been "
            "sent for this project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Princeps project UUID"},
            },
            "required": ["project_id"],
        },
    },
    # ──────────────────────────────────────────────────────────────────────
    # BOT-CHT 2026-04-21 — P0 wiring pack. Each tool wraps an existing FastAPI
    # router endpoint or utils module. Handlers call the internal function
    # directly (not HTTP) to avoid the self-request loop.
    # ──────────────────────────────────────────────────────────────────────
    {
        "name": "list_projects",
        "description": (
            "List projects in the user's pipeline (portfolio-tagged projects only by default). "
            "Returns id, name, technology, capacity_mw, stage, verdict, lat, lon, blocker, "
            "portfolio_id. Use this when the user asks 'what projects do I have', 'list my "
            "portfolio', 'show pipeline'. Pipeline scope = portfolio_id IS NOT NULL OR "
            "verdict IS NOT NULL (~26 rows), matching the Pipeline tab and mission control. "
            "The default scope excludes the ~4,600 public REPD/TEC rows — pass source='repd' "
            "or source='all' only if the user explicitly asks for public planning data or a "
            "market-wide search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["pipeline", "repd", "all"], "default": "pipeline", "description": "pipeline = user's own tracked projects (default); repd = public REPD rows only; all = everything"},
                "portfolio_id": {"type": "string", "description": "Filter to a single portfolio UUID"},
                "stage": {"type": "string", "description": "Filter by stage (prospect|screened|grid_applied|grid_offer|planning|fid|construction|energised)"},
                "technology": {"type": "string", "description": "solar|bess|wind|dc|hybrid"},
                "verdict": {"type": "string", "description": "GO|CAUTION|NO-GO"},
                "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 200},
            },
        },
    },
    {
        "name": "get_project",
        "description": (
            "Return full detail for a single project: name, technology, capacity_mw, "
            "stage, verdict, lat/lon, blocker, linked parcels, metadata (DNO, TEC, "
            "queue position, next_action). Wraps GET /api/v1/projects/{id}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Princeps project UUID"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "list_portfolios",
        "description": (
            "List the user's portfolios. Returns id, name, description, created_at. "
            "Wraps GET /api/v1/portfolios."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_portfolio_mission_control",
        "description": (
            "Portfolio-level KPIs: total_projects, total_mw, GO/CAUTION counts, "
            "in_queue count, next filing deadline, active_projects (top 12 by "
            "recency with IRR/grid/planning badges), recent activity. Use when the "
            "user asks 'how is my portfolio doing' or 'mission control'. Wraps "
            "GET /api/portfolios/mission-control."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_substation",
        "description": (
            "Enriched 8-section detail for a substation (identity, electrical, "
            "capacity_state, connections, queue, regulatory, environment, "
            "engineering). Wraps GET /api/grid/substation/{id}/detail. "
            "Accepts an integer substation_id (e.g. 9886 = Imperial Park)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "substation_id": {"type": "integer", "description": "Integer substation id from grid_substations"},
            },
            "required": ["substation_id"],
        },
    },
    {
        "name": "get_project_grid_connection",
        "description": (
            "Tier-1 grid connection summary for a project (by project_id): nearest "
            "substation, distance, headroom, capacity, cost estimate. Uses the "
            "project's stored lat/lon and capacity_mw. For a parcel-based lookup "
            "use get_grid_connection instead. Wraps utils.grid_connection_analyser."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Princeps project UUID"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "list_alerts",
        "description": (
            "List the alert library (Ofgem decisions, DNO updates, policy changes, "
            "etc.) grouped by cluster. Returns id, slug, title, cluster, cadence. "
            "Use when user asks 'what alerts are available' or 'search Ofgem "
            "decisions'. Wraps GET /api/alerts/library. Supports optional free-text "
            "`query` that filters title+slug+cluster client-side."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text filter on title/slug/cluster"},
                "cluster": {"type": "string", "description": "Filter to a single cluster name"},
                "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            },
        },
    },
    {
        "name": "list_dockets",
        "description": (
            "List regulatory dockets (NSIP DCO exams, Ofgem code mods, LPA "
            "planning apps, CfD rounds, s36 consents, DNO cases). Filterable by "
            "case_type, publisher, status, region, free-text. If project_id is "
            "given, limits to dockets pinned to that project. Wraps "
            "GET /api/dockets/library."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "If set, only return dockets pinned to this project"},
                "case_type": {"type": "string", "description": "nsip_dco|ofgem_code_mod|lpa_planning|cfd|s36|dno_case|custom"},
                "publisher": {"type": "string", "description": "Authority slug (e.g. 'ofgem', 'pins')"},
                "status": {"type": "string", "description": "e.g. 'open', 'decided', 'withdrawn'"},
                "region": {"type": "string", "description": "UK region / devolved nation (E/W/S/NI)"},
                "query": {"type": "string", "description": "Free-text filter on title + applicant"},
                "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            },
        },
    },
    {
        "name": "list_repd",
        "description": (
            "Search the UK Renewable Energy Planning Database (REPD) for projects "
            "by technology, status, location, or capacity. Returns a compact list. "
            "Wraps GET /tracker/repd and utils.repd_tracker.query_repd."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tech": {"type": "string", "description": "solar|wind|battery|bess|hybrid"},
                "status": {"type": "string", "description": "e.g. 'Application Approved', 'Operational', 'Under Construction'"},
                "developer": {"type": "string", "description": "Developer/applicant name substring"},
                "near_lat": {"type": "number", "description": "Centre latitude for radius search"},
                "near_lon": {"type": "number", "description": "Centre longitude for radius search"},
                "radius_km": {"type": "number", "default": 25},
                "min_mw": {"type": "number", "description": "Minimum capacity in MW"},
                "limit": {"type": "integer", "default": 25, "minimum": 1, "maximum": 100},
            },
        },
    },
    {
        "name": "get_regulatory_version",
        "description": (
            "Return the current canonical version + publication date + URL of a UK "
            "energy-development standard (G99, G100, NPPF, EN-1, EN-3, BNG, CDM, "
            "etc.). Use this whenever you need to cite a regulation in a response "
            "— never inline a hard-coded issue number. Wraps app.regulatory.versions. "
            "If key is omitted, returns the list of available keys."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Registry key, e.g. 'g99', 'nppf', 'en1', 'bng'"},
            },
        },
    },
    # BOT-CHC 2026-04-19 — lets Claude refresh its view of the current page
    # mid-conversation (e.g. user navigates to a different project without
    # opening a new chat). Returns the live session.ui_context dict.
    {
        "name": "current_page_context",
        "description": (
            "Return the user's current page context (workspace, viewMode, route, "
            "current project {id,name,lat,lon,tech,capacity_mw,stage,dno,tec_mw}, "
            "selected asset, FES pathway, as-of year). Call this whenever you "
            "need to know what page the user is on or which project they are "
            "looking at — do NOT ask the user for coordinates or project details."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    # ──────────────────────────────────────────────────────────────────────
    # BOT-PILL 2026-04-21 — Mission Control chat-pill tools. Each wraps one
    # SQL pass over the pipeline scope (portfolio_id IS NOT NULL OR verdict
    # IS NOT NULL) and returns a pre-ranked list. Claude uses exactly one of
    # these per matching pill prompt — no per-project fan-out.
    # ──────────────────────────────────────────────────────────────────────
    {
        "name": "get_portfolio_risk_scan",
        "description": (
            "Rank the user's pipeline projects by risk right now. Pulls every project "
            "with verdict='CAUTION' or a non-null blocker, ordered by capacity_mw DESC. "
            "Returns name, verdict, blocker, stage, capacity_mw, technology, updated_at. "
            "Use this for 'biggest pipeline risk', 'what's at risk', 'flagged projects'. "
            "Prefer this over list_projects+manual filtering — it's one round-trip."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            },
        },
    },
    {
        "name": "get_recent_activity",
        "description": (
            "Return the last 7 days of portfolio activity: grid_events (substation/ECR "
            "changes), notifications (alerts raised on sites), and projects whose "
            "updated_at falls in the window. Use this for 'this week's activity', "
            "'recent alerts', 'what changed', 'new signals'. Results are three capped "
            "lists (<= 15 each) with detected_at/created_at/updated_at ISO timestamps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 30},
            },
        },
    },
    {
        "name": "list_low_headroom_projects",
        "description": (
            "List pipeline projects whose nearest DNO-published substation has demand "
            "headroom below a threshold (default 10 MW). Joins projects to grid_substations "
            "by lateral nearest-neighbour on PostGIS geom, filtering to rows where "
            "demand_headroom_mw IS NOT NULL (excludes OSM positional rows). Returns project "
            "name, capacity_mw, nearest substation name/dno/voltage, distance_km, "
            "demand_headroom_mw. Use this for 'low headroom sites', 'constrained substations', "
            "'projects on tight grid'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "threshold_mw": {"type": "number", "default": 10.0, "minimum": 0.0},
                "limit": {"type": "integer", "default": 15, "minimum": 1, "maximum": 50},
            },
        },
    },
    {
        "name": "run_portfolio_dscr_stress",
        "description": (
            "Stress-test pipeline projects at a user-supplied PPA price (£/MWh). For each "
            "solar/wind/BESS project, computes annual revenue = capacity_mw * capacity_factor "
            "* 8760 * ppa_price, assumes debt-service-ratio = revenue / (capex * 0.08) using "
            "CB7 debt assumptions (70% gearing, 8% annual DS / MW installed), and returns "
            "which projects fall below 1.20 DSCR. Use this for 'DSCR stress', 'cashflow "
            "stress', 'which projects fail at £X PPA'. Data-centre (dc) projects are excluded "
            "— they buy electricity rather than sell it. Returns project_name, capacity_mw, "
            "tech, assumed_cf, annual_revenue_m, annual_ds_m, dscr, passes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ppa_price_mwh": {"type": "number", "default": 55.0, "minimum": 0.0, "description": "PPA strike price in GBP/MWh"},
                "dscr_threshold": {"type": "number", "default": 1.20, "minimum": 1.0, "maximum": 3.0},
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def execute_tool(
    name: str,
    args: dict,
    session: ChatSession,
    *,
    pool,                    # asyncpg pool
    run_sam_subprocess,      # from main.py
    fetch_parcel_context,    # from main.py
    run_geeflow_subprocess=None,  # from main.py (optional)
    run_geoai_subprocess=None,   # from main.py (optional)
) -> Any:
    """Execute a tool call and return the result dict."""
    try:
        if name == "current_page_context":
            # BOT-CHC 2026-04-19 — thin reflection of the session's live UI
            # snapshot. Falls back to the project_summary stash so Claude still
            # gets the project name/tech/capacity even before the first
            # page_context has landed over the wire.
            pg = None
            if session.ui_context and isinstance(session.ui_context.get("page_context"), dict):
                pg = session.ui_context["page_context"]
            out = {
                "has_context": bool(session.ui_context),
                "session_project_id": session.project_id,
                "session_parcel_id": session.parcel_id,
                "page_context": pg,
                "project_summary": session.project_summary,
            }
            # Surface flat-shape fields for convenience.
            if session.ui_context:
                for k in ("workspace", "view", "viewMode", "lifecycle_tab",
                          "pathname", "picked_location", "project_id"):
                    v = session.ui_context.get(k)
                    if v is not None:
                        out[k] = v
            return out

        # ──────────────────────────────────────────────────────────────────
        # BOT-CHT 2026-04-21 — P0 tool handlers. Each block compacts the
        # upstream payload so the result fits inside _compact_tool_result's
        # 4000-char cap without losing critical fields.
        # ──────────────────────────────────────────────────────────────────
        if name == "list_projects":
            conds, params = [], []
            idx = 1
            source = (args.get("source") or "pipeline").lower()
            if source == "pipeline":
                # BOT-PILL 2026-04-21 — harmonise with api_mission_control
                # (portfolio_id IS NOT NULL OR verdict IS NOT NULL). Old
                # AND-only filter returned 2 rows vs 26 in mission control,
                # breaking every pipeline-wide question the 5 chat pills
                # ask. OR-semantics matches the Pipeline tab + feed.
                conds.append("(portfolio_id IS NOT NULL OR verdict IS NOT NULL)")
            elif source == "repd":
                conds.append("repd_id IS NOT NULL")
            # source == "all" adds no filter
            if args.get("portfolio_id"):
                conds.append(f"portfolio_id = ${idx}::uuid"); params.append(args["portfolio_id"]); idx += 1
            if args.get("stage"):
                conds.append(f"stage = ${idx}"); params.append(args["stage"]); idx += 1
            if args.get("technology"):
                conds.append(f"technology = ${idx}"); params.append(args["technology"]); idx += 1
            if args.get("verdict"):
                conds.append(f"verdict = ${idx}"); params.append(args["verdict"]); idx += 1
            where = f"WHERE {' AND '.join(conds)}" if conds else ""
            lim = max(1, min(int(args.get("limit", 25) or 25), 200))
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""SELECT project_id, name, technology, capacity_mw, stage,
                               verdict, lat, lon, blocker, portfolio_id,
                               updated_at
                        FROM projects {where}
                        ORDER BY updated_at DESC NULLS LAST LIMIT ${idx}""",
                    *params, lim,
                )
                total = await conn.fetchval(f"SELECT count(*) FROM projects {where}", *params)
            items = [
                {
                    "id": str(r["project_id"]),
                    "name": r["name"],
                    "tech": r["technology"],
                    "mw": float(r["capacity_mw"]) if r["capacity_mw"] else None,
                    "stage": r["stage"],
                    "verdict": r["verdict"],
                    "lat": float(r["lat"]) if r["lat"] else None,
                    "lon": float(r["lon"]) if r["lon"] else None,
                    "blocker": r["blocker"],
                    "portfolio_id": str(r["portfolio_id"]) if r["portfolio_id"] else None,
                }
                for r in rows
            ]
            out = {"count": len(items), "total": int(total or 0), "projects": items}
            if not items:
                out["_explanation"] = (
                    "No projects match the filters. Try removing filters or calling "
                    "list_portfolios() first to find the user's portfolios."
                )
            return out

        if name == "get_project":
            from uuid import UUID as _UUID
            try:
                pid = _UUID(args["project_id"])
            except (ValueError, TypeError):
                return {"error": f"Invalid project_id UUID: {args.get('project_id')}"}
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM projects WHERE project_id = $1", pid,
                )
                if not row:
                    return {"error": f"Project {args['project_id']} not found"}
                parcels = await conn.fetch(
                    """SELECT ps.parcel_id,
                              ST_Y(ST_Transform(p.centroid, 4326)) AS lat,
                              ST_X(ST_Transform(p.centroid, 4326)) AS lon,
                              p.area_m2
                       FROM project_sites ps
                       LEFT JOIN parcels p ON p.parcel_id = ps.parcel_id
                       WHERE ps.project_id = $1""",
                    pid,
                )
            meta = row["metadata"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            meta = meta or {}
            return {
                "id": str(row["project_id"]),
                "name": row["name"],
                "description": row["description"],
                "technology": row["technology"],
                "capacity_mw": float(row["capacity_mw"]) if row["capacity_mw"] else None,
                "stage": row["stage"],
                "verdict": row["verdict"],
                "lat": float(row["lat"]) if row["lat"] else None,
                "lon": float(row["lon"]) if row["lon"] else None,
                "blocker": row["blocker"],
                "repd_id": row["repd_id"],
                "tec_id": row["tec_id"],
                "dno": meta.get("dno"),
                "tec_mw": meta.get("tec_mw") or meta.get("tec_capacity_mw"),
                "queue_position": meta.get("queue_position"),
                "next_action": meta.get("next_action"),
                "portfolio_id": str(row["portfolio_id"]) if row["portfolio_id"] else None,
                "parcels": [
                    {
                        "parcel_id": str(p["parcel_id"]),
                        "lat": float(p["lat"]) if p["lat"] else None,
                        "lon": float(p["lon"]) if p["lon"] else None,
                        "area_m2": float(p["area_m2"]) if p["area_m2"] else None,
                    }
                    for p in parcels[:10]
                ],
                "parcel_count": len(parcels),
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }

        if name == "list_portfolios":
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT portfolio_id, name, description, created_at,
                              (SELECT count(*) FROM projects pr
                                WHERE pr.portfolio_id = p.portfolio_id) AS project_count
                         FROM portfolios p
                        ORDER BY created_at DESC LIMIT 50"""
                )
            items = [
                {
                    "id": str(r["portfolio_id"]),
                    "name": r["name"],
                    "description": r["description"],
                    "project_count": int(r["project_count"] or 0),
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]
            out = {"count": len(items), "portfolios": items}
            if not items:
                out["_explanation"] = "No portfolios yet. Create one via the Portfolios tab."
            return out

        if name == "get_portfolio_mission_control":
            try:
                from app.routers.project_actions import api_mission_control as _mc
                data = await _mc(pool=pool)
            except Exception as exc:
                return {"error": f"mission_control raised {type(exc).__name__}: {exc}"}
            # Compact for history. Upstream nests KPIs under `metrics`.
            metrics = data.get("metrics") or {}
            active = (data.get("active_projects") or [])[:8]
            return {
                "total_projects": metrics.get("total_projects"),
                "total_mw": metrics.get("total_mw"),
                "go_count": metrics.get("go_count"),
                "caution_count": metrics.get("caution_count"),
                "in_queue": metrics.get("in_queue"),
                "next_filing": metrics.get("next_filing_deadline"),
                "active_projects_preview": [
                    {
                        "project_id": p.get("project_id"),
                        "name": p.get("name"),
                        "workload_type": p.get("workload_type"),
                        "verdict": p.get("verdict"),
                        "stage": p.get("stage"),
                        "capacity_mw": p.get("capacity_mw"),
                        "blocker": p.get("blocker"),
                        "grid_status": p.get("grid_status"),
                        "next_action": p.get("next_action"),
                        "next_action_due_days": p.get("next_action_due_days"),
                    }
                    for p in active
                ],
                "active_projects_total": len(data.get("active_projects") or []),
                "live_signals_count": len(data.get("live_signals") or []),
                "activity_feed_count": len(data.get("activity_feed") or []),
            }

        if name == "get_substation":
            try:
                sub_id = int(args["substation_id"])
            except (TypeError, ValueError):
                return {"error": f"substation_id must be integer, got {args.get('substation_id')!r}"}
            try:
                from utils.substation_detail import enriched_substation_detail
                result = await enriched_substation_detail(pool, sub_id)
            except Exception as exc:
                return {"error": f"enriched_substation_detail raised {type(exc).__name__}: {exc}"}
            if result is None:
                return {"error": f"Substation {sub_id} not found",
                        "_explanation": "Try search_substations(lat, lon, radius_km) to find ids near a point."}
            # Keep full result — _compact_tool_result will trim if >4000 chars.
            return result

        if name == "get_project_grid_connection":
            from uuid import UUID as _UUID
            try:
                pid = _UUID(args["project_id"])
            except (ValueError, TypeError):
                return {"error": f"Invalid project_id UUID: {args.get('project_id')}"}
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT project_id, name, technology, capacity_mw, lat, lon, metadata
                         FROM projects WHERE project_id = $1""",
                    pid,
                )
            if not row:
                return {"error": f"Project {args['project_id']} not found"}
            if row["lat"] is None or row["lon"] is None:
                return {"error": "Project has no coordinates; set lat/lon first",
                        "project_id": str(row["project_id"]), "name": row["name"]}
            cap_mw = float(row["capacity_mw"] or 5.0)
            tech = (row["technology"] or "solar").lower()
            try:
                from app.routers.grid import api_grid_assess as _gc_assess
                result = await _gc_assess(
                    lat=float(row["lat"]), lon=float(row["lon"]),
                    capacity_mw=cap_mw, technology=tech, radius_km=30.0,
                    pool=pool,
                )
            except Exception as exc:
                return {"error": f"grid_assess raised {type(exc).__name__}: {exc}",
                        "project_id": str(row["project_id"])}
            # Compact: verdict + top-3 substation candidates
            candidates = (result.get("substations") or result.get("candidates") or [])[:3]
            return {
                "project_id": str(row["project_id"]),
                "project_name": row["name"],
                "capacity_mw": cap_mw,
                "technology": tech,
                "verdict": result.get("verdict") or result.get("overall_verdict"),
                "headroom_mw": result.get("headroom_mw"),
                "nearest_substation": result.get("nearest_substation") or (candidates[0] if candidates else None),
                "connection_cost": result.get("estimated_connection_cost") or result.get("cost_estimate"),
                "candidates": candidates,
                "notes": result.get("notes") or result.get("_explanation"),
            }

        if name == "list_alerts":
            q = (args.get("query") or "").strip().lower()
            cluster_f = (args.get("cluster") or "").strip().lower()
            lim = max(1, min(int(args.get("limit", 25) or 25), 100))
            async with pool.acquire() as conn:
                try:
                    rows = await conn.fetch(
                        """SELECT id, slug, title, description, cluster, cadence
                             FROM alert_definitions
                            WHERE is_public = TRUE
                            ORDER BY cluster NULLS LAST, title
                            LIMIT 300"""
                    )
                except Exception as exc:
                    return {"error": f"alert_definitions query failed: {exc}",
                            "_explanation": "Alerts table may not be seeded. Run ingestion."}
            items = []
            for r in rows:
                title = (r["title"] or "")
                slug = (r["slug"] or "")
                cl = (r["cluster"] or "Other")
                if q and q not in title.lower() and q not in slug.lower() and q not in cl.lower():
                    continue
                if cluster_f and cluster_f != cl.lower():
                    continue
                items.append({
                    "id": str(r["id"]),
                    "slug": slug,
                    "title": title,
                    "cluster": cl,
                    "cadence": r["cadence"],
                })
                if len(items) >= lim:
                    break
            out = {"count": len(items), "alerts": items}
            if not items:
                out["_explanation"] = (
                    "No alerts match. Try removing filters. Alert library is seeded "
                    "from the regulatory registry + Ofgem/DNO sources."
                )
            return out

        if name == "list_dockets":
            conds = ["1=1"]
            params: list = []
            def _p(v):
                params.append(v); return f"${len(params)}"
            if args.get("case_type"):
                conds.append(f"d.case_type = {_p(args['case_type'])}")
            if args.get("publisher"):
                conds.append(f"a.slug = {_p(args['publisher'])}")
            if args.get("status"):
                conds.append(f"d.status = {_p(args['status'])}")
            if args.get("region"):
                conds.append(f"a.jurisdiction = {_p(args['region'])}")
            if args.get("query"):
                qv = f"%{args['query']}%"
                conds.append(f"(d.title ILIKE {_p(qv)} OR d.applicant_name ILIKE {_p(qv)})")
            join = "LEFT JOIN authorities a ON a.id = d.publisher_id"
            if args.get("project_id"):
                # Restrict to pinned dockets for the project
                join += f" JOIN project_docket_pins pdp ON pdp.docket_id = d.docket_id"
                conds.append(f"pdp.project_id = {_p(args['project_id'])}::uuid")
            lim = max(1, min(int(args.get("limit", 25) or 25), 100))
            sql = f"""SELECT d.docket_id, d.title, d.case_type, d.status, d.applicant_name,
                             d.opened_at, d.updated_at, a.slug AS publisher_slug,
                             a.name AS publisher_name
                        FROM dockets d {join}
                       WHERE {' AND '.join(conds)}
                       ORDER BY d.updated_at DESC NULLS LAST LIMIT {lim}"""
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(sql, *params)
            except Exception as exc:
                return {"error": f"dockets query failed: {type(exc).__name__}: {exc}"}
            items = [
                {
                    "id": str(r["docket_id"]),
                    "title": r["title"],
                    "case_type": r["case_type"],
                    "status": r["status"],
                    "applicant": r["applicant_name"],
                    "publisher": r["publisher_slug"],
                    "opened_at": r["opened_at"].isoformat() if r["opened_at"] else None,
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                }
                for r in rows
            ]
            out = {"count": len(items), "dockets": items}
            if not items:
                out["_explanation"] = (
                    "No dockets match. If filtering by project_id, the project may "
                    "have no pinned dockets yet. Use list_alerts() or the Docket "
                    "Library to discover and pin."
                )
            return out

        if name == "list_repd":
            try:
                from utils.repd_tracker import query_repd as _query_repd
            except Exception as exc:
                return {"error": f"repd_tracker import failed: {exc}"}
            tech = args.get("tech")
            if tech == "bess":
                tech = "battery"  # REPD calls it 'Battery'
            try:
                async with pool.acquire() as conn:
                    rows = await _query_repd(
                        conn,
                        tech_category=tech,
                        status=args.get("status"),
                        developer=args.get("developer"),
                        min_capacity_mw=args.get("min_mw"),
                        lat=args.get("near_lat"),
                        lon=args.get("near_lon"),
                        radius_km=float(args.get("radius_km", 25) or 25),
                        page=1,
                        limit=max(1, min(int(args.get("limit", 25) or 25), 100)),
                    )
            except Exception as exc:
                return {"error": f"query_repd raised {type(exc).__name__}: {exc}",
                        "_explanation": "REPD table may not be ingested. Run POST /tracker/repd/ingest."}
            items = [
                {
                    "ref_id": r.get("ref_id") or r.get("id"),
                    "name": r.get("site_name") or r.get("name"),
                    "tech": r.get("tech_category") or r.get("technology"),
                    "mw": r.get("capacity_mw"),
                    "status": r.get("status"),
                    "developer": r.get("developer"),
                    "region": r.get("region"),
                    "lat": r.get("lat"),
                    "lon": r.get("lon"),
                }
                for r in rows[:50]
            ]
            out = {"count": len(items), "projects": items}
            if not items:
                out["_explanation"] = "No REPD matches. Try widening the radius or dropping tech filter."
            return out

        if name == "get_regulatory_version":
            try:
                from app.regulatory import versions as _vers
            except Exception as exc:
                return {"error": f"regulatory.versions import failed: {exc}"}
            key = (args.get("key") or "").strip().lower()
            if not key:
                return {"available_keys": _vers.all_keys(),
                        "_explanation": "Pass key=<slug> (e.g. 'g99', 'nppf') to get a record."}
            try:
                rec = _vers.get(key)
            except KeyError as exc:
                return {"error": str(exc), "available_keys": _vers.all_keys()}
            return {
                "key": key,
                "name": rec.get("name"),
                "subtitle": rec.get("subtitle"),
                "version": rec.get("version"),
                "published": rec.get("published"),
                "effective": rec.get("effective"),
                "url": rec.get("url"),
                "notes": (rec.get("notes") or "")[:600],
                "supersedes": rec.get("supersedes") or [],
                "citation": _vers.cite(key, include_url=False),
            }

        if name == "get_pinned_dockets":
            from uuid import UUID as _UUID
            from app.dockets.agent_tool import get_pinned_dockets
            async with pool.acquire() as conn:
                return await get_pinned_dockets(conn, _UUID(args["project_id"]))

        if name == "get_dno_engagement_status":
            from app.dockets.dno_engagement_tool import get_dno_engagement_status
            return await get_dno_engagement_status(pool, args["project_id"])

        # ──────────────────────────────────────────────────────────────────
        # BOT-PILL 2026-04-21 — handlers for the 4 Mission Control pills
        # that were BROKEN or WEAK against the generic list_projects fan-out.
        # Each is SQL-only, 30-60 lines, returns a pre-ranked list.
        # ──────────────────────────────────────────────────────────────────
        if name == "get_portfolio_risk_scan":
            lim = max(1, min(int(args.get("limit", 10) or 10), 50))
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT project_id, name, verdict, blocker, stage, capacity_mw,
                              technology, updated_at
                         FROM projects
                        WHERE (portfolio_id IS NOT NULL OR verdict IS NOT NULL)
                          AND (UPPER(COALESCE(verdict,'')) = 'CAUTION' OR blocker IS NOT NULL)
                        ORDER BY capacity_mw DESC NULLS LAST
                        LIMIT $1""",
                    lim,
                )
            items = [
                {
                    "id": str(r["project_id"]),
                    "name": r["name"],
                    "verdict": r["verdict"],
                    "blocker": r["blocker"],
                    "stage": r["stage"],
                    "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] else None,
                    "technology": r["technology"],
                    "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
                }
                for r in rows
            ]
            out = {"count": len(items), "at_risk_projects": items}
            if not items:
                out["_explanation"] = "No pipeline projects currently flagged CAUTION or with an active blocker."
            return out

        if name == "get_recent_activity":
            days = max(1, min(int(args.get("days", 7) or 7), 30))
            async with pool.acquire() as conn:
                events = await conn.fetch(
                    f"""SELECT event_id, event_type, severity, project_id, substation_id,
                               source, detected_at
                          FROM grid_events
                         WHERE detected_at > now() - interval '{days} days'
                         ORDER BY detected_at DESC LIMIT 15"""
                )
                notes = await conn.fetch(
                    f"""SELECT notification_id, alert_type, title, severity, created_at
                          FROM notifications
                         WHERE created_at > now() - interval '{days} days'
                         ORDER BY created_at DESC LIMIT 15"""
                )
                proj_updates = await conn.fetch(
                    f"""SELECT project_id, name, stage, verdict, blocker, updated_at
                          FROM projects
                         WHERE (portfolio_id IS NOT NULL OR verdict IS NOT NULL)
                           AND updated_at > now() - interval '{days} days'
                         ORDER BY updated_at DESC LIMIT 15"""
                )
            return {
                "window_days": days,
                "grid_events": [
                    {"id": int(e["event_id"]), "type": e["event_type"], "severity": e["severity"],
                     "substation_id": e["substation_id"], "project_id": e["project_id"],
                     "source": e["source"], "at": e["detected_at"].isoformat() if e["detected_at"] else None}
                    for e in events
                ],
                "notifications": [
                    {"id": str(n["notification_id"]), "alert_type": n["alert_type"],
                     "title": n["title"], "severity": n["severity"],
                     "at": n["created_at"].isoformat() if n["created_at"] else None}
                    for n in notes
                ],
                "project_updates": [
                    {"id": str(p["project_id"]), "name": p["name"], "stage": p["stage"],
                     "verdict": p["verdict"], "blocker": p["blocker"],
                     "at": p["updated_at"].isoformat() if p["updated_at"] else None}
                    for p in proj_updates
                ],
                "counts": {"grid_events": len(events), "notifications": len(notes),
                            "project_updates": len(proj_updates)},
            }

        if name == "list_low_headroom_projects":
            threshold = float(args.get("threshold_mw", 10.0) or 10.0)
            lim = max(1, min(int(args.get("limit", 15) or 15), 50))
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT p.project_id, p.name, p.capacity_mw, p.technology, p.stage,
                              p.verdict, p.lat, p.lon,
                              nn.id AS sub_id, nn.name AS sub_name, nn.dno, nn.voltage_kv,
                              nn.demand_headroom_mw, nn.distance_m / 1000.0 AS distance_km
                         FROM projects p
                         JOIN LATERAL (
                             SELECT s.id, s.name, s.dno, s.voltage_kv, s.demand_headroom_mw,
                                    ST_Distance(
                                      s.geom,
                                      ST_Transform(ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326), 27700)
                                    ) AS distance_m
                               FROM grid_substations s
                              WHERE s.demand_headroom_mw IS NOT NULL
                                AND s.dno <> 'osm'
                              ORDER BY s.geom <-> ST_Transform(ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326), 27700)
                              LIMIT 1
                         ) nn ON TRUE
                        WHERE (p.portfolio_id IS NOT NULL OR p.verdict IS NOT NULL)
                          AND p.lat IS NOT NULL AND p.lon IS NOT NULL
                          AND nn.demand_headroom_mw < $1
                        ORDER BY nn.demand_headroom_mw ASC, p.capacity_mw DESC NULLS LAST
                        LIMIT $2""",
                    threshold, lim,
                )
            items = [
                {
                    "project_id": str(r["project_id"]),
                    "name": r["name"],
                    "capacity_mw": float(r["capacity_mw"]) if r["capacity_mw"] else None,
                    "technology": r["technology"],
                    "stage": r["stage"],
                    "verdict": r["verdict"],
                    "nearest_substation": {
                        "id": int(r["sub_id"]),
                        "name": r["sub_name"],
                        "dno": r["dno"],
                        "voltage_kv": float(r["voltage_kv"]) if r["voltage_kv"] else None,
                        "demand_headroom_mw": float(r["demand_headroom_mw"]),
                        "distance_km": round(float(r["distance_km"]), 2),
                    },
                }
                for r in rows
            ]
            out = {"threshold_mw": threshold, "count": len(items), "projects": items}
            if not items:
                out["_explanation"] = (
                    f"No pipeline projects have a nearest DNO-published substation with "
                    f"demand_headroom_mw < {threshold} MW."
                )
            return out

        if name == "run_portfolio_dscr_stress":
            ppa = float(args.get("ppa_price_mwh", 55.0) or 55.0)
            thresh = float(args.get("dscr_threshold", 1.20) or 1.20)
            # Capacity factors — UK typicals referenced in system prompt.
            # Offshore wind gets a higher CF than onshore.
            CF = {"solar": 0.11, "wind": 0.28, "wind_offshore": 0.42, "wind_onshore": 0.28,
                  "bess": 0.20, "hybrid": 0.15, "pumped_storage_hydroelectricity": 0.12,
                  "hydro": 0.35}
            # CB7-aligned: capex £/MW and annual debt service £/MW (70% gearing,
            # 25yr straight-line at ~6% cost of debt -> ~0.08 * capex / yr).
            CAPEX_PER_MW = {"solar": 650_000, "wind": 1_500_000, "wind_offshore": 3_000_000,
                             "wind_onshore": 1_500_000, "bess": 550_000, "hybrid": 900_000,
                             "pumped_storage_hydroelectricity": 1_800_000, "hydro": 2_000_000}
            def _lookup(d, tech, default):
                if tech in d:
                    return d[tech]
                # longest-prefix match (e.g. wind_offshore_floating -> wind_offshore -> wind)
                for k in sorted(d.keys(), key=len, reverse=True):
                    if tech.startswith(k):
                        return d[k]
                return default
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT project_id, name, technology, capacity_mw, stage, verdict
                         FROM projects
                        WHERE (portfolio_id IS NOT NULL OR verdict IS NOT NULL)
                          AND capacity_mw IS NOT NULL AND capacity_mw > 0
                          AND LOWER(COALESCE(technology,'')) <> 'dc'
                        ORDER BY capacity_mw DESC"""
                )
            fails, passes = [], []
            for r in rows:
                tech = (r["technology"] or "solar").lower()
                cf = _lookup(CF, tech, 0.15)
                capex_per_mw = _lookup(CAPEX_PER_MW, tech, 800_000)
                mw = float(r["capacity_mw"])
                annual_mwh = mw * cf * 8760.0
                revenue_m = annual_mwh * ppa / 1_000_000.0
                ds_m = mw * capex_per_mw * 0.08 / 1_000_000.0  # 8% annual DS on gross capex
                dscr = (revenue_m / ds_m) if ds_m > 0 else None
                rec = {
                    "project_id": str(r["project_id"]),
                    "name": r["name"],
                    "technology": tech,
                    "capacity_mw": mw,
                    "assumed_cf": cf,
                    "annual_revenue_m": round(revenue_m, 2),
                    "annual_ds_m": round(ds_m, 2),
                    "dscr": round(dscr, 2) if dscr is not None else None,
                    "passes": bool(dscr is not None and dscr >= thresh),
                }
                (passes if rec["passes"] else fails).append(rec)
            return {
                "ppa_price_mwh": ppa,
                "dscr_threshold": thresh,
                "assumptions": {
                    "capacity_factors": CF, "capex_gbp_per_mw": CAPEX_PER_MW,
                    "annual_ds_pct_of_capex": 0.08,
                    "note": "CB7 aligned: 70% gearing, ~25yr straight-line debt at ~6% cost",
                },
                "fail_count": len(fails), "pass_count": len(passes),
                "failing_projects": fails[:15],
                "passing_preview": passes[:5],
            }

        if name == "run_solar_yield":
            return await run_sam_subprocess(
                args["lat"], args["lon"],
                args.get("capacity_kw", 100),
                args.get("tilt", 25),
                args.get("azimuth", 180),
            )

        elif name == "get_site_context":
            from uuid import UUID
            pid = UUID(args["parcel_id"])
            async with pool.acquire() as conn:
                return await fetch_parcel_context(pid, conn)

        elif name == "create_site_parcel":
            # Reuse the from-location logic
            from uuid import UUID
            async with pool.acquire() as conn:
                lat, lon = args["lat"], args["lon"]
                area_m2 = args.get("area_m2", 50000)
                pid = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO parcels (parcel_id, centroid, area_m2, geometry)
                    VALUES ($1,
                            ST_Transform(ST_SetSRID(ST_MakePoint($2, $3), 4326), 27700),
                            $4,
                            ST_Transform(ST_Buffer(ST_SetSRID(ST_MakePoint($2, $3), 4326)::geography, $5)::geometry, 27700))
                    """,
                    pid, lon, lat, area_m2, (area_m2 ** 0.5) / 2,
                )
                # Update nearest substation
                await conn.execute(
                    """
                    WITH nearest AS (
                        SELECT s.sub_id, s.capacity_kw, ST_Distance(p.centroid, s.geometry) AS dist_m
                        FROM parcels p
                        JOIN LATERAL (
                            SELECT sub_id, capacity_kw, geometry
                            FROM dno_substations
                            ORDER BY p.centroid <-> geometry LIMIT 1
                        ) s ON true
                        WHERE p.parcel_id = $1
                    )
                    UPDATE parcels SET
                        nearest_substation_id = n.sub_id,
                        distance_to_sub_km = n.dist_m / 1000.0,
                        nearest_sub_capacity_kw = n.capacity_kw
                    FROM nearest n WHERE parcels.parcel_id = $1
                    """,
                    pid,
                )
                session.parcel_id = str(pid)
                return {"parcel_id": str(pid), "lat": lat, "lon": lon, "area_m2": area_m2}

        elif name == "get_grid_connection":
            from uuid import UUID
            from utils.grid_data_platform import connection_cost_estimate, substations_in_radius
            pid = UUID(args["parcel_id"])
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT p.nearest_substation_id, p.distance_to_sub_km,
                           p.nearest_sub_capacity_kw, s.name AS sub_name,
                           ST_Y(ST_Transform(p.centroid, 4326)) AS lat,
                           ST_X(ST_Transform(p.centroid, 4326)) AS lon
                    FROM parcels p
                    LEFT JOIN dno_substations s ON s.sub_id = p.nearest_substation_id
                    WHERE p.parcel_id = $1
                    """,
                    pid,
                )
                if not row:
                    return {"error": "Parcel not found"}
                cap_kw = args.get("capacity_kw", 100)
                dist_km = float(row["distance_to_sub_km"]) if row["distance_to_sub_km"] else None
                cost = connection_cost_estimate(cap_kw, dist_km) if dist_km else None
                return {
                    "nearest_substation": row["sub_name"],
                    "substation_id": row["nearest_substation_id"],
                    "distance_km": dist_km,
                    "substation_capacity_kw": float(row["nearest_sub_capacity_kw"]) if row["nearest_sub_capacity_kw"] else None,
                    "estimated_connection_cost": cost,
                    "site_lat": float(row["lat"]) if row["lat"] else None,
                    "site_lon": float(row["lon"]) if row["lon"] else None,
                }

        elif name == "run_power_flow":
            from app.helpers import _run_grid_subprocess
            lat, lon = args["lat"], args["lon"]
            cap_mw = args.get("capacity_mw", 50)
            tech = args.get("technology", "solar")
            sub_id = args.get("substation_id")
            contingency = args.get("contingency", False)
            try:
                result = await _run_grid_subprocess({
                    "command": "power_flow",
                    "lat": lat, "lon": lon,
                    "capacity_mw": cap_mw,
                    "technology": tech,
                    "substation_id": sub_id,
                    "contingency": contingency,
                })
                return result
            except Exception as e:
                # Fallback: analytical estimate from DNO-published substations
                # (grid_substations with dno != 'osm', demand_headroom_mw set).
                async with pool.acquire() as conn:
                    sub = await conn.fetchrow(
                        """SELECT id, name, demand_headroom_mw, transformer_rating_mva,
                                  ST_Distance(geom, ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326),27700))/1000.0 AS dist_km
                           FROM grid_substations
                           WHERE dno IN ('nged','ukpn','ssen','spen','enwl','npg')
                             AND demand_headroom_mw IS NOT NULL
                           ORDER BY geom <-> ST_Transform(ST_SetSRID(ST_MakePoint($1,$2),4326),27700)
                           LIMIT 1""", lon, lat)
                dist = float(sub["dist_km"]) if sub else 5.0
                sub_cap = float(sub["transformer_rating_mva"]) if sub and sub["transformer_rating_mva"] else 100
                headroom = sub_cap - cap_mw
                voltage_dev = min(5.5, cap_mw * 0.02 * dist)
                loading = min(95, cap_mw / sub_cap * 100) if sub_cap > 0 else 50
                return {
                    "analysis_type": "analytical_estimate",
                    "note": f"pandapower subprocess unavailable ({e}), returning analytical estimate",
                    "substation": sub["name"] if sub else "Unknown",
                    "distance_km": round(dist, 2),
                    "capacity_mw": cap_mw,
                    "headroom_mw": round(headroom, 1),
                    "voltage_deviation_pct": round(voltage_dev, 2),
                    "line_loading_pct": round(loading, 1),
                    "losses_pct": round(dist * 0.3, 2),
                    "verdict": "GO" if headroom > 0 and voltage_dev < 5 else "CAUTION" if headroom > -10 else "NO-GO",
                    "recommendation": "Full pandapower Newton-Raphson simulation recommended for Tier 2 assessment" if headroom < cap_mw * 0.5 else "Site has sufficient headroom — Tier 1 assessment adequate",
                }

        elif name == "run_financial_analysis":
            from utils.energy_price_forecast import predict_24h as price_predict_24h, estimate_revenue
            lat, lon = args["lat"], args["lon"]
            cap_kw = args.get("capacity_kw", 100)
            day = args.get("day_of_year", 172)
            forecast = price_predict_24h(day_of_year=day, lat=lat)
            price_hourly = forecast.get("hourly_price_gbp", [])
            # Get SAM yield for revenue calc
            try:
                sam = await run_sam_subprocess(lat, lon, cap_kw)
                hourly_kwh = sam.get("hourly_gen_kw", [])
                # Extract 24h for the given day
                start = (day - 1) * 24
                day_hourly = hourly_kwh[start:start + 24] if len(hourly_kwh) > start + 23 else []
                annual_kwh = sam.get("annual_energy_kwh", 0)
                revenue = estimate_revenue(day_hourly, price_hourly) if day_hourly and price_hourly else None
            except Exception:
                annual_kwh = None
                revenue = None
            return {
                "price_forecast_24h": forecast,
                "annual_energy_kwh": annual_kwh,
                "estimated_daily_revenue": revenue,
            }

        elif name == "get_energy_prices":
            from utils.agile_pricing import get_pricing_overview
            region = args.get("region", "C")
            return await get_pricing_overview(region)

        elif name == "get_demand_forecast":
            from utils.energy_demand_predictor import get_demand_forecast
            return await get_demand_forecast()

        elif name == "query_planning_apps":
            from utils.planning_energy import query_energy_applications
            async with pool.acquire() as conn:
                return await query_energy_applications(
                    conn,
                    category=args.get("category"),
                    status=args.get("status"),
                    search=args.get("search"),
                    limit=args.get("limit", 20),
                )

        elif name == "run_bipv_analysis":
            from datetime import datetime, timezone
            from utils.bipv_calculator import calculate_bipv
            return calculate_bipv(
                lat=args["lat"],
                lon=args["lon"],
                dt=datetime.now(timezone.utc),
                area_m2=args.get("area_m2", 50),
                surface_type=args.get("surface_type", "pitched_roof_south"),
                module_type=args.get("module_type", "mono_roof_tile"),
            )

        elif name == "get_inventory_bom":
            from utils.solar_inventory import generate_site_bom
            from uuid import UUID
            pid = UUID(args["parcel_id"])
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT area_m2 FROM parcels WHERE parcel_id = $1", pid
                )
                area_m2 = float(row["area_m2"]) if row and row["area_m2"] else 50000
            cap_kw = args.get("capacity_kw", 100)
            return generate_site_bom(cap_kw, area_m2)

        elif name == "search_substations":
            from utils.grid_data_platform import substations_in_radius
            return substations_in_radius(
                args["lat"], args["lon"],
                args.get("radius_km", 10),
            )

        elif name == "get_grid_live":
            from utils.national_grid_live import fetch_all_live
            return await fetch_all_live()

        elif name == "search_nged_network":
            from utils.nged_cim import find_opportunities_near
            async with pool.acquire() as conn:
                return await find_opportunities_near(
                    conn, args["lat"], args["lon"],
                    args.get("radius_km", 15),
                    args.get("min_headroom_mw", 1.0),
                )

        elif name == "create_map_layer":
            layer_id = f"chat-{uuid.uuid4().hex[:8]}"
            layer = {
                "id": layer_id,
                "name": args["name"],
                "geojson": args["geojson"],
                "layer_type": args.get("layer_type", "circle"),
                "color": args.get("color", "#00e5ff"),
                "style": args.get("style", {}),
            }
            session.map_layers.append(layer)
            return {"layer_id": layer_id, "name": args["name"], "feature_count": len(args["geojson"].get("features", []))}

        elif name == "zoom_to_location":
            return {
                "status": "ok",
                "lat": args["lat"],
                "lon": args["lon"],
                "zoom": args.get("zoom", 14),
                "label": args.get("label"),
            }

        elif name == "process_uploaded_file":
            filename = args["filename"]
            file_info = next((f for f in session.uploaded_files if f["filename"] == filename), None)
            if not file_info:
                return {"error": f"File '{filename}' not found in session uploads"}
            return file_info.get("summary", {"error": "No summary available"})

        elif name == "query_energy_scenario":
            from utils.uk_energy_scenario import system_scenario, site_in_national_context
            cap_kw = args.get("capacity_kw", 100)
            tech = args.get("technology", "solar")
            scenario = system_scenario()
            site_ctx = site_in_national_context(cap_kw, tech)
            return {"national_scenario": scenario, "site_context": site_ctx}

        elif name == "get_electricity_map":
            import httpx
            zone = args["zone"]
            metric = args.get("metric", "both")
            api_key = os.environ.get("ELECTRICITYMAPS_API_KEY", "")
            if not api_key:
                return {"error": "ELECTRICITYMAPS_API_KEY not configured"}
            base = "https://api.electricitymap.org/v3"
            headers = {"auth-token": api_key}
            result = {"zone": zone}
            async with httpx.AsyncClient(timeout=15) as client:
                if metric in ("carbon_intensity", "both"):
                    resp = await client.get(f"{base}/carbon-intensity/latest?zone={zone}", headers=headers)
                    if resp.status_code == 200:
                        result["carbon_intensity"] = resp.json()
                    else:
                        result["carbon_intensity_error"] = f"HTTP {resp.status_code}"
                if metric in ("power_breakdown", "both"):
                    resp = await client.get(f"{base}/power-breakdown/latest?zone={zone}", headers=headers)
                    if resp.status_code == 200:
                        result["power_breakdown"] = resp.json()
                    else:
                        result["power_breakdown_error"] = f"HTTP {resp.status_code}"
            return result

        elif name == "run_satellite_analysis":
            if not run_geeflow_subprocess:
                return {"error": "GeeFlow not configured — set GEE_PROJECT and GEEFLOW_PYTHON in .env"}
            lat, lon = args["lat"], args["lon"]
            radius_km = args.get("radius_km", 5)
            modes = args.get("modes", ["land_use", "terrain", "solar_resource", "vegetation"])
            # Submit as background job via main.py's job system
            import jobs
            async def _satellite_job():
                results = {}
                for mode in modes:
                    try:
                        results[mode] = await run_geeflow_subprocess(mode, lat, lon, radius_km)
                    except Exception as exc:
                        results[mode] = {"error": str(exc)[:200]}
                from utils.geeflow_site_scorer import compute_site_score
                score = compute_site_score(
                    terrain_data=results.get("terrain"),
                    land_use_data=results.get("land_use"),
                    solar_data=results.get("solar_resource"),
                    flood_data=results.get("flood_risk"),
                )
                return {"lat": lat, "lon": lon, "radius_km": radius_km,
                        "extractions": results, "site_score": score}
            job = await jobs.submit("geeflow_analysis", _satellite_job)
            return {"job_id": job.id, "status": job.status.value,
                    "message": f"Satellite analysis started for ({lat}, {lon}). Poll /job/{job.id} for results."}

        elif name == "score_tender_sites":
            from utils.geeflow_site_scorer import score_multiple_sites
            sites = args["sites"]
            technology = args.get("technology", "solar")
            # For each site, try to get cached GeeFlow data
            enriched = []
            for site in sites:
                site_data = dict(site)
                # Check for cached satellite data
                async with pool.acquire() as conn:
                    cached = await conn.fetchrow(
                        """
                        SELECT result_data, mode FROM geeflow_extractions
                        WHERE abs(lat - $1) < 0.01 AND abs(lon - $2) < 0.01
                          AND created_at > NOW() - INTERVAL '30 days'
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        site["lat"], site["lon"],
                    )
                    if cached:
                        geeflow = {}
                        rd = cached["result_data"]
                        if isinstance(rd, str):
                            rd = json.loads(rd)
                        if cached["mode"] == "site_composite":
                            geeflow = rd.get("components", {})
                        else:
                            geeflow[cached["mode"]] = rd
                        site_data["geeflow_data"] = geeflow
                enriched.append(site_data)
            return score_multiple_sites(enriched, technology)

        elif name == "query_legacy_assets":
            lat, lon = args["lat"], args["lon"]
            radius_km = args.get("radius_km", 25)
            asset_type = args.get("asset_type")
            async with pool.acquire() as conn:
                conditions = [
                    "ST_DWithin(geometry, ST_Transform(ST_SetSRID(ST_MakePoint($1, $2), 4326), 27700), $3)"
                ]
                params = [lon, lat, radius_km * 1000]
                idx = 4
                if asset_type:
                    conditions.append(f"asset_type = ${idx}")
                    params.append(asset_type)
                where = " AND ".join(conditions)
                rows = await conn.fetch(f"""
                    SELECT name, asset_type, capacity_kw, commissioning, status,
                           condition_score,
                           ST_X(ST_Transform(geometry, 4326)) as lon,
                           ST_Y(ST_Transform(geometry, 4326)) as lat
                    FROM legacy_assets WHERE {where}
                    ORDER BY name LIMIT 50
                """, *params)
                return {
                    "count": len(rows),
                    "assets": [
                        {
                            "name": r["name"],
                            "asset_type": r["asset_type"],
                            "capacity_kw": r["capacity_kw"],
                            "commissioning": r["commissioning"].isoformat() if r["commissioning"] else None,
                            "status": r["status"],
                            "condition_score": r["condition_score"],
                            "lat": round(r["lat"], 5),
                            "lon": round(r["lon"], 5),
                        }
                        for r in rows
                    ],
                }

        elif name == "run_geoai_analysis":
            lat, lon = args["lat"], args["lon"]
            mode = args.get("mode", "asset_condition")
            radius_km = args.get("radius_km", 2.0)
            asset_type = args.get("asset_type", "solar_farm")
            extra = {}
            for k in ("satellite", "model_size", "ref_lat", "ref_lon", "targets", "questions"):
                if k in args and args[k] is not None:
                    extra[k] = args[k]
            if run_geoai_subprocess:
                result = await run_geoai_subprocess(mode, lat, lon, radius_km, asset_type, **extra)
                # Store embeddings in DB if foundation_embeddings mode
                if mode == "foundation_embeddings" and pool and result.get("embedding"):
                    try:
                        emb = result["embedding"]
                        dim = result.get("embedding_dim", len(emb))
                        async with pool.acquire() as conn:
                            await conn.execute(
                                """
                                INSERT INTO geeflow_extractions (lat, lon, radius_km, mode, result_data, geometry)
                                VALUES ($1, $2, $3, $4, $5::jsonb,
                                        ST_Buffer(ST_SetSRID(ST_MakePoint($6, $7), 4326)::geography, $8)::geometry)
                                """,
                                lat, lon, radius_km, "foundation_embeddings",
                                json.dumps(result, default=str),
                                lon, lat, radius_km * 1000,
                            )
                    except Exception as e:
                        log.warning("Failed to store embedding: %s", e)
                return result
            return {"error": "GeoAI subprocess not available"}

        elif name == "assess_asset_lifecycle":
            from utils.legacy_asset_compliance import assess_asset_lifecycle as _assess
            asset_type = args.get("asset_type", "solar_farm")
            comm_date = args.get("commissioning_date", "2015-01-01")
            capacity_kw = args.get("capacity_kw", 100)
            return _assess(asset_type, comm_date, capacity_kw)

        elif name == "score_candidate_site_prospector":
            from utils.site_prospector import score_candidate_site as _score_site
            return _score_site(args["lat"], args["lon"], args.get("technology", "solar"))

        elif name == "scan_region_for_sites":
            from utils.site_prospector import regional_scan as _regional_scan
            return _regional_scan(
                args.get("region", "south_west"),
                args.get("technology", "solar"),
                args.get("grid_points", 25),
            )

        elif name == "find_similar_sites":
            from utils.site_prospector import find_similar_sites as _find_similar
            return _find_similar(
                args["lat"], args["lon"],
                args.get("radius_km", 50),
                technology=args.get("technology", "solar"),
            )

        elif name == "estimate_grid_losses":
            from utils.grid_efficiency_analyser import estimate_line_losses as _line_losses
            return _line_losses(
                args["distance_km"], args["voltage_kv"], args["load_mw"],
                args.get("capacity_mva"),
            )

        elif name == "assess_substation_health":
            from utils.grid_efficiency_analyser import substation_health_assessment as _sub_health
            return _sub_health(args.get("substations", []))

        elif name == "get_procurement_pipeline":
            from utils.uk_tender_tracker import fetch_all_tenders as _fetch_tenders
            from utils.procurement_intelligence import procurement_pipeline_summary as _pipeline
            tenders = await _fetch_tenders()
            return _pipeline(tenders)

        elif name == "assess_bid_viability":
            from utils.procurement_intelligence import assess_bid_viability as _bid_viability
            tender = {
                "title": args.get("title", ""),
                "description": args.get("description", ""),
                "value_gbp": args.get("value_gbp"),
                "deadline": args.get("deadline"),
            }
            return _bid_viability(
                tender,
                site_score=args.get("site_score"),
                grid_headroom_mw=args.get("grid_headroom_mw"),
            )

        elif name == "run_vision_analysis":
            lat = args.get("lat", 52.5)
            lon = args.get("lon", -1.5)
            img_type = args.get("image_type", "satellite")
            # Use httpx to call our own vision endpoints internally
            import httpx
            base = "http://localhost:8000"
            async with httpx.AsyncClient(timeout=30) as hx:
                # Fetch satellite screenshot
                sat_resp = await hx.post(f"{base}/vision/fetch/satellite",
                    json={"lat": lat, "lon": lon, "radius_km": 2})
                sat_data = sat_resp.json()
                upload_ids = sat_data.get("upload_ids", [])
                if not upload_ids:
                    return {"error": "Failed to fetch satellite imagery"}
                # Run instant analysis
                analysis_resp = await hx.post(f"{base}/vision/analyse/instant",
                    json={"upload_id": upload_ids[0], "lat": lat, "lon": lon, "image_type": img_type})
                result = analysis_resp.json()
            return {
                "suitability_score": result.get("suitability_score"),
                "verdict": result.get("verdict"),
                "summary": result.get("summary"),
                "findings": result.get("findings"),
            }

        elif name == "assess_home_retrofit":
            from utils.home_retrofit_engine import (
                run_assessment as _home_assess,
                build_case_library_from_rows as _build_cases,
            )
            house_type = args.get("house_type", "1930s_semi")
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM home_retrofit_cases ORDER BY house_type LIMIT 200"
                )
                case_library = _build_cases(rows)
            result = _home_assess(
                house_type=house_type,
                plot_width_m=args.get("plot_width_m", 8.0),
                plot_depth_m=args.get("plot_depth_m", 25.0),
                storeys=args.get("storeys", 2),
                epc_rating=args.get("epc_rating", "D"),
                heating=args.get("heating", "gas_boiler"),
                conservation=args.get("conservation", False),
                listed=args.get("listed"),
                budget_gbp=args.get("budget_gbp"),
                lat=args.get("lat", 52.5),
                lon=args.get("lon", -1.5),
                case_library=case_library,
            )
            # Compact for chat context
            return {
                "archetype": result["archetype"],
                "matched_cases_count": len(result.get("matched_cases", [])),
                "options": [
                    {
                        "name": o["name"],
                        "interventions": o["interventions"],
                        "total_cost_gbp": o["total_cost_gbp"],
                        "energy_saving_kwh": o["energy"]["energy_saving_kwh"],
                        "epc_before": o["energy"]["epc_before"],
                        "epc_after": o["energy"]["epc_after"],
                        "planning_route": o["planning"]["route"],
                    }
                    for o in result.get("options", [])
                ],
                "solar_potential": result.get("solar_potential"),
                "heat_pump_recommendation": result.get("heat_pump_assessment", {}).get("recommendation"),
            }

        elif name == "assess_dc_colocation":
            from utils.dc_colocation_scorer import score_dc_site as _dc_score
            lat, lon = args["lat"], args["lon"]
            capacity_mw = args.get("capacity_mw", 10)
            profile = args.get("profile", "colocation")
            async with pool.acquire() as conn:
                result = await _dc_score(conn, lat, lon, capacity_mw, profile)
            # Compact for chat context
            return {
                "dc_score": result["dc_score"],
                "verdict": result["verdict"],
                "confidence": result["confidence"],
                "profile": result["profile"],
                "capacity_mw": result["capacity_mw"],
                "proximity": result["proximity"],
                "grid_connection": result["grid_connection"],
                "gates_all_passed": result["gates_all_passed"],
                "risks": result["risks"],
                "opportunities": result["opportunities"],
            }

        elif name == "score_dc_site_extended":
            from utils.dc_site_comparator import score_dc_site_extended as _ext_score
            lat, lon = args["lat"], args["lon"]
            capacity_mw = args.get("capacity_mw", 100)
            profile = args.get("profile", "google_hyperscale")
            async with pool.acquire() as conn:
                result = await _ext_score(conn, lat, lon, capacity_mw, profile)
            return {
                "dc_score": result.get("dc_score"),
                "verdict": result.get("verdict"),
                "confidence": result.get("confidence"),
                "profile": result.get("profile"),
                "capacity_mw": result.get("capacity_mw"),
                "dimensions_15": {k: v.get("score") for k, v in result.get("scores", {}).items()},
                "cfe_pct": result.get("cfe", {}).get("achievable_cfe_pct"),
                "pue_estimate": result.get("cooling", {}).get("pue_estimate"),
                "constraint_clear": result.get("constraints", {}).get("is_clear"),
                "water_status": result.get("water", {}).get("status"),
                "incentive_zones": [z.get("name") for z in result.get("incentives", {}).get("zones", [])],
                "nsip_eligible": result.get("regulatory", {}).get("nsip_eligible"),
                "grid_connection": result.get("grid_connection"),
                "risks": result.get("risks", []),
                "opportunities": result.get("opportunities", []),
            }

        elif name == "compare_dc_sites":
            from utils.dc_site_comparator import compare_dc_sites as _compare
            sites = args["sites"]
            capacity_mw = args.get("capacity_mw", 100)
            profile = args.get("profile", "google_hyperscale")
            async with pool.acquire() as conn:
                result = await _compare(conn, sites, capacity_mw, profile)
            return {
                "site_count": result.get("site_count"),
                "ranking": result.get("ranking"),
                "dimension_winners": result.get("dimension_winners"),
                "recommendation": result.get("recommendation"),
            }

        elif name == "search_colocation_opportunities":
            from utils.colocation_search import search_colocation_opportunities
            lat, lon = args["lat"], args["lon"]
            result = await search_colocation_opportunities(
                pool, lat, lon,
                radius_km=args.get("radius_km", 10),
                technology=args.get("technology", "solar"),
                min_capacity_mw=args.get("min_capacity_mw", 5),
            )
            # Compact for chat context
            return {
                "count": result["count"],
                "opportunities": [
                    {
                        "rank": o["rank"],
                        "score": o["score"],
                        "substation": o["substation"]["name"],
                        "headroom_mw": o["substation"]["headroom_mw"],
                        "distance_km": o["substation"]["distance_km"],
                        "parcels_found": o["land"]["parcels_found"],
                        "alc_grade": o["alc"]["grade"],
                        "lease_mid_gbp_ha": o["lease_benchmark"]["mid"],
                        "repd_stalled": len(o.get("repd_opportunities", [])),
                    }
                    for o in result["opportunities"][:8]
                ],
            }

        elif name == "benchmark_lease_rate":
            from utils.colocation_search import benchmark_lease
            return benchmark_lease(
                args.get("technology", "solar"),
                args.get("alc_grade", "Grade 3b"),
                args.get("region", "default"),
                args.get("area_ha", 10),
            )

        elif name == "match_landowner":
            from utils.colocation_search import match_landowner_to_companies
            from utils.companies_house import search_landowner_companies
            companies_result = await search_landowner_companies(
                args["lat"], args["lon"], radius_km=args.get("radius_km", 5)
            )
            companies = companies_result.get("companies", [])
            matches = match_landowner_to_companies(args["landowner_name"], companies)
            return {
                "landowner_name": args["landowner_name"],
                "matches": matches[:3],
                "companies_searched": len(companies),
            }

        elif name == "find_dc_sites":
            from utils.dc_colocation_scorer import scan_dc_sites as _scan
            query = args.get("query", "")
            capacity_mw = args.get("capacity_mw", 100)
            min_hr = args.get("min_headroom_mw", 50)
            limit = args.get("limit", 20)
            async with pool.acquire() as conn:
                result = await _scan(conn, "google_hyperscale", capacity_mw,
                                     min_headroom_mw=min_hr, limit=limit)
            sites = result.get("sites", [])
            return {
                "query": query,
                "count": len(sites),
                "top_sites": [
                    {"name": s.get("substation_name"), "dc_score": s.get("dc_score"),
                     "verdict": s.get("verdict"), "headroom_mw": s.get("grid_connection", {}).get("headroom_mw"),
                     "lat": s.get("lat"), "lon": s.get("lon")}
                    for s in sites[:10]
                ],
            }

        elif name == "analyse_land_suitability":
            from app.helpers import run_clay_subprocess
            lat = args["lat"]
            lon = args["lon"]
            radius_m = args.get("radius_m", 500)
            suitability = await run_clay_subprocess("suitability", lat, lon, radius_m)
            return {
                "suitability_score": suitability.get("suitability_score"),
                "verdict": suitability.get("verdict"),
                "components": suitability.get("components"),
                "recommendations": suitability.get("recommendations"),
                "spectral_indices": suitability.get("spectral_indices"),
                "terrain": suitability.get("terrain"),
                "source": suitability.get("source"),
            }

        elif name == "forecast_grid_connection":
            from utils.connection_offer_forecaster import forecast_connection_offer
            lat, lon = args["lat"], args["lon"]
            capacity_mw = args.get("capacity_mw", 50)
            technology = args.get("technology", "solar")
            result = await forecast_connection_offer(
                pool, lat, lon, capacity_mw, technology
            )
            # Compact for chat context — keep headline numbers and risks
            fc = result.get("forecast", {})
            return {
                "time_to_offer_months": fc.get("time_to_offer_months"),
                "likely_voltage_kv": fc.get("likely_voltage_kv"),
                "recommended_substation": fc.get("recommended_substation"),
                "dno": fc.get("dno"),
                "distance_km": fc.get("distance_km"),
                "queue_position": fc.get("queue_position"),
                "headroom_mw": fc.get("headroom_mw"),
                "net_headroom_mw": fc.get("net_headroom_mw"),
                "reinforcement_cost_gbp": fc.get("reinforcement_cost_gbp"),
                "connection_cost_range": fc.get("connection_cost_range"),
                "total_cost_estimate_gbp": fc.get("total_cost_estimate_gbp"),
                "risk_level": result.get("risk_level"),
                "risk_factors": result.get("risk_factors", []),
                "recommended_substations": [
                    {
                        "name": s["name"],
                        "distance_km": s["distance_km"],
                        "headroom_mw": s["headroom_mw"],
                        "queue_count": s["queue_count"],
                        "time_to_offer_months": s["time_to_offer_months"],
                    }
                    for s in result.get("recommended_substations", [])
                ],
                "historical_count": len(result.get("historical_comparisons", [])),
                "avg_historical_months": result.get("avg_historical_planning_to_operational_months"),
                "tec_projects_count": len(result.get("tec_projects_nearby", [])),
            }

        elif name == "score_planning_risk":
            from utils.planning_risk_scorer import score_planning_risk as _score_risk
            result = await _score_risk(
                pool,
                args["lat"], args["lon"],
                args.get("capacity_mw", 10),
                args.get("technology", "solar"),
            )
            return {
                "risk_score": result.get("risk_score"),
                "risk_level": result.get("risk_level"),
                "verdict": result.get("verdict"),
                "factors": result.get("factors"),
                "local_outcomes": result.get("local_outcomes"),
                "recommendations": result.get("recommendations"),
            }

        elif name == "batch_screen_sites":
            from utils.batch_screener import screen_sites as _screen
            result = await _screen(
                pool,
                args["candidates"],
                top_n=args.get("top_n", 20),
            )
            # Compact: return summary + ranked sites
            ranked = result.get("ranked", [])
            return {
                "summary": result.get("summary"),
                "total_screened": result.get("total_screened"),
                "sites": [
                    {
                        "rank": i + 1,
                        "lat": s.get("lat"),
                        "lon": s.get("lon"),
                        "label": s.get("label"),
                        "composite_score": s.get("composite_score"),
                        "verdict": s.get("verdict"),
                        "scores": s.get("scores"),
                    }
                    for i, s in enumerate(ranked[:20])
                ],
            }

        elif name == "calculate_shadow_flicker":
            from utils.shadow_flicker import calculate_shadow_flicker as _sf
            result = await _sf(
                args["lat"], args["lon"],
                args.get("turbine_specs", {}),
                args.get("receptors", []),
                pool=pool,
            )
            return result

        elif name == "calculate_glint_glare":
            from utils.shadow_flicker import calculate_glint_glare as _gg
            result = await _gg(
                args["lat"], args["lon"],
                args.get("panel_specs", {}),
                args.get("receptors", []),
                pool=pool,
            )
            return result

        elif name == "estimate_energisation_timeline":
            from utils.energisation_estimator import estimate_energisation_timeline as _eet
            result = await _eet(
                pool,
                lat=args["lat"],
                lon=args["lon"],
                capacity_mw=args.get("capacity_mw", 50),
                technology=args.get("technology", "solar"),
            )
            return {
                "total_months": result["total_months"],
                "total_months_range": result["total_months_range"],
                "phases": result["phases"],
                "target_date": result.get("target_date"),
                "risk_factors": result.get("risk_factors", []),
                "benchmarks": result.get("benchmarks", {}),
            }

        elif name == "check_environmental_constraints":
            from utils.environmental_constraints import check_all_constraints
            lat, lon = args["lat"], args["lon"]
            radius_m = args.get("radius_m", 2000)
            result = await check_all_constraints(lat, lon, radius_m)
            # Compact for chat context — keep headline data
            env = result.get("environmental", {})
            flood = result.get("flood", {})
            heritage = result.get("heritage", {})
            return {
                "overall_risk_level": result.get("overall_risk_level"),
                "overall_planning_impact": result.get("overall_planning_impact"),
                "constraint_summary": result.get("constraint_summary"),
                "designations": env.get("designations", []),
                "env_risk": env.get("risk_level"),
                "flood_zone": flood.get("flood_zone"),
                "flood_risk": flood.get("risk_level"),
                "flood_planning_impact": flood.get("planning_impact"),
                "active_flood_warnings": len(flood.get("active_warnings", [])),
                "listed_buildings_count": heritage.get("total_count", 0),
                "grade_i_buildings": heritage.get("grade_i_count", 0),
                "heritage_risk": heritage.get("risk_level"),
                "heritage_planning_impact": heritage.get("planning_impact"),
                "has_map_layers": result.get("constraints_geojson") is not None,
            }

        elif name == "search_nearby_companies":
            from utils.companies_house import search_landowner_companies
            return await search_landowner_companies(
                args["lat"], args["lon"],
                radius_km=args.get("radius_km", 5),
            )

        elif name == "check_nsip_conflicts":
            from utils.pins_nsip import check_nsip_conflicts as _nsip
            return await _nsip(
                args["lat"], args["lon"],
                radius_km=args.get("radius_km", 20),
            )

        elif name == "calculate_noise_contours":
            from utils.noise_propagation import calculate_noise_contours
            return calculate_noise_contours(
                sources=args["sources"],
                study_radius_m=args.get("study_radius_m", 2000),
                compliance_limit_dba=args.get("compliance_limit_dba", 40),
                tonal_penalty=args.get("tonal_penalty", False),
            )

        elif name == "generate_construction_schedule":
            from utils.construction_planner import generate_construction_schedule
            return generate_construction_schedule(
                capacity_mw=args["capacity_mw"],
                technology=args.get("technology", "solar"),
                site_area_ha=args.get("site_area_ha"),
                grid_distance_km=args.get("grid_distance_km"),
            )

        elif name == "estimate_construction_traffic":
            from utils.construction_planner import estimate_construction_traffic
            return estimate_construction_traffic(
                capacity_mw=args["capacity_mw"],
                technology=args.get("technology", "solar"),
                site_area_ha=args.get("site_area_ha"),
                grid_distance_km=args.get("grid_distance_km"),
            )

        elif name == "fetch_lidar_terrain":
            from utils.lidar_terrain import analyse_terrain
            return await analyse_terrain(
                args["lat"], args["lon"],
                radius_m=args.get("radius_m", 500),
            )

        elif name == "calculate_viewshed":
            from utils.viewshed_analyser import calculate_viewshed as _calc_viewshed
            return await _calc_viewshed(
                args["lat"], args["lon"],
                target_height_m=args.get("target_height_m", 3.0),
                radius_m=args.get("radius_m", 2000),
            )

        elif name == "calculate_hydrology":
            from utils.viewshed_analyser import calculate_hydrology as _calc_hydro
            return await _calc_hydro(
                args["lat"], args["lon"],
                radius_m=args.get("radius_m", 500),
            )

        elif name == "predict_connection_timeline":
            from utils.tec_timeline_model import predict_connection_timeline as _predict_timeline
            result = await _predict_timeline(
                pool,
                capacity_mw=args.get("capacity_mw", 50),
                technology=args.get("technology", "solar"),
                host_to=args.get("host_to"),
            )
            return {
                "predicted_months": result.get("predicted_months"),
                "benchmark": result.get("benchmark"),
                "by_gate": result.get("by_gate", [])[:6],  # Keep compact
                "dno_comparison": result.get("dno_comparison"),
                "source": result.get("source"),
            }

        elif name == "benchmark_site":
            from utils.site_benchmarker import benchmark_site as _benchmark
            result = await _benchmark(
                pool,
                lat=args["lat"],
                lon=args["lon"],
                capacity_mw=args.get("capacity_mw", 50),
                technology=args.get("technology", "solar"),
            )
            # Compact for chat context
            metrics_compact = {}
            for k, m in result.get("metrics", {}).items():
                metrics_compact[k] = {
                    "value": m.get("value"),
                    "unit": m.get("unit"),
                    "percentile": m.get("percentile"),
                    "median": m.get("median"),
                }
            return {
                "overall_percentile": result.get("overall_percentile"),
                "verdict": result.get("verdict"),
                "metrics": metrics_compact,
                "comparable_approved": result.get("comparable_approved", [])[:3],
                "comparable_refused": result.get("comparable_refused", [])[:3],
                "summary": result.get("summary"),
                "source": result.get("source"),
            }

        elif name == "predict_planning_approval":
            from utils.repd_ml_model import predict_approval as _predict_approval
            result = await _predict_approval(
                pool,
                args["lat"], args["lon"],
                args.get("capacity_mw", 50),
                args.get("technology", "solar"),
            )
            # Compact for chat context — keep key fields
            comparables = result.get("comparable_projects", {})
            approved_examples = comparables.get("approved", [])[:3]
            refused_examples = comparables.get("refused", [])[:3]
            return {
                "approval_probability": result["approval_probability"],
                "verdict": result["verdict"],
                "confidence": result["confidence"],
                "planning_authority": result.get("planning_authority"),
                "authority_approval_rate": result.get("authority_approval_rate"),
                "region": result.get("region"),
                "risk_factors": result.get("risk_factors", []),
                "nearby_projects": result.get("nearby_projects"),
                "comparable_approved": [
                    {"name": p.get("site_name"), "mw": p.get("capacity_mw"),
                     "distance_km": p.get("distance_km")}
                    for p in approved_examples
                ],
                "comparable_refused": [
                    {"name": p.get("site_name"), "mw": p.get("capacity_mw"),
                     "distance_km": p.get("distance_km")}
                    for p in refused_examples
                ],
                "model_accuracy": result.get("model_stats", {}).get("accuracy"),
                "training_samples": result.get("model_stats", {}).get("training_samples"),
            }

        elif name == "mutate_design":
            from app.routers.design import apply_mutation
            result = await apply_mutation(pool, args["project_id"], args["field"], float(args["value"]))
            # Compact: drop the grid sub-object beyond headline, keep KPIs + design
            return {
                "project_id": result["project_id"],
                "field": result["field"],
                "value": result["value"],
                "design": result["design"],
                "derived_kpis": result["derived_kpis"],
                "grid_headroom_mw": (result.get("grid") or {}).get("headroom_mw"),
                "note": "Design updated in projects.metadata. KPIs recomputed.",
            }

        elif name == "optimize_design":
            from app.routers.design import _load_project_row, _extract_design_state, _grid_snapshot
            from utils.design_optimizer import optimise_capacity_mix
            from uuid import UUID as _UUID
            pid = _UUID(args["project_id"])
            objective = args.get("objective", "max_npv")
            raw_bounds = args.get("bounds") or {}
            bounds = {k: tuple(v) for k, v in raw_bounds.items() if isinstance(v, (list, tuple)) and len(v) == 2}
            async with pool.acquire() as conn:
                proj = await _load_project_row(conn, pid)
                if not proj:
                    return {"error": f"Project {args['project_id']} not found"}
                design = _extract_design_state(proj)
                grid = await _grid_snapshot(conn, proj["lat"], proj["lon"])
            return optimise_capacity_mix(
                objective=objective,
                bounds=bounds or None,
                ppa_price_gbp_mwh=float(design.get("ppa_price_gbp_mwh", 68.0)),
                site_area_ha=float(design.get("site_area_ha", 120.0)),
                grid_headroom_mw=float((grid or {}).get("headroom_mw") or 50.0),
                initial={
                    "solar_mw": float(design.get("solar_mw", 20)),
                    "bess_mw": float(design.get("bess_mw", 10)),
                    "bess_hours": float(design.get("bess_hours", 2.0)),
                    "ppa_share_pct": float(design.get("ppa_share_pct", 50.0)),
                },
            )

        elif name == "full_project_doc":
            from app.routers.design import full_project_doc as _full_doc
            doc = await _full_doc(args["project_id"], pool)
            # Compact: trim assessments + verbose finance kpis for chat history
            return {
                "project": {k: doc["project"].get(k) for k in
                            ("project_id", "name", "technology", "capacity_mw",
                             "stage", "verdict", "lat", "lon", "status")},
                "design": doc["design"],
                "derived_kpis": doc["derived_kpis"],
                "finance_kpis": (doc.get("finance") or {}).get("kpis"),
                "grid": doc["grid"],
                "planning": doc["planning"],
                "demand": doc["demand"],
                "latest_assessments": doc["latest_assessments"][:3],
            }

        else:
            return {"error": f"Unknown tool: {name}"}

    except Exception as exc:
        log.exception("Tool %s failed: %s", name, exc)
        return {"error": f"Tool {name} failed: {str(exc)[:300]}"}


# ---------------------------------------------------------------------------
# Document processing
# ---------------------------------------------------------------------------

def parse_uploaded_file(filename: str, content: bytes) -> dict:
    """Parse CSV or Excel file, return summary stats."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    summary: dict[str, Any] = {"filename": filename, "size_bytes": len(content)}

    try:
        if ext == "csv":
            df = pd.read_csv(BytesIO(content))
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(BytesIO(content), engine="openpyxl")
        elif ext in ("jpg", "jpeg", "png", "tif", "tiff", "webp"):
            return {**summary, "type": "image", "format": ext, "note": "Image uploaded. Use Vision AI to analyse it."}
        else:
            # For PDF or unknown, just return basic info
            return {**summary, "type": ext or "unknown", "note": "File stored. Ask me to analyse it."}

        summary["type"] = ext
        summary["rows"] = len(df)
        summary["columns"] = list(df.columns)
        summary["dtypes"] = {col: str(dt) for col, dt in df.dtypes.items()}

        # Summary stats for numeric columns
        numeric = df.select_dtypes(include="number")
        if not numeric.empty:
            stats = numeric.describe().round(2).to_dict()
            summary["numeric_stats"] = stats

        # Detect energy-related columns
        energy_keywords = ["kwh", "mwh", "demand", "generation", "consumption", "power", "energy", "voltage", "current", "watt"]
        energy_cols = [c for c in df.columns if any(kw in c.lower() for kw in energy_keywords)]
        if energy_cols:
            summary["energy_columns"] = energy_cols

        # Date range detection
        date_cols = df.select_dtypes(include=["datetime64"]).columns.tolist()
        if not date_cols:
            # Try to detect date columns by name
            for col in df.columns:
                if any(kw in col.lower() for kw in ["date", "time", "timestamp", "period"]):
                    try:
                        df[col] = pd.to_datetime(df[col])
                        date_cols.append(col)
                    except (ValueError, TypeError):
                        pass
        if date_cols:
            summary["date_range"] = {
                col: {"min": str(df[col].min()), "max": str(df[col].max())}
                for col in date_cols[:3]
            }

        # First few rows as preview
        summary["preview"] = df.head(5).to_dict(orient="records")

    except Exception as exc:
        summary["parse_error"] = str(exc)[:300]

    return summary


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def _compact_tool_result(result: Any, max_chars: int = 4000) -> str:
    """Compact a tool result for conversation history storage.

    The full result is already sent to Claude for the *current* turn.
    For history we keep key metrics and drop large arrays/blobs so
    accumulated tool results don't blow past the context window.
    """
    def _strip_large(obj, depth=0):
        if depth > 3:
            return obj
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if isinstance(v, list) and len(v) > 30:
                    out[k] = f"[{len(v)} items omitted]"
                else:
                    out[k] = _strip_large(v, depth + 1)
            return out
        if isinstance(obj, list) and len(obj) > 30:
            return f"[{len(obj)} items omitted]"
        return obj

    compact = _strip_large(result)
    result_str = json.dumps(compact, default=str)
    if len(result_str) > max_chars:
        return result_str[:max_chars - 40] + ' ... [truncated]"}'
    return result_str


def _prune_history(messages: list[dict], max_chars: int = 300_000) -> list[dict]:
    """Drop oldest message pairs when serialised history exceeds *max_chars*.

    Always keeps the most recent user message so the conversation stays
    coherent.  Drops from the front in pairs (user+assistant) to maintain
    valid message ordering.
    """
    total = sum(len(json.dumps(m, default=str)) for m in messages)
    while total > max_chars and len(messages) > 2:
        dropped = messages.pop(0)
        total -= len(json.dumps(dropped, default=str))
    return messages


def build_system_prompt(session: ChatSession, ui_context: dict | None = None) -> str:
    parts = [
        "You are Princeps, a senior energy infrastructure analyst.",
        "You help developers assess sites for solar, wind, BESS, and data centre projects across the UK.",
        "",
        "You have tools for: solar simulation (SAM PvWatts), grid connection analysis (6 UK DNOs),",
        "pandapower Tier 2 power flow simulation (Newton-Raphson, N-1 contingency),",
        "demand forecasting (Prophet/TFT), financial modelling (CB7 assumptions), satellite analysis (GEE),",
        "live grid data (BMRS), environmental constraints (Natural England), and planning screening.",
        "",
        "Communication style:",
        "- Write like a senior consultant, not a chatbot. No emojis. No markdown tables.",
        "- Use short paragraphs and bullet points with hyphens, not pipes or headers.",
        "- Lead with the answer, then supporting data. Never repeat the question back.",
        "- Numbers should be inline: 'Capacity factor is 10.8%, yielding 47.3 GWh/yr' — not in tables.",
        "- For lists of substations or sites, use simple bullet format:",
        "  - Black Lake 132/11kV — 10.2km, 400MW headroom",
        "  - Ocker Hill B 275/132/33kV — 12.6km, 500MW headroom",
        "- NEVER use markdown emphasis: no **bold**, no __bold__, no *italic*, no _italic_, no `backticks`.",
        "- NEVER use ### headers, ~~strikethrough~~, or | table | syntax |.",
        "- The UI does not render markdown — asterisks and underscores appear literally. Write plain prose.",
        "- Keep responses under 200 words unless the user asks for detail.",
        "",
        "Scope rule — projects:",
        "- When the user says 'my projects', 'pipeline', 'portfolio', or 'projects', this means ONLY the projects in their active pipeline (portfolio_id IS NOT NULL in list_projects).",
        "- Do NOT reference the full REPD/TEC dataset (~4,600 rows) as 'your projects' — that is public planning data, not the user's pipeline.",
        "- list_projects defaults to pipeline scope. Use source='repd' or source='all' only if the user explicitly asks for public planning data or market-wide search.",
        "",
        "Scope rule — substations & headroom:",
        "- The grid_substations table mixes two sources: DNO-published registers (dno IN ('nged','spen','enwl','ssen','npg','ukpn')) and raw OSM pylon geometry (dno='osm').",
        "- All DNO-published substations HAVE demand_headroom_mw and gen_headroom_mw. OSM-geometry ones do NOT, by design — OSM is positional only.",
        "- When answering headroom / capacity / connection-feasibility questions, only consider DNO-published substations. Never say 'most substations lack headroom data' — that statement conflates the two sources and is wrong.",
        "- If a project's nearest DNO-published substation is further than 10km, say so explicitly rather than claiming no data exists.",
        "",
        "Tool usage:",
        "- Use tools proactively when they provide concrete data.",
        "- When discussing solar yield, run a simulation rather than estimating.",
        "- When mentioning any location, call zoom_to_location so the map re-centres to what you are reasoning about.",
        "- When a project context is present, call zoom_to_location on the project's lat/lon at the start of a thread so the user sees the map align with your analysis.",
        "- When results have geographic components, create a map layer.",
        "- UK typical capacity factors: solar 9-12%, onshore wind 26-30%, offshore wind 38-42%.",
        "",
        "Clarify before acting:",
        "- Before running an expensive tool chain (grid connection analysis, financial model, DSCR stress, site design), ask at most 1-2 short clarifying questions IF the request is genuinely ambiguous on a material parameter (e.g. 'BESS or solar?', 'what duration for the BESS?', 'PPA price assumption?').",
        "- Do NOT ask clarifying questions you can resolve from the page/project context you already have. If the active project says 'BESS 50 MW', don't ask 'what technology?'.",
        "- Cap clarifying questions at 2. After that, pick the most reasonable default and proceed, stating the assumption explicitly (e.g. 'Assuming 2-hour duration and £55/MWh PPA — say if you want different').",
        "",
        "Map-click coordinates:",
        "- When `ui_context.focus.type === 'location'` or `ui_context.picked_location` is present, the user has just clicked a point on the map. Treat those coords as the primary location for the next response. Do not ask for coordinates again — they are right there.",
        "",
        "Mission Control pill routing (BOT-PILL 2026-04-21):",
        "- 'biggest pipeline risk' / 'at risk' / 'flagged projects' -> call get_portfolio_risk_scan (single ranked pull; do NOT fan out get_project).",
        "- 'this week' / 'recent activity' / 'what changed' -> call get_recent_activity (returns grid_events + notifications + project updates for the window).",
        "- 'low headroom' / 'less than X MW headroom' / 'constrained substations' -> call list_low_headroom_projects with threshold_mw.",
        "- 'DSCR stress' / 'fail at PPA £X' / 'cashflow stress at £X' -> call run_portfolio_dscr_stress with ppa_price_mwh.",
        "- 'grid connection slip' / 'grid delay' -> call list_projects + forecast_grid_connection on the top 3-5 by capacity (already working).",
    ]

    if session.parcel_id:
        parts.append(f"\nActive site parcel: {session.parcel_id}")
        parts.append("You can use this parcel_id with site-specific tools without asking the user.")

    if session.uploaded_files:
        parts.append("\nUploaded files in this session:")
        for f in session.uploaded_files:
            parts.append(f"  - {f['filename']} ({f.get('type', 'unknown')}, {f.get('size_bytes', 0)} bytes)")

    if session.map_layers:
        parts.append(f"\nMap layers created in this session: {len(session.map_layers)}")

    # BOT-CHC 2026-04-19 — project summary block. Rendered even when the
    # frontend page_context hasn't arrived yet (turn 1), as long as the
    # session was created with a project_id that we pre-fetched. The block
    # wins over generic "I need a location" behaviour because we tell Claude
    # explicitly to use these values directly.
    proj = None
    if ui_context and isinstance(ui_context.get("page_context"), dict):
        proj = ui_context["page_context"].get("project") or None
    if not proj and session.project_summary:
        proj = session.project_summary
    if proj and proj.get("id"):
        parts.append("")
        name = proj.get("name") or "(unnamed)"
        pid = proj.get("id")
        parts.append(f"You are currently viewing project: {name} (id={pid}).")
        if proj.get("lat") is not None and proj.get("lon") is not None:
            parts.append(f"- Coordinates: {proj['lat']}, {proj['lon']}")
        details = []
        if proj.get("technology") or proj.get("tech"):
            details.append(f"Technology: {proj.get('technology') or proj.get('tech')}")
        if proj.get("capacity_mw") is not None:
            details.append(f"Capacity: {proj['capacity_mw']} MW")
        if proj.get("stage"):
            details.append(f"Stage: {proj['stage']}")
        if details:
            parts.append("- " + "  .  ".join(details))
        grid_bits = []
        if proj.get("dno"):
            grid_bits.append(f"DNO: {proj['dno']}")
        if proj.get("tec_mw") is not None:
            grid_bits.append(f"TEC contracted: {proj['tec_mw']} MW")
        if grid_bits:
            parts.append("- " + "  .  ".join(grid_bits))
        parts.append("Use these values directly — never ask the user for them.")

    # UI context — tells you what the user is currently seeing on screen
    if ui_context:
        parts.append("\n--- Current UI State (what the user sees right now) ---")
        if ui_context.get("workspace"):
            parts.append(f"Active workspace: {ui_context['workspace']}")
        if ui_context.get("view") or ui_context.get("viewMode"):
            parts.append(f"Active view: {ui_context.get('view') or ui_context.get('viewMode')}")
        if ui_context.get("stage"):
            parts.append(f"Workflow stage: {ui_context['stage']}")
        if ui_context.get("intent"):
            parts.append(f"Active intent/analysis: {ui_context['intent']}")
        if ui_context.get("lifecycle_tab"):
            parts.append(f"Active lifecycle tab: {ui_context['lifecycle_tab']}")
        if ui_context.get("parcel_id"):
            parts.append(f"Selected parcel: {ui_context['parcel_id']}")
        if ui_context.get("picked_location"):
            loc = ui_context["picked_location"]
            parts.append(f"Picked location: {loc.get('lat')}, {loc.get('lon')}")
        # BOT-CHC — page_context nested block adds selected_asset + pathway + year.
        pg = ui_context.get("page_context") if isinstance(ui_context.get("page_context"), dict) else None
        if pg:
            sel = pg.get("selected_asset")
            if sel and (sel.get("id") or sel.get("name")):
                parts.append(
                    f"Selected asset: {sel.get('kind') or 'asset'} "
                    f"{sel.get('name') or sel.get('id')}"
                )
            if pg.get("pathway"):
                parts.append(f"FES pathway: {pg['pathway']}")
            if pg.get("as_of_year"):
                parts.append(f"As-of year (scrubber): {pg['as_of_year']}")
            url_params = pg.get("url_params") or {}
            if url_params:
                kvs = ", ".join(f"{k}={v}" for k, v in url_params.items())
                parts.append(f"URL params: {kvs}")
        if ui_context.get("visible_data"):
            parts.append(f"Data visible on screen: {', '.join(ui_context['visible_data'])}")
        if ui_context.get("open_panels"):
            parts.append(f"Open panels: {', '.join(ui_context['open_panels'])}")
        if ui_context.get("map_layers"):
            parts.append(f"Active map layers: {', '.join(ui_context['map_layers'])}")
        parts.append("Use this context to give relevant, contextual answers.")
        parts.append("If the user asks 'what am I looking at?', describe their current view.")
        parts.append("PROACTIVE GUIDANCE: Based on the current workflow stage, suggest the most useful next action:")
        parts.append("- site stage → suggest drawing a boundary or searching for a location")
        parts.append("- study stage → suggest running feasibility, grid connection, or financial analysis")
        parts.append("- plan stage → suggest placing assets, running power flow, or finalising design")
        parts.append("- act stage → suggest downloading reports, creating pipeline entry, or exporting data")
        parts.append("Always end with a concrete suggestion the user can act on.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Streaming chat loop (SSE generator)
# ---------------------------------------------------------------------------

async def stream_chat_response(
    session: ChatSession,
    user_message: str,
    *,
    client: anthropic.AsyncAnthropic,
    model: str,
    pool,
    run_sam_subprocess,
    fetch_parcel_context,
    run_geeflow_subprocess=None,
    run_geoai_subprocess=None,
    ui_context: dict | None = None,
):
    """
    Async generator yielding SSE events for the chat response.

    Events:
      data: {"type": "text_delta", "content": "..."}
      data: {"type": "tool_call", "name": "...", "args": {...}}
      data: {"type": "tool_result", "name": "...", "result": {...}}
      data: {"type": "map_layer", "layer": {...}}
      data: {"type": "done"}
      data: {"type": "error", "message": "..."}
    """
    # BOT-CHC 2026-04-19 — thread the page_context snapshot onto the session.
    # This makes the most recent UI state reachable from the `current_page_context`
    # tool (Claude can refresh mid-turn if the user switches pages). We merge
    # rather than overwrite so legacy flat-shape fields still land.
    if ui_context:
        prev = session.ui_context or {}
        session.ui_context = {**prev, **ui_context}
        # Lazy-hydrate project_summary if the frontend just revealed a new
        # project_id and we have no summary yet (e.g. session was created
        # before the project was known).
        pg = ui_context.get("page_context") if isinstance(ui_context.get("page_context"), dict) else None
        pid_from_ctx = None
        if pg and isinstance(pg.get("project"), dict):
            pid_from_ctx = pg["project"].get("id")
        pid_from_ctx = pid_from_ctx or ui_context.get("project_id")
        if pid_from_ctx and not session.project_summary and pool is not None:
            if not session.project_id:
                session.project_id = pid_from_ctx
            try:
                await hydrate_project_summary(session, pid_from_ctx, pool)
            except Exception:
                pass

    # Append user message
    session.messages.append({"role": "user", "content": user_message})

    system_prompt = build_system_prompt(session, ui_context=ui_context or session.ui_context)
    max_turns = 10  # prevent infinite tool loops

    for turn in range(max_turns):
        # Prune old messages so accumulated tool results don't exceed context
        session.messages = _prune_history(session.messages)

        try:
            async with client.messages.stream(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=session.messages,
                tools=TOOLS,
            ) as stream:
                # Accumulate the response
                text_content = ""
                tool_uses = []

                async for event in stream:
                    if event.type == "content_block_start":
                        if hasattr(event.content_block, "type"):
                            if event.content_block.type == "tool_use":
                                tool_uses.append({
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                    "input_json": "",
                                })
                    elif event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            text_content += event.delta.text
                            yield f"data: {json.dumps({'type': 'text_delta', 'content': event.delta.text})}\n\n"
                        elif hasattr(event.delta, "partial_json"):
                            if tool_uses:
                                tool_uses[-1]["input_json"] += event.delta.partial_json

                # Get the full message
                response = await stream.get_final_message()

        except anthropic.APIError as exc:
            log.exception("Claude API error: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:300]})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Store assistant message
        assistant_content = []
        if text_content:
            assistant_content.append({"type": "text", "text": text_content})

        # Check if there are tool uses to process
        has_tool_use = response.stop_reason == "tool_use"

        if has_tool_use:
            # Process each tool use from the response
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

                    # Emit tool_call event
                    yield f"data: {json.dumps({'type': 'tool_call', 'name': block.name, 'args': block.input})}\n\n"

                    # Execute the tool
                    result = await execute_tool(
                        block.name, block.input, session,
                        pool=pool,
                        run_sam_subprocess=run_sam_subprocess,
                        fetch_parcel_context=fetch_parcel_context,
                        run_geeflow_subprocess=run_geeflow_subprocess,
                        run_geoai_subprocess=run_geoai_subprocess,
                    )

                    # Emit tool_result event
                    # Truncate large results for SSE (full result goes to Claude)
                    result_str = json.dumps(result, default=str)
                    display_result = result if len(result_str) < 5000 else {"summary": f"Result received ({len(result_str)} bytes)", "truncated": True}
                    yield f"data: {json.dumps({'type': 'tool_result', 'name': block.name, 'result': display_result}, default=str)}\n\n"

                    # If this was a map layer creation, emit map_layer event
                    if block.name == "create_map_layer" and session.map_layers:
                        layer = session.map_layers[-1]
                        yield f"data: {json.dumps({'type': 'map_layer', 'layer': layer}, default=str)}\n\n"

                    # If this was a zoom_to_location, emit zoom_to event
                    if block.name == "zoom_to_location":
                        yield f"data: {json.dumps({'type': 'zoom_to', 'lat': result['lat'], 'lon': result['lon'], 'zoom': result.get('zoom', 14), 'label': result.get('label')}, default=str)}\n\n"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": _compact_tool_result(result),
                    })

            # Store assistant message + tool results for next turn
            session.messages.append({"role": "assistant", "content": assistant_content})
            session.messages.append({"role": "user", "content": tool_results})

            # Continue loop — Claude will process tool results
            continue

        else:
            # Final text response — no more tool calls
            session.messages.append({"role": "assistant", "content": assistant_content or [{"type": "text", "text": text_content}]})
            await _db_persist_session(session)
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

    # Max turns reached
    await _db_persist_session(session)
    yield f"data: {json.dumps({'type': 'error', 'message': 'Maximum tool call depth reached'})}\n\n"
    yield f"data: {json.dumps({'type': 'done'})}\n\n"

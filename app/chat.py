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
# Session storage (in-memory, same pattern as jobs.py)
# ---------------------------------------------------------------------------

@dataclass
class ChatSession:
    id: str
    messages: list[dict] = field(default_factory=list)
    parcel_id: str | None = None
    uploaded_files: list[dict] = field(default_factory=list)
    map_layers: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


_sessions: dict[str, ChatSession] = {}


def create_session(parcel_id: str | None = None) -> ChatSession:
    sid = uuid.uuid4().hex[:12]
    session = ChatSession(id=sid, parcel_id=parcel_id)
    _sessions[sid] = session
    return session


def get_session(session_id: str) -> ChatSession | None:
    return _sessions.get(session_id)


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
        "name": "create_map_layer",
        "description": "Create a GeoJSON layer to display on the map. Use this to visualise analysis results geographically.",
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
                    "enum": ["circle", "fill", "line", "heatmap"],
                    "description": "MapLibre layer type",
                    "default": "circle",
                },
                "color": {"type": "string", "description": "Primary colour for the layer", "default": "#00e5ff"},
            },
            "required": ["name", "geojson"],
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
) -> Any:
    """Execute a tool call and return the result dict."""
    try:
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

        elif name == "create_map_layer":
            layer_id = f"chat-{uuid.uuid4().hex[:8]}"
            layer = {
                "id": layer_id,
                "name": args["name"],
                "geojson": args["geojson"],
                "layer_type": args.get("layer_type", "circle"),
                "color": args.get("color", "#00e5ff"),
            }
            session.map_layers.append(layer)
            return {"layer_id": layer_id, "name": args["name"], "feature_count": len(args["geojson"].get("features", []))}

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

def build_system_prompt(session: ChatSession) -> str:
    parts = [
        "You are Feasibly AI, an expert energy analyst and solar site feasibility assistant.",
        "You help users analyse sites for renewable energy projects across the UK.",
        "You have access to tools for solar simulation (NREL SAM/PvWatts v8), grid connection analysis,",
        "energy pricing (Octopus Agile), demand forecasting, planning applications, BIPV analysis,",
        "bill of materials generation, and live National Grid data.",
        "",
        "Guidelines:",
        "- Use tools proactively when they can provide concrete data to support your analysis.",
        "- When discussing solar yield, always run a simulation rather than estimating.",
        "- Present numerical results clearly with units.",
        "- When results have geographic components, offer to create a map layer to visualise them.",
        "- Be concise but thorough. Prioritise actionable insights.",
        "- For UK-specific context: typical capacity factors are 9-12%, Agile tariffs vary by region.",
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
    # Append user message
    session.messages.append({"role": "user", "content": user_message})

    system_prompt = build_system_prompt(session)
    max_turns = 10  # prevent infinite tool loops

    for turn in range(max_turns):
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

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })

            # Store assistant message + tool results for next turn
            session.messages.append({"role": "assistant", "content": assistant_content})
            session.messages.append({"role": "user", "content": tool_results})

            # Continue loop — Claude will process tool results
            continue

        else:
            # Final text response — no more tool calls
            session.messages.append({"role": "assistant", "content": assistant_content or [{"type": "text", "text": text_content}]})
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

    # Max turns reached
    yield f"data: {json.dumps({'type': 'error', 'message': 'Maximum tool call depth reached'})}\n\n"
    yield f"data: {json.dumps({'type': 'done'})}\n\n"

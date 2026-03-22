#!/usr/bin/env python3
"""
Princeps MCP Server — Model Context Protocol interface for AI agents.

Lets Claude Desktop, GPT, and other MCP-compatible AI agents query
Princeps's grid, environmental, and site assessment data.

Run: python mcp_server.py
Register in Claude Desktop: ~/.claude/claude_desktop_config.json
"""

import json
import sys
import httpx

BASE = "http://localhost:8000"
TIMEOUT = 30


async def _get(path: str, params: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def _post(path: str, params: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()


TOOLS = [
    {
        "name": "assess_site",
        "description": "Run grid connection feasibility assessment at a UK location. Returns nearest substations, headroom, queue depth, connection cost, and GO/CAUTION/NO-GO verdict.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number", "description": "Latitude (WGS84)"},
                "lon": {"type": "number", "description": "Longitude (WGS84)"},
                "capacity_mw": {"type": "number", "description": "Proposed capacity in MW", "default": 5},
                "technology": {"type": "string", "description": "solar, wind, bess, or data_centre", "default": "solar"},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "search_substations",
        "description": "Find UK grid substations near a location with capacity headroom data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "radius_km": {"type": "number", "default": 20},
                "min_voltage_kv": {"type": "number", "default": 33},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "live_grid_status",
        "description": "Get real-time UK grid status: generation mix (wind/solar/nuclear/gas), carbon intensity, frequency, wholesale price.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "constraint_forecast",
        "description": "Get 48-hour grid constraint forecast showing which UK transmission boundaries are at risk of congestion.",
        "inputSchema": {
            "type": "object",
            "properties": {"hours_ahead": {"type": "integer", "default": 48}},
        },
    },
    {
        "name": "environmental_check",
        "description": "Check environmental constraints near a UK location: SSSI, AONB, flood zones, listed buildings, ancient woodland.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "radius_m": {"type": "number", "default": 2000},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "dc_score",
        "description": "Score a site for data centre suitability (0-100) considering grid headroom, fibre proximity, water stress, carbon intensity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lat": {"type": "number"}, "lon": {"type": "number"},
                "capacity_mw": {"type": "number", "default": 30},
            },
            "required": ["lat", "lon"],
        },
    },
    {
        "name": "queue_depth",
        "description": "Get connection queue depth per UK substation — how many MW are waiting, estimated wait time.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pricing_regional",
        "description": "Get current wholesale electricity prices for all 14 UK DNO regions.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


async def handle_tool(name: str, args: dict) -> str:
    try:
        if name == "assess_site":
            r = await _post("/api/grid/assess", {
                "lat": args["lat"], "lon": args["lon"],
                "capacity_mw": args.get("capacity_mw", 5),
                "technology": args.get("technology", "solar"),
            })
        elif name == "search_substations":
            r = await _get("/grid/substations", {
                "lat": args["lat"], "lon": args["lon"],
                "radius_km": args.get("radius_km", 20),
                "min_voltage_kv": args.get("min_voltage_kv", 33),
            })
        elif name == "live_grid_status":
            r = await _get("/api/grid/live-status")
        elif name == "constraint_forecast":
            r = await _get("/api/grid/constraints", {"hours_ahead": args.get("hours_ahead", 48)})
            # Simplify — remove timeseries bulk data
            if "timeseries" in r:
                del r["timeseries"]
        elif name == "environmental_check":
            r = await _get("/api/grid/environmental-constraints", {
                "lat": args["lat"], "lon": args["lon"],
                "radius_m": args.get("radius_m", 2000),
            })
        elif name == "dc_score":
            r = await _post("/api/dc/score", {
                "lat": args["lat"], "lon": args["lon"],
                "capacity_mw": args.get("capacity_mw", 30),
            })
        elif name == "queue_depth":
            r = await _get("/api/grid/queue-depth")
            # Return summary not full GeoJSON
            features = r.get("features", [])
            r = {"total_substations": len(features), "top_10": [
                f["properties"] for f in features[:10]
            ]}
        elif name == "pricing_regional":
            r = await _get("/api/pricing/regional")
        else:
            r = {"error": f"Unknown tool: {name}"}

        return json.dumps(r, indent=2, default=str)
    except httpx.ConnectError:
        return json.dumps({"error": "Princeps backend not running on localhost:8000"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── MCP stdio transport ──────────────────────────────────────────────────────

async def main():
    """Run as MCP server over stdio."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as types
    except ImportError:
        # Fallback: simple JSON-RPC over stdio
        print("MCP SDK not installed. Install: pip install mcp", file=sys.stderr)
        print("Running in standalone test mode...", file=sys.stderr)
        import asyncio
        # Test all tools
        for tool in TOOLS:
            test_args = {}
            for k, v in tool["inputSchema"].get("properties", {}).items():
                if k == "lat": test_args["lat"] = 52.0
                elif k == "lon": test_args["lon"] = -1.0
            result = await handle_tool(tool["name"], test_args)
            print(f"\n=== {tool['name']} ===")
            print(result[:300])
        return

    server = Server("princeps")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=t["name"], description=t["description"], inputSchema=t["inputSchema"])
            for t in TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        result = await handle_tool(name, arguments)
        return [types.TextContent(type="text", text=result)]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

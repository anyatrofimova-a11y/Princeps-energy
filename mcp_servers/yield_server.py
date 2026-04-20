#!/usr/bin/env python3
"""Princeps yield capability MCP server (SAM PvWatts)."""

from mcp_servers._base import make_tool, get, post, safe, main

TOOLS = [
    make_tool("run_sam_pvwatts", "Run NREL SAM PvWattsv8 for a UK site. Returns annual MWh + CF.",
        {"type": "object",
         "properties": {
             "lat": {"type": "number"}, "lon": {"type": "number"},
             "capacity_mw_dc": {"type": "number", "default": 10},
             "dc_ac_ratio": {"type": "number", "default": 1.3},
             "tilt": {"type": "number", "default": 30},
             "azimuth": {"type": "number", "default": 180}},
         "required": ["lat", "lon"]}),
    make_tool("annual_yield", "Annual yield summary (P50/P90 MWh, capacity factor).",
        {"type": "object",
         "properties": {"lat": {"type": "number"}, "lon": {"type": "number"},
                        "capacity_mw_dc": {"type": "number", "default": 10}},
         "required": ["lat", "lon"]}),
    make_tool("monthly_profile", "Monthly generation profile (12 values MWh).",
        {"type": "object",
         "properties": {"lat": {"type": "number"}, "lon": {"type": "number"},
                        "capacity_mw_dc": {"type": "number", "default": 10}},
         "required": ["lat", "lon"]}),
]


async def dispatch(name, args):
    if name in ("run_sam_pvwatts", "annual_yield", "monthly_profile"):
        r = await safe(post("/api/yield/sam", json_body=args), name)
        if name == "annual_yield" and isinstance(r, dict):
            return {k: r.get(k) for k in ("annual_mwh", "capacity_factor", "p50_mwh", "p90_mwh") if k in r}
        if name == "monthly_profile" and isinstance(r, dict):
            return {"monthly_mwh": r.get("monthly_mwh", [])}
        return r
    return {"error": f"Unknown tool: {name}"}


if __name__ == "__main__":
    main("princeps-yield", TOOLS, dispatch)

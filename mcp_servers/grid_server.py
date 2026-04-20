#!/usr/bin/env python3
"""Princeps grid capability MCP server."""

from mcp_servers._base import make_tool, get, post, safe, main

TOOLS = [
    make_tool("search_substations", "Find UK grid substations near a location with capacity headroom.",
        {"type": "object",
         "properties": {
             "lat": {"type": "number"}, "lon": {"type": "number"},
             "radius_km": {"type": "number", "default": 20},
             "min_voltage_kv": {"type": "number", "default": 33}},
         "required": ["lat", "lon"]}),
    make_tool("get_headroom", "Get current headroom (MW) at a substation.",
        {"type": "object",
         "properties": {"substation_id": {"type": "string"}},
         "required": ["substation_id"]}),
    make_tool("run_power_flow", "Run AC power flow + N-1 contingency via pandapower.",
        {"type": "object",
         "properties": {
             "substation_id": {"type": "string"},
             "injection_mw": {"type": "number", "default": 10}},
         "required": ["substation_id"]}),
    make_tool("estimate_connection_cost", "Estimate grid connection cost (P10/P50/P90) for a site.",
        {"type": "object",
         "properties": {
             "lat": {"type": "number"}, "lon": {"type": "number"},
             "capacity_mw": {"type": "number", "default": 10}},
         "required": ["lat", "lon"]}),
]


async def dispatch(name, args):
    if name == "search_substations":
        return await safe(get("/grid/substations", {
            "lat": args["lat"], "lon": args["lon"],
            "radius_km": args.get("radius_km", 20),
            "min_voltage_kv": args.get("min_voltage_kv", 33)}), name)
    if name == "get_headroom":
        return await safe(get(f"/api/grid/substation/{args['substation_id']}"), name)
    if name == "run_power_flow":
        return await safe(post("/api/grid/power-flow", json_body={
            "substation_id": args["substation_id"],
            "injection_mw": args.get("injection_mw", 10)}), name)
    if name == "estimate_connection_cost":
        return await safe(post("/api/grid/estimate-cost", json_body={
            "lat": args["lat"], "lon": args["lon"],
            "capacity_mw": args.get("capacity_mw", 10)}), name)
    return {"error": f"Unknown tool: {name}"}


if __name__ == "__main__":
    main("princeps-grid", TOOLS, dispatch)

#!/usr/bin/env python3
"""Princeps environment capability MCP server."""

from mcp_servers._base import make_tool, get, post, safe, main

TOOLS = [
    make_tool("glint_glare", "SGHAT-style glint & glare assessment for PV panels.",
        {"type": "object",
         "properties": {
             "lat": {"type": "number"}, "lon": {"type": "number"},
             "tilt": {"type": "number", "default": 30},
             "azimuth": {"type": "number", "default": 180},
             "receptor_lat": {"type": "number"},
             "receptor_lon": {"type": "number"}},
         "required": ["lat", "lon"]}),
    make_tool("noise_propagation", "ISO 9613-2 noise propagation to nearest receptor (dB).",
        {"type": "object",
         "properties": {
             "source_lat": {"type": "number"}, "source_lon": {"type": "number"},
             "source_db": {"type": "number", "default": 75}},
         "required": ["source_lat", "source_lon"]}),
    make_tool("flood_risk", "Environment Agency flood zone at a site.",
        {"type": "object",
         "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
         "required": ["lat", "lon"]}),
    make_tool("bng_estimate", "Biodiversity net gain (%) uplift estimate.",
        {"type": "object",
         "properties": {
             "lat": {"type": "number"}, "lon": {"type": "number"},
             "area_ha": {"type": "number"}},
         "required": ["lat", "lon"]}),
]


async def dispatch(name, args):
    if name == "glint_glare":
        return await safe(post("/api/environment/glare", json_body=args), name)
    if name == "noise_propagation":
        return await safe(post("/api/environment/noise", json_body=args), name)
    if name == "flood_risk":
        return await safe(get("/api/environment/flood-zone", params=args), name)
    if name == "bng_estimate":
        return await safe(post("/api/environment/bng", json_body=args), name)
    return {"error": f"Unknown tool: {name}"}


if __name__ == "__main__":
    main("princeps-environment", TOOLS, dispatch)

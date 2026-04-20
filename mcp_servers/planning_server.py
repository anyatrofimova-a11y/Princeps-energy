#!/usr/bin/env python3
"""Princeps planning capability MCP server."""

from mcp_servers._base import make_tool, get, post, safe, main

TOOLS = [
    make_tool("predict_approval", "XGBoost probability of planning approval for a site.",
        {"type": "object",
         "properties": {
             "lat": {"type": "number"}, "lon": {"type": "number"},
             "capacity_mw": {"type": "number"},
             "technology": {"type": "string", "default": "solar"}},
         "required": ["lat", "lon"]}),
    make_tool("find_similar_repd", "Find similar REPD-recorded decisions.",
        {"type": "object",
         "properties": {
             "lat": {"type": "number"}, "lon": {"type": "number"},
             "technology": {"type": "string", "default": "solar"},
             "limit": {"type": "integer", "default": 10}},
         "required": ["lat", "lon"]}),
    make_tool("check_lpa_speed", "Median decision days for the LPA covering this site.",
        {"type": "object",
         "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
         "required": ["lat", "lon"]}),
    make_tool("list_constraints", "Planning constraints (Green Belt, AONB, SSSI, etc).",
        {"type": "object",
         "properties": {"lat": {"type": "number"}, "lon": {"type": "number"},
                        "radius_m": {"type": "number", "default": 2000}},
         "required": ["lat", "lon"]}),
]


async def dispatch(name, args):
    if name == "predict_approval":
        return await safe(post("/api/planning/ml/predict", json_body=args), name)
    if name == "find_similar_repd":
        return await safe(get("/api/planning/ml/similar", params=args), name)
    if name == "check_lpa_speed":
        return await safe(get("/api/planning/lpa-profile", params={"lat": args["lat"], "lon": args["lon"]}), name)
    if name == "list_constraints":
        return await safe(get("/api/grid/environmental-constraints", params=args), name)
    return {"error": f"Unknown tool: {name}"}


if __name__ == "__main__":
    main("princeps-planning", TOOLS, dispatch)

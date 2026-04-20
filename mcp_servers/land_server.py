#!/usr/bin/env python3
"""Princeps land & ownership capability MCP server."""

from mcp_servers._base import make_tool, get, post, safe, main

TOOLS = [
    make_tool("lookup_parcel", "Look up an HMLR INSPIRE parcel by id or coords.",
        {"type": "object",
         "properties": {
             "inspire_id": {"type": "string"},
             "lat": {"type": "number"}, "lon": {"type": "number"}}}),
    make_tool("get_owner", "Ownership for a parcel (name + recent transactions).",
        {"type": "object",
         "properties": {"inspire_id": {"type": "string"}},
         "required": ["inspire_id"]}),
    make_tool("compute_buildable_area", "Compute buildable hectares after exclusion overlays.",
        {"type": "object",
         "properties": {
             "inspire_id": {"type": "string"},
             "exclude": {"type": "array", "items": {"type": "string"},
                         "default": ["flood3", "sssi", "aonb", "alc1", "alc2"]}}}),
    make_tool("list_adjacent_owners", "Owners of parcels within N metres.",
        {"type": "object",
         "properties": {"inspire_id": {"type": "string"},
                        "radius_m": {"type": "number", "default": 500}},
         "required": ["inspire_id"]}),
]


async def dispatch(name, args):
    if name == "lookup_parcel":
        return await safe(get("/api/land/parcel", params=args), name)
    if name == "get_owner":
        return await safe(get(f"/api/land/parcel/{args['inspire_id']}/owner"), name)
    if name == "compute_buildable_area":
        return await safe(post("/api/design/buildable-area", json_body=args), name)
    if name == "list_adjacent_owners":
        return await safe(get(f"/api/land/parcel/{args['inspire_id']}/neighbours",
                              params={"radius_m": args.get("radius_m", 500)}), name)
    return {"error": f"Unknown tool: {name}"}


if __name__ == "__main__":
    main("princeps-land", TOOLS, dispatch)

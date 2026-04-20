#!/usr/bin/env python3
"""Princeps finance capability MCP server."""

from mcp_servers._base import make_tool, get, post, safe, main

TOOLS = [
    make_tool("project_finance", "Full project finance model (NPV, IRR, LCOE, payback).",
        {"type": "object",
         "properties": {
             "capacity_mw": {"type": "number"},
             "capex_gbp_per_mw": {"type": "number", "default": 700000},
             "opex_gbp_per_mw_yr": {"type": "number", "default": 15000},
             "ppa_gbp_per_mwh": {"type": "number", "default": 55},
             "capacity_factor": {"type": "number", "default": 0.11},
             "lifetime_years": {"type": "integer", "default": 25},
             "discount_rate": {"type": "number", "default": 0.08}},
         "required": ["capacity_mw"]}),
    make_tool("lcoe", "Levelised cost of energy (£/MWh).",
        {"type": "object",
         "properties": {"capacity_mw": {"type": "number"},
                        "capex_gbp_per_mw": {"type": "number", "default": 700000}},
         "required": ["capacity_mw"]}),
    make_tool("npv_irr", "Compute NPV + IRR from cash-flow inputs.",
        {"type": "object",
         "properties": {"cashflows": {"type": "array", "items": {"type": "number"}},
                        "discount_rate": {"type": "number", "default": 0.08}},
         "required": ["cashflows"]}),
    make_tool("ppa_model", "PPA price structure comparison.",
        {"type": "object",
         "properties": {
             "capacity_mw": {"type": "number"},
             "term_years": {"type": "integer", "default": 15},
             "structure": {"type": "string", "default": "baseload",
                           "enum": ["baseload", "as_produced", "shape"]}},
         "required": ["capacity_mw"]}),
]


async def dispatch(name, args):
    if name == "project_finance":
        return await safe(post("/api/finance/project", json_body=args), name)
    if name == "lcoe":
        return await safe(post("/api/finance/lcoe", json_body=args), name)
    if name == "npv_irr":
        return await safe(post("/api/finance/npv-irr", json_body=args), name)
    if name == "ppa_model":
        return await safe(post("/api/finance/ppa", json_body=args), name)
    return {"error": f"Unknown tool: {name}"}


if __name__ == "__main__":
    main("princeps-finance", TOOLS, dispatch)

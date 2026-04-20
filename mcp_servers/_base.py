"""Shared transport + stdio-dispatch helpers for Princeps MCP servers."""

import json
import sys
import asyncio
import httpx

BASE = "http://localhost:8000"
TIMEOUT = 30


async def get(path, params=None):
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def post(path, params=None, json_body=None):
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{BASE}{path}", params=params, json=json_body)
        r.raise_for_status()
        return r.json()


async def safe(coro, label):
    try:
        return await coro
    except httpx.ConnectError:
        return {"error": f"{label}: backend unreachable at {BASE}", "stub": True}
    except httpx.HTTPStatusError as e:
        return {"error": f"{label}: {e.response.status_code}", "body": e.response.text[:300], "stub": True}
    except Exception as e:
        return {"error": f"{label}: {type(e).__name__}: {e}", "stub": True}


def make_tool(name, description, schema):
    return {"name": name, "description": description, "inputSchema": schema}


async def run_server(server_name, tools, dispatch):
    """Run as MCP server over stdio, falling back to standalone test mode."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        import mcp.types as types
    except ImportError:
        print(f"[{server_name}] MCP SDK not installed — running in test mode.", file=sys.stderr)
        for tool in tools:
            args = {}
            for k in tool["inputSchema"].get("properties", {}):
                if k == "lat": args["lat"] = 52.0
                elif k == "lon": args["lon"] = -1.0
                elif k == "site_id": args["site_id"] = "test"
            result = await dispatch(tool["name"], args)
            print(f"\n=== {tool['name']} ===")
            print(json.dumps(result, indent=2, default=str)[:400])
        return

    server = Server(server_name)

    @server.list_tools()
    async def list_tools():
        return [types.Tool(name=t["name"], description=t["description"], inputSchema=t["inputSchema"]) for t in tools]

    @server.call_tool()
    async def call_tool(name, arguments):
        result = await dispatch(name, arguments)
        text = json.dumps(result, indent=2, default=str)
        return [types.TextContent(type="text", text=text)]

    async with stdio_server() as (rs, ws):
        await server.run(rs, ws, server.create_initialization_options())


def main(server_name, tools, dispatch):
    asyncio.run(run_server(server_name, tools, dispatch))

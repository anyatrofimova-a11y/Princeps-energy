"""Princeps capability-specific MCP servers.

Six servers (grid, planning, land, yield, finance, environment), each a thin
HTTP wrapper over the Princeps backend at localhost:8000. Share the _base
helper module for transport and stdio dispatch.

Run any server standalone:  python -m mcp_servers.grid_server
Register with Claude Desktop: see README.md.
"""

# Princeps MCP Servers (Capability Split)

Six capability-specific MCP servers, each a thin HTTP wrapper over the Princeps
backend running at `http://localhost:8000`. Use them when you want Claude /
another MCP client to reason about a single capability without the full
monolithic `mcp_server.py` tool surface.

| Server | File | Tools |
|--------|------|-------|
| grid | `grid_server.py` | `search_substations`, `get_headroom`, `run_power_flow`, `estimate_connection_cost` |
| planning | `planning_server.py` | `predict_approval`, `find_similar_repd`, `check_lpa_speed`, `list_constraints` |
| land | `land_server.py` | `lookup_parcel`, `get_owner`, `compute_buildable_area`, `list_adjacent_owners` |
| yield | `yield_server.py` | `run_sam_pvwatts`, `annual_yield`, `monthly_profile` |
| finance | `finance_server.py` | `project_finance`, `lcoe`, `npv_irr`, `ppa_model` |
| environment | `environment_server.py` | `glint_glare`, `noise_propagation`, `flood_risk`, `bng_estimate` |

## Requirements

- Princeps backend on `localhost:8000` (`uvicorn app.main:app`).
- Optional: `pip install mcp` for real stdio transport. Without it, `python -m
  mcp_servers.grid_server` runs in test mode and prints one sample per tool.

## Register with Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "princeps-grid":        { "command": "python", "args": ["-m", "mcp_servers.grid_server"],        "cwd": "/Users/anyatrofimova/feasibly" },
    "princeps-planning":    { "command": "python", "args": ["-m", "mcp_servers.planning_server"],    "cwd": "/Users/anyatrofimova/feasibly" },
    "princeps-land":        { "command": "python", "args": ["-m", "mcp_servers.land_server"],        "cwd": "/Users/anyatrofimova/feasibly" },
    "princeps-yield":       { "command": "python", "args": ["-m", "mcp_servers.yield_server"],       "cwd": "/Users/anyatrofimova/feasibly" },
    "princeps-finance":     { "command": "python", "args": ["-m", "mcp_servers.finance_server"],     "cwd": "/Users/anyatrofimova/feasibly" },
    "princeps-environment": { "command": "python", "args": ["-m", "mcp_servers.environment_server"], "cwd": "/Users/anyatrofimova/feasibly" }
  }
}
```

Backend uses Opus 4.7 (`claude-opus-4-7`) throughout the agent modules.

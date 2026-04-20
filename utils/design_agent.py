"""Design agent — a Claude tool-using agent that edits the design doc via
structured tool calls. The agent has access to:
  - set_param(name, value)           — change a design parameter
  - set_capacity(mw)                  — shortcut for capacity_mw
  - add_constraint(code, severity)    — reject a stroke / note a designation
  - optimise_for(objective)           — kick the scipy optimiser
  - propose_alternative(workload)     — switch workload (solar ↔ bess ↔ dc)
  - ask_kpi_explanation(kpi_key)      — produce a one-line "why"

After each tool call the caller re-runs /api/design/generate so the agent
operates on fresh KPIs. The return envelope contains:
  { reply: str, tool_calls: [...], params: {...} updated, reasoning: [...] }
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("princeps.design.agent")


AGENT_TOOLS = [
    {
        "name": "set_param",
        "description": "Change a single design parameter by name (e.g. duration_h, tilt_deg, pue_target).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":  {"type": "string"},
                "value": {"type": "number"},
            },
            "required": ["name", "value"],
        },
    },
    {
        "name": "set_capacity",
        "description": "Set the project capacity in MW.",
        "input_schema": {
            "type": "object",
            "properties": {"mw": {"type": "number"}},
            "required": ["mw"],
        },
    },
    {
        "name": "optimise_for",
        "description": "Run scipy optimisation for the given objective: irr | lcoe | yield | capex | npv.",
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string"}},
            "required": ["objective"],
        },
    },
    {
        "name": "propose_alternative",
        "description": "Switch workload to explore an alternative (bess, solar, dc, hybrid).",
        "input_schema": {
            "type": "object",
            "properties": {"workload": {"type": "string"}},
            "required": ["workload"],
        },
    },
    {
        "name": "finalise",
        "description": "Confirm the current design and return a short summary. Must be called last.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]


SYSTEM_PROMPT = """You are the Princeps design agent — a senior UK energy
engineer embedded in a site design canvas. Your job: edit the live design
doc to match the user's ask. Use tool calls to modify parameters. Call
`finalise` when done with a 2-3 sentence rationale.

Keep in mind:
 - UK 2026 conditions (Dynamic Containment £17/MW/h, BM revenue realistic)
 - Grid headroom is hard — never ask for capacity beyond substation limit
   (the caller enforces this anyway, but explain the cap in your summary)
 - LFP chemistry by default for BESS; fixed-tilt for solar PV
 - BS 8629:2019 fire breaks non-negotiable
 - Planning risk is your friend — propose a smaller design if it unlocks
   a cleaner planning pathway

You should make at most 4 tool calls before finalising."""


def agent_tools_schema():
    return AGENT_TOOLS


async def run_agent(claude_client, model: str, *,
                     workload: str, params: dict, prompt: str,
                     context: dict | None = None,
                     max_turns: int = 6) -> dict[str, Any]:
    """Run the tool-using design agent.

    Returns { reply: str, params: dict, tool_calls: [...], reasoning: [...] }.
    """
    if not claude_client:
        return {
            "reply": "Claude client unavailable; running deterministic fallback.",
            "params": params, "tool_calls": [],
            "reasoning": ["Agent disabled — apply user's ask via deterministic rules."],
        }

    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                f"Workload: {workload}\n"
                f"Current params: {json.dumps(params, default=str)}\n"
                f"Context: {json.dumps(context or {}, default=str)[:600]}\n\n"
                f"User ask: {prompt}"
            ),
        }
    ]

    new_params = dict(params)
    tool_calls_log: list[dict] = []
    final_reply = ""

    for _ in range(max_turns):
        try:
            resp = await claude_client.messages.create(
                model=model,
                max_tokens=900,
                system=SYSTEM_PROMPT,
                tools=AGENT_TOOLS,
                messages=messages,
            )
        except Exception as e:
            log.warning("agent call failed: %s", e)
            return {
                "reply": f"Agent error: {e}",
                "params": new_params, "tool_calls": tool_calls_log, "reasoning": [],
            }

        # Gather any text reply
        for b in resp.content:
            if b.type == "text" and b.text:
                final_reply = b.text

        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            break

        # Execute each tool call against local state + build tool_result messages
        tool_results = []
        for tu in tool_uses:
            name, inp = tu.name, tu.input or {}
            result, summary = _dispatch_tool(name, inp, new_params, workload)
            tool_calls_log.append({"name": name, "input": inp, "summary": summary})
            if name == "set_param" and inp.get("name"):
                new_params[inp["name"]] = inp.get("value")
            elif name == "set_capacity" and inp.get("mw") is not None:
                new_params["capacity_mw"] = inp["mw"]
            elif name == "propose_alternative" and inp.get("workload"):
                workload = inp["workload"]
            tool_results.append({
                "type": "tool_result", "tool_use_id": tu.id,
                "content": json.dumps(result)[:600],
            })

        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": tool_results})

        # If the agent called `finalise`, stop the loop.
        if any(tu.name == "finalise" for tu in tool_uses):
            for tu in tool_uses:
                if tu.name == "finalise":
                    final_reply = (tu.input or {}).get("summary") or final_reply
            break

    reasoning = [c["summary"] for c in tool_calls_log if c.get("summary")]
    if final_reply:
        reasoning.insert(0, final_reply)
    return {
        "reply": final_reply or "Design updated.",
        "params": new_params,
        "workload": workload,
        "tool_calls": tool_calls_log,
        "reasoning": reasoning[:8],
    }


def _dispatch_tool(name: str, inp: dict, params: dict, workload: str):
    """Return (result_for_claude, human_summary)."""
    if name == "set_param":
        return ({"ok": True}, f"Set {inp.get('name')} → {inp.get('value')}")
    if name == "set_capacity":
        return ({"ok": True}, f"Capacity set to {inp.get('mw')} MW")
    if name == "optimise_for":
        # Actual scipy run happens at the endpoint level (kept async-free here).
        return ({"ok": True, "queued": True},
                f"Queued optimisation for {inp.get('objective')} — caller will run scipy.")
    if name == "propose_alternative":
        return ({"ok": True, "workload": inp.get("workload")},
                f"Switched workload to {inp.get('workload')}")
    if name == "finalise":
        return ({"ok": True}, None)
    return ({"ok": False, "error": f"unknown tool {name}"}, f"Unknown tool {name}")

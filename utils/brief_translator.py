"""Natural-language → structured plan translator.

Two layers:

  1. Slash-command parser: '/status', '/list', '/trigger <agent>',
     '/cancel <id>', '/help'. No LLM call needed.
  2. Claude orchestrator: turns free-form messages into a multi-step
     PLAN (1..N tasks), with dependencies, mixing build / research /
     agent_trigger / ask intents.

Output schema:

  {
    "kind": "ask" | "plan",
    "answer": "<inline answer when kind=ask>",
    "plan_summary": "<one-line summary of what will happen>",
    "tasks": [
      {
        "step": 1, "intent": "build" | "research" | "agent_trigger",
        "title": "<short>", "brief": "<full brief or agent_name>",
        "context_paths": [...],   // for build/research
        "agent_name": "<name>",    // for agent_trigger only
        "priority": 1-9,
        "depends_on_steps": [1,2]  // step numbers from this same plan
      }
    ]
  }
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)


# Slash commands we handle without invoking Claude.
SLASH_COMMANDS = {"/help", "/status", "/list", "/list-queue", "/trigger",
                  "/cancel", "/show", "/ship", "/research"}


_ORCHESTRATOR_PROMPT = """You are the orchestrator for Princeps' builder agent layer. The platform owner is sending you natural-language requests over WhatsApp. Your job is to convert each request into a structured PLAN of one or more tasks.

Tasks fall into three intents:

  build           Edit the Princeps repo (anyatrofimova-a11y/Princeps-energy).
                  The builder agent will then ask Claude for a diff and
                  open a PR.

  research        Investigate the web (competitors, regulators, APIs,
                  papers) and produce a markdown summary committed under
                  docs/research/<slug>.md. Uses WebSearch.

  agent_trigger   Fire one of the already-deployed monitoring agents
                  immediately (ignore its normal cadence). Valid agent
                  names:
                    ontology_coherence, schema_drift, ontology_backfill,
                    connector_health,
                    docket_watch, planning_constraint_watch, ar7_window_monitor,
                    headroom_patrol, reinforcement_cost_refresh,
                    sanctions_rescreen,
                    obligation_deadline, doc_change_watcher,
                    da_price_reactor, repd_cross_val,
                    twin_replay, council_convener

Use multi-step plans when the request implies more than one outcome.
Examples:

  "build me a competitor watcher for halcyon, hypercube and glint solar"
  → 4 tasks:
      1 research: scrape each competitor's site, summarise pricing + features
      2 build:    add utils/competitor_watcher.py that re-runs that summary daily
      3 build:    add app/routers/competitors.py with GET endpoint
      4 build:    add feasi-frontend/src/components/workspace/CompetitorPanel.jsx
                  (depends_on_steps: [3])

  "re-enrich all open dockets and tell me what changed"
  → 1 task:
      1 agent_trigger: docket_watch (depends_on_steps: [])

  "what's in the queue?"
  → kind=ask, answer=<inline reply listing the queue> (the dispatcher
    will fill the queue contents for you — just say "show queue").

Output JSON only. Schema:

  {
    "kind": "ask" | "plan",
    "answer": "<for kind=ask only>",
    "plan_summary": "<one-line, present tense; for kind=plan>",
    "tasks": [
      {
        "step": <int 1..N>,
        "intent": "build" | "research" | "agent_trigger",
        "title": "<short imperative, ≤80 chars>",
        "brief": "<for build/research: full brief; for agent_trigger: ignored>",
        "context_paths": ["repo/path", ...],
        "agent_name": "<for agent_trigger only>",
        "priority": <1-9>,
        "depends_on_steps": [<int>, ...]
      }
    ]
  }

Hints for context_paths (pick the most relevant 2-5):
  - new backend route → ["app/main.py", "app/routers/<existing>.py"]
  - new ingester → ["utils/<closest existing>.py", "requirements.txt"]
  - new agent module → ["agents/lib/base.py", ".github/workflows/deploy.yml"]
  - frontend component → ["feasi-frontend/src/components/workspace/<related>.jsx"]
  - schema change → ["migrations/<latest>.sql"]

Default priority 5. Raise to 3 for "urgent"/"asap"/"now", 7 for "later"/"low priority".
Refuse (kind=ask) if the request would touch .github/workflows or commit secrets.

User message follows.
"""


def parse_slash_command(text: str) -> dict[str, Any] | None:
    """If `text` starts with a recognised slash command, return a structured
    descriptor; otherwise None."""
    t = text.strip()
    if not t.startswith("/"):
        return None
    parts = t.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    if cmd not in SLASH_COMMANDS:
        return None
    return {"slash": True, "command": cmd, "args": args}


async def translate_brief(text: str) -> dict[str, Any]:
    """Map a free-form WhatsApp message to either a kind=ask reply or a
    kind=plan multi-step plan."""
    slash = parse_slash_command(text)
    if slash:
        return {"kind": "slash", **slash}

    api_key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"kind": "ask",
                "answer": "Orchestrator offline: no ANTHROPIC_API_KEY configured."}
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    async with httpx.AsyncClient(timeout=90) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={
                "model": model, "max_tokens": 4000,
                "system": _ORCHESTRATOR_PROMPT,
                "messages": [{"role": "user", "content": text}],
            },
        )
        r.raise_for_status()
        raw = r.json()["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("orchestrator returned non-JSON: %s", raw[:300])
            return {"kind": "ask",
                    "answer": "I couldn't parse that — try again with more specifics."}
        # Defensive normalisation
        plan.setdefault("kind", "ask")
        if plan["kind"] == "plan":
            plan.setdefault("plan_summary", text[:120])
            plan.setdefault("tasks", [])
            for i, t in enumerate(plan["tasks"], 1):
                t.setdefault("step", i)
                t.setdefault("priority", 5)
                t.setdefault("context_paths", [])
                t.setdefault("depends_on_steps", [])
                t.setdefault("intent", "build")
        return plan

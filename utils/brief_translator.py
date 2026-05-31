"""Natural-language → structured builder brief translator.

Maps a WhatsApp message like "research solar competitors in UK and write
me a summary" or "add a Companies House lookup to the parcel popup"
into one of three intents:

  intent="build"     → enqueue a builder.queue row with title/brief/paths
  intent="research"  → enqueue a research task (also a build row but with
                       a research-mode hint; the builder will use
                       WebSearch + post a summary back)
  intent="ask"       → just answer via Claude, don't enqueue anything

Output schema (strict JSON):
{
  "intent": "build" | "research" | "ask",
  "title": "<short imperative>",
  "brief": "<full brief for the builder>",
  "context_paths": ["repo/path1", "repo/path2"],
  "priority": 1-9,
  "answer": "<only when intent=ask; the direct answer to send back>"
}
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the natural-language router for Princeps' builder agent.

The user is the platform owner, prompting the agent over WhatsApp to either:

  build     — add or change code in the Princeps repo
              (anyatrofimova-a11y/Princeps-energy). Output a structured
              brief the builder agent will hand to Claude to generate a diff.
  research  — investigate something on the web (competitors, new APIs,
              UK regulatory changes) and write a summary report. The
              builder will use WebSearch + post the summary back.
  ask       — a direct question about the codebase, project state, or
              recent agent activity. Answer it inline; don't enqueue.

Return JSON only. Schema:

{
  "intent": "build" | "research" | "ask",
  "title": "<short imperative, ≤80 chars>",
  "brief": "<full brief, complete sentences>",
  "context_paths": ["<repo path>", ...],   // for build/research; [] for ask
  "priority": 1-9,                          // 1=urgent
  "answer": "<inline answer; only when intent=ask>"
}

Heuristics:
- Mentions of "research", "look at", "investigate", "compare", "competitor"
  → research.
- Mentions of "add", "fix", "wire", "build", "deploy", "rename"
  → build.
- Questions ("what is", "why does", "show me") → ask.
- For build/research, include the most-likely-relevant context_paths from:
  app/routers/, app/actions/, agents/, utils/, feasi-frontend/src/components/.
- Default priority 5; raise to 3 if user uses "urgent" / "asap" / "now".

If the user message is ambiguous, prefer intent=ask with answer asking
for clarification.

User message follows.
"""


async def translate_brief(text: str) -> dict[str, Any]:
    api_key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"intent": "ask",
                "answer": "Builder is offline — no ANTHROPIC_API_KEY configured.",
                "title": "", "brief": "", "context_paths": [], "priority": 5}
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={
                "model": model, "max_tokens": 1500,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": text}],
            },
        )
        r.raise_for_status()
        out = r.json()["content"][0]["text"].strip()
        if out.startswith("```"):
            out = out.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            parsed = json.loads(out)
        except json.JSONDecodeError as exc:
            log.warning("brief translator returned non-JSON: %s", out[:300])
            return {"intent": "ask",
                    "answer": "I couldn't parse that — try again with more specifics.",
                    "title": "", "brief": "", "context_paths": [], "priority": 5}
        # Defensive defaults
        parsed.setdefault("intent", "ask")
        parsed.setdefault("title", text[:80])
        parsed.setdefault("brief", text)
        parsed.setdefault("context_paths", [])
        parsed.setdefault("priority", 5)
        return parsed

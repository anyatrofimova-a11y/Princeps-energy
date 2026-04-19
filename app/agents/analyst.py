"""
AnalystAgent — on-demand deep research triggered from chat.

When the interactive chat hits a question that needs >30s of work (multi-site
comparisons, scenario sweeps, literature surveys), it enqueues a job here.
AnalystAgent runs for minutes-to-hours with high iteration budget, spawns
parallel sub-agents via the Claude Agent SDK, and writes the result back
to the chat session.

Payload:
    {
        "session_id": "uuid",            # chat session to write back to
        "question": "...",               # user's question
        "context": {...},                # portfolio context from chat
        "max_sub_agents": 4,             # how many parallel researchers
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import MODEL_OPUS, MODEL_SONNET, AgentContext, AgentResult, BaseAgent

log = logging.getLogger("princeps.agents.analyst")


_PLANNER_SYSTEM = """You are a research planner for a UK energy feasibility platform. Given the user's question + portfolio context, decompose the research into 2-6 independent subtasks that can run in parallel.

Output JSON:
  - plan: one-sentence summary of approach
  - subtasks: [{id, title, question, expected_output}]
Respond with ONLY the JSON."""


_SYNTH_SYSTEM = """You synthesise parallel research sub-agent outputs into a single, actionable answer for a UK energy developer. Engineering tone, concise, cite data where sources were given. No emojis, no marketing."""


class AnalystAgent(BaseAgent):
    name = "analyst"
    default_model = MODEL_SONNET         # synthesis needs Sonnet or better
    model_ceiling = MODEL_OPUS           # Opus allowed for final synthesis only
    monthly_budget_gbp   = 40.0
    daily_budget_gbp     = 6.0           # on-demand; don't let a user burn it all in one day
    max_cost_per_run_gbp = 2.00
    max_tokens_per_call  = 3000
    max_tokens_out_per_run = 50_000

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        question = payload.get("question", "")
        context = payload.get("context", {})
        max_subs = int(payload.get("max_sub_agents", 4))
        session_id = payload.get("session_id")

        if not question:
            return AgentResult(ok=False, summary="No question provided.")

        # 1. Plan
        plan_text, plan_usage = await self.think(
            ctx,
            system=_PLANNER_SYSTEM,
            user=json.dumps({"question": question, "context": context}, default=str)[:6000],
            model=MODEL_OPUS,
            max_tokens=1200,
        )
        try:
            plan = json.loads(plan_text)
        except Exception:
            return AgentResult(ok=False, summary="Planner returned invalid JSON.")

        subtasks = plan.get("subtasks", [])[:max_subs]

        # 2. Run subtasks in parallel (Sonnet, low cost, broad coverage)
        sub_prompts = [
            {
                "system": "You are a specialist researcher for a UK energy site feasibility platform. Answer the question thoroughly in 200-500 words; cite data where relevant.",
                "user": f"Subtask: {s.get('title')}\nQuestion: {s.get('question')}\nExpected output: {s.get('expected_output')}",
            }
            for s in subtasks
        ]
        sub_results = await self.think_parallel(
            ctx, sub_prompts, model=MODEL_SONNET, concurrency=4, max_tokens=1500
        )

        tokens_in = plan_usage.get("input_tokens", 0) + sum(
            u.get("input_tokens", 0) for _, u in sub_results
        )
        tokens_out = plan_usage.get("output_tokens", 0) + sum(
            u.get("output_tokens", 0) for _, u in sub_results
        )

        # 3. Synthesise (Opus — best quality for final answer)
        synth_input = {
            "question": question,
            "plan": plan.get("plan"),
            "subtask_results": [
                {"title": s.get("title"), "finding": text}
                for s, (text, _) in zip(subtasks, sub_results, strict=True)
            ],
        }
        final_text, synth_usage = await self.think(
            ctx,
            system=_SYNTH_SYSTEM,
            user=json.dumps(synth_input, default=str)[:20000],
            model=MODEL_OPUS,
            max_tokens=3000,
        )
        tokens_in += synth_usage.get("input_tokens", 0)
        tokens_out += synth_usage.get("output_tokens", 0)

        # 4. Write back to chat session
        if session_id:
            await self._append_to_chat(ctx, session_id, final_text)

        return AgentResult(
            ok=True,
            summary=f"Analyst ran {len(subtasks)} subtasks for session {session_id}.",
            data={"plan": plan, "answer": final_text[:2000], "session_id": session_id},
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    async def _append_to_chat(
        self, ctx: AgentContext, session_id: str, text: str
    ) -> None:
        await ctx.db.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, created_at)
            VALUES ($1, 'assistant', $2, now())
            """,
            session_id,
            text,
        )

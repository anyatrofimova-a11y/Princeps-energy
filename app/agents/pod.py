"""Pod — vertical specialist Council agent.

A Pod runs a Claude reasoning loop bounded to a specific tool whitelist and a
domain system prompt. It produces a structured ``AgentOutput`` (verdict /
confidence / risks / opportunities / next_steps) rather than free text, so the
Adjudicator can compare the three pods deterministically.

Tool substrate (Week 1's Action Registry has not merged yet — STUB) — we fall
back to ``chat.TOOLS`` and ``chat.execute_tool`` as the dispatch layer. The
pod imports these lazily so it doesn't pay the cost when no tool whitelist
matches a Claude tool_use block.

Audit log: every tool call lands in ``ontology_action_log`` with
``object_type='council_pod'`` and ``object_id=<session_rid>:<pod_name>``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import anthropic

from app.agent import AgentOutput

log = logging.getLogger("princeps.council.pod")


# Output schema — same JSON shape as app.agent so the adjudicator can reuse
# AgentOutput / Pydantic validation across the pods.
_POD_OUTPUT_SCHEMA = """\
You MUST end your turn by emitting ONE valid JSON object — no prose, no
markdown — with EXACTLY these fields:
{
  "verdict": "GO" | "CAUTION" | "NO-GO",
  "confidence": 0.0 to 1.0,
  "summary": "2-3 sentence engineering assessment",
  "risks": ["risk1", ...],
  "opportunities": ["opp1", ...],
  "recommended_capacity_kw": number or null,
  "estimated_roi_years": number or null,
  "next_steps": ["concrete next step", ...],
  "actions": [],
  "intent": "<your pod name>"
}

Cite specific RIDs (rid.princeps.<type>.<id>) and figures (MW, km, kV) drawn
from your tool calls. Do NOT invent numbers. The "actions" array MUST be
empty — actions are produced server-side."""


@dataclass
class PodContext:
    """Shared per-session state passed between pods + adjudicator."""
    session_rid: str
    project_rid: Optional[str]
    pool: Any                       # asyncpg pool
    runners: dict[str, Any] = field(default_factory=dict)
    actor: str = "council"


@dataclass
class PodTrace:
    """Per-pod execution trace surfaced via SSE for transparency."""
    pod_name: str
    tool_calls: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    elapsed_s: Optional[float] = None
    model: Optional[str] = None
    error: Optional[str] = None


def _extract_json(text: str) -> dict:
    """Extract first balanced JSON object from text. Mirrors agent.py."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in pod response")
    return json.loads(text[start:end])


async def _audit_log(
    pool, *, session_rid: str, pod_name: str, action: str,
    args: dict, result: Any, ok: bool, duration_ms: int,
    error: Optional[str] = None,
) -> None:
    """Insert one row into ontology_action_log for traceability.

    Mirrors app.ontology.dispatch._log_action shape but is direct asyncpg
    because Week 1's safe_log helper has not merged.
    """
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ontology_action_log
                  (object_type, object_id, action, actor, ok,
                   args_json, result_json, error, duration_ms,
                   started_utc, completed_utc)
                VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9,$10,$11)
                """,
                "council_pod",
                f"{session_rid}:{pod_name}",
                action,
                "council",
                ok,
                json.dumps(args, default=str)[:50_000],
                json.dumps(result, default=str)[:50_000],
                error,
                duration_ms,
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
            )
    except Exception:
        log.exception("council audit_log write failed pod=%s session=%s",
                      pod_name, session_rid)


class Pod:
    """Base vertical specialist.

    Subclasses set ``name``, ``system_prompt``, ``tool_whitelist``, and may
    override ``ontology_binding(verdict)`` to attach an RID prefix to the
    output.
    """

    name: str = "pod"
    system_prompt: str = ""
    tool_whitelist: list[str] = []
    model: str = "claude-sonnet-4-5-20250929"  # commercial-safe default
    max_tool_loops: int = 4
    max_tokens: int = 1500
    confidence_floor: float = 0.0  # set >0 to raise on low-confidence verdicts

    def __init__(self, *, model: Optional[str] = None) -> None:
        if model:
            self.model = model

    # ------------------------------------------------------------------
    # Tool substrate (chat.TOOLS fallback — see module docstring)
    # ------------------------------------------------------------------
    def _bound_tools(self) -> list[dict]:
        """Return the chat.TOOLS subset matching ``self.tool_whitelist``.

        Tools that don't exist in chat.TOOLS are dropped silently and
        recorded in ``self._stubbed`` for the run summary.
        """
        # Lazy import to avoid circulars + sys.path tweaks at module load.
        import chat as chat_module  # noqa: WPS433
        by_name = {t["name"]: t for t in chat_module.TOOLS}
        bound, missing = [], []
        for tname in self.tool_whitelist:
            if tname in by_name:
                bound.append(by_name[tname])
            else:
                missing.append(tname)
        self._stubbed: list[str] = missing  # exposed for the trace
        if missing:
            log.info("pod=%s missing whitelisted tools (stubbed): %s",
                     self.name, missing)
        return bound

    async def _execute_tool(
        self,
        ctx: PodContext,
        tool_name: str,
        tool_args: dict,
    ) -> Any:
        """Dispatch a single Claude tool_use through chat.execute_tool.

        We synthesise the minimal ChatSession that execute_tool needs so we
        don't actually create a chat row — pods are stateless w.r.t. chat.
        """
        import chat as chat_module  # noqa: WPS433
        from app.helpers import (
            run_sam_subprocess, run_geeflow_subprocess,
            run_geoai_subprocess, fetch_parcel_context,
        )

        # Synthetic per-call session with no message history.
        synthetic = chat_module.ChatSession(
            id=f"council_{ctx.session_rid}_{self.name}",
            parcel_id=None,
            project_id=ctx.project_rid,
        )
        try:
            return await chat_module.execute_tool(
                tool_name, tool_args, synthetic,
                pool=ctx.pool,
                run_sam_subprocess=run_sam_subprocess,
                fetch_parcel_context=fetch_parcel_context,
                run_geeflow_subprocess=run_geeflow_subprocess,
                run_geoai_subprocess=run_geoai_subprocess,
            )
        except Exception as exc:
            log.exception("pod tool dispatch failed pod=%s tool=%s",
                          self.name, tool_name)
            return {"error": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------------------------
    # Core run loop — non-streaming Anthropic call, manual tool loop
    # ------------------------------------------------------------------
    async def run(
        self,
        query: str,
        ctx: PodContext,
        client: anthropic.AsyncAnthropic,
    ) -> tuple[AgentOutput, PodTrace]:
        """Drive Claude through the bounded tool list until a final JSON
        verdict lands. Returns the validated AgentOutput plus a trace.
        """
        trace = PodTrace(pod_name=self.name, model=self.model)
        tools = self._bound_tools()

        # Prepend the schema rule to the user query so Claude knows the JSON
        # contract — the schema is too long for the system prompt budget.
        user_msg = (
            f"Pod query: {query}\n\n"
            f"Project RID: {ctx.project_rid or '(unbound)'}\n\n"
            f"{_POD_OUTPUT_SCHEMA}"
        )
        messages: list[dict] = [{"role": "user", "content": user_msg}]
        verdict: Optional[AgentOutput] = None

        for turn in range(self.max_tool_loops):
            t0 = time.time()
            try:
                resp = await client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=0.0,
                    system=self.system_prompt,
                    tools=tools or anthropic.NOT_GIVEN,
                    messages=messages,
                )
            except anthropic.APIError as exc:
                trace.error = f"claude_api: {exc}"
                log.exception("pod claude call failed pod=%s", self.name)
                break

            # Collect assistant blocks
            assistant_blocks = []
            tool_uses = []
            text_acc = ""
            for block in resp.content:
                if block.type == "text":
                    text_acc += block.text
                    assistant_blocks.append(
                        {"type": "text", "text": block.text}
                    )
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            messages.append({"role": "assistant", "content": assistant_blocks})

            if not tool_uses or resp.stop_reason != "tool_use":
                # Final turn — extract JSON verdict from text
                try:
                    raw = _extract_json(text_acc)
                    raw.setdefault("intent", self.name)
                    verdict = AgentOutput(**raw)
                except Exception as exc:
                    trace.error = f"json_extract: {exc}"
                    log.warning("pod=%s JSON extract failed: %s",
                                self.name, exc)
                break

            # Execute tools (sequential — pods are bounded; parallelism is
            # at the council level across pods).
            tool_results = []
            for tu in tool_uses:
                t_start = time.time()
                tool_result = await self._execute_tool(ctx, tu.name, tu.input)
                t_dur_ms = int((time.time() - t_start) * 1000)
                trace.tool_calls.append({
                    "name": tu.name,
                    "args": tu.input,
                    "duration_ms": t_dur_ms,
                    "ok": not (isinstance(tool_result, dict)
                               and "error" in tool_result),
                })
                await _audit_log(
                    ctx.pool,
                    session_rid=ctx.session_rid,
                    pod_name=self.name,
                    action=f"tool_call:{tu.name}",
                    args=tu.input,
                    result=tool_result,
                    ok=trace.tool_calls[-1]["ok"],
                    duration_ms=t_dur_ms,
                )
                # Compact result so we don't blow the context window
                import chat as chat_module  # noqa: WPS433
                content = chat_module._compact_tool_result(tool_result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content,
                })
            messages.append({"role": "user", "content": tool_results})

        trace.finished_at = time.time()
        trace.elapsed_s = round(trace.finished_at - trace.started_at, 2)

        if verdict is None:
            # Build a degraded fallback verdict so the council can still
            # adjudicate even if one pod stumbled.
            verdict = AgentOutput(
                verdict="CAUTION",
                confidence=0.2,
                summary=(f"{self.name} pod failed to emit a structured "
                         f"verdict ({trace.error or 'no_response'})."),
                risks=[trace.error or "pod_no_response"],
                opportunities=[],
                next_steps=["Re-run with manual context"],
                actions=[],
                intent=self.name,
            )

        if verdict.confidence < self.confidence_floor:
            log.info("pod=%s low confidence %.2f below floor %.2f",
                     self.name, verdict.confidence, self.confidence_floor)

        # Audit-log the final verdict itself so we can reconstruct sessions.
        await _audit_log(
            ctx.pool,
            session_rid=ctx.session_rid,
            pod_name=self.name,
            action="pod_verdict",
            args={"query": query[:500]},
            result=verdict.model_dump(),
            ok=trace.error is None,
            duration_ms=int((trace.elapsed_s or 0) * 1000),
            error=trace.error,
        )
        return verdict, trace

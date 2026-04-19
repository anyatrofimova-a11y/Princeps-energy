"""
ARQ worker entry point for Princeps agent bots.

One worker image runs any agent, selected by AGENT_NAME env var. Railway
deploys the same image N times with different AGENT_NAME values, giving
independent scaling per agent.

Run locally:

    AGENT_NAME=prospector arq app.agents.worker.WorkerSettings

On Railway: `railway.json` per service sets the start command + env.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import asyncpg
import httpx
from anthropic import AsyncAnthropic

from app.agents.base import (
    AgentContext, AgentDisabled, AgentResult, BaseAgent, BudgetExceeded,
)
from app.agents import (
    analyst,
    builder,
    grid_monitor,
    ingestion,
    market_intel,
    planning_monitor,
    procurement,
    prospector,
    report,
    rnd,
)

log = logging.getLogger("princeps.worker")


# ── Agent registry ───────────────────────────────────────────────────────────
# When a new agent is added, import it above and register here.
_AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "prospector":       prospector.ProspectorAgent,
    "grid_monitor":     grid_monitor.GridMonitorAgent,
    "procurement":      procurement.ProcurementAgent,
    "ingestion":        ingestion.IngestionAgent,
    "report":           report.ReportAgent,
    "analyst":          analyst.AnalystAgent,
    "rnd":              rnd.CompetitorRnDAgent,
    "planning_monitor": planning_monitor.PlanningMonitorAgent,
    "market_intel":     market_intel.MarketIntelAgent,
    "builder":          builder.BuilderAgent,
}


def _resolve_agent() -> BaseAgent:
    name = os.getenv("AGENT_NAME", "prospector")
    cls = _AGENT_REGISTRY.get(name)
    if cls is None:
        raise RuntimeError(
            f"Unknown AGENT_NAME={name!r}. Registered: {list(_AGENT_REGISTRY)}"
        )
    return cls()


# ── Lifecycle ────────────────────────────────────────────────────────────────


async def startup(ctx: dict) -> None:
    log.info("worker.startup agent=%s", os.getenv("AGENT_NAME"))
    db_url = os.environ["DATABASE_URL"]
    ctx["db"] = await asyncpg.create_pool(db_url, min_size=1, max_size=4)
    ctx["http"] = httpx.AsyncClient()
    ctx["claude"] = AsyncAnthropic(api_key=os.environ["CLAUDE_API_KEY"])
    ctx["agent"] = _resolve_agent()


async def shutdown(ctx: dict) -> None:
    await ctx["db"].close()
    await ctx["http"].aclose()
    log.info("worker.shutdown")


# ── Job dispatcher ───────────────────────────────────────────────────────────


async def dispatch(ctx: dict, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Generic ARQ task. All agents are invoked through this single entry point.
    The bound agent is determined by AGENT_NAME at worker startup.
    """
    agent: BaseAgent = ctx["agent"]
    acontext = AgentContext(
        db=ctx["db"],
        claude=ctx["claude"],
        http=ctx["http"],
        run_id=str(uuid.uuid4()),
        agent_name=agent.name,
    )
    try:
        await agent.preflight(acontext)
    except (AgentDisabled, BudgetExceeded) as gate_exc:
        log.warning("%s: preflight gate — %s", agent.name, gate_exc)
        result = AgentResult(
            ok=False,
            summary=str(gate_exc)[:500],
            data={"gated": True, "reason": type(gate_exc).__name__},
        )
        await agent.on_success(acontext, result)  # records but doesn't log as failure
        return {"ok": False, "gated": True, "summary": result.summary}

    try:
        result = await agent.run(acontext, payload)
        await agent.on_success(acontext, result)
        return {
            "ok": result.ok,
            "summary": result.summary,
            "data": result.data,
            "cost_gbp": result.cost_gbp,
            "run_id": acontext.run_id,
        }
    except BaseException as exc:
        await agent.on_failure(acontext, exc)
        raise


# ── ARQ WorkerSettings ───────────────────────────────────────────────────────

from arq.connections import RedisSettings  # noqa: E402

_REDIS_URL = os.environ.get("REDIS_URL")


_AGENT_NAME = os.getenv("AGENT_NAME", "prospector")


class WorkerSettings:
    """ARQ picks these up from the module path on the command line.

    Each worker service consumes only its own per-agent queue, routed by
    the AGENT_NAME env var. The scheduler enqueues jobs with
    ``_queue_name=f"arq:{agent}"``.
    """

    functions = [dispatch]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = int(os.getenv("WORKER_CONCURRENCY", "4"))
    job_timeout = int(os.getenv("WORKER_JOB_TIMEOUT_S", "1800"))  # 30 min default
    keep_result = 3600  # 1 hour
    queue_name = f"arq:{_AGENT_NAME}"
    redis_settings = (
        RedisSettings.from_dsn(_REDIS_URL) if _REDIS_URL else RedisSettings()
    )

"""Agent orchestration: on-demand triggers + slash-command handlers.

Used by the WhatsApp router so messages like "/trigger docket_watch"
or "re-enrich open dockets" can fire an agent's tick() directly,
without waiting for its cron interval.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

# name -> (module_path, class_name)
AGENT_REGISTRY: dict[str, tuple[str, str]] = {
    "ontology_coherence":      ("agents.graph",      "OntologyCoherence"),
    "schema_drift":            ("agents.graph",      "SchemaDrift"),
    "ontology_backfill":       ("agents.graph",      "OntologyBackfill"),
    "connector_health":        ("agents.connector",  "ConnectorHealth"),
    "docket_watch":            ("agents.regwatch",   "DocketWatch"),
    "planning_constraint_watch": ("agents.regwatch", "PlanningConstraintWatch"),
    "ar7_window_monitor":      ("agents.regwatch",   "AR7WindowMonitor"),
    "headroom_patrol":         ("agents.grid",       "HeadroomPatrol"),
    "reinforcement_cost_refresh": ("agents.grid",    "ReinforcementCostRefresh"),
    "sanctions_rescreen":      ("agents.screen",     "SanctionsReScreen"),
    "obligation_deadline":     ("agents.contracts",  "ObligationDeadlineReminder"),
    "doc_change_watcher":      ("agents.contracts",  "DocChangeWatcher"),
    "da_price_reactor":        ("agents.market",     "DAPriceReactor"),
    "repd_cross_val":          ("agents.market",     "REPDCrossValidator"),
    "twin_replay":             ("agents.replay",     "TwinReplayWaiter"),
    "council_convener":        ("agents.council",    "CouncilConvener"),
}


async def trigger_agent(
    pool: asyncpg.Pool,
    agent_name: str,
    *,
    requested_by: str = "api",
    task_id: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Run one agent's tick() now. Logs to builder.agent_triggers."""
    if agent_name not in AGENT_REGISTRY:
        return {"error": f"unknown agent '{agent_name}'",
                "available": sorted(AGENT_REGISTRY)}
    mod_path, cls_name = AGENT_REGISTRY[agent_name]
    async with pool.acquire() as conn:
        trig_id = await conn.fetchval(
            """INSERT INTO builder.agent_triggers
                 (agent_name, requested_by, task_id, status, started_at)
               VALUES ($1, $2, $3::uuid, 'running', now())
               RETURNING trigger_id""",
            agent_name, requested_by, task_id,
        )
    try:
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, cls_name)
        agent = cls()
        result = await asyncio.wait_for(agent.tick(), timeout=timeout_seconds)
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE builder.agent_triggers
                      SET status='done', finished_at=now(),
                          result=$2::jsonb
                    WHERE trigger_id=$1""",
                trig_id, __import__("json").dumps(result, default=str),
            )
        return {"trigger_id": str(trig_id), "agent": agent_name, "result": result}
    except Exception as exc:
        log.exception("agent %s tick failed", agent_name)
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE builder.agent_triggers
                      SET status='failed', finished_at=now(),
                          result=$2::jsonb
                    WHERE trigger_id=$1""",
                trig_id, __import__("json").dumps({"error": str(exc)}),
            )
        return {"trigger_id": str(trig_id), "agent": agent_name,
                "error": f"{type(exc).__name__}: {exc}"}


# ── Slash-command renderers ─────────────────────────────────────────────────

async def cmd_help() -> str:
    return (
        "Commands:\n"
        "/status — counts of open / in-progress / done tasks\n"
        "/list [N] — last N queued tasks (default 10)\n"
        "/trigger <agent> — fire an agent's tick() now\n"
        "/show <id> — show detail for one task\n"
        "/cancel <id> — mark a pending task rejected\n"
        "/research <topic> — shortcut for a research-mode task\n"
        "/ship <id> — set auto_merge=true on a pending task\n"
        "Or just type a normal sentence — I'll plan multi-step work."
    )


async def cmd_status(pool) -> str:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, COUNT(*) AS n FROM builder.queue GROUP BY status"
        )
        recent_prs = await conn.fetchval(
            "SELECT COUNT(*) FROM builder.queue WHERE pr_url IS NOT NULL "
            "AND finished_at > now() - interval '7 days'"
        )
    parts = ", ".join(f"{r['status']}: {r['n']}" for r in rows) or "queue empty"
    return f"📊 {parts} · 7d PRs opened: {recent_prs}"


async def cmd_list(pool, n: int = 10) -> str:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT task_id::text AS id, title, status, priority, mode
                 FROM builder.queue ORDER BY created_at DESC LIMIT $1""",
            n,
        )
    if not rows:
        return "(queue empty)"
    return "\n".join(
        f"`{r['id'][:8]}` {r['mode']:<8} p{r['priority']} {r['status']:<10} {r['title']}"
        for r in rows
    )


async def cmd_show(pool, short_id: str) -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM builder.queue
                WHERE task_id::text LIKE $1 || '%' LIMIT 1""",
            short_id,
        )
    if not row:
        return f"no task matching `{short_id}`"
    out = [
        f"📋 {row['title']}",
        f"  id: {str(row['task_id'])[:8]} · status: {row['status']} · mode: {row['mode']} · priority: {row['priority']}",
        f"  requested_by: {row['requested_by']}",
    ]
    if row["pr_url"]: out.append(f"  PR: {row['pr_url']}")
    if row["error"]:  out.append(f"  error: {row['error']}")
    if row["claude_plan"]:
        out.append(f"  plan: {row['claude_plan'][:240]}")
    return "\n".join(out)


async def cmd_cancel(pool, short_id: str) -> str:
    async with pool.acquire() as conn:
        n = await conn.execute(
            """UPDATE builder.queue SET status='rejected', finished_at=now()
                WHERE task_id::text LIKE $1 || '%' AND status='pending'""",
            short_id,
        )
    return f"✅ cancelled (rows={n.split()[-1]})" if "UPDATE" in n else f"no pending task matching `{short_id}`"


async def cmd_ship(pool, short_id: str) -> str:
    async with pool.acquire() as conn:
        n = await conn.execute(
            """UPDATE builder.queue SET auto_merge=true
                WHERE task_id::text LIKE $1 || '%' AND status IN ('pending','in_progress')""",
            short_id,
        )
    return f"🚢 auto_merge=true (rows={n.split()[-1]})"


async def cmd_research(pool, topic: str, requested_by: str) -> str:
    if not topic.strip():
        return "Usage: /research <topic>"
    async with pool.acquire() as conn:
        tid = await conn.fetchval(
            """INSERT INTO builder.queue
                 (title, brief, mode, branch_policy, priority, requested_by)
               VALUES ($1, $2, 'research', 'pr', 4, $3)
               RETURNING task_id::text""",
            topic[:120],
            f"RESEARCH MODE — investigate '{topic}' on the web, produce a markdown "
            f"summary under docs/research/<slug>.md with cited sources.",
            requested_by,
        )
    return f"🔬 research task queued `{tid[:8]}`"

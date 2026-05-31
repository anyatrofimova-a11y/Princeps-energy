"""princeps-agent-grid — A6 headroom patrol, A11 reinforcement cost refresh."""
from __future__ import annotations
from agents.lib.base import Agent, get_pool, run_agent


class HeadroomPatrol(Agent):
    NAME = "headroom_patrol"
    CADENCE_SECONDS = 6 * 3600

    async def tick(self):
        from agents.lib.build_queue import enqueue_build_task
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, name, dno, voltage_kv
                      FROM grid_substations
                     WHERE voltage_kv >= 33
                     LIMIT 500
                """)
                # If we have substations but no recent headroom_delta rows, ask
                # the builder to wire the missing API endpoint.
                has_endpoint = await conn.fetchval(
                    "SELECT to_regclass('public.headroom_delta') IS NOT NULL"
                )
            enqueued = 0
            if rows and not has_endpoint:
                task = await enqueue_build_task(
                    pool,
                    title="Add headroom_delta table + /api/grid/headroom-deltas writer",
                    brief=(
                        "The headroom_patrol agent has substations to track but the "
                        "headroom_delta table doesn't exist. Add the migration "
                        "(migrations/2026_06_01_headroom_delta.sql) creating "
                        "headroom_delta(substation_id, observed_at, available_mw, "
                        "delta_mw_24h, alert_threshold_pct) and a POST endpoint on "
                        "app/routers/grid.py that the agent can use to record observations."
                    ),
                    context_paths=["app/routers/grid.py", "migrations/2026_05_03_data_pipelines.sql"],
                    requested_by="agent:headroom_patrol",
                    priority=5,
                )
                if task: enqueued += 1
            return {"substations_scanned": len(rows), "build_tasks_enqueued": enqueued}
        finally:
            await pool.close()


class ReinforcementCostRefresh(Agent):
    NAME = "reinforcement_cost_refresh"
    CADENCE_SECONDS = 30 * 24 * 3600

    async def tick(self):
        return {"assessments_refreshed": 0}


if __name__ == "__main__":
    run_agent([HeadroomPatrol(), ReinforcementCostRefresh()])

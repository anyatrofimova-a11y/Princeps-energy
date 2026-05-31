"""princeps-agent-connector — A3 connector health sentinel.

If a connector goes stale, enqueues a build task asking the builder
agent to inspect and propose a fix.
"""
from __future__ import annotations
from agents.lib.base import Agent, get_pool, run_agent
from agents.lib.build_queue import enqueue_build_task


class ConnectorHealth(Agent):
    NAME = "connector_health"
    CADENCE_SECONDS = 3600

    async def tick(self):
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                stale = await conn.fetch("""
                    SELECT connector_id,
                           MAX(ran_at) AS last_run,
                           COUNT(*) FILTER (WHERE ok = false AND ran_at > now() - interval '24 hours') AS recent_errors
                      FROM connector_schedule_log
                     WHERE ran_at > now() - interval '7 days'
                  GROUP BY connector_id
                    HAVING MAX(ran_at) < now() - interval '24 hours'
                """)
                async with conn.transaction():
                    for r in stale:
                        await conn.execute("""
                            INSERT INTO connector_schedule_log
                              (connector_id, ran_at, ok, summary)
                            VALUES ($1, now(), false, $2)
                            ON CONFLICT DO NOTHING
                        """, r["connector_id"], f"stale: no fresh run since {r['last_run']}")

            enqueued = 0
            for r in stale:
                cid = r["connector_id"]
                task = await enqueue_build_task(
                    pool,
                    title=f"Diagnose stale connector: {cid}",
                    brief=(
                        f"The connector_health agent observed connector '{cid}' "
                        f"has not produced a successful run since {r['last_run']}. "
                        "Inspect the ingester module and propose either a schema-drift fix, "
                        "a credentials check, or a fallback adapter."
                    ),
                    context_paths=[
                        "app/connectors/registry.py",
                        "utils/grid_data_ingester.py",
                    ],
                    requested_by="agent:connector_health",
                    priority=4,
                )
                if task: enqueued += 1
            return {"stale_connectors": len(stale), "build_tasks_enqueued": enqueued}
        finally:
            await pool.close()


if __name__ == "__main__":
    run_agent([ConnectorHealth()])

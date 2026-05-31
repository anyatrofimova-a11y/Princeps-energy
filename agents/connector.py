"""princeps-agent-connector — A3 connector health sentinel."""
from __future__ import annotations
from agents.lib.base import Agent, get_pool, run_agent


class ConnectorHealth(Agent):
    NAME = "connector_health"
    CADENCE_SECONDS = 3600

    async def tick(self):
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                # Connectors that haven't logged a fresh row in 24h.
                stale = await conn.fetch("""
                    SELECT connector_id,
                           MAX(ran_at) AS last_run,
                           COUNT(*) FILTER (WHERE ok = false AND ran_at > now() - interval '24 hours') AS recent_errors
                      FROM connector_schedule_log
                     WHERE ran_at > now() - interval '7 days'
                  GROUP BY connector_id
                    HAVING MAX(ran_at) < now() - interval '24 hours'
                """)
                total = len(stale)
                # Re-rank: anything that has a recent_errors > 0 also surfaces.
                async with conn.transaction():
                    for r in stale:
                        await conn.execute("""
                            INSERT INTO connector_schedule_log
                              (connector_id, ran_at, ok, summary)
                            VALUES ($1, now(), false, $2)
                            ON CONFLICT DO NOTHING
                        """, r["connector_id"], f"stale: no fresh run since {r['last_run']}")
            return {"stale_connectors": total}
        finally:
            await pool.close()


if __name__ == "__main__":
    run_agent([ConnectorHealth()])

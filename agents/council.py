"""princeps-agent-council — A16 multi-agent convener for high-stakes Actions."""
from __future__ import annotations
from agents.lib.base import Agent, get_pool, run_agent


class CouncilConvener(Agent):
    NAME = "council_convener"
    CADENCE_SECONDS = 30

    async def tick(self):
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                pending = await conn.fetch("""
                    SELECT rid, action_id, params, created_at
                      FROM action_audit_log
                     WHERE ok = false
                       AND summary ILIKE '%awaiting council%'
                     ORDER BY created_at ASC
                     LIMIT 10
                """) if False else []
            return {"pending_actions": len(pending)}
        finally:
            await pool.close()


if __name__ == "__main__":
    run_agent([CouncilConvener()])

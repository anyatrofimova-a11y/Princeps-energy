"""princeps-agent-grid — A6 headroom patrol, A11 reinforcement cost refresh."""
from __future__ import annotations
from agents.lib.base import Agent, get_pool, run_agent


class HeadroomPatrol(Agent):
    NAME = "headroom_patrol"
    CADENCE_SECONDS = 6 * 3600

    async def tick(self):
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, name, dno, voltage_kv
                      FROM grid_substations
                     WHERE voltage_kv >= 33
                     LIMIT 500
                """)
            return {"substations_scanned": len(rows)}
        finally:
            await pool.close()


class ReinforcementCostRefresh(Agent):
    NAME = "reinforcement_cost_refresh"
    CADENCE_SECONDS = 30 * 24 * 3600

    async def tick(self):
        return {"assessments_refreshed": 0}


if __name__ == "__main__":
    run_agent([HeadroomPatrol(), ReinforcementCostRefresh()])

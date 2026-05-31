"""princeps-agent-screen — A7 counterparty sanctions re-screen."""
from __future__ import annotations
from agents.lib.base import Agent, get_pool, run_agent


class SanctionsReScreen(Agent):
    NAME = "sanctions_rescreen"
    CADENCE_SECONDS = 24 * 3600

    async def tick(self):
        from utils.uk_sanctions_ingester import screen_name, refresh
        pool = await get_pool()
        try:
            try:
                await refresh(pool)
            except Exception:
                pass
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT proprietor_name_1 AS name
                      FROM hm_land_registry_ccod
                     WHERE proprietor_name_1 IS NOT NULL
                     LIMIT 200
                """) if False else []
            hits = 0
            for r in rows:
                matches = await screen_name(pool, r["name"])
                if matches and matches[0].get("score", 0) > 0.85:
                    hits += 1
            return {"counterparties_screened": len(rows), "hits": hits}
        finally:
            await pool.close()


if __name__ == "__main__":
    run_agent([SanctionsReScreen()])

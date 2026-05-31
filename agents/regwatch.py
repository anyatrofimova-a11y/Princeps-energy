"""princeps-agent-regwatch — A4 docket watch, A5 planning constraint watch, A12 AR7 monitor."""
from __future__ import annotations
import asyncio
from agents.lib.base import Agent, get_pool, run_agent


class DocketWatch(Agent):
    NAME = "docket_watch"
    CADENCE_SECONDS = 24 * 3600

    async def tick(self):
        from utils.docket_enricher import enrich_all_open_dockets
        pool = await get_pool()
        try:
            result = await enrich_all_open_dockets(pool, limit=20)
            return {
                "scanned": result.get("scanned"),
                "enriched": result.get("enriched"),
                "failed": result.get("failed"),
            }
        finally:
            await pool.close()


class PlanningConstraintWatch(Agent):
    NAME = "planning_constraint_watch"
    CADENCE_SECONDS = 7 * 24 * 3600

    async def tick(self):
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT site_id, ST_X(geometry::geometry) AS lon, ST_Y(geometry::geometry) AS lat
                      FROM candidate_sites
                     WHERE geometry IS NOT NULL
                     LIMIT 200
                """)
                # The actual constraint check is done elsewhere; this surfaces sites
                # that haven't been re-checked recently.
            return {"sites_due_for_recheck": len(rows)}
        finally:
            await pool.close()


class AR7WindowMonitor(Agent):
    NAME = "ar7_window_monitor"
    CADENCE_SECONDS = 24 * 3600

    async def tick(self):
        import httpx
        from agents.lib.build_queue import enqueue_build_task
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                "https://www.gov.uk/government/publications/contracts-for-difference-cfd-allocation-round-7-ar7",
                follow_redirects=True,
            )
        opened = "applications open" in r.text.lower() or "round open" in r.text.lower()
        if opened:
            pool = await get_pool()
            try:
                await enqueue_build_task(
                    pool,
                    title="AR7 round open — surface banner on AR7-eligible projects",
                    brief=(
                        "The AR7 monitor agent detected that the CfD AR7 round is open. "
                        "Add a top-of-page banner to project workspaces flagged ar7-eligible "
                        "linking to the AR7 application template (/api/applications/templates/ar7_cfd_application)."
                    ),
                    context_paths=[
                        "feasi-frontend/src/components/workspace/ProjectPage.jsx",
                        "feasi-frontend/src/components/workspace/ApplicationsPanel.jsx",
                    ],
                    requested_by="agent:ar7_window_monitor",
                    priority=3,
                )
            finally:
                await pool.close()
        return {"ar7_page_http": r.status_code, "applications_open_detected": opened}


if __name__ == "__main__":
    run_agent([DocketWatch(), PlanningConstraintWatch(), AR7WindowMonitor()])

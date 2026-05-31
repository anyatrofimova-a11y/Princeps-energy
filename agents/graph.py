"""princeps-agent-graph — A1 ontology coherence, A2 schema drift, A15 backfill."""
from __future__ import annotations
import os
from agents.lib.base import Agent, get_pool, run_agent


class OntologyCoherence(Agent):
    NAME = "ontology_coherence"
    CADENCE_SECONDS = 6 * 3600

    async def tick(self):
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                # Duplicate-Site detector: same OS grid ref + name similarity > 0.85.
                dupes = await conn.fetch("""
                    SELECT a.site_id AS a, b.site_id AS b, a.name AS aname, b.name AS bname
                      FROM candidate_sites a
                      JOIN candidate_sites b ON a.site_id < b.site_id
                       AND ST_DWithin(a.geometry::geography, b.geometry::geography, 50)
                       AND similarity(coalesce(a.name,''), coalesce(b.name,'')) > 0.85
                     LIMIT 200
                """)
            return {"duplicate_site_pairs_found": len(dupes)}
        finally:
            await pool.close()


class SchemaDrift(Agent):
    NAME = "schema_drift"
    CADENCE_SECONDS = 7 * 24 * 3600

    async def tick(self):
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                # Find tables in public that are never written to (no insert in 30d).
                stale = await conn.fetch("""
                    SELECT relname, n_live_tup
                      FROM pg_stat_user_tables
                     WHERE schemaname = 'public'
                       AND coalesce(last_autoanalyze, '1970-01-01') < now() - interval '30 days'
                       AND n_live_tup = 0
                     LIMIT 50
                """)
            return {"likely_drift_tables": len(stale)}
        finally:
            await pool.close()


class OntologyBackfill(Agent):
    NAME = "ontology_backfill"
    CADENCE_SECONDS = 24 * 3600

    async def tick(self):
        # No-op stub; activated when a new typed column lands without backfill.
        return {"backfill_jobs": 0}


if __name__ == "__main__":
    run_agent([OntologyCoherence(), SchemaDrift(), OntologyBackfill()])

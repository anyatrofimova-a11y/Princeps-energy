"""princeps-agent-contracts — A8 obligation deadlines, A9 doc change watcher."""
from __future__ import annotations
from agents.lib.base import Agent, get_pool, run_agent


class ObligationDeadlineReminder(Agent):
    NAME = "obligation_deadline"
    CADENCE_SECONDS = 24 * 3600

    async def tick(self):
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                # Obligations expiring in the next 30 days.
                upcoming = await conn.fetch("""
                    SELECT obligation_rid, party, action, deadline_iso
                      FROM contracts.obligations
                     WHERE status = 'open'
                       AND deadline_iso ~ '^\\d{4}-\\d{2}-\\d{2}'
                       AND deadline_iso::date BETWEEN current_date AND current_date + interval '30 days'
                """)
            return {"upcoming_obligations": len(upcoming)}
        finally:
            await pool.close()


class DocChangeWatcher(Agent):
    NAME = "doc_change_watcher"
    CADENCE_SECONDS = 15 * 60

    async def tick(self):
        from utils.clause_diff import diff_drafts
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                pairs = await conn.fetch("""
                    WITH ranked AS (
                      SELECT document_rid, draft_rid,
                             ROW_NUMBER() OVER (PARTITION BY document_rid
                                                ORDER BY uploaded_at DESC) AS rn,
                             uploaded_at
                        FROM contracts.document_drafts
                    )
                    SELECT a.document_rid, a.draft_rid AS new_draft, b.draft_rid AS prev_draft
                      FROM ranked a JOIN ranked b USING (document_rid)
                     WHERE a.rn = 1 AND b.rn = 2
                       AND a.uploaded_at > now() - interval '15 minutes'
                       AND NOT EXISTS (
                         SELECT 1 FROM contracts.change_alerts c
                          WHERE c.draft_rid_a = b.draft_rid
                            AND c.draft_rid_b = a.draft_rid
                       )
                """)
                emitted = 0
                for row in pairs:
                    try:
                        delta = await diff_drafts(pool, row["prev_draft"], row["new_draft"])
                        s = delta["summary"]
                        if s["modified"] + s["added"] + s["removed"] > 0:
                            await conn.execute("""
                                INSERT INTO contracts.change_alerts
                                  (document_rid, draft_rid_a, draft_rid_b, summary, delta)
                                VALUES ($1, $2, $3, $4, $5::jsonb)
                            """, row["document_rid"], row["prev_draft"], row["new_draft"],
                                f"{s['modified']} modified, {s['added']} added, {s['removed']} removed",
                                __import__("json").dumps(s))
                            emitted += 1
                    except Exception:
                        pass
            return {"drafts_checked": len(pairs), "alerts_emitted": emitted}
        finally:
            await pool.close()


if __name__ == "__main__":
    run_agent([ObligationDeadlineReminder(), DocChangeWatcher()])

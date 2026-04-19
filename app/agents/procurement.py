"""
ProcurementAgent — daily sweep of UK public-sector energy tenders.

Sources: Find-a-Tender (gov.uk), Contracts Finder (gov.uk), OJEU.
For each new tender: classify (tech, capacity, budget), score bid viability
(0-100), match to user sites, persist.

Payload (optional):
    {"max_tenders": 50, "since_days": 7}
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import MODEL_HAIKU, MODEL_SONNET, AgentContext, AgentResult, BaseAgent

log = logging.getLogger("princeps.agents.procurement")


_CLASSIFY_SYSTEM = """You classify UK energy-sector procurement tenders. Given the tender title + abstract, output a JSON object:
  - tech: "solar" | "bess" | "wind" | "grid" | "dc" | "other"
  - capacity_mw: integer or null
  - budget_gbp: integer or null
  - scope: "design" | "build" | "operate" | "consulting" | "supply"
  - bid_viability: integer 0-100
  - reasoning: one sentence, <140 chars

Base bid_viability on: scope clarity, capacity size, timeline realism,
incumbent bias risk. Respond with ONLY the JSON object."""


class ProcurementAgent(BaseAgent):
    name = "procurement"
    default_model = MODEL_HAIKU          # tender classification — cheap model OK
    model_ceiling = MODEL_SONNET
    monthly_budget_gbp   = 15.0
    daily_budget_gbp     = 2.0
    max_cost_per_run_gbp = 0.50
    max_tokens_per_call  = 400

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        since_days = int(payload.get("since_days", 7))
        max_tenders = int(payload.get("max_tenders", 50))

        tenders = await self._fetch_new_tenders(ctx, since_days, max_tenders)
        if not tenders:
            return AgentResult(ok=True, summary="No new tenders.", data={"count": 0})

        prompts = [
            {
                "system": _CLASSIFY_SYSTEM,
                "user": json.dumps(
                    {"title": t["title"], "abstract": t.get("abstract", "")[:2000]},
                    separators=(",", ":"),
                ),
            }
            for t in tenders
        ]
        results = await self.think_parallel(ctx, prompts, concurrency=10, max_tokens=400)

        classified: list[dict[str, Any]] = []
        tokens_in = tokens_out = 0
        for tender, (text, usage) in zip(tenders, results, strict=True):
            tokens_in += usage.get("input_tokens", 0)
            tokens_out += usage.get("output_tokens", 0)
            try:
                classification = json.loads(text)
            except Exception:
                continue
            classified.append({**tender, **classification})

        await self._persist(ctx, classified)

        viable = [c for c in classified if c.get("bid_viability", 0) >= 70]
        if viable:
            await self.notify_slack(
                ctx,
                f"*ProcurementAgent* — {len(viable)} high-viability tenders this sweep.\n"
                + "\n".join(
                    f"• {c['title'][:80]} ({c['bid_viability']}/100, £{c.get('budget_gbp') or '?'})"
                    for c in viable[:5]
                ),
            )

        return AgentResult(
            ok=True,
            summary=f"Classified {len(classified)} tenders; {len(viable)} viable (>=70).",
            data={"count": len(classified), "viable": len(viable)},
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    async def _fetch_new_tenders(
        self, ctx: AgentContext, since_days: int, limit: int
    ) -> list[dict[str, Any]]:
        """Pull tenders from Find-a-Tender API. Placeholder; wire to real feed."""
        # TODO: integrate with gov.uk Find-a-Tender API
        # For now read from procurement_tenders_raw (populated by ingestion)
        rows = await ctx.db.fetch(
            """
            SELECT tender_id, title, abstract, buyer, closing_date, url
            FROM procurement_tenders_raw
            WHERE published_at > now() - make_interval(days => $1)
              AND classified_at IS NULL
            ORDER BY published_at DESC
            LIMIT $2
            """,
            since_days, limit,
        )
        return [dict(r) for r in rows]

    async def _persist(
        self, ctx: AgentContext, classified: list[dict[str, Any]]
    ) -> None:
        if not classified:
            return
        await ctx.db.executemany(
            """
            UPDATE procurement_tenders_raw
            SET tech = $2,
                capacity_mw = $3,
                budget_gbp = $4,
                scope = $5,
                bid_viability = $6,
                reasoning = $7,
                classified_at = now()
            WHERE tender_id = $1
            """,
            [
                (
                    c["tender_id"],
                    c.get("tech"),
                    c.get("capacity_mw"),
                    c.get("budget_gbp"),
                    c.get("scope"),
                    int(c.get("bid_viability", 0)),
                    (c.get("reasoning") or "")[:400],
                )
                for c in classified
            ],
        )

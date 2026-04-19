"""
GridMonitorAgent — watches NESO/DNO data for constraint changes.

Flow:
  1. Pull latest grid_substations + grid_ecr snapshots (updated by IngestionAgent).
  2. Compare against last snapshot stored in grid_snapshots table.
  3. For each user site in `user_sites` that was previously GO/CAUTION, re-run
     Tier 1 grid connection analysis; if verdict downgraded, write a
     grid_alerts row and Slack the user.
  4. Record summary.

Payload (optional):
    {"user_id": "uuid", "tech": "solar", "severity_threshold": "CAUTION"}
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import MODEL_HAIKU, AgentContext, AgentResult, BaseAgent

log = logging.getLogger("princeps.agents.grid_monitor")


_TRIAGE_SYSTEM = """You are a UK grid connection analyst triaging constraint-change alerts. Given before/after state of a grid substation (capacity, queue, voltage), output a JSON object:
  - severity: "info" | "watch" | "critical"
  - headline: one sentence, <120 chars
  - action: one sentence recommending what the site owner should do

Respond with ONLY the JSON object."""


class GridMonitorAgent(BaseAgent):
    name = "grid_monitor"
    default_model = MODEL_HAIKU
    model_ceiling = MODEL_HAIKU          # triage never needs Sonnet
    monthly_budget_gbp   = 10.0
    daily_budget_gbp     = 1.5
    max_cost_per_run_gbp = 0.20
    max_tokens_per_call  = 200

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        user_id = payload.get("user_id")
        changes = await self._detect_changes(ctx, user_id)
        if not changes:
            return AgentResult(ok=True, summary="No grid changes detected.", data={"count": 0})

        prompts = [
            {"system": _TRIAGE_SYSTEM, "user": json.dumps(c, separators=(",", ":"))}
            for c in changes
        ]
        results = await self.think_parallel(ctx, prompts, model=MODEL_HAIKU, concurrency=8)

        alerts: list[dict[str, Any]] = []
        tokens_in = tokens_out = 0
        for change, (text, usage) in zip(changes, results, strict=True):
            tokens_in += usage.get("input_tokens", 0)
            tokens_out += usage.get("output_tokens", 0)
            try:
                triage = json.loads(text)
            except Exception:
                continue
            alerts.append({**change, **triage})

        await self._write_alerts(ctx, alerts)

        critical = [a for a in alerts if a.get("severity") == "critical"]
        if critical:
            await self.notify_slack(
                ctx,
                f"*GridMonitorAgent* — {len(critical)} critical grid changes:\n"
                + "\n".join(f"• {a['headline']}" for a in critical[:5]),
            )

        return AgentResult(
            ok=True,
            summary=f"Processed {len(changes)} changes; {len(critical)} critical.",
            data={"count": len(alerts), "critical": len(critical)},
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    async def _detect_changes(
        self, ctx: AgentContext, user_id: str | None
    ) -> list[dict[str, Any]]:
        """
        Return list of substation-level changes since last run.

        Placeholder implementation — real version diffs grid_snapshots.
        """
        rows = await ctx.db.fetch(
            """
            SELECT
                s.substation_id,
                s.name,
                s.dno,
                s.capacity_mva,
                s.headroom_mw,
                s.updated_at
            FROM grid_substations s
            WHERE s.updated_at > now() - interval '25 hours'
            LIMIT 100
            """
        )
        return [dict(r) for r in rows]

    async def _write_alerts(
        self, ctx: AgentContext, alerts: list[dict[str, Any]]
    ) -> None:
        if not alerts:
            return
        await ctx.db.executemany(
            """
            INSERT INTO grid_alerts (substation_id, severity, headline, action, data, raised_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, now())
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    a["substation_id"],
                    a.get("severity", "info"),
                    (a.get("headline") or "")[:300],
                    (a.get("action") or "")[:500],
                    json.dumps({k: v for k, v in a.items() if k != "updated_at"}, default=str),
                )
                for a in alerts
            ],
        )

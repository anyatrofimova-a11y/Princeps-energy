"""
PlanningMonitorAgent — watches UK planning portals for applications that
intersect a user's saved site criteria (AOI + tech + radius), scores
relevance with Claude, and fires Slack/email alerts for high-threat items.

Table dependencies (created in sql/agents_coordination.sql):

  planning_watches   (user_id, aoi geometry, tech, radius_km, ...)
  planning_applications  (id, geom, status, application_date, description, ...)
  planning_alerts    (user_id, watch_id, application_id, relevance, threat_level, ...)

Payload shape:
    {
        "user_id": "uuid" | None,          # None = scan all watches
        "since_days": 7,                   # look-back window
        "max_alerts_per_watch": 10
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import (
    MODEL_HAIKU,
    MODEL_SONNET,
    AgentContext,
    AgentResult,
    BaseAgent,
)
from app.agents.coordination import (
    ActionStation,
    Coordinator,
    MissionConflict,
    SailingOrders,
)

log = logging.getLogger("princeps.agents.planning_monitor")


_SCORING_SYSTEM = """You assess UK planning applications for impact on a user's energy-development site.

Given a watched site (tech type, capacity target, location) and a nearby planning application, output JSON:
  - relevance: 0-100 (how relevant to the user's project)
  - threat_level: "none" | "low" | "med" | "high"
  - reasoning: 1 sentence, <160 chars
  - action: "watch" | "flag" | "escalate"

"threat_level" is high when: competing energy development within 5km, objections
from statutory consultees on similar tech, grid-constraint-triggering loads (e.g.
large DC), or land-use changes that would block your site's access.

Respond with ONLY the JSON object."""


class PlanningMonitorAgent(BaseAgent):
    """Scans the ``planning_applications`` table against user ``planning_watches``.

    This agent is read-only against planning data + write-only to
    ``planning_alerts`` + Slack. It never mutates the source applications
    table, so it declares only the alerts table in its sailing orders —
    ``ingestion`` can keep populating planning_applications concurrently.
    """

    name = "planning_monitor"
    default_model = MODEL_HAIKU
    model_ceiling = MODEL_SONNET
    monthly_budget_gbp     = 15.0
    daily_budget_gbp       = 2.0
    max_cost_per_run_gbp   = 0.50
    max_tokens_per_call    = 384
    max_tokens_out_per_run = 20_000

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        orders = SailingOrders.from_payload(self.name, payload)
        orders.action_station = ActionStation.GENERAL
        orders.touches_tables = ["planning_alerts"]
        orders.goal = orders.goal or "Scan planning applications against active watches"

        try:
            async with Coordinator(ctx.db, orders) as mission:
                result = await self._do_run(ctx, payload)
                mission.record_outcome({
                    "alerts_written": result.data.get("alerts_written", 0),
                    "high_threats":    result.data.get("high_threats", 0),
                })
                return result
        except MissionConflict as conflict:
            log.warning("planning_monitor.mission_conflict: %s", conflict)
            return AgentResult(
                ok=False,
                summary=f"Skipped — conflicting mission running: {conflict}",
                data={"gated": True, "reason": "MissionConflict"},
            )

    # ── Core flow ────────────────────────────────────────────────────────────

    async def _do_run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        user_id = payload.get("user_id")
        since_days = int(payload.get("since_days", 7))
        max_alerts = int(payload.get("max_alerts_per_watch", 10))

        watches = await self._load_watches(ctx, user_id)
        if not watches:
            return AgentResult(
                ok=True,
                summary="No active planning watches to scan.",
                data={"watches": 0},
            )

        total_matches = 0
        total_alerts = 0
        total_high = 0

        for watch in watches:
            applications = await self._load_applications(ctx, watch, since_days)
            if not applications:
                continue
            total_matches += len(applications)

            prompts = [
                {
                    "system": _SCORING_SYSTEM,
                    "user": json.dumps(
                        {
                            "watch": self._watch_brief(watch),
                            "application": self._app_brief(a),
                        },
                        separators=(",", ":"),
                    ),
                }
                for a in applications[:max_alerts]
            ]
            responses = await self.think_parallel(
                ctx, prompts, model=MODEL_HAIKU, concurrency=6, max_tokens=384
            )

            scored: list[dict[str, Any]] = []
            for app, (text, _usage) in zip(applications[: len(prompts)], responses, strict=True):
                try:
                    verdict = json.loads(text)
                except Exception:
                    log.warning("planning_monitor: unparseable verdict: %s", text[:160])
                    continue
                scored.append({
                    "application": app,
                    "watch": watch,
                    **verdict,
                })

            alerts = [s for s in scored if s.get("threat_level") in ("med", "high")]
            await self._write_alerts(ctx, alerts)
            total_alerts += len(alerts)
            highs = [a for a in alerts if a.get("threat_level") == "high"]
            total_high += len(highs)

            if highs:
                await self._notify(ctx, watch, highs)

        summary = (
            f"Scanned {len(watches)} watches → {total_matches} matches → "
            f"{total_alerts} alerts written ({total_high} HIGH)."
        )
        return AgentResult(
            ok=True,
            summary=summary,
            data={
                "watches": len(watches),
                "matches": total_matches,
                "alerts_written": total_alerts,
                "high_threats": total_high,
            },
        )

    # ── Data access ──────────────────────────────────────────────────────────

    async def _load_watches(
        self, ctx: AgentContext, user_id: str | None
    ) -> list[dict[str, Any]]:
        q = """
            SELECT id, user_id, name, tech, capacity_mw, radius_km,
                   ST_AsGeoJSON(ST_Transform(aoi, 4326)) AS aoi_geojson,
                   ST_SRID(aoi) AS srid,
                   constraints
              FROM planning_watches
             WHERE active = true
        """
        args: list = []
        if user_id:
            q += " AND user_id = $1"
            args.append(user_id)
        rows = await ctx.db.fetch(q, *args)
        return [dict(r) for r in rows]

    async def _load_applications(
        self,
        ctx: AgentContext,
        watch: dict[str, Any],
        since_days: int,
    ) -> list[dict[str, Any]]:
        """Find applications inside watch.aoi buffered by radius_km."""
        rows = await ctx.db.fetch(
            """
            SELECT pa.id, pa.reference, pa.description, pa.status,
                   pa.application_date, pa.decision_date, pa.authority,
                   pa.applicant, pa.development_type,
                   ST_AsGeoJSON(ST_Transform(pa.geom, 4326)) AS geom_4326,
                   ST_Distance(pa.geom, w.aoi) / 1000.0 AS distance_km
              FROM planning_applications pa
              JOIN planning_watches w ON w.id = $1
             WHERE pa.application_date >= now() - ($2::int || ' days')::interval
               AND ST_DWithin(pa.geom, w.aoi, w.radius_km * 1000)
             ORDER BY pa.application_date DESC
             LIMIT 40
            """,
            watch["id"], since_days,
        )
        return [dict(r) for r in rows]

    # ── Serialisation ────────────────────────────────────────────────────────

    @staticmethod
    def _watch_brief(w: dict) -> dict:
        return {
            "name": w.get("name"),
            "tech": w.get("tech"),
            "mw": w.get("capacity_mw"),
            "radius_km": w.get("radius_km"),
            "constraints": w.get("constraints") or [],
        }

    @staticmethod
    def _app_brief(a: dict) -> dict:
        return {
            "ref": a.get("reference"),
            "desc": (a.get("description") or "")[:500],
            "status": a.get("status"),
            "type": a.get("development_type"),
            "authority": a.get("authority"),
            "applicant": a.get("applicant"),
            "distance_km": round(float(a.get("distance_km") or 0), 2),
            "date": str(a.get("application_date") or ""),
        }

    # ── Persistence & notification ───────────────────────────────────────────

    async def _write_alerts(
        self, ctx: AgentContext, alerts: list[dict[str, Any]]
    ) -> None:
        if not alerts:
            return
        await ctx.db.executemany(
            """
            INSERT INTO planning_alerts (
                user_id, watch_id, application_id,
                relevance, threat_level, reasoning, action,
                data, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, now())
            ON CONFLICT (watch_id, application_id) DO UPDATE SET
                relevance    = EXCLUDED.relevance,
                threat_level = EXCLUDED.threat_level,
                reasoning    = EXCLUDED.reasoning,
                action       = EXCLUDED.action,
                data         = EXCLUDED.data,
                created_at   = now()
            """,
            [
                (
                    a["watch"].get("user_id"),
                    a["watch"]["id"],
                    a["application"]["id"],
                    int(a.get("relevance", 0)),
                    a.get("threat_level", "low"),
                    (a.get("reasoning") or "")[:500],
                    a.get("action", "watch"),
                    json.dumps(
                        {
                            "application": {
                                k: v for k, v in a["application"].items() if k != "geom_4326"
                            },
                            "verdict": {
                                k: a.get(k)
                                for k in ("relevance", "threat_level", "reasoning", "action")
                            },
                        },
                        default=str,
                    ),
                )
                for a in alerts
            ],
        )

    async def _notify(
        self,
        ctx: AgentContext,
        watch: dict,
        highs: list[dict],
    ) -> None:
        lines = [
            f"• {h['application'].get('reference')} "
            f"({h['application'].get('distance_km', '?')} km) — "
            f"{h.get('reasoning', '')}"
            for h in highs[:5]
        ]
        await self.notify_slack(
            ctx,
            f"*PlanningMonitor*: {len(highs)} HIGH-threat application(s) "
            f"near watch *{watch.get('name')}* ({watch.get('tech')})\n"
            + "\n".join(lines),
        )

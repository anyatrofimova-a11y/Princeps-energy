"""
IngestionAgent — scheduled data refreshes with anomaly triage.

Delegates to existing utils.*_ingester modules, records metrics to
ingestion_log, triages anomalies via Claude (Haiku — cheap).

Payload:
    {"source": "bmrs" | "neso" | "dno" | "osm" | "geeflow" | "all"}
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.agents.base import MODEL_HAIKU, AgentContext, AgentResult, BaseAgent

log = logging.getLogger("princeps.agents.ingestion")


_ANOMALY_SYSTEM = """You triage data-ingestion anomalies in a UK energy platform. Given a metric delta vs historical baseline, output JSON:
  - severity: "ignore" | "watch" | "alert"
  - explanation: one sentence, <140 chars
Typical anomalies: demand dropped >30% (holiday or sensor?), generation gap, row-count zero.
Respond with ONLY JSON."""


_SOURCES = {
    "bmrs":    "utils.demand_data_ingester",
    "neso":    "utils.grid_data_ingester",
    "dno":     "utils.dno_opendata_ingester",
    "osm":     "utils.grid_data_ingester",
    "geeflow": "utils.geeflow_runner",
}


class IngestionAgent(BaseAgent):
    name = "ingestion"
    default_model = MODEL_HAIKU
    model_ceiling = MODEL_HAIKU          # anomaly triage only
    monthly_budget_gbp   = 3.0           # mostly data plumbing — tiny LLM use
    daily_budget_gbp     = 0.50
    max_cost_per_run_gbp = 0.10
    max_tokens_per_call  = 200

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        source = payload.get("source", "all")
        sources_to_run = list(_SOURCES) if source == "all" else [source]

        results: dict[str, Any] = {}
        anomalies: list[dict[str, Any]] = []
        for src in sources_to_run:
            started = time.time()
            try:
                metrics = await self._run_source(ctx, src)
                results[src] = {"ok": True, **metrics, "duration_s": round(time.time() - started, 1)}
                if metric_anomaly := self._detect_anomaly(metrics):
                    anomalies.append({"source": src, **metric_anomaly})
            except Exception as e:
                log.exception("ingestion source=%s failed", src)
                results[src] = {"ok": False, "error": str(e)[:500]}
                await self._log_ingestion(ctx, src, None, 0, str(e))

        if anomalies:
            prompts = [
                {"system": _ANOMALY_SYSTEM, "user": json.dumps(a, separators=(",", ":"))}
                for a in anomalies
            ]
            triage_results = await self.think_parallel(ctx, prompts, concurrency=4, max_tokens=200)
            for anomaly, (text, _) in zip(anomalies, triage_results, strict=True):
                try:
                    anomaly["triage"] = json.loads(text)
                except Exception:
                    pass
            critical = [a for a in anomalies if a.get("triage", {}).get("severity") == "alert"]
            if critical:
                await self.notify_slack(
                    ctx,
                    f"*IngestionAgent* — {len(critical)} data anomalies.\n"
                    + "\n".join(
                        f"• {a['source']}: {a['triage'].get('explanation', '?')}"
                        for a in critical[:5]
                    ),
                )

        return AgentResult(
            ok=all(r.get("ok") for r in results.values()),
            summary=f"Ran {len(sources_to_run)} sources; {len(anomalies)} anomalies.",
            data={"sources": results, "anomalies": anomalies},
        )

    async def _run_source(self, ctx: AgentContext, source: str) -> dict[str, Any]:
        """Dispatch to the matching utils.*_ingester module.

        Each branch imports lazily + tolerates missing modules/functions so a
        partially-wired source never takes down the whole agent. A missing
        or broken ingester is logged and counted as a stub run rather than
        raised — the agent's outer try/except will catch raised errors, but
        an ``ImportError`` here means the file shipped without the expected
        async entry point, which is a deploy-time bug we want visible in
        ``ingestion_log`` rather than the failures table.
        """
        if source == "bmrs":
            try:
                from utils.demand_data_ingester import refresh_recent  # type: ignore
            except ImportError as e:
                await self._log_ingestion(
                    ctx, source, 0, 0, f"no refresh_recent in demand_data_ingester: {e}"
                )
                return {"rows_ingested": 0, "note": "refresh_recent missing"}
            rows = await refresh_recent(ctx.db)
            await self._log_ingestion(ctx, source, rows, 0)
            return {"rows_ingested": rows}
        # Other sources are not yet wired — emit a stub log row so we can
        # see cadence in ingestion_log without blowing up the run.
        await self._log_ingestion(ctx, source, 0, 0, "stub — no runner wired")
        return {"rows_ingested": 0, "note": "stub"}

    def _detect_anomaly(self, metrics: dict[str, Any]) -> dict[str, Any] | None:
        rows = metrics.get("rows_ingested", 0)
        if rows == 0:
            return {"metric": "rows_ingested", "observed": 0, "expected": ">0"}
        return None

    async def _log_ingestion(
        self,
        ctx: AgentContext,
        source: str,
        rows: int | None,
        updated: int,
        notes: str | None = None,
    ) -> None:
        await ctx.db.execute(
            """
            INSERT INTO ingestion_log (
                source, rows_ingested, rows_updated, started_at, ok, notes
            )
            VALUES ($1, $2, $3, now(), $4, $5)
            """,
            source,
            rows,
            updated,
            notes is None,
            (notes or "")[:500],
        )

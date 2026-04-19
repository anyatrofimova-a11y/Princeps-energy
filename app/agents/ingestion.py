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
    "bmrs":     "utils.demand_data_ingester",
    "neso":     "utils.grid_data_ingester",
    "dno":      "utils.dno_opendata_ingester",
    "osm":      "utils.grid_data_ingester",
    "geeflow":  "utils.geeflow_runner",
    "grid":     "utils.grid_substations_refresh",  # canonical grid_substations / grid_ecr / grid_snapshots
    "nged_ecr": "utils.nged_ecr",                   # monthly ECR CSV → nged_ecr → grid_ecr
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

        if source == "grid":
            # Refreshes the canonical grid_substations / grid_ecr /
            # grid_snapshots tables from NGED / OSM / DNO-primary feeds.
            try:
                from utils.grid_substations_refresh import refresh_all  # type: ignore
            except ImportError as e:
                await self._log_ingestion(
                    ctx, source, 0, 0, f"grid_substations_refresh import failed: {e}"
                )
                return {"rows_ingested": 0, "note": "refresher missing"}
            counts = await refresh_all(ctx.db)
            total = sum(counts.values())
            await self._log_ingestion(
                ctx, source, total, 0,
                f"substations={counts['substations']} ecr={counts['ecr']} snapshot={counts['snapshot']}",
            )
            return {"rows_ingested": total, **counts}

        if source == "nged_ecr":
            # Full monthly ECR snapshot from NGED's public CSV feed.
            # ingest_ecr truncates nged_ecr each run — it's a whole-month
            # replacement, not an append. Follow up with a grid-refresh so
            # the canonical grid_ecr picks up the new source rows.
            try:
                from utils.nged_ecr import ingest_ecr  # type: ignore
                from utils.grid_substations_refresh import refresh_ecr  # type: ignore
            except ImportError as e:
                await self._log_ingestion(ctx, source, 0, 0, f"ingester import failed: {e}")
                return {"rows_ingested": 0, "note": "ingester missing"}
            summary = await ingest_ecr(ctx.db)
            if not summary.get("ok"):
                await self._log_ingestion(
                    ctx, source, 0, 0, f"ingest_ecr failed: {summary.get('reason')}",
                )
                return {"rows_ingested": 0, **summary}
            inserted = int(summary.get("inserted", 0) or 0)
            canonical = await refresh_ecr(ctx.db)
            await self._log_ingestion(
                ctx, source, inserted, canonical,
                f"nged_ecr_inserted={inserted} grid_ecr_after={canonical}",
            )
            return {
                "rows_ingested": inserted,
                "grid_ecr_after": canonical,
                **{k: v for k, v in summary.items() if k != "ok"},
            }

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

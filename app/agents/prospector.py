"""
ProspectorAgent — continuously scans UK regions for viable energy sites.

Reference implementation. The other six bots follow this pattern.

Flow:
  1. Load scan targets (UK regions × tech types) from DB.
  2. For each target, pull candidate land parcels via utils.site_prospector.
  3. Score candidates with parallel Claude calls (think_parallel).
  4. Write top-N to prospect_candidates table.
  5. Notify user via Slack digest if any ★ (star) candidates found.

Payload shape:
    {
        "user_id": "uuid",
        "regions": ["south-east", "east-of-england"],  # optional
        "tech": "solar" | "bess" | "dc",
        "min_mw": 10,
        "max_results": 20
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

log = logging.getLogger("princeps.agents.prospector")


# System prompt reused across parallel scoring calls. Cached via ephemeral
# prompt caching (1-hour TTL) to cut per-site Claude cost by ~80%.
_SCORING_SYSTEM = """You are a UK energy site feasibility analyst evaluating candidate parcels for energy development (solar PV, BESS, data centres). You give terse, engineering-grade verdicts.

For each candidate parcel, output a JSON object with:
  - score: integer 0-100 (overall viability)
  - verdict: "GO" | "CAUTION" | "NO-GO"
  - reasoning: one sentence, <140 chars
  - flags: list of concerns (short strings)

Evaluate on: grid proximity + capacity, ALC grade (prefer grade 3b/4/5 for solar), planning constraints (AONB, SSSI, flood zone), access, land use conflict.

Respond with ONLY the JSON object, no prose."""


class ProspectorAgent(BaseAgent):
    name = "prospector"
    default_model = MODEL_HAIKU          # classification — Haiku is plenty
    model_ceiling = MODEL_SONNET
    monthly_budget_gbp   = 20.0
    daily_budget_gbp     = 2.0
    max_cost_per_run_gbp = 0.40
    max_tokens_per_call  = 256
    max_tokens_out_per_run = 15_000

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        user_id = payload.get("user_id")
        tech = payload.get("tech", "solar")
        regions = payload.get("regions") or await self._default_regions(ctx)
        min_mw = float(payload.get("min_mw", 10))
        max_results = int(payload.get("max_results", 20))

        log.info(
            "prospector.run user=%s tech=%s regions=%s min_mw=%s",
            user_id, tech, regions, min_mw,
        )

        # 1. Pull candidates from site_prospector utility. This is a
        #    placeholder; in production it wraps utils.site_prospector.
        candidates = await self._load_candidates(ctx, regions, tech, min_mw)
        if not candidates:
            return AgentResult(
                ok=True,
                summary=f"No candidates in {regions} for {tech}.",
                data={"count": 0},
            )

        # 2. Score with parallel Claude calls — the multiplier pattern.
        prompts = [
            {
                "system": _SCORING_SYSTEM,
                "user": json.dumps(self._candidate_brief(c), separators=(",", ":")),
            }
            for c in candidates
        ]
        results = await self.think_parallel(
            ctx, prompts, model=MODEL_HAIKU, concurrency=10, max_tokens=256
        )

        scored: list[dict[str, Any]] = []
        tokens_in = tokens_out = 0
        for candidate, (text, usage) in zip(candidates, results, strict=True):
            tokens_in += usage.get("input_tokens", 0)
            tokens_out += usage.get("output_tokens", 0)
            try:
                verdict = json.loads(text)
            except Exception:
                log.warning("prospector: unparseable Claude response: %s", text[:200])
                continue
            scored.append({**candidate, **verdict})

        scored.sort(key=lambda s: s.get("score", 0), reverse=True)
        top = scored[:max_results]

        # 3. Persist.
        await self._write_candidates(ctx, user_id, tech, top)

        # 4. Digest if any GO verdicts.
        stars = [s for s in top if s.get("verdict") == "GO"]
        summary = (
            f"Prospected {len(candidates)} parcels; {len(stars)} GO verdicts; "
            f"top score {top[0]['score'] if top else 0}."
        )
        if stars:
            await self.notify_slack(
                ctx,
                f"*ProspectorAgent*: {len(stars)} new GO candidates in "
                f"{', '.join(regions)} for {tech}.\n"
                + "\n".join(
                    f"• {s['name']} ({s['score']}/100) — {s['reasoning']}"
                    for s in stars[:5]
                ),
            )

        cost = _estimate_cost_gbp(tokens_in, tokens_out, MODEL_HAIKU)
        return AgentResult(
            ok=True,
            summary=summary,
            data={
                "count": len(top),
                "go_count": len(stars),
                "top": top[:5],
            },
            cost_gbp=cost,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _default_regions(self, ctx: AgentContext) -> list[str]:
        """All UK regions if user didn't scope."""
        return [
            "south-east",
            "east-of-england",
            "east-midlands",
            "yorkshire-humber",
            "south-west",
        ]

    async def _load_candidates(
        self,
        ctx: AgentContext,
        regions: list[str],
        tech: str,
        min_mw: float,
    ) -> list[dict[str, Any]]:
        """
        Pull candidate parcels from the spatial prospector pipeline.

        Placeholder query — real version wraps utils.site_prospector with
        grid-distance, ALC-grade, and planning-constraint joins.
        """
        rows = await ctx.db.fetch(
            """
            SELECT
                id,
                name,
                region,
                ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geom_4326,
                area_ha,
                estimated_mw,
                grid_distance_km,
                alc_grade,
                planning_flags
            FROM prospect_parcels
            WHERE region = ANY($1::text[])
              AND tech_suitable @> ARRAY[$2]::text[]
              AND estimated_mw >= $3
              AND status = 'active'
            ORDER BY (estimated_mw / NULLIF(grid_distance_km, 0)) DESC NULLS LAST
            LIMIT 100
            """,
            regions,
            tech,
            min_mw,
        )
        return [dict(r) for r in rows]

    def _candidate_brief(self, c: dict) -> dict:
        """Compact JSON for Claude — keep tokens tight."""
        return {
            "name": c["name"],
            "region": c["region"],
            "area_ha": c.get("area_ha"),
            "mw": c.get("estimated_mw"),
            "grid_km": c.get("grid_distance_km"),
            "alc": c.get("alc_grade"),
            "flags": c.get("planning_flags") or [],
        }

    async def _write_candidates(
        self,
        ctx: AgentContext,
        user_id: str | None,
        tech: str,
        rows: list[dict[str, Any]],
    ) -> None:
        if not rows:
            return
        await ctx.db.executemany(
            """
            INSERT INTO prospect_candidates (
                user_id, parcel_id, tech, score, verdict, reasoning, flags, data, found_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, now())
            ON CONFLICT (user_id, parcel_id, tech) DO UPDATE SET
                score = EXCLUDED.score,
                verdict = EXCLUDED.verdict,
                reasoning = EXCLUDED.reasoning,
                flags = EXCLUDED.flags,
                data = EXCLUDED.data,
                found_at = now()
            """,
            [
                (
                    user_id,
                    r["id"],
                    tech,
                    int(r.get("score", 0)),
                    r.get("verdict", "NO-GO"),
                    (r.get("reasoning") or "")[:500],
                    json.dumps(r.get("flags") or []),
                    json.dumps(
                        {k: v for k, v in r.items() if k != "geom_4326"},
                        default=str,
                    ),
                )
                for r in rows
            ],
        )


def _estimate_cost_gbp(tokens_in: int, tokens_out: int, model: str) -> float:
    """Rough GBP estimate per Anthropic public pricing. Approximations only."""
    # USD per 1M tokens, rough Apr 2026 pricing; FX ~1.27 USD/GBP.
    rates = {
        MODEL_HAIKU: (0.80, 4.00),
        MODEL_SONNET: (3.00, 15.00),
        "claude-opus-4-6": (15.00, 75.00),
    }
    rate_in, rate_out = rates.get(model, rates[MODEL_SONNET])
    usd = (tokens_in / 1e6) * rate_in + (tokens_out / 1e6) * rate_out
    return round(usd / 1.27, 4)

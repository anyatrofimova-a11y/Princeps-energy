"""
CompetitorRnDAgent — scouts market + drafts upgrade proposals for Princeps.

Two modes:

  scout  — crawl competitor product pages, careers pages, press, GitHub.
           Claude extracts {feature, hire, customer, pricing, press} signals
           and writes to competitor_signals.

  rnd    — consume recent signals + user feedback + feature backlog.
           Claude Opus drafts upgrade_proposals rows. Optionally opens a
           draft PR on a feature/rnd-* branch via GitHub API.

Payload:
    {"mode": "scout" | "rnd", "competitor": "envision-greenwich"}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

from app.agents.base import MODEL_HAIKU, MODEL_OPUS, MODEL_SONNET, AgentContext, AgentResult, BaseAgent

log = logging.getLogger("princeps.agents.rnd")


# Primary watchlist. Add via admin UI later.
_WATCHLIST: list[dict[str, Any]] = [
    {"name": "envision-greenwich", "urls": ["https://envisiongreenwich.co.uk"]},
    {"name": "arup-digital-energy", "urls": ["https://www.arup.com/expertise/services/digital/digital-energy"]},
    {"name": "wsp-energy", "urls": ["https://www.wsp.com/en-gb/sectors/power-energy"]},
    {"name": "tnei", "urls": ["https://www.tneigroup.com"]},
    {"name": "roadnight-taylor", "urls": ["https://roadnighttaylor.com"]},
    {"name": "landtech", "urls": ["https://land.tech"]},
    {"name": "dune-energy", "urls": ["https://www.dune.energy"]},
]


_SCOUT_SYSTEM = """You extract competitive intelligence from UK energy-software vendor web pages. Given page HTML/text, output a JSON array of distinct signals. Each signal:
  - type: "feature" | "hire" | "customer" | "pricing" | "press"
  - title: short, <80 chars
  - summary: 1 sentence, <200 chars
  - signal_date: ISO date if present on page, else null

Skip boilerplate. Return [] if no signals. Output ONLY the JSON array."""


_RND_SYSTEM = """You are the R&D lead for Princeps, a UK energy feasibility platform. Given recent competitor signals + our current feature backlog, propose ONE concrete upgrade that keeps us ahead. Output JSON:
  - title: feature name (<80 chars)
  - motivation: why now (<400 chars, cite competitor signals by title)
  - proposal: design sketch (<1000 chars)
  - risk_notes: 2-3 risks
  - effort_estimate: "S" | "M" | "L" | "XL"
Output ONLY the JSON object."""


class CompetitorRnDAgent(BaseAgent):
    name = "rnd"
    default_model = MODEL_HAIKU          # scout uses Haiku, R&D bumps to Opus explicitly
    model_ceiling = MODEL_OPUS
    monthly_budget_gbp   = 30.0
    daily_budget_gbp     = 5.0
    max_cost_per_run_gbp = 1.50
    max_tokens_per_call  = 2000
    max_tokens_out_per_run = 40_000

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        mode = payload.get("mode", "scout")
        if mode == "scout":
            return await self._run_scout(ctx, payload)
        if mode == "rnd":
            return await self._run_rnd(ctx, payload)
        return AgentResult(ok=False, summary=f"Unknown mode: {mode}")

    # ── Scout mode ───────────────────────────────────────────────────────────

    async def _run_scout(self, ctx: AgentContext, payload: dict) -> AgentResult:
        targets = _WATCHLIST
        if competitor := payload.get("competitor"):
            targets = [c for c in targets if c["name"] == competitor]

        pages: list[dict[str, str]] = []
        sem = asyncio.Semaphore(2)  # polite: 2 concurrent HTTP fetches

        async def fetch(competitor_name: str, url: str):
            async with sem:
                await asyncio.sleep(2)  # 1 req per 2 seconds per domain
                try:
                    r = await ctx.http.get(url, timeout=20, follow_redirects=True)
                    if r.status_code == 200:
                        pages.append(
                            {
                                "competitor": competitor_name,
                                "url": url,
                                "domain": urlparse(url).netloc,
                                "text": r.text[:30000],
                            }
                        )
                except Exception:
                    log.exception("scout fetch failed for %s", url)

        await asyncio.gather(*(fetch(c["name"], u) for c in targets for u in c["urls"]))

        if not pages:
            return AgentResult(ok=True, summary="No pages fetched.", data={"pages": 0})

        prompts = [
            {
                "system": _SCOUT_SYSTEM,
                "user": f"Competitor: {p['competitor']}\nURL: {p['url']}\n\nContent:\n{p['text']}",
            }
            for p in pages
        ]
        results = await self.think_parallel(ctx, prompts, concurrency=4, max_tokens=1500)

        all_signals: list[dict[str, Any]] = []
        tokens_in = tokens_out = 0
        for page, (text, usage) in zip(pages, results, strict=True):
            tokens_in += usage.get("input_tokens", 0)
            tokens_out += usage.get("output_tokens", 0)
            try:
                signals = json.loads(text)
            except Exception:
                continue
            for s in signals if isinstance(signals, list) else []:
                all_signals.append(
                    {
                        "competitor": page["competitor"],
                        "source_url": page["url"],
                        **s,
                    }
                )

        await self._persist_signals(ctx, all_signals)
        return AgentResult(
            ok=True,
            summary=f"Scouted {len(pages)} pages; extracted {len(all_signals)} signals.",
            data={"pages": len(pages), "signals": len(all_signals)},
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    async def _persist_signals(
        self, ctx: AgentContext, signals: list[dict[str, Any]]
    ) -> None:
        if not signals:
            return
        await ctx.db.executemany(
            """
            INSERT INTO competitor_signals (
                competitor, signal_type, title, summary, source_url, signal_date, raw
            )
            VALUES ($1, $2, $3, $4, $5, $6::date, $7::jsonb)
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    s["competitor"],
                    s.get("type", "press"),
                    (s.get("title") or "")[:500],
                    (s.get("summary") or "")[:2000],
                    s.get("source_url"),
                    s.get("signal_date"),
                    json.dumps(s),
                )
                for s in signals
            ],
        )

    # ── R&D mode ─────────────────────────────────────────────────────────────

    async def _run_rnd(self, ctx: AgentContext, payload: dict) -> AgentResult:
        since_days = int(payload.get("since_days", 14))
        signals = await ctx.db.fetch(
            """
            SELECT competitor, signal_type, title, summary, signal_date
            FROM competitor_signals
            WHERE ingested_at > now() - make_interval(days => $1)
            ORDER BY ingested_at DESC
            LIMIT 80
            """,
            since_days,
        )
        if not signals:
            return AgentResult(ok=True, summary="No recent signals to synthesise.", data={})

        backlog = await ctx.db.fetch(
            """
            SELECT title, proposal
            FROM upgrade_proposals
            WHERE status IN ('draft', 'proposed')
            ORDER BY proposed_at DESC
            LIMIT 20
            """
        )

        synth_input = {
            "signals": [dict(s) for s in signals],
            "existing_backlog": [dict(b) for b in backlog],
        }

        text, usage = await self.think(
            ctx,
            system=_RND_SYSTEM,
            user=json.dumps(synth_input, default=str)[:18000],
            model=MODEL_OPUS,
            max_tokens=2000,
        )
        try:
            proposal = json.loads(text)
        except Exception:
            return AgentResult(ok=False, summary="R&D output not valid JSON.", data={"raw": text[:500]})

        await ctx.db.execute(
            """
            INSERT INTO upgrade_proposals (
                title, motivation, proposal, risk_notes, effort_estimate, status
            )
            VALUES ($1, $2, $3, $4, $5, 'proposed')
            """,
            (proposal.get("title") or "Untitled proposal")[:300],
            (proposal.get("motivation") or "")[:3000],
            (proposal.get("proposal") or "")[:8000],
            (proposal.get("risk_notes") or "")[:2000],
            (proposal.get("effort_estimate") or "M")[:4],
        )

        await self.notify_slack(
            ctx,
            f"*CompetitorRnDAgent* — new proposal: {proposal.get('title')}\n"
            f"{(proposal.get('motivation') or '')[:240]}",
        )

        return AgentResult(
            ok=True,
            summary=f"Drafted proposal: {proposal.get('title')}",
            data={"proposal": proposal},
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
        )

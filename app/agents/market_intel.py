"""
MarketIntelAgent — macro / regulatory / market-price intelligence for UK
energy infrastructure development.

Distinct from the existing agents:
  * ``rnd`` watches competitor products (vendor-level signals)
  * ``procurement`` classifies specific tenders
  * ``market_intel`` (this) watches *policy + market structure* signals:
        - Ofgem consultations, decisions, code modifications
        - NESO / ESO announcements (CM auctions, CfD rounds, TNUoS)
        - DNO Price Control (ED2/ED3) updates, connection reform
        - Wholesale / PPA / balancing price movements (summary)
        - UK government energy policy (DESNZ) press releases

Two modes:

  scout  — fetch configured sources, extract signals with Haiku parallel
           calls, persist to ``market_signals``.

  digest — consume recent signals, use the superpowers plan/critique/verify
           loop on Sonnet to produce a ranked weekly digest with explicit
           "so what for Princeps users" guidance. Slack + email the digest.

Payload:
    {"mode": "scout" | "digest", "since_days": 7}
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

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

log = logging.getLogger("princeps.agents.market_intel")


# Primary watchlist. Swap to DB-backed config once an admin UI exists.
#
# URLs refreshed 2026-04-20 after all 4 non-NESO sources started returning
# 404. Ofgem moved from /publications-and-updates to /publications with
# search-type= query param; DESNZ news moved into the unified gov.uk
# search surface; EMR Delivery Body redesigned (CM docs now discoverable
# from site root); Ofgem's RIIO-ED2 long-path URL went away — scout now
# uses a keyword search that surfaces latest ED2 decisions.
_SOURCES: list[dict[str, Any]] = [
    # Regulator — Ofgem
    {"name": "ofgem-consultations", "category": "regulator",
     "url": "https://www.ofgem.gov.uk/publications?search-type=Consultation"},
    {"name": "ofgem-decisions",     "category": "regulator",
     "url": "https://www.ofgem.gov.uk/publications?search-type=Decision"},
    # System operator — NESO
    {"name": "neso-news",            "category": "system-operator",
     "url": "https://www.neso.energy/news"},
    {"name": "neso-cm",              "category": "capacity-market",
     "url": "https://www.emrdeliverybody.com/"},
    # Govt — DESNZ
    {"name": "desnz-news",           "category": "policy",
     "url": "https://www.gov.uk/search/news-and-communications?organisations%5B%5D=department-for-energy-security-and-net-zero"},
    # DNOs — Price Control
    {"name": "ed2-price-control",    "category": "network",
     "url": "https://www.ofgem.gov.uk/publications?keywords=RIIO-ED2"},
    # 2026 additions — CfD + DUKES (per BOT-Y regulatory sweep 2026-04-19)
    {"name": "cfd-ar7",              "category": "policy",
     "url": "https://www.gov.uk/government/publications/contracts-for-difference-cfd-allocation-round-7-allocation-framework"},
    {"name": "dukes",                "category": "statistics",
     "url": "https://www.gov.uk/government/collections/digest-of-uk-energy-statistics-dukes"},
]


_SCOUT_SYSTEM = """You extract UK energy market + policy signals from a web page.

For each distinct signal on the page, emit a JSON object in an array:
  - type: "consultation" | "decision" | "announcement" | "auction_result" | "price_signal" | "other"
  - title: <100 chars
  - summary: 1 sentence, <240 chars
  - published_date: ISO date if visible on page, else null
  - impact_areas: array of ["grid","planning","procurement","finance","policy"] (0..N)
  - severity: "low" | "med" | "high"

Skip navigation chrome, footer, boilerplate. Return [] if nothing substantive.
Output ONLY the JSON array."""


_DIGEST_SYSTEM = """You are the market-intel editor for Princeps, a UK energy feasibility platform.

Given the past week's market signals, produce a JSON digest:

{
  "headline": "<120 chars — the single most important development",
  "themes":   ["<=80 chars each — 2 to 4 themes"],
  "picks": [
    {
      "title": "<100 chars",
      "severity": "low|med|high",
      "so_what": "<=240 chars — what Princeps users should DO about this",
      "impact_areas": ["grid","planning","procurement","finance","policy"],
      "signal_titles": ["source signal titles this pick is derived from"]
    }
  ],
  "risks":    ["<=160 chars each — 1 to 3 medium-term risks"],
  "notable_misses": ["<=120 chars each — things we'd have expected but didn't see"]
}

Be terse. 3-5 picks max. Every pick needs a concrete "so_what". Output ONLY JSON."""


class MarketIntelAgent(BaseAgent):
    name = "market_intel"
    default_model = MODEL_HAIKU
    model_ceiling = MODEL_SONNET           # Sonnet for digest synthesis
    monthly_budget_gbp     = 25.0
    daily_budget_gbp       = 3.0
    max_cost_per_run_gbp   = 1.00          # digest runs are larger
    max_tokens_per_call    = 1_500
    max_tokens_out_per_run = 40_000

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        mode = payload.get("mode", "scout")
        orders = SailingOrders.from_payload(self.name, payload)
        orders.goal = f"market_intel.{mode}"
        orders.action_station = ActionStation.GENERAL
        orders.touches_tables = ["market_signals"] if mode == "scout" else []

        try:
            async with Coordinator(ctx.db, orders) as mission:
                result = (
                    await self._scout(ctx, payload)
                    if mode == "scout"
                    else await self._digest(ctx, payload)
                )
                mission.record_outcome({
                    "mode": mode,
                    **{k: v for k, v in result.data.items() if isinstance(v, (int, str, bool))},
                })
                return result
        except MissionConflict as conflict:
            return AgentResult(
                ok=False,
                summary=f"Skipped — {conflict}",
                data={"gated": True, "reason": "MissionConflict"},
            )

    # ── Mode: scout ──────────────────────────────────────────────────────────

    async def _scout(self, ctx: AgentContext, payload: dict) -> AgentResult:
        pages: list[tuple[dict, str]] = []
        for src in _SOURCES:
            text = await self._fetch(ctx, src["url"])
            if text:
                pages.append((src, text))

        if not pages:
            return AgentResult(
                ok=True, summary="No pages fetched.", data={"signals": 0},
            )

        prompts = [
            {
                "system": _SCOUT_SYSTEM,
                "user": f"SOURCE: {src['name']} ({src['category']})\n\n{text[:9000]}",
            }
            for src, text in pages
        ]
        responses = await self.think_parallel(
            ctx, prompts, model=MODEL_HAIKU, concurrency=4, max_tokens=1_024,
        )

        new_signals: list[dict] = []
        for (src, _), (text, _usage) in zip(pages, responses, strict=True):
            try:
                arr = json.loads(text)
                if not isinstance(arr, list):
                    continue
            except Exception:
                log.warning("market_intel: unparseable scout response from %s", src["name"])
                continue
            for sig in arr:
                if not isinstance(sig, dict) or not sig.get("title"):
                    continue
                new_signals.append({
                    "source_name": src["name"],
                    "source_category": src["category"],
                    "source_url": src["url"],
                    **sig,
                })

        written = await self._write_signals(ctx, new_signals)
        return AgentResult(
            ok=True,
            summary=f"Scouted {len(pages)} sources → {len(new_signals)} signals → {written} persisted.",
            data={"sources": len(pages), "signals": len(new_signals), "written": written},
        )

    # ── Mode: digest ─────────────────────────────────────────────────────────

    async def _digest(self, ctx: AgentContext, payload: dict) -> AgentResult:
        since_days = int(payload.get("since_days", 7))
        signals = await self._load_recent_signals(ctx, since_days)
        if not signals:
            return AgentResult(
                ok=True, summary="No signals in window — skipping digest.",
                data={"signals": 0},
            )

        # Plan → synthesise → critique → verify (superpowers loop).
        #
        # This demonstrates the new plan/critique/verify scaffold on a real
        # task: we don't execute the plan step-by-step (the actual synthesis
        # is a single Claude call), but we use critique+verify as gates.

        brief = json.dumps(
            [self._signal_brief(s) for s in signals], separators=(",", ":")
        )[:12_000]

        digest_text, _ = await self.think(
            ctx,
            system=_DIGEST_SYSTEM,
            user=f"WINDOW_DAYS: {since_days}\n\nSIGNALS:\n{brief}",
            model=MODEL_SONNET,
            max_tokens=1_500,
        )

        # Self-critique on a rubric before persisting.
        review = await self.critique(
            ctx,
            artifact=digest_text,
            rubric=(
                "1. Valid JSON. "
                "2. At least 2 picks, each with a non-trivial 'so_what'. "
                "3. Headline < 120 chars. "
                "4. No pick contradicts the signals."
            ),
        )

        # Verify — binary gate. If this fails we still persist but flag it.
        ok, note = await self.verify(
            ctx,
            artifact=digest_text,
            criteria="Output is valid JSON with keys: headline, themes, picks (>=2), risks.",
        )

        try:
            digest = json.loads(digest_text)
        except Exception:
            return AgentResult(
                ok=False,
                summary=f"Digest unparseable despite verify={ok}; note={note}",
                data={"signals": len(signals), "verify_ok": ok, "review": review},
            )

        digest_id = await self._write_digest(ctx, digest, since_days, review, ok)
        if ok and digest.get("picks"):
            await self._notify_digest(ctx, digest)

        return AgentResult(
            ok=ok,
            summary=(
                f"Digest #{digest_id[:8]} from {len(signals)} signals — "
                f"severity={review.get('severity','?')} score={review.get('score','?')}"
            ),
            data={
                "digest_id": digest_id,
                "signals": len(signals),
                "review": review,
                "verify_ok": ok,
                "headline": digest.get("headline"),
            },
        )

    # ── Fetching ─────────────────────────────────────────────────────────────

    async def _fetch(self, ctx: AgentContext, url: str) -> str | None:
        try:
            r = await ctx.http.get(
                url,
                timeout=20,
                headers={"User-Agent": "princeps-market-intel/1.0"},
                follow_redirects=True,
            )
            r.raise_for_status()
            # Very naive HTML → text. For the scout use-case (Claude parsing)
            # the cheap strip is adequate; move to readability-lxml later if
            # precision becomes an issue.
            import re
            text = re.sub(r"<script.*?</script>", " ", r.text, flags=re.S | re.I)
            text = re.sub(r"<style.*?</style>",  " ", text, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception as e:
            log.warning("market_intel.fetch_failed url=%s err=%s", urlparse(url).netloc, e)
            return None

    # ── DB ───────────────────────────────────────────────────────────────────

    async def _write_signals(
        self, ctx: AgentContext, signals: list[dict]
    ) -> int:
        if not signals:
            return 0
        rows = [
            (
                s["source_name"],
                s["source_category"],
                s["source_url"],
                s.get("type", "other"),
                str(s.get("title", ""))[:240],
                str(s.get("summary", ""))[:1000],
                s.get("published_date"),
                json.dumps(s.get("impact_areas") or []),
                s.get("severity", "low"),
            )
            for s in signals
        ]
        await ctx.db.executemany(
            """
            INSERT INTO market_signals (
                source_name, source_category, source_url,
                type, title, summary, published_date,
                impact_areas, severity, created_at
            )
            VALUES ($1,$2,$3,$4,$5,$6,
                    NULLIF($7,'')::date, $8::jsonb, $9, now())
            ON CONFLICT (source_name, title) DO UPDATE SET
                summary = EXCLUDED.summary,
                severity = EXCLUDED.severity,
                impact_areas = EXCLUDED.impact_areas,
                published_date = COALESCE(market_signals.published_date, EXCLUDED.published_date)
            """,
            rows,
        )
        return len(rows)

    async def _load_recent_signals(
        self, ctx: AgentContext, since_days: int
    ) -> list[dict]:
        rows = await ctx.db.fetch(
            """
            SELECT id, source_name, source_category, type, title,
                   summary, published_date, impact_areas, severity
              FROM market_signals
             WHERE created_at >= now() - ($1::int || ' days')::interval
             ORDER BY severity DESC NULLS LAST, created_at DESC
             LIMIT 200
            """,
            since_days,
        )
        return [dict(r) for r in rows]

    async def _write_digest(
        self,
        ctx: AgentContext,
        digest: dict,
        since_days: int,
        review: dict,
        verified: bool,
    ) -> str:
        row = await ctx.db.fetchrow(
            """
            INSERT INTO market_digests (
                headline, body, window_days, review, verified, created_at
            )
            VALUES ($1, $2::jsonb, $3, $4::jsonb, $5, now())
            RETURNING id::text
            """,
            str(digest.get("headline", ""))[:240],
            json.dumps(digest, default=str),
            since_days,
            json.dumps(review, default=str),
            verified,
        )
        return row["id"]

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _signal_brief(s: dict) -> dict:
        return {
            "src": s.get("source_name"),
            "cat": s.get("source_category"),
            "type": s.get("type"),
            "title": s.get("title"),
            "sum": s.get("summary"),
            "date": str(s.get("published_date") or ""),
            "sev": s.get("severity"),
            "areas": s.get("impact_areas") or [],
        }

    async def _notify_digest(self, ctx: AgentContext, digest: dict) -> None:
        headline = str(digest.get("headline", ""))[:200]
        picks = digest.get("picks") or []
        lines = [
            f"• [{p.get('severity','?').upper()}] {p.get('title','?')} — {p.get('so_what','')}"
            for p in picks[:5]
        ]
        await self.notify_slack(
            ctx,
            f"*MarketIntel weekly digest*\n*{headline}*\n" + "\n".join(lines),
        )

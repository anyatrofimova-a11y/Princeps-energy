"""
ReportAgent — weekly per-user portfolio PDFs.

Flow:
  1. Fetch user's sites + recent activity (alerts, prospect_candidates, grid changes).
  2. Generate exec summary via Claude Sonnet (portfolio narrative).
  3. Render PDF via existing utils.report_financial / Playwright+Jinja2.
  4. Email via Resend.

Payload:
    {"user_id": "uuid"}
    If user_id omitted: report for all users with reporting enabled.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.base import MODEL_HAIKU, MODEL_SONNET, AgentContext, AgentResult, BaseAgent

log = logging.getLogger("princeps.agents.report")


_SUMMARY_SYSTEM = """You write crisp executive summaries for UK energy developers reviewing their weekly portfolio. Tone: engineering-grade, concise, no marketing fluff. Structure: 3 bullet points on material moves (wins, losses, risks) + 1 line of recommended action. UK English, £/MW/km units. No emojis.

Respond with plain text (no JSON, no markdown headers) — just the bullets and action line."""


class ReportAgent(BaseAgent):
    name = "report"
    default_model = MODEL_SONNET         # exec summary quality matters
    model_ceiling = MODEL_SONNET
    monthly_budget_gbp   = 8.0           # weekly only, bounded # of users
    daily_budget_gbp     = 4.0           # allow a whole cohort in one day
    max_cost_per_run_gbp = 0.30
    max_tokens_per_call  = 500

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        user_id = payload.get("user_id")
        users = [user_id] if user_id else await self._all_reportable_users(ctx)

        sent = failed = 0
        for uid in users:
            try:
                await self._generate_for_user(ctx, uid)
                sent += 1
            except Exception:
                log.exception("report failed for user=%s", uid)
                failed += 1

        return AgentResult(
            ok=failed == 0,
            summary=f"Reports sent: {sent}/{len(users)} ({failed} failed).",
            data={"sent": sent, "failed": failed, "users": len(users)},
        )

    async def _all_reportable_users(self, ctx: AgentContext) -> list[str]:
        rows = await ctx.db.fetch(
            """
            SELECT user_id FROM user_preferences
            WHERE weekly_report_enabled = true
            """
        )
        return [str(r["user_id"]) for r in rows]

    async def _generate_for_user(self, ctx: AgentContext, user_id: str) -> None:
        portfolio = await self._fetch_portfolio(ctx, user_id)
        email = portfolio.get("email")
        if not email:
            log.info("report: user %s has no email, skipping", user_id)
            return

        # 1. Exec summary via Claude
        summary_text, _usage = await self.think(
            ctx,
            system=_SUMMARY_SYSTEM,
            user=json.dumps(portfolio["snapshot"], default=str, indent=2)[:8000],
            max_tokens=500,
        )

        # 2. Render PDF — wraps existing report generator.
        pdf_bytes = await self._render_pdf(portfolio, summary_text)

        # 3. Email
        await self._email_pdf(
            ctx,
            to=email,
            subject=f"Princeps weekly: {portfolio['site_count']} sites",
            html=f"<pre>{summary_text}</pre>",
            pdf=pdf_bytes,
        )

    async def _fetch_portfolio(self, ctx: AgentContext, user_id: str) -> dict[str, Any]:
        row = await ctx.db.fetchrow(
            """
            SELECT u.email, u.name,
                   COUNT(p.parcel_id) AS site_count,
                   COUNT(p.parcel_id) FILTER (WHERE p.verdict = 'GO') AS go_count
            FROM users u
            LEFT JOIN prospect_candidates p ON p.user_id = u.user_id
            WHERE u.user_id = $1
            GROUP BY u.email, u.name
            """,
            user_id,
        )
        if not row:
            return {"email": None}
        return {
            "email": row["email"],
            "name": row["name"],
            "site_count": row["site_count"],
            "go_count": row["go_count"],
            "snapshot": dict(row),
        }

    async def _render_pdf(self, portfolio: dict, summary: str) -> bytes:
        """Render the weekly PDF. Placeholder — wraps Jinja2 + Playwright.

        Real implementation: from utils.report_financial import render_weekly
        """
        return b""  # stub

    async def _email_pdf(
        self, ctx: AgentContext, *, to: str, subject: str, html: str, pdf: bytes
    ) -> None:
        # Uses the BaseAgent.notify_email helper; attachment support can be
        # added later (Resend supports multipart).
        await self.notify_email(ctx, to=to, subject=subject, html=html)

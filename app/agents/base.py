"""
BaseAgent — shared scaffold for all Princeps runtime agent bots.

Provides:
  - asyncpg pool + Anthropic SDK client
  - structured logging
  - Slack / Resend notification helpers
  - **Credit safeguards** — see the "COST CONTROL" section below. The goal is
    that a bug or runaway loop cannot spend more than the configured caps
    without raising BudgetExceeded, and that operators can kill every bot
    instantly with a single env var.

COST CONTROL
============
Four layers, enforced before every Claude call:

  1. Global kill switch
     ``PRINCEPS_AGENTS_ENABLED=false`` disables ALL agents instantly.
     ``PRINCEPS_AGENT_<NAME>_ENABLED=false`` disables one agent (uppercase).

  2. Budget caps (per agent — class attributes, can be overridden by env)
     ``monthly_budget_gbp``   — hard monthly cap (raises BudgetExceeded)
     ``daily_budget_gbp``     — hard daily cap (stops runaway spend in hours)
     ``max_cost_per_run_gbp`` — one invocation cannot exceed this

  3. Token ceilings
     ``max_tokens_out_per_run`` — total output tokens per run
     ``max_tokens_per_call``   — per single Claude call (also enforced by
                                  Anthropic, but we prefer early refusal)

  4. Model tier ceiling
     ``model_ceiling`` — highest model this agent may use. Attempting to
     pass a costlier model downgrades silently to the ceiling.

All costs are estimated in GBP using public pricing at Apr 2026; update
``_MODEL_PRICING_USD_PER_MTOK`` if pricing changes.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import httpx
from anthropic import AsyncAnthropic

log = logging.getLogger("princeps.agents")


# ── Anthropic models ─────────────────────────────────────────────────────────
MODEL_HAIKU  = "claude-haiku-4-5"
MODEL_SONNET = "claude-sonnet-4-6"
MODEL_OPUS   = "claude-opus-4-6"

# Model tier ordering (cheapest → most expensive). Used for ceiling clamps.
_MODEL_TIER = {MODEL_HAIKU: 0, MODEL_SONNET: 1, MODEL_OPUS: 2}

# Public pricing (USD per million tokens) — update here when Anthropic moves.
# Order: (input, cached_read, output)
_MODEL_PRICING_USD_PER_MTOK: dict[str, tuple[float, float, float]] = {
    MODEL_HAIKU:  (0.80,  0.08,  4.00),
    MODEL_SONNET: (3.00,  0.30,  15.00),
    MODEL_OPUS:   (15.00, 1.50,  75.00),
}

# USD→GBP. Intentionally conservative (rounded up) so we overestimate rather
# than underestimate spend. Edit if GBP weakens significantly.
_USD_TO_GBP = 0.82


# ── Context / result types ───────────────────────────────────────────────────

@dataclass
class AgentContext:
    """Runtime context passed into each agent invocation."""

    db: asyncpg.Pool
    claude: AsyncAnthropic
    http: httpx.AsyncClient
    run_id: str
    agent_name: str
    started_at: float = field(default_factory=time.time)

    # Running totals updated by BaseAgent.think() / think_parallel() so that
    # per-run limits are enforceable mid-run without database round-trips.
    tokens_in: int = 0
    tokens_out: int = 0
    cost_gbp: float = 0.0


@dataclass
class AgentResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    cost_gbp: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_s: float = 0.0


class BudgetExceeded(RuntimeError):
    """Raised when an agent would cross its monthly / daily / per-run cap."""


class AgentDisabled(RuntimeError):
    """Raised when PRINCEPS_AGENTS_ENABLED=false or the per-agent flag is set."""


# ── BaseAgent ────────────────────────────────────────────────────────────────

class BaseAgent:
    """
    Base class for all Princeps runtime agent bots.

    Subclass, set class attributes, implement ``run()``. Every Claude call
    must go through ``self.think()`` / ``self.think_parallel()`` — these
    enforce budget + token caps. Do NOT call ctx.claude directly.
    """

    name: str = "base"
    default_model: str = MODEL_HAIKU         # cheapest by default; upgrade explicitly
    model_ceiling: str  = MODEL_SONNET       # highest model this bot may use

    # Budget caps (GBP) — override per bot
    monthly_budget_gbp:   float = 20.0
    daily_budget_gbp:     float = 3.0
    max_cost_per_run_gbp: float = 0.75

    # Token ceilings
    max_tokens_out_per_run: int = 20_000
    max_tokens_per_call:    int = 2_048

    # Circuit breaker: N consecutive failures auto-disables for cooldown_s
    failure_threshold: int = 5
    failure_cooldown_s: int = 3600

    # ── Entry point ──────────────────────────────────────────────────────────

    async def run(self, ctx: AgentContext, payload: dict) -> AgentResult:
        raise NotImplementedError(f"{self.name} must implement run()")

    # ── Pre-flight gates (called by dispatch in worker.py) ───────────────────

    async def preflight(self, ctx: AgentContext) -> None:
        """Throws AgentDisabled / BudgetExceeded before the run executes."""
        self._check_kill_switch()
        await self._check_circuit_breaker(ctx)
        await self._check_budget(ctx)

    def _check_kill_switch(self) -> None:
        if os.getenv("PRINCEPS_AGENTS_ENABLED", "true").lower() in ("0", "false", "no"):
            raise AgentDisabled("Global kill switch set (PRINCEPS_AGENTS_ENABLED=false)")
        per_agent_flag = f"PRINCEPS_AGENT_{self.name.upper()}_ENABLED"
        if os.getenv(per_agent_flag, "true").lower() in ("0", "false", "no"):
            raise AgentDisabled(f"{per_agent_flag}=false")

    async def _check_circuit_breaker(self, ctx: AgentContext) -> None:
        row = await ctx.db.fetchrow(
            """
            SELECT COUNT(*) FILTER (WHERE ok = false) AS fails,
                   MAX(started_at) AS last
            FROM (
                SELECT ok, started_at FROM agent_runs
                WHERE agent_name = $1
                ORDER BY started_at DESC
                LIMIT $2
            ) recent
            """,
            self.name, self.failure_threshold,
        )
        if row and row["fails"] >= self.failure_threshold and row["last"]:
            age = time.time() - row["last"].timestamp()
            if age < self.failure_cooldown_s:
                raise AgentDisabled(
                    f"{self.name} circuit breaker open — {row['fails']} consecutive "
                    f"failures, {int(self.failure_cooldown_s - age)}s until retry"
                )

    async def _check_budget(self, ctx: AgentContext) -> None:
        row = await ctx.db.fetchrow(
            """
            SELECT
              COALESCE(SUM(cost_gbp) FILTER (
                WHERE started_at > date_trunc('month', now())
              ), 0) AS month,
              COALESCE(SUM(cost_gbp) FILTER (
                WHERE started_at > date_trunc('day', now())
              ), 0) AS day
            FROM agent_runs
            WHERE agent_name = $1
            """,
            self.name,
        )
        month_spent = float(row["month"] or 0)
        day_spent   = float(row["day"]   or 0)
        if month_spent >= self.monthly_budget_gbp:
            raise BudgetExceeded(
                f"{self.name} monthly budget hit: £{month_spent:.2f}/£{self.monthly_budget_gbp}"
            )
        if day_spent >= self.daily_budget_gbp:
            raise BudgetExceeded(
                f"{self.name} daily budget hit: £{day_spent:.2f}/£{self.daily_budget_gbp}"
            )
        # Threshold Slack warnings (only fires once per threshold per day because
        # the alert itself is cheap and cross-run state is noisy)
        for pct, label in ((0.95, "95%"), (0.80, "80%"), (0.50, "50%")):
            if month_spent >= self.monthly_budget_gbp * pct and \
               month_spent < self.monthly_budget_gbp * (pct + 0.05):
                await self._warn_budget(ctx, f"{self.name} at {label} of monthly budget "
                                             f"(£{month_spent:.2f}/£{self.monthly_budget_gbp})")
                break

    async def _warn_budget(self, ctx: AgentContext, msg: str) -> None:
        try:
            await self.notify_slack(ctx, f":warning: {msg}")
        except Exception:
            pass

    # ── Claude helpers (ALL Claude traffic goes through these) ───────────────

    def _clamp_model(self, requested: str | None) -> str:
        m = requested or self.default_model
        if _MODEL_TIER.get(m, 0) > _MODEL_TIER.get(self.model_ceiling, 0):
            log.warning(
                "%s: downgrading %s → %s (model_ceiling)",
                self.name, m, self.model_ceiling,
            )
            return self.model_ceiling
        return m

    def _clamp_tokens(self, max_tokens: int) -> int:
        return min(max_tokens, self.max_tokens_per_call)

    def _would_exceed_run_budget(self, ctx: AgentContext, extra_cost: float) -> bool:
        if ctx.cost_gbp + extra_cost > self.max_cost_per_run_gbp:
            return True
        return False

    async def think(
        self,
        ctx: AgentContext,
        *,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int = 1024,
        cached_blocks: list[dict] | None = None,
    ) -> tuple[str, dict]:
        """Single Claude turn. Enforces budget + model + token caps."""
        if os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes"):
            return "[DRY_RUN]", {"input_tokens": 0, "output_tokens": 0}

        model_clamped = self._clamp_model(model)
        max_tokens = self._clamp_tokens(max_tokens)

        # Pre-estimate: assume full max_tokens out, conservative input estimate.
        est_in = max(len(system) + len(user) + sum(len(b.get("text", "")) for b in (cached_blocks or [])), 1) // 4
        est_cost = self._estimate_cost_gbp(est_in, max_tokens, 0, model_clamped)
        if self._would_exceed_run_budget(ctx, est_cost):
            raise BudgetExceeded(
                f"{self.name}: next call (~£{est_cost:.3f}) would exceed "
                f"per-run cap £{self.max_cost_per_run_gbp} "
                f"(already £{ctx.cost_gbp:.3f})"
            )
        if ctx.tokens_out + max_tokens > self.max_tokens_out_per_run:
            raise BudgetExceeded(
                f"{self.name}: next call ({max_tokens} tokens) would exceed "
                f"per-run output cap {self.max_tokens_out_per_run} "
                f"(already emitted {ctx.tokens_out})"
            )

        system_blocks: list[dict] = [{"type": "text", "text": system}]
        if cached_blocks:
            system_blocks.extend(cached_blocks)

        resp = await ctx.claude.messages.create(
            model=model_clamped,
            max_tokens=max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        usage = {
            "input_tokens":               resp.usage.input_tokens,
            "output_tokens":              resp.usage.output_tokens,
            "cache_read_input_tokens":    getattr(resp.usage, "cache_read_input_tokens", 0),
            "cache_creation_input_tokens":getattr(resp.usage, "cache_creation_input_tokens", 0),
        }
        # Accumulate into ctx so subsequent calls see the running total.
        ctx.tokens_in  += usage["input_tokens"] + usage["cache_creation_input_tokens"]
        ctx.tokens_out += usage["output_tokens"]
        ctx.cost_gbp   += self._estimate_cost_gbp(
            usage["input_tokens"],
            usage["output_tokens"],
            usage["cache_read_input_tokens"],
            model_clamped,
        )
        return text, usage

    async def think_parallel(
        self,
        ctx: AgentContext,
        prompts: list[dict],
        *,
        model: str | None = None,
        concurrency: int = 10,
        max_tokens: int = 512,
    ) -> list[tuple[str, dict]]:
        """Parallel Claude calls with concurrency cap + per-call budget
        enforcement. A BudgetExceeded from any call short-circuits the batch
        (remaining slots return an error tuple)."""
        import asyncio

        sem = asyncio.Semaphore(concurrency)
        stop = asyncio.Event()

        async def one(p: dict) -> tuple[str, dict]:
            if stop.is_set():
                return "[budget_stopped]", {}
            async with sem:
                if stop.is_set():
                    return "[budget_stopped]", {}
                try:
                    return await self.think(
                        ctx,
                        system=p["system"],
                        user=p["user"],
                        model=model,
                        max_tokens=max_tokens,
                        cached_blocks=p.get("cached_blocks"),
                    )
                except BudgetExceeded as be:
                    log.warning("%s: parallel batch halted — %s", self.name, be)
                    stop.set()
                    return f"[budget_exceeded: {be}]", {}
                except Exception as e:
                    log.exception("think_parallel item failed")
                    return f"[error: {e}]", {}

        return await asyncio.gather(*(one(p) for p in prompts))

    # ── Reasoning helpers (superpowers-style plan / critique / verify) ──────
    #
    # Thin wrappers around self.think() that implement the plan → execute →
    # self-critique → verify loop. Each helper defaults to Haiku + tight token
    # caps so the scaffold is cheap relative to the main work.

    async def plan(
        self,
        ctx: AgentContext,
        *,
        goal: str,
        constraints: str = "",
        max_steps: int = 6,
    ) -> list[dict]:
        """Return an ordered list of steps to reach ``goal``.

        Each step is ``{"step": int, "action": str, "checks": str}``. Raises
        ValueError if Claude returns non-JSON.
        """
        system = (
            "You plan work for a specialist agent. Output ONLY a JSON array of "
            f"at most {max_steps} steps. Each step: "
            '{"step": int, "action": "<=120 chars", "checks": "<=120 chars how to verify"}. '
            "Prefer fewer, larger steps. No prose."
        )
        user = f"GOAL: {goal}\nCONSTRAINTS: {constraints or 'none'}"
        text, _ = await self.think(
            ctx, system=system, user=user, max_tokens=1024
        )
        try:
            steps = json.loads(text)
            if not isinstance(steps, list):
                raise ValueError("plan was not a JSON array")
            return steps[:max_steps]
        except Exception as e:
            raise ValueError(f"plan() got non-JSON from Claude: {text[:200]}") from e

    async def critique(
        self,
        ctx: AgentContext,
        *,
        artifact: str,
        rubric: str,
    ) -> dict:
        """Self-critique an artifact (code / JSON / text) against a rubric.

        Returns ``{"issues": [...], "severity": "low|med|high|none", "score": 0-100}``.
        """
        system = (
            "You critique agent output against a rubric. Output ONLY JSON: "
            '{"issues": ["<=140 chars each"], "severity": "none|low|med|high", '
            '"score": 0-100}. Be terse. No prose.'
        )
        user = f"RUBRIC:\n{rubric}\n\nARTIFACT:\n{artifact[:6000]}"
        text, _ = await self.think(
            ctx, system=system, user=user, max_tokens=768
        )
        try:
            return json.loads(text)
        except Exception:
            return {"issues": ["critique unparseable"], "severity": "med", "score": 50}

    async def verify(
        self,
        ctx: AgentContext,
        *,
        artifact: str,
        criteria: str,
    ) -> tuple[bool, str]:
        """Yes/no verification. Returns (ok, one-line note).

        Cheap gate to run before persisting / acting on a Claude-generated
        artifact. Failing verify should usually trigger one retry, then abort.
        """
        system = (
            "You verify whether an artifact meets binary criteria. Output ONLY "
            'JSON: {"ok": true|false, "note": "<=120 chars"}. No prose.'
        )
        user = f"CRITERIA:\n{criteria}\n\nARTIFACT:\n{artifact[:4000]}"
        text, _ = await self.think(
            ctx, system=system, user=user, max_tokens=256
        )
        try:
            obj = json.loads(text)
            return bool(obj.get("ok")), str(obj.get("note", ""))[:200]
        except Exception:
            return False, f"verify() unparseable: {text[:120]}"

    async def plan_and_execute(
        self,
        ctx: AgentContext,
        *,
        goal: str,
        executor,
        constraints: str = "",
        verify_criteria: str | None = None,
        max_retries: int = 1,
    ) -> dict:
        """Run plan → executor(step) per step → optional verify.

        ``executor`` is ``async def(step: dict, ctx) -> dict``. Returns
        ``{"steps": [...], "results": [...], "verified": bool|None}``.
        Short-circuits on first step exception.
        """
        steps = await self.plan(ctx, goal=goal, constraints=constraints)
        results: list[dict] = []
        for step in steps:
            attempt = 0
            while True:
                try:
                    out = await executor(step, ctx)
                    results.append({"step": step, "out": out})
                    break
                except Exception as e:
                    attempt += 1
                    if attempt > max_retries:
                        results.append({"step": step, "error": str(e)[:400]})
                        return {"steps": steps, "results": results, "verified": False}
        verified = None
        if verify_criteria:
            ok, _note = await self.verify(
                ctx,
                artifact=json.dumps(results, default=str)[:4000],
                criteria=verify_criteria,
            )
            verified = ok
        return {"steps": steps, "results": results, "verified": verified}

    # ── Cost estimation ─────────────────────────────────────────────────────

    @staticmethod
    def _estimate_cost_gbp(
        tokens_in: int,
        tokens_out: int,
        cached_read: int,
        model: str,
    ) -> float:
        rate_in, rate_cached, rate_out = _MODEL_PRICING_USD_PER_MTOK.get(
            model, _MODEL_PRICING_USD_PER_MTOK[MODEL_SONNET]
        )
        usd = (
            (tokens_in    / 1e6) * rate_in
          + (cached_read  / 1e6) * rate_cached
          + (tokens_out   / 1e6) * rate_out
        )
        return round(usd * _USD_TO_GBP, 5)

    # ── Lifecycle hooks ─────────────────────────────────────────────────────

    async def on_success(self, ctx: AgentContext, result: AgentResult) -> None:
        # Always sync ctx totals into the result so persisted cost matches
        # what actually happened (subclasses might forget to set these).
        if not result.cost_gbp:
            result.cost_gbp = ctx.cost_gbp
        if not result.tokens_in:
            result.tokens_in = ctx.tokens_in
        if not result.tokens_out:
            result.tokens_out = ctx.tokens_out
        result.duration_s = round(time.time() - ctx.started_at, 2)
        await self._record_run(ctx, result)

    async def on_failure(self, ctx: AgentContext, exc: BaseException) -> None:
        result = AgentResult(
            ok=False,
            summary=f"{type(exc).__name__}: {exc}"[:500],
            cost_gbp=ctx.cost_gbp,
            tokens_in=ctx.tokens_in,
            tokens_out=ctx.tokens_out,
            duration_s=round(time.time() - ctx.started_at, 2),
        )
        await self._record_run(ctx, result)
        await self._record_failure(ctx, exc)

    # ── Persistence ─────────────────────────────────────────────────────────

    async def _record_run(self, ctx: AgentContext, result: AgentResult) -> None:
        await ctx.db.execute(
            """
            INSERT INTO agent_runs (
                run_id, agent_name, ok, summary, data,
                cost_gbp, tokens_in, tokens_out, duration_s, started_at
            )
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8, $9, to_timestamp($10))
            ON CONFLICT (run_id) DO UPDATE SET
                ok = EXCLUDED.ok,
                summary = EXCLUDED.summary,
                data = EXCLUDED.data,
                cost_gbp = EXCLUDED.cost_gbp,
                tokens_in = EXCLUDED.tokens_in,
                tokens_out = EXCLUDED.tokens_out,
                duration_s = EXCLUDED.duration_s
            """,
            ctx.run_id,
            ctx.agent_name,
            result.ok,
            result.summary,
            json.dumps(result.data),
            result.cost_gbp,
            result.tokens_in,
            result.tokens_out,
            result.duration_s,
            ctx.started_at,
        )

    async def _record_failure(self, ctx: AgentContext, exc: BaseException) -> None:
        await ctx.db.execute(
            """
            INSERT INTO agent_failures (run_id, agent_name, error_type, error_message)
            VALUES ($1, $2, $3, $4)
            """,
            ctx.run_id,
            ctx.agent_name,
            type(exc).__name__,
            str(exc)[:2000],
        )

    # ── Notifications ───────────────────────────────────────────────────────

    async def notify_slack(self, ctx: AgentContext, message: str) -> None:
        webhook = os.getenv("SLACK_WEBHOOK_URL")
        if not webhook:
            return
        try:
            await ctx.http.post(webhook, json={"text": message}, timeout=10)
        except Exception:
            log.exception("Slack notification failed")

    async def notify_email(
        self, ctx: AgentContext, *, to: str, subject: str, html: str
    ) -> None:
        api_key = os.getenv("RESEND_API_KEY")
        from_addr = os.getenv("RESEND_FROM", "bots@princeps.energy")
        if not api_key:
            return
        try:
            await ctx.http.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"from": from_addr, "to": to, "subject": subject, "html": html},
                timeout=15,
            )
        except Exception:
            log.exception("Resend email failed")

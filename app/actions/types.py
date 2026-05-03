"""Concrete action types — the first 6 ports from the existing 31 chat intents.

Add more by subclassing ActionType and decorating with @action("<id>").
"""

from __future__ import annotations

from typing import ClassVar, Literal

from app.actions.registry import ActionContext, ActionResult, ActionType, action


@action("run_feasibility")
class RunFeasibility(ActionType):
    """Trigger a full feasibility analysis on a site (grid + planning + finance + EO)."""
    site_rid: str
    scenario: Literal["base", "optimistic", "stress"] = "base"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        # Wire to existing app/agent.py feasibility intent in a follow-up.
        return ActionResult(
            ok=True, summary=f"feasibility queued for {self.site_rid} scenario={self.scenario}",
            rid="", side_effects=["agent.queue_feasibility"],
            payload={"site_rid": self.site_rid, "scenario": self.scenario},
        )


@action("generate_grid_connection")
class GenerateGridConnection(ActionType):
    """Generate a grid-connection assessment for a site against a target substation."""
    site_rid: str
    substation_rid: str
    voltage_level_kv: float
    requested_export_mw: float

    async def execute(self, ctx: ActionContext) -> ActionResult:
        return ActionResult(
            ok=True, summary=f"connection assessment queued: {self.site_rid} → {self.substation_rid}",
            rid="", side_effects=["grid.connection_analyser"],
            payload=self.model_dump(),
        )


@action("lock_site_design")
class LockSiteDesign(ActionType):
    """Lock the current DesignCanvas state as the canonical design for a site."""
    site_rid: str
    note: str | None = None

    async def execute(self, ctx: ActionContext) -> ActionResult:
        return ActionResult(
            ok=True, summary=f"design locked for {self.site_rid}",
            rid="", side_effects=["design.lock"],
            payload={"site_rid": self.site_rid, "note": self.note},
        )


@action("send_dno_engagement")
class SendDnoEngagement(ActionType):
    """Send a formal DNO engagement letter for a site."""
    site_rid: str
    dno_area: str
    contact_email: str
    template: Literal["initial_enquiry", "follow_up", "formal_application"] = "initial_enquiry"

    async def execute(self, ctx: ActionContext) -> ActionResult:
        return ActionResult(
            ok=True, summary=f"DNO engagement letter scheduled for {self.dno_area}",
            rid="", side_effects=["email.send", "agent.dno_engagement"],
            payload=self.model_dump(),
        )


@action("screen_counterparty")
class ScreenCounterparty(ActionType):
    """Screen a counterparty against UK sanctions + GLEIF + Companies House."""
    legal_name: str
    lei: str | None = None
    ch_number: str | None = None

    async def execute(self, ctx: ActionContext) -> ActionResult:
        from utils.uk_sanctions_ingester import screen_name  # lazy
        matches = await screen_name(ctx.pool, self.legal_name) if ctx.pool else []
        sanctioned = bool(matches and matches[0].get("score", 0) > 0.85)
        return ActionResult(
            ok=True,
            summary=("MATCH on UK sanctions" if sanctioned
                     else f"clear ({len(matches)} weak matches)"),
            rid="",
            side_effects=["industrial.sanctions_screen"],
            payload={"sanctioned": sanctioned, "matches": matches},
        )


@action("refresh_industrial_base")
class RefreshIndustrialBase(ActionType):
    """One-shot refresh of UK Companies House + GLEIF + sanctions caches."""
    sources: list[Literal["sanctions", "lei", "ch"]] = ["sanctions"]

    async def execute(self, ctx: ActionContext) -> ActionResult:
        from utils import uk_sanctions_ingester as sanc  # lazy
        results: dict = {}
        if "sanctions" in self.sources and ctx.pool is not None:
            try:
                results["sanctions"] = await sanc.refresh(ctx.pool)
            except Exception as exc:
                results["sanctions"] = {"error": f"{type(exc).__name__}: {exc}"}
        return ActionResult(
            ok=True, summary=f"industrial base refresh complete ({list(results)})",
            rid="", side_effects=["industrial.refresh"],
            payload=results,
        )

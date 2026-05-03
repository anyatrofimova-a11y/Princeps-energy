"""Princeps Action Registry — Foundry-style typed action types.

An ActionType is a typed, validated, atomic ontology mutation with side
effects. Registering an action gives you for free:
  • parameter validation via Pydantic
  • RID-keyed audit trail
  • optional preview-before-commit
  • a single tool surface for the agent layer (no more hand-rolled REST
    fetches scattered across 30 panels)

Public surface:

    from app.actions import action, ActionType, ActionResult

    @action("run_feasibility")
    class RunFeasibility(ActionType):
        site_rid: str
        scenario: Literal["base", "optimistic", "stress"] = "base"
        async def execute(self, ctx) -> ActionResult: ...

The agent layer (app/chat.py / app/agent.py) discovers actions via
``registry.list()`` and surfaces them as Claude tools.
"""

from app.actions.registry import (
    ActionContext,
    ActionRegistry,
    ActionResult,
    ActionType,
    action,
    registry,
)

__all__ = [
    "ActionContext",
    "ActionRegistry",
    "ActionResult",
    "ActionType",
    "action",
    "registry",
]

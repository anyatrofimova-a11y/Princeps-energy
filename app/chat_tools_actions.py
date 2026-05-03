"""Bridge: Action Registry → Anthropic Tools API.

Walks ``app.actions.registry`` at module load and surfaces every registered
ActionType as a Claude tool spec. The chat dispatch loop in ``app/chat.py``
routes any tool call whose name matches a registered action through
``dispatch_action_tool`` — which validates input, runs the action, and writes
the audit row via the existing ``app.actions.registry.invoke`` path.

Closes the AIP parity gap: actions defined in the typed registry no longer
need a hand-rolled tool spec to be callable by the LLM.
"""

from __future__ import annotations

import logging
from typing import Any

from app.actions.registry import ActionContext, registry
from app.security.safe_log import safe_log

# Force-import the concrete action types so they self-register on the registry
# at import time. Without this, ``registry.list()`` returns an empty list.
import app.actions.types  # noqa: F401  (side-effect import — registers actions)

log = logging.getLogger("princeps.chat_tools_actions")

# Tool-name prefix so action tools are visually distinct from the legacy
# hand-rolled tools and easy to route in the dispatch loop. The Anthropic
# Tools API requires names to match ``^[a-zA-Z0-9_-]{1,64}$``.
ACTION_TOOL_PREFIX = "action_"


def _to_tool_spec(action_id: str, cls: type) -> dict[str, Any]:
    """Convert a registered ActionType subclass into an Anthropic tool spec.

    Pydantic's ``model_json_schema()`` already produces a JSON-Schema-shaped
    dict; we strip the top-level ``title`` (Claude doesn't need it) and pass
    the rest through unchanged so additionalProperties / required / nested
    refs all survive.
    """
    schema = cls.model_json_schema()
    # Anthropic requires input_schema.type == "object" at the top level.
    schema.pop("title", None)
    if schema.get("type") != "object":
        # Defensive — every Pydantic BaseModel renders as an object schema,
        # but if a subclass overrides we don't silently break the LLM call.
        log.warning("action %s schema is not object-typed: %s", action_id, schema.get("type"))

    description = (cls.__doc__ or f"Run the {action_id} action.").strip()
    if len(description) > 1024:
        description = description[:1021] + "..."

    return {
        "name": f"{ACTION_TOOL_PREFIX}{action_id}",
        "description": description,
        "input_schema": schema,
    }


def get_action_tools() -> list[dict[str, Any]]:
    """Return Anthropic Tools API specs for every registered action.

    Called once at module load by ``app/chat.py`` to extend the ``TOOLS``
    array. Adding a new ``@action(...)``-decorated class is enough to surface
    it to the chat LLM — no edits to chat.py required.
    """
    tools: list[dict[str, Any]] = []
    # ``registry.list()`` returns sorted dicts; we want the live class refs.
    for action_id, cls in sorted(registry._actions.items()):
        try:
            tools.append(_to_tool_spec(action_id, cls))
        except Exception as exc:
            log.warning("action %s failed tool-spec generation: %s", action_id, exc)
    log.info("get_action_tools: surfaced %d action tools", len(tools))
    return tools


def is_action_tool(tool_name: str) -> bool:
    """True if ``tool_name`` refers to a registered ActionType (vs legacy tool)."""
    return tool_name.startswith(ACTION_TOOL_PREFIX)


def _strip_prefix(tool_name: str) -> str:
    if not tool_name.startswith(ACTION_TOOL_PREFIX):
        return tool_name
    return tool_name[len(ACTION_TOOL_PREFIX):]


async def dispatch_action_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    user_id: str | None,
    tenant_id: str | None,
    pool: Any = None,
    request: Any = None,
) -> dict[str, Any]:
    """Run a registered action via the typed registry and return a JSON-safe dict.

    Returns the audited ``ActionResult`` as a plain dict so the chat dispatch
    loop can serialise it to SSE and feed it back into Claude as a
    ``tool_result``.
    """
    action_id = _strip_prefix(tool_name)
    ctx = ActionContext(
        user_id=user_id,
        tenant_id=tenant_id,
        pool=pool,
        request=request,
    )

    # Provenance log up front so we always have a record even if the call
    # raises before reaching the registry's own audit writer.
    safe_log(
        "action_tool.invoke",
        user_id=user_id,
        tenant_id=tenant_id,
        action_id=action_id,
        params=tool_input,
        redact=["password", "token", "secret"],
    )

    try:
        result = await registry.invoke(action_id, tool_input or {}, ctx)
    except KeyError as exc:
        # Unknown action — surface as a normal tool result so the LLM can
        # apologise/recover instead of escalating to a top-level exception.
        return {
            "ok": False,
            "error": f"unknown_action: {exc}",
            "summary": f"action {action_id!r} is not registered",
        }
    except Exception as exc:  # pragma: no cover — defence-in-depth
        log.exception("action %s dispatch raised", action_id)
        safe_log(
            "action_tool.error",
            user_id=user_id,
            tenant_id=tenant_id,
            action_id=action_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "summary": f"action {action_id!r} failed during dispatch",
        }

    # ``preview=False`` always returns ActionResult; we never call preview here.
    return {
        "ok": getattr(result, "ok", False),
        "summary": getattr(result, "summary", ""),
        "rid": getattr(result, "rid", ""),
        "side_effects": list(getattr(result, "side_effects", []) or []),
        "payload": dict(getattr(result, "payload", {}) or {}),
    }


__all__ = [
    "ACTION_TOOL_PREFIX",
    "dispatch_action_tool",
    "get_action_tools",
    "is_action_tool",
]

"""Provenance-tagged structured logger — Palantir "safe-logging" pattern.

Every Princeps log line emitted via ``safe_log()`` carries:
  * ``event``       — short kebab-case event id (e.g. ``action_tool.invoke``)
  * ``user_id``     — opaque user identifier (None for anonymous)
  * ``tenant_id``   — opaque tenant identifier (None for system events)
  * ``action_id``   — when emitted from an action dispatcher
  * ``ts``          — ISO-8601 UTC timestamp
  * arbitrary kwargs — PII fields redacted by default

The logger writes a single JSON line to ``princeps.audit`` so downstream
shippers (Cloudwatch / Datadog / Vector) can index without regex.

Usage::

    from app.security.safe_log import safe_log
    safe_log(
        "action_tool.invoke",
        user_id="u_123",
        tenant_id="t_acme",
        action_id="run_feasibility",
        params={"site_rid": "rid.site.42"},
        redact=["api_key", "token"],
    )
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

# Default field names that are redacted unconditionally, even if not in the
# caller-provided redact list. Mirrors the OWASP "always-sensitive" set.
_ALWAYS_REDACT: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "client_secret",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "auth_header",
        "private_key",
        "ssn",
        "credit_card",
    }
)

_REDACTED_PLACEHOLDER = "***REDACTED***"

log = logging.getLogger("princeps.audit")


def redact(payload: Any, fields: Iterable[str] = ()) -> Any:
    """Return ``payload`` with sensitive field values replaced.

    Walks dicts + lists recursively. Field-name match is case-insensitive.
    Non-collection scalars are returned unchanged (we redact by name, not by
    value heuristic — that's a different pass).
    """
    extra = {f.lower() for f in fields}
    blocklist = _ALWAYS_REDACT | extra

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: (_REDACTED_PLACEHOLDER if k.lower() in blocklist else _walk(v))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, tuple):
            return tuple(_walk(v) for v in node)
        return node

    return _walk(payload)


def safe_log(
    event: str,
    *,
    user_id: str | None = None,
    tenant_id: str | None = None,
    action_id: str | None = None,
    redact: Iterable[str] = (),  # noqa: A002 — name shadows; intentional API
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit one provenance-tagged JSON log line.

    ``redact`` extends the always-redacted set; named field values whose
    keys match (case-insensitive) are replaced before serialisation. Always
    best-effort: a logging failure is swallowed so business code never gets
    a stack trace from telemetry.
    """
    try:
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
        }
        if user_id is not None:
            record["user_id"] = user_id
        if tenant_id is not None:
            record["tenant_id"] = tenant_id
        if action_id is not None:
            record["action_id"] = action_id

        # Caller fields go through the redactor so accidental ``password=...``
        # never reaches the log sink.
        if fields:
            redacted = globals()["redact"](fields, redact)  # call module-level redact
            # Fold the redacted fields into the record at the top level so log
            # consumers can index on ``params.site_rid`` style paths.
            record.update(redacted)

        log.log(level, json.dumps(record, default=str))
    except Exception:  # pragma: no cover — telemetry must never crash callers
        # Last resort: a plain warning that does not echo any structured data
        # (the data may be the cause of the failure).
        log.warning("safe_log: emit failed for event=%s", event, exc_info=False)


__all__ = ["redact", "safe_log"]

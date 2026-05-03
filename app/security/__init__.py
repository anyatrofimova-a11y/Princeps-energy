"""Princeps security primitives — safe logging, redaction, provenance tags.

Public surface:

    from app.security import safe_log, redact

The Palantir "safe-logging" pattern: every log line carries a structured
provenance tag (event, user_id, tenant_id, action_id, ...) and is JSON-shaped
so downstream sinks (Cloudwatch, Datadog) can index without regex. Sensitive
fields are redacted by default before they hit the wire.
"""

from app.security.safe_log import redact, safe_log

__all__ = ["redact", "safe_log"]

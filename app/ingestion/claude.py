"""
app/ingestion/claude.py — thin Anthropic client factory for the ingestion
workers.

The app already constructs an AsyncAnthropic on ``app.state.claude``
inside :func:`app.main.lifespan`, but the ingestion workers are driven by
APScheduler cron jobs that don't have a Request context, so they can't
use :func:`app.deps.get_claude`. This module exposes a process-local
singleton keyed on the ``CLAUDE_API_KEY`` env var.

The client returned is an instance of ``anthropic.AsyncAnthropic``; use
``claude.messages.create(...)`` directly. Keep calls cheap (Haiku) —
budget guardrails live in :mod:`app.ingestion.classifier` and
:mod:`app.ingestion.ner`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("princeps.ingestion.claude")

_client: Any = None


def get_claude_client():
    """Return a process-singleton AsyncAnthropic client, or ``None`` if the
    ``anthropic`` package isn't installed or ``CLAUDE_API_KEY`` isn't set.

    Callers must be defensive against ``None`` — the ingestion workers are
    designed to degrade to regex-only classification when the LLM is
    unavailable (ie. on CI, local dev, or when the key is rotated).
    """
    global _client
    if _client is not None:
        return _client

    key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        log.warning("CLAUDE_API_KEY not set — ingestion LLM stages disabled")
        return None

    try:
        import anthropic
    except Exception as e:
        log.warning("anthropic SDK not importable — LLM stages disabled: %s", e)
        return None

    _client = anthropic.AsyncAnthropic(api_key=key)
    return _client


# Model used for all low-cost ingestion LLM work (classification, NER
# fallback, light triage). Never upgrade without flagging in a PR — cost
# scales linearly with document volume.
HAIKU_MODEL = "claude-haiku-4-5"


# Pricing reference (USD / M tok) — kept here so classifier.py / ner.py can
# tack a tiny cost estimate onto IngestionResult. Mirrors
# app/agents/base.py._MODEL_PRICING_USD_PER_MTOK.
HAIKU_PRICING_USD_PER_MTOK = (0.80, 0.08, 4.00)  # (input, cached_read, output)
USD_TO_GBP = 0.82


def estimate_cost_gbp(tokens_in: int, tokens_out: int) -> float:
    """Rough cost estimate for a single Haiku call."""
    inp_usd = tokens_in * HAIKU_PRICING_USD_PER_MTOK[0] / 1_000_000
    out_usd = tokens_out * HAIKU_PRICING_USD_PER_MTOK[2] / 1_000_000
    return (inp_usd + out_usd) * USD_TO_GBP

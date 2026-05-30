"""
memory.py — thin Python client for the agentmemory sidecar.

agentmemory (rohitg00/agentmemory, Apache-2.0) runs as a separate Fly app
(``princeps-agentmemory``) reachable via Fly's internal DNS at
``http://princeps-agentmemory.internal:3111``.

This module exposes 3 async functions for the rest of Princeps:

  * ``memory_recall(project_id, query, top_k=5)``         — fetch prior facts
  * ``memory_capture(project_id, session_id, messages)``   — store new ones
  * ``memory_persist_verdict(project_id, site_id, intent, verdict)``

All calls soft-fail: if the sidecar is unreachable Princeps continues to
work, just without cross-session memory. Each call logs a warning on
failure so we can spot sidecar outages in observability.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("princeps.memory")

DEFAULT_URL = os.environ.get(
    "AGENTMEMORY_URL", "http://princeps-agentmemory.internal:3111"
)
TIMEOUT_S = 10.0


def _base_url() -> str:
    # Re-read each call so a Fly secrets bump doesn't require process restart.
    return os.environ.get("AGENTMEMORY_URL", DEFAULT_URL)


async def memory_recall(
    project_id: str,
    query: str,
    *,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Return up to ``top_k`` prior memory records relevant to ``query``.

    Returns an empty list on any error so callers can safely treat the
    response as "best effort context" without try/except.
    """
    payload = {
        "query": query,
        "limit": top_k,
        "filter": {"project_id": project_id},
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.post(f"{_base_url()}/api/memory/search", json=payload)
            r.raise_for_status()
            data = r.json()
            return data.get("results", []) or []
    except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
        log.warning("memory_recall failed: %s", exc)
        return []


async def memory_capture(
    project_id: str,
    session_id: str,
    messages: list[dict[str, Any]],
    *,
    summary: str | None = None,
) -> dict[str, Any]:
    """Persist a slice of conversation for later recall. Idempotent on session_id."""
    payload = {
        "session_id": session_id,
        "project_id": project_id,
        "messages": messages,
    }
    if summary:
        payload["summary"] = summary
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.post(f"{_base_url()}/api/memory/capture", json=payload)
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
        log.warning("memory_capture failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def memory_persist_verdict(
    project_id: str,
    site_id: str,
    intent: str,
    verdict: dict[str, Any],
) -> dict[str, Any]:
    """Store a structured agent verdict (GO/CAUTION/NO-GO + rationale + numbers)
    so future sessions on the same project can recall it via ``memory_recall``.
    """
    payload = {
        "project_id": project_id,
        "site_id": site_id,
        "intent": intent,
        "verdict": verdict,
        "kind": "agent_verdict",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.post(
                f"{_base_url()}/api/memory/capture",
                json={
                    "session_id": f"{project_id}:{site_id}:{intent}",
                    "project_id": project_id,
                    "messages": [
                        {
                            "role": "assistant",
                            "content": (
                                f"VERDICT [{intent}] for site {site_id}: "
                                f"{verdict.get('label', '?')} — "
                                f"{verdict.get('rationale', '')}"
                            ),
                            "metadata": payload,
                        }
                    ],
                },
            )
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, httpx.TimeoutException, ValueError) as exc:
        log.warning("memory_persist_verdict failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def memory_health() -> bool:
    """Cheap probe used by /health to flag sidecar status.

    Hits the agentmemory livez at ``/agentmemory/livez``. Generous timeout
    because the sidecar uses ``auto_stop_machines = "stop"`` and cold-start
    takes ~3-5s on first request after idle.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{_base_url()}/agentmemory/livez")
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False

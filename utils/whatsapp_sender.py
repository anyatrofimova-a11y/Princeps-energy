"""WhatsApp Cloud API sender.

Sends a text message to a phone via Meta's Graph API.
Requires WHATSAPP_PHONE_NUMBER_ID + WHATSAPP_ACCESS_TOKEN env vars.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)


async def send_whatsapp_text(to_phone_e164: str, body: str) -> dict[str, Any]:
    """Send a freeform text reply. Returns the WA API response."""
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    if not phone_id or not token:
        log.warning("WhatsApp env not configured; would have sent to %s: %s",
                    to_phone_e164, body[:120])
        return {"skipped": True, "reason": "no_credentials"}
    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_e164.lstrip("+"),
        "type": "text",
        "text": {"body": body[:4096]},   # WA hard limit
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            url,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=payload,
        )
        if r.status_code >= 300:
            log.error("WhatsApp send failed: %s %s", r.status_code, r.text[:300])
            return {"error": r.text[:300], "http": r.status_code}
        return r.json()

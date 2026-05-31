"""WhatsApp Cloud API webhook + outbox.

Receives messages from WhatsApp (Meta Graph API), routes them through
the brief translator, and either enqueues a builder task or replies
inline.

Setup (Meta Business Platform):
  1. Create a Meta Business app with WhatsApp Business product.
  2. Get phone_number_id + permanent access token.
  3. Set webhook URL to:
       https://princeps-api.fly.dev/api/whatsapp/webhook
     and verify token = WHATSAPP_VERIFY_TOKEN (any string you pick).
  4. Subscribe to the `messages` field.
  5. Add your own phone to whatsapp.operators table.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.deps import get_pool

log = logging.getLogger("princeps.whatsapp")
router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


# ── Verification handshake (GET) ────────────────────────────────────────────

@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """Meta's one-time verification handshake."""
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN")
    if hub_mode == "subscribe" and hub_verify_token and hub_verify_token == expected:
        return hub_challenge or ""
    raise HTTPException(403, "verification failed")


# ── Inbound messages (POST) ─────────────────────────────────────────────────

def _verify_signature(raw_body: bytes, header_sig: str | None) -> bool:
    """Verify X-Hub-Signature-256 header against WHATSAPP_APP_SECRET."""
    secret = os.environ.get("WHATSAPP_APP_SECRET")
    if not secret or not header_sig:
        return False
    mac = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={mac}", header_sig)


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    raw = await request.body()
    if os.environ.get("WHATSAPP_APP_SECRET") and not _verify_signature(raw, x_hub_signature_256):
        raise HTTPException(401, "bad signature")
    payload = json.loads(raw)

    # WA payload shape: entry[].changes[].value.messages[]
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []) or []:
                await _handle_inbound(pool, msg, value)
    return {"ok": True}


async def _handle_inbound(pool, msg: dict[str, Any], envelope: dict[str, Any]):
    from utils.brief_translator import translate_brief
    from utils.whatsapp_sender import send_whatsapp_text

    wa_id = msg.get("id")
    wa_from = msg.get("from")
    text = (msg.get("text") or {}).get("body") or ""

    # Allowlist check
    async with pool.acquire() as conn:
        is_op = await conn.fetchval(
            "SELECT 1 FROM whatsapp.operators WHERE phone_e164 = $1",
            f"+{wa_from}" if not wa_from.startswith("+") else wa_from,
        )
    if not is_op:
        log.warning("ignoring message from non-operator %s", wa_from)
        return

    # Persist inbound
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO whatsapp.messages
                 (message_id, wa_from, direction, body, raw)
               VALUES ($1, $2, 'inbound', $3, $4::jsonb)
               ON CONFLICT (message_id) DO NOTHING""",
            wa_id, wa_from, text, json.dumps(envelope),
        )

    if not text.strip():
        return

    routed = await translate_brief(text)
    intent = routed.get("intent", "ask")

    if intent == "ask":
        reply = routed.get("answer", "(no answer)")
        await send_whatsapp_text(wa_from, reply)
        await _log_outbound(pool, wa_from, reply, intent="ask")
        return

    # build / research → enqueue a builder.queue row
    title = (routed.get("title") or text)[:200]
    brief = routed.get("brief") or text
    if intent == "research":
        brief = (
            "RESEARCH MODE — use WebSearch and produce a markdown summary "
            "(no code changes unless explicitly asked).\n\n" + brief
        )
    async with pool.acquire() as conn:
        task_id = await conn.fetchval(
            """INSERT INTO builder.queue
                 (title, brief, context_paths, branch_policy, priority,
                  requested_by)
               VALUES ($1, $2, $3::text[], 'pr', $4, $5)
               RETURNING task_id::text""",
            title, brief,
            list(routed.get("context_paths") or []),
            int(routed.get("priority", 5)),
            f"whatsapp:{wa_from}",
        )
        await conn.execute(
            "UPDATE whatsapp.messages SET intent=$2, task_id=$3 "
            "WHERE message_id=$1",
            wa_id, intent, task_id,
        )

    ack = (
        f"Got it. Queued as {intent} task `{title}` "
        f"(id `{task_id[:8]}`, priority {routed.get('priority',5)}). "
        f"I'll message back when the PR opens."
    )
    await send_whatsapp_text(wa_from, ack)
    await _log_outbound(pool, wa_from, ack, intent=intent, task_id=task_id)


async def _log_outbound(pool, wa_to: str, body: str, *, intent: str, task_id: str | None = None):
    import secrets
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO whatsapp.messages
                 (message_id, wa_from, wa_to, direction, body, intent, task_id)
               VALUES ($1, 'princeps-bot', $2, 'outbound', $3, $4, $5)""",
            f"out_{secrets.token_hex(12)}", wa_to, body, intent, task_id,
        )


# ── Outbound trigger from the builder agent ─────────────────────────────────

@router.post("/notify-task-complete/{task_id}")
async def notify_task_complete(
    task_id: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Called by the builder agent after a PR opens. Looks up the
    operator who originally messaged + DMs them the PR url."""
    from utils.whatsapp_sender import send_whatsapp_text
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT q.title, q.pr_url, q.branch_name, q.status,
                      m.wa_from
                 FROM builder.queue q
            LEFT JOIN whatsapp.messages m ON m.task_id = q.task_id
                                         AND m.direction = 'inbound'
                WHERE q.task_id::text = $1
             ORDER BY m.created_at ASC LIMIT 1""",
            task_id,
        )
    if not row or not row["wa_from"]:
        return {"skipped": True, "reason": "no whatsapp origin"}
    body = (
        f"✅ {row['title']}\n"
        f"Status: {row['status']}\n"
        f"PR: {row['pr_url'] or '(direct push)'}"
    )
    return await send_whatsapp_text(row["wa_from"], body)

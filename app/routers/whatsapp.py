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
    """Route inbound message to the right dispatcher (slash / plan / ask)."""
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
    kind = routed.get("kind", "ask")

    if kind == "slash":
        reply = await _dispatch_slash(pool, routed["command"], routed.get("args", ""),
                                      requested_by=f"whatsapp:{wa_from}")
        await send_whatsapp_text(wa_from, reply)
        await _log_outbound(pool, wa_from, reply, intent="slash")
        return

    if kind == "ask":
        reply = routed.get("answer", "(no answer)")
        await send_whatsapp_text(wa_from, reply)
        await _log_outbound(pool, wa_from, reply, intent="ask")
        return

    # kind == "plan" — multi-step. Enqueue every task, link inter-step deps.
    tasks = routed.get("tasks", [])
    if not tasks:
        await send_whatsapp_text(wa_from, "I parsed a plan but no tasks came back. Try rephrasing.")
        return

    plan_summary = routed.get("plan_summary", text[:200])
    import uuid
    plan_group = str(uuid.uuid4())
    step_to_taskid: dict[int, str] = {}
    async with pool.acquire() as conn:
        for t in sorted(tasks, key=lambda x: x.get("step", 1)):
            step = int(t["step"])
            intent = t.get("intent", "build")
            depends = [step_to_taskid[s] for s in t.get("depends_on_steps", [])
                       if s in step_to_taskid]
            title = (t.get("title") or text)[:200]
            brief = t.get("brief") or text
            mode = "build"
            if intent == "research":
                mode = "research"
                brief = (
                    "RESEARCH MODE — investigate using WebSearch + summarise as "
                    "markdown under docs/research/<slug>.md with cited sources.\n\n" + brief
                )
            elif intent == "agent_trigger":
                mode = "agent_trigger"
                brief = f"AGENT TRIGGER: {t.get('agent_name') or t.get('brief')}"
            tid = await conn.fetchval(
                """INSERT INTO builder.queue
                     (title, brief, context_paths, branch_policy, priority,
                      requested_by, depends_on, mode, plan_group)
                   VALUES ($1, $2, $3::text[], 'pr', $4, $5, $6::uuid[], $7, $8::uuid)
                   RETURNING task_id::text""",
                title, brief,
                list(t.get("context_paths") or []),
                int(t.get("priority", 5)),
                f"whatsapp:{wa_from}",
                depends, mode, plan_group,
            )
            step_to_taskid[step] = tid
        await conn.execute(
            "UPDATE whatsapp.messages SET intent='plan', task_id=$2 "
            "WHERE message_id=$1",
            wa_id, list(step_to_taskid.values())[0],
        )

    short_ids = " · ".join(f"`{tid[:8]}`" for tid in step_to_taskid.values())
    ack = (
        f"📋 Plan: {plan_summary}\n"
        f"Queued {len(step_to_taskid)} task(s): {short_ids}\n"
        f"I'll DM you as each PR opens."
    )
    await send_whatsapp_text(wa_from, ack)
    await _log_outbound(pool, wa_from, ack, intent="plan",
                        task_id=list(step_to_taskid.values())[0])


async def _dispatch_slash(pool, command: str, args: str, *, requested_by: str) -> str:
    """Handle /help, /status, /list, /trigger, /show, /cancel, /ship, /research."""
    from utils.agent_orchestrator import (
        cmd_help, cmd_status, cmd_list, cmd_show, cmd_cancel,
        cmd_ship, cmd_research, trigger_agent,
    )
    # Audit
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO builder.commands (command, args, requested_by) "
            "VALUES ($1, $2, $3)", command, args, requested_by,
        )
    cmd = command.lower()
    if cmd == "/help":
        return await cmd_help()
    if cmd == "/status":
        return await cmd_status(pool)
    if cmd in ("/list", "/list-queue"):
        try: n = int(args) if args.strip() else 10
        except ValueError: n = 10
        return await cmd_list(pool, n)
    if cmd == "/show":
        return await cmd_show(pool, args.strip()) if args.strip() else "Usage: /show <id>"
    if cmd == "/cancel":
        return await cmd_cancel(pool, args.strip()) if args.strip() else "Usage: /cancel <id>"
    if cmd == "/ship":
        return await cmd_ship(pool, args.strip()) if args.strip() else "Usage: /ship <id>"
    if cmd == "/research":
        return await cmd_research(pool, args.strip(), requested_by)
    if cmd == "/trigger":
        agent = args.strip().split()[0] if args.strip() else ""
        if not agent: return "Usage: /trigger <agent_name>"
        out = await trigger_agent(pool, agent, requested_by=requested_by)
        if "error" in out and "available" in out:
            return f"unknown agent. available: {', '.join(out['available'])}"
        if "error" in out:
            return f"❌ {agent}: {out['error']}"
        return f"⚡ {agent} ticked. Result: {str(out.get('result'))[:240]}"
    return f"unknown command {command}. /help for options."


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

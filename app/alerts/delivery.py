"""
app/alerts/delivery.py — channel dispatcher for Princeps Alerts.

Given an ``AlertSubscription``'s ``delivery_channels`` ({email, in_app, slack}),
routes a rendered digest to the right destination:

  * ``send_email``     — SMTP if ``SMTP_HOST`` env var is set, else logs and returns.
  * ``send_in_app``    — writes a row into the existing ``notifications`` table
                         (created by ``utils/alert_engine.py``).
  * ``send_slack``     — HTTP POST to a per-user Slack webhook.

Failures are swallowed per-channel and reported in the return dict — one
misconfigured channel should not block the others.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any, Mapping

import asyncpg
import httpx

log = logging.getLogger("princeps.alerts.delivery")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_subject(alert: Mapping[str, Any]) -> str:
    title = alert.get("title") or alert.get("slug") or "Princeps alert"
    return f"[Princeps] {title}"


def render_body(alert: Mapping[str, Any], digest: Mapping[str, Any]) -> str:
    """Plain-text body — identical across email / in-app / Slack."""
    extract = digest.get("llm_extract") or "(no LLM summary — raw documents below)"
    doc_count = len(digest.get("document_ids") or [])
    lines = [
        f"Alert: {alert.get('title') or alert.get('slug')}",
        f"Cluster: {alert.get('cluster') or '—'}",
        f"Documents in digest: {doc_count}",
        "",
        extract.strip(),
        "",
        "— Princeps Intelligence",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _smtp_config_present() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


async def send_email(
    pool: asyncpg.Pool,
    user_id: str,
    alert: Mapping[str, Any],
    digest: Mapping[str, Any],
) -> dict[str, Any]:
    """Send the digest as plain-text email.

    Resolves ``user_id → email`` via the ``users`` table. SMTP configured via
    env: ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``, ``SMTP_PASSWORD``,
    ``SMTP_FROM``, ``SMTP_TLS`` (default true).
    """
    # Look up email
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email FROM users WHERE user_id = $1",
                str(user_id),
            )
    except Exception as exc:
        log.warning("email lookup failed for %s: %s", user_id, exc)
        return {"channel": "email", "status": "skipped", "reason": "lookup_failed"}

    if not row or not row.get("email"):
        return {"channel": "email", "status": "skipped", "reason": "no_email_on_record"}

    if not _smtp_config_present():
        log.info("email digest for %s (%s) not sent — SMTP_HOST unset", user_id, alert.get("slug"))
        return {"channel": "email", "status": "stubbed", "reason": "smtp_unconfigured"}

    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", "alerts@princeps.energy")
    msg["To"] = row["email"]
    msg["Subject"] = render_subject(alert)
    msg.set_content(render_body(alert, digest))

    try:
        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ.get("SMTP_USER")
        pwd = os.environ.get("SMTP_PASSWORD")
        use_tls = os.environ.get("SMTP_TLS", "true").lower() == "true"

        # smtplib is blocking; we're in an async context — run it in a thread.
        import asyncio

        def _send() -> None:
            with smtplib.SMTP(host, port, timeout=30) as s:
                if use_tls:
                    s.starttls()
                if user and pwd:
                    s.login(user, pwd)
                s.send_message(msg)

        await asyncio.to_thread(_send)
        return {"channel": "email", "status": "sent", "to": row["email"]}
    except Exception as exc:
        log.exception("email send failed: %s", exc)
        return {"channel": "email", "status": "failed", "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# In-app (reuses `notifications` table from utils/alert_engine.py)
# ---------------------------------------------------------------------------

async def send_in_app(
    pool: asyncpg.Pool,
    user_id: str,
    alert: Mapping[str, Any],
    digest: Mapping[str, Any],
) -> dict[str, Any]:
    """Write a row into ``notifications`` so the bell icon picks it up."""
    try:
        async with pool.acquire() as conn:
            present = await conn.fetchval(
                "SELECT to_regclass('public.notifications') IS NOT NULL"
            )
            if not present:
                # Fall back to silent success — the table will be created by
                # utils.alert_engine on first run and we don't want to block
                # the digest pipeline for a cold boot.
                return {"channel": "in_app", "status": "skipped", "reason": "notifications_table_missing"}

            await conn.execute(
                """
                INSERT INTO notifications
                    (user_id, alert_type, title, body, severity,
                     source_ref, source_url, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                """,
                str(user_id),
                f"princeps_alert:{alert.get('slug')}",
                render_subject(alert),
                (digest.get("llm_extract") or "")[:2000],
                "info",
                str(alert.get("id")) if alert.get("id") else None,
                None,
                json.dumps({
                    "alert_slug": alert.get("slug"),
                    "alert_id": str(alert.get("id")) if alert.get("id") else None,
                    "digest_id": str(digest.get("id")) if digest.get("id") else None,
                    "document_ids": [str(d) for d in (digest.get("document_ids") or [])],
                    "cluster": alert.get("cluster"),
                }, default=str),
            )
        return {"channel": "in_app", "status": "sent"}
    except Exception as exc:
        log.exception("in-app delivery failed: %s", exc)
        return {"channel": "in_app", "status": "failed", "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

async def send_slack(
    webhook_url: str,
    alert: Mapping[str, Any],
    digest: Mapping[str, Any],
) -> dict[str, Any]:
    """POST a simple Slack message payload to *webhook_url*."""
    if not webhook_url:
        return {"channel": "slack", "status": "skipped", "reason": "no_webhook"}

    payload = {
        "text": render_subject(alert),
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": render_subject(alert)},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": render_body(alert, digest),
                },
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(webhook_url, json=payload)
        if resp.status_code >= 400:
            return {"channel": "slack", "status": "failed",
                    "reason": f"http_{resp.status_code}", "body": resp.text[:200]}
        return {"channel": "slack", "status": "sent"}
    except Exception as exc:
        log.exception("slack delivery failed: %s", exc)
        return {"channel": "slack", "status": "failed", "reason": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def deliver(
    pool: asyncpg.Pool,
    *,
    user_id: str,
    alert: Mapping[str, Any],
    digest: Mapping[str, Any],
    delivery_channels: Mapping[str, Any] | None,
    slack_webhook_url: str | None = None,
) -> list[dict[str, Any]]:
    """Dispatch the digest across all enabled channels.

    Returns a list of per-channel result dicts; the digest_worker can persist
    them or ignore them as suits its metrics pipeline.
    """
    channels = dict(delivery_channels or {"email": True, "in_app": True, "slack": False})
    results: list[dict[str, Any]] = []

    if channels.get("email"):
        results.append(await send_email(pool, user_id, alert, digest))
    if channels.get("in_app"):
        results.append(await send_in_app(pool, user_id, alert, digest))
    if channels.get("slack") and slack_webhook_url:
        results.append(await send_slack(slack_webhook_url, alert, digest))

    return results


__all__ = [
    "render_subject",
    "render_body",
    "send_email",
    "send_in_app",
    "send_slack",
    "deliver",
]

"""
app/routers/billing.py — Stripe billing + team seats (Task #11).

Mounted at ``/api/billing/*``. Drives:

* the paywall in ``app/routers/alerts.py`` (HTTP 402 w/ ``ALERT_CAP``),
* the Stripe Checkout + Customer Portal flows,
* team-tier seat management (invite / accept / remove).

Endpoints
---------
GET    /api/billing/tier                          — current user's tier + seat usage
POST   /api/billing/checkout                      — create a Stripe Checkout Session
POST   /api/billing/portal                        — create a Stripe Billing Portal session
POST   /api/billing/webhook                       — Stripe webhook (signature-verified)
GET    /api/billing/team/seats                    — team owner: list members + invites
POST   /api/billing/team/invite                   — team owner: invite by email
POST   /api/billing/team/invite/{token}/accept    — invitee: accept invite
DELETE /api/billing/team/members/{user_id}        — team owner: remove a member

Auth
----
All endpoints require ``get_current_user`` **except** ``/webhook`` which is
authenticated by Stripe's HMAC signature header.

Idempotency
-----------
* ``checkout.session.completed`` is upserted by ``(user_id)`` — safe to receive
  twice (a future ``stripe_event_id`` ledger would harden this further; see
  TODO at the bottom).
* Invite acceptance is upserted on ``(owner_user_id, member_user_id)`` so
  clicking the same invite link twice is a no-op.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from app.alerts.user_tiers import get_user_tier
from app.billing.price_catalog import (
    PRICE_IDS,
    TIER_METADATA,
    public_catalog,
    tier_from_price_id,
)
from app.billing.seats_check import can_add_seat, seats_summary
from app.billing.stripe_client import (
    StripeNotConfiguredError,
    get_stripe,
    get_webhook_secret,
    is_configured,
)
from app.billing.team_seats import (
    accept_invite,
    create_invite,
    ensure_schema as ensure_team_schema,
    list_members,
    list_pending_invites,
    remove_member,
)
from app.deps import get_current_user, get_pool

log = logging.getLogger("princeps.billing")

router = APIRouter(prefix="/api/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

TierLiteral = Literal["individual", "team", "enterprise"]


class CheckoutBody(BaseModel):
    tier: TierLiteral
    success_url: str = Field(..., description="Absolute URL Stripe redirects to on success.")
    cancel_url: str = Field(..., description="Absolute URL Stripe redirects to on cancel.")
    trial_days: int | None = Field(default=None, ge=0, le=30)


class PortalBody(BaseModel):
    return_url: str


class InviteBody(BaseModel):
    email: EmailStr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_id(user: dict) -> str:
    return str(user.get("user_id") or user.get("id") or "anonymous")


def _user_email(user: dict) -> str | None:
    email = user.get("email")
    return str(email) if email else None


async def _resolve_or_create_stripe_customer(
    pool: asyncpg.Pool,
    user_id: str,
    email: str | None,
) -> str:
    """Return a Stripe customer_id for *user_id*, creating one if missing.

    Idempotent: if ``user_subscriptions.stripe_customer_id`` is already set we
    return it unchanged. Otherwise we create a new Stripe Customer (scoped to
    the user's email) and upsert it into ``user_subscriptions``.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT stripe_customer_id FROM user_subscriptions WHERE user_id = $1",
            user_id,
        )
    if row and row["stripe_customer_id"]:
        return row["stripe_customer_id"]

    stripe = get_stripe()
    customer = stripe.Customer.create(
        email=email,
        metadata={"princeps_user_id": user_id},
    )
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_subscriptions (user_id, tier, stripe_customer_id)
            VALUES ($1, 'free', $2)
            ON CONFLICT (user_id)
            DO UPDATE SET
                stripe_customer_id = EXCLUDED.stripe_customer_id,
                updated_at = NOW()
            """,
            user_id, customer.id,
        )
    return customer.id


async def _is_team_owner(pool: asyncpg.Pool, user_id: str) -> bool:
    """Return True if *user_id*'s own ``user_subscriptions.tier`` = 'team'."""
    async with pool.acquire() as conn:
        tier = await conn.fetchval(
            "SELECT tier FROM user_subscriptions WHERE user_id = $1",
            user_id,
        )
    return tier == "team"


async def _require_team_owner(
    pool: asyncpg.Pool, user_id: str
) -> None:
    """Raise 403 if the user doesn't own a team subscription."""
    if not await _is_team_owner(pool, user_id):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "team_owner_required",
                "message": "This endpoint is available only to Team-tier owners.",
            },
        )


# ---------------------------------------------------------------------------
# GET /api/billing/tier
# ---------------------------------------------------------------------------

@router.get("/tier")
async def get_tier(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Return the current user's effective tier + seat usage + period end."""
    user_id = _user_id(user)
    tier = await get_user_tier(pool, user_id)

    async with pool.acquire() as conn:
        sub = await conn.fetchrow(
            """
            SELECT tier, stripe_customer_id, stripe_subscription_id,
                   current_period_end, trial_ends_at, updated_at
              FROM user_subscriptions
             WHERE user_id = $1
            """,
            user_id,
        )

    is_owner = bool(sub and sub["tier"] == "team")
    seats = await seats_summary(pool, user_id, tier) if is_owner else {
        "used": 1,
        "total": TIER_METADATA.get(tier, {}).get("seat_count", 1),
        "unlimited": TIER_METADATA.get(tier, {}).get("seat_count") is None,
    }

    return {
        "tier": tier,
        "is_team_owner": is_owner,
        "seats": seats,
        "current_period_end": (
            sub["current_period_end"].isoformat()
            if sub and sub["current_period_end"] else None
        ),
        "trial_ends_at": (
            sub["trial_ends_at"].isoformat()
            if sub and sub["trial_ends_at"] else None
        ),
        "has_active_subscription": bool(
            sub and sub["stripe_subscription_id"]
        ),
        "stripe_configured": is_configured(),
        "catalog": public_catalog(),
    }


# ---------------------------------------------------------------------------
# POST /api/billing/checkout
# ---------------------------------------------------------------------------

@router.post("/checkout")
async def create_checkout_session(
    body: CheckoutBody,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Create a Stripe Checkout Session for the chosen tier.

    Returns ``{url, session_id}``. The frontend redirects to ``url``; Stripe
    bounces back to ``success_url`` / ``cancel_url`` once the user finishes.
    """
    price_id = PRICE_IDS.get(body.tier)
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "price_not_configured",
                "message": f"STRIPE_PRICE_{body.tier.upper()} is not set",
            },
        )

    user_id = _user_id(user)
    email = _user_email(user)

    try:
        customer_id = await _resolve_or_create_stripe_customer(pool, user_id, email)
        stripe = get_stripe()
        params: dict[str, Any] = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": body.success_url,
            "cancel_url": body.cancel_url,
            "client_reference_id": user_id,
            "metadata": {
                "princeps_user_id": user_id,
                "tier": body.tier,
            },
        }
        if body.trial_days:
            params["subscription_data"] = {
                "trial_period_days": body.trial_days,
            }
        session = stripe.checkout.Session.create(**params)
    except StripeNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail={"error": "stripe_not_configured", "message": str(exc)})
    except Exception as exc:
        log.exception("Stripe checkout creation failed for user=%s tier=%s", user_id, body.tier)
        raise HTTPException(
            status_code=502,
            detail={"error": "stripe_checkout_failed", "message": str(exc)[:300]},
        )

    return {"url": session.url, "session_id": session.id}


# ---------------------------------------------------------------------------
# POST /api/billing/portal
# ---------------------------------------------------------------------------

@router.post("/portal")
async def create_billing_portal(
    body: PortalBody,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Create a Stripe Billing Portal session (self-serve cancel / update card)."""
    user_id = _user_id(user)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT stripe_customer_id FROM user_subscriptions WHERE user_id = $1",
            user_id,
        )
    if not row or not row["stripe_customer_id"]:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "no_stripe_customer",
                "message": "No Stripe customer on file. Start a Checkout first.",
            },
        )

    try:
        stripe = get_stripe()
        session = stripe.billing_portal.Session.create(
            customer=row["stripe_customer_id"],
            return_url=body.return_url,
        )
    except StripeNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail={"error": "stripe_not_configured", "message": str(exc)})
    except Exception as exc:
        log.exception("Stripe portal creation failed for user=%s", user_id)
        raise HTTPException(
            status_code=502,
            detail={"error": "stripe_portal_failed", "message": str(exc)[:300]},
        )

    return {"url": session.url}


# ---------------------------------------------------------------------------
# POST /api/billing/webhook
# ---------------------------------------------------------------------------

def _ts_to_dt(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


async def _upsert_subscription(
    pool: asyncpg.Pool,
    *,
    user_id: str,
    tier: str,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    current_period_end: datetime | None = None,
    trial_ends_at: datetime | None = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_subscriptions
                (user_id, tier, stripe_customer_id, stripe_subscription_id,
                 current_period_end, trial_ends_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                tier                   = EXCLUDED.tier,
                stripe_customer_id     = COALESCE(EXCLUDED.stripe_customer_id,
                                                  user_subscriptions.stripe_customer_id),
                stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id,
                                                  user_subscriptions.stripe_subscription_id),
                current_period_end     = COALESCE(EXCLUDED.current_period_end,
                                                  user_subscriptions.current_period_end),
                trial_ends_at          = COALESCE(EXCLUDED.trial_ends_at,
                                                  user_subscriptions.trial_ends_at),
                updated_at             = NOW()
            """,
            user_id, tier, stripe_customer_id, stripe_subscription_id,
            current_period_end, trial_ends_at,
        )


async def _user_id_for_customer(pool: asyncpg.Pool, customer_id: str) -> str | None:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT user_id FROM user_subscriptions WHERE stripe_customer_id = $1",
            customer_id,
        )


async def _handle_checkout_completed(
    pool: asyncpg.Pool, event_obj: dict
) -> None:
    """checkout.session.completed — upsert user_subscriptions row."""
    user_id = (
        event_obj.get("client_reference_id")
        or (event_obj.get("metadata") or {}).get("princeps_user_id")
    )
    if not user_id:
        log.warning("checkout.session.completed missing princeps_user_id: %s",
                    event_obj.get("id"))
        return

    tier = (event_obj.get("metadata") or {}).get("tier") or "individual"
    customer_id = event_obj.get("customer")
    subscription_id = event_obj.get("subscription")

    # Pull the subscription to get period end + trial end.
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    if subscription_id:
        try:
            stripe = get_stripe()
            sub = stripe.Subscription.retrieve(subscription_id)
            current_period_end = _ts_to_dt(getattr(sub, "current_period_end", None))
            trial_ends_at = _ts_to_dt(getattr(sub, "trial_end", None))
            # If the actual price differs from metadata.tier, trust the price.
            items = (sub.get("items") or {}).get("data") or []
            if items:
                price_id = (items[0].get("price") or {}).get("id")
                resolved = tier_from_price_id(price_id)
                if resolved:
                    tier = resolved
        except Exception as exc:
            log.warning("Subscription retrieve failed for %s: %s", subscription_id, exc)

    await _upsert_subscription(
        pool,
        user_id=str(user_id),
        tier=tier,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        current_period_end=current_period_end,
        trial_ends_at=trial_ends_at,
    )
    log.info("checkout.session.completed: user=%s tier=%s", user_id, tier)


async def _handle_subscription_updated(
    pool: asyncpg.Pool, sub_obj: dict
) -> None:
    """customer.subscription.updated — refresh period end + tier on plan change."""
    customer_id = sub_obj.get("customer")
    if not customer_id:
        return
    user_id = await _user_id_for_customer(pool, customer_id)
    if not user_id:
        log.info("subscription.updated for unknown customer=%s", customer_id)
        return

    items = (sub_obj.get("items") or {}).get("data") or []
    tier = "individual"
    if items:
        price_id = (items[0].get("price") or {}).get("id")
        resolved = tier_from_price_id(price_id)
        if resolved:
            tier = resolved

    current_period_end = _ts_to_dt(sub_obj.get("current_period_end"))
    trial_ends_at = _ts_to_dt(sub_obj.get("trial_end"))

    await _upsert_subscription(
        pool,
        user_id=user_id,
        tier=tier,
        stripe_subscription_id=sub_obj.get("id"),
        current_period_end=current_period_end,
        trial_ends_at=trial_ends_at,
    )
    log.info("subscription.updated: user=%s tier=%s", user_id, tier)


async def _handle_subscription_deleted(
    pool: asyncpg.Pool, sub_obj: dict
) -> None:
    """customer.subscription.deleted — downgrade to free tier."""
    customer_id = sub_obj.get("customer")
    if not customer_id:
        return
    user_id = await _user_id_for_customer(pool, customer_id)
    if not user_id:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE user_subscriptions
               SET tier = 'free',
                   stripe_subscription_id = NULL,
                   current_period_end = NULL,
                   trial_ends_at = NULL,
                   updated_at = NOW()
             WHERE user_id = $1
            """,
            user_id,
        )
    log.info("subscription.deleted: user=%s downgraded to free", user_id)


async def _handle_payment_failed(
    pool: asyncpg.Pool, invoice_obj: dict
) -> None:
    """invoice.payment_failed — log + optional dunning email."""
    customer_id = invoice_obj.get("customer")
    if not customer_id:
        return
    user_id = await _user_id_for_customer(pool, customer_id)
    amount_due = invoice_obj.get("amount_due")
    log.warning(
        "invoice.payment_failed: user=%s customer=%s amount_due=%s",
        user_id, customer_id, amount_due,
    )
    if not user_id:
        return

    # Best-effort dunning email — send_email is designed for digest payloads so
    # we adapt the shape. Import lazily so test envs without SMTP don't blow up.
    try:
        from app.alerts.delivery import send_email  # type: ignore
        fake_alert = {"title": "Princeps payment failed", "slug": "billing-dunning", "cluster": "Billing"}
        fake_digest = {
            "llm_extract": (
                "Hi — your most recent Princeps payment didn't go through.\n"
                "Please update your card via the Billing Portal to keep "
                "your plan active. If you need help, reply to this email."
            ),
            "document_ids": [],
        }
        await send_email(pool, user_id, fake_alert, fake_digest)
    except Exception as exc:
        log.info("dunning email skipped for user=%s: %s", user_id, exc)


_EVENT_HANDLERS = {
    "checkout.session.completed":      _handle_checkout_completed,
    "customer.subscription.updated":   _handle_subscription_updated,
    "customer.subscription.deleted":   _handle_subscription_deleted,
    "invoice.payment_failed":          _handle_payment_failed,
}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Stripe-signed webhook. Verifies signature then dispatches known events.

    Returns 200 quickly; heavier work runs via ``BackgroundTasks`` so Stripe
    doesn't retry a slow DB write.
    """
    try:
        stripe = get_stripe()
        secret = get_webhook_secret()
    except StripeNotConfiguredError as exc:
        log.error("stripe webhook received but not configured: %s", exc)
        raise HTTPException(status_code=503, detail={"error": "stripe_not_configured"})

    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=raw_body,
            sig_header=sig_header,
            secret=secret,
        )
    except ValueError:
        # Invalid payload
        raise HTTPException(status_code=400, detail={"error": "invalid_payload"})
    except Exception:
        # stripe.error.SignatureVerificationError or anything else
        raise HTTPException(status_code=400, detail={"error": "invalid_signature"})

    event_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    event_obj = (event.get("data") or {}).get("object") if isinstance(event, dict) else event["data"]["object"]
    event_id = event.get("id") if isinstance(event, dict) else getattr(event, "id", None)

    handler = _EVENT_HANDLERS.get(event_type)
    if handler is None:
        log.info("stripe webhook unhandled event=%s id=%s", event_type, event_id)
        return JSONResponse({"received": True, "handled": False, "event": event_type})

    # Run the handler as a background task so we return to Stripe fast.
    background_tasks.add_task(handler, pool, dict(event_obj))
    return JSONResponse({"received": True, "handled": True, "event": event_type, "id": event_id})


# ---------------------------------------------------------------------------
# Team seats
# ---------------------------------------------------------------------------

@router.get("/team/seats")
async def list_team_seats(
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """List active members + pending invites. Team owners only."""
    user_id = _user_id(user)
    await ensure_team_schema(pool)
    await _require_team_owner(pool, user_id)

    members = await list_members(pool, user_id)
    invites = await list_pending_invites(pool, user_id)
    summary = await seats_summary(pool, user_id, "team")

    return {"members": members, "invites": invites, "seats": summary}


@router.post("/team/invite")
async def invite_member(
    body: InviteBody,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Invite a user by email to the team. Team owners only."""
    user_id = _user_id(user)
    await ensure_team_schema(pool)
    await _require_team_owner(pool, user_id)

    if not await can_add_seat(pool, user_id, "team"):
        cap = TIER_METADATA["team"]["seat_count"]
        raise HTTPException(
            status_code=402,
            detail={
                "error": "seats_full",
                "message": f"Team plan is capped at {cap} seats. Upgrade to Enterprise for unlimited seats.",
                "upgrade_tier": "enterprise",
                "cap": cap,
            },
        )

    invite = await create_invite(pool, user_id, str(body.email))
    return {"invite": invite}


@router.post("/team/invite/{token}/accept")
async def accept_team_invite(
    token: str,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Accept a pending team invite.

    The accepting user's effective tier becomes ``team`` via
    ``user_tiers.get_user_tier`` (which consults ``team_memberships``).
    """
    user_id = _user_id(user)
    await ensure_team_schema(pool)

    try:
        membership = await accept_invite(pool, token, user_id)
    except ValueError as exc:
        code = str(exc)
        status = 410 if code == "invite_expired" else (409 if code == "invite_already_accepted" else 404)
        raise HTTPException(status_code=status, detail={"error": code})

    # Verify the owner still has Team seats available — if they've since downgraded,
    # we accept the membership but surface a warning in the payload.
    owner_id = membership["owner_user_id"]
    summary = await seats_summary(pool, owner_id, "team")
    over_cap = (
        summary["total"] is not None
        and summary["used"] > summary["total"]
    )

    return {
        "membership": membership,
        "tier": "team",
        "over_cap_warning": over_cap,
    }


@router.delete("/team/members/{member_user_id}")
async def remove_team_member(
    member_user_id: str,
    user: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Remove *member_user_id* from the owner's team. Team owners only."""
    user_id = _user_id(user)
    await ensure_team_schema(pool)
    await _require_team_owner(pool, user_id)

    removed = await remove_member(pool, user_id, member_user_id)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail={"error": "member_not_found", "member_user_id": member_user_id},
        )
    return {"deleted": True, "member_user_id": member_user_id}


# ---------------------------------------------------------------------------
# TODOs — follow-ups beyond MVP scope
# ---------------------------------------------------------------------------
# 1. Add a ``stripe_events`` ledger table keyed on event_id for stronger
#    idempotency (Stripe does retry with the same id on 5xx).
# 2. Enterprise tier: custom pricing — treat POST /checkout with tier=enterprise
#    as a sales lead (email sales@princeps.energy) rather than a Stripe session.
# 3. Seat re-sync: when an owner downgrades Team → Individual, auto-expire
#    team_memberships and email the affected members.
# 4. SCIM / SSO provisioning — lives on the Enterprise tier roadmap.

"""
app/billing/price_catalog.py — tier → Stripe price-id mapping + UX metadata.

Two things live here:

* ``PRICE_IDS``: maps tier slug (``individual`` / ``team`` / ``enterprise``) to
  the Stripe ``price_*`` id from env vars. These power the
  ``POST /api/billing/checkout`` endpoint.

* ``TIER_METADATA``: human-readable name, feature bullets, seat count, perks.
  Consumed by the frontend paywall modal (``PaywallModal.jsx``) via
  ``GET /api/billing/tier``.

Amounts below are the list prices at launch (Apr 2026):

    individual  £79/mo
    team       £299/mo   (5 seats, API, Slack)
    enterprise £1500/mo  (unlimited seats, SSO, audit log, white-label)
"""

from __future__ import annotations

import os
from typing import Any, Literal

TierSlug = Literal["individual", "team", "enterprise"]


PRICE_IDS: dict[TierSlug, str | None] = {
    "individual": os.environ.get("STRIPE_PRICE_INDIVIDUAL"),
    "team":       os.environ.get("STRIPE_PRICE_TEAM"),
    "enterprise": os.environ.get("STRIPE_PRICE_ENTERPRISE"),
}


TIER_METADATA: dict[str, dict[str, Any]] = {
    "free": {
        "name": "Free",
        "price_gbp_monthly": 0,
        "seat_count": 1,
        "features": [
            "Up to 5 alert subscriptions",
            "Daily + weekly digests",
            "Single project workspace",
            "Community support",
        ],
        "perks": [],
        "cta": "Current plan",
    },
    "individual": {
        "name": "Individual",
        "price_gbp_monthly": 79,
        "stripe_price_env": "STRIPE_PRICE_INDIVIDUAL",
        "seat_count": 1,
        "features": [
            "Unlimited alert subscriptions",
            "All 82 alerts in the library",
            "Saved searches + pinned evidence",
            "Email + in-app delivery",
        ],
        "perks": [
            "Priority digest refresh",
            "Export to CSV / PDF",
        ],
        "cta": "Upgrade to Individual",
    },
    "team": {
        "name": "Team",
        "price_gbp_monthly": 299,
        "stripe_price_env": "STRIPE_PRICE_TEAM",
        "seat_count": 5,
        "features": [
            "Everything in Individual",
            "5 seats included",
            "Slack digest integration",
            "API access (rate-limited)",
            "Shared project workspaces",
        ],
        "perks": [
            "Team invites + role management",
            "Per-seat audit trail",
            "Slack webhooks for every alert",
        ],
        "cta": "Upgrade to Team",
    },
    "enterprise": {
        "name": "Enterprise",
        "price_gbp_monthly": 1500,
        "stripe_price_env": "STRIPE_PRICE_ENTERPRISE",
        "seat_count": None,        # unlimited
        "features": [
            "Everything in Team",
            "Unlimited seats",
            "SSO (SAML / OIDC)",
            "Audit log + retention policy",
            "White-label reports + custom domain",
        ],
        "perks": [
            "Dedicated success engineer",
            "Custom SLAs + uptime guarantees",
            "On-prem / VPC deployment option",
        ],
        "cta": "Contact sales",
    },
}


def tier_from_price_id(price_id: str | None) -> TierSlug | None:
    """Reverse-lookup: Stripe ``price_id`` → tier slug.

    Used in the ``customer.subscription.updated`` webhook handler to detect
    when a user switches plans. Returns ``None`` if the price_id isn't in our
    catalog (e.g. legacy / deleted prices).
    """
    if not price_id:
        return None
    for tier, pid in PRICE_IDS.items():
        if pid and pid == price_id:
            return tier
    return None


def public_catalog() -> dict[str, Any]:
    """Shape consumed by the frontend paywall modal.

    We expose everything except the raw Stripe price-ids — those go via
    ``POST /api/billing/checkout``, not plain reads.
    """
    return {
        tier: {k: v for k, v in meta.items() if k != "stripe_price_env"}
        for tier, meta in TIER_METADATA.items()
    }


def seat_count_for_tier(tier: str) -> int | None:
    """Return the seat allowance for *tier*. ``None`` = unlimited."""
    meta = TIER_METADATA.get(tier)
    if not meta:
        return 1
    return meta.get("seat_count")


__all__ = [
    "PRICE_IDS",
    "TIER_METADATA",
    "TierSlug",
    "tier_from_price_id",
    "public_catalog",
    "seat_count_for_tier",
]

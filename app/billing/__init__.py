"""
app/billing/ — Princeps Stripe billing (Task #11).

Wires the paywall enforced by ``app/routers/alerts.py``: when a free-tier user
hits the 5-alert cap the frontend shows an upgrade modal, and the endpoints in
``app/routers/billing.py`` run a Stripe Checkout Session to upgrade them.

Public surface
--------------
* ``stripe_client.get_stripe()``   — thin ``stripe`` module wrapper.
* ``price_catalog.PRICE_IDS``      — tier → env-backed price id.
* ``price_catalog.TIER_METADATA``  — human names, perks, seat counts.
* ``team_seats``                   — seat helpers for the team tier.
* ``seats_check``                  — ``can_add_seat`` / ``current_seats_used``.

Stripe integration lives here, not in the alerts router.
"""

from __future__ import annotations

from app.billing.price_catalog import PRICE_IDS, TIER_METADATA, tier_from_price_id
from app.billing.spend_cap import (
    SpendCap,
    SpendCapExceeded,
    check_and_consume,
    get_cap,
)

__all__ = [
    "PRICE_IDS",
    "TIER_METADATA",
    "tier_from_price_id",
    "SpendCap",
    "SpendCapExceeded",
    "check_and_consume",
    "get_cap",
]

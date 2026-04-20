"""
app/billing/stripe_client.py — thin wrapper over the ``stripe`` Python SDK.

The SDK is configured once at import time; the module itself is the client (the
SDK exposes top-level functions like ``stripe.checkout.Session.create``). We
return the imported module so callers can do::

    from app.billing.stripe_client import get_stripe
    stripe = get_stripe()
    stripe.checkout.Session.create(...)

Env vars
--------
* ``STRIPE_SECRET_KEY``     — required. ``sk_live_*`` in prod, ``sk_test_*`` in dev.
* ``STRIPE_WEBHOOK_SECRET`` — required for the ``/api/billing/webhook`` handler.
* ``STRIPE_API_VERSION``    — optional; default ``None`` (pin to the SDK's default).

If ``STRIPE_SECRET_KEY`` is unset we fail loudly with a clear message so dev
knows which variables to set, rather than silently returning 500s later.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

log = logging.getLogger("princeps.billing.stripe")

if TYPE_CHECKING:  # pragma: no cover
    import stripe as _stripe_type


_STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
_STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
_STRIPE_API_VERSION = os.environ.get("STRIPE_API_VERSION")


class StripeNotConfiguredError(RuntimeError):
    """Raised when a Stripe call is attempted with no API key configured."""


def get_stripe() -> Any:
    """Return the configured ``stripe`` SDK module.

    Raises ``StripeNotConfiguredError`` with a clear hint if either
    ``STRIPE_SECRET_KEY`` is missing or the SDK isn't installed.
    """
    if not _STRIPE_SECRET_KEY:
        raise StripeNotConfiguredError(
            "STRIPE_SECRET_KEY is not set. "
            "Set it in your environment (use a sk_test_* key for local dev) "
            "and also set STRIPE_WEBHOOK_SECRET for the /api/billing/webhook endpoint."
        )
    try:
        import stripe  # type: ignore
    except ImportError as exc:  # pragma: no cover — environmental
        raise StripeNotConfiguredError(
            "The 'stripe' package is not installed. "
            "Run: pip install 'stripe>=8.0'  (or add it to requirements.txt)."
        ) from exc

    stripe.api_key = _STRIPE_SECRET_KEY
    if _STRIPE_API_VERSION:
        stripe.api_version = _STRIPE_API_VERSION
    return stripe


def get_webhook_secret() -> str:
    """Return the configured Stripe webhook signing secret.

    Raises ``StripeNotConfiguredError`` if unset — the webhook endpoint must
    never run without signature verification.
    """
    if not _STRIPE_WEBHOOK_SECRET:
        raise StripeNotConfiguredError(
            "STRIPE_WEBHOOK_SECRET is not set. "
            "Copy it from the Stripe Dashboard (Developers → Webhooks → your endpoint → "
            "'Signing secret') and export it before starting the API."
        )
    return _STRIPE_WEBHOOK_SECRET


def is_configured() -> bool:
    """Return True if both the secret key and webhook secret are present.

    Cheap check used by ``/api/billing/tier`` to decide whether to advertise
    the checkout flow. Never raises.
    """
    return bool(_STRIPE_SECRET_KEY and _STRIPE_WEBHOOK_SECRET)


__all__ = [
    "StripeNotConfiguredError",
    "get_stripe",
    "get_webhook_secret",
    "is_configured",
]

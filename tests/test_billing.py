"""
Integration + unit tests for the Princeps billing router (Task #11).

Mirrors the mocked-asyncpg style used in ``tests/test_alerts.py`` so these tests
run without a live Postgres or a real Stripe account. All Stripe SDK calls are
patched via ``unittest.mock.patch``.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/feasibly_test")
os.environ.setdefault("CLAUDE_API_KEY", "sk-test-fake-key-for-smoke-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("PRINCEPS_DEMO_MODE", "true")
os.environ.setdefault("PRINCEPS_SEED_ALERTS", "false")

# Stripe env — populated before import so price_catalog picks them up.
os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake_abc123"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_fake_test_secret"
os.environ["STRIPE_PRICE_INDIVIDUAL"] = "price_individual_test"
os.environ["STRIPE_PRICE_TEAM"] = "price_team_test"
os.environ["STRIPE_PRICE_ENTERPRISE"] = "price_enterprise_test"


# ---------------------------------------------------------------------------
# Mock pool + connection (same shape as tests/test_alerts.py)
# ---------------------------------------------------------------------------

class ScriptedConn:
    def __init__(self):
        self.fetch_queue: list = []
        self.fetchrow_queue: list = []
        self.fetchval_queue: list = []
        self.execute_log: list = []
        self.execute_return: str = "INSERT 0 1"

    async def fetch(self, *_a, **_kw):
        if not self.fetch_queue:
            return []
        v = self.fetch_queue.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    async def fetchrow(self, *_a, **_kw):
        if not self.fetchrow_queue:
            return None
        v = self.fetchrow_queue.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    async def fetchval(self, *_a, **_kw):
        if not self.fetchval_queue:
            return 0
        v = self.fetchval_queue.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    async def execute(self, sql, *_a, **_kw):
        self.execute_log.append(sql)
        return self.execute_return

    # A minimal transaction ctx for the accept_invite path.
    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self_inner):
                return conn
            async def __aexit__(self_inner, *exc):
                return False

        return _Tx()


def make_pool(conn: ScriptedConn):
    pool = MagicMock()
    pool.get_size.return_value = 5
    pool.get_idle_size.return_value = 3
    pool.get_min_size.return_value = 3
    pool.get_max_size.return_value = 15

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool


@pytest.fixture(scope="module")
def app_instance():
    from app import main as app_module
    return app_module.app


@pytest.fixture
def client_factory(app_instance):
    from fastapi.testclient import TestClient

    def _build(conn: ScriptedConn):
        pool = make_pool(conn)
        app_instance.state.pool = pool
        app_instance.state.claude = MagicMock()
        app_instance.state._start_time = 0
        return TestClient(app_instance, raise_server_exceptions=False)

    return _build


# ---------------------------------------------------------------------------
# Price catalog unit tests
# ---------------------------------------------------------------------------

class TestPriceCatalog:
    def test_tier_metadata_has_all_tiers(self):
        from app.billing.price_catalog import TIER_METADATA
        assert set(TIER_METADATA.keys()) >= {"free", "individual", "team", "enterprise"}
        assert TIER_METADATA["team"]["seat_count"] == 5
        assert TIER_METADATA["enterprise"]["seat_count"] is None
        assert TIER_METADATA["individual"]["price_gbp_monthly"] == 79
        assert TIER_METADATA["team"]["price_gbp_monthly"] == 299
        assert TIER_METADATA["enterprise"]["price_gbp_monthly"] == 1500

    def test_reverse_lookup_price_to_tier(self):
        from app.billing.price_catalog import tier_from_price_id
        assert tier_from_price_id("price_individual_test") == "individual"
        assert tier_from_price_id("price_team_test") == "team"
        assert tier_from_price_id("price_enterprise_test") == "enterprise"
        assert tier_from_price_id("price_unknown") is None
        assert tier_from_price_id(None) is None


# ---------------------------------------------------------------------------
# GET /api/billing/tier
# ---------------------------------------------------------------------------

class TestGetTier:
    def test_free_user_has_no_period_end(self, client_factory):
        conn = ScriptedConn()
        # get_user_tier: (1) own sub row → None  (2) team_memberships probe → None
        conn.fetchrow_queue.append(None)
        conn.fetchrow_queue.append(None)
        # tier endpoint's own sub lookup
        conn.fetchrow_queue.append(None)

        client = client_factory(conn)
        resp = client.get("/api/billing/tier")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tier"] == "free"
        assert body["is_team_owner"] is False
        assert body["current_period_end"] is None
        assert body["has_active_subscription"] is False
        assert "catalog" in body

    def test_team_owner_returns_seat_summary(self, client_factory):
        conn = ScriptedConn()
        # get_user_tier → team
        conn.fetchrow_queue.append({"tier": "team"})
        # tier endpoint's own sub lookup
        now = datetime.now(timezone.utc)
        conn.fetchrow_queue.append({
            "tier": "team",
            "stripe_customer_id": "cus_test",
            "stripe_subscription_id": "sub_test",
            "current_period_end": now + timedelta(days=30),
            "trial_ends_at": None,
            "updated_at": now,
        })
        # current_seats_used → 3 accepted members + owner
        conn.fetchval_queue.append(2)

        client = client_factory(conn)
        resp = client.get("/api/billing/tier")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tier"] == "team"
        assert body["is_team_owner"] is True
        assert body["seats"]["used"] == 3
        assert body["seats"]["total"] == 5
        assert body["seats"]["unlimited"] is False


# ---------------------------------------------------------------------------
# POST /api/billing/checkout
# ---------------------------------------------------------------------------

class TestCheckout:
    def test_checkout_creates_session_idempotent_customer(self, client_factory):
        conn = ScriptedConn()
        # _resolve_or_create_stripe_customer → existing
        conn.fetchrow_queue.append({"stripe_customer_id": "cus_existing"})

        fake_session = MagicMock()
        fake_session.url = "https://checkout.stripe.com/test"
        fake_session.id = "cs_test_123"

        fake_stripe = MagicMock()
        fake_stripe.checkout.Session.create.return_value = fake_session

        with patch("app.routers.billing.get_stripe", return_value=fake_stripe):
            client = client_factory(conn)
            resp = client.post(
                "/api/billing/checkout",
                json={
                    "tier": "individual",
                    "success_url": "https://princeps.energy/ok",
                    "cancel_url": "https://princeps.energy/cancel",
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["url"] == "https://checkout.stripe.com/test"
        assert body["session_id"] == "cs_test_123"

        # Assert Stripe was called with the right price id and the existing customer.
        kwargs = fake_stripe.checkout.Session.create.call_args.kwargs
        assert kwargs["customer"] == "cus_existing"
        assert kwargs["line_items"][0]["price"] == "price_individual_test"
        assert kwargs["mode"] == "subscription"

    def test_checkout_creates_customer_when_missing(self, client_factory):
        conn = ScriptedConn()
        # _resolve_or_create_stripe_customer → no row
        conn.fetchrow_queue.append(None)

        fake_customer = MagicMock()
        fake_customer.id = "cus_new"
        fake_session = MagicMock()
        fake_session.url = "https://checkout.stripe.com/new"
        fake_session.id = "cs_test_new"

        fake_stripe = MagicMock()
        fake_stripe.Customer.create.return_value = fake_customer
        fake_stripe.checkout.Session.create.return_value = fake_session

        with patch("app.routers.billing.get_stripe", return_value=fake_stripe):
            client = client_factory(conn)
            resp = client.post(
                "/api/billing/checkout",
                json={
                    "tier": "team",
                    "success_url": "https://princeps.energy/ok",
                    "cancel_url": "https://princeps.energy/cancel",
                },
            )
        assert resp.status_code == 200, resp.text
        assert fake_stripe.Customer.create.called

    def test_checkout_bad_tier_rejected(self, client_factory):
        conn = ScriptedConn()
        client = client_factory(conn)
        resp = client.post(
            "/api/billing/checkout",
            json={"tier": "gold", "success_url": "x", "cancel_url": "y"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/billing/webhook
# ---------------------------------------------------------------------------

class TestWebhookSignature:
    def test_bad_signature_returns_400(self, client_factory):
        conn = ScriptedConn()

        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.side_effect = Exception("bad sig")

        with patch("app.routers.billing.get_stripe", return_value=fake_stripe), \
             patch("app.routers.billing.get_webhook_secret", return_value="whsec_x"):
            client = client_factory(conn)
            resp = client.post(
                "/api/billing/webhook",
                content=b'{"id": "evt_x"}',
                headers={"stripe-signature": "bad"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "invalid_signature"

    def test_invalid_payload_returns_400(self, client_factory):
        conn = ScriptedConn()

        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.side_effect = ValueError("bad json")

        with patch("app.routers.billing.get_stripe", return_value=fake_stripe), \
             patch("app.routers.billing.get_webhook_secret", return_value="whsec_x"):
            client = client_factory(conn)
            resp = client.post(
                "/api/billing/webhook",
                content=b"not-json",
                headers={"stripe-signature": "t=1,v1=x"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "invalid_payload"


class TestWebhookCheckoutCompleted:
    def test_upserts_subscription_on_completed(self, client_factory):
        """
        checkout.session.completed with a subscription id should upsert
        user_subscriptions with tier=individual and the customer id.
        """
        conn = ScriptedConn()

        event_obj = {
            "id": "cs_test_1",
            "client_reference_id": "u1",
            "customer": "cus_u1",
            "subscription": "sub_u1",
            "metadata": {"princeps_user_id": "u1", "tier": "individual"},
        }
        event_envelope = {
            "id": "evt_checkout",
            "type": "checkout.session.completed",
            "data": {"object": event_obj},
        }

        # Fake Stripe: construct_event returns the envelope; Subscription.retrieve
        # returns a minimal sub with current_period_end.
        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.return_value = event_envelope

        now_ts = int(datetime.now(timezone.utc).timestamp())
        fake_sub = MagicMock()
        fake_sub.current_period_end = now_ts + 30 * 86400
        fake_sub.trial_end = None
        fake_sub.get = lambda k, default=None: {
            "items": {"data": [{"price": {"id": "price_individual_test"}}]},
        }.get(k, default)
        fake_stripe.Subscription.retrieve.return_value = fake_sub

        with patch("app.routers.billing.get_stripe", return_value=fake_stripe), \
             patch("app.routers.billing.get_webhook_secret", return_value="whsec_x"):
            client = client_factory(conn)
            resp = client.post(
                "/api/billing/webhook",
                content=json.dumps(event_envelope).encode(),
                headers={"stripe-signature": "t=1,v1=x"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["received"] is True
        assert body["handled"] is True
        assert body["event"] == "checkout.session.completed"

        # The BackgroundTasks runner under TestClient runs synchronously, so by the
        # time we get here the INSERT should have fired.
        inserts = [sql for sql in conn.execute_log if "INSERT INTO user_subscriptions" in sql]
        assert inserts, f"expected upsert; got: {conn.execute_log}"


class TestWebhookSubscriptionDeleted:
    def test_deleted_downgrades_to_free(self, client_factory):
        conn = ScriptedConn()
        # user_id_for_customer → u2
        conn.fetchval_queue.append("u2")

        event_obj = {
            "id": "sub_u2",
            "customer": "cus_u2",
        }
        event_envelope = {
            "id": "evt_sub_del",
            "type": "customer.subscription.deleted",
            "data": {"object": event_obj},
        }

        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.return_value = event_envelope

        with patch("app.routers.billing.get_stripe", return_value=fake_stripe), \
             patch("app.routers.billing.get_webhook_secret", return_value="whsec_x"):
            client = client_factory(conn)
            resp = client.post(
                "/api/billing/webhook",
                content=json.dumps(event_envelope).encode(),
                headers={"stripe-signature": "t=1,v1=x"},
            )
        assert resp.status_code == 200

        downgrades = [
            sql for sql in conn.execute_log
            if "UPDATE user_subscriptions" in sql and "tier = 'free'" in sql
        ]
        assert downgrades, f"expected downgrade; got: {conn.execute_log}"


class TestWebhookUnknownEvent:
    def test_unhandled_event_returns_ok(self, client_factory):
        conn = ScriptedConn()

        event_envelope = {
            "id": "evt_x",
            "type": "payment_method.attached",
            "data": {"object": {}},
        }

        fake_stripe = MagicMock()
        fake_stripe.Webhook.construct_event.return_value = event_envelope

        with patch("app.routers.billing.get_stripe", return_value=fake_stripe), \
             patch("app.routers.billing.get_webhook_secret", return_value="whsec_x"):
            client = client_factory(conn)
            resp = client.post(
                "/api/billing/webhook",
                content=json.dumps(event_envelope).encode(),
                headers={"stripe-signature": "t=1,v1=x"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["handled"] is False


# ---------------------------------------------------------------------------
# Team invites + accept + seat limit
# ---------------------------------------------------------------------------

class TestTeamInvite:
    def test_invite_requires_team_owner(self, client_factory):
        conn = ScriptedConn()
        # ensure_schema: present check
        conn.fetchval_queue.append(True)
        # _is_team_owner → tier='individual'
        conn.fetchval_queue.append("individual")

        client = client_factory(conn)
        resp = client.post("/api/billing/team/invite", json={"email": "new@example.com"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "team_owner_required"

    def test_invite_blocks_at_seat_cap(self, client_factory):
        conn = ScriptedConn()
        # ensure_schema: present
        conn.fetchval_queue.append(True)
        # _is_team_owner → 'team'
        conn.fetchval_queue.append("team")
        # current_seats_used → 4 accepted members → 5 seats used (cap)
        conn.fetchval_queue.append(4)

        client = client_factory(conn)
        resp = client.post("/api/billing/team/invite", json={"email": "six@example.com"})
        assert resp.status_code == 402, resp.text
        body = resp.json()
        assert body["detail"]["error"] == "seats_full"
        assert body["detail"]["upgrade_tier"] == "enterprise"
        assert body["detail"]["cap"] == 5

    def test_invite_happy_path(self, client_factory):
        conn = ScriptedConn()
        # ensure_schema: present
        conn.fetchval_queue.append(True)
        # _is_team_owner → 'team'
        conn.fetchval_queue.append("team")
        # current_seats_used → 0 accepted
        conn.fetchval_queue.append(0)
        # create_invite: existing-row check (none)
        conn.fetchrow_queue.append(None)
        # INSERT RETURNING
        now = datetime.now(timezone.utc)
        conn.fetchrow_queue.append({
            "id": "11111111-1111-1111-1111-111111111111",
            "token": "tok_abc",
            "expires_at": now + timedelta(days=14),
            "created_at": now,
        })

        client = client_factory(conn)
        resp = client.post(
            "/api/billing/team/invite",
            json={"email": "new@example.com"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["invite"]["token"] == "tok_abc"
        assert body["invite"]["invited_email"] == "new@example.com"


class TestTeamAccept:
    def test_accept_invite_happy(self, client_factory):
        conn = ScriptedConn()
        # ensure_schema: present
        conn.fetchval_queue.append(True)
        # invite lookup
        owner_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        conn.fetchrow_queue.append({
            "id": "11111111-1111-1111-1111-111111111111",
            "owner_user_id": owner_id,
            "invited_email": "m@example.com",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
            "accepted_at": None,
        })
        # membership upsert RETURNING
        now = datetime.now(timezone.utc)
        conn.fetchrow_queue.append({
            "id": "22222222-2222-2222-2222-222222222222",
            "owner_user_id": owner_id,
            "member_user_id": "00000000-0000-0000-0000-000000000000",
            "role": "member",
            "accepted_at": now,
        })
        # seats_summary's current_seats_used → 1 accepted → 2 used (fine, ≤ 5)
        conn.fetchval_queue.append(1)

        client = client_factory(conn)
        resp = client.post("/api/billing/team/invite/tok_abc/accept")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["tier"] == "team"
        assert body["membership"]["role"] == "member"
        assert body["over_cap_warning"] is False

    def test_accept_invite_expired(self, client_factory):
        conn = ScriptedConn()
        conn.fetchval_queue.append(True)
        conn.fetchrow_queue.append({
            "id": "11111111-1111-1111-1111-111111111111",
            "owner_user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "invited_email": "m@example.com",
            "expires_at": datetime.now(timezone.utc) - timedelta(days=1),
            "accepted_at": None,
        })
        client = client_factory(conn)
        resp = client.post("/api/billing/team/invite/tok_expired/accept")
        assert resp.status_code == 410
        assert resp.json()["detail"]["error"] == "invite_expired"

    def test_accept_invite_not_found(self, client_factory):
        conn = ScriptedConn()
        conn.fetchval_queue.append(True)
        conn.fetchrow_queue.append(None)
        client = client_factory(conn)
        resp = client.post("/api/billing/team/invite/missing/accept")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression: paywall 402 shape from alerts router is unchanged
# ---------------------------------------------------------------------------

class TestAlertCapPaywallShape:
    """Task #11 must not change the 402 shape the frontend already consumes."""

    def test_alerts_subscribe_cap_shape(self, client_factory):
        conn = ScriptedConn()
        # get_user_tier → free (no row, no team membership)
        conn.fetchrow_queue.append(None)
        # resolve_team_owner_tier → no match
        conn.fetchrow_queue.append(None)
        # _count_active_subs → at cap
        conn.fetchval_queue.append(5)

        client = client_factory(conn)
        resp = client.post(
            "/api/alerts/subscribe",
            json={"alert_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        )
        assert resp.status_code == 402
        body = resp.json()
        assert body["error"] == "ALERT_CAP"
        assert body["cap"] == 5
        # Must still advertise all three upgrade tiers at the right prices.
        tiers = {t["slug"]: t["gbp_monthly"] for t in body["upgrade_tiers"]}
        assert tiers == {"individual": 79, "team": 299, "enterprise": 1500}

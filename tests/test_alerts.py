"""
Integration tests for the Princeps Alerts router (Task #6).

Tests use the same mocked-asyncpg approach as ``tests/test_api_smoke.py`` so
they run without a live Postgres. Each test defines the minimal db-side
fixture its endpoint needs.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/feasibly_test")
os.environ.setdefault("CLAUDE_API_KEY", "sk-test-fake-key-for-smoke-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("PRINCEPS_DEMO_MODE", "true")
# Skip the alert seed on startup — we don't want to touch a real DB from tests.
os.environ.setdefault("PRINCEPS_SEED_ALERTS", "false")


# ---------------------------------------------------------------------------
# Helpers — a configurable mock pool where each test can script responses.
# ---------------------------------------------------------------------------

class ScriptedConn:
    """Pseudo-asyncpg connection with queues for fetch / fetchrow / fetchval."""

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
    """Return a builder: build_client(scripted_conn) -> TestClient."""
    from fastapi.testclient import TestClient

    def _build(conn: ScriptedConn):
        pool = make_pool(conn)
        app_instance.state.pool = pool
        app_instance.state.claude = MagicMock()
        app_instance.state._start_time = 0
        return TestClient(app_instance, raise_server_exceptions=False)

    return _build


# ---------------------------------------------------------------------------
# Tests — Library & subscribe
# ---------------------------------------------------------------------------

class TestLibrary:
    def test_library_returns_clusters(self, client_factory):
        conn = ScriptedConn()
        conn.fetch_queue.append([
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "slug": "ar7-cfd-notices",
                "title": "AR7 CfD notices",
                "description": "",
                "cluster": "Renewables & CfD",
                "source_filter": {},
                "cadence": "weekly_mon",
                "est_docs_per_digest": 5,
                "icp_tags": ["solar_dev"],
                "is_public": True,
                "created_by": None,
                "created_at": None,
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "slug": "tec-register-deltas",
                "title": "TEC Register deltas",
                "description": "",
                "cluster": "Grid connection & queue",
                "source_filter": {},
                "cadence": "weekly_fri",
                "est_docs_per_digest": 40,
                "icp_tags": ["solar_dev", "bess_dev"],
                "is_public": True,
                "created_by": None,
                "created_at": None,
            },
        ])
        conn.fetchval_queue.append(2)

        client = client_factory(conn)
        resp = client.get("/api/alerts/library")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        clusters = {c["cluster"] for c in data["clusters"]}
        assert "Renewables & CfD" in clusters
        assert "Grid connection & queue" in clusters


class TestSubscribeHappyPath:
    def test_subscribe_under_cap(self, client_factory):
        conn = ScriptedConn()
        # 1) get_user_tier: own sub row (None) + team_memberships probe (None)
        conn.fetchrow_queue.append(None)
        conn.fetchrow_queue.append(None)
        # 2) _count_active_subs → 2 (under 5-cap)
        conn.fetchval_queue.append(2)
        # 3) alert lookup inside subscribe
        conn.fetchrow_queue.append({
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "slug": "ar7-cfd-notices",
            "title": "AR7 CfD notices",
        })
        # 4) actual INSERT ... RETURNING
        conn.fetchrow_queue.append({
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "alert_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "delivery_channels": {"email": True, "in_app": True, "slack": False},
            "pinned_project_id": None,
            "muted": False,
            "created_at": None,
            "updated_at": None,
        })

        client = client_factory(conn)
        resp = client.post(
            "/api/alerts/subscribe",
            json={"alert_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["subscription"]["alert_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        assert body["alert"]["slug"] == "ar7-cfd-notices"

    def test_unsubscribe(self, client_factory):
        conn = ScriptedConn()
        conn.execute_return = "DELETE 1"
        client = client_factory(conn)
        resp = client.delete("/api/alerts/subscribe/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

    def test_unsubscribe_not_found(self, client_factory):
        conn = ScriptedConn()
        conn.execute_return = "DELETE 0"
        client = client_factory(conn)
        resp = client.delete("/api/alerts/subscribe/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        assert resp.status_code == 404


class TestCapEnforcement:
    def test_subscribe_blocked_at_cap(self, client_factory):
        conn = ScriptedConn()
        # get_user_tier: own sub row (None) + team_memberships probe (None)
        conn.fetchrow_queue.append(None)
        conn.fetchrow_queue.append(None)
        # _count_active_subs → 5 (at cap)
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
        tier_slugs = {t["slug"] for t in body["upgrade_tiers"]}
        assert tier_slugs == {"individual", "team", "enterprise"}

    def test_subscribe_allowed_when_paid(self, client_factory):
        conn = ScriptedConn()
        # get_user_tier → individual
        conn.fetchrow_queue.append({"tier": "individual"})
        # alert lookup
        conn.fetchrow_queue.append({
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "slug": "ar7-cfd-notices",
            "title": "AR7 CfD notices",
        })
        # insert return
        conn.fetchrow_queue.append({
            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "alert_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "delivery_channels": {"email": True, "in_app": True, "slack": False},
            "pinned_project_id": None,
            "muted": False,
            "created_at": None,
            "updated_at": None,
        })

        client = client_factory(conn)
        resp = client.post(
            "/api/alerts/subscribe",
            json={"alert_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        )
        assert resp.status_code == 200


class TestStarterPack:
    def test_pack_list(self, client_factory):
        conn = ScriptedConn()
        client = client_factory(conn)
        resp = client.get("/api/alerts/starter-packs")
        assert resp.status_code == 200
        slugs = {p["slug"] for p in resp.json()["packs"]}
        assert slugs == {"solar_dev", "bess_dev", "dc_dev", "grid_consultant", "land_agent"}

    def test_pack_subscribe_partial_free(self, client_factory):
        """Free tier + land_agent pack (8 alerts) → 5 subscribed, 3 remaining."""
        conn = ScriptedConn()

        # 1) get_user_tier: own sub row (None) + team_memberships probe (None)
        conn.fetchrow_queue.append(None)
        conn.fetchrow_queue.append(None)

        # 2) Resolve slug → id for the 8 slugs in land_agent pack
        land_agent_slugs = [
            "lpa-major-energy-10mw",
            "repd-new-entries",
            "nsip-dco-applications",
            "bng-nsip-filings",
            "roc-lifetime-end",
            "new-spv-incorporations",
            "director-watchlist",
            "dissolutions-project-spvs",
        ]
        conn.fetch_queue.append([
            {"id": f"{i:08d}-0000-0000-0000-000000000000", "slug": s}
            for i, s in enumerate(land_agent_slugs, start=1)
        ])

        # 3) _count_active_subs → 0
        conn.fetchval_queue.append(0)

        # 4) Insert rows for first 5 alerts (cap hit on the 6th). Each insert returns
        # a dict with id/alert_id/created_at/updated_at.
        for i in range(5):
            conn.fetchrow_queue.append({
                "id": f"a{i}aaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "alert_id": f"{i+1:08d}-0000-0000-0000-000000000000",
                "created_at": None,
                "updated_at": None,
            })

        client = client_factory(conn)
        resp = client.post("/api/alerts/starter-pack/land_agent/subscribe")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["subscribed"]) == 5
        assert len(body["pack_remaining"]) == 3
        assert body["tier"] == "free"
        assert body["cap"] == 5

    def test_pack_not_found(self, client_factory):
        conn = ScriptedConn()
        client = client_factory(conn)
        resp = client.post("/api/alerts/starter-pack/does_not_exist/subscribe")
        assert resp.status_code == 404


class TestDigestPagination:
    def test_digest_basic(self, client_factory):
        conn = ScriptedConn()
        import uuid
        from datetime import datetime, timezone
        rows = [
            {
                "id": uuid.uuid4(),
                "alert_id": uuid.uuid4(),
                "run_at": datetime.now(timezone.utc),
                "document_ids": [uuid.uuid4()],
                "llm_extract": "Summary",
                "llm_structured": {"document_count": 1},
                "sent_at": None,
                "alert_slug": "ar7-cfd-notices",
                "alert_title": "AR7 CfD notices",
                "alert_cluster": "Renewables & CfD",
            }
            for _ in range(3)
        ]
        # limit=2 → query asks for 3 (limit+1), so reply with up to 3 rows
        conn.fetch_queue.append(rows[:3])

        client = client_factory(conn)
        resp = client.get("/api/alerts/digest?limit=2")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["count"] == 2
        assert body["next_cursor"] is not None
        assert len(body["digests"]) == 2

    def test_digest_no_more(self, client_factory):
        conn = ScriptedConn()
        import uuid
        from datetime import datetime, timezone
        rows = [{
            "id": uuid.uuid4(),
            "alert_id": uuid.uuid4(),
            "run_at": datetime.now(timezone.utc),
            "document_ids": [],
            "llm_extract": "Summary",
            "llm_structured": {},
            "sent_at": None,
            "alert_slug": "ar7-cfd-notices",
            "alert_title": "AR7 CfD notices",
            "alert_cluster": "Renewables & CfD",
        }]
        conn.fetch_queue.append(rows)

        client = client_factory(conn)
        resp = client.get("/api/alerts/digest?limit=50")
        body = resp.json()
        assert body["count"] == 1
        assert body["next_cursor"] is None


# ---------------------------------------------------------------------------
# Unit-style sanity checks that don't need the full FastAPI app
# ---------------------------------------------------------------------------

class TestStarterPackCatalogueConsistency:
    def test_every_pack_slug_exists_in_catalogue(self):
        from app.alerts.starter_packs import validate_packs_against_catalogue
        missing = validate_packs_against_catalogue()
        assert missing == [], f"Starter packs reference slugs missing from catalogue: {missing}"

    def test_catalogue_count(self):
        from app.alerts.seed import catalogue
        assert len(catalogue()) == 82


class TestDigestSQLBuilder:
    def test_build_doc_query_basic(self):
        from datetime import datetime, timezone
        from app.alerts.digest_worker import _build_doc_query

        sql, params = _build_doc_query(
            {"source": "neso_tec", "topic_tags_any": ["tec_register"]},
            datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        assert "d.source = $" in sql
        assert "jsonb_array_elements_text" in sql
        # params: [since, source, topic_tags_list]
        assert len(params) == 3

    def test_build_doc_query_case_type_join(self):
        from datetime import datetime, timezone
        from app.alerts.digest_worker import _build_doc_query

        sql, _ = _build_doc_query(
            {"case_type_in": ["nsip_dco"]},
            datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        assert "LEFT JOIN dockets k" in sql
        assert "k.case_type = ANY" in sql

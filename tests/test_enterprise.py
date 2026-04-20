"""
tests/test_enterprise.py — Task #13 enterprise readiness tests.

Uses the same mocked-asyncpg pattern as ``tests/test_alerts.py`` so the
suite runs without a live Postgres. Covers:

* Trust Center endpoint shape (certifications / subprocessors / DPA /
  security-report).
* Encryption helpers (round-trip, key length validation).
* ACL dependency (403 on wrong tenant, pass-through on legacy NULL tenant).
* SSO callback JIT user creation (happy path).
* Audit-log entry capture (direct write, not middleware).
"""

from __future__ import annotations

import asyncio
import base64
import os
import pathlib
import secrets
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest


def _run(coro):
    """Run an async coroutine to completion — mirrors tests/test_dno_ingest.py."""
    return asyncio.run(coro)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/feasibly_test")
os.environ.setdefault("CLAUDE_API_KEY", "sk-test-fake-key-for-smoke-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("PRINCEPS_DEMO_MODE", "true")
os.environ.setdefault("PRINCEPS_SEED_ALERTS", "false")
os.environ.setdefault("PRINCEPS_SSO_ENABLED", "true")
# Deterministic 32-byte key so encryption round-trip is reproducible.
os.environ.setdefault(
    "PRINCEPS_ENCRYPTION_KEY",
    base64.b64encode(b"x" * 32).decode(),
)


# ---------------------------------------------------------------------------
# Helpers — a configurable mock pool where each test scripts responses.
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
            return None
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
    from fastapi.testclient import TestClient

    def _build(conn: ScriptedConn):
        pool = make_pool(conn)
        app_instance.state.pool = pool
        app_instance.state.claude = MagicMock()
        app_instance.state._start_time = 0
        return TestClient(app_instance, raise_server_exceptions=False)

    return _build


# ---------------------------------------------------------------------------
# Trust Center — shape tests
# ---------------------------------------------------------------------------

class TestTrustCenter:
    def test_certifications_shape(self, client_factory):
        client = client_factory(ScriptedConn())
        resp = client.get("/api/trust/certifications")
        assert resp.status_code == 200
        data = resp.json()
        assert "certifications" in data
        certs = data["certifications"]
        assert "iso_27001" in certs
        assert certs["iso_27001"]["status"] == "in_progress"
        assert certs["gdpr"]["status"] == "compliant"
        assert certs["soc_2"]["status"] == "planned"

    def test_subprocessors_shape(self, client_factory):
        client = client_factory(ScriptedConn())
        resp = client.get("/api/trust/subprocessors")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == len(data["subprocessors"])
        names = {s["name"] for s in data["subprocessors"]}
        # Sanity: the four MUST-haves for any enterprise procurement review.
        assert any("AWS" in n for n in names)
        assert "Anthropic" in names
        assert "Stripe" in names
        assert "Cloudflare" in names
        # Every row carries purpose + data_access + region.
        for s in data["subprocessors"]:
            assert {"name", "purpose", "data_access", "region"} <= set(s)

    def test_dpa_endpoint(self, client_factory):
        client = client_factory(ScriptedConn())
        resp = client.get("/api/trust/dpa")
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"].endswith(".pdf")
        assert data["version"]

    def test_security_report(self, client_factory):
        client = client_factory(ScriptedConn())
        resp = client.get("/api/trust/security-report")
        assert resp.status_code == 200
        report = resp.json()["security_report"]
        for section in ("access_controls", "encryption", "data_retention",
                        "incident_response", "availability", "employee_access"):
            assert section in report


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------

class TestEncryption:
    def test_roundtrip(self):
        from app.enterprise import encryption
        encryption.reset_cache_for_tests()
        ct = encryption.encrypt("super-secret-oidc-value")
        assert isinstance(ct, (bytes, bytearray))
        assert ct != b"super-secret-oidc-value"
        pt = encryption.decrypt(ct)
        assert pt == "super-secret-oidc-value"

    def test_bad_key_length_in_prod(self, monkeypatch):
        from app.enterprise import encryption
        monkeypatch.setenv("PRINCEPS_ENV", "production")
        monkeypatch.setenv(
            "PRINCEPS_ENCRYPTION_KEY",
            base64.b64encode(b"short").decode(),  # wrong length
        )
        encryption.reset_cache_for_tests()
        with pytest.raises(RuntimeError):
            encryption.encrypt("x")

    def test_missing_key_in_prod(self, monkeypatch):
        from app.enterprise import encryption
        monkeypatch.setenv("PRINCEPS_ENV", "production")
        monkeypatch.delenv("PRINCEPS_ENCRYPTION_KEY", raising=False)
        encryption.reset_cache_for_tests()
        with pytest.raises(RuntimeError):
            encryption.encrypt("x")

    def test_ciphertext_is_nondeterministic(self):
        from app.enterprise import encryption
        # Restore good key after prior test tweaked PRINCEPS_ENV.
        os.environ["PRINCEPS_ENCRYPTION_KEY"] = base64.b64encode(b"x" * 32).decode()
        os.environ.pop("PRINCEPS_ENV", None)
        encryption.reset_cache_for_tests()
        a = encryption.encrypt("same-plaintext")
        b = encryption.encrypt("same-plaintext")
        assert a != b  # nonce is random per call
        assert encryption.decrypt(a) == encryption.decrypt(b) == "same-plaintext"


# ---------------------------------------------------------------------------
# ACL dependency
# ---------------------------------------------------------------------------

class TestACL:
    def test_legacy_null_tenant_allowed(self, app_instance):
        """A resource with NULL tenant_id is legacy single-tenant and passes."""
        from fastapi import APIRouter, Depends
        from fastapi.testclient import TestClient
        from uuid import uuid4

        from app.enterprise.acl import require_tenant_access

        probe = APIRouter()

        @probe.get("/_test/project/{project_id}/probe")
        async def _probe(
            project_id: str,
            access = Depends(require_tenant_access(
                resource_type="project",
                resource_id_param="project_id",
                min_role="member",
            )),
        ):
            return {"ok": True, "access": access}

        app_instance.include_router(probe)

        conn = ScriptedConn()
        # tenant_for_resource -> None (legacy row).
        conn.fetchval_queue.append(None)

        app_instance.state.pool = make_pool(conn)
        app_instance.state.claude = MagicMock()
        app_instance.state._start_time = 0

        client = TestClient(app_instance, raise_server_exceptions=False)
        resp = client.get(f"/_test/project/{uuid4()}/probe")
        assert resp.status_code == 200
        assert resp.json()["access"]["role"] == "legacy"

    def test_403_when_not_member(self, app_instance):
        from fastapi import APIRouter, Depends
        from fastapi.testclient import TestClient
        from uuid import uuid4

        from app.enterprise.acl import require_tenant_access

        probe = APIRouter()

        @probe.get("/_test/project/{project_id}/guarded")
        async def _guarded(
            project_id: str,
            access = Depends(require_tenant_access(
                resource_type="project",
                resource_id_param="project_id",
                min_role="member",
            )),
        ):
            return {"ok": True}

        app_instance.include_router(probe)

        conn = ScriptedConn()
        tenant_uuid = str(uuid4())
        # tenant_for_resource -> tenant_uuid
        conn.fetchval_queue.append(tenant_uuid)
        # get_user_role -> None (caller is NOT a member)
        conn.fetchval_queue.append(None)

        app_instance.state.pool = make_pool(conn)
        client = TestClient(app_instance, raise_server_exceptions=False)
        resp = client.get(f"/_test/project/{uuid4()}/guarded")
        assert resp.status_code == 403

    def test_403_when_role_below_minimum(self, app_instance):
        from fastapi import APIRouter, Depends
        from fastapi.testclient import TestClient
        from uuid import uuid4

        from app.enterprise.acl import require_tenant_access

        probe = APIRouter()

        @probe.get("/_test/project/{project_id}/admin-only")
        async def _admin_only(
            project_id: str,
            access = Depends(require_tenant_access(
                resource_type="project",
                resource_id_param="project_id",
                min_role="admin",
            )),
        ):
            return {"ok": True}

        app_instance.include_router(probe)

        conn = ScriptedConn()
        tenant_uuid = str(uuid4())
        conn.fetchval_queue.append(tenant_uuid)   # tenant_for_resource
        conn.fetchval_queue.append("viewer")       # get_user_role: below admin

        app_instance.state.pool = make_pool(conn)
        client = TestClient(app_instance, raise_server_exceptions=False)
        resp = client.get(f"/_test/project/{uuid4()}/admin-only")
        assert resp.status_code == 403
        assert "Requires role" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Audit log — direct write (middleware path is integration-level)
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_write_entry_inserts(self):
        from app.enterprise import audit_log as al

        conn = ScriptedConn()
        pool = make_pool(conn)

        _run(al.write_entry(
            pool,
            action="GET /api/test",
            http_method="GET",
            http_path="/api/test",
            response_status=200,
            payload_hash="deadbeef",
            user_id=None,
            tenant_id=None,
        ))
        # One INSERT should have been logged.
        assert any("INSERT INTO audit_log_v2" in sql for sql in conn.execute_log)

    def test_write_entry_swallows_db_errors(self):
        """Audit failures must never surface — fire-and-forget semantics."""
        from app.enterprise import audit_log as al

        class ExplodingConn(ScriptedConn):
            async def execute(self, sql, *_a, **_kw):
                raise RuntimeError("db on fire")

        conn = ExplodingConn()
        pool = make_pool(conn)
        # No assertion required — just "doesn't raise".
        _run(al.write_entry(pool, action="BOOM"))

    def test_is_enabled_flag(self, monkeypatch):
        from app.enterprise import audit_log as al
        monkeypatch.delenv("PRINCEPS_AUDIT_ENABLED", raising=False)
        assert al.is_enabled() is False
        monkeypatch.setenv("PRINCEPS_AUDIT_ENABLED", "true")
        assert al.is_enabled() is True


# ---------------------------------------------------------------------------
# SSO — JIT provisioning on callback (bypasses real IdP via monkeypatch)
# ---------------------------------------------------------------------------

class TestSSOCallback:
    def test_jit_provisions_new_user(self, monkeypatch):
        from app.enterprise import sso as sso_mod
        import app.enterprise.tenants as tenants_mod

        # Patch tenant lookup + IdP config lookup.
        from uuid import uuid4
        tenant_id = str(uuid4())
        tenant = {"id": tenant_id, "slug": "acme", "display_name": "Acme",
                  "plan": "enterprise", "white_label": None, "trust_badges": {},
                  "created_at": None, "updated_at": None}
        config = {
            "id":                      str(uuid4()),
            "tenant_id":               tenant_id,
            "provider":                "google",
            "issuer_url":              "https://accounts.google.com",
            "client_id":               "client-id",
            "client_secret_encrypted": sso_mod.encryption.encrypt("secret"),
            "metadata_url":            None,
            "allowed_email_domains":   ["acme.com"],
            "jit_provisioning":        True,
            "default_role":            "member",
        }

        async def _fake_get_tenant(_pool, slug):
            return tenant if slug == "acme" else None

        async def _fake_get_idp(_pool, **_kw):
            return config

        async def _fake_exchange(**_kw):
            return {"email": "alice@acme.com", "name": "Alice"}

        async def _fake_add_member(_pool, *, tenant_id, user_id, role):
            return {"id": str(uuid4()), "tenant_id": tenant_id,
                    "user_id": user_id, "role": role}

        # Script user lookup: first None (no existing user), then the INSERT
        # RETURNING row, plus the userinfo request bypass.
        conn = ScriptedConn()
        conn.fetchrow_queue.append(None)  # SELECT users by email → not found
        conn.fetchrow_queue.append({       # INSERT users ... RETURNING
            "user_id": uuid4(),
            "email":   "alice@acme.com",
            "name":    "Alice",
            "org_name": None,
            "role":    "member",
        })

        pool = make_pool(conn)

        monkeypatch.setattr(sso_mod, "get_tenant_by_slug", _fake_get_tenant)
        monkeypatch.setattr(sso_mod, "get_tenant_idp", _fake_get_idp)
        monkeypatch.setattr(sso_mod, "_exchange_code", _fake_exchange)
        monkeypatch.setattr(sso_mod, "add_member", _fake_add_member)

        result = _run(sso_mod.handle_callback(
            pool,
            tenant_slug="acme",
            code="auth-code",
            state="s",
            expected_state="s",
            redirect_uri="https://princeps.energy/cb",
        ))
        assert result["provisioned"] is True
        assert result["user"]["email"] == "alice@acme.com"
        assert result["role"] == "member"

    def test_state_mismatch_rejected(self, monkeypatch):
        from app.enterprise import sso as sso_mod
        with pytest.raises(PermissionError):
            _run(sso_mod.handle_callback(
                make_pool(ScriptedConn()),
                tenant_slug="acme",
                code="c",
                state="s1",
                expected_state="s2",
                redirect_uri="https://princeps.energy/cb",
            ))

    def test_domain_not_allowed(self, monkeypatch):
        from app.enterprise import sso as sso_mod
        from uuid import uuid4

        tenant_id = str(uuid4())
        tenant = {"id": tenant_id, "slug": "acme", "display_name": "Acme",
                  "plan": "enterprise", "white_label": None, "trust_badges": {},
                  "created_at": None, "updated_at": None}
        config = {
            "id":                      str(uuid4()),
            "tenant_id":               tenant_id,
            "provider":                "google",
            "issuer_url":              "https://accounts.google.com",
            "client_id":               "client-id",
            "client_secret_encrypted": sso_mod.encryption.encrypt("secret"),
            "metadata_url":            None,
            "allowed_email_domains":   ["acme.com"],  # only acme.com allowed
            "jit_provisioning":        True,
            "default_role":            "member",
        }
        async def _t(_p, slug): return tenant
        async def _i(_p, **_kw): return config
        async def _x(**_kw): return {"email": "eve@other.com"}

        monkeypatch.setattr(sso_mod, "get_tenant_by_slug", _t)
        monkeypatch.setattr(sso_mod, "get_tenant_idp", _i)
        monkeypatch.setattr(sso_mod, "_exchange_code", _x)

        with pytest.raises(PermissionError):
            _run(sso_mod.handle_callback(
                make_pool(ScriptedConn()),
                tenant_slug="acme",
                code="c",
                state="s",
                expected_state="s",
                redirect_uri="https://princeps.energy/cb",
            ))


# ---------------------------------------------------------------------------
# Tenants — slug + role helpers
# ---------------------------------------------------------------------------

class TestTenantsHelpers:
    def test_slugify(self):
        from app.enterprise.tenants import slugify
        assert slugify("Acme Energy Ltd.") == "acme-energy-ltd"
        assert slugify("  lots   of spaces  ") == "lots-of-spaces"
        assert slugify("") == "tenant"

    def test_role_ordering(self):
        from app.enterprise.tenants import role_at_least
        assert role_at_least("owner", "admin") is True
        assert role_at_least("admin", "member") is True
        assert role_at_least("member", "admin") is False
        assert role_at_least("viewer", "viewer") is True
        assert role_at_least(None, "viewer") is False

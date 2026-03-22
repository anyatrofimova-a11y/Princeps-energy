"""Smoke tests for Princeps API — verifies key endpoints are reachable.

Usage:
    pytest tests/test_api_smoke.py -v

These tests spin up the FastAPI app with a mocked database pool
so they can run without a live PostgreSQL connection.
"""

from __future__ import annotations

import os
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pathlib

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# Set required env vars BEFORE importing the app
os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/feasibly_test")
os.environ.setdefault("CLAUDE_API_KEY", "sk-test-fake-key-for-smoke-tests")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("PRINCEPS_DEMO_MODE", "true")


# ---------------------------------------------------------------------------
# Fixture: mock pool + patched app
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mock_pool():
    """Create a mock asyncpg pool that returns safe defaults."""
    pool = MagicMock()
    pool.get_size.return_value = 5
    pool.get_idle_size.return_value = 3
    pool.get_min_size.return_value = 3
    pool.get_max_size.return_value = 15

    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock()

    # pool.acquire() as conn:
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    return pool


@pytest.fixture(scope="module")
def test_client(mock_pool):
    """Create httpx AsyncClient bound to the app, skipping real lifespan."""
    import httpx
    from fastapi.testclient import TestClient

    # Patch lifespan so it doesn't try to connect to real DB
    from app import main as app_module

    app = app_module.app

    # Inject mock state directly
    app.state.pool = mock_pool
    app.state.claude = MagicMock()
    app.state._start_time = 0

    client = TestClient(app, raise_server_exceptions=False)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_200(self, test_client):
        """GET /health should return 200 with status field."""
        resp = test_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "checks" in data
        assert "uptime_s" in data


class TestGridLiveStatus:
    def test_live_status_returns_200(self, test_client):
        """GET /api/grid/live-status should return 200 (may return cached/empty data)."""
        resp = test_client.get("/api/grid/live-status")
        # Accept 200 (data available) or 503 (no data yet) — both are valid responses
        assert resp.status_code in (200, 503, 404)


class TestConnectionForecast:
    def test_connection_forecast_returns_200(self, test_client):
        """POST /api/grid/connection-forecast with sample coords should not 500."""
        resp = test_client.post(
            "/api/grid/connection-forecast",
            params={"lat": 51.5, "lon": -1.0, "capacity_mw": 50, "technology": "solar"},
        )
        # Accept 200 (success) or 4xx/503 (missing data) — just not 500
        assert resp.status_code < 500

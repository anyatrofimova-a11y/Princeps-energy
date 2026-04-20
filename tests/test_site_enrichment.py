"""Unit tests for the site-enrichment package + /api/analysis/enrich endpoint.

All HTTP + PostGIS interactions are mocked — these tests run without network
access or a live database.

Coverage (8 tests):

1. postcode.lookup happy-path (postcodes.io mocked via respx/httpx).
2. postcode.lookup gracefully handles 404.
3. dno.lookup falls back to the bundled postcode→DNO map.
4. lpa.lookup uses PostGIS when the table exists.
5. hmlr.lookup returns a structured TODO when the table is missing.
6. constraints.lookup returns a TODO per missing table.
7. enricher.enrich is a total function — all sub-enrichers can fail and
   the result is still 200-shaped with errors[] populated.
8. GET /api/analysis/enrich routes through auth + orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/feasibly_test")
os.environ.setdefault("CLAUDE_API_KEY", "sk-test-fake-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("PRINCEPS_DEMO_MODE", "true")
os.environ.setdefault("PRINCEPS_SEED_ALERTS", "false")
# Force cache off for deterministic tests.
os.environ.pop("REDIS_URL", None)
os.environ.pop("OS_PLACES_KEY", None)
os.environ.pop("EPC_API_KEY", None)


# ---------------------------------------------------------------------------
# Helpers — a scripted asyncpg connection + pool
# ---------------------------------------------------------------------------

class ScriptedConn:
    def __init__(self):
        self.fetch_queue: list = []
        self.fetchrow_queue: list = []
        self.fetchval_queue: list = []
        self.execute_log: list = []

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
        return "OK"


def make_pool(conn: ScriptedConn):
    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool


class _DummyResp:
    def __init__(self, *, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._payload


class _DummyHTTPClient:
    """Mimics httpx.AsyncClient for single-response tests."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def aclose(self):
        pass


# ---------------------------------------------------------------------------
# 1 — postcode happy-path
# ---------------------------------------------------------------------------

def test_postcode_happy_path():
    from utils.site_enrichment import postcode

    resp = _DummyResp(payload={
        "status": 200,
        "result": [{
            "postcode": "SW1A 1AA",
            "lsoa": "Westminster 018C",
            "msoa": "Westminster 018",
            "country": "England",
            "parish": "Westminster, unparished area",
            "admin_district": "Westminster",
            "admin_ward": "St James's",
            "admin_county": None,
            "parliamentary_constituency": "Cities of London and Westminster",
            "eastings": 529090,
            "northings": 179645,
            "distance": 12.5,
        }],
    })
    client = _DummyHTTPClient(resp)
    out = asyncio.run(postcode.lookup(51.5014, -0.1419, client=client))
    assert out["postcode"] == "SW1A 1AA"
    assert out["admin_district"] == "Westminster"
    assert out["lsoa"] == "Westminster 018C"


# ---------------------------------------------------------------------------
# 2 — postcode 404 degrades gracefully
# ---------------------------------------------------------------------------

def test_postcode_404_returns_empty_dict():
    from utils.site_enrichment import postcode

    resp = _DummyResp(status_code=404, payload={})
    client = _DummyHTTPClient(resp)
    out = asyncio.run(postcode.lookup(0.0, 0.0, client=client))
    assert out == {}


# ---------------------------------------------------------------------------
# 3 — DNO static-map fallback
# ---------------------------------------------------------------------------

def test_dno_postcode_fallback():
    from utils.site_enrichment import dno

    # No pool → must use the bundled static map.
    out = asyncio.run(dno.lookup(51.5, -0.12, pool=None, postcode="SW1A 1AA"))
    assert out["dno_name"].startswith("UK Power Networks")
    assert out["licence_sub_region"] == "LPN"


# ---------------------------------------------------------------------------
# 4 — LPA PostGIS path
# ---------------------------------------------------------------------------

def test_lpa_postgis_hit():
    from utils.site_enrichment import lpa

    conn = ScriptedConn()
    # _table_exists is called twice inside lpa.lookup — before and after
    # the (skipped) bootstrap. Both must return truthy.
    conn.fetchval_queue.append("public.lpa_boundaries")
    conn.fetchval_queue.append("public.lpa_boundaries")
    # _postgis_lookup row
    conn.fetchrow_queue.append({
        "lpa_code": "E07000223",
        "lpa_name": "Arun",
        "region": "South East",
    })
    pool = make_pool(conn)

    out = asyncio.run(lpa.lookup(50.82, -0.55, pool=pool))
    assert out["lpa_code"] == "E07000223"
    assert out["lpa_name"] == "Arun"


# ---------------------------------------------------------------------------
# 5 — HMLR structured TODO when table missing
# ---------------------------------------------------------------------------

def test_hmlr_missing_table_returns_todo():
    from utils.site_enrichment import hmlr

    conn = ScriptedConn()
    # _table_exists → False
    conn.fetchval_queue.append(None)
    pool = make_pool(conn)

    out = asyncio.run(hmlr.lookup(51.5, -0.12, pool=pool))
    assert out["inspire_id"] is None
    assert out["title_number"] is None
    assert "not ingested" in out["todo"]


# ---------------------------------------------------------------------------
# 6 — constraints returns a TODO per missing table
# ---------------------------------------------------------------------------

def test_constraints_all_tables_missing():
    from utils.site_enrichment import constraints

    conn = ScriptedConn()
    # Every _table_exists probe returns None (12 layers).
    for _ in range(20):
        conn.fetchval_queue.append(None)
    pool = make_pool(conn)

    out = asyncio.run(constraints.lookup(51.5, -0.12, pool=pool))
    assert "aonb" in out and "todo" in out["aonb"]
    assert out["aonb"]["inside"] is None
    assert out["flood_zone_3"]["todo"].startswith("Table 'ea_flood_zone_3'")
    # Listed buildings + ALC grades also present
    assert "listed_buildings" in out
    assert "alc_grades_1_3a" in out


# ---------------------------------------------------------------------------
# 7 — enrich is total: every sub-enricher fails → 200-shaped result
# ---------------------------------------------------------------------------

def test_enrich_all_sub_enrichers_failing_still_returns_result():
    from utils.site_enrichment import enricher

    async def _boom(*a, **kw):
        raise RuntimeError("backend down")

    with patch.object(enricher._postcode,    "lookup", side_effect=_boom), \
         patch.object(enricher._lpa,         "lookup", side_effect=_boom), \
         patch.object(enricher._dno,         "lookup", side_effect=_boom), \
         patch.object(enricher._uprn,        "lookup", side_effect=_boom), \
         patch.object(enricher._hmlr,        "lookup", side_effect=_boom), \
         patch.object(enricher._constraints, "lookup", side_effect=_boom), \
         patch.object(enricher._epc,         "lookup", side_effect=_boom), \
         patch.object(enricher._landuse,     "lookup", side_effect=_boom):
        result = asyncio.run(enricher.enrich(51.5, -0.12, pool=None, use_cache=False))

    assert result.lat == 51.5
    assert result.lon == -0.12
    # Every sub-enricher is None.
    assert result.postcode    is None
    assert result.lpa         is None
    assert result.dno         is None
    assert result.uprn        is None
    assert result.hmlr        is None
    assert result.constraints is None
    assert result.epc         is None
    assert result.landuse     is None
    # 8 failures in errors[].
    assert len(result.errors) == 8
    assert all("backend down" in e for e in result.errors)
    assert result.elapsed_ms >= 0.0


# ---------------------------------------------------------------------------
# 8 — /api/analysis/enrich routes through auth + orchestrator
# ---------------------------------------------------------------------------

def test_enrich_endpoint_returns_result():
    """End-to-end: FastAPI TestClient hits the router, orchestrator mocked."""
    from fastapi.testclient import TestClient
    from app import main as app_module
    from utils.site_enrichment.enricher import EnrichmentResult

    app_instance = app_module.app

    # Minimal mocked pool so the dep resolves.
    conn = ScriptedConn()
    pool = make_pool(conn)
    app_instance.state.pool = pool
    app_instance.state.claude = MagicMock()
    app_instance.state._start_time = 0

    fake_result = EnrichmentResult(
        lat=51.5,
        lon=-0.12,
        postcode={"postcode": "SW1A 1AA", "admin_district": "Westminster"},
        lpa={"lpa_code": "E09000033", "lpa_name": "Westminster", "region": "London"},
        dno={"dno_slug": "ukpn_lp", "dno_name": "UKPN LPN", "licence_sub_region": "LPN"},
        uprn={"uprn": None, "todo": "Set OS_PLACES_KEY"},
        hmlr={"title_number": None, "inspire_id": None, "todo": "not ingested"},
        constraints={"aonb": {"inside": False, "distance_m": None, "todo": None}},
        epc={"certificates": [], "todo": "Set EPC_API_KEY"},
        landuse={"dominant": "built", "confidence": 0.92, "class_distribution": {"built": 0.92}},
        errors=[],
        elapsed_ms=12.3,
        cache_hit=False,
    )

    with patch("utils.site_enrichment.enricher.enrich", new=AsyncMock(return_value=fake_result)):
        client = TestClient(app_instance, raise_server_exceptions=False)
        resp = client.get("/api/analysis/enrich", params={"lat": 51.5, "lon": -0.12})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lat"] == 51.5
    assert body["lon"] == -0.12
    assert body["postcode"]["postcode"] == "SW1A 1AA"
    assert body["lpa"]["lpa_code"] == "E09000033"
    assert body["dno"]["dno_slug"] == "ukpn_lp"
    assert body["errors"] == []
    assert body["cache_hit"] is False

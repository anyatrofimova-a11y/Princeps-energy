"""
Integration tests for the DNO ingestion pipeline (Task #21 — Phase 7a).

These tests cover:
  * OpenDataSoftAdapter.fetch_substations  — happy-path parsing
  * CKANAdapter._fetch_records             — datastore + package_show fallback
  * ingest_all_dnos                        — end-to-end with mocked HTTP + DB
  * log schema extension                   — ensure_log_schema idempotency
  * start/finish helpers                   — grid_ingestion_log round-trip
  * latest_ingest_status_per_source        — read-side helper

All HTTP calls are patched via monkeypatch; no live network is hit and no
real DB is touched. Intentionally does NOT depend on pytest-asyncio so it
runs on the existing project test harness.

Usage:
    pytest tests/test_dno_ingest.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys
import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/feasibly_test")

from utils import grid_data_ingester as gdi  # noqa: E402


def _run(coro):
    """Convenience helper: run an async function to completion on a fresh loop."""
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_conn():
    """An AsyncMock asyncpg connection that records every execute/fetch."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.executemany = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value={"id": 42})
    conn.fetchval = AsyncMock(return_value=0)
    return conn


@pytest.fixture
def mock_pool(mock_conn):
    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx
    return pool


# ---------------------------------------------------------------------------
# OpenDataSoftAdapter — happy path
# ---------------------------------------------------------------------------


class TestOpenDataSoftAdapter:
    def test_fetch_substations_parses_records(self, monkeypatch):
        """OpenDataSoftAdapter should convert v2.1 record rows to
        upsertable substation dicts, handling `geo_point_2d` correctly."""
        config = {
            "name": "Test UKPN",
            "platform": "opendatasoft",
            "base_url": "https://example.test",
            "datasets": {"substations": "test-dataset"},
            "api_key_env": "TEST_ODS_KEY",
        }
        monkeypatch.setenv("TEST_ODS_KEY", "fake-key")

        async def fake_get(self, url, params=None):
            offset = (params or {}).get("offset", 0)
            if offset == 0:
                payload = {
                    "total_count": 2,
                    "results": [
                        {
                            "substation_name": "Canary Wharf",
                            "voltage": 132,
                            "demand_mw": 85,
                            "generation_mw": 0,
                            "demand_headroom_mw": 15,
                            "geo_point_2d": {"lat": 51.505, "lon": -0.02},
                        },
                        {
                            "substation_name": "Stratford",
                            "voltage": 33,
                            "demand_headroom_mw": 40,
                            "geo_point_2d": {"lat": 51.54, "lon": 0.01},
                        },
                    ],
                }
            else:
                payload = {"total_count": 2, "results": []}
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=payload)
            resp.raise_for_status = MagicMock()
            return resp

        monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

        adapter = gdi.OpenDataSoftAdapter("ukpn", config)
        subs = _run(adapter.fetch_substations())
        assert len(subs) == 2
        canary = subs[0]
        assert canary["name"] == "Canary Wharf"
        assert canary["lat"] == pytest.approx(51.505)
        assert canary["demand_headroom_mw"] == 15

    def test_fetch_ecr_returns_empty_when_not_configured(self):
        config = {
            "name": "NPG",
            "platform": "opendatasoft",
            "base_url": "https://example.test",
            "datasets": {"substations": "foo"},  # no ecr
        }
        adapter = gdi.OpenDataSoftAdapter("npg", config)
        assert _run(adapter.fetch_ecr()) == []


# ---------------------------------------------------------------------------
# CKANAdapter — datastore + package_show fallback
# ---------------------------------------------------------------------------


class TestCKANAdapter:
    def test_ckan_falls_through_to_package_show(self, monkeypatch):
        """Confirm that when datastore_search returns empty/unsuccess,
        the adapter falls through to package_show + CSV download (the NGED
        pattern that was broken in Task #21)."""
        config = {
            "name": "NGED",
            "platform": "ckan",
            "base_url": "https://connecteddata.nationalgrid.co.uk",
            "datasets": {"capacity": "test-resource-id"},
            "api_key_env": None,
        }
        adapter = gdi.CKANAdapter("nged", config)

        csv_body = (
            "Substation Name,Region,Voltage (kV),Demand (MW),"
            "Demand Headroom (MW),Latitude,Longitude\n"
            "Bristol GSP,South West,132,120,25,51.45,-2.58\n"
            "Exeter BSP,South West,33,40,8,50.72,-3.53\n"
        )

        async def fake_get(self, url, params=None, timeout=None):
            resp = MagicMock()
            if "datastore_search" in url:
                # Simulate NGED behaviour: datastore returns unsuccess
                resp.status_code = 200
                resp.json = MagicMock(return_value={"success": False})
            elif "package_show" in url:
                resp.status_code = 200
                resp.json = MagicMock(return_value={
                    "success": True,
                    "result": {"resources": [{
                        "format": "CSV",
                        "url": "https://example.test/mock.csv",
                    }]},
                })
            else:  # the CSV download
                resp.status_code = 200
                resp.text = csv_body
            resp.raise_for_status = MagicMock()
            return resp

        monkeypatch.setattr("httpx.AsyncClient.get", fake_get)

        subs = _run(adapter.fetch_substations())
        assert len(subs) == 2
        assert subs[0]["name"] == "Bristol GSP"
        assert subs[0]["voltage_kv"] == 132
        assert subs[0]["demand_headroom_mw"] == 25

    def test_ckan_datastore_happy_path(self, monkeypatch):
        """If the CKAN datastore IS populated, adapter should use it and
        NOT fall through to package_show."""
        config = {
            "name": "SSEN",
            "platform": "ckan",
            "base_url": "https://data-api.ssen.co.uk",
            "datasets": {"ecr": "ssen-ecr-id"},
            "api_key_env": None,
        }
        adapter = gdi.CKANAdapter("ssen", config)

        async def fake_get(self, url, params=None, timeout=None):
            if "datastore_search" in url:
                offset = (params or {}).get("offset", 0)
                if offset == 0:
                    payload = {
                        "success": True,
                        "result": {"records": [{
                            "Site Name": "Aberdeen",
                            "Technology": "wind",
                            "Capacity (MW)": 12.5,
                            "Connection Status": "connected",
                        }]},
                    }
                else:
                    payload = {"success": True, "result": {"records": []}}
                resp = MagicMock()
                resp.status_code = 200
                resp.json = MagicMock(return_value=payload)
                resp.raise_for_status = MagicMock()
                return resp
            raise AssertionError(f"Did not expect {url}")

        monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
        entries = _run(adapter.fetch_ecr())
        assert len(entries) == 1
        assert entries[0]["site_name"] == "Aberdeen"
        assert entries[0]["capacity_mw"] == 12.5


# ---------------------------------------------------------------------------
# ingest_all_dnos — end-to-end with all HTTP mocked
# ---------------------------------------------------------------------------


class TestIngestAllDnos:
    def test_dry_run_no_persist(self, mock_pool, monkeypatch):
        """--dry-run should fetch but not call the upserters."""
        async def no_subs(self):
            return []
        async def no_ecr(self):
            return []
        async def no_lines(*a, **k):
            return []
        async def no_bounds():
            return []

        monkeypatch.setattr(gdi.OpenDataSoftAdapter, "fetch_substations", no_subs)
        monkeypatch.setattr(gdi.OpenDataSoftAdapter, "fetch_ecr", no_ecr)
        monkeypatch.setattr(gdi.CKANAdapter, "fetch_substations", no_subs)
        monkeypatch.setattr(gdi.CKANAdapter, "fetch_ecr", no_ecr)
        monkeypatch.setattr(gdi.OverpassAdapter, "fetch_power_lines", no_lines)
        monkeypatch.setattr(gdi, "fetch_dno_boundaries", no_bounds)

        summary = _run(gdi.ingest_all_dnos(mock_pool, dry_run=True))
        assert summary["dry_run"] is True
        for dno_code in gdi.DNO_CONFIGS:
            assert dno_code in summary

    def test_one_dno_failure_does_not_break_others(self, mock_pool, monkeypatch):
        """If UKPN fetch raises, SSEN/NGED should still run and log rows."""
        async def ods_substations(self):
            if self.dno_code == "ukpn":
                raise ConnectionError("upstream 403")
            return []
        async def ok(self):
            return []
        async def no_lines(*a, **k):
            return []
        async def no_bounds():
            return []

        monkeypatch.setattr(gdi.OpenDataSoftAdapter, "fetch_substations", ods_substations)
        monkeypatch.setattr(gdi.OpenDataSoftAdapter, "fetch_ecr", ok)
        monkeypatch.setattr(gdi.CKANAdapter, "fetch_substations", ok)
        monkeypatch.setattr(gdi.CKANAdapter, "fetch_ecr", ok)
        monkeypatch.setattr(gdi.OverpassAdapter, "fetch_power_lines", no_lines)
        monkeypatch.setattr(gdi, "fetch_dno_boundaries", no_bounds)

        summary = _run(gdi.ingest_all_dnos(mock_pool))
        assert summary["ukpn"]["status"] in ("failed", "partial")
        for dno_code in ("npg", "spen", "enwl", "ssen", "nged"):
            assert dno_code in summary
            assert summary[dno_code]["status"] != "failed"


# ---------------------------------------------------------------------------
# grid_ingestion_log schema extension + helpers
# ---------------------------------------------------------------------------


class TestLogHelpers:
    def test_ensure_log_schema_is_idempotent(self, mock_conn):
        _run(gdi.ensure_log_schema(mock_conn))
        assert mock_conn.execute.await_count >= 2
        for call in mock_conn.execute.await_args_list:
            sql = call.args[0]
            assert "grid_ingestion_log" in sql

    def test_start_finish_roundtrip(self, mock_conn):
        async def go():
            log_id = await gdi.start_ingestion(mock_conn, "ukpn", "substations")
            await gdi.finish_ingestion(
                mock_conn, log_id,
                status="success", fetched=10, upserted=10, inserted=10,
            )
            return log_id
        log_id = _run(go())
        assert log_id == 42
        update_calls = [
            c for c in mock_conn.execute.await_args_list
            if "UPDATE grid_ingestion_log" in c.args[0]
        ]
        assert update_calls, "expected an UPDATE against grid_ingestion_log"
        assert update_calls[-1].args[1] == 42

    def test_finish_ingestion_noop_on_zero(self, mock_conn):
        before = mock_conn.execute.await_count
        _run(gdi.finish_ingestion(mock_conn, 0, status="success"))
        assert mock_conn.execute.await_count == before


# ---------------------------------------------------------------------------
# Status read helper
# ---------------------------------------------------------------------------


class TestIngestStatusReader:
    def test_latest_ingest_status_per_source(self, mock_pool, mock_conn):
        mock_conn.fetch = AsyncMock(return_value=[
            {
                "source": "ukpn", "dataset": "substations",
                "status": "success",
                "records_fetched": 100, "records_upserted": 100,
                "rows_inserted": 100, "rows_updated": 0, "rows_failed": 0,
                "error_message": None,
                "started_at": "2026-04-19T03:00:00Z",
                "finished_at": "2026-04-19T03:05:00Z",
            },
        ])
        rows = _run(gdi.latest_ingest_status_per_source(mock_pool))
        assert len(rows) == 1
        assert rows[0]["source"] == "ukpn"
        assert rows[0]["status"] == "success"

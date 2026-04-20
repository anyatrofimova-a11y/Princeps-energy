"""Unit tests for project KPIs + AI Site Memo (backend)."""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql://localhost:5432/feasibly_test")
os.environ.setdefault("CLAUDE_API_KEY", "sk-test-fake")
os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("PRINCEPS_DEMO_MODE", "true")
os.environ.setdefault("PRINCEPS_SEED_ALERTS", "false")


# ---------------------------------------------------------------------------
# 1. KPI — no-pool synthetic path
# ---------------------------------------------------------------------------
def test_compute_kpis_synthetic_when_no_pool():
    from utils.project_kpis import compute_kpis

    kpi = asyncio.run(compute_kpis("proj-123", pool=None, skip_cache=True))
    assert kpi.project_id == "proj-123"
    assert 0 <= kpi.viability_pct <= 100
    assert 0 <= kpi.grid_risk_pct <= 100
    assert 0 <= kpi.planning_risk_pct <= 100
    assert 0 <= kpi.confidence <= 1
    assert kpi.critical_path_days >= 0
    assert "T" in kpi.last_updated_iso  # ISO timestamp


# ---------------------------------------------------------------------------
# 2. KPI — cache hit shortcircuits the pool
# ---------------------------------------------------------------------------
def test_compute_kpis_cache_roundtrip():
    from utils.project_kpis import compute_kpis, invalidate_cache

    async def _go():
        await invalidate_cache("proj-cache")
        a = await compute_kpis("proj-cache", pool=None, skip_cache=True)
        b = await compute_kpis("proj-cache", pool=None)
        # Second call hits the cache layer and returns identical values.
        assert a.viability_pct == b.viability_pct
        assert a.last_updated_iso == b.last_updated_iso

    asyncio.run(_go())


# ---------------------------------------------------------------------------
# 3. Memo composer — validates schema when Claude returns malformed text
# ---------------------------------------------------------------------------
def test_compose_memo_schema_validity_fallback():
    from utils.site_memo import compose_memo, MEMO_SCHEMA

    ctx = {
        "project": {"project_id": "p1", "name": "Wessex Solar", "capacity_mw": 49.9, "technology": "solar"},
        "lpa": "South Somerset",
        "financial": {"npv_gbp_m": 12.2, "irr_pct": 10.8, "dscr": 1.38},
        "grid": {"poc": "Yeovil 33kV", "firm_mw": 48, "estimated_cost_gbp_m": 3.1, "timeline_months": 22},
        "planning": {"approval_pct": 72, "precedent_count": 4},
        "verdicts": {"feasibility": {"verdict": "GO", "confidence": 0.8, "summary": ""}},
    }

    memo = asyncio.run(compose_memo(ctx, claude_client=None))
    for key in MEMO_SCHEMA:
        assert key in memo, f"missing field: {key}"
    assert memo["investment_verdict"] in ("GO", "CAUTION", "NO-GO")
    assert 3 <= len(memo["key_strengths"]) <= 5
    assert 3 <= len(memo["critical_risks"]) <= 5
    assert len(memo["next_milestones"]) <= 3
    assert memo["financial_headline"]["irr_pct"] == 10.8


# ---------------------------------------------------------------------------
# 4. Memo composer — parses JSON-in-code-fence and upgrades verdict casing
# ---------------------------------------------------------------------------
def test_compose_memo_claude_response_parsed():
    from utils.site_memo import compose_memo

    fake_json = {
        "title": "Test Asset — 30 MW BESS",
        "one_liner": "Grid-scale battery adjacent to DNO 132 kV substation.",
        "investment_verdict": "go",  # lowercase — composer must normalise
        "key_strengths": ["A", "B", "C"],
        "critical_risks": ["X", "Y", "Z"],
        "next_milestones": [{"date": "2026-06-01", "action": "DNO app"}],
        "financial_headline": {"npv_gbp_m": 8.4, "irr_pct": 12.1, "dscr": 1.5},
        "grid_headline": {"poc": "Test POC", "firm_mw": 30, "estimated_cost_gbp_m": 2.1, "timeline_months": 18},
        "planning_headline": {"approval_pct": 80, "lpa": "Example DC", "precedent_count": 6},
        "regulatory_flags": ["G99"],
        "source_evidence": [{"label": "DNO map", "doc_id": "dno-1"}],
    }
    # Emulate Claude wrapping the JSON in a code fence.
    content_block = MagicMock(type="text", text="```json\n" + json.dumps(fake_json) + "\n```")
    resp = MagicMock(content=[content_block])

    client = MagicMock()
    client.messages.create = AsyncMock(return_value=resp)

    memo = asyncio.run(compose_memo({"project": {"name": "X"}}, claude_client=client))
    assert memo["investment_verdict"] == "GO"
    assert memo["title"] == "Test Asset — 30 MW BESS"
    assert memo["financial_headline"]["irr_pct"] == 12.1


# ---------------------------------------------------------------------------
# 5. Renderer — HTML mock render with fixture memo
# ---------------------------------------------------------------------------
def test_render_memo_html_contains_key_sections():
    from utils.site_memo import compose_memo
    from utils.site_memo.memo_renderer import render_memo_html

    memo = asyncio.run(compose_memo({"project": {"name": "Alpha", "capacity_mw": 40, "technology": "solar"}},
                                    claude_client=None))
    html = render_memo_html(memo)
    assert "Alpha" in html
    assert "PRINCEPS" in html
    assert "Key Strengths" in html
    assert "Critical Risks" in html
    assert "Next Milestones" in html
    assert memo["investment_verdict"] in html
    # Check brand palette landed.
    assert "#F5B731" in html or "gold" in html.lower()


# ---------------------------------------------------------------------------
# 6. Renderer — PDF path is mocked out so we don't need Chromium in CI.
# ---------------------------------------------------------------------------
def test_render_memo_pdf_invokes_html_to_pdf(tmp_path, monkeypatch):
    from utils.site_memo import compose_memo
    from utils.site_memo import memo_renderer

    monkeypatch.setattr(memo_renderer, "MEMO_OUTPUT_DIR", tmp_path)

    async def _fake_html_to_pdf(html: str) -> bytes:
        # Minimal mock — return the HTML encoded as bytes so we can assert.
        return b"%PDF-fake-" + html.encode("utf-8")[:64]

    # Patch the dynamic import inside render_memo_pdf.
    monkeypatch.setattr("utils.report_renderer.html_to_pdf", _fake_html_to_pdf)

    memo = asyncio.run(compose_memo({"project": {"name": "Beta", "capacity_mw": 25}},
                                    claude_client=None))

    pdf_bytes, saved_path = asyncio.run(memo_renderer.render_memo_pdf(memo))
    assert pdf_bytes.startswith(b"%PDF-")
    assert saved_path.exists()
    assert saved_path.suffix == ".pdf"
    assert tmp_path in saved_path.parents

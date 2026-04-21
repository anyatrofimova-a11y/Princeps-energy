"""utils.ic_memo — Equity IC memo pack (distinct from lender pack).

Per the 2026 IC memo standard (docs/competitive/ic_memo_standard_2026.md)
the IC memo is an EQUITY decision document, shorter and front-loaded,
sitting above the lender pack. This package produces a 6-section IC memo:

  s01_recommendation  — page-1 GO/CAUTION/NO-GO box + 4-row KPI table
  s02_exec_summary    — 2-page narrative (opportunity / thesis / why now / ask)
  s03_project_detail  — site / tech / counterparties / key assumptions
  s04_financial_case  — base + Lender Case (combined) + upside variance
  s05_risk_matrix     — 5×5 risk grid, linked to CPs/CSs/insurance
  s06_ask_vote        — investment ask + decision frame
  s_precedents        — UK comps (from utils.ic_memo.precedents)

Public API: utils.ic_memo.generate_ic_memo_pack_pdf(...)
Route:      POST /api/reports/ic-memo-pack in app.routers.reports
"""
from __future__ import annotations

from .precedents import UK_PRECEDENTS, get_comps, count_comps, to_lender_pack_rows
from .sections import (
    build_recommendation_box,
    build_exec_summary,
    build_project_detail,
    build_financial_case,
    build_risk_matrix,
    build_ask_vote,
    build_precedents_section,
)
from .pack import generate_ic_memo_pack_pdf, assemble_ic_memo_context

__all__ = [
    "UK_PRECEDENTS",
    "get_comps",
    "count_comps",
    "to_lender_pack_rows",
    "build_recommendation_box",
    "build_exec_summary",
    "build_project_detail",
    "build_financial_case",
    "build_risk_matrix",
    "build_ask_vote",
    "build_precedents_section",
    "generate_ic_memo_pack_pdf",
    "assemble_ic_memo_context",
]

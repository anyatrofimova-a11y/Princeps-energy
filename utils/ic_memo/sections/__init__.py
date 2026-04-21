"""IC Memo section builders.

Each module is a pure function that takes the assembled project context
and returns a dict the Jinja template consumes. Sections mirror the
2026 IC memo spec (docs/competitive/ic_memo_standard_2026.md §1).
"""
from __future__ import annotations

from .s01_recommendation import build_recommendation_box
from .s02_exec_summary import build_exec_summary
from .s03_project_detail import build_project_detail
from .s04_financial_case import build_financial_case
from .s05_risk_matrix import build_risk_matrix
from .s06_ask_vote import build_ask_vote
from .s_precedents import build_precedents_section

__all__ = [
    "build_recommendation_box",
    "build_exec_summary",
    "build_project_detail",
    "build_financial_case",
    "build_risk_matrix",
    "build_ask_vote",
    "build_precedents_section",
]

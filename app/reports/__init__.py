"""
app.reports — report generation pipelines (PDF + JSON).

Each module in this package is a self-contained report generator that
consumes a payload produced by a ``utils.*`` composer and emits a PDF
(via Jinja2 + Playwright) alongside the JSON preview.

Current generators
------------------
* ``report_dno_engagement`` — DNO Engagement Pack v1 (Task #18).
* ``lender_im`` — 30-page Data-Centre Lender Information Memorandum.
"""

from __future__ import annotations

__all__ = ["report_dno_engagement", "lender_im"]

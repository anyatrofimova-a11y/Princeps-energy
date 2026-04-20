"""Section 12 — Precedent transactions.

Calls utils.precedent_transactions.find_precedent_transactions (BOT-M)
via the shared DB pool. Top-5 comparables by similarity.
"""
from __future__ import annotations

from typing import Any


def build_precedent_transactions(
    precedent_rows: list[dict[str, Any]] | None,
    technology: str,
    capacity_mw: float,
    region: str,
) -> dict[str, Any]:
    rows = list(precedent_rows or [])
    return {
        "available": bool(rows),
        "rows": rows,
        "note": (
            f"Top {len(rows)} comparable deals by similarity (technology, "
            f"capacity bucket, region, year). Weighted composite per "
            f"utils.precedent_transactions."
        ),
        "target": {
            "technology": technology,
            "capacity_mw": capacity_mw,
            "region": region,
        },
        "citation": (
            "RICS Financial Viability in Planning (1st ed., 2021) — comparable "
            "evidence methodology; AIFMD marketing guidance (indicative only)."
        ),
    }

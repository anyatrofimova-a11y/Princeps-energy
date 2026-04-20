"""Section 11 — Conditions Subsequent (CS) schedule.

Pulls directly from utils.cp_cs_schedule.generate_cp_cs_schedule (BOT-P).
"""
from __future__ import annotations

from typing import Any


def build_cs_schedule(cp_cs_output: dict[str, Any] | None) -> dict[str, Any]:
    if not cp_cs_output or not cp_cs_output.get("cs_schedule"):
        return {
            "available": False,
            "note": "CS schedule unavailable.",
        }
    rows = list(cp_cs_output.get("cs_schedule", []) or [])
    summary = cp_cs_output.get("summary", {}) or {}
    return {
        "available": True,
        "rows": rows,
        "total": len(rows),
        "ready_pct": summary.get("cs_ready_pct", 0),
        "status_counts": summary.get("cs_status_counts", {}),
        "citation": "LMA IGFA — Conditions Subsequent + perfection steps (CA 2006 s.859A / LRA 2002 s.27).",
    }

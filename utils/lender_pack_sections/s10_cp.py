"""Section 10 — Conditions Precedent (CP) schedule.

Pulls directly from utils.cp_cs_schedule.generate_cp_cs_schedule (BOT-P)
and renders only the CP side. LMA Schedule 2 categories preserved.
"""
from __future__ import annotations

from typing import Any


def build_cp_schedule(cp_cs_output: dict[str, Any] | None) -> dict[str, Any]:
    if not cp_cs_output or not cp_cs_output.get("cp_schedule"):
        return {
            "available": False,
            "note": (
                "CP/CS schedule not generated (utils.cp_cs_schedule unavailable). "
                "Refer to LMA IGFA 2024 Schedule 2 for standard CP list."
            ),
        }
    rows = list(cp_cs_output.get("cp_schedule", []) or [])
    summary = cp_cs_output.get("summary", {}) or {}
    return {
        "available": True,
        "rows": rows,
        "total": len(rows),
        "ready_pct": summary.get("cp_ready_pct", 0),
        "status_counts": summary.get("cp_status_counts", {}),
        "citation": "LMA Leveraged Facility Agreement Schedule 2 (Conditions Precedent).",
    }

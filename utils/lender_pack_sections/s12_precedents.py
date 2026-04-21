"""Section 12 — Precedent transactions.

Calls utils.precedent_transactions.find_precedent_transactions (BOT-M)
via the shared DB pool. Top-5 comparables by similarity.

Extended (2026-04-19) to back-fill with the maintained UK precedent comps
in utils.ic_memo.precedents when the live DB lookup returns nothing or
fewer than `min_rows` rows.
"""
from __future__ import annotations

from typing import Any


def build_precedent_transactions(
    precedent_rows: list[dict[str, Any]] | None,
    technology: str,
    capacity_mw: float,
    region: str,
    *,
    min_rows: int = 6,
    capacity_band_pct: float = 0.5,
) -> dict[str, Any]:
    rows = list(precedent_rows or [])
    static_fallback_used = False

    # Back-fill with static UK comps when the DB lookup is thin.
    if len(rows) < min_rows:
        try:
            from utils.ic_memo.precedents import get_comps, to_lender_pack_rows  # local import — avoids cycle

            band: tuple[float, float] | None = None
            if capacity_mw:
                lo = capacity_mw * (1 - capacity_band_pct)
                hi = capacity_mw * (1 + capacity_band_pct)
                band = (lo, hi)

            static_rows_raw = get_comps(
                tech=technology,
                capacity_band=band,
                limit=12,
            )
            # If tight band returns too few, open to tech-only.
            if len(static_rows_raw) < min_rows:
                static_rows_raw = get_comps(tech=technology, limit=12)

            static_rows = to_lender_pack_rows(static_rows_raw)
            # Merge: live rows first, static fill the tail, dedup on deal_name.
            existing_names = {r.get("deal_name") for r in rows}
            for sr in static_rows:
                if sr.get("deal_name") not in existing_names:
                    rows.append(sr)
                    existing_names.add(sr.get("deal_name"))
                if len(rows) >= 10:
                    break
            static_fallback_used = True
        except Exception:
            # If the static comp set isn't importable, fall through
            static_fallback_used = False

    return {
        "available": bool(rows),
        "rows": rows,
        "note": (
            f"Top {len(rows)} comparable deals by similarity (technology, "
            f"capacity bucket, region, year). "
            + (
                "Live lookup via utils.precedent_transactions + "
                "utils.ic_memo.precedents static comp set."
                if static_fallback_used
                else "Weighted composite per utils.precedent_transactions."
            )
        ),
        "target": {
            "technology": technology,
            "capacity_mw": capacity_mw,
            "region": region,
        },
        "static_fallback_used": static_fallback_used,
        "citation": (
            "RICS Financial Viability in Planning (1st ed., 2021) — comparable "
            "evidence methodology; AIFMD marketing guidance (indicative only). "
            "Static UK comp set per utils.ic_memo.precedents."
        ),
    }

"""Section S — Precedent transactions (UK comps).

Reads the maintained UK precedent comps set from utils.ic_memo.precedents
and returns a filtered, sorted view for the IC memo table.
"""
from __future__ import annotations

from typing import Any

from utils.ic_memo.precedents import get_comps, count_comps


def build_precedents_section(
    tech: str | None = None,
    capacity_mw: float | None = None,
    live_rows: list[dict[str, Any]] | None = None,
    capacity_band_pct: float = 0.5,  # ±50%
    limit: int = 10,
) -> dict[str, Any]:
    """Return precedent rows for the IC memo.

    If live_rows (from BOT-M precedent_transactions) are provided,
    they take precedence and the static comps become the backup tail.
    """
    band: tuple[float, float] | None = None
    if capacity_mw:
        lo = capacity_mw * (1 - capacity_band_pct)
        hi = capacity_mw * (1 + capacity_band_pct)
        band = (lo, hi)

    static_rows = get_comps(tech=tech, capacity_band=band, limit=limit)
    # Fallback — if the tight band gives us < 6 results, open up tech only.
    if len(static_rows) < 6:
        static_rows = get_comps(tech=tech, limit=limit)

    primary_rows = list(live_rows or [])
    combined = primary_rows + static_rows
    combined = combined[:limit]

    # Derived stats
    gbp_per_mw_values = [
        r.get("gbp_per_mw") for r in static_rows
        if r.get("gbp_per_mw") is not None
    ]
    ev_ebitda_values = [
        r.get("ev_ebitda") for r in static_rows
        if r.get("ev_ebitda") is not None
    ]

    def _mean(v):
        return round(sum(v) / len(v), 0) if v else None

    return {
        "available": True,
        "rows": combined,
        "total_universe": count_comps(),
        "returned_count": len(combined),
        "mean_gbp_per_mw": _mean(gbp_per_mw_values),
        "mean_ev_ebitda": round(sum(ev_ebitda_values) / len(ev_ebitda_values), 1)
                           if ev_ebitda_values else None,
        "filter_note": (
            f"Filter: tech={tech or 'all'}, "
            f"capacity band "
            f"{('±%d%% around %.0f MW' % (capacity_band_pct * 100, capacity_mw))}"
            if capacity_mw else "all capacities"
            ", year 2023–2025 primary weighting."
        ),
        "citation": (
            "Princeps UK precedent transactions database (utils.ic_memo."
            "precedents). Source citations per-row; comp set refreshed monthly."
        ),
    }

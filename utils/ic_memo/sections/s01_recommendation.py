"""Section 1 — Page-1 recommendation box.

The single most important page of an IC memo. A seasoned IC chair will
turn to this page, read the verdict, the one-liner and the KPI table,
and form a provisional view in under 60 seconds.

Per 2026 IC memo standard (docs/competitive/ic_memo_standard_2026.md §1):
  - verdict: GO / CAUTION / NO-GO
  - one-liner: project name, tech, MW, location, ticket
  - KPI table (4 rows): capacity MW, IRR, NPV, risk rating
"""
from __future__ import annotations

from typing import Any


def _risk_rating(top_risks: list[dict[str, Any]] | None) -> tuple[str, str]:
    """Aggregate top-5 risk max(likelihood * impact) → RAG.

    Returns (label, rag) where rag ∈ {"green", "amber", "red"}.
    """
    if not top_risks:
        return ("Amber — baseline default", "amber")
    scores = [
        (r.get("likelihood", 3) or 3) * (r.get("impact", 3) or 3)
        for r in top_risks[:5]
    ]
    peak = max(scores) if scores else 9
    if peak >= 20:
        return (f"Red — peak L×I {peak}", "red")
    if peak >= 12:
        return (f"Amber — peak L×I {peak}", "amber")
    return (f"Green — peak L×I {peak}", "green")


def _verdict_variant(verdict: str) -> str:
    v = (verdict or "CAUTION").upper().replace("_", "-").replace(" ", "-")
    if v == "GO":
        return "go"
    if v in ("NO-GO", "NOGO"):
        return "nogo"
    return "caution"


def build_recommendation_box(
    proj: dict[str, Any],
    fin: dict[str, Any],
    verdict: str,
    ticket_gbp_m: float,
    hold_years: int,
    risks: list[dict[str, Any]] | None = None,
    vote_ask: str | None = None,
) -> dict[str, Any]:
    """Build the page-1 recommendation box.

    proj expected keys: name, workload or technology, capacity_mw, region,
                        lat, lon.
    fin expected keys: p50_irr, npv_gbp_m (or npv_m), equity_irr_pct
                       (optional), moic.
    """
    name = proj.get("name", "Untitled Project")
    tech = (proj.get("workload") or proj.get("technology") or "asset").title()
    capacity_mw = proj.get("capacity_mw") or 0
    region = proj.get("region") or "UK"

    risk_label, risk_rag = _risk_rating(risks)

    one_liner = (
        f"{name} — {capacity_mw:.0f} MW {tech} in {region}. "
        f"Sponsor ticket £{ticket_gbp_m:.1f}m; hold {hold_years} years; "
        f"verdict {verdict}."
    )

    # Numbers (IC expects the 4 headline KPIs)
    p50_irr = fin.get("p50_irr") or fin.get("equity_irr_pct")
    npv_m = fin.get("npv_gbp_m") or fin.get("npv_m")
    if npv_m is None and fin.get("npv_gbp"):
        npv_m = fin["npv_gbp"] / 1_000_000
    moic = fin.get("moic") or fin.get("equity_multiple")

    kpis = [
        {"label": "Capacity", "value": f"{capacity_mw:.0f} MW",
         "sub": f"{tech} · {region}"},
        {"label": "P50 equity IRR",
         "value": (f"{p50_irr:.1f}%" if p50_irr is not None else "—"),
         "sub": "post-tax, levered"},
        {"label": "Equity NPV @ WACC",
         "value": (f"£{npv_m:.1f}m" if npv_m is not None else "—"),
         "sub": (f"MOIC {moic:.2f}x" if moic else "MOIC pending")},
        {"label": "Risk rating",
         "value": risk_label,
         "sub": f"top-5 residual · {risk_rag.upper()}"},
    ]

    return {
        "available": True,
        "verdict": verdict,
        "verdict_variant": _verdict_variant(verdict),
        "one_liner": one_liner,
        "ticket_gbp_m": ticket_gbp_m,
        "hold_years": hold_years,
        "vote_ask": vote_ask or (
            f"Approve sponsor equity commitment of £{ticket_gbp_m:.1f}m "
            f"for {hold_years}-year hold, subject to the CPs at §6."
        ),
        "kpis": kpis,
        "risk_rag": risk_rag,
        "risk_label": risk_label,
        "citation": (
            "IC memo recommendation box — 2026 standard "
            "(see docs/competitive/ic_memo_standard_2026.md §1)."
        ),
    }

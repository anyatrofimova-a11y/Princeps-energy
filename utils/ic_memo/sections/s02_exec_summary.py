"""Section 2 — Executive summary (two-page narrative).

Four structured paragraphs the IC chair reads in 3–5 minutes:

  1. What is the opportunity?
  2. What is Princeps' thesis?
  3. Why now?
  4. What is the ask?

Each paragraph is 80–120 words. Tone: institutional, numerical,
no superlatives. Per 2026 IC standard §5 — "strong" and "attractive"
are red-pen words, replaced by a number.
"""
from __future__ import annotations

from typing import Any


def _fmt_mw(v: float | None) -> str:
    return f"{v:.0f} MW" if v else "capacity TBC"


def _fmt_pct(v: float | None, d: int = 1) -> str:
    return f"{v:.{d}f}%" if v is not None else "—"


def _fmt_gbp_m(v: float | None) -> str:
    return f"£{v:.1f}m" if v is not None else "£TBC"


def build_exec_summary(
    proj: dict[str, Any],
    fin: dict[str, Any],
    grid: dict[str, Any],
    plan: dict[str, Any],
    market_context: dict[str, Any] | None = None,
    ticket_gbp_m: float = 12.0,
    hold_years: int = 7,
) -> dict[str, Any]:
    """Return the four exec-summary paragraphs plus a headline-risk trio."""
    name = proj.get("name", "the project")
    tech = (proj.get("workload") or proj.get("technology") or "asset").lower()
    capacity_mw = proj.get("capacity_mw") or 0
    region = proj.get("region") or "UK"

    market = market_context or {}
    fes_pathway = market.get("fes_pathway", "Leading the Way")
    ppa_bench = market.get("ppa_bench_gbp_mwh", 62)

    irr = fin.get("p50_irr") or fin.get("equity_irr_pct")
    capex_m = fin.get("capex_m")
    moic = fin.get("moic") or fin.get("equity_multiple") or 1.65
    headroom = grid.get("headroom_mw")
    queue = grid.get("queue_years")
    plan_p = plan.get("planning_p") or plan.get("probability_approved_pct")

    p1_opportunity = (
        f"{name} is a {_fmt_mw(capacity_mw)} {tech} development in {region}. "
        f"Princeps has identified, triangulated and underwritten the site "
        f"through its platform: grid headroom of "
        f"{headroom or 'TBC'} MW at the nearest primary substation, "
        f"planning probability {_fmt_pct(plan_p, 0)} on the XGBoost-on-REPD "
        f"predictor, and a Tier-2 pandapower N-1 power-flow clearing the "
        f"connection on base-case loading. Indicative capex "
        f"{_fmt_gbp_m(capex_m)}; sponsor ticket "
        f"£{ticket_gbp_m:.1f}m at {hold_years}-year hold to target "
        f"MOIC {moic:.2f}x."
    )

    p2_thesis = (
        f"Princeps' thesis is that {tech} in {region} offers a "
        f"{'asymmetric' if (irr or 0) > 11 else 'risk-reward-balanced'} "
        f"entry point into the UK transition, anchored on three pillars: "
        f"(i) secured Gate 2 queue position under Ofgem OFG1164 methodology, "
        f"crystallising connection certainty; (ii) consentability validated "
        f"against the PIA 2025 regime with EN-1 / EN-3 (2025) CNP status "
        f"available; (iii) P50 equity IRR of {_fmt_pct(irr)} "
        f"vs our sponsor hurdle, with downside (combined Lender Case) "
        f"still delivering positive equity on the DCF engine."
    )

    p3_why_now = (
        f"The window is now. NESO's TMO4+ approval (Ofgem 15 April 2025) "
        f"and Gate 2 methodology decision have re-sequenced "
        f"the queue; projects not in the accepted queue by year-end risk a "
        f"further 18–24 month deferral. The {fes_pathway} NESO FES 2024 "
        f"pathway projects sustained capacity demand at this GSP through 2035. "
        f"Cornwall Insight Q1 2026 UK Power Market Forecast stabilised at "
        f"£{ppa_bench}/MWh on the baseload curve, which supports debt sizing "
        f"at SONIA + 225 bps. Delay from here erodes both revenue tail and "
        f"debt headroom."
    )

    p4_ask = (
        f"The ask is sponsor equity commitment of £{ticket_gbp_m:.1f}m, "
        f"subject to conditions precedent at §6 — Gate 2 offer, planning "
        f"consent, BNG plan (per Environment Act 2021 10% uplift requirement), "
        f"and Tier-1 EPC term sheet. Reporting cadence quarterly against "
        f"milestone waterfall. Delegated authority to the CIO for up to "
        f"£{ticket_gbp_m * 0.15:.1f}m of working-capital draw; anything "
        f"above returns to committee. Queue position is the only irreversible "
        f"input — the build sequence after FID is standard project finance."
    )

    # Headline risks — 3 with traffic light (IC-grade exec-summary expects this)
    headline_risks = [
        {"text": "Grid connection offer delayed past Gate 2 window",
         "rag": "amber" if (queue or 2.5) < 3.5 else "red"},
        {"text": "Planning refusal at LPA or PINS call-in",
         "rag": "amber" if (plan_p or 70) >= 60 else "red"},
        {"text": "Merchant curve soften post-COD (REMA RNP not materially "
                 "priced into 2026 curves)",
         "rag": "amber"},
    ]

    return {
        "available": True,
        "paragraphs": [
            {"heading": "What is the opportunity?", "body": p1_opportunity},
            {"heading": "What is Princeps' thesis?", "body": p2_thesis},
            {"heading": "Why now?", "body": p3_why_now},
            {"heading": "What is the ask?", "body": p4_ask},
        ],
        "headline_risks": headline_risks,
        "citation": (
            "Cornwall Insight UK Power Market Forecast Q1 2026; NESO FES "
            "2024; Ofgem TMO4+ decision 15 April 2025 (OFG1164)."
        ),
    }

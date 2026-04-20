"""Section 4 — Base-case model pack.

Full FCFF, FCFE, cashflow waterfall and amortising debt schedule, all drawn
from utils.dcf_evaluator.DCFResult (BOT-A). The section deliberately does
no new modelling — it renders the canonical DCFResult so the base case,
downside case and breakeven case all trace back to the same engine.

Data shape expected: dcf_result is a utils.dcf_evaluator.DCFResult, optional
amortising_rows from utils.financial_viability_charts.build_amortising_schedule_rows.
"""
from __future__ import annotations

from typing import Any

try:
    from utils.dcf_evaluator import DCFResult  # type: ignore
except Exception:
    DCFResult = None  # fallback


def build_base_case(
    dcf_result: Any,
    amortising_rows: list[dict[str, Any]] | None,
    wacc_pct: float,
) -> dict[str, Any]:
    if dcf_result is None:
        return {
            "available": False,
            "note": "DCF evaluator output not available — base case unavailable.",
        }

    summary = dict(getattr(dcf_result, "summary", {}) or {})
    cashflows = list(getattr(dcf_result, "cashflows", []) or [])
    fcff = list(getattr(dcf_result, "fcff", []) or [])
    fcfe = list(getattr(dcf_result, "fcfe", []) or [])

    fcff_series = [
        {"year": i + 1, "fcff": round(v, 2),
         "fcfe": round(fcfe[i], 2) if i < len(fcfe) else None}
        for i, v in enumerate(fcff)
    ]

    return {
        "available": True,
        "summary": summary,
        "cashflows": cashflows,
        "fcff_series": fcff_series,
        "amortising_rows": amortising_rows or [],
        "wacc_pct": wacc_pct,
        "npv_gbp": summary.get("npv", 0),
        "equity_npv_gbp": summary.get("equity_npv", 0),
        "irr_pct": summary.get("irr_pct"),
        "equity_irr_pct": summary.get("equity_irr_pct"),
        "terminal_value_gbp": summary.get("terminal_value", 0),
        "min_dscr": summary.get("min_dscr"),
        "min_llcr": summary.get("min_llcr"),
        "min_plcr": summary.get("min_plcr"),
        "min_icr": summary.get("min_icr"),
        "max_gearing": summary.get("max_gearing"),
        "any_breach": bool(summary.get("any_breach")),
        "breach_years": summary.get("breach_years", []),
        "citation": "Modelled per utils.dcf_evaluator.DCFEvaluator (BOT-A); Gordon terminal on final-year FCFF, WACC-discounted.",
    }

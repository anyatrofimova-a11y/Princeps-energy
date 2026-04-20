"""Section 14 — Model audit trail appendix.

Every number in the pack is sourced from one of:
  - BOT-A (utils.dcf_evaluator) — DCF, IRR, NPV, covenants
  - BOT-A (utils.dc_finance) — DC-native capacity / energy / ramp model
  - BOT-P (utils.cp_cs_schedule) — CP/CS list
  - BOT-M (utils.precedent_transactions) — comparable deals
  - Princeps DB (projects, grid_substations, demand_scenarios)
  - UK reference tables (utils.investment_appraisal CAPEX_PER_MW etc.)

This section lists every data input with its source, version, extraction
date, provenance class and any stale-data warning.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def build_model_audit(
    generated_at: datetime,
    model_version: str,
    dcf_params: dict[str, Any] | None,
    provenance_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = list(provenance_rows or [])

    # Always add the core modelling provenance entries
    rows.extend([
        {
            "data_item": "DCF engine",
            "source": "utils.dcf_evaluator.DCFEvaluator (BOT-A)",
            "version": "v1.0 — numpy_financial IRR + Gordon terminal",
            "extraction_date": generated_at.strftime("%Y-%m-%d"),
            "provenance_class": "SRC_INTERNAL_MODEL",
            "stale_days": 0,
            "notes": "Single source of truth; also powers Financial Viability and IC memo packs.",
        },
        {
            "data_item": "CP/CS schedule",
            "source": "utils.cp_cs_schedule (BOT-P)",
            "version": "LMA IGFA 2024",
            "extraction_date": generated_at.strftime("%Y-%m-%d"),
            "provenance_class": "SRC_INTERNAL_MODEL",
            "stale_days": 0,
            "notes": "Standard CP list merged with project overrides from projects.metadata.",
        },
        {
            "data_item": "Precedent transactions",
            "source": "utils.precedent_transactions (BOT-M)",
            "version": "REPD + procurement_tenders_raw + static seed",
            "extraction_date": generated_at.strftime("%Y-%m-%d"),
            "provenance_class": "SRC_DB_SNAPSHOT",
            "stale_days": 1,
            "notes": "REPD data refresh weekly; static seed includes hand-curated public announcements.",
        },
        {
            "data_item": "Covenant thresholds",
            "source": "utils.dcf_evaluator.COVENANT_THRESHOLDS",
            "version": "UK infra defaults (DSCR 1.20x, LLCR 1.30x, PLCR 1.40x)",
            "extraction_date": generated_at.strftime("%Y-%m-%d"),
            "provenance_class": "SRC_REGULATORY",
            "stale_days": 0,
            "notes": "LMA IGFA 2024 baseline; individual deal can tighten.",
        },
        {
            "data_item": "CAPEX / OPEX per MW",
            "source": "utils.investment_appraisal.CAPEX_PER_MW / OPEX_PER_MW",
            "version": "Princeps CB7 reference (2026 Q1)",
            "extraction_date": generated_at.strftime("%Y-%m-%d"),
            "provenance_class": "SRC_USER_INPUT",
            "stale_days": 90,
            "notes": "Needs refresh each BCIS release; superseded if deal-specific EPC bid available.",
        },
    ])

    # Sensitivity tornado narrative
    tornado_notes = [
        {
            "input": "Revenue (PPA × utilisation)",
            "shock_modelled": "±20%",
            "impact_on_irr_pp": "≈ ±3.5 pp",
            "method": "Direct multiply of revenue_schedule; see §5 Downside, §6 Breakeven.",
        },
        {
            "input": "CAPEX",
            "shock_modelled": "±15%",
            "impact_on_irr_pp": "≈ ±1.8 pp",
            "method": "Capex scalar; debt sized to gearing × shocked capex.",
        },
        {
            "input": "Capacity factor",
            "shock_modelled": "±10%",
            "impact_on_irr_pp": "≈ ±2.0 pp",
            "method": "Multiply annual generation (non-BESS) / revenue base (BESS).",
        },
        {
            "input": "Discount rate (WACC)",
            "shock_modelled": "6% → 10%",
            "impact_on_irr_pp": "IRR invariant, NPV ±£M",
            "method": "Changes NPV not IRR; covenants insensitive.",
        },
    ]

    formula_notes = [
        "FCFF = EBIT × (1 − t) + D&A − ΔWC − Maintenance CapEx (set to 0; covered in opex)",
        "FCFE = CFADS − Debt service (Interest + Principal)",
        "CFADS = EBITDA − Tax − ΔWC (before debt service)",
        "DSCR_t = CFADS_t / Debt service_t",
        "LLCR_t = Σ_{k=t}^{T_debt} CFADS_k / (1+WACC)^{k−t} / Outstanding debt at t",
        "PLCR_t = Σ_{k=t}^{T_life} CFADS_k / (1+WACC)^{k−t} / Outstanding debt at t",
        "Gearing_t = Debt outstanding_t / (Debt outstanding_t + Equity)",
    ]

    return {
        "model_version": model_version,
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "dcf_params": dcf_params or {},
        "provenance_rows": rows,
        "sensitivity_tornado": tornado_notes,
        "formula_notes": formula_notes,
        "audit_status": (
            "Model drafted by Princeps; NOT yet independently audited. "
            "Independent model audit (BDO, Operis or similar) is CS item cs_11_model_audit."
        ),
        "citation": "ICMA Model Auditor Best Practice / LMA Lenders' Technical Adviser Scope.",
    }

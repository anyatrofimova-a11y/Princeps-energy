"""Section 7 — Covenant package.

LMA-standard covenant package with cure-right language. Draws P50
thresholds from the BOT-A DCF engine (COVENANT_THRESHOLDS) and
overlays the standard project-finance cure-right mechanics
(equity cure, remedy period, lock-up triggers).
"""
from __future__ import annotations

from typing import Any

try:
    from utils.dcf_evaluator import COVENANT_THRESHOLDS  # type: ignore
except Exception:
    COVENANT_THRESHOLDS = {
        "dscr_min": 1.20, "llcr_min": 1.30, "plcr_min": 1.40,
        "icr_min": 2.00, "gearing_max": 0.75,
    }


def build_covenant_package(
    base_case_summary: dict[str, Any] | None,
    downside_case_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    base = base_case_summary or {}
    down = downside_case_summary or {}

    rows = [
        {
            "covenant": "Debt Service Coverage Ratio (DSCR)",
            "formula": "CFADS / (Principal + Interest)",
            "covenant_level": f"≥ {COVENANT_THRESHOLDS['dscr_min']:.2f}x P50; ≥ 1.10x P90",
            "base_case": _fmt_x(base.get("min_dscr")),
            "downside": _fmt_x(down.get("min_dscr")),
            "lock_up": "1.15x (no dividends / subordinated interest)",
            "default": "1.05x after cure period",
            "lma_ref": "LMA IGFA 2024 §24.5 (Financial Covenants — DSCR)",
        },
        {
            "covenant": "Loan Life Coverage Ratio (LLCR)",
            "formula": "PV(CFADS to maturity, WACC) / Outstanding debt",
            "covenant_level": f"≥ {COVENANT_THRESHOLDS['llcr_min']:.2f}x",
            "base_case": _fmt_x(base.get("min_llcr")),
            "downside": _fmt_x(down.get("min_llcr")),
            "lock_up": "1.20x",
            "default": "1.10x",
            "lma_ref": "LMA IGFA 2024 §24.5 (LLCR)",
        },
        {
            "covenant": "Project Life Coverage Ratio (PLCR)",
            "formula": "PV(CFADS to project end, WACC) / Outstanding debt",
            "covenant_level": f"≥ {COVENANT_THRESHOLDS['plcr_min']:.2f}x",
            "base_case": _fmt_x(base.get("min_plcr")),
            "downside": _fmt_x(down.get("min_plcr") or base.get("min_plcr")),
            "lock_up": "1.30x",
            "default": "1.15x",
            "lma_ref": "LMA IGFA 2024 §24.5 (PLCR)",
        },
        {
            "covenant": "Interest Coverage Ratio (ICR)",
            "formula": "EBITDA / Interest",
            "covenant_level": f"≥ {COVENANT_THRESHOLDS['icr_min']:.2f}x",
            "base_case": _fmt_x(base.get("min_icr")),
            "downside": _fmt_x(down.get("min_icr")),
            "lock_up": "2.25x",
            "default": "1.50x",
            "lma_ref": "LMA IGFA 2024 §24.5 (ICR)",
        },
        {
            "covenant": "Maximum Gearing",
            "formula": "Debt outstanding / (Debt + Equity)",
            "covenant_level": f"≤ {COVENANT_THRESHOLDS['gearing_max']*100:.0f}%",
            "base_case": _fmt_pct(base.get("max_gearing")),
            "downside": _fmt_pct(down.get("max_gearing") if down else None),
            "lock_up": "72.5%",
            "default": "78%",
            "lma_ref": "LMA IGFA 2024 §24.6 (Gearing)",
        },
        {
            "covenant": "Debt Service Reserve Account (DSRA)",
            "formula": "6 months' debt service, cash or LC",
            "covenant_level": "Funded at close; top up within 30 days of draw",
            "base_case": "Funded",
            "downside": "Funded — drawn under stress",
            "lock_up": "< 3 months ⇒ distribution lock",
            "default": "Not funded ⇒ event of default",
            "lma_ref": "LMA IGFA 2024 §23.1 (Reserve Accounts)",
        },
    ]

    cure_rights = [
        "Equity cure — sponsor may cure a covenant breach by injecting subordinated debt or equity within 20 Business Days, up to 2 cures per trailing 4 quarters, maximum 4 over life of facility (LMA §24.7).",
        "Remedy period — 30 calendar days for information covenants, 10 Business Days for payment defaults, immediate acceleration for material misrepresentation (LMA §25).",
        "Distribution lock-up — no distributions, management fees or subordinated interest while Lock-up Levels breached (LMA §26.3).",
        "Reserving — Cash Sweep to DSRA until DSCR back above 1.25x for 2 consecutive test dates.",
    ]

    operating_covenants = [
        "Maintain all Project Documents (EPC, O&M, PPA, Connection Agreement) in full force.",
        "No change of control, merger, or disposal > 5% of capex without Majority Lender consent.",
        "No incremental indebtedness beyond £5m or 2% of facility without consent.",
        "Insurances maintained on a broker-certified basis; annual broker letter to Agent.",
        "Environmental and health & safety compliance per CDM 2015 and EA permits (reg. change allowance capped at £2m pa).",
    ]

    information_covenants = [
        "Quarterly management accounts + compliance certificate (within 45 days of quarter end).",
        "Annual audited accounts within 120 days of year end.",
        "Annual base-case model re-run (banking case) within 90 days of COD anniversary.",
        "Construction-phase monthly progress report from Lenders' Technical Adviser (LTA).",
        "Notice within 5 Business Days of any litigation > £500k, permit revocation, change of law.",
    ]

    return {
        "rows": rows,
        "cure_rights": cure_rights,
        "operating_covenants": operating_covenants,
        "information_covenants": information_covenants,
        "thresholds": dict(COVENANT_THRESHOLDS),
        "citation": "LMA Investment Grade Facility Agreement 2024 §§23–26.",
    }


def _fmt_x(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f}x"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"

"""DCFEvaluator — reusable DCF + lender-covenant engine.

Inputs: capex, opex/revenue schedules, tax, WACC, terminal growth, debt schedule.
Outputs: NPV (Gordon terminal), IRR (numpy_financial or bisection), FCFF/FCFE,
equity NPV, and full covenant timeline (DSCR, LLCR, PLCR, ICR, gearing).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    import numpy_financial as _npf  # type: ignore
    _HAS_NPF = True
except ImportError:
    _HAS_NPF = False


# Lender thresholds (UK infra defaults)
COVENANT_THRESHOLDS = {
    "dscr_min":   1.20,
    "llcr_min":   1.30,
    "plcr_min":   1.40,
    "icr_min":    2.00,
    "gearing_max": 0.75,
}


@dataclass
class DebtYear:
    year: int
    opening_balance: float
    interest: float
    principal: float
    closing_balance: float

    @property
    def debt_service(self) -> float:
        return self.interest + self.principal


@dataclass
class DCFResult:
    npv: float
    equity_npv: float
    irr: float | None
    equity_irr: float | None
    fcff: list[float]
    fcfe: list[float]
    terminal_value: float
    covenants: list[dict[str, Any]]
    summary: dict[str, Any]
    cashflows: list[dict[str, Any]] = field(default_factory=list)


def _bisection_irr(cashflows: list[float], lo: float = -0.95, hi: float = 5.0, iters: int = 80) -> float | None:
    """IRR via bisection. cashflows[0] is t=0 outflow (negative)."""
    def npv_at(r: float) -> float:
        return sum(cf / ((1 + r) ** t) for t, cf in enumerate(cashflows))
    f_lo, f_hi = npv_at(lo), npv_at(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(iters):
        mid = (lo + hi) / 2
        f_mid = npv_at(mid)
        if abs(f_mid) < 1e-3:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def _irr(cashflows: list[float]) -> float | None:
    if not cashflows or all(c == 0 for c in cashflows):
        return None
    if _HAS_NPF:
        try:
            v = float(_npf.irr(cashflows))
            if v != v:  # NaN
                return _bisection_irr(cashflows)
            return v
        except Exception:
            return _bisection_irr(cashflows)
    return _bisection_irr(cashflows)


def _pv(values: list[float], rate: float, start_t: int = 1) -> float:
    return sum(v / ((1 + rate) ** (start_t + i)) for i, v in enumerate(values))


def build_amortising_debt(principal: float, rate: float, term_years: int, life_years: int) -> list[DebtYear]:
    """Level-payment (annuity) amortisation, zero-padded to life_years."""
    schedule: list[DebtYear] = []
    if principal <= 0 or term_years <= 0:
        return [DebtYear(y, 0, 0, 0, 0) for y in range(1, life_years + 1)]
    bal = principal
    if rate > 0:
        annuity = principal * rate / (1 - (1 + rate) ** -term_years)
    else:
        annuity = principal / term_years
    for y in range(1, life_years + 1):
        if y <= term_years and bal > 0.01:
            interest = bal * rate
            principal_pmt = min(annuity - interest, bal)
            closing = bal - principal_pmt
            schedule.append(DebtYear(y, bal, interest, principal_pmt, closing))
            bal = closing
        else:
            schedule.append(DebtYear(y, 0, 0, 0, 0))
    return schedule


class DCFEvaluator:
    """Project finance DCF + covenant evaluator.

    revenue_schedule / opex_schedule / debt_schedule indexed 0..life-1 (year 1..life).
    """

    def __init__(
        self,
        capex: float,
        revenue_schedule: list[float],
        opex_schedule: list[float],
        tax_rate: float = 0.25,
        wacc: float = 0.08,
        cost_of_equity: float | None = None,
        terminal_growth: float = 0.0,
        debt_schedule: list[DebtYear] | None = None,
        equity: float | None = None,
        depreciation_schedule: list[float] | None = None,
        working_capital_schedule: list[float] | None = None,
        thresholds: dict[str, float] | None = None,
    ) -> None:
        self.capex = float(capex)
        self.revenue = list(revenue_schedule)
        self.opex = list(opex_schedule)
        if len(self.opex) != len(self.revenue):
            raise ValueError("revenue_schedule and opex_schedule must be same length")
        self.life = len(self.revenue)
        self.tax_rate = tax_rate
        self.wacc = wacc
        self.cost_of_equity = cost_of_equity if cost_of_equity is not None else max(wacc, 0.10)
        self.terminal_growth = terminal_growth
        self.debt = debt_schedule or [DebtYear(y, 0, 0, 0, 0) for y in range(1, self.life + 1)]
        if len(self.debt) < self.life:
            self.debt = self.debt + [DebtYear(y, 0, 0, 0, 0) for y in range(len(self.debt) + 1, self.life + 1)]
        total_debt0 = self.debt[0].opening_balance if self.debt else 0
        self.equity = equity if equity is not None else max(self.capex - total_debt0, 0)
        self.depr = depreciation_schedule or [self.capex / self.life] * self.life
        if len(self.depr) < self.life:
            self.depr = self.depr + [0] * (self.life - len(self.depr))
        self.wc = working_capital_schedule or [0.0] * self.life
        if len(self.wc) < self.life:
            self.wc = self.wc + [0.0] * (self.life - len(self.wc))
        self.thresholds = {**COVENANT_THRESHOLDS, **(thresholds or {})}

    # ── cashflow mechanics ────────────────────────────────────────────────
    def _ebitda(self, y: int) -> float:
        return self.revenue[y] - self.opex[y]

    def _ebit(self, y: int) -> float:
        return self._ebitda(y) - self.depr[y]

    def _tax(self, y: int) -> float:
        ebit = self._ebit(y)
        interest = self.debt[y].interest
        taxable = max(0.0, ebit - interest)
        return taxable * self.tax_rate

    def _fcff_year(self, y: int) -> float:
        # EBIT*(1-t) + D&A - CapEx_maint - ΔWC. Assume capex is upfront only.
        ebit = self._ebit(y)
        nopat = ebit * (1 - self.tax_rate)
        return nopat + self.depr[y] - self.wc[y]

    def _cfads_year(self, y: int) -> float:
        """CFADS = EBITDA - tax - ΔWC (before debt service)."""
        return self._ebitda(y) - self._tax(y) - self.wc[y]

    def _fcfe_year(self, y: int) -> float:
        d = self.debt[y]
        return self._cfads_year(y) - d.debt_service

    # ── covenants ─────────────────────────────────────────────────────────
    def _covenant_row(self, y: int) -> dict[str, Any]:
        d = self.debt[y]
        cfads = self._cfads_year(y)
        ebitda = self._ebitda(y)
        ds = d.debt_service
        dscr = (cfads / ds) if ds > 0 else None
        icr = (ebitda / d.interest) if d.interest > 0 else None
        outstanding = d.opening_balance
        # LLCR: PV(remaining CFADS through debt maturity) / outstanding debt
        remaining_cfads = [self._cfads_year(k) for k in range(y, self.life) if self.debt[k].debt_service > 0 or self.debt[k].opening_balance > 0]
        llcr = (_pv(remaining_cfads, self.wacc, start_t=1) / outstanding) if outstanding > 0 and remaining_cfads else None
        # PLCR: PV(CFADS through project life) / outstanding
        project_cfads = [self._cfads_year(k) for k in range(y, self.life)]
        plcr = (_pv(project_cfads, self.wacc, start_t=1) / outstanding) if outstanding > 0 and project_cfads else None
        equity_bal = max(self.equity, 1e-6)
        gearing = outstanding / (outstanding + equity_bal) if outstanding > 0 else 0.0
        th = self.thresholds
        breaches = []
        if dscr is not None and dscr < th["dscr_min"]:
            breaches.append("DSCR")
        if llcr is not None and llcr < th["llcr_min"]:
            breaches.append("LLCR")
        if plcr is not None and plcr < th["plcr_min"]:
            breaches.append("PLCR")
        if icr is not None and icr < th["icr_min"]:
            breaches.append("ICR")
        if gearing > th["gearing_max"]:
            breaches.append("Gearing")
        return {
            "year": y + 1,
            "cfads": round(cfads, 2),
            "debt_service": round(ds, 2),
            "interest": round(d.interest, 2),
            "principal": round(d.principal, 2),
            "debt_outstanding": round(outstanding, 2),
            "dscr": round(dscr, 3) if dscr is not None else None,
            "llcr": round(llcr, 3) if llcr is not None else None,
            "plcr": round(plcr, 3) if plcr is not None else None,
            "icr": round(icr, 3) if icr is not None else None,
            "gearing": round(gearing, 4),
            "breaches": breaches,
            "status": "breach" if breaches else "ok",
        }

    # ── evaluate ──────────────────────────────────────────────────────────
    def evaluate(self) -> DCFResult:
        fcff_series = [self._fcff_year(y) for y in range(self.life)]
        fcfe_series = [self._fcfe_year(y) for y in range(self.life)]
        cashflows_detail = []
        for y in range(self.life):
            d = self.debt[y]
            cashflows_detail.append({
                "year": y + 1,
                "revenue": round(self.revenue[y], 2),
                "opex": round(self.opex[y], 2),
                "ebitda": round(self._ebitda(y), 2),
                "depreciation": round(self.depr[y], 2),
                "ebit": round(self._ebit(y), 2),
                "interest": round(d.interest, 2),
                "tax": round(self._tax(y), 2),
                "cfads": round(self._cfads_year(y), 2),
                "debt_service": round(d.debt_service, 2),
                "fcff": round(fcff_series[y], 2),
                "fcfe": round(fcfe_series[y], 2),
            })

        # Terminal value — Gordon growth on final-year FCFF
        if self.wacc > self.terminal_growth:
            tv = fcff_series[-1] * (1 + self.terminal_growth) / (self.wacc - self.terminal_growth)
        else:
            tv = 0.0
        tv_pv = tv / ((1 + self.wacc) ** self.life)

        # NPV (firm) — WACC-discounted FCFF + terminal
        npv = -self.capex + _pv(fcff_series, self.wacc) + tv_pv

        # Equity NPV — Ke-discounted FCFE
        equity_npv = -self.equity + _pv(fcfe_series, self.cost_of_equity)

        # IRR (firm on unlevered): -capex, fcff1..fcffN + tv in final year
        fcff_with_tv = list(fcff_series)
        fcff_with_tv[-1] = fcff_with_tv[-1] + tv
        irr_val = _irr([-self.capex] + fcff_with_tv)

        # Equity IRR: -equity, fcfe1..fcfeN
        equity_irr = _irr([-self.equity] + fcfe_series)

        # Covenant timeline
        covenants = [self._covenant_row(y) for y in range(self.life)]

        # Summary
        dscrs = [c["dscr"] for c in covenants if c["dscr"] is not None]
        llcrs = [c["llcr"] for c in covenants if c["llcr"] is not None]
        plcrs = [c["plcr"] for c in covenants if c["plcr"] is not None]
        icrs = [c["icr"] for c in covenants if c["icr"] is not None]
        any_breach = any(c["breaches"] for c in covenants)
        summary = {
            "npv": round(npv, 2),
            "equity_npv": round(equity_npv, 2),
            "irr_pct": round(irr_val * 100, 3) if irr_val is not None else None,
            "equity_irr_pct": round(equity_irr * 100, 3) if equity_irr is not None else None,
            "wacc_pct": round(self.wacc * 100, 3),
            "cost_of_equity_pct": round(self.cost_of_equity * 100, 3),
            "terminal_value": round(tv, 2),
            "terminal_value_pv": round(tv_pv, 2),
            "capex": round(self.capex, 2),
            "equity": round(self.equity, 2),
            "life_years": self.life,
            "min_dscr": round(min(dscrs), 3) if dscrs else None,
            "min_llcr": round(min(llcrs), 3) if llcrs else None,
            "min_plcr": round(min(plcrs), 3) if plcrs else None,
            "min_icr": round(min(icrs), 3) if icrs else None,
            "max_gearing": round(max((c["gearing"] for c in covenants), default=0.0), 4),
            "any_breach": any_breach,
            "breach_years": [c["year"] for c in covenants if c["breaches"]],
            "thresholds": self.thresholds,
            "uses_numpy_financial": _HAS_NPF,
        }

        return DCFResult(
            npv=npv,
            equity_npv=equity_npv,
            irr=irr_val,
            equity_irr=equity_irr,
            fcff=fcff_series,
            fcfe=fcfe_series,
            terminal_value=tv,
            covenants=covenants,
            summary=summary,
            cashflows=cashflows_detail,
        )

    def to_dict(self) -> dict[str, Any]:
        r = self.evaluate()
        return {
            "summary": r.summary,
            "covenants": r.covenants,
            "cashflows": r.cashflows,
            "fcff": [round(v, 2) for v in r.fcff],
            "fcfe": [round(v, 2) for v in r.fcfe],
            "terminal_value": round(r.terminal_value, 2),
            "npv": round(r.npv, 2),
            "equity_npv": round(r.equity_npv, 2),
            "irr_pct": round(r.irr * 100, 3) if r.irr is not None else None,
            "equity_irr_pct": round(r.equity_irr * 100, 3) if r.equity_irr is not None else None,
        }


def evaluate_from_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """Construct a DCFEvaluator from a JSON-friendly payload + evaluate."""
    capex = float(payload["capex"])
    revenue = [float(x) for x in payload["revenue_schedule"]]
    opex = [float(x) for x in payload["opex_schedule"]]
    tax_rate = float(payload.get("tax_rate", 0.25))
    wacc = float(payload.get("wacc", 0.08))
    cost_of_equity = payload.get("cost_of_equity")
    terminal_growth = float(payload.get("terminal_growth", 0.0))
    equity = payload.get("equity")
    thresholds = payload.get("thresholds")
    depr = payload.get("depreciation_schedule")
    wc = payload.get("working_capital_schedule")

    debt_payload = payload.get("debt_schedule")
    debt_schedule: list[DebtYear] | None = None
    if isinstance(debt_payload, list) and debt_payload and isinstance(debt_payload[0], dict):
        debt_schedule = [
            DebtYear(
                year=int(d["year"]),
                opening_balance=float(d.get("opening_balance", 0)),
                interest=float(d.get("interest", 0)),
                principal=float(d.get("principal", 0)),
                closing_balance=float(d.get("closing_balance", 0)),
            ) for d in debt_payload
        ]
    elif isinstance(debt_payload, dict):
        debt_schedule = build_amortising_debt(
            principal=float(debt_payload.get("principal", 0)),
            rate=float(debt_payload.get("rate", 0.06)),
            term_years=int(debt_payload.get("term_years", len(revenue))),
            life_years=len(revenue),
        )

    ev = DCFEvaluator(
        capex=capex,
        revenue_schedule=revenue,
        opex_schedule=opex,
        tax_rate=tax_rate,
        wacc=wacc,
        cost_of_equity=float(cost_of_equity) if cost_of_equity is not None else None,
        terminal_growth=terminal_growth,
        debt_schedule=debt_schedule,
        equity=float(equity) if equity is not None else None,
        depreciation_schedule=depr,
        working_capital_schedule=wc,
        thresholds=thresholds,
    )
    return ev.to_dict()

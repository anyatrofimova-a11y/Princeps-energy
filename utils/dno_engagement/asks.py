"""
utils.dno_engagement.asks — rule-based inference of DNO asks.

Reads the composed pack payload (constraint envelope + headroom +
reinforcement status + reactive offer + mitigation stack) and generates
a prioritised list of ``Ask`` items — specific things the pack author
wants the DNO to confirm, commit to, or co-design.

Rules are conservative — they only raise an ask when the data supports
one. The Claude orchestrator can supplement with bespoke narrative but
must not invent asks outside this rule base.

Cited per ask:
  * ENA EREC G99 Issue 2 — protection settings, FRT envelope, synchronised
    gen compliance.
  * ENA EREC P28/P29 — voltage & unbalance headroom.
  * CCCM v19 Sch.1 — sole/shared use classification, security deposit.
  * Distribution Code DPC4, DPC9 — ancillary service, islanding.
  * Ofgem RIIO-ED2 — incentive windows & reinforcement schedules.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Ask:
    """A single ask the pack makes of the DNO."""

    id: str                      # stable short id
    title: str                   # one-line question
    priority: str                # "P1" | "P2" | "P3"
    category: str                # capacity / reactive / protection / commercial / schedule
    body: str                    # full paragraph for the pack
    citation: str                # canonical EREC / code reference
    requested_by: str = "pack"   # "pack" | "user"
    decision_sla_days: int = 30  # how long the pack is giving the DNO

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rule base — each rule returns 0 or 1 Ask.
# ---------------------------------------------------------------------------
def _ask_firm_non_firm_split(payload: dict[str, Any]) -> Ask | None:
    """When headroom < capacity, ask for firm / non-firm split."""
    headroom_mw = payload.get("headroom", {}).get("firm_capacity_mw")
    firm_mw = payload.get("mitigation", {}).get("firm_request_mw")
    target_mw = payload.get("capacity_mw")
    if firm_mw is None or target_mw is None:
        return None
    if headroom_mw is not None and float(headroom_mw) < float(firm_mw):
        return Ask(
            id="firm-non-firm-split",
            title=(f"Confirm firm vs non-firm split at POC for "
                   f"{firm_mw:.1f} MW request against {float(headroom_mw):.1f} "
                   f"MW firm headroom"),
            priority="P1",
            category="capacity",
            body=(
                "Firm headroom at the proposed POC is insufficient for the "
                f"net {firm_mw:.1f} MW import request. Per CCCM v19 §3 the "
                "customer may accept a split offer (firm up to headroom, "
                "non-firm balance subject to ANM). Please confirm: "
                "(i) the firm MW available, (ii) the non-firm curtailment "
                "principle (last-in-first-out vs pro-rata), and "
                "(iii) the DNO's current ANM scheme reference for this POC."
            ),
            citation="CCCM v19 §3; Distribution Code DPC4; ENA EREC P2 Issue 7",
            decision_sla_days=45,
        )
    return None


def _ask_reinforcement_schedule(payload: dict[str, Any]) -> Ask | None:
    """When reinforcement is triggered, ask for the confirmed schedule."""
    triggers = payload.get("cost_estimate", {}).get("triggers_reinforcement")
    if not triggers:
        # Fall back to constraint envelope thermal fail.
        if (payload.get("constraint", {}) or {}).get("verdict") != "FAIL":
            return None
    return Ask(
        id="reinforcement-schedule",
        title="Confirm upstream reinforcement schedule and cost apportionment",
        priority="P1",
        category="schedule",
        body=(
            "The Tier 2 power flow / headroom analysis indicates upstream "
            "reinforcement is required to serve the full requested capacity. "
            "Please confirm: "
            "(a) whether this sits on the Common Connection Charging "
            "Methodology v19 Sch.1 §C 'aggregated' or 'commit-and-pay' path; "
            "(b) the RIIO-ED2 delivery window for the identified scheme; "
            "(c) the contestable vs non-contestable portion under DCUSA; "
            "(d) the proposed security payment per CCCM v19 Sch.4."
        ),
        citation="CCCM v19 Sch.1 §C + Sch.4; Ofgem RIIO-ED2 Licence Condition 25",
        decision_sla_days=60,
    )


def _ask_reactive_agreement(payload: dict[str, Any]) -> Ask | None:
    """When we offer reactive, ask for a compensating mechanism."""
    statcom_offer = payload.get("reactive", {}).get("statcom_mvar_offered")
    overnight = payload.get("reactive", {}).get("overnight_import_schedule")
    if (statcom_offer or 0) <= 0 and not overnight:
        return None
    return Ask(
        id="reactive-ancillary-agreement",
        title="Agreement-in-principle on voluntary reactive support (DPC4.5)",
        priority="P2",
        category="reactive",
        body=(
            "We offer a voluntary reactive-power service at the POC — the "
            "Q(V) curve, STATCOM MVAr envelope and overnight absorption "
            "schedule are set out in the Reactive Offer section. Please "
            "confirm whether the DNO will consider this under Distribution "
            "Code DPC4.5 (ancillary services) with quarterly settlement, "
            "or treat it as mandatory G99 Issue 2 §9.3 compliance only."
        ),
        citation="Distribution Code DPC4.5; ENA EREC G99 Issue 2 §9.3",
        decision_sla_days=45,
    )


def _ask_g99_protection_set(payload: dict[str, Any]) -> Ask | None:
    """Always requested for >1 MW schemes — G99 Table 10.1 settings."""
    cap = payload.get("capacity_mw") or 0
    if cap < 1.0:
        return None
    return Ask(
        id="g99-protection-settings",
        title="Issue G99 Issue 2 Table 10.1 / 10.2 protection settings",
        priority="P1",
        category="protection",
        body=(
            "Please issue the DNO-specific G99 Issue 2 Table 10.1 protection "
            "settings applicable at the POC voltage level, together with "
            "Table 10.2 stage durations. The pack assumes the RoCoF anti-"
            "islanding scheme (df/dt = 1 Hz/s with 500 ms delay). If the DNO "
            "applies vector shift or a faster RoCoF scheme, please state the "
            "value so the commissioning plan can be updated."
        ),
        citation="ENA EREC G99 Issue 2 §10 Table 10.1 + 10.2; §12 FRT",
        decision_sla_days=30,
    )


def _ask_voltage_headroom(payload: dict[str, Any]) -> Ask | None:
    """If constraint envelope voltage violations present, ask about tap plan."""
    cenv = payload.get("constraint", {}) or {}
    if (cenv.get("voltage_violations") or 0) <= 0:
        return None
    return Ask(
        id="voltage-tap-plan",
        title="Confirm upstream tap plan / voltage set-point at POC",
        priority="P2",
        category="capacity",
        body=(
            "The Tier 2 power flow indicates voltage violations at / near the "
            "POC under the proposed injection. Please confirm the DNO's "
            "primary substation AVC set-point, upstream transformer tap "
            "range used in the DNO's own study, and whether an OLTC block "
            "or schedule-tap will be applied during our commissioning."
        ),
        citation="ENA EREC P28 Issue 2 §4; Distribution Code DPC4",
        decision_sla_days=45,
    )


def _ask_poc_location_confirmation(payload: dict[str, Any]) -> Ask | None:
    """Always present — double-check POC substation identity + ownership."""
    poc = payload.get("best_candidate") or {}
    if not poc:
        return None
    return Ask(
        id="poc-location-confirmation",
        title=f"Confirm POC identity and ownership for {poc.get('name', 'target substation')}",
        priority="P1",
        category="commercial",
        body=(
            "The pack proposes a POC at "
            f"'{poc.get('name', '<unknown>')}' (voltage "
            f"{poc.get('voltage_kv', '?')} kV). Please confirm: "
            "(i) the substation is DNO-owned (not IDNO / IC), "
            "(ii) the bay availability and switchgear type, "
            "(iii) any active land or access constraints, "
            "(iv) the GSP group for RO / ROC settlement."
        ),
        citation="Distribution Licence Condition 25; CCCM v19 Sch.1 §A",
        decision_sla_days=30,
    )


def _ask_disruption_risk(payload: dict[str, Any]) -> Ask | None:
    """If disruption study shows high breach probability, ask about DNO backstop."""
    disr = payload.get("disruption", {}) or {}
    prob = disr.get("prob_firm_breach") or 0
    if prob < 0.05:
        return None
    return Ask(
        id="disruption-backstop",
        title=f"Contingency backstop — prob(firm breach) = {prob:.1%}",
        priority="P2",
        category="schedule",
        body=(
            f"Monte Carlo analysis (N={disr.get('n_runs', 1000)}) indicates a "
            f"{prob:.1%} probability of firm-headroom breach under the "
            "combined demand + weather + outage axes. Please confirm the "
            "DNO's pre-agreed non-firm curtailment protocol for this POC "
            "(trip-to-MW or ramp-to-MW) and expected notification timing."
        ),
        citation="ENA EREC P2 Issue 7 §7; Distribution Code DPC9",
        decision_sla_days=45,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
_RULES = [
    _ask_poc_location_confirmation,
    _ask_firm_non_firm_split,
    _ask_reinforcement_schedule,
    _ask_g99_protection_set,
    _ask_voltage_headroom,
    _ask_reactive_agreement,
    _ask_disruption_risk,
]


def generate_dno_asks(payload: dict[str, Any]) -> list[Ask]:
    """
    Infer the list of DNO asks from the composed pack payload.

    The rules are deterministic — same payload in, same asks out. The
    pack composer should call this once after assembling the payload.
    """
    if not isinstance(payload, dict):
        return []

    asks: list[Ask] = []
    for rule in _RULES:
        try:
            a = rule(payload)
        except Exception:
            a = None
        if a is not None:
            asks.append(a)

    # Sort P1 first, then P2, then P3 (alpha within priority).
    priority_order = {"P1": 0, "P2": 1, "P3": 2}
    asks.sort(key=lambda x: (priority_order.get(x.priority, 3), x.id))
    return asks

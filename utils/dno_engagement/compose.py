"""
utils.dno_engagement.compose — DNO pack orchestrator.

Pulls together every sub-module into a single :class:`DnoPackPayload`:

    compose_dno_pack(project_id) ─┬── profiles.compute_seasonal_demand_profile
                                  ├── constraint.compute_constraint_envelope
                                  ├── reactive.compute_reactive_offer
                                  ├── disruption.compute_disruption_scenarios
                                  ├── mitigation.compute_mitigation_stack
                                  ├── grid_connection_analyser.assess_connection
                                  ├── grid_connection_analyser.estimate_connection_cost
                                  ├── dno_profiles.get_profile
                                  └── asks.generate_dno_asks

Only one DB query is made directly here (project row load); everything
else is delegated to existing helpers.

Cited:
  * ENA EREC G99 Issue 2 — connection obligations (via grid_connection_analyser).
  * CCCM v19 — cost breakdown (via report_grid_connection.cccm_v19_breakdown).
  * ENA EREC P28, P29, P2/7, G5/5 — cited in sub-modules.
  * NESO SOF — cited in profiles + disruption modules.
  * BS EN ISO 8528-1 — cited in mitigation module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("princeps.dno_engagement.compose")


@dataclass
class DnoPackPayload:
    """The full JSON-able payload that feeds the Jinja template + PDF."""

    # Cover metadata
    project_id: str
    project_name: str
    technology: str
    capacity_mw: float
    lat: float | None
    lon: float | None
    pack_version: str
    generated_at: str
    target_dno: str | None
    dno_profile: dict[str, Any] = field(default_factory=dict)

    # Addressee / reliance
    addressee: str = "DNO Connection Team — pre-application"
    reliance_statement: str = ""

    # Headline verdict
    executive_verdict: str = "TBD"
    executive_summary: str = ""

    # Sub-module payloads (each .to_dict())
    site: dict[str, Any] = field(default_factory=dict)
    proposal: dict[str, Any] = field(default_factory=dict)
    seasonal_profile: dict[str, Any] = field(default_factory=dict)
    mitigation: dict[str, Any] = field(default_factory=dict)
    constraint: dict[str, Any] = field(default_factory=dict)
    disruption: dict[str, Any] = field(default_factory=dict)
    reactive: dict[str, Any] = field(default_factory=dict)
    connection_options: list[dict[str, Any]] = field(default_factory=list)
    cccm: dict[str, Any] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    asks: list[dict[str, Any]] = field(default_factory=list)

    # Best candidate + headroom (passed through from grid_connection_analyser)
    best_candidate: dict[str, Any] = field(default_factory=dict)
    headroom: dict[str, Any] = field(default_factory=dict)
    cost_estimate: dict[str, Any] = field(default_factory=dict)

    # Risk (MC snapshot + qualitative)
    risks: list[dict[str, Any]] = field(default_factory=list)

    # Appendices
    appendices: dict[str, Any] = field(default_factory=dict)

    # Provenance / citations — master list
    citations: list[str] = field(default_factory=list)

    # Internal health
    sub_module_errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_PACK_VERSION = "v1.0"


def _default_reliance_statement(project_name: str) -> str:
    return (
        f"This Pre-Application DNO Engagement Pack has been prepared by the "
        f"Princeps platform for the {project_name} project. Reliance is "
        f"extended to the recipient DNO connection team and the project "
        f"sponsor for the sole purpose of pre-application dialogue. No "
        f"reliance is extended to any other party. The quantitative outputs "
        f"reflect publicly available data at the generation date and should "
        f"be confirmed by the DNO through its formal budget-estimate and "
        f"connection-offer processes (CCCM v19 Sch.5)."
    )


def _connection_options_from_assessment(
    assessment: dict[str, Any],
    capacity_mw: float,
) -> list[dict[str, Any]]:
    """Express candidate substations + voltages as DNO 'connection options'."""
    out: list[dict[str, Any]] = []
    candidates = assessment.get("candidates", []) or []
    for i, c in enumerate(candidates[:5], start=1):
        out.append({
            "rank": i,
            "name": c.get("name", f"Candidate {i}"),
            "voltage_kv": c.get("voltage_kv"),
            "distance_km": c.get("distance_km"),
            "transformer_rating_mva": c.get("transformer_rating_mva"),
            "gen_headroom_mw": c.get("gen_headroom_mw"),
            "demand_headroom_mw": c.get("demand_headroom_mw"),
            "suitability_score": c.get("suitability_score"),
            "verdict": c.get("verdict"),
            "notes": c.get("notes", []),
            "queue": c.get("queue", {}),
        })
    return out


def _timeline(capacity_mw: float, pack_version: str) -> list[dict[str, Any]]:
    """Canonical DNO timeline — SSEN / UKPN / NGED broadly similar."""
    return [
        {
            "stage": "Pre-application enquiry (Stage 1)",
            "duration_weeks": 2,
            "owner": "Princeps + Customer",
            "output": "This pack (v" + pack_version + ")",
            "cost_gbp": 0,
            "citation": "CCCM v19 Sch.5",
        },
        {
            "stage": "DNO budget estimate (Stage 2)",
            "duration_weeks": 6,
            "owner": "DNO Connections",
            "output": "Budget estimate letter + indicative reinforcement",
            "cost_gbp": 8_000,
            "citation": "CCCM v19 Sch.5",
        },
        {
            "stage": "Formal application",
            "duration_weeks": 4,
            "owner": "Customer",
            "output": "G99 Type {B,C,D} application, ICP letter",
            "cost_gbp": 2_500,
            "citation": "ENA EREC G99 Issue 2 §7",
        },
        {
            "stage": "Connection offer + security deposit",
            "duration_weeks": 12,
            "owner": "DNO Connections",
            "output": "Offer letter; customer signs + pays security",
            "cost_gbp": 0,
            "citation": "CCCM v19 Sch.4 §Security Payment",
        },
        {
            "stage": "Detailed design + ICP/BCA build",
            "duration_weeks": 26,
            "owner": "Customer / ICP",
            "output": "Detailed design package, HV + civil works",
            "cost_gbp": 0,
            "citation": "ENA Lloyd's Register of Connections Competency",
        },
        {
            "stage": "Commissioning + G99 compliance",
            "duration_weeks": 4,
            "owner": "Customer + DNO",
            "output": "FAT, SAT, Authorisation to Energise, FON",
            "cost_gbp": 0,
            "citation": "ENA EREC G99 Issue 2 §9 Commissioning",
        },
    ]


def _executive_verdict(
    constraint: dict[str, Any] | None,
    headroom_firm: float | None,
    target_firm: float,
) -> tuple[str, str]:
    """Derive a one-word verdict + paragraph summary for the executive section."""
    cverdict = (constraint or {}).get("verdict") if constraint else None
    if cverdict == "FAIL":
        return (
            "AT RISK",
            "The Tier 2 constraint envelope fails P28 / P2/7 limits at the "
            "proposed capacity. Firm reinforcement is likely required. See "
            "constraint analysis section for details."
        )
    if cverdict == "MARGINAL":
        return (
            "VIABLE WITH WORKS",
            "The Tier 2 constraint envelope passes, but margins are tight. "
            "Non-firm offer or modest reinforcement likely on the CCCM v19 "
            "commit-and-pay path."
        )
    if headroom_firm is not None and headroom_firm < target_firm:
        return (
            "VIABLE WITH WORKS",
            f"POC firm capacity ({headroom_firm:.1f} MW) is below the net "
            f"target ({target_firm:.1f} MW) — a split firm/non-firm offer "
            f"is requested. Mitigation stack closes the gap."
        )
    return (
        "VIABLE",
        "The proposed capacity fits within the POC firm envelope with the "
        "mitigation stack applied. No upstream reinforcement required."
    )


def _risks_from_payload(payload: DnoPackPayload) -> list[dict[str, Any]]:
    """Assemble a qualitative risk register layered on top of MC output."""
    risks: list[dict[str, Any]] = []
    # Monte Carlo-derived
    disr = payload.disruption or {}
    p = disr.get("prob_firm_breach", 0)
    if p > 0.05:
        risks.append({
            "id": "MC-FIRM-BREACH",
            "title": f"Firm breach probability {p:.1%}",
            "severity": "HIGH" if p > 0.15 else "MEDIUM",
            "source": "disruption MC",
            "mitigation": "BESS peak-shave (see mitigation stack)",
            "citation": "ENA EREC P2 Issue 7 §7",
        })
    # Constraint-derived
    cenv = payload.constraint or {}
    if cenv.get("voltage_violations", 0) > 0:
        risks.append({
            "id": "P28-VOLTAGE",
            "title": "P28 voltage envelope breach",
            "severity": "HIGH",
            "source": "constraint envelope",
            "mitigation": "Reactive Q(V) curve + overnight absorption",
            "citation": "ENA EREC P28 Issue 2 §4",
        })
    if cenv.get("max_loading_pct", 0) > 85:
        risks.append({
            "id": "THERMAL-LOADING",
            "title": f"Thermal loading {cenv.get('max_loading_pct', 0):.0f}%",
            "severity": "HIGH" if cenv.get("max_loading_pct", 0) > 100 else "MEDIUM",
            "source": "constraint envelope",
            "mitigation": "Upstream reinforcement / non-firm offer",
            "citation": "ENA EREC P2 Issue 7 §6",
        })
    # Reinforcement-derived
    if payload.cost_estimate.get("triggers_reinforcement"):
        risks.append({
            "id": "REINFORCEMENT-SCHEDULE",
            "title": "RIIO-ED2 reinforcement window risk",
            "severity": "MEDIUM",
            "source": "CCCM v19 cost estimate",
            "mitigation": "Commit-and-pay path + secured land for early works",
            "citation": "CCCM v19 Sch.1 §C",
        })
    return risks


# ---------------------------------------------------------------------------
# Project loader (DB)
# ---------------------------------------------------------------------------
async def _load_project(conn, project_id: str) -> dict | None:
    try:
        pid = uuid.UUID(str(project_id))
    except Exception:
        return None
    row = await conn.fetchrow(
        """SELECT project_id, name, technology, capacity_mw, lat, lon,
                  metadata, stage, verdict
           FROM projects WHERE project_id = $1""",
        pid,
    )
    if not row:
        return None
    raw_meta = row["metadata"]
    if raw_meta is None:
        meta = {}
    elif isinstance(raw_meta, dict):
        meta = dict(raw_meta)
    elif isinstance(raw_meta, (bytes, str)):
        try:
            parsed = json.loads(raw_meta)
            meta = parsed if isinstance(parsed, dict) else {}
        except Exception:
            meta = {}
    else:
        meta = {}
    return {
        "project_id": str(row["project_id"]),
        "name": row["name"],
        "technology": (row["technology"] or meta.get("technology") or "datacentre"),
        "capacity_mw": float(row["capacity_mw"] or meta.get("capacity_mw") or 50.0),
        "lat": float(row["lat"]) if row["lat"] is not None else None,
        "lon": float(row["lon"]) if row["lon"] is not None else None,
        "metadata": meta,
        "stage": row["stage"],
        "project_verdict": row["verdict"],
    }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
async def compose_dno_pack(
    project_id: str,
    target_dno: str | None = None,
    *,
    conn=None,
    pool=None,
    run_power_flow: bool = True,
) -> DnoPackPayload:
    """
    Compose the full DNO engagement pack payload for a project.

    Parameters
    ----------
    project_id : str
        Princeps project UUID.
    target_dno : str | None
        Canonical DNO code (SSEN / UKPN / NGED / SPEN / NPG / ENWL / NIE).
        If None, auto-resolves via assess_connection.dno_area.
    conn :
        Open asyncpg connection for the DB query path. Either ``conn`` OR
        ``pool`` must be provided.
    pool :
        asyncpg Pool — used when ``conn`` is not supplied. Acquired once
        for the compose call.
    run_power_flow : bool
        If False, skips the Tier 2 subprocess (faster in CI / for preview).

    Returns
    -------
    DnoPackPayload
    """
    from .profiles import compute_seasonal_demand_profile
    from .constraint import compute_constraint_envelope
    from .reactive import compute_reactive_offer
    from .disruption import compute_disruption_scenarios
    from .mitigation import compute_mitigation_stack
    from .asks import generate_dno_asks
    from .dno_profiles import get_profile

    # Acquire a connection if only a pool was passed.
    own_conn = False
    if conn is None:
        if pool is None:
            raise ValueError("compose_dno_pack requires conn or pool")
        conn = await pool.acquire()
        own_conn = True

    try:
        project = await _load_project(conn, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        if project["lat"] is None or project["lon"] is None:
            raise ValueError(f"Project {project_id} has no lat/lon set")

        # Subsection 1 — site + DNO resolution (via grid_connection_analyser).
        sub_errors: dict[str, str] = {}
        assessment: dict[str, Any] = {}
        try:
            from utils.grid_connection_analyser import assess_connection
            assessment = await assess_connection(
                conn, project["lat"], project["lon"],
                project["capacity_mw"], project["technology"],
            )
        except Exception as e:  # noqa: BLE001
            sub_errors["assessment"] = f"{type(e).__name__}: {e}"
            log.warning("assess_connection failed: %s", e)

        dno_code = (
            target_dno
            or (assessment.get("dno_area") or {}).get("code")
            or (assessment.get("dno_area") or {}).get("name")
        )
        dno_profile = get_profile(dno_code).to_dict()

        best = assessment.get("best_candidate") or {}
        # Headroom firm MW (best candidate rating × 0.95 floor).
        firm_mw = None
        tx_rating = best.get("transformer_rating_mva")
        if tx_rating:
            firm_mw = round(float(tx_rating) * 0.95, 2)

        # Subsection 2 — seasonal profile.
        profile_payload: dict[str, Any] = {}
        try:
            prof = await compute_seasonal_demand_profile(
                project_id=project["project_id"],
                tech=project["technology"],
                capacity_mw=project["capacity_mw"],
                year=datetime.utcnow().year,
                weather_station=project["metadata"].get("weather_station"),
                use_forecaster=False,
            )
            profile_payload = prof.to_dict()
        except Exception as e:  # noqa: BLE001
            sub_errors["seasonal_profile"] = f"{type(e).__name__}: {e}"
            log.warning("seasonal profile failed: %s", e)

        # Subsection 3 — mitigation stack.
        mitigation_payload: dict[str, Any] = {}
        try:
            mit = compute_mitigation_stack(
                project_id=project["project_id"],
                target_mw=project["capacity_mw"],
                target_capacity_factor=(
                    profile_payload.get("annual_capacity_factor") or 0.35
                ),
                gross_demand_mw=project["capacity_mw"],
                technology_hint=project["technology"],
            )
            mitigation_payload = mit.to_dict()
        except Exception as e:  # noqa: BLE001
            sub_errors["mitigation"] = f"{type(e).__name__}: {e}"
            log.warning("mitigation stack failed: %s", e)

        # Subsection 4 — constraint envelope.
        constraint_payload: dict[str, Any] = {}
        try:
            cenv = await compute_constraint_envelope(
                project_id=project["project_id"],
                poc_substation_id=best.get("id"),
                conn=conn,
                lat=project["lat"],
                lon=project["lon"],
                capacity_mw=mitigation_payload.get("firm_request_mw")
                            or project["capacity_mw"],
                technology=project["technology"],
                contingency=run_power_flow,
            )
            constraint_payload = cenv.to_dict()
        except Exception as e:  # noqa: BLE001
            sub_errors["constraint"] = f"{type(e).__name__}: {e}"
            log.warning("constraint envelope failed: %s", e)

        # Subsection 5 — reactive offer.
        reactive_payload: dict[str, Any] = {}
        try:
            ro = compute_reactive_offer(
                project_id=project["project_id"],
                tech=project["technology"],
                capacity_mw=project["capacity_mw"],
            )
            reactive_payload = ro.to_dict()
        except Exception as e:  # noqa: BLE001
            sub_errors["reactive"] = f"{type(e).__name__}: {e}"
            log.warning("reactive offer failed: %s", e)

        # Subsection 6 — disruption MC.
        disruption_payload: dict[str, Any] = {}
        try:
            dr = compute_disruption_scenarios(
                project_id=project["project_id"],
                n=1000,
                base_peak_mw=project["capacity_mw"],
                firm_capacity_mw=firm_mw if firm_mw is not None else project["capacity_mw"] * 1.05,
                nameplate_mw=project["capacity_mw"],
                seed=42,
            )
            disruption_payload = dr.to_dict()
        except Exception as e:  # noqa: BLE001
            sub_errors["disruption"] = f"{type(e).__name__}: {e}"
            log.warning("disruption MC failed: %s", e)

        # Subsection 7 — CCCM v19 cost breakdown (via report_grid_connection).
        cccm_payload: dict[str, Any] = {}
        try:
            from utils.report_grid_connection import cccm_v19_breakdown
            distance_km = float(best.get("distance_km") or 5.0)
            rec_v = int(best.get("voltage_kv") or 33)
            queued_mw = float((best.get("queue") or {}).get("ecr_queued_mw", 0) or 0)
            headroom_mw = best.get("gen_headroom_mw")
            triggers = (
                headroom_mw is not None
                and float(headroom_mw) < project["capacity_mw"]
            )
            cccm_payload = cccm_v19_breakdown(
                distance_km=distance_km,
                capacity_mw=project["capacity_mw"],
                voltage_kv=rec_v,
                queued_mw=queued_mw,
                triggers_reinforcement=triggers,
            )
        except Exception as e:  # noqa: BLE001
            sub_errors["cccm"] = f"{type(e).__name__}: {e}"
            log.warning("CCCM breakdown failed: %s", e)

        # Connection options + cost estimate.
        connection_options = _connection_options_from_assessment(
            assessment, project["capacity_mw"],
        )
        cost_estimate = assessment.get("cost_estimate") or {}
        cost_estimate["triggers_reinforcement"] = bool(
            cccm_payload.get("triggers_reinforcement")
            if isinstance(cccm_payload, dict) else False
        )

        # Headroom block — simple dict shape for downstream asks rule.
        headroom_block = {
            "firm_capacity_mw": firm_mw,
            "non_firm_capacity_mw": (
                round(float(tx_rating) * 1.10, 2) if tx_rating else None
            ),
            "accepted_queue_mw": float(
                (best.get("queue") or {}).get("ecr_queued_mw", 0) or 0
            ),
        }

        # Site + proposal blocks.
        site_block = {
            "project_id": project["project_id"],
            "project_name": project["name"],
            "lat": project["lat"],
            "lon": project["lon"],
            "technology": project["technology"],
            "capacity_mw": project["capacity_mw"],
            "dno_area": assessment.get("dno_area") or {},
            "stage": project["stage"],
            "metadata": project["metadata"],
        }
        proposal_block = {
            "capacity_mw": project["capacity_mw"],
            "firm_request_mw": mitigation_payload.get("firm_request_mw"),
            "gross_demand_mw": mitigation_payload.get("gross_demand_mw"),
            "technology": project["technology"],
            "connection_voltage_kv": best.get("voltage_kv"),
            "connection_substation": best.get("name"),
            "connection_substation_id": best.get("id"),
            "poc_distance_km": best.get("distance_km"),
        }

        verdict, exec_summary = _executive_verdict(
            constraint_payload,
            firm_mw,
            mitigation_payload.get("firm_request_mw") or project["capacity_mw"],
        )

        payload = DnoPackPayload(
            project_id=project["project_id"],
            project_name=project["name"],
            technology=project["technology"],
            capacity_mw=project["capacity_mw"],
            lat=project["lat"],
            lon=project["lon"],
            pack_version=_PACK_VERSION,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            target_dno=dno_code,
            dno_profile=dno_profile,
            addressee=(
                f"{dno_profile.get('name') or 'DNO'} — Connection Team"
            ),
            reliance_statement=_default_reliance_statement(project["name"]),
            executive_verdict=verdict,
            executive_summary=exec_summary,
            site=site_block,
            proposal=proposal_block,
            seasonal_profile=profile_payload,
            mitigation=mitigation_payload,
            constraint=constraint_payload,
            disruption=disruption_payload,
            reactive=reactive_payload,
            connection_options=connection_options,
            cccm=cccm_payload,
            timeline=_timeline(project["capacity_mw"], _PACK_VERSION),
            best_candidate=best,
            headroom=headroom_block,
            cost_estimate=cost_estimate,
            appendices={
                "regulatory_register": [
                    "ENA EREC G99 Issue 2 (10 Mar 2025)",
                    "Ofgem-approved CCCM v19",
                    "ENA EREC P28 Issue 2 (voltage fluctuations)",
                    "ENA EREC P29 (unbalance)",
                    "ENA EREC P2 Issue 7 (security of supply)",
                    "ENA EREC G5 Issue 5 (harmonics)",
                    "BS EN ISO 8528-1 (genset classification)",
                    "NESO System Operability Framework 2024",
                    "Distribution Code v43 (DPC4, DPC4.5, DPC9)",
                    "Ofgem RIIO-ED2 Final Determinations (29 Nov 2022)",
                ],
                "dno_profile_full": dno_profile,
                "provenance": {
                    "assessment_tier": assessment.get("tier"),
                    "sub_module_errors": sub_errors,
                },
            },
            citations=[
                "ENA EREC G99 Issue 2",
                "Ofgem CCCM v19",
                "ENA EREC P28 Issue 2",
                "ENA EREC P29",
                "ENA EREC P2 Issue 7",
                "ENA EREC G5 Issue 5",
                "BS EN ISO 8528-1",
                "NESO SOF 2024",
            ],
            sub_module_errors=sub_errors,
        )

        # Risks (depend on payload being assembled first).
        payload.risks = _risks_from_payload(payload)

        # Asks — generated LAST so it sees every other section.
        try:
            asks = generate_dno_asks(payload.to_dict())
            payload.asks = [a.to_dict() for a in asks]
        except Exception as e:  # noqa: BLE001
            sub_errors["asks"] = f"{type(e).__name__}: {e}"
            log.warning("asks generation failed: %s", e)

        return payload

    finally:
        if own_conn and conn is not None:
            try:
                await pool.release(conn)
            except Exception:
                pass

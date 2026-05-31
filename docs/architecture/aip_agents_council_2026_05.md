# Princeps AIP agent roster — council-reviewed architecture (2026-05-31)

**Frame**: Treat Princeps as Palantir AIP. The Ontology (Conjure IDL +
DTDL v3 + Apache AGE) is the substrate. Typed Actions in
`app/actions/registry.py` are the only legal mutators. **Agents** are
the autonomous loops that run between human-driven sessions —
monitoring upstream sources, watching the ontology for events, and
dispatching typed Actions on schedule or in response to triggers.

This document was produced via the Council pattern: five reviewer
personas argue each proposal, then a final roster is consolidated.

## Council members

| Persona | Lens |
|---|---|
| **Architect** | Ontology coherence, function/action boundary, idempotency |
| **Reliability Engineer (SRE)** | Concurrency, retries, backpressure, SLA |
| **Regulatory Analyst** | UK rules fit — EREC G99, ENA, Ofgem CUSC, EIA, BNG, CDM |
| **Product** | Visible value to a developer/lender/analyst user |
| **CFO** | Compute spend per run + revenue lift per agent |

## Current Railway service topology (baseline)

13 services from the April deploy:
`princeps-frontend`, `princeps-web`, `princeps-scheduler`,
`princeps-worker-prospector`, `princeps-worker-grid-monitor`,
`princeps-worker-procurement`, `princeps-worker-ingestion`,
`princeps-worker-report`, `princeps-worker-analyst`,
`princeps-worker-rnd`, `princeps-worker-planning`,
`princeps-worker-market`, `princeps-worker-builder`.

These are **processes**, not yet **agents**. They run jobs but don't
read the ontology graph and react. Below is the agent layer that
should sit on top.

## Proposed agents — 16 distinct functions, in priority order

Legend:
- **Tier 0** = ship in week 1 (data-rotting issues, no agent → silent breakage)
- **Tier 1** = ship in weeks 2-3 (visible product wins)
- **Tier 2** = ship in month 2 (advanced / lower frequency)

---

### Tier 0 — ontology + ingestion hygiene

#### A1 · Ontology Coherence Agent
**Role**: walks the AGE graph, finds duplicate `Site`/`Project`/`Substation`/`Entity` nodes by name + spatial proximity, proposes merges. Writes proposals to `action_audit_log` as `merge_entities` actions awaiting human approval.
**Trigger**: every 6h + on bulk ingest finish.
**Reads**: AGE graph + `geometry::geography` proximity.
**Writes**: `merge_entities` action proposals (preview only).
**Council verdict**:
- Architect: **+1** — without this the AGE graph rots in 2 weeks at current ingest rates.
- SRE: cap at 200 proposals/run, throttle.
- Regulatory: low risk — never auto-merges.
- Product: **+1** — search quality degrades fast otherwise.
- CFO: ~£3/run via Claude judge calls. Net positive on quality.

#### A2 · Schema Drift Agent
**Role**: compares the live `conjure/idl/*.cdy` definitions against persisted ontology rows. Flags fields that exist in code but never populated, OR fields populated but missing from IDL.
**Trigger**: on every git push to main; weekly fallback.
**Reads**: Conjure IDL files, AGE node properties, `objects.*` tables.
**Writes**: `schema_drift_alert` notification.
**Council verdict**:
- Architect: **+2** — this is the gate that prevents the ontology becoming a hairball.
- SRE: O(types) — cheap.
- Regulatory: critical for compliance audit trail integrity.
- Product: invisible to end users but unblocks every refactor.
- CFO: ~£0.50/run.

#### A3 · Connector Health Sentinel
**Role**: pings every registered data connector (Ofgem CKAN, NESO OpenData, planning.data.gov.uk, BMRS, EA, OS, gov.uk publishing, etc.). Checks last fetch + row count delta; flags if zero-delta > N intervals (suggests source schema changed).
**Trigger**: hourly.
**Reads**: `connector_schedule_log` + `dataset_registry`.
**Writes**: `connector_health` rows → frontend `ConnectorHealthTile`.
**Council verdict**: unanimous **+1** — already partly stubbed; agentify it.

---

### Tier 1 — visible product agents

#### A4 · Stakeholder Watch Agent
**Role**: For every `Docket` the user pinned or that touches a tracked `Project`, re-fetches the canonical source URL daily. Diffs against the cached `docket_enrichments` row. If material change (deadline shift, new stakeholder filing, status change), fires `change_alert`.
**Trigger**: 06:00 UK time daily.
**Reads**: `dockets`, `docket_enrichments`, pinned dockets.
**Writes**: `change_alerts` row + `email` Action.
**Council verdict**:
- Regulatory: **+2** — this is the moat vs. waiting for Ofgem mailings.
- Product: **+2** — the "Halcyon-grade" promise from the gap analysis.
- SRE: simple cron — 50 dockets × 5s = manageable.

#### A5 · Planning Constraint Watcher
**Role**: For every tracked `CandidateSite`, re-runs planning.data.gov.uk constraints lookup weekly. If a new CRITICAL designation (SSSI, AONB, SAC) appears within 1 km, fires alert. If a constraint is lifted, also fires.
**Trigger**: weekly + manual re-scan endpoint.
**Reads**: `candidate_sites` + planning_designations MVT.
**Writes**: `planning_constraint_change` notification + chat-context update.

#### A6 · Grid Headroom Patrol
**Role**: Every 6h, refreshes NESO + DNO ECR feeds. For every substation tied to a project's connection assessment, recomputes available headroom. If headroom dropped > 10 % since last check (e.g. another queue addition), alerts owner.
**Trigger**: 6h cron + on every TEC register update.
**Reads**: `grid_substations`, `eso_tec_register`, `grid_ecr`.
**Writes**: `headroom_delta` + frontend `GridPulseTile` update.

#### A7 · Counterparty Sanctions Re-Screen
**Role**: Existing `screen_counterparty` action exists but is one-shot. Agent re-screens every `Counterparty` node daily against the refreshed UK sanctions + Companies House dissolved list.
**Trigger**: 03:00 UK time daily.
**Reads**: `counterparties`, sanctions cache.
**Writes**: `sanctions_alert` if new match crosses 0.85 score.

#### A8 · Obligation Deadline Reminder
**Role**: Walks `contracts.obligations` (Phase F output). Fires a reminder Action 30 / 7 / 1 days before any deadline.
**Trigger**: daily 07:00.
**Reads**: `contracts.obligations`.
**Writes**: chat-rail notification + project workspace toast.

#### A9 · Document Change Watcher
**Role**: Subscribes to inserts on `contracts.document_drafts`. When a new draft lands for a document with ≥1 prior draft, automatically calls `diff_drafts` + `extract_obligations` + emits a `ChangeAlert`. (Already designed as Phase G in the Hypercube gap analysis — agentify it.)
**Trigger**: event-driven on `contracts.document_drafts` insert.
**Reads / Writes**: as in Phase G design.

---

### Tier 2 — advanced / lower frequency

#### A10 · Market Price Reactor
**Role**: Watches BMRS DA prices. For each `Project` with an explicit PPA strike or expected revenue model, compares against rolling 30-day DA average. If divergence > 15 % vs underwriting assumption, fires advisory.
**Trigger**: daily after BMRS daily publish.

#### A11 · Reinforcement Cost Refresher
**Role**: For each `Project` with a `GridConnectionAssessment` older than 30 days, re-runs the cost model with current pandapower line/transformer prices.
**Trigger**: monthly + on demand.

#### A12 · AR7 Window Monitor
**Role**: Watches DESNZ AR7 page for round opening + closing dates. When window opens, auto-prepares an AR7 CfD bundle (using the `ar7_cfd_application` template) for every project flagged "ar7-eligible".
**Trigger**: daily polling of DESNZ AR7 publications page.

#### A13 · REPD Cross-Validator
**Role**: Nightly powerplantmatching cross-val (the script committed today). Flags REPD rows where matched capacity diverges > 20 % from the GEM/JRC consensus.
**Trigger**: 02:00 UK time daily.

#### A14 · Twin Replay / Backtest Agent
**Role**: Replays a tracked Project's grid twin against historical NESO/BMRS data for a chosen window. Produces a "what would have happened" report. Useful for verifying revenue assumptions post-FID.
**Trigger**: on user request from the Twin UI.

#### A15 · Ontology Backfill Agent
**Role**: When a new ontology type is added to Conjure IDL, walks existing related rows and back-populates the new fields using the generator_fn registered for that type.
**Trigger**: on git push that adds a `.cdy` file or new typed action.

#### A16 · Council Convener
**Role**: Multi-agent debate orchestrator (already stubbed in `app/routers/council.py`). For high-stakes Actions (deploy capital, sign filing, send email), pulls quotes from the relevant agents above into a single deliberation, surfaces consensus + dissent in the chat verdict rail.
**Trigger**: on any Action flagged `requires_council = true`.

---

## Recommended Railway service split

Rather than 16 separate services, group by cadence + side-effect class
to keep ops sane. Final mapping:

| Railway service | Hosts agents | Cadence | Side effects |
|---|---|---|---|
| `princeps-agent-graph` | A1, A2, A15 | cron + push hooks | proposes ontology mutations |
| `princeps-agent-connector` | A3 | hourly cron | health rows only |
| `princeps-agent-regwatch` | A4, A5, A12 | daily cron | alerts + emails |
| `princeps-agent-grid` | A6, A11 | 6h cron | grid assessments |
| `princeps-agent-screen` | A7 | daily cron | sanctions alerts |
| `princeps-agent-contracts` | A8, A9 | event + cron | obligation updates |
| `princeps-agent-market` | A10, A13 | daily cron | revenue/REPD advisories |
| `princeps-agent-replay` | A14 | on-demand | reports |
| `princeps-agent-council` | A16 | event-driven | wraps other agents |

That's 9 new Railway services. Combined with the 13 existing, total
Railway footprint = 22 services. Each new agent service is small
(256 MB / 1 shared CPU), so the Railway monthly add is modest (~£40-60).

## Implementation pattern (one per agent)

```python
# agents/<name>.py
from __future__ import annotations
import asyncio, logging
from app.actions.registry import ActionContext
from app.deps import get_pool_async
from app.ontology.events import subscribe   # for event-driven agents

log = logging.getLogger(__name__)

async def run_once():
    """One iteration. Idempotent. Returns counters."""
    pool = await get_pool_async()
    ctx  = ActionContext(user_id="agent:<name>", tenant_id=None, pool=pool)
    # 1. read from ontology
    # 2. compute deltas
    # 3. dispatch typed actions via registry
    # 4. emit metrics

async def main():
    while True:
        try:
            stats = await run_once()
            log.info("agent <name> tick stats=%s", stats)
        except Exception:
            log.exception("agent <name> tick failed")
        await asyncio.sleep(<cadence_seconds>)
```

Each agent is launched as a Railway "Worker" service with the entry
point `python -m agents.<name>`. Health probes hit `/ping` if the
agent exposes a tiny FastAPI sidecar (Tier 1+ agents should).

## What we are NOT building

- **Per-action human-approval UI** — already covered by the existing
  chat verdict rail; agents just enqueue Actions with `requires_review=true`.
- **A separate "agent dashboard" page** — Mission Control's existing
  ActionQueue + ConnectorHealth + ChangeAlerts tiles already surface
  agent output. Add filters, not screens.
- **Per-agent custom UIs** — every visible result flows through
  existing project workspace tabs (Overview / Contracts / Applications
  / Operate).

## Sequencing

```
Week 1   A1 → A2 → A3                  (ontology + connector hygiene)
Week 2   A4 → A5 → A6                  (regwatch + grid headroom)
Week 3   A7 → A8 → A9                  (sanctions + contracts)
Week 4   A10 → A12 → A13               (market + AR7 + REPD)
Week 5   A11 → A14 → A15 → A16         (advanced)
```

Each agent ships independently — there are no inter-agent dependencies
beyond reading the same ontology + writing typed Actions. Council
(A16) wraps the others and lands last so it has real agent voices to
convene.

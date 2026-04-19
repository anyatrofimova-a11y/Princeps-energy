"""
Coordination layer (nelson-inspired).

Provides a light orchestration primitive over the existing ARQ workers so
that multiple long-running agents can safely run in parallel without
overlapping writes or blowing their combined cost budget.

Core pieces:

  * ``SailingOrders``  — structured mission payload. Makes mission intent,
    success criteria, and claimed resources explicit rather than implicit
    in the agent's payload dict.

  * ``ActionStation``  — risk tier for the mission. Higher tiers force
    smaller models, tighter budgets, and mandatory human review before any
    external side effect (PR merge, email send, db mutation).

  * ``Coordinator``    — checks declared resource claims against the
    ``missions`` table (conflict detection), opens the mission record, and
    closes it on completion. All agents that declare a mission go through
    this — callers that don't need coordination (single-worker jobs) can
    ignore the module entirely.

Design notes
------------
This is deliberately NOT a nelson port. We only translate the parts that
are load-bearing for the Princeps worker fleet:

  - Conflict detection   → real concern when ``builder`` agents edit the
                           same file in parallel, or when ``ingestion``
                           and ``builder`` touch the same table.
  - Hull integrity       → piggybacks on the existing ``agent_runs`` /
                           cost_gbp machinery; no new monitoring layer.
  - Sailing orders       → explicit mission schema instead of free-form
                           dict payloads, so agents can be coordinated
                           without the coordinator understanding each
                           agent's payload shape.

We skip: captain's logs (agent_runs already covers it), turnover briefs
(not yet needed for single-agent missions), and the Royal Navy naming
(keeps the module reviewable by someone who hasn't read nelson).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any

import asyncpg

from app.agents.base import AgentContext

log = logging.getLogger("princeps.agents.coordination")


class ActionStation(str, Enum):
    """Risk tier of a mission. Determines model ceiling + review gates.

    Ordered low → high. Higher tiers require tighter guardrails. The names
    mirror the nelson convention but callers can treat them as plain tags.
    """

    PATROL    = "patrol"     # read-only, no external side effects
    STATIONS  = "stations"   # writes to its own tables only, no external calls
    GENERAL   = "general"    # writes + external calls (Slack/email/HTTP)
    TRAFALGAR = "trafalgar"  # code changes, PR creation, schema migrations


class MissionConflict(RuntimeError):
    """Raised when a new mission overlaps with a running one."""


@dataclass
class SailingOrders:
    """Structured mission payload.

    A mission is a single invocation of an agent with an explicit goal and
    declared resource claims. The coordinator uses ``touches_paths`` and
    ``touches_tables`` to detect conflicts with other running missions.
    """

    mission_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    goal: str = ""
    outcomes: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    success_criteria: str = ""
    action_station: ActionStation = ActionStation.STATIONS

    # Resources the mission intends to mutate. Used for overlap detection.
    touches_paths: list[str] = field(default_factory=list)     # repo paths (globs)
    touches_tables: list[str] = field(default_factory=list)    # db tables

    # Opaque parent payload (the original ARQ job payload) so agents that
    # already branch on payload keys still work.
    payload: dict[str, Any] = field(default_factory=dict)

    # Caller-provided deadline / budget hints (optional).
    deadline_s: int | None = None
    budget_gbp: float | None = None

    @classmethod
    def from_payload(cls, agent_name: str, payload: dict) -> "SailingOrders":
        """Lift a raw payload into SailingOrders, tolerating missing fields.

        Lets existing agents keep their payload shape; the coordinator fills
        in defaults for the orchestration fields.
        """
        orders = payload.get("_orders") or {}
        station_raw = orders.get("action_station", "stations")
        try:
            station = ActionStation(station_raw)
        except ValueError:
            station = ActionStation.STATIONS
        return cls(
            mission_id=orders.get("mission_id") or str(uuid.uuid4()),
            agent_name=agent_name,
            goal=orders.get("goal") or payload.get("goal") or f"{agent_name}.run",
            outcomes=orders.get("outcomes") or [],
            constraints=orders.get("constraints") or [],
            success_criteria=orders.get("success_criteria") or "",
            action_station=station,
            touches_paths=orders.get("touches_paths") or [],
            touches_tables=orders.get("touches_tables") or [],
            payload=payload,
            deadline_s=orders.get("deadline_s"),
            budget_gbp=orders.get("budget_gbp"),
        )

    def to_json(self) -> str:
        data = asdict(self)
        data["action_station"] = self.action_station.value
        return json.dumps(data, default=str)


# ── Coordinator ──────────────────────────────────────────────────────────────


class Coordinator:
    """Conflict-aware mission lifecycle.

    Usage (inside an agent's ``run()``)::

        orders = SailingOrders.from_payload(self.name, payload)
        async with Coordinator(ctx.db, orders) as mission:
            ...  # do the work
            mission.record_outcome({"pr_url": "..."})

    On ``__aenter__`` we scan for overlaps; on exit we close the record.
    """

    def __init__(self, pool: asyncpg.Pool, orders: SailingOrders):
        self.pool = pool
        self.orders = orders
        self._outcome: dict[str, Any] = {}
        self._conflicts: list[dict] = []

    async def __aenter__(self) -> "Coordinator":
        await self._open()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        ok = exc is None
        summary = "" if ok else f"{exc_type.__name__}: {exc}"[:500]
        await self._close(ok=ok, summary=summary)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def _open(self) -> None:
        """Insert mission row, check for conflicts, mark as running."""
        conflicts = await self._scan_conflicts()
        if conflicts:
            self._conflicts = conflicts
            raise MissionConflict(
                f"mission {self.orders.mission_id} conflicts with {len(conflicts)} running missions: "
                + ", ".join(
                    f"{c['mission_id'][:8]}({c['agent_name']})" for c in conflicts[:3]
                )
            )
        await self.pool.execute(
            """
            INSERT INTO missions (
                mission_id, agent_name, goal, action_station,
                touches_paths, touches_tables, orders_json,
                status, started_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, 'running', now())
            """,
            self.orders.mission_id,
            self.orders.agent_name,
            self.orders.goal[:500],
            self.orders.action_station.value,
            self.orders.touches_paths,
            self.orders.touches_tables,
            self.orders.to_json(),
        )
        log.info(
            "mission.open id=%s agent=%s station=%s paths=%d tables=%d",
            self.orders.mission_id[:8],
            self.orders.agent_name,
            self.orders.action_station.value,
            len(self.orders.touches_paths),
            len(self.orders.touches_tables),
        )

    async def _close(self, *, ok: bool, summary: str) -> None:
        await self.pool.execute(
            """
            UPDATE missions
               SET status = $2,
                   finished_at = now(),
                   outcome = $3::jsonb,
                   summary = $4
             WHERE mission_id = $1
            """,
            self.orders.mission_id,
            "done" if ok else "failed",
            json.dumps(self._outcome, default=str),
            summary,
        )
        log.info(
            "mission.close id=%s ok=%s outcome_keys=%s",
            self.orders.mission_id[:8], ok, list(self._outcome),
        )

    def record_outcome(self, data: dict[str, Any]) -> None:
        """Record mission output (e.g. PR URL, candidate count). Merged into ``outcome``."""
        self._outcome.update(data)

    # ── Conflict detection ──────────────────────────────────────────────────

    async def _scan_conflicts(self) -> list[dict]:
        """Find currently-running missions that overlap our resource claims.

        Overlap = shared table in ``touches_tables`` OR any glob overlap in
        ``touches_paths``. Path overlap is a simple substring check — glob
        semantics are not needed for the current agent set.
        """
        if not (self.orders.touches_paths or self.orders.touches_tables):
            return []
        rows = await self.pool.fetch(
            """
            SELECT mission_id, agent_name, touches_paths, touches_tables
              FROM missions
             WHERE status = 'running'
               AND mission_id <> $1
            """,
            self.orders.mission_id,
        )
        conflicts: list[dict] = []
        for r in rows:
            shared_tables = set(r["touches_tables"] or []) & set(self.orders.touches_tables)
            shared_paths = _paths_overlap(r["touches_paths"] or [], self.orders.touches_paths)
            if shared_tables or shared_paths:
                conflicts.append({
                    "mission_id": r["mission_id"],
                    "agent_name": r["agent_name"],
                    "shared_tables": list(shared_tables),
                    "shared_paths": shared_paths,
                })
        return conflicts


def _paths_overlap(a: list[str], b: list[str]) -> list[str]:
    """Substring-based path overlap. Good enough for allow-list style claims."""
    hits: list[str] = []
    for x in a:
        for y in b:
            if x == y or x in y or y in x:
                hits.append(x)
                break
    return hits


# ── Helpers agents may import ────────────────────────────────────────────────


def budget_for_station(station: ActionStation) -> tuple[float, int]:
    """Default (max_cost_per_run_gbp, max_tokens_out_per_run) by risk tier.

    Individual agents may override their own caps; this is a suggestion for
    callers that want station-based budgeting.
    """
    return {
        ActionStation.PATROL:    (0.10,  5_000),
        ActionStation.STATIONS:  (0.40, 15_000),
        ActionStation.GENERAL:   (1.00, 30_000),
        ActionStation.TRAFALGAR: (3.00, 60_000),
    }[station]


def requires_human_review(station: ActionStation) -> bool:
    """TRAFALGAR-tier side effects (PR merges, migrations) must not auto-apply."""
    return station is ActionStation.TRAFALGAR


__all__ = [
    "ActionStation",
    "Coordinator",
    "MissionConflict",
    "SailingOrders",
    "budget_for_station",
    "requires_human_review",
]

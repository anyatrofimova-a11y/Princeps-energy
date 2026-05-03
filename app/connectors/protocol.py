"""Connector contract — Protocol, health/report dataclasses, registry.

The Connector Protocol is deliberately small so that data ingesters across
very different sources (ArcGIS REST, CKAN, OpenDataSoft, planning.data.gov.uk,
BMRS, ...) can share one health/refresh surface. FastAPI routes read the
registry at request time; connectors register themselves at import time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

import asyncpg


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass
class IngestReport:
    """Outcome of a single ``refresh()`` call."""

    source_name: str
    rows_upserted: int = 0
    warnings: list[str] = field(default_factory=list)
    next_cursor: Optional[str] = None
    started_utc: Optional[datetime] = None
    completed_utc: Optional[datetime] = None
    status: str = "green"          # green|amber|red
    message: str = ""

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("started_utc", "completed_utc"):
            v = d.get(k)
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d


@dataclass
class ConnectorHealth:
    """Point-in-time health for a connector, read from connectors_registry."""

    source_name: str
    status: str                                  # green|amber|red
    last_successful_utc: Optional[datetime] = None
    last_attempted_utc: Optional[datetime] = None
    rows_total: int = 0
    rows_stale_days: Optional[int] = None
    schema_hash: Optional[str] = None
    message: str = ""
    schedule: str = ""

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("last_successful_utc", "last_attempted_utc"):
            v = d.get(k)
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Connector(Protocol):
    """Every ingester conforms to this contract.

    Attributes
    ----------
    source_name : str
        Unique, stable identifier — used as the primary key in
        ``connectors_registry`` and in the ``/api/connectors/{name}/refresh``
        route. Prefer snake_case.
    schedule : str
        Cron expression describing how often the scheduler should call
        ``refresh()``. The framework itself does not execute crons; an
        external scheduler (Dockerfile.scheduler) consumes this field.
    """

    source_name: str
    schedule: str

    async def refresh(self, pool: asyncpg.Pool) -> IngestReport: ...

    async def health(self) -> ConnectorHealth: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Connector] = {}


def register(connector: Connector) -> Connector:
    """Register a connector instance. Returns the connector for chaining."""
    name = getattr(connector, "source_name", None)
    if not name:
        raise ValueError(f"Connector {connector!r} has no source_name")
    _REGISTRY[name] = connector
    return connector


def get_connector(name: str) -> Optional[Connector]:
    return _REGISTRY.get(name)


def list_connectors() -> list[Connector]:
    return list(_REGISTRY.values())


# ---------------------------------------------------------------------------
# Registry persistence helpers (optional — connectors call these from
# their own ``refresh()``/``health()`` implementations)
# ---------------------------------------------------------------------------

_UPSERT_RUN_SQL = """
INSERT INTO connectors_registry (
    source_name, schedule, schema_hash,
    last_attempted_utc, last_successful_utc,
    last_status, last_message,
    rows_upserted_last_run, rows_total, next_cursor,
    updated_at
) VALUES (
    $1, $2, $3,
    $4, $5,
    $6, $7,
    $8, $9, $10,
    now()
)
ON CONFLICT (source_name) DO UPDATE SET
    schedule               = EXCLUDED.schedule,
    schema_hash            = EXCLUDED.schema_hash,
    last_attempted_utc     = EXCLUDED.last_attempted_utc,
    last_successful_utc    = COALESCE(EXCLUDED.last_successful_utc,
                                      connectors_registry.last_successful_utc),
    last_status            = EXCLUDED.last_status,
    last_message           = EXCLUDED.last_message,
    rows_upserted_last_run = EXCLUDED.rows_upserted_last_run,
    rows_total             = GREATEST(EXCLUDED.rows_total, connectors_registry.rows_total),
    next_cursor            = EXCLUDED.next_cursor,
    updated_at             = now()
"""


async def record_run(
    pool: asyncpg.Pool,
    *,
    source_name: str,
    schedule: str,
    schema_hash: Optional[str],
    report: IngestReport,
    rows_total: int,
) -> None:
    """Persist an IngestReport to connectors_registry."""
    async with pool.acquire() as conn:
        await conn.execute(
            _UPSERT_RUN_SQL,
            source_name,
            schedule,
            schema_hash,
            report.started_utc or datetime.now(timezone.utc),
            report.completed_utc if report.status != "red" else None,
            report.status,
            report.message or "",
            report.rows_upserted,
            rows_total,
            report.next_cursor,
        )


async def read_health(
    pool: asyncpg.Pool,
    *,
    source_name: str,
    schedule: str,
    table_name: Optional[str] = None,
    stale_days_amber: int = 7,
    stale_days_red: int = 30,
) -> ConnectorHealth:
    """Compute health from connectors_registry and the connector's table.

    If ``table_name`` is given, ``rows_total`` is refreshed from a live
    ``count(*)`` so the number reflects reality even when the registry
    has never been written.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM connectors_registry WHERE source_name = $1",
            source_name,
        )

        rows_total = row["rows_total"] if row else 0
        if table_name:
            try:
                rows_total = await conn.fetchval(
                    f"SELECT count(*) FROM {table_name}"
                ) or 0
            except Exception:
                # Table might not exist yet (migration not applied) — leave
                # registry value.
                pass

    now = datetime.now(timezone.utc)
    last_success = row["last_successful_utc"] if row else None
    stale_days = None
    if last_success:
        stale_days = int((now - last_success).total_seconds() // 86400)

    if row is None:
        status = "amber"
        message = "never run"
    elif row["last_status"] == "red":
        status = "red"
        message = row["last_message"] or "last run failed"
    elif stale_days is not None and stale_days >= stale_days_red:
        status = "red"
        message = f"stale {stale_days}d"
    elif stale_days is not None and stale_days >= stale_days_amber:
        status = "amber"
        message = f"stale {stale_days}d"
    elif rows_total == 0:
        status = "amber"
        message = "no rows"
    else:
        status = "green"
        message = row["last_message"] or "ok"

    return ConnectorHealth(
        source_name=source_name,
        status=status,
        last_successful_utc=last_success,
        last_attempted_utc=row["last_attempted_utc"] if row else None,
        rows_total=rows_total,
        rows_stale_days=stale_days,
        schema_hash=row["schema_hash"] if row else None,
        message=message,
        schedule=schedule,
    )


def schema_hash(fields: list[str]) -> str:
    """Stable hex hash of an ordered list of output fields."""
    payload = json.dumps(sorted(fields), separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

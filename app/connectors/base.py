"""Magritte-style connector ABC + dataset registry helpers.

This is the **new** Princeps Foundry-flavour connector framework. Every
external dataset (HM Land Registry CCOD, BMRS day-ahead prices, NSIP/DCO
register, ENTSO-E TYNDP, HSE incidents …) is a typed subclass of
:class:`Connector` registered in the :class:`princeps_datasets` table.

Subclasses normally override **just three** methods::

    class MyConnector(Connector):
        slug = "hm_land_registry_ccod"
        title = "HM Land Registry — Corporate Ownership"
        source_url = "https://use-land-property-data.service.gov.uk/datasets/ccod"
        license = "OGL-3.0"
        refresh_cadence = "monthly"
        table_name = "ccod_ownership"
        freshness_threshold_hours = 24 * 35   # monthly + 5d slack
        upstream_slugs = []

        async def ensure_schema(self, pool):
            async with pool.acquire() as conn:
                await conn.execute("CREATE TABLE IF NOT EXISTS …")

        async def fetch(self) -> list[dict]:
            ...   # HTTP / file pull → list of row dicts

        async def upsert(self, pool, rows) -> IngestResult:
            ...   # COPY / INSERT … ON CONFLICT into table_name

The default :meth:`Connector.ingest` orchestrates the rest:
``ensure_schema → fetch → license-guard → upsert → registry update +
refresh-log row``. It is what the FastAPI ``POST /api/datasets/{slug}/refresh``
route calls.

The legacy Protocol + ``connectors_registry`` ingest contract used by the
designation connectors lives at :mod:`app.connectors.protocol` and is still
exported from :mod:`app.connectors`.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

log = logging.getLogger("princeps.connectors")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    """Outcome of a single :meth:`Connector.upsert` call."""

    rows_ingested: int = 0          # rows actually written this run
    rows_total: int = 0             # rows in destination table after this run
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HealthCheck:
    """Computed point-in-time health for a registered dataset."""

    status: str                              # 'green' | 'yellow' | 'red'
    age_hours: Optional[float]
    row_count: Optional[int]
    expected_freshness_hours: int
    issues: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# License guard — hard block for non-commercial sources
# ---------------------------------------------------------------------------

_BLOCKED_LICENSES = {"NC", "non-commercial", "non_commercial", "noncommercial"}


def _license_blocked(license_str: str) -> bool:
    return (license_str or "").strip().lower() in {l.lower() for l in _BLOCKED_LICENSES}


# ---------------------------------------------------------------------------
# SQL helpers — kept private to this module
# ---------------------------------------------------------------------------

_REGISTER_SQL = """
INSERT INTO princeps_datasets
    (slug, title, source_url, license, refresh_cadence,
     table_name, freshness_threshold_hours, metadata)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
ON CONFLICT (slug) DO UPDATE SET
    title = EXCLUDED.title,
    source_url = EXCLUDED.source_url,
    license = EXCLUDED.license,
    refresh_cadence = EXCLUDED.refresh_cadence,
    table_name = EXCLUDED.table_name,
    freshness_threshold_hours = EXCLUDED.freshness_threshold_hours,
    metadata = EXCLUDED.metadata,
    updated_at = NOW()
"""

_LOG_START_SQL = """
INSERT INTO dataset_refresh_log (slug, started_at)
VALUES ($1, NOW())
RETURNING id
"""

_LOG_FINISH_OK_SQL = """
UPDATE dataset_refresh_log
SET completed_at = NOW(),
    ok = TRUE,
    rows_ingested = $2,
    rows_total = $3,
    duration_ms = $4
WHERE id = $1
"""

_LOG_FINISH_FAIL_SQL = """
UPDATE dataset_refresh_log
SET completed_at = NOW(),
    ok = FALSE,
    error = $2,
    duration_ms = $3
WHERE id = $1
"""

_REGISTRY_OK_SQL = """
UPDATE princeps_datasets
SET last_refreshed_at = NOW(),
    last_refresh_ok = TRUE,
    last_refresh_error = NULL,
    last_row_count = $2,
    health_status = 'green',
    health_checked_at = NOW(),
    updated_at = NOW()
WHERE slug = $1
"""

_REGISTRY_FAIL_SQL = """
UPDATE princeps_datasets
SET last_refresh_ok = FALSE,
    last_refresh_error = $2,
    health_status = 'red',
    health_checked_at = NOW(),
    updated_at = NOW()
WHERE slug = $1
"""

_LINEAGE_SQL = """
INSERT INTO dataset_lineage (upstream_slug, downstream_slug, relationship)
VALUES ($1, $2, 'derives_from')
ON CONFLICT (upstream_slug, downstream_slug, relationship) DO NOTHING
"""


# ---------------------------------------------------------------------------
# The ABC
# ---------------------------------------------------------------------------

async def _fire_dependent_pipelines(pool: asyncpg.Pool, connector_slug: str) -> None:
    """Find every enabled pipeline whose first connector_source node references
    `connector_slug` and fire them asynchronously.

    Best-effort: any error inside this helper is logged and swallowed so it
    never bubbles up to the caller's ingest path.
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT slug, manifest
                FROM data_pipelines
                WHERE enabled = TRUE
                  AND manifest @> jsonb_build_object(
                        'nodes', jsonb_build_array(
                          jsonb_build_object(
                            'kind', 'connector_source',
                            'props', jsonb_build_object('slug', $1::text)
                          )
                        )
                  )
                """,
                connector_slug,
            )
    except Exception as exc:
        log.warning("dependent pipeline lookup failed for %s: %s", connector_slug, exc)
        return

    # The jsonb @> match above is strict. Many real manifests will have
    # additional fields. Fall back to a Python-side scan that's tolerant.
    try:
        async with pool.acquire() as conn:
            all_rows = await conn.fetch(
                "SELECT slug, manifest FROM data_pipelines WHERE enabled = TRUE",
            )
        targets = []
        for r in all_rows:
            try:
                m = r["manifest"]
                if isinstance(m, str):
                    import json as _json
                    m = _json.loads(m)
                for n in (m.get("nodes") or []):
                    if (n.get("kind") == "connector_source"
                            and (n.get("props") or {}).get("slug") == connector_slug):
                        targets.append(r["slug"])
                        break
            except Exception:
                continue
    except Exception as exc:
        log.warning("pipeline scan failed for %s: %s", connector_slug, exc)
        return

    if not targets:
        return

    log.info(
        "connector %s triggered %d pipelines: %s",
        connector_slug, len(targets), targets,
    )

    # Run in series to avoid hammering the DB. Failure of one doesn't
    # block the others.
    try:
        from app.routers.pipelines import run_pipeline as _run
    except Exception as exc:
        log.warning("could not import pipelines.run_pipeline: %s", exc)
        return

    for target_slug in targets:
        try:
            await _run(
                slug=target_slug,
                body={"triggered_by": f"connector_refresh:{connector_slug}"},
                pool=pool,
            )
        except Exception as exc:
            log.warning("post-ingest pipeline fire failed slug=%s: %s", target_slug, exc)


class Connector(ABC):
    """Magritte-style connector contract.

    Subclasses set the class-level attributes below and implement
    :meth:`fetch` and :meth:`upsert` (and usually :meth:`ensure_schema`).
    The default :meth:`ingest` orchestrates everything else and writes the
    ``princeps_datasets`` registry + ``dataset_refresh_log`` rows.

    Class attributes
    ----------------
    slug : str
        Unique stable identifier (snake_case). Primary key in
        ``princeps_datasets``. Example: ``'hm_land_registry_ccod'``.
    title : str
        Human-readable title shown in the UI catalogue.
    source_url : str
        Canonical upstream URL (used as the citation).
    license : str
        SPDX-ish license tag — ``'OGL-3.0'``, ``'CC-BY-4.0'``, ``'OS-OpenData'``,
        … Anything in :data:`_BLOCKED_LICENSES` (e.g. ``'NC'``) makes
        :meth:`ingest` raise immediately.
    refresh_cadence : str
        ``'daily'`` | ``'monthly'`` | ``'on_demand'`` etc. Free-text — used
        for display + by external schedulers.
    table_name : str
        Destination table for the upsert (used by :func:`compute_health`
        to ``SELECT count(*)``).
    freshness_threshold_hours : int
        Health turns yellow when ``age > threshold`` and red when
        ``age > 2 × threshold``. Default 168 h (7 days).
    upstream_slugs : list[str]
        Optional lineage — slugs of datasets this one depends on. Persisted
        into ``dataset_lineage`` on ``register()``.
    """

    # — required overrides on subclasses (declared as class attrs) —
    slug: str = ""
    title: str = ""
    source_url: str = ""
    license: str = ""
    refresh_cadence: str = "on_demand"
    table_name: str = ""

    # — sensible defaults —
    freshness_threshold_hours: int = 168
    upstream_slugs: list[str] = []

    # ------------------------------------------------------------------ #
    # Subclass extension points                                          #
    # ------------------------------------------------------------------ #

    async def ensure_schema(self, pool: asyncpg.Pool) -> None:
        """Create destination table if missing.

        Default is a no-op; subclasses normally override with a single
        ``CREATE TABLE IF NOT EXISTS …`` so they're self-contained.
        """
        return None

    @abstractmethod
    async def fetch(self) -> list[dict]:
        """Pull rows from the upstream source. Return a list of dicts.

        Network/file errors should raise — :meth:`ingest` will catch and
        log them as a failed run. No DB access here.
        """

    @abstractmethod
    async def upsert(self, pool: asyncpg.Pool, rows: list[dict]) -> IngestResult:
        """Write *rows* into :attr:`table_name`.

        Return an :class:`IngestResult` with ``rows_ingested`` (rows
        upserted this call) and ``rows_total`` (post-run table count). On
        partial failure, append messages to ``result.errors`` rather than
        raising — :meth:`ingest` decides whether the run is yellow or red.
        """

    # ------------------------------------------------------------------ #
    # Default orchestration                                              #
    # ------------------------------------------------------------------ #

    async def ingest(self, pool: asyncpg.Pool, *, request: Any = None) -> IngestResult:
        """End-to-end refresh — schema → fetch → upsert → registry + log.

        Subclasses normally don't override this. Steps:

        1. Hard-block if :attr:`license` is non-commercial.
        2. Insert a row in ``dataset_refresh_log`` (started_at).
        3. Call :meth:`ensure_schema`.
        4. Call :meth:`fetch` (HTTP/file).
        5. Call :meth:`upsert` (DB write).
        6. Update ``princeps_datasets`` last_refreshed_at + last_row_count.
        7. Mark the refresh log row complete.

        On any error, both rows record the failure and the exception is
        re-raised so the caller (background task / cron) can surface it.

        The optional *request* parameter is passed through to
        :func:`app.license_guard.audit.record_artifact_use` if available,
        so commercial-safe accounting still works when a connector is
        triggered from an HTTP request.
        """
        if _license_blocked(self.license):
            raise PermissionError(
                f"connector '{self.slug}' is non-commercial "
                f"(license={self.license!r}) — blocked by license guard",
            )

        # Audit hook (best-effort — never break ingest if license_guard
        # module isn't importable in this venv).
        try:
            from app.license_guard.audit import record_artifact_use
            record_artifact_use(request, f"dataset:{self.slug}")
        except Exception:
            pass

        log_id: Optional[int] = None
        started_monotonic = time.monotonic()

        async with pool.acquire() as conn:
            log_id = await conn.fetchval(_LOG_START_SQL, self.slug)

        try:
            await self.ensure_schema(pool)
            rows = await self.fetch()
            result = await self.upsert(pool, rows)

            duration_ms = int((time.monotonic() - started_monotonic) * 1000)
            async with pool.acquire() as conn:
                await conn.execute(
                    _LOG_FINISH_OK_SQL,
                    log_id, result.rows_ingested, result.rows_total, duration_ms,
                )
                await conn.execute(_REGISTRY_OK_SQL, self.slug, result.rows_total)
            log.info(
                "connector ingest ok slug=%s rows=%s/%s duration=%dms",
                self.slug, result.rows_ingested, result.rows_total, duration_ms,
            )

            # Fire-and-forget: trigger any pipelines whose first connector_source
            # node references this slug. Failure here MUST NOT break ingest.
            try:
                import asyncio as _asyncio
                _asyncio.create_task(_fire_dependent_pipelines(pool, self.slug))
            except Exception as exc:
                log.warning("post-ingest pipeline trigger dispatch failed for %s: %s", self.slug, exc)

            return result

        except Exception as exc:
            duration_ms = int((time.monotonic() - started_monotonic) * 1000)
            err_msg = f"{type(exc).__name__}: {exc}"[:500]
            try:
                async with pool.acquire() as conn:
                    if log_id is not None:
                        await conn.execute(_LOG_FINISH_FAIL_SQL, log_id, err_msg, duration_ms)
                    await conn.execute(_REGISTRY_FAIL_SQL, self.slug, err_msg)
            except Exception:
                log.exception("failed to record connector failure for %s", self.slug)
            log.warning("connector ingest failed slug=%s err=%s", self.slug, err_msg)
            raise

    # ------------------------------------------------------------------ #
    # Health + registry                                                  #
    # ------------------------------------------------------------------ #

    async def health(self, pool: asyncpg.Pool) -> HealthCheck:
        """Compute health by reading ``princeps_datasets`` + table count.

        Delegates to :func:`app.connectors.health.compute_health` so
        subclasses don't reimplement freshness logic.
        """
        from app.connectors.health import compute_health  # avoid circular
        return await compute_health(pool, self.slug)

    async def register(self, pool: asyncpg.Pool) -> None:
        """Upsert this connector's metadata into ``princeps_datasets``.

        Called from :func:`app.connectors.startup.register_all_connectors`
        on app launch, before any ingest fires. Also writes the lineage
        edges declared in :attr:`upstream_slugs`.
        """
        if not self.slug or not self.title or not self.table_name:
            raise ValueError(
                f"connector {type(self).__name__} is missing slug/title/table_name",
            )
        meta = json.dumps({
            "class": f"{type(self).__module__}.{type(self).__name__}",
            "upstream_slugs": list(self.upstream_slugs or []),
        })
        async with pool.acquire() as conn:
            await conn.execute(
                _REGISTER_SQL,
                self.slug,
                self.title,
                self.source_url or None,
                self.license or None,
                self.refresh_cadence or "on_demand",
                self.table_name,
                int(self.freshness_threshold_hours or 168),
                meta,
            )
            for upstream in self.upstream_slugs or []:
                if upstream and upstream != self.slug:
                    await conn.execute(_LINEAGE_SQL, upstream, self.slug)


__all__ = ["Connector", "IngestResult", "HealthCheck"]

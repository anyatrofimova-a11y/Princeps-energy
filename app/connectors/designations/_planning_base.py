"""Common base class for planning.data.gov.uk designation connectors.

planning.data.gov.uk entities arrive with WKT geometry in WGS84, a stable
integer ``entity`` ID, and a ``reference``/``name`` pair. Each subclass
declares the ``dataset`` slug, the target table, any extra columns to store,
and an ``extract_extras`` hook that reads values from each entity.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from ..base import (
    ConnectorHealth,
    IngestReport,
    read_health,
    record_run,
    register,
    schema_hash,
)
from ._common import (
    build_upsert_sql,
    now_utc,
    planning_fetch_all,
    upsert_row,
)

log = logging.getLogger("princeps.connectors.designations")


class PlanningDataConnector:
    """Base class. Subclasses must set class-level attributes below."""

    source_name: str = ""
    schedule: str = "0 4 * * 0"          # weekly, Sun 04:00 UTC
    dataset: str = ""                    # planning.data.gov.uk dataset slug
    table: str = ""                      # target postgres table
    extra_cols: list[str] = []           # optional DB columns to store
    bbox_chunked: bool = False           # True for huge datasets (flood zones)

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------
    def extract_extras(self, entity: dict[str, Any]) -> list[Any]:
        """Return values matching ``extra_cols`` order. Override if needed."""
        return []

    # ------------------------------------------------------------------
    # Connector contract
    # ------------------------------------------------------------------
    async def refresh(self, pool: asyncpg.Pool) -> IngestReport:
        started = now_utc()
        report = IngestReport(source_name=self.source_name, started_utc=started)
        sql = build_upsert_sql(self.table, self.extra_cols)

        chunks: list[Optional[tuple[float, float, float, float]]]
        if self.bbox_chunked:
            from ._common import uk_bbox_chunks
            chunks = list(uk_bbox_chunks(step_deg=1.0))  # type: ignore[list-item]
        else:
            chunks = [None]

        upserted = 0
        async with pool.acquire() as conn:
            for chunk in chunks:
                try:
                    async for ent in planning_fetch_all(
                        self.dataset, bbox_wgs84=chunk
                    ):
                        try:
                            entity_id = ent.get("entity")
                            wkt = ent.get("geometry")
                            if entity_id is None or not wkt:
                                continue
                            await upsert_row(
                                conn,
                                sql,
                                feature_id=f"{self.dataset}:{entity_id}",
                                source_ref=(
                                    f"https://www.planning.data.gov.uk/entity/"
                                    f"{entity_id}"
                                ),
                                name=(ent.get("name") or "") or "",
                                reference=(ent.get("reference") or "") or "",
                                properties=ent,
                                wkt=wkt,
                                src_srid=4326,
                                extras=self.extract_extras(ent),
                            )
                            upserted += 1
                        except Exception as e:
                            report.warnings.append(
                                f"upsert entity={ent.get('entity')}: {e}"
                            )
                except Exception as e:
                    report.warnings.append(
                        f"fetch chunk={chunk} error={type(e).__name__}: {e}"
                    )
                    log.warning("connector %s chunk %s failed: %s",
                                self.source_name, chunk, e)
                await asyncio.sleep(0)

        report.rows_upserted = upserted
        report.completed_utc = now_utc()
        if upserted == 0:
            report.status = "amber"
            report.message = "0 rows upserted — API may be rate-limited or empty"
        else:
            report.status = "green"
            report.message = f"{upserted} rows upserted"
        # Truncate noisy warning lists before persisting.
        report.warnings = report.warnings[:50]

        try:
            rows_total = await pool.fetchval(
                f"SELECT count(*) FROM {self.table}"
            ) or 0
        except Exception:
            rows_total = upserted

        await record_run(
            pool,
            source_name=self.source_name,
            schedule=self.schedule,
            schema_hash=schema_hash(
                ["feature_id", "source_ref", "name", "reference",
                 *self.extra_cols, "properties", "geom"]
            ),
            report=report,
            rows_total=rows_total,
        )
        return report

    async def health(self) -> ConnectorHealth:
        # ``health()`` is called without a pool by callers that only want
        # registry fields; callers that want live row counts should use
        # ``health_with_pool``.
        return ConnectorHealth(
            source_name=self.source_name,
            status="amber",
            schedule=self.schedule,
            message="health() called without pool",
        )

    async def health_with_pool(self, pool: asyncpg.Pool) -> ConnectorHealth:
        return await read_health(
            pool,
            source_name=self.source_name,
            schedule=self.schedule,
            table_name=self.table,
        )


def register_planning(cls: type[PlanningDataConnector]) -> type[PlanningDataConnector]:
    """Decorator — instantiate and register a PlanningDataConnector subclass."""
    register(cls())
    return cls

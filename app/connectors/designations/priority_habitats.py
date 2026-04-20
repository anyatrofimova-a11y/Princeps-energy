"""Natural England Priority Habitat Inventory connector.

Source: Natural England ArcGIS FeatureServer
``Priority_Habitats_Inventory_England`` (layer 0). The dataset has ~1.4M
polygons nationwide, so we ingest in bbox chunks over the UK extent.

Each feature carries a ``Main_Habit`` attribute (e.g. ``"Lowland meadows"``,
``"Deciduous woodland"``). That gets mirrored to a dedicated column so
feasibility queries can filter without unpacking JSONB.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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
    arcgis_fetch_all,
    build_upsert_sql,
    geojson_to_wkt,
    now_utc,
    uk_bbox_chunks,
    upsert_row,
)

log = logging.getLogger("princeps.connectors.designations.priority_habitats")

QUERY_URL = (
    "https://services.arcgis.com/JJzESW51TqeY9uat/ArcGIS/rest/services/"
    "Priority_Habitats_Inventory_England/FeatureServer/0/query"
)


class PriorityHabitatsConnector:
    source_name = "priority_habitats"
    schedule = "0 7 * * 0"  # weekly
    table = "designations_priority_habitats"
    extra_cols = ["main_habit"]

    async def refresh(self, pool: asyncpg.Pool) -> IngestReport:
        started = now_utc()
        report = IngestReport(source_name=self.source_name, started_utc=started)
        sql = build_upsert_sql(self.table, self.extra_cols)

        upserted = 0
        chunks = uk_bbox_chunks(step_deg=1.0)
        async with pool.acquire() as conn:
            for chunk in chunks:
                try:
                    async for feat in arcgis_fetch_all(
                        QUERY_URL, bbox_wgs84=chunk, out_sr=4326
                    ):
                        try:
                            props = feat.get("properties") or {}
                            geom = feat.get("geometry") or {}
                            wkt = geojson_to_wkt(geom)
                            if not wkt:
                                continue
                            fid = (
                                props.get("OBJECTID")
                                or props.get("objectid")
                                or props.get("FID")
                            )
                            if fid is None:
                                continue
                            main_habit = (
                                props.get("Main_Habit")
                                or props.get("MAIN_HABIT")
                                or props.get("MainHabit")
                                or ""
                            )
                            await upsert_row(
                                conn,
                                sql,
                                feature_id=f"phi:{fid}",
                                source_ref=QUERY_URL,
                                name=str(main_habit or ""),
                                reference=str(fid),
                                properties=props,
                                wkt=wkt,
                                src_srid=4326,
                                extras=[str(main_habit or "")],
                            )
                            upserted += 1
                        except Exception as e:
                            report.warnings.append(
                                f"upsert phi OBJECTID={props.get('OBJECTID')}: {e}"
                            )
                except Exception as e:
                    report.warnings.append(
                        f"fetch chunk={chunk}: {type(e).__name__}: {e}"
                    )
                    log.warning("priority_habitats chunk %s failed: %s", chunk, e)
                await asyncio.sleep(0)

        report.rows_upserted = upserted
        report.completed_utc = now_utc()
        if upserted == 0:
            report.status = "amber"
            report.message = "0 rows upserted — NE ArcGIS may be rate-limited"
        else:
            report.status = "green"
            report.message = f"{upserted} rows upserted"
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


register(PriorityHabitatsConnector())

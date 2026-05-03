"""Agricultural Land Classification (ALC) Grade connector.

Source: Natural England ArcGIS FeatureServer
``Agricultural_Land_Classification_Post_1988`` (layer 0). Publicly readable,
no auth. Grades run 1-5 plus "Urban" and "Non-agricultural"; developers
treat Grade 3a+ as "best and most versatile" land.

Dataset is small enough (~hundreds of polygons) to pull in one pass.
"""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from ..protocol import (
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
    upsert_row,
)

log = logging.getLogger("princeps.connectors.designations.alc_grade")

QUERY_URL = (
    "https://services.arcgis.com/JJzESW51TqeY9uat/ArcGIS/rest/services/"
    "Agricultural_Land_Classification_Post_1988/FeatureServer/0/query"
)

GRADE_FIELDS = ("ALC_GRADE", "alc_grade", "Grade", "GRADE", "ALCGRADE")


def _extract_grade(props: dict[str, Any]) -> str:
    for f in GRADE_FIELDS:
        v = props.get(f)
        if v:
            return str(v).strip()
    return ""


def _extract_area_ha(props: dict[str, Any]) -> float | None:
    for k in ("AREA_HA", "Area_Ha", "area_ha"):
        v = props.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    shape_area = props.get("Shape_Area") or props.get("Shape__Area")
    if shape_area is not None:
        try:
            # Shape_Area from a 27700 layer is sqm -> ha.
            return float(shape_area) / 10_000.0
        except Exception:
            return None
    return None


class ALCGradeConnector:
    source_name = "alc_grade"
    schedule = "0 8 * * 0"
    table = "designations_alc_grade"
    extra_cols = ["alc_grade", "area_ha"]

    async def refresh(self, pool: asyncpg.Pool) -> IngestReport:
        started = now_utc()
        report = IngestReport(source_name=self.source_name, started_utc=started)
        sql = build_upsert_sql(self.table, self.extra_cols)

        upserted = 0
        async with pool.acquire() as conn:
            try:
                async for feat in arcgis_fetch_all(QUERY_URL, out_sr=4326):
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
                        grade = _extract_grade(props) or "Unknown"
                        area_ha = _extract_area_ha(props)
                        await upsert_row(
                            conn,
                            sql,
                            feature_id=f"alc:{fid}",
                            source_ref=QUERY_URL,
                            name=f"ALC Grade {grade}",
                            reference=str(fid),
                            properties=props,
                            wkt=wkt,
                            src_srid=4326,
                            extras=[grade, area_ha],
                        )
                        upserted += 1
                    except Exception as e:
                        report.warnings.append(
                            f"upsert alc OBJECTID={props.get('OBJECTID')}: {e}"
                        )
            except Exception as e:
                report.warnings.append(
                    f"fetch alc: {type(e).__name__}: {e}"
                )
                log.warning("alc_grade fetch failed: %s", e)

        report.rows_upserted = upserted
        report.completed_utc = now_utc()
        if upserted == 0:
            report.status = "amber"
            report.message = "0 rows upserted"
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


register(ALCGradeConnector())

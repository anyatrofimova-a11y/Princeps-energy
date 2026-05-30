"""earth-osm UK substation ingester.

Replaces the Overpass-based ``osm_substation_ingester.py`` with
reproducible Geofabrik snapshots — Overpass timeouts under load were
making the bulk pull unreliable.

Public surface: ``ingest_uk_substations(pool, voltage_min_kv=33.0)``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any

import asyncpg

log = logging.getLogger(__name__)


def _parse_voltage_kv(raw: Any) -> float | None:
    """OSM voltage tag is messy: '132000', '132 kV', '132000;33000', etc.
    Return the highest reading in kV (V/1000) or None.
    """
    if raw is None:
        return None
    s = str(raw)
    nums = [int(m) for m in re.findall(r"\d+", s)]
    if not nums:
        return None
    high = max(nums)
    # Heuristic: > 1000 → volts; otherwise already kV
    return round(high / 1000.0, 1) if high > 1000 else float(high)


async def _ensure_indexes(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_grid_sub_ext_uniq "
        "ON grid_substations (external_id, dno)"
    )


async def ingest_uk_substations(
    pool: asyncpg.Pool,
    voltage_min_kv: float = 33.0,
) -> dict[str, Any]:
    """Pull GB substations via earth-osm Geofabrik snapshot, upsert into
    ``grid_substations`` with ``dno = 'osm'``.
    """
    from earth_osm import eo  # imported lazily so the rest of the app
                              # doesn't pay the import cost at boot

    df = await asyncio.to_thread(
        eo.get_osm_data,
        "GB", "power", "substation",
        progress_bar=False,
    )
    if df is None or len(df) == 0:
        return {"inserted": 0, "updated": 0, "skipped": 0,
                "warning": "earth-osm returned no rows for GB power substation"}

    inserted = updated = skipped = 0
    async with pool.acquire() as conn:
        await _ensure_indexes(conn)
        for _, row in df.iterrows():
            tags = row.get("Tags", {}) or {}
            if isinstance(tags, str):
                try: tags = json.loads(tags.replace("'", '"'))
                except Exception: tags = {}
            v_kv = _parse_voltage_kv(tags.get("voltage") or row.get("voltage"))
            if v_kv is not None and v_kv < voltage_min_kv:
                skipped += 1
                continue
            ext_id = str(row.get("id") or row.get("osm_id") or "")
            if not ext_id:
                skipped += 1
                continue
            name = tags.get("name") or row.get("Name") or f"osm-sub-{ext_id}"
            lon = row.get("lon") or row.get("longitude") or row.get("Lon")
            lat = row.get("lat") or row.get("latitude") or row.get("Lat")
            if lon is None or lat is None:
                skipped += 1
                continue
            try:
                res = await conn.execute(
                    """
                    INSERT INTO grid_substations
                        (external_id, dno, name, voltage_kv, geom)
                    VALUES ($1, 'osm', $2, $3,
                            ST_SetSRID(ST_MakePoint($4::float, $5::float), 4326))
                    ON CONFLICT (external_id, dno) DO UPDATE
                       SET name = EXCLUDED.name,
                           voltage_kv = EXCLUDED.voltage_kv,
                           geom = EXCLUDED.geom
                    """,
                    ext_id, name, v_kv, float(lon), float(lat),
                )
                if "INSERT 0 1" in res:
                    inserted += 1
                else:
                    updated += 1
            except Exception as exc:
                log.warning("upsert failed for %s: %s", ext_id, exc)
                skipped += 1

        total = await conn.fetchval("SELECT COUNT(*) FROM grid_substations")

    return {"inserted": inserted, "updated": updated, "skipped": skipped,
            "total_in_db": total}


if __name__ == "__main__":
    async def _main():
        pool = await asyncpg.create_pool(
            os.environ["DATABASE_URL"],
            min_size=1, max_size=3, statement_cache_size=0,
        )
        r = await ingest_uk_substations(pool)
        print(json.dumps(r, default=str))
        await pool.close()
    asyncio.run(_main())

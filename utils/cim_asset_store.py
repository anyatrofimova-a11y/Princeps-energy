"""CIM Asset Library — PostgreSQL CRUD store for IEC 61970 assets.

Provides persistent storage, search, bulk operations, and NGED migration
for typed CIM Pydantic models.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import asyncpg

from models.cim.base import IdentifiedObject
from models.cim.core import Substation
from models.cim.topology import Terminal
from models.cim.wires import ACLineSegment, EnergyConsumer, PowerTransformer

log = logging.getLogger("princeps.cim_asset_store")

_SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

# Map CIM class name → collection key used by nged_cim.parse_cim_xml()
_CIM_CLASS_MAP: dict[str, type[IdentifiedObject]] = {}


def _ensure_class_map():
    """Lazy-load the full class map to avoid circular imports."""
    if _CIM_CLASS_MAP:
        return
    from utils.cim_serializer import _CIM_CLASS_MAP as full_map
    _CIM_CLASS_MAP.update(full_map)


# ---------------------------------------------------------------------------
# Table setup
# ---------------------------------------------------------------------------
async def setup_tables(conn: asyncpg.Connection) -> None:
    """Create cim_assets, cim_terminals, cim_exports, cim_model_assets tables."""
    ddl = (_SQL_DIR / "migrate_cim_assets.sql").read_text()
    await conn.execute(ddl)
    log.info("CIM asset library tables ready")


# ---------------------------------------------------------------------------
# Single-asset CRUD
# ---------------------------------------------------------------------------
async def upsert_asset(
    conn: asyncpg.Connection,
    asset: IdentifiedObject,
    source: str = "manual",
    source_region: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Insert or update a single CIM asset. Returns mrid."""
    cls_name = type(asset).__name__
    data = asset.model_dump(mode="json")
    lat = data.get("latitude")
    lon = data.get("longitude")

    await conn.execute(
        """
        INSERT INTO cim_assets (mrid, asset_type, name, data, geometry, source, source_region, tags, updated_at)
        VALUES ($1, $2, $3, $4::jsonb,
                CASE WHEN $5::float IS NOT NULL AND $6::float IS NOT NULL
                     THEN ST_SetSRID(ST_MakePoint($6, $5), 4326)
                     ELSE NULL END,
                $7, $8, $9::text[], NOW())
        ON CONFLICT (mrid) DO UPDATE SET
            asset_type    = EXCLUDED.asset_type,
            name          = EXCLUDED.name,
            data          = EXCLUDED.data,
            geometry      = EXCLUDED.geometry,
            source        = EXCLUDED.source,
            source_region = COALESCE(EXCLUDED.source_region, cim_assets.source_region),
            tags          = EXCLUDED.tags,
            updated_at    = NOW()
        """,
        asset.mrid,
        cls_name,
        asset.name,
        json.dumps(data),
        lat,
        lon,
        source,
        source_region,
        tags or [],
    )
    return asset.mrid


async def upsert_assets_bulk(
    conn: asyncpg.Connection,
    assets: list[IdentifiedObject],
    source: str = "import",
    source_region: str | None = None,
) -> int:
    """Bulk upsert assets. Returns count."""
    count = 0
    for asset in assets:
        await upsert_asset(conn, asset, source=source, source_region=source_region)
        count += 1
    return count


async def get_asset(conn: asyncpg.Connection, mrid: str) -> IdentifiedObject | None:
    """Fetch a single asset by MRID, returned as typed Pydantic model."""
    _ensure_class_map()
    row = await conn.fetchrow(
        "SELECT asset_type, data FROM cim_assets WHERE mrid = $1", mrid
    )
    if not row:
        return None
    cls = _CIM_CLASS_MAP.get(row["asset_type"])
    if cls is None:
        return None
    return cls(**json.loads(row["data"]))


async def get_asset_with_terminals(conn: asyncpg.Connection, mrid: str) -> dict | None:
    """Fetch asset + its terminals."""
    _ensure_class_map()
    row = await conn.fetchrow(
        "SELECT asset_type, data, source, source_region, tags, created_at, updated_at FROM cim_assets WHERE mrid = $1",
        mrid,
    )
    if not row:
        return None

    cls = _CIM_CLASS_MAP.get(row["asset_type"])
    asset_data = json.loads(row["data"])
    asset = cls(**asset_data) if cls else None

    terms = await conn.fetch(
        "SELECT mrid, connectivity_node_id, sequence_number, connected FROM cim_terminals WHERE conducting_equipment_id = $1",
        mrid,
    )

    return {
        "asset": asset_data,
        "asset_type": row["asset_type"],
        "source": row["source"],
        "source_region": row["source_region"],
        "tags": row["tags"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "terminals": [dict(t) for t in terms],
    }


async def list_assets(
    conn: asyncpg.Connection,
    asset_type: str | None = None,
    source: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List assets with optional filters. Returns dicts (not Pydantic models)."""
    conditions = []
    params: list[Any] = []
    idx = 1

    if asset_type:
        conditions.append(f"asset_type = ${idx}")
        params.append(asset_type)
        idx += 1

    if source:
        conditions.append(f"source = ${idx}")
        params.append(source)
        idx += 1

    if bbox:
        # bbox = (min_lon, min_lat, max_lon, max_lat)
        conditions.append(
            f"geometry && ST_MakeEnvelope(${idx}, ${idx+1}, ${idx+2}, ${idx+3}, 4326)"
        )
        params.extend(bbox)
        idx += 4

    if search:
        conditions.append(f"name ILIKE ${idx}")
        params.append(f"%{search}%")
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    params.append(limit)
    params.append(offset)

    rows = await conn.fetch(
        f"""
        SELECT mrid, asset_type, name, data, source, source_region, tags,
               ST_X(geometry) AS lon, ST_Y(geometry) AS lat,
               created_at, updated_at
        FROM cim_assets
        {where}
        ORDER BY updated_at DESC
        LIMIT ${idx} OFFSET ${idx+1}
        """,
        *params,
    )

    return [
        {
            "mrid": r["mrid"],
            "asset_type": r["asset_type"],
            "name": r["name"],
            "data": json.loads(r["data"]),
            "source": r["source"],
            "source_region": r["source_region"],
            "tags": r["tags"],
            "latitude": r["lat"],
            "longitude": r["lon"],
            "created_at": str(r["created_at"]),
            "updated_at": str(r["updated_at"]),
        }
        for r in rows
    ]


async def delete_asset(conn: asyncpg.Connection, mrid: str) -> bool:
    """Delete asset and its terminals. Returns True if deleted."""
    result = await conn.execute("DELETE FROM cim_assets WHERE mrid = $1", mrid)
    return result == "DELETE 1"


async def search_assets(
    conn: asyncpg.Connection,
    query: str,
    asset_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Full-text search on asset name using trigram similarity."""
    type_filter = ""
    params: list[Any] = [query, limit]
    if asset_type:
        type_filter = "AND asset_type = $3"
        params.append(asset_type)

    rows = await conn.fetch(
        f"""
        SELECT mrid, asset_type, name, source,
               similarity(name, $1) AS score
        FROM cim_assets
        WHERE name % $1 {type_filter}
        ORDER BY score DESC
        LIMIT $2
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def count_assets(
    conn: asyncpg.Connection,
    asset_type: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Return asset counts grouped by type and source."""
    by_type = await conn.fetch(
        "SELECT asset_type, count(*) AS cnt FROM cim_assets GROUP BY asset_type ORDER BY cnt DESC"
    )
    by_source = await conn.fetch(
        "SELECT source, count(*) AS cnt FROM cim_assets GROUP BY source ORDER BY cnt DESC"
    )
    total = await conn.fetchval("SELECT count(*) FROM cim_assets")
    return {
        "total": total,
        "by_type": {r["asset_type"]: r["cnt"] for r in by_type},
        "by_source": {r["source"]: r["cnt"] for r in by_source},
    }


# ---------------------------------------------------------------------------
# NGED migration — import existing nged_* table data into cim_assets
# ---------------------------------------------------------------------------
async def import_from_nged(conn: asyncpg.Connection) -> int:
    """Migrate data from nged_substation/transformer/line_segment/energy_consumer
    into cim_assets as typed Pydantic models."""
    count = 0

    # Substations
    rows = await conn.fetch(
        "SELECT id, name, region, voltage_kv, lat, lon FROM nged_substation"
    )
    for r in rows:
        sub = Substation(
            mrid=r["id"],
            name=r["name"],
            region=r["region"],
            latitude=r["lat"],
            longitude=r["lon"],
        )
        await upsert_asset(conn, sub, source="nged", source_region=r["region"])
        count += 1

    # Transformers
    rows = await conn.fetch(
        "SELECT id, name, rated_mva, substation_id, voltage_kv FROM nged_transformer"
    )
    for r in rows:
        xfmr = PowerTransformer(
            mrid=r["id"],
            name=r["name"],
            rated_mva=r["rated_mva"],
            substation_id=r["substation_id"],
        )
        await upsert_asset(conn, xfmr, source="nged")
        count += 1

    # Line segments
    rows = await conn.fetch(
        "SELECT id, name, length_km, r_ohm, x_ohm, region FROM nged_line_segment"
    )
    for r in rows:
        line = ACLineSegment(
            mrid=r["id"],
            name=r["name"],
            length_km=r["length_km"],
            r_ohm=r["r_ohm"],
            x_ohm=r["x_ohm"],
            region=r["region"],
        )
        await upsert_asset(conn, line, source="nged", source_region=r["region"])
        count += 1

    # Energy consumers
    rows = await conn.fetch(
        "SELECT id, name, p_mw, substation_id, region FROM nged_energy_consumer"
    )
    for r in rows:
        load = EnergyConsumer(
            mrid=r["id"],
            name=r["name"],
            p_mw=r["p_mw"],
            substation_id=r["substation_id"],
        )
        await upsert_asset(conn, load, source="nged", source_region=r["region"])
        count += 1

    log.info("Migrated %d NGED assets into cim_assets", count)
    return count


# ---------------------------------------------------------------------------
# Model composition (asset grouping for export)
# ---------------------------------------------------------------------------
async def create_model(
    conn: asyncpg.Connection,
    model_id: str,
    description: str,
    asset_mrids: list[str],
    profile: str,
) -> str:
    """Create a named model (group of assets) for export."""
    for mrid in asset_mrids:
        await conn.execute(
            """
            INSERT INTO cim_model_assets (model_id, asset_mrid)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            model_id,
            mrid,
        )
    return model_id


async def log_export(
    conn: asyncpg.Connection,
    model_id: str,
    profile: str,
    fmt: str,
    asset_count: int,
    description: str | None = None,
    created_by: str | None = None,
) -> int:
    """Record an export in the audit trail. Returns export id."""
    return await conn.fetchval(
        """
        INSERT INTO cim_exports (model_id, profile, format, asset_count, description, created_by)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        model_id,
        profile,
        fmt,
        asset_count,
        description,
        created_by,
    )


async def get_model_assets(
    conn: asyncpg.Connection,
    model_id: str,
) -> list[dict]:
    """Get all assets in a model."""
    rows = await conn.fetch(
        """
        SELECT a.mrid, a.asset_type, a.name, a.data, a.source
        FROM cim_assets a
        JOIN cim_model_assets ma ON ma.asset_mrid = a.mrid
        WHERE ma.model_id = $1
        """,
        model_id,
    )
    return [
        {
            "mrid": r["mrid"],
            "asset_type": r["asset_type"],
            "name": r["name"],
            "data": json.loads(r["data"]),
            "source": r["source"],
        }
        for r in rows
    ]


async def list_models(conn: asyncpg.Connection) -> list[dict]:
    """List all export models with asset counts."""
    rows = await conn.fetch(
        """
        SELECT ma.model_id, count(*) AS asset_count,
               max(e.created_at) AS last_export
        FROM cim_model_assets ma
        LEFT JOIN cim_exports e ON e.model_id = ma.model_id
        GROUP BY ma.model_id
        ORDER BY ma.model_id
        """
    )
    return [dict(r) for r in rows]

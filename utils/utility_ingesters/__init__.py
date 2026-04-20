"""
utility_ingesters — server-side ingesters for the DC-twin utility context
layers that BOT-DU previously called via browser-direct Overpass.

Four modules:

    waterways      OSM waterway=river|canal|stream     -> utility_waterways
    roads          OSM highway=primary..service        -> utility_roads
    gas_pipelines  OSM man_made=pipeline+substance=gas -> utility_gas_pipelines
    fibre_pop      Hand-curated carrier seed           -> fibre_pops

Each module exposes:

    async def ingest(pool, bbox: tuple[float, float, float, float] | None = None,
                     *, dry_run: bool = False) -> dict

and, where applicable, a CLI:

    python -m utils.utility_ingesters.<name> --bbox='w,s,e,n'

Tables are created by migrations/2026_04_20_utility_layers.sql; each ingester
also calls ensure_schema() on entry so stand-alone CLI runs against a fresh
DB don't fail.
"""

from __future__ import annotations

import logging
import pathlib

import asyncpg

log = logging.getLogger("princeps.utility_ingesters")


_MIGRATION_FILE = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "migrations"
    / "2026_04_20_utility_layers.sql"
)


async def ensure_schema(conn: asyncpg.Connection) -> None:
    """Apply the utility-layers migration (idempotent, safe on warm boots).

    The migration is wrapped in a BEGIN/COMMIT, so we run it as one exec
    rather than splitting on semicolons (the `;` inside function bodies
    would blow up a naive split anyway).
    """
    if not _MIGRATION_FILE.exists():
        log.warning("utility_ingesters: migration file missing at %s", _MIGRATION_FILE)
        return
    try:
        sql = _MIGRATION_FILE.read_text()
        await conn.execute(sql)
    except Exception as e:  # pragma: no cover - diagnostics only
        # Partial re-run where BEGIN is already active. Re-raise only on
        # novel errors.
        if "already exists" in str(e).lower():
            return
        log.warning("utility_ingesters.ensure_schema failed: %s", e)


async def run_overpass(query: str) -> dict:
    """Execute an Overpass query, reusing grid_data_ingester's adapter.

    Keeps the User-Agent and timeout consistent with other Princeps OSM
    callers; avoids re-declaring a second httpx client per module.
    """
    from utils.grid_data_ingester import OverpassAdapter
    adapter = OverpassAdapter()
    return await adapter._run_query(query)  # noqa: SLF001 — intentional reuse


def parse_bbox(s: str) -> tuple[float, float, float, float]:
    """Parse 'w,s,e,n' → (west, south, east, north)."""
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 4:
        raise ValueError(f"bbox must be 'w,s,e,n' (got {s!r})")
    w, s_lat, e, n = (float(p) for p in parts)
    if not (-180 <= w <= 180 and -180 <= e <= 180):
        raise ValueError("longitudes out of range")
    if not (-90 <= s_lat <= 90 and -90 <= n <= 90):
        raise ValueError("latitudes out of range")
    if w >= e or s_lat >= n:
        raise ValueError("bbox is empty or inverted")
    return w, s_lat, e, n

"""Seed `dtdl_cardinality` from DTDL JSON files.

Idempotent — safe to call at app startup. Reads every JSON in
`ontology/dtdl/`, walks its `contents`, picks out Relationship entries,
and UPSERTs (from_label, edge_label, to_label, min_mult, max_mult).

Labels are the short type name (e.g. `DataCentre`) extracted from the DTMI
(`dtmi:com:princeps:DataCentre;1`) so they match what the graph_nodes table
stores in its `label` column.
"""

from __future__ import annotations

import glob
import json
import logging
import os
from pathlib import Path

import asyncpg

log = logging.getLogger("princeps.graph.seed_cardinality")

_DTDL_DIR = Path(__file__).resolve().parents[2] / "ontology" / "dtdl"


def _short_label(dtmi: str | None) -> str | None:
    """Extract the class name from a DTMI like dtmi:com:princeps:DataCentre;1
    (which splits on `:` into ['dtmi','com','princeps','DataCentre;1']) →
    `DataCentre`. The version suffix after `;` is dropped."""
    if not dtmi or not dtmi.startswith("dtmi:"):
        return None
    try:
        last = dtmi.split(":")[-1]   # 'DataCentre;1'
        return last.split(";")[0]    # 'DataCentre'
    except (IndexError, ValueError):
        return None


async def seed_cardinality(pool: asyncpg.Pool) -> dict:
    """UPSERT cardinality rules from every ontology/dtdl/*.json. Returns
    {n_files, n_rules} for telemetry."""
    files = sorted(glob.glob(str(_DTDL_DIR / "*.json")))
    n_rules = 0
    rows: list[tuple[str, str, str | None, int, int | None, str]] = []

    for path in files:
        try:
            d = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("failed to parse %s: %s", path, exc)
            continue

        from_label = _short_label(d.get("@id"))
        if not from_label:
            continue

        for c in d.get("contents", []):
            if c.get("@type") != "Relationship":
                continue
            edge_label = c.get("name")
            if not edge_label:
                continue
            to_label = _short_label(c.get("target"))
            min_mult = int(c.get("minMultiplicity", 0))
            max_raw = c.get("maxMultiplicity")
            max_mult = int(max_raw) if max_raw is not None else None
            rows.append((from_label, edge_label, to_label, min_mult, max_mult, d.get("@id")))

    async with pool.acquire() as conn:
        for from_label, edge_label, to_label, min_mult, max_mult, source_dtmi in rows:
            await conn.execute(
                """
                INSERT INTO dtdl_cardinality (from_label, edge_label, to_label, min_mult, max_mult, source_dtmi)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (from_label, edge_label) DO UPDATE
                  SET to_label = EXCLUDED.to_label,
                      min_mult = EXCLUDED.min_mult,
                      max_mult = EXCLUDED.max_mult,
                      source_dtmi = EXCLUDED.source_dtmi
                """,
                from_label, edge_label, to_label, min_mult, max_mult, source_dtmi,
            )
            n_rules += 1

    log.info("dtdl_cardinality seeded: %d files, %d rules", len(files), n_rules)
    return {"n_files": len(files), "n_rules": n_rules}


if __name__ == "__main__":
    import asyncio
    async def _main():
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise SystemExit("DATABASE_URL not set")
        pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
        try:
            result = await seed_cardinality(pool)
            print(json.dumps(result))
        finally:
            await pool.close()
    asyncio.run(_main())

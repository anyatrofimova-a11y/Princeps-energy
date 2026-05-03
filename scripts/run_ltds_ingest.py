"""Batch runner — end-to-end LTDS ingest for all 6 UK DNOs.

What this does
--------------
1. Ensures the ``ltds_*`` schema is installed (idempotent).
2. For each DNO, looks for its source files under ``data/ltds/<dno>/``
   and, failing that, falls back to ``~/Downloads/`` (where the NGED CIM
   XML files currently live on the dev box).
3. Runs the appropriate parser:
   * **NGED** — CIM RDF/XML via :mod:`utils.ltds_cim_ingester`.
     Looks for ``LTDS_*_EQ_*.xml`` files.
   * **UKPN** — OpenDataSoft API pull via
     :mod:`utils.substation_tracker.ltds_excel_parser`.
   * **SSEN / SPEN / NPG / ENWL** — Excel workbook parsers (stubs — log a
     warning describing the expected download and move on).
4. Runs :func:`match_coordinates_fuzzy` + :func:`promote_ltds_to_grid_substations`
   so the newly-ingested rows appear in ``grid_substations`` and become
   valid endpoints for the ``grid_line_linker`` spatial snap.
5. Re-runs :func:`utils.grid_line_linker.link_grid_lines` and reports the
   before/after ``grid_lines`` link counts.

Idempotency
-----------
Every INSERT uses ``ON CONFLICT DO (UPDATE / NOTHING)`` so re-running
this script writes zero new rows once the source data is stable.

CLI usage::

    .venv/bin/python -m scripts.run_ltds_ingest
    .venv/bin/python -m scripts.run_ltds_ingest --no-linker
    .venv/bin/python -m scripts.run_ltds_ingest --dno NGED --dno UKPN
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import asyncpg

log = logging.getLogger("princeps.scripts.run_ltds_ingest")

# Paths relative to the repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "ltds"
DOWNLOADS_DIR = Path.home() / "Downloads"

ALL_DNOS = ["NGED", "UKPN", "SSEN", "SPEN", "NPG", "ENWL"]


async def _count_grid_lines_linked(conn: asyncpg.Connection) -> dict[str, int]:
    both = await conn.fetchval(
        "SELECT count(*) FROM grid_lines WHERE from_sub_id IS NOT NULL AND to_sub_id IS NOT NULL"
    ) or 0
    either = await conn.fetchval(
        "SELECT count(*) FROM grid_lines WHERE from_sub_id IS NOT NULL OR to_sub_id IS NOT NULL"
    ) or 0
    total = await conn.fetchval("SELECT count(*) FROM grid_lines") or 0
    return {"total": int(total), "either_end_linked": int(either), "both_ends_linked": int(both)}


async def _run_nged(pool: asyncpg.Pool) -> dict:
    """Run the NGED CIM RDF/XML ingester.

    Looks for LTDS_*_EQ_*.xml in (a) ``data/ltds/nged/`` then (b)
    ``~/Downloads/`` (the dev-box default).
    """
    from utils.ltds_cim_ingester import ingest_all

    nged_dir = DATA_DIR / "nged"
    xml_files = list(nged_dir.glob("LTDS_*_EQ_*.xml")) if nged_dir.exists() else []
    download_dir = nged_dir if xml_files else DOWNLOADS_DIR

    if not xml_files and not list(download_dir.glob("LTDS_*_EQ_*.xml")):
        log.warning("NGED: no LTDS XML files found in %s or %s — skipping", nged_dir, DOWNLOADS_DIR)
        return {"dno": "NGED", "ok": False, "reason": "no source files"}

    log.info("NGED: ingesting from %s", download_dir)
    summary = await ingest_all(pool, download_dir=download_dir)
    return {"dno": "NGED", "ok": True, **summary}


async def _run_ukpn(pool: asyncpg.Pool) -> dict:
    """Pull UKPN LTDS via OpenDataSoft + upsert into grid_substations.

    UKPN publishes its sites with coordinates directly; we re-use the
    existing parser and drop a thin upsert into grid_substations so the
    linker sees the points.
    """
    try:
        from utils.substation_tracker.ltds_excel_parser import (
            fetch_ukpn_ods_records, parse_ukpn_workbook,
        )
    except Exception as e:
        return {"dno": "UKPN", "ok": False, "reason": f"import failed: {e}"}

    try:
        records = await fetch_ukpn_ods_records()
    except Exception as e:
        return {"dno": "UKPN", "ok": False, "reason": f"ODS fetch failed: {e}"}

    projects = parse_ukpn_workbook(records=records)
    if not projects:
        return {"dno": "UKPN", "ok": False, "reason": "no records produced"}

    inserted = 0
    async with pool.acquire() as conn:
        for p in projects:
            if not p.geom_wkt:  # skip sites we can't place
                continue
            ext_id = f"ltds_ukpn:{p.external_ids.get('ltds', p.project_id)}"
            try:
                res = await conn.execute(
                    """
                    INSERT INTO grid_substations (
                        external_id, name, dno, region, voltage_kv, site_type, geom, raw_data
                    )
                    VALUES (
                        $1, $2, 'ukpn', $3, $4, $5,
                        ST_Transform(ST_GeomFromText($6, 4326), 27700),
                        $7::jsonb
                    )
                    ON CONFLICT (external_id, dno) DO UPDATE SET
                        voltage_kv = COALESCE(grid_substations.voltage_kv, EXCLUDED.voltage_kv),
                        site_type  = COALESCE(grid_substations.site_type,  EXCLUDED.site_type),
                        raw_data   = grid_substations.raw_data || EXCLUDED.raw_data,
                        updated_at = now()
                    """,
                    ext_id, p.substation_name, p.region, p.voltage_kv_primary,
                    p.equipment_description, p.geom_wkt,
                    json.dumps({
                        "source": "ltds_ukpn_ods",
                        "external_source": "ltds_ukpn",
                        "ltds_external_id": p.external_ids.get("ltds"),
                        "ltds_site_type": p.equipment_description,
                        "ltds_licence_area": p.region,
                        "ltds_transformer_mva": p.equipment_capacity_mva,
                    }),
                )
                if "INSERT" in res:
                    inserted += 1
            except Exception as e:
                log.debug("UKPN upsert skipped %s: %s", ext_id, e)
                continue
    log.info("UKPN: upserted %d rows into grid_substations", inserted)
    return {"dno": "UKPN", "ok": True, "records_fetched": len(records),
            "projects_parsed": len(projects), "upserted": inserted}


async def _run_excel_stub(dno: str) -> dict:
    """Report missing Excel sources for the stubbed DNOs.

    These DNOs publish annual LTDS workbooks that have to be downloaded
    manually because they're hosted behind click-wrap on each DNO portal.
    We inspect ``data/ltds/<dno>/`` and report what's found (or isn't).
    """
    dno_dir = DATA_DIR / dno.lower()
    if not dno_dir.exists():
        return {"dno": dno, "ok": False,
                "reason": f"directory missing: {dno_dir} — see data/ltds/README.md"}

    xlsx_files = list(dno_dir.glob("*.xlsx"))
    if not xlsx_files:
        return {"dno": dno, "ok": False,
                "reason": f"no .xlsx files in {dno_dir} — see data/ltds/README.md for download URLs"}

    # Parser stubs are still in place — we surface what we found and wait
    # for the DNO-specific column-mapping implementation.
    return {"dno": dno, "ok": False,
            "reason": f"found {len(xlsx_files)} workbook(s) but parser is a stub — "
                      f"see utils/substation_tracker/ltds_excel_parser.py",
            "workbooks": [p.name for p in xlsx_files]}


async def run_all(pool: asyncpg.Pool, *, dnos: list[str], run_linker: bool = True) -> dict:
    """Run ingest for each selected DNO, then the linker."""
    from utils.ltds_cim_ingester import (
        ensure_schema, match_coordinates_fuzzy, promote_ltds_to_grid_substations,
    )

    await ensure_schema(pool)

    async with pool.acquire() as conn:
        before_links = await _count_grid_lines_linked(conn)
        before_subs = await conn.fetchval("SELECT count(*) FROM grid_substations") or 0
        before_ltds = await conn.fetchval("SELECT count(*) FROM ltds_substations") or 0

    per_dno: list[dict] = []
    for dno in dnos:
        if dno == "NGED":
            per_dno.append(await _run_nged(pool))
        elif dno == "UKPN":
            per_dno.append(await _run_ukpn(pool))
        else:
            per_dno.append(await _run_excel_stub(dno))

    # Run the match + promote passes even if some DNOs were stubs — UKPN
    # inserts arrive directly in grid_substations, NGED already ran its
    # own match in ingest_all, but running again is cheap + idempotent.
    matched = await match_coordinates_fuzzy(pool)
    promoted = await promote_ltds_to_grid_substations(pool)

    linker_summary = None
    if run_linker:
        from utils.grid_line_linker import link_grid_lines
        async with pool.acquire() as conn:
            linker_summary = await link_grid_lines(
                conn, max_distance_m=100, batch_size=5000, dry_run=False,
            )

    async with pool.acquire() as conn:
        after_links = await _count_grid_lines_linked(conn)
        after_subs = await conn.fetchval("SELECT count(*) FROM grid_substations") or 0
        after_ltds = await conn.fetchval("SELECT count(*) FROM ltds_substations") or 0
        ltds_with_coords = await conn.fetchval(
            "SELECT count(*) FROM ltds_substations WHERE lat IS NOT NULL"
        ) or 0

    return {
        "per_dno": per_dno,
        "match_coordinates_updated": matched,
        "promoted": promoted,
        "linker": linker_summary,
        "counts_before": {
            "grid_substations": int(before_subs),
            "ltds_substations": int(before_ltds),
            **before_links,
        },
        "counts_after": {
            "grid_substations": int(after_subs),
            "ltds_substations": int(after_ltds),
            "ltds_substations_with_coords": int(ltds_with_coords),
            **after_links,
        },
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dno", action="append", choices=ALL_DNOS, default=None,
        help="DNOs to ingest (repeat flag). Default: all 6.",
    )
    parser.add_argument(
        "--no-linker", action="store_true",
        help="Skip the grid_line_linker re-run after ingest.",
    )
    parser.add_argument(
        "--db-url", default=os.environ.get("DATABASE_URL"),
        help="Postgres DSN (defaults to $DATABASE_URL).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if not args.db_url:
        log.error("No DATABASE_URL set and --db-url not provided.")
        return 2

    dnos = args.dno or ALL_DNOS
    pool = await asyncpg.create_pool(args.db_url, min_size=1, max_size=3)
    try:
        summary = await run_all(pool, dnos=dnos, run_linker=not args.no_linker)
        print(json.dumps(summary, indent=2, default=str))
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))

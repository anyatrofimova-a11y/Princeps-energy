"""Spatial audit + migration runner for the feasibly (Princeps) database.

Default mode: read-only audit — prints a table of every geometry column with
its schema, table, column, SRID, and whether a GiST index is present on it.

With ``--apply``: runs the two canonicalisation migrations
(``migrations/2026_04_19_srid_canon.sql`` + ``migrations/2026_04_19_spatial_indexes.sql``)
via ``psql`` and then re-runs the audit so the operator can confirm the
resulting state.

Usage:
    python utils/db_spatial_audit.py              # audit only
    python utils/db_spatial_audit.py --apply      # run migrations then re-audit

Environment overrides (defaults in parentheses):
    PSQL_BIN   (/opt/homebrew/opt/postgresql@17/bin/psql)
    PGHOST     (localhost)
    PGPORT     (5432)
    PGDATABASE (feasibly)
    PGUSER     (current OS user)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

DEFAULT_PSQL = "/opt/homebrew/opt/postgresql@17/bin/psql"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = "5432"
DEFAULT_DB = "feasibly"

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = [
    REPO_ROOT / "migrations" / "2026_04_19_srid_canon.sql",
    REPO_ROOT / "migrations" / "2026_04_19_spatial_indexes.sql",
]

AUDIT_SQL = """
SELECT
    gc.f_table_schema  AS schema,
    gc.f_table_name    AS table_name,
    gc.f_geometry_column AS column_name,
    gc.srid            AS srid,
    gc.type            AS geom_type,
    CASE WHEN EXISTS (
        SELECT 1
        FROM pg_index x
        JOIN pg_class c      ON c.oid = x.indrelid
        JOIN pg_class i      ON i.oid = x.indexrelid
        JOIN pg_namespace n  ON n.oid = c.relnamespace
        JOIN pg_am am        ON am.oid = i.relam
        JOIN pg_attribute a  ON a.attrelid = c.oid AND a.attnum = ANY (x.indkey)
        WHERE am.amname = 'gist'
          AND n.nspname = gc.f_table_schema
          AND c.relname = gc.f_table_name
          AND a.attname = gc.f_geometry_column
    ) THEN 't' ELSE 'f' END AS has_gist
FROM geometry_columns gc
ORDER BY gc.f_table_schema, gc.f_table_name, gc.f_geometry_column;
"""


def _psql_cmd() -> List[str]:
    psql = os.environ.get("PSQL_BIN", DEFAULT_PSQL)
    host = os.environ.get("PGHOST", DEFAULT_HOST)
    port = os.environ.get("PGPORT", DEFAULT_PORT)
    db = os.environ.get("PGDATABASE", DEFAULT_DB)
    cmd = [psql, "-h", host, "-p", port, "-d", db]
    user = os.environ.get("PGUSER")
    if user:
        cmd += ["-U", user]
    return cmd


def _run_sql(sql: str) -> str:
    cmd = _psql_cmd() + ["-At", "-F", "\t", "-c", sql]
    result = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _run_sql_file(path: Path) -> None:
    cmd = _psql_cmd() + ["-v", "ON_ERROR_STOP=1", "-f", str(path)]
    subprocess.run(cmd, check=True)


def _parse_audit(raw: str) -> List[Tuple[str, str, str, int, str, bool]]:
    rows: List[Tuple[str, str, str, int, str, bool]] = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        schema, table, column, srid, gtype, gist = parts[:6]
        rows.append((schema, table, column, int(srid), gtype, gist == "t"))
    return rows


def _print_audit(rows: List[Tuple[str, str, str, int, str, bool]], title: str) -> None:
    print()
    print(f"=== {title} ({len(rows)} geometry columns) ===")
    header = ("schema", "table", "column", "srid", "type", "gist")
    widths = [
        max(len(header[0]), *(len(r[0]) for r in rows)) if rows else len(header[0]),
        max(len(header[1]), *(len(r[1]) for r in rows)) if rows else len(header[1]),
        max(len(header[2]), *(len(r[2]) for r in rows)) if rows else len(header[2]),
        max(len(header[3]), *(len(str(r[3])) for r in rows)) if rows else len(header[3]),
        max(len(header[4]), *(len(r[4]) for r in rows)) if rows else len(header[4]),
        max(len(header[5]), 5),
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*header))
    print(fmt.format(*("-" * w for w in widths)))
    for schema, table, column, srid, gtype, has_gist in rows:
        print(
            fmt.format(
                schema,
                table,
                column,
                srid,
                gtype,
                "yes" if has_gist else "NO",
            )
        )
    missing = [r for r in rows if not r[5]]
    zero_srid = [r for r in rows if r[3] == 0]
    print()
    print(f"summary: {len(rows)} columns, "
          f"{len(missing)} missing GiST, "
          f"{len(zero_srid)} with SRID=0")
    if missing:
        print("missing GiST:")
        for r in missing:
            print(f"  - {r[0]}.{r[1]}.{r[2]}")
    if zero_srid:
        print("SRID=0:")
        for r in zero_srid:
            print(f"  - {r[0]}.{r[1]}.{r[2]}")


def run_audit(title: str = "audit") -> List[Tuple[str, str, str, int, str, bool]]:
    raw = _run_sql(AUDIT_SQL)
    rows = _parse_audit(raw)
    _print_audit(rows, title)
    return rows


def apply_migrations() -> None:
    for path in MIGRATIONS:
        if not path.exists():
            raise FileNotFoundError(f"migration not found: {path}")
        print(f"\n--- applying {path.name} ---")
        _run_sql_file(path)
        print(f"--- {path.name} OK ---")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run the canonicalisation migrations then re-audit.",
    )
    args = parser.parse_args()

    try:
        run_audit("as-was audit")
        if args.apply:
            apply_migrations()
            run_audit("post-migration audit")
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip() if hasattr(exc, "stderr") else ""
        print(f"psql failed (exit {exc.returncode}): {stderr}", file=sys.stderr)
        return exc.returncode or 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

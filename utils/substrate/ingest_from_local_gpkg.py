"""
Bulk-load a locally-downloaded EA Flood Map for Planning GeoPackage into
Princeps PostGIS tables (ea_flood_zone_2 / ea_flood_zone_3).

Why this exists
---------------
April 2025: Defra retired the EA WFS / WMS endpoints (every documented
URL now 404s) and moved bulk Flood Zone downloads behind the Agrimetrics
data marketplace. Agrimetrics needs an Ocp-Apim-Subscription-Key for
programmatic access. Until that key is provisioned, the only reliable
path is the manual web download → ogr2ogr → PostGIS dance below.

How to get the gpkg (no payment, free signup):
    1.  https://app.agrimetrics.co.uk/  →  free account
    2.  Open dataset: Flood_Map_for_Planning_Flood_Zones
        (id 455d2eb3-3065-4d20-871b-c4d5dee23f67)
    3.  Click "Download" → choose .gpkg.zip (~ 280 MB)
    4.  Unzip into  data/ea_flood/
    5.  Run:
            python -m utils.substrate.ingest_from_local_gpkg \\
                data/ea_flood/Flood_Map_for_Planning_Flood_Zones.gpkg

Alternative source if Agrimetrics blocks you:
    -  https://environment.data.gov.uk/dataset/04532375-a198-476e-985e-0579a0a11b47
       (the same dataset's data.gov.uk record links back to Agrimetrics)
    -  Wales:    https://datamap.gov.wales/maps/inspire/wales-flood-risk
    -  Scotland: https://map.sepa.org.uk/floodmaps/

What this script does
---------------------
1. Inspects the gpkg layers (typically two: "Flood_Zone_2" and "Flood_Zone_3")
2. Uses ogr2ogr to bulk-load each layer to a staging table (one COPY per
   layer; far faster than per-row INSERT via psycopg/asyncpg).
3. Promotes the staging rows into the canonical ea_flood_zone_2 /
   ea_flood_zone_3 tables, projecting to EPSG:4326 (geography) and
   keeping only the columns the Princeps app reads.
4. Writes a row to ea_ingest_log so the ops dashboard can see when the
   bulk load happened.

Idempotent: re-running with the same gpkg upserts on feature_id.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("princeps.ea_flood_local_gpkg")

# Database URL — the same one the FastAPI app uses.
DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://anyatrofimova@localhost:5432/feasibly",
)

# Layers we expect inside the gpkg (Defra naming as of 2025).
EXPECTED_LAYERS = {
    2: ["Flood_Zone_2", "Flood Zone 2", "FloodZone2"],
    3: ["Flood_Zone_3", "Flood Zone 3", "FloodZone3"],
}


def _check_ogr2ogr() -> str:
    path = shutil.which("ogr2ogr")
    if not path:
        sys.exit(
            "ogr2ogr not found. Install GDAL:\n"
            "    brew install gdal     # macOS\n"
            "    apt install gdal-bin  # Debian/Ubuntu"
        )
    return path


def _list_gpkg_layers(gpkg: Path) -> list[str]:
    """Use ogrinfo -ro -al -so to list layer names."""
    try:
        out = subprocess.check_output(
            ["ogrinfo", "-ro", "-q", str(gpkg)],
            text=True, timeout=60,
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"ogrinfo failed: {exc.output}")
    layers: list[str] = []
    for line in out.splitlines():
        # Lines look like: "1: Flood_Zone_2 (Multi Polygon)"
        if ":" in line:
            after = line.split(":", 1)[1].strip()
            name = after.split(" (")[0].strip()
            if name:
                layers.append(name)
    return layers


def _resolve_layer_name(gpkg_layers: list[str], wanted: list[str]) -> str | None:
    norm = {l.replace(" ", "").replace("_", "").lower(): l for l in gpkg_layers}
    for w in wanted:
        key = w.replace(" ", "").replace("_", "").lower()
        if key in norm:
            return norm[key]
    return None


def _ingest_zone(gpkg: Path, layer_name: str, target_table: str) -> int:
    """ogr2ogr load → staging → upsert into target table.

    Returns the number of features loaded into staging.
    """
    staging = f"{target_table}_staging"
    log.info("Loading %s → %s (staging %s)", layer_name, target_table, staging)
    # Drop any existing staging table to keep this idempotent.
    subprocess.run(
        ["psql", DB_URL, "-c", f"DROP TABLE IF EXISTS {staging};"],
        check=True, timeout=60,
    )
    # Use -t_srs to land geometries already projected to 4326 (geography
    # in the canonical table). -lco precision=NO speeds the load.
    cmd = [
        "ogr2ogr", "-f", "PostgreSQL",
        f"PG:{DB_URL}",
        str(gpkg),
        layer_name,
        "-nln", staging,
        "-t_srs", "EPSG:4326",
        "-overwrite",
        "-progress",
        "-lco", "GEOMETRY_NAME=geom",
        "-lco", "FID=feature_id",
        "-lco", "PRECISION=NO",
        "-nlt", "MULTIPOLYGON",
    ]
    subprocess.run(cmd, check=True, timeout=1800)
    # How many rows landed?
    out = subprocess.check_output(
        ["psql", DB_URL, "-tAc", f"SELECT COUNT(*) FROM {staging};"],
        text=True, timeout=30,
    )
    n = int(out.strip())
    log.info("  staging %s rows: %d", staging, n)

    # Promote into canonical table. The canonical table uses geography(4326)
    # and a feature_id text PK; we cast and ON CONFLICT upsert.
    promote_sql = f"""
        INSERT INTO {target_table} (feature_id, geom, ingested_at)
        SELECT
            COALESCE(feature_id::text, gen_random_uuid()::text),
            geom::geography,
            now()
        FROM {staging}
        ON CONFLICT (feature_id) DO UPDATE
          SET geom = EXCLUDED.geom,
              ingested_at = EXCLUDED.ingested_at;
    """
    subprocess.run(
        ["psql", DB_URL, "-c", promote_sql],
        check=True, timeout=600,
    )
    # Drop staging now we're done.
    subprocess.run(
        ["psql", DB_URL, "-c", f"DROP TABLE IF EXISTS {staging};"],
        check=True, timeout=60,
    )
    return n


def _log_run(rows_z2: int, rows_z3: int) -> None:
    sql = """
        INSERT INTO ea_ingest_log
            (dataset, bbox_min_lon, bbox_min_lat, bbox_max_lon, bbox_max_lat,
             features_fetched, features_upserted, status, started_at, finished_at)
        VALUES
            ('flood_map_planning_local_gpkg', -8, 49, 2, 61, $1, $2, 'ok',
             now(), now());
    """.replace("$1", str(rows_z2 + rows_z3)).replace("$2", str(rows_z2 + rows_z3))
    try:
        subprocess.run(["psql", DB_URL, "-c", sql], check=True, timeout=30)
    except Exception as exc:
        log.warning("ea_ingest_log row insert failed (non-fatal): %s", exc)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("gpkg", type=Path,
                    help="Path to Flood_Map_for_Planning_Flood_Zones.gpkg")
    ap.add_argument("--zones", nargs="+", type=int, default=[2, 3],
                    help="Subset of zones to load (default: 2 3)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _check_ogr2ogr()

    if not args.gpkg.exists():
        sys.exit(f"file not found: {args.gpkg}")

    layers = _list_gpkg_layers(args.gpkg)
    log.info("gpkg layers: %s", layers)

    counts: dict[int, int] = {}
    for zone in args.zones:
        wanted = EXPECTED_LAYERS.get(zone, [])
        layer_name = _resolve_layer_name(layers, wanted)
        if not layer_name:
            log.warning("no layer matching zone %s in gpkg (looked for %s)",
                        zone, wanted)
            counts[zone] = 0
            continue
        counts[zone] = _ingest_zone(
            args.gpkg, layer_name, f"ea_flood_zone_{zone}",
        )

    _log_run(counts.get(2, 0), counts.get(3, 0))
    log.info("DONE — Zone 2: %d, Zone 3: %d", counts.get(2, 0), counts.get(3, 0))


if __name__ == "__main__":
    main()

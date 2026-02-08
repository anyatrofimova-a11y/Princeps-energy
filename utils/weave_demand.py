"""
Weave Smart Meter Demand — load substation-level consumption from Weave's S3.

Data lives at s3://weave.energy/smart-meter as partitioned GeoParquet,
sorted by timestamp, DNO, substation, feeder.

We pull one recent settlement period, aggregate to substation level,
filter outliers, and upsert into PostGIS table `smart_meter_demand`.
"""

import logging
import math
import pyarrow.parquet as pq
import s3fs

log = logging.getLogger("princeps.weave")

S3_BUCKET = "weave.energy"
S3_PREFIX = "smart-meter"

# Wh cap — any single-reading above this is treated as an outlier
OUTLIER_WH = 20_000


async def setup_demand_table(conn):
    """Create smart_meter_demand table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS smart_meter_demand (
            substation_id TEXT PRIMARY KEY,
            substation_name TEXT,
            dno TEXT,
            total_kwh DOUBLE PRECISION,
            meter_count INTEGER,
            kwh_per_meter DOUBLE PRECISION,
            geometry GEOMETRY(Point, 27700)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_demand_geom
        ON smart_meter_demand USING GIST (geometry)
    """)


def _extract_coords(geom):
    """Extract (lon, lat) from Weave's geometry struct {'x': lon, 'y': lat}.

    Returns (lon, lat) or None if invalid/NaN.
    """
    try:
        if isinstance(geom, dict):
            lon = float(geom.get("x", float("nan")))
            lat = float(geom.get("y", float("nan")))
        elif hasattr(geom, "x"):
            lon, lat = float(geom.x), float(geom.y)
        else:
            return None
        if math.isnan(lon) or math.isnan(lat) or lon == 0 or lat == 0:
            return None
        return (lon, lat)
    except (TypeError, ValueError):
        return None


def _load_from_s3():
    """Read the most recent settlement period from Weave's S3 bucket.

    Returns a list of dicts with substation-level aggregates, or []
    on any failure (network, auth, empty data).
    """
    try:
        fs = s3fs.S3FileSystem(anon=True)

        # List parquet files and pick the last one (most recent partition)
        files = fs.ls(f"{S3_BUCKET}/{S3_PREFIX}", detail=False)
        parquet_files = sorted(f for f in files if f.endswith(".parquet"))
        if not parquet_files:
            log.warning("No parquet files found in s3://%s/%s", S3_BUCKET, S3_PREFIX)
            return []

        latest = parquet_files[-1]
        log.info("Reading Weave demand from s3://%s", latest)

        # Read the full file — we need all columns for filtering + aggregation
        table = pq.read_table(
            latest,
            filesystem=fs,
            columns=[
                "secondary_substation_unique_id",
                "dno_alias",
                "total_consumption_active_import",
                "aggregated_device_count_active",
                "data_collection_log_timestamp",
                "geometry",
            ],
        )

        df = table.to_pandas()
        if df.empty:
            log.warning("Weave parquet file was empty")
            return []

        log.info("Loaded %d raw rows from Weave", len(df))

        # Filter to latest settlement period only (data sorted by timestamp)
        latest_ts = df["data_collection_log_timestamp"].max()
        df = df[df["data_collection_log_timestamp"] == latest_ts]
        log.info("Filtered to settlement period %s: %d rows", latest_ts, len(df))

        # Filter outliers
        df = df[df["total_consumption_active_import"] <= OUTLIER_WH]

        # Extract lon/lat from struct geometry {'x': lon, 'y': lat}
        df["_coords"] = df["geometry"].apply(_extract_coords)
        df = df[df["_coords"].notna()]
        df["lon"] = df["_coords"].apply(lambda c: c[0])
        df["lat"] = df["_coords"].apply(lambda c: c[1])

        log.info("Rows with valid geometry: %d", len(df))

        # Aggregate to substation level
        agg = df.groupby("secondary_substation_unique_id").agg(
            total_wh=("total_consumption_active_import", "sum"),
            meter_count=("aggregated_device_count_active", "max"),
            dno=("dno_alias", "first"),
            lon=("lon", "first"),
            lat=("lat", "first"),
        ).reset_index()

        results = []
        for _, row in agg.iterrows():
            total_kwh = row["total_wh"] / 1000.0
            meter_count = int(row["meter_count"]) if row["meter_count"] else 1
            results.append({
                "substation_id": row["secondary_substation_unique_id"],
                "dno": row["dno"] or "unknown",
                "total_kwh": total_kwh,
                "meter_count": meter_count,
                "kwh_per_meter": total_kwh / max(meter_count, 1),
                "lon": row["lon"],
                "lat": row["lat"],
            })

        log.info("Loaded %d substations from Weave", len(results))
        return results

    except Exception as e:
        log.warning("Failed to load Weave demand data: %s", e)
        return []


async def seed_demand(conn):
    """Load Weave data from S3 and upsert into smart_meter_demand table.

    Skips seeding if the table already has rows (avoids re-downloading on restart).
    """
    count = await conn.fetchval("SELECT count(*) FROM smart_meter_demand")
    if count > 0:
        log.info("smart_meter_demand already has %d rows — skipping seed", count)
        return

    rows = _load_from_s3()
    if not rows:
        log.info("No Weave demand data to seed")
        return

    for r in rows:
        await conn.execute(
            """
            INSERT INTO smart_meter_demand
                (substation_id, dno, total_kwh, meter_count, kwh_per_meter, geometry)
            VALUES ($1, $2, $3, $4, $5,
                    ST_Transform(ST_SetSRID(ST_MakePoint($6, $7), 4326), 27700))
            ON CONFLICT (substation_id) DO UPDATE SET
                total_kwh = EXCLUDED.total_kwh,
                meter_count = EXCLUDED.meter_count,
                kwh_per_meter = EXCLUDED.kwh_per_meter
            """,
            r["substation_id"], r["dno"],
            r["total_kwh"], r["meter_count"], r["kwh_per_meter"],
            r["lon"], r["lat"],
        )

    log.info("Seeded %d Weave demand substations", len(rows))


async def demand_geojson(conn):
    """Return smart_meter_demand as a GeoJSON FeatureCollection (WGS84)."""
    rows = await conn.fetch("""
        SELECT substation_id, substation_name, dno, total_kwh, meter_count,
               kwh_per_meter,
               ST_X(ST_Transform(geometry, 4326)) AS lon,
               ST_Y(ST_Transform(geometry, 4326)) AS lat
        FROM smart_meter_demand
        ORDER BY total_kwh DESC
    """)

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r["lon"]), float(r["lat"])],
            },
            "properties": {
                "substation_id": r["substation_id"],
                "name": r["substation_name"] or r["substation_id"],
                "dno": r["dno"],
                "total_kwh": round(r["total_kwh"], 2),
                "meter_count": r["meter_count"],
                "kwh_per_meter": round(r["kwh_per_meter"], 2),
            },
        })

    return {"type": "FeatureCollection", "features": features}

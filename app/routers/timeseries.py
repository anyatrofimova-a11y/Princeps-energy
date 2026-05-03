"""``/api/timeseries`` — generic time-series store query surface.

Backs the Slate ``TimeSeriesChart`` widget. The underlying ``time_series``
table (see ``migrations/2026_05_03_time_series.sql``) is one row per
sensor reading; this router serves binned aggregations so a 30-day window
collapses cleanly into a sparkline-friendly 200-point series.

Endpoints
---------

  GET /api/timeseries
        ?sensor_id=bmrs.system_buy_price
        &bin=raw|5m|30m|1h|1d            (default: 1h)
        &from=2026-04-25T00:00Z          (default: now - 7d)
        &to=2026-05-02T00:00Z            (default: now)
        &limit=2000                      (cap on returned points)

      Returns binned (AVG, MIN, MAX, COUNT) buckets plus echoed window
      metadata.

  GET /api/timeseries/sensors
      Distinct sensor_ids with their row counts and ts span.

Notes
-----
* No TimescaleDB. Plain Postgres ``date_trunc`` for h/d bins and an
  ``floor(epoch / N) * N`` arithmetic bucket for sub-hour bins.
* Bin parameter is whitelisted — ALL SQL strings are computed from a
  fixed map, never spliced from user input.
* If ``raw`` is requested the rows come back ungrouped; min/max/count
  per row are still emitted so the frontend payload shape is invariant.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_pool as _raw_pool  # noqa: F401
from app.middleware.tenant_jwt import get_tenant_pool as get_pool

log = logging.getLogger("princeps.timeseries")

router = APIRouter(prefix="/api/timeseries", tags=["timeseries"])


# ---------------------------------------------------------------------------
# Bin specification — whitelisted to keep the SQL injection surface flat.
# Each entry is (bucket-mode, seconds-or-trunc-arg).
# ---------------------------------------------------------------------------
_BIN_SECONDS = {
    "5m": 300,
    "30m": 1800,
}
_BIN_TRUNC = {
    "1h": "hour",
    "1d": "day",
}
_BIN_RAW = {"raw"}
_ALL_BINS = set(_BIN_SECONDS) | set(_BIN_TRUNC) | _BIN_RAW


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_iso(s: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp; return UTC-aware datetime or None.

    Accepts ``...Z`` shorthand which Python's stdlib only learned in 3.11.
    Bare dates ('2026-04-25') are accepted too — interpreted as midnight UTC.
    """
    if not s:
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError as exc:
        raise HTTPException(400, f"invalid timestamp {s!r}: {exc}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_iso(v: Any) -> Any:
    """Normalise a row value for JSON output (TIMESTAMPTZ → ISO string,
    NUMERIC → float so JS can do arithmetic without BigInt fumbles)."""
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    # asyncpg returns NUMERIC as decimal.Decimal — JSON-encodes fine but
    # the frontend treats it as a string. Cast to float for chart code.
    try:
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
    except Exception:  # pragma: no cover
        pass
    return v


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/sensors")
async def list_sensors(pool: asyncpg.Pool = Depends(get_pool)) -> dict[str, Any]:
    """Distinct sensor_ids with row count + ts span.

    Cheap aggregate; relies on the ``idx_ts_sensor_ts`` covering index for
    the per-sensor min/max scans.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              sensor_id,
              COUNT(*)::bigint AS count,
              MIN(ts) AS first_ts,
              MAX(ts) AS last_ts,
              MAX(label) AS label
            FROM time_series
            GROUP BY sensor_id
            ORDER BY sensor_id ASC
            """
        )
    sensors = [
        {
            "sensor_id": r["sensor_id"],
            "count": int(r["count"]),
            "first_ts": _row_iso(r["first_ts"]),
            "last_ts": _row_iso(r["last_ts"]),
            "label": r["label"],
        }
        for r in rows
    ]
    return {"sensors": sensors, "count": len(sensors)}


@router.get("")
async def query_timeseries(
    sensor_id: str = Query(..., min_length=1, max_length=200),
    bin: str = Query("1h", description="raw|5m|30m|1h|1d"),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    limit: int = Query(2000, ge=1, le=20000),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Binned aggregation of one sensor over a time window.

    Returns one bucket per ``bin`` step within ``[from, to)``; the bucket
    timestamp is the LEFT edge (i.e. start) so the frontend can plot it
    as a step series.
    """
    if bin not in _ALL_BINS:
        raise HTTPException(400, f"bin must be one of {sorted(_ALL_BINS)}")

    now = datetime.now(timezone.utc)
    t_from = _parse_iso(from_) or (now - timedelta(days=7))
    t_to = _parse_iso(to) or now
    if t_from >= t_to:
        raise HTTPException(400, "`from` must be earlier than `to`")

    async with pool.acquire() as conn:
        if bin == "raw":
            rows = await conn.fetch(
                """
                SELECT ts, value AS avg, value AS min, value AS max, 1::bigint AS count
                FROM time_series
                WHERE sensor_id = $1 AND ts >= $2 AND ts < $3
                ORDER BY ts ASC
                LIMIT $4
                """,
                sensor_id, t_from, t_to, limit,
            )
        elif bin in _BIN_TRUNC:
            trunc_arg = _BIN_TRUNC[bin]  # 'hour' | 'day' — whitelisted above
            sql = f"""
                SELECT
                  date_trunc('{trunc_arg}', ts) AS ts,
                  AVG(value)::numeric AS avg,
                  MIN(value)::numeric AS min,
                  MAX(value)::numeric AS max,
                  COUNT(*)::bigint   AS count
                FROM time_series
                WHERE sensor_id = $1 AND ts >= $2 AND ts < $3
                GROUP BY 1
                ORDER BY 1 ASC
                LIMIT $4
            """
            rows = await conn.fetch(sql, sensor_id, t_from, t_to, limit)
        else:  # _BIN_SECONDS — sub-hour arithmetic bucket
            secs = _BIN_SECONDS[bin]
            sql = f"""
                SELECT
                  to_timestamp(
                    floor(extract(epoch FROM ts) / {secs}) * {secs}
                  ) AT TIME ZONE 'UTC' AS ts,
                  AVG(value)::numeric AS avg,
                  MIN(value)::numeric AS min,
                  MAX(value)::numeric AS max,
                  COUNT(*)::bigint   AS count
                FROM time_series
                WHERE sensor_id = $1 AND ts >= $2 AND ts < $3
                GROUP BY 1
                ORDER BY 1 ASC
                LIMIT $4
            """
            rows = await conn.fetch(sql, sensor_id, t_from, t_to, limit)

    points = [
        {
            "ts": _row_iso(r["ts"]),
            "value": _row_iso(r["avg"]),
            "min": _row_iso(r["min"]),
            "max": _row_iso(r["max"]),
            "count": int(r["count"]),
        }
        for r in rows
    ]
    return {
        "sensor_id": sensor_id,
        "bin": bin,
        "from": t_from.isoformat(),
        "to": t_to.isoformat(),
        "points": points,
        "count": len(points),
    }

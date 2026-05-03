"""Smoke test — fire bmrs_settlement_prices via the scheduler, verify a
connector_schedule_log row lands.

Usage
-----
    .venv/bin/python -m scripts.test_connector_scheduler

Expects PostgreSQL up at the standard local URL (DATABASE_URL env or
the default in app/main.py). Does NOT require uvicorn — it builds its
own pool, scheduler instance, and calls fire_now() directly.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import asyncpg


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost:5432/feasibly",
)


async def main() -> int:
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    try:
        # Import + register every connector subclass so the registry walk
        # has something to find.
        from app.connectors.startup import register_all_connectors
        await register_all_connectors(pool)

        from app.cron.connector_scheduler import ConnectorScheduler

        # Build a tiny app-shim so ConnectorScheduler.app.state works.
        class _Shim:
            class state:  # type: ignore[no-redef]
                pass
        shim = _Shim()
        shim.state = type("S", (), {})()

        cs = ConnectorScheduler(pool, shim)
        summary = await cs.start()
        print(f"scheduler started: {summary}")

        slug = "bmrs_settlement_prices"
        fire = cs.fire_now(slug)
        print(f"fire_now({slug}): {fire}")
        if not fire.get("ok"):
            print("fire_now did not schedule — bailing")
            cs.stop()
            return 1

        # Poll connector_schedule_log for up to 60 s waiting for any row.
        deadline = time.monotonic() + 60
        row = None
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, slug, ok, rows_ingested, error, duration_ms
                    FROM connector_schedule_log
                    WHERE slug = $1
                    ORDER BY fired_at DESC
                    LIMIT 1
                    """,
                    slug,
                )
            if row is not None:
                break
        cs.stop()
        if row is None:
            print("ERROR: no connector_schedule_log row appeared within 60s")
            return 2
        print("schedule_log row:", dict(row))
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

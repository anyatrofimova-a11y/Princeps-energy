"""app.cron — in-process scheduled background jobs.

Lightweight pattern: each module exposes ``async def start(pool)`` that
``app/startup.py`` fires via ``asyncio.create_task``. No APScheduler dep.
"""

"""
Async job runner with in-memory cache + PostgreSQL write-through.

Jobs run in background asyncio tasks.  Results are kept in an in-memory dict
(fast reads) and written through to the ``background_jobs`` table for
persistence across restarts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

log = logging.getLogger("princeps.jobs")

# Optional pool — set via ``init_pool()`` at startup so we can persist.
_pool = None


def init_pool(pool) -> None:
    """Set the asyncpg pool for write-through persistence."""
    global _pool
    _pool = pool


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus = JobStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_s": round(self.finished_at - self.started_at, 2)
            if self.started_at and self.finished_at
            else None,
            "result": self.result,
            "error": self.error,
        }


# In-memory cache (fast reads)
_jobs: dict[str, Job] = {}


async def _db_upsert(job: Job) -> None:
    """Write-through to background_jobs table (best-effort)."""
    if _pool is None:
        return
    try:
        result_json = json.dumps(job.result, default=str) if job.result is not None else None
        from datetime import datetime, timezone
        started = datetime.fromtimestamp(job.started_at, tz=timezone.utc) if job.started_at else None
        finished = datetime.fromtimestamp(job.finished_at, tz=timezone.utc) if job.finished_at else None
        created = datetime.fromtimestamp(job.created_at, tz=timezone.utc)
        await _pool.execute(
            """INSERT INTO background_jobs (job_id, kind, status, result_data, error,
                                            created_at, started_at, finished_at)
               VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8)
               ON CONFLICT (job_id) DO UPDATE SET
                 status = EXCLUDED.status,
                 result_data = EXCLUDED.result_data,
                 error = EXCLUDED.error,
                 started_at = EXCLUDED.started_at,
                 finished_at = EXCLUDED.finished_at""",
            job.id, job.kind, job.status.value,
            result_json, job.error,
            created, started, finished,
        )
    except Exception as e:
        log.warning("Failed to persist job %s: %s", job.id, e)


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def list_jobs(kind: str | None = None, limit: int = 50) -> list[dict]:
    jobs = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)
    if kind:
        jobs = [j for j in jobs if j.kind == kind]
    return [j.to_dict() for j in jobs[:limit]]


async def submit(
    kind: str,
    coro_factory: Callable[..., Coroutine],
    *args: Any,
    **kwargs: Any,
) -> Job:
    """
    Submit a coroutine to run as a background job.

    Usage:
        job = await submit("grid_study", run_grid_study, parcel_id, capacity_kw)
    """
    job = Job(id=uuid.uuid4().hex[:12], kind=kind)
    _jobs[job.id] = job
    await _db_upsert(job)

    async def _run():
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        await _db_upsert(job)
        try:
            job.result = await coro_factory(*args, **kwargs)
            job.status = JobStatus.DONE
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
        finally:
            job.finished_at = time.time()
            await _db_upsert(job)

    asyncio.create_task(_run())
    return job

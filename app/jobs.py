"""
In-memory async job runner for heavy backend tasks.

Jobs run in background asyncio tasks and store results in a dict.
For production, swap the dict for Redis or Postgres-backed store.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine


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


# Global job store  (swap for Redis / PG in production)
_jobs: dict[str, Job] = {}


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

    async def _run():
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        try:
            job.result = await coro_factory(*args, **kwargs)
            job.status = JobStatus.DONE
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
        finally:
            job.finished_at = time.time()

    asyncio.create_task(_run())
    return job

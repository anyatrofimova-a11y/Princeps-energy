"""Earth-Observation pipeline orchestrator (Swarm 7).

Replaces per-site GEE jobs with regional/national batched extraction.
Uses DeepMind geeflow patterns (Apache Beam) for the heavy compute,
forest_typology + Prithvi as add-on heads.

Phase 1 surface (this file): scheduler entry-points + job registry. The
heavy Beam pipelines live in their own files and are dispatched via
the existing utils/geeflow_runner.py subprocess bridge.

Job types:
  • landcover_weekly   — DynamicWorld V1 mode composite, national tiles
  • forest_typology    — annual planted-vs-natural map (CC-BY)
  • burn_scars         — Prithvi burn-scar segmentation, on-event
  • asset_condition    — drone/sat TAPNet change detection per portfolio asset
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("princeps.eo_pipeline")

GEEFLOW_PYTHON = os.environ.get("GEEFLOW_PYTHON")  # .venv-geeflow/bin/python

JOB_REGISTRY = {
    "landcover_weekly": {
        "cadence_hours": 24 * 7,
        "scope": "national",
        "ingest_table": "geeflow_extractions",
    },
    "forest_typology": {
        "cadence_hours": 24 * 30,
        "scope": "national",
        "ingest_table": "geeflow_extractions",
    },
    "burn_scars": {
        "cadence_hours": 24,
        "scope": "on_event",
        "ingest_table": "asset_condition_events",
    },
    "asset_condition": {
        "cadence_hours": 24,
        "scope": "per_portfolio",
        "ingest_table": "asset_condition_events",
    },
}


@dataclass
class JobResult:
    job_type: str
    started_at: datetime
    finished_at: datetime
    rows_written: int
    table: str
    log_excerpt: str


async def run_job(job_type: str, *, region_wkt: str | None = None, asset_rids: list[str] | None = None) -> JobResult:
    if job_type not in JOB_REGISTRY:
        raise ValueError(f"Unknown EO job type: {job_type!r}")
    spec = JOB_REGISTRY[job_type]
    started = datetime.now(timezone.utc)
    log.info("starting eo job: %s scope=%s", job_type, spec["scope"])

    rows_written = 0
    log_excerpt = ""

    try:
        if job_type in ("landcover_weekly", "forest_typology"):
            rows_written, log_excerpt = await _run_geeflow_job(job_type, region_wkt)
        elif job_type == "burn_scars":
            rows_written, log_excerpt = await _run_prithvi_job(asset_rids or [])
        elif job_type == "asset_condition":
            rows_written, log_excerpt = await _run_tapnet_job(asset_rids or [])
    except Exception as exc:
        log.exception("eo job %s failed", job_type)
        log_excerpt = f"{type(exc).__name__}: {exc}"

    finished = datetime.now(timezone.utc)
    return JobResult(
        job_type=job_type, started_at=started, finished_at=finished,
        rows_written=rows_written, table=spec["ingest_table"], log_excerpt=log_excerpt,
    )


async def _run_geeflow_job(job_type: str, region_wkt: str | None) -> tuple[int, str]:
    """Dispatch to .venv-geeflow subprocess. Real implementation streams a
    Beam pipeline; here we stub the call shape so callers integrate cleanly.
    """
    if not GEEFLOW_PYTHON:
        return (0, "GEEFLOW_PYTHON env not set; skipped")
    cmd = [GEEFLOW_PYTHON, "utils/geeflow_runner.py", "--mode", job_type]
    if region_wkt:
        cmd += ["--region_wkt", region_wkt]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    excerpt = (stderr or stdout).decode(errors="replace")[-1024:]
    rows = stdout.decode(errors="replace").count("\n") if proc.returncode == 0 else 0
    return (rows, excerpt)


async def _run_prithvi_job(asset_rids: list[str]) -> tuple[int, str]:
    """Run Prithvi burn-scars head on tile stacks for the given assets. Stub
    until app/ingestion/asset_tile_resolver.py lands.
    """
    return (0, f"prithvi job stubbed for {len(asset_rids)} assets")


async def _run_tapnet_job(asset_rids: list[str]) -> tuple[int, str]:
    return (0, f"tapnet job stubbed for {len(asset_rids)} assets")


def all_job_types() -> list[str]:
    return list(JOB_REGISTRY)

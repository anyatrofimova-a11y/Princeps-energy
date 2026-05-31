"""princeps-agent-platform — backend keeper.

Three loops, all in one service:

  ApiHealthSentinel:   pings princeps-api / health, enqueues a build task
                       if it's been down > N consecutive ticks.
  MigrationApplier:    diffs migrations/ on disk against schema_migrations
                       and applies the missing ones (CREATE TABLE IF NOT
                       EXISTS lines are idempotent so re-applies are safe).
                       Enqueues a build task for anything that errors.
  CiHealthSentinel:    polls the GitHub Actions API for the last 10 runs;
                       if a workflow has failed 3 times in a row, enqueues
                       a build task to inspect.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import httpx

from agents.lib.base import Agent, get_pool, run_agent
from agents.lib.build_queue import enqueue_build_task

log = logging.getLogger(__name__)


class ApiHealthSentinel(Agent):
    NAME = "api_health"
    CADENCE_SECONDS = 300                     # 5 min
    _consecutive_down = 0
    _threshold = 3

    async def tick(self):
        url = os.environ.get("PRINCEPS_API_URL", "https://princeps-api.fly.dev")
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{url}/health")
            ok = r.status_code == 200
        except Exception:
            ok = False
        if ok:
            type(self)._consecutive_down = 0
            return {"ok": True}
        type(self)._consecutive_down += 1
        if type(self)._consecutive_down >= self._threshold:
            pool = await get_pool()
            try:
                await enqueue_build_task(
                    pool,
                    title=f"princeps-api health failing ({type(self)._consecutive_down} ticks)",
                    brief=(
                        f"The api_health agent has observed {url}/health "
                        f"failing for {type(self)._consecutive_down} consecutive "
                        "5-minute checks. Inspect Fly machine logs for "
                        "princeps-api, find the cause, and either:\n"
                        "  - revert the most recent commit that touched app/, or\n"
                        "  - patch the failing handler.\n"
                        "Open a PR with the fix."
                    ),
                    context_paths=["app/main.py", "app/deps.py",
                                   "app/middleware/tenant_jwt.py"],
                    requested_by="agent:api_health",
                    priority=2,
                )
                type(self)._consecutive_down = 0
            finally:
                await pool.close()
        return {"ok": False, "consecutive_down": type(self)._consecutive_down}


class MigrationApplier(Agent):
    NAME = "migration_applier"
    CADENCE_SECONDS = 600                     # 10 min

    async def tick(self):
        mig_dir = Path(__file__).resolve().parent.parent / "migrations"
        if not mig_dir.exists():
            return {"skipped": "no migrations dir"}
        files = sorted(p for p in mig_dir.glob("*.sql"))
        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                # Make sure tracking table exists (idempotent).
                await conn.execute(
                    """CREATE TABLE IF NOT EXISTS schema_migrations (
                         filename text PRIMARY KEY,
                         applied_at timestamptz NOT NULL DEFAULT now(),
                         sha256 text,
                         applied_by text DEFAULT 'platform_agent'
                       )"""
                )
                applied_rows = await conn.fetch(
                    "SELECT filename FROM schema_migrations"
                )
            applied = {r["filename"] for r in applied_rows}
            applied_now = []
            failed_now = []
            for path in files:
                if path.name in applied:
                    continue
                sql = path.read_text()
                sha = hashlib.sha256(sql.encode()).hexdigest()
                try:
                    async with pool.acquire() as conn:
                        await conn.execute(sql)
                        await conn.execute(
                            """INSERT INTO schema_migrations (filename, sha256)
                                 VALUES ($1, $2)
                                 ON CONFLICT (filename) DO NOTHING""",
                            path.name, sha,
                        )
                    applied_now.append(path.name)
                except Exception as exc:
                    failed_now.append({"file": path.name, "error": str(exc)[:300]})
                    await enqueue_build_task(
                        pool,
                        title=f"Migration failed: {path.name}",
                        brief=(
                            f"The migration_applier agent failed to apply "
                            f"{path.name}. Error:\n{exc}\n\n"
                            "Inspect the SQL, fix the offending statement "
                            "(usually a missing FK target or a CREATE TYPE "
                            "without IF NOT EXISTS), and re-commit."
                        ),
                        context_paths=[f"migrations/{path.name}"],
                        requested_by="agent:migration_applier",
                        priority=2,
                    )
            return {"applied": applied_now, "failed": failed_now}
        finally:
            await pool.close()


class CiHealthSentinel(Agent):
    NAME = "ci_health"
    CADENCE_SECONDS = 1800                    # 30 min

    async def tick(self):
        token = os.environ.get("GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPO", "anyatrofimova-a11y/Princeps-energy")
        if not token:
            return {"skipped": "no GITHUB_TOKEN"}
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                f"https://api.github.com/repos/{repo}/actions/runs?per_page=20",
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/vnd.github+json"},
            )
        if r.status_code >= 300:
            return {"error": r.text[:200]}
        runs = r.json().get("workflow_runs", [])
        # Group by workflow name, count consecutive failures from newest backwards
        by_wf: dict[str, list[str]] = {}
        for run in runs:
            by_wf.setdefault(run["name"], []).append(run.get("conclusion") or "in_progress")
        enqueued = 0
        pool = await get_pool()
        try:
            for wf, results in by_wf.items():
                # 3+ failures in a row at the head?
                head_failures = 0
                for r in results:
                    if r == "failure": head_failures += 1
                    elif r in (None, "in_progress"): continue
                    else: break
                if head_failures >= 3:
                    task = await enqueue_build_task(
                        pool,
                        title=f"CI workflow '{wf}' failing {head_failures}x in a row",
                        brief=(
                            f"The ci_health agent observed the '{wf}' workflow "
                            f"failing {head_failures} consecutive runs. Pull the "
                            "logs of the latest failed job, identify the failing "
                            "step, and propose a fix."
                        ),
                        context_paths=[".github/workflows/"],
                        requested_by="agent:ci_health",
                        priority=3,
                    )
                    if task: enqueued += 1
            return {"workflows_checked": len(by_wf), "alerts_enqueued": enqueued}
        finally:
            await pool.close()


if __name__ == "__main__":
    run_agent([ApiHealthSentinel(), MigrationApplier(), CiHealthSentinel()])

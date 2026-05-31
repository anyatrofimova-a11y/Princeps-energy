"""Shared agent runtime.

Pattern: every agent runs `run_once()` on a fixed cadence inside a
supervised loop. Failures are logged but don't kill the loop. A small
FastAPI sidecar exposes /ping for Railway health checks.

Subclass shape::

    from agents.lib.base import Agent, run_agent

    class MyAgent(Agent):
        NAME = "ontology_coherence"
        CADENCE_SECONDS = 21600  # 6 hours
        async def tick(self):
            ...   # do work, return dict of counters
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

log = logging.getLogger("princeps.agent")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


class Agent:
    NAME: str = "agent"
    CADENCE_SECONDS: int = 3600

    async def tick(self) -> dict[str, Any]:
        raise NotImplementedError

    async def loop(self):
        log.info("agent %s starting (cadence=%ss)", self.NAME, self.CADENCE_SECONDS)
        while True:
            try:
                stats = await self.tick()
                log.info("agent %s tick ok stats=%s", self.NAME, stats)
            except Exception:
                log.exception("agent %s tick failed", self.NAME)
            await asyncio.sleep(self.CADENCE_SECONDS)


def make_sidecar(agent_name: str):
    """Tiny FastAPI app for Railway HTTP health checks."""
    from fastapi import FastAPI
    app = FastAPI()
    app.state.last_tick = None

    @app.get("/ping")
    def ping():
        return {"agent": agent_name, "ok": True}

    return app


async def get_pool():
    """asyncpg pool — same shape as app.deps."""
    import asyncpg
    url = os.environ["DATABASE_URL"]
    return await asyncpg.create_pool(
        url, min_size=1, max_size=4, statement_cache_size=0,
    )


def run_agent(agents: list[Agent], *, with_sidecar: bool = True):
    """Run one or many Agent instances concurrently. Optional FastAPI sidecar."""
    async def _main():
        tasks = [asyncio.create_task(a.loop()) for a in agents]
        if with_sidecar:
            import uvicorn
            cfg = uvicorn.Config(
                make_sidecar(",".join(a.NAME for a in agents)),
                host="0.0.0.0", port=int(os.environ.get("PORT", "8080")),
                log_level="warning",
            )
            tasks.append(asyncio.create_task(uvicorn.Server(cfg).serve()))
        await asyncio.gather(*tasks)

    asyncio.run(_main())

"""princeps-agent-replay — A14 grid twin replay / backtest (on-demand)."""
from __future__ import annotations
from agents.lib.base import Agent, run_agent


class TwinReplayWaiter(Agent):
    """Long-poll for replay jobs from a queue. Stubbed until queue lands."""
    NAME = "twin_replay"
    CADENCE_SECONDS = 60

    async def tick(self):
        return {"jobs_processed": 0}


if __name__ == "__main__":
    run_agent([TwinReplayWaiter()])

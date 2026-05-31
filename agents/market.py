"""princeps-agent-market — A10 DA price reactor, A13 REPD cross-validator."""
from __future__ import annotations
import httpx
from agents.lib.base import Agent, get_pool, run_agent


class DAPriceReactor(Agent):
    NAME = "da_price_reactor"
    CADENCE_SECONDS = 24 * 3600

    async def tick(self):
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index?format=json")
        ok = r.status_code == 200
        return {"bmrs_http": r.status_code, "ok": ok}


class REPDCrossValidator(Agent):
    NAME = "repd_cross_val"
    CADENCE_SECONDS = 24 * 3600

    async def tick(self):
        try:
            from utils.powerplant_validator import cross_validate_repd
        except Exception as exc:
            return {"skipped": True, "reason": str(exc)}
        pool = await get_pool()
        try:
            out = await cross_validate_repd(pool, fuzz_threshold=88)
            return {
                "matched": out.get("matched"),
                "divergent": out.get("divergent_over_20pct"),
            }
        finally:
            await pool.close()


if __name__ == "__main__":
    run_agent([DAPriceReactor(), REPDCrossValidator()])

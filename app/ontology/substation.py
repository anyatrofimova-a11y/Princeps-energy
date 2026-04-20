"""Substation ontology object — backed by ``grid_substations``.

Actions: watch, request_headroom_check, request_connection_cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .base import ActionResult, ObjectNotFound

TYPE = "substation"


@dataclass(frozen=True)
class Substation:
    id: str
    type: str = TYPE
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def load_from_db(cls, pool, id: str) -> "Substation":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, dno, voltage_kv, demand_headroom_mw, gen_headroom_mw, "
                "rag_demand, rag_generation FROM grid_substations WHERE id = $1::int",
                int(id),
            )
        if not row:
            raise ObjectNotFound(f"substation:{id}")
        meta = {}
        for k, v in dict(row).items():
            if hasattr(v, "quantize"):
                meta[k] = float(v)
            else:
                meta[k] = v
        return cls(id=str(row["id"]), metadata=meta)

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "metadata": self.metadata}


class WatchArgs(BaseModel):
    cadence: str = "daily"


class HeadroomArgs(BaseModel):
    target_mw: float
    direction: str = "gen"  # gen | demand


class ConnectionCostArgs(BaseModel):
    target_mw: float
    distance_km: float | None = None


async def watch(obj: Substation, pool, **kwargs) -> ActionResult:
    args = WatchArgs(**kwargs)
    import json as _json
    patch = _json.dumps({"watched": True, "cadence": args.cadence})
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE grid_substations SET raw_data = raw_data || $1::jsonb, "
            "updated_at=now() WHERE id=$2::int",
            patch, int(obj.id),
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        diff={"watched": True, "cadence": args.cadence})


async def request_headroom_check(obj: Substation, pool, **kwargs) -> ActionResult:
    args = HeadroomArgs(**kwargs)
    key = "gen_headroom_mw" if args.direction == "gen" else "demand_headroom_mw"
    available = obj.metadata.get(key)
    if available is None:
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                            error="headroom_unknown")
    fits = float(available) >= args.target_mw
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        object_after={"id": obj.id, "fits": fits,
                                      "available_mw": float(available),
                                      "requested_mw": args.target_mw},
                        provenance={"source": "grid_substations.headroom"})


async def request_connection_cost(obj: Substation, pool, **kwargs) -> ActionResult:
    args = ConnectionCostArgs(**kwargs)
    # UK £/km benchmarks by voltage (from project memory).
    voltage = float(obj.metadata.get("voltage_kv") or 33)
    if voltage >= 132:
        rate = 500_000
    elif voltage >= 33:
        rate = 150_000
    else:
        rate = 80_000
    dist = args.distance_km if args.distance_km is not None else 2.0
    cost = int(rate * dist)
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        object_after={"id": obj.id, "p50_cost_gbp": cost,
                                      "rate_per_km": rate, "distance_km": dist},
                        provenance={"source": "ontology.substation.benchmark",
                                    "note": "P50 only; Tier-2 via utils.grid_connection_analyser"})


ACTIONS = {
    "watch": (watch, WatchArgs, False),
    "request_headroom_check": (request_headroom_check, HeadroomArgs, False),
    "request_connection_cost": (request_connection_cost, ConnectionCostArgs, False),
}

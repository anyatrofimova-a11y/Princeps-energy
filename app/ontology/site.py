"""Site/Parcel ontology object — backed by ``prospect_parcels`` + ``prospect_candidates``.

Actions: score, reserve, buildable_rerun, request_gridstudy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .base import ActionResult, ObjectNotFound

TYPE = "site"


@dataclass(frozen=True)
class Site:
    id: str
    type: str = TYPE
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def load_from_db(cls, pool, id: str) -> "Site":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, name, region, area_ha, estimated_mw, grid_distance_km, "
                "alc_grade, status FROM prospect_parcels WHERE id = $1", id,
            )
        if not row:
            raise ObjectNotFound(f"site:{id}")
        return cls(id=row["id"], metadata=dict(row))

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "metadata": self.metadata}


class ScoreArgs(BaseModel):
    tech: str = "solar"
    weights: dict[str, float] | None = None


class ReserveArgs(BaseModel):
    reason: str | None = "user_reserved"


class BuildableArgs(BaseModel):
    buffer_m: float = 10.0


class GridStudyArgs(BaseModel):
    target_mw: float | None = None


async def score(obj: Site, pool, **kwargs) -> ActionResult:
    args = ScoreArgs(**kwargs)
    try:
        from utils.site_prospector import score_candidate_site  # noqa
    except Exception:
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                            error="not_implemented: site_prospector unavailable")
    # Delegate: build a parcel-shaped dict, let the existing scorer do the math.
    parcel = {**obj.metadata, "tech": args.tech}
    try:
        scored = score_candidate_site(parcel, weights=args.weights)
    except Exception as e:
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}", error=f"scorer_failed: {e}")
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        object_after={"id": obj.id, "score": scored.get("score"),
                                      "verdict": scored.get("verdict")},
                        provenance={"scorer": "utils.site_prospector.score_candidate_site"})


async def reserve(obj: Site, pool, **kwargs) -> ActionResult:
    args = ReserveArgs(**kwargs)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE prospect_parcels SET status='reserved' WHERE id=$1", obj.id,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        diff={"status": {"from": obj.metadata.get("status"), "to": "reserved"},
                              "reason": args.reason})


async def buildable_rerun(obj: Site, pool, **kwargs) -> ActionResult:
    BuildableArgs(**kwargs)
    return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                        error="not_implemented: buildable_rerun pending BOT-I",
                        provenance={"stub": True})


async def request_gridstudy(obj: Site, pool, **kwargs) -> ActionResult:
    args = GridStudyArgs(**kwargs)
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        side_effects=[{"queued": "grid_study",
                                       "target_mw": args.target_mw or obj.metadata.get("estimated_mw")}],
                        provenance={"source": "ontology.site.request_gridstudy",
                                    "note": "stub — grid study queue wired by BOT-I"})


ACTIONS = {
    "score": (score, ScoreArgs, True),
    "reserve": (reserve, ReserveArgs, True),
    "buildable_rerun": (buildable_rerun, BuildableArgs, True),
    "request_gridstudy": (request_gridstudy, GridStudyArgs, True),
}

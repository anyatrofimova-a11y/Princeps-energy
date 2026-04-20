"""Tender ontology object — backed by ``procurement_tenders_raw``.

Actions: classify, assess_viability, draft_bid, submit_bid.
Delegates to utils.procurement_intelligence for the analytical steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .base import ActionResult, ObjectNotFound

TYPE = "tender"


@dataclass(frozen=True)
class Tender:
    id: str
    type: str = TYPE
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def load_from_db(cls, pool, id: str) -> "Tender":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tender_id, title, abstract, buyer, closing_date, tech, "
                "capacity_mw, budget_gbp, scope, bid_viability, reasoning "
                "FROM procurement_tenders_raw WHERE tender_id = $1", id,
            )
        if not row:
            raise ObjectNotFound(f"tender:{id}")
        return cls(id=row["tender_id"], metadata=dict(row))

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "metadata": self.metadata}


class ClassifyArgs(BaseModel):
    override_tech: str | None = None


class ViabilityArgs(BaseModel):
    our_capacity_mw: float | None = None
    our_techs: list[str] | None = None


class DraftBidArgs(BaseModel):
    cover_letter_tone: str = "formal"


class SubmitBidArgs(BaseModel):
    confirm: bool = True


async def classify(obj: Tender, pool, **kwargs) -> ActionResult:
    args = ClassifyArgs(**kwargs)
    try:
        from utils.procurement_intelligence import classify_tender_technology
    except Exception:
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                            error="not_implemented: procurement_intelligence unavailable")
    tech = args.override_tech or classify_tender_technology(
        obj.metadata.get("title") or "", obj.metadata.get("abstract") or "",
    )
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE procurement_tenders_raw SET tech=$1, classified_at=now() "
            "WHERE tender_id=$2", tech, obj.id,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        diff={"tech": {"from": obj.metadata.get("tech"), "to": tech}},
                        object_after={"id": obj.id, "tech": tech},
                        provenance={"source": "utils.procurement_intelligence.classify_tender_technology"})


async def assess_viability(obj: Tender, pool, **kwargs) -> ActionResult:
    args = ViabilityArgs(**kwargs)
    # Simple heuristic: tech match + capacity fit. Full scoring in utils.procurement_intelligence.
    tech = obj.metadata.get("tech")
    cap = obj.metadata.get("capacity_mw")
    score = 50
    if args.our_techs and tech in args.our_techs:
        score += 25
    if args.our_capacity_mw and cap and float(cap) <= float(args.our_capacity_mw) * 1.2:
        score += 20
    score = min(score, 100)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE procurement_tenders_raw SET bid_viability=$1 WHERE tender_id=$2",
            score, obj.id,
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}",
                        object_after={"id": obj.id, "bid_viability": score},
                        provenance={"source": "ontology.tender.heuristic_viability"})


async def draft_bid(obj: Tender, pool, **kwargs) -> ActionResult:
    DraftBidArgs(**kwargs)
    return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                        error="not_implemented: bid_drafter pending (BOT-I)",
                        provenance={"stub": True})


async def submit_bid(obj: Tender, pool, **kwargs) -> ActionResult:
    SubmitBidArgs(**kwargs)
    return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                        error="not_implemented: external e-tender portal not wired",
                        provenance={"stub": True})


ACTIONS = {
    "classify": (classify, ClassifyArgs, False),
    "assess_viability": (assess_viability, ViabilityArgs, False),
    "draft_bid": (draft_bid, DraftBidArgs, True),
    "submit_bid": (submit_bid, SubmitBidArgs, True),
}

"""Layout ontology object — backed by ``site_layouts``.

Actions: auto_design, version, export_dxf, yield_run.
Delegates to utils.site_auto_designer where available; stubs elsewhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from .base import ActionResult, ObjectNotFound

TYPE = "layout"


@dataclass(frozen=True)
class Layout:
    id: str  # parcel_id (uuid) — site_layouts is keyed by parcel
    type: str = TYPE
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def load_from_db(cls, pool, id: str) -> "Layout":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT parcel_id, layout_data, created_at, updated_at "
                "FROM site_layouts WHERE parcel_id = $1::uuid", id,
            )
        if not row:
            # Allow "empty" layout object so auto_design can create the row.
            return cls(id=id, metadata={"exists": False})
        ld = row["layout_data"]
        if isinstance(ld, str):
            ld = json.loads(ld)
        return cls(id=str(row["parcel_id"]),
                   metadata={"exists": True, "layout_data": ld,
                             "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None})

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "metadata": self.metadata}


class AutoDesignArgs(BaseModel):
    tech: str = "solar"
    target_mw: float | None = None


class VersionArgs(BaseModel):
    label: str | None = None


class ExportArgs(BaseModel):
    format: str = "dxf"


class YieldArgs(BaseModel):
    tech: str = "solar"


async def auto_design(obj: Layout, pool, **kwargs) -> ActionResult:
    args = AutoDesignArgs(**kwargs)
    try:
        from utils.site_auto_designer import auto_design_solar, auto_design_bess  # noqa
    except Exception:
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                            error="not_implemented: site_auto_designer unavailable")
    fn = auto_design_solar if args.tech == "solar" else auto_design_bess
    # Existing designers expect a parcel geom; here we just persist the intent.
    try:
        payload = {"tech": args.tech, "target_mw": args.target_mw,
                   "designer": fn.__name__}
    except Exception as e:
        return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}", error=str(e))
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO site_layouts (parcel_id, layout_data, created_at, updated_at) "
            "VALUES ($1::uuid, $2::jsonb, now(), now()) "
            "ON CONFLICT (parcel_id) DO UPDATE SET layout_data=$2::jsonb, updated_at=now()",
            obj.id, json.dumps(payload),
        )
    return ActionResult(ok=True, object_key=f"{TYPE}:{obj.id}", object_after=payload,
                        provenance={"source": "ontology.layout.auto_design"})


async def version(obj: Layout, pool, **kwargs) -> ActionResult:
    VersionArgs(**kwargs)
    return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                        error="not_implemented: site_layouts has no version column yet",
                        provenance={"stub": True})


async def export_dxf(obj: Layout, pool, **kwargs) -> ActionResult:
    ExportArgs(**kwargs)
    return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                        error="not_implemented: DXF exporter not wired",
                        provenance={"stub": True})


async def yield_run(obj: Layout, pool, **kwargs) -> ActionResult:
    args = YieldArgs(**kwargs)
    return ActionResult(ok=False, object_key=f"{TYPE}:{obj.id}",
                        error="not_implemented: SAM yield run queued via BOT-I",
                        provenance={"stub": True, "tech": args.tech})


ACTIONS = {
    "auto_design": (auto_design, AutoDesignArgs, True),
    "version": (version, VersionArgs, False),
    "export_dxf": (export_dxf, ExportArgs, False),
    "yield_run": (yield_run, YieldArgs, True),
}

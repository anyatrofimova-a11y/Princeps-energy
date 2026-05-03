"""Connected-asset financial exposure — REST endpoint that feeds the
`ConnectedAssetPanel` drawer on the frontend.

When a user clicks a substation / GSP / connection point on any map
(MapView, GridTwin, AssessTwin, DiscoverTab) the panel fires a
``GET /api/portfolio/asset-exposure/{substation_id}`` and displays the
portfolio-wide exposure routed through that single grid asset:
projects, aggregate MW + IRR + NPV, HHI concentration index, and
four pre-canned stress cases.

See :mod:`utils.asset_exposure` for the analytics pipeline.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
import asyncpg

from app.deps import get_pool, get_optional_user
from utils.asset_exposure import compute_asset_exposure

log = logging.getLogger("princeps.portfolio_asset_exposure")

router = APIRouter(tags=["portfolio", "asset-exposure"])


@router.get("/api/portfolio/asset-exposure/{substation_id}")
async def api_asset_exposure(
    substation_id: int,
    portfolio_id: str | None = Query(
        None,
        description="Optional UUID — scope exposure to a single portfolio. "
                    "When omitted the view aggregates across every project the "
                    "caller can see.",
    ),
    pool: asyncpg.Pool = Depends(get_pool),
    user=Depends(get_optional_user),
):
    """Return the full Connected-Asset payload for one substation.

    Response shape (see :func:`utils.asset_exposure.compute_asset_exposure`):

    ```
    {
      "asset_header":      { substation_id, name, dno, voltage_kv,
                             firm_headroom_mw, non_firm_headroom_mw,
                             transformer_rating_mva, rag, ... },
      "projects":          [ { project_id, name, capacity_mw, stage,
                               irr_pct, npv_gbp, technology, ... } ],
      "portfolio_exposure":{ connected_mw, portfolio_total_mw,
                             mw_share_pct, total_npv_gbp_m,
                             mw_weighted_irr_pct, project_count,
                             diversification_flag },
      "concentration_index":{ hhi_raw, hhi_normalised, n },
      "stress_cases":      [ ... 4 scenarios ... ],
      "sparkline":         [ { label, npv_gbp_m, drop_gbp_m } ],
      "filters":           { substation_id, portfolio_id }
    }
    ```
    """
    try:
        payload = await compute_asset_exposure(
            pool=pool,
            substation_id=substation_id,
            portfolio_id=portfolio_id,
        )
    except asyncpg.PostgresError as e:
        log.warning("asset-exposure DB error: %s", e)
        raise HTTPException(status_code=500, detail=f"Database error: {e}") from e
    except Exception as e:
        log.exception("asset-exposure unexpected error")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e

    if payload.get("asset_header", {}).get("not_found"):
        # Keep the 200 path — the frontend shows an empty-state rather than
        # an error toast when the substation row is missing (e.g. clicked
        # an OSM point that isn't in grid_substations yet).
        payload["warning"] = (
            f"No grid_substations row for substation_id={substation_id}; "
            "projects list + exposure are still computed from project metadata."
        )
    return payload

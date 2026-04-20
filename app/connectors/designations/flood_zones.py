"""Environment Agency Flood Map for Planning connector.

Source: planning.data.gov.uk dataset ``flood-risk-zone``. Each row carries a
``flood-risk-level`` ("1" | "2" | "3") and a ``flood-risk-type``
("Tidal Models" | "Fluvial Models" | ...). This is a very large dataset
(~780k features), so we chunk by UK bbox to stay under the API's offset
limits.
"""

from __future__ import annotations

from typing import Any

from ._planning_base import PlanningDataConnector, register_planning


@register_planning
class FloodZonesConnector(PlanningDataConnector):
    source_name = "flood_zones"
    schedule = "0 6 * * 0"  # weekly Sunday 06:00 UTC
    dataset = "flood-risk-zone"
    table = "designations_flood_zones"
    extra_cols = ["flood_zone", "flood_risk_type"]
    # ~780k records. The upstream API's WKT-bbox filter times out on this
    # dataset, so we paginate linearly by offset instead. A full run takes
    # ~10 minutes at the default 0.3s rate delay; a scheduled weekly cron
    # is fine, and operators can run a partial refresh from the router.
    bbox_chunked = False

    def extract_extras(self, entity: dict[str, Any]) -> list[Any]:
        level = entity.get("flood-risk-level") or ""
        kind = entity.get("flood-risk-type") or ""
        return [str(level), str(kind)]

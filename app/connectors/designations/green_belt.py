"""Green Belt connector.

Source: planning.data.gov.uk dataset ``green-belt``. Rows carry the
local authority in the ``name`` field (e.g. ``"Halton"``) and a
``reference`` of the form ``<GSS code>/<metropolitan area>``. We
capture the LA into a dedicated column for fast filters.
"""

from __future__ import annotations

from typing import Any

from ._planning_base import PlanningDataConnector, register_planning


@register_planning
class GreenBeltConnector(PlanningDataConnector):
    source_name = "green_belt"
    schedule = "0 5 * * 0"  # weekly Sunday 05:00 UTC
    dataset = "green-belt"
    table = "designations_green_belt"
    extra_cols = ["local_authority"]

    def extract_extras(self, entity: dict[str, Any]) -> list[Any]:
        # name is typically the LA; fall back to a token from reference.
        la = entity.get("name") or ""
        if not la:
            ref = entity.get("reference") or ""
            la = ref.split("/")[0] if "/" in ref else ref
        return [la]

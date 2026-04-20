"""AONB / National Landscapes connector.

Source: planning.data.gov.uk dataset ``area-of-outstanding-natural-beauty``.
Roughly 34 polygons nationwide — one full pull is safe, no bbox chunking.
"""

from __future__ import annotations

from ._planning_base import PlanningDataConnector, register_planning


@register_planning
class AONBConnector(PlanningDataConnector):
    source_name = "aonb"
    schedule = "0 4 * * 0"  # weekly Sunday 04:00 UTC
    dataset = "area-of-outstanding-natural-beauty"
    table = "designations_aonb"

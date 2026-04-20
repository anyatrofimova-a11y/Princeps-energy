"""SSSI connector.

Source: planning.data.gov.uk dataset ``site-of-special-scientific-interest``.
~4100 records — single-pass pagination is fine.
"""

from __future__ import annotations

from ._planning_base import PlanningDataConnector, register_planning


@register_planning
class SSSIConnector(PlanningDataConnector):
    source_name = "sssi"
    schedule = "0 4 * * 0"  # weekly
    dataset = "site-of-special-scientific-interest"
    table = "designations_sssi"

"""SPA / SAC / Ramsar connectors (European and international sites).

All three come from planning.data.gov.uk with the same shape, so we declare
three small connector classes and register each.

- SPA (Special Protection Area) — EU Birds Directive
- SAC (Special Area of Conservation) — EU Habitats Directive
- Ramsar — Convention on Wetlands of International Importance
"""

from __future__ import annotations

from ._planning_base import PlanningDataConnector, register_planning


@register_planning
class SPAConnector(PlanningDataConnector):
    source_name = "spa"
    schedule = "0 4 * * 0"
    dataset = "special-protection-area"
    table = "designations_spa"


@register_planning
class SACConnector(PlanningDataConnector):
    source_name = "sac"
    schedule = "0 4 * * 0"
    dataset = "special-area-of-conservation"
    table = "designations_sac"


@register_planning
class RamsarConnector(PlanningDataConnector):
    source_name = "ramsar"
    schedule = "0 4 * * 0"
    dataset = "ramsar"
    table = "designations_ramsar"

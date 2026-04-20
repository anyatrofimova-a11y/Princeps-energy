"""
app/dockets/ — Dockets engine for Princeps Intelligence.

The docket is the primary unit of UK energy proceedings — NSIP DCOs, LPA
planning applications, Ofgem code modifications, CFD/CM auctions, DNO
connection cases, etc. A docket groups documents, stakeholders, timeline
events and consultee requirements into a single entity a developer /
advisor / lender can monitor, question and pin to a project.

Submodules
----------
- ``exec_summary``         — Claude-driven executive-summary refresh.
- ``stakeholder_extractor``— NER pass that extracts participants from docs.
- ``timeline_extractor``   — extraction of forward-looking deadlines.
- ``docket_resolver``      — source -> docket_id mapping / upsert.
- ``authorities_seed``     — UK authorities registry seed.
- ``consultee_rules_seed`` — statutory / discretionary consultee rules seed.
- ``agent_tool``           — ``get_pinned_dockets`` agent tool wiring.
"""

from __future__ import annotations

__all__ = [
    "exec_summary",
    "stakeholder_extractor",
    "timeline_extractor",
    "docket_resolver",
    "authorities_seed",
    "consultee_rules_seed",
    "agent_tool",
]

"""Site enrichment package — point-to-everything lookup for UK developer workflows.

This package bundles two generations of enrichment:

1. The *legacy* module (``legacy.py``) — the existing deterministic postcode /
   LPA / parish / ward / UPRN / title enricher that powers 1APP and DCO form
   rendering.  Its public functions (``enrich_site``, ``lookup_postcode``,
   ``lookup_lpa``, ``lookup_parish``, ``lookup_ward``, ``EnrichedField``,
   ``SiteEnrichment``, ``_provenance``) are re-exported so downstream callers
   (``utils.site_enrichment_ai``, ``utils.parcel_detail``, ``app.routers.project_actions``)
   keep working unchanged.

2. The *new* fast pipeline (``enricher.enrich``) — a parallel ``asyncio.gather``
   of 8 sub-enrichers, target <800 ms p95, used by ``GET /api/analysis/enrich``.
   Each sub-enricher degrades gracefully to ``None`` with a structured TODO
   when the underlying data source is not wired (missing API key, missing
   table, etc.) so the endpoint NEVER 500s on partial infra.
"""

# Re-export the legacy API so existing imports keep working after the
# module-to-package conversion.
from .legacy import (  # noqa: F401
    EnrichedField,
    SiteEnrichment,
    _provenance,
    apply_enrichment_to_project_dict,
    apply_enrichment_to_site_dict,
    enrich_site,
    lookup_lpa,
    lookup_parish,
    lookup_postcode,
    lookup_uprn,
    lookup_ward,
)

# New fast enricher (exposed for the FastAPI router + tests).
from .enricher import EnrichmentResult, enrich  # noqa: F401

__all__ = [
    "EnrichedField",
    "SiteEnrichment",
    "EnrichmentResult",
    "enrich",
    "enrich_site",
    "lookup_postcode",
    "lookup_lpa",
    "lookup_parish",
    "lookup_ward",
    "lookup_uprn",
    "apply_enrichment_to_site_dict",
    "apply_enrichment_to_project_dict",
    "_provenance",
]

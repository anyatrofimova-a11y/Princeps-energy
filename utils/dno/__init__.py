"""
utils.dno — DNO-PLUS ingesters (BOT-DNO-PLUS scope).

This package extends the existing multi-DNO ingestion layer
(``utils.dno_opendata_ingester`` + ``utils.grid_data_ingester`` +
``utils.ltds_cim_ingester``) with two datasets the earlier pipeline
does not cover:

1. ``nged_ckan_ingester`` — richer NGED Connected Data Portal (CKAN)
   feeders / ANM zones / HV & LV topology / reinforcement plans.
2. ``ltds_fetcher``        — the full 6-DNO Long-Term Development
   Statement corpus (UKPN, NGED, SSEN, SPEN, NPG, ENWL) — PDF + Excel,
   parsed for transformer ratings + network limits.

These modules are intentionally decoupled from the existing DNO
ingesters: they write to their own ``nged_*`` / ``ltds_*`` tables and
register their own ``data_subscriptions`` rows.
"""

from __future__ import annotations

__all__ = [
    "nged_ckan_ingester",
    "ltds_fetcher",
]

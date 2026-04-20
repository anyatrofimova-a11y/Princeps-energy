"""BOT-FF parcel dossier package — single-page deep-detail for any INSPIRE parcel.

Public surface
--------------
* ``build_dossier(pool, inspire_id, *, user=None)`` — async, returns a fully
  populated ``ParcelDossier`` dict. Never raises: every sub-query is
  wrapped and degrades to ``{"warning": "..."}`` on failure so the FastAPI
  endpoint can always return 200.

* ``mock_dossier(inspire_id)`` — synchronous, returns a realistic fixture
  keyed by a small set of fake INSPIRE ids. Used by tests and by the
  endpoint whenever upstream DB / Redis is unavailable.

This package is deliberately thin and composed of focused sub-modules:

* ``dossier_builder.py`` — orchestrator, runs 10 sub-queries concurrently.
* ``repd_overlap.py`` — PostGIS intersection against REPD projects.
* ``planning_history.py`` — PlanIt-style 5-year planning-app history.
* ``similar_parcels.py`` — pgvector-backed nearest-neighbour lookup.

The existing legacy deep-detail pipeline (``utils/parcel_detail.py``) is
*not* imported here — BOT-FF's dossier is intentionally a new, simpler
shape driven by the UI's right-side drawer.
"""

from __future__ import annotations

from .dossier_builder import build_dossier, mock_dossier

__all__ = ["build_dossier", "mock_dossier"]

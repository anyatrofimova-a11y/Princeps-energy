"""Princeps connector framework.

Two coexisting frameworks live in this package:

1. **Magritte / dataset-registry** (``base.py``, ``registry.py``,
   ``health.py``, ``startup.py``) — Foundry-style typed connectors
   registered in :class:`princeps_datasets`. Subclass :class:`Connector`
   (an ``ABC``) and override ``fetch`` + ``upsert``. Used by the new
   ingestion sources under ``app/connectors/sources/``.

2. **Legacy Protocol** (``protocol.py``) — pre-existing duck-typed
   :class:`Connector` Protocol used by the planning.data.gov.uk
   designation connectors. Persists into ``connectors_registry``.
   Surfaced under ``/api/connectors/*``.

Both are exported here so callers can pick whichever fits their needs.
"""

from __future__ import annotations

# ── New Magritte ABC + dataclasses + registry helpers ──────────────────
from .base import Connector, HealthCheck, IngestResult
from .registry import (
    all_connectors,
    get,
    register as register_class,
)

# ── Legacy Protocol + dataclasses (kept for designation connectors) ────
# The legacy Protocol type is re-exported as ``LegacyConnector`` so the
# unqualified ``Connector`` name belongs to the new ABC. ``register`` is
# the legacy instance-registration helper — re-exported here as
# ``register_instance`` for clarity (designation modules still call the
# original name from ``app.connectors.protocol`` directly).
from .protocol import (
    Connector as LegacyConnector,
    ConnectorHealth,
    IngestReport,
    get_connector,
    list_connectors,
    register as register_instance,
)

# Register all legacy designation connectors at import time so the old
# /api/connectors router has a populated registry without app/main needing
# to import each one. Wrap in try/except so a single broken connector
# doesn't kill the rest of the package import.
try:
    from .designations import (  # noqa: F401
        aonb as _aonb,
        sssi as _sssi,
        spa_sac_ramsar as _spa_sac_ramsar,
        green_belt as _green_belt,
        flood_zones as _flood_zones,
        priority_habitats as _priority_habitats,
        alc_grade as _alc_grade,
    )
except Exception:  # pragma: no cover — defensive
    import logging
    logging.getLogger("princeps.connectors").warning(
        "designations registry import failed — legacy connectors registry empty",
        exc_info=True,
    )

__all__ = [
    # New Magritte framework
    "Connector",
    "HealthCheck",
    "IngestResult",
    "register_class",
    "get",
    "all_connectors",
    # Legacy
    "LegacyConnector",
    "ConnectorHealth",
    "IngestReport",
    "register_instance",
    "get_connector",
    "list_connectors",
]

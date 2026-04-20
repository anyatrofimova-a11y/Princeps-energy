"""Princeps connector framework.

A Connector is a contract for ingesting an external dataset into Princeps:
it exposes a stable ``source_name``, a cron ``schedule``, and two async
methods — ``refresh(pool)`` which upserts rows and returns an IngestReport,
and ``health()`` which returns a ConnectorHealth snapshot.

Every connector is registered at import time via ``register()``. The router
``app.routers.connectors`` exposes ``/api/connectors/health`` and
``POST /api/connectors/{name}/refresh`` on top of the registry.

Importing this package side-effect-imports each designation connector so
that the registry is populated by the time FastAPI loads the router.
"""

from __future__ import annotations

from .base import (
    Connector,
    ConnectorHealth,
    IngestReport,
    get_connector,
    list_connectors,
    register,
)

# Register all designation connectors at import time. Import-time side
# effects are how the registry is populated — the router reads ``_REGISTRY``
# when requests come in, it doesn't re-scan the filesystem.
from .designations import (  # noqa: F401
    aonb as _aonb,
    sssi as _sssi,
    spa_sac_ramsar as _spa_sac_ramsar,
    green_belt as _green_belt,
    flood_zones as _flood_zones,
    priority_habitats as _priority_habitats,
    alc_grade as _alc_grade,
)

__all__ = [
    "Connector",
    "ConnectorHealth",
    "IngestReport",
    "get_connector",
    "list_connectors",
    "register",
]

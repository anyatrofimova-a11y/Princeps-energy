"""App-launch wiring for the Magritte connector framework.

Single public entry point — :func:`register_all_connectors`. Walks
``app.connectors.sources``, lets each subclass register itself in the
in-process class registry, then upserts every connector's metadata into
``princeps_datasets`` so the catalogue is complete before the first HTTP
request.

Designed so an empty ``app.connectors.sources`` (no source files yet)
is a *successful* run — the package may not have been created yet by
the downstream agents that own the actual connectors.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

import asyncpg

from . import registry as _registry
from .base import Connector

log = logging.getLogger("princeps.connectors.startup")


def _import_all_sources() -> int:
    """Import every module under ``app.connectors.sources``.

    Each module is expected to apply :func:`app.connectors.registry.register`
    at import time (typically via the ``@register_class`` decorator) so the
    in-process registry fills up as a side effect.

    Returns the number of source modules successfully imported. Missing
    package, single broken module — all are logged and tolerated; the
    framework should never block app boot.
    """
    try:
        sources_pkg = importlib.import_module("app.connectors.sources")
    except ModuleNotFoundError:
        # Sources package doesn't exist yet — that's fine, the other agents
        # will create it. Empty registry is a valid state.
        log.info("app.connectors.sources not present yet — skipping connector import")
        return 0
    except Exception as exc:
        log.warning("app.connectors.sources import failed: %s", exc)
        return 0

    imported = 0
    for _finder, modname, _ispkg in pkgutil.walk_packages(
        sources_pkg.__path__, prefix="app.connectors.sources.",
    ):
        try:
            importlib.import_module(modname)
            imported += 1
        except Exception as exc:
            log.warning("connector module %s failed to import: %s", modname, exc)
    return imported


async def register_all_connectors(pool: asyncpg.Pool) -> dict[str, int]:
    """Hydrate the dataset registry from all known connector classes.

    Called from ``app/startup.py:launch_background_tasks``. Idempotent —
    safe to call on every boot. Returns a small summary dict for logging.
    """
    n_modules = _import_all_sources()
    classes = _registry.all_connectors()

    n_registered = 0
    n_failed = 0
    for cls in classes:
        try:
            instance = cls()
        except Exception as exc:
            log.warning(
                "connector %s could not be instantiated: %s",
                getattr(cls, "__name__", str(cls)), exc,
            )
            n_failed += 1
            continue
        try:
            await instance.register(pool)
            n_registered += 1
        except Exception as exc:
            log.warning("connector %s register() failed: %s", instance.slug, exc)
            n_failed += 1

    log.info(
        "Magritte connectors: imported=%d registered=%d failed=%d",
        n_modules, n_registered, n_failed,
    )
    return {
        "modules_imported": n_modules,
        "registered": n_registered,
        "failed": n_failed,
    }


__all__ = ["register_all_connectors"]

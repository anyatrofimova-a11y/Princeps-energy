"""In-process class registry for Magritte-style connectors.

Each connector subclass registers itself once via the ``@register``
decorator. The registry is read at app-launch time by
:func:`app.connectors.startup.register_all_connectors` (which calls
``cls().register(pool)`` on every entry to populate
``princeps_datasets``) and at request time by the ``/api/datasets``
router.

Class-level rather than instance-level — connectors are cheap to
instantiate but the registry survives reloads cleanly when keyed on
the type. Slug uniqueness is enforced at register time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Connector


_REGISTRY: dict[str, type["Connector"]] = {}


def register(cls: type["Connector"]) -> type["Connector"]:
    """Class decorator — adds *cls* to the in-process registry, keyed by ``slug``.

    Usage::

        from app.connectors import Connector, register_class

        @register_class
        class CcodConnector(Connector):
            slug = "hm_land_registry_ccod"
            ...

    Raises ``ValueError`` if the class has no ``slug`` or the slug is
    already registered to a different class. Re-registering the same
    class is a no-op (safe across module reloads).
    """
    slug = getattr(cls, "slug", None)
    if not slug:
        raise ValueError(f"connector {cls.__name__} has no slug")

    existing = _REGISTRY.get(slug)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"connector slug {slug!r} already registered to "
            f"{existing.__module__}.{existing.__name__}",
        )
    _REGISTRY[slug] = cls
    return cls


def get(slug: str) -> type["Connector"] | None:
    """Return the connector class registered under *slug*, or ``None``."""
    return _REGISTRY.get(slug)


def all_connectors() -> list[type["Connector"]]:
    """Return every registered connector class. Order is registration order."""
    return list(_REGISTRY.values())


def _clear_for_tests() -> None:
    """Reset the registry. **Tests only — never call from app code.**"""
    _REGISTRY.clear()


__all__ = ["register", "get", "all_connectors"]

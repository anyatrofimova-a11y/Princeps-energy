"""Princeps Resource Identifier (RID) — Palantir-style stable id.

Format: ``rid.princeps.{instance}.{type}.{locator}``

* ``service``  — always ``princeps`` for our platform
* ``instance`` — deployment instance: ``production``, ``staging``, ``demo``, etc.
* ``type``     — lowercase ontology object type: ``site``, ``substation``, ``gsp``, ...
* ``locator``  — UUID4 by default; may be a stable external id when one exists
                 (REPD reference, GLEIF LEI, etc.) prefixed with the source.

Examples:
    rid.princeps.production.substation.7e1c4a3a-2b8f-4e3a-9b7e-1c4a3a2b8f4e
    rid.princeps.production.repd.lei-213800XXXXXXXXXXXX42
    rid.princeps.demo.solar_farm.f47ac10b-58cc-4372-a567-0e02b2c3d479
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from typing import Final

_RID_PATTERN: Final = re.compile(
    r"^rid\.(?P<service>[a-z][a-z0-9_-]*)"
    r"\.(?P<instance>[a-z][a-z0-9_-]*)"
    r"\.(?P<type>[a-z][a-z0-9_]*)"
    r"\.(?P<locator>[a-zA-Z0-9_.\-]+)$"
)

_DEFAULT_SERVICE: Final = "princeps"
_DEFAULT_INSTANCE: Final = os.environ.get("PRINCEPS_RID_INSTANCE", "production")


class RidError(ValueError):
    """Raised when an RID string is malformed."""


@dataclass(frozen=True, slots=True)
class Rid:
    service: str
    instance: str
    type: str
    locator: str

    def __str__(self) -> str:
        return f"rid.{self.service}.{self.instance}.{self.type}.{self.locator}"

    @classmethod
    def parse(cls, s: str) -> Rid:
        m = _RID_PATTERN.match(s)
        if not m:
            raise RidError(f"Malformed RID: {s!r}")
        return cls(
            service=m["service"],
            instance=m["instance"],
            type=m["type"],
            locator=m["locator"],
        )

    @classmethod
    def new(
        cls,
        type_: str,
        *,
        instance: str = _DEFAULT_INSTANCE,
        service: str = _DEFAULT_SERVICE,
        locator: str | None = None,
    ) -> Rid:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", type_):
            raise RidError(
                f"Invalid type {type_!r} — must be lowercase, start with a letter, "
                "and contain only [a-z0-9_]."
            )
        return cls(
            service=service,
            instance=instance,
            type=type_,
            locator=locator or str(uuid.uuid4()),
        )

    @classmethod
    def from_external(
        cls,
        type_: str,
        source: str,
        external_id: str,
        *,
        instance: str = _DEFAULT_INSTANCE,
        service: str = _DEFAULT_SERVICE,
    ) -> Rid:
        """Construct an RID whose locator embeds an external system's id.

        E.g. ``Rid.from_external("counterparty", "lei", "213800ABC...")``
        gives ``rid.princeps.production.counterparty.lei-213800ABC...``.
        """
        clean = re.sub(r"[^a-zA-Z0-9_.-]", "_", external_id)
        return cls.new(type_, instance=instance, service=service, locator=f"{source}-{clean}")


# Convenience constructors per ontology type — keeps callers out of magic strings.
def site_rid(locator: str | None = None) -> Rid:
    return Rid.new("site", locator=locator)


def substation_rid(locator: str | None = None) -> Rid:
    return Rid.new("substation", locator=locator)


def gsp_rid(neso_gsp_id: str | None = None) -> Rid:
    if neso_gsp_id:
        return Rid.from_external("gsp", "neso", neso_gsp_id)
    return Rid.new("gsp")


def repd_rid(repd_reference: str) -> Rid:
    return Rid.from_external("repd", "repd", repd_reference)


def counterparty_rid(*, lei: str | None = None, ch_number: str | None = None) -> Rid:
    if lei:
        return Rid.from_external("counterparty", "lei", lei)
    if ch_number:
        return Rid.from_external("counterparty", "ch", ch_number)
    return Rid.new("counterparty")


def bess_rid() -> Rid:
    return Rid.new("bess_unit")


def solar_farm_rid() -> Rid:
    return Rid.new("solar_farm")


def wind_farm_rid() -> Rid:
    return Rid.new("wind_farm")


def data_centre_rid() -> Rid:
    return Rid.new("data_centre")


def tender_rid() -> Rid:
    return Rid.new("tender")

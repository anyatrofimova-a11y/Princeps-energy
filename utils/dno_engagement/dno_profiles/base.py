"""
utils.dno_engagement.dno_profiles.base — DnoProfile protocol + default.

Each DNO supplies:
  * ``code`` / ``name`` / ``licence_areas``
  * voltage ladder — the standard HV voltages the DNO operates at
  * ECR adapter key — which dataset slug to call in utils.dno_capacity_ingester
  * protection template — G99 Table 10.1 overrides
  * G99 notes — DNO-specific commentary (e.g. SSEN's islanding requirements
    for remote Scotland, UKPN's LPN constraints)
  * RIIO period — RIIO-ED2 (2023-2028) or RIIO-ED3 (2028-) placeholder
  * LTDS citation
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class DnoProfile:
    """Per-DNO overrides used by the engagement pack engine."""

    code: str
    name: str
    licence_areas: list[str] = field(default_factory=list)

    # Voltage hierarchy — e.g. SSEN SEPD: [400, 132, 33, 11, 0.4]
    voltage_ladder_kv: list[float] = field(default_factory=list)

    # Which dno_capacity_ingester adapter returns this DNO's ECR feed.
    ecr_adapter: str = "opendatasoft"
    ecr_dataset_slug: str = ""

    # G99 Table 10.1 overrides (voltage-level → settings).
    # Each key: voltage_kv; value: dict of relay settings per G99 §10.
    protection_template: dict[str, Any] = field(default_factory=dict)

    # DNO-specific G99 notes (shown in DNO pack §10 protection section).
    g99_notes: list[str] = field(default_factory=list)

    # RIIO period + Ofgem determination reference.
    riio_period: str = "RIIO-ED2"
    riio_window: str = "2023-04-01 to 2028-03-31"
    riio_ref: str = ""

    # LTDS citation (Long Term Development Statement — Licence Condition 25).
    ltds_publication: str = ""
    ltds_publication_date: str = ""
    ltds_primary_table: str = ""
    ltds_page_ref: str = ""
    ltds_url: str = ""

    # Contacts (public) — connection team, pre-app portal.
    connection_portal_url: str = ""
    pre_app_enquiry_email: str = ""

    # Flag — True if this profile has been fully researched. v1 sets True
    # only for SSEN; others stub with reasonable defaults.
    is_pilot: bool = False

    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# A generic "unknown DNO" profile used when the caller cannot resolve
# the project location to a known licence area.
DEFAULT_PROFILE = DnoProfile(
    code="UNKNOWN",
    name="Unknown / unresolved DNO",
    licence_areas=[],
    voltage_ladder_kv=[132, 33, 11, 0.4],
    ecr_adapter="opendatasoft",
    ecr_dataset_slug="",
    protection_template={},
    g99_notes=[
        "No DNO resolved — ENA EREC G99 Issue 2 Table 10.1 applied with "
        "default RoCoF (1 Hz/s, 500 ms) and ±6% voltage envelope.",
    ],
    riio_period="RIIO-ED2",
    riio_window="2023-04-01 to 2028-03-31",
    riio_ref="Ofgem RIIO-ED2 Final Determinations, Nov 2022",
    ltds_publication="N/A",
    ltds_publication_date="N/A",
    ltds_primary_table="N/A",
    ltds_page_ref="N/A",
    ltds_url="",
    connection_portal_url="",
    pre_app_enquiry_email="",
    is_pilot=False,
    notes=[
        "Project location did not resolve to a DNO licence area — "
        "pack author to manually set the DNO code before dispatch.",
    ],
)

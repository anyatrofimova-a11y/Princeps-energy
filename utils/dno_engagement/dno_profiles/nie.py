"""
utils.dno_engagement.dno_profiles.nie — NIE Networks profile (Northern Ireland, stub).

NIE Networks is not under GB's Ofgem — it's regulated by the Utility
Regulator of Northern Ireland. The Distribution Code and Grid Code
differ and G99 does not apply; NIE uses its own Distribution Connection
Agreement (DCA) process.

v1 stub flags this so the DNO pack composer emits a "not supported" note
if a project resolves to NIE Networks.
"""

from __future__ import annotations

from .base import DnoProfile

NIE_PROFILE = DnoProfile(
    code="NIE",
    name="NIE Networks (Northern Ireland Electricity)",
    licence_areas=["NI"],
    voltage_ladder_kv=[110, 33, 11, 0.4],   # NI uses 110 kV, not 132 kV.
    ecr_adapter="none",
    ecr_dataset_slug="",
    protection_template={},
    g99_notes=[
        "NIE Networks is regulated by the Utility Regulator of Northern "
        "Ireland — NOT Ofgem. G99 does not apply; use the NIE Distribution "
        "Code + Distribution Connection Agreement (DCA).",
        "NI operates a 110 kV sub-transmission tier rather than 132 kV.",
        "v1 pack does NOT support NIE — composer must fall back to manual.",
    ],
    riio_period="RP7 (NI regulatory period 2024-2031)",
    riio_window="2024-10-01 to 2031-09-30",
    riio_ref="Utility Regulator RP7 Final Determination (Mar 2024)",
    ltds_publication="NIE Networks 7-Year Forecast Statement",
    ltds_publication_date="Annual (typical Q3)",
    ltds_primary_table="Section 3 — Network Development",
    ltds_page_ref="Section 3 + Appendix A",
    ltds_url="https://www.nienetworks.co.uk/about-us/our-business-plan",
    connection_portal_url="https://www.nienetworks.co.uk/connections",
    pre_app_enquiry_email="connections@nienetworks.co.uk",
    is_pilot=False,
    notes=[
        "v1 NOT supported — Princeps DNO Engagement Pack is GB-only for now.",
        "NI connection work tracked under Task #22 (deferred).",
    ],
)

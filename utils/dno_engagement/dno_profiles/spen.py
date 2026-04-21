"""
utils.dno_engagement.dno_profiles.spen — SP Energy Networks profile (stub).
"""

from __future__ import annotations

from .base import DnoProfile

SPEN_PROFILE = DnoProfile(
    code="SPEN",
    name="SP Energy Networks (SPD, SPM)",
    licence_areas=["SPD", "SPM"],
    voltage_ladder_kv=[132, 33, 11, 0.4],
    ecr_adapter="opendatasoft",
    ecr_dataset_slug="spen-ecr",
    protection_template={},
    g99_notes=[
        "SPEN SPD (central Scotland) sits behind Cockenzie / Torness BSPs — "
        "132 kV connection options constrained by NGET bulk supply.",
        "SPEN SPM (Merseyside / Cheshire / North Wales) has high solar "
        "penetration — non-firm offers now standard on new >10 MW export.",
        "v1 pack uses G99 Issue 2 default protection.",
    ],
    riio_period="RIIO-ED2",
    riio_window="2023-04-01 to 2028-03-31",
    riio_ref="Ofgem RIIO-ED2 Final Determinations (29 Nov 2022) — SPEN",
    ltds_publication="SPEN Long Term Development Statement 2024",
    ltds_publication_date="October 2024",
    ltds_primary_table="Table 3 — Demand / Generation Headroom",
    ltds_page_ref="SPD §5.2 p. 41; SPM §5.2 p. 48",
    ltds_url="https://www.spenergynetworks.co.uk/pages/ltds.aspx",
    connection_portal_url="https://www.spenergynetworks.co.uk/pages/connections.aspx",
    pre_app_enquiry_email="newconnections@spenergynetworks.co.uk",
    is_pilot=False,
    notes=["v1 stub — full profile in v2."],
)

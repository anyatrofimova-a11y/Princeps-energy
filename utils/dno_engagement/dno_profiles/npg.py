"""
utils.dno_engagement.dno_profiles.npg — Northern Powergrid profile (stub).
"""

from __future__ import annotations

from .base import DnoProfile

NPG_PROFILE = DnoProfile(
    code="NPG",
    name="Northern Powergrid (NEDL, YEDL)",
    licence_areas=["NEDL", "YEDL"],
    voltage_ladder_kv=[132, 66, 33, 11, 0.4],
    ecr_adapter="opendatasoft",
    ecr_dataset_slug="npg-ecr",
    protection_template={},
    g99_notes=[
        "NPG operates both 66 kV and 33 kV sub-transmission — voltage "
        "ladder choice depends on the BSP parent.",
        "NPG NEDL (North East England) has high offshore wind backfeed — "
        "check reverse-power limits carefully in generation offers.",
        "v1 pack uses G99 Issue 2 default protection.",
    ],
    riio_period="RIIO-ED2",
    riio_window="2023-04-01 to 2028-03-31",
    riio_ref="Ofgem RIIO-ED2 Final Determinations (29 Nov 2022) — NPG",
    ltds_publication="Northern Powergrid LTDS 2024",
    ltds_publication_date="September 2024",
    ltds_primary_table="Table 4 — Primary Substation Capacity",
    ltds_page_ref="NEDL §6.3 p. 36; YEDL §6.3 p. 38",
    ltds_url="https://www.northernpowergrid.com/ltds",
    connection_portal_url="https://www.northernpowergrid.com/connections",
    pre_app_enquiry_email="connections@northernpowergrid.com",
    is_pilot=False,
    notes=["v1 stub — full profile in v2."],
)

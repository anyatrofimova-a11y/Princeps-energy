"""
utils.dno_engagement.dno_profiles.enwl — Electricity North West profile (stub).
"""

from __future__ import annotations

from .base import DnoProfile

ENWL_PROFILE = DnoProfile(
    code="ENWL",
    name="Electricity North West",
    licence_areas=["NWEST"],
    voltage_ladder_kv=[132, 33, 11, 6.6, 0.4],
    ecr_adapter="opendatasoft",
    ecr_dataset_slug="enwl-ecr",
    protection_template={},
    g99_notes=[
        "ENWL operates a 6.6 kV legacy tier in older urban Manchester "
        "networks — rare but worth noting in protection design.",
        "ENWL is the smallest DNO by area — reinforcement windows tend "
        "to be shorter than other DNOs.",
        "v1 pack uses G99 Issue 2 default protection.",
    ],
    riio_period="RIIO-ED2",
    riio_window="2023-04-01 to 2028-03-31",
    riio_ref="Ofgem RIIO-ED2 Final Determinations (29 Nov 2022) — ENWL",
    ltds_publication="ENWL LTDS 2024",
    ltds_publication_date="October 2024",
    ltds_primary_table="Section 4 — Bulk Supply Point Firm Capacity",
    ltds_page_ref="§4.2 p. 28-45",
    ltds_url="https://www.enwl.co.uk/ltds",
    connection_portal_url="https://www.enwl.co.uk/connections",
    pre_app_enquiry_email="connections@enwl.co.uk",
    is_pilot=False,
    notes=["v1 stub — full profile in v2."],
)

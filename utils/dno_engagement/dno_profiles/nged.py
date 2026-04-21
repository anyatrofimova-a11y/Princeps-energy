"""
utils.dno_engagement.dno_profiles.nged — National Grid Electricity Distribution (stub).

v1 stub — covers former WPD licence areas (EMID, WMID, SWALES, SWEST).
"""

from __future__ import annotations

from .base import DnoProfile

NGED_PROFILE = DnoProfile(
    code="NGED",
    name="National Grid Electricity Distribution (formerly WPD)",
    licence_areas=["EMID", "WMID", "SWALES", "SWEST"],
    voltage_ladder_kv=[132, 33, 11, 0.4],
    ecr_adapter="ckan",
    ecr_dataset_slug="nged-ckan",
    protection_template={},
    g99_notes=[
        "NGED operates a Flexibility Services zonal map — large generation "
        "offers in the Midlands test-flex before firm reinforcement.",
        "NGED's Connected Data Portal (CKAN) exposes ANM zones, HV / LV "
        "feeder topology, and reinforcement plans — used by Princeps "
        "nged_ckan_ingester.",
        "v1 pack uses G99 Issue 2 default protection.",
    ],
    riio_period="RIIO-ED2",
    riio_window="2023-04-01 to 2028-03-31",
    riio_ref="Ofgem RIIO-ED2 Final Determinations (29 Nov 2022) — NGED",
    ltds_publication="NGED Long Term Development Statement 2024 (CIM Stage 1.3)",
    ltds_publication_date="September 2024",
    ltds_primary_table="Table 2 — Firm Capacity at BSP / Primary",
    ltds_page_ref="EMID §3.2 p. 22; WMID §3.2 p. 24; SWALES §3.2 p. 20; SWEST §3.2 p. 21",
    ltds_url="https://www.nationalgrid.co.uk/ltds",
    connection_portal_url="https://www.nationalgrid.co.uk/electricity-distribution/customers-and-community/connections",
    pre_app_enquiry_email="connections@nationalgrid.co.uk",
    is_pilot=False,
    notes=["v1 stub — full profile in v2."],
)

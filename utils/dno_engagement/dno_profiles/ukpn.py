"""
utils.dno_engagement.dno_profiles.ukpn — UK Power Networks profile (stub).

v1 stub — populated for identification but protection template and G99
notes default to generic G99 Issue 2. To be fully researched in v2.
"""

from __future__ import annotations

from .base import DnoProfile

UKPN_PROFILE = DnoProfile(
    code="UKPN",
    name="UK Power Networks (EPN, LPN, SPN)",
    licence_areas=["EPN", "LPN", "SPN"],
    voltage_ladder_kv=[132, 66, 33, 11, 0.4],
    ecr_adapter="opendatasoft",
    ecr_dataset_slug="ukpn-ecr",
    protection_template={},
    g99_notes=[
        "UKPN Flexibility First — any new >1 MW demand offer is tested "
        "against flex auction before reinforcement is committed.",
        "LPN (London) secondary system runs at 66 kV/11 kV — voltage "
        "ladder differs from EPN/SPN (132 kV/33 kV).",
        "v1 pack uses G99 Issue 2 default protection — confirm with UKPN "
        "Connections the DNO-specific settings before commissioning.",
    ],
    riio_period="RIIO-ED2",
    riio_window="2023-04-01 to 2028-03-31",
    riio_ref="Ofgem RIIO-ED2 Final Determinations (29 Nov 2022) — UKPN",
    ltds_publication="UKPN Long Term Development Statement 2024",
    ltds_publication_date="November 2024",
    ltds_primary_table="Table 2b — Primary Substation Firm Capacity",
    ltds_page_ref="Vol. 2 §4.3, p. 58-117",
    ltds_url="https://www.ukpowernetworks.co.uk/our-services/ltds",
    connection_portal_url="https://www.ukpowernetworks.co.uk/our-services/connections",
    pre_app_enquiry_email="connections@ukpowernetworks.co.uk",
    is_pilot=False,
    notes=["v1 stub — full profile in v2."],
)

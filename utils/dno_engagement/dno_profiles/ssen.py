"""
utils.dno_engagement.dno_profiles.ssen — SSEN pilot profile.

Fully researched v1 profile — SSEN is the Princeps pilot DNO for the
DNO Engagement Pack engine.

SSEN operates two licence areas:
  * NSHI / SHEPD — Scottish Hydro-Electric Power Distribution (north of
    Scotland). Known for high reactive challenges, remote islands, and
    a distinctive 33 kV ring topology.
  * SEPD — Southern Electric Power Distribution (central southern
    England, Hampshire, Wiltshire, Oxfordshire, Isle of Wight).

The SSEN G99 notes are tighter than the default because SEPD and NSHI
both have published pre-app practices:
  * Constraint Management Zones (CMZs) on the Oxfordshire cluster
    require non-firm curtailment language in every offer.
  * NSHI islands (Orkney, Shetland) have their own protection envelope
    layered over the UK mainland set — not in scope for v1, but flagged.
"""

from __future__ import annotations

from .base import DnoProfile

SSEN_PROFILE = DnoProfile(
    code="SSEN",
    name="Scottish & Southern Electricity Networks (SSEN)",
    licence_areas=["SEPD", "NSHI (SHEPD)"],
    voltage_ladder_kv=[132, 33, 11, 0.4],
    ecr_adapter="opendatasoft",
    ecr_dataset_slug="ssen-ecr",
    protection_template={
        "11": {
            "ov_stage1": {"pickup_pu": 1.10, "delay_s": 1.0},
            "ov_stage2": {"pickup_pu": 1.15, "delay_s": 0.5},
            "uv_stage1": {"pickup_pu": 0.90, "delay_s": 2.5},
            "uv_stage2": {"pickup_pu": 0.80, "delay_s": 0.5},
            "of_stage1": {"pickup_hz": 51.5, "delay_s": 0.5},
            "uf_stage1": {"pickup_hz": 47.5, "delay_s": 20.0},
            "rocof":     {"pickup_hz_s": 1.0, "delay_s": 0.5,
                          "scheme": "G99 Issue 2 RoCoF (SSEN default)"},
            "reference": "G99 Issue 2 Table 10.1 — SSEN default",
        },
        "33": {
            "ov_stage1": {"pickup_pu": 1.10, "delay_s": 1.0},
            "ov_stage2": {"pickup_pu": 1.15, "delay_s": 0.5},
            "uv_stage1": {"pickup_pu": 0.90, "delay_s": 2.5},
            "uv_stage2": {"pickup_pu": 0.80, "delay_s": 0.5},
            "of_stage1": {"pickup_hz": 51.5, "delay_s": 0.5},
            "uf_stage1": {"pickup_hz": 47.5, "delay_s": 20.0},
            "rocof":     {"pickup_hz_s": 1.0, "delay_s": 0.5,
                          "scheme": "G99 Issue 2 RoCoF (SSEN default)"},
            "reference": "G99 Issue 2 Table 10.1 — SSEN default",
        },
        "132": {
            "ov_stage1": {"pickup_pu": 1.09, "delay_s": 1.0},
            "ov_stage2": {"pickup_pu": 1.15, "delay_s": 0.5},
            "uv_stage1": {"pickup_pu": 0.90, "delay_s": 2.5},
            "uv_stage2": {"pickup_pu": 0.80, "delay_s": 0.5},
            "of_stage1": {"pickup_hz": 51.5, "delay_s": 0.5},
            "uf_stage1": {"pickup_hz": 47.5, "delay_s": 20.0},
            "rocof":     {"pickup_hz_s": 1.0, "delay_s": 0.5,
                          "scheme": "G99 Issue 2 RoCoF (SSEN default)"},
            "reference": "G99 Issue 2 Table 10.1 — SSEN 132 kV overlay",
        },
    },
    g99_notes=[
        "SSEN SEPD: Constraint Management Zones (CMZs) in Oxfordshire, "
        "Berkshire, and parts of Hampshire — any offer above 5 MW will "
        "include CMZ curtailment language.",
        "SSEN NSHI (Scottish Hydro-Electric): 132 kV ring topology — "
        "check N-1 on the ring BEFORE firm offer is given.",
        "SSEN prefers RoCoF 1 Hz/s with 500 ms delay (G99 Issue 2 default); "
        "vector shift is deprecated for new Type B/C/D connections.",
        "SSEN operates a non-contestable assumption for works on the "
        "supergrid transformer; contestable on radial feeders.",
        "Pre-app Stage 1 enquiries: free. Stage 2 budget estimate: charged "
        "per CCCM v19 Sch.5 — currently £4,200-£12,000 depending on voltage.",
    ],
    riio_period="RIIO-ED2",
    riio_window="2023-04-01 to 2028-03-31",
    riio_ref="Ofgem RIIO-ED2 Final Determinations (29 Nov 2022) — SSEN",
    ltds_publication="SSEN LTDS 2024",
    ltds_publication_date="November 2024",
    ltds_primary_table="Appendix A — Generation Headroom by GSP Group",
    ltds_page_ref="NSHI p. 67; SEPD p. 72",
    ltds_url="https://www.ssen.co.uk/aboutus/ltds/",
    connection_portal_url="https://ssencommunity.co.uk/connections/",
    pre_app_enquiry_email="newconnections@ssen.co.uk",
    is_pilot=True,
    notes=[
        "Pilot DNO for Princeps DNO Engagement Pack v1.",
        "CMZ list at https://www.ssen.co.uk/our-services/connections/"
        "constraint-management-zones/ — refresh quarterly.",
    ],
)

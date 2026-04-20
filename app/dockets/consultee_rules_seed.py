"""
app/dockets/consultee_rules_seed.py — seed the UK consultee rules engine.

Each row in ``consultee_requirements`` encodes a single "if this then that"
rule, where the trigger is a JSONB blob containing any subset of:

    { "geometry_pred":      "within" | "intersects" | "adjacent" | "always",
      "capacity_threshold_mw": 10,
      "capacity_threshold_mwh": 1,
      "tech":                "solar" | "wind" | "bess" | "dc" | "any",
      "proximity_km":        2,
      "buffer_m":            500,
      "layer":               "SSSI" | "AONB" | "flood2" | "Listed" | "MoD" | "Airspace" | ... }

The resolver in ``utils/consultee_resolver.py`` walks the rules for a
given case_type + geometry + tech and unions the matched authorities.

Idempotent: deletes existing rows for the seeded case_types before
re-inserting so edits to the fixture propagate cleanly. Gated behind
``PRINCEPS_SEED_AUTHORITIES=true`` (same flag as authorities seeding).

TODO — this is ~50 rules covering the commercial-critical case types
(NSIP DCO, LPA solar/BESS, Ofgem code mods, AR7/CfD). Full taxonomy
expansion: s36, DNS, Ofgem RIIO-ED3, DCUSA, STC, judicial review.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from app.dockets.authorities_seed import resolve_authority_id

log = logging.getLogger("princeps.dockets.consultee_rules_seed")


# ── The rule set ────────────────────────────────────────────────────────
# One list of dicts; each will be resolved against the authorities table
# at seed time. Keep authority references as slugs so they survive
# re-seeds without stable UUIDs.

RULES: list[dict[str, Any]] = [

    # ── NSIP DCO (Planning Act 2008 s.42 + Regs 8/10) ─────────────────
    # Universal statutory consultees — apply to every energy NSIP.
    {"case_type": "nsip_dco", "authority_slug": "pins",            "trigger": {"geometry_pred": "always"},                                    "mandatory": True,  "consultation_period_days": 28,  "statutory_basis": "Planning Act 2008 s.55",  "reason_code": "pins_accepting_authority",     "draft_letter_slug": "nsip_pins_notification"},
    {"case_type": "nsip_dco", "authority_slug": "natural_england", "trigger": {"geometry_pred": "always"},                                    "mandatory": True,  "consultation_period_days": 28,  "statutory_basis": "APFP Regs 2009 Sch.1",   "reason_code": "nsip_s42_prescribed",          "draft_letter_slug": "nsip_s42_ne"},
    {"case_type": "nsip_dco", "authority_slug": "environment_agency","trigger":{"geometry_pred": "always"},                                   "mandatory": True,  "consultation_period_days": 28,  "statutory_basis": "APFP Regs 2009 Sch.1",   "reason_code": "nsip_s42_prescribed",          "draft_letter_slug": "nsip_s42_ea"},
    {"case_type": "nsip_dco", "authority_slug": "historic_england", "trigger": {"geometry_pred": "always"},                                   "mandatory": True,  "consultation_period_days": 28,  "statutory_basis": "APFP Regs 2009 Sch.1",   "reason_code": "nsip_s42_prescribed",          "draft_letter_slug": "nsip_s42_he"},
    {"case_type": "nsip_dco", "authority_slug": "forestry_england", "trigger": {"geometry_pred": "always", "tech": "any"},                   "mandatory": True,  "consultation_period_days": 28,  "statutory_basis": "APFP Regs 2009 Sch.1",   "reason_code": "nsip_s42_prescribed",          "draft_letter_slug": "nsip_s42_fe"},

    # Host & adjacent LPAs (buffer 500m) — resolver will fan out to actual LPA IDs via geometry.
    # A "sentinel" rule (authority_slug = None) is emitted so the resolver
    # knows to inject geometry-derived LPAs. Here we pin PINS as the
    # catch-all; the resolver layer does the real LPA fan-out.

    # Crown Estate — only if Crown land adjacent.
    {"case_type": "nsip_dco", "authority_slug": "crown_estate",    "trigger": {"geometry_pred": "adjacent", "layer": "crown_land"},          "mandatory": True,  "consultation_period_days": 28,  "statutory_basis": "APFP Regs 2009 Sch.1",   "reason_code": "crown_adjacent",               "draft_letter_slug": "nsip_crown_estate"},
    {"case_type": "nsip_dco", "authority_slug": "crown_estate_scotland","trigger":{"geometry_pred":"adjacent","layer":"crown_land_scotland"},"mandatory": True,  "consultation_period_days": 28,  "statutory_basis": "APFP Regs 2009 Sch.1",   "reason_code": "crown_adjacent_scotland",      "draft_letter_slug": "nsip_crown_estate_scotland"},

    # MoD DIO — only inside a safeguarding zone.
    {"case_type": "nsip_dco", "authority_slug": "mod_dio",         "trigger": {"geometry_pred": "within",   "layer": "mod_safeguard"},       "mandatory": True,  "consultation_period_days": 42,  "statutory_basis": "ODPM Circular 01/03",    "reason_code": "mod_safeguard",                "draft_letter_slug": "mod_dio_safeguard"},

    # MMO — marine / coastal projects.
    {"case_type": "nsip_dco", "authority_slug": "mmo",             "trigger": {"geometry_pred": "intersects","layer": "marine_plan_area"},    "mandatory": True,  "consultation_period_days": 42,  "statutory_basis": "Marine & Coastal Access Act 2009","reason_code": "mmo_marine",         "draft_letter_slug": "mmo_marine"},

    # CAA — wind or anything >50m tall OR within airspace safeguarding buffer.
    {"case_type": "nsip_dco", "authority_slug": "caa",             "trigger": {"geometry_pred": "within",   "layer": "airspace_buffer"},     "mandatory": True,  "consultation_period_days": 28,  "statutory_basis": "Air Navigation Order 2016","reason_code": "airspace_safeguard",          "draft_letter_slug": "caa_airspace"},
    {"case_type": "nsip_dco", "authority_slug": "caa",             "trigger": {"geometry_pred": "always",   "tech": "wind"},                  "mandatory": True,  "consultation_period_days": 28,  "statutory_basis": "Air Navigation Order 2016","reason_code": "wind_turbine_caa",            "draft_letter_slug": "caa_wind"},

    # Ofcom — wind / tall structures near telecom links.
    {"case_type": "nsip_dco", "authority_slug": "ofcom",           "trigger": {"geometry_pred": "within",   "layer": "telecom_link", "buffer_m": 500}, "mandatory": False, "consultation_period_days": 28,  "statutory_basis": "Wireless Telegraphy Act 2006","reason_code": "telecom_link",     "draft_letter_slug": "ofcom_telecom"},


    # ── LPA planning — solar ≥10 MW ──────────────────────────────────
    {"case_type": "lpa_planning", "authority_slug": "natural_england",     "trigger": {"tech": "solar", "capacity_threshold_mw": 10, "layer": "SSSI", "proximity_km": 1}, "mandatory": True,  "consultation_period_days": 21, "statutory_basis": "DMPO 2015 Sch.4", "reason_code": "sssi_within_1km",            "draft_letter_slug": "lpa_ne_sssi"},
    {"case_type": "lpa_planning", "authority_slug": "environment_agency", "trigger": {"tech": "solar", "capacity_threshold_mw": 10, "layer": "flood2"},                   "mandatory": True,  "consultation_period_days": 21, "statutory_basis": "DMPO 2015 Sch.4", "reason_code": "flood_zone_2_3",             "draft_letter_slug": "lpa_ea_flood"},
    {"case_type": "lpa_planning", "authority_slug": "historic_england",   "trigger": {"tech": "solar", "capacity_threshold_mw": 10, "layer": "listed_building", "buffer_m": 500}, "mandatory": True, "consultation_period_days": 21, "statutory_basis": "DMPO 2015 Sch.4", "reason_code": "listed_building_500m",   "draft_letter_slug": "lpa_he_listed"},
    {"case_type": "lpa_planning", "authority_slug": "forestry_england",   "trigger": {"tech": "solar", "capacity_threshold_mw": 10, "layer": "ancient_woodland"},         "mandatory": True,  "consultation_period_days": 21, "statutory_basis": "NPPF 2024 para 186", "reason_code": "ancient_woodland",        "draft_letter_slug": "lpa_fe_woodland"},
    {"case_type": "lpa_planning", "authority_slug": "mod_dio",            "trigger": {"tech": "solar", "capacity_threshold_mw": 10, "layer": "mod_safeguard"},            "mandatory": True,  "consultation_period_days": 21, "statutory_basis": "ODPM Circular 01/03","reason_code": "mod_safeguard",             "draft_letter_slug": "mod_dio_safeguard"},

    # ── LPA planning — BESS (any capacity, with co-location trigger) ─
    {"case_type": "lpa_planning", "authority_slug": "hse",                "trigger": {"tech": "bess", "capacity_threshold_mwh": 1},                                       "mandatory": True,  "consultation_period_days": 21, "statutory_basis": "HSE Planning Advice Note — BESS","reason_code": "bess_hse_liaison",       "draft_letter_slug": "lpa_hse_bess"},
    {"case_type": "lpa_planning", "authority_slug": "environment_agency", "trigger": {"tech": "bess", "capacity_threshold_mwh": 50},                                      "mandatory": True,  "consultation_period_days": 21, "statutory_basis": "EPR 2016 sch.8",  "reason_code": "bess_ea_permit",             "draft_letter_slug": "lpa_ea_bess"},

    # ── LPA planning — wind (onshore) ────────────────────────────────
    {"case_type": "lpa_planning", "authority_slug": "caa",                "trigger": {"tech": "wind"},                                                                     "mandatory": True,  "consultation_period_days": 21, "statutory_basis": "Air Navigation Order 2016","reason_code": "wind_turbine_caa",       "draft_letter_slug": "caa_wind"},
    {"case_type": "lpa_planning", "authority_slug": "natural_england",    "trigger": {"tech": "wind", "layer": "SPA_SAC", "proximity_km": 5},                              "mandatory": True,  "consultation_period_days": 21, "statutory_basis": "Habitats Regs 2017","reason_code": "hra_screening",             "draft_letter_slug": "lpa_ne_wind"},

    # ── LPA planning — data centres (large) ──────────────────────────
    {"case_type": "lpa_planning", "authority_slug": "environment_agency", "trigger": {"tech": "dc", "capacity_threshold_mw": 50},                                          "mandatory": True,  "consultation_period_days": 21, "statutory_basis": "EPR 2016",          "reason_code": "dc_cooling_water",         "draft_letter_slug": "lpa_ea_dc"},
    {"case_type": "lpa_planning", "authority_slug": "hse",                "trigger": {"tech": "dc", "capacity_threshold_mw": 50},                                          "mandatory": False, "consultation_period_days": 21, "statutory_basis": "HSE Planning Advice Note","reason_code": "dc_backup_fuel",        "draft_letter_slug": "lpa_hse_dc"},


    # ── Ofgem code modifications — CMP / GC / BSC / CUSC / DCUSA ────
    {"case_type": "cmp", "authority_slug": "elexon",               "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "BSC s.F",        "reason_code": "bsc_panel",           "draft_letter_slug": "ofgem_cmp_elexon"},
    {"case_type": "cmp", "authority_slug": "neso",                 "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "CUSC s.8",       "reason_code": "neso_signatory",      "draft_letter_slug": "ofgem_cmp_neso"},
    {"case_type": "cmp", "authority_slug": "nget",                 "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "CUSC s.8",       "reason_code": "to_signatory",        "draft_letter_slug": "ofgem_cmp_to"},
    {"case_type": "cmp", "authority_slug": "spt",                  "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "CUSC s.8",       "reason_code": "to_signatory",        "draft_letter_slug": "ofgem_cmp_to"},
    {"case_type": "cmp", "authority_slug": "shet",                 "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "CUSC s.8",       "reason_code": "to_signatory",        "draft_letter_slug": "ofgem_cmp_to"},
    {"case_type": "cmp", "authority_slug": "ukpn",                 "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "DCUSA",           "reason_code": "dno_signatory",       "draft_letter_slug": "ofgem_cmp_dno"},
    {"case_type": "cmp", "authority_slug": "nged",                 "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "DCUSA",           "reason_code": "dno_signatory",       "draft_letter_slug": "ofgem_cmp_dno"},
    {"case_type": "cmp", "authority_slug": "northern_powergrid",   "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "DCUSA",           "reason_code": "dno_signatory",       "draft_letter_slug": "ofgem_cmp_dno"},
    {"case_type": "cmp", "authority_slug": "sse_distribution",     "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "DCUSA",           "reason_code": "dno_signatory",       "draft_letter_slug": "ofgem_cmp_dno"},
    {"case_type": "cmp", "authority_slug": "spen_distribution",    "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "DCUSA",           "reason_code": "dno_signatory",       "draft_letter_slug": "ofgem_cmp_dno"},
    {"case_type": "cmp", "authority_slug": "enw",                  "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "DCUSA",           "reason_code": "dno_signatory",       "draft_letter_slug": "ofgem_cmp_dno"},

    # Grid Code mods — similar shape, shorter consultation.
    {"case_type": "gc",  "authority_slug": "neso",                 "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "Grid Code GB",    "reason_code": "gc_signatory",        "draft_letter_slug": "ofgem_gc_neso"},
    {"case_type": "gc",  "authority_slug": "nget",                 "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "Grid Code GB",    "reason_code": "gc_signatory",        "draft_letter_slug": "ofgem_gc_to"},

    # BSC modifications — Elexon central + user groups.
    {"case_type": "bsc_pmod", "authority_slug": "elexon",          "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 15, "statutory_basis": "BSC s.F",         "reason_code": "bsc_panel",           "draft_letter_slug": "ofgem_bsc_elexon"},
    {"case_type": "bsc_pmod", "authority_slug": "neso",            "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 15, "statutory_basis": "BSC s.F",         "reason_code": "bsc_settlement",      "draft_letter_slug": "ofgem_bsc_neso"},


    # ── CfD (AR7 — 2026 round) ──────────────────────────────────────
    {"case_type": "cfd_round", "authority_slug": "lccc",           "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "Energy Act 2013", "reason_code": "cfd_counterparty",    "draft_letter_slug": "cfd_lccc"},
    {"case_type": "cfd_round", "authority_slug": "desnz",          "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "Energy Act 2013", "reason_code": "cfd_policy_lead",     "draft_letter_slug": "cfd_desnz"},
    {"case_type": "cfd_round", "authority_slug": "emrs",           "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "Energy Act 2013", "reason_code": "cfd_settlement",      "draft_letter_slug": "cfd_emrs"},
    {"case_type": "cfd_round", "authority_slug": "neso",           "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "Energy Act 2013", "reason_code": "cfd_dispatch",        "draft_letter_slug": "cfd_neso"},


    # ── Capacity Market auction ─────────────────────────────────────
    {"case_type": "cm_auction", "authority_slug": "neso",          "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "CM Rules 2014",   "reason_code": "cm_delivery_body",    "draft_letter_slug": "cm_neso"},
    {"case_type": "cm_auction", "authority_slug": "emrs",          "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "CM Rules 2014",   "reason_code": "cm_settlement",       "draft_letter_slug": "cm_emrs"},
    {"case_type": "cm_auction", "authority_slug": "desnz",         "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "CM Rules 2014",   "reason_code": "cm_policy_lead",      "draft_letter_slug": "cm_desnz"},


    # ── DNO connection cases (Gate 2 / NESO TMO4+) ───────────────────
    {"case_type": "dno_connection_case", "authority_slug": "neso", "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 14, "statutory_basis": "CUSC s.6",        "reason_code": "neso_gate_holder",    "draft_letter_slug": "dno_neso"},

    # ── Scottish s36 ────────────────────────────────────────────────
    {"case_type": "section36", "authority_slug": "ecu",            "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "Electricity Act 1989 s.36", "reason_code": "scottish_ministers", "draft_letter_slug": "s36_ecu"},
    {"case_type": "section36", "authority_slug": "naturescot",     "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "Electricity Act 1989 s.36", "reason_code": "statutory_scotland", "draft_letter_slug": "s36_naturescot"},
    {"case_type": "section36", "authority_slug": "sepa",           "trigger": {"geometry_pred": "always"}, "mandatory": True,  "consultation_period_days": 28, "statutory_basis": "Electricity Act 1989 s.36", "reason_code": "statutory_scotland", "draft_letter_slug": "s36_sepa"},
    {"case_type": "section36", "authority_slug": "historic_environment_scotland", "trigger": {"geometry_pred":"always"}, "mandatory": True, "consultation_period_days": 28, "statutory_basis": "Electricity Act 1989 s.36","reason_code":"statutory_scotland","draft_letter_slug":"s36_hes"},

    # ── Welsh DNS ───────────────────────────────────────────────────
    {"case_type": "scottish_dns", "authority_slug": "pedw",                       "trigger": {"geometry_pred": "always"}, "mandatory": True, "consultation_period_days": 28, "statutory_basis": "Welsh DNS Order 2016",    "reason_code": "pedw_decision_body",   "draft_letter_slug": "dns_pedw"},
    {"case_type": "scottish_dns", "authority_slug": "natural_resources_wales",    "trigger": {"geometry_pred": "always"}, "mandatory": True, "consultation_period_days": 28, "statutory_basis": "Welsh DNS Order 2016",    "reason_code": "nrw_statutory",        "draft_letter_slug": "dns_nrw"},
    {"case_type": "scottish_dns", "authority_slug": "cadw",                       "trigger": {"geometry_pred": "always"}, "mandatory": True, "consultation_period_days": 28, "statutory_basis": "Welsh DNS Order 2016",    "reason_code": "cadw_historic",        "draft_letter_slug": "dns_cadw"},

    # ── BESS explicit — always trigger HSE + local F&RS ─────────────
    # Separate case_type hook for non-planning BESS notifications.
    {"case_type": "hse_comah", "authority_slug": "hse",            "trigger": {"tech": "bess", "capacity_threshold_mwh": 1},  "mandatory": True,  "consultation_period_days": 14, "statutory_basis": "COMAH 2015",         "reason_code": "comah_lower_tier",        "draft_letter_slug": "bess_comah"},
]


async def seed_consultee_rules(pool: asyncpg.Pool) -> int:
    """Idempotent seed of the ``consultee_requirements`` table.

    Strategy
    --------
    1. Resolve authority slugs → UUIDs from the authorities table.
    2. Delete existing rows for the covered (case_type, reason_code) tuples.
    3. Bulk-insert the fresh set.

    Safe to re-run; rule edits in RULES propagate by reason_code.
    """
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT to_regclass('public.consultee_requirements') IS NOT NULL"
        )
        if not exists:
            log.info("seed_consultee_rules: consultee_requirements table missing — skipping")
            return 0

        # Resolve authority slugs up-front so we don't round-trip per rule.
        slugs_needed = {r["authority_slug"] for r in RULES if r.get("authority_slug")}
        slug_map: dict[str, str] = {}
        for slug in slugs_needed:
            auth_id = await resolve_authority_id(conn, slug)
            if auth_id:
                slug_map[slug] = auth_id

        missing = slugs_needed - slug_map.keys()
        if missing:
            log.warning(
                "seed_consultee_rules: %d authorities missing from registry — "
                "rules referencing them will be skipped: %s",
                len(missing), sorted(missing),
            )

        # Clear the slate for the (case_type, reason_code) pairs we own so
        # the seed is idempotent. This leaves hand-authored rules alone.
        seeded_keys = {(r["case_type"], r.get("reason_code")) for r in RULES}
        for case_type, reason_code in seeded_keys:
            if reason_code is None:
                continue
            await conn.execute(
                "DELETE FROM consultee_requirements "
                "WHERE case_type = $1 AND reason_code = $2",
                case_type, reason_code,
            )

        inserted = 0
        for rule in RULES:
            slug = rule.get("authority_slug")
            authority_id = slug_map.get(slug) if slug else None
            if not authority_id:
                continue
            try:
                await conn.execute(
                    """
                    INSERT INTO consultee_requirements
                        (case_type, trigger, authority_id, mandatory,
                         consultation_period_days, statutory_basis,
                         reason_code, draft_letter_slug)
                    VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7, $8)
                    """,
                    rule["case_type"],
                    json.dumps(rule.get("trigger") or {}),
                    authority_id,
                    bool(rule.get("mandatory", True)),
                    rule.get("consultation_period_days"),
                    rule.get("statutory_basis"),
                    rule.get("reason_code"),
                    rule.get("draft_letter_slug"),
                )
                inserted += 1
            except Exception as exc:
                log.warning(
                    "seed_consultee_rules: insert failed for %s/%s: %s",
                    rule.get("case_type"), rule.get("reason_code"), exc,
                )
                continue

    log.info("seed_consultee_rules: inserted %d / %d rules", inserted, len(RULES))
    return inserted


__all__ = ["seed_consultee_rules", "RULES"]

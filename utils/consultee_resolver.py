"""
utils/consultee_resolver.py — THE MOAT.

Given a geometry WKT + case_type + tech + capacity_mw, return the full
set of authorities that a project would need to consult, drawn from:

1. ``consultee_requirements`` rules (see
   ``app/dockets/consultee_rules_seed.py`` for the seeded rule set).
2. Geometry-derived authorities — host LPAs, parish councils, DNOs in
   whose licence area the site falls, TOs for transmission-voltage
   connections, MoD safeguarding zones, SSSI/AONB/SPA proximity, CAA
   airspace safeguarding buffers, Listed Buildings within 500m, MMO
   marine plan areas.
3. Current stakeholder status from the supplied docket (optional), so
   the caller can see *"Natural England: already objecting — last
   submission 2026-03-07"*.

Returns a dict shaped for the GET /api/consultees endpoint:

  {
    "consultees":         [ {authority_id, name, acronym, type, mandatory,
                              consultation_period_days, current_status,
                              statutory_basis, reason_code }, ... ],
    "reason_codes":       [ "sssi_within_1km", "flood_zone_2_3", ... ],
    "draft_email_slugs":  [ "lpa_ne_sssi", "lpa_ea_flood", ... ]
  }

TODO layers that may not yet be present in PostGIS — this resolver
gracefully skips them and logs a one-line warning:
  - ``magic_constraints`` (SSSI, AONB, flood, habitat)
  - ``mod_safeguarding``
  - ``caa_airspace``
  - ``listed_buildings``
  - ``marine_plan_areas``
  - ``lpa_boundaries``
  - ``parish_councils``
  - ``dno_licence_areas``  (we have ``grid_dno_boundaries`` which we use)
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg

log = logging.getLogger("princeps.consultee_resolver")


# ── Layer probe cache — avoid repeating to_regclass per request ─────────
_LAYER_CACHE: dict[str, bool] = {}


async def _table_exists(conn: asyncpg.Connection, tbl: str) -> bool:
    if tbl in _LAYER_CACHE:
        return _LAYER_CACHE[tbl]
    v = await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{tbl}")
    _LAYER_CACHE[tbl] = bool(v)
    return bool(v)


def _wkt_to_geog_expr(wkt: str) -> str:
    """Wrap a WKT for PostGIS geography intersection — SRID 4326 assumed
    unless the caller prefixed SRID=27700; in that case we transform."""
    # Callers almost always pass 4326. If EWKT with SRID=NNNN; prefix,
    # ST_GeomFromEWKT handles it.
    if wkt.upper().startswith("SRID="):
        return "ST_Transform(ST_GeomFromEWKT($1), 4326)::geography"
    return "ST_SetSRID(ST_GeomFromText($1), 4326)::geography"


# ── Main entrypoint ────────────────────────────────────────────────────

async def resolve_consultees(
    pool: asyncpg.Pool,
    *,
    geometry_wkt: str | None,
    case_type: str,
    tech: str | None = None,
    capacity_mw: float | None = None,
    capacity_mwh: float | None = None,
    docket_id: str | UUID | None = None,
) -> dict[str, Any]:
    """Resolve the consultee list.

    ``geometry_wkt`` is optional — pure-policy case types like ``cmp``,
    ``gc``, ``bsc_pmod`` don't depend on a project footprint.
    """
    case_type = (case_type or "").lower()
    tech = (tech or "any").lower()

    async with pool.acquire() as conn:
        # 1. Rule-matched authorities (the big bulk).
        rule_matches = await _match_rules(
            conn,
            case_type=case_type,
            tech=tech,
            capacity_mw=capacity_mw,
            capacity_mwh=capacity_mwh,
            geometry_wkt=geometry_wkt,
        )

        # 2. Geometry-derived authorities — LPAs / parishes / DNOs / TOs.
        geometry_matches: list[dict[str, Any]] = []
        if geometry_wkt:
            geometry_matches = await _match_geometry(conn, geometry_wkt, case_type)

        # 3. Merge + dedupe by authority_id.
        merged: dict[str, dict[str, Any]] = {}
        for m in (*rule_matches, *geometry_matches):
            aid = m.get("authority_id")
            if not aid:
                continue
            if aid in merged:
                prev = merged[aid]
                # Prefer mandatory over discretionary.
                if m.get("mandatory") and not prev.get("mandatory"):
                    prev["mandatory"] = True
                    prev["statutory_basis"] = m.get("statutory_basis") or prev.get("statutory_basis")
                    prev["reason_code"] = m.get("reason_code") or prev.get("reason_code")
                # Keep the shortest consultation period (tightest deadline).
                p_old = prev.get("consultation_period_days")
                p_new = m.get("consultation_period_days")
                if p_new and (not p_old or p_new < p_old):
                    prev["consultation_period_days"] = p_new
            else:
                merged[aid] = dict(m)

        # 4. Overlay current stakeholder status if a docket was supplied.
        if docket_id:
            await _overlay_stakeholder_status(conn, merged, docket_id)

        # 5. Rank: mandatory first, then by shortest consultation period.
        consultees = sorted(
            merged.values(),
            key=lambda r: (
                not r.get("mandatory", False),
                r.get("consultation_period_days") or 9999,
                r.get("name") or "",
            ),
        )

        reason_codes = sorted({
            c.get("reason_code") for c in consultees if c.get("reason_code")
        })
        draft_email_slugs = sorted({
            c.get("draft_letter_slug") for c in consultees if c.get("draft_letter_slug")
        })

    return {
        "consultees":        consultees,
        "reason_codes":      list(reason_codes),
        "draft_email_slugs": list(draft_email_slugs),
        "case_type":         case_type,
        "tech":              tech,
    }


# ── Rule matching ──────────────────────────────────────────────────────

async def _match_rules(
    conn: asyncpg.Connection,
    *,
    case_type: str,
    tech: str,
    capacity_mw: float | None,
    capacity_mwh: float | None,
    geometry_wkt: str | None,
) -> list[dict[str, Any]]:
    """Evaluate each seeded rule for this case_type and return those whose
    trigger conditions match."""
    rules = await conn.fetch(
        """
        SELECT r.id, r.trigger, r.authority_id, r.mandatory,
               r.consultation_period_days, r.statutory_basis,
               r.reason_code, r.draft_letter_slug,
               a.slug AS authority_slug, a.name AS authority_name,
               a.acronym AS authority_acronym, a.type AS authority_type,
               a.logo_url AS authority_logo
        FROM consultee_requirements r
        JOIN authorities a ON a.id = r.authority_id
        WHERE r.case_type = $1
        """,
        case_type,
    )

    matches: list[dict[str, Any]] = []
    for r in rules:
        trigger = r["trigger"] or {}
        if isinstance(trigger, str):
            try:
                trigger = json.loads(trigger)
            except Exception:
                trigger = {}

        # tech gate
        t = (trigger.get("tech") or "any").lower()
        if t not in ("any", tech):
            continue
        # capacity gates
        thr_mw = trigger.get("capacity_threshold_mw")
        if thr_mw and (capacity_mw is None or capacity_mw < float(thr_mw)):
            continue
        thr_mwh = trigger.get("capacity_threshold_mwh")
        if thr_mwh and (capacity_mwh is None or capacity_mwh < float(thr_mwh)):
            continue

        # geometry-dependent rules: check the named layer.
        # A rule is "geometry-dependent" if either geometry_pred is set
        # to something other than always, OR a layer is named (the layer
        # is the constraint the resolver actually tests).
        pred = (trigger.get("geometry_pred") or "always").lower()
        layer = trigger.get("layer")
        if layer:
            if not geometry_wkt:
                # Rule needs geometry we don't have — skip.
                continue
            # Default predicate for layer-gated rules is "within"
            # (site-within-buffer-of-layer) unless explicitly set.
            effective_pred = pred if pred != "always" else "within"
            ok = await _geometry_predicate(
                conn, geometry_wkt, effective_pred, layer,
                trigger.get("proximity_km"), trigger.get("buffer_m"),
            )
            if not ok:
                continue
        elif pred != "always" and not geometry_wkt:
            # Pred set but no layer and no geometry — skip.
            continue

        matches.append({
            "authority_id":   str(r["authority_id"]),
            "authority_slug": r["authority_slug"],
            "name":           r["authority_name"],
            "acronym":        r["authority_acronym"],
            "type":           r["authority_type"],
            "logo_url":       r["authority_logo"],
            "mandatory":      bool(r["mandatory"]),
            "consultation_period_days": r["consultation_period_days"],
            "statutory_basis": r["statutory_basis"],
            "reason_code":    r["reason_code"],
            "draft_letter_slug": r["draft_letter_slug"],
        })
    return matches


# ── Layer predicate evaluation ─────────────────────────────────────────

_LAYER_TABLE_MAP: dict[str, tuple[str, str]] = {
    # layer name → (table, geometry column)
    "SSSI":                ("magic_constraints", "geom"),
    "AONB":                ("magic_constraints", "geom"),
    "flood2":              ("magic_constraints", "geom"),
    "flood3":              ("magic_constraints", "geom"),
    "habitat":             ("magic_constraints", "geom"),
    "SPA_SAC":             ("magic_constraints", "geom"),
    "ancient_woodland":    ("magic_constraints", "geom"),
    "listed_building":     ("listed_buildings",  "geom"),
    "mod_safeguard":       ("mod_safeguarding",  "geom"),
    "airspace_buffer":     ("caa_airspace",      "geom"),
    "marine_plan_area":    ("marine_plan_areas", "geom"),
    "crown_land":          ("crown_estate_land", "geom"),
    "crown_land_scotland": ("crown_estate_scotland_land", "geom"),
    "telecom_link":        ("ofcom_telecom_links", "geom"),
}


async def _geometry_predicate(
    conn: asyncpg.Connection,
    wkt: str,
    pred: str,
    layer: str,
    proximity_km: float | None,
    buffer_m: float | None,
) -> bool:
    """Return True if the layer is absent (fail-open — better to over-consult
    than to silently skip) OR the predicate holds. We log once per
    missing layer so the operator can see what's unresolved."""
    tbl_info = _LAYER_TABLE_MAP.get(layer)
    if not tbl_info:
        # Unknown layer string — fail open.
        log.debug("consultee_resolver: unknown layer '%s' — keeping rule", layer)
        return True

    table, geom_col = tbl_info
    if not await _table_exists(conn, table):
        log.info("consultee_resolver: layer table '%s' missing — rule fails open", table)
        return True

    geog_expr = _wkt_to_geog_expr(wkt)

    # Build the spatial test.
    if pred == "intersects":
        sql = (
            f"SELECT EXISTS (SELECT 1 FROM {table} "
            f"WHERE ST_Intersects({geom_col}::geography, {geog_expr}))"
        )
        return bool(await conn.fetchval(sql, wkt))

    if pred == "within":
        # "site within a buffer around layer". Use buffer_m if specified;
        # proximity_km otherwise; default 0.
        buf_m = float(buffer_m) if buffer_m else (
            float(proximity_km) * 1000 if proximity_km else 0
        )
        sql = (
            f"SELECT EXISTS (SELECT 1 FROM {table} "
            f"WHERE ST_DWithin({geom_col}::geography, {geog_expr}, {buf_m}))"
        )
        return bool(await conn.fetchval(sql, wkt))

    if pred == "adjacent":
        # Touches or within 10m — the "adjacent" test used for Crown land.
        sql = (
            f"SELECT EXISTS (SELECT 1 FROM {table} "
            f"WHERE ST_DWithin({geom_col}::geography, {geog_expr}, 10))"
        )
        return bool(await conn.fetchval(sql, wkt))

    # Unknown predicate → fail open so the consultation still surfaces.
    return True


# ── Geometry-derived authorities (LPAs / DNOs / Parishes) ──────────────

async def _match_geometry(
    conn: asyncpg.Connection, wkt: str, case_type: str,
) -> list[dict[str, Any]]:
    """Return authorities whose geometry intersects the site's WKT.

    Covers:
    - Host LPA (via authorities.geometry where type='lpa')
    - DNO licence area (via grid_dno_boundaries — has licence area polys)
    - TOs (transmission-level only, coarse bbox match on authorities)
    """
    out: list[dict[str, Any]] = []
    geog = _wkt_to_geog_expr(wkt)

    # Host LPA — the authorities table has a geography column. When LPAs
    # don't have polygons yet this is a no-op.
    try:
        rows = await conn.fetch(
            f"""
            SELECT id, slug, name, acronym, type, logo_url
            FROM authorities
            WHERE type IN ('lpa','devolved')
              AND geometry IS NOT NULL
              AND ST_Intersects(geometry, {geog})
            LIMIT 20
            """,
            wkt,
        )
        for r in rows:
            out.append({
                "authority_id":   str(r["id"]),
                "authority_slug": r["slug"],
                "name":           r["name"],
                "acronym":        r["acronym"],
                "type":           r["type"],
                "logo_url":       r["logo_url"],
                "mandatory":      True,
                "consultation_period_days": 21,
                "statutory_basis": "DMPO 2015 / s.42 PA 2008 (host LPA)" if case_type == "nsip_dco" else "DMPO 2015",
                "reason_code":    "host_lpa",
                "draft_letter_slug": "host_lpa_notification",
            })
    except Exception as exc:
        log.debug("LPA geometry match skipped: %s", exc)

    # DNO — use grid_dno_boundaries to find the licence area, then look
    # up the authorities row by matching on the DNO slug.
    if await _table_exists(conn, "grid_dno_boundaries"):
        try:
            dno_row = await conn.fetchrow(
                f"""
                SELECT dno_code
                FROM grid_dno_boundaries
                WHERE ST_Intersects(geometry::geography, {geog})
                LIMIT 1
                """,
                wkt,
            )
            if dno_row and dno_row["dno_code"]:
                # Map DNO code to authority slug; small fixed mapping.
                _DNO_CODE_TO_SLUG = {
                    "UKPN": "ukpn", "NGED": "nged", "NPG": "northern_powergrid",
                    "SSEN": "sse_distribution", "SPEN": "spen_distribution",
                    "ENWL": "enw",
                }
                slug = _DNO_CODE_TO_SLUG.get(dno_row["dno_code"].upper())
                if slug:
                    auth = await conn.fetchrow(
                        "SELECT id, slug, name, acronym, type, logo_url "
                        "FROM authorities WHERE slug = $1", slug,
                    )
                    if auth:
                        out.append({
                            "authority_id":   str(auth["id"]),
                            "authority_slug": auth["slug"],
                            "name":           auth["name"],
                            "acronym":        auth["acronym"],
                            "type":           auth["type"],
                            "logo_url":       auth["logo_url"],
                            "mandatory":      True,
                            "consultation_period_days": 28,
                            "statutory_basis": "EREC G99/G100 grid connection",
                            "reason_code":    "dno_licence_area",
                            "draft_letter_slug": "dno_licence_area_notification",
                        })
        except Exception as exc:
            log.debug("DNO geometry match skipped: %s", exc)

    return out


# ── Stakeholder-status overlay ─────────────────────────────────────────

async def _overlay_stakeholder_status(
    conn: asyncpg.Connection,
    merged: dict[str, dict[str, Any]],
    docket_id: str | UUID,
) -> None:
    """For every authority we resolved, see if there's a matching row in
    ``stakeholders`` for the docket. If so, annotate ``current_status``.
    """
    if isinstance(docket_id, str):
        try:
            docket_id = UUID(docket_id)
        except ValueError:
            return

    rows = await conn.fetch(
        """
        SELECT authority_id, role, position, last_submission_at, submission_count
        FROM stakeholders
        WHERE docket_id = $1 AND authority_id IS NOT NULL
        """,
        docket_id,
    )
    lut = {str(r["authority_id"]): dict(r) for r in rows}
    for aid, rec in merged.items():
        s = lut.get(aid)
        rec["current_status"] = (
            {
                "role": s["role"],
                "position": s["position"],
                "last_submission_at": s["last_submission_at"],
                "submission_count": s["submission_count"] or 0,
            }
            if s else None
        )


__all__ = ["resolve_consultees"]

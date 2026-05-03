"""Solutions marketplace — Foundry-style packaged Slate dashboards.

  GET    /api/solutions/marketplace?category=&q=&featured_only=
                                                — list packages
  GET    /api/solutions/{slug}                  — package detail
  POST   /api/solutions/{slug}/install          — body {target_slug?}
                                                  Clones manifest into
                                                  workshop_modules under
                                                  target_slug, bumps
                                                  install_count.
  GET    /api/solutions/{slug}/installs         — installation history

Packages are seeded at startup from `_BUILT_IN_SOLUTIONS` (idempotent
ON CONFLICT). Future: support user-published packages from existing
workshop_modules with a "Publish to marketplace" button.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.deps import get_pool as _raw_pool  # noqa: F401
from app.middleware.tenant_jwt import get_tenant_pool as get_pool

log = logging.getLogger("princeps.solutions")
router = APIRouter(prefix="/api/solutions", tags=["solutions"])


# ── Built-in catalogue ──────────────────────────────────────────────────────
# These are real working manifests — same shape as workshop_modules.manifest.
# They use the Slate widgets (KPI / DatasetHealth / ObjectList / NotesFeed /
# QuiverChart) so they render the moment they're installed.

_BUILT_IN_SOLUTIONS: list[dict] = [
    {
        "slug": "uk-bess-pipeline",
        "title": "UK BESS Pipeline",
        "description": "Live KPI strip + REPD scatter + connector health + recent battery REPDs + ops notes — the BESS team's daily dashboard.",
        "category": "BESS",
        "vertical": "bess",
        "version": "1.0.0",
        "author": "Princeps",
        "featured": True,
        "required_object_types": ["REPDProject", "Substation"],
        "required_connectors": ["bmrs_settlement_prices", "hm_land_registry_ccod"],
        "manifest": {
            "title": "UK BESS Pipeline",
            "target_type": "bess_unit",
            "widgets": [
                {"id": "kpi-bess",  "kind": "KPI", "w": 3, "props": {"label": "Battery REPDs",      "endpoint": "/api/objects/REPDProject?technology=Battery&limit=1", "value_path": "count"}},
                {"id": "kpi-subs",  "kind": "KPI", "w": 3, "props": {"label": "Substations",        "endpoint": "/api/objects/Substation?limit=1",                       "value_path": "count"}},
                {"id": "kpi-conn",  "kind": "KPI", "w": 3, "props": {"label": "Connectors live",    "endpoint": "/api/datasets",                                          "value_path": "count"}},
                {"id": "kpi-notes", "kind": "KPI", "w": 3, "props": {"label": "Recent notes",       "endpoint": "/api/notes/recent?limit=1",                              "value_path": "count"}},
                {"id": "scatter",   "kind": "QuiverChart", "w": 8, "props": {"type": "REPDProject", "x_field": "capacity_mw", "y_field": "capacity_mw", "technology": "Battery", "limit": 200, "title": "REPD Battery — capacity"}},
                {"id": "health",    "kind": "DatasetHealth", "w": 4, "props": {"title": "Magritte connectors"}},
                {"id": "list",      "kind": "ObjectList", "w": 8, "props": {"type": "REPDProject", "technology": "Battery", "limit": 10, "title": "Recent battery REPDs", "columns": ["label", "capacity_mw", "status", "operator"]}},
                {"id": "feed",      "kind": "NotesFeed", "w": 4, "props": {"limit": 6, "title": "Recent ops notes"}},
            ],
        },
    },
    {
        "slug": "uk-data-centre-pipeline",
        "title": "UK Data Centre Pipeline",
        "description": "NSIP + REPD + TEC pipeline — capacity distribution, connector health, recent NSIP submissions.",
        "category": "Data Centre",
        "vertical": "dc",
        "version": "1.0.0",
        "author": "Princeps",
        "featured": True,
        "required_object_types": ["NSIPProject", "REPDProject", "TecQueueEntry"],
        "required_connectors": ["pins_nsip_dco"],
        "manifest": {
            "title": "UK Data Centre Pipeline",
            "target_type": "data_centre",
            "widgets": [
                {"id": "kpi-nsip", "kind": "KPI", "w": 3, "props": {"label": "NSIP projects",   "endpoint": "/api/objects/NSIPProject?limit=1",                       "value_path": "count"}},
                {"id": "kpi-repd", "kind": "KPI", "w": 3, "props": {"label": "REPD projects",   "endpoint": "/api/objects/REPDProject?limit=1",                       "value_path": "count"}},
                {"id": "kpi-tec",  "kind": "KPI", "w": 3, "props": {"label": "TEC queue",       "endpoint": "/api/objects/TecQueueEntry?limit=1",                     "value_path": "count"}},
                {"id": "kpi-rows", "kind": "KPI", "w": 3, "props": {"label": "Connectors live", "endpoint": "/api/datasets",                                          "value_path": "count"}},
                {"id": "scatter",  "kind": "QuiverChart", "w": 8, "props": {"type": "NSIPProject", "x_field": "capacity_mw", "y_field": "capacity_mw", "limit": 100, "title": "NSIP — capacity distribution"}},
                {"id": "health",   "kind": "DatasetHealth", "w": 4, "props": {"title": "Connector health"}},
                {"id": "list",     "kind": "ObjectList", "w": 12, "props": {"type": "NSIPProject", "limit": 12, "title": "Recent NSIPs", "columns": ["label", "sector", "status", "promoter", "capacity_mw"]}},
            ],
        },
    },
    {
        "slug": "ops-pulse",
        "title": "Ops Pulse",
        "description": "Connector health + recent notes + active projects table — the morning standup view.",
        "category": "Ops",
        "vertical": "all",
        "version": "1.0.0",
        "author": "Princeps",
        "featured": True,
        "required_connectors": [],
        "manifest": {
            "title": "Ops Pulse",
            "widgets": [
                {"id": "health",   "kind": "DatasetHealth", "w": 5, "props": {"title": "Magritte connectors"}},
                {"id": "feed",     "kind": "NotesFeed", "w": 7, "props": {"limit": 8, "title": "Recent ops notes"}},
                {"id": "projects", "kind": "ObjectList", "w": 12, "props": {"type": "Project", "limit": 12, "title": "Active projects", "columns": ["label", "stage", "verdict", "technology", "capacity_mw"]}},
            ],
        },
    },
    {
        "slug": "grid-headroom-tracker",
        "title": "Grid Headroom Tracker",
        "description": "Substation list + voltage filter + capacity scatter — for siting decisions and DNO engagement.",
        "category": "Grid",
        "vertical": "all",
        "version": "1.0.0",
        "author": "Princeps",
        "featured": False,
        "required_object_types": ["Substation"],
        "manifest": {
            "title": "Grid Headroom Tracker",
            "widgets": [
                {"id": "kpi", "kind": "KPI", "w": 4, "props": {"label": "Substations indexed", "endpoint": "/api/objects/Substation?limit=1", "value_path": "count"}},
                {"id": "kpi-hv", "kind": "KPI", "w": 4, "props": {"label": "132 kV+", "endpoint": "/api/objects/Substation?voltage_min=132&limit=1", "value_path": "count"}},
                {"id": "kpi-ehv", "kind": "KPI", "w": 4, "props": {"label": "275 kV+", "endpoint": "/api/objects/Substation?voltage_min=275&limit=1", "value_path": "count"}},
                {"id": "scatter", "kind": "QuiverChart", "w": 12, "props": {"type": "Substation", "x_field": "voltage_kv", "y_field": "voltage_kv", "voltage_min": 33, "limit": 300, "title": "Substations by voltage"}},
                {"id": "list", "kind": "ObjectList", "w": 12, "props": {"type": "Substation", "voltage_min": 132, "limit": 15, "title": "132 kV+ substations", "columns": ["label", "voltage_kv", "dno"]}},
            ],
        },
    },
    {
        "slug": "asset-risk-heatmap",
        "title": "Asset Risk Heatmap",
        "description": "HSE incidents + REPD status mix + recent ops notes — risk dashboard for portfolio review.",
        "category": "Risk",
        "vertical": "all",
        "version": "1.0.0",
        "author": "Princeps",
        "featured": False,
        "required_connectors": ["hse_riddor_incidents"],
        "manifest": {
            "title": "Asset Risk Heatmap",
            "widgets": [
                {"id": "kpi-incidents", "kind": "KPI", "w": 6, "props": {"label": "HSE incidents indexed", "endpoint": "/api/datasets", "value_path": "count"}},
                {"id": "kpi-pending",   "kind": "KPI", "w": 6, "props": {"label": "Pending approvals",     "endpoint": "/api/pending-actions?status=pending&limit=1", "value_path": "count"}},
                {"id": "scatter",       "kind": "QuiverChart", "w": 8, "props": {"type": "REPDProject", "x_field": "capacity_mw", "y_field": "status", "limit": 300, "title": "REPD status × capacity"}},
                {"id": "feed",          "kind": "NotesFeed", "w": 4, "props": {"limit": 8, "tag": "risk", "title": "Risk-tagged notes"}},
            ],
        },
    },
]


def _row_to_dict(r) -> dict:
    # `published_*`, `visibility`, `source_module_slug` come from the
    # 2026_05_03_marketplace_v2 migration. Use .get-style access via dict
    # cast so this stays safe if the migration hasn't applied yet.
    rd = dict(r)
    return {
        "package_id": str(rd["package_id"]),
        "slug": rd["slug"],
        "title": rd["title"],
        "description": rd["description"],
        "category": rd["category"],
        "vertical": rd["vertical"],
        "version": rd["version"],
        "author": rd["author"],
        "manifest": rd["manifest"] if isinstance(rd["manifest"], dict) else json.loads(rd["manifest"] or "{}"),
        "required_connectors": list(rd["required_connectors"] or []),
        "required_object_types": list(rd["required_object_types"] or []),
        "install_count": rd["install_count"],
        "featured": rd["featured"],
        "created_at": rd["created_at"].isoformat() if rd["created_at"] else None,
        "visibility": rd.get("visibility") or "public",
        "published_by": rd.get("published_by"),
        "published_at": rd["published_at"].isoformat() if rd.get("published_at") else None,
        "source_module_slug": rd.get("source_module_slug"),
    }


async def seed_built_in_solutions(pool):
    """Idempotent — UPSERTs all _BUILT_IN_SOLUTIONS into solution_packages.
    Hooked into app startup so the marketplace is always populated.

    Also stamps `published_by = 'Princeps (official)'` on inserts so new
    built-ins get the same author pill as the migration backfill applied
    to pre-existing rows. ON CONFLICT does NOT touch published_by, which
    preserves any user-edited author on republished packages.
    """
    n = 0
    # Detect whether the marketplace_v2 migration has applied; this lets
    # the seeder run cleanly on a database that hasn't been migrated yet.
    async with pool.acquire() as conn:
        has_v2 = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'solution_packages' AND column_name = 'published_by'"
        )
        for s in _BUILT_IN_SOLUTIONS:
            if has_v2:
                await conn.execute(
                    """
                    INSERT INTO solution_packages
                      (slug, title, description, category, vertical, version, author,
                       manifest, required_connectors, required_object_types, featured,
                       published_by, visibility)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,'public')
                    ON CONFLICT (slug) DO UPDATE
                      SET title = EXCLUDED.title,
                          description = EXCLUDED.description,
                          category = EXCLUDED.category,
                          vertical = EXCLUDED.vertical,
                          version = EXCLUDED.version,
                          manifest = EXCLUDED.manifest,
                          required_connectors = EXCLUDED.required_connectors,
                          required_object_types = EXCLUDED.required_object_types,
                          featured = EXCLUDED.featured,
                          updated_at = NOW()
                    """,
                    s["slug"], s["title"], s["description"],
                    s.get("category"), s.get("vertical"),
                    s.get("version", "1.0.0"), s.get("author", "Princeps"),
                    json.dumps(s["manifest"]),
                    s.get("required_connectors") or [],
                    s.get("required_object_types") or [],
                    s.get("featured", False),
                    "Princeps (official)",
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO solution_packages
                      (slug, title, description, category, vertical, version, author,
                       manifest, required_connectors, required_object_types, featured)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11)
                    ON CONFLICT (slug) DO UPDATE
                      SET title = EXCLUDED.title,
                          description = EXCLUDED.description,
                          category = EXCLUDED.category,
                          vertical = EXCLUDED.vertical,
                          version = EXCLUDED.version,
                          manifest = EXCLUDED.manifest,
                          required_connectors = EXCLUDED.required_connectors,
                          required_object_types = EXCLUDED.required_object_types,
                          featured = EXCLUDED.featured,
                          updated_at = NOW()
                    """,
                    s["slug"], s["title"], s["description"],
                    s.get("category"), s.get("vertical"),
                    s.get("version", "1.0.0"), s.get("author", "Princeps"),
                    json.dumps(s["manifest"]),
                    s.get("required_connectors") or [],
                    s.get("required_object_types") or [],
                    s.get("featured", False),
                )
            n += 1
    return n


_ALLOWED_VISIBILITY = {"public", "tenant", "private", "all"}


@router.get("/marketplace")
async def list_marketplace(
    category: str | None = Query(None),
    q: str | None = Query(None),
    featured_only: bool = Query(False),
    visibility: str = Query("public"),
    limit: int = Query(50, ge=1, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
):
    where = []
    params: list[Any] = []
    def _b(v):
        params.append(v); return f"${len(params)}"
    if category: where.append(f"category = {_b(category)}")
    if q: where.append(f"(title ILIKE '%' || {_b(q)} || '%' OR description ILIKE '%' || {_b(q)} || '%')")
    if featured_only: where.append("featured = TRUE")
    vis = (visibility or "public").lower()
    if vis not in _ALLOWED_VISIBILITY:
        raise HTTPException(400, f"visibility must be one of {sorted(_ALLOWED_VISIBILITY)}")
    if vis != "all":
        where.append(f"visibility = {_b(vis)}")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT * FROM solution_packages {where_sql}
        ORDER BY featured DESC, install_count DESC, created_at DESC
        LIMIT {int(limit)}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {
        "packages": [_row_to_dict(r) for r in rows],
        "count": len(rows),
        "categories": sorted({r["category"] for r in rows if r["category"]}),
    }


_ALLOWED_CATEGORIES = {"BESS", "Data Centre", "Ops", "Grid", "Risk", "Other"}
_ALLOWED_PUB_VISIBILITY = {"public", "tenant", "private"}
_SLUG_RX = re.compile(r"[^a-z0-9]+")


def _short_hash(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6]


@router.post("/publish")
async def publish_module(
    body: dict[str, Any] = Body(...),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Publish a saved workshop_modules row as an installable solution
    package. Looks up the module by slug, copies its manifest into a new
    `solution_packages` row, and tags it with author + visibility so it
    shows up alongside the built-in catalogue at /v2/solutions.

    The package slug is derived as `<module_slug>-pkg-<short_hash>` so a
    user can republish the same module multiple times (e.g. after edits)
    without colliding with prior versions.
    """
    module_slug = (body.get("module_slug") or "").strip()
    if not module_slug:
        raise HTTPException(422, "module_slug is required")

    description = (body.get("description") or "").strip()
    if not description:
        raise HTTPException(422, "description is required")

    category = (body.get("category") or "Other").strip()
    if category not in _ALLOWED_CATEGORIES:
        raise HTTPException(
            422,
            f"category must be one of {sorted(_ALLOWED_CATEGORIES)}",
        )

    visibility = (body.get("visibility") or "public").strip().lower()
    if visibility not in _ALLOWED_PUB_VISIBILITY:
        raise HTTPException(
            422,
            f"visibility must be one of {sorted(_ALLOWED_PUB_VISIBILITY)}",
        )

    version = (body.get("version") or "1.0.0").strip()
    published_by = (body.get("published_by") or "Anonymous").strip()
    explicit_title = (body.get("title") or "").strip()

    async with pool.acquire() as conn:
        mod = await conn.fetchrow(
            "SELECT id, slug, title, target_type, manifest "
            "FROM workshop_modules WHERE slug = $1",
            module_slug,
        )
        if not mod:
            raise HTTPException(404, f"module '{module_slug}' not found")

        manifest = (
            mod["manifest"]
            if isinstance(mod["manifest"], dict)
            else json.loads(mod["manifest"] or "{}")
        )
        title = explicit_title or mod["title"] or module_slug

        # Slug = <module_slug>-pkg-<6-char hash of (slug|title|published_by)>.
        # Collision-resistant enough for human republishing cadence; if a
        # collision somehow occurs we surface 409 from the unique index.
        seed = f"{module_slug}|{title}|{published_by}|{version}"
        hash_suffix = _short_hash(seed)
        # Sanitise just in case the upstream slug has something exotic.
        safe_base = _SLUG_RX.sub("-", module_slug.lower()).strip("-") or "module"
        pkg_slug = f"{safe_base}-pkg-{hash_suffix}"

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO solution_packages
                  (slug, title, description, category, vertical, version, author,
                   manifest, required_connectors, required_object_types, featured,
                   visibility, published_by, source_module_slug)
                VALUES ($1,$2,$3,$4,'all',$5,$6,$7::jsonb,
                        ARRAY[]::TEXT[], ARRAY[]::TEXT[], FALSE,
                        $8,$9,$10)
                RETURNING *
                """,
                pkg_slug, title, description, category,
                version, published_by,
                json.dumps(manifest),
                visibility, published_by, module_slug,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                409,
                f"package slug '{pkg_slug}' already exists — bump version to republish",
            )

    log.info(
        "published module %s as solution_packages.%s by %s",
        module_slug, pkg_slug, published_by,
    )
    return _row_to_dict(row)


@router.get("/{slug}")
async def get_package(
    slug: str,
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM solution_packages WHERE slug = $1", slug)
    if not row:
        raise HTTPException(404, f"package '{slug}' not found")
    return _row_to_dict(row)


@router.post("/{slug}/install")
async def install_package(
    slug: str,
    body: dict[str, Any] | None = Body(None),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Clone the package's manifest into workshop_modules under target_slug
    (defaults to '<slug>-<unix_ts>'). Bumps install_count for popularity."""
    target_slug = (body or {}).get("target_slug")
    installed_by = (body or {}).get("installed_by", "ui")

    async with pool.acquire() as conn:
        pkg = await conn.fetchrow("SELECT * FROM solution_packages WHERE slug = $1", slug)
        if not pkg:
            raise HTTPException(404, f"package '{slug}' not found")

        if not target_slug:
            from datetime import datetime, timezone
            target_slug = f"{pkg['slug']}-{int(datetime.now(timezone.utc).timestamp())}"

        manifest = pkg["manifest"] if isinstance(pkg["manifest"], dict) else json.loads(pkg["manifest"])
        # Stamp the slug on the manifest itself (so downstream consumers can identify it)
        manifest = dict(manifest)
        manifest["slug"] = target_slug
        manifest.setdefault("title", pkg["title"])

        try:
            mod_row = await conn.fetchrow(
                """
                INSERT INTO workshop_modules(slug, title, target_type, manifest)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (slug) DO UPDATE
                    SET title = EXCLUDED.title,
                        target_type = EXCLUDED.target_type,
                        manifest = EXCLUDED.manifest,
                        updated_at = NOW()
                RETURNING id, slug
                """,
                target_slug, pkg["title"], manifest.get("target_type"),
                json.dumps(manifest),
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"slug '{target_slug}' already taken")

        await conn.execute(
            """
            INSERT INTO solution_installs (package_id, module_slug, installed_by)
            VALUES ($1, $2, $3)
            """,
            pkg["package_id"], target_slug, installed_by,
        )
        await conn.execute(
            "UPDATE solution_packages SET install_count = install_count + 1 WHERE package_id = $1",
            pkg["package_id"],
        )

    return {
        "ok": True,
        "package_slug": slug,
        "module_slug": target_slug,
        "module_id": str(mod_row["id"]) if mod_row else None,
        "open_at": f"/v2/modules/{target_slug}",
    }


@router.get("/{slug}/installs")
async def list_installs(
    slug: str,
    limit: int = Query(50, ge=1, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        pkg = await conn.fetchrow("SELECT package_id FROM solution_packages WHERE slug = $1", slug)
        if not pkg:
            raise HTTPException(404, "not found")
        rows = await conn.fetch(
            """
            SELECT install_id, module_slug, installed_by, installed_at
            FROM solution_installs
            WHERE package_id = $1
            ORDER BY installed_at DESC LIMIT $2
            """,
            pkg["package_id"], limit,
        )
    return {
        "package_slug": slug,
        "installs": [
            {
                "install_id": str(r["install_id"]),
                "module_slug": r["module_slug"],
                "installed_by": r["installed_by"],
                "installed_at": r["installed_at"].isoformat(),
            } for r in rows
        ],
        "count": len(rows),
    }

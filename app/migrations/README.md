# app/migrations — Princeps numbered migrations

This directory holds **forward-only, numbered, idempotent** SQL migrations that
ship with the FastAPI backend and are applied automatically at startup.

It is distinct from the older `sql/` directory at the repo root (which holds
ad-hoc per-feature SQL migrations applied by individual `utils/*` modules).
New shared-schema work — in particular the Phase 7a Intelligence schema
(Alerts, Dockets, Data Subscriptions) — lives here.

## Conventions

1. **File naming:** `NNNN_short_slug.sql`, four-digit zero-padded sequence,
   no gaps. The numbering expresses dependency order.
2. **Idempotent only.** Every statement must be safe on the *nth* run:
   - `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`.
   - `CREATE EXTENSION IF NOT EXISTS`.
   - `ADD CONSTRAINT` wrapped in a `DO $$ … IF NOT EXISTS … END $$` guard.
   - Seed inserts wrapped in `ON CONFLICT DO NOTHING`.
3. **Forward only.** No down migrations. Rollbacks are handled by writing a
   new forward migration that undoes what is needed.
4. **No destructive DDL** (`DROP TABLE`, `DROP COLUMN`, backfills that
   require downtime) without explicit council sign-off and a separate,
   clearly numbered migration.
5. **Deferred FKs.** If table `B` has a FK back to table `A` but `A` also
   references `B` (or the tables were created in separate migrations),
   add the FK in a `DO $$ … pg_constraint … END $$` guard so re-runs are
   no-ops.

## Application mechanism

Migrations are applied by `app/db_setup.py` during FastAPI startup. The
pattern is:

```python
# inside setup_database(pool):
_mig_path = pathlib.Path(__file__).parent / "migrations" / "0001_intelligence_schema.sql"
_already_applied = await conn.fetchval(
    "SELECT to_regclass('public.documents') IS NOT NULL"
)
if not _already_applied and _mig_path.exists():
    await conn.execute(_mig_path.read_text())
```

The gate uses `to_regclass` on a marker table that the migration creates —
cheap (single catalog lookup) and correct even on a fresh database because
`to_regclass` returns NULL rather than raising. If the marker table is
already present we skip the file entirely; the DDL is still idempotent, so
re-running is safe but wasteful.

When adding a **new** migration, pick a new marker table (or a new column
on an existing marker) and extend `db_setup.py` to gate on that marker.
Do not bypass the gate just because every statement is `IF NOT EXISTS` —
the gate keeps startup fast and prevents churn on catalog locks.

## Why not Alembic / sqlalchemy-migrate / yoyo?

The existing codebase is raw `asyncpg` end-to-end (no SQLAlchemy ORM). An
ORM-driven migration framework would introduce a second way of talking to
the database just for DDL, which the council ruled out for Phase 7a. If
and when we adopt an ORM layer we can port these files into Alembic
without rewriting the DDL — the numbering scheme is already Alembic-compatible.

## Current migrations

| Seq  | File                                | What it ships                                                        |
| ---- | ----------------------------------- | -------------------------------------------------------------------- |
| 0001 | `0001_intelligence_schema.sql`      | Intelligence schema: Authorities, Dockets, Documents, Stakeholders, Stakeholder Submissions, Docket Timeline Events, Consultee Requirements, Alert Definitions/Subscriptions/Digests, Data Subscriptions, Data Subscription Rows, Document/Project pins, Docket pins/watches, Docket QA cache. |

## How to add a new migration

1. Create `NNNN_slug.sql` with strictly idempotent DDL.
2. Add a matching set of Pydantic models to `app/models/*.py`.
3. Extend `app/db_setup.py::setup_database` with a `to_regclass` gate on a
   new marker table introduced by your migration, and a call to apply it.
4. Run the backend locally; verify startup logs say
   `Applied 0001_intelligence_schema.sql` the first time and
   `0001_intelligence_schema.sql already applied — skipping` thereafter.
5. Confirm a second cold start is a no-op (no catalog churn, no errors).

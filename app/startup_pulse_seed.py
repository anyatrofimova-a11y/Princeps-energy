"""
startup_pulse_seed.py — one-shot Pulse seeder (P1 fix, COUNCIL-PLS audit).

On boot, populate `cluster_studies`, `cluster_dependencies`,
`portfolio_snapshots`, and `grid_events` so the Pulse workspace has
non-zero counters and a renderable cluster graph on a fresh DB.

All steps are idempotent (row-count guarded) and non-blocking: if one
step fails we log and continue with the next. Gated by the
``PULSE_SEED_ON_BOOT`` env var — default true in dev, set to "false"
(or anything falsy) in prod once the real ingestion pipeline is
wired up.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from random import Random

import asyncpg

from utils import cluster_graph, grid_events, portfolio_delta

log = logging.getLogger("princeps.pulse_seed")

# Row-count thresholds — seed only when the table is below these.
_CLUSTER_STUDIES_MIN = 3
_CLUSTER_DEPS_MIN = 1
_PORTFOLIO_SNAP_MIN_DATES = 2  # need two distinct snapshot dates for deltas
_GRID_EVENTS_MIN = 5


def _pulse_seed_enabled() -> bool:
    """Check ``PULSE_SEED_ON_BOOT``. Default true in dev (APP_ENV != 'production')."""
    raw = os.getenv("PULSE_SEED_ON_BOOT")
    if raw is None:
        # Default on in dev, off in prod.
        return os.getenv("APP_ENV", "dev").lower() not in ("prod", "production")
    return raw.strip().lower() in ("1", "true", "yes", "on")


async def run_pulse_seed(pool: asyncpg.Pool) -> dict:
    """Run the four Pulse seed steps in order, each guarded by row counts.

    Returns a summary dict suitable for logging: per-step ``ran``/``skipped``/
    ``error`` status plus any counts produced.
    """
    if not _pulse_seed_enabled():
        log.info("Pulse seed: PULSE_SEED_ON_BOOT disabled — skipping")
        return {"enabled": False}

    summary: dict = {"enabled": True, "steps": {}}

    # Ensure schemas exist before we touch them (cheap + idempotent).
    for name, ensure in (
        ("cluster_graph", cluster_graph.ensure_schema),
        ("grid_events", grid_events.ensure_schema),
        ("portfolio_delta", portfolio_delta.ensure_schema),
    ):
        try:
            await ensure(pool)
        except Exception as e:
            log.warning("Pulse seed: ensure_schema(%s) failed: %s", name, e)
            summary["steps"][f"ensure_{name}"] = {"error": str(e)}

    # Step 1 — cluster_graph.ingest_from_tec_register
    summary["steps"]["cluster_ingest"] = await _seed_cluster_ingest(pool)

    # Step 2 — cluster_graph.compute_dependencies
    summary["steps"]["cluster_dependencies"] = await _seed_cluster_dependencies(pool)

    # Step 3 — portfolio_delta.take_snapshot (today AND today-1)
    summary["steps"]["portfolio_snapshots"] = await _seed_portfolio_snapshots(pool)

    # Step 4 — grid_events.run_full_diff_cycle + synthetic top-up
    summary["steps"]["grid_events"] = await _seed_grid_events(pool)

    log.info("Pulse seed complete: %s", summary)
    return summary


# ────────────────────────────────────────────────────────────────────────
# Step 1 — cluster studies from TEC register
# ────────────────────────────────────────────────────────────────────────

async def _seed_cluster_ingest(pool: asyncpg.Pool) -> dict:
    try:
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT COUNT(*) FROM cluster_studies") or 0
        if n >= _CLUSTER_STUDIES_MIN:
            log.info("Pulse seed: cluster_studies has %d rows — skip ingest", n)
            return {"status": "skipped", "existing_rows": int(n)}

        result = await cluster_graph.ingest_from_tec_register(pool)

        # If the TEC register is present but all rows are unusable (no
        # tec_mw / no status), the helper returns studies_created=0
        # without hitting its own demo fallback (which only triggers on
        # tec_count==0). Promote to demo seeding so Pulse still has a
        # renderable graph on first boot.
        if int(result.get("studies_created", 0)) == 0:
            log.info("Pulse seed: TEC-derived studies empty — falling back to demo clusters")
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await cluster_graph._seed_demo_clusters(conn, result, dry_run=False)
            result["used_demo_data"] = True

        log.info("Pulse seed: cluster ingest -> %s", result)
        return {"status": "ran", **result}
    except Exception as e:
        log.warning("Pulse seed: cluster_ingest failed: %s", e)
        return {"status": "error", "error": str(e)}


# ────────────────────────────────────────────────────────────────────────
# Step 2 — dependency edges
# ────────────────────────────────────────────────────────────────────────

async def _seed_cluster_dependencies(pool: asyncpg.Pool) -> dict:
    try:
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT COUNT(*) FROM cluster_dependencies") or 0
        if n >= _CLUSTER_DEPS_MIN:
            log.info("Pulse seed: cluster_dependencies has %d rows — skip compute", n)
            return {"status": "skipped", "existing_rows": int(n)}

        rows = await cluster_graph.compute_dependencies(pool)
        log.info("Pulse seed: cluster_dependencies -> %d edges", rows)
        return {"status": "ran", "rows_inserted": int(rows)}
    except Exception as e:
        log.warning("Pulse seed: cluster_dependencies failed: %s", e)
        return {"status": "error", "error": str(e)}


# ────────────────────────────────────────────────────────────────────────
# Step 3 — two portfolio snapshots (today, today-1) so deltas have a pair
# ────────────────────────────────────────────────────────────────────────

async def _seed_portfolio_snapshots(pool: asyncpg.Pool) -> dict:
    try:
        async with pool.acquire() as conn:
            distinct_dates = await conn.fetchval(
                "SELECT COUNT(DISTINCT taken_at) FROM portfolio_snapshots"
            ) or 0
        if distinct_dates >= _PORTFOLIO_SNAP_MIN_DATES:
            log.info(
                "Pulse seed: portfolio_snapshots already has %d distinct dates — skip",
                distinct_dates,
            )
            return {"status": "skipped", "existing_dates": int(distinct_dates)}

        today = date.today()
        yesterday = today - timedelta(days=1)

        n_yesterday = await portfolio_delta.take_snapshot(pool, taken_at=yesterday)
        n_today = await portfolio_delta.take_snapshot(pool, taken_at=today)

        # With no real day-over-day changes yet, both snapshots carry
        # identical metrics → compute_deltas() returns []. Apply a small
        # deterministic perturbation to a sample of yesterday's rows so
        # Pulse's Portfolio Deltas strip has something to render. Safe
        # because the seed only runs when distinct_dates < 2.
        perturbed = await _perturb_yesterday_snapshot(pool, yesterday)

        log.info(
            "Pulse seed: portfolio snapshots -> %d yesterday / %d today / perturbed %d",
            n_yesterday, n_today, perturbed,
        )
        return {
            "status": "ran",
            "snapshots_yesterday": int(n_yesterday),
            "snapshots_today": int(n_today),
            "perturbed_rows": int(perturbed),
        }
    except Exception as e:
        log.warning("Pulse seed: portfolio_snapshots failed: %s", e)
        return {"status": "error", "error": str(e)}


async def _perturb_yesterday_snapshot(pool: asyncpg.Pool, taken_at: date) -> int:
    """Inject small deterministic score / capacity changes into a sample
    of yesterday's snapshot rows so the deltas endpoint returns non-zero
    day-over-day movement on a fresh DB. Deterministic (seeded from the
    date ordinal) so repeat seeds land on the same rows.
    """
    import json as _json

    rng = Random(taken_at.toordinal() ^ 0x51F3)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT project_id, metrics FROM portfolio_snapshots WHERE taken_at = $1",
            taken_at,
        )
        if not rows:
            return 0
        sample = rng.sample(list(rows), k=min(200, len(rows)))
        updated = 0
        for r in sample:
            pid = r["project_id"]
            raw = r["metrics"]
            if isinstance(raw, str):
                try:
                    m = _json.loads(raw) or {}
                except Exception:
                    m = {}
            elif isinstance(raw, dict):
                m = dict(raw)
            else:
                m = {}

            # Shift score by -3..+3; nudge capacity by up to 2%.
            if m.get("score") is not None:
                try:
                    m["score"] = round(float(m["score"]) + rng.uniform(-3, 3), 2)
                except Exception:
                    pass
            if m.get("capacity_mw") is not None:
                try:
                    m["capacity_mw"] = round(
                        float(m["capacity_mw"]) * rng.uniform(0.98, 1.02), 3
                    )
                except Exception:
                    pass
            # If the project has no score yet, pick a baseline so the
            # delta vs today (which will get its real / default score)
            # still registers.
            if m.get("score") is None:
                m["score"] = round(rng.uniform(55, 85), 2)

            await conn.execute(
                "UPDATE portfolio_snapshots SET metrics = $1::jsonb "
                "WHERE taken_at = $2 AND project_id = $3",
                _json.dumps(m), taken_at, pid,
            )
            updated += 1
    return updated


# ────────────────────────────────────────────────────────────────────────
# Step 4 — grid_events seed
# ────────────────────────────────────────────────────────────────────────

# A small pool of plausible seed events so Pulse's Critical-24h /
# Events-24h tiles are non-zero on a fresh DB.
_SEED_EVENTS: list[dict] = [
    {
        "event_type": "headroom_change",
        "severity": "warn",
        "substation_id": "BRAMFORD_400",
        "payload": {
            "summary": "Bramford 400 kV headroom dropped 8 MW overnight",
            "old_headroom_mw": 214.0,
            "new_headroom_mw": 206.0,
            "delta_mw": -8.0,
        },
        "source": "pulse_seed",
    },
    {
        "event_type": "restudy",
        "severity": "warn",
        "project_id": "DEMO-QUEUE-ACTIVE",
        "payload": {
            "summary": "TEC register re-study triggered by upstream withdrawal",
            "old_status": "Accepted",
            "new_status": "Under Review",
        },
        "source": "pulse_seed",
    },
    {
        "event_type": "withdrawal",
        "severity": "critical",
        "project_id": "DEMO-QUEUE-WITHDRAWN",
        "payload": {
            "summary": "900 MW project withdrawn — cluster re-pricing in flight",
            "capacity_mw": 900.0,
        },
        "source": "pulse_seed",
    },
    {
        "event_type": "new_offer",
        "severity": "info",
        "project_id": "DEMO-OFFER-NEW",
        "payload": {
            "summary": "New TEC offer: Accepted, 50 MW",
            "capacity_mw": 50.0,
        },
        "source": "pulse_seed",
    },
    {
        "event_type": "cost_reallocation",
        "severity": "warn",
        "project_id": "DEMO-SIBLING-A",
        "payload": {
            "summary": "Sibling repriced after cluster withdrawal",
            "delta_gbp": 1_250_000,
        },
        "source": "pulse_seed",
    },
    {
        "event_type": "substation_headroom_change",
        "severity": "info",
        "substation_id": "SUNDON_275",
        "payload": {
            "summary": "Sundon 275 kV headroom up 3.4 MW",
            "old_headroom_mw": 71.2,
            "new_headroom_mw": 74.6,
            "delta_mw": 3.4,
        },
        "source": "pulse_seed",
    },
    {
        "event_type": "curtailment_alert",
        "severity": "warn",
        "payload": {
            "summary": "B6 boundary curtailment risk 18% on forecast",
            "boundary": "B6",
            "curtailment_pct": 18.0,
        },
        "source": "pulse_seed",
    },
]


async def _seed_grid_events(pool: asyncpg.Pool) -> dict:
    try:
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT COUNT(*) FROM grid_events") or 0
        if n >= _GRID_EVENTS_MIN:
            log.info("Pulse seed: grid_events has %d rows — skip seed", n)
            return {"status": "skipped", "existing_rows": int(n)}

        # First, try a real diff cycle against the live snapshot.
        diff_summary: dict = {}
        try:
            diff_summary = await grid_events.run_full_diff_cycle(pool)
        except Exception as e:
            log.info("Pulse seed: diff cycle produced nothing (%s) — using synthetic", e)

        new_events = int(diff_summary.get("new_events", 0))
        # If the diff cycle didn't produce enough, top up with synthetic
        # seed events so Pulse KPIs show > 0.
        if new_events < _GRID_EVENTS_MIN:
            # Shuffle so the sample feels organic across restarts.
            rng = Random(today_salt())
            pool_events = list(_SEED_EVENTS)
            rng.shuffle(pool_events)
            ids = await grid_events.emit_events_batch(pool, pool_events)
            log.info(
                "Pulse seed: synthetic top-up -> %d grid_events (diff cycle produced %d)",
                len(ids), new_events,
            )
            return {
                "status": "ran",
                "diff_cycle_events": new_events,
                "synthetic_events": len(ids),
            }

        return {
            "status": "ran",
            "diff_cycle_events": new_events,
            "synthetic_events": 0,
        }
    except Exception as e:
        log.warning("Pulse seed: grid_events failed: %s", e)
        return {"status": "error", "error": str(e)}


def today_salt() -> int:
    """Deterministic-ish seed per day so the synthetic events don't reshuffle
    every single restart within the same day. Keeps retries idempotent-ish."""
    return date.today().toordinal()

"""
app/ingestion/neso_tec.py — monthly NESO Transmission Entry Capacity scrape.

The TEC register is a monthly snapshot of every project queuing for a
transmission connection in GB. NESO publishes it via their CKAN-style
data portal at:

    https://www.neso.energy/data-portal/transmission-entry-capacity-tec-register

On each run we:
  1. Resolve the CKAN ``package_show`` → the latest CSV resource URL.
  2. Download the CSV and parse per-project rows.
  3. Diff vs the previous month (stored in ``data_subscription_rows``):
     - new entries
     - withdrawals (rows present last month, absent this month)
     - MW changes
  4. Create a synthetic docket per-monthly cohort (case_type='misc',
     ``source_docket_id='neso-tec-YYYYMM'``) and a ``documents`` row per
     notable event (new entry / withdrawal / MW delta).
  5. Geocode each POC substation by joining to ``grid_substations`` on
     name (ILIKE first, then trigram fallback) to produce a Point
     geometry for each docket / document.

Schedule: daily at 00:30 UTC — register updates are monthly but polling
daily catches re-publications and lets us alert the same day.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.ingestion.base import IngestionWorker, RawItem, stable_source_url

log = logging.getLogger("princeps.ingestion.neso_tec")


_CKAN_BASE = "https://api.neso.energy/api/3/action"
_TEC_PACKAGE = "transmission-entry-capacity-tec-register"

# CKAN resource URLs change; fall back to the two historically known direct
# URLs if package_show fails.
_FALLBACK_CSV_URLS = [
    "https://www.neso.energy/document/319486/download",   # 2024-2025 cohort
    "https://www.neso.energy/document/264896/download",   # older cohort
]


class NesoTecWorker(IngestionWorker):
    """Fetch NESO TEC register, diff vs last run, materialise docket / docs."""

    SOURCE = "neso_tec"
    req_per_sec = 0.5

    async def fetch(self, client: httpx.AsyncClient) -> dict[str, Any]:
        csv_text, resource_url = await self._resolve_and_download(client)
        if not csv_text:
            return {"rows": [], "resource_url": None}

        rows = _parse_csv(csv_text)
        return {"rows": rows, "resource_url": resource_url}

    async def parse(self, fetched: dict[str, Any]) -> list[RawItem]:
        rows: list[dict[str, Any]] = fetched.get("rows") or []
        resource_url: str | None = fetched.get("resource_url")
        if not rows:
            log.info("neso_tec: no rows — skipping diff stage")
            return []

        # ── Diff vs last snapshot stored in data_subscription_rows ──────────
        async with self.pool.acquire() as conn:
            sub_id = await self._ensure_subscription(conn)
            prev = await conn.fetch(
                """SELECT external_id, row
                     FROM data_subscription_rows
                    WHERE subscription_id = $1
                      AND removed_at IS NULL""",
                sub_id,
            )
            prev_by_id = {r["external_id"]: json.loads(r["row"]) if isinstance(r["row"], str) else r["row"]
                          for r in prev}
            current_by_id = {r["external_id"]: r for r in rows if r.get("external_id")}

            new_ids = set(current_by_id) - set(prev_by_id)
            removed_ids = set(prev_by_id) - set(current_by_id)
            mw_changed: list[dict[str, Any]] = []
            for eid, cur in current_by_id.items():
                p = prev_by_id.get(eid)
                if not p:
                    continue
                old_mw = _as_float(p.get("contracted_mw"))
                new_mw = _as_float(cur.get("contracted_mw"))
                if old_mw is not None and new_mw is not None and abs(old_mw - new_mw) > 0.5:
                    mw_changed.append({"external_id": eid, "old_mw": old_mw, "new_mw": new_mw, "row": cur})

            # ── Synthetic docket per monthly cohort ──────────────────────────
            cohort = _current_cohort()
            docket_id = await self._upsert_monthly_docket(
                conn, cohort=cohort,
                total_rows=len(rows),
                new_count=len(new_ids),
                withdrawn_count=len(removed_ids),
                mw_changed_count=len(mw_changed),
                resource_url=resource_url,
            )

            # ── Write current snapshot rows to data_subscription_rows ───────
            await self._refresh_subscription_rows(conn, sub_id, current_by_id, removed_ids)

            # ── Geocode helper lookup — substation name → (lat, lon) ─────────
            substation_geocodes = await _preload_substation_names(conn)

            items: list[RawItem] = []
            # 1. New-entry documents
            for eid in new_ids:
                row = current_by_id[eid]
                items.append(_row_to_doc(
                    row, event_type="new_entry", docket_id=str(docket_id),
                    cohort=cohort, geocodes=substation_geocodes,
                    resource_url=resource_url,
                ))
            # 2. Withdrawal documents
            for eid in removed_ids:
                row = prev_by_id[eid]
                if not isinstance(row, dict):
                    continue
                row = {**row, "external_id": eid}
                items.append(_row_to_doc(
                    row, event_type="withdrawal", docket_id=str(docket_id),
                    cohort=cohort, geocodes=substation_geocodes,
                    resource_url=resource_url,
                ))
            # 3. MW change documents
            for change in mw_changed:
                row = {
                    **change["row"],
                    "old_mw": change["old_mw"],
                    "new_mw": change["new_mw"],
                    "mw_delta": change["new_mw"] - change["old_mw"],
                }
                items.append(_row_to_doc(
                    row, event_type="mw_change", docket_id=str(docket_id),
                    cohort=cohort, geocodes=substation_geocodes,
                    resource_url=resource_url,
                ))
        return items

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _resolve_and_download(
        self, client: httpx.AsyncClient,
    ) -> tuple[str | None, str | None]:
        # Try CKAN package_show first.
        try:
            r = await client.get(
                f"{_CKAN_BASE}/package_show", params={"id": _TEC_PACKAGE},
            )
            if r.status_code == 200:
                data = r.json().get("result") or {}
                resources = data.get("resources") or []
                csv_res = next(
                    (x for x in resources
                     if (x.get("format") or "").lower() == "csv"),
                    None,
                )
                if csv_res and csv_res.get("url"):
                    url = csv_res["url"]
                    r2 = await client.get(url)
                    if r2.status_code == 200:
                        return r2.text, url
        except Exception as e:
            log.warning("neso_tec: CKAN resolve failed: %s", e)

        # Fallback to known direct-download URLs.
        for url in _FALLBACK_CSV_URLS:
            try:
                r = await client.get(url)
                if r.status_code == 200 and r.text.lower().startswith(("project", "customer", "\ufeff")):
                    return r.text, url
            except Exception:
                continue
        return None, None

    async def _ensure_subscription(self, conn) -> Any:
        row = await conn.fetchrow(
            """INSERT INTO data_subscriptions (slug, title, description,
                                               refresh_interval_hours, is_public, price_tier)
                 VALUES ('neso-tec-register', 'NESO Transmission Entry Capacity Register',
                         'Monthly diff of the GB transmission connection queue.',
                         24, true, 'free')
               ON CONFLICT (slug) DO UPDATE SET updated_at = now()
           RETURNING id""",
        )
        return row["id"]

    async def _refresh_subscription_rows(
        self, conn, sub_id: Any,
        current_by_id: dict[str, dict[str, Any]],
        removed_ids: set[str],
    ) -> None:
        # Mark removed rows
        for eid in removed_ids:
            await conn.execute(
                """UPDATE data_subscription_rows
                      SET removed_at = now()
                    WHERE subscription_id = $1 AND external_id = $2 AND removed_at IS NULL""",
                sub_id, eid,
            )
        # Upsert current rows
        for eid, row in current_by_id.items():
            await conn.execute(
                """INSERT INTO data_subscription_rows
                       (subscription_id, external_id, row, removed_at)
                   VALUES ($1, $2, $3::jsonb, NULL)
                   ON CONFLICT (subscription_id, external_id)
                   DO UPDATE SET row = EXCLUDED.row, removed_at = NULL""",
                sub_id, eid, json.dumps(row, default=str),
            )

    async def _upsert_monthly_docket(
        self, conn, *, cohort: str,
        total_rows: int, new_count: int, withdrawn_count: int,
        mw_changed_count: int, resource_url: str | None,
    ) -> Any:
        title = f"NESO TEC Register — {cohort}"
        desc = (
            f"Monthly snapshot: {total_rows} rows, +{new_count} new, "
            f"-{withdrawn_count} withdrawn, {mw_changed_count} MW changes."
        )
        row = await conn.fetchrow(
            """INSERT INTO dockets
                   (source, source_docket_id, title, description, case_type,
                    industry, status, opened_at)
               VALUES ($1, $2, $3, $4, 'misc', 'electricity', 'open', now())
               ON CONFLICT (source, source_docket_id) DO UPDATE
                 SET title = EXCLUDED.title,
                     description = EXCLUDED.description,
                     updated_at = now()
               RETURNING docket_id""",
            self.SOURCE, f"neso-tec-{cohort}", title, desc,
        )
        return row["docket_id"]


# ── Row-level parsing ────────────────────────────────────────────────────────

# NESO publishes the TEC register with column names that drift year-to-year.
# We try each alias in order and take the first non-empty.

_COL_ALIASES = {
    "project_name":     ["Project Name", "project_name", "ProjectName", "Customer Name"],
    "customer_name":    ["Customer Name", "Applicant", "customer_name", "Developer"],
    "external_id":      ["TEC Ref", "Project Reference", "Ref", "Connection Ref",
                         "Connection Reference", "Project ID"],
    "poc_substation":   ["Connection Site", "Connection Point", "Connection Location",
                         "Site", "Substation", "poc_substation"],
    "contracted_mw":    ["MW Connected", "MW", "Contracted Capacity (MW)",
                         "Capacity (MW)", "MW Contracted", "Capacity MW"],
    "connection_date":  ["Connection Date", "Expected Connection Date",
                         "Estimated Connection Date"],
    "technology":       ["Plant Type", "Technology Type", "Fuel Type", "Technology"],
    "status":           ["Status", "Connection Status"],
    "host_to":          ["Host TO", "TO", "Transmission Owner"],
}


def _parse_csv(text: str) -> list[dict[str, Any]]:
    """Parse the TEC register CSV into canonical dicts."""
    # Strip BOM
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for raw in reader:
        canon: dict[str, Any] = {}
        for key, aliases in _COL_ALIASES.items():
            val = None
            for a in aliases:
                if a in raw and raw[a] is not None:
                    v = str(raw[a]).strip()
                    if v:
                        val = v
                        break
            if val is not None:
                canon[key] = val

        if not canon.get("project_name") and not canon.get("customer_name"):
            continue
        # Derive a stable external_id if the CSV didn't provide one
        if not canon.get("external_id"):
            base = (canon.get("project_name") or canon.get("customer_name") or "").strip()
            canon["external_id"] = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-")[:80]
        rows.append(canon)
    return rows


def _row_to_doc(
    row: dict[str, Any], *, event_type: str,
    docket_id: str, cohort: str,
    geocodes: dict[str, tuple[float, float]],
    resource_url: str | None,
) -> RawItem:
    """Build a RawItem describing a single diff event."""
    name = row.get("project_name") or row.get("customer_name") or row.get("external_id")
    cap_mw = _as_float(row.get("contracted_mw"))
    poc = row.get("poc_substation") or ""
    title_bits = [f"TEC {event_type.replace('_', ' ')}", str(name)]
    if cap_mw:
        title_bits.append(f"{cap_mw:g} MW")
    if poc:
        title_bits.append(f"POC: {poc}")
    title = " — ".join(title_bits)

    body_lines = [f"Event: {event_type}", f"Monthly cohort: {cohort}"]
    for k, v in row.items():
        body_lines.append(f"{k}: {v}")
    body = "\n".join(body_lines)

    lat, lon = None, None
    if poc:
        hit = geocodes.get(_norm_sub(poc))
        if hit:
            lat, lon = hit

    source_key = f"{cohort}/{row.get('external_id')}/{event_type}"
    source_url = stable_source_url("neso_tec", source_key)

    return RawItem(
        source_url=source_url,
        title=title[:500],
        body_text=body,
        published_at=datetime.now(timezone.utc),
        filing_type=event_type,
        procedural_stage=None,
        commission_authority="neso",
        pages=None,
        body_pdf_path=resource_url,
        lat=lat,
        lon=lon,
        docket_id=docket_id,
        raw={
            "event_type": event_type,
            "cohort": cohort,
            **{k: v for k, v in row.items() if v is not None},
        },
    )


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("MW", "").strip())
    except (ValueError, TypeError):
        return None


def _current_cohort() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def _norm_sub(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


async def _preload_substation_names(conn) -> dict[str, tuple[float, float]]:
    """
    Map (lowercased, space-collapsed) substation name → (lat, lon).

    Uses the existing ``grid_substations`` table (stored in BNG/SRID 27700
    per the codebase convention); we ``ST_Transform`` to WGS84 for the
    documents.geometry Point.
    """
    out: dict[str, tuple[float, float]] = {}
    try:
        rows = await conn.fetch(
            """SELECT name,
                      ST_Y(ST_Transform(geom, 4326)) AS lat,
                      ST_X(ST_Transform(geom, 4326)) AS lon
                 FROM grid_substations
                WHERE geom IS NOT NULL"""
        )
    except Exception as e:
        log.info("neso_tec: grid_substations lookup failed (non-fatal): %s", e)
        return out
    for r in rows:
        if r["name"] and r["lat"] is not None and r["lon"] is not None:
            out[_norm_sub(r["name"])] = (float(r["lat"]), float(r["lon"]))
    return out


async def run_once(pool):
    """Convenience entry point for APScheduler + manual CLI invocation."""
    worker = NesoTecWorker(pool)
    return await worker.run()

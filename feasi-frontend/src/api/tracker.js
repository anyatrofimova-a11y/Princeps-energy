/**
 * Substation Tracker — fetch layer.
 *
 *   Backend router is live at /api/tracker/*. When VITE_MOCK_TRACKER=true
 *   (default while the frontend is iterating ahead of the backend) the
 *   module falls back to src/data/mock-tracker.json so the dashboard
 *   renders end-to-end without the server.
 *
 *   Mirrors the alerts.js / dockets.js pattern: relative paths, standard
 *   JSON, thin helpers. Do not add caching here — leave it to the hook
 *   layer so stale invalidation is explicit.
 */

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const delay = async () => sleep(60 + Math.random() * 80);

// ── helpers ─────────────────────────────────────────────────────
function applyFilters(rows, f = {}) {
  let out = [...rows];
  if (f.region) out = out.filter((r) => r.region === f.region);
  if (f.status) out = out.filter((r) => r.construction_status === f.status);
  if (f.developer) out = out.filter((r) => r.developer === f.developer);
  if (f.voltage_band) {
    out = out.filter((r) => {
      const v = r.voltage_kv_primary || 0;
      if (f.voltage_band === "ehv_400") return v >= 400;
      if (f.voltage_band === "hv_275") return v >= 200 && v < 400;
      if (f.voltage_band === "hv_132") return v >= 100 && v < 200;
      if (f.voltage_band === "mv_33") return v >= 20 && v < 100;
      if (f.voltage_band === "lv_11") return v < 20;
      return true;
    });
  }
  if (f.year_min != null) {
    out = out.filter((r) => (r.operation_year ?? r.construction_year ?? 9999) >= f.year_min);
  }
  if (f.year_max != null) {
    out = out.filter((r) => (r.operation_year ?? r.construction_year ?? 0) <= f.year_max);
  }
  if (f.confidence_lt != null) out = out.filter((r) => (r.confidence ?? 0) < f.confidence_lt);
  if (f.confidence_gte != null) out = out.filter((r) => (r.confidence ?? 0) >= f.confidence_gte);
  if (f.sme_reviewed != null) out = out.filter((r) => !!r.sme_reviewed === !!f.sme_reviewed);
  if (f.q) {
    const q = String(f.q).toLowerCase();
    out = out.filter((r) =>
      [r.substation_name, r.parent_project, r.project_description, r.developer, r.county]
        .filter(Boolean)
        .some((s) => s.toLowerCase().includes(q))
    );
  }
  if (f.sort) {
    const [key, dirRaw] = String(f.sort).split(":");
    const dir = dirRaw === "desc" ? -1 : 1;
    out.sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }
  return out;
}

// ── List (paginated) ────────────────────────────────────────────
export async function listSubstations(filters = {}) {
  const limit = filters.limit ?? 100;
  const cursor = Number(filters.cursor ?? 0);
    const qs = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v != null && v !== "") qs.set(k, String(v));
  });
  const r = await fetch(`/api/tracker/substations?${qs.toString()}`);
  if (!r.ok) throw new Error(`list ${r.status}`);
  return r.json();
}

// ── Detail ──────────────────────────────────────────────────────
export async function getSubstation(id) {
    const r = await fetch(`/api/tracker/substations/${encodeURIComponent(id)}`);
  if (!r.ok) throw new Error(`detail ${r.status}`);
  return r.json();
}

// ── GeoJSON for map ─────────────────────────────────────────────
export async function getGeoJSON() {
    const r = await fetch("/api/tracker/substations/geojson");
  if (!r.ok) throw new Error(`geojson ${r.status}`);
  return r.json();
}

// ── Stats ───────────────────────────────────────────────────────
export async function getStats() {
    const r = await fetch("/api/tracker/stats");
  if (!r.ok) throw new Error(`stats ${r.status}`);
  return r.json();
}

// ── Refresh (admin trigger) ─────────────────────────────────────
export async function triggerRefresh() {
    const r = await fetch("/api/tracker/refresh", { method: "POST" });
  if (!r.ok) throw new Error(`refresh ${r.status}`);
  return r.json();
}

// ── Downloads (CSV / GeoJSON / Parquet) ─────────────────────────
function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export async function downloadCSV() {
    const r = await fetch("/api/tracker/substations.csv");
  if (!r.ok) throw new Error(`csv ${r.status}`);
  const blob = await r.blob();
  triggerDownload(blob, "tracker-substations.csv");
  return { ok: true };
}

export async function downloadGeoJSON() {
  const gj = await getGeoJSON();
  triggerDownload(
    new Blob([JSON.stringify(gj, null, 2)], { type: "application/geo+json" }),
    "tracker-substations.geojson"
  );
  return { ok: true };
}

export async function downloadParquet() {
  // Parquet export isn't wired on the backend side yet. Stub: warn + fall back to CSV.
    const r = await fetch("/api/tracker/substations.parquet");
  if (!r.ok) throw new Error(`parquet ${r.status}`);
  const blob = await r.blob();
  triggerDownload(blob, "tracker-substations.parquet");
  return { ok: true };
}

// ── Edit (PATCH) — backend endpoint TBC ─────────────────────────
// TODO: wire to PATCH /api/tracker/substations/{id} once the backend route lands.
export async function updateSubstation(id, patch) {
    const r = await fetch(`/api/tracker/substations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`update ${r.status}`);
  return r.json();
}

// ── Review queue actions ────────────────────────────────────────
export async function approveSubstation(id, reviewer = "current-user") {
  return updateSubstation(id, { sme_reviewed: true, sme_reviewer: reviewer });
}

export async function rejectSubstation(id, reviewer = "current-user") {
  return updateSubstation(id, { sme_reviewed: true, sme_reviewer: reviewer, rejected: true });
}

export async function batchApprove(ids, reviewer = "current-user") {
  const results = [];
  for (const id of ids) {
    try {
      results.push(await approveSubstation(id, reviewer));
    } catch (e) {
      results.push({ ok: false, id, error: e.message });
    }
  }
  return { ok: true, results };
}

export const MOCK_MODE = false;

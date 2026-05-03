/**
 * Grid Connection API helper. Live-only as of 2026-04-29.
 *
 * Backend (app/routers/grid.py):
 *   POST /api/grid/assess              → Tier 1 ranked POCs
 *   POST /api/grid/power-flow          → Tier 2 pandapower sim
 *   GET  /api/grid/capacity-map        → GeoJSON of substations w/ headroom
 *   GET  /api/grid/substation/{id}/detail
 *   POST /api/grid/connection-forecast → timeline + cost
 *
 * Live-shape adapter normalises into the contract GridConnectionPanel
 * expects so the rendering code stays untouched.
 */

const API_BASE = import.meta.env.VITE_API_BASE || "";

export async function getGridConnection(projectId, opts = {}) {
  const { lat, lon, capacity_mw, technology = "dc" } = opts;
  const params = new URLSearchParams({
    lat: lat ?? 51.5239,
    lon: lon ?? -0.6269,
    capacity_mw: capacity_mw ?? 65,
    technology,
  });
  const [assessRes, forecastRes] = await Promise.all([
    fetch(`${API_BASE}/api/grid/assess?${params}`, { method: "POST" }),
    fetch(`${API_BASE}/api/grid/connection-forecast?${params}`, { method: "POST" })
      .catch(() => null),
  ]);
  if (!assessRes.ok) throw new Error(`Grid assess HTTP ${assessRes.status}`);
  const assess = await assessRes.json();
  const forecast = forecastRes?.ok ? await forecastRes.json() : null;
  return normaliseLive(assess, forecast, { lat, lon, capacity_mw, technology, projectId });
}

export async function runTier2PowerFlow(projectId, opts = {}) {
  const { lat, lon, capacity_mw, technology = "dc", substation_id } = opts;
  const params = new URLSearchParams({
    lat: lat ?? 51.5239,
    lon: lon ?? -0.6269,
    capacity_mw: capacity_mw ?? 65,
    technology,
    contingency: "true",
  });
  if (substation_id != null) params.set("substation_id", substation_id);
  const res = await fetch(`${API_BASE}/api/grid/power-flow?${params}`, { method: "POST" });
  if (!res.ok) throw new Error(`Power flow HTTP ${res.status}`);
  return await res.json();
}

export async function getCapacityMap({ bbox } = {}) {
  const params = new URLSearchParams();
  if (bbox && bbox.length === 4) {
    params.set("west", bbox[0]); params.set("south", bbox[1]);
    params.set("east", bbox[2]); params.set("north", bbox[3]);
  }
  const qs = params.toString();
  const res = await fetch(`${API_BASE}/api/grid/capacity-map${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`Capacity map HTTP ${res.status}`);
  return await res.json();
}

/* ── Live → panel-shape adapter ────────────────────────────────────────── */
function normaliseLive(assess, forecast, opts) {
  const candidates = assess?.candidates || [];
  const best = candidates[0];
  const cost = assess?.cost_estimate?.cost_gbp || {};

  return {
    project_meta: {
      project_id: opts.projectId,
      lat: opts.lat,
      lon: opts.lon,
      target_capacity_mw: opts.capacity_mw,
    },
    at_a_glance: {
      poc_substation: best?.name || "—",
      dno: best?.dno || assess?.dno_area?.name || "—",
      voltage_kv: best?.voltage_kv || 0,
      distance_km: best?.distance_km || 0,
      firm_headroom_mw: best?.gen_headroom_mw || 0,
      non_firm_headroom_mw: best?.gen_headroom_mw
        ? Math.round(best.gen_headroom_mw * 1.9) : 0,
      queue_depth: best?.queue?.ecr_queued || 0,
      queue_mw: best?.queue?.ecr_queued_mw || 0,
      est_cost_p50_gbp_m: cost.p50 ? cost.p50 / 1e6 : null,
      commissioning_months: forecast?.timeline_months_p50 || null,
      verdict: assess?.verdict || "CAUTION",
      verdict_reason: assess?.summary || "",
    },
    poc_options: candidates.slice(0, 5).map((c, i) => ({
      id: c.id,
      name: c.name,
      dno: c.dno,
      voltage_kv: c.voltage_kv,
      distance_km: c.distance_km,
      firm_mw: c.gen_headroom_mw,
      non_firm_mw: c.gen_headroom_mw != null
        ? Math.round(c.gen_headroom_mw * 1.9) : null,
      firm_post_reinforcement_mw: null,
      reinforcement_date: null,
      queue_depth: c.queue?.ecr_queued || 0,
      queue_mw: c.queue?.ecr_queued_mw || 0,
      est_cost_p10_gbp_m: cost.p10 ? cost.p10 / 1e6 : null,
      est_cost_p50_gbp_m: cost.p50 ? cost.p50 / 1e6 : null,
      est_cost_p90_gbp_m: cost.p90 ? cost.p90 / 1e6 : null,
      commissioning_months: forecast?.timeline_months_p50 || null,
      rag: c.rag_generation || "amber",
      preferred: i === 0,
      notes: (c.notes || []).join(" · "),
    })),
    capacity_map_features: candidates.map((c) => ({
      id: c.id, name: c.name, lat: c.lat, lon: c.lon,
      voltage_kv: c.voltage_kv, firm_mw: c.gen_headroom_mw,
      rag: c.rag_generation || "amber",
    })),
    cost_breakdown: assess?.cost_estimate?.breakdown
      ? {
          total_p50_gbp_m: cost.p50 ? cost.p50 / 1e6 : 0,
          components: Object.entries(assess.cost_estimate.breakdown).map(([k, v]) => ({
            key: k, label: k.replace(/_/g, " "),
            gbp_m: v / 1e6,
            share: cost.p50 ? v / cost.p50 : 0,
          })),
        }
      : null,
    timeline_gantt: forecast?.gantt || null,
    compliance: null,
    power_chain: null,
    _provenance: assess?.data_provenance || "live_backend",
  };
}

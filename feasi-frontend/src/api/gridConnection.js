/**
 * Grid Connection API helper.
 *
 * When VITE_MOCK_GRID !== "false" (default ON for dev without backend),
 * returns a realistic Slough-DC fixture. Otherwise calls the live backend:
 *   POST /api/grid/assess              → Tier 1 ranked POCs
 *   POST /api/grid/power-flow          → Tier 2 pandapower sim
 *   GET  /api/grid/capacity-map        → GeoJSON of substations w/ headroom
 *   GET  /api/grid/substation/{id}/detail
 *   POST /api/grid/connection-forecast → timeline + cost
 *
 * All live shapes are passed through the mock-compatible normaliser so
 * GridConnectionPanel rendering is identical regardless of source.
 */
import mock from "../data/mock-grid-connection.json";

const USE_MOCK = (import.meta.env.VITE_MOCK_GRID ?? "true") !== "false";
const API_BASE = import.meta.env.VITE_API_BASE || "";

function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

function pickFixture(projectId) {
  // Any known DC project id falls back to the default Slough fixture.
  return mock[projectId] || mock.default;
}

/** One payload with every Grid-Connection view needs. */
export async function getGridConnection(projectId, opts = {}) {
  const { lat, lon, capacity_mw, technology = "dc" } = opts;

  if (USE_MOCK) {
    await wait(160);
    return pickFixture(projectId);
  }

  const params = new URLSearchParams({
    // Slough Trading Estate (Bath Rd / Buckingham Ave) — default demo pin.
    lat: lat ?? 51.5260,
    lon: lon ?? -0.6155,
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

  return normaliseLive(assess, forecast, { lat, lon, capacity_mw, technology });
}

export async function runTier2PowerFlow(projectId, opts = {}) {
  const { lat, lon, capacity_mw, technology = "dc", substation_id } = opts;

  if (USE_MOCK) {
    await wait(420); // feel of a real pandapower call
    return pickFixture(projectId).power_flow_stub;
  }

  const params = new URLSearchParams({
    // Slough Trading Estate (Bath Rd / Buckingham Ave) — default demo pin.
    lat: lat ?? 51.5260,
    lon: lon ?? -0.6155,
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
  if (USE_MOCK) {
    await wait(80);
    const features = mock.default.capacity_map_features.map((f) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [f.lon, f.lat] },
      properties: {
        id: f.id, name: f.name, voltage_kv: f.voltage_kv,
        firm_mw: f.firm_mw, rag: f.rag,
      },
    }));
    return { type: "FeatureCollection", features };
  }
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

/* ── Live → Mock-shape adapter ─────────────────────────────────────────── */
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
    timeline_gantt: forecast?.gantt || mock.default.timeline_gantt,
    compliance: mock.default.compliance, // regulatory registry shared
    power_chain: null,
    _provenance: assess?.data_provenance || "live_backend",
  };
}

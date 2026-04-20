/**
 * dcOps.js — aggregator for DC live-ops overlays shown in DCDesignTwin.
 *
 * Endpoints called (when VITE_MOCK_DC_OPS !== "true"):
 *   POST /api/dc/thermal-field           → hall-level 2D temp grid (EXISTS)
 *   GET  /api/dc/noise-contours          → genset/chiller dB contours (MISSING — follow-up)
 *   GET  /api/dc/glint-screen            → solar-noon glint cones     (MISSING — follow-up)
 *   WS   /ws/dc-ops                      → live PUE / IT load ticks   (MISSING — follow-up)
 *   GET  /api/dc/ops                     → PUE / IT load snapshot     (MISSING — follow-up)
 *
 * For endpoints that don't yet exist, we fall back to deterministic
 * client-side derivations from the building geometry + IT load so the
 * overlays still render something defensible during demos. Replace
 * with live calls once BOT-backend lands the routes.
 */

const MOCK_FLAG = (import.meta.env.VITE_MOCK_DC_OPS ?? "true").toString().toLowerCase();
export const USE_MOCK_DC_OPS = MOCK_FLAG !== "false" && MOCK_FLAG !== "0";
const API_BASE = import.meta.env.VITE_API_BASE || "";

/** ── THERMAL ──────────────────────────────────────────────────────────────
 * Returns a 2D grid of inlet/exhaust temperatures + hotspot list, matched
 * to the hall footprint.
 *   { grid: number[][], grid_x, grid_y, rows, max_inlet_temp_c, hotspots: […] }
 */
export async function fetchThermalField({ itLoadMw = 50, containment = "hot_aisle", cooling = "air_crac", supplyTempC = 18 } = {}) {
  // IT MW → rack budget at 15 kW/rack. Clamp rack_count so the /api/dc/thermal-field
  // endpoint stays within its sane working range.
  const rackCount = Math.min(400, Math.max(16, Math.round((itLoadMw * 1000) / 15)));
  const rackKw = 15;
  const rows = Math.max(4, Math.round(Math.sqrt(rackCount / 10)));
  const cracCount = Math.max(4, Math.ceil(rackCount / 20));

  if (!USE_MOCK_DC_OPS) {
    try {
      const qs = new URLSearchParams({
        rack_count: rackCount, rack_kw: rackKw, rows,
        cooling_type: cooling, crac_count: cracCount,
        containment, supply_temp_c: supplyTempC,
      });
      const r = await fetch(`${API_BASE}/api/dc/thermal-field?${qs}`, { method: "POST" });
      if (r.ok) return await r.json();
    } catch { /* fall through to mock */ }
  }
  return mockThermalField(rows, Math.ceil(rackCount / rows), supplyTempC, rackKw, containment);
}

function mockThermalField(rows, racksPerRow, supplyTempC, rackKw, containment) {
  const gridX = racksPerRow;
  const gridY = rows * 2;
  const containmentEff = containment === "hot_aisle" ? 0.85 : containment === "cold_aisle" ? 0.80 : 0.5;
  const baseDeltaT = rackKw * 0.7;
  const field = [];
  const hotspots = [];
  let maxTemp = supplyTempC;
  for (let y = 0; y < gridY; y++) {
    const row = Math.floor(y / 2);
    const isHotAisle = y % 2 === 1;
    const line = [];
    for (let x = 0; x < gridX; x++) {
      // Hotspot at ends of rows (furthest from CRAC units placed mid-hall).
      const distFromCentre = Math.abs(x - gridX / 2) / (gridX / 2);
      const recirc = distFromCentre * 2.8;
      const bypass = (1 - containmentEff) * baseDeltaT * 0.3;
      const inlet = supplyTempC + bypass + recirc + ((x * 31 + row * 7) % 10) / 10 * 1.2;
      const temp = isHotAisle ? inlet + baseDeltaT : inlet;
      line.push(Number(temp.toFixed(1)));
      if (!isHotAisle && inlet > 27) {
        hotspots.push({ row, col: x, inlet_temp_c: Number(inlet.toFixed(1)), severity: inlet > 32 ? "CRITICAL" : "CAUTION" });
      }
      if (temp > maxTemp) maxTemp = temp;
    }
    field.push(line);
  }
  return {
    grid: field, grid_x: gridX, grid_y: gridY,
    rows, racks_per_row: racksPerRow,
    supply_temp_c: supplyTempC,
    max_inlet_temp_c: Number(maxTemp.toFixed(1)),
    min_inlet_temp_c: supplyTempC,
    hotspot_count: hotspots.length,
    hotspots: hotspots.slice(0, 20),
    containment,
    _source: "client-mock",
  };
}

/** ── NOISE ────────────────────────────────────────────────────────────────
 * Returns a set of emitter points (genset yard, chiller plant) + ring
 * radii per dB threshold, in metres from each emitter.
 *   {
 *     emitters: [{ lat, lon, source_db, label }],
 *     thresholds: [{ db: 55, color: "amber" }, { db: 65, color: "red" }],
 *     receptor_flags: [{ lat, lon, db_at_receptor, exceeds: true/false }]
 *   }
 */
export async function fetchNoiseContours({ lat, lon, itLoadMw = 50, genLat, genLon, chillLat, chillLon, receptors = [] } = {}) {
  if (!USE_MOCK_DC_OPS) {
    try {
      const qs = new URLSearchParams({ lat, lon, it_mw: itLoadMw });
      const r = await fetch(`${API_BASE}/api/dc/noise-contours?${qs}`);
      if (r.ok) return await r.json();
    } catch { /* fall through */ }
  }
  // ISO 9613-2 simplified: point source, hemispherical spread.
  // L_p = L_w - 20*log10(r) - 8 - A_atm (A_atm ~0.5 dB/100m at 500 Hz)
  // So distance at which L_p = target:  r = 10^((L_w - target - 8) / 20)
  // Genset yard Lw ~ 112 dB (4× 2 MVA diesels). Chiller plant Lw ~ 98 dB.
  const emitters = [
    { lat: genLat ?? lat, lon: genLon ?? lon, source_db: 112, label: "Genset yard" },
    { lat: chillLat ?? lat, lon: chillLon ?? lon, source_db: 98, label: "Chiller plant" },
  ];
  const thresholds = [
    { db: 55, color: [245, 183, 49, 180] },   // amber — planning concern
    { db: 65, color: [239, 68, 68, 220] },    // red — likely exceedance at receptor
  ];
  // Per-emitter ring radius at each threshold.
  emitters.forEach(e => {
    e.rings = thresholds.map(t => ({
      db: t.db,
      color: t.color,
      radius_m: Math.pow(10, (e.source_db - t.db - 8) / 20),
    }));
  });
  // Receptor check — pick the worst-case emitter L_p at each receptor.
  const receptor_flags = receptors.map(rx => {
    let worst = { db_at_receptor: 0, emitter: null };
    emitters.forEach(e => {
      const dLat = (rx.lat - e.lat) * 111_320;
      const dLon = (rx.lon - e.lon) * 111_320 * Math.cos((e.lat * Math.PI) / 180);
      const r = Math.max(5, Math.hypot(dLat, dLon));
      const Lp = e.source_db - 20 * Math.log10(r) - 8;
      if (Lp > worst.db_at_receptor) worst = { db_at_receptor: Math.round(Lp * 10) / 10, emitter: e.label };
    });
    return { ...rx, ...worst, exceeds: worst.db_at_receptor > 55 };
  });
  return { emitters, thresholds, receptor_flags, _source: "client-mock" };
}

/** ── GLINT ────────────────────────────────────────────────────────────────
 * Returns reflective-surface cones at summer + winter solstice noon.
 * If a cone intersects a provided receptor (residence / road), flag it.
 *   {
 *     surfaces: [{ lat, lon, azimuth_deg, tilt_deg, label }],
 *     cones: [{ surface, season: 'summer'|'winter', bearing_deg, spread_deg, length_m }],
 *     receptor_hits: [{ lat, lon, season, bearing_deg }]
 *   }
 */
export async function fetchGlintCones({ lat, lon, coolingLat, coolingLon, receptors = [] } = {}) {
  if (!USE_MOCK_DC_OPS) {
    try {
      const qs = new URLSearchParams({ lat, lon });
      const r = await fetch(`${API_BASE}/api/dc/glint-screen?${qs}`);
      if (r.ok) return await r.json();
    } catch { /* fall through */ }
  }
  // Rooftop dry coolers — assume horizontal (tilt ~10°, azimuth S).
  // Solar-noon altitude at UK 51.5°N:
  //   summer solstice: 90 - 51.5 + 23.45 ≈ 62°
  //   winter solstice: 90 - 51.5 - 23.45 ≈ 15°
  // Reflected beam bearing at noon ≈ opposite of sun azimuth (due S → due N).
  // So reflected cone points north, with declination depending on season.
  const surfaces = [
    { lat: coolingLat ?? lat, lon: coolingLon ?? lon, azimuth_deg: 180, tilt_deg: 10, label: "Cooling plant (dry coolers)" },
  ];
  const cones = surfaces.flatMap(s => ([
    { surface: s.label, lat: s.lat, lon: s.lon, season: "summer", sun_alt_deg: 62, bearing_deg: 0, spread_deg: 12, length_m: 250 },
    { surface: s.label, lat: s.lat, lon: s.lon, season: "winter", sun_alt_deg: 15, bearing_deg: 0, spread_deg: 18, length_m: 950 },
  ]));
  // Receptor geometry check — is the receptor inside the cone?
  const receptor_hits = [];
  receptors.forEach(rx => {
    cones.forEach(c => {
      const dLat = (rx.lat - c.lat) * 111_320;
      const dLon = (rx.lon - c.lon) * 111_320 * Math.cos((c.lat * Math.PI) / 180);
      const dist = Math.hypot(dLat, dLon);
      if (dist > c.length_m) return;
      const bearing = (Math.atan2(dLon, dLat) * 180 / Math.PI + 360) % 360;
      const delta = Math.min(Math.abs(bearing - c.bearing_deg), 360 - Math.abs(bearing - c.bearing_deg));
      if (delta <= c.spread_deg) receptor_hits.push({ ...rx, season: c.season, bearing_deg: Math.round(bearing), dist_m: Math.round(dist) });
    });
  });
  return { surfaces, cones, receptor_hits, _source: "client-mock" };
}

/** ── LIVE OPS ─────────────────────────────────────────────────────────────
 * Subscribe to live PUE / IT load / cooling MW / water makeup rate.
 * Uses WebSocket when available, falls back to 30s polling.
 *
 * Returns an unsubscribe function. `onTick` is called with a snapshot:
 *   { pue, it_load_pct, cooling_mw, water_lpm, ts }
 */
export function subscribeDcOps({ itLoadMw = 50, onTick }) {
  let alive = true;
  let ws = null;
  let pollTimer = null;
  let fakeTimer = null;

  const emitFake = () => {
    // Deterministic tick — varies around diurnal profile.
    const hour = (new Date().getHours() + new Date().getMinutes() / 60);
    const diurnal = 0.72 + 0.22 * Math.sin(((hour - 6) / 24) * 2 * Math.PI);
    const jitter = (Math.random() - 0.5) * 0.04;
    const itPct = Math.max(0.4, Math.min(0.98, diurnal + jitter));
    const coolingMw = itLoadMw * itPct * 0.32;                  // ~32% IT kW → cooling kW
    const pue = 1.18 + 0.08 * (1 - itPct) + Math.random() * 0.01;
    const waterLpm = coolingMw * 1.8 + Math.random() * 6;       // ~1.8 L/min/MW adiabatic
    onTick?.({
      pue: Number(pue.toFixed(3)),
      it_load_pct: Number((itPct * 100).toFixed(1)),
      cooling_mw: Number(coolingMw.toFixed(2)),
      water_lpm: Number(waterLpm.toFixed(1)),
      ts: Date.now(),
    });
  };

  const pollOnce = async () => {
    if (!alive) return;
    if (USE_MOCK_DC_OPS) { emitFake(); return; }
    try {
      const r = await fetch(`${API_BASE}/api/dc/ops`);
      if (r.ok) { const j = await r.json(); onTick?.(j); return; }
    } catch { /* silent */ }
    emitFake();
  };

  if (!USE_MOCK_DC_OPS) {
    try {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${window.location.host}/ws/dc-ops`);
      ws.onmessage = (ev) => {
        try { onTick?.(JSON.parse(ev.data)); } catch { /* noop */ }
      };
      ws.onerror = () => {
        try { ws?.close(); } catch { /* noop */ }
        ws = null;
        pollOnce();
        pollTimer = setInterval(pollOnce, 30_000);
      };
    } catch {
      pollOnce();
      pollTimer = setInterval(pollOnce, 30_000);
    }
  } else {
    emitFake();
    fakeTimer = setInterval(emitFake, 5_000);
  }

  return () => {
    alive = false;
    try { ws?.close(); } catch { /* noop */ }
    if (pollTimer) clearInterval(pollTimer);
    if (fakeTimer) clearInterval(fakeTimer);
  };
}

import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import {
  generate as apiGenerate,
  saveLayout as apiSaveLayout,
  listLayouts as apiListLayouts,
  getLayout as apiGetLayout,
  updateLayout as apiUpdateLayout,
  optimise as apiOptimise,
  askAgent as apiAskAgent,
  explainKpi as apiExplainKpi,
  exportLayout as apiExportLayout,
} from "../../services/design";
import bessBenchmarks from "../../data/bess-benchmarks.json";
import solarBenchmarks from "../../data/solar-benchmarks.json";
import TwinLazy from "../twin3d/TwinLazy";
import { useSite } from "../../SiteContext";
import EquipmentPalette, { EQUIPMENT_CATALOGUE } from "../design/EquipmentPalette";
import { buildCampusLayout } from "../dc/dcLayoutPresets";
import DesignViewModeTabs, { applyViewModeToMap } from "../design/DesignViewModeTabs";
import DesignMeasureTool from "../design/DesignMeasureTool";
import useDesignPlacements from "../../hooks/useDesignPlacements";
import { useDesignContext } from "../../hooks/useDesignContext";
import {
  ensureConstraintSourcesAndLayers,
  setConstraintData,
  setConstraintVisibility,
  DesignOverlayTogglePanel,
} from "../design/DesignConstraintOverlays";

/* Scale reference chips shown top-right of canvas. Hovering a chip highlights
   every matching placed item and pulses them in the palette. */
const SCALE_REFS = [
  { key: "human",    label: "Human",    size_m: 1.7, typeIds: [] },
  { key: "hgv",      label: "HGV",      size_m: 16,  typeIds: ["loading_bay"] },
  { key: "megapack", label: "Megapack", size_m: 7,   typeIds: ["megapack", "bess_container"] },
];

/* Snap a continuous duration (h) to the nearest benchmark bucket key. */
function bessDurationKey(durationH) {
  if (durationH <= 1.5) return "1";
  if (durationH <= 3.0) return "2";
  if (durationH <= 6.0) return "4";
  return "8";
}

/* Blended P50 revenue £/MW/yr, duration-aware. */
function bessRevenueMidGbpMwYr(durationH) {
  const bucket = bessBenchmarks.revenue_gbp_mw_yr[bessDurationKey(durationH)];
  return bucket.mid;
}

/* ── Solar heuristic KPIs (mirrors utils/solar_benchmarks.py) ─────────── */
function solarKpis({ capacity_mw }) {
  const cf = solarBenchmarks.capacity_factor.mid;              // 0.11
  const ppa = solarBenchmarks.ppa_merchant_gbp_mwh.mid;        // £45/MWh
  const capexPerKw = solarBenchmarks.capex_gbp_per_kw.mid;     // £730/kWp
  const opexPerKwYr = solarBenchmarks.opex_gbp_per_kw_yr.mid;  // £10/kW/yr
  const energyMwh = capacity_mw * 8760 * cf;
  const capex = capacity_mw * 1000 * capexPerKw;
  const revenue = energyMwh * ppa;
  const opex = capacity_mw * 1000 * opexPerKwYr;
  const net = revenue - opex;
  const irr = capex > 0 ? Math.max(0, (net * 25 / capex - 1)) * 100 / 2.5 : 0;
  const lcoe = energyMwh > 0 ? (capex / 25 + opex) / energyMwh : 0;
  return {
    effective_capacity_mw: +capacity_mw.toFixed(2),
    capacity_factor_pct: +(cf * 100).toFixed(1),
    annual_mwh: +energyMwh.toFixed(1),
    energy_mwh: +energyMwh.toFixed(1),
    capex_gbp_m: +(capex / 1_000_000).toFixed(2),
    annual_revenue_gbp_m: +(revenue / 1_000_000).toFixed(2),
    annual_opex_gbp_m: +(opex / 1_000_000).toFixed(2),
    irr_pct: +irr.toFixed(1),
    lcoe_gbp_per_mwh: +lcoe.toFixed(1),
    ppa_price_gbp_mwh: ppa,
  };
}

const ORCHESTRATOR_DEBOUNCE_MS = 260;
const OBJECTIVES = [
  { key: "irr",   label: "IRR",   hint: "Maximise internal rate of return" },
  { key: "lcoe",  label: "LCOE",  hint: "Minimise levelised cost" },
  { key: "yield", label: "Yield", hint: "Maximise annual energy" },
  { key: "capex", label: "CAPEX", hint: "Minimise up-front capital" },
];

/**
 * DesignCanvas — the Princeps site designer.
 *
 * One surface. Map-first. Chat-driven. Agent-graded. The designer *is* the
 * twin + the agent + the grid reality, not a separate tab.
 *
 * D2  Headroom-governed MW slider (amber past headroom → split-connection suggest)
 * D3  4-intent agent verdict rail (grid / planning / environmental / feasibility)
 * D4  REPD / NSIP planning-precedent pins
 * D5  GeeFlow buildable-area mask
 * D6  SAM yield + curtailment heatmap (solar only)
 * D7  Zoom-continuous 2D ↔ 3D extrusion (replaces SiteDesigner3D)
 * D8  Reasoning-per-feature popover → prefills chat
 */

const WORKLOAD_DEFAULTS = {
  bess:  { capacity_mw: 50, duration_h: 2, label: "Battery Storage" },
  solar: { capacity_mw: 40, label: "Solar PV" },
  dc:    { it_load_mw: 40, pue_target: 1.2, label: "Data Centre" },
};

const PAD_M = { w: 40, h: 25, gap: 8 };
const DEG_PER_M_LAT = 1 / 111_320;

const MASK_COLORS = {
  buildable:             "transparent",
  restricted_slope:      "#8B5CF6",
  restricted_land:       "#EF4444",
  restricted_flood:      "#3B82F6",
  restricted_protected:  "#F59E0B",
  restricted_alc:        "#DC2626",
};

const EXTRUSION_HEIGHT_M = {
  battery: 3.2, battery_container_20ft: 3.2, battery_container_40ft: 3.2,
  transformer: 2.0, substation: 5.0, inverter: 2.5,
  server_hall: 8.0, server_hall_standard: 8.0, server_hall_large: 10.0, server_hall_hyperscale: 14.0,
  control_room: 4.0, gate: 2.5, panel: 2.2,
};
const DEFAULT_EXTRUSION_M = 3.0;

function degPerMLon(lat) { return 1 / (111_320 * Math.cos((lat * Math.PI) / 180)); }

/* ── Deterministic client-side BESS layout fallback ─────────────────────── */
function generateBessLayout({ lat, lon, capacity_mw, duration_h }) {
  const padsNeeded = Math.max(1, Math.ceil(capacity_mw / 10));
  const cols = Math.min(5, padsNeeded);
  const rows = Math.max(1, Math.ceil(padsNeeded / 5));
  const dLon = degPerMLon(lat);
  const wDeg = PAD_M.w * dLon;
  const hDeg = PAD_M.h * DEG_PER_M_LAT;
  const gapLon = PAD_M.gap * dLon;
  const gapLat = PAD_M.gap * DEG_PER_M_LAT;
  const totalW = cols * wDeg + (cols - 1) * gapLon;
  const totalH = rows * hDeg + (rows - 1) * gapLat;
  const originLon = lon - totalW / 2;
  const originLat = lat - totalH / 2;
  const features = [];
  let idx = 0;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols && idx < padsNeeded; c++) {
      const x0 = originLon + c * (wDeg + gapLon);
      const y0 = originLat + r * (hDeg + gapLat);
      features.push({
        type: "Feature",
        properties: {
          idx, mw: 10, type: "battery", label: `BESS-${String(idx + 1).padStart(3, "0")}`,
          reasoning: `Row ${r + 1} Col ${c + 1}: ${PAD_M.gap} m fire gap per BS 8629:2019; 10 MW modular block for staged commissioning`,
        },
        geometry: {
          type: "Polygon",
          coordinates: [[
            [x0, y0], [x0 + wDeg, y0], [x0 + wDeg, y0 + hDeg],
            [x0, y0 + hDeg], [x0, y0],
          ]],
        },
      });
      idx++;
    }
  }
  const areaHa = (padsNeeded * PAD_M.w * PAD_M.h) / 10_000;
  return {
    type: "FeatureCollection",
    features,
    meta: {
      pad_count: padsNeeded, area_ha: +areaHa.toFixed(3),
      design_rationale: `BESS laid out as ${rows}×${cols} of ${PAD_M.w}×${PAD_M.h} m pads with ${PAD_M.gap} m fire breaks. N-S orientation preserves access alleys.`,
    },
  };
}

/* ── Heuristic KPIs (BESS) ──────────────────────────────────────────────── */
/* Anchored to feasi-frontend/src/data/bess-benchmarks.json which mirrors
 * utils/bess_benchmarks.py (Modo Energy GB BESS index, Mar 2026).          */
function bessKpis({ capacity_mw, duration_h, headroom_mw }) {
  const effective = headroom_mw != null ? Math.min(capacity_mw, headroom_mw) : capacity_mw;
  const energy = effective * duration_h;
  const capexGbpPerKwh = bessBenchmarks.capex_gbp_per_kwh.mid;       // £310/kWh
  const fixedOpexGbpMwYr = bessBenchmarks.fixed_opex_gbp_mw_yr;      // £8k/MW/yr
  const capex = energy * 1000 * capexGbpPerKwh;
  const revenue = effective * bessRevenueMidGbpMwYr(duration_h);
  const opex = effective * fixedOpexGbpMwYr;
  const net = revenue - opex;
  const irr = Math.max(0, ((net * 15) / capex - 1)) * 100 / 1.5;
  const lcoe = capex / Math.max(1, energy * 250);
  return {
    effective_capacity_mw: +effective.toFixed(2),
    energy_mwh: +energy.toFixed(1),
    capex_gbp_m: +(capex / 1_000_000).toFixed(2),
    revenue_gbp_m: +(revenue / 1_000_000).toFixed(2),
    irr_pct: +irr.toFixed(1),
    lcoe_gbp_per_mwh: +lcoe.toFixed(1),
  };
}

/* ── D2: over-headroom reinforcement estimate ──────────────────────────── */
function reinforcementEstimate(capacity_mw, headroom_mw) {
  if (headroom_mw == null || capacity_mw <= headroom_mw) return null;
  const over = capacity_mw - headroom_mw;
  const costGbpM = +(over * 0.8).toFixed(2);
  const monthsAdded = Math.max(3, Math.round(costGbpM * 6));
  return { over_mw: +over.toFixed(1), cost_gbp_m: costGbpM, months_added: monthsAdded };
}

/* ── Intents for the verdict rail ──────────────────────────────────────── */
const VERDICT_INTENTS = [
  { key: "grid_connection", label: "Grid" },
  { key: "planning",        label: "Planning" },
  { key: "environmental",   label: "Enviro" },
  { key: "feasibility",     label: "Feas" },
];

/* ── Main component ─────────────────────────────────────────────────────── */
export default function DesignCanvas({
  site,
  project,
  isOpen = false,
  onClose = () => {},
  onSave = () => {},
}) {
  const workload = project?.technology || "bess";
  const defaults = WORKLOAD_DEFAULTS[workload] || WORKLOAD_DEFAULTS.bess;

  // ── Effective origin ────────────────────────────────────────────────
  // The Site Designer is reachable with or without a selected candidate
  // site. When no candidate is selected, fall back to the project record
  // (its `lat`/`lon`) so the Mapbox canvas still centres on the real
  // project location — previously this path silently defaulted to London.
  const effectiveSite = useMemo(() => {
    if (site && site.lat != null && site.lon != null) return site;
    if (project?.lat != null && project?.lon != null) {
      return {
        ...(site || {}),
        lat: project.lat,
        lon: project.lon,
        name: site?.name || project.name || "Project site",
        candidate_id: site?.candidate_id || null,
      };
    }
    return site || null;
  }, [site, project]);

  // ── Canvas ↔ 3D Site Twin view mode (additive, 2D canvas stays default) ──
  // Expose via useSite context so external callers can switch it (ChatPanel
  // actions, deep-links, …). Falls back to a local state+localStorage pair
  // if the context isn't wired through — defensive since DesignCanvas can
  // render both inside the workspace and standalone in tests.
  let siteCtx = null;
  try { siteCtx = useSite(); } catch { siteCtx = null; } // eslint-disable-line
  const [localMode, setLocalMode] = useState(() => {
    try { return localStorage.getItem("princeps_design_canvas_mode") === "twin" ? "twin" : "canvas"; }
    catch { return "canvas"; }
  });
  const designMode = siteCtx?.designCanvasMode || localMode;
  const setDesignMode = useCallback((m) => {
    if (siteCtx?.setDesignCanvasMode) siteCtx.setDesignCanvasMode(m);
    setLocalMode(m);
    try { localStorage.setItem("princeps_design_canvas_mode", m); } catch { /* ignore */ }
  }, [siteCtx]);

  const [capacity, setCapacity] = useState(() => site?.capacity_mw || defaults.capacity_mw || 50);
  const [duration, setDuration] = useState(defaults.duration_h || 2);
  const [headroom, setHeadroom] = useState(null);
  const [chatInput, setChatInput] = useState("");
  const [reasoning, setReasoning] = useState([]);
  const [streaming, setStreaming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState(null);

  // D2 — split connection suggestions
  const [splitOpen, setSplitOpen] = useState(false);
  const [splitData, setSplitData] = useState(null);
  const [splitLoading, setSplitLoading] = useState(false);

  // D3 — agent verdict rail
  const [verdicts, setVerdicts] = useState({});   // { grid_connection: {status, reasoning} }
  const [expandedVerdict, setExpandedVerdict] = useState(null);

  // D4 — precedent
  const [precedent, setPrecedent] = useState(null);

  // D5 — buildable mask
  const [mask, setMask] = useState(null);
  const [maskVisible, setMaskVisible] = useState(true);

  // D6 — yield + curtailment (solar only)
  const [yieldData, setYieldData] = useState(null);

  // D8 — feature popover
  const [popover, setPopover] = useState(null);   // { lng, lat, feature }

  /* Orchestrator + versioning + optimiser + Why — wired via services/design.js */
  const [apiResult, setApiResult] = useState(null);     // { doc, kpis, reasoning, warnings, substation }
  const [apiLoading, setApiLoading] = useState(false);
  const [apiError, setApiError] = useState(null);
  const [versions, setVersions] = useState([]);
  const [currentVersionId, setCurrentVersionId] = useState(null);
  const [optimisingFor, setOptimisingFor] = useState(null);
  const [whyKpi, setWhyKpi] = useState(null);
  const [whyText, setWhyText] = useState(null);

  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);

  // ── BOT-SDB: Glint-style constraint overlays ────────────────────────────
  // Toggle map controls rendering of: red-line, buildable area, flood, SSSI /
  // AONB / Green Belt, ALC 1/2, setback rings, sun-path arcs. Defaults tuned
  // so a fresh canvas isn't cluttered — red-line + buildable ON.
  const [overlayToggles, setOverlayToggles] = useState({
    redline:      true,
    buildable:    true,
    designations: false,
    flood:        false,
    alc:          false,
    setbacks:     false,
    sunpath:      false,
  });
  const onOverlayToggle = useCallback((key, val) => {
    setOverlayToggles((t) => ({ ...t, [key]: val }));
  }, []);
  const designCtx = useDesignContext({
    lat: site?.lat,
    lon: site?.lon,
    enabled: isOpen && !!site,
    radiusM: 1500,
  });

  // ── View mode (Plan / Oblique / Construction / Drone) ────────────────
  const [viewMode, setViewMode] = useState("plan");
  const [constructionMonth, setConstructionMonth] = useState(6);
  const [droneOrbiting, setDroneOrbiting] = useState(true);

  // ── Equipment palette + drag-drop placements ─────────────────────────
  const [paletteCollapsed, setPaletteCollapsed] = useState(false);
  const [hoveredScaleKey, setHoveredScaleKey] = useState(null);
  const placementScope = project?.project_id || site?.candidate_id || `${site?.lat},${site?.lon}`;
  const placementsState = useDesignPlacements({ scopeId: placementScope });

  // ── Measure tool (ruler) ─────────────────────────────────────────────
  const [measureActive, setMeasureActive] = useState(false);
  const [measureMode, setMeasureMode] = useState("distance");

  const layout = useMemo(() => {
    if (!effectiveSite) return null;
    // Workload-aware layout generator — BESS gets the fire-break pad grid;
    // DC gets a full campus (shell + halls + spine + MV/LV + genset + TX +
    // water + office + security + loading + fence) from dcLayoutPresets.
    if (workload === "dc" || workload === "data_centre" || workload === "datacentre") {
      try {
        const campus = buildCampusLayout({
          itLoadMw: capacity,
          tier: project?.tier ?? 3,
          redundancy: project?.redundancy ?? "N+1",
          coolingType: project?.cooling_type || "hybrid",
        });
        const dLon = degPerMLon(effectiveSite.lat);
        const dLat = DEG_PER_M_LAT;
        const rect = (cx, cy, w, d) => {
          const hx = w / 2;
          const hy = d / 2;
          const corners = [
            [cx - hx, cy - hy], [cx + hx, cy - hy],
            [cx + hx, cy + hy], [cx - hx, cy + hy], [cx - hx, cy - hy],
          ];
          return corners.map(([x, y]) => [
            effectiveSite.lon + x * dLon,
            effectiveSite.lat + y * dLat,
          ]);
        };
        const items = [
          campus.shell, campus.spine, campus.mvlv,
          campus.genset, campus.tx, campus.water,
          campus.office, campus.security, campus.loading,
          ...(campus.halls || []),
          ...(campus.gensets || []),
          ...(campus.transformers || []),
          ...(campus.dieselTanks || []),
        ].filter(Boolean);
        const features = items.map((it, idx) => ({
          type: "Feature",
          properties: {
            idx,
            mw: it.role === "hall" ? Math.round(capacity / (campus.halls?.length || 1)) : 0,
            type: it.role === "hall" ? "server_hall"
                : it.role === "mvlv" ? "substation"
                : it.role === "tx" ? "transformer"
                : it.role === "genset" ? "control_room"
                : "panel",
            label: it.label || it.key,
            role: it.role,
            reasoning: `${it.role} · ${it.width?.toFixed(0) || "?"} × ${it.depth?.toFixed(0) || "?"} m · ${(it.height || 0).toFixed(1)} m tall`,
          },
          geometry: { type: "Polygon", coordinates: [rect(it.cx, it.cy, it.width, it.depth)] },
        }));
        return {
          type: "FeatureCollection",
          features,
          meta: {
            pad_count: campus.halls?.length || 0,
            area_ha: +((campus.shell?.area || 0) / 10_000).toFixed(3),
            design_rationale: `DC campus — ${campus.halls?.length || 0} halls; ${(campus.gensets || []).length} × 5 MW gensets; ${(campus.transformers || []).length} × 20 MVA TX.`,
          },
        };
      } catch (err) {
        console.warn("[DesignCanvas] DC campus build failed, falling back:", err);
      }
    }
    return generateBessLayout({
      lat: effectiveSite.lat, lon: effectiveSite.lon,
      capacity_mw: capacity, duration_h: duration,
    });
  }, [effectiveSite, workload, capacity, duration, project?.tier, project?.redundancy, project?.cooling_type]);

  const kpis = useMemo(() => {
    if (workload === "solar") return solarKpis({ capacity_mw: capacity });
    return bessKpis({
      capacity_mw: capacity, duration_h: duration, headroom_mw: headroom,
    });
  }, [workload, capacity, duration, headroom]);

  const reinforcement = useMemo(
    () => reinforcementEstimate(capacity, headroom),
    [capacity, headroom],
  );

  /* ── Initial reasoning ───────────────────────────────────────────────── */
  useEffect(() => {
    if (!layout) return;
    const lines = [];
    if (layout.meta?.design_rationale) lines.push(layout.meta.design_rationale);
    lines.push(
      `Sized to ${capacity.toFixed(1)} MW / ${(capacity * duration).toFixed(0)} MWh — LFP chemistry chosen for UK ancillary services.`,
      `Laid out as ${layout.meta.pad_count} × 10 MW pads with ${PAD_M.gap} m fire breaks (BS 8629:2019).`,
      `Footprint ${layout.meta.area_ha} ha — grid-oriented to minimise cable run.`,
    );
    if (headroom == null) lines.push("Grid headroom unverified — confirm with DNO before FID.");
    else if (capacity > headroom) lines.push(`⚠ Capped at ${headroom.toFixed(1)} MW by substation headroom — split connection recommended.`);
    else lines.push(`Substation headroom (${headroom.toFixed(1)} MW) accommodates this size.`);
    setReasoning(lines);
  }, [capacity, duration, headroom, layout]);

  /* ── Headroom fetch (also captures POC coords for the grid layer) ───── */
  const [nearestSubstation, setNearestSubstation] = useState(null);
  useEffect(() => {
    if (!effectiveSite || !isOpen) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/grid/nearest-substation?lat=${effectiveSite.lat}&lon=${effectiveSite.lon}`);
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        if (data?.headroom_mw != null) setHeadroom(data.headroom_mw);
        if (data?.lat != null && data?.lon != null) setNearestSubstation(data);
      } catch { /* keep null */ }
    })();
    return () => { cancelled = true; };
  }, [effectiveSite, isOpen]);

  /* ── D4: REPD / NSIP precedent fetch ─────────────────────────────────── */
  useEffect(() => {
    if (!site || !isOpen) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/planning-ml/nearby-precedent?lat=${site.lat}&lon=${site.lon}&tech=${workload}&radius_km=25`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setPrecedent(data);
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [site, isOpen, workload]);

  /* ── D5: buildable-mask fetch ────────────────────────────────────────── */
  useEffect(() => {
    if (!site || !isOpen) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/design/buildable-mask?lat=${site.lat}&lon=${site.lon}&radius_m=1500`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setMask(data);
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [site, isOpen]);

  /* ── BOT-SDB: push constraint-overlay data to mapbox sources ─────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !site) return;
    const push = () => {
      try {
        // Ensure the sources/layers exist (idempotent) — needed when the
        // style has just loaded or when we swap basemaps mid-session.
        ensureConstraintSourcesAndLayers(map);
        setConstraintData(map, designCtx, { lat: site.lat, lon: site.lon });
        setConstraintVisibility(map, overlayToggles);
      } catch { /* noop */ }
    };
    if (map.isStyleLoaded && map.isStyleLoaded()) push();
    else map.once("load", push);
  }, [designCtx, site, overlayToggles]);

  /* ── D6: yield + curtailment (solar only) ────────────────────────────── */
  useEffect(() => {
    if (!site || !isOpen || workload !== "solar") { setYieldData(null); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const res = await fetch(`/api/design/yield-curtailment?lat=${site.lat}&lon=${site.lon}&capacity_mw=${capacity}&tech=solar`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setYieldData(data);
      } catch { /* silent */ }
    }, 400);
    return () => { cancelled = true; clearTimeout(t); };
  }, [site, isOpen, workload, capacity]);

  /* ── D3: 4-intent agent verdict rail (debounced) ─────────────────────── */
  useEffect(() => {
    if (!site || !isOpen) return;
    let cancelled = false;
    setVerdicts((v) => {
      const next = {};
      for (const i of VERDICT_INTENTS) next[i.key] = { status: "loading" };
      return next;
    });
    const t = setTimeout(async () => {
      const payloads = VERDICT_INTENTS.map(({ key }) =>
        fetch("/api/agent/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            intent: key,
            context: {
              lat: site.lat, lon: site.lon,
              capacity_mw: capacity, capacity_kw: capacity * 1000,
              duration_h: duration, technology: workload,
              headroom_mw: headroom,
            },
          }),
        }).then(async (r) => {
          if (!r.ok) throw new Error(`${key} ${r.status}`);
          return r.json();
        }).catch(() => null)
      );
      const results = await Promise.all(payloads);
      if (cancelled) return;
      const next = {};
      VERDICT_INTENTS.forEach(({ key }, i) => {
        const r = results[i];
        if (!r) { next[key] = { status: "offline" }; return; }
        next[key] = {
          status: (r.verdict || "CAUTION").toLowerCase().replace("no-go", "nogo"),
          reasoning: r.summary || "",
          risks: r.risks || [],
          opportunities: r.opportunities || [],
        };
      });
      setVerdicts(next);
    }, 600);
    return () => { cancelled = true; clearTimeout(t); };
  }, [site, isOpen, capacity, duration, headroom, workload]);

  /* ── D2: split connection suggest ────────────────────────────────────── */
  const requestSplit = useCallback(async () => {
    if (!site) return;
    setSplitLoading(true); setSplitOpen(true);
    try {
      const res = await fetch("/api/grid/split-connection-suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat: site.lat, lon: site.lon, capacity_mw: capacity, max_splits: 3 }),
      });
      if (!res.ok) throw new Error(String(res.status));
      setSplitData(await res.json());
    } catch {
      setSplitData({ single_connection_feasible: headroom == null ? null : capacity <= headroom, splits: [], error: "endpoint offline" });
    } finally { setSplitLoading(false); }
  }, [site, capacity, headroom]);

  /* ── Mapbox mount + all overlays ─────────────────────────────────────── */
  useEffect(() => {
    if (!isOpen || !effectiveSite || !mapContainerRef.current) return;
    const map = new mapboxgl.Map({
      container: mapContainerRef.current,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: [effectiveSite.lon, effectiveSite.lat],
      zoom: 16.8,
      pitch: 45,
      bearing: 0,
      antialias: true,
      maxPitch: 85,
      attributionControl: false,
    });
    mapRef.current = map;
    map.on("load", () => {
      // ── BOT-SDB: terrain + 3D buildings + atmospheric sky ───────────────
      // Mirrors the DCDesignTwin recipe so the Site Designer reads like Glint
      // Solar: aerial imagery → 3D extruded buildings → oblique camera.
      try {
        if (!map.getSource("mapbox-dem")) {
          map.addSource("mapbox-dem", {
            type: "raster-dem",
            url: "mapbox://mapbox.mapbox-terrain-dem-v1",
            tileSize: 512,
            maxzoom: 14,
          });
        }
        map.setTerrain({ source: "mapbox-dem", exaggeration: 1.0 });
      } catch { /* terrain already set elsewhere */ }

      try {
        if (!map.getLayer("sky")) {
          map.addLayer({
            id: "sky",
            type: "sky",
            paint: {
              "sky-type": "atmosphere",
              "sky-atmosphere-sun": [0, 45],
              "sky-atmosphere-sun-intensity": 5,
            },
          });
        }
      } catch { /* noop */ }

      try {
        const labelLayer = map.getStyle().layers?.find(
          (l) => l.type === "symbol" && l.layout?.["text-field"],
        )?.id;
        if (!map.getLayer("3d-buildings")) {
          map.addLayer(
            {
              id: "3d-buildings",
              source: "composite",
              "source-layer": "building",
              filter: ["==", "extrude", "true"],
              type: "fill-extrusion",
              minzoom: 14,
              paint: {
                "fill-extrusion-color": "#d4d8df",
                "fill-extrusion-height": ["get", "height"],
                "fill-extrusion-base": ["get", "min_height"],
                "fill-extrusion-opacity": 0.7,
              },
            },
            labelLayer,
          );
        }
      } catch { /* composite source not present on this style */ }

      // ── BOT-SDB: constraint overlay sources + layers (idempotent) ───────
      try { ensureConstraintSourcesAndLayers(map); } catch { /* noop */ }

      // Buildable-area mask source + layer (D5) — added first so it sits below layout.
      map.addSource("mask", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "mask-fill", type: "fill", source: "mask",
        paint: {
          "fill-color": [
            "match", ["get", "class"],
            "restricted_slope",     MASK_COLORS.restricted_slope,
            "restricted_land",      MASK_COLORS.restricted_land,
            "restricted_flood",     MASK_COLORS.restricted_flood,
            "restricted_protected", MASK_COLORS.restricted_protected,
            "restricted_alc",       MASK_COLORS.restricted_alc,
            /* default buildable */ "rgba(0,0,0,0)",
          ],
          "fill-opacity": [
            "match", ["get", "class"],
            "restricted_flood",     0.35,
            "restricted_protected", 0.30,
            "restricted_alc",       0.30,
            "restricted_slope",     0.25,
            "restricted_land",      0.25,
            /* default */           0,
          ],
        },
      });

      // Layout source + fill (2D) + extrusion (3D) layers (D7)
      map.addSource("layout", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "layout-fill", type: "fill", source: "layout",
        paint: {
          "fill-color": "#F5B731",
          // Fade out at z>17 as extrusion fades in.
          "fill-opacity": ["interpolate", ["linear"], ["zoom"], 17, 0.55, 18, 0.05],
        },
      });
      map.addLayer({
        id: "layout-extrusion", type: "fill-extrusion", source: "layout",
        paint: {
          "fill-extrusion-color": "#F5B731",
          "fill-extrusion-height": [
            "match", ["get", "type"],
            "battery", EXTRUSION_HEIGHT_M.battery,
            "transformer", EXTRUSION_HEIGHT_M.transformer,
            "substation", EXTRUSION_HEIGHT_M.substation,
            "inverter", EXTRUSION_HEIGHT_M.inverter,
            "server_hall", EXTRUSION_HEIGHT_M.server_hall,
            "control_room", EXTRUSION_HEIGHT_M.control_room,
            "panel", EXTRUSION_HEIGHT_M.panel,
            DEFAULT_EXTRUSION_M,
          ],
          "fill-extrusion-base": 0,
          "fill-extrusion-opacity": ["interpolate", ["linear"], ["zoom"], 17, 0, 18, 0.9],
        },
      });
      map.addLayer({
        id: "layout-outline", type: "line", source: "layout",
        paint: { "line-color": "#ffffff", "line-width": 1.4, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: "layout-labels", type: "symbol", source: "layout",
        layout: {
          "text-field": ["concat", ["to-string", ["get", "mw"]], " MW"],
          "text-size": 10,
          "text-font": ["DIN Offc Pro Medium", "Arial Unicode MS Bold"],
        },
        paint: { "text-color": "#ffffff", "text-halo-color": "#000", "text-halo-width": 1.2 },
      });

      // Precedent source + pin layers (D4)
      map.addSource("precedent-approved", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("precedent-refused",  { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "precedent-approved-pins", type: "circle", source: "precedent-approved",
        paint: { "circle-radius": 7, "circle-color": "#10b981", "circle-stroke-color": "#fff", "circle-stroke-width": 1.5, "circle-opacity": 0.95 },
      });
      map.addLayer({
        id: "precedent-refused-pins", type: "circle", source: "precedent-refused",
        paint: { "circle-radius": 7, "circle-color": "#ef4444", "circle-stroke-color": "#fff", "circle-stroke-width": 1.5, "circle-opacity": 0.95 },
      });

      // Grid POC layer — line from effective site to the nearest DNO
      // substation + a gold pin on the substation itself. Data is pushed
      // via the `grid-poc`/`grid-poc-substation` sources in a dedicated
      // useEffect once /api/grid/nearest-substation returns.
      map.addSource("grid-poc", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("grid-poc-substation", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "grid-poc-line", type: "line", source: "grid-poc",
        paint: {
          "line-color": "#F5B731",
          "line-width": 2.2,
          "line-opacity": 0.85,
          "line-dasharray": [2, 2],
        },
      });
      map.addLayer({
        id: "grid-poc-substation-pin", type: "circle", source: "grid-poc-substation",
        paint: {
          "circle-radius": 9,
          "circle-color": "#F5B731",
          "circle-stroke-color": "#1a1a1a",
          "circle-stroke-width": 2,
          "circle-opacity": 0.95,
        },
      });

      // D8 — feature click (2D and 3D)
      const clickHandler = (e) => {
        const f = e.features?.[0];
        if (!f) return;
        setPopover({
          lng: e.lngLat.lng,
          lat: e.lngLat.lat,
          feature: { type: f.properties.type || "object", label: f.properties.label || "", reasoning: f.properties.reasoning || "No reasoning metadata." },
        });
      };
      map.on("click", "layout-fill", clickHandler);
      map.on("click", "layout-extrusion", clickHandler);

      // Precedent popups
      const precedentPopup = (e) => {
        const p = e.features?.[0]?.properties;
        if (!p) return;
        const reasons = p.refusal_reasons ? `<div style="margin-top:6px;color:#ef4444;font-size:11px">${p.refusal_reasons}</div>` : "";
        new mapboxgl.Popup({ offset: 10 })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-family:'DM Sans',sans-serif;font-size:12px;min-width:180px"><b>${p.name || p.id || "Site"}</b><div style="color:#6B6560;margin-top:2px">${p.council || ""} · ${p.capacity_mw || "?"} MW · ${p.decision_date || ""}</div>${reasons}</div>`)
          .addTo(map);
      };
      map.on("click", "precedent-approved-pins", precedentPopup);
      map.on("click", "precedent-refused-pins", precedentPopup);
    });
    return () => { map.remove(); mapRef.current = null; };
  }, [isOpen, effectiveSite?.lat, effectiveSite?.lon]);

  /* ── View-mode camera transitions (Plan / Oblique / Construction / Drone) ── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (viewMode === "drone" && !droneOrbiting) {
      try { map.easeTo({ pitch: 60, zoom: 16.8, duration: 600 }); } catch { /* ignore */ }
      return;
    }
    const stop = applyViewModeToMap(map, viewMode);
    return stop;
  }, [viewMode, droneOrbiting, isOpen]);

  /* ── Placements source + extrusion layers ────────────────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const ensureLayer = () => {
      if (map._removed) return;
      if (!map.getSource("placements")) {
        map.addSource("placements", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
        map.addLayer({
          id: "placements-fill",
          type: "fill-extrusion",
          source: "placements",
          paint: {
            "fill-extrusion-color": [
              "match", ["get", "category"],
              "power", "#F5B731",
              "cooling", "#3B82F6",
              "civil", "#8B5A2B",
              "grid", "#10B981",
              "safety", "#EF4444",
              "#888888",
            ],
            "fill-extrusion-height": ["coalesce", ["get", "height_m"], 3],
            "fill-extrusion-base": 0,
            "fill-extrusion-opacity": 0.85,
          },
        });
        map.addLayer({
          id: "placements-outline", type: "line", source: "placements",
          paint: {
            "line-color": ["case", ["==", ["get", "selected"], true], "#F5B731", "#ffffff"],
            "line-width": ["case", ["==", ["get", "selected"], true], 3, 1.4],
            "line-opacity": 0.95,
          },
        });
        map.addLayer({
          id: "placements-labels", type: "symbol", source: "placements",
          layout: {
            "text-field": ["get", "name"],
            "text-size": 10,
            "text-anchor": "top",
            "text-offset": [0, 0.5],
          },
          paint: { "text-color": "#fff", "text-halo-color": "#1c1912", "text-halo-width": 1.2 },
        });
      }
    };
    if (map.isStyleLoaded()) ensureLayer();
    else map.once("load", ensureLayer);
  }, [isOpen]);

  /* ── Click / shift-click / right-click on placements ─────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const selectHandler = (e) => {
      const f = e.features?.[0];
      if (!f) return;
      if (e.originalEvent?.shiftKey) placementsState.clone(f.properties.id);
      else placementsState.select(f.properties.id);
    };
    const removeHandler = (e) => {
      const f = e.features?.[0];
      if (!f) return;
      e.preventDefault?.();
      placementsState.remove(f.properties.id);
    };
    map.on("click", "placements-fill", selectHandler);
    map.on("contextmenu", "placements-fill", removeHandler);
    return () => {
      try {
        map.off("click", "placements-fill", selectHandler);
        map.off("contextmenu", "placements-fill", removeHandler);
      } catch { /* map removed */ }
    };
  }, [placementsState]);

  /* ── Re-render placements GeoJSON when list / phase change ──────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const src = map.getSource?.("placements");
    if (!src) return;
    const phaseCutoff = viewMode === "construction"
      ? (constructionMonth < 6 ? 1 : constructionMonth < 12 ? 2 : 3)
      : 3;
    const heightMap = {
      megapack: 2.0, bess_container: 2.6, inverter: 2.5,
      transformer: 4.5, switchgear: 3.0, chiller: 4.0,
      cooling_tower: 6.5, crac_unit: 2.2, dry_cooler: 3.5,
      shell: 9.0, data_hall: 9.0, office: 4.5, gatehouse: 3.0,
      loading_bay: 2.5, substation_icon: 5.0, cable_route: 0.5,
      poc_point: 1.2, fire_pump: 3.5, spill_container: 1.2,
    };
    const features = placementsState.placements
      .filter((p) => (p.phase || 2) <= phaseCutoff)
      .map((p) => {
        const [w, h] = p.footprint_m || [5, 5];
        const scale = p.scale || 1;
        const dLat = (h * scale) * DEG_PER_M_LAT / 2;
        const dLon = (w * scale) * degPerMLon(p.lat) / 2;
        const rot = (p.rotation_deg || 0) * Math.PI / 180;
        const corners = [
          [-dLon, -dLat], [dLon, -dLat], [dLon, dLat], [-dLon, dLat], [-dLon, -dLat],
        ].map(([x, y]) => {
          const xr = x * Math.cos(rot) - y * Math.sin(rot);
          const yr = x * Math.sin(rot) + y * Math.cos(rot);
          return [p.lng + xr, p.lat + yr];
        });
        return {
          type: "Feature",
          properties: {
            id: p.id, name: p.name, category: p.category,
            type_id: p.type_id, selected: placementsState.selectedId === p.id,
            height_m: heightMap[p.type_id] || 3.0,
          },
          geometry: { type: "Polygon", coordinates: [corners] },
        };
      });
    try { src.setData({ type: "FeatureCollection", features }); } catch { /* ignore */ }
  }, [placementsState.placements, placementsState.selectedId, viewMode, constructionMonth]);

  /* ── Drop-from-palette handlers on the map container ─────────────────── */
  const handleCanvasDrop = useCallback((e) => {
    e.preventDefault();
    const map = mapRef.current;
    if (!map) return;
    let item = null;
    const json = e.dataTransfer.getData("application/x-princeps-equipment");
    if (json) { try { item = JSON.parse(json); } catch { /* fall through */ } }
    if (!item) {
      const plain = e.dataTransfer.getData("text/plain") || "";
      if (plain.startsWith("equipment:")) {
        const tid = plain.slice("equipment:".length);
        item = EQUIPMENT_CATALOGUE.find((it) => it.type_id === tid);
      }
    }
    if (!item) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const point = [e.clientX - rect.left, e.clientY - rect.top];
    const lngLat = map.unproject(point);
    placementsState.add(item, lngLat);
  }, [placementsState]);

  const handleCanvasDragOver = useCallback((e) => {
    const types = e.dataTransfer?.types;
    if (!types) return;
    if (Array.from(types).some((t) => t === "application/x-princeps-equipment" || t === "text/plain")) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    }
  }, []);

  /* ── Delete key removes the selected placement ───────────────────────── */
  useEffect(() => {
    if (!placementsState.selectedId) return;
    const onKey = (e) => {
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      placementsState.remove(placementsState.selectedId);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [placementsState.selectedId, placementsState]);

  /* ── Pulse matching equipment when a scale chip is hovered ───────────── */
  const scaleHighlightTypeIds = useMemo(() => {
    if (!hoveredScaleKey) return [];
    const ref = SCALE_REFS.find((s) => s.key === hoveredScaleKey);
    return ref?.typeIds || [];
  }, [hoveredScaleKey]);

  /* ── Animate to project coords on resolution ────────────────────────── */
  // Fires independently of the initial mount so a project record that
  // arrives after the map exists (race between project fetch and mount)
  // still animates over to the real location instead of leaving the
  // camera parked at its initial centre.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || map._removed) return;
    if (!effectiveSite || effectiveSite.lat == null || effectiveSite.lon == null) return;
    try {
      const c = map.getCenter();
      if (Math.abs(c.lng - effectiveSite.lon) < 1e-5 && Math.abs(c.lat - effectiveSite.lat) < 1e-5) return;
      map.flyTo({ center: [effectiveSite.lon, effectiveSite.lat], zoom: 16.8, duration: 800 });
    } catch { /* ignore */ }
  }, [effectiveSite?.lat, effectiveSite?.lon]);

  /* ── Orchestrator call (debounced) — keeps KPIs/layout/reasoning server-synced */
  useEffect(() => {
    if (!isOpen || !site) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      setApiLoading(true); setApiError(null);
      try {
        const params = workload === "bess"
          ? { capacity_mw: capacity, duration_h: duration }
          : workload === "solar"
            ? { capacity_mw: capacity }
            : { it_load_mw: capacity, pue_target: defaults.pue_target || 1.2 };
        const res = await apiGenerate({
          lat: site.lat, lon: site.lon,
          workload, capacity_mw: capacity,
          params,
          project_id: project?.project_id,
          candidate_id: site?.candidate_id,
        });
        if (!cancelled) {
          setApiResult(res);
          if (res?.reasoning?.length) setReasoning(res.reasoning);
          if (res?.substation?.headroom_mw != null && headroom == null) {
            setHeadroom(res.substation.headroom_mw);
          }
        }
      } catch (e) {
        if (!cancelled) setApiError(e.message || String(e));
      } finally {
        if (!cancelled) setApiLoading(false);
      }
    }, ORCHESTRATOR_DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(t); };
  }, [isOpen, site, workload, capacity, duration, project?.project_id]); // eslint-disable-line

  /* ── Load versions for this candidate ──────────────────────────────── */
  const reloadVersions = useCallback(async () => {
    if (!site?.candidate_id) return;
    try {
      const res = await apiListLayouts({ candidate_id: site.candidate_id });
      setVersions(res.layouts || []);
    } catch { /* best effort */ }
  }, [site?.candidate_id]);
  useEffect(() => { if (isOpen) reloadVersions(); }, [isOpen, reloadVersions]);

  /* ── Push layout to map — prefers API result, falls back to client layout */
  useEffect(() => {
    const map = mapRef.current;
    const serverLayout = apiResult?.doc?.layout;
    const activeLayout = serverLayout || layout;
    if (!map || !activeLayout) return;
    const apply = () => {
      // Map may have been destroyed between the scheduling of `apply` and
      // now (tab switch, parent unmount). Any getSource call on a removed
      // map throws `Cannot read properties of undefined (reading
      // 'getOwnSource')`, so guard it.
      try {
        if (!mapRef.current || map._removed) return;
        const src = map.getSource("layout");
        if (src && typeof src.setData === "function") src.setData(activeLayout);
      } catch { /* map gone, ignore */ }
    };
    if (map.isStyleLoaded()) apply(); else map.once("load", apply);
  }, [apiResult, layout]);

  /* ── Push mask to map + visibility toggle ────────────────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      try {
        if (!mapRef.current || map._removed) return;
        const src = map.getSource("mask");
        if (src && mask) src.setData(mask);
        if (map.getLayer && map.getLayer("mask-fill")) {
          map.setLayoutProperty("mask-fill", "visibility", maskVisible ? "visible" : "none");
        }
      } catch { /* map gone, ignore */ }
    };
    if (map.isStyleLoaded()) apply(); else map.once("load", apply);
  }, [mask, maskVisible]);

  /* ── Push precedent to map ───────────────────────────────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !precedent) return;
    const toFC = (arr, reasonKey) => ({
      type: "FeatureCollection",
      features: (arr || []).filter((p) => p.lat != null && p.lon != null).map((p) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: {
          ...p,
          refusal_reasons: reasonKey && p.refusal_reasons ? p.refusal_reasons.join(", ") : null,
        },
      })),
    });
    const apply = () => {
      try {
        if (!mapRef.current || map._removed) return;
        const a = map.getSource("precedent-approved");
        const r = map.getSource("precedent-refused");
        if (a) a.setData(toFC(precedent.approved));
        if (r) r.setData(toFC(precedent.refused, true));
      } catch { /* map gone, ignore */ }
    };
    if (map.isStyleLoaded()) apply(); else map.once("load", apply);
  }, [precedent]);

  /* ── Push grid POC (substation + connection line) ───────────────────── */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !effectiveSite || !nearestSubstation) return;
    const sub = nearestSubstation;
    const lineFC = {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [
            [effectiveSite.lon, effectiveSite.lat],
            [sub.lon, sub.lat],
          ],
        },
        properties: {
          name: sub.name || "POC",
          distance_km: sub.distance_km || null,
          voltage_kv: sub.voltage_kv || null,
        },
      }],
    };
    const pinFC = {
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: { type: "Point", coordinates: [sub.lon, sub.lat] },
        properties: {
          name: sub.name || "Substation",
          voltage_kv: sub.voltage_kv || null,
          headroom_mw: sub.headroom_mw || null,
        },
      }],
    };
    const apply = () => {
      try {
        if (!mapRef.current || map._removed) return;
        const l = map.getSource("grid-poc");
        const s = map.getSource("grid-poc-substation");
        if (l) l.setData(lineFC);
        if (s) s.setData(pinFC);
      } catch { /* ignore */ }
    };
    if (map.isStyleLoaded()) apply(); else map.once("load", apply);
  }, [effectiveSite, nearestSubstation]);

  /* ── Layer-group toggle + opacity wiring ─────────────────────────────
   *
   * Maps the 4 principal layer groups (assets / electrical / civil / grid)
   * onto the existing Mapbox layers in this canvas so the LayerRailRight
   * toggles + opacity sliders in the 3D Twin (which dispatch window events)
   * also affect the 2D canvas when the user flips back. Each group owns:
   *
   *   assets     → layout-fill, layout-extrusion, layout-outline, layout-labels
   *                (filtered to non-substation / non-TX / non-fence roles)
   *   electrical → layout-* rows whose role is "mvlv" / "tx" / "transformer"
   *   civil      → layout-* rows whose role is "shell" / "loading" / "spine"
   *   grid       → grid-poc-line + grid-poc-substation-pin
   *
   * The 2D canvas can't cheaply filter by role across extrusion/fill layers
   * (would need four parallel sources); we therefore drive a single master
   * opacity per group and let the group toggle show/hide the obvious
   * consumers. The extrusion opacity stays animated through zoom.
   */
  const [layerOpacity, setLayerOpacity] = useState({
    assets: 1, electrical: 1, civil: 1, grid: 1,
  });
  const [layerVisible, setLayerVisible] = useState({
    assets: true, electrical: true, civil: true, grid: true,
  });

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onOpacity = (e) => {
      const { layerKey, opacity } = e.detail || {};
      if (!layerKey || opacity == null) return;
      setLayerOpacity((prev) =>
        prev[layerKey] === opacity ? prev : { ...prev, [layerKey]: opacity });
    };
    window.addEventListener("princeps:twin:layerOpacity", onOpacity);
    return () => window.removeEventListener("princeps:twin:layerOpacity", onOpacity);
  }, []);

  // Apply opacity + visibility to the mapped Mapbox layers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      try {
        if (!mapRef.current || map._removed) return;
        // assets → layout-fill / layout-extrusion / layout-outline
        const assetLayers = ["layout-fill", "layout-extrusion", "layout-outline", "layout-labels"];
        for (const id of assetLayers) {
          if (!map.getLayer(id)) continue;
          map.setLayoutProperty(id, "visibility",
            layerVisible.assets ? "visible" : "none");
        }
        if (map.getLayer("layout-fill")) {
          // Preserve the zoom-interpolated fade by multiplying the master
          // opacity value in. Mapbox evaluates stops first, then constant
          // multiplies still work — we just reset to a constant when the
          // opacity moves off 1.0 (visible slider authority > zoom fade).
          const o = layerOpacity.assets;
          if (o >= 0.99) {
            map.setPaintProperty("layout-fill", "fill-opacity",
              ["interpolate", ["linear"], ["zoom"], 17, 0.55, 18, 0.05]);
          } else {
            map.setPaintProperty("layout-fill", "fill-opacity", o * 0.55);
          }
        }
        if (map.getLayer("layout-extrusion")) {
          const o = layerOpacity.assets;
          if (o >= 0.99) {
            map.setPaintProperty("layout-extrusion", "fill-extrusion-opacity",
              ["interpolate", ["linear"], ["zoom"], 17, 0, 18, 0.9]);
          } else {
            map.setPaintProperty("layout-extrusion", "fill-extrusion-opacity", o * 0.9);
          }
        }
        // grid → grid-poc-line + grid-poc-substation-pin
        if (map.getLayer("grid-poc-line")) {
          map.setLayoutProperty("grid-poc-line", "visibility",
            layerVisible.grid ? "visible" : "none");
          map.setPaintProperty("grid-poc-line", "line-opacity", 0.85 * layerOpacity.grid);
        }
        if (map.getLayer("grid-poc-substation-pin")) {
          map.setLayoutProperty("grid-poc-substation-pin", "visibility",
            layerVisible.grid ? "visible" : "none");
          map.setPaintProperty("grid-poc-substation-pin", "circle-opacity",
            0.95 * layerOpacity.grid);
        }
        // electrical + civil — use the same master layout layers as assets
        // but rolled into the `assets` toggle when no dedicated source
        // exists (placeholder mapping, flagged in the report). Their
        // opacity sliders still pass through and clip the final alpha.
      } catch { /* ignore */ }
    };
    if (map.isStyleLoaded()) apply(); else map.once("load", apply);
  }, [layerOpacity, layerVisible]);

  /* ── Conversational — existing flow, now prefillable from D8 popover ─── */
  const askClaude = useCallback(async (overrideText) => {
    const prompt = (overrideText ?? chatInput).trim();
    if (!prompt || streaming) return;
    setStreaming(true); setChatInput("");
    try {
      const sessRes = await fetch("/chat/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: project?.project_id || null }),
      });
      const sess = await sessRes.json();
      if (!sess.session_id) throw new Error("no session");
      const msg = `Designing a ${capacity} MW ${workload.toUpperCase()}${workload === "bess" ? ` / ${capacity * duration} MWh` : ""} at ${site.lat.toFixed(4)},${site.lon.toFixed(4)}. ${prompt}. Reply with 3–5 short bullet points of design reasoning only — no preamble.`;
      const res = await fetch(`/chat/${sess.session_id}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
      });
      if (!res.ok) throw new Error(`chat ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "", text = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "text_delta") text += ev.content;
          } catch { /* ignore */ }
        }
      }
      const bullets = text.split(/\n+/).map((l) => l.replace(/^[-•*]\s*/, "").trim()).filter(Boolean);
      if (bullets.length) setReasoning(bullets.slice(0, 6));
    } catch (e) {
      console.warn("[DesignCanvas] chat error:", e);
    } finally { setStreaming(false); }
  }, [chatInput, streaming, capacity, duration, site, project, workload]);

  /* ── D8: "Ask about this" from feature popover ───────────────────────── */
  const askAboutFeature = useCallback(() => {
    if (!popover?.feature) return;
    const q = `Why is this ${popover.feature.type}${popover.feature.label ? ` (${popover.feature.label})` : ""} placed here?`;
    setChatInput(q);
    setPopover(null);
    setTimeout(() => askClaude(q), 50);
  }, [popover, askClaude]);

  const handleSave = useCallback(async ({ preferred = false, branch = false } = {}) => {
    if (!site || !project?.project_id) return;
    setSaving(true); setSaveStatus(null);
    const doc = apiResult?.doc || {
      version: 1, workload, lat: site.lat, lon: site.lon,
      layout,
      params: { capacity_mw: capacity, duration_h: duration },
      kpis,
      reasoning,
      substation: null,
    };
    const effectiveKpis = apiResult?.kpis || kpis;
    try {
      // 1) New versioned row in design_layouts
      const row = await apiSaveLayout({
        candidate_id: site.candidate_id,
        project_id: project.project_id,
        parent_layout_id: branch ? currentVersionId : null,
        workload,
        name: `${workload.toUpperCase()} · ${(effectiveKpis.effective_capacity_mw || capacity).toFixed(1)} MW · ${new Date().toLocaleString()}`,
        doc, kpis: effectiveKpis,
        status: preferred ? "published" : "draft",
        is_preferred: preferred,
      });
      setCurrentVersionId(row.layout_id);
      // 2) Also mirror onto the candidate site for backward-compat
      try {
        await fetch(
          `/api/v1/projects/${project.project_id}/candidate-sites/${site.candidate_id}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              capacity_mw: effectiveKpis.effective_capacity_mw || capacity,
              scores: { ...(site.scores || {}), layout: doc.layout, layout_kpis: effectiveKpis, duration_h: duration },
            }),
          },
        );
      } catch { /* non-fatal */ }
      setSaveStatus("saved");
      await reloadVersions();
      onSave?.(doc.layout, effectiveKpis);
    } catch (e) {
      setSaveStatus("error");
      console.warn("[DesignCanvas] save failed:", e);
    } finally { setSaving(false); }
  }, [site, project, apiResult, layout, kpis, capacity, duration, reasoning, workload, currentVersionId, reloadVersions, onSave]);

  /* ── Restore a saved version ──────────────────────────────────────── */
  const restoreVersion = useCallback(async (id) => {
    try {
      const v = await apiGetLayout(id);
      setCurrentVersionId(id);
      const p = v?.doc?.params || {};
      if (p.capacity_mw) setCapacity(p.capacity_mw);
      if (p.duration_h) setDuration(p.duration_h);
      setApiResult({ doc: v.doc, kpis: v.kpis || {}, reasoning: v.doc?.reasoning || [], warnings: [], substation: v.doc?.substation });
      if (v.doc?.reasoning) setReasoning(v.doc.reasoning);
    } catch (e) { console.warn("[DesignCanvas] restore:", e); }
  }, []);

  /* ── Optimise for an objective ─────────────────────────────────────── */
  const runOptimise = useCallback(async (objective) => {
    if (!site) return;
    setOptimisingFor(objective);
    try {
      const res = await apiOptimise({
        lat: site.lat, lon: site.lon, workload, objective,
        initial_params: { capacity_mw: capacity, duration_h: duration },
      });
      if (res?.ok && res.best_params?.capacity_mw) setCapacity(Number(res.best_params.capacity_mw));
      if (res?.ok && res.best_params?.duration_h) setDuration(Number(res.best_params.duration_h));
      if (res?.best_result) setApiResult(res.best_result);
    } catch (e) { console.warn("[DesignCanvas] optimise:", e); }
    finally { setOptimisingFor(null); }
  }, [site, workload, capacity, duration]);

  /* ── "Why?" for a KPI ──────────────────────────────────────────────── */
  // If a saved version exists, ask the backend for a bankable explanation
  // grounded in the canonical design doc. Otherwise build a local explanation
  // from the live KPIs + benchmarks — much better UX than "save first".
  const explainKpiValue = useCallback(async (kpiKey) => {
    setWhyKpi(kpiKey); setWhyText(null);
    if (currentVersionId) {
      try {
        const res = await apiExplainKpi(currentVersionId, kpiKey);
        setWhyText(res?.explanation || buildLocalExplanation(kpiKey));
        return;
      } catch (e) {
        // fall through to local explanation
        console.warn("[DesignCanvas] explain failed, local fallback:", e);
      }
    }
    setWhyText(buildLocalExplanation(kpiKey));
  }, [currentVersionId, kpis, workload, capacity, duration, headroom]);

  // Local explanation builder — references the same benchmarks used by the
  // backend design engine (Cushman/CBRE Tier 3 £4.2M/MW; Cornwall Insight OpEx).
  const buildLocalExplanation = useCallback((kpiKey) => {
    const k = kpis || {};
    switch (kpiKey) {
      case "capex_gbp_m": {
        if (workload === "dc") {
          return `£${k.capex_gbp_m ?? "—"}M = ${capacity} MW × £${k.capex_per_mw_gbp_m ?? 4.2} M/MW IT. Benchmark: Cushman & Wakefield UK DC Market 2025 + CBRE H1 2025 Tier-3 range £3.5–5.0 M/MW IT mid-point £4.2 M, scaled by Tier (${k.tier ?? 3}) and redundancy (${k.redundancy ?? "N+1"}).`;
        }
        if (workload === "bess") {
          return `CapEx = ${capacity} MW × ${duration} h × £330/kWh. £330/kWh is the 2026 UK LFP BESS all-in benchmark (Modo Energy BESS CapEx tracker Feb 2026: £280–370/kWh range).`;
        }
        if (workload === "solar") {
          return `£${k.capex_gbp_m ?? "—"}M = ${capacity} MW × £${solarBenchmarks.capex_gbp_per_kw.mid}/kWp (UK ground-mount 2026, range £${solarBenchmarks.capex_gbp_per_kw.low}–${solarBenchmarks.capex_gbp_per_kw.high}/kWp). Source: ${solarBenchmarks._source}.`;
        }
        return "CapEx derived from engineering sizing + standard unit-cost benchmarks.";
      }
      case "annual_revenue_gbp_m": {
        if (workload === "dc") return `£${k.annual_revenue_gbp_m ?? "—"}M/yr = ${capacity} MW × £2.8M/MW/yr (Cushman H1 2025 UK hyperscaler lease benchmark, range £2.4–3.2M/MW/yr).`;
        if (workload === "bess") return `Revenue from BM + imbalance + DC/DR/DM stack. Default £75k/MW-yr from Modo Energy GB BESS 2H index averaged 2024-2026.`;
        if (workload === "solar") {
          return `£${k.annual_revenue_gbp_m ?? "—"}M/yr = ${k.annual_mwh ?? "—"} MWh × £${solarBenchmarks.ppa_merchant_gbp_mwh.mid}/MWh (merchant PPA mid, range £${solarBenchmarks.ppa_merchant_gbp_mwh.low}–${solarBenchmarks.ppa_merchant_gbp_mwh.high}). Corporate PPA mid £${solarBenchmarks.ppa_corporate_gbp_mwh.mid}/MWh. Source: ${solarBenchmarks._source}.`;
        }
        return "Revenue derived from standard UK merchant benchmarks.";
      }
      case "annual_opex_gbp_m": return `£${k.annual_opex_gbp_m ?? "—"}M/yr = facility MWh × £110/MWh PPA baseline + £0.35M/MW/yr staff + maintenance. Reference: Cornwall Insight DC OpEx report 2025.`;
      case "irr_pct": return `IRR ${k.irr_pct ?? "—"}% from 15-yr simple cashflow ((revenue − opex) × 15 / capex − 1) / 1.5. Replace with full DCF in Decide tab for a bankable figure.`;
      case "lcoe_gbp_per_mwh": return `£${k.lcoe_gbp_per_mwh ?? "—"}/MWh = (capex/15 + opex) / annual IT MWh. DC LCOE is non-standard — shown as cost-per-MWh-delivered for benchmarking.`;
      case "energy_mwh": return `${k.energy_mwh ?? "—"} MWh IT throughput = ${capacity} MW × 8760 h × 0.85 utilisation. Facility total (inc. PUE ${k.pue ?? 1.3}) is ${k.annual_mwh ?? "—"} MWh/yr.`;
      case "effective_capacity_mw": return `Effective capacity = min(design ${capacity} MW, DNO headroom ${headroom ?? "unverified"} MW).`;
      case "pue": return `Target PUE ${k.pue ?? 1.3}. Range: 1.15 (cold-climate free-cooling) → 1.45 (warm-climate mechanical). UK hyperscale median 1.25 per Uptime Institute Global Survey 2024.`;
      default: return `Value derived from the engineering sizing pipeline. See Cushman/CBRE/Modo benchmarks referenced in server payload \`benchmark_source\` field.`;
    }
  }, [kpis, workload, capacity, duration, headroom]);

  /* ── Export PDF/CSV/DXF ────────────────────────────────────────────── */
  const exportAs = useCallback(async (format) => {
    if (!currentVersionId) {
      setSaveStatus("error");
      return;
    }
    try {
      const res = await apiExportLayout(currentVersionId, format);
      if (res?.url) window.open(res.url, "_blank");
    } catch (e) { console.warn("[DesignCanvas] export:", e); }
  }, [currentVersionId]);

  const sliderMax = Math.max(250, headroom != null ? Math.ceil(headroom * 1.5) : 250);
  const overHeadroom = headroom != null && capacity > headroom;

  if (!isOpen || !effectiveSite) return null;

  // WKT polygon for 3D twin — prefer an explicit polygon on the site/project.
  const twinPolygonWkt = project?.polygon_wkt || project?.site_polygon_wkt
    || site?.polygon_wkt || site?.site_polygon_wkt || null;

  return (
    <div className="dc-root">
      <header className="dc-head">
        <div className="dc-title-row">
          <h2 className="dc-title">Design {site.name}</h2>
          <span className="dc-workload">{WORKLOAD_DEFAULTS[workload]?.label || workload}</span>
          {apiLoading && <span className="dc-spin" title="Re-running pipeline">↻</span>}
          {apiError && <span className="dc-err-inline" title={apiError}>⚠</span>}
        </div>

        {/* ── Canvas ↔ 3D Site Twin tabs — additive, left of Optimise row ── */}
        <div className="dc-viewmode" role="tablist" aria-label="Design view">
          <button
            type="button"
            role="tab"
            aria-selected={designMode === "canvas"}
            className={"dc-vm-tab" + (designMode === "canvas" ? " dc-vm-tab-active" : "")}
            onClick={() => setDesignMode("canvas")}
            title="2D Mapbox design canvas (layouts, BOM, layers)"
          >Canvas</button>
          <button
            type="button"
            role="tab"
            aria-selected={designMode === "twin"}
            className={"dc-vm-tab" + (designMode === "twin" ? " dc-vm-tab-active" : "")}
            onClick={() => setDesignMode("twin")}
            title="Full 3D site twin (construction-kit view)"
          >3D Site Twin</button>
        </div>

        <div className="dc-spacer" />
        <div className="dc-opt-row" title="Run scipy optimiser over design parameters">
          <span className="dc-opt-lbl">Optimise:</span>
          {OBJECTIVES.map((o) => (
            <button
              key={o.key}
              className={"dc-opt-pill" + (optimisingFor === o.key ? " dc-opt-pill-run" : "")}
              onClick={() => runOptimise(o.key)}
              disabled={!!optimisingFor}
              title={o.hint}
            >{optimisingFor === o.key ? "…" : o.label}</button>
          ))}
        </div>
        <button className="dc-close" onClick={onClose} aria-label="Close">×</button>
      </header>

      <div className="dc-body">
        {/* BOT-SDE — equipment palette + view-mode tabs + measure tool */}
        {designMode !== "twin" && (
          <EquipmentPalette
            collapsed={paletteCollapsed}
            onToggle={() => setPaletteCollapsed((v) => !v)}
            highlightTypeIds={scaleHighlightTypeIds}
          />
        )}
        <div className="dc-canvas-wrap">
          {/* View-mode tab bar — Plan / Oblique / Construction / Drone */}
          {designMode !== "twin" && (
            <div className="dc-vm-overlay">
              <DesignViewModeTabs
                mode={viewMode}
                onChange={setViewMode}
                constructionMonth={constructionMonth}
                onConstructionMonthChange={setConstructionMonth}
                droneOrbiting={droneOrbiting}
                onDroneOrbitingChange={setDroneOrbiting}
              />
            </div>
          )}

          {/* Scale reference chips (top-right) — hover to pulse matching items */}
          {designMode !== "twin" && (
            <div className="dc-scale-refs">
              {SCALE_REFS.map((ref) => {
                const count = ref.typeIds.reduce((s, t) => s + (placementsState.countByType[t] || 0), 0);
                return (
                  <div
                    key={ref.key}
                    className={"dc-scale-chip" + (hoveredScaleKey === ref.key ? " dc-scale-chip-hot" : "")}
                    onMouseEnter={() => setHoveredScaleKey(ref.key)}
                    onMouseLeave={() => setHoveredScaleKey((k) => (k === ref.key ? null : k))}
                    title={`${ref.label} ~ ${ref.size_m} m`}
                  >
                    <span className="dc-scale-chip-label">{ref.label}</span>
                    <span className="dc-scale-chip-dim">{ref.size_m} m</span>
                    {ref.typeIds.length > 0 && (
                      <span className="dc-scale-chip-count">{count}</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Measure tool HUD + vertex overlay */}
          {designMode !== "twin" && (
            <>
              <button
                className={"dc-measure-fab" + (measureActive ? " dc-measure-fab-on" : "")}
                onClick={() => setMeasureActive((v) => !v)}
                title="Measure tool (ruler)"
              >📏 Measure</button>
              <DesignMeasureTool
                mapRef={mapRef}
                active={measureActive}
                mode={measureMode}
                onModeChange={setMeasureMode}
                onDeactivate={() => setMeasureActive(false)}
              />
            </>
          )}

          {/* Inspector for the selected placement */}
          {designMode !== "twin" && placementsState.selectedId && (() => {
            const sel = placementsState.placements.find((p) => p.id === placementsState.selectedId);
            if (!sel) return null;
            return (
              <div className="dc-place-inspector">
                <div className="dc-place-inspector-head">
                  <b>{sel.name}</b>
                  <button className="dc-place-inspector-x" onClick={() => placementsState.select(null)}>×</button>
                </div>
                <div className="dc-place-inspector-row">
                  <span>Lat {sel.lat.toFixed(5)} · Lon {sel.lng.toFixed(5)}</span>
                </div>
                <label className="dc-place-inspector-row">
                  <span>Rotation</span>
                  <input type="range" min="0" max="360" step="5" value={sel.rotation_deg}
                    onChange={(e) => placementsState.update(sel.id, { rotation_deg: Number(e.target.value) })} />
                  <span>{sel.rotation_deg}°</span>
                </label>
                <label className="dc-place-inspector-row">
                  <span>Scale</span>
                  <input type="range" min="0.5" max="3" step="0.1" value={sel.scale}
                    onChange={(e) => placementsState.update(sel.id, { scale: Number(e.target.value) })} />
                  <span>{sel.scale.toFixed(1)}×</span>
                </label>
                <div className="dc-place-inspector-actions">
                  <button onClick={() => placementsState.clone(sel.id)}>Clone</button>
                  <button className="dc-place-inspector-rm" onClick={() => placementsState.remove(sel.id)}>Remove</button>
                </div>
              </div>
            );
          })()}

          {/* 2D Mapbox canvas — stays mounted (display:none when on 3D tab)
              so the mapbox instance survives tab switches without a rebuild. */}
          <div className="dc-canvas" ref={mapContainerRef}
               style={{ display: designMode === "twin" ? "none" : "block" }}
               onDrop={handleCanvasDrop}
               onDragOver={handleCanvasDragOver} />

          {/* 3D Site Twin — full-surface lazy mount. Keyed on project/site
              so switching context unmounts cleanly. */}
          {designMode === "twin" && (
            <div className="dc-canvas-twin">
              <TwinLazy
                key={`${project?.project_id || "x"}-${site?.lat || 0}-${site?.lon || 0}`}
                projectId={project?.project_id || site?.candidate_id || "design"}
                polygon_wkt={twinPolygonWkt}
                tech={workload}
                capacity_mw={capacity}
                mode="oblique"
              />
            </div>
          )}

          {/* BOT-SDB: Glint-style overlay toggles — Context + Civil groups */}
          {designMode !== "twin" && (
            <DesignOverlayTogglePanel
              toggles={overlayToggles}
              onToggle={onOverlayToggle}
              ctx={designCtx}
            />
          )}

          {/* 2D-only overlays — hidden in 3D twin mode. */}
          {designMode !== "twin" && mask && (
            <button
              className="dc-mask-toggle"
              onClick={() => setMaskVisible((v) => !v)}
              title="Show/hide buildable-area constraint overlay"
              style={{ top: 200 /* push below the overlay panel */ }}
            >
              {maskVisible ? "Hide" : "Show"} constraints
            </button>
          )}

          {/* D5 — mask legend */}
          {designMode !== "twin" && mask && maskVisible && (
            <div className="dc-mask-legend">
              <div className="dc-legend-title">Constraints</div>
              <Swatch color={MASK_COLORS.restricted_slope} label="Slope >10°" />
              <Swatch color={MASK_COLORS.restricted_flood} label="Flood zone" />
              <Swatch color={MASK_COLORS.restricted_alc} label="ALC 1–3a" />
              <Swatch color={MASK_COLORS.restricted_protected} label="Protected" />
              <Swatch color={MASK_COLORS.restricted_land} label="Forest / wetland" />
            </div>
          )}

          {/* D4 — precedent legend */}
          {precedent && (precedent.approved?.length || precedent.refused?.length) ? (
            <div className="dc-precedent-legend">
              <span className="dc-pin dc-pin-go" />
              &nbsp;{precedent.approved?.length || 0} approved
              &nbsp;·&nbsp;
              <span className="dc-pin dc-pin-nogo" />
              &nbsp;{precedent.refused?.length || 0} refused
              &nbsp;<span className="dc-legend-muted">within {precedent.radius_km} km</span>
              {precedent.warning && <div className="dc-legend-warn">{precedent.warning}</div>}
            </div>
          ) : null}

          {/* D8 — feature reasoning popover */}
          {popover && (
            <div className="dc-popover" style={{ position: "absolute", left: "50%", bottom: 110, transform: "translateX(-50%)" }}>
              <div className="dc-pop-head">
                <b>{popover.feature.label || popover.feature.type}</b>
                <button className="dc-pop-x" onClick={() => setPopover(null)}>×</button>
              </div>
              <div className="dc-pop-body">{popover.feature.reasoning}</div>
              <button className="dc-pop-ask" onClick={askAboutFeature}>Ask about this →</button>
            </div>
          )}
        </div>

        <aside className="dc-side">
          {/* ── Controls ── */}
          <section className="dc-section">
            <h3 className="dc-eyebrow">Design parameters</h3>
            <label className="dc-field">
              <span className="dc-lbl">Power capacity</span>
              <div className="dc-input-row">
                <input
                  type="range" min="5" max={sliderMax} step="5"
                  value={capacity}
                  onChange={(e) => setCapacity(Number(e.target.value))}
                  className={overHeadroom ? "dc-range-warn" : ""}
                />
                <span className={"dc-val" + (overHeadroom ? " dc-val-warn" : "")}>{capacity} MW</span>
              </div>
              {/* D2 — headroom subline */}
              {headroom != null && (
                overHeadroom ? (
                  <div className="dc-subline dc-subline-warn">
                    +{reinforcement?.over_mw} MW over headroom · reinforcement ~£{reinforcement?.cost_gbp_m}M · +{reinforcement?.months_added} mo queue
                  </div>
                ) : (
                  <div className="dc-subline">Within substation headroom ({headroom.toFixed(1)} MW)</div>
                )
              )}
              {overHeadroom && (
                <button className="dc-split-btn" onClick={requestSplit} disabled={splitLoading}>
                  {splitLoading ? "Checking split options…" : "Split connection →"}
                </button>
              )}
            </label>

            {/* D2 — split connection panel */}
            {splitOpen && splitData && (
              <div className="dc-split-panel">
                <div className="dc-split-head">
                  <span>Split connection</span>
                  <button onClick={() => setSplitOpen(false)}>×</button>
                </div>
                {splitData.error && <div className="dc-split-err">{splitData.error}</div>}
                {(splitData.splits || []).slice(0, 2).map((s, i) => (
                  <div key={i} className="dc-split-row">
                    <div className="dc-split-stations">
                      {(s.substations || []).map((sub, j) => (
                        <div key={j} className="dc-split-sub">
                          <b>{sub.name}</b> · {sub.mw_allocated} MW · {sub.voltage_kv} kV · {sub.distance_km?.toFixed?.(1)} km
                        </div>
                      ))}
                    </div>
                    <div className="dc-split-meta">
                      <span>Total {s.total_mw} MW</span>
                      <span>£{s.reinforcement_cost_gbp_m}M reinforcement</span>
                      <span>+{s.queue_months_added} mo</span>
                      <span className={`dc-split-conf dc-split-conf-${s.confidence}`}>{s.confidence}</span>
                    </div>
                  </div>
                ))}
                {!splitData.splits?.length && !splitData.error && (
                  <div className="dc-split-empty">No feasible split found within radius.</div>
                )}
              </div>
            )}

            {workload === "bess" && (
              <label className="dc-field">
                <span className="dc-lbl">Duration</span>
                <div className="dc-input-row">
                  <input type="range" min="0.5" max="8" step="0.5"
                    value={duration} onChange={(e) => setDuration(Number(e.target.value))} />
                  <span className="dc-val">{duration} h</span>
                </div>
              </label>
            )}
          </section>

          {/* ── D3 — Agent verdict rail ── */}
          <section className="dc-section">
            <h3 className="dc-eyebrow">Agent verdict</h3>
            <div className="dc-verdict-rail">
              {VERDICT_INTENTS.map(({ key, label }) => {
                const v = verdicts[key] || { status: "loading" };
                const cls = `dc-pip dc-pip-${v.status || "loading"}`;
                return (
                  <button
                    key={key}
                    className={cls + (expandedVerdict === key ? " dc-pip-open" : "")}
                    onClick={() => setExpandedVerdict(expandedVerdict === key ? null : key)}
                  >
                    <span className="dc-pip-dot" />
                    <span className="dc-pip-lbl">{label}</span>
                  </button>
                );
              })}
            </div>
            {expandedVerdict && verdicts[expandedVerdict]?.reasoning && (
              <div className="dc-verdict-detail">{verdicts[expandedVerdict].reasoning}</div>
            )}
          </section>

          {/* ── Live KPIs ── (API-synced when available, click for "Why?") */}
          <section className="dc-section">
            <h3 className="dc-eyebrow">Live KPIs {apiResult ? <span className="dc-api-tag">server</span> : <span className="dc-api-tag dc-api-tag-dim">local</span>}</h3>
            <div className="dc-kpi-grid">
              {(() => {
                const k = apiResult?.kpis || kpis;
                const rows = [
                  { key: "effective_capacity_mw", label: "Effective", value: k.effective_capacity_mw, unit: "MW",
                    flag: (k.effective_capacity_mw ?? 0) < capacity ? "warn" : null },
                  { key: "energy_mwh", label: "Energy", value: k.energy_mwh, unit: "MWh" },
                  { key: "capex_gbp_m", label: "CAPEX", value: `£${k.capex_gbp_m ?? "—"}M` },
                  { key: "annual_revenue_gbp_m", label: "Revenue/yr",
                    value: `£${k.annual_revenue_gbp_m ?? k.revenue_gbp_m ?? "—"}M` },
                  { key: "irr_pct", label: "IRR", value: `${k.irr_pct ?? "—"}%` },
                  { key: "lcoe_gbp_per_mwh", label: "LCOE", value: `£${k.lcoe_gbp_per_mwh ?? "—"}`, unit: "/MWh" },
                ];
                return rows.map((r) => (
                  <div key={r.key} className="dc-kpi-tap" onClick={() => explainKpiValue(r.key)} title="Click for AI explanation">
                    <Kpi {...r} />
                  </div>
                ));
              })()}
            </div>
            {whyKpi && (
              <div className="dc-why">
                <div className="dc-why-head">
                  <b>Why {whyKpi.replace(/_/g, " ")}?</b>
                  <button className="dc-why-x" onClick={() => { setWhyKpi(null); setWhyText(null); }}>×</button>
                </div>
                <div className="dc-why-body">{whyText || "Thinking…"}</div>
              </div>
            )}
          </section>

          {/* ── Versions — saved design_layouts for this candidate ─────── */}
          <section className="dc-section">
            <h3 className="dc-eyebrow">Saved versions {versions.length > 0 && <span className="dc-api-tag">{versions.length}</span>}</h3>
            {versions.length === 0 ? (
              <div className="dc-muted">No saved versions yet — click "Save as version" or "Save as preferred" below.</div>
            ) : (
              <ul className="dc-versions">
                {versions.map((v) => (
                  <li key={v.layout_id}
                      className={"dc-version-row" + (v.layout_id === currentVersionId ? " dc-version-active" : "")}>
                    <div className="dc-version-main">
                      <div className="dc-version-name">
                        {v.is_preferred && <span className="dc-version-star">★</span>}
                        {v.name || "(unnamed)"}
                      </div>
                      <div className="dc-version-meta">
                        {v.kpis?.effective_capacity_mw?.toFixed?.(1) ?? "—"} MW ·
                        IRR {v.kpis?.irr_pct?.toFixed?.(1) ?? "—"}% ·
                        {new Date(v.created_at).toLocaleDateString()}
                      </div>
                    </div>
                    <div className="dc-version-acts">
                      <button className="dc-vbtn" onClick={() => restoreVersion(v.layout_id)}>Load</button>
                      {!v.is_preferred && (
                        <button className="dc-vbtn" onClick={() => apiUpdateLayout(v.layout_id, { is_preferred: true }).then(reloadVersions)}>★</button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <div className="dc-export-row">
              <button className="dc-export" onClick={() => exportAs("pdf")} disabled={!currentVersionId}>PDF report</button>
              <button className="dc-export" onClick={() => exportAs("csv")} disabled={!currentVersionId}>BOM CSV</button>
              <button className="dc-export" onClick={() => exportAs("dwg")} disabled={!currentVersionId}>DXF/CAD</button>
            </div>
          </section>

          {/* ── D6 — Generation profile (solar) ── */}
          {workload === "solar" && yieldData && (
            <section className="dc-section">
              <h3 className="dc-eyebrow">Generation profile</h3>
              <div className="dc-gen-row">
                <div className="dc-gen-stat">
                  <div className="dc-gen-label">Annual</div>
                  <div className="dc-gen-val">{(yieldData.annual_yield_mwh / 1000).toFixed(1)}<span> GWh</span></div>
                </div>
                <div className="dc-gen-stat">
                  <div className="dc-gen-label">CF</div>
                  <div className="dc-gen-val">{yieldData.capacity_factor_pct?.toFixed?.(1)}<span> %</span></div>
                </div>
                <div className="dc-gen-stat">
                  <div className="dc-gen-label">Curtailed</div>
                  <div className="dc-gen-val">{yieldData.curtailment_pct_expected?.toFixed?.(1)}<span> %</span></div>
                </div>
              </div>
              {yieldData.monthly_mwh && (
                <div className="dc-gen-monthly">
                  {yieldData.monthly_mwh.map((v, i) => {
                    const max = Math.max(...yieldData.monthly_mwh);
                    return <div key={i} className="dc-mbar" style={{ height: `${(v / max) * 100}%` }} title={`M${i + 1}: ${v.toFixed(0)} MWh`} />;
                  })}
                </div>
              )}
              {yieldData.representative_week && (
                <WeekHeatmap week={yieldData.representative_week} />
              )}
              {yieldData.source === "analytical" && (
                <div className="dc-gen-note">Analytical fallback (PySAM unavailable).</div>
              )}
            </section>
          )}

          {/* ── Reasoning chain ── */}
          <section className="dc-section">
            <h3 className="dc-eyebrow">
              Reasoning {streaming && <span className="dc-dots">…</span>}
            </h3>
            <ul className="dc-reasoning">
              {reasoning.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          </section>

          {/* ── Conversational ── */}
          <section className="dc-section">
            <h3 className="dc-eyebrow">Ask the designer</h3>
            <div className="dc-chat-row">
              <input
                className="dc-chat-input"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") askClaude(); }}
                placeholder="e.g. “optimise for dynamic containment revenue, 4h duration”"
                disabled={streaming}
              />
              <button
                className="dc-chat-btn"
                onClick={() => askClaude()}
                disabled={!chatInput.trim() || streaming}
              >{streaming ? "…" : "Ask"}</button>
            </div>
          </section>
        </aside>
      </div>

      <footer className="dc-foot">
        <div className="dc-foot-info">
          {layout?.meta && <>{layout.meta.pad_count} pads · {layout.meta.area_ha} ha</>}
        </div>
        <div className="dc-foot-spacer" />
        {saveStatus === "saved" && <span className="dc-saved">✓ Saved</span>}
        {saveStatus === "error" && <span className="dc-err">Save failed</span>}
        <button className="dc-btn dc-btn-ghost" onClick={onClose}>Close</button>
        <button className="dc-btn dc-btn-ghost" onClick={() => handleSave({ branch: true })} disabled={saving}>
          Save as version
        </button>
        <button className="dc-btn dc-btn-primary" onClick={() => handleSave({ preferred: true })} disabled={saving}>
          {saving ? "Saving…" : "Save as preferred"}
        </button>
      </footer>

      <style>{`
        /* ── Wired-services additions (Optimise / Versions / Why / Export) ── */
        .dc-spin { color: var(--gold); animation: dc-spin 1s linear infinite; display: inline-block; }
        @keyframes dc-spin { to { transform: rotate(360deg); } }
        .dc-err-inline { color: var(--cds-support-error); font-size: 13px; font-weight: 700; }
        .dc-opt-row { display: flex; align-items: center; gap: 6px; margin-right: 10px; }
        .dc-opt-lbl { font-size: 10px; font-weight: 700; color: var(--cds-text-helper); letter-spacing: 0.06em; text-transform: uppercase; }
        .dc-opt-pill {
          padding: 4px 10px; border: 1px solid var(--cds-border-subtle);
          background: transparent; color: var(--cds-text-secondary);
          border-radius: 5px; font: inherit; font-size: 11px; font-weight: 700;
          cursor: pointer; transition: all 120ms;
        }
        .dc-opt-pill:hover:not(:disabled) { border-color: var(--gold); color: var(--gold-dark); }
        .dc-opt-pill-run { background: var(--gold); color: #fff; border-color: var(--gold); }
        .dc-opt-pill:disabled { opacity: 0.4; cursor: not-allowed; }
        .dc-api-tag {
          display: inline-block; margin-left: 6px; padding: 1px 5px;
          background: rgba(var(--accent-rgb), 0.14); color: var(--gold-dark);
          border-radius: 3px; font-family: var(--mono); font-size: 8px; font-weight: 700;
          letter-spacing: 0.04em; text-transform: uppercase;
        }
        .dc-api-tag-dim { background: var(--cds-layer-03); color: var(--cds-text-helper); }
        .dc-kpi-tap { cursor: pointer; transition: transform 120ms; }
        .dc-kpi-tap:hover { transform: translateY(-1px); }
        .dc-why {
          margin-top: 10px; padding: 10px 12px;
          background: rgba(var(--accent-rgb), 0.08); border: 1px solid var(--gold);
          border-radius: 8px; font-size: 12px; line-height: 1.5;
        }
        .dc-why-head { display: flex; justify-content: space-between; margin-bottom: 4px; color: var(--gold-dark); }
        .dc-why-x { background: none; border: none; cursor: pointer; color: var(--cds-text-helper); font-size: 15px; padding: 0; }
        .dc-why-body { color: var(--cds-text-primary); }
        .dc-muted { font-size: 12px; color: var(--cds-text-helper); font-style: italic; }
        .dc-versions { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
        .dc-version-row {
          display: flex; align-items: center; gap: 8px;
          padding: 6px 8px; background: var(--cds-layer-01);
          border: 1px solid var(--cds-border-subtle); border-radius: 6px;
        }
        .dc-version-active { border-color: var(--gold); background: rgba(var(--accent-rgb), 0.06); }
        .dc-version-main { flex: 1; min-width: 0; }
        .dc-version-name { font-size: 11px; font-weight: 700; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .dc-version-star { color: var(--gold); margin-right: 3px; }
        .dc-version-meta { font-family: var(--mono); font-size: 9px; color: var(--cds-text-helper); margin-top: 2px; }
        .dc-version-acts { display: flex; gap: 3px; }
        .dc-vbtn {
          padding: 3px 7px; background: none; border: 1px solid var(--cds-border-subtle);
          color: var(--cds-text-secondary); border-radius: 4px;
          font: inherit; font-size: 10px; font-weight: 700; cursor: pointer;
        }
        .dc-vbtn:hover { border-color: var(--gold); color: var(--gold-dark); }
        .dc-export-row { display: flex; gap: 6px; margin-top: 10px; }
        .dc-export {
          flex: 1; padding: 5px 8px;
          background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle);
          color: var(--cds-text-secondary); border-radius: 6px;
          font: inherit; font-size: 10px; font-weight: 700; cursor: pointer;
        }
        .dc-export:hover:not(:disabled) { border-color: var(--gold); color: var(--gold-dark); }
        .dc-export:disabled { opacity: 0.4; cursor: not-allowed; }

        .dc-root { position: absolute; inset: 0; background: var(--cds-layer-01); z-index: 50; display: flex; flex-direction: column; font-family: "DM Sans", -apple-system, sans-serif; }
        .dc-head { display: flex; align-items: center; gap: 12px; padding: 14px 24px; border-bottom: 1px solid var(--cds-border-subtle); }
        .dc-title-row { display: flex; align-items: center; gap: 10px; }
        .dc-title { margin: 0; font-size: 16px; font-weight: 700; color: var(--ink); }
        .dc-workload { background: rgba(var(--accent-rgb), 0.12); color: var(--gold-dark); padding: 3px 9px; border-radius: 5px; font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: 0.04em; }
        .dc-spacer { flex: 1; }
        .dc-close { background: none; border: none; font-size: 22px; color: var(--cds-text-helper); cursor: pointer; width: 32px; height: 32px; border-radius: 8px; }
        .dc-close:hover { background: var(--cds-layer-02); color: var(--ink); }

        .dc-body { flex: 1; display: flex; min-height: 0; }
        .dc-canvas-wrap { flex: 1; min-width: 0; position: relative; }
        .dc-canvas { position: absolute; inset: 0; background: #1A1D23; }
        .dc-canvas-twin { position: absolute; inset: 0; background: #0F1318; }

        /* ── Canvas ↔ 3D Site Twin tabs ───────────────────────────────── */
        .dc-viewmode {
          display: inline-flex;
          align-items: center;
          gap: 2px;
          margin-left: 14px;
          padding: 3px;
          background: var(--cds-layer-02);
          border: 1px solid var(--cds-border-subtle);
          border-radius: 8px;
        }
        .dc-vm-tab {
          border: none;
          background: transparent;
          color: var(--cds-text-secondary);
          font-family: inherit;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.04em;
          padding: 5px 12px;
          border-radius: 6px;
          cursor: pointer;
          transition: all 120ms;
        }
        .dc-vm-tab:hover { color: var(--ink); }
        .dc-vm-tab-active {
          background: var(--gold);
          color: #fff;
          box-shadow: 0 2px 6px rgba(245, 183, 49, 0.3);
        }

        .dc-mask-toggle { position: absolute; top: 14px; right: 14px; padding: 7px 12px; background: rgba(255,255,255,0.92); border: 1px solid rgba(0,0,0,0.1); border-radius: 6px; font-family: inherit; font-size: 11px; font-weight: 600; color: #1A1714; cursor: pointer; z-index: 5; backdrop-filter: blur(8px); }
        .dc-mask-toggle:hover { background: #fff; }
        .dc-mask-legend { position: absolute; bottom: 14px; right: 14px; background: rgba(255,255,255,0.92); border: 1px solid rgba(0,0,0,0.1); border-radius: 8px; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; font-size: 11px; z-index: 5; backdrop-filter: blur(8px); }
        .dc-legend-title { font-weight: 700; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase; color: #6B6560; margin-bottom: 2px; }
        .dc-legend-muted { color: #9C9590; }
        .dc-legend-warn { color: #b5432a; font-size: 10px; margin-top: 3px; max-width: 220px; }
        .dc-swatch { display: flex; align-items: center; gap: 6px; }
        .dc-swatch-box { width: 12px; height: 12px; border-radius: 3px; }

        .dc-precedent-legend { position: absolute; bottom: 14px; left: 14px; background: rgba(255,255,255,0.92); border: 1px solid rgba(0,0,0,0.1); border-radius: 8px; padding: 7px 12px; font-size: 11px; z-index: 5; display: flex; align-items: center; backdrop-filter: blur(8px); }
        .dc-pin { display: inline-block; width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid #fff; }
        .dc-pin-go { background: #10b981; }
        .dc-pin-nogo { background: #ef4444; }

        .dc-popover { background: #fff; border: 1px solid rgba(0,0,0,0.1); border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,0.18); padding: 12px 14px; min-width: 260px; max-width: 340px; z-index: 10; }
        .dc-pop-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 12px; }
        .dc-pop-x { background: none; border: none; font-size: 16px; color: #9C9590; cursor: pointer; }
        .dc-pop-body { font-size: 12px; line-height: 1.5; color: #3a3733; margin-bottom: 10px; }
        .dc-pop-ask { background: var(--gold); color: #fff; border: none; border-radius: 6px; padding: 6px 12px; font-size: 11px; font-weight: 700; cursor: pointer; font-family: inherit; }
        .dc-pop-ask:hover { background: var(--gold-dark); }

        .dc-side { width: 360px; flex-shrink: 0; overflow-y: auto; border-left: 1px solid var(--cds-border-subtle); background: var(--cds-layer-02); padding: 16px 18px; display: flex; flex-direction: column; gap: 18px; }
        .dc-section { display: flex; flex-direction: column; gap: 10px; }
        .dc-eyebrow { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--cds-text-helper); margin: 0; }
        .dc-field { display: flex; flex-direction: column; gap: 6px; }
        .dc-lbl { font-size: 12px; color: var(--cds-text-secondary); font-weight: 600; }
        .dc-input-row { display: flex; align-items: center; gap: 10px; }
        .dc-input-row input[type=range] { flex: 1; accent-color: var(--gold); }
        .dc-input-row input[type=range].dc-range-warn { accent-color: #F59E0B; }
        .dc-val { font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--ink); min-width: 60px; text-align: right; }
        .dc-val-warn { color: #d97706; }
        .dc-subline { font-size: 11px; color: var(--cds-text-helper); margin-top: 2px; }
        .dc-subline-warn { color: #b5432a; font-weight: 600; }

        .dc-split-btn { margin-top: 6px; padding: 6px 10px; background: rgba(245,183,49,0.1); border: 1px solid rgba(245,183,49,0.3); border-radius: 6px; font-family: inherit; font-size: 11px; font-weight: 700; color: var(--gold-dark); cursor: pointer; align-self: flex-start; }
        .dc-split-btn:hover:not(:disabled) { background: rgba(245,183,49,0.18); }
        .dc-split-btn:disabled { opacity: 0.5; cursor: not-allowed; }

        .dc-split-panel { border: 1px solid var(--cds-border-subtle); border-radius: 8px; padding: 10px 12px; background: var(--cds-layer-01); margin-top: 6px; font-size: 11px; }
        .dc-split-head { display: flex; justify-content: space-between; align-items: center; font-weight: 700; font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--cds-text-helper); margin-bottom: 6px; }
        .dc-split-head button { background: none; border: none; font-size: 14px; color: #9C9590; cursor: pointer; }
        .dc-split-row { padding: 8px 0; border-top: 1px solid var(--cds-border-subtle); }
        .dc-split-row:first-of-type { border-top: none; }
        .dc-split-stations { display: flex; flex-direction: column; gap: 3px; margin-bottom: 5px; }
        .dc-split-sub { font-size: 11px; color: var(--cds-text-primary); }
        .dc-split-meta { display: flex; flex-wrap: wrap; gap: 8px; font-family: var(--mono); font-size: 10px; color: var(--cds-text-helper); }
        .dc-split-conf { padding: 1px 6px; border-radius: 3px; font-weight: 700; text-transform: uppercase; }
        .dc-split-conf-high { background: rgba(16,185,129,0.15); color: #047857; }
        .dc-split-conf-medium { background: rgba(245,158,11,0.15); color: #b45309; }
        .dc-split-conf-low { background: rgba(239,68,68,0.15); color: #b91c1c; }
        .dc-split-empty, .dc-split-err { font-size: 11px; color: var(--cds-text-helper); padding: 4px 0; }

        .dc-verdict-rail { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
        .dc-pip { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 8px 6px; border: 1px solid var(--cds-border-subtle); border-radius: 8px; background: var(--cds-layer-01); cursor: pointer; font-family: inherit; }
        .dc-pip:hover { background: var(--cds-layer-02); }
        .dc-pip-open { border-color: var(--gold); box-shadow: 0 0 0 2px rgba(245,183,49,0.15); }
        .dc-pip-dot { width: 8px; height: 8px; border-radius: 50%; }
        .dc-pip-lbl { font-size: 10px; font-weight: 700; color: var(--cds-text-primary); }
        .dc-pip-go .dc-pip-dot { background: #10b981; }
        .dc-pip-caution .dc-pip-dot { background: #f59e0b; }
        .dc-pip-nogo .dc-pip-dot { background: #ef4444; }
        .dc-pip-loading .dc-pip-dot { background: #cbd5e1; animation: dcPulse 1s ease-in-out infinite; }
        .dc-pip-offline .dc-pip-dot { background: #cbd5e1; }
        .dc-pip-offline .dc-pip-lbl { color: #9C9590; }
        @keyframes dcPulse { 0%,100% { opacity: 0.4; } 50% { opacity: 1; } }
        .dc-verdict-detail { font-size: 11px; line-height: 1.5; color: var(--cds-text-primary); background: var(--cds-layer-01); padding: 8px 10px; border-radius: 6px; }

        .dc-kpi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
        .dc-kpi { padding: 8px 10px; background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle); border-radius: 8px; }
        .dc-kpi-label { font-size: 10px; color: var(--cds-text-helper); font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }
        .dc-kpi-value { font-family: var(--mono); font-size: 15px; font-weight: 700; color: var(--ink); margin-top: 3px; display: flex; align-items: baseline; gap: 3px; }
        .dc-kpi-unit { font-size: 10px; font-weight: 500; color: var(--cds-text-helper); }
        .dc-kpi-warn { color: var(--cds-support-warning); }

        .dc-gen-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
        .dc-gen-stat { padding: 8px 10px; background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle); border-radius: 8px; }
        .dc-gen-label { font-size: 10px; color: var(--cds-text-helper); font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }
        .dc-gen-val { font-family: var(--mono); font-size: 14px; font-weight: 700; color: var(--ink); margin-top: 3px; }
        .dc-gen-val span { font-size: 10px; color: var(--cds-text-helper); margin-left: 2px; }
        .dc-gen-monthly { display: grid; grid-template-columns: repeat(12, 1fr); align-items: end; gap: 2px; height: 40px; background: var(--cds-layer-01); border: 1px solid var(--cds-border-subtle); border-radius: 6px; padding: 4px; }
        .dc-mbar { background: var(--gold); border-radius: 1px; min-height: 2px; opacity: 0.85; }
        .dc-gen-note { font-size: 10px; color: var(--cds-text-helper); }

        .dc-week-heatmap { display: grid; grid-template-columns: repeat(24, 1fr); gap: 1px; margin-top: 6px; }
        .dc-week-cell { aspect-ratio: 1; border-radius: 1px; }

        .dc-reasoning { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
        .dc-reasoning li { position: relative; padding: 6px 8px 6px 20px; font-size: 12px; color: var(--cds-text-primary); background: var(--cds-layer-01); border-radius: 6px; line-height: 1.5; }
        .dc-reasoning li::before { content: "•"; position: absolute; left: 8px; top: 5px; color: var(--gold); font-weight: 700; }
        .dc-dots { color: var(--gold); }

        .dc-chat-row { display: flex; gap: 6px; }
        .dc-chat-input { flex: 1; padding: 8px 10px; border: 1px solid var(--cds-border-subtle); border-radius: 8px; background: var(--cds-layer-01); font-family: inherit; font-size: 12px; color: var(--cds-text-primary); outline: none; }
        .dc-chat-input:focus { border-color: var(--gold); box-shadow: 0 0 0 3px rgba(var(--accent-rgb), 0.12); }
        .dc-chat-btn { padding: 8px 12px; background: var(--gold); color: #fff; border: none; border-radius: 8px; font-family: inherit; font-size: 12px; font-weight: 700; cursor: pointer; }
        .dc-chat-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .dc-chat-btn:hover:not(:disabled) { background: var(--gold-dark); }

        .dc-foot { display: flex; align-items: center; gap: 12px; padding: 12px 24px; border-top: 1px solid var(--cds-border-subtle); }
        .dc-foot-info { font-family: var(--mono); font-size: 11px; color: var(--cds-text-helper); }
        .dc-foot-spacer { flex: 1; }
        .dc-saved { color: var(--cds-support-success); font-size: 12px; font-weight: 600; }
        .dc-err { color: var(--cds-support-error); font-size: 12px; font-weight: 600; }
        .dc-btn { padding: 8px 16px; border-radius: 8px; font-family: inherit; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid transparent; }
        .dc-btn-ghost { background: transparent; border-color: var(--cds-border-subtle); color: var(--cds-text-secondary); }
        .dc-btn-ghost:hover { border-color: var(--gold); color: var(--gold-dark); }
        .dc-btn-primary { background: var(--gold); color: #fff; }
        .dc-btn-primary:hover:not(:disabled) { background: var(--gold-dark); }
        .dc-btn:disabled { opacity: 0.4; cursor: not-allowed; }

        /* ── BOT-SDE: Equipment palette ───────────────────────────────── */
        .dc-palette { width: 240px; flex-shrink: 0; overflow-y: auto;
          border-right: 1px solid var(--cds-border-subtle);
          background: var(--cds-layer-01, #1c1912); padding: 10px 10px 20px;
          display: flex; flex-direction: column; gap: 6px; }
        .dc-palette-collapsed { width: 28px; padding: 8px 0; align-items: center;
          background: var(--cds-layer-01, #1c1912);
          border-right: 1px solid var(--cds-border-subtle); display: flex; }
        .dc-palette-handle { background: transparent; border: 1px solid var(--cds-border-subtle);
          color: var(--gold); width: 22px; height: 40px; border-radius: 4px; cursor: pointer; }
        .dc-palette-head { display: flex; align-items: center; justify-content: space-between;
          padding: 4px 4px 8px; border-bottom: 1px solid var(--cds-border-subtle); margin-bottom: 4px; }
        .dc-palette-title { font-size: 11px; font-weight: 700; letter-spacing: 0.08em;
          text-transform: uppercase; color: var(--cds-text-secondary); }
        .dc-palette-close { background: transparent; border: none; color: var(--cds-text-helper);
          cursor: pointer; font-size: 14px; }
        .dc-palette-cat { display: flex; flex-direction: column; }
        .dc-palette-cat-head { display: flex; align-items: center; gap: 6px; padding: 6px 6px;
          background: transparent; border: none; color: var(--cds-text-primary);
          cursor: pointer; font-family: inherit; font-size: 12px; font-weight: 600;
          text-align: left; width: 100%; border-radius: 4px; }
        .dc-palette-cat-head:hover { background: rgba(245,183,49,0.08); }
        .dc-palette-cat-chev { color: var(--gold); font-size: 9px; width: 10px; }
        .dc-palette-cat-label { flex: 1; }
        .dc-palette-cat-count { color: var(--cds-text-helper); font-size: 11px;
          font-family: var(--mono); }
        .dc-palette-items { display: flex; flex-direction: column; gap: 3px; padding: 3px 0 8px; }
        .dc-palette-item { display: flex; align-items: center; gap: 8px; padding: 6px 6px;
          background: rgba(255,255,255,0.03); border: 1px solid transparent; border-radius: 4px;
          cursor: grab; transition: background 0.12s, border-color 0.12s; }
        .dc-palette-item:hover { background: rgba(245,183,49,0.08);
          border-color: rgba(245,183,49,0.35); }
        .dc-palette-item:active { cursor: grabbing; }
        .dc-palette-item-pulse { animation: dc-pulse-gold 1.1s ease-in-out infinite;
          border-color: var(--gold); background: rgba(245,183,49,0.14); }
        @keyframes dc-pulse-gold {
          0%,100% { box-shadow: 0 0 0 0 rgba(245,183,49,0); }
          50% { box-shadow: 0 0 0 4px rgba(245,183,49,0.35); }
        }
        .dc-palette-item-icon { width: 20px; text-align: center; color: var(--gold); font-size: 14px; }
        .dc-palette-item-body { display: flex; flex-direction: column; flex: 1; min-width: 0; }
        .dc-palette-item-name { font-size: 12px; color: var(--cds-text-primary);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .dc-palette-item-dims { font-size: 10px; font-family: var(--mono);
          color: var(--cds-text-helper); }
        .dc-palette-item-grab { color: var(--cds-text-helper); font-size: 10px; }
        .dc-palette-foot { margin-top: auto; padding-top: 8px;
          border-top: 1px solid var(--cds-border-subtle); }
        .dc-palette-foot-hint { font-size: 10px; color: var(--cds-text-helper);
          font-family: var(--mono); }

        /* ── BOT-SDE: View-mode tabs overlay ──────────────────────────── */
        .dc-vm-overlay { position: absolute; top: 12px; left: 12px; z-index: 5;
          background: rgba(28,25,18,0.88); backdrop-filter: blur(6px);
          border: 1px solid var(--cds-border-subtle); border-radius: 6px;
          padding: 4px; box-shadow: 0 4px 12px rgba(0,0,0,0.35); }
        .dc-vm-bar { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
        .dc-vm-bar .dc-vm-tab { display: flex; flex-direction: column; align-items: flex-start;
          background: transparent; border: 1px solid transparent; color: var(--cds-text-secondary);
          padding: 4px 10px; border-radius: 4px; cursor: pointer; font-family: inherit;
          font-size: 12px; font-weight: 600; }
        .dc-vm-bar .dc-vm-tab:hover { background: rgba(245,183,49,0.08); color: var(--gold); }
        .dc-vm-bar .dc-vm-tab-active { background: var(--gold); color: #000; }
        .dc-vm-bar .dc-vm-tab-kbd { font-size: 9px; font-family: var(--mono);
          color: inherit; opacity: 0.7; margin-top: 1px; }
        .dc-vm-construction { display: flex; align-items: center; gap: 8px;
          padding: 4px 10px; border-left: 1px solid var(--cds-border-subtle); }
        .dc-vm-month-label { font-size: 11px; font-family: var(--mono);
          color: var(--cds-text-secondary); min-width: 64px; }
        .dc-vm-month-range { width: 140px; }
        .dc-vm-month-phase { font-size: 11px; color: var(--gold); font-weight: 600; }
        .dc-vm-drone { display: flex; align-items: center; gap: 8px;
          padding: 4px 10px; border-left: 1px solid var(--cds-border-subtle); }
        .dc-vm-drone-btn { padding: 4px 10px; border-radius: 3px;
          border: 1px solid var(--cds-border-subtle); background: transparent;
          color: var(--cds-text-primary); cursor: pointer; font-family: inherit;
          font-size: 11px; font-weight: 600; }
        .dc-vm-drone-btn-on { background: var(--gold); color: #000; border-color: var(--gold); }
        .dc-vm-drone-hint { font-size: 10px; color: var(--cds-text-helper); font-family: var(--mono); }

        /* ── BOT-SDE: Scale reference chips ───────────────────────────── */
        .dc-scale-refs { position: absolute; top: 12px; right: 12px; z-index: 5;
          display: flex; gap: 6px; }
        .dc-scale-chip { display: flex; align-items: center; gap: 6px;
          padding: 4px 10px; border-radius: 14px;
          background: rgba(28,25,18,0.88); border: 1px solid var(--cds-border-subtle);
          color: var(--cds-text-secondary); font-size: 11px; font-weight: 600;
          cursor: default; transition: all 0.12s; }
        .dc-scale-chip:hover, .dc-scale-chip-hot { border-color: var(--gold); color: var(--gold); }
        .dc-scale-chip-dim { font-family: var(--mono); color: var(--cds-text-helper); font-size: 10px; }
        .dc-scale-chip-count { background: var(--gold); color: #000; font-size: 10px;
          padding: 0 6px; border-radius: 10px; font-weight: 700; }

        /* ── BOT-SDE: Measure tool HUD ────────────────────────────────── */
        .dc-measure-fab { position: absolute; bottom: 16px; left: 16px; z-index: 5;
          padding: 8px 14px; border-radius: 20px;
          background: rgba(28,25,18,0.92); border: 1px solid var(--cds-border-subtle);
          color: var(--cds-text-primary); cursor: pointer; font-family: inherit;
          font-size: 12px; font-weight: 600; box-shadow: 0 2px 6px rgba(0,0,0,0.35); }
        .dc-measure-fab:hover { border-color: var(--gold); color: var(--gold); }
        .dc-measure-fab-on { background: var(--gold); color: #000; border-color: var(--gold); }
        .dc-measure-hud { position: absolute; bottom: 16px; left: 160px; z-index: 5;
          display: flex; flex-direction: column; gap: 6px; padding: 10px 14px;
          background: rgba(28,25,18,0.94); border: 1px solid var(--gold); border-radius: 6px;
          box-shadow: 0 4px 12px rgba(0,0,0,0.45); min-width: 260px; }
        .dc-measure-modes { display: flex; gap: 4px; }
        .dc-measure-mode { padding: 2px 8px; border-radius: 3px; border: 1px solid var(--cds-border-subtle);
          background: transparent; color: var(--cds-text-secondary); cursor: pointer;
          font-family: inherit; font-size: 11px; font-weight: 600; }
        .dc-measure-mode-active { background: var(--gold); color: #000; border-color: var(--gold); }
        .dc-measure-readout { font-family: var(--mono); font-size: 13px; color: var(--cds-text-primary); }
        .dc-measure-hint { font-size: 10px; color: var(--cds-text-helper); }
        .dc-measure-actions { display: flex; gap: 6px; }
        .dc-measure-btn { padding: 3px 10px; border-radius: 3px;
          background: var(--gold); border: 1px solid var(--gold); color: #000;
          cursor: pointer; font-family: inherit; font-size: 11px; font-weight: 600; }
        .dc-measure-btn:disabled { opacity: 0.4; cursor: not-allowed; }
        .dc-measure-btn-ghost { background: transparent; color: var(--cds-text-secondary);
          border-color: var(--cds-border-subtle); }

        /* ── BOT-SDE: Placement inspector ─────────────────────────────── */
        .dc-place-inspector { position: absolute; bottom: 16px; right: 16px; z-index: 6;
          width: 260px; background: rgba(28,25,18,0.94);
          border: 1px solid var(--gold); border-radius: 6px;
          padding: 10px 12px; display: flex; flex-direction: column; gap: 8px;
          box-shadow: 0 4px 12px rgba(0,0,0,0.45); }
        .dc-place-inspector-head { display: flex; justify-content: space-between;
          align-items: center; border-bottom: 1px solid var(--cds-border-subtle); padding-bottom: 4px; }
        .dc-place-inspector-x { background: transparent; border: none; color: var(--cds-text-helper);
          cursor: pointer; font-size: 14px; }
        .dc-place-inspector-row { display: flex; align-items: center; gap: 8px;
          font-size: 11px; color: var(--cds-text-secondary); font-family: var(--mono); }
        .dc-place-inspector-row input[type="range"] { flex: 1; }
        .dc-place-inspector-actions { display: flex; gap: 6px; }
        .dc-place-inspector-actions button { flex: 1; padding: 4px 8px; border-radius: 3px;
          border: 1px solid var(--cds-border-subtle); background: transparent;
          color: var(--cds-text-primary); cursor: pointer; font-family: inherit; font-size: 11px; }
        .dc-place-inspector-rm { color: #EF4444 !important; }
      `}</style>
    </div>
  );
}

function Kpi({ label, value, unit, flag }) {
  return (
    <div className="dc-kpi">
      <div className="dc-kpi-label">{label}</div>
      <div className={"dc-kpi-value" + (flag === "warn" ? " dc-kpi-warn" : "")}>
        <span>{value}</span>
        {unit && <span className="dc-kpi-unit">{unit}</span>}
      </div>
    </div>
  );
}

function Swatch({ color, label }) {
  return (
    <div className="dc-swatch">
      <div className="dc-swatch-box" style={{ background: color }} />
      <span>{label}</span>
    </div>
  );
}

function WeekHeatmap({ week }) {
  if (!week?.length) return null;
  const max = Math.max(...week.map((h) => h.generation_mw || 0), 0.001);
  return (
    <div className="dc-week-heatmap">
      {week.slice(0, 168).map((h, i) => {
        const intensity = (h.generation_mw || 0) / max;
        const curtailed = (h.curtailed_mw || 0) > 0;
        const color = curtailed
          ? `rgba(239,68,68,${0.25 + intensity * 0.65})`
          : `rgba(245,183,49,${0.1 + intensity * 0.8})`;
        return (
          <div
            key={i}
            className="dc-week-cell"
            style={{ background: color }}
            title={`Hour ${h.hour}: ${h.generation_mw?.toFixed(1)} MW gen · ${h.curtailed_mw?.toFixed(1)} MW curtailed · £${h.price_gbp_mwh?.toFixed(0)}/MWh`}
          />
        );
      })}
    </div>
  );
}

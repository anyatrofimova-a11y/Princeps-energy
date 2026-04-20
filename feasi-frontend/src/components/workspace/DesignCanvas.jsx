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
function bessKpis({ capacity_mw, duration_h, headroom_mw }) {
  const effective = headroom_mw != null ? Math.min(capacity_mw, headroom_mw) : capacity_mw;
  const energy = effective * duration_h;
  const capex = energy * 1000 * 330;
  const revenue = effective * 75_000;
  const opex = energy * 1000 * 8;
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

  const layout = useMemo(() => {
    if (!site) return null;
    return generateBessLayout({
      lat: site.lat, lon: site.lon,
      capacity_mw: capacity, duration_h: duration,
    });
  }, [site, capacity, duration]);

  const kpis = useMemo(() => bessKpis({
    capacity_mw: capacity, duration_h: duration, headroom_mw: headroom,
  }), [capacity, duration, headroom]);

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

  /* ── Headroom fetch ──────────────────────────────────────────────────── */
  useEffect(() => {
    if (!site || !isOpen) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/grid/nearest-substation?lat=${site.lat}&lon=${site.lon}`);
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && data?.headroom_mw != null) setHeadroom(data.headroom_mw);
      } catch { /* keep null */ }
    })();
    return () => { cancelled = true; };
  }, [site, isOpen]);

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
    if (!isOpen || !site || !mapContainerRef.current) return;
    const map = new mapboxgl.Map({
      container: mapContainerRef.current,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: [site.lon, site.lat],
      zoom: 16.8,
      pitch: 0,
      attributionControl: false,
    });
    mapRef.current = map;
    map.on("load", () => {
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
  }, [isOpen, site]);

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
  const explainKpiValue = useCallback(async (kpiKey) => {
    setWhyKpi(kpiKey); setWhyText(null);
    if (!currentVersionId) {
      setWhyText("Save a version first to ask why this value is what it is.");
      return;
    }
    try {
      const res = await apiExplainKpi(currentVersionId, kpiKey);
      setWhyText(res?.explanation || "No explanation available.");
    } catch (e) { setWhyText(e.message || String(e)); }
  }, [currentVersionId]);

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

  if (!isOpen || !site) return null;

  return (
    <div className="dc-root">
      <header className="dc-head">
        <div className="dc-title-row">
          <h2 className="dc-title">Design {site.name}</h2>
          <span className="dc-workload">{WORKLOAD_DEFAULTS[workload]?.label || workload}</span>
          {apiLoading && <span className="dc-spin" title="Re-running pipeline">↻</span>}
          {apiError && <span className="dc-err-inline" title={apiError}>⚠</span>}
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
        <div className="dc-canvas-wrap">
          <div className="dc-canvas" ref={mapContainerRef} />

          {/* D5 — mask toggle */}
          {mask && (
            <button
              className="dc-mask-toggle"
              onClick={() => setMaskVisible((v) => !v)}
              title="Show/hide buildable-area constraint overlay"
            >
              {maskVisible ? "Hide" : "Show"} constraints
            </button>
          )}

          {/* D5 — mask legend */}
          {mask && maskVisible && (
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

/**
 * DCDesignTwin — Real-terrain 3D simulation of a Pre-FID Data Centre design.
 *
 * Replaces the abstract "racks floating in white void" view that DCPhysicalTwin
 * showed on the Plan/Design tab. Renders the proposed DC building shell, cooling
 * yard, on-site substation pad, cable corridor and access road as deck.gl
 * extrusions on top of Mapbox satellite + 3D buildings + raster-DEM terrain at
 * the user's picked lat/lon.
 *
 * Engineering rules of thumb used (deterministic — no backend round-trip
 * required for first paint; refine via /api/dc/site-design/{id} when wired):
 *   • Building footprint: 600 m² per MW IT load (2-storey shell, GFA 1,200 m²/MW)
 *   • Building height: 12 m base + 0.4 m per MW (capped 24 m); UK B8 typical
 *   • Cooling yard: 35% of building footprint, height 5 m, placed south of shell
 *   • On-site substation pad: 0.6 ha for ≤50 MW, 1.2 ha for ≤200 MW
 *   • Cable corridor: straight line shell-edge → substation pad (cost-of-rights
 *     calc would route around obstacles; out of scope for first paint)
 *   • Access road: 60 m spur from nearest mapped road (placeholder NE of site)
 *   • Perimeter fence: 5 m offset from building shell
 *
 * The geometry is meant to be DIRECTIONALLY CORRECT for engineer review at
 * Pre-FID — not survey-grade. Polygon refinement happens in DesignCanvas.
 */
import React, { useEffect, useRef, useState, useMemo, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { PolygonLayer, PathLayer, ScatterplotLayer, TextLayer, IconLayer, SolidPolygonLayer } from "@deck.gl/layers";
import { buildCampusLayout, ROLE_COLOURS } from "./dc/dcLayoutPresets";
import { buildStructureLayers } from "./dc/DCFacilityStructure";
import useBuildableMask from "../hooks/useBuildableMask";
import useShellDragHandlers, { DRAG_STATUS_COLORS } from "./dc/DCShellDragHandler";
import { useDCContext } from "../hooks/useDCContext";
import {
  buildUtilityOverlayLayers,
  DCUtilityOverlayPanel,
} from "./dc/DCUtilityOverlays";
import {
  buildContextOverlayLayers,
  deriveBlockerFlags,
  DCContextOverlayPanel,
  DCConstraintBadge,
} from "./dc/DCContextOverlays";
/* ── Live-ops overlays — owned by BOT-DX.
 *  Heatmap / Noise / Glint layers + PUE/IT/cooling/water live strip.
 *  Each overlay exposes a hook that fetches its data + a pure builder
 *  that returns deck.gl layers, so we can weave them into the existing
 *  `deckLayers` memo without forking the render path. */
import { useThermalField, thermalHeatmapLayers } from "./dc/DCThermalHeatmap";
import { useNoiseContours, noiseContourLayers } from "./dc/DCNoiseContour";
import { useGlintCones, glintConeLayers } from "./dc/DCGlintCone";
import DCLiveOpsStrip from "./dc/DCLiveOpsStrip";
// D2.5 — D1 constraint overlay (red forbidden buildings) + D2 draggable
// centroid marker with collision feedback against forbidden zones.
import ConstraintOverlay from "./dc/ConstraintOverlay";
import DraggableComponent from "./dc/DraggableComponent";
import "./dc/dc-design-overlay.css";
// D4 — UK queue overlay (TEC + ECR + REPD) so the user sees nearby
// queue projects, lines and a project-info card directly in the DC twin.
import GridQueueLayer from "./grid-overlay/GridQueueLayer";
import QueueFilterBar from "./grid-overlay/QueueFilterBar";
import ProjectInfoCard from "./grid-overlay/ProjectInfoCard";
import "./grid-overlay/queue-overlay.css";

/* ── Valid selection keys (anything else falls back to clearing selection).
 *  Structure keys: shell / hall_* / spine / mvlv / genset_yard / gen_N
 *                  / tank_N / tx_yard / tx_N / water / office / security
 *                  / loading. Plus legacy: cable / road / nearbySub:<id>.
 *  We accept any structure-style key prefix via the helper below. */
const LEGACY_SELECTED = new Set(["shell", "cooling", "substation", "cable", "road"]);
const STRUCT_PREFIXES = [
  "shell", "hall_", "spine", "mvlv", "genset_yard", "gen_", "tank_",
  "tx_yard", "tx_", "water", "office", "security", "loading",
];
function isValidSelection(s) {
  if (!s) return false;
  if (LEGACY_SELECTED.has(s)) return true;
  if (typeof s === "string") {
    if (s.startsWith("nearbySub:")) return true;
    if (STRUCT_PREFIXES.some(p => s === p || s.startsWith(p))) return true;
  }
  return false;
}

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";

const C = {
  // NOTE: shell / hall / mvlv / genset / tx / water / office / security /
  //       loading colours live in dcLayoutPresets.ROLE_COLOURS — the
  //       DCFacilityStructure renderer reads them directly.  These kept-here
  //       entries are only for the ancillary legacy layers (cable run, access
  //       road, perimeter fence) that sit outside the campus layout.
  cable:       [239, 68, 68, 255],    // red — cable corridor
  road:        [100, 116, 139, 255],  // slate — access road
  fence:       [156, 163, 175, 200],  // grey — perimeter fence
};

/* Geo helpers — flat-earth approximation; fine for a few km at this latitude. */
const M_PER_DEG_LAT = 111_320;
function mPerDegLon(lat) { return M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180); }
function offsetMeters(lat, lon, dxMeters, dyMeters) {
  return [lon + dxMeters / mPerDegLon(lat), lat + dyMeters / M_PER_DEG_LAT];
}
function rectanglePolygon(lat, lon, widthM, depthM, rotationDeg = 0) {
  const cosR = Math.cos((rotationDeg * Math.PI) / 180);
  const sinR = Math.sin((rotationDeg * Math.PI) / 180);
  const corners = [
    [-widthM / 2, -depthM / 2],
    [+widthM / 2, -depthM / 2],
    [+widthM / 2, +depthM / 2],
    [-widthM / 2, +depthM / 2],
  ];
  const ring = corners.map(([x, y]) => {
    const rx = x * cosR - y * sinR;
    const ry = x * sinR + y * cosR;
    return offsetMeters(lat, lon, rx, ry);
  });
  ring.push(ring[0]);
  return ring;
}

/* Derive site geometry deterministically from IT load + Tier + cooling type.
 *
 * The CAMPUS structure (halls, MV/LV, genset yard, TX yard, water plant,
 * office, gatehouse, loading bay) is built by `buildCampusLayout(...)` and
 * stored on the returned object as `layout`. The lighter legacy fields
 * (`shell` / `cooling` / `substation` / `cable` / `road` / `fence`) are
 * preserved so the existing InspectorPane + drag handler keep working.
 *
 * Convention: layout.* uses a local-metres frame with shell centroid at (0,0);
 * the legacy polygon-shaped fields are in WGS84 lon/lat. */
function deriveSiteGeometry({ lat, lon, itLoadMw, parcelHa, tier, redundancy, coolingType }) {
  const safeMw = Math.max(1, itLoadMw || 50);
  const layout = buildCampusLayout({
    itLoadMw: safeMw,
    tier,
    redundancy,
    coolingType: coolingType || "hybrid",
  });

  // Legacy "shell" facade — now represents the outer envelope footprint
  // (halls + MVLV + spine all sit inside). Keeps InspectorPane + drag working.
  const shellWidth = layout.shell.width;
  const shellDepth = layout.shell.depth;
  const shellHeight = layout.shell.height;
  // Shell in the campus frame is centred at (0, layout.shell.cy) — so when
  // projecting the drag-anchor polygon we offset by cy.
  const shellLocalDy = layout.shell.cy;
  const shellWgsCentroid = offsetMeters(lat, lon, 0, shellLocalDy);
  const shellLon = shellWgsCentroid[0];
  const shellLat = shellWgsCentroid[1];

  // Legacy "cooling" — now points at the water/chiller plant.
  const coolingCentroid = offsetMeters(lat, lon, layout.water.cx, layout.water.cy);
  const coolingLon = coolingCentroid[0];
  const coolingLat = coolingCentroid[1];

  // Legacy "substation" — now points at the TX yard (which is the DC's on-site substation).
  const subCentroid = offsetMeters(lat, lon, layout.tx.cx, layout.tx.cy);
  const subLon = subCentroid[0];
  const subLat = subCentroid[1];
  const subSide = Math.max(layout.tx.width, layout.tx.depth);

  // Site fence polygon in WGS84 — derived from layout.fence.
  const fenceCentroid = offsetMeters(lat, lon, layout.fence.cx, layout.fence.cy);
  const fenceLon = fenceCentroid[0];
  const fenceLat = fenceCentroid[1];

  // Access road spur: from NE fence corner outward 60 m.
  const fenceNE = offsetMeters(fenceLat, fenceLon, layout.fence.width / 2, layout.fence.depth / 2);
  const roadEnd = offsetMeters(fenceNE[1], fenceNE[0], 60, 60);

  // Cable corridor: from MVLV building east edge → TX yard west edge.
  const cableStart = offsetMeters(lat, lon, layout.mvlv.cx + layout.mvlv.width / 2, layout.mvlv.cy);
  const cableEnd   = offsetMeters(lat, lon, layout.tx.cx + layout.tx.width / 2,     layout.tx.cy);

  return {
    parcelArea: parcelHa ? parcelHa * 10000 : null,
    // Campus layout recipe (local metres frame) — consumed by DCFacilityStructure.
    layout,
    // Legacy fields (WGS84 polygons) — kept for InspectorPane + drag handler.
    shell: {
      polygon: rectanglePolygon(shellLat, shellLon, shellWidth, shellDepth, 0),
      heightM: shellHeight,
      widthM: shellWidth, depthM: shellDepth, areaM2: shellWidth * shellDepth,
      lat: shellLat, lon: shellLon,
    },
    cooling: {
      polygon: rectanglePolygon(coolingLat, coolingLon, layout.water.width, layout.water.depth, 0),
      heightM: layout.water.height,
      widthM: layout.water.width, depthM: layout.water.depth, areaM2: layout.water.area,
    },
    substation: {
      polygon: rectanglePolygon(subLat, subLon, layout.tx.width, layout.tx.depth, 0),
      heightM: 8,
      sideM: Math.round(subSide),
    },
    fence: {
      polygon: rectanglePolygon(fenceLat, fenceLon, layout.fence.width, layout.fence.depth, 0),
      widthM: layout.fence.width, depthM: layout.fence.depth,
    },
    cable: { start: cableStart, end: cableEnd },
    road:  { start: fenceNE, end: roadEnd },
  };
}

function fmtArea(m2) {
  if (m2 == null) return "—";
  if (m2 >= 10_000) return `${(m2 / 10_000).toFixed(2)} ha`;
  return `${Math.round(m2).toLocaleString()} m²`;
}

export default function DCDesignTwin({
  // Default pin: Slough Heat & Power Station (REPD 4699, 49.9 MW under construction).
  // Real grid-connected energy asset on Slough Trading Estate — existing 33/132kV
  // connection, Iver 132kV GSP 2.2 km north. Anchored via grid_substations +
  // repd_projects (not "plausible industrial plot"). See migration
  // 2026_04_21_project_real_anchors.sql.
  lat: initialLat = 51.5239,
  lon: initialLon = -0.6269,
  itLoadMw = 50,
  parcelHa = null,
  parcelId = null,           // optional HMLR INSPIRE id — plumbed for BOT-G
  tier = 3,
  redundancy = "N+1",
  coolingType = "hybrid",
  /* Optional project identity — when provided, the legend fetches BOT-REAL
   * layout specs from GET /api/design/layout-specs so every number shows a
   * source pill (planning / benchmark / estimated). Back-compat safe: absent
   * → local synthetic math (the existing `buildCampusLayout` path). */
  projectId = null,
  projectName = null,
  /* Buildable mask — if provided, the layout recipe tries to fit inside it.
   * Contract (rectangular form, local metres frame centred on shell):
   *   { minX, maxX, minY, maxY }
   * When null, structures arrange relative to the shell position. */
  buildableMask = null,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const inspectorRef = useRef(null);
  const dragStateRef = useRef({ active: false, startLonLat: null, startMouse: null });
  const orbitRafRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const [hoverInfo, setHoverInfo] = useState(null);
  const [showFence, setShowFence] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [showContext, setShowContext] = useState(true);
  /* ── BOT-DX live-ops toggles. Heatmap / Noise / Glint toggles add/remove
   *  their deck.gl sub-layers; showLive mounts the floating DCLiveOpsStrip
   *  (PUE / IT load % / cooling MW / water makeup rate). All four are
   *  independent so an operator can isolate the consequence they care about. */
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [showNoise,   setShowNoise]   = useState(false);
  const [showGlint,   setShowGlint]   = useState(false);
  const [showLive,    setShowLive]    = useState(false);
  // Drag-moveable site centroid — initialised from props, then user-controlled
  const [lat, setLat] = useState(initialLat);
  const [lon, setLon] = useState(initialLon);
  // Click-to-inspect selection (null | "shell" | "cooling" | "substation"
  //   | "cable" | "road" | "nearbySub:<id>"). Legacy/unknown values are
  //   scrubbed by the guard at render time.
  const [selectedRaw, setSelected] = useState(null);
  const selected = isValidSelection(selectedRaw) ? selectedRaw : null;
  // Ambient grid overlay — nearby substations fetched from backend
  const [nearbySubs, setNearbySubs] = useState([]);
  // BOT-REAL layout specs — each legend row carries a `source` tag
  // ("planning" | "benchmark" | "estimated") and a citation string. When the
  // fetch hasn't completed (or projectId/name aren't provided), falls back to
  // local synthetic math inside the legend render.
  const [layoutSpecs, setLayoutSpecs] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams();
    if (projectId) params.set("project_id", projectId);
    if (projectName) params.set("project_name", projectName);
    if (itLoadMw) params.set("capacity_mw", String(itLoadMw));
    if (tier) params.set("tier", String(tier));
    if (redundancy) params.set("redundancy", redundancy);
    if (coolingType) params.set("cooling", coolingType);
    fetch(`/api/design/layout-specs?${params.toString()}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!cancelled) setLayoutSpecs(d); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [projectId, projectName, itLoadMw, tier, redundancy, coolingType]);
  // Which inspector tab to show: "spec" | "cost" | "provenance"
  const [inspectorTab, setInspectorTab] = useState("spec");
  // Continuous orbit flag (driven by the "Orbit" camera preset button).
  const [orbiting, setOrbiting] = useState(false);
  // Has the user touched the site centroid? If not we recentre on new site
  // selection; once they've dragged we preserve their position.
  const snappedOnceRef = useRef(false);

  // ── Utility + context overlay toggles (BOT-DU) ─────────────────────
  //   Defaults: substation POC + planning red-line ON, rest OFF.
  const [utilityToggles, setUtilityToggles] = useState({
    substation: true, fiber: false, water: false, gas: false, road: false,
  });
  const [contextToggles, setContextToggles] = useState({
    redline: true, designations: false, flood: false, alc: false,
  });
  const [utilitySelected, setUtilitySelected] = useState(null);

  // D2.5 — placement-intelligence state.
  const [forbiddenZones, setForbiddenZones] = useState({type: 'FeatureCollection', features: []});
  const [showOverlay, setShowOverlay] = useState(true);
  const [showQueue, setShowQueue] = useState(false);
  const [queueSources, setQueueSources] = useState(['tec', 'ecr', 'repd']);
  const [queueVoltageMin, setQueueVoltageMin] = useState(33);
  const [queueShowLines, setQueueShowLines] = useState(true);
  const [queueCounts, setQueueCounts] = useState({queue: 0, lines: 0});
  const [openProjectId, setOpenProjectId] = useState(null);

  const handleUtilityToggle = useCallback((key, val) => {
    setUtilityToggles((s) => ({ ...s, [key]: val }));
  }, []);
  const handleContextToggle = useCallback((key, val) => {
    setContextToggles((s) => ({ ...s, [key]: val }));
  }, []);

  useEffect(() => {
    setLat(initialLat);
    setLon(initialLon);
    snappedOnceRef.current = false;   // new site → allow auto-snap to centroid
  }, [initialLat, initialLon]);

  /* ── Buildable-area mask for this site ────────────────────────────────── */
  const mask = useBuildableMask({ lat: initialLat, lon: initialLon, radiusM: 1500 });

  /* ── BOT-DU context: substation POC + designations + utility routes ──── */
  const dcContext = useDCContext({ lat, lon, enabled: true, radiusM: 2000 });
  // blockerFlags is declared below after `geom` (needs shell polygon).

  /* ── Initial snap to buildable centroid (once per new site) ───────────── */
  useEffect(() => {
    if (snappedOnceRef.current) return;
    if (!mask.buildableCentroid) return;
    const [cLon, cLat] = mask.buildableCentroid;
    // Only snap if the centroid moves us by ≥30 m — otherwise initialLat/Lon
    // is already close to the buildable centre and we save a visual jump.
    const dxm = (cLon - initialLon) * mPerDegLon(initialLat);
    const dym = (cLat - initialLat) * M_PER_DEG_LAT;
    if (Math.hypot(dxm, dym) > 30) {
      setLat(cLat);
      setLon(cLon);
    }
    snappedOnceRef.current = true;
  }, [mask.buildableCentroid, initialLat, initialLon]);

  /* ── Drag handlers with buildable-mask constraint ─────────────────────── */
  const drag = useShellDragHandlers({
    lat, lon, setLat, setLon, mapRef,
    isBuildable: mask.isBuildable,
    parcelContains: mask.parcelContains,
    restrictionAt: mask.restrictionAt,
  });

  const geom = useMemo(
    () => deriveSiteGeometry({ lat, lon, itLoadMw, parcelHa, tier, redundancy, coolingType }),
    [lat, lon, itLoadMw, parcelHa, tier, redundancy, coolingType]
  );

  /* ── Blocker detection based on buildable-mask + flood designations ──── */
  const blockerFlags = useMemo(
    () => deriveBlockerFlags({ ctx: dcContext, shellPolygon: geom?.shell?.polygon }),
    [dcContext, geom]
  );

  /* ── Mount Mapbox ── */
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    if (!mapboxgl.accessToken) {
      console.warn("[DCDesignTwin] VITE_MAPBOX_TOKEN missing — skipping map init");
      return;
    }

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: [lon, lat],
      zoom: 16.5,
      pitch: 60,
      bearing: -25,
      antialias: true,
      preserveDrawingBuffer: true,   // allow canvas.toBlob() for PNG snapshots
      // Explicit interaction options — don't let anything fight the user.
      interactive: true,
      dragPan: true,
      dragRotate: true,
      pitchWithRotate: true,
      scrollZoom: true,
      boxZoom: true,
      doubleClickZoom: true,
      touchZoomRotate: true,
      touchPitch: true,
      keyboard: true,
      // Widen pitch range so the preset "Side" (75°) works without clamping.
      minPitch: 0,
      maxPitch: 85,
    });
    // Defence-in-depth: some Mapbox builds ship with dragRotate disabled when
    // the container has a touch flag. Re-enable them after construction.
    try {
      map.dragRotate.enable();
      map.touchZoomRotate.enable();
      map.touchZoomRotate.enableRotation();
      map.keyboard.enable();
    } catch { /* noop */ }

    map.on("load", () => {
      // 3D terrain
      map.addSource("dem", {
        type: "raster-dem",
        url: "mapbox://mapbox.mapbox-terrain-dem-v1",
        tileSize: 512,
        maxzoom: 14,
      });
      map.setTerrain({ source: "dem", exaggeration: 1.4 });

      // Sky
      map.addLayer({
        id: "sky", type: "sky",
        paint: { "sky-type": "atmosphere", "sky-atmosphere-sun": [0, 45], "sky-atmosphere-sun-intensity": 5 },
      });

      // Existing 3D buildings (greyed out so the new design reads as the hero)
      const labelLayer = map.getStyle().layers.find(l => l.type === "symbol" && l.layout?.["text-field"]);
      map.addLayer({
        id: "3d-buildings-context",
        source: "composite",
        "source-layer": "building",
        filter: ["==", "extrude", "true"],
        type: "fill-extrusion",
        minzoom: 14,
        paint: {
          "fill-extrusion-color": "#cbd5e1",
          "fill-extrusion-height": ["get", "height"],
          "fill-extrusion-base": ["get", "min_height"],
          "fill-extrusion-opacity": 0.55,
        },
      }, labelLayer?.id);

      const overlay = new MapboxOverlay({ layers: [] });
      map.addControl(overlay);
      overlayRef.current = overlay;
      setMapReady(true);
    });

    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; overlayRef.current = null; };
  }, []); // eslint-disable-line

  /* ── Recentre when the CONTROLLING coords change (prop-driven only). */
  useEffect(() => {
    if (mapRef.current && mapReady) {
      mapRef.current.flyTo({ center: [initialLon, initialLat], zoom: 16.5, pitch: 60, duration: 1200 });
    }
  }, [initialLat, initialLon, mapReady]);

  /* ── Fetch nearby substations in a ~10 km bbox around the site. Re-runs
        whenever the centroid moves > 500 m so the ambient context stays
        accurate as the user drags the building. ── */
  useEffect(() => {
    let cancelled = false;
    const halfDegLat = 10_000 / 111_320;       // ~10 km in deg lat
    const halfDegLon = 10_000 / (111_320 * Math.cos((lat * Math.PI) / 180));
    const bbox = [lon - halfDegLon, lat - halfDegLat, lon + halfDegLon, lat + halfDegLat];
    const url = `/grid/osm/substations?west=${bbox[0]}&south=${bbox[1]}&east=${bbox[2]}&north=${bbox[3]}`;
    (async () => {
      try {
        const res = await fetch(url);
        if (!res.ok) return;
        const json = await res.json();
        const feats = json?.features || json?.substations || json || [];
        if (cancelled) return;
        const norm = (Array.isArray(feats) ? feats : []).slice(0, 40).map((f, i) => {
          const geo = f.geometry?.coordinates || f.centroid || [f.lon, f.lat];
          const props = f.properties || f;
          const kv = Number(props.voltage_kv ?? props.voltage ?? 0);
          return {
            id: props.osm_id || props.id || `sub-${i}`,
            lon: geo[0], lat: geo[1],
            name: props.name || props.ref || `Substation ${i + 1}`,
            voltage_kv: kv,
            headroom_mw: props.headroom_mw ?? props.capacity_headroom_mw ?? null,
            operator: props.operator || null,
          };
        }).filter(s => s.lon != null && s.lat != null);
        setNearbySubs(norm);
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [
    // Debounce by snapping to 0.005° grid (~500 m) so small drag adjustments
    // don't thrash the API every render.
    Math.round(lat * 200) / 200,
    Math.round(lon * 200) / 200,
  ]);

  /* ── Drag handler: middle-click or alt+left-drag on the shell moves the
        centroid. Plain left-drag still pans Mapbox. We consume pointer
        events at the deck.gl layer level via onDragStart/onDrag/onDragEnd. ── */
  // Thin shims that delegate to useShellDragHandlers (buildable-mask-aware).
  // The legacy dragStateRef is kept alive so other hover/tooltip logic that
  // reads dragStateRef.current.active keeps working.
  const handleShellDragStart = useCallback((info, event) => {
    dragStateRef.current.active = true;
    drag.onDragStart(info, event);
  }, [drag]);
  const handleShellDrag = useCallback((info, event) => {
    drag.onDrag(info, event);
  }, [drag]);
  const handleShellDragEnd = useCallback(() => {
    drag.onDragEnd();
    dragStateRef.current.active = false;
  }, [drag]);

  /* ── Escape clears selection; click outside the inspector clears too.
        (The inspector pane has pointer-events, so a click inside it won't
        bubble up to the map's container.) */
  useEffect(() => {
    if (!selected) return undefined;
    const onKey = (e) => { if (e.key === "Escape") setSelected(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected]);

  const handleCanvasBgClick = useCallback((e) => {
    // If the click lands on empty map canvas (not on a pickable deck.gl object
    // and not on the inspector pane), clear the selection. Deck.gl picks
    // fire their own onClick which calls setSelected; those stop propagation.
    if (inspectorRef.current && inspectorRef.current.contains(e.target)) return;
    // Mapbox canvases carry class "mapboxgl-canvas"; only clear on those.
    if (e.target && e.target.classList && e.target.classList.contains("mapboxgl-canvas")) {
      setSelected(null);
    }
  }, []);

  /* ── Camera preset helper — commits to Mapbox via easeTo/flyTo and toggles
        the continuous orbit RAF loop when requested. */
  const applyCameraPreset = useCallback((preset) => {
    const map = mapRef.current;
    if (!map) return;
    // Always cancel any in-flight orbit first so presets don't stack.
    if (orbitRafRef.current) {
      cancelAnimationFrame(orbitRafRef.current);
      orbitRafRef.current = null;
    }
    setOrbiting(false);
    const center = [lon, lat];
    const views = {
      plan:    { pitch: 0,  bearing: 0,   zoom: 17.0 },
      oblique: { pitch: 45, bearing: -25, zoom: 16.5 },
      side:    { pitch: 75, bearing: 90,  zoom: 16.8 },
      orbit:   { pitch: 55, bearing: 0,   zoom: 16.3 },
      reset:   { pitch: 60, bearing: -25, zoom: 16.5 },
    };
    const v = views[preset] || views.oblique;
    map.flyTo({ center, ...v, duration: 1000, essential: true });
    if (preset === "orbit") {
      setOrbiting(true);
      let bearing = v.bearing;
      const tick = () => {
        bearing = (bearing + 0.15) % 360;
        try { map.setBearing(bearing); } catch { /* noop */ }
        orbitRafRef.current = requestAnimationFrame(tick);
      };
      // start after the flyTo settles
      setTimeout(() => {
        if (!mapRef.current) return;
        orbitRafRef.current = requestAnimationFrame(tick);
      }, 1050);
    }
  }, [lat, lon]);

  /* Stop orbit when unmounting. */
  useEffect(() => {
    return () => {
      if (orbitRafRef.current) cancelAnimationFrame(orbitRafRef.current);
      orbitRafRef.current = null;
    };
  }, []);

  /* ── Take snapshot PNG of the current viewport. */
  const handleSnapshot = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    try {
      const canvas = map.getCanvas();
      canvas.toBlob((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `princeps-dc-twin-${Date.now()}.png`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1200);
      }, "image/png");
    } catch { /* noop */ }
  }, []);

  /* ── BOT-DX: live-ops overlay data. Fetched lazily — each hook returns
   *  null when its toggle is off and fires a client-side (or /api/dc/*)
   *  request when it flips on. Receptors are synthesised from the nearest
   *  5 OSM substations as proxy "sensitive" points — once the backend
   *  ships /api/dc/receptors, feed that in its place. */
  const receptors = useMemo(() => (nearbySubs || []).slice(0, 5).map((s, i) => ({
    lat: s.lat, lon: s.lon, label: s.name || `Receptor ${i + 1}`, kind: "infra",
  })), [nearbySubs]);
  // Emitter positions derived from the campus layout — genset yard + chiller plant.
  const genLat = geom?.layout?.genset_yard
    ? lat + geom.layout.genset_yard.cy / M_PER_DEG_LAT : lat;
  const genLon = geom?.layout?.genset_yard
    ? lon + geom.layout.genset_yard.cx / mPerDegLon(lat) : lon;
  const chillLat = geom?.cooling?.polygon?.[0]?.[1] ?? lat;
  const chillLon = geom?.cooling?.polygon?.[0]?.[0] ?? lon;
  const coolingLat = geom?.cooling?.lat
    ?? (geom?.cooling?.polygon?.[0]?.[1] ?? lat);
  const coolingLon = geom?.cooling?.lon
    ?? (geom?.cooling?.polygon?.[0]?.[0] ?? lon);

  const { field: thermalField } = useThermalField({
    itLoadMw, enabled: showHeatmap,
  });
  const noiseData = useNoiseContours({
    lat, lon, itLoadMw, genLat, genLon, chillLat, chillLon, receptors,
    enabled: showNoise,
  });
  const glintData = useGlintCones({
    lat, lon, coolingLat, coolingLon, receptors,
    enabled: showGlint,
  });

  /* ── Build deck.gl layers from derived geometry ── */
  const deckLayers = useMemo(() => {
    if (!mapReady) return [];
    const layers = [];

    // Buildable-area overlay — semi-transparent gold polygon with restricted
    // designations (SSSI / AONB / flood / ALC / steep slope) punched out as
    // interior rings. Rendered first so it sits UNDER the extruded structures.
    if (mask.buildablePolygon) {
      layers.push(new SolidPolygonLayer({
        id: "buildable-overlay",
        data: [{ polygon: mask.buildablePolygon.coordinates }],
        getPolygon: d => d.polygon,
        getFillColor: [245, 183, 49, 55],       // gold @ ~22%
        getLineColor: [245, 183, 49, 160],
        stroked: true,
        filled: true,
        extruded: false,
        pickable: false,
        lineWidthMinPixels: 1,
      }));
    }

    // ── Campus structure stack ──
    // Replaces the monolithic purple shell with a structured hyperscaler
    // campus: shell outline (charcoal) + data halls (pale gold) + MEP spine
    // + MV/LV switchgear (blue-grey) + genset yard (dark green, with
    // individual gensets + diesel tanks) + TX yard (orange-brown, with
    // individual transformers) + water/cooling plant (blue) + office/NOC
    // (cream) + security gatehouse (amber) + loading bay + dashed perimeter
    // fence. Shell drag-handlers from BOT-DP's useShellDragHandlers so the
    // whole campus moves as a unit with green/amber/red mask feedback.
    layers.push(...buildStructureLayers({
      layout: geom.layout,
      lat, lon,
      selected,
      showFence,
      onSelect: (item) => setSelected(item.key),
      onHover: (info) => setHoverInfo(info),
      onShellDragStart: drag?.onDragStart,
      onShellDrag:      drag?.onDrag,
      onShellDragEnd:   drag?.onDragEnd,
    }));

    // Cable corridor — pickable so clicking opens the cable schedule drawer.
    layers.push(new PathLayer({
      id: "dc-cable",
      data: [{ path: [geom.cable.start, geom.cable.end] }],
      getPath: d => d.path,
      getColor: selected === "cable" ? [255, 215, 0, 255] : C.cable,
      widthMinPixels: selected === "cable" ? 7 : 4,
      capRounded: true,
      jointRounded: true,
      pickable: true,
      updateTriggers: { getColor: [selected], getWidth: [selected] },
      onClick: ({ object }) => { if (object) setSelected("cable"); },
      onHover: ({ object, x, y }) => setHoverInfo(object ? {
        x, y,
        title: "Cable corridor",
        rows: [
          ["Route", "Shell east edge → sub west edge"],
          ["Sizing", "BS 7671 · armoured LV/HV"],
          ["Click", "Open cable schedule"],
        ],
      } : null),
    }));

    // Access road — pickable so clicking opens the road spec drawer.
    layers.push(new PathLayer({
      id: "dc-road",
      data: [{ path: [geom.road.start, geom.road.end] }],
      getPath: d => d.path,
      getColor: selected === "road" ? [255, 215, 0, 255] : C.road,
      widthMinPixels: selected === "road" ? 12 : 8,
      capRounded: true,
      pickable: true,
      updateTriggers: { getColor: [selected], getWidth: [selected] },
      onClick: ({ object }) => { if (object) setSelected("road"); },
      onHover: ({ object, x, y }) => setHoverInfo(object ? {
        x, y,
        title: "Access road spur",
        rows: [
          ["Width", "6.0 m (HGV-capable)"],
          ["Surface", "Bitumen on Type 1 sub-base"],
          ["Click", "Open loading / drainage spec"],
        ],
      } : null),
    }));

    // Perimeter fence is now rendered inside buildStructureLayers (above)
    // wrapping the entire campus — including the genset + TX + water + office
    // compounds — rather than just the shell. Kept as a no-op block so the
    // showFence toggle still functions via the `showFence` prop passed in.

    // Ambient context — nearby grid substations. Thin dashed line from each
    // to the DC site for quick distance read.
    if (showContext && nearbySubs.length > 0) {
      layers.push(new ScatterplotLayer({
        id: "nearby-subs",
        data: nearbySubs,
        getPosition: d => [d.lon, d.lat],
        getFillColor: d => {
          if (selected === `nearbySub:${d.id}`) return [255, 215, 0, 255];
          if (d.voltage_kv >= 275) return [239, 68, 68, 230];
          if (d.voltage_kv >= 132) return [30, 136, 229, 220];
          if (d.voltage_kv >= 33)  return [156, 39, 176, 220];
          return [158, 158, 158, 200];
        },
        getRadius: d => {
          const base = d.voltage_kv >= 132 ? 60 : 40;
          return selected === `nearbySub:${d.id}` ? base * 1.4 : base;
        },
        getLineColor: [255, 255, 255, 220],
        lineWidthMinPixels: 1.5,
        stroked: true,
        radiusUnits: "meters",
        radiusMinPixels: 6,
        pickable: true,
        updateTriggers: { getFillColor: [selected], getRadius: [selected] },
        onClick: ({ object }) => { if (object) setSelected(`nearbySub:${object.id}`); },
        onHover: ({ object, x, y }) => setHoverInfo(object ? {
          x, y,
          title: object.name,
          rows: [
            ["Voltage", object.voltage_kv ? `${object.voltage_kv} kV` : "—"],
            ["Headroom", object.headroom_mw != null ? `${object.headroom_mw} MW` : "—"],
            ["Operator", object.operator || "—"],
            ["Distance", `${(Math.hypot(
              (object.lat - lat) * M_PER_DEG_LAT,
              (object.lon - lon) * mPerDegLon(lat),
            ) / 1000).toFixed(2)} km`],
          ],
        } : null),
      }));

      // Faint connecting line from each substation to the site for visual
      // triangulation. Thicker for the nearest 5.
      const sorted = [...nearbySubs].map(s => ({
        ...s,
        dist_m: Math.hypot(
          (s.lat - lat) * M_PER_DEG_LAT,
          (s.lon - lon) * mPerDegLon(lat),
        ),
      })).sort((a, b) => a.dist_m - b.dist_m);
      const top5Ids = new Set(sorted.slice(0, 5).map(s => s.id));
      layers.push(new PathLayer({
        id: "nearby-subs-spokes",
        data: nearbySubs.map(s => ({
          path: [[s.lon, s.lat], [lon, lat]],
          prominent: top5Ids.has(s.id),
        })),
        getPath: d => d.path,
        getColor: d => d.prominent ? [255, 215, 0, 120] : [200, 200, 200, 50],
        getWidth: d => d.prominent ? 2 : 1,
        widthMinPixels: 1,
      }));
    }

    // Labels — one per structure in the campus. Positions are projected
    // from the layout's local-metres centroids into WGS84.
    if (showLabels) {
      const mLon = mPerDegLon(lat);
      const offsetLL = (cx, cy) => [lon + cx / mLon, lat + cy / M_PER_DEG_LAT];
      const labelData = [];
      const layoutMeta = geom.layout;
      if (layoutMeta) {
        const [shellLon, shellLat] = offsetLL(layoutMeta.shell.cx, layoutMeta.shell.cy);
        const [mvlvLon, mvlvLat]   = offsetLL(layoutMeta.mvlv.cx,  layoutMeta.mvlv.cy);
        const [gLon, gLat]         = offsetLL(layoutMeta.genset.cx, layoutMeta.genset.cy);
        const [txLon, txLat]       = offsetLL(layoutMeta.tx.cx,    layoutMeta.tx.cy);
        const [wLon, wLat]         = offsetLL(layoutMeta.water.cx, layoutMeta.water.cy);
        const [oLon, oLat]         = offsetLL(layoutMeta.office.cx, layoutMeta.office.cy);
        const [sLon, sLat]         = offsetLL(layoutMeta.security.cx, layoutMeta.security.cy);
        labelData.push(
          { lon: shellLon, lat: shellLat, text: `Shell · ${layoutMeta.meta.hallCount} halls` },
          { lon: mvlvLon,  lat: mvlvLat,  text: "MV / LV" },
          { lon: gLon,     lat: gLat,     text: `Genset · ${layoutMeta.meta.genCount} × 5 MW` },
          { lon: txLon,    lat: txLat,    text: `TX · ${layoutMeta.meta.txCount} × 20 MVA` },
          { lon: wLon,     lat: wLat,     text: "Water plant" },
          { lon: oLon,     lat: oLat,     text: "Office / NOC" },
          { lon: sLon,     lat: sLat,     text: "Gatehouse" },
        );
      }
      layers.push(new TextLayer({
        id: "dc-labels",
        data: labelData,
        getPosition: d => [d.lon, d.lat],
        getText: d => d.text,
        getSize: 13,
        getColor: [255, 255, 255, 240],
        getPixelOffset: [0, -8],
        background: true,
        getBackgroundColor: [15, 23, 42, 200],
        backgroundPadding: [4, 2],
        fontFamily: '"DM Sans", sans-serif',
        fontWeight: 700,
      }));
    }

    /* ── BOT-DX live-ops overlay layers. Each builder returns [] when
     *  its toggle is off so they're cheap to leave on the render path. */
    if (showHeatmap && thermalField && geom?.shell) {
      layers.push(...thermalHeatmapLayers({
        shell: geom.shell,
        field: thermalField,
        visible: true,
        showArrows: true,
      }));
    }
    if (showNoise && noiseData) {
      layers.push(...noiseContourLayers({ data: noiseData, visible: true }));
    }
    if (showGlint && glintData) {
      layers.push(...glintConeLayers({ data: glintData, visible: true }));
    }

    // ── BOT-DU utility overlays (substation POC, fibre, water, gas, road)
    //     Anchor point is the east-edge midpoint of the shell — that's where
    //     the cable corridor leaves the building in the legacy geometry.
    if (geom?.shell) {
      const shellEdge = [
        geom.shell.lon + (geom.shell.widthM / 2) / mPerDegLon(geom.shell.lat),
        geom.shell.lat,
      ];
      layers.push(...buildUtilityOverlayLayers({
        ctx: dcContext,
        shellEdge,
        toggles: utilityToggles,
        selected: utilitySelected,
        onSelect: (id) => setUtilitySelected(id),
        onHover: (info) => setHoverInfo(info),
      }));

      // ── BOT-DU context overlays (red-line, designations, flood, ALC)
      layers.push(...buildContextOverlayLayers({
        ctx: dcContext,
        shellPolygon: geom.shell.polygon,
        toggles: contextToggles,
      }));
    }

    return layers;
  }, [
    geom, mapReady, showFence, showLabels, showContext, selected, nearbySubs,
    itLoadMw, redundancy, tier, lat, lon,
    handleShellDragStart, handleShellDrag, handleShellDragEnd,
    showHeatmap, thermalField, showNoise, noiseData, showGlint, glintData,
    dcContext, utilityToggles, contextToggles, utilitySelected,
    mask.buildablePolygon, drag.status,
  ]);

  useEffect(() => {
    if (overlayRef.current) overlayRef.current.setProps({ layers: deckLayers });
  }, [deckLayers]);

  return (
    <div
      style={{ position: "relative", width: "100%", height: "100%", minHeight: 480, background: "#0f172a" }}
      onClickCapture={handleCanvasBgClick}
    >
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />

      {/* D2.5 — placement intelligence + UK queue overlay. Both bind onto
          the existing Mapbox map ref once it's ready. */}
      {mapReady && showOverlay && (
        <ConstraintOverlay
          map={mapRef.current}
          lat={lat}
          lng={lon}
          radiusM={500}
          onZonesReady={(features) => setForbiddenZones({type: 'FeatureCollection', features})}
        />
      )}
      {mapReady && (
        <DraggableComponent
          map={mapRef.current}
          id="campus-centroid"
          label="CAMPUS"
          position={[lon, lat]}
          forbiddenZones={forbiddenZones}
          onMove={(_id, [lng, la]) => { setLon(lng); setLat(la); }}
        />
      )}
      {mapReady && showQueue && (
        <GridQueueLayer
          map={mapRef.current}
          voltageMin={queueVoltageMin}
          sources={queueSources}
          showLines={queueShowLines}
          onProjectClick={setOpenProjectId}
          onFeaturesLoaded={setQueueCounts}
        />
      )}
      {showQueue && (
        <QueueFilterBar
          voltageMin={queueVoltageMin}
          onVoltageMin={setQueueVoltageMin}
          sources={queueSources}
          onSourcesToggle={setQueueSources}
          showLines={queueShowLines}
          onShowLinesToggle={setQueueShowLines}
          counts={queueCounts}
        />
      )}
      {openProjectId && (
        <ProjectInfoCard
          featureId={openProjectId}
          onClose={() => setOpenProjectId(null)}
        />
      )}
      {/* Quick toggles for the new overlays. Sits below the existing layer chips. */}
      <div style={{
        position: 'absolute', top: 12, right: 12, zIndex: 4,
        display: 'flex', gap: 6,
        background: 'rgba(255,255,255,0.92)', backdropFilter: 'blur(10px)',
        padding: '6px 8px', borderRadius: 10, border: '1px solid rgba(15,19,24,0.08)',
        fontFamily: '"DM Sans", sans-serif', fontSize: 11,
      }}>
        <button onClick={() => setShowOverlay(s => !s)}
          style={{...chipBtn(showOverlay), color: '#0F1318'}}
          title="Red-zone forbidden buildings + project red-line">Forbidden</button>
        <button onClick={() => setShowQueue(s => !s)}
          style={{...chipBtn(showQueue), color: '#0F1318'}}
          title="UK queue (TEC / ECR / REPD) + power lines">UK Queue</button>
      </div>

      {!mapboxgl.accessToken && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
          background: "rgba(15,23,42,0.92)", color: "#cbd5e1", textAlign: "center",
          fontFamily: '"DM Sans", sans-serif', padding: 32,
        }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>Mapbox token missing</div>
            <div style={{ fontSize: 12, color: "#94a3b8" }}>
              Add <code>VITE_MAPBOX_TOKEN=pk.…</code> to <code>feasi-frontend/.env</code> and restart Vite.
            </div>
          </div>
        </div>
      )}

      {/* Layer toggle + camera preset chip bar */}
      <div style={{
        position: "absolute", top: 12, left: 12, display: "flex",
        flexDirection: "column", gap: 6,
        fontFamily: '"DM Sans", sans-serif', fontSize: 11, color: "#e2e8f0",
      }}>
        {/* Row 1 — layer toggles */}
        <div style={{
          display: "flex", gap: 6,
          background: "rgba(15,23,42,0.85)", padding: "6px 8px", borderRadius: 8,
          backdropFilter: "blur(6px)",
        }}>
          <button onClick={() => setShowFence(s => !s)} style={chipBtn(showFence)}>Fence</button>
          <button onClick={() => setShowLabels(s => !s)} style={chipBtn(showLabels)}>Labels</button>
          <button onClick={() => setShowContext(s => !s)} style={chipBtn(showContext)}>Grid ({nearbySubs.length})</button>
        </div>
        {/* Row 1b — BOT-DX live-ops overlays. Heatmap wires the top-bar
         *  "Heatmap" button (previously dead) to an actual thermal layer.
         *  All four toggles are independent. */}
        <div style={{
          display: "flex", gap: 6,
          background: "rgba(15,23,42,0.85)", padding: "6px 8px", borderRadius: 8,
          backdropFilter: "blur(6px)",
        }}>
          <button onClick={() => setShowHeatmap(s => !s)} style={chipBtn(showHeatmap)} title="Hall thermal heatmap (CFD-lite)">Heatmap</button>
          <button onClick={() => setShowNoise(s => !s)}   style={chipBtn(showNoise)}   title="ISO 9613-2 noise contours (genset + chillers)">Noise</button>
          <button onClick={() => setShowGlint(s => !s)}   style={chipBtn(showGlint)}   title="Solar-noon glint cones (summer + winter)">Glint</button>
          <button onClick={() => setShowLive(s => !s)}    style={chipBtn(showLive)}    title="Live PUE / IT / cooling / water makeup">Live</button>
        </div>
        {/* Row 2 — camera presets */}
        <div style={{
          display: "flex", gap: 6,
          background: "rgba(15,23,42,0.85)", padding: "6px 8px", borderRadius: 8,
          backdropFilter: "blur(6px)",
        }}>
          <button onClick={() => applyCameraPreset("plan")}    style={chipBtn(false)}>Plan</button>
          <button onClick={() => applyCameraPreset("oblique")} style={chipBtn(false)}>45°</button>
          <button onClick={() => applyCameraPreset("side")}    style={chipBtn(false)}>Side</button>
          <button onClick={() => applyCameraPreset("orbit")}   style={chipBtn(orbiting)}>Orbit</button>
          <button onClick={() => applyCameraPreset("reset")}   style={chipBtn(false)}>Reset</button>
          <button onClick={handleSnapshot}                     style={chipBtn(false)}>PNG</button>
        </div>
      </div>

      {/* BOT-DU — constraint badge (top-centre, blockers first) */}
      <DCConstraintBadge
        blockers={blockerFlags.blockers}
        nearMisses={blockerFlags.nearMisses}
        overallRisk={blockerFlags.overallRisk}
      />

      {/* BOT-DU — utility overlay toggles (top-right, slot 1) */}
      <DCUtilityOverlayPanel
        toggles={utilityToggles}
        onToggle={handleUtilityToggle}
        fallbacks={dcContext.fallbacks || []}
        ctx={dcContext}
      />

      {/* BOT-DU — context overlay toggles (top-right, slot 2 below utility) */}
      <DCContextOverlayPanel
        toggles={contextToggles}
        onToggle={handleContextToggle}
        ctx={dcContext}
        topOffset={188}
      />

      {/* Drag hint — only on first paint until the user has moved the shell.
           Pushed down-left so it doesn't collide with the utility/context panels. */}
      {!dragStateRef.current.active && (
        <div style={{
          position: "absolute", bottom: 12, right: 12,
          background: "rgba(15,23,42,0.85)", color: "#e2e8f0",
          padding: "6px 10px", borderRadius: 6,
          fontFamily: '"DM Sans", sans-serif', fontSize: 10, letterSpacing: 0.4,
          textTransform: "uppercase", fontWeight: 700, backdropFilter: "blur(6px)",
        }}>
          Drag shell to reposition · Click any element to inspect
        </div>
      )}

      {/* Real-time constraint readout — visible while dragging. Shows the
          pointer's current status + distances to nearest substation, the
          inverse nearest flood buffer, and the current restriction if any.
          Background tint mirrors drag.status for instant feedback. */}
      {drag.status !== "idle" && (
        <ConstraintReadout
          status={drag.status}
          hint={drag.pointerHint}
          pointerLonLat={drag.pointerLonLat}
          siteLonLat={[lon, lat]}
          nearbySubs={nearbySubs}
          nearestFloodBufferM={mask.nearestFloodBufferM}
          restrictionAt={mask.restrictionAt}
          mapLoading={mask.loading}
        />
      )}

      {/* Inspector pane — shows click-selected element detail
       *  ┌──────────────────────────────────────────────┐
       *  │ Building shell              [Spec|Cost|Prov] │
       *  │ Footprint          1.80 ha                   │
       *  │ Width × depth      134 × 134 m               │
       *  │ Height             24.0 m (2-storey)         │
       *  │ IT load            50 MW                     │
       *  │ ...                                          │
       *  │ [ Snap DC to this substation ]               │
       *  └──────────────────────────────────────────────┘
       */}
      {selected && (
        <InspectorPane
          paneRef={inspectorRef}
          selected={selected}
          activeTab={inspectorTab}
          onTabChange={setInspectorTab}
          geom={geom}
          itLoadMw={itLoadMw}
          tier={tier}
          redundancy={redundancy}
          nearbySubs={nearbySubs}
          lat={lat}
          lon={lon}
          onClose={() => setSelected(null)}
          onSnapToSub={(sub) => {
            // Snap the site centroid to ~120 m north of the chosen substation so
            // the cable corridor lands directly on its pad.
            setLat(sub.lat + 120 / M_PER_DEG_LAT);
            setLon(sub.lon);
            setSelected("shell");
          }}
        />
      )}

      {/* Legend — each swatch is now a clickable chip that opens its sub-drawer.
          BOT-REAL: when /api/design/layout-specs returns rows, render the
          real/benchmark-tagged labels and show a source pill. Otherwise fall
          back to the local synthetic math (geom.layout.*). */}
      <div style={{
        position: "absolute", bottom: 12, left: 12,
        background: "rgba(15,23,42,0.88)", padding: "10px 12px", borderRadius: 8,
        fontFamily: '"DM Sans", sans-serif', fontSize: 11, color: "#e2e8f0",
        backdropFilter: "blur(6px)", lineHeight: 1.6,
      }}>
        <div style={{ fontWeight: 700, marginBottom: 4, letterSpacing: 0.4, textTransform: "uppercase", fontSize: 9, color: "#94a3b8" }}>
          Pre-FID layout · {itLoadMw} MW · Tier {tier} · {redundancy}
        </div>
        {layoutSpecs?.summary && (
          <div style={{ fontSize: 9, color: "#94a3b8", marginBottom: 4 }}
               title={layoutSpecs.summary.citation || ""}>
            {layoutSpecs.summary.source === "planning"
              ? `Anchored to ${layoutSpecs.summary.confidence || "submission"} · `
              : "Benchmark-sourced · "}
            {layoutSpecs.summary.source_url ? (
              <a href={layoutSpecs.summary.source_url} target="_blank" rel="noreferrer"
                 style={{ color: "#fde68a", textDecoration: "underline" }}>source</a>
            ) : (
              <span>{layoutSpecs.summary.citation?.slice(0, 40) || "ASHRAE / Uptime"}</span>
            )}
          </div>
        )}
        {/* Campus structure roster — one swatch per dominant role, each
            showing area and (where useful) count. Click to focus. */}
        {(() => {
          const rows = layoutSpecs?.legend_rows || [];
          const row = (i) => rows[i] || null;
          const shell = row(0), halls = row(1), mvlv = row(2),
                genset = row(3), tx = row(4), water = row(5),
                office = row(6), gatehouse = row(7), loading = row(8);
          return (
            <>
              <Swatch
                c={ROLE_COLOURS.shell}
                label={shell?.label ?? `Shell ${(geom.layout.shell.area / 10_000).toFixed(2)} ha · ${geom.layout.meta.shellHeight.toFixed(0)} m · ${geom.layout.meta.hallCount} halls`}
                source={shell?.source} citation={shell?.citation}
                active={selected === "shell"}
                onClick={() => setSelected("shell")}
              />
              <Swatch
                c={ROLE_COLOURS.hall}
                label={halls?.label ?? `Halls · IT white space ${(geom.layout.shell.itAreaM2 / 10_000).toFixed(2)} ha`}
                source={halls?.source} citation={halls?.citation}
                active={selected?.startsWith("hall_")}
                onClick={() => setSelected("hall_0_0")}
              />
              <Swatch
                c={ROLE_COLOURS.mvlv}
                label={mvlv?.label ?? `MV/LV · ${Math.round(geom.layout.mvlv.width * geom.layout.mvlv.depth).toLocaleString()} m² · switchgear + UPS`}
                source={mvlv?.source} citation={mvlv?.citation}
                active={selected === "mvlv"}
                onClick={() => setSelected("mvlv")}
              />
              <Swatch
                c={ROLE_COLOURS.genset}
                label={genset?.label ?? `Genset yard · ${geom.layout.meta.genCount} × 5 MW · ${(geom.layout.genset.area / 10_000).toFixed(2)} ha`}
                source={genset?.source} citation={genset?.citation}
                active={selected === "genset_yard" || selected?.startsWith("gen_")}
                onClick={() => setSelected("genset_yard")}
              />
              <Swatch
                c={ROLE_COLOURS.tx}
                label={tx?.label ?? `TX yard · ${geom.layout.meta.txCount} × 20 MVA · ${(geom.layout.tx.area / 10_000).toFixed(2)} ha`}
                source={tx?.source} citation={tx?.citation}
                active={selected === "tx_yard" || selected?.startsWith("tx_")}
                onClick={() => setSelected("tx_yard")}
              />
              <Swatch
                c={ROLE_COLOURS.water}
                label={water?.label ?? `Water plant · ${(geom.layout.water.area / 10_000).toFixed(2)} ha · ${coolingType}`}
                source={water?.source} citation={water?.citation}
                active={selected === "water"}
                onClick={() => setSelected("water")}
              />
              <Swatch
                c={ROLE_COLOURS.office}
                label={office?.label ?? `Office / NOC · ${Math.round(geom.layout.office.area).toLocaleString()} m² · 2-storey`}
                source={office?.source} citation={office?.citation}
                active={selected === "office"}
                onClick={() => setSelected("office")}
              />
              <Swatch
                c={ROLE_COLOURS.security}
                label={gatehouse?.label ?? `Gatehouse · ${Math.round(geom.layout.security.area).toLocaleString()} m² · access control`}
                source={gatehouse?.source} citation={gatehouse?.citation}
                active={selected === "security"}
                onClick={() => setSelected("security")}
              />
              <Swatch
                c={ROLE_COLOURS.loading}
                label={loading?.label ?? `Loading bay · ${Math.round(geom.layout.loading.area).toLocaleString()} m² · HGV dock`}
                source={loading?.source} citation={loading?.citation}
                active={selected === "loading"}
                onClick={() => setSelected("loading")}
              />
            </>
          );
        })()}
        <Swatch c={C.cable} label="Cable corridor · MV/LV → TX yard"  active={selected === "cable"} onClick={() => setSelected("cable")} />
        <Swatch c={C.road}  label="Access road · HGV spur"            active={selected === "road"}  onClick={() => setSelected("road")} />
      </div>

      {/* Hover tip */}
      {hoverInfo && (
        <div style={{
          position: "absolute", left: hoverInfo.x + 12, top: hoverInfo.y + 12,
          background: "rgba(15,23,42,0.94)", color: "#f1f5f9",
          padding: "10px 12px", borderRadius: 8, fontFamily: '"DM Sans", sans-serif',
          fontSize: 11, pointerEvents: "none", boxShadow: "0 6px 24px rgba(0,0,0,0.4)",
          zIndex: 5,
        }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 4 }}>{hoverInfo.title}</div>
          {hoverInfo.rows.map((r, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
              <span style={{ color: "#94a3b8" }}>{r[0]}</span>
              <span style={{ fontFamily: '"JetBrains Mono", monospace' }}>{r[1]}</span>
            </div>
          ))}
        </div>
      )}

      {/* BOT-DX — floating live-ops strip. Toggled by the "Live" chip.
       *  Ticks every 5s via WS when /ws/dc-ops is available, else falls
       *  back to 30s polling of /api/dc/ops (or a deterministic simulator
       *  when VITE_MOCK_DC_OPS is truthy). */}
      {showLive && (
        <DCLiveOpsStrip
          itLoadMw={itLoadMw}
          visible={showLive}
          onClose={() => setShowLive(false)}
        />
      )}

      {/* BOT-DX — Heatmap legend. Shows when Heatmap is on so the operator
       *  can read the cold→hot scale and hotspot count at a glance. */}
      {showHeatmap && thermalField && (
        <div style={{
          position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)",
          background: "rgba(15,23,42,0.92)", color: "#f1f5f9",
          borderRadius: 8, padding: "8px 14px",
          fontFamily: '"DM Sans", sans-serif', fontSize: 11,
          display: "flex", alignItems: "center", gap: 12,
          border: "1px solid rgba(245,183,49,0.35)",
          zIndex: 5,
        }}>
          <span style={{ fontSize: 9, color: "#fca5a5", fontWeight: 800, letterSpacing: 0.8, textTransform: "uppercase" }}>
            Thermal
          </span>
          <div style={{
            width: 120, height: 10, borderRadius: 5,
            background: "linear-gradient(90deg, rgb(0,120,255), rgb(40,200,120), rgb(250,200,40), rgb(239,68,68))",
          }} />
          <span style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color: "#cbd5e1" }}>
            {thermalField.min_inlet_temp_c ?? 18}° → {thermalField.max_inlet_temp_c ?? 35}°C
          </span>
          {thermalField.hotspot_count > 0 && (
            <span style={{
              padding: "2px 8px", borderRadius: 10,
              background: "rgba(239,68,68,0.25)", color: "#fca5a5",
              fontWeight: 700, fontSize: 10,
            }}>
              {thermalField.hotspot_count} hotspot{thermalField.hotspot_count === 1 ? "" : "s"}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function ConstraintReadout({ status, hint, pointerLonLat, siteLonLat, nearbySubs, nearestFloodBufferM, restrictionAt, mapLoading }) {
  const MPERLAT = 111_320;
  const mPerLon = (la) => MPERLAT * Math.cos((la * Math.PI) / 180);
  const [lon, lat] = pointerLonLat || siteLonLat || [0, 0];
  let nearestSubDist = Infinity;
  for (const s of nearbySubs || []) {
    const dxm = (s.lon - lon) * mPerLon(lat);
    const dym = (s.lat - lat) * MPERLAT;
    const d = Math.hypot(dxm, dym);
    if (d < nearestSubDist) nearestSubDist = d;
  }
  const floodM = typeof nearestFloodBufferM === "function" ? nearestFloodBufferM(lon, lat) : Infinity;
  const restriction = typeof restrictionAt === "function" ? restrictionAt(lon, lat) : null;
  const palette = {
    ok:      { bg: "rgba(22,101,52,0.95)",  accent: "#86efac" },
    warn:    { bg: "rgba(120,53,15,0.95)",  accent: "#fbbf24" },
    blocked: { bg: "rgba(127,29,29,0.95)",  accent: "#fca5a5" },
  }[status] || { bg: "rgba(15,23,42,0.94)", accent: "#e2e8f0" };
  const fmtM = (m) => !isFinite(m) ? "—" : m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(2)} km`;
  const headline = status === "ok" ? "Buildable"
                 : status === "warn" ? "In restriction zone"
                 : status === "blocked" ? "Outside parcel" : "—";
  return (
    <div style={{
      position: "absolute", bottom: 120, left: "50%", transform: "translateX(-50%)",
      background: palette.bg, color: "#f1f5f9",
      padding: "10px 16px", borderRadius: 10,
      fontFamily: '"DM Sans", sans-serif', fontSize: 11,
      boxShadow: "0 8px 28px rgba(0,0,0,0.45)",
      backdropFilter: "blur(8px)",
      border: `1px solid ${palette.accent}`,
      zIndex: 7, pointerEvents: "none",
      minWidth: 280, textAlign: "center",
    }}>
      <div style={{ fontSize: 10, letterSpacing: 1.2, textTransform: "uppercase", fontWeight: 800, color: palette.accent, marginBottom: 4 }}>
        {headline}{mapLoading ? " · loading mask" : ""}
      </div>
      <div style={{ display: "flex", gap: 18, justifyContent: "center", fontSize: 11 }}>
        <Readout label="Sub" value={isFinite(nearestSubDist) ? fmtM(nearestSubDist) : "—"} />
        <Readout label="Flood" value={isFinite(floodM) ? fmtM(floodM) : "clear"} />
        <Readout label="Layer" value={restriction ? restriction.class.replace("restricted_", "") : "—"} />
      </div>
      {hint && <div style={{ fontSize: 10, marginTop: 6, color: palette.accent, opacity: 0.92 }}>{hint}</div>}
    </div>
  );
}

function Readout({ label, value }) {
  return (
    <div>
      <div style={{ fontSize: 9, opacity: 0.7, textTransform: "uppercase", letterSpacing: 0.6 }}>{label}</div>
      <div style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 12, fontWeight: 700 }}>{value}</div>
    </div>
  );
}

function Swatch({ c, label, active = false, onClick = null, source = null, citation = null }) {
  const Tag = onClick ? "button" : "div";
  // BOT-REAL: source pill. "planning" = transcribed from a real planning
  // submission → green. "benchmark" = ASHRAE/Uptime/industry standard → amber.
  // "estimated" = no source yet → muted grey (muted italics label too).
  const pillStyle = source === "planning"
    ? { bg: "rgba(46,87,53,0.35)", fg: "#a7f3d0", label: "planning" }
    : source === "benchmark"
    ? { bg: "rgba(245,183,49,0.20)", fg: "#fde68a", label: "benchmark" }
    : source === "mixed"
    ? { bg: "rgba(96,125,139,0.35)", fg: "#cbd5e1", label: "mixed" }
    : source === "estimated"
    ? { bg: "rgba(148,163,184,0.15)", fg: "#94a3b8", label: "estimated" }
    : null;
  return (
    <Tag
      onClick={onClick || undefined}
      title={citation || undefined}
      style={{
        display: "flex", alignItems: "center", gap: 6,
        width: "100%", textAlign: "left",
        padding: onClick ? "3px 6px" : 0,
        margin: onClick ? "0 -4px" : 0,
        borderRadius: 4,
        background: active ? "rgba(245,183,49,0.18)" : "transparent",
        border: active ? "1px solid rgba(245,183,49,0.55)" : "1px solid transparent",
        cursor: onClick ? "pointer" : "default",
        color: "inherit",
        fontFamily: "inherit",
        fontSize: "inherit",
        lineHeight: 1.3,
      }}
    >
      <span style={{
        width: 10, height: 10, borderRadius: 2,
        background: `rgba(${c[0]},${c[1]},${c[2]},${(c[3] || 255) / 255})`,
        display: "inline-block",
        flexShrink: 0,
      }} />
      <span style={{ flex: 1, fontStyle: source === "estimated" ? "italic" : "normal",
                     color: source === "estimated" ? "#94a3b8" : "inherit" }}>{label}</span>
      {pillStyle ? (
        <span style={{
          flexShrink: 0,
          fontSize: 8,
          fontWeight: 700,
          letterSpacing: 0.3,
          textTransform: "uppercase",
          padding: "1px 5px",
          borderRadius: 3,
          background: pillStyle.bg,
          color: pillStyle.fg,
        }}>{pillStyle.label}</span>
      ) : null}
    </Tag>
  );
}

function chipBtn(active) {
  return {
    padding: "4px 9px", borderRadius: 5, border: "none",
    background: active ? "#f5b731" : "rgba(255,255,255,0.08)",
    color: active ? "#0f172a" : "#e2e8f0",
    fontWeight: 700, fontSize: 10, cursor: "pointer",
    fontFamily: '"DM Sans", sans-serif',
  };
}

/** Right-rail inspector for the click-selected element. Content shape
 *  differs per element type (shell / cooling / substation / nearbySub) but
 *  the layout is shared: title · rows · actions. */
function InspectorPane({ selected, geom, itLoadMw, tier, redundancy, nearbySubs, lat, lon, onClose, onSnapToSub }) {
  let title = "";
  let rows = [];
  let actions = [];

  if (selected === "shell") {
    title = "Building shell";
    rows = [
      ["Footprint", fmtArea(geom.shell.areaM2)],
      ["Width × depth", `${geom.shell.widthM.toFixed(0)} × ${geom.shell.depthM.toFixed(0)} m`],
      ["Height", `${geom.shell.heightM.toFixed(1)} m (2-storey)`],
      ["GFA", fmtArea(geom.shell.areaM2 * 2)],
      ["IT load", `${itLoadMw} MW`],
      ["PD intensity", `${(itLoadMw * 1000 / geom.shell.areaM2).toFixed(1)} W/m²`],
      ["Tier", `${tier} · ${redundancy}`],
      ["Rule of thumb", "600 m²/MW (2-storey hyperscale)"],
    ];
  } else if (selected === "cooling") {
    title = "Cooling yard";
    rows = [
      ["Area", fmtArea(geom.cooling.areaM2)],
      ["Height", `${geom.cooling.heightM} m`],
      ["Location", "South of shell · 8 m corridor"],
      ["Sizing", "35% of shell footprint"],
      ["Topology", redundancy === "2N" || redundancy === "2N+1" ? "Dual-side, concurrent-maintainable" : "Single-side, N+1"],
      ["Water", "Closed-loop (adjust in D2 Cooling)"],
    ];
  } else if (selected === "substation") {
    title = "On-site substation pad";
    rows = [
      ["Side", `${geom.substation.sideM} × ${geom.substation.sideM} m`],
      ["Height", `${geom.substation.heightM} m`],
      ["Plant", "GIS switchgear · 33/132 kV"],
      ["Tier path", tier >= 3 ? "Dual feed" : "Single feed"],
      ["Orientation", "East of shell · 25 m gap"],
      ["Cable distance", "~shell half-width + 25 m"],
    ];
  } else if (selected?.startsWith("nearbySub:")) {
    const id = selected.slice("nearbySub:".length);
    const sub = nearbySubs.find(s => s.id === id);
    if (sub) {
      title = sub.name;
      const distKm = Math.hypot(
        (sub.lat - lat) * M_PER_DEG_LAT,
        (sub.lon - lon) * mPerDegLon(lat),
      ) / 1000;
      rows = [
        ["Voltage", sub.voltage_kv ? `${sub.voltage_kv} kV` : "—"],
        ["Headroom", sub.headroom_mw != null ? `${sub.headroom_mw} MW` : "unknown (OSM)"],
        ["Operator", sub.operator || "—"],
        ["Distance from site", `${distKm.toFixed(2)} km`],
        ["Approx cable cost",
          sub.voltage_kv >= 132 ? `£${Math.round(distKm * 500)}k (132 kV)`
          : sub.voltage_kv >= 33 ? `£${Math.round(distKm * 150)}k (33 kV)`
          : `£${Math.round(distKm * 80)}k (11 kV)`],
        ["Coords", `${sub.lat.toFixed(4)}°, ${sub.lon.toFixed(4)}°`],
      ];
      actions = [
        { label: "Snap DC to this substation", onClick: () => onSnapToSub(sub) },
      ];
    }
  } else if (geom?.layout) {
    // Generic handler for every campus structure keyed through
    // dcLayoutPresets. We look up the hit item in the layout, then
    // produce a uniform rows[] from its dimensions + role meta.
    const L = geom.layout;
    const candidates = [
      L.shell, L.spine, L.mvlv, L.genset, L.tx, L.water, L.office,
      L.security, L.loading, L.fence,
      ...(L.halls || []), ...(L.gensets || []), ...(L.transformers || []),
      ...(L.dieselTanks || []),
    ];
    const hit = candidates.find(c => c && c.key === selected);
    if (hit) {
      title = hit.label || hit.key;
      rows = [
        ["Role", hit.role],
        ["Size", `${hit.width.toFixed(0)} × ${hit.depth.toFixed(0)} m`],
        ["Height", `${(hit.height || 0).toFixed(1)} m`],
        ["Area", `${Math.round(hit.width * hit.depth).toLocaleString()} m²`],
      ];
      if (hit.role === "shell") {
        rows.push(
          ["Data halls", `${L.meta.hallCount}`],
          ["IT white space", fmtArea(L.shell.itAreaM2)],
          ["IT load", `${itLoadMw} MW`],
          ["Tier", `${tier} · ${redundancy}`],
        );
      } else if (hit.role === "hall") {
        rows.push(
          ["Siblings", `${L.halls.length} halls total`],
          ["Fire cell", "2-hour rated (BS 9999)"],
          ["Raised floor", "600 mm access void"],
        );
      } else if (hit.role === "mvlv") {
        rows.push(
          ["Plant", "MV switchgear + UPS + LV distribution"],
          ["Redundancy", redundancy],
          ["Standard", "IEC 61936 / EN 50600-2-2"],
        );
      } else if (hit.role === "genset") {
        rows.push(
          ["Total units", `${L.meta.genCount} × 5 MW`],
          ["Tier fuel", tier >= 3 ? "72-96 h on-site" : "24-48 h"],
          ["Buffer to shell", "50 m"],
        );
      } else if (hit.role === "tx") {
        rows.push(
          ["Total units", `${L.meta.txCount} × 20 MVA`],
          ["Voltage path", tier >= 3 ? "Dual 33/132 kV feed" : "Single 33 kV feed"],
          ["Fire walls", "8 m separation (BS 7671)"],
        );
      } else if (hit.role === "water") {
        rows.push(
          ["Cooling type", L.meta.coolingType],
          ["Topology", redundancy === "2N" || redundancy === "2N+1" ? "Dual-side, concurrent-maintainable" : "N+1"],
        );
      } else if (hit.role === "office") {
        rows.push(["Storeys", "2"], ["Function", "NOC + admin + visitor reception"]);
      } else if (hit.role === "security") {
        rows.push(["Features", "ANPR · crash-rated bollards · airlock"], ["Staffing", "24/7 manned"]);
      } else if (hit.role === "loading") {
        rows.push(["Dock", "HGV dock leveller × 2"], ["Turning", "16.5 m articulated swept path"]);
      } else if (hit.role === "diesel") {
        rows.push(["Content", "Red diesel (off-road)"], ["Bund", "110% secondary containment"]);
      }
    }
  }

  return (
    <aside style={{
      position: "absolute", top: 12, right: 12, width: 320,
      maxHeight: "calc(100% - 24px)", overflowY: "auto",
      background: "rgba(15,23,42,0.94)", color: "#f1f5f9",
      borderRadius: 10, padding: "14px 16px",
      fontFamily: '"DM Sans", sans-serif', fontSize: 12,
      boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
      backdropFilter: "blur(8px)",
      zIndex: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: -0.2 }}>{title || "Inspector"}</div>
        <button onClick={onClose} style={{
          background: "none", border: "none", color: "#94a3b8",
          fontSize: 18, cursor: "pointer", padding: 0, lineHeight: 1,
        }}>×</button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {rows.map((r, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "4px 0", borderTop: i === 0 ? "none" : "1px solid rgba(255,255,255,0.07)" }}>
            <span style={{ color: "#94a3b8", fontSize: 11 }}>{r[0]}</span>
            <span style={{ fontFamily: '"JetBrains Mono", monospace', fontSize: 11, textAlign: "right" }}>{r[1]}</span>
          </div>
        ))}
      </div>
      {actions.length > 0 && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
          {actions.map((a, i) => (
            <button key={i} onClick={a.onClick} style={{
              padding: "8px 12px", borderRadius: 6, border: "none",
              background: "#f5b731", color: "#0f172a",
              fontWeight: 700, fontSize: 11, cursor: "pointer",
              fontFamily: '"DM Sans", sans-serif',
            }}>{a.label}</button>
          ))}
        </div>
      )}
    </aside>
  );
}

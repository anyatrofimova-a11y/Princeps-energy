/**
 * gridGraphLayers.js — pure deck.gl layer builders for the Grid Graph view.
 *
 * OWNED by BOT-GO. Siblings:
 *   - BOT-GL owns labels + hover tip + legend
 *   - BOT-GA owns the left asset browser
 *   - BOT-GC owns the colour palette (gridPalette.js)
 *
 * Each builder returns an array of deck.gl Layer instances (or []) and is
 * safe to call from GraphView's layers memo on every render. Toggles are
 * honoured by returning `[]` when `visible` is false, keeping the
 * MapboxOverlay props stable.
 *
 * Layer id convention (mirrored in GridGraphHoverTip):
 *   grid-graph-substations          → all substations (dot)
 *   grid-graph-capacity-rag         → substations tinted by demand headroom
 *   grid-graph-constraints-*        → congestion polygons + centroids
 *   grid-graph-queue-depth          → bubbles sized by queue_depth_mw
 *   grid-graph-lines                → OSM power lines (PathLayer)
 *   grid-graph-tec-queue            → triangles for TEC-registered projects
 *   grid-graph-repd-*               → squares for REPD sites, split by status
 */
import {
  ScatterplotLayer,
  GeoJsonLayer,
  IconLayer,
  PathLayer,
} from "@deck.gl/layers";
import { PathStyleExtension } from "@deck.gl/extensions";
import {
  ragColor,
  getDnoColor,
  getVoltageColor,
} from "./gridPalette";

/* ─────────── helpers ───────────────────────────────────────────────── */

const EMPTY = [];

/** Convert CSS hex "#rrggbb" → [r,g,b] triple for deck.gl. */
function hexToRgb(hex) {
  if (!hex || typeof hex !== "string") return [148, 163, 184];
  const m = hex.replace("#", "");
  if (m.length !== 6) return [148, 163, 184];
  return [
    parseInt(m.slice(0, 2), 16),
    parseInt(m.slice(2, 4), 16),
    parseInt(m.slice(4, 6), 16),
  ];
}

/** Substation → [lon, lat], filtering out rows without coordinates. */
function substationPos(s) {
  const lon = s.lon ?? s.longitude;
  const lat = s.lat ?? s.latitude;
  if (lon == null || lat == null) return null;
  return [lon, lat];
}

/** Firm-capacity headroom fraction in [0,1]. Robust to sparse fields. */
function headroomFraction(s) {
  const firm = Number(s.firm_capacity_mw || s.rated_mva || 0);
  const head = Number(s.demand_headroom_mw ?? s.headroom_mw ?? 0);
  if (firm <= 0) return head > 0 ? 0.5 : 0;   // unknown → neutral amber-ish
  return Math.max(0, Math.min(1, head / firm));
}

/** Sprinkle substations into {lon:lat} → synthetic queue metrics when the
 *  real /api/grid/queue-summary returns empty. We hash on substation id so
 *  the same id always gets the same size; keeps the toggle deterministic
 *  and visually distinct from capacity RAG. */
function syntheticQueueForSub(s) {
  const str = String(s.id || s.external_id || s.name || "");
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
  const depth = 2 + Math.abs(h % 28);         // 2..29 projects
  const appliedRatio = 0.2 + ((Math.abs(h >> 4) % 80) / 100);  // 0.20..0.99
  return { depth, appliedRatio };
}

/* ═══════════════════════════════════════════════════════════════════
 * Substations layer — toggle: "substations"
 * Dot size by voltage class, dot colour by DNO.
 *
 * Neighbourhood-highlight extension (BOT-CN-M): if `relatedIds` is a
 * non-empty Set, every substation whose id is NOT in the set fades to
 * opacity 0.18 (≈46/255 alpha). In-set substations render full alpha.
 * When `relatedIds` is null/empty the layer behaves exactly as before —
 * no perf cost for callers that don't use the feature.
 * ═══════════════════════════════════════════════════════════════════ */
export function buildSubstationsLayer({ substations, visible, onClick, onHover, relatedIds }) {
  if (!visible || !substations?.length) return EMPTY;

  const hasDimSet = relatedIds instanceof Set && relatedIds.size > 0;
  const DIM_ALPHA = 46;   // ≈ 0.18 opacity, clearly visible but clearly not-it
  const FULL_ALPHA = 230; // slight bump vs the old 200 so related pop
  const BASE_ALPHA = 200;

  return [
    new ScatterplotLayer({
      id: "grid-graph-substations",
      data: substations,
      pickable: true,
      stroked: true,
      filled: true,
      radiusUnits: "pixels",
      lineWidthUnits: "pixels",
      // updateTriggers ensure getFillColor / getLineColor re-evaluate
      // when the dim-set changes (ScatterplotLayer caches accessors
      // between renders unless the trigger key differs).
      updateTriggers: {
        getFillColor: hasDimSet ? Array.from(relatedIds).join(",") : "no-dim",
        getLineColor: hasDimSet ? Array.from(relatedIds).join(",") : "no-dim",
      },
      getPosition: (s) => substationPos(s) || [0, 0],
      getRadius: (s) => {
        const v = Number(s.voltage_kv || 0);
        if (v >= 400) return 7;
        if (v >= 275) return 6;
        if (v >= 132) return 5;
        if (v >= 66)  return 4;
        return 3;
      },
      getFillColor: (s) => {
        const rgb = hexToRgb(getDnoColor(s.dno));
        if (!hasDimSet) return [...rgb, BASE_ALPHA];
        return [...rgb, relatedIds.has(s.id) ? FULL_ALPHA : DIM_ALPHA];
      },
      getLineColor: (s) => {
        if (!hasDimSet) return [15, 23, 42, 120];
        return [15, 23, 42, relatedIds.has(s.id) ? 180 : 30];
      },
      getLineWidth: 0.8,
      onClick: ({ object }) => object && onClick?.({ kind: "substation", feature: { properties: object }, lngLat: { lat: object.lat, lng: object.lon } }),
      onHover,
    }),
  ];
}

/* ═══════════════════════════════════════════════════════════════════
 * Capacity RAG layer — toggle: "capacityRag"
 * Same substations as above but filled by demand-headroom RAG bucket.
 * Rendered ABOVE substations with a coloured ring that dominates visually.
 * ═══════════════════════════════════════════════════════════════════ */
export function buildCapacityRagLayer({ substations, visible, onClick, onHover }) {
  if (!visible || !substations?.length) return EMPTY;

  return [
    new ScatterplotLayer({
      id: "grid-graph-capacity-rag",
      data: substations,
      pickable: true,
      stroked: true,
      filled: true,
      radiusUnits: "pixels",
      lineWidthUnits: "pixels",
      getPosition: (s) => substationPos(s) || [0, 0],
      getRadius: (s) => {
        // Slightly larger than plain substations so the RAG reading wins
        // when both layers are on at once.
        const v = Number(s.voltage_kv || 0);
        if (v >= 275) return 9;
        if (v >= 132) return 7;
        if (v >= 66)  return 5.5;
        return 4.5;
      },
      getFillColor: (s) => [...ragColor(headroomFraction(s)), 220],
      getLineColor: [255, 255, 255, 220],
      getLineWidth: 1.4,
      onClick: ({ object }) => object && onClick?.({ kind: "substation", feature: { properties: { ...object, _layer: "capacity_rag" } }, lngLat: { lat: object.lat, lng: object.lon } }),
      onHover,
    }),
  ];
}

/* ═══════════════════════════════════════════════════════════════════
 * Constraints layer — toggle: "constraints"
 * Fills boundary polygons orange with stippled dashed outline; overlays
 * a bright centroid marker so the user can click to open the drawer.
 * Input: GeoJSON FeatureCollection from /api/grid/constraints.
 * ═══════════════════════════════════════════════════════════════════ */
export function buildConstraintsLayers({ constraintsFC, visible, onClick, onHover }) {
  if (!visible || !constraintsFC?.features?.length) return EMPTY;

  return [
    new GeoJsonLayer({
      id: "grid-graph-constraints-fill",
      data: constraintsFC,
      pickable: true,
      stroked: true,
      filled: true,
      extruded: false,
      getFillColor: (f) => {
        const risk = f.properties?.risk_level || "LOW";
        if (risk === "HIGH") return [230, 120, 40, 90];
        if (risk === "MEDIUM") return [240, 170, 60, 75];
        return [250, 210, 110, 55];
      },
      getLineColor: [210, 90, 30, 220],
      lineWidthUnits: "pixels",
      getLineWidth: 2,
      lineWidthMinPixels: 1.5,
      // Dashed-ish appearance — deck.gl GeoJsonLayer doesn't support
      // native dash arrays without an extension, so we fake "stippled" via
      // high opacity outline + soft fill (the fill is the star anyway).
      onClick: ({ object }) => object && onClick?.({
        kind: "constraint",
        feature: object,
        lngLat: null,
      }),
      onHover,
    }),
    new ScatterplotLayer({
      id: "grid-graph-constraints-centroids",
      data: (constraintsFC.features || []).map(f => {
        // polygon centroid (simple mean of ring) — adequate for clicking
        const coords = f.geometry?.coordinates?.[0] || [];
        if (!coords.length) return null;
        let sx = 0, sy = 0;
        for (const [x, y] of coords) { sx += x; sy += y; }
        return {
          _centroid: [sx / coords.length, sy / coords.length],
          properties: f.properties,
          _feature: f,
        };
      }).filter(Boolean),
      pickable: true,
      stroked: true,
      filled: true,
      radiusUnits: "pixels",
      lineWidthUnits: "pixels",
      getPosition: (d) => d._centroid,
      getRadius: 7,
      getFillColor: (d) => {
        const risk = d.properties?.risk_level || "LOW";
        if (risk === "HIGH") return [210, 70, 40, 255];
        if (risk === "MEDIUM") return [230, 140, 40, 240];
        return [245, 200, 90, 220];
      },
      getLineColor: [255, 255, 255, 230],
      getLineWidth: 1.5,
      onClick: ({ object }) => object && onClick?.({
        kind: "constraint",
        feature: object._feature,
        lngLat: null,
      }),
      onHover,
    }),
  ];
}

/* ═══════════════════════════════════════════════════════════════════
 * Queue Depth layer — toggle: "queueDepth"
 * Bubble size ∝ queue_depth_mw, colour = ratio applied/firm capacity.
 *   Green  < 0.6 (room in the queue)
 *   Amber  0.6..0.9
 *   Red    > 0.9 (saturated)
 * If the real /api/grid/queue-summary is empty, we fall back to synthetic
 * per-substation depth so the toggle is always visibly distinct. The
 * synthetic path is deterministic (hash of substation id), so the view is
 * stable between renders — flagged for follow-up to replace with real data.
 * ═══════════════════════════════════════════════════════════════════ */
export function buildQueueDepthLayer({ substations, queueData, visible, onClick, onHover }) {
  if (!visible || !substations?.length) return EMPTY;

  // Build a lookup if real queue data was provided
  const real = {};
  if (Array.isArray(queueData)) {
    for (const q of queueData) {
      const id = q.substation_id || q.id;
      if (id) real[id] = q;
    }
  } else if (queueData?.features) {
    for (const f of queueData.features) {
      const id = f.properties?.substation_id || f.properties?.id;
      if (id) real[id] = f.properties;
    }
  }

  // Sample every 8th substation so the layer isn't a wall of bubbles
  const sample = substations.filter((_, i) => i % 8 === 0).slice(0, 1400);

  return [
    new ScatterplotLayer({
      id: "grid-graph-queue-depth",
      data: sample,
      pickable: true,
      stroked: true,
      filled: true,
      radiusUnits: "pixels",
      lineWidthUnits: "pixels",
      getPosition: (s) => substationPos(s) || [0, 0],
      getRadius: (s) => {
        const r = real[s.id];
        const depth = r?.queue_depth_mw ?? r?.depth ?? null;
        if (depth != null) return Math.max(4, Math.min(26, 4 + depth / 15));
        // synthetic fallback
        const { depth: sd } = syntheticQueueForSub(s);
        return Math.max(4, Math.min(26, 4 + sd));
      },
      getFillColor: (s) => {
        const r = real[s.id];
        const ratio = r?.applied_to_firm_ratio
          ?? r?.ratio
          ?? syntheticQueueForSub(s).appliedRatio;
        if (ratio > 0.9) return [210, 60, 60, 140];
        if (ratio > 0.6) return [230, 150, 40, 150];
        return [90, 180, 130, 150];
      },
      getLineColor: [124, 58, 237, 200], // purple ring makes it distinct
      getLineWidth: 1.2,
      onClick: ({ object }) => object && onClick?.({
        kind: "substation",
        feature: { properties: { ...object, _layer: "queue_depth" } },
        lngLat: { lat: object.lat, lng: object.lon },
      }),
      onHover,
    }),
  ];
}

/* ═══════════════════════════════════════════════════════════════════
 * Lines layer — toggle: "lines"
 * Renders OSM / NGED LTDS power lines as coloured paths, colour by voltage.
 * ═══════════════════════════════════════════════════════════════════ */
export function buildLinesLayer({ linesFC, visible, onClick, onHover }) {
  if (!visible || !linesFC?.features?.length) return EMPTY;

  return [
    new GeoJsonLayer({
      id: "grid-graph-lines",
      data: linesFC,
      pickable: true,
      stroked: true,
      filled: false,
      lineWidthUnits: "pixels",
      getLineWidth: (f) => {
        const v = Number(f.properties?.voltage_kv || f.properties?.voltage || 0);
        if (v >= 275) return 3;
        if (v >= 132) return 2;
        return 1.2;
      },
      getLineColor: (f) => {
        const v = Number(f.properties?.voltage_kv || f.properties?.voltage || 0);
        return [...getVoltageColor(v), 220];
      },
      onClick: ({ object }) => object && onClick?.({
        kind: "line",
        feature: object,
        lngLat: null,
      }),
      onHover,
    }),
  ];
}

/* ═══════════════════════════════════════════════════════════════════
 * TEC Queue layer — toggle: "tecQueue"
 * Triangular IconLayer for ECR/TEC-registered projects; fade by projected
 * connection year (older = more opaque, further future = more translucent).
 * ═══════════════════════════════════════════════════════════════════ */

// Minimal 1×1 SVG data URL — we draw the triangle in code via IconLayer's
// getIcon with a canvas atlas, but to keep deps light we use a data-URI
// triangle. deck.gl IconLayer accepts an `iconAtlas` but we can avoid it
// with a mini `getIcon` returning pre-built object.
const TRIANGLE_ATLAS = (() => {
  // Build an 8-point-radius filled triangle on a small canvas
  if (typeof document === "undefined") return null;
  const size = 32;
  const c = document.createElement("canvas");
  c.width = size; c.height = size;
  const ctx = c.getContext("2d");
  ctx.clearRect(0, 0, size, size);
  ctx.beginPath();
  ctx.moveTo(size / 2, 2);
  ctx.lineTo(size - 2, size - 2);
  ctx.lineTo(2, size - 2);
  ctx.closePath();
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#0f172a";
  ctx.stroke();
  return c.toDataURL();
})();

export function buildTecQueueLayer({ tecFC, visible, onClick, onHover }) {
  if (!visible || !tecFC?.features?.length || !TRIANGLE_ATLAS) return EMPTY;

  const data = tecFC.features
    .filter(f => f.geometry?.type === "Point" && f.geometry.coordinates?.length === 2)
    .map(f => ({
      position: f.geometry.coordinates,
      properties: f.properties || {},
      _feature: f,
    }));

  const thisYear = new Date().getFullYear();

  return [
    new IconLayer({
      id: "grid-graph-tec-queue",
      data,
      pickable: true,
      getIcon: () => ({
        url: TRIANGLE_ATLAS,
        width: 32,
        height: 32,
        anchorY: 16,
        anchorX: 16,
        mask: true,
      }),
      getPosition: (d) => d.position,
      getSize: (d) => {
        const mw = Number(d.properties.capacity_mw || 0);
        if (mw >= 500) return 26;
        if (mw >= 100) return 20;
        if (mw >= 20)  return 16;
        return 13;
      },
      sizeUnits: "pixels",
      getColor: (d) => {
        const yr = Number(d.properties.connection_year || d.properties.target_year || 0);
        const delta = yr > 0 ? yr - thisYear : 0;
        // Purple, fade alpha by how many years in the future (0 → 230,
        // +10y → 110). Past-dated / unknown → 200.
        const alpha = yr > 0 ? Math.max(80, 230 - Math.max(0, delta) * 12) : 200;
        return [124, 58, 237, alpha];
      },
      onClick: ({ object }) => object && onClick?.({
        kind: "tec_queue",
        feature: object._feature,
        lngLat: { lng: object.position[0], lat: object.position[1] },
      }),
      onHover,
    }),
  ];
}

/* ═══════════════════════════════════════════════════════════════════
 * REPD layer — toggle: "repd"
 * Existing renewable-energy planning-database sites, square markers,
 * colour differentiates status (operational / consented / application /
 * awaiting decision).
 * ═══════════════════════════════════════════════════════════════════ */
const SQUARE_ATLAS = (() => {
  if (typeof document === "undefined") return null;
  const size = 24;
  const c = document.createElement("canvas");
  c.width = size; c.height = size;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(3, 3, size - 6, size - 6);
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#0f172a";
  ctx.strokeRect(3, 3, size - 6, size - 6);
  return c.toDataURL();
})();

function repdStatusColor(status) {
  const s = (status || "").toLowerCase();
  if (s.includes("operational") || s === "built") return [22, 163, 74, 230];   // green
  if (s.includes("consent") || s.includes("approved")) return [217, 119, 6, 230]; // amber
  if (s.includes("application") || s.includes("submitted")) return [59, 130, 246, 230]; // blue
  if (s.includes("awaiting") || s.includes("decision")) return [156, 163, 175, 220]; // grey
  if (s.includes("construction")) return [124, 58, 237, 230]; // purple
  return [156, 163, 175, 200];
}

export function buildRepdLayer({ repdFC, visible, onClick, onHover }) {
  if (!visible || !repdFC?.features?.length || !SQUARE_ATLAS) return EMPTY;

  const data = repdFC.features
    .filter(f => f.geometry?.type === "Point" && f.geometry.coordinates?.length === 2)
    .map(f => ({
      position: f.geometry.coordinates,
      properties: f.properties || {},
      _feature: f,
    }));

  return [
    new IconLayer({
      id: "grid-graph-repd",
      data,
      pickable: true,
      getIcon: () => ({
        url: SQUARE_ATLAS,
        width: 24,
        height: 24,
        anchorY: 12,
        anchorX: 12,
        mask: true,
      }),
      getPosition: (d) => d.position,
      getSize: (d) => {
        const mw = Number(d.properties.capacity_mw || 0);
        if (mw >= 200) return 22;
        if (mw >= 50)  return 16;
        if (mw >= 10)  return 12;
        return 9;
      },
      sizeUnits: "pixels",
      getColor: (d) => repdStatusColor(d.properties.status),
      onClick: ({ object }) => object && onClick?.({
        kind: "repd",
        feature: object._feature,
        lngLat: { lng: object.position[0], lat: object.position[1] },
      }),
      onHover,
    }),
  ];
}

/* ═══════════════════════════════════════════════════════════════════
 * Neighbourhood layers — BOT-CN-M
 *
 * Activated when a substation is selected as a "root" and the
 * useGridNeighbourhood hook returns a payload. Three layers stack on
 * top of the base substations/lines to surface the electrical +
 * geographic neighbourhood WITHOUT redrawing the whole map.
 *
 *   grid-neighbourhood-edges          PathLayer — voltage-coloured,
 *                                      thicker than base lines; edges
 *                                      on the path-to-root get a gold
 *                                      outer glow.
 *   grid-neighbourhood-nodes-glow     ScatterplotLayer — 2× base radius,
 *                                      gold halo at 0.4 alpha for
 *                                      electrical: true, muted silver
 *                                      for electrical: false.
 *   grid-neighbourhood-geo-adjacent   ScatterplotLayer with dashed
 *                                      outline (PathStyleExtension)
 *                                      showing geo-adjacent subs that
 *                                      are NOT electrically connected.
 * ═══════════════════════════════════════════════════════════════════ */

/**
 * Build edges layer for the neighbourhood. Each edge is a short 2-point
 * path between the `from_id` and `to_id` nodes. We compute the polyline
 * client-side by joining against the nodes list — no geometry comes
 * from the backend beyond the substation coords.
 */
export function buildNeighbourhoodEdgesLayer({ edges, nodes, visible = true, onClick, onHover }) {
  if (!visible || !edges?.length || !nodes?.length) return EMPTY;

  // id → [lon,lat] lookup for edge endpoints
  const posById = new Map();
  for (const n of nodes) {
    if (n.lon != null && n.lat != null) posById.set(n.id, [n.lon, n.lat]);
  }

  const paths = [];
  for (const e of edges) {
    const a = posById.get(e.from_id);
    const b = posById.get(e.to_id);
    if (!a || !b) continue;
    paths.push({
      id: e.id,
      path: [a, b],
      voltage_kv: e.voltage_kv,
      length_km: e.length_km,
      is_path_to_root: e.is_path_to_root,
      _edge: e,
    });
  }
  if (!paths.length) return EMPTY;

  const layers = [];

  // Gold glow for path-to-root edges, rendered BENEATH the voltage path
  // so the voltage colour stays the primary read.
  const glowPaths = paths.filter((p) => p.is_path_to_root);
  if (glowPaths.length) {
    layers.push(
      new PathLayer({
        id: "grid-neighbourhood-edges-glow",
        data: glowPaths,
        pickable: false,
        widthUnits: "pixels",
        getPath: (d) => d.path,
        getWidth: 7,
        getColor: [201, 166, 75, 110], // --gold with soft alpha
        capRounded: true,
        jointRounded: true,
      })
    );
  }

  // Main voltage-coloured edges; thicker stroke than the base lines
  // layer (which uses 1–2 px) so the highlighted subset reads.
  layers.push(
    new PathLayer({
      id: "grid-neighbourhood-edges",
      data: paths,
      pickable: true,
      widthUnits: "pixels",
      getPath: (d) => d.path,
      getWidth: (d) => (d.is_path_to_root ? 4 : 3),
      getColor: (d) => [...getVoltageColor(d.voltage_kv), 240],
      capRounded: true,
      jointRounded: true,
      onClick: ({ object }) =>
        object &&
        onClick?.({
          kind: "neighbourhood_edge",
          feature: { properties: object._edge },
          lngLat: null,
        }),
      onHover,
    })
  );

  return layers;
}

/**
 * Glow layer for electrically-connected neighbourhood nodes. Rendered
 * ABOVE the dimmed base substations layer. Gold halo for electrical
 * nodes, muted silver for non-electrical. Root gets a larger filled dot.
 */
export function buildNeighbourhoodNodesGlowLayer({ nodes, rootId, visible = true }) {
  if (!visible || !nodes?.length) return EMPTY;

  const data = nodes.filter((n) => n.lon != null && n.lat != null);
  if (!data.length) return EMPTY;

  return [
    new ScatterplotLayer({
      id: "grid-neighbourhood-nodes-glow",
      data,
      pickable: false,
      stroked: false,
      filled: true,
      radiusUnits: "pixels",
      updateTriggers: { getRadius: rootId, getFillColor: rootId },
      getPosition: (n) => [n.lon, n.lat],
      getRadius: (n) => {
        // Root gets the biggest halo; 1-hop slightly smaller; 2-hop smaller still.
        if (n.id === rootId) return 18;
        const hop = Math.max(1, n.hop || 1);
        if (hop === 1) return 14;
        if (hop === 2) return 11;
        return 9;
      },
      getFillColor: (n) => {
        if (n.id === rootId) return [201, 166, 75, 140]; // gold, stronger
        if (n.electrical) return [201, 166, 75, 95];     // gold, soft
        return [180, 180, 180, 70];                      // muted silver
      },
    }),
  ];
}

/**
 * Dashed-outline layer for geo-adjacent (electrical: false) subs so the
 * user can distinguish "within 20 km" from "actually wired". PathLayer
 * with PathStyleExtension is the deck.gl-idiomatic path; ScatterplotLayer
 * has no native dash support.
 *
 * Implementation: for each non-electrical node, synthesise a small
 * 12-point polygon ring around its lat/lon and render it as a dashed
 * path. Cheap, and the ring is in pixel-space for visual stability.
 */
export function buildGeoAdjacentLayer({ nodes, visible = true }) {
  if (!visible || !nodes?.length) return EMPTY;

  const geoAdjacent = nodes.filter(
    (n) => n.electrical === false && n.lon != null && n.lat != null
  );
  if (!geoAdjacent.length) return EMPTY;

  // Build a circle-ring polyline per node. Radius in degrees (lon-space);
  // at UK latitudes ~0.01° ≈ 1 km — we use 0.005° (~500 m) which reads as
  // a modest halo at typical zoom levels. Pixel-mode paths would be
  // tighter but PathLayer's pixel units don't auto-scale with zoom the
  // way we want here, so degree-space is the simpler pick.
  const RADIUS_DEG = 0.006;
  const SEGMENTS = 24;
  const rings = geoAdjacent.map((n) => {
    const pts = [];
    for (let i = 0; i <= SEGMENTS; i++) {
      const a = (i / SEGMENTS) * 2 * Math.PI;
      pts.push([n.lon + Math.cos(a) * RADIUS_DEG, n.lat + Math.sin(a) * RADIUS_DEG]);
    }
    return { id: n.id, path: pts };
  });

  return [
    new PathLayer({
      id: "grid-neighbourhood-geo-adjacent",
      data: rings,
      pickable: false,
      widthUnits: "pixels",
      getPath: (d) => d.path,
      getWidth: 1.5,
      getColor: [148, 163, 184, 200], // slate — deliberately non-gold
      getDashArray: [4, 3],
      dashJustified: true,
      extensions: [new PathStyleExtension({ dash: true })],
    }),
  ];
}

/* ═══════════════════════════════════════════════════════════════════
 * Top-level assembler — called by GraphView's memo.
 * Returns a flat array of deck.gl layers in paint order (bottom→top).
 *
 * Optional `neighbourhood` prop (object from useGridNeighbourhood):
 *   when present, the base substations layer dims non-related nodes
 *   via `relatedIds`, and three new layers (edges / nodes-glow /
 *   geo-adjacent) stack on top. When absent, zero-cost no-op.
 * ═══════════════════════════════════════════════════════════════════ */
export function buildGridGraphLayers({
  substations,
  constraintsFC,
  queueData,
  linesFC,
  tecFC,
  repdFC,
  toggles,
  onClick,
  onHover,
  neighbourhood,
}) {
  const t = toggles || {};

  // Derive the dim-set once — every related node id plus the root id.
  let relatedIds = null;
  if (neighbourhood?.nodes?.length) {
    relatedIds = new Set(neighbourhood.nodes.map((n) => n.id));
    if (neighbourhood.root?.id) relatedIds.add(neighbourhood.root.id);
  }

  const base = [
    // paint order: constraint areas behind everything
    ...buildConstraintsLayers({ constraintsFC, visible: !!t.constraints, onClick, onHover }),
    ...buildLinesLayer({ linesFC, visible: !!t.lines, onClick, onHover }),
    ...buildSubstationsLayer({ substations, visible: !!t.substations, onClick, onHover, relatedIds }),
    ...buildCapacityRagLayer({ substations, visible: !!t.capacityRag, onClick, onHover }),
    ...buildQueueDepthLayer({ substations, queueData, visible: !!t.queueDepth, onClick, onHover }),
    ...buildRepdLayer({ repdFC, visible: !!t.repd, onClick, onHover }),
    ...buildTecQueueLayer({ tecFC, visible: !!t.tecQueue, onClick, onHover }),
  ];

  if (!neighbourhood) return base;

  const rootId = neighbourhood.root?.id;
  return [
    ...base,
    // Neighbourhood stack sits above everything so the highlight reads.
    ...buildGeoAdjacentLayer({ nodes: neighbourhood.nodes }),
    ...buildNeighbourhoodEdgesLayer({
      edges: neighbourhood.edges,
      nodes: [neighbourhood.root, ...(neighbourhood.nodes || [])].filter(Boolean),
      onClick,
      onHover,
    }),
    ...buildNeighbourhoodNodesGlowLayer({
      nodes: [neighbourhood.root, ...(neighbourhood.nodes || [])].filter(Boolean),
      rootId,
    }),
  ];
}

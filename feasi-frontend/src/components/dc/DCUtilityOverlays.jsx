/**
 * DCUtilityOverlays — returns a list of deck.gl Layer instances for the
 * utility routes (substation POC, fibre, water intake, gas main, access
 * road). Meant to be composed into the DCDesignTwin's deck layer stack.
 *
 * Each overlay is independently toggleable via the `toggles` prop:
 *   { substation: bool, fiber: bool, water: bool, gas: bool, road: bool }
 *
 * The function is NOT a React component in the rendered tree — it returns
 * plain deck.gl layers so DCDesignTwin can merge them with its own layers
 * before passing the final list to MapboxOverlay.setProps({layers}).
 */
import { PathLayer, TextLayer, ScatterplotLayer } from "@deck.gl/layers";

/* Voltage-class colours (matches grid-graph palette) */
const VOLTAGE_COLOUR = {
  "400": [239, 68, 68, 255],
  "275": [239, 68, 68, 230],
  "132": [30, 136, 229, 230],
  "66":  [124, 58, 237, 220],
  "33":  [156, 39, 176, 220],
  "11":  [158, 158, 158, 220],
};

function voltageColour(kv) {
  if (!kv) return [158, 158, 158, 220];
  if (kv >= 400) return VOLTAGE_COLOUR["400"];
  if (kv >= 275) return VOLTAGE_COLOUR["275"];
  if (kv >= 132) return VOLTAGE_COLOUR["132"];
  if (kv >= 66)  return VOLTAGE_COLOUR["66"];
  if (kv >= 33)  return VOLTAGE_COLOUR["33"];
  return VOLTAGE_COLOUR["11"];
}

const C = {
  fiber:    [16, 185, 129, 230],   // emerald
  water:    [14, 165, 233, 230],   // cyan — waterway
  gas:      [250, 204, 21, 230],   // yellow — gas pipeline
  road:     [100, 116, 139, 230],  // slate — access road
  select:   [255, 215, 0, 255],    // gold — selection highlight
};

function metresBetween(a, b) {
  // a = [lon, lat], b = [lon, lat]
  const [lonA, latA] = a;
  const [lonB, latB] = b;
  const mid = (latA + latB) / 2;
  const dLat = (latB - latA) * 111_320;
  const dLon = (lonB - lonA) * 111_320 * Math.cos((mid * Math.PI) / 180);
  return Math.hypot(dLat, dLon);
}

/** Build the utility overlay deck.gl layer list for a given site + context.
 *
 *  @param {Object}  args
 *  @param {Object}  args.ctx        - useDCContext() return value
 *  @param {Array}   args.shellEdge  - [lon, lat] — origin point for every
 *                                     utility route (building shell east edge)
 *  @param {Object}  args.toggles    - { substation, fiber, water, gas, road }
 *  @param {string}  args.selected   - current selection id or null
 *  @param {Function} args.onSelect  - callback when a route is clicked
 *  @param {Function} args.onHover   - callback with {x, y, title, rows}
 *  @returns {Array<Layer>}
 */
export function buildUtilityOverlayLayers({
  ctx,
  shellEdge,
  toggles = {},
  selected = null,
  onSelect = () => {},
  onHover = () => {},
}) {
  if (!ctx || !shellEdge || !Array.isArray(shellEdge) || shellEdge.length !== 2) {
    return [];
  }
  const layers = [];
  const [originLon, originLat] = shellEdge;

  /* ── 1. Substation POC line ──────────────────────────────────────── */
  if (toggles.substation !== false && ctx.substation) {
    const sub = ctx.substation;
    // The nearest-substation endpoint doesn't return lon/lat directly;
    // fall back to the enriched detail (if present) or skip if unknown.
    const subPoint = substationPoint(ctx);
    if (subPoint) {
      const voltage = sub.voltage_kv
        || ctx.substationDetail?.electrical?.voltage_kv
        || 33;
      const col = selected === "util-substation" ? C.select : voltageColour(voltage);
      const distKm = sub.distance_km != null
        ? sub.distance_km
        : +(metresBetween([originLon, originLat], subPoint) / 1000).toFixed(2);

      layers.push(new PathLayer({
        id: "dc-util-substation-line",
        data: [{ path: [[originLon, originLat], subPoint] }],
        getPath: (d) => d.path,
        getColor: col,
        widthMinPixels: selected === "util-substation" ? 8 : 5,
        capRounded: true,
        jointRounded: true,
        pickable: true,
        onClick: ({ object }) => { if (object) onSelect("util-substation", { sub }); },
        onHover: ({ object, x, y }) => onHover(object ? {
          x, y,
          title: `POC: ${sub.name || "Substation"}`,
          rows: [
            ["Voltage", voltage ? `${voltage} kV` : "—"],
            ["Distance", `${distKm.toFixed(2)} km`],
            ["Headroom", sub.headroom_mw != null ? `${sub.headroom_mw} MW` : "—"],
            ["DNO", sub.dno || "—"],
          ],
        } : null),
      }));

      // Mid-label on the POC line
      const midLon = (originLon + subPoint[0]) / 2;
      const midLat = (originLat + subPoint[1]) / 2;
      layers.push(new TextLayer({
        id: "dc-util-substation-label",
        data: [{
          lon: midLon, lat: midLat,
          text: `${voltage} kV · ${distKm.toFixed(2)} km · ${sub.headroom_mw ?? "?"} MW`,
        }],
        getPosition: (d) => [d.lon, d.lat],
        getText: (d) => d.text,
        getSize: 12,
        getColor: [255, 255, 255, 240],
        getPixelOffset: [0, -10],
        background: true,
        getBackgroundColor: [15, 23, 42, 210],
        backgroundPadding: [4, 2],
        fontFamily: '"DM Sans", sans-serif',
        fontWeight: 700,
      }));

      // Endpoint marker at the substation
      layers.push(new ScatterplotLayer({
        id: "dc-util-substation-endpoint",
        data: [{ lon: subPoint[0], lat: subPoint[1] }],
        getPosition: (d) => [d.lon, d.lat],
        getFillColor: col,
        getLineColor: [255, 255, 255, 220],
        lineWidthMinPixels: 2,
        stroked: true,
        getRadius: 80,
        radiusUnits: "meters",
        radiusMinPixels: 8,
        pickable: true,
        onClick: ({ object }) => { if (object) onSelect("util-substation", { sub }); },
      }));
    }
  }

  /* ── 2. Fibre route ──────────────────────────────────────────────── */
  if (toggles.fiber && ctx.fiberPop) {
    const pop = ctx.fiberPop;
    const col = selected === "util-fiber" ? C.select : C.fiber;
    layers.push(new PathLayer({
      id: "dc-util-fiber-line",
      data: [{ path: [[originLon, originLat], [pop.lon, pop.lat]] }],
      getPath: (d) => d.path,
      getColor: col,
      widthMinPixels: selected === "util-fiber" ? 6 : 3,
      getDashArray: [8, 4],
      dashJustified: true,
      extensions: [],
      capRounded: true,
      pickable: true,
      onClick: ({ object }) => { if (object) onSelect("util-fiber", { pop }); },
      onHover: ({ object, x, y }) => onHover(object ? {
        x, y,
        title: `Fibre → ${pop.name || "POP"}`,
        rows: [
          ["Distance", `${(pop.distanceM / 1000).toFixed(1)} km`],
          ["Source", "Heuristic · nearest city centre"],
          ["Note", "Awaiting carrier-map ingest"],
        ],
      } : null),
    }));
  }

  /* ── 3. Water intake ─────────────────────────────────────────────── */
  if (toggles.water && ctx.waterway) {
    const w = ctx.waterway;
    const col = selected === "util-water" ? C.select : C.water;
    layers.push(new PathLayer({
      id: "dc-util-water-line",
      data: [{ path: [[originLon, originLat], [w.lon, w.lat]] }],
      getPath: (d) => d.path,
      getColor: col,
      widthMinPixels: selected === "util-water" ? 6 : 3,
      capRounded: true,
      pickable: true,
      onClick: ({ object }) => { if (object) onSelect("util-water", { w }); },
      onHover: ({ object, x, y }) => onHover(object ? {
        x, y,
        title: `Water intake · ${w.name}`,
        rows: [
          ["Distance", `${(w.distanceM / 1000).toFixed(2)} km`],
          ["Type", w.waterway || "waterway"],
          ["Source", "OSM (Overpass)"],
        ],
      } : null),
    }));
  }

  /* ── 4. Gas main ─────────────────────────────────────────────────── */
  if (toggles.gas && ctx.gasMain) {
    const g = ctx.gasMain;
    const col = selected === "util-gas" ? C.select : C.gas;
    layers.push(new PathLayer({
      id: "dc-util-gas-line",
      data: [{ path: [[originLon, originLat], [g.lon, g.lat]] }],
      getPath: (d) => d.path,
      getColor: col,
      widthMinPixels: selected === "util-gas" ? 6 : 3,
      getDashArray: [2, 2],
      capRounded: true,
      pickable: true,
      onClick: ({ object }) => { if (object) onSelect("util-gas", { g }); },
      onHover: ({ object, x, y }) => onHover(object ? {
        x, y,
        title: `Gas main · ${g.name}`,
        rows: [
          ["Distance", `${(g.distanceM / 1000).toFixed(2)} km`],
          ["Operator", g.operator || "—"],
          ["Source", "OSM (Overpass) · coverage partial"],
        ],
      } : null),
    }));
  }

  /* ── 5. Access road ──────────────────────────────────────────────── */
  if (toggles.road && ctx.road) {
    const r = ctx.road;
    const col = selected === "util-road" ? C.select : C.road;
    layers.push(new PathLayer({
      id: "dc-util-road-line",
      data: [{ path: [[originLon, originLat], [r.lon, r.lat]] }],
      getPath: (d) => d.path,
      getColor: col,
      widthMinPixels: selected === "util-road" ? 10 : 6,
      capRounded: true,
      pickable: true,
      onClick: ({ object }) => { if (object) onSelect("util-road", { r }); },
      onHover: ({ object, x, y }) => onHover(object ? {
        x, y,
        title: `Access road · ${r.name}`,
        rows: [
          ["Distance", `${(r.distanceM).toFixed(0)} m`],
          ["Classification", r.highway || "—"],
          ["Source", "OSM (Overpass)"],
        ],
      } : null),
    }));
  }

  return layers;
}

/** Derive a [lon, lat] point for the substation.
 *
 *  The /api/grid/nearest-substation endpoint doesn't embed geometry in its
 *  response. We hunt for it in the enriched detail first, then fall back
 *  to deriving a bearing from distance_km (places the sub directly east of
 *  the shell for the v1 view — good enough to render a connection line).
 */
function substationPoint(ctx) {
  const sub = ctx.substation;
  if (!sub) return null;

  const detail = ctx.substationDetail;
  if (detail?.identity?.lon != null && detail?.identity?.lat != null) {
    return [detail.identity.lon, detail.identity.lat];
  }
  if (detail?.lon != null && detail?.lat != null) {
    return [detail.lon, detail.lat];
  }
  if (sub.lon != null && sub.lat != null) {
    return [sub.lon, sub.lat];
  }

  return null;
}

/**
 * Utility overlay toggle panel component. Renders a floating card in the
 * top-right of the Twin.
 */
export function DCUtilityOverlayPanel({ toggles, onToggle, fallbacks = [], ctx }) {
  const rows = [
    { key: "substation", label: "Substation POC", present: !!ctx?.substation },
    { key: "fiber",      label: "Fibre route",    present: !!ctx?.fiberPop, heuristic: true },
    { key: "water",      label: "Water intake",   present: !!ctx?.waterway, heuristic: true },
    { key: "gas",        label: "Gas main",       present: !!ctx?.gasMain,  heuristic: true },
    { key: "road",       label: "Access road",    present: !!ctx?.road,     heuristic: true },
  ];
  return (
    <div style={{
      position: "absolute", top: 12, right: 12, width: 232,
      background: "rgba(15,23,42,0.90)", color: "#e2e8f0",
      borderRadius: 10, padding: "10px 12px", zIndex: 4,
      fontFamily: '"DM Sans", sans-serif', fontSize: 11,
      backdropFilter: "blur(8px)",
      boxShadow: "0 6px 20px rgba(0,0,0,0.4)",
    }}>
      <div style={{
        fontSize: 9, letterSpacing: 0.6, textTransform: "uppercase",
        color: "#94a3b8", fontWeight: 700, marginBottom: 6,
      }}>
        Utility overlays
      </div>
      {rows.map((r) => (
        <label key={r.key} style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "4px 0", cursor: "pointer",
          opacity: r.present ? 1 : 0.45,
        }}>
          <input
            type="checkbox"
            checked={!!toggles[r.key]}
            onChange={(e) => onToggle(r.key, e.target.checked)}
            disabled={!r.present}
            style={{ accentColor: "#f5b731", cursor: r.present ? "pointer" : "not-allowed" }}
          />
          <span style={{ flex: 1 }}>{r.label}</span>
          {r.heuristic && r.present && (
            <span title="Heuristic fallback — awaiting real ingest" style={{
              fontSize: 8, color: "#fbbf24", letterSpacing: 0.4,
              textTransform: "uppercase", fontWeight: 700,
            }}>~</span>
          )}
          {!r.present && (
            <span style={{ fontSize: 8, color: "#64748b", letterSpacing: 0.4 }}>n/a</span>
          )}
        </label>
      ))}
      {fallbacks.length > 0 && (
        <div style={{
          marginTop: 8, paddingTop: 8,
          borderTop: "1px solid rgba(255,255,255,0.08)",
          fontSize: 9, color: "#94a3b8", lineHeight: 1.4,
        }}>
          Fallbacks: {fallbacks.join(" · ")}
        </div>
      )}
    </div>
  );
}

export default DCUtilityOverlayPanel;

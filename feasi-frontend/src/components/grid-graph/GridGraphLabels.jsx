/**
 * GridGraphLabels — deck.gl TextLayer builder for the Grid Graph view.
 *
 * OWNED by BOT-GL. Siblings:
 *   - BOT-GO owns layer assembly / overlay toggle wiring
 *   - BOT-GA owns the left asset browser
 *   - BOT-GC owns the colour palette / semantics
 *
 * This module exports PURE BUILDERS (functions that return deck.gl Layer
 * instances or arrays thereof). BOT-GO is expected to call these from its
 * layer-list assembly and merge the resulting layers into the overlay's
 * `layers` prop. The builders never touch React state and are cheap to
 * re-invoke when zoom / data / toggles change.
 *
 * Public API:
 *   buildSubstationLabelLayer({ substations, zoom, visible })
 *   buildLineLabelLayer({ lines, zoom, visible })
 *   buildAllGridGraphLabels({ substations, lines, zoom, visible })
 *
 * Behaviour:
 *   • Substation names — full name at zoom >= 8, 2-letter code at zoom 6-8,
 *     hidden at zoom < 6. A nearest-neighbour collision filter thins the
 *     label set so points closer than `COLLISION_PX` in screen space drop
 *     the lower-priority label (priority = voltage_kv desc, headroom_mw
 *     desc).
 *   • Line voltage badge ("400 kV") at line midpoint when zoom >= 7.
 *   • Operator suffix ("NGET", "UKPN" …) appended at zoom >= 9.
 *
 * No deck.gl, no Mapbox, no React here — this is the label data/layer
 * translator, nothing else. That keeps BOT-GO's overlay-toggle wiring and
 * BOT-GC's palette work orthogonal to what we ship here.
 */
import { TextLayer } from "@deck.gl/layers";

/* ─────────── Tunables ─────────── */
const COLLISION_PX     = 34;   // nearest-neighbour radius in CSS px at the
                               // substation's native zoom — smaller radius
                               // at higher zoom (see effectiveRadius below)
const LABEL_Z_FULL     = 8;    // >= this zoom → full name
const LABEL_Z_CODE     = 6;    // >= this zoom & < LABEL_Z_FULL → 2-letter code
const LINE_Z_VOLTAGE   = 7;    // voltage badge appears
const LINE_Z_OPERATOR  = 9;    // operator suffix appended
const MAX_LABELS       = 600;  // hard cap regardless of zoom — keeps the
                               // WebGL buffers small even on a wide view

/* ─────────── Colour / typography ─────────── */
/* NOTE: these are PRESENTATION defaults. BOT-GC owns the semantic palette,
   so I only fall back to these when no `colour` field is supplied on the
   feature. */
const INK          = [26, 26, 26];        // --ink
const INK_HALO     = [255, 255, 255, 230];
const INK_DIM      = [74, 74, 74];
const BADGE_INK    = [26, 26, 26];
const BADGE_HALO   = [255, 255, 255, 245];

const FONT_FAMILY = "'DM Sans', 'Inter', system-ui, sans-serif";
const FONT_MONO   = "'JetBrains Mono', 'DM Mono', ui-monospace, monospace";

/* ─────────── Utilities ─────────── */

/** Build a 2-letter code from a substation name (first letters of first two
 *  tokens, falling back to first two alphanumerics of the single token). */
export function shortCode(name) {
  if (!name) return "";
  const clean = String(name).replace(/[^A-Za-z0-9 ]+/g, " ").trim();
  if (!clean) return "";
  const tokens = clean.split(/\s+/).filter(Boolean);
  if (tokens.length >= 2) {
    return (tokens[0][0] + tokens[1][0]).toUpperCase();
  }
  return tokens[0].slice(0, 2).toUpperCase();
}

/** Approximate CSS-px per geographic degree of longitude at the given zoom.
 *  Used for lat/lon based nearest-neighbour filtering without a real
 *  Mercator projection (Web Mercator base tile ≈ 512px, plus cos(lat)). */
function metresPerPixel(zoom, lat) {
  const latRad = (lat * Math.PI) / 180;
  return (40075016.686 * Math.cos(latRad)) / (512 * Math.pow(2, zoom));
}

/** Great-circle-ish chord distance between two (lat, lon) points in metres.
 *  Small-angle formula — fine for < 50 km, which is all we care about
 *  for label collision. */
function distMetres(a, b) {
  const R = 6371000;
  const latRad = (((a[1] + b[1]) / 2) * Math.PI) / 180;
  const dx = ((a[0] - b[0]) * Math.PI) / 180 * R * Math.cos(latRad);
  const dy = ((a[1] - b[1]) * Math.PI) / 180 * R;
  return Math.hypot(dx, dy);
}

/** Nearest-neighbour collision filter.
 *  Keep higher-priority points; drop any lower-priority point within
 *  `collisionPx * metresPerPixel` of an already-kept point. */
function thinByCollision(points, zoom, collisionPx) {
  if (!points?.length) return [];
  const sorted = [...points].sort((a, b) => (b._priority || 0) - (a._priority || 0));
  const kept = [];
  for (const p of sorted) {
    const mpp = metresPerPixel(zoom, p.lat ?? 54);
    const minDistM = collisionPx * mpp;
    let collides = false;
    for (const k of kept) {
      const d = distMetres([p.lon, p.lat], [k.lon, k.lat]);
      if (d < minDistM) { collides = true; break; }
    }
    if (!collides) kept.push(p);
    if (kept.length >= MAX_LABELS) break;
  }
  return kept;
}

/* ─────────── Substation label layer ─────────── */

/** Returns a single TextLayer (or null) for substation names.
 *
 *  Expected `substations` shape (a superset of what the 14k index returns):
 *    [{ id, name, lat, lon, voltage_kv, headroom_mw, dno, ... }]
 *
 *  Hidden below LABEL_Z_CODE. 2-letter code between LABEL_Z_CODE and
 *  LABEL_Z_FULL. Full name at LABEL_Z_FULL and above.
 */
export function buildSubstationLabelLayer({ substations, zoom, visible = true } = {}) {
  if (!visible) return null;
  if (!Array.isArray(substations) || substations.length === 0) return null;
  if (zoom == null || zoom < LABEL_Z_CODE) return null;

  const useFullName = zoom >= LABEL_Z_FULL;
  const fontSize    = useFullName ? 12 : 10;
  // Tighter collision when zoomed in (labels physically further apart).
  const collisionPx = useFullName ? COLLISION_PX : Math.round(COLLISION_PX * 0.7);

  // Attach priority and the actual text to render.
  const candidates = substations
    .filter(s => s && s.lat != null && s.lon != null)
    .map(s => {
      const name = s.name && s.name.trim() ? s.name.trim()
                 : (s.external_id || "");
      if (!name) return null;
      const text = useFullName ? name : shortCode(name);
      if (!text) return null;
      return {
        ...s,
        _text: text,
        _priority: (s.voltage_kv || 0) * 100 + (s.headroom_mw || 0),
      };
    })
    .filter(Boolean);

  const kept = thinByCollision(candidates, zoom, collisionPx);
  if (kept.length === 0) return null;

  return new TextLayer({
    id: "grid-graph-substation-labels",
    data: kept,
    pickable: false,
    getPosition: d => [d.lon, d.lat],
    getText: d => d._text,
    // Anchor below the dot so labels don't occlude the marker.
    getAlignmentBaseline: "top",
    getTextAnchor: "middle",
    getPixelOffset: [0, 8],
    getSize: fontSize,
    sizeUnits: "pixels",
    getColor: INK,
    fontFamily: FONT_FAMILY,
    fontWeight: useFullName ? 600 : 700,
    // Halo = background readability without a box behind the text.
    background: false,
    outlineWidth: 2,
    outlineColor: INK_HALO,
    fontSettings: { sdf: true, radius: 8 },
    characterSet: "auto",
    updateTriggers: {
      getText:   [useFullName],
      getSize:   [fontSize],
    },
  });
}

/* ─────────── Line label layer ─────────── */

/** Returns a single TextLayer (or null) for line voltage / operator badges.
 *
 *  Expected `lines` shape:
 *    [{ id, path: [[lon,lat], [lon,lat], ...], voltage_kv, operator,
 *       from_substation, to_substation, length_km }]
 *    OR the legacy shape:
 *    [{ id, from_lat, from_lon, to_lat, to_lon, voltage_kv, operator }]
 */
export function buildLineLabelLayer({ lines, zoom, visible = true } = {}) {
  if (!visible) return null;
  if (!Array.isArray(lines) || lines.length === 0) return null;
  if (zoom == null || zoom < LINE_Z_VOLTAGE) return null;

  const showOperator = zoom >= LINE_Z_OPERATOR;

  const items = lines
    .map(l => {
      let mid = null;
      if (Array.isArray(l.path) && l.path.length >= 2) {
        const i = Math.floor(l.path.length / 2);
        mid = l.path[i];
      } else if (l.from_lat != null && l.to_lat != null
              && l.from_lon != null && l.to_lon != null) {
        mid = [(l.from_lon + l.to_lon) / 2, (l.from_lat + l.to_lat) / 2];
      }
      if (!mid || mid[0] == null || mid[1] == null) return null;

      const v = l.voltage_kv != null ? `${Math.round(l.voltage_kv)} kV` : "";
      const op = showOperator && l.operator ? ` · ${l.operator}` : "";
      const text = (v + op).trim();
      if (!text) return null;

      return {
        ...l,
        _text: text,
        _mid: mid,
        _priority: (l.voltage_kv || 0),
        lat: mid[1],
        lon: mid[0],
      };
    })
    .filter(Boolean);

  // Thin collision so overlapping circuits don't stack three badges.
  const kept = thinByCollision(items, zoom, 42);
  if (kept.length === 0) return null;

  return new TextLayer({
    id: "grid-graph-line-labels",
    data: kept,
    pickable: false,
    getPosition: d => d._mid,
    getText: d => d._text,
    getAlignmentBaseline: "center",
    getTextAnchor: "middle",
    getSize: 10,
    sizeUnits: "pixels",
    getColor: BADGE_INK,
    fontFamily: FONT_MONO,
    fontWeight: 700,
    background: true,
    backgroundPadding: [4, 2, 4, 2],
    getBackgroundColor: BADGE_HALO,
    getBorderColor: [180, 170, 145, 200],
    getBorderWidth: 0.5,
    fontSettings: { sdf: true, radius: 8 },
    characterSet: "auto",
    updateTriggers: {
      getText: [showOperator],
    },
  });
}

/* ─────────── Convenience combiner ─────────── */

/** Returns the two label layers, filtering nulls. Meant to be spread into
 *  whatever layer list BOT-GO assembles:
 *
 *     const layers = [...BOT_GO_layers, ...buildAllGridGraphLabels({...})];
 */
export function buildAllGridGraphLabels({ substations, lines, zoom, visible } = {}) {
  const layers = [];
  const sub = buildSubstationLabelLayer({ substations, zoom, visible });
  if (sub) layers.push(sub);
  const line = buildLineLabelLayer({ lines, zoom, visible });
  if (line) layers.push(line);
  return layers;
}

/* ─────────── Default export: null React component ───────────
 * This file is imported as a JSX module even though it exports builders
 * rather than a component. Giving it a no-op default export lets the
 * container `import GridGraphLabels from ...` without warnings if the
 * caller forgets to use the named builders. */
export default function GridGraphLabels() {
  return null;
}

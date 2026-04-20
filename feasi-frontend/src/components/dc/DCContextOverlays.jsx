/**
 * DCContextOverlays — site-context + designation overlays for the DC Twin.
 *
 * Returns a list of deck.gl Layer instances for:
 *   - Planning red-line (site boundary, gold outline)
 *   - SSSI / AONB / National Park / protected polygons (from buildable mask)
 *   - Flood zones 2+3 (from EA Flood endpoint or buildable-mask fallback)
 *   - Agricultural Land Classification grades 1/2/3a
 *
 * Also exports:
 *   - <DCContextOverlayPanel> — floating toggle card (top-right, below utility)
 *   - <DCConstraintBadge>     — blocker badge pill in top bar
 *
 * Data flow: whatever the /api/design/buildable-mask endpoint returns gets
 * tinted by its `class` property (matches MASK_COLORS in DesignCanvas.jsx).
 */
import { PolygonLayer, GeoJsonLayer } from "@deck.gl/layers";

const MASK_COLOURS = {
  restricted_flood:     [14, 165, 233, 100],   // cyan
  restricted_protected: [220, 38, 127, 140],   // magenta — SSSI/AONB
  restricted_land:      [251, 146, 60, 100],   // orange — green belt / woodland
  restricted_alc:       [234, 179, 8, 90],     // yellow — ALC
  restricted_slope:     [120, 113, 108, 120],  // stone
};

const MASK_EDGE = {
  restricted_flood:     [14, 165, 233, 255],
  restricted_protected: [185, 28, 80, 255],
  restricted_land:      [234, 88, 12, 255],
  restricted_alc:       [161, 98, 7, 255],
  restricted_slope:     [68, 64, 60, 255],
};

const RED_LINE_GOLD   = [245, 183, 49, 255];
const RED_LINE_FILL   = [245, 183, 49, 30];
const BLOCKER_RED     = [220, 38, 38, 255];

/** Build a rectangular red-line around the shell polygon with a buffer. */
function redLinePolygon(shellPolygon, bufferM = 40) {
  if (!shellPolygon || shellPolygon.length < 4) return null;
  // Derive centroid + bounds from the shell polygon ring.
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const [lon, lat] of shellPolygon) {
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
  }
  const midLat = (minLat + maxLat) / 2;
  const dLat = bufferM / 111_320;
  const dLon = bufferM / (111_320 * Math.cos((midLat * Math.PI) / 180));
  return [
    [minLon - dLon, minLat - dLat],
    [maxLon + dLon, minLat - dLat],
    [maxLon + dLon, maxLat + dLat],
    [minLon - dLon, maxLat + dLat],
    [minLon - dLon, minLat - dLat],
  ];
}

/** Build the context overlay layer list.
 *
 *  @param {Object}  args
 *  @param {Object}  args.ctx             - useDCContext() return value
 *  @param {Array}   args.shellPolygon    - [[lon,lat], …]
 *  @param {Object}  args.toggles         - { redline, designations, flood, alc }
 */
export function buildContextOverlayLayers({
  ctx,
  shellPolygon,
  toggles = {},
}) {
  const layers = [];

  /* ── 1. Planning red-line (site boundary) ────────────────────────── */
  if (toggles.redline !== false && shellPolygon) {
    const rl = redLinePolygon(shellPolygon, 40);
    if (rl) {
      layers.push(new PolygonLayer({
        id: "dc-context-redline",
        data: [{ polygon: rl }],
        getPolygon: (d) => d.polygon,
        getFillColor: RED_LINE_FILL,
        getLineColor: RED_LINE_GOLD,
        lineWidthMinPixels: 3,
        extruded: false,
        stroked: true,
        filled: true,
        getDashArray: [10, 6],
      }));
    }
  }

  /* ── 2. Designations from buildable-mask GeoJSON ─────────────────── */
  if (ctx?.buildableMask?.features?.length) {
    const features = ctx.buildableMask.features.filter((f) => {
      const cls = f?.properties?.class;
      if (cls === "restricted_protected") return toggles.designations !== false;
      if (cls === "restricted_flood") return toggles.flood !== false;
      if (cls === "restricted_alc") return toggles.alc !== false;
      if (cls === "restricted_land") return toggles.designations !== false;
      if (cls === "restricted_slope") return false; // slope is not a designation overlay
      return false;
    });

    if (features.length > 0) {
      layers.push(new GeoJsonLayer({
        id: "dc-context-designations",
        data: { type: "FeatureCollection", features },
        stroked: true,
        filled: true,
        extruded: false,
        getFillColor: (f) => MASK_COLOURS[f?.properties?.class] || [148, 163, 184, 80],
        getLineColor: (f) => MASK_EDGE[f?.properties?.class] || [100, 116, 139, 200],
        lineWidthMinPixels: 1.5,
        pickable: false,
      }));
    }
  }

  /* ── 3. EA Flood zones (if the dedicated ingest is live) ─────────── */
  if (toggles.flood !== false && ctx?.floodZones?.features?.length) {
    layers.push(new GeoJsonLayer({
      id: "dc-context-flood-zones-ea",
      data: ctx.floodZones,
      stroked: true,
      filled: true,
      getFillColor: [14, 165, 233, 60],
      getLineColor: [14, 165, 233, 220],
      lineWidthMinPixels: 1,
      pickable: false,
    }));
  }

  return layers;
}

/* ═══════════════════════════════════════════════════════════════════════
 * Blocker detection — does any designation intersect the red-line?
 * Cheap bbox overlap check (axis-aligned) is sufficient at this scale;
 * server-side PostGIS ST_Intersects already did the expensive join.
 * ═══════════════════════════════════════════════════════════════════════ */

function bboxOfRing(ring) {
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const pt of ring) {
    if (pt[0] < minLon) minLon = pt[0];
    if (pt[0] > maxLon) maxLon = pt[0];
    if (pt[1] < minLat) minLat = pt[1];
    if (pt[1] > maxLat) maxLat = pt[1];
  }
  return { minLon, maxLon, minLat, maxLat };
}

function bboxesOverlap(a, b) {
  return !(a.maxLon < b.minLon || a.minLon > b.maxLon
        || a.maxLat < b.minLat || a.minLat > b.maxLat);
}

function extractBbox(geometry) {
  if (!geometry) return null;
  const coords = geometry.coordinates;
  if (!coords) return null;
  const flat = [];
  const walk = (arr) => {
    if (typeof arr[0] === "number") {
      flat.push(arr);
      return;
    }
    for (const sub of arr) walk(sub);
  };
  walk(coords);
  if (!flat.length) return null;
  return bboxOfRing(flat);
}

/** Derive blocker + near-miss flags from the context. */
export function deriveBlockerFlags({ ctx, shellPolygon }) {
  const result = { blockers: [], nearMisses: [], overallRisk: null };
  if (!ctx) return result;

  // Overall risk from /api/environment/constraints
  result.overallRisk = ctx.environment?.overall_risk_level || null;

  if (!shellPolygon) return result;
  const shellBbox = bboxOfRing(shellPolygon);

  const features = ctx.buildableMask?.features || [];
  for (const f of features) {
    const cls = f?.properties?.class;
    const name = f?.properties?.name || cls;
    const source = f?.properties?.source || "";
    const bbox = extractBbox(f.geometry);
    if (!bbox) continue;

    // Direct overlap with shell → hard blocker.
    if (bboxesOverlap(shellBbox, bbox)) {
      if (cls === "restricted_protected") {
        result.blockers.push({
          cls, name,
          source,
          message: `BLOCKER: ${prettyName(source)} overlaps shell — statutory setback required`,
        });
      } else if (cls === "restricted_flood") {
        result.blockers.push({
          cls, name,
          source,
          message: `BLOCKER: ${prettyName(source)} overlaps shell — sequential test required`,
        });
      } else if (cls === "restricted_land") {
        result.nearMisses.push({
          cls, name, source,
          message: `CAUTION: ${prettyName(source)} overlaps shell — VSC needed`,
        });
      }
    } else {
      // Expand shell bbox by ~250 m buffer and check again for near-miss.
      const midLat = (shellBbox.minLat + shellBbox.maxLat) / 2;
      const dLat = 250 / 111_320;
      const dLon = 250 / (111_320 * Math.cos((midLat * Math.PI) / 180));
      const buffered = {
        minLon: shellBbox.minLon - dLon,
        maxLon: shellBbox.maxLon + dLon,
        minLat: shellBbox.minLat - dLat,
        maxLat: shellBbox.maxLat + dLat,
      };
      if (bboxesOverlap(buffered, bbox) && cls === "restricted_protected") {
        result.nearMisses.push({
          cls, name, source,
          message: `NEAR-MISS: ${prettyName(source)} within 250 m of shell — setback check`,
        });
      }
    }
  }

  // Flood zone hit from EA endpoint
  if (ctx.floodZones?.features?.length && shellPolygon) {
    for (const f of ctx.floodZones.features) {
      const bbox = extractBbox(f.geometry);
      if (bbox && bboxesOverlap(shellBbox, bbox)) {
        const zone = f?.properties?.zone_number || 3;
        result.blockers.push({
          cls: "restricted_flood",
          name: `Flood Zone ${zone}`,
          source: "ea_flood",
          message: `BLOCKER: EA Flood Zone ${zone} overlaps shell — sequential test required`,
        });
        break;
      }
    }
  }

  return result;
}

function prettyName(source) {
  if (!source) return "Designation";
  return source
    .replace(/^env_/, "")
    .replace(/^planning_/, "")
    .replace(/_/g, " ")
    .toUpperCase();
}

/* ═══════════════════════════════════════════════════════════════════════
 * UI components
 * ═══════════════════════════════════════════════════════════════════════ */

export function DCContextOverlayPanel({ toggles, onToggle, ctx, topOffset = 160 }) {
  const designationCount = (ctx?.buildableMask?.features || []).filter(
    (f) => f?.properties?.class === "restricted_protected"
      || f?.properties?.class === "restricted_land"
  ).length;
  const floodCount = (ctx?.buildableMask?.features || []).filter(
    (f) => f?.properties?.class === "restricted_flood"
  ).length + (ctx?.floodZones?.features?.length || 0);
  const alcCount = (ctx?.buildableMask?.features || []).filter(
    (f) => f?.properties?.class === "restricted_alc"
  ).length;

  const rows = [
    { key: "redline",      label: "Planning red-line",  count: null,           always: true },
    { key: "designations", label: "SSSI / AONB / land", count: designationCount },
    { key: "flood",        label: "Flood zones",        count: floodCount },
    { key: "alc",          label: "ALC 1 / 2 / 3a",     count: alcCount },
  ];

  return (
    <div style={{
      position: "absolute", top: topOffset, right: 12, width: 232,
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
        Context overlays
      </div>
      {rows.map((r) => (
        <label key={r.key} style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "4px 0", cursor: "pointer",
          opacity: (r.always || r.count > 0) ? 1 : 0.5,
        }}>
          <input
            type="checkbox"
            checked={!!toggles[r.key]}
            onChange={(e) => onToggle(r.key, e.target.checked)}
            disabled={!r.always && r.count === 0}
            style={{ accentColor: "#f5b731" }}
          />
          <span style={{ flex: 1 }}>{r.label}</span>
          {r.count != null && (
            <span style={{
              fontSize: 9, color: r.count > 0 ? "#fbbf24" : "#64748b",
              fontVariantNumeric: "tabular-nums",
            }}>
              {r.count}
            </span>
          )}
        </label>
      ))}
    </div>
  );
}

/** Top-bar blocker pill. Shows the most severe issue only; click to expand. */
export function DCConstraintBadge({ blockers = [], nearMisses = [], overallRisk = null }) {
  if (!blockers.length && !nearMisses.length && !overallRisk) return null;

  const hasBlocker = blockers.length > 0;
  const topItem = hasBlocker ? blockers[0] : nearMisses[0];
  const colour = hasBlocker ? BLOCKER_RED : [234, 179, 8, 255];
  const label = hasBlocker ? "BLOCKER" : "CAUTION";

  const allItems = [...blockers, ...nearMisses];

  return (
    <div style={{
      position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)",
      zIndex: 5, maxWidth: 640,
      background: `rgba(${colour[0]},${colour[1]},${colour[2]},0.95)`,
      color: "#ffffff", padding: "8px 14px", borderRadius: 6,
      fontFamily: '"DM Sans", sans-serif', fontSize: 11, fontWeight: 700,
      boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
      letterSpacing: 0.3,
    }} title={allItems.map((x) => x.message).join("\n")}>
      <span style={{
        fontSize: 9, background: "rgba(0,0,0,0.25)",
        padding: "2px 6px", borderRadius: 3, marginRight: 8,
      }}>
        {label}
      </span>
      {topItem?.message}
      {allItems.length > 1 && (
        <span style={{ marginLeft: 10, opacity: 0.8 }}>
          +{allItems.length - 1} more
        </span>
      )}
    </div>
  );
}

export default DCContextOverlayPanel;

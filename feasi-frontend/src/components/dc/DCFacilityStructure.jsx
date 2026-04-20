/**
 * DCFacilityStructure — turns a campus layout recipe (from dcLayoutPresets.js)
 * into a list of deck.gl PolygonLayer extrusions.
 *
 * This is NOT a React component — the parent (DCDesignTwin) already owns the
 * deck.gl MapboxOverlay. This module exposes `buildStructureLayers(...)` which
 * returns an array of PolygonLayer instances ready for overlay.setProps({ layers }).
 *
 * Each sub-structure is individually pickable; clicking sets the parent's
 * `selected` state to the structure's `key`. A yellow highlight outline is
 * applied when a structure is selected.
 *
 * Geometry pipeline:
 *   layout (local metres, shell-centred)
 *     → projectRect(lat, lon, dx, dy, width, depth)
 *     → [lon, lat] polygon ring
 *     → PolygonLayer
 */

import { PolygonLayer } from "@deck.gl/layers";
import { ROLE_COLOURS, ROLE_META } from "./dcLayoutPresets";

const M_PER_DEG_LAT = 111_320;
function mPerDegLon(lat) { return M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180); }

/** Project a rectangle centred at (dx, dy) metres offset from (lat, lon)
 *  into a GeoJSON-style [lon, lat] closed ring. */
function projectRect(lat, lon, dx, dy, width, depth) {
  const mLon = mPerDegLon(lat);
  const hx = width / 2;
  const hy = depth / 2;
  // corners in local metres
  const localCorners = [
    [dx - hx, dy - hy],
    [dx + hx, dy - hy],
    [dx + hx, dy + hy],
    [dx - hx, dy + hy],
  ];
  const ring = localCorners.map(([x, y]) => [
    lon + x / mLon,
    lat + y / M_PER_DEG_LAT,
  ]);
  ring.push(ring[0]);
  return ring;
}

/** Convert a 4-channel colour and a selected flag into fill + edge colours. */
function highlightColours(role, isSelected) {
  const base = ROLE_COLOURS[role] || [150, 150, 150, 220];
  if (isSelected) {
    return {
      fill: [Math.min(255, base[0] + 20), Math.min(255, base[1] + 20), Math.min(255, base[2] + 20), Math.min(255, (base[3] || 220) + 20)],
      edge: [255, 215, 0, 255],
      lineWidth: 3,
    };
  }
  // slightly darker edge than fill for legibility
  return {
    fill: base,
    edge: [Math.max(0, base[0] - 40), Math.max(0, base[1] - 40), Math.max(0, base[2] - 40), 255],
    lineWidth: 1.4,
  };
}

/** Build one PolygonLayer for a single structure item. */
function makeLayer({
  id, item, lat, lon, selected, onClick, onHover, extruded = true,
}) {
  const { fill, edge, lineWidth } = highlightColours(item.role, selected === item.key);
  const polygon = projectRect(lat, lon, item.cx, item.cy, item.width, item.depth);
  return new PolygonLayer({
    id,
    data: [{ polygon, item }],
    getPolygon: d => d.polygon,
    getElevation: () => item.height || 0.5,
    getFillColor: fill,
    getLineColor: edge,
    lineWidthMinPixels: selected === item.key ? 3 : lineWidth,
    extruded,
    pickable: true,
    stroked: true,
    filled: true,
    updateTriggers: { getFillColor: [selected], getLineColor: [selected] },
    onClick: ({ object }) => { if (object && onClick) onClick(item); },
    onHover: ({ object, x, y }) => {
      if (!onHover) return;
      if (!object) return onHover(null);
      onHover({
        x, y,
        title: item.label || ROLE_META[item.role]?.label || item.key,
        rows: [
          ["Purpose", ROLE_META[item.role]?.purpose || "—"],
          ["Size", `${item.width.toFixed(0)} × ${item.depth.toFixed(0)} m`],
          ["Height", `${(item.height || 0).toFixed(1)} m`],
          ["Area", `${Math.round(item.width * item.depth).toLocaleString()} m²`],
        ],
      });
    },
  });
}

/**
 * Build the full layer stack for a campus layout.
 *
 * @param {object} opts
 * @param {object} opts.layout   output of buildCampusLayout(...)
 * @param {number} opts.lat      shell centroid latitude (WGS84)
 * @param {number} opts.lon      shell centroid longitude (WGS84)
 * @param {string|null} opts.selected  currently-selected structure key
 * @param {function} opts.onSelect(item)  click handler
 * @param {function} opts.onHover(info|null)
 * @param {boolean} [opts.showFence=true]
 * @returns {PolygonLayer[]}
 */
export function buildStructureLayers({
  layout, lat, lon, selected, onSelect, onHover, showFence = true,
  onShellDragStart, onShellDrag, onShellDragEnd,
}) {
  if (!layout) return [];
  const layers = [];

  // Shell envelope — wire outline only (no fill) so halls read as the hero.
  // This is ALSO the drag-handle: drag it to reposition the whole campus.
  if (layout.shell) {
    const shellPoly = projectRect(lat, lon, layout.shell.cx, layout.shell.cy, layout.shell.width, layout.shell.depth);
    const isSel = selected === "shell";
    layers.push(new PolygonLayer({
      id: "dc-struct-shell-outline",
      data: [{ polygon: shellPoly, item: layout.shell }],
      getPolygon: d => d.polygon,
      getElevation: () => layout.shell.height,
      // Translucent charcoal so the halls inside stay visible but the
      // silhouette is still readable from a distance.
      getFillColor: isSel ? [80, 80, 90, 100] : [58, 58, 64, 60],
      getLineColor: isSel ? [255, 215, 0, 255] : [30, 30, 36, 255],
      lineWidthMinPixels: isSel ? 4 : 2,
      extruded: false,
      wireframe: true,
      stroked: true,
      filled: true,
      pickable: true,
      updateTriggers: { getFillColor: [selected], getLineColor: [selected] },
      onClick: ({ object }) => { if (object) onSelect(layout.shell); },
      onDragStart: onShellDragStart,
      onDrag:      onShellDrag,
      onDragEnd:   onShellDragEnd,
      onHover: ({ object, x, y }) => {
        if (!onHover) return;
        if (!object) return onHover(null);
        onHover({
          x, y,
          title: "Shell envelope · drag to move campus",
          rows: [
            ["Data halls", `${layout.meta.hallCount}`],
            ["Shell size", `${layout.shell.width.toFixed(0)} × ${layout.shell.depth.toFixed(0)} m`],
            ["Shell height", `${layout.meta.shellHeight.toFixed(1)} m`],
            ["IT white space", `${Math.round(layout.shell.itAreaM2).toLocaleString()} m²`],
          ],
        });
      },
    }));
  }

  // Data halls — pale gold extruded boxes.
  layout.halls.forEach((h, i) => {
    layers.push(makeLayer({
      id: `dc-struct-${h.key}`,
      item: h, lat, lon, selected, onClick: onSelect, onHover,
    }));
    void i;
  });

  // Central spine corridor.
  if (layout.spine) {
    layers.push(makeLayer({
      id: "dc-struct-spine",
      item: layout.spine, lat, lon, selected, onClick: onSelect, onHover,
    }));
  }

  // MV / LV building.
  if (layout.mvlv) {
    layers.push(makeLayer({
      id: "dc-struct-mvlv",
      item: layout.mvlv, lat, lon, selected, onClick: onSelect, onHover,
    }));
  }

  // Genset yard pad (flat green compound)
  if (layout.genset) {
    layers.push(makeLayer({
      id: "dc-struct-genset-yard",
      item: layout.genset, lat, lon, selected, onClick: onSelect, onHover,
      extruded: true,
    }));
  }
  // Individual gensets (small boxes on the pad)
  (layout.gensets || []).forEach((g) => {
    layers.push(makeLayer({
      id: `dc-struct-${g.key}`,
      item: g, lat, lon, selected, onClick: onSelect, onHover,
    }));
  });
  // Diesel bulk tanks
  (layout.dieselTanks || []).forEach((t) => {
    layers.push(makeLayer({
      id: `dc-struct-${t.key}`,
      item: t, lat, lon, selected, onClick: onSelect, onHover,
    }));
  });

  // Transformer yard pad
  if (layout.tx) {
    layers.push(makeLayer({
      id: "dc-struct-tx-yard",
      item: layout.tx, lat, lon, selected, onClick: onSelect, onHover,
      extruded: true,
    }));
  }
  // Individual transformers
  (layout.transformers || []).forEach((t) => {
    layers.push(makeLayer({
      id: `dc-struct-${t.key}`,
      item: t, lat, lon, selected, onClick: onSelect, onHover,
    }));
  });

  // Water / cooling plant
  if (layout.water) {
    layers.push(makeLayer({
      id: "dc-struct-water",
      item: layout.water, lat, lon, selected, onClick: onSelect, onHover,
    }));
  }

  // Office / NOC
  if (layout.office) {
    layers.push(makeLayer({
      id: "dc-struct-office",
      item: layout.office, lat, lon, selected, onClick: onSelect, onHover,
    }));
  }

  // Security gatehouse
  if (layout.security) {
    layers.push(makeLayer({
      id: "dc-struct-security",
      item: layout.security, lat, lon, selected, onClick: onSelect, onHover,
    }));
  }

  // Loading bay / HGV dock
  if (layout.loading) {
    layers.push(makeLayer({
      id: "dc-struct-loading",
      item: layout.loading, lat, lon, selected, onClick: onSelect, onHover,
    }));
  }

  // Perimeter fence — dashed wire outline around the whole campus.
  if (showFence && layout.fence) {
    const fencePoly = projectRect(
      lat, lon,
      layout.fence.cx, layout.fence.cy,
      layout.fence.width, layout.fence.depth,
    );
    layers.push(new PolygonLayer({
      id: "dc-struct-fence",
      data: [{ polygon: fencePoly }],
      getPolygon: d => d.polygon,
      getFillColor: [0, 0, 0, 0],
      getLineColor: ROLE_COLOURS.fence,
      lineWidthMinPixels: 2,
      getDashArray: [6, 4],
      extruded: false,
      stroked: true,
      filled: false,
    }));
  }

  return layers;
}

/** Compute the total buildable fit — returns { fitsMask: bool, unfit: [...] }.
 *  If `mask` (array of { cx, cy, width, depth } in local metres, or null) is
 *  null/undefined, this returns { fitsMask: true } (i.e. no mask to enforce).
 *  This is a placeholder for the BOT-DP buildable mask contract; once that
 *  lands, swap to a proper shapely-ish polygon intersection test. */
export function checkFitsBuildableMask(layout, mask) {
  if (!mask) return { fitsMask: true, unfit: [] };
  const items = [
    layout.shell, layout.genset, layout.tx, layout.water,
    layout.office, layout.security, layout.loading,
  ].filter(Boolean);
  const unfit = [];
  items.forEach((it) => {
    const minX = it.cx - it.width / 2;
    const maxX = it.cx + it.width / 2;
    const minY = it.cy - it.depth / 2;
    const maxY = it.cy + it.depth / 2;
    const m = mask;   // rectangle-style mask for now
    if (minX < m.minX || maxX > m.maxX || minY < m.minY || maxY > m.maxY) {
      unfit.push(it.key);
    }
  });
  return { fitsMask: unfit.length === 0, unfit };
}

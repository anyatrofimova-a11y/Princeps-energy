/**
 * DnoLayerStack — deck.gl layer factory for DNO licence-area overlays.
 *
 * This module exports a single function ``buildDnoLayerStack(params)`` which
 * returns an array of deck.gl PolygonLayers. It's designed to be splatted into
 * an existing layer list inside ``MapView.jsx`` or ``GridTwinCesium.jsx`` with
 * zero structural changes:
 *
 *     const layers = [
 *       ...otherLayers,
 *       ...buildDnoLayerStack({ features, activeDnos, onClick }),
 *     ];
 *
 * There is also a default React export that renders nothing — useful if a
 * caller wants to mount the hook once to hydrate data while the factory is
 * used elsewhere. Most callers will use the named export only.
 *
 * Data
 * ────
 * The factory takes the raw GeoJSON FeatureCollection from
 * ``GET /api/dno/licence-areas`` (see app/routers/dno.py) and splits it into
 * idle / active layers so the active DNO draws on top of everything else at
 * higher opacity.
 *
 * Styling
 * ───────
 *   Idle:      fill 6% alpha, stroke 1 px in palette accent.
 *   Active:    fill 18% alpha, stroke 2 px in palette accent.
 *
 * Non-DNO features (operator_class='IDNO' or 'TO') always draw in the idle
 * band so they never dominate the active DNO.
 */

import React, { useEffect, useState } from "react";
import { PolygonLayer } from "@deck.gl/layers";
import palette from "../../data/dno-palette.json";
import useDnoFilter, { DNO_SLUGS } from "../../hooks/useDnoFilter";

// ── Colour helpers ──────────────────────────────────────────────────────────
function hexToRgba(hex, alpha) {
  if (!hex) return [160, 160, 160, Math.round(alpha * 255)];
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return [r, g, b, Math.round(alpha * 255)];
}

// Map top-level slug → palette entry. Sub-regions (e.g. 'ukpn-lpn') fall back
// to their parent ('ukpn').
function paletteFor(dnoSlug) {
  if (!dnoSlug) return null;
  if (palette[dnoSlug]) return palette[dnoSlug];
  const parent = dnoSlug.split("-")[0];
  return palette[parent] || null;
}

function topLevelSlug(dnoSlug) {
  if (!dnoSlug) return null;
  const base = dnoSlug.split("-")[0];
  return DNO_SLUGS.includes(base) ? base : null;
}

// ── Feature splitting ───────────────────────────────────────────────────────
/**
 * Split a GeoJSON FeatureCollection into {idle, active} arrays given the
 * current ``activeDnos`` set.
 *
 * "Active" means top-level DNO slug membership — a sub-region like
 * ``ukpn-lpn`` is active whenever ``ukpn`` is in the set.
 */
function partitionFeatures(features, activeDnos) {
  const idle = [];
  const active = [];
  const noFilter = !activeDnos || activeDnos.size === 0;

  for (const f of features) {
    const props = f?.properties || {};
    const opClass = (props.operator_class || "DNO").toUpperCase();
    const tlSlug = topLevelSlug(props.dno_slug);

    const isActive = (
      opClass === "DNO"
      && !noFilter
      && tlSlug
      && activeDnos.has(tlSlug)
    );

    (isActive ? active : idle).push(f);
  }
  return { idle, active };
}

// ── Layer factory ───────────────────────────────────────────────────────────
/**
 * Build the deck.gl layers for the DNO overlay.
 *
 * @param {Object}   params
 * @param {Array}    params.features     GeoJSON features from /api/dno/licence-areas.
 * @param {Set}      params.activeDnos   Set of top-level DNO slugs that are active.
 * @param {Function} [params.onClick]    Called with ({dno_slug, display_name, ...}).
 * @param {boolean}  [params.showTOs]    Whether to include TO outlines (default true).
 * @param {boolean}  [params.showIdnos]  Whether to include IDNO polygons (default true).
 * @param {boolean}  [params.pickable]   Make layers pickable (default true).
 * @returns {Array}  deck.gl layer instances.
 */
export function buildDnoLayerStack({
  features,
  activeDnos,
  onClick,
  showTOs = true,
  showIdnos = true,
  pickable = true,
} = {}) {
  if (!features || !features.length) return [];

  // Optional class filters.
  const filtered = features.filter((f) => {
    const cls = (f?.properties?.operator_class || "DNO").toUpperCase();
    if (cls === "TO"   && !showTOs)   return false;
    if (cls === "IDNO" && !showIdnos) return false;
    return true;
  });

  const { idle, active } = partitionFeatures(filtered, activeDnos);

  const commonProps = {
    pickable: Boolean(pickable),
    autoHighlight: true,
    highlightColor: [245, 183, 49, 48],
    extruded: false,
    stroked: true,
    filled: true,
    lineJointRounded: true,
    lineWidthUnits: "pixels",
    lineWidthMinPixels: 1,
    parameters: { depthTest: false },
    onClick: (info) => {
      if (onClick && info?.object?.properties) onClick(info.object.properties);
    },
    getPolygon: (f) => {
      // deck.gl PolygonLayer accepts Feature objects via the `data` array but
      // needs `getPolygon` to return the raw coordinate ring(s).
      const g = f?.geometry;
      if (!g) return [];
      if (g.type === "Polygon")      return g.coordinates;
      if (g.type === "MultiPolygon") return g.coordinates;
      return [];
    },
  };

  const idleLayer = idle.length
    ? new PolygonLayer({
        id: "dno-licence-areas-idle",
        data: idle,
        ...commonProps,
        getFillColor: (f) => {
          const p = paletteFor(f?.properties?.dno_slug);
          return hexToRgba(p?.accent, 0.06);
        },
        getLineColor: (f) => {
          const cls = (f?.properties?.operator_class || "DNO").toUpperCase();
          const p = paletteFor(f?.properties?.dno_slug);
          // TOs draw dashed-feel via a dimmer alpha, since deck.gl
          // PolygonLayer doesn't support dashes natively.
          const alpha = cls === "TO" ? 0.35 : 0.6;
          return hexToRgba(p?.accent, alpha);
        },
        getLineWidth: 1,
      })
    : null;

  const activeLayer = active.length
    ? new PolygonLayer({
        id: "dno-licence-areas-active",
        data: active,
        ...commonProps,
        getFillColor: (f) => {
          const p = paletteFor(f?.properties?.dno_slug);
          return hexToRgba(p?.accent, 0.18);
        },
        getLineColor: (f) => {
          const p = paletteFor(f?.properties?.dno_slug);
          return hexToRgba(p?.accent, 0.95);
        },
        getLineWidth: 2,
      })
    : null;

  return [idleLayer, activeLayer].filter(Boolean);
}

// ── Optional hook — fetch once + rebuild on activeDnos changes ──────────────
/**
 * useDnoLayerStack — thin convenience hook. Fetches licence-area GeoJSON once
 * (cached via module-scope Promise) and returns the current layer stack.
 *
 * Most call sites (MapView, GridTwinCesium) already own their own fetcher —
 * prefer using ``buildDnoLayerStack`` directly with pre-fetched features.
 */
let _fetchPromise = null;
function _fetchOnce(signal) {
  if (_fetchPromise) return _fetchPromise;
  _fetchPromise = fetch("/api/dno/licence-areas", { credentials: "include", signal })
    .then((r) => (r.ok ? r.json() : { features: [] }))
    .then((fc) => fc?.features || [])
    .catch(() => []);
  return _fetchPromise;
}

export function useDnoLayerStack({ onClick, showTOs = true, showIdnos = true } = {}) {
  const { activeDnos } = useDnoFilter();
  const [features, setFeatures] = useState([]);

  useEffect(() => {
    const ctl = new AbortController();
    _fetchOnce(ctl.signal).then((fs) => {
      if (!ctl.signal.aborted) setFeatures(fs || []);
    });
    return () => ctl.abort();
  }, []);

  return buildDnoLayerStack({
    features,
    activeDnos,
    onClick,
    showTOs,
    showIdnos,
  });
}

// Default export: a no-op React component for callers who prefer to mount
// the fetcher with JSX. It returns null but does trigger the fetch.
export default function DnoLayerStack() {
  useDnoLayerStack();
  return null;
}

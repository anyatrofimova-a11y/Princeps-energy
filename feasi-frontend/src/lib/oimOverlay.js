/**
 * oimOverlay — single-call glue that wires the full OpenInfraMap power overlay
 * onto a Mapbox GL v3 map.
 *
 * Used by GridTwin.jsx, MapView.jsx, and ProjectWorkspace.jsx so all three
 * map surfaces show the same voltage-banded lines, plant icons, and
 * substation polygons.
 *
 * What it does:
 *   1. Adds 7 GeoJSON sources (one per OSM power table) — empty until refresh.
 *   2. Loads the 46 OIM SVG icons as map images (oimSprites).
 *   3. Builds and adds all adapted OIM layer specs (oimStyleAdapter).
 *   4. Wires a click handler that opens a Mapbox popup with the OIM popup HTML.
 *   5. Hooks `moveend` to refresh sources from /api/grid/osm/* when the bbox
 *      changes, throttled to once per ~600ms.
 *
 * Returns a detach() function that removes all sources, layers, and listeners.
 */
import mapboxgl from 'mapbox-gl';
import oimPowerLayers from '../style/oim/style_oim_power.ts';
import { adaptOimLayers, OIM_SOURCE_IDS } from './oimStyleAdapter';
import { loadOimSprites } from './oimSprites';
import { renderOimPopupHtml } from '../components/OIMFeaturePopup';

const ID_PREFIX = 'oim-';
const API_BASE = (typeof window !== 'undefined' && window.__PRINCEPS_API__) || '';

// Maps each Princeps GeoJSON source id → the FastAPI endpoint that returns
// it as a FeatureCollection for a bbox query.
const SOURCE_ENDPOINTS = {
  'princeps-osm-power-lines': '/api/grid/osm/lines',
  'princeps-osm-power-substations': '/api/grid/osm/substations',
  'princeps-osm-power-substation-polys': '/api/grid/osm/substation-polys',
  'princeps-osm-power-plants': '/api/grid/osm/plants',
  'princeps-osm-power-generators': '/api/grid/osm/generators',
  'princeps-osm-power-towers': '/api/grid/osm/towers',
  'princeps-osm-power-switchgear': '/api/grid/osm/switchgear',
};

function emptyFC() {
  return { type: 'FeatureCollection', features: [] };
}

async function fetchSource(map, srcId, endpoint, abortSignal) {
  if (!map.getSource(srcId)) return;
  const b = map.getBounds();
  const url = `${API_BASE}${endpoint}?west=${b.getWest().toFixed(4)}&south=${b.getSouth().toFixed(4)}&east=${b.getEast().toFixed(4)}&north=${b.getNorth().toFixed(4)}`;
  try {
    const r = await fetch(url, { signal: abortSignal });
    if (!r.ok) return;
    const data = await r.json();
    const src = map.getSource(srcId);
    if (src && typeof src.setData === 'function') src.setData(data);
  } catch (e) {
    if (e?.name !== 'AbortError') {
      // eslint-disable-next-line no-console
      console.debug(`[oimOverlay] ${srcId} refresh failed:`, e?.message || e);
    }
  }
}

async function refreshAllSources(map, abortSignal) {
  // Only fetch sources that are actually wired (some Princeps backends may
  // not yet expose every endpoint — fall back to empty FC silently).
  await Promise.all(
    Object.entries(SOURCE_ENDPOINTS).map(([srcId, ep]) => fetchSource(map, srcId, ep, abortSignal))
  );
}

/**
 * Attach the OIM overlay to a Mapbox GL v3 map.
 *
 * @param {mapboxgl.Map} map
 * @param {object} [opts]
 * @param {string} [opts.idPrefix='oim-']
 * @param {string[]} [opts.font]   - overrides text-font (must match basemap glyphs)
 * @param {boolean} [opts.popup=true] - install click handler that opens a popup
 * @returns {{detach: () => void, refresh: () => Promise<void>, layerIds: string[]}}
 */
export function attachOimOverlay(map, opts = {}) {
  if (!map) return { detach: () => {}, refresh: async () => {}, layerIds: [] };

  const idPrefix = opts.idPrefix ?? ID_PREFIX;
  let detached = false;
  let abortController = null;
  const debounceMs = 600;
  let pendingTimer = null;

  // 1) Add empty GeoJSON sources.
  for (const srcId of OIM_SOURCE_IDS) {
    if (!map.getSource(srcId)) {
      map.addSource(srcId, { type: 'geojson', data: emptyFC() });
    }
  }

  // 2) Generate adapted layers (skip if already added — re-attach is a no-op).
  const rawLayers = oimPowerLayers();
  const adapted = adaptOimLayers(rawLayers, { idPrefix, font: opts.font });
  const layerIds = [];
  for (const layer of adapted) {
    if (map.getLayer(layer.id)) continue;
    try {
      map.addLayer(layer);
      layerIds.push(layer.id);
    } catch (e) {
      // Some Mapbox basemaps don't have the glyphs the layer wants — log and skip.
      // eslint-disable-next-line no-console
      console.warn(`[oimOverlay] addLayer ${layer.id} failed:`, e?.message || e);
    }
  }

  // 3) Load sprites (non-blocking — Mapbox renders blank for missing images).
  loadOimSprites(map).catch(() => {});

  // 4) Throttled refresh on move.
  const scheduleRefresh = () => {
    if (detached) return;
    if (pendingTimer) clearTimeout(pendingTimer);
    pendingTimer = setTimeout(() => {
      pendingTimer = null;
      if (abortController) abortController.abort();
      abortController = new AbortController();
      refreshAllSources(map, abortController.signal);
    }, debounceMs);
  };
  map.on('moveend', scheduleRefresh);
  // First fetch on the bbox we already have.
  refreshAllSources(map, (abortController = new AbortController()).signal);

  // 5) Popup wiring.
  let popup = null;
  const onClick = (e) => {
    const feats = map.queryRenderedFeatures(e.point, {
      layers: layerIds.length ? layerIds : undefined,
    });
    if (!feats || feats.length === 0) return;
    // Prefer the topmost OIM-prefixed feature.
    const f = feats.find((x) => x.layer?.id?.startsWith(idPrefix)) || feats[0];
    if (!f) return;
    const html = renderOimPopupHtml(f);
    if (!html) return;
    if (popup) popup.remove();
    popup = new mapboxgl.Popup({ closeButton: true, maxWidth: '320px' })
      .setLngLat(e.lngLat)
      .setHTML(html)
      .addTo(map);
  };
  if (opts.popup !== false) {
    map.on('click', onClick);
  }

  return {
    layerIds,
    refresh: () => refreshAllSources(map, (abortController = new AbortController()).signal),
    detach: () => {
      if (detached) return;
      detached = true;
      if (pendingTimer) clearTimeout(pendingTimer);
      if (abortController) abortController.abort();
      try { map.off('moveend', scheduleRefresh); } catch {}
      try { map.off('click', onClick); } catch {}
      if (popup) { try { popup.remove(); } catch {} popup = null; }
      for (const id of layerIds) {
        if (map.getLayer(id)) { try { map.removeLayer(id); } catch {} }
      }
      for (const srcId of OIM_SOURCE_IDS) {
        if (map.getSource(srcId)) { try { map.removeSource(srcId); } catch {} }
      }
    },
  };
}

/**
 * Inject the mandatory CC-BY 4.0 attribution into a Mapbox AttributionControl.
 * Mapbox merges attribution strings from sources automatically; for our
 * GeoJSON sources we tag them with the correct credit so it shows in the
 * footer alongside the basemap's own attribution.
 */
export const OIM_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a> · ' +
  'Open Infrastructure Map style (<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC-BY 4.0</a>)';

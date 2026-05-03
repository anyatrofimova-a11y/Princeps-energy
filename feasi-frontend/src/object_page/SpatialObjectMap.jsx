import {useEffect, useRef, useState, useCallback} from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || '';

/**
 * SpatialObjectMap — Mapbox pane for the typed-object list view.
 * Fetches `/api/object-geo/{type}?bbox=...` on every map move, renders
 * markers sized + coloured per object kind, and bubbles the clicked
 * feature_id back up to the parent so the table row can highlight.
 */

const COLOURS = {
  REPDProject: '#8B5CF6',  // violet
  Substation:  '#3B82F6',  // blue
  NSIPProject: '#F5B731',  // gold
};

const SRC = 'spatial-objects-src';
const LYR_CIRCLE = 'spatial-objects-circle';
const LYR_LABEL  = 'spatial-objects-label';

export default function SpatialObjectMap({
  objectType,
  filters = {},
  selectedId,
  onSelectFeature,
  onFeaturesLoaded,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const installedRef = useRef(false);
  const [ready, setReady] = useState(false);

  const fillFor = COLOURS[objectType] || '#7C3AED';

  // Init map
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    if (!mapboxgl.accessToken) return;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: 'mapbox://styles/mapbox/light-v11',
      center: [-1.5, 53.0],
      zoom: 5.4,
    });
    mapRef.current = map;
    map.on('load', () => setReady(true));
    return () => { try { map.remove(); } catch {} mapRef.current = null; };
  }, []);

  // Fetch + render
  const fetchAndRender = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const b = map.getBounds();
    const bbox = `${b.getWest().toFixed(4)},${b.getSouth().toFixed(4)},${b.getEast().toFixed(4)},${b.getNorth().toFixed(4)}`;
    const qs = new URLSearchParams({bbox, limit: '1500', ...filters}).toString();
    try {
      const res = await fetch(`/api/object-geo/${encodeURIComponent(objectType)}?${qs}`);
      if (!res.ok) return;
      const fc = await res.json();

      if (!map.getSource(SRC)) {
        map.addSource(SRC, {type: 'geojson', data: fc, generateId: false});
        map.addLayer({
          id: LYR_CIRCLE,
          type: 'circle',
          source: SRC,
          paint: {
            'circle-radius': [
              'interpolate', ['linear'], ['coalesce', ['get', 'capacity_mw'], 5],
              0, 4, 50, 6, 200, 9, 500, 13, 1000, 18,
            ],
            'circle-color': fillFor,
            'circle-stroke-color': '#0F1318',
            'circle-stroke-width': 1,
            'circle-opacity': 0.85,
          },
        });
        map.addLayer({
          id: LYR_LABEL,
          type: 'symbol',
          source: SRC,
          minzoom: 10,
          layout: {
            'text-field': ['get', 'label'],
            'text-size': 11,
            'text-offset': [0, 1.0],
            'text-anchor': 'top',
            'text-optional': true,
          },
          paint: {
            'text-color': '#0F1318',
            'text-halo-color': '#FFFFFF',
            'text-halo-width': 1.4,
          },
        });
        map.on('click', LYR_CIRCLE, (e) => {
          const f = e.features?.[0];
          if (f?.properties?.feature_id) {
            onSelectFeature?.(f.properties.feature_id);
          }
        });
        map.on('mouseenter', LYR_CIRCLE, () => map.getCanvas().style.cursor = 'pointer');
        map.on('mouseleave', LYR_CIRCLE, () => map.getCanvas().style.cursor = '');
        installedRef.current = true;
      } else {
        map.getSource(SRC).setData(fc);
      }
      onFeaturesLoaded?.(fc.features || []);
    } catch (err) {
      console.warn('SpatialObjectMap fetch failed', err);
    }
  }, [objectType, JSON.stringify(filters)]);

  // Refetch on ready + move + filter change
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    let timer = null;
    const debounced = () => { clearTimeout(timer); timer = setTimeout(fetchAndRender, 300); };
    map.on('moveend', debounced);
    fetchAndRender();
    return () => { map.off('moveend', debounced); clearTimeout(timer); };
  }, [ready, fetchAndRender]);

  // Highlight selected feature
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !installedRef.current || !selectedId) return;
    const feature_id = `${objectType}:${selectedId}`;
    map.setPaintProperty(LYR_CIRCLE, 'circle-stroke-color', [
      'case',
      ['==', ['get', 'feature_id'], feature_id], '#F5B731',
      '#0F1318',
    ]);
    map.setPaintProperty(LYR_CIRCLE, 'circle-stroke-width', [
      'case',
      ['==', ['get', 'feature_id'], feature_id], 3,
      1,
    ]);
  }, [selectedId, objectType]);

  if (!mapboxgl.accessToken) {
    return (
      <div className="opx-map-empty">
        Mapbox token missing — add VITE_MAPBOX_TOKEN to feasi-frontend/.env
      </div>
    );
  }
  return <div ref={containerRef} className="opx-map" />;
}

export function isSpatialType(t) {
  return ['REPDProject', 'Substation', 'NSIPProject'].includes(t);
}

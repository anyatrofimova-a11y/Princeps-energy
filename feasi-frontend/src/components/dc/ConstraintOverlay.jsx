import {useEffect, useRef} from 'react';

/**
 * D1 — Constraint overlay for the DC Design canvas.
 *
 * Fetches OSM building footprints within `radiusM` of the project's
 * picked location, paints them as red "forbidden zone" fills + dashed
 * outlines, and adds the red-line as a gold polygon. The auto-layout
 * solver and the drag-and-drop UX both consult this data via the
 * `onZonesReady(features)` callback so they can deconflict against
 * real ground truth.
 *
 * Mounts INTO an existing Mapbox map instance — no new map. Idempotent:
 * adds the source/layer once, removes them on unmount.
 *
 * Source: GET /api/dc-design/forbidden-zones?lat&lng&radius_m
 */
export default function ConstraintOverlay({
  map,
  lat,
  lng,
  radiusM = 400,
  redLineGeoJson,
  onZonesReady,
}) {
  const cleanedRef = useRef(false);

  useEffect(() => {
    if (!map || lat == null || lng == null) return;
    cleanedRef.current = false;

    let cancelled = false;
    let teardown = () => {};

    const ensureLayers = (data) => {
      if (cancelled || !map.isStyleLoaded()) return;
      try {
        const FORBIDDEN_SRC = 'dc-design-forbidden-src';
        const FORBIDDEN_FILL = 'dc-design-forbidden-fill';
        const FORBIDDEN_LINE = 'dc-design-forbidden-line';

        if (map.getLayer(FORBIDDEN_FILL)) map.removeLayer(FORBIDDEN_FILL);
        if (map.getLayer(FORBIDDEN_LINE)) map.removeLayer(FORBIDDEN_LINE);
        if (map.getSource(FORBIDDEN_SRC)) map.removeSource(FORBIDDEN_SRC);

        map.addSource(FORBIDDEN_SRC, {type: 'geojson', data});
        map.addLayer({
          id: FORBIDDEN_FILL,
          type: 'fill-extrusion',
          source: FORBIDDEN_SRC,
          paint: {
            'fill-extrusion-color': '#DC2626',
            'fill-extrusion-opacity': 0.32,
            'fill-extrusion-height': [
              'coalesce',
              ['*', ['get', 'levels'], 3.5],
              ['get', 'height'],
              4,
            ],
            'fill-extrusion-base': 0,
          },
        });
        map.addLayer({
          id: FORBIDDEN_LINE,
          type: 'line',
          source: FORBIDDEN_SRC,
          paint: {
            'line-color': '#B91C1C',
            'line-width': 1.2,
            'line-dasharray': [2, 2],
            'line-opacity': 0.8,
          },
        });

        // Project red-line (preferred zone outline)
        const REDLINE_SRC = 'dc-design-redline-src';
        const REDLINE_LINE = 'dc-design-redline-line';
        if (redLineGeoJson) {
          if (map.getLayer(REDLINE_LINE)) map.removeLayer(REDLINE_LINE);
          if (map.getSource(REDLINE_SRC)) map.removeSource(REDLINE_SRC);
          map.addSource(REDLINE_SRC, {type: 'geojson', data: redLineGeoJson});
          map.addLayer({
            id: REDLINE_LINE,
            type: 'line',
            source: REDLINE_SRC,
            paint: {
              'line-color': '#F5B731',
              'line-width': 2,
              'line-dasharray': [4, 2],
            },
          });
        }

        teardown = () => {
          for (const id of [FORBIDDEN_FILL, FORBIDDEN_LINE, REDLINE_LINE]) {
            if (map.getLayer(id)) map.removeLayer(id);
          }
          for (const id of [FORBIDDEN_SRC, REDLINE_SRC]) {
            if (map.getSource(id)) map.removeSource(id);
          }
        };
      } catch (err) {
        console.warn('ConstraintOverlay: layer add failed', err);
      }
    };

    fetch(`/api/dc-design/forbidden-zones?lat=${lat}&lng=${lng}&radius_m=${radiusM}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then((fc) => {
        if (cancelled) return;
        const ready = () => {
          ensureLayers(fc);
          onZonesReady?.(fc.features ?? []);
        };
        if (map.isStyleLoaded()) ready();
        else map.once('style.load', ready);
      })
      .catch((err) => {
        console.warn('ConstraintOverlay: fetch failed', err);
      });

    return () => {
      cancelled = true;
      try { teardown(); } catch { /* style may have unloaded */ }
    };
  }, [map, lat, lng, radiusM, redLineGeoJson, onZonesReady]);

  return null;
}

import {useEffect, useRef, useState, useCallback} from 'react';

/**
 * D4 — MeanderX-grade UK queue overlay for the v2 cockpit map and the
 * DC Design Twin map. Mounts INTO an existing Mapbox map instance.
 *
 *   <GridQueueLayer
 *      map={mapInstance}
 *      voltageMin={132}
 *      sources={['tec','ecr','repd']}
 *      onProjectClick={(featureId) => setOpenCard(featureId)}
 *   />
 *
 * Renders three layers, refetched whenever the visible bbox changes:
 *   - dc-overlay-lines       (LineString, voltage-banded color)
 *   - dc-overlay-queue-circle (Point, source-keyed color, capacity-sized)
 *   - dc-overlay-queue-label  (Symbol — name on hover/zoom)
 *
 * Click on a queue feature → onProjectClick(feature_id). The parent
 * mounts <ProjectInfoCard featureId={...}/>.
 *
 * Idempotent: adds sources/layers once on mount (or on map style change),
 * removes everything on unmount.
 */

const VOLTAGE_COLORS = {
  '400kV+': '#7C3AED',
  '275kV':  '#A855F7',
  '132kV':  '#0EA5E9',
  '66kV':   '#22D3EE',
  '33kV':   '#10B981',
  '≤22kV':  '#84CC16',
  'unknown': '#94A3B8',
};

const SOURCE_COLORS = {
  tec:  '#F5B731', // gold — Princeps brand
  ecr:  '#3B82F6', // blue
  repd: '#8B5CF6', // violet
};

const SRC_QUEUE = 'px-overlay-queue-src';
const SRC_LINES = 'px-overlay-lines-src';
const LYR_LINES = 'px-overlay-lines';
const LYR_QUEUE_CIRCLE = 'px-overlay-queue-circle';
const LYR_QUEUE_LABEL = 'px-overlay-queue-label';

export default function GridQueueLayer({
  map,
  voltageMin = 0,
  sources = ['tec', 'ecr', 'repd'],
  showLines = true,
  onProjectClick,
  onFeaturesLoaded,
}) {
  const installedRef = useRef(false);
  const debounceRef = useRef(null);
  const [loading, setLoading] = useState(false);

  const fetchAndUpdate = useCallback(async () => {
    if (!map || !map.isStyleLoaded()) return;
    const b = map.getBounds();
    const bbox = `${b.getWest().toFixed(4)},${b.getSouth().toFixed(4)},${b.getEast().toFixed(4)},${b.getNorth().toFixed(4)}`;
    const sourceParam = sources.length === 3 ? 'all' : sources[0] ?? 'all';

    setLoading(true);
    try {
      const queueUrl = `/api/grid-overlay/queue?bbox=${bbox}` +
        (voltageMin > 0 ? `&voltage_min=${voltageMin}` : '') +
        `&source=${sourceParam}&limit=1000`;
      const linesUrl = `/api/grid-overlay/lines?bbox=${bbox}` +
        (voltageMin > 0 ? `&voltage_min=${voltageMin}` : '') +
        `&limit=2000`;

      const promises = [fetch(queueUrl).then(r => r.json())];
      if (showLines) promises.push(fetch(linesUrl).then(r => r.json()));
      const [queueFc, linesFc] = await Promise.all(promises);

      // Filter queue by sources whitelist (when not 'all'/3-of-3 server-side)
      let qFeatures = queueFc.features || [];
      if (sources.length < 3) {
        qFeatures = qFeatures.filter(f => sources.includes(f.properties.source));
      }

      const queueSrc = map.getSource(SRC_QUEUE);
      if (queueSrc) {
        queueSrc.setData({type: 'FeatureCollection', features: qFeatures});
      }
      if (showLines && linesFc) {
        const linesSrc = map.getSource(SRC_LINES);
        if (linesSrc) linesSrc.setData(linesFc);
      }
      onFeaturesLoaded?.({queue: qFeatures.length, lines: linesFc?.features?.length ?? 0});
    } catch (err) {
      console.warn('GridQueueLayer fetch failed', err);
    } finally {
      setLoading(false);
    }
  }, [map, voltageMin, sources.join('|'), showLines]);

  // Install layers once
  useEffect(() => {
    if (!map) return;

    const install = () => {
      if (installedRef.current) return;

      // Empty source containers — fetchAndUpdate will populate them.
      if (!map.getSource(SRC_LINES)) {
        map.addSource(SRC_LINES, {type: 'geojson', data: {type: 'FeatureCollection', features: []}});
      }
      if (!map.getSource(SRC_QUEUE)) {
        map.addSource(SRC_QUEUE, {type: 'geojson', data: {type: 'FeatureCollection', features: []}});
      }

      if (!map.getLayer(LYR_LINES)) {
        map.addLayer({
          id: LYR_LINES,
          type: 'line',
          source: SRC_LINES,
          layout: {'line-cap': 'round', 'line-join': 'round'},
          paint: {
            'line-color': [
              'match', ['get', 'voltage_band'],
              '400kV+',  VOLTAGE_COLORS['400kV+'],
              '275kV',   VOLTAGE_COLORS['275kV'],
              '132kV',   VOLTAGE_COLORS['132kV'],
              '66kV',    VOLTAGE_COLORS['66kV'],
              '33kV',    VOLTAGE_COLORS['33kV'],
              '≤22kV',   VOLTAGE_COLORS['≤22kV'],
              VOLTAGE_COLORS.unknown,
            ],
            'line-width': [
              'match', ['get', 'voltage_band'],
              '400kV+',  3.4,
              '275kV',   2.8,
              '132kV',   2.2,
              '66kV',    1.6,
              '33kV',    1.2,
              0.8,
            ],
            'line-opacity': 0.85,
          },
        });
      }

      if (!map.getLayer(LYR_QUEUE_CIRCLE)) {
        map.addLayer({
          id: LYR_QUEUE_CIRCLE,
          type: 'circle',
          source: SRC_QUEUE,
          paint: {
            'circle-color': [
              'match', ['get', 'source'],
              'tec',  SOURCE_COLORS.tec,
              'ecr',  SOURCE_COLORS.ecr,
              'repd', SOURCE_COLORS.repd,
              '#94A3B8',
            ],
            'circle-radius': [
              'interpolate', ['linear'],
              ['coalesce', ['get', 'capacity_mw'], 5],
              0, 4, 50, 6, 200, 9, 500, 13, 1000, 18,
            ],
            'circle-stroke-color': '#0F1318',
            'circle-stroke-width': 1,
            'circle-opacity': 0.85,
          },
        });
      }

      if (!map.getLayer(LYR_QUEUE_LABEL)) {
        map.addLayer({
          id: LYR_QUEUE_LABEL,
          type: 'symbol',
          source: SRC_QUEUE,
          minzoom: 11,
          layout: {
            'text-field': ['concat',
              ['coalesce', ['get', 'name'], ''],
              ['case', ['has', 'capacity_mw'],
                ['concat', '  ', ['number-format', ['get', 'capacity_mw'], {'max-fraction-digits': 0}], ' MW'],
                '',
              ],
            ],
            'text-size': 11,
            'text-offset': [0, 1.1],
            'text-anchor': 'top',
            'text-allow-overlap': false,
            'text-optional': true,
            'text-font': ['DIN Pro Medium', 'Arial Unicode MS Regular'],
          },
          paint: {
            'text-color': '#0F1318',
            'text-halo-color': '#FFFFFF',
            'text-halo-width': 1.4,
          },
        });
      }

      // Click handler — bubble up feature_id.
      const onClick = (e) => {
        const f = e.features?.[0];
        if (f?.properties?.feature_id) onProjectClick?.(f.properties.feature_id);
      };
      const onEnter = () => { map.getCanvas().style.cursor = 'pointer'; };
      const onLeave = () => { map.getCanvas().style.cursor = ''; };
      map.on('click', LYR_QUEUE_CIRCLE, onClick);
      map.on('mouseenter', LYR_QUEUE_CIRCLE, onEnter);
      map.on('mouseleave', LYR_QUEUE_CIRCLE, onLeave);

      installedRef.current = true;
      installedRef._teardownClicks = () => {
        map.off('click', LYR_QUEUE_CIRCLE, onClick);
        map.off('mouseenter', LYR_QUEUE_CIRCLE, onEnter);
        map.off('mouseleave', LYR_QUEUE_CIRCLE, onLeave);
      };

      // Initial fetch
      fetchAndUpdate();
    };

    if (map.isStyleLoaded()) install();
    else map.once('style.load', install);

    return () => {
      installedRef._teardownClicks?.();
      for (const id of [LYR_QUEUE_LABEL, LYR_QUEUE_CIRCLE, LYR_LINES]) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      for (const id of [SRC_QUEUE, SRC_LINES]) {
        if (map.getSource(id)) map.removeSource(id);
      }
      installedRef.current = false;
    };
  }, [map]);

  // Refetch on map move + filter change
  useEffect(() => {
    if (!map) return;
    const debounced = () => {
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(fetchAndUpdate, 380);
    };
    map.on('moveend', debounced);
    debounced();  // also fire when filter inputs change
    return () => {
      map.off('moveend', debounced);
      clearTimeout(debounceRef.current);
    };
  }, [map, fetchAndUpdate]);

  return null;
}

export {VOLTAGE_COLORS, SOURCE_COLORS};

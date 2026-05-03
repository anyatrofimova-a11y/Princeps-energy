import {useEffect, useRef} from 'react';
import mapboxgl from 'mapbox-gl';

/**
 * D2 — Draggable Mapbox marker for a DC campus component (building shell,
 * genset yard, water plant, MV/LV, gatehouse, etc.).
 *
 * Wraps the legacy static-extrusion rendering with a draggable HTML marker
 * that the user can pick up and reposition. While dragging, a "ghost"
 * footprint outline tracks the cursor; on `dragend` the parent's
 * `onMove(newLngLat)` fires so it can persist + re-render the extrusion
 * layer at the new position.
 *
 * Collision feedback: if `forbiddenZones` is supplied, the marker turns
 * red while overlapping any feature in that GeoJSON FeatureCollection.
 */
export default function DraggableComponent({
  map,
  id,
  label,
  position,             // [lng, lat]
  size_m = [40, 30],    // [width, depth] in metres for collision footprint
  color = '#F5B731',
  forbiddenZones,
  onMove,
  onSelect,
  selected = false,
}) {
  const markerRef = useRef(null);
  const elRef = useRef(null);

  useEffect(() => {
    if (!map || !position) return;

    const el = document.createElement('div');
    elRef.current = el;
    el.className = 'px-dc-component-handle';
    el.innerHTML = `
      <div class="px-dc-handle-dot" style="background:${color};"></div>
      <div class="px-dc-handle-label">${label ?? id}</div>
    `;

    const marker = new mapboxgl.Marker({element: el, draggable: true, anchor: 'center'})
      .setLngLat(position)
      .addTo(map);
    markerRef.current = marker;

    el.addEventListener('click', () => onSelect?.(id));

    marker.on('dragstart', () => {
      el.classList.add('is-dragging');
    });
    marker.on('drag', () => {
      const ll = marker.getLngLat();
      const overlap = forbiddenZones && _isOverlap([ll.lng, ll.lat], forbiddenZones);
      el.classList.toggle('is-overlap', Boolean(overlap));
    });
    marker.on('dragend', () => {
      const ll = marker.getLngLat();
      el.classList.remove('is-dragging');
      onMove?.(id, [ll.lng, ll.lat]);
    });

    return () => {
      try { marker.remove(); } catch { /* map already torn down */ }
    };
  }, [map, id]);  // intentional — recreate on id change only, position updates via setLngLat below

  // Sync position prop → marker (so external updates / undo land in the UI).
  useEffect(() => {
    if (markerRef.current && position) {
      markerRef.current.setLngLat(position);
    }
  }, [position?.[0], position?.[1]]);

  // Selection styling.
  useEffect(() => {
    if (elRef.current) elRef.current.classList.toggle('is-selected', selected);
  }, [selected]);

  return null;
}


/** Cheap overlap test — checks if the lng/lat point falls inside any
 *  forbidden polygon. Uses a ray-cast for Polygon, recurses on MultiPolygon.
 */
function _isOverlap(point, fc) {
  if (!fc?.features) return false;
  for (const f of fc.features) {
    const g = f.geometry;
    if (!g) continue;
    if (g.type === 'Polygon') {
      if (_pointInRing(point, g.coordinates[0])) return true;
    } else if (g.type === 'MultiPolygon') {
      for (const poly of g.coordinates) {
        if (_pointInRing(point, poly[0])) return true;
      }
    }
  }
  return false;
}

function _pointInRing(p, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    const intersects = ((yi > p[1]) !== (yj > p[1])) &&
      (p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi + 1e-12) + xi);
    if (intersects) inside = !inside;
  }
  return inside;
}

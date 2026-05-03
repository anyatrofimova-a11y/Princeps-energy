import {useEffect, useRef} from 'react';
import {useSelection} from './useSelection.jsx';

/**
 * Pattern (b) — bidirectional 3D ↔ table linking.
 *
 * Watches the global selectedAssetRid and runs `flyTo(position)` on the
 * supplied imperative viewer ref whenever the selection changes. Pair with
 * a viewer that exposes `flyTo({lng, lat, zoom?, pitch?})` (Mapbox/Cesium)
 * or `lookAt(position)` (deck.gl/Three).
 *
 * Usage:
 *   const map = useRef(null);
 *   useFlyToOnSelection(map, async (rid) => {
 *     const r = await fetch(`/api/assets/${rid}`).then(r => r.json());
 *     return {lng: r.lon, lat: r.lat, zoom: 15};
 *   });
 */
export function useFlyToOnSelection(viewerRef, getPositionForRid, options = {}) {
  const {animationMs = 1200, debounceMs = 80} = options;
  const {selectedAssetRid} = useSelection();
  const lastRidRef = useRef(null);

  useEffect(() => {
    if (!selectedAssetRid || selectedAssetRid === lastRidRef.current) return;
    if (!viewerRef.current) return;
    lastRidRef.current = selectedAssetRid;
    const ridAtCallTime = selectedAssetRid;
    const t = setTimeout(async () => {
      try {
        const pos = await getPositionForRid(ridAtCallTime);
        if (!pos || ridAtCallTime !== lastRidRef.current) return;
        const v = viewerRef.current;
        if (!v) return;
        if (typeof v.flyTo === 'function') {
          v.flyTo({...pos, duration: animationMs});
        } else if (typeof v.lookAt === 'function') {
          v.lookAt(pos);
        }
      } catch (err) {
        // Soft-fail: fly-to is non-critical; don't crash the UI.
        console.warn('useFlyToOnSelection: flyTo failed', err);
      }
    }, debounceMs);
    return () => clearTimeout(t);
  }, [selectedAssetRid, viewerRef, getPositionForRid, animationMs, debounceMs]);
}

/**
 * Companion hook — scrolls a table row into view + applies a highlight class
 * when an asset is selected from elsewhere (3D pick, tree click, AI message).
 *
 * Usage in a row:
 *   const ref = useScrollIntoViewOnSelection(row.rid);
 *   return <tr ref={ref} className={isSelected ? 'is-selected' : ''}>...</tr>
 */
export function useScrollIntoViewOnSelection(rowRid) {
  const {selectedAssetRid} = useSelection();
  const ref = useRef(null);
  useEffect(() => {
    if (selectedAssetRid === rowRid && ref.current) {
      ref.current.scrollIntoView({behavior: 'smooth', block: 'center'});
    }
  }, [selectedAssetRid, rowRid]);
  return ref;
}

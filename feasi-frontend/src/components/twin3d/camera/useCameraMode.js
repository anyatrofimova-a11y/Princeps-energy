/**
 * Princeps 3D Twin v1 — useCameraMode
 * ----------------------------------------------------------------------
 * React hook that listens to `twinStore.viewMode` and flies the Mapbox
 * camera to the corresponding pose:
 *   - plan        : top-down,  pitch 0,  bearing 0,   zoom 18
 *   - oblique     : marketing, pitch 45, bearing -25, zoom 16
 *   - construction: FPS,       pitch 80, zoom 20       (first-person-ish)
 *   - drone       : cinematic orbit, pitch 55, zoom 17, auto-rotate
 *                   bearing at 0.3 deg/s
 *
 * Usage:
 *   const mapRef = useRef(null);
 *   useCameraMode(mapRef, { center: [lng, lat] });
 *
 * `mapRef.current` must be a Mapbox GL JS Map instance (or compatible
 * maplibre instance) exposing `.flyTo`, `.easeTo`, `.getBearing`,
 * `.getCenter`, `.getZoom`, `.getPitch`.
 */

import { useEffect, useRef } from 'react';

import { useTwinStore } from '../stores/twinStore.js';

const POSES = {
  plan: { pitch: 0, bearing: 0, zoom: 18 },
  oblique: { pitch: 45, bearing: -25, zoom: 16 },
  construction: { pitch: 80, bearing: 0, zoom: 20 },
  drone: { pitch: 55, bearing: 0, zoom: 17 },
};

// deg per second for drone auto-rotate
const DRONE_ROTATE_DEG_PER_SEC = 0.3;

/**
 * @param {{current: import('mapbox-gl').Map | null}} mapRef
 * @param {Object} opts
 * @param {[number, number]} [opts.center] flyTo centre (lng, lat)
 * @param {boolean} [opts.enabled=true]
 */
export function useCameraMode(mapRef, opts = {}) {
  const { center, enabled = true } = opts;
  const viewMode = useTwinStore((s) => s.viewMode);
  const rafRef = useRef(null);
  const lastTickRef = useRef(0);

  useEffect(() => {
    if (!enabled) return undefined;
    const map = mapRef && mapRef.current;
    if (!map || typeof map.flyTo !== 'function') return undefined;

    const pose = POSES[viewMode] || POSES.oblique;
    const target = {
      pitch: pose.pitch,
      bearing: pose.bearing,
      zoom: pose.zoom,
    };
    if (Array.isArray(center) && center.length >= 2) {
      target.center = [center[0], center[1]];
    } else if (typeof map.getCenter === 'function') {
      // keep current centre if caller didn't supply one
      const c = map.getCenter();
      target.center = [c.lng, c.lat];
    }

    try {
      map.flyTo({
        ...target,
        essential: true,
        speed: 1.1,
        curve: 1.4,
        duration: 900,
      });
    } catch (err) {
      console.warn('[useCameraMode] flyTo failed', err);
    }

    // ---- drone auto-rotate ----
    if (viewMode === 'drone') {
      const tick = (now) => {
        if (!mapRef.current) return;
        const dt =
          lastTickRef.current === 0 ? 0 : (now - lastTickRef.current) / 1000;
        lastTickRef.current = now;
        if (dt > 0) {
          try {
            const b = mapRef.current.getBearing();
            mapRef.current.easeTo({
              bearing: b + DRONE_ROTATE_DEG_PER_SEC * dt,
              duration: 0,
              essential: true,
            });
          } catch (err) {
            // ignore transient errors during map resize / teardown
          }
        }
        rafRef.current = requestAnimationFrame(tick);
      };
      lastTickRef.current = 0;
      rafRef.current = requestAnimationFrame(tick);
    }

    return () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [mapRef, viewMode, enabled, center && center[0], center && center[1]]);
}

export { POSES as CAMERA_POSES };
export default useCameraMode;

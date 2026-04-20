/**
 * ParcelDrawerTrigger
 * -------------------
 * Custom-event bus between any map / canvas / table and the right-side
 * `ParcelDrawer`. Decouples the map (which knows about parcel clicks) from
 * the drawer (which knows how to render dossiers) so neither has to import
 * the other.
 *
 * Wire it up:
 *
 *   // In the drawer host (App.jsx or similar)
 *   import { subscribeToParcelOpen } from "./components/parcel/ParcelDrawerTrigger";
 *   useEffect(() => subscribeToParcelOpen(setOpenInspireId), []);
 *
 *   // In any map click handler
 *   import { openParcelDrawer } from "./components/parcel/ParcelDrawerTrigger";
 *   openParcelDrawer(feature.properties.inspire_id);
 *
 * The event name is stable — `princeps-open-parcel` — so third-party widgets
 * can fire it too without importing anything.
 */

export const PARCEL_OPEN_EVENT = "princeps-open-parcel";
export const PARCEL_CLOSE_EVENT = "princeps-close-parcel";

/** Fire from any click handler. */
export function openParcelDrawer(inspireId, extras = {}) {
  if (!inspireId) return;
  const ev = new CustomEvent(PARCEL_OPEN_EVENT, {
    detail: { inspire_id: inspireId, ...extras },
  });
  window.dispatchEvent(ev);
}

export function closeParcelDrawer() {
  window.dispatchEvent(new CustomEvent(PARCEL_CLOSE_EVENT));
}

/**
 * Subscribe to open events.
 * @param {(inspireId: string, detail: object) => void} handler
 * @returns {() => void} unsubscribe
 */
export function subscribeToParcelOpen(handler) {
  const listener = (ev) => {
    const id = ev?.detail?.inspire_id;
    if (id) handler(id, ev.detail || {});
  };
  window.addEventListener(PARCEL_OPEN_EVENT, listener);
  return () => window.removeEventListener(PARCEL_OPEN_EVENT, listener);
}

export function subscribeToParcelClose(handler) {
  const listener = () => handler();
  window.addEventListener(PARCEL_CLOSE_EVENT, listener);
  return () => window.removeEventListener(PARCEL_CLOSE_EVENT, listener);
}

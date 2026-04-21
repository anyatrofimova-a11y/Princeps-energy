/**
 * datasetLayerBridge — shared helpers for the Datasets → Map "Show on Map"
 * pipeline.
 *
 * Problem this solves (BOT-DM scope):
 * ------------------------------------
 * `useDatasetLayer` navigates from the Intelligence route to "/" (LegacyApp)
 * and dispatches `princeps-activate-dataset-layer`. But:
 *   1. IntelligenceShell does NOT wrap SiteProvider, so the listener that
 *      flips `layers[...]=true` isn't mounted while the user is on
 *      `/intelligence/datasets`.
 *   2. React must tear IntelligenceShell down, mount LegacyApp, and only
 *      THEN does SiteProvider's useEffect run and attach the listener.
 *   3. A single `setTimeout(_, 0)` reliably loses the race.
 *
 * Fix strategy (three belts, no suspenders):
 *   (a) Plant the intended slug + layer in `sessionStorage` before
 *       navigating — SiteProvider's URL-param fallback at mount already
 *       activates from `?layer=...`, but we stash a copy here so any
 *       consumer can hydrate if they missed the event.
 *   (b) After navigate(), dispatch the CustomEvent several times over
 *       ~2 seconds (0ms / 60ms / 250ms / 800ms / 1600ms) so at least one
 *       fires after SiteProvider has attached its listener.
 *   (c) Also dispatch a `princeps-dismiss-mission-control` event so the
 *       legacy Mission Control overlay closes and the map becomes
 *       visible.
 */

export const DATASET_LAYER_EVENT = "princeps-activate-dataset-layer";
export const DISMISS_MISSION_CONTROL_EVENT = "princeps-dismiss-mission-control";
export const DATASET_TOAST_EVENT = "princeps-dataset-toast";
export const PENDING_KEY = "princeps.pendingDatasetLayer";

// Lightweight human-friendly label cache — keep in sync with the set of
// slugs we know about so the toast is meaningful.
const LAYER_LABELS = {
  tec_register: "NESO TEC Register",
  dno_capacity: "DNO Capacity Maps",
  land_parcels: "HMLR INSPIRE Polygons",
  repd: "REPD",
  nsip: "PINS NSIP Register",
  n1_reliability_heat: "UK N-1 Reliability",
  ea_flood_planning: "EA Flood Map for Planning",
  mod_safeguarding: "MoD Safeguarding Zones",
  caa_aerodrome_safeguarding: "CAA Aerodrome Safeguarding",
};

export function labelForSlug(slug) {
  if (!slug) return "Dataset layer";
  return LAYER_LABELS[String(slug).toLowerCase()] || slug;
}

/**
 * Stash the pending layer in sessionStorage so a late-mounting consumer
 * (SiteProvider on a cold /intelligence → / navigation) can hydrate it.
 * SiteProvider already has a URL-param fallback (`?layer=`) — this is a
 * second channel in case the URL gets scrubbed before the provider sees it.
 */
export function queuePendingLayer(slug, layer) {
  try {
    sessionStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ slug, layer, ts: Date.now() }),
    );
    // NSIP gets an auxiliary filter flag so a future NSIP-scale filter
    // can key off it without adding another slug to the URL.
    if (String(slug).toLowerCase() === "nsip") {
      sessionStorage.setItem("princeps_nsip_scale_filter", "1");
    }
  } catch {
    /* private mode / quota — fail silently */
  }
}

/**
 * Fire the activation event repeatedly, starting immediately, so at
 * least one dispatch lands after SiteProvider's listener attaches.
 * Cancels the schedule as soon as the window posts a
 * `princeps-dataset-layer-ack` back (optional — no consumer ACKs today,
 * so we just run the full schedule). This is intentionally cheap — 5
 * dispatches spread over <2s, each dispatch is O(listeners).
 */
export function dispatchLayerActivation(slug, layer) {
  const detail = { slug, layer };
  const schedule = [0, 60, 250, 800, 1600];
  schedule.forEach((ms) => {
    setTimeout(() => {
      try {
        window.dispatchEvent(new CustomEvent(DATASET_LAYER_EVENT, { detail }));
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn("datasetLayerBridge: dispatch failed", err);
      }
    }, ms);
  });
}

/**
 * Dismiss the Mission Control overlay (which occludes the map on
 * `/?redesign !== 1`). App.jsx listens and flips `activeViewMode=map`.
 */
export function dismissMissionControlOverlay() {
  try {
    window.dispatchEvent(new CustomEvent(DISMISS_MISSION_CONTROL_EVENT));
  } catch {}
}

/**
 * User-facing toast: small ephemeral "Activated: <layer>" pill.
 * The Datasets page hosts a minimal in-scope renderer that listens for
 * this event; if no renderer is present, the event is a no-op and the
 * URL/event path still works.
 */
export function emitDatasetToast(message, variant = "success") {
  try {
    window.dispatchEvent(
      new CustomEvent(DATASET_TOAST_EVENT, { detail: { message, variant } }),
    );
  } catch {}
}

/**
 * Called by consumers (e.g. SiteProvider on mount) to drain a pending
 * layer that got queued before the provider was mounted. Returns the
 * pending record once (and clears it) or null.
 *
 * Currently unused at call-site — SiteProvider's URL fallback covers the
 * cold-navigation case — but kept here so future consumers outside
 * BOT-DM's strict scope can hydrate without another helper.
 */
export function consumePendingLayer() {
  try {
    const raw = sessionStorage.getItem(PENDING_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(PENDING_KEY);
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

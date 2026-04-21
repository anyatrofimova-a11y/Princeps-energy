/**
 * useDatasetLayer — bridge between the Datasets browser and the map layer
 * system.
 *
 * Problem: the Datasets page ("Show on Map" button) lives under
 * /intelligence/datasets and navigates to "/" with `?dataset=<slug>&layer=<id>`
 * query params. The legacy map (rendered by App.jsx on the "*" catch-all)
 * already owns its own layer registry. IntelligenceShell does NOT wrap
 * SiteProvider, so a naive `setTimeout(_, 0)` dispatch races the
 * route-swap: the event fires before SiteProvider mounts and attaches its
 * listener, so the event is lost.
 *
 * Fix: see `src/lib/datasetLayerBridge.js` — three parallel channels
 * (URL param, repeat-fire event, sessionStorage queue) and a side-effect
 * that closes the Mission Control overlay so the user actually sees the
 * map change.
 *
 * Usage
 * -----
 * // From the Datasets page:
 *   const go = useDatasetLayer();
 *   <button onClick={() => go(dataset.slug, dataset.map_layer_slug)}>Show on Map</button>
 *
 * // SiteProvider already listens for `princeps-activate-dataset-layer`
 * // AND consumes `?layer=` URL params on mount; both paths are driven
 * // by this hook.
 */
import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  DATASET_LAYER_EVENT,
  dispatchLayerActivation,
  dismissMissionControlOverlay,
  emitDatasetToast,
  labelForSlug,
  queuePendingLayer,
} from "../lib/datasetLayerBridge";

export { DATASET_LAYER_EVENT };

export default function useDatasetLayer() {
  const navigate = useNavigate();

  return useCallback(
    (slug, layer) => {
      if (!slug || !layer) return;

      // 1. Queue in sessionStorage BEFORE navigating. If the URL param
      //    gets scrubbed (SiteProvider deletes them after reading) and
      //    the event gets lost, a future consumer can still hydrate.
      queuePendingLayer(slug, layer);

      // 2. Navigate to the root map with the dataset/layer in the query
      //    string. SiteProvider's mount effect reads `?layer=` and
      //    activates the matching SiteContext layer id — this is the
      //    most reliable path on cross-route navigations.
      const qs = new URLSearchParams({ dataset: slug, layer }).toString();
      navigate(`/?${qs}`);

      // 3. Fire a repeat-schedule of CustomEvents so at least one lands
      //    AFTER SiteProvider mounts and attaches its listener. Covers
      //    the intra-LegacyApp case (provider already mounted) and the
      //    cross-route case (provider mounts ~next few ticks).
      dispatchLayerActivation(slug, layer);

      // 4. Close the Mission Control overlay that otherwise covers the
      //    map on Home → Dashboard. App.jsx listens for the dismiss
      //    event and flips activeViewMode to "map".
      dismissMissionControlOverlay();

      // 5. User-visible confirmation — small ephemeral toast so the
      //    button feels responsive even during the route-swap flash.
      emitDatasetToast(`Activated: ${labelForSlug(slug)}`, "success");
    },
    [navigate],
  );
}

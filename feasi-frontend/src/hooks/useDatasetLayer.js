/**
 * useDatasetLayer — bridge between the Datasets browser and the map layer
 * system.
 *
 * Problem: the Datasets page ("Show on Map" button) lives under
 * /intelligence/datasets and navigates to "/" with `?dataset=<slug>&layer=<id>`
 * query params. The legacy map (rendered by App.jsx on the "*" catch-all)
 * already owns its own layer registry. We don't want to plumb a new prop
 * chain through it. Instead, we fire a window-level CustomEvent that the
 * map's existing layer activation code can listen for.
 *
 * Usage
 * -----
 * // On the map page (LegacyApp or wherever layers live):
 *   useEffect(() => {
 *     const handler = (e) => {
 *       const { slug, layer } = e.detail;
 *       activateLayer(layer);      // existing map API
 *     };
 *     window.addEventListener("princeps-activate-dataset-layer", handler);
 *     return () => window.removeEventListener("princeps-activate-dataset-layer", handler);
 *   }, []);
 *
 * // From the Datasets page:
 *   const go = useDatasetLayer();
 *   <button onClick={() => go(dataset.slug, dataset.map_layer_slug)}>Show on Map</button>
 *
 * The hook itself is intentionally side-effect-on-call: it navigates and
 * dispatches the event after navigation so the map is mounted when the
 * event fires.
 */
import { useCallback } from "react";
import { useNavigate } from "react-router-dom";

export const DATASET_LAYER_EVENT = "princeps-activate-dataset-layer";

export default function useDatasetLayer() {
  const navigate = useNavigate();

  return useCallback(
    (slug, layer) => {
      if (!slug || !layer) return;

      // Navigate to the root map with the dataset/layer in the query string.
      // The map page reads these on mount (see below) and also listens for
      // the custom event for in-app transitions.
      const qs = new URLSearchParams({ dataset: slug, layer }).toString();
      navigate(`/?${qs}`);

      // Dispatch on the next tick so any listeners mounted by the map page
      // have a chance to attach before the event fires.
      window.setTimeout(() => {
        try {
          window.dispatchEvent(
            new CustomEvent(DATASET_LAYER_EVENT, {
              detail: { slug, layer },
            })
          );
        } catch (err) {
          // CustomEvent is supported everywhere we care about, but fail
          // silently rather than blow up the UI.
          // eslint-disable-next-line no-console
          console.warn("useDatasetLayer: failed to dispatch event", err);
        }
      }, 0);
    },
    [navigate]
  );
}

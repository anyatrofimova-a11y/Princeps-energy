/**
 * NGEDLiveLayer — Pulse live-intelligence map overlay for NGED data.
 *
 * Adds four toggleable layers on top of the base Mapbox instance:
 *   • Headroom — every substation coloured by remaining demand/gen headroom
 *   • ECR       — embedded capacity register sites (colour by connection status)
 *   • GSPs      — live grid supply points (colour by utilisation, 5-min updates)
 *   • Licence areas — NGED 4-region aggregate flow polygons
 *
 * Every feature is clickable — the `onSelect` callback fires with the clicked
 * feature so the parent can drive the GridIntelPanel on the right-hand side.
 */
import React, { useEffect, useRef, useCallback } from "react";
import api from "../../services/api";

const SOURCE_HEADROOM   = "nged-headroom";
const SOURCE_ECR        = "nged-ecr";
const SOURCE_GSP        = "nged-gsp";
const SOURCE_LICENCE    = "nged-licence";

const LAYER_HEADROOM    = "nged-headroom-circles";
const LAYER_ECR         = "nged-ecr-circles";
const LAYER_GSP_OUTER   = "nged-gsp-halo";
const LAYER_GSP_INNER   = "nged-gsp-inner";
const LAYER_GSP_LABEL   = "nged-gsp-label";
const LAYER_LICENCE_FILL = "nged-licence-fill";
const LAYER_LICENCE_LINE = "nged-licence-line";

const EMPTY_FC = { type: "FeatureCollection", features: [] };

export default function NGEDLiveLayer({ map, layers = {}, onSelect }) {
  const loadedRef = useRef(false);

  // Load sources + layers once the map is ready
  useEffect(() => {
    if (!map) return;
    let cancelled = false;

    const attach = () => {
      if (cancelled || loadedRef.current) return;

      // Sources
      if (!map.getSource(SOURCE_HEADROOM)) {
        map.addSource(SOURCE_HEADROOM, { type: "geojson", data: EMPTY_FC });
      }
      if (!map.getSource(SOURCE_ECR)) {
        map.addSource(SOURCE_ECR, { type: "geojson", data: EMPTY_FC });
      }
      if (!map.getSource(SOURCE_GSP)) {
        map.addSource(SOURCE_GSP, { type: "geojson", data: EMPTY_FC });
      }
      if (!map.getSource(SOURCE_LICENCE)) {
        map.addSource(SOURCE_LICENCE, { type: "geojson", data: EMPTY_FC });
      }

      // Licence area polygons — lowest z
      if (!map.getLayer(LAYER_LICENCE_FILL)) {
        map.addLayer({
          id: LAYER_LICENCE_FILL,
          type: "fill",
          source: SOURCE_LICENCE,
          paint: {
            "fill-color": ["get", "fill"],
            "fill-opacity": [
              "interpolate", ["linear"], ["coalesce", ["get", "flow_intensity"], 0],
              0, 0.05,
              1, 0.22,
            ],
          },
          layout: { visibility: "none" },
        });
      }
      if (!map.getLayer(LAYER_LICENCE_LINE)) {
        map.addLayer({
          id: LAYER_LICENCE_LINE,
          type: "line",
          source: SOURCE_LICENCE,
          paint: {
            "line-color": ["get", "fill"],
            "line-width": 1.5,
            "line-dasharray": [2, 2],
            "line-opacity": 0.8,
          },
          layout: { visibility: "none" },
        });
      }

      // Headroom circles — the Network Opportunity Map
      if (!map.getLayer(LAYER_HEADROOM)) {
        map.addLayer({
          id: LAYER_HEADROOM,
          type: "circle",
          source: SOURCE_HEADROOM,
          paint: {
            "circle-radius": [
              "interpolate", ["linear"], ["zoom"],
              5, ["*", 0.3, ["coalesce", ["get", "radius"], 4]],
              10, ["coalesce", ["get", "radius"], 6],
              14, ["*", 1.8, ["coalesce", ["get", "radius"], 8]],
            ],
            "circle-color": ["coalesce", ["get", "colour"], "#888"],
            "circle-opacity": 0.85,
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 0.5,
            "circle-stroke-opacity": 0.5,
          },
          layout: { visibility: "none" },
        });
      }

      // ECR pins
      if (!map.getLayer(LAYER_ECR)) {
        map.addLayer({
          id: LAYER_ECR,
          type: "circle",
          source: SOURCE_ECR,
          paint: {
            "circle-radius": [
              "interpolate", ["linear"], ["zoom"],
              5, 1.5,
              10, ["coalesce", ["get", "radius"], 4],
              14, ["*", 1.5, ["coalesce", ["get", "radius"], 5]],
            ],
            "circle-color": ["coalesce", ["get", "colour"], "#607d8b"],
            "circle-opacity": 0.82,
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 0.8,
          },
          layout: { visibility: "none" },
        });
      }

      // GSP halo + inner
      if (!map.getLayer(LAYER_GSP_OUTER)) {
        map.addLayer({
          id: LAYER_GSP_OUTER,
          type: "circle",
          source: SOURCE_GSP,
          paint: {
            "circle-radius": [
              "interpolate", ["linear"], ["zoom"],
              5, ["*", 1.2, ["coalesce", ["get", "radius"], 8]],
              10, ["*", 1.6, ["coalesce", ["get", "radius"], 12]],
              14, ["*", 2.4, ["coalesce", ["get", "radius"], 18]],
            ],
            "circle-color": ["coalesce", ["get", "colour"], "#4a5568"],
            "circle-opacity": 0.18,
            "circle-blur": 0.25,
          },
          layout: { visibility: "none" },
        });
      }
      if (!map.getLayer(LAYER_GSP_INNER)) {
        map.addLayer({
          id: LAYER_GSP_INNER,
          type: "circle",
          source: SOURCE_GSP,
          paint: {
            "circle-radius": [
              "interpolate", ["linear"], ["zoom"],
              5, ["*", 0.6, ["coalesce", ["get", "radius"], 6]],
              10, ["*", 0.8, ["coalesce", ["get", "radius"], 10]],
              14, ["*", 1.0, ["coalesce", ["get", "radius"], 14]],
            ],
            "circle-color": ["coalesce", ["get", "colour"], "#4a5568"],
            "circle-opacity": 0.95,
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 1.8,
          },
          layout: { visibility: "none" },
        });
      }
      if (!map.getLayer(LAYER_GSP_LABEL)) {
        map.addLayer({
          id: LAYER_GSP_LABEL,
          type: "symbol",
          source: SOURCE_GSP,
          layout: {
            "text-field": ["get", "gsp_name"],
            "text-size": 11,
            "text-offset": [0, 1.8],
            "text-anchor": "top",
            "text-allow-overlap": false,
            visibility: "none",
          },
          paint: {
            "text-color": "#1a202c",
            "text-halo-color": "#ffffff",
            "text-halo-width": 1.5,
          },
        });
      }

      loadedRef.current = true;

      // Click handlers
      const bindClick = (layerId, kind) => {
        map.on("click", layerId, (e) => {
          const feature = e.features?.[0];
          if (feature && onSelect) {
            onSelect({ kind, feature, lngLat: e.lngLat });
          }
        });
        map.on("mouseenter", layerId, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", layerId, () => { map.getCanvas().style.cursor = ""; });
      };
      bindClick(LAYER_HEADROOM, "substation");
      bindClick(LAYER_ECR, "ecr");
      bindClick(LAYER_GSP_INNER, "gsp");
      bindClick(LAYER_LICENCE_FILL, "licence_area");
    };

    if (map.loaded() && map.isStyleLoaded()) {
      attach();
    } else {
      map.once("load", attach);
      map.once("style.load", attach);
    }

    return () => { cancelled = true; };
  }, [map, onSelect]);

  // Data-fetch effects — one per toggle
  useEffect(() => {
    if (!map || !layers.nged_headroom) return;
    let cancelled = false;
    (async () => {
      try {
        const fc = await api.nged.headroomGeojson("demand", null, 33, 5000);
        if (cancelled) return;
        const src = map.getSource(SOURCE_HEADROOM);
        if (src) src.setData(fc);
      } catch (e) {
        console.warn("[NGEDLiveLayer] headroom fetch failed:", e);
      }
    })();
    return () => { cancelled = true; };
  }, [map, layers.nged_headroom]);

  useEffect(() => {
    if (!map || !layers.nged_ecr) return;
    let cancelled = false;
    (async () => {
      try {
        const fc = await api.nged.ecrGeojson({ min_mw: 1, limit: 5000 });
        if (cancelled) return;
        const src = map.getSource(SOURCE_ECR);
        if (src) src.setData(fc);
      } catch (e) {
        console.warn("[NGEDLiveLayer] ECR fetch failed:", e);
      }
    })();
    return () => { cancelled = true; };
  }, [map, layers.nged_ecr]);

  useEffect(() => {
    if (!map || !layers.nged_gsp) return;
    let cancelled = false;
    const fetchGsps = async () => {
      try {
        const fc = await api.nged.gspGeojson();
        if (cancelled) return;
        const src = map.getSource(SOURCE_GSP);
        if (src) src.setData(fc);
      } catch (e) {
        console.warn("[NGEDLiveLayer] GSP fetch failed:", e);
      }
    };
    fetchGsps();
    // Refresh every 5 min while visible — GSP data is near-real-time
    const id = setInterval(fetchGsps, 5 * 60 * 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [map, layers.nged_gsp]);

  useEffect(() => {
    if (!map || !layers.nged_licence) return;
    let cancelled = false;
    (async () => {
      try {
        const fc = await api.nged.liveLicenceAreasGeojson();
        if (cancelled) return;
        const src = map.getSource(SOURCE_LICENCE);
        if (src) src.setData(fc);
      } catch (e) {
        console.warn("[NGEDLiveLayer] licence area fetch failed:", e);
      }
    })();
    return () => { cancelled = true; };
  }, [map, layers.nged_licence]);

  // Visibility toggles
  useEffect(() => {
    if (!map || !loadedRef.current) return;
    const set = (id, on) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    };
    set(LAYER_HEADROOM, !!layers.nged_headroom);
    set(LAYER_ECR, !!layers.nged_ecr);
    set(LAYER_GSP_OUTER, !!layers.nged_gsp);
    set(LAYER_GSP_INNER, !!layers.nged_gsp);
    set(LAYER_GSP_LABEL, !!layers.nged_gsp);
    set(LAYER_LICENCE_FILL, !!layers.nged_licence);
    set(LAYER_LICENCE_LINE, !!layers.nged_licence);
  }, [map, layers.nged_headroom, layers.nged_ecr, layers.nged_gsp, layers.nged_licence]);

  return null;
}

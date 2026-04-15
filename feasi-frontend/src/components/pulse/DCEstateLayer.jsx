/**
 * DCEstateLayer — NESO098 consolidated DC estate overlay.
 *
 * Renders the /api/neso098/estate.geojson feed on the base Mapbox instance.
 * Two feature classes, toggled via the `layers.dc_estate` flag:
 *   • LA rollups   — one marker per UKPN local authority (status: operational / pipeline)
 *   • Applications — anonymised Large Demand List connection queue entries (status: applied)
 *
 * Styling:
 *   - Radius scales with total_facility_power_mw
 *   - Colour by status: operational=green, pipeline=amber, applied=blue
 *   - Hyperscaler applications (≥50 MVA) get a gold ring
 *   - Click → fires onSelect with a Pulse-style feature payload
 */
import React, { useEffect, useRef } from "react";
import api from "../../services/api";

const SOURCE = "dc-estate";
const LAYER_HALO = "dc-estate-halo";
const LAYER_CIRCLE = "dc-estate-circle";
const LAYER_LABEL = "dc-estate-label";

const EMPTY_FC = { type: "FeatureCollection", features: [] };

const STATUS_COLOURS = {
  operational: "#10b981",
  pipeline:    "#f59e0b",
  applied:     "#3b82f6",
};

export default function DCEstateLayer({ map, layers = {}, onSelect }) {
  const loadedRef = useRef(false);

  useEffect(() => {
    if (!map) return;
    let cancelled = false;

    const attach = () => {
      if (cancelled || loadedRef.current) return;

      if (!map.getSource(SOURCE)) {
        map.addSource(SOURCE, { type: "geojson", data: EMPTY_FC });
      }

      if (!map.getLayer(LAYER_HALO)) {
        map.addLayer({
          id: LAYER_HALO,
          type: "circle",
          source: SOURCE,
          filter: [">=", ["coalesce", ["get", "it_power_mw"], 0], 50],
          paint: {
            "circle-radius": [
              "interpolate", ["linear"], ["coalesce", ["get", "total_facility_power_mw"], 0],
              0, 8, 50, 14, 200, 22, 500, 30,
            ],
            "circle-color": "transparent",
            "circle-stroke-color": "#fbbf24",
            "circle-stroke-width": 2,
            "circle-opacity": 0.9,
          },
          layout: { visibility: "none" },
        });
      }

      if (!map.getLayer(LAYER_CIRCLE)) {
        map.addLayer({
          id: LAYER_CIRCLE,
          type: "circle",
          source: SOURCE,
          paint: {
            "circle-radius": [
              "interpolate", ["linear"], ["coalesce", ["get", "total_facility_power_mw"], 0],
              0, 5, 50, 9, 200, 14, 500, 20,
            ],
            "circle-color": [
              "match", ["get", "status"],
              "operational", STATUS_COLOURS.operational,
              "pipeline",    STATUS_COLOURS.pipeline,
              "applied",     STATUS_COLOURS.applied,
              "#94a3b8",
            ],
            "circle-stroke-color": "#0f172a",
            "circle-stroke-width": 1.2,
            "circle-opacity": 0.85,
          },
          layout: { visibility: "none" },
        });
      }

      if (!map.getLayer(LAYER_LABEL)) {
        map.addLayer({
          id: LAYER_LABEL,
          type: "symbol",
          source: SOURCE,
          minzoom: 9,
          layout: {
            "text-field": [
              "concat",
              ["coalesce", ["get", "local_authority"], ""],
              "\n",
              ["to-string", ["round", ["coalesce", ["get", "total_facility_power_mw"], 0]]],
              " MW",
            ],
            "text-size": 10,
            "text-offset": [0, 1.5],
            "text-anchor": "top",
            "text-font": ["DIN Offc Pro Medium", "Arial Unicode MS Regular"],
            visibility: "none",
          },
          paint: {
            "text-color": "#0f172a",
            "text-halo-color": "rgba(255,255,255,0.9)",
            "text-halo-width": 1.4,
          },
        });
      }

      // Click → Pulse selection
      const clickHandler = (e) => {
        const f = e.features?.[0];
        if (!f) return;
        onSelect?.({
          id: f.properties.dc_id,
          source: "dc_estate",
          feature: {
            ...f,
            properties: {
              ...f.properties,
              id: f.properties.dc_id,
              kind: "dc_estate",
            },
          },
        });
      };
      map.on("click", LAYER_CIRCLE, clickHandler);
      map.on("mouseenter", LAYER_CIRCLE, () => {
        if (map.getCanvas()) map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", LAYER_CIRCLE, () => {
        if (map.getCanvas()) map.getCanvas().style.cursor = "";
      });

      loadedRef.current = true;
    };

    if (map.isStyleLoaded()) attach();
    else map.once("load", attach);

    return () => { cancelled = true; };
  }, [map, onSelect]);

  // Fetch data when enabled, clear source when disabled
  useEffect(() => {
    if (!map || !loadedRef.current) return;
    const visible = !!layers.dc_estate;

    if (!visible) {
      [LAYER_CIRCLE, LAYER_HALO, LAYER_LABEL].forEach(id => {
        if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
      });
      return;
    }

    [LAYER_CIRCLE, LAYER_HALO, LAYER_LABEL].forEach(id => {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "visible");
    });

    let cancelled = false;
    api.neso098.estateGeojson()
      .then(fc => {
        if (cancelled) return;
        const src = map.getSource(SOURCE);
        if (src) src.setData(fc || EMPTY_FC);
      })
      .catch(err => console.warn("DC estate fetch failed:", err));

    return () => { cancelled = true; };
  }, [map, layers.dc_estate]);

  return null;
}

import React, { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || "";

const EMPTY_FC = { type: "FeatureCollection", features: [] };

const RAG_COLORS = {
  Green: "#4caf50",
  Amber: "#ff9800",
  Red: "#f44336",
};

export default function NOMMap({ geojsonData, selectedSub, onSelectSubstation }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);

  // Initialize map
  useEffect(() => {
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        glyphs: "mapbox://fonts/mapbox/{fontstack}/{range}.pbf",
        sources: {
          "carto-light": {
            type: "raster",
            tiles: ["https://basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}@2x.png"],
            tileSize: 256,
            attribution: "&copy; CartoDB &copy; OpenStreetMap",
          },
          "carto-labels": {
            type: "raster",
            tiles: ["https://basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}@2x.png"],
            tileSize: 256,
          },
        },
        layers: [
          { id: "light-base", type: "raster", source: "carto-light" },
          { id: "labels", type: "raster", source: "carto-labels" },
        ],
      },
      center: [-1.5, 53.5],
      zoom: 6,
      maxZoom: 16,
      attributionControl: false,
    });

    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");

    map.on("load", () => {
      // NOM substations source
      map.addSource("nom-substations", {
        type: "geojson",
        data: EMPTY_FC,
      });

      // Circle layer — color by RAG, size by headroom
      map.addLayer({
        id: "nom-circles",
        type: "circle",
        source: "nom-substations",
        paint: {
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            5, ["interpolate", ["linear"], ["max", ["coalesce", ["get", "display_headroom_mw"], 0], 0],
              0, 4, 5, 6, 15, 8, 50, 12],
            10, ["interpolate", ["linear"], ["max", ["coalesce", ["get", "display_headroom_mw"], 0], 0],
              0, 6, 5, 10, 15, 14, 50, 20],
          ],
          "circle-color": [
            "match", ["get", "display_rag"],
            "Green", RAG_COLORS.Green,
            "Amber", RAG_COLORS.Amber,
            "Red", RAG_COLORS.Red,
            "#888",
          ],
          "circle-opacity": 0.8,
          "circle-blur": 0.15,
          "circle-stroke-width": [
            "case",
            ["boolean", ["feature-state", "selected"], false], 3,
            1,
          ],
          "circle-stroke-color": [
            "case",
            ["boolean", ["feature-state", "selected"], false], "#fff",
            ["match", ["get", "display_rag"],
              "Green", "rgba(76,175,80,0.4)",
              "Amber", "rgba(255,152,0,0.4)",
              "Red", "rgba(244,67,54,0.4)",
              "rgba(136,136,136,0.4)"],
          ],
        },
      });

      // Substation name labels at high zoom
      map.addLayer({
        id: "nom-labels",
        type: "symbol",
        source: "nom-substations",
        minzoom: 9,
        paint: {
          "text-color": "#333",
          "text-halo-color": "#fff",
          "text-halo-width": 1.5,
        },
        layout: {
          "text-field": ["get", "substation_name"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 10,
          "text-offset": [0, 1.5],
          "text-anchor": "top",
          "text-optional": true,
        },
      });

      // Click handler
      map.on("click", "nom-circles", (e) => {
        if (e.features && e.features.length > 0) {
          const props = e.features[0].properties;
          onSelectSubstation?.(props.substation_number);
        }
      });

      // Hover cursor + tooltip
      map.on("mouseenter", "nom-circles", (e) => {
        map.getCanvas().style.cursor = "pointer";
        if (e.features && e.features.length > 0) {
          const f = e.features[0];
          const coords = f.geometry.coordinates.slice();
          const name = f.properties.substation_name;
          const hw = f.properties.display_headroom_mw;
          const rag = f.properties.display_rag;

          if (popupRef.current) popupRef.current.remove();
          popupRef.current = new mapboxgl.Popup({
            closeButton: false,
            closeOnClick: false,
            className: "nom-tooltip",
            offset: 12,
          })
            .setLngLat(coords)
            .setHTML(`<strong>${name}</strong><br/>Headroom: ${hw} MW (${rag})`)
            .addTo(map);
        }
      });

      map.on("mouseleave", "nom-circles", () => {
        map.getCanvas().style.cursor = "";
        if (popupRef.current) {
          popupRef.current.remove();
          popupRef.current = null;
        }
      });
    });

    mapRef.current = map;
    return () => map.remove();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Update GeoJSON data when it changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const update = () => {
      const src = map.getSource("nom-substations");
      if (src) src.setData(geojsonData || EMPTY_FC);
    };

    if (map.isStyleLoaded()) {
      update();
    } else {
      map.once("load", update);
    }
  }, [geojsonData]);

  // Fly to selected substation
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedSub) return;

    map.flyTo({
      center: [selectedSub.lon, selectedSub.lat],
      zoom: Math.max(map.getZoom(), 11),
      duration: 800,
    });
  }, [selectedSub]);

  return (
    <div className="nom-map-container" ref={containerRef}>
      <div className="nom-legend">
        <div className="nom-legend-item">
          <span className="nom-legend-dot" style={{ background: RAG_COLORS.Green }} />
          Green
        </div>
        <div className="nom-legend-item">
          <span className="nom-legend-dot" style={{ background: RAG_COLORS.Amber }} />
          Amber
        </div>
        <div className="nom-legend-item">
          <span className="nom-legend-dot" style={{ background: RAG_COLORS.Red }} />
          Red
        </div>
      </div>
    </div>
  );
}

import React, { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";

const PROXY = "pmtiles://http://localhost:3000/pmtiles-proxy";

let protocolAdded = false;

export default function MapView({ slopeOpacity = 0.6, layers = {} }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);

  useEffect(() => {
    if (!protocolAdded) {
      const protocol = new Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      protocolAdded = true;
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "&copy; OpenStreetMap contributors",
          },
          terrainSource: {
            type: "raster-dem",
            url: `${PROXY}/DTM.pmtiles`,
            tileSize: 512,
            minzoom: 0,
            maxzoom: 14,
            encoding: "mapbox",
            attribution: '<a href="https://doi.org/10.1177/23998083251401613">GBDEM</a>',
          },
          hillshadeSource: {
            type: "raster-dem",
            url: `${PROXY}/DTM.pmtiles`,
            tileSize: 512,
            minzoom: 0,
            maxzoom: 11,
            encoding: "mapbox",
          },
        },
        layers: [
          { id: "osm", type: "raster", source: "osm" },
          {
            id: "hillshade",
            type: "hillshade",
            source: "hillshadeSource",
            paint: {
              "hillshade-shadow-color": "#473B24",
              "hillshade-illumination-anchor": "map",
              "hillshade-exaggeration": 0.6,
            },
          },
        ],
        terrain: {
          source: "terrainSource",
          exaggeration: 2.0,
        },
      },
      center: [-1.5, 52.5],
      zoom: 7,
      pitch: 45,
      bearing: -10,
      maxPitch: 85,
    });

    mapRef.current = map;

    map.on("load", () => {
      // Slope raster from our backend
      map.addSource("slope-raster", {
        type: "raster",
        tiles: ["/tiles/slope/{z}/{x}/{y}.png"],
        tileSize: 256,
      });
      map.addLayer({
        id: "slope-tiles",
        type: "raster",
        source: "slope-raster",
        paint: { "raster-opacity": slopeOpacity },
        layout: { visibility: layers.slope ? "visible" : "none" },
      });

      // PBCC Carbon vector overlay
      map.addSource("pbcc-carbon", {
        type: "vector",
        url: `${PROXY}/pbcc.pmtiles`,
      });
      map.addLayer({
        id: "carbon-fill",
        type: "fill",
        source: "pbcc-carbon",
        "source-layer": "pbcc",
        paint: {
          "fill-color": [
            "interpolate", ["linear"],
            ["coalesce", ["get", "total_co2"], 0],
            0, "rgba(255,255,255,0)",
            50, "#fff9c4",
            200, "#ffcc02",
            500, "#f44336",
            1000, "#b71c1c",
          ],
          "fill-opacity": 0.55,
        },
        layout: { visibility: layers.carbon ? "visible" : "none" },
      });
      map.addLayer({
        id: "carbon-line",
        type: "line",
        source: "pbcc-carbon",
        "source-layer": "pbcc",
        paint: { "line-color": "#e91e63", "line-width": 0.4, "line-opacity": 0.4 },
        layout: { visibility: layers.carbon ? "visible" : "none" },
      });

      // Local Authority boundaries
      map.addSource("pbcc-la", {
        type: "vector",
        url: `${PROXY}/la.pmtiles`,
      });
      map.addLayer({
        id: "la-line",
        type: "line",
        source: "pbcc-la",
        "source-layer": "la",
        paint: { "line-color": "#ff9800", "line-width": 2, "line-opacity": 0.7 },
        layout: { visibility: layers.la ? "visible" : "none" },
      });
      map.addLayer({
        id: "la-fill",
        type: "fill",
        source: "pbcc-la",
        "source-layer": "la",
        paint: { "fill-color": "#ff9800", "fill-opacity": 0.06 },
        layout: { visibility: layers.la ? "visible" : "none" },
      });

      // Transport overlay
      map.addSource("pbcc-transport", {
        type: "vector",
        url: `${PROXY}/transport.pmtiles`,
      });
      map.addLayer({
        id: "transport-fill",
        type: "fill",
        source: "pbcc-transport",
        "source-layer": "transport",
        paint: {
          "fill-color": "#00bcd4",
          "fill-opacity": 0.25,
        },
        layout: { visibility: layers.transport ? "visible" : "none" },
      });
      map.addLayer({
        id: "transport-line",
        type: "line",
        source: "pbcc-transport",
        "source-layer": "transport",
        paint: { "line-color": "#00838f", "line-width": 0.5, "line-opacity": 0.5 },
        layout: { visibility: layers.transport ? "visible" : "none" },
      });

      // Carbon popup on click
      map.on("click", "carbon-fill", (e) => {
        if (!e.features?.length) return;
        const f = e.features[0].properties;
        const html = Object.entries(f)
          .filter(([k]) => !k.startsWith("_"))
          .slice(0, 8)
          .map(([k, v]) => `<strong>${k}:</strong> ${v}`)
          .join("<br>");
        new maplibregl.Popup({ maxWidth: "280px" })
          .setLngLat(e.lngLat)
          .setHTML(`<div style="font-size:12px;line-height:1.6">${html}</div>`)
          .addTo(map);
      });

      // Cursor feedback
      map.on("mouseenter", "carbon-fill", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "carbon-fill", () => { map.getCanvas().style.cursor = ""; });

      map.addControl(new maplibregl.NavigationControl(), "top-left");
      map.addControl(
        new maplibregl.TerrainControl({ source: "terrainSource", exaggeration: 2.0 }),
        "top-right"
      );
    });

    return () => map.remove();
  }, []);

  // Update layer visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const layerMap = {
      slope: ["slope-tiles"],
      carbon: ["carbon-fill", "carbon-line"],
      la: ["la-line", "la-fill"],
      transport: ["transport-fill", "transport-line"],
      hillshade: ["hillshade"],
    };

    for (const [key, layerIds] of Object.entries(layerMap)) {
      const vis = layers[key] ? "visible" : "none";
      for (const lid of layerIds) {
        if (map.getLayer(lid)) {
          map.setLayoutProperty(lid, "visibility", vis);
        }
      }
    }
  }, [layers]);

  // Update slope opacity
  useEffect(() => {
    const map = mapRef.current;
    if (map && map.getLayer("slope-tiles")) {
      map.setPaintProperty("slope-tiles", "raster-opacity", slopeOpacity);
    }
  }, [slopeOpacity]);

  return <div ref={containerRef} className="mapContainer" />;
}

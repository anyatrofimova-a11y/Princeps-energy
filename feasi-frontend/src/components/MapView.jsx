import React, { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Protocol } from "pmtiles";

const SLOPE_LAYER = "slope-tiles";
// Proxied through Vite dev server to avoid CORS issues with Azure Blob Storage
const GBDEM_DTM_URL = "pmtiles://http://localhost:3000/pmtiles-proxy/DTM.pmtiles";

let protocolAdded = false;

export default function MapView({ slopeOpacity = 0.8 }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);

  useEffect(() => {
    // Register PMTiles protocol once
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
            url: GBDEM_DTM_URL,
            tileSize: 512,
            minzoom: 0,
            maxzoom: 14,
            encoding: "mapbox",
            attribution: '<a href="https://doi.org/10.1177/23998083251401613">GBDEM</a>',
          },
          hillshadeSource: {
            type: "raster-dem",
            url: GBDEM_DTM_URL,
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
      // Slope overlay from our backend
      map.addSource("slope-raster", {
        type: "raster",
        tiles: ["/tiles/slope/{z}/{x}/{y}.png"],
        tileSize: 256,
      });

      map.addLayer({
        id: SLOPE_LAYER,
        type: "raster",
        source: "slope-raster",
        paint: { "raster-opacity": slopeOpacity },
      });

      map.addControl(new maplibregl.NavigationControl(), "top-left");
      map.addControl(
        new maplibregl.TerrainControl({ source: "terrainSource", exaggeration: 2.0 }),
        "top-right"
      );
    });

    return () => map.remove();
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (map && map.getLayer(SLOPE_LAYER)) {
      map.setPaintProperty(SLOPE_LAYER, "raster-opacity", slopeOpacity);
    }
  }, [slopeOpacity]);

  return <div ref={containerRef} className="mapContainer" />;
}

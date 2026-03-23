import { useEffect, useRef } from "react";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { Tile3DLayer } from "@deck.gl/geo-layers";
import { Tiles3DLoader } from "@loaders.gl/3d-tiles";

const GOOGLE_KEY = import.meta.env.VITE_GOOGLE_MAPS_KEY || "";

/**
 * Google3DTilesOverlay — adds Google Photorealistic 3D Tiles to any Mapbox map.
 *
 * Renders photorealistic buildings, trees, and terrain from Google's 3D dataset
 * as a deck.gl overlay on the existing Mapbox GL map instance.
 *
 * Requires VITE_GOOGLE_MAPS_KEY in .env with Maps Tiles API enabled.
 */
export default function Google3DTilesOverlay({ mapInstance, enabled = false }) {
  const overlayRef = useRef(null);

  useEffect(() => {
    const map = mapInstance;
    if (!map || !enabled || !GOOGLE_KEY) return;
    // Wait for style to load before adding overlay
    if (!map.isStyleLoaded || !map.isStyleLoaded()) return;

    // Create deck.gl overlay with Tile3DLayer
    const overlay = new MapboxOverlay({
      layers: [
        new Tile3DLayer({
          id: "google-3d-photorealistic",
          data: `https://tile.googleapis.com/v1/3dtiles/root.json?key=${GOOGLE_KEY}`,
          loader: Tiles3DLoader,
          loadOptions: {
            "3d-tiles": { loadGLTF: true },
          },
          opacity: 0.95,
          pickable: false,
        }),
      ],
    });

    map.addControl(overlay);
    overlayRef.current = overlay;

    // Enable 3D terrain on the map for proper integration
    if (map.getTerrain && !map.getTerrain()) {
      try {
        if (!map.getSource("mapbox-dem-3d")) {
          map.addSource("mapbox-dem-3d", {
            type: "raster-dem",
            url: "mapbox://mapbox.mapbox-terrain-dem-v1",
            tileSize: 512,
            maxzoom: 14,
          });
        }
        map.setTerrain({ source: "mapbox-dem-3d", exaggeration: 1.2 });
      } catch {
        // Terrain may already be set
      }
    }

    return () => {
      try {
        if (overlayRef.current) {
          map.removeControl(overlayRef.current);
          overlayRef.current = null;
        }
      } catch {
        // Map may be destroyed
      }
    };
  }, [mapInstance, enabled]);

  // Update overlay when enabled changes
  useEffect(() => {
    if (!overlayRef.current) return;
    overlayRef.current.setProps({
      layers: enabled && GOOGLE_KEY
        ? [
            new Tile3DLayer({
              id: "google-3d-photorealistic",
              data: `https://tile.googleapis.com/v1/3dtiles/root.json?key=${GOOGLE_KEY}`,
              loader: Tiles3DLoader,
              loadOptions: { "3d-tiles": { loadGLTF: true } },
              opacity: 0.95,
              pickable: false,
            }),
          ]
        : [],
    });
  }, [enabled]);

  return null;
}

import { useEffect, useRef } from "react";

/**
 * DCMapOverlay — renders data centre assets as 3D extruded buildings
 * on the Mapbox map using native fill-extrusion layers.
 *
 * Buildings sit on terrain, sized by capacity, colored by PUE.
 */

const SOURCE_ID = "dc-buildings-3d";
const LAYER_FILL = "dc-buildings-fill";
const LAYER_OUTLINE = "dc-buildings-outline";
const LAYER_LABEL = "dc-buildings-label";

function createBuildingPolygon(lon, lat, widthM, heightM) {
  const dLat = heightM / 111320;
  const dLon = widthM / (111320 * Math.cos((lat * Math.PI) / 180));
  return [
    [lon - dLon / 2, lat - dLat / 2],
    [lon + dLon / 2, lat - dLat / 2],
    [lon + dLon / 2, lat + dLat / 2],
    [lon - dLon / 2, lat + dLat / 2],
    [lon - dLon / 2, lat - dLat / 2],
  ];
}

function pueColor(pue) {
  if (pue == null) return "#D4A018";
  if (pue < 1.3) return "#24a148";
  if (pue < 1.5) return "#f1c21b";
  return "#da1e28";
}

function buildGeoJSON(assets) {
  const features = assets
    .filter((a) => a.lat && a.lon)
    .map((a) => {
      const cap = a.capacity_mw || 10;
      // Scale footprint: 50m x 30m base, grows with capacity
      const scale = Math.sqrt(cap / 10);
      const width = Math.max(30, 50 * scale);
      const depth = Math.max(20, 30 * scale);
      // Height: 10m per MW, clamped
      const height = Math.max(15, Math.min(80, cap * 10));

      return {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [createBuildingPolygon(a.lon, a.lat, width, depth)],
        },
        properties: {
          id: a.id || `dc-${a.lon}-${a.lat}`,
          name: a.name || "Data Centre",
          capacity_mw: cap,
          pue: a.pue || 1.4,
          cooling_type: a.cooling_type || "air",
          status: a.status || "planned",
          height,
          color: pueColor(a.pue),
          it_load_mw: a.it_load_mw || cap * 0.8,
          water_usage_m3_day: a.water_usage_m3_day || cap * 25,
        },
      };
    });

  return { type: "FeatureCollection", features };
}

export default function DCMapOverlay({ mapInstance, dcAssets = [] }) {
  const addedRef = useRef(false);

  useEffect(() => {
    const map = mapInstance;
    if (!map || !map.isStyleLoaded()) return;

    const geojson = buildGeoJSON(dcAssets);

    // Add or update source
    if (!map.getSource(SOURCE_ID)) {
      map.addSource(SOURCE_ID, { type: "geojson", data: geojson });

      // 3D extruded buildings
      map.addLayer({
        id: LAYER_FILL,
        type: "fill-extrusion",
        source: SOURCE_ID,
        paint: {
          "fill-extrusion-color": ["get", "color"],
          "fill-extrusion-height": ["get", "height"],
          "fill-extrusion-base": 0,
          "fill-extrusion-opacity": 0.85,
        },
      });

      // Outline at ground level
      map.addLayer({
        id: LAYER_OUTLINE,
        type: "line",
        source: SOURCE_ID,
        paint: {
          "line-color": ["get", "color"],
          "line-width": 2,
          "line-opacity": 0.9,
        },
      });

      // Labels
      map.addLayer({
        id: LAYER_LABEL,
        type: "symbol",
        source: SOURCE_ID,
        layout: {
          "text-field": [
            "concat",
            ["get", "name"],
            "\n",
            ["to-string", ["get", "capacity_mw"]],
            " MW",
          ],
          "text-size": 11,
          "text-anchor": "bottom",
          "text-offset": [0, -1],
          "text-allow-overlap": true,
        },
        paint: {
          "text-color": "#ffffff",
          "text-halo-color": "rgba(0,0,0,0.7)",
          "text-halo-width": 1.5,
        },
      });

      // Click handler
      map.on("click", LAYER_FILL, (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        window.dispatchEvent(
          new CustomEvent("princeps-dc-click", { detail: p })
        );
      });
      map.on("mouseenter", LAYER_FILL, () => {
        if (!map._pickMode) map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", LAYER_FILL, () => {
        if (!map._pickMode) map.getCanvas().style.cursor = "";
      });

      addedRef.current = true;
    } else {
      map.getSource(SOURCE_ID).setData(geojson);
    }

    // Toggle visibility based on whether we have assets
    const vis = dcAssets.length > 0 ? "visible" : "none";
    [LAYER_FILL, LAYER_OUTLINE, LAYER_LABEL].forEach((lid) => {
      if (map.getLayer(lid)) map.setLayoutProperty(lid, "visibility", vis);
    });
  }, [mapInstance, dcAssets]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      const map = mapInstance;
      if (!map || !addedRef.current) return;
      try {
        [LAYER_LABEL, LAYER_OUTLINE, LAYER_FILL].forEach((lid) => {
          if (map.getLayer(lid)) map.removeLayer(lid);
        });
        if (map.getSource(SOURCE_ID)) map.removeSource(SOURCE_ID);
      } catch {
        /* map may be destroyed */
      }
    };
  }, [mapInstance]);

  return null; // purely imperative — no DOM output
}

import { useEffect, useRef, useCallback } from "react";

/**
 * Asset3DOverlay — renders ALL placed assets as 3D extruded buildings
 * on the Mapbox map, plus animated flow lines between connected assets.
 *
 * Asset types: solar_array, bess, transformer, substation, inverter,
 * wind_turbine, data_centre, cable_33kv, meter
 */

const SRC_BUILDINGS = "asset-3d-buildings";
const SRC_FLOWS = "asset-3d-flows";
const LYR_FILL = "asset-3d-fill";
const LYR_OUTLINE = "asset-3d-outline";
const LYR_LABEL = "asset-3d-label";
const LYR_FLOW = "asset-3d-flow";
const LYR_FLOW_ANIM = "asset-3d-flow-anim";

/* ── Asset visual config ── */
const ASSET_VIS = {
  solar_array:   { color: "#D4A018", heightPerMW: 1.5, baseH: 3,  maxH: 8,   widthM: 80, depthM: 60, label: "Solar" },
  bess:          { color: "#16a34a", heightPerMW: 3,   baseH: 8,  maxH: 25,  widthM: 30, depthM: 20, label: "BESS" },
  transformer:   { color: "#0891b2", heightPerMW: 0,   baseH: 12, maxH: 18,  widthM: 10, depthM: 10, label: "Transformer" },
  substation:    { color: "#78909c", heightPerMW: 0,   baseH: 8,  maxH: 15,  widthM: 25, depthM: 20, label: "Substation" },
  inverter:      { color: "#ff9800", heightPerMW: 0,   baseH: 4,  maxH: 6,   widthM: 6,  depthM: 4,  label: "Inverter" },
  wind_turbine:  { color: "#00b0ff", heightPerMW: 12,  baseH: 40, maxH: 120, widthM: 8,  depthM: 8,  label: "Wind" },
  data_centre:   { color: "#9333ea", heightPerMW: 10,  baseH: 15, maxH: 80,  widthM: 50, depthM: 30, label: "DC" },
  cable_33kv:    { color: "#607d8b", heightPerMW: 0,   baseH: 1,  maxH: 1,   widthM: 2,  depthM: 2,  label: "Cable" },
  meter:         { color: "#e91e63", heightPerMW: 0,   baseH: 3,  maxH: 3,   widthM: 2,  depthM: 2,  label: "Meter" },
};

function getVis(type) {
  return ASSET_VIS[type] || ASSET_VIS.substation;
}

function createRect(lon, lat, wM, dM) {
  const dLat = dM / 111320;
  const dLon = wM / (111320 * Math.cos((lat * Math.PI) / 180));
  return [
    [lon - dLon / 2, lat - dLat / 2],
    [lon + dLon / 2, lat - dLat / 2],
    [lon + dLon / 2, lat + dLat / 2],
    [lon - dLon / 2, lat + dLat / 2],
    [lon - dLon / 2, lat - dLat / 2],
  ];
}

/* ── Auto-connect logic ──
   Builds flow lines between assets using simple rules:
   generation → inverter → transformer → substation → grid
   bess connects to inverter bidirectionally
*/
const FLOW_ORDER = ["solar_array", "wind_turbine", "inverter", "transformer", "substation"];

function buildFlowLines(assets) {
  if (assets.length < 2) return { type: "FeatureCollection", features: [] };

  // Group by type
  const byType = {};
  assets.forEach((a) => {
    (byType[a.assetType] = byType[a.assetType] || []).push(a);
  });

  const features = [];
  const connected = new Set();

  // Connect in flow order
  for (let i = 0; i < FLOW_ORDER.length - 1; i++) {
    const fromType = FLOW_ORDER[i];
    const toType = FLOW_ORDER[i + 1];
    const froms = byType[fromType] || [];
    const tos = byType[toType] || [];
    if (froms.length === 0 || tos.length === 0) continue;

    froms.forEach((f) => {
      // Connect to nearest of next type
      let nearest = tos[0];
      let minDist = Infinity;
      tos.forEach((t) => {
        const d = Math.hypot(f.lat - t.lat, f.lon - t.lon);
        if (d < minDist) { minDist = d; nearest = t; }
      });

      const key = `${f.id}-${nearest.id}`;
      if (connected.has(key)) return;
      connected.add(key);

      features.push({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [[f.lon, f.lat], [nearest.lon, nearest.lat]],
        },
        properties: {
          from_type: f.assetType,
          to_type: nearest.assetType,
          color: getVis(f.assetType).color,
          mw: f.mw || 0,
        },
      });
    });
  }

  // BESS connects to nearest inverter
  (byType.bess || []).forEach((b) => {
    const invs = byType.inverter || byType.transformer || [];
    if (invs.length === 0) return;
    let nearest = invs[0];
    let minDist = Infinity;
    invs.forEach((inv) => {
      const d = Math.hypot(b.lat - inv.lat, b.lon - inv.lon);
      if (d < minDist) { minDist = d; nearest = inv; }
    });
    features.push({
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [[b.lon, b.lat], [nearest.lon, nearest.lat]],
      },
      properties: { from_type: "bess", to_type: nearest.assetType, color: "#16a34a", mw: b.mw || 0 },
    });
  });

  // Data centre connects to nearest substation/transformer
  (byType.data_centre || []).forEach((dc) => {
    const targets = [...(byType.substation || []), ...(byType.transformer || [])];
    if (targets.length === 0) return;
    let nearest = targets[0];
    let minDist = Infinity;
    targets.forEach((t) => {
      const d = Math.hypot(dc.lat - t.lat, dc.lon - t.lon);
      if (d < minDist) { minDist = d; nearest = t; }
    });
    features.push({
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [[dc.lon, dc.lat], [nearest.lon, nearest.lat]],
      },
      properties: { from_type: "data_centre", to_type: nearest.assetType, color: "#9333ea", mw: dc.mw || 0 },
    });
  });

  return { type: "FeatureCollection", features };
}

function buildBuildingsGeoJSON(assets, validations = {}) {
  const VERDICT_COLORS = { GO: "#16a34a", CAUTION: "#D4A018", "NO-GO": "#dc2626" };
  const VERDICT_ICONS = { GO: "\u2713", CAUTION: "\u26A0", "NO-GO": "\u2717" };

  const features = assets
    .filter((a) => a.lat && a.lon)
    .map((a) => {
      const vis = getVis(a.assetType);
      const mw = a.mw || 0;
      const scale = Math.max(1, Math.sqrt(mw / 10));
      const width = vis.widthM * scale;
      const depth = vis.depthM * scale;
      const height = Math.max(vis.baseH, Math.min(vis.maxH, vis.baseH + mw * vis.heightPerMW));

      const val = validations[a.id];
      const verdict = val?.verdict;
      const color = verdict ? VERDICT_COLORS[verdict] || vis.color : vis.color;
      const badge = verdict ? ` ${VERDICT_ICONS[verdict] || ""}` : "";
      const costStr = val?.costs?.cable_cost_gbp ? `\n£${(val.costs.cable_cost_gbp / 1000).toFixed(0)}k cable` : "";

      return {
        type: "Feature",
        geometry: {
          type: "Polygon",
          coordinates: [createRect(a.lon, a.lat, width, depth)],
        },
        properties: {
          id: a.id,
          name: a.label || vis.label,
          assetType: a.assetType,
          mw,
          height,
          color,
          label_text: `${vis.label}${badge}\n${mw > 0 ? mw + " MW" : ""}${costStr}`,
        },
      };
    });

  return { type: "FeatureCollection", features };
}

export default function Asset3DOverlay({ mapInstance, assets = [], validations = {} }) {
  const addedRef = useRef(false);

  useEffect(() => {
    const map = mapInstance;
    if (!map || !map.isStyleLoaded()) return;

    const buildings = buildBuildingsGeoJSON(assets, validations);
    const flows = buildFlowLines(assets);

    if (!map.getSource(SRC_BUILDINGS)) {
      // Buildings source + layers
      map.addSource(SRC_BUILDINGS, { type: "geojson", data: buildings });
      map.addSource(SRC_FLOWS, { type: "geojson", data: flows });

      // 3D extruded buildings
      map.addLayer({
        id: LYR_FILL,
        type: "fill-extrusion",
        source: SRC_BUILDINGS,
        paint: {
          "fill-extrusion-color": ["get", "color"],
          "fill-extrusion-height": ["get", "height"],
          "fill-extrusion-base": 0,
          "fill-extrusion-opacity": 0.85,
        },
      });

      // Ground outline
      map.addLayer({
        id: LYR_OUTLINE,
        type: "line",
        source: SRC_BUILDINGS,
        paint: {
          "line-color": ["get", "color"],
          "line-width": 2,
          "line-opacity": 0.7,
        },
      });

      // Labels
      map.addLayer({
        id: LYR_LABEL,
        type: "symbol",
        source: SRC_BUILDINGS,
        layout: {
          "text-field": ["get", "label_text"],
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

      // Flow lines (glow)
      map.addLayer({
        id: LYR_FLOW,
        type: "line",
        source: SRC_FLOWS,
        paint: {
          "line-color": ["get", "color"],
          "line-width": 4,
          "line-opacity": 0.2,
          "line-blur": 3,
        },
      });

      // Flow lines (animated core)
      map.addLayer({
        id: LYR_FLOW_ANIM,
        type: "line",
        source: SRC_FLOWS,
        paint: {
          "line-color": ["get", "color"],
          "line-width": 2,
          "line-opacity": 0.8,
          "line-dasharray": [2, 3],
        },
      });

      // Click handler
      map.on("click", LYR_FILL, (e) => {
        if (map._pickMode) return;
        const p = e.features[0].properties;
        window.dispatchEvent(
          new CustomEvent("princeps-asset-click", { detail: p })
        );
      });
      map.on("mouseenter", LYR_FILL, () => {
        if (!map._pickMode) map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", LYR_FILL, () => {
        if (!map._pickMode) map.getCanvas().style.cursor = "";
      });

      addedRef.current = true;
    } else {
      map.getSource(SRC_BUILDINGS).setData(buildings);
      map.getSource(SRC_FLOWS).setData(flows);
    }

    // Toggle visibility
    const vis = assets.length > 0 ? "visible" : "none";
    [LYR_FILL, LYR_OUTLINE, LYR_LABEL, LYR_FLOW, LYR_FLOW_ANIM].forEach((lid) => {
      if (map.getLayer(lid)) map.setLayoutProperty(lid, "visibility", vis);
    });
  }, [mapInstance, assets]);

  // Animate dash offset for flow lines
  useEffect(() => {
    const map = mapInstance;
    if (!map || assets.length < 2) return;

    let offset = 0;
    let frame;
    const animate = () => {
      offset = (offset + 0.15) % 5;
      if (map.getLayer(LYR_FLOW_ANIM)) {
        map.setPaintProperty(LYR_FLOW_ANIM, "line-dasharray", [2, 3]);
      }
      frame = requestAnimationFrame(animate);
    };
    animate();
    return () => cancelAnimationFrame(frame);
  }, [mapInstance, assets.length]);

  // Cleanup
  useEffect(() => {
    return () => {
      const map = mapInstance;
      if (!map || !addedRef.current) return;
      try {
        [LYR_LABEL, LYR_OUTLINE, LYR_FILL, LYR_FLOW_ANIM, LYR_FLOW].forEach((lid) => {
          if (map.getLayer(lid)) map.removeLayer(lid);
        });
        [SRC_BUILDINGS, SRC_FLOWS].forEach((sid) => {
          if (map.getSource(sid)) map.removeSource(sid);
        });
      } catch { /* map destroyed */ }
    };
  }, [mapInstance]);

  return null;
}

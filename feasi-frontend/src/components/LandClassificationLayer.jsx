/**
 * LandClassificationLayer — Suitability heatmap overlay on CesiumJS globe.
 *
 * Fetches classification data from /api/land/classification-heatmap and
 * renders a grid of coloured polygons using a viridis colour scale.
 * Click shows breakdown tooltip with ALC grade, slope, flood zone, etc.
 *
 * Props:
 *   viewer    — CesiumJS Viewer instance
 *   visible   — layer visibility toggle
 *   opacity   — fill opacity (0-1, default 0.6)
 *   onCellClick — callback({ cell, breakdown })
 */
import { useEffect, useRef, useCallback } from "react";
import * as Cesium from "cesium";

/* ── Viridis colour scale (0-100 mapped to 11 stops) ── */
const VIRIDIS = [
  [68, 1, 84],      // 0   — dark purple
  [72, 35, 116],     // 10
  [64, 67, 135],     // 20
  [52, 94, 141],     // 30
  [33, 119, 140],    // 40  — teal
  [21, 145, 132],    // 50
  [34, 168, 112],    // 60
  [77, 190, 83],     // 70
  [131, 210, 51],    // 80
  [186, 222, 40],    // 90
  [253, 231, 37],    // 100 — bright yellow
];

function viridisColor(score, alpha = 0.6) {
  const t = Math.max(0, Math.min(100, score)) / 100;
  const idx = t * (VIRIDIS.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.min(lo + 1, VIRIDIS.length - 1);
  const frac = idx - lo;
  const r = Math.round(VIRIDIS[lo][0] + (VIRIDIS[hi][0] - VIRIDIS[lo][0]) * frac);
  const g = Math.round(VIRIDIS[lo][1] + (VIRIDIS[hi][1] - VIRIDIS[lo][1]) * frac);
  const b = Math.round(VIRIDIS[lo][2] + (VIRIDIS[hi][2] - VIRIDIS[lo][2]) * frac);
  return new Cesium.Color(r / 255, g / 255, b / 255, alpha);
}

/* ── Constraint pin icon colours ── */
const CONSTRAINT_COLORS = {
  sssi: "#e53935",
  aonb: "#ff6f00",
  national_park: "#2e7d32",
  special_area: "#1565c0",
  scheduled_monument: "#6a1b9a",
  listed_building: "#4e342e",
  flood_zone_3: "#0288d1",
  flood_zone_2: "#4fc3f7",
  greenbelt: "#388e3c",
};

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export default function LandClassificationLayer({
  viewer,
  visible = true,
  opacity = 0.6,
  onCellClick,
}) {
  const dsRef = useRef(null);
  const pinDsRef = useRef(null);
  const lastBboxRef = useRef(null);

  /* ── Create data sources ── */
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const ds = new Cesium.CustomDataSource("land-classification");
    viewer.dataSources.add(ds);
    dsRef.current = ds;

    const pinDs = new Cesium.CustomDataSource("constraint-pins");
    viewer.dataSources.add(pinDs);
    pinDsRef.current = pinDs;

    return () => {
      if (viewer && !viewer.isDestroyed()) {
        if (dsRef.current) viewer.dataSources.remove(dsRef.current, true);
        if (pinDsRef.current) viewer.dataSources.remove(pinDsRef.current, true);
      }
      dsRef.current = null;
      pinDsRef.current = null;
    };
  }, [viewer]);

  /* ── Fetch and render classification heatmap ── */
  const fetchAndRender = useCallback(async (bbox) => {
    const ds = dsRef.current;
    const pinDs = pinDsRef.current;
    if (!ds || !pinDs) return;

    const { west, south, east, north } = bbox;

    try {
      const res = await fetch(
        `/api/land/classification-heatmap?lon_min=${west}&lat_min=${south}&lon_max=${east}&lat_max=${north}`
      );
      if (!res.ok) return;
      const data = await res.json();
      const cells = data?.cells || data?.features || data || [];
      const constraints = data?.constraints || [];

      ds.entities.removeAll();
      pinDs.entities.removeAll();

      // Render grid cells
      for (const cell of cells) {
        const props = cell.properties || cell;
        const score = props.overall_score ?? props.score ?? 50;
        const geom = cell.geometry;

        // Skip non-land / water / urban
        if (props.land_type === "water" || props.land_type === "urban" || props.exclude) {
          continue;
        }

        let positions;
        if (geom && geom.coordinates) {
          const ring = geom.type === "Polygon" ? geom.coordinates[0] : geom.coordinates[0][0];
          positions = ring.flatMap(([lon, lat]) => [lon, lat]);
        } else if (props.lon_min != null) {
          // Grid cell defined by bounds
          positions = [
            props.lon_min, props.lat_min,
            props.lon_max, props.lat_min,
            props.lon_max, props.lat_max,
            props.lon_min, props.lat_max,
          ];
        } else {
          continue;
        }

        const color = viridisColor(score, opacity);

        const entity = ds.entities.add({
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(positions),
            material: color,
            outline: true,
            outlineColor: color.withAlpha(0.15),
            outlineWidth: 1,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            classificationType: Cesium.ClassificationType.BOTH,
          },
        });

        entity._princepsData = {
          type: "classification_cell",
          data: {
            overall_score: score,
            alc_grade: props.alc_grade,
            slope_deg: props.slope_deg ?? props.slope,
            flood_zone: props.flood_zone,
            grid_proximity_km: props.grid_proximity_km ?? props.grid_distance_km,
            protected_area: props.protected_area,
            land_type: props.land_type,
            terrain: props.terrain,
          },
        };
      }

      // Render constraint pins
      for (const c of constraints) {
        const lon = c.lon || c.longitude;
        const lat = c.lat || c.latitude;
        if (lon == null || lat == null) continue;

        const cType = (c.type || c.constraint_type || "").toLowerCase().replace(/\s+/g, "_");
        const color = CONSTRAINT_COLORS[cType] || "#757575";

        pinDs.entities.add({
          position: Cesium.Cartesian3.fromDegrees(lon, lat),
          point: {
            pixelSize: 8,
            color: Cesium.Color.fromCssColorString(color).withAlpha(0.9),
            outlineColor: Cesium.Color.WHITE.withAlpha(0.8),
            outlineWidth: 1.5,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
            scaleByDistance: new Cesium.NearFarScalar(5e3, 1.2, 1e5, 0.4),
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          },
          label: {
            text: c.name || c.type || "",
            font: "9px 'DM Sans', sans-serif",
            fillColor: Cesium.Color.fromCssColorString(color),
            outlineColor: Cesium.Color.BLACK.withAlpha(0.7),
            outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -10),
            scaleByDistance: new Cesium.NearFarScalar(2e3, 1.0, 2e4, 0),
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          },
        });
      }
    } catch (e) {
      console.warn("[LandClassificationLayer] fetch error:", e);
    }
  }, [opacity]);

  /* ── Camera move handler ── */
  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !visible) {
      if (dsRef.current) dsRef.current.entities.removeAll();
      if (pinDsRef.current) pinDsRef.current.entities.removeAll();
      return;
    }

    const updateFromCamera = debounce(() => {
      const camera = viewer.camera;
      const scene = viewer.scene;
      const cameraHeight = Cesium.Cartographic.fromCartesian(camera.positionWC).height;

      // Only show when zoomed in (< 100km)
      if (cameraHeight > 100000) {
        if (dsRef.current) dsRef.current.entities.removeAll();
        if (pinDsRef.current) pinDsRef.current.entities.removeAll();
        return;
      }

      const rect = camera.computeViewRectangle(scene.globe.ellipsoid);
      if (!rect) return;

      const bbox = {
        west: Cesium.Math.toDegrees(rect.west),
        south: Cesium.Math.toDegrees(rect.south),
        east: Cesium.Math.toDegrees(rect.east),
        north: Cesium.Math.toDegrees(rect.north),
      };

      const key = `${bbox.west.toFixed(3)},${bbox.south.toFixed(3)},${bbox.east.toFixed(3)},${bbox.north.toFixed(3)}`;
      if (key === lastBboxRef.current) return;
      lastBboxRef.current = key;

      fetchAndRender(bbox);
    }, 300);

    const removeListener = viewer.camera.moveEnd.addEventListener(updateFromCamera);
    updateFromCamera();

    return () => removeListener();
  }, [viewer, visible, fetchAndRender]);

  /* ── Visibility ── */
  useEffect(() => {
    if (dsRef.current) dsRef.current.show = visible;
    if (pinDsRef.current) pinDsRef.current.show = visible;
  }, [visible]);

  return null; // Pure Cesium entity layer
}

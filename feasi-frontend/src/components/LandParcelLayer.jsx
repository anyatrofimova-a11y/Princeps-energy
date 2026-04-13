/**
 * LandParcelLayer — UK land parcel polygons on CesiumJS globe.
 *
 * Fetches parcels from /api/parcels when the camera moves, renders them
 * as GeoJSON polygons with purple/magenta fill and white boundaries.
 * Supports click-to-inspect and Shift+click multi-select.
 *
 * Props:
 *   viewer           — CesiumJS Viewer instance
 *   onParcelClick    — callback(parcel) when a single parcel is clicked
 *   onSelectionChange — callback(selectedParcels[]) when selection changes
 *   visible          — layer visibility toggle
 *   opacity          — fill opacity (0-1, default 0.3)
 *   filters          — { minArea, maxArea, tenure } for filtering parcels
 */
import { useEffect, useRef, useCallback, useState } from "react";
import * as Cesium from "cesium";

const PARCEL_FILL = Cesium.Color.fromCssColorString("#c040ff").withAlpha(0.3);
const PARCEL_STROKE = Cesium.Color.fromCssColorString("#ffffff").withAlpha(0.7);
const PARCEL_SELECTED = Cesium.Color.fromCssColorString("#D4A018").withAlpha(0.5);
const PARCEL_SELECTED_STROKE = Cesium.Color.fromCssColorString("#D4A018").withAlpha(0.9);
const LABEL_VISIBLE_HEIGHT = 20000; // metres — show labels from further out

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function polygonCentroid(coords) {
  let sumLon = 0, sumLat = 0, n = 0;
  for (const ring of coords) {
    for (const pt of ring) {
      sumLon += pt[0];
      sumLat += pt[1];
      n++;
    }
  }
  return n > 0 ? [sumLon / n, sumLat / n] : [0, 0];
}

export default function LandParcelLayer({
  viewer,
  onParcelClick,
  onSelectionChange,
  visible = true,
  opacity = 0.3,
  filters = {},
  filterVersion = 0,
}) {
  const dsRef = useRef(null);
  const handlerRef = useRef(null);
  const parcelsRef = useRef([]);
  const selectedRef = useRef(new Set());
  const [selectedParcels, setSelectedParcels] = useState([]);
  const lastBboxRef = useRef(null);

  /* ── Create data source ── */
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const ds = new Cesium.CustomDataSource("land-parcels");
    viewer.dataSources.add(ds);
    dsRef.current = ds;

    return () => {
      if (viewer && !viewer.isDestroyed() && dsRef.current) {
        viewer.dataSources.remove(dsRef.current, true);
      }
      dsRef.current = null;
    };
  }, [viewer]);

  /* ── Fetch parcels for current bbox ── */
  const fetchParcels = useCallback(async (bbox) => {
    const { west, south, east, north } = bbox;
    try {
      const res = await fetch(
        `/api/land/parcels?west=${west}&south=${south}&east=${east}&north=${north}`
      );
      if (!res.ok) return;
      const data = await res.json();
      return data?.features || data?.parcels || data || [];
    } catch (e) {
      console.warn("[LandParcelLayer] fetch error:", e);
      return [];
    }
  }, []);

  /* ── Render parcels to Cesium entities ── */
  const renderParcels = useCallback((parcels, cameraHeight) => {
    const ds = dsRef.current;
    if (!ds) return;
    ds.entities.removeAll();
    parcelsRef.current = parcels;

    const showLabels = cameraHeight < LABEL_VISIBLE_HEIGHT;
    const selected = selectedRef.current;
    const fillAlpha = opacity;

    for (const p of parcels) {
      const props = p.properties || p;
      const titleNo = props.title_number || props.titleNumber || props.title_no || "";
      const geom = p.geometry;
      if (!geom || !geom.coordinates) continue;

      // Apply filters
      const areaHa = props.area_ha || props.area || 0;
      if (filters.minArea && areaHa < filters.minArea) continue;
      if (filters.maxArea && areaHa > filters.maxArea) continue;
      if (filters.tenure && filters.tenure !== "All" && props.tenure !== filters.tenure) continue;

      const isSelected = selected.has(titleNo);
      const coords = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];

      for (const polygon of coords) {
        const ring = polygon[0];
        if (!ring || ring.length < 3) continue;

        const positions = ring.flatMap(([lon, lat]) => [lon, lat]);

        const entity = ds.entities.add({
          polygon: {
            hierarchy: Cesium.Cartesian3.fromDegreesArray(positions),
            material: isSelected
              ? PARCEL_SELECTED.withAlpha(fillAlpha + 0.2)
              : Cesium.Color.fromCssColorString("#c040ff").withAlpha(fillAlpha),
            outline: true,
            outlineColor: isSelected ? PARCEL_SELECTED_STROKE : PARCEL_STROKE,
            outlineWidth: isSelected ? 2.5 : 1.5,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            classificationType: Cesium.ClassificationType.BOTH,
          },
        });
        entity._princepsData = {
          type: "parcel",
          data: { ...props, title_number: titleNo },
        };
        entity._parcelTitle = titleNo;

        // Label at centroid — show Bk number (title number)
        if (showLabels && titleNo) {
          const [cLon, cLat] = polygonCentroid(polygon);
          // Format: extract prefix + number for compact display
          const match = titleNo.match(/^([A-Z]{1,3})(\d+)$/);
          const displayText = match ? `Bk ${match[1]}${match[2]}` : titleNo;
          ds.entities.add({
            position: Cesium.Cartesian3.fromDegrees(cLon, cLat),
            label: {
              text: displayText,
              font: "bold 12px 'JetBrains Mono', monospace",
              fillColor: isSelected
                ? Cesium.Color.fromCssColorString("#D4A018")
                : Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK.withAlpha(0.9),
              outlineWidth: 4,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.CENTER,
              horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
              scaleByDistance: new Cesium.NearFarScalar(500, 1.2, 20000, 0.5),
              pixelOffset: new Cesium.Cartesian2(0, 0),
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
              showBackground: true,
              backgroundColor: Cesium.Color.BLACK.withAlpha(0.5),
              backgroundPadding: new Cesium.Cartesian2(6, 4),
            },
          });
        }
      }
    }
  }, [opacity, filters]);

  /* ── Camera move handler (debounced) ── */
  useEffect(() => {
    if (!viewer || viewer.isDestroyed() || !visible) {
      if (dsRef.current) dsRef.current.entities.removeAll();
      return;
    }

    const scene = viewer.scene;

    const updateFromCamera = debounce(async () => {
      const camera = viewer.camera;
      const canvas = scene.canvas;
      const cameraHeight = Cesium.Cartographic.fromCartesian(
        camera.positionWC
      ).height;

      // Only fetch when zoomed in enough (< 50km)
      if (cameraHeight > 50000) {
        if (dsRef.current) dsRef.current.entities.removeAll();
        return;
      }

      // Get camera viewport bbox
      const rect = camera.computeViewRectangle(scene.globe.ellipsoid);
      if (!rect) return;

      const west = Cesium.Math.toDegrees(rect.west);
      const south = Cesium.Math.toDegrees(rect.south);
      const east = Cesium.Math.toDegrees(rect.east);
      const north = Cesium.Math.toDegrees(rect.north);

      // Skip if bbox unchanged AND filters haven't changed
      const bboxKey = `${west.toFixed(4)},${south.toFixed(4)},${east.toFixed(4)},${north.toFixed(4)}_fv${filterVersion}`;
      if (bboxKey === lastBboxRef.current) return;
      lastBboxRef.current = bboxKey;

      const parcels = await fetchParcels({ west, south, east, north });
      if (parcels && parcels.length > 0) {
        renderParcels(parcels, cameraHeight);
      }
    }, 300);

    const removeListener = camera_addMoveEnd(viewer, updateFromCamera);
    // Initial load (or re-load on filter change)
    updateFromCamera();

    return () => {
      removeListener();
    };
  }, [viewer, visible, fetchParcels, renderParcels, filterVersion]);

  /* ── Click handler for parcel selection ── */
  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handlerRef.current = handler;

    handler.setInputAction((click) => {
      const picked = viewer.scene.pick(click.position);
      if (!picked?.id?._parcelTitle) return;

      const titleNo = picked.id._parcelTitle;
      const parcelData = picked.id._princepsData?.data;
      const shiftHeld = click.position._shiftKey || window._princepsShiftHeld;

      if (shiftHeld) {
        // Multi-select toggle
        const sel = new Set(selectedRef.current);
        if (sel.has(titleNo)) {
          sel.delete(titleNo);
        } else {
          sel.add(titleNo);
        }
        selectedRef.current = sel;
        const selected = parcelsRef.current
          .filter(p => sel.has((p.properties || p).title_number || (p.properties || p).titleNumber || (p.properties || p).title_no))
          .map(p => p.properties || p);
        setSelectedParcels(selected);
        onSelectionChange?.(selected);

        // Re-render to update highlight
        const cameraHeight = Cesium.Cartographic.fromCartesian(
          viewer.camera.positionWC
        ).height;
        renderParcels(parcelsRef.current, cameraHeight);
      } else {
        // Single select
        selectedRef.current = new Set([titleNo]);
        const selected = [parcelData];
        setSelectedParcels(selected);
        onParcelClick?.(parcelData);
        onSelectionChange?.(selected);

        // Re-render
        const cameraHeight = Cesium.Cartographic.fromCartesian(
          viewer.camera.positionWC
        ).height;
        renderParcels(parcelsRef.current, cameraHeight);
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    return () => {
      if (handlerRef.current && !handlerRef.current.isDestroyed()) {
        handlerRef.current.destroy();
      }
      handlerRef.current = null;
    };
  }, [viewer, onParcelClick, onSelectionChange, renderParcels]);

  /* ── Track Shift key globally ── */
  useEffect(() => {
    const down = (e) => { if (e.key === "Shift") window._princepsShiftHeld = true; };
    const up = (e) => { if (e.key === "Shift") window._princepsShiftHeld = false; };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  /* ── Visibility toggle ── */
  useEffect(() => {
    if (dsRef.current) {
      dsRef.current.show = visible;
    }
  }, [visible]);

  return null; // Pure Cesium entity layer, no DOM
}

/* Helper: attach camera move-end listener, return cleanup function */
function camera_addMoveEnd(viewer, callback) {
  const removeListener = viewer.camera.moveEnd.addEventListener(callback);
  return () => removeListener();
}

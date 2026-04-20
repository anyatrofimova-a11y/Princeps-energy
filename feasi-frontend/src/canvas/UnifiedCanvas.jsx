/**
 * UnifiedCanvas — MapLibre base map + deck.gl MapboxOverlay (interleaved)
 * with an EditableGeoJsonLayer for polygon drawing/editing.
 *
 * Base map: Protomaps PMTiles (public demo URL by default). Override with
 * VITE_MAPLIBRE_STYLE for production.
 *
 * Emits:
 *   props.onSelect(feature | null)       — latest drawn/selected polygon
 *   props.drawMode                       — controlled: 'view' | 'draw' | 'modify'
 *   props.onDrawModeChange(mode)         — controlled change callback
 */
import React, { useEffect, useRef, useState, useCallback } from "react";
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";
import { MapboxOverlay } from "@deck.gl/mapbox";
import {
  EditableGeoJsonLayer,
  DrawPolygonMode,
  ViewMode,
  ModifyMode,
} from "@deck.gl-community/editable-layers";
import layersProtomaps from "protomaps-themes-base";
import "maplibre-gl/dist/maplibre-gl.css";

const DEFAULT_PMTILES =
  "https://build.protomaps.com/20240101.pmtiles"; // public demo. See src/canvas/README.md.

const INITIAL_VIEW = { lon: -2.5, lat: 54, zoom: 5 }; // UK

const MODE_MAP = {
  view: ViewMode,
  draw: DrawPolygonMode,
  modify: ModifyMode,
};

function buildProtomapsStyle(pmtilesUrl) {
  return {
    version: 8,
    glyphs:
      "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf",
    sprite:
      "https://protomaps.github.io/basemaps-assets/sprites/v4/light",
    sources: {
      protomaps: {
        type: "vector",
        url: `pmtiles://${pmtilesUrl}`,
        attribution:
          '<a href="https://protomaps.com">Protomaps</a> © <a href="https://openstreetmap.org">OpenStreetMap</a>',
      },
    },
    layers: layersProtomaps("protomaps", "light"),
  };
}

export default function UnifiedCanvas({
  onSelect,
  drawMode = "view",
  onDrawModeChange,
  featureCollection,
  onFeatureCollectionChange,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);

  const [internalFC, setInternalFC] = useState(
    featureCollection || { type: "FeatureCollection", features: [] }
  );
  const [selectedIndexes, setSelectedIndexes] = useState([]);

  // Keep refs in sync for use inside deck.gl callbacks (which close over state).
  const fcRef = useRef(internalFC);
  useEffect(() => {
    fcRef.current = internalFC;
  }, [internalFC]);

  const drawModeRef = useRef(drawMode);
  useEffect(() => {
    drawModeRef.current = drawMode;
  }, [drawMode]);

  const notifySelection = useCallback(
    (fc) => {
      if (!onSelect) return;
      const last = fc?.features?.[fc.features.length - 1] || null;
      onSelect(last);
    },
    [onSelect]
  );

  // Build editable layer reactively
  const buildEditableLayer = useCallback(() => {
    const Mode = MODE_MAP[drawModeRef.current] || ViewMode;
    return new EditableGeoJsonLayer({
      id: "pc-editable",
      data: fcRef.current,
      mode: Mode,
      selectedFeatureIndexes: selectedIndexes,
      pickable: true,
      getFillColor: [201, 162, 77, 48],
      getLineColor: [201, 162, 77, 220],
      getLineWidth: 2,
      lineWidthMinPixels: 2,
      getEditHandlePointColor: [201, 162, 77, 255],
      getEditHandlePointRadius: 5,
      editHandlePointRadiusMinPixels: 4,
      onEdit: ({ updatedData, editType }) => {
        fcRef.current = updatedData;
        setInternalFC(updatedData);
        if (onFeatureCollectionChange) onFeatureCollectionChange(updatedData);

        // Auto-select newly added feature; emit selection for completed polygons.
        if (editType === "addFeature") {
          const idx = updatedData.features.length - 1;
          setSelectedIndexes([idx]);
          notifySelection(updatedData);
          // Auto-return to view once a polygon is complete.
          if (onDrawModeChange) onDrawModeChange("view");
        } else if (
          editType === "movePosition" ||
          editType === "addPosition" ||
          editType === "removePosition" ||
          editType === "finishMovePosition"
        ) {
          notifySelection(updatedData);
        }
      },
    });
  }, [
    selectedIndexes,
    onFeatureCollectionChange,
    notifySelection,
    onDrawModeChange,
  ]);

  // ── Init map ──
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    // Register pmtiles protocol with MapLibre (per-instance is safe; calling
    // addProtocol twice with the same name is idempotent in practice).
    const protocol = new Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);

    const styleOverride = import.meta.env.VITE_MAPLIBRE_STYLE;
    const style = styleOverride
      ? styleOverride
      : buildProtomapsStyle(DEFAULT_PMTILES);

    const map = new maplibregl.Map({
      container: containerRef.current,
      style,
      center: [INITIAL_VIEW.lon, INITIAL_VIEW.lat],
      zoom: INITIAL_VIEW.zoom,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    const overlay = new MapboxOverlay({
      interleaved: true,
      layers: [],
    });
    map.addControl(overlay);

    mapRef.current = map;
    overlayRef.current = overlay;

    map.on("load", () => {
      overlay.setProps({ layers: [buildEditableLayer()] });
    });

    return () => {
      try { overlay.finalize?.(); } catch (_) {}
      try { map.remove(); } catch (_) {}
      try { maplibregl.removeProtocol("pmtiles"); } catch (_) {}
      mapRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Update deck.gl layers when mode / data / selection changes ──
  useEffect(() => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    overlay.setProps({ layers: [buildEditableLayer()] });
  }, [drawMode, internalFC, selectedIndexes, buildEditableLayer]);

  // ── External featureCollection overrides local state ──
  useEffect(() => {
    if (featureCollection && featureCollection !== internalFC) {
      setInternalFC(featureCollection);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [featureCollection]);

  // ── Toolbar ──
  const Toolbar = (
    <div className="pc-canvas-toolbar" role="toolbar" aria-label="Drawing tools">
      <button
        type="button"
        className={`pc-tool-btn ${drawMode === "view" ? "active" : ""}`}
        title="View / pan (Esc)"
        onClick={() => onDrawModeChange && onDrawModeChange("view")}
        aria-pressed={drawMode === "view"}
      >
        V
      </button>
      <button
        type="button"
        className={`pc-tool-btn ${drawMode === "draw" ? "active" : ""}`}
        title="Draw polygon (double-click to finish)"
        onClick={() => onDrawModeChange && onDrawModeChange("draw")}
        aria-pressed={drawMode === "draw"}
      >
        P
      </button>
      <button
        type="button"
        className={`pc-tool-btn ${drawMode === "modify" ? "active" : ""}`}
        title="Modify vertices"
        onClick={() => onDrawModeChange && onDrawModeChange("modify")}
        aria-pressed={drawMode === "modify"}
      >
        M
      </button>
    </div>
  );

  return (
    <div className="pc-centre">
      <div ref={containerRef} className="pc-map-container" />
      {Toolbar}
    </div>
  );
}

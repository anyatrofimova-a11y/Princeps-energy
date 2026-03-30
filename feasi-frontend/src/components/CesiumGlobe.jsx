/**
 * CesiumGlobe — Reusable CesiumJS globe with terrain, 3D tiles, and NASA GIBS.
 *
 * Provides a full 3D globe with:
 *   - Cesium World Terrain (quantized mesh, water mask)
 *   - Google Photorealistic 3D Tiles (optional, needs VITE_GOOGLE_MAPS_KEY)
 *   - Cesium OSM Buildings (optional)
 *   - NASA GIBS satellite imagery layers
 *   - Dark atmosphere + sky
 *
 * Props:
 *   onReady(viewer)   — called when Cesium viewer is initialized
 *   darkMode          — dark globe styling (default true)
 *   showTerrain       — enable 3D terrain (default true)
 *   showBuildings     — enable OSM 3D buildings (default true)
 *   show3DTiles       — enable Google Photorealistic 3D Tiles (default false)
 *   gibsLayers        — array of GIBS layer keys to enable
 *   gibsDate          — date string (YYYY-MM-DD) for GIBS imagery
 *   initialView       — { lon, lat, height, heading, pitch } for initial camera
 *   className         — additional CSS class
 *   style             — inline style override
 *   children          — Resium child entities
 */
import React, { useEffect, useRef, useCallback, useState } from "react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import {
  createWorldTerrain,
  googlePhotorealistic3DTilesUrl,
  createOSMBuildings,
  createGIBSProvider,
  UK_CENTER,
  UK_ORIENTATION,
} from "../lib/cesium-config";

export default function CesiumGlobe({
  onReady,
  darkMode = true,
  showTerrain = true,
  showBuildings = true,
  show3DTiles = false,
  gibsLayers = [],
  gibsDate,
  initialView,
  className = "",
  style,
  children,
}) {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const buildingsRef = useRef(null);
  const tiles3dRef = useRef(null);
  const gibsProvidersRef = useRef({});
  const [ready, setReady] = useState(false);

  /* ── Initialize Cesium Viewer ──────────────────────────────────────── */
  useEffect(() => {
    if (!containerRef.current || viewerRef.current) return;

    // Set default view BEFORE creating viewer so globe never shows world view
    Cesium.Camera.DEFAULT_VIEW_RECTANGLE = Cesium.Rectangle.fromDegrees(-8, 49, 2, 59); // UK bounds

    const viewer = new Cesium.Viewer(containerRef.current, {
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      infoBox: false,
      sceneModePicker: false,
      selectionIndicator: false,
      timeline: false,
      animation: false,
      fullscreenButton: false,
      vrButton: false,
      navigationHelpButton: false,
      creditContainer: document.createElement("div"),
      baseLayer: false,
      requestRenderMode: false,
      maximumRenderTimeChange: Infinity,
      msaaSamples: 4,
      useBrowserRecommendedResolution: false, // render at full device pixel ratio for crisp output
      orderIndependentTranslucency: false,
      shadows: false,
      terrainShadows: Cesium.ShadowMode.DISABLED,
      contextOptions: {
        webgl: { antialias: true, preserveDrawingBuffer: false },
      },
    });

    viewerRef.current = viewer;

    // Base imagery — use Bing Maps aerial with labels for best quality
    if (darkMode) {
      viewer.imageryLayers.addImageryProvider(
        new Cesium.UrlTemplateImageryProvider({
          url: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
          credit: "CartoDB",
          maximumLevel: 19,
        })
      );
    } else {
      const mbToken = import.meta.env.VITE_MAPBOX_TOKEN || "";
      if (mbToken) {
        // Single crisp layer: Mapbox satellite with vector labels baked in
        viewer.imageryLayers.addImageryProvider(
          new Cesium.UrlTemplateImageryProvider({
            url: `https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}@2x.jpg90?access_token=${mbToken}`,
            credit: "Mapbox, Maxar",
            maximumLevel: 22,
            tileWidth: 512,
            tileHeight: 512,
          })
        );
      } else {
        viewer.imageryLayers.addImageryProvider(
          new Cesium.UrlTemplateImageryProvider({
            url: "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            credit: "Esri, Maxar",
            maximumLevel: 19,
          })
        );
      }
    }

    // Scene settings
    const scene = viewer.scene;
    scene.globe.enableLighting = false; // no day/night shading — cleaner
    scene.globe.depthTestAgainstTerrain = false;
    scene.screenSpaceCameraController.minimumZoomDistance = 5; // allow very close zoom
    scene.fog.enabled = true;
    scene.fog.density = 0.0001;
    scene.fog.minimumBrightness = 0.1;

    if (darkMode) {
      scene.globe.baseColor = Cesium.Color.fromCssColorString("#0a0a14");
      scene.backgroundColor = Cesium.Color.fromCssColorString("#000008");
    } else {
      scene.globe.baseColor = Cesium.Color.fromCssColorString("#e8ecf0");
      scene.backgroundColor = Cesium.Color.fromCssColorString("#b4cfe0");
    }

    // Atmosphere — natural sky
    scene.skyAtmosphere.hueShift = darkMode ? -0.05 : 0;
    scene.skyAtmosphere.saturationShift = darkMode ? -0.4 : 0;
    scene.skyAtmosphere.brightnessShift = darkMode ? -0.3 : 0;

    // Antialiasing
    if (Cesium.PostProcessStageLibrary.createFXAAStage) {
      scene.postProcessStages.fxaa.enabled = true;
    }

    // Set initial camera position
    if (initialView) {
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(
          initialView.lon,
          initialView.lat,
          initialView.height || 1200000
        ),
        orientation: {
          heading: Cesium.Math.toRadians(initialView.heading || 350),
          pitch: Cesium.Math.toRadians(initialView.pitch || -55),
          roll: 0,
        },
      });
    } else {
      viewer.camera.setView({
        destination: UK_CENTER,
        orientation: UK_ORIENTATION,
      });
    }

    // Terrain
    if (showTerrain) {
      createWorldTerrain().then((tp) => {
        if (viewerRef.current) {
          viewerRef.current.terrainProvider = tp;
        }
      });
    }

    setReady(true);
    onReady?.(viewer);

    return () => {
      if (viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.destroy();
      }
      viewerRef.current = null;
      buildingsRef.current = null;
      tiles3dRef.current = null;
      gibsProvidersRef.current = {};
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── OSM Buildings toggle ──────────────────────────────────────────── */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    if (showBuildings && !buildingsRef.current) {
      createOSMBuildings().then((tileset) => {
        if (tileset && viewerRef.current && !viewerRef.current.isDestroyed()) {
          buildingsRef.current = viewerRef.current.scene.primitives.add(tileset);
        }
      });
    } else if (!showBuildings && buildingsRef.current) {
      viewer.scene.primitives.remove(buildingsRef.current);
      buildingsRef.current = null;
    }
  }, [showBuildings, ready]);

  /* ── Google Photorealistic 3D Tiles toggle ─────────────────────────── */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    if (show3DTiles && !tiles3dRef.current) {
      const url = googlePhotorealistic3DTilesUrl();
      if (url) {
        Cesium.Cesium3DTileset.fromUrl(url, {
          maximumScreenSpaceError: 4,  // Lower = sharper (default 16)
          preloadWhenHidden: true,
          preferLeaves: true,
          dynamicScreenSpaceError: true,
          dynamicScreenSpaceErrorDensity: 0.00278,
          dynamicScreenSpaceErrorFactor: 4.0,
        }).then((tileset) => {
          if (viewerRef.current && !viewerRef.current.isDestroyed()) {
            tiles3dRef.current = viewerRef.current.scene.primitives.add(tileset);
          }
        }).catch(() => {});
      }
    } else if (!show3DTiles && tiles3dRef.current) {
      viewer.scene.primitives.remove(tiles3dRef.current);
      tiles3dRef.current = null;
    }
  }, [show3DTiles, ready]);

  /* ── GIBS layers toggle ────────────────────────────────────────────── */
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || viewer.isDestroyed()) return;

    const current = gibsProvidersRef.current;
    const wantedSet = new Set(gibsLayers);

    // Remove layers no longer wanted
    for (const key of Object.keys(current)) {
      if (!wantedSet.has(key)) {
        viewer.imageryLayers.remove(current[key], true);
        delete current[key];
      }
    }

    // Add new layers
    for (const key of gibsLayers) {
      if (!current[key]) {
        const provider = createGIBSProvider(key, gibsDate);
        if (provider) {
          const layer = viewer.imageryLayers.addImageryProvider(provider);
          layer.alpha = 0.7;
          current[key] = layer;
        }
      }
    }
  }, [gibsLayers, gibsDate, ready]);

  return (
    <div
      ref={containerRef}
      className={`cesium-globe ${className}`}
      style={{ width: "100%", height: "100%", ...style }}
    >
      {children}
    </div>
  );
}

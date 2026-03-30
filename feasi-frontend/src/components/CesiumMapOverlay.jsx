/**
 * CesiumMapOverlay — Full Cesium 3D globe overlay for the main MapView.
 *
 * Activated via the "Cesium Globe" layer toggle. Renders a photorealistic
 * 3D globe with terrain, buildings, and NASA GIBS layers overlaid on
 * the existing map. Energy assets and grid data are plotted as Cesium entities.
 *
 * Props:
 *   enabled       — whether to show the Cesium overlay
 *   layers        — current layer state (for GIBS toggles)
 *   energyAssets  — GeoJSON FeatureCollection of energy assets
 *   gridSubs      — grid substations data (from NOM/grid endpoints)
 *   onPick(loc)   — callback when user clicks a location on the globe
 */
import React, { useEffect, useRef, useCallback, useState } from "react";
import * as Cesium from "cesium";
import CesiumGlobe from "./CesiumGlobe";
import { voltageColorCesium, utilisationColorCesium } from "../lib/cesium-config";

const ASSET_COLORS = {
  nuclear: "#e53935",
  gas: "#ff8f00",
  biomass: "#8d6e63",
  wind: "#00b0ff",
  solar: "#fdd835",
  hydro: "#1565c0",
  battery: "#7cb342",
  interconnector: "#ab47bc",
  substation: "#78909c",
};

// Map GIBS layer IDs from SiteContext to cesium-config keys
const GIBS_MAP = {
  gibsModis: "modis_truecolor",
  gibsViirs: "viirs_truecolor",
  gibsNightlights: "viirs_nightlights",
  gibsNdvi: "ndvi",
  gibsLandTemp: "land_surface_temp",
  gibsCloudFraction: "cloud_fraction",
  gibsFire: "fire_thermal",
};

export default function CesiumMapOverlay({ enabled, layers = {}, onPick }) {
  const viewerRef = useRef(null);
  const assetDsRef = useRef(null);

  // Collect active GIBS layers
  const activeGibs = Object.entries(GIBS_MAP)
    .filter(([siteKey]) => layers[siteKey])
    .map(([, cesiumKey]) => cesiumKey);

  const handleReady = useCallback((viewer) => {
    viewerRef.current = viewer;

    // Asset data source
    const ds = new Cesium.CustomDataSource("map-assets");
    viewer.dataSources.add(ds);
    assetDsRef.current = ds;

    // Click handler for location picking
    if (onPick) {
      const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      handler.setInputAction((click) => {
        const cartesian = viewer.camera.pickEllipsoid(click.position, viewer.scene.globe.ellipsoid);
        if (cartesian) {
          const carto = Cesium.Cartographic.fromCartesian(cartesian);
          onPick({
            lat: Cesium.Math.toDegrees(carto.latitude),
            lon: Cesium.Math.toDegrees(carto.longitude),
          });
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    }

    // Load energy assets
    fetch("/analytics/energy-assets")
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data?.features || !assetDsRef.current) return;
        for (const f of data.features) {
          const [lon, lat] = f.geometry.coordinates;
          const props = f.properties;
          const color = ASSET_COLORS[props.asset_type] || "#888";
          const size = 4 + Math.min(props.capacity_mw || 0, 1000) / 80;

          assetDsRef.current.entities.add({
            position: Cesium.Cartesian3.fromDegrees(lon, lat, 50),
            point: {
              pixelSize: size,
              color: Cesium.Color.fromCssColorString(color).withAlpha(0.85),
              outlineColor: Cesium.Color.fromCssColorString(color).withAlpha(0.4),
              outlineWidth: 2,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
              scaleByDistance: new Cesium.NearFarScalar(1e4, 1.2, 2e6, 0.3),
            },
            label: {
              text: props.name || "",
              font: "10px 'DM Sans', sans-serif",
              fillColor: Cesium.Color.WHITE.withAlpha(0.8),
              outlineColor: Cesium.Color.BLACK.withAlpha(0.6),
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -8),
              scaleByDistance: new Cesium.NearFarScalar(5e3, 1.0, 5e5, 0),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          });
        }
      })
      .catch(() => {});

    // Load grid substations
    fetch("/api/grid/substations")
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data || !assetDsRef.current) return;
        const subs = data.substations || data;
        for (const s of subs) {
          if (!s.lon || !s.lat) continue;
          const util = s.demand_mw / Math.max(s.capacity_mw || 1, 1);
          const height = Math.max(s.demand_mw * 30, 500);

          assetDsRef.current.entities.add({
            position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat, height / 2),
            cylinder: {
              length: height,
              topRadius: 800,
              bottomRadius: 1000,
              material: utilisationColorCesium(util).withAlpha(0.7),
              outline: true,
              outlineColor: utilisationColorCesium(util).withAlpha(0.3),
              shadows: Cesium.ShadowMode.DISABLED,
            },
            label: {
              text: s.name || s.gsp_name || "",
              font: "10px 'JetBrains Mono', monospace",
              fillColor: Cesium.Color.WHITE.withAlpha(0.85),
              outlineColor: Cesium.Color.BLACK.withAlpha(0.7),
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -10),
              scaleByDistance: new Cesium.NearFarScalar(1e4, 1.0, 1e6, 0),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          });
        }
      })
      .catch(() => {});
  }, [onPick]);

  if (!enabled) return null;

  return (
    <div className="cesium-map-overlay">
      <CesiumGlobe
        onReady={handleReady}
        darkMode={false}
        showTerrain={true}
        showBuildings={true}
        show3DTiles={!!layers.google3d}
        gibsLayers={activeGibs}
        className="cesium-map-overlay-globe"
      />
    </div>
  );
}

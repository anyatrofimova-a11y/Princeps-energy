/**
 * Princeps 3D Twin v1 — TwinRoot shell
 * ----------------------------------------------------------------------
 * Top-level twin shell. New pathway, does NOT touch:
 *   DataCentreTwin.jsx, DigitalTwin.jsx, GridTwinCesium.jsx,
 *   AssessProjectTwin.jsx.
 *
 * Props:
 *   projectId    : string — persistence namespace
 *   polygon_wkt  : 'POLYGON((lng lat, lng lat, ...))' site boundary
 *   tech         : 'bess' | 'solar' | 'dc'
 *   capacity_mw  : number — AC export capacity for BESS/Solar, IT MW for DC
 *   duration_h   : number — BESS duration (default 2h)
 *
 * Responsibilities:
 *   - mount Mapbox container + deck.gl MapboxOverlay
 *   - compute parametric asset layout via computeLayout()
 *   - render AssetInstancedLayer + ShadowPolygonLayer + site-boundary
 *     polygon, respecting twinStore.layerVisibility
 *   - wire camera to useCameraMode(viewMode)
 *   - surface clicks to twinStore.setSelected
 *
 * Sibling agents will wire this into AssessTab and the Design page as
 * an explicit mount option (the existing twins remain intact).
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import mapboxgl from 'mapbox-gl';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { PolygonLayer } from '@deck.gl/layers';
import * as turf from '@turf/turf';

import {
  useTwinStore,
  bindStoreToProject,
} from './stores/twinStore.js';
import { getAssetRegistry } from './assets/registry.js';
import { createAssetInstancedLayers } from './deck/AssetInstancedLayer.js';
import { createShadowPolygonLayer } from './deck/ShadowPolygonLayer.js';
import { useCameraMode } from './camera/useCameraMode.js';

const MAPBOX_TOKEN = import.meta.env?.VITE_MAPBOX_TOKEN || '';

// ------------------------------------------------------------------
// WKT helpers
// ------------------------------------------------------------------

function parsePolygonWkt(wkt) {
  if (!wkt || typeof wkt !== 'string') return null;
  const m = wkt.trim().match(/POLYGON\s*\(\s*\(([^)]+)\)\s*\)/i);
  if (!m) return null;
  const ring = m[1]
    .split(',')
    .map((pair) =>
      pair
        .trim()
        .split(/\s+/)
        .map(Number)
        .slice(0, 2),
    )
    .filter((p) => p.length === 2 && p.every(Number.isFinite));
  if (ring.length < 3) return null;
  // turf expects closed ring
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) ring.push(first);
  return ring;
}

// ------------------------------------------------------------------
// ENU metres -> lng/lat offset
// ------------------------------------------------------------------

function enuToLngLat(centreLng, centreLat, eastMetres, northMetres) {
  const mPerDegLng = 111320 * Math.cos((centreLat * Math.PI) / 180);
  const mPerDegLat = 110540;
  const lng = centreLng + eastMetres / (mPerDegLng || 1);
  const lat = centreLat + northMetres / mPerDegLat;
  return [lng, lat];
}

// ------------------------------------------------------------------
// Parametric layout
// ------------------------------------------------------------------

/**
 * computeLayout — deterministic seed rules for v1. Sibling agents will
 * replace with spatially aware packing using the actual buildable mask.
 *
 * @param {string} tech         'bess' | 'solar' | 'dc'
 * @param {number} capacityMw   AC export / IT MW
 * @param {number} durationH    BESS duration (h); defaults 2
 * @param {Array}  polygonRing  [[lng,lat], ...] closed ring
 * @returns {Array<{id, assetType, position:[lng,lat], rotation:number}>}
 */
export function computeLayout(tech, capacityMw, durationH = 2, polygonRing = null) {
  if (!Number.isFinite(capacityMw) || capacityMw <= 0) return [];
  const cap = Math.max(1, capacityMw);
  const dur = Math.max(0.5, Number(durationH) || 2);

  // Determine centroid
  let centroid = [-0.1276, 51.5074]; // London fallback
  if (polygonRing && polygonRing.length >= 3) {
    try {
      const poly = turf.polygon([polygonRing]);
      const c = turf.centroid(poly).geometry.coordinates;
      if (Array.isArray(c) && c.length === 2 && c.every(Number.isFinite)) {
        centroid = c;
      }
    } catch (_) {
      // keep fallback
    }
  }
  const [clng, clat] = centroid;

  const t = String(tech || '').toLowerCase();

  // ------------------------------------------------------------
  // BESS: Tesla Megapack 2XL — 3.9 MWh per unit, 1.9 MW power,
  // footprint 8.8 x 1.8 m, stacked in 8-wide rows with 8 m firebreaks
  // ------------------------------------------------------------
  if (t === 'bess') {
    const energyMwh = cap * dur;
    const unitEnergy = 3.9;
    const unitCount = Math.max(1, Math.ceil(energyMwh / unitEnergy));

    const ROW_WIDTH = 7; // 7 units per row (matches v1 seed spec: 4 rows × 7)
    const rows = Math.ceil(unitCount / ROW_WIDTH);

    const unitL = 8.8; // along row (east)
    const unitW = 1.8; // across row (north)
    const rowSpacing = unitW + 8.0; // 8 m firebreak between rows
    const colSpacing = unitL + 1.2; // 1.2 m between containers in row

    // centre the block around centroid
    const blockWidth = ROW_WIDTH * colSpacing;
    const blockDepth = rows * rowSpacing;
    const x0 = -blockWidth / 2 + colSpacing / 2;
    const y0 = -blockDepth / 2 + rowSpacing / 2;

    const assets = [];
    let placed = 0;
    for (let r = 0; r < rows && placed < unitCount; r += 1) {
      const rowUnits = Math.min(ROW_WIDTH, unitCount - placed);
      for (let c = 0; c < rowUnits; c += 1) {
        const ex = x0 + c * colSpacing;
        const ny = y0 + r * rowSpacing;
        assets.push({
          id: `bess-mp-${r}-${c}`,
          assetType: 'bess.tesla_megapack_2xl',
          position: enuToLngLat(clng, clat, ex, ny),
          rotation: 0,
        });
        placed += 1;
      }
    }

    // one PCS skid and one aux TX at the north edge
    const pcsY = -blockDepth / 2 - 8;
    assets.push({
      id: 'bess-pcs-01',
      assetType: 'bess.pcs_skid',
      position: enuToLngLat(clng, clat, -5, pcsY),
      rotation: 0,
    });
    assets.push({
      id: 'bess-auxtx-01',
      assetType: 'bess.aux_tx',
      position: enuToLngLat(clng, clat, 5, pcsY),
      rotation: 0,
    });
    return assets;
  }

  // ------------------------------------------------------------
  // SOLAR: grid of PV tables at 4 acres / MWp ≈ 16_186 m²/MWp
  // Each PV table = 12 x 4 m, 23 kWp. Row spacing 6 m.
  // ------------------------------------------------------------
  if (t === 'solar') {
    const kwpTotal = cap * 1000;
    const tableKwp = 23;
    const tableCount = Math.max(1, Math.ceil(kwpTotal / tableKwp));

    const tableL = 12; // east
    const tableW = 4; // north
    const rowPitch = tableW + 6; // 6 m inter-row
    const colPitch = tableL + 2; // 2 m gap in row

    const cols = Math.max(1, Math.ceil(Math.sqrt(tableCount * 1.6)));
    const rows = Math.ceil(tableCount / cols);

    const blockWidth = cols * colPitch;
    const blockDepth = rows * rowPitch;
    const x0 = -blockWidth / 2 + colPitch / 2;
    const y0 = -blockDepth / 2 + rowPitch / 2;

    const assets = [];
    let placed = 0;
    for (let r = 0; r < rows && placed < tableCount; r += 1) {
      const rowCount = Math.min(cols, tableCount - placed);
      for (let c = 0; c < rowCount; c += 1) {
        const ex = x0 + c * colPitch;
        const ny = y0 + r * rowPitch;
        assets.push({
          id: `pv-tbl-${r}-${c}`,
          assetType: 'solar.pv_table_4h',
          position: enuToLngLat(clng, clat, ex, ny),
          rotation: 0,
        });
        placed += 1;
      }
    }

    // central inverters: one per ~3 MVA → one per 3 MW AC
    const invCount = Math.max(1, Math.ceil(cap / 3));
    for (let i = 0; i < invCount; i += 1) {
      assets.push({
        id: `pv-inv-${i}`,
        assetType: 'solar.central_inverter_3mva',
        position: enuToLngLat(
          clng,
          clat,
          -blockWidth / 2 - 8,
          y0 + i * rowPitch * 2,
        ),
        rotation: 0,
      });
    }
    // pad transformers: one per 3 MVA
    for (let i = 0; i < invCount; i += 1) {
      assets.push({
        id: `pv-tx-${i}`,
        assetType: 'solar.pad_tx',
        position: enuToLngLat(
          clng,
          clat,
          -blockWidth / 2 - 14,
          y0 + i * rowPitch * 2,
        ),
        rotation: 0,
      });
    }
    return assets;
  }

  // ------------------------------------------------------------
  // DC: single IT-hall shell 100 x 60 x 24 m plus gensets, CRACs, UPS
  // ------------------------------------------------------------
  if (t === 'dc' || t === 'datacentre' || t === 'data_centre') {
    const assets = [];
    // one hall per ~40 MW IT
    const hallCount = Math.max(1, Math.ceil(cap / 40));
    for (let i = 0; i < hallCount; i += 1) {
      assets.push({
        id: `dc-hall-${i}`,
        assetType: 'dc.it_hall_shell',
        position: enuToLngLat(clng, clat, i * 110, 0),
        rotation: 0,
      });
    }
    // gensets: one 3 MW per ~3.5 MW IT, line them up north of hall
    const gensetCount = Math.max(1, Math.ceil(cap / 3.5));
    for (let i = 0; i < gensetCount; i += 1) {
      assets.push({
        id: `dc-gs-${i}`,
        assetType: 'dc.genset_3mw',
        position: enuToLngLat(clng, clat, -40 + i * 15, 50),
        rotation: 0,
      });
    }
    // CRACs: 80 kW each; 1 per ~1 MW IT × PUE overhead
    const cracCount = Math.max(4, Math.ceil((cap * 1000) / 80));
    const cracCols = Math.min(20, Math.ceil(Math.sqrt(cracCount)));
    const cracRows = Math.ceil(cracCount / cracCols);
    for (let r = 0; r < cracRows; r += 1) {
      const rowN = Math.min(cracCols, cracCount - r * cracCols);
      for (let c = 0; c < rowN; c += 1) {
        assets.push({
          id: `dc-crac-${r}-${c}`,
          assetType: 'dc.crac',
          position: enuToLngLat(clng, clat, -45 + c * 2.5, -35 - r * 3.5),
          rotation: 0,
        });
      }
    }
    // UPS rooms: 1 per ~2.5 MW IT
    const upsCount = Math.max(1, Math.ceil(cap / 2.5));
    for (let i = 0; i < upsCount; i += 1) {
      assets.push({
        id: `dc-ups-${i}`,
        assetType: 'dc.ups_room',
        position: enuToLngLat(clng, clat, 55, -30 + i * 12),
        rotation: 0,
      });
    }
    return assets;
  }

  return [];
}

// ------------------------------------------------------------------
// TwinRoot component
// ------------------------------------------------------------------

export default function TwinRoot({
  projectId = 'default',
  polygon_wkt = null,
  tech = 'bess',
  capacity_mw = 50,
  duration_h = 2,
  mapStyle = 'mapbox://styles/mapbox/dark-v11',
  style = null,
  onAssetSelected = null,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);

  const layerVisibility = useTwinStore((s) => s.layerVisibility);
  const selectedAssetId = useTwinStore((s) => s.selectedAssetId);
  const setSelected = useTwinStore((s) => s.setSelected);
  const sunDate = useTwinStore((s) => s.sunDate);

  // bind persistence namespace once on mount
  useEffect(() => {
    bindStoreToProject(projectId);
  }, [projectId]);

  // parse polygon + compute centroid
  const polygonRing = useMemo(() => parsePolygonWkt(polygon_wkt), [polygon_wkt]);
  const centroid = useMemo(() => {
    if (polygonRing && polygonRing.length >= 3) {
      try {
        const c = turf.centroid(turf.polygon([polygonRing])).geometry.coordinates;
        if (Array.isArray(c) && c.length === 2 && c.every(Number.isFinite)) {
          return c;
        }
      } catch (_) {
        /* fallthrough */
      }
    }
    return [-0.1276, 51.5074];
  }, [polygonRing]);

  // parametric layout
  const assets = useMemo(
    () => computeLayout(tech, capacity_mw, duration_h, polygonRing),
    [tech, capacity_mw, duration_h, polygonRing],
  );

  const registry = useMemo(() => getAssetRegistry(), []);

  // ---- init mapbox ----
  useEffect(() => {
    if (!containerRef.current) return undefined;
    if (!MAPBOX_TOKEN) {
      console.warn('[TwinRoot] missing VITE_MAPBOX_TOKEN — map will not render');
      return undefined;
    }
    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: mapStyle,
      center: centroid,
      zoom: 16,
      pitch: 45,
      bearing: -25,
      antialias: true,
    });
    mapRef.current = map;

    map.on('load', () => {
      const overlay = new MapboxOverlay({ layers: [] });
      map.addControl(overlay);
      overlayRef.current = overlay;
      setMapReady(true);
    });

    return () => {
      setMapReady(false);
      overlayRef.current = null;
      if (mapRef.current) {
        try {
          mapRef.current.remove();
        } catch (_) {
          /* ignore */
        }
        mapRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapStyle]);

  // camera mode follows store
  useCameraMode(mapRef, { center: centroid, enabled: mapReady });

  // ---- build + push deck.gl layers ----
  useEffect(() => {
    if (!mapReady || !overlayRef.current) return;

    const layers = [];

    // site boundary polygon
    if (layerVisibility.site && polygonRing && polygonRing.length >= 3) {
      layers.push(
        new PolygonLayer({
          id: 'twin-site-boundary',
          data: [{ polygon: polygonRing }],
          getPolygon: (d) => d.polygon,
          stroked: true,
          filled: true,
          getFillColor: [255, 195, 85, 28],
          getLineColor: [255, 195, 85, 220],
          lineWidthMinPixels: 2,
          pickable: false,
        }),
      );
    }

    // assets
    if (layerVisibility.assets) {
      const assetLayers = createAssetInstancedLayers({
        assets,
        registry,
        visible: true,
        pickable: true,
        selectedAssetId,
        onClick: (payload) => {
          setSelected(payload.id || null);
          if (typeof onAssetSelected === 'function') onAssetSelected(payload);
        },
      });
      layers.push(...assetLayers);
    }

    // shadows (tied to environment toggle — available even when off by
    // default via direct store toggle; render only when environment ON)
    if (layerVisibility.environment) {
      const shadowLayer = createShadowPolygonLayer({
        assets,
        sunDate,
        centroid,
        opacity: 0.4,
      });
      if (shadowLayer) layers.push(shadowLayer);
    }

    overlayRef.current.setProps({ layers });
  }, [
    mapReady,
    assets,
    registry,
    layerVisibility,
    selectedAssetId,
    polygonRing,
    sunDate,
    centroid,
    onAssetSelected,
    setSelected,
  ]);

  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: 480,
        background: '#0b0c0f',
        ...(style || {}),
      }}
    >
      <div
        ref={containerRef}
        style={{ position: 'absolute', inset: 0 }}
        data-twin-root={projectId}
      />
      {!MAPBOX_TOKEN && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#b3b6bd',
            fontFamily: 'system-ui, sans-serif',
            padding: 24,
            textAlign: 'center',
          }}
        >
          VITE_MAPBOX_TOKEN missing — TwinRoot cannot initialise the
          Mapbox canvas.
        </div>
      )}
    </div>
  );
}

export { TwinRoot };

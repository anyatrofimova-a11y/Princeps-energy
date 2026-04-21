/**
 * Princeps 3D Twin v1 — ShadowPolygonLayer
 * ----------------------------------------------------------------------
 * Cheap ground-plane shadow approximation — no CSM, no shadow maps.
 * For each asset we compute the sun's azimuth/altitude for the store's
 * sunDate at the site centroid, then project the asset's footprint in
 * the anti-sun direction by `h / tan(altitude)`. The resulting polygon
 * is fed to a PolygonLayer at 40% black opacity.
 *
 * Heuristic simplifications (fine for v1 pitch visualisation):
 *   - treats each asset footprint as axis-aligned rectangle (l x w),
 *     ignoring rotation for the shadow cast (rotation <20° barely
 *     perceptible at typical pitch angles)
 *   - if sun altitude < 5°, shadow is capped at 20× height to avoid
 *     absurd streaks at sunrise/sunset
 *   - shadows drawn as a quadrilateral extending from the footprint
 *     edge opposite the sun
 *
 * Sibling agents in v2 will swap this for three.js PCF shadow maps in
 * a custom R3F layer — this file stays as the fast fallback.
 */

import { PolygonLayer } from '@deck.gl/layers';
import SunCalc from 'suncalc';

import { getAssetDef } from '../assets/registry.js';

// ------------------------------------------------------------------
// Metre <-> degree conversion (WGS-84 small-angle, local)
// ------------------------------------------------------------------

function metresToLngDegrees(metres, latDeg) {
  const mPerDeg = 111320 * Math.cos((latDeg * Math.PI) / 180);
  if (!Number.isFinite(mPerDeg) || mPerDeg === 0) return 0;
  return metres / mPerDeg;
}

function metresToLatDegrees(metres) {
  return metres / 110540;
}

// ------------------------------------------------------------------
// Shadow geometry for a single asset
// ------------------------------------------------------------------

function buildAssetShadowPolygon(asset, sunAzimuthRad, sunAltitudeRad) {
  const def = getAssetDef(asset.assetType) || getAssetDef(asset.type);
  if (!def) return null;
  const { l, w, h } = def.dims;
  if (!Number.isFinite(h) || h <= 0) return null;

  const [lng, lat] = asset.position || [0, 0];
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;

  // skip near-dawn/dusk — shadow would exceed sane bounds
  const minAlt = (5 * Math.PI) / 180;
  if (sunAltitudeRad <= 0) return null;
  const effectiveAlt = Math.max(sunAltitudeRad, minAlt);

  // shadow length in metres; cap at 20*h
  const rawLen = h / Math.tan(effectiveAlt);
  const shadowLen = Math.min(rawLen, 20 * h);

  // sun azimuth in SunCalc is measured south-clockwise; convert to
  // compass bearing (north = 0, east = 90) for clarity
  const compassAz = sunAzimuthRad + Math.PI; // SunCalc: 0 at south
  // shadow points away from the sun
  const shadowBearing = compassAz + Math.PI;

  // bearing -> (dx east, dy north) unit vector
  const ex = Math.sin(shadowBearing);
  const ny = Math.cos(shadowBearing);

  // half footprint size in metres — assume axis-aligned rectangle
  const halfL = l / 2;
  const halfW = w / 2;

  // footprint corners in metres (local ENU)
  const footprint = [
    [-halfL, -halfW],
    [halfL, -halfW],
    [halfL, halfW],
    [-halfL, halfW],
  ];

  // extended shadow: take the two "trailing" corners (projected along
  // shadow direction by +shadowLen) and the two original "leading"
  // corners to form a quadrilateral.
  const tx = ex * shadowLen;
  const ty = ny * shadowLen;

  const corners = [
    [-halfL, -halfW],
    [halfL, -halfW],
    [halfL + tx, -halfW + ty],
    [-halfL + tx, halfW + ty],
    [halfL + tx, halfW + ty],
    [-halfL, halfW],
  ];
  // simpler convex-ish hull: footprint projected forwards as a prism
  // build: 4 footprint corners + 4 shifted corners, then convex hull in
  // local ENU. For v1 "good enough", approximate as a hexagon:
  const hex = [
    [-halfL, -halfW],
    [halfL, -halfW],
    [halfL + tx, -halfW + ty],
    [halfL + tx, halfW + ty],
    [-halfL + tx, halfW + ty],
    [-halfL, halfW],
  ];

  // convert each ENU metre-offset to lng/lat
  const ring = hex.map(([mx, my]) => {
    const dLng = metresToLngDegrees(mx, lat);
    const dLat = metresToLatDegrees(my);
    return [lng + dLng, lat + dLat];
  });
  // close ring
  ring.push(ring[0]);

  return {
    id: asset.id,
    polygon: ring,
  };
}

// ------------------------------------------------------------------
// Public factory
// ------------------------------------------------------------------

/**
 * @param {Object} opts
 * @param {Array}  opts.assets      asset instances
 * @param {Date}   opts.sunDate     sun date (from twinStore)
 * @param {Array}  [opts.centroid]  [lng, lat] centroid for sun calc; if
 *                                  omitted we use the mean of asset
 *                                  positions.
 * @param {boolean}[opts.visible=true]
 * @param {string} [opts.id='twin-shadows']
 * @param {number} [opts.opacity=0.4]
 * @returns {PolygonLayer|null}
 */
export function createShadowPolygonLayer(opts) {
  const {
    assets = [],
    sunDate,
    centroid,
    visible = true,
    id = 'twin-shadows',
    opacity = 0.4,
  } = opts || {};

  if (!visible || !sunDate || !Array.isArray(assets) || assets.length === 0) {
    return null;
  }

  // centroid for sun position
  let [clng, clat] = centroid || [];
  if (!Number.isFinite(clng) || !Number.isFinite(clat)) {
    let sx = 0;
    let sy = 0;
    let n = 0;
    for (const a of assets) {
      if (!a.position || a.position.length < 2) continue;
      sx += a.position[0];
      sy += a.position[1];
      n += 1;
    }
    if (n === 0) return null;
    clng = sx / n;
    clat = sy / n;
  }

  const sun = SunCalc.getPosition(sunDate, clat, clng);
  if (!sun || sun.altitude <= 0) return null;

  const polygons = [];
  for (const a of assets) {
    const poly = buildAssetShadowPolygon(a, sun.azimuth, sun.altitude);
    if (poly) polygons.push(poly);
  }
  if (polygons.length === 0) return null;

  return new PolygonLayer({
    id,
    data: polygons,
    pickable: false,
    stroked: false,
    filled: true,
    getPolygon: (d) => d.polygon,
    getFillColor: [0, 0, 0, Math.round(255 * Math.max(0, Math.min(1, opacity)))],
    parameters: {
      // render before assets so shadows sit on ground
      depthTest: true,
    },
  });
}

export default createShadowPolygonLayer;

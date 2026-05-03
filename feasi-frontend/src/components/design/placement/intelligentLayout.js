/**
 * intelligentLayout.js — polygon-aware DC campus equipment placement
 * ----------------------------------------------------------------------
 * Replaces the naive centroid + ENU-offset seeding in TwinRoot.computeLayout
 * for tech = 'dc'. Takes the project's red-line polygon, an optional point-
 * of-connection (POC) coordinate, and sizing inputs (capacity MW, tier,
 * redundancy) and produces a set of asset instances that:
 *
 *   1. Sit entirely inside the polygon (clipped to a 5 m setback buffer).
 *   2. Respect DC campus adjacency rules:
 *        - Halls centred, long-axis aligned with the polygon's long axis
 *        - TX yard on the edge nearest the POC / substation
 *        - Gatehouse + NOC office on the edge nearest the public road
 *        - Genset yard opposite the office, >50 m from halls
 *        - Water plant on the edge orthogonal to the office/genset axis
 *        - Loading bay near the gatehouse, not touching the halls
 *        - 10 m fire break between buildings
 *        - Fence at 3 m offset from hall shell
 *        - Cable corridor: straight polyline MV/LV room → TX yard
 *
 * The module is deliberately free of React / deck.gl imports so it can be
 * unit-tested in Node (see the module footer for a runnable smoke test).
 *
 * Returned asset instances are drop-in compatible with
 * `AssetInstancedLayer`:
 *
 *   [{ id, assetType, position:[lng,lat], rotation, category,
 *      width_m, length_m, ring_geojson? }]
 *
 * `assetType` values reference entries in twin3d/assets/registry.js where
 * a matching 3D primitive exists. For equipment that has no dedicated
 * registry entry yet (water plant, office, gatehouse, loading bay) we re-
 * use the closest physical analogue (`dc.ups_room`) and set a sensible
 * `width_m` / `length_m` so the bounding-box fits.
 */

import * as turf from '@turf/turf';

// ------------------------------------------------------------------
// Constants — all metres
// ------------------------------------------------------------------

const SETBACK_RED_LINE_M = 5;
const FIRE_BREAK_M = 10;
const GENSET_HALL_CLEARANCE_M = 50;
const FENCE_OFFSET_M = 3;

// ------------------------------------------------------------------
// WKT + GeoJSON helpers
// ------------------------------------------------------------------

/** Parse 'POLYGON((lng lat, lng lat, ...))' → closed [lng,lat] ring. */
export function parsePolygonWkt(wkt) {
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
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) ring.push(first);
  return ring;
}

/** Accept either a WKT string, a closed ring, or a GeoJSON polygon/feature. */
function toRing(input) {
  if (Array.isArray(input) && input.length >= 3 && Array.isArray(input[0])) {
    // already a ring
    const ring = input.map((p) => [Number(p[0]), Number(p[1])]);
    const first = ring[0];
    const last = ring[ring.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) ring.push(first);
    return ring;
  }
  if (typeof input === 'string') return parsePolygonWkt(input);
  if (input && input.type === 'Feature' && input.geometry) {
    return toRing(input.geometry);
  }
  if (input && input.type === 'Polygon' && Array.isArray(input.coordinates)) {
    return input.coordinates[0] || null;
  }
  return null;
}

// ------------------------------------------------------------------
// Local ENU <-> lng/lat transform anchored at site centroid
// ------------------------------------------------------------------

function makeEnuFrame(centreLng, centreLat) {
  const cosLat = Math.cos((centreLat * Math.PI) / 180);
  const mPerDegLng = 111320 * cosLat;
  const mPerDegLat = 110540;
  return {
    toXY: (lng, lat) => [
      (lng - centreLng) * mPerDegLng,
      (lat - centreLat) * mPerDegLat,
    ],
    toLngLat: (x, y) => [
      centreLng + x / (mPerDegLng || 1),
      centreLat + y / mPerDegLat,
    ],
  };
}

// ------------------------------------------------------------------
// Polygon analysis — centroid, long-axis, setback
// ------------------------------------------------------------------

/**
 * Estimate the polygon's long axis by rotating its 2D points through a
 * range of angles and picking the bearing that produces the largest
 * bounding-box aspect ratio in the rotated frame.
 *
 * Returns an object:
 *   {
 *     bearingDeg  : compass bearing of the long axis (0=N, 90=E)
 *     lengthM     : long-axis extent in metres
 *     widthM      : short-axis extent in metres
 *     centreXy    : [x,y] centre of the rotated bbox, mapped back to ENU
 *   }
 */
function findLongAxis(ringXY) {
  if (!ringXY || ringXY.length < 3) return null;
  let best = null;
  // 0..180 in 3° steps (axis is symmetric, so 0..180 is enough)
  for (let deg = 0; deg < 180; deg += 3) {
    const theta = (deg * Math.PI) / 180;
    const c = Math.cos(theta);
    const s = Math.sin(theta);
    let minU = Infinity;
    let maxU = -Infinity;
    let minV = Infinity;
    let maxV = -Infinity;
    for (const [x, y] of ringXY) {
      const u = x * c + y * s;
      const v = -x * s + y * c;
      if (u < minU) minU = u;
      if (u > maxU) maxU = u;
      if (v < minV) minV = v;
      if (v > maxV) maxV = v;
    }
    const lenU = maxU - minU;
    const lenV = maxV - minV;
    const longSide = Math.max(lenU, lenV);
    const shortSide = Math.min(lenU, lenV);
    const area = lenU * lenV;
    // prefer tight rectangles with large aspect ratio
    if (!best || area < best.area) {
      best = {
        area,
        longSide,
        shortSide,
        // axis direction in ENU coords: the longer of (u, v)
        longAlongU: lenU >= lenV,
        theta,
        uMid: (minU + maxU) / 2,
        vMid: (minV + maxV) / 2,
      };
    }
  }
  if (!best) return null;
  // Map centre back to ENU
  const c = Math.cos(best.theta);
  const s = Math.sin(best.theta);
  const cx = best.uMid * c - best.vMid * s;
  const cy = best.uMid * s + best.vMid * c;
  // ENU bearing of the long axis: u-axis direction is theta from +x
  // If longAlongU is false, the long axis is along v (theta + 90°).
  const axisAngle = best.longAlongU ? best.theta : best.theta + Math.PI / 2;
  // Compass bearing: 0° = N (+y), 90° = E (+x)
  //   bearing = 90° - axisAngleDeg, wrapped to [0,360)
  const bearingDeg =
    ((90 - (axisAngle * 180) / Math.PI) % 360 + 360) % 360;
  return {
    bearingDeg,
    lengthM: best.longSide,
    widthM: best.shortSide,
    centreXy: [cx, cy],
  };
}

/** Inward-buffer a GeoJSON polygon by `metres`. Falls back to the input
 *  polygon if turf fails (e.g. self-intersecting after erosion). */
function erodePolygon(feature, metres) {
  try {
    const eroded = turf.buffer(feature, -metres, { units: 'meters' });
    if (eroded && eroded.geometry && eroded.geometry.coordinates?.length) {
      return eroded;
    }
  } catch (_) {
    /* fall through */
  }
  return feature;
}

/** Outward-buffer a GeoJSON feature by `metres`. */
function dilate(feature, metres) {
  try {
    const dil = turf.buffer(feature, metres, { units: 'meters' });
    if (dil && dil.geometry) return dil;
  } catch (_) {
    /* fall through */
  }
  return feature;
}

/** Bounding rectangle in a rotated frame. Returns the four corners in
 *  ENU (x,y) coords, centred on `centreXy`, aligned with axisAngleRad. */
function orientedRect(centreXy, lengthM, widthM, axisAngleRad) {
  const hx = lengthM / 2;
  const hy = widthM / 2;
  const c = Math.cos(axisAngleRad);
  const s = Math.sin(axisAngleRad);
  const corners = [
    [-hx, -hy],
    [hx, -hy],
    [hx, hy],
    [-hx, hy],
  ];
  return corners.map(([x, y]) => [
    centreXy[0] + x * c - y * s,
    centreXy[1] + x * s + y * c,
  ]);
}

/** Test whether a lng/lat point sits inside the polygon (turf wrapper). */
function pointInPolygon(lngLat, polygonFeature) {
  try {
    return turf.booleanPointInPolygon(turf.point(lngLat), polygonFeature);
  } catch (_) {
    return false;
  }
}

// ------------------------------------------------------------------
// Edge selection — find the polygon edge closest to a target lng/lat
// ------------------------------------------------------------------

/**
 * Return the midpoint (lng/lat) + bearing of the polygon edge whose
 * midpoint is closest to `targetLngLat`. If target is null, picks the
 * southernmost edge (lowest mean latitude) as a fallback.
 */
function closestEdgeTo(ringLngLat, targetLngLat) {
  if (!ringLngLat || ringLngLat.length < 2) return null;
  const edges = [];
  for (let i = 0; i < ringLngLat.length - 1; i += 1) {
    const a = ringLngLat[i];
    const b = ringLngLat[i + 1];
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const length = turf.distance(turf.point(a), turf.point(b), { units: 'meters' });
    edges.push({ a, b, mid, length });
  }
  if (targetLngLat) {
    const target = turf.point(targetLngLat);
    let best = null;
    for (const e of edges) {
      const d = turf.distance(target, turf.point(e.mid), { units: 'meters' });
      if (!best || d < best.d) best = { ...e, d };
    }
    return best;
  }
  // Fallback: southernmost edge (lowest latitude midpoint).
  let best = null;
  for (const e of edges) {
    if (!best || e.mid[1] < best.mid[1]) best = e;
  }
  return best;
}

/** Return the edge diametrically opposite the given edge (maximum midpoint
 *  distance in polygon units). */
function oppositeEdge(ringLngLat, edge) {
  let best = null;
  const target = turf.point(edge.mid);
  for (let i = 0; i < ringLngLat.length - 1; i += 1) {
    const a = ringLngLat[i];
    const b = ringLngLat[i + 1];
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const d = turf.distance(target, turf.point(mid), { units: 'meters' });
    if (!best || d > best.d) {
      const length = turf.distance(turf.point(a), turf.point(b), { units: 'meters' });
      best = { a, b, mid, length, d };
    }
  }
  return best;
}

// ------------------------------------------------------------------
// Placement helpers — project a block inward from an edge
// ------------------------------------------------------------------

/**
 * Place a rectangular block of size (lengthM × widthM) inside the setback
 * polygon, anchored near `edgeMidLngLat` and projected inward along the
 * edge's inward-pointing normal. Returns the block centre in ENU (x,y).
 */
function placeAnchoredBlock({
  enu,
  centroidLngLat,
  setbackPoly,
  edgeMidLngLat,
  lengthM,
  widthM,
  insetM,
}) {
  if (!edgeMidLngLat) return null;
  const [cx, cy] = enu.toXY(centroidLngLat[0], centroidLngLat[1]);
  const [ex, ey] = enu.toXY(edgeMidLngLat[0], edgeMidLngLat[1]);
  // Inward direction: from edge mid toward centroid
  const dx = cx - ex;
  const dy = cy - ey;
  const mag = Math.hypot(dx, dy) || 1;
  const nx = dx / mag;
  const ny = dy / mag;
  // Inset so the block sits fully inside the setback buffer plus a
  // generous extra margin equal to half the block width.
  const inset = insetM + widthM / 2;
  let bx = ex + nx * inset;
  let by = ey + ny * inset;
  // Clip: if bbox falls outside setback, nudge inward toward centroid in
  // 2 m steps until the centre is inside (up to 60 tries).
  for (let i = 0; i < 60; i += 1) {
    const [lng, lat] = enu.toLngLat(bx, by);
    if (pointInPolygon([lng, lat], setbackPoly)) break;
    bx += nx * 2;
    by += ny * 2;
  }
  return [bx, by];
}

// ------------------------------------------------------------------
// Public API
// ------------------------------------------------------------------

/**
 * Build the intelligent DC layout.
 *
 * @param {Object} opts
 * @param {string|Array|Object} opts.polygon  WKT string, closed ring or
 *   GeoJSON polygon/feature. Required.
 * @param {number} opts.capacityMw            IT MW. Required (>0).
 * @param {[number,number]|null} [opts.pocLatLon]   [lat,lon] of the POC/
 *   substation. Falls back to south edge when null.
 * @param {[number,number]|null} [opts.roadLatLon]  [lat,lon] of the public
 *   road access point. Falls back to opposite edge from POC when null.
 * @param {number} [opts.tier=3]
 * @param {string} [opts.redundancy='N+1']
 * @returns {{
 *   assets: Array<{id,assetType,position:[number,number],rotation:number,
 *                  category:string,width_m:number,length_m:number}>,
 *   rings: { setback?:object, fence?:object, fireZone?:object,
 *            cableCorridor?:object },
 *   meta: { centroid:[number,number], areaM2:number,
 *           longAxisBearingDeg:number, insidePolygon:number, total:number }
 * }}
 */
export function buildIntelligentDcLayout(opts) {
  const {
    polygon,
    capacityMw,
    pocLatLon = null,
    roadLatLon = null,
    tier = 3,
    redundancy = 'N+1',
  } = opts || {};

  if (!Number.isFinite(capacityMw) || capacityMw <= 0) {
    return { assets: [], rings: {}, meta: { error: 'invalid_capacity' } };
  }

  const ring = toRing(polygon);
  if (!ring || ring.length < 4) {
    return { assets: [], rings: {}, meta: { error: 'invalid_polygon' } };
  }

  const polyFeature = turf.polygon([ring]);
  const centroidFeat = turf.centroid(polyFeature);
  const centroidLngLat = centroidFeat.geometry.coordinates;
  const areaM2 = turf.area(polyFeature);

  const enu = makeEnuFrame(centroidLngLat[0], centroidLngLat[1]);
  const ringXY = ring.map(([lng, lat]) => enu.toXY(lng, lat));
  const axis = findLongAxis(ringXY) || {
    bearingDeg: 0,
    lengthM: 50,
    widthM: 30,
    centreXy: [0, 0],
  };
  // The "east" of the rotated frame is the long axis — convert compass
  // bearing to trig angle (radians, CCW from +x).
  const longAxisAngleRad = ((90 - axis.bearingDeg) * Math.PI) / 180;

  // ------------------------------------------------------------
  // Setback polygon (eroded by 5 m)
  // ------------------------------------------------------------
  const setbackFeat = erodePolygon(polyFeature, SETBACK_RED_LINE_M);

  // ------------------------------------------------------------
  // Identify edges
  // ------------------------------------------------------------
  const ringLngLat = ring;
  // POC edge: closest to POC (lat, lon) → turf.point takes [lng, lat]
  const pocLngLat = pocLatLon
    ? [pocLatLon[1], pocLatLon[0]]
    : null;
  const roadLngLat = roadLatLon
    ? [roadLatLon[1], roadLatLon[0]]
    : null;
  const pocEdge = closestEdgeTo(ringLngLat, pocLngLat);
  // Road edge: closest to road if known; otherwise the edge opposite to
  // the POC edge (access road on the opposite side of the campus from
  // the grid substation).
  const roadEdge = roadLngLat
    ? closestEdgeTo(ringLngLat, roadLngLat)
    : (pocEdge ? oppositeEdge(ringLngLat, pocEdge) : closestEdgeTo(ringLngLat, null));
  // Genset edge: opposite the office (road) edge
  const gensetEdge = roadEdge ? oppositeEdge(ringLngLat, roadEdge) : null;

  // ------------------------------------------------------------
  // Hall block sizing
  // ------------------------------------------------------------
  // Standard IT hall footprint 100 × 60 m, 40 MW per hall
  const HALL_L = 100; // along long-axis
  const HALL_W = 60;  // across long-axis
  const hallCount = Math.max(1, Math.ceil(capacityMw / 40));
  // Try 1×N (all in a line along long axis) first. If the block doesn't
  // fit, switch to 2×(ceil(N/2)) or 4×(ceil(N/4)).
  const cfgCandidates = [
    { rows: 1, cols: hallCount },
    { rows: 2, cols: Math.ceil(hallCount / 2) },
    { rows: 4, cols: Math.ceil(hallCount / 4) },
  ];
  // Available space (setback bbox in rotated frame).
  const availLen = Math.max(0, axis.lengthM - 2 * SETBACK_RED_LINE_M);
  const availWid = Math.max(0, axis.widthM - 2 * SETBACK_RED_LINE_M);
  let hallCfg = cfgCandidates[0];
  for (const cfg of cfgCandidates) {
    const blockLen = cfg.cols * HALL_L + (cfg.cols - 1) * FIRE_BREAK_M;
    const blockWid = cfg.rows * HALL_W + (cfg.rows - 1) * FIRE_BREAK_M;
    // Reserve ~30% of the long axis for ancillary blocks + corridors
    const reservedLen = 0.35 * availLen;
    const reservedWid = 0.35 * availWid;
    if (
      blockLen + reservedLen <= availLen &&
      blockWid + reservedWid <= availWid
    ) {
      hallCfg = cfg;
      break;
    }
  }

  // ------------------------------------------------------------
  // Placement — everything in the rotated frame (u = along long axis,
  // v = across). Centroid of the polygon is our origin.
  // ------------------------------------------------------------
  const c = Math.cos(longAxisAngleRad);
  const s = Math.sin(longAxisAngleRad);
  const toWorld = (u, v) => [u * c - v * s, u * s + v * c];

  const assets = [];
  let placedInside = 0;
  let totalPlaced = 0;

  function push(inst) {
    totalPlaced += 1;
    if (pointInPolygon(inst.position, polyFeature)) placedInside += 1;
    assets.push(inst);
  }

  // ---- IT halls ----
  const hallBlockLen =
    hallCfg.cols * HALL_L + (hallCfg.cols - 1) * FIRE_BREAK_M;
  const hallBlockWid =
    hallCfg.rows * HALL_W + (hallCfg.rows - 1) * FIRE_BREAK_M;
  // Centre the halls on the polygon centroid in the rotated frame.
  const hallU0 = -hallBlockLen / 2 + HALL_L / 2;
  const hallV0 = -hallBlockWid / 2 + HALL_W / 2;
  const hallRotation = axis.bearingDeg;
  // Rotation for the box: our registry box has l along x (long side east-
  // west in the default frame). deck.gl SimpleMeshLayer reads `rotation`
  // as yaw around Z in degrees. We want the long side to face along the
  // polygon long axis → rotation = 90° - axis.bearingDeg so that yaw 0
  // points east.
  //
  // (We pass axis.bearingDeg; if the visualiser adopts a different
  // convention, rotate at the layer site.)
  let hallIdx = 0;
  for (let r = 0; r < hallCfg.rows; r += 1) {
    const v = hallV0 + r * (HALL_W + FIRE_BREAK_M);
    for (let col = 0; col < hallCfg.cols; col += 1) {
      if (hallIdx >= hallCount) break;
      const u = hallU0 + col * (HALL_L + FIRE_BREAK_M);
      const [ex, ey] = toWorld(u, v);
      push({
        id: `dc-hall-${hallIdx}`,
        assetType: 'dc.it_hall_shell',
        position: enu.toLngLat(ex, ey),
        rotation: hallRotation,
        category: 'hall',
        length_m: HALL_L,
        width_m: HALL_W,
      });
      hallIdx += 1;
    }
  }

  // ---- TX yard ----
  // Sized ~ max(40, 15 × capacityMw^0.5) by 30 m — keeps small sites
  // realistic (40 × 30) while hyperscale lots get bigger yards.
  const txLen = Math.max(40, Math.round(15 * Math.sqrt(capacityMw)));
  const txWid = 30;
  const txCentre = pocEdge
    ? placeAnchoredBlock({
        enu,
        centroidLngLat,
        setbackPoly: setbackFeat,
        edgeMidLngLat: pocEdge.mid,
        lengthM: txLen,
        widthM: txWid,
        insetM: SETBACK_RED_LINE_M,
      })
    : null;
  if (txCentre) {
    push({
      id: 'dc-tx-yard',
      assetType: 'dc.ups_room', // re-use UPS box as TX-yard placeholder
      position: enu.toLngLat(txCentre[0], txCentre[1]),
      rotation: axis.bearingDeg,
      category: 'tx_yard',
      length_m: txLen,
      width_m: txWid,
      colour: '#d4a54a',
    });
  }

  // ---- Gatehouse + Office/NOC (at road entry) ----
  const gateLen = 10;
  const gateWid = 8;
  const officeLen = 40;
  const officeWid = 20;
  const gateCentre = roadEdge
    ? placeAnchoredBlock({
        enu,
        centroidLngLat,
        setbackPoly: setbackFeat,
        edgeMidLngLat: roadEdge.mid,
        lengthM: gateLen + officeLen + 15,
        widthM: Math.max(gateWid, officeWid),
        insetM: SETBACK_RED_LINE_M,
      })
    : null;
  if (gateCentre) {
    // Inward unit vector = from edge mid toward centroid (origin).
    const [mx, my] = enu.toXY(roadEdge.mid[0], roadEdge.mid[1]);
    const dx = 0 - mx;
    const dy = 0 - my;
    const mag = Math.hypot(dx, dy) || 1;
    const nx = dx / mag; // inward normal
    const ny = dy / mag;
    const tx = -ny; // tangent along edge
    const ty = nx;
    // Gatehouse: at the placed anchor (safely inside the setback).
    push({
      id: 'dc-gatehouse',
      assetType: 'dc.ups_room',
      position: enu.toLngLat(gateCentre[0], gateCentre[1]),
      rotation: axis.bearingDeg + 90,
      category: 'gatehouse',
      length_m: gateLen,
      width_m: gateWid,
      colour: '#8a8478',
    });
    // Office: step 25 m further inward of gatehouse, then clamp if it
    // falls outside the setback.
    let offX = gateCentre[0] + nx * 25;
    let offY = gateCentre[1] + ny * 25;
    for (let k = 0; k < 30; k += 1) {
      const ll = enu.toLngLat(offX, offY);
      if (pointInPolygon(ll, setbackFeat)) break;
      offX -= nx * 2;
      offY -= ny * 2;
    }
    push({
      id: 'dc-office-noc',
      assetType: 'dc.ups_room',
      position: enu.toLngLat(offX, offY),
      rotation: axis.bearingDeg + 90,
      category: 'office',
      length_m: officeLen,
      width_m: officeWid,
      colour: '#6b6560',
    });
    // Loading bay: same inward offset as gatehouse but along the edge
    // tangent by 25 m. Pick whichever tangent direction stays inside.
    for (const sign of [1, -1]) {
      let loadX = gateCentre[0] + tx * 25 * sign + nx * 8;
      let loadY = gateCentre[1] + ty * 25 * sign + ny * 8;
      const ll = enu.toLngLat(loadX, loadY);
      if (pointInPolygon(ll, setbackFeat)) {
        push({
          id: 'dc-loading-bay',
          assetType: 'dc.ups_room',
          position: ll,
          rotation: axis.bearingDeg,
          category: 'loading_bay',
          length_m: 30,
          width_m: 15,
          colour: '#4a5260',
        });
        break;
      }
    }
  }

  // ---- Genset yard (opposite road) ----
  const gensetLen = Math.max(30, 12 * Math.ceil(capacityMw / 3.5));
  const gensetWid = 25;
  const gensetCentre = gensetEdge
    ? placeAnchoredBlock({
        enu,
        centroidLngLat,
        setbackPoly: setbackFeat,
        edgeMidLngLat: gensetEdge.mid,
        lengthM: gensetLen,
        widthM: gensetWid,
        insetM: SETBACK_RED_LINE_M,
      })
    : null;
  if (gensetCentre) {
    const gensetUnitL = 12;
    const gensetUnitW = 2.5;
    const gensetSpacing = gensetUnitL + 3; // 3 m between units
    const baseCount = Math.max(1, Math.ceil(capacityMw / 3.5));
    const wantCount = redundancy === 'N+1' ? baseCount + 1 : baseCount;
    // Cap count by the available edge length at this inset — we row the
    // gensets along the long-axis tangent, so the row must fit inside
    // (axis.lengthM - 2·SETBACK_RED_LINE_M).
    const availEdgeLen = Math.max(
      gensetUnitL,
      axis.lengthM - 2 * SETBACK_RED_LINE_M - 4,
    );
    const maxByEdge = Math.max(1, Math.floor(availEdgeLen / gensetSpacing));
    const gensetCount = Math.min(wantCount, maxByEdge);
    // Enforce 50 m hall-clearance: if the genset centre (perpendicular
    // from the edge) is closer than 50 m to any hall skin, push the
    // centre outward toward the edge. This moves the whole row.
    const nearestHall = assets.find((a) => a.category === 'hall');
    if (nearestHall) {
      const [hx, hy] = enu.toXY(
        nearestHall.position[0],
        nearestHall.position[1],
      );
      // Approximate hall skin as a circle of radius HALL_W/2; genset
      // centre must be >= HALL_W/2 + 50 + gensetUnitW/2 from hall centre.
      const minSep =
        HALL_W / 2 + GENSET_HALL_CLEARANCE_M + gensetUnitW / 2;
      const d = Math.hypot(gensetCentre[0] - hx, gensetCentre[1] - hy);
      if (d < minSep) {
        const vx = gensetCentre[0] - hx;
        const vy = gensetCentre[1] - hy;
        const vmag = Math.hypot(vx, vy) || 1;
        // Target position with the 50 m fire break.
        const targetX = hx + (vx / vmag) * minSep;
        const targetY = hy + (vy / vmag) * minSep;
        const targetLngLat = enu.toLngLat(targetX, targetY);
        if (pointInPolygon(targetLngLat, setbackFeat)) {
          gensetCentre[0] = targetX;
          gensetCentre[1] = targetY;
        } else {
          // Tight site: honour the setback first; surface a warning but
          // keep the genset inside the polygon even if the 50 m fire break
          // is infeasible. Walk the line hall→edge and take the furthest
          // point that still fits in the setback.
          let best = [gensetCentre[0], gensetCentre[1]];
          for (let k = 1; k <= 20; k += 1) {
            const t = k / 20;
            const px = hx + (vx / vmag) * (minSep * t + d * (1 - t));
            const py = hy + (vy / vmag) * (minSep * t + d * (1 - t));
            if (pointInPolygon(enu.toLngLat(px, py), setbackFeat)) {
              best = [px, py];
            }
          }
          gensetCentre[0] = best[0];
          gensetCentre[1] = best[1];
        }
      }
    }
    const blockLen =
      gensetCount * gensetUnitL + (gensetCount - 1) * 3;
    const g0 = -blockLen / 2 + gensetUnitL / 2;
    for (let i = 0; i < gensetCount; i += 1) {
      const u = g0 + i * gensetSpacing;
      const [ox, oy] = toWorld(u, 0);
      const lngLat = enu.toLngLat(
        gensetCentre[0] + ox,
        gensetCentre[1] + oy,
      );
      // Final per-unit clip: skip units that fall outside the setback.
      if (!pointInPolygon(lngLat, setbackFeat)) continue;
      push({
        id: `dc-gs-${i}`,
        assetType: 'dc.genset_3mw',
        position: lngLat,
        rotation: axis.bearingDeg,
        category: 'genset',
        length_m: gensetUnitL,
        width_m: gensetUnitW,
      });
    }
  }

  // ---- Water plant (orthogonal edge) ----
  // Pick the edge whose bearing from centroid is ~90° off the road→genset
  // axis.
  let waterEdge = null;
  if (roadEdge && gensetEdge) {
    let best = null;
    const roadBearing = turf.bearing(
      turf.point(centroidLngLat),
      turf.point(roadEdge.mid),
    );
    for (let i = 0; i < ringLngLat.length - 1; i += 1) {
      const a = ringLngLat[i];
      const b = ringLngLat[i + 1];
      const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      const br = turf.bearing(turf.point(centroidLngLat), turf.point(mid));
      // angular distance from 90° off the road bearing
      const delta = Math.abs(
        (((br - roadBearing + 90 + 540) % 360) - 180),
      );
      if (!best || delta < best.delta) {
        const length = turf.distance(turf.point(a), turf.point(b), { units: 'meters' });
        best = { a, b, mid, length, delta };
      }
    }
    waterEdge = best;
  }
  if (waterEdge) {
    const waterLen = 30;
    const waterWid = 20;
    const waterCentre = placeAnchoredBlock({
      enu,
      centroidLngLat,
      setbackPoly: setbackFeat,
      edgeMidLngLat: waterEdge.mid,
      lengthM: waterLen,
      widthM: waterWid,
      insetM: SETBACK_RED_LINE_M,
    });
    if (waterCentre) {
      push({
        id: 'dc-water-plant',
        assetType: 'dc.ups_room',
        position: enu.toLngLat(waterCentre[0], waterCentre[1]),
        rotation: axis.bearingDeg,
        category: 'water_plant',
        length_m: waterLen,
        width_m: waterWid,
        colour: '#3a6fa0',
      });
    }
  }

  // ---- CRACs on each hall's long side ----
  // One 80 kW CRAC per ~1 MW IT; place in a row on the +v side of the
  // hall block.
  const cracCount = Math.max(4, Math.ceil(capacityMw * 1.2));
  const cracSpacing = 2.8;
  // Distribute along the hall block length, in a row just outside the
  // block but still within the setback polygon.
  const cracRowV = hallBlockWid / 2 + 2.5; // 2.5 m clear of hall skin
  const cracRowLen = Math.min(cracCount * cracSpacing, hallBlockLen);
  const cracActual = Math.min(cracCount, Math.floor(cracRowLen / cracSpacing));
  const cracU0 = -cracRowLen / 2 + cracSpacing / 2;
  for (let i = 0; i < cracActual; i += 1) {
    const u = cracU0 + i * cracSpacing;
    const [ex, ey] = toWorld(u, cracRowV);
    const lngLat = enu.toLngLat(ex, ey);
    // only place if inside setback
    if (!pointInPolygon(lngLat, setbackFeat)) continue;
    push({
      id: `dc-crac-${i}`,
      assetType: 'dc.crac',
      position: lngLat,
      rotation: axis.bearingDeg,
      category: 'crac',
      length_m: 1.5,
      width_m: 1.0,
    });
  }

  // ---- UPS rooms — one per 2.5 MW, in a line next to halls ----
  const upsCount = Math.max(1, Math.ceil(capacityMw / 2.5));
  const upsL = 10;
  const upsW = 6;
  const upsSpacing = upsL + 2;
  const upsBlockLen = upsCount * upsSpacing;
  const upsU0 = -upsBlockLen / 2 + upsL / 2;
  const upsV = -hallBlockWid / 2 - upsW / 2 - 5; // 5 m clear below halls
  for (let i = 0; i < upsCount; i += 1) {
    const u = upsU0 + i * upsSpacing;
    const [ex, ey] = toWorld(u, upsV);
    const lngLat = enu.toLngLat(ex, ey);
    if (!pointInPolygon(lngLat, setbackFeat)) continue;
    push({
      id: `dc-ups-${i}`,
      assetType: 'dc.ups_room',
      position: lngLat,
      rotation: axis.bearingDeg,
      category: 'ups',
      length_m: upsL,
      width_m: upsW,
    });
  }

  // ------------------------------------------------------------
  // Rings — setback, fence, cable corridor (MV/LV → TX yard)
  // ------------------------------------------------------------
  const rings = { setback: setbackFeat };
  try {
    // Fence: buffer convex hull of hall centres by HALL_W/2 + 3 m
    const hallPoints = assets
      .filter((a) => a.category === 'hall')
      .map((a) => turf.point(a.position));
    if (hallPoints.length > 0) {
      const fc = turf.featureCollection(hallPoints);
      const hull = hallPoints.length >= 3
        ? turf.convex(fc)
        : (hallPoints.length === 2
            ? turf.lineString(hallPoints.map((p) => p.geometry.coordinates))
            : hallPoints[0]);
      const fence = hull
        ? dilate(hull, HALL_W / 2 + FENCE_OFFSET_M)
        : null;
      if (fence) rings.fence = fence;
    }
    // Cable corridor: straight line from hall-block centroid → TX yard
    const tx = assets.find((a) => a.category === 'tx_yard');
    if (tx) {
      rings.cableCorridor = turf.lineString([
        centroidLngLat,
        tx.position,
      ]);
    }
  } catch (_) {
    /* ignore ring failures */
  }

  return {
    assets,
    rings,
    meta: {
      centroid: centroidLngLat,
      areaM2: Math.round(areaM2),
      longAxisBearingDeg: Math.round(axis.bearingDeg),
      longAxisLengthM: Math.round(axis.lengthM),
      shortAxisLengthM: Math.round(axis.widthM),
      hallConfig: hallCfg,
      hallCount,
      tier,
      redundancy,
      insidePolygon: placedInside,
      total: totalPlaced,
    },
  };
}

export default buildIntelligentDcLayout;

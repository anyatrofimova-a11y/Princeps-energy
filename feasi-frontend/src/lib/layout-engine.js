/**
 * Layout Engine — draw-and-fill auto-design for solar, BESS, DC buildings.
 *
 * Uses @turf/turf for all geometry operations. Designed to run client-side
 * for instant preview; server-side (Shapely) mirrors for final precision.
 */
import * as turf from "@turf/turf";

/* ── Defaults ─────────────────────────────────────────────────────────── */
const DEFAULT_SOLAR = {
  gcr: 0.43,           // ground coverage ratio
  rowPitch: 8,         // metres between row centres
  panelWidth: 2.1,     // metres (module width)
  panelLength: 1.05,   // metres (module height)
  tilt: 25,            // degrees
  azimuth: 180,        // degrees (south-facing)
  setbackM: 5,         // metres inward from boundary
  wattsPerPanel: 550,
};

const DEFAULT_BESS = {
  containerLength: 12.2,  // metres (standard 40ft)
  containerWidth: 2.44,   // metres
  spacingX: 3,            // metres between containers (side)
  spacingY: 4,            // metres between rows
  setbackM: 10,
  kwhPerContainer: 3700,
};

const DEFAULT_DC = {
  buildingLength: 120,  // metres
  buildingWidth: 60,    // metres
  clearanceM: 15,       // metres between buildings
  maxBuildings: 4,
  mwPerBuilding: 25,
};

/* ── Helpers ──────────────────────────────────────────────────────────── */
function safeDifference(a, b) {
  try { return turf.difference(turf.featureCollection([a, b])); } catch { return a; }
}

function safeIntersect(a, b) {
  try { return turf.intersect(turf.featureCollection([a, b])); } catch { return null; }
}

function safeBuffer(geom, dist) {
  try { return turf.buffer(geom, dist, { units: "meters" }); } catch { return geom; }
}

function subtractExclusions(polygon, exclusions) {
  let result = polygon;
  for (const ex of exclusions) {
    if (!ex) continue;
    result = safeDifference(result, ex);
    if (!result) return null;
  }
  return result;
}

/* ── Solar Layout ─────────────────────────────────────────────────────── */
/**
 * Fill a boundary polygon with solar panel rows.
 * @param {GeoJSON} boundary - Site boundary polygon
 * @param {GeoJSON[]} exclusions - Exclusion zone polygons
 * @param {object} profile - Layout parameters (merged with defaults)
 * @returns {{ features: GeoJSON, stats: object }}
 */
export function generateSolarLayout(boundary, exclusions = [], profile = {}) {
  const p = { ...DEFAULT_SOLAR, ...profile };

  // 1. Buffer inward
  const buffered = safeBuffer(boundary, -p.setbackM);
  if (!buffered) return { features: turf.featureCollection([]), stats: { panels: 0, capacityMW: 0, areaHa: 0 } };

  // 2. Subtract exclusions
  const buildable = subtractExclusions(buffered, exclusions);
  if (!buildable) return { features: turf.featureCollection([]), stats: { panels: 0, capacityMW: 0, areaHa: 0 } };

  // 3. Generate row lines
  const bbox = turf.bbox(buildable);
  const [minX, minY, maxX, maxY] = bbox;
  const azRad = ((p.azimuth - 90) * Math.PI) / 180; // perpendicular to azimuth
  const rowPitchDeg = p.rowPitch / 111320; // approximate metres to degrees

  const rows = [];
  let panelCount = 0;
  const rowWidth = p.panelWidth / 111320; // metres to degrees (approx)

  // Generate parallel lines across bbox
  const diagLen = Math.sqrt((maxX - minX) ** 2 + (maxY - minY) ** 2);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const numRows = Math.ceil((diagLen / rowPitchDeg) * 1.5);

  for (let i = -numRows; i <= numRows; i++) {
    const offset = i * rowPitchDeg;
    // Row centre perpendicular to azimuth
    const oy = cy + offset * Math.cos(azRad);
    const ox = cx + offset * Math.sin(azRad);

    // Line along azimuth direction
    const dx = diagLen * Math.cos(azRad + Math.PI / 2);
    const dy = diagLen * Math.sin(azRad + Math.PI / 2);
    const line = turf.lineString([[ox - dx, oy - dy], [ox + dx, oy + dy]]);

    // Clip to buildable area
    const clipped = turf.lineIntersect(line, buildable);
    if (!clipped?.features?.length) {
      // Try lineSplit or just buffer-intersect
      const bufferedLine = safeBuffer(line, rowWidth / 2);
      if (!bufferedLine) continue;
      const intersection = safeIntersect(bufferedLine, buildable);
      if (intersection && turf.area(intersection) > 1) {
        intersection.properties = { featureType: "solar_row", rowIndex: i };
        rows.push(intersection);
        // Estimate panels: area / (panelWidth * panelLength) in m²
        const areaM2 = turf.area(intersection);
        panelCount += Math.floor(areaM2 / (p.panelWidth * p.panelLength));
      }
    } else if (clipped.features.length >= 2) {
      // Create row rectangles from intersection points
      for (let j = 0; j < clipped.features.length - 1; j += 2) {
        const a = clipped.features[j].geometry.coordinates;
        const b = clipped.features[j + 1].geometry.coordinates;
        const seg = turf.lineString([a, b]);
        const rowPoly = safeBuffer(seg, rowWidth / 2);
        if (rowPoly) {
          rowPoly.properties = { featureType: "solar_row", rowIndex: i };
          rows.push(rowPoly);
          const len = turf.length(seg, { units: "meters" });
          panelCount += Math.floor(len / p.panelLength);
        }
      }
    }
  }

  const capacityMW = (panelCount * p.wattsPerPanel) / 1e6;
  const areaHa = turf.area(buildable) / 10000;

  return {
    features: turf.featureCollection(rows),
    stats: { panels: panelCount, capacityMW: Math.round(capacityMW * 100) / 100, areaHa: Math.round(areaHa * 10) / 10, rows: rows.length },
  };
}

/* ── BESS Layout ──────────────────────────────────────────────────────── */
export function generateBESSLayout(boundary, exclusions = [], profile = {}) {
  const p = { ...DEFAULT_BESS, ...profile };

  const buffered = safeBuffer(boundary, -p.setbackM);
  if (!buffered) return { features: turf.featureCollection([]), stats: { containers: 0, capacityMWh: 0 } };

  const buildable = subtractExclusions(buffered, exclusions);
  if (!buildable) return { features: turf.featureCollection([]), stats: { containers: 0, capacityMWh: 0 } };

  const bbox = turf.bbox(buildable);
  const [minX, minY, maxX, maxY] = bbox;
  const containers = [];

  const dxDeg = (p.containerLength + p.spacingX) / 111320;
  const dyDeg = (p.containerWidth + p.spacingY) / (111320 * Math.cos((minY * Math.PI) / 180));
  const cLenDeg = p.containerLength / 111320;
  const cWidDeg = p.containerWidth / (111320 * Math.cos((minY * Math.PI) / 180));

  for (let x = minX; x + cLenDeg <= maxX; x += dxDeg) {
    for (let y = minY; y + cWidDeg <= maxY; y += dyDeg) {
      const box = turf.bboxPolygon([x, y, x + cLenDeg, y + cWidDeg]);
      // Check if fully inside buildable
      const inter = safeIntersect(box, buildable);
      if (inter && turf.area(inter) > turf.area(box) * 0.9) {
        box.properties = { featureType: "bess_container", index: containers.length };
        containers.push(box);
      }
    }
  }

  return {
    features: turf.featureCollection(containers),
    stats: {
      containers: containers.length,
      capacityMWh: Math.round((containers.length * p.kwhPerContainer) / 1000 * 10) / 10,
    },
  };
}

/* ── DC Building Layout ───────────────────────────────────────────────── */
export function generateDCBuildingLayout(boundary, exclusions = [], profile = {}) {
  const p = { ...DEFAULT_DC, ...profile };

  const buffered = safeBuffer(boundary, -p.clearanceM);
  if (!buffered) return { features: turf.featureCollection([]), stats: { buildings: 0, totalMW: 0 } };

  const buildable = subtractExclusions(buffered, exclusions);
  if (!buildable) return { features: turf.featureCollection([]), stats: { buildings: 0, totalMW: 0 } };

  const bbox = turf.bbox(buildable);
  const [minX, minY, maxX, maxY] = bbox;
  const buildings = [];

  const bLenDeg = p.buildingLength / 111320;
  const bWidDeg = p.buildingWidth / (111320 * Math.cos((minY * Math.PI) / 180));
  const gapXDeg = p.clearanceM / 111320;
  const gapYDeg = p.clearanceM / (111320 * Math.cos((minY * Math.PI) / 180));

  for (let x = minX; x + bLenDeg <= maxX && buildings.length < p.maxBuildings; x += bLenDeg + gapXDeg) {
    for (let y = minY; y + bWidDeg <= maxY && buildings.length < p.maxBuildings; y += bWidDeg + gapYDeg) {
      const box = turf.bboxPolygon([x, y, x + bLenDeg, y + bWidDeg]);
      const inter = safeIntersect(box, buildable);
      if (inter && turf.area(inter) > turf.area(box) * 0.85) {
        box.properties = {
          featureType: "dc_building",
          index: buildings.length,
          mw: p.mwPerBuilding,
          label: `DC Hall ${buildings.length + 1}`,
        };
        buildings.push(box);
      }
    }
  }

  return {
    features: turf.featureCollection(buildings),
    stats: {
      buildings: buildings.length,
      totalMW: buildings.length * p.mwPerBuilding,
    },
  };
}

/* ── Buildable Area ───────────────────────────────────────────────────── */
export function computeBuildableArea(boundary, constraints = {}) {
  const { slopeLimit, floodZones = [], heritage = [], ecology = [], setbacks = {} } = constraints;
  const totalAreaHa = turf.area(boundary) / 10000;

  let buildable = boundary;

  // Apply boundary setback
  if (setbacks.boundary) {
    buildable = safeBuffer(buildable, -setbacks.boundary);
    if (!buildable) return { buildable: null, excluded: boundary, buildableAreaHa: 0, totalAreaHa, buildablePct: 0 };
  }

  // Subtract all constraint layers
  const allExclusions = [...floodZones, ...heritage, ...ecology];
  for (const ex of allExclusions) {
    if (!ex) continue;
    // Buffer constraint features if setback specified
    const bufDist = setbacks.watercourse || setbacks.heritage || 0;
    const bufferedEx = bufDist ? safeBuffer(ex, bufDist) : ex;
    buildable = safeDifference(buildable, bufferedEx);
    if (!buildable) return { buildable: null, excluded: boundary, buildableAreaHa: 0, totalAreaHa, buildablePct: 0 };
  }

  const buildableAreaHa = turf.area(buildable) / 10000;
  const excluded = safeDifference(boundary, buildable);

  return {
    buildable,
    excluded,
    buildableAreaHa: Math.round(buildableAreaHa * 10) / 10,
    totalAreaHa: Math.round(totalAreaHa * 10) / 10,
    buildablePct: Math.round((buildableAreaHa / totalAreaHa) * 100),
  };
}

/* ── Hybrid Layout ────────────────────────────────────────────────────── */
export function generateHybridLayout(boundary, exclusions = [], config = {}) {
  const { solarProfile, bessProfile, dcProfile } = config;

  // Phase 1: Place DC buildings first (largest setback)
  const dcResult = generateDCBuildingLayout(boundary, exclusions, dcProfile);
  const dcExclusions = [...exclusions, ...dcResult.features.features.map((f) => safeBuffer(f, 10)).filter(Boolean)];

  // Phase 2: Place BESS near DC buildings
  const bessResult = generateBESSLayout(boundary, dcExclusions, bessProfile);
  const bessExclusions = [...dcExclusions, ...bessResult.features.features.map((f) => safeBuffer(f, 3)).filter(Boolean)];

  // Phase 3: Fill remainder with solar
  const solarResult = generateSolarLayout(boundary, bessExclusions, solarProfile);

  // Combine
  const allFeatures = [
    ...dcResult.features.features,
    ...bessResult.features.features,
    ...solarResult.features.features,
  ];

  return {
    features: turf.featureCollection(allFeatures),
    stats: {
      dc: dcResult.stats,
      bess: bessResult.stats,
      solar: solarResult.stats,
      totalAreaHa: Math.round(turf.area(boundary) / 10000 * 10) / 10,
    },
  };
}

/**
 * Nebula.gl-inspired drawing mode engine for MapLibre GL JS.
 *
 * Implements the click-sequence state machine pattern from nebula.gl:
 *  - Click to add vertices
 *  - Mouse move updates tentative (preview) geometry
 *  - Click first/last handle or double-click to complete
 *  - Escape to cancel
 *
 * Modes: view, point, line, polygon, rectangle, circle, modify, measure
 */

// ── Geometry helpers ──

function distance(a, b) {
  const dx = a[0] - b[0], dy = a[1] - b[1];
  return Math.sqrt(dx * dx + dy * dy);
}

function midpoint(a, b) {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
}

/** Haversine distance in metres */
function haversineMetres(a, b) {
  const R = 6371000;
  const toRad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * toRad;
  const dLon = (b[0] - a[0]) * toRad;
  const lat1 = a[1] * toRad, lat2 = b[1] * toRad;
  const sin1 = Math.sin(dLat / 2), sin2 = Math.sin(dLon / 2);
  const h = sin1 * sin1 + Math.cos(lat1) * Math.cos(lat2) * sin2 * sin2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** Polygon area via Shoelace (in map units, then scaled to m²) */
function polygonAreaM2(ring) {
  if (ring.length < 3) return 0;
  // Use haversine-based area approximation
  let area = 0;
  const n = ring.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    area += ring[i][0] * ring[j][1];
    area -= ring[j][0] * ring[i][1];
  }
  area = Math.abs(area) / 2;
  // Convert from degree² to m² (rough at mid-latitudes ~52°N)
  const midLat = ring.reduce((s, p) => s + p[1], 0) / n;
  const mPerDegLat = 111320;
  const mPerDegLon = 111320 * Math.cos(midLat * Math.PI / 180);
  return area * mPerDegLat * mPerDegLon;
}

function perimeterMetres(ring) {
  let total = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    total += haversineMetres(ring[i], ring[i + 1]);
  }
  return total;
}

function circlePolygon(center, radiusDeg, n = 64) {
  const coords = [];
  for (let i = 0; i <= n; i++) {
    const angle = (i / n) * 2 * Math.PI;
    coords.push([
      center[0] + radiusDeg * Math.cos(angle),
      center[1] + radiusDeg * Math.sin(angle) * (111320 / (111320 * Math.cos(center[1] * Math.PI / 180))),
    ]);
  }
  return coords;
}

// ── Drawing Mode Engine ──

export const MODES = {
  VIEW: "view",
  POINT: "point",
  LINE: "line",
  POLYGON: "polygon",
  RECTANGLE: "rectangle",
  CIRCLE: "circle",
  MODIFY: "modify",
  MEASURE: "measure",
};

/**
 * Create initial drawing state.
 */
export function createDrawState() {
  return {
    mode: MODES.VIEW,
    clickSequence: [],   // [lng, lat] positions clicked so far
    mouseCoord: null,    // current mouse [lng, lat]
    features: { type: "FeatureCollection", features: [] },
    selectedIndex: -1,   // index of selected feature (modify mode)
    dragVertex: null,    // { featureIndex, vertexIndex } when dragging
    snapCoord: null,     // snapped coordinate if applicable
  };
}

/**
 * Get tentative (preview) GeoJSON for current drawing state.
 * Returns a FeatureCollection with:
 *   - tentative geometry (the shape being drawn)
 *   - edit handles (circles at clicked vertices)
 */
export function getTentativeGuides(state) {
  const { mode, clickSequence, mouseCoord } = state;
  const features = [];

  if (mode === MODES.VIEW || !mouseCoord) return { type: "FeatureCollection", features };

  const seq = clickSequence;
  const mouse = mouseCoord;

  if (mode === MODES.POINT) {
    features.push({
      type: "Feature",
      properties: { guideType: "tentative", drawMode: "point" },
      geometry: { type: "Point", coordinates: mouse },
    });
  }

  if (mode === MODES.LINE) {
    if (seq.length >= 1) {
      features.push({
        type: "Feature",
        properties: { guideType: "tentative", drawMode: "line" },
        geometry: { type: "LineString", coordinates: [...seq, mouse] },
      });
    }
  }

  if (mode === MODES.POLYGON) {
    if (seq.length === 1) {
      features.push({
        type: "Feature",
        properties: { guideType: "tentative", drawMode: "polygon" },
        geometry: { type: "LineString", coordinates: [...seq, mouse] },
      });
    } else if (seq.length >= 2) {
      features.push({
        type: "Feature",
        properties: { guideType: "tentative", drawMode: "polygon" },
        geometry: { type: "Polygon", coordinates: [[...seq, mouse, seq[0]]] },
      });
    }
  }

  if (mode === MODES.RECTANGLE) {
    if (seq.length === 1) {
      const [x0, y0] = seq[0];
      const [x1, y1] = mouse;
      features.push({
        type: "Feature",
        properties: { guideType: "tentative", drawMode: "rectangle" },
        geometry: {
          type: "Polygon",
          coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
        },
      });
    }
  }

  if (mode === MODES.CIRCLE) {
    if (seq.length === 1) {
      const r = distance(seq[0], mouse);
      const ring = circlePolygon(seq[0], r);
      features.push({
        type: "Feature",
        properties: {
          guideType: "tentative", drawMode: "circle",
          radiusMetres: Math.round(haversineMetres(seq[0], mouse)),
        },
        geometry: { type: "Polygon", coordinates: [ring] },
      });
    }
  }

  if (mode === MODES.MEASURE) {
    if (seq.length >= 1) {
      const allPts = [...seq, mouse];
      features.push({
        type: "Feature",
        properties: { guideType: "tentative", drawMode: "measure" },
        geometry: {
          type: seq.length >= 2 ? "Polygon" : "LineString",
          coordinates: seq.length >= 2 ? [[...allPts, allPts[0]]] : allPts,
        },
      });
    }
  }

  // Edit handles for each clicked vertex
  seq.forEach((coord, i) => {
    features.push({
      type: "Feature",
      properties: {
        guideType: "editHandle",
        handleType: i === 0 ? "first" : i === seq.length - 1 ? "last" : "intermediate",
        positionIndex: i,
      },
      geometry: { type: "Point", coordinates: coord },
    });
  });

  return { type: "FeatureCollection", features };
}

/**
 * Get edit handles for existing features in modify mode.
 */
export function getModifyGuides(state) {
  const features = [];
  if (state.mode !== MODES.MODIFY || state.selectedIndex < 0) {
    return { type: "FeatureCollection", features };
  }

  const feat = state.features.features[state.selectedIndex];
  if (!feat) return { type: "FeatureCollection", features };

  const coords = feat.geometry.type === "Polygon"
    ? feat.geometry.coordinates[0].slice(0, -1) // remove closing coord
    : feat.geometry.type === "LineString"
      ? feat.geometry.coordinates
      : feat.geometry.type === "Point"
        ? [feat.geometry.coordinates]
        : [];

  coords.forEach((coord, i) => {
    features.push({
      type: "Feature",
      properties: {
        guideType: "editHandle",
        handleType: "existing",
        featureIndex: state.selectedIndex,
        vertexIndex: i,
      },
      geometry: { type: "Point", coordinates: coord },
    });
  });

  // Midpoint handles for polygon/line (for inserting new vertices)
  if (feat.geometry.type === "Polygon" || feat.geometry.type === "LineString") {
    const isPolygon = feat.geometry.type === "Polygon";
    const pts = isPolygon ? feat.geometry.coordinates[0].slice(0, -1) : feat.geometry.coordinates;
    const count = isPolygon ? pts.length : pts.length - 1;
    for (let i = 0; i < count; i++) {
      const j = (i + 1) % pts.length;
      features.push({
        type: "Feature",
        properties: {
          guideType: "editHandle",
          handleType: "midpoint",
          featureIndex: state.selectedIndex,
          vertexIndex: i,
          insertAfter: i,
        },
        geometry: { type: "Point", coordinates: midpoint(pts[i], pts[j]) },
      });
    }
  }

  return { type: "FeatureCollection", features };
}

/**
 * Get measurement tooltips for current state.
 */
export function getMeasurements(state) {
  const { mode, clickSequence, mouseCoord } = state;
  if (mode !== MODES.MEASURE || !mouseCoord || clickSequence.length === 0) return null;

  const allPts = [...clickSequence, mouseCoord];

  let totalDist = 0;
  for (let i = 0; i < allPts.length - 1; i++) {
    totalDist += haversineMetres(allPts[i], allPts[i + 1]);
  }

  const result = { distance: totalDist };

  if (allPts.length >= 3) {
    const ring = [...allPts, allPts[0]];
    result.area = polygonAreaM2(allPts);
    result.perimeter = perimeterMetres(ring);
  }

  return result;
}

/**
 * Process a click event. Returns { state, completedFeature? }.
 */
export function handleClick(state, lngLat, clickedHandleIndex = -1) {
  const { mode, clickSequence } = state;
  let newState = { ...state };

  if (mode === MODES.VIEW) return { state };

  if (mode === MODES.POINT) {
    const feature = {
      type: "Feature",
      properties: { drawMode: "point", created: Date.now() },
      geometry: { type: "Point", coordinates: lngLat },
    };
    newState = {
      ...state,
      features: addFeature(state.features, feature),
      clickSequence: [],
    };
    return { state: newState, completedFeature: feature };
  }

  if (mode === MODES.POLYGON) {
    // Check if clicked first or last handle to close polygon
    if (clickSequence.length > 2 && (clickedHandleIndex === 0 || clickedHandleIndex === clickSequence.length - 1)) {
      const feature = {
        type: "Feature",
        properties: { drawMode: "polygon", created: Date.now() },
        geometry: { type: "Polygon", coordinates: [[...clickSequence, clickSequence[0]]] },
      };
      newState = {
        ...state,
        features: addFeature(state.features, feature),
        clickSequence: [],
      };
      return { state: newState, completedFeature: feature };
    }
    // Add vertex
    newState = { ...state, clickSequence: [...clickSequence, lngLat] };
    return { state: newState };
  }

  if (mode === MODES.LINE) {
    // Double-click or click last handle to finish line
    if (clickSequence.length > 1 && clickedHandleIndex === clickSequence.length - 1) {
      const feature = {
        type: "Feature",
        properties: { drawMode: "line", created: Date.now() },
        geometry: { type: "LineString", coordinates: [...clickSequence] },
      };
      newState = {
        ...state,
        features: addFeature(state.features, feature),
        clickSequence: [],
      };
      return { state: newState, completedFeature: feature };
    }
    newState = { ...state, clickSequence: [...clickSequence, lngLat] };
    return { state: newState };
  }

  if (mode === MODES.RECTANGLE) {
    if (clickSequence.length === 0) {
      newState = { ...state, clickSequence: [lngLat] };
      return { state: newState };
    }
    // Second click completes rectangle
    const [x0, y0] = clickSequence[0];
    const [x1, y1] = lngLat;
    const feature = {
      type: "Feature",
      properties: { drawMode: "rectangle", created: Date.now() },
      geometry: {
        type: "Polygon",
        coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
      },
    };
    newState = {
      ...state,
      features: addFeature(state.features, feature),
      clickSequence: [],
    };
    return { state: newState, completedFeature: feature };
  }

  if (mode === MODES.CIRCLE) {
    if (clickSequence.length === 0) {
      newState = { ...state, clickSequence: [lngLat] };
      return { state: newState };
    }
    const r = distance(clickSequence[0], lngLat);
    const ring = circlePolygon(clickSequence[0], r);
    const feature = {
      type: "Feature",
      properties: {
        drawMode: "circle",
        center: clickSequence[0],
        radiusMetres: Math.round(haversineMetres(clickSequence[0], lngLat)),
        created: Date.now(),
      },
      geometry: { type: "Polygon", coordinates: [ring] },
    };
    newState = {
      ...state,
      features: addFeature(state.features, feature),
      clickSequence: [],
    };
    return { state: newState, completedFeature: feature };
  }

  if (mode === MODES.MEASURE) {
    newState = { ...state, clickSequence: [...clickSequence, lngLat] };
    return { state: newState };
  }

  if (mode === MODES.MODIFY) {
    // Select feature at click point (handled externally via map query)
    return { state };
  }

  return { state };
}

/**
 * Handle double-click (finish polygon/line).
 * Note: browser fires click → click → dblclick, so the clickSequence
 * will contain up to 2 extra duplicate vertices from those click events.
 * We strip the duplicate(s) before finalising the geometry.
 */
export function handleDoubleClick(state) {
  const { mode, clickSequence } = state;

  // Remove trailing duplicate vertices added by the click events that precede dblclick
  let seq = [...clickSequence];
  while (seq.length > 1 && distance(seq[seq.length - 1], seq[seq.length - 2]) < 0.00001) {
    seq.pop();
  }

  if (mode === MODES.POLYGON && seq.length > 2) {
    const feature = {
      type: "Feature",
      properties: { drawMode: "polygon", created: Date.now() },
      geometry: { type: "Polygon", coordinates: [[...seq, seq[0]]] },
    };
    return {
      state: {
        ...state,
        features: addFeature(state.features, feature),
        clickSequence: [],
      },
      completedFeature: feature,
    };
  }

  if (mode === MODES.LINE && seq.length > 1) {
    const feature = {
      type: "Feature",
      properties: { drawMode: "line", created: Date.now() },
      geometry: { type: "LineString", coordinates: [...seq] },
    };
    return {
      state: {
        ...state,
        features: addFeature(state.features, feature),
        clickSequence: [],
      },
      completedFeature: feature,
    };
  }

  if (mode === MODES.MEASURE && clickSequence.length >= 2) {
    return { state: { ...state, clickSequence: [] } };
  }

  return { state };
}

/**
 * Move a vertex in modify mode.
 */
export function moveVertex(state, featureIndex, vertexIndex, newCoord) {
  const feat = state.features.features[featureIndex];
  if (!feat) return state;

  const updated = JSON.parse(JSON.stringify(feat));
  if (updated.geometry.type === "Polygon") {
    updated.geometry.coordinates[0][vertexIndex] = newCoord;
    // If it's the first or last vertex, update the closing coord too
    const ring = updated.geometry.coordinates[0];
    if (vertexIndex === 0) ring[ring.length - 1] = newCoord;
    if (vertexIndex === ring.length - 1) ring[0] = newCoord;
  } else if (updated.geometry.type === "LineString") {
    updated.geometry.coordinates[vertexIndex] = newCoord;
  } else if (updated.geometry.type === "Point") {
    updated.geometry.coordinates = newCoord;
  }

  const newFeatures = [...state.features.features];
  newFeatures[featureIndex] = updated;
  return {
    ...state,
    features: { ...state.features, features: newFeatures },
  };
}

/**
 * Insert a vertex after the given index (for midpoint handle clicks).
 */
export function insertVertex(state, featureIndex, afterIndex, coord) {
  const feat = state.features.features[featureIndex];
  if (!feat) return state;

  const updated = JSON.parse(JSON.stringify(feat));
  if (updated.geometry.type === "Polygon") {
    updated.geometry.coordinates[0].splice(afterIndex + 1, 0, coord);
  } else if (updated.geometry.type === "LineString") {
    updated.geometry.coordinates.splice(afterIndex + 1, 0, coord);
  }

  const newFeatures = [...state.features.features];
  newFeatures[featureIndex] = updated;
  return {
    ...state,
    features: { ...state.features, features: newFeatures },
  };
}

/**
 * Delete selected feature.
 */
export function deleteFeature(state, index) {
  if (index < 0 || index >= state.features.features.length) return state;
  const newFeatures = state.features.features.filter((_, i) => i !== index);
  return {
    ...state,
    features: { ...state.features, features: newFeatures },
    selectedIndex: -1,
  };
}

/**
 * Delete a vertex from the selected feature.
 */
export function deleteVertex(state, featureIndex, vertexIndex) {
  const feat = state.features.features[featureIndex];
  if (!feat) return state;

  const updated = JSON.parse(JSON.stringify(feat));
  if (updated.geometry.type === "Polygon") {
    const ring = updated.geometry.coordinates[0];
    if (ring.length <= 4) return deleteFeature(state, featureIndex); // need at least 3 vertices + closing
    ring.splice(vertexIndex, 1);
    if (vertexIndex === 0) ring[ring.length - 1] = ring[0]; // fix closing coord
  } else if (updated.geometry.type === "LineString") {
    if (updated.geometry.coordinates.length <= 2) return deleteFeature(state, featureIndex);
    updated.geometry.coordinates.splice(vertexIndex, 1);
  }

  const newFeatures = [...state.features.features];
  newFeatures[featureIndex] = updated;
  return {
    ...state,
    features: { ...state.features, features: newFeatures },
  };
}

/**
 * Find nearest snap target among existing features.
 * Returns [lng, lat] or null.
 */
export function findSnapTarget(state, coord, threshold = 0.0005) {
  let best = null, bestDist = threshold;
  for (const feat of state.features.features) {
    const coords = feat.geometry.type === "Polygon"
      ? feat.geometry.coordinates[0]
      : feat.geometry.type === "LineString"
        ? feat.geometry.coordinates
        : feat.geometry.type === "Point"
          ? [feat.geometry.coordinates]
          : [];
    for (const c of coords) {
      const d = distance(coord, c);
      if (d < bestDist) { bestDist = d; best = c; }
    }
  }
  return best;
}

// ── Helpers ──

function addFeature(fc, feature) {
  return {
    ...fc,
    features: [...fc.features, feature],
  };
}

/**
 * Format area for display.
 */
export function formatArea(m2) {
  if (m2 > 10000) return `${(m2 / 10000).toFixed(2)} ha`;
  return `${Math.round(m2)} m\u00B2`;
}

/**
 * Format distance for display.
 */
export function formatDistance(m) {
  if (m > 1000) return `${(m / 1000).toFixed(2)} km`;
  return `${Math.round(m)} m`;
}

/**
 * Get cursor for current mode.
 */
export function getCursor(mode) {
  switch (mode) {
    case MODES.POINT:
    case MODES.LINE:
    case MODES.POLYGON:
    case MODES.RECTANGLE:
    case MODES.CIRCLE:
    case MODES.MEASURE:
      return "crosshair";
    case MODES.MODIFY:
      return "default";
    default:
      return "";
  }
}

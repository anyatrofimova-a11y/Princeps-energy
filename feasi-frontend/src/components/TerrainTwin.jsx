import React, { useEffect, useRef, useState, useCallback, useMemo } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

/* ═══════════════════════════════════════════════════════════════════════════
   TerrainTwin — High-resolution LiDAR terrain analysis digital twin
   ═══════════════════════════════════════════════════════════════════════════
   Fetches EA LiDAR 1m data from /api/terrain/lidar and /api/terrain/analyse.
   Renders a Three.js terrain mesh with toggleable analysis overlays:
     Elevation | Slope | Aspect | Viewshed | Hydrology
   Cross-section tool, contour lines, stats panel.
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── Color ramps ────────────────────────────────────────────────────────── */

// Elevation: hypsometric tint (green lowlands -> brown hills -> white peaks)
const ELEV_RAMP = [
  [0.00, [0.16, 0.44, 0.22]],  // dark forest green
  [0.10, [0.24, 0.55, 0.28]],  // green
  [0.25, [0.45, 0.66, 0.30]],  // yellow-green
  [0.40, [0.72, 0.72, 0.35]],  // tan
  [0.55, [0.65, 0.50, 0.30]],  // brown
  [0.70, [0.55, 0.40, 0.32]],  // dark brown
  [0.85, [0.70, 0.65, 0.60]],  // grey
  [1.00, [0.92, 0.92, 0.92]],  // near-white
];

// Slope: green (flat) -> yellow -> orange -> red (steep)
const SLOPE_RAMP = [
  [0.00, [0.20, 0.66, 0.33]],  // green — <2 deg
  [0.08, [0.40, 0.75, 0.30]],  // light green — 3 deg
  [0.20, [0.85, 0.85, 0.20]],  // yellow — 7 deg
  [0.40, [0.95, 0.65, 0.10]],  // orange — 15 deg
  [0.65, [0.90, 0.30, 0.10]],  // red-orange — 25 deg
  [1.00, [0.75, 0.10, 0.10]],  // red — 35+ deg
];

// Aspect: compass-based (N=blue, E=green, S=warm-red, W=purple)
const ASPECT_COLORS = {
  N:  [0.30, 0.45, 0.75],  // cool blue
  NE: [0.25, 0.60, 0.65],  // teal
  E:  [0.30, 0.70, 0.40],  // green
  SE: [0.70, 0.70, 0.25],  // yellow-green
  S:  [0.90, 0.55, 0.15],  // warm orange (solar-optimal)
  SW: [0.85, 0.35, 0.20],  // red-orange
  W:  [0.65, 0.25, 0.55],  // purple
  NW: [0.40, 0.35, 0.70],  // blue-purple
};

// Viewshed: visible=green, hidden=dark
const VIS_COLOR = [0.20, 0.85, 0.35];
const HIDDEN_COLOR = [0.12, 0.12, 0.15];

// Hydrology TWI: dry (tan) -> wet (deep blue)
const HYDRO_RAMP = [
  [0.00, [0.72, 0.62, 0.42]],  // dry tan
  [0.20, [0.50, 0.60, 0.35]],  // olive
  [0.40, [0.30, 0.55, 0.50]],  // teal
  [0.60, [0.20, 0.45, 0.70]],  // blue
  [0.80, [0.15, 0.30, 0.75]],  // deep blue
  [1.00, [0.10, 0.15, 0.60]],  // dark blue
];

function sampleRamp(ramp, t) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 0; i < ramp.length - 1; i++) {
    const [t0, c0] = ramp[i];
    const [t1, c1] = ramp[i + 1];
    if (t >= t0 && t <= t1) {
      const f = (t - t0) / (t1 - t0);
      return [
        c0[0] + (c1[0] - c0[0]) * f,
        c0[1] + (c1[1] - c0[1]) * f,
        c0[2] + (c1[2] - c0[2]) * f,
      ];
    }
  }
  return ramp[ramp.length - 1][1];
}

function aspectToColor(deg) {
  // 0=N, 90=E, 180=S, 270=W
  const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const idx = Math.round(((deg % 360 + 360) % 360) / 45) % 8;
  const nextIdx = (idx + 1) % 8;
  const frac = (((deg % 360 + 360) % 360) / 45) - idx;
  const c0 = ASPECT_COLORS[dirs[idx]];
  const c1 = ASPECT_COLORS[dirs[nextIdx]];
  const f = Math.abs(frac);
  return [
    c0[0] + (c1[0] - c0[0]) * f,
    c0[1] + (c1[1] - c0[1]) * f,
    c0[2] + (c1[2] - c0[2]) * f,
  ];
}


/* ── Terrain computation helpers ───────────────────────────────────────── */

function computeSlope(values, w, h, resolution) {
  const slope = new Float32Array(w * h);
  for (let r = 0; r < h; r++) {
    for (let c = 0; c < w; c++) {
      const idx = r * w + c;
      const left = c > 0 ? values[r * w + (c - 1)] : values[idx];
      const right = c < w - 1 ? values[r * w + (c + 1)] : values[idx];
      const up = r > 0 ? values[(r - 1) * w + c] : values[idx];
      const down = r < h - 1 ? values[(r + 1) * w + c] : values[idx];
      const dx = (right - left) / (2 * resolution);
      const dy = (down - up) / (2 * resolution);
      slope[idx] = Math.atan(Math.sqrt(dx * dx + dy * dy)) * (180 / Math.PI);
    }
  }
  return slope;
}

function computeAspect(values, w, h, resolution) {
  const aspect = new Float32Array(w * h);
  for (let r = 0; r < h; r++) {
    for (let c = 0; c < w; c++) {
      const idx = r * w + c;
      const left = c > 0 ? values[r * w + (c - 1)] : values[idx];
      const right = c < w - 1 ? values[r * w + (c + 1)] : values[idx];
      const up = r > 0 ? values[(r - 1) * w + c] : values[idx];
      const down = r < h - 1 ? values[(r + 1) * w + c] : values[idx];
      const dx = (right - left) / (2 * resolution);
      const dy = (down - up) / (2 * resolution);
      let a = Math.atan2(-dy, dx) * (180 / Math.PI);
      // Convert from math angle to compass bearing (0=N, clockwise)
      a = (90 - a + 360) % 360;
      aspect[idx] = a;
    }
  }
  return aspect;
}

function computeViewshed(values, w, h) {
  // Simple ray-cast viewshed from centre
  const cx = Math.floor(w / 2);
  const cy = Math.floor(h / 2);
  const vis = new Uint8Array(w * h);
  vis[cy * w + cx] = 1;

  const edges = new Set();
  for (let x = 0; x < w; x++) {
    edges.add(`0,${x}`);
    edges.add(`${h - 1},${x}`);
  }
  for (let y = 0; y < h; y++) {
    edges.add(`${y},0`);
    edges.add(`${y},${w - 1}`);
  }

  const targetElev = values[cy * w + cx] + 3; // 3m structure height

  for (const key of edges) {
    const [ey, ex] = key.split(",").map(Number);
    const dy = ey - cy;
    const dx = ex - cx;
    const steps = Math.max(Math.abs(dy), Math.abs(dx));
    if (steps === 0) continue;
    const yStep = dy / steps;
    const xStep = dx / steps;
    let maxAngle = -Infinity;

    for (let i = 1; i <= steps; i++) {
      const py = Math.round(cy + yStep * i);
      const px = Math.round(cx + xStep * i);
      if (py < 0 || py >= h || px < 0 || px >= w) break;
      const dist = Math.sqrt((py - cy) ** 2 + (px - cx) ** 2);
      if (dist < 0.5) continue;
      const elev = values[py * w + px] + 1.6; // observer eye height
      const angle = Math.atan2(elev - targetElev, dist);
      if (angle > maxAngle) {
        maxAngle = angle;
        vis[py * w + px] = 1;
      }
    }
  }
  return vis;
}

function computeTWI(values, w, h, resolution) {
  // Simplified Topographic Wetness Index
  const twi = new Float32Array(w * h);
  const flowAcc = new Float32Array(w * h).fill(1);

  // D8 flow direction offsets
  const offsets = [[-1,-1],[-1,0],[-1,1],[0,-1],[0,1],[1,-1],[1,0],[1,1]];
  const dists = [1.414, 1, 1.414, 1, 1, 1.414, 1, 1.414];

  // Sort by elevation descending for flow routing
  const indices = Array.from({ length: w * h }, (_, i) => i);
  indices.sort((a, b) => values[b] - values[a]);

  for (const idx of indices) {
    const r = Math.floor(idx / w);
    const c = idx % w;
    if (r < 1 || r >= h - 1 || c < 1 || c >= w - 1) continue;

    let maxSlope = 0;
    let maxDir = -1;
    for (let d = 0; d < 8; d++) {
      const nr = r + offsets[d][0];
      const nc = c + offsets[d][1];
      const drop = values[idx] - values[nr * w + nc];
      const s = drop / (dists[d] * resolution);
      if (s > maxSlope) {
        maxSlope = s;
        maxDir = d;
      }
    }
    if (maxDir >= 0) {
      const nr = r + offsets[maxDir][0];
      const nc = c + offsets[maxDir][1];
      flowAcc[nr * w + nc] += flowAcc[idx];
    }
  }

  // TWI = ln(a / tan(beta))
  const pixelArea = resolution * resolution;
  for (let i = 0; i < w * h; i++) {
    const r = Math.floor(i / w);
    const c = i % w;
    const left = c > 0 ? values[r * w + (c - 1)] : values[i];
    const right = c < w - 1 ? values[r * w + (c + 1)] : values[i];
    const up = r > 0 ? values[(r - 1) * w + c] : values[i];
    const down = r < h - 1 ? values[(r + 1) * w + c] : values[i];
    const dx = (right - left) / (2 * resolution);
    const dy = (down - up) / (2 * resolution);
    let tanSlope = Math.sqrt(dx * dx + dy * dy);
    if (tanSlope < 0.001) tanSlope = 0.001;
    const specificArea = flowAcc[i] * pixelArea / resolution;
    twi[i] = Math.max(0, Math.min(25, Math.log(specificArea / tanSlope)));
  }
  return { twi, flowAcc };
}


/* ── Three.js environment ──────────────────────────────────────────────── */

function buildSkyGradient(scene) {
  const canvas = document.createElement("canvas");
  canvas.width = 2;
  canvas.height = 512;
  const ctx = canvas.getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 512);
  grad.addColorStop(0.0, "#0a1628");
  grad.addColorStop(0.15, "#1a3a5c");
  grad.addColorStop(0.35, "#4a8ab5");
  grad.addColorStop(0.5, "#87ceeb");
  grad.addColorStop(0.7, "#b8dce8");
  grad.addColorStop(1.0, "#d4e4d0");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 2, 512);
  const tex = new THREE.CanvasTexture(canvas);
  tex.mapping = THREE.EquirectangularReflectionMapping;
  scene.background = tex;
}

function setupLighting(scene) {
  // Ambient
  const ambient = new THREE.AmbientLight(0x8899bb, 0.5);
  scene.add(ambient);

  // Hemisphere (sky/ground)
  const hemi = new THREE.HemisphereLight(0x87ceeb, 0x3d6b35, 0.35);
  scene.add(hemi);

  // Sun (directional)
  const sun = new THREE.DirectionalLight(0xfff4e0, 1.2);
  sun.position.set(80, 120, 60);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.left = -150;
  sun.shadow.camera.right = 150;
  sun.shadow.camera.top = 150;
  sun.shadow.camera.bottom = -150;
  sun.shadow.camera.near = 10;
  sun.shadow.camera.far = 400;
  sun.shadow.bias = -0.001;
  scene.add(sun);

  // Fill light
  const fill = new THREE.DirectionalLight(0xb0c4de, 0.3);
  fill.position.set(-40, 60, -30);
  scene.add(fill);
}

function buildFog(scene) {
  scene.fog = new THREE.FogExp2(0x8faec0, 0.0015);
}


/* ── Contour line generation ───────────────────────────────────────────── */

function buildContourLines(values, w, h, meshSize, elevMin, elevRange, interval) {
  const group = new THREE.Group();
  group.name = "contours";
  if (!values || elevRange < 1) return group;

  const cellW = meshSize / (w - 1);
  const cellH = meshSize / (h - 1);
  const heightScale = Math.min(60, Math.max(20, elevRange * 1.5));

  // Determine contour levels
  const startElev = Math.ceil(elevMin / interval) * interval;
  const endElev = elevMin + elevRange;
  const levels = [];
  for (let e = startElev; e <= endElev; e += interval) {
    levels.push(e);
  }

  const majorInterval = interval * 5;
  const contourMat = new THREE.LineBasicMaterial({
    color: 0x000000, transparent: true, opacity: 0.2, linewidth: 1,
  });
  const majorMat = new THREE.LineBasicMaterial({
    color: 0x000000, transparent: true, opacity: 0.4, linewidth: 1,
  });

  for (const level of levels) {
    const isMajor = Math.abs(level % majorInterval) < 0.01;
    const segments = [];

    for (let r = 0; r < h - 1; r++) {
      for (let c = 0; c < w - 1; c++) {
        // Marching squares on this cell
        const v00 = values[r * w + c];
        const v10 = values[r * w + (c + 1)];
        const v01 = values[(r + 1) * w + c];
        const v11 = values[(r + 1) * w + (c + 1)];

        const corners = [v00, v10, v11, v01];
        let config = 0;
        for (let i = 0; i < 4; i++) {
          if (corners[i] >= level) config |= (1 << i);
        }
        if (config === 0 || config === 15) continue;

        // Interpolate edge crossings
        const edges = marchingSquaresEdges(config, corners, level);
        for (const [e0, e1] of edges) {
          const p0 = edgeToWorld(e0, r, c, cellW, cellH, w, h, meshSize, values, elevMin, elevRange, heightScale);
          const p1 = edgeToWorld(e1, r, c, cellW, cellH, w, h, meshSize, values, elevMin, elevRange, heightScale);
          if (p0 && p1) {
            segments.push(p0, p1);
          }
        }
      }
    }

    if (segments.length >= 2) {
      const geom = new THREE.BufferGeometry().setFromPoints(segments);
      const line = new THREE.LineSegments(geom, isMajor ? majorMat : contourMat);
      line.renderOrder = 1;
      group.add(line);
    }
  }

  return group;
}

// Marching squares edge lookup
function marchingSquaresEdges(config, corners, level) {
  // Edge numbering: 0=bottom, 1=right, 2=top, 3=left
  const edgeTable = {
    1: [[3, 0]], 2: [[0, 1]], 3: [[3, 1]], 4: [[1, 2]], 5: [[3, 0], [1, 2]],
    6: [[0, 2]], 7: [[3, 2]], 8: [[2, 3]], 9: [[2, 0]], 10: [[0, 1], [2, 3]],
    11: [[2, 1]], 12: [[1, 3]], 13: [[1, 0]], 14: [[0, 3]],
  };
  const pairs = edgeTable[config];
  if (!pairs) return [];

  return pairs.map(([e0, e1]) => [e0, e1]);
}

function edgeToWorld(edgeIdx, r, c, cellW, cellH, w, h, meshSize, values, elevMin, elevRange, heightScale) {
  const halfSize = meshSize / 2;
  // Cell corners in world XZ
  const x0 = c * cellW - halfSize;
  const x1 = (c + 1) * cellW - halfSize;
  const z0 = r * cellH - halfSize;
  const z1 = (r + 1) * cellH - halfSize;

  const v00 = values[r * w + c];
  const v10 = values[r * w + (c + 1)];
  const v01 = values[(r + 1) * w + c];
  const v11 = values[(r + 1) * w + (c + 1)];

  // Edge midpoints (approximate — avoids needing the level for interpolation)
  let px, pz, elev;
  switch (edgeIdx) {
    case 0: // bottom edge (v00 -> v10)
      px = (x0 + x1) / 2; pz = z0;
      elev = (v00 + v10) / 2;
      break;
    case 1: // right edge (v10 -> v11)
      px = x1; pz = (z0 + z1) / 2;
      elev = (v10 + v11) / 2;
      break;
    case 2: // top edge (v11 -> v01)
      px = (x0 + x1) / 2; pz = z1;
      elev = (v01 + v11) / 2;
      break;
    case 3: // left edge (v00 -> v01)
      px = x0; pz = (z0 + z1) / 2;
      elev = (v00 + v01) / 2;
      break;
    default:
      return null;
  }

  const norm = elevRange > 0 ? (elev - elevMin) / elevRange : 0;
  const py = norm * heightScale + 0.3; // slight offset above terrain
  return new THREE.Vector3(px, py, pz);
}


/* ── Cross-section profile chart (canvas 2D) ──────────────────────────── */

function drawProfileChart(canvas, profileData, colorMode) {
  if (!canvas || !profileData || profileData.length < 2) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  // Background
  ctx.fillStyle = "rgba(10, 12, 18, 0.95)";
  ctx.fillRect(0, 0, W, H);

  const elevs = profileData.map(p => p.elev);
  const minE = Math.min(...elevs);
  const maxE = Math.max(...elevs);
  const range = maxE - minE || 1;
  const totalDist = profileData[profileData.length - 1].dist;

  const pad = { top: 24, bottom: 28, left: 50, right: 16 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  // Grid lines
  ctx.strokeStyle = "rgba(255,255,255,0.08)";
  ctx.lineWidth = 1;
  const nGridY = 4;
  for (let i = 0; i <= nGridY; i++) {
    const y = pad.top + (plotH / nGridY) * i;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(W - pad.right, y); ctx.stroke();
    // Label
    const elev = maxE - (range / nGridY) * i;
    ctx.fillStyle = "#6B7280";
    ctx.font = "10px 'IBM Plex Mono', monospace";
    ctx.textAlign = "right";
    ctx.fillText(`${elev.toFixed(1)}m`, pad.left - 6, y + 4);
  }

  // Distance labels
  ctx.textAlign = "center";
  const nGridX = 4;
  for (let i = 0; i <= nGridX; i++) {
    const x = pad.left + (plotW / nGridX) * i;
    const d = (totalDist / nGridX) * i;
    ctx.fillText(d >= 1000 ? `${(d / 1000).toFixed(1)}km` : `${d.toFixed(0)}m`, x, H - 6);
  }

  // Fill area under profile
  ctx.beginPath();
  ctx.moveTo(pad.left, pad.top + plotH);
  for (let i = 0; i < profileData.length; i++) {
    const x = pad.left + (profileData[i].dist / totalDist) * plotW;
    const y = pad.top + plotH - ((profileData[i].elev - minE) / range) * plotH;
    ctx.lineTo(x, y);
  }
  ctx.lineTo(pad.left + plotW, pad.top + plotH);
  ctx.closePath();
  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
  grad.addColorStop(0, "rgba(212, 160, 24, 0.25)");
  grad.addColorStop(1, "rgba(212, 160, 24, 0.02)");
  ctx.fillStyle = grad;
  ctx.fill();

  // Profile line
  ctx.beginPath();
  for (let i = 0; i < profileData.length; i++) {
    const x = pad.left + (profileData[i].dist / totalDist) * plotW;
    const y = pad.top + plotH - ((profileData[i].elev - minE) / range) * plotH;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = "#D4A018";
  ctx.lineWidth = 2;
  ctx.stroke();

  // Title
  ctx.fillStyle = "#D4A018";
  ctx.font = "bold 11px 'IBM Plex Mono', monospace";
  ctx.textAlign = "left";
  ctx.fillText("CROSS-SECTION", pad.left, 16);
  ctx.fillStyle = "#9CA3AF";
  ctx.font = "10px 'IBM Plex Mono', monospace";
  ctx.fillText(
    `  ${totalDist.toFixed(0)}m  |  ${minE.toFixed(1)}m - ${maxE.toFixed(1)}m  |  ${range.toFixed(1)}m range`,
    pad.left + 98, 16
  );
}


/* ═══════════════════════════════════════════════════════════════════════════
   Component
   ═══════════════════════════════════════════════════════════════════════════ */

const MODES = ["elevation", "slope", "aspect", "viewshed", "hydrology"];
const MODE_LABELS = {
  elevation: "Elevation",
  slope: "Slope",
  aspect: "Aspect",
  viewshed: "Viewshed/ZTV",
  hydrology: "Hydrology",
};

export default function TerrainTwin({
  lat = 52.0,
  lon = -1.5,
  zoom: initialZoom = 14,
  placedAssets = [],
  onClose,
}) {
  const containerRef = useRef(null);
  const rendererRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const terrainMeshRef = useRef(null);
  const contourGroupRef = useRef(null);
  const crossSectionLineRef = useRef(null);
  const crossSectionMarkersRef = useRef(null);
  const raycasterRef = useRef(new THREE.Raycaster());
  const mouseRef = useRef(new THREE.Vector2());
  const animFrameRef = useRef(null);
  const profileCanvasRef = useRef(null);

  // Data
  const [lidarData, setLidarData] = useState(null);
  const [analysisData, setAnalysisData] = useState(null);
  const [viewshedData, setViewshedData] = useState(null);
  const [hydrologyData, setHydrologyData] = useState(null);

  // UI state
  const [loading, setLoading] = useState(true);
  const [loadingMsg, setLoadingMsg] = useState("Fetching LiDAR terrain data...");
  const [error, setError] = useState(null);
  const [colorMode, setColorMode] = useState("elevation");
  const [showContours, setShowContours] = useState(true);
  const [showStats, setShowStats] = useState(true);
  const [exaggeration, setExaggeration] = useState(1.5);
  const [crossSectionMode, setCrossSectionMode] = useState(false);
  const [crossSectionPoints, setCrossSectionPoints] = useState([]);
  const [profileData, setProfileData] = useState(null);
  const [hoverInfo, setHoverInfo] = useState(null);

  // Computed analysis arrays (cached)
  const computed = useRef({
    flatValues: null,
    w: 0, h: 0,
    resolution: 2,
    elevMin: 0, elevMax: 0, elevRange: 0,
    slope: null,
    aspect: null,
    viewshed: null,
    twi: null,
    flowAcc: null,
  });


  /* ── Fetch data on mount ────────────────────────────────────────────── */
  useEffect(() => {
    let cancelled = false;

    async function fetchData() {
      try {
        setLoadingMsg("Fetching LiDAR terrain data...");
        const lidarRes = await fetch("/api/terrain/lidar", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lat, lon, radius_m: 500, resolution_m: 2 }),
        });
        const lidar = await lidarRes.json();
        if (cancelled) return;

        if (lidar.error) {
          setError(lidar.error);
          setLoading(false);
          return;
        }
        setLidarData(lidar);

        // Fetch analysis in parallel
        setLoadingMsg("Running terrain analysis...");
        const [analyseRes, viewshedRes, hydroRes] = await Promise.allSettled([
          fetch("/api/terrain/analyse", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lat, lon, radius_m: 500 }),
          }).then(r => r.json()),
          fetch("/api/terrain/viewshed", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lat, lon, target_height_m: 3, radius_m: 500 }),
          }).then(r => r.json()),
          fetch("/api/terrain/hydrology", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lat, lon, radius_m: 500 }),
          }).then(r => r.json()),
        ]);

        if (cancelled) return;
        if (analyseRes.status === "fulfilled") setAnalysisData(analyseRes.value);
        if (viewshedRes.status === "fulfilled") setViewshedData(viewshedRes.value);
        if (hydroRes.status === "fulfilled") setHydrologyData(hydroRes.value);

        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(`Failed to fetch terrain data: ${err.message}`);
          setLoading(false);
        }
      }
    }

    fetchData();
    return () => { cancelled = true; };
  }, [lat, lon]);


  /* ── Precompute analysis arrays when LiDAR data arrives ─────────────── */
  useEffect(() => {
    if (!lidarData?.heightmap?.values) return;
    const hm = lidarData.heightmap;
    const w = hm.width;
    const h = hm.height;
    const flatValues = hm.values.flat();
    const resolution = hm.resolution_m || 2;

    let vMin = Infinity, vMax = -Infinity;
    for (const v of flatValues) {
      if (v != null) {
        if (v < vMin) vMin = v;
        if (v > vMax) vMax = v;
      }
    }

    const c = computed.current;
    c.flatValues = flatValues;
    c.w = w;
    c.h = h;
    c.resolution = resolution;
    c.elevMin = vMin;
    c.elevMax = vMax;
    c.elevRange = vMax - vMin || 1;
    c.slope = computeSlope(flatValues, w, h, resolution);
    c.aspect = computeAspect(flatValues, w, h, resolution);
    c.viewshed = computeViewshed(flatValues, w, h);
    const hydro = computeTWI(flatValues, w, h, resolution);
    c.twi = hydro.twi;
    c.flowAcc = hydro.flowAcc;
  }, [lidarData]);


  /* ── Initialize Three.js scene ──────────────────────────────────────── */
  useEffect(() => {
    if (!containerRef.current || loading || error) return;

    // Scene
    const scene = new THREE.Scene();
    sceneRef.current = scene;
    buildSkyGradient(scene);
    buildFog(scene);
    setupLighting(scene);

    // Camera
    const rect = containerRef.current.getBoundingClientRect();
    const camera = new THREE.PerspectiveCamera(50, rect.width / rect.height, 0.5, 2000);
    camera.position.set(80, 100, 120);
    camera.lookAt(0, 0, 0);
    cameraRef.current = camera;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(rect.width, rect.height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    containerRef.current.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    // Controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.minDistance = 20;
    controls.maxDistance = 400;
    controls.target.set(0, 5, 0);
    controlsRef.current = controls;

    // Ground plane (far ground)
    const groundGeom = new THREE.PlaneGeometry(1200, 1200);
    groundGeom.rotateX(-Math.PI / 2);
    const ground = new THREE.Mesh(groundGeom, new THREE.MeshStandardMaterial({
      color: 0x3a5a30, roughness: 0.95, metalness: 0,
    }));
    ground.position.y = -0.5;
    ground.receiveShadow = true;
    scene.add(ground);

    // Grid helper
    const grid = new THREE.GridHelper(200, 40, 0x556655, 0x445544);
    grid.position.y = 0.02;
    grid.material.opacity = 0.1;
    grid.material.transparent = true;
    scene.add(grid);

    // Compass rose
    const compassGroup = buildCompassRose();
    compassGroup.position.set(85, 0.5, 85);
    scene.add(compassGroup);

    // Site marker at centre
    const markerGeom = new THREE.ConeGeometry(1.5, 4, 4);
    const marker = new THREE.Mesh(markerGeom, new THREE.MeshStandardMaterial({
      color: 0xd4a018, emissive: 0xd4a018, emissiveIntensity: 0.3,
    }));
    marker.position.set(0, 35, 0);
    marker.rotation.x = Math.PI;
    scene.add(marker);

    // Animation loop
    function animate() {
      animFrameRef.current = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    // Resize handler
    const onResize = () => {
      const r = containerRef.current?.getBoundingClientRect();
      if (!r) return;
      camera.aspect = r.width / r.height;
      camera.updateProjectionMatrix();
      renderer.setSize(r.width, r.height);
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      controls.dispose();
      renderer.dispose();
      if (containerRef.current && renderer.domElement.parentNode === containerRef.current) {
        containerRef.current.removeChild(renderer.domElement);
      }
    };
  }, [loading, error]);


  /* ── Build/rebuild terrain mesh when data or colorMode changes ──────── */
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene || !lidarData?.heightmap?.values) return;

    const c = computed.current;
    if (!c.flatValues) return;

    // Remove old terrain mesh
    if (terrainMeshRef.current) {
      scene.remove(terrainMeshRef.current);
      terrainMeshRef.current.geometry.dispose();
      terrainMeshRef.current.material.dispose();
    }

    const { flatValues, w, h, elevMin, elevRange } = c;
    const meshSize = 200;
    const heightScale = Math.min(60, Math.max(20, elevRange * exaggeration));

    // Build plane geometry
    const geom = new THREE.PlaneGeometry(meshSize, meshSize, w - 1, h - 1);
    geom.rotateX(-Math.PI / 2);
    const pos = geom.attributes.position;
    const colors = new Float32Array(pos.count * 3);

    // Compute max values for normalization
    let maxSlope = 0;
    if (c.slope) for (const s of c.slope) if (s > maxSlope) maxSlope = s;
    maxSlope = Math.max(maxSlope, 35); // cap at 35 degrees for color scale

    let twiMin = Infinity, twiMax = -Infinity;
    if (c.twi) {
      for (const t of c.twi) {
        if (t < twiMin) twiMin = t;
        if (t > twiMax) twiMax = t;
      }
    }
    const twiRange = twiMax - twiMin || 1;

    for (let i = 0; i < pos.count; i++) {
      const val = flatValues[i] ?? elevMin;
      const norm = elevRange > 0 ? (val - elevMin) / elevRange : 0;
      pos.setY(i, norm * heightScale);

      let col;
      switch (colorMode) {
        case "elevation":
          col = sampleRamp(ELEV_RAMP, norm);
          break;
        case "slope":
          col = c.slope
            ? sampleRamp(SLOPE_RAMP, Math.min(1, c.slope[i] / maxSlope))
            : sampleRamp(ELEV_RAMP, norm);
          break;
        case "aspect":
          col = c.aspect
            ? aspectToColor(c.aspect[i])
            : sampleRamp(ELEV_RAMP, norm);
          break;
        case "viewshed":
          if (c.viewshed) {
            col = c.viewshed[i] ? VIS_COLOR : HIDDEN_COLOR;
            // Blend with slight elevation tint for depth
            const elevTint = sampleRamp(ELEV_RAMP, norm);
            col = [
              col[0] * 0.7 + elevTint[0] * 0.3,
              col[1] * 0.7 + elevTint[1] * 0.3,
              col[2] * 0.7 + elevTint[2] * 0.3,
            ];
          } else {
            col = sampleRamp(ELEV_RAMP, norm);
          }
          break;
        case "hydrology":
          if (c.twi) {
            const tNorm = (c.twi[i] - twiMin) / twiRange;
            col = sampleRamp(HYDRO_RAMP, tNorm);
            // Highlight high flow accumulation
            if (c.flowAcc && c.flowAcc[i] > 100) {
              const flowIntensity = Math.min(1, Math.log10(c.flowAcc[i]) / 4);
              col = [
                col[0] * (1 - flowIntensity * 0.5),
                col[1] * (1 - flowIntensity * 0.3),
                col[2] * (1 - flowIntensity * 0.1) + flowIntensity * 0.3,
              ];
            }
          } else {
            col = sampleRamp(ELEV_RAMP, norm);
          }
          break;
        default:
          col = sampleRamp(ELEV_RAMP, norm);
      }

      colors[i * 3] = col[0];
      colors[i * 3 + 1] = col[1];
      colors[i * 3 + 2] = col[2];
    }

    geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geom.computeVertexNormals();

    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.82,
      metalness: 0.02,
      side: THREE.DoubleSide,
      flatShading: false,
    });

    const mesh = new THREE.Mesh(geom, mat);
    mesh.receiveShadow = true;
    mesh.castShadow = true;
    mesh.name = "terrain";
    scene.add(mesh);
    terrainMeshRef.current = mesh;

    // Rebuild contours
    if (contourGroupRef.current) {
      scene.remove(contourGroupRef.current);
    }
    if (showContours) {
      const interval = elevRange > 50 ? 5 : elevRange > 20 ? 2 : 1;
      const contourGroup = buildContourLines(flatValues, w, h, meshSize, elevMin, elevRange, interval);
      scene.add(contourGroup);
      contourGroupRef.current = contourGroup;
    }

  }, [lidarData, colorMode, exaggeration, showContours]);


  /* ── Mouse interaction: hover info + cross-section clicks ──────────── */
  const handleCanvasClick = useCallback((e) => {
    if (!crossSectionMode || !terrainMeshRef.current || !cameraRef.current || !containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );

    const raycaster = raycasterRef.current;
    raycaster.setFromCamera(mouse, cameraRef.current);
    const hits = raycaster.intersectObject(terrainMeshRef.current);

    if (hits.length > 0) {
      const point = hits[0].point.clone();

      setCrossSectionPoints(prev => {
        const next = prev.length >= 2 ? [point] : [...prev, point];

        // Add marker sphere
        const scene = sceneRef.current;
        if (scene) {
          // Remove old markers
          if (crossSectionMarkersRef.current) {
            crossSectionMarkersRef.current.forEach(m => scene.remove(m));
          }
          const markers = [];
          for (const p of next) {
            const sphere = new THREE.Mesh(
              new THREE.SphereGeometry(1.5, 16, 16),
              new THREE.MeshStandardMaterial({ color: 0x00e5ff, emissive: 0x00e5ff, emissiveIntensity: 0.5 }),
            );
            sphere.position.copy(p);
            sphere.position.y += 1;
            scene.add(sphere);
            markers.push(sphere);
          }
          crossSectionMarkersRef.current = markers;

          // Draw line between points
          if (crossSectionLineRef.current) {
            scene.remove(crossSectionLineRef.current);
          }
          if (next.length === 2) {
            const lineGeom = new THREE.BufferGeometry().setFromPoints([
              new THREE.Vector3(next[0].x, next[0].y + 0.5, next[0].z),
              new THREE.Vector3(next[1].x, next[1].y + 0.5, next[1].z),
            ]);
            const line = new THREE.Line(lineGeom, new THREE.LineBasicMaterial({
              color: 0x00e5ff, linewidth: 2, transparent: true, opacity: 0.8,
            }));
            scene.add(line);
            crossSectionLineRef.current = line;

            // Compute profile
            computeProfile(next[0], next[1]);
          }
        }

        return next;
      });
    }
  }, [crossSectionMode]);

  // Compute cross-section profile from two 3D points
  const computeProfile = useCallback((p0, p1) => {
    const c = computed.current;
    if (!c.flatValues) return;

    const { flatValues, w, h, elevMin, elevRange } = c;
    const meshSize = 200;
    const halfSize = meshSize / 2;
    const heightScale = Math.min(60, Math.max(20, elevRange * exaggeration));

    const samples = 100;
    const profile = [];
    const totalDist3D = Math.sqrt((p1.x - p0.x) ** 2 + (p1.z - p0.z) ** 2);
    // Convert scene distance to real-world metres
    const realDist = totalDist3D / meshSize * (c.resolution * w);

    for (let i = 0; i <= samples; i++) {
      const t = i / samples;
      const sx = p0.x + (p1.x - p0.x) * t;
      const sz = p0.z + (p1.z - p0.z) * t;

      // Convert scene coords to grid coords
      const gc = ((sx + halfSize) / meshSize) * (w - 1);
      const gr = ((sz + halfSize) / meshSize) * (h - 1);

      // Bilinear interpolation
      const c0 = Math.floor(gc);
      const r0 = Math.floor(gr);
      const c1 = Math.min(c0 + 1, w - 1);
      const r1 = Math.min(r0 + 1, h - 1);
      const fc = gc - c0;
      const fr = gr - r0;

      const v00 = flatValues[r0 * w + c0] || 0;
      const v10 = flatValues[r0 * w + c1] || 0;
      const v01 = flatValues[r1 * w + c0] || 0;
      const v11 = flatValues[r1 * w + c1] || 0;

      const elev = v00 * (1 - fc) * (1 - fr) + v10 * fc * (1 - fr) + v01 * (1 - fc) * fr + v11 * fc * fr;

      profile.push({
        dist: realDist * t,
        elev,
      });
    }

    setProfileData(profile);
  }, [exaggeration]);

  // Mouse move for hover elevation
  const handleCanvasMouseMove = useCallback((e) => {
    if (!terrainMeshRef.current || !cameraRef.current || !containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );

    const raycaster = raycasterRef.current;
    raycaster.setFromCamera(mouse, cameraRef.current);
    const hits = raycaster.intersectObject(terrainMeshRef.current);

    if (hits.length > 0) {
      const point = hits[0].point;
      const c = computed.current;
      if (!c.flatValues) return;

      const { flatValues, w, h, elevMin, elevRange } = c;
      const meshSize = 200;
      const halfSize = meshSize / 2;

      // Convert scene coords to grid coords
      const gc = Math.round(((point.x + halfSize) / meshSize) * (w - 1));
      const gr = Math.round(((point.z + halfSize) / meshSize) * (h - 1));

      if (gc >= 0 && gc < w && gr >= 0 && gr < h) {
        const idx = gr * w + gc;
        const info = {
          elevation: flatValues[idx]?.toFixed(1) || "N/A",
          slope: c.slope ? c.slope[idx]?.toFixed(1) : "N/A",
          aspect: c.aspect ? c.aspect[idx]?.toFixed(0) : "N/A",
          twi: c.twi ? c.twi[idx]?.toFixed(1) : "N/A",
          visible: c.viewshed ? (c.viewshed[idx] ? "Yes" : "No") : "N/A",
          x: e.clientX,
          y: e.clientY,
        };
        setHoverInfo(info);
      }
    } else {
      setHoverInfo(null);
    }
  }, []);

  // Draw profile when data changes
  useEffect(() => {
    if (profileCanvasRef.current && profileData) {
      drawProfileChart(profileCanvasRef.current, profileData, colorMode);
    }
  }, [profileData, colorMode]);


  /* ── Keyboard shortcuts ─────────────────────────────────────────────── */
  useEffect(() => {
    const handler = (e) => {
      if (e.key === "Escape") {
        if (crossSectionMode) {
          setCrossSectionMode(false);
          setCrossSectionPoints([]);
          setProfileData(null);
          // Clean up scene markers
          const scene = sceneRef.current;
          if (scene) {
            if (crossSectionLineRef.current) scene.remove(crossSectionLineRef.current);
            if (crossSectionMarkersRef.current) crossSectionMarkersRef.current.forEach(m => scene.remove(m));
          }
        } else if (onClose) {
          onClose();
        }
      }
      // Number keys for mode switching
      const num = parseInt(e.key);
      if (num >= 1 && num <= 5) {
        setColorMode(MODES[num - 1]);
      }
      if (e.key === "c" || e.key === "C") {
        setShowContours(p => !p);
      }
      if (e.key === "x" || e.key === "X") {
        setCrossSectionMode(p => !p);
        setCrossSectionPoints([]);
        setProfileData(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [crossSectionMode, onClose]);


  /* ── Stats computation ──────────────────────────────────────────────── */
  const stats = useMemo(() => {
    if (!lidarData?.heightmap?.values) return null;
    const c = computed.current;
    if (!c.flatValues) return null;

    // Slope distribution
    const slopeBins = [0, 0, 0, 0, 0]; // <2, 2-5, 5-10, 10-20, 20+
    if (c.slope) {
      for (const s of c.slope) {
        if (s < 2) slopeBins[0]++;
        else if (s < 5) slopeBins[1]++;
        else if (s < 10) slopeBins[2]++;
        else if (s < 20) slopeBins[3]++;
        else slopeBins[4]++;
      }
      const total = c.slope.length;
      for (let i = 0; i < 5; i++) slopeBins[i] = Math.round(slopeBins[i] / total * 100);
    }

    // Aspect distribution (8 directions)
    const aspectBins = new Array(8).fill(0);
    if (c.aspect) {
      for (const a of c.aspect) {
        const idx = Math.round(((a % 360 + 360) % 360) / 45) % 8;
        aspectBins[idx]++;
      }
      const total = c.aspect.length;
      for (let i = 0; i < 8; i++) aspectBins[i] = Math.round(aspectBins[i] / total * 100);
    }

    // Viewshed
    let visPct = 0;
    if (c.viewshed) {
      let visCount = 0;
      for (const v of c.viewshed) if (v) visCount++;
      visPct = Math.round(visCount / c.viewshed.length * 100);
    }

    // TWI stats
    let twiMean = 0, waterloggedPct = 0;
    if (c.twi && c.slope) {
      let sum = 0;
      let wlCount = 0;
      for (let i = 0; i < c.twi.length; i++) {
        sum += c.twi[i];
        if (c.twi[i] > 12 && c.slope[i] < 2) wlCount++;
      }
      twiMean = sum / c.twi.length;
      waterloggedPct = Math.round(wlCount / c.twi.length * 100);
    }

    return {
      elevMin: c.elevMin,
      elevMax: c.elevMax,
      elevRange: c.elevRange,
      elevMean: c.flatValues.reduce((a, b) => a + (b || 0), 0) / c.flatValues.length,
      slopeBins,
      aspectBins,
      visPct,
      twiMean,
      waterloggedPct,
      source: lidarData.source || "Unknown",
      gridW: c.w,
      gridH: c.h,
      resolution: c.resolution,
      terrainScore: analysisData?.terrain_score,
      flatnessScore: analysisData?.flatness_score,
      slopeClass: analysisData?.slope?.suitability,
      aspectClass: analysisData?.aspect?.suitability,
      drainageRisk: hydrologyData?.drainage_risk,
    };
  }, [lidarData, analysisData, hydrologyData]);


  /* ── Render ─────────────────────────────────────────────────────────── */
  return (
    <div className="digital-twin-overlay">
      {/* ── Toolbar ── */}
      <div className="twin-toolbar" style={{ background: "rgba(10, 12, 18, 0.95)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button className="twin-close-btn" onClick={onClose} title="Close (Esc)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
          <span style={{ fontWeight: 700, fontSize: 13, color: "#D4A018", letterSpacing: 1 }}>
            TERRAIN TWIN
          </span>
          <span style={{ fontSize: 11, color: "#9CA3AF" }}>
            {lat.toFixed(4)}N, {Math.abs(lon).toFixed(4)}{lon < 0 ? "W" : "E"}
          </span>
          {stats && (
            <span style={{ fontSize: 10, color: "#6B7280", marginLeft: 4 }}>
              {stats.source} | {stats.gridW}x{stats.gridH} @ {stats.resolution}m
            </span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {/* Analysis mode buttons */}
          <div style={{ display: "flex", gap: 2 }}>
            {MODES.map((mode, idx) => (
              <button
                key={mode}
                onClick={() => setColorMode(mode)}
                title={`${MODE_LABELS[mode]} (${idx + 1})`}
                style={{
                  padding: "3px 10px",
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: 0.5,
                  border: `1px solid ${colorMode === mode ? "rgba(212,160,24,0.6)" : "rgba(255,255,255,0.1)"}`,
                  borderRadius: 3,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  background: colorMode === mode ? "rgba(212,160,24,0.2)" : "transparent",
                  color: colorMode === mode ? "#D4A018" : "#6B7280",
                  transition: "all 0.15s",
                }}
              >
                {MODE_LABELS[mode]}
              </button>
            ))}
          </div>

          {/* Exaggeration slider */}
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ fontSize: 9, color: "#6B7280", fontWeight: 600 }}>VERT</span>
            <input
              type="range" min="0.5" max="4" step="0.1" value={exaggeration}
              onChange={(e) => setExaggeration(parseFloat(e.target.value))}
              style={{ width: 60, accentColor: "#D4A018" }}
            />
            <span style={{ fontSize: 10, color: "#9CA3AF", minWidth: 24, fontFamily: "'IBM Plex Mono', monospace" }}>
              {exaggeration.toFixed(1)}x
            </span>
          </div>

          {/* Toggle buttons */}
          <button
            onClick={() => setShowContours(p => !p)}
            title="Contour lines (C)"
            style={{
              padding: "3px 8px", fontSize: 10, fontWeight: 700,
              border: `1px solid ${showContours ? "rgba(212,160,24,0.4)" : "rgba(255,255,255,0.1)"}`,
              borderRadius: 3, cursor: "pointer", fontFamily: "inherit",
              background: showContours ? "rgba(212,160,24,0.15)" : "transparent",
              color: showContours ? "#D4A018" : "#6B7280",
            }}
          >
            CONTOURS
          </button>

          <button
            onClick={() => {
              setCrossSectionMode(p => !p);
              setCrossSectionPoints([]);
              setProfileData(null);
            }}
            title="Cross-section tool (X)"
            style={{
              padding: "3px 8px", fontSize: 10, fontWeight: 700,
              border: `1px solid ${crossSectionMode ? "#00e5ff" : "rgba(255,255,255,0.1)"}`,
              borderRadius: 3, cursor: "pointer", fontFamily: "inherit",
              background: crossSectionMode ? "rgba(0,229,255,0.15)" : "transparent",
              color: crossSectionMode ? "#00e5ff" : "#6B7280",
              display: "flex", alignItems: "center", gap: 4,
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 20L20 4" />
              <circle cx="4" cy="20" r="2" />
              <circle cx="20" cy="4" r="2" />
            </svg>
            SECTION
          </button>

          <button
            onClick={() => setShowStats(p => !p)}
            title="Stats panel"
            style={{
              padding: "3px 8px", fontSize: 10, fontWeight: 700,
              border: `1px solid ${showStats ? "rgba(212,160,24,0.4)" : "rgba(255,255,255,0.1)"}`,
              borderRadius: 3, cursor: "pointer", fontFamily: "inherit",
              background: showStats ? "rgba(212,160,24,0.15)" : "transparent",
              color: showStats ? "#D4A018" : "#6B7280",
            }}
          >
            STATS
          </button>

          {/* Screenshot */}
          <button
            onClick={() => {
              const renderer = rendererRef.current;
              if (!renderer) return;
              renderer.render(sceneRef.current, cameraRef.current);
              const url = renderer.domElement.toDataURL("image/png");
              const a = document.createElement("a");
              a.href = url;
              a.download = `terrain-twin-${lat.toFixed(4)}-${lon.toFixed(4)}.png`;
              a.click();
            }}
            title="Screenshot"
            style={{
              padding: "4px 8px",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 3, cursor: "pointer", background: "transparent", color: "#6B7280",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z" />
              <circle cx="12" cy="13" r="4" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── Three.js canvas container ── */}
      <div
        ref={containerRef}
        className="twin-canvas"
        style={{ cursor: crossSectionMode ? "crosshair" : "grab" }}
        onClick={handleCanvasClick}
        onMouseMove={handleCanvasMouseMove}
      />

      {/* ── Loading overlay ── */}
      {loading && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center",
          justifyContent: "center", background: "rgba(10, 12, 18, 0.9)", zIndex: 20,
        }}>
          <div style={{ textAlign: "center" }}>
            <div style={{
              width: 40, height: 40, border: "3px solid rgba(212,160,24,0.3)",
              borderTopColor: "#D4A018", borderRadius: "50%",
              animation: "spin 0.8s linear infinite", margin: "0 auto 16px",
            }} />
            <div style={{ color: "#D4A018", fontSize: 13, fontWeight: 600, letterSpacing: 1 }}>
              LOADING TERRAIN
            </div>
            <div style={{ color: "#6B7280", fontSize: 11, marginTop: 4 }}>
              {loadingMsg}
            </div>
          </div>
        </div>
      )}

      {/* ── Error overlay ── */}
      {error && (
        <div style={{
          position: "absolute", inset: 0, display: "flex", alignItems: "center",
          justifyContent: "center", background: "rgba(10, 12, 18, 0.95)", zIndex: 20,
        }}>
          <div style={{ textAlign: "center", maxWidth: 400 }}>
            <div style={{ color: "#f5222d", fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
              Terrain Load Error
            </div>
            <div style={{ color: "#9CA3AF", fontSize: 12, lineHeight: 1.5 }}>{error}</div>
            <button
              onClick={onClose}
              style={{
                marginTop: 16, padding: "8px 20px", background: "rgba(245,34,45,0.15)",
                border: "1px solid rgba(245,34,45,0.3)", borderRadius: 4,
                color: "#f5222d", cursor: "pointer", fontSize: 12, fontWeight: 600,
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* ── Cross-section mode HUD ── */}
      {crossSectionMode && (
        <div style={{
          position: "absolute", top: 60, left: "50%", transform: "translateX(-50%)",
          background: "rgba(0, 20, 30, 0.85)", backdropFilter: "blur(10px)",
          border: "1px solid rgba(0, 229, 255, 0.3)", borderRadius: 6,
          padding: "8px 16px", zIndex: 15, display: "flex", alignItems: "center", gap: 12,
        }}>
          <div style={{
            width: 8, height: 8, borderRadius: "50%", background: "#00e5ff",
            boxShadow: "0 0 8px rgba(0,229,255,0.6)",
          }} />
          <span style={{ color: "#00e5ff", fontSize: 12, fontWeight: 600 }}>
            {crossSectionPoints.length === 0
              ? "Click terrain to set start point"
              : crossSectionPoints.length === 1
                ? "Click terrain to set end point"
                : "Cross-section computed -- click to start new"}
          </span>
          <button
            onClick={() => {
              setCrossSectionMode(false);
              setCrossSectionPoints([]);
              setProfileData(null);
            }}
            style={{ background: "none", border: "none", color: "#6B7280", cursor: "pointer", fontSize: 14, padding: "0 4px" }}
          >
            x
          </button>
        </div>
      )}

      {/* ── Cross-section profile chart ── */}
      {profileData && (
        <div style={{
          position: "absolute", bottom: 16, left: showStats ? 290 : 16, right: 16,
          height: 160, zIndex: 15, borderRadius: 8, overflow: "hidden",
          border: "1px solid rgba(255,255,255,0.1)",
        }}>
          <canvas
            ref={profileCanvasRef}
            width={800}
            height={160}
            style={{ width: "100%", height: "100%" }}
          />
        </div>
      )}

      {/* ── Hover tooltip ── */}
      {hoverInfo && (
        <div style={{
          position: "fixed", left: hoverInfo.x + 16, top: hoverInfo.y - 10,
          background: "rgba(10, 12, 18, 0.9)", backdropFilter: "blur(8px)",
          border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6,
          padding: "6px 10px", zIndex: 20, pointerEvents: "none",
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, lineHeight: 1.6,
        }}>
          <div style={{ color: "#D4A018", fontWeight: 700 }}>Elev: {hoverInfo.elevation}m</div>
          <div style={{ color: "#9CA3AF" }}>Slope: {hoverInfo.slope}deg</div>
          <div style={{ color: "#9CA3AF" }}>Aspect: {hoverInfo.aspect}deg</div>
          <div style={{ color: "#9CA3AF" }}>TWI: {hoverInfo.twi}</div>
          <div style={{ color: "#9CA3AF" }}>Visible: {hoverInfo.visible}</div>
        </div>
      )}

      {/* ── Stats panel ── */}
      {showStats && stats && (
        <div style={{
          position: "absolute", top: 56, left: 8, bottom: profileData ? 184 : 8,
          width: 264, background: "rgba(10, 12, 18, 0.92)", backdropFilter: "blur(12px)",
          border: "1px solid rgba(255,255,255,0.08)", borderRadius: 8,
          padding: "12px 14px", zIndex: 15, overflowY: "auto",
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 10,
        }}>
          {/* Terrain Score */}
          {stats.terrainScore != null && (
            <div style={{ marginBottom: 14, textAlign: "center" }}>
              <div style={{ fontSize: 9, color: "#6B7280", fontWeight: 700, letterSpacing: 1, marginBottom: 4 }}>
                TERRAIN SCORE
              </div>
              <div style={{
                fontSize: 32, fontWeight: 800,
                color: stats.terrainScore >= 70 ? "#4caf50" : stats.terrainScore >= 40 ? "#ff9800" : "#f44336",
                lineHeight: 1,
              }}>
                {stats.terrainScore}
              </div>
              <div style={{ fontSize: 9, color: "#6B7280", marginTop: 2 }}>/ 100</div>
            </div>
          )}

          {/* Elevation */}
          <StatSection title="ELEVATION">
            <StatRow label="Min" value={`${stats.elevMin.toFixed(1)}m AOD`} />
            <StatRow label="Max" value={`${stats.elevMax.toFixed(1)}m AOD`} />
            <StatRow label="Mean" value={`${stats.elevMean.toFixed(1)}m AOD`} />
            <StatRow label="Range" value={`${stats.elevRange.toFixed(1)}m`} />
          </StatSection>

          {/* Slope Distribution */}
          <StatSection title="SLOPE DISTRIBUTION">
            <div style={{ display: "flex", gap: 2, marginBottom: 4, height: 40 }}>
              {["<2\u00b0", "2-5\u00b0", "5-10\u00b0", "10-20\u00b0", ">20\u00b0"].map((label, i) => (
                <div key={label} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                  <div style={{
                    flex: 1, width: "100%", display: "flex", alignItems: "flex-end",
                  }}>
                    <div style={{
                      width: "100%", borderRadius: "2px 2px 0 0",
                      height: `${Math.max(2, stats.slopeBins[i])}%`,
                      background: [
                        "rgba(76,175,80,0.7)", "rgba(139,195,74,0.7)",
                        "rgba(255,235,59,0.7)", "rgba(255,152,0,0.7)", "rgba(244,67,54,0.7)"
                      ][i],
                    }} />
                  </div>
                  <div style={{ fontSize: 8, color: "#6B7280", marginTop: 2 }}>{label}</div>
                  <div style={{ fontSize: 8, color: "#9CA3AF" }}>{stats.slopeBins[i]}%</div>
                </div>
              ))}
            </div>
            {stats.slopeClass && (
              <div style={{
                fontSize: 9, color: stats.slopeClass === "excellent" ? "#4caf50" : stats.slopeClass === "good" ? "#8bc34a" : stats.slopeClass === "moderate" ? "#ff9800" : "#f44336",
                fontWeight: 600, textTransform: "uppercase", marginTop: 2,
              }}>
                {stats.slopeClass}
              </div>
            )}
          </StatSection>

          {/* Aspect Rose */}
          <StatSection title="ASPECT ROSE">
            <div style={{ position: "relative", width: 100, height: 100, margin: "0 auto" }}>
              <AspectRose bins={stats.aspectBins} />
            </div>
            {stats.aspectClass && (
              <div style={{
                fontSize: 9, textAlign: "center", marginTop: 4, fontWeight: 600,
                color: stats.aspectClass === "excellent" ? "#4caf50" : stats.aspectClass === "good" ? "#8bc34a" : "#ff9800",
                textTransform: "uppercase",
              }}>
                Solar orientation: {stats.aspectClass}
              </div>
            )}
          </StatSection>

          {/* Viewshed */}
          <StatSection title="VIEWSHED / ZTV">
            <StatRow label="Visible area" value={`${stats.visPct}%`} />
            <div style={{
              height: 4, borderRadius: 2, background: "rgba(255,255,255,0.08)", marginTop: 4, overflow: "hidden",
            }}>
              <div style={{
                height: "100%", borderRadius: 2, width: `${stats.visPct}%`,
                background: stats.visPct < 30 ? "#4caf50" : stats.visPct < 60 ? "#ff9800" : "#f44336",
              }} />
            </div>
            <div style={{ fontSize: 9, color: "#6B7280", marginTop: 2 }}>
              {stats.visPct < 30 ? "Low visual impact" : stats.visPct < 60 ? "Moderate visual impact" : "High visual impact"}
            </div>
          </StatSection>

          {/* Hydrology */}
          <StatSection title="HYDROLOGY">
            <StatRow label="Mean TWI" value={stats.twiMean.toFixed(1)} />
            <StatRow label="Waterlogged" value={`${stats.waterloggedPct}%`} />
            {stats.drainageRisk && (
              <div style={{
                fontSize: 9, fontWeight: 600, textTransform: "uppercase", marginTop: 2,
                color: stats.drainageRisk === "low" ? "#4caf50" : stats.drainageRisk === "medium" ? "#ff9800" : "#f44336",
              }}>
                Drainage risk: {stats.drainageRisk}
              </div>
            )}
          </StatSection>

          {/* Flatness Score */}
          {stats.flatnessScore != null && (
            <StatSection title="FLATNESS">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: "50%", display: "flex", alignItems: "center",
                  justifyContent: "center", fontSize: 14, fontWeight: 800,
                  border: `2px solid ${stats.flatnessScore >= 70 ? "#4caf50" : stats.flatnessScore >= 40 ? "#ff9800" : "#f44336"}`,
                  color: stats.flatnessScore >= 70 ? "#4caf50" : stats.flatnessScore >= 40 ? "#ff9800" : "#f44336",
                }}>
                  {stats.flatnessScore}
                </div>
                <div style={{ fontSize: 9, color: "#9CA3AF", lineHeight: 1.4 }}>
                  {stats.flatnessScore >= 70 ? "Minimal grading needed" : stats.flatnessScore >= 40 ? "Some earthworks needed" : "Significant grading required"}
                </div>
              </div>
            </StatSection>
          )}

          {/* Color legend */}
          <StatSection title={`LEGEND: ${MODE_LABELS[colorMode].toUpperCase()}`}>
            <ColorLegend mode={colorMode} elevMin={stats.elevMin} elevMax={stats.elevMax} />
          </StatSection>
        </div>
      )}

      {/* ── Coordinate display ── */}
      <div style={{
        position: "absolute", bottom: 8, right: 8,
        background: "rgba(10, 12, 18, 0.7)", borderRadius: 4, padding: "4px 10px",
        zIndex: 10, display: "flex", alignItems: "center", gap: 12,
      }}>
        <span style={{ fontSize: 10, color: "#6B7280", fontFamily: "'IBM Plex Mono', monospace" }}>
          {lat.toFixed(5)}, {lon.toFixed(5)}
        </span>
        <span style={{ fontSize: 10, color: "#4B5563" }}>|</span>
        <span style={{ fontSize: 10, color: "#6B7280" }}>
          Keys: 1-5 modes | C contours | X section | Esc close
        </span>
      </div>

      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}


/* ── Sub-components ────────────────────────────────────────────────────── */

function StatSection({ title, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{
        fontSize: 9, fontWeight: 700, color: "#6B7280", letterSpacing: 1,
        marginBottom: 4, paddingBottom: 3,
        borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function StatRow({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "1px 0" }}>
      <span style={{ color: "#9CA3AF" }}>{label}</span>
      <span style={{ color: "#E5E7EB", fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function AspectRose({ bins }) {
  const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const maxBin = Math.max(...bins, 1);
  const cx = 50, cy = 50, maxR = 38;

  return (
    <svg width="100" height="100" viewBox="0 0 100 100">
      {/* Grid circles */}
      {[0.33, 0.66, 1.0].map((f, i) => (
        <circle key={i} cx={cx} cy={cy} r={maxR * f}
          fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="0.5" />
      ))}
      {/* Direction lines */}
      {dirs.map((d, i) => {
        const angle = (i * 45 - 90) * Math.PI / 180;
        return (
          <line key={d}
            x1={cx} y1={cy}
            x2={cx + Math.cos(angle) * maxR} y2={cy + Math.sin(angle) * maxR}
            stroke="rgba(255,255,255,0.06)" strokeWidth="0.5"
          />
        );
      })}
      {/* Rose petals */}
      <polygon
        points={bins.map((b, i) => {
          const angle = (i * 45 - 90) * Math.PI / 180;
          const r = (b / maxBin) * maxR;
          return `${cx + Math.cos(angle) * r},${cy + Math.sin(angle) * r}`;
        }).join(" ")}
        fill="rgba(212,160,24,0.3)"
        stroke="#D4A018"
        strokeWidth="1"
      />
      {/* South highlight */}
      {(() => {
        const sIdx = 4; // S
        const angle = (sIdx * 45 - 90) * Math.PI / 180;
        const r = (bins[sIdx] / maxBin) * maxR;
        return (
          <circle cx={cx + Math.cos(angle) * r} cy={cy + Math.sin(angle) * r}
            r="3" fill="#ff9800" opacity="0.8" />
        );
      })()}
      {/* Labels */}
      {dirs.map((d, i) => {
        const angle = (i * 45 - 90) * Math.PI / 180;
        const lr = maxR + 8;
        return (
          <text key={`l${d}`}
            x={cx + Math.cos(angle) * lr} y={cy + Math.sin(angle) * lr + 3}
            fill={d === "S" ? "#ff9800" : "#6B7280"} fontSize="7"
            fontWeight={d === "S" ? "700" : "400"} textAnchor="middle"
          >
            {d}
          </text>
        );
      })}
    </svg>
  );
}

function ColorLegend({ mode, elevMin, elevMax }) {
  const barStyle = {
    height: 8, borderRadius: 4, marginBottom: 4, width: "100%",
  };

  let gradient, labels;
  switch (mode) {
    case "elevation":
      gradient = "linear-gradient(to right, #295c38, #3d8c47, #738c4d, #b8b859, #a6804d, #8c6652, #b3a699, #ebebeb)";
      labels = [`${elevMin.toFixed(0)}m`, `${elevMax.toFixed(0)}m`];
      break;
    case "slope":
      gradient = "linear-gradient(to right, #33a854, #66bf4d, #d9d933, #f2a61a, #e64d1a, #bf1a1a)";
      labels = ["0\u00b0", "35\u00b0+"];
      break;
    case "aspect":
      gradient = "linear-gradient(to right, #4d73bf, #40997a, #4db366, #b3b340, #e68c26, #d95933, #a64089, #6659b3, #4d73bf)";
      labels = ["N", "E", "S", "W", "N"];
      break;
    case "viewshed":
      gradient = "linear-gradient(to right, #1e1e26, #33d959)";
      labels = ["Hidden", "Visible"];
      break;
    case "hydrology":
      gradient = "linear-gradient(to right, #b89e6b, #809959, #4d8c80, #3373b3, #264dbf, #1a2699)";
      labels = ["Dry", "Wet"];
      break;
    default:
      gradient = "linear-gradient(to right, #333, #fff)";
      labels = ["Low", "High"];
  }

  return (
    <div>
      <div style={{ ...barStyle, background: gradient }} />
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        {labels.map((l, i) => (
          <span key={i} style={{ fontSize: 8, color: "#9CA3AF" }}>{l}</span>
        ))}
      </div>
    </div>
  );
}

function buildCompassRose() {
  const group = new THREE.Group();
  group.name = "compass";

  // N arrow
  const arrowGeom = new THREE.ConeGeometry(1.5, 6, 3);
  const nArrow = new THREE.Mesh(arrowGeom, new THREE.MeshStandardMaterial({
    color: 0xf44336, emissive: 0xf44336, emissiveIntensity: 0.2,
  }));
  nArrow.position.set(0, 3, -4);
  group.add(nArrow);

  // S arrow
  const sArrow = new THREE.Mesh(arrowGeom, new THREE.MeshStandardMaterial({
    color: 0x9e9e9e,
  }));
  sArrow.position.set(0, 3, 4);
  sArrow.rotation.x = Math.PI;
  group.add(sArrow);

  // Circle base
  const ringGeom = new THREE.RingGeometry(6, 7, 32);
  ringGeom.rotateX(-Math.PI / 2);
  const ring = new THREE.Mesh(ringGeom, new THREE.MeshBasicMaterial({
    color: 0xffffff, transparent: true, opacity: 0.15, side: THREE.DoubleSide,
  }));
  ring.position.y = 0.1;
  group.add(ring);

  return group;
}

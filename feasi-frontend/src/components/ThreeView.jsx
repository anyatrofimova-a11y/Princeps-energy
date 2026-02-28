import React, { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const SIZE = 240;

/**
 * Flatten a 2D array (from ST_DumpValues valarray) into a 1D array.
 * Handles both [[row], [row], ...] and already-flat [v, v, ...] inputs.
 */
function flattenValues(values) {
  if (!values || values.length === 0) return [];
  if (Array.isArray(values[0])) return values.flat();
  return values;
}

/**
 * Generate a normal-map DataTexture from a heightmap grid using Sobel-style dx/dy.
 */
function generateNormalMap(flat, w, h) {
  const data = new Uint8Array(w * h * 4);
  const val = (r, c) => flat[Math.min(r, h - 1) * w + Math.min(c, w - 1)] ?? 0;
  const strength = 2.0;

  for (let r = 0; r < h; r++) {
    for (let c = 0; c < w; c++) {
      const tl = val(Math.max(r - 1, 0), Math.max(c - 1, 0));
      const t  = val(Math.max(r - 1, 0), c);
      const tr = val(Math.max(r - 1, 0), Math.min(c + 1, w - 1));
      const l  = val(r, Math.max(c - 1, 0));
      const ri = val(r, Math.min(c + 1, w - 1));
      const bl = val(Math.min(r + 1, h - 1), Math.max(c - 1, 0));
      const b  = val(Math.min(r + 1, h - 1), c);
      const br = val(Math.min(r + 1, h - 1), Math.min(c + 1, w - 1));

      const dx = (tr + 2 * ri + br) - (tl + 2 * l + bl);
      const dy = (bl + 2 * b + br) - (tl + 2 * t + tr);

      const nx = -dx * strength;
      const ny = -dy * strength;
      const nz = 1.0;
      const len = Math.sqrt(nx * nx + ny * ny + nz * nz);

      const idx = (r * w + c) * 4;
      data[idx]     = Math.round(((nx / len) * 0.5 + 0.5) * 255);
      data[idx + 1] = Math.round(((ny / len) * 0.5 + 0.5) * 255);
      data[idx + 2] = Math.round(((nz / len) * 0.5 + 0.5) * 255);
      data[idx + 3] = 255;
    }
  }

  const tex = new THREE.DataTexture(data, w, h, THREE.RGBAFormat);
  tex.needsUpdate = true;
  return tex;
}

/**
 * Load a 3x3 grid of ArcGIS satellite tiles and composite into a single CanvasTexture.
 * Returns a Promise<THREE.CanvasTexture | null>.
 */
function loadSatelliteTexture(tile) {
  if (!tile?.url) return Promise.resolve(null);
  const z = tile.zoom;
  const cx = tile.tile_x;
  const cy = tile.tile_y;
  const GRID = 3;
  const TILE_PX = 256;
  const canvas = document.createElement("canvas");
  canvas.width = GRID * TILE_PX;
  canvas.height = GRID * TILE_PX;
  const ctx2d = canvas.getContext("2d");
  const baseUrl = "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile";

  return new Promise((resolve) => {
    let loaded = 0;
    const total = GRID * GRID;
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.src = `${baseUrl}/${z}/${cy + dy}/${cx + dx}`;
        const onDone = () => {
          loaded++;
          if (loaded === total) {
            const tex = new THREE.CanvasTexture(canvas);
            tex.colorSpace = THREE.SRGBColorSpace;
            resolve(tex);
          }
        };
        img.onload = () => {
          ctx2d.drawImage(img, (dx + 1) * TILE_PX, (dy + 1) * TILE_PX, TILE_PX, TILE_PX);
          onDone();
        };
        img.onerror = onDone;
      }
    }
  });
}

export default function ThreeView({ heightmap }) {
  const mountRef = useRef(null);

  useEffect(() => {
    if (!heightmap || !heightmap.values) return;

    const flat = flattenValues(heightmap.values);
    if (flat.length === 0) return;

    const w = heightmap.width || Math.round(Math.sqrt(flat.length));
    const h = heightmap.height || w;

    // Find min/max for normalisation
    let vMin = Infinity;
    let vMax = -Infinity;
    for (const v of flat) {
      if (v == null) continue;
      if (v < vMin) vMin = v;
      if (v > vMax) vMax = v;
    }
    if (!isFinite(vMin)) { vMin = 0; vMax = 1; }
    const range = vMax - vMin || 1;

    // Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf0f0f0);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
    camera.position.set(0, 80, 120);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(SIZE, SIZE);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    mountRef.current.innerHTML = "";
    mountRef.current.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI * 0.48;

    // Geometry — 128x128 mesh (or whatever the heightmap provides)
    const geom = new THREE.PlaneGeometry(100, 100, w - 1, h - 1);
    geom.rotateX(-Math.PI / 2);

    const pos = geom.attributes.position;
    const colors = new Float32Array(pos.count * 3);

    for (let i = 0; i < pos.count; i++) {
      const val = flat[i] ?? vMin;
      const norm = (val - vMin) / range;
      pos.setY(i, norm * 40);
      // green (low) -> brown (high) vertex colors (fallback)
      colors[i * 3] = 0.25 + 0.55 * norm;
      colors[i * 3 + 1] = 0.6 - 0.25 * norm;
      colors[i * 3 + 2] = 0.1 + 0.05 * norm;
    }

    geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geom.computeVertexNormals();

    // Normal map for micro-terrain detail
    const normalMap = generateNormalMap(flat, w, h);

    // Start with vertex-color fallback material, upgrade when satellite loads
    const matOpts = {
      vertexColors: true,
      side: THREE.DoubleSide,
      roughness: 0.85,
      metalness: 0.05,
      normalMap,
      normalScale: new THREE.Vector2(0.5, 0.5),
    };
    const material = new THREE.MeshStandardMaterial(matOpts);
    const mesh = new THREE.Mesh(geom, material);
    mesh.receiveShadow = true;
    scene.add(mesh);

    // Lights — DigitalTwin-quality setup
    const ambient = new THREE.AmbientLight(0x404060, 0.6);
    scene.add(ambient);
    const hemi = new THREE.HemisphereLight(0x88aacc, 0x443322, 0.4);
    scene.add(hemi);
    const sunLight = new THREE.DirectionalLight(0xffffff, 1.2);
    sunLight.position.set(50, 80, 30);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.set(1024, 1024);
    sunLight.shadow.camera.left = -60;
    sunLight.shadow.camera.right = 60;
    sunLight.shadow.camera.top = 60;
    sunLight.shadow.camera.bottom = -60;
    scene.add(sunLight);

    // Load satellite texture and upgrade material
    const tile = heightmap.satellite_tile;
    if (tile?.url) {
      loadSatelliteTexture(tile).then((tex) => {
        if (tex) {
          material.map = tex;
          material.vertexColors = false;
          material.needsUpdate = true;
        }
      });
    }

    // Animation loop
    let animId;
    function animate() {
      animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    return () => {
      cancelAnimationFrame(animId);
      renderer.dispose();
      normalMap.dispose();
      material.dispose();
      geom.dispose();
      if (mountRef.current) mountRef.current.innerHTML = "";
    };
  }, [heightmap]);

  return (
    <div
      ref={mountRef}
      style={{ width: SIZE, height: SIZE, border: "1px solid #ddd", borderRadius: 4 }}
    />
  );
}

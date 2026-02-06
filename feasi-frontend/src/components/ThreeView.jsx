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
  if (Array.isArray(values[0])) {
    return values.flat();
  }
  return values;
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
    mountRef.current.innerHTML = "";
    mountRef.current.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);

    // Plane geometry
    const geom = new THREE.PlaneGeometry(100, 100, w - 1, h - 1);
    geom.rotateX(-Math.PI / 2);

    const pos = geom.attributes.position;
    const colors = new Float32Array(pos.count * 3);

    for (let i = 0; i < pos.count; i++) {
      const val = flat[i] ?? vMin;
      const norm = (val - vMin) / range;
      pos.setY(i, norm * 30);
      // green (low) -> brown (high)
      colors[i * 3] = 0.3 + 0.5 * norm;
      colors[i * 3 + 1] = 0.6 - 0.3 * norm;
      colors[i * 3 + 2] = 0.1;
    }

    geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geom.computeVertexNormals();

    const mat = new THREE.MeshLambertMaterial({ vertexColors: true });
    scene.add(new THREE.Mesh(geom, mat));

    // Lights
    const light = new THREE.DirectionalLight(0xffffff, 1);
    light.position.set(1, 2, 1);
    scene.add(light);
    scene.add(new THREE.AmbientLight(0x606060));

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

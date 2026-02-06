import React, { useEffect, useRef, useCallback } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const SIZE = 480;

const COMP_COLORS = {
  PNL: 0x1e88e5,
  INV: 0xff9800,
  BAT: 0x4caf50,
  TRF: 0x9e9e9e,
  MON: 0xe91e63,
  CBL: 0x607d8b,
  MNT: 0x795548,
  BOS: 0x00bcd4,
};

function createComponentMesh(item) {
  const prefix = item.componentId.split("-")[0];
  let geometry, color;

  switch (prefix) {
    case "PNL":
      geometry = new THREE.BoxGeometry(4, 0.08, 2.5);
      color = COMP_COLORS.PNL;
      break;
    case "INV":
      geometry = new THREE.BoxGeometry(1.5, 2, 1);
      color = COMP_COLORS.INV;
      break;
    case "BAT":
      geometry = new THREE.BoxGeometry(3, 2.5, 5);
      color = COMP_COLORS.BAT;
      break;
    case "TRF":
      geometry = new THREE.BoxGeometry(2.5, 3, 2.5);
      color = COMP_COLORS.TRF;
      break;
    case "MON":
      geometry = new THREE.CylinderGeometry(0.3, 0.3, 3, 8);
      color = COMP_COLORS.MON;
      break;
    default:
      geometry = new THREE.BoxGeometry(1, 1, 1);
      color = 0x757575;
  }

  const material = new THREE.MeshLambertMaterial({ color });
  const mesh = new THREE.Mesh(geometry, material);

  if (prefix === "PNL") {
    mesh.rotation.order = "YXZ";
    mesh.rotation.x = THREE.MathUtils.degToRad(-25);
  }

  mesh.userData.layoutId = item.id;
  mesh.userData.defaultColor = color;
  mesh.position.set(item.x || 0, (item.z || 0) + 1, item.y || 0);
  mesh.rotation.y = THREE.MathUtils.degToRad(item.rotation || 0);

  return mesh;
}

function buildTerrain(heightmap) {
  if (!heightmap?.values) return null;
  const vals = Array.isArray(heightmap.values[0])
    ? heightmap.values.flat()
    : heightmap.values;
  const w = heightmap.width || Math.round(Math.sqrt(vals.length));
  const h = heightmap.height || w;

  let vMin = Infinity, vMax = -Infinity;
  for (const v of vals) {
    if (v == null) continue;
    if (v < vMin) vMin = v;
    if (v > vMax) vMax = v;
  }
  const range = vMax - vMin || 1;

  const geom = new THREE.PlaneGeometry(100, 100, w - 1, h - 1);
  geom.rotateX(-Math.PI / 2);
  const pos = geom.attributes.position;
  const colors = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) {
    const val = vals[i] ?? vMin;
    const norm = (val - vMin) / range;
    pos.setY(i, norm * 20);
    colors[i * 3] = 0.3 + 0.5 * norm;
    colors[i * 3 + 1] = 0.65 - 0.3 * norm;
    colors[i * 3 + 2] = 0.12;
  }
  geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geom.computeVertexNormals();
  return new THREE.Mesh(
    geom,
    new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide })
  );
}

export default function LayoutEditor({
  heightmap,
  componentLayout,
  onDrop,
  onSelectItem,
  selectedItem,
}) {
  const mountRef = useRef(null);
  const internals = useRef({
    scene: null,
    camera: null,
    renderer: null,
    controls: null,
    terrainMesh: null,
    meshMap: new Map(),
    animId: null,
  });

  // Initialise scene
  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xeef2f5);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
    camera.position.set(0, 70, 90);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(SIZE, SIZE);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.innerHTML = "";
    el.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 5, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI / 2.1;

    // Lights
    const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight.position.set(30, 60, 40);
    scene.add(dirLight);
    scene.add(new THREE.AmbientLight(0x808080));

    // Grid
    const grid = new THREE.GridHelper(100, 20, 0xaaaaaa, 0xdddddd);
    grid.position.y = 0.01;
    scene.add(grid);

    // Terrain
    const terrain = buildTerrain(heightmap);
    if (terrain) {
      scene.add(terrain);
      internals.current.terrainMesh = terrain;
    }

    internals.current.scene = scene;
    internals.current.camera = camera;
    internals.current.renderer = renderer;
    internals.current.controls = controls;

    function animate() {
      internals.current.animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    return () => {
      cancelAnimationFrame(internals.current.animId);
      renderer.dispose();
      if (el) el.innerHTML = "";
      internals.current.meshMap = new Map();
    };
  }, [heightmap]);

  // Sync component meshes
  useEffect(() => {
    const { scene, meshMap } = internals.current;
    if (!scene) return;

    const currentIds = new Set(componentLayout.map((i) => i.id));

    // Remove deleted
    for (const [id, mesh] of meshMap.entries()) {
      if (!currentIds.has(id)) {
        scene.remove(mesh);
        mesh.geometry.dispose();
        mesh.material.dispose();
        meshMap.delete(id);
      }
    }

    // Add or update
    componentLayout.forEach((item) => {
      if (meshMap.has(item.id)) {
        const mesh = meshMap.get(item.id);
        mesh.position.set(item.x || 0, (item.z || 0) + 1, item.y || 0);
        const prefix = item.componentId.split("-")[0];
        if (prefix === "PNL") {
          mesh.rotation.order = "YXZ";
          mesh.rotation.y = THREE.MathUtils.degToRad(item.rotation || 0);
          mesh.rotation.x = THREE.MathUtils.degToRad(-25);
        } else {
          mesh.rotation.y = THREE.MathUtils.degToRad(item.rotation || 0);
        }
        // Highlight selected
        const col = item.id === selectedItem ? 0xffeb3b : mesh.userData.defaultColor;
        mesh.material.color.setHex(col);
      } else {
        const mesh = createComponentMesh(item);
        scene.add(mesh);
        meshMap.set(item.id, mesh);
      }
    });
  }, [componentLayout, selectedItem]);

  // Click handler — select component
  const handleClick = useCallback(
    (e) => {
      const { renderer, camera } = internals.current;
      if (!renderer || !camera) return;
      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );
      const rc = new THREE.Raycaster();
      rc.setFromCamera(mouse, camera);
      const meshes = Array.from(internals.current.meshMap.values());
      const hits = rc.intersectObjects(meshes);
      if (hits.length > 0) {
        onSelectItem(hits[0].object.userData.layoutId);
      } else {
        onSelectItem(null);
      }
    },
    [onSelectItem]
  );

  // Drop handler — place component on terrain
  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData("application/json");
      if (!raw) return;
      const component = JSON.parse(raw);

      const { renderer, camera, terrainMesh } = internals.current;
      if (!renderer || !camera) return;

      const rect = renderer.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );
      const rc = new THREE.Raycaster();
      rc.setFromCamera(mouse, camera);

      let pos;
      if (terrainMesh) {
        const hits = rc.intersectObject(terrainMesh);
        if (hits.length > 0) {
          pos = hits[0].point;
        }
      }
      if (!pos) {
        // Fallback: intersect y=0 plane
        const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
        pos = new THREE.Vector3();
        rc.ray.intersectPlane(plane, pos);
      }

      onDrop({
        component,
        x: Math.round(pos.x * 2) / 2,
        y: Math.round(pos.z * 2) / 2,
        z: Math.max(0, pos.y),
      });
    },
    [onDrop]
  );

  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  };

  return (
    <div
      ref={mountRef}
      className="layout-editor"
      onClick={handleClick}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    />
  );
}

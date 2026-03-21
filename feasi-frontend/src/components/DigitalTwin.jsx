import React, { useEffect, useRef, useState, useCallback } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const COMP_COLORS = {
  PNL: 0x1e88e5, INV: 0xff9800, BAT: 0x4caf50, TRF: 0x9e9e9e,
  MON: 0xe91e63, CBL: 0x607d8b, MNT: 0x795548, BOS: 0x00bcd4,
};
const SUN_PATH_COLORS = { summer: 0xffeb3b, winter: 0x2196f3, equinox: 0xff9800 };

/* ══════════════════════════════════════════════════════════
   Environment builders
   ══════════════════════════════════════════════════════════ */

function buildSkyGradient(scene) {
  const canvas = document.createElement("canvas");
  canvas.width = 2;
  canvas.height = 512;
  const ctx = canvas.getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 512);
  grad.addColorStop(0, "#0a1628");
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

function buildGroundPlane() {
  // Large textured ground with grass color
  const geom = new THREE.PlaneGeometry(1200, 1200, 1, 1);
  geom.rotateX(-Math.PI / 2);
  const mat = new THREE.MeshStandardMaterial({
    color: 0x3d6b35,
    roughness: 0.95,
    metalness: 0,
  });
  const mesh = new THREE.Mesh(geom, mat);
  mesh.position.y = -0.2;
  mesh.receiveShadow = true;
  return mesh;
}

function buildGrid() {
  const grid = new THREE.GridHelper(400, 40, 0x556655, 0x445544);
  grid.position.y = 0.01;
  grid.material.opacity = 0.15;
  grid.material.transparent = true;
  return grid;
}

function buildTrees(count = 40, spread = 180) {
  const group = new THREE.Group();
  group.name = "trees";
  const trunkMat = new THREE.MeshStandardMaterial({ color: 0x5d4037, roughness: 0.9 });
  const leafMat = new THREE.MeshStandardMaterial({ color: 0x2e7d32, roughness: 0.8 });
  const trunkGeom = new THREE.CylinderGeometry(0.3, 0.5, 4, 6);
  const leafGeom = new THREE.SphereGeometry(2.5, 6, 5);

  for (let i = 0; i < count; i++) {
    const angle = Math.random() * Math.PI * 2;
    const dist = 80 + Math.random() * spread;
    const x = Math.cos(angle) * dist;
    const z = Math.sin(angle) * dist;
    const scale = 0.6 + Math.random() * 0.8;

    const trunk = new THREE.Mesh(trunkGeom, trunkMat);
    trunk.position.set(x, 2 * scale, z);
    trunk.scale.set(scale, scale, scale);
    trunk.castShadow = true;
    group.add(trunk);

    const leaves = new THREE.Mesh(leafGeom, leafMat);
    leaves.position.set(x, 5.5 * scale, z);
    leaves.scale.set(scale, scale * 1.2, scale);
    leaves.castShadow = true;
    group.add(leaves);
  }
  return group;
}

function buildClouds(count = 8) {
  const group = new THREE.Group();
  group.name = "clouds";
  const mat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.5 });

  for (let i = 0; i < count; i++) {
    const cloud = new THREE.Group();
    const blobs = 3 + Math.floor(Math.random() * 3);
    for (let j = 0; j < blobs; j++) {
      const geom = new THREE.SphereGeometry(8 + Math.random() * 6, 6, 4);
      const m = new THREE.Mesh(geom, mat);
      m.position.set(j * 10 - blobs * 5, Math.random() * 4, Math.random() * 8 - 4);
      m.scale.set(1, 0.4 + Math.random() * 0.3, 1);
      cloud.add(m);
    }
    cloud.position.set(
      Math.random() * 400 - 200,
      100 + Math.random() * 40,
      Math.random() * 400 - 200,
    );
    group.add(cloud);
  }
  return group;
}

function buildWindParticles(scene) {
  const count = 200;
  const geom = new THREE.BufferGeometry();
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    positions[i * 3] = Math.random() * 400 - 200;
    positions[i * 3 + 1] = Math.random() * 60 + 2;
    positions[i * 3 + 2] = Math.random() * 400 - 200;
  }
  geom.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const mat = new THREE.PointsMaterial({ color: 0xffffff, size: 0.3, transparent: true, opacity: 0.3 });
  const points = new THREE.Points(geom, mat);
  points.name = "wind_particles";
  return points;
}

/* ══════════════════════════════════════════════════════════
   Data builders (terrain, buildings, solar, sun paths, etc.)
   ══════════════════════════════════════════════════════════ */

function buildTerrainMesh(heightmap, satelliteTexture) {
  if (!heightmap?.values) return null;
  const vals = Array.isArray(heightmap.values[0]) ? heightmap.values.flat() : heightmap.values;
  const w = heightmap.width || Math.round(Math.sqrt(vals.length));
  const h = heightmap.height || w;

  let vMin = Infinity, vMax = -Infinity;
  for (const v of vals) { if (v != null) { if (v < vMin) vMin = v; if (v > vMax) vMax = v; } }
  const range = vMax - vMin || 1;

  const geom = new THREE.PlaneGeometry(200, 200, w - 1, h - 1);
  geom.rotateX(-Math.PI / 2);
  const pos = geom.attributes.position;
  const colors = new Float32Array(pos.count * 3);
  // Scale vertical exaggeration based on actual terrain range
  // UK terrain: typically 5-50m range → gentle undulation, not mountains
  const vertScale = range > 100 ? 15 : range > 30 ? 8 : 4;
  for (let i = 0; i < pos.count; i++) {
    const val = vals[i] ?? vMin;
    const norm = (val - vMin) / range;
    pos.setY(i, norm * vertScale);
    colors[i * 3] = 0.25 + 0.55 * norm;
    colors[i * 3 + 1] = 0.6 - 0.25 * norm;
    colors[i * 3 + 2] = 0.1 + 0.05 * norm;
  }
  geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geom.computeVertexNormals();

  const matOpts = { side: THREE.DoubleSide, roughness: 0.85, metalness: 0.05 };
  if (satelliteTexture) {
    matOpts.map = satelliteTexture;
    matOpts.vertexColors = false;
  } else {
    matOpts.vertexColors = true;
  }
  const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial(matOpts));
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  mesh.name = "terrain";
  return mesh;
}

function buildDefaultTerrain() {
  // Gentle rolling English countryside — NOT mountains
  const size = 64;
  const vals = [];
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      const nx = c / size - 0.5, ny = r / size - 0.5;
      // Gentle undulation: 2-3m variation, smooth curves
      const e = 50 + 2 * Math.sin(nx * 3) * Math.cos(ny * 2.5) + 1 * Math.sin(nx * 6 + ny * 4) + Math.random() * 0.3;
      vals.push(Math.round(e * 10) / 10);
    }
  }
  return buildTerrainMesh({ width: size, height: size, values: vals }, null);
}

function buildBuildings(buildings) {
  if (!buildings?.features?.length) return null;
  const group = new THREE.Group();
  group.name = "buildings";
  const material = new THREE.MeshStandardMaterial({ color: 0x78909c, roughness: 0.7, metalness: 0.2 });

  buildings.features.forEach((f, idx) => {
    const height = f.properties?.height || f.properties?.estimated_height || 8;
    const coords = f.geometry?.coordinates?.[0];
    if (!coords || coords.length < 3) return;

    const xs = coords.map(c => c[0]);
    const ys = coords.map(c => c[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const w = Math.max(2, (maxX - minX) * 111000 * 0.5);
    const d = Math.max(2, (maxY - minY) * 111000 * 0.5);

    const geom = new THREE.BoxGeometry(w, height, d);
    const mesh = new THREE.Mesh(geom, material.clone());
    mesh.position.set(
      ((minX + maxX) / 2) * 20 - 100 + Math.random() * 160 - 80,
      height / 2,
      ((minY + maxY) / 2) * 20 - 100 + Math.random() * 160 - 80,
    );
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData = { type: "building", height, index: idx };
    group.add(mesh);
  });
  return group;
}

function buildDefaultBuildings() {
  // A few placeholder buildings when no data
  const group = new THREE.Group();
  group.name = "buildings";
  const mat = new THREE.MeshStandardMaterial({ color: 0x78909c, roughness: 0.7, metalness: 0.2 });
  const defs = [
    { x: -20, z: -15, w: 12, h: 6, d: 8 },
    { x: 15, z: -25, w: 8, h: 4, d: 6 },
    { x: -35, z: 20, w: 15, h: 8, d: 10 },
    { x: 30, z: 10, w: 10, h: 5, d: 7 },
  ];
  defs.forEach((b, i) => {
    const geom = new THREE.BoxGeometry(b.w, b.h, b.d);
    const mesh = new THREE.Mesh(geom, mat.clone());
    mesh.position.set(b.x, b.h / 2, b.z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData = { type: "building", height: b.h, index: i };
    group.add(mesh);
  });
  return group;
}

function buildSolarLayout(layout) {
  if (!layout?.length) return null;
  const group = new THREE.Group();
  group.name = "solar_layout";

  layout.forEach(item => {
    const prefix = (item.componentId || "PNL").split("-")[0];
    let geom, color;
    switch (prefix) {
      case "PNL": geom = new THREE.BoxGeometry(4, 0.08, 2.5); color = COMP_COLORS.PNL; break;
      case "INV": geom = new THREE.BoxGeometry(1.5, 2, 1); color = COMP_COLORS.INV; break;
      case "BAT": geom = new THREE.BoxGeometry(3, 2.5, 5); color = COMP_COLORS.BAT; break;
      case "TRF": geom = new THREE.BoxGeometry(2.5, 3, 2.5); color = COMP_COLORS.TRF; break;
      default: geom = new THREE.BoxGeometry(1, 1, 1); color = 0x757575;
    }
    const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color, roughness: 0.3, metalness: 0.5 }));
    mesh.position.set(item.x || 0, (item.z || 0) + 1, item.y || 0);
    if (prefix === "PNL") { mesh.rotation.order = "YXZ"; mesh.rotation.x = THREE.MathUtils.degToRad(-25); }
    mesh.rotation.y = THREE.MathUtils.degToRad(item.rotation || 0);
    mesh.castShadow = true;
    group.add(mesh);
  });
  return group;
}

function buildDefaultSolarField() {
  // Demo solar array
  const group = new THREE.Group();
  group.name = "solar_layout";
  const panelMat = new THREE.MeshStandardMaterial({ color: 0x1565c0, metalness: 0.7, roughness: 0.2 });

  for (let row = 0; row < 6; row++) {
    for (let col = 0; col < 8; col++) {
      const geom = new THREE.BoxGeometry(4, 0.08, 2.5);
      const panel = new THREE.Mesh(geom, panelMat);
      panel.position.set(-30 + col * 7, 2.5, 10 + row * 5);
      panel.rotation.x = THREE.MathUtils.degToRad(-25);
      panel.castShadow = true;
      group.add(panel);

      // Support structure
      const legGeom = new THREE.CylinderGeometry(0.08, 0.08, 2.5, 4);
      const legMat = new THREE.MeshStandardMaterial({ color: 0x888888 });
      [-1.5, 1.5].forEach(dx => {
        const leg = new THREE.Mesh(legGeom, legMat);
        leg.position.set(-30 + col * 7 + dx, 1.25, 10 + row * 5);
        group.add(leg);
      });
    }
  }

  // Inverter box
  const invGeom = new THREE.BoxGeometry(2, 2.5, 1.5);
  const inv = new THREE.Mesh(invGeom, new THREE.MeshStandardMaterial({ color: 0xff9800, roughness: 0.4, metalness: 0.4 }));
  inv.position.set(30, 1.25, 20);
  inv.castShadow = true;
  group.add(inv);

  // Transformer
  const txGeom = new THREE.BoxGeometry(3, 3.5, 3);
  const tx = new THREE.Mesh(txGeom, new THREE.MeshStandardMaterial({ color: 0x607d8b, roughness: 0.6, metalness: 0.3 }));
  tx.position.set(35, 1.75, 20);
  tx.castShadow = true;
  group.add(tx);

  return group;
}

function buildSunPaths(sunPath) {
  if (!sunPath) return null;
  const group = new THREE.Group();
  group.name = "sun_paths";

  for (const [season, color] of Object.entries(SUN_PATH_COLORS)) {
    const hourly = sunPath[season];
    if (!hourly?.length) continue;
    const points = hourly.map(h => {
      const alt = THREE.MathUtils.degToRad(h.altitude);
      const az = THREE.MathUtils.degToRad(h.azimuth);
      const r = 120;
      return new THREE.Vector3(
        r * Math.cos(alt) * Math.sin(az),
        r * Math.sin(alt) + 5,
        -r * Math.cos(alt) * Math.cos(az),
      );
    });
    if (points.length > 1) {
      const curve = new THREE.CatmullRomCurve3(points);
      const geom = new THREE.BufferGeometry().setFromPoints(curve.getPoints(50));
      const line = new THREE.Line(geom, new THREE.LineBasicMaterial({ color, linewidth: 2, transparent: true, opacity: 0.6 }));
      line.name = `sun_${season}`;
      group.add(line);
    }
  }
  return group;
}

function buildDefaultSunPaths() {
  // Approximate UK sun paths for lat ~52°
  const paths = {};
  for (const [season, maxAlt, daylength] of [["summer", 60, 16], ["equinox", 38, 12], ["winter", 15, 8]]) {
    const hours = [];
    const sunrise = 12 - daylength / 2;
    for (let h = sunrise; h <= sunrise + daylength; h += 0.5) {
      const frac = (h - sunrise) / daylength;
      const alt = maxAlt * Math.sin(frac * Math.PI);
      const az = 90 + 180 * frac;
      hours.push({ hour: Math.round(h), altitude: alt, azimuth: az });
    }
    paths[season] = hours;
  }
  return buildSunPaths(paths);
}

function buildDetectionOverlays(detections) {
  if (!detections?.findings) return null;
  const group = new THREE.Group();
  group.name = "detections";
  const findings = detections.findings;

  const exclusions = findings.exclusion_zones || [];
  exclusions.forEach((ez, i) => {
    const geom = new THREE.PlaneGeometry(15, 15);
    geom.rotateX(-Math.PI / 2);
    const mesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
      color: 0xda1e28, transparent: true, opacity: 0.25, side: THREE.DoubleSide,
    }));
    mesh.position.set(-40 + i * 30, 0.5, -30 + i * 20);
    mesh.name = "exclusion_zone";
    mesh.userData = { type: ez.type, reason: ez.reason };
    group.add(mesh);
  });

  const usable = findings.usable_area_pct || 0;
  if (usable > 0) {
    const scale = Math.sqrt(usable / 100);
    const geom = new THREE.PlaneGeometry(160 * scale, 160 * scale);
    geom.rotateX(-Math.PI / 2);
    const mesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
      color: 0x4caf50, transparent: true, opacity: 0.12, side: THREE.DoubleSide,
    }));
    mesh.position.y = 0.3;
    mesh.name = "usable_area";
    group.add(mesh);
  }
  return group;
}

function buildRetrofitGeometry(retrofitData) {
  if (!retrofitData || !Array.isArray(retrofitData) || retrofitData.length === 0) return null;
  const group = new THREE.Group();
  group.name = "retrofit_geometry";

  retrofitData.forEach((feature) => {
    const props = feature.properties || {};
    const type = props.type || "extension";
    const height = props.height_m || 3;
    const coords = feature.geometry?.coordinates?.[0];
    if (!coords || coords.length < 3) return;

    if (type.includes("extension")) {
      const shape = new THREE.Shape();
      coords.forEach((c, i) => {
        if (i === 0) shape.moveTo(c[0], c[1]);
        else shape.lineTo(c[0], c[1]);
      });
      const geom = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
      geom.rotateX(-Math.PI / 2);
      const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({
        color: 0x8e24aa, transparent: true, opacity: 0.45, roughness: 0.6,
      }));
      mesh.castShadow = true;
      mesh.name = `retrofit_${type}`;
      mesh.userData = props;
      group.add(mesh);
      group.add(new THREE.LineSegments(
        new THREE.EdgesGeometry(geom),
        new THREE.LineBasicMaterial({ color: 0xce93d8, linewidth: 2 }),
      ));
    }
  });

  // Insulation shell + solar panels + heat pump
  const shellGeom = new THREE.BoxGeometry(22, 10, 16);
  const shell = new THREE.Mesh(shellGeom, new THREE.MeshStandardMaterial({
    color: 0xff9800, transparent: true, opacity: 0.15, side: THREE.DoubleSide, roughness: 1,
  }));
  shell.position.set(0, 5, 0);
  shell.name = "insulation_shell";
  group.add(shell);

  const panelGeom = new THREE.PlaneGeometry(8, 5);
  panelGeom.rotateX(-Math.PI / 4);
  const panel = new THREE.Mesh(panelGeom, new THREE.MeshStandardMaterial({ color: 0x1565c0, metalness: 0.8, roughness: 0.2 }));
  panel.position.set(0, 11, -2);
  panel.name = "solar_panels";
  group.add(panel);

  const hp = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.9, 0.5), new THREE.MeshStandardMaterial({ color: 0xeeeeee, roughness: 0.5 }));
  hp.position.set(-12, 0.45, 8);
  hp.name = "heat_pump";
  group.add(hp);
  const fan = new THREE.Mesh(new THREE.CircleGeometry(0.3, 16), new THREE.MeshBasicMaterial({ color: 0x333333 }));
  fan.position.set(-12, 0.45, 8.26);
  group.add(fan);

  return group;
}

/* ══════════════════════════════════════════════════════════
   Real infrastructure builders (REPD, OSM, grid data)
   ══════════════════════════════════════════════════════════ */

const TECH_COLORS = {
  "Solar Photovoltaics": 0xfdd835,
  "Wind Onshore": 0x42a5f5,
  "Wind Offshore": 0x1565c0,
  "Battery": 0x66bb6a,
  "Biomass": 0x8d6e63,
  "Landfill Gas": 0x78909c,
  "Hydro": 0x26c6da,
};
const VOLTAGE_COLORS = {
  400: 0xe53935, 275: 0xf44336, 132: 0xff7043,
  66: 0xffa726, 33: 0xffca28, 11: 0x66bb6a,
};

function voltageColor(kv) {
  if (!kv) return 0x9e9e9e;
  if (kv >= 275) return VOLTAGE_COLORS[400];
  if (kv >= 100) return VOLTAGE_COLORS[132];
  if (kv >= 50) return VOLTAGE_COLORS[66];
  if (kv >= 20) return VOLTAGE_COLORS[33];
  return VOLTAGE_COLORS[11];
}

function buildRealRenewables(renewables, centreLat, centreLon) {
  if (!renewables?.length) return null;
  const group = new THREE.Group();
  group.name = "real_renewables";
  const SCALE = 2000; // metres per scene unit (approx)

  renewables.forEach((proj) => {
    const dx = (proj.lon - centreLon) * 111320 * Math.cos(centreLat * Math.PI / 180) / SCALE;
    const dz = -(proj.lat - centreLat) * 110540 / SCALE;

    // Clamp to visible area
    if (Math.abs(dx) > 200 || Math.abs(dz) > 200) return;

    const tech = proj.technology || "Unknown";
    const color = TECH_COLORS[tech] || 0xab47bc;
    const capMw = proj.capacity_mw || 1;
    const height = Math.max(1, Math.min(12, capMw * 0.5));
    const radius = Math.max(0.8, Math.min(4, capMw * 0.3));

    if (tech.includes("Wind")) {
      // Wind turbine — tall cylinder + blade disc
      const tower = new THREE.Mesh(
        new THREE.CylinderGeometry(0.15, 0.3, height * 2, 6),
        new THREE.MeshStandardMaterial({ color: 0xeeeeee, roughness: 0.6 }),
      );
      tower.position.set(dx, height, dz);
      tower.castShadow = true;
      group.add(tower);
      const blades = new THREE.Mesh(
        new THREE.CircleGeometry(height * 0.6, 3),
        new THREE.MeshStandardMaterial({ color: 0xdddddd, side: THREE.DoubleSide, transparent: true, opacity: 0.7 }),
      );
      blades.position.set(dx, height * 2 - 0.5, dz);
      blades.rotation.y = Math.random() * Math.PI;
      group.add(blades);
    } else {
      // Solar / other — flat coloured marker
      const geom = new THREE.CylinderGeometry(radius, radius, 0.6, 8);
      const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color, roughness: 0.4, metalness: 0.3 }));
      mesh.position.set(dx, 0.3, dz);
      mesh.castShadow = true;
      mesh.userData = { type: "repd_project", name: proj.name, technology: tech, capacity_mw: capMw, status: proj.status };
      group.add(mesh);
    }

    // Label sprite
    const canvas = document.createElement("canvas");
    canvas.width = 256; canvas.height = 64;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(0, 0, 256, 64);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 18px sans-serif";
    const label = `${(proj.name || tech).slice(0, 20)} ${capMw.toFixed(1)}MW`;
    ctx.fillText(label, 6, 24);
    ctx.font = "14px sans-serif";
    ctx.fillStyle = "#bbbbbb";
    ctx.fillText(proj.status || "", 6, 48);
    const tex = new THREE.CanvasTexture(canvas);
    const spriteMat = new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0.85 });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.position.set(dx, height + 3, dz);
    sprite.scale.set(12, 3, 1);
    group.add(sprite);
  });
  return group;
}

function buildRealSubstations(osmSubs, gridSubs, centreLat, centreLon) {
  const all = [];
  const SCALE = 2000;

  (osmSubs || []).forEach(s => {
    all.push({ ...s, source: "osm" });
  });
  (gridSubs || []).forEach(s => {
    all.push({ ...s, source: "grid" });
  });
  if (!all.length) return null;

  const group = new THREE.Group();
  group.name = "real_substations";

  all.forEach((sub) => {
    const dx = (sub.lon - centreLon) * 111320 * Math.cos(centreLat * Math.PI / 180) / SCALE;
    const dz = -(sub.lat - centreLat) * 110540 / SCALE;
    if (Math.abs(dx) > 200 || Math.abs(dz) > 200) return;

    const kv = sub.voltage_kv || 11;
    const color = voltageColor(kv);
    const size = Math.max(1.5, Math.min(5, kv / 30));
    const height = Math.max(2, Math.min(8, kv / 20));

    const geom = new THREE.BoxGeometry(size, height, size);
    const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.4 }));
    mesh.position.set(dx, height / 2, dz);
    mesh.castShadow = true;
    mesh.userData = {
      type: "substation", name: sub.name, voltage_kv: kv, source: sub.source,
      demand_mw: sub.demand_mw, headroom_mw: sub.demand_headroom_mw,
    };
    group.add(mesh);

    // Fence / outline
    const wireGeom = new THREE.EdgesGeometry(new THREE.BoxGeometry(size + 0.5, height + 0.3, size + 0.5));
    const wire = new THREE.LineSegments(wireGeom, new THREE.LineBasicMaterial({ color: 0x888888 }));
    wire.position.copy(mesh.position);
    group.add(wire);

    // Label
    const canvas = document.createElement("canvas");
    canvas.width = 256; canvas.height = 48;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(0, 0, 256, 48);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 16px sans-serif";
    ctx.fillText(`${(sub.name || "Substation").slice(0, 22)} ${kv}kV`, 4, 20);
    if (sub.demand_headroom_mw != null) {
      ctx.font = "13px sans-serif";
      ctx.fillStyle = "#aaaaaa";
      ctx.fillText(`Headroom: ${sub.demand_headroom_mw.toFixed(1)}MW`, 4, 40);
    }
    const tex = new THREE.CanvasTexture(canvas);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0.8 }));
    sprite.position.set(dx, height + 2, dz);
    sprite.scale.set(10, 2.5, 1);
    group.add(sprite);
  });
  return group;
}

function buildRealPowerLines(lines, centreLat, centreLon) {
  if (!lines?.length) return null;
  const group = new THREE.Group();
  group.name = "real_power_lines";
  const SCALE = 2000;

  lines.forEach((line) => {
    const coords = line.geometry?.coordinates;
    if (!coords || coords.length < 2) return;

    const kv = line.voltage_kv || 11;
    const color = voltageColor(kv);
    const lineHeight = Math.max(3, Math.min(15, kv / 15));

    const points = coords.map(([lng, lat]) => {
      const dx = (lng - centreLon) * 111320 * Math.cos(centreLat * Math.PI / 180) / SCALE;
      const dz = -(lat - centreLat) * 110540 / SCALE;
      return new THREE.Vector3(dx, lineHeight, dz);
    }).filter(p => Math.abs(p.x) <= 250 && Math.abs(p.z) <= 250);

    if (points.length < 2) return;

    // Power line as tube
    const curve = new THREE.CatmullRomCurve3(points);
    const tubeRadius = Math.max(0.05, Math.min(0.3, kv / 400));
    const tubeGeom = new THREE.TubeGeometry(curve, Math.max(4, points.length * 2), tubeRadius, 4, false);
    const tubeMesh = new THREE.Mesh(tubeGeom, new THREE.MeshStandardMaterial({
      color, roughness: 0.4, metalness: 0.6, transparent: true, opacity: 0.8,
    }));
    tubeMesh.userData = { type: "power_line", voltage_kv: kv, name: line.name, line_type: line.line_type };
    group.add(tubeMesh);

    // Pylons at intervals
    const pylonMat = new THREE.MeshStandardMaterial({ color: 0x666666, roughness: 0.8 });
    const interval = Math.max(1, Math.floor(points.length / 5));
    for (let i = 0; i < points.length; i += interval) {
      const p = points[i];
      const pylon = new THREE.Mesh(
        new THREE.CylinderGeometry(0.1, 0.2, lineHeight, 4),
        pylonMat,
      );
      pylon.position.set(p.x, lineHeight / 2, p.z);
      group.add(pylon);
      // Cross-arm
      const arm = new THREE.Mesh(
        new THREE.BoxGeometry(1.5, 0.1, 0.1),
        pylonMat,
      );
      arm.position.set(p.x, lineHeight - 0.5, p.z);
      group.add(arm);
    }
  });
  return group;
}

function buildRealTecQueue(tecProjects, centreLat, centreLon) {
  if (!tecProjects?.length) return null;
  const group = new THREE.Group();
  group.name = "real_tec_queue";
  const SCALE = 2000;

  tecProjects.forEach((proj) => {
    const dx = (proj.lon - centreLon) * 111320 * Math.cos(centreLat * Math.PI / 180) / SCALE;
    const dz = -(proj.lat - centreLat) * 110540 / SCALE;
    if (Math.abs(dx) > 200 || Math.abs(dz) > 200) return;

    const capMw = proj.capacity_mw || 10;
    const radius = Math.max(0.6, Math.min(3, capMw / 100));

    // Diamond shape for TEC projects
    const geom = new THREE.OctahedronGeometry(radius);
    const color = proj.plant_type?.toLowerCase().includes("solar") ? 0xfdd835
      : proj.plant_type?.toLowerCase().includes("wind") ? 0x42a5f5
      : proj.plant_type?.toLowerCase().includes("battery") ? 0x66bb6a
      : 0xce93d8;
    const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({
      color, roughness: 0.3, metalness: 0.5, transparent: true, opacity: 0.7,
    }));
    mesh.position.set(dx, radius + 0.5, dz);
    mesh.castShadow = true;
    mesh.userData = { type: "tec_project", name: proj.project_name, capacity_mw: capMw, status: proj.status, plant_type: proj.plant_type };
    group.add(mesh);

    // Label
    const canvas = document.createElement("canvas");
    canvas.width = 256; canvas.height = 48;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "rgba(80,0,120,0.6)";
    ctx.fillRect(0, 0, 256, 48);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 14px sans-serif";
    ctx.fillText(`TEC: ${(proj.project_name || "").slice(0, 20)} ${capMw}MW`, 4, 20);
    ctx.font = "12px sans-serif";
    ctx.fillStyle = "#cccccc";
    ctx.fillText(`${proj.plant_type || ""} | ${proj.status || ""}`, 4, 40);
    const tex = new THREE.CanvasTexture(canvas);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0.8 }));
    sprite.position.set(dx, radius * 2 + 3, dz);
    sprite.scale.set(10, 2.5, 1);
    group.add(sprite);
  });
  return group;
}

/* ══════════════════════════════════════════════════════════
   Main Component
   ══════════════════════════════════════════════════════════ */

export default function DigitalTwin({ data, realContext, onClose }) {
  const containerRef = useRef(null);
  const rendererRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const sunLightRef = useRef(null);
  const sunSphereRef = useRef(null);
  const cloudsRef = useRef(null);
  const windRef = useRef(null);
  const raycasterRef = useRef(new THREE.Raycaster());
  const mouseRef = useRef(new THREE.Vector2());

  const [timeOfDay, setTimeOfDay] = useState(12);
  const [season, setSeason] = useState("summer");
  const [measureMode, setMeasureMode] = useState(false);
  const [measurePoints, setMeasurePoints] = useState([]);
  const [info, setInfo] = useState(null);
  const [layers, setLayers] = useState({
    terrain: true, buildings: true, solar_layout: true,
    sun_paths: true, detections: true, retrofit_geometry: false,
    real_renewables: true, real_substations: true, real_power_lines: true, real_tec_queue: true,
  });

  // Build scene
  useEffect(() => {
    if (!containerRef.current) return;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    // Sky gradient background
    buildSkyGradient(scene);
    scene.fog = new THREE.FogExp2(0x88aacc, 0.0015);

    const camera = new THREE.PerspectiveCamera(60, containerRef.current.clientWidth / containerRef.current.clientHeight, 0.5, 1500);
    camera.position.set(120, 80, 120);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    containerRef.current.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxDistance = 500;
    controls.minDistance = 10;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.target.set(0, 10, 0);
    controlsRef.current = controls;

    // ── Lighting ──
    const ambient = new THREE.AmbientLight(0x8899aa, 0.5);
    scene.add(ambient);
    const hemi = new THREE.HemisphereLight(0x87ceeb, 0x3d6b35, 0.6);
    scene.add(hemi);
    const sunLight = new THREE.DirectionalLight(0xffeedd, 1.5);
    sunLight.position.set(60, 100, 40);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.set(2048, 2048);
    sunLight.shadow.camera.left = -150;
    sunLight.shadow.camera.right = 150;
    sunLight.shadow.camera.top = 150;
    sunLight.shadow.camera.bottom = -150;
    sunLight.shadow.camera.far = 400;
    sunLight.shadow.bias = -0.001;
    scene.add(sunLight);
    sunLightRef.current = sunLight;

    // Sun indicator
    const sunGeom = new THREE.SphereGeometry(4, 16, 16);
    const sunMat = new THREE.MeshBasicMaterial({ color: 0xffee88 });
    const sunSphere = new THREE.Mesh(sunGeom, sunMat);
    sunSphere.position.copy(sunLight.position);
    scene.add(sunSphere);
    sunSphereRef.current = sunSphere;

    // ── Environment ──
    scene.add(buildGroundPlane());
    scene.add(buildGrid());
    const trees = buildTrees();
    scene.add(trees);
    const clouds = buildClouds();
    scene.add(clouds);
    cloudsRef.current = clouds;
    const wind = buildWindParticles();
    scene.add(wind);
    windRef.current = wind;

    // Shadow catcher
    const shadowGeom = new THREE.PlaneGeometry(600, 600);
    shadowGeom.rotateX(-Math.PI / 2);
    const shadowMesh = new THREE.Mesh(shadowGeom, new THREE.ShadowMaterial({ opacity: 0.25 }));
    shadowMesh.receiveShadow = true;
    shadowMesh.position.y = 0;
    scene.add(shadowMesh);

    // ── Site Data or Defaults ──
    const buildScene = (satTexture) => {
      // Terrain
      if (data?.heightmap) {
        const terrain = buildTerrainMesh(data.heightmap, satTexture);
        if (terrain) scene.add(terrain);
      } else {
        const defTerrain = buildDefaultTerrain();
        if (defTerrain) scene.add(defTerrain);
      }

      // Buildings
      if (data?.buildings) {
        const bldgs = buildBuildings(data.buildings);
        if (bldgs) scene.add(bldgs);
      } else {
        scene.add(buildDefaultBuildings());
      }

      // Solar layout
      if (data?.solar_layout) {
        const layout = buildSolarLayout(data.solar_layout);
        if (layout) scene.add(layout);
      } else {
        scene.add(buildDefaultSolarField());
      }

      // Sun paths
      if (data?.sun_path) {
        const paths = buildSunPaths(data.sun_path);
        if (paths) scene.add(paths);
      } else {
        const defPaths = buildDefaultSunPaths();
        if (defPaths) scene.add(defPaths);
      }

      // Detection overlays
      if (data?.vision_detections) {
        const overlays = buildDetectionOverlays(data.vision_detections);
        if (overlays) scene.add(overlays);
      }

      // Retrofit geometry (hidden by default)
      if (data?.retrofit_geometry) {
        const retro = buildRetrofitGeometry(data.retrofit_geometry);
        if (retro) { retro.visible = false; scene.add(retro); }
      }

      // ── Real infrastructure from REPD / OSM / Grid / TEC ──
      const cLat = data?.lat ?? realContext?.centre?.lat;
      const cLon = data?.lon ?? realContext?.centre?.lon;
      if (realContext && cLat && cLon) {
        const renewables = buildRealRenewables(realContext.nearby_renewables, cLat, cLon);
        if (renewables) scene.add(renewables);

        const subs = buildRealSubstations(realContext.osm_substations, realContext.grid_substations, cLat, cLon);
        if (subs) scene.add(subs);

        const lines = buildRealPowerLines(realContext.osm_lines, cLat, cLon);
        if (lines) scene.add(lines);

        const tec = buildRealTecQueue(realContext.tec_queue, cLat, cLon);
        if (tec) scene.add(tec);
      }
    };

    // Load satellite texture if available
    const tile = data?.satellite_tile;
    if (tile?.url) {
      const z = tile.zoom, cx = tile.tile_x, cy = tile.tile_y;
      const GRID = 3, TILE_PX = 256;
      const canvas = document.createElement("canvas");
      canvas.width = GRID * TILE_PX;
      canvas.height = GRID * TILE_PX;
      const ctx2d = canvas.getContext("2d");
      let loaded = 0;
      const total = GRID * GRID;
      const baseUrl = "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile";

      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          const img = new Image();
          img.crossOrigin = "anonymous";
          img.src = `${baseUrl}/${z}/${cy + dy}/${cx + dx}`;
          img.onload = () => {
            ctx2d.drawImage(img, (dx + 1) * TILE_PX, (dy + 1) * TILE_PX, TILE_PX, TILE_PX);
            loaded++;
            if (loaded === total) {
              const tex = new THREE.CanvasTexture(canvas);
              tex.colorSpace = THREE.SRGBColorSpace;
              buildScene(tex);
            }
          };
          img.onerror = () => { loaded++; if (loaded === total) buildScene(null); };
        }
      }
    } else {
      buildScene(null);
    }

    // ── Animation loop ──
    let animId;
    let clock = new THREE.Clock();
    const animate = () => {
      animId = requestAnimationFrame(animate);
      const dt = clock.getDelta();
      controls.update();

      // Animate clouds
      if (cloudsRef.current) {
        cloudsRef.current.children.forEach((c, i) => {
          c.position.x += dt * (1 + i * 0.3);
          if (c.position.x > 300) c.position.x = -300;
        });
      }

      // Animate wind particles
      if (windRef.current) {
        const pos = windRef.current.geometry.attributes.position;
        for (let i = 0; i < pos.count; i++) {
          pos.setX(i, pos.getX(i) + dt * 8);
          pos.setY(i, pos.getY(i) + Math.sin(Date.now() * 0.001 + i) * dt * 0.5);
          if (pos.getX(i) > 200) pos.setX(i, -200);
        }
        pos.needsUpdate = true;
      }

      renderer.render(scene, camera);
    };
    animate();

    const handleResize = () => {
      if (!containerRef.current) return;
      const w = containerRef.current.clientWidth;
      const h = containerRef.current.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      cancelAnimationFrame(animId);
      controls.dispose();
      renderer.dispose();
      if (containerRef.current?.contains(renderer.domElement)) {
        containerRef.current.removeChild(renderer.domElement);
      }
    };
  }, [data, realContext]);

  // Update sun position
  useEffect(() => {
    if (!sunLightRef.current) return;
    // Use real sun path data or computed position
    const sunData = data?.sun_path;
    const path = sunData?.[season] || [];
    const hourData = path.find(h => h.hour === Math.round(timeOfDay));

    let x, y, z;
    if (hourData) {
      const alt = THREE.MathUtils.degToRad(hourData.altitude);
      const az = THREE.MathUtils.degToRad(hourData.azimuth);
      const r = 120;
      x = r * Math.cos(alt) * Math.sin(az);
      y = r * Math.sin(alt) + 10;
      z = -r * Math.cos(alt) * Math.cos(az);
    } else {
      // Computed fallback for lat ~52°N
      const maxAlts = { summer: 60, equinox: 38, winter: 15 };
      const dayLens = { summer: 16, equinox: 12, winter: 8 };
      const maxAlt = maxAlts[season] || 38;
      const dayLen = dayLens[season] || 12;
      const sunrise = 12 - dayLen / 2;
      const frac = Math.max(0, Math.min(1, (timeOfDay - sunrise) / dayLen));
      const alt = THREE.MathUtils.degToRad(maxAlt * Math.sin(frac * Math.PI));
      const az = THREE.MathUtils.degToRad(90 + 180 * frac);
      const r = 120;
      x = r * Math.cos(alt) * Math.sin(az);
      y = Math.max(5, r * Math.sin(alt) + 10);
      z = -r * Math.cos(alt) * Math.cos(az);
    }

    sunLightRef.current.position.set(x, y, z);
    sunLightRef.current.intensity = Math.max(0.2, Math.min(1.5, y / 60));
    if (sunSphereRef.current) {
      sunSphereRef.current.position.set(x, y, z);
      sunSphereRef.current.material.color.setHSL(0.12, 0.9, 0.5 + 0.3 * Math.min(1, y / 80));
    }

    // Adjust sky tint based on time
    if (sceneRef.current) {
      const nightFactor = Math.max(0, 1 - y / 40);
      sceneRef.current.fog.color.setHSL(0.58, 0.3 - nightFactor * 0.2, 0.6 - nightFactor * 0.4);
    }
  }, [timeOfDay, season, data?.sun_path]);

  // Layer visibility
  useEffect(() => {
    if (!sceneRef.current) return;
    sceneRef.current.children.forEach(child => {
      if (child.name && layers[child.name] !== undefined) {
        child.visible = layers[child.name];
      }
    });
  }, [layers]);

  // Click handler
  const handleClick = useCallback((e) => {
    if (!containerRef.current || !sceneRef.current || !cameraRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    mouseRef.current.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouseRef.current.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycasterRef.current.setFromCamera(mouseRef.current, cameraRef.current);
    const intersects = raycasterRef.current.intersectObjects(sceneRef.current.children, true);
    if (!intersects.length) return;

    const hit = intersects[0];
    if (measureMode) {
      const newPoints = [...measurePoints, hit.point.clone()];
      if (newPoints.length === 2) {
        const dist = newPoints[0].distanceTo(newPoints[1]);
        setInfo(`Distance: ${dist.toFixed(1)}m`);
        const geom = new THREE.BufferGeometry().setFromPoints(newPoints);
        sceneRef.current.add(new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0x00e5ff, linewidth: 2 })));
        setMeasurePoints([]);
      } else {
        setMeasurePoints(newPoints);
        setInfo("Click second point to measure...");
      }
    } else {
      const obj = hit.object;
      if (obj.userData?.type === "building") {
        setInfo(`Building #${obj.userData.index + 1} — Height: ${obj.userData.height}m`);
      } else if (obj.userData?.type === "repd_project") {
        setInfo(`REPD: ${obj.userData.name || "?"} — ${obj.userData.technology} ${obj.userData.capacity_mw}MW [${obj.userData.status}]`);
      } else if (obj.userData?.type === "substation") {
        const hd = obj.userData.headroom_mw != null ? ` | Headroom: ${obj.userData.headroom_mw.toFixed(1)}MW` : "";
        setInfo(`Substation: ${obj.userData.name || "?"} — ${obj.userData.voltage_kv}kV (${obj.userData.source})${hd}`);
      } else if (obj.userData?.type === "power_line") {
        setInfo(`Power line: ${obj.userData.name || obj.userData.line_type || "?"} — ${obj.userData.voltage_kv}kV`);
      } else if (obj.userData?.type === "tec_project") {
        setInfo(`TEC Queue: ${obj.userData.name || "?"} — ${obj.userData.plant_type} ${obj.userData.capacity_mw}MW [${obj.userData.status}]`);
      } else if (obj.name === "exclusion_zone") {
        setInfo(`Exclusion: ${obj.userData.type} — ${obj.userData.reason}`);
      } else if (obj.name === "terrain") {
        setInfo(`Elevation: ${hit.point.y.toFixed(1)}m`);
      }
    }
  }, [measureMode, measurePoints]);

  const handleScreenshot = useCallback(() => {
    if (!rendererRef.current || !sceneRef.current || !cameraRef.current) return;
    rendererRef.current.render(sceneRef.current, cameraRef.current);
    const url = rendererRef.current.domElement.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = url;
    a.download = "digital-twin-screenshot.png";
    a.click();
  }, []);

  return (
    <div className="digital-twin-overlay">
      {/* Toolbar */}
      <div className="twin-toolbar">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button className="twin-close-btn" onClick={onClose}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
          <span style={{ fontWeight: 700, fontSize: 13, color: "#7c4dff", letterSpacing: 1 }}>3D DIGITAL TWIN</span>
          {data?.lat && <span style={{ fontSize: 11, color: "#4B5563" }}>{data.lat.toFixed(4)}N, {Math.abs(data.lon).toFixed(4)}{data.lon < 0 ? "W" : "E"}</span>}
          {!data && <span style={{ fontSize: 11, color: "#D4A018" }}>Demo environment — select a site for real data</span>}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          {/* Time of day slider */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 10, color: "#4B5563" }}>TIME</span>
            <input type="range" min="5" max="20" step="0.5" value={timeOfDay}
              onChange={(e) => setTimeOfDay(parseFloat(e.target.value))}
              style={{ width: 100, accentColor: "#7c4dff" }} />
            <span style={{ fontSize: 11, color: "#4B5563", minWidth: 36 }}>{Math.floor(timeOfDay)}:{String(Math.round((timeOfDay % 1) * 60)).padStart(2, "0")}</span>
          </div>

          {/* Season toggle */}
          <div style={{ display: "flex", gap: 2 }}>
            {["summer", "equinox", "winter"].map(s => (
              <button key={s} onClick={() => setSeason(s)}
                style={{
                  padding: "3px 8px", fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                  border: "1px solid " + (season === s ? "#7c4dff" : "rgba(0,0,0,0.1)"),
                  borderRadius: 2, cursor: "pointer", fontFamily: "inherit",
                  background: season === s ? "rgba(124,77,255,0.2)" : "transparent",
                  color: season === s ? "#7c4dff" : "#4B5563",
                }}>{s.slice(0, 3)}</button>
            ))}
          </div>

          {/* Layer toggles */}
          <div style={{ display: "flex", gap: 4 }}>
            {Object.keys(layers).map(key => (
              <button key={key} onClick={() => setLayers(l => ({ ...l, [key]: !l[key] }))}
                title={key.replace(/_/g, " ")}
                style={{
                  padding: "3px 6px", fontSize: 9, fontWeight: 700,
                  border: "1px solid " + (layers[key] ? "rgba(0,0,0,0.15)" : "rgba(0,0,0,0.1)"),
                  borderRadius: 2, cursor: "pointer", fontFamily: "inherit",
                  background: layers[key] ? "rgba(0,0,0,0.05)" : "transparent",
                  color: layers[key] ? "#1A1D23" : "#9CA3AF",
                  textTransform: "uppercase",
                }}>{key.slice(0, 4)}</button>
            ))}
          </div>

          {/* Measure + Screenshot */}
          <button onClick={() => { setMeasureMode(!measureMode); setMeasurePoints([]); setInfo(null); }}
            title="Measure distance"
            style={{
              padding: "4px 8px", fontSize: 10, fontWeight: 700,
              border: "1px solid " + (measureMode ? "#D4A018" : "rgba(0,0,0,0.1)"),
              borderRadius: 2, cursor: "pointer", fontFamily: "inherit",
              background: measureMode ? "rgba(0,229,255,0.15)" : "transparent",
              color: measureMode ? "#D4A018" : "#4B5563",
            }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
            </svg>
          </button>
          <button onClick={handleScreenshot} title="Screenshot"
            style={{ padding: "4px 8px", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 2, cursor: "pointer", background: "transparent", color: "#4B5563" }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z" /><circle cx="12" cy="13" r="4" />
            </svg>
          </button>
        </div>
      </div>

      {/* Canvas */}
      <div className="twin-canvas" ref={containerRef} onClick={handleClick} />

      {/* Real infrastructure summary strip */}
      {realContext && (realContext.nearby_renewables?.length > 0 || realContext.grid_substations?.length > 0) && (
        <div style={{
          position: "absolute", bottom: 40, left: 12, right: 12, display: "flex", gap: 12,
          background: "rgba(10,10,20,0.75)", borderRadius: 4, padding: "6px 12px",
          backdropFilter: "blur(6px)", zIndex: 10,
        }}>
          {realContext.total_renewable_mw > 0 && (
            <span style={{ fontSize: 11, color: "#fdd835", fontWeight: 700 }}>
              {realContext.total_renewable_mw.toFixed(1)} MW RE nearby
            </span>
          )}
          {realContext.nearby_renewables?.length > 0 && (
            <span style={{ fontSize: 11, color: "#aaa" }}>
              {realContext.nearby_renewables.length} REPD projects
            </span>
          )}
          {realContext.osm_substations?.length > 0 && (
            <span style={{ fontSize: 11, color: "#ff7043" }}>
              {realContext.osm_substations.length} OSM substations
            </span>
          )}
          {realContext.grid_substations?.length > 0 && (
            <span style={{ fontSize: 11, color: "#ffa726" }}>
              {realContext.grid_substations.length} DNO substations
            </span>
          )}
          {realContext.osm_lines?.length > 0 && (
            <span style={{ fontSize: 11, color: "#42a5f5" }}>
              {realContext.osm_lines.length} power lines
            </span>
          )}
          {realContext.tec_queue?.length > 0 && (
            <span style={{ fontSize: 11, color: "#ce93d8" }}>
              {realContext.tec_queue.length} TEC queue
            </span>
          )}
          {realContext.technology_mix && Object.keys(realContext.technology_mix).length > 0 && (
            <span style={{ fontSize: 10, color: "#777", marginLeft: 8 }}>
              Mix: {Object.entries(realContext.technology_mix).map(([t, mw]) => `${t.replace("Solar Photovoltaics", "Solar").replace("Wind Onshore", "Wind")} ${mw.toFixed(0)}MW`).join(", ")}
            </span>
          )}
        </div>
      )}

      {/* Info panel */}
      {info && (
        <div className="twin-info-panel">
          <div style={{ fontSize: 12, color: "#1A1D23" }}>{info}</div>
          <button onClick={() => setInfo(null)}
            style={{ position: "absolute", top: 6, right: 8, background: "none", border: "none", color: "#4B5563", cursor: "pointer", fontSize: 14 }}>
            x
          </button>
        </div>
      )}
    </div>
  );
}

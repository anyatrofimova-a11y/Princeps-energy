import React, { useEffect, useRef, useState, useCallback } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

const COMP_COLORS = {
  PNL: 0x1e88e5, INV: 0xff9800, BAT: 0x4caf50, TRF: 0x9e9e9e,
  MON: 0xe91e63, CBL: 0x607d8b, MNT: 0x795548, BOS: 0x00bcd4,
};

const SUN_PATH_COLORS = { summer: 0xffeb3b, winter: 0x2196f3, equinox: 0xff9800 };

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
  for (let i = 0; i < pos.count; i++) {
    const val = vals[i] ?? vMin;
    const norm = (val - vMin) / range;
    pos.setY(i, norm * 40);
    colors[i * 3] = 0.25 + 0.55 * norm;
    colors[i * 3 + 1] = 0.6 - 0.25 * norm;
    colors[i * 3 + 2] = 0.1 + 0.05 * norm;
  }
  geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geom.computeVertexNormals();

  // Use satellite imagery texture if available, fall back to vertex colors
  const matOpts = { side: THREE.DoubleSide, roughness: 0.85, metalness: 0.05 };
  if (satelliteTexture) {
    matOpts.map = satelliteTexture;
    matOpts.vertexColors = false;
  } else {
    matOpts.vertexColors = true;
  }
  const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial(matOpts));
  mesh.receiveShadow = true;
  mesh.name = "terrain";
  return mesh;
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

    // Simple box for each building (approximate)
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
    mesh.userData.type = "building";
    mesh.userData.height = height;
    mesh.userData.index = idx;
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

function buildDetectionOverlays(detections) {
  if (!detections?.findings) return null;
  const group = new THREE.Group();
  group.name = "detections";
  const findings = detections.findings;

  // Exclusion zones as red planes
  const exclusions = findings.exclusion_zones || [];
  exclusions.forEach((ez, i) => {
    const geom = new THREE.PlaneGeometry(15, 15);
    geom.rotateX(-Math.PI / 2);
    const mesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({
      color: 0xda1e28, transparent: true, opacity: 0.25, side: THREE.DoubleSide,
    }));
    mesh.position.set(-40 + i * 30, 0.5, -30 + i * 20);
    mesh.name = "exclusion_zone";
    mesh.userData.type = ez.type;
    mesh.userData.reason = ez.reason;
    group.add(mesh);
  });

  // Usable area as green plane (proportional to usable_area_pct)
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

  retrofitData.forEach((feature, idx) => {
    const props = feature.properties || {};
    const type = props.type || "extension";
    const height = props.height_m || 3;
    const coords = feature.geometry?.coordinates?.[0];
    if (!coords || coords.length < 3) return;

    // Extension volumes — semi-transparent purple
    if (type.includes("extension")) {
      const shape = new THREE.Shape();
      coords.forEach((c, i) => {
        if (i === 0) shape.moveTo(c[0], c[1]);
        else shape.lineTo(c[0], c[1]);
      });
      const extrudeSettings = { depth: height, bevelEnabled: false };
      const geom = new THREE.ExtrudeGeometry(shape, extrudeSettings);
      geom.rotateX(-Math.PI / 2);
      const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({
        color: 0x8e24aa, transparent: true, opacity: 0.45, roughness: 0.6,
      }));
      mesh.castShadow = true;
      mesh.name = `retrofit_${type}`;
      mesh.userData = props;
      group.add(mesh);

      // Wireframe outline
      const wire = new THREE.LineSegments(
        new THREE.EdgesGeometry(geom),
        new THREE.LineBasicMaterial({ color: 0xce93d8, linewidth: 2 })
      );
      group.add(wire);
    }
  });

  // Add insulation shell indicator (thin overlay on buildings)
  const shellGeom = new THREE.BoxGeometry(22, 10, 16);
  const shellMat = new THREE.MeshStandardMaterial({
    color: 0xff9800, transparent: true, opacity: 0.15, side: THREE.DoubleSide, roughness: 1,
  });
  const shell = new THREE.Mesh(shellGeom, shellMat);
  shell.position.set(0, 5, 0);
  shell.name = "insulation_shell";
  group.add(shell);

  // Solar panels on roof
  const panelGeom = new THREE.PlaneGeometry(8, 5);
  panelGeom.rotateX(-Math.PI / 4);
  const panelMat = new THREE.MeshStandardMaterial({ color: 0x1565c0, metalness: 0.8, roughness: 0.2 });
  const panel = new THREE.Mesh(panelGeom, panelMat);
  panel.position.set(0, 11, -2);
  panel.name = "solar_panels";
  group.add(panel);

  // Heat pump unit in garden
  const hpGeom = new THREE.BoxGeometry(1.2, 0.9, 0.5);
  const hpMat = new THREE.MeshStandardMaterial({ color: 0xeeeeee, roughness: 0.5 });
  const hp = new THREE.Mesh(hpGeom, hpMat);
  hp.position.set(-12, 0.45, 8);
  hp.name = "heat_pump";
  // Fan grill on front
  const fanGeom = new THREE.CircleGeometry(0.3, 16);
  const fanMat = new THREE.MeshBasicMaterial({ color: 0x333333 });
  const fan = new THREE.Mesh(fanGeom, fanMat);
  fan.position.set(-12, 0.45, 8.26);
  group.add(hp);
  group.add(fan);

  return group;
}

export default function DigitalTwin({ data, onClose }) {
  const containerRef = useRef(null);
  const rendererRef = useRef(null);
  const sceneRef = useRef(null);
  const cameraRef = useRef(null);
  const controlsRef = useRef(null);
  const sunLightRef = useRef(null);
  const sunSphereRef = useRef(null);
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
  });

  // Build scene
  useEffect(() => {
    if (!containerRef.current) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a2030);
    scene.fog = new THREE.Fog(0x1a2030, 300, 600);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(60, containerRef.current.clientWidth / containerRef.current.clientHeight, 0.5, 1000);
    camera.position.set(120, 80, 120);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    containerRef.current.appendChild(renderer.domElement);
    rendererRef.current = renderer;

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxDistance = 400;
    controls.minDistance = 20;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.target.set(0, 10, 0);
    controlsRef.current = controls;

    // Lights
    const ambient = new THREE.AmbientLight(0x404060, 0.6);
    scene.add(ambient);
    const hemi = new THREE.HemisphereLight(0x88aacc, 0x443322, 0.4);
    scene.add(hemi);
    const sunLight = new THREE.DirectionalLight(0xffffff, 1.2);
    sunLight.position.set(50, 80, 30);
    sunLight.castShadow = true;
    sunLight.shadow.mapSize.set(2048, 2048);
    sunLight.shadow.camera.left = -120;
    sunLight.shadow.camera.right = 120;
    sunLight.shadow.camera.top = 120;
    sunLight.shadow.camera.bottom = -120;
    scene.add(sunLight);
    sunLightRef.current = sunLight;

    // Sun indicator sphere
    const sunGeom = new THREE.SphereGeometry(3, 16, 16);
    const sunMat = new THREE.MeshBasicMaterial({ color: 0xffeb3b });
    const sunSphere = new THREE.Mesh(sunGeom, sunMat);
    sunSphere.position.copy(sunLight.position);
    scene.add(sunSphere);
    sunSphereRef.current = sunSphere;

    // Ground plane (for shadow catching)
    const groundGeom = new THREE.PlaneGeometry(600, 600);
    groundGeom.rotateX(-Math.PI / 2);
    const ground = new THREE.Mesh(groundGeom, new THREE.ShadowMaterial({ opacity: 0.3 }));
    ground.receiveShadow = true;
    ground.position.y = -0.1;
    scene.add(ground);

    // Load satellite imagery as terrain texture, then build scene
    const buildScene = (satTexture) => {
      if (data?.heightmap) {
        const terrain = buildTerrainMesh(data.heightmap, satTexture);
        if (terrain) scene.add(terrain);
      }
      if (data?.buildings) {
        const bldgs = buildBuildings(data.buildings);
        if (bldgs) scene.add(bldgs);
      }
      if (data?.solar_layout) {
        const layout = buildSolarLayout(data.solar_layout);
        if (layout) scene.add(layout);
      }
      if (data?.sun_path) {
        const paths = buildSunPaths(data.sun_path);
        if (paths) scene.add(paths);
      }
      if (data?.vision_detections) {
        const overlays = buildDetectionOverlays(data.vision_detections);
        if (overlays) scene.add(overlays);
      }
      if (data?.retrofit_geometry) {
        const retro = buildRetrofitGeometry(data.retrofit_geometry);
        if (retro) {
          retro.visible = false; // off by default, toggled via layer control
          scene.add(retro);
        }
      }
    };

    // Load a 3x3 grid of satellite tiles and composite into a single texture
    const tile = data?.satellite_tile;
    if (tile?.url) {
      const z = tile.zoom;
      const cx = tile.tile_x;
      const cy = tile.tile_y;
      const GRID = 3; // 3x3 tiles = 768x768 px
      const TILE_PX = 256;
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
          const tx = cx + dx;
          const ty = cy + dy;
          img.src = `${baseUrl}/${z}/${ty}/${tx}`;
          img.onload = () => {
            ctx2d.drawImage(img, (dx + 1) * TILE_PX, (dy + 1) * TILE_PX, TILE_PX, TILE_PX);
            loaded++;
            if (loaded === total) {
              const tex = new THREE.CanvasTexture(canvas);
              tex.colorSpace = THREE.SRGBColorSpace;
              buildScene(tex);
            }
          };
          img.onerror = () => {
            loaded++;
            if (loaded === total) {
              const tex = loaded > 0 ? new THREE.CanvasTexture(canvas) : null;
              if (tex) tex.colorSpace = THREE.SRGBColorSpace;
              buildScene(tex);
            }
          };
        }
      }
    } else {
      buildScene(null);
    }

    // Animation loop
    let animId;
    const animate = () => {
      animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    // Resize handler
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
  }, [data]);

  // Update sun position based on time/season
  useEffect(() => {
    if (!sunLightRef.current || !data?.sun_path) return;
    const path = data.sun_path[season] || [];
    const hourData = path.find(h => h.hour === Math.round(timeOfDay)) || path[Math.floor(path.length / 2)];
    if (!hourData) return;

    const alt = THREE.MathUtils.degToRad(hourData.altitude);
    const az = THREE.MathUtils.degToRad(hourData.azimuth);
    const r = 100;
    const x = r * Math.cos(alt) * Math.sin(az);
    const y = r * Math.sin(alt) + 10;
    const z = -r * Math.cos(alt) * Math.cos(az);
    sunLightRef.current.position.set(x, Math.max(y, 10), z);
    if (sunSphereRef.current) sunSphereRef.current.position.set(x, Math.max(y, 10), z);
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

  // Click handler for measurement / info
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
        // Draw line
        const geom = new THREE.BufferGeometry().setFromPoints(newPoints);
        const line = new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0x00e5ff, linewidth: 2 }));
        sceneRef.current.add(line);
        setMeasurePoints([]);
      } else {
        setMeasurePoints(newPoints);
        setInfo("Click second point to measure...");
      }
    } else {
      const obj = hit.object;
      if (obj.userData?.type === "building") {
        setInfo(`Building #${obj.userData.index + 1} — Height: ${obj.userData.height}m`);
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
                }}>
                {s.slice(0, 3)}
              </button>
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
                }}>
                {key.slice(0, 4)}
              </button>
            ))}
          </div>

          {/* Tools */}
          <button onClick={() => { setMeasureMode(!measureMode); setMeasurePoints([]); setInfo(null); }}
            title="Measure distance"
            style={{
              padding: "4px 8px", fontSize: 10, fontWeight: 700,
              border: "1px solid " + (measureMode ? "#7c5cfc" : "rgba(0,0,0,0.1)"),
              borderRadius: 2, cursor: "pointer", fontFamily: "inherit",
              background: measureMode ? "rgba(0,229,255,0.15)" : "transparent",
              color: measureMode ? "#7c5cfc" : "#4B5563",
            }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
            </svg>
          </button>
          <button onClick={handleScreenshot} title="Screenshot"
            style={{
              padding: "4px 8px", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 2,
              cursor: "pointer", background: "transparent", color: "#4B5563",
            }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z" />
              <circle cx="12" cy="13" r="4" />
            </svg>
          </button>
        </div>
      </div>

      {/* Canvas */}
      <div className="twin-canvas" ref={containerRef} onClick={handleClick} />

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

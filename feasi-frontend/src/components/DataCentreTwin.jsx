import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, OrthographicCamera, Grid, Html } from "@react-three/drei";
import * as THREE from "three";
import { useSite } from "../SiteContext";
import PostprocessingEffects from "./PostprocessingEffects";

/* ── Design Tokens ───────────────────────────────────────────────────────── */
const T = {
  bg: "#F2F3F5",
  accent: "#D4A018",
  panel: "rgba(255, 255, 255, 0.95)",
  border: "1px solid rgba(108, 92, 231, 0.2)",
  text: "#1A1D23",
  textSec: "#4B5563",
  green: "#24a148",
  red: "#da1e28",
  orange: "#f1c21b",
  blue: "#1890ff",
  cyan: "#00bcd4",
  purple: "#D4A018",
};

/* ── Utils ────────────────────────────────────────────────────────────────── */
function fmtGbp(v) {
  if (v == null) return "--";
  if (v >= 1_000_000) return `£${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1000) return `£${(v / 1000).toFixed(0)}k`;
  return `£${v.toFixed(0)}`;
}
function fmtKw(v) {
  if (v == null) return "--";
  if (v >= 1000) return `${(v / 1000).toFixed(1)} MW`;
  return `${v.toFixed(0)} kW`;
}

function tempColor(t) {
  if (t > 30) return T.red;
  if (t > 27) return T.orange;
  return T.green;
}
// HSL thermal gradient (Grafana-style: blue→green→yellow→red)
function tempToHSL(temp, min = 18, max = 35) {
  const t = Math.max(0, Math.min(1, (temp - min) / (max - min)));
  const hue = 0.67 - t * 0.67; // blue (0.67) → red (0.0)
  return new THREE.Color().setHSL(hue, 0.85, 0.5);
}
function tempColorHex(t) {
  return tempToHSL(t);
}
function statusColor(s) {
  if (s === "critical") return T.red;
  if (s === "warning") return T.orange;
  return T.green;
}
// Lerp speed for smooth state transitions (Grafana pattern)
const LERP_SPEED = 5;

const REDUNDANCY_OPTIONS = ["N", "N+1", "2N", "2N+1"];
const COOLING_OPTIONS = ["mechanical", "free_cooling", "hybrid", "evaporative"];
const TIER_OPTIONS = [1, 2, 3, 4];
const VIEW_MODES = ["plan", "design", "monitor", "simulate", "feasibility"];

/* ═══════════════════════════════════════════════════════════════════════════
   3D Scene Components — Rack-level DC visualization
   ═══════════════════════════════════════════════════════════════════════════ */

function ServerRack({ position, rack, index, selected, onClick, colorBy }) {
  const meshRef = useRef();
  const lerpRef = useRef({ scaleY: 1, emissiveI: 0.08 });
  const [hovered, setHovered] = useState(false);

  // HSL thermal gradient for temperature, load-proportional height
  const col = useMemo(() => {
    if (colorBy === "thermal") return tempToHSL(rack.inlet_temp_c || 22);
    if (colorBy === "load") {
      const norm = Math.min(1, (rack.it_load_kw || 0) / 12);
      return new THREE.Color().setHSL(0.67 - norm * 0.67, 0.85, 0.5);
    }
    if (rack.status === "critical") return new THREE.Color(0xda1e28);
    if (rack.status === "warning") return new THREE.Color(0xf1c21b);
    return new THREE.Color(0x3a3f55);
  }, [rack, colorBy]);

  // Load-proportional height (Grafana pattern: scaleY = 0.5 + 0.7 * load)
  const targetScaleY = useMemo(() => {
    const norm = Math.min(1, (rack.it_load_kw || 0) / 12);
    return 0.5 + 0.7 * norm;
  }, [rack.it_load_kw]);

  useFrame((state, delta) => {
    if (!meshRef.current) return;
    const lr = lerpRef.current;
    const t = state.clock.elapsedTime;
    const idx = index || 0;

    // Smooth lerp scale transition
    lr.scaleY += (targetScaleY - lr.scaleY) * Math.min(1, LERP_SPEED * delta);
    meshRef.current.scale.y = lr.scaleY;
    meshRef.current.position.y = lr.scaleY; // Keep base on ground

    // Emissive: idle breathing + state overlays (Grafana pattern)
    let targetEmissive;
    if (rack.status === "critical") {
      targetEmissive = 0.85 + Math.sin(t * 5 + idx) * 0.15; // fast alert pulse
    } else if (rack.status === "warning") {
      targetEmissive = 0.35 + Math.sin(t * 3 + idx * 0.5) * 0.15;
    } else if (selected) {
      targetEmissive = 0.5;
    } else if (hovered) {
      targetEmissive = 0.35;
    } else {
      // Staggered idle breathing (Grafana: 1 + 0.012*sin(t*0.002 + i*0.3))
      targetEmissive = 0.08 + Math.sin(t * 2 + idx * 0.3) * 0.04;
    }
    lr.emissiveI += (targetEmissive - lr.emissiveI) * Math.min(1, LERP_SPEED * delta);
    meshRef.current.material.emissiveIntensity = lr.emissiveI;
  });

  return (
    <group position={position}>
      <mesh
        ref={meshRef}
        onClick={(e) => { e.stopPropagation(); onClick?.(rack.id); }}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { setHovered(false); document.body.style.cursor = "auto"; }}
        castShadow
      >
        <boxGeometry args={[0.55, 2.0, 0.9]} />
        <meshStandardMaterial
          color={col}
          emissive={col}
          emissiveIntensity={0.08}
          transparent
          opacity={hovered ? 1 : 0.92}
          roughness={0.2}
          metalness={0.7}
        />
      </mesh>
      {/* Front status LED strip */}
      <mesh position={[0, 1.05, 0.46]}>
        <boxGeometry args={[0.04, 0.3, 0.01]} />
        <meshBasicMaterial color={rack.status === "critical" ? T.red : rack.status === "warning" ? T.orange : T.green} />
      </mesh>
      {/* Rack back panel (Grafana: subtle glow on hover) */}
      <mesh position={[0, 0, -0.46]}>
        <boxGeometry args={[0.55, 2.0, 0.02]} />
        <meshStandardMaterial
          color="#1a1f2e"
          emissive={hovered ? "#3366cc" : "#111"}
          emissiveIntensity={hovered ? 0.22 : 0.02}
          roughness={0.4}
          metalness={0.5}
        />
      </mesh>
      {(hovered || selected) && (
        <Html position={[0, 1.8, 0]} center distanceFactor={10} style={{ pointerEvents: "none" }}>
          <div style={{
            background: T.panel, border: T.border, borderRadius: 6,
            padding: "6px 12px", whiteSpace: "nowrap", fontSize: 10,
            color: T.text, fontFamily: "system-ui", minWidth: 100,
            boxShadow: "0 4px 16px rgba(0,0,0,0.5)",
          }}>
            <div style={{ fontWeight: 700, marginBottom: 2, color: T.accent }}>Rack {rack.id}</div>
            <div style={{ display: "flex", gap: 12 }}>
              <div><span style={{ color: "#666" }}>Load </span><span style={{ color: T.blue }}>{rack.it_load_kw?.toFixed(1) ?? "--"} kW</span></div>
              <div><span style={{ color: "#666" }}>Inlet </span><span style={{ color: tempColor(rack.inlet_temp_c) }}>{rack.inlet_temp_c?.toFixed(1) ?? "--"}°C</span></div>
            </div>
            {rack.humidity_pct && <div><span style={{ color: "#666" }}>RH </span><span style={{ color: T.cyan }}>{rack.humidity_pct}%</span></div>}
          </div>
        </Html>
      )}
    </group>
  );
}

/* ── Cooling Unit ── */
function CoolingUnit({ position }) {
  const meshRef = useRef();
  useFrame((state) => {
    if (meshRef.current) {
      meshRef.current.rotation.y = state.clock.elapsedTime * 0.5;
    }
  });
  return (
    <group position={position}>
      <mesh castShadow>
        <boxGeometry args={[2, 1.5, 2]} />
        <meshStandardMaterial color="#1a3a4a" emissive="#00bcd4" emissiveIntensity={0.08} roughness={0.3} metalness={0.6} />
      </mesh>
      {/* Spinning fan */}
      <mesh ref={meshRef} position={[0, 0.85, 0]}>
        <cylinderGeometry args={[0.5, 0.5, 0.05, 16]} />
        <meshStandardMaterial color="#555" metalness={0.9} roughness={0.2} />
      </mesh>
    </group>
  );
}

/* ── UPS Unit ── */
function UPSUnit({ position }) {
  return (
    <group position={position}>
      <mesh castShadow>
        <boxGeometry args={[1.2, 1.8, 0.8]} />
        <meshStandardMaterial color="#2a1f4e" emissive="#D4A018" emissiveIntensity={0.1} roughness={0.3} metalness={0.7} />
      </mesh>
      <Html position={[0, 1.2, 0.41]} center distanceFactor={12} style={{ pointerEvents: "none" }}>
        <div style={{ fontSize: 8, color: T.accent, fontWeight: 600, fontFamily: "system-ui" }}>UPS</div>
      </Html>
    </group>
  );
}

/* ── Hot/Cold Aisle Airflow Particles (Grafana-inspired) ── */
function AirflowParticles({ row, side, rackCount }) {
  const ref = useRef();
  const count = Math.min(rackCount * 2, 40);
  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      arr[i * 3] = Math.random() * rackCount * 0.7;
      arr[i * 3 + 1] = 0.3 + Math.random() * 1.8;
      arr[i * 3 + 2] = row * 3.6 + side * 1.2 + (side === 0 ? -0.5 : 0.5);
    }
    return arr;
  }, [count, rackCount, row, side]);

  useFrame((state) => {
    if (!ref.current) return;
    const pos = ref.current.geometry.attributes.position;
    for (let i = 0; i < count; i++) {
      // Float upward (hot aisle) or sideways (cold aisle)
      pos.array[i * 3 + 1] += 0.008 + Math.sin(state.clock.elapsedTime + i) * 0.002;
      if (pos.array[i * 3 + 1] > 2.5) pos.array[i * 3 + 1] = 0.3;
    }
    pos.needsUpdate = true;
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" array={positions} itemSize={3} count={count} />
      </bufferGeometry>
      <pointsMaterial size={0.04} color={side === 1 ? "#ff4444" : "#4488ff"} transparent opacity={0.4} sizeAttenuation />
    </points>
  );
}

/* ── Network Interconnect Lines (Grafana: ring topology per row) ── */
function NetworkLines({ rackLayout }) {
  const lineRef = useRef();

  useFrame((state) => {
    if (lineRef.current) {
      lineRef.current.material.opacity = 0.15 + Math.sin(state.clock.elapsedTime * 1.5) * 0.08;
    }
  });

  // Build ring topology lines per row
  const points = useMemo(() => {
    if (rackLayout.length < 2) return [];
    const rows = {};
    rackLayout.forEach(r => {
      if (!rows[r.row]) rows[r.row] = [];
      rows[r.row].push(r);
    });
    const pts = [];
    Object.values(rows).forEach(rowRacks => {
      rowRacks.sort((a, b) => a.position - b.position);
      for (let i = 0; i < rowRacks.length - 1; i++) {
        pts.push(
          new THREE.Vector3(rowRacks[i].x, 2.3, rowRacks[i].z),
          new THREE.Vector3(rowRacks[i + 1].x, 2.3, rowRacks[i + 1].z),
        );
      }
    });
    return pts;
  }, [rackLayout]);

  if (points.length === 0) return null;
  return (
    <lineSegments ref={lineRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          array={new Float32Array(points.flatMap(p => [p.x, p.y, p.z]))}
          itemSize={3}
          count={points.length}
        />
      </bufferGeometry>
      <lineBasicMaterial color="#00bcd4" transparent opacity={0.2} />
    </lineSegments>
  );
}

/* ── Floor Thermal Heatmap (datacenter-planner / heatmap-threejs pattern) ── */
function ThermalHeatmap({ rackLayout, telemetry, visible }) {
  const meshRef = useRef();
  const canvasRef = useRef(document.createElement("canvas"));
  const textureRef = useRef(null);

  useEffect(() => {
    if (!visible) return;
    const canvas = canvasRef.current;
    const res = 256;
    canvas.width = res;
    canvas.height = res;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, res, res);

    // Map rack positions to canvas and paint thermal blobs
    const racks = telemetry?.racks || [];
    const rackMap = {};
    racks.forEach(r => { rackMap[r.id] = r; });

    const sceneW = 40, sceneD = 20; // approximate scene bounds
    const offX = 5, offZ = 5;

    rackLayout.forEach(pos => {
      const rd = rackMap[pos.id];
      const temp = rd?.inlet_temp_c || 22;
      const norm = Math.max(0, Math.min(1, (temp - 18) / 17)); // 18-35 range
      const cx = ((pos.x + offX) / sceneW) * res;
      const cy = ((pos.z + offZ) / sceneD) * res;
      const radius = res * 0.08;

      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
      // HSL: blue(240)→green(120)→yellow(60)→red(0)
      const hue = Math.round(240 - norm * 240);
      grad.addColorStop(0, `hsla(${hue}, 85%, 50%, 0.6)`);
      grad.addColorStop(0.5, `hsla(${hue}, 85%, 50%, 0.2)`);
      grad.addColorStop(1, `hsla(${hue}, 85%, 50%, 0)`);
      ctx.fillStyle = grad;
      ctx.fillRect(cx - radius, cy - radius, radius * 2, radius * 2);
    });

    if (!textureRef.current) {
      textureRef.current = new THREE.CanvasTexture(canvas);
    } else {
      textureRef.current.image = canvas;
    }
    textureRef.current.needsUpdate = true;
    if (meshRef.current) {
      meshRef.current.material.map = textureRef.current;
      meshRef.current.material.needsUpdate = true;
    }
  }, [rackLayout, telemetry, visible]);

  if (!visible) return null;
  return (
    <mesh ref={meshRef} rotation={[-Math.PI / 2, 0, 0]} position={[15, 0.02, 5]}>
      <planeGeometry args={[40, 20]} />
      <meshBasicMaterial transparent opacity={0.55} depthWrite={false} />
    </mesh>
  );
}

/* ── Rack Detail LOD — expanded U-slot view on selection ── */
function RackDetailLOD({ position, rack, visible }) {
  if (!visible) return null;
  const slots = 42; // 42U rack
  const usedSlots = Math.round(slots * Math.min(1, (rack.it_load_kw || 0) / 12));

  return (
    <group position={position}>
      {/* Expanded rack frame */}
      <mesh position={[0, 1.2, 0]}>
        <boxGeometry args={[0.7, 2.4, 1.0]} />
        <meshStandardMaterial color="#0d1117" transparent opacity={0.5} roughness={0.8} />
      </mesh>
      {/* U-slots (green=occupied, dark=empty) */}
      {Array.from({ length: Math.min(slots, 21) }).map((_, i) => {
        const yPos = 0.1 + i * 0.1;
        const occupied = i < Math.ceil(usedSlots / 2);
        return (
          <mesh key={i} position={[0, yPos, 0.35]}>
            <boxGeometry args={[0.5, 0.06, 0.01]} />
            <meshStandardMaterial
              color={occupied ? "#1a6630" : "#1a1a2e"}
              emissive={occupied ? "#24a148" : "#000"}
              emissiveIntensity={occupied ? 0.3 : 0}
            />
          </mesh>
        );
      })}
      {/* Label */}
      <Html position={[0, 2.6, 0]} center distanceFactor={8} style={{ pointerEvents: "none" }}>
        <div style={{
          background: T.panel, border: T.border, borderRadius: 6,
          padding: "8px 14px", fontSize: 10, color: T.text, fontFamily: "system-ui",
          minWidth: 130, boxShadow: "0 4px 20px rgba(0,0,0,0.6)",
        }}>
          <div style={{ fontWeight: 700, color: T.accent, marginBottom: 4 }}>Rack {rack.id} — Device View</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2px 12px", fontSize: 9 }}>
            <span style={{ color: "#666" }}>Load</span><span style={{ color: T.blue }}>{rack.it_load_kw?.toFixed(1)} kW</span>
            <span style={{ color: "#666" }}>Inlet</span><span style={{ color: tempColor(rack.inlet_temp_c) }}>{rack.inlet_temp_c}°C</span>
            <span style={{ color: "#666" }}>Outlet</span><span style={{ color: tempColor(rack.outlet_temp_c) }}>{rack.outlet_temp_c}°C</span>
            <span style={{ color: "#666" }}>U-Slots</span><span>{usedSlots}/{slots} occupied</span>
            <span style={{ color: "#666" }}>Humidity</span><span style={{ color: T.cyan }}>{rack.humidity_pct}%</span>
            <span style={{ color: "#666" }}>Status</span>
            <span style={{ color: statusColor(rack.status), fontWeight: 600 }}>{rack.status}</span>
          </div>
        </div>
      </Html>
    </group>
  );
}

/* ── DC 3D Scene ── */
function DCScene({ rackLayout, telemetry, selectedRack, onSelectRack, colorBy, cameraMode, showHeatmap }) {
  const racks = telemetry?.racks || [];
  const rackMap = useMemo(() => {
    const m = {};
    racks.forEach(r => { m[r.id] = r; });
    return m;
  }, [racks]);

  // Unique rows for airflow particles
  const rowSet = useMemo(() => {
    const s = new Set();
    rackLayout.forEach(r => s.add(r.row));
    return [...s];
  }, [rackLayout]);

  return (
    <>
      <ambientLight intensity={0.35} />
      <directionalLight position={[20, 30, 10]} intensity={0.65} castShadow
        shadow-mapSize-width={1024} shadow-mapSize-height={1024} />
      <pointLight position={[-10, 15, -10]} intensity={0.25} color="#D4A018" />
      {/* Hemisphere fill light (Grafana pattern) */}
      <hemisphereLight args={["#2a2f45", "#0a0e17", 0.4]} />

      <Grid
        args={[80, 80]}
        position={[0, -0.01, 0]}
        cellSize={1}
        cellColor="#1a1f2e"
        sectionSize={5}
        sectionColor="#252a3a"
        fadeDistance={60}
        fadeStrength={1}
      />

      {/* Server racks */}
      {rackLayout.map((pos, i) => {
        const rackData = rackMap[pos.id] || { id: pos.id, status: "normal", it_load_kw: 0, inlet_temp_c: 22 };
        return (
          <ServerRack
            key={pos.id}
            position={[pos.x, 1, pos.z]}
            rack={rackData}
            index={i}
            selected={selectedRack === pos.id}
            onClick={onSelectRack}
            colorBy={colorBy}
          />
        );
      })}

      {/* Hot/cold aisle airflow particles */}
      {rowSet.map(row => (
        <React.Fragment key={`air-${row}`}>
          <AirflowParticles row={row} side={0} rackCount={Math.min(20, rackLayout.length)} />
          <AirflowParticles row={row} side={1} rackCount={Math.min(20, rackLayout.length)} />
        </React.Fragment>
      ))}

      {/* Network interconnect lines */}
      <NetworkLines rackLayout={rackLayout} />

      {/* Cooling units at ends of rows */}
      {rackLayout.length > 0 && (
        <>
          <CoolingUnit position={[-3, 0.75, 0]} />
          <CoolingUnit position={[-3, 0.75, 3.6]} />
          {rackLayout[rackLayout.length - 1] && (
            <CoolingUnit position={[rackLayout[rackLayout.length - 1].x + 3, 0.75, 0]} />
          )}
        </>
      )}

      {/* UPS modules */}
      <UPSUnit position={[-3, 0.9, -3]} />
      <UPSUnit position={[-1.5, 0.9, -3]} />

      {/* Thermal heatmap overlay (datacenter-planner pattern) */}
      <ThermalHeatmap rackLayout={rackLayout} telemetry={telemetry} visible={showHeatmap} />

      {/* Rack detail LOD — expanded device view for selected rack */}
      {rackLayout.map(pos => {
        const rd = rackMap[pos.id];
        return (
          <RackDetailLOD
            key={`lod-${pos.id}`}
            position={[pos.x, 0, pos.z]}
            rack={rd || { id: pos.id, status: "normal", it_load_kw: 0, inlet_temp_c: 22 }}
            visible={selectedRack === pos.id}
          />
        );
      })}

      {/* Building shell, external infrastructure */}
      <BuildingShell rackLayout={rackLayout} />
      <CoolingTowerCompound rackLayout={rackLayout} />
      <GeneratorCompound rackLayout={rackLayout} />
      <SubstationModel rackLayout={rackLayout} />

      {/* Floor plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[120, 120]} />
        <meshStandardMaterial color="#0c1018" roughness={0.9} />
      </mesh>

      {/* 2D orthographic camera for planning mode (datacenter-planner pattern) */}
      {cameraMode === "2d" && (
        <OrthographicCamera
          makeDefault
          position={[15, 30, 5]}
          zoom={22}
          near={0.1}
          far={100}
          rotation={[-Math.PI / 2, 0, 0]}
        />
      )}

      <OrbitControls
        target={[rackLayout.length > 0 ? rackLayout[Math.floor(rackLayout.length / 2)]?.x || 5 : 5, cameraMode === "2d" ? 0 : 1, 2]}
        maxDistance={cameraMode === "2d" ? 60 : 50}
        minDistance={cameraMode === "2d" ? 10 : 3}
        maxPolarAngle={cameraMode === "2d" ? 0.01 : Math.PI / 2.1}
        minPolarAngle={cameraMode === "2d" ? 0 : 0}
        enableRotate={cameraMode !== "2d"}
      />
    </>
  );
}

/* ── Hourly CFE Chart ── */
function CFEChart({ data, height = 160 }) {
  if (!data?.hours) return null;
  const hours = data.hours;
  const w = 280, h = height, pad = 24;
  const chartW = w - pad * 2, chartH = h - pad * 1.5;
  const barW = chartW / 24 - 1;

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 9, color: T.textSec, fontWeight: 700, letterSpacing: "0.06em", marginBottom: 4 }}>24/7 CARBON-FREE ENERGY</div>
      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", maxHeight: h }}>
        {hours.map((hr, i) => {
          const x = pad + i * (barW + 1);
          const cfePct = hr.cfe_pct || 0;
          const barH = (cfePct / 100) * chartH;
          const color = cfePct >= 90 ? "#16a34a" : cfePct >= 60 ? "#D4A018" : "#8B3A3A";
          return (
            <g key={i}>
              <rect x={x} y={pad + chartH - barH} width={barW} height={barH} fill={color} opacity={0.7} rx={1} />
              {/* Grid carbon dot */}
              <circle cx={x + barW / 2} cy={pad + chartH + 8} r={2.5}
                fill={`hsl(${120 - Math.min(1, (hr.carbon_gco2 || 0) / 400) * 120}, 70%, 45%)`} />
            </g>
          );
        })}
        {/* 90% target line */}
        <line x1={pad} y1={pad + chartH * 0.1} x2={pad + chartW} y2={pad + chartH * 0.1}
          stroke="#16a34a" strokeWidth={0.5} strokeDasharray="3,2" />
        <text x={pad - 2} y={pad + chartH * 0.1 + 3} textAnchor="end" fontSize={7} fill="#16a34a">90%</text>
        {/* Axis labels */}
        {[0, 6, 12, 18].map(hr => (
          <text key={hr} x={pad + hr * (barW + 1) + barW / 2} y={h - 2}
            textAnchor="middle" fontSize={7} fill="#888">{hr}h</text>
        ))}
        {/* Legend */}
        <rect x={pad} y={1} width={6} height={6} fill="#16a34a" rx={1} />
        <text x={pad + 9} y={7} fontSize={6} fill="#888">CFE%</text>
        <circle cx={pad + 45} cy={4} r={2.5} fill="#f59e0b" />
        <text x={pad + 50} y={7} fontSize={6} fill="#888">Grid CO₂</text>
      </svg>
      {data.summary && (
        <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
          <div style={{ flex: 1, textAlign: "center" }}>
            <div style={{ fontSize: 18, fontWeight: 900, color: data.summary.avg_cfe >= 90 ? "#16a34a" : "#D4A018" }}>
              {data.summary.avg_cfe?.toFixed(0)}%
            </div>
            <div style={{ fontSize: 7, color: T.textSec }}>AVG CFE</div>
          </div>
          <div style={{ flex: 1, textAlign: "center" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: T.text }}>{data.summary.hours_above_90 || 0}/24</div>
            <div style={{ fontSize: 7, color: T.textSec }}>HRS &gt;90%</div>
          </div>
          <div style={{ flex: 1, textAlign: "center" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#00bcd4" }}>{data.summary.avg_carbon?.toFixed(0) || "—"}</div>
            <div style={{ fontSize: 7, color: T.textSec }}>gCO₂/kWh</div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── ASHRAE Compliance Badge ── */
function ASHRAEBadge({ data }) {
  if (!data) return null;
  const classColors = { Recommended: "#16a34a", A1: "#22c55e", A2: "#D4A018", A3: "#f59e0b", A4: "#8B3A3A" };
  return (
    <div style={{ marginTop: 8, padding: 8, background: "rgba(255,255,255,0.04)", borderRadius: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontSize: 9, color: T.textSec, fontWeight: 700, letterSpacing: "0.06em" }}>ASHRAE TC 9.9</span>
        <span style={{
          padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 900,
          background: classColors[data.class] || "#888", color: "#fff",
        }}>{data.class}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 10 }}>
        <div><span style={{ color: T.textSec }}>Max Temp</span> <span style={{ color: T.text, fontWeight: 600 }}>{data.max_temp_c?.toFixed(1)}°C</span></div>
        <div><span style={{ color: T.textSec }}>Min Temp</span> <span style={{ color: T.text, fontWeight: 600 }}>{data.min_temp_c?.toFixed(1)}°C</span></div>
        <div><span style={{ color: T.textSec }}>Free Cool</span> <span style={{ color: "#00bcd4", fontWeight: 600 }}>{data.free_cooling_hours || 0}h</span></div>
        <div><span style={{ color: T.textSec }}>Outside Rec.</span> <span style={{ color: data.hours_outside_recommended > 500 ? T.orange : T.green, fontWeight: 600 }}>{data.hours_outside_recommended || 0}h</span></div>
      </div>
    </div>
  );
}

/* ── Tier Compliance Badge ── */
function TierBadge({ data }) {
  if (!data) return null;
  const tierColors = { 1: "#8B3A3A", 2: "#D4A018", 3: "#16a34a", 4: "#3b82f6" };
  return (
    <div style={{ marginTop: 8, padding: 8, background: "rgba(255,255,255,0.04)", borderRadius: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontSize: 9, color: T.textSec, fontWeight: 700, letterSpacing: "0.06em" }}>UPTIME TIER</span>
        <span style={{
          padding: "2px 10px", borderRadius: 4, fontSize: 11, fontWeight: 900,
          background: tierColors[data.tier] || "#888", color: "#fff",
        }}>{data.label || `Tier ${data.tier}`}</span>
      </div>
      <div style={{ fontSize: 10, color: T.text }}>
        <div>Availability: <span style={{ fontWeight: 700 }}>{data.availability_pct}%</span></div>
        <div>Max downtime: <span style={{ fontWeight: 700 }}>{data.annual_downtime_hours}h/yr</span></div>
      </div>
      {data.gaps?.length > 0 && (
        <div style={{ marginTop: 4, fontSize: 9, color: T.orange }}>
          {data.gaps.map((g, i) => <div key={i}>⚠ {g}</div>)}
        </div>
      )}
    </div>
  );
}

/* ── Power Chain Diagram ── */
function PowerChainSVG({ data }) {
  if (!data?.stages) return null;
  const stages = data.stages;
  const w = 260, stageH = 28, gap = 4;
  const h = stages.length * (stageH + gap) + 20;
  const colors = ["#f44336", "#ff9800", "#D4A018", "#4caf50", "#00bcd4", "#3b82f6", "#9c27b0", "#78909c"];

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 9, color: T.textSec, fontWeight: 700, letterSpacing: "0.06em", marginBottom: 4 }}>POWER CHAIN</div>
      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", maxHeight: h }}>
        {stages.map((s, i) => {
          const y = 4 + i * (stageH + gap);
          const col = colors[i % colors.length];
          return (
            <g key={i}>
              <rect x={4} y={y} width={w - 8} height={stageH} rx={4}
                fill={`${col}15`} stroke={`${col}44`} strokeWidth={1} />
              <circle cx={16} cy={y + stageH / 2} r={4} fill={col} opacity={0.6} />
              <text x={26} y={y + stageH / 2 + 3} fontSize={9} fontWeight={600} fill={T.text}>
                {s.name}
              </text>
              <text x={w - 10} y={y + stageH / 2 + 3} textAnchor="end" fontSize={8} fill={T.textSec}>
                {s.units}× {s.capacity_each} · {s.redundancy}
              </text>
              {/* Connector */}
              {i < stages.length - 1 && (
                <line x1={w / 2} y1={y + stageH} x2={w / 2} y2={y + stageH + gap}
                  stroke={T.textSec} strokeWidth={1} strokeDasharray="2,1" />
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/* ── Construction Timeline (Gantt) ── */
function TimelineGantt({ data }) {
  if (!data?.phases) return null;
  const phases = data.phases;
  const total = data.total_months || 24;
  const w = 260, barH = 14, rowH = 20;
  const h = phases.length * rowH + 20;
  const pad = 80;

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 9, color: T.textSec, fontWeight: 700, letterSpacing: "0.06em", marginBottom: 4 }}>
        CONSTRUCTION TIMELINE — {total} months
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", maxHeight: Math.max(h, 120) }}>
        {phases.map((p, i) => {
          const y = 4 + i * rowH;
          const x = pad + (p.start_month / total) * (w - pad - 8);
          const barW = Math.max(4, (p.duration_months / total) * (w - pad - 8));
          const isCritical = data.critical_path?.includes(p.name);
          return (
            <g key={i}>
              <text x={pad - 4} y={y + barH / 2 + 3} textAnchor="end" fontSize={7} fill={T.textSec}>
                {p.name.length > 12 ? p.name.slice(0, 12) + "…" : p.name}
              </text>
              <rect x={x} y={y} width={barW} height={barH} rx={3}
                fill={isCritical ? T.accent : "#3b82f6"} opacity={0.7} />
              <text x={x + barW / 2} y={y + barH / 2 + 3} textAnchor="middle" fontSize={6} fill="#fff" fontWeight={600}>
                {p.duration_months}m
              </text>
            </g>
          );
        })}
        {/* Month markers */}
        {[0, 6, 12, 18, 24].filter(m => m <= total).map(m => (
          <text key={m} x={pad + (m / total) * (w - pad - 8)} y={h - 2}
            textAnchor="middle" fontSize={6} fill="#888">{m}m</text>
        ))}
      </svg>
    </div>
  );
}

/* ── DC Financial Summary ── */
function DCFinancials({ data }) {
  if (!data) return null;
  const fmtM = (v) => v >= 1e6 ? `£${(v / 1e6).toFixed(1)}M` : `£${(v / 1e3).toFixed(0)}k`;

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 9, color: T.textSec, fontWeight: 700, letterSpacing: "0.06em", marginBottom: 6 }}>DC FINANCIAL MODEL</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        <div style={{ textAlign: "center", padding: 6, background: "rgba(255,255,255,0.04)", borderRadius: 6 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: T.accent }}>{fmtM(data.capex?.total || 0)}</div>
          <div style={{ fontSize: 7, color: T.textSec }}>TOTAL CAPEX</div>
        </div>
        <div style={{ textAlign: "center", padding: 6, background: "rgba(255,255,255,0.04)", borderRadius: 6 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: T.orange }}>{fmtM(data.opex?.total_annual || 0)}</div>
          <div style={{ fontSize: 7, color: T.textSec }}>ANNUAL OPEX</div>
        </div>
        <div style={{ textAlign: "center", padding: 6, background: "rgba(255,255,255,0.04)", borderRadius: 6 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: data.irr >= 10 ? T.green : T.orange }}>{data.irr?.toFixed(1) || "—"}%</div>
          <div style={{ fontSize: 7, color: T.textSec }}>PROJECT IRR</div>
        </div>
        <div style={{ textAlign: "center", padding: 6, background: "rgba(255,255,255,0.04)", borderRadius: 6 }}>
          <div style={{ fontSize: 16, fontWeight: 900, color: T.text }}>{data.payback_years?.toFixed(1) || "—"}yr</div>
          <div style={{ fontSize: 7, color: T.textSec }}>PAYBACK</div>
        </div>
      </div>
      {data.capex?.per_mw && (
        <div style={{ fontSize: 10, color: T.textSec, marginTop: 6, textAlign: "center" }}>
          {fmtM(data.capex.per_mw)}/MW · Revenue {fmtM(data.revenue?.annual || 0)}/yr
        </div>
      )}
    </div>
  );
}

/* ── Water Stress Badge ── */
function WaterStressBadge({ data }) {
  if (!data) return null;
  const stressColors = { low: T.green, moderate: T.orange, high: T.red, "very high": T.red };
  return (
    <div style={{ marginTop: 8, padding: 8, background: "rgba(255,255,255,0.04)", borderRadius: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 9, color: T.textSec, fontWeight: 700, letterSpacing: "0.06em" }}>WATER</span>
        <span style={{
          padding: "2px 8px", borderRadius: 4, fontSize: 9, fontWeight: 700,
          color: stressColors[data.water_stress_level] || T.textSec,
          background: `${stressColors[data.water_stress_level] || "#888"}15`,
        }}>{data.water_stress_level?.toUpperCase()}</span>
      </div>
      <div style={{ fontSize: 10, color: T.text, marginTop: 4 }}>
        <div>WUE: <span style={{ fontWeight: 700, color: "#00bcd4" }}>{data.wue_l_kwh?.toFixed(2)} L/kWh</span></div>
        <div>Annual: <span style={{ fontWeight: 700 }}>{(data.annual_water_m3 || 0).toLocaleString()} m³</span></div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Auto-Design Modal — "AI Load → Full Facility"
   ═══════════════════════════════════════════════════════════════════════════ */

const WORKLOAD_PRESETS = [
  { id: "edge", label: "Edge DC", mw: 5, kwRack: 8, cooling: "mechanical", info: "Single-building edge facility. Air cooled, 625 racks." },
  { id: "enterprise", label: "Enterprise", mw: 20, kwRack: 10, cooling: "hybrid", info: "Campus enterprise DC. Hybrid cooling, 2,000 racks." },
  { id: "colo", label: "Colocation", mw: 50, kwRack: 12, cooling: "hybrid", info: "Multi-tenant colocation. Hybrid cooling, ~4,200 racks." },
  { id: "hyperscale", label: "Hyperscale", mw: 200, kwRack: 15, cooling: "free_cooling", info: "Google/Meta scale. Free cooling where climate allows, ~13,000 racks." },
  { id: "ai_factory", label: "AI Factory", mw: 500, kwRack: 60, cooling: "evaporative", info: "NVIDIA GB200 NVL72 config. Direct liquid cooling required, ~8,300 racks at 60kW each." },
];

const WORKLOAD_TYPES = [
  { id: "general", label: "General Purpose", kwRack: 8, cooling: "mechanical", desc: "Standard 1U/2U servers, air cooled" },
  { id: "ai_training", label: "AI Training", kwRack: 60, cooling: "evaporative", desc: "GPU clusters (H100/B200), DLC required" },
  { id: "ai_inference", label: "AI Inference", kwRack: 30, cooling: "hybrid", desc: "Inference serving, hybrid cooling" },
  { id: "hpc", label: "HPC", kwRack: 40, cooling: "evaporative", desc: "Scientific computing, liquid assisted" },
  { id: "storage", label: "Storage", kwRack: 5, cooling: "mechanical", desc: "Object/block storage, low density" },
];

function AutoDesignModal({ onDesign, onClose, lat, lon }) {
  const [itLoadMw, setItLoadMw] = useState(50);
  const [workload, setWorkload] = useState("general");
  const [kwRack, setKwRack] = useState(8);
  const [cooling, setCooling] = useState("hybrid");
  const [tier, setTier] = useState(3);
  const [designing, setDesigning] = useState(false);

  const selectPreset = (preset) => {
    setItLoadMw(preset.mw);
    setKwRack(preset.kwRack);
    setCooling(preset.cooling);
  };

  const selectWorkload = (wl) => {
    setWorkload(wl.id);
    setKwRack(wl.kwRack);
    setCooling(wl.cooling);
  };

  const handleDesign = async () => {
    setDesigning(true);

    // Run all 7 API calls in parallel
    const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.ok ? r.json() : null).catch(() => null);
    const get = (url) => fetch(url).then(r => r.ok ? r.json() : null).catch(() => null);

    const redundancy = tier >= 4 ? "2N" : tier >= 3 ? "N+1" : "N";
    const useLat = lat || 51.5;
    const useLon = lon || -0.1;

    const [design, chain, timeline, financial, cfe, ashrae, tierCheck] = await Promise.all([
      post("/api/dc/power-density-design", { it_load_mw: itLoadMw, kw_per_rack: kwRack, tier, redundancy, cooling_type: cooling }),
      post("/api/dc/power-chain", { it_load_mw: itLoadMw, tier, voltage_kv: itLoadMw >= 100 ? 132 : 33 }),
      post("/api/dc/construction-timeline", { it_load_mw: itLoadMw, tier, modular: itLoadMw <= 20 }),
      post("/api/dc/financial-model", { it_load_mw: itLoadMw, tier, kw_per_rack: kwRack, pue: 1.3 }),
      post("/api/dc/hourly-cfe", { lat: useLat, lon: useLon, capacity_mw: itLoadMw, solar_mw: itLoadMw * 0.5, wind_mw: itLoadMw * 0.2, bess_mwh: itLoadMw * 2 }),
      get(`/api/dc/ashrae?lat=${useLat}&lon=${useLon}`),
      post("/api/dc/tier-check", { redundancy, power_paths: tier >= 3 ? 2 : 1, cooling_paths: tier >= 3 ? 2 : 1, concurrently_maintainable: tier >= 3, fault_tolerant: tier >= 4 }),
    ]);

    onDesign({
      itLoadMw, workload, kwRack, cooling, tier,
      design, chain, timeline, financial, cfe, ashrae, tierCheck,
    });
    setDesigning(false);
  };

  const wlType = WORKLOAD_TYPES.find(w => w.id === workload);
  const estRacks = Math.ceil(itLoadMw * 1000 / kwRack);
  const estArea = Math.ceil(estRacks * 3.5); // ~3.5m² per rack

  return (
    <div style={{
      position: "absolute", inset: 0, zIndex: 100, background: "rgba(15,14,10,0.92)",
      display: "flex", alignItems: "center", justifyContent: "center",
      backdropFilter: "blur(8px)",
    }}>
      <div style={{
        background: T.panel, borderRadius: 16, width: "90%", maxWidth: 700,
        maxHeight: "90vh", overflow: "auto", boxShadow: "0 24px 80px rgba(0,0,0,0.4)",
      }}>
        {/* Header */}
        <div style={{ padding: "20px 24px 12px", borderBottom: `1px solid rgba(0,0,0,0.06)` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 900, color: T.accent, letterSpacing: "0.06em" }}>DESIGN YOUR FACILITY</div>
              <div style={{ fontSize: 11, color: T.textSec, marginTop: 2 }}>Set your IT load. Princeps designs everything else.</div>
            </div>
            <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, color: T.textSec, cursor: "pointer" }}>&times;</button>
          </div>
        </div>

        <div style={{ padding: "16px 24px" }}>
          {/* Quick Presets */}
          <div style={{ fontSize: 9, fontWeight: 700, color: T.textSec, letterSpacing: "0.06em", marginBottom: 8 }}>SCALE PRESET</div>
          <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
            {WORKLOAD_PRESETS.map(p => (
              <button key={p.id} onClick={() => selectPreset(p)} style={{
                flex: 1, minWidth: 100, padding: "8px 6px", borderRadius: 8,
                border: itLoadMw === p.mw ? `2px solid ${T.accent}` : "1px solid rgba(0,0,0,0.08)",
                background: itLoadMw === p.mw ? "rgba(212,160,24,0.06)" : "transparent",
                cursor: "pointer", textAlign: "center",
              }}>
                <div style={{ fontSize: 16, fontWeight: 900, color: itLoadMw === p.mw ? T.accent : T.text }}>{p.mw}</div>
                <div style={{ fontSize: 8, color: T.textSec }}>MW</div>
                <div style={{ fontSize: 9, fontWeight: 600, color: T.text, marginTop: 2 }}>{p.label}</div>
              </button>
            ))}
          </div>

          {/* IT Load Slider */}
          <div style={{ fontSize: 9, fontWeight: 700, color: T.textSec, letterSpacing: "0.06em", marginBottom: 4 }}>IT LOAD</div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
            <input type="range" min={1} max={500} value={itLoadMw} onChange={e => setItLoadMw(+e.target.value)}
              style={{ flex: 1, accentColor: T.accent }} />
            <div style={{ textAlign: "right", minWidth: 70 }}>
              <span style={{ fontSize: 28, fontWeight: 900, color: T.text }}>{itLoadMw}</span>
              <span style={{ fontSize: 11, color: T.textSec, marginLeft: 4 }}>MW</span>
            </div>
          </div>

          {/* Workload Type */}
          <div style={{ fontSize: 9, fontWeight: 700, color: T.textSec, letterSpacing: "0.06em", marginBottom: 8 }}>WORKLOAD TYPE</div>
          <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
            {WORKLOAD_TYPES.map(w => (
              <button key={w.id} onClick={() => selectWorkload(w)} style={{
                flex: 1, minWidth: 90, padding: "6px 8px", borderRadius: 6,
                border: workload === w.id ? `2px solid ${T.accent}` : "1px solid rgba(0,0,0,0.08)",
                background: workload === w.id ? "rgba(212,160,24,0.06)" : "transparent",
                cursor: "pointer", textAlign: "left",
              }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: T.text }}>{w.label}</div>
                <div style={{ fontSize: 8, color: T.textSec }}>{w.kwRack} kW/rack</div>
              </button>
            ))}
          </div>

          {/* Configuration row */}
          <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: T.textSec, letterSpacing: "0.06em", marginBottom: 4 }}>kW/RACK</div>
              <input type="number" value={kwRack} min={2} max={250} onChange={e => setKwRack(+e.target.value)}
                style={{ width: "100%", padding: "6px 8px", borderRadius: 6, border: "1px solid rgba(0,0,0,0.1)", fontSize: 14, fontWeight: 700 }} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: T.textSec, letterSpacing: "0.06em", marginBottom: 4 }}>COOLING</div>
              <select value={cooling} onChange={e => setCooling(e.target.value)}
                style={{ width: "100%", padding: "6px 8px", borderRadius: 6, border: "1px solid rgba(0,0,0,0.1)", fontSize: 12 }}>
                <option value="mechanical">Air (Mechanical)</option>
                <option value="free_cooling">Free Cooling</option>
                <option value="hybrid">Hybrid</option>
                <option value="evaporative">Evaporative / DLC</option>
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: T.textSec, letterSpacing: "0.06em", marginBottom: 4 }}>TIER</div>
              <div style={{ display: "flex", gap: 3 }}>
                {[1, 2, 3, 4].map(t => (
                  <button key={t} onClick={() => setTier(t)} style={{
                    flex: 1, padding: "6px 0", borderRadius: 4, fontSize: 12, fontWeight: 700,
                    border: tier === t ? `2px solid ${T.accent}` : "1px solid rgba(0,0,0,0.08)",
                    background: tier === t ? "rgba(212,160,24,0.1)" : "transparent",
                    color: tier === t ? T.accent : T.textSec, cursor: "pointer",
                  }}>{t}</button>
                ))}
              </div>
            </div>
          </div>

          {/* Preview strip */}
          <div style={{
            display: "flex", gap: 16, padding: "12px 16px", background: "rgba(0,0,0,0.02)",
            borderRadius: 8, marginBottom: 16, justifyContent: "space-around",
          }}>
            {[
              { label: "Racks", value: estRacks.toLocaleString(), color: T.accent },
              { label: "Floor", value: `${(estArea / 1000).toFixed(1)}k m²`, color: T.text },
              { label: "Total Power", value: `${Math.round(itLoadMw * 1.3)} MW`, color: T.blue },
              { label: "Est. CAPEX", value: `£${(itLoadMw * (kwRack >= 30 ? 15 : 10)).toFixed(0)}M`, color: T.accent },
            ].map(m => (
              <div key={m.label} style={{ textAlign: "center" }}>
                <div style={{ fontSize: 18, fontWeight: 900, color: m.color }}>{m.value}</div>
                <div style={{ fontSize: 8, color: T.textSec, textTransform: "uppercase" }}>{m.label}</div>
              </div>
            ))}
          </div>

          {/* Design button */}
          <button onClick={handleDesign} disabled={designing} style={{
            width: "100%", padding: "14px", borderRadius: 10, border: "none",
            background: T.accent, color: "#0F0E0A", fontSize: 14, fontWeight: 900,
            cursor: designing ? "wait" : "pointer", opacity: designing ? 0.7 : 1,
            letterSpacing: "0.04em",
          }}>
            {designing ? "Designing facility..." : `Design ${itLoadMw} MW ${wlType?.label || "Facility"}`}
          </button>

          {/* Workload info */}
          {wlType && (
            <div style={{ fontSize: 10, color: T.textSec, marginTop: 8, textAlign: "center" }}>
              {wlType.desc}. Estimated {estRacks.toLocaleString()} racks at {kwRack} kW each.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Building Shell for 3D scene ── */
function BuildingShell({ rackLayout }) {
  if (!rackLayout?.length) return null;
  const xs = rackLayout.map(r => r.x);
  const zs = rackLayout.map(r => r.z);
  const minX = Math.min(...xs) - 3, maxX = Math.max(...xs) + 3;
  const minZ = Math.min(...zs) - 3, maxZ = Math.max(...zs) + 3;
  const w = maxX - minX, d = maxZ - minZ;
  const cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2;

  return (
    <group>
      {/* Walls */}
      <mesh position={[cx, 2.5, cz]}>
        <boxGeometry args={[w + 2, 5, d + 2]} />
        <meshStandardMaterial color="#1a1f2e" transparent opacity={0.08} roughness={0.9} side={2} />
      </mesh>
      {/* Roof */}
      <mesh position={[cx, 5.1, cz]}>
        <boxGeometry args={[w + 4, 0.15, d + 4]} />
        <meshStandardMaterial color="#2a2f3e" transparent opacity={0.15} roughness={0.7} metalness={0.5} />
      </mesh>
    </group>
  );
}

/* ── Cooling Towers (outdoor) ── */
function CoolingTowerCompound({ rackLayout }) {
  if (!rackLayout?.length) return null;
  const maxX = Math.max(...rackLayout.map(r => r.x)) + 8;
  return (
    <group position={[maxX, 0, 0]}>
      {[0, 3, 6].map(i => (
        <group key={i} position={[0, 0, i]}>
          <mesh position={[0, 1, 0]}>
            <cylinderGeometry args={[1.2, 1.5, 2, 16]} />
            <meshStandardMaterial color="#4a5568" roughness={0.6} metalness={0.3} />
          </mesh>
          <mesh position={[0, 2.2, 0]}>
            <cylinderGeometry args={[0.3, 1.0, 0.5, 16]} />
            <meshStandardMaterial color="#718096" transparent opacity={0.3} />
          </mesh>
        </group>
      ))}
      {/* Label */}
      <Html position={[0, 3.5, 3]} center distanceFactor={15} style={{ pointerEvents: "none" }}>
        <div style={{ fontSize: 8, color: "#00bcd4", fontWeight: 700, fontFamily: "system-ui", background: "rgba(0,0,0,0.5)", padding: "2px 6px", borderRadius: 4 }}>
          COOLING TOWERS
        </div>
      </Html>
    </group>
  );
}

/* ── Generator Compound (outdoor) ── */
function GeneratorCompound({ rackLayout }) {
  if (!rackLayout?.length) return null;
  const minZ = Math.min(...rackLayout.map(r => r.z)) - 6;
  return (
    <group position={[0, 0, minZ]}>
      {[0, 4, 8].map(i => (
        <mesh key={i} position={[i, 0.75, 0]}>
          <boxGeometry args={[3, 1.5, 2]} />
          <meshStandardMaterial color="#2d3748" emissive="#D4A018" emissiveIntensity={0.05} roughness={0.4} metalness={0.6} />
        </mesh>
      ))}
      <Html position={[4, 2.5, 0]} center distanceFactor={15} style={{ pointerEvents: "none" }}>
        <div style={{ fontSize: 8, color: T.orange, fontWeight: 700, fontFamily: "system-ui", background: "rgba(0,0,0,0.5)", padding: "2px 6px", borderRadius: 4 }}>
          GENERATORS ({rackLayout.length > 100 ? "N+1" : "N"})
        </div>
      </Html>
    </group>
  );
}

/* ── Substation model ── */
function SubstationModel({ rackLayout }) {
  if (!rackLayout?.length) return null;
  const minX = Math.min(...rackLayout.map(r => r.x)) - 10;
  return (
    <group position={[minX, 0, 0]}>
      <mesh position={[0, 1.5, 0]}>
        <boxGeometry args={[4, 3, 3]} />
        <meshStandardMaterial color="#374151" roughness={0.5} metalness={0.4} />
      </mesh>
      {/* HV bushings */}
      {[-1, 0, 1].map(i => (
        <mesh key={i} position={[i * 1.2, 3.2, 0]}>
          <cylinderGeometry args={[0.08, 0.08, 1, 8]} />
          <meshStandardMaterial color="#dc2626" emissive="#ff0000" emissiveIntensity={0.3} />
        </mesh>
      ))}
      <Html position={[0, 4.5, 0]} center distanceFactor={15} style={{ pointerEvents: "none" }}>
        <div style={{ fontSize: 8, color: "#f44336", fontWeight: 700, fontFamily: "system-ui", background: "rgba(0,0,0,0.5)", padding: "2px 6px", borderRadius: 4 }}>
          SUBSTATION 33/11kV
        </div>
      </Html>
    </group>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Sidebar Sub-components
   ═══════════════════════════════════════════════════════════════════════════ */

function MetricCard({ label, value, unit, color, small }) {
  return (
    <div style={{ padding: small ? "4px 0" : "6px 0" }}>
      <div style={{ fontSize: 9, color: T.textSec, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: small ? 16 : 22, fontWeight: 700, color: color || T.text, lineHeight: 1.1 }}>
        {value}<span style={{ fontSize: 10, fontWeight: 400, color: T.textSec, marginLeft: 3 }}>{unit}</span>
      </div>
    </div>
  );
}

function AnomalyList({ anomalies }) {
  if (!anomalies?.length) return <div style={{ fontSize: 10, color: T.textSec, padding: "8px 0" }}>No anomalies</div>;
  return (
    <div style={{ maxHeight: 120, overflowY: "auto" }}>
      {anomalies.slice(0, 8).map((a, i) => (
        <div key={i} style={{
          fontSize: 10, color: T.text, padding: "3px 0",
          borderLeft: `2px solid ${a.severity === "critical" ? T.red : T.orange}`,
          paddingLeft: 8, marginBottom: 2,
        }}>
          {a.msg}
        </div>
      ))}
    </div>
  );
}

function PUEGauge({ pue, target }) {
  const pct = Math.min(100, ((pue - 1) / 0.8) * 100);
  const color = pue <= target ? T.green : pue <= target + 0.15 ? T.orange : T.red;
  return (
    <div style={{ padding: "6px 0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
        <span style={{ fontSize: 9, color: T.textSec }}>PUE</span>
        <span style={{ fontSize: 9, color: T.textSec }}>Target: {target}</span>
      </div>
      <div style={{ height: 6, background: "#1a1f2e", borderRadius: 3 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.5s" }} />
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color, marginTop: 2, textAlign: "center" }}>{pue.toFixed(3)}</div>
    </div>
  );
}

function CostBreakdown({ costs }) {
  if (!costs) return null;
  const capex = costs.capex;
  const opex = costs.opex;
  const items = [
    { label: "Racks", val: capex?.racks },
    { label: "UPS", val: capex?.ups },
    { label: "Generators", val: capex?.generators },
    { label: "Cooling", val: capex?.cooling },
    { label: "Civil", val: capex?.civil_works },
    { label: "Cabling", val: capex?.cabling },
  ];
  return (
    <div>
      <div style={{ fontSize: 10, color: T.textSec, fontWeight: 600, marginBottom: 4 }}>CapEx Breakdown</div>
      {items.map(it => (
        <div key={it.label} style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: T.text, padding: "1px 0" }}>
          <span>{it.label}</span><span style={{ color: T.accent }}>{fmtGbp(it.val)}</span>
        </div>
      ))}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, fontWeight: 700, color: T.text, borderTop: "1px solid rgba(0,0,0,0.08)", marginTop: 4, paddingTop: 4 }}>
        <span>Total CapEx</span><span style={{ color: T.accent }}>{fmtGbp(capex?.total_gbp)}</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: T.text, marginTop: 6 }}>
        <span>Annual OpEx</span><span style={{ color: T.orange }}>{fmtGbp(opex?.total_gbp)}</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: T.textSec, marginTop: 2 }}>
        <span>Per kW</span><span>CapEx {fmtGbp(capex?.per_kw_gbp)} | OpEx {fmtGbp(opex?.per_kw_gbp)}/yr</span>
      </div>
    </div>
  );
}

function PowerChainDiagram({ power }) {
  if (!power) return null;
  const items = [
    { label: "Grid", val: `${power.voltage_kv}kV`, color: T.cyan },
    { label: "Switchgear", val: `${power.switchgear_panels} panels`, color: "#888" },
    { label: "Transformers", val: `${power.transformer_count}× ${power.transformer_mva?.toFixed?.(1) || "--"} MVA`, color: T.purple },
    { label: "UPS", val: `${power.ups_modules} modules (${fmtKw(power.ups_capacity_kw)})`, color: T.accent },
    { label: "Generators", val: `${power.generator_sets} gensets`, color: T.orange },
    { label: "PDUs", val: `${power.pdu_count} (${power.redundancy})`, color: T.green },
  ];
  return (
    <div>
      <div style={{ fontSize: 10, color: T.textSec, fontWeight: 600, marginBottom: 4 }}>Power Distribution Chain</div>
      {items.map((it, i) => (
        <div key={it.label} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
          <div style={{ width: 6, height: 6, borderRadius: 3, background: it.color, flexShrink: 0 }} />
          <span style={{ fontSize: 10, color: T.textSec, width: 70, flexShrink: 0 }}>{it.label}</span>
          <span style={{ fontSize: 10, color: T.text }}>{it.val}</span>
          {i < items.length - 1 && <span style={{ fontSize: 8, color: "#333", marginLeft: "auto" }}>→</span>}
        </div>
      ))}
    </div>
  );
}

/* ── 24h Simulation Chart (SVG) ── */
function SimulationChart({ data, height = 180 }) {
  if (!data?.hourly) return null;
  const hourly = data.hourly;
  const w = 440, h = height, pad = 30;
  const chartW = w - pad * 2, chartH = h - pad * 1.5;
  const maxPue = Math.max(...hourly.map(d => d.pue || 0), 1.5);
  const maxKw = Math.max(...hourly.map(d => (d.it_kw || 0) + (d.hvac_kw || 0)), 1);

  const puePoints = hourly.map((d, i) => {
    const x = pad + (i / 23) * chartW;
    const y = pad + chartH - ((d.pue || 1) / maxPue) * chartH;
    return `${x},${y}`;
  }).join(" ");

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 10, color: T.textSec, fontWeight: 600, marginBottom: 4 }}>24h SIMULATION</div>
      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", maxHeight: h }}>
        {/* IT load area */}
        <path d={hourly.map((d, i) => {
          const x = pad + (i / 23) * chartW;
          const y = pad + chartH - ((d.it_kw || 0) / maxKw) * chartH;
          return `${i === 0 ? "M" : "L"}${x},${y}`;
        }).join(" ") + ` L${pad + chartW},${pad + chartH} L${pad},${pad + chartH} Z`}
          fill="rgba(24, 144, 255, 0.15)" />

        {/* HVAC area (stacked) */}
        <path d={hourly.map((d, i) => {
          const x = pad + (i / 23) * chartW;
          const y = pad + chartH - (((d.it_kw || 0) + (d.hvac_kw || 0)) / maxKw) * chartH;
          return `${i === 0 ? "M" : "L"}${x},${y}`;
        }).join(" ") + ` L${pad + chartW},${pad + chartH} L${pad},${pad + chartH} Z`}
          fill="rgba(0, 188, 212, 0.12)" />

        {/* PUE line */}
        <polyline points={puePoints} fill="none" stroke={T.accent} strokeWidth={2} />

        {/* Carbon dots */}
        {hourly.map((d, i) => {
          const x = pad + (i / 23) * chartW;
          const norm = Math.min(1, (d.carbon_gco2_kwh || 0) / 400);
          return (
            <circle key={i} cx={x} cy={pad + chartH + 10} r={3}
              fill={`hsl(${120 - norm * 120}, 70%, 45%)`} opacity={0.7} />
          );
        })}

        {/* Axes */}
        <line x1={pad} y1={pad} x2={pad} y2={pad + chartH} stroke="#ccc" strokeWidth={0.5} />
        <line x1={pad} y1={pad + chartH} x2={pad + chartW} y2={pad + chartH} stroke="#ccc" strokeWidth={0.5} />
        {[0, 6, 12, 18, 23].map(hr => (
          <text key={hr} x={pad + (hr / 23) * chartW} y={h - 2}
            textAnchor="middle" fontSize={8} fill="#999">{hr}:00</text>
        ))}

        {/* Legend */}
        <rect x={pad} y={2} width={8} height={8} fill="rgba(24,144,255,0.3)" rx={1} />
        <text x={pad + 11} y={9} fontSize={7} fill="#666">IT</text>
        <rect x={pad + 30} y={2} width={8} height={8} fill="rgba(0,188,212,0.25)" rx={1} />
        <text x={pad + 41} y={9} fontSize={7} fill="#666">HVAC</text>
        <line x1={pad + 65} y1={6} x2={pad + 80} y2={6} stroke={T.accent} strokeWidth={2} />
        <text x={pad + 83} y={9} fontSize={7} fill="#666">PUE</text>
      </svg>

      {/* Summary */}
      {data.summary && (
        <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
          {[
            { label: "Avg PUE", value: data.summary.avg_pue?.toFixed(3), color: T.accent },
            { label: "Peak PUE", value: data.summary.peak_pue?.toFixed(3), color: T.orange },
            { label: "Total Energy", value: `${(data.summary.total_energy_kwh / 1000).toFixed(0)} MWh`, color: T.blue },
            { label: "Carbon", value: `${(data.summary.total_carbon_kg / 1000).toFixed(1)} t`, color: T.green },
          ].map(m => (
            <div key={m.label} style={{ textAlign: "center", flex: 1 }}>
              <div style={{ fontSize: 7, color: T.textSec, textTransform: "uppercase" }}>{m.label}</div>
              <div style={{ fontSize: 11, fontWeight: 700, color: m.color }}>{m.value || "—"}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Carbon Optimisation Comparison ── */
function CarbonComparison({ baseline, optimised }) {
  if (!baseline || !optimised) return null;
  const bCarbon = baseline.summary?.total_carbon_kg || 0;
  const oCarbon = optimised.summary?.total_carbon_kg || 0;
  const savings = bCarbon - oCarbon;
  const pct = bCarbon > 0 ? (savings / bCarbon * 100) : 0;

  return (
    <div style={{ marginTop: 12, padding: 10, background: "#f0fdf4", borderRadius: 8, border: "1px solid #bbf7d0" }}>
      <div style={{ fontSize: 10, color: T.green, fontWeight: 700, marginBottom: 6 }}>CARBON OPTIMISATION</div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 8, color: T.textSec }}>BASELINE</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: T.textSec }}>{(bCarbon / 1000).toFixed(1)}t</div>
        </div>
        <div style={{ fontSize: 18, color: T.green }}>→</div>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 8, color: T.green }}>OPTIMISED</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: T.green }}>{(oCarbon / 1000).toFixed(1)}t</div>
        </div>
        <div style={{ textAlign: "center", padding: "4px 10px", background: "#dcfce7", borderRadius: 8 }}>
          <div style={{ fontSize: 8, color: T.green }}>SAVED</div>
          <div style={{ fontSize: 14, fontWeight: 900, color: T.green }}>{pct.toFixed(0)}%</div>
        </div>
      </div>
    </div>
  );
}

/* ── Lifecycle Carbon Breakdown ── */
function LifecycleCarbon({ data }) {
  if (!data) return null;
  const op = data.operational_carbon_tco2 || 0;
  const em = data.embodied_carbon_tco2 || 0;
  const total = op + em;
  const opPct = total > 0 ? (op / total * 100) : 0;

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 10, color: T.textSec, fontWeight: 600, marginBottom: 4 }}>LIFECYCLE CARBON</div>
      <div style={{ height: 12, background: "#eee", borderRadius: 6, overflow: "hidden", display: "flex" }}>
        <div style={{ width: `${opPct}%`, background: T.orange, height: "100%" }} title={`Operational: ${op.toFixed(0)} tCO₂`} />
        <div style={{ flex: 1, background: "#78909c", height: "100%" }} title={`Embodied: ${em.toFixed(0)} tCO₂`} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
        <span style={{ fontSize: 9, color: T.orange }}>Operational {opPct.toFixed(0)}% ({op.toFixed(0)}t)</span>
        <span style={{ fontSize: 9, color: "#78909c" }}>Embodied {(100 - opPct).toFixed(0)}% ({em.toFixed(0)}t)</span>
      </div>
      <div style={{ fontSize: 16, fontWeight: 900, color: T.text, textAlign: "center", marginTop: 4 }}>
        {total.toFixed(0)} <span style={{ fontSize: 10, fontWeight: 400, color: T.textSec }}>tCO₂ lifetime</span>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════════════════════════ */

export default function DataCentreTwin({ onClose }) {
  const { explain, pickedLocation, samCapacity } = useSite();

  // Config state
  const [itLoadKw, setItLoadKw] = useState(10000);
  const [redundancy, setRedundancy] = useState("N+1");
  const [coolingType, setCoolingType] = useState("hybrid");
  const [rackDensity, setRackDensity] = useState(8);
  const [tier, setTier] = useState(3);
  const [viewMode, setViewMode] = useState("plan"); // plan | monitor | feasibility

  // Data state
  const [plan, setPlan] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  const [feasibility, setFeasibility] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedRack, setSelectedRack] = useState(null);
  const [colorBy, setColorBy] = useState("status"); // status | thermal | load
  const [cameraMode, setCameraMode] = useState("3d"); // 3d | 2d
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);

  // Simulation state
  const [sim24h, setSim24h] = useState(null);
  const [optimised, setOptimised] = useState(null);
  const [lifecycle, setLifecycle] = useState(null);
  const [simLoading, setSimLoading] = useState(false);

  // Phase 1+2: Advanced DC design state
  const [cfeProfile, setCfeProfile] = useState(null);
  const [ashraeResult, setAshraeResult] = useState(null);
  const [tierResult, setTierResult] = useState(null);
  const [powerDesign, setPowerDesign] = useState(null);
  const [powerChain, setPowerChain] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [dcFinancials, setDcFinancials] = useState(null);
  const [waterStress, setWaterStress] = useState(null);
  const [designLoading, setDesignLoading] = useState(false);
  const [showAutoDesign, setShowAutoDesign] = useState(true); // Show on open
  const [autoDesignResult, setAutoDesignResult] = useState(null);

  const wsRef = useRef(null);

  // Init capacity from SAM
  useEffect(() => {
    if (samCapacity) setItLoadKw(Math.max(100, samCapacity));
  }, [samCapacity]);

  // Fetch facility plan
  const fetchPlan = useCallback(async () => {
    setLoading(true);
    try {
      const lat = explain?.lat ?? pickedLocation?.lat ?? 52.5;
      const params = new URLSearchParams({
        it_load_kw: itLoadKw, redundancy, cooling_type: coolingType,
        rack_density_kw: rackDensity, target_pue: 1.3, tier, lat,
      });
      const res = await fetch(`/api/dc/plan?${params}`);
      if (res.ok) setPlan(await res.json());
    } catch (e) { console.error("DC plan failed:", e); }
    finally { setLoading(false); }
  }, [itLoadKw, redundancy, coolingType, rackDensity, tier, explain, pickedLocation]);

  // Fetch feasibility score
  const fetchFeasibility = useCallback(async () => {
    try {
      const lat = explain?.lat ?? pickedLocation?.lat ?? 51.5;
      const lon = explain?.lon ?? pickedLocation?.lon ?? -0.1;
      const params = new URLSearchParams({ lat, lon, capacity_mw: itLoadKw / 1000, profile: "colocation" });
      const res = await fetch(`/api/dc/score?${params}`, { method: "POST" });
      if (res.ok) setFeasibility(await res.json());
    } catch (e) { console.error("DC feasibility failed:", e); }
  }, [itLoadKw, explain, pickedLocation]);

  // Run full advanced design analysis
  const runAdvancedDesign = useCallback(async () => {
    setDesignLoading(true);
    const lat = explain?.lat ?? pickedLocation?.lat ?? 51.5;
    const lon = explain?.lon ?? pickedLocation?.lon ?? -0.1;
    const loadMw = itLoadKw / 1000;
    const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.ok ? r.json() : null).catch(() => null);
    const get = (url) => fetch(url).then(r => r.ok ? r.json() : null).catch(() => null);

    const [cfe, ashrae, tierCheck, pDesign, pChain, tl, fin, water] = await Promise.all([
      post("/api/dc/hourly-cfe", { lat, lon, capacity_mw: loadMw, solar_mw: loadMw * 0.5, wind_mw: loadMw * 0.2, bess_mwh: loadMw * 2 }),
      get(`/api/dc/ashrae?lat=${lat}&lon=${lon}`),
      post("/api/dc/tier-check", { redundancy, power_paths: tier >= 3 ? 2 : 1, cooling_paths: tier >= 3 ? 2 : 1, concurrently_maintainable: tier >= 3, fault_tolerant: tier >= 4 }),
      post("/api/dc/power-density-design", { it_load_mw: loadMw, kw_per_rack: rackDensity, tier, redundancy, cooling_type: coolingType }),
      post("/api/dc/power-chain", { it_load_mw: loadMw, tier, voltage_kv: 33 }),
      post("/api/dc/construction-timeline", { it_load_mw: loadMw, tier, modular: loadMw <= 20 }),
      post("/api/dc/financial-model", { it_load_mw: loadMw, tier, kw_per_rack: rackDensity, pue: plan?.pue?.pue || 1.3 }),
      get(`/api/dc/water-stress?lat=${lat}&lon=${lon}&capacity_mw=${loadMw}`),
    ]);

    setCfeProfile(cfe);
    setAshraeResult(ashrae);
    setTierResult(tierCheck);
    setPowerDesign(pDesign);
    setPowerChain(pChain);
    setTimeline(tl);
    setDcFinancials(fin);
    setWaterStress(water);
    setDesignLoading(false);
  }, [itLoadKw, tier, redundancy, rackDensity, coolingType, explain, pickedLocation, plan]);

  // Handle auto-design completion — populate all state from results
  const handleAutoDesign = useCallback((result) => {
    setAutoDesignResult(result);
    setShowAutoDesign(false);

    // Update configuration
    setItLoadKw(result.itLoadMw * 1000);
    setRackDensity(result.kwRack);
    setCoolingType(result.cooling);
    setTier(result.tier);
    const redundancy = result.tier >= 4 ? "2N" : result.tier >= 3 ? "N+1" : "N";
    setRedundancy(redundancy);

    // Populate design results
    if (result.design) setPowerDesign(result.design);
    if (result.chain) setPowerChain(result.chain);
    if (result.timeline) setTimeline(result.timeline);
    if (result.financial) setDcFinancials(result.financial);
    if (result.cfe) setCfeProfile(result.cfe);
    if (result.ashrae) setAshraeResult(result.ashrae);
    if (result.tierCheck) setTierResult(result.tierCheck);

    // Also fetch the facility plan for 3D visualization
    fetchPlan();

    // Switch to design view to show results
    setViewMode("design");
  }, [fetchPlan]);

  // Auto-plan on mount
  useEffect(() => { fetchPlan(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // WebSocket for monitoring
  useEffect(() => {
    if (viewMode !== "monitor") {
      if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
      return;
    }
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/dc-twin`);
    wsRef.current = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({
        it_load_kw: itLoadKw,
        rack_count: plan?.layout?.rack_count || 100,
        cooling_type: coolingType,
      }));
    };
    ws.onmessage = (e) => {
      try { setTelemetry(JSON.parse(e.data)); } catch {}
    };
    return () => { ws.close(); wsRef.current = null; };
  }, [viewMode, itLoadKw, coolingType, plan?.layout?.rack_count]);

  // Run 24h simulation + carbon optimisation + lifecycle
  const run24hSimulation = useCallback(async () => {
    setSimLoading(true);
    const loadMw = itLoadKw / 1000;
    try {
      const [simRes, optRes, lcRes] = await Promise.all([
        fetch("/api/dc/simulate-24h", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ it_load_mw: loadMw, cooling_type: coolingType }),
        }).then(r => r.ok ? r.json() : null),
        fetch("/api/dc/optimise", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ it_load_mw: loadMw, battery_mwh: loadMw * 2 }),
        }).then(r => r.ok ? r.json() : null),
        fetch("/api/dc/lifecycle-carbon", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            annual_energy_mwh: loadMw * 8760 * 0.6,
            num_servers: plan?.layout?.rack_count ? plan.layout.rack_count * 40 : 4000,
          }),
        }).then(r => r.ok ? r.json() : null),
      ]);
      if (simRes) setSim24h(simRes);
      if (optRes) setOptimised(optRes);
      if (lcRes) setLifecycle(lcRes);
    } catch (e) { console.error("DC simulation failed:", e); }
    setSimLoading(false);
  }, [itLoadKw, coolingType, plan]);

  // Fetch feasibility when switching to that view
  useEffect(() => {
    if (viewMode === "feasibility" && !feasibility) fetchFeasibility();
    if (viewMode === "feasibility" && !sim24h) run24hSimulation();
  }, [viewMode]); // eslint-disable-line react-hooks/exhaustive-deps

  const rackLayout = plan?.rack_layout || [];
  const metrics = telemetry?.metrics;
  const selectedRackData = telemetry?.racks?.find(r => r.id === selectedRack);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 1300, background: T.bg,
      display: "flex", flexDirection: "column", fontFamily: "system-ui",
    }}>
      {/* ── Top Bar ── */}
      <div style={{
        height: 44, display: "flex", alignItems: "center", padding: "0 16px",
        background: "rgba(255,255,255,0.98)", borderBottom: T.border, gap: 12, flexShrink: 0,
      }}>
        <button onClick={onClose} style={{
          background: "none", border: "none", color: T.textSec, cursor: "pointer", fontSize: 18, padding: "0 4px",
        }}>←</button>
        <span style={{ fontSize: 14, fontWeight: 700, color: T.text }}>Data Centre Digital Twin</span>

        {/* Auto-design button */}
        <button onClick={() => setShowAutoDesign(true)} style={{
          marginLeft: 8, padding: "4px 12px", borderRadius: 6, border: `1px solid ${T.accent}`,
          background: "rgba(212,160,24,0.08)", color: T.accent, fontSize: 10, fontWeight: 900,
          cursor: "pointer", letterSpacing: "0.04em",
        }}>
          New Design
        </button>

        {/* View mode tabs */}
        <div style={{ display: "flex", gap: 2, marginLeft: 16, background: "#EBEDF0", borderRadius: 6, padding: 2 }}>
          {VIEW_MODES.map(m => (
            <button key={m} onClick={() => setViewMode(m)} style={{
              padding: "4px 14px", borderRadius: 4, border: "none", fontSize: 11, fontWeight: 600,
              background: viewMode === m ? T.accent : "transparent",
              color: viewMode === m ? "#fff" : T.textSec,
              cursor: "pointer", textTransform: "capitalize",
            }}>{m}</button>
          ))}
        </div>

        {/* Color-by selector */}
        {viewMode === "monitor" && (
          <div style={{ display: "flex", gap: 2, marginLeft: 12, background: "#EBEDF0", borderRadius: 6, padding: 2 }}>
            {["status", "thermal", "load"].map(c => (
              <button key={c} onClick={() => setColorBy(c)} style={{
                padding: "3px 10px", borderRadius: 3, border: "none", fontSize: 10,
                background: colorBy === c ? "rgba(108,92,231,0.3)" : "transparent",
                color: colorBy === c ? T.accent : T.textSec,
                cursor: "pointer", textTransform: "capitalize",
              }}>{c}</button>
            ))}
          </div>
        )}

        {/* 2D/3D camera toggle (datacenter-planner pattern) */}
        <div style={{ display: "flex", gap: 2, marginLeft: 12, background: "#EBEDF0", borderRadius: 6, padding: 2 }}>
          {["3d", "2d"].map(m => (
            <button key={m} onClick={() => setCameraMode(m)} style={{
              padding: "3px 10px", borderRadius: 3, border: "none", fontSize: 10,
              background: cameraMode === m ? "rgba(108,92,231,0.3)" : "transparent",
              color: cameraMode === m ? T.accent : T.textSec,
              cursor: "pointer", textTransform: "uppercase",
            }}>{m}</button>
          ))}
        </div>

        {/* Heatmap toggle */}
        <button onClick={() => setShowHeatmap(h => !h)} style={{
          padding: "3px 10px", borderRadius: 4, border: "none", fontSize: 10,
          background: showHeatmap ? "rgba(255,152,0,0.2)" : "#151922",
          color: showHeatmap ? T.orange : T.textSec,
          cursor: "pointer", marginLeft: 4,
        }}>
          {showHeatmap ? "Heatmap ON" : "Heatmap"}
        </button>

        {/* Live indicator */}
        {viewMode === "monitor" && telemetry && (
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginLeft: 8 }}>
            <div style={{ width: 6, height: 6, borderRadius: 3, background: T.green, animation: "pulse 2s infinite" }} />
            <span style={{ fontSize: 10, color: T.green }}>LIVE</span>
          </div>
        )}

        {/* Tier badge */}
        {(plan?.tier || tierResult) && (
          <div style={{
            marginLeft: "auto", padding: "2px 10px", borderRadius: 10,
            border: `1px solid ${T.accent}`, fontSize: 10, color: T.accent, fontWeight: 600,
          }}>
            {tierResult?.label || plan?.tier?.label} — {tierResult?.availability_pct || plan?.tier?.availability}%
          </div>
        )}

        {/* Download Spec */}
        <button onClick={async () => {
          const lat = explain?.lat ?? pickedLocation?.lat ?? 51.5;
          const lon = explain?.lon ?? pickedLocation?.lon ?? -0.1;
          try {
            const blob = await fetch(`/api/dc/report?lat=${lat}&lon=${lon}&site_name=DC%20Facility&capacity_mw=${itLoadKw / 1000}&profile=google_hyperscale`, { method: "POST" })
              .then(r => r.blob());
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a"); a.href = url; a.download = "princeps-dc-spec.pdf"; a.click();
            URL.revokeObjectURL(url);
          } catch { /* silent */ }
        }} style={{
          padding: "4px 12px", borderRadius: 6, border: "none",
          background: T.accent, color: "#0F0E0A", fontSize: 10, fontWeight: 900,
          cursor: "pointer", letterSpacing: "0.04em", marginLeft: 8,
        }}>
          Download Spec
        </button>
      </div>

      {/* ── Main Content ── */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

        {/* Left Panel */}
        <div style={{
          width: leftCollapsed ? 36 : 280, flexShrink: 0,
          background: T.panel, borderRight: T.border,
          display: "flex", flexDirection: "column", transition: "width 0.2s",
          overflow: "hidden",
        }}>
          <button onClick={() => setLeftCollapsed(!leftCollapsed)} style={{
            background: "none", border: "none", color: T.textSec, cursor: "pointer",
            fontSize: 12, padding: "8px", textAlign: "center", borderBottom: T.border,
          }}>{leftCollapsed ? "▶" : "◀"}</button>

          {!leftCollapsed && (
            <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
              {/* Configuration */}
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, color: T.accent, fontWeight: 700, marginBottom: 8 }}>CONFIGURATION</div>

                <label style={{ fontSize: 10, color: T.textSec, display: "block", marginBottom: 2 }}>IT Load</label>
                <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
                  <input type="range" min={500} max={100000} step={500} value={itLoadKw}
                    onChange={e => setItLoadKw(+e.target.value)} style={{ flex: 1 }} />
                  <span style={{ fontSize: 11, color: T.text, minWidth: 50, textAlign: "right" }}>{fmtKw(itLoadKw)}</span>
                </div>

                <label style={{ fontSize: 10, color: T.textSec, display: "block", marginBottom: 2 }}>Rack Density</label>
                <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
                  <input type="range" min={2} max={30} step={0.5} value={rackDensity}
                    onChange={e => setRackDensity(+e.target.value)} style={{ flex: 1 }} />
                  <span style={{ fontSize: 11, color: T.text, minWidth: 40, textAlign: "right" }}>{rackDensity} kW</span>
                </div>

                <label style={{ fontSize: 10, color: T.textSec, display: "block", marginBottom: 2 }}>Redundancy</label>
                <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
                  {REDUNDANCY_OPTIONS.map(r => (
                    <button key={r} onClick={() => setRedundancy(r)} style={{
                      flex: 1, padding: "4px 0", borderRadius: 4, fontSize: 10, fontWeight: 600,
                      border: redundancy === r ? `1px solid ${T.accent}` : "1px solid rgba(0,0,0,0.08)",
                      background: redundancy === r ? "rgba(108,92,231,0.15)" : "transparent",
                      color: redundancy === r ? T.accent : T.textSec, cursor: "pointer",
                    }}>{r}</button>
                  ))}
                </div>

                <label style={{ fontSize: 10, color: T.textSec, display: "block", marginBottom: 2 }}>Cooling</label>
                <select value={coolingType} onChange={e => setCoolingType(e.target.value)}
                  style={{ width: "100%", padding: "4px 6px", borderRadius: 4, fontSize: 10,
                    background: "#EBEDF0", color: T.text, border: "1px solid rgba(0,0,0,0.08)", marginBottom: 8 }}>
                  {COOLING_OPTIONS.map(c => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
                </select>

                <label style={{ fontSize: 10, color: T.textSec, display: "block", marginBottom: 2 }}>Tier</label>
                <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
                  {TIER_OPTIONS.map(t => (
                    <button key={t} onClick={() => setTier(t)} style={{
                      flex: 1, padding: "4px 0", borderRadius: 4, fontSize: 10, fontWeight: 600,
                      border: tier === t ? `1px solid ${T.accent}` : "1px solid rgba(0,0,0,0.08)",
                      background: tier === t ? "rgba(108,92,231,0.15)" : "transparent",
                      color: tier === t ? T.accent : T.textSec, cursor: "pointer",
                    }}>{t}</button>
                  ))}
                </div>

                <button onClick={fetchPlan} disabled={loading} style={{
                  width: "100%", padding: "8px", borderRadius: 6, border: "none",
                  background: T.accent, color: "#fff", fontWeight: 700, fontSize: 12,
                  cursor: loading ? "wait" : "pointer", opacity: loading ? 0.6 : 1,
                }}>{loading ? "Planning..." : "Generate Plan"}</button>
              </div>

              {/* Layout summary */}
              {plan?.layout && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 11, color: T.accent, fontWeight: 700, marginBottom: 6 }}>LAYOUT</div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
                    <MetricCard label="Racks" value={plan.layout.rack_count} small />
                    <MetricCard label="Halls" value={plan.layout.halls} small />
                    <MetricCard label="White Space" value={plan.layout.whitespace_m2?.toLocaleString()} unit="m²" small />
                    <MetricCard label="Total Area" value={plan.layout.total_m2?.toLocaleString()} unit="m²" small />
                  </div>
                </div>
              )}

              {/* Power chain */}
              {plan?.power && <PowerChainDiagram power={plan.power} />}
            </div>
          )}
        </div>

        {/* 3D Canvas */}
        <div style={{ flex: 1, position: "relative" }}>
          <Canvas
            shadows
            camera={{ position: [15, 15, 15], fov: 50 }}
            gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.2 }}
            style={{ background: T.bg }}
          >
            <fog attach="fog" args={[T.bg, 30, 70]} />
            <DCScene
              rackLayout={rackLayout}
              telemetry={telemetry}
              selectedRack={selectedRack}
              onSelectRack={setSelectedRack}
              colorBy={colorBy}
              cameraMode={cameraMode}
              showHeatmap={showHeatmap}
            />
            <PostprocessingEffects bloom={1.2} bloomThreshold={0.35} chromaticAberration={0.001} vignette={0.4} />
          </Canvas>

          {/* Metrics strip at bottom of canvas */}
          {viewMode === "monitor" && metrics && (
            <div style={{
              position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)",
              display: "flex", gap: 16, padding: "8px 20px",
              background: T.panel, borderRadius: 8, border: T.border,
            }}>
              {[
                { label: "IT Load", value: `${metrics.it_load_kw?.toFixed(0)} kW`, color: T.blue },
                { label: "Cooling", value: `${metrics.cooling_kw?.toFixed(0)} kW`, color: T.cyan },
                { label: "PUE", value: metrics.pue?.toFixed(3), color: metrics.pue <= 1.3 ? T.green : T.orange },
                { label: "Avg Inlet", value: `${metrics.avg_inlet_temp_c}°C`, color: tempColor(metrics.avg_inlet_temp_c) },
                { label: "Utilisation", value: `${metrics.utilisation_pct?.toFixed(0)}%`, color: T.accent },
                { label: "WUE", value: `${metrics.wue} L/kWh`, color: T.cyan },
              ].map(m => (
                <div key={m.label} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 8, color: T.textSec, textTransform: "uppercase" }}>{m.label}</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: m.color }}>{m.value}</div>
                </div>
              ))}
            </div>
          )}

          {/* Plan summary strip when in plan mode */}
          {viewMode === "plan" && plan && (
            <div style={{
              position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)",
              display: "flex", gap: 16, padding: "8px 20px",
              background: T.panel, borderRadius: 8, border: T.border,
            }}>
              {[
                { label: "IT Load", value: fmtKw(plan.power?.it_load_kw), color: T.blue },
                { label: "Total Facility", value: fmtKw(plan.power?.total_facility_kw), color: T.cyan },
                { label: "PUE", value: plan.pue?.pue?.toFixed(3), color: plan.pue?.pue <= 1.3 ? T.green : T.orange },
                { label: "Racks", value: plan.layout?.rack_count, color: T.accent },
                { label: "CapEx", value: fmtGbp(plan.costs?.capex?.total_gbp), color: T.accent },
                { label: "OpEx/yr", value: fmtGbp(plan.costs?.opex?.total_gbp), color: T.orange },
              ].map(m => (
                <div key={m.label} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 8, color: T.textSec, textTransform: "uppercase" }}>{m.label}</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: m.color }}>{m.value}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right Panel */}
        <div style={{
          width: rightCollapsed ? 36 : 280, flexShrink: 0,
          background: T.panel, borderLeft: T.border,
          display: "flex", flexDirection: "column", transition: "width 0.2s",
          overflow: "hidden",
        }}>
          <button onClick={() => setRightCollapsed(!rightCollapsed)} style={{
            background: "none", border: "none", color: T.textSec, cursor: "pointer",
            fontSize: 12, padding: "8px", textAlign: "center", borderBottom: T.border,
          }}>{rightCollapsed ? "◀" : "▶"}</button>

          {!rightCollapsed && (
            <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>

              {/* Monitor mode — live metrics */}
              {viewMode === "monitor" && (
                <>
                  {metrics && <PUEGauge pue={metrics.pue || 1.3} target={1.3} />}

                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 11, color: T.accent, fontWeight: 700, marginBottom: 6 }}>ANOMALIES</div>
                    <AnomalyList anomalies={telemetry?.anomalies} />
                  </div>

                  {/* Selected rack detail */}
                  {selectedRackData && (
                    <div style={{ marginTop: 12, padding: 8, background: "#F7F8FA", borderRadius: 6, border: "1px solid rgba(0,0,0,0.08)" }}>
                      <div style={{ fontSize: 11, color: T.accent, fontWeight: 700, marginBottom: 6 }}>Rack {selectedRackData.id}</div>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                        <MetricCard label="Load" value={selectedRackData.it_load_kw?.toFixed(2)} unit="kW" color={T.blue} small />
                        <MetricCard label="Inlet" value={selectedRackData.inlet_temp_c} unit="°C" color={tempColor(selectedRackData.inlet_temp_c)} small />
                        <MetricCard label="Outlet" value={selectedRackData.outlet_temp_c} unit="°C" color={tempColor(selectedRackData.outlet_temp_c)} small />
                        <MetricCard label="Humidity" value={selectedRackData.humidity_pct} unit="%" color={T.cyan} small />
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* Plan mode — costs & cooling */}
              {viewMode === "plan" && plan && (
                <>
                  {plan.pue && <PUEGauge pue={plan.pue.pue} target={1.3} />}

                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 11, color: T.accent, fontWeight: 700, marginBottom: 6 }}>COOLING</div>
                    <div style={{ fontSize: 10, color: T.text }}>
                      <div>Type: <span style={{ color: T.cyan, fontWeight: 600 }}>{plan.cooling?.type?.replace("_", " ")}</span></div>
                      <div>COP: {plan.cooling?.cop} | Free cooling: {plan.cooling?.free_cooling_pct}%</div>
                      <div>CRACs: {plan.cooling?.crac_units} | Chillers: {plan.cooling?.chiller_count}</div>
                      {plan.cooling?.water_consumption_m3_yr > 0 && (
                        <div>Water: {plan.cooling.water_consumption_m3_yr?.toLocaleString()} m³/yr</div>
                      )}
                    </div>
                  </div>

                  <div style={{ marginTop: 12 }}>
                    <CostBreakdown costs={plan.costs} />
                  </div>

                  {/* PUE breakdown */}
                  {plan.pue?.breakdown && (
                    <div style={{ marginTop: 12 }}>
                      <div style={{ fontSize: 10, color: T.textSec, fontWeight: 600, marginBottom: 4 }}>Energy Breakdown</div>
                      <div style={{ fontSize: 10, color: T.text }}>
                        <div>IT: {(plan.pue.breakdown.it_load_kw / 1000).toFixed(1)} MW</div>
                        <div>Cooling: {(plan.pue.breakdown.cooling_kw / 1000).toFixed(1)} MW</div>
                        <div>UPS losses: {plan.pue.breakdown.ups_losses_kw?.toFixed(0)} kW</div>
                        <div>Distribution: {plan.pue.breakdown.distribution_kw?.toFixed(0)} kW</div>
                        <div style={{ marginTop: 4, color: T.orange }}>
                          Annual waste: {(plan.pue.annual_waste_kwh / 1_000_000).toFixed(1)} GWh
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* Design mode — advanced DC design analysis */}
              {viewMode === "design" && (
                <>
                  <div style={{ fontSize: 11, color: T.accent, fontWeight: 700, marginBottom: 8 }}>ADVANCED DESIGN</div>

                  <button onClick={runAdvancedDesign} disabled={designLoading} style={{
                    width: "100%", padding: "8px", borderRadius: 6, border: "none",
                    background: T.accent, color: "#0F0E0A", fontWeight: 700, fontSize: 11,
                    cursor: designLoading ? "wait" : "pointer", opacity: designLoading ? 0.6 : 1,
                    marginBottom: 12, letterSpacing: "0.04em",
                  }}>{designLoading ? "Analysing..." : "Run Full Design Analysis"}</button>

                  {/* Hourly CFE */}
                  <CFEChart data={cfeProfile} />

                  {/* ASHRAE + Tier side by side */}
                  <ASHRAEBadge data={ashraeResult} />
                  <TierBadge data={tierResult} />

                  {/* Power Chain */}
                  <PowerChainSVG data={powerChain} />

                  {/* Construction Timeline */}
                  <TimelineGantt data={timeline} />

                  {/* DC Financials */}
                  <DCFinancials data={dcFinancials} />

                  {/* Water Stress */}
                  <WaterStressBadge data={waterStress} />

                  {!cfeProfile && !designLoading && (
                    <div style={{ textAlign: "center", padding: "20px 0", color: T.textSec, fontSize: 11 }}>
                      Click "Run Full Design Analysis" to calculate CFE profile, ASHRAE compliance, tier validation, power chain, timeline, financials, and water stress.
                    </div>
                  )}
                </>
              )}

              {/* Simulate mode — 24h physics + carbon + lifecycle */}
              {viewMode === "simulate" && (
                <>
                  <div style={{ fontSize: 11, color: T.accent, fontWeight: 700, marginBottom: 8 }}>PHYSICS SIMULATION</div>
                  <div style={{ fontSize: 10, color: T.textSec, marginBottom: 8 }}>
                    HPE SustainDC thermal model · OpenDC power curves · 24h hourly resolution
                  </div>

                  <button onClick={run24hSimulation} disabled={simLoading} style={{
                    width: "100%", padding: "8px", borderRadius: 6, border: "none",
                    background: T.accent, color: "#fff", fontWeight: 700, fontSize: 12,
                    cursor: simLoading ? "wait" : "pointer", opacity: simLoading ? 0.6 : 1,
                    marginBottom: 12,
                  }}>{simLoading ? "Simulating..." : "Run 24h Simulation"}</button>

                  {sim24h && <SimulationChart data={sim24h} height={200} />}
                  {sim24h && optimised && <CarbonComparison baseline={sim24h} optimised={optimised} />}
                  {lifecycle && <LifecycleCarbon data={lifecycle} />}

                  {!sim24h && !simLoading && (
                    <div style={{ textAlign: "center", padding: "30px 0", color: T.textSec, fontSize: 11 }}>
                      Click "Run 24h Simulation" to model hourly IT load, HVAC demand, PUE, and carbon intensity using real physics engines.
                    </div>
                  )}
                </>
              )}

              {/* Feasibility mode — DC score + radar */}
              {viewMode === "feasibility" && (
                <>
                  {feasibility ? (
                    <>
                      <div style={{ textAlign: "center", marginBottom: 12 }}>
                        <div style={{
                          fontSize: 42, fontWeight: 700,
                          color: feasibility.dc_score >= 70 ? T.green : feasibility.dc_score >= 45 ? T.orange : T.red,
                        }}>{feasibility.dc_score}</div>
                        <div style={{ fontSize: 11, color: T.textSec, marginBottom: 4 }}>DC-SCORE</div>
                        <span style={{
                          padding: "3px 12px", borderRadius: 12, fontSize: 12, fontWeight: 700, color: "#fff",
                          background: feasibility.verdict === "GO" ? T.green : feasibility.verdict === "CAUTION" ? T.orange : T.red,
                        }}>{feasibility.verdict}</span>
                        <span style={{ fontSize: 11, color: T.textSec, marginLeft: 8 }}>{(feasibility.confidence * 100).toFixed(0)}%</span>
                      </div>

                      {/* Dimension scores */}
                      {feasibility.scores && (
                        <div>
                          {Object.entries(feasibility.scores).map(([k, v]) => (
                            <div key={k} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                              <span style={{ fontSize: 10, color: T.textSec, width: 70, flexShrink: 0 }}>
                                {k.replace(/_/g, " ")}
                              </span>
                              <div style={{ flex: 1, height: 4, background: "#1a1f2e", borderRadius: 2 }}>
                                <div style={{
                                  width: `${v.score || 0}%`, height: "100%",
                                  background: v.score >= 70 ? T.green : v.score >= 45 ? T.orange : T.red,
                                  borderRadius: 2,
                                }} />
                              </div>
                              <span style={{ fontSize: 10, color: T.text, width: 24, textAlign: "right" }}>{v.score || 0}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Grid headroom */}
                      {feasibility.grid_connection && (
                        <div style={{ marginTop: 12, padding: 8, background: "#F7F8FA", borderRadius: 6, border: "1px solid rgba(0,0,0,0.08)" }}>
                          <div style={{ fontSize: 10, color: T.textSec, fontWeight: 600, marginBottom: 4 }}>Grid Headroom</div>
                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                            <div>
                              <div style={{ fontSize: 9, color: "#666" }}>Available</div>
                              <div style={{ fontSize: 16, fontWeight: 700, color: T.green }}>
                                {feasibility.grid_connection.headroom_mw != null ? `${feasibility.grid_connection.headroom_mw} MW` : "N/A"}
                              </div>
                            </div>
                            <div>
                              <div style={{ fontSize: 9, color: "#666" }}>Substation</div>
                              <div style={{ fontSize: 10, color: T.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {feasibility.grid_connection.substation || "--"}
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Risks */}
                      {feasibility.risks?.length > 0 && (
                        <div style={{ marginTop: 12 }}>
                          <div style={{ fontSize: 10, color: T.red, fontWeight: 600, marginBottom: 4 }}>Risks</div>
                          {feasibility.risks.map((r, i) => (
                            <div key={i} style={{ fontSize: 10, color: T.text, padding: "2px 0 2px 8px", borderLeft: `2px solid ${T.red}`, marginBottom: 2 }}>{r}</div>
                          ))}
                        </div>
                      )}

                      {/* 24h Simulation Chart */}
                      {sim24h && <SimulationChart data={sim24h} />}

                      {/* Carbon Optimisation */}
                      {sim24h && optimised && (
                        <CarbonComparison baseline={sim24h} optimised={optimised} />
                      )}

                      {/* Lifecycle Carbon */}
                      {lifecycle && <LifecycleCarbon data={lifecycle} />}

                      {/* Run simulation button */}
                      {!sim24h && (
                        <button onClick={run24hSimulation} disabled={simLoading} style={{
                          width: "100%", padding: "8px", borderRadius: 6, border: "none",
                          background: T.cyan, color: "#fff", fontWeight: 700, fontSize: 11,
                          cursor: simLoading ? "wait" : "pointer", marginTop: 12,
                          opacity: simLoading ? 0.6 : 1,
                        }}>{simLoading ? "Simulating..." : "Run 24h Physics Simulation"}</button>
                      )}
                    </>
                  ) : (
                    <div style={{ textAlign: "center", padding: "40px 0", color: T.textSec }}>
                      <div style={{ fontSize: 12, marginBottom: 8 }}>Loading feasibility score...</div>
                      <button onClick={fetchFeasibility} style={{
                        padding: "6px 14px", borderRadius: 4, border: `1px solid ${T.accent}`,
                        background: "transparent", color: T.accent, fontSize: 11, cursor: "pointer",
                      }}>Assess Site</button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Auto-design modal */}
      {showAutoDesign && (
        <AutoDesignModal
          onDesign={handleAutoDesign}
          onClose={() => setShowAutoDesign(false)}
          lat={explain?.lat ?? pickedLocation?.lat}
          lon={explain?.lon ?? pickedLocation?.lon}
        />
      )}

      {/* CSS keyframes for pulse animation */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}

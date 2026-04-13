import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Grid, Html } from "@react-three/drei";
import * as THREE from "three";
import api from "../services/api";
// import PostprocessingEffects from "./PostprocessingEffects";

/* ── Design Tokens ────────────────────────────────────────────────────── */
const T = {
  bg: "#F2F3F5",
  accent: "#D4A018",
  panel: "rgba(255, 255, 255, 0.95)",
  border: "1px solid rgba(212, 160, 24, 0.2)",
  text: "#1A1D23",
  textSec: "#4B5563",
  green: "#52c41a",
  red: "#f5222d",
  orange: "#fa8c16",
  blue: "#1890ff",
};

/* ── Utilities ────────────────────────────────────────────────────────── */
function fmtNum(v, dec = 0) {
  if (v == null) return "--";
  return v.toLocaleString("en-GB", { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function randomWalk(prev, step, lo, hi) { return clamp(prev + (Math.random() - 0.5) * step, lo, hi); }

function socColor(soc) {
  if (soc > 80) return T.green;
  if (soc > 40) return T.orange;
  return T.red;
}
function socColorHex(soc) {
  if (soc > 80) return new THREE.Color(0x52c41a);
  if (soc > 40) return new THREE.Color(0xfa8c16);
  return new THREE.Color(0xf5222d);
}

const STRATEGIES = ["hybrid", "frequency_response", "arbitrage", "capacity_market"];
const BIDDER_STRATEGIES = ["coordinated", "day_ahead", "rolling_intrinsic"];
const DURATIONS = ["1h", "2h", "4h"];
const CONTAINER_COUNT = 10;

/* ── Initial simulated facility state ─────────────────────────────────── */
function createInitialContainers() {
  return Array.from({ length: CONTAINER_COUNT }, (_, i) => ({
    id: `C-${String(i + 1).padStart(2, "0")}`,
    soc: 50 + Math.random() * 40,
    powerKw: 0,
    tempC: 22 + Math.random() * 5,
    voltageV: 600 + Math.random() * 20,
    currentA: 80 + Math.random() * 40,
    cycles: Math.floor(200 + Math.random() * 800),
    healthPct: 95 + Math.random() * 5,
    status: "idle",
  }));
}

function createInitialAlarms() {
  return [
    { id: 1, time: "14:32:18", severity: "warning", message: "C-03 temperature high (33.2C)" },
    { id: 2, time: "13:15:42", severity: "info", message: "TX load > 60% threshold" },
    { id: 3, time: "11:48:05", severity: "critical", message: "C-07 SoC below 25%" },
    { id: 4, time: "10:22:33", severity: "warning", message: "Inverter PCS-3 efficiency drop" },
  ];
}

/* ═══════════════════════════════════════════════════════════════════════════
   3D Scene Components
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── Battery Container ── */
function BatteryContainer({ position, container, index, selected, onClick }) {
  const meshRef = useRef();
  const [hovered, setHovered] = useState(false);
  const col = useMemo(() => socColorHex(container.soc), [container.soc]);

  useFrame((state) => {
    if (!meshRef.current) return;
    const pulse = container.status !== "idle"
      ? 0.25 + Math.sin(state.clock.elapsedTime * 3 + index) * 0.15
      : 0.1;
    meshRef.current.material.emissiveIntensity = hovered ? 0.6 : selected ? 0.5 : pulse;
  });

  return (
    <group position={position}>
      <mesh
        ref={meshRef}
        onClick={(e) => { e.stopPropagation(); onClick(index); }}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { setHovered(false); document.body.style.cursor = "auto"; }}
        castShadow
      >
        <boxGeometry args={[2.4, 1.2, 1]} />
        <meshStandardMaterial
          color={col}
          emissive={col}
          emissiveIntensity={0.15}
          transparent
          opacity={hovered ? 1 : 0.9}
          roughness={0.2}
          metalness={0.7}
        />
      </mesh>
      {/* HVAC unit on top */}
      <mesh position={[0.7, 0.8, 0]} castShadow>
        <boxGeometry args={[0.5, 0.3, 0.4]} />
        <meshStandardMaterial color="#00bcd4" emissive="#00bcd4" emissiveIntensity={0.15} roughness={0.3} metalness={0.5} />
      </mesh>
      {/* Label */}
      <Html position={[0, 1.1, 0]} center distanceFactor={12} style={{ pointerEvents: "none" }}>
        <div style={{
          background: "rgba(255,255,255,0.92)", border: "1px solid rgba(212,160,24,0.3)",
          borderRadius: 4, padding: "2px 8px", whiteSpace: "nowrap", fontSize: 10,
          color: T.text, fontFamily: "system-ui", textAlign: "center",
        }}>
          {container.id} <span style={{ color: socColor(container.soc), fontWeight: 600 }}>{container.soc.toFixed(0)}%</span>
        </div>
      </Html>
    </group>
  );
}

/* ── Inverter/PCS Unit ── */
function InverterUnit({ position, index, active }) {
  const meshRef = useRef();
  useFrame((state) => {
    if (meshRef.current) {
      meshRef.current.material.emissiveIntensity = 0.1 + Math.sin(state.clock.elapsedTime * 2 + index * 0.7) * 0.05;
    }
  });
  return (
    <group position={position}>
      <mesh ref={meshRef} castShadow>
        <boxGeometry args={[0.8, 0.9, 0.6]} />
        <meshStandardMaterial color="#5a5f73" emissive="#5a5f73" emissiveIntensity={0.1} roughness={0.3} metalness={0.8} />
      </mesh>
      {/* Status dot */}
      <mesh position={[0, 0.55, 0.31]}>
        <sphereGeometry args={[0.06, 8, 8]} />
        <meshBasicMaterial color={active ? T.green : T.red} />
      </mesh>
      <Html position={[0, 0.8, 0]} center distanceFactor={12} style={{ pointerEvents: "none" }}>
        <div style={{
          background: "rgba(255,255,255,0.92)", border: "1px solid rgba(212,160,24,0.2)",
          borderRadius: 3, padding: "1px 6px", fontSize: 9, color: T.textSec, fontFamily: "system-ui",
        }}>
          PCS-{index + 1}
        </div>
      </Html>
    </group>
  );
}

/* ── Transformer ── */
function Transformer({ position, loadPct }) {
  const meshRef = useRef();
  useFrame((state) => {
    if (meshRef.current) {
      meshRef.current.material.emissiveIntensity = 0.12 + Math.sin(state.clock.elapsedTime * 1.5) * 0.06;
    }
  });
  return (
    <group position={position}>
      <mesh ref={meshRef} castShadow>
        <boxGeometry args={[1.6, 1.8, 1.2]} />
        <meshStandardMaterial color="#6b4c9a" emissive="#6b4c9a" emissiveIntensity={0.12} roughness={0.25} metalness={0.75} />
      </mesh>
      {/* Bushings */}
      {[-0.4, 0, 0.4].map((x, i) => (
        <mesh key={i} position={[x, 1.1, 0]}>
          <cylinderGeometry args={[0.06, 0.06, 0.5, 8]} />
          <meshStandardMaterial color="#a0a0a0" metalness={0.9} roughness={0.2} />
        </mesh>
      ))}
      <Html position={[0, 1.6, 0]} center distanceFactor={12} style={{ pointerEvents: "none" }}>
        <div style={{
          background: "rgba(255,255,255,0.92)", border: "1px solid rgba(212,160,24,0.3)",
          borderRadius: 4, padding: "2px 8px", fontSize: 10, color: T.text, fontFamily: "system-ui",
        }}>
          33kV TX <span style={{ color: loadPct > 80 ? T.red : loadPct > 60 ? T.orange : T.green, fontWeight: 600 }}>{loadPct.toFixed(0)}%</span>
        </div>
      </Html>
    </group>
  );
}

/* ── Grid Connection Point (Pylon) ── */
function GridPoint({ position, exportMw }) {
  return (
    <group position={position}>
      {/* Pylon base */}
      <mesh position={[0, 1.5, 0]}>
        <cylinderGeometry args={[0.08, 0.2, 3, 6]} />
        <meshStandardMaterial color="#7a7a7a" metalness={0.8} roughness={0.3} />
      </mesh>
      {/* Crossarm */}
      <mesh position={[0, 2.8, 0]}>
        <boxGeometry args={[1.6, 0.08, 0.08]} />
        <meshStandardMaterial color="#7a7a7a" metalness={0.8} roughness={0.3} />
      </mesh>
      {/* Overhead line going off-scene */}
      <line>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            array={new Float32Array([0, 2.8, 0, 6, 4, 0])}
            count={2}
            itemSize={3}
          />
        </bufferGeometry>
        <lineBasicMaterial color="#999" linewidth={1} />
      </line>
      <Html position={[0, 3.5, 0]} center distanceFactor={12} style={{ pointerEvents: "none" }}>
        <div style={{
          background: "rgba(255,255,255,0.92)", border: "1px solid rgba(212,160,24,0.3)",
          borderRadius: 4, padding: "3px 10px", fontSize: 11, color: T.text, fontFamily: "system-ui", fontWeight: 600,
        }}>
          {exportMw > 0 ? "Export" : "Import"} {Math.abs(exportMw).toFixed(1)} MW
        </div>
      </Html>
    </group>
  );
}

/* ── Control Room ── */
function ControlRoom({ position }) {
  return (
    <group position={position}>
      <mesh castShadow>
        <boxGeometry args={[1.5, 1, 1]} />
        <meshStandardMaterial color="#3a3f50" roughness={0.4} metalness={0.5} />
      </mesh>
      <Html position={[0, 0.8, 0]} center distanceFactor={14} style={{ pointerEvents: "none" }}>
        <div style={{ fontSize: 9, color: T.textSec, fontFamily: "system-ui" }}>Control Room</div>
      </Html>
    </group>
  );
}

/* ── Fire Suppression ── */
function FireSuppression({ position }) {
  return (
    <mesh position={position}>
      <boxGeometry args={[0.4, 0.5, 0.4]} />
      <meshStandardMaterial color="#d32f2f" emissive="#d32f2f" emissiveIntensity={0.1} roughness={0.4} metalness={0.3} />
    </mesh>
  );
}

/* ── Fence Perimeter ── */
function Fence() {
  const points = useMemo(() => {
    const pts = [
      [-10, 0.3, -4], [10, 0.3, -4], [10, 0.3, 4], [-10, 0.3, 4], [-10, 0.3, -4],
    ];
    return new Float32Array(pts.flat());
  }, []);
  return (
    <line>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" array={points} count={5} itemSize={3} />
      </bufferGeometry>
      <lineBasicMaterial color="#555" linewidth={1} />
    </line>
  );
}

/* ── Access Road ── */
function AccessRoad() {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[-10.5, 0.01, 0]}>
      <planeGeometry args={[2, 8]} />
      <meshStandardMaterial color="#8a8a88" roughness={0.9} metalness={0.1} />
    </mesh>
  );
}

/* ── Power Flow Particles ── */
function PowerFlowParticles({ charging, power, count = 40 }) {
  const meshRef = useRef();
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const particles = useMemo(() =>
    Array.from({ length: count }, (_, i) => ({
      t: i / count,
      speed: 0.15 + Math.random() * 0.15,
      offset: (Math.random() - 0.5) * 0.3,
    })), [count]);

  // Path: containers(-4,0,0) -> inverters(0,0,0) -> transformer(6,0,0) -> grid(9,0,0)
  const pathForward = useMemo(() => [
    new THREE.Vector3(-4, 0.6, 0),
    new THREE.Vector3(0, 0.6, 0),
    new THREE.Vector3(6, 0.9, 0),
    new THREE.Vector3(9, 1.5, 0),
  ], []);

  useFrame((state) => {
    if (!meshRef.current || Math.abs(power) < 0.1) return;
    const t = state.clock.elapsedTime;
    const speed = clamp(Math.abs(power) / 50, 0.3, 1.5);
    particles.forEach((p, i) => {
      let frac = ((p.t + t * p.speed * speed) % 1);
      if (charging) frac = 1 - frac;
      const segCount = pathForward.length - 1;
      const segIdx = Math.min(Math.floor(frac * segCount), segCount - 1);
      const segFrac = (frac * segCount) - segIdx;
      const pos = new THREE.Vector3().lerpVectors(pathForward[segIdx], pathForward[segIdx + 1], segFrac);
      pos.z += p.offset;
      dummy.position.copy(pos);
      dummy.scale.setScalar(0.04);
      dummy.updateMatrix();
      meshRef.current.setMatrixAt(i, dummy.matrix);
    });
    meshRef.current.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh ref={meshRef} args={[null, null, count]}>
      <sphereGeometry args={[1, 6, 6]} />
      <meshBasicMaterial color={charging ? T.blue : T.green} transparent opacity={0.8} />
    </instancedMesh>
  );
}

/* ── Full BESS Facility Scene ── */
function BESSFacilityScene({ containers, systemState, selectedContainer, onSelectContainer, txLoadPct, exportMw }) {
  return (
    <>
      {/* Lighting */}
      <ambientLight intensity={0.3} />
      <directionalLight position={[10, 15, 8]} intensity={0.8} castShadow shadow-mapSize={[1024, 1024]} />
      <pointLight position={[-5, 8, -3]} intensity={0.3} color="#D4A018" />

      {/* Ground */}
      <Grid
        args={[40, 40]}
        cellSize={1}
        cellColor="#d0d3d8"
        sectionSize={5}
        sectionColor="#b8bcc2"
        fadeDistance={30}
        position={[0, 0, 0]}
      />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]} receiveShadow>
        <planeGeometry args={[24, 10]} />
        <meshStandardMaterial color="#C5D4B0" roughness={1} metalness={0} />
      </mesh>

      {/* Row 1 of containers (top row, z = -1.8) */}
      {containers.slice(0, 5).map((c, i) => (
        <BatteryContainer
          key={c.id}
          position={[-5 + i * 2.8, 0.6, -1.8]}
          container={c}
          index={i}
          selected={selectedContainer === i}
          onClick={onSelectContainer}
        />
      ))}

      {/* Row 2 of containers (bottom row, z = 1.8) */}
      {containers.slice(5, 10).map((c, i) => (
        <BatteryContainer
          key={c.id}
          position={[-5 + i * 2.8, 0.6, 1.8]}
          container={c}
          index={i + 5}
          selected={selectedContainer === i + 5}
          onClick={onSelectContainer}
        />
      ))}

      {/* Inverters between the rows */}
      {Array.from({ length: 5 }, (_, i) => (
        <InverterUnit
          key={i}
          position={[-5 + i * 2.8, 0.45, 0]}
          index={i}
          active={containers[i].status !== "fault"}
        />
      ))}

      {/* Transformer */}
      <Transformer position={[8, 0.9, 0]} loadPct={txLoadPct} />

      {/* Grid Connection Point */}
      <GridPoint position={[11, 0, 0]} exportMw={exportMw} />

      {/* Fire Suppression units */}
      <FireSuppression position={[-7, 0.25, -1.8]} />
      <FireSuppression position={[-7, 0.25, 1.8]} />

      {/* Control Room */}
      <ControlRoom position={[-9, 0.5, 0]} />

      {/* Fence & Road */}
      <Fence />
      <AccessRoad />

      {/* Power Flow Animation */}
      <PowerFlowParticles
        charging={systemState === "charging"}
        power={containers.reduce((s, c) => s + c.powerKw, 0) / 1000}
      />

      <OrbitControls
        makeDefault
        enablePan
        enableZoom
        enableRotate
        minDistance={5}
        maxDistance={35}
        minPolarAngle={0.2}
        maxPolarAngle={Math.PI / 2.2}
        target={[1, 0, 0]}
      />
    </>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SoC Gauge (SVG Arc)
   ═══════════════════════════════════════════════════════════════════════════ */
function SoCGauge({ soc, size = 100 }) {
  const r = (size - 12) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const startAngle = -225;
  const endAngle = 45;
  const range = endAngle - startAngle;
  const angle = startAngle + (soc / 100) * range;

  function polarToCart(cx2, cy2, r2, deg) {
    const rad = (deg * Math.PI) / 180;
    return { x: cx2 + r2 * Math.cos(rad), y: cy2 + r2 * Math.sin(rad) };
  }

  const bgStart = polarToCart(cx, cy, r, startAngle);
  const bgEnd = polarToCart(cx, cy, r, endAngle);
  const valEnd = polarToCart(cx, cy, r, angle);
  const large = soc / 100 * range > 180 ? 1 : 0;
  const bgLarge = range > 180 ? 1 : 0;

  const bgD = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 ${bgLarge} 1 ${bgEnd.x} ${bgEnd.y}`;
  const valD = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 ${large} 1 ${valEnd.x} ${valEnd.y}`;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <path d={bgD} fill="none" stroke="#1a1f2e" strokeWidth={8} strokeLinecap="round" />
      <path d={valD} fill="none" stroke={socColor(soc)} strokeWidth={8} strokeLinecap="round" />
      <text x={cx} y={cy + 2} textAnchor="middle" fill={T.text} fontSize={18} fontWeight="700" fontFamily="system-ui">
        {soc.toFixed(0)}%
      </text>
      <text x={cx} y={cy + 16} textAnchor="middle" fill={T.textSec} fontSize={9} fontFamily="system-ui">SoC</text>
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Revenue Stacked Bar Chart
   ═══════════════════════════════════════════════════════════════════════════ */
function RevenueChart({ breakdown }) {
  if (!breakdown) return null;
  const keys = ["ffr_dynamic", "dynamic_containment", "arbitrage", "capacity_market", "dno_peak_shaving"];
  const labels = ["FFR", "DC", "Arb", "CM", "DNO"];
  const colors = [T.accent, T.blue, T.green, T.orange, "#e040fb"];
  const total = keys.reduce((s, k) => s + (breakdown[k] || 0), 0);
  if (total <= 0) return <div style={{ color: T.textSec, fontSize: 11 }}>No revenue data</div>;
  const barW = 180;
  const barH = 18;
  let x = 0;

  return (
    <div>
      <svg width={barW} height={barH + 40} style={{ display: "block" }}>
        {keys.map((k, i) => {
          const val = breakdown[k] || 0;
          const w = (val / total) * barW;
          const seg = <rect key={k} x={x} y={0} width={Math.max(w, 0)} height={barH} fill={colors[i]} rx={i === 0 ? 3 : 0} />;
          x += w;
          return seg;
        })}
        {/* Legend */}
        {keys.map((k, i) => (
          <g key={k} transform={`translate(${i * 36}, ${barH + 8})`}>
            <rect width={8} height={8} fill={colors[i]} rx={1} />
            <text x={10} y={8} fill={T.textSec} fontSize={8} fontFamily="system-ui">{labels[i]}</text>
          </g>
        ))}
      </svg>
      <div style={{ fontSize: 11, color: T.textSec, marginTop: 2 }}>
        Total: <span style={{ color: T.text, fontWeight: 600 }}>GBP {fmtNum(total)}/yr</span>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Dispatch Schedule Bars
   ═══════════════════════════════════════════════════════════════════════════ */
function DispatchBars({ schedule }) {
  const barW = 180;
  const barH = 14;
  return (
    <div>
      {schedule.map((slot, i) => {
        const pct = Math.abs(slot.mw) / 50;
        const charging = slot.mw < 0;
        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
            <span style={{ fontSize: 10, color: T.textSec, width: 40, textAlign: "right", fontFamily: "monospace" }}>{slot.time}</span>
            <div style={{ width: barW, height: barH, background: "#1a1f2e", borderRadius: 3, overflow: "hidden", position: "relative" }}>
              <div style={{
                width: `${pct * 100}%`, height: "100%",
                background: charging ? T.blue : T.green,
                borderRadius: 3, opacity: 0.8,
              }} />
            </div>
            <span style={{ fontSize: 10, color: charging ? T.blue : T.green, width: 46, fontFamily: "monospace" }}>
              {charging ? "CHG" : "DIS"} {Math.abs(slot.mw)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Bottom SLD (Single Line Diagram) Strip
   ═══════════════════════════════════════════════════════════════════════════ */
function SingleLineDiagram({ containers, systemState, txLoadPct, exportMw }) {
  const totalPower = containers.reduce((s, c) => s + c.powerKw, 0);
  const avgSoc = containers.reduce((s, c) => s + c.soc, 0) / containers.length;
  const elements = [
    { label: "Battery Racks", value: `${avgSoc.toFixed(0)}% SoC`, on: true, color: socColor(avgSoc) },
    { label: "PCS / Inverters", value: `${(totalPower / 1000).toFixed(1)} MW`, on: true, color: T.accent },
    { label: "LV Bus (0.6kV)", value: "ON", on: true, color: T.green },
    { label: "Step-up TX", value: `${txLoadPct.toFixed(0)}% Load`, on: true, color: txLoadPct > 80 ? T.orange : T.green },
    { label: "33kV Switchgear", value: "CLOSED", on: true, color: T.green },
    { label: "Grid", value: `${exportMw > 0 ? "+" : ""}${exportMw.toFixed(1)} MW`, on: true, color: exportMw > 0 ? T.green : T.blue },
  ];
  const w = 900;
  const elemW = 120;
  const gap = (w - elements.length * elemW) / (elements.length - 1);

  return (
    <svg width="100%" height={70} viewBox={`0 0 ${w} 70`} preserveAspectRatio="xMidYMid meet" style={{ display: "block" }}>
      {elements.map((el, i) => {
        const x = i * (elemW + gap);
        return (
          <g key={i}>
            <rect x={x} y={8} width={elemW} height={44} rx={6} fill="rgba(212,160,24,0.08)" stroke="rgba(212,160,24,0.25)" strokeWidth={1} />
            <circle cx={x + 12} cy={18} r={4} fill={el.on ? el.color : T.red} />
            <text x={x + 20} y={22} fill={T.text} fontSize={10} fontWeight="600" fontFamily="system-ui">{el.label}</text>
            <text x={x + elemW / 2} y={42} textAnchor="middle" fill={el.color} fontSize={11} fontWeight="700" fontFamily="system-ui">{el.value}</text>
            {i < elements.length - 1 && (
              <line x1={x + elemW + 2} y1={30} x2={x + elemW + gap - 2} y2={30} stroke={T.accent} strokeWidth={2} strokeDasharray="4 3" opacity={0.5} />
            )}
          </g>
        );
      })}
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN COMPONENT
   ═══════════════════════════════════════════════════════════════════════════ */
/* ── Bidder Price + Schedule Chart (SVG) ──────────────────────────────── */
function BidderChart({ schedule, prices }) {
  if (!schedule?.length) return null;
  const W = 480, H = 160, PAD = { l: 40, r: 10, t: 10, b: 24 };
  const iW = W - PAD.l - PAD.r, iH = H - PAD.t - PAD.b;
  const n = schedule.length;

  // Price line
  const priceVals = schedule.map(s => s.price_gbp_mwh ?? s.da_price_gbp ?? 0);
  const pMin = Math.min(...priceVals) * 0.9, pMax = Math.max(...priceVals) * 1.1;
  const pRange = pMax - pMin || 1;

  // Power bars
  const powerVals = schedule.map(s => s.power_mw ?? s.combined_power_mw ?? s.da_power_mw ?? 0);
  const maxPow = Math.max(...powerVals.map(Math.abs)) || 1;
  const barW = iW / n * 0.7;

  return (
    <svg width={W} height={H} style={{ display: "block" }}>
      {/* Y axis labels */}
      <text x={PAD.l - 4} y={PAD.t + 6} textAnchor="end" fill="#4B5563" fontSize={9}>{Math.round(pMax)}</text>
      <text x={PAD.l - 4} y={H - PAD.b} textAnchor="end" fill="#4B5563" fontSize={9}>{Math.round(pMin)}</text>
      {/* X axis labels */}
      {schedule.filter((_, i) => i % 4 === 0).map((s, j) => (
        <text key={j} x={PAD.l + (s.hour ?? s.bucket ?? j * 4) / n * iW + barW / 2} y={H - 4} textAnchor="middle" fill="#4B5563" fontSize={8}>
          {String(s.hour ?? s.bucket ?? j * 4).padStart(2, "0")}
        </text>
      ))}
      {/* Power bars */}
      {schedule.map((s, i) => {
        const pw = s.power_mw ?? s.combined_power_mw ?? s.da_power_mw ?? 0;
        const x = PAD.l + i / n * iW;
        const mid = PAD.t + iH / 2;
        const bH = Math.abs(pw) / maxPow * (iH / 2 - 4);
        const y = pw >= 0 ? mid - bH : mid;
        return (
          <rect key={i} x={x} y={y} width={barW} height={bH}
            fill={pw > 0 ? "rgba(82,196,26,0.6)" : pw < 0 ? "rgba(24,144,255,0.5)" : "rgba(100,100,100,0.2)"}
            rx={2}
          />
        );
      })}
      {/* Mid line (zero power) */}
      <line x1={PAD.l} x2={W - PAD.r} y1={PAD.t + iH / 2} y2={PAD.t + iH / 2} stroke="rgba(212,160,24,0.2)" strokeDasharray="3,3" />
      {/* Price line */}
      <polyline
        fill="none"
        stroke="#fa8c16"
        strokeWidth={1.5}
        points={priceVals.map((p, i) =>
          `${PAD.l + i / n * iW + barW / 2},${PAD.t + iH - (p - pMin) / pRange * iH}`
        ).join(" ")}
      />
    </svg>
  );
}

/* ── Bidder Panel Component ──────────────────────────────────────────── */
function BidderPanel({ powerMw, energyMwh, onClose }) {
  const [bidderStrategy, setBidderStrategy] = useState("coordinated");
  const [bidderResult, setBidderResult] = useState(null);
  const [bidderLoading, setBidderLoading] = useState(false);
  const [bidderHours, setBidderHours] = useState(24);

  const runBidder = useCallback(() => {
    setBidderLoading(true);
    api.bess.bidder(powerMw, energyMwh, bidderStrategy, bidderHours)
      .then(d => { if (d) setBidderResult(d); })
      .finally(() => setBidderLoading(false));
  }, [powerMw, energyMwh, bidderStrategy, bidderHours]);

  useEffect(() => { runBidder(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const r = bidderResult;

  return (
    <div style={{
      position: "absolute", top: 0, right: 0, bottom: 0, width: "25%",
      background: T.panel, borderLeft: T.border, zIndex: 10,
      overflowY: "auto", padding: 14, display: "flex", flexDirection: "column",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontWeight: 700, fontSize: 13, color: T.accent }}>Multi-Market Bidder</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: T.textSec, cursor: "pointer", fontSize: 16 }}>x</button>
      </div>

      {/* Controls */}
      <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
        <select
          value={bidderStrategy}
          onChange={e => setBidderStrategy(e.target.value)}
          style={{
            height: 28, background: "#1a1f2e", border: T.border,
            borderRadius: 4, color: "#E8E6E1", fontSize: 11, outline: "none", padding: "0 8px", flex: 1,
          }}
        >
          {BIDDER_STRATEGIES.map(s => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
        </select>
        <select
          value={bidderHours}
          onChange={e => setBidderHours(+e.target.value)}
          style={{
            height: 28, background: "#1a1f2e", border: T.border,
            borderRadius: 4, color: "#E8E6E1", fontSize: 11, outline: "none", padding: "0 8px", width: 60,
          }}
        >
          {[24, 48, 72, 168].map(h => <option key={h} value={h}>{h}h</option>)}
        </select>
        <button
          onClick={runBidder}
          disabled={bidderLoading}
          style={{
            height: 28, padding: "0 12px", background: "rgba(212,160,24,0.2)",
            border: "1px solid rgba(212,160,24,0.4)", borderRadius: 4,
            color: T.accent, fontSize: 11, fontWeight: 600, cursor: "pointer",
          }}
        >
          {bidderLoading ? "..." : "Run"}
        </button>
      </div>

      {r && !r.error && (
        <>
          {/* Revenue summary */}
          <div style={{
            background: "rgba(212,160,24,0.06)", border: T.border, borderRadius: 8,
            padding: 12, marginBottom: 10,
          }}>
            <div style={{ fontSize: 11, color: T.textSec, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
              {r.strategy?.replace(/_/g, " ")} Revenue
            </div>
            {r.combined_revenue_gbp != null ? (
              <>
                <div style={{ fontSize: 22, fontWeight: 700, color: T.green }}>
                  GBP {fmtNum(r.combined_revenue_gbp)}
                </div>
                <div style={{ display: "flex", gap: 16, marginTop: 6 }}>
                  <div>
                    <div style={{ fontSize: 10, color: T.textSec }}>DA Revenue</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: T.text }}>GBP {fmtNum(r.da_revenue_gbp)}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 10, color: T.textSec }}>ID Revenue</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: T.blue }}>{r.id_revenue_gbp >= 0 ? "+" : ""}GBP {fmtNum(r.id_revenue_gbp)}</div>
                  </div>
                </div>
                {r.improvement_pct != null && (
                  <div style={{
                    marginTop: 6, fontSize: 11, color: r.improvement_pct > 0 ? T.green : T.red,
                    fontWeight: 600,
                  }}>
                    {r.improvement_pct > 0 ? "+" : ""}{r.improvement_pct}% vs DA-only
                  </div>
                )}
              </>
            ) : (
              <div style={{ fontSize: 22, fontWeight: 700, color: T.green }}>
                GBP {fmtNum(r.forecast_revenue_gbp ?? r.total_revenue_gbp ?? 0)}
              </div>
            )}
            <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: 10, color: T.textSec }}>
              <span>Trades: {r.num_trades ?? ((r.da_trades ?? 0) + (r.id_trades ?? 0))}</span>
              <span>Cycles: {r.cycles ?? r.da_cycles ?? r.cycles_used ?? "--"}</span>
              {r.lambda_da != null && <span>Lambda: {r.lambda_da}</span>}
            </div>
          </div>

          {/* Price & schedule chart */}
          <div style={{
            background: "rgba(212,160,24,0.06)", border: T.border, borderRadius: 8,
            padding: 8, marginBottom: 10,
          }}>
            <div style={{ fontSize: 11, color: T.textSec, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
              Schedule & Prices
            </div>
            <BidderChart schedule={r.schedule} prices={r.prices} />
            <div style={{ display: "flex", gap: 12, fontSize: 9, color: T.textSec, marginTop: 4, justifyContent: "center" }}>
              <span><span style={{ display: "inline-block", width: 8, height: 8, background: "rgba(82,196,26,0.6)", borderRadius: 2, marginRight: 3, verticalAlign: "middle" }} />Discharge</span>
              <span><span style={{ display: "inline-block", width: 8, height: 8, background: "rgba(24,144,255,0.5)", borderRadius: 2, marginRight: 3, verticalAlign: "middle" }} />Charge</span>
              <span><span style={{ display: "inline-block", width: 12, height: 2, background: "#fa8c16", marginRight: 3, verticalAlign: "middle" }} />Price</span>
            </div>
          </div>

          {/* Trade log */}
          {(r.trades?.length > 0 || r.schedule?.length > 0) && (
            <div style={{
              background: "rgba(212,160,24,0.06)", border: T.border, borderRadius: 8,
              padding: 8, marginBottom: 10,
            }}>
              <div style={{ fontSize: 11, color: T.textSec, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>
                Trades ({(r.trades || r.schedule.filter(s => (s.action || s.da_action) !== "idle")).length})
              </div>
              <div style={{ maxHeight: 200, overflowY: "auto" }}>
                {(r.trades || r.schedule.filter(s => (s.action || s.da_action) !== "idle")).slice(0, 30).map((t, i) => (
                  <div key={i} style={{
                    display: "flex", justifyContent: "space-between", padding: "3px 0",
                    borderBottom: "1px solid rgba(212,160,24,0.06)", fontSize: 10,
                  }}>
                    <span style={{ color: (t.side || t.action || t.da_action) === "buy" || (t.side || t.action || t.da_action) === "charge" ? T.blue : T.green, fontWeight: 600, width: 35 }}>
                      {(t.side || t.action || t.da_action || "").toUpperCase()}
                    </span>
                    <span style={{ color: T.text }}>{t.volume_mw ?? t.volume_mwh ?? Math.abs(t.power_mw ?? t.da_power_mw ?? 0)} MW</span>
                    <span style={{ color: T.orange }}>GBP {t.price_gbp_mwh ?? t.da_price_gbp ?? "--"}/MWh</span>
                    <span style={{ color: T.textSec }}>H{t.hour ?? t.bucket ?? i}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* SoC profile */}
          {r.soc_profile && (
            <div style={{
              background: "rgba(212,160,24,0.06)", border: T.border, borderRadius: 8,
              padding: 8,
            }}>
              <div style={{ fontSize: 11, color: T.textSec, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
                SoC Profile
              </div>
              <svg width="100%" viewBox="0 0 480 60" style={{ display: "block" }}>
                {r.soc_profile.map((s, i) => {
                  const x = i / r.soc_profile.length * 470 + 5;
                  const h = s / 100 * 50;
                  return (
                    <rect key={i} x={x} y={55 - h} width={Math.max(1, 470 / r.soc_profile.length - 1)} height={h}
                      fill={s > 80 ? T.green : s > 40 ? T.orange : T.red} opacity={0.7} rx={1}
                    />
                  );
                })}
              </svg>
            </div>
          )}
        </>
      )}

      {r?.error && (
        <div style={{ padding: 12, color: T.red, fontSize: 12 }}>{r.error}</div>
      )}

      <div style={{ marginTop: "auto", paddingTop: 10, fontSize: 9, color: T.textSec, textAlign: "center" }}>
        Based on BessBidder (Miskiw et al., ACM e-Energy 2025)
      </div>
    </div>
  );
}

export default function BESSFacilityTwin({ onClose, lat, lon }) {
  const siteLat = lat || 52.5;
  const siteLon = lon || -1.5;

  /* ── Config state ── */
  const [powerMw, setPowerMw] = useState(50);
  const [duration, setDuration] = useState("2h");
  const [strategy, setStrategy] = useState("hybrid");
  const [isLive, setIsLive] = useState(false);
  const [bidderOpen, setBidderOpen] = useState(false);

  /* ── Data state ── */
  const [containers, setContainers] = useState(createInitialContainers);
  const [systemState, setSystemState] = useState("idle"); // charging | discharging | idle
  const [alarms, setAlarms] = useState(createInitialAlarms);
  const [selectedContainer, setSelectedContainer] = useState(null);
  const [siteScore, setSiteScore] = useState(null);
  const [financial, setFinancial] = useState(null);
  const [revenue, setRevenue] = useState(null);
  const [todayRevenue, setTodayRevenue] = useState(1842);
  const [txLoadPct, setTxLoadPct] = useState(55);

  const energyMwh = useMemo(() => powerMw * parseFloat(duration), [powerMw, duration]);

  /* ── Dispatch schedule (next 6 hours) ── */
  const dispatch = useMemo(() => {
    const now = new Date();
    return Array.from({ length: 6 }, (_, i) => {
      const h = new Date(now.getTime() + i * 3600000);
      const hour = h.getHours();
      const charging = hour >= 1 && hour <= 5;
      return {
        time: `${String(hour).padStart(2, "0")}:00`,
        mw: charging ? -(powerMw * (0.6 + Math.random() * 0.4)) : powerMw * (0.3 + Math.random() * 0.7),
      };
    });
  }, [powerMw]);

  /* ── Computed totals ── */
  const totalPowerMw = useMemo(() => containers.reduce((s, c) => s + c.powerKw, 0) / 1000, [containers]);
  const avgSoc = useMemo(() => containers.reduce((s, c) => s + c.soc, 0) / containers.length, [containers]);
  const systemEff = useMemo(() => 88 + Math.random() * 6, [containers]);
  const exportMw = systemState === "discharging" ? Math.abs(totalPowerMw) : systemState === "charging" ? -Math.abs(totalPowerMw) : 0;

  /* ── API calls on mount ── */
  useEffect(() => {
    api.bess.score(siteLat, siteLon).then(d => { if (d) setSiteScore(d); });
  }, [siteLat, siteLon]);

  const runSizing = useCallback(() => {
    api.bess.sizing(powerMw, parseFloat(duration), strategy, powerMw)
      .then(d => { if (d) setFinancial(d); });
  }, [powerMw, duration, strategy]);

  const runRevenue = useCallback(() => {
    api.bess.revenue(powerMw, energyMwh, strategy)
      .then(d => { if (d) setRevenue(d); });
  }, [powerMw, energyMwh, strategy]);

  useEffect(() => {
    runSizing();
    runRevenue();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── WebSocket or simulated telemetry ── */
  useEffect(() => {
    const host = window.location.host;
    let ws;
    let simInterval;
    let stateInterval;

    try {
      ws = new WebSocket(`ws://${host}/ws/bess-facility`);
      ws.onopen = () => setIsLive(true);
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.containers) setContainers(data.containers);
          if (data.system_state) setSystemState(data.system_state);
          if (data.tx_load_pct != null) setTxLoadPct(data.tx_load_pct);
        } catch { /* ignore */ }
      };
      ws.onerror = () => { ws.close(); };
      ws.onclose = () => { setIsLive(false); startSim(); };
    } catch {
      startSim();
    }

    function startSim() {
      // Cycle system state every ~20s
      stateInterval = setInterval(() => {
        setSystemState(prev => {
          if (prev === "idle") return Math.random() > 0.5 ? "charging" : "discharging";
          if (prev === "charging") return Math.random() > 0.3 ? "charging" : "discharging";
          return Math.random() > 0.3 ? "discharging" : "idle";
        });
      }, 20000);

      // Telemetry every 2s
      simInterval = setInterval(() => {
        setContainers(prev => prev.map(c => {
          let newSoc = randomWalk(c.soc, 1.5, 15, 100);
          let newPower = c.powerKw;
          setSystemState(st => {
            if (st === "charging") newPower = -(powerMw / CONTAINER_COUNT) * 1000 * (0.8 + Math.random() * 0.4);
            else if (st === "discharging") newPower = (powerMw / CONTAINER_COUNT) * 1000 * (0.8 + Math.random() * 0.4);
            else newPower = (Math.random() - 0.5) * 200;
            return st;
          });
          return {
            ...c,
            soc: newSoc,
            powerKw: newPower,
            tempC: randomWalk(c.tempC, 0.5, 18, 38),
            voltageV: randomWalk(c.voltageV, 3, 580, 640),
            currentA: randomWalk(c.currentA, 5, 40, 160),
            status: newPower < -100 ? "charging" : newPower > 100 ? "discharging" : "idle",
          };
        }));
        setTxLoadPct(prev => randomWalk(prev, 3, 20, 95));
        setTodayRevenue(prev => prev + Math.random() * 5);
      }, 2000);
    }

    return () => {
      if (ws) ws.close();
      clearInterval(simInterval);
      clearInterval(stateInterval);
    };
  }, [powerMw]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ── Score badge color ── */
  function recColor(rec) {
    if (!rec) return T.textSec;
    const r = rec.toUpperCase();
    if (r.includes("HIGH")) return T.green;
    if (r.includes("PROMISING")) return T.orange;
    if (r.includes("MARGINAL")) return T.orange;
    return T.red;
  }

  /* ── Inline card style helper ── */
  const cardStyle = {
    background: "rgba(212,160,24,0.06)",
    border: T.border,
    borderRadius: 8,
    padding: 12,
    marginBottom: 10,
  };
  const cardTitle = { fontSize: 11, color: T.textSec, fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 };
  const kpiRow = { display: "flex", justifyContent: "space-between", padding: "2px 0" };
  const kpiLabel = { fontSize: 11, color: T.textSec };
  const kpiVal = { fontSize: 12, color: T.text, fontWeight: 600 };

  const selC = selectedContainer != null ? containers[selectedContainer] : null;

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999, background: T.bg,
      display: "flex", flexDirection: "column", fontFamily: "system-ui", color: T.text,
    }}>

      {/* ═══════════════ TOP BAR ═══════════════ */}
      <div style={{
        height: 52, background: T.panel, borderBottom: T.border,
        display: "flex", alignItems: "center", padding: "0 16px", gap: 14, flexShrink: 0,
      }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: T.accent, marginRight: 8 }}>BESS Facility Twin</div>

        {/* Power MW */}
        <label style={{ fontSize: 11, color: T.textSec }}>Power MW</label>
        <input
          type="number"
          value={powerMw}
          onChange={e => setPowerMw(Math.max(1, +e.target.value || 1))}
          style={{
            width: 56, height: 28, background: "#1a1f2e", border: T.border,
            borderRadius: 4, color: "#E8E6E1", textAlign: "center", fontSize: 12, outline: "none",
          }}
        />

        {/* Duration */}
        <label style={{ fontSize: 11, color: T.textSec }}>Duration</label>
        <select
          value={duration}
          onChange={e => setDuration(e.target.value)}
          style={{
            height: 28, background: "#1a1f2e", border: T.border,
            borderRadius: 4, color: "#E8E6E1", fontSize: 12, outline: "none", padding: "0 8px",
          }}
        >
          {DURATIONS.map(d => <option key={d} value={d}>{d}</option>)}
        </select>

        {/* Strategy */}
        <label style={{ fontSize: 11, color: T.textSec }}>Strategy</label>
        <select
          value={strategy}
          onChange={e => setStrategy(e.target.value)}
          style={{
            height: 28, background: "#1a1f2e", border: T.border,
            borderRadius: 4, color: "#E8E6E1", fontSize: 12, outline: "none", padding: "0 8px",
          }}
        >
          {STRATEGIES.map(s => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
        </select>

        {/* Live indicator */}
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginLeft: 4 }}>
          <div style={{ width: 8, height: 8, borderRadius: 4, background: isLive ? T.green : T.orange }} />
          <span style={{ fontSize: 11, color: isLive ? T.green : T.orange }}>{isLive ? "LIVE" : "SIMULATED"}</span>
        </div>

        <div style={{ flex: 1 }} />

        {/* Action buttons */}
        <button
          onClick={() => {
            api.bess.score(siteLat, siteLon).then(d => { if (d) setSiteScore(d); });
          }}
          style={{
            height: 30, padding: "0 14px", background: "rgba(212,160,24,0.15)",
            border: "1px solid rgba(212,160,24,0.4)", borderRadius: 5, color: T.accent,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
          }}
        >
          Score Site
        </button>
        <button
          onClick={() => { runSizing(); runRevenue(); }}
          style={{
            height: 30, padding: "0 14px", background: "rgba(212,160,24,0.15)",
            border: "1px solid rgba(212,160,24,0.4)", borderRadius: 5, color: T.accent,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
          }}
        >
          Run Sizing
        </button>
        <button
          onClick={() => setBidderOpen(p => !p)}
          style={{
            height: 30, padding: "0 14px",
            background: bidderOpen ? "rgba(212,160,24,0.35)" : "rgba(250,140,22,0.15)",
            border: `1px solid ${bidderOpen ? "rgba(212,160,24,0.6)" : "rgba(250,140,22,0.4)"}`,
            borderRadius: 5, color: bidderOpen ? T.accent : T.orange,
            fontSize: 12, fontWeight: 600, cursor: "pointer",
          }}
        >
          Bidder
        </button>
        <button
          onClick={onClose}
          style={{
            width: 30, height: 30, background: "rgba(245,34,45,0.15)",
            border: "1px solid rgba(245,34,45,0.3)", borderRadius: 5,
            color: T.red, fontSize: 18, cursor: "pointer", lineHeight: 1,
          }}
        >
          x
        </button>
      </div>

      {/* ═══════════════ MAIN BODY ═══════════════ */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden", position: "relative" }}>

        {/* ─── LEFT PANEL (25%) ─── */}
        <div style={{
          width: "25%", background: T.panel, borderRight: T.border,
          overflowY: "auto", padding: 14, flexShrink: 0,
        }}>

          {/* Site Score Card */}
          <div style={cardStyle}>
            <div style={cardTitle}>Site Score</div>
            {siteScore ? (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
                  <span style={{ fontSize: 32, fontWeight: 700, color: T.accent }}>{siteScore.total_score ?? "--"}</span>
                  <span style={{ fontSize: 13, color: T.textSec }}>/100</span>
                </div>
                {siteScore.recommendation && (
                  <span style={{
                    display: "inline-block", padding: "2px 10px", borderRadius: 10,
                    fontSize: 10, fontWeight: 700, color: "#fff",
                    background: recColor(siteScore.recommendation),
                  }}>
                    {siteScore.recommendation.replace(/_/g, " ")}
                  </span>
                )}
                {siteScore.max_feasible_mw != null && (
                  <div style={{ ...kpiRow, marginTop: 6 }}>
                    <span style={kpiLabel}>Max Feasible</span>
                    <span style={kpiVal}>{siteScore.max_feasible_mw} MW</span>
                  </div>
                )}
              </>
            ) : (
              <div style={{ fontSize: 11, color: T.textSec }}>Loading...</div>
            )}
          </div>

          {/* Financial Summary Card */}
          <div style={cardStyle}>
            <div style={cardTitle}>Financial Summary</div>
            {financial ? (
              <>
                <div style={kpiRow}><span style={kpiLabel}>NPV</span><span style={kpiVal}>GBP {fmtNum(financial.npv || financial.npv_gbp)}</span></div>
                <div style={kpiRow}><span style={kpiLabel}>IRR</span><span style={kpiVal}>{((financial.irr || financial.irr_pct || 0) * (financial.irr > 1 ? 1 : 100)).toFixed(1)}%</span></div>
                <div style={kpiRow}><span style={kpiLabel}>CAPEX</span><span style={kpiVal}>GBP {fmtNum(financial.capex || financial.capex_gbp)}</span></div>
                <div style={kpiRow}><span style={kpiLabel}>Payback</span><span style={kpiVal}>{(financial.payback_years ?? financial.payback ?? "--")} yrs</span></div>
              </>
            ) : (
              <div style={{ fontSize: 11, color: T.textSec }}>Run sizing to populate</div>
            )}
          </div>

          {/* Revenue Breakdown Card */}
          <div style={cardStyle}>
            <div style={cardTitle}>Revenue Breakdown</div>
            {revenue && revenue.breakdown ? (
              <RevenueChart breakdown={revenue.breakdown} />
            ) : (
              <div style={{ fontSize: 11, color: T.textSec }}>Awaiting revenue data</div>
            )}
          </div>

          {/* Degradation Card */}
          <div style={cardStyle}>
            <div style={cardTitle}>Degradation</div>
            <div style={kpiRow}><span style={kpiLabel}>Cycles/year</span><span style={kpiVal}>{financial?.cycles_per_year ?? 365}</span></div>
            <div style={kpiRow}><span style={kpiLabel}>Capacity Factor</span><span style={kpiVal}>{((financial?.capacity_factor ?? 0.12) * 100).toFixed(1)}%</span></div>
            <div style={kpiRow}><span style={kpiLabel}>Degrad. Cost/yr</span><span style={kpiVal}>GBP {fmtNum(financial?.degradation_cost_yr ?? 45000)}</span></div>
          </div>

          {/* Grid Connection Card */}
          <div style={cardStyle}>
            <div style={cardTitle}>Grid Connection</div>
            <div style={kpiRow}><span style={kpiLabel}>Voltage</span><span style={kpiVal}>33 kV</span></div>
            <div style={kpiRow}><span style={kpiLabel}>Connection Cost</span><span style={kpiVal}>GBP {fmtNum(financial?.connection_cost ?? 750000)}</span></div>
            <div style={kpiRow}><span style={kpiLabel}>Distance</span><span style={kpiVal}>{(financial?.grid_distance_km ?? 2.4).toFixed(1)} km</span></div>
          </div>
        </div>

        {/* ─── CENTER PANEL (50%) — 3D Scene ─── */}
        <div style={{ flex: 1, position: "relative" }}>
          <React.Suspense fallback={<div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#666", fontSize: 12 }}>Loading BESS 3D view...</div>}>
          <Canvas
            shadows
            camera={{ position: [0, 12, 16], fov: 45 }}
            style={{ background: T.bg }}
            gl={{ antialias: true, alpha: false }}
            frameloop="demand"
          >
            <BESSFacilityScene
              containers={containers}
              systemState={systemState}
              selectedContainer={selectedContainer}
              onSelectContainer={(i) => setSelectedContainer(prev => prev === i ? null : i)}
              txLoadPct={txLoadPct}
              exportMw={exportMw}
            />
            {/* <PostprocessingEffects bloom={1.4} bloomThreshold={0.3} chromaticAberration={0.0015} vignette={0.55} /> */}
          </Canvas>
          </React.Suspense>
          {/* State badge overlay */}
          <div style={{
            position: "absolute", top: 12, left: "50%", transform: "translateX(-50%)",
            background: systemState === "charging" ? "rgba(24,144,255,0.2)" : systemState === "discharging" ? "rgba(82,196,26,0.2)" : "rgba(212,160,24,0.12)",
            border: `1px solid ${systemState === "charging" ? T.blue : systemState === "discharging" ? T.green : "rgba(212,160,24,0.3)"}`,
            borderRadius: 20, padding: "4px 18px", fontSize: 12, fontWeight: 700,
            color: systemState === "charging" ? T.blue : systemState === "discharging" ? T.green : T.textSec,
            textTransform: "uppercase", letterSpacing: 1,
          }}>
            {systemState} | {Math.abs(totalPowerMw).toFixed(1)} MW
          </div>
          {/* Config overlay bottom-left */}
          <div style={{
            position: "absolute", bottom: 12, left: 12,
            background: T.panel, border: T.border, borderRadius: 6, padding: "6px 12px",
            fontSize: 10, color: T.textSec,
          }}>
            {powerMw} MW / {energyMwh} MWh | {strategy.replace(/_/g, " ")} | {siteLat.toFixed(2)}, {siteLon.toFixed(2)}
          </div>
        </div>

        {/* ─── RIGHT PANEL (25%) — Telemetry ─── */}
        <div style={{
          width: "25%", background: T.panel, borderLeft: T.border,
          overflowY: "auto", padding: 14, flexShrink: 0,
        }}>

          {/* System Overview */}
          <div style={cardStyle}>
            <div style={cardTitle}>System Overview</div>
            <div style={{ display: "flex", justifyContent: "space-around", textAlign: "center", marginBottom: 4 }}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 700, color: systemState === "charging" ? T.blue : systemState === "discharging" ? T.green : T.textSec }}>
                  {Math.abs(totalPowerMw).toFixed(1)}
                </div>
                <div style={{ fontSize: 10, color: T.textSec }}>MW {systemState === "charging" ? "(CHG)" : systemState === "discharging" ? "(DIS)" : ""}</div>
              </div>
              <div>
                <div style={{ fontSize: 20, fontWeight: 700, color: socColor(avgSoc) }}>{avgSoc.toFixed(0)}%</div>
                <div style={{ fontSize: 10, color: T.textSec }}>Avg SoC</div>
              </div>
              <div>
                <div style={{ fontSize: 20, fontWeight: 700, color: T.text }}>{systemEff.toFixed(1)}%</div>
                <div style={{ fontSize: 10, color: T.textSec }}>Efficiency</div>
              </div>
            </div>
          </div>

          {/* Container Detail (when selected) */}
          {selC ? (
            <div style={cardStyle}>
              <div style={{ ...cardTitle, display: "flex", justifyContent: "space-between" }}>
                <span>Container {selC.id}</span>
                <button onClick={() => setSelectedContainer(null)} style={{ background: "none", border: "none", color: T.textSec, cursor: "pointer", fontSize: 14, lineHeight: 1 }}>x</button>
              </div>
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 4 }}>
                <SoCGauge soc={selC.soc} size={90} />
              </div>
              <div style={kpiRow}>
                <span style={kpiLabel}>Power</span>
                <span style={{ ...kpiVal, color: selC.powerKw > 0 ? T.green : selC.powerKw < 0 ? T.blue : T.textSec }}>
                  {selC.powerKw > 0 ? "+" : ""}{(selC.powerKw).toFixed(0)} kW
                </span>
              </div>
              <div style={kpiRow}><span style={kpiLabel}>Temperature</span><span style={{ ...kpiVal, color: selC.tempC > 32 ? T.red : T.text }}>{selC.tempC.toFixed(1)} C</span></div>
              <div style={kpiRow}><span style={kpiLabel}>Voltage</span><span style={kpiVal}>{selC.voltageV.toFixed(0)} V</span></div>
              <div style={kpiRow}><span style={kpiLabel}>Current</span><span style={kpiVal}>{selC.currentA.toFixed(0)} A</span></div>
              <div style={kpiRow}><span style={kpiLabel}>Cycles</span><span style={kpiVal}>{selC.cycles}</span></div>
              <div style={kpiRow}><span style={kpiLabel}>Health</span><span style={{ ...kpiVal, color: selC.healthPct > 90 ? T.green : T.orange }}>{selC.healthPct.toFixed(1)}%</span></div>
            </div>
          ) : (
            <div style={{ ...cardStyle, textAlign: "center", color: T.textSec, fontSize: 11, padding: 20 }}>
              Click a container in the 3D view to inspect
            </div>
          )}

          {/* Revenue Live */}
          <div style={cardStyle}>
            <div style={cardTitle}>Revenue Today</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: T.green }}>GBP {fmtNum(todayRevenue)}</div>
            <div style={{ fontSize: 10, color: T.textSec, marginTop: 2 }}>
              Projected daily: GBP {fmtNum(todayRevenue * (24 / new Date().getHours() || 1))}
            </div>
          </div>

          {/* Dispatch Schedule */}
          <div style={cardStyle}>
            <div style={cardTitle}>Dispatch Schedule (next 6h)</div>
            <DispatchBars schedule={dispatch} />
          </div>

          {/* Alarms */}
          <div style={cardStyle}>
            <div style={cardTitle}>Alarms</div>
            {alarms.map(a => (
              <div key={a.id} style={{
                display: "flex", gap: 6, alignItems: "flex-start", padding: "4px 0",
                borderBottom: "1px solid rgba(212,160,24,0.06)",
              }}>
                <div style={{
                  width: 7, height: 7, borderRadius: 4, marginTop: 4, flexShrink: 0,
                  background: a.severity === "critical" ? T.red : a.severity === "warning" ? T.orange : T.blue,
                }} />
                <div>
                  <div style={{ fontSize: 11, color: T.text }}>{a.message}</div>
                  <div style={{ fontSize: 9, color: T.textSec }}>{a.time}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Bidder overlay panel */}
        {bidderOpen && (
          <BidderPanel powerMw={powerMw} energyMwh={energyMwh} onClose={() => setBidderOpen(false)} />
        )}
      </div>

      {/* ═══════════════ BOTTOM STRIP — SLD ═══════════════ */}
      <div style={{
        height: 80, background: T.panel, borderTop: T.border,
        padding: "5px 24px", flexShrink: 0, display: "flex", alignItems: "center",
      }}>
        <SingleLineDiagram containers={containers} systemState={systemState} txLoadPct={txLoadPct} exportMw={exportMw} />
      </div>
    </div>
  );
}

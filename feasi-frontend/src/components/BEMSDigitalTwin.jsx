import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Grid, Html } from "@react-three/drei";
import * as THREE from "three";

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

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function randomWalk(prev, step, lo, hi) {
  return clamp(prev + (Math.random() - 0.5) * step, lo, hi);
}

function formatTime(d) {
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDate(d) {
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}

/* ── Initial simulated state ──────────────────────────────────────────── */
function createInitialState() {
  const chillers = Array.from({ length: 6 }, (_, i) => ({
    id: `CH-${i + 1}`,
    running: i < 4,
    loadPct: 60 + Math.random() * 30,
    supplyTemp: 5.5 + Math.random() * 1.5,
    returnTemp: 11 + Math.random() * 2,
  }));

  const transformers = [
    { id: "TX-1", loadPct: 62, ratingKva: 2000, status: "normal" },
    { id: "TX-2", loadPct: 48, ratingKva: 2000, status: "normal" },
  ];

  const zones = [
    { id: "Z1", name: "Ground Floor", temp: 21.4, setpoint: 21.0, humidity: 45, mode: "cooling" },
    { id: "Z2", name: "1st Floor", temp: 22.1, setpoint: 21.5, humidity: 48, mode: "cooling" },
    { id: "Z3", name: "2nd Floor", temp: 20.8, setpoint: 21.0, humidity: 42, mode: "heating" },
    { id: "Z4", name: "3rd Floor", temp: 23.2, setpoint: 22.0, humidity: 51, mode: "cooling" },
    { id: "Z5", name: "4th Floor", temp: 21.0, setpoint: 21.0, humidity: 44, mode: "idle" },
    { id: "Z6", name: "Server Room", temp: 18.5, setpoint: 18.0, humidity: 38, mode: "cooling" },
  ];

  const alarms = [
    { id: 1, time: "14:32:18", severity: "warning", message: "CH-3 supply temp high (7.8C)", acked: false },
    { id: 2, time: "13:15:42", severity: "info", message: "TX-1 load > 60% threshold", acked: true },
    { id: 3, time: "11:48:05", severity: "critical", message: "Zone Z4 temp deviation +1.2C", acked: false },
    { id: 4, time: "10:22:33", severity: "warning", message: "Power factor below 0.93", acked: true },
    { id: 5, time: "09:05:11", severity: "info", message: "Scheduled maintenance CH-5 complete", acked: true },
  ];

  return {
    powerKw: 452,
    powerFactor: 0.94,
    todayKwh: 7840,
    monthKwh: 198500,
    yearKwh: 2145000,
    coolingTodayGj: 28.4,
    coolingMonthGj: 712,
    coolingYearGj: 8540,
    carbonKg: 1568,
    eer: 3.8,
    eerHistory: Array.from({ length: 24 }, (_, i) => ({ hour: i, value: 3.2 + Math.random() * 1.2 })),
    chillers,
    transformers,
    zones,
    alarms,
    breakerStates: { main: true, bus1: true, bus2: true, dist1: true, dist2: true, dist3: true },
  };
}

/* ═══════════════════════════════════════════════════════════════════════════
   3D Building Components
   ═══════════════════════════════════════════════════════════════════════════ */

function FloorPlate({ position, size, consumption, index }) {
  const meshRef = useRef();
  const intensity = 0.3 + consumption * 0.7;
  const color = new THREE.Color().setHSL(0.72 - consumption * 0.15, 0.8, 0.15 + intensity * 0.35);

  useFrame((state) => {
    if (meshRef.current) {
      meshRef.current.material.emissiveIntensity = 0.3 + Math.sin(state.clock.elapsedTime * 0.5 + index) * 0.1;
    }
  });

  return (
    <mesh ref={meshRef} position={position} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.4}
        transparent
        opacity={0.85}
        roughness={0.3}
        metalness={0.6}
      />
    </mesh>
  );
}

function BuildingEdges({ position, size }) {
  const geo = useMemo(() => new THREE.BoxGeometry(...size), [size]);
  return (
    <lineSegments position={position}>
      <edgesGeometry args={[geo]} />
      <lineBasicMaterial color="#D4A018" opacity={0.4} transparent />
    </lineSegments>
  );
}

function EnergyParticles({ count = 60 }) {
  const meshRef = useRef();
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const particles = useMemo(() => {
    return Array.from({ length: count }, () => ({
      angle: Math.random() * Math.PI * 2,
      radius: 3.5 + Math.random() * 2,
      speed: 0.3 + Math.random() * 0.5,
      y: Math.random() * 8 - 1,
      ySpeed: 0.2 + Math.random() * 0.4,
      phase: Math.random() * Math.PI * 2,
    }));
  }, [count]);

  useFrame((state) => {
    if (!meshRef.current) return;
    const t = state.clock.elapsedTime;
    particles.forEach((p, i) => {
      const a = p.angle + t * p.speed;
      dummy.position.set(
        Math.cos(a) * p.radius,
        p.y + Math.sin(t * p.ySpeed + p.phase) * 1.5,
        Math.sin(a) * p.radius
      );
      dummy.scale.setScalar(0.03 + Math.sin(t * 2 + p.phase) * 0.015);
      dummy.updateMatrix();
      meshRef.current.setMatrixAt(i, dummy.matrix);
    });
    meshRef.current.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh ref={meshRef} args={[null, null, count]}>
      <sphereGeometry args={[1, 8, 8]} />
      <meshBasicMaterial color="#D4A018" transparent opacity={0.7} />
    </instancedMesh>
  );
}

/* ── Clickable Equipment Piece ── */
function EquipmentPiece({ position, size, color, label, status, alertLevel, data, selected, onClick }) {
  const meshRef = useRef();
  const [hovered, setHovered] = useState(false);

  useFrame(() => {
    if (meshRef.current) {
      meshRef.current.material.emissiveIntensity = hovered ? 0.6 : selected ? 0.4 : 0.15;
    }
  });

  const alertColor = alertLevel === "critical" ? "#f5222d" : alertLevel === "warning" ? "#fa8c16" : null;

  return (
    <group position={position}>
      <mesh
        ref={meshRef}
        onClick={(e) => { e.stopPropagation(); onClick?.({ label, status, data, position }); }}
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { setHovered(false); document.body.style.cursor = "auto"; }}
        castShadow
      >
        <boxGeometry args={size} />
        <meshStandardMaterial
          color={color}
          emissive={selected ? "#D4A018" : color}
          emissiveIntensity={0.15}
          transparent
          opacity={hovered ? 1 : 0.9}
          roughness={0.2}
          metalness={0.7}
        />
      </mesh>
      {/* Equipment label — always visible */}
      <Html position={[0, size[1] / 2 + 0.3, 0]} center distanceFactor={10} style={{ pointerEvents: "none" }}>
        <div style={{
          background: "rgba(255,255,255,0.92)", border: "1px solid rgba(212,160,24,0.3)",
          borderRadius: 4, padding: "2px 8px", whiteSpace: "nowrap", fontSize: 10,
          color: "#1A1D23", fontFamily: "system-ui", textAlign: "center",
        }}>
          {label}
          {status && <span style={{ marginLeft: 6, color: status === "Run" || status === "ON" ? "#52c41a" : "#f5222d", fontWeight: 600 }}>{status}</span>}
        </div>
      </Html>
      {/* Alert indicator badge */}
      {alertColor && (
        <Html position={[size[0] / 2 + 0.15, size[1] / 2 + 0.15, 0]} center style={{ pointerEvents: "none" }}>
          <div style={{
            width: 16, height: 16, borderRadius: 8, background: alertColor,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 10, fontWeight: 700, color: "#fff", border: "2px solid #F2F3F5",
          }}>!</div>
        </Html>
      )}
    </group>
  );
}

/* ── Azure DT-style floating property card ── */
function PropertyPopup({ equipment, onClose }) {
  if (!equipment) return null;
  const { label, status, data, position } = equipment;
  return (
    <Html position={[position[0] + 1.5, position[1] + 0.5, position[2]]} style={{ pointerEvents: "auto" }}>
      <div style={{
        background: "rgba(255,255,255,0.95)", border: "1px solid rgba(212,160,24,0.3)",
        borderRadius: 8, padding: 14, width: 220, fontFamily: "system-ui",
        color: "#1A1D23", boxShadow: "0 8px 32px rgba(0,0,0,0.12)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <span style={{ fontWeight: 700, fontSize: 14 }}>{label}</span>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#4B5563", cursor: "pointer", fontSize: 16 }}>×</button>
        </div>
        <div style={{ display: "flex", gap: 12, marginBottom: 8 }}>
          <button style={{ background: "rgba(212,160,24,0.2)", border: "1px solid rgba(212,160,24,0.4)", borderRadius: 4, color: "#1A1D23", padding: "2px 10px", fontSize: 11, cursor: "pointer" }}>State</button>
          <button style={{ background: "transparent", border: "1px solid rgba(212,160,24,0.2)", borderRadius: 4, color: "#4B5563", padding: "2px 10px", fontSize: 11, cursor: "pointer" }}>All properties</button>
        </div>
        {data?.alertMessage && (
          <div style={{ background: "rgba(245,34,45,0.1)", border: "1px solid rgba(245,34,45,0.3)", borderRadius: 4, padding: "6px 8px", marginBottom: 8, fontSize: 11 }}>
            <span style={{ color: "#f5222d", fontWeight: 600 }}>⚠ {data.alertMessage}</span>
          </div>
        )}
        {data && Object.entries(data).filter(([k]) => k !== "alertMessage").map(([key, val]) => (
          <div key={key} style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px solid rgba(212,160,24,0.08)" }}>
            <span style={{ fontSize: 11, color: "#4B5563" }}>{key.replace(/([A-Z])/g, " $1").trim()}</span>
            <span style={{ fontSize: 11, fontWeight: 600, color: "#1A1D23" }}>{typeof val === "number" ? val.toFixed(1) : String(val)}</span>
          </div>
        ))}
      </div>
    </Html>
  );
}

function Building({ zones, chillers, transformers, selectedEquipment, onSelectEquipment }) {
  const floorCount = 5;
  const floorHeight = 1.2;
  const gap = 0.15;
  const floorWidth = 4;
  const floorDepth = 3;

  const consumptions = useMemo(() => {
    if (!zones || zones.length === 0) return Array(floorCount).fill(0.5);
    return Array.from({ length: floorCount }, (_, i) => {
      const z = zones[i];
      if (!z) return 0.5;
      const diff = Math.abs(z.temp - z.setpoint);
      return clamp(diff / 3, 0.1, 1.0);
    });
  }, [zones]);

  return (
    <group position={[0, 0, 0]}>
      {/* Building floors */}
      {Array.from({ length: floorCount }, (_, i) => {
        const y = i * (floorHeight + gap) + floorHeight / 2;
        const size = [floorWidth - i * 0.05, floorHeight, floorDepth - i * 0.03];
        return (
          <React.Fragment key={i}>
            <FloorPlate position={[0, y, 0]} size={size} consumption={consumptions[i]} index={i} />
            <BuildingEdges position={[0, y, 0]} size={size} />
          </React.Fragment>
        );
      })}

      {/* Chillers — positioned on the roof */}
      {(chillers || []).slice(0, 6).map((ch, i) => {
        const x = -1.5 + (i % 3) * 1.5;
        const z = i < 3 ? -2.2 : -3.4;
        const y = floorCount * (floorHeight + gap) + 0.4;
        const chAlert = ch.supplyTemp > 7.5 ? "warning" : null;
        return (
          <EquipmentPiece
            key={ch.id}
            position={[x, y, z]}
            size={[0.8, 0.6, 0.5]}
            color={ch.running ? "#1890ff" : "#555"}
            label={ch.id}
            status={ch.running ? "Run" : "Stop"}
            alertLevel={chAlert}
            data={{
              "Load": `${ch.loadPct.toFixed(0)}%`,
              "Supply Temp": `${ch.supplyTemp.toFixed(1)}°C`,
              "Return Temp": `${ch.returnTemp.toFixed(1)}°C`,
              ...(chAlert ? { alertMessage: `Supply temp high (${ch.supplyTemp.toFixed(1)}°C)` } : {}),
            }}
            selected={selectedEquipment?.label === ch.id}
            onClick={onSelectEquipment}
          />
        );
      })}

      {/* Transformers — on the ground floor side */}
      {(transformers || []).map((tx, i) => (
        <EquipmentPiece
          key={tx.id}
          position={[3 + i * 1.2, 0.5, 0]}
          size={[0.7, 0.9, 0.6]}
          color={tx.loadPct > 75 ? "#fa8c16" : "#52c41a"}
          label={tx.id}
          status={`${tx.loadPct.toFixed(0)}%`}
          alertLevel={tx.loadPct > 80 ? "warning" : null}
          data={{
            "Load": `${tx.loadPct.toFixed(0)}%`,
            "Rating": `${tx.ratingKva} kVA`,
            "Status": tx.status,
            ...(tx.loadPct > 80 ? { alertMessage: `Load above 80% (${tx.loadPct.toFixed(0)}%)` } : {}),
          }}
          selected={selectedEquipment?.label === tx.id}
          onClick={onSelectEquipment}
        />
      ))}

      {/* HVAC units — one per floor, on the building side */}
      {(zones || []).slice(0, 5).map((z, i) => {
        const y = i * (floorHeight + gap) + floorHeight / 2;
        const diff = Math.abs(z.temp - z.setpoint);
        const alert = diff > 1.5 ? "critical" : diff > 0.8 ? "warning" : null;
        return (
          <EquipmentPiece
            key={z.id}
            position={[-2.8, y, 0]}
            size={[0.5, 0.4, 0.3]}
            color={z.mode === "cooling" ? "#1890ff" : z.mode === "heating" ? "#fa8c16" : "#555"}
            label={z.name}
            status={z.mode}
            alertLevel={alert}
            data={{
              "Temperature": `${z.temp.toFixed(1)}°C`,
              "Setpoint": `${z.setpoint.toFixed(1)}°C`,
              "Humidity": `${z.humidity.toFixed(0)}%`,
              "Mode": z.mode,
              ...(alert ? { alertMessage: `Temp deviation ${diff > 0 ? "+" : ""}${(z.temp - z.setpoint).toFixed(1)}°C` } : {}),
            }}
            selected={selectedEquipment?.label === z.name}
            onClick={onSelectEquipment}
          />
        );
      })}

      <EnergyParticles count={60} />

      {/* Floating property card for selected equipment */}
      {selectedEquipment && (
        <PropertyPopup equipment={selectedEquipment} onClose={() => onSelectEquipment(null)} />
      )}
    </group>
  );
}

function Scene({ zones, chillers, transformers, selectedEquipment, onSelectEquipment }) {
  return (
    <>
      <ambientLight intensity={0.3} />
      <directionalLight position={[8, 12, 5]} intensity={0.8} castShadow />
      <directionalLight position={[-5, 8, -3]} intensity={0.3} color="#D4A018" />
      <pointLight position={[0, 10, 0]} intensity={0.4} color="#D4A018" />
      <Building zones={zones} chillers={chillers} transformers={transformers} selectedEquipment={selectedEquipment} onSelectEquipment={onSelectEquipment} />
      <Grid
        args={[30, 30]}
        position={[0, -0.5, 0]}
        cellSize={1}
        cellThickness={0.5}
        cellColor="#1a1f2e"
        sectionSize={5}
        sectionThickness={1}
        sectionColor="#2a2f4e"
        fadeDistance={20}
        infiniteGrid
      />
      <OrbitControls
        enablePan
        enableZoom
        enableRotate
        autoRotate
        autoRotateSpeed={0.3}
        minDistance={5}
        maxDistance={25}
        target={[0, 3, 0]}
      />
    </>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   EER Line Chart (Canvas 2D)
   ═══════════════════════════════════════════════════════════════════════════ */
function EERChart({ data }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs || !data || data.length === 0) return;
    const ctx = cvs.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = cvs.clientWidth;
    const h = cvs.clientHeight;
    cvs.width = w * dpr;
    cvs.height = h * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, w, h);

    const pad = { top: 10, right: 10, bottom: 22, left: 30 };
    const cw = w - pad.left - pad.right;
    const ch = h - pad.top - pad.bottom;

    const vals = data.map((d) => d.value);
    const minV = Math.min(...vals) - 0.2;
    const maxV = Math.max(...vals) + 0.2;

    // Grid lines
    ctx.strokeStyle = "rgba(212, 160, 24, 0.1)";
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (ch * i) / 4;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + cw, y);
      ctx.stroke();
    }

    // Y-axis labels
    ctx.fillStyle = T.textSec;
    ctx.font = "9px system-ui";
    ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const v = maxV - ((maxV - minV) * i) / 4;
      const y = pad.top + (ch * i) / 4;
      ctx.fillText(v.toFixed(1), pad.left - 4, y + 3);
    }

    // X-axis labels
    ctx.textAlign = "center";
    for (let i = 0; i < data.length; i += 6) {
      const x = pad.left + (cw * i) / (data.length - 1);
      ctx.fillText(`${data[i].hour}:00`, x, h - 4);
    }

    // Gradient fill
    const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + ch);
    gradient.addColorStop(0, "rgba(212, 160, 24, 0.3)");
    gradient.addColorStop(1, "rgba(212, 160, 24, 0.02)");

    ctx.beginPath();
    data.forEach((d, i) => {
      const x = pad.left + (cw * i) / (data.length - 1);
      const y = pad.top + ch - ((d.value - minV) / (maxV - minV)) * ch;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.lineTo(pad.left + cw, pad.top + ch);
    ctx.lineTo(pad.left, pad.top + ch);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Line
    ctx.beginPath();
    data.forEach((d, i) => {
      const x = pad.left + (cw * i) / (data.length - 1);
      const y = pad.top + ch - ((d.value - minV) / (maxV - minV)) * ch;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = T.accent;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Dots
    data.forEach((d, i) => {
      const x = pad.left + (cw * i) / (data.length - 1);
      const y = pad.top + ch - ((d.value - minV) / (maxV - minV)) * ch;
      ctx.beginPath();
      ctx.arc(x, y, 2, 0, Math.PI * 2);
      ctx.fillStyle = T.accent;
      ctx.fill();
    });
  }, [data]);

  return <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />;
}

/* ═══════════════════════════════════════════════════════════════════════════
   Power Factor Gauge (SVG)
   ═══════════════════════════════════════════════════════════════════════════ */
function PowerFactorGauge({ value }) {
  const size = 120;
  const cx = size / 2;
  const cy = size / 2 + 10;
  const r = 42;
  const startAngle = -210;
  const endAngle = 30;
  const range = endAngle - startAngle;
  const normalized = clamp((value - 0.8) / 0.2, 0, 1);
  const angle = startAngle + normalized * range;

  function polarToCart(angleDeg, radius) {
    const rad = (angleDeg * Math.PI) / 180;
    return { x: cx + radius * Math.cos(rad), y: cy + radius * Math.sin(rad) };
  }

  const arcStart = polarToCart(startAngle, r);
  const arcEnd = polarToCart(angle, r);
  const arcFullEnd = polarToCart(endAngle, r);
  const largeArc = angle - startAngle > 180 ? 1 : 0;

  const gaugeColor = value >= 0.95 ? T.green : value >= 0.90 ? T.accent : T.orange;

  return (
    <svg width={size} height={size - 10} viewBox={`0 0 ${size} ${size - 10}`}>
      {/* Background arc */}
      <path
        d={`M ${arcStart.x} ${arcStart.y} A ${r} ${r} 0 1 1 ${arcFullEnd.x} ${arcFullEnd.y}`}
        fill="none"
        stroke="rgba(212, 160, 24, 0.15)"
        strokeWidth="8"
        strokeLinecap="round"
      />
      {/* Value arc */}
      <path
        d={`M ${arcStart.x} ${arcStart.y} A ${r} ${r} 0 ${largeArc} 1 ${arcEnd.x} ${arcEnd.y}`}
        fill="none"
        stroke={gaugeColor}
        strokeWidth="8"
        strokeLinecap="round"
      />
      {/* Center value */}
      <text x={cx} y={cy - 4} textAnchor="middle" fill={T.text} fontSize="18" fontWeight="700">
        {value.toFixed(2)}
      </text>
      <text x={cx} y={cy + 12} textAnchor="middle" fill={T.textSec} fontSize="9">
        Power Factor
      </text>
      {/* Min / Max labels */}
      <text x={arcStart.x - 2} y={arcStart.y + 14} textAnchor="middle" fill={T.textSec} fontSize="8">
        0.80
      </text>
      <text x={arcFullEnd.x + 2} y={arcFullEnd.y + 14} textAnchor="middle" fill={T.textSec} fontSize="8">
        1.00
      </text>
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Single Line Diagram (SVG)
   ═══════════════════════════════════════════════════════════════════════════ */
function SingleLineDiagram({ breakerStates, powerKw }) {
  const w = 900;
  const h = 90;

  const elements = [
    { x: 40, label: "Grid", type: "source" },
    { x: 140, label: "Main CB", type: "breaker", stateKey: "main" },
    { x: 280, label: "Bus Bar 1", type: "busbar", stateKey: "bus1" },
    { x: 420, label: "Bus Bar 2", type: "busbar", stateKey: "bus2" },
    { x: 560, label: "Dist. 1", type: "breaker", stateKey: "dist1" },
    { x: 660, label: "Dist. 2", type: "breaker", stateKey: "dist2" },
    { x: 760, label: "Dist. 3", type: "breaker", stateKey: "dist3" },
    { x: 860, label: "Loads", type: "load" },
  ];

  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {/* Connection lines */}
      {elements.slice(0, -1).map((el, i) => {
        const next = elements[i + 1];
        const closed = el.stateKey ? breakerStates[el.stateKey] : true;
        return (
          <line
            key={`line-${i}`}
            x1={el.x + 20}
            y1={40}
            x2={next.x - 20}
            y2={40}
            stroke={closed ? T.green : T.red}
            strokeWidth="2"
            strokeDasharray={closed ? "none" : "4,4"}
            opacity={0.7}
          />
        );
      })}

      {/* Flow arrows */}
      {elements.slice(0, -1).map((el, i) => {
        const next = elements[i + 1];
        const mid = (el.x + 20 + next.x - 20) / 2;
        const closed = el.stateKey ? breakerStates[el.stateKey] : true;
        if (!closed) return null;
        return (
          <polygon
            key={`arrow-${i}`}
            points={`${mid - 4},36 ${mid + 4},40 ${mid - 4},44`}
            fill={T.green}
            opacity={0.6}
          />
        );
      })}

      {/* Elements */}
      {elements.map((el) => {
        const closed = el.stateKey ? breakerStates[el.stateKey] : true;
        if (el.type === "source") {
          return (
            <g key={el.label}>
              <circle cx={el.x} cy={40} r={16} fill="none" stroke={T.accent} strokeWidth="2" />
              <text x={el.x} y={43} textAnchor="middle" fill={T.text} fontSize="10" fontWeight="600">
                ~
              </text>
              <text x={el.x} y={70} textAnchor="middle" fill={T.textSec} fontSize="8">
                {el.label}
              </text>
            </g>
          );
        }
        if (el.type === "load") {
          return (
            <g key={el.label}>
              <polygon points={`${el.x - 12},28 ${el.x + 12},28 ${el.x + 8},52 ${el.x - 8},52`} fill="none" stroke={T.accent} strokeWidth="1.5" />
              <text x={el.x} y={43} textAnchor="middle" fill={T.text} fontSize="9">
                {Math.round(powerKw)}
              </text>
              <text x={el.x} y={70} textAnchor="middle" fill={T.textSec} fontSize="8">
                {el.label} (kW)
              </text>
            </g>
          );
        }
        if (el.type === "breaker") {
          return (
            <g key={el.label}>
              <rect x={el.x - 14} y={28} width={28} height={24} rx={4} fill={closed ? "rgba(82,196,26,0.15)" : "rgba(245,34,45,0.15)"} stroke={closed ? T.green : T.red} strokeWidth="1.5" />
              <text x={el.x} y={43} textAnchor="middle" fill={closed ? T.green : T.red} fontSize="9" fontWeight="600">
                {closed ? "ON" : "OFF"}
              </text>
              <text x={el.x} y={70} textAnchor="middle" fill={T.textSec} fontSize="8">
                {el.label}
              </text>
            </g>
          );
        }
        if (el.type === "busbar") {
          return (
            <g key={el.label}>
              <rect x={el.x - 30} y={35} width={60} height={10} rx={2} fill="rgba(212,160,24,0.2)" stroke={T.accent} strokeWidth="1.5" />
              <text x={el.x} y={70} textAnchor="middle" fill={T.textSec} fontSize="8">
                {el.label}
              </text>
            </g>
          );
        }
        return null;
      })}

      {/* Power label */}
      <text x={w / 2} y={16} textAnchor="middle" fill={T.textSec} fontSize="9">
        Active Power Flow: {Math.round(powerKw)} kW
      </text>
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   BEMS Digital Twin — Main Component
   ═══════════════════════════════════════════════════════════════════════════ */
export default function BEMSDigitalTwin({ onClose }) {
  const wsRef = useRef(null);
  const simRef = useRef(null);
  const [state, setState] = useState(createInitialState);
  const [clock, setClock] = useState(new Date());
  const [site, setSite] = useState("Princeps HQ - London");
  const [wsConnected, setWsConnected] = useState(false);
  const [selectedEquipment, setSelectedEquipment] = useState(null);
  const [elementFilter, setElementFilter] = useState("");

  const sites = useMemo(() => [
    "Princeps HQ - London",
    "Birmingham Data Centre",
    "Manchester Campus",
    "Edinburgh Office",
  ], []);

  /* ── Live clock ── */
  useEffect(() => {
    const id = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  /* ── WebSocket / simulated feed ── */
  useEffect(() => {
    let cancelled = false;

    function connectWs() {
      try {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const host = window.location.host;
        const ws = new WebSocket(`${protocol}//${host}/ws/bems`);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!cancelled) setWsConnected(true);
        };

        ws.onmessage = (evt) => {
          try {
            const data = JSON.parse(evt.data);
            if (!cancelled) setState((prev) => ({ ...prev, ...data }));
          } catch { /* ignore parse errors */ }
        };

        ws.onerror = () => {
          ws.close();
        };

        ws.onclose = () => {
          if (!cancelled) {
            setWsConnected(false);
            startSimulation();
          }
        };
      } catch {
        startSimulation();
      }
    }

    function startSimulation() {
      if (simRef.current) return;
      simRef.current = setInterval(() => {
        if (cancelled) return;
        setState((prev) => {
          const newPower = randomWalk(prev.powerKw, 20, 350, 550);
          const newPf = randomWalk(prev.powerFactor, 0.01, 0.88, 0.99);
          const newEer = randomWalk(prev.eer, 0.15, 2.8, 4.8);

          const newChillers = prev.chillers.map((ch) => ({
            ...ch,
            loadPct: ch.running ? randomWalk(ch.loadPct, 3, 30, 95) : 0,
            supplyTemp: ch.running ? randomWalk(ch.supplyTemp, 0.2, 4.5, 8.0) : 0,
            returnTemp: ch.running ? randomWalk(ch.returnTemp, 0.3, 9, 14) : 0,
            running: Math.random() > 0.02 ? ch.running : !ch.running,
          }));

          const newTransformers = prev.transformers.map((tx) => ({
            ...tx,
            loadPct: randomWalk(tx.loadPct, 2, 20, 85),
            status: tx.loadPct > 75 ? "warning" : "normal",
          }));

          const newZones = prev.zones.map((z) => ({
            ...z,
            temp: randomWalk(z.temp, 0.3, z.setpoint - 3, z.setpoint + 4),
            humidity: randomWalk(z.humidity, 1, 30, 65),
          }));

          const hourIdx = new Date().getHours();
          const newEerHistory = [...prev.eerHistory];
          newEerHistory[hourIdx] = { hour: hourIdx, value: newEer };

          return {
            ...prev,
            powerKw: newPower,
            powerFactor: newPf,
            eer: newEer,
            todayKwh: prev.todayKwh + newPower * (2 / 3600),
            monthKwh: prev.monthKwh + newPower * (2 / 3600),
            carbonKg: prev.carbonKg + newPower * 0.000233 * 2,
            coolingTodayGj: prev.coolingTodayGj + 0.001,
            chillers: newChillers,
            transformers: newTransformers,
            zones: newZones,
            eerHistory: newEerHistory,
          };
        });
      }, 2000);
    }

    connectWs();

    return () => {
      cancelled = true;
      if (wsRef.current) wsRef.current.close();
      if (simRef.current) clearInterval(simRef.current);
      simRef.current = null;
    };
  }, []);

  const alertCount = useMemo(
    () => state.alarms.filter((a) => !a.acked).length,
    [state.alarms]
  );

  /* ── Inline styles ── */
  const S = useMemo(() => ({
    overlay: {
      position: "fixed", inset: 0, zIndex: 9999,
      background: T.bg, display: "flex", flexDirection: "column",
      fontFamily: "'Roboto', 'Segoe UI', system-ui, sans-serif",
      color: T.text, overflow: "hidden",
    },
    topBar: {
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "8px 16px", background: T.panel, borderBottom: T.border,
      height: 48, flexShrink: 0,
    },
    topLeft: { display: "flex", alignItems: "center", gap: 16 },
    topRight: { display: "flex", alignItems: "center", gap: 16 },
    title: { fontSize: 16, fontWeight: 700, color: T.text, letterSpacing: "0.5px" },
    titleAccent: { color: T.accent },
    closeBtn: {
      background: "rgba(212, 160, 24, 0.1)", border: T.border, borderRadius: 6,
      color: T.text, padding: "4px 12px", cursor: "pointer", fontSize: 13,
      transition: "all 0.2s",
    },
    select: {
      background: "rgba(212, 160, 24, 0.08)", border: T.border, borderRadius: 6,
      color: T.text, padding: "4px 10px", fontSize: 12, outline: "none",
      cursor: "pointer",
    },
    clockText: { fontSize: 12, color: T.textSec },
    alertBell: {
      position: "relative", cursor: "pointer", fontSize: 18, color: T.textSec,
      background: "none", border: "none", padding: 4,
    },
    alertBadge: {
      position: "absolute", top: -2, right: -4, background: T.red,
      color: "#fff", fontSize: 9, fontWeight: 700, borderRadius: 8,
      padding: "1px 4px", lineHeight: "12px",
    },
    body: { display: "flex", flex: 1, overflow: "hidden" },
    leftPanel: {
      width: "25%", padding: 12, overflowY: "auto", background: T.panel,
      borderRight: T.border, display: "flex", flexDirection: "column", gap: 10,
    },
    centerPanel: { width: "50%", position: "relative" },
    rightPanel: {
      width: "25%", padding: 12, overflowY: "auto", background: T.panel,
      borderLeft: T.border, display: "flex", flexDirection: "column", gap: 10,
    },
    bottomStrip: {
      height: 120, background: T.panel, borderTop: T.border,
      padding: "4px 16px", flexShrink: 0,
    },
    card: {
      background: "rgba(212, 160, 24, 0.04)", border: T.border, borderRadius: 8,
      padding: 12,
    },
    cardTitle: {
      fontSize: 11, fontWeight: 600, color: T.textSec, textTransform: "uppercase",
      letterSpacing: "0.8px", marginBottom: 8,
    },
    kpiRow: {
      display: "flex", justifyContent: "space-between", alignItems: "baseline",
      padding: "3px 0",
    },
    kpiLabel: { fontSize: 11, color: T.textSec },
    kpiValue: { fontSize: 14, fontWeight: 600, color: T.text },
    kpiValueLarge: { fontSize: 22, fontWeight: 700, color: T.accent },
    badge: (running) => ({
      display: "inline-block", padding: "2px 8px", borderRadius: 4,
      fontSize: 10, fontWeight: 600,
      background: running ? "rgba(82,196,26,0.15)" : "rgba(245,34,45,0.15)",
      color: running ? T.green : T.red,
      border: `1px solid ${running ? T.green : T.red}`,
    }),
    progressBar: (pct, color) => ({
      height: 6, borderRadius: 3, background: "rgba(212,160,24,0.1)",
      position: "relative", marginTop: 4,
    }),
    progressFill: (pct, color) => ({
      height: "100%", borderRadius: 3, width: `${clamp(pct, 0, 100)}%`,
      background: color || T.accent, transition: "width 0.5s ease",
    }),
    zoneGrid: {
      display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6,
    },
    zoneCard: {
      background: "rgba(212,160,24,0.04)", border: T.border, borderRadius: 6,
      padding: 8, fontSize: 11,
    },
    alarmItem: (severity) => ({
      display: "flex", gap: 8, alignItems: "flex-start", padding: "6px 0",
      borderBottom: "1px solid rgba(212,160,24,0.08)",
    }),
    alarmDot: (severity) => ({
      width: 6, height: 6, borderRadius: 3, marginTop: 5, flexShrink: 0,
      background: severity === "critical" ? T.red : severity === "warning" ? T.orange : T.blue,
    }),
    alarmText: { fontSize: 11, color: T.textSec, lineHeight: "16px" },
    alarmTime: { fontSize: 10, color: "rgba(139,143,163,0.6)" },
    wsIndicator: {
      width: 8, height: 8, borderRadius: 4,
      background: wsConnected ? T.green : T.orange,
      display: "inline-block",
    },
    liveLabel: { fontSize: 10, color: T.textSec, marginLeft: 4 },
  }), [wsConnected]);

  return (
    <div style={S.overlay}>
      {/* ── Top Bar ────────────────────────────────────────────────────── */}
      <div style={S.topBar}>
        <div style={S.topLeft}>
          <span style={S.title}>
            <span style={S.titleAccent}>BEMS</span> Digital Twin
          </span>
          <select
            style={S.select}
            value={site}
            onChange={(e) => setSite(e.target.value)}
          >
            {sites.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <span style={{ display: "flex", alignItems: "center" }}>
            <span style={S.wsIndicator} />
            <span style={S.liveLabel}>{wsConnected ? "Live" : "Simulated"}</span>
          </span>
          <div style={{ display: "flex", gap: 0, borderRadius: 4, overflow: "hidden", border: "1px solid rgba(212,160,24,0.3)" }}>
            <button style={{ padding: "3px 12px", fontSize: 11, background: "rgba(212,160,24,0.15)", color: "#1A1D23", border: "none", cursor: "pointer" }}>Build</button>
            <button style={{ padding: "3px 12px", fontSize: 11, background: "rgba(212,160,24,0.4)", color: "#fff", border: "none", cursor: "pointer", fontWeight: 600 }}>View</button>
          </div>
        </div>
        <div style={S.topRight}>
          <span style={S.clockText}>{formatTime(clock)}</span>
          <span style={S.clockText}>{formatDate(clock)}</span>
          <button style={S.alertBell} title="Alerts">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
            {alertCount > 0 && <span style={S.alertBadge}>{alertCount}</span>}
          </button>
          <button
            style={S.closeBtn}
            onClick={onClose}
            onMouseEnter={(e) => { e.target.style.background = "rgba(212,160,24,0.25)"; }}
            onMouseLeave={(e) => { e.target.style.background = "rgba(212,160,24,0.1)"; }}
          >
            Close
          </button>
        </div>
      </div>

      {/* ── Body ───────────────────────────────────────────────────────── */}
      <div style={S.body}>
        {/* ── Left Panel — Elements + Energy KPIs ── */}
        <div style={S.leftPanel}>
          {/* Elements Tree (Azure DT style) */}
          <div style={{ ...S.card, maxHeight: 220, display: "flex", flexDirection: "column" }}>
            <div style={{ ...S.cardTitle, display: "flex", alignItems: "center", gap: 6 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/></svg>
              Elements
            </div>
            <input
              type="text"
              placeholder="Type to filter elements or alerts"
              value={elementFilter}
              onChange={(e) => setElementFilter(e.target.value)}
              style={{
                background: "rgba(212,160,24,0.06)", border: "1px solid rgba(212,160,24,0.15)",
                borderRadius: 4, padding: "5px 8px", fontSize: 11, color: "#1A1D23",
                outline: "none", marginBottom: 6, width: "100%",
              }}
            />
            <div style={{ overflowY: "auto", flex: 1 }}>
              {/* Chillers */}
              {state.chillers.filter(ch => !elementFilter || ch.id.toLowerCase().includes(elementFilter.toLowerCase())).map(ch => {
                const hasAlert = ch.supplyTemp > 7.5;
                return (
                  <div
                    key={ch.id}
                    onClick={() => setSelectedEquipment({ label: ch.id, status: ch.running ? "Run" : "Stop", data: { Load: `${ch.loadPct.toFixed(0)}%`, "Supply Temp": `${ch.supplyTemp.toFixed(1)}°C` }, position: [0, 7, -2.5] })}
                    style={{
                      padding: "4px 6px", cursor: "pointer", borderRadius: 4, fontSize: 11,
                      display: "flex", alignItems: "center", gap: 6,
                      background: selectedEquipment?.label === ch.id ? "rgba(212,160,24,0.15)" : "transparent",
                    }}
                  >
                    {hasAlert && <span style={{ width: 6, height: 14, borderRadius: 2, background: "#fa8c16", flexShrink: 0 }} />}
                    <span style={{ color: "#1A1D23" }}>{ch.id}</span>
                    <span style={{ color: ch.running ? "#52c41a" : "#f5222d", fontSize: 10, marginLeft: "auto" }}>{ch.running ? "RUN" : "STOP"}</span>
                  </div>
                );
              })}
              {state.chillers.some(ch => ch.supplyTemp > 7.5) && (
                <div style={{ padding: "2px 6px 2px 18px", fontSize: 10, color: "#fa8c16" }}>
                  ⚠ Supply temp high
                </div>
              )}
              {/* Transformers */}
              {state.transformers.filter(tx => !elementFilter || tx.id.toLowerCase().includes(elementFilter.toLowerCase())).map(tx => (
                <div
                  key={tx.id}
                  onClick={() => setSelectedEquipment({ label: tx.id, status: `${tx.loadPct.toFixed(0)}%`, data: { Load: `${tx.loadPct.toFixed(0)}%`, Rating: `${tx.ratingKva} kVA` }, position: [3.5, 0.5, 0] })}
                  style={{
                    padding: "4px 6px", cursor: "pointer", borderRadius: 4, fontSize: 11,
                    display: "flex", alignItems: "center", gap: 6,
                    background: selectedEquipment?.label === tx.id ? "rgba(212,160,24,0.15)" : "transparent",
                  }}
                >
                  {tx.loadPct > 80 && <span style={{ width: 6, height: 14, borderRadius: 2, background: "#fa8c16", flexShrink: 0 }} />}
                  <span style={{ color: "#1A1D23" }}>{tx.id}</span>
                  <span style={{ color: "#4B5563", fontSize: 10, marginLeft: "auto" }}>{tx.loadPct.toFixed(0)}%</span>
                </div>
              ))}
              {/* Zones */}
              {state.zones.filter(z => !elementFilter || z.name.toLowerCase().includes(elementFilter.toLowerCase())).map(z => {
                const diff = Math.abs(z.temp - z.setpoint);
                const hasAlert = diff > 1.0;
                return (
                  <div
                    key={z.id}
                    onClick={() => setSelectedEquipment({ label: z.name, status: z.mode, data: { Temp: `${z.temp.toFixed(1)}°C`, Setpoint: `${z.setpoint.toFixed(1)}°C` }, position: [-2.8, 2, 0] })}
                    style={{
                      padding: "4px 6px", cursor: "pointer", borderRadius: 4, fontSize: 11,
                      display: "flex", alignItems: "center", gap: 6,
                      background: selectedEquipment?.label === z.name ? "rgba(212,160,24,0.15)" : "transparent",
                    }}
                  >
                    {hasAlert && <span style={{ width: 6, height: 14, borderRadius: 2, background: diff > 1.5 ? "#f5222d" : "#fa8c16", flexShrink: 0 }} />}
                    <span style={{ color: "#1A1D23" }}>{z.name}</span>
                    <span style={{ color: "#4B5563", fontSize: 10, marginLeft: "auto" }}>{z.temp.toFixed(1)}°C</span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Live Power */}
          <div style={S.card}>
            <div style={S.cardTitle}>Live Power Demand</div>
            <div style={{ textAlign: "center", padding: "4px 0" }}>
              <span style={S.kpiValueLarge}>{fmtNum(state.powerKw, 0)}</span>
              <span style={{ fontSize: 13, color: T.textSec, marginLeft: 4 }}>kW</span>
            </div>
          </div>

          {/* Energy Consumption */}
          <div style={S.card}>
            <div style={S.cardTitle}>Energy Consumption</div>
            <div style={S.kpiRow}>
              <span style={S.kpiLabel}>Today</span>
              <span style={S.kpiValue}>{fmtNum(state.todayKwh, 0)} kWh</span>
            </div>
            <div style={S.kpiRow}>
              <span style={S.kpiLabel}>This Month</span>
              <span style={S.kpiValue}>{fmtNum(state.monthKwh, 0)} kWh</span>
            </div>
            <div style={S.kpiRow}>
              <span style={S.kpiLabel}>This Year</span>
              <span style={S.kpiValue}>{fmtNum(state.yearKwh, 0)} kWh</span>
            </div>
          </div>

          {/* Cooling Capacity */}
          <div style={S.card}>
            <div style={S.cardTitle}>Cooling Capacity</div>
            <div style={S.kpiRow}>
              <span style={S.kpiLabel}>Today</span>
              <span style={S.kpiValue}>{fmtNum(state.coolingTodayGj, 1)} GJ</span>
            </div>
            <div style={S.kpiRow}>
              <span style={S.kpiLabel}>This Month</span>
              <span style={S.kpiValue}>{fmtNum(state.coolingMonthGj, 0)} GJ</span>
            </div>
            <div style={S.kpiRow}>
              <span style={S.kpiLabel}>This Year</span>
              <span style={S.kpiValue}>{fmtNum(state.coolingYearGj, 0)} GJ</span>
            </div>
          </div>

          {/* EER Chart */}
          <div style={{ ...S.card, height: 140 }}>
            <div style={S.cardTitle}>Energy Efficiency Ratio (24h)</div>
            <div style={{ height: 100 }}>
              <EERChart data={state.eerHistory} />
            </div>
          </div>

          {/* Power Factor Gauge */}
          <div style={{ ...S.card, display: "flex", flexDirection: "column", alignItems: "center" }}>
            <div style={{ ...S.cardTitle, alignSelf: "flex-start" }}>Power Factor</div>
            <PowerFactorGauge value={state.powerFactor} />
          </div>

          {/* Carbon Emissions */}
          <div style={S.card}>
            <div style={S.cardTitle}>Carbon Emissions</div>
            <div style={{ textAlign: "center", padding: "4px 0" }}>
              <span style={{ fontSize: 20, fontWeight: 700, color: T.orange }}>{fmtNum(state.carbonKg, 0)}</span>
              <span style={{ fontSize: 12, color: T.textSec, marginLeft: 4 }}>kg CO2 today</span>
            </div>
          </div>
        </div>

        {/* ── Center — 3D Building ── */}
        <div style={S.centerPanel}>
          <Canvas
            shadows
            camera={{ position: [10, 8, 10], fov: 45 }}
            style={{ background: T.bg }}
            gl={{ antialias: true, alpha: false }}
          >
            <Scene
              zones={state.zones}
              chillers={state.chillers}
              transformers={state.transformers}
              selectedEquipment={selectedEquipment}
              onSelectEquipment={setSelectedEquipment}
            />
          </Canvas>
          {/* 3D label overlay */}
          <div style={{
            position: "absolute", bottom: 12, left: 12,
            background: "rgba(255,255,255,0.92)", border: T.border,
            borderRadius: 8, padding: "8px 14px", fontSize: 11, color: T.textSec,
          }}>
            <span style={{ color: T.accent, fontWeight: 600 }}>3D Building Model</span>
            <span style={{ margin: "0 8px", opacity: 0.3 }}>|</span>
            Floor colors = energy consumption intensity
            <span style={{ margin: "0 8px", opacity: 0.3 }}>|</span>
            Drag to rotate, scroll to zoom
          </div>
        </div>

        {/* ── Right Panel — Equipment Status ── */}
        <div style={S.rightPanel}>
          {/* Chiller Plant Status */}
          <div style={S.card}>
            <div style={S.cardTitle}>Chiller Plant Status</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {state.chillers.map((ch) => (
                <div key={ch.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: T.text, width: 42 }}>{ch.id}</span>
                  <span style={S.badge(ch.running)}>{ch.running ? "RUN" : "STOP"}</span>
                  <span style={{ fontSize: 10, color: T.textSec, width: 50, textAlign: "right" }}>
                    {ch.running ? `${ch.loadPct.toFixed(0)}%` : "--"}
                  </span>
                  <span style={{ fontSize: 10, color: T.textSec, width: 55, textAlign: "right" }}>
                    {ch.running ? `${ch.supplyTemp.toFixed(1)}C` : "--"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Transformer Status */}
          <div style={S.card}>
            <div style={S.cardTitle}>Transformer Status</div>
            {state.transformers.map((tx) => (
              <div key={tx.id} style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>{tx.id}</span>
                  <span style={{ fontSize: 11, color: T.textSec }}>{tx.ratingKva} kVA</span>
                  <span style={{
                    fontSize: 12, fontWeight: 600,
                    color: tx.loadPct > 75 ? T.orange : tx.loadPct > 90 ? T.red : T.green,
                  }}>
                    {tx.loadPct.toFixed(0)}%
                  </span>
                </div>
                <div style={S.progressBar(tx.loadPct)}>
                  <div style={S.progressFill(
                    tx.loadPct,
                    tx.loadPct > 80 ? T.orange : tx.loadPct > 90 ? T.red : T.accent
                  )} />
                </div>
              </div>
            ))}
          </div>

          {/* HVAC Zones */}
          <div style={S.card}>
            <div style={S.cardTitle}>HVAC Zones</div>
            <div style={S.zoneGrid}>
              {state.zones.map((z) => {
                const diff = z.temp - z.setpoint;
                const tempColor = Math.abs(diff) > 1.5 ? T.red : Math.abs(diff) > 0.8 ? T.orange : T.green;
                return (
                  <div key={z.id} style={S.zoneCard}>
                    <div style={{ fontWeight: 600, color: T.text, marginBottom: 3, fontSize: 11 }}>{z.name}</div>
                    <div style={{ display: "flex", justifyContent: "space-between" }}>
                      <span style={{ color: tempColor, fontWeight: 600 }}>{z.temp.toFixed(1)}C</span>
                      <span style={{ color: T.textSec }}>SP: {z.setpoint.toFixed(1)}</span>
                    </div>
                    <div style={{ fontSize: 10, color: T.textSec, marginTop: 2 }}>
                      {z.humidity.toFixed(0)}% RH
                      <span style={{
                        marginLeft: 6, fontSize: 9, padding: "1px 4px", borderRadius: 3,
                        background: z.mode === "cooling" ? "rgba(24,144,255,0.15)" : z.mode === "heating" ? "rgba(250,140,22,0.15)" : "rgba(212,160,24,0.08)",
                        color: z.mode === "cooling" ? T.blue : z.mode === "heating" ? T.orange : T.textSec,
                      }}>
                        {z.mode}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Recent Alarms */}
          <div style={{ ...S.card, flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            <div style={S.cardTitle}>Recent Alarms</div>
            <div style={{ flex: 1, overflowY: "auto" }}>
              {state.alarms.map((alarm) => (
                <div key={alarm.id} style={S.alarmItem(alarm.severity)}>
                  <span style={S.alarmDot(alarm.severity)} />
                  <div>
                    <div style={S.alarmText}>{alarm.message}</div>
                    <div style={S.alarmTime}>
                      {alarm.time}
                      {alarm.acked && (
                        <span style={{ marginLeft: 6, color: T.green, fontSize: 9 }}>ACK</span>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Bottom Strip — Single Line Diagram ── */}
      <div style={S.bottomStrip}>
        <SingleLineDiagram breakerStates={state.breakerStates} powerKw={state.powerKw} />
      </div>
    </div>
  );
}

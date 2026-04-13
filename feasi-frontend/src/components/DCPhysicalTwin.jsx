/**
 * DCPhysicalTwin — full physical architecture digital twin for a data centre.
 *
 * Models the canonical Uptime Institute Tier III / IV DC architecture
 * referenced in the IEA Data Centre diagram + Princeps NESO098 methodology:
 *
 *   Grid connection
 *     ↓ 132/33/11 kV utility feed (BCA boundary)
 *   Main substation (N+1 transformers)
 *     ↓ 11 kV medium-voltage distribution
 *   ATS (automatic transfer switch)
 *     ↓ chooses between utility and genset
 *   Diesel generators (2N redundancy)
 *   UPS (battery bridging, N+1)
 *     ↓ 400V LV facility distribution
 *   PDUs (rack-level)
 *     ↓
 *   Server racks (compute load)
 *
 *   Cooling stack:
 *     Cooling towers → chillers → CHW distribution → CRAH / CRAC
 *     → hot aisle / cold aisle → direct-to-chip liquid cooling
 *
 *   Fire + BMS + physical security overlays
 *
 * Real-time state derived from the existing dc_cooling_analyser, dc_cfe_scorer,
 * and project_finance modules. Full 3D rendering via @react-three/fiber (already
 * in the stack).
 */
import React, { useMemo, useRef, useState, useCallback } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Text, Html } from "@react-three/drei";
import * as THREE from "three";

const C = {
  bg:         "#0a0e18",
  grid:       "#1e293b",
  text:       "#e2e8f0",
  textDim:    "#94a3b8",
  gold:       "#f5b731",
  utility:    "#64748b",
  transformer:"#0891b2",
  ats:        "#7c3aed",
  genset:     "#dc2626",
  ups:        "#f59e0b",
  pdu:        "#14b8a6",
  rack:       "#10b981",
  rackHot:    "#ef4444",
  chiller:    "#06b6d4",
  crah:       "#3b82f6",
  pipe:       "#475569",
};


/* ─────────── Component metadata ─────────── */
const COMPONENTS = {
  utility: {
    label: "Utility feed (BCA boundary)",
    description: "132 kV grid connection via Bilateral Connection Agreement. Princeps tracks via dc_hyperscaler optioneer.",
    typical_voltage: "132 kV / 33 kV",
  },
  main_sub: {
    label: "Main substation (N+1)",
    description: "Step-down from transmission voltage to 11 kV medium voltage. Redundant transformers per Uptime Tier III/IV.",
    typical_voltage: "132/11 kV",
  },
  ats: {
    label: "Automatic Transfer Switch",
    description: "Switches between utility and generator power automatically on loss of supply.",
    typical_voltage: "11 kV / 400 V",
  },
  genset: {
    label: "Diesel generators (2N)",
    description: "Backup generation — typically 2×100% redundancy for Tier IV. Fuel storage for 72+ hours.",
    typical_voltage: "11 kV",
  },
  ups: {
    label: "UPS (battery bridging)",
    description: "15-30 minutes of battery bridging between utility loss and genset start. Lithium-ion or VRLA.",
    typical_voltage: "400 V DC/AC",
  },
  pdu: {
    label: "PDU (rack-level distribution)",
    description: "400 V 3-phase to rack. Metering per-outlet. Dual-cord to each rack for 2N.",
    typical_voltage: "400 V",
  },
  rack: {
    label: "Server rack",
    description: "Typically 10-40 kW per rack for air-cooled, 50-150 kW for direct-to-chip liquid cooling.",
    typical_voltage: "400 V / 48 V DC",
  },
  chiller: {
    label: "Chiller plant",
    description: "Water-cooled or air-cooled chillers producing chilled water (CHW) at ~7°C supply.",
    typical_voltage: "400 V",
  },
  cooling_tower: {
    label: "Cooling tower",
    description: "Evaporative heat rejection to atmosphere. Water-intensive — Princeps tracks in dc_water_stress.",
    typical_voltage: "400 V",
  },
  crah: {
    label: "CRAH / CRAC unit",
    description: "Computer Room Air Handler. Delivers cold air to cold aisles, returns hot air from hot aisles.",
    typical_voltage: "400 V",
  },
};


/* ─────────── Reusable primitive: labelled 3D component ─────────── */
function Component3D({ position, size, colour, label, kind, onClick, selected, emissive = 0.15 }) {
  const ref = useRef();
  useFrame((state) => {
    if (ref.current && selected) {
      ref.current.rotation.y = Math.sin(state.clock.elapsedTime * 2) * 0.03;
    }
  });
  return (
    <group position={position}>
      <mesh
        ref={ref}
        onClick={(e) => { e.stopPropagation(); onClick?.(kind); }}
        onPointerOver={(e) => { e.stopPropagation(); document.body.style.cursor = "pointer"; }}
        onPointerOut={() => { document.body.style.cursor = "default"; }}
      >
        <boxGeometry args={size} />
        <meshStandardMaterial
          color={colour}
          emissive={colour}
          emissiveIntensity={selected ? 0.6 : emissive}
          metalness={0.35}
          roughness={0.55}
        />
      </mesh>
      <Text
        position={[0, size[1] / 2 + 0.3, 0]}
        fontSize={0.22}
        color={selected ? C.gold : C.text}
        anchorX="center"
        anchorY="bottom"
      >
        {label}
      </Text>
    </group>
  );
}


/* ─────────── Power flow line (animated dashed segment) ─────────── */
function PowerLine({ start, end, colour = C.gold, active = true }) {
  const ref = useRef();
  useFrame((state) => {
    if (ref.current && active) {
      const mat = ref.current.material;
      if (mat) mat.dashOffset = -state.clock.elapsedTime * 2;
    }
  });
  const points = useMemo(() => [
    new THREE.Vector3(...start),
    new THREE.Vector3(...end),
  ], [start, end]);
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry().setFromPoints(points);
    g.computeBoundingSphere();
    return g;
  }, [points]);

  return (
    <line ref={ref} geometry={geometry}>
      <lineBasicMaterial color={colour} linewidth={2} />
    </line>
  );
}


/* ─────────── Server rack grid ─────────── */
function RackGrid({ rows = 4, cols = 6, spacing = 1.0, hotAisleIndices = [1, 3] }) {
  const racks = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const inHotAisle = hotAisleIndices.includes(r);
      racks.push(
        <group key={`${r}-${c}`} position={[c * spacing - (cols - 1) * spacing / 2, 0, r * spacing - (rows - 1) * spacing / 2]}>
          <mesh>
            <boxGeometry args={[0.5, 1.6, 0.35]} />
            <meshStandardMaterial color={inHotAisle ? C.rackHot : C.rack} emissiveIntensity={0.2} emissive={inHotAisle ? C.rackHot : C.rack} />
          </mesh>
          {/* rack LEDs */}
          {[0, 1, 2, 3, 4].map(i => (
            <mesh key={i} position={[0, 0.6 - i * 0.3, 0.18]}>
              <boxGeometry args={[0.35, 0.04, 0.01]} />
              <meshStandardMaterial color="#00ff88" emissive="#00ff88" emissiveIntensity={0.8} />
            </mesh>
          ))}
        </group>
      );
    }
  }
  return <group>{racks}</group>;
}


/* ─────────── Main scene ─────────── */
function DCScene({ selected, setSelected }) {
  // Positions are arranged along a left-to-right power flow:
  //   Utility → Main Sub → ATS → (Gensets || UPS) → PDUs → Racks
  // And cooling: Cooling Towers → Chillers → CRAH → Racks
  return (
    <group>
      {/* ── Lighting ── */}
      <ambientLight intensity={0.35} />
      <pointLight position={[10, 10, 10]} intensity={1.1} />
      <directionalLight position={[-5, 8, 5]} intensity={0.4} />

      {/* ── Ground grid ── */}
      <gridHelper args={[30, 30, C.grid, C.grid]} position={[0, -0.001, 0]} />

      {/* ── POWER ROW (back of hall) ── */}
      <Component3D position={[-12, 1.0, -6]} size={[1.5, 2.0, 1.5]} colour={C.utility}
                   label="Utility 132 kV" kind="utility" onClick={setSelected} selected={selected === "utility"} />
      <Component3D position={[-9, 0.8, -6]} size={[1.5, 1.6, 1.5]} colour={C.transformer}
                   label="Main Sub 132/11 kV" kind="main_sub" onClick={setSelected} selected={selected === "main_sub"} />
      <Component3D position={[-6, 0.7, -6]} size={[1.3, 1.4, 1.3]} colour={C.ats}
                   label="ATS" kind="ats" onClick={setSelected} selected={selected === "ats"} />
      <Component3D position={[-3, 0.7, -8]} size={[1.4, 1.4, 1.4]} colour={C.genset}
                   label="Gensets 2×N" kind="genset" onClick={setSelected} selected={selected === "genset"} />
      <Component3D position={[-3, 0.5, -4]} size={[1.4, 1.0, 1.4]} colour={C.ups}
                   label="UPS battery" kind="ups" onClick={setSelected} selected={selected === "ups"} />
      <Component3D position={[0, 0.35, -6]} size={[1.1, 0.7, 1.1]} colour={C.pdu}
                   label="PDU" kind="pdu" onClick={setSelected} selected={selected === "pdu"} />

      {/* ── POWER FLOW LINES ── */}
      <PowerLine start={[-11.25, 1.0, -6]} end={[-9.75, 1.0, -6]} />
      <PowerLine start={[-8.25, 1.0, -6]} end={[-6.75, 1.0, -6]} />
      <PowerLine start={[-5.25, 1.0, -6]} end={[-3.75, 1.0, -8]} colour={C.genset} />
      <PowerLine start={[-5.25, 1.0, -6]} end={[-3.75, 1.0, -4]} colour={C.ups} />
      <PowerLine start={[-2.25, 0.7, -4]} end={[-0.55, 0.7, -6]} colour={C.ups} />
      <PowerLine start={[-2.25, 0.7, -8]} end={[-0.55, 0.7, -6]} colour={C.genset} />

      {/* ── SERVER HALL (centre) ── */}
      <group position={[5, 0.8, 0]}>
        <RackGrid />
        <Text position={[0, 2.4, 0]} fontSize={0.3} color={C.text} anchorX="center">
          Server Hall · 4×6 racks
        </Text>
      </group>

      {/* ── COOLING ROW (front of hall) ── */}
      <Component3D position={[-3, 0.7, 6]} size={[1.3, 1.4, 1.3]} colour={C.chiller}
                   label="Chiller Plant" kind="chiller" onClick={setSelected} selected={selected === "chiller"} />
      <Component3D position={[-6, 0.9, 7]} size={[1.4, 1.8, 1.4]} colour={C.cooling_tower}
                   label="Cooling Tower" kind="cooling_tower" onClick={setSelected} selected={selected === "cooling_tower"} />
      <Component3D position={[1, 0.5, 6]} size={[1.1, 1.0, 1.1]} colour={C.crah}
                   label="CRAH / CRAC" kind="crah" onClick={setSelected} selected={selected === "crah"} />

      {/* ── COOLING FLOW LINES (dashed) ── */}
      <PowerLine start={[-5.25, 0.9, 7]} end={[-3.75, 0.9, 6]} colour={C.chiller} />
      <PowerLine start={[-2.25, 0.7, 6]} end={[-0.5, 0.7, 6]} colour={C.chiller} />
      <PowerLine start={[1.55, 0.5, 6]} end={[3.5, 0.5, 1]} colour={C.chiller} />

      {/* ── FLOOR LABELS ── */}
      <Text position={[-6, 0.01, -9]} fontSize={0.25} color={C.textDim} anchorX="center" rotation={[-Math.PI / 2, 0, 0]}>
        POWER ROW
      </Text>
      <Text position={[-3, 0.01, 9]} fontSize={0.25} color={C.textDim} anchorX="center" rotation={[-Math.PI / 2, 0, 0]}>
        COOLING ROW
      </Text>
    </group>
  );
}


/* ─────────── Info sidebar ─────────── */
const PANEL = {
  root: {
    position: "absolute", top: 20, right: 20, width: 340,
    background: "rgba(11, 14, 19, 0.94)", color: C.text,
    border: `1px solid rgba(255,255,255,0.08)`,
    borderRadius: 10, padding: 20,
    fontFamily: "'DM Sans', sans-serif",
    boxShadow: "0 4px 18px rgba(0,0,0,0.6)",
  },
  title: { fontSize: 11, letterSpacing: 0.7, color: C.gold, textTransform: "uppercase", fontWeight: 700 },
  h2: { fontSize: 15, fontWeight: 800, margin: "6px 0 10px" },
  desc: { fontSize: 11, color: C.textDim, lineHeight: 1.55 },
  row: { display: "flex", justifyContent: "space-between", padding: "6px 0",
         borderBottom: "1px dashed rgba(255,255,255,0.08)", fontSize: 11 },
  label: { color: C.textDim },
  val: { fontFamily: "'JetBrains Mono', monospace", fontWeight: 600 },
  close: { position: "absolute", top: 8, right: 8, background: "none", border: "none",
           color: C.textDim, cursor: "pointer", fontSize: 18 },
};

function InfoPanel({ component, onClose, facility }) {
  if (!component) return null;
  const meta = COMPONENTS[component];
  if (!meta) return null;
  return (
    <div style={PANEL.root}>
      <button style={PANEL.close} onClick={onClose}>×</button>
      <div style={PANEL.title}>Component</div>
      <div style={PANEL.h2}>{meta.label}</div>
      <div style={PANEL.desc}>{meta.description}</div>
      <div style={{ marginTop: 14 }}>
        <div style={PANEL.row}><span style={PANEL.label}>Typical voltage</span><span style={PANEL.val}>{meta.typical_voltage}</span></div>
        {component === "rack" && (
          <>
            <div style={PANEL.row}><span style={PANEL.label}>Rack count</span><span style={PANEL.val}>{facility.rack_count}</span></div>
            <div style={PANEL.row}><span style={PANEL.label}>Per-rack kW</span><span style={PANEL.val}>{facility.rack_kw}</span></div>
          </>
        )}
        {component === "chiller" && (
          <div style={PANEL.row}><span style={PANEL.label}>CHW supply</span><span style={PANEL.val}>7 °C</span></div>
        )}
        {component === "genset" && (
          <div style={PANEL.row}><span style={PANEL.label}>Fuel storage</span><span style={PANEL.val}>72 hrs</span></div>
        )}
      </div>
    </div>
  );
}


/* ─────────── KPI strip (top) ─────────── */
function KPIStrip({ facility }) {
  return (
    <div style={{
      position: "absolute", top: 20, left: 20,
      display: "flex", gap: 22, alignItems: "center",
      background: "rgba(11, 14, 19, 0.94)", color: C.text,
      border: "1px solid rgba(255,255,255,0.08)",
      padding: "12px 22px", borderRadius: 10,
      fontFamily: "'DM Sans', sans-serif",
      boxShadow: "0 4px 18px rgba(0,0,0,0.6)",
    }}>
      <Kpi label="IT Load" value={facility.it_mw + " MW"} colour="#10b981" />
      <Kpi label="Total facility" value={facility.total_mw + " MW"} colour="#3b82f6" />
      <Kpi label="PUE" value={facility.pue.toFixed(2)} colour="#f59e0b" />
      <Kpi label="Uptime Tier" value={"Tier " + facility.tier} colour="#a855f7" />
      <Kpi label="CFE 24/7" value={facility.cfe_pct + "%"} colour="#10b981" />
      <Kpi label="Water m³/yr" value={facility.water_m3_year.toLocaleString()} colour="#06b6d4" />
    </div>
  );
}

function Kpi({ label, value, colour }) {
  return (
    <div>
      <div style={{ fontSize: 15, fontWeight: 800, color, fontFamily: "'JetBrains Mono', monospace" }}>{value}</div>
      <div style={{ fontSize: 9, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5, marginTop: 2 }}>{label}</div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════
 * Top-level component
 * ═══════════════════════════════════════════════════════════════════ */
export default function DCPhysicalTwin({ facilitySpec }) {
  const [selected, setSelected] = useState(null);

  const facility = {
    it_mw:         facilitySpec?.it_mw ?? 48,
    pue:           facilitySpec?.pue ?? 1.18,
    tier:          facilitySpec?.tier ?? "III",
    cfe_pct:       facilitySpec?.cfe_pct ?? 72,
    water_m3_year: facilitySpec?.water_m3_year ?? 168_000,
    rack_count:   facilitySpec?.rack_count ?? 24,
    rack_kw:      facilitySpec?.rack_kw ?? 20,
  };
  facility.total_mw = Math.round(facility.it_mw * facility.pue * 10) / 10;

  return (
    <div style={{ width: "100%", height: "100%", background: C.bg, position: "relative", overflow: "hidden" }}>
      <KPIStrip facility={facility} />

      <Canvas
        shadows
        camera={{ position: [12, 10, 12], fov: 45 }}
        style={{ width: "100%", height: "100%" }}
      >
        <color attach="background" args={[C.bg]} />
        <fog attach="fog" args={[C.bg, 15, 45]} />
        <DCScene selected={selected} setSelected={setSelected} />
        <OrbitControls
          enablePan
          enableRotate
          enableZoom
          maxPolarAngle={Math.PI * 0.49}
          minDistance={5}
          maxDistance={40}
        />
      </Canvas>

      <InfoPanel component={selected} onClose={() => setSelected(null)} facility={facility} />

      {/* Legend footer */}
      <div style={{
        position: "absolute", bottom: 18, left: 20,
        display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap",
        background: "rgba(11, 14, 19, 0.9)", padding: "10px 18px",
        borderRadius: 10, border: "1px solid rgba(255,255,255,0.08)",
        fontSize: 10, color: C.textDim,
      }}>
        <LegendDot colour={C.utility}     label="Utility" />
        <LegendDot colour={C.transformer} label="Transformer" />
        <LegendDot colour={C.ats}         label="ATS" />
        <LegendDot colour={C.genset}      label="Gensets" />
        <LegendDot colour={C.ups}         label="UPS" />
        <LegendDot colour={C.pdu}         label="PDU" />
        <LegendDot colour={C.rack}        label="Racks" />
        <LegendDot colour={C.chiller}     label="Chiller" />
        <LegendDot colour={C.cooling_tower} label="Cooling tower" />
        <LegendDot colour={C.crah}        label="CRAH" />
      </div>

      <div style={{
        position: "absolute", bottom: 18, right: 20,
        fontSize: 9, color: "#475569", fontStyle: "italic",
      }}>
        Click any component · IEA Data Centre reference architecture
      </div>
    </div>
  );
}

function LegendDot({ colour, label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 10, height: 10, borderRadius: 5, background: colour }} />
      <span>{label}</span>
    </div>
  );
}

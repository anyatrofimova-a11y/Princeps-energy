import React, { useState, useMemo, useRef, useCallback } from 'react';
import { Canvas, useThree, useFrame } from '@react-three/fiber';
import { OrbitControls, Html, Points, PointMaterial } from '@react-three/drei';
import * as THREE from 'three';

/* ─── Design tokens ─── */
const COLORS = {
  bg: '#F2F3F5',
  panel: 'rgba(255, 255, 255, 0.95)',
  accent: '#D4A018',
  accentDim: 'rgba(212, 160, 24, 0.2)',
  border: '1px solid rgba(212, 160, 24, 0.2)',
  text: '#1A1D23',
  textSec: '#4B5563',
  label: 'rgba(40, 120, 200, 0.85)',
  green: '#34d399',
  red: '#f87171',
  orange: '#fb923c',
  blue: '#60a5fa',
};

/* ─── Classification palette ─── */
const CLASS_COLORS = {
  ground:     [0.40, 0.30, 0.20],
  pole:       [0.55, 0.55, 0.55],
  crossarm:   [0.60, 0.50, 0.40],
  wire:       [0.25, 0.50, 0.85],
  vegetation: [0.20, 0.55, 0.20],
  equipment:  [0.75, 0.45, 0.15],
};

/* ─── Point Cloud Generator ─── */
function generatePolePointCloud() {
  const pts = [];
  const cols = [];
  const classifications = [];

  // Ground plane — 10 000 pts
  for (let i = 0; i < 10000; i++) {
    const x = (Math.random() - 0.5) * 24;
    const y = (Math.random() - 0.5) * 24;
    const z = Math.random() * 0.25 - 0.1;
    pts.push(x, y, z);
    const g = 0.35 + Math.random() * 0.1;
    cols.push(g, g * 0.75, g * 0.5);
    classifications.push('ground');
  }

  // Pole — 5 000 pts along cylinder
  for (let i = 0; i < 5000; i++) {
    const h = Math.random() * 12;
    const angle = Math.random() * Math.PI * 2;
    const r = 0.15 + Math.random() * 0.05;
    pts.push(Math.cos(angle) * r, Math.sin(angle) * r, h);
    const shade = 0.45 + Math.random() * 0.15;
    cols.push(shade, shade, shade);
    classifications.push('pole');
  }

  // Crossarms — 2 000 pts (2 arms)
  for (let arm = 0; arm < 2; arm++) {
    const z = 10 + arm * 1.5;
    for (let i = 0; i < 1000; i++) {
      const x = (Math.random() - 0.5) * 5;
      const y = (Math.random() - 0.5) * 0.12;
      const zz = z + (Math.random() - 0.5) * 0.12;
      pts.push(x, y, zz);
      cols.push(0.6, 0.5, 0.4);
      classifications.push('crossarm');
    }
  }

  // Wires — 10 000 pts (4 wires, catenary)
  const wireAnchors = [
    { y: -0.8, z: 11.5 },
    { y:  0.8, z: 11.5 },
    { y: -0.6, z: 10.0 },
    { y:  0.6, z: 10.0 },
  ];
  for (const anchor of wireAnchors) {
    for (let i = 0; i < 2500; i++) {
      const t = (Math.random() - 0.5) * 2; // -1..1
      const x = t * 12;
      const sag = 0.8 * (t * t); // catenary sag
      const z = anchor.z - sag + (Math.random() - 0.5) * 0.06;
      const y = anchor.y + (Math.random() - 0.5) * 0.04;
      pts.push(x, y, z);
      cols.push(0.25, 0.50, 0.85);
      classifications.push('wire');
    }
  }

  // Equipment (transformer) — 2 000 pts, box on pole
  for (let i = 0; i < 2000; i++) {
    const x = (Math.random() - 0.5) * 0.7 + 0.5;
    const y = (Math.random() - 0.5) * 0.7;
    const z = 8 + Math.random() * 1.0;
    pts.push(x, y, z);
    cols.push(0.75, 0.45, 0.15);
    classifications.push('equipment');
  }

  // Vegetation — 15 000 pts, clusters
  const vegClusters = [
    { cx: -6, cy: 4, cz: 3, r: 2.5 },
    { cx: 7, cy: -3, cz: 2.5, r: 2 },
    { cx: -4, cy: -6, cz: 2, r: 1.8 },
    { cx: 8, cy: 5, cz: 3.5, r: 2.8 },
    { cx: -8, cy: -2, cz: 1.8, r: 1.5 },
  ];
  const vegPerCluster = 3000;
  for (const c of vegClusters) {
    for (let i = 0; i < vegPerCluster; i++) {
      const phi = Math.random() * Math.PI * 2;
      const theta = Math.random() * Math.PI;
      const rr = Math.random() * c.r;
      const x = c.cx + rr * Math.sin(theta) * Math.cos(phi);
      const y = c.cy + rr * Math.sin(theta) * Math.sin(phi);
      const z = Math.max(0, c.cz + rr * Math.cos(theta) * 0.6);
      pts.push(x, y, z);
      const g = 0.18 + Math.random() * 0.4;
      cols.push(g * 0.5, g, g * 0.3);
      classifications.push('vegetation');
    }
  }

  // Guy wires — 1 847 pts (3 guys)
  const guyAngles = [Math.PI * 0.25, Math.PI * 0.75, Math.PI * 1.5];
  for (const ga of guyAngles) {
    for (let i = 0; i < 616; i++) {
      const t = Math.random();
      const x = Math.cos(ga) * t * 4;
      const y = Math.sin(ga) * t * 4;
      const z = 9 * (1 - t) + (Math.random() - 0.5) * 0.05;
      pts.push(x, y, z);
      cols.push(0.6, 0.6, 0.6);
      classifications.push('wire');
    }
  }

  return {
    positions: new Float32Array(pts),
    colors: new Float32Array(cols),
    count: pts.length / 3,
    classifications,
  };
}

/* ─── 3D Point Cloud Scene ─── */
function PointCloudScene({ onClickPoint, labelsVisible }) {
  const { positions, colors, count } = useMemo(() => generatePolePointCloud(), []);
  const pointsRef = useRef();

  const handleClick = useCallback((e) => {
    if (!e.point) return;
    onClickPoint?.({ x: e.point.x, y: e.point.y, z: e.point.z });
  }, [onClickPoint]);

  return (
    <>
      <ambientLight intensity={0.6} />
      <directionalLight position={[10, 10, 15]} intensity={0.8} />
      <Points ref={pointsRef} positions={positions} colors={colors} stride={3} onClick={handleClick}>
        <PointMaterial
          vertexColors
          size={0.06}
          sizeAttenuation
          transparent
          opacity={0.9}
          depthWrite={false}
        />
      </Points>
      <OrbitControls
        makeDefault
        target={[0, 0, 6]}
        minDistance={3}
        maxDistance={50}
        enableDamping
        dampingFactor={0.12}
      />
      {labelsVisible && <ComponentLabels />}
    </>
  );
}

/* ─── Floating Component Labels ─── */
function ComponentLabels() {
  const labelStyle = {
    background: 'rgba(30, 90, 160, 0.88)',
    color: '#e0f0ff',
    padding: '6px 10px',
    borderRadius: 6,
    fontSize: 11,
    fontFamily: "'Roboto', 'SF Pro Display', sans-serif",
    whiteSpace: 'nowrap',
    pointerEvents: 'none',
    border: '1px solid rgba(100, 180, 255, 0.3)',
    backdropFilter: 'blur(8px)',
    boxShadow: '0 2px 12px rgba(0,0,0,0.4)',
    lineHeight: 1.5,
  };

  const labels = [
    {
      pos: [0, 0, 13],
      title: 'Pole001 26726',
      details: 'Owner: Looq Power | Length: 40\' | Class: 5',
    },
    {
      pos: [2, 0, 11.5],
      title: 'Wire 001 Crossarm',
      details: "Type: 8' Crossarm | Height: 32.25'",
    },
    {
      pos: [-2.2, 0, 10],
      title: 'Wire 001 Insulator',
      details: 'Type: Pin | Material: Polymer',
    },
    {
      pos: [0.5, 0, 8.5],
      title: 'Equipment 001 Transformer',
      details: 'Size: 10kVA | Tension: Full',
    },
    {
      pos: [2.5, 2.5, 4.5],
      title: 'Guying',
      details: '3-point anchor | Condition: Good',
    },
  ];

  return labels.map((l, i) => (
    <Html key={i} position={l.pos} center distanceFactor={18} zIndexRange={[100, 0]}>
      <div style={labelStyle}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>{l.title}</div>
        <div style={{ opacity: 0.8, fontSize: 10 }}>{l.details}</div>
      </div>
    </Html>
  ));
}

/* ─── Schematic View (SLD) ─── */
function SchematicView() {
  const [hovered, setHovered] = useState(null);

  const elemStyle = (id) => ({
    cursor: 'pointer',
    transition: 'filter 0.15s, opacity 0.15s',
    filter: hovered === id ? 'drop-shadow(0 0 6px rgba(212, 160, 24, 0.8))' : 'none',
    opacity: hovered && hovered !== id ? 0.45 : 1,
  });

  const labelStyle = {
    fontSize: 10, fill: COLORS.textSec, fontFamily: "'Roboto', sans-serif",
  };
  const valStyle = {
    fontSize: 9, fill: COLORS.accent, fontFamily: "'Roboto', sans-serif", fontWeight: 600,
  };

  return (
    <div style={{
      flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: COLORS.bg, padding: 24,
    }}>
      <svg viewBox="0 0 820 360" width="100%" height="100%" style={{ maxWidth: 900, maxHeight: 420 }}>
        {/* Background grid */}
        <defs>
          <pattern id="sld-grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(212,160,24,0.06)" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width="820" height="360" fill="url(#sld-grid)" rx="8" />

        {/* Title block */}
        <text x="16" y="24" style={{ fontSize: 13, fill: COLORS.text, fontFamily: "'Roboto', sans-serif", fontWeight: 600 }}>
          Single-Line Diagram — 11kV/400V Distribution
        </text>
        <text x="16" y="40" style={{ fontSize: 10, fill: COLORS.textSec, fontFamily: "'Roboto', sans-serif" }}>
          Pole-mount transformer substation — 3 feeder circuits
        </text>

        {/* ── HV Incoming Line ── */}
        <g style={elemStyle('hv-line')} onMouseEnter={() => setHovered('hv-line')} onMouseLeave={() => setHovered(null)}>
          <line x1="30" y1="140" x2="110" y2="140" stroke={COLORS.red} strokeWidth="2.5" />
          <line x1="30" y1="140" x2="42" y2="132" stroke={COLORS.red} strokeWidth="2" />
          <line x1="30" y1="140" x2="42" y2="148" stroke={COLORS.red} strokeWidth="2" />
          <text x="40" y="126" style={labelStyle}>HV Incoming</text>
          <text x="40" y="158" style={valStyle}>11kV 3-phase</text>
        </g>

        {/* ── HV Disconnector ── */}
        <g style={elemStyle('disconnector')} onMouseEnter={() => setHovered('disconnector')} onMouseLeave={() => setHovered(null)}>
          <line x1="110" y1="140" x2="130" y2="140" stroke={COLORS.red} strokeWidth="2" />
          {/* Disconnector symbol: angled blade */}
          <line x1="130" y1="140" x2="155" y2="122" stroke={COLORS.orange} strokeWidth="2.5" strokeLinecap="round" />
          <circle cx="130" cy="140" r="4" fill={COLORS.bg} stroke={COLORS.orange} strokeWidth="2" />
          <circle cx="160" cy="140" r="4" fill={COLORS.bg} stroke={COLORS.orange} strokeWidth="2" />
          <line x1="160" y1="140" x2="180" y2="140" stroke={COLORS.red} strokeWidth="2" />
          <text x="126" y="112" style={labelStyle}>Disconnector</text>
          <text x="130" y="170" style={valStyle}>CLOSED</text>
        </g>

        {/* ── HV Fuse ── */}
        <g style={elemStyle('hv-fuse')} onMouseEnter={() => setHovered('hv-fuse')} onMouseLeave={() => setHovered(null)}>
          <line x1="180" y1="140" x2="200" y2="140" stroke={COLORS.red} strokeWidth="2" />
          <rect x="200" y="133" width="30" height="14" rx="3" fill={COLORS.bg} stroke={COLORS.orange} strokeWidth="1.5" />
          <line x1="204" y1="140" x2="226" y2="140" stroke={COLORS.orange} strokeWidth="1.5" />
          <line x1="230" y1="140" x2="250" y2="140" stroke={COLORS.red} strokeWidth="2" />
          <text x="198" y="126" style={labelStyle}>HV Fuse</text>
          <text x="200" y="158" style={valStyle}>100A</text>
        </g>

        {/* ── Transformer ── */}
        <g style={elemStyle('transformer')} onMouseEnter={() => setHovered('transformer')} onMouseLeave={() => setHovered(null)}>
          <line x1="250" y1="140" x2="280" y2="140" stroke={COLORS.red} strokeWidth="2" />
          {/* Primary winding */}
          <circle cx="300" cy="140" r="20" fill={COLORS.bg} stroke={COLORS.red} strokeWidth="2" />
          <text x="292" y="144" style={{ fontSize: 10, fill: COLORS.red, fontFamily: "'Roboto', sans-serif", fontWeight: 600 }}>HV</text>
          {/* Secondary winding */}
          <circle cx="340" cy="140" r="20" fill={COLORS.bg} stroke={COLORS.blue} strokeWidth="2" />
          <text x="333" y="144" style={{ fontSize: 10, fill: COLORS.blue, fontFamily: "'Roboto', sans-serif", fontWeight: 600 }}>LV</text>
          <line x1="360" y1="140" x2="390" y2="140" stroke={COLORS.blue} strokeWidth="2" />
          {/* Rating label */}
          <text x="300" y="104" style={{ ...labelStyle, textAnchor: 'middle', fontSize: 11 }}>Transformer</text>
          <text x="320" y="180" style={{ ...valStyle, textAnchor: 'middle' }}>11kV / 400V</text>
          <text x="320" y="192" style={{ ...valStyle, textAnchor: 'middle' }}>500 kVA Dyn11</text>
        </g>

        {/* ── LV Main Breaker ── */}
        <g style={elemStyle('lv-breaker')} onMouseEnter={() => setHovered('lv-breaker')} onMouseLeave={() => setHovered(null)}>
          <line x1="390" y1="140" x2="410" y2="140" stroke={COLORS.blue} strokeWidth="2" />
          {/* Breaker symbol: square with X */}
          <rect x="410" y="128" width="24" height="24" rx="2" fill={COLORS.bg} stroke={COLORS.blue} strokeWidth="1.5" />
          <line x1="414" y1="132" x2="430" y2="148" stroke={COLORS.blue} strokeWidth="1.5" />
          <line x1="430" y1="132" x2="414" y2="148" stroke={COLORS.blue} strokeWidth="1.5" />
          <line x1="434" y1="140" x2="460" y2="140" stroke={COLORS.blue} strokeWidth="2" />
          <text x="408" y="120" style={labelStyle}>MCCB</text>
          <text x="408" y="166" style={valStyle}>800A</text>
        </g>

        {/* ── LV Busbar ── */}
        <g style={elemStyle('busbar')} onMouseEnter={() => setHovered('busbar')} onMouseLeave={() => setHovered(null)}>
          <line x1="460" y1="140" x2="500" y2="140" stroke={COLORS.blue} strokeWidth="2" />
          {/* Thick busbar */}
          <rect x="500" y="80" width="6" height="190" rx="3" fill={COLORS.blue} />
          <text x="516" y="78" style={{ ...labelStyle, fontSize: 11 }}>LV Busbar</text>
          <text x="516" y="92" style={valStyle}>400V 3ph+N</text>
        </g>

        {/* ── Feeder 1 ── */}
        <g style={elemStyle('feeder1')} onMouseEnter={() => setHovered('feeder1')} onMouseLeave={() => setHovered(null)}>
          <line x1="506" y1="110" x2="560" y2="110" stroke={COLORS.green} strokeWidth="1.5" />
          {/* MCB symbol */}
          <rect x="560" y="102" width="18" height="16" rx="2" fill={COLORS.bg} stroke={COLORS.green} strokeWidth="1.5" />
          <line x1="564" y1="106" x2="574" y2="114" stroke={COLORS.green} strokeWidth="1.5" />
          <line x1="578" y1="110" x2="620" y2="110" stroke={COLORS.green} strokeWidth="1.5" />
          {/* Load symbol */}
          <polygon points="620,96 620,124 650,110" fill={COLORS.bg} stroke={COLORS.green} strokeWidth="1.5" />
          <text x="560" y="94" style={labelStyle}>Feeder 1 — Lighting</text>
          <text x="660" y="108" style={valStyle}>63A</text>
          <text x="660" y="120" style={{ fontSize: 8, fill: COLORS.textSec, fontFamily: "'Roboto', sans-serif" }}>32 kW</text>
        </g>

        {/* ── Feeder 2 ── */}
        <g style={elemStyle('feeder2')} onMouseEnter={() => setHovered('feeder2')} onMouseLeave={() => setHovered(null)}>
          <line x1="506" y1="175" x2="560" y2="175" stroke={COLORS.green} strokeWidth="1.5" />
          <rect x="560" y="167" width="18" height="16" rx="2" fill={COLORS.bg} stroke={COLORS.green} strokeWidth="1.5" />
          <line x1="564" y1="171" x2="574" y2="179" stroke={COLORS.green} strokeWidth="1.5" />
          <line x1="578" y1="175" x2="620" y2="175" stroke={COLORS.green} strokeWidth="1.5" />
          <polygon points="620,161 620,189 650,175" fill={COLORS.bg} stroke={COLORS.green} strokeWidth="1.5" />
          <text x="560" y="160" style={labelStyle}>Feeder 2 — Power</text>
          <text x="660" y="173" style={valStyle}>100A</text>
          <text x="660" y="185" style={{ fontSize: 8, fill: COLORS.textSec, fontFamily: "'Roboto', sans-serif" }}>55 kW</text>
        </g>

        {/* ── Feeder 3 ── */}
        <g style={elemStyle('feeder3')} onMouseEnter={() => setHovered('feeder3')} onMouseLeave={() => setHovered(null)}>
          <line x1="506" y1="240" x2="560" y2="240" stroke={COLORS.green} strokeWidth="1.5" />
          <rect x="560" y="232" width="18" height="16" rx="2" fill={COLORS.bg} stroke={COLORS.green} strokeWidth="1.5" />
          <line x1="564" y1="236" x2="574" y2="244" stroke={COLORS.green} strokeWidth="1.5" />
          <line x1="578" y1="240" x2="620" y2="240" stroke={COLORS.green} strokeWidth="1.5" />
          <polygon points="620,226 620,254 650,240" fill={COLORS.bg} stroke={COLORS.green} strokeWidth="1.5" />
          <text x="560" y="225" style={labelStyle}>Feeder 3 — Aux / EV</text>
          <text x="660" y="238" style={valStyle}>32A</text>
          <text x="660" y="250" style={{ fontSize: 8, fill: COLORS.textSec, fontFamily: "'Roboto', sans-serif" }}>18 kW</text>
        </g>

        {/* ── Earth symbol ── */}
        <g style={elemStyle('earth')} onMouseEnter={() => setHovered('earth')} onMouseLeave={() => setHovered(null)}>
          <line x1="503" y1="270" x2="503" y2="310" stroke={COLORS.textSec} strokeWidth="1.5" />
          <line x1="490" y1="310" x2="516" y2="310" stroke={COLORS.textSec} strokeWidth="2" />
          <line x1="494" y1="316" x2="512" y2="316" stroke={COLORS.textSec} strokeWidth="1.5" />
          <line x1="498" y1="322" x2="508" y2="322" stroke={COLORS.textSec} strokeWidth="1" />
          <text x="518" y="318" style={labelStyle}>Earth</text>
        </g>

        {/* ── Voltage labels at top ── */}
        <rect x="30" y="56" width="220" height="22" rx="4" fill="rgba(248,113,113,0.1)" stroke="rgba(248,113,113,0.2)" strokeWidth="1" />
        <text x="140" y="71" style={{ fontSize: 10, fill: COLORS.red, fontFamily: "'Roboto', sans-serif", fontWeight: 600, textAnchor: 'middle' }}>
          11kV HV ZONE
        </text>
        <rect x="460" y="56" width="260" height="22" rx="4" fill="rgba(96,165,250,0.1)" stroke="rgba(96,165,250,0.2)" strokeWidth="1" />
        <text x="590" y="71" style={{ fontSize: 10, fill: COLORS.blue, fontFamily: "'Roboto', sans-serif", fontWeight: 600, textAnchor: 'middle' }}>
          400V LV ZONE
        </text>

        {/* ── Hover tooltip ── */}
        {hovered && (
          <rect x="16" y="332" width={200} height="20" rx="4" fill="rgba(212,160,24,0.12)" stroke="rgba(212,160,24,0.25)" strokeWidth="1" />
        )}
        {hovered && (
          <text x="26" y="346" style={{ fontSize: 10, fill: COLORS.accent, fontFamily: "'Roboto', sans-serif" }}>
            Selected: {hovered.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
          </text>
        )}
      </svg>
    </div>
  );
}

/* ─── Photos View (gallery) ─── */
function PhotosView() {
  const photos = [
    {
      label: 'North face — full structure',
      date: '12 Feb 2026',
      inspector: 'J. Whitfield',
      condition: 'Good',
      gradient: 'linear-gradient(135deg, #1a3a5c 0%, #2d5a3d 40%, #3a6b4a 70%, #4a7d5c 100%)',
      overlay: 'POLE-001 N',
    },
    {
      label: 'Crossarm detail — primary',
      date: '12 Feb 2026',
      inspector: 'J. Whitfield',
      condition: 'Good',
      gradient: 'linear-gradient(150deg, #2c3e50 0%, #4a6741 35%, #5a7d5c 60%, #8fbc8f 100%)',
      overlay: 'CROSSARM',
    },
    {
      label: 'Transformer — close-up',
      date: '12 Feb 2026',
      inspector: 'S. Patel',
      condition: 'Fair',
      gradient: 'linear-gradient(120deg, #2c3e50 0%, #5c4a3a 40%, #7a6a5a 70%, #8b7355 100%)',
      overlay: 'EQUIP-001',
    },
    {
      label: 'Ground level — base & anchor',
      date: '13 Feb 2026',
      inspector: 'S. Patel',
      condition: 'Poor',
      gradient: 'linear-gradient(140deg, #3a2a1a 0%, #5a4a3a 30%, #4a5a3a 60%, #6a7a5a 100%)',
      overlay: 'BASE / GUY',
    },
  ];

  const conditionColor = (c) =>
    c === 'Good' ? COLORS.green : c === 'Fair' ? COLORS.orange : COLORS.red;

  return (
    <div style={{
      flex: 1, display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
      flexWrap: 'wrap', gap: 20, padding: 32, background: COLORS.bg, overflowY: 'auto',
      alignContent: 'center',
    }}>
      {photos.map((photo, i) => (
        <div key={i} style={{
          width: 290, borderRadius: 10, overflow: 'hidden',
          border: COLORS.border, background: 'rgba(255, 255, 255, 0.95)',
          transition: 'transform 0.2s, box-shadow 0.2s', cursor: 'pointer',
        }}
          onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-3px)'; e.currentTarget.style.boxShadow = '0 8px 24px rgba(212,160,24,0.15)'; }}
          onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = 'none'; }}
        >
          {/* Simulated photo area */}
          <div style={{
            height: 170, background: photo.gradient, position: 'relative',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {/* Simulated noise texture */}
            <div style={{
              position: 'absolute', inset: 0, opacity: 0.15,
              backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,0.03) 2px, rgba(255,255,255,0.03) 4px)',
            }} />
            {/* Crosshair / survey overlay */}
            <div style={{
              position: 'absolute', top: 8, left: 8,
              background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(4px)',
              borderRadius: 4, padding: '3px 8px', fontSize: 9, color: '#fff',
              fontFamily: "'SF Mono', 'Fira Code', monospace", letterSpacing: 0.5,
            }}>
              {photo.overlay}
            </div>
            {/* Timestamp overlay */}
            <div style={{
              position: 'absolute', bottom: 8, right: 8,
              background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(4px)',
              borderRadius: 4, padding: '3px 8px', fontSize: 9, color: 'rgba(255,255,255,0.7)',
              fontFamily: "'SF Mono', 'Fira Code', monospace",
            }}>
              {photo.date} 14:{String(22 + i * 7).padStart(2, '0')}
            </div>
            {/* Camera icon in centre */}
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="1.2">
              <rect x="2" y="6" width="20" height="14" rx="2" />
              <circle cx="12" cy="13" r="4" />
              <path d="M8 6l1-2h6l1 2" />
            </svg>
          </div>

          {/* Metadata strip */}
          <div style={{ padding: '10px 12px' }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
              marginBottom: 8,
            }}>
              <div style={{ fontSize: 12, color: COLORS.text, fontWeight: 500, flex: 1, lineHeight: 1.4 }}>
                {photo.label}
              </div>
              {/* Condition badge */}
              <span style={{
                fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
                padding: '2px 8px', borderRadius: 10, flexShrink: 0, marginLeft: 8,
                background: `${conditionColor(photo.condition)}22`,
                color: conditionColor(photo.condition),
                border: `1px solid ${conditionColor(photo.condition)}44`,
              }}>
                {photo.condition.toUpperCase()}
              </span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: COLORS.textSec }}>
              <span>{photo.inspector}</span>
              <span>{photo.date}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ─── Photo Viewer (right panel) ─── */
function PhotoViewer() {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: COLORS.textSec, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
        Field Photos
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        {[1, 2, 3].map(i => (
          <div key={i} style={{
            flex: 1, height: 64, background: 'rgba(212, 160, 24, 0.06)',
            border: COLORS.border, borderRadius: 6, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
          }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={COLORS.textSec} strokeWidth="1.5">
              <rect x="2" y="4" width="20" height="16" rx="2" />
              <circle cx="8" cy="11" r="2" />
              <path d="M22 20L16 13l-4 4-3-2-7 5" />
            </svg>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Attribute Row ─── */
function AttrRow({ label, value, editable = true }) {
  const [val, setVal] = useState(value);
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '4px 0', borderBottom: '1px solid rgba(0,0,0,0.06)',
    }}>
      <span style={{ fontSize: 11, color: COLORS.textSec }}>{label}</span>
      {editable ? (
        <input
          value={val}
          onChange={e => setVal(e.target.value)}
          style={{
            background: 'rgba(212, 160, 24, 0.08)', border: '1px solid rgba(212, 160, 24, 0.15)',
            borderRadius: 4, padding: '2px 6px', color: COLORS.text, fontSize: 11,
            width: 100, textAlign: 'right', outline: 'none', fontFamily: 'inherit',
          }}
          onFocus={e => e.target.style.borderColor = COLORS.accent}
          onBlur={e => e.target.style.borderColor = 'rgba(212, 160, 24, 0.15)'}
        />
      ) : (
        <span style={{ fontSize: 11, color: COLORS.text }}>{value}</span>
      )}
    </div>
  );
}

/* ─── Expandable Section ─── */
function Section({ title, badge, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ marginBottom: 2 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 6,
          background: 'rgba(212, 160, 24, 0.06)', border: 'none', borderRadius: 6,
          padding: '7px 10px', cursor: 'pointer', color: COLORS.text, fontSize: 12,
          fontFamily: 'inherit', textAlign: 'left',
        }}
      >
        <span style={{
          display: 'inline-block', width: 14, textAlign: 'center',
          transition: 'transform 0.15s', transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
          color: COLORS.textSec, fontSize: 10,
        }}>&#9654;</span>
        <span style={{ flex: 1, fontWeight: 500 }}>{title}</span>
        {badge && (
          <span style={{
            background: COLORS.green, color: '#000', fontSize: 9, padding: '1px 6px',
            borderRadius: 10, fontWeight: 600,
          }}>{badge}</span>
        )}
      </button>
      {open && (
        <div style={{ padding: '6px 10px 6px 24px' }}>
          {children}
        </div>
      )}
    </div>
  );
}

/* ─── Component Tree (Right Panel) ─── */
function ComponentTree() {
  return (
    <div style={{ flex: 1, overflowY: 'auto', paddingRight: 4 }}>
      <div style={{ fontSize: 11, color: COLORS.textSec, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
        Components
      </div>

      <Section title="Pole" badge="Base" defaultOpen>
        <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
          <span style={{
            background: COLORS.green, color: '#000', fontSize: 9, padding: '2px 8px',
            borderRadius: 10, fontWeight: 600, cursor: 'pointer',
          }}>Base</span>
          <span style={{
            background: COLORS.green, color: '#000', fontSize: 9, padding: '2px 8px',
            borderRadius: 10, fontWeight: 600, cursor: 'pointer',
          }}>Top</span>
        </div>
        <div style={{ fontSize: 11, color: COLORS.textSec, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4, marginTop: 4 }}>
          Attributes
        </div>
        <AttrRow label="Owner" value="Looq Power" />
        <AttrRow label="Species" value="Southern Pine" />
        <AttrRow label="Length" value="40'" />
        <AttrRow label="Class" value="5" />
        <AttrRow label="Height AGL" value="36.2'" />
        <AttrRow label="Circumference" value="33.5&quot;" />
        <AttrRow label="Lean Angle" value="1.2 deg" />
        <AttrRow label="Lean Direction" value="NNW (342 deg)" />

        <Section title="Damage">
          <AttrRow label="Woodpecker" value="None" />
          <AttrRow label="Shell rot" value="Minor" />
          <AttrRow label="Condition" value="Good" />
        </Section>
      </Section>

      <Section title="Wire 001">
        <AttrRow label="Type" value="Primary" />
        <AttrRow label="Conductor" value="4/0 ACSR" />
        <AttrRow label="Sag" value="2.8'" />
        <AttrRow label="Clearance" value="24.1'" />
        <AttrRow label="Tension" value="Full" />
        <Section title="Crossarm">
          <AttrRow label="Type" value="8' Crossarm" />
          <AttrRow label="Height" value="32.25'" />
          <AttrRow label="Material" value="Wood" />
        </Section>
        <Section title="Insulator">
          <AttrRow label="Type" value="Pin" />
          <AttrRow label="Material" value="Polymer" />
          <AttrRow label="Condition" value="Good" />
        </Section>
      </Section>

      <Section title="Wire 002">
        <AttrRow label="Type" value="Secondary" />
        <AttrRow label="Conductor" value="2/0 ACSR" />
        <AttrRow label="Sag" value="3.1'" />
        <AttrRow label="Clearance" value="22.8'" />
        <AttrRow label="Tension" value="Full" />
      </Section>

      <Section title="Guying">
        <AttrRow label="Count" value="3" />
        <AttrRow label="Type" value="Down guy" />
        <AttrRow label="Attachment" value="9.0'" />
        <AttrRow label="Anchor" value="Screw" />
        <AttrRow label="Condition" value="Good" />
      </Section>

      <Section title="Equipment 001">
        <AttrRow label="Type" value="Transformer" />
        <AttrRow label="Size" value="10 kVA" />
        <AttrRow label="Voltage" value="7.2/12.47 kV" />
        <AttrRow label="Manufacturer" value="ABB" />
        <AttrRow label="Mounting" value="Pole-mount" />
        <AttrRow label="Condition" value="Good" />
      </Section>
    </div>
  );
}

/* ─── Classification Legend Item ─── */
function LegendItem({ color, label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <div style={{
        width: 10, height: 10, borderRadius: 2,
        background: `rgb(${Math.round(color[0]*255)}, ${Math.round(color[1]*255)}, ${Math.round(color[2]*255)})`,
      }} />
      <span style={{ fontSize: 11, color: COLORS.textSec }}>{label}</span>
    </div>
  );
}

/* ─── Main Component ─── */
export default function AssetInspector({ onClose }) {
  const [mode, setMode] = useState('pointcloud');
  const [detecting, setDetecting] = useState(false);
  const [detected, setDetected] = useState(true);
  const [labelsVisible, setLabelsVisible] = useState(true);
  const [clickInfo, setClickInfo] = useState(null);

  const handleAutoDetect = useCallback(() => {
    setDetecting(true);
    setDetected(false);
    setTimeout(() => {
      setDetecting(false);
      setDetected(true);
      setLabelsVisible(true);
    }, 2200);
  }, []);

  const modeBtn = (key, label) => (
    <button
      onClick={() => setMode(key)}
      style={{
        padding: '5px 14px', fontSize: 12, borderRadius: 6, cursor: 'pointer',
        border: mode === key ? `1px solid ${COLORS.accent}` : '1px solid rgba(0,0,0,0.08)',
        background: mode === key ? 'rgba(212, 160, 24, 0.18)' : 'transparent',
        color: mode === key ? COLORS.text : COLORS.textSec,
        fontFamily: 'inherit', transition: 'all 0.15s',
      }}
    >
      {label}
    </button>
  );

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: COLORS.bg, display: 'flex', flexDirection: 'column',
      fontFamily: "'Roboto', 'SF Pro Display', -apple-system, sans-serif",
      color: COLORS.text,
    }}>

      {/* ── Top Bar ── */}
      <div style={{
        height: 52, display: 'flex', alignItems: 'center', padding: '0 16px',
        borderBottom: COLORS.border, background: COLORS.panel, gap: 12, flexShrink: 0,
      }}>
        {/* Title */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={COLORS.accent} strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 6v6l4 2" />
          </svg>
          <span style={{ fontWeight: 600, fontSize: 15 }}>Asset Inspector</span>
          <span style={{
            background: 'rgba(212, 160, 24, 0.15)', color: COLORS.accent,
            fontSize: 10, padding: '2px 8px', borderRadius: 10, fontWeight: 600,
            letterSpacing: 0.5,
          }}>qSurvey</span>
        </div>

        {/* Mode toggle */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 24 }}>
          {modeBtn('pointcloud', 'Point Cloud')}
          {modeBtn('schematic', 'Schematic')}
          {modeBtn('photos', 'Photos')}
        </div>

        {/* Auto-detect */}
        <button
          onClick={handleAutoDetect}
          disabled={detecting}
          style={{
            marginLeft: 'auto', padding: '5px 14px', fontSize: 12, borderRadius: 6,
            cursor: detecting ? 'wait' : 'pointer',
            border: `1px solid ${COLORS.accent}`, background: detecting ? 'rgba(212, 160, 24, 0.25)' : 'rgba(212, 160, 24, 0.12)',
            color: COLORS.accent, fontFamily: 'inherit', fontWeight: 500,
            display: 'flex', alignItems: 'center', gap: 6, transition: 'all 0.15s',
          }}
        >
          {detecting ? (
            <span style={{ display: 'inline-block', animation: 'assetSpin 1s linear infinite', width: 14, height: 14 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={COLORS.accent} strokeWidth="2.5">
                <path d="M12 2a10 10 0 0 1 10 10" />
              </svg>
            </span>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={COLORS.accent} strokeWidth="2">
              <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          )}
          {detecting ? 'Detecting...' : 'Auto-detect'}
        </button>

        {/* Labels toggle */}
        <button
          onClick={() => setLabelsVisible(v => !v)}
          style={{
            padding: '5px 10px', fontSize: 11, borderRadius: 6, cursor: 'pointer',
            border: labelsVisible ? `1px solid ${COLORS.accent}` : '1px solid rgba(0,0,0,0.08)',
            background: labelsVisible ? 'rgba(212, 160, 24, 0.12)' : 'transparent',
            color: labelsVisible ? COLORS.accent : COLORS.textSec,
            fontFamily: 'inherit',
          }}
        >
          Labels
        </button>

        {/* Close */}
        <button
          onClick={onClose}
          style={{
            width: 34, height: 34, borderRadius: 8, border: '1px solid rgba(0,0,0,0.08)',
            background: 'transparent', cursor: 'pointer', display: 'flex',
            alignItems: 'center', justifyContent: 'center', color: COLORS.textSec,
            fontSize: 18, fontFamily: 'inherit', transition: 'all 0.15s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(248,113,113,0.15)'; e.currentTarget.style.color = COLORS.red; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = COLORS.textSec; }}
        >
          &#x2715;
        </button>
      </div>

      {/* ── Body ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* ── 3D View (left, 70%) ── */}
        <div style={{ flex: 7, position: 'relative', background: COLORS.bg }}>
          {mode === 'pointcloud' && (
            <Canvas
              camera={{ position: [12, 8, 10], fov: 50, near: 0.1, far: 200 }}
              style={{ background: COLORS.bg }}
              gl={{ antialias: true }}
            >
              <PointCloudScene
                onClickPoint={setClickInfo}
                labelsVisible={labelsVisible && detected}
              />
            </Canvas>
          )}
          {mode === 'schematic' && <SchematicView />}
          {mode === 'photos' && <PhotosView />}

          {/* Click info tooltip */}
          {clickInfo && mode === 'pointcloud' && (
            <div style={{
              position: 'absolute', bottom: 60, left: 16,
              background: COLORS.panel, border: COLORS.border, borderRadius: 8,
              padding: '8px 14px', fontSize: 11, color: COLORS.textSec,
            }}>
              Clicked: ({clickInfo.x.toFixed(2)}, {clickInfo.y.toFixed(2)}, {clickInfo.z.toFixed(2)})
            </div>
          )}

          {/* Detecting overlay */}
          {detecting && (
            <div style={{
              position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'rgba(255, 255, 255, 0.7)', zIndex: 10,
            }}>
              <div style={{
                background: COLORS.panel, border: COLORS.border, borderRadius: 12,
                padding: '24px 32px', textAlign: 'center',
              }}>
                <div style={{ fontSize: 14, fontWeight: 500, marginBottom: 8 }}>Running AI Component Detection</div>
                <div style={{ fontSize: 12, color: COLORS.textSec }}>Classifying point cloud segments...</div>
                <div style={{
                  marginTop: 12, height: 3, background: 'rgba(212, 160, 24, 0.15)',
                  borderRadius: 2, overflow: 'hidden',
                }}>
                  <div style={{
                    height: '100%', background: COLORS.accent, borderRadius: 2,
                    animation: 'assetProgress 2s ease-in-out',
                    width: '100%',
                  }} />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Right Panel (30%) ── */}
        <div style={{
          flex: 3, display: 'flex', flexDirection: 'column',
          borderLeft: COLORS.border, background: COLORS.panel,
          padding: 16, overflowY: 'auto', minWidth: 280,
        }}>
          <PhotoViewer />
          <ComponentTree />
        </div>
      </div>

      {/* ── Bottom Toolbar ── */}
      <div style={{
        height: 44, display: 'flex', alignItems: 'center', padding: '0 16px',
        borderTop: COLORS.border, background: COLORS.panel, gap: 20, flexShrink: 0,
      }}>
        {/* Point count */}
        <div style={{ fontSize: 12, color: COLORS.textSec }}>
          <span style={{ color: COLORS.text, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>52,847</span> points
        </div>

        {/* Separator */}
        <div style={{ width: 1, height: 20, background: 'rgba(0,0,0,0.08)' }} />

        {/* Classification legend */}
        <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
          <LegendItem color={CLASS_COLORS.ground} label="Ground" />
          <LegendItem color={CLASS_COLORS.pole} label="Pole" />
          <LegendItem color={CLASS_COLORS.wire} label="Wire" />
          <LegendItem color={CLASS_COLORS.vegetation} label="Vegetation" />
          <LegendItem color={CLASS_COLORS.equipment} label="Equipment" />
        </div>

        <div style={{ width: 1, height: 20, background: 'rgba(0,0,0,0.08)' }} />

        {/* Measure tool */}
        <button style={{
          padding: '4px 12px', fontSize: 11, borderRadius: 6, cursor: 'pointer',
          border: '1px solid rgba(0,0,0,0.08)', background: 'transparent',
          color: COLORS.textSec, fontFamily: 'inherit', display: 'flex',
          alignItems: 'center', gap: 5,
        }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 2l20 20M6 2v4M2 6h4M18 22v-4M22 18h-4" />
          </svg>
          Measure
        </button>

        {/* Export */}
        <button
          disabled
          style={{
            padding: '4px 12px', fontSize: 11, borderRadius: 6,
            border: '1px solid rgba(0,0,0,0.05)', background: 'transparent',
            color: 'rgba(75,85,99,0.4)', fontFamily: 'inherit', cursor: 'not-allowed',
            display: 'flex', alignItems: 'center', gap: 5,
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
          </svg>
          Export
        </button>

        {/* AI Confidence */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: COLORS.textSec }}>AI Detection:</span>
          <span style={{
            fontSize: 12, fontWeight: 600, color: COLORS.green,
            fontVariantNumeric: 'tabular-nums',
          }}>
            {detected ? '94.2%' : '—'}
          </span>
          {detected && (
            <div style={{
              width: 60, height: 4, background: 'rgba(52, 211, 153, 0.15)',
              borderRadius: 2, overflow: 'hidden',
            }}>
              <div style={{ width: '94.2%', height: '100%', background: COLORS.green, borderRadius: 2 }} />
            </div>
          )}
        </div>
      </div>

      {/* ── Keyframe animations ── */}
      <style>{`
        @keyframes assetSpin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes assetProgress {
          from { width: 0%; }
          to { width: 100%; }
        }
      `}</style>
    </div>
  );
}

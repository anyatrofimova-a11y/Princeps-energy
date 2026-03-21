/**
 * Asset3DModeller — Gemini AI-powered 3D asset preview and map placement.
 *
 * 1. User selects asset type (data_centre, substation, solar_farm, bess, wind_turbine)
 * 2. Calls /api/grid/asset-model to get Gemini-generated specs
 * 3. Renders interactive 3D preview with React Three Fiber + postprocessing
 * 4. User clicks "Place on Map" → drops asset at current map centre
 * 5. Shows construction protocol timeline
 */
import React, { useState, useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Grid, Html, Environment } from "@react-three/drei";
import * as THREE from "three";
import PostprocessingEffects from "./PostprocessingEffects";

/* ── Procedural component renderer ────────────────────────────────── */
function AssetComponent({ comp, hovered, onClick }) {
  const meshRef = useRef();
  const [isHovered, setIsHovered] = useState(false);
  const baseColor = new THREE.Color(comp.color || "#666");

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    const mat = meshRef.current.material;
    const targetEmissive = isHovered ? 0.4 : 0.05;
    mat.emissiveIntensity += (targetEmissive - mat.emissiveIntensity) * delta * 8;
  });

  const pos = comp.position || [0, 0, 0];
  const dims = comp.dims || [1, 1, 1];
  const repeat = comp.repeat || [1, 1, 1];
  const spacing = comp.spacing || [0, 0, 0];

  const instances = [];
  for (let ix = 0; ix < repeat[0]; ix++) {
    for (let iy = 0; iy < repeat[1]; iy++) {
      for (let iz = 0; iz < repeat[2]; iz++) {
        instances.push([
          pos[0] + ix * spacing[0] - ((repeat[0] - 1) * spacing[0]) / 2,
          pos[1] + iy * spacing[1],
          pos[2] + iz * spacing[2] - ((repeat[2] - 1) * spacing[2]) / 2,
        ]);
      }
    }
  }

  return (
    <>
      {instances.map((p, i) => (
        <mesh
          key={i}
          ref={i === 0 ? meshRef : undefined}
          position={p}
          rotation={comp.rotation ? comp.rotation.map(r => (r * Math.PI) / 180) : [0, 0, 0]}
          castShadow
          receiveShadow
          onClick={onClick}
          onPointerEnter={() => setIsHovered(true)}
          onPointerLeave={() => setIsHovered(false)}
        >
          {comp.type === "security_fence" || comp.type === "perimeter_fence" ? (
            <boxGeometry args={[dims[0], dims[1] || 2.4, dims[2]]} />
          ) : (
            <boxGeometry args={dims} />
          )}
          <meshStandardMaterial
            color={baseColor}
            emissive={baseColor}
            emissiveIntensity={0.05}
            metalness={comp.type?.includes("transformer") || comp.type?.includes("steel") ? 0.7 : 0.2}
            roughness={comp.type?.includes("panel") ? 0.1 : 0.6}
            transparent={comp.type?.includes("fence")}
            opacity={comp.type?.includes("fence") ? 0.3 : 1}
            wireframe={comp.type?.includes("fence")}
          />
        </mesh>
      ))}
    </>
  );
}

function AssetScene({ spec, selectedComponent, onSelectComponent }) {
  if (!spec || !spec.components) return null;

  // Auto-scale camera based on footprint
  const maxDim = Math.max(spec.footprint_m?.[0] || 50, spec.footprint_m?.[1] || 50, spec.height_m || 10);
  const camDist = maxDim * 0.8;

  return (
    <>
      <ambientLight intensity={0.35} />
      <directionalLight
        position={[camDist * 0.6, camDist * 0.8, camDist * 0.4]}
        intensity={0.9}
        castShadow
        shadow-mapSize={[1024, 1024]}
      />
      <pointLight position={[-camDist * 0.3, camDist * 0.5, -camDist * 0.2]} intensity={0.3} color="#D4A018" />

      {/* Ground plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow position={[0, -0.01, 0]}>
        <planeGeometry args={[maxDim * 3, maxDim * 3]} />
        <meshStandardMaterial color="#1a2a1a" />
      </mesh>

      <Grid
        args={[maxDim * 2, maxDim * 2]}
        cellSize={maxDim / 20}
        cellColor="#2a3a2a"
        sectionSize={maxDim / 4}
        sectionColor="#3a5a3a"
        fadeDistance={maxDim * 2}
        position={[0, 0.01, 0]}
      />

      {spec.components.map((comp, i) => (
        <AssetComponent
          key={i}
          comp={comp}
          hovered={selectedComponent === i}
          onClick={() => onSelectComponent?.(i)}
        />
      ))}

      <OrbitControls
        enablePan
        enableZoom
        enableRotate
        minDistance={maxDim * 0.3}
        maxDistance={maxDim * 3}
        target={[0, (spec.height_m || 10) / 3, 0]}
        maxPolarAngle={Math.PI * 0.48}
      />
    </>
  );
}

/* ── Main panel ────────────────────────────────────────────────────── */
const ASSET_ICONS = {
  data_centre: "🏢",
  substation: "⚡",
  solar_farm: "☀️",
  bess: "🔋",
  wind_turbine: "🌬️",
};

export default function Asset3DModeller({ onClose, onPlaceOnMap }) {
  const [assetTypes, setAssetTypes] = useState([]);
  const [selectedType, setSelectedType] = useState("data_centre");
  const [spec, setSpec] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedComponent, setSelectedComponent] = useState(null);
  const [showProtocol, setShowProtocol] = useState(false);
  const [capacityMw, setCapacityMw] = useState(null);

  // Fetch asset types
  useEffect(() => {
    fetch("/api/grid/asset-types")
      .then(r => r.json())
      .then(setAssetTypes)
      .catch(() => {});
  }, []);

  // Generate model
  const generateModel = async () => {
    setLoading(true);
    setSpec(null);
    setSelectedComponent(null);
    try {
      const params = new URLSearchParams({ asset_type: selectedType });
      if (capacityMw) params.set("capacity_mw", capacityMw);
      const r = await fetch(`/api/grid/asset-model?${params}`, { method: "POST" });
      const data = await r.json();
      if (!data.error) setSpec(data);
    } catch (e) {
      console.warn("Asset model generation failed:", e);
    }
    setLoading(false);
  };

  // Auto-generate on type change
  useEffect(() => {
    generateModel();
  }, [selectedType]);

  const comp = spec?.components?.[selectedComponent];

  return (
    <div className="a3d-overlay">
      {/* Header */}
      <div className="a3d-header">
        <div className="a3d-header-left">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#D4A018" strokeWidth="2">
            <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/>
          </svg>
          <span className="a3d-title">Gemini 3D Asset Modeller</span>
          {spec && <span className="a3d-badge">{spec.name}</span>}
        </div>
        <button className="a3d-close" onClick={onClose}>&times;</button>
      </div>

      <div className="a3d-body">
        {/* Left: Asset type selector + specs */}
        <div className="a3d-sidebar">
          <div className="a3d-section-title">Asset Type</div>
          <div className="a3d-type-grid">
            {assetTypes.map(t => (
              <button
                key={t.id}
                className={`a3d-type-btn ${selectedType === t.id ? "active" : ""}`}
                onClick={() => { setSelectedType(t.id); setCapacityMw(t.default_mw); }}
              >
                <span className="a3d-type-icon">{ASSET_ICONS[t.id] || "📦"}</span>
                <span className="a3d-type-label">{t.label}</span>
              </button>
            ))}
          </div>

          {/* Capacity input */}
          <div className="a3d-section-title" style={{ marginTop: 12 }}>Capacity (MW)</div>
          <input
            type="number"
            className="a3d-input"
            value={capacityMw || ""}
            onChange={e => setCapacityMw(e.target.value ? Number(e.target.value) : null)}
            placeholder="Auto"
          />
          <button className="a3d-generate-btn" onClick={generateModel} disabled={loading}>
            {loading ? "Generating…" : "Regenerate with Gemini AI"}
          </button>

          {/* Spec summary */}
          {spec && (
            <div className="a3d-specs">
              <div className="a3d-spec-row">
                <span>Footprint</span>
                <span>{spec.footprint_m?.[0]}m × {spec.footprint_m?.[1]}m</span>
              </div>
              <div className="a3d-spec-row">
                <span>Height</span>
                <span>{spec.height_m}m</span>
              </div>
              <div className="a3d-spec-row">
                <span>Capacity</span>
                <span>{spec.power_mw} MW</span>
              </div>
              <div className="a3d-spec-row">
                <span>Build time</span>
                <span>{spec.construction_months} months</span>
              </div>
              <div className="a3d-spec-row">
                <span>Est. cost</span>
                <span>£{spec.cost_gbp_m}M</span>
              </div>
              <div className="a3d-spec-row">
                <span>Components</span>
                <span>{spec.components?.length}</span>
              </div>
            </div>
          )}

          {/* Selected component detail */}
          {comp && (
            <div className="a3d-comp-detail">
              <div className="a3d-section-title">Selected: {comp.type}</div>
              <div className="a3d-spec-row"><span>Size</span><span>{comp.dims?.join(" × ")}m</span></div>
              <div className="a3d-spec-row"><span>Position</span><span>{comp.position?.map(v => v.toFixed(1)).join(", ")}</span></div>
              {comp.repeat && <div className="a3d-spec-row"><span>Count</span><span>{comp.repeat.reduce((a, b) => a * b, 1)}</span></div>}
            </div>
          )}

          {/* Place on map */}
          {spec && (
            <button
              className="a3d-place-btn"
              onClick={() => onPlaceOnMap?.(spec)}
            >
              Place on Map
            </button>
          )}
        </div>

        {/* Centre: 3D viewport */}
        <div className="a3d-viewport">
          {loading && (
            <div className="a3d-loading">
              <div className="a3d-loading-spinner" />
              Gemini is designing your asset…
            </div>
          )}
          <Canvas
            shadows
            camera={{
              position: [
                (spec?.footprint_m?.[0] || 50) * 0.6,
                (spec?.height_m || 10) * 1.2,
                (spec?.footprint_m?.[1] || 50) * 0.6,
              ],
              fov: 45,
            }}
            style={{ background: "#0a0f0a" }}
          >
            <AssetScene
              spec={spec}
              selectedComponent={selectedComponent}
              onSelectComponent={setSelectedComponent}
            />
            <PostprocessingEffects
              bloom={1.6}
              bloomThreshold={0.25}
              chromaticAberration={0.002}
              vignette={0.55}
            />
          </Canvas>
        </div>

        {/* Right: Construction protocol */}
        {spec?.protocol && (
          <div className="a3d-protocol">
            <div className="a3d-section-title">
              Construction Protocol
              <button
                className="a3d-toggle-btn"
                onClick={() => setShowProtocol(!showProtocol)}
              >
                {showProtocol ? "▲" : "▼"}
              </button>
            </div>
            {showProtocol && (
              <div className="a3d-protocol-list">
                {spec.protocol.map((step, i) => (
                  <div key={i} className="a3d-protocol-step">
                    <span className="a3d-protocol-num">{i + 1}</span>
                    <span className="a3d-protocol-text">{step}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

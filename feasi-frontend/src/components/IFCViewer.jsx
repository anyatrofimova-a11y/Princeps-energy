/**
 * IFCViewer — BIM/IFC model viewer using web-ifc + @react-three/fiber.
 *
 * Upload .ifc files, parse geometry in-browser via WASM, render with Three.js.
 * Supports: selection highlighting, property inspection, spatial tree.
 */
import React, { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Grid, Environment } from "@react-three/drei";
import * as THREE from "three";

/* ── Styles ───────────────────────────────────────────────────────────── */
const S = {
  wrap: { width: "100%", height: "100%", display: "flex", flexDirection: "column", background: "#0F1117", color: "#E8E6E1", fontFamily: "Inter, system-ui, sans-serif" },
  toolbar: { display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderBottom: "1px solid rgba(212,160,24,0.2)", background: "rgba(15,17,23,0.95)" },
  btn: { padding: "6px 12px", border: "1px solid rgba(212,160,24,0.3)", borderRadius: 6, background: "transparent", color: "#D4A018", cursor: "pointer", fontSize: 12 },
  btnActive: { background: "rgba(212,160,24,0.18)" },
  main: { flex: 1, display: "flex", position: "relative", overflow: "hidden" },
  sidebar: { width: 260, borderRight: "1px solid rgba(212,160,24,0.15)", overflowY: "auto", padding: 8, fontSize: 12 },
  canvas: { flex: 1 },
  props: { width: 280, borderLeft: "1px solid rgba(212,160,24,0.15)", overflowY: "auto", padding: 10, fontSize: 12 },
  treeItem: (depth, selected) => ({
    paddingLeft: depth * 14, padding: "3px 6px", cursor: "pointer", borderRadius: 4,
    background: selected ? "rgba(212,160,24,0.18)" : "transparent",
    color: selected ? "#D4A018" : "#9CA3AF",
  }),
  dropZone: { flex: 1, display: "flex", alignItems: "center", justifyContent: "center", border: "2px dashed rgba(212,160,24,0.3)", borderRadius: 12, margin: 24, cursor: "pointer" },
  propRow: { display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px solid rgba(255,255,255,0.05)" },
  propKey: { color: "#9CA3AF" },
  propVal: { color: "#E8E6E1", textAlign: "right", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis" },
  status: { padding: "4px 12px", fontSize: 11, color: "#9CA3AF", borderTop: "1px solid rgba(212,160,24,0.1)" },
};

/* ── IFC Mesh component ──────────────────────────────────────────────── */
function IFCMesh({ meshData, selected, onClick }) {
  const ref = useRef();
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(meshData.positions, 3));
    g.setAttribute("normal", new THREE.BufferAttribute(meshData.normals, 3));
    if (meshData.indices) g.setIndex(new THREE.BufferAttribute(meshData.indices, 1));
    g.computeBoundingSphere();
    return g;
  }, [meshData]);

  const mat = useMemo(() => new THREE.MeshStandardMaterial({
    color: selected ? new THREE.Color("#D4A018") : new THREE.Color(meshData.color || "#8899aa"),
    metalness: 0.1,
    roughness: 0.7,
    transparent: !selected,
    opacity: selected ? 1 : 0.85,
    side: THREE.DoubleSide,
  }), [selected, meshData.color]);

  return (
    <mesh ref={ref} geometry={geo} material={mat} onClick={(e) => { e.stopPropagation(); onClick?.(meshData.expressID); }}
      matrixAutoUpdate={false} matrix={meshData.matrix ? new THREE.Matrix4().fromArray(meshData.matrix) : new THREE.Matrix4()} />
  );
}

/* ── Camera auto-fit ──────────────────────────────────────────────────── */
function AutoFit({ meshes }) {
  const { camera } = useThree();
  useEffect(() => {
    if (!meshes?.length) return;
    const box = new THREE.Box3();
    for (const m of meshes) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(m.positions, 3));
      g.computeBoundingBox();
      if (m.matrix) {
        const mat = new THREE.Matrix4().fromArray(m.matrix);
        g.boundingBox.applyMatrix4(mat);
      }
      box.union(g.boundingBox);
      g.dispose();
    }
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length();
    camera.position.copy(center.clone().add(new THREE.Vector3(size * 0.7, size * 0.5, size * 0.7)));
    camera.lookAt(center);
    camera.updateProjectionMatrix();
  }, [meshes, camera]);
  return null;
}

/* ── Main Component ───────────────────────────────────────────────────── */
export default function IFCViewer() {
  const [meshes, setMeshes] = useState([]);
  const [selectedID, setSelectedID] = useState(null);
  const [properties, setProperties] = useState({});
  const [treeNodes, setTreeNodes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState(null);
  const [status, setStatus] = useState("Drop an .ifc file or click to upload");
  const fileRef = useRef(null);
  const apiRef = useRef(null);
  const modelRef = useRef(null);

  const loadIFC = useCallback(async (buffer) => {
    setLoading(true);
    setStatus("Loading web-ifc WASM...");

    try {
      const WebIFC = await import("web-ifc");
      const api = new WebIFC.IfcAPI();
      // Attempt to set WASM path for Vite
      try { api.SetWasmPath("/node_modules/web-ifc/"); } catch {}
      await api.Init();
      apiRef.current = api;

      setStatus("Parsing IFC model...");
      const data = new Uint8Array(buffer);
      const modelID = api.OpenModel(data);
      modelRef.current = modelID;

      // Extract meshes
      const allMeshes = [];
      const flatMeshes = api.LoadAllGeometry(modelID);

      for (let i = 0; i < flatMeshes.size(); i++) {
        const flatMesh = flatMeshes.get(i);
        const placedGeometries = flatMesh.geometries;

        for (let j = 0; j < placedGeometries.size(); j++) {
          const placed = placedGeometries.get(j);
          const geo = api.GetGeometry(modelID, placed.geometryExpressID);

          const vData = api.GetVertexArray(geo.GetVertexData(), geo.GetVertexDataSize());
          const iData = api.GetIndexArray(geo.GetIndexData(), geo.GetIndexDataSize());

          const vertexCount = vData.length / 6;
          const positions = new Float32Array(vertexCount * 3);
          const normals = new Float32Array(vertexCount * 3);

          for (let k = 0; k < vertexCount; k++) {
            positions[k * 3] = vData[k * 6];
            positions[k * 3 + 1] = vData[k * 6 + 1];
            positions[k * 3 + 2] = vData[k * 6 + 2];
            normals[k * 3] = vData[k * 6 + 3];
            normals[k * 3 + 1] = vData[k * 6 + 4];
            normals[k * 3 + 2] = vData[k * 6 + 5];
          }

          const r = placed.color.x, g = placed.color.y, b = placed.color.z;
          const color = `#${Math.round(r * 255).toString(16).padStart(2, "0")}${Math.round(g * 255).toString(16).padStart(2, "0")}${Math.round(b * 255).toString(16).padStart(2, "0")}`;

          allMeshes.push({
            expressID: flatMesh.expressID,
            positions,
            normals,
            indices: iData.length ? new Uint32Array(iData) : null,
            color,
            matrix: Array.from(placed.flatTransformation),
          });

          geo.delete();
        }
      }

      setMeshes(allMeshes);

      // Build simple tree from IFC types
      const types = [
        { label: "IfcWall", type: WebIFC.IFCWALL },
        { label: "IfcSlab", type: WebIFC.IFCSLAB },
        { label: "IfcColumn", type: WebIFC.IFCCOLUMN },
        { label: "IfcBeam", type: WebIFC.IFCBEAM },
        { label: "IfcDoor", type: WebIFC.IFCDOOR },
        { label: "IfcWindow", type: WebIFC.IFCWINDOW },
        { label: "IfcRoof", type: WebIFC.IFCROOF },
        { label: "IfcStair", type: WebIFC.IFCSTAIRFLIGHT },
      ];

      const tree = [];
      for (const t of types) {
        try {
          const ids = api.GetLineIDsWithType(modelID, t.type);
          if (ids.size() > 0) {
            const children = [];
            for (let i = 0; i < ids.size(); i++) {
              const id = ids.get(i);
              try {
                const props = api.GetLine(modelID, id);
                children.push({ id, label: props?.Name?.value || `#${id}`, depth: 1 });
              } catch {
                children.push({ id, label: `#${id}`, depth: 1 });
              }
            }
            tree.push({ label: `${t.label} (${children.length})`, children, depth: 0 });
          }
        } catch {}
      }
      setTreeNodes(tree);

      flatMeshes.delete();
      setStatus(`Loaded ${allMeshes.length} meshes`);
    } catch (err) {
      console.error("IFC load error:", err);
      setStatus(`Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSelect = useCallback((expressID) => {
    setSelectedID(expressID);
    if (apiRef.current && modelRef.current != null) {
      try {
        const line = apiRef.current.GetLine(modelRef.current, expressID, true);
        const props = {};
        if (line) {
          for (const [key, val] of Object.entries(line)) {
            if (val?.value !== undefined) props[key] = val.value;
            else if (typeof val === "string" || typeof val === "number") props[key] = val;
          }
        }
        setProperties(props);
      } catch {
        setProperties({ expressID });
      }
    }
  }, []);

  const handleFile = useCallback((file) => {
    if (!file?.name?.toLowerCase().endsWith(".ifc")) {
      setStatus("Please select an .ifc file");
      return;
    }
    setFileName(file.name);
    const reader = new FileReader();
    reader.onload = (e) => loadIFC(e.target.result);
    reader.readAsArrayBuffer(file);
  }, [loadIFC]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFile(file);
  }, [handleFile]);

  // No model loaded — show upload
  if (!meshes.length && !loading) {
    return (
      <div style={S.wrap}>
        <div style={S.toolbar}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>IFC Viewer</span>
        </div>
        <div style={S.dropZone} onDrop={handleDrop} onDragOver={(e) => e.preventDefault()} onClick={() => fileRef.current?.click()}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 36, marginBottom: 8, opacity: 0.4 }}>📐</div>
            <div style={{ color: "#9CA3AF" }}>{status}</div>
            <div style={{ color: "#D4A018", marginTop: 8, fontSize: 12 }}>Supports IFC2x3 and IFC4</div>
          </div>
          <input ref={fileRef} type="file" accept=".ifc" style={{ display: "none" }} onChange={(e) => handleFile(e.target.files?.[0])} />
        </div>
      </div>
    );
  }

  return (
    <div style={S.wrap}>
      <div style={S.toolbar}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>IFC Viewer</span>
        {fileName && <span style={{ fontSize: 12, color: "#9CA3AF" }}>{fileName}</span>}
        <div style={{ flex: 1 }} />
        <button style={S.btn} onClick={() => { setMeshes([]); setTreeNodes([]); setProperties({}); setSelectedID(null); setFileName(null); }}>
          New File
        </button>
        <button style={S.btn} onClick={() => fileRef.current?.click()}>Upload</button>
        <input ref={fileRef} type="file" accept=".ifc" style={{ display: "none" }} onChange={(e) => handleFile(e.target.files?.[0])} />
      </div>

      <div style={S.main}>
        {/* Spatial Tree */}
        <div style={S.sidebar}>
          <div style={{ fontWeight: 600, marginBottom: 8, color: "#D4A018" }}>Model Tree</div>
          {treeNodes.map((node, i) => (
            <div key={i}>
              <div style={S.treeItem(0, false)}>{node.label}</div>
              {node.children?.map((child) => (
                <div key={child.id} style={S.treeItem(1, selectedID === child.id)} onClick={() => handleSelect(child.id)}>
                  {child.label}
                </div>
              ))}
            </div>
          ))}
          {treeNodes.length === 0 && !loading && <div style={{ color: "#666" }}>No elements found</div>}
        </div>

        {/* 3D Canvas */}
        <div style={S.canvas}>
          {loading ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#D4A018" }}>
              Loading...
            </div>
          ) : (
            <Canvas camera={{ position: [30, 20, 30], fov: 50, near: 0.1, far: 10000 }} gl={{ antialias: true }}>
              <ambientLight intensity={0.6} />
              <directionalLight position={[20, 40, 20]} intensity={0.8} castShadow />
              <directionalLight position={[-10, 20, -10]} intensity={0.3} />
              <OrbitControls makeDefault enableDamping dampingFactor={0.1} />
              <Grid infiniteGrid fadeDistance={200} cellSize={1} sectionSize={10} cellColor="#1a1a2e" sectionColor="#2a2a3e" />
              <AutoFit meshes={meshes} />
              {meshes.map((m, i) => (
                <IFCMesh key={i} meshData={m} selected={selectedID === m.expressID} onClick={handleSelect} />
              ))}
            </Canvas>
          )}
        </div>

        {/* Properties Panel */}
        <div style={S.props}>
          <div style={{ fontWeight: 600, marginBottom: 8, color: "#D4A018" }}>Properties</div>
          {selectedID != null ? (
            Object.entries(properties).map(([k, v]) => (
              <div key={k} style={S.propRow}>
                <span style={S.propKey}>{k}</span>
                <span style={S.propVal}>{String(v)}</span>
              </div>
            ))
          ) : (
            <div style={{ color: "#666" }}>Click an element to inspect</div>
          )}
        </div>
      </div>

      <div style={S.status}>{status} | {meshes.length} meshes | {treeNodes.reduce((a, n) => a + (n.children?.length || 0), 0)} elements</div>
    </div>
  );
}

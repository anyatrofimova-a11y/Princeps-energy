import {Suspense, useMemo, useEffect, useRef} from 'react';
import {Canvas, useThree} from '@react-three/fiber';
import {OrbitControls, Edges, Text, Html, useGLTF, Bounds} from '@react-three/drei';
import {useQuery} from '@tanstack/react-query';
import {useSelection} from '../workshop/useSelection.jsx';

/**
 * TwinScene — procedural 3D rendering of any twin instance + its subtree.
 *
 * Strategy: pick a layout policy from the root DTMI, then walk the subgraph
 * recursively. Every mesh has `userData.rid` so click → setSelectedAssetRid.
 *
 * Layouts (W1 v1):
 *   • DataCentre: Hall(s) side-by-side. Each Hall contains Aisles as racks-rows.
 *   • BESSUnit:   Blocks side-by-side. Each Block contains Racks as cabinets.
 *   • default:    one box per node, stacked.
 */
export default function TwinScene({rid}) {
  const {data, isLoading, error} = useQuery({
    queryKey: ['twin-scene', rid],
    queryFn: async () => {
      const r = await fetch(`/api/workshop/scene/${encodeURIComponent(rid)}?hops=3`);
      if (!r.ok) throw new Error(`scene fetch ${r.status}`);
      return r.json();
    },
    enabled: Boolean(rid),
  });

  const {data: geometry} = useQuery({
    queryKey: ['twin-geometry', rid],
    queryFn: async () => {
      const r = await fetch(`/api/workshop/geometry/${encodeURIComponent(rid)}`);
      if (!r.ok) return null;
      return r.json();
    },
    enabled: Boolean(rid),
  });

  const {setSelectedAssetRid} = useSelection();
  const layout = useMemo(() => buildLayout(data, rid), [data, rid]);

  if (isLoading) return <div className="px-twin-placeholder">Loading 3D scene…</div>;
  if (error)     return <div className="px-twin-placeholder">3D scene error: {String(error)}</div>;
  if (!layout)   return <div className="px-twin-placeholder">No subgraph under {rid}</div>;

  const hasGlb = Boolean(geometry?.glb_url);

  return (
    <div style={{width: '100%', height: '100%', minHeight: 360}}>
      <Canvas
        shadows
        camera={{position: layout.cameraPos, fov: 42, near: 0.1, far: 2000}}
        gl={{antialias: true}}
        style={{background: 'linear-gradient(180deg, #FAFAF6 0%, #F2F3F5 100%)'}}
      >
        <ambientLight intensity={0.65} />
        <directionalLight position={[80, 120, 60]} intensity={0.7} castShadow shadow-mapSize={[1024, 1024]} />
        <hemisphereLight args={['#FDD85D', '#F2F3F5', 0.45]} />
        <gridHelper args={[200, 40, '#E8EAED', '#F2F3F5']} position={[0, -0.01, 0]} />

        <Suspense fallback={null}>
          {hasGlb ? (
            <Bounds fit clip observe margin={1.2}>
              <GltfTwin
                url={geometry.glb_url}
                bindings={geometry.bindings || {}}
                onPick={setSelectedAssetRid}
              />
            </Bounds>
          ) : (
            layout.boxes.map((b) => (
              <SceneBox key={b.rid} {...b} onClick={() => setSelectedAssetRid(b.rid)} />
            ))
          )}
        </Suspense>

        <OrbitControls makeDefault enablePan enableZoom enableRotate target={layout.target} maxDistance={500} minDistance={6} />
      </Canvas>
    </div>
  );
}


// ───────────────────────── GltfTwin ─────────────────────────
// Loads the converted IFC→glTF scene served at /static/glb/<id>.glb.
// Each mesh's userData typically includes the IFC GlobalId (set by the
// converter); we walk the tree on mount and tag each mesh's onClick to
// hand the matching Princeps RID back to the SelectionContext.

function GltfTwin({url, bindings, onPick}) {
  const {scene} = useGLTF(url);
  const {selectedAssetRid} = useSelection();

  // Apply Princeps light-theme materials.
  useEffect(() => {
    if (!scene) return;
    scene.traverse((obj) => {
      if (obj.isMesh && obj.material) {
        obj.castShadow = true;
        obj.receiveShadow = true;
        obj.material.transparent = true;
        obj.material.opacity = 0.85;
        obj.material.metalness = 0.05;
        obj.material.roughness = 0.65;
        // Cream tint for the body, gold-edged emissive on selection lookup.
        if (obj.material.color) obj.material.color.setHex(0xFAFAF6);
      }
    });
  }, [scene]);

  return (
    <primitive
      object={scene}
      onClick={(e) => {
        e.stopPropagation();
        // glTF serializer stuffs the IFC GlobalId into mesh.name. Resolve
        // through the bindings map handed in from /api/workshop/geometry.
        const globalId = e.object?.name;
        const binding = globalId && bindings ? bindings[globalId] : null;
        if (binding?.rid) {
          onPick?.(binding.rid);
        } else if (globalId) {
          // Fallback — selection still gets *something* visible in the
          // inspector even if the binding lookup misses.
          onPick?.(globalId);
        }
      }}
    />
  );
}


// ───────────────────────── SceneBox ─────────────────────────

function SceneBox({rid, label, position, size, color, alarm, opacity = 0.85, onClick}) {
  const meshRef = useRef();
  const {selectedAssetRid} = useSelection();
  const isSelected = selectedAssetRid === rid;

  return (
    <group position={position}>
      <mesh
        ref={meshRef}
        onClick={(e) => { e.stopPropagation(); onClick?.(); }}
        onPointerOver={(e) => { e.stopPropagation(); document.body.style.cursor = 'pointer'; }}
        onPointerOut={() => { document.body.style.cursor = ''; }}
        userData={{rid}}
        castShadow receiveShadow
      >
        <boxGeometry args={size} />
        <meshStandardMaterial
          color={alarm ? '#DC2626' : color}
          transparent opacity={alarm ? 0.92 : opacity}
          metalness={0.04}
          roughness={0.7}
          emissive={alarm ? '#DC2626' : '#000000'}
          emissiveIntensity={alarm ? 0.18 : 0}
        />
        <Edges threshold={12} color={isSelected ? '#E8A012' : '#A8AEB6'} lineWidth={isSelected ? 2 : 1} />
      </mesh>
      {label && size[1] >= 1.5 ? (
        <Text
          position={[0, size[1] / 2 + 0.5, 0]}
          fontSize={Math.max(0.4, Math.min(2, size[0] / 8))}
          color={isSelected ? '#E8A012' : '#4B5563'}
          anchorX="center" anchorY="middle"
        >
          {label}
        </Text>
      ) : null}
    </group>
  );
}


// ───────────────────────── Layout builders ─────────────────────────

function buildLayout(graph, rootRid) {
  if (!graph || !graph.nodes) return null;
  const root = graph.nodes.find((n) => n.rid === rootRid) ?? graph.nodes[0];
  if (!root) return null;

  if (root.dtmi === 'dtmi:com:princeps:DataCentre;1') {
    return buildDcLayout(graph, root);
  }
  if (root.dtmi === 'dtmi:com:princeps:BESSUnit;1') {
    return buildBessLayout(graph, root);
  }
  return buildGenericLayout(graph, root);
}

function buildDcLayout(graph, root) {
  // Halls along x-axis. Each hall: long shed shape with aisle stripes inside.
  const halls = childrenOf(graph, root.rid, 'containsHall');
  const HALL_W = 50, HALL_D = 30, HALL_H = 8, GAP = 8;
  const totalW = halls.length * HALL_W + (halls.length - 1) * GAP;
  const startX = -totalW / 2 + HALL_W / 2;

  const boxes = [];
  // Root campus footprint (very faint)
  boxes.push({
    rid: root.rid, label: root.label,
    position: [0, 0.05, 0],
    size: [totalW + 16, 0.1, HALL_D + 16],
    color: '#E8EAED', opacity: 0.6,
  });

  halls.forEach((hall, i) => {
    const cx = startX + i * (HALL_W + GAP);
    boxes.push({
      rid: hall.rid, label: hall.label,
      position: [cx, HALL_H / 2, 0],
      size: [HALL_W, HALL_H, HALL_D],
      color: '#FAFAF6', opacity: 0.32,
    });

    // Aisles along z-axis inside the hall
    const aisles = childrenOf(graph, hall.rid, 'containsAisle');
    const AISLE_W = HALL_W * 0.85;
    const AISLE_H = 2.4;
    const AISLE_D = 1.6;
    const aisleSpacing = HALL_D / (aisles.length + 1);
    aisles.forEach((aisle, j) => {
      const cz = -HALL_D / 2 + (j + 1) * aisleSpacing;
      const hotspot = aisle.properties?.hotspot === true;
      boxes.push({
        rid: aisle.rid, label: aisle.properties?.aisleId ?? aisle.label,
        position: [cx, AISLE_H / 2 + 0.2, cz],
        size: [AISLE_W, AISLE_H, AISLE_D],
        color: hotspot ? '#F97316' : '#94B7CC',
        alarm: hotspot,
        opacity: 0.92,
      });

      // Synthetic rack rendering — 24 mini boxes per aisle
      const RACKS_PER_AISLE = 24;
      const rackW = (AISLE_W - 2) / RACKS_PER_AISLE;
      const rackH = AISLE_H * 0.95;
      for (let k = 0; k < RACKS_PER_AISLE; k++) {
        const rx = cx - AISLE_W / 2 + 1 + (k + 0.5) * rackW;
        boxes.push({
          rid: `${aisle.rid}.rack-${k.toString().padStart(2, '0')}`,
          label: '',
          position: [rx, rackH / 2 + 0.2, cz],
          size: [rackW * 0.9, rackH, AISLE_D * 0.55],
          color: hotspot && k > RACKS_PER_AISLE - 8 ? '#DC2626' : '#5C8AAF',
          opacity: 0.88,
        });
      }
    });
  });

  return {
    boxes,
    cameraPos: [totalW * 0.7, 50, totalW * 0.7],
    target: [0, 4, 0],
  };
}

function buildBessLayout(graph, root) {
  // Blocks side-by-side as shipping containers. Each block holds rack-cabinets in a row.
  const blocks = childrenOf(graph, root.rid, 'containsBlock');
  const BLOCK_W = 12, BLOCK_D = 2.5, BLOCK_H = 2.6, GAP = 2;
  const totalW = blocks.length * BLOCK_W + (blocks.length - 1) * GAP;
  const startX = -totalW / 2 + BLOCK_W / 2;

  const boxes = [];
  boxes.push({
    rid: root.rid, label: root.label,
    position: [0, 0.05, 0],
    size: [totalW + 6, 0.1, BLOCK_D + 6],
    color: '#162028', opacity: 0.5,
  });

  blocks.forEach((block, i) => {
    const cx = startX + i * (BLOCK_W + GAP);
    const props = block.properties ?? {};
    const tooHot = (props.containerExhaustTempC ?? 0) > 30;
    boxes.push({
      rid: block.rid, label: props.blockId ?? block.label,
      position: [cx, BLOCK_H / 2, 0],
      size: [BLOCK_W, BLOCK_H, BLOCK_D],
      color: '#0EA5E9',
      alarm: tooHot,
      opacity: 0.7,
    });

    const racks = childrenOf(graph, block.rid, 'containsRack');
    const RACK_W = BLOCK_W * 0.06;
    racks.forEach((rack, j) => {
      const rx = cx - BLOCK_W / 2 + 0.6 + (j + 0.5) * (BLOCK_W - 1.2) / Math.max(racks.length, 1);
      const rprops = rack.properties ?? {};
      const imbalanceWarn = (rprops.imbalancePct ?? 0) > 2.5;
      boxes.push({
        rid: rack.rid, label: rprops.rackId ?? rack.label,
        position: [rx, BLOCK_H * 0.5, 0],
        size: [RACK_W, BLOCK_H * 0.9, BLOCK_D * 0.5],
        color: imbalanceWarn ? '#F97316' : '#22D3EE',
        alarm: imbalanceWarn,
        opacity: 0.95,
      });
    });
  });

  return {
    boxes,
    cameraPos: [totalW * 0.9, 8, totalW * 0.9],
    target: [0, 1.5, 0],
  };
}

function buildGenericLayout(graph, root) {
  const boxes = graph.nodes.map((n, i) => ({
    rid: n.rid,
    label: n.label,
    position: [(i % 5) * 4 - 8, 1, Math.floor(i / 5) * 4 - 4],
    size: [3, 2, 3],
    color: '#3B82F6',
  }));
  return {boxes, cameraPos: [20, 14, 20], target: [0, 1, 0]};
}

function childrenOf(graph, parentRid, relName) {
  const childRids = (graph.edges ?? [])
    .filter((e) => e.from_rid === parentRid && (!relName || e.rel_name === relName))
    .map((e) => e.to_rid);
  return childRids
    .map((cid) => graph.nodes.find((n) => n.rid === cid))
    .filter(Boolean);
}

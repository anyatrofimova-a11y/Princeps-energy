/**
 * SingleLineDiagram.jsx — SVG single-line for the BESS engineering panel.
 *
 * Layout: vertical stack
 *
 *   POC (HV)            ── grid voltage (132 kV by default)
 *     │
 *   GIS bay
 *     │
 *   Main TX (1..n)      ── one column per main step-up
 *     │
 *   33 kV MV switchboard (single horizontal bus)
 *    ╱│╲
 *   LV-MV TX × n
 *     │ each
 *   PCS
 *     │ each
 *   Battery block
 *
 * Uses design.single_line.{nodes,edges} produced by /api/twin/bess-design.
 * Fully self-contained — no external chart libs.
 */

import React, { useMemo } from 'react';

const COL_W = 140;       // column pitch
const ROW_H = 70;        // row pitch
const PAD_X = 28;
const PAD_Y = 28;
const NODE_W = 122;
const NODE_H = 38;

const VOLTAGE_FILL = (kv) => {
  if (kv >= 132) return '#5a3d12';
  if (kv >= 33)  return '#244068';
  if (kv >= 1)   return '#1f3a2c';
  return '#3a3a40';
};
const VOLTAGE_STROKE = (kv) => {
  if (kv >= 132) return '#d4a240';
  if (kv >= 33)  return '#508cdc';
  if (kv >= 1)   return '#76b582';
  return '#9aa1ad';
};

function nodeKey(n) {
  return n.id;
}

export default function SingleLineDiagram({ design, height = 480 }) {
  const layout = useMemo(() => {
    if (!design || !design.single_line) return null;
    const { nodes, edges } = design.single_line;
    if (!Array.isArray(nodes) || !nodes.length) return null;

    // Determine horizontal layout per role row.
    const byRole = {
      poc: [], switchgear: [], hv_tx: [], mv_bus: [], lvmv_tx: [], pcs: [], battery: [],
    };
    for (const n of nodes) {
      if (byRole[n.role]) byRole[n.role].push(n);
      else byRole.battery.push(n); // unknown roles fall to bottom row
    }

    // Order MV-LVMV chains so PCS and battery columns align with their LV-MV tx.
    const orderedLvmv = byRole.lvmv_tx.slice().sort((a, b) => (a.id < b.id ? -1 : 1));
    const orderedPcs = byRole.pcs
      .slice()
      .sort((a, b) => Number(a.id.split('_').pop()) - Number(b.id.split('_').pop()));
    const orderedBat = byRole.battery
      .slice()
      .sort((a, b) => Number(a.id.split('_').pop()) - Number(b.id.split('_').pop()));

    const positions = {};
    const setRow = (arr, y) => {
      const n = arr.length;
      const totalW = Math.max(1, (n - 1)) * COL_W;
      const x0 = PAD_X + (totalW > 0 ? 0 : 0);
      arr.forEach((node, i) => {
        const x = PAD_X + (n === 1 ? 0 : i * COL_W);
        positions[nodeKey(node)] = { x, y, node };
      });
      return totalW;
    };
    let y = PAD_Y;
    setRow(byRole.poc, y); y += ROW_H;
    setRow(byRole.switchgear, y); y += ROW_H;
    setRow(byRole.hv_tx, y); y += ROW_H;
    setRow(byRole.mv_bus, y); y += ROW_H;
    setRow(orderedLvmv, y); y += ROW_H;
    setRow(orderedPcs, y); y += ROW_H;
    setRow(orderedBat, y); y += ROW_H;

    const totalW = Math.max(
      ...Object.values(positions).map((p) => p.x),
    ) + NODE_W + PAD_X;
    const totalH = y + PAD_Y;
    return { positions, edges, totalW, totalH };
  }, [design]);

  if (!layout) {
    return (
      <div style={{ color: '#999', fontSize: 12, padding: 12 }}>
        single-line: no design yet
      </div>
    );
  }

  const { positions, edges, totalW, totalH } = layout;

  return (
    <div style={{ width: '100%', overflow: 'auto', background: '#0c0e12', borderRadius: 8 }}>
      <svg
        viewBox={`0 0 ${totalW} ${totalH}`}
        width="100%"
        style={{ display: 'block', minHeight: height, fontFamily: 'system-ui, sans-serif' }}
      >
        {/* edges first so nodes paint on top */}
        {edges.map((e, i) => {
          const a = positions[e.from_id];
          const b = positions[e.to_id];
          if (!a || !b) return null;
          const ax = a.x + NODE_W / 2;
          const ay = a.y + NODE_H;
          const bx = b.x + NODE_W / 2;
          const by = b.y;
          const stroke = VOLTAGE_STROKE(Number(e.voltage_kv) || 0);
          const dash = e.role === 'dc_string' ? '4 3' : '0';
          return (
            <g key={`edge-${i}`}>
              <path
                d={`M ${ax} ${ay} L ${ax} ${(ay + by) / 2} L ${bx} ${(ay + by) / 2} L ${bx} ${by}`}
                fill="none"
                stroke={stroke}
                strokeWidth={1.6}
                strokeDasharray={dash}
                opacity={0.85}
              />
            </g>
          );
        })}
        {/* nodes */}
        {Object.values(positions).map(({ x, y, node }) => {
          const fill = VOLTAGE_FILL(Number(node.voltage_kv) || 0);
          const stroke = VOLTAGE_STROKE(Number(node.voltage_kv) || 0);
          return (
            <g key={node.id} transform={`translate(${x} ${y})`}>
              <rect
                width={NODE_W}
                height={NODE_H}
                rx={5}
                ry={5}
                fill={fill}
                stroke={stroke}
                strokeWidth={1.2}
              />
              <text
                x={NODE_W / 2}
                y={16}
                textAnchor="middle"
                fontSize={10.5}
                fill="#f5b731"
                fontWeight={600}
              >
                {node.label.length > 22 ? node.label.slice(0, 21) + '…' : node.label}
              </text>
              <text
                x={NODE_W / 2}
                y={29}
                textAnchor="middle"
                fontSize={9.5}
                fill="#cbd1dc"
              >
                {node.voltage_kv ? `${node.voltage_kv} kV` : ''}
                {node.role ? ` · ${node.role}` : ''}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

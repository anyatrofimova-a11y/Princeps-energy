import React, { useMemo, useState } from "react";
import { COLOURS, POSITION_BADGE, ROLE_LABEL, ROLE_RINGS, SANS, MONO } from "./tokens";

// Custom SVG concentric-ring stakeholder graph. SPV at centre (gold),
// role rings expand outward. Each node: 48 px with initials, submission
// count pill, and position badge. Accessibility toggle flips to table view.
export default function StakeholderGraph({ stakeholders = [], onSelect, selectedId }) {
  const [view, setView] = useState("graph"); // "graph" | "table"

  if (!stakeholders.length) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: COLOURS.muted, fontSize: 13 }}>
        No stakeholders yet.
      </div>
    );
  }

  return (
    <section
      style={{
        background: "#FFFFFF",
        border: `1px solid ${COLOURS.border}`,
        borderRadius: 8,
        padding: 20,
        fontFamily: SANS,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: COLOURS.ink, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Stakeholders <span style={{ color: COLOURS.muted, fontWeight: 500 }}>({stakeholders.length})</span>
        </h3>
        <div style={{ display: "inline-flex", border: `1px solid ${COLOURS.border}`, borderRadius: 4, overflow: "hidden" }}>
          <TabBtn active={view === "graph"} onClick={() => setView("graph")}>Graph</TabBtn>
          <TabBtn active={view === "table"} onClick={() => setView("table")}>Table</TabBtn>
        </div>
      </div>

      {view === "graph" ? (
        <GraphView stakeholders={stakeholders} onSelect={onSelect} selectedId={selectedId} />
      ) : (
        <TableView stakeholders={stakeholders} onSelect={onSelect} selectedId={selectedId} />
      )}

      {/* Legend */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 14, paddingTop: 12, borderTop: `1px solid ${COLOURS.border}` }}>
        {Object.entries(POSITION_BADGE).map(([k, v]) => (
          <span key={k} style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11, color: COLOURS.inkSoft }}>
            <span style={{ width: 10, height: 10, background: v.bg, borderRadius: 2, display: "inline-block" }} />
            {v.label}
          </span>
        ))}
      </div>
    </section>
  );
}

function TabBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "4px 12px",
        fontSize: 11.5,
        fontWeight: 600,
        background: active ? COLOURS.gold : "#FFFFFF",
        color: COLOURS.ink,
        border: "none",
        cursor: "pointer",
        fontFamily: SANS,
      }}
    >
      {children}
    </button>
  );
}

// ── Graph view ──────────────────────────────────────────────────
function GraphView({ stakeholders, onSelect, selectedId }) {
  // Partition into rings.
  const rings = useMemo(() => {
    const byRole = {};
    for (const r of ROLE_RINGS) byRole[r] = [];
    for (const s of stakeholders) {
      const role = ROLE_RINGS.includes(s.role) ? s.role : "statutory";
      byRole[role].push(s);
    }
    // Keep applicant at the centre (ring 0); others fan out.
    return byRole;
  }, [stakeholders]);

  const width = 900;
  const height = 720;
  const cx = width / 2;
  const cy = height / 2;
  const ringSpacing = 74;

  const applicants = rings.applicant || [];
  const ringsOrder = ROLE_RINGS.filter((r) => r !== "applicant");

  const nodes = [];
  applicants.forEach((s, i) => {
    // If more than one applicant, cluster them around centre at small radius.
    const r = applicants.length === 1 ? 0 : 28;
    const theta = (2 * Math.PI * i) / Math.max(1, applicants.length) - Math.PI / 2;
    nodes.push({ ...s, x: cx + r * Math.cos(theta), y: cy + r * Math.sin(theta), isCentre: applicants.length === 1 });
  });

  ringsOrder.forEach((roleKey, ringIdx) => {
    const ringNodes = rings[roleKey] || [];
    if (!ringNodes.length) return;
    const radius = ringSpacing * (ringIdx + 1);
    ringNodes.forEach((s, i) => {
      const theta = (2 * Math.PI * i) / ringNodes.length - Math.PI / 2;
      nodes.push({ ...s, x: cx + radius * Math.cos(theta), y: cy + radius * Math.sin(theta), isCentre: false });
    });
  });

  return (
    <div style={{ position: "relative", width: "100%", overflow: "auto" }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: "auto", display: "block" }} role="img" aria-label="Stakeholder graph">
        {/* Ring guides */}
        {ringsOrder.map((roleKey, ringIdx) => {
          if (!rings[roleKey] || rings[roleKey].length === 0) return null;
          const radius = ringSpacing * (ringIdx + 1);
          return (
            <g key={roleKey}>
              <circle cx={cx} cy={cy} r={radius} fill="none" stroke={COLOURS.border} strokeDasharray="4 4" />
              <text x={cx} y={cy - radius - 4} textAnchor="middle" fontSize="10" fill={COLOURS.muted} fontFamily={SANS} style={{ textTransform: "uppercase", letterSpacing: 0.4 }}>
                {ROLE_LABEL[roleKey]}
              </text>
            </g>
          );
        })}

        {/* Connector lines from centre */}
        {nodes.filter((n) => !n.isCentre).map((n) => (
          <line
            key={`l_${n.id}`}
            x1={cx}
            y1={cy}
            x2={n.x}
            y2={n.y}
            stroke={COLOURS.border}
            strokeWidth="1"
            opacity="0.5"
          />
        ))}

        {/* Nodes */}
        {nodes.map((n) => (
          <Node key={n.id} node={n} selected={n.id === selectedId} onSelect={onSelect} />
        ))}
      </svg>
    </div>
  );
}

function Node({ node, selected, onSelect }) {
  const pos = POSITION_BADGE[node.position] || POSITION_BADGE.neutral;
  const isCentre = node.isCentre;
  const r = isCentre ? 36 : 24;
  const fill = isCentre ? COLOURS.gold : "#FFFFFF";
  const stroke = selected ? COLOURS.gold : isCentre ? COLOURS.goldDeep : COLOURS.border;
  const strokeWidth = selected ? 3 : isCentre ? 2 : 1.5;

  return (
    <g
      transform={`translate(${node.x}, ${node.y})`}
      onClick={() => onSelect && onSelect(node)}
      style={{ cursor: "pointer" }}
    >
      <circle r={r} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
      <text
        y={isCentre ? 2 : 1}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={isCentre ? 14 : 11}
        fontWeight="700"
        fill={isCentre ? COLOURS.ink : COLOURS.ink}
        fontFamily={SANS}
      >
        {node.logo_initials || (node.name || "?").slice(0, 2).toUpperCase()}
      </text>

      {/* Submission count pill (top-right) */}
      {!isCentre && node.submission_count > 0 && (
        <g transform={`translate(${r - 4}, ${-r + 4})`}>
          <circle r={9} fill={COLOURS.ink} />
          <text textAnchor="middle" dominantBaseline="middle" fontSize="9" fontWeight="700" fill="#FFF" fontFamily={MONO}>
            {node.submission_count > 99 ? "99+" : node.submission_count}
          </text>
        </g>
      )}

      {/* Position badge (bottom-right) */}
      {!isCentre && (
        <g transform={`translate(${r - 4}, ${r - 4})`}>
          <circle r={6} fill={pos.bg} stroke="#FFFFFF" strokeWidth="1.5" />
        </g>
      )}

      {/* Name label below node */}
      <text y={r + 12} textAnchor="middle" fontSize="10.5" fill={COLOURS.ink} fontFamily={SANS} fontWeight={isCentre ? 700 : 500}>
        {truncate(node.name || "", isCentre ? 20 : 14)}
      </text>
    </g>
  );
}

function truncate(s, n) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// ── Table view ──────────────────────────────────────────────────
function TableView({ stakeholders, onSelect, selectedId }) {
  return (
    <div style={{ maxHeight: 560, overflowY: "auto", border: `1px solid ${COLOURS.border}`, borderRadius: 6 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: SANS }}>
        <thead>
          <tr style={{ background: COLOURS.ivory, position: "sticky", top: 0 }}>
            {["Name", "Role", "Position", "Submissions"].map((h) => (
              <th
                key={h}
                style={{
                  textAlign: "left",
                  padding: "8px 12px",
                  fontSize: 11,
                  fontWeight: 700,
                  color: COLOURS.muted,
                  textTransform: "uppercase",
                  letterSpacing: 0.4,
                  borderBottom: `1px solid ${COLOURS.border}`,
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stakeholders.map((s) => {
            const pos = POSITION_BADGE[s.position] || POSITION_BADGE.neutral;
            return (
              <tr
                key={s.id}
                onClick={() => onSelect && onSelect(s)}
                style={{
                  cursor: "pointer",
                  background: s.id === selectedId ? "rgba(245,183,49,.10)" : "#FFFFFF",
                }}
              >
                <td style={{ padding: "8px 12px", fontSize: 13, color: COLOURS.ink, borderBottom: `1px solid ${COLOURS.border}`, fontWeight: 500 }}>
                  {s.name}
                </td>
                <td style={{ padding: "8px 12px", fontSize: 12, color: COLOURS.inkSoft, borderBottom: `1px solid ${COLOURS.border}` }}>
                  {ROLE_LABEL[s.role] || s.role}
                </td>
                <td style={{ padding: "8px 12px", borderBottom: `1px solid ${COLOURS.border}` }}>
                  <span
                    style={{
                      padding: "2px 8px",
                      fontSize: 10.5,
                      fontWeight: 600,
                      color: pos.fg,
                      background: pos.bg,
                      borderRadius: 10,
                      textTransform: "uppercase",
                      letterSpacing: 0.4,
                    }}
                  >
                    {pos.label}
                  </span>
                </td>
                <td style={{ padding: "8px 12px", fontFamily: MONO, fontSize: 12, color: COLOURS.ink, borderBottom: `1px solid ${COLOURS.border}` }}>
                  {s.submission_count}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * NeighbourhoodRail — 40-px vertical sidecar between the map and the
 * GridAssetDrawer that shows voltage-coloured chips for the root
 * substation + its electrical/geo neighbourhood.
 *
 * Spec: docs/audits/connection_nodes_spec.md §6 (BOT-CN-M brief).
 *
 *   ┌──┐
 *   │ 2│   hop-depth picker (1/2/3)  — header
 *   ├──┤
 *   │●R│   root chip — gold border, larger
 *   ├──┤
 *   │HV│   chip per related node, sorted by voltage DESC + headroom DESC
 *   │BS│   voltage-coloured dot + 2-letter code + tiny headroom bar
 *   │CA│
 *   │ ⋮│
 *   ├──┤
 *   │+N│   truncation hint if backend flagged _truncated
 *   ├──┤
 *   │ ✕│   reset pill — clears selection back to full map
 *   └──┘
 *
 * Interaction contract:
 *   - Hover a chip → pulses the map node by publishing to
 *     window.__gridGraphHover(info). Uses the same publisher BOT-GL
 *     wired up for deck.gl hover tooltips so the tip overlay picks it up.
 *   - Click a chip → calls onReroot(nodeId) so the container swaps the
 *     neighbourhood root and re-fetches.
 *   - Click reset → calls onReset().
 *   - Depth radio → calls onDepthChange(depth).
 *
 * OWNED by BOT-CN-M. Imports palette from ./gridPalette only.
 */
import React, { useMemo } from "react";
import { getVoltageColor, rgbToCss } from "./gridPalette";

const RAIL_WIDTH = 40;

const styles = {
  rail: {
    width: RAIL_WIDTH,
    flexShrink: 0,
    height: "100%",
    background: "#ffffff",
    borderLeft: "1px solid #e8e5df",
    borderRight: "1px solid #e8e5df",
    display: "flex",
    flexDirection: "column",
    alignItems: "stretch",
    overflow: "hidden",
    fontFamily: "'DM Sans', system-ui, sans-serif",
  },
  header: {
    borderBottom: "1px solid #f0ece4",
    padding: "6px 0 4px",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 3,
  },
  headerLabel: {
    fontSize: 8,
    fontWeight: 700,
    letterSpacing: 0.4,
    color: "#9c9590",
    textTransform: "uppercase",
  },
  depthRow: {
    display: "flex",
    gap: 1,
    marginTop: 2,
  },
  depthBtn: (active) => ({
    width: 10,
    height: 16,
    padding: 0,
    fontSize: 9,
    fontWeight: 700,
    border: "none",
    borderRadius: 2,
    cursor: "pointer",
    background: active ? "#C9A64B" : "transparent",
    color: active ? "#fff" : "#9c9590",
    fontFamily: "inherit",
  }),
  list: {
    flex: 1,
    overflowY: "auto",
    overflowX: "hidden",
    padding: "4px 0",
    display: "flex",
    flexDirection: "column",
    gap: 2,
    scrollbarWidth: "thin",
  },
  chip: (isRoot, voltageCss) => ({
    margin: "0 2px",
    height: 28,
    minHeight: 28,
    borderRadius: 4,
    border: isRoot ? `1.5px solid #C9A64B` : `1px solid ${voltageCss}`,
    background: isRoot ? "rgba(201,166,75,0.12)" : "#ffffff",
    cursor: "pointer",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    padding: "2px 0",
    gap: 1,
    position: "relative",
  }),
  code: {
    fontSize: 9,
    fontWeight: 700,
    color: "#1a1a1a",
    lineHeight: 1,
    letterSpacing: 0.2,
    fontFamily: "'JetBrains Mono', monospace",
  },
  voltageBadge: (voltageCss) => ({
    fontSize: 7,
    fontWeight: 700,
    color: voltageCss,
    lineHeight: 1,
  }),
  headroomBar: (frac) => ({
    width: 22,
    height: 2,
    background: "#f0ece4",
    borderRadius: 1,
    position: "relative",
    overflow: "hidden",
    marginTop: 1,
  }),
  headroomFill: (frac) => ({
    position: "absolute",
    left: 0,
    top: 0,
    bottom: 0,
    width: `${Math.max(0, Math.min(1, frac)) * 100}%`,
    background:
      frac >= 0.3 ? "#46b482" : frac >= 0.1 ? "#dca03c" : "#d25050",
  }),
  truncHint: {
    padding: "6px 4px",
    textAlign: "center",
    fontSize: 8,
    color: "#9c9590",
    fontWeight: 600,
    fontFamily: "'JetBrains Mono', monospace",
  },
  footer: {
    borderTop: "1px solid #f0ece4",
    padding: 4,
    display: "flex",
    justifyContent: "center",
  },
  resetBtn: {
    width: "100%",
    padding: "4px 0",
    background: "transparent",
    border: "1px dashed #e8e5df",
    borderRadius: 3,
    cursor: "pointer",
    color: "#9c9590",
    fontSize: 9,
    fontWeight: 700,
    fontFamily: "inherit",
    letterSpacing: 0.3,
  },
  loading: {
    padding: "12px 4px",
    fontSize: 9,
    color: "#9c9590",
    textAlign: "center",
    fontStyle: "italic",
  },
  error: {
    padding: "12px 4px",
    fontSize: 9,
    color: "#b91c1c",
    textAlign: "center",
  },
};

/** Pull a 2-character code out of a substation name. */
function shortCode(name, fallbackId) {
  if (!name) return String(fallbackId || "??").slice(0, 2).toUpperCase();
  // Take first letter of each whitespace-split word, up to 2 chars
  const parts = name.split(/[\s_\-]+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

/** Compute fractional headroom (0..1) for the tiny bar on each chip. */
function headroomFraction(node) {
  const firm = Number(node.firm_capacity_mw || 0);
  const head = Number(node.headroom_mw ?? 0);
  if (firm <= 0) return 0.5; // unknown → neutral
  return Math.max(0, Math.min(1, head / firm));
}

export default function NeighbourhoodRail({
  data,                     // normalised payload from useGridNeighbourhood
  loading = false,
  error = null,
  depth = 2,
  onDepthChange,
  onReroot,
  onReset,
  onHoverNode,              // optional — tests / future callers
}) {
  // Sort related nodes: highest voltage first, then highest headroom.
  const sortedNodes = useMemo(() => {
    if (!data?.nodes?.length) return [];
    return [...data.nodes].sort((a, b) => {
      const dv = (b.voltage_kv || 0) - (a.voltage_kv || 0);
      if (dv !== 0) return dv;
      return (b.headroom_mw || 0) - (a.headroom_mw || 0);
    });
  }, [data]);

  const hoverPublish = (node) => {
    if (onHoverNode) onHoverNode(node);
    if (typeof window !== "undefined" && typeof window.__gridGraphHover === "function") {
      if (!node) {
        window.__gridGraphHover(null);
        return;
      }
      // Fabricate a deck.gl PickingInfo-shape the existing tooltip expects.
      window.__gridGraphHover({
        object: {
          id: node.id,
          name: node.name,
          voltage_kv: node.voltage_kv,
          lat: node.lat,
          lon: node.lon,
          dno: node.dno,
          headroom_mw: node.headroom_mw,
        },
        x: 0,
        y: 0,
        layer: { id: "grid-neighbourhood-nodes-glow" },
        coordinate: [node.lon, node.lat],
      });
    }
  };

  return (
    <aside style={styles.rail} aria-label="Neighbourhood rail">
      {/* Header — hop-depth picker */}
      <div style={styles.header}>
        <span style={styles.headerLabel}>HOP</span>
        <div style={styles.depthRow} role="radiogroup" aria-label="Hop depth">
          {[1, 2, 3].map((d) => (
            <button
              key={d}
              role="radio"
              aria-checked={depth === d}
              onClick={() => onDepthChange?.(d)}
              style={styles.depthBtn(depth === d)}
              title={`Depth ${d}`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      {/* List body */}
      <div style={styles.list}>
        {loading && <div style={styles.loading}>…</div>}
        {error && !loading && <div style={styles.error}>!</div>}

        {/* Root chip (first, larger, gold) */}
        {data?.root && (
          <button
            onClick={() => onReroot?.(data.root.id)} // clicking root re-fetches / no-ops
            onMouseEnter={() => hoverPublish(data.root)}
            onMouseLeave={() => hoverPublish(null)}
            style={{
              ...styles.chip(true, rgbToCss(getVoltageColor(data.root.voltage_kv))),
              height: 34,
              minHeight: 34,
            }}
            title={`${data.root.name || data.root.id} — ${data.root.voltage_kv} kV (root)`}
          >
            <span style={styles.code}>{shortCode(data.root.name, data.root.id)}</span>
            <span style={styles.voltageBadge(rgbToCss(getVoltageColor(data.root.voltage_kv)))}>
              {data.root.voltage_kv || "?"}
            </span>
          </button>
        )}

        {/* Related node chips */}
        {sortedNodes.map((n) => {
          const voltageCss = rgbToCss(getVoltageColor(n.voltage_kv));
          const frac = headroomFraction(n);
          return (
            <button
              key={n.id}
              onClick={() => onReroot?.(n.id)}
              onMouseEnter={() => hoverPublish(n)}
              onMouseLeave={() => hoverPublish(null)}
              style={styles.chip(false, voltageCss)}
              title={`${n.name || n.id} — ${n.voltage_kv} kV · hop ${n.hop}${
                n.electrical ? "" : " · geo only"
              }${n.headroom_mw != null ? ` · ${Math.round(n.headroom_mw)} MW free` : ""}`}
            >
              <span style={styles.code}>{shortCode(n.name, n.id)}</span>
              <span style={styles.voltageBadge(voltageCss)}>
                {n.voltage_kv || "?"}
              </span>
              {n.firm_capacity_mw ? (
                <div style={styles.headroomBar(frac)}>
                  <div style={styles.headroomFill(frac)} />
                </div>
              ) : null}
            </button>
          );
        })}

        {/* Truncation hint */}
        {data?._truncated && (
          <div style={styles.truncHint}>
            … +N
          </div>
        )}
      </div>

      {/* Footer — reset */}
      <div style={styles.footer}>
        <button
          onClick={onReset}
          style={styles.resetBtn}
          title="Clear neighbourhood highlight (Esc)"
        >
          ✕
        </button>
      </div>
    </aside>
  );
}

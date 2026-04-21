/**
 * GridGraphHoverTip — DOM hover tooltip for the Grid Graph view.
 *
 * OWNED by BOT-GL. Renders a compact popover at the cursor's screen position
 * for whatever feature BOT-GO's deck.gl `onHover` callback surfaces.
 *
 * Expected input shape (mirrors deck.gl's PickingInfo):
 *
 *   info = {
 *     x, y,                              // CSS-px, deck.gl-provided
 *     coordinate: [lon, lat],            // optional
 *     layer: { id: "grid-graph-..." },   // which layer produced this pick
 *     object: { ...substation-or-line }  // the feature itself
 *   }
 *
 * Layer id convention (agreed with BOT-GO):
 *   • "grid-graph-substations"     → substation shape, show substation card
 *   • "grid-graph-lines"           → line shape, show line card
 *   • any id starting with "grid-graph-" else → fallback KV card
 *
 * Field contract reuses the `GridAssetDrawer` ontology so a hover and a
 * click read identically:
 *   substation: { name, dno, voltage_kv, firm_capacity_mw,
 *                 demand_headroom_mw, gen_headroom_mw, queue_summary }
 *   line:       { from_substation, to_substation, voltage_kv, length_km,
 *                 operator }
 *
 * The component is position: fixed so it ignores scroll containers.
 */
import React from "react";

const PAL = {
  bg:       "rgba(15, 23, 42, 0.96)",   // slate-900 @ 96% — matches legacy tip
  bgSoft:   "rgba(30, 41, 59, 0.96)",
  ink:      "#f8fafc",
  inkDim:   "#cbd5e1",
  inkMuted: "#94a3b8",
  green:    "#4ade80",
  amber:    "#fbbf24",
  red:      "#f87171",
  border:   "rgba(255,255,255,0.08)",
};

const S = {
  root: (x, y) => ({
    position: "fixed",
    left: Math.min(x + 14, (typeof window !== "undefined" ? window.innerWidth : 1200) - 260),
    top:  Math.max(8, y - 12),
    minWidth: 200,
    maxWidth: 260,
    padding: "10px 12px",
    background: PAL.bg,
    color: PAL.ink,
    borderRadius: 8,
    border: `1px solid ${PAL.border}`,
    boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
    fontFamily: "'DM Sans', 'Inter', system-ui, sans-serif",
    fontSize: 11,
    lineHeight: 1.4,
    pointerEvents: "none",   // never interferes with deck.gl hover
    zIndex: 5000,
    backdropFilter: "blur(6px)",
  }),
  kindPill: {
    display: "inline-block",
    padding: "1px 6px",
    fontSize: 9,
    fontWeight: 700,
    letterSpacing: 0.5,
    textTransform: "uppercase",
    background: "rgba(201,166,75,0.25)",
    color: "#f5e9c8",
    borderRadius: 10,
    marginBottom: 4,
    fontFamily: "'JetBrains Mono', monospace",
  },
  title: {
    fontWeight: 700,
    fontSize: 13,
    color: PAL.ink,
    lineHeight: 1.25,
    letterSpacing: "-0.01em",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  sub: {
    fontSize: 10,
    color: PAL.inkMuted,
    marginTop: 2,
    fontFamily: "'JetBrains Mono', monospace",
  },
  row: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    gap: 8,
    marginTop: 4,
    fontSize: 11,
  },
  label: {
    color: PAL.inkMuted,
    fontSize: 9,
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  val: (tone = "ink") => ({
    fontFamily: "'JetBrains Mono', monospace",
    fontWeight: 700,
    color: tone === "green" ? PAL.green
         : tone === "amber" ? PAL.amber
         : tone === "red"   ? PAL.red
         : PAL.ink,
  }),
  divider: {
    height: 1,
    background: PAL.border,
    margin: "8px -12px",
  },
  footer: {
    marginTop: 8,
    fontSize: 9,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    color: PAL.inkMuted,
  },
};

function fmt(n, { dp = 0, suffix = "" } = {}) {
  if (n == null || n === "") return "—";
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  return `${v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })}${suffix}`;
}

/** Heuristic RAG tone for headroom (matches legend semantics exactly). */
function headroomTone(headroom_mw, firm_mw) {
  if (headroom_mw == null || !firm_mw) return "ink";
  const pct = (headroom_mw / firm_mw) * 100;
  if (pct > 30) return "green";
  if (pct > 10) return "amber";
  return "red";
}

function SubstationCard({ f }) {
  const p = f || {};
  // The hover payload can come through as either the enriched detail
  // shape OR the flat index row. We accept both.
  const name    = p.name || p.external_id || p.id || "Unnamed";
  const dno     = p.dno || p.operator || p.owner;
  const volt    = p.voltage_kv != null ? `${Math.round(p.voltage_kv)} kV` : null;
  const firm    = p.firm_capacity_mw ?? p.firm_mw ?? null;
  const demHR   = p.demand_headroom_mw ?? p.headroom_mw ?? null;
  const genHR   = p.gen_headroom_mw ?? p.generation_headroom_mw ?? null;
  const queue   = p.queue_summary
                ?? (p.accepted_queue_mw != null || p.in_progress_queue_mw != null
                    ? `${fmt(p.accepted_queue_mw, { dp: 0 })} acc · ${fmt(p.in_progress_queue_mw, { dp: 0 })} prog (MW)`
                    : null);
  const tone = headroomTone(demHR, firm);

  return (
    <div>
      <div style={S.kindPill}>Substation</div>
      <div style={S.title} title={name}>{name}</div>
      <div style={S.sub}>{[dno, volt].filter(Boolean).join(" · ") || "—"}</div>

      <div style={S.divider} />

      <div style={S.row}>
        <span style={S.label}>Firm capacity</span>
        <span style={S.val()}>{fmt(firm, { dp: 1, suffix: " MW" })}</span>
      </div>
      <div style={S.row}>
        <span style={S.label}>Demand headroom</span>
        <span style={S.val(tone)}>{fmt(demHR, { dp: 1, suffix: " MW" })}</span>
      </div>
      <div style={S.row}>
        <span style={S.label}>Gen headroom</span>
        <span style={S.val()}>{fmt(genHR, { dp: 1, suffix: " MW" })}</span>
      </div>
      {queue && (
        <div style={S.row}>
          <span style={S.label}>Queue</span>
          <span style={S.val()}>{queue}</span>
        </div>
      )}

      <div style={S.footer}>Click for full detail</div>
    </div>
  );
}

function LineCard({ f }) {
  const p = f || {};
  const from = p.from_substation || p.from_name || p.from || null;
  const to   = p.to_substation   || p.to_name   || p.to   || null;
  const voltage = p.voltage_kv != null ? `${Math.round(p.voltage_kv)} kV` : "—";
  const length  = p.length_km != null ? `${Number(p.length_km).toFixed(1)} km` : "—";
  const operator = p.operator || p.owner || "—";
  const header = from && to ? `${from} → ${to}` : (p.name || p.id || "Circuit");

  return (
    <div>
      <div style={S.kindPill}>Line</div>
      <div style={S.title} title={header}>{header}</div>
      <div style={S.sub}>{operator}</div>

      <div style={S.divider} />

      <div style={S.row}>
        <span style={S.label}>Voltage</span>
        <span style={S.val()}>{voltage}</span>
      </div>
      <div style={S.row}>
        <span style={S.label}>Length</span>
        <span style={S.val()}>{length}</span>
      </div>
      <div style={S.row}>
        <span style={S.label}>Operator</span>
        <span style={S.val()}>{operator}</span>
      </div>
    </div>
  );
}

function FallbackCard({ f, kind }) {
  if (!f) return <div style={S.title}>—</div>;
  const rows = Object.entries(f)
    .filter(([k, v]) => v != null && v !== "" && !k.startsWith("_"))
    .slice(0, 6);
  return (
    <div>
      <div style={S.kindPill}>{kind || "Feature"}</div>
      <div style={S.title}>{f.name || f.id || kind || "Feature"}</div>
      <div style={S.divider} />
      {rows.map(([k, v]) => (
        <div key={k} style={S.row}>
          <span style={S.label}>{k.replace(/_/g, " ")}</span>
          <span style={S.val()}>{String(v).slice(0, 24)}</span>
        </div>
      ))}
    </div>
  );
}

/** Classify a deck.gl PickingInfo into a hover card kind. */
function classify(info) {
  const id = info?.layer?.id || "";
  if (id.includes("line")) return "line";
  if (id.includes("substation") || id.includes("label")) return "substation";
  if (info?.object?.from_substation || info?.object?.to_substation) return "line";
  return "substation";
}

/**
 * The tooltip itself.
 *
 * @param {object}  props
 * @param {object=} props.info  deck.gl PickingInfo (or null to hide)
 */
export default function GridGraphHoverTip({ info }) {
  if (!info || !info.object) return null;
  const kind = classify(info);
  const x = info.x ?? 0;
  const y = info.y ?? 0;

  return (
    <div style={S.root(x, y)} role="tooltip" aria-live="polite">
      {kind === "substation" && <SubstationCard f={info.object} />}
      {kind === "line"       && <LineCard       f={info.object} />}
      {kind !== "substation" && kind !== "line" &&
        <FallbackCard f={info.object} kind={kind} />}
    </div>
  );
}

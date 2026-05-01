// ModuleRuntime.jsx — renders a Workshop Module Builder manifest as a
// 12-column CSS grid. Mounted at /v2/modules/:id.
//
// Princeps tokens — cream + gold, NOT Foundry-dark:
//   bg     : #FBF8F2
//   accent : #F5B731
//   text   : #0F1318
//   font   : DM Sans (UI), JetBrains Mono (numbers)
//   shadow : 0 4px 24px rgba(15,19,24,0.08)
//
// Widget kinds: ObjectCard | ObjectTable | Chart | Map | Markdown | ActionButton
// Bindings use ${variable.field} template syntax — resolved without eval().

import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

const TOKENS = {
  bg: "#FBF8F2",
  card: "#FFFFFF",
  accent: "#F5B731",
  text: "#0F1318",
  muted: "#5B6470",
  border: "rgba(15,19,24,0.08)",
  shadow: "0 4px 24px rgba(15,19,24,0.08)",
  fontUi: "'DM Sans', -apple-system, sans-serif",
  fontMono: "'JetBrains Mono', ui-monospace, monospace",
};

// ── ${var.path} template parser — no eval, just regex + dotted lookup. ──
const TPL_RX = /\$\{([^}]+)\}/g;
function lookup(scope, path) {
  if (!path) return undefined;
  return path.split(".").reduce((acc, k) => (acc == null ? acc : acc[k]), scope);
}
function resolveTpl(tpl, scope) {
  if (typeof tpl !== "string") return tpl;
  const matches = [...tpl.matchAll(TPL_RX)];
  if (!matches.length) return tpl;
  // Single-token bindings keep their typed value. Multi-token = stringified.
  if (matches.length === 1 && matches[0][0] === tpl) {
    const v = lookup(scope, matches[0][1].trim());
    return v === undefined ? tpl : v;
  }
  return tpl.replace(TPL_RX, (_, k) => {
    const v = lookup(scope, k.trim());
    return v === undefined ? "" : String(v);
  });
}
function resolveBindings(bindings, scope) {
  const out = {};
  for (const [k, v] of Object.entries(bindings || {})) out[k] = resolveTpl(v, scope);
  return out;
}

// ── Widget renderers ─────────────────────────────────────────────────────
function ObjectCard({ widget, resolved }) {
  const { props } = widget;
  const fields = Array.isArray(props?.fields) ? props.fields : [];
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{props?.title || widget.id}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12 }}>
        {fields.slice(0, 4).map((f, i) => (
          <div key={i} style={{ padding: 12, background: TOKENS.bg, borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: TOKENS.muted, marginBottom: 4, fontFamily: TOKENS.fontUi }}>
              {f.label || f.key}
            </div>
            <div style={{ fontSize: 18, color: TOKENS.text, fontFamily: TOKENS.fontMono, fontWeight: 500 }}>
              {fmt(resolved[f.key] ?? f.fallback ?? "—")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ObjectTable({ widget, resolved }) {
  const { props } = widget;
  const cols = Array.isArray(props?.columns) ? props.columns : [];
  const rows = Array.isArray(resolved.rows) ? resolved.rows : [];
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{props?.title || widget.id}</div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: TOKENS.fontUi, fontSize: 13 }}>
          <thead>
            <tr>
              {cols.map((c, i) => (
                <th key={i} style={{ textAlign: "left", padding: "8px 10px", borderBottom: `1px solid ${TOKENS.border}`, color: TOKENS.muted, fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4 }}>
                  {c.label || c.key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={cols.length} style={{ padding: 16, color: TOKENS.muted, textAlign: "center" }}>No rows</td></tr>
            ) : rows.map((r, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${TOKENS.border}` }}>
                {cols.map((c, j) => (
                  <td key={j} style={{ padding: "8px 10px", color: TOKENS.text, fontFamily: c.mono ? TOKENS.fontMono : TOKENS.fontUi }}>
                    {fmt(r?.[c.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Chart({ widget }) {
  const series = Array.isArray(widget.props?.series) ? widget.props.series : [];
  const points = series.length ? series : [10, 14, 12, 18, 22, 19, 26, 31, 28, 35];
  const max = Math.max(...points, 1);
  const w = 320, h = 80, step = w / Math.max(points.length - 1, 1);
  const path = points.map((v, i) => `${i ? "L" : "M"}${i * step},${h - (v / max) * h}`).join(" ");
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{widget.props?.title || widget.id}</div>
      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: 80 }}>
        <path d={path} fill="none" stroke={TOKENS.accent} strokeWidth="2" />
      </svg>
      <span style={{ fontSize: 10, color: TOKENS.muted, fontFamily: TOKENS.fontUi }}>TODO: live data follows</span>
    </div>
  );
}

function MapWidget({ widget, resolved }) {
  const center = resolved.center || widget.props?.center || "—";
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{widget.props?.title || widget.id}</div>
      <div style={{
        height: 180, borderRadius: 8, position: "relative", overflow: "hidden",
        background: `${TOKENS.bg} repeating-linear-gradient(0deg, transparent 0 23px, ${TOKENS.border} 23px 24px), repeating-linear-gradient(90deg, transparent 0 23px, ${TOKENS.border} 23px 24px)`,
      }}>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: TOKENS.muted, fontFamily: TOKENS.fontUi, fontSize: 12 }}>
          Map: {String(center)}
        </div>
      </div>
    </div>
  );
}

function Markdown({ widget, resolved }) {
  const text = resolved.text || widget.props?.text || "";
  return (
    <div style={cardBase()}>
      <div style={cardTitle()}>{widget.props?.title || widget.id}</div>
      <pre style={{ whiteSpace: "pre-wrap", fontFamily: TOKENS.fontUi, fontSize: 13, color: TOKENS.text, margin: 0 }}>{text}</pre>
    </div>
  );
}

function ActionButton({ widget, resolved }) {
  const onClick = async () => {
    try {
      const aid = widget.props?.action_id || "noop";
      await fetch(`/api/actions/${encodeURIComponent(aid)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bindings: resolved }),
      });
    } catch (e) { console.warn("action failed", e); }
  };
  return (
    <div style={{ ...cardBase(), display: "flex", alignItems: "center", justifyContent: "center" }}>
      <button onClick={onClick} style={{
        padding: "10px 24px", border: "none", borderRadius: 8, cursor: "pointer",
        background: TOKENS.accent, color: TOKENS.text, fontFamily: TOKENS.fontUi,
        fontSize: 13, fontWeight: 600,
      }}>
        {widget.props?.label || widget.id}
      </button>
    </div>
  );
}

const RENDERERS = { ObjectCard, ObjectTable, Chart, Map: MapWidget, Markdown, ActionButton };

function fmt(v) {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v : v.toFixed(2);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function cardBase() {
  return { background: TOKENS.card, borderRadius: 12, padding: 16, boxShadow: TOKENS.shadow, border: `1px solid ${TOKENS.border}` };
}
function cardTitle() {
  return { fontSize: 13, fontWeight: 600, color: TOKENS.text, fontFamily: TOKENS.fontUi, marginBottom: 12, letterSpacing: 0.2 };
}

// ── Public helper: render a manifest inline (used by ComposeDemo). ──
export function renderManifest(manifest) {
  if (!manifest || !Array.isArray(manifest.widgets)) {
    return <div style={{ padding: 24, color: TOKENS.muted, fontFamily: TOKENS.fontUi }}>No manifest.</div>;
  }
  const scope = manifest.bindings_scope || {}; // future: hydrate from /api/objects
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(12, 1fr)", gap: 12 }}>
      {manifest.widgets.map((w) => {
        const Renderer = RENDERERS[w.kind];
        const resolved = resolveBindings(w.bindings || {}, scope);
        const style = { gridColumn: `span ${Math.min(Math.max(w.w || 6, 1), 12)}` };
        if (w.row) style.gridRow = String(w.row);
        return (
          <div key={w.id} style={style}>
            {Renderer ? <Renderer widget={w} resolved={resolved} /> : (
              <div style={cardBase()}>Unknown widget: {w.kind}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function ModuleRuntime() {
  const { id } = useParams();
  const [manifest, setManifest] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setError(null); setManifest(null);
    fetch(`/api/workshop/modules/${encodeURIComponent(id)}`)
      .then((r) => r.ok ? r.json() : r.json().then((j) => Promise.reject(j)))
      .then((row) => alive && setManifest(row.manifest || row))
      .catch((e) => alive && setError(e?.detail || e?.message || "Failed to load module"));
    return () => { alive = false; };
  }, [id]);

  const titleLine = useMemo(() => manifest ? (manifest.title || id) : "Loading…", [manifest, id]);

  return (
    <div style={{ background: TOKENS.bg, minHeight: "100vh", padding: "32px 40px", fontFamily: TOKENS.fontUi, color: TOKENS.text }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 16, marginBottom: 24 }}>
          <h1 style={{ fontSize: 22, fontWeight: 600, margin: 0 }}>{titleLine}</h1>
          {manifest?.target_type && (
            <span style={{ fontSize: 11, color: TOKENS.muted, textTransform: "uppercase", letterSpacing: 0.6 }}>{manifest.target_type}</span>
          )}
        </div>
        {error && (
          <div style={{ padding: 16, background: "#FEE", border: "1px solid #F99", borderRadius: 8, color: "#900" }}>
            {String(error)}
          </div>
        )}
        {!error && manifest && renderManifest(manifest)}
        {!error && !manifest && <div style={{ color: TOKENS.muted }}>Loading…</div>}
      </div>
    </div>
  );
}

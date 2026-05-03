// ComposeDemo.jsx — minimal AI-composer demo at /v2/builder.
//
// Flow: prompt + target_type → POST /api/workshop/modules/compose →
// preview via renderManifest() → optionally save (POST /api/workshop/modules)
// → navigate to /v2/modules/:slug.

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { renderManifest } from "./ModuleRuntime.jsx";
import ModuleCanvas from "./ModuleCanvas.jsx";
import "./module-canvas.css";

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

// ── Slate templates — one-click composable dashboards ─────────────────────
const SLATE_TEMPLATES = [
  {
    id: "uk-bess-dashboard",
    label: "UK BESS Pipeline",
    desc: "BESS site count + capacity total + REPD scatter + recent BESS notes",
    manifest: {
      slug: `uk-bess-dashboard-${Date.now()}`,
      title: "UK BESS Pipeline",
      target_type: "bess_unit",
      widgets: [
        { id: "kpi-count",    kind: "KPI",          w: 3, props: { label: "BESS REPDs",     endpoint: "/api/objects/REPDProject?technology=Battery&limit=1", value_path: "count" } },
        { id: "kpi-cap",      kind: "KPI",          w: 3, props: { label: "Substations",   endpoint: "/api/objects/Substation?limit=1",                       value_path: "count" } },
        { id: "kpi-conn",     kind: "KPI",          w: 3, props: { label: "Connectors live", endpoint: "/api/datasets",                                       value_path: "count" } },
        { id: "kpi-notes",    kind: "KPI",          w: 3, props: { label: "Recent notes",  endpoint: "/api/notes/recent?limit=1",                              value_path: "count" } },
        { id: "scatter-bess", kind: "QuiverChart",  w: 8, props: { type: "REPDProject", x_field: "capacity_mw", y_field: "capacity_mw", technology: "Battery", limit: 200, title: "REPD Battery — capacity distribution" } },
        { id: "health",       kind: "DatasetHealth", w: 4, props: { title: "Connector health" } },
        { id: "list-bess",    kind: "ObjectList",    w: 8, props: { type: "REPDProject", technology: "Battery", limit: 10, title: "Recent battery REPDs", columns: ["label", "capacity_mw", "status", "operator"] } },
        { id: "feed-recent",  kind: "NotesFeed",     w: 4, props: { limit: 6, title: "Recent notes (all)" } },
      ],
    },
  },
  {
    id: "uk-dc-dashboard",
    label: "UK Data Centre Pipeline",
    desc: "DC NSIP + REPD + capacity + recent NSIP submissions",
    manifest: {
      slug: `uk-dc-dashboard-${Date.now()}`,
      title: "UK Data Centre Pipeline",
      target_type: "data_centre",
      widgets: [
        { id: "kpi-nsip",  kind: "KPI",         w: 3, props: { label: "NSIP projects",   endpoint: "/api/objects/NSIPProject?limit=1",                       value_path: "count" } },
        { id: "kpi-repd",  kind: "KPI",         w: 3, props: { label: "REPD projects",   endpoint: "/api/objects/REPDProject?limit=1",                       value_path: "count" } },
        { id: "kpi-tec",   kind: "KPI",         w: 3, props: { label: "TEC queue",       endpoint: "/api/objects/TecQueueEntry?limit=1",                     value_path: "count" } },
        { id: "kpi-rows",  kind: "KPI",         w: 3, props: { label: "Total rows",      endpoint: "/api/datasets",                                          value_path: "count" } },
        { id: "scatter-nsip", kind: "QuiverChart", w: 8, props: { type: "NSIPProject",   x_field: "capacity_mw", y_field: "capacity_mw", limit: 100, title: "NSIP — capacity distribution" } },
        { id: "health",       kind: "DatasetHealth", w: 4, props: { title: "Connector health" } },
        { id: "list-nsip",    kind: "ObjectList", w: 12, props: { type: "NSIPProject", limit: 10, title: "Recent NSIPs", columns: ["label", "sector", "status", "promoter", "capacity_mw"] } },
      ],
    },
  },
  {
    id: "ops-pulse",
    label: "Ops Pulse",
    desc: "Connector health + recent notes + project list",
    manifest: {
      slug: `ops-pulse-${Date.now()}`,
      title: "Ops Pulse",
      widgets: [
        { id: "health",     kind: "DatasetHealth", w: 5, props: { title: "Magritte connectors" } },
        { id: "feed",       kind: "NotesFeed",     w: 7, props: { limit: 8, title: "Recent ops notes" } },
        { id: "projects",   kind: "ObjectList",    w: 12, props: { type: "Project", limit: 12, title: "Active projects", columns: ["label", "stage", "verdict", "technology", "capacity_mw"] } },
      ],
    },
  },
];

function SlateTemplatePicker({ onPick }) {
  return (
    <div style={{ marginBottom: 24, background: "rgba(245,183,49,0.10)", border: "1px solid rgba(245,183,49,0.40)", borderRadius: 12, padding: 14 }}>
      <div style={{ fontSize: 10, letterSpacing: 0.10, textTransform: "uppercase", color: "#4A3208", fontWeight: 700, marginBottom: 8 }}>SLATE · TEMPLATES</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
        {SLATE_TEMPLATES.map(t => (
          <button
            key={t.id}
            onClick={() => onPick(t.manifest)}
            style={{
              background: "#FFFFFF", border: "1px solid rgba(15,19,24,0.10)", borderRadius: 8,
              padding: "10px 14px", textAlign: "left", cursor: "pointer",
              fontFamily: "inherit", color: "#0F1318",
              transition: "border-color 100ms, box-shadow 100ms",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "#F5B731"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(245,183,49,0.18)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = "rgba(15,19,24,0.10)"; e.currentTarget.style.boxShadow = "none"; }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{t.label}</div>
            <div style={{ fontSize: 11, color: "#5A5F66", marginTop: 4, lineHeight: 1.4 }}>{t.desc}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function ComposeDemo() {
  const nav = useNavigate();
  const [prompt, setPrompt] = useState("Build a BESS revenue module with a dispatch summary card, recent trades table, and a P&L chart.");
  const [targetType, setTargetType] = useState("bess_unit");
  const [manifest, setManifest] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [saving, setSaving] = useState(false);

  const compose = async () => {
    setBusy(true); setErr(null); setManifest(null);
    try {
      const r = await fetch("/api/workshop/modules/compose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, target_type: targetType || null }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail || `compose failed (${r.status})`);
      setManifest(j.manifest || j);
    } catch (e) {
      setErr(e?.message || "compose failed");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!manifest) return;
    setSaving(true); setErr(null);
    try {
      const slug = manifest.slug || `module-${Date.now()}`;
      const title = manifest.title || "Untitled module";
      const r = await fetch("/api/workshop/modules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, title, target_type: manifest.target_type || targetType, manifest }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j?.detail || `save failed (${r.status})`);
      nav(`/v2/modules/${j.slug || slug}`);
    } catch (e) {
      setErr(e?.message || "save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ background: TOKENS.bg, minHeight: "100vh", padding: "32px 40px", fontFamily: TOKENS.fontUi, color: TOKENS.text }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <h1 style={{ fontSize: 22, fontWeight: 600, margin: "0 0 6px" }}>Workshop Composer</h1>
        <p style={{ fontSize: 13, color: TOKENS.muted, margin: "0 0 24px" }}>
          Describe the module you want. Claude composes a manifest against the DTDL schemas and renders it below — or drop a Slate template to start with a working dashboard.
        </p>

        <SlateTemplatePicker onPick={(t) => setManifest(t)} />


        <div style={{ background: TOKENS.card, padding: 20, borderRadius: 12, boxShadow: TOKENS.shadow, border: `1px solid ${TOKENS.border}`, marginBottom: 24 }}>
          <label style={{ display: "block", fontSize: 11, color: TOKENS.muted, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 6 }}>Prompt</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={4}
            style={{
              width: "100%", padding: 12, fontFamily: TOKENS.fontUi, fontSize: 13,
              border: `1px solid ${TOKENS.border}`, borderRadius: 8, resize: "vertical",
              background: TOKENS.bg, color: TOKENS.text, boxSizing: "border-box",
            }}
          />

          <div style={{ display: "flex", gap: 16, alignItems: "flex-end", marginTop: 16, flexWrap: "wrap" }}>
            <div>
              <label style={{ display: "block", fontSize: 11, color: TOKENS.muted, textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 6 }}>Target type</label>
              <select
                value={targetType}
                onChange={(e) => setTargetType(e.target.value)}
                style={{ padding: "8px 12px", fontFamily: TOKENS.fontUi, fontSize: 13, border: `1px solid ${TOKENS.border}`, borderRadius: 8, background: TOKENS.card, color: TOKENS.text }}
              >
                <option value="data_centre">data_centre</option>
                <option value="bess_unit">bess_unit</option>
              </select>
            </div>
            <button
              onClick={compose}
              disabled={busy || !prompt.trim()}
              style={{
                padding: "10px 24px", border: "none", borderRadius: 8,
                cursor: busy ? "wait" : "pointer", opacity: busy ? 0.6 : 1,
                background: TOKENS.accent, color: TOKENS.text, fontFamily: TOKENS.fontUi,
                fontSize: 13, fontWeight: 600,
              }}
            >
              {busy ? "Composing…" : "Compose"}
            </button>
            {manifest && (
              <button
                onClick={save}
                disabled={saving}
                style={{
                  padding: "10px 24px", border: `1px solid ${TOKENS.text}`, borderRadius: 8,
                  cursor: saving ? "wait" : "pointer", opacity: saving ? 0.6 : 1,
                  background: TOKENS.card, color: TOKENS.text, fontFamily: TOKENS.fontUi,
                  fontSize: 13, fontWeight: 600,
                }}
              >
                {saving ? "Saving…" : "Save & open"}
              </button>
            )}
          </div>
        </div>

        {err && (
          <div style={{ padding: 16, background: "#FEE", border: "1px solid #F99", borderRadius: 8, color: "#900", marginBottom: 16, fontSize: 13 }}>
            {err}
          </div>
        )}

        {manifest && (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12, marginTop: 8 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>Visual canvas</h2>
              <span style={{ fontSize: 11, color: TOKENS.muted }}>drag rows to reorder, slide ▭ to resize, click to edit props</span>
            </div>
            <ModuleCanvas
              manifest={manifest}
              onChange={setManifest}
              onSave={save}
              saving={saving}
            />
            <details style={{ marginTop: 24 }}>
              <summary style={{ cursor: "pointer", fontSize: 11, color: TOKENS.muted, textTransform: "uppercase", letterSpacing: 0.6 }}>Manifest JSON</summary>
              <pre style={{ marginTop: 8, padding: 12, background: TOKENS.card, border: `1px solid ${TOKENS.border}`, borderRadius: 8, fontFamily: TOKENS.fontMono, fontSize: 11, overflow: "auto", maxHeight: 400 }}>
                {JSON.stringify(manifest, null, 2)}
              </pre>
            </details>
          </>
        )}

        {!manifest && (
          <div style={{ marginTop: 12 }}>
            <button
              onClick={() => setManifest({slug: `module-${Date.now()}`, title: "New module", widgets: []})}
              style={{
                padding: "10px 20px", border: `1px solid ${TOKENS.border}`, borderRadius: 8,
                background: TOKENS.card, color: TOKENS.text, fontFamily: TOKENS.fontUi,
                fontSize: 13, fontWeight: 600, cursor: "pointer",
              }}>
              + Start blank canvas
            </button>
            <span style={{ fontSize: 11, color: TOKENS.muted, marginLeft: 12 }}>
              or pick a Slate template above, or compose with Claude.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ComposeDemo.jsx — minimal AI-composer demo at /v2/builder.
//
// Flow: prompt + target_type → POST /api/workshop/modules/compose →
// preview via renderManifest() → optionally save (POST /api/workshop/modules)
// → navigate to /v2/modules/:slug.

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { renderManifest } from "./ModuleRuntime.jsx";

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
          Describe the module you want. Claude composes a manifest against the DTDL schemas and renders it below.
        </p>

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
            <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
              <h2 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>{manifest.title || "Composed module"}</h2>
              <span style={{ fontSize: 11, color: TOKENS.muted, fontFamily: TOKENS.fontMono }}>{manifest.slug}</span>
            </div>
            {renderManifest(manifest)}
            <details style={{ marginTop: 24 }}>
              <summary style={{ cursor: "pointer", fontSize: 11, color: TOKENS.muted, textTransform: "uppercase", letterSpacing: 0.6 }}>Manifest JSON</summary>
              <pre style={{ marginTop: 8, padding: 12, background: TOKENS.card, border: `1px solid ${TOKENS.border}`, borderRadius: 8, fontFamily: TOKENS.fontMono, fontSize: 11, overflow: "auto", maxHeight: 400 }}>
                {JSON.stringify(manifest, null, 2)}
              </pre>
            </details>
          </>
        )}
      </div>
    </div>
  );
}

import React, { useCallback, useEffect, useMemo, useState } from "react";

/**
 * PipelineView — 8-column kanban of projects across lifecycle stages.
 *
 * Stages mirror backend VALID_STAGES in app/routers/projects.py:
 *   prospect → screened → grid_applied → grid_offer → planning → fid →
 *   construction → energised
 *
 * Drag a card between columns → PATCH /api/v1/projects/{id} { stage }.
 */

const STAGES = [
  { id: "prospect",      label: "Prospect",       hint: "Sourcing" },
  { id: "screened",      label: "Screened",       hint: "GO / CAUTION / NO-GO" },
  { id: "grid_applied",  label: "Grid applied",   hint: "G99 / G100 in" },
  { id: "grid_offer",    label: "Grid offer",     hint: "DNO offer received" },
  { id: "planning",      label: "Planning",       hint: "LPA / NSIP" },
  { id: "fid",           label: "FID",            hint: "Funded" },
  { id: "construction",  label: "Construction",   hint: "On site" },
  { id: "energised",     label: "Energised",      hint: "Operational" },
];

const COLOR = {
  gold: "#caa24a",
  ink: "#0f1318",
  ink_soft: "#6b7280",
  border: "#e5e7eb",
  bg: "#ffffff",
  shimmer: "#f3f4f6",
  go: "#2f7c46",
  caution: "#c07a1a",
  nogo: "#b23b3b",
};

function VerdictChip({ v }) {
  if (!v) return null;
  const bg =
    v === "GO" ? COLOR.go :
    v === "NO-GO" ? COLOR.nogo :
    v === "CAUTION" ? COLOR.caution :
    COLOR.ink_soft;
  return (
    <span style={{
      background: bg, color: "#fff", padding: "1px 6px", borderRadius: 8,
      fontSize: 9, fontWeight: 700, letterSpacing: 0.5,
    }}>
      {v}
    </span>
  );
}

export default function PipelineView({ onSelectProject }) {
  const [projects, setProjects] = useState(null);
  const [err, setErr] = useState(null);
  const [dragged, setDragged] = useState(null);
  const [dragOver, setDragOver] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/v1/projects");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setProjects(Array.isArray(data) ? data : (data.projects || []));
      setErr(null);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const byStage = useMemo(() => {
    const acc = Object.fromEntries(STAGES.map((s) => [s.id, []]));
    (projects || []).forEach((p) => {
      const s = p.stage || "prospect";
      (acc[s] || acc.prospect).push(p);
    });
    return acc;
  }, [projects]);

  const moveTo = async (proj, targetStage) => {
    if (!proj || proj.stage === targetStage) return;
    // Optimistic update
    setProjects((curr) =>
      (curr || []).map((p) => p.project_id === proj.project_id ? { ...p, stage: targetStage } : p)
    );
    try {
      const r = await fetch(`/api/v1/projects/${proj.project_id}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ stage: targetStage }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    } catch (e) {
      setErr(`move failed: ${e.message}`);
      load(); // rollback
    }
  };

  const onDragStart = (e, p) => {
    setDragged(p);
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setData("text/plain", p.project_id); } catch {}
  };
  const onDragEnd = () => { setDragged(null); setDragOver(null); };
  const onDragOver = (e, stageId) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOver !== stageId) setDragOver(stageId);
  };
  const onDrop = (e, stageId) => {
    e.preventDefault();
    if (dragged) moveTo(dragged, stageId);
    onDragEnd();
  };

  return (
    <div style={root}>
      <header style={header}>
        <div>
          <div style={eyebrow}>Pipeline</div>
          <h2 style={{ fontSize: 20, margin: "2px 0 0", letterSpacing: -0.3 }}>All projects by stage</h2>
        </div>
        <div style={{ fontSize: 12, color: COLOR.ink_soft }}>
          {projects ? `${projects.length} projects` : "…"}
          {err && <span style={{ color: COLOR.nogo, marginLeft: 12 }}>· {err}</span>}
        </div>
      </header>

      <div style={board}>
        {STAGES.map((stage) => {
          const items = byStage[stage.id] || [];
          const hot = dragOver === stage.id;
          return (
            <div
              key={stage.id}
              style={{ ...col, background: hot ? "#fff8e6" : COLOR.shimmer, borderColor: hot ? COLOR.gold : COLOR.border }}
              onDragOver={(e) => onDragOver(e, stage.id)}
              onDrop={(e) => onDrop(e, stage.id)}
              onDragLeave={() => dragOver === stage.id && setDragOver(null)}
            >
              <div style={colHead}>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{stage.label}</div>
                <span style={{ fontSize: 11, color: COLOR.ink_soft, fontVariantNumeric: "tabular-nums" }}>
                  {items.length}
                </span>
              </div>
              <div style={{ fontSize: 10, color: COLOR.ink_soft, marginBottom: 8 }}>{stage.hint}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {items.map((p) => (
                  <div
                    key={p.project_id}
                    draggable
                    onDragStart={(e) => onDragStart(e, p)}
                    onDragEnd={onDragEnd}
                    onClick={() => onSelectProject?.(p.project_id)}
                    style={{
                      ...card,
                      opacity: dragged && dragged.project_id === p.project_id ? 0.5 : 1,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{p.name || "Untitled"}</div>
                      <VerdictChip v={p.verdict} />
                    </div>
                    <div style={{ fontSize: 11, color: COLOR.ink_soft, marginTop: 3 }}>
                      {p.technology || "—"}
                      {p.capacity_mw != null && ` · ${Number(p.capacity_mw).toFixed(0)} MW`}
                    </div>
                  </div>
                ))}
                {items.length === 0 && (
                  <div style={{ fontSize: 11, color: COLOR.ink_soft, padding: "4px 0", fontStyle: "italic" }}>
                    (empty — drop a project here)
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const root = {
  padding: 20, fontFamily: "'DM Sans', -apple-system, sans-serif", color: COLOR.ink,
  background: COLOR.bg, height: "100%", display: "flex", flexDirection: "column",
};
const header = {
  display: "flex", justifyContent: "space-between", alignItems: "baseline",
  marginBottom: 16, flexShrink: 0,
};
const eyebrow = { fontSize: 10, letterSpacing: 2, textTransform: "uppercase", color: COLOR.gold, fontWeight: 600 };
const board = {
  display: "flex", gap: 10, overflowX: "auto", flex: 1, paddingBottom: 6,
};
const col = {
  minWidth: 220, flex: "0 0 220px", padding: 12, borderRadius: 5,
  border: `1px solid ${COLOR.border}`, transition: "background 140ms, border 140ms",
  display: "flex", flexDirection: "column",
};
const colHead = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
};
const card = {
  background: COLOR.bg, border: `1px solid ${COLOR.border}`, padding: 10,
  borderRadius: 4, cursor: "grab", fontSize: 13, transition: "opacity 120ms",
};

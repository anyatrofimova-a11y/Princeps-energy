import React, { useState, useMemo } from "react";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

/* ── Pipeline stages ────────────────────────────────────────── */
const STAGES = [
  { id: "prospecting", label: "Prospecting", opacity: 1.0 },
  { id: "feasibility", label: "Feasibility", opacity: 0.85 },
  { id: "grid_application", label: "Grid Application", opacity: 0.7 },
  { id: "planning", label: "Planning", opacity: 0.55 },
  { id: "construction", label: "Construction", opacity: 0.4 },
  { id: "operational", label: "Operational", opacity: 0.25 },
];

/* Map project phases to pipeline stages */
const PHASE_TO_STAGE = {
  prospecting: "prospecting",
  feasibility: "feasibility",
  grid_study: "grid_application",
  planning: "planning",
  installation: "construction",
  commissioning: "construction",
  operational: "operational",
};

/* ── Styles ─────────────────────────────────────────────────── */
const colors = {
  gold: "#F5B731",
  goldDark: "#E8A012",
  goldSurface: "rgba(245,183,49,0.06)",
  goldBorder: "rgba(245,183,49,0.25)",
  bg: "#F7F8FA",
  card: "#FFFFFF",
  border: "#E8E5DF",
  ink: "#1A1714",
  secondary: "#6B6560",
  tertiary: "#9C9590",
  go: "#2D7A4F",
  caution: "#C67A1A",
  danger: "#B5432A",
};

/* ── Sortable kanban card ───────────────────────────────────── */
function KanbanCard({ project, isDragging }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging: isSortDragging,
  } = useSortable({ id: project.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isSortDragging ? 0.4 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} {...attributes}>
      <CardContent project={project} listeners={listeners} isDragging={isDragging} />
    </div>
  );
}

/* ── Card content (shared between sortable + drag overlay) ─── */
function CardContent({ project, listeners, isDragging }) {
  const [hovered, setHovered] = useState(false);
  const p = project;

  const verdictStyle = {
    GO: { bg: `${colors.go}15`, color: colors.go, border: `${colors.go}30` },
    CAUTION: { bg: `${colors.caution}15`, color: colors.caution, border: `${colors.caution}30` },
    "NO-GO": { bg: `${colors.danger}15`, color: colors.danger, border: `${colors.danger}30` },
  };
  const v = verdictStyle[p.verdict] || verdictStyle.CAUTION;

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: colors.card,
        border: `1px solid ${hovered || isDragging ? colors.goldBorder : colors.border}`,
        borderRadius: 10,
        padding: "14px 16px",
        marginBottom: 8,
        cursor: "grab",
        transition: "all 0.2s ease",
        boxShadow: isDragging
          ? `0 8px 24px rgba(245,183,49,0.15), 0 2px 8px rgba(0,0,0,0.08)`
          : hovered
            ? "0 2px 8px rgba(0,0,0,0.06)"
            : "0 1px 3px rgba(0,0,0,0.03)",
        transform: isDragging ? "rotate(1.5deg) scale(1.02)" : "none",
        borderLeft: hovered ? `3px solid ${colors.gold}` : "3px solid transparent",
        position: "relative",
      }}
      {...listeners}
    >
      {/* Title + tech */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <span style={{
          fontSize: 13,
          fontWeight: 600,
          color: colors.ink,
          flex: 1,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {p.name}
        </span>
      </div>

      {/* Tech + Capacity row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{
          fontSize: 10,
          fontWeight: 600,
          color: colors.goldDark,
          background: colors.goldSurface,
          border: `1px solid ${colors.goldBorder}`,
          padding: "2px 8px",
          borderRadius: 12,
          textTransform: "capitalize",
          letterSpacing: "0.02em",
        }}>
          {p.technology}
        </span>
        <span style={{
          fontSize: 12,
          fontWeight: 700,
          fontFamily: "var(--mono, 'JetBrains Mono'), monospace",
          color: colors.ink,
        }}>
          {p.capacity_mw} MW
        </span>
      </div>

      {/* Stage-specific info */}
      {p.stage_info && (
        <div style={{
          fontSize: 11,
          color: p.stage_info_urgent ? colors.danger : colors.secondary,
          fontWeight: p.stage_info_urgent ? 600 : 400,
          marginBottom: 8,
          lineHeight: 1.4,
        }}>
          {p.stage_info}
        </div>
      )}

      {/* Bottom row: score + verdict + owner */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {p.score != null && (
          <span style={{
            fontSize: 11,
            fontWeight: 700,
            fontFamily: "var(--mono, 'JetBrains Mono'), monospace",
            color: p.score >= 70 ? colors.gold : p.score >= 50 ? colors.caution : colors.danger,
          }}>
            {p.score}
          </span>
        )}
        {p.verdict && (
          <span style={{
            fontSize: 9,
            fontWeight: 700,
            padding: "2px 7px",
            borderRadius: 10,
            background: v.bg,
            color: v.color,
            border: `1px solid ${v.border}`,
            letterSpacing: "0.03em",
            textTransform: "uppercase",
          }}>
            {p.verdict}
          </span>
        )}
        <div style={{ flex: 1 }} />
        {p.owner && (
          <div style={{
            width: 22,
            height: 22,
            borderRadius: "50%",
            background: colors.goldSurface,
            border: `1.5px solid ${colors.goldBorder}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 9,
            fontWeight: 700,
            color: colors.goldDark,
          }}>
            {p.owner.split(" ").map(n => n[0]).join("")}
          </div>
        )}
        {/* Drag handle */}
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ opacity: hovered ? 0.5 : 0.15, transition: "opacity 0.15s" }}>
          <circle cx="4" cy="2.5" r="1" fill={colors.tertiary} />
          <circle cx="8" cy="2.5" r="1" fill={colors.tertiary} />
          <circle cx="4" cy="6" r="1" fill={colors.tertiary} />
          <circle cx="8" cy="6" r="1" fill={colors.tertiary} />
          <circle cx="4" cy="9.5" r="1" fill={colors.tertiary} />
          <circle cx="8" cy="9.5" r="1" fill={colors.tertiary} />
        </svg>
      </div>
    </div>
  );
}

/* ── Column ─────────────────────────────────────────────────── */
function KanbanColumn({ stage, projects, totalMw }) {
  const ids = projects.map(p => p.id);

  return (
    <div style={{
      flex: "0 0 220px",
      minWidth: 220,
      display: "flex",
      flexDirection: "column",
      height: "100%",
    }}>
      {/* Column header */}
      <div style={{
        borderTop: `3px solid ${colors.gold}`,
        borderTopLeftRadius: 8,
        borderTopRightRadius: 8,
        opacity: stage.opacity + 0.3,
        padding: "12px 12px 8px",
        background: colors.card,
        border: `1px solid ${colors.border}`,
        borderBottom: "none",
        borderRadius: "10px 10px 0 0",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            fontSize: 12,
            fontWeight: 700,
            color: colors.ink,
          }}>
            {stage.label}
          </span>
          <span style={{
            fontSize: 10,
            fontWeight: 600,
            color: colors.goldDark,
            background: colors.goldSurface,
            padding: "1px 6px",
            borderRadius: 8,
          }}>
            {projects.length}
          </span>
        </div>
        <div style={{
          fontSize: 10,
          color: colors.tertiary,
          marginTop: 2,
          fontFamily: "var(--mono, 'JetBrains Mono'), monospace",
        }}>
          {totalMw} MW total
        </div>
      </div>

      {/* Cards area */}
      <div style={{
        flex: 1,
        background: `rgba(245,183,49,${0.01 + stage.opacity * 0.02})`,
        border: `1px solid ${colors.border}`,
        borderTop: "none",
        borderRadius: "0 0 10px 10px",
        padding: 8,
        overflowY: "auto",
        minHeight: 200,
      }}>
        <SortableContext items={ids} strategy={verticalListSortingStrategy}>
          {projects.map(p => (
            <KanbanCard key={p.id} project={p} />
          ))}
        </SortableContext>

        {/* Add project */}
        <button style={{
          width: "100%",
          padding: "10px 0",
          border: `1px dashed ${colors.border}`,
          borderRadius: 8,
          background: "transparent",
          color: colors.tertiary,
          fontSize: 11,
          fontWeight: 500,
          cursor: "pointer",
          fontFamily: "'DM Sans', sans-serif",
          transition: "all 0.15s",
          marginTop: 4,
        }}
          onMouseEnter={e => {
            e.currentTarget.style.borderColor = colors.goldBorder;
            e.currentTarget.style.color = colors.goldDark;
            e.currentTarget.style.background = colors.goldSurface;
          }}
          onMouseLeave={e => {
            e.currentTarget.style.borderColor = colors.border;
            e.currentTarget.style.color = colors.tertiary;
            e.currentTarget.style.background = "transparent";
          }}
        >
          + Add project
        </button>
      </div>
    </div>
  );
}

/* ── Pipeline sidebar ───────────────────────────────────────── */
function PipelineSidebar({ projects, stageGroups }) {
  const totalProjects = projects.length;
  const totalMw = projects.reduce((s, p) => s + (p.capacity_mw || 0), 0);
  const avgIrr = projects.length
    ? (projects.reduce((s, p) => s + (p.irr || 0), 0) / projects.length).toFixed(1)
    : 0;
  const atRisk = projects.filter(p => p.verdict === "CAUTION" || p.verdict === "NO-GO").length;

  const maxCount = Math.max(...STAGES.map(s => (stageGroups[s.id] || []).length), 1);

  return (
    <div style={{
      width: 220,
      flexShrink: 0,
      display: "flex",
      flexDirection: "column",
      gap: 16,
      padding: "0 4px",
    }}>
      {/* Summary card */}
      <div style={{
        background: colors.card,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        padding: 16,
      }}>
        <div style={{
          fontSize: 12,
          fontWeight: 700,
          color: colors.ink,
          marginBottom: 12,
        }}>
          Pipeline Summary
        </div>
        {[
          { label: "Total projects", value: totalProjects },
          { label: "Total capacity", value: `${totalMw} MW` },
          { label: "Average IRR", value: `${avgIrr}%` },
          { label: "At risk", value: atRisk, color: atRisk > 0 ? colors.danger : colors.go },
        ].map(m => (
          <div key={m.label} style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "6px 0",
            borderBottom: `1px solid ${colors.border}`,
          }}>
            <span style={{ fontSize: 11, color: colors.secondary }}>{m.label}</span>
            <span style={{
              fontSize: 12,
              fontWeight: 700,
              fontFamily: "var(--mono, 'JetBrains Mono'), monospace",
              color: m.color || colors.ink,
            }}>
              {m.value}
            </span>
          </div>
        ))}
      </div>

      {/* Pipeline funnel */}
      <div style={{
        background: colors.card,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        padding: 16,
      }}>
        <div style={{
          fontSize: 12,
          fontWeight: 700,
          color: colors.ink,
          marginBottom: 12,
        }}>
          Pipeline Funnel
        </div>
        {STAGES.map(s => {
          const count = (stageGroups[s.id] || []).length;
          const pct = (count / maxCount) * 100;
          return (
            <div key={s.id} style={{ marginBottom: 8 }}>
              <div style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 10,
                color: colors.secondary,
                marginBottom: 3,
              }}>
                <span>{s.label}</span>
                <span style={{ fontWeight: 700, fontFamily: "var(--mono), monospace", color: colors.goldDark }}>
                  {count}
                </span>
              </div>
              <div style={{
                height: 6,
                background: `${colors.gold}15`,
                borderRadius: 3,
                overflow: "hidden",
              }}>
                <div style={{
                  height: "100%",
                  width: `${pct}%`,
                  background: `linear-gradient(90deg, ${colors.gold}, ${colors.goldDark})`,
                  borderRadius: 3,
                  transition: "width 0.4s ease",
                }} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Conversion rates */}
      <div style={{
        background: colors.card,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
        padding: 16,
      }}>
        <div style={{
          fontSize: 12,
          fontWeight: 700,
          color: colors.ink,
          marginBottom: 12,
        }}>
          Conversion Rates
        </div>
        {[
          { from: "Prospect", to: "Feasibility", rate: "67%" },
          { from: "Feasibility", to: "Grid App", rate: "78%" },
          { from: "Grid App", to: "Planning", rate: "83%" },
          { from: "Planning", to: "Construction", rate: "56%" },
        ].map((c, i) => (
          <div key={i} style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "5px 0",
            borderBottom: i < 3 ? `1px solid ${colors.border}` : "none",
          }}>
            <span style={{ fontSize: 10, color: colors.secondary }}>
              {c.from} → {c.to}
            </span>
            <span style={{
              fontSize: 11,
              fontWeight: 700,
              fontFamily: "var(--mono), monospace",
              color: colors.goldDark,
            }}>
              {c.rate}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Demo data ──────────────────────────────────────────────── */
const DEMO_PROJECTS = [
  { id: "p1", name: "Essex Solar Farm", technology: "solar", capacity_mw: 25, stage: "prospecting", owner: "James Chen", irr: 14.5 },
  { id: "p2", name: "Suffolk Wind", technology: "wind", capacity_mw: 15, stage: "prospecting", owner: "Sarah Kim", irr: 16.2 },
  { id: "p3", name: "Cambridge BESS", technology: "bess", capacity_mw: 35, stage: "prospecting", owner: "Tom Wright", irr: 22.1 },
  { id: "p4", name: "Norfolk Solar", technology: "solar", capacity_mw: 25, score: 55, verdict: "CAUTION", stage: "feasibility", owner: "Sarah Kim", irr: 12.1, stage_info: "ALC survey pending" },
  { id: "p5", name: "Devon Wind", technology: "wind", capacity_mw: 25, score: 71, verdict: "GO", stage: "feasibility", owner: "James Chen", irr: 18.4 },
  { id: "p6", name: "Slough DC", technology: "datacentre", capacity_mw: 15, score: 64, verdict: "CAUTION", stage: "grid_application", owner: "James Chen", irr: 15.2, stage_info: "Grid offer due: 15 Apr", stage_info_urgent: true },
  { id: "p7", name: "Reading Solar", technology: "solar", capacity_mw: 20, score: 73, verdict: "GO", stage: "grid_application", owner: "Tom Wright", irr: 17.8, stage_info: "Offer accepted — awaiting connection" },
  { id: "p8", name: "Kent BESS", technology: "bess", capacity_mw: 40, score: 81, verdict: "GO", stage: "planning", owner: "Sarah Kim", irr: 28.3, stage_info: "LPA submission pending" },
  { id: "p9", name: "Bristol Hybrid", technology: "solar", capacity_mw: 30, score: 68, verdict: "CAUTION", stage: "planning", owner: "Tom Wright", irr: 16.9, stage_info: "S106 negotiation" },
  { id: "p10", name: "Midlands Solar", technology: "solar", capacity_mw: 30, score: 72, verdict: "GO", stage: "construction", owner: "James Chen", irr: 19.8, stage_info: "COD: Sep 2026 — 65% complete" },
  { id: "p11", name: "Highland Wind", technology: "wind", capacity_mw: 50, score: 78, verdict: "GO", stage: "operational", owner: "Sarah Kim", irr: 24.1, stage_info: "Generation: 102% of forecast" },
  { id: "p12", name: "Welsh Solar", technology: "solar", capacity_mw: 20, score: 75, verdict: "GO", stage: "operational", owner: "Tom Wright", irr: 20.3, stage_info: "£1.4M revenue YTD" },
];

/* ── Filter chips ───────────────────────────────────────────── */
const TECH_OPTIONS = [
  { key: "all", label: "All" },
  { key: "solar", label: "Solar" },
  { key: "wind", label: "Wind" },
  { key: "bess", label: "BESS" },
  { key: "datacentre", label: "DC" },
];

const MEMBER_OPTIONS = [
  { key: "all", label: "All members" },
  { key: "James Chen", label: "James Chen" },
  { key: "Sarah Kim", label: "Sarah Kim" },
  { key: "Tom Wright", label: "Tom Wright" },
];

/* ── Main component ─────────────────────────────────────────── */
export default function KanbanPipeline({ projects: externalProjects }) {
  const [items, setItems] = useState(externalProjects?.length ? externalProjects : DEMO_PROJECTS);
  const [activeId, setActiveId] = useState(null);
  const [techFilter, setTechFilter] = useState("all");
  const [memberFilter, setMemberFilter] = useState("all");

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  );

  const filtered = useMemo(() => {
    let list = items;
    if (techFilter !== "all") list = list.filter(p => p.technology === techFilter);
    if (memberFilter !== "all") list = list.filter(p => p.owner === memberFilter);
    return list;
  }, [items, techFilter, memberFilter]);

  const stageGroups = useMemo(() => {
    const groups = {};
    STAGES.forEach(s => { groups[s.id] = []; });
    filtered.forEach(p => {
      const stage = p.stage || PHASE_TO_STAGE[p.phase] || "prospecting";
      if (groups[stage]) groups[stage].push(p);
      else groups.prospecting.push(p);
    });
    return groups;
  }, [filtered]);

  const activeProject = activeId ? items.find(p => p.id === activeId) : null;

  const findStage = (id) => {
    for (const [stage, projs] of Object.entries(stageGroups)) {
      if (projs.some(p => p.id === id)) return stage;
    }
    return null;
  };

  const handleDragStart = (event) => {
    setActiveId(event.active.id);
  };

  const handleDragOver = (event) => {
    const { active, over } = event;
    if (!over) return;

    const activeStage = findStage(active.id);
    const overStage = findStage(over.id);

    // If dragging over a column (stage id), move to that column
    const targetStage = STAGES.find(s => s.id === over.id)?.id || overStage;

    if (activeStage && targetStage && activeStage !== targetStage) {
      setItems(prev => prev.map(p =>
        p.id === active.id ? { ...p, stage: targetStage } : p
      ));
    }
  };

  const handleDragEnd = (event) => {
    setActiveId(null);
  };

  const totalMw = filtered.reduce((s, p) => s + (p.capacity_mw || 0), 0);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "16px 20px",
        borderBottom: `1px solid ${colors.border}`,
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 18, fontWeight: 800, color: colors.ink }}>Deal Pipeline</span>
          <span style={{
            fontSize: 10,
            fontWeight: 600,
            color: colors.secondary,
            background: `${colors.border}`,
            padding: "3px 10px",
            borderRadius: 12,
          }}>
            {filtered.length} projects
          </span>
          <span style={{
            fontSize: 10,
            fontWeight: 600,
            fontFamily: "var(--mono), monospace",
            color: colors.goldDark,
          }}>
            {totalMw} MW
          </span>
        </div>

        <div style={{ flex: 1 }} />

        {/* Tech filters */}
        <div style={{ display: "flex", gap: 4 }}>
          {TECH_OPTIONS.map(t => (
            <button
              key={t.key}
              className={`pd3-chip ${techFilter === t.key ? "pd3-chip-active" : ""}`}
              onClick={() => setTechFilter(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Member filter */}
        <select
          value={memberFilter}
          onChange={e => setMemberFilter(e.target.value)}
          style={{
            padding: "5px 10px",
            fontSize: 12,
            fontFamily: "'DM Sans', sans-serif",
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            background: colors.card,
            color: colors.ink,
            outline: "none",
            cursor: "pointer",
          }}
        >
          {MEMBER_OPTIONS.map(m => (
            <option key={m.key} value={m.key}>{m.label}</option>
          ))}
        </select>
      </div>

      {/* Board + Sidebar */}
      <div style={{
        flex: 1,
        display: "flex",
        gap: 16,
        padding: 16,
        overflow: "hidden",
      }}>
        {/* Kanban columns */}
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDragEnd={handleDragEnd}
        >
          <div style={{
            flex: 1,
            display: "flex",
            gap: 10,
            overflowX: "auto",
            overflowY: "hidden",
            paddingBottom: 8,
          }}>
            {STAGES.map(stage => {
              const stageProjects = stageGroups[stage.id] || [];
              const stageMw = stageProjects.reduce((s, p) => s + (p.capacity_mw || 0), 0);
              return (
                <KanbanColumn
                  key={stage.id}
                  stage={stage}
                  projects={stageProjects}
                  totalMw={stageMw}
                />
              );
            })}
          </div>

          <DragOverlay>
            {activeProject ? (
              <div style={{ width: 220 }}>
                <CardContent project={activeProject} isDragging />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>

        {/* Sidebar */}
        <PipelineSidebar projects={filtered} stageGroups={stageGroups} />
      </div>
    </div>
  );
}

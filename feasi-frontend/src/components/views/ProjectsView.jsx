/**
 * ProjectsView — flat list of all portfolio projects.
 *
 * Distinct from the Home Dashboard (portfolio KPIs + charts) and the Pipeline
 * workspace (kanban + timeline). This is the "spreadsheet" — sortable, filterable
 * table of every project with score / verdict / phase / blocker.
 */
import React, { useEffect, useState, useCallback } from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import api from "../../services/api";
import ProjectPipelineTable from "../dashboard/ProjectPipelineTable";

const FALLBACK_PROJECTS = [
  { id: "1", name: "Highland Wind",   technology: "wind",       capacity_mw: 50, phase: "operational",  score: 78, verdict: "GO",      status: "operational" },
  { id: "2", name: "Midlands Solar",  technology: "solar",      capacity_mw: 30, phase: "installation", score: 72, verdict: "GO",      status: "in_progress" },
  { id: "3", name: "Slough DC",       technology: "datacentre", capacity_mw: 15, phase: "grid_study",   score: 64, verdict: "CAUTION", status: "at_risk" },
  { id: "4", name: "Kent BESS",       technology: "bess",       capacity_mw: 40, phase: "planning",     score: 81, verdict: "GO",      status: "at_risk" },
  { id: "5", name: "Norfolk Solar",   technology: "solar",      capacity_mw: 25, phase: "feasibility",  score: 55, verdict: "CAUTION", status: "in_progress" },
];

export default function ProjectsView() {
  const { setPickedLocation } = useSite();
  const { setActiveViewMode, navigateToIntent } = useWorkspace();

  const [projects, setProjects] = useState(FALLBACK_PROJECTS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.projects.list({ limit: 500 });
        if (cancelled) return;
        if (Array.isArray(data) && data.length) setProjects(data);
      } catch (e) {
        if (!cancelled) setError(e?.message || "Failed to load projects");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleView = useCallback((project) => {
    if (project?.lat != null && project?.lon != null) {
      setPickedLocation({ lat: project.lat, lon: project.lon });
    }
    setActiveViewMode("map");
  }, [setPickedLocation, setActiveViewMode]);

  const handleAssess = useCallback(() => {
    navigateToIntent?.("feasibility");
  }, [navigateToIntent]);

  const total = projects.length;
  const totalMw = projects.reduce((s, p) => s + (p.capacity_mw || 0), 0);
  const goCount = projects.filter(p => p.verdict === "GO").length;
  const cautionCount = projects.filter(p => p.verdict === "CAUTION").length;
  const nogoCount = projects.filter(p => p.verdict === "NO-GO").length;

  return (
    <div style={{
      height: "100%",
      overflowY: "auto",
      background: "var(--cds-background, #F7F8FA)",
      fontFamily: "'DM Sans', sans-serif",
    }}>
      <div style={{ padding: "24px 28px", maxWidth: 1400, margin: "0 auto" }}>
        {/* Header */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 18,
        }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: "#111827" }}>Projects</h1>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "#6B7280" }}>
              {loading ? "Loading projects…" : `${total} projects · ${Math.round(totalMw)} MW total`}
            </p>
          </div>

          {/* Counts strip */}
          {!loading && (
            <div style={{ display: "flex", gap: 8 }}>
              <Chip label={`${goCount} GO`}       bg="#DCFCE7" fg="#15803D" />
              <Chip label={`${cautionCount} CAUTION`} bg="#FEF3C7" fg="#92400E" />
              <Chip label={`${nogoCount} NO-GO`}  bg="#FEE2E2" fg="#991B1B" />
            </div>
          )}
        </div>

        {error && (
          <div style={{
            padding: "10px 14px",
            marginBottom: 16,
            background: "#FEF3C7",
            border: "1px solid #FDE68A",
            borderRadius: 8,
            fontSize: 12,
            color: "#92400E",
          }}>
            Showing demo data — {error}
          </div>
        )}

        <ProjectPipelineTable
          projects={projects}
          onViewProject={handleView}
          onAssessProject={handleAssess}
        />
      </div>
    </div>
  );
}

function Chip({ label, bg, fg }) {
  return (
    <span style={{
      padding: "4px 10px",
      fontSize: 11,
      fontWeight: 700,
      borderRadius: 12,
      background: bg,
      color: fg,
      fontFamily: "'DM Sans', sans-serif",
    }}>{label}</span>
  );
}

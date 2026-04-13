import React, { useState, useRef, useEffect, lazy, Suspense } from "react";
import ProjectPipelineTable from "./ProjectPipelineTable";
import KanbanPipeline from "./KanbanPipeline";
import SiteSearchPanel from "./SiteSearchPanel";
import RegulatoryFeed from "./RegulatoryFeed";

const UnifiedSiteDesigner = lazy(() => import("../designer/UnifiedSiteDesigner"));

const TABS = [
  { key: "projects", label: "Projects" },
  { key: "pipeline", label: "Pipeline" },
  { key: "designer", label: "Designer" },
  { key: "search", label: "Site Search" },
  { key: "regulations", label: "Regulations" },
  { key: "scenarios", label: "Scenarios" },
];

export default function WorkspaceTabs({
  projects,
  onSiteSelect,
  onSearchRegion,
  onViewProject,
  onAssessProject,
  onAction,
}) {
  const [activeTab, setActiveTab] = useState("projects");
  const [transitioning, setTransitioning] = useState(false);
  const contentRef = useRef(null);

  const handleTabChange = (key) => {
    if (key === activeTab) return;
    setTransitioning(true);
    setTimeout(() => {
      setActiveTab(key);
      setTransitioning(false);
    }, 150);
  };

  const renderContent = () => {
    switch (activeTab) {
      case "projects":
        return (
          <ProjectPipelineTable
            projects={projects}
            onViewProject={onViewProject}
            onAssessProject={onAssessProject}
            onNavigateIntent={onAction}
          />
        );
      case "pipeline":
        return <KanbanPipeline projects={projects} />;
      case "designer":
        return (
          <Suspense fallback={<div style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>Loading designer...</div>}>
            <div style={{ height: 600 }}>
              <UnifiedSiteDesigner />
            </div>
          </Suspense>
        );
      case "search":
        return (
          <SiteSearchPanel
            onSiteSelect={onSiteSelect}
            onSearchRegion={onSearchRegion}
          />
        );
      case "regulations":
        return <RegulatoryFeed />;
      case "scenarios":
        return (
          <div style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            padding: "64px 24px",
            gap: 14,
          }}>
            <div style={{
              width: 48,
              height: 48,
              borderRadius: 12,
              background: "rgba(245,183,49,0.06)",
              border: "1px solid rgba(245,183,49,0.15)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}>
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="1.5">
                <path d="M3 3v18h18" strokeLinecap="round" />
                <path d="M7 14l4-6 4 3 5-7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <span style={{
              fontSize: 10,
              fontWeight: 700,
              color: "var(--gold-dark)",
              background: "rgba(245,183,49,0.06)",
              padding: "3px 10px",
              borderRadius: 20,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
            }}>
              Coming Soon
            </span>
            <span style={{ fontSize: 15, fontWeight: 600, color: "var(--ink)" }}>
              Scenario Modelling
            </span>
            <span style={{ fontSize: 12, color: "var(--muted)", textAlign: "center", maxWidth: 360, lineHeight: 1.5 }}>
              Compare NESO FES pathways, curtailment profiles, and dispatch strategies across your portfolio.
            </span>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="pd3-card pd3-enter-4" style={{ margin: "0 24px 16px", overflow: "hidden" }}>
      {/* Tab bar */}
      <div className="pd3-tab-bar">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`pd3-tab ${activeTab === t.key ? "pd3-tab-active" : ""}`}
            onClick={() => handleTabChange(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content with fade transition */}
      <div
        ref={contentRef}
        style={{
          minHeight: 300,
          opacity: transitioning ? 0 : 1,
          transform: transitioning ? "translateY(4px)" : "translateY(0)",
          transition: "opacity 0.15s ease, transform 0.15s ease",
        }}
      >
        {renderContent()}
      </div>
    </div>
  );
}

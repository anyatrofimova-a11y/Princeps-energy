import React, { Suspense, lazy } from "react";
import Breadcrumb from "../shell/Breadcrumb";
import ProjectHeader from "../shell/ProjectHeader";
// MarketRibbon import removed (BOT-VV 2026-04-19) — duplicate live-data strip on project view. Component still lives at shell/MarketRibbon.jsx for Pulse / Markets surfaces.
import HeroMetricStrip from "../HeroMetricStrip";
import StageRibbon from "../StageRibbon";
import OverviewTab from "./OverviewTab";
import DiscoverTab from "./DiscoverTab";
import AssessTab from "./AssessTab";
import DecideTab from "./DecideTab";
import FileTab from "./FileTab";
import OperateTab from "./OperateTab";

// Verb-based IA per 2026-04-19 redesign brief: collapsed from 10 domain tabs
// to 6 verbs (Overview · Discover · Assess · Decide · File · Operate).
// Nothing deleted — every legacy panel surfaces inside one of the verb tabs.
const TABS = [
  { key: "overview", label: "Overview" },
  { key: "discover", label: "Discover" },
  { key: "assess",   label: "Assess" },
  { key: "decide",   label: "Decide" },
  { key: "file",     label: "File" },
  { key: "operate",  label: "Operate" },
];

function StubTab({ name }) {
  return (
    <div className="pp-stub">
      <div className="pp-stub-icon">◦</div>
      <div className="pp-stub-title">{name} — coming next</div>
      <div className="pp-stub-sub">This tab will wrap the existing panel for {name}.</div>
    </div>
  );
}

export default function ProjectPage({
  portfolio = null,
  project = null,
  sites = [],
  activeTab = "overview",
  activeSubTab = null,
  onTabChange = () => {},
  onNavigate = () => {},
  onPopOutTwin = () => {},
  onAddCandidate = () => {},
  onSelectSite = () => {},
  onViewMap = () => {},
  actions = null,
  mapSlot = null,
}) {
  const breadcrumbItems = [];
  if (portfolio) breadcrumbItems.push({ label: portfolio.name, href: `/p/${portfolio.portfolio_id}` });
  if (project) breadcrumbItems.push({
    label: project.name,
    href: `/p/${portfolio?.portfolio_id ?? "_"}/project/${project.project_id}`,
  });

  const projectWithCount = project && { ...project, sites_count: sites.length };

  return (
    <div className="pp-root">
      {/* MarketRibbon removed (BOT-VV 2026-04-19) — duplicate of global LiveDataStrip. */}
      <Breadcrumb items={breadcrumbItems} currentTab={activeTab} onNavigate={onNavigate} />
      {project && <ProjectHeader project={projectWithCount} actions={actions} />}
      {project && <HeroMetricStrip project={project} projectId={project.project_id} />}
      {project && (
        <StageRibbon
          project={project}
          onTabChange={(t) => onTabChange(t)}
          onDispatchChat={(prompt) => {
            if (prompt) window.dispatchEvent(new CustomEvent("princeps-chat", { detail: { text: prompt } }));
          }}
          onOpenArtefact={(key) => {
            if (key) window.dispatchEvent(new CustomEvent("princeps-file-generate", { detail: { artefact: key } }));
          }}
        />
      )}

      <nav className="pp-tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={activeTab === t.key}
            className={"pp-tab" + (activeTab === t.key ? " pp-tab-active" : "")}
            onClick={() => onTabChange(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="pp-body">
        {!project ? (
          <div className="pp-empty">
            <div className="pp-empty-title">No project selected</div>
            <div className="pp-empty-sub">Pick a project from the left rail, or create a new one.</div>
          </div>
        ) : activeTab === "overview" ? (
          <OverviewTab project={project} mapSlot={mapSlot} onViewTab={onTabChange} onViewMap={onViewMap} />
        ) : activeTab === "discover" ? (
          <DiscoverTab project={project} sites={sites} mapSlot={mapSlot} />
        ) : activeTab === "assess" ? (
          <AssessTab project={project} onPopOutTwin={onPopOutTwin} subTabHint={activeSubTab} />
        ) : activeTab === "decide" ? (
          <DecideTab project={project} />
        ) : activeTab === "file" ? (
          <FileTab project={project} />
        ) : activeTab === "operate" ? (
          <OperateTab project={project} onPopOutTwin={onPopOutTwin} />
        ) : (
          <StubTab name={TABS.find((t) => t.key === activeTab)?.label || activeTab} />
        )}
      </main>

      <style>{`
        .pp-root {
          display: flex; flex-direction: column;
          flex: 1; min-width: 0; min-height: 0;
          background: var(--bg);
        }
        .pp-tabs {
          display: flex; gap: 2px;
          padding: 0 20px;
          background: var(--cds-layer-01);
          border-bottom: 1px solid var(--cds-border-subtle);
          flex-shrink: 0;
        }
        .pp-tab {
          background: none;
          border: none;
          padding: 12px 16px;
          font-family: "DM Sans", -apple-system, sans-serif;
          font-size: 13px; font-weight: 600;
          color: var(--cds-text-secondary);
          cursor: pointer;
          border-bottom: 2px solid transparent;
          transition: all 120ms;
          margin-bottom: -1px;
        }
        .pp-tab:hover { color: var(--gold-dark); }
        .pp-tab-active {
          color: var(--ink);
          border-bottom-color: var(--gold);
        }
        .pp-body {
          flex: 1; min-height: 0; overflow: auto;
        }
        .pp-empty {
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          height: 100%; min-height: 320px;
          color: var(--cds-text-helper);
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .pp-empty-title { font-size: 18px; font-weight: 600; margin-bottom: 6px; color: var(--cds-text-secondary); }
        .pp-empty-sub { font-size: 13px; }
        .pp-stub {
          padding: 64px 24px;
          text-align: center;
          color: var(--cds-text-helper);
          font-family: "DM Sans", -apple-system, sans-serif;
        }
        .pp-stub-icon { font-size: 40px; color: var(--cds-border-strong); }
        .pp-stub-title { font-size: 16px; font-weight: 600; margin-top: 8px; color: var(--cds-text-secondary); }
        .pp-stub-sub { font-size: 13px; margin-top: 6px; }
        .pp-panel-wrap {
          padding: 20px 24px;
          min-height: 100%;
        }
        .pp-panel-wrap > * {
          position: relative !important;
          inset: auto !important;
          width: 100% !important;
          height: auto !important;
          max-width: none !important;
          box-shadow: none !important;
        }
      `}</style>
    </div>
  );
}

/**
 * PortfolioDashboardV2 — "Decision Cockpit" V3
 *
 * Premium layout with animated components:
 *   [ Command Bar ]
 *   [ Live Intelligence Strip ]
 *   [ HERO: Portfolio Performance (70%) + Health Dial (30%) ]
 *   [ ACTION ROW: Recommended Next Steps ]
 *   [ WORKSPACE TABS: Projects | Site Search | Regulations | Scenarios ]
 *   [ Quick Actions Grid ]
 */
import React, { useState, useEffect, useCallback } from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import api from "../../services/api";

import CommandBar from "./CommandBar";
import LiveIntelligenceStrip from "./LiveIntelligenceStrip";
import PortfolioHero from "./PortfolioHero";
import ActionRow from "./ActionRow";
import WorkspaceTabs from "./WorkspaceTabs";
import QuickActionsGrid from "./QuickActionsGrid";

import "./dashboard.css";

const DEMO_SITES = [
  { id: "1", name: "Highland Wind", technology: "wind", capacity_mw: 50, phase: "operational", score: 78, verdict: "GO", irr: 24.1, status: "operational" },
  { id: "2", name: "Midlands Solar", technology: "solar", capacity_mw: 30, phase: "installation", score: 72, verdict: "GO", irr: 19.8, status: "in_progress" },
  { id: "3", name: "Slough DC", technology: "datacentre", capacity_mw: 15, phase: "grid_study", score: 64, verdict: "CAUTION", irr: 15.2, status: "at_risk" },
  { id: "4", name: "Kent BESS", technology: "bess", capacity_mw: 40, phase: "planning", score: 81, verdict: "GO", irr: 28.3, status: "at_risk" },
  { id: "5", name: "Norfolk Solar", technology: "solar", capacity_mw: 25, phase: "feasibility", score: 55, verdict: "CAUTION", irr: 12.1, status: "in_progress" },
];

class DashboardErrorBoundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, textAlign: "center", color: "#B5432A" }}>
          <h3>Dashboard failed to load</h3>
          <pre style={{ fontSize: 11, color: "#6B6560", maxWidth: 600, margin: "12px auto", textAlign: "left", overflow: "auto" }}>
            {this.state.error.message}
          </pre>
          <button onClick={() => this.setState({ error: null })} style={{ marginTop: 12, padding: "8px 16px", background: "#F5B731", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer" }}>
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function PortfolioDashboardInner() {
  const { navigateToIntent, setActiveViewMode } = useWorkspace();
  const { setPickedLocation } = useSite();

  const [projects, setProjects] = useState(DEMO_SITES);
  const [portfolio, setPortfolio] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [projData, summaryData] = await Promise.allSettled([
          api.projects?.list?.({ limit: 50 }),
          api.sustainability?.portfolioSummary?.(DEMO_SITES),
        ]);
        if (cancelled) return;
        if (projData.status === "fulfilled" && projData.value?.length) setProjects(projData.value);
        if (summaryData.status === "fulfilled" && summaryData.value) setPortfolio(summaryData.value);
      } catch {}
    })();
    return () => { cancelled = true; };
  }, []);

  const totalMw = projects.reduce((s, p) => s + (p.capacity_mw || 0), 0);
  const goCount = projects.filter(p => p.verdict === "GO").length;
  const cautionCount = projects.filter(p => p.verdict === "CAUTION").length;
  const nogoCount = projects.filter(p => p.verdict === "NO-GO").length;
  const avgScore = projects.length ? Math.round(projects.reduce((s, p) => s + (p.score || 0), 0) / projects.length) : 0;
  const avgIrr = projects.length ? projects.reduce((s, p) => s + (p.irr || 0), 0) / projects.length : 0;
  const annualGwh = portfolio?.total_annual_gen_mwh ? Math.round(portfolio.total_annual_gen_mwh / 1000) : Math.round(totalMw * 0.11 * 8760 / 1000);

  const handleSiteSelect = useCallback((site) => {
    if (site?.lat && site?.lon) setPickedLocation({ lat: site.lat, lon: site.lon });
    setActiveViewMode("map");
  }, [setPickedLocation, setActiveViewMode]);

  const handleAction = useCallback((intent) => {
    navigateToIntent(intent);
  }, [navigateToIntent]);

  return (
    <div className="princeps-dashboard">
      <CommandBar onSelect={handleSiteSelect} onAction={handleAction} />
      <LiveIntelligenceStrip />
      <PortfolioHero
        totalMw={totalMw}
        annualGwh={annualGwh}
        irr={avgIrr || 23.4}
        avgScore={avgScore}
        goCount={goCount}
        cautionCount={cautionCount}
        nogoCount={nogoCount}
        projectCount={projects.length}
      />
      <ActionRow onAction={handleAction} />
      <WorkspaceTabs
        projects={projects}
        onSiteSelect={handleSiteSelect}
        onSearchRegion={() => setActiveViewMode("map")}
        onViewProject={handleSiteSelect}
        onAssessProject={() => handleAction("feasibility")}
        onAction={handleAction}
      />
      <QuickActionsGrid onAction={handleAction} />
    </div>
  );
}

export default function PortfolioDashboardV2() {
  return (
    <DashboardErrorBoundary>
      <PortfolioDashboardInner />
    </DashboardErrorBoundary>
  );
}

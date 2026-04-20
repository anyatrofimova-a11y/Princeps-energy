import React, { useEffect } from "react";
import { useWorkspace, WORKSPACES, WORKSPACE_VIEWS } from "../../contexts/WorkspaceContext";
import Sidebar from "./Sidebar";
import LiveDataStrip from "./LiveDataStrip";
import HeadroomTicker from "./HeadroomTicker";

// Project-detail view ("projects") owns its own KPI surface (project hero,
// HeroMetricStrip, StageRibbon). The global LiveDataStrip becomes ambient
// noise on top of project-specific numbers and previously fought with the
// MarketRibbon for attention. Hide it there. (BOT-VV, 2026-04-19)
const HIDE_LIVE_STRIP_VIEWS = new Set(["projects"]);

export default function AppShell({ children, onGridTwin, onBems, onAssetInspect, onGridGraph, onBessFacility, onHardware, onThermal, onPitch, onCapabilities, onNomExplorer, onSettings, onCommandPalette, onDcTwin, onPipeline, onIntelligence }) {
  const { toggleBrowser, toggleDetail, setActiveWorkspace, activeWorkspace, activeViewMode, setActiveViewMode } = useWorkspace();

  const hideLiveStrip = HIDE_LIVE_STRIP_VIEWS.has(activeViewMode);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      if (e.ctrlKey && e.key === "b") { e.preventDefault(); toggleBrowser(); }
      if (e.ctrlKey && e.key === "d") { e.preventDefault(); toggleDetail(); }
      if (e.ctrlKey && !e.shiftKey && e.key >= "1" && e.key <= "6") {
        e.preventDefault();
        const idx = parseInt(e.key) - 1;
        if (WORKSPACES[idx]) setActiveWorkspace(WORKSPACES[idx].id);
      }
      if (e.ctrlKey && e.shiftKey && e.key >= "1" && e.key <= "8") {
        e.preventDefault();
        const views = WORKSPACE_VIEWS[activeWorkspace];
        if (views) {
          const idx = parseInt(e.key) - 1;
          if (views[idx]) setActiveViewMode(views[idx]);
        }
      }
      if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
        const searchInput = document.querySelector(".gat-search input");
        if (searchInput) { e.preventDefault(); searchInput.focus(); }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleBrowser, toggleDetail, setActiveWorkspace, setActiveViewMode, activeWorkspace]);

  return (
    <div style={{
      display: "flex",
      width: "100vw",
      height: "100vh",
      overflow: "hidden",
      background: "#F7F8FA",
    }}>
      <Sidebar
        onGridTwin={onGridTwin}
        onDcTwin={onDcTwin}
        onBessFacility={onBessFacility}
        onPipeline={onPipeline}
      />
      <div style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        minWidth: 0,
      }}>
        {/* Godmode #1 — Headroom-Now ticker (auto-hides while connecting) */}
        <HeadroomTicker />

        {/* COUNCIL-5 / BOT-RR: hard-coded "Portfolio > Dashboard" breadcrumb +
            New Project button + bell removed. The dynamic Breadcrumb in
            ProjectPage.jsx is the single source of truth on project views;
            other views own their own header chrome. */}

        {/* Main content */}
        <div style={{ flex: 1, overflow: "auto", position: "relative" }}>
          {children}
        </div>

        {/* Live data strip — global ambient context. Hidden on project-detail
            views (own KPI surface dominates). See HIDE_LIVE_STRIP_VIEWS. */}
        {!hideLiveStrip && <LiveDataStrip />}
      </div>
    </div>
  );
}

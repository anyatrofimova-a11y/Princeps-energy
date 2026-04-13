import React, { useEffect } from "react";
import { useWorkspace, WORKSPACES, WORKSPACE_VIEWS } from "../../contexts/WorkspaceContext";
import Sidebar from "./Sidebar";
import LiveDataStrip from "./LiveDataStrip";

export default function AppShell({ children, onGridTwin, onBems, onAssetInspect, onGridGraph, onBessFacility, onHardware, onThermal, onPitch, onCapabilities, onNomExplorer, onSettings, onCommandPalette, onDcTwin, onPipeline, onIntelligence, onSiteDesigner }) {
  const { toggleBrowser, toggleDetail, setActiveWorkspace, activeWorkspace, setActiveViewMode } = useWorkspace();

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
        onSiteDesigner={onSiteDesigner}
      />
      <div style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        minWidth: 0,
      }}>
        {/* Breadcrumb bar */}
        <div style={{
          display: "flex",
          alignItems: "center",
          padding: "10px 24px",
          background: "#FFFFFF",
          borderBottom: "1px solid #E8E5DF",
          flexShrink: 0,
          gap: 12,
        }}>
          <span style={{ fontSize: 13, color: "#6B6560" }}>Portfolio</span>
          <span style={{ fontSize: 13, color: "#9C9590" }}>&gt;</span>
          <span style={{ fontSize: 13, color: "#E8A012", fontWeight: 600 }}>Dashboard</span>
          <div style={{ flex: 1 }} />
          <button
            style={{
              padding: "7px 16px",
              fontSize: 12,
              fontWeight: 600,
              background: "#F5B731",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              cursor: "pointer",
              fontFamily: "'DM Sans', sans-serif",
              display: "flex",
              alignItems: "center",
              gap: 5,
            }}
          >
            + New Project
          </button>
          <div style={{ position: "relative", cursor: "pointer", padding: 4 }}>
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="#6B6560" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7.5 15.5a1.5 1.5 0 003 0M9 2a5 5 0 00-5 5c0 2.5-1 4-1.5 4.5h13c-.5-.5-1.5-2-1.5-4.5a5 5 0 00-5-5z" />
            </svg>
            <span style={{
              position: "absolute",
              top: 0,
              right: 0,
              width: 16,
              height: 16,
              borderRadius: "50%",
              background: "#B5432A",
              color: "#fff",
              fontSize: 9,
              fontWeight: 700,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}>
              3
            </span>
          </div>
        </div>

        {/* Main content */}
        <div style={{ flex: 1, overflow: "auto", position: "relative" }}>
          {children}
        </div>

        {/* Live data strip */}
        <LiveDataStrip />
      </div>
    </div>
  );
}

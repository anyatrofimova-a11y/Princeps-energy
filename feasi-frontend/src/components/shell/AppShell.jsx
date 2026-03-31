import React, { useEffect } from "react";
import { useWorkspace, WORKSPACES, WORKSPACE_VIEWS } from "../../contexts/WorkspaceContext";
import NavRail from "./NavRail";
import TopStatusBar from "./TopStatusBar";
import LiveDataStrip from "./LiveDataStrip";
import GridCanvas from "../GridCanvas";

export default function AppShell({ children, onGridTwin, onBems, onAssetInspect, onGridGraph, onBessFacility, onHardware, onThermal, onPitch, onNomExplorer, onSettings, onCommandPalette, onDcTwin, onPipeline, onIntelligence, onSiteDesigner }) {
  const { toggleBrowser, toggleDetail, setActiveWorkspace, activeWorkspace, setActiveViewMode } = useWorkspace();

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      // Ctrl+B — toggle browser
      if (e.ctrlKey && e.key === "b") {
        e.preventDefault();
        toggleBrowser();
      }
      // Ctrl+D — toggle detail
      if (e.ctrlKey && e.key === "d") {
        e.preventDefault();
        toggleDetail();
      }
      // Ctrl+1-6 — switch workspace
      if (e.ctrlKey && !e.shiftKey && e.key >= "1" && e.key <= "6") {
        e.preventDefault();
        const idx = parseInt(e.key) - 1;
        if (WORKSPACES[idx]) {
          setActiveWorkspace(WORKSPACES[idx].id);
        }
      }
      // Ctrl+Shift+1-8 — switch grid workspace views
      if (e.ctrlKey && e.shiftKey && e.key >= "1" && e.key <= "8") {
        e.preventDefault();
        const views = WORKSPACE_VIEWS[activeWorkspace];
        if (views) {
          const idx = parseInt(e.key) - 1;
          if (views[idx]) {
            setActiveViewMode(views[idx]);
          }
        }
      }
      // Escape — deselect (handled by grid model context if available)
      // / — focus search in asset tree
      if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
        const searchInput = document.querySelector(".gat-search input");
        if (searchInput) {
          e.preventDefault();
          searchInput.focus();
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleBrowser, toggleDetail, setActiveWorkspace, setActiveViewMode, activeWorkspace]);

  return (
    <div className="app-shell">
      <div className="app-shell-bg">
        <GridCanvas dark />
      </div>
      <NavRail />
      <div className="app-shell-main">
        <TopStatusBar
          onGridTwin={onGridTwin}
          onBems={onBems}
          onAssetInspect={onAssetInspect}
          onGridGraph={onGridGraph}
          onBessFacility={onBessFacility}
          onHardware={onHardware}
          onThermal={onThermal}
          onPitch={onPitch}
          onNomExplorer={onNomExplorer}
          onSettings={onSettings}
          onCommandPalette={onCommandPalette}
          onDcTwin={onDcTwin}
          onPipeline={onPipeline}
          onIntelligence={onIntelligence}
          onSiteDesigner={onSiteDesigner}
        />
        {children}
        <LiveDataStrip />
      </div>
    </div>
  );
}

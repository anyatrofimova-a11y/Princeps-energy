import React, { useEffect } from "react";
import { useWorkspace, WORKSPACES } from "../../contexts/WorkspaceContext";
import NavRail from "./NavRail";
import TopStatusBar from "./TopStatusBar";

export default function AppShell({ children, onGridTwin, onPitch, onNomExplorer, onSettings }) {
  const { toggleBrowser, toggleDetail, setActiveWorkspace } = useWorkspace();

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
      if (e.ctrlKey && e.key >= "1" && e.key <= "6") {
        e.preventDefault();
        const idx = parseInt(e.key) - 1;
        if (WORKSPACES[idx]) {
          setActiveWorkspace(WORKSPACES[idx].id);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [toggleBrowser, toggleDetail, setActiveWorkspace]);

  return (
    <div className="app-shell">
      <NavRail />
      <div className="app-shell-main">
        <TopStatusBar
          onGridTwin={onGridTwin}
          onPitch={onPitch}
          onNomExplorer={onNomExplorer}
          onSettings={onSettings}
        />
        {children}
      </div>
    </div>
  );
}

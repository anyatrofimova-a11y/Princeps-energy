import React, { useState, useEffect, useRef, useCallback } from "react";
import { useWorkspace, WORKSPACES } from "../../contexts/WorkspaceContext";

const COMMANDS = [
  { id: "ws-home", label: "Go to Home", section: "Workspaces", icon: "home", action: "workspace", value: "home" },
  { id: "ws-grid", label: "Go to Grid", section: "Workspaces", icon: "bolt", action: "workspace", value: "grid" },
  { id: "ws-feasibility", label: "Go to Feasibility", section: "Workspaces", icon: "sun", action: "workspace", value: "feasibility" },
  { id: "ws-environment", label: "Go to Environment", section: "Workspaces", icon: "leaf", action: "workspace", value: "environment" },
  { id: "ws-operations", label: "Go to Operations", section: "Workspaces", icon: "gear", action: "workspace", value: "operations" },
  { id: "ws-investment", label: "Go to Investment", section: "Workspaces", icon: "briefcase", action: "workspace", value: "investment" },
  { id: "act-twin", label: "Open Grid Twin", section: "Actions", action: "twin" },
  { id: "act-bems", label: "Open BEMS Digital Twin", section: "Actions", action: "bems" },
  { id: "act-inspect", label: "Open Asset Inspector", section: "Actions", action: "inspect" },
  { id: "act-graph", label: "Open Grid Graph Topology", section: "Actions", action: "graph" },
  { id: "act-bess-facility", label: "Open BESS Facility Twin", section: "Actions", action: "bess-facility" },
  { id: "act-dc-twin", label: "Open Data Centre Twin", section: "Actions", action: "dc-twin" },
  { id: "act-hardware", label: "Open Hardware Configurator", section: "Actions", action: "hardware" },
  { id: "act-thermal", label: "Open Thermal Model (TEASER)", section: "Actions", action: "thermal" },
  { id: "act-pitch", label: "Open Pitch Deck", section: "Actions", action: "pitch" },
  { id: "act-nom", label: "Open NOM Explorer", section: "Actions", action: "nom" },
  { id: "act-compare", label: "Compare Scenarios", section: "Actions", action: "compare" },
  { id: "act-pdf", label: "Download PDF Report", section: "Actions", action: "pdf" },
  { id: "act-settings", label: "Open Settings", section: "Actions", action: "settings" },
  { id: "act-browser", label: "Toggle Asset Browser", section: "Actions", action: "browser", shortcut: "Ctrl+B" },
  { id: "act-detail", label: "Toggle Detail Panel", section: "Actions", action: "detail", shortcut: "Ctrl+D" },
  { id: "act-asset3d", label: "Gemini 3D Asset Modeller", section: "AI Tools", action: "asset-3d" },
  { id: "act-wizard", label: "Site Assessment Wizard", section: "AI Tools", action: "wizard" },
  { id: "act-dashboard", label: "Open Live Dashboard", section: "AI Tools", action: "dashboard" },
  { id: "act-dc-score", label: "Score DC Site", section: "Data Centre", action: "dc-score" },
  { id: "act-dc-compare", label: "Compare DC Sites", section: "Data Centre", action: "dc-compare" },
  { id: "act-dc-report", label: "Generate DC Report", section: "Data Centre", action: "dc-report" },
  { id: "act-dc-landing", label: "Open DC Landing Page", section: "Data Centre", action: "dc-landing" },
  { id: "act-gate", label: "Gate Readiness Dashboard", section: "Grid Connection", action: "gate-readiness" },
  { id: "act-g99", label: "G99/G100 Compliance Check", section: "Grid Connection", action: "g99" },
  { id: "act-compare", label: "Compare Sites (Bloomberg-style)", section: "Analysis", action: "site-compare" },
  { id: "act-export-pdf", label: "Export Site Report (PDF)", section: "Export", action: "export-pdf" },
  { id: "act-export-csv", label: "Export Sites (CSV/Excel)", section: "Export", action: "export-csv" },
  { id: "act-intel", label: "Regulatory Intelligence Feed", section: "Intelligence", action: "intelligence" },
];

export default function CommandPalette({ open, onClose, onAction }) {
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef(null);
  const { setActiveWorkspace } = useWorkspace();

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIdx(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const filtered = query.trim()
    ? COMMANDS.filter(c => c.label.toLowerCase().includes(query.toLowerCase()))
    : COMMANDS;

  const sections = {};
  filtered.forEach(c => {
    if (!sections[c.section]) sections[c.section] = [];
    sections[c.section].push(c);
  });

  const flatFiltered = filtered;

  const execute = useCallback((cmd) => {
    if (cmd.action === "workspace") {
      setActiveWorkspace(cmd.value);
    } else if (onAction) {
      onAction(cmd.action);
    }
    onClose();
  }, [setActiveWorkspace, onAction, onClose]);

  const handleKeyDown = (e) => {
    if (e.key === "Escape") { onClose(); return; }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx(i => Math.min(i + 1, flatFiltered.length - 1));
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx(i => Math.max(i - 1, 0));
    }
    if (e.key === "Enter" && flatFiltered[selectedIdx]) {
      execute(flatFiltered[selectedIdx]);
    }
  };

  if (!open) return null;

  return (
    <div className="cmd-palette-overlay" onClick={onClose}>
      <div className="cmd-palette" onClick={e => e.stopPropagation()}>
        <div className="cmd-palette-input-wrap">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
          </svg>
          <input
            ref={inputRef}
            className="cmd-palette-input"
            value={query}
            onChange={e => { setQuery(e.target.value); setSelectedIdx(0); }}
            onKeyDown={handleKeyDown}
            placeholder="Type a command or search..."
          />
          <kbd className="cmd-palette-esc">ESC</kbd>
        </div>
        <div className="cmd-palette-list">
          {Object.entries(sections).map(([section, cmds]) => (
            <div key={section}>
              <div className="cmd-palette-section">{section}</div>
              {cmds.map(cmd => {
                const idx = flatFiltered.indexOf(cmd);
                return (
                  <button
                    key={cmd.id}
                    className={`cmd-palette-item${idx === selectedIdx ? " selected" : ""}`}
                    onClick={() => execute(cmd)}
                    onMouseEnter={() => setSelectedIdx(idx)}
                  >
                    <span className="cmd-palette-item-label">{cmd.label}</span>
                    {cmd.shortcut && <kbd className="cmd-palette-kbd">{cmd.shortcut}</kbd>}
                  </button>
                );
              })}
            </div>
          ))}
          {flatFiltered.length === 0 && (
            <div className="cmd-palette-empty">No results found</div>
          )}
        </div>
      </div>
    </div>
  );
}

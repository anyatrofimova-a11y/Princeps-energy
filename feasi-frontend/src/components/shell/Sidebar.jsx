import React, { useState } from "react";
import { useWorkspace, WORKSPACES } from "../../contexts/WorkspaceContext";
import SettingsPanel from "./SettingsPanel";

const C = {
  gold: "#F5B731", goldDark: "#E8A012", goldSurface: "rgba(245,183,49,0.06)",
  goldBorder: "rgba(245,183,49,0.25)",
  ink: "#1A1714", secondary: "#6B6560", tertiary: "#9C9590",
  border: "#E8E5DF", card: "#FFFFFF", bg: "#F7F8FA",
};

/* ── SVG Icons (16px) ────────────────────────────────────────── */
const I = {
  grid: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/></svg>,
  folder: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><path d="M2 4.5A1.5 1.5 0 013.5 3H6l1.5 2h5A1.5 1.5 0 0114 6.5V12a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 12V4.5z"/></svg>,
  kanban: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><path d="M3 2v12M8 2v8M13 2v10"/></svg>,
  map: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><path d="M8 2C5.8 2 4 3.8 4 6c0 3 4 8 4 8s4-5 4-8c0-2.2-1.8-4-4-4z"/><circle cx="8" cy="6" r="1.5"/></svg>,
  layout: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><rect x="2" y="2" width="12" height="12" rx="1"/><path d="M2 6h12M6 6v8"/></svg>,
  bolt: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"><path d="M9 1.5L3 9h5l-.5 5.5L14 7H9l.5-5.5z"/></svg>,
  chart: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><path d="M2 2v12h12"/><path d="M5 10l3-4 3 2 3-4"/></svg>,
  clipboard: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><rect x="3" y="2" width="10" height="12" rx="1.5"/><path d="M6 2V1h4v1"/><path d="M6 7h4M6 10h2"/></svg>,
  trending: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><path d="M2 12l4-5 3 2.5 5-6"/><path d="M11 3.5H14V6.5"/></svg>,
  candle: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><path d="M4 4v8M4 6h0M8 3v10M8 5h0M12 5v6M12 7h0"/><rect x="3" y="6" width="2" height="4" rx="0.5"/><rect x="7" y="5" width="2" height="5" rx="0.5"/><rect x="11" y="7" width="2" height="3" rx="0.5"/></svg>,
  doc: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><path d="M9 1.5H4.5A1.5 1.5 0 003 3v10a1.5 1.5 0 001.5 1.5h7A1.5 1.5 0 0013 13V5.5L9 1.5z"/><path d="M9 1.5V5.5h4"/></svg>,
  cube: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"><path d="M8 1.5L14 5v6l-6 3.5L2 11V5L8 1.5z"/><path d="M8 8.5V15M8 8.5L2 5M8 8.5L14 5"/></svg>,
  users: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><circle cx="6" cy="5" r="2.5"/><path d="M1.5 14c0-2.5 2-4.5 4.5-4.5s4.5 2 4.5 4.5"/><circle cx="11.5" cy="5.5" r="1.8"/><path d="M14.5 14c0-2 -1.3-3.5-3-3.5"/></svg>,
  bell: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><path d="M6.5 13.5a1.5 1.5 0 003 0"/><path d="M8 2a4 4 0 00-4 4c0 2-1 3.5-1.5 4h11c-.5-.5-1.5-2-1.5-4a4 4 0 00-4-4z"/></svg>,
  key: <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><circle cx="5.5" cy="10.5" r="3"/><path d="M8 8l6-6M11 5l2 2"/></svg>,
  search: <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"><circle cx="7" cy="7" r="5"/><path d="M11 11l3.5 3.5"/></svg>,
  chevron: <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M3 1.5L7 5L3 8.5"/></svg>,
};

const NAV_SECTIONS = [
  {
    id: "portfolio", label: "PORTFOLIO",
    items: [
      { id: "home", label: "Dashboard", icon: I.grid, workspace: "home", viewMode: "dashboard" },
      { id: "projects", label: "Projects", icon: I.folder, workspace: "home", viewMode: "projects" },
      { id: "pipeline", label: "Pipeline", icon: I.kanban, workspace: "pipeline" },
      { id: "map", label: "Map", icon: I.map, workspace: "home", viewMode: "map" },
    ],
  },
  {
    id: "analysis", label: "ANALYSIS",
    items: [
      { id: "designer", label: "Site Designer", icon: I.layout, workspace: "design" },
      { id: "grid", label: "Grid Connection", icon: I.bolt, workspace: "analyse", intent: "grid_connection" },
      { id: "financial", label: "Financial Model", icon: I.chart, workspace: "analyse", intent: "financial" },
      { id: "planning", label: "Planning", icon: I.clipboard, workspace: "analyse", intent: "planning" },
      { id: "demand", label: "Demand Forecast", icon: I.trending, workspace: "analyse", intent: "demand_forecast" },
    ],
  },
  {
    id: "twins", label: "DIGITAL TWINS",
    items: [
      { id: "gridtwin", label: "Grid Twin", icon: I.cube, action: "gridtwin" },
      { id: "dctwin", label: "DC Twin", icon: I.layout, action: "dctwin" },
      { id: "besstwin", label: "BESS Twin", icon: I.bolt, action: "besstwin" },
    ],
  },
  {
    id: "intelligence", label: "INTELLIGENCE",
    items: [
      { id: "market", label: "Market Data", icon: I.candle, workspace: "home" },
      { id: "regulatory", label: "Regulatory", icon: I.doc, workspace: "home" },
    ],
  },
];

const SETTINGS_ITEMS = [
  { id: "team", label: "Team", icon: I.users },
  { id: "notifications", label: "Notifications", icon: I.bell },
  { id: "apikeys", label: "API Keys", icon: I.key },
];

function NavItem({ item, active, onClick }) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "8px 12px 8px 16px",
        border: "none",
        borderLeft: active ? `3px solid ${C.gold}` : "3px solid transparent",
        background: active ? C.goldSurface : hovered ? "rgba(245,183,49,0.03)" : "transparent",
        color: active ? C.ink : hovered ? C.ink : C.secondary,
        fontWeight: active ? 600 : 500,
        fontSize: 13,
        fontFamily: "'DM Sans', sans-serif",
        cursor: "pointer",
        borderRadius: "0 6px 6px 0",
        transition: "all 0.12s ease",
        textAlign: "left",
      }}
    >
      <span style={{ color: active ? C.gold : C.tertiary, flexShrink: 0, display: "flex" }}>
        {item.icon}
      </span>
      {item.label}
    </button>
  );
}

function SectionHeader({ label, collapsed, onToggle }) {
  return (
    <div
      onClick={onToggle}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "12px 12px 4px 16px",
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      <span style={{
        transform: collapsed ? "rotate(0)" : "rotate(90deg)",
        transition: "transform 0.15s",
        color: C.tertiary,
        display: "flex",
      }}>
        {I.chevron}
      </span>
      <span style={{
        fontSize: 10,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        color: C.tertiary,
        flex: 1,
      }}>
        {label}
      </span>
    </div>
  );
}

export default function Sidebar({ onGridTwin, onPipeline, onSiteDesigner, onDcTwin, onBessFacility }) {
  const { activeWorkspace, setActiveWorkspace, navigateToIntent, setActiveViewMode } = useWorkspace();
  const [collapsed, setCollapsed] = useState({});
  const [activeItem, setActiveItem] = useState("home");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState("team");

  const handleNav = (item) => {
    setActiveItem(item.id);
    if (item.workspace) setActiveWorkspace(item.workspace);
    if (item.viewMode) setActiveViewMode(item.viewMode);
    if (item.intent) navigateToIntent?.(item.intent);

    // Special handlers
    if (item.action === "gridtwin") onGridTwin?.();
    if (item.action === "dctwin") onDcTwin?.();
    if (item.action === "besstwin") onBessFacility?.();
    if (item.id === "pipeline") onPipeline?.();
    if (item.id === "designer") onSiteDesigner?.();
  };

  const toggleSection = (id) => {
    setCollapsed(prev => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <nav style={{
      width: 240,
      height: "100vh",
      background: C.card,
      borderRight: `1px solid ${C.border}`,
      display: "flex",
      flexDirection: "column",
      flexShrink: 0,
      overflow: "hidden",
      zIndex: 100,
    }}>
      {/* Logo */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "16px 16px 12px",
        borderBottom: `1px solid ${C.border}`,
        flexShrink: 0,
      }}>
        <img
          src="/logo-princeps.png"
          alt="Princeps"
          style={{ width: 28, height: 28, objectFit: "contain" }}
          onError={(e) => { e.target.style.display = "none"; }}
        />
        <span style={{
          fontSize: 16,
          fontWeight: 800,
          color: C.ink,
          letterSpacing: "-0.02em",
        }}>
          PRINCEPS
        </span>
      </div>

      {/* Search */}
      <div style={{ padding: "10px 12px 6px", flexShrink: 0 }}>
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "7px 10px",
          background: C.bg,
          border: `1px solid ${C.border}`,
          borderRadius: 8,
          cursor: "text",
        }}>
          <span style={{ color: C.tertiary, display: "flex" }}>{I.search}</span>
          <span style={{ fontSize: 12, color: C.tertiary }}>Search...</span>
          <span style={{
            marginLeft: "auto",
            fontSize: 10,
            color: C.tertiary,
            background: C.card,
            border: `1px solid ${C.border}`,
            padding: "1px 5px",
            borderRadius: 4,
            fontFamily: "var(--mono), monospace",
          }}>
            /
          </span>
        </div>
      </div>

      {/* Navigation */}
      <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
        {NAV_SECTIONS.map(section => (
          <div key={section.id}>
            <SectionHeader
              label={section.label}
              collapsed={collapsed[section.id]}
              onToggle={() => toggleSection(section.id)}
            />
            {!collapsed[section.id] && section.items.map(item => (
              <NavItem
                key={item.id}
                item={item}
                active={activeItem === item.id}
                onClick={() => handleNav(item)}
              />
            ))}
          </div>
        ))}

        {/* Settings at bottom */}
        <div style={{ marginTop: 16 }}>
          <SectionHeader
            label="SETTINGS"
            collapsed={collapsed.settings}
            onToggle={() => toggleSection("settings")}
          />
          {!collapsed.settings && SETTINGS_ITEMS.map(item => (
            <NavItem
              key={item.id}
              item={item}
              active={activeItem === item.id}
              onClick={() => {
                setActiveItem(item.id);
                setSettingsTab(item.id === "apikeys" ? "apikeys" : item.id);
                setSettingsOpen(true);
              }}
            />
          ))}
        </div>
      </div>

      {/* User */}
      <div style={{
        padding: "12px 16px",
        borderTop: `1px solid ${C.border}`,
        display: "flex",
        alignItems: "center",
        gap: 10,
        flexShrink: 0,
      }}>
        <div style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: C.goldSurface,
          border: `1.5px solid ${C.goldBorder}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 10,
          fontWeight: 700,
          color: C.goldDark,
        }}>
          AT
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.ink }}>Anya T.</div>
          <div style={{ fontSize: 10, color: C.tertiary }}>Admin</div>
        </div>
      </div>
      <SettingsPanel
        open={settingsOpen}
        activeTab={settingsTab}
        onTabChange={setSettingsTab}
        onClose={() => setSettingsOpen(false)}
      />
    </nav>
  );
}

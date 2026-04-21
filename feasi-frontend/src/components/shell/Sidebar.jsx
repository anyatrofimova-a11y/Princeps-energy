import React, { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import SettingsPanel from "./SettingsPanel";
import ProjectTree from "./ProjectTree";
import { getPortfolioTree } from "../../services/portfolios";
import useAlerts from "../../hooks/useAlerts";

// ── Light-gold palette (2026-04 redesign) ──────────────────────
const C = {
  gold: "#C9A64B",
  goldStrong: "#B5912F",
  goldSurface: "rgba(201,166,75,0.10)",
  goldBorder: "rgba(201,166,75,0.30)",
  cream: "#F5E9C8",
  ink: "#1a1a1a",
  secondary: "#6B6560",
  tertiary: "#9C9590",
  border: "#E8E5DF",
  card: "#FFFFFF",
  bg: "#F7F8FA",
};

// ── Icons (16px stroked) ───────────────────────────────────────
const I = {
  mission: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="5" height="5" rx="1" />
      <rect x="9" y="2" width="5" height="5" rx="1" />
      <rect x="2" y="9" width="5" height="5" rx="1" />
      <rect x="9" y="9" width="5" height="5" rx="1" />
    </svg>
  ),
  folder: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4.5A1.5 1.5 0 013.5 3H6l1.5 2h5A1.5 1.5 0 0114 6.5V12a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 012 12V4.5z" />
    </svg>
  ),
  map: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 4l4-2 4 2 4-2v10l-4 2-4-2-4 2V4z" />
      <path d="M6 2v10M10 4v10" />
    </svg>
  ),
  cube: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" strokeLinecap="round">
      <path d="M8 1.5L14 5v6l-6 3.5L2 11V5L8 1.5z" />
      <path d="M8 8.5V15M8 8.5L2 5M8 8.5L14 5" />
    </svg>
  ),
  siteCube: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" strokeLinecap="round">
      <rect x="2.5" y="6.5" width="11" height="7" rx="0.5" />
      <path d="M2.5 6.5L8 3l5.5 3.5" />
      <path d="M5 9.5h1.5M8.75 9.5h2.25M5 11.5h1.5M8.75 11.5h2.25" />
    </svg>
  ),
  chat: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.5 3h11A1.5 1.5 0 0115 4.5v6a1.5 1.5 0 01-1.5 1.5H6l-3 3v-3H2.5A1.5 1.5 0 011 10.5v-6A1.5 1.5 0 012.5 3z" />
    </svg>
  ),
  gear: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.5v1.8M8 12.7v1.8M1.5 8h1.8M12.7 8h1.8M3.4 3.4l1.3 1.3M11.3 11.3l1.3 1.3M3.4 12.6l1.3-1.3M11.3 4.7l1.3-1.3" />
    </svg>
  ),
  chevron: (
    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 1.5L7 5L3 8.5" />
    </svg>
  ),
  bell: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 10.5V7a4 4 0 018 0v3.5l1 1.5H3l1-1.5z" />
      <path d="M6.5 13.5a1.5 1.5 0 003 0" />
    </svg>
  ),
  docket: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="2.5" width="10" height="11" rx="1" />
      <path d="M5.5 6h5M5.5 8.5h5M5.5 11h3" />
    </svg>
  ),
  dataset: (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="8" cy="4" rx="5" ry="1.8" />
      <path d="M3 4v4c0 1 2.2 1.8 5 1.8s5-.8 5-1.8V4" />
      <path d="M3 8v4c0 1 2.2 1.8 5 1.8s5-.8 5-1.8V8" />
    </svg>
  ),
};

// ── Nav items — exactly what the brief asks for ────────────────
//   (a) Mission Control, (b) Projects, (c) Map, (d) Grid Twin,
//   (e) Chat, (f) Settings. Nothing else.
const NAV_ITEMS = [
  { id: "mission",      label: "Mission Control", icon: I.mission },
  { id: "projects",     label: "Projects",        icon: I.folder, collapsible: true },
  { id: "map",          label: "Map",             icon: I.map },
  // Intelligence group — three children expand below (Alerts bell has an
  // unread count badge injected at render time).
  { id: "intelligence", label: "Intelligence",    icon: I.bell,   collapsible: true, badge: true },
  { id: "gridtwin",     label: "Grid Twin",       icon: I.cube },
  // "Site Designer 3D" disambiguates from Grid Twin (network-scale) and matches
  // the underlying /design/:projectId page (DesignCanvas.jsx). Was: "Site Twin".
  { id: "sitetwin",     label: "Site Designer 3D", icon: I.siteCube, disabledHint: "select project ↗" },
  { id: "chat",         label: "Chat",            icon: I.chat },
  { id: "settings",     label: "Settings",        icon: I.gear },
];

// Children rendered under the Intelligence group when expanded.
const INTEL_CHILDREN = [
  { id: "alerts",   label: "Alerts",   icon: I.bell,    to: "/intelligence/alerts" },
  { id: "dockets",  label: "Dockets",  icon: I.docket,  to: "/intelligence/dockets" },
  { id: "datasets", label: "Datasets", icon: I.dataset, to: "/intelligence/datasets" },
];

// ────────────────────────────────────────────────────────────────
function NavRow({ item, active, expanded, onClick, onToggleExpand, badgeCount, disabled, disabledTooltip, disabledHint, onDisabledClick }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", alignItems: "stretch",
        borderLeft: active ? `3px solid ${C.gold}` : "3px solid transparent",
        background: active ? C.goldSurface : (hovered && !disabled) ? "rgba(201,166,75,0.04)" : "transparent",
        opacity: disabled ? 0.55 : 1,
        cursor: disabled ? "not-allowed" : "default",
      }}
      title={disabled ? disabledTooltip : undefined}
    >
      <button
        onClick={disabled ? onDisabledClick : onClick}
        aria-disabled={disabled || undefined}
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 10px 8px 13px",
          border: "none",
          background: "transparent",
          color: active ? C.ink : C.secondary,
          fontWeight: active ? 600 : 500,
          fontSize: 13,
          fontFamily: "'DM Sans', sans-serif",
          cursor: disabled ? "not-allowed" : "pointer",
          textAlign: "left",
        }}
      >
        <span style={{ color: active ? C.gold : C.tertiary, flexShrink: 0, display: "flex" }}>
          {item.icon}
        </span>
        <span style={{ flex: 1, display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
          <span style={{ lineHeight: 1.2 }}>{item.label}</span>
          {disabled && disabledHint && (
            <span style={{
              fontSize: 10,
              fontWeight: 400,
              color: C.tertiary,
              fontFamily: "'DM Sans', sans-serif",
              lineHeight: 1.2,
              letterSpacing: "0.01em",
            }}>
              {disabledHint}
            </span>
          )}
        </span>
        {badgeCount > 0 && (
          <span
            aria-label={`${badgeCount} unread`}
            style={{
              minWidth: 16,
              height: 16,
              padding: "0 5px",
              borderRadius: 8,
              background: "#F5B731",
              color: "#0F1318",
              fontSize: 9,
              fontWeight: 800,
              fontFamily: "'JetBrains Mono', monospace",
              letterSpacing: "0.02em",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {badgeCount > 99 ? "99+" : badgeCount}
          </span>
        )}
      </button>
      {item.collapsible && (
        <button
          onClick={(e) => { e.stopPropagation(); onToggleExpand?.(); }}
          aria-label={expanded ? "Collapse" : "Expand"}
          style={{
            padding: "0 10px",
            border: "none",
            background: "transparent",
            color: C.tertiary,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
          }}
        >
          <span style={{
            transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            transition: "transform 0.15s",
            display: "flex",
          }}>{I.chevron}</span>
        </button>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
export default function Sidebar({ onGridTwin, onPipeline, onDcTwin, onBessFacility }) {
  const { setActiveWorkspace, setActiveViewMode, activeViewMode, activeWorkspace } = useWorkspace();

  // React Router hooks — available because the whole tree is wrapped in
  // <BrowserRouter /> in main.jsx.
  const navigate = useNavigate();
  const location = useLocation();

  // Unread-count badge for the Intelligence → Alerts row.
  const { unreadCount } = useAlerts();

  const [active, setActive] = useState("mission");
  const [projectsOpen, setProjectsOpen] = useState(false);
  const [intelligenceOpen, setIntelligenceOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Active project for Site Twin deep-link — prefer URL param, fall back to
  // whichever project the sidebar tree has selected locally.
  const [activeProjectId, setActiveProjectId] = useState(null);
  useEffect(() => {
    try {
      const url = new URL(window.location.href);
      setActiveProjectId(url.searchParams.get("project") || null);
    } catch { /* ignore */ }
    const onChange = () => {
      try {
        const url = new URL(window.location.href);
        setActiveProjectId(url.searchParams.get("project") || null);
      } catch { /* ignore */ }
    };
    window.addEventListener("popstate", onChange);
    return () => window.removeEventListener("popstate", onChange);
  }, [location.pathname, location.search]);

  // Keep the Intelligence group highlighted when on one of its routes.
  useEffect(() => {
    if (location.pathname.startsWith("/intelligence")) {
      setActive("intelligence");
      setIntelligenceOpen(true);
    }
  }, [location.pathname]);

  // Auto-close the Portfolio tree when the user navigates away from the
  // Projects view. The tree is a project-only concern; on Grid Graph / Grid
  // Twin / Map / Pulse it just competes with the Grid Assets rail.
  useEffect(() => {
    if (activeViewMode !== "projects" && projectsOpen) {
      setProjectsOpen(false);
    }
    // Skip the workspace-driven highlight while the user is on an
    // Intelligence route — the URL-driven effect below owns the state.
    if (location.pathname.startsWith("/intelligence")) return;
    // Keep the primary-nav highlight in sync with the current view
    if (activeViewMode === "projects") setActive("projects");
    else if (activeViewMode === "map") setActive("map");
    else if (activeViewMode === "grid_graph" || activeViewMode === "pulse") setActive("gridtwin");
    else if (activeViewMode === "dashboard" && activeWorkspace === "home") setActive("mission");
  }, [activeViewMode, activeWorkspace]); // eslint-disable-line react-hooks/exhaustive-deps

  // Project tree state — loaded only when Projects row is expanded
  const [tree, setTree] = useState([]);
  const [selPortfolio, setSelPortfolio] = useState(null);
  const [selProject, setSelProject] = useState(null);
  const [selSite, setSelSite] = useState(null);
  const [treeLoaded, setTreeLoaded] = useState(false);

  useEffect(() => {
    if (!projectsOpen || treeLoaded) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await getPortfolioTree();
        if (!cancelled) {
          setTree(data.portfolios || []);
          setTreeLoaded(true);
        }
      } catch (e) {
        if (!cancelled) {
          console.warn("[Sidebar] portfolio tree load failed:", e.message);
          setTreeLoaded(true); // stop retrying
        }
      }
    })();
    return () => { cancelled = true; };
  }, [projectsOpen, treeLoaded]);

  const goMission = useCallback(() => {
    setActiveWorkspace?.("home");
    setActiveViewMode?.("dashboard");
  }, [setActiveWorkspace, setActiveViewMode]);

  const goMap = useCallback(() => {
    setActiveWorkspace?.("home");
    setActiveViewMode?.("map");
  }, [setActiveWorkspace, setActiveViewMode]);

  const openChat = useCallback(() => {
    // ChatRail already listens for cmd-K (see ChatRail.jsx). Dispatching a
    // synthetic keydown is the least-invasive way to uncollapse and focus
    // the input without plumbing extra props through App.jsx.
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }));
  }, []);

  const onSelectProject = useCallback((projectId, portfolioId) => {
    setSelProject(projectId);
    setSelSite(null);
    if (portfolioId) setSelPortfolio(portfolioId);
    // Bridge into the redesign project page + mark URL so Mission Control
    // overlay unmounts and the project view mounts underneath.
    const url = new URL(window.location.href);
    url.searchParams.set("redesign", "1");
    if (projectId) url.searchParams.set("project", projectId);
    window.history.replaceState({}, "", url);
    setActiveViewMode?.("map");
    window.dispatchEvent(new CustomEvent("princeps-redesign-select-project", {
      detail: { projectId },
    }));
  }, [setActiveViewMode]);

  const onSelectSite = useCallback((siteId, projectId, portfolioId) => {
    setSelSite(siteId);
    if (projectId) setSelProject(projectId);
    if (portfolioId) setSelPortfolio(portfolioId);
  }, []);

  const handleNav = useCallback((id) => {
    setActive(id);
    switch (id) {
      case "mission":
        goMission();
        break;
      case "projects":
        // Clicking Projects toggles the tree + routes to Projects view
        setProjectsOpen((p) => !p);
        setActiveWorkspace?.("home");
        setActiveViewMode?.("projects");
        break;
      case "map":
        goMap();
        break;
      case "intelligence":
        // Toggle the child list, and route into Alerts by default.
        setIntelligenceOpen((p) => !p);
        if (!location.pathname.startsWith("/intelligence")) {
          navigate("/intelligence/alerts");
        }
        break;
      case "gridtwin":
        onGridTwin?.();
        break;
      case "sitetwin":
        // Route to the full-screen 3D Site Twin for the active project.
        // When no project is pinned, the nav row is disabled — this branch
        // shouldn't fire, but keep a safe no-op.
        if (activeProjectId) navigate(`/design/${encodeURIComponent(activeProjectId)}`);
        break;
      case "chat":
        openChat();
        break;
      case "settings":
        // Route to /settings (full-screen page) for reliability; the legacy
        // modal panel is kept as a fallback via setSettingsOpen below.
        navigate("/settings");
        setSettingsOpen(true);
        break;
      default:
        break;
    }
  }, [goMission, goMap, openChat, onGridTwin, setActiveWorkspace, setActiveViewMode, navigate, location.pathname]);

  return (
    <nav
      aria-label="Primary"
      style={{
        width: 240,
        height: "100vh",
        background: C.card,
        borderRight: `1px solid ${C.border}`,
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        overflow: "hidden",
        zIndex: 100,
      }}
    >
      {/* Brand */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
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
          fontSize: 16, fontWeight: 800, color: C.ink, letterSpacing: "-0.02em",
        }}>
          PRINCEPS
        </span>
      </div>

      {/* Primary nav — exactly 6 items */}
      <div style={{ padding: "8px 0 4px", flexShrink: 0 }}>
        {NAV_ITEMS.map((item) => {
          const disabled = item.id === "sitetwin" && !activeProjectId;
          return (
          <React.Fragment key={item.id}>
            <NavRow
              item={item}
              active={active === item.id || (item.id === "sitetwin" && location.pathname.startsWith("/design"))}
              expanded={
                item.id === "projects" ? projectsOpen :
                item.id === "intelligence" ? intelligenceOpen : false
              }
              onClick={() => handleNav(item.id)}
              onToggleExpand={
                item.id === "projects"
                  ? () => setProjectsOpen((p) => !p)
                  : item.id === "intelligence"
                    ? () => setIntelligenceOpen((p) => !p)
                    : undefined
              }
              badgeCount={item.id === "intelligence" ? unreadCount : 0}
              disabled={disabled}
              disabledTooltip={disabled
                ? "Open a project first — Site Designer 3D renders a 3D design canvas for the selected project's site."
                : undefined}
              disabledHint={disabled ? item.disabledHint : undefined}
              onDisabledClick={disabled && item.id === "sitetwin"
                ? () => {
                    // Soft-nudge: auto-expand Projects so the user sees where
                    // to click to pin a project, and route into Projects view.
                    setProjectsOpen(true);
                    setActive("projects");
                    setActiveWorkspace?.("home");
                    setActiveViewMode?.("projects");
                  }
                : undefined}
            />
            {item.id === "intelligence" && intelligenceOpen && (
              <div
                style={{
                  borderTop: `1px solid ${C.border}`,
                  borderBottom: `1px solid ${C.border}`,
                  background: C.bg,
                  padding: "4px 0",
                }}
              >
                {INTEL_CHILDREN.map((child) => {
                  const childActive = location.pathname.startsWith(child.to);
                  const showBadge = child.id === "alerts" && unreadCount > 0;
                  return (
                    <button
                      key={child.id}
                      onClick={() => {
                        setActive("intelligence");
                        navigate(child.to);
                      }}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        width: "100%",
                        padding: "6px 12px 6px 32px",
                        border: "none",
                        background: childActive ? "rgba(201,166,75,0.08)" : "transparent",
                        color: childActive ? C.ink : C.secondary,
                        fontFamily: "'DM Sans', sans-serif",
                        fontSize: 12,
                        fontWeight: childActive ? 700 : 500,
                        cursor: "pointer",
                        textAlign: "left",
                      }}
                    >
                      <span style={{
                        color: childActive ? C.gold : C.tertiary,
                        display: "flex", flexShrink: 0,
                      }}>
                        {child.icon}
                      </span>
                      <span style={{ flex: 1 }}>{child.label}</span>
                      {showBadge && (
                        <span style={{
                          minWidth: 16, height: 16, padding: "0 5px",
                          borderRadius: 8,
                          background: "#F5B731",
                          color: "#0F1318",
                          fontSize: 9, fontWeight: 800,
                          fontFamily: "'JetBrains Mono', monospace",
                          display: "inline-flex", alignItems: "center", justifyContent: "center",
                        }}>
                          {unreadCount > 99 ? "99+" : unreadCount}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
            {/* COUNCIL-5 / BOT-RR: hide the Sidebar-embedded project tree
                when the user is already on the Projects view (RedesignLayout
                ships its own tree there). Avoids the duplicate-tree mess in
                the dashboard_redesign_spec. */}
            {item.id === "projects" && projectsOpen && activeViewMode !== "projects" && (
              <div
                style={{
                  borderTop: `1px solid ${C.border}`,
                  borderBottom: `1px solid ${C.border}`,
                  background: C.bg,
                  maxHeight: "55vh",
                  overflow: "hidden",
                  display: "flex",
                }}
                // Override ProjectTree's hard-coded 280px root width so the
                // embedded variant fits inside the 240px sidebar column.
                className="sidebar-project-tree-host"
              >
                <style>{`
                  .sidebar-project-tree-host .pt-root,
                  .sidebar-project-tree-host .pt-scroll,
                  .sidebar-project-tree-host .pt-row { min-width: 0; }
                  .sidebar-project-tree-host .pt-root { width: 100%; }
                  .sidebar-project-tree-host .pt-pf-name,
                  .sidebar-project-tree-host .pt-name {
                    min-width: 0; white-space: nowrap;
                    overflow: hidden; text-overflow: ellipsis;
                  }
                `}</style>
                <div style={{ flex: 1, display: "flex", minHeight: 0, minWidth: 0 }}>
                  <ProjectTree
                    portfolios={tree}
                    selectedPortfolioId={selPortfolio}
                    selectedProjectId={selProject}
                    selectedSiteId={selSite}
                    onSelectPortfolio={setSelPortfolio}
                    onSelectProject={onSelectProject}
                    onSelectSite={onSelectSite}
                    onNewProject={() => {
                      const url = new URL(window.location.href);
                      url.searchParams.set("redesign", "1");
                      window.history.replaceState({}, "", url);
                      setActiveViewMode?.("map");
                      window.dispatchEvent(new CustomEvent("princeps-redesign-new-project"));
                    }}
                  />
                </div>
              </div>
            )}
          </React.Fragment>
          );
        })}
      </div>

      <div style={{ flex: 1 }} />

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
          width: 28, height: 28, borderRadius: "50%",
          background: C.goldSurface,
          border: `1.5px solid ${C.goldBorder}`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 10, fontWeight: 700, color: C.goldStrong,
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
        activeTab="team"
        onTabChange={() => { /* single-panel mode */ }}
        onClose={() => setSettingsOpen(false)}
      />
    </nav>
  );
}

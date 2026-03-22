import React, { useState, useCallback, useRef, useEffect } from "react";
import { useSite } from "../../SiteContext";
import { useWorkspace, WORKSPACES } from "../../contexts/WorkspaceContext";
import api from "../../services/api";
import LiveStatusStrip from "../LiveStatusStrip";
import ErrorBoundary from "../ErrorBoundary";
import ThemeToggle from "../ThemeToggle";
import NotificationCentre from "../NotificationCentre";

const STEPS = [
  { id: "site",    label: "Discover", sub: "Find & select",     num: "1" },
  { id: "study",   label: "Assess",   sub: "Feasibility",       num: "2", gate: "pickedLocation" },
  { id: "plan",    label: "Design",   sub: "Layout & build",    num: "3", gate: "pickedLocation" },
];

function WorkflowSteps() {
  const { workflowStage, navigateWorkflow, pickedLocation, agentResult, workflowHistory } = useSite();
  const stageIdx = STEPS.findIndex(s => s.id === workflowStage);

  const canNavigate = (step) => {
    if (step.id === "site") return true;
    if (step.id === "study") return !!pickedLocation;
    if (step.id === "connect") return !!pickedLocation;
    if (step.id === "plan") return !!agentResult;
    if (step.id === "impact") return !!agentResult;
    if (step.id === "act") return !!agentResult;
    return false;
  };

  return (
    <div className="workflow-steps">
      {STEPS.map((step, i) => {
        const done = workflowHistory.includes(step.id) && i < stageIdx;
        const active = i === stageIdx;
        const reachable = canNavigate(step);
        const locked = !reachable && !done && !active;
        return (
          <React.Fragment key={step.id}>
            {i > 0 && (
              <div className={`workflow-step-line${done ? " done" : active ? " active" : ""}`}>
                <div className="workflow-step-line-fill" />
              </div>
            )}
            <button
              className={`workflow-step${active ? " active" : ""}${done ? " done" : ""}${locked ? " locked" : ""}`}
              onClick={() => reachable && navigateWorkflow(step.id)}
              disabled={locked}
              title={locked ? `Complete ${STEPS[i - 1]?.label || "previous step"} first` : step.sub}
            >
              <div className="workflow-step-dot">
                {done ? (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12" /></svg>
                ) : locked ? (
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" /></svg>
                ) : (
                  <span className="workflow-step-num">{step.num}</span>
                )}
              </div>
              <div className="workflow-step-text">
                <span className="workflow-step-label">{step.label}</span>
                <span className="workflow-step-sub">{step.sub}</span>
              </div>
            </button>
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* ── Site Context Breadcrumb ── */
function SiteBreadcrumb() {
  const { explain, pickedLocation, samCapacity, agentResult, workflowSummary } = useSite();

  const siteName = explain?.location_name || explain?.name || null;
  const lat = explain?.lat ?? pickedLocation?.lat;
  const lon = explain?.lon ?? pickedLocation?.lon;
  const verdict = workflowSummary?.overall_verdict || agentResult?.verdict;

  if (!lat && !siteName) {
    return (
      <div className="tsb-breadcrumb-site tsb-breadcrumb-empty">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
        </svg>
        <span>No site selected</span>
      </div>
    );
  }

  return (
    <div className="tsb-breadcrumb-site">
      {siteName && <span className="tsb-bc-name">{siteName}</span>}
      {lat && lon && (
        <>
          {siteName && <span className="tsb-bc-sep">&middot;</span>}
          <span className="tsb-bc-coords">{lat.toFixed(4)}, {lon.toFixed(4)}</span>
        </>
      )}
      {samCapacity > 0 && (
        <>
          <span className="tsb-bc-sep">&middot;</span>
          <span className="tsb-bc-capacity">{samCapacity} kW</span>
        </>
      )}
      {verdict && (
        <>
          <span className="tsb-bc-sep">&middot;</span>
          <span className={`tsb-bc-verdict tsb-bc-verdict-${verdict.toLowerCase().replace("-", "")}`}>
            {verdict}
          </span>
        </>
      )}
    </div>
  );
}

/* ── Hero Search Bar ── */
function HeroSearch({ onCommandPalette }) {
  const [focused, setFocused] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef(null);
  const dropdownRef = useRef(null);
  const { setPickedLocation, loadSite, setParcelId, samCapacity, samDay } = useSite();

  // Close dropdown on outside click
  useEffect(() => {
    if (!focused) return;
    const handler = (e) => {
      if (
        inputRef.current && !inputRef.current.contains(e.target) &&
        dropdownRef.current && !dropdownRef.current.contains(e.target)
      ) {
        setFocused(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [focused]);

  const SUGGESTED = [
    "Solar feasibility near Birmingham",
    "Grid capacity in South Wales",
    "52.4862, -1.8904",
    "B15 2TT",
  ];

  const loadRecentSearches = () => {
    try {
      const raw = localStorage.getItem("princeps_recent_searches");
      return raw ? JSON.parse(raw).slice(0, 4) : [];
    } catch { return []; }
  };

  const saveSearch = (q) => {
    try {
      const existing = loadRecentSearches().filter(s => s !== q);
      localStorage.setItem("princeps_recent_searches", JSON.stringify([q, ...existing].slice(0, 8)));
    } catch { /* ignore */ }
  };

  const isCoordinate = (text) => {
    const match = text.match(/^(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)$/);
    if (match) {
      const lat = parseFloat(match[1]);
      const lon = parseFloat(match[2]);
      if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
        return { lat, lon };
      }
    }
    return null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;

    saveSearch(q);
    setFocused(false);

    const coords = isCoordinate(q);
    if (coords) {
      setPickedLocation(coords);
      // Attempt to load site at these coordinates
      try {
        const data = await api.site.fromLocation(coords.lat, coords.lon);
        if (data?.parcel_id) {
          setParcelId(data.parcel_id);
          loadSite(data.parcel_id, samCapacity, samDay);
        }
      } catch { /* ignore */ }
      setQuery("");
      return;
    }

    // Text or postcode query — delegate to command palette / copilot
    onCommandPalette?.(q);
    setQuery("");
  };

  const handleSuggestionClick = (text) => {
    setQuery(text);
    setFocused(false);
    inputRef.current?.focus();
  };

  const recentSearches = loadRecentSearches();

  return (
    <div className="tsb-hero-search-wrap">
      <form className={`tsb-hero-search${focused ? " tsb-hero-search-focused" : ""}`} onSubmit={handleSubmit}>
        <svg className="tsb-hero-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          className="tsb-hero-search-input"
          placeholder="Search by postcode, coordinates, or describe what you need..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
        />
        <kbd className="tsb-hero-search-kbd">&#8984;K</kbd>
      </form>

      {focused && (
        <div className="tsb-hero-dropdown" ref={dropdownRef}>
          {recentSearches.length > 0 && (
            <div className="tsb-hero-dropdown-section">
              <div className="tsb-hero-dropdown-label">Recent</div>
              {recentSearches.map((s, i) => (
                <button key={i} className="tsb-hero-dropdown-item" onClick={() => handleSuggestionClick(s)}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                  {s}
                </button>
              ))}
            </div>
          )}
          <div className="tsb-hero-dropdown-section">
            <div className="tsb-hero-dropdown-label">Suggestions</div>
            {SUGGESTED.map((s, i) => (
              <button key={i} className="tsb-hero-dropdown-item" onClick={() => handleSuggestionClick(s)}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" /></svg>
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MoreMenu({ items }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <button className="btn-topbar-action" onClick={() => setOpen(!open)} title="More tools">
        ···
      </button>
      {open && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 1199 }} onClick={() => setOpen(false)} />
          <div style={{
            position: "absolute", top: "100%", right: 0, marginTop: 4,
            background: "#ffffff", border: "1px solid rgba(0,0,0,0.1)",
            borderRadius: 8, padding: "4px 0", zIndex: 1200, minWidth: 160,
            boxShadow: "0 4px 16px rgba(0,0,0,0.08)",
          }}>
            {items.map((it, i) => (
              <button key={i} onClick={() => { setOpen(false); it.action?.(); }} style={{
                display: "block", width: "100%", padding: "7px 14px", border: "none",
                background: "transparent", color: "#374151", fontSize: 12,
                textAlign: "left", cursor: "pointer",
              }}
                onMouseEnter={e => e.target.style.background = "rgba(212,160,24,0.06)"}
                onMouseLeave={e => e.target.style.background = "transparent"}
              >{it.label}</button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function TopStatusBar({ onGridTwin, onBems, onAssetInspect, onGridGraph, onBessFacility, onHardware, onThermal, onPitch, onNomExplorer, onSettings, onCommandPalette, onDcTwin, onPipeline, onIntelligence }) {
  const {
    solarYield, gridContext, explain,
    agentResult, workflowSummary,
    samCapacity, setSamCapacity,
    pickedLocation, parcelId,
  } = useSite();
  const { activeWorkspace } = useWorkspace();

  // PDF download
  const [pdfLoading, setPdfLoading] = useState(false);
  const downloadPdf = useCallback(async () => {
    if (pdfLoading) return;
    setPdfLoading(true);
    try {
      const lat = explain?.lat ?? explain?.location?.lat ?? pickedLocation?.lat;
      const lon = explain?.lon ?? explain?.location?.lon ?? pickedLocation?.lon;
      if (!lat || !lon) { alert("Select a site first"); setPdfLoading(false); return; }
      const name = explain?.name || parcelId || "Site";
      const blob = await api.reports.siteAssessment(lat, lon, name, samCapacity / 1000 || 50);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `princeps-report-${name.replace(/[^\w-]/g, "-")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("PDF download failed:", e);
      alert("Report generation failed — see console.");
    } finally {
      setPdfLoading(false);
    }
  }, [explain, pickedLocation, parcelId, samCapacity, pdfLoading]);

  return (
    <header className="top-status-bar">
      <div className="tsb-left">
        <WorkflowSteps />
      </div>

      <div className="tsb-center">
        <SiteBreadcrumb />
        <HeroSearch onCommandPalette={onCommandPalette} />
      </div>

      <div className="tsb-right">
        <button className="btn-topbar-intel" onClick={onIntelligence} title="Regulatory Intelligence Feed">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
          </svg>
          Intel
        </button>
        <button className="btn-topbar-icon" onClick={onCommandPalette} title="Commands (Cmd+K)">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M18 3a3 3 0 00-3 3v12a3 3 0 003 3 3 3 0 003-3 3 3 0 00-3-3H6a3 3 0 00-3 3 3 3 0 003 3 3 3 0 003-3V6a3 3 0 00-3-3 3 3 0 00-3 3 3 3 0 003 3h12a3 3 0 003-3 3 3 0 00-3-3z" />
          </svg>
        </button>
        <button className="btn-topbar-icon" onClick={onSettings} title="Settings">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>
        <ErrorBoundary name="LiveStatusStrip" fallback={null}>
          <LiveStatusStrip />
        </ErrorBoundary>
      </div>
    </header>
  );
}

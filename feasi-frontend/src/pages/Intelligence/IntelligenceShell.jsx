import React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

// Gold/ink tokens — mirrors the Sidebar light-gold palette to stay
// visually continuous with the rest of the Princeps chrome.
const C = {
  gold: "#F5B731",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  goldBorder: "rgba(245,183,49,0.32)",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#F7F8FA",
  ivory: "#FBF8F2",
};

const TABS = [
  { id: "alerts",       label: "Alerts",       to: "/intelligence/alerts" },
  { id: "dockets",      label: "Dockets",      to: "/intelligence/dockets" },
  { id: "engagements",  label: "Engagements",  to: "/intelligence/engagements" },
  { id: "datasets",     label: "Datasets",     to: "/intelligence/datasets" },
];

function SegmentedControl() {
  const loc = useLocation();
  return (
    <div
      role="tablist"
      aria-label="Intelligence sections"
      style={{
        display: "inline-flex",
        padding: 4,
        borderRadius: 10,
        background: C.bg,
        border: `1px solid ${C.border}`,
        gap: 2,
      }}
    >
      {TABS.map((t) => {
        const active = loc.pathname.startsWith(t.to);
        return (
          <NavLink
            key={t.id}
            to={t.to}
            role="tab"
            aria-selected={active}
            style={{
              textDecoration: "none",
              padding: "6px 14px",
              borderRadius: 8,
              fontSize: 13,
              fontWeight: active ? 700 : 600,
              fontFamily: "'DM Sans', sans-serif",
              letterSpacing: "-0.01em",
              color: active ? C.ink : C.secondary,
              background: active ? "#FFFFFF" : "transparent",
              border: active ? `1px solid ${C.goldBorder}` : "1px solid transparent",
              boxShadow: active ? "0 1px 2px rgba(15,19,24,0.05)" : "none",
              transition: "all 120ms ease",
            }}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              {active && (
                <span
                  aria-hidden
                  style={{
                    width: 6, height: 6, borderRadius: 3,
                    background: C.gold,
                    display: "inline-block",
                  }}
                />
              )}
              {t.label}
            </span>
          </NavLink>
        );
      })}
    </div>
  );
}

/**
 * IntelligenceShell — parent layout for Alerts / Dockets / Datasets.
 * Sub-tabs live in a gold segmented control at the top; nested
 * routes are rendered via <Outlet />.
 */
export default function IntelligenceShell() {
  const navigate = useNavigate();
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        minHeight: 0,
        background: C.ivory,
        fontFamily: "'DM Sans', sans-serif",
        color: C.ink,
      }}
    >
      {/* Top bar — title + segmented control */}
      <header
        style={{
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "16px 24px 12px",
          borderBottom: `1px solid ${C.border}`,
          background: "#FFFFFF",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <button
            onClick={() => navigate("/")}
            title="Back to Princeps"
            aria-label="Back to Princeps"
            style={{
              background: "transparent",
              border: `1px solid ${C.border}`,
              borderRadius: 6,
              padding: "4px 10px",
              fontSize: 12,
              fontWeight: 600,
              color: C.secondary,
              cursor: "pointer",
              fontFamily: "'DM Sans', sans-serif",
              marginRight: 4,
              alignSelf: "center",
              transition: "all 120ms ease",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = C.goldBorder;
              e.currentTarget.style.color = C.ink;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = C.border;
              e.currentTarget.style.color = C.secondary;
            }}
          >
            ← Princeps
          </button>
          <h1
            style={{
              margin: 0,
              fontSize: 20,
              fontWeight: 800,
              letterSpacing: "-0.02em",
            }}
          >
            Intelligence
          </h1>
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10,
              color: C.tertiary,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
            }}
          >
            regulatory · market · grid
          </span>
        </div>
        <SegmentedControl />
      </header>

      {/* Body */}
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        <Outlet />
      </div>
    </div>
  );
}

// Simple placeholder sub-pages for Dockets / Datasets. These are
// intentionally light — the Alerts tab is the deliverable.
export function DocketsPlaceholder() {
  return (
    <div style={{ flex: 1, padding: 40, color: "#4B5563" }}>
      <h2 style={{ fontSize: 16, margin: "0 0 8px", color: "#0F1318" }}>Dockets</h2>
      <p style={{ fontSize: 13, lineHeight: 1.55, maxWidth: 520 }}>
        PINS NSIP docket viewer, Ofgem consultation dockets, DCO examination libraries.
        Coming in the next cut — the data contract piggybacks on the Alerts doc index.
      </p>
    </div>
  );
}

export function DatasetsPlaceholder() {
  return (
    <div style={{ flex: 1, padding: 40, color: "#4B5563" }}>
      <h2 style={{ fontSize: 16, margin: "0 0 8px", color: "#0F1318" }}>Datasets</h2>
      <p style={{ fontSize: 13, lineHeight: 1.55, maxWidth: 520 }}>
        NESO TEC register, DNO ECRs, REPD, PINS register — browsable as tables with
        delta history. Wiring in after the initial Alerts tab ships.
      </p>
    </div>
  );
}

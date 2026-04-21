import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { SiteProvider } from "./SiteContext";
import { WorkspaceProvider } from "./contexts/WorkspaceContext";
import App from "./App";
import Toast from "./components/Toast";
import "normalize.css";
import "@blueprintjs/core/lib/css/blueprint.css";
import "@blueprintjs/icons/lib/css/blueprint-icons.css";
import "@blueprintjs/select/lib/css/blueprint-select.css";
import "@blueprintjs/table/lib/css/table.css";
import "./styles.css";

// Unified Canvas (L1) — additive, additive. Lives under /canvas/:projectId.
const CanvasShell = lazy(() => import("./canvas/ShellLayout.jsx"));

// 3D Site Twin — full-screen route at /design/:projectId. Wraps TwinLazy.
const DesignPage = lazy(() => import("./pages/Design/DesignPage.jsx"));

// Customer-visible pages (BOT-K).
const BuildableAreaPlayground = lazy(() => import("./components/BuildableAreaPlayground.jsx"));
const ConnectorHealthDashboard = lazy(() => import("./components/ConnectorHealthDashboard.jsx"));

// Public marketing — Substation Tracker landing at /tracker.
const TrackerLanding = lazy(() => import("./pages/Marketing/TrackerLanding.jsx"));

// Intelligence (Alerts / Dockets / Datasets). Nested under /intelligence.
const IntelligenceShell = lazy(() => import("./pages/Intelligence/IntelligenceShell.jsx"));
const AlertsIndex = lazy(() => import("./pages/Intelligence/Alerts/AlertsIndex.jsx"));
const DocketsIndex = lazy(() => import("./pages/Intelligence/Dockets/DocketsIndex.jsx"));

// Tracker admin (SME review + publish) at /tracker-admin.
const TrackerDashboard = lazy(() => import("./pages/Tracker/TrackerDashboard.jsx"));
const DatasetsIndex = lazy(() => import("./pages/Intelligence/Datasets/DatasetsIndex.jsx"));
const EngagementsIndex = lazy(() => import("./pages/Intelligence/Engagements/EngagementsIndex.jsx"));

// Global parcel drawer — listens on window event from any map.
const ParcelDrawer = lazy(() => import("./components/parcel/ParcelDrawer.jsx"));

// Tiny placeholder for the Dockets/Datasets sub-tabs — the Alerts tab is
// the deliverable; these slots exist so the segmented control routes without
// 404s. Keep inline to avoid a separate file.
function IntelligencePlaceholder({ kind }) {
  const label = kind === "dockets" ? "Dockets" : "Datasets";
  const blurb = kind === "dockets"
    ? "PINS NSIP docket viewer, Ofgem consultation dockets, DCO examination libraries. Coming in the next cut — the data contract piggybacks on the Alerts doc index."
    : "NESO TEC register, DNO ECRs, REPD, PINS register — browsable as tables with delta history. Wiring in after the initial Alerts tab ships.";
  return (
    <div style={{ flex: 1, padding: 40, color: "#4B5563", fontFamily: "'DM Sans', sans-serif" }}>
      <h2 style={{ fontSize: 16, margin: "0 0 8px", color: "#0F1318" }}>{label}</h2>
      <p style={{ fontSize: 13, lineHeight: 1.55, maxWidth: 520 }}>{blurb}</p>
    </div>
  );
}

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error("Princeps error:", error, info); }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          height: "100vh", fontFamily: "'Inter', 'DM Sans', -apple-system, sans-serif",
          background: "#F9FAFB", color: "#111827",
        }}>
          <img src="/logo-princeps.png" alt="Princeps" width="48" height="48" style={{ marginBottom: 24, objectFit: "contain" }} />
          <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 8px" }}>Something went wrong</h2>
          <p style={{ fontSize: 14, color: "#6B7280", margin: "0 0 24px", maxWidth: 400, textAlign: "center" }}>
            An unexpected error occurred. This has been logged. Please try refreshing the page.
          </p>
          <div style={{ display: "flex", gap: 12 }}>
            <button
              onClick={() => this.setState({ error: null })}
              style={{
                padding: "10px 24px", borderRadius: 8, border: "1px solid #E5E7EB",
                background: "white", color: "#374151", fontSize: 14, fontWeight: 500,
                cursor: "pointer", fontFamily: "inherit",
              }}
            >Retry</button>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: "10px 24px", borderRadius: 8, border: "none",
                background: "#D4A018", color: "white", fontSize: 14, fontWeight: 600,
                cursor: "pointer", fontFamily: "inherit",
              }}
            >Reload Page</button>
          </div>
          {process.env.NODE_ENV === "development" && (
            <details style={{ marginTop: 24, maxWidth: 600, width: "100%" }}>
              <summary style={{ cursor: "pointer", fontSize: 11, color: "#9CA3AF" }}>Developer details</summary>
              <pre style={{ fontSize: 10, color: "#9CA3AF", whiteSpace: "pre-wrap", marginTop: 8, padding: 12, background: "#F3F4F6", borderRadius: 6, overflow: "auto", maxHeight: 200 }}>
                {this.state.error.message}
              </pre>
            </details>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}

const LegacyApp = () => (
  <SiteProvider>
    <WorkspaceProvider>
      <App />
    </WorkspaceProvider>
  </SiteProvider>
);

createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <BrowserRouter>
      <Suspense fallback={null}>
        <ParcelDrawer />
      </Suspense>
      <Routes>
        <Route
          path="/canvas/:projectId"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading canvas…</div>}>
              <CanvasShell />
            </Suspense>
          }
        />
        <Route
          path="/canvas"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading canvas…</div>}>
              <CanvasShell />
            </Suspense>
          }
        />
        <Route
          path="/design/:projectId"
          element={
            <SiteProvider>
              <WorkspaceProvider>
                <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading 3D site twin…</div>}>
                  <DesignPage />
                </Suspense>
              </WorkspaceProvider>
            </SiteProvider>
          }
        />
        <Route
          path="/design"
          element={
            <SiteProvider>
              <WorkspaceProvider>
                <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading 3D site twin…</div>}>
                  <DesignPage />
                </Suspense>
              </WorkspaceProvider>
            </SiteProvider>
          }
        />
        <Route
          path="/buildable-area/:projectId"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading buildable area…</div>}>
              <BuildableAreaPlayground />
            </Suspense>
          }
        />
        <Route
          path="/buildable-area"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading buildable area…</div>}>
              <BuildableAreaPlayground />
            </Suspense>
          }
        />
        <Route
          path="/connectors"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading connectors…</div>}>
              <ConnectorHealthDashboard />
            </Suspense>
          }
        />
        <Route
          path="/tracker"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading…</div>}>
              <TrackerLanding />
            </Suspense>
          }
        />
        <Route
          path="/tracker-admin"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading tracker…</div>}>
              <TrackerDashboard />
            </Suspense>
          }
        />
        <Route
          path="/tracker-admin/review/:id"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading tracker…</div>}>
              <TrackerDashboard />
            </Suspense>
          }
        />
        {/* Intelligence — nested routes under IntelligenceShell's <Outlet />. */}
        <Route
          path="/intelligence"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading intelligence…</div>}>
              <IntelligenceShell />
            </Suspense>
          }
        >
          <Route
            index
            element={
              <Suspense fallback={null}>
                <AlertsIndex />
              </Suspense>
            }
          />
          <Route
            path="alerts"
            element={
              <Suspense fallback={null}>
                <AlertsIndex />
              </Suspense>
            }
          />
          <Route
            path="alerts/:alertId"
            element={
              <Suspense fallback={null}>
                <AlertsIndex />
              </Suspense>
            }
          />
          <Route
            path="dockets"
            element={
              <Suspense fallback={null}>
                <DocketsIndex />
              </Suspense>
            }
          />
          <Route
            path="dockets/:docketId"
            element={
              <Suspense fallback={null}>
                <DocketsIndex />
              </Suspense>
            }
          />
          <Route
            path="datasets"
            element={
              <Suspense fallback={null}>
                <DatasetsIndex />
              </Suspense>
            }
          />
          <Route
            path="engagements"
            element={
              <Suspense fallback={null}>
                <EngagementsIndex />
              </Suspense>
            }
          />
        </Route>
        <Route path="*" element={<LegacyApp />} />
      </Routes>
      {/* Global toast render layer — driven by src/lib/toast.js. Mounted at
          the router root so it covers every route (legacy App, Intelligence,
          Canvas, Design, …). */}
      <Toast />
    </BrowserRouter>
  </ErrorBoundary>
);

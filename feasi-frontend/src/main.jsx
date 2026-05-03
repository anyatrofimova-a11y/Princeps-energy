import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Princeps query client — sane defaults for the analysis cache (Stage B
// of the SiteContext dissolution). Per-query options can override these.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: 1,
    },
  },
});
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

// Workshop — Kognitwin-pattern operations cockpit demo (Swarm 10).
const WorkshopDemo = lazy(() => import("./workshop/WorkshopDemo.jsx"));

// Kongsberg-grade twin views — BESS + DC.
const BESSTwinView = lazy(() => import("./twin-explorer/BESSTwinView.jsx"));
const DCTwinView = lazy(() => import("./twin-explorer/DCTwinView.jsx"));

// WorkshopShell — DEPRECATED. Replaced by AppShell (Princeps v2). Kept
// only as a no-op layout route so existing nested children render bare.
import { WorkshopShell } from "./workshop/WorkshopShell.jsx";

// Princeps v2 shell — Foundry/Kognitwin three-column layout.
const AppShell = lazy(() => import("./shell/AppShell.jsx"));
const ObjectPage = lazy(() => import("./shell/ObjectPage.jsx"));
const MissionControlPage = lazy(() => import("./components/MissionControl.jsx"));
// Mission Control v2 — composed Workshop module backed by ontology objects.
const MissionControlV2 = lazy(() => import("./mission_control/MissionControlV2.jsx"));

// Workshop Module Builder MVP — AI-composed manifest runtime.
const ModuleRuntime = lazy(() => import("./runtime/ModuleRuntime.jsx"));
const ComposeDemo = lazy(() => import("./runtime/ComposeDemo.jsx"));
// Magritte dataset catalogue — typed connector registry surface.
const DatasetsCatalog = lazy(() => import("./pages/Datasets/DatasetsCatalog.jsx"));
// Council demo — GRID + BESS + DC pods + Adjudicator (SSE timeline).
const CouncilDemo = lazy(() => import("./pages/Council/CouncilDemo.jsx"));
// Object Page — typed object detail / list at /v2/object/:type[/:id].
const ObjectDetailPage = lazy(() => import("./object_page/ObjectPage.jsx"));
// Lineage Panel — global slide-over; opens via window.dispatchEvent('princeps:lineage', {root}).
const LineagePanel = lazy(() => import("./lineage/LineagePanel.jsx"));
// Quiver — cross-filter charts over typed object sets.
const QuiverPage = lazy(() => import("./quiver/QuiverPage.jsx"));
// Solutions Marketplace — installable Slate dashboards.
const SolutionsMarketplace = lazy(() => import("./solutions/SolutionsMarketplace.jsx"));
// Object Sets — saved typed queries with set algebra.
const SetsBrowser = lazy(() => import("./object_sets/SetsBrowser.jsx"));
// Pipeline Builder — DAG editor + run + history.
const PipelinesPage = lazy(() => import("./pipelines/PipelinesPage.jsx"));
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
    <QueryClientProvider client={queryClient}>
    <BrowserRouter>
      <Suspense fallback={null}>
        <ParcelDrawer />
      </Suspense>
      <Suspense fallback={null}>
        <LineagePanel />
      </Suspense>
      <Routes>
        {/* Marketing / public routes — bare, no Workshop chrome. */}
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

        {/* v2 shell — clean Foundry/Kognitwin three-column app */}
        <Route
          element={
            <Suspense fallback={<div style={{padding: 40, fontFamily: "DM Sans"}}>Loading Princeps v2…</div>}>
              <AppShell />
            </Suspense>
          }
        >
          <Route
            path="/v2/object/:type/:rid"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading object…</div>}>
                <ObjectPage />
              </Suspense>
            }
          />
          <Route
            path="/v2"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading mission control…</div>}>
                <MissionControlV2 />
              </Suspense>
            }
          />
          <Route
            path="/v2/legacy"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading legacy dashboard…</div>}>
                <MissionControlPage />
              </Suspense>
            }
          />
          <Route
            path="/v2/modules/:id"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading module…</div>}>
                <ModuleRuntime />
              </Suspense>
            }
          />
          <Route
            path="/v2/builder"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading composer…</div>}>
                <ComposeDemo />
              </Suspense>
            }
          />
          <Route
            path="/v2/datasets"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading datasets…</div>}>
                <DatasetsCatalog />
              </Suspense>
            }
          />
          <Route
            path="/v2/council"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading council…</div>}>
                <CouncilDemo />
              </Suspense>
            }
          />
          <Route
            path="/v2/object/:type"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading object list…</div>}>
                <ObjectDetailPage />
              </Suspense>
            }
          />
          <Route
            path="/v2/object/:type/:id"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading object…</div>}>
                <ObjectDetailPage />
              </Suspense>
            }
          />
          <Route
            path="/v2/quiver/:type"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading quiver…</div>}>
                <QuiverPage />
              </Suspense>
            }
          />
          <Route
            path="/v2/quiver"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading quiver…</div>}>
                <QuiverPage />
              </Suspense>
            }
          />
          <Route
            path="/v2/solutions"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading marketplace…</div>}>
                <SolutionsMarketplace />
              </Suspense>
            }
          />
          <Route
            path="/v2/sets"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading object sets…</div>}>
                <SetsBrowser />
              </Suspense>
            }
          />
          <Route
            path="/v2/pipelines"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading pipelines…</div>}>
                <PipelinesPage />
              </Suspense>
            }
          />
          <Route
            path="/v2/pipelines/:slug"
            element={
              <Suspense fallback={<div style={{padding: 40}}>loading pipeline…</div>}>
                <PipelinesPage />
              </Suspense>
            }
          />
        </Route>

        {/* Legacy routes — bare. WorkshopShell drawers retired so they don't leak overlays. */}
        <Route>
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
        <Route
          path="/workshop"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading workshop…</div>}>
              <WorkshopDemo />
            </Suspense>
          }
        />
        <Route
          path="/twin/bess/:rid"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading BESS twin…</div>}>
              <BESSTwinView />
            </Suspense>
          }
        />
        <Route
          path="/twin/dc/:rid"
          element={
            <Suspense fallback={<div style={{ padding: 40, fontFamily: "DM Sans" }}>Loading DC twin…</div>}>
              <DCTwinView />
            </Suspense>
          }
        />
        <Route path="*" element={<LegacyApp />} />
        </Route>
        {/* End Workshop-shelled routes. */}
      </Routes>
      {/* Global toast render layer — driven by src/lib/toast.js. Mounted at
          the router root so it covers every route (legacy App, Intelligence,
          Canvas, Design, …). */}
      <Toast />
    </BrowserRouter>
    </QueryClientProvider>
  </ErrorBoundary>
);

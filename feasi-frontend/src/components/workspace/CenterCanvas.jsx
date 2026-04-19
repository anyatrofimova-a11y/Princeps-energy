import React, { lazy, Suspense } from "react";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import ViewTabs from "./ViewTabs";
import WorkspaceHome from "./WorkspaceHome";
import DataTableView from "../views/DataTableView";
import ChartView from "../views/ChartView";
import CurtailmentBrowser from "../curtailment/CurtailmentBrowser";
const RedesignLayout = lazy(() => import("../shell/RedesignLayout"));
const MissionControl = lazy(() => import("../MissionControl"));
const PulseWorkspace = lazy(() => import("../pulse/PulseWorkspace"));
const DCHyperscalerPanel = lazy(() => import("../dc/DCHyperscalerPanel"));
const NESO098Workspace = lazy(() => import("../neso098/NESO098Workspace"));
const GridGraphContainer = lazy(() => import("../grid-graph/GridGraphContainer"));
const DCPhysicalTwin = lazy(() => import("../DCPhysicalTwin"));

const GridNetworkView = lazy(() => import("../grid/GridNetworkView"));
const GridCircuitView = lazy(() => import("../grid/GridCircuitView"));
const GridTablePlusView = lazy(() => import("../grid/GridTablePlusView"));
const GSPExplorerView = lazy(() => import("../grid/GSPExplorerView"));
const GridCompareView = lazy(() => import("../grid/GridCompareView"));

const ViewLoading = () => (
  <div className="view-placeholder">Loading...</div>
);

export default function CenterCanvas({ children, dashboardView }) {
  const { activeViewMode } = useWorkspace();

  // Map stays mounted across view switches — unmounting Mapbox on every toggle
  // destroys zoom/pan state and is slow. We hide the map with CSS instead so its
  // ResizeObserver picks up the dimension change and calls map.resize() on show.
  const isMapView = activeViewMode === "map" || activeViewMode === "explore" || activeViewMode === "satellite";

  return (
    <div className="center-canvas">
      <ViewTabs />
      <div className="center-canvas-body">
        {/* Map layer — always mounted, shown only on map-like views */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: isMapView ? "block" : "none",
          }}
        >
          {children}
        </div>

        {activeViewMode === "table" && <DataTableView />}
        {activeViewMode === "chart" && <ChartView />}
        {activeViewMode === "dashboard" && (dashboardView || (
          <Suspense fallback={<ViewLoading />}>
            <MissionControl
              onSelectProject={(pid) => window.dispatchEvent(new CustomEvent("princeps-set-view", { detail: { view: "projects", projectId: pid } }))}
              onNewProject={() => window.dispatchEvent(new CustomEvent("princeps-set-view", { detail: { view: "projects" } }))}
              onPickWorkload={(w) => window.dispatchEvent(new CustomEvent("princeps-set-view", { detail: { view: "projects", workload: w } }))}
            />
          </Suspense>
        ))}
        {activeViewMode === "projects" && (
          <Suspense fallback={<ViewLoading />}><RedesignLayout mapSlot={children} /></Suspense>
        )}
        {activeViewMode === "curtailment" && <CurtailmentBrowser />}
        {activeViewMode === "pulse" && (
          <Suspense fallback={<ViewLoading />}><PulseWorkspace /></Suspense>
        )}
        {activeViewMode === "dc_connection" && (
          <Suspense fallback={<ViewLoading />}><DCHyperscalerPanel /></Suspense>
        )}
        {activeViewMode === "neso098" && (
          <Suspense fallback={<ViewLoading />}><NESO098Workspace /></Suspense>
        )}
        {activeViewMode === "grid_graph" && (
          <Suspense fallback={<ViewLoading />}>
            <GridGraphContainer mapContent={children} />
          </Suspense>
        )}
        {activeViewMode === "dc_twin" && (
          <Suspense fallback={<ViewLoading />}><DCPhysicalTwin /></Suspense>
        )}

        {activeViewMode === "network" && (
          <Suspense fallback={<ViewLoading />}><GridNetworkView /></Suspense>
        )}
        {activeViewMode === "circuit" && (
          <Suspense fallback={<ViewLoading />}><GridCircuitView /></Suspense>
        )}
        {activeViewMode === "data" && (
          <Suspense fallback={<ViewLoading />}><GridTablePlusView /></Suspense>
        )}
        {activeViewMode === "forecast" && (
          <Suspense fallback={<ViewLoading />}><GSPExplorerView /></Suspense>
        )}
        {activeViewMode === "compare" && (
          <Suspense fallback={<ViewLoading />}><GridCompareView /></Suspense>
        )}
      </div>
    </div>
  );
}

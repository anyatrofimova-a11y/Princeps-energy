import React, { lazy, Suspense } from "react";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import ViewTabs from "./ViewTabs";
import WorkspaceHome from "./WorkspaceHome";
import DataTableView from "../views/DataTableView";
import ChartView from "../views/ChartView";

// Lazy-load grid-specific views to keep bundle lean
const GridNetworkView = lazy(() => import("../grid/GridNetworkView"));
const GridCircuitView = lazy(() => import("../grid/GridCircuitView"));
const GridTablePlusView = lazy(() => import("../grid/GridTablePlusView"));
const GSPExplorerView = lazy(() => import("../grid/GSPExplorerView"));
const GridCompareView = lazy(() => import("../grid/GridCompareView"));

const ViewLoading = () => (
  <div className="view-placeholder">Loading...</div>
);

export default function CenterCanvas({ children, dashboardView }) {
  const { activeViewMode, activeWorkspace } = useWorkspace();

  return (
    <div className="center-canvas">
      <ViewTabs />
      <div className="center-canvas-body">
        {/* Shared views */}
        {activeViewMode === "map" && children}
        {activeViewMode === "table" && <DataTableView />}
        {activeViewMode === "chart" && <ChartView />}
        {activeViewMode === "dashboard" && (dashboardView || <WorkspaceHome />)}

        {/* Grid workspace: "explore" = map with enhanced grid overlays */}
        {activeViewMode === "explore" && children}

        {/* Grid workspace: lazy-loaded specialized views */}
        {activeViewMode === "network" && (
          <Suspense fallback={<ViewLoading />}>
            <GridNetworkView />
          </Suspense>
        )}
        {activeViewMode === "circuit" && (
          <Suspense fallback={<ViewLoading />}>
            <GridCircuitView />
          </Suspense>
        )}
        {activeViewMode === "data" && (
          <Suspense fallback={<ViewLoading />}>
            <GridTablePlusView />
          </Suspense>
        )}
        {activeViewMode === "forecast" && (
          <Suspense fallback={<ViewLoading />}>
            <GSPExplorerView />
          </Suspense>
        )}
        {activeViewMode === "compare" && (
          <Suspense fallback={<ViewLoading />}>
            <GridCompareView />
          </Suspense>
        )}

        {/* Feasibility satellite view (reuses map with satellite overlay) */}
        {activeViewMode === "satellite" && children}
      </div>
    </div>
  );
}

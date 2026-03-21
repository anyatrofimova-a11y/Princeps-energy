import React, { lazy, Suspense } from "react";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import ViewTabs from "./ViewTabs";
import WorkspaceHome from "./WorkspaceHome";
import DataTableView from "../views/DataTableView";
import ChartView from "../views/ChartView";

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

  // Map mode: no tab bar, map fills everything
  const isMapMode = activeViewMode === "map" || activeViewMode === "explore" || activeViewMode === "satellite";

  return (
    <div className="center-canvas">
      {/* Only show tab bar when NOT in map mode — map should fill the screen */}
      {!isMapMode && <ViewTabs />}
      <div className="center-canvas-body">
        {activeViewMode === "map" && children}
        {activeViewMode === "explore" && children}
        {activeViewMode === "satellite" && children}
        {activeViewMode === "table" && <DataTableView />}
        {activeViewMode === "chart" && <ChartView />}
        {activeViewMode === "dashboard" && (dashboardView || <WorkspaceHome />)}

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

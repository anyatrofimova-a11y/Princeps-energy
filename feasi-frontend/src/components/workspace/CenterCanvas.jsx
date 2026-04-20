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
  const { activeViewMode, setActiveViewMode } = useWorkspace();

  // Dashboard project-row clicks → open the real project page (RedesignLayout).
  // 1. Flip view mode to "projects" so RedesignLayout mounts.
  // 2. Dispatch the event RedesignLayout already listens to with projectId.
  const goToProject = React.useCallback((projectId) => {
    // Persist the pending selection so RedesignLayout can pick it up on
    // mount (the lazy-loaded Suspense fallback can take hundreds of ms, so
    // a fixed setTimeout is race-prone). RedesignLayout reads + clears
    // sessionStorage on mount.
    try { sessionStorage.setItem("princeps.pendingProjectId", String(projectId)); } catch {}
    setActiveViewMode("projects");
    // Also dispatch the event on a short and long timeout — covers warm
    // (already mounted) and cold (lazy-load) cases.
    [30, 400, 1200].forEach((ms) => setTimeout(() => {
      window.dispatchEvent(new CustomEvent("princeps-redesign-select-project", {
        detail: { projectId },
      }));
    }, ms));
  }, [setActiveViewMode]);

  const goToNewProject = React.useCallback(() => {
    try { sessionStorage.setItem("princeps.pendingNewProject", "1"); } catch {}
    setActiveViewMode("projects");
    [30, 400, 1200].forEach((ms) => setTimeout(() => {
      window.dispatchEvent(new CustomEvent("princeps-redesign-new-project"));
    }, ms));
  }, [setActiveViewMode]);

  // Dispatcher for activity-feed rows: route per entity_type so every row
  // opens a real thing — projects → project page, substations → grid view +
  // focus event, memos → project page with an intent hint the project page
  // picks up to open the IC memo tab.
  const goToEntity = React.useCallback(({ entity_type, entity_id, project_id }) => {
    if (entity_type === "substation" && entity_id) {
      setActiveViewMode("grid_network");
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent("princeps-focus-substation", {
          detail: { substationId: entity_id },
        }));
      }, 30);
      return;
    }
    if (entity_type === "memo") {
      const pid = entity_id || project_id;
      if (!pid) return;
      setActiveViewMode("projects");
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent("princeps-redesign-select-project", {
          detail: { projectId: pid, tab: "ic_memo" },
        }));
      }, 30);
      return;
    }
    // default: project
    const pid = entity_id || project_id;
    if (pid) goToProject(pid);
  }, [goToProject, setActiveViewMode]);

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
              onSelectProject={goToProject}
              onSelectEntity={goToEntity}
              onNewProject={goToNewProject}
              onPickWorkload={() => goToNewProject()}
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

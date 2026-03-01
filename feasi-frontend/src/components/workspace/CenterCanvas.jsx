import React from "react";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import ViewTabs from "./ViewTabs";
import WorkspaceHome from "./WorkspaceHome";
import DataTableView from "../views/DataTableView";
import ChartView from "../views/ChartView";

export default function CenterCanvas({ children, dashboardView }) {
  const { activeViewMode, activeWorkspace } = useWorkspace();

  return (
    <div className="center-canvas">
      <ViewTabs />
      <div className="center-canvas-body">
        {activeViewMode === "map" && children}
        {activeViewMode === "table" && <DataTableView />}
        {activeViewMode === "chart" && <ChartView />}
        {activeViewMode === "dashboard" && (dashboardView || <WorkspaceHome />)}
      </div>
    </div>
  );
}

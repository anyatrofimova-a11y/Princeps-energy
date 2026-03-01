import React from "react";
import { useWorkspace } from "../../contexts/WorkspaceContext";
import AssetBrowser from "./AssetBrowser";
import CenterCanvas from "./CenterCanvas";
import DetailPanel from "./DetailPanel";

export default function WorkspaceRouter({ mapContent, dashboardContent }) {
  const { activeWorkspace, activeViewMode } = useWorkspace();

  return (
    <div className="workspace-layout">
      <AssetBrowser />
      <CenterCanvas dashboardView={dashboardContent}>
        {mapContent}
      </CenterCanvas>
      <DetailPanel />
    </div>
  );
}
